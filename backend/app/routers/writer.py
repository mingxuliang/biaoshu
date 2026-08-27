import os
import urllib.parse

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines import e_writer
from ..engines.ark_image import ArkImageError, generate_and_save
from ..engines.docx_extract import extract_paragraphs
from ..engines.writer_export import chapters_to_docx
from .. import storage
from ..models import (
    BidDocument,
    EvaluationChecklist,
    Project,
    TenderDocument,
    User,
    WriterDraft,
    WriterImage,
    WriterJob,
)
from ..permissions import PERM_WRITER, require_perm, require_project
from ..schemas import (
    GenerateWriterImageIn,
    OptimizeImagePromptIn,
    OptimizeImagePromptOut,
    OutlineNodeOut,
    SaveChapterContentIn,
    TenderParagraphOut,
    UpdateWriterDraftIn,
    WriterChatIn,
    WriterChatOut,
    WriterDraftOut,
    WriterImageOut,
    WriterJobOut,
)
from ..tasks import run_chapter_generate_task, run_outline_generate_task

router = APIRouter(prefix="/api", tags=["writer"])


def _draft_to_out(draft: WriterDraft) -> WriterDraftOut:
    return WriterDraftOut(
        id=draft.id,
        projectId=draft.project_id,
        modelId=draft.model_id,
        selectedKnowledge=draft.selected_knowledge_json or [],
        selectedProductLibraryId=draft.selected_product_library_id,
        knowledgeRefs=draft.knowledge_refs_json or {},
        settings=draft.settings_json or {},
        interpretSource=draft.interpret_source,
        outline=[OutlineNodeOut(**n) for n in (draft.outline_json or [])],
        chapterContents=draft.chapter_contents_json or {},
        step=draft.step,
    )


def _job_to_out(job: WriterJob) -> WriterJobOut:
    return WriterJobOut(jobId=job.id, kind=job.kind, chapterId=job.chapter_id, status=job.status, error=job.error)


def _require_writer_draft(db: Session, user: User, draft_id: str) -> WriterDraft:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")
    require_project(db, user, draft.project_id, PERM_WRITER)
    return draft


@router.get("/projects/{project_id}/writer-draft", response_model=WriterDraftOut)
def get_or_create_writer_draft(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WriterDraftOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    draft = db.query(WriterDraft).filter(WriterDraft.project_id == project_id).first()
    if not draft:
        draft = WriterDraft(project_id=project_id)
        db.add(draft)
        db.commit()
        db.refresh(draft)
    return _draft_to_out(draft)


@router.patch("/writer-drafts/{draft_id}", response_model=WriterDraftOut)
def update_writer_draft(
    draft_id: str,
    payload: UpdateWriterDraftIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterDraftOut:
    draft = _require_writer_draft(db, current_user, draft_id)

    data = payload.model_dump(exclude_unset=True)
    if "modelId" in data:
        draft.model_id = data["modelId"]
    if "selectedKnowledge" in data:
        draft.selected_knowledge_json = data["selectedKnowledge"]
        flag_modified(draft, "selected_knowledge_json")
    if "selectedProductLibraryId" in data:
        draft.selected_product_library_id = data["selectedProductLibraryId"] or None
    if "knowledgeRefs" in data:
        draft.knowledge_refs_json = data["knowledgeRefs"]
        flag_modified(draft, "knowledge_refs_json")
        refs = data["knowledgeRefs"] or {}
        n_refs = 0
        if isinstance(refs, dict):
            n_refs = sum(len(v) if isinstance(v, list) else 0 for v in refs.values())
        write_audit(
            db,
            action="引用知识",
            user_name=actor_from_request(db, request),
            target=project_label(db, draft.project_id),
            version="—",
            detail=f"撰写工作台引用知识切片 {n_refs} 处",
        )
    if "settings" in data:
        draft.settings_json = data["settings"]
        flag_modified(draft, "settings_json")
    if "interpretSource" in data:
        draft.interpret_source = data["interpretSource"]
    if "outline" in data:
        draft.outline_json = data["outline"]
        flag_modified(draft, "outline_json")
    if "step" in data:
        draft.step = data["step"]

    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.post("/writer-drafts/{draft_id}/outline-jobs", response_model=WriterJobOut)
def create_outline_job(
    draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WriterJobOut:
    _require_writer_draft(db, current_user, draft_id)

    job = WriterJob(draft_id=draft_id, kind="outline", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    run_outline_generate_task.delay(job.id)

    return _job_to_out(job)


@router.get("/writer-jobs/{job_id}", response_model=WriterJobOut)
def get_writer_job_status(
    job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WriterJobOut:
    job = db.get(WriterJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    _require_writer_draft(db, current_user, job.draft_id)
    return _job_to_out(job)


@router.post(
    "/writer-drafts/{draft_id}/chapters/{chapter_id}/generate-jobs", response_model=WriterJobOut
)
def create_chapter_generate_job(
    draft_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterJobOut:
    draft = _require_writer_draft(db, current_user, draft_id)

    outline = draft.outline_json or []
    if not any(n.get("id") == chapter_id for n in outline):
        raise HTTPException(404, "章节不存在，可能已被删除")

    job = WriterJob(draft_id=draft_id, kind="chapter", chapter_id=chapter_id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    run_chapter_generate_task.delay(job.id)

    return _job_to_out(job)


@router.patch("/writer-drafts/{draft_id}/chapters/{chapter_id}", response_model=WriterDraftOut)
def save_chapter_content(
    draft_id: str,
    chapter_id: str,
    payload: SaveChapterContentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterDraftOut:
    draft = _require_writer_draft(db, current_user, draft_id)

    contents = dict(draft.chapter_contents_json or {})
    contents[chapter_id] = payload.content
    draft.chapter_contents_json = contents
    flag_modified(draft, "chapter_contents_json")

    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.get("/writer-drafts/{draft_id}/export")
def export_writer_draft_docx(
    draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    draft = _require_writer_draft(db, current_user, draft_id)
    if not draft.outline_json:
        raise HTTPException(400, "尚无目录内容，请先生成目录后再导出")

    project = db.get(Project, draft.project_id)
    project_name = project.name if project else ""

    images = db.query(WriterImage).filter(WriterImage.project_id == draft.project_id).all()
    refs = {img.id: img.storage_path for img in images}

    layout = (draft.settings_json or {}).get("layout") if isinstance(draft.settings_json, dict) else None
    with storage.as_local_map(refs) as image_paths:
        docx_bytes = chapters_to_docx(
            project_name, draft.outline_json or [], draft.chapter_contents_json or {}, image_paths, layout
        )

    key = storage.put_bytes(f"bid-documents/{draft.project_id}", docx_bytes, ".docx")
    display_name = f"{project_name or '投标书'}-撰写工作台导出.docx"
    doc = BidDocument(
        project_id=draft.project_id,
        filename=display_name,
        storage_path=key,
        size_bytes=len(docx_bytes),
        source="writer",
    )
    db.add(doc)
    db.commit()

    encoded_name = urllib.parse.quote(display_name)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"writer-export.docx\"; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/tender-documents/{tender_document_id}/paragraphs", response_model=list[TenderParagraphOut])
def get_tender_document_paragraphs(
    tender_document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TenderParagraphOut]:
    doc = db.get(TenderDocument, tender_document_id)
    if not doc:
        raise HTTPException(404, "招标文件不存在")
    require_project(db, current_user, doc.project_id)
    try:
        with storage.as_local(doc.storage_path) as path:
            paragraphs = extract_paragraphs(path)
    except FileNotFoundError:
        raise HTTPException(404, "招标文件不存在")
    return [
        TenderParagraphOut(index=p["index"], text=p["text"], style=p["style"], outlineLevel=p["outline_level"])
        for p in paragraphs
    ]


UPLOAD_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _image_to_out(img: WriterImage) -> WriterImageOut:
    return WriterImageOut(
        id=img.id,
        projectId=img.project_id,
        source=img.source if img.source in ("generated", "upload", "knowledge", "product") else "generated",
        mode=img.mode if img.mode in ("normal", "flow", "arch") else "normal",
        prompt=img.prompt or "",
        filename=img.filename,
        url=f"/api/writer-images/{img.id}/file",
        createdAt=img.created_at.isoformat() if img.created_at else "",
    )


@router.post("/projects/{project_id}/writer-images/generate", response_model=WriterImageOut)
def generate_writer_image(
    project_id: str,
    payload: GenerateWriterImageIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterImageOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "请填写生图描述")
    try:
        storage_path, filename = generate_and_save(project_id, prompt, payload.mode)
    except ArkImageError as exc:
        raise HTTPException(400, str(exc)) from exc

    img = WriterImage(
        project_id=project_id,
        source="generated",
        mode=payload.mode,
        prompt=prompt,
        filename=filename,
        storage_path=storage_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return _image_to_out(img)


@router.post("/projects/{project_id}/writer-images/upload", response_model=WriterImageOut)
async def upload_writer_image(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterImageOut:
    require_project(db, current_user, project_id, PERM_WRITER)

    original = file.filename or "upload.png"
    ext = os.path.splitext(original)[1].lower()
    if ext not in UPLOAD_IMAGE_EXTS:
        raise HTTPException(400, "仅支持 jpg / png / webp 图片")

    content = await file.read()
    if not content:
        raise HTTPException(400, "上传文件为空")
    key = storage.put_bytes(f"writer-images/{project_id}", content, ext)

    img = WriterImage(
        project_id=project_id,
        source="upload",
        mode="normal",
        prompt="",
        filename=original,
        storage_path=key,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return _image_to_out(img)


@router.get("/projects/{project_id}/writer-images", response_model=list[WriterImageOut])
def list_writer_images(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WriterImageOut]:
    require_project(db, current_user, project_id, PERM_WRITER)
    images = (
        db.query(WriterImage)
        .filter(WriterImage.project_id == project_id)
        .order_by(WriterImage.created_at.desc())
        .all()
    )
    return [_image_to_out(img) for img in images]


@router.get("/writer-images/{image_id}/file")
def get_writer_image_file(
    image_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    img = db.get(WriterImage, image_id)
    if not img or not storage.exists(img.storage_path):
        raise HTTPException(404, "图片不存在")
    require_project(db, current_user, img.project_id)
    ext = os.path.splitext(img.filename or img.storage_path)[1].lower()
    media = IMAGE_MIME.get(ext, "image/png")
    try:
        return storage.http_response(img.storage_path, filename=img.filename, media_type=media, inline=True)
    except FileNotFoundError:
        raise HTTPException(404, "图片不存在")


@router.post("/writer-images/optimize-prompt", response_model=OptimizeImagePromptOut)
def optimize_writer_image_prompt(
    payload: OptimizeImagePromptIn,
    current_user: User = Depends(get_current_user),
) -> OptimizeImagePromptOut:
    require_perm(current_user, PERM_WRITER)
    return OptimizeImagePromptOut(prompt=e_writer.optimize_image_prompt(payload.prompt, payload.mode))


@router.post("/writer-drafts/{draft_id}/chat", response_model=WriterChatOut)
def writer_chat(
    draft_id: str,
    payload: WriterChatIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterChatOut:
    draft = _require_writer_draft(db, current_user, draft_id)
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(400, "请输入问题")

    project = db.get(Project, draft.project_id)
    project_name = project.name if project else ""

    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == draft.project_id, EvaluationChecklist.status == "done")
        .order_by(EvaluationChecklist.locked.desc(), EvaluationChecklist.version.desc())
        .first()
    )
    data = (checklist.checklist_json or {}) if checklist else {}
    score_rules = data.get("scoreRules") or []
    must_respond = data.get("mustRespond") or []
    if not isinstance(score_rules, list):
        score_rules = []
    if not isinstance(must_respond, list):
        must_respond = []

    outline_titles = []
    for node in draft.outline_json or []:
        if isinstance(node, dict) and node.get("title"):
            num = node.get("num") or ""
            outline_titles.append(f"{num} {node['title']}".strip())

    history = [{"role": m.role, "content": m.content} for m in payload.history]
    reply = e_writer.chat_assist(
        message,
        history,
        project_name,
        score_rules,
        must_respond,
        outline_titles,
        payload.chapterTitle or "",
        payload.chapterExcerpt or "",
        draft.model_id,
    )
    return WriterChatOut(reply=reply, hasChecklist=bool(score_rules or must_respond))
