"""知识库轻量级检索：BM25（rank-bm25）+ 中文分词（jieba），不依赖向量库/embedding。

规模较小（企业知识库通常几十到几百篇文档、数千片段）时，BM25 已能提供有效的
关键词相关性排序，供 Writer 章节生成时挑选最相关的参考片段。
"""

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from ..models import KnowledgeDocument, KnowledgeSlice


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def _load_slices(db: Session, doc_ids: list[str]) -> list[KnowledgeSlice]:
    if not doc_ids:
        return []
    return (
        db.query(KnowledgeSlice)
        .filter(KnowledgeSlice.document_id.in_(doc_ids))
        .order_by(KnowledgeSlice.document_id, KnowledgeSlice.seq)
        .all()
    )


def _doc_titles(db: Session, doc_ids: list[str]) -> dict[str, str]:
    if not doc_ids:
        return {}
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    return {d.id: d.title for d in docs}


def list_knowledge_headings(db: Session, doc_ids: list[str], limit: int = 40) -> list[str]:
    """取出已选知识库文档的标题切片，供目录生成借鉴结构（不去重后的顺序 heading）。"""
    if not doc_ids:
        return []
    slices = _load_slices(db, doc_ids)
    seen: set[str] = set()
    headings: list[str] = []
    for slice_ in slices:
        heading = (slice_.heading or "").strip()
        if not heading or heading in seen or heading == "全文":
            continue
        seen.add(heading)
        headings.append(heading)
        if len(headings) >= limit:
            break
    return headings


def retrieve_for_chapter(db: Session, doc_ids: list[str], query: str, top_k: int = 4) -> list[dict]:
    """BM25 命中标题后取其整包子树（正文+配图），避免自动选章时丢下级素材。"""
    from sqlalchemy.orm import selectinload

    if not doc_ids or not query.strip():
        return []
    slices = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id.in_(doc_ids))
        .order_by(KnowledgeSlice.document_id, KnowledgeSlice.seq)
        .all()
    )
    if not slices:
        return []

    corpus = [_tokenize(s.text) for s in slices]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(slices, scores), key=lambda x: x[1], reverse=True)
    seeds = [s.heading for s, score in ranked[:top_k] if score > 0 and s.heading]
    if not seeds:
        return []

    titles = _doc_titles(db, doc_ids)
    chosen = _subtree_slices(slices, seeds)
    return [
        {
            "docId": s.document_id,
            "docTitle": titles.get(s.document_id, ""),
            "heading": s.heading,
            "text": s.text or "",
            "images": [
                {
                    "id": img.id,
                    "caption": img.caption or s.heading,
                    "storage_path": img.storage_path,
                    "filename": img.filename or "",
                }
                for img in (s.images or [])
                if img.storage_path
            ],
        }
        for s in chosen
    ]


def retrieve_by_doc_and_headings(
    db: Session, doc_id: str, headings: list[str], max_slices: int | None = None
) -> list[dict]:
    """勾选章节整包：命中标题及其全部下级切片，正文与配图一并返回，不截断。"""
    from sqlalchemy.orm import selectinload

    slices = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id == doc_id)
        .order_by(KnowledgeSlice.seq.asc())
        .all()
    )
    chosen = _subtree_slices(slices, headings)
    if max_slices:
        chosen = chosen[:max_slices]
    doc = db.get(KnowledgeDocument, doc_id)
    title = doc.title if doc else ""
    return [
        {
            "docId": doc_id,
            "docTitle": title,
            "heading": s.heading,
            "text": s.text or "",
            "images": [
                {
                    "id": img.id,
                    "caption": img.caption or s.heading,
                    "storage_path": img.storage_path,
                    "filename": img.filename or "",
                }
                for img in (s.images or [])
                if img.storage_path
            ],
        }
        for s in chosen
    ]


def _subtree_slices(slices: list[KnowledgeSlice], headings: list[str]) -> list[KnowledgeSlice]:
    """无勾选则整篇；有勾选则取这些标题及其子孙，按原文顺序。"""
    if not slices:
        return []
    if not headings:
        return list(slices)
    wanted = {h for h in headings if h}
    children: dict[str, list[KnowledgeSlice]] = {}
    for row in slices:
        if row.parent_id:
            children.setdefault(row.parent_id, []).append(row)
    picked: set[str] = set()

    def walk(row: KnowledgeSlice) -> None:
        if row.id in picked:
            return
        picked.add(row.id)
        for child in children.get(row.id, []):
            walk(child)

    for row in slices:
        if row.heading in wanted:
            walk(row)
    if not picked:
        return list(slices)
    return [row for row in slices if row.id in picked]


def suggest_docs(
    db: Session, candidate_doc_ids: list[str], query: str, top_k_docs: int = 3, top_k_headings: int = 2
) -> list[dict]:
    """「AI 自动选择」：在候选文档池内检索，按文档分组返回最相关的若干文档及其命中标题。"""
    slices = _load_slices(db, candidate_doc_ids)
    if not slices or not query.strip():
        return []

    corpus = [_tokenize(s.text) for s in slices]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(slices, scores), key=lambda x: x[1], reverse=True)

    titles = _doc_titles(db, candidate_doc_ids)
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for slice_, score in ranked:
        if score <= 0:
            continue
        doc_id = slice_.document_id
        if doc_id not in grouped:
            if len(order) >= top_k_docs:
                continue
            grouped[doc_id] = []
            order.append(doc_id)
        if slice_.heading not in grouped[doc_id] and len(grouped[doc_id]) < top_k_headings:
            grouped[doc_id].append(slice_.heading)

    return [
        {"docId": doc_id, "docTitle": titles.get(doc_id, ""), "chapters": grouped[doc_id]}
        for doc_id in order
    ]
