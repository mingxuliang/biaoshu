"""从招标文件正文抽出「约定章节」标题树，并把条款下的功能要求带到编写思路。

标题来自 Word 样式或正文编号（一、（一）、1.、3.1、3.1.1）。
「3.1.1 课程创建：支持…」这类标题+功能说明会拆成目录节点 + 应实现内容，不因段落过长丢条。
"""

from __future__ import annotations

import re

from .docx_extract import extract_paragraphs

_TOC_DOTS = re.compile(r"[.．…·]{3,}\s*\d+\s*$")
_PAGE_TAIL = re.compile(r"\s+\d{1,3}$")

_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_CN_DOT = re.compile(r"^([一二三四五六七八九十]+)、\s*(.*)$")
_CN_PAREN = re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]\s*(.*)$")
_DOTTED = re.compile(r"^(\d+\.\d+(?:\.\d+)*)(?:\s*[、.．:：]?\s*)(.*)$")
_SEQ = re.compile(r"^(\d{1,2})[.．、](?!\d)(.*)$")
_ATTACH = re.compile(r"^附件[0-9一二三四五六七八九十]")
_PREFIX = re.compile(
    r"^(?:"
    r"第[0-9一二三四五六七八九十百]+[章节篇]\s*"
    r"|[一二三四五六七八九十]+、\s*"
    r"|[（(][一二三四五六七八九十]+[）)]\s*"
    r"|\d+\.\d+(?:\.\d+)*[.．、]?\s*"
    r"|\d+[.．、）)]\s*"
    r")"
)

IDEA_MAX = 8000
BLOB_MAX = 12000

_FUNC_KEYS = ("功能需求", "功能要求", "系统功能", "业务功能")
_FUNC_SIDES = ("管理员端", "学员端", "教师端", "用户端", "管理端")
_REQ_CONTAINERS = ("用户需求书", "用户需求", "建设内容", "采购需求")

# 非功能需求：招标目录是需求，不是应标目录。对标成应标章节，原文全部写入编写思路。
_SCHEME_TEMPLATES: list[tuple[tuple[str, ...], str, list[tuple[str, str]]]] = [
    (
        ("项目管理",),
        "项目实施方案",
        [
            ("实施总体思路与方法", "阐述实施路径、阶段划分与采用的实施技术。"),
            ("组织机构与人员分工", "写明项目组织机构、岗位职责、人员投入与分工。"),
            ("进度计划与开发时间点", "给出里程碑、开发时间点与工期保障措施。"),
            ("沟通协调与风险管理", "说明沟通机制、变更控制与风险应对。"),
        ],
    ),
    (
        ("技术要求", "技术规格", "技术规范"),
        "技术架构与实施技术方案",
        [
            ("总体架构设计", "给出系统总体架构、分层与模块划分。"),
            ("关键技术与标准符合性", "说明关键技术选型及对招标技术标准的符合性。"),
            ("安全、性能与可靠性", "响应安全、性能、可靠性及运维指标。"),
            ("部署与运行环境", "说明部署架构、软硬件与运行环境。"),
        ],
    ),
    (
        ("运营管理",),
        "运营管理方案",
        [
            ("运营组织与流程", "写运营组织、岗位与日常流程。"),
            ("日常运营与监控", "写运行监控、内容运营与用户运营。"),
            ("持续改进与考核", "写考核指标、复盘与持续改进机制。"),
        ],
    ),
    (
        ("项目服务", "售后服务", "培训与"),
        "培训与运维服务方案",
        [
            ("培训方案", "写培训对象、课程、场次与考核。"),
            ("运维服务内容与响应", "写运维范围、服务级别与响应时限。"),
            ("质保与升级", "写质保期、缺陷修复与版本升级安排。"),
        ],
    ),
    (
        ("交付", "验收"),
        "项目交付与验收",
        [
            ("交付成果清单", "列明文档、系统、源代码、账号等交付物。"),
            ("验收标准与安排", "写验收条件、步骤、时间与责任分工。"),
        ],
    ),
    (
        ("保密",),
        "保密与知识产权管理",
        [
            ("保密措施", "写人员、数据、文档与现场保密措施。"),
            ("知识产权归属与使用", "写权属、授权范围与使用限制。"),
        ],
    ),
    (
        ("招聘",),
        "人员保障与招聘安排",
        [
            ("人员配置与资质", "写投入人员岗位、数量与资质要求。"),
            ("招聘与补充机制", "写招聘计划、到岗时间与人员替补。"),
        ],
    ),
]

TECH_ANCHORS = (
    "用户需求",
    "技术要求",
    "技术规范",
    "采购需求",
    "需求书",
    "功能需求",
    "建设内容",
    "技术规格",
    "服务需求",
    "技术方案应",
    "技术标应",
)
COMPOSE_ANCHORS = (
    "响应文件格式",
    "投标文件格式",
    "响应文件的格式",
    "投标文件的格式",
    "投标文件组成",
    "响应文件组成",
    "投标文件的组成",
    "响应文件的组成",
    "响应文件编制",
    "投标文件应包括",
    "响应文件应包括",
    "技术部分应包括",
    "技术标应包括",
    "投标文件的编制",
    "响应文件的编制",
)
STOP_VOLUMES = (
    "投标人须知",
    "评标办法",
    "评标方法",
    "合同条款",
    "合同格式",
    "资格审查",
    "资格预审",
    "开标",
)


def extract_stipulated_toc(path: str) -> dict:
    """返回 {compose, tech}，每项为 [{level, title, requirement}, ...]。"""
    try:
        paragraphs = extract_paragraphs(path)
    except Exception:
        return {"compose": [], "tech": []}

    headings = _heading_candidates(paragraphs)
    _attach_following_text(paragraphs, headings)
    compose = _slice_by_anchors(headings, COMPOSE_ANCHORS)
    tech = _slice_by_anchors(headings, TECH_ANCHORS)
    if not tech:
        tech = _fallback_tech_headings(headings)
    return {"compose": compose[:80], "tech": tech[:400]}


def format_toc_for_prompt(toc: dict) -> str:
    lines: list[str] = []
    compose = toc.get("compose") or []
    tech = toc.get("tech") or []
    if compose:
        lines.append("本份招标书对响应文件/投标文件组成与格式的规定（目录骨架以这些章节名与顺序为准，不得另换一套）：")
        for item in compose:
            pad = "  " * max(int(item.get("level") or 1) - 1, 0)
            lines.append(f"{pad}- {item.get('title', '')}")
        lines.append("")
    if tech:
        lines.append("本份招标书中的需求/技术条款（须挂入上方规定骨架的对应章节之下，不得单独改写成整本投标文件一级目录）：")
        for item in tech:
            pad = "  " * max(int(item.get("level") or 1) - 1, 0)
            req = (item.get("requirement") or "").strip()
            if req:
                lines.append(f"{pad}- {item.get('title', '')}")
                lines.append(f"{pad}  应实现：{req[:400]}")
            else:
                lines.append(f"{pad}- {item.get('title', '')}")
        lines.append("")
    if not compose and not tech:
        lines.append("（未能从招标文件样式/编号中抽出约定章节。）")
        lines.append("")
    return "\n".join(lines)


def toc_has_structure(toc: dict | None) -> bool:
    if not toc:
        return False
    return bool(toc.get("tech") or toc.get("compose"))


def _split_title_body(rest: str) -> tuple[str, str]:
    rest = (rest or "").strip()
    if not rest:
        return "", ""
    for sep in ("：", ":"):
        idx = rest.find(sep)
        if 0 < idx <= 40:
            return rest[:idx].strip(), rest[idx + 1 :].strip()
    return rest, ""


def _parse_numbered(text: str) -> tuple[int, str, str] | None:
    """返回 (level, title, inline_requirement)。"""
    m = _CHAPTER.match(text)
    if m:
        title, body = _split_title_body(text)
        return 1, title or text, body

    m = _CN_DOT.match(text)
    if m:
        rest = m.group(2).strip()
        title, body = _split_title_body(rest)
        label = f"{m.group(1)}、{title}".strip("、 ")
        return 2, label, body

    m = _CN_PAREN.match(text)
    if m:
        rest = m.group(2).strip()
        title, body = _split_title_body(rest)
        label = f"（{m.group(1)}）{title}".strip()
        return 3, label, body

    m = _DOTTED.match(text)
    if m:
        num, rest = m.group(1), (m.group(2) or "").strip()
        first = int(num.split(".", 1)[0])
        if first > 40:
            return None
        title, body = _split_title_body(rest)
        label = f"{num} {title}".strip() if title else num
        return 4 + num.count("."), label, body

    m = _SEQ.match(text)
    if m:
        num, rest = m.group(1), (m.group(2) or "").strip()
        if int(num) > 40:
            return None
        title, body = _split_title_body(rest)
        label = f"{num}. {title}".strip() if title else f"{num}."
        return 4, label, body

    if _ATTACH.match(text):
        title, body = _split_title_body(text)
        return 1, title or text, body
    return None


def _heading_candidates(paragraphs: list[dict]) -> list[dict]:
    items: list[dict] = []
    skip_toc = False
    for p in paragraphs:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if text in ("目录", "目 录") or (text.startswith("目录") and len(text) < 8):
            skip_toc = True
            continue
        if skip_toc and _CHAPTER.match(text):
            skip_toc = False
        if skip_toc:
            continue
        if _TOC_DOTS.search(text):
            continue

        style = (p.get("style") or "").lower()
        outline = p.get("outline_level")
        parsed = _parse_numbered(text)
        level = None
        title = _PAGE_TAIL.sub("", text).strip()
        inline = ""

        if parsed:
            level, title, inline = parsed
        elif style.startswith("heading"):
            digits = "".join(ch for ch in style if ch.isdigit())
            level = max(1, min(int(digits), 6)) if digits else 1
            title, inline = _split_title_body(text)
            title = title or text
        elif isinstance(outline, int) and 0 <= outline <= 5:
            level = outline + 1
            title, inline = _split_title_body(text)
            title = title or text

        if level is None or not title:
            continue
        inline = (inline or "").strip()
        if not inline:
            rest = strip_heading_prefix(title)
            if len(rest) > 28:
                inline = rest
        items.append(
            {
                "index": p.get("index", 0),
                "level": level,
                "title": title[:80],
                "requirement": inline,
            }
        )
    return _split_glued_headings(items)


def _split_glued_headings(items: list[dict]) -> list[dict]:
    """拆开「培训大纲  1.1学习大纲」这类粘在同一段里的子标题。"""
    glued = re.compile(r"\s{2,}(\d+\.\d+(?:\.\d+)*)\s*")
    out: list[dict] = []
    for item in items:
        title = item.get("title") or ""
        m = glued.search(title)
        if not m:
            out.append(item)
            continue
        left = title[: m.start()].strip()
        right = f"{m.group(1)} {title[m.end():].strip()}".strip()
        a = dict(item)
        a["title"] = left[:80]
        out.append(a)
        b = dict(item)
        b["level"] = int(item.get("level") or 1) + 1
        b["title"] = right[:80]
        b["requirement"] = (item.get("requirement") or "") if not left else ""
        out.append(b)
    return out


def _attach_following_text(paragraphs: list[dict], headings: list[dict]) -> None:
    """把两条标题之间的正文并入上一标题的 requirement。"""
    if not headings:
        return
    heading_indexes = [h["index"] for h in headings]
    heading_set = set(heading_indexes)
    by_index = {h["index"]: h for h in headings}
    para_by_index = {p.get("index"): p for p in paragraphs}
    all_idx = sorted(para_by_index)
    for i, h_idx in enumerate(heading_indexes):
        next_h = heading_indexes[i + 1] if i + 1 < len(heading_indexes) else None
        chunks: list[str] = []
        for idx in all_idx:
            if idx <= h_idx:
                continue
            if next_h is not None and idx >= next_h:
                break
            if idx in heading_set:
                continue
            text = (para_by_index[idx].get("text") or "").strip()
            if text:
                chunks.append(text)
        extra = "\n".join(chunks).strip()
        if extra:
            prev = (by_index[h_idx].get("requirement") or "").strip()
            merged = f"{prev}\n{extra}".strip() if prev else extra
            by_index[h_idx]["requirement"] = merged[:50000]


def _contains_any(title: str, needles: tuple[str, ...]) -> bool:
    return any(n in title for n in needles)


def _is_section_anchor(title: str, anchors: tuple[str, ...]) -> bool:
    compact = (title or "").replace(" ", "")
    if len(compact) > 36:
        return False
    return _contains_any(compact, anchors)


def _find_anchor_index(headings: list[dict], anchors: tuple[str, ...]) -> int | None:
    ranked: list[tuple[int, int]] = []
    for i, h in enumerate(headings):
        title = h.get("title") or ""
        if not _is_section_anchor(title, anchors):
            continue
        score = 0
        if _CHAPTER.match(title):
            score += 10
        if any(k in title for k in ("响应文件格式", "投标文件格式", "投标文件组成", "响应文件组成")):
            score += 12
        if "用户需求书" in title or "技术规范" in title:
            score += 8
        if int(h.get("level") or 9) <= 2:
            score += 3
        ranked.append((score, i))
    if not ranked:
        return None
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][1]


def _slice_by_anchors(headings: list[dict], anchors: tuple[str, ...]) -> list[dict]:
    start = _find_anchor_index(headings, anchors)
    if start is None:
        return []
    base_level = headings[start]["level"]
    out = [headings[start]]
    for h in headings[start + 1 :]:
        if h["level"] <= base_level:
            if _contains_any(h["title"], STOP_VOLUMES) or _CHAPTER.match(h["title"]):
                break
            if h["level"] < base_level:
                break
        out.append(h)
    return out


def _fallback_tech_headings(headings: list[dict]) -> list[dict]:
    out: list[dict] = []
    skipping = False
    skip_level = 99
    for h in headings:
        title = h["title"]
        if _contains_any(title, STOP_VOLUMES) and h["level"] <= 2:
            skipping = True
            skip_level = h["level"]
            continue
        if skipping:
            if h["level"] <= skip_level and not _contains_any(title, STOP_VOLUMES):
                skipping = False
            else:
                continue
        if _contains_any(title, TECH_ANCHORS) or (not _contains_any(title, STOP_VOLUMES) and h["level"] >= 2):
            out.append(h)
    return out[:200]


def strip_heading_prefix(title: str) -> str:
    t = (title or "").strip()
    prev = None
    while prev != t:
        prev = t
        t = _PREFIX.sub("", t).strip()
    return t or (title or "").strip()


def clause_no(title: str) -> str:
    t = (title or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)*)", t)
    if m:
        return m.group(1)
    m = re.match(r"^([一二三四五六七八九十]+)、", t)
    if m:
        return f"{m.group(1)}、"
    m = re.match(r"^[（(]([一二三四五六七八九十]+)[）)]", t)
    if m:
        return f"（{m.group(1)}）"
    m = re.match(r"^第([0-9一二三四五六七八九十百]+)[章节篇]", t)
    if m:
        return f"第{m.group(1)}章"
    return ""


def _node_from_heading(h: dict) -> dict:
    title = h.get("title") or "未命名章节"
    req = (h.get("requirement") or "").strip()
    if req:
        idea = f"应实现：{req}"
    else:
        idea = f"按招标文件约定章节「{title}」逐项响应，不得漏项。"
    return {
        "title": title,
        "requirement": req,
        "sourceIndex": h.get("index"),
        "dimension": None,
        "weight": 0,
        "idea": idea[:IDEA_MAX],
        "aiIdea": idea[:IDEA_MAX],
        "children": [],
    }


def headings_to_chapters(headings: list[dict]) -> list[dict]:
    """按 level 栈还原层级：3.1 下挂 3.1.1 / 3.1.2，功能要求写入 idea。"""
    if not headings:
        return []
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for h in headings:
        node = _node_from_heading(h)
        lv = int(h.get("level") or 1)
        while stack and stack[-1][0] >= lv:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1]["children"].append(node)
        stack.append((lv, node))

    if len(roots) == 1 and roots[0].get("children"):
        return roots[0]["children"]
    return roots


def expand_with_knowledge(chapters: list[dict], knowledge_headings: list[str] | None) -> list[dict]:
    """仅在标题能对上的约定章下追加知识库子节，不替换原节点。"""
    if not knowledge_headings:
        return chapters

    def core(title: str) -> str:
        return re.sub(r"^[\d一二三四五六七八九十.\s、（）()]+", "", title or "").strip()

    existing: set[str] = set()

    def collect(nodes: list[dict]) -> None:
        for n in nodes:
            existing.add((n.get("title") or "").strip())
            collect(n.get("children") or [])

    collect(chapters)

    def walk(nodes: list[dict]) -> None:
        for n in nodes:
            key = core(n.get("title") or "")
            kids = n.setdefault("children", [])
            if n.get("map_mode") == "scheme":
                continue
            if key and len(key) >= 2:
                added = 0
                for kh in knowledge_headings:
                    if added >= 2:
                        break
                    kh = (kh or "").strip()
                    if not kh or kh in existing:
                        continue
                    if key in kh or kh in key:
                        kids.append(
                            {
                                "title": kh,
                                "dimension": None,
                                "weight": 0,
                                "idea": f"借鉴知识库同类目录「{kh}」，在招标约定「{n.get('title')}」下补充实施要点，不得偏离招标功能要求。",
                                "aiIdea": f"借鉴知识库同类目录「{kh}」，在招标约定「{n.get('title')}」下补充实施要点，不得偏离招标功能要求。",
                                "children": [],
                            }
                        )
                        existing.add(kh)
                        added += 1
            walk(kids)

    walk(chapters)
    return chapters


def _is_function_chapter(title: str) -> bool:
    t = title or ""
    if any(k in t for k in _FUNC_KEYS) or any(k in t for k in _FUNC_SIDES):
        return True
    if re.match(r"^\d+\.\d+", t.strip()):
        plain = strip_heading_prefix(t)
        return not any(k in plain for keys, _, _ in _SCHEME_TEMPLATES for k in keys)
    return False


def _is_req_container(title: str) -> bool:
    t = strip_heading_prefix(title or "")
    compact = t.replace(" ", "")
    if _is_function_chapter(t):
        return False
    return any(k in compact for k in _REQ_CONTAINERS)


def _extract_req_text(node: dict) -> str:
    req = (node.get("requirement") or "").strip()
    if req:
        return req
    idea = (node.get("idea") or "").strip()
    if idea.startswith("应实现："):
        return idea[4:].strip()
    if idea.startswith("按招标文件约定章节"):
        return ""
    return idea


def _collect_requirement_blob(node: dict) -> str:
    chunks: list[str] = []

    def walk(n: dict) -> None:
        title = (n.get("title") or "").strip()
        req = _extract_req_text(n)
        label = strip_heading_prefix(title) or title
        clause = clause_no(title)
        head = f"{clause} {label}".strip() if clause else label
        if req:
            chunks.append(f"【{head}】{req}")
        elif head:
            chunks.append(f"【{head}】")
        for child in n.get("children") or []:
            walk(child)

    walk(node)
    return "\n".join(chunks).strip()[:BLOB_MAX]


_HEADING_NOISE = re.compile(
    r"(功能需求服务|功能需求|建设设计|服务设计|管理建设|服务建设|建设|设计)$"
)

_TOPIC_ALIASES = (
    ("培训计划", "计划"),
    ("培训大纲", "大纲"),
    ("学习大纲", "大纲"),
    ("培训课件", "课件"),
    ("培训资源", "资源"),
    ("培训师资", "师资"),
    ("培训基地", "基地"),
    ("培训课程", "课程"),
    ("课程设置", "课程"),
    ("培训学习", "学习"),
    ("线上考试", "考试"),
    ("线下考试", "考试"),
    ("证书管理", "证书"),
    ("考试管理", "考试"),
    ("培训统计分析", "培训统计"),
    ("考试统计分析", "考试统计"),
    ("统计分析", "统计"),
    ("员工培训档案", "档案"),
    ("培训档案", "档案"),
    ("题库", "题库"),
    ("报表", "报表"),
)


def _is_catalog_title(text: str) -> bool:
    """已是应标/模块目录名，不是功能要求长句。"""
    t = (text or "").strip()
    if not t or len(t) > 14:
        return False
    if t.endswith(("。", "；", ";", "）", "）")):
        return False
    if re.search(r"支持|应当|应能|必须|包括但不|进行.{0,16}操作|可设置", t):
        return False
    return True


def _topic_word(parent_title: str) -> str:
    t = strip_heading_prefix(parent_title or "").replace(" ", "")
    t = _HEADING_NOISE.sub("", t)
    for key, alias in _TOPIC_ALIASES:
        if key in t:
            return alias
    if t.endswith("管理"):
        t = t[:-2]
    if len(t) >= 4:
        return t[-2:]
    return t or "功能"


def _distill_bid_title(text: str, parent_title: str, clause: str = "") -> str:
    """把功能要求描述提炼成应标短目录，如 新增计划 / 计划关联 / 计划编辑。"""
    raw = strip_heading_prefix(text or "").strip()
    if _is_catalog_title(raw):
        return raw
    body = re.sub(r"\s+", "", (text or ""))
    obj = _topic_word(parent_title)

    m = re.match(r"^([\u4e00-\u9fff]{2,8}?)(?:主要包含|包含|包括)", body)
    if m:
        name = m.group(1)
        if name not in {obj, "系统", "平台"}:
            return name[:12]

    m = re.search(r"创建和管理([\u4e00-\u9fff]{2,12})", body)
    if m:
        return m.group(1)[:12]

    if re.search(r"进行[\u4e00-\u9fff、，,]{2,40}(?:等)?操作", body):
        return f"{obj}编辑"

    if "新增" in body and ("导入" in body or "批量" in body) and "关联到" not in body:
        return f"新增{obj}"

    if re.search(r"关联到|相互关联|自动或手动关联", body) and not any(
        k in body for k in ("预算", "费用", "培训资源")
    ):
        return f"{obj}关联"

    if any(k in body for k in ("预算", "费用", "培训资源")) and "关联" in body:
        return f"{obj}资源关联"

    if "预警" in body:
        return "学时预警" if "学时" in body else f"{obj}预警"
    if "完成情况" in body and "导入" in body:
        return "完成情况导入"
    if "完成情况" in body and ("统计" in body or "分析" in body):
        return "培训完成统计"
    if "学时" in body and "统计" in body:
        return "学时统计"

    if "短视频" in body:
        return "短视频上传" if "上传" in body else "短视频学习"
    if "视频推送" in body or ("推送" in body and any(k in body for k in ("专业", "习惯", "岗位"))):
        return "个性化推送"

    verb_first = {"新增", "创建"}
    for pat, verb in (
        ("批量导入", "导入"),
        ("导入", "导入"),
        ("新增", "新增"),
        ("预约", "预约"),
        ("组卷", "组卷"),
        ("阅卷", "阅卷"),
        ("颁发", "颁发"),
        ("审核", "审核"),
        ("发布", "发布"),
        ("推送", "推送"),
        ("提醒", "提醒"),
        ("统计", "统计"),
        ("查询", "查询"),
        ("下载", "下载"),
        ("浏览", "浏览"),
        ("展示", "展示"),
        ("显示", "显示"),
        ("上传", "上传"),
        ("导出", "导出"),
        ("编辑", "编辑"),
        ("创建", "创建"),
        ("分类", "分类"),
        ("授权", "授权"),
        ("评分", "评分"),
        ("录入", "录入"),
        ("设置", "设置"),
    ):
        if pat in body:
            title = f"{verb}{obj}" if verb in verb_first else f"{obj}{verb}"
            return title[:12]

    if clause:
        return f"{obj}要点"[:12]
    return (raw or "功能要点")[:8]


def _should_keep_function_heading(clean: str, has_children: bool) -> bool:
    if _is_catalog_title(clean):
        return True
    if has_children and len(clean) <= 16 and not re.search(r"支持|应当|进行", clean):
        return True
    return False


def _dedupe_child_titles(children: list[dict]) -> None:
    used: set[str] = set()
    for child in children:
        title = (child.get("title") or "功能要点").strip()
        if title not in used:
            used.add(title)
            child["title"] = title
            continue
        alt = f"{title}要点"
        n = 2
        while alt in used:
            alt = f"{title}{n}"
            n += 1
        child["title"] = alt[:12]
        used.add(child["title"])


def _split_capability_chunks(text: str) -> list[str]:
    """把一段功能描述拆成可独立应标的能力点。"""
    t = (text or "").strip()
    if not t:
        return []
    numbered = re.split(r"(?=[（(]\d+[）)])", t)
    numbered = [p.strip() for p in numbered if p.strip()]
    numbered_body = [re.sub(r"^[（(]\d+[）)]\s*", "", p).strip() for p in numbered if re.match(r"[（(]\d+[）)]", p)]
    if len(numbered_body) >= 2:
        return [p for p in numbered_body if len(p) >= 6]

    parts = [p.strip("，,；;。 ") for p in re.split(r"(?=支持)", t) if p.strip()]
    parts = [p for p in parts if len(p) >= 8]
    if len(parts) >= 2:
        return parts[:8]
    return []


def _derive_third_level(parent_title: str, req: str, parent_clause: str, source_index=None) -> list[dict]:
    """二级功能点若本身没有子条，从描述中衍生三级功能点。"""
    chunks = _split_capability_chunks(req)
    if len(chunks) < 2:
        return []
    used: set[str] = {parent_title}
    children: list[dict] = []
    for i, chunk in enumerate(chunks[:8], start=1):
        sub_clause = f"{parent_clause}.{i}" if parent_clause else str(i)
        title = _distill_bid_title(chunk, parent_title, sub_clause)
        if not title or title in used:
            continue
        used.add(title)
        idea = f"【对应招标 {parent_clause}】应实现：{chunk}" if parent_clause else f"应实现：{chunk}"
        children.append(
            {
                "title": title[:12],
                "dimension": None,
                "weight": 0,
                "idea": idea[:IDEA_MAX],
                "aiIdea": idea[:IDEA_MAX],
                "map_mode": "function",
                "sourceIndex": source_index,
                "children": [],
            }
        )
    return children if len(children) >= 2 else []


def _clean_function_tree(node: dict, parent_title: str = "") -> dict:
    title = node.get("title") or ""
    clause = clause_no(title)
    clean = strip_heading_prefix(title)
    req = _extract_req_text(node)
    kids = node.get("children") or []
    source_index = node.get("sourceIndex")
    if _should_keep_function_heading(clean, bool(kids)):
        short = clean
    else:
        if not req:
            req = clean
        short = _distill_bid_title(req or clean, parent_title, clause)
    if req:
        idea = f"【对应招标 {clause}】应实现：{req}" if clause else f"应实现：{req}"
    else:
        idea = (
            f"【对应招标 {clause}】按招标功能点「{short}」逐项响应，不得漏项。"
            if clause
            else f"按招标功能点「{short}」逐项响应，不得漏项。"
        )
    children = [_clean_function_tree(c, clean or short) for c in kids]
    if not children and req:
        children = _derive_third_level(short, req, clause, source_index)
    _dedupe_child_titles(children)
    return {
        "title": short,
        "dimension": node.get("dimension"),
        "weight": node.get("weight") or 0,
        "idea": idea[:IDEA_MAX],
        "aiIdea": idea[:IDEA_MAX],
        "map_mode": "function",
        "sourceIndex": source_index,
        "children": children,
    }


def _pick_scheme_template(title: str) -> tuple[str, list[tuple[str, str]]]:
    t = strip_heading_prefix(title or "")
    for keys, bid_title, children in _SCHEME_TEMPLATES:
        if any(k in t for k in keys):
            return bid_title, children
    scheme = t.replace("需求", "方案")
    if not any(x in scheme for x in ("方案", "实施", "措施", "承诺", "安排")):
        scheme = f"{scheme}响应方案" if scheme else "专项响应方案"
    return scheme, [
        ("需求理解与响应要点", "归纳招标该项需求的全部条款并给出响应要点。"),
        ("实施方案与技术路径", "写具体怎么做，覆盖招标该项需求的每一条。"),
        ("组织、进度与保障措施", "写人员、计划、质量与服务保障。"),
    ]


def _restructure_requirement_chapter(node: dict) -> dict:
    orig = node.get("title") or "专项需求"
    orig_clean = strip_heading_prefix(orig)
    blob = _collect_requirement_blob(node)
    bid_title, specs = _pick_scheme_template(orig)
    cover = blob or f"（招标「{orig_clean}」未抽出条款正文，请对照招标文件补全后应标。）"
    parent_idea = (
        f"本章对标招标「{orig_clean}」，按应标结构撰写，不照搬招标目录。"
        f"下列子章必须覆盖该项需求全文，不得漏项。\n\n应覆盖招标需求全文：\n{cover}"
    )[:IDEA_MAX]
    children = []
    for child_title, guidance in specs:
        idea = (
            f"{guidance}本章对标招标「{orig_clean}」，不得按招标书目录逐条列标题，"
            f"但正文必须覆盖该项需求的全部内容，不得漏项。\n\n应覆盖招标需求全文，不得漏项：\n{cover}"
        )[:IDEA_MAX]
        children.append(
            {
                "title": child_title,
                "dimension": None,
                "weight": 0,
                "idea": idea,
                "aiIdea": idea,
                "map_mode": "scheme",
                "sourceIndex": node.get("sourceIndex"),
                "children": [],
            }
        )
    return {
        "title": bid_title,
        "dimension": None,
        "weight": 0,
        "idea": parent_idea,
        "aiIdea": parent_idea,
        "map_mode": "scheme",
        "sourceIndex": node.get("sourceIndex"),
        "children": children,
    }


def _transform_chapters(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for node in nodes:
        title = node.get("title") or ""
        if _is_function_chapter(title):
            out.append(_clean_function_tree(node))
        elif _is_req_container(title):
            kids = _transform_chapters(node.get("children") or [])
            if kids:
                out.extend(kids)
            else:
                out.append(_restructure_requirement_chapter(node))
        else:
            out.append(_restructure_requirement_chapter(node))
    return out


def build_bid_chapters(headings: list[dict]) -> list[dict]:
    """功能需求严格 1:1；其余需求整理为应标目录，编写思路收录需求全文。"""
    return _transform_chapters(headings_to_chapters(headings))
