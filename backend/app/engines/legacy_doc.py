"""旧版 Word .doc：能当 zip/docx 的直接打开，否则用 LibreOffice 转成 .docx。"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator


class DocConvertError(RuntimeError):
    pass


def _soffice_bin() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_office(path: str, target: str) -> str:
    """LibreOffice 转成 docx 或 xlsx。返回新文件路径。"""
    if target not in {"docx", "xlsx"}:
        raise DocConvertError(f"不支持转到 {target}")
    binary = _soffice_bin()
    if not binary:
        raise DocConvertError(f"当前环境无法转换该文件，请安装 LibreOffice，或另存为 .{target} 后再上传")
    out_dir = tempfile.mkdtemp(prefix=f"lo2{target}-")
    profile = tempfile.mkdtemp(prefix="lo-profile-")
    profile_uri = "file:///" + profile.replace("\\", "/").lstrip("/")
    try:
        proc = subprocess.run(
            [
                binary,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--norestore",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                target,
                "--outdir",
                out_dir,
                os.path.abspath(path),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        matches = glob.glob(os.path.join(out_dir, f"*.{target}"))
        if proc.returncode != 0 or not matches:
            err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:400]
            raise DocConvertError(err or f"LibreOffice 未能转为 .{target}")
        return matches[0]
    except subprocess.TimeoutExpired as exc:
        raise DocConvertError("Office 文件转换超时") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def looks_like_docx_zip(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4).startswith(b"PK")
    except OSError:
        return False


def convert_doc_to_docx(path: str) -> str:
    return convert_office(path, "docx")


def convert_xls_to_xlsx(path: str) -> str:
    return convert_office(path, "xlsx")


@contextmanager
def as_docx(path: str) -> Iterator[str]:
    """产出 python-docx 可打开的路径；.doc 会转换，调用结束后删除转换文件。"""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".doc":
        yield path
        return
    if looks_like_docx_zip(path):
        yield path
        return
    converted = convert_doc_to_docx(path)
    try:
        yield converted
    finally:
        parent = os.path.dirname(converted)
        try:
            os.remove(converted)
        except OSError:
            pass
        shutil.rmtree(parent, ignore_errors=True)


@contextmanager
def as_xlsx(path: str) -> Iterator[str]:
    """产出可当 xlsx 打开的路径；.xls 会转换。"""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".xls":
        yield path
        return
    converted = convert_xls_to_xlsx(path)
    try:
        yield converted
    finally:
        parent = os.path.dirname(converted)
        try:
            os.remove(converted)
        except OSError:
            pass
        shutil.rmtree(parent, ignore_errors=True)
