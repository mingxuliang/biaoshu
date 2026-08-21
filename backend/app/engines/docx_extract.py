"""基于 python-docx 的公共文档抽取工具，供五大引擎共用。"""

import docx


def extract_paragraphs(path: str) -> list[dict]:
    """返回非空段落列表：[{index, text, style, outline_level}]。"""
    document = docx.Document(path)
    result = []
    for idx, p in enumerate(document.paragraphs):
        text = p.text.strip()
        if not text:
            continue
        style_name = p.style.name if p.style is not None else ""
        try:
            outline_level = p.paragraph_format.outline_level
        except Exception:
            outline_level = None
        result.append(
            {
                "index": idx,
                "text": text,
                "style": style_name,
                "outline_level": outline_level,
            }
        )
    return result


def extract_full_text(path: str) -> str:
    paragraphs = extract_paragraphs(path)
    return "\n".join(p["text"] for p in paragraphs)


def has_toc_field(path: str) -> bool:
    document = docx.Document(path)
    xml = document.element.xml
    return "TOC" in xml and ("fldSimple" in xml or "instrText" in xml)


def has_revision_marks(path: str) -> bool:
    document = docx.Document(path)
    xml = document.element.xml
    return "<w:ins " in xml or "<w:del " in xml or "<w:ins>" in xml or "<w:del>" in xml


def get_core_author(path: str) -> str | None:
    document = docx.Document(path)
    props = document.core_properties
    return props.author or props.last_modified_by
