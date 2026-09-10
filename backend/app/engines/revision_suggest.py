"""修改闭环：沿用 AI 预审 Finding 的规则与建议，生成可回写原文的改写句。"""

from __future__ import annotations

import json
import re

_QUOTE_RE = re.compile(r"[「“\"]([^」”\"]{6,})[」”\"]")
_PREFIX_RE = re.compile(r"^【预审规则[^\n】]*】")
_TRAILING_STRATEGY_RE = re.compile(r"[。；\s]*高分策略[：:].+$")
_CLAUSE_LEAD_RE = re.compile(r"^条款：[^。]*。\s*")
_SCORE_LEAD_RE = re.compile(r"^按此写法可拿高分。\s*")


def strip_strategy_overlay(text: str) -> str:
    """去掉历史上挂上的「高分策略库」前缀/后缀，保留预审引擎自己的建议。"""
    raw = (text or "").strip()
    raw = _PREFIX_RE.sub("", raw).strip()
    raw = _CLAUSE_LEAD_RE.sub("", raw).strip()
    raw = _SCORE_LEAD_RE.sub("", raw).strip()
    raw = _TRAILING_STRATEGY_RE.sub("", raw).strip()
    return raw


def fallback_suggestion(issue: dict) -> str:
    rule = str(issue.get("rule") or "").strip() or "本条预审规则"
    quote = str(issue.get("tenderQuote") or "").strip()
    excerpt = str(issue.get("excerpt") or "").strip()
    if excerpt:
        return f"请按预审规则「{rule}」改写命中句，补全可核验的响应内容，删除空话与未响应表述。"
    if quote:
        return f"投标书未定位到对应句。请按预审规则「{rule}」补写对标响应，落实招标要求：「{quote[:80]}」。"
    return f"请按预审规则「{rule}」补全可核验的响应内容。"


def llm_write_suggestion(issue: dict) -> str:
    """预审未给出建议时，按该条预审规则补一条可执行的改写建议。"""
    from .llm import LlmError, chat_complete, get_default_model_id

    rule = str(issue.get("rule") or "").strip()
    quote = str(issue.get("tenderQuote") or "").strip()
    excerpt = str(issue.get("excerpt") or "").strip()
    location = str(issue.get("location") or "").strip()
    severity = str(issue.get("severity") or "").strip()
    prompt = (
        "你是投标文件预审整改编辑。请只根据【本条 AI 预审规则】给出一条可执行的修改建议，不要引用「高分策略库」。\n"
        "要求：指出改哪一句、改成什么样（尽量带数量、时限、频次、百分比或规范条文号）；不要输出标题或前缀。\n"
        f"层级/严重度：{issue.get('level') or ''} / {severity}\n"
        f"定位：{location}\n"
        f"预审规则：{rule}\n"
        f"招标对标原文：{quote or '（无，投标书自洽核验）'}\n"
        f"投标书命中句：{excerpt or '（缺项/未定位）'}\n"
    )
    try:
        raw = chat_complete(
            model_id=get_default_model_id(),
            messages=[
                {"role": "system", "content": "只输出一条中文修改建议，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            timeout=30,
            max_tokens=280,
        )
    except (LlmError, Exception):
        return ""
    text = strip_strategy_overlay((raw or "").strip().strip('"').strip("“”"))
    if len(text) < 8 or text.startswith("{") or text.startswith("【"):
        return ""
    return text[:500]


def enrich_issue(issue: dict) -> dict:
    """沿用预审规则与建议；去掉高分策略库字段；缺建议时给出按该条规则的修改说明。"""
    out = dict(issue)
    sk = str(out.get("strategyKey") or "")
    out["strategyKey"] = sk
    out["strategyCategory"] = str(out.get("strategyCategory") or "")
    out["strategyPoint"] = str(out.get("strategyPoint") or "")
    out["strategyClauses"] = list(out.get("strategyClauses") or []) if isinstance(out.get("strategyClauses"), list) else []
    suggestion = strip_strategy_overlay(str(out.get("suggestion") or ""))
    if len(suggestion) < 8:
        suggestion = fallback_suggestion(out)
    out["suggestion"] = suggestion
    if not out.get("applyText"):
        derived = heuristic_apply_text(out.get("excerpt") or "", suggestion)
        if derived:
            out["applyText"] = derived
    return out


def heuristic_apply_text(excerpt: str, suggestion: str) -> str:
    """从建议里抽出可直接替换 excerpt 的句子；抽不到则返回空，交给 LLM。"""
    text = strip_strategy_overlay(suggestion or "")
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
        replacement = strip_strategy_overlay(suggestion or "")
    return replace_in_paragraph(paragraph, excerpt, replacement)


def llm_rewrite_paragraph(paragraph: str, excerpt: str, suggestion: str, issue: dict | None = None) -> str:
    """按本条预审规则把建议落成可替换的整段正文；失败时返回空串。"""
    from .llm import LlmError, chat_complete, get_default_model_id

    info = issue or {}
    rule = str(info.get("rule") or "").strip()
    quote = str(info.get("tenderQuote") or "").strip()
    prompt = (
        "你是投标文件改写编辑。请按【本条 AI 预审规则】和整改建议改写【当前段落】，直接输出改写后的整段正文，不要解释。\n"
        "要求：\n"
        "1. 只落实本条预审规则与招标对标原文，不要套用「高分策略库」。\n"
        "2. 用数量、时限、频次、百分比、规范条文号等可核验表述替换空话。\n"
        "3. 只改与 excerpt 相关的句子，其余事实、项目名称、已有数据不得编造或删除。\n"
        "4. 不要输出目录行、不要输出「建议：」前缀。\n"
        f"预审规则：{rule or '（未标注规则名）'}\n"
        f"招标对标原文：{quote or '（无，按预审建议自洽修改）'}\n"
        f"问题摘录：{excerpt}\n"
        f"整改建议：{strip_strategy_overlay(suggestion)}\n"
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
