"""条款是否已在投标书响应：先检索对应段，强字面重合算出响应，否则 LLM 确认。

宁缺毋滥：没有模型、贴不上原句、或模型说已响应，一律不出废标。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from . import clause_scan
from .excerpt_guard import snap_bid_excerpt
from .llm import LlmError, chat_complete, get_default_model_id

logger = logging.getLogger(__name__)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_GENERIC = ("必须", "应当", "须", "应", "提交", "提供", "出具", "附上", "要求", "投标人", "招标人")
_WS = re.compile(r"\s+")

# 与解析派生上限对齐：招标解析字段都要进预审，不再用 5/8 条截断。
CAPS = {"star": 80, "must": 80, "qualification": 80, "format": 80, "score": 200, "custom": 80}


@dataclass
class CoverResult:
    answered: bool
    excerpt: str = ""
    reason: str = ""
    unanswered_confirmed: bool = False
    candidates: list[str] = field(default_factory=list)


def _cjk(text: str) -> str:
    raw = "".join(_CJK.findall(text or ""))
    for prefix in _GENERIC:
        raw = raw.replace(prefix, "")
    return raw


def _windows(text: str, n: int = 8) -> list[str]:
    cjk = _cjk(text)
    if len(cjk) < 4:
        return []
    width = n if len(cjk) >= n else 4
    out = [cjk[i : i + width] for i in range(0, max(1, len(cjk) - width + 1))]
    if cjk[:12] not in out:
        out.insert(0, cjk[:12] if len(cjk) > 12 else cjk)
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        if item in seen or len(item) < 4:
            continue
        seen.add(item)
        uniq.append(item)
        if len(uniq) >= 16:
            break
    return uniq


def substance_blob(full_text: str, paragraphs: list[dict] | None) -> str:
    if not paragraphs:
        return full_text or ""
    parts: list[str] = []
    for p in paragraphs:
        if not isinstance(p, dict):
            continue
        t = (p.get("text") or "").strip()
        if not t:
            continue
        if p.get("isImage") or p.get("fromTable"):
            parts.append(t)
            continue
        if p.get("isHeading"):
            continue
        if len(t) < 20:
            continue
        parts.append(t)
    return "\n".join(parts) if parts else (full_text or "")


def retrieve(clause: str, paragraphs: list[dict] | None, k: int = 5) -> list[str]:
    keys = _windows(clause, 6)
    if not keys:
        return []
    scored: list[tuple[int, str]] = []
    for p in paragraphs or []:
        if not isinstance(p, dict):
            continue
        t = (p.get("text") or "").strip()
        if not t or p.get("isHeading"):
            continue
        hits = sum(1 for key in keys if key in t)
        if hits:
            scored.append((hits, t))
    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    out: list[str] = []
    seen: set[str] = set()
    for _hits, text in scored:
        key = _WS.sub("", text)[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:1200])
        if len(out) >= k:
            break
    return out


def lexical_covered(clause: str, bid: str, title: str = "") -> bool:
    blob = bid or ""
    if not blob.strip():
        return False
    long_keys = [w for w in _windows(clause, 8) if len(w) >= 8]
    if any(w in blob for w in long_keys):
        return True
    short_hits = [w for w in _windows(clause, 6) if len(w) >= 6 and w in blob]
    if len(short_hits) >= 2:
        return True
    title_cjk = _cjk(title)
    if len(title_cjk) >= 4 and title_cjk in blob:
        return True
    return False


def _verify_llm(clause: str, candidates: list[str]) -> CoverResult:
    catalog = "\n\n".join(f"【候选{i}】{text}" for i, text in enumerate(candidates, start=1)) or "（全文未检出对应段落）"
    system = (
        "你在核对投标文件是否实质性响应招标条款。"
        "只能依据给出的候选段落判断。目录标题、空承诺不算响应。"
        "同义改写、证书名称、明确承诺若能对应条款，视为已响应。"
        "只返回 JSON：{\"answered\":true/false,\"excerpt\":\"投标原句或空\",\"reason\":\"一句话\"}"
    )
    user = f"招标条款：\n{clause[:800]}\n\n投标书候选：\n{catalog[:6000]}"
    try:
        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clause cover skipped, no model: %s", exc)
        return CoverResult(answered=True, reason="未配置模型，按宁缺毋滥视为已响应", candidates=candidates)
    try:
        raw = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout=60,
            max_tokens=800,
            extra={"response_format": {"type": "json_object"}},
        )
    except LlmError:
        try:
            raw = chat_complete(
                model_id=model_id,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1,
                timeout=60,
                max_tokens=800,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("clause cover llm failed: %s", exc)
            return CoverResult(answered=True, reason="模型确认失败，按宁缺毋滥视为已响应", candidates=candidates)
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return CoverResult(answered=True, reason="模型返回无法解析，按宁缺毋滥视为已响应", candidates=candidates)
    answered = bool(data.get("answered"))
    excerpt = str(data.get("excerpt") or "").strip()
    hay = "\n".join(candidates)
    snapped = snap_bid_excerpt(excerpt, hay) if excerpt else ""
    if answered:
        return CoverResult(answered=True, excerpt=snapped, reason=str(data.get("reason") or ""), candidates=candidates)
    return CoverResult(
        answered=False,
        excerpt=snapped,
        reason=str(data.get("reason") or "未检出实质性响应"),
        unanswered_confirmed=True,
        candidates=candidates,
    )


def check_clause(
    clause: str,
    *,
    bid: str,
    paragraphs: list[dict] | None = None,
    title: str = "",
) -> CoverResult:
    """单条版本：星号/废标条款、投标保证金等一票否决级检查用这条，风险最高，不能只靠
    关键词窗口。委托给 check_clauses_batch 复用「零候选升级分块通读」兜底，避免关键词
    检索找不到候选时直接把「未检出候选」喂给模型判未响应，误判成假废标/假降档。
    """
    text = (clause or "").strip()
    if len(text) < 4:
        return CoverResult(answered=True, reason="条款过短，不作为未响应")
    result = check_clauses_batch(
        [{"id": "0", "clause": text, "title": title}],
        bid=bid,
        paragraphs=paragraphs,
        full_text=bid,
    )
    return result.get("0") or CoverResult(answered=True, reason="核验异常，按宁缺毋滥视为已响应")


def check_clauses_batch(
    items: list[dict],
    *,
    bid: str,
    paragraphs: list[dict] | None = None,
    full_text: str = "",
) -> dict[str, CoverResult]:
    """一次性核对一批条款/评分点是否已在投标书响应，供一个引擎的一整类条目共用。

    items: [{"id"（本批内唯一）, "clause"（核对用条款/评分点文本）, "title"（可选，用于标题字面命中与展示）}]

    每条先跑现有免费路径：`lexical_covered` 字面命中——命中直接判已响应，不动。
    `retrieve` 关键词窗口检索到候选后用 `_verify_llm` 窄范围校验：若判「已响应」直接采信
    （误判代价低，不升级）；若判「未响应」不直接采信——候选可能只是关键词凑巧命中、并非
    真正对应段落，真正的应答内容可能写在文档别处、窗口检索没扫到，这种情况和「retrieve
    完全找不到候选」一起收集成一批，整批升级调用 `clause_scan.scan_items()` 按章节分块
    通读投标书正文复核（每份预审对这一类条目只跑一次分块扫描，不是逐条调模型）。只有
    分块通读也确认未响应，才最终落成缺项，避免把「窗口找歪/找窄」误判成「投标书没写」。

    返回按 items 的 "id" 建索引的结果字典，调用方现有的 `_collect()` / CAPS 截断逻辑不用改。
    """
    results: dict[str, CoverResult] = {}
    pending_scan: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("id") or "")
        if not item_id:
            continue
        clause = str(it.get("clause") or "").strip()
        title = str(it.get("title") or "")
        if len(clause) < 4:
            results[item_id] = CoverResult(answered=True, reason="条款过短，不作为未响应")
            continue
        if lexical_covered(clause, bid, title):
            results[item_id] = CoverResult(answered=True, reason="投标书已出现对应表述")
            continue
        cands = retrieve(clause, paragraphs)
        if cands:
            narrow = _verify_llm(clause, cands)
            if narrow.answered:
                results[item_id] = narrow
                continue
            pending_scan.append({"id": item_id, "query": clause, "title": title})
            continue
        pending_scan.append({"id": item_id, "query": clause, "title": title})

    if pending_scan:
        scanned = clause_scan.scan_items(pending_scan, full_text)
        for it in pending_scan:
            item_id = it["id"]
            row = scanned.get(item_id) or {}
            results[item_id] = CoverResult(
                answered=bool(row.get("answered")),
                excerpt=str(row.get("excerpt") or ""),
                reason=str(row.get("reason") or ""),
                unanswered_confirmed=bool(row.get("unanswered_confirmed")),
            )
    return results


def cap_overflow_finding(kind: str, omitted: int, level: str, severity: str) -> dict:
    labels = {
        "star": "星号/废标条款",
        "must": "实质性条款",
        "qualification": "资格条件",
        "format": "格式约定",
        "score": "评分点",
        "custom": "自定义规则",
    }
    return {
        "engine": "e_parse_match",
        "level": level,
        "severity": "建议",
        "location": f"需人工抽查 / {labels.get(kind, kind)}",
        "excerpt": "",
        "rule": "约定对照超过自动核验上限",
        "tenderQuote": "",
        "suggestion": f"另有 {omitted} 条{labels.get(kind, kind)}未自动核验，请人工抽查，避免漏项。",
        "confidence": 0.4,
        "issueClass": "human_check",
        "unansweredConfirmed": False,
        "evidenceOk": True,
    }
