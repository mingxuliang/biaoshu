"""撰写工作台 Word 排版配置：预设模板、合并校验、文字说明。

前端设置页、对话工具 set_layout 和导出共用同一份配置，字段兼容旧版
（margins / fontSize / lineSpacing / bodyFont / headingFont ...）。
"""

from __future__ import annotations

import copy
import re

FONT_SIZE_PT: dict[str, float] = {
    "初号": 42,
    "小初": 36,
    "一号": 26,
    "小一": 24,
    "二号": 22,
    "小二": 18,
    "三号": 16,
    "小三": 15,
    "四号": 14,
    "小四": 12,
    "五号": 10.5,
    "小五": 9,
    "六号": 7.5,
    "小六": 6.5,
    "七号": 5.5,
    "八号": 5,
}
_PT_TO_NAME = {value: key for key, value in FONT_SIZE_PT.items()}

# 招标书识别出来的正文格式，选模板时不能被覆盖
TENDER_KEYS = ("bodyFont", "bodySizePt", "fontSize", "indentPt", "indentChars")

_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_ALIGNS = ("left", "center", "right", "justify")

PRESETS: dict[str, dict] = {
    # 取自《自然资源综合业务管理智能框架及智能体研发项目》技术标配图优化版：
    # 章黑体小二，节黑体小三，条黑体 13 磅，正文仿宋小四、首行缩进 2 字、1.5 倍行距。
    "技术标标准": {
        "preset": "技术标标准",
        "margins": {"top": 3.7, "bottom": 3.5, "left": 2.8, "right": 2.6},
        "bodyFont": "仿宋",
        "bodyLatinFont": "Times New Roman",
        "fontSize": "小四",
        "bodySizePt": 12,
        "lineSpacing": "1.5倍行距",
        "lineSpacingMul": 1.5,
        "indentChars": 2,
        "indentPt": 24,
        "justify": False,
        # 实测自《自然资源…》V4-1：章节标题段前段后为 0（不是旧版的 12/6），多出第四级条款标题
        "headings": {
            "h1": {"font": "黑体", "sizePt": 18, "bold": True, "align": "left", "spaceBefore": 0, "spaceAfter": 0},
            "h2": {"font": "黑体", "sizePt": 15, "bold": True, "align": "left", "spaceBefore": 0, "spaceAfter": 0},
            "h3": {"font": "黑体", "sizePt": 13, "bold": True, "align": "left", "spaceBefore": 0, "spaceAfter": 0},
            "h4": {"font": "黑体", "sizePt": 12, "bold": True, "align": "left", "spaceBefore": 0, "spaceAfter": 0},
        },
        "pageNumber": "full",
        "header": "{project}  技术投标书",
        "headerFont": "仿宋",
        "headerSizePt": 9,
        "headerBorder": True,
        "headerDistanceCm": 1.5,
        "footerFont": "仿宋",
        "footerSizePt": 10.5,
        "footerDistanceCm": 2.0,
        "differentFirstPage": True,
        "orientation": "portrait",
        "cover": {
            "enabled": False,
            "title": "{project}",
            "subtitle": "技 术 投 标 书",
            "company": "投标单位：（投标人名称）",
            "date": "编制日期：",
            "titleFont": "方正小标宋简体",
            "titleSizePt": 32,
            "subtitleFont": "黑体",
            "subtitleSizePt": 44,
            "infoFont": "仿宋",
            "infoSizePt": 16,
            "infoSpaceAfter": 12,
        },
        "toc": {"enabled": False, "levels": 3},
        "table": {"headerFill": "E8E8E8", "fontSizePt": 10.5, "headerBold": True, "borderColor": "808080", "borderSizePt": 0.5},
        "caption": {"font": "黑体", "sizePt": 10.5, "spaceAfter": 10},
    },
    "政府采购标准": {
        "preset": "政府采购标准",
        "margins": {"top": 2.54, "bottom": 2.54, "left": 3.17, "right": 3.17},
        "bodyFont": "宋体",
        "bodyLatinFont": "Times New Roman",
        "fontSize": "小四",
        "bodySizePt": 12,
        "lineSpacing": "1.5倍行距",
        "lineSpacingMul": 1.5,
        "indentChars": 2,
        "indentPt": 24,
        "justify": True,
        "headings": {
            "h1": {"font": "黑体", "sizePt": 16, "bold": True, "align": "center", "spaceBefore": 18, "spaceAfter": 12},
            "h2": {"font": "黑体", "sizePt": 14, "bold": True, "align": "left", "spaceBefore": 12, "spaceAfter": 6},
            "h3": {"font": "宋体", "sizePt": 12, "bold": True, "align": "left", "spaceBefore": 6, "spaceAfter": 6},
        },
        "pageNumber": "full",
        "header": "",
        "orientation": "portrait",
        "cover": {"enabled": False},
        "toc": {"enabled": False, "levels": 3},
        "table": {"headerFill": "D9D9D9", "fontSizePt": 10.5, "headerBold": True},
        "caption": {"font": "宋体", "sizePt": 10.5},
    },
    "工程投标标准": {
        "preset": "工程投标标准",
        "margins": {"top": 2.54, "bottom": 2.54, "left": 2.8, "right": 2.6},
        "bodyFont": "仿宋",
        "bodyLatinFont": "Times New Roman",
        "fontSize": "四号",
        "bodySizePt": 14,
        "lineSpacing": "固定值28磅",
        "lineSpacingMul": None,
        "lineSpacingExactPt": 28,
        "indentChars": 2,
        "indentPt": 28,
        "justify": True,
        "headings": {
            "h1": {"font": "黑体", "sizePt": 22, "bold": True, "align": "center", "spaceBefore": 24, "spaceAfter": 18},
            "h2": {"font": "黑体", "sizePt": 16, "bold": True, "align": "left", "spaceBefore": 14, "spaceAfter": 8},
            "h3": {"font": "黑体", "sizePt": 14, "bold": True, "align": "left", "spaceBefore": 8, "spaceAfter": 6},
        },
        "pageNumber": "full",
        "header": "{project}",
        "orientation": "portrait",
        "cover": {"enabled": True, "title": "{project}", "subtitle": "投标文件", "company": "", "date": ""},
        "toc": {"enabled": True, "levels": 3},
        "table": {"headerFill": "D9D9D9", "fontSizePt": 12, "headerBold": True},
        "caption": {"font": "宋体", "sizePt": 12},
    },
    "简洁商务": {
        "preset": "简洁商务",
        "margins": {"top": 2.2, "bottom": 2.2, "left": 2.2, "right": 2.2},
        "bodyFont": "微软雅黑",
        "bodyLatinFont": "Calibri",
        "fontSize": "五号",
        "bodySizePt": 10.5,
        "lineSpacing": "1.5倍行距",
        "lineSpacingMul": 1.3,
        "indentChars": 0,
        "indentPt": 0,
        "justify": False,
        "paragraphAfter": 4,
        "headings": {
            "h1": {"font": "微软雅黑", "sizePt": 16, "bold": True, "align": "left", "color": "1F3864", "spaceBefore": 18, "spaceAfter": 8},
            "h2": {"font": "微软雅黑", "sizePt": 14, "bold": True, "align": "left", "color": "1F3864", "spaceBefore": 12, "spaceAfter": 6},
            "h3": {"font": "微软雅黑", "sizePt": 12, "bold": True, "align": "left", "color": "2F5496", "spaceBefore": 8, "spaceAfter": 4},
        },
        "pageNumber": "simple",
        "header": "",
        "orientation": "portrait",
        "cover": {"enabled": False},
        "toc": {"enabled": False, "levels": 3},
        "table": {"headerFill": "DEEAF6", "fontSizePt": 9.5, "headerBold": True},
        "caption": {"font": "微软雅黑", "sizePt": 9},
    },
}


DEFAULT_PRESET = "技术标标准"


def preset_names() -> list[str]:
    return list(PRESETS)


def default_writing_layout() -> dict:
    return copy.deepcopy(PRESETS[DEFAULT_PRESET])


def font_size_pt(value) -> float | None:
    """'小四' / '12' / 12 / '12pt' 都转成磅。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if text in FONT_SIZE_PT:
        return float(FONT_SIZE_PT[text])
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:pt|磅)?$", text, re.I)
    return float(match.group(1)) if match else None


def _num(value, low: float, high: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if not low <= number <= high:
        raise ValueError(f"{label}要在 {low:g} 到 {high:g} 之间")
    return number


def _text(value, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _hex(value, label: str) -> str:
    text = str(value or "").strip().lstrip("#")
    if not _HEX.match(text):
        raise ValueError(f"{label}要写 6 位十六进制颜色，例如 1F3864")
    return text.upper()


def _clean_heading(raw: dict, label: str) -> dict:
    out: dict = {}
    for key, value in raw.items():
        if key == "font":
            out["font"] = _text(value, 40)
        elif key in ("sizePt", "size"):
            pt = font_size_pt(value)
            if pt is None:
                raise ValueError(f"{label}字号无法识别")
            out["sizePt"] = _num(pt, 8, 72, f"{label}字号")
        elif key == "bold":
            out["bold"] = bool(value)
        elif key == "align":
            if value not in _ALIGNS:
                raise ValueError(f"{label}对齐只能是 left/center/right/justify")
            out["align"] = value
        elif key in ("spaceBefore", "spaceAfter"):
            out[key] = _num(value, 0, 72, f"{label}{key}")
        elif key == "color":
            out["color"] = _hex(value, f"{label}颜色")
    return out


def sanitize_patch(patch: dict) -> dict:
    """只留白名单字段并校验取值，非法值抛 ValueError（带中文原因，会回给模型）。"""
    if not isinstance(patch, dict):
        raise ValueError("排版设置必须是对象")
    out: dict = {}
    for key, value in patch.items():
        if key == "preset":
            name = _text(value, 40)
            if name not in PRESETS:
                raise ValueError("没有这个排版模板，可用：" + "、".join(PRESETS))
            out["preset"] = name
        elif key in (
            "bodyFont",
            "bodyLatinFont",
            "headingFont",
            "lineSpacing",
            "headerFont",
            "footerFont",
        ):
            out[key] = _text(value, 40)
        elif key == "fontSize":
            pt = font_size_pt(value)
            if pt is None:
                raise ValueError("字号无法识别，请用小四、四号或磅值")
            out["fontSize"] = _PT_TO_NAME.get(pt, "")
            out["bodySizePt"] = _num(pt, 5, 72, "正文字号")
        elif key == "bodySizePt":
            pt = _num(font_size_pt(value) if font_size_pt(value) is not None else value, 5, 72, "正文字号")
            out["bodySizePt"] = pt
            out["fontSize"] = _PT_TO_NAME.get(pt, "")
        elif key == "headingSizePt":
            out[key] = _num(value, 8, 72, "标题字号")
        elif key == "lineSpacingMul":
            out[key] = _num(value, 1, 3, "行距倍数")
            out["lineSpacingExactPt"] = None
            out["lineSpacingAtLeastPt"] = None
        elif key == "lineSpacingExactPt":
            out[key] = _num(value, 10, 80, "固定行距")
            out["lineSpacingMul"] = None
            out["lineSpacingAtLeastPt"] = None
        elif key == "lineSpacingAtLeastPt":
            out[key] = _num(value, 10, 80, "最小行距")
            out["lineSpacingMul"] = None
            out["lineSpacingExactPt"] = None
        elif key in ("paragraphBefore", "paragraphAfter"):
            out[key] = _num(value, 0, 60, "段间距")
        elif key == "indentChars":
            chars = _num(value, 0, 4, "首行缩进字数")
            out["indentChars"] = chars
            out["indentPt"] = None  # 由导出按正文字号换算
        elif key == "indentPt":
            out[key] = _num(value, 0, 80, "首行缩进")
        elif key == "hangingIndentPt":
            out[key] = _num(value, 0, 80, "悬挂缩进")
        elif key == "leftIndentPt":
            out[key] = _num(value, 0, 120, "左缩进")
        elif key in ("justify", "headingBold", "headerBorder", "differentFirstPage"):
            out[key] = bool(value)
        elif key in ("headerSizePt", "footerSizePt"):
            pt = font_size_pt(value)
            if pt is None:
                raise ValueError("页眉页脚字号无法识别")
            out[key] = _num(pt, 6, 24, "页眉页脚字号")
        elif key in ("headerDistanceCm", "footerDistanceCm"):
            out[key] = _num(value, 0.3, 5, "页眉页脚距边")
        elif key == "orientation":
            if value not in ("portrait", "landscape"):
                raise ValueError("纸张方向只能是 portrait 或 landscape")
            out[key] = value
        elif key == "pageNumber":
            if value not in ("none", "simple", "full"):
                raise ValueError("页码只能是 none / simple / full")
            out[key] = value
        elif key == "header":
            out[key] = _text(value, 80)
        elif key == "margins":
            if not isinstance(value, dict):
                raise ValueError("页边距必须是对象")
            out[key] = {
                side: _num(number, 0.5, 6, f"{side}边距")
                for side, number in value.items()
                if side in ("top", "bottom", "left", "right")
            }
        elif key == "headings":
            if not isinstance(value, dict):
                raise ValueError("标题样式必须是对象")
            out[key] = {
                level: _clean_heading(spec, level)
                for level, spec in value.items()
                if level in ("h1", "h2", "h3", "h4") and isinstance(spec, dict)
            }
        elif key == "cover" and isinstance(value, dict):
            cover: dict = {}
            if "enabled" in value:
                cover["enabled"] = bool(value["enabled"])
            for field in ("title", "subtitle", "company", "date", "titleFont", "subtitleFont", "infoFont"):
                if field in value:
                    cover[field] = _text(value[field], 80)
            for field in ("titleSizePt", "subtitleSizePt", "infoSizePt", "infoSpaceAfter"):
                if field in value:
                    pt = font_size_pt(value[field])
                    cover[field] = _num(pt if pt is not None else value[field], 0, 72, "封面字号/间距")
            out[key] = cover
        elif key == "toc" and isinstance(value, dict):
            toc: dict = {}
            if "enabled" in value:
                toc["enabled"] = bool(value["enabled"])
            if "levels" in value:
                toc["levels"] = int(_num(value["levels"], 1, 5, "目录层级"))
            out[key] = toc
        elif key == "table" and isinstance(value, dict):
            table: dict = {}
            if "headerFill" in value:
                table["headerFill"] = _hex(value["headerFill"], "表头底色")
            if "fontSizePt" in value:
                table["fontSizePt"] = _num(font_size_pt(value["fontSizePt"]) or value["fontSizePt"], 6, 24, "表格字号")
            if "headerBold" in value:
                table["headerBold"] = bool(value["headerBold"])
            if "borderColor" in value:
                table["borderColor"] = _hex(value["borderColor"], "表格边框颜色")
            if "borderSizePt" in value:
                table["borderSizePt"] = _num(value["borderSizePt"], 0.25, 3, "表格边框粗细")
            out[key] = table
        elif key == "caption" and isinstance(value, dict):
            caption: dict = {}
            if "font" in value:
                caption["font"] = _text(value["font"], 40)
            if "sizePt" in value:
                caption["sizePt"] = _num(font_size_pt(value["sizePt"]) or value["sizePt"], 6, 24, "图注字号")
            if "spaceAfter" in value:
                caption["spaceAfter"] = _num(value["spaceAfter"], 0, 40, "图注段后间距")
            out[key] = caption
    if not out:
        raise ValueError("没有可识别的排版字段")
    return out


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def merge_layout(base: dict | None, patch: dict) -> dict:
    """在已有排版上叠加 patch。选模板时保留招标书识别出的正文字体、字号和缩进。"""
    clean = sanitize_patch(patch)
    current = copy.deepcopy(base) if isinstance(base, dict) else {}
    preset = clean.pop("preset", None)
    if preset:
        kept = {key: current[key] for key in TENDER_KEYS if current.get("fromTender") and key in current}
        from_tender = current.get("fromTender")
        current = copy.deepcopy(PRESETS[preset])
        current.update(kept)
        if from_tender:
            current["fromTender"] = True
    return _deep_merge(current, clean)


def describe_layout(layout: dict | None) -> str:
    data = layout or {}
    parts: list[str] = []
    if data.get("preset"):
        parts.append(f"模板：{data['preset']}")
    body = data.get("bodyFont") or "宋体"
    size = data.get("bodySizePt") or font_size_pt(data.get("fontSize")) or 12
    latin = f"，英文数字 {data['bodyLatinFont']}" if data.get("bodyLatinFont") else ""
    parts.append(f"正文：{body} {size:g}pt{latin}")
    if data.get("lineSpacingExactPt"):
        parts.append(f"行距：固定值 {data['lineSpacingExactPt']:g} 磅")
    elif data.get("lineSpacingAtLeastPt"):
        parts.append(f"行距：最小值 {data['lineSpacingAtLeastPt']:g} 磅")
    elif data.get("lineSpacingMul"):
        parts.append(f"行距：{data['lineSpacingMul']:g} 倍")
    elif data.get("lineSpacing"):
        parts.append(f"行距：{data['lineSpacing']}")
    margins = data.get("margins") or {}
    if margins:
        parts.append(
            "页边距(cm)：上{top} 下{bottom} 左{left} 右{right}".format(
                **{k: margins.get(k, "-") for k in ("top", "bottom", "left", "right")}
            )
        )
    for level in ("h1", "h2", "h3", "h4"):
        spec = (data.get("headings") or {}).get(level)
        if spec:
            parts.append(
                f"{level.upper()}：{spec.get('font') or ''} {spec.get('sizePt') or ''}pt"
                f"{' 加粗' if spec.get('bold') else ''} {spec.get('align') or ''}".strip()
            )
    if data.get("header"):
        parts.append(f"页眉：{data['header']}")
    if data.get("pageNumber") and data["pageNumber"] != "none":
        parts.append("页码：" + ("第 X 页 共 Y 页" if data["pageNumber"] == "full" else "数字页码"))
    if (data.get("cover") or {}).get("enabled"):
        parts.append("含封面")
    if (data.get("toc") or {}).get("enabled"):
        parts.append("含自动目录")
    return "\n".join(parts)


def resolve_text(value: str, project_name: str) -> str:
    return (value or "").replace("{project}", project_name or "")
