"""docx 表格转 Markdown 表。产品库、知识库、资质库三处共用。

python-docx 的 row.cells 遇到合并单元格会重复返回同一个单元格，这里按底层 tc 去重，
并保留空单元格，列才不会错位。
"""

from __future__ import annotations

import re


def docx_table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        seen: set[int] = set()
        cells: list[str] = []
        for cell in row.cells:
            key = id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            cells.append(" ".join((cell.text or "").split()))
        rows.append(cells)
    return rows


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", "<br>").strip()


def rows_to_markdown(rows: list[list[str]]) -> str:
    """第一行当表头。全空的行丢掉；只有一列时按普通文本行输出。"""
    kept = [[c or "" for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not kept:
        return ""
    width = max(len(r) for r in kept)
    if width == 1:
        return "\n".join(r[0].strip() for r in kept)
    padded = [r + [""] * (width - len(r)) for r in kept]
    lines = ["| " + " | ".join(_cell(c) for c in padded[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    lines.extend("| " + " | ".join(_cell(c) for c in r) + " |" for r in padded[1:])
    return "\n".join(lines)


def docx_table_markdown(table) -> str:
    return rows_to_markdown(docx_table_rows(table))


_SEP_ROW = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def markdown_table_rows(text: str) -> list[list[str]]:
    """把 rows_to_markdown 生成的表格还原成行；非表格行返回空列表。"""
    rows: list[list[str]] = []
    for line in (text or "").split("\n"):
        t = line.strip()
        if not t.startswith("|") or _SEP_ROW.match(t):
            continue
        body = t[1:-1] if t.endswith("|") else t[1:]
        rows.append([c.replace("\\|", "|").replace("<br>", "\n").strip() for c in re.split(r"(?<!\\)\|", body)])
    return rows
