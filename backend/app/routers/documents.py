import os
import uuid

import docx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import BidDocument
from ..schemas import UploadDocOut

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/bid-documents", response_model=UploadDocOut)
async def upload_bid_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadDocOut:
    settings = get_settings()
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".doc":
        raise HTTPException(400, "暂不支持旧版 .doc 格式，请在 Word 中另存为 .docx 后重新上传")
    if ext != ".docx":
        raise HTTPException(400, "仅支持 .docx 格式的 Word 文档")

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

    doc = BidDocument(
        project_id=project_id,
        filename=filename,
        storage_path=storage_path,
        size_bytes=len(content),
        source="upload",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return UploadDocOut(id=doc.id, filename=doc.filename, size_bytes=doc.size_bytes, source=doc.source)


@router.post("/bid-documents/from-sample", response_model=UploadDocOut)
def use_sample_document(project_id: str = Form(...), db: Session = Depends(get_db)) -> UploadDocOut:
    """撰写工作台后端未接入前，用内置示例投标书跑真实引擎，保证「从工作台选择」路径也有真实结果。"""
    settings = get_settings()
    sample_path = os.path.join(settings.sample_dir, "demo_bid.docx")
    if not os.path.exists(sample_path):
        raise HTTPException(500, "示例文档缺失，请检查 backend/sample_data/demo_bid.docx 是否存在")

    doc = BidDocument(
        project_id=project_id,
        filename="demo_bid.docx（工作台示例文档）",
        storage_path=sample_path,
        size_bytes=os.path.getsize(sample_path),
        source="workbench",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return UploadDocOut(id=doc.id, filename=doc.filename, size_bytes=doc.size_bytes, source=doc.source)
