"""对照招标解析约定内容，检查投标书是否覆盖。

判定：条款检索对应段 → 强字面重合算出已响应 → 否则 LLM 确认。
禁止 6 字窗口未命中就报废标。
"""

from __future__ import annotations

from .bid_kind import booklet_of_source
from .clause_cover import (
    CAPS,
    cap_overflow_finding,
    check_clauses_batch,
    lexical_covered,
    substance_blob,
)


def _finding(
    level: str,
    severity: str,
    location: str,
    excerpt: str,
    rule: str,
    suggestion: str,
    quote: str = "",
    *,
    unanswered_confirmed: bool = False,
    issue_class: str = "",
) -> dict:
    return {
        "engine": "e_parse_match",
        "level": level,
        "severity": severity,
        "location": location,
        "excerpt": excerpt[:200],
        "rule": rule,
        "tenderQuote": quote[:500],
        "suggestion": suggestion,
        "confidence": 0.75 if unanswered_confirmed else 0.55,
        "unansweredConfirmed": unanswered_confirmed,
        "issueClass": issue_class,
    }


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _unanswered(text: str, bid: str, title: str = "", heading_blob: str = "") -> bool:
    """兼容旧单测：目录标题不算已覆盖，强字面重合才算出响应。"""
    del heading_blob
    return not lexical_covered(text, bid, title)


def _item_text(item: dict, *fields: str) -> str:
    parts = []
    for f in fields:
        val = item.get(f)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts)


def _collect(kind: str, items: list, build, cap: int, level: str, severity: str) -> list[dict]:
    findings: list[dict] = []
    omitted = 0
    for item, result in items:
        if result.answered:
            continue
        if len(findings) >= cap:
            omitted += 1
            continue
        findings.append(build(item, result))
    if omitted:
        findings.append(cap_overflow_finding(kind, omitted, level, severity))
    return findings


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
    paragraphs: list[dict] | None = None,
) -> list[dict]:
    del headings
    bid = substance_blob(full_text or "", paragraphs)
    findings: list[dict] = []

    if _enabled("star_clause", veto_keys):
        entries = []
        for item in must_respond or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            if any(h in kind for h in ("星号", "废标")):
                continue
            clause = str(item.get("clause") or item.get("text") or "").strip()
            if not clause:
                continue
            entries.append((item, clause))
        batch = [{"id": str(i), "clause": clause} for i, (_item, clause) in enumerate(entries)]
        scanned = check_clauses_batch(batch, bid=bid, paragraphs=paragraphs, full_text=full_text or "")
        pending = [(item, scanned[str(i)]) for i, (item, _clause) in enumerate(entries)]
        findings.extend(
            _collect(
                "must",
                pending,
                lambda item, result: _finding(
                    "L1",
                    "降档",
                    "投标文件 / 实质性条款",
                    result.excerpt,
                    "招标解析约定：实质性条款须响应",
                    result.reason or "招标解析抽出的实质性条款未在投标书中确认对应表述，请按招标原文补写响应",
                    str(item.get("clause") or item.get("text") or ""),
                    unanswered_confirmed=result.unanswered_confirmed,
                ),
                CAPS["must"],
                "L1",
                "降档",
            )
        )

    if _enabled("qualification", veto_keys):
        entries = []
        for item in qualification or []:
            if not isinstance(item, dict):
                continue
            blob = _item_text(item, "title", "desc")
            if not blob:
                continue
            entries.append((item, blob))
        batch = [
            {"id": str(i), "clause": blob, "title": str(item.get("title") or "")}
            for i, (item, blob) in enumerate(entries)
        ]
        scanned = check_clauses_batch(batch, bid=bid, paragraphs=paragraphs, full_text=full_text or "")
        pending = [(item, scanned[str(i)]) for i, (item, _blob) in enumerate(entries)]
        findings.extend(
            _collect(
                "qualification",
                pending,
                lambda item, result: _finding(
                    "L1",
                    "降档" if (item.get("level") or "") == "星号" else "建议",
                    f"资格条件 / {item.get('title') or '未标注'}",
                    result.excerpt,
                    "招标解析约定：资格条件须响应",
                    result.reason or "资格条件未在投标书中确认，请人工核验证书与承诺",
                    _item_text(item, "title", "desc"),
                    unanswered_confirmed=result.unanswered_confirmed,
                    issue_class="human_check",
                ),
                CAPS["qualification"],
                "L1",
                "建议",
            )
        )

    if _enabled("file_form", veto_keys):
        entries = []
        for item in format_requirements or []:
            if not isinstance(item, dict):
                continue
            blob = _item_text(item, "title", "desc")
            if not blob:
                continue
            entries.append((item, blob))
        batch = [
            {"id": str(i), "clause": blob, "title": str(item.get("title") or "")}
            for i, (item, blob) in enumerate(entries)
        ]
        scanned = check_clauses_batch(batch, bid=bid, paragraphs=paragraphs, full_text=full_text or "")
        pending = [(item, scanned[str(i)]) for i, (item, _blob) in enumerate(entries)]
        findings.extend(
            _collect(
                "format",
                pending,
                lambda item, result: _finding(
                    "L5",
                    "建议",
                    f"格式约定 / {item.get('title') or '未标注'}",
                    result.excerpt,
                    "招标解析约定：投标文件格式/递交要求",
                    result.reason or "格式或递交约定未在投标书中确认，请按招标文件格式部分人工核对",
                    _item_text(item, "title", "desc"),
                    unanswered_confirmed=result.unanswered_confirmed,
                    issue_class="human_check",
                ),
                CAPS["format"],
                "L5",
                "建议",
            )
        )

    if _enabled("checklist_map", strategy_keys):
        from .e_tender_score import is_grading_rule, split_label_content

        entries = []
        for item in score_rules or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("sourceItemId") or "") == "contract-tech":
                # 专用合同条款：中标后履约条款（付款进度、违约金、验收标准…），不是投标时
                # 要写进技术方案的评分点，即便解析时误标了权重也不当应答项处理。
                continue
            try:
                weight = float(item.get("weight") or 0)
            except (TypeError, ValueError):
                weight = 0.0
            if weight <= 0:
                # 没有分值的条目不是真正的评分点：可能是评标办法/合同履约条款等参考性文字
                # （如「专用合同条款」的违约金/验收期限、"本段未出现XX公式"占位说明），也可能
                # 是格式要求误落进这一类。e_tender_score 的模拟打分本就只认 weight>0 的条目，
                # 这里对齐同一口径，避免「是否应答」和「打分证据」判两套标准、也避免把履约
                # 条款误判成投标人必须响应的评分点。
                continue
            blob = _item_text(item, "dimension", "detail")
            if not blob:
                continue
            label, content = split_label_content(str(item.get("detail") or ""))
            if is_grading_rule(label or str(item.get("sectionPath") or ""), content):
                # 评委打分/分档语言（如「分档/赋分规则」），投标人不会把它写进正文，
                # 不当作「必须在投标书里出现」的应答项，避免误判成缺项。
                continue
            entries.append((item, blob))
        batch = [
            {"id": str(i), "clause": blob, "title": str(item.get("dimension") or "")}
            for i, (item, blob) in enumerate(entries)
        ]
        scanned = check_clauses_batch(batch, bid=bid, paragraphs=paragraphs, full_text=full_text or "")
        pending = [(item, scanned[str(i)]) for i, (item, _blob) in enumerate(entries)]

        def _score_finding(item: dict, result) -> dict:
            dim = item.get("dimension") or "评分点"
            slot = booklet_of_source(str(item.get("sourceItemId") or ""), str(dim))
            level = "L2" if slot in ("business", "price") else "L3"
            return _finding(
                level,
                "扣分",
                f"评分细则 / {dim}",
                result.excerpt,
                "招标解析约定：评分点须在投标书中响应",
                result.reason or f"评分点「{dim}」未确认对应内容，请按本册规则补写",
                blob if (blob := _item_text(item, "dimension", "detail")) else dim,
                unanswered_confirmed=result.unanswered_confirmed,
            )

        findings.extend(_collect("score", pending, _score_finding, CAPS["score"], "L3", "扣分"))

    del tech_keys
    return findings
