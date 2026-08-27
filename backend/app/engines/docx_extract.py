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


def extract_document_plain_text(path: str) -> str:
    """按正文顺序抽出段落和表格文字，供目录生成阅读整篇招标书。"""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    chunks: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            if text:
                chunks.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    cell_text = " ".join(cell.text.split())
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    chunks.append(" | ".join(cells))
    return "\n".join(chunks)


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


def has_comments(path: str) -> bool:
    """检测批注残留（commentRange 或 comments 部件）。"""
    document = docx.Document(path)
    xml = document.element.xml
    if "commentRangeStart" in xml or "commentRangeEnd" in xml or "w:commentReference" in xml:
        return True
    try:
        for rel in document.part.rels.values():
            reltype = (getattr(rel, "reltype", None) or "").lower()
            if "comments" in reltype:
                return True
    except Exception:
        pass
    return False


def has_blank_page_hint(path: str) -> bool:
    """连续空段落达到一页量级时视为空白页线索，不做跨页精确分页。"""
    document = docx.Document(path)
    empty_run = 0
    for p in document.paragraphs:
        if not p.text.strip():
            empty_run += 1
            if empty_run >= 15:
                return True
        else:
            empty_run = 0
    return False
