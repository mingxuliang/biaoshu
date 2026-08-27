import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..audit import project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from .. import storage
from ..engines import rules_config
from ..engines.knowledge_extract import chunk_document, detect_review_flag, extract_full_text_any
from ..engines.knowledge_retrieval import suggest_docs
from ..models import KnowledgeDocument, KnowledgeSlice, User
from ..permissions import PERM_WRITER, require_perm, require_project
from ..schemas import (
    KnowledgeChapterDetailOut,
    KnowledgeChapterOut,
    KnowledgeDocumentOut,
    KnowledgeSuggestIn,
    KnowledgeSuggestOut,
)

router = APIRouter(prefix="/api", tags=["knowledge"])

ALLOWED_EXTS = {".doc", ".docx", ".pdf"}
VALID_SCOPES = {"企业库", "项目库", "个人库"}


def _doc_to_out(doc: KnowledgeDocument) -> KnowledgeDocumentOut:
    return KnowledgeDocumentOut(
        id=doc.id,
        scope=doc.scope,
        type=doc.type,
        title=doc.title,
        tags=doc.tags_json or [],
        projectId=doc.project_id,
        source=doc.filename,
        sliceCount=doc.slice_count,
        reviewFlag=doc.review_flag,
        updatedAt=doc.created_at.isoformat(),
    )


@router.post("/knowledge-documents", response_model=KnowledgeDocumentOut)
async def upload_knowledge_document(
    scope: str = Form(...),
    type: str = Form(...),
    title: str = Form(""),
    tags: str = Form(""),
    project_id: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocumentOut:
    require_perm(current_user, PERM_WRITER)
    if scope not in VALID_SCOPES:
        raise HTTPException(400, "归属范围不合法")
    if scope == "项目库" and not project_id:
        raise HTTPException(400, "归属「项目库」时必须指定项目")
    if scope == "项目库":
        require_project(db, current_user, project_id)

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "仅支持 .doc / .docx / .pdf 格式")

    content = await file.read()
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        slices = chunk_document(tmp_path, ext)
        full_text = extract_full_text_any(tmp_path, ext)
    except Exception as exc:
        raise HTTPException(400, "文档已损坏或无法解析，请重新上传") from exc
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    storage_path = storage.put_bytes("knowledge", content, ext)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    doc_title = title.strip() or os.path.splitext(filename)[0] or "未命名文档"

    word_rules = rules_config.load_enabled_filler_words(db)
    thresholds = rules_config.load_thresholds(db)
    filler_words = [rule[0] for rule in word_rules]

    doc = KnowledgeDocument(
        scope=scope,
        type=type,
        title=doc_title,
        tags_json=tag_list,
        project_id=project_id or None,
        owner_id=current_user.id if scope == "个人库" else None,
        filename=filename,
        storage_path=storage_path,
        size_bytes=len(content),
        slice_count=len(slices),
        review_flag=detect_review_flag(
            full_text,
            filler_words=filler_words,
            threshold=thresholds.get("filler_density_safe"),
        ),
    )
    db.add(doc)
    db.flush()

    for i, s in enumerate(slices):
        db.add(KnowledgeSlice(document_id=doc.id, heading=s["heading"], seq=i, text=s["text"]))

    target = f"知识库 / {doc_title}"
    if scope == "项目库" and project_id:
        target = f"{project_label(db, project_id)} / {doc_title}"
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=target,
        version="—",
        detail=f"上传知识文档至{scope}，切出 {len(slices)} 段",
    )
    db.commit()
    db.refresh(doc)
    return _doc_to_out(doc)


@router.get("/knowledge-documents", response_model=list[KnowledgeDocumentOut])
def list_knowledge_documents(
    scope: str = Query(""),
    type: str = Query(""),
    project_id: str = Query(""),
    keyword: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeDocumentOut]:
    _ = current_user
    query = db.query(KnowledgeDocument)
    if scope and scope != "全部":
        query = query.filter(KnowledgeDocument.scope == scope)
    if type and type != "全部类型":
        query = query.filter(KnowledgeDocument.type == type)
    if project_id:
        query = query.filter(
            (KnowledgeDocument.scope == "企业库")
            | (KnowledgeDocument.scope == "个人库")
            | ((KnowledgeDocument.scope == "项目库") & (KnowledgeDocument.project_id == project_id))
        )

    docs = query.order_by(KnowledgeDocument.created_at.desc()).all()

    if keyword.strip():
        kw = keyword.strip().lower()
        docs = [
            d
            for d in docs
            if kw in d.title.lower() or any(kw in t.lower() for t in (d.tags_json or []))
        ]

    return [_doc_to_out(d) for d in docs]


@router.get("/knowledge-documents/{doc_id}/chapters", response_model=list[KnowledgeChapterOut])
def get_knowledge_chapters(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[KnowledgeChapterOut]:
    _ = current_user
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(404, "知识文档不存在")

    counts: dict[str, int] = {}
    order: list[str] = []
    for s in doc.slices:
        if s.heading not in counts:
            counts[s.heading] = 0
            order.append(s.heading)
        counts[s.heading] += 1

    return [KnowledgeChapterOut(heading=h, sliceCount=counts[h]) for h in order]


@router.get("/knowledge-documents/{doc_id}/chapter-detail", response_model=KnowledgeChapterDetailOut)
def get_knowledge_chapter_detail(
    doc_id: str, heading: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> KnowledgeChapterDetailOut:
    _ = current_user
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(404, "知识文档不存在")

    paragraphs = [
        s.text
        for s in sorted(
            (s for s in doc.slices if s.heading == heading), key=lambda s: s.seq
        )
    ]
    if not paragraphs:
        raise HTTPException(404, "章节不存在")

    return KnowledgeChapterDetailOut(docTitle=doc.title, heading=heading, paragraphs=paragraphs)


@router.delete("/knowledge-documents/{doc_id}")
def delete_knowledge_document(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    require_perm(current_user, PERM_WRITER)
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(404, "知识文档不存在")

    storage_path = doc.storage_path
    db.delete(doc)
    db.commit()
    storage.delete(storage_path)

    return {"ok": True}


@router.get("/knowledge-documents/{doc_id}/download")
def download_knowledge_document(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    _ = current_user
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "知识文档不存在")
    try:
        return storage.http_response(
            doc.storage_path,
            filename=doc.filename or doc.title or "knowledge.bin",
        )
    except FileNotFoundError:
        raise HTTPException(404, "知识文档不存在")


@router.post("/projects/{project_id}/knowledge-suggest", response_model=list[KnowledgeSuggestOut])
def suggest_knowledge_for_project(
    project_id: str,
    payload: KnowledgeSuggestIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeSuggestOut]:
    require_project(db, current_user, project_id, PERM_WRITER)
    candidates = (
        db.query(KnowledgeDocument)
        .filter(
            (KnowledgeDocument.scope == "企业库")
            | (KnowledgeDocument.scope == "个人库")
            | ((KnowledgeDocument.scope == "项目库") & (KnowledgeDocument.project_id == project_id))
        )
        .all()
    )
    doc_ids = [d.id for d in candidates]
    results = suggest_docs(db, doc_ids, payload.query)
    return [KnowledgeSuggestOut(**r) for r in results]
