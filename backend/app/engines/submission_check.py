"""提交前五项自查（缺项、矛盾、有效性、形式、补遗）与追溯矩阵。

每次修改后都可以重跑。结果只给提示，不阻止导出。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

CHECK_NAMES = ("缺项", "矛盾", "有效性", "形式", "补遗", "资质缺口")

_FIELD = re.compile(
    r"(工期|质保期|免费维保期|维保期|响应时间|到场时间|交付周期|投标有效期|服务期)[^，。；\n]{0,8}?"
    r"(\d+(?:\.\d+)?)\s*(个?工作日|日历天|天|日|小时|分钟|年|个月|月)"
)
_VALID_UNTIL = re.compile(r"有效期[至到:：\s]*(\d{4})\s*[年\-/.]\s*(\d{1,2})")
_PENDING = re.compile(r"待填|待补充|待补")


def _leaf_ids(outline: list[dict]) -> set[str]:
    parents = {str(n.get("parentId")) for n in outline if isinstance(n, dict) and n.get("parentId")}
    return {str(n["id"]) for n in outline if isinstance(n, dict) and n.get("id") and str(n["id"]) not in parents}


def refresh_forms(db, draft) -> int:
    """按最新应答记录重填偏离表等表单章节。返回更新的章节数。"""
    from sqlalchemy.orm.attributes import flag_modified

    from .form_registry import form_content
    from .req_ledger import collect_responses, full_project_ledger

    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    registry = settings.get("formRegistry") or []
    targets = [n for n in (draft.outline_json or []) if isinstance(n, dict) and n.get("formKeys")]
    if not registry or not targets:
        return 0
    ledger = full_project_ledger(draft.project_id)
    responses = collect_responses(db, draft.project_id)
    contents = dict(draft.chapter_contents_json or {})
    changed = 0
    team_filled = settings.get("teamFill") if isinstance(settings.get("teamFill"), dict) else {}
    # 记录系统上次写入的正文指纹；正文与指纹不一致说明用户手改过，不再覆盖
    auto = dict(settings.get("formAuto") or {}) if isinstance(settings.get("formAuto"), dict) else {}
    auto_changed = False
    for node in targets:
        cid = str(node["id"])
        body = form_content(list(node.get("formKeys") or []), registry, ledger, responses, team_filled)
        if not body:
            continue
        current = str(contents.get(cid) or "")
        if current == body:
            if auto.get(cid) != _fingerprint(body):
                auto[cid] = _fingerprint(body)
                auto_changed = True
            continue
        if current.strip() and cid in auto and auto[cid] != _fingerprint(current):
            continue  # 用户手改过
        contents[cid] = body
        auto[cid] = _fingerprint(body)
        auto_changed = True
        changed += 1
    if changed or auto_changed:
        if changed:
            draft.chapter_contents_json = contents
            flag_modified(draft, "chapter_contents_json")
        new_settings = dict(settings)
        new_settings["formAuto"] = auto
        draft.settings_json = new_settings
        flag_modified(draft, "settings_json")
        db.commit()
    return changed


def _fingerprint(text: str) -> str:
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _check_missing(outline: list[dict], contents: dict, ledger: list[dict], responses: dict) -> list[str]:
    problems: list[str] = []
    for entry in ledger:
        if not entry.get("chapters"):
            tag = "必须项" if entry.get("mandatory") else "条目"
            problems.append(f"{tag}「{entry['id']}」没有章节应答：{str(entry['text'])[:40]}")
    for node in outline:
        if str(node.get("id")) in _leaf_ids(outline) and not str(contents.get(node["id"]) or "").strip():
            problems.append(f"章节「{node.get('num') or ''}{node.get('title')}」还没有正文")
    for entry in ledger:
        if entry.get("chapters") and entry["id"] not in responses and entry.get("mandatory"):
            problems.append(f"必须项「{entry['id']}」还没有应答结论记录")
    return problems[:40]


def _check_conflicts(outline: list[dict], contents: dict) -> list[str]:
    seen: dict[str, dict[str, str]] = {}
    titles = {str(n.get("id")): f"{n.get('num') or ''}{n.get('title')}" for n in outline}
    for cid, text in contents.items():
        body = re.sub(r"^##\s*原始需求[\s\S]*?(?=^##\s*解决方案|\Z)", "", str(text or ""), flags=re.M)
        for label, number, unit in _FIELD.findall(body):
            seen.setdefault(label, {}).setdefault(f"{number}{unit}", titles.get(cid, cid))
    problems = []
    for label, values in seen.items():
        if len(values) >= 2:
            listed = "、".join(f"{v}（{c}）" for v, c in list(values.items())[:4])
            problems.append(f"「{label}」在不同章节写法不一致：{listed}")
    return problems


def _check_validity(contents: dict, today: datetime) -> list[str]:
    problems: list[str] = []
    for cid, text in contents.items():
        for year, month in _VALID_UNTIL.findall(str(text or "")):
            if (int(year), int(month)) < (today.year, today.month):
                problems.append(f"正文写到的证书有效期至 {year} 年 {month} 月已过期（章节 {cid}）")
    return problems[:20]


def _check_form(outline: list[dict], contents: dict, registry: list[dict]) -> list[str]:
    from .form_registry import pasted_matches_original

    problems: list[str] = []
    for node in outline:
        text = str(contents.get(node.get("id")) or "")
        keys = [k for k in (node.get("formKeys") or []) if isinstance(k, int)]
        if keys and not pasted_matches_original(text, keys, registry):
            problems.append(f"「{node.get('title')}」与招标书附录格式不一致，请恢复为原文")
        if "【未找到对应招标条款】" in str(node.get("idea") or ""):
            problems.append(f"「{node.get('title')}」没有对应的招标条款")
    pending = sum(len(_PENDING.findall(str(t or ""))) for t in contents.values())
    if pending:
        problems.append(f"全文还有 {pending} 处「待填/待补」，提交前需要人工补齐")
    return problems[:30]


def _check_addendum(db, draft) -> list[str]:
    from ..models import TenderDocument

    docs = (
        db.query(TenderDocument)
        .filter(TenderDocument.project_id == draft.project_id, TenderDocument.kind.in_(("addendum", "boq")))
        .all()
    )
    stamp = draft.updated_at or draft.created_at
    out: list[str] = []
    for doc in docs:
        if doc.uploaded_at and stamp and doc.uploaded_at > stamp:
            out.append(f"补遗/清单《{doc.filename}》在本草稿最近一次保存之后上传，请重新生成目录并核对")
    if not docs:
        out.append("本项目没有上传补遗或澄清文件；若招标方有补遗，请先上传再生成目录")
    return out


def gap_chapters(outline: list[dict], contents: dict) -> list[tuple[str, str, int]]:
    """正文里带红字缺口提示的章节：(章节编号+标题, 章节 id, 缺口处数)。"""
    from .red_marker import count_gaps

    out: list[tuple[str, str, int]] = []
    for node in outline:
        cid = str(node.get("id") or "")
        n = count_gaps(str(contents.get(cid) or ""))
        if n:
            out.append((f"{node.get('num') or ''}{node.get('title') or ''}", cid, n))
    return out


def _check_gaps(outline: list[dict], contents: dict) -> list[str]:
    rows = gap_chapters(outline, contents)
    if not rows:
        return []
    problems = [f"「{title}」有 {n} 处资质材料库内没有，正文已用红字标出，补充入库并重新生成后才能应标" for title, _cid, n in rows]
    return problems[:30]


def run_self_check(db, draft) -> dict:
    from .req_ledger import collect_responses

    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    ledger = settings.get("ledger") or []
    outline = [n for n in (draft.outline_json or []) if isinstance(n, dict)]
    contents = draft.chapter_contents_json or {}
    registry = settings.get("formRegistry") or []
    responses = collect_responses(db, draft.project_id)
    results = {
        "缺项": _check_missing(outline, contents, ledger, responses),
        "矛盾": _check_conflicts(outline, contents),
        "有效性": _check_validity(contents, datetime.utcnow()),
        "形式": _check_form(outline, contents, registry),
        "补遗": _check_addendum(db, draft),
        "资质缺口": _check_gaps(outline, contents),
    }
    checks = [{"name": name, "ok": not results[name], "problems": results[name]} for name in CHECK_NAMES]
    return {"checks": checks, "ok": all(c["ok"] for c in checks), "matrix": trace_matrix(ledger, responses, outline, contents)}


def trace_matrix(ledger: list[dict], responses: dict, outline: list[dict], contents: dict) -> list[dict]:
    from .red_marker import count_gaps

    # 台账用标题登记应答章节；目录里允许出现同名标题，所以一个标题对应其全部章节，而不是只取第一个
    by_title: dict[str, list[str]] = {}
    for node in outline:
        by_title.setdefault(str(node.get("title") or ""), []).append(str(node.get("id") or ""))

    def texts(titles: list[str]) -> list[str]:
        return [str(contents.get(cid) or "") for t in titles for cid in by_title.get(t, [])]

    rows: list[dict] = []
    for entry in ledger:
        resp = responses.get(entry["id"]) or {}
        chapter_texts = texts(entry.get("chapters") or [])
        written = any(t.strip() for t in chapter_texts)
        gap = sum(count_gaps(t) for t in chapter_texts)
        rows.append(
            {
                "id": entry["id"],
                "volume": "技术标" if entry.get("volume") == "tech" else "商务标",
                "requirement": entry.get("text") or "",
                "kind": entry.get("kind") or "",
                "mandatory": "是" if entry.get("mandatory") else "否",
                "source": entry.get("source") or "",
                "composition": entry.get("composition") or "",
                "chapters": "、".join(entry.get("chapters") or []),
                "status": resp.get("status") or ("已成文" if written else "未成文"),
                "answerSource": resp.get("source") or "",
                "evidence": "；".join(resp.get("evidence") or []),
                "gap": f"缺资质材料 {gap} 处" if gap else "",
            }
        )
    return rows


MATRIX_HEADERS = (
    ("id", "编号"),
    ("volume", "所属册"),
    ("requirement", "招标要求（原文）"),
    ("kind", "类型"),
    ("mandatory", "是否必须"),
    ("source", "招标书出处"),
    ("composition", "所属大章"),
    ("chapters", "应答章节"),
    ("status", "应答状态"),
    ("answerSource", "应答来源"),
    ("evidence", "依据编号"),
    ("gap", "资质缺口"),
)


_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value) -> str:
    """招标书原文进了 CSV，Excel 打开时以 = + - @ 开头的单元格会被当公式执行，前面加单引号转成文本。"""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_LEADS):
        return "'" + text
    return text


def matrix_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _key, label in MATRIX_HEADERS])
    for row in rows:
        writer.writerow([csv_cell(row.get(key, "")) for key, _label in MATRIX_HEADERS])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
