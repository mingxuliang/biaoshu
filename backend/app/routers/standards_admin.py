"""平台规范库：目录查询和上传入库。"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_platform_db
from ..platform_auth import ROLE_OPS, get_current_admin, require_roles
from ..platform_models import StdCatalog
from ..tasks import import_platform_standard_task

router = APIRouter(prefix="/api/admin", tags=["admin-standards"])


class StandardCatalogOut(BaseModel):
    id: str
    code: str
    name: str
    specialty: str
    status: str
    clauseCount: int
    note: str


@router.get("/standards", response_model=list[StandardCatalogOut])
def list_standards(
    db: Session = Depends(get_platform_db),
    _: object = Depends(get_current_admin),
) -> list[StandardCatalogOut]:
    rows = db.query(StdCatalog).order_by(StdCatalog.id.desc()).limit(200).all()
    return [
        StandardCatalogOut(
            id=row.id,
            code=row.code or "",
            name=row.name or "",
            specialty=row.specialty or "",
            status=row.status or "",
            clauseCount=row.clause_count or 0,
            note=row.note or "",
        )
        for row in rows
    ]


@router.post("/standards/upload")
def upload_standard(
    file: UploadFile = File(...),
    db: Session = Depends(get_platform_db),
    _: object = Depends(require_roles(ROLE_OPS)),
) -> dict:
    name = os.path.basename(file.filename or "standard.pdf")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "请上传 PDF")
    folder = os.path.join("uploads", "standards")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uuid.uuid4().hex}-{name}")
    with open(path, "wb") as handle:
        handle.write(file.file.read())
    catalog = StdCatalog(code="", name=name, source_file=name, storage_path=path, status="入库中")
    db.add(catalog)
    db.commit()
    import_platform_standard_task.delay(path, name, catalog.id)
    return {"id": catalog.id, "status": "入库中"}
