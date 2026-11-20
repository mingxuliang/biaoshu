"""把招标规则、清单特征、图纸推导和专业规则池合成一份本项目规则清单。"""

from __future__ import annotations

import re

from ..data.water_rule_table import WATER_RULES

_GRADE = re.compile(r"C(\d{2})", re.I)


def _item(**kwargs) -> dict:
    row = {
        "source": "",
        "title": "",
        "requirement": "",
        "checkType": "必须有",
        "severity": "扣分",
        "evidence": "",
        "basis": "",
        "parameters": "",
        "enabled": True,
    }
    row.update(kwargs)
    return row


def _from_tech(rules: list | None) -> list[dict]:
    out: list[dict] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        title = str(rule.get("factor") or rule.get("name") or "").strip()
        must = str(rule.get("mustWrite") or "").strip()
        if len(title) < 2 or len(must) < 4:
            continue
        out.append(
            _item(
                source="招标",
                title=title[:40],
                requirement=must[:400],
                checkType="必须有",
                severity="扣分",
                evidence=str(rule.get("chapter") or "招标文件")[:80],
                parameters=str(rule.get("parameters") or "")[:200],
            )
        )
    return out


def _from_boq(rows: list | None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        feature = str(row.get("feature") or "")
        name = str(row.get("name") or "")
        grade = _GRADE.search(feature)
        if not grade:
            continue
        key = f"{name}|C{grade.group(1)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            _item(
                source="清单",
                title=f"{name[:16]}不低于 C{grade.group(1)}"[:40],
                requirement=f"清单项目特征写明 C{grade.group(1)}，施组不得低于该等级。",
                checkType="参数一致",
                severity="降档",
                evidence=feature[:180],
                parameters=f"C{grade.group(1)} {row.get('qty') or ''}{row.get('unit') or ''}".strip(),
            )
        )
        if len(out) >= 40:
            break
    return out


def _from_pool(specialty: str) -> list[dict]:
    if specialty != "水利":
        return []
    out: list[dict] = []
    for rule in WATER_RULES:
        associative = bool(rule.get("associative"))
        out.append(
            _item(
                source="规则池",
                title=rule["title"],
                requirement=rule["requirement"],
                checkType="建议" if associative else rule["checkType"],
                severity="建议" if associative else rule["severity"],
                evidence=rule.get("layer") or "",
                basis="水利专业规则池",
            )
        )
    return out


def compose_project_rules(
    *,
    tech_rules: list | None = None,
    boq_rows: list | None = None,
    derived_rules: list | None = None,
    specialty: str = "",
) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for rule in (
        _from_tech(tech_rules) + _from_boq(boq_rows) + list(derived_rules or []) + _from_pool(specialty)
    ):
        if not isinstance(rule, dict):
            continue
        key = f"{rule.get('source')}|{rule.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        rule = dict(rule)
        rule["id"] = f"pr-{len(merged) + 1}"
        merged.append(rule)
    return merged
