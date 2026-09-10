"""工程标招标文件包：正文 / 答疑补遗 / 工程量清单 / 报价文件 / 施工图纸。

解析时按类型分别抽文后合成一把尺子；图纸不整卷灌进模型。
缺类在页面上固定展示「未能上传该类型文件」。
"""

from __future__ import annotations

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
        "label": "报价文件",
        "accept": ".xlsx,.xls,.docx,.pdf",
        "formats": "Excel / Word / PDF",
        "hint": "报价表、投标报价文件",
    },
    {
        "key": KIND_DRAWING,
        "label": "施工图纸",
        "accept": ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,.docx",
        "formats": "PDF / 图片 / Word",
        "hint": "图纸、图册、扫描件",
    },
]

KIND_KEYS = {s["key"] for s in KIND_SLOTS}
KIND_LABELS = {s["key"]: s["label"] for s in KIND_SLOTS}

DOC_EXTS = {".docx", ".pdf"}
XLS_EXTS = {".xlsx", ".xls"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
ALLOWED_EXTS = DOC_EXTS | XLS_EXTS | IMAGE_EXTS

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
    KIND_MAIN: "写入右侧全部固定指标（基本信息、资格与门槛、评标办法等）",
    KIND_ADDENDUM: "与正文冲突时以补遗为准，覆盖写入各相关维度；原文摘录见「文件包解读」",
    KIND_BOQ: "「清单、图纸与技术标准」→ 工程量清单规则",
    KIND_QUOTE: "「商务/技术/报价评审」中的报价相关字段",
    KIND_DRAWING: "「清单、图纸与技术标准」→ 图纸（图号目录、设计说明与施工要点）",
}

KIND_JUMP = {
    KIND_MAIN: "basic",
    KIND_ADDENDUM: "basic",
    KIND_BOQ: "quantity",
    KIND_QUOTE: "envelope",
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


def compose_parse_text(parts: list[dict]) -> tuple[str, dict]:
    """parts: [{kind, filename, text}]. 答疑补遗放最后，冲突时后段优先生效。"""
    grouped: dict[str, list[dict]] = {k: [] for k in KIND_KEYS}
    for part in parts:
        kind = part.get("kind") or KIND_MAIN
        grouped.setdefault(kind, []).append(part)

    chunks: list[str] = [
        "以下文本由多份招标文件包拼接而成。"
        "章节标记为【招标文件正文】【答疑补遗】【工程量清单】【报价文件】【施工图纸】。"
        "若答疑补遗与正文冲突，以答疑补遗为准。"
        "工程量清单、报价表中的规则优先写入「清单、图纸与技术标准」相关字段。"
        "施工图纸另册识读，不把整卷图纸当作招标条款。",
    ]
    notes: dict[str, list[str]] = {k: [] for k in KIND_KEYS}
    for kind in _PARSE_ORDER:
        label = KIND_LABELS.get(kind, kind)
        for part in grouped.get(kind) or []:
            name = part.get("filename") or "未命名"
            notes[kind].append(name)
            if kind == KIND_DRAWING:
                chunks.append(
                    f"\n===== 【{label}】{name} =====\n（施工图纸另册识读，不把整卷图纸当作招标条款。）"
                )
                continue
            body = (part.get("text") or "").strip()
            if not body:
                chunks.append(f"\n===== 【{label}】{name} =====\n（未能抽出文字。）")
                continue
            chunks.append(f"\n===== 【{label}】{name} =====\n{body}")
    return "\n".join(chunks), notes


def extra_fills_from_package(parts: list[dict], notes: dict[str, list[str]]) -> dict:
    """清单 xlsx / 图纸文件名写入工程类固定字段；原文没有的仍保持空。"""
    boq_text = "\n".join((p.get("text") or "") for p in parts if p.get("kind") == KIND_BOQ)
    quote_text = "\n".join((p.get("text") or "") for p in parts if p.get("kind") == KIND_QUOTE)
    combined = f"{boq_text}\n{quote_text}"
    qb: dict[str, str] = {}
    for label, keys in (
        ("暂列金额", ("暂列金额",)),
        ("暂估价", ("暂估价",)),
        ("安全生产费/不可竞争费比例", ("安全生产", "不可竞争", "规费")),
        ("缺漏/偏差容差（如3%）", ("偏差", "容差", "缺漏项", "3%")),
        ("清单编码名称特征单位数量不得改动条款", ("不得改动", "清单编码", "项目特征", "工程量")),
    ):
        qb[label] = _snippet_around(combined, keys)

    drawing_names = notes.get(KIND_DRAWING) or []
    drawing_text = "\n".join((p.get("text") or "") for p in parts if p.get("kind") == KIND_DRAWING)
    qd: dict[str, str] = {}
    if drawing_names:
        qd["图纸章节位置与图号图名"] = "已上传施工图纸：" + "；".join(drawing_names)
        conflict = _snippet_around(drawing_text, ("冲突", "不一致", "以图纸为准", "以清单为准"))
        if conflict:
            qd["图纸与技术标准冲突时的处理原则"] = conflict

    fills: dict = {}
    if any(qb.values()):
        fills["qty-boq"] = {"qb-1": qb}
    if qd:
        fills["qty-drawing"] = {"qd-1": qd}
    return fills


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
