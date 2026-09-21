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


def _slots_text(source: str, sources: list | None) -> str:
    if source == "tender":
        return "招标文件"
    if source == "drawing":
        return "图纸"
    names = [_SLOT_LABELS.get(str(k), str(k)) for k in (sources or []) if k]
    return "、".join(names) if names else SOURCE_LABELS.get(source, "多种类型")


def _level_for_scope(severity: str, scope: str) -> str:
    """自定义规则要落在当前分册的可见层级，避免商务预审丢掉「扣分」。"""
    if scope == "business":
        return "L1" if severity in ("废标", "降档") else "L2"
    if scope == "tech":
        return "L5" if severity == "建议" else "L3"
    if severity in ("废标", "降档"):
        return "L1"
    if severity == "建议":
        return "L5"
    return "L3"


def run(full_text: str, paragraphs: list[dict] | None, rules: list | None, scope: str = "full") -> dict:
    from .clause_cover import CAPS, CoverResult, cap_overflow_finding, check_clauses_batch, substance_blob

    bid = substance_blob(full_text or "", paragraphs)
    findings: list[dict] = []
    items: list[dict] = []
    omitted = 0

    entries = []
    for raw in rules or []:
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            continue
        content = str(raw.get("content") or "").strip()
        if len(content) < 2:
            continue
        entries.append(raw)

    batch = [
        {"id": str(i), "clause": str(raw.get("content") or "").strip(), "title": str(raw.get("title") or "").strip()}
        for i, raw in enumerate(entries)
    ]
    # 先跑免费的字面命中/关键词候选校验；命中不到候选的规则（原文换了说法、或规则本身
    # 是评委/审查口径而非投标人应答语言）整批升级到分块通读投标书正文，不再直接判「未响应」。
    scanned = check_clauses_batch(batch, bid=bid, paragraphs=paragraphs, full_text=full_text or "")

    for i, raw in enumerate(entries):
        content = str(raw.get("content") or "").strip()
        title = str(raw.get("title") or "").strip()
        cover = scanned.get(str(i)) or CoverResult(answered=True, reason="核验缺失，按宁缺毋滥视为已响应")
        source = str(raw.get("source") or "tender")
        where = _slots_text(source, raw.get("sources") if isinstance(raw.get("sources"), list) else [])
        label = title or content[:24]
        severity = str(raw.get("severity") or "扣分")
        if severity not in ("废标", "降档", "扣分", "建议"):
            severity = "扣分"
        status = "已响应" if cover.answered else "未响应"
        items.append(
            {
                "id": str(raw.get("id") or ""),
                "title": label,
                "content": content[:800],
                "source": source,
                "sourceLabel": where,
                "severity": severity,
                "status": status,
                "excerpt": cover.excerpt or "",
                "reason": cover.reason or ("投标书已覆盖该规则。" if cover.answered else "投标书未确认对应表述。"),
            }
        )
        if cover.answered:
            continue
        if len(findings) >= CAPS["custom"]:
            omitted += 1
            continue
        findings.append(
            {
                "engine": "e_custom_rules",
                "level": _level_for_scope(severity, scope),
                "severity": severity,
                "location": f"自定义规则 / {where}",
                "excerpt": cover.excerpt,
                "rule": f"自定义规则（{where}）：{label}",
                "tenderQuote": content[:500],
                "suggestion": cover.reason or f"人工补充的规则未确认对应表述，请按该条款补写。来源：{where}。",
                "confidence": 0.78,
                "unansweredConfirmed": cover.unanswered_confirmed or not cover.answered,
            }
        )
    if omitted:
        findings.append(cap_overflow_finding("custom", omitted, "L5", "建议"))
    return {"findings": findings, "items": items}
