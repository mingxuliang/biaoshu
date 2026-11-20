"""规范对标：技术标叶子规则 → 按专业检索少量条文 → 对照必须写到的内容和条文判断标书。

没有叶子规则时提示重新解析，不用清单行顶上。
规范库未命中时，仍按招标书写明的技术要求判断已响应、应有未写、参数不一致。
做法冲突必须引用本次检索到的条文。编造的标准号丢弃。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import as_completed

from ..ctx_executor import ContextThreadPoolExecutor as ThreadPoolExecutor

from sqlalchemy.orm import Session

from ..models import KnowledgeDocument, KnowledgeSlice, StandardClause
from .e_tender_score import expand_score_items
from .llm import LlmError, chat_complete, get_default_model_id
from .parse_schema import is_engineering_category
from .qty_boq import rows_from_dimensions
from .standard_ingest import detect_specialty

logger = logging.getLogger(__name__)

MAX_POINTS = 108
MAX_CLAUSES = 3
KNOWLEDGE_LIMIT = 3
KNOWLEDGE_EXCERPT = 400
BATCH = 8  # 每次判断塞入的查核点数：标书片段本身才是主要的 token 成本，多塞几个点省的是往返次数
JUDGE_WORKERS = 4  # 跟 e3/e4 并行度一致；chat_complete 每次调用自建连接，可以安全并发
_BANDS = (100, 90, 80, 70, 60)
_BAND_LABEL = {100: "优", 90: "良", 80: "中等", 70: "一般", 60: "差", 0: "未提供"}
_OFFTOPIC = ("学员", "积分", "激励中心", "学分", "登录密码", "软件平台")
DIRECT_BID_CHARS = 60000
CHUNK_CHARS = 12000
CHUNK_OVERLAP = 600
VERDICTS = {"参数不一致", "应有未写", "做法冲突", "已响应"}
CHECK_RESULTS = {"已对上", "部分写到", "未见", "与规范不符"}
NO_STANDARD_NOTE = "知识库未命中对应条文，本节不判规范冲突"
MISS = "规范库未命中"
REPARSE_NOTE = "请重新解析招标书"
_SKIP_SCORE_IDS = {"qty-drawing", "qty-boq"}
_STOP = {"的", "和", "及", "应", "必须", "进行", "施工", "工程", "要求", "方案", "项目", "技术", "相关"}

_PARAM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("混凝土强度", re.compile(r"C\d{2}")),
    ("抗渗等级", re.compile(r"抗渗(?:等级)?\s*[Pp]?\d+")),
    ("抗震", re.compile(r"抗震(?:设防)?(?:烈度|等级)?[^\n，。；]{0,16}")),
    ("压实度", re.compile(r"压实度\s*[0-9]+(?:\.[0-9]+)?%?")),
)
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}|\d+(?:\.\d+)?")

_JUDGE_SYSTEM = """你是工程标预审员。调用方给出的是投标书全文，你必须通读全文后再下结论，不能只看开头的编制依据或编制原则。
知识库摘录是检索到的工程知识，用来理解做法；不得编造其中没有的标准号，不得另算总分。
结论只能是：参数不一致、应有未写、做法冲突、已响应。
参数不一致：全文里的强度、尺寸、数量和已挂参数、知识库摘录或条文矛盾。
应有未写：通读全文后，必须写到的施工内容仍然没有出现。后面章节已经写了相关措施、方案或参数，就不要判应有未写。允许投标人换一种说法。
评审计分规则里的权重、去掉最高最低分、评委人数、计算公式，不是投标人要写进施工组织设计的内容，全文没抄这些计分办法不能判应有未写。
做法冲突：全文写了与给出规范条文相反的做法。没有条文时不要下这个结论。
已响应：全文已经覆盖必须写到的施工内容，或材料不足以判断。
规则若带 checkType：必须有看方案是否写到；参数一致看标书是否低于给出的设计值；量与资源一致看人数、工期、机械和工程量是否对得上；建议不要判应有未写。
按本条招标文件的赋分档打分，不要只写已响应。五维用来说明为什么是这一档：完整性看事项有没有写全，针对性看是否针对本工程，合规性看是否符合给出的规范和知识库，可落地性看措施能否施工，规范性看依据和数据是否具体。
score 只能落在给出的赋分档。档次为 100/90/80/70/60 时，只能给其中一档；关键内容没写到时不得给 100 或 90；全文没有这项时给 0。
本条写明不单独赋分时，score 置空，grade 只写「符合」或「不符合」。
先用本条招标原文写清 scoreRule：权重、优100/良90/中等80/一般70/差60 各档要写到什么程度。去掉最高最低分、评委人数这些计分过程不要要求投标人照抄。
checks 最多 8 条，逐项对标。每条 item 是要核对的事项，bid 必须是投标书原句，result 只能是：已对上、部分写到、未见、与规范不符。
excerpts 列出这些原句，必须逐字来自投标书全文，不要写招标书或知识库的句子。
strengths 写好的地方，并点明对应哪条原文。revisions 写需要修改的地方，指出缺了哪一项、改哪一节。
noncompliance 只写与给出的知识库条文或规范条文相反的做法，并照抄标准号和条号。没有检索到条文时，写「知识库未命中对应条文，本节不判规范冲突」，不要编造标准号。
strategy 写针对本工程的高分写法。这是预审模拟分，不是评标委员会最终得分。
返回 JSON 对象 {"items":[{"id","verdict","score","grade","scoreRule","checks","excerpts","strengths","revisions","noncompliance","strategy","reason","clauseKey"}]}。
checks 项为 {"item","bid","result"}。clauseKey 必须照抄给出的「标准号 条号」。做法冲突和与规范不符必须有 clauseKey。"""

# 软件服务类标书版：与上面的工程类系统提示词结构一一对应，只是把施工/工程量语境
# 换成系统功能/接口/部署/服务条款语境，不出现"施工""工程量"等措辞。
_JUDGE_SYSTEM_SW = """你是软件服务类标书预审员。调用方给出的是投标书全文，你必须通读全文后再下结论，不能只看开头的编制依据或编制原则。
知识库摘录是检索到的技术/行业知识，用来理解做法；不得编造其中没有的标准号，不得另算总分。
结论只能是：参数不一致、应有未写、做法冲突、已响应。
参数不一致：全文里的技术指标、数量、规格和已挂参数、知识库摘录或条文矛盾。
应有未写：通读全文后，必须写到的系统功能、接口、部署或服务条款仍然没有出现。后面章节已经写了相关方案或参数，就不要判应有未写。允许投标人换一种说法。
评审计分规则里的权重、去掉最高最低分、评委人数、计算公式，不是投标人要写进技术方案的内容，全文没抄这些计分办法不能判应有未写。
做法冲突：全文写了与给出规范条文相反的做法。没有条文时不要下这个结论。
已响应：全文已经覆盖必须写到的系统功能/接口/部署/服务内容，或材料不足以判断。
按本条招标文件的赋分档打分，不要只写已响应。五维用来说明为什么是这一档：完整性看事项有没有写全，针对性看是否针对本项目业务场景，合规性看是否符合给出的规范和知识库，可落地性看方案能否落地实施，规范性看依据和数据是否具体。
score 只能落在给出的赋分档。档次为 100/90/80/70/60 时，只能给其中一档；关键内容没写到时不得给 100 或 90；全文没有这项时给 0。
本条写明不单独赋分时，score 置空，grade 只写「符合」或「不符合」。
先用本条招标原文写清 scoreRule：权重、优100/良90/中等80/一般70/差60 各档要写到什么程度。去掉最高最低分、评委人数这些计分过程不要要求投标人照抄。
checks 最多 8 条，逐项对标。每条 item 是要核对的事项，bid 必须是投标书原句，result 只能是：已对上、部分写到、未见、与规范不符。
excerpts 列出这些原句，必须逐字来自投标书全文，不要写招标书或知识库的句子。
strengths 写好的地方，并点明对应哪条原文。revisions 写需要修改的地方，指出缺了哪一项、改哪一节。
noncompliance 只写与给出的知识库条文或规范条文相反的做法，并照抄标准号和条号。没有检索到条文时，写「知识库未命中对应条文，本节不判规范冲突」，不要编造标准号。
strategy 写针对本项目的高分写法。这是预审模拟分，不是评标委员会最终得分。
返回 JSON 对象 {"items":[{"id","verdict","score","grade","scoreRule","checks","excerpts","strengths","revisions","noncompliance","strategy","reason","clauseKey"}]}。
checks 项为 {"item","bid","result"}。clauseKey 必须照抄给出的「标准号 条号」。做法冲突和与规范不符必须有 clauseKey。"""


def _judge_system_for(is_engineering: bool) -> str:
    return _JUDGE_SYSTEM if is_engineering else _JUDGE_SYSTEM_SW


def _norm(text: str) -> str:
    return _WS.sub("", text or "")


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(text or ""):
        pieces = [token]
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            pieces = [token[i : i + 2] for i in range(len(token) - 1)]
        for piece in pieces:
            if len(piece) < 2 or piece in _STOP or piece in seen:
                continue
            seen.add(piece)
            out.append(piece)
    return out


def _walk_text(node) -> str:
    parts: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"content", "original", "text", "label", "摘要", "原文"} and isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (dict, list)):
                parts.append(_walk_text(value))
    elif isinstance(node, list):
        for item in node:
            parts.append(_walk_text(item))
    return "\n".join(part for part in parts if part)


def project_specialty(dimensions: list | None) -> str:
    return detect_specialty(_walk_text(dimensions))


def drawing_blob(dimensions: list | None) -> str:
    chunks: list[str] = []
    for dim in dimensions or []:
        if not isinstance(dim, dict):
            continue
        for item in dim.get("items") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "")
            if item.get("id") == "qty-drawing" or "图纸" in label or "设计说明" in label:
                chunks.append(_walk_text(item))
    return "\n".join(chunks)


def _point(source: str, name: str, detail: str) -> dict:
    title = re.sub(r"\s+", " ", (name or "").strip())[:40]
    body = re.sub(r"\s+", " ", (detail or "").strip())[:240]
    return {
        "id": "",
        "source": source,
        "name": title or source,
        "detail": body,
        "verdict": "",
        "excerpt": "",
        "reason": "",
        "clauses": [],
    }


def drawing_points(dimensions: list | None) -> list[dict]:
    blob = drawing_blob(dimensions)
    points: list[dict] = []
    seen: set[str] = set()
    for label, pattern in _PARAM_RES:
        for match in pattern.finditer(blob):
            value = re.sub(r"\s+", "", match.group())
            key = f"{label}:{value}"
            if key in seen:
                continue
            seen.add(key)
            start = max(0, match.start() - 24)
            end = min(len(blob), match.end() + 24)
            title = value if value.startswith(label) else f"{label} {value}"
            points.append(_point("图纸", title, blob[start:end]))
    return points


def boq_points(dimensions: list | None) -> list[dict]:
    points: list[dict] = []
    for row in rows_from_dimensions(dimensions):
        name = (row.name or "").strip()
        if len(name) < 2 or name in {"项目名称", "合计", "暂列金额"}:
            continue
        detail_bits = [bit for bit in (row.remark, f"{row.qty:g}{row.unit}" if row.qty is not None else "") if bit]
        points.append(_point("清单", name, " ".join(detail_bits)))
    featured = [item for item in points if item["detail"]]
    plain = [item for item in points if not item["detail"]]
    return featured + plain


def tender_booklet(item: dict) -> str:
    """招标解析槽优先。技术标只留技术，商务、资信、报价归到商务标。"""
    from .bid_kind import booklet_of_source

    slot = booklet_of_source(
        str(item.get("sourceItemId") or ""),
        f"{item.get('group') or ''}{item.get('name') or ''}",
    )
    if slot == "tech":
        return "技术标"
    if slot in {"business", "price"}:
        return "商务标"
    blob = f"{item.get('group') or ''}{item.get('name') or ''}{item.get('rule') or ''}"
    if any(word in blob for word in ("报价", "价格", "商务", "资信", "业绩", "信用", "资格", "投标函")):
        return "商务标"
    return "技术标"


def score_points(score_rules: list | None, tree: list | None = None) -> list[dict]:
    """只用招标解析已经抽出的 scoreRules，不再通读招标书原文。tree 不参与，避免把另一册规则带回来。"""
    del tree
    points: list[dict] = []
    for item in expand_score_items(score_rules, None):
        if item.get("formula"):
            continue
        if str(item.get("sourceItemId") or "") in _SKIP_SCORE_IDS:
            continue
        name = str(item.get("name") or "").strip()
        if len(name) < 2:
            continue
        point = _point("招标书", name, str(item.get("rule") or ""))
        point["booklet"] = tender_booklet(item)
        points.append(point)
    return points


def _cap_source(items: list[dict], start: int) -> list[dict]:
    """每一类单独计数，清单再多也不能挤掉招标书和图纸。"""
    picked: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = _norm(item["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        row = dict(item)
        row["id"] = f"sp-{start + len(picked) + 1}"
        picked.append(row)
        if len(picked) >= MAX_POINTS:
            break
    return picked


def _cap_project_tech(items: list[dict]) -> list[dict]:
    """规则池条数少，但排在大量招标叶子后面时会被 108 条上限截掉。先留规则池。"""
    pinned = [item for item in items if item.get("source") == "规则池"]
    rest = [item for item in items if item.get("source") != "规则池"]
    return _cap_source(pinned + rest, 0)


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def leaf_points(tech_rules: list | None) -> list[dict]:
    """技术标只收解析时抽出的叶子，不把评分表标题或清单行当成规则。"""
    points: list[dict] = []
    for rule in tech_rules or []:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("booklet") or "技术标") != "技术标":
            continue
        name = str(rule.get("factor") or rule.get("name") or "").strip()
        must = str(rule.get("mustWrite") or rule.get("detail") or "").strip()
        if len(name) < 2:
            continue
        point = _point("招标书", name, must)
        point["booklet"] = "技术标"
        point["mustWrite"] = must[:400]
        point["parameters"] = str(rule.get("parameters") or "").strip()[:400]
        point["standards"] = _as_list(rule.get("standards"))[:8]
        point["chapter"] = str(rule.get("chapter") or "").strip()[:40]
        point["axis"] = str(rule.get("axis") or "").strip()[:8]
        point["ruleScore"] = str(rule.get("score") or "").strip()[:80]
        point["grades"] = str(rule.get("grades") or "").strip()[:160]
        points.append(point)
    return points


def drawing_review_points(drawing_rules: list | None) -> list[dict]:
    """施工图规则单独成查核点，清单行不在这里展开。"""
    points: list[dict] = []
    for rule in drawing_rules or []:
        if not isinstance(rule, dict):
            continue
        title = str(rule.get("title") or "").strip()
        notes = str(rule.get("notes") or "").strip()
        if len(title) < 2:
            continue
        point = _point("图纸", title, notes)
        point["booklet"] = "技术标"
        point["mustWrite"] = notes[:800]
        point["parameters"] = str(rule.get("parameters") or "").strip()[:400]
        point["standards"] = _as_list(rule.get("standards"))[:8]
        point["chapter"] = str(rule.get("chapter") or title).strip()[:40]
        point["axis"] = str(rule.get("axis") or "").strip()[:8]
        point["drawingNo"] = str(rule.get("drawingNo") or "").strip()[:40]
        points.append(point)
    return points


def project_rule_points(project_rules: list | None) -> list[dict]:
    """本项目规则清单优先于把图纸说明原文当成必须照抄。"""
    points: list[dict] = []
    for rule in project_rules or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        title = str(rule.get("title") or "").strip()
        requirement = str(rule.get("requirement") or "").strip()
        if len(title) < 2 or len(requirement) < 4:
            continue
        point = _point(str(rule.get("source") or "规则"), title, requirement)
        point["booklet"] = "商务标" if rule.get("source") in {"资格", "商务"} or str(rule.get("evidence") or "") in {"资格", "商务"} else "技术标"
        if str(rule.get("evidence") or "") in {"资格", "商务"}:
            point["booklet"] = "商务标"
        point["mustWrite"] = requirement[:400]
        point["checkType"] = str(rule.get("checkType") or "必须有")
        point["parameters"] = str(rule.get("parameters") or "")[:200]
        point["evidence"] = str(rule.get("evidence") or "")[:200]
        point["basis"] = str(rule.get("basis") or "")[:120]
        point["severityHint"] = str(rule.get("severity") or "")[:8]
        points.append(point)
    return points


def build_points(
    score_rules: list | None,
    dimensions: list | None,
    scope: str = "full",
    tech_rules: list | None = None,
    drawing_rules: list | None = None,
    project_rules: list | None = None,
) -> list[dict]:
    """有本项目规则清单时用它代替招标叶子加图纸说明。商务标评分点仍保留。"""
    del dimensions
    business = [item for item in score_points(score_rules) if item.get("booklet") == "商务标"]
    pooled = project_rule_points(project_rules)
    if scope == "business":
        extra = [item for item in pooled if item.get("booklet") == "商务标"]
        return _cap_source(extra + business, 0)
    if project_rules:
        tech = [item for item in pooled if item.get("booklet") == "技术标"]
        picked = _cap_project_tech(tech)
    else:
        picked = _cap_source(leaf_points(tech_rules), 0)
        picked.extend(_cap_source(drawing_review_points(drawing_rules), len(picked)))
    if scope == "tech":
        return picked
    picked.extend(_cap_source(business, len(picked)))
    return picked


def _clause_key(code: str, clause_no: str) -> str:
    return f"{(code or '').strip()} {(clause_no or '').strip()}".strip()


def _topics_of(row) -> list[str]:
    raw = row.get("topics") if isinstance(row, dict) else getattr(row, "topics_json", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def search_terms(tokens: list[str], limit: int = 4) -> list[str]:
    """多词检索用的词，按长度取前几个，不再只留最长的一个。"""
    ranked = sorted({token for token in tokens if len(token) >= 2}, key=len, reverse=True)
    return ranked[:limit]


def _as_hit(row) -> dict:
    if isinstance(row, dict):
        code = str(row.get("code") or "")
        clause_no = str(row.get("clause_no") or row.get("clauseNo") or "")
        text = str(row.get("text") or "")
        specialty = str(row.get("specialty") or "")
    else:
        code = row.code or ""
        clause_no = row.clause_no or ""
        text = row.text or ""
        specialty = row.specialty or ""
    return {
        "code": code,
        "clauseNo": clause_no,
        "specialty": specialty,
        "excerpt": text[:280],
        "key": _clause_key(code, clause_no),
        "topics": _topics_of(row),
    }


def select_clauses(rows: list, query: str, specialty: str, limit: int = MAX_CLAUSES) -> list[dict]:
    """同专业加通用。先按标准号，再按词重合。没有命中则不返回，避免拿无关条文充数。"""
    from .standard_ingest import parse_standard_code

    pool = list(rows or [])
    if specialty and specialty != "通用":
        pool = [
            row
            for row in pool
            if (row.get("specialty") if isinstance(row, dict) else row.specialty) in {specialty, "通用"}
        ]
    tokens = _tokens(query)
    wanted = set()
    for match in re.findall(r"(?:GB/T|GB|SL/T|SL|JGJ|JTG|CJJ)\s*\d+(?:\.\d+)?(?:-\d{4})?", query or "", flags=re.I):
        code = parse_standard_code(match + "-2000") if "-" not in match else parse_standard_code(match)
        # parse_standard_code expects a year; keep the raw compact form when the query already has one
        compact = re.sub(r"\s+", "", match).upper().replace("—", "-")
        wanted.add(compact)
        if code:
            wanted.add(code.upper())
    if not tokens and not wanted:
        return []
    ranked: list[tuple[int, dict]] = []
    for row in pool:
        hit = _as_hit(row)
        blob = f"{hit['code']} {hit['clauseNo']} {hit['excerpt']}"
        score = sum(1 for token in tokens if token in blob)
        for topic in hit.get("topics") or []:
            if topic and topic in (query or ""):
                score += 30
        code = re.sub(r"\s+", "", str(hit.get("code") or "")).upper()
        if code and code in wanted:
            score += 100
        if score <= 0:
            continue
        ranked.append((score, hit))
    ranked.sort(key=lambda item: item[0], reverse=True)
    out: list[dict] = []
    seen: set[str] = set()
    for _score, hit in ranked:
        if hit["key"] in seen:
            continue
        seen.add(hit["key"])
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _rows_for_terms(query, column, tokens: list[str], per_term: int = 80) -> list:
    found = []
    seen: set[str] = set()
    for term in search_terms(tokens):
        for row in query.filter(column.contains(term)).limit(per_term).all():
            ident = str(getattr(row, "id", None) or id(row))
            if ident in seen:
                continue
            seen.add(ident)
            found.append(row)
    return found


def search_clauses(db: Session, query: str, specialty: str, limit: int = MAX_CLAUSES) -> list[dict]:
    """先按标准号取平台库和企业库，再用多个词排序，不再只拿最长的一个词看前 80 条。"""
    tokens = _tokens(query)
    codes = []
    for match in re.findall(r"(?:GB/T|GB|SL/T|SL|JGJ|JTG|CJJ)\s*\d+(?:\.\d+)?(?:-\d{4})?", query or "", flags=re.I):
        codes.append(re.sub(r"\s+", "", match).upper().replace("—", "-"))
    if not tokens and not codes:
        return []
    rows: list = []
    try:
        from ..db import platform_session
        from ..platform_models import StdClause

        pdb = platform_session()
        try:
            q = pdb.query(StdClause)
            if specialty and specialty != "通用":
                q = q.filter(StdClause.specialty.in_([specialty, "通用"]))
            if codes:
                rows.extend(q.filter(StdClause.code.in_(codes)).limit(200).all())
            else:
                rows.extend(_rows_for_terms(q, StdClause.text, tokens))
        finally:
            pdb.close()
    except Exception:
        logger.exception("platform clause search failed")
    try:
        q = db.query(StandardClause)
        if specialty and specialty != "通用":
            q = q.filter(StandardClause.specialty.in_([specialty, "通用"]))
        if codes:
            rows.extend(q.filter(StandardClause.code.in_(codes)).limit(200).all())
        else:
            rows.extend(_rows_for_terms(q, StandardClause.text, tokens))
    except Exception:
        logger.exception("tenant clause search failed")
    return select_clauses(rows, query, specialty, limit)


def bid_chunks(text: str) -> list[str]:
    """全文一次装得下就整篇给模型。更长时按段覆盖每一个字，段与段有重叠。"""
    body = text or ""
    if not body:
        return [""]
    if len(body) <= DIRECT_BID_CHARS:
        return [body]
    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + CHUNK_CHARS)
        chunks.append(body[start:end])
        if end >= len(body):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def search_knowledge(db: Session, query: str, limit: int = KNOWLEDGE_LIMIT) -> list[dict]:
    """从知识库切片检索少量工程知识，不把整库塞进模型。"""
    text = (query or "").strip()
    if not text or db is None:
        return []
    try:
        rows = db.query(KnowledgeSlice).order_by(KnowledgeSlice.seq.asc()).limit(800).all()
    except Exception:
        logger.exception("knowledge slice load failed")
        return []
    rows = [row for row in rows if isinstance(getattr(row, "text", None), str) and row.text.strip()]
    if not rows:
        return []
    try:
        from rank_bm25 import BM25Okapi

        from .knowledge_retrieval import _tokenize

        corpus = [_tokenize(f"{row.heading or ''} {(row.text or '')[:1500]}") for row in rows]
        scores = BM25Okapi(corpus).get_scores(_tokenize(text[:180]))
    except Exception:
        logger.exception("knowledge rag failed")
        return []
    ranked = sorted(zip(rows, scores), key=lambda item: float(item[1]), reverse=True)
    picked = []
    for row, score in ranked:
        if score <= 0:
            continue
        picked.append(row)
        if len(picked) >= limit:
            break
    if not picked:
        return []
    titles: dict[str, str] = {}
    try:
        doc_ids = [row.document_id for row in picked if row.document_id]
        docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all() if doc_ids else []
        titles = {doc.id: doc.title for doc in docs}
    except Exception:
        logger.exception("knowledge title load failed")
    return [
        {
            "title": titles.get(row.document_id) or "",
            "heading": str(row.heading or "")[:40],
            "excerpt": (row.text or "").strip()[:KNOWLEDGE_EXCERPT],
        }
        for row in picked
    ]


def merge_chunk_judgments(items: list[dict]) -> dict:
    """任一段全文写到了，就不要被另一段的「应有未写」盖掉。"""
    usable = [item for item in items if "未能完成全文判断" not in str(item.get("reason") or "")]
    pool = usable or list(items or [])
    valid = [item for item in pool if str(item.get("verdict") or "") in VERDICTS]
    if not valid:
        return {
            "id": str((pool[0].get("id") if pool else "") or ""),
            "verdict": "已响应",
            "reason": "本次未能完成全文判断",
            "excerpt": "",
        }
    rank = {"做法冲突": 3, "参数不一致": 2, "已响应": 1, "应有未写": 0}
    valid.sort(key=lambda item: rank.get(str(item.get("verdict") or ""), 0), reverse=True)
    best = dict(valid[0])
    checks: list = []
    quotes: list = []
    for item in valid:
        raw_checks = item.get("checks")
        if isinstance(raw_checks, list):
            checks.extend(raw_checks)
        raw_quotes = item.get("excerpts")
        if isinstance(raw_quotes, list):
            quotes.extend(raw_quotes)
        elif item.get("excerpt"):
            quotes.append(item.get("excerpt"))
        for field in ("scoreRule", "strengths", "revisions", "noncompliance", "strategy", "suggestion", "problems"):
            if not best.get(field) and item.get(field):
                best[field] = item[field]
    if checks:
        best["checks"] = checks[:8]
    if quotes:
        best["excerpts"] = quotes[:8]
    return best


def relevant_knowledge(hits: list | None, name: str) -> list[dict]:
    """丢掉和本条工程事项对不上的知识片段，避免评分办法、软件说明被当成依据。"""
    tokens = [
        token
        for token in _tokens(name)
        if token not in {"保障", "体系", "措施", "管理", "要求", "编制", "评审", "标准", "评分", "分值", "权重", "技术", "文件"}
    ][:8]
    kept: list[dict] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        blob = f"{hit.get('title') or ''}{hit.get('heading') or ''}{hit.get('excerpt') or ''}"
        if any(word in blob for word in _OFFTOPIC):
            continue
        if tokens and not any(token in blob for token in tokens):
            continue
        kept.append(hit)
        if len(kept) >= KNOWLEDGE_LIMIT:
            break
    return kept


def _as_text(value) -> str:
    if isinstance(value, list):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def expert_score(point: dict, judged: dict) -> dict:
    """把模型分数收进招标文件的五档。不单独赋分的条目不编一个分数。"""
    grades = str(point.get("grades") or "")
    rule_score = str(point.get("ruleScore") or "")
    separate = "不单独赋分" in rule_score or "不单独赋分" in grades
    problems = _as_text(judged.get("problems"))[:400]
    suggestion = _as_text(judged.get("suggestion"))[:400]
    strategy = _as_text(judged.get("strategy"))[:400]
    grade = str(judged.get("grade") or "").strip()[:16]
    weight_match = re.search(r"权重\s*(\d+(?:\.\d+)?)\s*%", rule_score)
    weight = f"{weight_match.group(1)}%" if weight_match else ""
    if separate:
        if grade not in {"符合", "不符合"}:
            grade = "不符合" if str(judged.get("verdict") or "") == "应有未写" else "符合"
        return {
            "score": None,
            "maxScore": None,
            "grade": grade,
            "weight": weight,
            "weightedScore": None,
            "problems": problems,
            "suggestion": suggestion,
            "strategy": strategy,
        }
    bands = [int(num) for num in re.findall(r"\d+", grades) if int(num) in _BANDS]
    if not bands:
        bands = list(_BANDS)
    raw = judged.get("score")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        number = None
    if number is None:
        score = None
    elif number <= 0:
        score = 0
    else:
        score = min(bands, key=lambda band: (abs(band - number), band))
    label = _BAND_LABEL.get(score, grade)
    weighted = round(score * float(weight_match.group(1)) / 100, 1) if score is not None and weight_match else None
    return {
        "score": score,
        "maxScore": max(bands) if bands else None,
        "grade": label,
        "weight": weight,
        "weightedScore": weighted,
        "problems": problems,
        "suggestion": suggestion,
        "strategy": strategy,
    }


def review_detail(point: dict, judged: dict, bid: str) -> dict:
    """对标项里的原句必须能在投标书中找到。没有检索到条文时，不判规范冲突。"""
    allowed = {
        str(clause.get("key") or "")
        for clause in (point.get("clauses") or [])
        if isinstance(clause, dict) and clause.get("key")
    }
    has_library = bool(allowed or point.get("knowledge"))
    clause_key = str(judged.get("clauseKey") or judged.get("clause_key") or "").strip()
    cited = clause_key in allowed

    raw_quotes = judged.get("excerpts")
    if not isinstance(raw_quotes, list):
        raw_quotes = [judged.get("excerpt")] if judged.get("excerpt") else []
    excerpts: list[str] = []
    for raw in raw_quotes:
        quote = _excerpt_in_bid(str(raw or "")[:300], bid)
        if quote and quote not in excerpts:
            excerpts.append(quote)
        if len(excerpts) >= 8:
            break

    checks: list[dict] = []
    for raw in (judged.get("checks") or [])[:8]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("item") or "").strip()[:80]
        if len(name) < 2:
            continue
        quote = _excerpt_in_bid(str(raw.get("bid") or "")[:300], bid)
        result = str(raw.get("result") or "").strip()
        if result not in CHECK_RESULTS:
            result = "已对上" if quote else "未见"
        if result == "与规范不符" and not cited:
            result = "部分写到" if quote else "未见"
        if result != "未见" and not quote:
            result = "未见"
        checks.append({"item": name, "bid": quote, "result": result})
        if quote and quote not in excerpts and len(excerpts) < 8:
            excerpts.append(quote)

    noncompliance = _as_text(judged.get("noncompliance"))[:400]
    if not has_library:
        noncompliance = NO_STANDARD_NOTE
    elif not cited or not any(row["result"] == "与规范不符" for row in checks):
        noncompliance = ""
    return {
        "scoreRule": _as_text(judged.get("scoreRule"))[:400],
        "checks": checks,
        "excerpts": excerpts,
        "excerpt": excerpts[0] if excerpts else "",
        "strengths": _as_text(judged.get("strengths"))[:400],
        "revisions": _as_text(judged.get("revisions"))[:400],
        "noncompliance": noncompliance,
    }


def _window(bid: str, paragraphs: list[dict] | None, name: str, detail: str, chapter: str = "") -> str:
    keys = _tokens(f"{chapter} {name} {detail}")[:6]
    chapter_hits: list[str] = []
    hits: list[str] = []
    for para in paragraphs or []:
        text = str(para.get("text") or "").strip()
        if not text:
            continue
        if chapter and chapter in text:
            chapter_hits.append(text)
        elif keys and any(key in text for key in keys):
            hits.append(text)
        if len(chapter_hits) >= 3:
            break
    chosen = chapter_hits or hits
    blob = "\n".join(chosen[:3]).strip()
    if blob:
        return blob[:1200]
    return (bid or "")[:800]


def _excerpt_in_bid(excerpt: str, bid: str) -> str:
    excerpt = (excerpt or "").strip()
    if not excerpt:
        return ""
    if excerpt in (bid or ""):
        return excerpt
    if _norm(excerpt) and _norm(excerpt) in _norm(bid):
        return excerpt
    return ""


def apply_judgments(packed: list[dict], raw_items: list, bid: str) -> tuple[list[dict], list[dict]]:
    """丢掉不在本次检索结果里的标准号。没有标书原句的问题不进入问题清单。"""
    by_id = {str(item.get("id") or ""): item for item in raw_items if isinstance(item, dict)}
    points: list[dict] = []
    findings: list[dict] = []
    for point in packed:
        item = dict(point)
        judged = by_id.get(item["id"]) or {}
        allowed = {clause["key"] for clause in item.get("clauses") or [] if clause.get("key")}
        clause_key = str(judged.get("clauseKey") or judged.get("clause_key") or "").strip()
        verdict = str(judged.get("verdict") or "").strip()
        if verdict not in VERDICTS:
            verdict = ""
        has_rule = bool(item.get("mustWrite") or item.get("parameters"))
        needs_clause = verdict == "做法冲突" or (verdict in {"参数不一致", "应有未写"} and not has_rule)
        if verdict and verdict != "已响应" and needs_clause and clause_key not in allowed:
            item["verdict"] = ""
            item["reason"] = "条文编号不在检索结果中，已丢弃"
            item["excerpt"] = ""
            points.append(item)
            continue
        excerpt = _excerpt_in_bid(str(judged.get("excerpt") or ""), bid)
        item["verdict"] = verdict or "已响应"
        reason = str(judged.get("reason") or "").strip()[:300]
        axis = str(item.get("axis") or "").strip()
        if axis and axis not in reason:
            reason = f"{axis}：{reason}" if reason else axis
        item["reason"] = reason[:300]
        item.update(expert_score(item, judged))
        item.update(review_detail(item, judged, bid))
        if not item.get("excerpt"):
            item["excerpt"] = excerpt
        excerpt = item.get("excerpt") or excerpt
        if not item.get("suggestion"):
            item["suggestion"] = item.get("revisions") or ""
        missing_ok = item["verdict"] == "应有未写" and has_rule
        if item["verdict"] in {"参数不一致", "应有未写", "做法冲突"} and (excerpt or missing_ok):
            cited = next((clause for clause in item.get("clauses") or [] if clause.get("key") == clause_key), None)
            quote = ""
            if cited:
                quote = f"{cited.get('code') or ''} {cited.get('clauseNo') or ''} {cited.get('excerpt') or ''}".strip()
            elif item.get("mustWrite"):
                quote = str(item.get("mustWrite") or "")
            severity = str(item.get("severityHint") or "")
            if severity not in {"废标", "降档", "扣分", "建议"}:
                severity = "降档" if item["verdict"] == "参数不一致" else "扣分"
            if item.get("checkType") == "建议":
                severity = "建议"
            findings.append(
                {
                    "engine": "standard_review",
                    "level": "L3",
                    "severity": severity,
                    "location": f"{item.get('chapter') or item.get('evidence') or '技术标'} / 规范对标",
                    "excerpt": excerpt,
                    "rule": f"{item['name']}：{item['verdict']}",
                    "tenderQuote": quote[:400],
                    "basis": str(item.get("evidence") or "")[:200],
                    "suggestion": item.get("suggestion") or item["reason"] or f"按检索到的规范条文核对「{item['name']}」。",
                    "confidence": 0.7,
                }
            )
        points.append(item)
    return points, findings


def _strip_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def _parse_judge_items(raw: str) -> list:
    text = _strip_fence(raw)
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "rules", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    found: list[dict] = []
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace < 0:
            break
        try:
            obj, end_at = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            idx = brace + 1
            continue
        if isinstance(obj, dict) and obj.get("id") and obj.get("verdict"):
            found.append(obj)
        idx = max(end_at, brace + 1)
    return found


def _judge_batch(batch: list[dict], bid_text: str, is_engineering: bool = True) -> list[dict]:
    rules = []
    for point in batch:
        knowledge = [
            " ".join(
                bit
                for bit in (item.get("title") or "", item.get("heading") or "", item.get("excerpt") or "")
                if bit
            ).strip()
            for item in (point.get("knowledge") or [])
            if isinstance(item, dict)
        ]
        rules.append(
            {
                "id": point["id"],
                "name": point["name"],
                "source": point["source"],
                "fact": point.get("mustWrite") or point.get("detail") or "",
                "parameters": point.get("parameters") or "",
                "standards": point.get("standards") or [],
                "chapter": point.get("chapter") or "",
                "axis": point.get("axis") or "",
                "ruleScore": point.get("ruleScore") or "",
                "grades": point.get("grades") or "优100、良90、中等80、一般70、差60",
                "checkType": point.get("checkType") or "",
                "evidence": point.get("evidence") or "",
                "knowledge": [item for item in knowledge if item],
                "clauses": [
                    {"clauseKey": clause["key"], "text": clause.get("excerpt") or ""}
                    for clause in point.get("clauses") or []
                ],
            }
        )
    raw = chat_complete(
        model_id=get_default_model_id(),
        messages=[
            {"role": "system", "content": _judge_system_for(is_engineering)},
            {
                "role": "user",
                "content": json.dumps({"bid": bid_text or "", "rules": rules}, ensure_ascii=False),
            },
        ],
        temperature=0.1,
        timeout=180,
        max_tokens=min(16000, 3500 * max(len(batch), 1)),  # 每点预留 3500 token，批大了响应也要跟着长，但封顶避免拖慢单次请求
    )
    return _parse_judge_items(raw)


def judge_points(packed: list[dict], bid: str, is_engineering: bool = True) -> tuple[list[dict], list[dict]]:
    pending = [
        point
        for point in packed
        if point.get("clauses") or point.get("knowledge") or point.get("mustWrite") or point.get("parameters")
    ]
    jobs: list[tuple[str, list[dict]]] = []
    for chunk in bid_chunks(bid or ""):
        for offset in range(0, len(pending), BATCH):
            jobs.append((chunk, pending[offset : offset + BATCH]))

    def work(chunk: str, batch: list[dict]) -> tuple[list[dict], list[dict]]:
        try:
            raw_items = _judge_batch(batch, chunk, is_engineering)
        except (LlmError, json.JSONDecodeError, TypeError, ValueError):
            logger.exception("standard review judge failed")
            raw_items = []
        return raw_items, batch

    by_id: dict[str, list[dict]] = {}

    def absorb(raw_items: list[dict], batch: list[dict]) -> None:
        got = {str(item.get("id") or "") for item in raw_items if isinstance(item, dict)}
        for item in raw_items:
            if isinstance(item, dict):
                by_id.setdefault(str(item.get("id") or ""), []).append(item)
        for point in batch:
            if point["id"] not in got:
                by_id.setdefault(point["id"], []).append(
                    {"id": point["id"], "verdict": "已响应", "reason": "本次未能完成全文判断"}
                )

    # 全文每一段都要判一遍，覆盖面不能少；但段与段互不依赖，可以并发跑，不用排队等上一段。
    if len(jobs) <= 1:
        for chunk, batch in jobs:
            absorb(*work(chunk, batch))
    else:
        with ThreadPoolExecutor(max_workers=min(JUDGE_WORKERS, len(jobs))) as pool:
            futures = [pool.submit(work, chunk, batch) for chunk, batch in jobs]
            for future in as_completed(futures):
                absorb(*future.result())

    merged = [merge_chunk_judgments(by_id.get(point["id"]) or []) for point in pending]
    for point, item in zip(pending, merged):
        item["id"] = point["id"]
    return apply_judgments(packed, merged, bid)


_CATALOG_CODE = re.compile(r"^(?P<head>GB/T|GB|SL/T|SL)(?P<num>\d+(?:\.\d+)?)-(?P<year>(?:19|20)\d{2})$", re.I)


def _norm_standard_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper().replace("—", "-").replace("–", "-")


def _standard_family(code: str) -> tuple[str, str] | None:
    parsed = _CATALOG_CODE.match(_norm_standard_code(code))
    if not parsed:
        return None
    head = parsed.group("head").upper()
    if head in {"SL", "SL/T"}:
        head = "SL"
    return head, parsed.group("num")


def newer_catalog_row(cited: str, rows: list):
    """同一标准号有更新的现行版本时返回那一行。库里没有更新的不编造。"""
    parsed = _CATALOG_CODE.match(_norm_standard_code(cited))
    family = _standard_family(cited)
    if not parsed or family is None:
        return None
    year = int(parsed.group("year"))
    best = None
    best_year = year
    for row in rows or []:
        code = row.get("code") if isinstance(row, dict) else getattr(row, "code", "")
        status = row.get("status") if isinstance(row, dict) else getattr(row, "status", "")
        other = _CATALOG_CODE.match(_norm_standard_code(str(code or "")))
        if other is None or _standard_family(str(code or "")) != family:
            continue
        if str(status or "") == "废止":
            continue
        other_year = int(other.group("year"))
        if other_year > best_year:
            best = row
            best_year = other_year
    return best


def cited_standard_findings(bid_text: str) -> list[dict]:
    """标书引用了目录里已废止、被替代或年号旧于现行版本的标准号时记一条问题。库里没有的不编造。"""
    codes = []
    for match in re.findall(r"(?:GB/T|GB|SL/T|SL)\s*\d+(?:\.\d+)?-\d{4}", bid_text or "", flags=re.I):
        code = _norm_standard_code(match)
        if code not in codes:
            codes.append(code)
    if not codes:
        return []
    try:
        from ..db import platform_session
        from ..platform_models import StdCatalog

        pdb = platform_session()
        try:
            rows = pdb.query(StdCatalog).all()
        finally:
            pdb.close()
    except Exception:
        logger.exception("cited standard lookup failed")
        return []
    by_code = {_norm_standard_code(row.code): row for row in rows}
    findings = []
    for code in codes:
        row = by_code.get(code)
        if row is not None and (row.status == "废止" or (row.replaced_by or "").strip()):
            findings.append(
                {
                    "engine": "standard_review",
                    "level": "L3",
                    "severity": "扣分",
                    "location": "技术标 / 引用规范",
                    "excerpt": row.code,
                    "rule": f"{row.code} 已被替代" if row.replaced_by else f"{row.code} 已废止",
                    "tenderQuote": row.replaced_by or row.status,
                    "basis": f"{row.code} {row.replaced_by or row.status}".strip(),
                    "suggestion": f"请改用现行标准 {row.replaced_by or '目录中的替代标准'}。",
                    "confidence": 0.8,
                }
            )
            continue
        newer = newer_catalog_row(code, rows)
        if newer is None:
            continue
        newer_code = _norm_standard_code(newer.code if not isinstance(newer, dict) else newer.get("code"))
        if not newer_code or newer_code == code:
            continue
        findings.append(
            {
                "engine": "standard_review",
                "level": "L3",
                "severity": "扣分",
                "location": "技术标 / 引用规范",
                "excerpt": code,
                "rule": f"{code} 年号不符",
                "tenderQuote": newer_code,
                "basis": f"{code} 现行版本为 {newer_code}",
                "suggestion": f"请改用现行标准 {newer_code}。",
                "confidence": 0.75,
            }
        )
    return findings


def review(
    db: Session,
    *,
    score_rules: list | None,
    dimensions: list | None,
    bid_text: str,
    paragraphs: list[dict] | None = None,
    scope: str = "full",
    tech_rules: list | None = None,
    drawing_rules: list | None = None,
    project_rules: list | None = None,
    category: str = "",
) -> dict:
    is_engineering = is_engineering_category(category)
    specialty = project_specialty(dimensions)
    points = build_points(
        score_rules,
        dimensions,
        scope=scope,
        tech_rules=tech_rules,
        drawing_rules=drawing_rules,
        project_rules=project_rules,
    )
    reparse = scope != "business" and not tech_rules and not drawing_rules and not project_rules
    if not points:
        note = REPARSE_NOTE if reparse else "本项目没有抽出查核点"
        return {"specialty": specialty, "note": note, "points": [], "findings": []}

    packed: list[dict] = []
    hit_count = 0
    for point in points:
        standards = " ".join(point.get("standards") or [])
        query = f"{point['name']} {point.get('mustWrite') or point.get('detail') or ''} {standards}"
        try:
            clauses = search_clauses(db, query, specialty)
        except Exception:
            logger.exception("standard clause search failed")
            clauses = []
        try:
            knowledge = relevant_knowledge(
                search_knowledge(
                    db,
                    f"{point['name']} {point.get('parameters') or ''} {standards}",
                ),
                point["name"],
            )
        except Exception:
            logger.exception("knowledge rag failed")
            knowledge = []
        item = dict(point)
        item["clauses"] = clauses
        item["knowledge"] = knowledge
        if clauses or knowledge:
            hit_count += 1
        elif not (item.get("mustWrite") or item.get("parameters")):
            item["verdict"] = MISS
            item["reason"] = "规范库没有命中对应条文"
        packed.append(item)

    para_text = "\n".join(str(item.get("text") or "") for item in paragraphs or [] if isinstance(item, dict))
    body = para_text if len(para_text) > len(bid_text or "") else (bid_text or "")
    judgeable = any(
        point.get("clauses") or point.get("knowledge") or point.get("mustWrite") or point.get("parameters")
        for point in packed
    )
    findings: list[dict] = []
    if judgeable:
        judged, findings = judge_points(packed, body, is_engineering)
        judged_by_id = {item["id"]: item for item in judged}
        merged = []
        for point in packed:
            if point.get("verdict") == MISS:
                merged.append({key: value for key, value in point.items() if key != "window"})
            else:
                chosen = judged_by_id.get(point["id"]) or point
                merged.append({key: value for key, value in chosen.items() if key != "window"})
        packed_out = merged
    else:
        packed_out = [{key: value for key, value in point.items() if key != "window"} for point in packed]
    findings.extend(cited_standard_findings(body))

    if reparse:
        note = REPARSE_NOTE
    elif hit_count == 0 and any(point.get("mustWrite") or point.get("parameters") for point in points):
        note = "已通读投标书全文。知识库未命中，已按招标书写明的技术要求核对"
    elif hit_count == 0:
        note = "已通读投标书全文。知识库未命中，未对照条文下结论"
    else:
        note = f"已通读投标书全文，并对照 {hit_count} 个查核点的知识库工程知识"
    return {"specialty": specialty, "note": note, "points": packed_out, "findings": findings}
