"""两份技术标查重：上传后同步比对，不落库。"""

from __future__ import annotations

import hashlib
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ..audit import actor_from_request, write_audit
from ..auth import get_current_user
from ..db import get_db
from ..engines import rules_config
from ..engines.docx_extract import extract_full_text
from ..engines.e_duplicate_pair import analyze_pair
from ..models import User
from ..permissions import PERM_REVIEW, require_perm
from ..schemas import DuplicateCheckOut

router = APIRouter(prefix="/api", tags=["duplicate"])

ALLOWED_EXTS = {".docx", ".pdf"}
MAX_BYTES = 40 * 1024 * 1024


def _read_upload(file: UploadFile) -> tuple[str, str, bytes]:
    filename = file.filename or "未命名"
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".doc":
        raise HTTPException(400, "暂不支持旧版 .doc，请另存为 .docx 后上传")
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, "仅支持技术标 .docx 或 .pdf")
    content = file.file.read()
    if not content:
        raise HTTPException(400, f"「{filename}」是空文件")
    if len(content) > MAX_BYTES:
        raise HTTPException(400, f"「{filename}」超过 40MB，请压缩后再传")
    return filename, ext, content


def _extract(content: bytes, ext: str, filename: str) -> str:
    suffix = ext if ext.startswith(".") else f".{ext}"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(content)
        try:
            text = extract_full_text(path)
        except Exception as exc:
            raise HTTPException(400, f"「{filename}」无法解析，请确认是可读的技术标文件") from exc
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, f"「{filename}」未抽出正文（扫描件 PDF 请先 OCR，或改用 Word）")
    return text


@router.post("/duplicate-check", response_model=DuplicateCheckOut)
async def duplicate_check(
    request: Request,
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    require_perm(current_user, PERM_REVIEW)
    name_a, ext_a, bytes_a = _read_upload(file_a)
    name_b, ext_b, bytes_b = _read_upload(file_b)
    hash_a = hashlib.md5(bytes_a).hexdigest()
    hash_b = hashlib.md5(bytes_b).hexdigest()
    identical = hash_a == hash_b
    text_a = _extract(bytes_a, ext_a, name_a)
    text_b = text_a if identical else _extract(bytes_b, ext_b, name_b)
    thresholds = rules_config.load_thresholds(db)
    sim_keys = rules_config.load_enabled_catalog_keys(db, "dup_sim")
    result = analyze_pair(
        text_a,
        text_b,
        thresholds,
        identical=identical,
        name_a=name_a,
        name_b=name_b,
        sim_keys=sim_keys,
    )
    write_audit(
        db,
        action="技术标查重",
        user_name=actor_from_request(db, request),
        target=f"{name_a} ↔ {name_b}",
        detail=f"整体 {result.get('wholePct')}%，灯 {result.get('light')}",
    )
    db.commit()
    return result
