"""红字提示标记：库里没有的材料，正文里空出来并用醒目的大号红字提醒用户补充。

标记沿用字体标记 {{字体:字号}}…{{/}}，第三段是颜色（十六进制，无 #）：
    {{宋体:16pt:C00000}}**【缺少资质材料】**{{/}}
导出 docx、编辑器、自查都认这一种写法。每一行单独包一层，不跨行。
"""

from __future__ import annotations

import re

RED_COLOR = "C00000"
RED_OPEN_RE = re.compile(r"\{\{[^|:{}]+:[^}:]+:" + RED_COLOR + r"\}\}")
RED_SPAN_RE = re.compile(r"\{\{[^|:{}]+:[^}:]+:" + RED_COLOR + r"\}\}(.*?)\{\{/\}\}", re.S)
GAP_HEAD = "【缺少资质材料，请补充后再投标】"


def _clean(text: str) -> str:
    return (text or "").replace("{{", "").replace("}}", "").replace("\n", " ").strip()


def red(text: str, size: str = "12pt", bold: bool = False, font: str = "宋体") -> str:
    body = _clean(text)
    if bold:
        body = f"**{body}**"
    return "{{" + f"{font}:{size}:{RED_COLOR}" + "}}" + body + "{{/}}"


def red_cell(text: str) -> str:
    return red(text, "10.5pt", bold=True)


def red_lines(lines: list[str], size: str = "12pt", bold: bool = False) -> str:
    """多行红字：每行各包一层，行与行之间空一行成段。"""
    return "\n\n".join(red(line, size, bold) for line in lines if (line or "").strip())


def gap_block(label: str, requirement: str, count: int, have: int, notes: list[str] | None = None) -> str:
    """一处材料缺口的完整提示块。"""
    missing = max(count - have, 1)
    lines = [
        red(GAP_HEAD, "18pt", bold=True),
        red(
            f"招标要求：{label}{('（' + requirement + '）') if requirement else ''}，需提供 {count} 项；"
            f"资质证照库中已入库且符合条件的有 {have} 项，还缺 {missing} 项。",
            "14pt",
            bold=True,
        ),
    ]
    for note in notes or []:
        lines.append(red(note, "12pt"))
    lines.append(
        red("请到「企业资质证照库」录入该材料并审核入库，然后重新生成本章。缺少该材料将无法应标，此处不得留空提交。", "14pt", bold=True)
    )
    return "\n\n".join(lines)


def count_gaps(md: str) -> int:
    """正文里有几处缺口提示（以提示头为准，一处缺口算一次）。"""
    return len(re.findall(re.escape(GAP_HEAD), md or "")) + len(re.findall(r"【缺】|【缺人员】", md or ""))


def has_red(md: str) -> bool:
    return bool(RED_OPEN_RE.search(md or ""))


def red_texts(md: str) -> list[str]:
    return [m.strip().strip("*") for m in RED_SPAN_RE.findall(md or "")]
