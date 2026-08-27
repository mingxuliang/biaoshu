"""从过往技术标抽取产品功能点：本地结构优先，LLM 填字段，未覆盖标题回扫。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import pymupdf as fitz
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ProductSourceDoc
from .. import storage
from .legacy_doc import as_docx
from .docx_extract import extract_paragraphs
from .knowledge_extract import _is_heading
from .llm import LlmError, chat_complete
from .product_dedup import apply_to_library, merge_candidates_in_doc, sha256_bytes

logger = logging.getLogger(__name__)

SKIP_HEADING = re.compile(
    r"封面|目录|投标函|授权委托|报价一览|报价表|偏离表|资格审查|业绩一览|"
    r"人员简历|身份证|资质证书|营业执照|财务报表|进度计划|质量保证体系|"
    r"安全文明|评分办法|评标办法|投标保证金|法定代表人|廉洁承诺|保密承诺|"
    r"投标人须知|招标公告"
)
TABLE_HINT = re.compile(r"功能|模块|能力|参数|规格|配置|清单")
CHUNK_CHARS = 2400
EXTRACT_SYSTEM = """你从本公司过往技术标中抽取产品功能点。只抽取产品能力，不要商务套话、资质、报价、人员。
返回 JSON 数组，每项字段：
{"name":"短名称不超过16字","module":"所属模块","kind":"软件功能|货物产品|模块方案","params":"原文中的技术参数，没有则空","intro":"根据原文改写的能力说明","bidCopy":"可用于投标的能力陈述","brand":"","model":"","unit":"","low_confidence":false}
禁止编造原文没有的数字和能力。看不清则 params 留空并 low_confidence=true。只返回 JSON 数组。"""


def _extract_model_id() -> str:
    settings = get_settings()
    if settings.ark_api_key:
        return "doubao"
    return "deepseek-v4-flash"


def _looks_boilerplate(heading: str) -> bool:
    return bool(SKIP_HEADING.search(heading or ""))


def _guess_image_kind(caption: str) -> str:
    text = (caption or "").lower()
    if re.search(r"架构|architecture|topo|部署", text):
        return "架构"
    if re.search(r"流程|flow|bpmn", text):
        return "流程"
    if re.search(r"实物|设备|服务器|机柜|hardware", text):
        return "实物"
    return "界面"


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


def extract_docx_product_blocks(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (blocks, expected, images)。blocks 供 LLM；expected 做覆盖回扫。"""
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
        blocks.append({"heading": current_heading, "text": text})
        if len(current_heading) <= 24 and current_heading not in ("全文",):
            expected.append({"heading": current_heading, "text": text[:800], "kind": "heading"})

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            for blob, ext in _blip_blobs(child, document):
                digest = sha256_bytes(blob)
                caption = current_heading if current_heading != "全文" else "原文附图"
                images.append(
                    {
                        "blob": blob,
                        "ext": ext,
                        "caption": caption[:40],
                        "kind": _guess_image_kind(caption),
                        "heading": current_heading,
                        "sha256": digest,
                    }
                )
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
            if not rows:
                continue
            header = " ".join(rows[0])
            table_text = "\n".join(" | ".join(r) for r in rows)
            heading = current_heading
            if TABLE_HINT.search(header) or TABLE_HINT.search(heading):
                blocks.append({"heading": heading, "text": table_text[:CHUNK_CHARS]})
                for row in rows[1:]:
                    name = row[0][:24]
                    if name and not _looks_boilerplate(name):
                        expected.append(
                            {
                                "heading": name,
                                "text": " | ".join(row)[:800],
                                "kind": "table",
                                "module": heading,
                            }
                        )
            else:
                current_texts.append(table_text)
            for blob, ext in _blip_blobs(child, document):
                digest = sha256_bytes(blob)
                images.append(
                    {
                        "blob": blob,
                        "ext": ext,
                        "caption": heading[:40] or "原文附图",
                        "kind": _guess_image_kind(heading),
                        "heading": heading,
                        "sha256": digest,
                    }
                )

    flush_section()
    if not blocks:
        paras = extract_paragraphs(path)
        blob = "\n".join(p["text"] for p in paras)
        if blob.strip():
            blocks.append({"heading": "全文", "text": blob[:8000]})
    return blocks, expected, images


def extract_pdf_product_blocks(path: str) -> tuple[list[dict], list[dict], list[dict]]:
    blocks: list[dict] = []
    expected: list[dict] = []
    images: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            heading = f"第 {i} 页"
            text = page.get_text("text").strip()
            if len(text) >= 20 and not _looks_boilerplate(text[:40]):
                blocks.append({"heading": heading, "text": text[:CHUNK_CHARS]})
                for line in text.splitlines():
                    line = line.strip()
                    if 4 <= len(line) <= 16 and not _looks_boilerplate(line):
                        expected.append({"heading": line, "text": line, "kind": "heading"})
            else:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                blob = pix.tobytes("png")
                if len(blob) >= 8192:
                    images.append(
                        {
                            "blob": blob,
                            "ext": ".png",
                            "caption": heading,
                            "kind": "界面",
                            "heading": heading,
                            "sha256": sha256_bytes(blob),
                        }
                    )
            for img in page.get_images(full=True)[:12]:
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
                images.append(
                    {
                        "blob": blob,
                        "ext": ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png",
                        "caption": heading,
                        "kind": "界面",
                        "heading": heading,
                        "sha256": sha256_bytes(blob),
                    }
                )
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
    if isinstance(data, dict) and isinstance(data.get("features"), list):
        data = data["features"]
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _fallback_from_block(block: dict) -> list[dict]:
    heading = (block.get("heading") or "待命名功能点").strip()[:16]
    text = (block.get("text") or "").strip()
    if _looks_boilerplate(heading) or heading in ("全文",):
        return []
    return [
        {
            "name": heading,
            "module": "",
            "kind": "软件功能",
            "params": "",
            "intro": text[:400],
            "bidCopy": "",
            "brand": "",
            "model": "",
            "unit": "",
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
        logger.exception("product extract llm failed for %s", heading)
        rows = []
    if not rows:
        return _fallback_from_block(block)
    out: list[dict] = []
    for row in rows:
        name = (row.get("name") or "").strip()[:16] or heading[:16]
        if _looks_boilerplate(name):
            continue
        out.append(
            {
                "name": name,
                "module": (row.get("module") or heading)[:80],
                "kind": row.get("kind") if row.get("kind") in ("软件功能", "货物产品", "模块方案") else "软件功能",
                "params": (row.get("params") or "").strip()[:800],
                "intro": (row.get("intro") or "").strip()[:800],
                "bidCopy": (row.get("bidCopy") or "").strip()[:800],
                "brand": (row.get("brand") or "").strip()[:40],
                "model": (row.get("model") or "").strip()[:40],
                "unit": (row.get("unit") or "").strip()[:20],
                "evidence": [{"heading": heading, "excerpt": text[:300]}],
                "images": [],
                "low_confidence": bool(row.get("low_confidence")),
            }
        )
    return out or _fallback_from_block(block)


def _attach_images(candidates: list[dict], images: list[dict]) -> None:
    if not images:
        return
    unused = list(images)
    for cand in candidates:
        name = cand.get("name") or ""
        module = cand.get("module") or ""
        matched: list[dict] = []
        rest: list[dict] = []
        for img in unused:
            heading = img.get("heading") or ""
            if heading and (heading == name or heading == module or name in heading or heading in name):
                matched.append(img)
            else:
                rest.append(img)
        cand["images"] = (cand.get("images") or []) + matched[:4]
        unused = rest
    if unused and candidates:
        by_heading: dict[str, list[dict]] = {}
        for img in unused:
            by_heading.setdefault(img.get("heading") or "", []).append(img)
        for cand in candidates:
            heading = cand.get("module") or cand.get("name") or ""
            extra = by_heading.pop(heading, [])
            if extra:
                cand["images"] = (cand.get("images") or []) + extra[:4]


def _coverage_fill(expected: list[dict], candidates: list[dict]) -> list[dict]:
    from .product_dedup import normalize_name

    have = {normalize_name(c.get("name") or "") for c in candidates}
    extra: list[dict] = []
    for row in expected:
        heading = (row.get("heading") or "").strip()
        key = normalize_name(heading)
        if not key or key in have:
            continue
        extra.append(
            {
                "name": heading[:16],
                "module": (row.get("module") or "")[:80],
                "kind": "软件功能",
                "params": "",
                "intro": (row.get("text") or "")[:400],
                "bidCopy": "",
                "brand": "",
                "model": "",
                "unit": "",
                "evidence": [{"heading": heading, "excerpt": (row.get("text") or "")[:300]}],
                "images": [],
                "low_confidence": True,
            }
        )
        have.add(key)
    return extra


def extract_candidates(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        blocks, expected, images = extract_pdf_product_blocks(path)
    else:
        with as_docx(path) as word_path:
            blocks, expected, images = extract_docx_product_blocks(word_path)

    candidates: list[dict] = []
    for block in blocks:
        if _looks_boilerplate(block.get("heading") or ""):
            continue
        candidates.extend(_llm_fill_block(block))
    candidates.extend(_coverage_fill(expected, candidates))
    candidates = merge_candidates_in_doc(candidates)
    _attach_images(candidates, images)
    return candidates


def run_extract_for_source_doc(db: Session, source_doc_id: str) -> None:
    doc = db.get(ProductSourceDoc, source_doc_id)
    if not doc:
        return
    doc.status = "running"
    doc.note = "正在抽取功能点与附图…"
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
            f"疑似 {stats['suspected']}，参数冲突 {stats['conflicts']}，请审核"
        )
        doc.error = None
        doc.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("product extract %s failed", source_doc_id)
        doc = db.get(ProductSourceDoc, source_doc_id)
        if doc:
            doc.status = "failed"
            doc.error = str(exc)
            doc.note = "抽取失败"
            doc.finished_at = datetime.utcnow()
            db.commit()
        raise
