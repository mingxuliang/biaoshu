import hashlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..audit import project_label, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines import export_check, rules_config
from ..engines.bid_kind import SCOPE_BUSINESS, SCOPE_TECH
from ..engines.category_profile import (
    MODE_BLIND,
    MODE_CLEAR,
    category_key,
    category_label,
    default_export_mode,
    effective_export_mode,
    tender_requires_anonymity,
)
from ..engines.export_anon import anonymize_docx, residual_identity
from ..models import (
    BidDocument,
    BidRevision,
    BidRevisionVersion,
    ExportRecord,
    Project,
    QualificationAsset,
    User,
)
from ..permissions import PERM_EXPORT, require_project
from ..schemas import CreateExportIn, ExportChecksOut, ExportRecordOut
from .. import storage

router = APIRouter(prefix="/api", tags=["export"])

_SCOPE_LABEL = {SCOPE_BUSINESS: "商务标", SCOPE_TECH: "技术标"}
EXPORT_SOURCE = "export"


def _norm_scope(scope: str | None) -> str:
    """导出只有商务册、技术册两册；缺省或不认识的值按商务册。"""
    return scope if scope in (SCOPE_BUSINESS, SCOPE_TECH) else SCOPE_BUSINESS


def _latest_version(db: Session, project_id: str, scope: str) -> tuple[BidRevision, BidRevisionVersion]:
    label = _SCOPE_LABEL[scope]
    revision = (
        db.query(BidRevision)
        .filter(BidRevision.project_id == project_id, BidRevision.scope == scope)
        .first()
    )
    if not revision:
        raise HTTPException(400, f"该项目暂无{label}的修改闭环草稿，请先在「修改闭环」选择{label}并完成一次保存")

    version = (
        db.query(BidRevisionVersion)
        .filter(BidRevisionVersion.revision_id == revision.id, BidRevisionVersion.bid_document_id.isnot(None))
        .order_by(BidRevisionVersion.created_at.desc())
        .first()
    )
    if not version:
        raise HTTPException(400, f"该项目暂无已保存的{label}版本，请先在「修改闭环」完成一次保存")
    return revision, version


def _bidder_names(db: Session) -> list[str]:
    """本企业名称：取已入库营业执照的持有人。暗标时用来清页眉页脚里的单位名。"""
    names: list[str] = []
    rows = db.query(QualificationAsset).filter(QualificationAsset.review_status == "已入库").all()
    for row in rows:
        if (row.kind or "") == "cert" and "营业执照" in (row.name or ""):
            owner = (row.owner or "").strip()
            if len(owner) >= 4 and owner not in names:
                names.append(owner)
    return names


class _CheckResult:
    def __init__(self, revision, version, items, blocked, block_reason, scope, category, mode, checklist_params):
        self.revision = revision
        self.version = version
        self.items = items
        self.blocked = blocked
        self.block_reason = block_reason
        self.scope = scope
        self.category = category
        self.mode = mode
        self.checklist_params = checklist_params or {}


def _run_checks_for(db: Session, project_id: str, scope: str, requested_mode: str | None) -> _CheckResult:
    revision, version = _latest_version(db, project_id, scope)
    doc = db.get(BidDocument, version.bid_document_id)
    if not doc or not storage.exists(doc.storage_path):
        raise HTTPException(404, "该版本对应的文件不存在")

    project = db.get(Project, project_id)
    category = category_key(project.category if project else None)
    checklist_params, must_respond = rules_config.load_locked_checklist(db, project_id)
    mode = effective_export_mode(scope, requested_mode, checklist_params)
    with storage.as_local(doc.storage_path) as path:
        findings = export_check.run_checks(
            db,
            path,
            checklist_params,
            must_respond,
            project_id,
            scope=scope,
            category=category,
            mode=mode,
            doc_kind=doc.kind,
            filename=doc.filename,
        )
        items, blocked, block_reason = export_check.summarize(findings, path, mode, scope, checklist_params)
    return _CheckResult(revision, version, items, blocked, block_reason, scope, category, mode, checklist_params)


@router.get("/projects/{project_id}/export-checks", response_model=ExportChecksOut)
def get_export_checks(
    project_id: str,
    scope: str = SCOPE_BUSINESS,
    mode: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExportChecksOut:
    require_project(db, current_user, project_id, PERM_EXPORT)
    booklet = _norm_scope(scope)
    requested = mode if mode in (MODE_CLEAR, MODE_BLIND) else None
    result = _run_checks_for(db, project_id, booklet, requested)
    return ExportChecksOut(
        revisionId=result.revision.id,
        versionLabel=result.version.label,
        wordCount=result.version.word_count,
        updatedAt=result.version.created_at.isoformat(),
        items=result.items,
        blocked=result.blocked,
        blockReason=result.block_reason,
        scope=booklet,
        category=result.category,
        categoryLabel=category_label(result.category),
        mode=result.mode,
        defaultMode=default_export_mode(booklet, result.checklist_params),
        anonymityRequired=tender_requires_anonymity(result.checklist_params),
        blindAllowed=booklet == SCOPE_TECH,
        checklistLocked=rules_config.checklist_locked(db, project_id),
    )


def _record_to_out(record: ExportRecord, filename: str) -> ExportRecordOut:
    return ExportRecordOut(
        id=record.id,
        projectId=record.project_id,
        scope=record.scope or "",
        category=record.category or "",
        mode=record.mode,
        operator=record.operator,
        checkStatus=record.check_status,
        checkNote=record.check_note,
        fileSize=record.file_size,
        fileHash=record.file_hash,
        filename=filename,
        createdAt=record.created_at.isoformat(),
    )


def _export_filename(project_name: str, scope: str, mode: str) -> str:
    base = (project_name or "投标文件").strip() or "投标文件"
    for ch in '\\/:*?"<>|':
        base = base.replace(ch, "_")
    return f"{base}-{_SCOPE_LABEL[scope]}-{mode}.docx"


@router.post("/projects/{project_id}/exports", response_model=ExportRecordOut)
def create_export(
    project_id: str,
    payload: CreateExportIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExportRecordOut:
    require_project(db, current_user, project_id, PERM_EXPORT)
    scope = _norm_scope(payload.scope)
    if scope != SCOPE_TECH and payload.mode == MODE_BLIND:
        raise HTTPException(400, "暗标只适用于技术标，商务标请按明标导出")
    result = _run_checks_for(db, project_id, scope, payload.mode)
    mode = result.mode
    revision, version = result.revision, result.version
    project = db.get(Project, project_id)
    project_name = project.name if project else ""

    check_note = result.block_reason or "；".join(i["note"] for i in result.items if not i["ok"] and i["note"])

    def _record(status: str, note: str, bid_document_id: str, size: int, digest: str) -> ExportRecord:
        return ExportRecord(
            project_id=project_id,
            revision_id=revision.id,
            bid_document_id=bid_document_id,
            mode=mode,
            scope=scope,
            category=result.category,
            operator=current_user.name,
            check_status=status,
            check_note=note,
            file_size=size,
            file_hash=digest,
        )

    if result.blocked:
        db.add(
            _record(
                "阻断",
                check_note or "存在废标级问题，已阻断导出",
                version.bid_document_id,
                0,
                "",
            )
        )
        write_audit(
            db,
            action="导出",
            user_name=current_user.name,
            target=project_label(db, project_id),
            version=version.label,
            result="阻断",
            detail=f"{_SCOPE_LABEL[scope]}{mode}导出被阻断：{check_note or '存在废标级问题'}",
        )
        db.commit()
        raise HTTPException(400, check_note or "存在废标级问题，已阻断导出，请返回「修改闭环」处理后重试")

    source_doc = db.get(BidDocument, version.bid_document_id)
    if not source_doc or not storage.exists(source_doc.storage_path):
        raise HTTPException(404, "导出文件不存在")
    try:
        content = storage.get_bytes(source_doc.storage_path)
    except FileNotFoundError:
        raise HTTPException(404, "导出文件不存在")

    if mode == MODE_BLIND:
        names = _bidder_names(db)
        try:
            content = anonymize_docx(content, names)
        except Exception as exc:  # noqa: BLE001 —— 坏 docx 不能当成已脱敏
            raise HTTPException(400, f"暗标脱敏失败：{exc}") from exc
        residual = residual_identity(content, names)
        if residual:
            note = "暗标脱敏后仍有残留：" + "、".join(residual)
            db.add(_record("阻断", note, version.bid_document_id, 0, ""))
            write_audit(
                db,
                action="导出",
                user_name=current_user.name,
                target=project_label(db, project_id),
                version=version.label,
                result="阻断",
                detail=f"{_SCOPE_LABEL[scope]}{mode}导出被阻断：{note}",
            )
            db.commit()
            raise HTTPException(400, note)

    key = storage.put_bytes(f"export/{project_id}", content, ".docx")
    export_doc = BidDocument(
        project_id=project_id,
        filename=_export_filename(project_name, scope, mode),
        storage_path=key,
        size_bytes=len(content),
        source=f"{EXPORT_SOURCE}-anon" if mode == MODE_BLIND else EXPORT_SOURCE,
        kind=scope,
    )
    db.add(export_doc)
    db.flush()

    file_hash = hashlib.sha256(content).hexdigest()
    record = _record("通过", check_note, export_doc.id, len(content), file_hash)
    db.add(record)
    write_audit(
        db,
        action="导出",
        user_name=current_user.name,
        target=project_label(db, project_id),
        version=version.label,
        result="成功",
        detail=f"{_SCOPE_LABEL[scope]}{mode}导出，校验通过，哈希 {file_hash[:4].upper()}…{file_hash[-4:].upper()}",
    )
    db.commit()
    db.refresh(record)
    return _record_to_out(record, export_doc.filename)


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
