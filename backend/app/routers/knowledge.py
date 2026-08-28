import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from ..audit import project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from .. import storage
from ..engines import rules_config
from ..engines.knowledge_extract import chunk_document, detect_review_flag, extract_full_text_any
from ..engines.knowledge_retrieval import suggest_docs
from ..models import KnowledgeDocument, KnowledgeSlice, KnowledgeSliceImage, User
from ..permissions import PERM_WRITER, require_perm, require_project
from ..schemas import (
    KnowledgeChapterDetailOut,
    KnowledgeChapterOut,
    KnowledgeDocumentOut,
    KnowledgeSliceImageOut,
    KnowledgeSuggestIn,
    KnowledgeSuggestOut,
)

router = APIRouter(prefix="/api", tags=["knowledge"])

ALLOWED_EXTS = {".doc", ".docx", ".pdf"}
VALID_SCOPES = {"企业库", "项目库", "个人库"}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


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


def _img_out(img: KnowledgeSliceImage) -> KnowledgeSliceImageOut:
    return KnowledgeSliceImageOut(
        id=img.id,
        caption=img.caption or "",
        url=f"/api/knowledge-slice-images/{img.id}/file",
    )


def _excerpt(text: str) -> str:
    return " ".join((text or "").split())[:120]


def _chapter_from_slice(slice_row: KnowledgeSlice, children: list[KnowledgeChapterOut]) -> KnowledgeChapterOut:
    images = [_img_out(img) for img in (slice_row.images or [])]
    child_slices = sum(c.sliceCount for c in children)
    child_images = sum(c.imageCount for c in children)
    return KnowledgeChapterOut(
        heading=slice_row.heading,
        sliceCount=1 + child_slices,
        level=slice_row.level or "一级",
        imageCount=len(images) + child_images,
        excerpt=_excerpt(slice_row.text or ""),
        images=images,
        children=children,
    )


def _chapter_from_group(rows: list[KnowledgeSlice], children: list[KnowledgeChapterOut]) -> KnowledgeChapterOut:
    first = rows[0]
    images = [_img_out(img) for row in rows for img in (row.images or [])]
    child_slices = sum(c.sliceCount for c in children)
    child_images = sum(c.imageCount for c in children)
    excerpt = _excerpt(" ".join(row.text or "" for row in rows))
    return KnowledgeChapterOut(
        heading=first.heading,
        sliceCount=len(rows) + child_slices,
        level=first.level or "一级",
        imageCount=len(images) + child_images,
        excerpt=excerpt,
        images=images,
        children=children,
    )


def _persist_slices(db: Session, doc: KnowledgeDocument, slices: list[dict]) -> int:
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
        for img in (item.get("images") or []):
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


def _clear_slices(db: Session, doc: KnowledgeDocument) -> list[str]:
    rows = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id == doc.id)
        .all()
    )
    refs: list[str] = []
    slice_ids = [row.id for row in rows]
    for row in rows:
        for img in row.images or []:
            if img.storage_path:
                refs.append(img.storage_path)
    if slice_ids:
        db.query(KnowledgeSliceImage).filter(KnowledgeSliceImage.slice_id.in_(slice_ids)).delete(
            synchronize_session=False
        )
    db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id == doc.id).update(
        {KnowledgeSlice.parent_id: None}, synchronize_session=False
    )
    db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id == doc.id).delete(synchronize_session=False)
    db.flush()
    db.expire_all()
    return refs


def _collect_image_refs(doc: KnowledgeDocument) -> list[str]:
    refs: list[str] = []
    for slice_row in doc.slices or []:
        for img in slice_row.images or []:
            if img.storage_path:
                refs.append(img.storage_path)
    return refs


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
        slice_count=0,
        review_flag=detect_review_flag(
            full_text,
            filler_words=filler_words,
            threshold=thresholds.get("filler_density_safe"),
        ),
    )
    db.add(doc)
    db.flush()

    saved = _persist_slices(db, doc, slices)
    doc.slice_count = saved

    target = f"知识库 / {doc_title}"
    if scope == "项目库" and project_id:
        target = f"{project_label(db, project_id)} / {doc_title}"
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=target,
        version="—",
        detail=f"上传知识文档至{scope}，切出 {saved} 个章节（含配图）",
    )
    db.commit()
    db.refresh(doc)
    return _doc_to_out(doc)


@router.post("/knowledge-documents/{doc_id}/rechunk", response_model=KnowledgeDocumentOut)
def rechunk_knowledge_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocumentOut:
    require_perm(current_user, PERM_WRITER)
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(404, "知识文档不存在")
    if not doc.storage_path or not storage.exists(doc.storage_path):
        raise HTTPException(400, "原文件不存在，请重新上传")
    ext = os.path.splitext(doc.filename or doc.storage_path)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "仅支持 .doc / .docx / .pdf 格式")
    try:
        with storage.as_local(doc.storage_path, suffix=ext) as path:
            slices = chunk_document(path, ext)
    except Exception as exc:
        raise HTTPException(400, "文档无法按目录重新切片，请检查原文件") from exc

    old_refs = _clear_slices(db, doc)
    saved = _persist_slices(db, doc, slices)
    doc.slice_count = saved
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=f"知识库 / {doc.title}",
        version="—",
        detail=f"按目录重新切片，切出 {saved} 个章节",
    )
    db.commit()
    for ref in old_refs:
        storage.delete(ref)
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

    slices = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id == doc_id)
        .order_by(KnowledgeSlice.seq.asc())
        .all()
    )
    if not slices:
        return []

    children_map: dict[str, list[KnowledgeSlice]] = {}
    for row in slices:
        if row.parent_id:
            children_map.setdefault(row.parent_id, []).append(row)

    if any(row.parent_id for row in slices):
        roots = [row for row in slices if not row.parent_id]

        def build(row: KnowledgeSlice) -> KnowledgeChapterOut:
            kids = [build(child) for child in children_map.get(row.id, [])]
            return _chapter_from_slice(row, kids)

        return [build(row) for row in roots]

    order: list[str] = []
    grouped: dict[str, list[KnowledgeSlice]] = {}
    for row in slices:
        if row.heading not in grouped:
            grouped[row.heading] = []
            order.append(row.heading)
        grouped[row.heading].append(row)
    return [_chapter_from_group(grouped[heading], []) for heading in order]


@router.get("/knowledge-documents/{doc_id}/chapter-detail", response_model=KnowledgeChapterDetailOut)
def get_knowledge_chapter_detail(
    doc_id: str, heading: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> KnowledgeChapterDetailOut:
    _ = current_user
    doc = db.get(KnowledgeDocument, doc_id)
    if not doc:
        raise HTTPException(404, "知识文档不存在")

    rows = (
        db.query(KnowledgeSlice)
        .options(selectinload(KnowledgeSlice.images))
        .filter(KnowledgeSlice.document_id == doc_id, KnowledgeSlice.heading == heading)
        .order_by(KnowledgeSlice.seq.asc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "章节不存在")

    paragraphs = [row.text for row in rows if row.text]
    images = [_img_out(img) for row in rows for img in (row.images or [])]
    return KnowledgeChapterDetailOut(
        docTitle=doc.title,
        heading=heading,
        paragraphs=paragraphs,
        level=rows[0].level or "一级",
        images=images,
    )


@router.get("/knowledge-slice-images/{image_id}/file")
def get_knowledge_slice_image_file(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    img = db.get(KnowledgeSliceImage, image_id)
    if not img or not img.storage_path or not storage.exists(img.storage_path):
        raise HTTPException(404, "附图不存在")
    ext = os.path.splitext(img.filename or img.storage_path)[1].lower()
    media = IMAGE_MIME.get(ext, "image/png")
    try:
        return storage.http_response(img.storage_path, filename=img.filename, media_type=media, inline=True)
    except FileNotFoundError:
        raise HTTPException(404, "附图不存在")


@router.delete("/knowledge-documents/{doc_id}")
def delete_knowledge_document(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    require_perm(current_user, PERM_WRITER)
    doc = (
        db.query(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.slices).selectinload(KnowledgeSlice.images))
        .filter(KnowledgeDocument.id == doc_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, "知识文档不存在")

    image_refs = _collect_image_refs(doc)
    storage_path = doc.storage_path
    db.delete(doc)
    db.commit()
    for ref in image_refs:
        storage.delete(ref)
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
