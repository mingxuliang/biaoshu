"""MinIO 对象存储。上传文件、图片与生成文档一律写入 bucket。

数据库 `storage_path` 存对象键，例如 `product-images/{libraryId}/{uuid}.png`。
若值为仍存在的本地绝对路径（历史数据），读取时优先用本地文件。
引擎需要真实路径时用 `as_local()` 下载到临时文件。
"""

from __future__ import annotations

import io
import os
import tempfile
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from typing import Iterator

from fastapi.responses import Response
from minio import Minio
from minio.error import S3Error

from .config import get_settings

_CLIENT: Minio | None = None
_BUCKET_READY = False

_MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def media_type_of(name: str, default: str = "application/octet-stream") -> str:
    ext = os.path.splitext(name or "")[1].lower()
    return _MEDIA.get(ext, default)


def is_local_file(ref: str | None) -> bool:
    return bool(ref and os.path.isfile(ref))


def object_key(prefix: str, ext: str) -> str:
    suffix = ext if ext.startswith(".") else f".{ext}" if ext else ""
    clean = (prefix or "misc").strip("/").replace("\\", "/")
    return f"{clean}/{uuid.uuid4().hex}{suffix.lower()}"


def _client() -> Minio:
    global _CLIENT
    if _CLIENT is None:
        settings = get_settings()
        _CLIENT = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _CLIENT


def ensure_ready() -> None:
    """创建 bucket（若不存在）。应用与 worker 启动时调用。"""
    global _BUCKET_READY
    if _BUCKET_READY:
        return
    settings = get_settings()
    last: Exception | None = None
    for _ in range(20):
        try:
            client = _client()
            if not client.bucket_exists(settings.minio_bucket):
                client.make_bucket(settings.minio_bucket)
            _BUCKET_READY = True
            return
        except Exception as exc:  # noqa: BLE001 —— 等待 MinIO 就绪
            last = exc
            time.sleep(1)
    raise RuntimeError(f"MinIO 不可用：{last}") from last


def put_bytes(prefix: str, data: bytes, ext: str, content_type: str = "") -> str:
    if not data:
        raise ValueError("不能上传空文件")
    ensure_ready()
    key = object_key(prefix, ext)
    ctype = content_type or media_type_of(key)
    _client().put_object(
        get_settings().minio_bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=ctype,
    )
    return key


def put_file(prefix: str, local_path: str, ext: str = "", content_type: str = "") -> str:
    with open(local_path, "rb") as fh:
        data = fh.read()
    if not ext:
        ext = os.path.splitext(local_path)[1]
    return put_bytes(prefix, data, ext, content_type)


def get_bytes(ref: str) -> bytes:
    if not ref:
        raise FileNotFoundError("空对象键")
    if is_local_file(ref):
        with open(ref, "rb") as fh:
            return fh.read()
    ensure_ready()
    try:
        resp = _client().get_object(get_settings().minio_bucket, ref.replace("\\", "/"))
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except S3Error as exc:
        raise FileNotFoundError(ref) from exc


def exists(ref: str | None) -> bool:
    if not ref:
        return False
    if is_local_file(ref):
        return True
    try:
        ensure_ready()
        _client().stat_object(get_settings().minio_bucket, ref.replace("\\", "/"))
        return True
    except S3Error:
        return False
    except Exception:
        return False


def copy_object(src_ref: str, prefix: str, ext: str = "") -> str:
    data = get_bytes(src_ref)
    if not ext:
        ext = os.path.splitext(src_ref)[1] or ".bin"
    return put_bytes(prefix, data, ext)


def delete(ref: str | None) -> None:
    if not ref:
        return
    if is_local_file(ref):
        try:
            os.remove(ref)
        except OSError:
            pass
        return
    try:
        ensure_ready()
        _client().remove_object(get_settings().minio_bucket, ref.replace("\\", "/"))
    except S3Error:
        pass


@contextmanager
def as_local(ref: str | None, suffix: str = "") -> Iterator[str]:
    """得到可供 python-docx / PyMuPDF 打开的本地路径。退出后删除临时文件。"""
    if not ref:
        raise FileNotFoundError("文件不存在")
    if is_local_file(ref):
        yield ref
        return
    data = get_bytes(ref)
    ext = suffix or os.path.splitext(ref)[1] or ""
    fd, tmp = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        yield tmp
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@contextmanager
def as_local_map(refs: dict[str, str]) -> Iterator[dict[str, str]]:
    cms: list = []
    out: dict[str, str] = {}
    try:
        for key, ref in refs.items():
            if not ref:
                continue
            cm = as_local(ref)
            out[key] = cm.__enter__()
            cms.append(cm)
        yield out
    finally:
        for cm in reversed(cms):
            cm.__exit__(None, None, None)


def http_response(
    ref: str,
    *,
    filename: str = "",
    media_type: str = "",
    inline: bool = False,
) -> Response:
    data = get_bytes(ref)
    name = filename or os.path.basename(ref) or "file"
    media = media_type or media_type_of(name)
    encoded = urllib.parse.quote(name)
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"file\"; filename*=UTF-8''{encoded}",
            "Cache-Control": "private, max-age=86400",
        },
    )
