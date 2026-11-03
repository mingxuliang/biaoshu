"""技术标叶子规则：从招标技术章节抽出必须写到的内容，图纸和清单只补参数。"""

from __future__ import annotations

import json
import logging
import re

from .llm import LlmError, chat_complete, get_default_model_id
from .qty_boq import rows_from_dimensions

logger = logging.getLogger(__name__)

MAX_LEAVES = 40
AXES = {"完整性", "针对性", "合规性", "可落地性", "规范性"}
_ITEM_IDS = ("eval-tech", "contract-tech", "qty-techstd")
_HEADINGS = ("评标办法", "技术标准和要求", "发包人要求", "施工组织设计", "技术标评分", "详细评审")
_BUSINESS = ("报价", "价格", "商务", "资信", "业绩", "信用", "资格", "投标函")
_STOP = {"的", "和", "及", "应", "必须", "进行", "施工", "工程", "要求", "方案", "项目", "技术", "相关", "内容"}
_PARAM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("混凝土强度", re.compile(r"C\d{2}")),
    ("抗渗等级", re.compile(r"抗渗(?:等级)?\s*[Pp]?\d+")),
    ("抗震", re.compile(r"抗震(?:设防)?(?:烈度|等级)?[^\n，。；]{0,16}")),
    ("压实度", re.compile(r"压实度\s*[0-9]+(?:\.[0-9]+)?%?")),
)
_STD = re.compile(r"(?:GB/T|GB|JGJ|JTG|CJJ|SL)\s*/?\s*\d+(?:\.\d+)?(?:-\d{4})?", re.I)
_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}|\d+(?:\.\d+)?")
_WS = re.compile(r"\s+")

_SYSTEM = """你从招标文件的技术标材料抽取评审叶子规则。
不要输出商务、资信、业绩、资格、报价、价格。
必须写到的内容是规则正文，不能只重复评分因素标题。
axis 只能是：完整性、针对性、合规性、可落地性、规范性。
standards 只收录原文写明的标准号。
只返回 JSON 对象 {"rules":[...]}，最多 40 条，不要 markdown。每项字段：
{"factor","score","grades","mustWrite","parameters","standards","chapter","axis"}
"""


def _walk_text(node) -> str:
    parts: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"content", "original", "text", "label", "摘要", "原文"} and isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (dict, list)):
                parts.append(_walk_text(value))
    elif isinstance(node, list):
        for item in node:
            parts.append(_walk_text(item))
    return "\n".join(part for part in parts if part)


def _item_text(dimensions: list | None, item_id: str) -> str:
    chunks: list[str] = []
    for dim in dimensions or []:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                chunks.append(_walk_text(item))
    return "\n".join(chunks).strip()


def corpus_windows(corpus: str, limit: int = 12000) -> str:
    text = corpus or ""
    chunks: list[str] = []
    used = 0
    for key in _HEADINGS:
        start = 0
        while used < limit:
            idx = text.find(key, start)
            if idx < 0:
                break
            piece = text[max(0, idx - 80) : idx + 1800]
            chunks.append(piece)
            used += len(piece)
            start = idx + len(key)
    return "\n\n".join(chunks)[:limit]


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(text or ""):
        if token in _STOP or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _standards(value) -> list[str]:
    if isinstance(value, list):
        blob = " ".join(str(item) for item in value)
    else:
        blob = str(value or "")
    found: list[str] = []
    seen: set[str] = set()
    for match in _STD.findall(blob):
        code = re.sub(r"\s+", "", match).upper()
        if code not in seen:
            seen.add(code)
            found.append(code)
    return found[:8]


def _is_business(text: str) -> bool:
    return any(word in (text or "") for word in _BUSINESS)


def normalize_leaves(rows: list | None) -> list[dict]:
    leaves: list[dict] = []
    seen: set[str] = set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        factor = _WS.sub(" ", str(raw.get("factor") or raw.get("name") or "")).strip()[:40]
        must = _WS.sub(" ", str(raw.get("mustWrite") or raw.get("must_write") or "")).strip()[:400]
        if len(factor) < 2 or len(must) < 4:
            continue
        if _is_business(f"{factor}{must}"):
            continue
        key = f"{factor}|{must[:24]}"
        if key in seen:
            continue
        seen.add(key)
        axis = str(raw.get("axis") or "").strip()
        if axis not in AXES:
            axis = "完整性"
        score = str(raw.get("score") or "").strip()[:16]
        grades = _WS.sub(" ", str(raw.get("grades") or "")).strip()[:120]
        parameters = _WS.sub(" ", str(raw.get("parameters") or "")).strip()[:240]
        chapter = _WS.sub(" ", str(raw.get("chapter") or "")).strip()[:40] or "技术标"
        leaves.append(
            {
                "factor": factor,
                "score": score,
                "grades": grades,
                "mustWrite": must,
                "parameters": parameters,
                "standards": _standards(raw.get("standards")),
                "chapter": chapter,
                "axis": axis,
                "booklet": "技术标",
            }
        )
        if len(leaves) >= MAX_LEAVES:
            break
    return leaves


def _strip_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def _rows_of(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("rules", "items", "leaves", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_rows(raw: str) -> list:
    """整段 JSON 优先。被截断时收下已经闭合的规则对象，不因一处坏掉整批。"""
    text = _strip_fence(raw)
    if not text:
        return []
    try:
        return _rows_of(json.loads(text))
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    found: list = []
    idx = 0
    while idx < len(text) and len(found) < MAX_LEAVES:
        brace = text.find("{", idx)
        if brace < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            idx = brace + 1
            continue
        if isinstance(obj, dict):
            wrapped = _rows_of(obj)
            if wrapped:
                return wrapped
            if obj.get("factor") or obj.get("mustWrite") or obj.get("name"):
                found.append(obj)
        idx = max(end, brace + 1)
    return found


def _drawing_blob(dimensions: list | None) -> str:
    chunks: list[str] = []
    for dim in dimensions or []:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "")
            if item.get("id") == "qty-drawing" or "图纸" in label or "设计说明" in label:
                chunks.append(_walk_text(item))
    return "\n".join(chunks)


def _drawing_hits(blob: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for label, pattern in _PARAM_RES:
        for match in pattern.finditer(blob or ""):
            value = _WS.sub("", match.group())
            start = max(0, match.start() - 40)
            end = min(len(blob), match.end() + 40)
            found.append((label, value, blob[start:end]))
    return found


def _overlaps(leaf_text: str, other: str) -> bool:
    if not other:
        return False
    for token in _tokens(leaf_text):
        if len(token) >= 2 and token in other:
            return True
    return False


def attach_constraints(leaves: list | None, dimensions: list | None) -> list[dict]:
    """名称对得上的图纸参数、清单工程量写入 parameters。对不上的清单行不另成规则。"""
    drawing = _drawing_blob(dimensions)
    params = _drawing_hits(drawing)
    rows = rows_from_dimensions(dimensions)
    attached: list[dict] = []
    for raw in leaves or []:
        if not isinstance(raw, dict):
            continue
        leaf = dict(raw)
        bits = [str(leaf.get("parameters") or "").strip()]
        name = f"{leaf.get('factor') or ''}{leaf.get('mustWrite') or ''}"
        for label, value, context in params:
            if not _overlaps(str(leaf.get("factor") or ""), context):
                continue
            bit = f"图纸{label}{value}"
            if bit not in "；".join(bits):
                bits.append(bit)
        for row in rows:
            row_name = (row.name or "").strip()
            if len(row_name) < 2:
                continue
            if row_name not in name and str(leaf.get("factor") or "") not in row_name:
                continue
            qty = f"{row.qty:g}{row.unit}" if row.qty is not None else row.unit
            bit = f"清单{row_name}{qty}".strip()
            if bit not in "；".join(bits):
                bits.append(bit)
        leaf["parameters"] = "；".join(bit for bit in bits if bit)[:400]
        attached.append(leaf)
    return attached


def extract_tech_rules(dimensions: list | None, corpus: str, complete=None) -> dict:
    """抽出技术标叶子。模型失败时返回空列表和备注，不抛给解析任务。"""
    parts = [text for item_id in _ITEM_IDS if (text := _item_text(dimensions, item_id))]
    windows = corpus_windows(corpus)
    if windows:
        parts.append(windows)
    source = "\n\n".join(parts).strip()
    if len(source) < 40:
        return {"rules": [], "note": "技术标相关章节为空"}
    source = source[:16000]
    try:
        if complete is None:
            raw = chat_complete(
                model_id=get_default_model_id(),
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": source},
                ],
                temperature=0.1,
                timeout=180,
                max_tokens=8000,
                extra={"response_format": {"type": "json_object"}},
            )
        else:
            raw = complete(source)
        rows = _parse_rows(raw)
    except (LlmError, json.JSONDecodeError, TypeError, ValueError):
        logger.exception("tech leaf extract failed")
        return {"rules": [], "note": "技术标叶子规则未抽出"}
    leaves = attach_constraints(normalize_leaves(rows if isinstance(rows, list) else []), dimensions)
    if not leaves:
        return {"rules": [], "note": "技术标叶子规则未抽出"}
    return {"rules": leaves, "note": f"技术标叶子规则 {len(leaves)} 条"}
