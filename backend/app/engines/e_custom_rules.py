"""项目解析页人工补充的自定义规则：对照投标书是否响应，写入 AI 预审。"""

from __future__ import annotations

SOURCE_LABELS = {
    "tender": "招标文件",
    "drawing": "图纸",
    "mixed": "多种类型",
}

_SLOT_LABELS = {
    "main": "招标文件正文",
    "addendum": "答疑补遗",
    "boq": "工程量清单",
    "quote": "其他",
    "drawing": "施工图纸",
}

_LEVEL = {
    "废标": ("L1", "废标"),
    "降档": ("L1", "降档"),
    "扣分": ("L3", "扣分"),
    "建议": ("L5", "建议"),
}


def _slots_text(source: str, sources: list | None) -> str:
    if source == "tender":
        return "招标文件"
    if source == "drawing":
        return "图纸"
    names = [_SLOT_LABELS.get(str(k), str(k)) for k in (sources or []) if k]
    return "、".join(names) if names else "多种类型"


def run(full_text: str, paragraphs: list[dict] | None, rules: list | None) -> list[dict]:
    from .e_parse_match import _substance_blob, _unanswered

    bid = _substance_blob(full_text or "", paragraphs)
    heading_blob = "".join((p.get("text") or "") for p in (paragraphs or []) if p.get("isHeading"))
    findings: list[dict] = []
    for item in rules or []:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        content = str(item.get("content") or "").strip()
        if len(content) < 2:
            continue
        title = str(item.get("title") or "").strip()
        if not _unanswered(content, bid, title, heading_blob):
            continue
        source = str(item.get("source") or "tender")
        where = _slots_text(source, item.get("sources") if isinstance(item.get("sources"), list) else [])
        label = title or content[:24]
        level, severity = _LEVEL.get(str(item.get("severity") or "扣分"), ("L3", "扣分"))
        findings.append(
            {
                "engine": "e_custom_rules",
                "level": level,
                "severity": severity,
                "location": f"自定义规则 / {where}",
                "excerpt": "",
                "rule": f"自定义规则（{where}）：{label}",
                "tenderQuote": content[:500],
                "suggestion": f"人工补充的规则未在投标书中检出对应表述，请按该条款补写响应。来源：{where}。",
                "confidence": 0.7,
            }
        )
        if len(findings) >= 40:
            break
    return findings
