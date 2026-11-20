"""水利施组用的设计参数账、规范预绑定和已入库规范编号。

设计参数不落库：每次从解析清单里的图纸事实和工程量清单实时算，清单重解析后写作立刻跟着变。
没有出处的参数不进账，写作和校核都只认账里有的。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

MAX_ENTRIES = 240
MAX_LINES = 8

_GRADE = re.compile(r"(?<![A-Za-z])C(\d{2})(?!\d)")
_PERM = re.compile(r"(?<![A-Za-z])[WP](\d{1,2})(?!\d)")
_FROST = re.compile(r"(?<![A-Za-z])F(\d{2,3})(?!\d)")
_DOSAGE = re.compile(r"掺量[^。；;\n]{0,8}?(\d{1,2}(?:\.\d+)?)\s*%")
_COMPACT = re.compile(r"压实度[^。；;\n]{0,8}?(\d{2,3}(?:\.\d+)?)\s*%")

# 小节标题或意图命中左边，就取右边这些关键词去账里找。
_TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"混凝土|砼|浇筑|防洪墙|挡墙|涵|闸|底板|衬砌", ("混凝土", "抗渗", "抗冻", "强度", "钢筋")),
    (r"搅拌桩|软基|软土|地基处理|水泥土", ("搅拌桩", "水泥", "掺量", "桩径", "桩长")),
    (r"土方|填筑|堤身|压实|培厚|回填", ("压实度", "填筑", "土方", "回填", "含水率")),
    (r"止水|伸缩缝|分缝", ("止水", "伸缩缝", "分缝")),
    (r"护坡|护岸|砌石|块石|格宾", ("护坡", "护岸", "砌石", "块石", "格宾")),
    (r"清淤|疏浚", ("清淤", "淤泥")),
    (r"基坑|降水|支护", ("基坑", "降水", "支护")),
)


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _items(source, name: str) -> list[dict]:
    if isinstance(source, dict):
        rows = source.get(name)
    else:
        rows = getattr(source, name, None)
    return [r for r in (rows or []) if isinstance(r, dict)]


def design_ledger(checklist) -> list[dict]:
    """从图纸事实和清单项目特征生成参数账。每条 {topic, text, source, grades...}。"""
    out: list[dict] = []
    for fact in _items(checklist, "drawing_facts"):
        obj, field, value = _text(fact.get("object")), _text(fact.get("field")), _text(fact.get("value"))
        if not value or not (obj or field):
            continue
        unit = _text(fact.get("unit"))
        where = []
        if fact.get("drawingNo"):
            where.append(f"图 {_text(fact.get('drawingNo'))}")
        if fact.get("page"):
            where.append(f"第 {_text(fact.get('page'))} 页")
        source = "、".join(where) or "图纸"
        out.append(
            {
                "blob": f"{obj}{field}{value}",
                "text": f"{obj}{field} {value}{unit}（{source}）".replace("  ", " "),
                "source": source,
            }
        )
        if len(out) >= MAX_ENTRIES:
            return out
    for row in _items(checklist, "boq_rows"):
        name, feature = _text(row.get("name")), _text(row.get("feature"))
        if not name:
            continue
        has_param = bool(feature and (_GRADE.search(feature) or _PERM.search(feature) or _FROST.search(feature)
                                      or _DOSAGE.search(feature) or _COMPACT.search(feature) or "厚" in feature
                                      or "桩" in feature))
        if not has_param and not feature:
            continue
        qty = f"，工程量 {_text(row.get('qty'))}{_text(row.get('unit'))}" if row.get("qty") else ""
        code = _text(row.get("code"))
        source = f"清单 {code}" if code else "工程量清单"
        out.append(
            {
                "blob": f"{name}{feature}",
                "text": f"{name}：{feature[:100]}{qty}（{source}）",
                "source": source,
            }
        )
        if len(out) >= MAX_ENTRIES:
            break
    return out


def _topic_keys(title: str, idea: str) -> list[str]:
    blob = f"{title} {idea}"
    keys: list[str] = []
    for pattern, words in _TOPICS:
        if re.search(pattern, blob):
            keys.extend(words)
    return list(dict.fromkeys(keys))


def design_lines_for(ledger: list[dict] | None, title: str, idea: str = "", limit: int = MAX_LINES) -> list[str]:
    """按小节标题和意图分发参数账，命中词越多越靠前。"""
    if not ledger:
        return []
    keys = _topic_keys(title, idea)
    if not keys:
        return []
    scored: list[tuple[int, int, str]] = []
    for index, entry in enumerate(ledger):
        hits = sum(1 for key in keys if key in entry.get("blob", ""))
        if hits:
            scored.append((-hits, index, entry["text"]))
    scored.sort()
    return [text for _, _, text in scored[:limit]]


def design_params(ledger: list[dict] | None) -> dict[str, set[str]]:
    """把参数账里的等级和比例拆出来，给校核做一致性比对。"""
    params: dict[str, set[str]] = {"grade": set(), "perm": set(), "frost": set(), "dosage": set(), "compaction": set()}
    for entry in ledger or []:
        blob = entry.get("blob", "")
        params["grade"].update(f"C{n}" for n in _GRADE.findall(blob))
        params["perm"].update(f"W{n}" for n in _PERM.findall(blob))
        params["frost"].update(f"F{n}" for n in _FROST.findall(blob))
        params["dosage"].update(_DOSAGE.findall(blob))
        params["compaction"].update(_COMPACT.findall(blob))
    return params


def concrete_tuple_missing(text: str, params: dict[str, set[str]]) -> list[str]:
    """正文写了混凝土强度等级，但参数账里有抗渗或抗冻而正文没写，返回缺的项。"""
    if not _GRADE.search(text or ""):
        return []
    missing = []
    if params.get("perm") and not _PERM.search(text):
        missing.append("抗渗等级")
    if params.get("frost") and not _FROST.search(text):
        missing.append("抗冻等级")
    return missing


# ---------------------------------------------------------------------------
# 规范编号
# ---------------------------------------------------------------------------


def code_key(code: str) -> str:
    """比较用的标准号：去空格、统一连字符、忽略 /T。"""
    text = re.sub(r"\s+", "", code or "").upper().replace("—", "-").replace("–", "-")
    return text.replace("/T", "")


def known_standard_codes(db) -> set[str]:
    """平台规范目录和企业条文库里已入库的标准号，已规范成 code_key 形式。"""
    codes: set[str] = set()
    try:
        from ..db import platform_session
        from ..platform_models import StdCatalog

        pdb = platform_session()
        try:
            for (code,) in pdb.query(StdCatalog.code).all():
                if code:
                    codes.add(code_key(code))
        finally:
            pdb.close()
    except Exception:
        logger.exception("platform standard codes failed")
    try:
        from ..models import StandardClause

        for (code,) in db.query(StandardClause.code).distinct().all():
            if code:
                codes.add(code_key(code))
    except Exception:
        logger.exception("tenant standard codes failed")
    return codes


def attach_clause_refs(outline: list[dict], finder, *, pattern: str | None = None, limit: int = 3) -> int:
    """大纲定稿后，给每个工艺叶子预绑定真实条款。finder(title) 返回 [{code, clauseNo, excerpt}]。
    返回绑定了条款的节点数。"""
    from .engineering_writer import KIND_GROUP, section_kind

    rule = re.compile(pattern or r"施工方法|施工工艺|清淤|护坡|护岸|挡墙|堰|导流|防汛道路|填筑|搅拌桩|防洪墙|衬砌|基坑|围堰|止水")
    parents = {n.get("parentId") for n in outline if n.get("parentId")}
    bound = 0
    for node in outline:
        if node.get("id") in parents or section_kind(node) == KIND_GROUP:
            continue
        title = str(node.get("title") or "")
        if not rule.search(title):
            continue
        try:
            rows = finder(title) or []
        except Exception:
            logger.exception("prebind clauses failed for %s", title)
            rows = []
        refs = [
            {
                "code": str(r.get("code") or ""),
                "clauseNo": str(r.get("clauseNo") or r.get("clause_no") or ""),
                "excerpt": str(r.get("excerpt") or r.get("text") or "")[:220],
            }
            for r in rows[:limit]
            if r.get("code")
        ]
        if refs:
            node["clauseRefs"] = refs
            bound += 1
    return bound
