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
from .tenancy import bucket_for, current_tenant, require_tenant

_CLIENT: Minio | None = None
_READY_BUCKETS: set[str] = set()

_MEDIA = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def media_type_of(name: str, default: str = "application/octet-stream") -> str:
    ext = os.path.splitext(name or "")[1].lower()
    return _MEDIA.get(ext, default)


def _allowed_roots() -> list[str]:
    settings = get_settings()
    roots = []
    for root in (settings.upload_dir, settings.sample_dir):
        if root:
            roots.append(os.path.realpath(root))
    return roots


def is_local_file(ref: str | None) -> bool:
    """历史数据里的本地路径只认上传目录和示例目录下的文件，防止库里被写入 /etc/passwd 之类的路径后被读出。"""
    if not ref or not os.path.isfile(ref):
        return False
    real = os.path.realpath(ref)
    for root in _allowed_roots():
        try:
            if os.path.commonpath([real, root]) == root:
                return True
        except ValueError:
            continue
    return False


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


def platform_bucket() -> str:
    """平台自有文件（发票等），不放进任何企业 bucket。"""
    return f"{get_settings().minio_bucket_prefix}-platform"


def _bucket(bucket: str | None = None) -> str:
    """显式传 bucket 只给平台文件用；企业文件一律按当前企业上下文选 bucket，没有上下文就报错。"""
    if bucket:
        return bucket
    return bucket_for(require_tenant())


def ensure_bucket(name: str, retries: int = 20) -> None:
    if name in _READY_BUCKETS:
        return
    last: Exception | None = None
    for _ in range(retries):
        try:
            client = _client()
            if not client.bucket_exists(name):
                client.make_bucket(name)
            _READY_BUCKETS.add(name)
            return
        except Exception as exc:  # noqa: BLE001 —— 等待 MinIO 就绪
            last = exc
            time.sleep(1)
    raise RuntimeError(f"MinIO 不可用：{last}") from last


def ensure_ready(bucket: str | None = None) -> None:
    """创建 bucket（若不存在）。没有企业上下文时（启动阶段）只检查 MinIO 可用并建平台 bucket。"""
    if bucket:
        ensure_bucket(bucket)
        return
    tenant_id = current_tenant()
    ensure_bucket(bucket_for(tenant_id) if tenant_id else platform_bucket())


def bucket_usage_bytes(bucket: str) -> tuple[int, int]:
    """(对象数, 总字节)；bucket 不存在时为 (0, 0)。"""
    client = _client()
    if not client.bucket_exists(bucket):
        return 0, 0
    count = 0
    total = 0
    for obj in client.list_objects(bucket, recursive=True):
        count += 1
        total += int(obj.size or 0)
    return count, total


def remove_bucket(bucket: str) -> int:
    """企业注销时清空并删除其 bucket，返回删除的对象数。"""
    client = _client()
    if not client.bucket_exists(bucket):
        return 0
    removed = 0
    for obj in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, obj.object_name)
        removed += 1
    client.remove_bucket(bucket)
    _READY_BUCKETS.discard(bucket)
    return removed


_USAGE_CACHE: dict[str, tuple[float, int]] = {}
_USAGE_TTL = 300


def tenant_usage_bytes(tenant_id: str, *, refresh: bool = False) -> int:
    cached = _USAGE_CACHE.get(tenant_id)
    if cached and not refresh and time.time() - cached[0] < _USAGE_TTL:
        return cached[1]
    _, total = bucket_usage_bytes(bucket_for(tenant_id))
    _USAGE_CACHE[tenant_id] = (time.time(), total)
    return total


class StorageQuotaExceeded(Exception):
    pass


def check_quota(tenant_id: str, incoming: int) -> None:
    from .db import platform_session
    from .platform_models import Tenant

    with platform_session() as pdb:
        tenant = pdb.get(Tenant, tenant_id)
        quota_mb = int(tenant.storage_quota_mb or 0) if tenant else 0
    if quota_mb <= 0:
        return
    try:
        used = tenant_usage_bytes(tenant_id)
    except Exception:  # noqa: BLE001 —— 统计失败不阻断上传
        return
    if used + incoming > quota_mb * 1024 * 1024:
        raise StorageQuotaExceeded(f"企业存储空间已满（{quota_mb} MB），请清理文件或升级套餐")
    _USAGE_CACHE[tenant_id] = (_USAGE_CACHE.get(tenant_id, (time.time(), 0))[0], used + incoming)


def put_bytes(prefix: str, data: bytes, ext: str, content_type: str = "", *, bucket: str | None = None) -> str:
    if not data:
        raise ValueError("不能上传空文件")
    if bucket is None:
        check_quota(require_tenant(), len(data))
    ensure_ready(_bucket(bucket))
    key = object_key(prefix, ext)
    ctype = content_type or media_type_of(key)
    _client().put_object(
        _bucket(bucket),
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=ctype,
    )
    return key


def put_at(key: str, data: bytes, content_type: str = "", *, bucket: str | None = None) -> str:
    """写到指定对象键，已存在则覆盖。给断点续跑这类「同一份进度反复更新」的场景用，
    跟 put_bytes 每次生成新 uuid 键不一样。不计入存储配额：这是内部记账文件，不是用户上传内容。
    """
    ensure_ready(_bucket(bucket))
    ctype = content_type or media_type_of(key)
    _client().put_object(
        _bucket(bucket),
        key.replace("\\", "/"),
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


def get_bytes(ref: str, *, bucket: str | None = None) -> bytes:
    if not ref:
        raise FileNotFoundError("空对象键")
    if is_local_file(ref):
        with open(ref, "rb") as fh:
            return fh.read()
    ensure_ready(_bucket(bucket))
    try:
        resp = _client().get_object(_bucket(bucket), ref.replace("\\", "/"))
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except S3Error as exc:
        raise FileNotFoundError(ref) from exc


def exists(ref: str | None, *, bucket: str | None = None) -> bool:
    if not ref:
        return False
    if is_local_file(ref):
        return True
    try:
        ensure_ready(_bucket(bucket))
        _client().stat_object(_bucket(bucket), ref.replace("\\", "/"))
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


def delete(ref: str | None, *, bucket: str | None = None) -> None:
    if not ref:
        return
    if is_local_file(ref):
        try:
            os.remove(ref)
        except OSError:
            pass
        return
    try:
        ensure_ready(_bucket(bucket))
        _client().remove_object(_bucket(bucket), ref.replace("\\", "/"))
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
    bucket: str | None = None,
) -> Response:
    data = get_bytes(ref, bucket=bucket)
    name = filename or os.path.basename(ref) or "file"
    media = media_type or media_type_of(name)
    encoded = urllib.parse.quote(name)
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '\\"' else "_" for ch in os.path.splitext(name)[0]) or "file"
    ascii_name = f"{ascii_name}{os.path.splitext(name)[1]}"
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}",
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )
