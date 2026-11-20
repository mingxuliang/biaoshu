"""文档库后台入库：切章节、虚词自检、规范按条入库、simhash 近重复提示。

上传接口只落文件和建档，解析放到 Celery，避免大文件或扫描件把请求拖到超时。
"""

from __future__ import annotations

import hashlib
import logging
import os
import zipfile
from datetime import datetime

import jieba
from sqlalchemy.orm import Session, selectinload

from .. import storage
from ..models import KnowledgeDocument, KnowledgeSlice, KnowledgeSliceImage
from . import rules_config
from .knowledge_extract import chunk_document, detect_review_flag, extract_full_text_any
from .standard_ingest import clauses_from_path, replace_document_clauses

logger = logging.getLogger(__name__)

# 规范条文抽不出来时，把真正原因说清楚，不要全部收成「文件损坏」。
_STANDARD_FAILURE_MESSAGES = {
    "文档无法读取": "原文件无法打开，可能已损坏或格式不受支持，请重新上传",
    "仅支持 pdf / doc / docx": "仅支持 .pdf / .doc / .docx 格式，请重新上传",
    "扫描页未能抽出文字": "这是扫描件，但没能从任何一页识别出足够的文字，请换一份更清晰的扫描件，或重新发起解析重试",
    "未抽出足够正文": "没能识别出足够的正文，请换一份更清晰的扫描件，或重新发起解析重试",
    "未抽出正文": "没能从文件中抽出正文，请重新发起解析或更换文件",
    "未识别到条号": "已读出正文，但没有找到「4.1.3」这类条号格式，请确认这是规范正文而不是目录或前言部分",
}


def _standard_failure_message(note: str) -> str:
    return _STANDARD_FAILURE_MESSAGES.get(note, note or "未能从文件中识别出条文，请重新发起解析或更换文件")


def _ingest_failure_message(exc: Exception) -> str:
    """区分打不开文件和其他解析异常，不再笼统地说「文件已损坏」。"""
    if isinstance(exc, FileNotFoundError):
        return "原文件已丢失，无法打开，请重新上传"
    if isinstance(exc, zipfile.BadZipFile):
        return "文件已损坏，无法作为 Word 文档打开，请重新上传"
    name = exc.__class__.__name__
    if "FileData" in name or "EmptyFile" in name or "FormatError" in name or "MuPDF" in name:
        return "文件已损坏，无法作为 PDF 打开，请重新上传"
    return "后台解析出现异常，已记录日志，请重新发起解析，若多次失败请联系管理员"

# 64 位 simhash 海明距离不超过这个值视为近似重复
SIMHASH_DISTANCE = 3
MIN_SIMHASH_CHARS = 200


def simhash64(text: str) -> str:
    """按 jieba 分词做 64 位 simhash，词频作权重。正文太短返回空串。"""
    body = "".join((text or "").split())
    if len(body) < MIN_SIMHASH_CHARS:
        return ""
    weights: dict[str, int] = {}
    for token in jieba.lcut(body):
        token = token.strip()
        if len(token) < 2:
            continue
        weights[token] = weights.get(token, 0) + 1
    if not weights:
        return ""
    vector = [0] * 64
    for token, weight in weights.items():
        h = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += weight if (h >> bit) & 1 else -weight
    value = 0
    for bit in range(64):
        if vector[bit] > 0:
            value |= 1 << bit
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def near_duplicate(db: Session, doc: KnowledgeDocument) -> KnowledgeDocument | None:
    """只在上传者能看到的范围里找近似文档：企业库、同项目的项目库、本人的个人库。"""
    if not doc.simhash:
        return None
    rows = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id != doc.id,
            KnowledgeDocument.simhash != "",
            KnowledgeDocument.simhash.isnot(None),
        )
        .all()
    )
    for row in rows:
        if row.scope == "个人库" and row.owner_id != doc.owner_id:
            continue
        if row.scope == "项目库" and row.project_id != doc.project_id:
            continue
        if hamming(doc.simhash, row.simhash) <= SIMHASH_DISTANCE:
            return row
    return None


def clear_existing_slices(db: Session, doc: KnowledgeDocument) -> list[str]:
    """重新解析前清掉旧的章节切片和配图引用，避免叠加出重复内容。返回待删除的配图对象键，
    调用方应在提交事务之后再真正删除存储里的文件。规范条文不走这里，StandardClause 的清理
    在 replace_document_clauses 里按 document_id 整体替换。"""
    rows = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id == doc.id)
        .all()
    )
    if not rows:
        return []
    refs: list[str] = []
    slice_ids = [row.id for row in rows]
    for row in rows:
        for img in row.images or []:
            if img.storage_path:
                refs.append(img.storage_path)
    db.query(KnowledgeSliceImage).filter(KnowledgeSliceImage.slice_id.in_(slice_ids)).delete(synchronize_session=False)
    db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id == doc.id).update(
        {KnowledgeSlice.parent_id: None}, synchronize_session=False
    )
    db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id == doc.id).delete(synchronize_session=False)
    db.flush()
    db.expire_all()
    return refs


def persist_slices(db: Session, doc: KnowledgeDocument, slices: list[dict]) -> int:
    last_primary_id = None
    last_secondary_id = None
    saved = 0
    used_headings: dict[str, int] = {}
    for i, item in enumerate(slices):
        level = item.get("level") if item.get("level") in ("一级", "二级", "三级") else "一级"
        parent_id = None
        if level == "二级":
            parent_id = last_primary_id
        elif level == "三级":
            parent_id = last_secondary_id or last_primary_id
        if level == "一级":
            parent_id = None
        heading = (item.get("heading") or "全文")[:80]
        n = used_headings.get(heading, 0)
        used_headings[heading] = n + 1
        if n:
            heading = f"{heading[:70]}（{n + 1}）"
        row = KnowledgeSlice(
            document_id=doc.id,
            heading=heading,
            seq=i,
            text=item.get("text") or "",
            level=level,
            parent_id=parent_id,
        )
        db.add(row)
        db.flush()
        if level == "一级":
            last_primary_id = row.id
            last_secondary_id = None
        elif level == "二级":
            last_secondary_id = row.id
        heading = row.heading
        for img in item.get("images") or []:
            blob = img.get("blob")
            ext = img.get("ext") or ".png"
            if not blob:
                continue
            key = storage.put_bytes(f"knowledge-images/{doc.id}", blob, ext)
            db.add(
                KnowledgeSliceImage(
                    slice_id=row.id,
                    caption=(img.get("caption") or heading)[:40],
                    filename=f"{heading[:30]}{ext}",
                    storage_path=key,
                    sha256=img.get("sha256") or "",
                )
            )
        saved += 1
    return saved


def ingest_knowledge_document(db: Session, doc_id: str) -> None:
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        return
    doc.status = "running"
    doc.error = None
    db.commit()
    ext = os.path.splitext(doc.filename or doc.storage_path)[1].lower()
    old_image_refs: list[str] = []
    failed_note: str | None = None
    try:
        with storage.as_local(doc.storage_path, suffix=ext) as path:
            if doc.type == "规范条文":
                # 进度按文档在对象存储里的路径记一份固定键：knowledge_ingest 每次用
                # as_local 下载出来的本地临时文件路径都不一样，不能拿那个路径当续跑的键。
                progress_ref = f"knowledge-progress/{doc.storage_path}.json"

                def _on_progress(done: int, total: int, _doc=doc) -> None:
                    _doc.progress_json = {"done": done, "total": total}
                    db.commit()

                clauses, note = clauses_from_path(
                    path, doc.filename or "", progress_ref=progress_ref, on_progress=_on_progress
                )
                if not clauses:
                    failed_note = note
                    saved = 0
                else:
                    saved = replace_document_clauses(db, doc, clauses)
                    doc.review_flag = note or None
            else:
                old_image_refs = clear_existing_slices(db, doc)
                slices = chunk_document(path, ext)
                full_text = extract_full_text_any(path, ext)
                words = [rule[0] for rule in rules_config.load_enabled_filler_words(db)]
                thresholds = rules_config.load_thresholds(db)
                doc.review_flag = detect_review_flag(
                    full_text, filler_words=words, threshold=thresholds.get("filler_density_safe")
                )
                saved = persist_slices(db, doc, slices)
                doc.simhash = simhash64(full_text)
                twin = near_duplicate(db, doc)
                doc.duplicate_hint = f"与《{twin.title}》正文高度相似，可能是重复上传" if twin else ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("knowledge ingest %s failed", doc_id)
        db.rollback()
        doc = db.get(KnowledgeDocument, doc_id)
        if doc:
            doc.status = "failed"
            doc.error = _ingest_failure_message(exc)
            doc.finished_at = datetime.utcnow()
            db.commit()
        return
    if failed_note is not None:
        doc.status = "failed"
        doc.error = _standard_failure_message(failed_note)
        doc.slice_count = 0
        doc.progress_json = None
        doc.finished_at = datetime.utcnow()
        db.commit()
        return
    doc.slice_count = saved
    doc.status = "done"
    doc.progress_json = None
    doc.finished_at = datetime.utcnow()
    db.commit()
    for ref in old_image_refs:
        storage.delete(ref)
