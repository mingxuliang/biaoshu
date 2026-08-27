import hashlib
import io

import docx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..audit import project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines import export_check, rules_config
from ..models import BidDocument, BidRevision, BidRevisionVersion, ExportRecord, User
from ..permissions import PERM_EXPORT, require_project
from ..schemas import CreateExportIn, ExportChecksOut, ExportRecordOut
from .. import storage

router = APIRouter(prefix="/api", tags=["export"])


def _latest_version(db: Session, project_id: str) -> tuple[BidRevision, BidRevisionVersion]:
    revision = db.query(BidRevision).filter(BidRevision.project_id == project_id).first()
    if not revision:
        raise HTTPException(400, "该项目暂无修改闭环草稿，请先在「修改闭环」完成一次保存")

    version = (
        db.query(BidRevisionVersion)
        .filter(BidRevisionVersion.revision_id == revision.id, BidRevisionVersion.bid_document_id.isnot(None))
        .order_by(BidRevisionVersion.created_at.desc())
        .first()
    )
    if not version:
        raise HTTPException(400, "该项目暂无已保存的版本，请先在「修改闭环」完成一次保存")
    return revision, version


def _run_checks_for(db: Session, project_id: str, mode: str) -> tuple[BidRevision, BidRevisionVersion, list, bool, str]:
    revision, version = _latest_version(db, project_id)
    doc = db.get(BidDocument, version.bid_document_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "该版本对应的文件不存在")

    checklist_params, must_respond = rules_config.load_locked_checklist(db, project_id)
    with storage.as_local(doc.storage_path) as path:
        findings = export_check.run_checks(db, path, checklist_params, must_respond, project_id)
        items, blocked, block_reason = export_check.summarize(findings, path, mode)
    return revision, version, items, blocked, block_reason


@router.get("/projects/{project_id}/export-checks", response_model=ExportChecksOut)
def get_export_checks(
    project_id: str,
    mode: str = "明标",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExportChecksOut:
    require_project(db, current_user, project_id, PERM_EXPORT)
    if mode not in ("明标", "暗标"):
        mode = "明标"
    revision, version, items, blocked, block_reason = _run_checks_for(db, project_id, mode)
    return ExportChecksOut(
        revisionId=revision.id,
        versionLabel=version.label,
        wordCount=version.word_count,
        updatedAt=version.created_at.isoformat(),
        items=items,
        blocked=blocked,
        blockReason=block_reason,
    )


def _record_to_out(record: ExportRecord, filename: str) -> ExportRecordOut:
    return ExportRecordOut(
        id=record.id,
        projectId=record.project_id,
        mode=record.mode,
        operator=record.operator,
        checkStatus=record.check_status,
        checkNote=record.check_note,
        fileSize=record.file_size,
        fileHash=record.file_hash,
        filename=filename,
        createdAt=record.created_at.isoformat(),
    )


@router.post("/projects/{project_id}/exports", response_model=ExportRecordOut)
def create_export(
    project_id: str,
    payload: CreateExportIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExportRecordOut:
    require_project(db, current_user, project_id, PERM_EXPORT)
    mode = payload.mode
    revision, version, items, blocked, block_reason = _run_checks_for(db, project_id, mode)

    check_note = block_reason or "；".join(i["note"] for i in items if not i["ok"] and i["note"])

    if blocked:
        record = ExportRecord(
            project_id=project_id,
            revision_id=revision.id,
            bid_document_id=version.bid_document_id,
            mode=mode,
            operator=current_user.name,
            check_status="阻断",
            check_note=check_note or "存在废标级问题，已阻断导出",
            file_size=0,
            file_hash="",
        )
        db.add(record)
        write_audit(
            db,
            action="导出",
            user_name=current_user.name,
            target=project_label(db, project_id),
            version=version.label,
            result="阻断",
            detail=f"{mode}导出被阻断：{check_note or '存在废标级问题'}",
        )
        db.commit()
        raise HTTPException(400, check_note or "存在废标级问题，已阻断导出，请返回「修改闭环」处理后重试")

    source_doc = db.get(BidDocument, version.bid_document_id)
    if not source_doc or not storage.exists(source_doc.storage_path):
        raise HTTPException(404, "导出文件不存在")

    if mode == "暗标":
        with storage.as_local(source_doc.storage_path) as path:
            anon_document = docx.Document(path)
            props = anon_document.core_properties
            props.author = ""
            props.last_modified_by = ""
            props.title = ""
            props.subject = ""
            props.keywords = ""
            props.comments = ""
            buf = io.BytesIO()
            anon_document.save(buf)
            content = buf.getvalue()

        key = storage.put_bytes(f"export/{project_id}", content, ".docx")
        export_doc = BidDocument(
            project_id=project_id,
            filename="投标书-暗标脱敏版.docx",
            storage_path=key,
            size_bytes=len(content),
            source="export-anon",
        )
        db.add(export_doc)
        db.flush()
        bid_document_id = export_doc.id
    else:
        try:
            content = storage.get_bytes(source_doc.storage_path)
        except FileNotFoundError:
            raise HTTPException(404, "导出文件不存在")
        bid_document_id = source_doc.id

    file_hash = hashlib.sha256(content).hexdigest()

    record = ExportRecord(
        project_id=project_id,
        revision_id=revision.id,
        bid_document_id=bid_document_id,
        mode=mode,
        operator=current_user.name,
        check_status="通过",
        check_note=check_note,
        file_size=len(content),
        file_hash=file_hash,
    )
    db.add(record)
    write_audit(
        db,
        action="导出",
        user_name=current_user.name,
        target=project_label(db, project_id),
        version=version.label,
        result="成功",
        detail=f"{mode}导出，校验通过，哈希 {file_hash[:4].upper()}…{file_hash[-4:].upper()}",
    )
    db.commit()
    db.refresh(record)

    exported_doc = db.get(BidDocument, bid_document_id)
    return _record_to_out(record, exported_doc.filename if exported_doc else "")


@router.get("/projects/{project_id}/export-records", response_model=list[ExportRecordOut])
def list_export_records(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExportRecordOut]:
    require_project(db, current_user, project_id, PERM_EXPORT)
    records = (
        db.query(ExportRecord)
        .filter(ExportRecord.project_id == project_id)
        .order_by(ExportRecord.created_at.desc())
        .all()
    )
    out = []
    for r in records:
        doc = db.get(BidDocument, r.bid_document_id)
        out.append(_record_to_out(r, doc.filename if doc else ""))
    return out


@router.get("/export-records/{record_id}/download")
def download_export_record(
    record_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    record = db.get(ExportRecord, record_id)
    if not record:
        raise HTTPException(404, "导出记录不存在")
    require_project(db, current_user, record.project_id, PERM_EXPORT)

    doc = db.get(BidDocument, record.bid_document_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "导出文件不存在")
    try:
        return storage.http_response(doc.storage_path, filename=doc.filename)
    except FileNotFoundError:
        raise HTTPException(404, "导出文件不存在")
