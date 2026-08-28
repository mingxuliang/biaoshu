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
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Inches

_INLINE_SPLIT_RE = re.compile(r"(\*\*.+?\*\*|__.+?__|\*.+?\*)")
_FONT_WRAP_RE = re.compile(r"\{\{([^|}]+)\|([^}]+)\}\}(.*?)\{\{/\}\}", re.S)
_BULLET_RE = re.compile(r"^[-*]\s+")
_NUMBERED_RE = re.compile(r"^\d+[）.)\]].*")
_CN_NUMBERED_RE = re.compile(r"^（[一二三四五六七八九十]+）")
_IMAGE_MD_RE = re.compile(r"^!\[([^\]]*)\]\((/api/writer-images/([^/]+)/file)\)$")
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
    if t.endswith("|"):
        t = t[:-1]
    return [c.strip() for c in t.split("|")]


def _add_markdown_table(document, rows: list[list[str]]) -> None:
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = document.add_table(rows=len(rows), cols=max(cols, 1))
    table.style = "Table Grid"
    for i, row in enumerate(rows):
        for j in range(cols):
            cell = table.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            _add_runs_with_inline_styles(p, row[j] if j < len(row) else "")


def render_markdown_block(document, line: str, image_paths: dict[str, str] | None = None) -> None:
    """把编辑器里的一行 markdown-lite 文本追加为 docx 段落/标题。"""
    align, body = _split_align(line)
    trimmed = body.strip()
    if not trimmed:
        document.add_paragraph("")
        return

    img_match = _IMAGE_MD_RE.match(trimmed)
    if img_match:
        image_id = img_match.group(3)
        path = (image_paths or {}).get(image_id)
        if path and os.path.exists(path):
            try:
                document.add_picture(path, width=Inches(5.4))
            except Exception:  # noqa: BLE001 —— 坏图不阻断整份导出
                document.add_paragraph(f"[图片无法嵌入：{img_match.group(1) or image_id}]")
        else:
            document.add_paragraph(f"[图片缺失：{img_match.group(1) or image_id}]")
        return

    if trimmed.startswith("### "):
        p = document.add_heading(trimmed[4:], level=3)
        if align is not None:
            p.alignment = align
        return
    if trimmed.startswith("## "):
        p = document.add_heading(trimmed[3:], level=2)
        if align is not None:
            p.alignment = align
        return

    bullet_match = _BULLET_RE.match(trimmed)
    if bullet_match:
        p = document.add_paragraph(style="List Bullet")
        _add_runs_with_inline_styles(p, trimmed[bullet_match.end():].strip())
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
    if align is not None:
        p.alignment = align


def _node_level(outline: list[dict], node_id: str, _depth: int = 0) -> int:
    node = next((n for n in outline if n.get("id") == node_id), None)
    if not node or not node.get("parentId"):
        return _depth
    return _node_level(outline, node["parentId"], _depth + 1)


_FONT_PT = {"小三": 15, "小四": 12, "四号": 14, "三号": 16}
_LINE_SPACING = {
    "1.5倍行距": 1.5,
    "2倍行距": 2.0,
    "固定值28磅": 28,
    "固定值30磅": 30,
}


def _apply_layout(document, layout: dict | None) -> None:
    if not layout:
        return
    section = document.sections[0]
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

    style = document.styles["Normal"]
    font = style.font
    font.name = "宋体"
    font.size = Pt(_FONT_PT.get(str(layout.get("fontSize") or ""), 12))

    pf = style.paragraph_format
    spacing = layout.get("lineSpacing")
    multiple = _LINE_SPACING.get(str(spacing or ""), 1.5)
    if spacing in ("固定值28磅", "固定值30磅"):
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(multiple)
    else:
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = multiple


def chapters_to_docx(
    project_name: str,
    outline: list[dict],
    chapter_contents: dict[str, str],
    image_paths: dict[str, str] | None = None,
    layout: dict | None = None,
) -> bytes:
    """按目录顺序把全部章节内容拼接为一份完整 .docx。"""
    document = docx.Document()
    _apply_layout(document, layout)
    if project_name:
        document.add_heading(project_name, level=0)

    for node in outline:
        level = min(_node_level(outline, node["id"]) + 1, 3)
        heading_text = f"{node.get('num', '')} {node.get('title', '')}".strip()
        document.add_heading(heading_text, level=level)

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
                _add_markdown_table(document, rows)
                continue
            render_markdown_block(document, lines[i], image_paths)
            i += 1

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
