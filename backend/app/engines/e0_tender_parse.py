"""E0 招标文件解析：按早期前端固定的一级/二级分析指标逐项抽取。

指标项来自 parse_dimension_schema.json（与 src/mocks/parse.ts 对齐），不可增删。
原文没有的字段填空字符串，该项仍保留在结果中。预审/撰写用的四类尺子从该树派生。
"""

import json

import httpx

from ..config import get_settings
from . import parse_schema

MAX_CHARS = 48000
BATCHES = [
    ["basic", "qualification"],
    ["review", "business", "reject"],
    ["bidReq", "rejectCheck", "docReview", "process"],
]

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
4. 每个给出的二级项目和板块都要出现在 fills 中，即使全部字段都是空字符串。
"""


def run(full_text: str) -> dict:
    tree = parse_schema.empty_tree()
    settings = get_settings()
    if not settings.deepseek_api_key:
        return _pack(tree, full_text, "未配置 DeepSeek API Key，指标项已列出但内容为空，请人工核对原文")

    truncated = (full_text or "")[:MAX_CHARS]
    errors: list[str] = []
    for keys in BATCHES:
        try:
            fills = _extract_batch(settings, truncated, keys)
            parse_schema.apply_fills(tree, fills)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{'+'.join(keys)}失败（{exc.__class__.__name__}）")

    parse_schema.mark_completed(tree)
    filled, total = parse_schema.filled_row_counts(tree)
    error = None
    if errors and filled == 0:
        error = "调用 DeepSeek 失败，" + "；".join(errors) + "。指标项已列出但内容为空，请人工核对原文"
    elif errors:
        error = "部分维度抽取失败：" + "；".join(errors) + f"。已填 {filled}/{total} 项，其余保持空白"
    return _pack(tree, full_text, error)


def _extract_batch(settings, truncated: str, dim_keys: list[str]) -> dict:
    catalog = parse_schema.catalog_for_keys(dim_keys)
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请按下列固定指标逐项抽取，id 与字段名必须原样使用。\n\n"
                    f"{catalog}\n\n"
                    "以下是招标文件正文（可能因篇幅截断）：\n\n"
                    f"{truncated}"
                ),
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}
    with httpx.Client(base_url=settings.deepseek_base_url, timeout=180) as client:
        resp = client.post("/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    fills = data.get("fills") if isinstance(data, dict) else None
    if not isinstance(fills, dict):
        # 容错：有的模型直接把 itemId 放在根上
        fills = data if isinstance(data, dict) else {}
        fills.pop("fills", None)
    return fills


def _pack(tree: list[dict], full_text: str, error: str | None) -> dict:
    parse_schema.mark_completed(tree)
    engine = parse_schema.derive_engine_fields(tree)
    return {
        "dimensions": tree,
        "scoreRules": engine["scoreRules"],
        "mustRespond": engine["mustRespond"],
        "qualification": engine["qualification"],
        "formatRequirements": engine["formatRequirements"],
        "vetoParams": parse_schema.derive_veto_params(tree, full_text),
        "error": error,
    }
