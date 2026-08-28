"""AI 撰写工作台引擎：大模型阅读招标原文生成应标目录，并逐章生成投标文件正文。

目录生成与章节正文使用用户在标书设置中选择的大模型（DeepSeek 4 Pro / 豆包）。
未配置 Key 或调用异常时降级为招标条款原树或占位正文，不阻塞撰写流程。
"""

import json
import logging
import re

from .llm import LlmError, chat_complete, is_vision_model

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


OUTLINE_INPUT_MAX = 42000
OUTLINE_INVENTORY_MAX = 16000
OUTLINE_TIMEOUT = 300

OUTLINE_SYSTEM_PROMPT = """# 角色
你是拥有10年以上央企/国企招投标标书编制经验的资深投标总监，精通综合评估法、经评审最低价法等主流评审规则，深谙评标专家“逐条打勾、按目录定位应答内容”的评审习惯。你擅长基于任意招标文件原文，拆解出颗粒度精准、层级清晰、100%覆盖所有需求点的投标文件多级目录，目录质量达到资深投标专员人工编制水准，无漏项、无冗余、逻辑顺、易核查，可直接用于正式投标文件排版。

# 核心目标
必须先通读本份招标文件全文，再严格按本份「响应文件格式」（或本份对响应文件/投标文件如何组成、如何编写的同等规定，以下统称格式要求）去写投标文件目录。
不同招标书的格式要求不同，章节名称、顺序、层级、某一章应写什么，一律以本份格式要求的原文为准，禁止套用任何预置章节清单或他项目目录。

编制时同时做到：
1. 格式要求列出的章节，就是目录的大标题骨架；名称与顺序按格式要求原文，不得改名、调序、增删。
2. 格式里的每一章都要单独阅读该章自己的编写要求，再决定这一章下面写什么：
   - 若该章要求按招标书另一部分的目录编制、或按该部分条款逐条描述/逐条响应：把该部分中与本章主题对应的条款目录完整写入本章下级；若要求覆盖该部分全部目录，则把尚未被其他格式章归位的条款也写入本章。
   - 若该章要求根据招标书某部分的有关要求编制：到该部分中找出与本章标题/主题对应的章节，将其条款目录写入本章下级。
   - 若该章编写要求只列出本章自身要点、未指向招标书其他部分：按该章要求自身的要点展开，不要把无关部分塞进来。
   - 若该章属于固定格式签字件（承诺类、授权委托类、报价类、商务/技术偏差表类等：招标书已给出填写格式，填好后打印签字）：只保留该文件名作为叶子节点，不要展开下级目录，不要写入应标细目，直接沿用招标书原文格式。
3. 同一条应标细目只写入最对应的那一个格式章。禁止把本应分属多章的内容全部塞进其中一章，导致其他格式章只有空标题。

禁止只输出格式大标题而丢掉应标细目；禁止抛开格式要求另起一套目录；禁止只根据某一章的编写要求去处理全部需求。

# 强制执行：5步目录编制SOP（必须严格按顺序执行）
## 第一步：通读全文，按本份格式要求锁定大标题骨架
逐字通读输入的全部招标文本。先找出本份格式要求的原文，按它列出的文件/章节作为投标文件目录的大标题骨架。
- 有格式要求的：只采用本份格式要求中的章节名与顺序。
- 没有单独格式要求的：再按本份招标书自身章节逻辑划分大类，仍不得套用固定模板。

## 第二步：逐章阅读格式要求，把招标书对应部分写入各章
对格式列出的每一章，分别阅读该章编写要求，再回原文中定位它指向的那一部分（各招标书用词、章节名都可能不同，以本份原文为准）：
- 指向「按某部分目录编制 / 逐条响应」的：写入该部分中与本章对应的全部条款目录；
- 指向「根据某部分有关要求编制」的：写入该部分里标题/主题与本章对应的章节；
- 未指向其他部分的：只按本章自身要求展开。
- 固定格式签字件（承诺、授权委托、报价、商务/技术偏差表等招标已给格式、填写后打印签字的）：只输出该文件标题，不要任何下级标题，不要把其他部分的条款目录写进去。
把对应条款拆到「最小不可拆分的独立需求单元」作为该章下级（一条都不能少），并标注：
- 【实质性条款】：带★/*/标注、写明“否决投标”“必须满足”“强制”“否则无效”的条款；
- 【一般条款】：明确要求但不触发否决的常规要求；
- 【交付物】：明确要求提交的文档、成果、资料、证明文件；
- 【推荐/可选条款】：写明“可提供”“建议”“鼓励”的非强制要求。
不得把招标书某一部分的目录提升为整本投标文件的一级目录；不得漏读格式某一章所指向的原文部分。

## 第三步：自上而下搭层级，在各格式章内拆到最小需求
层级控制在五级以内：
- 靠前的层级：本份格式要求中的大标题；
- 其下：按该章编写要求应写入的应标细目，拆到最小不可分的单个需求点。
每一个末级节点只对应一个最小需求单元。凡格式要求对照招标书某部分来写的章，其下必须有对应细目，不能只有空标题或编写说明。固定格式签字件保持叶子，不要再拆。

## 第四步：反向校验闭环，确保符合本份格式要求
A. 格式骨架：本份格式要求列出的大标题是否全部入目录且顺序一致；
B. 分章归位：每一章是否都按其自己的编写要求写入了所指向的原文部分；有对应原文的章不得空着；同一条款未重复塞进无关章。固定格式签字件有文件名即可，不算空壳。
并满足：
1. 每一条须响应的招标要求，都能在格式中最对应的那一章下找到明确节点；
2. 所有【实质性条款】【交付物】必须单独成节点，不得埋藏在其他节点中；
3. 存在多个需求合并为一个节点的，必须拆分；存在层级错位的，必须调整。

## 第五步：标题命名（本份招标书全部条款适用）
凡条款，目录标题规则相同：只能用「短名称」，禁止把「需求原文/说明句」当作目录。

先判断该条是名称还是描述（按句子形态判断，不按它属于哪一章）：
- 【短名称】：一般不超过16字，无句号，不以「支持/须/必须/应当/应能/包括/因/对于」开头，也不含「提供…咨询」「小时内完成」这类完整要求句。
- 【需求描述】：说明「要做什么」的句子或半句。包括以「支持/须/必须/应当/提供/因」开头、超过16字、带逗号/顿号的完整说明，以及服务时限、响应时限类条款原文。即使写在某章编号后面，也仍是描述，不是目录名。

A. 判定为【短名称】：目录标题必须原样使用，禁止改写合并、禁止跳级。
B. 判定为【需求描述】：必须根据内容提炼 4～12 字短标题（名词或动宾短语）；严禁把原句、半句、原文列举粘贴为任何一级标题；一条描述含两个独立要求时拆成两个短标题。

编号连续无跳号；标题本身不要写编号（不要把招标原文里的序号抄进标题，目录编号由排版系统生成）。

【A 正确】招标已写出的短名称原样做标题
【B 错误】把需求说明整句或半句当目录
【B 正确】把说明句提炼为不超过12字的短标题

# 刚性编制准则（违反即不合格）
0. 格式要求优先准则：大标题的名称、顺序，以及某一章应写入什么，只来自本份格式要求原文；不同招标书不得共用同一套章节。禁止套用预置章节、他项目目录或通用标书模板。
0.1 应标细目归位准则：格式每一章写什么，只看该章自己的编写要求及其指向的原文部分；有对应原文的章不得空壳。禁止把多章应写的内容合并进其中一章。
0.2 固定格式签字件准则：承诺类、授权委托类、报价类、商务/技术偏差表类等招标已给出固定格式、填写后打印签字的文件，目录只保留文件名叶子，禁止再展开应标细目或撰写正文，直接使用招标书原文。
1. 颗粒度准则：招标表格中的每一行参数、每一个功能点、每一项服务要求、每一条验收标准，都必须对应到末级目录；禁止用“相关要求”“其他功能”等笼统标题覆盖多条需求。
2. 名称/描述分离准则：已有短名称则原词做标题；需求描述必须提炼成短标题。禁止把招标条款原文、说明句、半句或顿号清单当作任何一级目录标题。
3. 实质性条款显式准则：所有带★/*/否决投标/强制性要求，绝不允许隐藏在深层目录或大段文字对应的目录中，必须保证醒目可查。
4. 交付物独立准则：本份招标文件明确列出的全部交付物清单，必须在目录中有独立对应节点，不得散落在其他章节内。
5. 分卷分册准则：本份格式要求如何分卷、分册或分部分，目录就如何划分；未划分的，不要自行套用固定分册。
6. 无冗余准则：目录只保留与本份招标应答强相关的节点，不添加本份招标未要求的冗余章节，不做方案性展开。
7. 禁则：禁止跳号、重号；禁止出现“其他”“等等”类模糊标题；禁止跨维度合并需求；禁止自行新增本份招标未提及的核心模块；禁止把功能描述粘贴为标题；禁止把已命名功能点改成拼接标题。
8. 禁止套话模板：禁止用与本份招标条款无法一一对应的套话章节，去合并、替换或吞掉招标里已经点名的条款。本份招标点了名的条款名称，必须在目录中原样点名出现。

# 输出规范
1. 仅输出目录本身，使用标准Markdown多级标题格式：# 一级、## 二级、### 三级、#### 四级；
2. 不输出任何解释说明、编制思路、应答正文、方案描述、需求清单或SOP过程；
3. 标题不要自带编号（不要写「一、」「（一）」「1.」「1.1」），编号由排版系统单独生成；标题只写本份招标书中的章节/条款名称本身；
4. 大标题按本份格式要求；每一章按其编写要求写入所指向的原文对应部分。短名称原样输出；需求描述必须先提炼成不超过12个汉字的短标题再输出，禁止把「支持…」「须…」「提供…」「因…须…」整句或半句写入任何一级标题；
5. 目录必须同时包含格式大标题与应标细目，结构完整、层级缩进清晰，可直接用于正式投标文件排版。
6. 固定格式签字件只输出其所在层级的文件名标题，不要下级标题。
"""

ORIGINAL_FORM_NOTE = (
    "本章为招标书已给出的固定格式文件，请直接使用招标书原文填写后打印签字，"
    "系统不展开目录、不撰写正文。"
)
ORIGINAL_FORM_IDEA_PREFIX = "【按招标书原文格式填写后打印签字，不展开目录、不撰写正文】"
BUSINESS_SKIP_NOTE = (
    "商务标本章无需撰写应标正文。承诺书、报价文件、偏差表等固定格式件请直接使用招标书原文填写后打印签字。"
)
BUSINESS_SKIP_IDEA_PREFIX = "【商务标无需应答，不撰写应标正文】"

# 按「文件类别」识别，不用某份招标书的具体章节名。
_ORIGINAL_FORM_TITLE = re.compile(
    r"(承诺书|承诺函|"
    r"授权委托|"
    r"报价文件|报价表|开标一览|分项报价|投标报价|报价部分|"
    r"商务.{0,8}技术.{0,6}偏差|商务偏差|技术偏差|偏差表)"
)
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
    """承诺/授权委托/报价/商务技术偏差等招标已给格式、打印签字的文件，不展开目录。"""
    from .tender_toc import strip_heading_prefix

    t = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    if not t:
        return False
    if t in {"报价", "投标报价"}:
        return True
    return bool(_ORIGINAL_FORM_TITLE.search(t))


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
    for n in outline:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "")
        kind = chapter_kind(title, n.get("part"), str(n.get("idea") or ""), str(n.get("requirement") or ""))
        if kind not in ("form", "business") and not is_original_form_title(title):
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
) -> str:
    """form=签字件原文；business=商务标不应答；tech=先列原始需求再写解决方案。"""
    if is_original_form_title(title) or part == "form":
        return "form"
    from .tender_toc import strip_heading_prefix

    t = re.sub(r"\s+", "", strip_heading_prefix(title or ""))
    blob = f"{idea or ''}\n{requirement or ''}"
    if _BUSINESS_SKIP_TITLE.search(t):
        return "business"
    if _TECH_VOLUME_TITLE.search(t) and (
        _FORMAT_DIR_HINT.search(blob) or not (requirement or "").strip()
    ):
        return "business"
    if part in ("business", "tech"):
        return part
    if (requirement or "").strip() or (idea or "").startswith("应实现：") or "应完整响应" in (idea or ""):
        return "tech"
    return "tech"


def _requirement_from_idea(idea: str) -> str:
    text = (idea or "").strip()
    for prefix in ("应实现：", "不得漏项：", "招标书原文："):
        if prefix in text:
            return text.split(prefix, 1)[-1].strip()
    return ""


def _collapse_original_form_chapters(nodes: list[dict], tender_toc: dict | None = None) -> None:
    for n in nodes:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "")
        if is_original_form_title(title):
            n["children"] = []
            n["idea"] = original_form_idea(title, str(n.get("idea") or ""), _compose_requirement_blob(title, tender_toc))
            n["aiIdea"] = n["idea"]
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
) -> list[dict]:
    """大模型阅读招标原文编制应标目录；失败时回退为招标条款原树。"""
    del knowledge_headings  # 目录只覆盖招标需求，不用知识库目录改写结构
    try:
        content = _call_outline_llm(
            model_id,
            project_name,
            tender_text or "",
            tender_toc,
            score_rules,
            must_respond,
        )
        chapters = _chapters_from_llm_output(content)
        if chapters:
            _fill_format_chapters_with_requirements(chapters, tender_toc)
            _collapse_original_form_chapters(chapters, tender_toc)
            _attach_tender_refs(chapters, tender_toc, score_rules)
            nodes = _normalize_outline({"chapters": chapters})
            if nodes:
                return nodes
            logger.warning("outline LLM returned no parseable directory")
    except Exception:  # noqa: BLE001 —— 调用失败降级，不让撰写任务中断
        logger.exception("outline LLM generate failed, falling back to tender headings")
    return _fallback_outline(score_rules, tender_toc)


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
            "名称与顺序以本份招标书为准；这不是目录的全部，其下还必须展开全部需求应标细目："
        )
        for item in compose:
            pad = "  " * max(int(item.get("level") or 1) - 1, 0)
            lines.append(f"{pad}- {item.get('title', '')}")
        lines.append("")
    if tech:
        lines.append(
            "【应标细目】下列条款须按本份格式要求，全部写入格式指定的那一章之下，不得拆到与该章平级的其他格式章节。"
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


def _build_outline_user_message(
    project_name: str,
    tender_text: str,
    tender_toc: dict | None,
    score_rules: list[dict],
    must_respond: list[dict],
) -> str:
    lines = [
        f"项目名称：{project_name or '（未命名项目）'}",
        "",
        "请先通读下方本份招标文件全文，再严格按本份响应文件格式（或同等的组成/编写规定）编写投标文件目录。"
        "格式列出的每一章都要单独看该章编写要求：要求对照招标书哪一部分来写，就把那一部分里与本章对应的条款目录写进本章；不要只处理其中一章、让其他章空着。"
        "不同招标书的章节名和指向部分都不同，一律以本份原文为准，禁止套用预置章节。"
        "短名称原样做标题；需求说明句必须提炼成短标题，严禁把招标原文整句当目录。"
        "承诺类、授权委托类、报价类、商务/技术偏差表类等招标已给固定格式、填写后打印签字的文件，目录只保留文件名，不要展开下级。",
        "",
    ]
    if score_rules:
        lines.append("评分维度（仅供划分卷册与标注分值对应关系，禁止按评分点另起一套目录）：")
        for r in score_rules[:40]:
            lines.append(f"- [{r.get('dimension', '')}] 权重 {r.get('weight', 0)} 分：{r.get('detail', '')}")
        lines.append("")
    if must_respond:
        lines.append("解析出的实质性/否决条款（必须在目录中醒目单列，不得埋入其他节点）：")
        for m in must_respond[:40]:
            lines.append(f"- [{m.get('type', '')}] {m.get('clause', '')}")
        lines.append("")
    corpus = (tender_text or "").strip()
    if len(corpus) > OUTLINE_INPUT_MAX:
        corpus = corpus[:OUTLINE_INPUT_MAX]
    lines.append("----------上传的招标文件原文（未抽取、未改写）----------")
    lines.append(corpus if corpus else "（未能读取上传的招标文件原文。）")
    return "\n".join(lines)


def _call_outline_llm(
    model_id: str | None,
    project_name: str,
    tender_text: str,
    tender_toc: dict | None,
    score_rules: list[dict],
    must_respond: list[dict],
) -> str:
    return chat_complete(
        model_id=model_id,
        messages=[
            {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_outline_user_message(
                    project_name, tender_text, tender_toc, score_rules, must_respond
                ),
            },
        ],
        temperature=0.2,
        timeout=OUTLINE_TIMEOUT,
        max_tokens=8192,
    )


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


def _markdown_to_chapters(text: str) -> list[dict]:
    entries: list[tuple[int, str]] = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("```") or set(line) <= set("-—* "):
            continue
        match = _MD_HEADING.match(line)
        if not match:
            continue
        title = _compact_catalog_title(_strip_generated_num(match.group(2)))
        if not title:
            continue
        entries.append((len(match.group(1)), title))
    if not entries:
        return []
    min_lv = min(lv for lv, _ in entries)
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for lv, title in entries:
        level = lv - min_lv + 1
        node = {"title": title, "children": []}
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
                n["children"] = []
                if hit and isinstance(hit.get("index"), int):
                    n["sourceIndex"] = hit["index"]
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


def _wrap_tech_chapter(requirement: str, solution: str) -> str:
    body = sanitize_chapter_markdown(solution)
    body = re.sub(r"^##\s*原始需求[\s\S]*?(?=^##\s*解决方案|\Z)", "", body, flags=re.M).strip()
    body = re.sub(r"^##\s*解决方案\s*", "", body, flags=re.M).strip()
    req = (requirement or "").strip() or "（本章未抽取到招标原文，请对照招标文件补充。）"
    return f"## 原始需求\n\n{req}\n\n## 解决方案\n\n{body}".strip()


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
) -> str:
    """生成单章正文。失败或未配置 Key 时返回提示性占位文本，不抛错。"""
    kind = chapter_kind(chapter_title, part, chapter_idea, requirement or "")
    if kind == "form":
        return original_form_markdown(chapter_title, chapter_idea)
    if kind == "business":
        return business_skip_markdown(chapter_title)

    req_text = (requirement or "").strip() or _requirement_from_idea(chapter_idea)
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
    )
    timeout = 180 if (knowledge_snippets or knowledge_images or product_features or qualification_assets) else 90
    system = TECH_SOLUTION_SYSTEM
    try:
        text = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": _user_content_with_images(prompt, knowledge_images, model_id),
                },
            ],
            temperature=0.5,
            timeout=timeout,
        )
        solution = sanitize_chapter_markdown(text) or _fallback_chapter_content(
            chapter_title, chapter_idea, "AI 返回内容为空"
        )
        return _wrap_tech_chapter(req_text, solution)
    except LlmError as exc:
        if knowledge_images and is_vision_model(model_id):
            try:
                text = chat_complete(
                    model_id=model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.5,
                    timeout=timeout,
                )
                solution = sanitize_chapter_markdown(text) or _fallback_chapter_content(
                    chapter_title, chapter_idea, "AI 返回内容为空"
                )
                return _wrap_tech_chapter(req_text, solution)
            except Exception:
                logger.exception("chapter generate retry without images failed")
        return _wrap_tech_chapter(req_text, _fallback_chapter_content(chapter_title, chapter_idea, str(exc)))
    except Exception as exc:  # noqa: BLE001 —— 任何网络/解析异常都应降级为占位正文，而不是让任务失败
        return _wrap_tech_chapter(
            req_text,
            _fallback_chapter_content(chapter_title, chapter_idea, f"调用大模型失败（{exc.__class__.__name__}）"),
        )


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
            lines.append(
                f"本公司已审核产品能力（来自产品库「{product_library_name or '未命名'}」，"
                f"共 {len(product_features)} 项，必须通读全部参数与应标原文，禁止编造未列出的能力）："
            )
            for i, feat in enumerate(product_features, start=1):
                lines.append("")
                lines.append(f"{i}. 【{feat.get('name', '')}】模块：{feat.get('module') or '未分模块'}")
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
    style = (writing_prefs or {}).get("style") or {}
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


def _new_node(node_id: str, num: str, title: str, parent_id: str | None, item: dict, expanded: bool) -> dict:
    idea = _as_str(item.get("idea"), "请补充本章编写思路")
    clean_title = _compact_catalog_title(title)
    if num and clean_title.startswith(num):
        clean_title = clean_title[len(num) :].strip()
    form = is_original_form_title(clean_title or title)
    if form:
        idea = original_form_idea(clean_title or title, idea)
    part = item.get("part") if item.get("part") in ("tech", "business", "form") else None
    if form:
        part = "form"
    kind = chapter_kind(clean_title or title, part, idea, str(item.get("requirement") or ""))
    if kind == "business":
        part = "business"
        if not form:
            idea = BUSINESS_SKIP_IDEA_PREFIX
    skip_write = kind in ("form", "business")
    return {
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
        nodes.append(_new_node(node_id, num, title, parent_id, item, expanded=depth < 4))
        if is_original_form_title(title):
            return
        children = item.get("children")
        if not isinstance(children, list) or depth >= 5:
            return
        for j, sub in enumerate(children[:120], start=1):
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


CHAT_SYSTEM_PROMPT = """你是智标云投标文件撰写助手，只根据用户提供的项目上下文回答。
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
