"""E4 虚词语义引擎（青天第四层 L4）。

用大模型阅读投标书原文，找出「该写做法却只有态度」的句子，并给出应补充的数据。
虚词表、高危句式只作为提示词参考，禁止见词即报。全文/跨项目相似度不在本引擎。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .excerpt_guard import snap_bid_excerpt
from .llm import chat_complete, get_default_model_id
from .rules_data import (
    FILLER_SELF_CHECK_RULES,
    FILLER_WORDS,
    HIGH_RISK_SENTENCE_PATTERNS,
    REWRITE_BY_WORD,
    THRESHOLDS,
)

logger = logging.getLogger(__name__)

_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、")
_CN_PAREN = re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]")
_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)")
_ATTACH = re.compile(r"^附件[0-9一二三四五六七八九十]")

CHUNK_CHARS = 10000
MAX_CHUNKS = 10
MAX_REVIEW_CHARS = 100_000
PARALLEL_WORKERS = 4
CALL_TIMEOUT = 60
PER_CHUNK = 8
ISSUE_CAP = 8


def _default_word_patterns() -> list[tuple[str, str, str, str]]:
    return [(item["word"], item["category"], item["level"], item.get("rewrite") or "") for item in FILLER_WORDS]


DEFAULT_WORD_PATTERNS = _default_word_patterns()


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
        "confidence": 0.82,
    }


def _unpack(rule) -> tuple[str, str, str, str]:
    word = rule[0]
    category = rule[1] if len(rule) > 1 else ""
    level = rule[2] if len(rule) > 2 else "中危"
    rewrite = rule[3] if len(rule) > 3 else REWRITE_BY_WORD.get(word, "")
    return word, category, level, rewrite


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _is_heading_line(line: str) -> bool:
    text = (line or "").strip()
    if not text or len(text) > 48 or "。" in text:
        return False
    return bool(_CHAPTER.match(text) or _CN_DOT.match(text) or _CN_PAREN.match(text) or _DOTTED.match(text) or _ATTACH.match(text))


def _is_heading_para(p: dict) -> bool:
    text = (p.get("text") or "").strip()
    style = (p.get("style") or "").lower()
    if "heading" in style or "标题" in style:
        return bool(text) and len(text) <= 48
    return _is_heading_line(text)


def _loads_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        left, right = text.find("{"), text.rfind("}")
        if left >= 0 and right > left:
            try:
                data = json.loads(text[left : right + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _word_reference(word_patterns: list[tuple[str, str, str, str]]) -> str:
    groups: dict[str, list[str]] = {}
    for word, category, level, rewrite in word_patterns:
        hint = f"{word}（{level}"
        if rewrite:
            hint += f"，补数据方向：{rewrite}"
        hint += "）"
        groups.setdefault(category or "未分类", []).append(hint)
    lines = []
    for cat, items in groups.items():
        lines.append(f"{cat}：" + "；".join(items[:18]))
    return "\n".join(lines) if lines else "（无启用虚词）"


def _split_sections(paragraphs: list[dict]) -> list[dict]:
    heading = "开篇"
    buf: list[str] = []
    sections: list[dict] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append({"heading": heading, "text": body})

    for p in paragraphs:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if _is_heading_para(p):
            flush()
            heading = text[:48]
            buf = []
            continue
        buf.append(text)
    flush()
    return sections or [{"heading": "全文", "text": "\n".join((p.get("text") or "") for p in paragraphs)}]


def _pack_chunks(sections: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    heading = sections[0]["heading"] if sections else "全文"
    buf: list[str] = []
    used = 0
    for sec in sections:
        piece = f"【{sec['heading']}】\n{sec['text']}"
        if buf and len("\n".join(buf)) + len(piece) > CHUNK_CHARS:
            chunks.append({"heading": heading, "text": "\n".join(buf)})
            used += len(chunks[-1]["text"])
            if len(chunks) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
                break
            heading = sec["heading"]
            buf = [piece]
            continue
        if not buf:
            heading = sec["heading"]
        buf.append(piece)
        if len("\n".join(buf)) >= CHUNK_CHARS:
            chunks.append({"heading": heading, "text": "\n".join(buf)})
            used += len(chunks[-1]["text"])
            buf = []
            if len(chunks) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
                break
    if buf and len(chunks) < MAX_CHUNKS and used < MAX_REVIEW_CHARS:
        text = "\n".join(buf)
        chunks.append({"heading": heading, "text": text[: MAX_REVIEW_CHARS - used]})
    return chunks or [{"heading": "全文", "text": ""}]


def _system_prompt(
    word_ref: str,
    *,
    include_templates: bool,
    include_five: bool,
    density_safe: float,
    project_name: str,
) -> str:
    five = ""
    if include_five:
        five = "评判时对照虚词自查五规则：\n" + "\n".join(f"- {r}" for r in FILLER_SELF_CHECK_RULES)
    templates = ""
    if include_templates:
        templates = "以下句式常是万能模板，若原文语义同样空洞可列入，但必须确认没有具体数据后再报：\n" + "\n".join(
            f"- {p}" for p in HIGH_RISK_SENTENCE_PATTERNS
        )
    project = f"本项目名称：{project_name}。" if project_name else ""
    return f"""你是招投标技术标「虚词语义」评审。任务是阅读投标书原文，找出表述很虚、需要补数据才能拿分的句子。
{project}

什么叫虚：措施性章节（施工组织、进度、质量、安全、重难点、人员机械、专项方案等）里只有态度/承诺/口号，没有可核验的数量、工期、责任人、频次、验收标准或规范号。
什么不叫虚：
- 编制依据、工程概况、投标函、承诺书、目录、术语、法规引用等背景章节的原则性表述
- 已有数字、单位、岗位、频次、规范号的句子
- 正常技术用语（如建筑高度、及时报告、全面验收有对象和标准时）
- 仅仅因为出现参考虚词表中的词——见词不得报

参考虚词表（只帮助你辨认空话口径，禁止作为命中清单）：
{word_ref}

{five}
{templates}

空话占比参考线 {density_safe}%：只统计措施性表述，不要把背景章套话算进去。
每段最多 {PER_CHUNK} 条问题。excerpt 必须是原文连续原句，禁止改写、禁止编造。
rewrite 必须是可直接替换原句的量化写法（带数字/对象/频次）。
只返回 JSON：
{{
  "vague_ratio": 0,
  "issues": [
    {{
      "excerpt": "原文原句",
      "location": "章节名",
      "severity": "扣分或建议",
      "kind": "empty_talk或template",
      "reason": "为何虚",
      "need_data": "应补充的数据",
      "rewrite": "带数据的改写句"
    }}
  ]
}}
"""


def _call_chunk(
    *,
    model_id: str,
    chunk: dict,
    word_ref: str,
    include_templates: bool,
    include_five: bool,
    density_safe: float,
    project_name: str,
) -> dict:
    text = (chunk.get("text") or "").strip()
    if len(text) < 40:
        return {"vague_ratio": 0.0, "issues": [], "heading": chunk.get("heading") or "", "chars": len(text)}
    heading = chunk.get("heading") or "技术标"
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            raw = chat_complete(
                model_id=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": _system_prompt(
                            word_ref,
                            include_templates=include_templates,
                            include_five=include_five,
                            density_safe=density_safe,
                            project_name=project_name,
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"以下是投标文件技术标原文（本章标题：{heading}）。请只根据这段原文做虚词语义分析：\n\n{text}",
                    },
                ],
                temperature=0.2,
                timeout=CALL_TIMEOUT,
                extra={"response_format": {"type": "json_object"}},
            )
            data = _loads_json(raw)
            issues = data.get("issues") if isinstance(data.get("issues"), list) else []
            ratio = data.get("vague_ratio")
            try:
                ratio_f = float(ratio) if ratio is not None else 0.0
            except (TypeError, ValueError):
                ratio_f = 0.0
            return {
                "vague_ratio": max(0.0, min(100.0, ratio_f)),
                "issues": issues[:PER_CHUNK],
                "heading": heading,
                "chars": len(text),
                "text": text,
            }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                continue
    logger.warning("E4 filler semantic chunk failed: %s", last_exc)
    return {"vague_ratio": 0.0, "issues": [], "heading": heading, "chars": len(text), "text": text}


def findings_from_semantic(
    payload: dict,
    *,
    source_text: str,
    emit_sentences: bool,
    emit_templates: bool,
    emit_density: bool,
    density_safe: float,
) -> list[dict]:
    """把模型 JSON 收成 Finding，供预审与单测共用。excerpt 必须能对回原文。"""
    findings: list[dict] = []
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    heading = payload.get("heading") or "技术标"
    chunk_text = payload.get("text") or source_text
    seen: set[str] = set()
    examples: list[str] = []

    for raw in issues:
        if not isinstance(raw, dict):
            continue
        excerpt = (raw.get("excerpt") or "").strip()
        snapped = snap_bid_excerpt(excerpt, chunk_text) or snap_bid_excerpt(excerpt, source_text)
        if not snapped:
            continue
        key = re.sub(r"\s+", "", snapped)[:80]
        if key in seen:
            continue
        seen.add(key)
        kind = (raw.get("kind") or "empty_talk").strip()
        loc = (raw.get("location") or heading or "技术标").strip()[:80]
        severity = raw.get("severity") if raw.get("severity") in ("扣分", "建议", "降档") else "扣分"
        if severity == "降档":
            severity = "扣分"
        need = (raw.get("need_data") or "").strip()
        rewrite = (raw.get("rewrite") or "").strip()
        reason = (raw.get("reason") or "").strip()
        bits = [reason or "本句只有态度/套话，缺少可核验数据"]
        if need:
            bits.append(f"应补充：{need}")
        if rewrite:
            bits.append(f"改写参考：{rewrite}")
        suggestion = "。".join(bits)
        examples.append(snapped[:150])
        if kind == "template" and emit_templates:
            findings.append(
                _finding(
                    severity=severity,
                    location=f"{loc} / 高危句式",
                    excerpt=snapped[:180],
                    rule="F10.02 虚词语义-模板句",
                    suggestion=suggestion,
                )
            )
            continue
        if emit_sentences:
            findings.append(
                _finding(
                    severity=severity,
                    location=f"{loc} / 虚词语义",
                    excerpt=snapped[:180],
                    rule="F10.02 虚词语义-缺数据",
                    suggestion=suggestion,
                )
            )

    if emit_density:
        try:
            ratio = float(payload.get("vague_ratio") or 0)
        except (TypeError, ValueError):
            ratio = 0.0
        if ratio > density_safe:
            excerpt = "；".join(examples[:3])
            findings.insert(
                0,
                _finding(
                    severity="扣分",
                    location=f"{heading} / 空话占比",
                    excerpt=excerpt,
                    rule="F10.02 虚词语义-空话占比",
                    suggestion=(
                        f"措施性表述中空话占比约 {round(ratio, 1)}%（参考线 {density_safe}%）。"
                        "请按数字/动作/对象/验证补数据，替换态度词与万能模板句"
                    ),
                ),
            )
    return findings


def run(
    paragraphs: list[dict],
    word_rules: list[tuple] | None = None,
    thresholds: dict | None = None,
    context=None,
    dup_keys: set[str] | None = None,
) -> list[dict]:
    density_on = _enabled("filler_density", dup_keys)
    words_on = _enabled("high_risk_words", dup_keys)
    templates_on = _enabled("high_risk_sentences", dup_keys)
    five_on = _enabled("self_check_five", dup_keys)
    if not (density_on or words_on or templates_on or five_on):
        return []

    raw_rules = word_rules if word_rules is not None else DEFAULT_WORD_PATTERNS
    word_patterns = [_unpack(r) for r in raw_rules]
    word_patterns.sort(key=lambda x: len(x[0]), reverse=True)
    thresholds = thresholds or THRESHOLDS
    density_safe = float(thresholds.get("filler_density_safe", THRESHOLDS["filler_density_safe"]))
    project_name = ""
    if context is not None:
        project_name = getattr(context, "project_name", "") or ""

    sections = _split_sections(paragraphs)
    chunks = [c for c in _pack_chunks(sections) if (c.get("text") or "").strip()]
    if not chunks:
        return []

    word_ref = _word_reference(word_patterns)
    source_text = "\n".join(p.get("text") or "" for p in paragraphs)
    emit_sentences = words_on or five_on or density_on
    try:
        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        logger.warning("E4 filler semantic skipped, no model: %s", exc)
        return []

    packed: list[dict] = []
    if len(chunks) == 1:
        packed.append(
            _call_chunk(
                model_id=model_id,
                chunk=chunks[0],
                word_ref=word_ref,
                include_templates=templates_on,
                include_five=five_on,
                density_safe=density_safe,
                project_name=project_name,
            )
        )
    else:
        workers = min(PARALLEL_WORKERS, len(chunks))
        ordered: list[dict | None] = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(
                    _call_chunk,
                    model_id=model_id,
                    chunk=chunk,
                    word_ref=word_ref,
                    include_templates=templates_on,
                    include_five=five_on,
                    density_safe=density_safe,
                    project_name=project_name,
                ): i
                for i, chunk in enumerate(chunks)
            }
            for fut in as_completed(futs):
                ordered[futs[fut]] = fut.result()
        packed = [row for row in ordered if row]

    findings: list[dict] = []
    weighted_ratio = 0.0
    weight_sum = 0
    all_examples: list[str] = []
    for row in packed:
        chars = int(row.get("chars") or 0)
        weighted_ratio += float(row.get("vague_ratio") or 0) * chars
        weight_sum += chars
        part = findings_from_semantic(
            row,
            source_text=source_text,
            emit_sentences=emit_sentences,
            emit_templates=templates_on,
            emit_density=False,
            density_safe=density_safe,
        )
        for item in part:
            all_examples.append(item.get("excerpt") or "")
        findings.extend(part)

    if density_on and weight_sum:
        ratio = round(weighted_ratio / weight_sum, 1)
        if ratio > density_safe:
            excerpt = "；".join([x for x in all_examples if x][:3])
            findings.insert(
                0,
                _finding(
                    severity="扣分",
                    location="技术标 / 空话占比",
                    excerpt=excerpt,
                    rule="F10.02 虚词语义-空话占比",
                    suggestion=(
                        f"措施性表述中空话占比约 {ratio}%（参考线 {density_safe}%）。"
                        "请按数字/动作/对象/验证补数据，替换态度词与万能模板句"
                    ),
                ),
            )

    seen: set[str] = set()
    uniq: list[dict] = []
    for item in findings:
        sig = (item.get("rule"), re.sub(r"\s+", "", item.get("excerpt") or "")[:80])
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(item)
        if len(uniq) >= ISSUE_CAP:
            break
    return uniq
