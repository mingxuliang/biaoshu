"""工程标技术标（施工组织设计）撰写：目录和正文都不依赖知识库，按招标事实和施工逻辑来写。

工程技术标的评审办法一般直接列出几项技术评分项（如「工程重点难点及危大工程的保障体系」
「确保工期与质量的保障体系与措施」「确保人、材、机的保障体系与措施」），并在技术标准和要求里
点名本工程的重点难点和危大工程。投标人的施组按下面的固定骨架编：

- 编制说明（编制依据、编制原则）
- 每个技术评分项一章，标题用评分项原文；章下按施工逻辑展开，点名的重难点逐条成节，
  每条再分「重难点分析」「重难点解决措施」；评分项里「包括但不限于 X」的 X 单独成节
- 附件：主要施工设备表、试验检测仪器表、劳动力计划表、进度横道图/网络图、施工总平面图、临时用地表

正文几乎都写在表格里：两列「项目 / 内容」表、一格文字框、多列数据表三种写法。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from .llm import LlmError, chat_complete
from .parse_schema import is_engineering_category

logger = logging.getLogger(__name__)

FACTS_KEY = "engFacts"

KIND_BOX = "box"
KIND_PAIRS = "pairs"
KIND_GRID = "grid"
KIND_FIGURE = "figure"
KIND_GROUP = "group"

SOURCE_TENDER = "招标点名"
SOURCE_EXTRA = "补充"


def is_engineering(category: str | None) -> bool:
    return is_engineering_category(category)


def is_engineering_tech(category: str | None, doc_kind: str | None) -> bool:
    return is_engineering(category) and (doc_kind or "tech") == "tech"


TRACK_SOFTWARE = "software"
TRACK_ENGINEERING = "engineering"
TRACK_WATER = "water"


def writer_track(category: str | None, specialty: str | None, doc_kind: str | None = "tech") -> str:
    """撰写轨道：软件服务标 / 工程标通用 / 工程标水利。水利必须是工程类技术标且专业为水利。"""
    if not is_engineering(category):
        return TRACK_SOFTWARE
    if (specialty or "").strip() == "水利" and (doc_kind or "tech") == "tech":
        return TRACK_WATER
    return TRACK_ENGINEERING


def apply_detected_specialty(current: str | None, detected: str | None) -> str:
    """用户选过的专业不覆盖。工程标通用解析成水利时留空，避免把通用项目改成水利轨道。"""
    if (current or "").strip():
        return (current or "").strip()
    name = (detected or "").strip()
    if name == "水利":
        return ""
    return name


# ---------------------------------------------------------------------------
# 工程事实
# ---------------------------------------------------------------------------

FACT_FIELDS = (
    "projectName",
    "location",
    "scale",
    "scope",
    "duration",
    "milestones",
    "quality",
    "greenBuilding",
    "smartSite",
    "civilization",
    "environment",
    "formatNote",
)
LIST_FIELDS = (
    "difficulties",
    "extraDifficulties",
    "hazards",
    "scoreItems",
    "attachments",
    "majorWorks",
    "buildings",
    "siteConstraints",
    "trades",
    "stages",
    "processSystems",
)

FACT_LABELS = {
    "projectName": "项目名称",
    "location": "建设地点",
    "scale": "建设规模",
    "scope": "招标范围",
    "duration": "计划工期",
    "milestones": "节点工期",
    "quality": "质量标准",
    "greenBuilding": "绿色建筑要求",
    "smartSite": "智慧工地要求",
    "civilization": "安全文明施工要求",
    "environment": "周边环境",
    "formatNote": "施组编制要求",
}

FACTS_SYSTEM = """你在阅读一份工程施工招标文件的节选，为编制技术标（施工组织设计）抽取本工程事实。
只抽取原文里写明的内容，没有的字段留空字符串或空数组，不要编造。只输出一个 JSON 对象，字段如下：
{
  "projectName": "项目名称",
  "location": "建设地点",
  "scale": "建设规模与主要建设内容（原文概括，不超过200字）",
  "scope": "招标范围（原文概括，不超过200字）",
  "duration": "计划工期，如 730日历天",
  "milestones": "计划开工日期、节点工期",
  "quality": "质量标准",
  "greenBuilding": "绿色建筑等级要求",
  "smartSite": "智慧工地等级要求",
  "civilization": "安全文明施工、扬尘防治、标准化工地等要求",
  "environment": "周边环境：临近住宅、道路、管线、障碍物等",
  "formatNote": "施工组织设计的编制要求：页数上限、字体字号、行距等",
  "pageLimit": 0,
  "scoreItems": [{"title": "技术评分项完整名称（原文逐字，含括号里的「包括但不限于…」）", "weight": "权重或分值", "points": "评审要点",
                  "sections": ["按施工逻辑建议的 3～6 个下级章节短标题"]}],
  "difficulties": [{"title": "不超过16字的短标题", "text": "招标文件点名的重点难点原文"}],
  "extraDifficulties": [{"title": "不超过16字的短标题", "text": "招标未点名、但按招标范围和工程特点必然存在的专业重难点，2～3条"}],
  "hazards": [{"name": "危大工程名称", "text": "原文或范围说明"}],
  "attachments": ["施工组织设计格式要求的附表名称，原文，如：附表一：拟投入本标段的主要施工设备表"],
  "majorWorks": ["主要分部分项工程，如：土方工程、基坑支护、主体结构、装饰装修、安装工程"],
  "buildings": [{"name": "单体建（构）筑物名称", "scale": "面积/高度/层数", "structure": "结构形式"}],
  "siteConstraints": [{"title": "现场约束短标题", "text": "原文：临近住宅、无市政道路、管线、邻厂、作业面等"}],
  "trades": ["本工程实际专业，如：土建、市政道排、机电设备安装、智能化"],
  "stages": [{"name": "施工阶段名称", "work": "该阶段主要工作，原文口径"}],
  "processSystems": [{"name": "工艺系统名称", "text": "规模或约束，如 转运1000吨/天、渗滤液处理"}]
}
注意：
1. scoreItems 只要「技术文件/技术标/施工组织设计」评审因素，不要商务、报价、业绩、信誉。PDF 表格里的评审因素名称常被拆成多行，请拼回完整名称。不要给 scoreItems.sections 填「保障体系」「主要措施」这类套话。
2. difficulties 必须逐条对应招标文件「重点难点」原文，一条一项，不要合并，也不要省略。
3. 页数上限写进 pageLimit（整数，没有写 0）。
4. 评分项名称里「包括但不限于 X」点名的 X，如果对应某条重难点，那条重难点的 title 直接用 X 原文。
5. siteConstraints、trades、stages、processSystems、buildings、majorWorks 是施工理解：写本工程实际有的单体、专业、阶段、现场约束和工艺，不要编通用房建模板。没有原文就留空。
"""

# 水利事实账。节点工期原文字段仍叫 milestones；结构化节点另用 controlNodes，避免把房建草稿的字符串写坏。
WATER_FACT_KEYS = (
    "regions",
    "regionTotalLength",
    "controlNodes",
    "floodSeason",
    "standardsRefs",
    "projectGrade",
    "structures",
    "siteSurvey",
)

WATER_FACTS_EXTRA = """
本项目专业是水利。在同一个 JSON 里再增加下面字段。没有原文依据就留空，不要编造数字和规范编号：
"regionTotalLength": "招标公告写出的治理总长，保留单位，如 8.85km",
"regions": [{"name": "区段名称", "length": "约3.02km", "mainQuantities": "该区段主要工程量，原文口径"}],
"controlNodes": [{"name": "控制性节点名称，如羊角堰拆建", "window": "时间窗口，如第46天至第65天拆除、第66天至第95天重建", "note": "同时写明的约束，如埋石率20%"}],
"floodSeason": {"spansFlood": false, "diversionMethod": "导流方式，原文有才写", "stopWorkRule": "停工撤离标准，原文有才写"},
"standardsRefs": ["原文出现的规范编号，如 SL/T 223-2025"],
"projectGrade": {"projectLevel": "工程等别，如 Ⅳ等", "structureLevel": "主要建筑物级别，如 4级", "floodStandard": "设计洪水或度汛标准，如 20年一遇", "source": "出处，如 招标文件第X章"},
"structures": [{"name": "构筑物或设备汇总项，如 新建泵站、涵、总装机", "count": "座数或台数，数字", "spec": "容量或规格，如 140kW"}],
"siteSurvey": {"boundaries": "工程四至", "sensitivePoints": [{"name": "学校、水源地、居民点等名称", "kind": "类别", "note": "距离或要求"}], "access": "对外交通", "crsNote": "坐标系或高程系说明"}
spansFlood 仅在工期跨汛期、或原文要求度汛导流时为 true。
projectGrade、structures、siteSurvey 只从招标文本取，招标没写就留空，不要根据规范推算等别，也不要编造坐标、学校和水源名称。
"""

WATER_CHAPTER_SYSTEM = """你是有 20 年经验的水利工程施工总承包企业总工程师，正在为投标编制施工组织设计（技术标）的一个小节。只写水利、灌区、高标准农田、河道、堤防、泵站涵闸、水库塘坝，不要套房建模板。
写作原则：
1. 本节写什么由标题、编写思路和挂到本节的事实决定，不要套通用顺序。施工方法节按本分项的工艺流程、分步施工、质量控制要点写，数字取【本节清单】和给出的账目。
2. 重难点分析要分条，写清工程量、点位分布、地质水文、工期窗口、对灌排或度汛的影响，不要只写一段空话，也不要写措施。
3. 重难点解决措施用（1）（2）（3）（4），每条先写短措施名，再写时限、数量、机械、施工顺序和责任岗位。
4. 保证措施汇总写成表：措施、对应难点、责任岗位、实施时间。
5. 每个工序步骤至少一个「数字＋单位」参数。约束只用文字：不小于、不低于、不超过、不大于、严禁。不要写 ≤、≥、<、>。
6. 控制性节点的日期和天数必须与节点账一致。劳动力和备电写常态与高峰两档，用「由…增至…」。
7. 规范编号只能用账目或本节列出的编号，没有就写「暂无可引用规范」，不要编造。混凝土的强度、抗渗、抗冻成组写，没有的参数写「【待核实】」。
8. 现场勘察只写【勘察资料】里有的内容；缺项写「【待补：xxx】」。严禁编造经纬度、学校和水源地名称。
9. 度汛按「工程等别 → 建筑物级别 → 设计洪水重现期」写依据链，账上没有的环节写「【待核实】」。
10. 高标准农田和灌区写施工期灌排保障、分段施工、临时导流、农忙和临时用地复垦。数量以构筑物账和清单为准。
11. 【施工计划账】里的阶段天数、机械台数、劳动力人数、材料量照抄，全书一致；没有出处的数字写「【待核实】」。
12. 篇幅是上限。可写的事实少就写短，不要凑字；规范和通用工法里已有的做法不要复述。
13. 不依赖公司资料库；禁止编造工程量、业绩、获奖、证书编号和人员姓名。
14. 只输出 Markdown 表格，不要标题、不要表格外的段落、不要代码围栏、不要解释。单元格内换行用 <br>，不要出现竖线 |。
"""

_EXCERPT_KEYS: tuple[tuple[str, int], ...] = (
    ("技术文件评审", 3500),
    ("技术标评审", 3500),
    ("技术文件", 1200),
    ("施工组织设计", 1500),
    ("重点难点", 3500),
    ("危险性较大", 1800),
    ("工程概况", 1500),
    ("项目概况", 1500),
    ("建设地点", 600),
    ("建设规模", 900),
    ("建设内容", 900),
    ("招标范围", 1200),
    ("计划工期", 600),
    ("质量标准", 400),
    ("质量要求", 400),
    ("绿色建筑", 800),
    ("智慧工地", 800),
    ("扬尘", 600),
    ("附表", 1200),
    ("篇幅", 400),
)
EXCERPT_LIMIT = 40000


def tender_excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """按关键词截取招标原文里与施组相关的片段，合并重叠区间后按原文顺序拼接。"""
    corpus = text or ""
    if len(corpus) <= limit:
        return corpus
    spans: list[tuple[int, int]] = []
    for key, size in _EXCERPT_KEYS:
        for i, m in enumerate(re.finditer(re.escape(key), corpus)):
            if i >= 4:
                break
            spans.append((max(0, m.start() - 200), min(len(corpus), m.start() + size)))
    if not spans:
        return corpus[:limit]
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[str] = []
    total = 0
    for a, b in merged:
        piece = corpus[a:b]
        if total + len(piece) > limit:
            piece = piece[: max(0, limit - total)]
        out.append(piece)
        total += len(piece)
        if total >= limit:
            break
    return "\n……\n".join(out)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_json_object(content: str) -> dict:
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


_DIFF_HEAD = re.compile(r"重点难点[：:]\s*(?=1\s*[.．、])")
_DIFF_ITEM = re.compile(r"(?:^|(?<=[\s。；;]))(\d{1,2})[.．、](?!\d)\s*")


def _heuristic_difficulties(text: str) -> list[dict]:
    corpus = text or ""
    for m in _DIFF_HEAD.finditer(corpus):
        chunk = corpus[m.end() : m.end() + 4000]
        stop = re.search(r"[（(][二三四][）)]|危险性较大|五、", chunk)
        if stop:
            chunk = chunk[: stop.start()]
        parts = _DIFF_ITEM.split(chunk)
        items: list[dict] = []
        # split 结果：[前缀, 序号, 正文, 序号, 正文, ...]
        for i in range(1, len(parts) - 1, 2):
            body = _clean(parts[i + 1]).rstrip("。；;")
            if len(body) >= 4:
                items.append({"title": _short_title(body), "text": body[:600]})
        if len(items) >= 2:
            return items[:12]
    return []


def _short_title(text: str, limit: int = 16) -> str:
    clauses = [c.strip() for c in re.split(r"[，,。；;：:]", _clean(text)) if c.strip()]
    for clause in clauses:
        if re.match(r"^(根据|按照|依据|为|经)", clause):
            continue
        t = re.sub(r"^(本项目|本工程|项目)", "", clause).strip()
        if len(t) >= 4:
            return t[:limit]
    return _clean(text)[:limit]


def _standard_codes(text: str, limit: int = 30) -> list[str]:
    from .standard_ingest import _CODE_RE

    codes: list[str] = []
    for match in _CODE_RE.finditer(text or ""):
        head = match.group("head").upper()
        slash_t = "/T" if match.group("t") else ""
        code = f"{head}{slash_t}{match.group('num')}-{match.group('year')}"
        if code not in codes:
            codes.append(code)
    return codes[:limit]


_KM = r"([\d]+(?:\.\d+)?)\s*(?:km|公里|千米)"
_TOTAL_WORDS = ("总长", "河长", "总计", "合计", "共计", "全长")
_REGION_SUFFIX = r"(?:堤|埂|渠|段|线|岸|沟|圩|坝|河)"
_STRUCT_WORDS = "泵站|节制闸|分水闸|水闸|涵闸|涵洞|箱涵|渡槽|倒虹吸|涵|闸|桥|堰"


def _is_total_name(name: str) -> bool:
    return any(word in name for word in _TOTAL_WORDS) or name in {"综合治理", "治理"}


def _heuristic_regions(corpus: str) -> list[dict]:
    """区段账：既认「竹园稞约 3.02km」，也认「左堤 2.919km＋窑头子埂 0.23km」这类堤线写法。"""
    found: list[dict] = []

    def add(name: str, length: str) -> None:
        name = name.strip("约共计总长，、；： ")
        if len(name) < 2 or _is_total_name(name):
            return
        for row in found:
            if row["length"] == f"{length}km" and (row["name"].endswith(name) or name.endswith(row["name"])):
                return
        found.append({"name": name[:20], "length": f"{length}km", "mainQuantities": ""})

    for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9～~\-]{2,20}?)\s*约\s*" + _KM, corpus, re.I):
        add(match.group(1), match.group(2))
    for match in re.finditer(
        r"((?:左|右)?[\u4e00-\u9fa5A-Za-z0-9]{0,6}?" + _REGION_SUFFIX + r")\s*(?:长)?\s*" + _KM, corpus, re.I
    ):
        add(match.group(1), match.group(2))
    return found[:8]


def _heuristic_structures(corpus: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"((?:新建|改建|重建|拆建|新增|加固|排涝|排灌|提水)?(?:" + _STRUCT_WORDS + r"))\s*(?:共)?\s*(\d{1,3})\s*座", corpus
    ):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        rows.append({"name": name, "count": match.group(2), "spec": ""})
        if len(rows) >= 10:
            break
    power = re.search(r"总装机(?:容量|功率)?\s*(?:约)?\s*([\d.]+)\s*(kW|KW|kw|千瓦|MW|万千瓦)", corpus)
    if power:
        rows.append({"name": "总装机", "count": "", "spec": f"{power.group(1)}{power.group(2)}"})
    return rows[:12]


def _heuristic_grade(corpus: str) -> dict:
    grade = {"projectLevel": "", "structureLevel": "", "floodStandard": "", "source": ""}
    m = re.search(r"工程等别[：:为是]?\s*([ⅠⅡⅢⅣⅤ]+|[IV]{1,3}|[一二三四五])\s*等", corpus)
    if m:
        grade["projectLevel"] = f"{m.group(1)}等"
    m = re.search(r"(?:主要)?建筑物级别[：:为是]?\s*([1-5一二三四五])\s*级|([1-5一二三四五])\s*级(?:建筑物|堤防)", corpus)
    if m:
        grade["structureLevel"] = f"{m.group(1) or m.group(2)}级"
    m = re.search(r"(?:设计洪水|防洪标准|度汛标准|防洪)[^。\n]{0,20}?(\d{1,3})\s*年一遇", corpus)
    if m:
        grade["floodStandard"] = f"{m.group(1)}年一遇"
    if any(grade[k] for k in ("projectLevel", "structureLevel", "floodStandard")):
        grade["source"] = "招标文件"
    return grade


def _heuristic_water(text: str) -> dict:
    """水利招标原文里能用规则钉住的账。模型没抽到时用这份补空。"""
    corpus = text or ""
    extra: dict = {}
    total = re.search(r"(?:总长|河长|全长)度?约?\s*[：:为是]?\s*约?\s*" + _KM, corpus, re.I)
    if total:
        extra["regionTotalLength"] = f"{total.group(1)}km"
    regions = _heuristic_regions(corpus)
    if regions:
        extra["regions"] = regions
    structures = _heuristic_structures(corpus)
    if structures:
        extra["structures"] = structures
    grade = _heuristic_grade(corpus)
    if grade["source"]:
        extra["projectGrade"] = grade
    days = re.search(r"(\d{2,4})\s*日历天", corpus)
    spans = bool(re.search(r"汛期|度汛|渡汛|导流", corpus))
    if days and int(days.group(1)) >= 240:
        spans = True
    extra["floodSeason"] = {"spansFlood": spans, "diversionMethod": "", "stopWorkRule": ""}
    nodes: list[dict] = []
    for match in re.finditer(
        r"([\u4e00-\u9fa5]{2,12}(?:堰|坝|闸|桥))[^。\n]{0,24}?(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        corpus,
    ):
        nodes.append({"name": match.group(1), "window": re.sub(r"\s+", "", match.group(2)), "note": ""})
        if len(nodes) >= 8:
            break
    if nodes:
        extra["controlNodes"] = nodes
    codes = _standard_codes(corpus)
    if codes:
        extra["standardsRefs"] = codes
    return extra


def _empty_flood() -> dict:
    return {"spansFlood": False, "diversionMethod": "", "stopWorkRule": ""}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "是", "跨汛"}


def _heuristic_facts(text: str, project_name: str = "", score_rules: list[dict] | None = None, specialty: str = "") -> dict:
    corpus = text or ""
    facts: dict = {"projectName": project_name}
    m = re.search(r"(?:计划)?工期[：:为]?\s*(\d{1,4}\s*(?:日历天|天|个月))", corpus)
    if m:
        facts["duration"] = m.group(1).replace(" ", "")
    m = re.search(r"质量(?:标准|要求)[：:为]?\s*([^\n。；;]{2,40})", corpus)
    if m:
        facts["quality"] = _clean(m.group(1))
    m = re.search(r"建设地点[：:为]?\s*([^\n。；;]{2,60})", corpus)
    if m:
        facts["location"] = _clean(m.group(1))
    m = re.search(r"篇幅[^\n]{0,12}?不超过\s*(\d{1,4})\s*页", corpus)
    if m:
        facts["pageLimit"] = int(m.group(1))
    facts["difficulties"] = _heuristic_difficulties(corpus)
    m = re.search(r"危险性较大的分部分项工程清单[：:]?([\s\S]{0,500})", corpus)
    if m:
        names = re.findall(r"(深基坑|基坑工程|高大模板|模板工程|起重吊装|脚手架|拆除工程|暗挖|幕墙|钢结构|人工挖孔桩)", m.group(1))
        facts["hazards"] = [{"name": n, "text": ""} for n in dict.fromkeys(names)]
    from .bid_kind import booklet_of_source

    items = []
    for rule in score_rules or []:
        if booklet_of_source(str(rule.get("sourceItemId") or ""), str(rule.get("dimension") or "")) != "tech":
            continue
        title = _clean(rule.get("dimension") or rule.get("item") or "")
        if title and title not in {i["title"] for i in items}:
            items.append({"title": title, "weight": str(rule.get("weight") or ""), "points": _clean(rule.get("detail"))[:300]})
    facts["scoreItems"] = items
    if specialty == "水利":
        facts.update(_heuristic_water(corpus))
    return facts


def normalize_facts(data: dict | None) -> dict:
    """前端可编辑后回写，这里统一字段形状。"""
    src = data if isinstance(data, dict) else {}
    out: dict = {k: _clean(src.get(k)) for k in FACT_FIELDS}
    try:
        out["pageLimit"] = max(0, int(src.get("pageLimit") or 0))
    except (TypeError, ValueError):
        out["pageLimit"] = 0

    def rows(key: str, fields: tuple[str, ...]) -> list[dict]:
        result = []
        for item in src.get(key) or []:
            if isinstance(item, str):
                item = {fields[0]: item}
            if not isinstance(item, dict):
                continue
            row = {f: _clean(item.get(f)) for f in fields}
            if row[fields[0]]:
                if key == "scoreItems":
                    row["sections"] = [_clean(s) for s in (item.get("sections") or []) if _clean(s)][:8]
                result.append(row)
        return result

    out["scoreItems"] = rows("scoreItems", ("title", "weight", "points"))
    for row in out["scoreItems"]:
        row["title"] = re.sub(r"\s*[（(]\s*\d+(?:\.\d+)?\s*分\s*[）)]\s*$", "", row["title"]) or row["title"]
    out["difficulties"] = rows("difficulties", ("title", "text"))
    out["extraDifficulties"] = rows("extraDifficulties", ("title", "text"))[:8]
    out["hazards"] = rows("hazards", ("name", "text"))
    out["buildings"] = rows("buildings", ("name", "scale", "structure"))
    out["attachments"] = [_clean(a) for a in (src.get("attachments") or []) if _clean(a)]
    out["majorWorks"] = [_clean(a) for a in (src.get("majorWorks") or []) if _clean(a)][:16]
    out["siteConstraints"] = rows("siteConstraints", ("title", "text"))[:8]
    out["trades"] = [_clean(a) for a in (src.get("trades") or []) if _clean(a)][:12]
    out["stages"] = rows("stages", ("name", "work"))[:8]
    out["processSystems"] = rows("processSystems", ("name", "text"))[:8]
    for row in out["difficulties"] + out["extraDifficulties"]:
        if len(row["title"]) > 18 or not row["title"]:
            row["title"] = _short_title(row["title"] or row["text"])
    out["regionTotalLength"] = _clean(src.get("regionTotalLength"))
    out["regions"] = rows("regions", ("name", "length", "mainQuantities"))[:8]
    out["controlNodes"] = rows("controlNodes", ("name", "window", "note"))[:8]
    flood = src.get("floodSeason") if isinstance(src.get("floodSeason"), dict) else {}
    out["floodSeason"] = {
        "spansFlood": _as_bool(flood.get("spansFlood")),
        "diversionMethod": _clean(flood.get("diversionMethod")),
        "stopWorkRule": _clean(flood.get("stopWorkRule")),
    }
    refs: list[str] = []
    for item in src.get("standardsRefs") or []:
        code = _clean(item)
        if code and code not in refs:
            refs.append(code)
    out["standardsRefs"] = refs[:30]
    grade = src.get("projectGrade") if isinstance(src.get("projectGrade"), dict) else {}
    out["projectGrade"] = {k: _clean(grade.get(k)) for k in ("projectLevel", "structureLevel", "floodStandard", "source")}
    out["structures"] = rows("structures", ("name", "count", "spec"))[:12]
    site = src.get("siteSurvey") if isinstance(src.get("siteSurvey"), dict) else {}
    points = []
    for item in site.get("sensitivePoints") or []:
        if isinstance(item, str):
            item = {"name": item}
        if isinstance(item, dict) and _clean(item.get("name")):
            points.append({k: _clean(item.get(k)) for k in ("name", "kind", "note")})
    out["siteSurvey"] = {
        "boundaries": _clean(site.get("boundaries")),
        "sensitivePoints": points[:12],
        "access": _clean(site.get("access")),
        "crsNote": _clean(site.get("crsNote")),
    }
    return out


def site_gaps(facts: dict | None) -> list[str]:
    """勘察资料里还缺哪几项。正文只写已有的，缺项写待补。"""
    site = normalize_facts(facts)["siteSurvey"]
    gaps = []
    if not site["boundaries"]:
        gaps.append("工程四至")
    if not site["sensitivePoints"]:
        gaps.append("敏感点（学校、水源、居民点）")
    if not site["access"]:
        gaps.append("对外交通")
    if not site["crsNote"]:
        gaps.append("坐标系与高程系")
    return gaps


def extract_facts(
    tender_text: str,
    model_id: str | None,
    *,
    project_name: str = "",
    score_rules: list[dict] | None = None,
    specialty: str = "",
) -> dict:
    """模型抽取为主，规则抽取补空。模型不可用时只用规则抽取，不阻断目录。"""
    base = _heuristic_facts(tender_text, project_name, score_rules, specialty)
    data: dict = {}
    excerpt = tender_excerpt(tender_text)
    system = FACTS_SYSTEM + (WATER_FACTS_EXTRA if specialty == "水利" else "")
    if excerpt.strip():
        try:
            content = chat_complete(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"项目名称：{project_name}\n专业：{specialty or '未标明'}\n\n招标文件节选：\n{excerpt}"},
                ],
                temperature=0.1,
                timeout=180,
            )
            data = _parse_json_object(content)
        except LlmError:
            logger.exception("engineering facts extraction failed")
    merged = dict(base)
    for key, value in data.items():
        if value not in (None, "", [], 0):
            merged[key] = value
    for key in ("projectGrade", "siteSurvey"):
        # 模型给了空壳字典时，不能把规则抽到的内容盖掉
        if isinstance(base.get(key), dict) and isinstance(merged.get(key), dict):
            merged[key] = {**base[key], **{k: v for k, v in merged[key].items() if v not in (None, "", [])}}
    if specialty != "水利":
        for key in WATER_FACT_KEYS:
            merged.pop(key, None)
    if not merged.get("projectName"):
        merged["projectName"] = project_name
    return normalize_facts(merged)


def facts_brief(facts: dict, limit: int = 6000, *, specialty: str = "") -> str:
    """给正文提示词用的工程事实摘要。"""
    f = normalize_facts(facts)
    lines = [f"{FACT_LABELS[k]}：{f[k]}" for k in FACT_FIELDS if f.get(k)]
    if f["pageLimit"]:
        lines.append(f"施组页数上限：{f['pageLimit']} 页")
    if f["majorWorks"]:
        lines.append("主要分部分项：" + "、".join(f["majorWorks"]))
    if f["buildings"]:
        lines.append("单体：" + "；".join(f"{b['name']}（{b['scale']} {b['structure']}）".replace("（ ）", "") for b in f["buildings"]))
    if f["trades"]:
        lines.append("本工程专业：" + "、".join(f["trades"]))
    if f["stages"]:
        lines.append("施工阶段：" + "；".join(f"{s['name']}（{s['work']}）" if s.get("work") else s["name"] for s in f["stages"]))
    if f["siteConstraints"]:
        lines.append("现场约束：")
        lines.extend(f"  - {c['title']}：{c['text']}" for c in f["siteConstraints"])
    if f["processSystems"]:
        lines.append("工艺系统：" + "；".join(f"{p['name']}{('：' + p['text']) if p.get('text') else ''}" for p in f["processSystems"]))
    if f["difficulties"]:
        lines.append("招标点名重难点：")
        lines.extend(f"  {i}. {d['title']}：{d['text']}" for i, d in enumerate(f["difficulties"], 1))
    if f["hazards"]:
        lines.append("危大工程：" + "；".join(f"{h['name']}{('：' + h['text']) if h['text'] else ''}" for h in f["hazards"]))
    if f["scoreItems"]:
        lines.append("技术评分项：" + "；".join(f"{s['title']}（{s['weight']}）" for s in f["scoreItems"]))
    if specialty == "水利":
        if f["regions"] or f["regionTotalLength"]:
            lines.append(f"区段账：{len(f['regions'])} 段，公告总长 {f['regionTotalLength'] or '未给出'}")
        if f["controlNodes"]:
            lines.append(f"控制性节点：{len(f['controlNodes'])} 个")
        flood = f["floodSeason"]
        if flood["spansFlood"] or flood["diversionMethod"] or flood["stopWorkRule"]:
            lines.append(
                "汛期："
                + ("跨汛" if flood["spansFlood"] else "未标明跨汛")
                + (f"，导流 {flood['diversionMethod']}" if flood["diversionMethod"] else "")
                + (f"，停工 {flood['stopWorkRule']}" if flood["stopWorkRule"] else "")
            )
        if f["standardsRefs"]:
            lines.append("依据账规范编号：" + "、".join(f["standardsRefs"][:8]))
        grade = f["projectGrade"]
        if any(grade.values()):
            lines.append(
                "工程等别账：" + "，".join(f"{label}{grade[k]}" for k, label in (("projectLevel", "工程等别 "), ("structureLevel", "建筑物级别 "), ("floodStandard", "设计洪水 ")) if grade[k])
            )
        if f["structures"]:
            lines.append(
                "构筑物账："
                + "；".join(f"{s['name']} {s['count']}{'座' if s['count'] else ''} {s['spec']}".strip() for s in f["structures"])
            )
    return "\n".join(lines)[:limit]


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------

DEFAULT_SCORE_ITEMS = (
    "工程概况及施工部署",
    "施工进度计划及工期保证措施",
    "主要施工方法及技术措施",
    "确保工程质量的技术组织措施",
    "确保安全生产和文明施工的技术组织措施",
    "施工现场总平面布置",
    "劳动力、材料、机械设备配置计划",
)

DEFAULT_ATTACHMENTS = (
    "附表一：拟投入本标段的主要施工设备表",
    "附表二：拟配备本标段的试验和检测仪器设备表",
    "附表三：劳动力计划表",
    "附表四（1）：计划开、竣工日期和施工进度横道图",
    "附表四（2）：计划开、竣工日期和施工进度网络图",
    "附表五：施工总平面图",
    "附表六：临时用地表",
)


def _node(title: str, kind: str = "", children: list | None = None, *, idea: str = "", requirement: str = "", source: str = "") -> dict:
    node = {"title": title, "children": children or [], "engKind": kind, "idea": idea, "requirement": requirement}
    if source:
        node["engSource"] = source
    return node


def _similar(a: str, b: str) -> bool:
    a, b = re.sub(r"(重难点|保障措施|措施)$", "", a), re.sub(r"(重难点|保障措施|措施)$", "", b)
    return bool(a and b) and (a[:5] in b or b[:5] in a)


def _water_blob(facts: dict) -> str:
    return " ".join(
        [str(facts.get(k) or "") for k in ("projectName", "scope", "scale")] + [str(w) for w in facts.get("majorWorks") or []]
    )


def _water_subtypes(facts: dict) -> list[str]:
    from ..data.water_craft import detect_subtypes

    return detect_subtypes(_water_blob(facts))


def _difficulty_children(title: str, text: str, specialty: str) -> list[dict]:
    if specialty == "水利":
        return [
            _node(
                "重难点分析",
                KIND_BOX,
                idea=(
                    f"分条写「{title}」。写清工程量、点位分布、地质水文、工期窗口、对灌排或度汛的影响。"
                    "数字来自清单和招标原文，没有的写【待核实】。不要写措施。"
                ),
                requirement=text,
            ),
            _node(
                "重难点解决措施",
                KIND_BOX,
                idea=(
                    f"针对「{title}」用（1）（2）（3）（4）分条。每条先写短措施名，再写时限、数量、机械、施工顺序和责任岗位。"
                ),
                requirement=text,
            ),
            _node(
                "保证措施汇总",
                KIND_GRID,
                idea=f"用表列出针对「{title}」的措施、对应难点、责任岗位、实施时间。",
                requirement=text,
            ),
        ]
    return [
        _node(
            "重难点分析",
            KIND_BOX,
            idea=(
                f"只写一段，不要分条，不要写措施。先写主管部门或招标人对「{title}」的要求，"
                "再写本工程的具体约束和工程量，最后写顺序或做法不合理时对工期、质量或安全的影响。"
            ),
            requirement=text,
        ),
        _node(
            "重难点解决措施",
            KIND_BOX,
            idea=(
                f"针对「{title}」用（1）（2）（3）（4）分条。每条先写一个短措施名，句号后再写做法："
                "开工后第几天、数量、机械、施工顺序和责任岗位。不要只写态度和口号。"
            ),
            requirement=text,
        ),
    ]


def _difficulty_nodes(facts: dict, named: list[str], specialty: str = "") -> list[dict]:
    """评分项「包括但不限于 X」点名的 X 排在最前，算招标点名；已有相近的重难点就并进去并改用 X 作标题。"""
    tender = list(facts["difficulties"])
    extra = list(facts["extraDifficulties"])
    if specialty == "水利":
        from ..data.water_craft import craft_difficulties

        known = [d["title"] for d in tender + extra] + list(named)
        for cand in craft_difficulties(_water_subtypes(facts), _water_blob(facts)):
            if len(extra) >= 8:
                break
            if any(_similar(cand["title"], t) for t in known):
                continue
            extra.append({"title": cand["title"], "text": cand["text"]})
            known.append(cand["title"])
    front: list[dict] = []
    for x in named:
        if re.search(r"智慧工地|绿色施工", x):
            continue
        hit = next((pool for pool in (tender, extra) for d in pool if _similar(d["title"], x)), None)
        if hit is not None:
            d = next(d for d in hit if _similar(d["title"], x))
            hit.remove(d)
            front.append({"title": x, "text": d.get("text") or f"招标评分项点名：{x}"})
        else:
            front.append({"title": x, "text": f"招标评分项点名：{x}"})
    rows: list[tuple[dict, str]] = [(d, SOURCE_TENDER) for d in front + tender]
    rows.extend((d, SOURCE_EXTRA) for d in extra)
    out = []
    for d, source in rows:
        text = d.get("text") or ""
        out.append(
            _node(
                d["title"],
                KIND_GROUP,
                _difficulty_children(d["title"], text, specialty),
                requirement=text,
                source=source,
            )
        )
    return out


def _themes(title: str, specialty: str = "") -> list[str]:
    t = title
    found = []
    rules = (
        ("difficulty", r"重点|难点|危大|危险性较大"),
        ("overview", r"工程概况|施工部署|总体部署"),
        ("schedule", r"进度计划|施工进度|工期计划"),
        ("method", r"施工方案|施工方法|技术措施|施工工艺|主要施工|施工组织设计"),
        ("guarantee", r"工期|质量|安全|文明|环保|环境保护"),
        ("resource", r"人、材、机|人材机|劳动力|材料|机械|设备配置|资源配置"),
        ("layout", r"平面布置|总平面"),
        ("tech", r"新技术|新工艺|新材料|四新"),
        ("season", r"季节|雨季|冬季|夏季|台风"),
        ("emergency", r"应急"),
        ("coordination", r"协调|配合|总包管理|总承包管理"),
    )
    for name, pattern in rules:
        if re.search(pattern, t):
            found.append(name)
    if specialty == "水利" and re.search(r"度汛|导流|渡汛", t):
        found.append("flood")
    if "flood" in found:
        found = [name for name in found if name != "season"]
    return found


def _infer_water_works(facts: dict) -> list[str]:
    blob = f"{facts.get('scope') or ''} {facts.get('scale') or ''}"
    found = []
    for name, pattern in (
        ("护坡护岸", r"护坡|护岸"),
        ("河道清淤", r"清淤"),
        ("防汛道路", r"防汛道路|道路"),
        ("堰坝拆建加固", r"堰坝|拆建堰|堰"),
    ):
        if re.search(pattern, blob):
            found.append(name)
    return found


def _water_process_idea(title: str) -> str:
    if "清淤" in title:
        return "围堰截流 → 抽排水 → 干地开挖 → 分段推进 → 余土外运。每步挂一个带单位的参数，并引用依据账里的一条规范编号。"
    if re.search(r"护坡|护岸|挡墙", title):
        return "基面处理 → 垫层 → 砌筑或安装 → 勾缝或充填 → 验收。每步挂参数，约束用文字表述。"
    if re.search(r"堰|坝", title):
        return "按节点账写拆除窗口、基坑、重建和过水验收。天数不得另起一套。"
    return "按工序写流程，每步至少一个带单位的参数，并挂一条依据账里的规范编号。没有编号就写「暂无可引用规范」。"


def _water_method_nodes(facts: dict) -> list[dict]:
    nodes: list[dict] = []
    for region in facts.get("regions") or []:
        qty = region.get("mainQuantities") or "主要工程量按清单，对不上就写【待核实】"
        nodes.append(
            _node(
                f"{region['name']}施工部署",
                KIND_PAIRS,
                idea=f"区段长度 {region.get('length') or '【待核实】'}，{qty}。施工顺序和工程量与区段账一致，不要改数字。",
                requirement=qty,
            )
        )
    from ..data.water_craft import craft_works

    mine = [str(w) for w in facts.get("majorWorks") or []]
    works: list[tuple[str, str]] = []  # (节标题, 编写思路)
    for work in mine:
        title = work if work.endswith("施工方法") else f"{work}施工方法"
        works.append((title, f"{work}：{_water_process_idea(work)}"))
    subtypes = _water_subtypes(facts)
    if subtypes:
        for item in craft_works(subtypes, _water_blob(facts)):
            if any(_similar(item["name"], w) or item["name"] in w for w in mine):
                continue
            works.append((item["title"], f"{item['name']}：{item['idea']}"))
    elif not mine:
        for work in _infer_water_works(facts):
            works.append((f"{work}施工方法", f"{work}：{_water_process_idea(work)}"))
    for title, idea in works[:10]:
        nodes.append(_node(title, KIND_PAIRS, idea=idea))
    if re.search(r"土方|开挖|填筑|清淤|堤|回填|疏浚", _water_blob(facts)):
        nodes.append(
            _node(
                "土方平衡与调配",
                KIND_PAIRS,
                idea="写挖方、填方、借方、弃方的数量关系，土源和余土去向，运距，回填压实度。数量取区段账和设计参数账，对不上写【待核实】。",
            )
        )
    return nodes


def _grade_line(facts: dict) -> str:
    grade = facts.get("projectGrade") or {}
    parts = [
        f"工程等别 {grade.get('projectLevel')}" if grade.get("projectLevel") else "工程等别【待核实】",
        f"建筑物级别 {grade.get('structureLevel')}" if grade.get("structureLevel") else "建筑物级别【待核实】",
        f"设计洪水 {grade.get('floodStandard')}" if grade.get("floodStandard") else "设计洪水重现期【待核实】",
    ]
    return "，".join(parts)


def _flood_nodes(facts: dict) -> list[dict]:
    flood = facts.get("floodSeason") or _empty_flood()
    stop = flood.get("stopWorkRule") or "【待核实：停工撤离标准，招标或设计文件没给出就不要写数字】"
    diversion = flood.get("diversionMethod") or "分段分期导流"
    return [
        _node(
            "度汛标准与依据",
            KIND_PAIRS,
            idea=f"按「工程等别 → 建筑物级别 → 设计洪水重现期」写依据链。账上现有：{_grade_line(facts)}。没有的环节写【待核实】，不要用规范推算。",
        ),
        _node(
            "分段分期导流",
            KIND_PAIRS,
            idea=f"按区段分期，不全面开花。导流方式：{diversion}。先围堰、后抽排、再干地作业，清淤锚在汛前控制节点上。",
        ),
        _node(
            "围堰施工与拆除",
            KIND_PAIRS,
            idea="围堰型式、断面尺寸、填筑材料、防渗做法，汛前达到的挡水标准，拆除时机和余料去向。尺寸写带单位的数字，没有设计值就写【待核实】。",
        ),
        _node(
            "基坑排水与降水",
            KIND_PAIRS,
            idea="初期排水和经常性排水的设备配置、排水量估算依据、集水井布置，降水方式和监测。备用泵和备电写常态与高峰两档。",
        ),
        _node(
            "汛期应急预案",
            KIND_PAIRS,
            idea=f"写停工撤离标准（{stop}）、基坑排水设备冗余、汛后复工检查清单。",
        ),
        _node(
            "冬雨季施工参数",
            KIND_PAIRS,
            idea="汛期与不良天气下的工期协调：哪些工序停、哪些工序抢，节点如何顺延。混凝土浇筑避开低温时段，雨后基面处理写清工艺参数。约束用文字，不用小于等于符号。",
        ),
    ]


def _water_smart_node(facts: dict) -> dict | None:
    site = facts.get("smartSite") or ""
    if not site:
        return None
    nodes = facts.get("controlNodes") or []
    if not nodes and not re.search(r"巡检|BIM|无人机", site):
        return None
    names = "、".join(n["name"] for n in nodes[:3]) or "巡检场景"
    return _node(
        "智慧工地管理机制",
        KIND_PAIRS,
        idea=(
            f"只写能挂到「{names}」的做法，不要罗列智慧工地名词。每个应用写五项：数据来源、采集频次、"
            f"预警阈值（带单位的数字）、触发动作、责任岗位。招标要求：{site}"
        ),
        requirement=site,
    )


def _water_survey_node(facts: dict) -> dict:
    return _node(
        "现场勘察与外部条件",
        KIND_PAIRS,
        idea="按勘察资料账写四至、敏感点、对外交通、坐标系说明。账上缺的项逐条写「【待补：xxx】」，严禁编造坐标、学校和水源地名称。",
        requirement=str(facts.get("environment") or ""),
    )


def _water_acceptance_node(facts: dict) -> dict:
    from ..data.water_craft import acceptance_hint

    hint = acceptance_hint(_water_subtypes(facts))
    return _node(
        "质量验收与评定",
        KIND_PAIRS,
        idea=(
            "按「单元工程 → 分部工程 → 单位工程」写验收评定：划分原则、主控项目和一般项目、原材料与中间产品复试、"
            "评定标准与合格率要求。" + (f"划分参考：{hint}" if hint else "")
        ),
    )


def _water_monitor_node(facts: dict) -> dict | None:
    from ..data.water_craft import craft_monitors

    items = craft_monitors(_water_subtypes(facts))
    if not items:
        return None
    return _node(
        "工程观测与监测",
        KIND_GRID,
        idea=f"列出观测设施和监测项目：{'、'.join(items)}。每项写监测方式、频率、预警值和记录要求；水保、环保监测另列。",
    )


def _water_env_node(facts: dict) -> dict:
    return _node(
        "水土保持与环境保护措施",
        KIND_PAIRS,
        idea="水源地和敏感点保护、表土剥离与回覆、弃土去向和运距、沉砂池与泥浆处置、施工人员健康与防疫。数量取账，没有就写【待核实】。",
    )


def _named_items(title: str) -> list[str]:
    m = re.search(r"包括但不限于([^）)]+)", title or "")
    if not m:
        return []
    items = [re.sub(r"等(内容|方面|措施)?$", "", p.strip("：:，, ")) for p in re.split(r"[、；;]", m.group(1))]
    return [p for p in items if len(p) >= 4]


def _guarantee_nodes(title: str, facts: dict) -> list[dict]:
    out = []
    pairs = (
        (r"工期|进度", "确保工期的保障体系与措施", "工期目标、进度计划编制与控制、关键节点保证、赶工与纠偏措施"),
        (r"质量", "确保质量的保障体系与措施", "质量目标、质量保证体系、关键工序质量控制、检验试验、质量通病防治、成品保护"),
        (r"安全", "确保安全生产的管理体系与措施", "安全目标、安全管理体系与责任制、安全教育与交底、专项安全措施、隐患排查与应急"),
        (r"文明", "确保文明施工的管理体系与措施", "文明施工目标、现场标准化、扬尘防治、噪声与污水控制、农民工管理"),
        (r"环保|环境保护", "环境保护措施", "扬尘、噪声、污水、固废、光污染控制措施"),
    )
    for pattern, sub, idea in pairs:
        if re.search(pattern, title):
            out.append(_node(sub, KIND_PAIRS, idea=f"按体系和措施展开：{idea}。"))
    if not re.search(r"安全|文明|绿色|智慧|环保|环境保护", title):
        return out
    if facts.get("smartSite"):
        out.append(
            _node(
                f"智慧工地安全管理系统（{facts['smartSite'][:12]}）" if len(facts["smartSite"]) <= 12 else "智慧工地安全管理系统",
                KIND_GRID,
                idea="按招标要求的智慧工地等级列出子系统、功能和数据对接平台。",
                requirement=facts["smartSite"],
            )
        )
    if facts.get("greenBuilding"):
        out.append(
            _node(
                f"绿色施工过程监控（{facts['greenBuilding']}）" if len(facts["greenBuilding"]) <= 8 else "绿色施工过程监控",
                KIND_GRID,
                idea="落实四节一环保，列出监测项目、监测方式、频率和记录要求。",
                requirement=facts["greenBuilding"],
            )
        )
    return out


def _theme_nodes(theme: str, title: str, facts: dict, specialty: str = "") -> list[dict]:
    if theme == "flood":
        return _flood_nodes(facts)
    if theme == "difficulty":
        nodes = []
        if not re.search(r"工程概况|施工部署", title):
            if specialty == "水利":
                overview = [
                    _node("工程概况", KIND_PAIRS, idea="项目名称、建设地点、治理河长、招标范围、工期、质量标准。河长用区段账的总长。"),
                ]
                if facts.get("regions"):
                    overview.append(
                        _node("治理区段", KIND_GRID, idea="按区段账列出名称、长度和主要工程量。各段长度相加等于公告总长。")
                    )
                nodes.append(_node("工程概述", KIND_GROUP, overview))
            else:
                nodes.append(
                    _node(
                        "工程概述",
                        KIND_GROUP,
                        [
                            _node("工程概况", KIND_PAIRS, idea="项目名称、建设地点、建设内容、招标范围、工期、质量标准等。"),
                            _node("主要建（构）筑物概况", KIND_GRID, idea="列出各单体的规模、层数、结构形式和基础形式。"),
                        ],
                    )
                )
            nodes.append(
                _node(
                    "施工总体部署",
                    KIND_GROUP,
                    [
                        _node("总体管理目标", KIND_PAIRS, idea="质量、工期、安全、文明施工、环保等目标。"),
                        _node("项目组织机构", KIND_PAIRS, idea="项目管理机构设置原则、岗位职责、管理层级。"),
                        _water_survey_node(facts)
                        if specialty == "水利"
                        else _node("工地现场勘察", KIND_PAIRS, idea="场地、交通、水电、周边环境和障碍物情况及应对。"),
                        _node("施工总平面布置", KIND_PAIRS, idea="分阶段平面布置、临时设施、临时道路、水电和排水。"),
                        _node("总体施工部署", KIND_PAIRS, idea="施工区段划分、施工顺序、流水组织和阶段划分。"),
                    ],
                )
            )
        nodes.append(_node("重点难点及危大工程保障体系", KIND_PAIRS, idea="成立重难点及危大工程领导小组，写清组织、职责、制度和运行流程。"))
        nodes.append(
            _node(
                "工程重点、难点及对应保障措施",
                KIND_GROUP,
                _difficulty_nodes(facts, _named_items(title), specialty),
            )
        )
        if facts["hazards"] or re.search(r"危大|危险性较大", title):
            hz = "；".join(h["name"] for h in facts["hazards"])
            nodes.append(
                _node(
                    "危大工程及对应保障措施",
                    KIND_GROUP,
                    [
                        _node("危大工程清单", KIND_GRID, idea="列出危大和超危大工程、判定标准、对应部位。", requirement=hz),
                        _node("危大工程保证措施", KIND_PAIRS, idea="全流程管控（方案、论证、交底、验收、监测）和分项保证措施。", requirement=hz),
                    ],
                )
            )
        return nodes
    if theme == "overview":
        nodes = [_node("工程概况", KIND_PAIRS, idea="项目名称、建设地点、建设内容、招标范围、工期、质量标准等。")]
        if specialty == "水利":
            nodes.append(_water_survey_node(facts))
        nodes.append(_node("施工总体部署", KIND_PAIRS, idea="管理目标、组织机构、施工区段划分、施工顺序和阶段划分。"))
        return nodes
    if theme == "schedule":
        return [
            _node("施工进度计划", KIND_PAIRS, idea="总工期、阶段工期、关键线路和里程碑节点。"),
            _node("关键节点控制措施", KIND_PAIRS, idea="各节点的资源保证、纠偏和预警措施。"),
        ]
    if theme == "method":
        if specialty == "水利" and re.search(r"施工方案|施工方法|施工工艺|主要施工", title):
            water_nodes = _water_method_nodes(facts)
            if water_nodes:
                return water_nodes
        works = facts["majorWorks"][:10]
        if works:
            return [_node(f"{w}施工方法", KIND_PAIRS, idea=f"{w}的工艺流程、施工要点、质量控制和安全措施。") for w in works]
        return [
            _node("施工工艺流程", KIND_PAIRS, idea="主要分部分项工程的施工工艺流程。"),
            _node("主要施工方法", KIND_PAIRS, idea="各分部分项工程的施工方法和技术要点。"),
            _node("技术保证措施", KIND_PAIRS, idea="技术管理制度、交底、检验与试验。"),
        ]
    if theme == "guarantee":
        nodes = _guarantee_nodes(title, facts)
        if specialty != "水利":
            return nodes
        kept = []
        for node in nodes:
            if node["title"].startswith("绿色施工") or node["title"].startswith("智慧工地"):
                continue
            if node["title"] == "环境保护措施":
                continue
            idea = node["idea"].replace("扬尘防治、", "").replace("扬尘、", "")
            kept.append({**node, "idea": idea})
        if re.search(r"质量", title):
            kept.append(_water_acceptance_node(facts))
            monitor = _water_monitor_node(facts)
            if monitor:
                kept.append(monitor)
        if re.search(r"文明|环保|环境保护", title):
            kept.append(_water_env_node(facts))
        smart = _water_smart_node(facts)
        if smart:
            kept.append(smart)
        return kept
    if theme == "resource" and specialty == "水利":
        return [
            _node("确保人、材、机的保障体系", KIND_PAIRS, idea="以项目经理为总负责。人数和设备写常态与高峰两档，并写明高峰对应哪个控制节点。"),
            _node("劳动力的保障措施", KIND_PAIRS, idea="不要写死一个人数。写成弹性区间，例如普工由 65 人增至 90 人，并说明高峰出现在清淤或拆堰阶段。"),
            _node("主要材料保障措施", KIND_PAIRS, idea="材料投入计划、采购与供应、进场检验、储存与调配。数量与区段账同量级。"),
            _node("施工机械、设备保障措施", KIND_PAIRS, idea="机械配置写进场计划。备电写柴油发电机容量的常态和高峰两档。"),
        ]
    if theme == "resource":
        return [
            _node("确保人、材、机的保障体系", KIND_PAIRS, idea="以项目经理为总负责的人材机三级保障体系与职责。"),
            _node("劳动力的保障措施", KIND_PAIRS, idea="劳动力来源、进退场计划、高峰期保证、农民工工资保障、实名制。"),
            _node("主要材料保障措施", KIND_PAIRS, idea="材料投入计划、采购与供应、进场检验、储存与调配。"),
            _node("施工机械、设备保障措施", KIND_PAIRS, idea="机械配置、进场计划、三定制度、维修保养和备用。"),
        ]
    if theme == "layout":
        return [
            _node("施工总平面布置原则", KIND_PAIRS, idea="布置原则和依据。"),
            _node("分阶段平面布置", KIND_PAIRS, idea="各施工阶段平面布置和交通组织。"),
            _node("临时设施布置", KIND_GRID, idea="临时设施名称、面积、位置和使用时间。"),
        ]
    if theme == "tech":
        return [_node("拟采用的新技术、新工艺", KIND_GRID, idea="列出新技术名称、应用部位和效果。")]
    if theme == "season":
        return [
            _node("雨季施工措施", KIND_PAIRS, idea="排水、防雷、材料防护和主要工序措施。"),
            _node("冬季与高温施工措施", KIND_PAIRS, idea="混凝土养护、防冻、防暑降温措施。"),
        ]
    if theme == "emergency":
        return [
            _node("应急组织机构", KIND_PAIRS, idea="应急领导小组及职责。"),
            _node("应急预案与处置", KIND_PAIRS, idea="主要风险的应急预案、处置流程、应急物资和演练。"),
        ]
    if theme == "coordination":
        return [_node("总承包管理与协调配合", KIND_PAIRS, idea="与建设、监理、设计、专业分包和周边单位的协调机制。")]
    return []


def _score_chapter(item: dict, facts: dict, specialty: str = "") -> dict:
    title = item["title"]
    children: list[dict] = []
    seen: set[str] = set()
    for theme in _themes(title, specialty):
        for node in _theme_nodes(theme, title, facts, specialty):
            if node["title"] not in seen:
                seen.add(node["title"])
                children.append(node)
    covered = " ".join(_all_titles(children))
    named = [
        _node(x, KIND_PAIRS, idea=f"评分项点名的「{x}」，单独成节写清措施。", source=SOURCE_TENDER)
        for x in _named_items(title)
        if x[:6] not in covered
    ]
    at = next((i for i, c in enumerate(children) if c["engKind"] == KIND_GRID), len(children))
    children[at:at] = named
    sections = [s for s in (item.get("sections") or []) if s and not re.search(r"保障体系|主要措施|检查与考核", s)]
    if not sections and len(children) < 3:
        sections = [s["name"] for s in facts.get("stages") or [] if s.get("name")]
        sections += [c["title"] for c in facts.get("siteConstraints") or [] if c.get("title")]
        sections += [p["name"] for p in facts.get("processSystems") or [] if p.get("name")]
    if len(children) < 3:
        covered = " ".join(_all_titles(children))
        children += [
            _node(s, KIND_PAIRS, idea=f"按本工程实际写「{s}」，不要空对空解释章名。")
            for s in sections
            if s[:4] not in covered
        ][:6]
    return _node(title, KIND_GROUP, children, requirement=item.get("points") or "")


def _all_titles(nodes: list[dict]) -> list[str]:
    out = []
    for n in nodes:
        out.append(n["title"])
        out.extend(_all_titles(n.get("children") or []))
    return out


def _attachment_kind(title: str) -> str:
    return KIND_FIGURE if re.search(r"横道图|网络图|平面图|布置图", title) else KIND_GRID


def build_chapters(facts: dict, specialty: str = "") -> list[dict]:
    f = normalize_facts(facts)
    items = f["scoreItems"] or [{"title": t, "weight": "", "points": ""} for t in DEFAULT_SCORE_ITEMS]
    chapters = [
        _node(
            "编制说明",
            KIND_GROUP,
            [
                _node("编制依据", KIND_BOX, idea="招标文件与补遗、图纸与清单、现场踏勘，国家、行业和地方现行规范标准（写出编号）。"),
                _node("编制原则", KIND_BOX, idea="响应招标要求、确保工期质量安全、科学组织、绿色施工等原则。"),
            ],
        )
    ]
    once: set[str] = set()
    for item in items:
        chapter = _score_chapter(item, f, specialty)
        kept = []
        for child in chapter["children"]:
            key = next(
                (k for k in ("智慧工地", "绿色施工过程监控", "水土保持与环境保护", "质量验收与评定", "工程观测与监测") if child["title"].startswith(k)),
                "",
            )
            if key and key in once:
                continue
            once.add(key)
            kept.append(child)
        chapter["children"] = kept
        chapters.append(chapter)
    titles_now = _all_titles(chapters)
    if specialty == "水利" and not any(title.endswith("施工方法") or title == "土方平衡与调配" for title in titles_now):
        methods = _water_method_nodes(f)
        if methods:
            chapters.append(_node("主要施工方法及技术措施", KIND_GROUP, methods))
    if specialty == "水利" and not any(re.search(r"度汛|导流", chapter["title"]) for chapter in chapters):
        chapters.append(_node("度汛、导流与冬雨季施工", KIND_GROUP, _flood_nodes(f)))
    if specialty == "水利" and re.search(r"环保|水保|弃土|表土|水源|沉砂", _water_blob(f)):
        if not any("水土保持" in title for title in _all_titles(chapters)):
            chapters.append(_node("水土保持与环境保护", KIND_GROUP, [_water_env_node(f)]))
    attachments = f["attachments"] or list(DEFAULT_ATTACHMENTS)
    chapters.append(
        _node(
            "附件",
            KIND_GROUP,
            [_node(a, _attachment_kind(a), idea="按施组格式附表填写。") for a in attachments],
        )
    )
    return chapters


def flatten_chapters(chapters: list[dict]) -> list[dict]:
    """转成撰写工作台的扁平目录节点。标题保持原文，不走通用的短标题压缩。"""
    from .e_writer import _format_outline_num

    nodes: list[dict] = []

    def add(item: dict, node_id: str, num: str, parent_id: str | None, depth: int) -> None:
        kids = item.get("children") or []
        idea = item.get("idea") or ""
        node = {
            "id": node_id,
            "num": num,
            "title": item["title"],
            "parentId": parent_id,
            "expanded": depth < 3,
            "weight": 0,
            "dimension": None,
            "idea": idea,
            "aiIdea": idea,
            "optimized": False,
            "status": "待生成",
            "words": 0,
            "aiRounds": 0,
            "sourceIndex": None,
            "part": "tech",
            "requirement": item.get("requirement") or "",
            "engKind": item.get("engKind") or (KIND_GROUP if kids else KIND_PAIRS),
        }
        if item.get("engSource"):
            node["engSource"] = item["engSource"]
        nodes.append(node)
        for j, sub in enumerate(kids, start=1):
            add(sub, f"{node_id}-{j}", _format_outline_num(depth + 1, j, num), node_id, depth + 1)

    for i, ch in enumerate(chapters, start=1):
        add(ch, f"o-{i}", _format_outline_num(0, i, ""), None, 0)
    return nodes


def assign_section_kinds(chapters: list[dict]) -> None:
    """智能体编的目录没有表式标记，按有无下级和标题推断一个，正文才知道写框表还是数据表。"""
    for item in chapters:
        if not isinstance(item, dict):
            continue
        kids = [kid for kid in (item.get("children") or []) if isinstance(kid, dict)]
        if kids:
            item["engKind"] = KIND_GROUP
            assign_section_kinds(kids)
        elif not item.get("engKind"):
            item["engKind"] = section_kind({"title": item.get("title") or ""})


def outline_from_markdown(markdown: str, facts: dict, specialty: str = "") -> list[dict]:
    """把智能体写的目录 Markdown 转成施组目录节点。标题保持原文，不压短。

    解析不出标题时返回空列表，由调用方决定是否回退确定性骨架。
    """
    from .e_writer import _markdown_to_chapters

    chapters = [item for item in _markdown_to_chapters(markdown or "", compact=False) if isinstance(item, dict)]
    if not chapters:
        return []
    assign_section_kinds(chapters)
    nodes = flatten_chapters(chapters)
    del facts, specialty  # 事实账只作为撰写输入，不参与目录结构
    return nodes


def outline_coverage(facts: dict, specialty: str = "") -> dict:
    """目录生成后的覆盖报告。智能体路径和确定性骨架共用。"""
    f = normalize_facts(facts)
    report = {
        "engineering": True,
        "scoreItems": len(f["scoreItems"]),
        "difficulties": len(f["difficulties"]),
        "extraDifficulties": len(f["extraDifficulties"]),
        "hazards": len(f["hazards"]),
        "defaultSkeleton": not f["scoreItems"],
        "specialty": specialty,
    }
    if specialty == "水利":
        from ..data.water_craft import subtype_labels

        report["water"] = True
        report["regions"] = len(f["regions"])
        report["controlNodes"] = len(f["controlNodes"])
        report["spansFlood"] = bool(f["floodSeason"]["spansFlood"])
        report["subtypes"] = subtype_labels(_water_subtypes(f))
        report["siteGaps"] = site_gaps(f)
        report["structures"] = len(f["structures"])
    return report


def outline_problems(nodes: list[dict], facts: dict, specialty: str = "") -> list[str]:
    """目录编完的确定性核对：评分项、招标点名的重难点、要求的附表有没有对应章节。

    只报问题，不改写智能体编的目录。
    """
    f = normalize_facts(facts)
    titles = [str(node.get("title") or "") for node in nodes if isinstance(node, dict)]
    blob = " ".join(titles)
    problems: list[str] = []
    for item in f["scoreItems"]:
        name = item["title"]
        if not name:
            continue
        if not any(_similar(name, title) or name[:8] in title for title in titles):
            problems.append(f"技术评分项「{name[:30]}」没有对应章节，请按评分项原文补一章")
    for item in f["difficulties"]:
        name = item["title"]
        if name and not any(_similar(name, title) for title in titles):
            problems.append(f"招标点名的重难点「{name}」没有对应章节")
    for name in f["attachments"]:
        core = re.sub(r"^附表[一二三四五六七八九十\d]*[（(]?\d*[）)]?[：:]\s*", "", name)
        if core and core[:6] not in blob:
            problems.append(f"招标要求的附表「{name[:30]}」没有对应节点")
    if specialty == "水利":
        if f["floodSeason"]["spansFlood"] and not re.search(r"度汛|导流|渡汛", blob):
            problems.append("本工程跨汛期，目录里没有度汛或导流章节")
        if not re.search(r"施工方法|施工工艺", blob):
            problems.append("目录里没有主要施工方法章节")
    return problems[:20]


def generate_outline(facts: dict, report: dict | None = None, specialty: str = "") -> list[dict]:
    chapters = build_chapters(facts, specialty)
    nodes = flatten_chapters(chapters)
    if report is not None:
        report.clear()
        report.update(outline_coverage(facts, specialty))
    return nodes


# ---------------------------------------------------------------------------
# 正文
# ---------------------------------------------------------------------------

GRID_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"施工设备表|主要施工设备|机械设备表", ("序号", "设备名称", "型号规格", "数量", "国别产地", "制造年份", "额定功率（kW）", "生产能力", "用于施工部位")),
    (r"试验和检测|检测仪器|试验仪器", ("序号", "仪器设备名称", "型号规格", "数量", "国别产地", "制造年份", "已使用台时数", "用途", "备注")),
    (r"劳动力计划", ("工种", "按施工阶段（季度）分列投入人数……", "合计")),
    (r"临时用地", ("用途", "面积（平方米）", "位置", "需用时间")),
    (r"临时设施", ("临时设施名称", "面积（平方米）", "位置", "使用时间")),
    (r"危大工程清单", ("危大工程", "判定范围", "对应部位", "专项方案与论证")),
    (r"建（构）筑物|建筑物", ("序号", "名称", "规模（面积/高度/层数）", "结构形式", "基础形式", "备注")),
    (r"智慧工地", ("子系统", "功能", "对接/上传")),
    (r"绿色施工|监控|监测", ("监测项目", "监测方式", "监测频率", "记录要求")),
    (r"材料", ("序号", "材料名称", "规格型号", "单位", "数量", "进场时间", "供应方式")),
    (r"新技术", ("序号", "技术名称", "应用部位", "预期效果")),
    (r"保证措施汇总", ("序号", "保证措施", "对应难点", "责任岗位", "实施时间")),
)

ENG_CHAPTER_SYSTEM = """你是有 20 年经验的施工总承包企业总工程师，正在为投标编制施工组织设计（技术标）的一个小节。
写作原则：
1. 本节写什么由【本节标题】【编写思路】和挂到本节的事实决定。不要套「依据、目标、组织、措施、检查」的通用顺序，不要把上级章名再解释一遍。
2. 数字只能来自【工程事实】【本节清单】【施工计划账】【招标原文】。施工计划账里的阶段天数、机械台数、劳动力人数、材料量照抄，全书一致。没有出处的写「【待核实：说明】」。
3. 措施要能落地：写清本工程的部位、做法、时间节点、数量、机械和责任岗位。国家和地方规范、通用工法里已有的做法不要复述，只写本工程怎么做。
4. 规范编号只能用【可以引用的规范条文】或招标原文里出现的编号，没有就不写编号。
5. 篇幅是上限。可写的事实少就写短，不要凑字，不要写态度和口号。
6. 不依赖任何公司资料库；禁止编造工程量、业绩、获奖、证书编号和人员姓名。
7. 只输出 Markdown 表格，不要标题、不要表格外的段落、不要代码围栏、不要解释。
8. 单元格内换行用 <br>，单元格内不要出现竖线 |。分条写成（1）（2）（3）或①②③。
9. 与同级小节不要重复，只写本小节的内容。
"""

_FORMAT_HINT = {
    KIND_BOX: "写成一格文字框：只有一列的表格，表头行就是正文本身，下面紧跟一行 | --- |，不要再加行。例：\n| （1）……<br>（2）…… |\n| --- |",
    KIND_PAIRS: "写成两列表格「项目 | 具体内容」：左列是本节要讲的具体事项（工序、部位、措施名），不要用「目标」「组织保证」「检查考核」这类通用标签；右列写本工程的做法和数字；行数按实际事项定，不超过 10 行。",
    KIND_FIGURE: "这是图表附件。输出一个两列表格：| 图表名称 | 说明 |，说明里写清本图应表达的内容（关键线路、节点工期或分区布置），并注明「请插入专业软件绘制的图」。",
}


def section_kind(node: dict) -> str:
    kind = str(node.get("engKind") or "")
    if kind:
        return kind
    title = str(node.get("title") or "")
    if re.search(r"分析|依据|原则|解决措施", title):
        return KIND_BOX
    if re.search(r"横道图|网络图|平面图", title):
        return KIND_FIGURE
    if re.search(r"清单|附表|一览|计划表|设备表", title):
        return KIND_GRID
    return KIND_PAIRS


def grid_columns(title: str) -> tuple[str, ...]:
    for pattern, cols in GRID_COLUMNS:
        if re.search(pattern, title or ""):
            return cols
    return ("序号", "项目", "内容", "备注")


def format_hint(node: dict, specialty: str = "") -> str:
    kind = section_kind(node)
    title = str(node.get("title") or "")
    if title == "重难点分析":
        if specialty == "水利":
            return (
                "写成一格文字框：只有一列的表格，表头行就是正文本身，下面紧跟一行 | --- |。"
                "正文分条写（1）（2）（3），条与条之间用 <br>。写清工程量、点位分布、地质水文、工期窗口、对灌排或度汛的影响。"
                "数字来自清单和招标原文，没有的写【待核实】。不要写措施。"
            )
        return (
            "写成一格文字框：只有一列的表格，表头行就是正文本身，下面紧跟一行 | --- |。"
            "正文只写一段，不要分条，不要写措施。"
            "先写行业主管部门或招标人的要求，再写本工程这项难点的具体约束和工程量，"
            "最后写顺序或做法不合理时对工期、质量或安全的影响。"
        )
    if title == "重难点解决措施":
        return (
            "写成一格文字框：只有一列的表格，表头行就是正文本身，下面紧跟一行 | --- |。"
            "正文用（1）（2）（3）（4）分条，条与条之间用 <br>。"
            "每条先写一个短措施名，句号后写做法：开工后第几天、数量、机械、施工顺序和责任岗位。"
            "不要只写态度和口号。数字用本工程事实，没有的写【待核实】。"
        )
    if specialty == "水利" and title == "保证措施汇总":
        return (
            "写成多列数据表，表头用：| 序号 | 保证措施 | 对应难点 | 责任岗位 | 实施时间 |。"
            "按本难点列 4～8 行，措施要能对应分析里的条，时间用第几天或月份。"
        )
    if specialty == "水利" and kind == KIND_FIGURE:
        return (
            "这是图表附件。输出两列表格：| 图表名称 | 说明 |。"
            "说明列先写 200～300 字文字摘要，写清关键线路、总时差为零的工作、节点工期或分区布置原则，"
            "再注明「请插入专业软件绘制的图」。不能只有一句插图说明。"
        )
    if kind == KIND_GRID:
        cols = grid_columns(title)
        extra = ""
        if "劳动力" in title:
            extra = "按计划工期把施工阶段（季度）展开成列，列出管理人员和各工种人数，末行合计。"
            if specialty == "水利":
                extra += "人数写常态和高峰两档，用「由…人增至…人」，不要只写一个死数字。"
        if re.search(r"劳动力|机械|设备|材料|物资", title):
            extra += "人数、台数、材料量照抄【施工计划账】，账上没有的写【待核实】。"
        return (
            "写成多列数据表，表头用：| " + " | ".join(cols) + " |。按本工程实际列 6～20 行。"
            + extra
            + "数量、规格要与工期和工程规模匹配；表后不要写说明段落。"
        )
    return _FORMAT_HINT.get(kind, _FORMAT_HINT[KIND_PAIRS])


def _ancestors(outline: list[dict], node: dict) -> list[dict]:
    by_id = {n.get("id"): n for n in outline}
    chain: list[dict] = []
    cur = by_id.get(node.get("parentId"))
    while cur is not None and len(chain) < 8:
        chain.insert(0, cur)
        cur = by_id.get(cur.get("parentId"))
    return chain


def _siblings(outline: list[dict], node: dict) -> list[str]:
    return [str(n.get("title") or "") for n in outline if n.get("parentId") == node.get("parentId") and n.get("id") != node.get("id")]


def leaf_count(outline: list[dict]) -> int:
    parents = {n.get("parentId") for n in outline}
    return sum(1 for n in outline if n.get("id") not in parents) or 1


def _water_heavy(node: dict, outline: list[dict], facts: dict) -> float:
    blob = " ".join(str(item.get("title") or "") for item in _ancestors(outline, node) + [node])
    if re.search(r"度汛|导流", blob):
        return 1.5 if (facts.get("floodSeason") or {}).get("spansFlood") else 1.3
    if re.search(r"施工方案|施工方法|施工工艺|主要施工", blob):
        return 1.3
    return 1.0


def _weight_value(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def _score_share(node: dict, outline: list[dict], facts: dict) -> tuple[float, int] | None:
    """本节所在一级章按评分权重分到的篇幅比例，以及该章下的末级节点数。对不上评分项时返回 None。"""
    items = [(s["title"], _weight_value(s.get("weight") or "")) for s in normalize_facts(facts)["scoreItems"]]
    total = sum(w for _, w in items)
    if total <= 0:
        return None
    chain = _ancestors(outline, node)
    top = chain[0] if chain else node
    top_title = str(top.get("title") or "")
    key = re.sub(r"\s+", "", top_title)[:8]
    weight = next((w for t, w in items if key and re.sub(r"\s+", "", t)[:8] == key), 0.0)
    if weight <= 0:
        return None
    by_id = {n.get("id"): n for n in outline}
    parents = {n.get("parentId") for n in outline}

    def under_top(n: dict) -> bool:
        cur = n
        while cur is not None:
            if cur.get("id") == top.get("id"):
                return True
            cur = by_id.get(cur.get("parentId"))
        return False

    leaves = sum(1 for n in outline if n.get("id") not in parents and under_top(n)) or 1
    return weight / total, leaves


def target_chars(node: dict, outline: list[dict], facts: dict, layout: dict | None = None, specialty: str = "") -> int:
    kind = section_kind(node)
    if kind == KIND_FIGURE:
        return 320 if specialty == "水利" else 200
    pages = normalize_facts(facts)["pageLimit"]
    if pages:
        from .e_writer import chars_per_page

        total = pages * chars_per_page(layout) * 0.85
        share = _score_share(node, outline, facts)
        if share:
            ratio, leaves = share
            per = int(total * ratio / leaves)
        else:
            per = int(total / leaf_count(outline))
    else:
        per = 1400
    if specialty == "水利":
        per = int(per * _water_heavy(node, outline, normalize_facts(facts)))
    floor = 300 if kind == KIND_BOX else 500
    return max(floor, min(per, 3000))


_CACHE_TTL = 600
_tender_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()


def project_tender_text(project_id: str) -> str:
    with _cache_lock:
        hit = _tender_cache.get(project_id)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
    from .writer_tool_runtime import load_original_tender_text

    text = load_original_tender_text(project_id) if project_id else ""
    with _cache_lock:
        _tender_cache[project_id] = (time.time(), text)
    return text


def related_tender_text(corpus: str, keywords: list[str], limit: int = 2500) -> str:
    """招标原文里与本节相关的行，按关键词命中挑选。"""
    if not corpus:
        return ""
    keys = [k for k in dict.fromkeys(keywords) if len(k) >= 2]
    picked: list[str] = []
    total = 0
    for line in corpus.splitlines():
        text = line.strip()
        if len(text) < 6 or text in picked:
            continue
        if any(k in text for k in keys):
            picked.append(text)
            total += len(text)
            if total >= limit:
                break
    return "\n".join(picked)[:limit]


def _keywords(title: str) -> list[str]:
    t = re.sub(r"[（(].*?[）)]", "", title or "")
    t = re.sub(r"^(确保|主要|施工|工程)", "", t)
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}", t)
    stop = {"保障", "措施", "体系", "管理", "分析", "解决", "对应", "及其", "包括", "以及"}
    return [w for w in words if w not in stop][:6]


def _relevant_ledger(facts: dict, title: str, idea: str) -> str:
    """只把标题或编写思路命中的账目送进本节，避免每节塞全量数字。"""
    blob = f"{title} {idea}"
    lines: list[str] = []
    for region in facts.get("regions") or []:
        name = region.get("name") or ""
        if name and name[:4] in blob:
            lines.append(f"区段 {name} {region.get('length') or ''} {region.get('mainQuantities') or ''}".strip())
    echo = bool(re.search(r"进度|工期|导流|度汛|部署|资源|劳动力|机械|设备", blob))
    for node in facts.get("controlNodes") or []:
        name = node.get("name") or ""
        if name and (name[:4] in blob or echo):
            lines.append(f"节点 {name} {node.get('window') or ''} {node.get('note') or ''}".strip())
    if re.search(r"度汛|导流|汛|雨季|冬季", blob):
        flood = facts.get("floodSeason") or {}
        lines.append(
            "汛期账：跨汛 {spans}；导流 {method}；停工 {stop}".format(
                spans="是" if flood.get("spansFlood") else "否",
                method=flood.get("diversionMethod") or "未给出",
                stop=flood.get("stopWorkRule") or "未给出",
            )
        )
    if facts.get("standardsRefs") and re.search(r"工艺|方案|方法|依据|质量|护坡|清淤|堰|导流", blob):
        lines.append("可引用规范编号：" + "、".join(facts["standardsRefs"][:8]))
    if facts.get("regionTotalLength") and re.search(r"概况|区段|部署", blob):
        lines.append(f"公告总长 {facts['regionTotalLength']}，各区段长度相加必须等于这个数")
    if re.search(r"度汛|导流|围堰|等别|设计洪水|防洪标准", blob):
        lines.append("工程等别账：" + _grade_line(facts))
    structures = facts.get("structures") or []
    if structures and re.search(r"概况|部署|泵|闸|涵|桥|堰|装机|机电|设备|构筑物", blob):
        lines.append(
            "构筑物账（数量照抄）："
            + "；".join(f"{s['name']} {s['count']}{'座' if s['count'] else ''} {s['spec']}".strip() for s in structures)
        )
    if re.search(r"勘察|外部条件|周边环境|敏感点|对外交通|场地", blob):
        site = facts.get("siteSurvey") or {}
        lines.append(
            "勘察资料：四至 {b}；敏感点 {p}；对外交通 {a}；坐标系 {c}".format(
                b=site.get("boundaries") or "【待补：工程四至】",
                p="、".join(
                    f"{x['name']}{('（' + x['note'] + '）') if x.get('note') else ''}" for x in (site.get("sensitivePoints") or [])
                )
                or "【待补：敏感点】",
                a=site.get("access") or "【待补：对外交通】",
                c=site.get("crsNote") or "【待补：坐标系与高程系】",
            )
        )
    return "\n".join(lines)


_TERM_STOP = {
    "保障", "体系", "重难点", "难点", "解决", "汇总", "分步", "进度", "工期", "安全", "文明", "劳动力", "机械", "物资",
    "材料", "设备", "资源", "组织", "部署", "概况", "编制", "依据", "识别", "特点", "本工程", "项目", "说明", "附件",
    "重点", "总体", "现场", "环境", "保护", "季节性", "临时", "主要", "其他",
}
_TERM_SUFFIX = re.compile(r"(工程|施工|方案|工艺|流程|质量|控制|要点|措施|分析|保证|计划|管理|技术|方法|要求|作业|部分)$")
_GENERIC_TITLE = re.compile(r"^(工艺流程|分步施工|质量控制要点|重难点分析|重难点解决措施|保证措施汇总|施工方法|施工工艺|质量控制|技术要点)$")
BOQ_LINE_LIMIT = 15


def _title_terms(title: str) -> list[str]:
    text = re.sub(r"[（(][^）)]*[）)]", "", title or "")
    terms: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fa5]{2,}", text):
        for part in re.split(r"[与及和的、]", run):
            part = re.sub(r"^(确保|主要|本工程|新建|改建)", "", part)
            prev = None
            while prev != part:
                prev = part
                part = _TERM_SUFFIX.sub("", part)
            if len(part) >= 2 and part not in _TERM_STOP and part not in terms:
                terms.append(part)
    return terms


def _bigrams(text: str) -> set[str]:
    chars = re.sub(r"[^\u4e00-\u9fa5]", "", text or "")
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def _term_hits(term: str, name: str) -> bool:
    if term in name:
        return True
    grams = _bigrams(term)
    if len(term) < 3 or not grams:
        return False
    return len(grams & _bigrams(name)) / len(grams) >= 0.66


def _has_qty(row: dict) -> bool:
    return bool(re.search(r"\d", str(row.get("qty") or "")))


def _boq_line(row: dict) -> str:
    line = f"{row.get('code') or ''} {row.get('name') or ''} {row.get('qty') or ''}{row.get('unit') or ''}".strip()
    extra = str(row.get("feature") or row.get("remark") or "").strip()
    if extra:
        line += f"（{extra[:80]}）"
    return line


def boq_lines_for(rows: list[dict] | None, outline: list[dict], node: dict, limit: int = BOQ_LINE_LIMIT) -> list[str]:
    """按本节标题匹配清单行；命中分部标题时带出它下面有数量的子目。标题太泛时用上级标题匹配。"""
    rows = [r for r in (rows or []) if isinstance(r, dict) and str(r.get("name") or "").strip()]
    if not rows:
        return []
    chain = [node] + list(reversed(_ancestors(outline, node)))
    for level, item in enumerate(chain[:3]):
        title = str(item.get("title") or "")
        if level == 0 and _GENERIC_TITLE.match(title.strip()):
            continue
        terms = _title_terms(title)
        if not terms:
            continue
        picked: list[int] = []
        prefixes: list[str] = []
        for i, row in enumerate(rows):
            name = str(row.get("name") or "")
            if not any(_term_hits(t, name) for t in terms):
                continue
            code = str(row.get("code") or "").strip()
            if not _has_qty(row) and code:
                prefixes.append(code + ".")
            if _has_qty(row):
                picked.append(i)
        if prefixes:
            picked += [
                i for i, row in enumerate(rows)
                if _has_qty(row) and any(str(row.get("code") or "").startswith(p) for p in prefixes)
            ]
        if not picked:
            continue
        ordered = sorted(set(picked))
        lines = [_boq_line(rows[i]) for i in ordered[:limit]]
        if len(ordered) > limit:
            lines.append(f"……另有 {len(ordered) - limit} 项清单子目")
        return lines
    return []


PLAN_KEY = "engPlan"

PLAN_SYSTEM = """你是施工总承包企业的计划经理。根据工程事实和工程量清单，编一本全书共用的施工计划账。正文各章写到工期、机械、劳动力、材料时都照抄这本账，所以数字必须前后自洽。
只输出 JSON，不要解释：
{"stages": [{"name": "施工阶段", "start": "开工后第几天", "end": "第几天", "work": "主要工作和工程量"}],
 "machines": [{"name": "机械名称", "spec": "型号规格", "count": "台数，数字", "use": "用于哪个分项，按什么工程量算"}],
 "labor": [{"trade": "工种", "normal": "常态人数，数字", "peak": "高峰人数，数字"}],
 "materials": [{"name": "主要材料", "qty": "数量，数字", "unit": "单位", "basis": "来自清单哪一项或怎么算"}]}
要求：
1. 阶段名优先用工程事实里的施工阶段，最后一个阶段的结束天数不超过计划工期。
2. 材料量只从清单数量推算，basis 写出清单子目或算式；清单里没有的材料不要列。
3. 机械台数按工程量、台班产量和阶段天数推算，use 写明用在哪个分项。
4. 劳动力按工种列常态和高峰两档，高峰人数不少于常态人数。
5. 没有清单时只排阶段和招标点名的机械，不要编工程量。不写公司名称和人员姓名。"""


def normalize_plan(data: dict | None) -> dict:
    src = data if isinstance(data, dict) else {}

    def rows(key: str, fields: tuple[str, ...], cap: int) -> list[dict]:
        out = []
        for item in src.get(key) or []:
            if not isinstance(item, dict):
                continue
            row = {f: _clean(item.get(f)) for f in fields}
            if row[fields[0]]:
                out.append(row)
        return out[:cap]

    return {
        "stages": rows("stages", ("name", "start", "end", "work"), 10),
        "machines": rows("machines", ("name", "spec", "count", "use"), 20),
        "labor": rows("labor", ("trade", "normal", "peak"), 16),
        "materials": rows("materials", ("name", "qty", "unit", "basis"), 20),
    }


def _boq_digest(rows: list[dict] | None, limit: int = 12000) -> str:
    lines: list[str] = []
    total = 0
    for row in rows or []:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        line = f"{row.get('code') or ''} {row.get('name') or ''} {row.get('qty') or ''}{row.get('unit') or ''}".strip()
        lines.append(line)
        total += len(line) + 1
        if total >= limit:
            lines.append("……清单后续子目略")
            break
    return "\n".join(lines)


def build_plan(facts: dict, boq_rows: list[dict] | None, model_id: str | None, *, specialty: str = "") -> dict:
    """全书共用的施工计划账：阶段天数、机械、劳动力、材料。模型不可用时返回空账，正文照常写但数字标待核实。"""
    digest = _boq_digest(boq_rows)
    prompt = "【工程事实】\n" + facts_brief(facts, specialty=specialty)
    prompt += "\n\n【工程量清单】\n" + (digest or "（未上传清单）")
    try:
        content = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=180,
        )
    except LlmError:
        logger.exception("engineering plan build failed")
        return normalize_plan({})
    return normalize_plan(_parse_json_object(content))


def plan_brief(plan: dict | None) -> str:
    p = normalize_plan(plan)
    lines: list[str] = []
    if p["stages"]:
        lines.append("施工阶段：" + "；".join(
            f"{s['name']}（{s['start']}～{s['end']}）{s['work']}".replace("（～）", "") for s in p["stages"]
        ))
    if p["machines"]:
        lines.append("主要机械：" + "；".join(
            f"{m['name']}{(' ' + m['spec']) if m['spec'] else ''} {m['count']}台{('，' + m['use']) if m['use'] else ''}" for m in p["machines"]
        ))
    if p["labor"]:
        lines.append("劳动力：" + "；".join(
            f"{w['trade']} 常态{w['normal']}人／高峰{w['peak']}人" for w in p["labor"]
        ))
    if p["materials"]:
        lines.append("主要材料：" + "；".join(
            f"{m['name']} {m['qty']}{m['unit']}{('（' + m['basis'] + '）') if m['basis'] else ''}" for m in p["materials"]
        ))
    return "\n".join(lines)


_QTY_RE = re.compile(r"(?<![第\d.])(\d+(?:\.\d+)?)\s*(日历天|天|台|辆|人|名|吨|t|m³|m3|立方米|万亩|亩|km|公里|眼|座|㎡|m²|m2)")


def ungrounded_numbers(content: str, sources: str, *, floor: float = 10) -> list[str]:
    """正文里带单位的数量，在工程事实、清单、计划账和招标原文里都找不到的。小于 floor 的不查。"""
    found: list[str] = []
    text = content or ""
    for match in _QTY_RE.finditer(text):
        if re.search(r"第\s*$", text[max(0, match.start() - 3) : match.start()]):
            continue
        num = match.group(1)
        try:
            if float(num) < floor:
                continue
        except ValueError:
            continue
        bare = num[:-2] if num.endswith(".0") else num
        if re.search(rf"(?<![\d.]){re.escape(bare)}(?!\d)", sources or ""):
            continue
        label = f"{num}{match.group(2)}"
        if label not in found:
            found.append(label)
    return found


def build_chapter_prompt(
    node: dict,
    outline: list[dict],
    facts: dict,
    *,
    tender_text: str = "",
    layout: dict | None = None,
    project_rules: list | None = None,
    clauses: list | None = None,
    specialty: str = "",
    design_lines: list[str] | None = None,
    boq_lines: list[str] | None = None,
    plan_text: str = "",
) -> str:
    chain = _ancestors(outline, node)
    path = " > ".join(f"{n.get('num', '')} {n.get('title', '')}".strip() for n in chain + [node])
    title = str(node.get("title") or "")
    parent_title = str(chain[-1].get("title") or "") if chain else ""
    focus = title if section_kind(node) != KIND_BOX or not parent_title else f"{parent_title}{title}"
    requirement = str(node.get("requirement") or "").strip() or (str(chain[-1].get("requirement") or "").strip() if chain else "")
    related = related_tender_text(tender_text, _keywords(focus) + _keywords(parent_title))
    lines = [
        "【工程事实】",
        facts_brief(facts, specialty=specialty),
        "",
        f"【本节位置】{path}",
        f"【本节标题】{title}",
    ]
    if node.get("idea"):
        lines.append(f"【编写思路】{node['idea']}")
    if requirement:
        lines.append(f"【招标要求原文】{requirement[:1500]}")
    siblings = _siblings(outline, node)
    if siblings:
        lines.append("【同级小节，不要重复】" + "、".join(siblings[:12]))
    if related:
        lines += ["", "【招标原文相关条款】", related]
    if boq_lines:
        lines += ["", "【本节清单（工程量照抄，不要另编数量）】", "\n".join(boq_lines)]
    if plan_text:
        lines += ["", "【施工计划账（全书共用，天数、台数、人数、材料量照抄）】", plan_text]
    words = _keywords(focus)
    matched = []
    if words:
        matched = [
            f"{item.get('title')}：{item.get('requirement')}"
            for item in (project_rules or [])
            if item.get("enabled") is not False
            and any(word in f"{item.get('title') or ''}{item.get('requirement') or ''}" for word in words)
        ][:6]
    if matched:
        lines += ["", "【本节要落实的预审规则】", "\n".join(matched)]
    if clauses:
        lines += ["", "【可以引用的规范条文，没有列出的标准号不要写】"]
        for clause in clauses[:3]:
            lines.append(f"{clause.get('code') or ''} {clause.get('clauseNo') or ''} {clause.get('excerpt') or ''}".strip())
    if specialty != "水利":
        codes = _standard_codes(tender_text, limit=12)
        lines += ["", "【招标原文出现的规范编号，正文只能用这些和上面列出的条文】" + ("、".join(codes) if codes else "无，正文不写规范编号")]
    if specialty == "水利":
        ledger = _relevant_ledger(normalize_facts(facts), title, str(node.get("idea") or ""))
        lines += [
            "",
            "【水利写作约束】工艺步骤各带一个数字加单位。约束用「不小于」「不低于」「不超过」「不大于」「严禁」，禁止 ≤ ≥ < >。"
            "规范编号只能用依据账或本节列出的编号，没有就写「暂无可引用规范」。控制性节点的日期和天数必须与节点账一致。",
        ]
        if ledger:
            lines += ["", "【本节相关账目，数字照抄】", ledger]
        if design_lines:
            lines += ["", "【设计参数（来自图纸与清单，数字照抄，没有的参数写【待核实】）】", "\n".join(design_lines)]
    lines += [
        "",
        f"【写法】{format_hint(node, specialty)}",
        f"【篇幅】不超过约 {target_chars(node, outline, facts, layout, specialty)} 字。可写的事实少就写短，不要为凑字复述规范、工法和管理套话。",
    ]
    return "\n".join(lines)


def _escape_cell(text: str) -> str:
    return text.replace("|", "／")


def box_table(text: str) -> str:
    body = "<br>".join(_escape_cell(line.strip()) for line in (text or "").splitlines() if line.strip())
    if not body:
        return ""
    return f"| {body} |\n| --- |"


def normalize_table_markdown(markdown: str) -> str:
    """模型偶尔在表格外写段落或标题：把表格外的文字收进一格框，保证全章都是表格。"""
    text = (markdown or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text).strip()
    blocks: list[str] = []
    loose: list[str] = []
    table: list[str] = []

    def flush_loose() -> None:
        if loose:
            cleaned = [re.sub(r"^#{1,6}\s*", "", ln).strip() for ln in loose]
            box = box_table("\n".join(c for c in cleaned if c))
            if box:
                blocks.append(box)
            loose.clear()

    def flush_table() -> None:
        if table:
            blocks.append("\n".join(table))
            table.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("|") and line.count("|") >= 2:
            flush_loose()
            table.append(line)
        elif not line:
            flush_table()
            flush_loose()
        else:
            flush_table()
            loose.append(line)
    flush_table()
    flush_loose()
    fixed = []
    for block in blocks:
        rows = block.split("\n")
        if len(rows) == 1 or not re.match(r"^\|\s*:?-{3,}", rows[1]):
            cols = max(1, rows[0].strip().strip("|").count("|") + 1)
            rows.insert(1, "| " + " | ".join(["---"] * cols) + " |")
        fixed.append("\n".join(rows))
    return "\n\n".join(fixed)


_checklist_cache: dict[str, tuple[float, object]] = {}


def _load_checklist(project_id: str):
    """读一次解析清单，短时间内同一项目的各章共用，批量并发写章不重复查库。"""
    if not project_id:
        return None
    with _cache_lock:
        hit = _checklist_cache.get(project_id)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
    try:
        from ..db import SessionLocal
        from .rules_config import load_project_checklist

        db = SessionLocal()
        try:
            checklist = load_project_checklist(db, project_id)
        finally:
            db.close()
    except Exception:
        logger.exception("project checklist for writer failed")
        return None
    with _cache_lock:
        _checklist_cache[project_id] = (time.time(), checklist)
    return checklist


def _project_rules_for(project_id: str) -> list[dict]:
    checklist = _load_checklist(project_id)
    return list(getattr(checklist, "project_rules", None) or [])


def _design_ledger_for(project_id: str) -> list[dict]:
    checklist = _load_checklist(project_id)
    if checklist is None:
        return []
    from .water_design import design_ledger

    return design_ledger(checklist)


def _clauses_for(project_id: str, title: str) -> list[dict]:
    if not project_id or not title:
        return []
    try:
        from ..db import SessionLocal
        from .standard_review import search_clauses

        db = SessionLocal()
        try:
            from ..models import Project

            project = db.get(Project, project_id)
            specialty = (project.specialty if project is not None else "") or "通用"
            return search_clauses(db, title, specialty, limit=3)
        finally:
            db.close()
    except Exception:
        logger.exception("clause lookup for writer failed")
        return []


def boq_rows_for(project_id: str) -> list[dict]:
    checklist = _load_checklist(project_id)
    return list(getattr(checklist, "boq_rows", None) or [])


def chapter_prompt_for(
    node: dict,
    outline: list[dict],
    facts: dict,
    *,
    project_id: str = "",
    layout: dict | None = None,
    specialty: str = "",
    plan: dict | None = None,
) -> str:
    """正文提示词：工程事实、本节清单、施工计划账、招标原文、预审规则和规范条文一起给。"""
    design_lines: list[str] = []
    if specialty == "水利":
        from .water_design import design_lines_for

        design_lines = design_lines_for(_design_ledger_for(project_id), str(node.get("title") or ""), str(node.get("idea") or ""))
    bound = [c for c in (node.get("clauseRefs") or []) if isinstance(c, dict) and c.get("code")]
    return build_chapter_prompt(
        node,
        outline,
        facts,
        tender_text=project_tender_text(project_id),
        layout=layout,
        project_rules=_project_rules_for(project_id),
        clauses=bound or _clauses_for(project_id, str(node.get("title") or "")),
        specialty=specialty,
        design_lines=design_lines,
        boq_lines=boq_lines_for(boq_rows_for(project_id), outline, node),
        plan_text=plan_brief(plan),
    )


def write_chapter(
    node: dict,
    outline: list[dict],
    facts: dict,
    *,
    model_id: str | None,
    project_id: str = "",
    layout: dict | None = None,
    specialty: str = "",
    plan: dict | None = None,
) -> str:
    """写一节工程施组正文。不取知识库、产品库和资质库，只看工程事实、清单、计划账与招标原文。"""
    prompt = chapter_prompt_for(
        node, outline, facts, project_id=project_id, layout=layout, specialty=specialty, plan=plan
    )
    system = WATER_CHAPTER_SYSTEM if specialty == "水利" else ENG_CHAPTER_SYSTEM
    try:
        content = chat_complete(
            model_id=model_id,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.4,
            timeout=300,
        )
    except LlmError as exc:
        logger.warning("engineering chapter failed: %s", exc)
        return box_table(f"（AI 生成暂不可用：{exc}）\n请结合招标文件和施工逻辑补充本节：{node.get('idea') or node.get('title')}")
    return normalize_table_markdown(content)


__all__ = [
    "FACTS_KEY",
    "KIND_BOX",
    "KIND_FIGURE",
    "KIND_GRID",
    "KIND_GROUP",
    "KIND_PAIRS",
    "build_chapters",
    "extract_facts",
    "facts_brief",
    "flatten_chapters",
    "generate_outline",
    "apply_detected_specialty",
    "is_engineering",
    "is_engineering_tech",
    "writer_track",
    "TRACK_ENGINEERING",
    "TRACK_SOFTWARE",
    "TRACK_WATER",
    "normalize_facts",
    "normalize_table_markdown",
    "section_kind",
    "site_gaps",
    "tender_excerpt",
    "write_chapter",
]
