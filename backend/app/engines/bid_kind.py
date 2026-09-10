"""投标文件分册：商务标 / 技术标 / 合订。"""

from __future__ import annotations

KIND_BUSINESS = "business"
KIND_TECH = "tech"
KIND_COMBINED = "combined"
KINDS = {KIND_BUSINESS, KIND_TECH, KIND_COMBINED}

SCOPE_BUSINESS = "business"
SCOPE_TECH = "tech"
SCOPE_FULL = "full"
SCOPES = {SCOPE_BUSINESS, SCOPE_TECH, SCOPE_FULL}

BOOKLET_LEVELS = {
    SCOPE_BUSINESS: ("L1", "L2"),
    SCOPE_TECH: ("L3", "L4", "L5"),
}
BOOKLET_WEIGHTS = {
    SCOPE_BUSINESS: {"L1": 0.40, "L2": 0.60},
    SCOPE_TECH: {"L3": 0.55, "L4": 0.25, "L5": 0.20},
}

_BUSINESS_HINTS = ("商务标", "商务部分", "商务文件", "商务", "资格文件", "资格审查", "业绩证明", "投标函", "资信")
_TECH_HINTS = ("技术标", "技术文件", "技术部分", "施组", "施工组织", "技术方案", "施工方案")


def guess_bid_kind(filename: str) -> str:
    name = filename or ""
    biz = any(k in name for k in _BUSINESS_HINTS)
    tech = any(k in name for k in _TECH_HINTS)
    if biz and tech:
        return KIND_COMBINED
    if biz:
        return KIND_BUSINESS
    if tech:
        return KIND_TECH
    return KIND_COMBINED


def normalize_kind(kind: str | None, filename: str = "") -> str:
    raw = (kind or "").strip().lower()
    if raw in (KIND_BUSINESS, KIND_TECH):
        return raw
    guessed = guess_bid_kind(filename)
    if guessed in (KIND_BUSINESS, KIND_TECH):
        return guessed
    if raw in KINDS:
        return raw
    return guessed


def scope_for_kind(kind: str) -> str:
    if kind == KIND_BUSINESS:
        return SCOPE_BUSINESS
    if kind == KIND_TECH:
        return SCOPE_TECH
    return SCOPE_FULL


def normalize_scope(scope: str | None, kind: str = KIND_COMBINED) -> str:
    raw = (scope or "").strip().lower()
    if raw in SCOPES:
        return raw
    return scope_for_kind(kind)


def is_business_group(name: str) -> bool:
    blob = name or ""
    if any(k in blob for k in ("报价", "价格")):
        return True
    return any(k in blob for k in ("商务", "资信", "业绩", "信用"))


def is_tech_group(name: str) -> bool:
    blob = name or ""
    if is_business_group(blob) and "技术" not in blob:
        return False
    return any(k in blob for k in ("技术", "施工", "设计", "方案", "施组"))


BUSINESS_SOURCE_IDS = {
    "eval-business",
    "env-business",
    "business-credit",
    "business-commerce",
    "business-price",
    "pro-standard",
}
TECH_SOURCE_IDS = {
    "eval-tech",
    "env-tech",
    "review-tech",
    "review-service",
    "review-after",
}
PRICE_SOURCE_IDS = {"business-price", "env-price", "env-calc"}


def booklet_of_source(source_item_id: str, label: str = "") -> str:
    """business | tech | price | ''。优先解析槽 id，没有再回退分组名。"""
    sid = (source_item_id or "").strip()
    if sid in PRICE_SOURCE_IDS:
        return "price"
    if sid in BUSINESS_SOURCE_IDS:
        return "business"
    if sid in TECH_SOURCE_IDS:
        return "tech"
    if "price" in sid or sid.endswith("calc"):
        return "price"
    if "business" in sid:
        return "business"
    if "tech" in sid or sid.startswith("review-"):
        return "tech"
    blob = label or ""
    if any(k in blob for k in ("报价", "价格", "限价")):
        return "price"
    if is_business_group(blob):
        return "business"
    if is_tech_group(blob):
        return "tech"
    return ""


def booklet_of_format(source_item_id: str, label: str = "") -> str:
    """格式/递交约定分到哪一册。三信封组成、商务不得报价走商务；暗标/技术格式走技术。"""
    sid = (source_item_id or "").strip()
    blob = label or ""
    if sid == "req-compose" or any(
        k in blob for k in ("三份文件", "三信封", "信息隔离", "商务文件不得", "不得出现报价")
    ):
        return "business"
    if sid in ("req-submit", "req-encrypt", "req-delivery"):
        return ""
    if sid in ("req-format", "req-formatrule") or any(k in blob for k in ("暗标", "技术标", "技术文件", "页数", "字体", "装订")):
        if any(k in blob for k in ("商务文件", "报价文件", "三份文件")):
            return "business"
        return "tech"
    if sid == "req-seal" or any(k in blob for k in ("盖章", "密封", "签署")):
        return "business"
    if any(k in blob for k in ("报价", "价格")):
        return "price"
    if any(k in blob for k in ("商务", "资格")):
        return "business"
    if any(k in blob for k in ("技术", "暗标")):
        return "tech"
    return ""


def format_requirements_for_scope(items: list | None, scope: str) -> list:
    rows = [i for i in (items or []) if isinstance(i, dict)]
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH):
        return rows
    kept = []
    for item in rows:
        blob = f"{item.get('title') or ''}{item.get('desc') or ''}{item.get('source') or ''}"
        slot = booklet_of_format(str(item.get("sourceItemId") or ""), blob)
        if scope == SCOPE_TECH and slot == "tech":
            kept.append(item)
        elif scope == SCOPE_BUSINESS and slot in ("business", "price"):
            kept.append(item)
    return kept


def tree_for_scope(tree: list | None, scope: str) -> list:
    """按解析槽把招标树切到本册，避免商务文件给技术因素打分后再扔掉。"""
    dims = [d for d in (tree or []) if isinstance(d, dict)]
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH):
        return dims
    out: list[dict] = []
    for dim in dims:
        items = []
        for item in dim.get("items") or []:
            if not isinstance(item, dict):
                continue
            slot = booklet_of_source(str(item.get("id") or ""), str(item.get("label") or ""))
            if scope == SCOPE_BUSINESS and slot in ("business", "price"):
                items.append(item)
            elif scope == SCOPE_TECH and slot == "tech":
                items.append(item)
        if items:
            cloned = dict(dim)
            cloned["items"] = items
            out.append(cloned)
    return out


def score_rules_for_scope(score_rules: list | None, scope: str) -> list:
    rules = [r for r in (score_rules or []) if isinstance(r, dict)]
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH):
        return rules
    kept = []
    for item in rules:
        slot = booklet_of_source(str(item.get("sourceItemId") or ""), str(item.get("dimension") or ""))
        if scope == SCOPE_BUSINESS and slot in ("business", "price"):
            kept.append(item)
        elif scope == SCOPE_TECH and slot == "tech":
            kept.append(item)
    return kept


def _looks_heading(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) > 48 or "。" in s:
        return False
    return True


def split_paragraphs_for_scope(paragraphs: list[dict], scope: str) -> list[dict]:
    """合订文件按目录切开本册；切不出两端标题则整份保留，避免误删。"""
    paras = [p for p in (paragraphs or []) if isinstance(p, dict)]
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH) or not paras:
        return paras
    kinds: list[str | None] = []
    current: str | None = None
    for p in paras:
        text = (p.get("text") or "").strip()
        if _looks_heading(text):
            if is_business_group(text) or any(k in text for k in ("资格", "投标函", "商务部分")):
                current = SCOPE_BUSINESS
            elif is_tech_group(text) or any(k in text for k in ("技术部分", "施工组织")):
                current = SCOPE_TECH
        kinds.append(current)
    if SCOPE_BUSINESS not in kinds or SCOPE_TECH not in kinds:
        return paras
    return [p for p, kind in zip(paras, kinds) if kind == scope]


def filter_tender_rules(report: dict | None, scope: str) -> dict:
    data = dict(report or {})
    groups = [g for g in (data.get("groups") or []) if isinstance(g, dict)]
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH):
        return data
    kept = []
    for group in groups:
        label = str(group.get("label") or group.get("key") or "")
        items = [i for i in (group.get("items") or []) if isinstance(i, dict)]
        filtered = []
        for item in items:
            slot = booklet_of_source(str(item.get("sourceItemId") or ""), label + str(item.get("name") or ""))
            if scope == SCOPE_BUSINESS and slot in ("business", "price"):
                filtered.append(item)
            elif scope == SCOPE_TECH and slot == "tech":
                filtered.append(item)
        if not items:
            if scope == SCOPE_BUSINESS and is_business_group(label):
                kept.append(group)
            elif scope == SCOPE_TECH and is_tech_group(label):
                kept.append(group)
            continue
        if not filtered:
            continue
        g = dict(group)
        g["items"] = filtered
        g["maxScore"] = round(sum(float(i.get("maxScore") or 0) for i in filtered if i.get("status") != "公式项"), 1)
        g["score"] = round(sum(float(i.get("score") or 0) for i in filtered if i.get("status") not in ("公式项", "未能评审")), 1)
        kept.append(g)
    data["groups"] = kept
    total_max = sum(float(g.get("maxScore") or 0) for g in kept)
    total_score = sum(float(g.get("score") or 0) for g in kept)
    data["totalMax"] = round(total_max, 1)
    data["totalScore"] = round(total_score, 1)
    data["percent"] = round(100.0 * total_score / total_max, 1) if total_max else 0.0
    return data


def booklet_overall(levels: list, scope: str) -> float:
    weights = BOOKLET_WEIGHTS.get(scope) or {}
    keys = BOOKLET_LEVELS.get(scope) or ()
    score_by_key = {str(lv.get("key")): float(lv.get("score") or 0) for lv in (levels or []) if isinstance(lv, dict)}
    return round(sum(score_by_key.get(k, 0.0) * weights.get(k, 0.0) for k in keys), 1)


def project_booklet_payload(payload: dict, scope: str) -> dict:
    """把合订 full 结果切成商务或技术分册视图，各自满分 100，不再混算。"""
    if scope not in (SCOPE_BUSINESS, SCOPE_TECH):
        return payload
    keys = set(BOOKLET_LEVELS[scope])
    levels = [lv for lv in (payload.get("levels") or []) if isinstance(lv, dict) and lv.get("key") in keys]
    issues = [i for i in (payload.get("issues") or []) if isinstance(i, dict) and (i.get("level") or "") in keys]
    waste = sum(1 for i in issues if i.get("severity") == "废标")
    risk = sum(1 for i in issues if i.get("severity") in ("降档", "扣分"))
    suggest = sum(1 for i in issues if i.get("severity") == "建议")
    if waste:
        light = "红"
    elif risk:
        light = "橙"
    else:
        light = "绿"
    out = dict(payload)
    out["scope"] = scope
    out["levels"] = levels
    out["overall"] = booklet_overall(levels, scope)
    out["issues"] = issues
    out["waste"] = waste
    out["risk"] = risk
    out["suggest"] = suggest
    out["light"] = light
    if scope == SCOPE_BUSINESS:
        out["dimensions"] = []
        out["techModules"] = []
    tender = payload.get("tenderRules")
    if tender is None:
        tender = payload.get("tender_rules")
    out["tenderRules"] = filter_tender_rules(tender, scope)
    return out

