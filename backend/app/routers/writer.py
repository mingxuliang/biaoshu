import json
import logging
import os
import time
import urllib.parse
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import SessionLocal, get_db
from ..engines import e_writer
from ..engines.ark_image import ArkImageError, generate_and_save
from ..engines.writer_diagram import DiagramError, create_diagram_png
from ..engines.tender_form import extract_forms_from_storage, needs_form_recopy
from ..engines.tender_style import extract_tender_typography_from_storage
from ..engines.writer_export import chapters_to_docx
from .. import storage
from ..models import (
    BidDocument,
    EvaluationChecklist,
    Project,
    TenderDocument,
    User,
    WriterChatFile,
    WriterChatMessage,
    WriterDraft,
    WriterImage,
    WriterJob,
)
from ..permissions import PERM_WRITER, require_perm, require_project
from ..writer_tracks import DOC_KINDS as _DOC_KINDS
from ..writer_tracks import branch_legacy_draft as _branch_legacy_draft
from ..writer_tracks import mirror_shared_fields as _mirror_shared_fields
from ..schemas import (
    GenerateAllChaptersIn,
    GenerateWriterImageIn,
    WriterDiagramIn,
    WriterDiagramOut,
    OptimizeImagePromptIn,
    OptimizeImagePromptOut,
    OutlineNodeOut,
    SaveChapterContentIn,
    TenderParagraphOut,
    UpdateWriterDraftIn,
    WriterChatFileOut,
    WriterChatIn,
    WriterChatOut,
    WriterChatMessageOut,
    WriterDraftOut,
    WriterImageOut,
    WriterJobOut,
)
from ..tasks import (
    run_batch_generate_task,
    run_chapter_generate_task,
    run_outline_generate_task,
    run_product_match_task,
    run_writer_chat_task,
)

router = APIRouter(prefix="/api", tags=["writer"])
logger = logging.getLogger(__name__)


def _draft_to_out(draft: WriterDraft) -> WriterDraftOut:
    return WriterDraftOut(
        id=draft.id,
        projectId=draft.project_id,
        docKind=draft.doc_kind or "tech",
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
    raw = job.result_json if isinstance(job.result_json, dict) else None
    result = None
    if job.kind == "chat":
        reply = str((raw or {}).get("reply") or "")
        trace = (raw or {}).get("trace") or []
        if reply or trace:
            result = {
                "reply": reply,
                "edits": (raw or {}).get("edits") or [],
                "hasChecklist": bool((raw or {}).get("hasChecklist")),
                "engine": (raw or {}).get("engine") or "AgentScope",
                "trace": trace,
            }
    elif raw:
        result = raw
    return WriterJobOut(
        jobId=job.id,
        kind=job.kind,
        chapterId=job.chapter_id,
        status=job.status,
        error=job.error,
        result=result,
    )


def _require_writer_draft(db: Session, user: User, draft_id: str) -> WriterDraft:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")
    require_project(db, user, draft.project_id, PERM_WRITER)
    return draft


def _project_tender_path(db: Session, project_id: str) -> str | None:
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    doc = None
    if checklist and checklist.tender_document_id:
        doc = db.get(TenderDocument, checklist.tender_document_id)
    if not doc:
        doc = (
            db.query(TenderDocument)
            .filter(TenderDocument.project_id == project_id)
            .order_by(TenderDocument.uploaded_at.desc())
            .first()
        )
    if doc and doc.storage_path and storage.exists(doc.storage_path):
        return doc.storage_path
    return None


def _backfill_business_originals(db: Session, draft: WriterDraft) -> None:
    """已有草稿若商务标仍是占位说明，打开时补抽招标书原文。"""
    outline = list(draft.outline_json or [])
    if not outline:
        return
    contents = dict(draft.chapter_contents_json or {})
    need = False
    titles: list[str] = []
    for n in outline:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "")
        kind = e_writer.chapter_kind(
            title, n.get("part"), str(n.get("idea") or ""), str(n.get("requirement") or "")
        )
        if kind not in ("form", "business") and not e_writer.is_original_form_title(title):
            continue
        titles.append(title)
        if needs_form_recopy(contents.get(n.get("id") or "") or ""):
            need = True
    if not need or not titles:
        return
    tender_path = _project_tender_path(db, draft.project_id)
    if not tender_path:
        return
    try:
        originals = extract_forms_from_storage(tender_path, titles, draft.model_id)
    except Exception:  # noqa: BLE001 —— 补抽失败不影响打开草稿
        return
    if not e_writer.fill_business_originals(outline, contents, originals):
        return
    draft.outline_json = outline
    flag_modified(draft, "outline_json")
    draft.chapter_contents_json = contents
    flag_modified(draft, "chapter_contents_json")
    db.commit()
    db.refresh(draft)


def _ensure_tender_layout(db: Session, draft: WriterDraft) -> None:
    """打开草稿时按本项目招标书补正文字体/字号/缩进；已识别过的不覆盖用户改动。"""
    settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
    layout = dict(settings.get("layout") or {}) if isinstance(settings.get("layout"), dict) else {}
    if layout.get("fromTender") and layout.get("bodyFont"):
        return
    tender_path = _project_tender_path(db, draft.project_id)
    if not tender_path:
        return
    try:
        extracted = extract_tender_typography_from_storage(tender_path)
    except Exception:  # noqa: BLE001 —— 识别失败不影响打开草稿
        logger.exception("extract tender typography failed")
        return
    extracted.pop("margins", None)
    layout.update(extracted)
    layout["fromTender"] = True
    settings["layout"] = layout
    draft.settings_json = settings
    flag_modified(draft, "settings_json")
    db.commit()
    db.refresh(draft)


@router.get("/projects/{project_id}/writer-draft", response_model=WriterDraftOut)
def get_or_create_writer_draft(
    project_id: str,
    doc_kind: str = Query("tech"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterDraftOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    wanted = doc_kind if doc_kind in _DOC_KINDS else "tech"
    draft = (
        db.query(WriterDraft)
        .filter(WriterDraft.project_id == project_id, WriterDraft.doc_kind == wanted)
        .first()
    )
    if draft:
        _backfill_business_originals(db, draft)
    else:
        legacy = db.query(WriterDraft).filter(WriterDraft.project_id == project_id).order_by(WriterDraft.created_at.asc()).first()
        if legacy is None:
            draft = WriterDraft(project_id=project_id, doc_kind=wanted)
            db.add(draft)
            db.commit()
            db.refresh(draft)
        else:
            draft = _branch_legacy_draft(db, legacy, wanted)
            _backfill_business_originals(db, draft)
    _ensure_tender_layout(db, draft)
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
    _mirror_shared_fields(db, draft, data)
    return _draft_to_out(draft)


@router.post("/writer-drafts/{draft_id}/outline-jobs", response_model=WriterJobOut)
def create_outline_job(
    draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WriterJobOut:
    _require_writer_draft(db, current_user, draft_id)

    job = WriterJob(draft_id=draft_id, kind="outline", status="queued", user_id=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    run_outline_generate_task.delay(job.id)

    return _job_to_out(job)


@router.post("/writer-drafts/{draft_id}/product-match-jobs", response_model=WriterJobOut)
def create_product_match_job(
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterJobOut:
    draft = _require_writer_draft(db, current_user, draft_id)
    if not draft.selected_product_library_id:
        raise HTTPException(400, "请先在标书设置中选择产品功能库")
    if not (draft.outline_json or []):
        raise HTTPException(400, "请先生成应标目录")
    job = WriterJob(draft_id=draft_id, kind="product-match", status="queued", user_id=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    run_product_match_task.delay(job.id)
    return _job_to_out(job)


@router.get("/writer-jobs/{job_id}", response_model=WriterJobOut)
def get_writer_job_status(
    job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> WriterJobOut:
    job = db.get(WriterJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    _require_writer_draft(db, current_user, job.draft_id)
    if job.kind == "chat" and job.user_id and job.user_id != current_user.id:
        raise HTTPException(404, "任务不存在")
    return _job_to_out(job)


@router.get("/writer-jobs/{job_id}/events")
def stream_writer_job_events(
    job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> StreamingResponse:
    job = db.get(WriterJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    _require_writer_draft(db, current_user, job.draft_id)
    if job.kind == "chat" and job.user_id and job.user_id != current_user.id:
        raise HTTPException(404, "任务不存在")

    def events():
        last = ""
        deadline = time.time() + 600
        while time.time() < deadline:
            session = SessionLocal()
            try:
                row = session.get(WriterJob, job_id)
                if row is None:
                    yield 'data: {"status":"failed","error":"任务不存在"}\n\n'
                    return
                payload = _job_to_out(row).model_dump(mode="json")
            finally:
                session.close()
            blob = json.dumps(payload, ensure_ascii=False)
            if blob != last:
                last = blob
                yield f"data: {blob}\n\n"
            if payload.get("status") in ("done", "failed"):
                return
            time.sleep(0.25)
        yield 'data: {"status":"failed","error":"生成任务超时，请稍后重试"}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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

    job = WriterJob(
        draft_id=draft_id,
        kind="chapter",
        chapter_id=chapter_id,
        status="queued",
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    run_chapter_generate_task.delay(job.id)

    return _job_to_out(job)


@router.get("/writer-layout-presets")
def list_writer_layout_presets(current_user: User = Depends(get_current_user)) -> dict:
    """Word 排版预设模板，设置页选模板时取回整套字段。"""
    require_perm(current_user, PERM_WRITER)
    from ..engines.writer_layout import PRESETS

    return {"presets": PRESETS}


@router.post("/writer-drafts/{draft_id}/generate-all-jobs", response_model=WriterJobOut)
def create_generate_all_job(
    draft_id: str,
    payload: GenerateAllChaptersIn | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterJobOut:
    """按目录一次生成全部章节。默认只补还没有正文的章节，overwrite=true 全部重写。"""
    draft = _require_writer_draft(db, current_user, draft_id)
    if not (draft.outline_json or []):
        raise HTTPException(400, "请先生成应标目录")
    running = (
        db.query(WriterJob)
        .filter(WriterJob.draft_id == draft_id, WriterJob.kind == "batch", WriterJob.status.in_(["queued", "running"]))
        .order_by(WriterJob.created_at.desc())
        .first()
    )
    if running is not None and running.created_at and (datetime.utcnow() - running.created_at).total_seconds() < 7200:
        raise HTTPException(409, "已有一个全文生成任务在进行，请等它结束")
    job = WriterJob(
        draft_id=draft_id,
        kind="batch",
        status="queued",
        user_id=current_user.id,
        result_json={"overwrite": bool(payload.overwrite) if payload else False},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    run_batch_generate_task.delay(job.id)
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
            try:
                from ..engines.tender_package import extract_as_paragraphs

                paragraphs = extract_as_paragraphs(path, doc.filename)
            except Exception:
                paragraphs = []
    except FileNotFoundError:
        raise HTTPException(404, "招标文件不存在")
    return [
        TenderParagraphOut(
            index=p["index"],
            text=p["text"],
            style=p["style"],
            outlineLevel=p["outline_level"],
            page=p.get("page"),
        )
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
        storage_path, filename = generate_and_save(project_id, prompt, payload.mode, payload.style)
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


@router.post("/projects/{project_id}/writer-images/diagram", response_model=WriterDiagramOut)
def generate_writer_diagram(
    project_id: str,
    payload: WriterDiagramIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterDiagramOut:
    require_project(db, current_user, project_id, PERM_WRITER)
    draft = _require_writer_draft(db, current_user, payload.draftId)
    if draft.project_id != project_id:
        raise HTTPException(404, "撰写草稿不存在")
    node = next((item for item in (draft.outline_json or []) if item.get("id") == payload.chapterId), None)
    if not isinstance(node, dict):
        raise HTTPException(404, "章节不存在")
    content = str((draft.chapter_contents_json or {}).get(payload.chapterId) or "")
    try:
        png, mode, prompt, notice = create_diagram_png(
            draft.model_id,
            payload.kind,
            str(node.get("title") or ""),
            content,
            str(node.get("idea") or ""),
        )
    except DiagramError as exc:
        raise HTTPException(400, str(exc)) from exc
    key = storage.put_bytes(f"writer-images/{project_id}", png, ".png", "image/png")
    img = WriterImage(
        project_id=project_id,
        source="generated",
        mode=mode if mode in ("normal", "flow", "arch") else "arch",
        prompt=prompt,
        filename=f"{prompt}.png",
        storage_path=key,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    base = _image_to_out(img)
    return WriterDiagramOut(
        id=base.id,
        projectId=base.projectId,
        source=base.source,
        mode=base.mode,
        prompt=base.prompt,
        filename=base.filename,
        url=base.url,
        createdAt=base.createdAt,
        notice=notice,
    )


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


@router.get("/writer-drafts/{draft_id}/chat-messages", response_model=list[WriterChatMessageOut])
def list_writer_chat_messages(
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WriterChatMessageOut]:
    _require_writer_draft(db, current_user, draft_id)
    rows = (
        db.query(WriterChatMessage)
        .filter(WriterChatMessage.draft_id == draft_id, WriterChatMessage.user_id == current_user.id)
        .order_by(WriterChatMessage.created_at.asc())
        .limit(50)
        .all()
    )
    return [
        WriterChatMessageOut(
            id=row.id,
            role=row.role if row.role in ("user", "assistant") else "assistant",
            content=row.content or "",
            edits=row.edits_json or [],
            trace=row.trace_json or [],
            files=row.files_json or [],
        )
        for row in rows
    ]


@router.delete("/writer-drafts/{draft_id}/chat-messages")
def clear_writer_chat_messages(
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_writer_draft(db, current_user, draft_id)
    (
        db.query(WriterChatMessage)
        .filter(WriterChatMessage.draft_id == draft_id, WriterChatMessage.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True}


CHAT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CHAT_FILE_EXTS = {".docx", ".pdf", ".txt", ".md"} | CHAT_IMAGE_EXTS
CHAT_FILE_MAX_BYTES = 20 * 1024 * 1024
CHAT_FILE_MAX_COUNT = 3
CHAT_FILE_DEFAULT_MESSAGE = "请阅读附件，并说明要如何修改当前标书"
CHAT_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _chat_file_kind(filename: str) -> str:
    return "image" if os.path.splitext(filename or "")[1].lower() in CHAT_IMAGE_EXTS else "file"


def _chat_file_out(draft_id: str, row: WriterChatFile) -> WriterChatFileOut:
    return WriterChatFileOut(
        id=row.id,
        filename=row.filename,
        kind=_chat_file_kind(row.filename),
        url=f"/api/writer-drafts/{draft_id}/chat-files/{row.id}",
    )


def _chat_filename(raw: str, content_type: str = "") -> tuple[str, str]:
    name = os.path.basename((raw or "").replace("\\", "/")).strip() or "附件"
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        ext = CHAT_IMAGE_TYPES.get((content_type or "").split(";")[0].strip().lower(), "")
        if ext:
            name = f"{name}{ext}"
    if ext not in CHAT_FILE_EXTS:
        raise HTTPException(400, "只支持 Word、PDF、TXT、Markdown 和图片（PNG/JPG/WebP/GIF）")
    return name[:180], ext


@router.post("/writer-drafts/{draft_id}/chat-files", response_model=WriterChatFileOut)
def upload_writer_chat_file(
    draft_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterChatFileOut:
    draft = _require_writer_draft(db, current_user, draft_id)
    filename, ext = _chat_filename(file.filename or "", file.content_type or "")
    content = file.file.read()
    if not content:
        raise HTTPException(400, "不能上传空文件")
    if len(content) > CHAT_FILE_MAX_BYTES:
        raise HTTPException(400, "附件不能超过 20MB")
    key = storage.put_bytes(f"writer-chat/{current_user.id}/{draft.id}", content, ext)
    row = WriterChatFile(
        user_id=current_user.id,
        draft_id=draft.id,
        filename=filename,
        storage_path=key,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _chat_file_out(draft.id, row)


@router.get("/writer-drafts/{draft_id}/chat-files/{file_id}")
def get_writer_chat_file(
    draft_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _require_writer_draft(db, current_user, draft_id)
    row = db.get(WriterChatFile, file_id)
    if row is None or row.user_id != current_user.id or row.draft_id != draft_id:
        raise HTTPException(404, "附件不存在")
    if not storage.exists(row.storage_path):
        raise HTTPException(404, "附件不存在")
    media = storage.media_type_of(row.filename)
    inline = _chat_file_kind(row.filename) == "image"
    try:
        return storage.http_response(row.storage_path, filename=row.filename, media_type=media, inline=inline)
    except FileNotFoundError:
        raise HTTPException(404, "附件不存在")


@router.post("/writer-drafts/{draft_id}/chat", response_model=WriterChatOut)
def writer_chat(
    draft_id: str,
    payload: WriterChatIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WriterChatOut:
    draft = _require_writer_draft(db, current_user, draft_id)
    message = (payload.message or "").strip()
    file_ids = [item for item in (payload.fileIds or []) if item]
    if len(file_ids) > CHAT_FILE_MAX_COUNT:
        raise HTTPException(400, "一次最多附带 3 个文件")
    files = []
    for file_id in file_ids:
        attached = db.get(WriterChatFile, file_id)
        if attached is None or attached.user_id != current_user.id or attached.draft_id != draft.id:
            raise HTTPException(404, "附件不存在")
        files.append(attached)
    if not message and files:
        message = "请查看图片，并说明要如何修改当前标书" if all(_chat_file_kind(item.filename) == "image" for item in files) else CHAT_FILE_DEFAULT_MESSAGE
    if not message:
        raise HTTPException(400, "请输入问题")
    if payload.chapterId and not any(
        isinstance(node, dict) and node.get("id") == payload.chapterId for node in (draft.outline_json or [])
    ):
        raise HTTPException(404, "章节不存在，可能已被删除")

    row = WriterChatMessage(
        user_id=current_user.id,
        draft_id=draft.id,
        role="user",
        content=message[:4000],
        files_json=[
            {"id": item.id, "filename": item.filename, "kind": _chat_file_kind(item.filename), "url": f"/api/writer-drafts/{draft.id}/chat-files/{item.id}"}
            for item in files
        ],
    )
    db.add(row)
    db.flush()
    job = WriterJob(
        draft_id=draft.id,
        kind="chat",
        chapter_id=payload.chapterId,
        status="queued",
        user_id=current_user.id,
        result_json={"messageId": row.id, "fileIds": [item.id for item in files]},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    run_writer_chat_task.delay(job.id)
    return WriterChatOut(jobId=job.id)