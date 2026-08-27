"""E4 查重与虚词引擎（对应青天第四层「查重/防废标专项检查」，前端 L4）。

查重部分为企业自检版本：与内置示例模板库、本企业其他项目投标文件和知识库做相似度比对，
不比对其他投标人（监管侧能力，本系统明确不做）。
阈值取自规则页：全文 30%/42%，重难点/四新 20%/40%，本企业跨项目 60%/80%。
"""

import difflib
import re

from .rules_data import FILLER_WORDS, HIGH_RISK_SENTENCE_PATTERNS, REWRITE_BY_WORD, THRESHOLDS

SENTENCE_SPLIT = re.compile(r"[。！；\n]")
KEY_SECTION_HINTS = ("重难点", "四新", "新技术", "新工艺", "新材料", "新设备")

TEMPLATE_LIBRARY = [
    "在项目实施过程中，我方将加强现场管理，确保工程质量和安全，高度重视文明施工，全力以赴按期完成本项目建设任务。",
    "我公司将科学安排施工进度，合理组织劳动力和机械设备，严格按照国家规范和相关标准施工，努力创造优质工程。",
    "为确保本工程顺利实施，我方将建立健全质量管理体系，完善安全生产责任制，采用先进施工工艺，保证工程质量达到优良标准。",
]


def _default_word_patterns() -> list[tuple[str, str, str, str]]:
    return [(item["word"], item["category"], item["level"], item.get("rewrite") or "") for item in FILLER_WORDS]


DEFAULT_WORD_PATTERNS = _default_word_patterns()
HIGH_RISK_COMPILED = [re.compile(p) for p in HIGH_RISK_SENTENCE_PATTERNS]


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e4_duplicate_filler",
        "level": "L4",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.7,
    }


def _unpack(rule) -> tuple[str, str, str, str]:
    word = rule[0]
    category = rule[1] if len(rule) > 1 else ""
    level = rule[2] if len(rule) > 2 else "中危"
    rewrite = rule[3] if len(rule) > 3 else REWRITE_BY_WORD.get(word, "")
    return word, category, level, rewrite


def _pct(thresholds: dict, key: str, default: float) -> float:
    raw = thresholds.get(key, THRESHOLDS.get(key, default))
    try:
        return float(raw) / 100.0
    except (TypeError, ValueError):
        return default / 100.0


def run(
    paragraphs: list[dict],
    word_rules: list[tuple] | None = None,
    thresholds: dict | None = None,
    context=None,
) -> list[dict]:
    raw_rules = word_rules if word_rules is not None else DEFAULT_WORD_PATTERNS
    word_patterns = [_unpack(r) for r in raw_rules]
    # 长词优先，避免「高度」抢在「高度重视」之前误切
    word_patterns.sort(key=lambda x: len(x[0]), reverse=True)
    thresholds = thresholds or THRESHOLDS
    filler_density_safe = thresholds.get("filler_density_safe", THRESHOLDS["filler_density_safe"])
    full_safe = _pct(thresholds, "full_text_similarity_safe", 30)
    full_risk = _pct(thresholds, "full_text_similarity_risk", 42)
    key_safe = _pct(thresholds, "key_section_similarity_safe", 20)
    key_risk = _pct(thresholds, "key_section_similarity_risk", 40)

    findings: list[dict] = []
    full_text = "\n".join(p["text"] for p in paragraphs)
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(full_text) if s.strip()]
    total = len(sentences) or 1

    hit_sentences = sum(1 for s in sentences if any(w in s for w, _, _, _ in word_patterns))
    density = round(hit_sentences / total * 100, 1)

    if density > filler_density_safe:
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 全文虚词密度",
                excerpt=f"全文虚词命中句子占比 {density}%（安全线 {filler_density_safe}%）",
                rule="F10.02 虚词表-空话承诺",
                suggestion="按虚词自查五规则（数字/动作/对象/验证/密度）逐段改写，替换为可量化表述",
            )
        )

    high_hits: list[tuple[str, str, str]] = []
    seen_words: set[str] = set()
    for s in sentences:
        for word, _category, level, rewrite in word_patterns:
            if word in seen_words or word not in s:
                continue
            if level != "高危":
                continue
            seen_words.add(word)
            high_hits.append((word, s, rewrite))
            if len(high_hits) >= 8:
                break
        if len(high_hits) >= 8:
            break
    for word, excerpt, rewrite in high_hits:
        hint = rewrite or REWRITE_BY_WORD.get(word, "替换为可量化表述")
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 高危虚词",
                excerpt=excerpt[:150],
                rule="F10.02 虚词表-高危词",
                suggestion=f"命中高危虚词「{word}」。{hint}",
            )
        )

    seen_patterns: set[str] = set()
    for s in sentences:
        for pattern in HIGH_RISK_COMPILED:
            if pattern.pattern in seen_patterns:
                continue
            if pattern.search(s):
                seen_patterns.add(pattern.pattern)
                findings.append(
                    _finding(
                        severity="扣分",
                        location="技术标 / 高危句式",
                        excerpt=s[:150],
                        rule="F10.02 虚词表-高危句式",
                        suggestion="该句式属于万能模板句，请结合本项目实际情况改写为具体做法+数据",
                    )
                )

    best_full = (0.0, "")
    best_key = (0.0, "")
    for p in paragraphs:
        is_key = any(h in p["text"] for h in KEY_SECTION_HINTS)
        for s in SENTENCE_SPLIT.split(p["text"]):
            s = s.strip()
            if len(s) < 15:
                continue
            for tpl in TEMPLATE_LIBRARY:
                ratio = difflib.SequenceMatcher(None, s, tpl).ratio()
                if ratio > best_full[0]:
                    best_full = (ratio, s)
                if is_key and ratio > best_key[0]:
                    best_key = (ratio, s)

    if best_full[0] > full_risk:
        findings.append(
            _finding(
                severity="降档",
                location="技术标 / 模板相似度自检",
                excerpt=best_full[1][:150],
                rule="F06.05 查重阈值全文≤30%",
                suggestion=(
                    f"该段落与内置示例模板相似度约 {round(best_full[0] * 100)}%"
                    f"（风险线 {int(full_risk * 100)}%），技术标整体应降档，请注入本项目地点/工期/地质等特征重写"
                ),
            )
        )
    elif best_full[0] > full_safe:
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 模板相似度自检",
                excerpt=best_full[1][:150],
                rule="F06.05 查重阈值全文≤30%",
                suggestion=(
                    f"该段落与内置示例模板相似度约 {round(best_full[0] * 100)}%"
                    f"（安全线 {int(full_safe * 100)}%），请结合本项目特征改写"
                ),
            )
        )

    if best_key[0] > key_risk:
        findings.append(
            _finding(
                severity="降档",
                location="技术标 / 重难点四新查重",
                excerpt=best_key[1][:150],
                rule="F06.05 重难点/四新查重≤20%",
                suggestion=(
                    f"重难点/四新段落与内置模板相似度约 {round(best_key[0] * 100)}%"
                    f"（风险线 {int(key_risk * 100)}%），该小节应按清零处理并重写"
                ),
            )
        )
    elif best_key[0] > key_safe:
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 重难点四新查重",
                excerpt=best_key[1][:150],
                rule="F06.05 重难点/四新查重≤20%",
                suggestion=(
                    f"重难点/四新段落与内置模板相似度约 {round(best_key[0] * 100)}%"
                    f"（安全线 {int(key_safe * 100)}%），请按本工程地质/工况重写"
                ),
            )
        )

    findings.extend(_cross_project_findings(paragraphs, sentences, thresholds, context))
    return findings


def _cross_project_findings(paragraphs: list[dict], sentences: list[str], thresholds: dict, context) -> list[dict]:
    if context is None:
        return []
    extra: list[dict] = []
    para_risk = _pct(thresholds, "cross_bidder_paragraph_risk", 60)
    whole_risk = _pct(thresholds, "cross_bidder_whole_risk", 80)
    current_hash = getattr(context, "current_hash", "") or ""
    for label, digest in getattr(context, "other_file_hashes", []) or []:
        if current_hash and digest and current_hash == digest:
            extra.append(
                _finding(
                    severity="降档",
                    location="本企业跨项目 / 文件哈希",
                    excerpt=label[:80],
                    rule="F06.05 本企业文件哈希撞库",
                    suggestion=(
                        f"当前投标文件与本企业项目「{label}」的文件 MD5 相同，属于同一文件复用。"
                        "本系统不做其他投标人围串标比对，只核验本企业已归档文件"
                    ),
                )
            )
            break

    best = (0.0, "", "")
    other_sentences = getattr(context, "other_sentences", []) or []
    for s in sentences:
        if len(s) < 20:
            continue
        for label, other in other_sentences:
            ratio = difflib.SequenceMatcher(None, s[:400], other[:400]).ratio()
            if ratio > best[0]:
                best = (ratio, s, label)
        if best[0] > para_risk:
            break
    if best[0] > para_risk:
        extra.append(
            _finding(
                severity="降档" if best[0] > max(para_risk, 0.75) else "扣分",
                location="本企业跨项目 / 段落查重",
                excerpt=best[1][:150],
                rule="F06.05 本企业跨项目段落雷同",
                suggestion=(
                    f"该段落与本企业项目「{best[2]}」相似度约 {round(best[0] * 100)}%"
                    f"（风险线 {int(para_risk * 100)}%）。这是本企业历史标书查重，不是其他投标人围串标比对"
                ),
            )
        )

    current_full = "\n".join(p["text"] for p in paragraphs)[:8000]
    best_whole = (0.0, "")
    for label, other in getattr(context, "other_full_texts", []) or []:
        ratio = difflib.SequenceMatcher(None, current_full[:4000], other[:4000]).ratio()
        if ratio > best_whole[0]:
            best_whole = (ratio, label)
    if best_whole[0] > whole_risk:
        extra.append(
            _finding(
                severity="降档",
                location="本企业跨项目 / 整体查重",
                excerpt=best_whole[1][:80],
                rule="F06.05 本企业跨项目整体雷同",
                suggestion=(
                    f"全文与本企业项目「{best_whole[1]}」整体相似度约 {round(best_whole[0] * 100)}%"
                    f"（废标线 {int(whole_risk * 100)}%）。请按本项目特征重写，系统不比对其他公司投标文件"
                ),
            )
        )

    knowledge_hits = 0
    knowledge_excerpt = ""
    for snippet in getattr(context, "knowledge_texts", []) or []:
        if len(snippet) < 30:
            continue
        for s in sentences:
            if len(s) < 20:
                continue
            ratio = difflib.SequenceMatcher(None, s[:300], snippet[:300]).ratio()
            if ratio > para_risk:
                knowledge_hits += 1
                knowledge_excerpt = s[:150]
                break
        if knowledge_hits:
            break
    if knowledge_hits:
        extra.append(
            _finding(
                severity="扣分",
                location="知识库 / 历史材料查重",
                excerpt=knowledge_excerpt,
                rule="F06.05 知识库材料高相似",
                suggestion="该段落与企业知识库已入库材料高度相似，请改写为本项目工况后再用",
            )
        )
    return extra
