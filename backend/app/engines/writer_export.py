"""撰写工作台「导出 Word」：把逐章生成/编辑的 markdown-lite 文本还原为真实 .docx。

与前端 ChapterEditor 的行级/行内约定保持一致：
`### ` 三级标题、`## ` 二级标题、`- `/`* ` 项目符号列表（要求标记后有空格，避免与行内 `*斜体*` 冲突）、
`数字)` 或 `（一）` 编号段落，其余为普通段落；行内 `**加粗**` / `*斜体*` / `__下划线__` 会被拆分为独立样式的 run。
`>>> ` 居中、`>> ` 右对齐；连续 `| a | b |` 行还原为表格。
`![说明](/api/writer-images/{id}/file)` 会按本地落盘文件嵌入图片。

不是预审引擎（不产生 Finding），仅供 routers/writer.py 复用。
"""

import io
import os
import re

import docx
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Inches, RGBColor

from .writer_layout import font_size_pt, resolve_text

_INLINE_SPLIT_RE = re.compile(r"(\*\*.+?\*\*|__.+?__|\*.+?\*)")
_FONT_WRAP_RE = re.compile(r"\{\{([^|:{}]+)[:|]([^}]+)\}\}(.*?)\{\{/\}\}", re.S)
_CELL_SPAN_RE = re.compile(r"^(?:#c(\d+)#)?(?:#r(\d+)#)?")
_BULLET_RE = re.compile(r"^[-*]\s+")
_NUMBERED_RE = re.compile(r"^\d+[）.)\]].*")
_CN_NUMBERED_RE = re.compile(r"^（[一二三四五六七八九十]+）")
_IMAGE_MD_RE = re.compile(r"^!\[([^\]]*)\]\((/api/writer-images/([^/]+)/file)\)$")
_CAPTION_RE = re.compile(r"^(图|表)\s*[：:]\s*(.+)$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _set_run_font(run, name: str | None, size: str | None) -> None:
    if name:
        run.font.name = name
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), name)
        rFonts.set(qn("w:hAnsi"), name)
        rFonts.set(qn("w:eastAsia"), name)
        rFonts.set(qn("w:cs"), name)
    if size:
        m = re.match(r"([0-9.]+)", str(size).strip())
        if m:
            run.font.size = Pt(float(m.group(1)))


def _add_inner_runs(paragraph, text: str, font: str | None = None, size: str | None = None) -> None:
    for part in _INLINE_SPLIT_RE.split(text or ""):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            run.underline = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            run = paragraph.add_run(part)
        _set_run_font(run, font, size)


def _add_runs_with_inline_styles(paragraph, text: str) -> None:
    raw = text or ""
    pos = 0
    for m in _FONT_WRAP_RE.finditer(raw):
        if m.start() > pos:
            _add_inner_runs(paragraph, raw[pos : m.start()])
        _add_inner_runs(paragraph, m.group(3), m.group(1).strip(), m.group(2).strip())
        pos = m.end()
    if pos == 0:
        _add_inner_runs(paragraph, raw)
    elif pos < len(raw):
        _add_inner_runs(paragraph, raw[pos:])


def _split_align(line: str) -> tuple[object | None, str]:
    raw = line or ""
    stripped = raw.lstrip()
    if stripped.startswith(">>> "):
        return WD_ALIGN_PARAGRAPH.CENTER, stripped[4:]
    if stripped.startswith(">>>"):
        return WD_ALIGN_PARAGRAPH.CENTER, stripped[3:]
    if stripped.startswith(">> "):
        return WD_ALIGN_PARAGRAPH.RIGHT, stripped[3:]
    return None, raw


def _is_table_row(line: str) -> bool:
    t = (line or "").strip()
    return t.startswith("|") and t.count("|") >= 2


def _is_table_sep(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match((line or "").strip()))


def _parse_table_row(line: str) -> list[str]:
    t = (line or "").strip()
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|") and not t.endswith("\\|"):
        t = t[:-1]
    cells: list[str] = []
    buf: list[str] = []
    brace = 0
    escape = False
    i = 0
    while i < len(t):
        ch = t[i]
        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == "{" and i + 1 < len(t) and t[i + 1] == "{":
            brace += 1
            buf.append("{{")
            i += 2
            continue
        if ch == "}" and i + 1 < len(t) and t[i + 1] == "}":
            brace = max(0, brace - 1)
            buf.append("}}")
            i += 2
            continue
        if ch == "|" and brace == 0:
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _parse_cell(raw: str) -> dict:
    text = raw or ""
    col_span = 1
    row_span = 1
    m = _CELL_SPAN_RE.match(text)
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            col_span = max(1, int(m.group(1)))
        if m.group(2):
            row_span = max(1, int(m.group(2)))
        text = text[m.end() :]
    return {"text": text, "colspan": col_span, "rowspan": row_span}


def _fill_cell(cell, text: str) -> None:
    cell.text = ""
    parts = re.split(r"<br\s*/?>", text or "", flags=re.I)
    for i, part in enumerate(parts):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        _add_runs_with_inline_styles(p, part)


def _add_markdown_table(document, rows: list[list[str]], layout: dict | None = None) -> None:
    if not rows:
        return
    parsed = [[_parse_cell(c) for c in row] for row in rows]
    cols = max((sum(c["colspan"] for c in row) for row in parsed), default=1)
    table = document.add_table(rows=len(parsed), cols=max(cols, 1))
    table.style = "Table Grid"
    occupied = [[False] * cols for _ in parsed]
    for i, row in enumerate(parsed):
        c = 0
        for info in row:
            while c < cols and occupied[i][c]:
                c += 1
            if c >= cols:
                break
            cs = max(1, int(info["colspan"]))
            rs = max(1, int(info["rowspan"]))
            cell = table.cell(i, c)
            if cs > 1 or rs > 1:
                end_r = min(i + rs - 1, len(parsed) - 1)
                end_c = min(c + cs - 1, cols - 1)
                if end_r > i or end_c > c:
                    cell.merge(table.cell(end_r, end_c))
            _fill_cell(cell, info["text"])
            for rr in range(i, min(i + rs, len(parsed))):
                for cc in range(c, min(c + cs, cols)):
                    occupied[rr][cc] = True
            c += cs
    _style_table(table, layout)


def render_markdown_block(
    document, line: str, image_paths: dict[str, str] | None = None, layout: dict | None = None
) -> None:
    """把编辑器里的一行 markdown-lite 文本追加为 docx 段落/标题。"""
    align, body = _split_align(line)
    trimmed = body.strip()
    if not trimmed:
        document.add_paragraph("")
        return

    caption = _CAPTION_RE.match(trimmed)
    if caption and align == WD_ALIGN_PARAGRAPH.CENTER:
        _add_caption(document, caption.group(1), caption.group(2).strip(), layout)
        return

    img_match = _IMAGE_MD_RE.match(trimmed)
    if img_match:
        image_id = img_match.group(3)
        path = (image_paths or {}).get(image_id)
        if path and os.path.exists(path):
            try:
                section = document.sections[0]
                usable = section.page_width - section.left_margin - section.right_margin
                document.add_picture(path, width=min(Inches(5.4), usable))
                pic = document.paragraphs[-1]
                pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pic.paragraph_format.first_line_indent = Pt(0)
                pic.paragraph_format.keep_with_next = True
            except Exception:  # noqa: BLE001 —— 坏图不阻断整份导出
                document.add_paragraph(f"[图片无法嵌入：{img_match.group(1) or image_id}]")
        else:
            document.add_paragraph(f"[图片缺失：{img_match.group(1) or image_id}]")
        return

    if trimmed.startswith("### "):
        p = document.add_heading(_unwrap_inline(trimmed[4:]), level=3)
        _restyle_heading(p, layout, 3)
        if align is not None:
            p.alignment = align
        return
    if trimmed.startswith("## "):
        p = document.add_heading(_unwrap_inline(trimmed[3:]), level=2)
        _restyle_heading(p, layout, 2)
        if align is not None:
            p.alignment = align
        return

    bullet_match = _BULLET_RE.match(trimmed)
    if bullet_match:
        p = document.add_paragraph(style="List Bullet")
        _add_runs_with_inline_styles(p, trimmed[bullet_match.end() :].strip())
        if align is not None:
            p.alignment = align
        return

    if _NUMBERED_RE.match(trimmed) or _CN_NUMBERED_RE.match(trimmed):
        p = document.add_paragraph()
        _add_runs_with_inline_styles(p, trimmed)
        if align is not None:
            p.alignment = align
        return

    p = document.add_paragraph()
    _add_runs_with_inline_styles(p, trimmed)
    _apply_body_indent(p, trimmed, layout)
    if align is not None:
        p.alignment = align


def _node_level(outline: list[dict], node_id: str, _depth: int = 0) -> int:
    node = next((n for n in outline if n.get("id") == node_id), None)
    if not node or not node.get("parentId"):
        return _depth
    return _node_level(outline, node["parentId"], _depth + 1)


_LINE_SPACING = {
    "1.5倍行距": 1.5,
    "2倍行距": 2.0,
    "固定值28磅": 28,
    "固定值30磅": 30,
}
_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


def _unwrap_inline(text: str) -> str:
    t = _FONT_WRAP_RE.sub(lambda m: m.group(3), text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"__(.+?)__", r"\1", t)
    t = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"\1", t)
    return t.strip()


def _set_style_font(style, name: str, size_pt: float, latin: str | None = None) -> None:
    """中文用 name，英文数字用 latin（没给就和中文一致）。"""
    font = style.font
    font.name = latin or name
    font.size = Pt(size_pt)
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), latin or name)
    rFonts.set(qn("w:hAnsi"), latin or name)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:cs"), latin or name)


def _layout_body_pt(layout: dict | None) -> float:
    if not layout:
        return 12.0
    for key in ("bodySizePt", "fontSize"):
        pt = font_size_pt(layout.get(key))
        if pt:
            return float(pt)
    return 12.0


def _heading_spec(layout: dict | None, level: int) -> dict:
    """某一级标题的最终样式：headings.hN 优先，其次旧版统一标题字段，最后正文。"""
    data = layout or {}
    body_pt = _layout_body_pt(data)
    spec = {
        "font": str(data.get("headingFont") or data.get("bodyFont") or "宋体"),
        "sizePt": body_pt,
        "bold": bool(data.get("headingBold", True)),
        "align": None,
        "spaceBefore": None,
        "spaceAfter": None,
        "color": None,
    }
    try:
        if data.get("headingSizePt"):
            spec["sizePt"] = float(data["headingSizePt"])
    except (TypeError, ValueError):
        pass
    custom = (data.get("headings") or {}).get(f"h{level}") if isinstance(data.get("headings"), dict) else None
    if isinstance(custom, dict):
        for key, value in custom.items():
            if value is not None and value != "":
                spec[key] = value
    return spec


def _rgb(hex_text: str | None) -> RGBColor:
    if hex_text and re.match(r"^[0-9A-Fa-f]{6}$", str(hex_text)):
        return RGBColor.from_string(str(hex_text).upper())
    return RGBColor(0, 0, 0)


def _restyle_heading(paragraph, layout: dict | None, level: int = 2) -> None:
    if not layout:
        return
    spec = _heading_spec(layout, level)
    paragraph.paragraph_format.first_line_indent = Pt(0)
    if spec.get("align") in _ALIGN:
        paragraph.alignment = _ALIGN[spec["align"]]
    for run in paragraph.runs:
        _set_run_font(run, spec["font"], f"{float(spec['sizePt']):g}pt")
        run.bold = bool(spec["bold"])
        run.font.color.rgb = _rgb(spec.get("color"))


def _indent_pt(layout: dict | None) -> float:
    if not layout:
        return 0.0
    try:
        points = float(layout.get("indentPt") or 0)
    except (TypeError, ValueError):
        points = 0.0
    if points < 8:
        try:
            chars = float(layout.get("indentChars") or 0)
        except (TypeError, ValueError):
            chars = 0.0
        points = chars * _layout_body_pt(layout)
    return points


def _apply_body_indent(paragraph, text: str, layout: dict | None) -> None:
    indent_pt = _indent_pt(layout)
    if indent_pt < 8:
        return
    stripped = (text or "").lstrip()
    if stripped.startswith("　") or stripped.startswith(" "):
        return
    paragraph.paragraph_format.first_line_indent = Pt(indent_pt)


def _add_field(paragraph, instruction: str, placeholder: str = "1", font: str | None = None, size: str | None = None):
    """插入 Word 域（PAGE、NUMPAGES、SEQ、TOC）。打开 Word 后会按实际值刷新。"""
    runs = []

    def part(kind: str, text: str = ""):
        run = paragraph.add_run()
        if kind in ("begin", "separate", "end"):
            node = OxmlElement("w:fldChar")
            node.set(qn("w:fldCharType"), kind)
            run._r.append(node)
        elif kind == "instr":
            node = OxmlElement("w:instrText")
            node.set(qn("xml:space"), "preserve")
            node.text = f" {text} "
            run._r.append(node)
        else:
            run.text = text
        _set_run_font(run, font, size)
        runs.append(run)

    part("begin")
    part("instr", instruction)
    part("separate")
    part("text", placeholder)
    part("end")
    return runs


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    for old in tc_pr.findall(qn("w:shd")):
        tc_pr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _style_table(table, layout: dict | None) -> None:
    """表头底色、表内字号、居中。没有排版配置时保持原样。"""
    cfg = (layout or {}).get("table") if isinstance((layout or {}).get("table"), dict) else None
    if not cfg:
        return
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    size = cfg.get("fontSizePt")
    fill = cfg.get("headerFill")
    bold = bool(cfg.get("headerBold", True))
    for r, row in enumerate(table.rows):
        for cell in row.cells:
            if r == 0 and fill:
                _shade(cell, str(fill))
            for p in cell.paragraphs:
                p.paragraph_format.first_line_indent = Pt(0)
                if r == 0:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in p.runs:
                    if size:
                        run.font.size = Pt(float(size))
                    if r == 0 and bold:
                        run.bold = True


def _add_caption(document, kind: str, text: str, layout: dict | None) -> None:
    """图注/表注：'图 N 说明'，N 用 SEQ 域自动编号，Word 里改顺序后可更新域。"""
    cfg = (layout or {}).get("caption") if isinstance((layout or {}).get("caption"), dict) else {}
    font = cfg.get("font") or None
    size = f"{float(cfg['sizePt']):g}pt" if cfg.get("sizePt") else None
    try:
        p = document.add_paragraph(style="Caption")
    except KeyError:
        p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Pt(0)
    label = p.add_run(f"{kind} ")
    _set_run_font(label, font, size)
    _add_field(p, f"SEQ {kind} \\* ARABIC", "1", font, size)
    body = p.add_run(f" {text}")
    _set_run_font(body, font, size)
    for run in p.runs:
        run.bold = False
        run.italic = False
        run.font.color.rgb = RGBColor(0, 0, 0)
    if kind == "表":
        p.paragraph_format.keep_with_next = True


def _add_cover(document, layout: dict, project_name: str) -> None:
    cover = layout.get("cover") if isinstance(layout.get("cover"), dict) else {}
    title = resolve_text(str(cover.get("title") or "{project}"), project_name) or "投标文件"
    spec = _heading_spec(layout, 1)
    for _ in range(6):
        document.add_paragraph("")
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    _set_run_font(run, spec["font"], "26pt")
    run.bold = True
    if cover.get("subtitle"):
        sub = document.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.paragraph_format.space_before = Pt(24)
        run = sub.add_run(str(cover["subtitle"]))
        _set_run_font(run, spec["font"], "20pt")
        run.bold = True
    for _ in range(8):
        document.add_paragraph("")
    for key in ("company", "date"):
        if cover.get(key):
            line = document.add_paragraph()
            line.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = line.add_run(resolve_text(str(cover[key]), project_name))
            _set_run_font(run, spec["font"], "14pt")
    document.add_page_break()


def _add_toc(document, layout: dict) -> None:
    toc = layout.get("toc") if isinstance(layout.get("toc"), dict) else {}
    levels = max(1, min(int(toc.get("levels") or 3), 3))
    spec = _heading_spec(layout, 1)
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("目  录")
    _set_run_font(run, spec["font"], "16pt")
    run.bold = True
    holder = document.add_paragraph()
    _add_field(holder, f'TOC \\o "1-{levels}" \\h \\z \\u', "（用 Word 打开后，在此处右键选择“更新域”生成目录）")
    document.add_page_break()
    settings = document.settings.element
    if settings.find(qn("w:updateFields")) is None:
        node = OxmlElement("w:updateFields")
        node.set(qn("w:val"), "true")
        settings.append(node)


def _apply_header_footer(document, layout: dict, project_name: str) -> None:
    section = document.sections[0]
    text = resolve_text(str(layout.get("header") or ""), project_name)
    if text:
        p = section.header.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        _set_run_font(run, layout.get("bodyFont"), "9pt")
    mode = layout.get("pageNumber")
    if mode in ("simple", "full"):
        p = section.footer.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        font = layout.get("bodyFont")
        if mode == "full":
            _set_run_font(p.add_run("第 "), font, "9pt")
            _add_field(p, "PAGE", "1", font, "9pt")
            _set_run_font(p.add_run(" 页 共 "), font, "9pt")
            _add_field(p, "NUMPAGES", "1", font, "9pt")
            _set_run_font(p.add_run(" 页"), font, "9pt")
        else:
            _add_field(p, "PAGE", "1", font, "9pt")


def _apply_layout(document, layout: dict | None, project_name: str = "") -> None:
    if not layout:
        return
    section = document.sections[0]
    if layout.get("orientation") == "landscape":
        section.orientation = WD_ORIENT.LANDSCAPE
        width, height = section.page_width, section.page_height
        if height > width:
            section.page_width, section.page_height = height, width
    margins = layout.get("margins") or {}
    if isinstance(margins, dict):
        if margins.get("top") is not None:
            section.top_margin = Cm(float(margins["top"]))
        if margins.get("bottom") is not None:
            section.bottom_margin = Cm(float(margins["bottom"]))
        if margins.get("left") is not None:
            section.left_margin = Cm(float(margins["left"]))
        if margins.get("right") is not None:
            section.right_margin = Cm(float(margins["right"]))

    body_font = str(layout.get("bodyFont") or "宋体")
    latin = str(layout.get("bodyLatinFont") or "") or None
    body_pt = _layout_body_pt(layout)
    normal = document.styles["Normal"]
    _set_style_font(normal, body_font, body_pt, latin)

    for level in range(1, 4):
        try:
            hstyle = document.styles[f"Heading {level}"]
        except KeyError:
            continue
        spec = _heading_spec(layout, level)
        _set_style_font(hstyle, spec["font"], float(spec["sizePt"]), latin)
        hstyle.font.bold = bool(spec["bold"])
        hstyle.font.color.rgb = _rgb(spec.get("color"))
        hstyle.paragraph_format.first_line_indent = Pt(0)
        if spec.get("align") in _ALIGN:
            hstyle.paragraph_format.alignment = _ALIGN[spec["align"]]
        else:
            hstyle.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if spec.get("spaceBefore") is not None:
            hstyle.paragraph_format.space_before = Pt(float(spec["spaceBefore"]))
        if spec.get("spaceAfter") is not None:
            hstyle.paragraph_format.space_after = Pt(float(spec["spaceAfter"]))
        hstyle.paragraph_format.keep_with_next = True
    try:
        title_style = document.styles["Title"]
        spec = _heading_spec(layout, 1)
        _set_style_font(title_style, spec["font"], float(spec["sizePt"]) + 4, latin)
        title_style.font.bold = True
        title_style.font.color.rgb = _rgb(spec.get("color"))
        title_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    except KeyError:
        pass
    try:
        caption_style = document.styles["Caption"]
        cfg = layout.get("caption") if isinstance(layout.get("caption"), dict) else {}
        _set_style_font(
            caption_style,
            str(cfg.get("font") or body_font),
            float(cfg.get("sizePt") or max(body_pt - 1.5, 8)),
            latin,
        )
        caption_style.font.bold = False
        caption_style.font.italic = False
        caption_style.font.color.rgb = RGBColor(0, 0, 0)
    except KeyError:
        pass

    pf = normal.paragraph_format
    if layout.get("justify"):
        pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if layout.get("paragraphBefore") is not None:
        pf.space_before = Pt(float(layout["paragraphBefore"]))
    if layout.get("paragraphAfter") is not None:
        pf.space_after = Pt(float(layout["paragraphAfter"]))

    spacing = layout.get("lineSpacing")
    exact = layout.get("lineSpacingExactPt")
    try:
        mul = float(layout["lineSpacingMul"]) if layout.get("lineSpacingMul") is not None else None
    except (TypeError, ValueError):
        mul = None
    if exact:
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(float(exact))
    else:
        multiple = mul if mul else _LINE_SPACING.get(str(spacing or ""), 1.5)
        if spacing in ("固定值28磅", "固定值30磅") and mul is None:
            pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            pf.line_spacing = Pt(multiple)
        else:
            pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pf.line_spacing = multiple

    _apply_header_footer(document, layout, project_name)


def chapters_to_docx(
    project_name: str,
    outline: list[dict],
    chapter_contents: dict[str, str],
    image_paths: dict[str, str] | None = None,
    layout: dict | None = None,
) -> bytes:
    """按目录顺序把全部章节内容拼接为一份完整 .docx。"""
    from .e_writer import chapter_kind

    document = docx.Document()
    _apply_layout(document, layout, project_name)
    cover_on = bool(layout and isinstance(layout.get("cover"), dict) and layout["cover"].get("enabled"))
    toc_on = bool(layout and isinstance(layout.get("toc"), dict) and layout["toc"].get("enabled"))
    if cover_on:
        _add_cover(document, layout, project_name)
    elif project_name:
        document.add_heading(project_name, level=0)
    if toc_on:
        _add_toc(document, layout)

    for node in outline:
        level = min(_node_level(outline, node["id"]) + 1, 3)
        heading_text = f"{node.get('num', '')} {node.get('title', '')}".strip()
        document.add_heading(heading_text, level=level)

        kind = chapter_kind(
            str(node.get("title") or ""),
            node.get("part"),
            str(node.get("idea") or ""),
            str(node.get("requirement") or ""),
        )
        body_layout = layout if kind == "tech" else None

        content = chapter_contents.get(node["id"], "")
        if not content.strip():
            continue
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            if _is_table_row(lines[i]) or _is_table_sep(lines[i]):
                rows: list[list[str]] = []
                while i < len(lines) and (_is_table_row(lines[i]) or _is_table_sep(lines[i])):
                    if not _is_table_sep(lines[i]):
                        rows.append(_parse_table_row(lines[i]))
                    i += 1
                _add_markdown_table(document, rows, body_layout)
                continue
            render_markdown_block(document, lines[i], image_paths, body_layout)
            i += 1

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
