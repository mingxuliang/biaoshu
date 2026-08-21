"""E2 商务客观核验引擎（对应青天第二层「商务标 AI 打分自查项」，前端 L2）。

若项目已锁定评标尺子（checklist_params 携带 asset_liability_ratio_max），按该项目真实招标文件
要求的阈值判定；否则回退到 rules_data.THRESHOLDS 的通用默认值。
"""

import re

from .rules_data import THRESHOLDS

PERFORMANCE_KEYWORDS = ["业绩", "类似项目", "施工业绩"]
FOUR_PIECES = ["中标通知书", "合同", "竣工验收", "官网"]

ASSET_LIABILITY_PATTERN = re.compile(r"资产负债率\D{0,10}(\d{1,3}(?:\.\d+)?)\s*%")


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e2_business",
        "level": "L2",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.75,
    }


def run(paragraphs: list[dict], checklist_params: dict | None = None) -> list[dict]:
    findings: list[dict] = []
    text_blocks = [p["text"] for p in paragraphs]
    full_text = "\n".join(text_blocks)

    checklist_params = checklist_params or {}
    ratio_max = checklist_params.get("asset_liability_ratio_max")
    if ratio_max is None:
        ratio_max = THRESHOLDS["asset_liability_ratio_max"]

    flagged_windows: set[int] = set()
    for idx, p in enumerate(paragraphs):
        text = p["text"]
        if not any(k in text for k in PERFORMANCE_KEYWORDS):
            continue
        window_key = idx // 6
        if window_key in flagged_windows:
            continue
        window = "\n".join(text_blocks[idx : idx + 6])
        missing = [kw for kw in FOUR_PIECES if kw not in window]
        if missing:
            flagged_windows.add(window_key)
            findings.append(
                _finding(
                    severity="降档",
                    location=f"商务标 / 业绩证明 / 段落 {p['index']}",
                    excerpt=text[:150],
                    rule="F03.05 业绩四件套齐全才计分",
                    suggestion=f"该业绩缺少：{'、'.join(missing)}，请补充佐证材料，否则该项业绩不予计分",
                )
            )

    m = ASSET_LIABILITY_PATTERN.search(full_text)
    if m:
        ratio = float(m.group(1))
        if ratio > ratio_max:
            findings.append(
                _finding(
                    severity="扣分",
                    location="资格文件 / 财务指标",
                    excerpt=m.group(0),
                    rule="F02.04 财务要求核对",
                    suggestion=(
                        f"资产负债率 {ratio}% 超过 {ratio_max}% 上限，"
                        "请核对最新年度报表或附说明函"
                    ),
                    tender_quote=f"资产负债率不高于 {ratio_max}%" if checklist_params.get("asset_liability_ratio_max") is not None else "",
                )
            )

    return findings
