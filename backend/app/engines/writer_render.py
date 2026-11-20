"""撰写页版式预览：把和导出同一条路径生成的 .docx 交给 LibreOffice 渲染成 PDF，再按页转 PNG。

- 结果按 docx 内容哈希缓存。同一份内容不会再次转换。
- 优先走常驻的 lo 服务（backend/lo），不可达时回退本机 soffice（冷启动，慢，但开发环境能用）。
- 缓存是可丢弃的：删掉目录只会让下一次预览重新渲染。
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from ..config import get_settings

# 导出代码、字体映射或渲染服务有改动、需要作废旧缓存时加一。
RENDER_VERSION = "1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_KEEP_PER_DRAFT = 60
_PNG_ZOOM = 1.6


class RenderUnavailable(RuntimeError):
    """没有可用的 LibreOffice 渲染能力，或渲染失败。"""


def is_valid_hash(value: str) -> bool:
    return bool(_HASH_RE.match(value or ""))


def docx_fingerprint(docx_bytes: bytes) -> str:
    """docx 本身带 zip 时间戳，直接哈希整个文件每次都不同；这里只哈希各部件的内容。"""
    digest = hashlib.sha256(RENDER_VERSION.encode())
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("docProps/"):
                continue
            digest.update(name.encode("utf-8"))
            digest.update(zf.read(name))
    return digest.hexdigest()


def _cache_dir(draft_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", draft_id)
    path = os.path.join(get_settings().upload_dir, "writer-render", safe)
    os.makedirs(path, exist_ok=True)
    return path


def _pdf_path(draft_id: str, key: str) -> str:
    return os.path.join(_cache_dir(draft_id), f"{key}.pdf")


def _prune(draft_id: str) -> None:
    folder = _cache_dir(draft_id)
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".pdf")]
    if len(files) <= _KEEP_PER_DRAFT:
        return
    files.sort(key=lambda p: os.path.getmtime(p))
    for path in files[: len(files) - _KEEP_PER_DRAFT]:
        try:
            os.remove(path)
        except OSError:
            pass


def _convert_via_service(docx_bytes: bytes) -> bytes:
    settings = get_settings()
    url = settings.lo_render_url.rstrip("/") + "/convert"
    req = urllib.request.Request(
        url,
        data=docx_bytes,
        method="POST",
        headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.lo_render_timeout_sec) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RenderUnavailable(f"渲染服务转换失败：{detail or exc.code}") from exc
    except TimeoutError as exc:
        raise RenderUnavailable("版式渲染超时") from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        # 服务没起来或网络不通：交给调用方回退本机 soffice
        raise ConnectionError(str(exc)) from exc


def _convert_via_local_soffice(docx_bytes: bytes) -> bytes:
    from .legacy_doc import _soffice_bin

    binary = _soffice_bin()
    if not binary:
        raise RenderUnavailable("版式预览服务未启动，本机也没有 LibreOffice")
    work = tempfile.mkdtemp(prefix="wr-preview-")
    profile = tempfile.mkdtemp(prefix="lo-profile-")
    try:
        src = os.path.join(work, "draft.docx")
        with open(src, "wb") as fh:
            fh.write(docx_bytes)
        proc = subprocess.run(
            [
                binary,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--norestore",
                "-env:UserInstallation=file:///" + profile.replace("\\", "/").lstrip("/"),
                "--convert-to",
                "pdf",
                "--outdir",
                work,
                src,
            ],
            capture_output=True,
            timeout=get_settings().lo_render_timeout_sec,
            check=False,
        )
        out = os.path.join(work, "draft.pdf")
        if proc.returncode != 0 or not os.path.exists(out):
            raise RenderUnavailable("LibreOffice 未能转成 PDF")
        with open(out, "rb") as fh:
            return fh.read()
    except subprocess.TimeoutExpired as exc:
        raise RenderUnavailable("版式渲染超时") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    try:
        return _convert_via_service(docx_bytes)
    except ConnectionError:
        return _convert_via_local_soffice(docx_bytes)


def pdf_page_count(pdf_bytes: bytes) -> int:
    import pymupdf as fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        return int(pdf.page_count or 0)


def render_docx(draft_id: str, docx_bytes: bytes) -> dict:
    """渲染并缓存。返回 {hash, pages, cached, ms}。"""
    key = docx_fingerprint(docx_bytes)
    path = _pdf_path(draft_id, key)
    started = time.time()
    if os.path.exists(path):
        os.utime(path, None)
        with open(path, "rb") as fh:
            pages = pdf_page_count(fh.read())
        return {"hash": key, "pages": pages, "cached": True, "ms": int((time.time() - started) * 1000)}
    pdf = convert_docx_to_pdf(docx_bytes)
    pages = pdf_page_count(pdf)
    if pages < 1:
        raise RenderUnavailable("渲染结果没有页面")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(pdf)
    os.replace(tmp, path)
    _prune(draft_id)
    return {"hash": key, "pages": pages, "cached": False, "ms": int((time.time() - started) * 1000)}


def render_page_png(draft_id: str, key: str, page: int) -> bytes:
    """取缓存里 PDF 的第 page 页（从 1 起）。缓存不存在抛 FileNotFoundError。"""
    import pymupdf as fitz

    path = _pdf_path(draft_id, key)
    if not os.path.exists(path):
        raise FileNotFoundError(key)
    with fitz.open(path) as pdf:
        total = int(pdf.page_count or 0)
        if total < 1:
            raise FileNotFoundError(key)
        index = max(1, min(page, total)) - 1
        pix = pdf[index].get_pixmap(matrix=fitz.Matrix(_PNG_ZOOM, _PNG_ZOOM), alpha=False)
        return pix.tobytes("png")
