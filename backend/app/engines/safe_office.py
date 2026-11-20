"""Office/压缩包上传的安全检查与安全 XML 解析。

docx/xlsx/pptx 本质是 zip：解压炸弹（几百 KB 解出几十 GB）会把 worker 内存打满；
XML 里的外部实体会读本机文件或发起内网请求。统一在这里拦。
"""

from __future__ import annotations

import io
import zipfile

from lxml import etree

MAX_UNCOMPRESSED = 1024 * 1024 * 1024  # 解压后总大小 1 GB
MAX_ENTRIES = 20000
MAX_RATIO = 200  # 单个条目压缩比上限
RATIO_MIN_SIZE = 10 * 1024 * 1024  # 小于 10 MB 的条目不看压缩比，纯文本 XML 压缩比天然很高

ZIP_EXTS = {".docx", ".xlsx", ".pptx", ".zip", ".docm", ".xlsm"}

SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def safe_fromstring(data: bytes | str):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return etree.fromstring(data, parser=SAFE_PARSER)


class UnsafeArchive(ValueError):
    pass


def check_zip_bytes(content: bytes) -> None:
    """不合格抛 UnsafeArchive；不是 zip 的内容直接放过，交给后续解析报错。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise UnsafeArchive("压缩包内文件数量异常")
        total = 0
        for info in infos:
            total += info.file_size
            if total > MAX_UNCOMPRESSED:
                raise UnsafeArchive("文件解压后体积异常（疑似解压炸弹）")
            if info.file_size >= RATIO_MIN_SIZE and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise UnsafeArchive("文件压缩比异常（疑似解压炸弹）")
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise UnsafeArchive("压缩包内含非法路径")


def check_upload(content: bytes, ext: str) -> None:
    """上传接口调用：office/zip 类做解压检查，失败转成 400。"""
    if (ext or "").lower() not in ZIP_EXTS:
        return
    from fastapi import HTTPException

    try:
        check_zip_bytes(content)
    except UnsafeArchive as exc:
        raise HTTPException(400, f"{exc}，已拒绝上传") from exc
