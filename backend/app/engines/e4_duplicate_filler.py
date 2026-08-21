"""E4 查重与虚词引擎（对应青天第四层「查重/防废标专项检查」，前端 L4）。

查重部分为企业自检版本：与内置示例模板库做相似度比对，
不做跨投标人比对（监管侧能力，本系统明确不做）。
"""

import difflib
import re

from .rules_data import FILLER_WORD_CATEGORIES, HIGH_RISK_SENTENCE_PATTERNS, THRESHOLDS

SENTENCE_SPLIT = re.compile(r"[。！；\n]")

TEMPLATE_LIBRARY = [
    "在项目实施过程中，我方将加强现场管理，确保工程质量和安全，高度重视文明施工，全力以赴按期完成本项目建设任务。",
    "我公司将科学安排施工进度，合理组织劳动力和机械设备，严格按照国家规范和相关标准施工，努力创造优质工程。",
    "为确保本工程顺利实施，我方将建立健全质量管理体系，完善安全生产责任制，采用先进施工工艺，保证工程质量达到优良标准。",
]


def _word_patterns() -> list[tuple[str, str, str]]:
    patterns = []
    for cat in FILLER_WORD_CATEGORIES:
        for w in cat["words"]:
            patterns.append((w, cat["category"], cat["level"]))
    return patterns


WORD_PATTERNS = _word_patterns()
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


def run(paragraphs: list[dict]) -> list[dict]:
    findings: list[dict] = []
    full_text = "\n".join(p["text"] for p in paragraphs)
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(full_text) if s.strip()]
    total = len(sentences) or 1

    hit_sentences = sum(1 for s in sentences if any(w in s for w, _, _ in WORD_PATTERNS))
    density = round(hit_sentences / total * 100, 1)

    if density > THRESHOLDS["filler_density_safe"]:
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 全文虚词密度",
                excerpt=f"全文虚词命中句子占比 {density}%（安全线 {THRESHOLDS['filler_density_safe']}%）",
                rule="F10.02 虚词表-空话承诺",
                suggestion="按虚词自查五规则（数字/动作/对象/验证/密度）逐段改写，替换为可量化表述",
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

    seen_similarity = False
    for s in sentences:
        if len(s) < 15 or seen_similarity:
            break
        for tpl in TEMPLATE_LIBRARY:
            ratio = difflib.SequenceMatcher(None, s, tpl).ratio()
            if ratio > 0.55:
                seen_similarity = True
                findings.append(
                    _finding(
                        severity="降档",
                        location="技术标 / 模板相似度自检",
                        excerpt=s[:150],
                        rule="F06.05 查重阈值全文≤30%",
                        suggestion=f"该段落与内置示例模板相似度约 {round(ratio * 100)}%，请注入本项目地点/工期/地质等特征重写",
                    )
                )
                break

    return findings
