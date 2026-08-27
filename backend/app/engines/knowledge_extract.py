"""知识库文档抽取与切片：将上传的 .docx / .pdf 按标题分组，再按字数切成检索用的片段。

docx 复用 docx_extract.extract_paragraphs 的段落/样式信息识别标题；
pdf 没有可靠的样式信息，采用简化策略——按页码作为 heading。
"""

import re

import pymupdf as fitz

from .docx_extract import extract_paragraphs
from .legacy_doc import as_docx
from .rules_data import FILLER_WORDS, THRESHOLDS

SLICE_MAX_CHARS = 500
SENTENCE_SPLIT = re.compile(r"[。！；\n]")
_FILLER_WORDS = [item["word"] for item in FILLER_WORDS]


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
    """抽出知识库 .docx 中的内嵌图片。跳过过小的图标，不处理 WMF。"""
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
        ext = ".png"
        if "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        elif "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        elif "webp" in content_type:
            ext = ".webp"
        out.append((blob, ext))
        if len(out) >= max_count:
            break
    return out


def chunk_document(path: str, ext: str) -> list[dict]:
    """返回 [{heading, text}, ...]，按扩展名分发到对应的抽取逻辑。"""
    if ext == ".pdf":
        return extract_pdf_sections(path)
    if ext == ".doc":
        with as_docx(path) as word_path:
            return extract_docx_sections(word_path)
    return extract_docx_sections(path)


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
