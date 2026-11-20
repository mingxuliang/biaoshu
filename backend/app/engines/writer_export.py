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

# 目录树最深能到几层。Word 自带 Heading 1~9；以前压到 3 层，6 层的目录导出后层级全丢了。
MAX_HEADING_LEVEL = 9
MAX_TOC_LEVELS = 5

_INLINE_SPLIT_RE = re.compile(r"(\*\*.+?\*\*|__.+?__|\*.+?\*)")
_FONT_WRAP_RE = re.compile(r"\{\{([^|:{}]+)[:|]([^}]+)\}\}(.*?)\{\{/\}\}", re.S)
_CELL_SPAN_RE = re.compile(r"^(?:#c(\d+)#)?(?:#r(\d+)#)?")
_BULLET_RE = re.compile(r"^[-*]\s+")
_NUMBERED_RE = re.compile(r"^\d+[）.)\]].*")
_CN_NUMBERED_RE = re.compile(r"^（[一二三四五六七八九十]+）")
_IMAGE_MD_RE = re.compile(r"^!\[([^\]]*)\]\((/api/writer-images/([^/]+)/file)\)$")
_CAPTION_RE = re.compile(r"^(图|表)\s*[：:]\s*(.+)$")
_TABLE_SEP_RE = re.compile(r"^(?:\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?|\|\s*:?-{2,}:?\s*\|)\s*$")


def _split_size_color(spec: str | None) -> tuple[str | None, str | None]:
    """字号段可带第三段颜色：16pt:C00000 → ("16pt", "C00000")。颜色只认 6 位十六进制。"""
    parts = [p.strip() for p in str(spec or "").split(":")]
    size = parts[0] or None
    color = parts[1].lstrip("#").upper() if len(parts) > 1 and re.fullmatch(r"#?[0-9A-Fa-f]{6}", parts[1]) else None
    return size, color


def _clear_theme_fonts(rFonts) -> None:
    """Word 优先用主题字体（等线/Calibri），不删掉就会和指定的宋体、黑体混在一起。"""
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        key = qn(attr)
        if key in rFonts.attrib:
            del rFonts.attrib[key]


def _clear_theme_color(rPr) -> None:
    color = rPr.find(qn("w:color"))
    if color is None:
        return
    for attr in ("w:themeColor", "w:themeTint", "w:themeShade"):
        key = qn(attr)
        if key in color.attrib:
            del color.attrib[key]


def _set_run_font(run, name: str | None, size: str | None, color: str | None = None, latin: str | None = None) -> None:
    rPr = run._element.get_or_add_rPr()
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
        _clear_theme_color(rPr)
    if name:
        run.font.name = latin or name
        rFonts = rPr.get_or_add_rFonts()
        _clear_theme_fonts(rFonts)
        western = latin or name
        rFonts.set(qn("w:ascii"), western)
        rFonts.set(qn("w:hAnsi"), western)
        rFonts.set(qn("w:eastAsia"), name)
        rFonts.set(qn("w:cs"), western)
    if size:
        m = re.match(r"([0-9.]+)", str(size).strip())
        if m:
            run.font.size = Pt(float(m.group(1)))


def _body_type(layout: dict | None) -> tuple[str, str | None, str]:
    font = str((layout or {}).get("bodyFont") or "仿宋")
    latin = str((layout or {}).get("bodyLatinFont") or "") or None
    return font, latin, f"{_layout_body_pt(layout):g}pt"


def _apply_line_spacing(paragraph, layout: dict | None) -> None:
    if not layout:
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        paragraph.paragraph_format.line_spacing = 1.5
        return
    exact = layout.get("lineSpacingExactPt")
    if exact:
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        paragraph.paragraph_format.line_spacing = Pt(float(exact))
        return
    at_least = layout.get("lineSpacingAtLeastPt")
    if at_least:
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
        paragraph.paragraph_format.line_spacing = Pt(float(at_least))
        return
    try:
        mul = float(layout["lineSpacingMul"]) if layout.get("lineSpacingMul") is not None else None
    except (TypeError, ValueError):
        mul = None
    spacing = str(layout.get("lineSpacing") or "")
    if spacing in ("固定值28磅", "固定值30磅") and mul is None:
        paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        paragraph.paragraph_format.line_spacing = Pt(_LINE_SPACING[spacing])
        return
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    paragraph.paragraph_format.line_spacing = mul if mul else _LINE_SPACING.get(spacing, 1.5)


def _add_inner_runs(
    paragraph,
    text: str,
    font: str | None = None,
    size: str | None = None,
    color: str | None = None,
    latin: str | None = None,
) -> None:
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
        _set_run_font(run, font, size, color, latin)


def _add_runs_with_inline_styles(
    paragraph, text: str, font: str | None = None, size: str | None = None, latin: str | None = None
) -> None:
    """导出时全段用同一套字体字号。编辑器里夹带的 {{楷体:10.5pt}} 不再写进 Word。"""
    raw = text or ""
    pos = 0
    for m in _FONT_WRAP_RE.finditer(raw):
        if m.start() > pos:
            _add_inner_runs(paragraph, raw[pos : m.start()], font, size, None, latin)
        _size, color = _split_size_color(m.group(2))
        _add_inner_runs(paragraph, m.group(3), font or m.group(1).strip(), size or _size, color, latin)
        pos = m.end()
    if pos == 0:
        _add_inner_runs(paragraph, raw, font, size, None, latin)
    elif pos < len(raw):
        _add_inner_runs(paragraph, raw[pos:], font, size, None, latin)


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


def _add_markdown_table(
    document, rows: list[list[str]], layout: dict | None = None, engineering: bool = False
) -> None:
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
    if engineering:
        _style_engineering_table(table, layout, parsed)
    else:
        _style_table(table, layout)


def _add_subtitle(document, text: str, level: int, layout: dict | None, align=None) -> None:
    """章节正文里的 `##` / `###` 小标题。

    只是加粗的小标题段落，不用 Word 的 Heading 样式：目录里的层级由大纲（目录树）决定，
    正文里的小标题如果也用 Heading，会和大纲同级标题混在一起，还会被塞进自动目录。
    """
    p = document.add_paragraph()
    p.paragraph_format.first_line_indent = Pt(0)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.bold = True
    spec = _heading_spec(layout, min(level, 3))
    # 正文里的「原始需求 / 解决方案」用黑体，比章标题小一号；更深的小标题跟正文字号，但仍是黑体。
    size_pt = float(spec["sizePt"]) if level <= 3 else _layout_body_pt(layout)
    _set_run_font(run, spec["font"], f"{size_pt:g}pt")
    run.font.color.rgb = RGBColor(0, 0, 0)
    _clear_theme_color(run._element.get_or_add_rPr())
    _apply_line_spacing(p, layout)
    if spec.get("spaceBefore") is not None:
        p.paragraph_format.space_before = Pt(float(spec["spaceBefore"]))
    if spec.get("spaceAfter") is not None:
        p.paragraph_format.space_after = Pt(float(spec["spaceAfter"]))
    if align is not None:
        p.alignment = align


def render_markdown_block(
    document, line: str, image_paths: dict[str, str] | None = None, layout: dict | None = None
) -> None:
    """把编辑器里的一行 markdown-lite 文本追加为 docx 段落/标题。"""
    align, body = _split_align(line)
    trimmed = body.strip()
    font, latin, size = _body_type(layout)
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
        _add_subtitle(document, _unwrap_inline(trimmed[4:]), 4, layout, align)
        return
    if trimmed.startswith("## "):
        _add_subtitle(document, _unwrap_inline(trimmed[3:]), 3, layout, align)
        return

    bullet_match = _BULLET_RE.match(trimmed)
    if bullet_match:
        p = document.add_paragraph()
        _add_runs_with_inline_styles(p, trimmed[bullet_match.end() :].strip(), font, size, latin)
        _apply_body_indent(p, trimmed, layout)
        _apply_line_spacing(p, layout)
        if align is not None:
            p.alignment = align
        return

    if _NUMBERED_RE.match(trimmed) or _CN_NUMBERED_RE.match(trimmed):
        p = document.add_paragraph()
        _add_runs_with_inline_styles(p, trimmed, font, size, latin)
        _apply_body_indent(p, trimmed, layout)
        _apply_line_spacing(p, layout)
        if align is not None:
            p.alignment = align
        return

    p = document.add_paragraph()
    _add_runs_with_inline_styles(p, trimmed, font, size, latin)
    _apply_body_indent(p, trimmed, layout)
    _apply_line_spacing(p, layout)
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
    _clear_theme_fonts(rFonts)
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
    headings = data.get("headings") if isinstance(data.get("headings"), dict) else {}
    # 设置里只定义 h1~h4；更深的层级沿用 h4 的样式
    custom = headings.get(f"h{min(level, 4)}")
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
        _clear_theme_color(run._element.get_or_add_rPr())


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
    left_pt = (layout or {}).get("leftIndentPt")
    if left_pt:
        paragraph.paragraph_format.left_indent = Pt(float(left_pt))
    hanging_pt = (layout or {}).get("hangingIndentPt")
    if hanging_pt:
        # Word 的悬挂缩进是「左缩进 + 负的首行缩进」，和首行缩进互斥
        paragraph.paragraph_format.first_line_indent = Pt(-float(hanging_pt))
        return
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


def _set_table_borders(table, color: str, size_pt: float) -> None:
    tbl_pr = table._tbl.tblPr
    for old in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(old)
    borders = OxmlElement("w:tblBorders")
    sz = str(max(2, round(float(size_pt) * 8)))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), sz)
        edge.set(qn("w:space"), "0")
        edge.set(qn("w:color"), color.upper())
        borders.append(edge)
    tbl_pr.append(borders)


def _style_table(table, layout: dict | None) -> None:
    """表头底色、表内字号、居中、边框色。没有排版配置时保持原样。"""
    cfg = (layout or {}).get("table") if isinstance((layout or {}).get("table"), dict) else None
    if not cfg:
        return
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if cfg.get("borderColor"):
        _set_table_borders(table, str(cfg["borderColor"]), float(cfg.get("borderSizePt") or 0.5))
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
                    body_font, body_latin, body_size = _body_type(layout)
                    _set_run_font(run, body_font, f"{float(size):g}pt" if size else body_size, latin=body_latin)
                    if r == 0 and bold:
                        run.bold = True


_ENG_PAIR_HEADERS = {"项目", "内容", "具体内容", "名称", "说明", "类别", "管理目标", "措施", "要求"}
_ENG_LABEL_FILL = "F2F2F2"
_ENG_HEADER_FILL = "D9D9D9"


def _style_engineering_table(table, layout: dict | None, parsed: list[list[dict]]) -> None:
    """工程施工组织设计的三种表：一格框表（整段正文装在一个格里）、「项目｜内容」两列表、多列数据表。

    没有排版配置也要成形：框表左对齐不缩进；两列表左列底色居中；数据表表头底色加粗、短格居中。
    """
    from docx.enum.table import WD_ALIGN_VERTICAL

    cfg = (layout or {}).get("table") if isinstance((layout or {}).get("table"), dict) else {}
    size = cfg.get("fontSizePt")
    header_fill = str(cfg.get("headerFill") or _ENG_HEADER_FILL)
    cols = len(table.columns)
    first_row = [str(c.get("text") or "").strip() for c in (parsed[0] if parsed else [])]
    pair_header = cols == 2 and bool(first_row) and all(t in _ENG_PAIR_HEADERS for t in first_row)
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            text = cell.text.strip()
            header = r == 0 and (cols >= 3 or pair_header)
            label = cols == 2 and c == 0 and not header
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if header:
                _shade(cell, header_fill)
            elif label:
                _shade(cell, _ENG_LABEL_FILL)
            if cols == 2:
                cell.width = Cm(3.2) if c == 0 else Cm(12.8)
            for p in cell.paragraphs:
                p.paragraph_format.first_line_indent = Pt(0)
                if cols == 1:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                elif header or label or (cols >= 3 and len(text) <= 12):
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in p.runs:
                    body_font, body_latin, body_size = _body_type(layout)
                    _set_run_font(run, body_font, f"{float(size):g}pt" if size else body_size, latin=body_latin)
                    if header or label:
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
    if cfg.get("spaceAfter") is not None:
        p.paragraph_format.space_after = Pt(float(cfg["spaceAfter"]))
    if kind == "表":
        p.paragraph_format.keep_with_next = True


def _add_cover(document, layout: dict, project_name: str) -> None:
    """封面：标题（可两行）、副标题（如《技 术 投 标 书》）、投标单位等信息。

    字体字号取 cover.titleFont/subtitleFont/infoFont 等；没配置就退回标题样式，
    和以前只有一种封面字号的版本兼容。
    """
    cover = layout.get("cover") if isinstance(layout.get("cover"), dict) else {}
    title = resolve_text(str(cover.get("title") or "{project}"), project_name) or "投标文件"
    spec = _heading_spec(layout, 1)
    title_font = cover.get("titleFont") or spec["font"]
    title_size = f"{float(cover['titleSizePt']):g}pt" if cover.get("titleSizePt") else "26pt"
    sub_font = cover.get("subtitleFont") or spec["font"]
    sub_size = f"{float(cover['subtitleSizePt']):g}pt" if cover.get("subtitleSizePt") else "20pt"
    info_font = cover.get("infoFont") or spec["font"]
    info_size = f"{float(cover['infoSizePt']):g}pt" if cover.get("infoSizePt") else "14pt"
    info_gap = Pt(float(cover["infoSpaceAfter"])) if cover.get("infoSpaceAfter") is not None else None

    for _ in range(6):
        document.add_paragraph("")
    for line in str(title).split("\n"):
        if not line.strip():
            continue
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(line)
        _set_run_font(run, title_font, title_size)
        run.bold = True
    if cover.get("subtitle"):
        sub = document.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.paragraph_format.space_before = Pt(24)
        run = sub.add_run(str(cover["subtitle"]))
        _set_run_font(run, sub_font, sub_size)
        run.bold = True
    for _ in range(8):
        document.add_paragraph("")
    for key in ("company", "date"):
        if cover.get(key):
            line = document.add_paragraph()
            line.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if info_gap is not None:
                line.paragraph_format.space_after = info_gap
            run = line.add_run(resolve_text(str(cover[key]), project_name))
            _set_run_font(run, info_font, info_size)
    document.add_page_break()


def _add_toc(document, layout: dict) -> None:
    toc = layout.get("toc") if isinstance(layout.get("toc"), dict) else {}
    levels = max(1, min(int(toc.get("levels") or 3), MAX_TOC_LEVELS))
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


def _header_bottom_border(paragraph) -> None:
    """页眉下方一条细线，V4-1 模板里页眉和正文之间的分隔线。"""
    pPr = paragraph._p.get_or_add_pPr()
    borders = pPr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        pPr.append(borders)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    borders.append(bottom)


def _apply_header_footer(document, layout: dict, project_name: str) -> None:
    section = document.sections[0]
    header_font = layout.get("headerFont") or layout.get("bodyFont")
    header_size = f"{float(layout['headerSizePt']):g}pt" if layout.get("headerSizePt") else "9pt"
    footer_font = layout.get("footerFont") or layout.get("bodyFont")
    footer_size = f"{float(layout['footerSizePt']):g}pt" if layout.get("footerSizePt") else "9pt"

    text = resolve_text(str(layout.get("header") or ""), project_name)
    if text:
        p = section.header.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        _set_run_font(run, header_font, header_size)
        if layout.get("headerBorder"):
            _header_bottom_border(p)
    mode = layout.get("pageNumber")
    if mode in ("simple", "full"):
        p = section.footer.paragraphs[0]
        p.text = ""
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if mode == "full":
            _set_run_font(p.add_run("第 "), footer_font, footer_size)
            _add_field(p, "PAGE", "1", footer_font, footer_size)
            _set_run_font(p.add_run(" 页 共 "), footer_font, footer_size)
            _add_field(p, "NUMPAGES", "1", footer_font, footer_size)
            _set_run_font(p.add_run(" 页"), footer_font, footer_size)
        else:
            _add_field(p, "PAGE", "1", footer_font, footer_size)
    if layout.get("differentFirstPage") and (text or mode in ("simple", "full")):
        section.different_first_page_header_footer = True
        # 首页页眉页脚清空，和正文页用的是同一个 section 但首页另算一份
        section.first_page_header.paragraphs[0].text = ""
        section.first_page_footer.paragraphs[0].text = ""
    if layout.get("headerDistanceCm") is not None:
        section.header_distance = Cm(float(layout["headerDistanceCm"]))
    if layout.get("footerDistanceCm") is not None:
        section.footer_distance = Cm(float(layout["footerDistanceCm"]))


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

    for level in range(1, MAX_HEADING_LEVEL + 1):
        try:
            hstyle = document.styles[f"Heading {level}"]
        except KeyError:
            continue
        spec = _heading_spec(layout, level)
        _set_style_font(hstyle, spec["font"], float(spec["sizePt"]), latin)
        hstyle.font.bold = bool(spec["bold"])
        hstyle.font.color.rgb = _rgb(spec.get("color"))
        _clear_theme_color(hstyle.element.get_or_add_rPr())
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


def _splice_original_xml(document, xml_blocks: list[str]) -> bool:
    """把招标书附录格式的原始段落和表格接到文档末尾，保留原表的边框、列宽、合并单元格。"""
    from lxml import etree

    from .safe_office import SAFE_PARSER

    body = document.element.body
    sect = body.find(qn("w:sectPr"))
    valid_styles = {st.style_id for st in document.styles}
    added = 0
    for xml in xml_blocks:
        try:
            element = etree.fromstring(xml.encode("utf-8"), parser=SAFE_PARSER)
        except etree.XMLSyntaxError:
            continue
        for tag in ("w:drawing", "w:pict", "w:sectPr", "w:numPr"):
            for node in list(element.iter(qn(tag))):
                node.getparent().remove(node)
        for style_tag, style_attr in (("w:pStyle", "w:val"), ("w:tblStyle", "w:val"), ("w:rStyle", "w:val")):
            for node in list(element.iter(qn(style_tag))):
                if node.get(qn(style_attr)) not in valid_styles:
                    node.getparent().remove(node)
        if element.tag == qn("w:tbl"):
            props = element.find(qn("w:tblPr"))
            if props is not None and props.find(qn("w:tblBorders")) is None and props.find(qn("w:tblStyle")) is None:
                borders = etree.SubElement(props, qn("w:tblBorders"))
                for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                    edge = etree.SubElement(borders, qn(f"w:{side}"))
                    edge.set(qn("w:val"), "single")
                    edge.set(qn("w:sz"), "4")
                    edge.set(qn("w:space"), "0")
                    edge.set(qn("w:color"), "000000")
        if sect is not None:
            sect.addprevious(element)
        else:
            body.append(element)
        added += 1
    return added > 0


def _export_layout(layout: dict | None) -> dict:
    """导出统一用技术标标准。招标书自动识别的小字号，以及没写标题样式的旧配置，都改回这套。"""
    from .writer_layout import default_writing_layout

    base = default_writing_layout()
    if not isinstance(layout, dict):
        return base
    if layout.get("fromTender") or not isinstance(layout.get("headings"), dict):
        kept = dict(base)
        for key, value in layout.items():
            if key in ("fromTender", "headings") or value is None:
                continue
            if key in ("bodyFont", "bodySizePt", "fontSize", "bodyLatinFont", "indentPt", "indentChars"):
                continue
            kept[key] = value
        return kept
    return layout


def _add_doc_title(document, text: str, layout: dict | None) -> None:
    """封面关闭时的文首标题。不用 Word 的 Title 样式，避免变成另一套英文字体。"""
    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Pt(0)
    spec = _heading_spec(layout, 1)
    run = p.add_run(text)
    run.bold = True
    _set_run_font(run, spec["font"], f"{float(spec['sizePt']):g}pt")
    run.font.color.rgb = RGBColor(0, 0, 0)
    _clear_theme_color(run._element.get_or_add_rPr())
    _apply_line_spacing(p, layout)


def chapters_to_docx(
    project_name: str,
    outline: list[dict],
    chapter_contents: dict[str, str],
    image_paths: dict[str, str] | None = None,
    layout: dict | None = None,
    form_registry: list[dict] | None = None,
    engineering: bool = False,
    only_chapter_ids: set[str] | None = None,
) -> bytes:
    """按目录顺序把全部章节内容拼接为一份完整 .docx。engineering=工程类技术标，表格按施工组织设计样式。

    only_chapter_ids 给定时只输出这些章节（版式预览用）：不加封面、文首标题和目录，
    其余——版式、字体、页边距、页眉页脚、每章的排版代码——和整本导出完全是同一条路径。
    """
    from .e_writer import chapter_kind

    layout = _export_layout(layout)
    document = docx.Document()
    _apply_layout(document, layout, project_name)
    cover_on = bool(layout and isinstance(layout.get("cover"), dict) and layout["cover"].get("enabled"))
    toc_on = bool(layout and isinstance(layout.get("toc"), dict) and layout["toc"].get("enabled"))
    if only_chapter_ids is None:
        if cover_on:
            _add_cover(document, layout, project_name)
        elif project_name:
            _add_doc_title(document, project_name, layout)
        if toc_on:
            _add_toc(document, layout)

    for node in outline:
        if only_chapter_ids is not None and node.get("id") not in only_chapter_ids:
            continue
        level = min(_node_level(outline, node["id"]) + 1, MAX_HEADING_LEVEL)
        heading_text = f"{node.get('num', '')} {node.get('title', '')}".strip()
        heading = document.add_heading(heading_text, level=level)
        _restyle_heading(heading, layout, level)

        kind = chapter_kind(
            str(node.get("title") or ""),
            node.get("part"),
            str(node.get("idea") or ""),
            str(node.get("requirement") or ""),
        )
        body_layout = layout if kind in ("tech", "response") else None

        content = chapter_contents.get(node["id"], "")
        if not content.strip():
            continue
        form_keys = [k for k in (node.get("formKeys") or []) if isinstance(k, int)]
        if form_keys and form_registry:
            from .form_registry import ooxml_for_chapter, pasted_matches_original

            kinds = {str(form_registry[k].get("kind")) for k in form_keys if 0 <= k < len(form_registry)}
            if not kinds & {"deviation", "quote", "team"} and pasted_matches_original(content, form_keys, form_registry):
                if _splice_original_xml(document, ooxml_for_chapter(form_keys, form_registry)):
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
                _add_markdown_table(
                    document, rows, body_layout, engineering=engineering and node.get("part") == "tech"
                )
                continue
            render_markdown_block(document, lines[i], image_paths, body_layout)
            i += 1

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


DOC_KIND_LABEL = {"tech": "技术标", "business": "商务标"}


def blind_layout(layout: dict | None, bidder_names: list[str] | None = None) -> dict | None:
    """暗标版式：封面不写公司和日期，页眉里的单位名称删掉。其余排版不动。"""
    if not isinstance(layout, dict):
        return layout
    out = dict(layout)
    cover = dict(out.get("cover") or {})
    if cover:
        cover["company"] = ""
        cover["date"] = ""
        out["cover"] = cover
    header = str(out.get("header") or "")
    for name in sorted({n.strip() for n in (bidder_names or []) if n and n.strip()}, key=len, reverse=True):
        header = header.replace(name, "")
    out["header"] = header.strip()
    return out


def draft_filename(project_name: str, doc_kind: str) -> str:
    """技术标、商务标两份草稿导出的文件名要能分开。"""
    label = DOC_KIND_LABEL.get(doc_kind or "tech", "技术标")
    return f"{project_name or '投标书'}-{label}（撰写工作台导出）.docx"


def build_draft_export(db, draft) -> tuple[bytes, str, str]:
    """撰写工作台导出的统一入口，路由和对话工具共用。返回 (docx 字节, 显示文件名, 分册)。"""
    docx_bytes, project_name, doc_kind = build_draft_docx(db, draft)
    return docx_bytes, draft_filename(project_name, doc_kind), doc_kind


def subtree_ids(outline: list[dict], node_id: str) -> list[str]:
    """某个目录节点自己和它的所有子孙，按目录顺序。"""
    wanted = {node_id}
    changed = True
    while changed:
        changed = False
        for node in outline:
            if node.get("parentId") in wanted and node.get("id") not in wanted:
                wanted.add(node["id"])
                changed = True
    return [n["id"] for n in outline if n.get("id") in wanted]


def build_draft_docx(db, draft, chapter_ids: set[str] | None = None) -> tuple[bytes, str, str]:
    """生成 docx。chapter_ids=None 为整本导出，否则只含这些章节（版式预览）。返回 (docx, 项目名, 分册)。

    技术册且招标文件要求暗标时，封面和页眉不带公司信息。
    """
    from .. import storage
    from ..models import Project, QualificationAsset, WriterImage
    from . import rules_config
    from .category_profile import tender_requires_anonymity
    from .parse_schema import is_engineering_category

    doc_kind = draft.doc_kind if draft.doc_kind in DOC_KIND_LABEL else "tech"
    project = db.get(Project, draft.project_id)
    project_name = project.name if project else ""
    images = db.query(WriterImage).filter(WriterImage.project_id == draft.project_id).all()
    refs = {img.id: img.storage_path for img in images}
    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    layout = settings.get("layout")

    if doc_kind == "tech":
        params, _ = rules_config.load_locked_checklist(db, draft.project_id)
        if tender_requires_anonymity(params):
            names = [
                (row.owner or "").strip()
                for row in db.query(QualificationAsset).filter(QualificationAsset.review_status == "已入库").all()
                if (row.kind or "") == "cert" and "营业执照" in (row.name or "")
            ]
            layout = blind_layout(layout, names)

    with storage.as_local_map(refs) as image_paths:
        docx_bytes = chapters_to_docx(
            project_name,
            draft.outline_json or [],
            draft.chapter_contents_json or {},
            image_paths,
            layout,
            settings.get("formRegistry"),
            engineering=doc_kind == "tech" and is_engineering_category(project.category if project else ""),
            only_chapter_ids=chapter_ids,
        )
    return docx_bytes, project_name, doc_kind
