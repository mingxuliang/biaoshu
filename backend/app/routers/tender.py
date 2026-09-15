from datetime import datetime
import io
import os
import urllib.parse
import zipfile

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
from ..engines.tender_package import (
    ALLOWED_EXTS,
    BLOCKED_EXTS,
    IMAGE_EXTS,
    effective_kind,
    normalize_kind,
    package_slots,
)
from ..models import EvaluationChecklist, Project, ProjectCustomRule, TenderDocument, User
from ..permissions import PERM_PROJECT_EDIT, PERM_REVIEW, PERM_WRITER, require_any_perm, require_project
from ..schemas import (
    ChecklistOut,
    CreateTenderParseJobIn,
    CustomRuleIn,
    CustomRuleOut,
    TenderParseJobOut,
    TenderUploadOut,
    UpdateCustomRuleIn,
)
from ..tasks import run_tender_parse_task
from .. import storage

router = APIRouter(prefix="/api", tags=["tender"])


def _project_tender_docs(db: Session, project_id: str) -> list[TenderDocument]:
    return (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == project_id)
        .order_by(TenderDocument.uploaded_at.desc())
        .all()
    )


def _checklist_to_out(checklist: EvaluationChecklist, db: Session) -> ChecklistOut:
    data = checklist.checklist_json or {}
    project = db.get(Project, checklist.project_id)
    category = (project.category if project else None) or "软件服务类"
    pkg = data.get("package")
    if not pkg:
        pkg = package_slots(_project_tender_docs(db, checklist.project_id))
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
        dimensions=merge_tree(data.get("dimensions"), category),
        vetoParams=checklist.engine_params_json or {},
        package=pkg,
        error=checklist.error,
    )


def _validate_upload(ext: str, content: bytes) -> None:
    if ext == ".docx":
        try:
            docx.Document(io.BytesIO(content))
        except Exception as exc:
            raise HTTPException(400, "Word 文档已损坏或无法解析，请重新上传") from exc
        return
    if ext == ".pdf":
        import pymupdf as fitz

        try:
            with fitz.open(stream=content, filetype="pdf") as doc:
                if doc.page_count < 1:
                    raise ValueError("空文档")
        except Exception as exc:
            raise HTTPException(400, "PDF 文件已损坏或无法解析，请重新上传") from exc
        return
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                if "xl/workbook.xml" not in zf.namelist():
                    raise ValueError("不是有效的 Excel 工作簿")
        except Exception as exc:
            raise HTTPException(400, "Excel 文件已损坏或无法解析，请重新上传") from exc
        return
    if ext == ".xls":
        if len(content) < 8:
            raise HTTPException(400, "Excel 文件已损坏或无法解析，请重新上传")
        return
    if ext in IMAGE_EXTS:
        if len(content) < 24:
            raise HTTPException(400, "图片文件已损坏，请重新上传")
        return
    if ext in {".txt", ".csv", ".md", ".html", ".htm"}:
        if len(content) < 4:
            raise HTTPException(400, "文本文件过小或已损坏，请重新上传")
        return
    if ext == ".pptx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                if not any(n.startswith("ppt/slides/") for n in zf.namelist()):
                    raise ValueError("不是有效的 PPTX")
        except Exception as exc:
            raise HTTPException(400, "PPT 文件已损坏或无法解析，请重新上传") from exc
        return
    if ext in {".zip", ".rar", ".7z", ".ppt", ".doc"}:
        if len(content) < 8:
            raise HTTPException(400, "文件过小或已损坏，请重新上传")
        return
    raise HTTPException(400, "不支持该文件格式")


@router.post("/tender-documents", response_model=TenderUploadOut)
async def upload_tender_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    kind: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TenderUploadOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER)
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    resolved_kind = normalize_kind(kind, filename)

    if ext in BLOCKED_EXTS:
        raise HTTPException(400, "不支持可执行或脚本文件")
    if resolved_kind == "quote":
        if not ext:
            raise HTTPException(400, "其他材料需要带文件扩展名")
    elif ext == ".doc":
        raise HTTPException(400, "暂不支持旧版 .doc 格式，请在 Word 中另存为 .docx 后重新上传")
    elif ext not in ALLOWED_EXTS:
        raise HTTPException(400, "支持 Word、PDF、Excel 与常见图片格式（.docx / .pdf / .xlsx / .png / .jpg 等）")

    content = await file.read()
    if resolved_kind == "quote":
        if len(content) < 8:
            raise HTTPException(400, "文件过小或已损坏，请重新上传")
        if ext in ALLOWED_EXTS and ext not in {".zip", ".rar", ".7z", ".ppt", ".doc"}:
            _validate_upload(ext, content)
    else:
        _validate_upload(ext, content)

    key = storage.put_bytes(f"tender/{project_id}", content, ext)
    doc = TenderDocument(
        project_id=project_id,
        filename=filename,
        storage_path=key,
        size_bytes=len(content),
        kind=resolved_kind,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return TenderUploadOut(id=doc.id, filename=doc.filename, size_bytes=doc.size_bytes, kind=doc.kind)


@router.get("/tender-documents/{doc_id}/download")
def download_tender_document(
    doc_id: str,
    inline: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    doc = db.get(TenderDocument, doc_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "文件不存在")
    require_project(db, current_user, doc.project_id)
    try:
        return storage.http_response(doc.storage_path, filename=doc.filename, inline=inline)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")


@router.get("/tender-documents/{doc_id}/preview-meta")
def tender_preview_meta(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    doc = db.get(TenderDocument, doc_id)
    if not doc:
        raise HTTPException(404, "文件不存在")
    require_project(db, current_user, doc.project_id)
    ext = os.path.splitext(doc.filename or "")[1].lower()
    if ext != ".pdf":
        return {"pageCount": 0, "kind": "other", "filename": doc.filename}
    try:
        import pymupdf as fitz

        with storage.as_local(doc.storage_path) as path:
            with fitz.open(path) as pdf:
                return {"pageCount": int(pdf.page_count or 0), "kind": "pdf", "filename": doc.filename}
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在") from None


@router.get("/tender-documents/{doc_id}/preview-page")
def tender_preview_page(
    doc_id: str,
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """把 PDF 单页渲染成 PNG，供页面内 <img> 预览，避免浏览器把 PDF 当成附件下载。"""
    doc = db.get(TenderDocument, doc_id)
    if not doc:
        raise HTTPException(404, "文件不存在")
    require_project(db, current_user, doc.project_id)
    ext = os.path.splitext(doc.filename or "")[1].lower()
    if ext != ".pdf":
        raise HTTPException(400, "仅 PDF 支持分页预览")
    try:
        import pymupdf as fitz

        with storage.as_local(doc.storage_path) as path:
            with fitz.open(path) as pdf:
                total = int(pdf.page_count or 0)
                if total < 1:
                    raise HTTPException(400, "PDF 没有页面")
                index = max(1, min(page, total)) - 1
                pix = pdf[index].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                png = pix.tobytes("png")
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在") from None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "PDF 预览失败") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline; filename=preview.png",
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/tender-documents/{doc_id}")
def delete_tender_document(
    doc_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    doc = db.get(TenderDocument, doc_id)
    if not doc:
        raise HTTPException(404, "文件不存在")
    require_project(db, current_user, doc.project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER)
    referenced = (
        db.query(EvaluationChecklist.id)
        .filter(EvaluationChecklist.tender_document_id == doc_id)
        .first()
    )
    if referenced:
        raise HTTPException(400, "该文件已被解析任务引用，无法删除")
    try:
        storage.delete(doc.storage_path)
    except Exception:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True}


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

    requested = [str(x) for x in (payload.tender_document_ids or []) if x]
    if payload.tender_document_id:
        requested = [payload.tender_document_id] + [i for i in requested if i != payload.tender_document_id]

    project_docs = _project_tender_docs(db, project_id)
    if requested:
        by_id = {d.id: d for d in project_docs}
        docs = [by_id[i] for i in requested if i in by_id]
        missing = [i for i in requested if i not in by_id]
        if missing:
            extra = db.query(TenderDocument).filter(TenderDocument.id.in_(missing)).all()
            for d in extra:
                if d.project_id != project_id:
                    raise HTTPException(400, f"文件不属于当前项目：{d.filename}")
                docs.append(d)
            still = [i for i in missing if i not in {d.id for d in docs}]
            if still:
                raise HTTPException(404, "招标文件不存在，请重新上传")
    else:
        docs = project_docs

    if not docs:
        raise HTTPException(400, "请先上传招标文件包中的至少一份文件")

    primary = next((d for d in docs if effective_kind(d.kind, d.filename) == "main"), docs[0])

    last_version = (
        db.query(func.max(EvaluationChecklist.version))
        .filter(EvaluationChecklist.project_id == project_id)
        .scalar()
    ) or 0

    checklist = EvaluationChecklist(
        project_id=project_id,
        tender_document_id=primary.id,
        version=last_version + 1,
        status="queued",
        checklist_json={"packageDocIds": [d.id for d in docs], "package": package_slots(docs)},
    )
    db.add(checklist)
    names = "、".join(d.filename for d in docs[:6])
    if len(docs) > 6:
        names += f" 等 {len(docs)} 份"
    write_audit(
        db,
        action="解析",
        user_name=actor_from_request(db, request),
        target=f"{project_label(db, project_id)} / {names}",
        version=f"v{checklist.version}",
        detail=f"发起招标文件包解析（{len(docs)} 份）",
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
    return _checklist_to_out(checklist, db)


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

    return _checklist_to_out(checklist, db)


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
        category=(project.category if project else None) or "软件服务类",
    )
    encoded_name = urllib.parse.quote(f"{(project.code if project else 'parse')}-解析报告-v{checklist.version}.docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"parse-report.docx\"; filename*=UTF-8''{encoded_name}"
        },
    )


_CUSTOM_SOURCES = {"tender", "drawing", "mixed"}
_CUSTOM_SEVERITIES = {"废标", "降档", "扣分", "建议"}
_CUSTOM_SLOTS = {"main", "addendum", "boq", "quote", "drawing"}


def _custom_rule_out(row: ProjectCustomRule) -> CustomRuleOut:
    sources = [s for s in (row.sources_json or []) if s in _CUSTOM_SLOTS]
    return CustomRuleOut(
        id=row.id,
        projectId=row.project_id,
        source=row.source if row.source in _CUSTOM_SOURCES else "tender",
        sources=sources,
        title=row.title or "",
        content=row.content or "",
        severity=row.severity if row.severity in _CUSTOM_SEVERITIES else "扣分",
        enabled=bool(row.enabled),
        createdAt=row.created_at.isoformat() if row.created_at else "",
    )


def _clean_custom_content(text: str) -> str:
    return (text or "").strip()


def _clean_custom_sources(source: str, sources: list | None) -> list[str]:
    if source != "mixed":
        return []
    return [s for s in (sources or []) if s in _CUSTOM_SLOTS]


@router.get("/projects/{project_id}/custom-rules", response_model=list[CustomRuleOut])
def list_custom_rules(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CustomRuleOut]:
    require_project(db, current_user, project_id)
    rows = (
        db.query(ProjectCustomRule)
        .filter(ProjectCustomRule.project_id == project_id)
        .order_by(ProjectCustomRule.created_at.desc())
        .all()
    )
    return [_custom_rule_out(r) for r in rows]


@router.post("/projects/{project_id}/custom-rules", response_model=CustomRuleOut)
def create_custom_rule(
    project_id: str,
    payload: CustomRuleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomRuleOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER, PERM_REVIEW)
    content = _clean_custom_content(payload.content)
    if len(content) < 2:
        raise HTTPException(400, "请填写规则内容")
    if len(content) > 4000:
        raise HTTPException(400, "规则内容请控制在 4000 字以内")
    title = (payload.title or "").strip()[:80]
    row = ProjectCustomRule(
        project_id=project_id,
        source=payload.source,
        sources_json=_clean_custom_sources(payload.source, payload.sources),
        title=title,
        content=content,
        severity=payload.severity,
        enabled=payload.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _custom_rule_out(row)


@router.patch("/projects/{project_id}/custom-rules/{rule_id}", response_model=CustomRuleOut)
def update_custom_rule(
    project_id: str,
    rule_id: str,
    payload: UpdateCustomRuleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomRuleOut:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER, PERM_REVIEW)
    row = db.get(ProjectCustomRule, rule_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "自定义规则不存在")
    data = payload.model_dump(exclude_unset=True)
    if "content" in data:
        content = _clean_custom_content(data["content"])
        if len(content) < 2:
            raise HTTPException(400, "请填写规则内容")
        if len(content) > 4000:
            raise HTTPException(400, "规则内容请控制在 4000 字以内")
        row.content = content
    if "title" in data:
        row.title = (data["title"] or "").strip()[:80]
    if "source" in data:
        row.source = data["source"]
    if "sources" in data or "source" in data:
        row.sources_json = _clean_custom_sources(row.source, data.get("sources", row.sources_json))
    if "severity" in data:
        row.severity = data["severity"]
    if "enabled" in data:
        row.enabled = bool(data["enabled"])
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _custom_rule_out(row)


@router.delete("/projects/{project_id}/custom-rules/{rule_id}")
def delete_custom_rule(
    project_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_project(db, current_user, project_id)
    require_any_perm(current_user, PERM_PROJECT_EDIT, PERM_WRITER, PERM_REVIEW)
    row = db.get(ProjectCustomRule, rule_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "自定义规则不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
