"""招标解析固定指标骨架：与前端 src/mocks/parse.ts（软件服务类）/ parseEngineering.ts（工程类）
的一级维度 / 二级分析项目完全对齐。

按项目 category（软件服务类 | 工程类）选用不同的固定骨架文件；同一 category 内部
禁止增删 key、id、label、section id/title、row label。抽取结果填充 rows.content（页面摘要）
和 rows.original（招标原文，供 AI 预审）；找不到时保持空字符串，指标项仍然出现在结果里。
"""

from __future__ import annotations

import json
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
        "\n\n每个字段的值必须是对象 {\"摘要\": \"...\", \"原文\": \"...\"}，禁止只返回字符串。"
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


# 派生四类尺子时的单类上限：早期为 20，滨湖/濉溪等工程标一个项目的技术因素+
# 第七章考题+商务客观件轻松超过 20 条，截断会漏掉「无市政道路」这类括号命题，
# 因此统一放宽到 60，两类 category 都受益。
_MAX_DERIVED_ITEMS = 60


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
    # 工程类：施工组织设计、商务机构评分、合同技术指标为主观项，报价公式为客观项。
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

    return {
        "scoreRules": score_rules[:_MAX_DERIVED_ITEMS],
        "mustRespond": must_respond[:_MAX_DERIVED_ITEMS],
        "qualification": qualification[:_MAX_DERIVED_ITEMS],
        "formatRequirements": format_requirements[:_MAX_DERIVED_ITEMS],
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
