"""分块通读扫描：按章节把投标书正文切块，逐块核对一批「待应答清单」是否被实质性写到。

用于关键词检索完全落空的条款/评分点——例如评分尺子本来就是评委打分语言，投标书原文
根本搜不到这些字；或投标书换了说法、关键词窗口检索不到候选段落。这类条目不再直接判
「未响应」，而是升级到本模块：按章节分块通读投标书正文，每块正文带着「全部待扫条目」
一次性问模型，跨块合并——任意一块判定命中就算已应答。

不是逐条调模型：调用次数量级是「块数」（≤ MAX_CHUNKS），不随条目数线性放大。
分块基础设施与 `e3_semantic.py` 五维语义评审共用同一套参数（章节边界切分、30 万字/
19 块预算），生产环境已验证过延迟量级；`e3_semantic.py` 从本模块导入并重新导出，
对外名字不变。

安全兜底：模型不可用或全部调用失败时，比照 `clause_cover._verify_llm` 的「宁缺毋滥」
策略——不判未响应，标记已应答并注明原因，避免模型故障时把报告刷满假缺项。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .llm import LlmError, chat_complete, get_default_model_id

logger = logging.getLogger(__name__)

# 单块约 1.6 万字；合计最多送审 30 万字（约 19 块），与 e3_semantic 五维语义评审同一
# 预算，避免百万字标把预审拖成几十分钟。
CHUNK_CHARS = 16000
MAX_REVIEW_CHARS = 300_000
MAX_CHUNKS = 19
PARALLEL_WORKERS = 4
CALL_TIMEOUT = 60
# 每次调用最多带上多少个待扫条目；条目更多时拆成多批，仍是「块数 × 批数」量级的调用。
ITEMS_PER_CALL = 40

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
    """送审上限：累计 30 万字、最多 MAX_CHUNKS 块。短碎片并入上一块；未送审章节占用剩余额度。"""
    coalesced: list[dict] = []
    for chunk in chunks:
        body = chunk.get("text") or ""
        if coalesced and len(body) < 400:
            prev = dict(coalesced[-1])
            prev["text"] = ((prev.get("text") or "").rstrip() + "\n" + body).strip()
            coalesced[-1] = prev
            continue
        coalesced.append(dict(chunk))

    kept: list[dict] = []
    used = 0
    leftover: list[dict] = []
    leftover_prefix = ""
    for i, chunk in enumerate(coalesced):
        body = chunk.get("text") or ""
        if used >= MAX_REVIEW_CHARS or len(kept) >= MAX_CHUNKS:
            leftover.extend(coalesced[i:])
            break
        room = MAX_REVIEW_CHARS - used
        if room <= 0:
            leftover.extend(coalesced[i:])
            break
        if len(body) > room:
            trimmed = dict(chunk)
            trimmed["text"] = body[:room]
            kept.append(trimmed)
            leftover_prefix = body[room : room + 2000]
            leftover.extend(coalesced[i + 1 :])
            used += len(trimmed["text"])
            break
        kept.append(chunk)
        used += len(body)

    room = MAX_REVIEW_CHARS - used
    if kept and (leftover or leftover_prefix) and room > 80:
        bits: list[str] = []
        if leftover_prefix:
            bits.append(leftover_prefix)
        for c in leftover[:12]:
            heading = (c.get("heading") or "").strip() or "未标注章节"
            snippet = (c.get("text") or "").strip()[:2000]
            bits.append(f"【{heading}】\n{snippet}")
        extra = "【后续未送审章节（标题+文首）】\n" + "\n\n".join(bits)
        extra = extra[: min(24000, room)]
        kept[-1] = dict(kept[-1])
        kept[-1]["text"] = kept[-1]["text"].rstrip() + "\n" + extra
    return kept or coalesced[:1] or chunks[:1]


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
        elif buf_len + line_len > CHUNK_CHARS and buf and line_len <= CHUNK_CHARS:
            flush()
            if at_heading:
                heading = line.strip()[:40]
        elif at_heading:
            heading = line.strip()[:40]

        if line_len > CHUNK_CHARS:
            prefix = "\n".join(buf).strip()
            buf = []
            buf_len = 0
            for start in range(0, len(line), CHUNK_CHARS):
                piece = line[start : start + CHUNK_CHARS]
                if start == 0 and prefix:
                    piece = f"{prefix}\n{piece}"
                chunks.append({"text": piece, "heading": heading})
            continue

        buf.append(line)
        buf_len += line_len

    flush()
    return _cap_review_chunks(chunks or [{"text": text, "heading": "全文"}])


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


def _scan_chunk(model_id: str, chunk_text: str, batch: list[dict]) -> dict[str, dict]:
    """把一块正文和一批待扫条目一起送模型，只返回本段确实命中的条目。"""
    catalog = [
        {
            "id": str(it.get("id") or ""),
            "name": str(it.get("title") or it.get("query") or "")[:60],
            "ask": str(it.get("query") or "")[:300],
        }
        for it in batch
    ]
    system = (
        "你在核对投标文件某一段正文，是否实质性回应了下列招标要求/评分点清单里的条目。\n"
        "只能依据这一段正文本身判断，不得凭标题猜测，不得把清单里的条目原文当成投标书内容。\n"
        "目录行、空承诺、只复述招标原文不算响应；同义改写、具体方案、数据、证书、承诺若能对应，才算命中。\n"
        "只返回本段确实命中的条目，未命中的不要出现在结果里；不确定就不要返回。\n"
        '只返回 JSON：{"hits":[{"id":"","excerpt":"投标原句","reason":"一句话"}]}'
    )
    user = f"待核对清单：\n{json.dumps(catalog, ensure_ascii=False)}\n\n投标书正文（本段）：\n{chunk_text[:CHUNK_CHARS]}"
    extra = {"response_format": {"type": "json_object"}}
    try:
        raw = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout=CALL_TIMEOUT,
            max_tokens=2000,
            extra=extra,
        )
    except LlmError:
        raw = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout=CALL_TIMEOUT,
            max_tokens=2000,
        )
    data = _loads_json(raw)
    rows = data.get("hits") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out[str(row["id"])] = {
            "hit": True,
            "excerpt": str(row.get("excerpt") or "").strip(),
            "reason": str(row.get("reason") or "").strip(),
        }
    return out


def scan_items(pending: list[dict], full_text: str) -> dict[str, dict]:
    """按章节分块通读 full_text，核对 pending 里每条是否被投标书实质性写到。

    pending: [{"id", "query"(条款/评分点一句话说的是什么), "title"(可选，用于展示)}]
    返回: {id: {"answered": bool, "excerpt": str, "reason": str, "unanswered_confirmed": bool}}

    只应该被整批调用一次：不是逐条调模型，是把整批 pending 条目和每一块正文一起送模型，
    跨块合并——任意一块命中就算应答。模型不可用或全部调用失败时，按「宁缺毋滥」策略把
    全部条目标记为已应答，避免模型故障时把报告刷满假缺项。
    """
    items = [it for it in (pending or []) if isinstance(it, dict) and str(it.get("id") or "").strip()]
    if not items:
        return {}

    try:
        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clause scan skipped, no model: %s", exc)
        return {
            str(it["id"]): {"answered": True, "reason": f"未配置可用大模型（{exc}），按宁缺毋滥视为已响应"}
            for it in items
        }

    chunks = _split_chunks(full_text or "")
    if not chunks or not any((c.get("text") or "").strip() for c in chunks):
        return {
            str(it["id"]): {"answered": True, "reason": "投标书正文为空，按宁缺毋滥视为已响应"}
            for it in items
        }

    item_batches = [items[i : i + ITEMS_PER_CALL] for i in range(0, len(items), ITEMS_PER_CALL)]
    jobs = [(chunk, batch) for chunk in chunks for batch in item_batches]

    def work(chunk: dict, batch: list[dict]) -> tuple[dict[str, dict], bool]:
        try:
            return _scan_chunk(model_id, chunk.get("text") or "", batch), True
        except Exception:  # noqa: BLE001 —— 单块失败不拖垮整批扫描
            logger.exception("clause scan chunk call failed")
            return {}, False

    merged: dict[str, dict] = {}
    ok_count = 0
    workers = min(PARALLEL_WORKERS, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, chunk, batch) for chunk, batch in jobs]
        for fut in as_completed(futures):
            hits, ok = fut.result()
            if ok:
                ok_count += 1
            for item_id, row in hits.items():
                if not row.get("hit") or item_id in merged:
                    continue
                merged[item_id] = {
                    "answered": True,
                    "excerpt": str(row.get("excerpt") or "").strip(),
                    "reason": str(row.get("reason") or "投标书已通读确认实质性响应。"),
                    "unanswered_confirmed": False,
                }

    all_calls_failed = ok_count == 0 and len(jobs) > 0
    out: dict[str, dict] = {}
    for it in items:
        item_id = str(it["id"])
        if item_id in merged:
            out[item_id] = merged[item_id]
        elif all_calls_failed:
            out[item_id] = {"answered": True, "reason": "模型调用失败，按宁缺毋滥视为已响应"}
        else:
            out[item_id] = {
                "answered": False,
                "excerpt": "",
                "reason": "对照本项招标要求，投标书中未见相应的实质性响应内容。",
                "unanswered_confirmed": True,
            }
    return out
