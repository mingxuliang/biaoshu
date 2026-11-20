"""AI 撰写工作台引擎：大模型阅读招标原文生成应标目录，并逐章生成投标文件正文。

目录生成与章节正文使用用户在标书设置中选择的大模型（DeepSeek 4 Pro / 豆包）。
未配置 Key 或调用异常时降级为招标条款原树或占位正文，不阻塞撰写流程。
"""

import json
import logging
import re

from .llm import LlmError, chat_complete, is_vision_model
from .tender_style import apply_tech_markdown_style

logger = logging.getLogger(__name__)


def _cn_num(n: int) -> str:
    if n <= 0:
        return str(n)
    digits = "零一二三四五六七八九"
    if n <= 10:
        return "一二三四五六七八九十"[n - 1]
    if n < 20:
        return "十" + digits[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        head = ["", "十", "二十", "三十", "四十", "五十", "六十", "七十", "八十", "九十"][tens]
        return head if ones == 0 else head + digits[ones]
    return str(n)


def _format_outline_num(depth: int, index: int, parent_num: str) -> str:
    """一级 一、 / 二级 （一） / 三级 1. / 四级及以下 1.1、1.1.1。"""
    if depth == 0:
        return f"{_cn_num(index)}、"
    if depth == 1:
        return f"（{_cn_num(index)}）"
    if depth == 2:
        return f"{index}."
    base = re.sub(r"[、.）\s]+$", "", parent_num or "")
    base = re.sub(r"^（", "", base)
    if re.match(r"^\d+(\.\d+)*$", base):
        return f"{base}.{index}"
    return f"{index}."


OUTLINE_INVENTORY_MAX = 16000

_OUTLINE_SHARED = """用检索找「投标文件格式」「响应文件格式」「投标文件组成」「响应文件编制」。格式节不限章号。不要从第 1 页逐页翻到最后。
评标办法不进目录。合同条款、投标人须知、形式评审、资格评审、响应性评审里的句子也不要写进目录。机器码、标识码、签字盖章、未出现报价、限价、IP 地址都不是章节。
禁止再套「符合第×章格式的要求」或任何自拟总标题。抽不到这份清单时，不要套一套默认章节。
文件名按原文。需求说明句收成不超过 12 字的短标题，标题不要自带编号。
对应某条需求的标题，下一行写「依据：T5」或「依据：B3」，多条写「依据：T5,T6」。
只输出 Markdown 标题（# 一级、## 二级、### 三级），不要解释。
"""

BUSINESS_OUTLINE_PROMPT = """你是商务标目录编辑。软件服务标、工程标、水利标的商务分册都用这一份。只根据本份招标书格式节里的商务文件编目录。

""" + _OUTLINE_SHARED + """
一级章只用格式节里的商务文件，按原文和顺序，一项文件一个一级章。
下级只写这一节在该文件下面印出的目录。
承诺书、承诺函、授权委托、投标函、开标一览只留文件名。投标函附录若在格式节里单独列出，则保留。
商务标不按篇幅加章。报价文件不进商务标。
"""

SOFTWARE_TECH_OUTLINE_PROMPT = """你是软件服务标技术标目录编辑。只根据本份招标书格式节里的技术文件编目录。工程施组、水利施组不使用这一份。

""" + _OUTLINE_SHARED + """
一级章只用格式节里的技术文件，按原文和顺序，一项文件一个一级章。
下级照招标书的需求结构写：二级是需求小节（如 4.1），三级是该小节里的每一条需求，一条一个标题，不要合并，不要改名。
采购需求、用户需求、技术标准、发包人要求里的条款都要挂上。有编号的标题保留编号，如「F-01 组织与账号管理」；没有编号的收成不超过 12 字的短名。
投标函、授权委托、资格、报价、业绩不要输出。不要为凑页数自拟章节。
"""


def outline_system_prompt(doc_kind: str) -> str:
    """商务标三种标共用一份。软件技术标单独一份。施组不走这里。"""
    if (doc_kind or "tech").strip().lower() == "business":
        return BUSINESS_OUTLINE_PROMPT
    return SOFTWARE_TECH_OUTLINE_PROMPT


# 旧名保留给仍按「系统提示词」断言的测试。内容是两份目录提示词，都含共用禁则。
OUTLINE_SYSTEM_PROMPT = BUSINESS_OUTLINE_PROMPT + "\n" + SOFTWARE_TECH_OUTLINE_PROMPT

ORIGINAL_FORM_NOTE = "招标书未提供本文件的固定格式，请按投标人自有格式提供并签字盖章。"
ORIGINAL_FORM_IDEA_PREFIX = "【按招标书原文格式填写后打印签字，不展开目录、不撰写正文】"
BUSINESS_SKIP_NOTE = (
    "商务标本章无需撰写应标正文。承诺书、授权委托、投标函、开标一览及证照业绩请直接使用招标书原文或扫描件。"
)
BUSINESS_SKIP_IDEA_PREFIX = "【商务标无需应答，不撰写应标正文】"

# 按「文件类别」识别，不用某份招标书的具体章节名。
_ORIGINAL_FORM_TITLE = re.compile(r"(承诺书|承诺函|授权委托|投标函|开标一览)")
_CERTIFICATE_TITLE = re.compile(r"(营业执照|资质证书|财务报告|财务报表|审计报告|业绩证明|类似业绩)")
_BUSINESS_SKIP_TITLE = re.compile(
    r"商务标|商务部分|商务文件|商务响应|"
    r"资格审查|资格预审|资格证明|资格文件|"
    r"投标函|法定代表人|"
    r"企业资质|资质证书|营业执照|资质文件|"
    r"财务报告|财务报表|审计报告|财务状况|"
    r"类似业绩|业绩证明|"
    r"投标文件组成|响应文件组成|投标文件的组成|响应文件的组成|"
    r"响应文件格式|投标文件格式"
)
_TECH_VOLUME_TITLE = re.compile(r"技术方案$|技术部分$|技术标$|技术文件$|技术响应$")
_FORMAT_DIR_HINT = re.compile(r"按.{0,40}目录编制|逐条进行描述|逐条描述|逐条响应")


def is_original_form_title(title: str) -> bool:
    """承诺书、授权委托、投标函、开标一览等签字空白件不展开目录。"""
    from .tender_toc import strip_heading_prefix

    t = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    if not t:
        return False
    return bool(_ORIGINAL_FORM_TITLE.search(t))


def is_certificate_title(title: str) -> bool:
    """营业执照、审计报告、业绩证明等粘贴扫描件，不改写成应答正文。"""
    from .tender_toc import strip_heading_prefix

    t = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    return bool(t and _CERTIFICATE_TITLE.search(t))


def original_form_idea(title: str, existing: str = "", tender_req: str = "") -> str:
    body = (tender_req or existing or "").strip()
    if body.startswith(ORIGINAL_FORM_IDEA_PREFIX):
        return body[:8000]
    head = ORIGINAL_FORM_IDEA_PREFIX
    if body:
        return f"{head}\n\n招标书原文：\n{body}"[:8000]
    return f"{head}请直接使用招标书中「{title}」的固定格式原文填写、打印并签字。"


def original_form_markdown(title: str, idea: str = "", original: str = "") -> str:
    text = (original or "").strip()
    if text:
        return text
    extra = _requirement_from_idea(idea)
    if extra and extra not in {title or "", ""}:
        from .tender_toc import strip_heading_prefix

        if extra != strip_heading_prefix(title or ""):
            return extra
    return f"{title or '固定格式文件'}\n\n{ORIGINAL_FORM_NOTE}"


def business_skip_markdown(title: str, original: str = "") -> str:
    text = (original or "").strip()
    if text:
        return text
    return f"{title or '商务标'}\n\n{BUSINESS_SKIP_NOTE}"


def fill_business_originals(
    outline: list[dict],
    contents: dict[str, str],
    originals_by_title: dict[str, str],
) -> bool:
    """把招标书原文写入商务标/固定格式章。已有非占位正文时不覆盖。"""
    from .tender_form import needs_form_recopy

    changed = False
    parent_ids = {str(n.get("parentId")) for n in outline if isinstance(n, dict) and n.get("parentId")}
    for n in outline:
        if not isinstance(n, dict) or n.get("formKeys"):
            continue
        title = str(n.get("title") or "")
        kind = chapter_kind(
            title,
            n.get("part"),
            str(n.get("idea") or ""),
            str(n.get("requirement") or ""),
            has_children=str(n.get("id")) in parent_ids,
        )
        if not should_paste_tender_original(
            title,
            n.get("part"),
            str(n.get("idea") or ""),
            str(n.get("requirement") or ""),
            has_children=str(n.get("id")) in parent_ids,
        ):
            continue
        original = (originals_by_title.get(title) or "").strip()
        existing = contents.get(n["id"]) or ""
        if existing and not needs_form_recopy(existing):
            continue
        if kind == "business" and not is_original_form_title(title):
            body = business_skip_markdown(title, original)
        else:
            body = original_form_markdown(title, str(n.get("idea") or ""), original)
        if not body or body == existing:
            continue
        contents[n["id"]] = body
        n["status"] = "用原文"
        n["part"] = "form" if (kind == "form" or is_original_form_title(title)) else "business"
        n["words"] = len(body.replace(" ", "").replace("\n", ""))
        changed = True
    return changed


def chapter_kind(
    title: str,
    part: str | None = None,
    idea: str = "",
    requirement: str = "",
    *,
    has_children: bool = False,
) -> str:
    """form=签字件原文；business=证照或无条款的商务章；response=按条款写商务应答；tech=技术方案。

    「技术方案」这类整册容器标题：有下级节点、或已明确标成技术章时仍是技术章，
    不会因为标题以「技术方案」结尾、需求为空就被当成商务章。
    有绑定条款的商务叶子写应答；容器章、证照和签字件不走这路。"""
    if is_original_form_title(title) or part == "form":
        return "form"
    from .tender_toc import strip_heading_prefix

    t = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    blob = f"{idea or ''}\n{requirement or ''}"
    if is_certificate_title(t):
        return "business"
    # 只有商务分册上已标成 business、且自身带有条款的叶子才写商务应答。
    # 技术标叶子的 part 是 tech 或尚未标注，不能因为有需求原文就被当成商务应答。
    if (requirement or "").strip() and not has_children and part == "business":
        return "response"
    if _BUSINESS_SKIP_TITLE.search(t):
        return "business"
    if (
        _TECH_VOLUME_TITLE.search(t)
        and not has_children
        and part != "tech"
        and (_FORMAT_DIR_HINT.search(blob) or not (requirement or "").strip())
    ):
        return "business"
    if part in ("business", "tech"):
        return part
    if (requirement or "").strip() or (idea or "").startswith("应实现：") or "应完整响应" in (idea or ""):
        return "tech"
    return "tech"


def chapter_follows_response_rule(title: str) -> bool:
    """投标函、授权委托、证照和纯报价金额行按招标格式填写，不套本份应答规定。"""
    from .tender_toc import strip_heading_prefix

    name = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    if not name or is_original_form_title(name) or is_certificate_title(name):
        return False
    if re.search(r"报价|单价|总价|金额|付款", name) and not re.search(r"响应|偏离|偏差", name):
        return False
    return True


def should_paste_tender_original(
    title: str,
    part: str | None = None,
    idea: str = "",
    requirement: str = "",
    *,
    has_children: bool = False,
) -> bool:
    """签字件和证照粘贴招标原文。已经绑定条款、要逐条应答的商务章不贴「无需应答」。"""
    if is_original_form_title(title) or part == "form":
        return True
    kind = chapter_kind(title, part, idea, requirement, has_children=has_children)
    if kind == "form":
        return True
    if kind != "business":
        return False
    if is_certificate_title(title):
        return True
    return not (requirement or "").strip()


def _requirement_from_idea(idea: str) -> str:
    text = (idea or "").strip()
    for prefix in ("应实现：", "不得漏项：", "招标书原文："):
        if prefix in text:
            return text.split(prefix, 1)[-1].strip()
    if text.startswith(("【对应招标", "【上级条款全文")) and "】" in text:
        body = text.split("】", 1)[-1].strip()
        if body and "按该条款全部要求逐项应答" not in body:
            return body
    return ""


def resolve_chapter_requirement(
    outline: list[dict] | None,
    chapter_id: str | None,
    own_requirement: str,
    idea: str,
    project_id: str = "",
    title: str = "",
) -> tuple[str, str]:
    """章节要答的招标条款。返回 (条款原文, 必须逐项应答数字指标的原文)。

    顺序：节点自己的 requirement -> 编写思路里的条款 -> 沿父链取最近祖先的条款（只取和本章标题相关的分句）
    -> 按标题在招标原文里检索。沿用上级全文、汇总章不要求逐项出现数字指标。
    """
    req = (own_requirement or "").strip() or _requirement_from_idea(idea)
    whole_parent = PARENT_CONTEXT_MARK in (idea or "")
    summary = SUMMARY_CHAPTER_MARK in (idea or "")
    if not req and outline and chapter_id:
        by_id = {str(n.get("id")): n for n in outline if isinstance(n, dict) and n.get("id")}
        node = by_id.get(str(chapter_id))
        seen: set[str] = set()
        while node is not None and node.get("parentId") and str(node.get("parentId")) not in seen:
            seen.add(str(node.get("parentId")))
            node = by_id.get(str(node.get("parentId")))
            if node is None:
                break
            parent_req = str(node.get("requirement") or "").strip() or _requirement_from_idea(str(node.get("idea") or ""))
            if parent_req:
                piece = _clauses_for_title(parent_req, title)
                req = piece or parent_req
                whole_parent = not piece
                break
    if not req and project_id:
        from .writer_tool_runtime import load_original_tender_text

        req = _search_original_snippet(load_original_tender_text(project_id), title)
    facts_source = "" if (whole_parent or summary) else req
    marked = re.search(re.escape(FACTS_MARK) + r"([^】]+)】", idea or "")
    if marked and not summary:
        extra = marked.group(1).replace("、", "，")
        facts_source = f"{facts_source}；{extra}" if facts_source else extra
    return req, facts_source


def _leaf_doc_kind_counts(
    node_id: str, nodes_by_id: dict[str, dict], children_of: dict[str, list[str]]
) -> dict[str, int]:
    counts = {"tech": 0, "business": 0, "form": 0}
    stack = [node_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        kids = children_of.get(current) or []
        if not kids:
            node = nodes_by_id.get(current) or {}
            kind = chapter_kind(
                str(node.get("title") or ""),
                node.get("part"),
                str(node.get("idea") or ""),
                str(node.get("requirement") or ""),
            )
            counts[kind] = counts.get(kind, 0) + 1
        else:
            stack.extend(kids)
    return counts


def split_outline_by_doc_kind(
    outline: list[dict] | None,
    contents: dict[str, str] | None,
    knowledge_refs: dict[str, list] | None,
) -> tuple[tuple[list[dict], dict[str, str], dict[str, list]], tuple[list[dict], dict[str, str], dict[str, list]]]:
    """旧版混合目录（技术标/商务标同树）迁移成两条独立轨道时用：按每个顶层节点的叶子多数票判断它属于哪一分册，
    整棵子树（含已生成正文、知识引用）一起搬走。返回 (技术标 bundle, 商务标 bundle)，bundle=(outline, contents, knowledgeRefs)。
    """
    nodes = [n for n in (outline or []) if isinstance(n, dict) and n.get("id")]
    nodes_by_id = {str(n["id"]): n for n in nodes}
    children_of: dict[str, list[str]] = {}
    top_ids: list[str] = []
    for n in nodes:
        node_id = str(n["id"])
        parent = n.get("parentId")
        if parent in (None, "", False):
            top_ids.append(node_id)
        else:
            children_of.setdefault(str(parent), []).append(node_id)

    business_ids: set[str] = set()
    for top_id in top_ids:
        counts = _leaf_doc_kind_counts(top_id, nodes_by_id, children_of)
        biz = counts.get("business", 0) + counts.get("form", 0)
        if biz > counts.get("tech", 0):
            stack = [top_id]
            while stack:
                current = stack.pop()
                if current in business_ids:
                    continue
                business_ids.add(current)
                stack.extend(children_of.get(current, []))

    all_contents = dict(contents or {})
    all_refs = dict(knowledge_refs or {})
    tech_outline = [n for n in nodes if str(n["id"]) not in business_ids]
    business_outline = [n for n in nodes if str(n["id"]) in business_ids]
    tech_contents = {k: v for k, v in all_contents.items() if k not in business_ids}
    business_contents = {k: v for k, v in all_contents.items() if k in business_ids}
    tech_refs = {k: v for k, v in all_refs.items() if k not in business_ids}
    business_refs = {k: v for k, v in all_refs.items() if k in business_ids}
    return (tech_outline, tech_contents, tech_refs), (business_outline, business_contents, business_refs)


def _collapse_original_form_chapters(nodes: list[dict], tender_toc: dict | None = None) -> None:
    for n in nodes:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "")
        if is_original_form_title(title):
            # 投标函附录是另一份文件，不能跟填写栏一起清掉。
            kept = [
                child
                for child in (n.get("children") or [])
                if isinstance(child, dict) and "附录" in _node_title(child)
            ]
            n["children"] = kept
            n["idea"] = original_form_idea(title, str(n.get("idea") or ""), _compose_requirement_blob(title, tender_toc))
            n["aiIdea"] = n["idea"]
            _collapse_original_form_chapters(kept, tender_toc)
            continue
        kids = n.get("children")
        if isinstance(kids, list):
            _collapse_original_form_chapters(kids, tender_toc)


CHAPTER_SYSTEM_PROMPT = """你是资深投标文件撰写专家，请围绕给定的章节标题与编写思路，撰写正式的投标文件正文内容。
写作要求：
1. 使用 Markdown 排版，标题只用 ## 和 ###（不要用 ####、# 或 HTML），列表用 - 或 1. ；正文长度约 800-2000 字；
2. 不要输出代码围栏（```）、不要把井号当装饰留在正文里；
3. 语言正式、专业，符合中国大陆招投标文件的行文习惯；
4. 编写思路里列出的「应实现」功能点必须逐条响应；标注「应覆盖招标需求全文」的条款必须全部写入正文，不得合并漏项或改成空泛描述；
5. 若提供了关联评分点或必响应条款，正文应体现针对性响应，但不要逐字复制原文；
6. 若提供了知识库/产品功能库/资质证照库整包素材：必须通读全部正文、参数、表格与原图，禁止只看摘要或丢掉任一张图、任一段文字；应借鉴其结构与信息并结合本项目改写。原图已按编号给出，请在对应位置写【此处插入图：1】【此处插入图：2】，不要编造图片 URL；未用到的图也要在章末按编号补齐，不允许丢失。
7. 若提供了「本公司已审核产品能力」，正文必须据此组句，只能写已列出的能力与参数，禁止编造未列出的功能、指标或截图；配图必须按附图清单编号全部插入；无匹配能力时必须写一行【能力缺口：本章招标需求在产品库中无对应功能点】，不要用套话填满；
8. 若提供了「本公司已入库资质材料」，只能引用列出的证号、持有人与有效期，禁止编造未入库的证书；扫描件必须按附图清单编号全部插入，不要编造图片 URL；
9. 只返回正文内容本身，不要包含任何解释说明，也不要用 JSON 包装。
"""

TECH_SOLUTION_SYSTEM = """你是资深投标文件撰写专家。本章是技术标对标条款：招标「原始需求」由系统插入，你只写「解决方案」。
写作要求：
1. 只输出解决方案正文，不要写「原始需求」标题或抄录招标原文；不要输出代码围栏；标题只用 ## 和 ###；
2. 必须针对本章招标需求逐条应答，不得漏项、不得改成空泛描述；
3. 解决方案必须使用用户勾选的产品功能库素材（参数、应标原文、原图），只能写已列出的能力，禁止编造未列出的功能、指标或截图；
4. 原图按附图清单编号在对应位置写【此处插入图：1】【此处插入图：2】，不要编造图片 URL；未用到的图也要在方案末按编号补齐，不允许丢失；
5. 无匹配产品能力时写一行【能力缺口：本章招标需求在产品库中无对应功能点】，不要用套话填满；
6. 若同时提供了知识库整包，可借鉴其结构但以产品能力为准；
7. 只返回解决方案本身，不要解释。
"""


def generate_outline(
    project_name: str,
    score_rules: list[dict],
    must_respond: list[dict],
    knowledge_headings: list[str] | None = None,
    tender_toc: dict | None = None,
    tender_text: str | None = None,
    model_id: str | None = None,
    harness: dict | None = None,
    format_requirements: list | None = None,
    doc_kind: str = "tech",
    page: dict | None = None,
    layout: dict | None = None,
    report: dict | None = None,
    ledger_out: list | None = None,
    form_registry: list[dict] | None = None,
) -> list[dict]:
    """用 AgentScope 阅读招标原文编制应标目录。report 传入时会被写入覆盖报告
    （total 条目数、boundByModel 模型引用数、titleMatched 按标题绑定数、backfilled 补章数、noSource 无依据节点）。harness 必填——目录生成只走 AgentScope harness 通读原文，
    不再接受「跳过 harness 裸调模型」的用法，也不再吃招标解析模块预抽出的技术标/商务标摘要。
    Harness 判定失败时直接抛出，不把套话目录当成功；非 Harness 的意外解析异常仍回退招标标题树兜底。"""
    del knowledge_headings  # 目录只覆盖招标需求，不用知识库目录改写结构
    from .writer_harness import HarnessError, write_outline_markdown

    if not harness:
        raise HarnessError("目录生成必须经过 AgentScope harness，不支持裸调模型")
    try:
        from .tender_toc import composition_for_volume, extract_bid_composition
        from .writer_tool_runtime import load_tender_extracts

        composition = composition_for_volume(extract_bid_composition(tender_text or ""), doc_kind)
        extracts = load_tender_extracts(str(harness.get("project_id") or ""))
        tech_text = extracts.get("tech") or ""
        business_text = extracts.get("business") or ""
        from .form_registry import make_form_mapper, registry_light

        light_registry = registry_light(form_registry)
        form_mapper = make_form_mapper(model_id)
        feedback = ""
        chapters: list[dict] = []
        coverage: dict = {}
        ledger: list[dict] = []
        issues: list[str] = []
        for attempt in range(OUTLINE_REVIEW_ROUNDS):
            content = write_outline_markdown(
                user_id=str(harness.get("user_id") or ""),
                project_id=str(harness.get("project_id") or ""),
                draft_id=str(harness.get("draft_id") or ""),
                job_id=str(harness.get("job_id") or ""),
                model_id=model_id,
                project_name=project_name,
                tender_text=tender_text or "",
                tender_toc=tender_toc,
                score_rules=score_rules,
                must_respond=must_respond,
                format_requirements=format_requirements,
                doc_kind=doc_kind,
                page=page,
                layout=layout,
                review_feedback=feedback,
            )
            chapters = _chapters_from_llm_output(content)
            if not chapters:
                break
            coverage, ledger, notes = _assemble_outline(
                chapters,
                composition=composition,
                tender_toc=tender_toc,
                score_rules=score_rules,
                tech_text=tech_text,
                business_text=business_text,
                tender_text=tender_text or "",
                doc_kind=doc_kind,
                form_registry=light_registry,
                form_mapper=form_mapper,
            )
            chapters = coverage.pop("_chapters")
            issues = outline_problems(chapters, ledger, notes)
            # 只按已经核对出的缺口再写一轮。不再另起评审智能体把全文重读一遍。
            if issues and attempt + 1 < OUTLINE_REVIEW_ROUNDS:
                feedback = "上一版目录评审未通过，请只修正这些问题后重新输出整份目录：\n" + "\n".join(
                    f"- {item}" for item in issues[:20]
                )
                continue
            break
        if chapters:
            coverage["reviewIssues"] = issues[:20]
            if ledger_out is not None:
                ledger_out[:] = ledger
            if report is not None:
                report.clear()
                report.update(coverage)
            nodes = _normalize_outline({"chapters": chapters})
            if nodes:
                return nodes
            logger.warning("outline harness returned no parseable directory")
        raise HarnessError("目录结果无法解析成章节")
    except HarnessError:
        raise
    except Exception:  # noqa: BLE001 —— 非 Harness 判定的意外解析异常仍回退招标标题树，避免整条流水线被卡死
        logger.exception("outline harness generate failed, falling back to tender headings")
    if report is not None:
        report["fallbackOutline"] = True  # 让前端提示：这份目录是招标标题树兜底，不是智能体评审后的结果
    return _fallback_outline(score_rules, tender_toc)


OUTLINE_REVIEW_ROUNDS = 2


def requirement_coverage_problems(
    chapters: list[dict],
    tech_text: str,
    business_text: str,
    tender_text: str,
    doc_kind: str,
    *,
    has_deviation_form: bool = False,
    has_quote_form: bool = False,
) -> list[str]:
    """应答编号和招标点名的表有没有进目录。只报问题，不补章、不改标题。"""
    from .writer_tool_runtime import numbered_requirement_items

    problems: list[str] = []
    cited = _tree_cited_ids(chapters)
    kind = (doc_kind or "tech").strip().lower()
    wanted: list[tuple[str, str]] = []
    if kind == "business":
        for item_id, title, _body in _business_volume_items(business_text):
            wanted.append((item_id, title))
    else:
        for item_id, raw in numbered_requirement_items(tech_text, "tech"):
            title, _body = _short_requirement_title(raw)
            if title:
                wanted.append((item_id, title))
        for item_id, raw in numbered_requirement_items(business_text, "business"):
            title, body = _short_requirement_title(raw)
            if title and business_item_belongs_in_tech(title, body):
                wanted.append((item_id, title))
    for item_id, title in wanted:
        if item_id in cited:
            continue
        problems.append(f"应答「{item_id}」没有目录节点：{title}")

    if kind == "business":
        corpus = f"{business_text}\n{tender_text}"
        titles = [_node_title(node) for node in _iter_chapter_nodes(chapters)]
        has_deviation = any("偏离" in title or "偏差" in title for title in titles)
        if _DEVIATION_HINT.search(corpus) and not has_deviation and not has_deviation_form:
            problems.append("招标要求偏离表或偏差表，目录里没有对应章节")
        if not has_quote_form:
            for node in _iter_chapter_nodes(chapters):
                title = _node_title(node)
                if _is_quote_detail_title(title) and not node.get("children"):
                    pieces = _enumerated_pieces(str(node.get("requirement") or ""))
                    if len(pieces) >= 2:
                        problems.append(f"「{title}」列出了报价分项，但没有拆成下级节点")
                        break
                if _is_quote_node(title) and "付款" not in title:
                    blob = f"{node.get('requirement') or ''}\n{node.get('idea') or ''}"
                    if _PAYMENT_HINT.search(blob) and _PAYMENT_DETAIL.search(blob) and not _descendant_has_keyword(node, "付款"):
                        problems.append(f"「{title}」写了付款节点，目录里没有付款小节")
                        break
    return problems[:20]


# 小节标题或所在章命中左边时，挂到标题命中右边的组成文件。一组命中多个组成文件时取组成清单里靠前的。
_SECTION_HOSTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("对接", "接口", "迁移", "集成"), ("接口", "迁移", "集成", "对接")),
    (("部署", "安全"), ("部署", "安全")),
    (("实施", "交付", "验收", "周期", "团队", "风险"), ("实施", "团队", "风险")),
    (("质保", "运维", "售后", "培训要求"), ("运维", "培训", "售后")),
)


def _requirement_tree_text(tree: list[dict], limit: int = 8000) -> str:
    lines: list[str] = []
    for section in tree or []:
        if not isinstance(section, dict):
            continue
        number = str(section.get("clauseNo") or "").strip()
        lines.append(f"- {number + ' ' if number else ''}{section.get('title') or ''}".rstrip())
        for item in section.get("items") or []:
            if isinstance(item, dict):
                lines.append(f"  - {_req_item_title(item)}")
    return "\n".join(lines)[:limit]


def _req_item_title(item: dict) -> str:
    code = str(item.get("code") or "").strip()
    name = str(item.get("name") or "").strip()
    if not name:
        name, _body = _short_requirement_title(str(item.get("text") or ""))
    if code and name:
        return f"{code} {name}"
    return name or code or "需求"


def _section_heading(section: dict) -> str:
    number = str(section.get("clauseNo") or "").strip()
    title = str(section.get("title") or "").strip()
    return f"{number} {title}".strip()


def _clause_in_title(number: str, title: str) -> bool:
    if not number:
        return False
    return bool(re.search(rf"(?<!\d){re.escape(number)}(?!\d)", title or ""))


def _host_groups(text: str) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    return [group for group in _SECTION_HOSTS if any(key in (text or "") for key in group[0])]


def _composition_hosts(chapters: list[dict], composition: list[dict] | None) -> list[tuple[str, dict]]:
    hosts: list[tuple[str, dict]] = []
    for item in composition or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        node = next(
            (chapter for chapter in chapters if isinstance(chapter, dict) and _is_same_large_chapter(title, _node_title(chapter))),
            None,
        )
        if title and node is not None:
            hosts.append((title, node))
    return hosts


def _pick_host(text: str, hosts: list[tuple[str, dict]]) -> dict | None:
    groups = _host_groups(text)
    if len(groups) != 1:
        return None
    keys = groups[0][1]
    for title, node in hosts:
        if any(key in title for key in keys):
            return node
    return None


def _default_requirement_host(hosts: list[tuple[str, dict]], chapters: list[dict]) -> dict | None:
    for words in (("需求响应",), ("技术方案", "技术响应")):
        for title, node in hosts:
            if any(word in title for word in words):
                return node
    if hosts:
        return hosts[0][1]
    for chapter in chapters:
        if isinstance(chapter, dict) and not is_original_form_title(_node_title(chapter)):
            return chapter
    return None


def _host_for_section(section: dict, hosts: list[tuple[str, dict]]) -> dict | None:
    found = _pick_host(str(section.get("title") or ""), hosts)
    if found is not None:
        return found
    return _pick_host(str(section.get("chapter") or ""), hosts)


def _detach_child(chapters: list[dict], node: dict) -> bool:
    """从非一级章的位置摘下节点。一级章是组成文件，不能摘。"""

    def walk(nodes: list[dict]) -> bool:
        for current in nodes:
            if not isinstance(current, dict):
                continue
            kids = current.get("children")
            if not isinstance(kids, list):
                continue
            if any(kid is node for kid in kids):
                current["children"] = [kid for kid in kids if kid is not node]
                return True
            if walk(kids):
                return True
        return False

    return walk(chapters)


def _find_skeleton_node(chapters: list[dict], *, code: str = "", number: str = "", name: str = "") -> dict | None:
    """按编号或小节号找已有节点。带编号的标题不再用名称去撞，避免「超级管理员」把 F-02 抢走。"""
    tops = {id(chapter) for chapter in chapters if isinstance(chapter, dict)}
    coded = re.compile(r"^[A-Za-z]{1,4}-\d+\s")
    for node in _iter_chapter_nodes(chapters):
        if id(node) in tops or is_original_form_title(_node_title(node)):
            continue
        title = _node_title(node)
        if code:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?!\d)", title):
                return node
            continue
        if number and _clause_in_title(number, title):
            return node
        plain = _plain_title(name)
        if not plain or len(plain) < 2 or coded.match(title):
            continue
        if _plain_title(title) == plain or plain in _plain_title(title):
            return node
    return None


def _write_item_node(node: dict, title: str, text: str, rule_text: str) -> None:
    node["title"] = title
    node["part"] = "tech"
    node["requirement"] = text
    idea = _idea_from_requirement(title, text)
    if rule_text:
        idea = (idea + f"\n【应答写法】{rule_text}")[:8000]
    node["idea"] = idea
    node["aiIdea"] = idea
    if not isinstance(node.get("children"), list):
        node["children"] = []


def _bind_skeleton_refs(chapters: list[dict], tech_text: str, business_text: str) -> None:
    """把 T、B 摘要对到已经按招标结构生成的小节上，避免覆盖检查把它们再报成漏项。"""
    from .writer_tool_runtime import numbered_requirement_items

    pool: list[tuple[str, str]] = []
    for item_id, raw in numbered_requirement_items(tech_text or "", "tech"):
        pool.append((item_id, _clean_item_text(raw)))
    for item_id, raw in numbered_requirement_items(business_text or "", "business"):
        title, body = _short_requirement_title(raw)
        if business_item_belongs_in_tech(title, body):
            pool.append((item_id, _clean_item_text(raw)))
    leaves = [node for node in _iter_chapter_nodes(chapters) if _is_leaf(node) and str(node.get("requirement") or "").strip()]
    for item_id, body in pool:
        short, _rest = _short_requirement_title(body)
        probe = re.sub(r"\s+", "", body)[:12]
        best = None
        best_score = 0
        for node in leaves:
            score = _title_overlap_score(short or body[:16], _node_title(node))
            if short and short in _node_title(node):
                score += 10
            if probe and probe in re.sub(r"\s+", "", str(node.get("requirement") or "")):
                score += 6
            if score > best_score:
                best, best_score = node, score
        if best is None or best_score < 6:
            continue
        refs = [str(ref) for ref in (best.get("sourceRefs") or [])]
        if item_id not in refs:
            refs.append(item_id)
        best["sourceRefs"] = refs


def apply_requirement_skeleton(
    chapters: list[dict],
    tree: list[dict] | None,
    composition: list[dict] | None,
    rules: list[str] | None,
) -> None:
    """技术标二三级按招标需求原结构摆正：缺的补上，放错章的移回，顺序照原文。"""
    sections = [section for section in (tree or []) if isinstance(section, dict) and section.get("title")]
    if not sections or not isinstance(chapters, list):
        return
    hosts = _composition_hosts(chapters, composition)
    default = _default_requirement_host(hosts, chapters)
    if default is None:
        return
    rule_text = "；".join(rule for rule in (rules or []) if rule)[:500]
    order: dict[str, int] = {}
    for index, section in enumerate(sections):
        heading = _section_heading(section)
        order[heading] = index
        host = _host_for_section(section, hosts) or default
        section_node = _find_skeleton_node(chapters, number=str(section.get("clauseNo") or ""), name=str(section.get("title") or ""))
        item_nodes: list[dict] = []
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = _req_item_title(item)
            node = _find_skeleton_node(chapters, code=str(item.get("code") or ""), name=str(item.get("name") or ""))
            if node is None or node is section_node:
                node = {"title": title, "children": [], "part": "tech"}
            item_nodes.append((node, title, str(item.get("text") or "").strip()))
        if section_node is not None:
            _detach_child(chapters, section_node)
            section_node["title"] = heading
        else:
            section_node = {"title": heading, "children": [], "part": "tech"}
        section_node["part"] = "tech"
        written: list[dict] = []
        for node, title, text in item_nodes:
            _detach_child(chapters, node)
            _write_item_node(node, title, text, rule_text)
            written.append(node)
        item_nodes = written
        extras = [
            child
            for child in (section_node.get("children") or [])
            if isinstance(child, dict) and child not in item_nodes
        ]
        section_node["children"] = item_nodes + extras
        if not item_nodes and section.get("text"):
            _write_item_node(section_node, heading, str(section.get("text") or ""), rule_text)
            section_node["children"] = extras
        kids = host.setdefault("children", [])
        if not isinstance(kids, list):
            kids = []
            host["children"] = kids
        if section_node not in kids:
            kids.append(section_node)
    if any("偏离" in rule or "响应表" in rule for rule in (rules or [])):
        deviation = _find_skeleton_node(chapters, name="偏离") or _find_skeleton_node(chapters, name="偏差")
        if deviation is not None and deviation not in chapters:
            _detach_child(chapters, deviation)
        if deviation is None:
            deviation = {"title": "需求响应偏离表", "children": [], "part": "tech"}
            _write_item_node(deviation, "需求响应偏离表", rule_text, rule_text)
        kids = default.setdefault("children", [])
        if isinstance(kids, list):
            default["children"] = [deviation] + [child for child in kids if child is not deviation]
    for _title, host in hosts:
        kids = [child for child in (host.get("children") or []) if isinstance(child, dict)]
        head = [child for child in kids if re.search(r"偏离|偏差", _node_title(child))]
        body = [child for child in kids if child not in head]
        body.sort(key=lambda child: order.get(_node_title(child), 1000))
        host["children"] = head + body


def _assemble_outline(
    chapters: list[dict],
    *,
    composition: list[dict],
    tender_toc: dict | None,
    score_rules: list[dict],
    tech_text: str,
    business_text: str,
    tender_text: str,
    doc_kind: str,
    form_registry: list[dict] | None = None,
    form_mapper=None,
) -> tuple[dict, list[dict], list[str]]:
    """智能体目录 -> 对照组成清单和应答编号 -> 绑定条款 -> 台账。

    不补章、不合并、不把需求树塞进格式章。缺口写进 notes，由下一轮评审让智能体自己改。
    """
    from .req_ledger import attach_chapters, build_ledger, ledger_summary

    notes: list[str] = []
    if (doc_kind or "").strip().lower() == "business":
        from .tender_toc import is_bid_review_factor

        composition = [
            item
            for item in (composition or [])
            if isinstance(item, dict) and not is_bid_review_factor(str(item.get("title") or ""))
        ]
    if composition:
        promote_format_chapters(chapters, composition)
    chapters = drop_review_shells(chapters, composition, doc_kind)
    if (doc_kind or "").strip().lower() == "business":
        drop_tender_body_nodes(chapters, composition, tender_text)

    def check_composition() -> None:
        for problem in annotate_composition(chapters, composition):
            if problem not in notes:
                notes.append(problem)

    check_composition()
    _collapse_original_form_chapters(chapters, tender_toc)
    _attach_tender_refs(chapters, tender_toc, score_rules)
    bind_report = bind_requirements(chapters, tech_text, business_text, tender_text, doc_kind)
    if (doc_kind or "").strip().lower() != "business" and (tender_toc or {}).get("reqTree"):
        from .tender_toc import extract_response_rules

        apply_requirement_skeleton(chapters, tender_toc.get("reqTree"), composition, extract_response_rules(tender_text))
        _bind_skeleton_refs(chapters, tech_text, business_text)
    ensure_named_roles(chapters)
    coverage: dict = {"mergedLeaves": 0}
    kind_now = (doc_kind or "tech").strip().lower()
    has_deviation_form = False
    has_quote_form = False
    if form_registry:
        from .form_registry import has_kind

        has_deviation_form = has_kind(form_registry, "deviation")
        has_quote_form = has_kind(form_registry, "quote")
    for problem in requirement_coverage_problems(
        chapters,
        tech_text,
        business_text,
        tender_text,
        doc_kind,
        has_deviation_form=has_deviation_form,
        has_quote_form=has_quote_form,
    ):
        if problem not in notes:
            notes.append(problem)
    check_composition()
    _collapse_original_form_chapters(chapters, tender_toc)
    if form_registry:
        from .form_registry import apply_registry_to_tree

        coverage["formMapped"] = apply_registry_to_tree(chapters, form_registry, form_mapper)
    coverage["noSource"] = list(bind_report.get("noSource") or [])
    if kind_now != "business":
        ledger = build_ledger(tech_text, "", tender_text)
        # 技术标册同时承接商务应答里的方案类条目，台账里也要带上
        ledger.extend(
            e
            for e in build_ledger("", business_text, tender_text)
            if business_item_belongs_in_tech(e["text"][:24], e["text"])
        )
    else:
        ledger = [
            e
            for e in build_ledger("", business_text, tender_text)
            if not business_item_belongs_in_tech(e["text"][:24], e["text"])
        ]
    attach_chapters(ledger, chapters)
    coverage["ledger"] = ledger_summary(ledger)
    coverage["placementNotes"] = notes[:20]
    coverage["_chapters"] = chapters
    return coverage, ledger, notes


def outline_problems(chapters: list[dict], ledger: list[dict], notes: list[str] | None = None) -> list[str]:
    """目录的确定性检查：没挂条款的必须项、多叶子共用同一条款、没有依据的叶子、归位存疑的章。"""
    problems: list[str] = list(notes or [])
    for entry in ledger:
        if entry.get("mandatory") and not entry.get("chapters"):
            problems.append(
                f"必须项「{entry['id']}」还没挂到已有格式文件上：{str(entry.get('text') or '')[:40]}。"
                "只挂到格式节已有的文件下。评审标准不要为此新增章节。"
            )
    seen: dict[str, list[str]] = {}
    for node in _iter_chapter_nodes(chapters):
        if not _is_leaf(node) or is_original_form_title(_node_title(node)):
            continue
        req = re.sub(r"\s+", "", str(node.get("requirement") or ""))
        if len(req) >= 20:
            seen.setdefault(req, []).append(_node_title(node))
        if NO_SOURCE_MARK in str(node.get("idea") or ""):
            problems.append(f"「{_node_title(node)}」没有对应的招标条款，请改写标题或删除")
    for titles in seen.values():
        if len(titles) >= 2:
            problems.append("这些章节对应同一条招标条款，应合成一章：" + "、".join(titles[:6]))
    return problems


def outline_review_text(chapters: list[dict], limit: int = 12000) -> str:
    lines: list[str] = []

    def walk(nodes: list[dict], depth: int) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            refs = ",".join(node.get("sourceRefs") or [])
            lines.append("  " * depth + f"- {_node_title(node)}" + (f"（依据 {refs}）" if refs else ""))
            walk(node.get("children") or [], depth + 1)

    walk(chapters, 0)
    return "\n".join(lines)[:limit]



def _looks_like_function_name(title: str) -> bool:
    """短名词视为功能点名称；说明句视为功能描述。"""
    from .tender_toc import strip_heading_prefix

    t = strip_heading_prefix(title or "").strip()
    if not t or len(t) > 16:
        return False
    if t.endswith(("。", "；", ";", "？", "?")):
        return False
    if re.search(r"[，；]", t):
        return False
    if re.match(r"^(支持|须|必须|应当|应能|包括|因|对于)", t):
        return False
    if re.search(r"提供|全天候|无间断|小时内|接到采购人", t):
        return False
    if "进行" in t and any(k in t for k in ("统计", "预警", "操作", "管理", "设置")):
        return False
    return True


def _format_requirement_inventory(toc: dict | None) -> str:
    compose = (toc or {}).get("compose") or []
    tech = (toc or {}).get("tech") or []
    lines: list[str] = []
    if compose:
        lines.append(
            "【大标题骨架】以下条目来自本份招标书对响应文件/投标文件组成与格式的规定，用作目录大标题。"
            "名称与顺序以本份招标书为准。下级只展开采购需求、用户需求、技术标准、发包人要求，不要展开评标办法、合同条款和投标人须知："
        )
        for item in compose:
            pad = "  " * max(int(item.get("level") or 1) - 1, 0)
            lines.append(f"{pad}- {item.get('title', '')}")
        lines.append("")
    if tech:
        lines.append(
            "【应标细目】下列条款只在属于采购需求、用户需求、技术标准、发包人要求时，写入格式指定的那一章之下。"
            "评标办法、合同条款、投标人须知里的条目不要写入，也不得拆成与格式文件平级的章节。"
            "【名称】须原样做该章下级标题；【描述】只作覆盖依据，必须提炼短标题，禁止把描述当标题："
        )
        for item in tech:
            pad = "  " * max(int(item.get("level") or 1) - 1, 0)
            title = item.get("title") or ""
            req = (item.get("requirement") or "").strip()
            if _looks_like_function_name(title):
                lines.append(f"{pad}- 【名称】{_strip_generated_num(title)}")
                if req:
                    lines.append(f"{pad}  {req[:500]}")
            else:
                lines.append(f"{pad}- 【描述】须提炼功能点名，禁止用下列原文做标题：{title[:200]}")
                if req:
                    lines.append(f"{pad}  {req[:500]}")
    text = "\n".join(lines).strip()
    return text[:OUTLINE_INVENTORY_MAX]


_DOC_KIND_LABEL = {"tech": "技术标", "business": "商务标"}

# 内嵌全文的上限：短招标书直接贴进 prompt，省去分页调用；超过这个量就只给分页读原文的指引，
# 交给 read_tender(section="original") 多轮翻页通读，避免把超长原文硬塞进单次 prompt。
OUTLINE_INLINE_TENDER_MAX = 16000


def _doc_kind_instruction(doc_kind: str, page: dict | None, layout: dict | None) -> str:
    del page, layout
    kind = (doc_kind or "tech").strip().lower()
    if kind == "business":
        return (
            "本次只编制《商务标》分册。软件服务标、工程标、水利标的商务标都按这一份。"
            "一级章只用格式节里的商务文件，不展开填写栏。商务标不按篇幅加章。"
            "投标函附录若在格式节里单独列出，则保留。报价文件不进商务标。"
        )
    return (
        "本次只编制《软件服务标技术标》分册。"
        "一级章只用格式节里的技术文件。采购需求、用户需求、技术标准、发包人要求按招标书原结构挂在对应文件下："
        "二级是需求小节，三级是每一条需求，一条一个标题，不要合并。"
        "投标函、授权委托、资格、报价、业绩不要输出。不要为凑页数自拟章节。"
    )


def _build_outline_user_message(
    project_name: str,
    tender_text: str,
    tender_toc: dict | None,
    score_rules: list[dict],
    must_respond: list[dict],
    format_requirements: list | None = None,
    *,
    doc_kind: str = "tech",
    total_pages: int = 0,
    page: dict | None = None,
    layout: dict | None = None,
) -> str:
    label = _DOC_KIND_LABEL.get((doc_kind or "tech").strip().lower(), "技术标")
    lines = [
        f"项目名称：{project_name or '（未命名项目）'}",
        f"本次编制分册：{label}",
        "",
        _doc_kind_instruction(doc_kind, page, layout),
        "",
        "先检索格式节，再按该节列出的文件名编写目录。不要从第 1 页逐页翻到最后。",
        "",
    ]
    from .tender_toc import composition_for_volume, extract_bid_composition, extract_response_rules

    corpus = (tender_text or "").strip()
    composition = composition_for_volume(extract_bid_composition(corpus), doc_kind)
    rules = extract_response_rules(corpus)
    if composition:
        lines.append("下列文件名就是本次分册的一级章，按顺序，不要另起一级章：")
        for item in composition:
            lines.append(f"- {item.get('title', '')}")
        lines.append("")
    else:
        lines.append("没有抽出这份清单。不要套默认章节，也不要用评标办法、合同条款代替。")
        lines.append("")
    if rules:
        lines.append("本份招标书对应答写法的规定（正文照下列原句写，不要改成别的格式）：")
        for rule in rules:
            lines.append(f"- {rule}")
        lines.append("")
    else:
        lines.append("本份招标书没有抽出逐项应答写法。不要套用「满足/部分满足/不满足」或任何固定应答表。")
        lines.append("")
    req_tree = (tender_toc or {}).get("reqTree") if (doc_kind or "tech").strip().lower() != "business" else None
    if req_tree:
        lines.append("下列是招标书技术与功能需求的原结构。二级、三级照抄，一条一个标题，不要合并，不要改名：")
        lines.append(_requirement_tree_text(req_tree))
        lines.append("")
    if score_rules:
        lines.append("这些句子用来核对，不要写成章节：")
        for r in score_rules[:40]:
            lines.append(f"- [{r.get('dimension', '')}] 权重 {r.get('weight', 0)} 分：{r.get('detail', '')}")
        lines.append("")
    if must_respond:
        lines.append("这些句子用来核对，不要写成章节：")
        for m in must_respond[:40]:
            lines.append(f"- [{m.get('type', '')}] {m.get('clause', '')}")
        lines.append("")
    if format_requirements:
        lines.append("本份招标书对响应文件/投标文件组成与格式的规定（完整文件结构，供判断分册边界，不代表这次全部要输出）：")
        for item in format_requirements[:80]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            desc = str(item.get("desc") or "").strip()
            if title:
                lines.append(f"- {title}" + (f"：{desc}" if desc else ""))
        lines.append("")
    if corpus and len(corpus) <= OUTLINE_INLINE_TENDER_MAX:
        lines.append("----------上传的招标文件原文（未抽取、未改写，全文已贴在下面）----------")
        lines.append(corpus)
    elif corpus:
        lines.append(
            f"招标文件原文较长（约 {len(corpus)} 字），已经存入 read_tender(section=\"original\")，共约 {total_pages} 页。"
            "不要从第 1 页逐页翻到最后。用 query 检索「投标文件格式」「响应文件格式」「投标文件组成」「响应文件编制」「评分」，"
            "找到本份招标书列出投标文件应含哪些文件的那一节，不限第几章，读中后再编目录。"
        )
    else:
        lines.append("（未能读取上传的招标文件原文，如确有必要请调用 read_tender 核实。）")
    return "\n".join(lines)


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TITLE_NUM = re.compile(
    r"^(?:"
    r"第[0-9一二三四五六七八九十百]+[章节篇]\s*"
    r"|[一二三四五六七八九十百]+、\s*"
    r"|[（(]\s*[一二三四五六七八九十百]+\s*[）)]\s*"
    r"|\d+\.\d+(?:\.\d+)*[.．、]?\s*"
    r"|\d+[.．、）)]\s*"
    r")"
)


def _strip_generated_num(title: str) -> str:
    from .tender_toc import strip_heading_prefix

    t = (title or "").strip()
    t = re.sub(r"^[\*★☆●•]+\s*", "", t)
    t = strip_heading_prefix(t)
    prev = None
    while prev != t:
        prev = t
        t = _TITLE_NUM.sub("", t).strip()
    return t


def _is_requirement_sentence(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith(("。", "；", ";", "？", "?")):
        return True
    if re.match(r"^(支持|须|必须|应当|应能|包括|因|对于|若|当)", t):
        return True
    if re.search(
        r"提供.{0,24}(?:咨询|受理|支持|服务)|全天候|无间断|小时内|接到采购人|组织架构调整",
        t,
    ):
        return True
    return len(t) > 24


def _compact_catalog_title(title: str) -> str:
    """把误当作目录的招标原句收成短标题；已经是目录名的保持不动。"""
    t = _strip_generated_num(title).strip("。；;，,：: ")
    if not t:
        return t
    if not _is_requirement_sentence(t) and len(t) <= 24:
        return t
    if re.search(r"服务热线|客户服务热线", t) and re.search(r"提供|全天候|24小时|7\s*天", t):
        return "全天候服务热线"
    if "基础数据" in t and re.search(r"须对|须在|组织架构|人员变动", t):
        return "组织变更数据修改"
    for sep in (
        "须包含",
        "必须包含",
        "应包含",
        "支持对",
        "包括但不限于",
        "提供",
        "须对",
        "须在",
        "应当",
        "应能",
        "必须",
        "支持",
        "包括",
        "须",
    ):
        if sep not in t:
            continue
        head, tail = t.split(sep, 1)[0].strip(" ，,的"), t.split(sep, 1)[1]
        if 2 <= len(head) <= 16:
            return head
        if sep in ("须对", "须在") and tail:
            if "基础数据" in tail:
                return "组织变更数据修改" if re.search(r"组织|架构|人员", t) else "基础数据修改"
            m = re.search(r"([^、，,]{2,10})(?:等)?(?:基础数据)?(?:修改|完成|调整|变更)", tail)
            if m:
                word = m.group(1).strip("的")
                if 2 <= len(word) <= 10:
                    return f"{word}修改" if "修改" in tail else word
        if not head and sep == "支持":
            m = re.search(r"进行([^，,。；;]{2,12})", tail)
            if m:
                word = m.group(1).strip("的与及")
                if 2 <= len(word) <= 12:
                    return word
            continue
    m = re.search(r"进行([^，,。；;]{2,12})", t)
    if m:
        word = m.group(1).strip("的与及")
        if 2 <= len(word) <= 12:
            return word
    cut = re.split(r"[，,、；;]", t, maxsplit=1)[0].strip()
    if 4 <= len(cut) <= 16:
        return cut
    if len(t) > 12:
        return t[:12].rstrip("、，,的与及")
    return t


def _compact_chapter_titles(nodes: list[dict]) -> None:
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if n.get("title"):
            n["title"] = _compact_catalog_title(str(n["title"]))
        kids = n.get("children")
        if isinstance(kids, list):
            _compact_chapter_titles(kids)


_MD_IDEA_LINE = re.compile(r"^思路[：:]\s*(.+)$")


def _markdown_to_chapters(text: str, compact: bool = True) -> list[dict]:
    """把目录 Markdown 转成章节树。compact=False 时保留完整标题，
    给施工组织设计用：它的章名就是评分项原文，压短就对不上评分表了。"""
    from .writer_tool_runtime import parse_source_refs

    entries: list[dict] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("```") or set(line) <= set("-—* "):
            continue
        match = _MD_HEADING.match(line)
        if not match:
            if not entries:
                continue
            idea = _MD_IDEA_LINE.match(line)
            if idea:
                entries[-1]["idea"] = idea.group(1).strip()[:8000]
                continue
            refs = parse_source_refs(line)
            if refs:
                entries[-1]["refs"].extend(ref for ref in refs if ref not in entries[-1]["refs"])
            continue
        title = _strip_generated_num(match.group(2))
        title = _compact_catalog_title(title) if compact else title.strip()
        if not title:
            continue
        entries.append({"level": len(match.group(1)), "title": title, "refs": [], "idea": ""})
    if not entries:
        return []
    min_lv = min(item["level"] for item in entries)
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for entry in entries:
        level = entry["level"] - min_lv + 1
        node: dict = {"title": entry["title"], "children": []}
        if entry["refs"]:
            node["sourceRefs"] = entry["refs"]
        if entry["idea"]:
            node["idea"] = entry["idea"]
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1]["children"].append(node)
        stack.append((level, node))
    return roots


def _chapters_from_llm_output(content: str) -> list[dict]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    chapters: list[dict] = []
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("chapters"), list):
            chapters = data["chapters"]
        elif isinstance(data, list):
            chapters = data
    if not chapters:
        chapters = _markdown_to_chapters(text)
    if chapters:
        _compact_chapter_titles(chapters)
    return chapters


def _count_outline_leaves(nodes: list[dict]) -> int:
    total = 0
    for x in nodes:
        if not isinstance(x, dict):
            continue
        kids = x.get("children")
        if isinstance(kids, list) and kids:
            total += _count_outline_leaves(kids)
        else:
            total += 1
    return total


def _iter_chapter_nodes(nodes: list[dict]):
    for n in nodes:
        if not isinstance(n, dict):
            continue
        yield n
        kids = n.get("children")
        if isinstance(kids, list):
            yield from _iter_chapter_nodes(kids)


def _compose_requirement_blob(title: str, tender_toc: dict | None) -> str:
    from .tender_toc import strip_heading_prefix

    core = strip_heading_prefix(title or "")
    parts = [core]
    for h in (tender_toc or {}).get("compose") or []:
        ht = strip_heading_prefix(h.get("title") or "")
        if ht and core and (ht == core or ht in core or core in ht):
            parts.append(h.get("requirement") or "")
    return "\n".join(parts)


def _requirement_host_score(node: dict, tender_toc: dict | None) -> int:
    from .tender_toc import strip_heading_prefix

    title = strip_heading_prefix(node.get("title") or "")
    blob = _compose_requirement_blob(title, tender_toc)
    blob += "\n" + str(node.get("idea") or "") + "\n" + str(node.get("requirement") or "")
    score = 0
    if re.search(r"按.{0,30}目录编制|逐条进行描述|逐条描述|逐条响应", blob):
        score += 20
    if re.search(r"按.{0,20}条款", blob) and re.search(r"逐条|目录", blob):
        score += 8
    return score


def _find_requirement_host(chapters: list[dict], tender_toc: dict | None) -> dict | None:
    best = None
    best_score = 0
    for n in _iter_chapter_nodes(chapters):
        if is_original_form_title(str(n.get("title") or "")):
            continue
        score = _requirement_host_score(n, tender_toc)
        if score > best_score:
            best_score = score
            best = n
    return best if best_score > 0 else None


def _title_overlap_score(a: str, b: str) -> int:
    from .tender_toc import strip_heading_prefix

    x = re.sub(r"\s+", "", strip_heading_prefix(a or ""))
    y = re.sub(r"\s+", "", strip_heading_prefix(b or ""))
    for suffix in ("解决方案", "响应方案", "实施方案", "方案", "要求", "内容"):
        if x.endswith(suffix) and len(x) > len(suffix) + 1:
            x = x[: -len(suffix)]
        if y.endswith(suffix) and len(y) > len(suffix) + 1:
            y = y[: -len(suffix)]
    if not x or not y:
        return 0
    if x == y or x in y or y in x:
        return 10 + min(len(x), len(y))
    best = 0
    for i in range(len(x)):
        for j in range(i + 4, len(x) + 1):
            if x[i:j] in y:
                best = max(best, j - i)
    return best


def _ensure_children(node: dict) -> list:
    kids = node.get("children")
    if not isinstance(kids, list):
        kids = []
        node["children"] = kids
    return kids


def _mark_tree_part(node: dict, part: str) -> None:
    node["part"] = part
    kids = node.get("children")
    if isinstance(kids, list):
        for child in kids:
            if isinstance(child, dict):
                _mark_tree_part(child, part)


def _attach_source_node(host: dict, source: dict) -> None:
    from .tender_toc import strip_heading_prefix

    _mark_tree_part(source, "tech")
    kids = _ensure_children(host)
    title = strip_heading_prefix(str(source.get("title") or ""))
    existing = {strip_heading_prefix(str(c.get("title") or "")) for c in kids if isinstance(c, dict)}
    if title and title in existing:
        return
    kids.append(source)


def _fill_format_chapters_with_requirements(chapters: list[dict], tender_toc: dict | None) -> None:
    """按标题/主题对应，把招标书需求树分到各格式章下，而不是整棵塞进一章。"""
    from .tender_toc import headings_to_chapters, strip_heading_prefix

    tech = (tender_toc or {}).get("tech") or []
    if not chapters or not tech:
        return
    tech_tree = headings_to_chapters(tech)
    if not tech_tree:
        return

    format_nodes = [n for n in _iter_chapter_nodes(chapters)]
    leftovers: list[dict] = []
    for src in tech_tree:
        best = None
        best_score = 0
        for fmt in format_nodes:
            if is_original_form_title(str(fmt.get("title") or "")):
                continue
            score = _title_overlap_score(str(fmt.get("title") or ""), str(src.get("title") or ""))
            if score > best_score:
                best = fmt
                best_score = score
        if best is not None and best_score >= 4:
            _attach_source_node(best, src)
        else:
            leftovers.append(src)

    if leftovers:
        host = _find_requirement_host(chapters, tender_toc)
        if host is None:
            host = next(
                (
                    c
                    for c in chapters
                    if isinstance(c, dict) and not is_original_form_title(str(c.get("title") or ""))
                ),
                None,
            )
        if host is None:
            host = chapters[-1]
        for src in leftovers:
            _attach_source_node(host, src)

    for fmt in format_nodes:
        kids = fmt.get("children")
        if not isinstance(kids, list):
            continue
        kept: list[dict] = []
        for child in kids:
            if not isinstance(child, dict):
                continue
            title = strip_heading_prefix(str(child.get("title") or ""))
            if re.search(r"目录编制|逐条描述|逐条响应", title) and _count_outline_leaves([child]) <= 1:
                continue
            kept.append(child)
        kids[:] = kept


def _heading_index_items(toc: dict | None) -> list[dict]:
    from .tender_toc import strip_heading_prefix

    items: list[dict] = []
    for key in ("tech", "compose"):
        for h in (toc or {}).get(key) or []:
            title = strip_heading_prefix(h.get("title") or "")
            items.append(
                {
                    "title": title,
                    "core": re.sub(r"\s+", "", title),
                    "index": h.get("index"),
                    "req": (h.get("requirement") or "").strip(),
                    "part": "tech" if key == "tech" else "business",
                }
            )
    return items


def _best_heading(title: str, items: list[dict]) -> dict | None:
    from .tender_toc import strip_heading_prefix

    core = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    for suffix in ("解决方案", "响应方案", "实施方案", "方案"):
        if core.endswith(suffix) and len(core) > len(suffix) + 1:
            core = core[: -len(suffix)]
            break
    if len(core) < 2:
        return None
    exact = [it for it in items if it["core"] == core]
    if exact:
        return exact[0]
    cands = [
        it
        for it in items
        if len(it["core"]) >= 4 and (it["core"] in core or core in it["core"])
    ]
    if not cands:
        return None
    cands.sort(key=lambda it: len(it["core"]), reverse=True)
    return cands[0]


def _match_dimension(title: str, score_rules: list[dict]) -> str | None:
    t = title or ""
    for r in score_rules:
        dim = r.get("dimension")
        if isinstance(dim, str) and dim and dim in t:
            return dim
    return None


_GENERIC_OUTLINE_IDEA = re.compile(r"^对应「[^」]*」，须严格按招标文件相关条款应答，不得漏项。?$")
_TECH_SCHEME_HINT = re.compile(r"部署|接口|实施|运维|安全|迁移|售后|演示")
_BUSINESS_FORM_HINT = re.compile(r"投标函|授权委托|资格|报价|业绩|财务|信用|资信|承诺")


def _short_requirement_title(raw: str) -> tuple[str, str]:
    text = re.sub(r"^(?:（\d{1,2}）|\(\d{1,2}\)|\d{1,2}[、.．])\s*", "", (raw or "").strip())
    split_at = text.find("：")
    if split_at < 0:
        split_at = text.find(":")
    if 0 < split_at <= 24:
        title, body = text[:split_at].strip(), text[split_at + 1 :].strip()
    else:
        title, body = text, text
    title = _compact_catalog_title(title) or title[:12]
    return title, body or text


def business_item_belongs_in_tech(title: str, body: str = "") -> bool:
    """部署、接口、实施、安全、运维、演示方案进技术标；函件、报价、资格留在商务标。"""
    name = title or ""
    if is_original_form_title(name) or _BUSINESS_SKIP_TITLE.search(name):
        return False
    if _BUSINESS_FORM_HINT.search(name) and not _TECH_SCHEME_HINT.search(name):
        return False
    return bool(_TECH_SCHEME_HINT.search(name) or _TECH_SCHEME_HINT.search(body or ""))


def _idea_from_requirement(title: str, body: str) -> str:
    detail = (body or "").strip()
    if detail:
        return f"【对应招标「{title}」】{detail}"[:8000]
    return f"【对应招标「{title}」】按该条款全部要求逐项应答，不得漏项。"


def _outline_title_blob(nodes: list[dict]) -> str:
    return "\n".join(str(node.get("title") or "") for node in _iter_chapter_nodes(nodes))


def _coverage_host(chapters: list[dict]) -> dict:
    preferred = None
    for node in _iter_chapter_nodes(chapters):
        title = str(node.get("title") or "")
        if is_original_form_title(title):
            continue
        if "逐项" in title or "功能需求" in title:
            return node
        if preferred is None and "技术" in title:
            preferred = node
    if preferred is not None:
        return preferred
    for node in chapters:
        if isinstance(node, dict) and not is_original_form_title(str(node.get("title") or "")):
            return node
    host = {"title": "技术方案", "children": []}
    chapters.append(host)
    return host


PARENT_CONTEXT_MARK = "【上级条款全文"
SUMMARY_CHAPTER_MARK = "【汇总章】"
NO_SOURCE_MARK = "【未找到对应招标条款】"
_ITEM_NUM_PREFIX = re.compile(r"^(?:（\d{1,2}）|\(\d{1,2}\)|\d{1,2}[、.．])\s*")


def _clean_item_text(raw: str) -> str:
    return _ITEM_NUM_PREFIX.sub("", (raw or "").strip()).strip()


def _is_generic_idea(idea: str) -> bool:
    text = (idea or "").strip()
    return not text or bool(_GENERIC_OUTLINE_IDEA.match(text))


def _title_core(title: str) -> str:
    return re.sub(r"\s+", "", _compact_catalog_title(title) or title or "")


def _clauses_for_title(body: str, title: str) -> str:
    """从上级条款里挑出和本章标题相关的分句；一句都挑不出时返回空串。"""
    core = _title_core(title)
    for suffix in ("方案", "要求", "管理", "设计", "说明"):
        if core.endswith(suffix) and len(core) > len(suffix) + 1:
            core = core[: -len(suffix)]
            break
    if len(core) < 2:
        return ""
    grams = {core[i : i + 2] for i in range(len(core) - 1)}
    need = max(2, (len(grams) + 1) // 2) if len(grams) > 1 else 1
    picked: list[str] = []
    for clause in re.split(r"[。；;\n，]", body or ""):
        text = clause.strip()
        if not text:
            continue
        compact = re.sub(r"\s+", "", text)
        hits = sum(1 for g in grams if g in compact)
        if core in compact or hits >= need:
            picked.append(text)
    return "；".join(picked)


def _node_title(node: dict) -> str:
    return str(node.get("title") or "").strip()


def _composition_key(title: str) -> str:
    """比对大章是否同一章用的键。连接词也去掉：须知写「身份证明或授权委托书」、
    格式章写「身份证明和授权委托书」，指的是同一章。"""
    return re.sub(r"[\s。；;，,：:、·•]|[或和及与]", "", title or "")


def _is_same_large_chapter(official: str, other: str) -> bool:
    left = _composition_key(official)
    right = _composition_key(other)
    if not left or not right:
        return False
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    return len(short) >= 4 and short in long


_REVIEW_SHELL_TITLES = {
    "形式评审",
    "资格评审",
    "响应性评审",
    "投标文件组成",
    "响应文件组成",
    "投标文件的组成",
    "响应文件的组成",
    "投标有效期",
}
_REVIEW_SHELL_LEAD = re.compile(r"^符合.{0,30}(格式的要求|格式要求)$")
_QUOTE_SHELL_TITLES = {"投标报价", "报价文件", "最高投标限价"}


def _plain_title(title: str) -> str:
    from .tender_toc import strip_heading_prefix

    return re.sub(r"[\s\"“”「」]", "", strip_heading_prefix(title or ""))


def _is_review_shell(title: str, composition: list[dict], *, doc_kind: str) -> bool:
    """评标表里的「符合格式要求」「形式评审」不是投标文件。组成清单里真有的文件名保留。"""
    plain = _plain_title(title)
    if not plain:
        return False
    # 只在标题和组成条目是同一个文件名时保留。「投标文件格式」出现在「符合第七章投标文件格式的要求」里，仍是评标标准。
    official = {_plain_title(str(item.get("title") or "")) for item in composition}
    if plain in official:
        return False
    if plain in _REVIEW_SHELL_TITLES or _REVIEW_SHELL_LEAD.match(plain):
        return True
    return (doc_kind or "").strip().lower() == "business" and plain in _QUOTE_SHELL_TITLES


def drop_review_shells(chapters: list[dict], composition: list[dict] | None, doc_kind: str = "tech") -> list[dict]:
    """去掉评标标准套出来的空壳。空壳下面如果已经有格式文件，把那些文件提升为同级。"""
    slots = [item for item in (composition or []) if isinstance(item, dict)]

    def clean(nodes: list[dict]) -> list[dict]:
        kept: list[dict] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get("children")
            node["children"] = clean(children) if isinstance(children, list) else []
            if _is_review_shell(_node_title(node), slots, doc_kind=doc_kind):
                kept.extend(node["children"])
                continue
            kept.append(node)
        return kept

    chapters[:] = clean(chapters)
    return chapters


_TENDER_BODY_CHAPTER = re.compile(r"评标办法|评标方法|合同条款|合同格式|通用合同|专用合同|投标人须知")
_FORMAT_CHAPTER = re.compile(r"投标文件格式|响应文件格式|内容及格式|内容与格式|投标文件编制|响应文件编制")
_MAJOR_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+章")
_NOT_A_BID_FILE = re.compile(
    r"未出现|签字盖章|机器码|标识码|上传地址|上传IP|IP地址|最高投标限价|价格清单|"
    r"限价控制|费用包含|评审因素|评审标准|大写金额|已标价工程量清单|符合第"
)
_ROLE_WORD = re.compile(r"项目经理|技术负责人|施工负责人|设计负责人|安全负责人|质量负责人")


def _short_heading(line: str) -> str:
    from .tender_toc import strip_heading_prefix

    plain = re.sub(r"[\s\"“”「」]", "", strip_heading_prefix(line or ""))
    if not plain or len(plain) < 2 or len(plain) > 22:
        return ""
    if re.search(r"[。；;]", plain):
        return ""
    return plain


def _chapter_heading_sets(text: str) -> tuple[set[str], set[str]]:
    """返回（评标办法/合同条款/投标人须知里的短标题，格式节里的短标题）。"""
    body: set[str] = set()
    form: set[str] = set()
    bucket: set[str] | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or not _MAJOR_CHAPTER.match(line):
            if bucket is not None:
                heading = _short_heading(line)
                if heading:
                    bucket.add(heading)
            continue
        if _FORMAT_CHAPTER.search(line):
            bucket = form
        elif _TENDER_BODY_CHAPTER.search(line):
            bucket = body
        else:
            bucket = None
    return body, form


def drop_tender_body_nodes(chapters: list[dict], composition: list[dict] | None, tender_text: str) -> list[dict]:
    """评标办法、合同条款、投标人须知是招标书自己的内容，不是应标章节。"""
    if not isinstance(chapters, list):
        return chapters
    body, form = _chapter_heading_sets(tender_text)
    official = {_plain_title(str(item.get("title") or "")) for item in (composition or []) if isinstance(item, dict)}

    from .tender_toc import is_bid_review_factor

    def protected(title: str) -> bool:
        plain = _plain_title(title)
        if not plain or is_bid_review_factor(title):
            return False
        if plain in official or plain in form or "附录" in plain:
            return True
        return bool(_ROLE_WORD.search(plain)) and not _NOT_A_BID_FILE.search(plain)

    def foreign(title: str) -> bool:
        plain = _plain_title(title)
        if not plain or protected(title):
            return False
        if plain in body or is_bid_review_factor(title) or _NOT_A_BID_FILE.search(plain):
            return True
        return False

    def clean(nodes: list[dict], parent_foreign: bool) -> list[dict]:
        kept: list[dict] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get("children")
            kids = children if isinstance(children, list) else []
            drop = parent_foreign or foreign(_node_title(node))
            if drop and not protected(_node_title(node)):
                kept.extend(clean(kids, True))
                continue
            node["children"] = clean(kids, False)
            kept.append(node)
        return kept

    chapters[:] = clean(chapters, False)
    return chapters


def _matches_format_file(title: str, official: str) -> bool:
    """节点是不是这份格式文件。评标句子里夹着文件名，不算。"""
    if _is_review_shell(title, [], doc_kind="business"):
        return False
    if _plain_title(title) == _plain_title(official):
        return True
    return _is_same_large_chapter(official, title)


def promote_format_chapters(chapters: list[dict], composition: list[dict] | None) -> list[dict]:
    """本份招标书列出的投标文件就是一级章，不限第几章。外面再套的评标句子或自拟总标题去掉。"""
    officials = [
        str(item.get("title") or "").strip()
        for item in (composition or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    if not officials or not isinstance(chapters, list):
        return chapters
    found: dict[str, dict] = {}

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = _node_title(node)
            for official in officials:
                if not _matches_format_file(title, official):
                    continue
                current = found.get(official)
                if current is None or _plain_title(title) == _plain_title(official):
                    found[official] = node
            children = node.get("children")
            if isinstance(children, list):
                walk(children)

    walk(chapters)
    ordered: list[dict] = []
    used: set[int] = set()
    for item in composition or []:
        if not isinstance(item, dict):
            continue
        official = str(item.get("title") or "").strip()
        if not official:
            continue
        node = found.get(official)
        if node is None or id(node) in used:
            volume = str(item.get("volume") or "").strip()
            node = {"title": official, "children": [], "composition": True}
            if volume in ("tech", "business"):
                node["part"] = volume
        else:
            used.add(id(node))
            node["title"] = official
            node["composition"] = True
            children = node.get("children") if isinstance(node.get("children"), list) else []
            node["children"] = [
                child
                for child in children
                if isinstance(child, dict)
                and not any(_matches_format_file(_node_title(child), other) for other in officials if other != official)
            ]
        ordered.append(node)
    chapters[:] = ordered
    return chapters


def ensure_composition_present(chapters: list[dict], composition: list[dict] | None) -> None:
    """格式章点名、目录里还没有的文件，补成一级章。不改已有章的顺序，也不删多出来的章。"""
    if not isinstance(chapters, list):
        return
    present = [_node_title(node) for node in chapters if isinstance(node, dict)]
    for item in composition or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or any(_is_same_large_chapter(title, name) for name in present):
            continue
        volume = str(item.get("volume") or "").strip()
        node: dict = {"title": title, "children": [], "composition": True}
        if volume in ("tech", "business"):
            node["part"] = volume
        chapters.append(node)
        present.append(title)


_NAMED_ROLES = ("技术负责人", "施工技术负责人")


def ensure_named_roles(chapters: list[dict]) -> None:
    """项目管理机构已经按岗位拆开时，条款点了名但没有节点的岗位补进去。"""
    host = None
    for node in _iter_chapter_nodes(chapters):
        kids = [_node_title(child) for child in (node.get("children") or []) if isinstance(child, dict)]
        if any("项目经理" in kid for kid in kids) and any("负责人" in kid for kid in kids):
            host = node
            break
    if host is None:
        return
    blob = "\n".join(
        f"{_node_title(node)}\n{node.get('requirement') or ''}\n{node.get('idea') or ''}"
        for node in _iter_chapter_nodes(chapters)
    )
    children = host.setdefault("children", [])
    if not isinstance(children, list):
        return
    have = " ".join(_node_title(child) for child in children if isinstance(child, dict))
    for role in _NAMED_ROLES:
        if role in have or role not in blob:
            continue
        children.append({"title": role, "children": [], "part": host.get("part") or "business"})
        have = f"{have} {role}"


def annotate_composition(chapters: list[dict], items: list[dict] | None) -> list[str]:
    """按本份组成清单给一级章打标并对齐措辞，不改顺序、不增删章、不搬动小节。

    打上 composition 的章保留完整标题：格式章的章名常超过十六字，不能压成短标题。
    对不上清单的地方作为问题返回，交给下一轮评审重编，而不是直接改写智能体编好的目录。
    重复调用不会改变结果。
    """
    slots = [
        {"title": str(item.get("title") or "").strip(), "volume": str(item.get("volume") or "").strip()}
        for item in (items or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    if not slots or not isinstance(chapters, list):
        return []
    problems: list[str] = []
    order: list[int] = []
    used: set[int] = set()
    for node in chapters:
        if not isinstance(node, dict):
            continue
        title = _node_title(node)
        if not title:
            continue
        hit = next(
            (i for i, slot in enumerate(slots) if i not in used and _is_same_large_chapter(slot["title"], title)),
            -1,
        )
        if hit < 0:
            problems.append(f"一级章「{title}」不在本份组成清单里，请挂到最对应的大章下面，不要另起一级章")
            continue
        used.add(hit)
        order.append(hit)
        slot = slots[hit]
        node["composition"] = True
        node["title"] = slot["title"]
        if slot["volume"] in ("tech", "business") and node.get("part") not in ("tech", "business", "form"):
            node["part"] = slot["volume"]
    for index, slot in enumerate(slots):
        if index not in used:
            problems.append(f"组成清单里的「{slot['title']}」没有对应的一级章，请按原文名称补上")
    if order != sorted(order):
        problems.append(
            "一级章顺序与本份组成清单不一致，请按清单原文顺序重排："
            + "、".join(slot["title"] for slot in slots)
        )
    return problems


def _set_node_source(node: dict, refs: list[str], items: dict[str, str], part: str = "tech") -> None:
    body = "\n".join(_clean_item_text(items[ref]) for ref in refs if ref in items).strip()
    if not body:
        return
    node["sourceRefs"] = list(refs)
    node["requirement"] = body
    node["idea"] = _idea_from_requirement(_node_title(node), body)
    node["aiIdea"] = node["idea"]
    node["part"] = part if part in ("tech", "business") else "tech"


def _search_original_snippet(corpus: str, title: str, limit: int = 600) -> str:
    core = _title_core(title)
    if len(core) < 3 or not corpus:
        return ""
    lines: list[str] = []
    for line in corpus.splitlines():
        if core in re.sub(r"\s+", "", line):
            text = line.strip()
            if text and text not in lines:
                lines.append(text)
        if len(lines) >= 3:
            break
    return "\n".join(lines)[:limit]


def _is_leaf(node: dict) -> bool:
    kids = node.get("children")
    return not (isinstance(kids, list) and kids)


def bind_requirements(
    chapters: list[dict],
    tech_text: str,
    business_text: str = "",
    tender_text: str = "",
    doc_kind: str = "tech",
) -> dict:
    """按条目编号把招标条款原文挂到节点上，并把没挂上的节点如实标出来。

    1. 节点的「依据」编号 -> 该条原文成为 requirement，编写思路带上条款全文（含数字、期限）。
    2. 没有依据的下级节点沿用上级条款，只挑出和本章标题相关的分句；挑不出就带上级全文并标注。
    3. 都没有时在招标原文里按标题检索；仍没有就写明「未找到对应招标条款」，计入报告。
    """
    from .writer_tool_runtime import requirement_item_map

    items = requirement_item_map({"tech": tech_text, "business": business_text})
    report: dict = {"noSource": [], "boundByModel": 0, "bound": 0}
    volume_part = "business" if (doc_kind or "tech").strip().lower() == "business" else "tech"
    cited: set[str] = set()

    def walk(nodes: list[dict], parent: tuple[str, str] | None) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            title = _node_title(node)
            if is_original_form_title(title):
                continue
            if volume_part == "business" and node.get("part") != "form":
                node["part"] = "business"
            refs = [ref for ref in (node.get("sourceRefs") or []) if ref in items]
            context: tuple[str, str] | None = parent
            if refs:
                _set_node_source(node, refs, items, volume_part)
                cited.update(refs)
                report["boundByModel"] += 1
                context = (title, str(node.get("requirement") or ""))
            else:
                node.pop("sourceRefs", None)
                own_req = str(node.get("requirement") or "").strip()
                if own_req:
                    context = (title, own_req)
                elif parent and parent[1]:
                    piece = _clauses_for_title(parent[1], title)
                    if piece:
                        node["requirement"] = piece
                        node["idea"] = (
                            f"【对应招标「{parent[0]}」下的「{title}」】{piece}"
                        )[:8000]
                    else:
                        node["requirement"] = parent[1]
                        node["idea"] = (
                            f"{PARENT_CONTEXT_MARK}，本章只答与「{title}」相关的部分】{parent[1]}"
                        )[:8000]
                    node["aiIdea"] = node["idea"]
                elif _is_leaf(node):
                    snippet = _search_original_snippet(tender_text, title)
                    if snippet:
                        node["requirement"] = snippet
                        node["idea"] = f"【对应招标原文「{title}」】{snippet}"[:8000]
                    else:
                        node["idea"] = f"{NO_SOURCE_MARK}请对照招标文件补充「{title}」的响应要求。"
                        report["noSource"].append(title)
                    node["aiIdea"] = node["idea"]
                elif _is_generic_idea(str(node.get("idea") or "")):
                    node["idea"] = f"本章总述「{title}」，概括下级各节的响应思路，条款细节写在下级章节。"
                    node["aiIdea"] = node["idea"]
            kids = node.get("children")
            if isinstance(kids, list) and kids:
                walk(kids, context)
                if context is not None and context is not parent:
                    _assign_residual_facts(node, context[1])

    walk(chapters, None)
    report["cited"] = sorted(cited)
    return report


FACTS_MARK = "【本章必须写明指标："


def _leaf_descendants(node: dict) -> list[dict]:
    leaves: list[dict] = []
    for child in node.get("children") or []:
        if not isinstance(child, dict) or is_original_form_title(_node_title(child)):
            continue
        if _is_leaf(child):
            leaves.append(child)
        else:
            leaves.extend(_leaf_descendants(child))
    return leaves


def _assign_residual_facts(node: dict, clause: str) -> None:
    """上级条款里的数字指标，若下级各章切出来的分句都没覆盖，就指给第一个沿用上级全文的叶子章去写，
    避免条款只写在不撰写正文的上级节点上，数字最终没人答。"""
    from .writer_tool_runtime import extract_hard_facts

    facts = extract_hard_facts(clause)
    if not facts:
        return
    leaves = _leaf_descendants(node)
    if not leaves:
        return
    covered: set[str] = set()
    for leaf in leaves:
        idea = str(leaf.get("idea") or "")
        if PARENT_CONTEXT_MARK in idea:
            continue
        covered.update(extract_hard_facts(str(leaf.get("requirement") or "")))
    residual = [fact for fact in facts if fact not in covered]
    if not residual:
        return
    target = next((leaf for leaf in leaves if PARENT_CONTEXT_MARK in str(leaf.get("idea") or "")), leaves[0])
    idea = str(target.get("idea") or "")
    if FACTS_MARK in idea:
        return
    target["idea"] = (idea + f"\n{FACTS_MARK}{'、'.join(residual)}】")[:8000]
    target["aiIdea"] = target["idea"]


SUBPOINTS_MARK = "【本章按小节逐点应答："


def _req_key(node: dict) -> str:
    return re.sub(r"\s+", "", str(node.get("requirement") or ""))


def merge_shared_requirement_leaves(chapters: list[dict]) -> int:
    """同一条款被拆成多个叶子章时合成一章，原始需求只贴一次。

    判断依据：同一个上级下的叶子章，要么只能沿用上级全文，要么各自的条款原文逐字相同。
    全部下级都在这一组时，上级自己成为叶子章；否则保留组里第一章。被合并的小点标题写进编写思路，
    正文里用小节区分。返回合并掉的叶子数。
    """
    merged = 0

    def is_shared_leaf(kid: dict) -> bool:
        return _is_leaf(kid) and not is_original_form_title(_node_title(kid)) and not kid.get("formKeys")

    def walk(nodes: list[dict]) -> None:
        nonlocal merged
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kids = [k for k in (node.get("children") or []) if isinstance(k, dict)]
            if not kids:
                continue
            walk(kids)
            groups: dict[str, list[dict]] = {}
            for kid in kids:
                if not is_shared_leaf(kid):
                    continue
                if PARENT_CONTEXT_MARK in str(kid.get("idea") or ""):
                    key = _req_key(node) or _req_key(kid)
                else:
                    key = _req_key(kid)
                if len(key) >= 20:
                    groups.setdefault(key, []).append(kid)
            for key, group in groups.items():
                if len(group) < 2:
                    continue
                titles = [_node_title(k) for k in group if _node_title(k)]
                all_kids = len(group) == len(kids)
                host = node if all_kids else group[0]
                rest = [k for k in group if k is not host]
                if all_kids:
                    base = group[0]
                    for field in ("requirement", "sourceRefs"):
                        if base.get(field) and not host.get(field):
                            host[field] = base[field]
                    refs: list = []
                    for kid in group:
                        for ref in kid.get("sourceRefs") or []:
                            if ref not in refs:
                                refs.append(ref)
                    if refs:
                        host["sourceRefs"] = refs
                    node["children"] = []
                else:
                    node["children"] = [k for k in kids if not any(k is r for r in rest)]
                host["idea"] = _idea_from_requirement(_node_title(host), str(host.get("requirement") or ""))
                idea = str(host.get("idea") or "")
                if SUBPOINTS_MARK not in idea:
                    idea = (idea + f"\n{SUBPOINTS_MARK}{'；'.join(titles)}】")[:8000]
                    host["idea"] = idea
                    host["aiIdea"] = idea
                merged += len(rest) if not all_kids else len(group)
                kids = [k for k in (node.get("children") or []) if isinstance(k, dict)]

    walk(chapters)
    return merged


def _tree_cited_ids(chapters: list[dict]) -> set[str]:
    cited: set[str] = set()
    for node in _iter_chapter_nodes(chapters):
        for ref in node.get("sourceRefs") or []:
            cited.add(str(ref))
    return cited


def _find_title_match(chapters: list[dict], title: str) -> dict | None:
    core = _title_core(title)
    if len(core) < 2:
        return None
    for node in _iter_chapter_nodes(chapters):
        if is_original_form_title(_node_title(node)):
            continue
        current = _title_core(_node_title(node))
        if current == core or (len(core) >= 3 and core in current):
            return node
    return None


def ensure_tech_requirement_coverage(
    chapters: list[dict],
    tech_text: str,
    business_text: str = "",
    doc_kind: str = "tech",
    report: dict | None = None,
) -> list[dict]:
    """技术标每一条应答需求（以及商务应答里的方案类条目）都必须有节点引用。

    先按编号检查谁被引用了；没被引用的条目，标题相同的节点直接绑定，否则补成新章。
    """
    if (doc_kind or "tech").strip().lower() == "business":
        return chapters
    from .writer_tool_runtime import numbered_requirement_items, requirement_item_map

    wanted: list[tuple[str, str, str]] = []
    for item_id, raw in numbered_requirement_items(tech_text, "tech"):
        title, body = _short_requirement_title(raw)
        if title:
            wanted.append((item_id, title, body))
    for item_id, raw in numbered_requirement_items(business_text, "business"):
        title, body = _short_requirement_title(raw)
        if title and business_item_belongs_in_tech(title, body):
            wanted.append((item_id, title, body))
    if not chapters:
        chapters = [{"title": "技术方案", "children": []}]
    items = requirement_item_map({"tech": tech_text, "business": business_text})
    cited = _tree_cited_ids(chapters)
    host = _coverage_host(chapters)
    children = host.get("children")
    if not isinstance(children, list):
        children = []
        host["children"] = children
    matched = 0
    backfilled = 0
    for item_id, title, body in wanted:
        if item_id in cited:
            continue
        node = _find_title_match(chapters, title)
        if node is not None:
            refs = [str(ref) for ref in (node.get("sourceRefs") or [])] + [item_id]
            _set_node_source(node, refs, items)
            cited.add(item_id)
            matched += 1
            continue
        new_node = {"title": title, "children": [], "part": "tech"}
        _set_node_source(new_node, [item_id], items)
        children.append(new_node)
        cited.add(item_id)
        backfilled += 1
    if report is not None:
        report["total"] = len(wanted)
        report["titleMatched"] = matched
        report["backfilled"] = backfilled
        report["boundByModel"] = len([1 for item_id, _, _ in wanted if item_id in cited]) - matched - backfilled
    blob = _outline_title_blob(chapters)
    table_host = host if host in chapters else chapters[0]
    for node in chapters:
        if isinstance(node, dict) and "技术" in str(node.get("title") or ""):
            table_host = node
            break
    table_children = table_host.get("children")
    if not isinstance(table_children, list):
        table_children = []
        table_host["children"] = table_children
    if "逐项需求响应表" not in blob and "偏离表" not in blob:
        table_children.append(
            {
                "title": "逐项需求响应表",
                "children": [],
                "part": "tech",
                "requirement": "按本份招标书原文规定的应答写法，逐条响应技术需求。",
                "idea": f"{SUMMARY_CHAPTER_MARK}按本份招标书原文规定的应答写法逐条响应技术需求。",
                "aiIdea": f"{SUMMARY_CHAPTER_MARK}按本份招标书原文规定的应答写法逐条响应技术需求。",
            }
        )
    return chapters


def _business_volume_items(business_text: str) -> list[tuple[str, str, str]]:
    """留在商务标的条目：(编号, 短名, 正文)。方案类和演示类不在此列。"""
    from .writer_tool_runtime import numbered_requirement_items

    wanted: list[tuple[str, str, str]] = []
    for item_id, raw in numbered_requirement_items(business_text, "business"):
        title, body = _short_requirement_title(raw)
        if title and not business_item_belongs_in_tech(title, body):
            wanted.append((item_id, title, body))
    return wanted


def _business_coverage_host(chapters: list[dict]) -> dict:
    for keywords in (("商务", "报价"), ("资格", "响应")):
        for node in chapters:
            if not isinstance(node, dict):
                continue
            title = _node_title(node)
            if is_original_form_title(title):
                continue
            if any(word in title for word in keywords):
                return node
    for node in chapters:
        if isinstance(node, dict) and not is_original_form_title(_node_title(node)):
            return node
    host = {"title": "商务响应", "children": [], "part": "business"}
    chapters.append(host)
    return host


def ensure_business_requirement_coverage(
    chapters: list[dict],
    business_text: str = "",
    report: dict | None = None,
) -> list[dict]:
    """商务标里不归技术标的每一条应答都要有节点引用。标题对得上就绑定，否则补章。"""
    from .writer_tool_runtime import requirement_item_map

    wanted = _business_volume_items(business_text)
    if not chapters:
        chapters = [{"title": "商务响应", "children": [], "part": "business"}]
    items = requirement_item_map({"business": business_text})
    cited = _tree_cited_ids(chapters)
    host = _business_coverage_host(chapters)
    children = host.get("children")
    if not isinstance(children, list):
        children = []
        host["children"] = children
    matched = 0
    backfilled = 0
    for item_id, title, _body in wanted:
        if item_id in cited:
            continue
        node = _find_title_match(chapters, title)
        if node is not None:
            refs = [str(ref) for ref in (node.get("sourceRefs") or [])] + [item_id]
            _set_node_source(node, refs, items, "business")
            cited.add(item_id)
            matched += 1
            continue
        new_node = {"title": title, "children": [], "part": "business"}
        _set_node_source(new_node, [item_id], items, "business")
        children.append(new_node)
        cited.add(item_id)
        backfilled += 1
    if report is not None:
        report["total"] = len(wanted)
        report["titleMatched"] = matched
        report["backfilled"] = backfilled
        report["boundByModel"] = len([1 for item_id, _, _ in wanted if item_id in cited]) - matched - backfilled
    return chapters


_DEVIATION_HINT = re.compile(r"偏离表|偏差表")
_PAYMENT_HINT = re.compile(r"付款")
_PAYMENT_DETAIL = re.compile(r"比例|节点|里程碑")
_QUOTE_DETAIL_TITLE = re.compile(r"报价明细|分项报价|报价表|报价清单")


def _is_quote_node(title: str) -> bool:
    compact = re.sub(r"\s+", "", title or "")
    if not compact or "开标一览" in compact or is_original_form_title(compact):
        return False
    return "报价" in compact


def _is_quote_detail_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title or "")
    if not _is_quote_node(compact):
        return False
    return bool(_QUOTE_DETAIL_TITLE.search(compact))


def _enumerated_pieces(text: str) -> list[str]:
    """条款里的编号行，或顿号、分号隔开的短分项。不足两项时返回空。"""
    numbered = re.findall(
        r"(?:^|\n)\s*(?:\d{1,2}[、.．]|（\d{1,2}）|\(\d{1,2}\))\s*([^\n]+)",
        text or "",
    )
    cleaned = [item.strip(" ；;，,") for item in numbered if item.strip()]
    if len(cleaned) >= 2:
        return cleaned
    best: list[str] = []
    for segment in re.split(r"[。\n]", text or ""):
        body = segment
        if "：" in body:
            body = body.split("：", 1)[1]
        elif ":" in body:
            body = body.split(":", 1)[1]
        parts = [part.strip(" ；;，,：: ") for part in re.split(r"[、；;]", body)]
        parts = [part for part in parts if 1 < len(part) <= 24]
        if len(parts) > len(best):
            best = parts
    return best if len(best) >= 2 else []


def _clauses_mentioning(text: str, pattern: re.Pattern[str]) -> str:
    picked = [chunk.strip() for chunk in re.split(r"[。\n]", text or "") if chunk.strip() and pattern.search(chunk)]
    return "。".join(picked)[:4000]


def _sibling_list(nodes: list[dict], target: dict) -> list[dict] | None:
    if any(node is target for node in nodes):
        return nodes
    for node in nodes:
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if isinstance(children, list):
            found = _sibling_list(children, target)
            if found is not None:
                return found
    return None


def _append_business_child(parent: dict, title: str, requirement: str) -> dict:
    name = _compact_catalog_title(title) or (title or "应答")[:24]
    child = {
        "title": name,
        "children": [],
        "part": "business",
        "requirement": requirement,
        "idea": _idea_from_requirement(name, requirement),
    }
    child["aiIdea"] = child["idea"]
    children = parent.get("children")
    if not isinstance(children, list):
        children = []
        parent["children"] = children
    children.append(child)
    return child


def _descendant_has_keyword(node: dict, keyword: str) -> bool:
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if keyword in _node_title(child) or _descendant_has_keyword(child, keyword):
            return True
    return False


def _widen_bound_title(node: dict, items: dict[str, str]) -> None:
    """节点只绑了一条，标题却只覆盖短名或顿号列举的第一项时，改成该条短名。"""
    refs = [str(ref) for ref in (node.get("sourceRefs") or []) if str(ref) in items]
    if len(refs) != 1:
        return
    short, body = _short_requirement_title(items[refs[0]])
    current = _node_title(node)
    if not short or short == current or len(short) > 24 or len(current) < 2 or len(short) <= len(current):
        return
    first = re.split(r"[、，,；;]", short)[0].strip()
    narrower = short.startswith(current) or bool(first) and (current == first or current.startswith(first))
    if not narrower:
        return
    node["title"] = short
    item_text = _clean_item_text(items[refs[0]])
    if len(item_text) > len(str(node.get("requirement") or "")):
        node["requirement"] = item_text
    text = str(node.get("requirement") or "").strip() or body
    node["idea"] = _idea_from_requirement(short, text)
    node["aiIdea"] = node["idea"]


def ensure_business_response_structure(
    chapters: list[dict],
    business_text: str = "",
    tender_text: str = "",
    has_deviation_form: bool = False,
    has_quote_form: bool = False,
) -> list[dict]:
    """按条款补上需求偏离表、付款节点和报价分项。不写死某一份招标的分项名称。"""
    from .writer_tool_runtime import requirement_item_map

    if not isinstance(chapters, list):
        return []
    items = requirement_item_map({"business": business_text})
    for node in _iter_chapter_nodes(chapters):
        _widen_bound_title(node, items)

    corpus = f"{business_text}\n{tender_text}"
    has_deviation = any(
        "偏离" in _node_title(node) or "偏差" in _node_title(node) for node in _iter_chapter_nodes(chapters)
    )
    if _DEVIATION_HINT.search(corpus) and not has_deviation and not has_deviation_form:
        requirement = _clauses_mentioning(corpus, _DEVIATION_HINT) or (
            "按招标文件偏离表格式逐条列明对需求的响应；未列示的视为已包含在报价和交付范围内。"
        )
        anchor = next(
            (
                node
                for node in _iter_chapter_nodes(chapters)
                if "响应" in _node_title(node) and "偏离" not in _node_title(node) and "偏差" not in _node_title(node)
            ),
            None,
        )
        created = {
            "title": "商务及需求偏离表",
            "children": [],
            "part": "business",
            "requirement": requirement,
            "idea": _idea_from_requirement("商务及需求偏离表", requirement),
        }
        created["aiIdea"] = created["idea"]
        if anchor is None:
            _append_business_child(_business_coverage_host(chapters), "商务及需求偏离表", requirement)
        else:
            siblings = _sibling_list(chapters, anchor) or chapters
            siblings.append(created)

    for node in list(_iter_chapter_nodes(chapters)):
        if has_quote_form:
            break
        if node.get("formKeys"):
            continue
        if not _is_quote_detail_title(_node_title(node)) or node.get("children"):
            continue
        pieces = _enumerated_pieces(str(node.get("requirement") or ""))
        for piece in pieces:
            short, body = _short_requirement_title(piece)
            _append_business_child(node, short or piece[:12], body or piece)

    for node in list(_iter_chapter_nodes(chapters)):
        title = _node_title(node)
        if not _is_quote_node(title) or "付款" in title:
            continue
        blob = f"{node.get('requirement') or ''}\n{node.get('idea') or ''}"
        if not (_PAYMENT_HINT.search(blob) and _PAYMENT_DETAIL.search(blob)):
            continue
        if _descendant_has_keyword(node, "付款"):
            continue
        pay = _clauses_mentioning(blob, _PAYMENT_HINT) or blob.strip()
        _append_business_child(node, "付款方式及节点", pay)
    return chapters


def _attach_tender_refs(nodes: list[dict], toc: dict | None, score_rules: list[dict]) -> None:
    items = _heading_index_items(toc)

    def walk(tree: list[dict]) -> None:
        for n in tree:
            if not isinstance(n, dict):
                continue
            title = n.get("title") or ""
            if is_original_form_title(title):
                hit = _best_heading(title, items)
                req = (hit.get("req") or "") if hit else ""
                n["idea"] = original_form_idea(title, str(n.get("idea") or ""), req)
                n["aiIdea"] = n["idea"]
                n["children"] = [
                    child
                    for child in (n.get("children") or [])
                    if isinstance(child, dict) and "附录" in _node_title(child)
                ]
                if hit and isinstance(hit.get("index"), int):
                    n["sourceIndex"] = hit["index"]
                walk(n["children"])
                continue
            hit = _best_heading(title, items)
            if hit:
                if isinstance(hit.get("index"), int):
                    n["sourceIndex"] = hit["index"]
                req = (hit.get("req") or "").strip()
                existing_req = (n.get("requirement") or "").strip()
                if len(req) > len(existing_req):
                    n["requirement"] = req
                elif not existing_req:
                    n["requirement"] = req
                hit_part = hit.get("part")
                if n.get("part") != "tech" and hit_part:
                    n["part"] = hit_part
                if req:
                    n["idea"] = f"【对应招标「{hit['title']}」】应完整响应，不得漏项：{req}"[:8000]
                else:
                    n["idea"] = f"【对应招标「{hit['title']}」】按该条款全部要求逐项应答，不得漏项。"
            elif not n.get("idea"):
                n["idea"] = f"对应「{title}」，须严格按招标文件相关条款应答，不得漏项。"
            n["aiIdea"] = n.get("aiIdea") or n.get("idea") or ""
            if not n.get("dimension"):
                dim = _match_dimension(title, score_rules)
                if dim:
                    n["dimension"] = dim
            kids = n.get("children")
            if isinstance(kids, list):
                walk(kids)

    walk(nodes)


def _user_content_with_images(text: str, knowledge_images: list[dict] | None, model_id: str | None):
    """豆包可读原图；DeepSeek 仍用全文+附图清单。原图均来自 MinIO。"""
    images = knowledge_images or []
    if not images or not is_vision_model(model_id):
        return text
    parts: list[dict] = [{"type": "text", "text": text}]
    for i, img in enumerate(images, start=1):
        b64 = img.get("b64") or ""
        mime = img.get("mime") or "image/png"
        if not b64:
            continue
        caption = img.get("caption") or img.get("heading") or "原文附图"
        parts.append({"type": "text", "text": f"\n原图{i}「{caption}」："})
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )
    return parts


def _wrap_tech_chapter(requirement: str, solution: str, layout: dict | None = None) -> str:
    body = sanitize_chapter_markdown(solution)
    body = re.sub(r"^##\s*原始需求[\s\S]*?(?=^##\s*解决方案|\Z)", "", body, flags=re.M).strip()
    body = re.sub(r"^##\s*解决方案\s*", "", body, flags=re.M).strip()
    req = (requirement or "").strip() or "（本章未抽取到招标原文，请对照招标文件补充。）"
    md = f"## 原始需求\n\n{req}\n\n## 解决方案\n\n{body}".strip()
    return apply_tech_markdown_style(md, layout if isinstance(layout, dict) else None)


_A4_WIDTH_MM = 210.0
_A4_HEIGHT_MM = 297.0
_PT_MM = 25.4 / 72
_FONT_NAME_PT = {
    "二号": 22,
    "小二": 18,
    "三号": 16,
    "小三": 15,
    "四号": 14,
    "小四": 12,
    "五号": 10.5,
    "小五": 9,
}


def _pref_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _body_pt(layout: dict | None) -> float:
    data = layout if isinstance(layout, dict) else {}
    if data.get("bodySizePt") is not None:
        return max(8.0, _pref_float(data.get("bodySizePt"), 12))
    return float(_FONT_NAME_PT.get(str(data.get("fontSize") or ""), 12))


def _line_pt(layout: dict | None, body_pt: float) -> float:
    data = layout if isinstance(layout, dict) else {}
    if data.get("lineSpacingExactPt"):
        return max(_pref_float(data.get("lineSpacingExactPt"), body_pt), body_pt)
    spacing = str(data.get("lineSpacing") or "")
    fixed = re.search(r"固定值\s*(\d+(?:\.\d+)?)\s*磅", spacing)
    if fixed and data.get("lineSpacingMul") is None:
        return max(float(fixed.group(1)), body_pt)
    mul = data.get("lineSpacingMul")
    if mul is None:
        if spacing.startswith("2"):
            mul = 2
        elif "1.5" in spacing:
            mul = 1.5
        else:
            mul = 1.5
    return max(body_pt * max(_pref_float(mul, 1.5), 1), body_pt)


def chars_per_page(layout: dict | None) -> int:
    """按 A4、页边距、正文字号和行距估算一页可容纳的汉字数。"""
    data = layout if isinstance(layout, dict) else {}
    margins = data.get("margins") if isinstance(data.get("margins"), dict) else {}
    left = _pref_float(margins.get("left"), 2)
    right = _pref_float(margins.get("right"), 2)
    top = _pref_float(margins.get("top"), 2)
    bottom = _pref_float(margins.get("bottom"), 2)
    width_mm = _A4_WIDTH_MM - (left + right) * 10
    height_mm = _A4_HEIGHT_MM - (top + bottom) * 10
    if width_mm < 40 or height_mm < 40:
        return 800
    body_pt = _body_pt(data)
    line_pt = _line_pt(data, body_pt)
    chars_line = max(8, int(width_mm / (body_pt * _PT_MM)))
    lines = max(8, int(height_mm / (line_pt * _PT_MM)))
    return chars_line * lines


def resolve_body_pages(page: dict | None) -> int:
    """正文页数。封面、正文、附录之和与总页数不一致时，用总页数减去封面和附录。"""
    if not isinstance(page, dict):
        return 0

    def _pages(key: str) -> int:
        return max(0, int(_pref_float(page.get(key), 0)))

    total, cover, body, appendix = _pages("total"), _pages("cover"), _pages("body"), _pages("appendix")
    if cover + body + appendix != total:
        body = max(0, total - cover - appendix)
    return body


def _tech_leaves(outline: list[dict] | None) -> list[dict]:
    nodes = [n for n in (outline or []) if isinstance(n, dict) and n.get("id")]
    parent_ids = {str(n.get("parentId")) for n in nodes if n.get("parentId")}
    leaves: list[dict] = []
    for node in nodes:
        if str(node["id"]) in parent_ids:
            continue
        kind = chapter_kind(
            str(node.get("title") or ""),
            node.get("part"),
            str(node.get("idea") or ""),
            str(node.get("requirement") or ""),
        )
        if kind == "tech":
            leaves.append(node)
    return leaves


CHAPTER_MIN_CHARS = 500
CHAPTER_CHARS_PER_REQ_CHAR = 1.2


def chapter_char_targets(
    outline: list[dict] | None,
    page: dict | None,
    layout: dict | None,
) -> dict[str, int]:
    """把正文页数按评分权重分给技术标叶子章，返回每章目标汉字数。"""
    body_pages = resolve_body_pages(page)
    leaves = _tech_leaves(outline)
    if body_pages <= 0 or not leaves:
        return {}
    total_chars = body_pages * chars_per_page(layout)
    weights: list[float] = []
    for node in leaves:
        weights.append(max(_pref_float(node.get("weight"), 0), 0))
    if sum(weights) <= 0:
        # 没有评分权重时按条款长度加权，并给每章设下限：条款答全优先于凑页数，总量可以超出预算。
        needs = [
            CHAPTER_MIN_CHARS
            + int(
                CHAPTER_CHARS_PER_REQ_CHAR
                * len(
                    re.sub(
                        r"\s+",
                        "",
                        str(node.get("requirement") or "") or _requirement_from_idea(str(node.get("idea") or "")),
                    )
                )
            )
            for node in leaves
        ]
        need_sum = sum(needs) or 1
        return {
            str(node["id"]): max(int(total_chars * need / need_sum), need)
            for node, need in zip(leaves, needs)
        }
    else:
        weight_sum = sum(weights)
        raw = [total_chars * weight / weight_sum for weight in weights]
    floors = [int(value) for value in raw]
    leftover = total_chars - sum(floors)
    order = sorted(range(len(leaves)), key=lambda i: raw[i] - floors[i], reverse=True)
    for index in order[:leftover]:
        floors[index] += 1
    return {str(node["id"]): max(floors[index], 1) for index, node in enumerate(leaves)}


def generate_chapter_content(
    project_name: str,
    chapter_title: str,
    chapter_idea: str,
    dimension_detail: dict | None,
    must_respond_context: list[dict],
    knowledge_snippets: list[dict] | None = None,
    writing_prefs: dict | None = None,
    model_id: str | None = None,
    product_features: list[dict] | None = None,
    product_library_name: str | None = None,
    qualification_assets: list[dict] | None = None,
    knowledge_images: list[dict] | None = None,
    part: str | None = None,
    requirement: str | None = None,
    outline: list[dict] | None = None,
    chapter_id: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    draft_id: str | None = None,
    job_id: str | None = None,
    enable_figures: bool = True,
) -> str:
    """生成单章正文。技术章由 Harness 撰写，失败时抛出，不写占位正文。"""
    has_kids = bool(chapter_id) and any(
        isinstance(n, dict) and n.get("parentId") == chapter_id for n in (outline or [])
    )
    kind = chapter_kind(chapter_title, part, chapter_idea, requirement or "", has_children=has_kids)
    if kind == "form":
        return original_form_markdown(chapter_title, chapter_idea)
    if kind == "business":
        return business_skip_markdown(chapter_title)

    response_mode = kind == "response"
    req_text, fact_text = resolve_chapter_requirement(
        outline, chapter_id, requirement or "", chapter_idea, project_id or "", chapter_title
    )
    layout = (writing_prefs or {}).get("layout") if isinstance(writing_prefs, dict) else None
    prompt = _build_chapter_context(
        project_name,
        chapter_title,
        chapter_idea,
        dimension_detail,
        must_respond_context,
        knowledge_snippets,
        writing_prefs,
        product_features,
        product_library_name,
        qualification_assets,
        knowledge_images,
        req_text,
        tech_mode=True,
        outline=outline,
        chapter_id=chapter_id,
    )
    if response_mode:
        prompt += (
            "\n\n本章是商务应答，不是技术方案。按条款逐条写响应，写全其中的数字、期限和并列项。"
            "涉及报价金额、单价、总价时一律写「待填」，不要编造价格。"
        )
    from .writer_harness import write_tech_chapter

    names = [] if response_mode else [
        str(feat.get("name") or "").strip() for feat in (product_features or []) if isinstance(feat, dict)
    ]
    names = [name for name in names if name]
    solution = write_tech_chapter(
        user_id=user_id or "",
        project_id=project_id or "",
        draft_id=draft_id or "",
        job_id=job_id or "",
        model_id=model_id,
        prompt=prompt,
        product_names=names,
        require_gap=False if response_mode else product_features is not None and not names,
        chapter_title=chapter_title,
        chapter_idea=chapter_idea,
        requirement=req_text,
        fact_text=fact_text,
    )
    solution = sanitize_chapter_markdown(solution)
    if not solution:
        from .writer_harness import HarnessError

        raise HarnessError("技术章正文为空")
    return _wrap_tech_chapter(req_text, solution, layout)


_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def sanitize_chapter_markdown(text: str) -> str:
    """把模型爱写的 #### / 代码围栏收成编辑器能渲染的 ## / ###。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    lines: list[str] = []
    for raw in cleaned.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        match = _HEADING_LINE_RE.match(stripped)
        if match:
            rest = match.group(2).strip()
            level = min(len(match.group(1)), 3)
            prefix = "#" * max(level, 2)
            lines.append(f"{prefix} {rest}")
            continue
        lines.append(raw)
    return "\n".join(lines).strip()


def _build_chapter_context(
    project_name: str,
    chapter_title: str,
    chapter_idea: str,
    dimension_detail: dict | None,
    must_respond_context: list[dict],
    knowledge_snippets: list[dict] | None = None,
    writing_prefs: dict | None = None,
    product_features: list[dict] | None = None,
    product_library_name: str | None = None,
    qualification_assets: list[dict] | None = None,
    knowledge_images: list[dict] | None = None,
    tender_requirement: str | None = None,
    tech_mode: bool = False,
    outline: list[dict] | None = None,
    chapter_id: str | None = None,
) -> str:
    lines = [
        f"项目名称：{project_name or '（未命名项目）'}",
        f"章节标题：{chapter_title}",
        f"编写思路：{chapter_idea or '（无特别说明，请自行组织内容）'}",
    ]
    if tech_mode:
        lines.append("")
        lines.append(
            "本章招标原始需求全文如下（必须逐条覆盖，但不要在输出中重复这段原文；系统会单独插入「原始需求」）："
        )
        lines.append((tender_requirement or "").strip() or "（未抽取到招标原文）")
    if dimension_detail:
        lines.append("")
        lines.append(
            f"关联评分点：[{dimension_detail.get('dimension', '')}] "
            f"权重 {dimension_detail.get('weight', 0)} 分：{dimension_detail.get('detail', '')}"
        )
    if must_respond_context:
        lines.append("")
        lines.append("需重点响应的相关条款：")
        for m in must_respond_context[:10]:
            lines.append(f"- [{m.get('type', '')}] {m.get('clause', '')}")
    if product_library_name or product_features is not None:
        lines.append("")
        if product_features:
            unreviewed = sum(1 for f in product_features if (f.get("status") or "已入库") == "待审核")
            label = "本公司产品能力" if unreviewed else "本公司已审核产品能力"
            lines.append(
                f"{label}（来自产品库「{product_library_name or '未命名'}」，"
                f"共 {len(product_features)} 项，必须通读全部参数与应标原文，禁止编造未列出的能力）："
            )
            if unreviewed:
                lines.append(f"其中 {unreviewed} 项标注「待审核」，内容来自过往技术标抽取、尚未人工审核，只按原文表述，不要加码。")
            for i, feat in enumerate(product_features, start=1):
                lines.append("")
                review = "（待审核）" if (feat.get("status") or "已入库") == "待审核" else ""
                lines.append(f"{i}. 【{feat.get('name', '')}】{review}模块：{feat.get('module') or '未分模块'}")
                params = (feat.get("params") or "").strip()
                lines.append(f"参数：{params or '无'}")
                copy = (feat.get("bidCopy") or feat.get("intro") or "").strip()
                if copy:
                    lines.append("应标原文：")
                    lines.append(copy)
                n_img = len(feat.get("images") or [])
                if n_img:
                    lines.append(f"（本功能原图 {n_img} 张，见下方附图清单，不允许丢失）")
        else:
            lines.append(
                f"已选择产品库「{product_library_name or '未命名'}」，但本章没有匹配到已入库功能点。"
                "正文必须写【能力缺口：本章招标需求在产品库中无对应功能点】，禁止编造本公司能力。"
            )
    if qualification_assets:
        lines.append("")
        lines.append(
            f"本公司已入库资质材料（共 {len(qualification_assets)} 条，必须据此写证号与有效期，"
            "禁止编造未列出的证书；扫描件见附图清单，必须全部插入）："
        )
        for i, asset in enumerate(qualification_assets, start=1):
            lines.append("")
            lines.append(
                f"{i}. 【{asset.get('name', '')}】类型：{asset.get('kind') or ''}；"
                f"编号：{asset.get('number') or '无'}；持有人：{asset.get('owner') or '无'}；"
                f"有效期：{asset.get('validUntil') or '长期'}"
            )
            detail = (asset.get("detail") or "").strip()
            if detail:
                lines.append(detail)
            ocr = (asset.get("ocrText") or "").strip()
            if ocr:
                lines.append(f"OCR：{ocr}")
            n_img = len(asset.get("images") or [])
            if n_img:
                lines.append(f"（本条扫描件 {n_img} 张，见下方附图清单，不允许丢失）")
    if knowledge_snippets:
        lines.append("")
        lines.append(
            "知识库整包素材（用户勾选章节及其全部下级，含正文、表格与原图。"
            "必须通读，禁止截取摘要代替，禁止丢失任意图表或段落）："
        )
        for s in knowledge_snippets:
            heading = s.get("heading") or ""
            doc_title = s.get("docTitle") or ""
            text = s.get("text") or ""
            lines.append("")
            lines.append(f"## 《{doc_title}》· {heading}")
            if text:
                lines.append(text)
            else:
                lines.append("（本节无正文，请结合原图）")
            n_img = len(s.get("images") or [])
            if n_img:
                lines.append(f"（本节原图 {n_img} 张，见下方附图清单）")
    if knowledge_images:
        lines.append("")
        lines.append(
            f"附图清单（共 {len(knowledge_images)} 张，含知识库、产品功能库、资质证照库对象存储原图，"
            "撰写时用【此处插入图：序号】引用，不允许丢失）："
        )
        vision_n = sum(1 for img in knowledge_images if img.get("b64"))
        if vision_n and vision_n < len(knowledge_images):
            lines.append(
                f"说明：已内嵌原图 {vision_n} 张供阅读；其余 {len(knowledge_images) - vision_n} 张"
                "仍须按编号全部插入正文，不允许丢失。"
            )
        source_label = {"knowledge": "知识库", "product": "产品", "qualification": "资质"}
        for i, img in enumerate(knowledge_images, start=1):
            src = source_label.get(str(img.get("source") or ""), "")
            prefix = f"[{src}] " if src else ""
            lines.append(
                f"{i}. {prefix}{img.get('caption') or img.get('heading') or '原文附图'}"
                f"（所属：{img.get('heading') or ''}）"
            )
    prefs = writing_prefs if isinstance(writing_prefs, dict) else {}
    target = chapter_char_targets(outline, prefs.get("page"), prefs.get("layout")).get(str(chapter_id or ""))
    if target:
        low = max(1, int(target * 0.8))
        high = max(low, int(target * 1.2))
        lines.append("")
        lines.append(
            f"篇幅要求：本章目标约 {target} 字。请把解决方案控制在 {low} 到 {high} 字"
            "（目标的 0.8 倍到 1.2 倍），不要明显超出。"
        )
    style = prefs.get("style") or {}
    if isinstance(style, dict) and any(style.get(k) for k in ("tone", "length", "firmName", "strictness")):
        lines.append("")
        lines.append("撰写偏好：")
        if style.get("tone"):
            lines.append(f"- 行文基调：{style['tone']}")
        if style.get("length"):
            lines.append(f"- 篇幅：{style['length']}")
        if style.get("firmName"):
            lines.append(f"- 企业署名：{style['firmName']}")
        if style.get("strictness"):
            lines.append(f"- 格式规范：{style['strictness']}")
    lines.append("")
    lines.append("请只撰写本章「解决方案」。")
    return "\n".join(lines)


def _as_str(value, default: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else default


def _as_str_or_none(value):
    return value if isinstance(value, str) and value.strip() else None


def _as_float(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _new_node(
    node_id: str,
    num: str,
    title: str,
    parent_id: str | None,
    item: dict,
    expanded: bool,
    has_children: bool = False,
) -> dict:
    idea = _as_str(item.get("idea"), "请补充本章编写思路")
    clean_title = title.strip() if item.get("composition") else _compact_catalog_title(title)
    if num and clean_title.startswith(num):
        clean_title = clean_title[len(num) :].strip()
    form = is_original_form_title(clean_title or title)
    if form:
        idea = original_form_idea(clean_title or title, idea)
    part = item.get("part") if item.get("part") in ("tech", "business", "form") else None
    if form:
        part = "form"
    kind = chapter_kind(
        clean_title or title, part, idea, str(item.get("requirement") or ""), has_children=has_children
    )
    if kind == "business":
        part = "business"
        if not form and _is_generic_idea(idea):
            idea = BUSINESS_SKIP_IDEA_PREFIX
    elif kind == "response" and part not in ("tech", "business", "form"):
        part = "business"
    skip_write = kind in ("form", "business")
    extra: dict = {}
    refs = [str(r) for r in (item.get("sourceRefs") or []) if isinstance(r, (str, int))]
    if refs:
        extra["sourceRefs"] = refs
    form_keys = [k for k in (item.get("formKeys") or []) if isinstance(k, int)]
    if form_keys:
        extra["formKeys"] = form_keys
    return {
        **extra,
        "id": node_id,
        "num": num,
        "title": clean_title or title,
        "parentId": parent_id,
        "expanded": expanded and not form,
        "weight": _as_float(item.get("weight"), 0),
        "dimension": _as_str_or_none(item.get("dimension")),
        "idea": idea,
        "aiIdea": _as_str(item.get("aiIdea"), idea),
        "optimized": False,
        "status": "用原文" if skip_write else "待生成",
        "words": 0,
        "aiRounds": 0,
        "sourceIndex": item.get("sourceIndex") if isinstance(item.get("sourceIndex"), int) else None,
        "part": part,
        "requirement": item.get("requirement") if isinstance(item.get("requirement"), str) else "",
    }


def _normalize_outline(data: dict) -> list[dict]:
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return []

    nodes: list[dict] = []

    def add_item(item: dict, node_id: str, num: str, parent_id: str | None, depth: int) -> None:
        if not isinstance(item, dict) or len(nodes) >= 800:
            return
        title = _as_str(item.get("title"), node_id)
        kids_raw = item.get("children")
        nodes.append(
            _new_node(
                node_id,
                num,
                title,
                parent_id,
                item,
                expanded=depth < 4,
                has_children=isinstance(kids_raw, list) and bool(kids_raw) and depth < 5,
            )
        )
        if is_original_form_title(title):
            return
        children = item.get("children")
        if not isinstance(children, list) or depth >= 5:
            return
        for j, sub in enumerate(children[:400], start=1):
            child_num = _format_outline_num(depth + 1, j, num)
            add_item(sub, f"{node_id}-{j}", child_num, node_id, depth + 1)

    for i, ch in enumerate(chapters[:80], start=1):
        add_item(ch, f"o-{i}", _format_outline_num(0, i, ""), None, 0)
    return nodes


def _fallback_outline(score_rules: list[dict], tender_toc: dict | None = None) -> list[dict]:
    from .tender_toc import headings_to_chapters, toc_has_structure

    if toc_has_structure(tender_toc):
        compose = (tender_toc or {}).get("compose") or []
        tech = (tender_toc or {}).get("tech") or []
        headings = compose or tech
        chapters = headings_to_chapters(headings)
        if compose and tech:
            _fill_format_chapters_with_requirements(chapters, tender_toc)
        _collapse_original_form_chapters(chapters, tender_toc)
        nodes = _normalize_outline({"chapters": chapters})
        if nodes:
            return nodes

    dims: list[str] = []
    seen: set[str] = set()
    for r in score_rules:
        dim = r.get("dimension")
        if isinstance(dim, str) and dim and dim not in seen:
            seen.add(dim)
            dims.append(dim)
    if not dims:
        dims = ["项目理解与总体方案", "技术实施方案", "质量保障措施", "售后服务承诺"]

    nodes = []
    for i, dim in enumerate(dims[:18], start=1):
        node_id = f"o-{i}"
        nodes.append(
            {
                "id": node_id,
                "num": _format_outline_num(0, i, ""),
                "title": dim,
                "parentId": None,
                "expanded": True,
                "weight": 0,
                "dimension": dim,
                "idea": f"围绕「{dim}」评分维度组织本章内容，回应招标文件的相关要求。",
                "aiIdea": f"建议本章从背景理解、具体举措、保障机制三个层次展开，充分响应「{dim}」评分维度的要求。",
                "optimized": False,
                "status": "待生成",
                "words": 0,
                "aiRounds": 0,
            }
        )
    return nodes


def _fallback_chapter_content(chapter_title: str, chapter_idea: str, reason: str) -> str:
    return (
        f"## {chapter_title}\n\n"
        f"（AI 生成暂不可用：{reason}，以下为占位内容，请人工补充撰写）\n\n"
        f"{chapter_idea or '请结合招标文件评分要求，补充本章具体内容。'}"
    )


CHAT_SYSTEM_PROMPT = """你是慧投标投标文件撰写助手，只根据用户提供的项目上下文回答。
要求：
1. 用中文、简洁专业，面向投标文件编写人员；
2. 可以分析废标风险、优化章节结构、给出撰写建议或改写示例；
3. 不要编造招标文件中没有出现的资质、业绩、证书有效期或评分权重；
4. 若上下文不足，明确说明缺什么（例如尚未解析评标尺子），再给通用撰写建议；
5. 不要声称已经自动改写了正文或已经插入章节，除非用户只是在征求文案建议。
"""

OPTIMIZE_PROMPT_SYSTEM = """你是投标文件插图提示词工程师。把用户的短句扩写成适合文生图模型（豆包 Seedream）的详细中文提示词。
只返回扩写后的提示词本身，不要解释，不要加引号。
根据模式调整：
- normal：写实配图，场景、光线、构图、适合标书插图；
- flow：白底扁平矢量流程图，框、箭头、中文标签清晰；
- arch：白底分层架构图，方框与连接线、中文标签清晰。
不要要求出现真实品牌 logo 或可识别真人面孔。
"""


def chat_assist(
    user_message: str,
    history: list[dict],
    project_name: str,
    score_rules: list[dict],
    must_respond: list[dict],
    outline_titles: list[str],
    chapter_title: str = "",
    chapter_excerpt: str = "",
    model_id: str | None = None,
) -> str:
    """撰写助手对话。未配置 Key 时返回明确提示，不编造成果。"""
    messages: list[dict] = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_chat_context(
            project_name, score_rules, must_respond, outline_titles, chapter_title, chapter_excerpt
        )},
        {"role": "assistant", "content": "已了解当前项目上下文，请提出你的问题。"},
    ]
    for item in history[-12:]:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": "user" if role == "user" else "assistant", "content": content.strip()[:2000]})
    messages.append({"role": "user", "content": user_message.strip()[:4000]})

    try:
        text = chat_complete(model_id=model_id, messages=messages, temperature=0.4, timeout=60)
        return (text or "").strip() or "助手没有返回内容，请换一种问法再试。"
    except LlmError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return f"调用大模型失败（{exc.__class__.__name__}），请稍后重试。"


def optimize_image_prompt(user_prompt: str, mode: str, model_id: str | None = None) -> str:
    """把短句扩写成生图提示词。失败时原样返回用户输入。"""
    text = (user_prompt or "").strip()
    if not text:
        return text
    try:
        out = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": OPTIMIZE_PROMPT_SYSTEM},
                {"role": "user", "content": f"模式：{mode}\n用户描述：{text}"},
            ],
            temperature=0.4,
            timeout=45,
        )
        return (out or "").strip().strip('"').strip("「」") or text
    except Exception:  # noqa: BLE001
        return text


def _build_chat_context(
    project_name: str,
    score_rules: list[dict],
    must_respond: list[dict],
    outline_titles: list[str],
    chapter_title: str,
    chapter_excerpt: str,
) -> str:
    lines = [
        "以下是当前撰写项目的上下文，后续问题请结合这些信息回答。",
        f"项目名称：{project_name or '（未命名项目）'}",
        "",
        "评分规则（截断）：",
    ]
    if score_rules:
        for r in score_rules[:20]:
            lines.append(f"- [{r.get('dimension', '')}] 权重 {r.get('weight', 0)} 分：{r.get('detail', '')}")
    else:
        lines.append("（尚无评标尺子，可能还未解析招标文件）")
    lines.append("")
    lines.append("必响应 / 否决条款（截断）：")
    if must_respond:
        for m in must_respond[:20]:
            lines.append(f"- [{m.get('type', '')}] {m.get('clause', '')}")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("当前目录：")
    if outline_titles:
        for t in outline_titles[:30]:
            lines.append(f"- {t}")
    else:
        lines.append("（尚未生成目录）")
    if chapter_title:
        lines.append("")
        lines.append(f"用户正在编辑的章节：{chapter_title}")
        excerpt = (chapter_excerpt or "").strip()
        if excerpt:
            lines.append("章节正文摘录：")
            lines.append(excerpt[:1200])
    return "\n".join(lines)
