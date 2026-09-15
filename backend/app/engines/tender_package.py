"""工程标招标文件包：正文 / 答疑补遗 / 工程量清单 / 其他材料 / 施工图纸。

解析时按类型分别抽文后合成一把尺子；图纸不整卷灌进模型。
缺类在页面上固定展示「未能上传该类型文件」。
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from xml.etree import ElementTree as ET
from typing import Any, Iterable

MISSING_HINT = "未能上传该类型文件"

KIND_MAIN = "main"
KIND_ADDENDUM = "addendum"
KIND_BOQ = "boq"
KIND_QUOTE = "quote"
KIND_DRAWING = "drawing"

KIND_SLOTS: list[dict[str, str]] = [
    {
        "key": KIND_MAIN,
        "label": "招标文件正文",
        "accept": ".docx,.pdf",
        "formats": "Word / PDF",
        "hint": "投标人须知、评标办法、合同条款",
    },
    {
        "key": KIND_ADDENDUM,
        "label": "答疑补遗",
        "accept": ".docx,.pdf",
        "formats": "Word / PDF",
        "hint": "澄清、补遗、答疑纪要",
    },
    {
        "key": KIND_BOQ,
        "label": "工程量清单",
        "accept": ".xlsx,.xls,.docx,.pdf",
        "formats": "Excel / Word / PDF",
        "hint": "清单、控制价、工程量明细",
    },
    {
        "key": KIND_QUOTE,
        "label": "其他",
        "accept": "*",
        "formats": "任意格式",
        "hint": "补充材料；评审条款写入评分尺子",
    },
    {
        "key": KIND_DRAWING,
        "label": "施工图纸",
        "accept": ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp",
        "formats": "PDF / 图片",
        "hint": "只抽取设计说明，不识读图面与国标",
    },
]

KIND_KEYS = {s["key"] for s in KIND_SLOTS}
KIND_LABELS = {s["key"]: s["label"] for s in KIND_SLOTS}

DOC_EXTS = {".docx", ".pdf"}
XLS_EXTS = {".xlsx", ".xls"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
TEXT_EXTS = {".txt", ".csv", ".md", ".html", ".htm"}
PPT_EXTS = {".pptx"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z"}
BLOCKED_EXTS = {".exe", ".bat", ".cmd", ".com", ".msi", ".dll", ".scr", ".ps1", ".js"}
ALLOWED_EXTS = DOC_EXTS | XLS_EXTS | IMAGE_EXTS | TEXT_EXTS | PPT_EXTS | ARCHIVE_EXTS | {".ppt", ".doc"}

_TEXT_CAPS = {
    KIND_MAIN: 400_000,
    KIND_ADDENDUM: 200_000,
    KIND_BOQ: 80_000,
    KIND_QUOTE: 80_000,
    KIND_DRAWING: 8_000,
}

_PARSE_ORDER = [KIND_MAIN, KIND_BOQ, KIND_QUOTE, KIND_DRAWING, KIND_ADDENDUM]

_NS_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def normalize_kind(kind: str | None, filename: str = "") -> str:
    raw = (kind or "").strip().lower()
    if raw in KIND_KEYS:
        return raw
    return guess_kind(filename)


def guess_kind(filename: str) -> str:
    name = (filename or "").lower()
    if any(k in name for k in ("答疑", "补遗", "澄清", "addendum", "clarif")):
        return KIND_ADDENDUM
    if any(k in name for k in ("报价", "投标报价", "quote", "price")):
        return KIND_QUOTE
    if any(k in name for k in ("图纸", "图册", "施工图", "drawing", "dwg")):
        return KIND_DRAWING
    if any(k in name for k in ("清单", "工程量", "boq", "控制价", "工程量清单")):
        return KIND_BOQ
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in IMAGE_EXTS:
        return KIND_DRAWING
    if ext in XLS_EXTS:
        return KIND_BOQ
    return KIND_MAIN


def effective_kind(stored: str | None, filename: str) -> str:
    """列表/解析分组：显式非正文类型优先；历史默认 main 时按文件名再猜一次。"""
    raw = (stored or "").strip().lower()
    if raw in KIND_KEYS and raw != KIND_MAIN:
        return raw
    guessed = guess_kind(filename)
    if raw == KIND_MAIN and guessed != KIND_MAIN:
        return guessed
    return raw if raw in KIND_KEYS else guessed


def package_slots(docs: Iterable[Any]) -> list[dict]:
    by_kind: dict[str, list[dict]] = {k: [] for k in KIND_KEYS}
    for doc in docs:
        filename = getattr(doc, "filename", None) or (doc.get("filename") if isinstance(doc, dict) else "")
        stored = getattr(doc, "kind", None) if not isinstance(doc, dict) else doc.get("kind")
        doc_id = getattr(doc, "id", None) if not isinstance(doc, dict) else doc.get("id")
        size = getattr(doc, "size_bytes", None) if not isinstance(doc, dict) else doc.get("sizeBytes") or doc.get("size_bytes")
        kind = effective_kind(stored, filename or "")
        by_kind.setdefault(kind, []).append(
            {
                "id": doc_id,
                "filename": filename,
                "sizeBytes": int(size or 0),
                "kind": kind,
            }
        )
    slots: list[dict] = []
    for spec in KIND_SLOTS:
        files = by_kind.get(spec["key"]) or []
        uploaded = bool(files)
        slots.append(
            {
                "kind": spec["key"],
                "label": spec["label"],
                "uploaded": uploaded,
                "missingHint": "" if uploaded else MISSING_HINT,
                "files": files,
                "excerpt": "",
                "displayIn": KIND_DISPLAY.get(spec["key"], ""),
                "jumpKey": KIND_JUMP.get(spec["key"], "basic"),
            }
        )
    return slots


KIND_DISPLAY = {
    KIND_MAIN: "写入右侧全部固定指标（基础审核、资格与合规、技术/商务评分、废标风险等）；专用合同条款写入「商务评分」",
    KIND_ADDENDUM: "与正文冲突时以补遗为准，覆盖写入各相关维度；合同技术指标以答疑最新口径覆盖",
    KIND_BOQ: "「清单、图纸与其他」→ 工程量清单（项目名称、计量单位、工程数量、备注）",
    KIND_QUOTE: "「其他材料」提炼摘要；含评审条款时写入评分尺子，不写入报价评审",
    KIND_DRAWING: "「清单、图纸与其他」→ 图纸（仅抽取设计说明，多页合并）",
}

KIND_JUMP = {
    KIND_MAIN: "basic",
    KIND_ADDENDUM: "basic",
    KIND_BOQ: "quantity",
    KIND_QUOTE: "quantity",
    KIND_DRAWING: "quantity",
}


def attach_extracts(slots: list[dict], parts: list[dict], max_chars: int = 6000) -> list[dict]:
    """把各类型抽到的原文挂到 package 槽位上，供解析页「文件包解读」展示。"""
    texts: dict[str, list[str]] = {}
    for part in parts:
        kind = part.get("kind") or KIND_MAIN
        name = part.get("filename") or "未命名"
        body = (part.get("text") or "").strip()
        texts.setdefault(kind, []).append(f"【{name}】\n{body}" if body else f"【{name}】（未能抽出文字）")
    out: list[dict] = []
    for slot in slots:
        kind = slot.get("kind") or KIND_MAIN
        item = dict(slot)
        excerpt = "\n\n".join(texts.get(kind) or [])
        item["excerpt"] = excerpt[:max_chars] if item.get("uploaded") else ""
        item["displayIn"] = KIND_DISPLAY.get(kind, slot.get("displayIn") or "")
        item["jumpKey"] = KIND_JUMP.get(kind, slot.get("jumpKey") or "basic")
        out.append(item)
    return out


def extract_xlsx_text(path: str, max_chars: int = 80_000) -> str:
    try:
        zf = zipfile.ZipFile(path)
    except Exception:
        return ""
    strings: list[str] = []
    try:
        with zf.open("xl/sharedStrings.xml") as fh:
            root = ET.parse(fh).getroot()
        for si in root.findall(f"{{{_NS_SS}}}si"):
            texts = [t.text or "" for t in si.iter(f"{{{_NS_SS}}}t")]
            strings.append("".join(texts))
    except KeyError:
        strings = []
    except Exception:
        strings = []

    sheets = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    lines: list[str] = []
    total = 0
    for sheet_name in sheets:
        try:
            with zf.open(sheet_name) as fh:
                root = ET.parse(fh).getroot()
        except Exception:
            continue
        rows: dict[int, list[str]] = {}
        for cell in root.iter(f"{{{_NS_SS}}}c"):
            ref = cell.get("r") or ""
            row_i = 0
            for i, ch in enumerate(ref):
                if ch.isdigit():
                    try:
                        row_i = int(ref[i:])
                    except ValueError:
                        row_i = 0
                    break
            val = _xlsx_cell_value(cell, strings)
            if val:
                rows.setdefault(row_i, []).append(val)
        for i in sorted(rows):
            line = " | ".join(rows[i])
            if not line.strip():
                continue
            lines.append(line)
            total += len(line) + 1
            if total >= max_chars:
                break
        if total >= max_chars:
            break
    return "\n".join(lines)[:max_chars]


def _xlsx_cell_value(cell: ET.Element, strings: list[str]) -> str:
    t = cell.get("t")
    v = cell.find(f"{{{_NS_SS}}}v")
    is_el = cell.find(f"{{{_NS_SS}}}is")
    val = ""
    if t == "s" and v is not None and (v.text or "").isdigit():
        idx = int(v.text or "0")
        if 0 <= idx < len(strings):
            val = strings[idx]
    elif t == "inlineStr" and is_el is not None:
        val = "".join(n.text or "" for n in is_el.iter(f"{{{_NS_SS}}}t"))
    elif v is not None and v.text:
        val = v.text
    return " ".join(val.split())


def extract_pptx_text(path: str, max_chars: int = 80_000) -> str:
    try:
        zf = zipfile.ZipFile(path)
    except Exception:
        return ""
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    slides = sorted(n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
    lines: list[str] = []
    total = 0
    for name in slides:
        try:
            root = ET.parse(zf.open(name)).getroot()
        except Exception:
            continue
        for node in root.iter(f"{ns}t"):
            val = (node.text or "").strip()
            if not val:
                continue
            lines.append(val)
            total += len(val) + 1
            if total >= max_chars:
                break
        if total >= max_chars:
            break
    return "\n".join(lines)[:max_chars]


def extract_plain_text(path: str, ext: str = ".txt", max_chars: int = 80_000) -> str:
    try:
        raw = open(path, "rb").read()
    except Exception:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    if ext in {".html", ".htm"}:
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())[:max_chars]


_OTHER_FIELDS = (
    "文件摘要",
    "评分因素与标准",
    "否决/废标条款",
    "资格与门槛补充",
    "格式与递交要求",
    "技术指标与加分项",
)
_OTHER_SYSTEM = """你是招标文件解析助手。阅读「其他」材料全文，提炼给人看的摘要，并抽出评审相关条款。
只返回严格 JSON：
{"mo-1": {"文件摘要": "", "评分因素与标准": "", "否决/废标条款": "", "资格与门槛补充": "", "格式与递交要求": "", "技术指标与加分项": ""}}
要求：
1. 字段名必须原样使用，没有的填空字符串；
2. 文件摘要：忠实归纳材料用途与要点，不超过 400 字，不要整段粘贴原文；
3. 评分因素与标准、技术指标与加分项：保留分值、百分比、期限等数字，逐条列出；
4. 否决/废标条款、资格与门槛、格式与递交：有则提炼，无则空；
5. 禁止写入评标基准价、偏差率、报价得分等报价公式；
6. 不要编造材料中未出现的条款。"""


_CONTRACT_SECTIONS: dict[str, tuple[str, ...]] = {
    "ct-1": (
        "工程专业（市政/房建/公路/水利等）",
        "进度计划确认与修订时限",
        "材料、工艺与验收标准",
        "质量检测与实测实量要求",
        "安全文明施工量化要求",
        "监理/发包人确认时限",
        "违约、索赔与工期奖罚",
        "其他技术加分相关条款",
    ),
    "ct-2": (
        "管线迁改与保护",
        "交通组织与占道施工",
        "道路、桥梁与管网施工要求",
        "排水、绿化与移交标准",
    ),
    "ct-3": (
        "结构形式与主要材料",
        "装修装饰与节能要求",
        "起重机械与危大工程",
        "样板引路与实测实量",
    ),
    "ct-4": (
        "公路交通专项技术要求",
        "水利农田专项技术要求",
        "电力通信专项技术要求",
    ),
}
_SPECIALTY_LABELS = {
    "municipal": "市政工程",
    "building": "房建工程",
    "highway": "公路交通工程",
    "water": "水利/农田工程",
    "general": "综合/未明确",
}
_CONTRACT_HINTS = (
    "专用合同条款",
    "通用合同条款",
    "发包人要求",
    "技术标准和要求",
    "进度计划",
    "监理工程师",
    "监理人",
    "验收标准",
    "安全文明",
    "实测实量",
    "危大工程",
    "管线迁改",
    "交通组织",
    "样板引路",
    "材料要求",
    "工期奖罚",
    "违约责任",
    "确认期限",
    "修订申请",
)
_CONTRACT_CAPS = {
    KIND_MAIN: 70_000,
    KIND_ADDENDUM: 50_000,
    KIND_BOQ: 12_000,
    KIND_QUOTE: 30_000,
    KIND_DRAWING: 8_000,
}
_CONTRACT_SYSTEM = """你是工程招标解析助手。通读全部材料中的专用合同条款、发包人要求、技术标准，
提炼与技术评审、技术标加分相关的量化指标、时限、材料工艺、验收检测、安全文明要求。
合同里的进度确认期限、材料品牌/工艺、验收检测、监理确认时限等，往往也是招标书加分项，必须收录。
只返回严格 JSON，字段名必须原样使用，没有的填空字符串：
{
  "ct-1": {
    "工程专业（市政/房建/公路/水利等）": "",
    "进度计划确认与修订时限": "",
    "材料、工艺与验收标准": "",
    "质量检测与实测实量要求": "",
    "安全文明施工量化要求": "",
    "监理/发包人确认时限": "",
    "违约、索赔与工期奖罚": "",
    "其他技术加分相关条款": ""
  },
  "ct-2": {
    "管线迁改与保护": "",
    "交通组织与占道施工": "",
    "道路、桥梁与管网施工要求": "",
    "排水、绿化与移交标准": ""
  },
  "ct-3": {
    "结构形式与主要材料": "",
    "装修装饰与节能要求": "",
    "起重机械与危大工程": "",
    "样板引路与实测实量": ""
  },
  "ct-4": {
    "公路交通专项技术要求": "",
    "水利农田专项技术要求": "",
    "电力通信专项技术要求": ""
  }
}
要求：
1. 保留条款号、天数、百分比、强度等级等数字，逐条列出，禁止用「详见合同」代替；
2. 市政项目重点填 ct-2，房建重点填 ct-3，公路/水利/电力填 ct-4；不相关专业整组留空，不要编造；
3. 答疑补遗与正文冲突时只保留答疑口径；
4. 工程专业字段填写市政工程/房建工程/公路交通工程/水利/农田工程/综合 之一；
5. 不要输出上述板块以外的键。"""


def guess_engineering_specialty(project_name: str = "", project_type: str = "", text: str = "") -> str:
    blob = f"{project_type} {project_name} {(text or '')[:12000]}"
    scores = {
        "building": sum(1 for k in ("房建", "房屋建筑", "住宅", "公建", "装修装饰", "基坑支护", "主体结构", "建筑装饰") if k in blob),
        "municipal": sum(1 for k in ("市政", "道路", "管网", "排水", "桥梁", "给水", "污水", "绿化", "燃气", "综合管廊") if k in blob),
        "highway": sum(1 for k in ("公路", "高速", "路面", "路基") if k in blob),
        "water": sum(1 for k in ("水利", "农田", "灌区", "泵站", "河道", "高标准农田") if k in blob),
    }
    if project_type == "交通":
        scores["highway"] += 2
        scores["municipal"] += 1
    best = max(scores, key=lambda k: scores[k])
    if scores[best] <= 0:
        return "general"
    return best


def _contract_windows(text: str, max_chars: int) -> str:
    if not text:
        return ""
    hits: list[tuple[int, int]] = []
    for key in _CONTRACT_HINTS:
        start = 0
        while True:
            i = text.find(key, start)
            if i < 0:
                break
            hits.append((max(0, i - 160), min(len(text), i + 8000)))
            start = i + max(len(key), 1)
            if len(hits) >= 48:
                break
        if len(hits) >= 48:
            break
    if not hits:
        return text[: min(max_chars, 40_000)]
    hits.sort()
    merged: list[list[int]] = []
    for a, b in hits:
        if merged and a <= merged[-1][1] + 120:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    parts = [text[a:b] for a, b in merged]
    return ("\n…\n".join(parts))[:max_chars]


def compose_contract_corpus(parts: list[dict]) -> str:
    """从全部文件中截取专用合同条款/技术要求相关段落，答疑补遗放最后。"""
    blocks = [
        "以下为全部招标文件中与合同条款、技术要求相关的摘录。"
        "权威顺序：答疑补遗高于招标文件正文。"
        "重点阅读专用合同条款、发包人要求、技术标准中与技术评审和加分相关的量化指标与时限。"
    ]
    for kind in _PARSE_ORDER:
        label = KIND_LABELS.get(kind, kind)
        for part in parts:
            if part.get("kind") != kind:
                continue
            if kind == KIND_DRAWING:
                continue
            name = part.get("filename") or "未命名"
            body = (part.get("text") or "").strip()
            if not body or "未能抽取正文" in body or "未能抽出文字" in body:
                continue
            sliced = _contract_windows(body, _CONTRACT_CAPS.get(kind, 20_000))
            if not sliced.strip():
                continue
            blocks.append(f"\n===== 【{label}】{name} =====\n{sliced}")
    return "\n".join(blocks)


def _empty_contract_fills(specialty_label: str = "") -> dict:
    fills = {sec_id: {key: "" for key in labels} for sec_id, labels in _CONTRACT_SECTIONS.items()}
    if specialty_label:
        fills["ct-1"]["工程专业（市政/房建/公路/水利等）"] = specialty_label
    return fills


def _merge_contract_fills(dst: dict, src: dict) -> None:
    for sec_id, labels in _CONTRACT_SECTIONS.items():
        incoming = src.get(sec_id)
        if not isinstance(incoming, dict):
            incoming = src
        bucket = dst.setdefault(sec_id, {})
        for key in labels:
            val = incoming.get(key) if isinstance(incoming, dict) else ""
            if not isinstance(val, str):
                continue
            val = val.strip()
            if not val:
                continue
            old = (bucket.get(key) or "").strip()
            if not old:
                bucket[key] = val
            elif val in old:
                continue
            elif old in val:
                bucket[key] = val
            else:
                bucket[key] = old + "\n\n" + val


def extract_contract_tech_fills(
    text: str,
    *,
    specialty: str = "general",
    specialty_label: str = "",
) -> dict:
    """从全部文件的合同/技术要求摘录中抽取技术评审相关指标。"""
    blob = (text or "").strip()
    fills = _empty_contract_fills(specialty_label or _SPECIALTY_LABELS.get(specialty, ""))
    if not blob:
        return fills
    try:
        from .llm import chat_complete, get_default_model_id

        model_id = get_default_model_id()
    except Exception:
        return fills

    chunks: list[str] = []
    start = 0
    size, overlap = 36000, 4000
    while start < len(blob):
        end = min(len(blob), start + size)
        chunks.append(blob[start:end])
        if end >= len(blob):
            break
        start = max(end - overlap, start + 1)

    focus = _SPECIALTY_LABELS.get(specialty, "综合/未明确")
    for index, chunk in enumerate(chunks, start=1):
        hint = (
            f"本项目工程专业判定为「{focus}」。"
            "市政重点填市政板块，房建填房建板块，公路/水利/电力填其他专业；不相关留空。"
            f"以下是摘录的第 {index}/{len(chunks)} 段。\n\n"
        )
        try:
            raw = chat_complete(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": _CONTRACT_SYSTEM},
                    {"role": "user", "content": hint + chunk},
                ],
                temperature=0.1,
                timeout=180,
                max_tokens=4096,
                extra={"response_format": {"type": "json_object"}},
            )
        except Exception:
            continue
        payload = (raw or "").strip()
        if payload.startswith("```"):
            payload = payload.strip("`")
            payload = payload.split("\n", 1)[-1]
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if isinstance(data, dict):
            inner = data.get("fills") if isinstance(data.get("fills"), dict) else data
            if isinstance(inner, dict):
                _merge_contract_fills(fills, inner)
    if specialty_label and not (fills.get("ct-1") or {}).get("工程专业（市政/房建/公路/水利等）"):
        fills["ct-1"]["工程专业（市政/房建/公路/水利等）"] = specialty_label
    return fills


def extract_other_eval_fills(text: str) -> dict:
    """从其他材料抽出摘要与评审条款，供解析页展示并派生评分尺子。"""
    blob = (text or "").strip()
    if not blob:
        return {}
    blob = blob[:80_000]
    empty = {k: "" for k in _OTHER_FIELDS}
    empty["文件摘要"] = re.sub(r"\s+", " ", blob)[:400]
    try:
        from .llm import chat_complete, get_default_model_id

        model_id = get_default_model_id()
        raw = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": _OTHER_SYSTEM},
                {"role": "user", "content": "请提炼下列其他材料：\n\n" + blob},
            ],
            temperature=0.1,
            timeout=120,
            max_tokens=4096,
            extra={"response_format": {"type": "json_object"}},
        )
    except Exception:
        return {"mo-1": empty}
    payload = (raw or "").strip()
    if payload.startswith("```"):
        payload = payload.strip("`")
        payload = payload.split("\n", 1)[-1]
    try:
        data = json.loads(payload)
    except Exception:
        return {"mo-1": empty}
    if not isinstance(data, dict):
        return {"mo-1": empty}
    sec = data.get("mo-1") if isinstance(data.get("mo-1"), dict) else data
    fields = {}
    for key in _OTHER_FIELDS:
        val = sec.get(key) if isinstance(sec, dict) else ""
        fields[key] = val.strip() if isinstance(val, str) else ""
    if not any(fields.values()):
        fields["文件摘要"] = empty["文件摘要"]
    return {"mo-1": fields}


def extract_image_text(path: str) -> tuple[str, str]:
    from .ocr import ocr_image_path

    text, status = ocr_image_path(path)
    return (text or "").strip(), status


def extract_file_text(path: str, *, kind: str = KIND_MAIN, filename: str = "") -> str:
    """按扩展名抽文；图纸类截短，避免整卷 CAD/扫描件撑爆模型。"""
    ext = os.path.splitext((filename or path) or "")[1].lower()
    cap = _TEXT_CAPS.get(kind, 80_000)
    if ext == ".xls":
        return "该文件为旧版 .xls，未能抽取单元格文字。请另存为 .xlsx 后重新上传。"
    if ext == ".xlsx":
        return extract_xlsx_text(path, max_chars=cap)
    if ext == ".pptx":
        return extract_pptx_text(path, max_chars=cap)
    if ext in TEXT_EXTS:
        return extract_plain_text(path, ext=ext, max_chars=cap)
    if ext in ARCHIVE_EXTS or ext in {".ppt", ".doc"}:
        return f"已上传「{filename or os.path.basename(path)}」，该格式仅存档，未能抽取正文。"
    if ext in IMAGE_EXTS:
        text, status = extract_image_text(path)
        if text:
            return text[:cap]
        if status == "unavailable":
            return "施工图纸/图片已上传，当前环境未启用 OCR，未能识别图面文字。"
        return "施工图纸/图片已上传，扫描件未识别到文字。"
    from .docx_extract import extract_full_text

    if ext == ".pdf":
        text = extract_full_text(path)
        if kind == KIND_DRAWING:
            return (text or "")[:cap]
        return (text or "")[:cap] if kind != KIND_MAIN else (text or "")[: _TEXT_CAPS[KIND_MAIN]]
    if ext == ".docx":
        text = extract_full_text(path)
        return (text or "")[:cap]
    return ""


def extract_as_paragraphs(path: str, filename: str = "") -> list[dict]:
    ext = os.path.splitext((filename or path) or "")[1].lower()
    if ext == ".docx":
        from .docx_extract import extract_paragraphs

        return extract_paragraphs(path)
    text = extract_file_text(path, kind=guess_kind(filename), filename=filename)
    if not text.strip():
        return []
    out: list[dict] = []
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        out.append(
            {
                "index": i,
                "text": line,
                "style": "",
                "outline_level": None,
            }
        )
        if len(out) >= 4000:
            break
    return out


def compose_parse_text(parts: list[dict], *, include_addendum_body: bool = True) -> tuple[str, dict]:
    """parts: [{kind, filename, text}]. 答疑补遗默认可放入全文末尾；解析抽取时另册覆盖。"""
    grouped: dict[str, list[dict]] = {k: [] for k in KIND_KEYS}
    for part in parts:
        kind = part.get("kind") or KIND_MAIN
        grouped.setdefault(kind, []).append(part)

    chunks: list[str] = [
        "以下文本由多份招标文件包拼接而成。"
        "章节标记为【招标文件正文】【答疑补遗】【工程量清单】【其他】【施工图纸】。"
        "权威顺序：答疑补遗高于招标文件正文，高于工程量清单，高于施工图纸。"
        "若答疑补遗与正文冲突，只保留答疑补遗口径，不得把两种说法并列。"
        "工程量清单规则写入「清单、图纸与技术标准」。"
        "【其他】材料另册提炼，禁止写入报价评审字段。"
        "施工图纸另册只抽设计说明，不把整卷图纸当作招标条款。",
    ]
    notes: dict[str, list[str]] = {k: [] for k in KIND_KEYS}
    for kind in _PARSE_ORDER:
        label = KIND_LABELS.get(kind, kind)
        for part in grouped.get(kind) or []:
            name = part.get("filename") or "未命名"
            notes[kind].append(name)
            if kind == KIND_DRAWING:
                chunks.append(
                    f"\n===== 【{label}】{name} =====\n（施工图纸另册只抽设计说明，不把整卷图纸当作招标条款。）"
                )
                continue
            if kind == KIND_QUOTE:
                chunks.append(
                    f"\n===== 【{label}】{name} =====\n（其他材料另册提炼，不写入报价评审。）"
                )
                continue
            if kind == KIND_ADDENDUM and not include_addendum_body:
                chunks.append(
                    f"\n===== 【{label}】{name} =====\n（答疑补遗另册抽取；与正文冲突时以答疑补遗为准并覆盖。）"
                )
                continue
            body = (part.get("text") or "").strip()
            if not body:
                chunks.append(f"\n===== 【{label}】{name} =====\n（未能抽出文字。）")
                continue
            chunks.append(f"\n===== 【{label}】{name} =====\n{body}")
    return "\n".join(chunks), notes


def compose_addendum_text(parts: list[dict]) -> str:
    """只拼接答疑补遗正文，供第二遍抽取覆盖招标文件。"""
    blocks: list[str] = [
        "以下仅为答疑补遗/澄清材料。"
        "与招标文件正文、工程量清单冲突时，一律以本材料为准。"
        "只抽取本材料明确变更、补充或重申的条款；未提及的字段填空，不要用招标正文填回来。"
    ]
    n = 0
    for part in parts:
        if part.get("kind") != KIND_ADDENDUM:
            continue
        name = part.get("filename") or "未命名"
        body = (part.get("text") or "").strip()
        n += 1
        if not body:
            blocks.append(f"\n===== 【答疑补遗】{name} =====\n（未能抽出文字。）")
            continue
        blocks.append(f"\n===== 【答疑补遗】{name} =====\n{body}")
    if n == 0:
        return ""
    return "\n".join(blocks)


def extra_fills_from_package(
    parts: list[dict],
    notes: dict[str, list[str]],
    *,
    project_name: str = "",
    project_type: str = "",
    category: str = "",
) -> dict:
    """工程量清单按 Excel 列抽出；图纸文件名写入固定字段；工程类另抽专用合同条款。"""
    items: list[dict[str, str]] = []
    for part in parts:
        if part.get("kind") != KIND_BOQ:
            continue
        for row in part.get("boqItems") or []:
            if isinstance(row, dict):
                items.append(row)
    qb = _boq_fields_from_items(items)

    other_text = "\n\n".join(
        f"【{p.get('filename') or '未命名'}】\n{(p.get('text') or '').strip()}"
        for p in parts
        if p.get("kind") == KIND_QUOTE
        and (p.get("text") or "").strip()
        and "未能抽取正文" not in (p.get("text") or "")
        and "未能抽出文字" not in (p.get("text") or "")
    )
    other_fills = extract_other_eval_fills(other_text) if other_text else {}

    drawing_names = notes.get(KIND_DRAWING) or []
    qd: dict[str, str] = {}
    if drawing_names:
        qd["图纸文件"] = "；".join(drawing_names)

    fills: dict = {}
    if any(qb.values()):
        fills["qty-boq"] = {"qb-1": qb}
    if other_fills:
        fills["misc-other"] = other_fills
    if qd:
        fills["qty-drawing"] = {"qd-1": qd}
    if category == "工程类":
        corpus = compose_contract_corpus(parts)
        specialty = guess_engineering_specialty(project_name, project_type, corpus)
        label = _SPECIALTY_LABELS.get(specialty, "综合/未明确")
        if "=====" in corpus:
            fills["contract-tech"] = extract_contract_tech_fills(
                corpus,
                specialty=specialty,
                specialty_label=label,
            )
        else:
            fills["contract-tech"] = _empty_contract_fills(label)
    return fills


def _boq_fields_from_items(items: list[dict[str, str]]) -> dict[str, str]:
    names: list[str] = []
    units: list[str] = []
    qtys: list[str] = []
    remarks: list[str] = []
    for row in items:
        name = _one_line(row.get("name") or "")
        unit = _one_line(row.get("unit") or "")
        qty = _one_line(row.get("qty") or "")
        remark = _one_line(row.get("remark") or "")
        if not (name or unit or qty or remark):
            continue
        names.append(name)
        units.append(unit)
        qtys.append(qty)
        remarks.append(remark)
    if not names:
        return {}
    return {
        "项目名称": "\n".join(names),
        "计量单位": "\n".join(units),
        "工程数量": "\n".join(qtys),
        "备注": "\n".join(remarks),
    }


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


_BOQ_NAME_ALIASES = ("项目名称", "工程项目名称")
_BOQ_UNIT_ALIASES = ("计量单位", "单位")
_BOQ_QTY_ALIASES = ("工程数量", "工程量")
_BOQ_REMARK_ALIASES = ("备注",)
_BOQ_NOISE_EXACT = {
    "序号",
    "项目名称",
    "工程项目名称",
    "计量单位",
    "工程数量",
    "单价（元）",
    "合价（元）",
    "金额（元）",
    "备注",
    "单位",
    "数量",
    "合计",
    "项目编码",
}


def extract_boq_items(path: str, filename: str = "") -> list[dict[str, str]]:
    """从工程量清单 xlsx 抽出项目名称、计量单位、工程数量、备注（含分部标题行）。"""
    ext = os.path.splitext((filename or path) or "")[1].lower()
    if ext != ".xlsx":
        return []
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for _sheet, rows in _iter_xlsx_grids(path):
        colmap: dict[str, int] | None = None
        for row_i in sorted(rows):
            cells = rows[row_i]
            header = _boq_header_map(cells)
            if header:
                colmap = header
                continue
            if not colmap:
                continue
            item = {
                "name": _one_line(cells.get(colmap["name"], "")),
                "unit": _one_line(cells.get(colmap["unit"], "")),
                "qty": _one_line(cells.get(colmap["qty"], "")),
                "remark": _one_line(cells.get(colmap.get("remark", -1), "")),
            }
            if _is_boq_noise_name(item["name"]):
                continue
            if not item["name"]:
                continue
            key = (item["name"], item["unit"], item["qty"], item["remark"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _boq_header_map(cells: dict[int, str]) -> dict[str, int] | None:
    name_col = _pick_header_col(cells, _BOQ_NAME_ALIASES)
    unit_col = _pick_header_col(cells, _BOQ_UNIT_ALIASES)
    qty_col = _pick_header_col(cells, _BOQ_QTY_ALIASES)
    if name_col is None or unit_col is None or qty_col is None:
        return None
    mapping = {"name": name_col, "unit": unit_col, "qty": qty_col}
    remark_col = _pick_header_col(cells, _BOQ_REMARK_ALIASES)
    if remark_col is not None:
        mapping["remark"] = remark_col
    return mapping


def _pick_header_col(cells: dict[int, str], aliases: tuple[str, ...]) -> int | None:
    compact = {col: re.sub(r"\s+", "", val) for col, val in cells.items()}
    for alias in aliases:
        for col, val in compact.items():
            if val == alias:
                return col
    return None


def _is_boq_noise_name(name: str) -> bool:
    compact = re.sub(r"\s+", "", name or "")
    if not compact or compact in _BOQ_NOISE_EXACT:
        return True
    if compact.startswith(("分类分项工程量清单", "措施项目清单", "其他项目清单", "工程项目总价")):
        return True
    if (name or "").startswith(("合同编号", "工程名称")):
        return True
    if "新点水利" in compact or "新点软件" in compact:
        return True
    return False


def _iter_xlsx_grids(path: str) -> list[tuple[str, dict[int, dict[int, str]]]]:
    try:
        zf = zipfile.ZipFile(path)
    except Exception:
        return []
    strings = _xlsx_shared_strings(zf)
    sheets = _xlsx_sheet_targets(zf)
    out: list[tuple[str, dict[int, dict[int, str]]]] = []
    for title, target in sheets:
        try:
            with zf.open(target) as fh:
                root = ET.parse(fh).getroot()
        except Exception:
            continue
        rows: dict[int, dict[int, str]] = {}
        for cell in root.iter(f"{{{_NS_SS}}}c"):
            col, row_i = _xlsx_col_row(cell.get("r") or "")
            if not row_i:
                continue
            val = _xlsx_cell_value(cell, strings)
            if val:
                rows.setdefault(row_i, {})[col] = val
        if rows:
            out.append((title, rows))
    return out


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        with zf.open("xl/sharedStrings.xml") as fh:
            root = ET.parse(fh).getroot()
    except Exception:
        return []
    strings: list[str] = []
    for si in root.findall(f"{{{_NS_SS}}}si"):
        texts = [t.text or "" for t in si.iter(f"{{{_NS_SS}}}t")]
        strings.append("".join(texts))
    return strings


def _xlsx_sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    try:
        wb = ET.parse(zf.open("xl/workbook.xml")).getroot()
        rels = ET.parse(zf.open("xl/_rels/workbook.xml.rels")).getroot()
    except Exception:
        return []
    rid_to_target: dict[str, str] = {}
    for rel in rels:
        rid = rel.get("Id") or ""
        target = (rel.get("Target") or "").lstrip("/")
        if rid and target:
            if not target.startswith("xl/"):
                target = "xl/" + target
            rid_to_target[rid] = target
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    sheets: list[tuple[str, str]] = []
    for sh in wb.findall(f".//{{{_NS_SS}}}sheet"):
        name = sh.get("name") or ""
        rid = sh.get(f"{rns}id") or ""
        target = rid_to_target.get(rid)
        if target:
            sheets.append((name, target))
    return sheets


def _xlsx_col_row(ref: str) -> tuple[int, int]:
    letters = ""
    digits = ""
    for ch in ref or "":
        if ch.isalpha():
            letters += ch
        elif ch.isdigit():
            digits += ch
    col = 0
    for ch in letters.upper():
        col = col * 26 + (ord(ch) - 64)
    try:
        row_i = int(digits)
    except ValueError:
        row_i = 0
    return col, row_i


def _snippet_around(text: str, keys: tuple[str, ...], window: int = 180) -> str:
    if not text:
        return ""
    for key in keys:
        m = re.search(re.escape(key), text)
        if not m:
            continue
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + window)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        if snippet:
            return snippet[:400]
    return ""
