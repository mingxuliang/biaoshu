"""从施工图图签、图面参数和施工说明提炼本标评审规则。

只打开和图名对得上的图纸。标准号以图上文字为准，最多检索 3 条已入库条文辅助识图。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re

from .llm import LlmError, chat_complete, get_vision_model_id
from .ocr import TITLE_BLOCK_BOX, ocr_region, raster_pdf_page
from .qty_boq import rows_from_dimensions
from .standard_review import search_clauses

logger = logging.getLogger(__name__)

MAX_SCAN_PAGES = 120
MAX_OPEN = 40
MAX_CLAUSES = 3
NOTES_BOX = (0.0, 0.55, 0.68, 1.0)
_SKIP_TITLES = {"目录", "签字", "签字栏", "图框", "封面", "会签"}
_STOP = {"工程", "施工", "图纸", "设计", "项目", "说明", "部分"}
_STD = re.compile(
    r"(?:GB/T|GB|JGJ/T|JGJ|JTG|CJJ/T|CJJ|SL|NY/T)\s*/?\s*\d+(?:\.\d+)?(?:-\d{4})?",
    re.I,
)
_DRAWING_NO = re.compile(r"图\s*号\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-]{3,})")
_BARE_NO = re.compile(r"\b([A-Z]{2,}[A-Z0-9]*(?:-[A-Z0-9]+){1,})\b")
_TITLE = re.compile(r"图\s*名\s*[:：]?\s*([^\n]{2,40})")
_WS = re.compile(r"\s+")

_VISION_SYSTEM = """你只阅读这张施工图的图面。
返回 JSON：{"parameters":"尺寸、材料、配筋、高程"}。
不要写标准号。施工说明里没有的标准号不要补充。
若同时给出条文摘录，只用于解释图面已有符号，不得据此编造图上没有的要求。
"""


def parse_title_block(text: str) -> dict:
    """从图签文字分出图号和图名。"""
    blob = text or ""
    number = ""
    found = _DRAWING_NO.search(blob)
    if found:
        number = found.group(1)
    else:
        bare = _BARE_NO.search(blob)
        if bare:
            number = bare.group(1)
    title = ""
    named = _TITLE.search(blob)
    if named:
        title = named.group(1).strip()
    else:
        for line in blob.splitlines():
            line = line.strip()
            if "图" not in line or "图号" in line or "图框" in line:
                continue
            if 4 <= len(line) <= 40:
                title = line
                break
    return {"drawingNo": number, "title": title}


def extract_standards(text: str) -> list[str]:
    """保留施工说明里的标准号，不去掉。"""
    found: list[str] = []
    seen: set[str] = set()
    for match in _STD.findall(text or ""):
        code = re.sub(r"\s+", "", match).upper()
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found[:8]


def notes_from_text(text: str) -> str:
    """留下说明栏、标注和带标准号的句子。"""
    lines: list[str] = []
    capture = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "说明" in line or line.startswith("注"):
            capture = True
        if capture or _STD.search(line) or "图集" in line:
            lines.append(line)
    return "\n".join(lines)[:800]


def _skip_title(title: str) -> bool:
    compact = _WS.sub("", title or "")
    return compact in _SKIP_TITLES or compact.startswith("目录")


def _overlaps(title: str, name: str) -> bool:
    title = title or ""
    name = (name or "").strip()
    if len(name) < 2 or _skip_title(title):
        return False
    if name in title or (len(title) >= 2 and title in name):
        return True
    for index in range(len(name) - 1):
        gram = name[index : index + 2]
        if gram in _STOP:
            continue
        if gram in title:
            return True
    return False


def select_sheets(index: list | None, names: list | None, limit: int = MAX_OPEN) -> list[dict]:
    """图名对得上技术点或清单名称才打开。目录、签字栏、图框不打开。"""
    picked: list[dict] = []
    seen: set[str] = set()
    for sheet in index or []:
        if not isinstance(sheet, dict):
            continue
        title = str(sheet.get("title") or "")
        if _skip_title(title):
            continue
        if not any(_overlaps(title, str(name or "")) for name in (names or [])):
            continue
        key = f"{sheet.get('drawingNo') or ''}|{title}|{sheet.get('page')}"
        if key in seen:
            continue
        seen.add(key)
        picked.append(sheet)
        if len(picked) >= limit:
            break
    return picked


def match_names(tech_rules: list | None, dimensions: list | None) -> list[str]:
    names: list[str] = []
    for rule in tech_rules or []:
        if isinstance(rule, dict):
            factor = str(rule.get("factor") or rule.get("name") or "").strip()
            if len(factor) >= 2:
                names.append(factor)
    for row in rows_from_dimensions(dimensions):
        if row.name and len(row.name.strip()) >= 2:
            names.append(row.name.strip())
    return names


def strip_invented_codes(parameters: str, allowed: list[str]) -> str:
    allowed_set = {re.sub(r"\s+", "", code).upper() for code in allowed}

    def repl(match: re.Match[str]) -> str:
        code = re.sub(r"\s+", "", match.group()).upper()
        return match.group() if code in allowed_set else ""

    return _WS.sub(" ", _STD.sub(repl, parameters or "")).strip()


def compose_rule(sheet: dict, notes: str, vision_parameters: str | None) -> dict:
    """无识图结果时保留施工说明，参数标成未识图。标准号只来自说明。"""
    title = str(sheet.get("title") or "").strip()[:40] or "施工图"
    standards = extract_standards(notes)
    raw_params = (vision_parameters or "").strip()
    if raw_params:
        parameters = strip_invented_codes(raw_params, standards)[:400]
    else:
        parameters = "未识图" if notes else ""
    return {
        "drawingNo": str(sheet.get("drawingNo") or "")[:40],
        "title": title,
        "parameters": parameters,
        "notes": (notes or "")[:800],
        "standards": standards,
        "chapter": str(sheet.get("chapter") or title)[:40],
        "axis": "合规性" if standards else "完整性",
        "page": sheet.get("page"),
    }


def merge_drawing_into_leaves(leaves: list | None, rules: list | None) -> list[dict]:
    """对得上的技术标叶子并入图面参数和施工说明，叶子仍保留。"""
    merged: list[dict] = []
    for raw in leaves or []:
        if not isinstance(raw, dict):
            continue
        leaf = dict(raw)
        factor = str(leaf.get("factor") or "")
        for rule in rules or []:
            if not isinstance(rule, dict) or not _overlaps(str(rule.get("title") or ""), factor):
                continue
            params = str(rule.get("parameters") or "")
            if params and params != "未识图" and params not in str(leaf.get("parameters") or ""):
                leaf["parameters"] = "；".join(
                    bit for bit in (str(leaf.get("parameters") or "").strip(), f"图纸{params}") if bit
                )[:400]
            notes = str(rule.get("notes") or "").strip()
            if notes and notes[:40] not in str(leaf.get("mustWrite") or ""):
                leaf["mustWrite"] = "；".join(
                    bit for bit in (str(leaf.get("mustWrite") or "").strip(), notes[:200]) if bit
                )[:400]
            extra = [code for code in (rule.get("standards") or []) if code not in (leaf.get("standards") or [])]
            if extra:
                leaf["standards"] = list(leaf.get("standards") or []) + extra
        merged.append(leaf)
    return merged


def clauses_for_standards(db, standards: list[str], specialty: str) -> list[dict]:
    if db is None or not standards:
        return []
    hits: list[dict] = []
    seen: set[str] = set()
    for code in standards:
        try:
            rows = search_clauses(db, code, specialty or "通用", limit=MAX_CLAUSES)
        except Exception:
            logger.exception("drawing clause search failed")
            rows = []
        for row in rows:
            key = str(row.get("key") or "")
            if key in seen:
                continue
            seen.add(key)
            hits.append(row)
            if len(hits) >= MAX_CLAUSES:
                return hits
    return hits


def _loads_parameters(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        return ""
    return str(data.get("parameters") or "").strip()


def read_sheet_parameters(jpeg: bytes, notes: str, clauses: list[dict], complete=None) -> str:
    hint = "\n".join(
        f"{item.get('code') or ''} {item.get('clauseNo') or ''} {item.get('excerpt') or ''}".strip()
        for item in clauses or []
    )
    body = f"施工说明：{(notes or '')[:800]}"
    if hint:
        body += "\n只可参考这些条文解释图面，不得另引标准：\n" + hint
    body += '\n返回 JSON：{"parameters":"尺寸、材料、配筋、高程"}'
    b64 = base64.b64encode(jpeg).decode("ascii")
    messages = [
        {"role": "system", "content": _VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": body},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        },
    ]
    if complete is None:
        raw = chat_complete(
            model_id=get_vision_model_id(),
            messages=messages,
            temperature=0.1,
            timeout=90,
            max_tokens=800,
        )
    else:
        raw = complete(messages)
    return _loads_parameters(raw)


def _index_pdf(path: str, filename: str) -> list[dict]:
    try:
        import pymupdf as fitz
    except ImportError:
        return []
    sheets: list[dict] = []
    try:
        with fitz.open(path) as doc:
            total = min(len(doc), MAX_SCAN_PAGES)
            for index in range(total):
                native = (doc[index].get_text("text") or "").strip()
                title_text = native
                if len(native) < 40:
                    image = raster_pdf_page(path, index, zoom=1.4)
                    title_text, _status = ocr_region(image, TITLE_BLOCK_BOX)
                parsed = parse_title_block(title_text or native)
                if not parsed["title"] and not parsed["drawingNo"]:
                    continue
                parsed.update({"page": index, "path": path, "filename": filename, "native": native[:4000]})
                sheets.append(parsed)
    except Exception:
        logger.exception("drawing index failed: %s", filename)
    return sheets


def _notes_for_sheet(sheet: dict) -> str:
    native = str(sheet.get("native") or "")
    notes = notes_from_text(native)
    if notes:
        return notes
    image = raster_pdf_page(str(sheet.get("path") or ""), int(sheet.get("page") or 0), zoom=1.4)
    if image is None:
        return ""
    text, _status = ocr_region(image, NOTES_BOX)
    return notes_from_text(text)


def _jpeg_for_sheet(sheet: dict) -> bytes:
    from .ocr import image_to_jpeg_bytes

    image = raster_pdf_page(str(sheet.get("path") or ""), int(sheet.get("page") or 0), zoom=1.3)
    if image is None:
        return b""
    return image_to_jpeg_bytes(image, max_side=1400)


def extract_drawing_rules(
    files: list | None,
    tech_rules: list | None,
    dimensions: list | None,
    db=None,
    specialty: str = "通用",
    vision=None,
) -> dict:
    """vision=False 表示不识图，仍保留施工说明。失败由调用方接住。"""
    names = match_names(tech_rules, dimensions)
    if not names:
        return {"rules": [], "note": "没有可对上的技术点或清单名称"}
    index: list[dict] = []
    for item in files or []:
        path = str((item or {}).get("path") or "")
        filename = str((item or {}).get("filename") or os.path.basename(path) or "未命名")
        if not path or not os.path.exists(path):
            continue
        if os.path.splitext(path)[1].lower() != ".pdf":
            continue
        index.extend(_index_pdf(path, filename))
    chosen = select_sheets(index, names)
    if not chosen:
        return {"rules": [], "note": "图纸目录里没有对上的施工图"}
    use_vision = vision is not False
    vision_id = None
    if use_vision and vision is None:
        try:
            vision_id = get_vision_model_id()
        except Exception:
            logger.exception("vision model lookup failed")
            vision_id = None
        use_vision = bool(vision_id)
    rules: list[dict] = []
    for sheet in chosen:
        notes = _notes_for_sheet(sheet)
        standards = extract_standards(notes)
        clauses = clauses_for_standards(db, standards, specialty)
        parameters = ""
        if use_vision:
            try:
                jpeg = _jpeg_for_sheet(sheet)
                if jpeg:
                    parameters = read_sheet_parameters(
                        jpeg,
                        notes,
                        clauses,
                        complete=vision if callable(vision) else None,
                    )
            except (LlmError, json.JSONDecodeError, TypeError, ValueError):
                logger.exception("drawing vision failed")
                parameters = ""
        rule = compose_rule(sheet, notes, parameters or None)
        if rule["notes"] or (rule["parameters"] and rule["parameters"] != "未识图"):
            rules.append(rule)
    if not rules:
        return {"rules": [], "note": "对上的施工图没有抽出说明或参数"}
    return {"rules": rules, "note": f"图纸评审规则 {len(rules)} 条"}
