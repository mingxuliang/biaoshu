"""工程量逻辑匹配（技术评分 qty_logic）：大模型抽标书原文数字，确定性比对招标清单。

三条规则同一张卡：
1. 清单 ↔ 施组总量（混凝土 m³ / 土方 m³ / 钢筋 t），偏差超阈值扣分
2. 清单推主材 ↔ 采购计划；混凝土 m³↔吨用 2.4 t/m³；无采购计划则建议跳过
3. 土方产能：日开挖量 ↔ 土方总量/工期天数 ↔ 挖机台数×台班产量

不算图纸工程量。缺清单或缺标书对应量出建议「无法比对」，不视为一致通过。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import qty_boq, rules_data
from .excerpt_guard import snap_bid_excerpt
from .qty_boq import BoqAgg, classify_name, norm_unit, parse_qty, qty_in_canonical

logger = logging.getLogger(__name__)

CONCRETE_T_PER_M3 = 2.4
CHUNK_CHARS = 8000
MAX_CHUNKS = 8
MAX_REVIEW_CHARS = 80_000
PARALLEL_WORKERS = 3
CALL_TIMEOUT = 60
PER_CHUNK = 24

_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、")
_CN_PAREN = re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]")
_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)")
_ATTACH = re.compile(r"^附件[0-9一二三四五六七八九十]")

_CHUNK_HINTS = (
    "工程量",
    "混凝土",
    "土方",
    "材料",
    "机械",
    "挖掘机",
    "挖机",
    "工期",
    "采购",
    "钢筋",
    "填方",
    "挖方",
    "台班",
)

_MATERIAL_HINTS = ("采购计划", "材料计划", "物资计划", "主材采购", "材料采购")

_METRIC_KIND = {
    "concrete": "concrete",
    "earth": "earth",
    "steel": "steel",
    "混凝土": "concrete",
    "土方": "earth",
    "钢筋": "steel",
}

_SEVERITY_RANK = {"废标": 4, "降档": 3, "扣分": 2, "建议": 1}
_SEVERITY_DEDUCT_RATIO = {"废标": 1.0, "降档": 0.6, "扣分": 0.4, "建议": 0.15, "无法比对": 0.15}


@dataclass
class QtyHit:
    metric: str
    value: float
    unit: str
    excerpt: str = ""
    source: str = ""
    name: str = ""


@dataclass
class BidQty:
    items: list[QtyHit] = field(default_factory=list)
    has_material_plan: bool = False
    extract_failed: bool = False
    extract_reason: str = ""

    @property
    def org_concrete_m3(self) -> float:
        return _sum_kind(self.items, "concrete", "m³", org_only=True)

    @property
    def org_earth_m3(self) -> float:
        return _sum_kind(self.items, "earth", "m³", org_only=True)

    @property
    def org_steel_t(self) -> float:
        return _sum_kind(self.items, "steel", "t", org_only=True)


def _is_org_source(source: str) -> bool:
    src = source or ""
    if any(k in src for k in _MATERIAL_HINTS) or src == "材料计划":
        return False
    return True


def _sum_kind(items: list[QtyHit], kind: str, unit: str, *, org_only: bool) -> float:
    total = 0.0
    found = False
    for item in items:
        if item.metric != kind or item.unit != unit:
            continue
        if org_only and not _is_org_source(item.source):
            continue
        total += item.value
        found = True
    return total if found else 0.0


def _has_kind(items: list[QtyHit], kind: str, unit: str, *, org_only: bool) -> bool:
    for item in items:
        if item.metric != kind or item.unit != unit:
            continue
        if org_only and not _is_org_source(item.source):
            continue
        return True
    return False


def _is_heading_line(line: str) -> bool:
    text = (line or "").strip()
    if not text or len(text) > 48 or "。" in text:
        return False
    return bool(
        _CHAPTER.match(text)
        or _CN_DOT.match(text)
        or _CN_PAREN.match(text)
        or _DOTTED.match(text)
        or _ATTACH.match(text)
    )


def _is_heading_para(p: dict) -> bool:
    text = (p.get("text") or "").strip()
    style = (p.get("style") or "").lower()
    if "heading" in style or "标题" in style:
        return bool(text) and len(text) <= 48
    return _is_heading_line(text)


def _split_sections(paragraphs: list[dict]) -> list[dict]:
    heading = "开篇"
    buf: list[str] = []
    sections: list[dict] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append({"heading": heading, "text": body})

    for p in paragraphs:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if _is_heading_para(p):
            flush()
            heading = text[:48]
            buf = []
            continue
        buf.append(text)
    flush()
    return sections or [{"heading": "全文", "text": "\n".join((p.get("text") or "") for p in paragraphs)}]


def _section_relevant(sec: dict) -> bool:
    blob = f"{sec.get('heading') or ''}{sec.get('text') or ''}"
    return any(k in blob for k in _CHUNK_HINTS)


def _pack_chunks(sections: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    heading = sections[0]["heading"] if sections else "全文"
    buf: list[str] = []
    used = 0
    for sec in sections:
        piece = f"【{sec['heading']}】\n{sec['text']}"
        if buf and len("\n".join(buf)) + len(piece) > CHUNK_CHARS:
            chunks.append({"heading": heading, "text": "\n".join(buf)})
            used += len(chunks[-1]["text"])
            if len(chunks) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
                break
            heading = sec["heading"]
            buf = [piece]
            continue
        if not buf:
            heading = sec["heading"]
        buf.append(piece)
        if len("\n".join(buf)) >= CHUNK_CHARS:
            chunks.append({"heading": heading, "text": "\n".join(buf)})
            used += len(chunks[-1]["text"])
            buf = []
            if len(chunks) >= MAX_CHUNKS or used >= MAX_REVIEW_CHARS:
                break
    if buf and len(chunks) < MAX_CHUNKS and used < MAX_REVIEW_CHARS:
        text = "\n".join(buf)
        chunks.append({"heading": heading, "text": text[: MAX_REVIEW_CHARS - used]})
    return chunks


def _loads_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        left, right = text.find("{"), text.rfind("}")
        if left >= 0 and right > left:
            try:
                data = json.loads(text[left : right + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _system_prompt() -> str:
    return """你是招投标技术标工程量抽取员。只从本段投标书原文抄写数字，禁止估算、禁止编造、禁止改写原句。

关注：施工组织里的混凝土/土方/钢筋工程量，材料/采购计划里的主材数量，机械表里的挖掘机台数与台班产量，进度里的土方工期天数与日开挖量。

只返回 JSON：
{
  "has_material_plan": false,
  "items": [
    {
      "metric": "concrete|earth|steel|excavator_count|shift_yield|earth_days|daily_excavate|material",
      "name": "材料名称，metric=material 时必填",
      "value": 0,
      "unit": "m³或t或台或天或m³/台班",
      "excerpt": "含该数字的原文连续原句",
      "source": "施组|材料计划|机械|进度"
    }
  ]
}

规则：
- excerpt 必须是原文连续原句，禁止改写。
- 本段没有工程量数字则 items 为空数组。
- has_material_plan 仅当本段确有材料/采购计划表或专章时为 true。
- 局部分部分项数量也要抽出，后续会全局加总，不要自行加总或挑选「总量」。
- 台班产量单位用 m³/台班；挖机台数单位用 台；工期天数单位用 天。
"""


def _parse_metric(raw: dict) -> tuple[str, str]:
    metric = str(raw.get("metric") or "").strip().lower()
    name = str(raw.get("name") or "").strip()
    mapped = _METRIC_KIND.get(metric) or _METRIC_KIND.get(name)
    if mapped:
        return mapped, name or {"concrete": "混凝土", "earth": "土方", "steel": "钢筋"}[mapped]
    if metric in {"excavator_count", "shift_yield", "earth_days", "daily_excavate", "material"}:
        return metric, name
    kind = classify_name(name or str(raw.get("excerpt") or ""))
    if kind:
        return kind, name
    if metric == "material" or name:
        return "material", name
    return "", name


def _coerce_hit(raw: dict, hay: str) -> QtyHit | None:
    if not isinstance(raw, dict):
        return None
    excerpt = snap_bid_excerpt(str(raw.get("excerpt") or ""), hay)
    if not excerpt:
        return None
    metric, name = _parse_metric(raw)
    value = raw.get("value")
    if value is None:
        value = parse_qty(excerpt)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < 0:
        return None
    unit_raw = str(raw.get("unit") or "")
    qty, unit = qty_in_canonical(num, unit_raw)
    if qty is None:
        return None
    if metric in {"concrete", "earth"} and unit == "t":
        # 施组里混凝土/土方偶发写成吨，主材条再处理；这里仍保留
        pass
    if metric == "shift_yield":
        unit = "m³/台班"
    elif metric == "excavator_count":
        unit = "台"
    elif metric == "earth_days":
        unit = "天"
    elif metric == "daily_excavate":
        unit = "m³"
    elif metric in {"concrete", "earth"} and unit not in {"m³", "t"}:
        if "方" in unit_raw or "m3" in unit_raw.lower() or "m³" in unit_raw:
            unit = "m³"
        else:
            return None
    elif metric == "steel" and unit not in {"t"}:
        return None
    source = str(raw.get("source") or "").strip() or "施组"
    if metric == "material" and not name:
        name = excerpt[:20]
    if not metric:
        return None
    return QtyHit(metric=metric, value=qty, unit=unit, excerpt=excerpt, source=source, name=name)


def _call_chunk(model_id: str, chunk: dict) -> dict:
    from .llm import chat_complete

    text = (chunk.get("text") or "").strip()
    heading = chunk.get("heading") or "技术标"
    if len(text) < 20:
        return {"has_material_plan": False, "items": [], "text": text}
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            raw = chat_complete(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {
                        "role": "user",
                        "content": f"以下是投标文件原文（本章标题：{heading}）。只抽取本段出现的工程量数字：\n\n{text}",
                    },
                ],
                temperature=0.1,
                timeout=CALL_TIMEOUT,
                extra={"response_format": {"type": "json_object"}},
            )
            data = _loads_json(raw)
            items = data.get("items") if isinstance(data.get("items"), list) else []
            return {
                "has_material_plan": bool(data.get("has_material_plan")),
                "items": items[:PER_CHUNK],
                "text": text,
            }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                continue
    logger.warning("e_qty_logic chunk failed: %s", last_exc)
    return {"has_material_plan": False, "items": [], "text": text, "failed": True}


def extract_from_bid(paragraphs: list[dict] | None, full_text: str = "") -> BidQty:
    paras = paragraphs or []
    if not paras and full_text.strip():
        paras = [{"text": line, "style": ""} for line in full_text.splitlines() if line.strip()]
    if not paras:
        return BidQty(extract_failed=True, extract_reason="投标书无正文，无法抽取工程量")

    sections = [sec for sec in _split_sections(paras) if _section_relevant(sec)]
    if not sections:
        return BidQty(extract_failed=True, extract_reason="未检出含工程量/材料/机械/工期的章节")

    chunks = _pack_chunks(sections)
    try:
        from .llm import get_default_model_id

        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        logger.warning("e_qty_logic no model: %s", exc)
        return BidQty(extract_failed=True, extract_reason="未配置默认模型，无法抽取标书工程量")
    if not model_id:
        return BidQty(extract_failed=True, extract_reason="未配置默认模型，无法抽取标书工程量")

    payloads: list[dict] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=min(PARALLEL_WORKERS, len(chunks) or 1)) as pool:
        futs = [pool.submit(_call_chunk, model_id, chunk) for chunk in chunks]
        for fut in as_completed(futs):
            payloads.append(fut.result())
    hay = full_text or "\n".join((p.get("text") or "") for p in paras)
    items: list[QtyHit] = []
    has_plan = False
    seen: set[str] = set()
    for payload in payloads:
        if payload.get("failed"):
            failed += 1
        has_plan = has_plan or bool(payload.get("has_material_plan"))
        chunk_hay = payload.get("text") or hay
        for raw in payload.get("items") or []:
            hit = _coerce_hit(raw, chunk_hay) or _coerce_hit(raw, hay)
            if not hit:
                continue
            key = f"{hit.metric}|{hit.unit}|{hit.value}|{re.sub(r'\s+', '', hit.excerpt)[:60]}"
            if key in seen:
                continue
            seen.add(key)
            items.append(hit)
            if hit.source == "材料计划" or any(k in (hit.source or "") for k in _MATERIAL_HINTS):
                has_plan = True
    blob = hay
    if not has_plan and any(k in blob for k in _MATERIAL_HINTS):
        has_plan = True
    if failed == len(payloads) and not items:
        return BidQty(extract_failed=True, extract_reason="大模型抽取工程量失败")
    return BidQty(items=items, has_material_plan=has_plan)


def _finding(rule: str, excerpt: str, suggestion: str, severity: str = "建议") -> dict:
    return {
        "engine": "e_qty_logic",
        "level": "L3",
        "severity": severity,
        "location": "技术标 / 工程量逻辑匹配",
        "excerpt": excerpt or "",
        "rule": rule,
        "tenderQuote": "",
        "suggestion": suggestion,
        "confidence": 0.8,
    }


def _pct_dev(bid: float, boq: float) -> float:
    if boq == 0:
        return 0.0 if bid == 0 else 100.0
    return abs(bid - boq) / abs(boq) * 100.0


def _fmt(n: float, unit: str) -> str:
    if abs(n - round(n)) < 1e-6:
        return f"{int(round(n))} {unit}"
    return f"{n:.2f} {unit}"


def _first_excerpt(items: list[QtyHit], kind: str, unit: str, *, org_only: bool = False) -> str:
    for item in items:
        if item.metric != kind or item.unit != unit:
            continue
        if org_only and not _is_org_source(item.source):
            continue
        if item.excerpt:
            return item.excerpt
    return ""


def _threshold(thresholds: dict | None, key: str, default: float) -> float:
    if not thresholds:
        return float(rules_data.THRESHOLDS.get(key, default))
    try:
        return float(thresholds.get(key, rules_data.THRESHOLDS.get(key, default)))
    except (TypeError, ValueError):
        return default


def _compare_totals(agg: BoqAgg, bid: BidQty, dev_ok: float) -> list[dict]:
    findings: list[dict] = []
    specs = (
        ("concrete", "混凝土", "m³", agg.concrete_m3, bid.org_concrete_m3, _has_kind(bid.items, "concrete", "m³", org_only=True)),
        ("earth", "土方", "m³", agg.earth_m3, bid.org_earth_m3, _has_kind(bid.items, "earth", "m³", org_only=True)),
        ("steel", "钢筋", "t", agg.steel_t, bid.org_steel_t, _has_kind(bid.items, "steel", "t", org_only=True)),
    )
    compared = 0
    missing_notes: list[str] = []
    for kind, label, unit, boq_v, bid_v, bid_has in specs:
        if boq_v <= 0 and not bid_has:
            continue
        if boq_v <= 0:
            missing_notes.append(f"清单无{label}{unit}可对")
            continue
        if not bid_has:
            missing_notes.append(f"标书施组未抽出{label}总量")
            continue
        compared += 1
        dev = _pct_dev(bid_v, boq_v)
        if dev > dev_ok:
            findings.append(
                _finding(
                    rule=f"F06.09 清单与施组{label}不一致",
                    excerpt=_first_excerpt(bid.items, kind, unit, org_only=True),
                    suggestion=(
                        f"招标清单{label}汇总 {_fmt(boq_v, unit)}，标书施组同类加总 {_fmt(bid_v, unit)}，"
                        f"偏差 {dev:.1f}%（阈值 ±{dev_ok:g}%）。请按清单修正施工组织工程量，避免局部数字当总量。"
                    ),
                    severity="扣分",
                )
            )
    if not compared and missing_notes:
        findings.append(
            _finding(
                rule="F06.09 清单与施组总量无法比对",
                excerpt=_first_excerpt(bid.items, "concrete", "m³", org_only=True)
                or _first_excerpt(bid.items, "earth", "m³", org_only=True)
                or _first_excerpt(bid.items, "steel", "t", org_only=True),
                suggestion="无法比对：" + "；".join(missing_notes) + "。请在施组写明与清单对应的混凝土/土方/钢筋总量。",
                severity="建议",
            )
        )
    return findings


def _material_items(bid: BidQty) -> list[QtyHit]:
    out = []
    for item in bid.items:
        if item.metric == "material" or (not _is_org_source(item.source) and item.metric in {"concrete", "earth", "steel"}):
            out.append(item)
    return out


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def _compare_materials(agg: BoqAgg, bid: BidQty, mismatch: float) -> list[dict]:
    if not bid.has_material_plan and not _material_items(bid):
        return [
            _finding(
                rule="F06.10 主材采购与清单矛盾",
                excerpt="",
                suggestion="缺材料计划，未比主材。请补充材料/采购计划后再与清单推算量核对，本条不视为一致通过。",
                severity="建议",
            )
        ]
    mats = _material_items(bid)
    if not mats:
        return [
            _finding(
                rule="F06.10 主材采购与清单矛盾",
                excerpt="",
                suggestion="已见材料/采购计划章节，但未抽出可核验的主材数量，无法比对。请在采购计划中写明混凝土、钢筋等同名同单位数量。",
                severity="建议",
            )
        ]
    findings: list[dict] = []
    compared = False

    bid_conc_t = sum(i.value for i in mats if i.metric in {"concrete", "material"} and i.unit == "t" and (i.metric == "concrete" or classify_name(i.name) == "concrete"))
    bid_conc_m3 = sum(i.value for i in mats if i.metric in {"concrete", "material"} and i.unit == "m³" and (i.metric == "concrete" or classify_name(i.name) == "concrete"))
    if agg.concrete_m3 > 0 and bid_conc_t > 0:
        expected = agg.concrete_m3 * CONCRETE_T_PER_M3
        compared = True
        ratio = max(expected, bid_conc_t) / min(expected, bid_conc_t) if min(expected, bid_conc_t) > 0 else 99
        if ratio >= mismatch:
            excerpt = next((i.excerpt for i in mats if i.unit == "t" and (i.metric == "concrete" or classify_name(i.name) == "concrete")), "")
            findings.append(
                _finding(
                    rule="F06.10 主材采购与清单矛盾",
                    excerpt=excerpt,
                    suggestion=(
                        f"清单混凝土 {_fmt(agg.concrete_m3, 'm³')} 按表观密度 {CONCRETE_T_PER_M3:g} t/m³ 折合 "
                        f"{_fmt(expected, 't')}，采购计划混凝土 {_fmt(bid_conc_t, 't')}，相差 {ratio:.1f} 倍"
                        f"（阈值 {mismatch:g} 倍），记方案前后矛盾。请统一清单量与采购计划。"
                    ),
                    severity="扣分",
                )
            )
    elif agg.concrete_m3 > 0 and bid_conc_m3 > 0:
        compared = True
        ratio = max(agg.concrete_m3, bid_conc_m3) / min(agg.concrete_m3, bid_conc_m3)
        if ratio >= mismatch:
            excerpt = next((i.excerpt for i in mats if i.unit == "m³" and (i.metric == "concrete" or classify_name(i.name) == "concrete")), "")
            findings.append(
                _finding(
                    rule="F06.10 主材采购与清单矛盾",
                    excerpt=excerpt,
                    suggestion=(
                        f"清单混凝土 {_fmt(agg.concrete_m3, 'm³')}，采购计划 {_fmt(bid_conc_m3, 'm³')}，"
                        f"相差 {ratio:.1f} 倍（阈值 {mismatch:g} 倍），记方案前后矛盾。"
                    ),
                    severity="扣分",
                )
            )

    boq_by = {}
    for row in agg.rows:
        if row.qty is None or not row.name:
            continue
        key = (_norm_name(row.name), row.unit)
        boq_by[key] = boq_by.get(key, 0.0) + row.qty

    for item in mats:
        name = _norm_name(item.name)
        if not name or item.unit not in {"m³", "t"}:
            continue
        boq_v = boq_by.get((name, item.unit))
        if boq_v is None:
            continue
        if item.metric == "concrete" or classify_name(item.name) == "concrete":
            continue
        compared = True
        lo, hi = min(boq_v, item.value), max(boq_v, item.value)
        ratio = hi / lo if lo > 0 else 99
        if ratio >= mismatch:
            findings.append(
                _finding(
                    rule="F06.10 主材采购与清单矛盾",
                    excerpt=item.excerpt,
                    suggestion=(
                        f"清单「{item.name}」{_fmt(boq_v, item.unit)}，采购计划 {_fmt(item.value, item.unit)}，"
                        f"相差 {ratio:.1f} 倍（阈值 {mismatch:g} 倍），记方案前后矛盾。"
                    ),
                    severity="扣分",
                )
            )

    if not compared:
        findings.append(
            _finding(
                rule="F06.10 主材采购与清单矛盾",
                excerpt=mats[0].excerpt if mats else "",
                suggestion="采购计划与清单没有同名同单位的主材可对（混凝土按 2.4 t/m³ 折吨）。无法比对，请补全采购计划品名、单位与数量。",
                severity="建议",
            )
        )
    return findings


def _pick_value(items: list[QtyHit], metric: str) -> tuple[float | None, str]:
    total = 0.0
    found = False
    excerpt = ""
    for item in items:
        if item.metric != metric:
            continue
        total += item.value
        found = True
        if not excerpt:
            excerpt = item.excerpt
    return (total if found else None, excerpt)


def _compare_capacity(agg: BoqAgg, bid: BidQty, dev_ok: float, default_yield: float) -> list[dict]:
    if agg.earth_m3 <= 0:
        return [
            _finding(
                rule="F06.11 土方产能不匹配",
                excerpt="",
                suggestion="无法比对：招标清单未汇总出土方 m³，不能核验挖机产能。",
                severity="建议",
            )
        ]
    daily, daily_ex = _pick_value(bid.items, "daily_excavate")
    days, days_ex = _pick_value(bid.items, "earth_days")
    machines, mach_ex = _pick_value(bid.items, "excavator_count")
    yield_v, yield_ex = _pick_value(bid.items, "shift_yield")
    assumed = False
    if yield_v is None and machines is not None:
        yield_v = default_yield
        assumed = True
    required = None
    required_note = ""
    if days and days > 0:
        required = agg.earth_m3 / days
        required_note = f"清单土方 {_fmt(agg.earth_m3, 'm³')} / 土方工期 {days:g} 天 = {_fmt(required, 'm³/天')}"
    capacity = None
    cap_note = ""
    if machines is not None and yield_v is not None:
        capacity = machines * yield_v
        cap_note = f"挖机 {machines:g} 台 × 台班产量 {yield_v:g} m³/台班 = {_fmt(capacity, 'm³/台班')}"
        if assumed:
            cap_note += f"（标书未写台班产量，按规则页默认 {default_yield:g} m³/台班 估算）"

    if daily is None and required is None and capacity is None:
        return [
            _finding(
                rule="F06.11 土方产能不匹配",
                excerpt="",
                suggestion=(
                    f"无法比对：清单土方 {_fmt(agg.earth_m3, 'm³')}，但标书未抽出日开挖量、土方工期天数或挖机台数。"
                    "请在进度/机械表补明日开挖量、土方工期与挖机配置。"
                ),
                severity="建议",
            )
        ]

    pairs: list[tuple[str, float, float, str]] = []
    if daily is not None and required is not None:
        pairs.append(("日开挖量 vs 清单/工期", daily, required, daily_ex or days_ex))
    if capacity is not None and required is not None:
        pairs.append(("挖机产能 vs 清单/工期", capacity, required, mach_ex or yield_ex or days_ex))
    if daily is not None and capacity is not None:
        pairs.append(("日开挖量 vs 挖机产能", daily, capacity, daily_ex or mach_ex))

    if not pairs:
        bits = [required_note, cap_note]
        bits = [b for b in bits if b]
        extra = "；".join(bits) if bits else ""
        return [
            _finding(
                rule="F06.11 土方产能不匹配",
                excerpt=daily_ex or days_ex or mach_ex,
                suggestion="无法比对：交叉核验所需的日开挖量 / 工期 / 挖机台数不全。" + (extra and f"已掌握：{extra}"),
                severity="建议",
            )
        ]

    findings: list[dict] = []
    for label, a, b, excerpt in pairs:
        if b == 0:
            continue
        dev = abs(a - b) / abs(b) * 100.0
        if dev <= dev_ok:
            continue
        assume = f"台班产量按默认 {default_yield:g} m³/台班 估算。" if assumed else ""
        daily_note = f"标书日开挖量 {_fmt(daily, 'm³/天')}。" if daily is not None else ""
        findings.append(
            _finding(
                rule="F06.11 土方产能不匹配",
                excerpt=excerpt,
                suggestion=(
                    f"{label}偏差 {dev:.1f}%（阈值 ±{dev_ok:g}%）。"
                    f"{required_note + '。' if required_note else ''}"
                    f"{cap_note + '。' if cap_note else ''}"
                    f"{daily_note}"
                    f"{assume}请调整工期、挖机台数或台班产量，使产能覆盖清单土方。"
                ),
                severity="扣分",
            )
        )
    return findings


def compare(agg: BoqAgg, bid: BidQty, thresholds: dict | None = None) -> list[dict]:
    """三条确定性比对，可供单测注入抽取结果。"""
    dev_ok = _threshold(thresholds, "qty_deviation_ok", 5)
    mismatch = _threshold(thresholds, "qty_material_mismatch", 2)
    default_yield = _threshold(thresholds, "excavator_m3_per_shift", 400)
    findings: list[dict] = []
    if not agg.has_rows:
        findings.append(
            _finding(
                rule="F06.09 清单与施组总量无法比对",
                excerpt="",
                suggestion="无法比对：招标解析未抽出工程量清单行（需 xlsx 清单）。本模块不视为一致通过。",
                severity="建议",
            )
        )
        return findings
    if bid.extract_failed:
        findings.append(
            _finding(
                rule="F06.09 清单与施组总量无法比对",
                excerpt="",
                suggestion=f"无法比对：{bid.extract_reason or '未能从标书抽出工程量原文'}。清单已汇总但未与施组数字核对。",
                severity="建议",
            )
        )
        findings.extend(_compare_materials(agg, BidQty(has_material_plan=False), mismatch)[:1])
        findings.extend(_compare_capacity(agg, BidQty(), dev_ok, default_yield)[:1])
        return findings
    findings.extend(_compare_totals(agg, bid, dev_ok))
    findings.extend(_compare_materials(agg, bid, mismatch))
    findings.extend(_compare_capacity(agg, bid, dev_ok, default_yield))
    return findings


def _worst(findings: list[dict]) -> dict | None:
    if not findings:
        return None
    return max(findings, key=lambda f: _SEVERITY_RANK.get(f.get("severity") or "", 0))


def module_score(findings: list[dict], *, no_boq: bool = False) -> dict:
    meta = next((m for m in rules_data.TECH_SCORE_MODULES if m["key"] == "qty_logic"), {})
    max_score = meta.get("score", 10)
    if no_boq:
        return {
            "key": "qty_logic",
            "module": meta.get("module", "工程量逻辑匹配"),
            "maxScore": max_score,
            "score": round(max_score * (1 - _SEVERITY_DEDUCT_RATIO["无法比对"]), 1),
            "status": "无法比对",
            "summary": (findings[0]["suggestion"] if findings else "招标清单未抽出工程量，无法比对"),
        }
    if not findings:
        return {
            "key": "qty_logic",
            "module": meta.get("module", "工程量逻辑匹配"),
            "maxScore": max_score,
            "score": max_score,
            "status": "达标",
            "summary": "清单与施组总量、主材采购、土方产能交叉核验通过",
        }
    worst = _worst(findings)
    severity = worst["severity"] if worst else "建议"
    if all("无法比对" in (f.get("suggestion") or "") or "无法比对" in (f.get("rule") or "") for f in findings) and severity == "建议":
        status = "无法比对"
        ratio = _SEVERITY_DEDUCT_RATIO["无法比对"]
    else:
        status = severity
        ratio = _SEVERITY_DEDUCT_RATIO.get(severity, 0.15)
    score = max(0.0, round(max_score - max_score * ratio, 1))
    summary = "；".join(dict.fromkeys((f.get("suggestion") or "")[:80] for f in findings if f.get("suggestion")))
    return {
        "key": "qty_logic",
        "module": meta.get("module", "工程量逻辑匹配"),
        "maxScore": max_score,
        "score": score,
        "status": status,
        "summary": summary[:240] or (worst.get("suggestion") if worst else ""),
    }


def evaluate(
    full_text: str,
    paragraphs: list[dict] | None = None,
    dimensions: list | None = None,
    thresholds: dict | None = None,
    extracted: BidQty | None = None,
) -> tuple[list[dict], dict]:
    """返回 (L3 findings, tech_modules 一行)。extracted 传入则跳过 LLM，供单测。"""
    agg = qty_boq.aggregate(dimensions)
    bid = extracted if extracted is not None else extract_from_bid(paragraphs, full_text or "")
    findings = compare(agg, bid, thresholds)
    return findings, module_score(findings, no_boq=not agg.has_rows)
