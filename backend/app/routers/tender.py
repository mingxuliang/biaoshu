import os
import uuid

import docx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import EvaluationChecklist, TenderDocument
from ..schemas import (
    ChecklistOut,
    CreateTenderParseJobIn,
    TenderParseJobOut,
    TenderUploadOut,
)
from ..tasks import run_tender_parse_task

router = APIRouter(prefix="/api", tags=["tender"])


def _checklist_to_out(checklist: EvaluationChecklist) -> ChecklistOut:
    data = checklist.checklist_json or {}
    return ChecklistOut(
        id=checklist.id,
        project_id=checklist.project_id,
        tender_document_id=checklist.tender_document_id,
        version=checklist.version,
        status=checklist.status,
        locked=checklist.locked,
        scoreRules=data.get("scoreRules", []),
        mustRespond=data.get("mustRespond", []),
        qualification=data.get("qualification", []),
        formatRequirements=data.get("formatRequirements", []),
        vetoParams=checklist.engine_params_json or {},
        error=checklist.error,
    )


@router.post("/tender-documents", response_model=TenderUploadOut)
async def upload_tender_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TenderUploadOut:
    settings = get_settings()
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".doc":
        raise HTTPException(400, "暂不支持旧版 .doc 格式，请在 Word 中另存为 .docx 后重新上传")
    if ext != ".docx":
        raise HTTPException(400, "仅支持 .docx 格式的招标文件，如为 PDF 请先转换为 Word 格式")

    os.makedirs(settings.upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = os.path.join(settings.upload_dir, stored_name)

    content = await file.read()
    with open(storage_path, "wb") as f:
        f.write(content)

    try:
        docx.Document(storage_path)
    except Exception as exc:
        os.remove(storage_path)
        raise HTTPException(400, "文档已损坏或无法解析，请重新上传") from exc

    doc = TenderDocument(
        project_id=project_id,
        filename=filename,
        storage_path=storage_path,
        size_bytes=len(content),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return TenderUploadOut(id=doc.id, filename=doc.filename, size_bytes=doc.size_bytes)


@router.post("/projects/{project_id}/tender-parse-jobs", response_model=TenderParseJobOut)
def create_tender_parse_job(
    project_id: str, payload: CreateTenderParseJobIn, db: Session = Depends(get_db)
) -> TenderParseJobOut:
    tender_doc = db.get(TenderDocument, payload.tender_document_id)
    if not tender_doc:
        raise HTTPException(404, "招标文件不存在，请重新上传")

    last_version = (
        db.query(func.max(EvaluationChecklist.version))
        .filter(EvaluationChecklist.project_id == project_id)
        .scalar()
    ) or 0

    checklist = EvaluationChecklist(
        project_id=project_id,
        tender_document_id=tender_doc.id,
        version=last_version + 1,
        status="queued",
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)

    run_tender_parse_task.delay(checklist.id)

    return TenderParseJobOut(job_id=checklist.id, status=checklist.status, version=checklist.version)


@router.get("/tender-parse-jobs/{job_id}", response_model=TenderParseJobOut)
def get_tender_parse_job_status(job_id: str, db: Session = Depends(get_db)) -> TenderParseJobOut:
    checklist = db.get(EvaluationChecklist, job_id)
    if not checklist:
        raise HTTPException(404, "任务不存在")
    return TenderParseJobOut(
        job_id=checklist.id, status=checklist.status, version=checklist.version, error=checklist.error
    )


@router.get("/projects/{project_id}/checklist/latest", response_model=ChecklistOut)
def get_latest_checklist(project_id: str, db: Session = Depends(get_db)) -> ChecklistOut:
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    if not checklist:
        raise HTTPException(404, "该项目暂无解析记录，请先上传招标文件并发起解析")
    return _checklist_to_out(checklist)


@router.post("/projects/{project_id}/checklist/{checklist_id}/lock", response_model=ChecklistOut)
def lock_checklist(project_id: str, checklist_id: str, db: Session = Depends(get_db)) -> ChecklistOut:
    checklist = db.get(EvaluationChecklist, checklist_id)
    if not checklist or checklist.project_id != project_id:
        raise HTTPException(404, "评标尺子不存在")
    if checklist.status != "done":
        raise HTTPException(400, "解析尚未完成，暂不能锁定")

    others = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id, EvaluationChecklist.id != checklist.id)
        .all()
    )
    for other in others:
        other.locked = False
    checklist.locked = True
    db.commit()
    db.refresh(checklist)

    return _checklist_to_out(checklist)
