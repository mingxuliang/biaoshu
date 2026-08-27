"""预审上下文：本企业项目、资质库、知识库、文件形态，供 E1/E2/E4/E5 做本地可核验检查。"""

from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from ..models import BidDocument, KnowledgeSlice, Project, QualificationAsset, TenderDocument
from .. import storage
from .docx_extract import extract_full_text, extract_paragraphs

SENTENCE_LIMIT = 80
OTHER_DOC_LIMIT = 6
TEXT_CAP = 40000


@dataclass
class QualSnap:
    kind: str
    name: str
    level: str
    number: str
    owner: str
    detail: str
    expired: bool
    blob: str


@dataclass
class ReviewContext:
    project_id: str
    project_name: str
    other_project_names: list[str] = field(default_factory=list)
    other_sentences: list[tuple[str, str]] = field(default_factory=list)
    other_full_texts: list[tuple[str, str]] = field(default_factory=list)
    other_file_hashes: list[tuple[str, str]] = field(default_factory=list)
    knowledge_texts: list[str] = field(default_factory=list)
    quals: list[QualSnap] = field(default_factory=list)
    tender_text: str = ""
    current_hash: str = ""
    encrypted: bool = False
    scanned_pdf: bool = False


def _file_md5(ref: str) -> str:
    if not ref:
        return ""
    try:
        data = storage.get_bytes(ref)
    except FileNotFoundError:
        return ""
    return hashlib.md5(data).hexdigest()


def inspect_document(ref: str) -> tuple[bool, bool]:
    """返回 (encrypted, scanned_pdf)。不伪造结果；无法打开则视为加密/损坏。"""
    if not ref:
        return True, False
    try:
        with storage.as_local(ref) as path:
            return _inspect_local(path)
    except FileNotFoundError:
        return True, False


def _inspect_local(path: str) -> tuple[bool, bool]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            with zipfile.ZipFile(path) as zf:
                if any(info.flag_bits & 0x1 for info in zf.infolist()):
                    return True, False
                if "word/document.xml" not in zf.namelist() and "EncryptedPackage" in zf.namelist():
                    return True, False
            extract_paragraphs(path)
        except Exception:
            return True, False
        return False, False
    if ext == ".pdf":
        try:
            import pymupdf as fitz

            with fitz.open(path) as doc:
                if doc.needs_pass:
                    return True, False
                image_pages = 0
                text_pages = 0
                for page in doc:
                    text = (page.get_text("text") or "").strip()
                    images = page.get_images()
                    if len(text) >= 40:
                        text_pages += 1
                    elif images:
                        image_pages += 1
                scanned = image_pages > 0 and text_pages == 0
                return False, scanned
        except Exception:
            return True, False
    return False, False


def _qual_expired(valid_until: str) -> bool:
    text = (valid_until or "").strip() or "长期"
    if text in ("长期", "长期有效", "—", "-"):
        return False
    try:
        expire = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return expire < date.today()


def _sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"[。！？；\n]", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 15][:SENTENCE_LIMIT]


def load_review_context(db: Session, project_id: str, current_path: str | None = None) -> ReviewContext:
    project = db.get(Project, project_id)
    name = project.name if project else ""
    ctx = ReviewContext(project_id=project_id, project_name=name)
    if current_path:
        ctx.current_hash = _file_md5(current_path)
        ctx.encrypted, ctx.scanned_pdf = inspect_document(current_path)

    others = db.query(Project).filter(Project.id != project_id).all()
    ctx.other_project_names = [p.name.strip() for p in others if (p.name or "").strip() and len(p.name.strip()) >= 6]

    other_docs = (
        db.query(BidDocument)
        .filter(BidDocument.project_id != project_id)
        .order_by(BidDocument.uploaded_at.desc())
        .limit(OTHER_DOC_LIMIT)
        .all()
    )
    seen_projects: set[str] = set()
    for doc in other_docs:
        if doc.project_id in seen_projects:
            continue
        seen_projects.add(doc.project_id)
        label = doc.filename or doc.project_id
        other = db.get(Project, doc.project_id)
        if other and other.name:
            label = other.name
        digest = _file_md5(doc.storage_path)
        if digest:
            ctx.other_file_hashes.append((label, digest))
        try:
            with storage.as_local(doc.storage_path) as path:
                text = extract_full_text(path)[:TEXT_CAP]
        except Exception:
            continue
        if not text.strip():
            continue
        ctx.other_full_texts.append((label, text))
        for sent in _sentences(text):
            ctx.other_sentences.append((label, sent))

    slices = db.query(KnowledgeSlice).order_by(KnowledgeSlice.seq.asc()).limit(80).all()
    ctx.knowledge_texts = [(s.text or "")[:800] for s in slices if (s.text or "").strip()]

    tender = (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == project_id)
        .order_by(TenderDocument.uploaded_at.desc())
        .first()
    )
    if tender and tender.storage_path:
        try:
            ext = os.path.splitext(tender.storage_path)[1].lower()
            with storage.as_local(tender.storage_path) as path:
                if ext == ".pdf":
                    import pymupdf as fitz

                    with fitz.open(path) as pdf:
                        ctx.tender_text = "\n".join(page.get_text("text") for page in pdf)[:TEXT_CAP]
                else:
                    ctx.tender_text = extract_full_text(path)[:TEXT_CAP]
        except Exception:
            ctx.tender_text = ""

    for item in db.query(QualificationAsset).all():
        blob = " ".join(
            [
                item.kind or "",
                item.name or "",
                item.level or "",
                item.number or "",
                item.owner or "",
                item.detail or "",
                getattr(item, "ocr_text", "") or "",
            ]
        )
        ctx.quals.append(
            QualSnap(
                kind=item.kind or "",
                name=item.name or "",
                level=item.level or "",
                number=item.number or "",
                owner=item.owner or "",
                detail=item.detail or "",
                expired=_qual_expired(item.valid_until or ""),
                blob=blob,
            )
        )
    return ctx
