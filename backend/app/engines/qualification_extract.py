"""从过往商务标抽取资质证照、合同、财务材料：结构优先，LLM 填字段，标题回扫。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import pymupdf as fitz
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import QualificationSourceDoc
from .. import storage
from .docx_extract import extract_paragraphs
from .legacy_doc import as_docx
from .knowledge_extract import _is_heading
from .llm import LlmError, chat_complete
from .qualification_dedup import (
    VALID_KINDS,
    apply_to_library,
    is_business_license,
    merge_candidates_in_doc,
    normalize_name,
    sha256_bytes,
)

logger = logging.getLogger(__name__)

TARGET_HEADING = re.compile(
    r"资格|资质|证照|证书|执照|许可|ISO|业绩|合同|中标通知|协议|"
    r"财务|审计|资产负|利润|纳税|社保|人员|建造师|职称|信用|"
    r"荣誉|奖状|证明材料|复印件"
)
# 扫描件/证照材料，排除「证书颁发」这类产品功能名
QUAL_DOC = re.compile(
    r"营业执照|统一社会信用代码|资质证书|资质文件|资格审查|"
    r"荣誉证书|获奖证书|奖状|合同复印件|合同扫描|中标通知|"
    r"证明材料|资格证明|资质证明|业绩证明|"
    r"ISO\s*9001|ISO\s*27001|质量管理体系认证|信息安全管理体系|"
    r"高新(技术)?企业|软件企业认定|"
    r"财务报表|审计报告|纳税证明|社保证明|"
    r"建造师证|职称证|信用中国|许可证"
)
PRODUCT_CAPABILITY = re.compile(
    r"(管理|模块|功能|平台|系统|能力|颁发|模板|查询|配置|接口|同步|下载)"
)
SKIP_HEADING = re.compile(
    r"封面|目录|投标函|授权委托|报价一览|报价表|偏离表|技术规格|功能模块|"
    r"实施方案|进度计划|质量保证体系|评分办法|评标办法|投标保证金|"
    r"廉洁承诺|保密承诺|投标人须知|招标公告"
)
TABLE_HINT = re.compile(r"证书|证照|合同|业绩|财务|审计|人员|资质|执照|信用")
CHUNK_CHARS = 2400
NUMBER_RE = re.compile(
    r"(?:证号|证书编号|编号|合同号|合同编号|统一社会信用代码)[:：\s]*([A-Za-z0-9\-]{4,})"
)
DATE_RE = re.compile(r"(?:有效期至|有效期|截止日期|报表日期|审计截止)[:：\s]*(\d{4}-\d{2}-\d{2}|长期)")
EXTRACT_SYSTEM = """你从本公司过往商务标中抽取企业资质材料。只抽取证照、人员证书、合同/业绩、财务资料、设备与信用材料。
商务标正文经常很少，材料本身就是营业执照、资质证书、合同扫描件等图片；章节标题能对应到证照时也要抽取。
不要抽取技术方案、功能点、报价。
返回 JSON 数组，每项字段：
{"name":"短名称","kind":"cert|people|achievement|equipment|credit|contract|financial","number":"证号或合同号","level":"等级","validUntil":"YYYY-MM-DD或长期","owner":"持有人/主体","detail":"原文要点","low_confidence":false}
规则：
- 营业执照全公司只有一套，名称用「营业执照」，kind=cert。
- 荣誉证书、奖状、获奖证明 kind=cert，不要写成 credit。
- 人员证书必须写 owner（持证人姓名），有证号则填 number；同名证书不同人要分开。
- 合同 kind=contract，写清合同编号与金额。
- 财务（审计报告、报表、纳税）kind=financial，必须写 validUntil（报表截止日或年度，如 2024-12-31）；过期也要抽取，不要丢弃。
- 看不清则 low_confidence=true，不要编造证号。只返回 JSON 数组。"""


def _extract_model_id() -> str:
    from .llm import get_default_model_id

    return get_default_model_id()


def looks_like_qualification(name: str, text: str = "") -> bool:
    """是否为证照/合同/财务扫描材料，而不是产品功能名。"""
    title = (name or "").strip()
    if not title:
        return False
    blob = f"{title} {(text or '')[:160]}"
    if QUAL_DOC.search(blob):
        return True
    if PRODUCT_CAPABILITY.search(title):
        return False
    return bool(re.search(r"(证书|执照|合同复印件)$", title))


def _looks_product_capability(heading: str) -> bool:
    title = heading or ""
    if looks_like_qualification(title):
        return False
    return bool(PRODUCT_CAPABILITY.search(title))


def _looks_boilerplate(heading: str) -> bool:
    return bool(SKIP_HEADING.search(heading or ""))


def _looks_target(heading: str, text: str = "") -> bool:
    if _looks_product_capability(heading):
        return False
    blob = f"{heading} {text[:80]}"
    return bool(TARGET_HEADING.search(blob)) or looks_like_qualification(heading, text)


def _guess_kind(heading: str, text: str = "") -> str:
    blob = f"{heading} {text}"
    if is_business_license(heading, "", text) or re.search(r"资质|许可|ISO|认证", blob):
        if re.search(r"建造师|安全员|职称|人员", blob):
            return "people"
        return "cert"
    if re.search(r"信用中国|失信|信用报告", blob):
        return "credit"
    if re.search(r"荣誉|奖状|获奖", blob):
        return "cert"
    if re.search(r"财务|审计|资产负|利润|纳税", blob):
        return "financial"
    if re.search(r"合同|协议", blob):
        return "contract"
    if re.search(r"业绩|中标通知", blob):
        return "achievement"
    if re.search(r"设备|机具", blob):
        return "equipment"
    if re.search(r"信用", blob):
        return "credit"
    if re.search(r"建造师|安全员|职称|身份证|人员", blob):
        return "people"
    return "cert"


def _blip_blobs(element, document) -> list[tuple[bytes, str]]:
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out: list[tuple[bytes, str]] = []
    for blip in element.findall(f".//{ns}blip"):
        embed = blip.get(f"{rns}embed")
        if not embed:
            continue
        try:
            part = document.part.related_parts[embed]
            blob = part.blob
            ctype = (part.content_type or "").lower()
        except Exception:
            continue
        if not blob or len(blob) < 8192:
            continue
        if "wmf" in ctype or "emf" in ctype:
            continue
        ext = ".png"
        if "jpeg" in ctype or "jpg" in ctype:
            ext = ".jpg"
        elif "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        out.append((blob, ext))
    return out


def _image_dict(blob: bytes, ext: str, heading: str) -> dict:
    caption = heading if heading not in ("全文", "") else "证照扫描件"
    return {
        "blob": blob,
        "ext": ext,
        "caption": caption[:40],
        "heading": heading,
        "sha256": sha256_bytes(blob),
    }


def extract_docx_qual_blocks(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    blocks: list[dict] = []
    expected: list[dict] = []
    images: list[dict] = []
    current_heading = "全文"
    current_texts: list[str] = []

    def flush_section() -> None:
        text = "\n".join(current_texts).strip()
        if not text or _looks_boilerplate(current_heading):
            return
        if current_heading != "全文" and not _looks_target(current_heading, text):
            return
        if current_heading == "全文" and not _looks_target(current_heading, text):
            return
        blocks.append({"heading": current_heading, "text": text})
        if len(current_heading) <= 40 and current_heading not in ("全文",) and _looks_target(current_heading, text):
            expected.append({"heading": current_heading, "text": text[:800], "kind": "heading"})

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            for blob, ext in _blip_blobs(child, document):
                images.append(_image_dict(blob, ext, current_heading))
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name if para.style is not None else ""
            try:
                outline_level = para.paragraph_format.outline_level
            except Exception:
                outline_level = None
            if _is_heading(style_name, outline_level):
                flush_section()
                current_heading = text[:80]
                current_texts = []
            else:
                current_texts.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows: list[list[str]] = []
            for row in table.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(cells)
            heading = current_heading
            for blob, ext in _blip_blobs(child, document):
                images.append(_image_dict(blob, ext, heading))
            if not rows:
                continue
            header = " ".join(rows[0])
            table_text = "\n".join(" | ".join(r) for r in rows)
            if TABLE_HINT.search(header) or TABLE_HINT.search(heading) or _looks_target(heading, header):
                blocks.append({"heading": heading, "text": table_text[:CHUNK_CHARS]})
                for row in rows[1:]:
                    name = row[0][:40]
                    if name and not _looks_boilerplate(name):
                        expected.append(
                            {
                                "heading": name,
                                "text": " | ".join(row)[:800],
                                "kind": "table",
                            }
                        )
            else:
                current_texts.append(table_text)

    flush_section()
    if not blocks:
        paras = extract_paragraphs(path)
        blob = "\n".join(p["text"] for p in paras)
        if blob.strip():
            blocks.append({"heading": "全文", "text": blob[:8000]})
    return blocks, expected, images


def extract_pdf_qual_blocks(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    blocks: list[dict] = []
    expected: list[dict] = []
    images: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            heading = f"第 {i} 页"
            text = page.get_text("text").strip()
            image_only = len(text) < 20
            if image_only:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                blob = pix.tobytes("png")
                if len(blob) >= 8192:
                    images.append(_image_dict(blob, ".png", heading))
            elif not (_looks_boilerplate(text[:40]) and not _looks_target(text[:80], text)):
                if _looks_target(heading, text) or TARGET_HEADING.search(text[:400]):
                    blocks.append({"heading": heading, "text": text[:CHUNK_CHARS]})
                    for line in text.splitlines():
                        line = line.strip()
                        if 4 <= len(line) <= 40 and _looks_target(line):
                            expected.append({"heading": line, "text": line, "kind": "heading"})
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue
                blob = extracted.get("image") or b""
                if len(blob) < 8192:
                    continue
                ext = f".{(extracted.get('ext') or 'png').lower()}"
                if ext in (".wmf", ".emf"):
                    continue
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    ext = ".png"
                images.append(_image_dict(blob, ext, heading))
    return blocks, expected, images


def _parse_json_array(content: str) -> list[dict]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        for key in ("items", "assets", "features"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _regex_fields(text: str) -> tuple[str, str]:
    number = ""
    valid_until = ""
    num_match = NUMBER_RE.search(text or "")
    if num_match:
        number = num_match.group(1)[:80]
    date_match = DATE_RE.search(text or "")
    if date_match:
        valid_until = date_match.group(1)
    return number, valid_until


def _fallback_from_block(block: dict) -> list[dict]:
    heading = (block.get("heading") or "").strip()
    text = (block.get("text") or "").strip()
    if not heading or heading in ("全文",) or _looks_boilerplate(heading):
        return []
    if not _looks_target(heading, text):
        return []
    number, valid_until = _regex_fields(text)
    kind = _guess_kind(heading, text)
    if kind == "financial" and not valid_until:
        year = re.search(r"(20\d{2})", heading + text)
        if year:
            valid_until = f"{year.group(1)}-12-31"
    return [
        {
            "name": heading[:40],
            "kind": kind,
            "number": number,
            "level": "",
            "validUntil": valid_until or "长期",
            "owner": "",
            "detail": text[:800],
            "evidence": [{"heading": heading, "excerpt": text[:300]}],
            "images": [],
            "low_confidence": True,
        }
    ]


def _llm_fill_block(block: dict) -> list[dict]:
    heading = block.get("heading") or ""
    text = (block.get("text") or "")[:CHUNK_CHARS]
    if not text.strip():
        return []
    user = f"章节标题：{heading}\n\n正文：\n{text}"
    try:
        content = chat_complete(
            model_id=_extract_model_id(),
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            timeout=60,
            max_tokens=1800,
        )
        rows = _parse_json_array(content)
    except LlmError:
        rows = []
    except Exception:
        logger.exception("qualification extract llm failed for %s", heading)
        rows = []
    if not rows:
        return _fallback_from_block(block)
    out: list[dict] = []
    for row in rows:
        name = (row.get("name") or "").strip()[:40] or heading[:40]
        if _looks_boilerplate(name):
            continue
        kind = row.get("kind") if row.get("kind") in VALID_KINDS else _guess_kind(name, text)
        if re.search(r"荣誉|奖状|获奖", name) and kind == "credit":
            kind = "cert"
        valid_until = (row.get("validUntil") or "").strip() or "长期"
        if kind == "financial" and valid_until in ("", "长期"):
            year = re.search(r"(20\d{2})", name + text)
            if year:
                valid_until = f"{year.group(1)}-12-31"
        out.append(
            {
                "name": name,
                "kind": kind,
                "number": (row.get("number") or "").strip()[:80],
                "level": (row.get("level") or "").strip()[:80],
                "validUntil": valid_until,
                "owner": (row.get("owner") or "").strip()[:80],
                "detail": (row.get("detail") or "").strip()[:800],
                "evidence": [{"heading": heading, "excerpt": text[:300]}],
                "images": [],
                "low_confidence": bool(row.get("low_confidence")),
            }
        )
    return out or _fallback_from_block(block)


def _coverage_fill(expected: list[dict], candidates: list[dict]) -> list[dict]:
    have = {normalize_name(c.get("name") or "") for c in candidates}
    extra: list[dict] = []
    for row in expected:
        heading = (row.get("heading") or "").strip()
        key = normalize_name(heading)
        if not key or key in have:
            continue
        extra.extend(_fallback_from_block({"heading": heading, "text": row.get("text") or ""}))
        have.add(key)
    return extra


def _heading_matches(heading: str, name: str) -> bool:
    heading, name = (heading or "").strip(), (name or "").strip()
    if not heading or not name:
        return False
    return heading == name or name in heading or heading in name


def _attach_images(candidates: list[dict], images: list[dict]) -> list[dict]:
    if not images:
        return []
    unused = list(images)
    for cand in candidates:
        name = cand.get("name") or ""
        headings = {name}
        for ev in cand.get("evidence") or []:
            if ev.get("heading"):
                headings.add(ev["heading"])
        matched: list[dict] = []
        rest: list[dict] = []
        for img in unused:
            heading = img.get("heading") or ""
            if any(_heading_matches(heading, h) for h in headings if h):
                matched.append(img)
            else:
                rest.append(img)
        cand["images"] = (cand.get("images") or []) + matched
        unused = rest
    return unused


def _candidates_from_orphan_images(images: list[dict]) -> list[dict]:
    if not images:
        return []
    from .ocr import ocr_image_bytes

    grouped: dict[str, list[dict]] = {}
    for img in images:
        heading = img.get("heading") or "证照扫描件"
        grouped.setdefault(heading, []).append(img)
    extra: list[dict] = []
    page_re = re.compile(r"^第\s*\d+\s*页")
    for heading, imgs in grouped.items():
        if _looks_boilerplate(heading):
            continue
        is_page = bool(page_re.match(heading))
        if not _looks_target(heading) and not is_page and heading != "全文":
            continue
        ocr_parts: list[str] = []
        for img in imgs[:3]:
            blob = img.get("blob") or b""
            if not blob:
                continue
            text, _status = ocr_image_bytes(blob)
            if text:
                ocr_parts.append(text)
        ocr_text = "\n".join(ocr_parts)
        name = heading[:40] if heading not in ("全文",) else "证照扫描件"
        if ocr_text:
            if is_business_license(ocr_text, "", ocr_text):
                name = "营业执照"
            elif is_page:
                first_line = next(
                    (ln.strip() for ln in ocr_text.splitlines() if 2 <= len(ln.strip()) <= 24),
                    "",
                )
                if first_line:
                    name = first_line[:40]
        number, valid_until = _regex_fields(ocr_text)
        extra.append(
            {
                "name": name,
                "kind": _guess_kind(name, ocr_text or heading),
                "number": number,
                "level": "",
                "validUntil": valid_until or "长期",
                "owner": "",
                "detail": (ocr_text or heading)[:800],
                "evidence": [{"heading": heading, "excerpt": (ocr_text or "扫描件")[:300]}],
                "images": imgs,
                "low_confidence": True,
            }
        )
    return extra


def extract_candidates(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        blocks, expected, images = extract_pdf_qual_blocks(path)
    else:
        with as_docx(path) as word_path:
            blocks, expected, images = extract_docx_qual_blocks(word_path)

    candidates: list[dict] = []
    for block in blocks:
        heading = block.get("heading") or ""
        if _looks_boilerplate(heading) and not _looks_target(heading, block.get("text") or ""):
            continue
        candidates.extend(_llm_fill_block(block))
    candidates.extend(_coverage_fill(expected, candidates))
    unused = _attach_images(candidates, images)
    candidates.extend(_candidates_from_orphan_images(unused))
    return merge_candidates_in_doc(candidates)


def run_extract_for_source_doc(db: Session, source_doc_id: str) -> None:
    doc = db.get(QualificationSourceDoc, source_doc_id)
    if not doc:
        return
    doc.status = "running"
    doc.note = "正在抽取资质图片、证照与合同…"
    db.commit()
    try:
        if not doc.storage_path or not storage.exists(doc.storage_path):
            raise RuntimeError("源文件不存在")
        with storage.as_local(doc.storage_path) as path:
            candidates = extract_candidates(path)
        stats = apply_to_library(db, doc, candidates)
        doc.extracted = stats["extracted"]
        doc.merged = stats["merged"]
        doc.suspected = stats["suspected"]
        doc.conflicts = stats["conflicts"]
        doc.status = "done"
        doc.note = (
            f"新增 {stats['extracted']}，并入 {stats['merged']}，"
            f"疑似 {stats['suspected']}，信息冲突 {stats['conflicts']}，请审核"
        )
        doc.error = None
        doc.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("qualification extract %s failed", source_doc_id)
        doc = db.get(QualificationSourceDoc, source_doc_id)
        if doc:
            doc.status = "failed"
            doc.error = str(exc)
            doc.note = "抽取失败"
            doc.finished_at = datetime.utcnow()
            db.commit()
        raise
