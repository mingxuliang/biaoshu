"""E0 招标文件解析：按早期前端固定的一级/二级分析指标逐项抽取。

指标项来自 parse_dimension_schema.json（软件服务类，与 src/mocks/parse.ts 对齐）或
parse_dimension_schema_engineering.json（工程类，与 src/mocks/parseEngineering.ts 对齐），
按项目 category 选择，不可增删。原文没有的字段填空字符串，该项仍保留在结果中。
预审/撰写用的四类尺子从该树派生。
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
        ["quantity", "bidReq", "process"],
    ],
}

SYSTEM_PROMPT = """你是招标文件解析专家。必须针对用户给出的固定分析指标逐项抽取。
只返回严格 JSON，不要其它说明，格式如下：
{
  "fills": {
    "<二级项目id>": {
      "<板块id>": {
        "<字段名>": "从原文摘录或忠实归纳的内容"
      }
    }
  }
}
硬性要求：
1. 禁止增加、删除、改名任何一级维度、二级项目、板块 id 或字段名；
2. 招标文件未提及的字段必须填空字符串，不要编造；
3. 不要输出 fills 以外的键；
4. 每个给出的二级项目和板块都要出现在 fills 中，即使全部字段都是空字符串；
5. 涉及评分因素、评分标准、评标办法、详细评审标准、扣分加分细则的字段，必须完整收录
   本段原文列出的每一项评分因素、对应权重/分值/百分比、评分档次或扣分标准，逐条收录，
   不得只写部分、不得用摘要或省略号代替原文、不得写「详见招标文件」代替表格；
6. 用户会分段提供招标全文。只抽取【本段确实出现】的内容；本段没有的字段填空字符串，
   禁止根据目录或「详见详细评审标准」臆造。后段出现的表会在系统侧与前段合并。
"""


def run(
    full_text: str,
    category: str | None = parse_schema.DEFAULT_CATEGORY,
    extra_fills: dict | None = None,
) -> dict:
    category = category if category in BATCHES_BY_CATEGORY else parse_schema.DEFAULT_CATEGORY
    tree = parse_schema.empty_tree(category)
    errors: list[str] = []
    try:
        model_id = get_default_model_id()
    except Exception as exc:  # noqa: BLE001
        if extra_fills:
            parse_schema.apply_fills(tree, extra_fills, merge=True)
        return _pack(tree, full_text, f"未配置可用大模型（{exc}），请到「模型配置」填写秘钥", category)

    chunks = _iter_chunks(full_text)
    for keys in BATCHES_BY_CATEGORY[category]:
        batch_errors = 0
        for index, chunk in enumerate(chunks, start=1):
            try:
                fills = _extract_batch(model_id, chunk, keys, category, index, len(chunks))
                parse_schema.apply_fills(tree, fills, merge=True)
            except Exception as exc:  # noqa: BLE001
                batch_errors += 1
                if index == len(chunks) and batch_errors == len(chunks):
                    errors.append(f"{'+'.join(keys)}失败（{exc.__class__.__name__}）")
                elif index == len(chunks) and batch_errors:
                    errors.append(f"{'+'.join(keys)}有 {batch_errors}/{len(chunks)} 段失败（{exc.__class__.__name__}）")

    if extra_fills:
        parse_schema.apply_fills(tree, extra_fills, merge=True)
    parse_schema.mark_completed(tree)
    filled, total = parse_schema.filled_row_counts(tree)
    error = None
    if errors and filled == 0:
        error = "调用大模型失败，" + "；".join(errors) + "。指标项已列出但内容为空，请人工核对原文"
    elif errors:
        error = "部分维度抽取失败：" + "；".join(errors) + f"。已填 {filled}/{total} 项，其余保持空白"
    return _pack(tree, full_text, error, category)


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


def _extract_batch(
    model_id: str,
    chunk: str,
    dim_keys: list[str],
    category: str,
    part: int = 1,
    total: int = 1,
) -> dict:
    catalog = parse_schema.catalog_for_keys(dim_keys, category)
    user_content = (
        "请按下列固定指标逐项抽取，id 与字段名必须原样使用。\n\n"
        f"{catalog}\n\n"
        f"以下是招标文件全文的第 {part}/{total} 段，请阅读本段全部内容后再抽取。"
        "本段未出现的字段填空，不要根据目录猜测后文。\n\n"
        f"{chunk}"
    )
    if "evalMethod" in dim_keys or "envelope" in dim_keys:
        user_content = (
            "本批次抽取评标/详细评审规则。工程类招标的真正评分点常在中后部的"
            "「详细评审标准」表（条款号 2.2.1：商务文件评审标准、技术文件评审标准），"
            "权重可能是 30%、5% 这种百分比。本段若出现该表，必须把每一项评审因素、"
            "权重、评审标准原文和赋分档次（优/良/中/一般/差对应分数）完整收录："
            "商务进 eval-business，技术进 eval-tech。"
            "禁止用「详见招标文件详细评审标准」代替表格原文。\n\n" + user_content
        )
    try:
        content = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
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
                {"role": "system", "content": SYSTEM_PROMPT},
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
    parse_schema.mark_completed(tree)
    engine = parse_schema.derive_engine_fields(tree, category)
    return {
        "dimensions": tree,
        "scoreRules": engine["scoreRules"],
        "mustRespond": engine["mustRespond"],
        "qualification": engine["qualification"],
        "formatRequirements": engine["formatRequirements"],
        "vetoParams": parse_schema.derive_veto_params(tree, full_text),
        "error": error,
    }
