import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from sqlalchemy.orm import Session, joinedload

from ..audit import write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines.ocr import ocr_file
from ..engines.qualification_dedup import VALID_KINDS as DEDUP_KINDS
from ..engines.qualification_dedup import mark_keep_both, merge_assets
from ..models import QualificationAsset, QualificationAssetImage, QualificationSourceDoc, User
from ..permissions import PERM_QUAL_EDIT, require_perm
from ..schemas import (
    QualificationExtractJobOut,
    QualificationImageOut,
    QualificationMergeIn,
    QualificationOut,
    QualificationParseJobOut,
    QualificationResolveIn,
)
from .. import storage

router = APIRouter(prefix="/api", tags=["qualifications"])

VALID_KINDS = set(DEDUP_KINDS)
ALLOWED_SCAN_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_SOURCE_EXTS = {".doc", ".docx", ".pdf"}
MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
WARN_DAYS = 30
STATUS_MAP = {"queued": "解析中", "running": "解析中", "done": "已完成", "failed": "抽取失败"}
MERGE_STATUSES = {"新增", "并入已有", "疑似重复", "信息冲突"}
REVIEW_STATUSES = {"待审核", "已入库"}


def compute_status(valid_until: str) -> tuple[str, int | None]:
    text = (valid_until or "").strip() or "长期"
    if text in ("长期", "长期有效", "—", "-"):
        return "有效", None
    try:
        expire = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return "有效", None
    today = date.today()
    if expire < today:
        return "已过期", None
    days = (expire - today).days
    if days <= WARN_DAYS:
        return "将到期", days
    return "有效", None


def _dt_hm(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def _size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _to_out(item: QualificationAsset) -> QualificationOut:
    status, warn_days = compute_status(item.valid_until or "长期")
    images = [
        QualificationImageOut(
            id=img.id,
            caption=img.caption or "",
            url=f"/api/qualification-images/{img.id}/file",
        )
        for img in (item.images or [])
        if img.storage_path
    ]
    has_file = bool(images) or bool(item.storage_path and storage.exists(item.storage_path))
    updated = item.updated_at or item.created_at
    kind = item.kind if item.kind in VALID_KINDS else "cert"
    review = item.review_status if item.review_status in REVIEW_STATUSES else "已入库"
    merge = item.merge_status if item.merge_status in MERGE_STATUSES else "新增"
    return QualificationOut(
        id=item.id,
        kind=kind,  # type: ignore[arg-type]
        name=item.name,
        level=item.level or "",
        number=item.number or "",
        validUntil=item.valid_until or "长期",
        status=status,  # type: ignore[arg-type]
        warnDays=warn_days,
        owner=item.owner or "",
        detail=item.detail or "",
        filename=item.filename or "",
        hasFile=has_file,
        ocrText=(item.ocr_text or "")[:4000],
        ocrStatus=item.ocr_status or "",
        reviewStatus=review,  # type: ignore[arg-type]
        mergeStatus=merge,  # type: ignore[arg-type]
        aliases=list(item.aliases_json or []),
        sources=list(item.sources_json or []),
        evidence=list(item.evidence_json or []),
        fieldConflict=list(item.field_conflict_json or []),
        suspectedIds=list(item.suspected_ids_json or []),
        images=images,
        updatedAt=updated.date().isoformat() if updated else "",
    )


def _job_to_out(doc: QualificationSourceDoc) -> QualificationParseJobOut:
    return QualificationParseJobOut(
        id=doc.id,
        filename=doc.filename,
        status=STATUS_MAP.get(doc.status, "解析中"),  # type: ignore[arg-type]
        extracted=doc.extracted or 0,
        merged=doc.merged or 0,
        suspected=doc.suspected or 0,
        conflicts=doc.conflicts or 0,
        sizeLabel=_size_label(doc.size_bytes or 0),
        uploadedAt=_dt_hm(doc.created_at),
        note=doc.note or "",
        error=doc.error,
    )


def _save_file(file: UploadFile, content: bytes) -> tuple[str, str]:
    original = file.filename or "scan.bin"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_SCAN_EXTS:
        raise HTTPException(400, "扫描件仅支持 PDF / JPG / PNG / WEBP")
    key = storage.put_bytes("qualifications", content, ext)
    return original, key


def _fill_ocr(item: QualificationAsset, ref: str) -> None:
    if not ref:
        item.ocr_text = ""
        item.ocr_status = ""
        return
    with storage.as_local(ref) as path:
        text, status = ocr_file(path)
    item.ocr_text = text
    item.ocr_status = status


def _require_asset(db: Session, qual_id: str) -> QualificationAsset:
    item = (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .filter(QualificationAsset.id == qual_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "证照不存在")
    return item


@router.get("/qualifications", response_model=list[QualificationOut])
def list_qualifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[QualificationOut]:
    _ = current_user
    items = (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .order_by(QualificationAsset.created_at.desc())
        .all()
    )
    return [_to_out(i) for i in items]


@router.post("/qualifications", response_model=QualificationOut)
async def create_qualification(
    kind: str = Form(...),
    name: str = Form(...),
    level: str = Form(""),
    number: str = Form(""),
    valid_until: str = Form("长期"),
    owner: str = Form(""),
    detail: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QualificationOut:
    require_perm(current_user, PERM_QUAL_EDIT)
    if kind not in VALID_KINDS:
        raise HTTPException(400, "材料类型不合法")
    title = name.strip()
    if not title:
        raise HTTPException(400, "请填写名称")

    filename = ""
    storage_path = ""
    if file and file.filename:
        content = await file.read()
        if content:
            filename, storage_path = _save_file(file, content)

    item = QualificationAsset(
        kind=kind,
        name=title,
        level=level.strip(),
        number=number.strip(),
        valid_until=(valid_until.strip() or "长期"),
        owner=owner.strip(),
        detail=detail.strip(),
        filename=filename,
        storage_path=storage_path,
        review_status="已入库",
        merge_status="新增",
        aliases_json=[],
        sources_json=[],
        evidence_json=[],
        field_conflict_json=[],
        suspected_ids_json=[],
    )
    _fill_ocr(item, storage_path)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_out(item)


@router.patch("/qualifications/{qual_id}", response_model=QualificationOut)
async def update_qualification(
    qual_id: str,
    kind: str = Form(""),
    name: str = Form(""),
    level: str = Form(""),
    number: str = Form(""),
    valid_until: str = Form(""),
    owner: str = Form(""),
    detail: str = Form(""),
    review_status: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QualificationOut:
    require_perm(current_user, PERM_QUAL_EDIT)
    item = _require_asset(db, qual_id)
    if kind:
        if kind not in VALID_KINDS:
            raise HTTPException(400, "材料类型不合法")
        item.kind = kind
    if name.strip():
        item.name = name.strip()
    if level != "":
        item.level = level.strip()
    if number != "":
        item.number = number.strip()
    if valid_until != "":
        item.valid_until = valid_until.strip() or "长期"
    if owner != "":
        item.owner = owner.strip()
    if detail != "":
        item.detail = detail.strip()
    if review_status:
        if review_status not in REVIEW_STATUSES:
            raise HTTPException(400, "审核状态不合法")
        item.review_status = review_status
    if file and file.filename:
        content = await file.read()
        if content:
            storage.delete(item.storage_path)
            item.filename, item.storage_path = _save_file(file, content)
            _fill_ocr(item, item.storage_path)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _to_out(item)


@router.post("/qualifications/{qual_id}/merge", response_model=QualificationOut)
def merge_qualification(
    qual_id: str,
    payload: QualificationMergeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QualificationOut:
    require_perm(current_user, PERM_QUAL_EDIT)
    keep = _require_asset(db, qual_id)
    drop = _require_asset(db, payload.otherId)
    if keep.id == drop.id:
        raise HTTPException(400, "不能与自身合并")
    merge_assets(db, keep, drop)
    db.commit()
    return _to_out(_require_asset(db, keep.id))


@router.post("/qualifications/resolve", response_model=QualificationOut)
def resolve_qualification_pair(
    payload: QualificationResolveIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QualificationOut:
    require_perm(current_user, PERM_QUAL_EDIT)
    keep = _require_asset(db, payload.keepId)
    drop = _require_asset(db, payload.dropId)
    if payload.action == "merge":
        merge_assets(db, keep, drop)
    else:
        mark_keep_both(keep, drop)
    db.commit()
    return _to_out(_require_asset(db, keep.id))


@router.delete("/qualifications/{qual_id}")
def delete_qualification(
    qual_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_QUAL_EDIT)
    item = _require_asset(db, qual_id)
    refs = [img.storage_path for img in (item.images or []) if img.storage_path]
    if item.storage_path:
        refs.append(item.storage_path)
    db.delete(item)
    db.commit()
    for ref in refs:
        storage.delete(ref)
    return {"ok": True}


@router.get("/qualifications/{qual_id}/file")
def get_qualification_file(
    qual_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ = current_user
    item = _require_asset(db, qual_id)
    ref = item.storage_path
    filename = item.filename or "scan"
    if (not ref or not storage.exists(ref)) and item.images:
        first = next((img for img in item.images if img.storage_path and storage.exists(img.storage_path)), None)
        if first:
            ref = first.storage_path
            filename = first.filename or filename
    if not ref or not storage.exists(ref):
        raise HTTPException(404, "未上传扫描件")
    ext = os.path.splitext(filename or ref)[1].lower()
    try:
        return storage.http_response(
            ref,
            filename=filename,
            media_type=MIME.get(ext, "application/octet-stream"),
            inline=True,
        )
    except FileNotFoundError:
        raise HTTPException(404, "未上传扫描件")


@router.get("/qualification-images/{image_id}/file")
def get_qualification_image_file(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    img = db.get(QualificationAssetImage, image_id)
    if not img or not img.storage_path or not storage.exists(img.storage_path):
        raise HTTPException(404, "扫描图不存在")
    ext = os.path.splitext(img.filename or img.storage_path)[1].lower()
    try:
        return storage.http_response(
            img.storage_path,
            filename=img.filename,
            media_type=MIME.get(ext, "image/png"),
            inline=True,
        )
    except FileNotFoundError:
        raise HTTPException(404, "扫描图不存在")


@router.get("/qualification-source-docs", response_model=list[QualificationParseJobOut])
def list_source_docs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[QualificationParseJobOut]:
    _ = current_user
    rows = db.query(QualificationSourceDoc).order_by(QualificationSourceDoc.created_at.desc()).all()
    return [_job_to_out(d) for d in rows]


@router.post("/qualification-source-docs", response_model=list[QualificationParseJobOut])
async def upload_source_docs(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[QualificationParseJobOut]:
    require_perm(current_user, PERM_QUAL_EDIT)
    if not files:
        raise HTTPException(400, "请先选择商务标文件")
    created: list[QualificationSourceDoc] = []
    for upload in files:
        filename = upload.filename or ""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_SOURCE_EXTS:
            raise HTTPException(400, "仅支持 .doc / .docx / .pdf 格式")
        content = await upload.read()
        key = storage.put_bytes("qualification-docs", content, ext)
        doc = QualificationSourceDoc(
            filename=filename,
            storage_path=key,
            size_bytes=len(content),
            status="queued",
            note="排队抽取资质、合同与财务…",
        )
        db.add(doc)
        db.flush()
        created.append(doc)
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target="企业资质证照库",
        detail=f"上传 {len(created)} 份商务标并启动抽取",
    )
    db.commit()
    from ..tasks import run_qualification_extract_task

    for doc in created:
        db.refresh(doc)
        run_qualification_extract_task.delay(doc.id)
    return [_job_to_out(d) for d in created]


@router.get("/qualification-source-docs/{doc_id}/file")
def get_source_doc_file(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _ = current_user
    doc = db.get(QualificationSourceDoc, doc_id)
    if not doc or not doc.storage_path or not storage.exists(doc.storage_path):
        raise HTTPException(404, "来源商务标不存在")
    try:
        return storage.http_response(
            doc.storage_path,
            filename=doc.filename or "source.bin",
            media_type=storage.media_type_of(doc.filename or doc.storage_path),
            inline=True,
        )
    except FileNotFoundError:
        raise HTTPException(404, "来源商务标不存在")


@router.get("/qualification-extract-jobs/{job_id}", response_model=QualificationExtractJobOut)
def get_extract_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QualificationExtractJobOut:
    _ = current_user
    doc = db.get(QualificationSourceDoc, job_id)
    if not doc:
        raise HTTPException(404, "抽取任务不存在")
    status = doc.status if doc.status in ("queued", "running", "done", "failed") else "queued"
    return QualificationExtractJobOut(
        jobId=doc.id,
        status=status,  # type: ignore[arg-type]
        extracted=doc.extracted or 0,
        merged=doc.merged or 0,
        suspected=doc.suspected or 0,
        conflicts=doc.conflicts or 0,
        error=doc.error,
        note=doc.note or "",
    )
