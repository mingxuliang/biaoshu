"""逐条匹配标准产品：产品库功能优先，其次知识库文档切片，都对不上才由模型自己写。

命中的部分由代码按库内原文和原图拼装，模型只负责判断「能不能答」以及没覆盖的缺口。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

IMG_TOKEN = "{{IMG:%s}}"
IMG_TOKEN_RE = re.compile(r"\{\{IMG:([^}]+)\}\}")
_PLACEHOLDER_RE = re.compile(r"【此处插入图[:：]?[^】]*】")

_JUDGE_SYSTEM = """你是投标标准产品匹配专家。给你一条招标要求，以及本公司产品库功能和知识库文档片段。
判断这条要求能不能直接用现有标准产品内容应标：
- 满足：候选内容已完整覆盖该要求的全部要点（含数字、期限、数量）。
- 部分满足：覆盖了一部分，请在 gap 里写明没覆盖的要点。
- 无：候选内容与该要求无实质对应。
规则：产品库功能优先；产品库没有再看知识库；不要因个别字相同硬配；ids 必须逐字复制候选里的编号，不得编造。
只输出 JSON：{"verdict":"满足|部分满足|无","source":"标品|知识库|无","featureIds":["..."],"sliceIds":["s1"],"gap":"没覆盖的要点，满足时为空","reason":"一句话依据"}"""


def _json_object(text: str) -> dict:
    import json

    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def feature_view(feature) -> dict:
    return {
        "id": feature.id,
        "name": feature.name or "",
        "module": feature.module or "",
        "params": (feature.params or "").strip(),
        "intro": (feature.intro or "").strip(),
        "bidCopy": (feature.bid_copy or "").strip(),
        "sourceText": (getattr(feature, "source_text", "") or "").strip(),
        "lockedCopy": bool(getattr(feature, "locked_copy", False)),
        "images": [
            {"id": img.id, "caption": img.caption or feature.name}
            for img in (feature.images or [])
            if getattr(img, "storage_path", "")
        ],
    }


def rank_features(features: list, requirement: str, limit: int = 8) -> list:
    """按需求文字对功能点做 BM25 排序，取前几个交给模型判断。拿不到排序时按原顺序截断。"""
    if len(features) <= limit:
        return list(features)
    try:
        import jieba
        from rank_bm25 import BM25Okapi
    except ImportError:
        return list(features)[:limit]

    def tokens(text: str) -> list[str]:
        return [t for t in jieba.lcut(text or "") if t.strip()]

    corpus = [tokens(f"{f.name} {f.module} {f.intro} {f.params} {f.bid_copy}") for f in features]
    scores = BM25Okapi(corpus).get_scores(tokens(requirement))
    ranked = sorted(zip(features, scores), key=lambda x: x[1], reverse=True)
    picked = [f for f, score in ranked[:limit] if score > 0]
    return picked or []


def judge(
    requirement: str,
    features: list[dict],
    snippets: list[dict],
    model_id: str | None,
) -> dict:
    """一次模型调用判断本条要求能否由标品或知识库直接应标。失败或无候选返回 verdict=无。"""
    from .llm import LlmError, chat_complete

    none = {"verdict": "无", "source": "无", "featureIds": [], "sliceIds": [], "gap": "", "reason": ""}
    if not (requirement or "").strip() or not (features or snippets):
        return none
    lines = ["【招标要求】", requirement.strip()[:2000], "", "【产品库功能】"]
    for item in features:
        copy = item.get("bidCopy") or item.get("intro") or ""
        lines.append(
            f"- id={item['id']} 名称：{item['name']} 模块：{item.get('module') or '-'}\n"
            f"  参数：{(item.get('params') or '无')[:400]}\n  应标原文：{copy[:500]}"
        )
    if not features:
        lines.append("（无）")
    lines.append("")
    lines.append("【知识库片段】")
    for index, snip in enumerate(snippets):
        lines.append(f"- id=s{index} 标题：{snip.get('heading') or ''}\n  正文：{(snip.get('text') or '')[:500]}")
    if not snippets:
        lines.append("（无）")
    try:
        text = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": "\n".join(lines)},
            ],
            temperature=0.1,
            timeout=120,
            max_tokens=1200,
        )
    except LlmError:
        logger.exception("standard product judge failed")
        return none
    data = _json_object(text)
    verdict = str(data.get("verdict") or "无").strip()
    if verdict not in ("满足", "部分满足"):
        return none
    valid_features = {f["id"] for f in features}
    valid_slices = {f"s{i}" for i in range(len(snippets))}
    feature_ids = [x for x in (data.get("featureIds") or []) if isinstance(x, str) and x in valid_features]
    slice_ids = [x for x in (data.get("sliceIds") or []) if isinstance(x, str) and x in valid_slices]
    if not feature_ids and not slice_ids:
        return none
    source = "标品" if feature_ids else "知识库"
    return {
        "verdict": verdict,
        "source": source,
        "featureIds": feature_ids,
        "sliceIds": slice_ids if not feature_ids else [],
        "gap": str(data.get("gap") or "").strip(),
        "reason": str(data.get("reason") or "").strip()[:200],
    }


_MD_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_PIPE_LINE = re.compile(r"^[^|\n]*\S\s\|\s\S|^\|.*\|\s*$")


def pipe_tables_to_markdown(text: str) -> str:
    """库内原文里用「 | 」分隔的连续行是表格，补上分隔行，才能在正文和导出里按表格显示。
    已经是标准 Markdown 表（带分隔行）的整段原样带过。"""
    lines = (text or "").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not _PIPE_LINE.match(stripped):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and _PIPE_LINE.match(lines[j].strip()):
            j += 1
        block = lines[i:j]
        if any(_MD_SEP.match(ln.strip()) for ln in block):
            out.extend(block)
            i = j
            continue
        rows = [[c.strip() for c in re.split(r"\s\|\s|^\||\|$", ln.strip())] for ln in block]
        rows = [[c for c in r if c != ""] or [""] for r in rows]
        width = max(len(r) for r in rows)
        if len(block) >= 2 and width >= 2:
            fmt = lambda r: "| " + " | ".join(r + [""] * (width - len(r))) + " |"  # noqa: E731
            out.append(fmt(rows[0]))
            out.append("| " + " | ".join(["---"] * width) + " |")
            out.extend(fmt(r) for r in rows[1:])
        else:
            out.extend(block)
        i = j
    return "\n".join(out)


SOURCE_TEXT_CAP = 8000


def copy_of(feat: dict) -> str:
    """写进标书的库内正文：用户手改过的应标原文优先，其次是源文档原文全文，最后才是改写稿。"""
    if feat.get("lockedCopy") and feat.get("bidCopy"):
        return feat["bidCopy"]
    source = (feat.get("sourceText") or "").strip()
    if source:
        if len(source) > SOURCE_TEXT_CAP:
            cut = source[:SOURCE_TEXT_CAP]
            source = cut[: cut.rfind("\n")] if "\n" in cut else cut
        return source
    return feat.get("bidCopy") or feat.get("intro") or ""


def _first_sentence(text: str, limit: int = 120) -> str:
    text = "\n".join(ln for ln in (text or "").split("\n") if not _PIPE_LINE.match(ln.strip()))
    plain = re.sub(r"\s+", " ", _PLACEHOLDER_RE.sub("", text)).strip()
    cut = re.split(r"(?<=[。；])", plain, maxsplit=1)[0] if plain else ""
    return (cut or plain)[:limit]


def build_answer(
    decision: dict,
    features: list[dict],
    snippets: list[dict],
    placed: dict[str, dict],
    chapter_id: str,
    gap_text: str = "",
) -> tuple[str, list[str]]:
    """按库内原文拼装解决方案正文。图片用 {{IMG:id}} 占位，由调用方换成真实图片。

    placed 记录别的章节已经放过的功能点，重复引用只写「详见」。返回 (正文, 证据编号)。
    """
    verdict = decision.get("verdict") or "满足"
    by_id = {f["id"]: f for f in features}
    blocks: list[str] = []
    evidence: list[str] = []
    first_copy = ""
    if decision.get("featureIds"):
        for fid in decision["featureIds"]:
            feat = by_id.get(fid)
            if not feat:
                continue
            evidence.append(fid)
            earlier = placed.get(fid)
            if earlier and earlier.get("chapterId") != chapter_id:
                blocks.append(f"### {feat['name']}\n\n该功能的详细说明和界面截图详见「{earlier.get('title') or '前文章节'}」。")
                continue
            copy = pipe_tables_to_markdown(copy_of(feat))
            if not first_copy:
                first_copy = copy
            parts = [f"### {feat['name']}"]
            if copy:
                parts.append(copy)
            if feat["params"] and feat["params"] not in copy:
                parts.append(f"技术参数：\n{pipe_tables_to_markdown(feat['params'])}")
            for img in feat["images"]:
                parts.append(IMG_TOKEN % f"product:{img['id']}")
            blocks.append("\n\n".join(parts))
    else:
        for sid in decision.get("sliceIds") or []:
            try:
                snip = snippets[int(sid[1:])]
            except (ValueError, IndexError):
                continue
            evidence.append(f"{snip.get('docId') or ''}#{snip.get('heading') or ''}")
            body = pipe_tables_to_markdown(_PLACEHOLDER_RE.sub("", snip.get("text") or "").strip())
            if not first_copy:
                first_copy = body
            parts = [f"### {snip.get('heading') or '相关说明'}"]
            if body:
                parts.append(body)
            for img in snip.get("images") or []:
                parts.append(IMG_TOKEN % f"knowledge:{img.get('id')}")
            blocks.append("\n\n".join(parts))
    state = "满足" if verdict == "满足" else "部分满足"
    gap = (gap_text or decision.get("gap") or "").strip()
    head = [f"**响应情况：{state}**", ""]
    source_name = "公司标准产品" if decision.get("source") == "标品" else "公司已有技术资料"
    how = _first_sentence(first_copy) or f"由{source_name}直接提供"
    head.append(f"**实现方式：** 采用{source_name}实现。{how}")
    body = "\n\n".join(head) + "\n\n" + "\n\n".join(blocks)
    return body, evidence


def append_gap_and_deviation(solution: str, verdict: str, gap: str, gap_body: str = "") -> str:
    """部分满足时接上缺口应答；满足时写无偏离。"""
    if verdict == "满足":
        return solution.rstrip() + "\n\n**偏离说明：** 无偏离"
    out = solution.rstrip()
    if gap_body.strip():
        out += "\n\n### 其余要求的应答\n\n" + gap_body.strip()
    return out + f"\n\n**偏离说明：** 以下要点由其余要求的应答补充满足：{gap or '见上文'}"


def solution_of(wrapped: str) -> str:
    """取出 generate_chapter_content 返回的「## 解决方案」之后的正文。"""
    match = re.search(r"^##\s*解决方案\s*\n", wrapped or "", re.M)
    return (wrapped[match.end() :] if match else wrapped or "").strip()
