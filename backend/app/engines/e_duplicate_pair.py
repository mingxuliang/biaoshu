"""两份技术标相似度比对：对照规则页查重阈值，不比对内置套话模板。"""

from __future__ import annotations

import re

from .rules_data import THRESHOLDS

SENTENCE_SPLIT = re.compile(r"[。！？；\n]")
KEY_SECTION_HINTS = ("重难点", "四新", "新技术", "新工艺", "新材料", "新设备")
PAIR_CAP = 20
SENTENCE_CHARS = 800
SHINGLE = 6
SHINGLE_STEP = 4
CANDIDATE_CAP = 48


def _pct_value(thresholds: dict, key: str, default: float) -> float:
    raw = (thresholds or {}).get(key, THRESHOLDS.get(key, default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT.split(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        s = " ".join(part.split())
        if len(s) < 20:
            continue
        key = s[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _key_sentences(sentences: list[str], full_text: str) -> list[str]:
    keyed = [s for s in sentences if any(h in s for h in KEY_SECTION_HINTS)]
    seen = {s[:80] for s in keyed}
    for block in (full_text or "").split("\n"):
        s = " ".join(block.split())
        if len(s) < 20 or not any(h in s for h in KEY_SECTION_HINTS):
            continue
        if s[:80] in seen:
            continue
        seen.add(s[:80])
        keyed.append(s)
    return keyed


def _shingles(text: str) -> list[str]:
    cut = (text or "")[:SENTENCE_CHARS]
    if len(cut) < SHINGLE:
        return [cut] if cut else []
    return [cut[i : i + SHINGLE] for i in range(0, len(cut) - SHINGLE + 1, SHINGLE_STEP)]


def _index_shingles(sentences: list[str]) -> dict[str, list[int]]:
    inv: dict[str, list[int]] = {}
    for idx, sent in enumerate(sentences):
        seen: set[str] = set()
        for gram in _shingles(sent):
            if gram in seen:
                continue
            seen.add(gram)
            bucket = inv.setdefault(gram, [])
            bucket.append(idx)
    return inv


def _candidate_ids(sent: str, index: dict[str, list[int]], right_lens: list[int], la: int) -> list[int]:
    hits: dict[int, int] = {}
    for gram in _shingles(sent):
        for idx in index.get(gram, ()):
            hits[idx] = hits.get(idx, 0) + 1
    ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    out: list[int] = []
    for idx, _count in ranked:
        lb = right_lens[idx]
        if not lb:
            continue
        if abs(la - lb) / max(la, lb) > 0.45:
            continue
        out.append(idx)
        if len(out) >= CANDIDATE_CAP:
            break
    return out


def _whole_ratio(text_a: str, text_b: str) -> float:
    """对抽出的全部正文做 SequenceMatcher，不截文首。"""
    import difflib

    if not text_a or not text_b:
        return 0.0
    if text_a == text_b:
        return 1.0
    return difflib.SequenceMatcher(None, text_a, text_b).ratio()


def _match_sentences(left: list[str], right: list[str], min_pct: float) -> tuple[float, str, str, list[dict]]:
    import difflib

    empty: tuple[float, str, str, list[dict]] = (0.0, "", "", [])
    if not left or not right:
        return empty
    min_ratio = max(min_pct / 100.0, 0.25)
    scan_floor = 0.25
    index = _index_shingles(right)
    right_lens = [len(item[:SENTENCE_CHARS]) for item in right]
    best = (0.0, "", "")
    hits: list[tuple[float, str, str]] = []
    used_right: set[int] = set()
    for a in left:
        a_cut = a[:SENTENCE_CHARS]
        la = len(a_cut)
        if not la:
            continue
        local = (0.0, -1, "")
        for idx in _candidate_ids(a, index, right_lens, la):
            b = right[idx]
            b_cut = b[:SENTENCE_CHARS]
            sm = difflib.SequenceMatcher(None, a_cut, b_cut)
            if sm.quick_ratio() < scan_floor:
                continue
            ratio = sm.ratio()
            if ratio > best[0]:
                best = (ratio, a, b)
            if idx in used_right:
                continue
            if ratio > local[0]:
                local = (ratio, idx, b)
        if local[1] >= 0 and local[0] >= min_ratio:
            used_right.add(local[1])
            hits.append((local[0], a, local[2]))
    hits.sort(key=lambda item: item[0], reverse=True)
    pairs = [
        {"pct": round(item[0] * 100, 1), "excerptA": item[1][:180], "excerptB": item[2][:180]}
        for item in hits[:PAIR_CAP]
    ]
    return best[0], best[1], best[2], pairs


def _check(
    *,
    key: str,
    label: str,
    value: float | None,
    threshold: float,
    triggered: bool,
    severity: str,
    meaning: str,
    applicable: bool = True,
) -> dict:
    return {
        "key": key,
        "label": label,
        "value": None if value is None else round(value, 1),
        "threshold": threshold,
        "unit": "%",
        "triggered": bool(triggered),
        "severity": severity,
        "meaning": meaning,
        "applicable": applicable,
    }


def _sim_on(key: str, sim_keys: set[str] | None) -> bool:
    return sim_keys is None or key in sim_keys


def analyze_pair(
    text_a: str,
    text_b: str,
    thresholds: dict | None = None,
    *,
    identical: bool = False,
    name_a: str = "技术标甲",
    name_b: str = "技术标乙",
    sim_keys: set[str] | None = None,
) -> dict:
    """比较两份技术标全部抽出正文，返回灯色、阈值对照和原文配对。

    sim_keys 来自规则页「查重阈值」三张卡片；None 表示三项全开。
    """
    thresholds = thresholds or THRESHOLDS
    full_on = _sim_on("full_text_sim", sim_keys)
    key_on = _sim_on("key_section_sim", sim_keys)
    cross_on = _sim_on("cross_bidder", sim_keys)

    full_safe = _pct_value(thresholds, "full_text_similarity_safe", 30)
    full_risk = _pct_value(thresholds, "full_text_similarity_risk", 42)
    key_safe = _pct_value(thresholds, "key_section_similarity_safe", 20)
    key_risk = _pct_value(thresholds, "key_section_similarity_risk", 40)
    para_risk = _pct_value(thresholds, "cross_bidder_paragraph_risk", 60)
    whole_risk = _pct_value(thresholds, "cross_bidder_whole_risk", 80)

    a = (text_a or "").strip()
    b = (text_b or "").strip()
    pairs: list[dict] = []
    para_pct = 0.0
    key_pct: float | None = None
    if identical or (a and a == b):
        whole_pct = 100.0
        para_pct = 100.0 if cross_on else 0.0
        if key_on:
            key_pct = 100.0 if any(h in a for h in KEY_SECTION_HINTS) else None
        pairs = [
            {
                "pct": 100.0,
                "excerptA": a[:180] or "（文件内容相同）",
                "excerptB": b[:180] or "（文件内容相同）",
            }
        ] if (full_on or cross_on or key_on) else []
        identical = True
    else:
        whole_pct = round(_whole_ratio(a, b) * 100, 1) if (full_on or cross_on) else 0.0
        sents_a = _sentences(a) if (cross_on or key_on) else []
        sents_b = _sentences(b) if (cross_on or key_on) else []
        if cross_on:
            best_para, para_a, para_b, pairs = _match_sentences(sents_a, sents_b, full_safe)
            para_pct = round(best_para * 100, 1)
            if not pairs and para_a and para_b and para_pct >= full_safe:
                pairs = [{"pct": para_pct, "excerptA": para_a[:180], "excerptB": para_b[:180]}]
        if key_on:
            key_a = _key_sentences(sents_a or _sentences(a), a)
            key_b = _key_sentences(sents_b or _sentences(b), b)
            if key_a and key_b:
                key_best, _, _, _ = _match_sentences(key_a, key_b, key_safe)
                key_pct = round(key_best * 100, 1)

    full_safe_hit = full_on and whole_pct > full_safe
    full_risk_hit = full_on and whole_pct > full_risk
    whole_cross_hit = cross_on and whole_pct > whole_risk
    para_hit = cross_on and para_pct > para_risk
    key_applicable = key_on and key_pct is not None
    key_safe_hit = key_applicable and key_pct > key_safe
    key_risk_hit = key_applicable and key_pct > key_risk

    closed = "查重阈值中该项已关闭，未纳入本次比对"
    red = (identical and (full_on or cross_on or (key_on and key_applicable))) or full_risk_hit or whole_cross_hit or para_hit or key_risk_hit
    orange = (not red) and (full_safe_hit or key_safe_hit)
    light = "红" if red else ("橙" if orange else "绿")

    checks = [
        _check(
            key="full_text_similarity_safe",
            label="全文模板相似度安全线",
            value=whole_pct if full_on else None,
            threshold=full_safe,
            triggered=full_safe_hit,
            severity="扣分",
            meaning="两份技术标整体相似度超过安全线，青天口径应改写后重投" if full_on else closed,
            applicable=full_on,
        ),
        _check(
            key="full_text_similarity_risk",
            label="全文模板相似度风险线",
            value=whole_pct if full_on else None,
            threshold=full_risk,
            triggered=full_risk_hit,
            severity="降档",
            meaning="整体相似度超过风险线，技术标应按降档处理" if full_on else closed,
            applicable=full_on,
        ),
        _check(
            key="cross_bidder_whole_risk",
            label="本企业跨项目整体雷同风险线",
            value=whole_pct if cross_on else None,
            threshold=whole_risk,
            triggered=whole_cross_hit,
            severity="降档",
            meaning="两份标书整体高度雷同，视为本企业文件复用风险" if cross_on else closed,
            applicable=cross_on,
        ),
        _check(
            key="cross_bidder_paragraph_risk",
            label="本企业跨项目段落雷同风险线",
            value=para_pct if cross_on else None,
            threshold=para_risk,
            triggered=para_hit,
            severity="降档",
            meaning="存在超过风险线的段落配对，需按本项目工况重写" if cross_on else closed,
            applicable=cross_on,
        ),
        _check(
            key="key_section_similarity_safe",
            label="重难点/四新专项查重安全线",
            value=key_pct if key_on else None,
            threshold=key_safe,
            triggered=bool(key_safe_hit),
            severity="扣分",
            meaning=(
                closed
                if not key_on
                else ("重难点/四新段落相似度超过安全线" if key_applicable else "两份文件均未检出重难点/四新段落，本项不适用")
            ),
            applicable=key_applicable,
        ),
        _check(
            key="key_section_similarity_risk",
            label="重难点/四新专项查重风险线",
            value=key_pct if key_on else None,
            threshold=key_risk,
            triggered=bool(key_risk_hit),
            severity="降档",
            meaning=(
                closed
                if not key_on
                else ("重难点/四新段落相似度超过风险线，该小节应按清零处理" if key_applicable else "两份文件均未检出重难点/四新段落，本项不适用")
            ),
            applicable=key_applicable,
        ),
    ]

    issues = []
    if full_on or cross_on:
        for idx, pair in enumerate(pairs, start=1):
            pct = pair["pct"]
            if (cross_on and (pct > whole_risk or pct > para_risk)) or (full_on and pct > full_risk):
                severity = "降档"
            elif full_on and pct > full_safe:
                severity = "扣分"
            else:
                continue
            issues.append(
                {
                    "id": f"dup-{idx}",
                    "level": "L4",
                    "severity": severity,
                    "location": f"技术标对照 / 第 {idx} 组相似段落",
                    "excerpt": pair["excerptA"],
                    "tenderQuote": pair["excerptB"],
                    "rule": f"两文件段落相似度 {pct}%",
                    "suggestion": "请按本项目地点、工期、地质或工况改写该段，避免整段复用另一份技术标。",
                }
            )

    triggered = [c for c in checks if c["triggered"]]
    waste = len([c for c in triggered if c["severity"] == "降档"])
    risk = len([c for c in triggered if c["severity"] == "扣分"])
    suggest = max(0, len(issues) - waste - risk)
    if not (full_on or key_on or cross_on):
        conclusion = "查重阈值中三项规则均已关闭，本次未做两文件相似度判定。"
    elif identical:
        conclusion = (
            f"两份文件内容一致（或哈希相同），整体相似度 100%。"
            f"已按当前启用的查重规则判定为同一技术标复用。"
        )
    elif red:
        conclusion = (
            f"「{name_a}」与「{name_b}」整体相似度 {whole_pct}%，最高段落相似度 {para_pct}%。"
            f"已触发青天降档阈值，建议按本项目特征重写后再用于投标。"
        )
    elif orange:
        conclusion = (
            f"「{name_a}」与「{name_b}」整体相似度 {whole_pct}%，已越过安全线但未到降档线。"
            f"请重点改写报告中列出的相似段落。"
        )
    else:
        conclusion = (
            f"「{name_a}」与「{name_b}」整体相似度 {whole_pct}%，"
            f"段落最高 {para_pct}%，未触发青天查重安全线。"
        )

    return {
        "fileA": {"name": name_a, "chars": len(a)},
        "fileB": {"name": name_b, "chars": len(b)},
        "identical": identical,
        "wholePct": whole_pct,
        "paragraphPct": para_pct,
        "keySectionPct": key_pct,
        "light": light,
        "waste": waste,
        "risk": risk,
        "suggest": suggest,
        "checks": checks,
        "pairs": pairs,
        "issues": issues,
        "conclusion": conclusion,
        "scope": "tech",
        "method": "通读两份技术标全文 · 青天查重阈值",
    }
