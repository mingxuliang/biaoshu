"""从招标全文抽出技术标应答需求和商务标应答。

分段通读，不只取文首。抽失败时返回空字符串，不让整次解析失败。
"""

from __future__ import annotations

import json
import logging
import re

from .e0_tender_parse import CHUNK_CHARS, CHUNK_OVERLAP
from .llm import LlmError, chat_complete, get_default_model_id

logger = logging.getLogger(__name__)

FIELD_MAX = 24000

_SYSTEM = """你从招标文件原文中分开抽取两类应答材料。
只返回 JSON，不要 markdown，格式：
{"techBidResponseRequirements":"...","businessBidResponse":"..."}
技术标应答需求：功能、技术规格、服务、实施、验收等必须写入技术标的条款。每条单独一行，行首用「1、」「2、」，先写短名，再写要求和关键数字。不要把多条挤在同一行。保留条款短名和关键数字。
商务标应答：资格、资信、业绩、财务、人员证书、报价和固定格式件。每条单独一行，行首用「1、」「2、」，先写短名，再写要求和关键数字。不要把多条挤在同一行。
不要把评分办法写进技术标应答需求。不要把技术方案写进商务标应答。
本段没有的一侧填空字符串，禁止编造。"""


def extract_bid_requirements(full_text: str, model_id: str | None = None) -> dict:
    """返回 techBidResponseRequirements、businessBidResponse、note。"""
    text = (full_text or "").strip()
    empty = {"techBidResponseRequirements": "", "businessBidResponse": "", "note": ""}
    if not text:
        empty["note"] = "招标全文为空，未抽出应答需求"
        return empty
    try:
        model = model_id or get_default_model_id()
    except Exception as exc:  # noqa: BLE001 —— 没有模型时保留其余解析结果
        empty["note"] = f"未配置可用大模型，应答需求未抽出（{exc}）"
        return empty

    tech_parts: list[str] = []
    business_parts: list[str] = []
    errors: list[str] = []
    chunks = _chunks(text)
    for index, chunk in enumerate(chunks, start=1):
        try:
            data = _extract_chunk(model, chunk, index, len(chunks))
        except (LlmError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"第{index}段：{exc}")
            continue
        tech = str(data.get("techBidResponseRequirements") or "").strip()
        business = str(data.get("businessBidResponse") or "").strip()
        if tech:
            tech_parts.append(tech)
        if business:
            business_parts.append(business)

    note = ""
    if errors and not tech_parts and not business_parts:
        note = "应答需求未抽出：" + "；".join(errors[:3])
    elif errors:
        note = "部分段落未抽出：" + "；".join(errors[:2])
    return {
        "techBidResponseRequirements": _merge(tech_parts),
        "businessBidResponse": _merge(business_parts),
        "note": note,
    }


def _chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _extract_chunk(model_id: str, chunk: str, part: int, total: int) -> dict:
    content = chat_complete(
        model_id=model_id,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": f"以下是招标全文第 {part}/{total} 段。只抽取本段真实出现的内容。\n\n{chunk}",
            },
        ],
        temperature=0.1,
        timeout=180,
        max_tokens=4096,
    )
    return _parse_json(content)


def _parse_json(content: str) -> dict:
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("没有返回 JSON")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("返回的不是对象")
    return data


def _merge(parts: list[str]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for part in parts:
        for line in part.splitlines():
            item = line.strip()
            if not item:
                continue
            key = re.sub(r"\s+", "", item)
            if key in seen:
                continue
            seen.add(key)
            lines.append(item)
    return "\n".join(lines)[:FIELD_MAX]
