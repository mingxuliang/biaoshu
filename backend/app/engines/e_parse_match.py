"""对照招标解析约定内容，检查投标书是否覆盖。

约定来自 EvaluationChecklist.checklist_json：
- scoreRules：评分细则 → 未覆盖记 L3 扣分
- qualification：资格条件 → 星号级未覆盖记废标，其余降档
- formatRequirements：格式/递交约定 → 废标级记废标，其余建议
- mustRespond 中非废标的实质性条款 → 降档（废标条款仍由 E1 处理）

判定方式与 E1 星号条款相同：从约定原文抽出中文核心短语，投标书里一条都对不上即视为未响应。
"""

from __future__ import annotations

import re

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{4,}")
_GENERIC = ("必须", "应当", "须", "应", "提交", "提供", "出具", "附上", "要求", "投标人", "招标人")


def _finding(level: str, severity: str, location: str, excerpt: str, rule: str, suggestion: str, quote: str = "") -> dict:
    return {
        "engine": "e_parse_match",
        "level": level,
        "severity": severity,
        "location": location,
        "excerpt": excerpt[:200],
        "rule": rule,
        "tenderQuote": quote[:200],
        "suggestion": suggestion,
        "confidence": 0.75,
    }


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _keys(text: str) -> list[str]:
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", text or ""))
    for prefix in _GENERIC:
        cjk = cjk.replace(prefix, "")
    if len(cjk) < 4:
        return _CJK_RUN.findall(text or "")[:8]
    n = 6 if len(cjk) >= 6 else 4
    windows = [cjk[i : i + n] for i in range(0, max(1, len(cjk) - n + 1))]
    if cjk[:12] not in windows:
        windows.insert(0, cjk[:12] if len(cjk) > 12 else cjk)
    return [w for w in windows if len(w) >= 4][:16]


def _title_covered(title: str, bid: str, heading_blob: str) -> bool:
    t = (title or "").strip()
    if len(t) < 2:
        return False
    if t in bid or t in heading_blob:
        return True
    if len(t) >= 4 and t[:4] in heading_blob:
        return True
    return False


def _unanswered(text: str, bid: str, title: str = "", heading_blob: str = "") -> bool:
    """未覆盖：标题未出现，且约定原文也没有足够长的窗口命中。

    单个 4–6 字短窗口命中容易误报（招标套话与标书套话重叠），因此要求：
    命中一段 ≥8 字，或至少两个不同窗口。标题出现在正文或目录则直接视为已覆盖。
    """
    if _title_covered(title, bid, heading_blob):
        return False
    keys = _keys(text)
    if not keys:
        return False
    hits = [k for k in keys if k in bid]
    if any(len(k) >= 8 for k in hits):
        return False
    if len(hits) >= 2:
        return False
    return True


def _item_text(item: dict, *fields: str) -> str:
    parts = []
    for f in fields:
        val = item.get(f)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts)


def run(
    full_text: str,
    score_rules: list | None = None,
    qualification: list | None = None,
    format_requirements: list | None = None,
    must_respond: list | None = None,
    tech_keys: set[str] | None = None,
    veto_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    headings: list[str] | None = None,
) -> list[dict]:
    bid = full_text or ""
    heading_blob = "".join(h for h in (headings or []) if h)
    findings: list[dict] = []

    if _enabled("star_clause", veto_keys):
        extra_must = 0
        for item in must_respond or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if any(h in kind for h in ("星号", "废标")):
                continue
            clause = str(item.get("clause") or item.get("text") or "").strip()
            if not clause or not _unanswered(clause, bid, heading_blob=heading_blob):
                continue
            extra_must += 1
            if extra_must > 8:
                break
            findings.append(
                _finding(
                    "L1",
                    "降档",
                    "投标文件 / 实质性条款",
                    clause,
                    "招标解析约定：实质性条款须响应",
                    "招标解析抽出的实质性条款未在投标书中检出对应表述，请按招标原文补写响应",
                    str(item.get("original") or ""),
                )
            )

    if _enabled("qualification", veto_keys):
        n = 0
        for item in qualification or []:
            if not isinstance(item, dict):
                continue
            blob = _item_text(item, "title", "desc")
            if not blob or not _unanswered(blob, bid, str(item.get("title") or ""), heading_blob):
                continue
            n += 1
            if n > 8:
                break
            star = (item.get("level") or "") == "星号"
            findings.append(
                _finding(
                    "L1",
                    "废标" if star else "降档",
                    f"资格条件 / {item.get('title') or '未标注'}",
                    blob,
                    "招标解析约定：资格条件须响应",
                    "招标解析列出的资格条件未在投标书中检出，请补充证书、人员或对应承诺",
                    str(item.get("source") or ""),
                )
            )

    format_on = _enabled("file_form", veto_keys)
    if format_on:
        n = 0
        for item in format_requirements or []:
            if not isinstance(item, dict):
                continue
            blob = _item_text(item, "title", "desc")
            if not blob or not _unanswered(blob, bid, str(item.get("title") or ""), heading_blob):
                continue
            n += 1
            if n > 8:
                break
            fatal = (item.get("level") or "") == "废标"
            findings.append(
                _finding(
                    "L5",
                    "废标" if fatal else "建议",
                    f"格式约定 / {item.get('title') or '未标注'}",
                    blob,
                    "招标解析约定：投标文件格式/递交要求",
                    "招标解析抽出的格式或递交约定未在投标书中体现，请按招标文件格式部分补全",
                    str(item.get("source") or ""),
                )
            )

    if _enabled("checklist_map", strategy_keys):
        n = 0
        for item in score_rules or []:
            if not isinstance(item, dict):
                continue
            blob = _item_text(item, "dimension", "detail")
            if not blob or not _unanswered(blob, bid, str(item.get("dimension") or ""), heading_blob):
                continue
            n += 1
            if n > 10:
                break
            dim = item.get("dimension") or "评分点"
            findings.append(
                _finding(
                    "L3",
                    "扣分",
                    f"评分细则 / {dim}",
                    blob,
                    "招标解析约定：评分点须在投标书中响应",
                    f"招标解析抽出的评分点「{dim}」未在投标书中检出对应内容，技术标完整性将被扣分",
                    str(item.get("sectionPath") or ""),
                )
            )

    return findings
