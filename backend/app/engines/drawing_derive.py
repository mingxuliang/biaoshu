"""由图纸事实推导评审规则。只做确定性判断，不调用模型。"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+(?:\.\d+)?")
_GRADE = re.compile(r"C(\d{2})", re.I)


def _num(value: str) -> float | None:
    match = _NUM.search(str(value or ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _rule(fact: dict, title: str, requirement: str, check_type: str, severity: str) -> dict:
    drawing = str(fact.get("drawingNo") or "")
    page = fact.get("page")
    where = " ".join(bit for bit in (f"图 {drawing}" if drawing else "", f"第{page}页" if page else "") if bit)
    return {
        "source": "图纸",
        "title": title[:40],
        "requirement": requirement[:400],
        "checkType": check_type,
        "severity": severity,
        "evidence": str(fact.get("evidence") or where)[:200],
        "basis": str(fact.get("basis") or "")[:80],
        "parameters": f"{fact.get('field') or ''}{fact.get('value') or ''}"[:80],
        "enabled": True,
    }


def derive_rules(facts: list | None, specialty: str = "通用") -> list[dict]:
    rules: list[dict] = []
    seen: set[str] = set()
    water = specialty == "水利"
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        field = str(fact.get("field") or "")
        value = str(fact.get("value") or "")
        blob = f"{field}{value}{fact.get('object') or ''}"
        depth = _num(value) if "开挖" in field or "基坑" in field else None
        if depth is not None and depth >= 3:
            title = "超危大基坑" if depth >= 5 else "危大基坑"
            requirement = (
                f"基坑开挖深度 {depth:g}m，应列入超危大工程并有专项方案和专家论证。"
                if depth >= 5
                else f"基坑开挖深度 {depth:g}m，应列入危大工程并有支护和降水方案。"
            )
            if water:
                requirement += "水利项目同时对照 SL 721。"
            key = title
            if key not in seen:
                seen.add(key)
                rules.append(_rule(fact, title, requirement, "必须有", "降档" if depth >= 5 else "扣分"))
        if any(word in blob for word in ("围堰", "导流", "水下")):
            key = "导流度汛"
            if key not in seen:
                seen.add(key)
                rules.append(
                    _rule(fact, "导流与度汛", "图纸出现围堰、导流或水下作业，施组必须有导流标准、围堰、截流、基坑排水和度汛方案。", "必须有", "扣分")
                )
        grade = _GRADE.search(value)
        if grade and ("混凝土" in field or "混凝土" in str(fact.get("object") or "")):
            key = f"混凝土{grade.group(1)}"
            if key not in seen:
                seen.add(key)
                rules.append(
                    _rule(
                        fact,
                        f"混凝土不低于 C{grade.group(1)}",
                        f"施组中的混凝土强度不得低于设计 C{grade.group(1)}。",
                        "参数一致",
                        "降档",
                    )
                )
        if re.search(r"[WwPp]\d+", value) and ("抗渗" in field or "抗渗" in blob):
            key = f"抗渗{value}"
            if key not in seen:
                seen.add(key)
                rules.append(_rule(fact, "抗渗等级", f"施组采用的抗渗等级不得低于设计 {value}。", "参数一致", "降档"))
    return rules
