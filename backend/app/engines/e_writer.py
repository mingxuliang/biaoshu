"""AI 撰写工作台引擎：基于评标尺子生成目录大纲，并逐章生成投标文件正文。

调用 DeepSeek，沿用 e0_tender_parse.py / e3_semantic.py 的调用范式（httpx + Bearer +
json_object，未配置 Key 或调用异常时降级为兜底结果，不阻塞撰写流程，也不抛错）。
"""

import json

import httpx

from ..config import get_settings

_CN_NUMS = [
    "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
]


def _cn_num(n: int) -> str:
    return _CN_NUMS[n] if 0 <= n < len(_CN_NUMS) else str(n)


OUTLINE_SYSTEM_PROMPT = """你是资深投标文件撰写专家。请依据提供的评分规则与必响应/否决条款，为投标文件正文设计一份目录大纲。
只返回严格的 JSON，不要包含任何其他文字说明，格式如下：
{
  "chapters": [
    {
      "title": "章节标题",
      "dimension": "对应的评分维度名称（尽量从提供的评分维度列表中选取一个，无法对应则填 null）",
      "weight": 数字（该章预计对应分值，可参考评分维度权重，无法判断填 0）,
      "idea": "一句话编写思路（30-60字，说明本章应写什么）",
      "aiIdea": "更详细的编写建议（80-150字，包含具体应覆盖的要点）",
      "children": [
        {"title": "子章节标题", "dimension": "...", "weight": 数字, "idea": "...", "aiIdea": "..."}
      ]
    }
  ]
}
要求：
1. 顶层章节数量控制在 6-10 个，每个顶层章节可有 0-3 个子章节，也可以没有子章节；
2. 章节标题应贴合投标文件正文的常见结构（如项目理解、技术方案、实施计划、质量保障、售后服务等），并尽量覆盖全部评分维度；
3. weight 只是参考权重，不要求精确合计为 100。
"""

CHAPTER_SYSTEM_PROMPT = """你是资深投标文件撰写专家，请围绕给定的章节标题与编写思路，撰写正式的投标文件正文内容。
写作要求：
1. 使用 Markdown 风格排版（## 二级标题、### 三级标题、- 无序列表、数字编号列表），正文长度约 500-1200 字；
2. 语言正式、专业，符合中国大陆招投标文件的行文习惯；
3. 若提供了关联评分点或必响应条款，正文应体现针对性响应，但不要逐字复制原文；
4. 若提供了参考知识库资料，应合理借鉴其思路、结构与做法，但不得直接照抄，须结合本项目实际情况改写；
5. 只返回正文内容本身，不要包含任何解释说明，也不要用 JSON 包装。
"""


def generate_outline(project_name: str, score_rules: list[dict], must_respond: list[dict]) -> list[dict]:
    """生成目录大纲。失败或未配置 Key 时返回基于 scoreRules 维度的兜底目录，不抛错。"""
    settings = get_settings()

    if not settings.deepseek_api_key:
        return _fallback_outline(score_rules)

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_outline_context(project_name, score_rules, must_respond)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

    try:
        with httpx.Client(base_url=settings.deepseek_base_url, timeout=120) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            nodes = _normalize_outline(data)
            return nodes if nodes else _fallback_outline(score_rules)
    except Exception:  # noqa: BLE001 —— 任何网络/解析异常都应降级为兜底目录，而不是让任务失败
        return _fallback_outline(score_rules)


def generate_chapter_content(
    project_name: str,
    chapter_title: str,
    chapter_idea: str,
    dimension_detail: dict | None,
    must_respond_context: list[dict],
    knowledge_snippets: list[dict] | None = None,
) -> str:
    """生成单章正文。失败或未配置 Key 时返回提示性占位文本，不抛错。"""
    settings = get_settings()

    if not settings.deepseek_api_key:
        return _fallback_chapter_content(chapter_title, chapter_idea, "未配置 DeepSeek API Key")

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": CHAPTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_chapter_context(
                    project_name,
                    chapter_title,
                    chapter_idea,
                    dimension_detail,
                    must_respond_context,
                    knowledge_snippets,
                ),
            },
        ],
        "temperature": 0.5,
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

    try:
        with httpx.Client(base_url=settings.deepseek_base_url, timeout=90) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            return text.strip() or _fallback_chapter_content(chapter_title, chapter_idea, "AI 返回内容为空")
    except Exception as exc:  # noqa: BLE001 —— 任何网络/解析异常都应降级为占位正文，而不是让任务失败
        return _fallback_chapter_content(chapter_title, chapter_idea, f"调用 DeepSeek 失败（{exc.__class__.__name__}）")


def _build_outline_context(project_name: str, score_rules: list[dict], must_respond: list[dict]) -> str:
    lines = [f"项目名称：{project_name or '（未命名项目）'}", "", "评分规则（评分维度 / 权重 / 说明）："]
    for r in score_rules[:30]:
        lines.append(f"- [{r.get('dimension', '')}] 权重 {r.get('weight', 0)} 分：{r.get('detail', '')}")
    if not score_rules:
        lines.append("（无，暂未解析出评分规则，请自行规划常见的投标文件章节结构）")
    lines.append("")
    lines.append("必响应 / 否决条款：")
    for m in must_respond[:30]:
        lines.append(f"- [{m.get('type', '')}] {m.get('clause', '')}")
    if not must_respond:
        lines.append("（无）")
    return "\n".join(lines)


def _build_chapter_context(
    project_name: str,
    chapter_title: str,
    chapter_idea: str,
    dimension_detail: dict | None,
    must_respond_context: list[dict],
    knowledge_snippets: list[dict] | None = None,
) -> str:
    lines = [
        f"项目名称：{project_name or '（未命名项目）'}",
        f"章节标题：{chapter_title}",
        f"编写思路：{chapter_idea or '（无特别说明，请自行组织内容）'}",
    ]
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
    if knowledge_snippets:
        lines.append("")
        lines.append("参考知识库资料（仅供参考，禁止逐字抄录，请结合本项目实际改写）：")
        for i, s in enumerate(knowledge_snippets[:4], start=1):
            text = (s.get("text") or "")[:300]
            lines.append(f"{i}. 《{s.get('docTitle', '')}》· {s.get('heading', '')}：{text}")
    lines.append("")
    lines.append("请撰写本章正文。")
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
    return {
        "id": node_id,
        "num": num,
        "title": title,
        "parentId": parent_id,
        "expanded": expanded,
        "weight": _as_float(item.get("weight"), 0),
        "dimension": _as_str_or_none(item.get("dimension")),
        "idea": idea,
        "aiIdea": _as_str(item.get("aiIdea"), idea),
        "optimized": False,
        "status": "待生成",
        "words": 0,
        "aiRounds": 0,
    }


def _normalize_outline(data: dict) -> list[dict]:
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return []

    nodes: list[dict] = []
    for i, ch in enumerate(chapters[:12], start=1):
        if not isinstance(ch, dict):
            continue
        title = _as_str(ch.get("title"), f"第{_cn_num(i)}章")
        node_id = f"o-{i}"
        nodes.append(_new_node(node_id, _cn_num(i), title, None, ch, expanded=True))

        children = ch.get("children")
        if isinstance(children, list):
            for j, sub in enumerate(children[:6], start=1):
                if not isinstance(sub, dict):
                    continue
                sub_title = _as_str(sub.get("title"), f"第{j}节")
                nodes.append(_new_node(f"{node_id}-{j}", f"（{_cn_num(j)}）", sub_title, node_id, sub, expanded=False))

    return nodes


def _fallback_outline(score_rules: list[dict]) -> list[dict]:
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
    for i, dim in enumerate(dims[:10], start=1):
        node_id = f"o-{i}"
        nodes.append(
            {
                "id": node_id,
                "num": _cn_num(i),
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
