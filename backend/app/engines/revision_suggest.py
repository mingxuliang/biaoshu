"""修改闭环：把预审 Finding 挂到「预审规则 · 高分策略」条款，并生成可回写原文的改写句。"""

from __future__ import annotations

import json
import re

from .rules_data import HIGH_SCORE_STRATEGIES

_QUOTE_RE = re.compile(r"[「“\"]([^」”\"]{6,})[」”\"]")
_PREFIX_RE = re.compile(r"^【预审规则[^\n】]*】")

_STRATEGY_HINTS: dict[str, tuple[str, ...]] = {
    "quantify": ("虚词", "空话", "加强", "确保", "力争", "量化", "态度词", "万能动词"),
    "originality": ("查重", "相似", "模板", "雷同", "原创"),
    "structured_layout": ("目录", "标题", "修订", "批注", "页码", "跳级", "版式"),
    "chart_meta": ("作者", "元数据", "暗标", "文档属性"),
    "local_first": ("本地", "属地", "售后", "网点", "分支"),
    "data_loop": ("宿舍", "临建", "人均", "高峰人数", "交叉验"),
    "code_cite": ("规范", "条文", "废止", "GB/", "JGJ"),
    "zero_veto": ("废标", "星号", "有效期", "保证金", "资质", "报价", "签字", "盖章"),
    "checklist_map": ("评分点", "未覆盖", "缺项", "未响应", "对照"),
}


def _strategy_by_key(key: str) -> dict | None:
    for item in HIGH_SCORE_STRATEGIES:
        if item.get("key") == key:
            return item
    return None


def pick_strategy(issue: dict) -> dict | None:
    """按问题原文/规则/层级选一条高分策略。已有 strategyKey 时复用。"""
    existing = (issue.get("strategyKey") or "").strip()
    if existing:
        found = _strategy_by_key(existing)
        if found:
            return found

    blob = "".join(
        str(issue.get(k) or "")
        for k in ("rule", "location", "excerpt", "suggestion", "level", "severity")
    )
    level = str(issue.get("level") or "")
    if level == "L1" or issue.get("severity") == "废标":
        return _strategy_by_key("zero_veto")

    scored: list[tuple[int, dict]] = []
    for item in HIGH_SCORE_STRATEGIES:
        key = item.get("key") or ""
        hints = _STRATEGY_HINTS.get(key) or ()
        hits = sum(1 for h in hints if h and h in blob)
        if hits:
            scored.append((hits, item))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    if level == "L4":
        return _strategy_by_key("quantify")
    if level == "L5":
        return _strategy_by_key("structured_layout")
    if level == "L2":
        return _strategy_by_key("local_first")
    return _strategy_by_key("checklist_map") or _strategy_by_key("quantify")


def _clause_text(strategy: dict) -> str:
    items = [str(x) for x in (strategy.get("items") or []) if x]
    return "；".join(items[:3]) if items else (strategy.get("point") or "")


def format_strategy_suggestion(issue: dict, strategy: dict | None) -> str:
    raw = (issue.get("suggestion") or "").strip()
    if not strategy:
        return raw
    if "预审规则" in raw and "高分策略" in raw:
        return raw
    category = strategy.get("category") or strategy.get("key") or ""
    point = strategy.get("point") or ""
    clauses = _clause_text(strategy)
    prefix = (
        f"【预审规则 · 高分策略 · {category}】"
        f"条款：{point}"
        f"{('（' + clauses + '）') if clauses and clauses != point else ''}。"
        f"按此写法可拿高分。"
    )
    return f"{prefix} {raw}".strip()


def enrich_issue(issue: dict) -> dict:
    """给闭环 issue 补策略字段，并改写 suggestion 使其点名高分条款。"""
    out = dict(issue)
    strategy = pick_strategy(out)
    if strategy:
        out["strategyKey"] = strategy.get("key") or ""
        out["strategyCategory"] = strategy.get("category") or ""
        out["strategyPoint"] = strategy.get("point") or ""
        out["strategyClauses"] = list(strategy.get("items") or [])
        out["suggestion"] = format_strategy_suggestion(out, strategy)
    if not out.get("applyText"):
        derived = heuristic_apply_text(out.get("excerpt") or "", out.get("suggestion") or "")
        if derived:
            out["applyText"] = derived
    return out


def heuristic_apply_text(excerpt: str, suggestion: str) -> str:
    """从建议里抽出可直接替换 excerpt 的句子；抽不到则返回空，交给 LLM。"""
    text = _PREFIX_RE.sub("", suggestion or "").strip()
    text = re.sub(r"^条款：[^。]*。", "", text).strip()
    text = re.sub(r"^按此写法可拿高分。", "", text).strip()
    quotes = [q.strip() for q in _QUOTE_RE.findall(suggestion or "") if q.strip()]
    for q in quotes:
        if q in ("预审规则",) or "高分策略" in q:
            continue
        if excerpt and q == excerpt:
            continue
        return q
    for prefix in ("改为", "改写为", "替换为", "改成", "补写", "补填", "重写为"):
        if text.startswith(prefix):
            rest = re.sub(rf"^{prefix}[：:，,\s]*", "", text).strip()
            rest = rest.split("。")[0].strip()
            if len(rest) >= 6:
                return rest
    return ""


def replace_in_paragraph(paragraph: str, excerpt: str, replacement: str) -> str:
    if not replacement:
        return paragraph
    if excerpt and excerpt in paragraph:
        return paragraph.replace(excerpt, replacement, 1)
    return replacement


def apply_text_to_paragraph(paragraph: str, excerpt: str, suggestion: str, apply_text: str = "") -> str:
    replacement = (apply_text or "").strip() or heuristic_apply_text(excerpt, suggestion)
    if not replacement:
        replacement = (suggestion or "").strip()
        replacement = _PREFIX_RE.sub("", replacement).strip()
        replacement = re.sub(r"^条款：[^。]*。", "", replacement).strip()
        replacement = re.sub(r"^按此写法可拿高分。", "", replacement).strip()
    return replace_in_paragraph(paragraph, excerpt, replacement)


def llm_rewrite_paragraph(paragraph: str, excerpt: str, suggestion: str, strategy: dict | None) -> str:
    """把建议落成可替换的整段正文；失败时返回空串。"""
    from .llm import LlmError, chat_complete, get_default_model_id

    clause = ""
    if strategy:
        clause = f"{strategy.get('category') or ''}：{strategy.get('point') or ''}（{_clause_text(strategy)}）"
    prompt = (
        "你是投标文件改写编辑。请按预审整改建议改写【当前段落】，直接输出改写后的整段正文，不要解释。\n"
        "要求：\n"
        "1. 必须落实高分策略条款，用数量、时限、频次、百分比、规范条文号等可核验表述替换空话。\n"
        "2. 只改与 excerpt 相关的句子，其余事实、项目名称、已有数据不得编造或删除。\n"
        "3. 不要输出目录行、不要输出「建议：」前缀。\n"
        f"高分策略条款：{clause or '数据代替定性空话'}\n"
        f"问题摘录：{excerpt}\n"
        f"整改建议：{suggestion}\n"
        f"当前段落：{paragraph}\n"
    )
    try:
        raw = chat_complete(
            model_id=get_default_model_id(),
            messages=[
                {"role": "system", "content": "只输出改写后的投标书段落正文。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            timeout=45,
            max_tokens=800,
        )
    except (LlmError, Exception):
        return ""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    text = text.strip().strip('"').strip("“”")
    if len(text) < 4 or text.startswith("{") or text.startswith("【"):
        return ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return str(parsed.get("text") or parsed.get("paragraph") or "")[:2000]
    except (json.JSONDecodeError, TypeError):
        pass
    return text[:2000]


def patch_lexical_text(state: dict | None, old: str, new: str) -> bool:
    """在 Lexical 序列化 JSON 里把第一次出现的 old 换成 new。"""
    if not state or not old or old == new:
        return False

    found = False

    def walk(node):
        nonlocal found
        if found:
            return
        if isinstance(node, dict):
            if node.get("type") == "text" and old in str(node.get("text") or ""):
                node["text"] = str(node["text"]).replace(old, new, 1)
                found = True
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(state)
    return found
