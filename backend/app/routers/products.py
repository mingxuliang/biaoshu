"""产品功能库：产品库 CRUD、技术标抽取任务、功能点审核与去重确认。"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload

from ..audit import write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines.product_dedup import mark_keep_both, merge_features, sha256_bytes
from ..engines.product_extract import _delete_product_feature
from ..engines.qualification_extract import looks_like_qualification
from .. import storage
from ..models import (
    ProductFeature,
    ProductFeatureImage,
    ProductLibrary,
    ProductSourceDoc,
    User,
)
from ..permissions import PERM_WRITER, require_perm
from ..schemas import (
    ProductExtractJobOut,
    ProductFeatureIn,
    ProductFeatureOut,
    ProductFeaturePatchIn,
    ProductFeatureSourceOut,
    ProductImageOut,
    ProductLibraryIn,
    ProductLibraryOut,
    ProductMergeIn,
    ProductParseJobOut,
    ProductResolveIn,
)

router = APIRouter(prefix="/api", tags=["products"])

ALLOWED_EXTS = {".doc", ".docx", ".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
VALID_CATEGORIES = {"软件系统", "货物设备", "综合方案"}
STATUS_MAP = {"queued": "解析中", "running": "解析中", "done": "已完成", "failed": "抽取失败"}


def _dt(value) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _dt_hm(value) -> str:
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)[:16]


def _size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _library_counts(db: Session, lib: ProductLibrary) -> tuple[int, int, int, int]:
    roots = (
        db.query(ProductFeature.id, ProductFeature.status)
        .filter(ProductFeature.library_id == lib.id, ProductFeature.parent_id.is_(None))
        .all()
    )
    feature_count = len(roots)
    pending = sum(1 for f in roots if f.status == "待审核")
    image_count = (
        db.query(ProductFeatureImage.id)
        .join(ProductFeature, ProductFeatureImage.feature_id == ProductFeature.id)
        .filter(ProductFeature.library_id == lib.id)
        .count()
    )
    source_count = db.query(ProductSourceDoc).filter(ProductSourceDoc.library_id == lib.id).count()
    return feature_count, pending, image_count, source_count


def _library_to_out(db: Session, lib: ProductLibrary) -> ProductLibraryOut:
    feature_count, pending, image_count, source_count = _library_counts(db, lib)
    return ProductLibraryOut(
        id=lib.id,
        name=lib.name,
        category=lib.category if lib.category in VALID_CATEGORIES else "软件系统",  # type: ignore[arg-type]
        description=lib.description or "",
        owner=lib.owner or "",
        createdAt=_dt(lib.created_at),
        updatedAt=_dt(lib.updated_at or lib.created_at),
        featureCount=feature_count,
        pendingCount=pending,
        imageCount=image_count,
        sourceCount=source_count,
    )


def _image_to_out(img: ProductFeatureImage) -> ProductImageOut:
    kind = img.kind if img.kind in ("界面", "架构", "流程", "实物") else "界面"
    return ProductImageOut(
        id=img.id,
        caption=img.caption or "",
        kind=kind,  # type: ignore[arg-type]
        url=f"/api/product-images/{img.id}/file",
    )


def _feature_to_out(feat: ProductFeature, with_children: bool = True, with_evidence: bool = True) -> ProductFeatureOut:
    sources = []
    for row in feat.sources_json or []:
        if isinstance(row, dict):
            sources.append(
                ProductFeatureSourceOut(docId=row.get("docId") or "", filename=row.get("filename") or "")
            )
    source_doc = "、".join(s.filename for s in sources if s.filename) or "手工录入"
    merge_status = feat.merge_status if feat.merge_status in ("新增", "并入已有", "疑似重复", "参数冲突") else "新增"
    kind = feat.kind if feat.kind in ("软件功能", "货物产品", "模块方案") else "软件功能"
    status = feat.status if feat.status in ("待审核", "已入库", "已停用") else "待审核"
    children: list[ProductFeatureOut] = []
    if with_children:
        ordered = sorted(
            feat.children or [],
            key=lambda row: ((row.created_at.isoformat() if row.created_at else ""), row.name or ""),
        )
        children = [_feature_to_out(row, with_children=False, with_evidence=with_evidence) for row in ordered]
    return ProductFeatureOut(
        id=feat.id,
        libraryId=feat.library_id,
        name=feat.name,
        kind=kind,  # type: ignore[arg-type]
        module=feat.module or "",
        params=feat.params or "",
        intro=feat.intro or "",
        bidCopy=feat.bid_copy or "",
        brand=feat.brand or "",
        model=feat.model or "",
        unit=feat.unit or "",
        sourceDoc=source_doc,
        status=status,  # type: ignore[arg-type]
        mergeStatus=merge_status,  # type: ignore[arg-type]
        aliases=list(feat.aliases_json or []),
        sources=sources,
        evidence=list(feat.evidence_json or []) if with_evidence else [],
        paramsConflict=list(feat.params_conflict_json or []),
        suspectedIds=list(feat.suspected_ids_json or []),
        images=[_image_to_out(img) for img in feat.images],
        parentId=feat.parent_id or "",
        children=children,
        updatedAt=_dt(feat.updated_at or feat.created_at),
    )


def _job_to_out(doc: ProductSourceDoc) -> ProductParseJobOut:
    return ProductParseJobOut(
        id=doc.id,
        libraryId=doc.library_id,
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


def _require_library(db: Session, library_id: str) -> ProductLibrary:
    lib = db.get(ProductLibrary, library_id)
    if not lib:
        raise HTTPException(404, "产品库不存在")
    return lib


def _require_feature(db: Session, feature_id: str) -> ProductFeature:
    feat = (
        db.query(ProductFeature)
        .options(
            selectinload(ProductFeature.images),
            selectinload(ProductFeature.children).selectinload(ProductFeature.images),
        )
        .filter(ProductFeature.id == feature_id)
        .first()
    )
    if not feat:
        raise HTTPException(404, "功能点不存在")
    return feat


def _touch_library(lib: ProductLibrary) -> None:
    lib.updated_at = datetime.utcnow()


@router.get("/product-libraries", response_model=list[ProductLibraryOut])
def list_product_libraries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProductLibraryOut]:
    _ = current_user
    libs = db.query(ProductLibrary).order_by(ProductLibrary.updated_at.desc()).all()
    return [_library_to_out(db, lib) for lib in libs]


@router.post("/product-libraries", response_model=ProductLibraryOut)
def create_product_library(
    payload: ProductLibraryIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductLibraryOut:
    require_perm(current_user, PERM_WRITER)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "请填写产品库名称")
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(400, "产品类型不合法")
    lib = ProductLibrary(
        name=name,
        category=payload.category,
        description=(payload.description or "").strip(),
        owner=(payload.owner or current_user.name or "").strip(),
    )
    db.add(lib)
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=f"产品库 / {name}",
        detail="新建产品库",
    )
    db.commit()
    db.refresh(lib)
    return _library_to_out(db, lib)


@router.get("/product-libraries/{library_id}", response_model=ProductLibraryOut)
def get_product_library(
    library_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductLibraryOut:
    _ = current_user
    return _library_to_out(db, _require_library(db, library_id))


@router.patch("/product-libraries/{library_id}", response_model=ProductLibraryOut)
def update_product_library(
    library_id: str,
    payload: ProductLibraryIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductLibraryOut:
    require_perm(current_user, PERM_WRITER)
    lib = _require_library(db, library_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "请填写产品库名称")
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(400, "产品类型不合法")
    lib.name = name
    lib.category = payload.category
    lib.description = (payload.description or "").strip()
    lib.owner = (payload.owner or lib.owner or "").strip()
    _touch_library(lib)
    db.commit()
    db.refresh(lib)
    return _library_to_out(db, lib)


@router.delete("/product-libraries/{library_id}")
def delete_product_library(
    library_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_WRITER)
    lib = _require_library(db, library_id)
    name = lib.name
    refs = [img.storage_path for feat in lib.features for img in feat.images]
    refs.extend(doc.storage_path for doc in lib.source_docs)
    db.delete(lib)
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=f"产品库 / {name}",
        detail="删除产品库",
    )
    db.commit()
    for ref in refs:
        storage.delete(ref)
    return {"ok": True}


@router.get("/product-libraries/{library_id}/features", response_model=list[ProductFeatureOut])
def list_features(
    library_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProductFeatureOut]:
    _ = current_user
    _require_library(db, library_id)
    rows = (
        db.query(ProductFeature)
        .options(
            selectinload(ProductFeature.images),
            selectinload(ProductFeature.children).selectinload(ProductFeature.images),
        )
        .filter(ProductFeature.library_id == library_id, ProductFeature.parent_id.is_(None))
        .order_by(ProductFeature.updated_at.desc())
        .all()
    )
    return [_feature_to_out(f, with_evidence=False) for f in rows]


@router.post("/product-libraries/{library_id}/features", response_model=ProductFeatureOut)
def create_feature(
    library_id: str,
    payload: ProductFeatureIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductFeatureOut:
    require_perm(current_user, PERM_WRITER)
    lib = _require_library(db, library_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "请填写功能 / 产品名称")
    if looks_like_qualification(name, payload.intro or ""):
        raise HTTPException(400, "证照、合同复印件请放到资质证照库，产品库只收录功能点")
    parent_id = (payload.parentId or "").strip() or None
    if parent_id:
        parent = db.get(ProductFeature, parent_id)
        if not parent or parent.library_id != library_id:
            raise HTTPException(400, "一级功能菜单不存在")
        if parent.parent_id:
            raise HTTPException(400, "只能挂在一级功能菜单下")
    feat = ProductFeature(
        library_id=library_id,
        name=name,
        kind=payload.kind,
        module=(payload.module or "").strip(),
        params=(payload.params or "").strip(),
        intro=(payload.intro or "").strip(),
        bid_copy=(payload.bidCopy or payload.intro or "").strip(),
        brand=(payload.brand or "").strip(),
        model=(payload.model or "").strip(),
        unit=(payload.unit or "").strip(),
        status=payload.status or "待审核",
        merge_status="新增",
        aliases_json=[],
        sources_json=[{"docId": "", "filename": "手工录入"}],
        evidence_json=[],
        locked_copy=False,
        parent_id=parent_id,
    )
    db.add(feat)
    _touch_library(lib)
    db.commit()
    feat = _require_feature(db, feat.id)
    return _feature_to_out(feat)


@router.patch("/product-features/{feature_id}", response_model=ProductFeatureOut)
def patch_feature(
    feature_id: str,
    payload: ProductFeaturePatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductFeatureOut:
    require_perm(current_user, PERM_WRITER)
    feat = _require_feature(db, feature_id)
    data = payload.model_dump(exclude_unset=True)
    next_name = feat.name
    next_intro = feat.intro or ""
    if "name" in data:
        next_name = (data["name"] or "").strip()
        if not next_name:
            raise HTTPException(400, "请填写功能 / 产品名称")
    if "intro" in data:
        next_intro = (data["intro"] or "").strip()
    if ("name" in data or "intro" in data) and looks_like_qualification(next_name, next_intro):
        raise HTTPException(400, "证照、合同复印件请放到资质证照库，产品库只收录功能点")
    if "name" in data:
        feat.name = next_name
    if "kind" in data and data["kind"]:
        feat.kind = data["kind"]
    if "module" in data:
        feat.module = (data["module"] or "").strip()
    if "params" in data:
        feat.params = (data["params"] or "").strip()
    if "intro" in data:
        feat.intro = (data["intro"] or "").strip()
    if "bidCopy" in data:
        feat.bid_copy = (data["bidCopy"] or "").strip()
        feat.locked_copy = True
    if "brand" in data:
        feat.brand = (data["brand"] or "").strip()
    if "model" in data:
        feat.model = (data["model"] or "").strip()
    if "unit" in data:
        feat.unit = (data["unit"] or "").strip()
    if "status" in data and data["status"]:
        feat.status = data["status"]
        if data["status"] == "已入库" and feat.merge_status in ("疑似重复",):
            feat.merge_status = "新增"
        if not feat.parent_id:
            for child in feat.children or []:
                child.status = data["status"]
    lib = db.get(ProductLibrary, feat.library_id)
    if lib:
        _touch_library(lib)
    db.commit()
    return _feature_to_out(_require_feature(db, feat.id))


@router.delete("/product-features/{feature_id}")
def delete_feature(
    feature_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_WRITER)
    feat = _require_feature(db, feature_id)
    lib = db.get(ProductLibrary, feat.library_id)
    _delete_product_feature(db, feat)
    if lib:
        _touch_library(lib)
    db.commit()
    return {"ok": True}


@router.post("/product-features/{feature_id}/merge", response_model=ProductFeatureOut)
def merge_feature_api(
    feature_id: str,
    payload: ProductMergeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductFeatureOut:
    require_perm(current_user, PERM_WRITER)
    keep = _require_feature(db, feature_id)
    drop = _require_feature(db, payload.otherId)
    if keep.library_id != drop.library_id:
        raise HTTPException(400, "只能合并同一产品库内的功能点")
    if keep.id == drop.id:
        raise HTTPException(400, "不能与自身合并")
    merge_features(db, keep, drop)
    lib = db.get(ProductLibrary, keep.library_id)
    if lib:
        _touch_library(lib)
    db.commit()
    return _feature_to_out(_require_feature(db, keep.id))


@router.post("/product-libraries/{library_id}/resolve", response_model=ProductFeatureOut)
def resolve_pair(
    library_id: str,
    payload: ProductResolveIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductFeatureOut:
    require_perm(current_user, PERM_WRITER)
    _require_library(db, library_id)
    keep = _require_feature(db, payload.keepId)
    drop = _require_feature(db, payload.dropId)
    if keep.library_id != library_id or drop.library_id != library_id:
        raise HTTPException(400, "功能点不属于该产品库")
    if payload.action == "merge":
        merge_features(db, keep, drop)
    else:
        mark_keep_both(keep, drop)
    lib = db.get(ProductLibrary, library_id)
    if lib:
        _touch_library(lib)
    db.commit()
    return _feature_to_out(_require_feature(db, keep.id))


@router.post("/product-features/{feature_id}/images", response_model=ProductFeatureOut)
async def upload_feature_images(
    feature_id: str,
    files: list[UploadFile] = File(...),
    captions: str = Form(""),
    kinds: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductFeatureOut:
    require_perm(current_user, PERM_WRITER)
    feat = _require_feature(db, feature_id)
    if len(feat.images) + len(files) > 80:
        raise HTTPException(400, "最多上传 80 张附图")
    cap_list = [c.strip() for c in captions.split("|")] if captions else []
    kind_list = [k.strip() for k in kinds.split("|")] if kinds else []
    existing = {img.sha256 for img in feat.images if img.sha256}
    for idx, upload in enumerate(files):
        filename = upload.filename or "image.png"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in IMAGE_EXTS:
            raise HTTPException(400, "仅支持 JPG / PNG / WebP")
        content = await upload.read()
        if len(content) > 8 * 1024 * 1024:
            raise HTTPException(400, "单张图片不超过 8MB")
        digest = sha256_bytes(content)
        if digest in existing:
            continue
        key = storage.put_bytes(f"product-images/{feat.library_id}", content, ext)
        kind = kind_list[idx] if idx < len(kind_list) else "界面"
        if kind not in ("界面", "架构", "流程", "实物"):
            kind = "界面"
        caption = cap_list[idx] if idx < len(cap_list) else os.path.splitext(filename)[0]
        db.add(
            ProductFeatureImage(
                feature_id=feat.id,
                caption=(caption or "附图")[:80],
                kind=kind,
                filename=filename,
                storage_path=key,
                sha256=digest,
            )
        )
        existing.add(digest)
    lib = db.get(ProductLibrary, feat.library_id)
    if lib:
        _touch_library(lib)
    db.commit()
    return _feature_to_out(_require_feature(db, feat.id))


@router.delete("/product-images/{image_id}")
def delete_product_image(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_WRITER)
    img = db.get(ProductFeatureImage, image_id)
    if not img:
        raise HTTPException(404, "附图不存在")
    ref = img.storage_path
    db.delete(img)
    db.commit()
    storage.delete(ref)
    return {"ok": True}


@router.get("/product-images/{image_id}/file")
def get_product_image_file(
    image_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    img = db.get(ProductFeatureImage, image_id)
    if not img or not img.storage_path or not storage.exists(img.storage_path):
        raise HTTPException(404, "附图不存在")
    ext = os.path.splitext(img.filename or img.storage_path)[1].lower()
    media = IMAGE_MIME.get(ext, "image/png")
    try:
        return storage.http_response(img.storage_path, filename=img.filename, media_type=media, inline=True)
    except FileNotFoundError:
        raise HTTPException(404, "附图不存在")


@router.get("/product-libraries/{library_id}/source-docs", response_model=list[ProductParseJobOut])
def list_source_docs(
    library_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProductParseJobOut]:
    _ = current_user
    _require_library(db, library_id)
    rows = (
        db.query(ProductSourceDoc)
        .filter(ProductSourceDoc.library_id == library_id)
        .order_by(ProductSourceDoc.created_at.desc())
        .all()
    )
    return [_job_to_out(d) for d in rows]


@router.post("/product-libraries/{library_id}/source-docs", response_model=list[ProductParseJobOut])
async def upload_source_docs(
    library_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProductParseJobOut]:
    require_perm(current_user, PERM_WRITER)
    lib = _require_library(db, library_id)
    if not files:
        raise HTTPException(400, "请先选择技术标文件")
    created: list[ProductSourceDoc] = []
    for upload in files:
        filename = upload.filename or ""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(400, "仅支持 .doc / .docx / .pdf 格式")
        content = await upload.read()
        key = storage.put_bytes(f"product-docs/{library_id}", content, ext)
        doc = ProductSourceDoc(
            library_id=library_id,
            filename=filename,
            storage_path=key,
            size_bytes=len(content),
            status="queued",
            note="排队抽取功能点；证照将同步到资质库…",
        )
        db.add(doc)
        db.flush()
        created.append(doc)
    _touch_library(lib)
    write_audit(
        db,
        action="引用知识",
        user_name=current_user.name,
        target=f"产品库 / {lib.name}",
        detail=f"上传 {len(created)} 份技术标并启动抽取",
    )
    db.commit()
    from ..tasks import run_product_extract_task

    for doc in created:
        db.refresh(doc)
        run_product_extract_task.delay(doc.id)
    return [_job_to_out(d) for d in created]


@router.get("/product-extract-jobs/{job_id}", response_model=ProductExtractJobOut)
def get_extract_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductExtractJobOut:
    _ = current_user
    doc = db.get(ProductSourceDoc, job_id)
    if not doc:
        raise HTTPException(404, "抽取任务不存在")
    status = doc.status if doc.status in ("queued", "running", "done", "failed") else "queued"
    return ProductExtractJobOut(
        jobId=doc.id,
        status=status,  # type: ignore[arg-type]
        extracted=doc.extracted or 0,
        merged=doc.merged or 0,
        suspected=doc.suspected or 0,
        conflicts=doc.conflicts or 0,
        error=doc.error,
        note=doc.note or "",
    )
