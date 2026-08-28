"""知识库文档抽取：按 Word 标题树切章节，配图挂到所属章节，大模型只定一级/二级。

与产品功能库同一套「标题深度 + 图随节走」逻辑；知识库不丢证照/人员/荣誉等章节，
也不再按 500 字切断正文。封面、目录且无图的段落才跳过。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

import pymupdf as fitz

from .docx_extract import extract_paragraphs
from .legacy_doc import as_docx
from .llm import LlmError, chat_complete
from .rules_data import FILLER_WORDS, THRESHOLDS

logger = logging.getLogger(__name__)

SLICE_MAX_CHARS = 500
SENTENCE_SPLIT = re.compile(r"[。！；\n]")
_FILLER_WORDS = [item["word"] for item in FILLER_WORDS]

HEADING_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)(?:\s*[、.．:：]?\s*)(.*)$")
HEADING_NUM = re.compile(r"^(\d+(?:\.\d+)*)")
HEADING_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、\s*(.+)$")
SKIP_KNOWLEDGE = re.compile(r"封面|^目\s*录$|修订记录|版本记录")
WRAPPER_HEADING = re.compile(
    r"实施方案书|实施方案$|技术方案$|技术部分|建设内容|项目建议|"
    r"响应文件|响应正文|详细评审标准要求的其他|其他文件$"
)
TEXT_HARD_CAP = 200000
MAX_IMAGES_PER_CHAPTER = 500

WRAPPER_SYSTEM = """你在阅读投标/技术方案的目录标题，只判断是不是「包装袋」章节。

包装袋：本身只是大类名称，真正目录在下级编号里，例如「项目建议及实施方案书」「技术部分」「建设内容」。
不是包装袋：编号章节（3.1、3.1.1）、索引表、偏离表、具体功能或方案标题。

对每一项返回 {"index":整数,"isWrapper":true或false,"keep":true或false}。
- keep=false 仅封面、目录、空白页。
- 包装袋 keep=true（保留导语），isWrapper=true，禁止把下级 3.1/3.2 收进这一级。
只返回 JSON 数组。"""


def _is_heading(style: str, outline_level) -> bool:
    if style and style.lower().startswith("heading"):
        return True
    if isinstance(outline_level, int) and 0 <= outline_level <= 2:
        return True
    return False


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _numbered_depth(heading: str) -> int | None:
    """3 → 1，3.1 → 2，3.1.1 → 3。年份或不像目录编号的数字返回 None。"""
    raw = (heading or "").strip()
    m = HEADING_NUM.match(raw)
    if not m:
        return None
    first = int(m.group(1).split(".", 1)[0])
    if first <= 0 or first > 40:
        return None
    return m.group(1).count(".") + 1


def _toc_depth(style_depth: int | None, heading: str) -> int:
    numbered = _numbered_depth(heading)
    if numbered is not None:
        return numbered
    raw = (heading or "").strip()
    if HEADING_CN_DOT.match(raw):
        return 1
    return max(1, int(style_depth or 1))


def _is_wrapper_heading(heading: str) -> bool:
    if _numbered_depth(heading):
        return False
    return bool(WRAPPER_HEADING.search(heading or ""))


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


def _looks_cover(heading: str) -> bool:
    return bool(SKIP_KNOWLEDGE.search((heading or "").strip()))


def _ext_from_ctype(ctype: str) -> str:
    content_type = (ctype or "").lower()
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    return ".png"


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
        out.append((blob, _ext_from_ctype(ctype)))
    return out


def _image_item(blob: bytes, ext: str, heading: str) -> dict:
    return {
        "blob": blob,
        "ext": ext,
        "caption": (heading if heading != "全文" else "原文附图")[:40],
        "heading": heading,
        "sha256": _sha256_bytes(blob),
    }


def _split_into_slices(heading: str, text: str) -> list[dict]:
    """兼容旧调用：按字数切片段。新入库路径不再使用。"""
    text = text.strip()
    if not text:
        return []
    slices = []
    start = 0
    while start < len(text):
        chunk = text[start : start + SLICE_MAX_CHARS]
        slices.append({"heading": heading, "text": chunk})
        start += SLICE_MAX_CHARS
    return slices


def extract_docx_sections(path: str) -> list[dict]:
    """按标题把段落分组，组内文本拼接后再切片。无标题的文档整体归为「全文」。"""
    paragraphs = extract_paragraphs(path)

    groups: list[tuple[str, list[str]]] = []
    current_heading = "全文"
    current_texts: list[str] = []

    for p in paragraphs:
        if _is_heading(p.get("style", ""), p.get("outline_level")):
            if current_texts:
                groups.append((current_heading, current_texts))
            current_heading = p["text"][:60]
            current_texts = []
        else:
            current_texts.append(p["text"])

    if current_texts:
        groups.append((current_heading, current_texts))

    slices: list[dict] = []
    for heading, texts in groups:
        slices.extend(_split_into_slices(heading, "\n".join(texts)))
    return slices


def extract_pdf_sections(path: str) -> list[dict]:
    """逐页取文本；无文字层时尝试 OCR，识别失败则跳过该页，不编造正文。"""
    slices: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) < 20:
                try:
                    import pytesseract
                    from PIL import Image

                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    ocr_text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
                    if ocr_text:
                        text = ocr_text
                except Exception:
                    pass
            if not text:
                continue
            slices.extend(_split_into_slices(f"第 {i} 页", text))
    return slices


def extract_full_text_any(path: str, ext: str) -> str:
    if ext == ".pdf":
        with fitz.open(path) as doc:
            return "\n".join(page.get_text("text") for page in doc)
    from .docx_extract import extract_full_text

    if ext == ".doc":
        with as_docx(path) as word_path:
            return extract_full_text(word_path)
    return extract_full_text(path)


def extract_docx_images(path: str, min_bytes: int = 8192, max_count: int = 8) -> list[tuple[bytes, str]]:
    """抽出知识库 .docx 中的内嵌图片。跳过过小的图标，不处理 WMF。写标整篇回退时仍用此函数。"""
    import docx

    document = docx.Document(path)
    out: list[tuple[bytes, str]] = []
    try:
        rels = document.part.rels.values()
    except Exception:
        return []
    for rel in rels:
        reltype = (getattr(rel, "reltype", None) or "").lower()
        if "image" not in reltype:
            continue
        try:
            blob = rel.target_part.blob
            content_type = (rel.target_part.content_type or "").lower()
        except Exception:
            continue
        if not blob or len(blob) < min_bytes:
            continue
        if "wmf" in content_type or "emf" in content_type:
            continue
        out.append((blob, _ext_from_ctype(content_type)))
        if len(out) >= max_count:
            break
    return out


def extract_docx_knowledge_sections(path: str) -> list[dict]:
    """按标题切章节，正文含表格，配图挂在当前标题下。先识别标题再收图，避免图落到上一章。"""
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    sections: list[dict] = []
    current_heading = "全文"
    current_depth = 1
    current_texts: list[str] = []
    current_images: list[dict] = []
    seen_sha: set[str] = set()

    def add_images(blobs: list[tuple[bytes, str]]) -> None:
        for blob, ext in blobs:
            item = _image_item(blob, ext, current_heading)
            if item["sha256"] in seen_sha:
                continue
            if len(current_images) >= MAX_IMAGES_PER_CHAPTER:
                continue
            seen_sha.add(item["sha256"])
            current_images.append(item)

    def flush_section() -> None:
        text = "\n".join(current_texts).strip()
        if _looks_cover(current_heading) and not current_images and len(text) < 80:
            return
        if current_heading in ("全文",) and not text and not current_images:
            return
        sections.append(
            {
                "heading": current_heading[:80],
                "text": text[:TEXT_HARD_CAP],
                "depth": current_depth,
                "images": list(current_images),
            }
        )

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            text = para.text.strip()
            style_name = para.style.name if para.style is not None else ""
            try:
                outline_level = para.paragraph_format.outline_level
            except Exception:
                outline_level = None
            depth = _heading_depth(style_name, outline_level, text) if text else None
            if text and depth is not None:
                flush_section()
                current_heading = text[:80]
                current_depth = depth
                current_texts = []
                current_images = []
            elif text:
                current_texts.append(text)
            add_images(_blip_blobs(child, document))
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            rows: list[list[str]] = []
            for row in table.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(cells)
            if rows:
                current_texts.append("\n".join(" | ".join(r) for r in rows))
            add_images(_blip_blobs(child, document))

    flush_section()
    if not sections:
        paras = extract_paragraphs(path)
        blob = "\n".join(p["text"] for p in paras)
        sections.append({"heading": "全文", "text": blob[:TEXT_HARD_CAP], "depth": 1, "images": []})
    return sections


def _pdf_page_images(page, doc) -> list[tuple[bytes, str]]:
    out: list[tuple[bytes, str]] = []
    seen: set[int] = set()
    for img in page.get_images(full=True):
        xref = img[0]
        if xref in seen:
            continue
        seen.add(xref)
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            blob = pix.tobytes("png")
        except Exception:
            continue
        if blob and len(blob) >= 8192:
            out.append((blob, ".png"))
        if len(out) >= MAX_IMAGES_PER_CHAPTER:
            break
    return out


def extract_pdf_knowledge_sections(path: str) -> list[dict]:
    sections: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            heading = f"第 {i} 页"
            text = page.get_text("text").strip()
            if len(text) < 20:
                try:
                    import pytesseract
                    from PIL import Image

                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    ocr_text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
                    if ocr_text:
                        text = ocr_text
                except Exception:
                    pass
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            depth = _heading_depth("", None, first_line) if first_line else 1
            if first_line and 4 <= len(first_line) <= 80 and depth is not None:
                heading = first_line[:80]
            images = []
            seen_sha: set[str] = set()
            for blob, ext in _pdf_page_images(page, doc):
                item = _image_item(blob, ext, heading)
                if item["sha256"] in seen_sha:
                    continue
                seen_sha.add(item["sha256"])
                images.append(item)
            if _looks_cover(heading) and not images and len(text) < 80:
                continue
            if not text and not images:
                continue
            sections.append(
                {
                    "heading": heading,
                    "text": text[:TEXT_HARD_CAP],
                    "depth": depth or 1,
                    "images": images,
                }
            )
    if not sections:
        sections.append({"heading": "全文", "text": "", "depth": 1, "images": []})
    return sections


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
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _extract_model_id() -> str:
    from .llm import get_default_model_id

    return get_default_model_id()


def _choose_primary_depth(sections: list[dict]) -> int:
    """有大量 3.1 / 5.2 时，以这一级作为列表里的「一级章节」，避免包装袋吞掉整棵目录。"""
    from collections import Counter

    numbered = [_numbered_depth(sec.get("heading") or "") for sec in sections]
    numbered = [d for d in numbered if d]
    if not numbered:
        return 1
    counts = Counter(numbered)
    if counts.get(2, 0) >= 6:
        return 2
    if counts.get(1, 0) >= 6:
        return 1
    return min(numbered)


def _llm_mark_wrappers(candidates: list[dict]) -> dict[int, dict]:
    """只问包装袋/是否保留，不问整篇定级。失败则空，由规则兜底。"""
    if not candidates:
        return {}
    lines = []
    for i, sec in enumerate(candidates):
        lines.append(f"{i}. 标题：{sec.get('heading')}  Word层级：{sec.get('toc_depth')}")
    try:
        model_id = _extract_model_id()
        content = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": WRAPPER_SYSTEM},
                {"role": "user", "content": "请判断：\n" + "\n".join(lines)},
            ],
            temperature=0,
            timeout=45,
            max_tokens=800,
        )
        rows = _parse_json_array(content)
    except LlmError:
        logger.warning("knowledge wrapper LLM unavailable, using heading rules")
        return {}
    except Exception:
        logger.exception("knowledge wrapper label failed")
        return {}
    return {int(row["index"]): row for row in rows if "index" in row}


def _nest_by_toc(sections: list[dict], wrapper_flags: dict[int, bool] | None = None) -> list[dict]:
    """按目录编号嵌套到三级：3.1 一级，3.1.1 二级，3.1.1.1 三级；更深层级挂在最近的三级/二级下。"""
    wrapper_flags = wrapper_flags or {}
    annotated: list[dict] = []
    for sec in sections:
        heading = sec.get("heading") or "全文"
        annotated.append(
            {
                **sec,
                "heading": heading,
                "toc_depth": _toc_depth(sec.get("depth"), heading),
            }
        )
    primary = _choose_primary_depth(annotated)
    last_primary = ""
    last_secondary = ""
    out: list[dict] = []

    def emit(heading: str, text: str, images: list, level: str, parent: str) -> None:
        out.append(
            {
                "heading": heading,
                "text": text,
                "level": level,
                "parentHeading": parent,
                "images": images,
            }
        )

    for i, sec in enumerate(annotated):
        heading = sec["heading"]
        depth = int(sec["toc_depth"] or 1)
        images = list(sec.get("images") or [])
        text = sec.get("text") or ""
        is_wrapper = bool(wrapper_flags.get(i, _is_wrapper_heading(heading)))
        if is_wrapper and not images and not text.strip():
            continue
        if depth < primary or is_wrapper:
            emit(heading, text, images, "一级", "")
            if not is_wrapper and _numbered_depth(heading):
                last_primary = heading
                last_secondary = ""
            continue
        if depth == primary:
            emit(heading, text, images, "一级", "")
            last_primary = heading
            last_secondary = ""
            continue
        if depth == primary + 1:
            if not last_primary:
                emit(heading, text, images, "一级", "")
                last_primary = heading
                last_secondary = ""
            else:
                emit(heading, text, images, "二级", last_primary)
                last_secondary = heading
            continue
        if last_secondary:
            emit(heading, text, images, "三级", last_secondary)
        elif last_primary:
            emit(heading, text, images, "二级", last_primary)
            last_secondary = heading
        else:
            emit(heading, text, images, "一级", "")
            last_primary = heading
            last_secondary = ""
    return out


def _label_sections_with_llm(sections: list[dict]) -> list[dict]:
    """目录编号决定父子；大模型只标包装袋。编号章节一律保留。"""
    kept: list[dict] = []
    for sec in sections:
        heading = sec.get("heading") or "全文"
        images = list(sec.get("images") or [])
        text = sec.get("text") or ""
        if _looks_cover(heading) and not images and len(text.strip()) < 80:
            continue
        kept.append(sec)
    if not kept:
        return _nest_by_toc(sections)

    candidates: list[tuple[int, dict]] = []
    for i, sec in enumerate(kept):
        heading = sec.get("heading") or ""
        if _numbered_depth(heading):
            continue
        candidates.append((i, sec))

    llm_rows = _llm_mark_wrappers(
        [
            {
                "heading": sec.get("heading"),
                "toc_depth": _toc_depth(sec.get("depth"), sec.get("heading") or ""),
            }
            for _, sec in candidates
        ]
    )
    wrapper_flags: dict[int, bool] = {}
    drop: set[int] = set()
    for cand_i, (orig_i, sec) in enumerate(candidates):
        row = llm_rows.get(cand_i) or {}
        heading = sec.get("heading") or ""
        images = list(sec.get("images") or [])
        text = sec.get("text") or ""
        keep = row.get("keep")
        if keep is False or str(keep).lower() in ("false", "0"):
            if not images and (_looks_cover(heading) or len(text.strip()) < 40):
                drop.add(orig_i)
                continue
        if "isWrapper" in row:
            flag = row.get("isWrapper")
            wrapper_flags[orig_i] = flag is True or str(flag).lower() in ("true", "1")
        elif _is_wrapper_heading(heading):
            wrapper_flags[orig_i] = True

    filtered = [sec for i, sec in enumerate(kept) if i not in drop]
    shifted: dict[int, bool] = {}
    new_i = 0
    for i, sec in enumerate(kept):
        if i in drop:
            continue
        if i in wrapper_flags:
            shifted[new_i] = wrapper_flags[i]
        new_i += 1
    return _nest_by_toc(filtered, shifted)


def chunk_document(path: str, ext: str) -> list[dict]:
    """返回 [{heading, text, level, parentHeading, images}, ...]。"""
    if ext == ".pdf":
        sections = extract_pdf_knowledge_sections(path)
    elif ext == ".doc":
        with as_docx(path) as word_path:
            sections = extract_docx_knowledge_sections(word_path)
    else:
        sections = extract_docx_knowledge_sections(path)
    return _label_sections_with_llm(sections)


def detect_review_flag(
    full_text: str,
    filler_words: list[str] | None = None,
    threshold: float | None = None,
) -> str | None:
    """复用 E4 引擎的虚词密度算法：命中句子占比超过安全线时给出提示。"""
    words = filler_words if filler_words is not None else _FILLER_WORDS
    safe_line = threshold if threshold is not None else THRESHOLDS["filler_density_safe"]

    sentences = [s.strip() for s in SENTENCE_SPLIT.split(full_text) if s.strip()]
    total = len(sentences) or 1
    hit = sum(1 for s in sentences if any(w in s for w in words))
    density = hit / total * 100
    if density > safe_line:
        return "虚词偏高，建议改写后复用"
    return None
