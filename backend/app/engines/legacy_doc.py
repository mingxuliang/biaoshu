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


def looks_like_docx_zip(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4).startswith(b"PK")
    except OSError:
        return False


def convert_doc_to_docx(path: str) -> str:
    binary = _soffice_bin()
    if not binary:
        raise DocConvertError("当前环境无法转换 .doc，请安装 LibreOffice，或另存为 .docx 后再上传")
    out_dir = tempfile.mkdtemp(prefix="doc2docx-")
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
                "docx",
                "--outdir",
                out_dir,
                os.path.abspath(path),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        matches = glob.glob(os.path.join(out_dir, "*.docx"))
        if proc.returncode != 0 or not matches:
            err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[:400]
            raise DocConvertError(err or "LibreOffice 未能将 .doc 转为 .docx")
        return matches[0]
    except subprocess.TimeoutExpired as exc:
        raise DocConvertError(".doc 转换超时") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)


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
