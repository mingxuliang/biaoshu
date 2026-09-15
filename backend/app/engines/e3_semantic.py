"""E3 技术标五维语义引擎（对应青天第三层「技术标核心 AI 评分点」，前端 L3）。

按章节把正文、表格文字与全部附图送给模型配置中的看图模型（优先 DeepSeek V4.1 Flash）。
"""

from __future__ import annotations

import base64
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .bid_media import marker_for, seqs_in_text
from .excerpt_guard import display_rule, snap_bid_excerpt
from .llm import LlmError, chat_complete, get_default_model_id, get_vision_model_id, is_vision_model
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
VISION_WORKERS = 2
ISSUE_CAP = 60
CALL_TIMEOUT = 60
VISION_TIMEOUT = 180
MAX_IMAGES_PER_CALL = 8

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
    """送审上限：累计 30 万字，且不超过 MAX_CHUNKS 块。未送审章节并入标题+文首约 2 千字。"""
    kept: list[dict] = []
    used = 0
    leftover: list[dict] = []
    leftover_prefix = ""
    for i, chunk in enumerate(chunks):
        body = chunk.get("text") or ""
        if len(kept) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
            leftover.extend(chunks[i:])
            break
        room = MAX_REVIEW_CHARS - used
        if len(body) > room:
            trimmed = dict(chunk)
            trimmed["text"] = body[:room]
            kept.append(trimmed)
            leftover_prefix = body[room : room + 2000]
            leftover.extend(chunks[i + 1 :])
            break
        kept.append(chunk)
        used += len(body)

    if kept and (leftover or leftover_prefix):
        bits: list[str] = []
        if leftover_prefix:
            bits.append(leftover_prefix)
        for c in leftover[:12]:
            heading = (c.get("heading") or "").strip() or "未标注章节"
            snippet = (c.get("text") or "").strip()[:2000]
            bits.append(f"【{heading}】\n{snippet}")
        extra = "【后续未送审章节（标题+文首）】\n" + "\n\n".join(bits)
        kept[-1] = dict(kept[-1])
        kept[-1]["text"] = kept[-1]["text"].rstrip() + "\n" + extra[:24000]
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


def _pick_model(images: list[dict] | None) -> str:
    has_jpeg = any((img or {}).get("jpeg") for img in (images or []))
    if has_jpeg:
        vision_id = get_vision_model_id()
        if vision_id and is_vision_model(vision_id):
            return vision_id
    return get_default_model_id()


def _user_parts(text: str, chunk_note: str, images: list[dict] | None) -> str | list[dict]:
    body = f"以下是投标文件技术标原文{chunk_note}（含正文、表格文字与附图占位）。必须阅读全部原文和附图，不得只看标题：\n\n{text}"
    ready = [img for img in (images or []) if (img or {}).get("jpeg")]
    if not ready:
        return body
    parts: list[dict] = [{"type": "text", "text": body}]
    for img in ready:
        seq = img.get("seq") or ""
        heading = img.get("heading") or ""
        parts.append(
            {
                "type": "text",
                "text": f"\n{img.get('marker') or marker_for(seq, heading)} 请阅读原图："
                "若为空白、装饰、与标题不符、或不是进度/网络/横道等所称图示，按未实质性响应扣分。",
            }
        )
        b64 = base64.b64encode(img["jpeg"]).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return parts


def _call_once(
    text: str,
    weights: dict,
    tech_keys: set[str] | None,
    strategy_keys: set[str] | None,
    self_check_enabled: bool,
    score_rules: list | None,
    chunk_note: str,
    model_id: str,
    images: list[dict] | None = None,
) -> dict:
    has_img = any((img or {}).get("jpeg") for img in (images or []))
    timeout = VISION_TIMEOUT if has_img else CALL_TIMEOUT
    user_content = _user_parts(text, chunk_note, images)
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            extra: dict = {"response_format": {"type": "json_object"}}
            if has_img:
                extra["thinking"] = {"type": "disabled"}
            raw = chat_complete(
                model_id=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": _build_system_prompt(
                            weights, tech_keys, strategy_keys, self_check_enabled, score_rules
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                timeout=timeout,
                extra=extra,
            )
            data = _loads_json(raw)
            if not data:
                raise ValueError("empty json")
            return _normalize(data, weights, text)
        except Exception as exc:  # noqa: BLE001 —— 单块失败不拖垮全书评审
            last_exc = exc
            if attempt == 0:
                continue
    name = last_exc.__class__.__name__ if last_exc else "Error"
    return _fallback_result(f"本段调用大模型失败（{name}），已用保守默认分", weights)


def _assign_images(chunks: list[dict], images: list[dict] | None) -> tuple[list[list[dict]], list[dict]]:
    by_seq = {int(img.get("seq") or 0): img for img in (images or []) if img.get("seq")}
    used: set[int] = set()
    assigned: list[list[dict]] = []
    for chunk in chunks:
        body = chunk.get("text") or ""
        seqs = seqs_in_text(body)
        batch = [by_seq[s] for s in sorted(seqs) if s in by_seq]
        used |= {int(img.get("seq") or 0) for img in batch}
        assigned.append(batch)
    leftover = [img for seq, img in sorted(by_seq.items()) if seq and seq not in used]
    return assigned, leftover


def _split_image_batches(images: list[dict]) -> list[list[dict]]:
    if not images:
        return [[]]
    out: list[list[dict]] = []
    for i in range(0, len(images), MAX_IMAGES_PER_CALL):
        out.append(images[i : i + MAX_IMAGES_PER_CALL])
    return out


def run(
    full_text: str,
    weights: dict | None = None,
    tech_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
    score_rules: list | None = None,
    images: list[dict] | None = None,
) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    self_check_enabled = dup_keys is None or "self_check_five" in dup_keys
    try:
        model_id = _pick_model(images)
    except (LlmError, Exception) as exc:
        return _fallback_result(f"未配置可用大模型（{exc}），已使用保守默认分，请人工复核技术标内容", weights)

    chunks = _split_chunks(full_text)
    assigned, leftover = _assign_images(chunks, images)
    jobs: list[tuple[int, dict, list[dict]]] = []
    for i, chunk in enumerate(chunks):
        batches = _split_image_batches(assigned[i] if i < len(assigned) else [])
        for batch in batches:
            jobs.append((i, chunk, batch))
    if leftover:
        leftover_text = "\n".join(
            (img.get("marker") or marker_for(img.get("seq") or 0, img.get("heading") or "")) for img in leftover
        )
        leftover_chunk = {"text": leftover_text or "【未挂载附图】", "heading": "未挂载附图"}
        leftover_idx = len(chunks)
        for batch in _split_image_batches(leftover):
            jobs.append((leftover_idx, leftover_chunk, batch))
    n_text = len(chunks)
    total_chars = sum(len(c.get("text") or "") for c in chunks)
    img_n = sum(1 for img in (images or []) if img.get("jpeg"))
    logger.info("E3 semantic review: %s chars in %s chunks, %s figures, %s llm jobs", total_chars, n_text, img_n, len(jobs))

    def work(job_index: int, text_index: int, chunk: dict, batch: list[dict]) -> tuple[int, dict, int]:
        heading = chunk.get("heading") or "技术标"
        body = chunk.get("text") or ""
        if text_index >= n_text:
            note = f"（补送未挂载附图 {len(batch)} 张，必须阅读原图；空白/装饰图按未实质性响应）"
        elif n_text == 1 and len(jobs) == 1:
            note = "（全文）"
        else:
            note = (
                f"（全书第 {text_index + 1}/{n_text} 段，本章标题：{heading}。"
                f"本请求附图 {len(batch)} 张。完整标书已按章节拆分全部送审，附图按出现顺序全部送审；"
                "请只评本段原文与附图，不要因未看到其他章节而压低完整性）"
            )
        result = _call_once(
            body,
            weights,
            tech_keys,
            strategy_keys,
            self_check_enabled,
            score_rules,
            note,
            model_id,
            batch,
        )
        if n_text > 1 or len(jobs) > 1:
            for issue in result.get("issues") or []:
                loc = issue.get("location") or "技术标"
                issue["location"] = f"{heading} / {loc}"
        return job_index, result, len(body) or 1

    ordered: list[tuple[dict, int] | None] = [None] * len(jobs)
    workers = VISION_WORKERS if img_n else min(PARALLEL_WORKERS, max(1, len(jobs)))
    if len(jobs) == 1:
        _, result, length = work(0, 0, jobs[0][1], jobs[0][2])
        ordered[0] = (result, length)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, j, text_i, ch, batch) for j, (text_i, ch, batch) in enumerate(jobs)]
            for fut in as_completed(futures):
                j, result, length = fut.result()
                ordered[j] = (result, length)

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

评分时请遵循"虚词自查五规则"（用于可落地性给分；空话原句不要写入 issues，由专项检查虚词语义分析负责）：
{check_lines}

属地合规细节（合肥/安徽常见）：临边防护高度 1.2m、扫地杆距地 ≤20cm、扬尘六个 100%。若正文涉及对应主题但缺少量化，在合规性或可落地性中扣分。

高分策略（改写建议必须点名其中一条，并说明按该条款写可拿高分）：
{strategy_lines}

注意：完整标书已按章节拆分后全部送审，表格文字与【附图N】原图必须阅读。完整性只评本段应有内容是否写清，禁止因为看不到前后章节而给低分。
仅有章节标题、目录行、空图、装饰图或与标题不符的附图，一律按未实质性响应列入 issues（降档或扣分），不得给高完整性分。
不得凭正文里出现「网络图」「横道图」字样认定已附图，必须从图中看到对应图示。
issues 每段最多 8 条，优先降档/扣分。excerpt 必须摘自本段【正文】或【附图N】占位，禁止摘目录行或带点线页码的目录条目。location 写章节名，不要写「目录」。

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
    {{"severity": "扣分|降档|建议", "location": "章节名/正文位置", "excerpt": "正文原句", "suggestion": "【预审规则-高分策略：《分类》】条款：……。按此写法可拿高分。随后给出可直接替换原文的句子", "strategyKey": "quantify", "applyText": "可直接替换 excerpt 的正文句子"}}
  ]
}}
"""


def _normalize(data: dict, weights: dict, chunk_text: str = "") -> dict:
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
        location = item.get("location", "技术标")
        excerpt = snap_bid_excerpt(item.get("excerpt") or "", chunk_text, location)
        strategy_key = str(item.get("strategyKey") or "")
        issues.append(
            {
                "engine": "e3_semantic",
                "level": "L3",
                "severity": severity,
                "location": location,
                "excerpt": excerpt[:200],
                "rule": display_rule("五维语义评审（AI 生成，供参考）", item.get("suggestion") or "", strategy_key),
                "tenderQuote": "",
                "suggestion": item.get("suggestion", ""),
                "strategyKey": strategy_key,
                "applyText": item.get("applyText") or "",
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
            "excerpt": "",
            "rule": "五维语义评审降级提示",
            "tenderQuote": "",
            "suggestion": "请检查 DeepSeek API Key 配置或网络连通性后重试",
            "confidence": 0.3,
        }
    ]
    return {"dimensions": dims, "issues": issues}
