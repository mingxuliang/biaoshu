from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..db import get_db
from ..engines.docx_extract import extract_paragraphs
from ..models import TenderDocument, WriterDraft, WriterJob
from ..schemas import (
    OutlineNodeOut,
    SaveChapterContentIn,
    TenderParagraphOut,
    UpdateWriterDraftIn,
    WriterDraftOut,
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
        knowledgeRefs=draft.knowledge_refs_json or {},
        settings=draft.settings_json or {},
        interpretSource=draft.interpret_source,
        outline=[OutlineNodeOut(**n) for n in (draft.outline_json or [])],
        chapterContents=draft.chapter_contents_json or {},
        step=draft.step,
    )


def _job_to_out(job: WriterJob) -> WriterJobOut:
    return WriterJobOut(jobId=job.id, kind=job.kind, chapterId=job.chapter_id, status=job.status, error=job.error)


@router.get("/projects/{project_id}/writer-draft", response_model=WriterDraftOut)
def get_or_create_writer_draft(project_id: str, db: Session = Depends(get_db)) -> WriterDraftOut:
    draft = db.query(WriterDraft).filter(WriterDraft.project_id == project_id).first()
    if not draft:
        draft = WriterDraft(project_id=project_id)
        db.add(draft)
        db.commit()
        db.refresh(draft)
    return _draft_to_out(draft)


@router.patch("/writer-drafts/{draft_id}", response_model=WriterDraftOut)
def update_writer_draft(
    draft_id: str, payload: UpdateWriterDraftIn, db: Session = Depends(get_db)
) -> WriterDraftOut:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")

    data = payload.model_dump(exclude_unset=True)
    if "modelId" in data:
        draft.model_id = data["modelId"]
    if "selectedKnowledge" in data:
        draft.selected_knowledge_json = data["selectedKnowledge"]
        flag_modified(draft, "selected_knowledge_json")
    if "knowledgeRefs" in data:
        draft.knowledge_refs_json = data["knowledgeRefs"]
        flag_modified(draft, "knowledge_refs_json")
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
def create_outline_job(draft_id: str, db: Session = Depends(get_db)) -> WriterJobOut:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")

    job = WriterJob(draft_id=draft_id, kind="outline", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    run_outline_generate_task.delay(job.id)

    return _job_to_out(job)


@router.get("/writer-jobs/{job_id}", response_model=WriterJobOut)
def get_writer_job_status(job_id: str, db: Session = Depends(get_db)) -> WriterJobOut:
    job = db.get(WriterJob, job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return _job_to_out(job)


@router.post(
    "/writer-drafts/{draft_id}/chapters/{chapter_id}/generate-jobs", response_model=WriterJobOut
)
def create_chapter_generate_job(
    draft_id: str, chapter_id: str, db: Session = Depends(get_db)
) -> WriterJobOut:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")

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
    draft_id: str, chapter_id: str, payload: SaveChapterContentIn, db: Session = Depends(get_db)
) -> WriterDraftOut:
    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise HTTPException(404, "撰写草稿不存在")

    contents = dict(draft.chapter_contents_json or {})
    contents[chapter_id] = payload.content
    draft.chapter_contents_json = contents
    flag_modified(draft, "chapter_contents_json")

    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.get("/tender-documents/{tender_document_id}/paragraphs", response_model=list[TenderParagraphOut])
def get_tender_document_paragraphs(
    tender_document_id: str, db: Session = Depends(get_db)
) -> list[TenderParagraphOut]:
    doc = db.get(TenderDocument, tender_document_id)
    if not doc:
        raise HTTPException(404, "招标文件不存在")

    paragraphs = extract_paragraphs(doc.storage_path)
    return [
        TenderParagraphOut(index=p["index"], text=p["text"], style=p["style"], outlineLevel=p["outline_level"])
        for p in paragraphs
    ]
