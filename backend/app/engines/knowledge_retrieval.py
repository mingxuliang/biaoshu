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


def retrieve_for_chapter(db: Session, doc_ids: list[str], query: str, top_k: int = 4) -> list[dict]:
    """在给定文档池内，按 query 用 BM25 检索最相关的 top_k 个片段。"""
    slices = _load_slices(db, doc_ids)
    if not slices or not query.strip():
        return []

    corpus = [_tokenize(s.text) for s in slices]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))

    titles = _doc_titles(db, doc_ids)
    ranked = sorted(zip(slices, scores), key=lambda x: x[1], reverse=True)

    results = []
    for slice_, score in ranked[:top_k]:
        if score <= 0:
            continue
        results.append(
            {
                "docId": slice_.document_id,
                "docTitle": titles.get(slice_.document_id, ""),
                "heading": slice_.heading,
                "text": slice_.text,
            }
        )
    return results


def retrieve_by_doc_and_headings(
    db: Session, doc_id: str, headings: list[str], max_slices: int = 6
) -> list[dict]:
    """章节级精确引用：直接取指定文档下匹配 headings 的全部片段（截断避免过长）。"""
    query = db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id == doc_id)
    if headings:
        query = query.filter(KnowledgeSlice.heading.in_(headings))
    slices = query.order_by(KnowledgeSlice.seq).limit(max_slices).all()

    doc = db.get(KnowledgeDocument, doc_id)
    title = doc.title if doc else ""
    return [{"docId": doc_id, "docTitle": title, "heading": s.heading, "text": s.text} for s in slices]


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
