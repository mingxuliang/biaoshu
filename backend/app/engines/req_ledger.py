"""需求台账：每条应答要求逐字保留，带出处、类型、是否必须，目录生成后回填所属大章和章节。

台账条目编号沿用 T/B 编号（见 writer_tool_runtime.numbered_requirement_items），
所以 read_tender、目录里的「依据：T5」和台账是同一套编号。台账存在 draft.settings_json["ledger"]，
逐条应答记录存在 draft.settings_json["responses"]。
"""

from __future__ import annotations

import re

_MANDATORY = re.compile(r"[★*＊]|否决|废标|无效投标|被拒绝|不予接受|必须|不得|须")
_QUALIFY = re.compile(r"资格|资质|营业执照|业绩|信用|财务|审计|纳税|社保")
_SCORING = re.compile(r"评分|加分|得分|分值")
_FORMAT = re.compile(r"格式|签字|盖章|装订|份数|密封|页码|字体")
_HEADING = re.compile(r"^(第[0-9一二三四五六七八九十百零]+[章节篇].*|\d+(?:\.\d+)+\s*\S.*|附件[0-9一二三四五六七八九十]*.*)$")
_PART_SPLIT = re.compile(r"[；;]\s*")

STATUS_RANK = {"满足": 0, "部分满足": 1, "不满足": 2}
SOURCE_LABELS = ("标品", "知识库", "自行撰写")


def classify_item(text: str) -> str:
    """资格性 / 实质性 / 评分性 / 格式 / 应答。只看条款自己的措辞。"""
    body = text or ""
    if _QUALIFY.search(body) and not _SCORING.search(body):
        return "资格性"
    if re.search(r"[★*＊]|否决|废标|无效投标", body):
        return "实质性"
    if _SCORING.search(body):
        return "评分性"
    if _FORMAT.search(body):
        return "格式"
    return "应答"


def _is_mandatory(text: str) -> bool:
    return bool(_MANDATORY.search(text or ""))


def split_parts(text: str) -> list[str]:
    """复合句按分号拆成单点。不足两点时返回空，整条仍是一条。"""
    parts = [p.strip(" 。,，") for p in _PART_SPLIT.split(text or "") if len(p.strip(" 。,，")) >= 4]
    return parts if len(parts) >= 2 else []


def _source_label(original_lines: list[str], text: str) -> str:
    """在原文里找到这条的位置，返回它之前最近的章节标题。找不到返回空串。"""
    probe = re.sub(r"\s+", "", text or "")[:18]
    if len(probe) < 6:
        return ""
    heading = ""
    for line in original_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING.match(stripped) and len(stripped) <= 40:
            heading = stripped
        if probe in re.sub(r"\s+", "", stripped):
            return heading
    return ""


def build_ledger(tech_text: str, business_text: str, original_text: str = "") -> list[dict]:
    """从技术标、商务标应答条目生成台账。条目原文逐字保留（只去掉行首序号）。"""
    from .e_writer import _clean_item_text
    from .writer_tool_runtime import numbered_requirement_items

    lines = (original_text or "").replace("\r\n", "\n").split("\n")
    ledger: list[dict] = []
    for section, text in (("tech", tech_text), ("business", business_text)):
        for item_id, raw in numbered_requirement_items(text or "", section):
            body = _clean_item_text(raw)
            if not body:
                continue
            ledger.append(
                {
                    "id": item_id,
                    "volume": section,
                    "text": body,
                    "parts": split_parts(body),
                    "kind": classify_item(body),
                    "mandatory": _is_mandatory(body),
                    "source": _source_label(lines, body),
                    "composition": "",
                    "chapters": [],
                    "status": "",
                }
            )
    return ledger


def attach_chapters(ledger: list[dict], chapters: list[dict]) -> list[dict]:
    """目录生成后回填：每条台账由哪个大章下的哪些章节引用。"""
    index: dict[str, tuple[str, list[str]]] = {}

    def walk(nodes: list[dict], root: str) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = str(node.get("title") or "").strip()
            for ref in node.get("sourceRefs") or []:
                owner, titles = index.setdefault(str(ref), (root or title, []))
                if title and title not in titles:
                    titles.append(title)
            walk(node.get("children") or [], root)

    for root_node in chapters:
        if isinstance(root_node, dict):
            walk([root_node], str(root_node.get("title") or "").strip())
    for entry in ledger:
        hit = index.get(str(entry.get("id")))
        if hit:
            entry["composition"] = hit[0]
            entry["chapters"] = hit[1][:6]
    return ledger


def ledger_summary(ledger: list[dict]) -> dict:
    total = len(ledger)
    cited = sum(1 for e in ledger if e.get("chapters"))
    return {
        "total": total,
        "cited": cited,
        "mandatory": sum(1 for e in ledger if e.get("mandatory")),
        "uncited": [e["id"] for e in ledger if not e.get("chapters")][:40],
    }


def ledger_by_id(ledger: list[dict] | None) -> dict[str, dict]:
    return {str(e.get("id")): e for e in (ledger or []) if isinstance(e, dict) and e.get("id")}


def full_project_ledger(project_id: str, original_text: str = "") -> list[dict]:
    """技术标 T 条目加商务标 B 条目的完整台账（没有回填章节）。偏离表按它逐行出。"""
    from .writer_tool_runtime import load_tender_extracts

    extracts = load_tender_extracts(project_id)
    return build_ledger(extracts.get("tech") or "", extracts.get("business") or "", original_text)


_STATUS_LINE = re.compile(r"(?:响应情况|应答情况|满足情况)\s*[:：]\s*\**\s*(部分满足|不满足|满足)")
_HOW_LINE = re.compile(r"实现方式\s*[:：]\s*\**\s*([^\n]{2,400})")
_DEV_LINE = re.compile(r"偏离说明\s*[:：]\s*\**\s*([^\n]{1,300})")


def parse_response_marks(solution: str) -> dict:
    """从章节正文里读出逐条应答字样：取最差的响应情况，以及第一处实现方式和偏离说明。"""
    text = solution or ""
    states = _STATUS_LINE.findall(text)
    if not states:
        return {}
    worst = max(states, key=lambda s: STATUS_RANK.get(s, 0))
    how = _HOW_LINE.search(text)
    dev = _DEV_LINE.search(text)
    return {
        "status": worst,
        "how": (how.group(1).strip(" *。") if how else "")[:300],
        "deviation": (dev.group(1).strip(" *。") if dev else "")[:200],
    }


def record_responses(
    responses: dict,
    refs: list[str],
    chapter: str,
    solution: str,
    source: str = "",
    evidence: list[str] | None = None,
) -> dict:
    """把一章的应答结果记到它引用的每条台账上。source 取 标品 / 知识库 / 自行撰写。"""
    marks = parse_response_marks(solution)
    for ref in refs:
        row = dict(responses.get(ref) or {})
        row.update({k: v for k, v in marks.items() if v})
        row["chapter"] = chapter
        if source in SOURCE_LABELS:
            row["source"] = source
        if evidence:
            row["evidence"] = list(evidence)[:6]
        responses[str(ref)] = row
    return responses


def collect_responses(db, project_id: str) -> dict[str, dict]:
    """同项目所有草稿（技术标、商务标）的应答记录合在一起，偏离表要跨册取用。"""
    from ..models import WriterDraft

    merged: dict[str, dict] = {}
    for draft in db.query(WriterDraft).filter(WriterDraft.project_id == project_id).all():
        settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
        rows = settings.get("responses")
        if isinstance(rows, dict):
            for key, value in rows.items():
                if isinstance(value, dict):
                    merged.setdefault(str(key), value)
    return merged
