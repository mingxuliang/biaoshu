"""从施工图 PDF 抽出可核对的工程事实。

先读页面上的真文字。识图模型只能补充文字里已经出现的数值，对不上的丢弃。
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_NUM = re.compile(r"C\d{2}|[WwPp]\d+|\d+(?:\.\d+)?\s*(?:m|mm|kN|MPa|m3|m³|%)")
_SHEET_KIND = (
    ("设计说明", ("设计说明", "总说明")),
    ("配筋图", ("配筋", "钢筋")),
    ("工程量表", ("工程量", "材料表")),
    ("结构图", ("结构", "剖面", "平面")),
)


def classify_sheet(title: str, text: str = "") -> str:
    blob = f"{title or ''} {text or ''}"
    for name, words in _SHEET_KIND:
        if any(word in blob for word in words):
            return name
    return "其他"


def facts_from_text(text: str, *, drawing_no: str = "", page: int = 1, title: str = "") -> list[dict]:
    """从一页文字里抽出带原文证据的参数。数值必须来自这一页。"""
    facts: list[dict] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if len(line) < 2:
            continue
        for match in _NUM.finditer(line):
            value = re.sub(r"\s+", "", match.group())
            field = "混凝土强度" if value.upper().startswith("C") else "抗渗等级" if re.match(r"[WwPp]\d+", value) else "尺寸"
            if "开挖" in line or "基坑" in line:
                field = "开挖深度"
            if "围堰" in line or "导流" in line:
                field = "导流"
                value = "围堰" if "围堰" in line else "导流"
            key = f"{field}|{value}|{line[:24]}"
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                {
                    "object": (title or "施工图")[:40],
                    "field": field,
                    "value": value[:40],
                    "unit": "",
                    "drawingNo": drawing_no[:40],
                    "page": page,
                    "evidence": line[:180],
                    "sheetKind": classify_sheet(title, line),
                }
            )
    return facts


def keep_grounded(facts: list | None, page_text: str) -> list[dict]:
    """识图结果里的数值必须能在该页文字中找到。"""
    blob = re.sub(r"\s+", "", page_text or "")
    kept: list[dict] = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        value = re.sub(r"\s+", "", str(fact.get("value") or ""))
        evidence = re.sub(r"\s+", "", str(fact.get("evidence") or ""))
        if not value:
            continue
        if value not in blob and evidence not in blob:
            continue
        kept.append(fact)
    return kept


def _loads_facts(raw: str) -> list[dict]:
    text = (raw or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    data = json.loads(text[start : end + 1])
    return data if isinstance(data, list) else []


def _blocks(page) -> list[dict]:
    raw = page.get_text("dict") or {}
    out: list[dict] = []
    for block in raw.get("blocks") or []:
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines") or []:
            text = "".join(span.get("text") or "" for span in line.get("spans") or []).strip()
            if text:
                lines.append(text)
        text = "\n".join(lines).strip()
        if len(text) < 2:
            continue
        bbox = tuple(block.get("bbox") or (0, 0, 0, 0))
        kind = "表格" if text.count("\n") >= 3 and sum(ch.isdigit() for ch in text) >= 6 else "视图"
        if any(word in text for word in ("材料表", "工程量", "钢筋表", "表")):
            kind = "表格"
        out.append({"text": text[:500], "bbox": bbox, "kind": kind})
    return out


def regions_from_blocks(blocks: list | None) -> list[dict]:
    """把相邻文字块收成视图或表格区域，供高分辨率识读。"""
    ordered = sorted(
        [item for item in blocks or [] if isinstance(item, dict) and item.get("bbox")],
        key=lambda item: (item["bbox"][1], item["bbox"][0]),
    )
    regions: list[dict] = []
    for block in ordered:
        if regions:
            prev = regions[-1]
            gap = block["bbox"][1] - prev["bbox"][3]
            if gap < 28 and block.get("kind") == prev.get("kind"):
                prev["text"] = f"{prev['text']}\n{block['text']}"[:800]
                x0, y0, x1, y1 = prev["bbox"]
                bx0, by0, bx1, by1 = block["bbox"]
                prev["bbox"] = (min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1))
                continue
        regions.append({"text": block["text"], "bbox": block["bbox"], "kind": block.get("kind") or "视图"})
    return [item for item in regions if len(item["text"]) >= 8][:12]


def _clip_jpeg(page, bbox) -> bytes:
    import pymupdf as fitz

    rect = fitz.Rect(bbox)
    if rect.width < 20 or rect.height < 20:
        return b""
    zoom = 2.2
    longest = max(rect.width, rect.height)
    if longest * zoom > 1600:
        zoom = 1600 / longest
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
    return pix.tobytes("jpeg")


def _vision_json(jpeg: bytes, text: str, complete=None) -> str:
    if not jpeg:
        return ""
    import base64

    from .llm import LlmError, chat_complete, get_vision_model_id

    prompt = (
        "只根据图块和下面的文字，列出图中已经写明的参数。"
        "返回 JSON 数组，每项含 object、field、value、evidence。"
        "evidence 必须是文字里的原句。不要补充图上没有的数值。没有就返回 []。\n"
        + (text or "")[:1200]
    )
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}"}},
    ]
    messages = [{"role": "user", "content": content}]
    try:
        if complete is not None:
            return complete(messages)
        model_id = get_vision_model_id()
        if not model_id:
            return ""
        return chat_complete(model_id=model_id, messages=messages, temperature=0.1, timeout=90, max_tokens=800)
    except (LlmError, TypeError, ValueError):
        return ""
    except Exception:
        logger.exception("drawing region vision failed")
        return ""


def extract_drawing_facts(files: list | None, vision=None) -> dict:
    """先读矢量文字，再把视图和表格切成小块识读。数值必须能在该页文字里找到。"""
    facts: list[dict] = []
    vision_used = 0
    try:
        import pymupdf as fitz
    except ImportError:
        return {"facts": [], "note": "未安装 PDF 解析"}
    for item in files or []:
        path = str((item or {}).get("path") or "")
        if not path or not os.path.exists(path) or not path.lower().endswith(".pdf"):
            continue
        try:
            with fitz.open(path) as doc:
                for index, page in enumerate(doc):
                    if index >= 80:
                        break
                    text = page.get_text("text") or ""
                    title = ""
                    for line in text.splitlines():
                        if "图名" in line:
                            title = line.strip()[:40]
                            break
                    page_facts = facts_from_text(text, page=index + 1, title=title)
                    if vision:
                        for region in regions_from_blocks(_blocks(page)):
                            if vision_used >= 8:
                                break
                            try:
                                jpeg = _clip_jpeg(page, region["bbox"])
                                raw = vision(region["text"], jpeg) if callable(vision) else _vision_json(jpeg, region["text"])
                                extra = keep_grounded(_loads_facts(raw), text)
                            except (json.JSONDecodeError, TypeError, ValueError):
                                extra = []
                            vision_used += 1
                            for fact in extra:
                                fact.setdefault("object", title or region["kind"])
                                fact.setdefault("page", index + 1)
                                fact.setdefault("sheetKind", classify_sheet(title, region["text"]))
                            page_facts.extend(extra)
                    facts.extend(keep_grounded(page_facts, text))
        except Exception:
            logger.exception("drawing facts failed: %s", path)
    if not facts:
        return {"facts": [], "note": "图纸没有抽出可核对的参数"}
    return {"facts": facts[:200], "note": f"图纸事实 {len(facts[:200])} 条"}
