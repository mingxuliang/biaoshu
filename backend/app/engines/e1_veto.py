"""E1 一票否决引擎（对应青天第一层「一票否决项」，前端 L1）。

P1 落地后：若项目已解析并锁定评标尺子（EvaluationChecklist.engine_params_json），
则按该项目的真实招标文件参数（有效期天数、预算上限、资质关键词等）判定；
若项目尚未解析/锁定尺子（checklist_params 为 None），完全回退到通用正则/关键词，
保证 demo 文档与既有项目行为不受影响。
"""

import re
from datetime import datetime

VALIDITY_KEYWORDS = ["投标有效期"]
VALIDITY_NUMBER_PATTERN = re.compile(r"(\d{1,3})\s*(日历天|天)")

SIGNATURE_KEYWORDS = ["法定代表人", "授权代表", "单位盖章", "公章"]
PLACEHOLDER_PATTERN = re.compile(r"[＿_]{3,}|（\s*）|\(\s*\)")

QUALIFICATION_KEYWORDS = ["资质证书", "安全生产许可证", "营业执照"]
DATE_VALID_UNTIL_PATTERN = re.compile(
    r"有效期(?:至|到)?\s*[:：]?\s*(\d{4})[年\-./](\d{1,2})[月\-./](\d{1,2})"
)

PRICE_KEYWORDS = ["投标报价", "总报价", "投标总价"]
PRICE_WAN_PATTERN = re.compile(r"(?:投标报价|总报价|投标总价)\D{0,10}(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")


def _now() -> datetime:
    return datetime.utcnow()


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e1_veto",
        "level": "L1",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.8,
    }


def run(paragraphs: list[dict], checklist_params: dict | None = None) -> list[dict]:
    findings: list[dict] = []
    today = _now()

    checklist_params = checklist_params or {}
    validity_days_required = checklist_params.get("validity_days_required")
    budget_cap_wan = checklist_params.get("budget_cap_wan")
    qualification_keywords = checklist_params.get("qualification_keywords") or QUALIFICATION_KEYWORDS

    seen_validity = False
    seen_validity_number = False
    seen_validity_days: int | None = None

    for p in paragraphs:
        text = p["text"]

        if any(k in text for k in VALIDITY_KEYWORDS):
            seen_validity = True
            m_days = VALIDITY_NUMBER_PATTERN.search(text)
            if m_days:
                seen_validity_number = True
                try:
                    seen_validity_days = int(m_days.group(1))
                except ValueError:
                    pass

        if budget_cap_wan is not None:
            m_price = PRICE_WAN_PATTERN.search(text)
            if m_price:
                try:
                    price_wan = float(m_price.group(1).replace(",", ""))
                except ValueError:
                    price_wan = None
                if price_wan is not None and price_wan > budget_cap_wan:
                    findings.append(
                        _finding(
                            severity="废标",
                            location=f"投标文件 / 段落 {p['index']}",
                            excerpt=text[:150],
                            rule="F02.01 投标报价不得超过预算上限（评标尺子）",
                            suggestion=f"投标报价 {price_wan} 万元超过招标文件预算上限 {budget_cap_wan} 万元，须重新核对报价",
                            tender_quote=f"预算上限 {budget_cap_wan} 万元",
                        )
                    )

        for kw in qualification_keywords:
            if kw not in text:
                continue
            m = DATE_VALID_UNTIL_PATTERN.search(text)
            if not m:
                continue
            y, mo, d = map(int, m.groups())
            try:
                expire = datetime(y, mo, d)
            except ValueError:
                continue
            if expire < today:
                findings.append(
                    _finding(
                        severity="废标",
                        location=f"投标文件 / 段落 {p['index']}",
                        excerpt=text[:150],
                        rule="F02.02 资质证书须在有效期内",
                        suggestion=f"「{kw}」已于 {y}-{mo:02d}-{d:02d} 过期，须更新为有效证书后重新提交",
                    )
                )

        for kw in SIGNATURE_KEYWORDS:
            if kw in text and PLACEHOLDER_PATTERN.search(text):
                findings.append(
                    _finding(
                        severity="降档",
                        location=f"投标文件 / 段落 {p['index']}",
                        excerpt=text[:150],
                        rule="F02.05 签字盖章须实质性完成",
                        suggestion=f"检测到「{kw}」附近存在占位符（下划线/空括号），请确认已实际签字盖章",
                    )
                )

    if seen_validity and not seen_validity_number:
        findings.append(
            _finding(
                severity="废标",
                location="投标文件 / 投标函",
                excerpt="投标有效期条款未填写明确天数",
                rule="F02.03 实质性条款须明确响应",
                suggestion="补填投标有效期的具体天数（如 90 日历天）并加盖公章",
            )
        )
    elif (
        seen_validity
        and seen_validity_number
        and validity_days_required is not None
        and seen_validity_days is not None
        and seen_validity_days < validity_days_required
    ):
        findings.append(
            _finding(
                severity="废标",
                location="投标文件 / 投标函",
                excerpt=f"投标有效期填写为 {seen_validity_days} 日历天",
                rule="F02.03 实质性条款须明确响应（评标尺子）",
                suggestion=f"招标文件要求投标有效期不少于 {validity_days_required} 日历天，当前填写 {seen_validity_days} 天不满足要求",
                tender_quote=f"投标有效期不少于 {validity_days_required} 日历天",
            )
        )
    elif not seen_validity:
        findings.append(
            _finding(
                severity="建议",
                location="投标文件 / 投标函",
                excerpt="全文未检测到「投标有效期」条款",
                rule="F02.03 实质性条款须明确响应",
                suggestion="请人工确认投标函是否包含投标有效期条款",
            )
        )

    return findings
