"""知识库轻量级检索：BM25（rank-bm25）+ 中文分词（jieba），不依赖向量库/embedding。

规模较小（企业知识库通常几十到几百篇文档、数千片段）时，BM25 已能提供有效的
关键词相关性排序，供 Writer 章节生成时挑选最相关的参考片段。

要点：
- 索引对「标题 + 正文」建，标题权重更高；按文档集合缓存，不再每次调用重建。
- 引用章节按标题或 `id:切片id` 解析；没匹配到就返回空，不回退成整篇文档。
- 整包取回有字数上限：超出时每节正文按行截断，所有配图照常保留。
"""

from __future__ import annotations

import threading
import time

import jieba
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import KnowledgeDocument, KnowledgeSlice, KnowledgeSliceImage

DEFAULT_MAX_CHARS = 30000
MIN_SLICE_CHARS = 600
TRUNCATE_NOTE = "\n（本节原文较长，已截取前半部分）"
_CACHE_TTL = 600.0
_CACHE_MAX = 16
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def _signature(db: Session, doc_ids: list[str]) -> tuple:
    count, total = (
        db.query(func.count(KnowledgeSlice.id), func.coalesce(func.sum(func.length(KnowledgeSlice.text)), 0))
        .filter(KnowledgeSlice.document_id.in_(doc_ids))
        .one()
    )
    return (tuple(sorted(doc_ids)), int(count or 0), int(total or 0))


def _index(db: Session, doc_ids: list[str]) -> dict:
    """返回 {rows, bm25}。rows 是按文档、顺序排好的轻量切片字典。结果按文档集合缓存。"""
    ids = [d for d in doc_ids if d]
    if not ids:
        return {"rows": [], "bm25": None}
    key = _signature(db, ids)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    rows = [
        {
            "id": r.id,
            "docId": r.document_id,
            "heading": r.heading or "",
            "text": r.text or "",
            "parentId": r.parent_id,
            "seq": r.seq or 0,
        }
        for r in db.query(
            KnowledgeSlice.id,
            KnowledgeSlice.document_id,
            KnowledgeSlice.heading,
            KnowledgeSlice.text,
            KnowledgeSlice.parent_id,
            KnowledgeSlice.seq,
        )
        .filter(KnowledgeSlice.document_id.in_(ids))
        .order_by(KnowledgeSlice.document_id, KnowledgeSlice.seq)
        .all()
    ]
    bm25 = None
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:  # 精简环境没装 BM25 时只能按引用取片段，不能检索
        BM25Okapi = None
    if rows and BM25Okapi is not None:
        corpus = [_tokenize(f"{r['heading']} {r['heading']} {r['text']}") for r in rows]
        bm25 = BM25Okapi(corpus)
    built = {"rows": rows, "bm25": bm25}
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (now, built)
    return built


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _doc_titles(db: Session, doc_ids: list[str]) -> dict[str, str]:
    if not doc_ids:
        return {}
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    return {d.id: d.title for d in docs}


def list_knowledge_headings(db: Session, doc_ids: list[str], limit: int = 40) -> list[str]:
    """取出已选知识库文档的标题切片，供目录生成借鉴结构（不去重后的顺序 heading）。"""
    if not doc_ids:
        return []
    seen: set[str] = set()
    headings: list[str] = []
    for row in _index(db, doc_ids)["rows"]:
        heading = row["heading"].strip()
        if not heading or heading in seen or heading == "全文":
            continue
        seen.add(heading)
        headings.append(heading)
        if len(headings) >= limit:
            break
    return headings


def _subtree(rows: list[dict], seeds: list[dict]) -> list[dict]:
    """种子切片及其全部下级，按原文顺序。"""
    if not seeds:
        return []
    children: dict[str, list[dict]] = {}
    for row in rows:
        if row["parentId"]:
            children.setdefault(row["parentId"], []).append(row)
    picked: set[str] = set()

    def walk(row: dict) -> None:
        if row["id"] in picked:
            return
        picked.add(row["id"])
        for child in children.get(row["id"], []):
            walk(child)

    for seed in seeds:
        walk(seed)
    return [row for row in rows if row["id"] in picked]


def _resolve_refs(rows: list[dict], refs: list[str]) -> list[dict]:
    """引用写法：标题文字（同名取第一个）或 `id:切片id`。没匹配到的引用不扩大范围。"""
    by_id = {row["id"]: row for row in rows}
    first_by_heading: dict[str, dict] = {}
    for row in rows:
        first_by_heading.setdefault(row["heading"], row)
    seeds: list[dict] = []
    for ref in refs:
        if not ref:
            continue
        if ref.startswith("id:"):
            row = by_id.get(ref[3:])
        else:
            row = first_by_heading.get(ref)
        if row and row not in seeds:
            seeds.append(row)
    return seeds


def _cap_chars(rows: list[dict], max_chars: int) -> list[dict]:
    """总字数超限时，每节正文按行截断到平均额度（不低于 MIN_SLICE_CHARS）。配图不受影响。"""
    total = sum(len(r["text"]) for r in rows)
    if not max_chars or total <= max_chars or not rows:
        return rows
    quota = max(MIN_SLICE_CHARS, max_chars // len(rows))
    out: list[dict] = []
    for row in rows:
        text = row["text"]
        if len(text) > quota:
            cut = text[:quota]
            cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
            row = {**row, "text": cut.rstrip() + TRUNCATE_NOTE}
        out.append(row)
    return out


def _with_images(db: Session, rows: list[dict], titles: dict[str, str]) -> list[dict]:
    ids = [r["id"] for r in rows]
    images: dict[str, list[KnowledgeSliceImage]] = {}
    if ids:
        for img in (
            db.query(KnowledgeSliceImage)
            .filter(KnowledgeSliceImage.slice_id.in_(ids))
            .order_by(KnowledgeSliceImage.created_at)
            .all()
        ):
            images.setdefault(img.slice_id, []).append(img)
    return [
        {
            "docId": r["docId"],
            "docTitle": titles.get(r["docId"], ""),
            "heading": r["heading"],
            "text": r["text"],
            "images": [
                {
                    "id": img.id,
                    "caption": img.caption or r["heading"],
                    "storage_path": img.storage_path,
                    "filename": img.filename or "",
                }
                for img in images.get(r["id"], [])
                if img.storage_path
            ],
        }
        for r in rows
    ]


def retrieve_for_chapter(
    db: Session, doc_ids: list[str], query: str, top_k: int = 4, max_chars: int = DEFAULT_MAX_CHARS
) -> list[dict]:
    """BM25 命中切片后取其整包子树（正文+配图），避免自动选章时丢下级素材。"""
    if not doc_ids or not query.strip():
        return []
    built = _index(db, doc_ids)
    rows, bm25 = built["rows"], built["bm25"]
    if not rows or bm25 is None:
        return []
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(rows, scores), key=lambda x: x[1], reverse=True)
    seeds = [row for row, score in ranked[:top_k] if score > 0]
    chosen = _cap_chars(_subtree(rows, seeds), max_chars)
    return _with_images(db, chosen, _doc_titles(db, doc_ids))


def retrieve_by_doc_and_headings(
    db: Session,
    doc_id: str,
    headings: list[str],
    max_slices: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[dict]:
    """勾选章节整包：命中章节及其全部下级，正文与配图一并返回。
    不给章节时取整篇；给了章节但一个都没匹配到时返回空，不扩大成整篇。"""
    rows = [r for r in _index(db, [doc_id])["rows"] if r["docId"] == doc_id]
    wanted = [h for h in (headings or []) if h]
    chosen = _subtree(rows, _resolve_refs(rows, wanted)) if wanted else list(rows)
    if max_slices:
        chosen = chosen[:max_slices]
    chosen = _cap_chars(chosen, max_chars)
    return _with_images(db, chosen, _doc_titles(db, [doc_id]))


def suggest_docs(
    db: Session, candidate_doc_ids: list[str], query: str, top_k_docs: int = 3, top_k_headings: int = 2
) -> list[dict]:
    """「AI 自动选择」：在候选文档池内检索，按文档分组返回最相关的若干文档及其命中标题。"""
    if not candidate_doc_ids or not query.strip():
        return []
    built = _index(db, candidate_doc_ids)
    rows, bm25 = built["rows"], built["bm25"]
    if not rows or bm25 is None:
        return []
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(rows, scores), key=lambda x: x[1], reverse=True)

    titles = _doc_titles(db, candidate_doc_ids)
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for row, score in ranked:
        if score <= 0:
            continue
        doc_id = row["docId"]
        if doc_id not in grouped:
            if len(order) >= top_k_docs:
                continue
            grouped[doc_id] = []
            order.append(doc_id)
        if row["heading"] not in grouped[doc_id] and len(grouped[doc_id]) < top_k_headings:
            grouped[doc_id].append(row["heading"])

    return [
        {"docId": doc_id, "docTitle": titles.get(doc_id, ""), "chapters": grouped[doc_id]}
        for doc_id in order
    ]
