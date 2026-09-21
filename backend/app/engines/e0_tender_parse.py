"""E0 招标文件解析：按早期前端固定的一级/二级分析指标逐项抽取。

指标项来自 parse_dimension_schema.json（软件服务类，与 src/mocks/parse.ts 对齐）或
parse_dimension_schema_engineering.json（工程类，与 src/mocks/parseEngineering.ts 对齐），
按项目 category 选择，不可增删。页面字段填提炼摘要，招标原文另存供 AI 预审。
找不到的字段保持空，该项仍保留在结果中。预审/撰写用的四类尺子从该树派生。
"""

import json

from . import parse_schema
from .llm import LlmError, chat_complete, get_default_model_id

# 单段送模型的长度；全文按重叠窗口逐段读完再合并，禁止只截文首。
CHUNK_CHARS = 36000
CHUNK_OVERLAP = 4000
_MAX_OUTPUT_TOKENS = 8192
# 评标办法（技术评审标准/商务标评分评审标准）单独一批，避免和其它维度抢输出预算，
# 尽量保证评分因素能被完整收录而不是被截断。
BATCHES_BY_CATEGORY = {
    "软件服务类": [
        ["basic", "qualification"],
        ["evalMethod"],
        ["review", "business", "reject"],
        ["bidReq", "rejectCheck", "docReview", "process"],
    ],
    "工程类": [
        ["basic", "qualification"],
        ["evalMethod"],
        ["envelope"],
        ["reject"],
        ["quantity", "bidReq", "process"],
    ],
}

_FILL_RULES = """
硬性要求：
1. 禁止增加、删除、改名任何一级维度、二级项目、板块 id 或字段名；
2. 招标文件未提及的字段摘要和原文都必须填空字符串，不要编造；
3. 不要输出 fills 以外的键；
4. 每个给出的二级项目和板块都要出现在 fills 中，即使全部字段都是空对象；
5. 字段值必须是对象 {"摘要":"...","原文":"..."}，禁止只返回字符串。
6. 摘要（页面展示，让人快速看懂招标要求，禁止粘贴招标正文）：
   - 改写成事实条目或短句，一条一行；删套话、重复、「投标人应当」「详见招标文件」；
   - 必须保留全部关键数字、日期、金额、百分比、条款号、岗位、证书、业绩门槛、证明文件；
   - 人员：岗位 / 资格 / 经验年限 / 证书 / 人数 一条写清；业绩：类别、金额或规模、时间窗口、类似工程定义、证明文件；
   - 招标人/代理/监督：名称、地址、联系人、电话、邮箱写在同一字段；
   - 专用设备：名称 / 规格 / 数量。
   - 投标文件组成五个字段按行对齐（第 n 行是同一份文件）：序号、文件名称、格式要求、是否必须（是/否/按需）、备注。
   - 资格审查资料四个字段按行对齐：资料类别、具体资料、是否必须、备注。
   - 禁止把清单写成一段话塞进一个字段。
   - 废标风险四个字段按行对齐（第 n 行是同一条风险），不要把四列写成一段话：
     风险点=短名称（如「投标保证金未按规定提交」）；详细描述=触发条件、数字与后果；
     风险等级只写「高」或「中」或「低」；来源/依据=条款号（如「投标人须知第3.4.1项」）。
     按开标前 / 资格性审查 / 符合性审查 / 评标定标 / 其他高风险 分项填写。
7. 评分、评标、赋分、报价公式类字段（评分因素与标准、评分细则、评分因素与权重原文、
   分档/赋分规则、评标基准价、偏差率、K值等）：
   - 摘要必须逐条完整：每一项评分因素、权重/分值、优/良/中/差（或 A/B/C）及对应分数、
     计算公式与全部参数（K值区间、偏差率、E系数、有效报价区间、去最高最低等）一条不漏；
   - 禁止省略号、禁止只写「详见原文/详见招标文件」代替表格；
   - 「评分因素与权重原文」只写因素名称+分值/权重清单，不要把分档文字再贴一遍；
   - 「分档/赋分规则」写每个因素的分档分数；报价公式写完整算式与参数，不要写策略建议。
8. 原文（锁定评标尺子与后续 AI 预审用）：只摘该字段对应的招标条款原文（含条款号），
   不要把整章投标人须知粘进来。摘要与原文必须分开写，禁止把原文整段复制进摘要。
9. 用户会分段提供全文。只抽取【本段确实出现】的内容；本段没有的字段填空字符串。
   后段出现的表会在系统侧与前段合并。
10. 权威顺序：答疑补遗 > 招标文件正文。同一字段冲突时只保留答疑补遗口径。
"""

SYSTEM_PROMPT = """你是招标文件解析专家。必须针对用户给出的固定分析指标逐项抽取。
写法对齐专业解读报告：页面展示的是提炼后的事实表，不是招标正文粘贴。
原文单独保存，供锁定评标尺子。
只返回严格 JSON，不要其它说明，格式如下：
{
  "fills": {
    "<二级项目id>": {
      "<板块id>": {
        "<字段名>": {"摘要": "压缩后的事实条目", "原文": "对应条款原文"}
      }
    }
  }
}
""" + _FILL_RULES

ADDENDUM_SYSTEM_PROMPT = """你是招标文件解析专家。当前材料【仅为答疑补遗】，效力高于招标文件正文。
写法对齐专业解读报告：页面展示提炼后的有效口径，不是答疑全文粘贴。
只返回严格 JSON，不要其它说明，格式如下：
{
  "fills": {
    "<二级项目id>": {
      "<板块id>": {
        "<字段名>": {"摘要": "答疑后的有效口径", "原文": "答疑对应条款原文"}
      }
    }
  }
}
硬性要求：
1. 禁止增加、删除、改名任何一级维度、二级项目、板块 id 或字段名；
2. 答疑补遗未提及的字段摘要和原文都必须填空字符串，不要用招标正文的记忆来填；
3. 不要输出 fills 以外的键；
4. 每个给出的二级项目和板块都要出现在 fills 中，即使全部字段都是空对象；
5. 字段值必须是对象 {"摘要":"...","原文":"..."}，禁止只返回字符串；
6. 答疑中变更的评分、否决、资格、格式、工期、金额等，必须按答疑最新口径完整收录；
   评分表仍须逐条保留因素、权重、分档分数和公式参数，不得省略；
7. 与招标文件冲突时只写答疑口径，不要写「原文为…现改为…」的并列句；
8. 摘要删套话、写成可扫读事实；原文摘对应条款（含条款号）供锁定评标尺子，二者不得相同粘贴。
"""


def run(
    full_text: str,
    category: str | None = parse_schema.DEFAULT_CATEGORY,
    extra_fills: dict | None = None,
    addendum_text: str | None = None,
) -> dict:
    category = category if category in BATCHES_BY_CATEGORY else parse_schema.DEFAULT_CATEGORY
    tree = parse_schema.empty_tree(category)
    errors: list[str] = []
    skip_item_ids: set[str] = {"qty-drawing"}
    if isinstance(extra_fills, dict):
        if extra_fills.get("qty-boq"):
            skip_item_ids.add("qty-boq")
        if extra_fills.get("misc-other"):
            skip_item_ids.add("misc-other")
        # 专用合同条款由全部文件另册抽取；两遍都跳过，避免答疑空字段冲掉已填内容。
        if extra_fills.get("contract-tech"):
            skip_item_ids.add("contract-tech")

    try:
        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        _apply_extra_fills(tree, extra_fills)
        return _pack(tree, _authority_text(full_text, addendum_text), f"未配置可用大模型（{exc}），请到「模型配置」填写秘钥", category)

    chunks = _iter_chunks(full_text)
    for keys in BATCHES_BY_CATEGORY[category]:
        batch_errors = 0
        for index, chunk in enumerate(chunks, start=1):
            try:
                fills = _extract_batch(
                    model_id, chunk, keys, category, index, len(chunks), skip_item_ids=skip_item_ids
                )
                parse_schema.apply_fills(tree, fills, merge=True)
            except Exception as exc:  # noqa: BLE001
                batch_errors += 1
                if index == len(chunks) and batch_errors == len(chunks):
                    errors.append(f"{'+'.join(keys)}失败（{exc.__class__.__name__}）")
                elif index == len(chunks) and batch_errors:
                    errors.append(f"{'+'.join(keys)}有 {batch_errors}/{len(chunks)} 段失败（{exc.__class__.__name__}）")

    addendum = (addendum_text or "").strip()
    if addendum:
        add_chunks = _iter_chunks(addendum)
        for keys in BATCHES_BY_CATEGORY[category]:
            batch_errors = 0
            for index, chunk in enumerate(add_chunks, start=1):
                try:
                    fills = _extract_batch(
                        model_id,
                        chunk,
                        keys,
                        category,
                        index,
                        len(add_chunks),
                        skip_item_ids=skip_item_ids,
                        addendum=True,
                    )
                    parse_schema.apply_fills(tree, fills, replace=True)
                except Exception as exc:  # noqa: BLE001
                    batch_errors += 1
                    if index == len(add_chunks) and batch_errors == len(add_chunks):
                        errors.append(f"答疑补遗{'+'.join(keys)}失败（{exc.__class__.__name__}）")
                    elif index == len(add_chunks) and batch_errors:
                        errors.append(
                            f"答疑补遗{'+'.join(keys)}有 {batch_errors}/{len(add_chunks)} 段失败（{exc.__class__.__name__}）"
                        )

    _apply_extra_fills(tree, extra_fills)
    parse_schema.mark_completed(tree)
    filled, total = parse_schema.filled_row_counts(tree)
    error = None
    if errors and filled == 0:
        error = "调用大模型失败，" + "；".join(errors) + "。指标项已列出但内容为空，请人工核对原文"
    elif errors:
        error = "部分维度抽取失败：" + "；".join(errors) + f"。已填 {filled}/{total} 项，其余保持空白"
    return _pack(tree, _authority_text(full_text, addendum_text), error, category)


def _iter_chunks(full_text: str) -> list[str]:
    """把招标全文切成重叠窗口，保证中后部「详细评审标准」等章节都会被读到。"""
    text = full_text or ""
    if not text:
        return [""]
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _apply_extra_fills(tree: list[dict], extra_fills: dict | None) -> None:
    """Excel 清单与其他材料覆盖写入，避免和大模型摘要拼接。其余字段仍与模型结果合并。"""
    if not extra_fills:
        return
    overwrite = {}
    rest = {}
    for key, value in extra_fills.items():
        if key in {"qty-boq", "misc-other", "contract-tech", "qty-drawing"}:
            overwrite[key] = value
        else:
            rest[key] = value
    if rest:
        parse_schema.apply_fills(tree, rest, merge=True)
    if overwrite:
        parse_schema.apply_fills(tree, overwrite, merge=False)


def _authority_text(full_text: str, addendum_text: str | None) -> str:
    addendum = (addendum_text or "").strip()
    base = full_text or ""
    if not addendum:
        return base
    return addendum + "\n\n" + base


def _extract_batch(
    model_id: str,
    chunk: str,
    dim_keys: list[str],
    category: str,
    part: int = 1,
    total: int = 1,
    skip_item_ids: set[str] | None = None,
    addendum: bool = False,
) -> dict:
    catalog = parse_schema.catalog_for_keys(dim_keys, category, skip_item_ids=skip_item_ids)
    if addendum:
        user_content = (
            "请按下列固定指标抽取答疑补遗中的有效条款，id 与字段名必须原样使用。"
            "每个字段填 {摘要, 原文}。摘要提炼给人看，原文摘条款供锁定评标尺子。未在答疑中出现的字段摘要和原文都填空。"
            "与招标文件冲突时只保留答疑口径。\n\n"
            f"{catalog}\n\n"
            f"以下是答疑补遗的第 {part}/{total} 段。\n\n"
            f"{chunk}"
        )
        system = ADDENDUM_SYSTEM_PROMPT
    else:
        user_content = (
            "请按下列固定指标逐项抽取，id 与字段名必须原样使用。每个字段填 {摘要, 原文}。"
            "摘要写提炼后的事实，原文摘对应条款，供锁定评标尺子。\n\n"
            f"{catalog}\n\n"
            f"以下是招标文件全文的第 {part}/{total} 段，请阅读本段全部内容后再抽取。"
            "本段未出现的字段填空，不要根据目录猜测后文。\n\n"
            f"{chunk}"
        )
        system = SYSTEM_PROMPT
    if "evalMethod" in dim_keys or "envelope" in dim_keys:
        user_content = (
            "本批次抽取评标/详细评审规则。"
            + (
                "技术标评分表进 eval-tech：摘要按「评分项目 + 分值」逐条列出，"
                "优/良/中/一般/差（或 A/B/C）及对应分数写入分档/赋分规则，一条不漏；"
                "技术标暗标编制要点、评分门槛一并抽取。"
                "专用合同条款本批次不填。"
                if "evalMethod" in dim_keys
                else ""
            )
            + (
                "商务评分进 eval-business（因素+分值与分档分开写）；"
                "报价公式、K 值、偏差率、E 系数、有效报价区间写入 env-price。"
                if "envelope" in dim_keys
                else ""
            )
            + "禁止用「详见招标文件详细评审标准」代替表格，也禁止把整章投标人须知粘进评分因素字段。"
            + ("答疑补遗若改了评分表，以答疑最新表为准。\n\n" if addendum else "\n\n")
            + user_content
        )
    if "reject" in dim_keys:
        user_content = (
            "本批次抽取无效标与废标风险，对齐专业解读报告 E 模块。"
            "每个二级项目填四列：风险点、详细描述、风险等级、来源/依据；"
            "四列摘要按换行对齐，一行一条风险，禁止把一条风险挤进单个字段。"
            "风险点写短名，风险等级只写高/中/低，来源/依据写条款号。"
            "不要整章粘贴投标人须知。\n\n"
            + user_content
        )
    if "bidReq" in dim_keys:
        user_content = (
            "本批次抽取投标文件要求，对齐专业解读报告 F 模块。"
            "req-compose 填五列：序号、文件名称、格式要求、是否必须、备注，按换行对齐，一行一份文件；"
            "req-qualdocs 填四列：资料类别、具体资料、是否必须、备注，一行一份资料。"
            "是否必须只写是/否/按需。禁止把整张组成表写成一段话。\n\n"
            + user_content
        )
    try:
        content = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            timeout=180,
            max_tokens=_MAX_OUTPUT_TOKENS,
            extra={"response_format": {"type": "json_object"}},
        )
    except LlmError:
        content = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            timeout=180,
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1]
    data = json.loads(raw)
    fills = data.get("fills") if isinstance(data, dict) else None
    if not isinstance(fills, dict):
        fills = data if isinstance(data, dict) else {}
        fills.pop("fills", None)
    return fills


def _pack(tree: list[dict], full_text: str, error: str | None, category: str | None = parse_schema.DEFAULT_CATEGORY) -> dict:
    parse_schema.ensure_originals(tree)
    parse_schema.mark_completed(tree)
    engine = parse_schema.derive_engine_fields(tree, category)
    parse_schema.distill_display(tree)
    return {
        "dimensions": tree,
        "scoreRules": engine["scoreRules"],
        "mustRespond": engine["mustRespond"],
        "qualification": engine["qualification"],
        "formatRequirements": engine["formatRequirements"],
        "omittedCount": engine.get("omittedCount") or {},
        "vetoParams": parse_schema.derive_veto_params(tree, full_text),
        "error": error,
    }
