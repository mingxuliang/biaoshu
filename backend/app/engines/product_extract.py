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
from ..models import ProductFeature, ProductSourceDoc, QualificationSourceDoc
from .. import storage
from .legacy_doc import as_docx
from .docx_extract import extract_paragraphs
from .knowledge_extract import _is_heading
from .llm import LlmError, chat_complete
from .product_dedup import apply_to_library, merge_candidates_in_doc, sha256_bytes
from .qualification_extract import looks_like_qualification

logger = logging.getLogger(__name__)

SKIP_HEADING = re.compile(
    r"封面|目录|投标函|授权委托|报价一览|报价表|偏离表|资格审查|业绩一览|"
    r"人员简历|身份证|资质证书|营业执照|财务报表|进度计划|质量保证体系|"
    r"安全文明|评分办法|评标办法|投标保证金|法定代表人|廉洁承诺|保密承诺|"
    r"投标人须知|招标公告|荣誉证书|合同复印件|证明材料|中标通知|"
    r"工作量|人天|实施计划|进度安排|项目实施"
)
HEADING_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)(?:\s*[、.．:：]?\s*)(.*)$")
HEADING_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、\s*(.+)$")
WRAPPER_HEADING = re.compile(r"响应演示|核心功能演示|功能清单|建设内容|技术方案$|平台概述|目录")
JUNK_FEATURE_NAME = re.compile(
    r"合计|小计|总计|序号|金额|备注|数量|工作量|人天|通过时光|基本全部|应当满足"
)
CHUNK_CHARS = 2400
JUDGE_SYSTEM = """你在阅读本公司过往技术标，只为「产品功能库」收录真正的产品能力。

算作功能点：软件/平台可投标的功能菜单或子功能，例如培训管理、签到方式、证书颁发、学习档案、任务推送。
不算功能点：项目实施、工作量、人天、进度、报价、合计、表头、目录、商务套话、资质证照、合同、荣誉、人员、纯数字、句子片段、需求符合性空话、把表格一行当功能。

先判断本章是不是产品功能。
- 不是：返回 [{"isFeature":false}]
- 是：只返回一项 [{"isFeature":true,"level":"一级或二级","name":"不超过16字短名","module":"所属一级功能菜单","kind":"软件功能","params":"原文技术参数没有则空","intro":"根据原文改写的能力说明","bidCopy":"一两句投标可用陈述"}]

name 必须是功能短名，禁止整句、禁止合计/序号/数字。intro 和 bidCopy 不要粘贴表格、不要重复标题。禁止编造原文没有的能力。只返回 JSON 数组。"""


def _extract_model_id() -> str:
    from .llm import get_default_model_id

    return get_default_model_id()


def _clean_heading(text: str) -> str:
    t = (text or "").strip()
    m = HEADING_DOTTED.match(t)
    if m:
        rest = (m.group(2) or "").strip()
        return rest[:40] if rest else t[:40]
    m = HEADING_CN_DOT.match(t)
    if m:
        return (m.group(2) or t).strip()[:40]
    t = re.sub(r"^第[0-9一二三四五六七八九十]+[章节篇]\s*", "", t)
    return t[:40]


def _heading_depth(style_name: str, outline_level, text: str) -> int | None:
    raw = (text or "").strip()
    m = HEADING_DOTTED.match(raw)
    if m:
        first = int(m.group(1).split(".", 1)[0])
        if first <= 40:
            return m.group(1).count(".") + 1
    style = (style_name or "").lower()
    if style.startswith("heading"):
        digits = "".join(ch for ch in style if ch.isdigit())
        if digits:
            return max(1, min(int(digits), 9))
        return 1
    if isinstance(outline_level, int) and 0 <= outline_level <= 8:
        return outline_level + 1
    if HEADING_CN_DOT.match(raw) and style.startswith("heading"):
        return 2
    if _is_heading(style_name, outline_level):
        return 2
    return None


def _looks_boilerplate(heading: str) -> bool:
    return bool(SKIP_HEADING.search(heading or "")) or looks_like_qualification(heading or "")


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
    current_depth = 1
    current_texts: list[str] = []

    def flush_section() -> None:
        text = "\n".join(current_texts).strip()
        if _looks_boilerplate(current_heading):
            return
        if current_heading in ("全文",) and not text:
            return
        blocks.append({"heading": current_heading, "text": text, "depth": current_depth})

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = para.text.strip()
            style_name = para.style.name if para.style is not None else ""
            try:
                outline_level = para.paragraph_format.outline_level
            except Exception:
                outline_level = None
            if text and _heading_depth(style_name, outline_level, text) is not None:
                flush_section()
                current_heading = text[:80]
                current_depth = _heading_depth(style_name, outline_level, text) or 2
                current_texts = []
            elif text:
                current_texts.append(text)
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
            table_text = "\n".join(" | ".join(r) for r in rows)
            heading = current_heading
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


def _parse_json_object(content: str) -> dict:
    rows = _parse_json_array(content)
    if rows:
        return rows[0]
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _bad_feature_name(name: str) -> bool:
    n = (name or "").strip()
    if not n or n in ("全文",) or _looks_boilerplate(n):
        return True
    if re.fullmatch(r"[\d.]+", n):
        return True
    if JUNK_FEATURE_NAME.search(n):
        return True
    if len(n) > 18:
        return True
    return False


def _clean_copy(text: str) -> str:
    t = (text or "").strip()
    if t.count("|") >= 2:
        parts = [p.strip() for p in t.split("|") if p.strip()]
        if len(parts) >= 2 and len(set(parts)) == 1:
            return parts[0][:800]
    return t[:800]


def _llm_judge_section(node: dict, parent_name: str) -> dict | None:
    heading = (node.get("heading") or node.get("name") or "").strip()
    name = (node.get("name") or _clean_heading(heading)).strip()
    if not heading or heading == "全文" or _looks_boilerplate(heading) or _looks_boilerplate(name):
        return None
    if WRAPPER_HEADING.search(f"{name} {heading}"):
        return None
    if _bad_feature_name(name) and not (node.get("children") or []):
        return None
    text = (node.get("text") or "").strip()[:CHUNK_CHARS]
    child_titles = "、".join(
        (c.get("name") or _clean_heading(c.get("heading") or ""))[:16]
        for c in (node.get("children") or [])[:20]
        if c.get("name") or c.get("heading")
    )
    user = (
        f"上级菜单：{parent_name or '无'}\n"
        f"本章标题：{heading}\n"
        f"下级标题：{child_titles or '无'}\n\n"
        f"正文：\n{text or '（无正文，仅标题）'}"
    )
    try:
        content = chat_complete(
            model_id=_extract_model_id(),
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0,
            timeout=60,
            max_tokens=900,
        )
        row = _parse_json_object(content)
    except LlmError:
        return None
    except Exception:
        logger.exception("product feature judge failed for %s", heading)
        return None
    if not row or row.get("isFeature") is False or str(row.get("isFeature")).lower() in ("false", "0"):
        return None
    feat_name = (row.get("name") or name).strip()[:16]
    if _bad_feature_name(feat_name):
        return None
    level = row.get("level") if row.get("level") in ("一级", "二级") else ("二级" if parent_name else "一级")
    intro = _clean_copy(row.get("intro") or "")
    bid = _clean_copy(row.get("bidCopy") or intro)
    return {
        "name": feat_name,
        "module": (row.get("module") or parent_name or feat_name)[:80],
        "kind": row.get("kind") if row.get("kind") in ("软件功能", "货物产品", "模块方案") else "软件功能",
        "params": (row.get("params") or "").strip()[:800],
        "intro": intro,
        "bidCopy": bid,
        "brand": "",
        "model": "",
        "unit": "",
        "evidence": [{"heading": heading, "excerpt": text[:300]}] if text else [],
        "images": [],
        "low_confidence": bool(row.get("low_confidence")),
        "level": level,
        "sourceHeading": heading,
        "children": [],
    }


def _walk_candidates_leaves_first(candidates: list[dict]):
    for cand in candidates:
        yield from _walk_candidates_leaves_first(cand.get("children") or [])
        yield cand


def _image_belongs_to(cand: dict, img: dict) -> bool:
    heading = (img.get("heading") or "").strip()
    if not heading:
        return False
    clean = _clean_heading(heading)
    name = (cand.get("name") or "").strip()
    source = (cand.get("sourceHeading") or "").strip()
    if source and (heading == source or clean == _clean_heading(source)):
        return True
    if name and (clean == name or heading == name or name == source):
        return True
    if name and len(name) >= 2 and name in heading:
        return True
    return False


def _attach_images(candidates: list[dict], images: list[dict]) -> None:
    if not images:
        return
    unused = [img for img in images if not looks_like_qualification(img.get("heading") or "")]
    for cand in _walk_candidates_leaves_first(candidates):
        matched: list[dict] = []
        rest: list[dict] = []
        for img in unused:
            if _image_belongs_to(cand, img):
                matched.append(img)
            else:
                rest.append(img)
        cand["images"] = (cand.get("images") or []) + matched
        unused = rest
    if unused:
        by_heading: dict[str, list[dict]] = {}
        for img in unused:
            key = _clean_heading(img.get("heading") or "") or (img.get("heading") or "")
            by_heading.setdefault(key, []).append(img)
        for cand in _walk_candidates_leaves_first(candidates):
            heading = cand.get("name") or cand.get("sourceHeading") or cand.get("module") or ""
            extra = by_heading.pop(_clean_heading(heading), []) or by_heading.pop(heading, [])
            if extra:
                cand["images"] = (cand.get("images") or []) + extra


def _build_heading_tree(blocks: list[dict]) -> list[dict]:
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for block in blocks:
        heading = (block.get("heading") or "").strip()
        if not heading or heading == "全文":
            continue
        depth = int(block.get("depth") or 2)
        node = {
            "heading": heading,
            "name": _clean_heading(heading),
            "text": block.get("text") or "",
            "depth": depth,
            "children": [],
        }
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((depth, node))
    return roots


def _is_wrapper_node(node: dict) -> bool:
    title = f"{node.get('name') or ''} {node.get('heading') or ''}"
    return bool(WRAPPER_HEADING.search(title))


def _judge_heading_tree(nodes: list[dict], parent_name: str = "") -> list[dict]:
    from .product_dedup import normalize_name

    judged: list[tuple[dict, str, dict | None]] = []

    def walk(items: list[dict], parent: str) -> None:
        for node in items:
            title = node.get("name") or ""
            feat = None
            if not _looks_boilerplate(title) and not _is_wrapper_node(node):
                feat = _llm_judge_section(node, parent)
            judged.append((node, parent, feat))
            next_parent = feat["name"] if feat and feat.get("level") != "二级" else parent
            walk(node.get("children") or [], next_parent)

    walk(nodes, parent_name)

    menus: list[dict] = []
    by_name: dict[str, dict] = {}
    for node, parent, feat in judged:
        if not feat or feat.get("level") == "二级":
            continue
        feat["sourceHeading"] = node.get("heading") or feat.get("sourceHeading") or ""
        feat["children"] = []
        menus.append(feat)
        key = normalize_name(feat["name"])
        if key:
            by_name[key] = feat

    for node, parent, feat in judged:
        if not feat or feat.get("level") != "二级":
            continue
        feat["sourceHeading"] = node.get("heading") or feat.get("sourceHeading") or ""
        feat["children"] = []
        host = by_name.get(normalize_name(feat.get("module") or "")) or by_name.get(normalize_name(parent))
        if host:
            feat["module"] = host["name"]
            host.setdefault("children", []).append(feat)
        else:
            feat["level"] = "一级"
            feat["module"] = feat["name"]
            menus.append(feat)
            key = normalize_name(feat["name"])
            if key:
                by_name[key] = feat
    return menus


def _judge_flat_blocks(blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        node = {
            "heading": block.get("heading") or "",
            "name": _clean_heading(block.get("heading") or ""),
            "text": block.get("text") or "",
            "children": [],
        }
        feat = _llm_judge_section(node, "")
        if not feat:
            continue
        feat["level"] = "一级"
        feat["children"] = []
        feat["sourceHeading"] = node["heading"]
        out.append(feat)
    return out


def extract_candidates(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        blocks, _expected, images = extract_pdf_product_blocks(path)
    else:
        with as_docx(path) as word_path:
            blocks, _expected, images = extract_docx_product_blocks(word_path)

    has_depth = any(isinstance(block.get("depth"), int) for block in blocks)
    if has_depth:
        candidates = _judge_heading_tree(_build_heading_tree(blocks))
    else:
        candidates = _judge_flat_blocks(blocks)

    candidates = merge_candidates_in_doc(candidates)
    cleaned: list[dict] = []
    for cand in candidates:
        blob = " ".join([cand.get("intro") or "", cand.get("bidCopy") or "", cand.get("params") or ""])
        if looks_like_qualification(cand.get("name") or "", blob) or _bad_feature_name(cand.get("name") or ""):
            continue
        kids = []
        for child in cand.get("children") or []:
            child_blob = " ".join(
                [child.get("intro") or "", child.get("bidCopy") or "", child.get("params") or ""]
            )
            if looks_like_qualification(child.get("name") or "", child_blob) or _bad_feature_name(child.get("name") or ""):
                continue
            child["children"] = []
            kids.append(child)
        cand["children"] = kids
        cleaned.append(cand)
    _attach_images(cleaned, images)
    return cleaned


def _ensure_qual_source_from_product(db: Session, product_doc: ProductSourceDoc) -> QualificationSourceDoc:
    found = (
        db.query(QualificationSourceDoc)
        .filter(QualificationSourceDoc.storage_path == product_doc.storage_path)
        .first()
    )
    if found:
        found.status = "running"
        found.note = "由产品库文档同步抽取资质…"
        db.flush()
        return found
    doc = QualificationSourceDoc(
        filename=product_doc.filename,
        storage_path=product_doc.storage_path,
        size_bytes=product_doc.size_bytes or 0,
        status="running",
        note="由产品库文档同步抽取资质…",
    )
    db.add(doc)
    db.flush()
    return doc


def _feature_to_qual_candidate(feat: ProductFeature) -> dict:
    from .qualification_extract import _guess_kind

    blob_text = " ".join([feat.name or "", feat.intro or "", feat.params or "", feat.bid_copy or ""])
    images: list[dict] = []
    for img in feat.images or []:
        if not img.storage_path or not storage.exists(img.storage_path):
            continue
        with storage.as_local(img.storage_path) as path:
            with open(path, "rb") as fh:
                data = fh.read()
        if not data:
            continue
        ext = os.path.splitext(img.filename or "")[1] or ".png"
        images.append(
            {
                "blob": data,
                "ext": ext,
                "caption": (img.caption or feat.name)[:40],
                "heading": feat.name,
                "sha256": img.sha256 or sha256_bytes(data),
            }
        )
    return {
        "name": (feat.name or "")[:40],
        "kind": _guess_kind(feat.name or "", blob_text),
        "number": "",
        "level": "",
        "validUntil": "长期",
        "owner": "",
        "detail": (feat.intro or feat.params or feat.bid_copy or "")[:800],
        "evidence": list(feat.evidence_json or []),
        "images": images,
        "low_confidence": True,
    }


def _delete_product_feature(db: Session, feat: ProductFeature) -> None:
    children = (
        db.query(ProductFeature)
        .filter(ProductFeature.parent_id == feat.id)
        .all()
    )
    for child in children:
        _delete_product_feature(db, child)
    db.expire(feat, ["children"])
    refs = [img.storage_path for img in (feat.images or []) if img.storage_path]
    db.delete(feat)
    db.flush()
    for ref in refs:
        storage.delete(ref)


def nest_features_by_module(db: Session, library_id: str) -> int:
    """把历史扁平功能点按 module 收成一级菜单 + 二级目录。"""
    from .product_dedup import normalize_name

    rows = db.query(ProductFeature).filter(ProductFeature.library_id == library_id).all()
    roots = [row for row in rows if not row.parent_id]
    by_name = {normalize_name(row.name): row for row in roots if normalize_name(row.name)}
    groups: dict[str, list[ProductFeature]] = {}
    for row in roots:
        mod = (row.module or "").strip()
        if not mod or normalize_name(mod) == normalize_name(row.name):
            continue
        groups.setdefault(mod, []).append(row)
    moved = 0
    for mod, feats in groups.items():
        parent = by_name.get(normalize_name(mod))
        if parent is None:
            parent = ProductFeature(
                library_id=library_id,
                name=mod[:80],
                kind="软件功能",
                module=mod[:80],
                status="待审核",
                merge_status="新增",
                aliases_json=[],
                sources_json=[],
                evidence_json=[],
                params_conflict_json=[],
                suspected_ids_json=[],
            )
            db.add(parent)
            db.flush()
            by_name[normalize_name(mod)] = parent
        for feat in feats:
            if feat.id == parent.id:
                continue
            feat.parent_id = parent.id
            feat.module = parent.name
            moved += 1
    if moved:
        db.flush()
    return moved


def divert_qualification_features(db: Session, library_id: str) -> int:
    """把已误入产品库的证照条目迁到资质库并查重合并。"""
    from sqlalchemy.orm import joinedload

    from .qualification_dedup import apply_to_library as apply_qual

    rows = (
        db.query(ProductFeature)
        .options(joinedload(ProductFeature.images))
        .filter(ProductFeature.library_id == library_id)
        .all()
    )
    misplaced = [
        feat
        for feat in rows
        if looks_like_qualification(feat.name or "", f"{feat.intro or ''} {feat.params or ''}")
    ]
    if not misplaced:
        return 0

    qdoc = None
    for feat in misplaced:
        for row in feat.sources_json or []:
            pdoc = db.get(ProductSourceDoc, row.get("docId") or "")
            if pdoc and pdoc.storage_path:
                qdoc = _ensure_qual_source_from_product(db, pdoc)
                break
        if qdoc:
            break
    if qdoc is None:
        qdoc = QualificationSourceDoc(
            filename="产品库迁出",
            storage_path="",
            size_bytes=0,
            status="running",
            note="从产品功能库同步证照…",
        )
        db.add(qdoc)
        db.flush()

    cands = [_feature_to_qual_candidate(feat) for feat in misplaced]
    stats = apply_qual(db, qdoc, cands)
    for feat in misplaced:
        _delete_product_feature(db, feat)
    qdoc.status = "done"
    qdoc.extracted = (qdoc.extracted or 0) + stats["extracted"]
    qdoc.merged = (qdoc.merged or 0) + stats["merged"]
    qdoc.suspected = (qdoc.suspected or 0) + stats["suspected"]
    qdoc.conflicts = (qdoc.conflicts or 0) + stats["conflicts"]
    qdoc.note = (
        f"从产品库同步：新增 {stats['extracted']}，并入 {stats['merged']}，"
        f"疑似 {stats['suspected']}，请审核"
    )
    qdoc.finished_at = datetime.utcnow()
    qdoc.error = None
    db.flush()
    return len(misplaced)


def run_extract_for_source_doc(db: Session, source_doc_id: str) -> None:
    from .qualification_dedup import apply_to_library as apply_qual
    from .qualification_extract import extract_candidates as extract_qual_candidates

    doc = db.get(ProductSourceDoc, source_doc_id)
    if not doc:
        return
    doc.status = "running"
    doc.note = "正在抽取功能点，证照将同步到资质库…"
    db.commit()
    try:
        if not doc.storage_path or not storage.exists(doc.storage_path):
            raise RuntimeError("源文件不存在")
        with storage.as_local(doc.storage_path) as path:
            candidates = extract_candidates(path)
            qual_cands = extract_qual_candidates(path)
        qstats = {"extracted": 0, "merged": 0, "suspected": 0, "conflicts": 0}
        if qual_cands:
            qdoc = _ensure_qual_source_from_product(db, doc)
            qstats = apply_qual(db, qdoc, qual_cands)
            qdoc.status = "done"
            qdoc.extracted = qstats["extracted"]
            qdoc.merged = qstats["merged"]
            qdoc.suspected = qstats["suspected"]
            qdoc.conflicts = qstats["conflicts"]
            qdoc.error = None
            qdoc.finished_at = datetime.utcnow()
            qdoc.note = (
                f"由产品库同步：新增 {qstats['extracted']}，并入 {qstats['merged']}，"
                f"疑似 {qstats['suspected']}，请审核"
            )
        stats = apply_to_library(db, doc, candidates)
        nest_features_by_module(db, doc.library_id)
        swept = divert_qualification_features(db, doc.library_id)
        doc.extracted = stats["extracted"]
        doc.merged = stats["merged"]
        doc.suspected = stats["suspected"]
        doc.conflicts = stats["conflicts"]
        doc.status = "done"
        note = (
            f"新增 {stats['extracted']}，并入 {stats['merged']}，"
            f"疑似 {stats['suspected']}，参数冲突 {stats['conflicts']}"
        )
        qual_n = qstats["extracted"] + qstats["merged"]
        if qual_n:
            note += f"；同步资质 新增{qstats['extracted']} 并入{qstats['merged']}"
        if swept:
            note += f"；迁出证照 {swept} 条"
        note += "，请审核"
        doc.note = note
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
