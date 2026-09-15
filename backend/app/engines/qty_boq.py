"""从招标解析 qty-boq 四列还原清单行，并按混凝土/土方/钢筋分类加总。

预审不改表：直接读 EvaluationChecklist.checklist_json.dimensions。
.xlsx 清单由 tender_package.extract_boq_items 写入四列换行对齐的字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_QTY_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_CONCRETE = re.compile(r"混凝土|商品砼|C[2-5]\d")
_EARTH = re.compile(r"土方|挖方|填方|基坑开挖|开挖土")
_STEEL = re.compile(r"钢筋|螺纹钢|盘螺")

_NAME_ALIASES = ("项目名称", "工程项目名称")
_UNIT_ALIASES = ("计量单位", "单位")
_QTY_ALIASES = ("工程数量", "工程量")
_REMARK_ALIASES = ("备注",)


@dataclass
class BoqRow:
    name: str
    unit: str
    qty: float | None
    remark: str = ""
    kind: str = ""  # concrete | earth | steel | ""


@dataclass
class BoqAgg:
    rows: list[BoqRow] = field(default_factory=list)
    concrete_m3: float = 0.0
    earth_m3: float = 0.0
    steel_t: float = 0.0

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)


def parse_qty(text: str) -> float | None:
    raw = (text or "").replace(",", "").replace("，", "").replace(" ", "")
    if not raw:
        return None
    match = _QTY_NUM.search(raw)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def norm_unit(unit: str) -> str:
    raw = (unit or "").strip().lower().replace(" ", "").replace("３", "3")
    raw = raw.replace("m^3", "m3").replace("立方米", "m3").replace("立方", "m3")
    if raw in {"m3", "m³", "方"}:
        return "m³"
    if raw in {"t", "吨"}:
        return "t"
    if raw in {"kg", "千克", "公斤"}:
        return "kg"
    return (unit or "").strip()


def qty_in_canonical(qty: float | None, unit: str) -> tuple[float | None, str]:
    """把 kg 折成 t，其余保持 norm_unit。"""
    if qty is None:
        return None, norm_unit(unit)
    u = norm_unit(unit)
    if u == "kg":
        return qty / 1000.0, "t"
    return qty, u


def classify_name(name: str) -> str:
    text = name or ""
    if _CONCRETE.search(text):
        return "concrete"
    if _STEEL.search(text):
        return "steel"
    if _EARTH.search(text):
        return "earth"
    return ""


def _cell(row_map: dict[str, str], aliases: tuple[str, ...]) -> str:
    for key in aliases:
        if key in row_map and (row_map[key] or "").strip():
            return row_map[key]
    for key in aliases:
        if key in row_map:
            return row_map[key]
    return ""


def _row_text(row: dict) -> str:
    content = row.get("content")
    if isinstance(content, dict):
        content = content.get("摘要") or content.get("原文") or ""
    text = str(content or "")
    if not text.strip():
        original = row.get("original") or ""
        if isinstance(original, dict):
            original = original.get("原文") or original.get("摘要") or ""
        text = str(original or "")
    return text


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def rows_from_dimensions(dimensions: list | None) -> list[BoqRow]:
    """从 checklist.dimensions 还原 qty-boq 行。"""
    out: list[BoqRow] = []
    for dim in dimensions or []:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict):
                continue
            if (item.get("id") or "") != "qty-boq":
                continue
            for sec in item.get("sections") or []:
                if not isinstance(sec, dict):
                    continue
                row_map: dict[str, str] = {}
                for row in sec.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    label = str(row.get("label") or "").strip()
                    if label:
                        row_map[label] = _row_text(row)
                names = _split_lines(_cell(row_map, _NAME_ALIASES))
                units = _split_lines(_cell(row_map, _UNIT_ALIASES))
                qtys = _split_lines(_cell(row_map, _QTY_ALIASES))
                remarks = _split_lines(_cell(row_map, _REMARK_ALIASES))
                n = max(len(names), len(units), len(qtys), len(remarks))
                for i in range(n):
                    name = names[i].strip() if i < len(names) else ""
                    unit = units[i].strip() if i < len(units) else ""
                    qty_raw = qtys[i].strip() if i < len(qtys) else ""
                    remark = remarks[i].strip() if i < len(remarks) else ""
                    if not (name or unit or qty_raw or remark):
                        continue
                    qty, canon_unit = qty_in_canonical(parse_qty(qty_raw), unit)
                    kind = classify_name(name)
                    out.append(
                        BoqRow(
                            name=name,
                            unit=canon_unit or unit,
                            qty=qty,
                            remark=remark,
                            kind=kind,
                        )
                    )
    return out


def aggregate(dimensions: list | None) -> BoqAgg:
    rows = rows_from_dimensions(dimensions)
    agg = BoqAgg(rows=rows)
    for row in rows:
        if row.qty is None:
            continue
        if row.kind == "concrete" and row.unit == "m³":
            agg.concrete_m3 += row.qty
        elif row.kind == "earth" and row.unit == "m³":
            agg.earth_m3 += row.qty
        elif row.kind == "steel" and row.unit == "t":
            agg.steel_t += row.qty
    return agg
