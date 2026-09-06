"""按「这一份」招标文件自己的评分规则做模拟评标。

每份招标书的商务/技术/报价因素、分值、档次公式都不同，本引擎不使用青天
8 模块或五维作为评分题干，只消费本项目招标解析树 / scoreRules 里的原文。
换项目或重新解析后，条目集合会整体替换。
"""

from __future__ import annotations

import json
import logging
import re

from . import parse_schema, rules_data
from .llm import LlmError, chat_complete, get_default_model_id

logger = logging.getLogger(__name__)

# 只从「评分类」解析槽位取原文；槽位 id 是骨架，槽位里的文字每份标书都不同。
_TREE_ITEM_IDS: set[str] = set()
for _ids in parse_schema.SCORE_ITEM_IDS_BY_CATEGORY.values():
    _TREE_ITEM_IDS |= set(_ids)
_TREE_ITEM_IDS.discard("env-calc")  # 评委畸高畸低，不是投标人自查项

_SKIP_LABELS = (
    "分档/赋分规则",
    "分档/赋分规则（A/B/C 或分值区间）",
    "AI类人评审说明",
    "评委打分纵向/横向偏差率剔除算法原文",
    "综合评价等级组合规则（好/较好/一般）",
    "异常低价识别公式与参数",
    "异常低价说明不得作为依据的排除清单",
)
_SKIP_HINTS = ("畸高畸低", "类人评审", "不替代评标委员会", "纵向偏差率", "横向偏差率")
_PARENT_NAME_HINTS = ("评分标准", "分值构成", "分值组成", "分值分配", "评分办法")

# 括号分值：对设计文件的理解（7分）
_FACTOR_RE = re.compile(r"([^、；。：:\n]{2,40}?)[（(](\d+(?:\.\d+)?)分[）)]")
# 行内分值：1. 设计管理方案 7分 / 设计管理方案：7分 / 权重 10%
_LINE_SCORE_RE = re.compile(
    r"^(?:\d+[\.、．]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.．])?\s*"
    r"(.+?)\s*[：:]\s*(?:满分|分值|权重)?\s*(\d+(?:\.\d+)?)\s*(?:分|%)\s*$"
)
_LINE_SCORE_RE2 = re.compile(
    r"^(?:\d+[\.、．]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.．])?\s*"
    r"(.{2,40}?)\s+(\d+(?:\.\d+)?)\s*分\s*$"
)

_GROUP_ORDER = ("技术评审标准", "商务标评分评审标准", "技术评审", "商务评审", "技术", "商务", "报价评审", "报价", "其他")

# 高分策略只是改写建议的工具箱，不充当评分题干；是否挂上取决于本条招标原文主题。
_STRATEGY_BY_THEME = {
    "checklist_map": ("评分", "方案", "响应", "理解", "设计", "实施", "组织", "建议", "功能", "服务"),
    "quantify": ("进度", "工期", "质量", "安全", "环保", "资源", "量化", "指标", "优化", "报价"),
    "originality": ("重难点", "优化", "理解", "建议书", "四新", "针对性"),
    "local_first": ("业绩", "资信", "信用", "人员", "售后", "获奖"),
    "data_loop": ("资源", "劳动力", "进度", "机械", "人员"),
    "code_cite": ("规范", "质量", "安全", "危大", "方案", "验收", "标准"),
    "structured_layout": ("组织", "施组", "目录", "总纲", "格式"),
}


def _group_of(dimension: str, label: str = "") -> str:
    """分组名优先用本项目解析二级标题（技术评审标准/商务评审/技术…），不套固定 8 模块名。"""
    blob = f"{dimension}{label}"
    if any(k in blob for k in ("报价", "价格", "限价")):
        return dimension if dimension and any(k in dimension for k in ("报价", "价格")) else "报价"
    if dimension:
        return dimension
    if any(k in blob for k in ("商务", "资信", "业绩", "信用")):
        return "商务标"
    if any(k in blob for k in ("技术", "施工", "设计", "方案")):
        return "技术标"
    return "其他"


def _is_formula(group: str, text: str) -> bool:
    if "报价" in (group or "") or "价格" in (group or ""):
        return True
    return any(k in (text or "") for k in ("计算公式", "评标基准价", "偏差率", "每减少", "最高限价"))


def _should_skip(label: str, content: str) -> bool:
    if label in _SKIP_LABELS:
        return True
    blob = f"{label}{content}"
    return any(h in blob for h in _SKIP_HINTS)


def _split_factors(content: str) -> list[tuple[str, float]]:
    """按本条原文自己的写法拆叶子评分点：括号分、冒号分、换行分。拆不出就整段保留。"""
    text = (content or "").strip()
    if not text:
        return []

    hits = [(name.strip(" 、；;"), float(score)) for name, score in _FACTOR_RE.findall(text)]
    leaves = [(n, s) for n, s in hits if n and not any(h in n for h in _PARENT_NAME_HINTS)]
    if len(leaves) >= 2:
        return leaves

    line_hits: list[tuple[str, float]] = []
    for raw_line in re.split(r"[\n；;]|(?=\d+[\.、．])", text):
        line = raw_line.strip()
        if not line or any(h in line for h in _PARENT_NAME_HINTS):
            continue
        m = _LINE_SCORE_RE.match(line) or _LINE_SCORE_RE2.match(line)
        if not m:
            continue
        name = re.sub(r"^[（(]\d+[）)]", "", m.group(1)).strip(" 、；;:：")
        if name and not any(h in name for h in _PARENT_NAME_HINTS):
            line_hits.append((name, float(m.group(2))))
    if len(line_hits) >= 2:
        return line_hits
    if len(hits) >= 2:
        return hits

    percent_hits: list[tuple[str, float]] = []
    pieces = re.split(r"(\d+(?:\.\d+)?)\s*%", text)
    idx = 1
    while idx + 1 < len(pieces):
        try:
            score = float(pieces[idx])
        except ValueError:
            idx += 2
            continue
        tail = pieces[idx + 1]
        name_m = re.search(r"[\u4e00-\u9fffA-Za-z0-9（(][\u4e00-\u9fffA-Za-z0-9）)、]{1,30}", tail)
        name = (name_m.group(0) if name_m else "").strip(" 、；;")
        if name and not any(h in name for h in _PARENT_NAME_HINTS) and "偏差" not in name:
            percent_hits.append((name, score))
        idx += 2
    if len(percent_hits) >= 2:
        return percent_hits
    return []


def _rule_for_factor(content: str, name: str) -> str:
    """尽量截取包含该评分点的那一句，作为「本条招标规则原文」。"""
    for sent in re.split(r"[。\n]", content or ""):
        if name and name in sent:
            return sent.strip()
    return (content or "").strip()


def _blobs_from_tree(tree: list | None) -> list[dict]:
    out: list[dict] = []
    if not tree:
        return out
    for dim in tree:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict) or item.get("id") not in _TREE_ITEM_IDS:
                continue
            dim_label = item.get("label") or dim.get("label") or ""
            for sec in item.get("sections") or []:
                title = (sec.get("title") or "") if isinstance(sec, dict) else ""
                for row in (sec.get("rows") or []) if isinstance(sec, dict) else []:
                    if not isinstance(row, dict):
                        continue
                    label = row.get("label") or ""
                    content = (row.get("content") or "").strip()
                    if not content:
                        continue
                    if content.startswith("分值构成"):
                        continue
                    if content.startswith("招标文件未明确列出") or content.strip() in ("未明确", "无"):
                        continue
                    if label in ("分档/赋分规则", "分档/赋分规则（A/B/C 或分值区间）"):
                        continue
                    if _should_skip(label, content):
                        continue
                    out.append(
                        {
                            "dimension": dim_label,
                            "section": title,
                            "label": label,
                            "content": content,
                        }
                    )
    return out


def _blobs_from_score_rules(score_rules: list | None) -> list[dict]:
    out: list[dict] = []
    for item in score_rules or []:
        if not isinstance(item, dict):
            continue
        content = (item.get("detail") or "").strip()
        label = ""
        if "：" in content[:20]:
            label, _, rest = content.partition("：")
            if rest:
                content = rest
        if not content or _should_skip(label or item.get("sectionPath") or "", content):
            continue
        if content.startswith("分值构成") or content.startswith("招标文件未明确列出"):
            continue
        out.append(
            {
                "dimension": item.get("dimension") or "评分点",
                "section": item.get("sectionPath") or "",
                "label": label,
                "content": content,
                "weight": item.get("weight") or 0,
            }
        )
    return out


def expand_score_items(score_rules: list | None, tree: list | None = None) -> list[dict]:
    """展开「这一份」招标书的评分点。优先解析树原文，没有再退回派生 scoreRules。"""
    blobs = _blobs_from_tree(tree) or _blobs_from_score_rules(score_rules)
    items: list[dict] = []
    seq = 0
    for blob in blobs:
        group = _group_of(blob["dimension"], f"{blob.get('label') or ''}{blob['content'][:20]}")
        factors = _split_factors(blob["content"])
        if factors:
            for name, score in factors:
                seq += 1
                items.append(
                    {
                        "id": f"tr-{seq}",
                        "group": group,
                        "name": name,
                        "rule": _rule_for_factor(blob["content"], name),
                        "maxScore": score,
                        "formula": _is_formula(group, name + blob["content"]),
                    }
                )
            continue
        seq += 1
        weight = float(blob.get("weight") or 0)
        if weight <= 0:
            found = re.search(r"(\d+(?:\.\d+)?)\s*分", blob["content"])
            if not found:
                found = re.search(r"(\d+(?:\.\d+)?)\s*%", blob["content"])
            weight = float(found.group(1)) if found else 0
        if weight <= 0:
            continue
        name = blob.get("label") or blob.get("dimension") or "评分点"
        items.append(
            {
                "id": f"tr-{seq}",
                "group": group,
                "name": name,
                "rule": blob["content"],
                "maxScore": weight,
                "formula": _is_formula(group, blob["content"]),
            }
        )
    return items


def _collect_grade_book(tree: list | None) -> str:
    """本项目评标办法里的分档/赋分公式，供评委按档给分。"""
    parts: list[str] = []
    for dim in tree or []:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict) or item.get("id") not in _TREE_ITEM_IDS:
                continue
            for sec in item.get("sections") or []:
                if not isinstance(sec, dict):
                    continue
                for row in sec.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    label = row.get("label") or ""
                    content = (row.get("content") or "").strip()
                    if content and ("分档" in label or "赋分" in label):
                        parts.append(content)
    return "\n".join(parts)


def _pick_strategies(name: str, rule: str, strategy_keys: set[str] | None) -> list[dict]:
    blob = f"{name}{rule}"
    picked: list[dict] = []
    for strat in rules_data.HIGH_SCORE_STRATEGIES:
        key = strat["key"]
        if strategy_keys is not None and key not in strategy_keys:
            continue
        hints = _STRATEGY_BY_THEME.get(key)
        if key == "checklist_map" or (hints and any(h in blob for h in hints)):
            picked.append(
                {
                    "key": key,
                    "category": strat.get("category") or key,
                    "point": strat.get("point") or "",
                    "clauses": list(strat.get("items") or []),
                }
            )
    return picked[:4]


_WINDOW = 8000
_BATCH = 6
_JUDGE_TIMEOUT = 180
_DIGEST = 36000


def _windows(name: str, rule: str, bid: str) -> str:
    """从全文检索与本评分点相关的段落，供评委阅读（先扫完全文再截取）。"""
    if not (bid or "").strip():
        return ""
    keys = [k for k in (name, *(re.findall(r"[\u4e00-\u9fff]{4,}", name or ""))) if k]
    paras = [p.strip() for p in re.split(r"\n+", bid) if p.strip()]
    hits: list[str] = []
    for i, para in enumerate(paras):
        if any(k in para for k in keys):
            chunk = "\n".join(paras[max(0, i - 1) : i + 3])
            if chunk not in hits:
                hits.append(chunk)
        if sum(len(h) for h in hits) >= _WINDOW:
            break
    if hits:
        return "\n\n----\n\n".join(hits)[:_WINDOW]
    token = (name or "")[:4]
    idx = bid.find(token) if len(token) >= 4 else -1
    if idx >= 0:
        return bid[max(0, idx - 500) : idx + _WINDOW - 500]
    return ""


def _digest(bid: str, headings: list[str] | None) -> str:
    toc = [h.strip() for h in (headings or []) if h and 2 <= len(h.strip()) <= 80][:100]
    head = "目录/标题：\n" + "\n".join(toc) if toc else ""
    body = bid or ""
    if len(body) <= _DIGEST:
        return f"{head}\n\n投标文件全文：\n{body}".strip()
    mid = len(body) // 2
    return (
        f"{head}\n\n投标文件全文（已通读后分段送审，首部+中部+尾部）：\n"
        f"{body[: _DIGEST // 2]}\n\n……\n\n{body[mid : mid + _DIGEST // 4]}\n\n……\n\n{body[-_DIGEST // 4 :]}"
    )


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1]
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


def _judge_batch(
    model_id: str,
    batch: list[dict],
    digest: str,
    grade_book: str,
) -> dict[str, dict]:
    catalog = []
    for item in batch:
        catalog.append(
            {
                "id": item["id"],
                "name": item["name"],
                "maxScore": item["maxScore"],
                "rule": item["rule"],
                "evidenceFromBid": item.get("window") or "（全文未定位到明显对应段落，请结合下面全文节选判断；没有依据则 0 分）",
            }
        )
    system = (
        "你是本项目评标委员会成员，正在对一份投标文件做详细评审打分。\n"
        "必须且只能使用用户给出的「本项目招标评分规则」和档次公式，"
        "禁止套用其他招标项目、禁止使用青天/通用技术模块标准。\n"
        "你已经获得投标文件通读材料（目录+全文节选）以及各评分点检索到的对应段落。\n"
        "要求：\n"
        "1. 先根据投标原文判断该评分因素是否响应；没有对应内容必须 0 分，档次为未响应；\n"
        "2. 有档次公式（优/良/一般或分值区间）时，先定档，再在该档区间内给具体分数；\n"
        "3. 分数不得超出 maxScore，保留 1 位小数；\n"
        "4. reason 必须引用投标书原文依据，说明为何是这一档/这一分；\n"
        "5. suggestion 针对本条招标规则说明怎样改才能升到更高档；\n"
        "6. 不得编造投标书中不存在的内容。\n"
        "只返回 JSON：{\"scores\":[{\"id\":\"\",\"score\":0,\"grade\":\"优|良|一般|未响应\",\"reason\":\"\",\"suggestion\":\"\",\"evidence\":\"投标原文依据\"}]}"
    )
    user = (
        f"本项目招标档次/赋分公式（若有）：\n{grade_book or '（本项目未单独抽出分档公式，按各条规则原文掌握）'}\n\n"
        f"待评评分点：\n{json.dumps(catalog, ensure_ascii=False, indent=2)}\n\n"
        f"{digest}"
    )
    try:
        raw = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.15,
            timeout=_JUDGE_TIMEOUT,
            max_tokens=4096,
            extra={"response_format": {"type": "json_object"}},
        )
    except LlmError:
        raw = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.15,
            timeout=_JUDGE_TIMEOUT,
            max_tokens=4096,
        )
    data = _loads(raw)
    rows = data.get("scores") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = row
    return out


def _formula_entry(raw: dict, strategies: list[dict]) -> dict:
    return {
        "id": raw["id"],
        "group": raw["group"],
        "name": raw["name"],
        "rule": raw["rule"],
        "maxScore": raw["maxScore"],
        "score": 0.0,
        "status": "公式项",
        "grade": "公式项",
        "evidence": "",
        "reason": f"本条是该招标文件的报价/公式规则「{raw['name']}」，已按原文收录。模拟评委不估算实际报价得分，需代入本项目公式核算。规则原文：{raw['rule']}",
        "suggestion": f"按本项目招标公式核算报价。高分策略：" + "；".join(f"{s['category']}：{s['point']}" for s in strategies),
        "strategies": strategies,
    }


def _failed_entry(raw: dict, strategies: list[dict], err: str) -> dict:
    return {
        "id": raw["id"],
        "group": raw["group"],
        "name": raw["name"],
        "rule": raw["rule"],
        "maxScore": raw["maxScore"],
        "score": 0.0,
        "status": "未能评审",
        "grade": "未能评审",
        "evidence": "",
        "reason": f"模拟评委未能完成本条评审（{err}）。本条招标规则：{raw['rule']}",
        "suggestion": f"请重试全量预审。仍应按本项目招标「{raw['name']}」原文准备响应。",
        "strategies": strategies,
    }


def _judged_entry(raw: dict, judged: dict, strategies: list[dict]) -> dict:
    max_score = float(raw["maxScore"] or 0)
    try:
        score = float(judged.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    if max_score > 0:
        score = max(0.0, min(max_score, round(score, 1)))
    else:
        score = max(0.0, round(score, 1))
    grade = str(judged.get("grade") or "").strip() or ("未响应" if score <= 0 else "已评分")
    reason = str(judged.get("reason") or "").strip() or "评委未给出书面理由。"
    suggestion = str(judged.get("suggestion") or "").strip()
    clauses = "；".join(f"{s['category']}：{s['point']}" for s in strategies)
    if clauses:
        suggestion = f"{suggestion} 高分策略：{clauses}".strip()
    return {
        "id": raw["id"],
        "group": raw["group"],
        "name": raw["name"],
        "rule": raw["rule"],
        "maxScore": raw["maxScore"],
        "score": score,
        "status": grade,
        "grade": grade,
        "evidence": str(judged.get("evidence") or "").strip(),
        "reason": reason,
        "suggestion": suggestion or f"按本项目招标「{raw['name']}」原文补强。",
        "strategies": strategies,
    }


def run(
    full_text: str,
    score_rules: list | None = None,
    tree: list | None = None,
    headings: list[str] | None = None,
    strategy_keys: set[str] | None = None,
) -> dict:
    bid = full_text or ""
    raw_items = expand_score_items(score_rules, tree)
    grade_book = _collect_grade_book(tree)
    digest = _digest(bid, headings)

    judged_map: dict[str, dict] = {}
    to_judge = [it for it in raw_items if not it["formula"]]
    if to_judge:
        try:
            model_id = get_default_model_id()
        except Exception as exc:  # noqa: BLE001
            model_id = ""
            for it in to_judge:
                judged_map[it["id"]] = {"_error": f"未配置可用大模型（{exc}）"}
        if model_id:
            for i in range(0, len(to_judge), _BATCH):
                batch = to_judge[i : i + _BATCH]
                for it in batch:
                    it["window"] = _windows(it["name"], it["rule"], bid)
                try:
                    judged_map.update(_judge_batch(model_id, batch, digest, grade_book))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("tender rule judge batch failed")
                    for it in batch:
                        judged_map.setdefault(it["id"], {"_error": exc.__class__.__name__})

    groups: dict[str, list[dict]] = {}
    for raw in raw_items:
        strategies = _pick_strategies(raw["name"], raw["rule"], strategy_keys)
        if raw["formula"]:
            entry = _formula_entry(raw, strategies)
        else:
            judged = judged_map.get(raw["id"]) or {}
            if judged.get("_error") or not judged:
                entry = _failed_entry(raw, strategies, str(judged.get("_error") or "无评委返回"))
            else:
                entry = _judged_entry(raw, judged, strategies)
        groups.setdefault(raw["group"], []).append(entry)

    ordered_keys = [k for k in _GROUP_ORDER if k in groups] + [k for k in groups if k not in _GROUP_ORDER]
    group_out = []
    total_max = 0.0
    total_score = 0.0
    for key in ordered_keys:
        items = groups[key]
        g_max = sum(i["maxScore"] for i in items if i["status"] != "公式项")
        g_score = sum(i["score"] for i in items if i["status"] not in ("公式项", "未能评审"))
        total_max += g_max
        total_score += g_score
        group_out.append(
            {
                "key": key,
                "label": key if key.endswith(("规则", "标准", "评审")) else f"{key}评分规则",
                "maxScore": round(g_max, 1),
                "score": round(g_score, 1),
                "items": items,
            }
        )

    percent = round(total_score / total_max * 100, 1) if total_max else 0.0
    return {
        "judgeMode": True,
        "totalMax": round(total_max, 1),
        "totalScore": round(total_score, 1),
        "percent": percent,
        "groups": group_out,
        "note": "本报告由模拟评委通读投标文件后，严格按本项目招标评分规则原文及档次公式逐条赋分；每份招标书规则不同。报价公式项不估算实际报价。结论仅供投标前自查，不替代评标委员会。",
    }
