"""预审原文包：按文档顺序抽出全部正文、表格文字与内嵌原图。

不替代 docx_extract.extract_paragraphs（版式/修改闭环仍用旧行为）。
空段落里的图不再丢掉；解不出的矢量图仍留【附图N】占位，避免假装没图。
"""

from __future__ import annotations

import io
import logging
import os
import re

logger = logging.getLogger(__name__)

MIN_BLOB = 2048
MIN_SIDE = 48
JPEG_MAX_SIDE = 1024
JPEG_QUALITY = 75
PDF_SPARSE_CHARS = 80

_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、")
_CN_PAREN = re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]")
_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)")
_ATTACH = re.compile(r"^附件[0-9一二三四五六七八九十]")
_MARKER = re.compile(r"【附图(\d+)")


def marker_for(seq: int, heading: str, decoded: bool = True) -> str:
    head = (heading or "未标注章节").strip()[:40]
    if decoded:
        return f"【附图{seq}：{head}】"
    return f"【附图{seq}：{head}｜未能解码】"


def seqs_in_text(text: str) -> set[int]:
    return {int(m.group(1)) for m in _MARKER.finditer(text or "")}


def filter_pack_for_paragraphs(paragraphs: list[dict], images: list[dict]) -> tuple[list[dict], list[dict]]:
    """合订切册后只保留本册段落里出现的附图。"""
    blob = "\n".join((p.get("text") or "") for p in (paragraphs or []) if isinstance(p, dict))
    keep = seqs_in_text(blob)
    kept_images = [img for img in (images or []) if int(img.get("seq") or 0) in keep]
    return paragraphs, kept_images


def extract_review_pack(path: str) -> dict:
    """返回 {paragraphs, images, full_text, table_rows, image_count}。"""
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".pdf":
        pack = _extract_pdf_pack(path)
    else:
        pack = _extract_docx_pack(path)
    paras = pack.get("paragraphs") or []
    images = pack.get("images") or []
    text = "\n".join((p.get("text") or "") for p in paras if p.get("text"))
    table_rows = sum(1 for p in paras if p.get("fromTable"))
    logger.info(
        "review pack: paras=%s tables=%s images=%s chars=%s",
        len(paras),
        table_rows,
        len(images),
        len(text),
    )
    return {
        "paragraphs": paras,
        "images": images,
        "full_text": text,
        "table_rows": table_rows,
        "image_count": len(images),
    }


def _is_heading_text(text: str, style: str = "", outline_level=None) -> bool:
    raw = (text or "").strip()
    if style and str(style).lower().startswith("heading"):
        return True
    if isinstance(outline_level, int) and 0 <= outline_level <= 8:
        return True
    if not raw or len(raw) > 48 or "。" in raw:
        return False
    return bool(
        _CHAPTER.match(raw)
        or _CN_DOT.match(raw)
        or _CN_PAREN.match(raw)
        or _DOTTED.match(raw)
        or _ATTACH.match(raw)
    )


def _ext_from_ctype(ctype: str) -> str:
    content_type = (ctype or "").lower()
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    return ".png"


def _blip_raw(element, document) -> list[tuple[bytes, str, bool]]:
    """(blob, ext, vector_skipped). vector_skipped 表示 wmf/emf 无法送视觉。"""
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out: list[tuple[bytes, str, bool]] = []
    seen: set[str] = set()
    for blip in element.findall(f".//{ns}blip"):
        embed = blip.get(f"{rns}embed")
        if not embed or embed in seen:
            continue
        seen.add(embed)
        try:
            part = document.part.related_parts[embed]
            blob = part.blob
            ctype = (part.content_type or "").lower()
        except Exception:
            continue
        if not blob:
            continue
        if "wmf" in ctype or "emf" in ctype:
            out.append((blob or b"", ".wmf", True))
            continue
        if len(blob) < MIN_BLOB:
            continue
        out.append((blob, _ext_from_ctype(ctype), False))
    return out


def _decode_blob(blob: bytes) -> dict:
    """原图像素与送审 JPEG。分辨率按原始宽高计，不按压缩后的 1024 边。"""
    info = {"jpeg": None, "width": 0, "height": 0, "dpi": 0}
    if not blob:
        return info
    try:
        from PIL import Image

        from .ocr import image_to_jpeg_bytes

        with Image.open(io.BytesIO(blob)) as img:
            img.load()
            w, h = img.size
            info["width"], info["height"] = int(w), int(h)
            dpi_info = img.info.get("dpi")
            if isinstance(dpi_info, (tuple, list)) and dpi_info:
                try:
                    info["dpi"] = int(float(dpi_info[0] or 0))
                except (TypeError, ValueError):
                    info["dpi"] = 0
            elif isinstance(dpi_info, (int, float)):
                info["dpi"] = int(dpi_info)
            if min(w, h) < MIN_SIDE:
                return info
            if img.mode not in ("RGB", "L"):
                work = img.convert("RGB")
            else:
                work = img
            info["jpeg"] = image_to_jpeg_bytes(work, quality=JPEG_QUALITY, max_side=JPEG_MAX_SIDE)
    except Exception:
        return info
    return info


def _to_jpeg(blob: bytes) -> bytes | None:
    return _decode_blob(blob).get("jpeg")


def _para_base(idx: int, text: str, *, style: str = "", outline_level=None, from_table: bool = False, **extra) -> dict:
    item = {
        "index": idx,
        "text": text,
        "style": style,
        "outline_level": outline_level,
        "align": "",
        "font": "宋体",
        "fontSizePt": 12.0,
        "bold": False,
        "fromTable": from_table,
        "isHeading": _is_heading_text(text, style, outline_level),
        "isImage": False,
    }
    item.update(extra)
    return item


def _extract_docx_pack(path: str) -> dict:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from .docx_extract import _para_dict, _table_row_texts

    document = docx.Document(path)
    paragraphs: list[dict] = []
    images: list[dict] = []
    idx = 0
    seq = 0
    heading = "开篇"

    def push_images(element, *, from_table: bool) -> None:
        nonlocal idx, seq
        for blob, _ext, vector in _blip_raw(element, document):
            seq += 1
            info = {"jpeg": None, "width": 0, "height": 0, "dpi": 0} if vector else _decode_blob(blob)
            if vector and blob:
                probed = _decode_blob(blob)
                info["width"] = probed.get("width") or 0
                info["height"] = probed.get("height") or 0
                info["dpi"] = probed.get("dpi") or 0
            decoded = bool(info.get("jpeg"))
            mark = marker_for(seq, heading, decoded=decoded)
            paragraphs.append(
                _para_base(
                    idx,
                    mark,
                    from_table=from_table,
                    isImage=True,
                    imageSeq=seq,
                )
            )
            idx += 1
            images.append(
                {
                    "seq": seq,
                    "heading": heading,
                    "marker": mark,
                    "jpeg": info.get("jpeg"),
                    "decoded": decoded,
                    "width": info.get("width") or 0,
                    "height": info.get("height") or 0,
                    "dpi": info.get("dpi") or 0,
                    "fromTable": from_table,
                    "vector": vector,
                }
            )

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, document)
            item = _para_dict(para, idx, False)
            if item:
                item["isHeading"] = _is_heading_text(item.get("text") or "", item.get("style") or "", item.get("outline_level"))
                item["isImage"] = False
                if item["isHeading"]:
                    heading = (item.get("text") or heading)[:40]
                paragraphs.append(item)
                idx += 1
            push_images(child, from_table=False)
            continue
        if child.tag != qn("w:tbl"):
            continue
        table = Table(child, document)
        rows = _table_row_texts(table)
        if not rows:
            paragraphs.append(_para_base(idx, "【表格（无文字单元格）】", from_table=True))
            idx += 1
        else:
            for row_text in rows:
                paragraphs.append(_para_base(idx, row_text, from_table=True))
                idx += 1
        push_images(child, from_table=True)
    return {"paragraphs": paragraphs, "images": images}


def _extract_pdf_pack(path: str) -> dict:
    import pymupdf as fitz

    from .ocr import image_to_jpeg_bytes, pixmap_to_image

    paragraphs: list[dict] = []
    images: list[dict] = []
    idx = 0
    seq = 0
    heading = "开篇"
    seen_xref: set[tuple[int, int]] = set()

    def push_jpeg(jpeg: bytes | None, label: str, decoded: bool, *, width: int = 0, height: int = 0, dpi: int = 0) -> None:
        nonlocal idx, seq
        seq += 1
        mark = marker_for(seq, label, decoded=decoded and bool(jpeg))
        paragraphs.append(_para_base(idx, mark, isImage=True, imageSeq=seq))
        idx += 1
        images.append(
            {
                "seq": seq,
                "heading": label,
                "marker": mark,
                "jpeg": jpeg if decoded else None,
                "decoded": bool(decoded and jpeg),
                "width": width,
                "height": height,
                "dpi": dpi,
                "fromTable": False,
                "vector": False,
            }
        )

    with fitz.open(path) as doc:
        for page_i, page in enumerate(doc, start=1):
            label = f"第{page_i}页"
            text = (page.get_text() or "").strip()
            table_lines: list[str] = []
            try:
                found = page.find_tables()
                for table in found.tables if found else []:
                    for row in table.extract() or []:
                        cells = [" ".join(str(c).split()) for c in row if c and str(c).strip()]
                        if cells:
                            table_lines.append(" | ".join(cells))
            except Exception:
                table_lines = []
            for line in (text.splitlines() if text else []):
                raw = line.strip()
                if not raw:
                    continue
                item = _para_base(idx, raw)
                if item["isHeading"]:
                    heading = raw[:40]
                    label = heading
                paragraphs.append(item)
                idx += 1
            for row_text in table_lines:
                if row_text and row_text[:60] not in (text or ""):
                    paragraphs.append(_para_base(idx, row_text, from_table=True))
                    idx += 1
            page_images = 0
            for img in page.get_images(full=True) or []:
                xref = int(img[0])
                key = (page_i, xref)
                if key in seen_xref:
                    continue
                seen_xref.add(key)
                try:
                    extracted = doc.extract_image(xref)
                    blob = extracted.get("image") or b""
                except Exception:
                    blob = b""
                info = _decode_blob(blob) if blob else {"jpeg": None, "width": 0, "height": 0, "dpi": 0}
                jpeg = info.get("jpeg")
                if jpeg:
                    push_jpeg(
                        jpeg,
                        label,
                        True,
                        width=info.get("width") or 0,
                        height=info.get("height") or 0,
                        dpi=info.get("dpi") or 0,
                    )
                    page_images += 1
                elif blob:
                    push_jpeg(
                        None,
                        label,
                        False,
                        width=info.get("width") or 0,
                        height=info.get("height") or 0,
                        dpi=info.get("dpi") or 0,
                    )
                    page_images += 1
            if len(text) < PDF_SPARSE_CHARS and page_images == 0:
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                    img = pixmap_to_image(pix)
                    jpeg = image_to_jpeg_bytes(img, quality=JPEG_QUALITY, max_side=JPEG_MAX_SIDE)
                    push_jpeg(jpeg, label, True, width=int(pix.width or 0), height=int(pix.height or 0), dpi=115)
                except Exception:
                    push_jpeg(None, label, False)
    return {"paragraphs": paragraphs, "images": images}
