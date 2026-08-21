"""知识库文档抽取与切片：将上传的 .docx / .pdf 按标题分组，再按字数切成检索用的片段。

docx 复用 docx_extract.extract_paragraphs 的段落/样式信息识别标题；
pdf 没有可靠的样式信息，采用简化策略——按页码作为 heading。
"""

import re

import pymupdf as fitz

from .docx_extract import extract_paragraphs
from .rules_data import FILLER_WORD_CATEGORIES, THRESHOLDS

SLICE_MAX_CHARS = 500
SENTENCE_SPLIT = re.compile(r"[。！；\n]")
_FILLER_WORDS = [w for cat in FILLER_WORD_CATEGORIES for w in cat["words"]]


def _is_heading(style: str, outline_level) -> bool:
    if style and style.lower().startswith("heading"):
        return True
    if isinstance(outline_level, int) and 0 <= outline_level <= 2:
        return True
    return False


def _split_into_slices(heading: str, text: str) -> list[dict]:
    """把一段长文本按 SLICE_MAX_CHARS 切成若干片段，保留所属 heading。"""
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
    """逐页取文本，以「第 N 页」作为 heading，页内文本按字数切片。"""
    slices: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            slices.extend(_split_into_slices(f"第 {i} 页", text))
    return slices


def extract_full_text_any(path: str, ext: str) -> str:
    if ext == ".pdf":
        with fitz.open(path) as doc:
            return "\n".join(page.get_text("text") for page in doc)
    from .docx_extract import extract_full_text

    return extract_full_text(path)


def chunk_document(path: str, ext: str) -> list[dict]:
    """返回 [{heading, text}, ...]，按扩展名分发到对应的抽取逻辑。"""
    if ext == ".pdf":
        return extract_pdf_sections(path)
    return extract_docx_sections(path)


def detect_review_flag(full_text: str) -> str | None:
    """复用 E4 引擎的虚词密度算法：命中句子占比超过安全线时给出提示。"""
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(full_text) if s.strip()]
    total = len(sentences) or 1
    hit = sum(1 for s in sentences if any(w in s for w in _FILLER_WORDS))
    density = hit / total * 100
    if density > THRESHOLDS["filler_density_safe"]:
        return "虚词偏高，建议改写后复用"
    return None
