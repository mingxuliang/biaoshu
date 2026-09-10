"""施工图纸识读：设计说明 / 图签目录 / 代表性图面视觉，写入工程类 qty-drawing。

不把整卷图纸灌进 E0 招标条款抽取。看不清的字段保持空，禁止编造。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from collections import defaultdict

from . import ocr
from .llm import LlmError, chat_complete, get_vision_model_id, is_vision_model, resolve_llm

logger = logging.getLogger(__name__)

MAX_SCAN_PAGES = 80
MAX_FULL_OCR_PAGES = 10
MAX_VISION_SHEETS = 8
MAX_NOTES_CHARS = 12_000
VISION_MAX_SIDE = 1600
VISION_BATCH = 2

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

LABEL_LOCATION = "图纸章节位置与图号图名"
LABEL_CATALOG = "图纸目录（图号 / 图名 / 专业 / 比例 / 页码）"
LABEL_NOTES = "设计说明与施工要点"
LABEL_WORKS = "主要工程内容与结构形式"
LABEL_DIMS = "关键尺寸、材料与图面注记"
LABEL_CONFLICT = "图纸与技术标准冲突时的处理原则"
LABEL_SCOPE = "解读范围说明（读了哪些页、哪些页未送视觉）"

_NOTE_KEYS = ("设计说明", "施工说明", "编制说明", "总说明", "设计概况", "工程概况", "施工要求")
_CATALOG_KEYS = ("图纸目录", "图号", "图名")
_CONFLICT_KEYS = ("冲突", "不一致", "以图纸为准", "以清单为准", "以设计为准")

_DISCIPLINE = (
    ("田间", "田间工程"),
    ("灌溉", "灌溉"),
    ("排水", "排水"),
    ("沟渠", "沟渠"),
    ("道路", "道路"),
    ("桥梁", "桥梁"),
    ("泵站", "泵站"),
    ("培肥", "土壤培肥"),
    ("结构", "结构"),
    ("建筑", "建筑"),
    ("给排水", "给排水"),
    ("电气", "电气"),
    ("总平", "总平面"),
    ("平面", "平面"),
    ("大样", "大样"),
    ("剖面", "剖面"),
)

_VISION_SYSTEM = """你是工程图纸识读助手。只根据图面可见内容作答，禁止编造看不清的尺寸、材料或工程量。
只返回 JSON，不要其它说明：
{
  "number": "图号，看不清则空",
  "name": "图名，看不清则空",
  "discipline": "专业，看不清则空",
  "scale": "比例，看不清则空",
  "works": "本图可见的主要工程内容与结构/断面形式，看不清则空",
  "dimensions": "本图能看清的关键尺寸、材料、图例或注记，看不清则空",
  "notes": "本图可见的施工说明/注意要点，没有则空",
  "conflict": "本图可见的图纸与清单/技术标准冲突处理原则，没有则空"
}
"""


def analyze_drawings(files: list[dict]) -> dict:
    """files: [{path, filename}]. 返回 qty-drawing extra_fills。"""
    if not files:
        return {}
    catalog: list[str] = []
    notes_chunks: list[str] = []
    conflict_bits: list[str] = []
    locations: list[str] = []
    sheet_candidates: list[dict] = []
    scanned_pages = 0
    skipped_over_cap = 0
    ocr_unavailable = False

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
            info = _analyze_other(path, name)
        catalog.extend(info["catalog"])
        notes_chunks.extend(info["notes"])
        conflict_bits.extend(info["conflict"])
        sheet_candidates.extend(info["sheets"])
        scanned_pages += info["scanned"]
        skipped_over_cap += info["skipped"]
        ocr_unavailable = ocr_unavailable or info["ocr_unavailable"]

    vision_id = get_vision_model_id()
    vision_ok = bool(vision_id and is_vision_model(vision_id))
    vision_label = vision_id or ""
    if vision_id:
        try:
            vision_label = resolve_llm(vision_id).api_model or vision_id
        except LlmError:
            vision_label = vision_id
    selected = _pick_vision_sheets(sheet_candidates)
    vision_pages: list[str] = []
    works: list[str] = []
    dims: list[str] = []
    extra_notes: list[str] = []
    extra_conflict: list[str] = []
    extra_catalog: list[str] = []
    vision_error = ""

    if vision_ok and selected:
        logger.info("drawing vision using %s on %s sheets", vision_label, len(selected))
        v = _run_vision(vision_id, selected)
        works = v["works"]
        dims = v["dims"]
        extra_notes = v["notes"]
        extra_conflict = v["conflict"]
        extra_catalog = v["catalog"]
        vision_pages = v["pages"]
        vision_error = v.get("error") or ""
        catalog.extend(extra_catalog)
    elif selected and not vision_ok:
        vision_pages = []
        vision_error = "未配置可用的视觉模型（需 DeepSeek Vision 等看图模型）"

    catalog = _uniq(catalog)
    notes = _join_capped(notes_chunks + extra_notes, MAX_NOTES_CHARS)
    works_text = _join_capped(works, 4000)
    dims_text = _join_capped(dims, 4000)
    conflict = _join_capped(conflict_bits + extra_conflict, 1500)
    if not conflict:
        conflict = _snippet_conflict("\n".join(notes_chunks))

    scope = _scope_text(
        files=files,
        scanned_pages=scanned_pages,
        skipped_over_cap=skipped_over_cap,
        catalog_n=len(catalog),
        notes_n=len(notes_chunks),
        vision_pages=vision_pages,
        vision_ok=vision_ok,
        vision_id=vision_label,
        vision_error=vision_error,
        ocr_unavailable=ocr_unavailable,
        selected_n=len(selected),
    )

    qd: dict[str, str] = {
        LABEL_LOCATION: "；".join(locations),
        LABEL_CATALOG: "\n".join(catalog),
        LABEL_NOTES: notes,
        LABEL_WORKS: works_text,
        LABEL_DIMS: dims_text,
        LABEL_CONFLICT: conflict,
        LABEL_SCOPE: scope,
    }
    return {"qty-drawing": {"qd-1": qd}}


def merge_drawing_fills(base: dict, intel: dict) -> dict:
    """图纸识读覆盖文件名占位；空串不冲掉已有实质内容。"""
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
        elif key == LABEL_LOCATION and text and old.startswith("已上传"):
            slot[key] = text
        elif key in (LABEL_CATALOG, LABEL_NOTES, LABEL_WORKS, LABEL_DIMS, LABEL_SCOPE):
            slot[key] = text
        elif text not in old:
            slot[key] = old + "\n\n" + text
    return out


def _analyze_pdf(path: str, filename: str) -> dict:
    try:
        import pymupdf as fitz
    except ImportError:
        return _empty_info(ocr_unavailable=True)

    catalog: list[str] = []
    notes: list[str] = []
    conflict: list[str] = []
    sheets: list[dict] = []
    skipped = 0
    ocr_unavail = False
    scanned = 0
    try:
        with fitz.open(path) as doc:
            total = len(doc)
            limit = min(total, MAX_SCAN_PAGES)
            skipped = max(0, total - limit)
            for i in range(limit):
                scanned += 1
                page = doc[i]
                native = (page.get_text("text") or "").strip()
                role = _classify(native)
                img = None
                page_text = native
                need_full = i < MAX_FULL_OCR_PAGES or role in ("notes", "catalog") or len(native) < 80
                if need_full:
                    try:
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
                        img = ocr.pixmap_to_image(pix)
                    except Exception:
                        img = None
                elif role == "sheet":
                    img = _title_block_image(page)
                if img is not None and (i < MAX_FULL_OCR_PAGES or role in ("notes", "catalog")) and len(native) < 80:
                    ocr_text, status = ocr.ocr_pil_image(img)
                    if status == ocr.STATUS_UNAVAILABLE:
                        ocr_unavail = True
                    elif ocr_text:
                        page_text = ocr_text
                        role = _classify(page_text)
                title_text = ""
                if img is not None and role == "sheet":
                    if need_full:
                        title_text, status = ocr.ocr_region(img)
                    else:
                        title_text, status = ocr.ocr_pil_image(img)
                    if status == ocr.STATUS_UNAVAILABLE:
                        ocr_unavail = True
                entry = _catalog_line(filename, i + 1, page_text, title_text)
                if role == "catalog":
                    catalog.extend(_catalog_lines_from_text(filename, i + 1, page_text))
                    if entry:
                        catalog.append(entry)
                elif entry:
                    catalog.append(entry)
                if role == "notes" or _looks_like_notes(page_text):
                    notes.append(f"【{filename} 第{i + 1}页】\n{page_text[:4000]}")
                    bit = _snippet_conflict(page_text)
                    if bit:
                        conflict.append(bit)
                if role == "sheet":
                    sheets.append(
                        {
                            "filename": filename,
                            "path": path,
                            "page": i,
                            "page_human": i + 1,
                            "title": title_text or page_text[:200],
                            "discipline": _discipline_of(title_text or page_text or filename),
                        }
                    )
    except Exception:
        logger.exception("drawing pdf analyze failed: %s", filename)
    return {
        "catalog": _uniq(catalog),
        "notes": notes,
        "conflict": conflict,
        "sheets": sheets,
        "scanned": scanned,
        "skipped": skipped,
        "ocr_unavailable": ocr_unavail,
    }


def _title_block_image(page):
    try:
        import pymupdf as fitz
    except ImportError:
        return None
    try:
        rect = page.rect
        left, top, right, bottom = ocr.TITLE_BLOCK_BOX
        clip = fitz.Rect(
            rect.x0 + rect.width * left,
            rect.y0 + rect.height * top,
            rect.x0 + rect.width * right,
            rect.y0 + rect.height * bottom,
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), clip=clip, alpha=False)
        return ocr.pixmap_to_image(pix)
    except Exception:
        return None


def _analyze_image(path: str, filename: str) -> dict:
    img = ocr.load_image_file(path)
    ocr_unavail = False
    page_text = ""
    title_text = ""
    if img is not None:
        page_text, status = ocr.ocr_pil_image(img)
        if status == ocr.STATUS_UNAVAILABLE:
            ocr_unavail = True
        title_text, status2 = ocr.ocr_region(img)
        if status2 == ocr.STATUS_UNAVAILABLE:
            ocr_unavail = True
    role = _classify(page_text or title_text)
    catalog = []
    notes = []
    conflict = []
    sheets = []
    entry = _catalog_line(filename, 1, page_text, title_text)
    if entry:
        catalog.append(entry)
    if role == "notes" or _looks_like_notes(page_text):
        if page_text:
            notes.append(f"【{filename}】\n{page_text[:4000]}")
        bit = _snippet_conflict(page_text)
        if bit:
            conflict.append(bit)
    sheets.append(
        {
            "filename": filename,
            "path": path,
            "page": 0,
            "page_human": 1,
            "title": title_text or page_text[:200],
            "discipline": _discipline_of(title_text or page_text or filename),
            "image_path": path,
        }
    )
    return {
        "catalog": catalog,
        "notes": notes,
        "conflict": conflict,
        "sheets": sheets,
        "scanned": 1,
        "skipped": 0,
        "ocr_unavailable": ocr_unavail,
    }


def _analyze_other(path: str, filename: str) -> dict:
    from .docx_extract import extract_full_text

    text = ""
    try:
        text = (extract_full_text(path) or "").strip()
    except Exception:
        text = ""
    notes = [f"【{filename}】\n{text[:4000]}"] if text else []
    catalog = [f"{filename}（非 PDF/图片，仅抽取可识别文字）"]
    bit = _snippet_conflict(text)
    return {
        "catalog": catalog,
        "notes": notes,
        "conflict": [bit] if bit else [],
        "sheets": [],
        "scanned": 1,
        "skipped": 0,
        "ocr_unavailable": False,
    }


def _empty_info(*, ocr_unavailable: bool = False) -> dict:
    return {
        "catalog": [],
        "notes": [],
        "conflict": [],
        "sheets": [],
        "scanned": 0,
        "skipped": 0,
        "ocr_unavailable": ocr_unavailable,
    }


def _classify(text: str) -> str:
    sample = (text or "").strip()
    if not sample:
        return "sheet"
    head = sample[:800]
    if any(k in head for k in _NOTE_KEYS) and len(sample) >= 80:
        return "notes"
    if "图纸目录" in head or (("图号" in head and "图名" in head) and ("目录" in head or sample.count("\n") >= 8)):
        return "catalog"
    if len(sample) >= 400 and any(k in sample for k in _NOTE_KEYS):
        return "notes"
    if len(sample) >= 600:
        return "notes"
    return "sheet"


def _looks_like_notes(text: str) -> bool:
    sample = text or ""
    return any(k in sample for k in _NOTE_KEYS) and len(sample) >= 60


def _discipline_of(text: str) -> str:
    sample = text or ""
    for key, label in _DISCIPLINE:
        if key in sample:
            return label
    return "其他"


def _catalog_line(filename: str, page: int, page_text: str, title_text: str) -> str:
    blob = f"{title_text}\n{page_text[:500]}"
    number = _find(r"(?:图号|图别)[:：\s]*([A-Za-z0-9\-–—\.]+)", blob) or _find(
        r"\b([A-Z]{1,4}[-–—]\d{1,4}(?:[-–—]\d{1,3})?)\b", blob
    )
    name = _find(r"(?:图名)[:：\s]*([^\n]{2,40})", blob)
    scale = _find(r"(?:比例)[:：\s]*(1\s*[:：]\s*\d+)", blob)
    disc = _discipline_of(blob or filename)
    parts = [f"P{page}", filename]
    if number:
        parts.append(f"图号 {number}")
    if name:
        parts.append(name.strip())
    if disc and disc != "其他":
        parts.append(f"专业:{disc}")
    if scale:
        parts.append(f"比例:{re.sub(r'\s+', '', scale)}")
    if number or name or scale:
        return "  ".join(parts)
    return ""


def _catalog_lines_from_text(filename: str, page: int, text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        if "图号" in line or re.search(r"[A-Z]{1,4}[-–—]\d+", line):
            lines.append(f"P{page} {filename}  {line[:80]}")
        if len(lines) >= 40:
            break
    return lines


def _find(pattern: str, text: str) -> str:
    m = re.search(pattern, text or "")
    return (m.group(1) or "").strip() if m else ""


def _pick_vision_sheets(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    by_disc: dict[str, list[dict]] = defaultdict(list)
    for item in candidates:
        by_disc[item.get("discipline") or "其他"].append(item)
    picked: list[dict] = []
    seen: set[tuple] = set()
    # 每专业最多 2 张，轮询直到满 8 张。
    while len(picked) < MAX_VISION_SHEETS:
        progressed = False
        for disc, items in by_disc.items():
            taken = sum(1 for p in picked if p.get("discipline") == disc)
            if taken >= 2:
                continue
            for item in items:
                key = (item.get("path"), item.get("page"), item.get("filename"))
                if key in seen:
                    continue
                seen.add(key)
                picked.append(item)
                progressed = True
                break
            if len(picked) >= MAX_VISION_SHEETS:
                break
        if not progressed:
            break
    return picked[:MAX_VISION_SHEETS]


def _run_vision(model_id: str, sheets: list[dict]) -> dict:
    works: list[str] = []
    dims: list[str] = []
    notes: list[str] = []
    conflict: list[str] = []
    catalog: list[str] = []
    pages: list[str] = []
    last_error = ""
    for i in range(0, len(sheets), VISION_BATCH):
        batch = sheets[i : i + VISION_BATCH]
        parts: list[dict] = [
            {
                "type": "text",
                "text": _VISION_SYSTEM
                + "\n以下是招标文件包中的施工图纸页。逐张识读可见施工信息。"
                "看不清的字段必须填空字符串。不要估算工程量。",
            }
        ]
        ready: list[dict] = []
        for sheet in batch:
            jpeg = _sheet_jpeg(sheet)
            if not jpeg:
                continue
            label = f"{sheet.get('filename')} 第{sheet.get('page_human')}页"
            parts.append({"type": "text", "text": f"\n【{label}】"})
            b64 = base64.b64encode(jpeg).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            ready.append(sheet)
        if not ready:
            continue
        try:
            # DeepSeek Vision 只允许在 user 消息里放图片，指令一并放进 user。
            raw = chat_complete(
                model_id=model_id,
                messages=[{"role": "user", "content": parts}],
                temperature=0.1,
                timeout=180,
                max_tokens=2048,
            )
        except LlmError as exc:
            last_error = str(exc)
            logger.exception("drawing vision failed")
            continue
        parsed_list = _parse_vision_payload(raw, len(ready))
        for sheet, data in zip(ready, parsed_list):
            label = f"{sheet.get('filename')} 第{sheet.get('page_human')}页"
            pages.append(label)
            number = (data.get("number") or "").strip()
            name = (data.get("name") or "").strip()
            disc = (data.get("discipline") or sheet.get("discipline") or "").strip()
            scale = (data.get("scale") or "").strip()
            bits = [label]
            if number:
                bits.append(f"图号 {number}")
            if name:
                bits.append(name)
            if disc:
                bits.append(f"专业:{disc}")
            if scale:
                bits.append(f"比例:{scale}")
            catalog.append("  ".join(bits))
            w = (data.get("works") or "").strip()
            d = (data.get("dimensions") or "").strip()
            n = (data.get("notes") or "").strip()
            c = (data.get("conflict") or "").strip()
            if w:
                works.append(f"{label}：{w}")
            if d:
                dims.append(f"{label}：{d}")
            if n:
                notes.append(f"{label}：{n}")
            if c:
                conflict.append(f"{label}：{c}")
    return {
        "works": works,
        "dims": dims,
        "notes": notes,
        "conflict": conflict,
        "catalog": catalog,
        "pages": pages,
        "error": last_error if not pages else "",
    }


def _sheet_jpeg(sheet: dict) -> bytes:
    image_path = sheet.get("image_path") or ""
    if image_path:
        img = ocr.load_image_file(image_path)
        if img is None:
            return b""
        return ocr.image_to_jpeg_bytes(img, max_side=VISION_MAX_SIDE)
    path = sheet.get("path") or ""
    page = int(sheet.get("page") or 0)
    img = ocr.raster_pdf_page(path, page, zoom=1.6)
    if img is None:
        return b""
    return ocr.image_to_jpeg_bytes(img, max_side=VISION_MAX_SIDE)


def _parse_vision_payload(raw: str, n: int) -> list[dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return [{} for _ in range(n)]
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return [{} for _ in range(n)]
    if isinstance(data, list):
        rows = [x if isinstance(x, dict) else {} for x in data]
    elif isinstance(data, dict):
        if any(k in data for k in ("works", "number", "name", "dimensions")):
            rows = [data]
        else:
            rows = [v for v in data.values() if isinstance(v, dict)] or [data]
    else:
        rows = []
    while len(rows) < n:
        rows.append({})
    return rows[:n]


def _snippet_conflict(text: str) -> str:
    if not text:
        return ""
    for key in _CONFLICT_KEYS:
        idx = text.find(key)
        if idx < 0:
            continue
        start = max(0, idx - 40)
        end = min(len(text), idx + 180)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if snippet:
            return snippet[:400]
    return ""


def _scope_text(
    *,
    files: list[dict],
    scanned_pages: int,
    skipped_over_cap: int,
    catalog_n: int,
    notes_n: int,
    vision_pages: list[str],
    vision_ok: bool,
    vision_id: str,
    vision_error: str,
    ocr_unavailable: bool,
    selected_n: int,
) -> str:
    names = "、".join((f.get("filename") or "未命名") for f in files)
    parts = [
        f"已识读文件：{names}。",
        f"扫描 {scanned_pages} 页" + (f"（另有 {skipped_over_cap} 页超出 {MAX_SCAN_PAGES} 页上限未扫描）" if skipped_over_cap else "") + "。",
        f"图签/目录条目 {catalog_n} 条，设计说明页 {notes_n} 页。",
    ]
    if vision_ok and vision_pages:
        used = vision_id or "vision"
        parts.append(f"视觉识读（{used}）：" + "；".join(vision_pages) + "。其余图面未送视觉。")
    elif selected_n and vision_error:
        parts.append(f"视觉识读失败：{vision_error}")
    elif selected_n and not vision_ok:
        parts.append("未配置可用的视觉模型（需 DeepSeek Vision 等看图模型），图面施工内容未解读，请到「模型配置」填写后重新解析。")
    elif not selected_n:
        parts.append("未选出代表性施工图页，图面视觉未执行。")
    if ocr_unavailable:
        parts.append("当前环境未启用 OCR，扫描件文字可能偏少。")
    parts.append("未读到的尺寸、材料与工程量保持空白，不编造。")
    return "".join(parts)


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = (item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _join_capped(items: list[str], cap: int) -> str:
    text = "\n\n".join(_uniq(items)).strip()
    if len(text) <= cap:
        return text
    return text[: cap - 1].rstrip() + "…"
