"""业绩口径排除项。

招标常写「类似业绩不含水环境治理、农田整治、高标准农田等项目」。这类项目不能当类似业绩。
本模块只做两件事：从招标文本里抽出排除的项目类型，以及判断一条业绩文本是否落在排除类型里。
招标解析、写标选材和预审三处共用，口径一致。
"""

from __future__ import annotations

import re

_TRIGGER = re.compile(r"排除|不含|不包括|不包含|除外|不予认可|不认可|不得为|不接受|不计入|不属于")
_SPLIT = re.compile(r"[、，,和及或与]")
_TYPE_WORD = re.compile(
    r"治理|整治|工程|项目|建设|改造|修复|疏浚|清淤|护岸|设施|农田|水环境|绿化|景观|房建|房屋|市政|公路|装修|安装|维修|养护|水利|堤|渠|泵站|水库|桥|路|管网|生态"
)
_NOISE = re.compile(r"税|金额|价格|报价|费用|\d")
_TAIL_STRIP = re.compile(r"(?:等(?:类型|类别|类)?(?:的)?(?:项目|工程)?|类(?:项目|工程)?|的?项目|的?工程|业绩)+$")
_HEAD_STRIP = re.compile(r"^(?:为|是|以下|如下|下列|的|：|:|\s)+")


def _clean_term(raw: str) -> str:
    term = _HEAD_STRIP.sub("", raw.strip())
    term = _TAIL_STRIP.sub("", term).strip("（()）：: 　")
    return term


def exclusions_from_text(text: str, limit: int = 10) -> list[str]:
    """在含「业绩」的片段里找排除用语，拆出被排除的项目类型。找不到返回空列表。"""
    body = text or ""
    found: list[str] = []
    for m in re.finditer(r"业绩|类似项目|类似工程", body):
        segment = body[m.start() : m.start() + 260]
        trig = _TRIGGER.search(segment)
        if not trig:
            continue
        tail = segment[trig.end() :]
        if tail[:1] == "税":
            continue
        tail = re.split(r"[。；;\n）)]", tail, maxsplit=1)[0][:80]
        for part in _SPLIT.split(tail):
            term = _clean_term(part)
            if not (3 <= len(term) <= 14):
                continue
            if _NOISE.search(term) or not _TYPE_WORD.search(term):
                continue
            if term not in found:
                found.append(term)
            if len(found) >= limit:
                return found
    return found


def _hit(text: str, term: str) -> bool:
    if term in text:
        return True
    if len(term) >= 4:
        # 「水环境治理」要能命中「水环境综合治理」：首两字和末两字在短距离内同时出现
        return bool(re.search(re.escape(term[:2]) + r".{0,6}" + re.escape(term[-2:]), text))
    return False


def hits(asset_text: str, terms: list[str] | None) -> list[str]:
    """返回这段业绩文本命中的排除类型。"""
    text = asset_text or ""
    return [t for t in (terms or []) if t and _hit(text, t)]


def merge_terms(*groups) -> list[str]:
    out: list[str] = []
    for group in groups:
        for item in group or []:
            term = str(item or "").strip()[:20]
            if term and term not in out:
                out.append(term)
    return out[:10]
