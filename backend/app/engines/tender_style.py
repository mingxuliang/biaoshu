"""从招标书抽取正文字体/字号/首行缩进，供技术标按该份文件排版。

优先读「用户需求书 / 技术规范」正文的实际 Word 样式；若招标书里写了
「正文宋体小四、首行缩进 2 字符」等格式条款，则与抽样互相补全。
不同招标书结果不同，不做全局写死。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from statistics import median

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .tender_form import _is_heading, _run_font_name, _run_font_size_pt

logger = logging.getLogger(__name__)

_PT_NAME = {
    9: "小五",
    10.5: "五号",
    12: "小四",
    14: "四号",
    15: "小三",
    16: "三号",
    18: "小二",
    22: "二号",
}
_NAME_PT = {v: k for k, v in _PT_NAME.items()}
_NAME_PT["五号"] = 10.5

_TECH_START = re.compile(r"(用户需求书|用户需求|技术规范|技术要求|采购需求|建设内容)")
_TECH_END = re.compile(r"(响应文件格式|投标文件格式|报价部分|商务和技术偏差|资格审查)")
_STATED_FACE = re.compile(r"(正文|正文字体|汉字)[^。；\n]{0,12}(宋体|仿宋|楷体|黑体|微软雅黑)")
_STATED_SIZE = re.compile(r"(正文|正文字体|汉字)?[^。；\n]{0,16}(小五|五号|小四|四号|小三|三号|小二|二号)")
_STATED_INDENT = re.compile(r"首行缩进\s*([一二两2])\s*(个)?(字符|字|汉字)")
_STATED_SPACING = re.compile(r"(1\.5|1.5|2)\s*倍行距")


def pt_to_size_name(pt: float) -> str:
    best = "小四"
    dist = 99.0
    for n, name in _PT_NAME.items():
        d = abs(float(pt) - n)
        if d < dist:
            dist = d
            best = name
    return best


def extract_tender_typography(path: str) -> dict:
    document = docx.Document(path)
    paras: list[tuple[Paragraph, str]] = []
    for child in document.element.body.iterchildren():
        if child.tag != qn("w:p"):
            continue
        para = Paragraph(child, document)
        text = (para.text or "").strip()
        if text:
            paras.append((para, text))

    stated = _stated_rules("\n".join(t for _, t in paras))
    start, end = _tech_span(paras)
    sampled = _sample_section(paras[start:end] or paras)
    out = {**sampled, **{k: v for k, v in stated.items() if v is not None}}
    if not out.get("bodyFont"):
        out["bodyFont"] = "宋体"
    if not out.get("bodySizePt"):
        out["bodySizePt"] = 12.0
    out["fontSize"] = pt_to_size_name(float(out["bodySizePt"]))
    if out.get("indentPt") and not out.get("indentChars"):
        out["indentChars"] = max(1, min(4, round(float(out["indentPt"]) / float(out["bodySizePt"]))))
    if out.get("indentChars") and not out.get("indentPt"):
        out["indentPt"] = round(float(out["indentChars"]) * float(out["bodySizePt"]), 1)
    if not out.get("headingFont"):
        out["headingFont"] = out["bodyFont"]
    if not out.get("headingSizePt"):
        out["headingSizePt"] = out["bodySizePt"]
    out.setdefault("headingBold", True)
    return out


def extract_bid_typography(path: str) -> dict:
    """投标文件（不区分技术标/商务标）整体的字体/字号/首行缩进画像，
    供「修改闭环」编辑器按投标书原文样式还原展示，而非固定编辑器默认样式。
    与 extract_tender_typography 的区别：不找「技术规范」子区间、不找招标书里
    「正文宋体小四」之类的声明文字，直接对全文段落抽样。
    """
    document = docx.Document(path)
    paras: list[tuple[Paragraph, str]] = []
    for child in document.element.body.iterchildren():
        if child.tag != qn("w:p"):
            continue
        para = Paragraph(child, document)
        text = (para.text or "").strip()
        if text:
            paras.append((para, text))

    out = _sample_section(paras)
    if not out.get("bodyFont"):
        out["bodyFont"] = "宋体"
    if not out.get("bodySizePt"):
        out["bodySizePt"] = 12.0
    out["fontSize"] = pt_to_size_name(float(out["bodySizePt"]))
    if not out.get("headingFont"):
        out["headingFont"] = out["bodyFont"]
    if not out.get("headingSizePt"):
        out["headingSizePt"] = out["bodySizePt"]
    out.setdefault("headingBold", True)
    return out


def extract_tender_typography_from_storage(storage_path: str) -> dict:
    from .. import storage
    from .legacy_doc import as_docx

    with storage.as_local(storage_path) as local:
        with as_docx(local) as word_path:
            return extract_tender_typography(word_path)


def apply_tech_markdown_style(md: str, layout: dict | None) -> str:
    """给技术标 markdown 补上招标书正文字体；已有 {{font:size}} 的行不改。"""
    if not md or not isinstance(layout, dict):
        return md
    font = str(layout.get("bodyFont") or "宋体")
    try:
        pt = float(layout.get("bodySizePt") or 12)
    except (TypeError, ValueError):
        pt = 12.0
    hfont = str(layout.get("headingFont") or font)
    try:
        hpt = float(layout.get("headingSizePt") or pt)
    except (TypeError, ValueError):
        hpt = pt
    hbold = bool(layout.get("headingBold", True))

    def wrap(face: str, size: float, text: str) -> str:
        return "{{" + f"{face}:{size:g}pt" + "}}" + text + "{{/}}"

    out: list[str] = []
    for raw in (md or "").split("\n"):
        line = raw
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("![") or "{{" in line:
            out.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            title = heading.group(2).strip()
            inner = f"**{title}**" if hbold and not title.startswith("**") else title
            out.append(f"{heading.group(1)} {wrap(hfont, hpt, inner)}")
            continue
        bullet = re.match(r"^([-*]\s+)(.*)$", stripped)
        if bullet:
            out.append(f"{bullet.group(1)}{wrap(font, pt, bullet.group(2))}")
            continue
        numbered = re.match(r"^(\d+[.)]\s+)(.*)$", stripped)
        if numbered:
            out.append(f"{numbered.group(1)}{wrap(font, pt, numbered.group(2))}")
            continue
        out.append(wrap(font, pt, stripped))
    return "\n".join(out)


def _stated_rules(blob: str) -> dict:
    out: dict = {}
    m = _STATED_FACE.search(blob)
    if m:
        out["bodyFont"] = m.group(2)
    m = _STATED_SIZE.search(blob)
    if m:
        name = m.group(2)
        out["fontSize"] = name
        out["bodySizePt"] = float(_NAME_PT.get(name, 12))
    m = _STATED_INDENT.search(blob)
    if m:
        n = 2 if m.group(1) in ("一", "二", "两", "2") else 2
        out["indentChars"] = n
    m = _STATED_SPACING.search(blob)
    if m:
        mul = 2.0 if m.group(1).startswith("2") else 1.5
        out["lineSpacingMul"] = mul
        out["lineSpacing"] = "2倍行距" if mul == 2 else "1.5倍行距"
    return out


def _tech_span(paras: list[tuple[Paragraph, str]]) -> tuple[int, int]:
    start = 0
    end = len(paras)
    for i, (_p, text) in enumerate(paras):
        if len(text) <= 24 and _TECH_START.search(text) and not text.startswith("1."):
            start = i
            break
    for j in range(start + 1, len(paras)):
        text = paras[j][1]
        if len(text) <= 24 and _TECH_END.search(text):
            end = j
            break
    if end - start < 8:
        return 0, len(paras)
    return start, end


def _first_run_style(para: Paragraph) -> tuple[str, float, bool]:
    for run in para.runs:
        if not (run.text or "").strip():
            continue
        return _run_font_name(run, para), _run_font_size_pt(run, para), bool(run.bold)
    return "宋体", 12.0, False


def _first_indent_pt(para: Paragraph) -> float | None:
    try:
        indent = para.paragraph_format.first_line_indent
        if indent and indent.pt >= 10:
            return round(float(indent.pt), 1)
    except Exception:
        return None
    return None


def _sample_section(paras: list[tuple[Paragraph, str]]) -> dict:
    body_faces: Counter[str] = Counter()
    body_pts: list[float] = []
    indents: list[float] = []
    head_faces: Counter[str] = Counter()
    head_pts: list[float] = []
    head_bold = 0
    head_n = 0
    for para, text in paras:
        if len(text) < 6:
            continue
        face, pt, bold = _first_run_style(para)
        heading = _is_heading(para, text) or (len(text) <= 32 and bold)
        if heading:
            head_faces[face] += 1
            head_pts.append(pt)
            head_n += 1
            if bold:
                head_bold += 1
            continue
        if len(text) < 12:
            continue
        body_faces[face] += 1
        body_pts.append(pt)
        ind = _first_indent_pt(para)
        if ind:
            indents.append(ind)
    out: dict = {}
    if body_faces:
        out["bodyFont"] = body_faces.most_common(1)[0][0]
    if body_pts:
        out["bodySizePt"] = float(median(body_pts))
    body_n = sum(body_faces.values()) or 1
    if indents and len(indents) / body_n >= 0.25:
        out["indentPt"] = float(median(indents))
        out["indentChars"] = max(1, min(4, round(out["indentPt"] / float(out.get("bodySizePt") or 12))))
    else:
        out["indentPt"] = 0
        out["indentChars"] = 0
    if head_faces:
        out["headingFont"] = head_faces.most_common(1)[0][0]
    if head_pts:
        out["headingSizePt"] = float(median(head_pts))
    if head_n:
        out["headingBold"] = head_bold / head_n >= 0.4
    return out
