"""基于 python-docx 的公共文档抽取工具，供五大引擎共用。

本模块是最底层的抽取工具，不反向依赖 tender_form/tender_toc 等上层引擎模块
（它们本身会 import 本模块），避免循环引用。
"""

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


def _first_run_style(p) -> tuple[str, float, bool]:
    """取段落第一个非空 run 的字体/字号/加粗；run 上没有则回落到段落样式。"""
    style_font = None
    try:
        style_font = p.style.font if p.style is not None else None
    except Exception:
        style_font = None

    def from_run(run) -> tuple[str, float, bool]:
        name = ""
        rPr = run._element.rPr
        if rPr is not None:
            rf = rPr.find(qn("w:rFonts"))
            if rf is not None:
                for key in (qn("w:eastAsia"), qn("w:ascii"), qn("w:hAnsi"), qn("w:cs")):
                    val = rf.get(key)
                    if val:
                        name = val
                        break
        if not name and run.font.name:
            name = run.font.name
        if not name and style_font is not None and style_font.name:
            name = style_font.name
        size = 0.0
        if run.font.size:
            size = round(float(run.font.size.pt), 1)
        elif rPr is not None:
            sz = rPr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                try:
                    size = int(sz.get(qn("w:val"))) / 2
                except (TypeError, ValueError):
                    size = 0.0
        if not size and style_font is not None and style_font.size:
            size = round(float(style_font.size.pt), 1)
        bold = bool(run.bold) if run.bold is not None else bool(style_font.bold) if style_font is not None else False
        return name or "宋体", size or 12.0, bold

    for run in p.runs:
        if (run.text or "").strip():
            return from_run(run)
    if style_font is not None:
        name = style_font.name or "宋体"
        size = round(float(style_font.size.pt), 1) if style_font.size else 12.0
        return name, size, bool(style_font.bold)
    return "宋体", 12.0, False


def _paragraph_align(p) -> str:
    """段落对齐方式：""（默认左对齐，不返回）/center/right/justify。"""
    val = ""
    try:
        if p._element.pPr is not None:
            jc = p._element.pPr.find(qn("w:jc"))
            if jc is not None:
                val = (jc.get(qn("w:val")) or "").lower()
    except Exception:
        val = ""
    if p.alignment == WD_ALIGN_PARAGRAPH.CENTER or val in ("center", "middle"):
        return "center"
    if p.alignment == WD_ALIGN_PARAGRAPH.RIGHT or val in ("right", "end"):
        return "right"
    if p.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY or val == "both":
        return "justify"
    return ""


def _para_dict(p, idx: int, from_table: bool = False) -> dict | None:
    text = (p.text or "").strip()
    if not text:
        return None
    style_name = p.style.name if p.style is not None else ""
    try:
        outline_level = p.paragraph_format.outline_level
    except Exception:
        outline_level = None
    font, size_pt, bold = _first_run_style(p)
    return {
        "index": idx,
        "text": text,
        "style": style_name,
        "outline_level": outline_level,
        "align": _paragraph_align(p),
        "font": font,
        "fontSizePt": size_pt,
        "bold": bold,
        "fromTable": from_table,
    }


def _table_row_texts(table) -> list[str]:
    """抽出表格文字：长单元格单独成段（便于 L3 excerpt 命中），短格仍按行拼接。"""
    rows: list[str] = []
    for row in table.rows:
        seen: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            cell_text = " ".join((cell.text or "").split())
            if cell_text:
                cells.append(cell_text)
        if not cells:
            continue
        long_cells = [c for c in cells if len(c) >= 16]
        if long_cells:
            rows.extend(long_cells)
        else:
            rows.append(" | ".join(cells))
    return rows


def extract_paragraphs(path: str) -> list[dict]:
    """按正文顺序返回非空块：段落 + 表格行。

    工程类投标书大量正文写在表格里；只抽 document.paragraphs 会只剩标题，
    预审 E3 用的是含表全文，修改闭环若不含表就会出现「有 L3、锚点全空」。
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(path)
    result: list[dict] = []
    idx = 0
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            item = _para_dict(Paragraph(child, document), idx, False)
            if item:
                result.append(item)
                idx += 1
            continue
        if child.tag != qn("w:tbl"):
            continue
        table = Table(child, document)
        for row_text in _table_row_texts(table):
            result.append(
                {
                    "index": idx,
                    "text": row_text,
                    "style": "",
                    "outline_level": None,
                    "align": "",
                    "font": "宋体",
                    "fontSizePt": 12.0,
                    "bold": False,
                    "fromTable": True,
                }
            )
            idx += 1
    return result


def extract_full_text(path: str, *, max_ocr_pages: int | None = None, stats: dict | None = None) -> str:
    """招标文件正文抽取的统一入口：按扩展名分发到 docx / pdf 抽取。

    PDF 版招标文件（部分工程标只提供 PDF 招标文件正文，清单/图纸另附）走
    PyMuPDF 抽取；文字层不足的页再 OCR。docx 仍走 python-docx。
    """
    if (path or "").lower().endswith(".pdf"):
        return _extract_pdf_full_text(path, max_ocr_pages=max_ocr_pages, stats=stats)
    paragraphs = extract_paragraphs(path)
    return "\n".join(p["text"] for p in paragraphs)


PDF_SPARSE_CHARS = 80
DEFAULT_TENDER_OCR_PAGES = 80


def _extract_pdf_full_text(
    path: str, *, max_ocr_pages: int | None = None, stats: dict | None = None
) -> str:
    """按页抽出正文；表格再补一行；稀疏页 OCR。"""
    import pymupdf as fitz

    from .ocr import ocr_pixmap

    ocr_limit = DEFAULT_TENDER_OCR_PAGES if max_ocr_pages is None else max_ocr_pages
    chunks: list[str] = []
    ocr_pages = 0
    page_count = 0
    with fitz.open(path) as doc:
        page_count = len(doc)
        for page in doc:
            text = (page.get_text() or "").strip()
            table_lines: list[str] = []
            try:
                found = page.find_tables()
                for table in found.tables if found else []:
                    for row in table.extract() or []:
                        cells = [" ".join(str(c).split()) for c in row if c and str(c).strip()]
                        if cells:
                            table_lines.append(" | ".join(cells))
            except Exception:
                table_lines = []
            extra = "\n".join(table_lines)
            if extra and extra[:60] not in (text or ""):
                block = f"{text}\n{extra}".strip() if text else extra
            else:
                block = text
            if len(block) < PDF_SPARSE_CHARS and ocr_pages < ocr_limit:
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                    ocr_text, _status = ocr_pixmap(pix)
                except Exception:
                    ocr_text = ""
                if ocr_text:
                    ocr_pages += 1
                    block = f"{block}\n{ocr_text}".strip() if block else ocr_text
            if block:
                chunks.append(block)
    if stats is not None:
        stats["ocrPages"] = int(stats.get("ocrPages") or 0) + ocr_pages
        stats["pages"] = int(stats.get("pages") or 0) + page_count
    return "\n".join(chunks)


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
