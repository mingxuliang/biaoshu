import io
import os
import urllib.parse

import docx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import actor_from_request, project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines.parse_export import checklist_to_docx
from ..engines.parse_schema import merge_tree
from ..models import EvaluationChecklist, Project, TenderDocument, User
from ..permissions import PERM_PROJECT_EDIT, PERM_WRITER, require_any_perm, require_project
from ..schemas import (
    ChecklistOut,
    CreateTenderParseJobIn,
    TenderParseJobOut,
    TenderUploadOut,
)
from ..tasks import run_tender_parse_task
from .. import storage

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
        dimensions=merge_tree(data.get("dimensions")),
        vetoParams=checklist.engine_params_json or {},
        error=checklist.error,
    )


@router.post("/tender-documents", response_model=TenderUploadOut)
async def upload_tender_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenderUploadOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER)
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".doc":
        raise HTTPException(400, "暂不支持旧版 .doc 格式，请在 Word 中另存为 .docx 后重新上传")
    if ext != ".docx":
        raise HTTPException(400, "仅支持 .docx 格式的招标文件，如为 PDF 请先转换为 Word 格式")

    content = await file.read()
    try:
        docx.Document(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(400, "文档已损坏或无法解析，请重新上传") from exc

    key = storage.put_bytes(f"tender/{project_id}", content, ext)
    doc = TenderDocument(
        project_id=project_id,
        filename=filename,
        storage_path=key,
        size_bytes=len(content),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return TenderUploadOut(id=doc.id, filename=doc.filename, size_bytes=doc.size_bytes)


@router.get("/tender-documents/{doc_id}/download")
def download_tender_document(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Response:
    doc = db.get(TenderDocument, doc_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "文件不存在")
    require_project(db, current_user, doc.project_id)
    try:
        return storage.http_response(doc.storage_path, filename=doc.filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")


@router.post("/projects/{project_id}/tender-parse-jobs", response_model=TenderParseJobOut)
def create_tender_parse_job(
    project_id: str,
    payload: CreateTenderParseJobIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenderParseJobOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER)
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
    write_audit(
        db,
        action="解析",
        user_name=actor_from_request(db, request),
        target=f"{project_label(db, project_id)} / {tender_doc.filename}",
        version=f"v{checklist.version}",
        detail="发起招标文件解析",
    )
    db.commit()
    db.refresh(checklist)

    run_tender_parse_task.delay(checklist.id)

    return TenderParseJobOut(job_id=checklist.id, status=checklist.status, version=checklist.version)


@router.get("/tender-parse-jobs/{job_id}", response_model=TenderParseJobOut)
def get_tender_parse_job_status(
    job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> TenderParseJobOut:
    checklist = db.get(EvaluationChecklist, job_id)
    if not checklist:
        raise HTTPException(404, "任务不存在")
    require_project(db, current_user, checklist.project_id)
    return TenderParseJobOut(
        job_id=checklist.id, status=checklist.status, version=checklist.version, error=checklist.error
    )


@router.get("/projects/{project_id}/checklist/latest", response_model=ChecklistOut)
def get_latest_checklist(
    project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ChecklistOut:
    require_project(db, current_user, project_id)
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
def lock_checklist(
    project_id: str,
    checklist_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChecklistOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER)
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
    data = checklist.checklist_json or {}
    n_rules = len(data.get("scoreRules") or [])
    n_must = len(data.get("mustRespond") or [])
    write_audit(
        db,
        action="确认对标",
        user_name=actor_from_request(db, request),
        target=f"{project_label(db, project_id)} 对标清单",
        version=f"v{checklist.version}",
        detail=f"锁定 {n_rules} 条评分规则、{n_must} 条必响应条款",
    )
    db.commit()
    db.refresh(checklist)

    return _checklist_to_out(checklist)


@router.get("/projects/{project_id}/checklist/{checklist_id}/export")
def export_checklist_report(
    project_id: str,
    checklist_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_project(db, current_user, project_id)
    checklist = db.get(EvaluationChecklist, checklist_id)
    if not checklist or checklist.project_id != project_id:
        raise HTTPException(404, "评标尺子不存在")
    if checklist.status != "done":
        raise HTTPException(400, "解析尚未完成，暂不能导出报告")

    project = db.get(Project, project_id)
    docx_bytes = checklist_to_docx(
        project_name=project.name if project else "",
        project_code=project.code if project else "",
        version=checklist.version,
        locked=bool(checklist.locked),
        data=checklist.checklist_json or {},
    )
    encoded_name = urllib.parse.quote(f"{(project.code if project else 'parse')}-解析报告-v{checklist.version}.docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"parse-report.docx\"; filename*=UTF-8''{encoded_name}"
        },
    )
