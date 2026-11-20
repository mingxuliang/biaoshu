"""商务标取材：按招标要求从「企业资质证照库」查材料，命中的由代码原样拷贝，库里没有的空出并用红字提示。

流程：条款 → 拆成材料需求（类型、数量、判定条件）→ 在已入库材料里硬筛（类型、有效期、年限、金额）
→ 模型只判断「是否同类/角色相符」→ 代码把库内字段、原文和扫描件写进正文；不足的数量输出红字缺口块。
正文里的事实字段（项目名、金额、证号、人名）只来自库内记录，模型不参与书写。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from . import red_marker
from .qualification_schema import allowed_fields, describe
from .standard_product import _json_object

logger = logging.getLogger(__name__)

PROJECT_KINDS = {"contract", "achievement"}
MATERIAL_KINDS = {"cert", "people", "contract", "achievement", "financial", "credit", "equipment"}
MAX_CANDIDATES = 30
MAX_IMAGES_PER_ASSET = 6

NEEDS_SYSTEM = """你在阅读招标文件里的一条要求，判断投标人需要从「企业资质证照库」提供哪些材料来应答。
材料类型：cert 企业证照与资质证书、荣誉证书；people 拟派人员及其资格；contract 合同与项目业绩（同类项目、案例）；financial 财务报告与审计报告、纳税证明；credit 信用材料与无违法声明依据；equipment 设备。
只拆「本章标题所指」的材料：条款可能是一整段资格要求，里面有证照、项目案例、人员、信用等多类材料，标题对不上的一律不拆。
例如标题是「资质证照」就不要拆项目案例和人员；标题是「同类项目案例」就不要拆证照和人员；标题是「项目团队」只拆人员。
要求里写「近 N 年」时 withinYears 填 N；写「合同金额不少于 X 万元」时 minAmountWan 填 X。
纯承诺、格式、时间地点、报价、付款、技术方案类要求不需要材料，返回空数组。
返回 JSON：{"needs":[{"label":"材料名称，如 同类项目业绩","kind":"类型","count":数量整数,"criteria":"判定条件原文，如 培训管理系统或同类数字化平台","withinYears":年限整数没有则0,"minAmountWan":金额下限万元数没有则0,"role":"人员岗位，仅people","excludeTerms":["招标明确不计入的业绩类型，如 水环境治理；没写就是空数组"],"original":"招标原文中对应的那句话"}]}
招标没写数量时 count 取 1。不要编造招标没有的条件。只返回 JSON。"""

JUDGE_SYSTEM = """你判断本公司已入库的材料是否满足招标的一项材料要求。
只依据给出的字段判断。字段里看不出符合的一律不选；同类项目要看项目类型、建设内容是否属于要求的范围。
返回 JSON：{"ids":["符合要求的材料 id，不符合的不要写"]}。只返回 JSON。"""


# ---------- 解析工具 ----------

def parse_amount_wan(text: str) -> float | None:
    """把「158万元」「1,200,000元」「25 万」换算成万元数，识别不了返回 None。"""
    raw = (text or "").replace(",", "").replace("，", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(亿|万|千)?", raw)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return value * 10000
    if unit == "万":
        return value
    if unit == "千":
        return value / 10
    if "元" in raw or value >= 10000:
        return value / 10000
    return None


def parse_date(text: str) -> date | None:
    m = re.search(r"(20\d{2}|19\d{2})\s*[年.\-/]\s*(\d{1,2})?\s*[月.\-/]?\s*(\d{1,2})?", text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2) or 12), int(m.group(3) or 28))
    except ValueError:
        try:
            return date(int(m.group(1)), int(m.group(2) or 12), 28)
        except ValueError:
            return None


def latest_date(attrs: dict) -> date | None:
    dates = [parse_date(str(attrs.get(k) or "")) for k in ("endDate", "signDate", "startDate")]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def is_expired(valid_until: str, today: date) -> bool:
    text = (valid_until or "").strip()
    if not text or text in ("长期", "长期有效"):
        return False
    d = parse_date(text)
    return bool(d and d < today)


# ---------- 材料需求 ----------

def _call_json(system: str, user: str, model_id: str | None, max_tokens: int = 1200) -> dict:
    from .llm import LlmError, chat_complete

    try:
        text = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout=90,
            max_tokens=max_tokens,
        )
    except LlmError:
        logger.warning("business materials llm unavailable")
        return {}
    except Exception:  # noqa: BLE001
        logger.exception("business materials llm failed")
        return {}
    return _json_object(text)


def normalize_need(raw: dict) -> dict | None:
    kind = str(raw.get("kind") or "").strip()
    if kind not in MATERIAL_KINDS:
        return None
    try:
        count = max(1, min(int(raw.get("count") or 1), 20))
    except (TypeError, ValueError):
        count = 1

    def num(key: str) -> float:
        try:
            return max(0.0, float(raw.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0

    label = str(raw.get("label") or "").strip()[:40]
    if not label:
        return None
    return {
        "label": label,
        "kind": kind,
        "count": count,
        "criteria": (str(raw.get("criteria") or "").strip() or ("" if str(raw.get("role") or "").strip() else label))[:200],
        "withinYears": int(num("withinYears")),
        "minAmountWan": num("minAmountWan"),
        "role": str(raw.get("role") or "").strip()[:40],
        "excludeTerms": [
            str(t).strip()[:20]
            for t in (raw.get("excludeTerms") if isinstance(raw.get("excludeTerms"), list) else [])
            if str(t or "").strip()
        ][:8],
        "original": str(raw.get("original") or "").strip()[:200],
    }


def extract_needs(title: str, requirement: str, model_id: str | None) -> list[dict]:
    if not (requirement or "").strip():
        return []
    data = _call_json(NEEDS_SYSTEM, f"本章标题：{title}\n\n招标要求：\n{requirement.strip()[:3000]}", model_id)
    needs = [normalize_need(r) for r in (data.get("needs") or []) if isinstance(r, dict)]
    out = [n for n in needs if n]
    # 模型没拆出排除项时，用同一套规则从招标原文兜底，选材和预审口径一致
    from .performance_scope import exclusions_from_text, merge_terms

    scoped = exclusions_from_text(requirement)
    for need in out:
        if need["kind"] in PROJECT_KINDS:
            need["excludeTerms"] = merge_terms(need.get("excludeTerms"), scoped)
    return out


# ---------- 匹配 ----------

def _kinds_for(kind: str) -> set[str]:
    return PROJECT_KINDS if kind in PROJECT_KINDS else {kind}


def hard_filter(need: dict, assets: list, today: date, unsure_out: set | None = None) -> tuple[list, list[str]]:
    """类型、有效期、年限、金额由代码判定。返回 (候选, 说明)。assets 是 ORM 条目。
    日期或金额识别不了的条目照样入围，id 记进 unsure_out，由最终选中的条目决定是否提示核对。"""
    kinds = _kinds_for(need["kind"])
    out: list = []
    dropped = {"expired": 0, "old": 0, "small": 0, "excluded": 0}
    exclude_terms = need.get("excludeTerms") or []
    unsure_ids = unsure_out if unsure_out is not None else set()
    for asset in assets:
        if asset.kind not in kinds:
            continue
        attrs = asset.attrs_json or {}
        if asset.kind in ("cert", "credit") and is_expired(asset.valid_until or "", today):
            dropped["expired"] += 1
            continue
        if exclude_terms and asset.kind in PROJECT_KINDS:
            from .performance_scope import hits as scope_hits

            text = " ".join(
                [str(asset.name or ""), str(asset.detail or "")] + [str(v) for v in attrs.values() if isinstance(v, (str, int, float))]
            )
            if scope_hits(text, exclude_terms):
                dropped["excluded"] += 1
                continue
        years = need["withinYears"]
        if years:
            if asset.kind in PROJECT_KINDS:
                d = latest_date(attrs)
                if d is None:
                    unsure_ids.add(asset.id)
                elif d < date(today.year - years, today.month, min(today.day, 28)):
                    dropped["old"] += 1
                    continue
            elif asset.kind == "financial":
                y = parse_date(str(attrs.get("year") or "") or (asset.valid_until or ""))
                if y and y.year < today.year - years:
                    dropped["old"] += 1
                    continue
        floor = need["minAmountWan"]
        if floor and asset.kind in PROJECT_KINDS:
            amount = parse_amount_wan(str(attrs.get("amount") or ""))
            if amount is None:
                unsure_ids.add(asset.id)
            elif amount < floor:
                dropped["small"] += 1
                continue
        out.append(asset)
    notes: list[str] = []
    if dropped["expired"]:
        notes.append(f"另有 {dropped['expired']} 项已过期，未采用。")
    if dropped["old"]:
        notes.append(f"另有 {dropped['old']} 项超出「近 {need['withinYears']} 年」范围，未采用。")
    if dropped["small"]:
        notes.append(f"另有 {dropped['small']} 项合同金额低于 {need['minAmountWan']:g} 万元，未采用。")
    if dropped["excluded"]:
        notes.append(
            f"另有 {dropped['excluded']} 项属于招标排除的业绩类型（{'、'.join(exclude_terms[:4])}），未采用。"
        )
    return out, notes


def asset_summary(asset) -> str:
    attrs = asset.attrs_json or {}
    parts = [f"名称：{asset.name}"]
    text = describe(asset.kind, attrs, asset.number or "", asset.owner or "", asset.valid_until or "")
    if text:
        parts.append(text)
    elif asset.detail:
        parts.append(f"说明：{(asset.detail or '')[:200]}")
    return "；".join(parts)[:500]


def _keyword_pick(need: dict, assets: list) -> list:
    words = [w for w in re.split(r"[、，,；;/或及和\s]+", f"{need['criteria']} {need['role']}") if len(w) >= 2]
    if not words:
        return list(assets)
    return [a for a in assets if any(w in asset_summary(a) for w in words)]


def judge_candidates(need: dict, candidates: list, model_id: str | None) -> list:
    """语义判断是否同类/岗位相符。没有判定条件时不问模型；模型不可用时退回关键词。"""
    if not candidates:
        return []
    if not need["criteria"] and not need["role"]:
        return list(candidates)
    pool = candidates[:MAX_CANDIDATES]
    listed = "\n".join(f"- id={a.id} {asset_summary(a)}" for a in pool)
    want = need["role"] and f"岗位：{need['role']}；" or ""
    data = _call_json(
        JUDGE_SYSTEM,
        f"招标要求：{need['label']}；{want}条件：{need['criteria'] or '无'}\n\n候选材料：\n{listed}",
        model_id,
    )
    if "ids" not in data:
        return _keyword_pick(need, pool)
    valid = {a.id: a for a in pool}
    return [valid[i] for i in data["ids"] if isinstance(i, str) and i in valid]


def _sort_recent(assets: list) -> list:
    def key(asset):
        d = latest_date(asset.attrs_json or {})
        return d or date(1900, 1, 1)

    return sorted(assets, key=key, reverse=True)


def match_need(need: dict, pool: list, pending: list, today: date, model_id: str | None) -> dict:
    """pool 是已入库材料，pending 是待审核材料（只用来提示，不参与）。"""
    unsure: set[str] = set()
    candidates, notes = hard_filter(need, pool, today, unsure)
    picked = _sort_recent(judge_candidates(need, candidates, model_id))
    matched = picked[: need["count"]]
    if any(a.id in unsure for a in matched):
        notes.append("所选材料里有日期或金额库内未记录，无法核对是否满足年限、金额要求，请人工确认。")
    missing = max(0, need["count"] - len(matched))
    if missing:
        waiting, _ = hard_filter(need, pending, today)
        if waiting:
            notes.append(f"资质库里还有 {len(waiting)} 项同类型材料处于「待审核」，审核入库后才能使用。")
    return {"need": need, "matched": matched, "missing": missing, "notes": notes}


def load_pool(db) -> tuple[list, list]:
    from sqlalchemy.orm import joinedload

    from ..models import QualificationAsset

    rows = db.query(QualificationAsset).options(joinedload(QualificationAsset.images)).all()
    return (
        [r for r in rows if (r.review_status or "已入库") == "已入库"],
        [r for r in rows if r.review_status == "待审核"],
    )


# ---------- 渲染 ----------

def image_keys(asset) -> list[str]:
    """扫描件的图片键，格式与 tasks._images_from_qualifications 的 prompt_key 一致。"""
    imgs = [img for img in (asset.images or []) if img.storage_path]
    related = [img for img in imgs if _caption_related(asset.name or "", img.caption or "")]
    keys = [f"qual:{asset.id}:{img.id}" for img in (related or imgs[:1])]
    if not keys and asset.storage_path:
        keys = [f"qual:{asset.id}:{asset.id}"]
    return keys[:MAX_IMAGES_PER_ASSET]


def _caption_related(name: str, caption: str) -> bool:
    """扫描件说明和条目名称有共同的连续两字就认为相关；说明为空视为相关。图是否贴对条目靠这一步兜底。"""
    cap = re.sub(r"\s+", "", caption or "")
    title = re.sub(r"\s+", "", name or "")
    if not cap or not title:
        return True
    grams = {title[i : i + 2] for i in range(len(title) - 1)}
    return any(g in cap for g in grams)


def _cell(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "\\|").strip()


def table_for(kind: str, assets: list) -> tuple[list[str], list[list[str]]]:
    """表头取该类型字段里至少一条记录有值的列；记录没有结构化字段时退回名称、编号、说明。"""
    fields = allowed_fields(kind)
    rows_attrs = []
    for asset in assets:
        attrs = dict(asset.attrs_json or {})
        if kind == "cert":
            attrs.setdefault("certName", asset.name or "")
            if asset.number:
                attrs.setdefault("number", asset.number)
            if asset.valid_until:
                attrs.setdefault("validUntil", asset.valid_until)
        if kind == "people" and asset.owner:
            attrs.setdefault("name", asset.owner)
        if kind in PROJECT_KINDS and asset.number:
            attrs.setdefault("contractNo", asset.number)
        rows_attrs.append(attrs)
    cols = [k for k in fields if any(a.get(k) for a in rows_attrs)]
    if not cols:
        headers = ["名称", "编号", "说明"]
        rows = [[a.name or "", a.number or "", (a.detail or "")[:160]] for a in assets]
        return headers, rows
    headers = [fields[k] for k in cols]
    rows = [[a.get(k, "") for k in cols] for a in rows_attrs]
    return headers, rows


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(_cell(c) for c in r) + " |" for r in rows)
    return "\n".join(lines)


def render(results: list[dict]) -> dict:
    """返回 {body, status, deviation, evidence, gaps}。body 里图片用 {{IMG:qual:资产:图}} 占位。"""
    blocks: list[str] = []
    evidence: list[str] = []
    gaps: list[str] = []
    total_missing = 0
    total_matched = 0
    for res in results:
        need, matched, missing = res["need"], res["matched"], res["missing"]
        total_matched += len(matched)
        total_missing += missing
        title = f"### {need['label']}"
        ask = need["criteria"] if need["criteria"] != need["label"] else ""
        ask = ask or need["role"] or ""
        head = f"招标要求：{need['label']}{('（' + ask + '）') if ask else ''}，需提供 {need['count']} 项。"
        part = [title, head]
        if matched:
            headers, rows = table_for(matched[0].kind, matched)
            part.append(f"我司提供 {len(matched)} 项，内容均取自公司资质证照库。")
            if missing:
                headers_full = headers
                rows = rows + [[red_marker.red_cell("【缺】")] + [""] * (len(headers_full) - 1)] * missing
            part.append(_md_table(headers, rows))
            for asset in matched:
                evidence.append(asset.id)
                for key in image_keys(asset):
                    part.append("{{IMG:" + key + "}}")
        elif missing:
            kind = need["kind"]
            headers = list(allowed_fields(kind).values())[:5] if kind != "cert" else ["证书名称", "证书编号", "有效期至"]
            part.append(_md_table(headers, [[red_marker.red_cell("【缺】")] + [""] * (len(headers) - 1)] * need["count"]))
        if missing:
            gaps.append(f"{need['label']}：需 {need['count']}，缺 {missing}")
            part.append(
                red_marker.gap_block(
                    need["label"], ask, need["count"], len(matched), res.get("notes") or []
                )
            )
        elif res.get("notes"):
            part.append("\n".join(f"- {n}" for n in res["notes"]))
        blocks.append("\n\n".join(part))
    if total_missing and total_matched:
        status = "部分满足"
    elif total_missing:
        status = "不满足"
    else:
        status = "满足"
    deviation = "无偏离" if not total_missing else "以下材料库内缺失，待补充：" + "；".join(gaps)
    body = (
        f"**响应情况：{status}**\n\n**实现方式：** 采用公司资质证照库内已入库的原始材料应答，内容与扫描件均为库内原件拷贝。\n\n"
        + "\n\n".join(blocks)
        + f"\n\n**偏离说明：** {deviation}"
    )
    return {"body": body, "status": status, "deviation": deviation, "evidence": evidence, "gaps": gaps}


def build_chapter(db, title: str, requirement: str, model_id: str | None, today: date | None = None) -> dict | None:
    """没有材料需求时返回 None，由调用方走原有写法。"""
    today = today or date.today()
    needs = extract_needs(title, requirement, model_id)
    if not needs:
        return None
    pool, pending = load_pool(db)
    results = [match_need(n, pool, pending, today, model_id) for n in needs]
    out = render(results)
    out["needs"] = needs
    return out


def match_text(db, title: str, requirement: str, model_id: str | None) -> str:
    """给 harness 工具看的纯文本结论：命中的材料 id 与字段、缺口。"""
    needs = extract_needs(title, requirement, model_id)
    if not needs:
        return "本条要求不需要从资质证照库取材料。"
    pool, pending = load_pool(db)
    today = date.today()
    lines: list[str] = []
    for need in needs:
        res = match_need(need, pool, pending, today, model_id)
        lines.append(f"【{need['label']}】需 {need['count']} 项，库内命中 {len(res['matched'])} 项，缺 {res['missing']} 项")
        for asset in res["matched"]:
            lines.append(f"- id={asset.id} {asset_summary(asset)}")
        for note in res["notes"]:
            lines.append(f"  说明：{note}")
        if res["missing"]:
            lines.append("  库内没有，不得编造；正文须空出并用红字提示用户补充。")
    return "\n".join(lines)


# ---------- 项目团队表 ----------

_ROLE_HEAD = re.compile(r"岗位|角色|职责|职务|拟任|分工")
_FIELD_HEAD = [
    (re.compile(r"序号|编号"), "index"),
    (re.compile(r"姓名|名字"), "name"),
    (re.compile(r"岗位|角色|拟任|分工"), "role"),
    (re.compile(r"职责|工作内容|投入"), "keep"),
    (re.compile(r"职称|职务|级别"), "title"),
    (re.compile(r"证书|资质|资格"), "certificates"),
    (re.compile(r"学历"), "education"),
    (re.compile(r"年限|经验|工龄"), "years"),
]

ROLES_SYSTEM = """从招标文件的一段要求里列出需要投标人配备的项目团队岗位。
返回 JSON：{"roles":["项目经理","产品顾问",...]}。招标没写岗位就返回空数组，不要自己补充。只返回 JSON。"""


def _split_row(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def _plain(cell: str) -> str:
    text = re.sub(r"#[cr]\d+#|\{\{[^}]*\}\}", "", cell or "")
    return re.sub(r"[*_`]|<br>", "", text).strip()


def team_roles(md: str, ledger_text: str, model_id: str | None) -> list[str]:
    """优先取表里已写好的岗位列；表是空白的就按招标要求拆岗位。"""
    lines = md.split("\n")
    table = [ln for ln in lines if ln.strip().startswith("|")]
    if len(table) >= 3:
        headers = [_plain(c) for c in _split_row(table[0])]
        role_cols = [i for i, h in enumerate(headers) if _ROLE_HEAD.search(h)]
        roles: list[str] = []
        for ln in table[2:]:
            cells = [_plain(c) for c in _split_row(ln)]
            for col in role_cols:
                if col < len(cells) and cells[col]:
                    roles.append(cells[col])
                    break
        if roles:
            return roles
    if not (ledger_text or "").strip():
        return []
    data = _call_json(ROLES_SYSTEM, ledger_text[:3000], model_id, 600)
    return [str(r).strip() for r in (data.get("roles") or []) if str(r).strip()][:20]


def _person_row(headers: list[str], index: int, asset, role: str, original: list[str] | None = None) -> list[str]:
    """按表头逐列填：库里有的字段取库内值，职责、投入比例等库里没有的列保留招标原表的内容。"""
    attrs = dict(asset.attrs_json or {}) if asset else {}
    if asset:
        attrs.setdefault("name", asset.owner or asset.name or "")
    original = original or []
    row: list[str] = []
    for col, head in enumerate(headers):
        key = next((k for pat, k in _FIELD_HEAD if pat.search(head)), "")
        kept = original[col] if col < len(original) else ""
        if key == "index":
            row.append(str(index))
        elif key == "role":
            row.append(role or attrs.get("role", ""))
        elif key == "keep" or not key:
            row.append(kept)
        elif asset:
            row.append(attrs.get(key, "") or "")
        elif key == "name":
            row.append(red_marker.red_cell("【缺人员】"))
        else:
            row.append("")
    return row


def fill_team_form(db, md: str, ledger_text: str, model_id: str | None) -> tuple[str, int]:
    """项目团队表：表头、注释原样，数据行由库内人员填入；岗位找不到人的行写红字。返回 (markdown, 缺口数)。"""
    lines = (md or "").split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.strip().startswith("|")]
    if len(idx) < 2:
        return md, 0
    start, end = idx[0], idx[-1] + 1
    headers = [_plain(c) for c in _split_row(lines[start])]
    roles = team_roles(md, ledger_text, model_id)
    if not roles:
        return md, 0
    pool, pending = load_pool(db)
    people = [a for a in pool if a.kind == "people"]
    used: set[str] = set()
    rows: list[list[str]] = []
    missing = 0
    data_rows = [[_plain(c) for c in _split_row(lines[i])] for i in idx[2:]]
    aligned = len(data_rows) == len(roles)
    for n, role in enumerate(roles, start=1):
        original = data_rows[n - 1] if aligned else None
        need = normalize_need({"label": role, "kind": "people", "count": 1, "role": role, "criteria": role}) or {}
        free = [a for a in people if a.id not in used]
        chosen = judge_candidates(need, free, model_id)[:1] if need else []
        if chosen:
            used.add(chosen[0].id)
            rows.append(_person_row(headers, n, chosen[0], role, original))
        else:
            missing += 1
            rows.append(_person_row(headers, n, None, role, original))
    kept = lines[start : start + 2]
    body = ["| " + " | ".join(_cell(c) if "{{" not in c else c.replace("|", "\\|") for c in r) + " |" for r in rows]
    out = lines[:start] + kept + body + lines[end:]
    if missing:
        waiting = len([a for a in pending if a.kind == "people"])
        notes = [f"团队表中有 {missing} 个岗位在资质证照库里找不到已入库的人员。"]
        if waiting:
            notes.append(f"资质库里还有 {waiting} 位人员处于「待审核」，审核入库后才能使用。")
        out.append("")
        out.append(red_marker.gap_block("项目团队人员", "、".join(roles), len(roles), len(roles) - missing, notes))
    return "\n".join(out), missing
