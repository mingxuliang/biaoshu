"""E3 技术标五维语义引擎（对应青天第三层「技术标核心 AI 评分点」，前端 L3）。

调用 DeepSeek Chat Completions API。长标书按章节切块送审（含表格文字），
默认最多 30 万字，并行评审后按篇幅加权合并五维分。
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from ..config import get_settings
from .rules_data import (
    DEFAULT_WEIGHTS,
    DIMENSION_LABELS,
    DIMENSION_RUBRIC,
    FILLER_SELF_CHECK_RULES,
    HIGH_SCORE_STRATEGIES,
    TECH_SCORE_MODULES,
)

logger = logging.getLogger(__name__)

# 单块约 1.6 万字；合计最多送审 30 万字（约 19 块），避免百万字标把预审拖成几十分钟。
CHUNK_CHARS = 16000
MAX_REVIEW_CHARS = 300_000
MAX_CHUNKS = 19
PARALLEL_WORKERS = 4
ISSUE_CAP = 60
CALL_TIMEOUT = 60

_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、")
_CN_PAREN = re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]")
_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)")
_ATTACH = re.compile(r"^附件[0-9一二三四五六七八九十]")


def _is_heading_line(line: str) -> bool:
    text = (line or "").strip()
    if not text or len(text) > 48 or "。" in text:
        return False
    return bool(_CHAPTER.match(text) or _CN_DOT.match(text) or _CN_PAREN.match(text) or _DOTTED.match(text) or _ATTACH.match(text))


def _cap_review_chunks(chunks: list[dict]) -> list[dict]:
    """送审上限：累计 30 万字，且不超过 MAX_CHUNKS 块。超出部分只保留章节标题供提示。"""
    kept: list[dict] = []
    used = 0
    leftover_heads: list[str] = []
    for i, chunk in enumerate(chunks):
        body = chunk.get("text") or ""
        if len(kept) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
            leftover_heads.extend(c.get("heading") or "" for c in chunks[i:] if c.get("heading"))
            break
        room = MAX_REVIEW_CHARS - used
        if len(body) > room:
            trimmed = dict(chunk)
            trimmed["text"] = body[:room]
            kept.append(trimmed)
            leftover_heads.extend(c.get("heading") or "" for c in chunks[i + 1 :] if c.get("heading"))
            break
        kept.append(chunk)
        used += len(body)

    leftover_heads = [h for h in leftover_heads if h]
    if kept and leftover_heads:
        extra = "【后续未送审章节标题】" + "、".join(leftover_heads[:20])
        kept[-1] = dict(kept[-1])
        kept[-1]["text"] = kept[-1]["text"].rstrip() + "\n" + extra[:400]
    return kept or chunks[:1]


def _split_chunks(full_text: str) -> list[dict]:
    """按章节边界把正文切成 {text, heading} 块，再按 30 万字上限截取连续前部。

    优先在「第X章 / 一、 / 1.1」标题处断开；单段超长则硬切。
    """
    text = full_text or ""
    if not text.strip():
        return [{"text": "", "heading": "开篇"}]
    if len(text) <= CHUNK_CHARS:
        heading = next((ln.strip() for ln in text.splitlines() if _is_heading_line(ln)), "全文")
        return [{"text": text, "heading": heading}]

    lines = text.splitlines()
    chunks: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    heading = "开篇"

    def flush() -> None:
        nonlocal buf, buf_len
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"text": body, "heading": heading})
        buf = []
        buf_len = 0

    for line in lines:
        line_len = len(line) + 1
        at_heading = _is_heading_line(line)
        if at_heading and buf_len >= int(CHUNK_CHARS * 0.5):
            flush()
            heading = line.strip()[:40]
        elif buf_len + line_len > CHUNK_CHARS and buf:
            flush()
            if at_heading:
                heading = line.strip()[:40]
        elif at_heading:
            heading = line.strip()[:40]

        if line_len > CHUNK_CHARS:
            flush()
            for start in range(0, len(line), CHUNK_CHARS):
                piece = line[start : start + CHUNK_CHARS]
                chunks.append({"text": piece, "heading": heading})
            continue

        buf.append(line)
        buf_len += line_len

    flush()
    return _cap_review_chunks(chunks or [{"text": text, "heading": "全文"}])


def _merge_chunk_results(results: list[dict], lengths: list[int], weights: dict) -> dict:
    total = float(sum(lengths) or 1)
    dims: dict[str, dict] = {}
    for key in weights:
        weighted = 0.0
        reasons: list[str] = []
        for r, n in zip(results, lengths):
            d = (r.get("dimensions") or {}).get(key) or {}
            try:
                weighted += float(d.get("score") or 70) * n
            except (TypeError, ValueError):
                weighted += 70.0 * n
            reason = (d.get("reason") or "").strip()
            if reason and len(reasons) < 8:
                reasons.append(reason)
        dims[key] = {"score": round(weighted / total, 1), "reason": "；".join(reasons)[:800]}

    rank = {"降档": 0, "扣分": 1, "建议": 2}
    issues: list[dict] = []
    seen: set[str] = set()
    for r in results:
        for item in r.get("issues") or []:
            sig = (item.get("excerpt") or item.get("suggestion") or "")[:48]
            if not sig or sig in seen:
                continue
            seen.add(sig)
            issues.append(item)
    issues.sort(key=lambda x: rank.get(x.get("severity") or "", 9))
    return {"dimensions": dims, "issues": issues[:ISSUE_CAP]}


def _call_once(
    text: str,
    weights: dict,
    tech_keys: set[str] | None,
    strategy_keys: set[str] | None,
    self_check_enabled: bool,
    score_rules: list | None,
    chunk_note: str,
) -> dict:
    settings = get_settings()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": _build_system_prompt(weights, tech_keys, strategy_keys, self_check_enabled, score_rules),
            },
            {"role": "user", "content": f"以下是投标文件技术标正文{chunk_note}：\n\n{text}"},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(base_url=settings.deepseek_base_url, timeout=CALL_TIMEOUT) as client:
                resp = client.post("/chat/completions", json=payload, headers=headers)
                if resp.status_code == 429 and attempt == 0:
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                return _normalize(data, weights)
        except Exception as exc:  # noqa: BLE001 —— 单块失败不拖垮全书评审
            last_exc = exc
            if attempt == 0:
                time.sleep(1)
                continue
    name = last_exc.__class__.__name__ if last_exc else "Error"
    return _fallback_result(f"本段调用 DeepSeek 失败（{name}），已用保守默认分", weights)


def run(
    full_text: str,
    weights: dict | None = None,
    tech_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
    score_rules: list | None = None,
) -> dict:
    settings = get_settings()
    weights = weights or DEFAULT_WEIGHTS
    self_check_enabled = dup_keys is None or "self_check_five" in dup_keys

    if not settings.deepseek_api_key:
        return _fallback_result("未配置 DeepSeek API Key，已使用保守默认分，请人工复核技术标内容", weights)

    chunks = _split_chunks(full_text)
    n = len(chunks)
    total_chars = sum(len(c.get("text") or "") for c in chunks)
    logger.info("E3 semantic review: %s chars in %s chunks", total_chars, n)

    def work(index: int, chunk: dict) -> tuple[int, dict, int]:
        heading = chunk.get("heading") or "技术标"
        body = chunk.get("text") or ""
        if n == 1:
            note = "（全文）"
        else:
            note = (
                f"（全书第 {index + 1}/{n} 段，本章标题：{heading}。"
                "完整标书已按章节拆分全部送审；请只评本段，不要因未看到其他章节而压低完整性）"
            )
        result = _call_once(
            body,
            weights,
            tech_keys,
            strategy_keys,
            self_check_enabled,
            score_rules,
            note,
        )
        if n > 1:
            for issue in result.get("issues") or []:
                loc = issue.get("location") or "技术标"
                issue["location"] = f"{heading} / {loc}"
        return index, result, len(body) or 1

    ordered: list[tuple[dict, int] | None] = [None] * n
    workers = min(PARALLEL_WORKERS, n)
    if n == 1:
        _, result, length = work(0, chunks[0])
        ordered[0] = (result, length)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, i, ch) for i, ch in enumerate(chunks)]
            for fut in as_completed(futures):
                i, result, length = fut.result()
                ordered[i] = (result, length)

    results = [pair[0] for pair in ordered if pair is not None]
    lengths = [pair[1] for pair in ordered if pair is not None]
    if not results:
        return _fallback_result("未能完成任何分段评审", weights)
    if len(results) == 1:
        return results[0]
    return _merge_chunk_results(results, lengths, weights)


def _build_system_prompt(
    weights: dict,
    tech_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    self_check_enabled: bool = True,
    score_rules: list | None = None,
) -> str:
    dim_lines = []
    for key, weight in weights.items():
        label = DIMENSION_LABELS.get(key, key)
        rubric = DIMENSION_RUBRIC.get(key, {})
        dim_lines.append(
            f"- {label}({weight}%)：校验重点：{rubric.get('focus', '')}；扣分/否决：{rubric.get('penalty', '')}"
        )
    self_check_rules = FILLER_SELF_CHECK_RULES if self_check_enabled else []
    check_lines = "\n".join(f"{i}. {rule}" for i, rule in enumerate(self_check_rules, 1))
    strategies = [s for s in HIGH_SCORE_STRATEGIES if strategy_keys is None or s["key"] in strategy_keys]
    strategy_lines = "\n".join(f"- {s['category']}：{s['point']}" for s in strategies[:6])
    modules = [m for m in TECH_SCORE_MODULES if tech_keys is None or m["key"] in tech_keys]
    module_lines = "\n".join(f"- {m['module']}：{m['logic']}" for m in modules)
    rule_block = ""
    if score_rules:
        lines = []
        for item in score_rules[:24]:
            if not isinstance(item, dict):
                continue
            dim = item.get("dimension") or "评分点"
            detail = (item.get("detail") or "")[:120]
            weight = item.get("weight") or ""
            w = f"{weight}分" if weight else ""
            lines.append(f"- {dim}{(' ' + w) if w else ''}：{detail}")
        if lines:
            rule_block = "本项目招标解析抽出的评分细则（必须逐条对照本段是否响应，未覆盖的列入 issues，severity 用扣分）：\n" + "\n".join(lines)
    return f"""你是"青天大模型"口径的招投标技术标评审专家。请严格按照以下五维评分标准对当前这一段投标文件打分：
{chr(10).join(dim_lines)}

技术标评分模块：
{module_lines}

{rule_block}

评分时请遵循"虚词自查五规则"：
{check_lines}

属地合规细节（合肥/安徽常见）：临边防护高度 1.2m、扫地杆距地 ≤20cm、扬尘六个 100%。若正文涉及对应主题但缺少量化，在合规性或可落地性中扣分。

高分策略参考（用于给改写建议，不作为虚构加分）：
{strategy_lines}

注意：完整标书已按章节拆分后全部送审。完整性只评本段应有内容是否写清，禁止因为看不到前后章节而给低分。issues 每段最多 8 条，优先降档/扣分，excerpt 必须摘自本段原文。

请仅返回严格的 JSON，不要包含任何其他文字说明，格式如下：
{{
  "dimensions": {{
    "completeness": {{"score": 0-100, "reason": "..."}},
    "relevance": {{"score": 0-100, "reason": "..."}},
    "compliance": {{"score": 0-100, "reason": "..."}},
    "feasibility": {{"score": 0-100, "reason": "..."}},
    "standardization": {{"score": 0-100, "reason": "..."}}
  }},
  "issues": [
    {{"severity": "扣分|降档|建议", "location": "章节/位置描述", "excerpt": "原文片段", "suggestion": "改写建议"}}
  ]
}}
"""


def _normalize(data: dict, weights: dict) -> dict:
    dims: dict[str, dict] = {}
    for key in weights:
        d = (data.get("dimensions") or {}).get(key, {}) or {}
        score = d.get("score", 70)
        try:
            score = max(0.0, min(100.0, float(score)))
        except (TypeError, ValueError):
            score = 70.0
        dims[key] = {"score": score, "reason": d.get("reason", "")}

    issues = []
    for item in (data.get("issues") or [])[:8]:
        severity = item.get("severity") if item.get("severity") in ("扣分", "降档", "建议") else "建议"
        issues.append(
            {
                "engine": "e3_semantic",
                "level": "L3",
                "severity": severity,
                "location": item.get("location", "技术标"),
                "excerpt": (item.get("excerpt") or "")[:200],
                "rule": "五维语义评审（AI 生成，供参考）",
                "tenderQuote": "",
                "suggestion": item.get("suggestion", ""),
                "confidence": 0.6,
            }
        )

    return {"dimensions": dims, "issues": issues}


def _fallback_result(reason: str, weights: dict | None = None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    dims = {key: {"score": 70.0, "reason": reason} for key in weights}
    issues = [
        {
            "engine": "e3_semantic",
            "level": "L3",
            "severity": "建议",
            "location": "技术标 / 五维评审",
            "excerpt": reason,
            "rule": "五维语义评审降级提示",
            "tenderQuote": "",
            "suggestion": "请检查 DeepSeek API Key 配置或网络连通性后重试",
            "confidence": 0.3,
        }
    ]
    return {"dimensions": dims, "issues": issues}
