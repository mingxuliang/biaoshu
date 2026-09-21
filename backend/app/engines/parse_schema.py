"""招标解析固定指标骨架：与前端 src/mocks/parse.ts（软件服务类）/ parseEngineering.ts（工程类）
的一级维度 / 二级分析项目完全对齐。

按项目 category（软件服务类 | 工程类）选用不同的固定骨架文件；同一 category 内部
禁止增删 key、id、label、section id/title、row label。抽取结果填充 rows.content（页面摘要）
和 rows.original（招标原文，供 AI 预审）；找不到时保持空字符串，指标项仍然出现在结果里。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_CATEGORY = "软件服务类"

_SCHEMA_FILES = {
    "软件服务类": "parse_dimension_schema.json",
    "工程类": "parse_dimension_schema_engineering.json",
}
_SCHEMA_CACHE: dict[str, list[dict]] = {}

# 预审 / 撰写仍消费四类尺子：从固定二级项目中派生，不另造解析页指标。
# 软件服务类与工程类的固定骨架 id 不同，按 category 分别配置派生规则。
SCORE_ITEM_IDS_BY_CATEGORY: dict[str, set[str]] = {
    "软件服务类": {
        "eval-tech",
        "eval-business",
        "review-tech",
        "review-service",
        "review-after",
        "business-credit",
        "business-commerce",
        "business-price",
        "pro-standard",
        "misc-other",
    },
    "工程类": {
        "eval-tech",
        "eval-business",
        "env-price",
        "misc-other",
        "contract-tech",
    },
}
MUST_ITEM_TYPES_BY_CATEGORY: dict[str, dict[str, str]] = {
    "软件服务类": {
        "reject-base": "废标条款",
        "reject-forbidden": "废标条款",
        "reject-invalid": "实质性条款",
        "req-invalid": "实质性条款",
    },
    "工程类": {
        "reject-open": "废标条款",
        "reject-qual": "废标条款",
        "reject-conform": "废标条款",
        "reject-eval": "废标条款",
        "reject-other": "废标条款",
        "qual-review": "实质性条款",
    },
}
QUAL_ITEM_IDS_BY_CATEGORY: dict[str, set[str]] = {
    "软件服务类": {"qual-applicant", "qual-capacity", "qual-conformity"},
    "工程类": {
        "qual-license",
        "qual-performance",
        "qual-personnel",
        "qual-finance",
        "qual-credit",
        "qual-equipment",
    },
}
FORMAT_ITEM_IDS_BY_CATEGORY: dict[str, set[str]] = {
    "软件服务类": {
        "req-submit",
        "req-compose",
        "req-seal",
        "req-encrypt",
        "req-format",
        "req-formatrule",
        "req-delivery",
    },
    "工程类": {
        "req-submit",
        "req-compose",
        "req-encrypt",
        "req-format",
        "req-qualdocs",
    },
}

# 兼容旧调用方：未传 category 时按软件服务类走（历史行为不变）。
SCORE_ITEM_IDS = SCORE_ITEM_IDS_BY_CATEGORY[DEFAULT_CATEGORY]
MUST_ITEM_TYPES = MUST_ITEM_TYPES_BY_CATEGORY[DEFAULT_CATEGORY]
QUAL_ITEM_IDS = QUAL_ITEM_IDS_BY_CATEGORY[DEFAULT_CATEGORY]
FORMAT_ITEM_IDS = FORMAT_ITEM_IDS_BY_CATEGORY[DEFAULT_CATEGORY]


def _normalize_category(category: str | None) -> str:
    return category if category in _SCHEMA_FILES else DEFAULT_CATEGORY


def load_schema(category: str | None = DEFAULT_CATEGORY) -> list[dict]:
    key = _normalize_category(category)
    if key not in _SCHEMA_CACHE:
        path = Path(__file__).with_name(_SCHEMA_FILES[key])
        _SCHEMA_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[key]


def empty_tree(category: str | None = DEFAULT_CATEGORY) -> list[dict]:
    """返回完整指标树，全部 content/original 为空、completed 为 false。"""
    tree: list[dict] = []
    for dim in load_schema(category):
        items = []
        for item in dim["items"]:
            sections = []
            for sec in item["sections"]:
                sections.append(
                    {
                        "id": sec["id"],
                        "title": sec["title"],
                        "rows": [
                            {"label": label, "content": "", "original": ""}
                            for label in sec["rows"]
                        ],
                    }
                )
            items.append({"id": item["id"], "label": item["label"], "sections": sections})
        tree.append({"key": dim["key"], "label": dim["label"], "completed": False, "items": items})
    return tree


def coerce_fill(value) -> tuple[str, str]:
    """把抽取结果拆成 (摘要, 原文)。摘要给人看，原文给预审。"""
    if isinstance(value, dict):
        summary = str(
            value.get("摘要") or value.get("summary") or value.get("content") or ""
        ).strip()
        original = str(
            value.get("原文") or value.get("original") or value.get("source") or ""
        ).strip()
        if not summary:
            summary = original
        if not original:
            original = summary
        return summary, original
    if value is None:
        return "", ""
    text = str(value).strip()
    return text, text


def row_body(row: dict) -> str:
    """预审/派生尺子用招标原文；没有原文时退回摘要。"""
    return (row.get("original") or row.get("content") or "").strip()


_SKIP_DISTILL_LABELS = {
    "序号",
    "是否必须",
    "风险等级",
    "计量单位",
    "工程数量",
    "来源/依据",
}
_CLAUSE_HINTS = (
    "投标人应当",
    "投标人应",
    "投标人必须",
    "投标人须",
    "响应文件应当",
    "招标文件规定",
    "本招标文件",
    "详见招标文件",
    "一经发现",
    "按招标文件",
    "根据招标文件",
    "须知前附表",
)
_FLUFF_SENTENCE = re.compile(r"^(详见(招标文件|本章|本节).{0,24}|以招标文件为准|按招标文件执行)$")
_LEAD_IN = re.compile(r"^(投标人|响应人|供应商|承包人)(应当|应|必须|须)")


def _looks_like_raw_clause(text: str) -> bool:
    body = (text or "").replace("【答疑补遗为准】", "").strip()
    if len(body) < 48:
        return False
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if len(lines) >= 3:
        heavy = sum(1 for ln in lines if len(ln) >= 72 or any(h in ln for h in _CLAUSE_HINTS))
        return heavy * 2 >= len(lines)
    if any(h in body for h in _CLAUSE_HINTS) and (body.count("。") >= 1 or len(body) >= 80):
        return True
    return body.count("。") >= 2 and len(body) >= 100


def _compress_sentence(text: str) -> str:
    s = (text or "").strip(" 　，,。；;、")
    if not s:
        return ""
    s = _LEAD_IN.sub("", s).strip(" 　，,")
    s = re.sub(r"^(应当|应|必须|须)", "", s).strip(" 　，,")
    s = s.replace("详见招标文件", "").replace("本招标文件的规定", "").replace("本招标文件规定", "")
    s = re.sub(r"\s{2,}", " ", s).strip(" 　，,。；;")
    if _FLUFF_SENTENCE.match(s) or s in {"详见招标文件", "以招标文件为准"}:
        return ""
    return s


def _compress_clause(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    prefix = ""
    body = raw
    mark = "【答疑补遗为准】"
    if body.startswith(mark):
        prefix = mark
        body = body[len(mark) :].strip()
    lines = body.split("\n")
    if len(lines) >= 2:
        result = "\n".join(_compress_sentence(ln) or ln.strip() for ln in lines)
    else:
        kept = [_compress_sentence(p) for p in re.split(r"[。；;]", body) if p.strip()]
        kept = [x for x in kept if x]
        result = "\n".join(kept) if kept else body
    if not result.strip():
        return raw
    return f"{prefix}{result}" if prefix else result


def _should_distill_row(label: str, content: str, original: str) -> bool:
    if (label or "") in _SKIP_DISTILL_LABELS:
        return False
    text = (content or "").strip()
    if not text:
        return False
    orig = (original or "").strip()
    if orig and text != orig and not _looks_like_raw_clause(text):
        return False
    return _looks_like_raw_clause(text) or (bool(orig) and text == orig and len(text) >= 48)


def ensure_originals(tree: list[dict]) -> None:
    """没有单独原文时，把当前字段当作招标原文留给评标尺子。"""
    for dim in tree:
        for item in dim.get("items") or []:
            for sec in item.get("sections") or []:
                for row in sec.get("rows") or []:
                    content = (row.get("content") or "").strip()
                    original = (row.get("original") or "").strip()
                    if not original and content:
                        row["original"] = content


def distill_display(tree: list[dict]) -> None:
    """页面摘要改写成可扫读事实；不改 original。"""
    for dim in tree:
        for item in dim.get("items") or []:
            for sec in item.get("sections") or []:
                for row in sec.get("rows") or []:
                    content = (row.get("content") or "").strip()
                    original = (row.get("original") or "").strip()
                    if _should_distill_row(row.get("label") or "", content, original):
                        distilled = _compress_clause(content)
                        if distilled and distilled != content:
                            row["content"] = distilled


def catalog_for_keys(
    dim_keys: list[str],
    category: str | None = DEFAULT_CATEGORY,
    skip_item_ids: set[str] | None = None,
) -> str:
    """把指定一级维度的固定字段编成提示词目录，供模型逐项填写。"""
    wanted = set(dim_keys)
    skip = skip_item_ids or set()
    lines: list[str] = []
    for dim in load_schema(category):
        if dim["key"] not in wanted:
            continue
        lines.append(f"## 一级维度 {dim['key']}（{dim['label']}）")
        for item in dim["items"]:
            if item["id"] in skip:
                continue
            lines.append(f"### 二级项目 {item['id']}（{item['label']}）")
            for sec in item["sections"]:
                fields = "、".join(sec["rows"])
                lines.append(f"- 板块 {sec['id']}「{sec['title']}」字段：{fields}")
    return "\n".join(lines) + (
        "\n\n每个字段的值必须是对象 {\"摘要\": \"提炼后的事实\", \"原文\": \"对应条款原文\"}。"
        "摘要给人快速看懂要求，禁止粘贴招标正文；原文留给锁定评标尺子，须含条款号。"
    )


def _is_weak_fill(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if t.startswith("招标文件未明确列出") or t in ("未明确", "无"):
        return True
    if t.startswith("详见") and len(t) < 48:
        return True
    return False


ADDENDUM_PREFIX = "【答疑补遗为准】"


def stamp_addendum(old: str, new: str) -> str:
    """答疑非空值覆盖正文；若改写了已有字段，加上来源标记。"""
    new_s = (new or "").strip()
    if not new_s:
        return (old or "").strip()
    if new_s.startswith(ADDENDUM_PREFIX):
        new_s = new_s[len(ADDENDUM_PREFIX):].strip()
    old_s = (old or "").strip()
    if old_s.startswith(ADDENDUM_PREFIX):
        old_plain = old_s[len(ADDENDUM_PREFIX):].strip()
    else:
        old_plain = old_s
    if old_plain and old_plain != new_s and new_s not in old_plain:
        return f"{ADDENDUM_PREFIX}{new_s}"
    return new_s


def prefer_fill(old: str, new: str) -> str:
    """分段抽取合并：空/占位不覆盖已有原文；两段都有实质内容则拼接，避免漏页。"""
    old_s = (old or "").strip()
    new_s = (new or "").strip()
    if _is_weak_fill(new_s):
        return old_s
    if _is_weak_fill(old_s):
        return new_s
    if new_s in old_s:
        return old_s
    if old_s in new_s:
        return new_s
    return old_s.rstrip() + "\n\n" + new_s


def apply_fills(tree: list[dict], fills: dict, *, merge: bool = False, replace: bool = False) -> None:
    """只写入骨架里已有的 item/section/row；未知键丢弃。

    字段值可以是字符串，或 {摘要, 原文}。content 存摘要，original 存原文。
    merge=True 时按分段结果合并，后一段的空串/「未明确列出」不会冲掉前一段已抽出的内容。
    replace=True 时非空新值覆盖旧值（答疑补遗压过招标正文），空值不改。
    """
    if not isinstance(fills, dict):
        return
    for dim in tree:
        for item in dim["items"]:
            item_fill = fills.get(item["id"])
            if not isinstance(item_fill, dict):
                continue
            for sec in item["sections"]:
                sec_fill = item_fill.get(sec["id"])
                if not isinstance(sec_fill, dict):
                    continue
                for row in sec["rows"]:
                    if row["label"] not in sec_fill:
                        continue
                    summary, original = coerce_fill(sec_fill.get(row["label"]))
                    if "original" not in row:
                        row["original"] = ""
                    if replace:
                        if not _is_weak_fill(summary):
                            row["content"] = stamp_addendum(row.get("content") or "", summary)
                        if not _is_weak_fill(original):
                            row["original"] = stamp_addendum(row.get("original") or "", original)
                    elif merge:
                        row["content"] = prefer_fill(row.get("content") or "", summary)
                        row["original"] = prefer_fill(row.get("original") or "", original)
                    else:
                        row["content"] = summary
                        row["original"] = original


def mark_completed(tree: list[dict]) -> None:
    for dim in tree:
        dim["completed"] = any(
            (row.get("content") or row.get("original") or "").strip()
            for item in dim["items"]
            for sec in item["sections"]
            for row in sec["rows"]
        )


def merge_tree(stored: list | None, category: str | None = DEFAULT_CATEGORY) -> list[dict]:
    """API 输出永远返回完整骨架；用已存 content/original 覆盖对应字段。"""
    tree = empty_tree(category)
    if not stored:
        return tree
    fills: dict = {}
    for dim in stored:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            sec_map: dict = {}
            for sec in item.get("sections") or []:
                if not isinstance(sec, dict) or not sec.get("id"):
                    continue
                row_map = {}
                for row in sec.get("rows") or []:
                    if isinstance(row, dict) and row.get("label"):
                        row_map[row["label"]] = {
                            "摘要": row.get("content") or "",
                            "原文": row.get("original") or "",
                        }
                sec_map[sec["id"]] = row_map
            fills[item["id"]] = sec_map
    apply_fills(tree, fills)
    _migrate_legacy_tables(tree, fills)
    ensure_originals(tree)
    distill_display(tree)
    mark_completed(tree)
    return tree


def collect_text(tree: list[dict]) -> str:
    parts = []
    for dim in tree:
        for item in dim["items"]:
            for sec in item["sections"]:
                for row in sec["rows"]:
                    body = row_body(row)
                    if body:
                        parts.append(body)
    return "\n".join(parts)


def filled_row_counts(tree: list[dict]) -> tuple[int, int]:
    filled = 0
    total = 0
    for dim in tree:
        for item in dim["items"]:
            for sec in item["sections"]:
                for row in sec["rows"]:
                    total += 1
                    if (row.get("content") or row.get("original") or "").strip():
                        filled += 1
    return filled, total


def _row_contents(item: dict) -> list[tuple[str, str, str]]:
    """(section_title, row_label, content) 非空行。"""
    out = []
    for sec in item.get("sections") or []:
        title = sec.get("title") or ""
        for row in sec.get("rows") or []:
            content = row_body(row)
            if content:
                out.append((title, row.get("label") or "", content))
    return out


_RISK_LABELS = ("风险点", "详细描述", "风险等级", "来源/依据")


def _zip_aligned_rows(item: dict, labels: tuple[str, ...]) -> list[list[str]]:
    """把按行对齐的多列表格还原成逐条记录。"""
    by: dict[str, list[str]] = {label: [] for label in labels}
    for sec in item.get("sections") or []:
        for row in sec.get("rows") or []:
            label = row.get("label") or ""
            if label in by:
                by[label] = [ln.strip() for ln in (row_body(row) or "").split("\n")]
    n = max((len(v) for v in by.values()), default=0)
    out: list[list[str]] = []
    for i in range(n):
        rec = [(by[label][i] if i < len(by[label]) else "") for label in labels]
        if any(rec):
            out.append(rec)
    return out


def _zip_risk_rows(item: dict) -> list[dict]:
    """把废标四列按行对齐成报告同款风险点。"""
    title = ""
    for sec in item.get("sections") or []:
        title = sec.get("title") or title
    out: list[dict] = []
    for rec in _zip_aligned_rows(item, _RISK_LABELS):
        point, desc, level, source = (rec + ["", "", "", ""])[:4]
        if not (point or desc):
            continue
        out.append({"title": title, "point": point, "desc": desc, "level": level, "source": source})
    return out


_COMPOSE_LABELS = ("序号", "文件名称", "格式要求", "是否必须", "备注")
_QUALDOC_LABELS = ("资料类别", "具体资料", "是否必须", "备注")
_OLD_RISK_LABEL = "废标风险点（风险点/描述/等级/条款号）"
_OLD_COMPOSE_LABEL = "投标文件组成清单（文件名/格式/是否必须/备注）"
_OLD_QUALDOC_LABEL = "资格审查资料详细清单（资料类别/具体资料/是否必须/备注）"


def _split_legacy_lines(blob: str) -> list[str]:
    text = (blob or "").replace("【答疑补遗为准】", "").strip()
    if not text:
        return []
    lines = [ln.strip("；;· ").strip() for ln in re.split(r"\n+", text) if ln.strip()]
    if len(lines) == 1 and ("；" in lines[0] or ";" in lines[0]):
        lines = [x.strip() for x in re.split(r"[；;]", lines[0]) if x.strip()]
    return lines


def _parse_legacy_risk(blob: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in _split_legacy_lines(blob):
        point, rest = "", line
        m = re.match(r"^([^：:]{2,40})[：:](.+)$", line)
        if m:
            point, rest = m.group(1).strip(), m.group(2).strip()
        level, source = "", ""
        tail = re.search(r"[（(]([^）)]+)[）)]\s*$", rest)
        if tail:
            rest = rest[: tail.start()].strip()
            for part in re.split(r"[，,、]", tail.group(1)):
                part = part.strip()
                if not part:
                    continue
                if part[:1] in "高中低" and not level:
                    level = part[:1]
                else:
                    source = f"{source}、{part}" if source else part
        if not point:
            point = rest[:18] if rest else line[:18]
        if point or rest:
            rows.append([point, rest or point, level, source])
    return rows


def _parse_legacy_compose(blob: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for i, line in enumerate(_split_legacy_lines(blob), start=1):
        line = re.sub(r"^[\d一二三四五六七八九十]+[.、．)）]\s*", "", line)
        parts = [p.strip() for p in re.split(r"\s*/\s*", line) if p.strip()]
        if len(parts) >= 2:
            name, fmt = parts[0], parts[1]
            must = parts[2] if len(parts) > 2 else ""
            remark = " / ".join(parts[3:]) if len(parts) > 3 else ""
        else:
            m = re.match(r"^(.+?)[：:](.+)$", line)
            name, fmt, must, remark = (m.group(1).strip(), m.group(2).strip(), "", "") if m else (line, "", "", "")
        if "必须" in must or must in {"是", "须"}:
            must = "是"
        elif must in {"否", "非必须"}:
            must = "否"
        elif "按需" in must or "如有" in must:
            must = "按需"
        if name:
            rows.append([str(i), name, fmt, must, remark])
    return rows


def _parse_legacy_qualdoc(blob: str) -> list[list[str]]:
    rows: list[list[str]] = []
    last_kind = ""
    for line in _split_legacy_lines(blob):
        parts = [p.strip() for p in re.split(r"\s*/\s*", line) if p.strip()]
        if len(parts) >= 2:
            kind, name = parts[0], parts[1]
            must = parts[2] if len(parts) > 2 else ""
            remark = " / ".join(parts[3:]) if len(parts) > 3 else ""
        else:
            m = re.match(r"^(.+?)[：:](.+)$", line)
            kind, name, must, remark = (m.group(1).strip(), m.group(2).strip(), "", "") if m else ("", line, "", "")
        if kind:
            last_kind = kind
        else:
            kind = last_kind
        if name:
            rows.append([kind, name, must, remark])
    return rows


def _table_line_counts(sec: dict, cols: tuple[str, ...]) -> list[int]:
    counts: list[int] = []
    for row in sec.get("rows") or []:
        if row.get("label") not in cols:
            continue
        lines = [ln.strip() for ln in (row.get("content") or "").split("\n") if ln.strip()]
        if lines:
            counts.append(len(lines))
    return counts


def _already_aligned_table(sec: dict, cols: tuple[str, ...]) -> bool:
    counts = _table_line_counts(sec, cols)
    if len(counts) < 2:
        return False
    peak = max(counts)
    return peak >= 2 and sum(1 for n in counts if n >= peak - 1) >= 2


def _fill_text(value) -> str:
    summary, original = coerce_fill(value)
    return summary or original


def _pick_legacy_blob(sec: dict, sec_fill: dict, cols: tuple[str, ...], old_label: str) -> str:
    blob = _fill_text(sec_fill.get(old_label)) if isinstance(sec_fill, dict) else ""
    if blob.strip():
        return blob
    if isinstance(sec_fill, dict):
        extras = []
        for key, value in sec_fill.items():
            if key in cols or key == old_label:
                continue
            text = _fill_text(value)
            if text.strip():
                extras.append(text)
        if extras:
            return "\n".join(extras)
    nonempty = [
        (row.get("content") or "").strip()
        for row in sec.get("rows") or []
        if row.get("label") in cols and (row.get("content") or "").strip()
    ]
    if len(nonempty) == 1:
        return nonempty[0]
    return ""


def _write_aligned_cols(sec: dict, cols: tuple[str, ...], parsed: list[list[str]]) -> None:
    by = {col: "\n".join(row[i] if i < len(row) else "" for row in parsed) for i, col in enumerate(cols)}
    for row in sec.get("rows") or []:
        if row.get("label") in by:
            row["content"] = by[row["label"]]
            if not (row.get("original") or "").strip():
                row["original"] = by[row["label"]]


def _migrate_legacy_tables(tree: list[dict], fills: dict) -> None:
    specs = (
        (None, _OLD_RISK_LABEL, _RISK_LABELS, _parse_legacy_risk),
        ("req-compose", _OLD_COMPOSE_LABEL, _COMPOSE_LABELS, _parse_legacy_compose),
        ("req-qualdocs", _OLD_QUALDOC_LABEL, _QUALDOC_LABELS, _parse_legacy_qualdoc),
    )
    for dim in tree:
        for item in dim.get("items") or []:
            item_fill = fills.get(item.get("id")) or {}
            for old_id, old_label, cols, parser in specs:
                if old_id and item.get("id") != old_id:
                    continue
                if old_id is None and not str(item.get("id") or "").startswith("reject-"):
                    continue
                for sec in item.get("sections") or []:
                    if _already_aligned_table(sec, cols):
                        continue
                    sec_fill = item_fill.get(sec.get("id")) or {}
                    blob = _pick_legacy_blob(sec, sec_fill if isinstance(sec_fill, dict) else {}, cols, old_label)
                    parsed = parser(blob)
                    if not parsed:
                        continue
                    _write_aligned_cols(sec, cols, parsed)


# 派生四类尺子时的单类上限：早期为 20，滨湖/濉溪等工程标一个项目的技术因素+
# 第七章考题+商务客观件轻松超过 20 条，截断会漏掉「无市政道路」这类括号命题，
# 因此统一放宽到 60，两类 category 都受益。
_MAX_DERIVED_ITEMS = 200


_MISC_OTHER_ID = "misc-other"
_MISC_SCORE_LABELS = {"评分因素与标准", "技术指标与加分项"}
_MISC_MUST_LABEL = "否决/废标条款"
_MISC_QUAL_LABEL = "资格与门槛补充"
_MISC_FORMAT_LABEL = "格式与递交要求"
_CONTRACT_TECH_ID = "contract-tech"
_CONTRACT_SKIP_LABELS = {"工程专业（市政/房建/公路/水利等）"}
_CONTRACT_MUST_LABELS = {
    "进度计划确认与修订时限",
    "监理/发包人确认时限",
    "材料、工艺与验收标准",
    "质量检测与实测实量要求",
    "安全文明施工量化要求",
}


def derive_engine_fields(tree: list[dict], category: str | None = DEFAULT_CATEGORY) -> dict:
    """从固定树派生预审/撰写仍使用的四类尺子，不增加解析页指标。"""
    import re
    import uuid

    key = _normalize_category(category)
    score_item_ids = SCORE_ITEM_IDS_BY_CATEGORY[key]
    must_item_types = MUST_ITEM_TYPES_BY_CATEGORY[key]
    qual_item_ids = QUAL_ITEM_IDS_BY_CATEGORY[key]
    format_item_ids = FORMAT_ITEM_IDS_BY_CATEGORY[key]
    # 软件服务类里"review-"前缀代表技术/服务/售后主观评审项；
    # 工程类：技术标评分、商务机构评分、合同技术指标为主观项，报价公式为客观项。
    subject_prefixes = (
        ("review-", "eval-tech") if key == "软件服务类" else ("eval-tech", "eval-business", "contract-tech")
    )

    score_rules = []
    must_respond = []
    qualification = []
    format_requirements = []

    for dim in tree:
        for item in dim["items"]:
            item_id = item["id"]
            rows = _row_contents(item)
            if item_id == _MISC_OTHER_ID:
                for title, label, content in rows:
                    if _is_weak_fill(content):
                        continue
                    if label in _MISC_SCORE_LABELS:
                        weight = 0.0
                        found = re.search(r"(\d+(?:\.\d+)?)\s*分", content)
                        if not found:
                            found = re.search(r"(\d+(?:\.\d+)?)\s*%", content)
                        if found:
                            weight = float(found.group(1))
                        score_rules.append(
                            {
                                "id": f"sr-{uuid.uuid4().hex[:8]}",
                                "dimension": item["label"],
                                "weight": weight,
                                "detail": content if label == "评分因素与标准" else f"{label}：{content}",
                                "subject": label == "技术指标与加分项",
                                "sectionPath": title or "其他材料",
                                "responseStatus": "未覆盖",
                                "isEssential": False,
                                "sourceItemId": item_id,
                            }
                        )
                    elif label == _MISC_MUST_LABEL:
                        must_respond.append(
                            {
                                "id": f"mr-{uuid.uuid4().hex[:8]}",
                                "clause": content,
                                "original": title or "其他材料",
                                "type": "废标条款" if any(k in content for k in ("废标", "否决", "无效标")) else "实质性条款",
                                "status": "待响应",
                            }
                        )
                    elif label == _MISC_QUAL_LABEL:
                        qualification.append(
                            {
                                "title": label,
                                "desc": content,
                                "source": title or "其他材料",
                                "level": "星号" if any(k in content for k in ("必须", "须具备", "不通过", "无效标")) else "建议",
                            }
                        )
                    elif label == _MISC_FORMAT_LABEL:
                        format_requirements.append(
                            {
                                "title": label,
                                "desc": content,
                                "source": title or "其他材料",
                                "level": "废标" if any(k in content for k in ("无效标", "废标", "否决")) else "强制",
                                "sourceItemId": item_id,
                            }
                        )
                continue
            if item_id == _CONTRACT_TECH_ID:
                for title, label, content in rows:
                    if _is_weak_fill(content) or label in _CONTRACT_SKIP_LABELS:
                        continue
                    score_rules.append(
                        {
                            "id": f"sr-{uuid.uuid4().hex[:8]}",
                            "dimension": item["label"],
                            "weight": 0.0,
                            "detail": f"{label}：{content}",
                            "subject": True,
                            "sectionPath": title or "专用合同条款",
                            "responseStatus": "未覆盖",
                            "isEssential": label in _CONTRACT_MUST_LABELS,
                            "sourceItemId": item_id,
                        }
                    )
                    if label in _CONTRACT_MUST_LABELS or any(k in content for k in ("日内", "小时内", "必须于", "须在")):
                        must_respond.append(
                            {
                                "id": f"mr-{uuid.uuid4().hex[:8]}",
                                "clause": f"{label}：{content}",
                                "original": title or "专用合同条款",
                                "type": "实质性条款",
                                "status": "待响应",
                            }
                        )
                continue
            if item_id in score_item_ids:
                for title, label, content in rows:
                    if _is_weak_fill(content):
                        continue
                    weight = 0.0
                    found = re.search(r"(\d+(?:\.\d+)?)\s*分", content)
                    if not found:
                        found = re.search(r"(\d+(?:\.\d+)?)\s*%", content)
                    if found:
                        weight = float(found.group(1))
                    score_rules.append(
                        {
                            "id": f"sr-{uuid.uuid4().hex[:8]}",
                            "dimension": item["label"],
                            "weight": weight,
                            "detail": content if label in ("评分细则", "评分因素与标准") else f"{label}：{content}" if label else content,
                            "subject": item_id.startswith(subject_prefixes),
                            "sectionPath": title or "未标注",
                            "responseStatus": "未覆盖",
                            "isEssential": False,
                            "sourceItemId": item_id,
                        }
                    )
            if item_id in must_item_types:
                risk_rows = _zip_risk_rows(item)
                if risk_rows:
                    for risk in risk_rows:
                        clause = f"{risk['point']}：{risk['desc']}" if risk["desc"] else risk["point"]
                        if risk["level"]:
                            clause = f"{clause}（{risk['level']}）"
                        must_respond.append(
                            {
                                "id": f"mr-{uuid.uuid4().hex[:8]}",
                                "clause": clause,
                                "original": risk["source"] or risk["title"] or "未标注",
                                "type": must_item_types[item_id],
                                "status": "待响应",
                            }
                        )
                else:
                    for title, _label, content in rows:
                        must_respond.append(
                            {
                                "id": f"mr-{uuid.uuid4().hex[:8]}",
                                "clause": content,
                                "original": title or "未标注",
                                "type": must_item_types[item_id],
                                "status": "待响应",
                            }
                        )
            if item_id in qual_item_ids:
                for title, label, content in rows:
                    level = "星号" if any(k in content for k in ("必须", "须具备", "不通过", "无效标")) else "建议"
                    qualification.append(
                        {
                            "title": label or item["label"],
                            "desc": content,
                            "source": title or "未标注",
                            "level": level,
                        }
                    )
            if item_id in format_item_ids:
                if item_id == "req-compose":
                    zipped = _zip_aligned_rows(item, _COMPOSE_LABELS)
                    if zipped:
                        for rec in zipped:
                            seq, name, fmt, must, remark = (rec + ["", "", "", "", ""])[:5]
                            parts = [p for p in (fmt, f"是否必须：{must}" if must else "", remark) if p]
                            format_requirements.append(
                                {
                                    "title": name or f"组成文件{seq}",
                                    "desc": "；".join(parts) or name,
                                    "source": seq or item.get("label") or "投标文件组成",
                                    "level": "废标" if must == "是" else "强制",
                                    "sourceItemId": item_id,
                                }
                            )
                        continue
                if item_id == "req-qualdocs":
                    zipped = _zip_aligned_rows(item, _QUALDOC_LABELS)
                    if zipped:
                        for rec in zipped:
                            kind, name, must, remark = (rec + ["", "", "", ""])[:4]
                            parts = [p for p in (kind, f"是否必须：{must}" if must else "", remark) if p]
                            format_requirements.append(
                                {
                                    "title": name or kind or "资格审查资料",
                                    "desc": "；".join(parts) or name,
                                    "source": kind or item.get("label") or "资格审查资料",
                                    "level": "废标" if must == "是" else "强制",
                                    "sourceItemId": item_id,
                                }
                            )
                        continue
                for title, label, content in rows:
                    level = "废标" if any(k in content for k in ("无效标", "废标", "否决")) else "强制"
                    format_requirements.append(
                        {
                            "title": item["label"] if label in ("提交要求", "编制要求", "盖章要求", "格式要求", "递交要求", "加密上传") else label or item["label"],
                            "desc": content,
                            "source": title or "未标注",
                            "level": level,
                            "sourceItemId": item_id,
                        }
                    )

    omitted = {
        "scoreRules": max(0, len(score_rules) - _MAX_DERIVED_ITEMS),
        "mustRespond": max(0, len(must_respond) - _MAX_DERIVED_ITEMS),
        "qualification": max(0, len(qualification) - _MAX_DERIVED_ITEMS),
        "formatRequirements": max(0, len(format_requirements) - _MAX_DERIVED_ITEMS),
    }
    return {
        "scoreRules": score_rules[:_MAX_DERIVED_ITEMS],
        "mustRespond": must_respond[:_MAX_DERIVED_ITEMS],
        "qualification": qualification[:_MAX_DERIVED_ITEMS],
        "formatRequirements": format_requirements[:_MAX_DERIVED_ITEMS],
        "omittedCount": omitted,
    }


def derive_veto_params(tree: list[dict], full_text: str) -> dict:
    import re

    blob = collect_text(tree) + "\n" + (full_text or "")[:20000]
    days = None
    m = re.search(r"有效期[^。；\n]{0,20}?(\d+)\s*日历天", blob)
    if m:
        days = int(m.group(1))
    budget = None
    m = re.search(r"预算[^。；\n]{0,24}?(\d+(?:\.\d+)?)\s*万", blob)
    if m:
        budget = float(m.group(1))
    ratio = None
    m = re.search(r"资产负债率[^。；\n]{0,12}?(?:不高于|不超过|低于|≦|≤)?\s*(\d+(?:\.\d+)?)\s*%", blob)
    if m:
        ratio = float(m.group(1))
    keywords = []
    for kw in ("营业执照", "安全生产许可证", "软件企业", "高新技术企业", "ISO 9001", "ISO 27001", "建造师"):
        if kw in blob and kw not in keywords:
            keywords.append(kw)

    provisional_amount_wan = None
    m = re.search(r"暂列金额[^。；\n]{0,10}?(\d+(?:\.\d+)?)\s*万", blob)
    if m:
        provisional_amount_wan = float(m.group(1))

    # 安全生产费用/文明施工费占合同造价比例：常见"不低于合同造价的1.5%"这类硬条款，
    # 属于可完全数值化核验的比例类规则（工程标常见，软件标遇不到时保持 None）。
    safety_fee_ratio_pct = None
    m = re.search(r"安全生产费[用]?[^。；\n]{0,20}?不低于合同(?:造价|价格)的?\s*(\d+(?:\.\d+)?)\s*%", blob)
    if m:
        safety_fee_ratio_pct = float(m.group(1))

    # 人员/设备数量要求：best-effort 正则派生，仅用于在解析出数字时做量化比对增强，
    # 解析不出时各引擎保持原有「资质库是否有条目」检查，不回退功能。
    # 工程类项目常见专职岗位远多于软件标，一并扫描不影响软件标（扫不到即忽略）。
    personnel_required: dict[str, int] = {}
    for role in (
        "项目经理",
        "安全员",
        "八大员",
        "施工员",
        "质量员",
        "技术负责人",
        "设计负责人",
        "施工负责人",
        "施工技术负责人",
        "造价人员",
        "质量负责人",
        "质检员",
        "终检工程师",
        "劳资专管员",
    ):
        rm = re.search(rf"{role}[^。；\n]{{0,8}}?(\d+)\s*(?:名|人)", blob)
        if rm:
            personnel_required[role] = int(rm.group(1))

    equipment_required: dict[str, int] = {}
    for eq in ("塔吊", "盾构机", "挖掘机", "泵车", "压路机", "装载机", "起重机"):
        em = re.search(rf"{eq}[^。；\n]{{0,10}}?(?:不少于|至少|配备)?\s*(\d+)\s*(?:台|套)", blob)
        if em:
            equipment_required[eq] = int(em.group(1))

    return {
        "validity_days_required": days,
        "budget_cap_wan": budget,
        "asset_liability_ratio_max": ratio,
        "qualification_keywords": keywords[:20],
        "anonymity_required": "暗标" in blob,
        "provisional_amount_wan": provisional_amount_wan,
        "safety_fee_ratio_pct": safety_fee_ratio_pct,
        "personnel_required": personnel_required,
        "equipment_required": equipment_required,
    }
