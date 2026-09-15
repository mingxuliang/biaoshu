"""施工图纸抽取：仅从 PDF / 图片中提炼「设计说明」，支持多页。

不识读图面内容，不提取图号、尺寸、材料；图纸中的 GB/国标是设计标准，不作为字段抽取。
"""

from __future__ import annotations

import logging
import os
import re

from . import ocr

logger = logging.getLogger(__name__)

MAX_SCAN_PAGES = 120
MAX_OCR_PAGES = 25
MAX_NOTES_CHARS = 12_000

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

LABEL_FILES = "图纸文件"
LABEL_NOTES = "设计说明"

_NOTE_KEYS = ("设计说明", "设计总说明", "图纸设计说明", "编制说明")
_GB_CODE_RE = re.compile(
    r"(?:GB/?T?|GBJ|CJJ/?T?|JTG/?[A-Z]?|JGJ/?T?|JTJ|SL/?T?|NB/T|DL/T|TB/?T?)\s*[\d.\-—–]+",
    re.I,
)


def analyze_drawings(files: list[dict]) -> dict:
    """files: [{path, filename}]. 只返回设计说明。"""
    if not files:
        return {}
    notes_chunks: list[str] = []
    locations: list[str] = []
    skipped_over_cap = 0
    ocr_unavailable = False
    scanned_pages = 0

    for item in files:
        path = item.get("path") or ""
        name = item.get("filename") or os.path.basename(path) or "未命名"
        if not path or not os.path.exists(path):
            locations.append(f"{name}（文件不存在）")
            continue
        ext = os.path.splitext(name or path)[1].lower()
        locations.append(name)
        if ext == ".pdf":
            info = _analyze_pdf(path, name)
        elif ext in IMAGE_EXTS:
            info = _analyze_image(path, name)
        else:
            info = {
                "notes": [],
                "scanned": 0,
                "skipped": 0,
                "ocr_unavailable": False,
            }
        notes_chunks.extend(info["notes"])
        scanned_pages += info["scanned"]
        skipped_over_cap += info["skipped"]
        ocr_unavailable = ocr_unavailable or info["ocr_unavailable"]

    notes = _join_capped(notes_chunks, MAX_NOTES_CHARS)
    if not notes and locations:
        if ocr_unavailable:
            notes = "已上传施工图纸，当前环境未启用 OCR，未能识别设计说明。"
        else:
            notes = "已扫描图纸，未定位到「设计说明」页。"

    qd: dict[str, str] = {
        LABEL_FILES: "；".join(locations),
        LABEL_NOTES: notes,
    }
    return {"qty-drawing": {"qd-1": qd}}


def merge_drawing_fills(base: dict, intel: dict) -> dict:
    """设计说明覆盖文件名占位；空串不冲掉已有内容。"""
    out = dict(base or {})
    intel_qd = ((intel or {}).get("qty-drawing") or {}).get("qd-1") or {}
    if not intel_qd:
        return out
    slot = out.setdefault("qty-drawing", {}).setdefault("qd-1", {})
    for key, value in intel_qd.items():
        text = (value or "").strip()
        if not text:
            continue
        old = (slot.get(key) or "").strip()
        if not old or old.startswith("已上传施工图纸"):
            slot[key] = text
        elif key == LABEL_NOTES:
            slot[key] = text
        elif key == LABEL_FILES:
            slot[key] = text
        elif text not in old:
            slot[key] = old + "\n\n" + text
    return out


def _analyze_pdf(path: str, filename: str) -> dict:
    try:
        import pymupdf as fitz
    except ImportError:
        return {"notes": [], "scanned": 0, "skipped": 0, "ocr_unavailable": True}

    notes: list[str] = []
    skipped = 0
    ocr_unavail = False
    scanned = 0
    ocr_used = 0
    continue_notes = False
    try:
        with fitz.open(path) as doc:
            total = len(doc)
            limit = min(total, MAX_SCAN_PAGES)
            skipped = max(0, total - limit)
            for i in range(limit):
                scanned += 1
                page = doc[i]
                native = (page.get_text("text") or "").strip()
                page_text = native
                need_ocr = len(native) < 80 and ocr_used < MAX_OCR_PAGES
                if need_ocr:
                    try:
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
                        img = ocr.pixmap_to_image(pix)
                    except Exception:
                        img = None
                    if img is not None:
                        ocr_text, status = ocr.ocr_pil_image(img)
                        ocr_used += 1
                        if status == ocr.STATUS_UNAVAILABLE:
                            ocr_unavail = True
                        elif ocr_text:
                            page_text = ocr_text
                cleaned = _strip_gb_standards(page_text)
                if _is_gb_standard_page(page_text):
                    continue_notes = False
                    continue
                is_notes = _looks_like_notes(cleaned)
                if is_notes or (continue_notes and _is_notes_continuation(cleaned)):
                    notes.append(f"【{filename} 第{i + 1}页】\n{cleaned[:4000]}")
                    continue_notes = True
                else:
                    continue_notes = False
    except Exception:
        logger.exception("drawing pdf analyze failed: %s", filename)
    return {
        "notes": notes,
        "scanned": scanned,
        "skipped": skipped,
        "ocr_unavailable": ocr_unavail,
    }


def _analyze_image(path: str, filename: str) -> dict:
    notes: list[str] = []
    ocr_unavail = False
    scanned = 0
    continue_notes = False
    try:
        from PIL import Image

        img = Image.open(path)
        n = getattr(img, "n_frames", 1) or 1
        for i in range(n):
            scanned += 1
            if n > 1:
                img.seek(i)
            frame = img.convert("RGB")
            page_text, status = ocr.ocr_pil_image(frame)
            if status == ocr.STATUS_UNAVAILABLE:
                ocr_unavail = True
            cleaned = _strip_gb_standards(page_text)
            if _is_gb_standard_page(page_text):
                continue_notes = False
                continue
            is_notes = _looks_like_notes(cleaned)
            if is_notes or (continue_notes and _is_notes_continuation(cleaned)):
                label = f"【{filename}】" if n == 1 else f"【{filename} 第{i + 1}页】"
                notes.append(f"{label}\n{cleaned[:4000]}")
                continue_notes = True
            else:
                continue_notes = False
    except Exception:
        logger.exception("drawing image analyze failed: %s", filename)
        return {"notes": [], "scanned": scanned, "skipped": 0, "ocr_unavailable": ocr_unavail}
    return {
        "notes": notes,
        "scanned": scanned,
        "skipped": 0,
        "ocr_unavailable": ocr_unavail,
    }


def _looks_like_notes(text: str) -> bool:
    sample = (text or "").strip()
    if len(sample) < 40:
        return False
    head = sample[:1200]
    return any(k in head for k in _NOTE_KEYS)


def _is_notes_continuation(text: str) -> bool:
    """设计说明常跨多页：上一页已是说明时，后续段落页继续收录，图面页停止。"""
    sample = (text or "").strip()
    if len(sample) < 80:
        return False
    if _is_gb_standard_page(sample):
        return False
    if re.search(r"(?:图号|图名)\s*[:：]", sample[:400]) and len(sample) < 600:
        return False
    return True


def _is_gb_standard_page(text: str) -> bool:
    sample = text or ""
    hits = _GB_CODE_RE.findall(sample)
    if len(hits) < 4:
        return False
    compact = re.sub(r"\s+", "", sample)
    if not compact:
        return False
    codes = re.sub(r"\s+", "", "".join(hits))
    return len(codes) * 2 >= len(compact) * 0.35 or (len(hits) >= 8 and not any(k in sample[:800] for k in _NOTE_KEYS))


def _strip_gb_standards(text: str) -> str:
    """去掉图纸里成段罗列的 GB/国标设计标准，保留设计说明叙述。"""
    if not text:
        return ""
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            kept.append("")
            continue
        compact = re.sub(r"\s+", "", line)
        codes = _GB_CODE_RE.findall(line)
        if codes and len(re.sub(r"\s+", "", "".join(codes))) >= max(8, int(len(compact) * 0.5)):
            continue
        if compact in {"国标", "国家标准", "设计标准"} or compact.startswith(("执行规范", "引用标准", "标准图集")):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _join_capped(items: list[str], cap: int) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = (item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    blob = "\n\n".join(out).strip()
    if len(blob) <= cap:
        return blob
    return blob[: cap - 1].rstrip() + "…"
