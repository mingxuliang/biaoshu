"""投标书摘句不得写成招标条款。

历史数据里，星号条款/约定对照未响应时，曾把招标原文放进 excerpt、只把栏目名放进 tender_quote。
写入与读出都走这里，旧报告刷新即可左右栏纠正。
"""

from __future__ import annotations

import difflib
import re

_WS = re.compile(r"\s+")
_DUMP_RULES = ("F02.06", "招标解析约定")
_SENT = re.compile(r"[。！？；\n]")
_WRAP = re.compile(r"^[「『“\"'《（(\[]+|[」』”\"'》）)\]]+$")
_TOC = re.compile(r"[.·．…]{4,}")
_HEAD_NO = re.compile(r"^[\d.]+")
_SCORE_VOICE = re.compile(
    r"不得分|不提供不得|最高\s*\d+\s*分|(?:1个|每[个项张]).{0,12}\d+\s*分|需提供有效期内"
)
_BID_SELF = re.compile(r"我司|本公司|我方|我单位|本投标人")
_REJECT_CLAUSE = re.compile(r"责令停业|吊销执照|吊销资质|暂扣或吊销")


def is_tender_score_voice(text: str) -> bool:
    """招标评分口吻（几分、不得分），不是投标人在陈述自身证书。"""
    s = text or ""
    if _BID_SELF.search(s):
        return False
    return bool(_SCORE_VOICE.search(s))


def is_reject_clause(text: str) -> bool:
    return bool(_REJECT_CLAUSE.search(text or ""))


def _norm(text: str) -> str:
    return _WS.sub("", text or "")


_FIGURE_MARK = re.compile(r"【附图\d+[：:]([^】｜|]+)")
_DOTTED_HEAD = re.compile(r"^(\d+(?:\.\d+)+)\s*")


def visible_needles(excerpt: str = "", location: str = "") -> list[str]:
    """把预审摘句变成源文件里真实存在的文字。

    预审原文包会写入【附图N：章节】，Word 源文件没有这句；锚点必须改搜章节标题。
    不要用「5.2.5」这种短编号单独去搜，否则会落到同级错误证书章节。
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        raw = (text or "").strip().strip("「」『』“”\"'")
        if len(raw) < 4 or "【附图" in raw:
            return
        key = _norm(raw)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(raw)

    for blob in (excerpt, location):
        if not blob:
            continue
        mark = _FIGURE_MARK.search(blob)
        if mark:
            add(mark.group(1))
        tail = blob.split("/")[-1].strip() if "/" in blob else blob.strip()
        mark_tail = _FIGURE_MARK.search(tail)
        if mark_tail:
            add(mark_tail.group(1))
        else:
            add(tail)

    extras: list[str] = []
    for item in list(out):
        m = _DOTTED_HEAD.match(item)
        if not m:
            continue
        rest = item[m.end() :].strip(" .、:：")
        if len(rest) >= 6:
            extras.append(rest)
    for item in extras:
        add(item)
    out.sort(key=lambda s: (-len(_norm(s)), -len(s)))
    return out


def source_visible_text(excerpt: str = "", location: str = "") -> str:
    needles = visible_needles(excerpt, location)
    if needles:
        return needles[0]
    cleaned = (excerpt or "").strip()
    return "" if "【附图" in cleaned else cleaned


_SKIP_CHAPTER = {
    "技术标",
    "商务标",
    "投标文件",
    "评分细则",
    "资格文件",
    "资格条件",
    "证件识读",
    "技术评分模块",
}
_NUM_CHAPTER = re.compile(
    r"^(\d+(?:\.\d+)+)|"
    r"^第[0-9一二三四五六七八九十百零]+[章节篇]|"
    r"^[（(][一二三四五六七八九十]+[）)]|"
    r"^[一二三四五六七八九十]+、"
)
_GENERIC_SEMANTIC = re.compile(r"五维语义评审")
_RULE_MARK = re.compile(r"【预审规则[-—]([^】]+)】")
_BOOK_TITLE = re.compile(r"《([^》]+)》")
_STRATEGY_BY_KEY = {
    "checklist_map": "高分策略：清单化对标响应",
    "quantify": "高分策略：数据代替定性空话",
    "originality": "高分策略：原创度控制红线",
    "local_first": "高分策略：本地化策略优先",
    "structured_layout": "高分策略：严格结构化排版",
    "data_loop": "高分策略：数据链逻辑闭环",
    "chart_meta": "高分策略：图表自制规范",
    "code_cite": "高分策略：规范引用精准",
}
_STRATEGY_ALIAS = {
    "数字代替定性空话": "数据代替定性空话",
    "数据代替定性空话": "数据代替定性空话",
    "清单化对标响应": "清单化对标响应",
    "本地化策略优先": "本地化策略优先",
    "本地化策略": "本地化策略优先",
    "原创度控制红线": "原创度控制红线",
    "严格结构化排版": "严格结构化排版",
    "数据链逻辑闭环": "数据链逻辑闭环",
    "图表自制规范": "图表自制规范",
    "规范引用精准": "规范引用精准",
}


def chapter_from_location(location: str = "") -> str:
    """把引擎拼接的定位路径收成投标书章节名。"""
    parts = [p.strip() for p in re.split(r"[／/]", location or "") if p.strip() and p.strip() not in _SKIP_CHAPTER]
    if not parts:
        return (location or "").strip()
    rest = parts[1:] if len(parts) >= 2 else parts
    numbered = [p for p in rest if _NUM_CHAPTER.match(p)]
    if numbered:
        return numbered[-1]
    return rest[-1]


_RULE_CODE = re.compile(r"^F\d{2}\.\d{2}\s+")


def display_rule(rule: str = "", suggestion: str = "", strategy_key: str = "") -> str:
    """五维语义条目改成命中的高分策略/规则名；其它引擎去掉 F 编号只留规则名。"""
    key = (strategy_key or "").strip()
    if key in _STRATEGY_BY_KEY:
        return _STRATEGY_BY_KEY[key]
    sug = suggestion or ""
    mark = _RULE_MARK.search(sug)
    if mark:
        body = mark.group(1).strip()
        book = _BOOK_TITLE.search(body)
        name = (book.group(1) if book else body).strip()
        name = _STRATEGY_ALIAS.get(name, name)
        if "高分策略" in body or book:
            if not name.startswith("高分策略"):
                return f"高分策略：{name}"
            return name
        return body
    raw = (rule or "").strip()
    if _GENERIC_SEMANTIC.search(raw):
        return "五维语义评审"
    return _RULE_CODE.sub("", raw).strip() or "未标注规则"


def _strip_wrap(text: str) -> str:
    s = (text or "").strip()
    for _ in range(3):
        nxt = _WRAP.sub("", s).strip()
        if nxt == s:
            break
        s = nxt
    return s


def _is_toc(text: str) -> bool:
    s = (text or "").strip()
    return bool(_TOC.search(s)) or (len(s) <= 48 and "。" not in s and s.count(".") >= 2)


def hit_sentence(
    full_text: str,
    paragraphs: list[dict] | None,
    keywords: tuple[str, ...] | list[str],
    extra_context: int = 24,
    max_len: int = 180,
    skip_score_voice: bool = False,
    skip_reject: bool = False,
) -> str:
    """从投标书摘含关键词的那一句，禁止用超长段落开头冒充命中句。"""
    keys = tuple(k for k in keywords if k)
    if not keys:
        return ""
    blobs = [(p.get("text") or "").strip() for p in (paragraphs or []) if isinstance(p, dict) and (p.get("text") or "").strip()]
    if not blobs:
        blob = (full_text or "").strip()
        if blob:
            blobs = [blob]
    for text in blobs:
        if not any(k in text for k in keys):
            continue
        for sent in _SENT.split(text):
            sent = sent.strip()
            if not sent or _is_toc(sent) or not any(k in sent for k in keys):
                continue
            if skip_score_voice and is_tender_score_voice(sent):
                continue
            if skip_reject and is_reject_clause(sent):
                continue
            if len(sent) <= max_len:
                return sent
            hits = [sent.find(k) for k in keys if k in sent]
            hits = [i for i in hits if i >= 0]
            idx = min(hits) if hits else 0
            start = max(0, idx - extra_context)
            return sent[start : start + max_len]
        hits = [text.find(k) for k in keys if k in text]
        hits = [i for i in hits if i >= 0]
        if not hits:
            continue
        snippet = text[max(0, min(hits) - extra_context) : min(hits) + max_len]
        if skip_score_voice and is_tender_score_voice(snippet):
            continue
        if skip_reject and is_reject_clause(snippet):
            continue
        idx = min(hits)
        start = max(0, idx - extra_context)
        return text[start : start + max_len]
    return ""



def _sentences(hay: str) -> list[str]:
    out: list[str] = []
    for s in _SENT.split(hay or ""):
        s = s.strip()
        if len(s) >= 8 and not _is_toc(s):
            out.append(s)
    return out


def _needles(text: str) -> list[str]:
    n = _norm(text)
    sizes = [size for size in (16, 12, 8) if len(n) >= size]
    if not sizes:
        return [n] if len(n) >= 4 else []
    size = sizes[0]
    step = max(1, size // 2)
    return [n[i : i + size] for i in range(0, len(n) - size + 1, step)][:8]


def _snap_one(excerpt: str, hay: str) -> str:
    excerpt = _strip_wrap(excerpt)
    if not excerpt or not hay:
        return ""
    if excerpt in hay:
        return excerpt[:200]
    n_ex = _norm(excerpt)
    if n_ex and n_ex in _norm(hay) and excerpt[:12] in hay:
        return excerpt[:200]
    sents = _sentences(hay)
    for needle in _needles(excerpt):
        for s in sents:
            if needle in s or needle in _norm(s):
                return s[:200]
    if len(n_ex) >= 12:
        best = ("", 0.0)
        for s in sents:
            n_s = _norm(s)
            if len(n_s) < 8:
                continue
            if n_ex in n_s or n_s in n_ex:
                return s[:200]
            ratio = difflib.SequenceMatcher(None, n_ex[:80], n_s[:80]).ratio()
            if ratio > best[1]:
                best = (s, ratio)
        if best[1] >= 0.55:
            return best[0][:200]
    return ""


def _heading_excerpt(location: str, hay: str) -> str:
    parts = [p.strip() for p in re.split(r"[／/]", location or "") if p.strip()]
    for head in reversed(parts):
        key = _HEAD_NO.sub("", head).strip() or head
        if len(key) < 2:
            continue
        idx = hay.find(head)
        if idx < 0:
            idx = hay.find(key)
        if idx < 0:
            continue
        window = hay[idx : idx + 900]
        for s in _sentences(window):
            if s == head or s == key or key in s[: len(key) + 2]:
                continue
            if len(s) >= 12:
                return s[:200]
    return ""


def snap_bid_excerpt(excerpt: str, hay: str, location: str = "") -> str:
    """把模型改写/拼接的摘句对齐回投标书原句；对齐不到才留空。"""
    excerpt = _strip_wrap(excerpt)
    hay = hay or ""
    if not hay:
        return ""
    parts = [p.strip() for p in excerpt.replace("；", ";").split(";") if p.strip()] if excerpt else []
    if len(parts) > 1:
        snapped = [_snap_one(p, hay) for p in parts]
        if all(snapped):
            return "；".join(snapped)
    if excerpt:
        hit = _snap_one(excerpt, hay)
        if hit:
            return hit
    if location:
        return _heading_excerpt(location, hay)
    return ""


def split_bid_and_tender(excerpt: str, tender_quote: str, rule: str = "") -> tuple[str, str]:
    """返回 (投标书摘句, 招标条款原文)。未响应类规则禁止把招标原文留在摘句栏。"""
    excerpt = (excerpt or "").strip()
    quote = (tender_quote or "").strip()
    dump = any(key in (rule or "") for key in _DUMP_RULES)
    if dump:
        body = excerpt if len(excerpt) > len(quote) else quote
        return "", body
    # 招标评分口吻误进左栏（如「1个证书2分…不提供不得分」）
    if excerpt and is_tender_score_voice(excerpt):
        if not quote or is_reject_clause(quote) or not is_tender_score_voice(quote):
            return "", excerpt
        return "", quote
    n_ex, n_qu = _norm(excerpt), _norm(quote)
    # 栏目名写在招标栏、条款全文误塞进投标摘句
    if excerpt and quote and len(quote) <= 24 and len(excerpt) >= 40 and n_qu and n_qu in n_ex:
        return "", excerpt
    if excerpt and n_qu:
        if n_ex == n_qu or n_ex in n_qu:
            return "", quote or excerpt
        if len(n_qu) >= 8 and n_qu in n_ex:
            return "", quote
    return excerpt, quote

