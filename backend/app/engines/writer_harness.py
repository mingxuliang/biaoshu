"""AgentScope 2.0 撰写编排。

只在这里引用 agentscope。工作区按用户、项目、草稿和单次任务隔开，
不注册 shell，也不给模型任意读写文件的工具。密钥只留在进程里。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class HarnessError(Exception):
    """Harness 无法完成撰写或对话修改。"""


def workspace_root() -> Path:
    raw = (os.environ.get("WRITER_WORKSPACE_ROOT") or "/app/workspaces").strip()
    return Path(raw)


def _safe_id(value: str, label: str) -> str:
    text = (value or "").strip()
    if not _ID.match(text):
        raise HarnessError(f"{label}不能进入工作区")
    return text


def scoped_workspace(user_id: str, project_id: str, draft_id: str, *parts: str) -> Path:
    """解析并创建隔离目录。路径跳出根目录时拒绝。"""
    chunks = [
        _safe_id(user_id, "用户"),
        _safe_id(project_id, "项目"),
        _safe_id(draft_id, "草稿"),
    ]
    for part in parts:
        chunks.append(_safe_id(part, "任务"))
    root = workspace_root().resolve()
    path = root.joinpath(*chunks).resolve()
    if path != root and root not in path.parents:
        raise HarnessError("工作区越界")
    path.mkdir(parents=True, exist_ok=True)
    return path


def content_edit_block_reason(node: dict) -> str | None:
    """报价和固定格式件、商务标不能被对话改写成技术方案。"""
    from .e_writer import chapter_kind, is_original_form_title

    title = str(node.get("title") or "")
    if "报价" in title:
        return "不能修改报价数字或报价文件"
    kind = chapter_kind(
        title,
        node.get("part"),
        str(node.get("idea") or ""),
        str(node.get("requirement") or ""),
    )
    if kind in ("form", "business") or is_original_form_title(title):
        return "固定格式件和商务标不能改写成技术方案"
    return None


def _parent_key(node: dict) -> str | None:
    parent = node.get("parentId")
    if parent in (None, "", False):
        return None
    return str(parent)


def _cn_num(index: int) -> str:
    digit = "零一二三四五六七八九"
    tens = ["", "十", "二十", "三十", "四十", "五十", "六十", "七十", "八十", "九十"]
    if index <= 0:
        return str(index)
    if index <= 10:
        return "一二三四五六七八九十"[index - 1]
    if index < 20:
        return f"十{digit[index - 10]}"
    if index < 100:
        tens_i, ones = divmod(index, 10)
        return tens[tens_i] if ones == 0 else f"{tens[tens_i]}{digit[ones]}"
    return str(index)


def format_outline_num(depth: int, index: int, parent_num: str) -> str:
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


def renumber_outline(nodes: list[dict]) -> list[dict]:
    result = [dict(item) for item in nodes]

    def children(parent_id: str | None) -> list[dict]:
        return [item for item in result if _parent_key(item) == parent_id]

    def walk(parent_id: str | None, depth: int, parent_num: str) -> None:
        for index, item in enumerate(children(parent_id), start=1):
            item["num"] = format_outline_num(depth, index, parent_num)
            walk(str(item.get("id") or ""), depth + 1, item["num"])

    walk(None, 0, "")
    return result


def _subtree_ids(outline: list[dict], node_id: str) -> set[str]:
    ids = {node_id}
    changed = True
    while changed:
        changed = False
        for item in outline:
            current = str(item.get("id") or "")
            if current and _parent_key(item) in ids and current not in ids:
                ids.add(current)
                changed = True
    return ids


def _last_index_of_subtree(outline: list[dict], node_id: str) -> int:
    ids = _subtree_ids(outline, node_id)
    last = -1
    for index, item in enumerate(outline):
        if str(item.get("id") or "") in ids:
            last = index
    return last


def _new_outline_node(title: str, parent_id: str | None, idea: str = "", part: str = "tech") -> dict:
    body = (idea or "").strip() or "请描述本章编写思路…"
    volume = part if part in ("tech", "business", "form") else "tech"
    return {
        "id": f"p-{uuid.uuid4().hex[:12]}",
        "num": "",
        "title": title[:24],
        "parentId": parent_id,
        "expanded": False,
        "weight": 0,
        "dimension": None,
        "idea": body[:8000],
        "aiIdea": body[:8000],
        "optimized": False,
        "status": "待生成",
        "words": 0,
        "aiRounds": 0,
        "part": volume,
    }


def outline_add(
    outline: list[dict],
    *,
    titles: list[str],
    parent_id: str = "",
    after_id: str = "",
    idea: str = "",
    part: str = "tech",
) -> tuple[list[dict], list[dict]]:
    names = [item.strip() for item in titles if (item or "").strip()]
    if not names:
        raise HarnessError("缺少要新增的目录标题")
    nodes = [dict(item) for item in outline]
    by_id = {str(item.get("id") or ""): item for item in nodes}
    parent: str | None = (parent_id or "").strip() or None
    after = (after_id or "").strip()
    if after:
        if after not in by_id:
            raise HarnessError("插入位置不存在")
        if parent is None:
            parent = _parent_key(by_id[after])
        insert_at = _last_index_of_subtree(nodes, after) + 1
    elif parent:
        if parent not in by_id:
            raise HarnessError("父节点不存在")
        by_id[parent]["expanded"] = True
        insert_at = _last_index_of_subtree(nodes, parent) + 1
    else:
        insert_at = len(nodes)
    created = [_new_outline_node(name, parent, idea, part) for name in names]
    nodes[insert_at:insert_at] = created
    return renumber_outline(nodes), created


def outline_delete(outline: list[dict], chapter_ids: list[str]) -> tuple[list[dict], list[str]]:
    wanted = [item.strip() for item in chapter_ids if (item or "").strip()]
    if not wanted:
        raise HarnessError("缺少章节编号")
    existing = {str(item.get("id") or "") for item in outline}
    found = [item for item in wanted if item in existing]
    if not found:
        raise HarnessError("章节不存在")
    drop: set[str] = set()
    for chapter_id in found:
        drop |= _subtree_ids(outline, chapter_id)
    remain = [dict(item) for item in outline if str(item.get("id") or "") not in drop]
    if not remain:
        raise HarnessError("不能删光全部目录")
    return renumber_outline(remain), sorted(drop)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise HarnessError("Harness 没有返回可解析的 JSON")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise HarnessError("Harness 返回的 JSON 无法解析") from exc
    if not isinstance(data, dict):
        raise HarnessError("Harness 返回的 JSON 不是对象")
    return data


def _outline_has_heading(markdown: str) -> bool:
    """多行目录里只要有一行 Markdown 标题就算有。整段 search 会把换行后的标题漏掉。"""
    for line in (markdown or "").splitlines():
        if _HEADING.match(line.strip()):
            return True
    return False


def _bad_outline_headings(markdown: str) -> list[str]:
    bad: list[str] = []
    for line in (markdown or "").splitlines():
        match = _HEADING.match(line.strip())
        if not match:
            continue
        title = match.group(2).strip()
        if (
            not title
            or len(title) > 24
            or title.endswith(("。", "；", ";", "？", "?"))
            or re.match(r"^(支持|须|必须|应当|应能|包括|因|对于)", title)
        ):
            bad.append(title[:40] or "空标题")
    return bad


def _min_solution_chars(requirement: str) -> int:
    """正文不能只复述标题：下限随条款长度增长，封顶 1200 字。"""
    size = len(re.sub(r"\s+", "", requirement or ""))
    if size < 20:
        return 0
    return min(max(200, int(size * 0.8)), 1200)


def _coverage_problems(
    obligations: list[dict],
    solution: str,
    product_names: list[str],
    require_gap: bool,
    facts: list[str] | None = None,
    min_chars: int = 0,
    response_marks: list[str] | None = None,
    evidence: str = "",
) -> list[str]:
    from .writer_tool_runtime import missing_hard_facts

    compact = re.sub(r"\s+", "", solution or "")
    problems: list[str] = []
    if facts:
        absent = missing_hard_facts(facts, solution)
        if absent:
            problems.append(
                "正文缺少招标条款里的指标，必须原样写出并说明如何满足："
                + "、".join(f"「{item}」" for item in absent[:12])
            )
    if min_chars and len(compact) < min_chars:
        problems.append(f"正文只有 {len(compact)} 字，不足以逐条应答本章条款，至少需要约 {min_chars} 字")
    for item in obligations:
        title = re.sub(r"\s+", "", str(item.get("title") or ""))
        if title and title not in compact:
            problems.append(f"缺少义务标题「{item.get('title')}」")
    names = [name for name in product_names if (name or "").strip()]
    if names:
        if not any(re.sub(r"\s+", "", name) in compact for name in names):
            problems.append("未引用已绑定的产品功能名称")
    elif require_gap and "能力缺口" not in (solution or ""):
        problems.append("没有产品功能时必须写明能力缺口")
    for phrase in response_marks or []:
        if phrase and phrase not in compact:
            problems.append(f"正文没有按本份招标书的应答规定写出「{phrase}」")
    if evidence:
        for claim in unsupported_claims(solution, evidence):
            problems.append(f"正文声称「{claim}」，但给定的招标条款和公司资料里没有依据，请删除或改成「待补充」")
    return problems


_CLAIM_PATTERNS = (
    re.compile(r"ISO\s?-?\d{4,5}(?::\d{4})?", re.I),
    re.compile(r"CMMI\s?-?\d?(?:级)?", re.I),
    re.compile(r"等保\s?[二三四五2345]\s?级|信息安全等级保护[二三四五]级"),
    re.compile(r"(?:软件著作权|软著)登记证书|专利号\s?[A-Z0-9.]+|ZL\s?\d{4}[0-9X.]+"),
    re.compile(r"\d+\s?(?:项|个|件)(?:软著|发明专利|专利|成功案例|类似案例)"),
)


def unsupported_claims(solution: str, evidence: str) -> list[str]:
    """正文里的认证、证书、专利、案例数量等断言，必须能在给定材料里找到原样出处。"""
    material = re.sub(r"\s+", "", evidence or "").upper()
    found: list[str] = []
    for pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(solution or ""):
            claim = match.group(0).strip()
            key = re.sub(r"\s+", "", claim).upper()
            if key and key not in material and claim not in found:
                found.append(claim)
    return found[:8]


def _make_model(model_id: str | None, stream: bool = False):
    from agentscope.credential import OpenAICredential
    from agentscope.model import OpenAIChatModel

    from .llm import LlmError, resolve_llm

    try:
        resolved = resolve_llm(model_id)
    except LlmError as exc:
        raise HarnessError(str(exc)) from exc
    base = (resolved.base_url or "").rstrip("/")
    if not base:
        raise HarnessError("未配置模型地址")
    key = (resolved.api_key or "").strip() or "local"
    return OpenAIChatModel(
        credential=OpenAICredential(api_key=key, base_url=base),
        model=resolved.api_model,
        stream=stream,
        client_kwargs={"timeout": 300},
    )


def _make_agent(
    name: str,
    system_prompt: str,
    model_id: str | None,
    workdir: Path,
    workspace_id: str,
    tools: list,
    max_iters: int,
    stream: bool = False,
    track: str = "software",
):
    from agentscope.agent import Agent, ReActConfig
    from agentscope.tool import Toolkit
    from agentscope.workspace import LocalWorkspace

    from .writer_tool_runtime import skill_directories

    dirs = skill_directories(track)
    try:
        from agentscope.skill import LocalSkillLoader

        loaders: list = [LocalSkillLoader(directory=item, scan_subdir=False) for item in dirs]
    except Exception:  # noqa: BLE001 —— 旧版没有 LocalSkillLoader 时退回逐个目录
        loaders = dirs
    toolkit = Toolkit(tools=tools, skills_or_loaders=loaders or None)
    return Agent(
        name=name,
        system_prompt=system_prompt,
        model=_make_model(model_id, stream=stream),
        toolkit=toolkit,
        offloader=LocalWorkspace(workdir=str(workdir), workspace_id=workspace_id),
        react_config=ReActConfig(max_iters=max_iters),
    )


async def _reply(agent, text: str) -> str:
    from agentscope.message import UserMsg

    msg = await agent.reply(UserMsg(name="user", content=text))
    body = (msg.get_text_content() or "").strip()
    reason = getattr(getattr(msg, "finished_reason", ""), "value", getattr(msg, "finished_reason", ""))
    if reason == "error":
        raise HarnessError("模型调用失败，请稍后重试")
    if not body:
        raise HarnessError("轮次用完仍没有结果" if reason == "exceed_max_iters" else "Harness 没有返回内容")
    return body


_TOOL_TITLES = {
    "read_chapter": "读取章节",
    "replace_chapter": "改写正文",
    "update_outline": "修改目录",
    "add_outline_node": "新增目录",
    "delete_outline_node": "删除目录",
    "read_upload": "阅读附件",
    "read_tender": "阅读招标摘录",
    "export_draft_docx": "导出 Word",
    "collect_material": "搜集素材",
    "run_skill_script": "运行 Skill 脚本",
    "search_knowledge": "检索知识库",
    "read_knowledge_section": "阅读知识库章节",
    "make_diagram": "绘制结构图",
    "generate_illustration": "生成示意图",
    "insert_image": "插入图片",
    "set_layout": "调整 Word 排版",
}
_TRACE_DETAIL_MAX = 12000


def new_chat_trace(model_id: str = "") -> dict:
    """一次对话的过程记录。步骤会随 AgentScope 事件增长。"""
    detail = "撰写对话代理"
    if model_id:
        detail += f" · 模型 {model_id}"
    return {
        "reply": "",
        "steps": [{"id": "engine", "kind": "engine", "title": "AgentScope", "detail": detail}],
    }


def chat_trace_snapshot(state: dict) -> list[dict]:
    rows = []
    for step in state.get("steps") or []:
        item = {
            "id": step.get("id") or "",
            "kind": step.get("kind") or "step",
            "title": step.get("title") or "",
            "detail": step.get("detail") or "",
        }
        if step.get("kind") == "tool":
            item["args"] = step.get("args") or ""
            item["result"] = step.get("result") or ""
            if step.get("state") in ("ERROR", "DENIED"):
                item["status"] = "error"
            else:
                item["status"] = "done" if step.get("state") or step.get("result") else "calling"
        rows.append(item)
    return rows


def _event_name(event) -> str:
    raw = getattr(event, "type", "")
    value = getattr(raw, "value", raw)
    return str(value or "")


def _trace_step(state: dict, step_id: str) -> dict | None:
    for step in state["steps"]:
        if step.get("id") == step_id:
            return step
    return None


def _clip_trace(text: str) -> str:
    body = text or ""
    if len(body) <= _TRACE_DETAIL_MAX:
        return body
    return body[:_TRACE_DETAIL_MAX] + "\n……（已截断）"


def apply_chat_event(state: dict, event) -> None:
    """把 AgentScope 的一条事件折进过程记录。未知事件忽略。"""
    if hasattr(event, "get_text_content"):
        body = (event.get_text_content() or "").strip()
        if body:
            state["reply"] = body
        return
    name = _event_name(event)
    if name == "MODEL_CALL_START":
        count = sum(1 for step in state["steps"] if step.get("kind") == "model") + 1
        state["steps"].append(
            {
                "id": f"model-{count}",
                "kind": "model",
                "title": f"第 {count} 次调用模型",
                "detail": str(getattr(event, "model_name", "") or ""),
            }
        )
        return
    if name == "MODEL_CALL_END":
        models = [step for step in state["steps"] if step.get("kind") == "model"]
        if not models:
            return
        current = models[-1]
        detail = current.get("detail") or ""
        detail += (
            f"\n输入 {getattr(event, 'input_tokens', 0)} token，"
            f"输出 {getattr(event, 'output_tokens', 0)} token"
        )
        current["detail"] = detail.strip()
        return
    if name == "THINKING_BLOCK_START":
        state["steps"].append(
            {"id": f"think-{getattr(event, 'block_id', '')}", "kind": "thinking", "title": "思考", "detail": ""}
        )
        return
    if name == "THINKING_BLOCK_DELTA":
        step = _trace_step(state, f"think-{getattr(event, 'block_id', '')}")
        if step is not None:
            step["detail"] = _clip_trace(step.get("detail", "") + str(getattr(event, "delta", "") or ""))
        return
    if name == "TOOL_CALL_START":
        tool = str(getattr(event, "tool_call_name", "") or "工具")
        label = _TOOL_TITLES.get(tool, tool)
        state["steps"].append(
            {
                "id": f"tool-{getattr(event, 'tool_call_id', '')}",
                "kind": "tool",
                "title": f"{label} · {tool}",
                "detail": "",
                "args": "",
                "result": "",
            }
        )
        return
    if name == "TOOL_CALL_DELTA":
        step = _trace_step(state, f"tool-{getattr(event, 'tool_call_id', '')}")
        if step is not None:
            step["args"] = _clip_trace(step.get("args", "") + str(getattr(event, "delta", "") or ""))
            step["detail"] = _tool_detail(step)
        return
    if name == "TOOL_RESULT_TEXT_DELTA":
        step = _trace_step(state, f"tool-{getattr(event, 'tool_call_id', '')}")
        if step is not None:
            step["result"] = _clip_trace(step.get("result", "") + str(getattr(event, "delta", "") or ""))
            step["detail"] = _tool_detail(step)
        return
    if name == "TOOL_RESULT_END":
        step = _trace_step(state, f"tool-{getattr(event, 'tool_call_id', '')}")
        if step is not None:
            raw = getattr(event, "state", "")
            step["state"] = str(getattr(raw, "value", raw) or "").upper()
        return
    if name == "REPLY_END":
        reason = str(getattr(getattr(event, "finished_reason", ""), "value", getattr(event, "finished_reason", "")) or "")
        if reason == "exceed_max_iters" and not _trace_step(state, "max-iters"):
            state["steps"].append({"id": "max-iters", "kind": "limit", "title": "达到推理轮次上限", "detail": ""})
        elif reason == "error":
            error = getattr(event, "error", None)
            state["error"] = str(getattr(error, "message", "") or "模型调用失败")
        return
    if name == "TEXT_BLOCK_DELTA":
        block_id = str(getattr(event, "block_id", "") or "")
        step = _trace_step(state, f"text-{block_id}")
        if step is None:
            step = {"id": f"text-{block_id}", "kind": "reply", "title": "生成回复", "detail": ""}
            state["steps"].append(step)
        step["detail"] = _clip_trace(step.get("detail", "") + str(getattr(event, "delta", "") or ""))
        if step["detail"].strip():
            state["reply"] = step["detail"].strip()
        return
    if name == "TEXT_BLOCK_END":
        block_id = str(getattr(event, "block_id", "") or "")
        final = getattr(event, "text", None)
        step = _trace_step(state, f"text-{block_id}")
        if isinstance(final, str) and final.strip():
            if step is None:
                step = {"id": f"text-{block_id}", "kind": "reply", "title": "生成回复", "detail": ""}
                state["steps"].append(step)
            step["detail"] = _clip_trace(final)
        if step and step.get("detail", "").strip():
            state["reply"] = step["detail"].strip()
        return
    if name == "EXCEED_MAX_ITERS":  # 已弃用事件，仍兼容；正式信号在 REPLY_END.finished_reason
        if not _trace_step(state, "max-iters"):
            state["steps"].append({"id": "max-iters", "kind": "limit", "title": "达到推理轮次上限", "detail": ""})


def _tool_detail(step: dict) -> str:
    parts = []
    if step.get("args"):
        parts.append(f"参数\n{step['args']}")
    if step.get("result"):
        parts.append(f"结果\n{step['result']}")
    return "\n\n".join(parts)


async def _reply_with_trace(agent, content, on_trace=None, model_id: str = "") -> tuple[str, list[dict]]:
    """边接收 AgentScope 事件边整理思考、工具和回复。"""
    from agentscope.message import UserMsg

    state = new_chat_trace(model_id)
    last_emit = 0.0

    def publish(force: bool = False) -> None:
        nonlocal last_emit
        if on_trace is None:
            return
        now = time.monotonic()
        if not force and now - last_emit < 0.2:
            return
        last_emit = now
        on_trace(chat_trace_snapshot(state), state.get("reply") or "")

    try:
        user_msg = UserMsg(name="user", content=content)
    except Exception:  # noqa: BLE001 —— 多模态块校验失败时只保留文字，绝不把 base64 当文字发给模型
        text_only = content if isinstance(content, str) else next(
            (getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text"), ""
        )
        user_msg = UserMsg(name="user", content=text_only)
    async for event in agent.reply_stream(user_msg, yield_final_msg=True):
        apply_chat_event(state, event)
        name = _event_name(event)
        publish(force=name.endswith("_END") or name.endswith("_START") or name == "REPLY_END")
    publish(True)
    if state.get("error") and not (state["reply"] or "").strip():
        raise HarnessError(f"模型调用失败：{state['error']}")
    reply = (state["reply"] or "").strip()
    if not reply:
        raise HarnessError("Harness 没有返回内容")
    return reply, chat_trace_snapshot(state)


def write_outline_markdown(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    project_name: str,
    tender_text: str,
    tender_toc: dict | None,
    score_rules: list[dict],
    must_respond: list[dict],
    format_requirements: list | None = None,
    doc_kind: str = "tech",
    page: dict | None = None,
    layout: dict | None = None,
    review_feedback: str = "",
) -> str:
    """用隔离工作区里的新 Agent 通读招标书原文、生成目录 Markdown。失败时抛出，不回退套话目录。

    不再把招标解析模块预抽出的技术标/商务标摘要当主输入：原文全文落地到工作区，
    由智能体自己调用 read_tender(section="original") 分页通读、自行判断需求边界。
    """
    from .e_writer import _build_outline_user_message, outline_system_prompt
    from .writer_tool_runtime import (
        load_original_tender_text,
        load_tender_extracts,
        materialize_full_tender_text,
        materialize_tender_extracts,
        original_tender_page_count,
    )

    workdir = scoped_workspace(user_id, project_id, draft_id, "jobs", job_id)
    materialize_tender_extracts(workdir, load_tender_extracts(project_id))
    if not (tender_text or "").strip():
        tender_text = load_original_tender_text(project_id)
    materialize_full_tender_text(workdir, tender_text)
    total_pages = original_tender_page_count(tender_text)
    prompt = _build_outline_user_message(
        project_name,
        tender_text,
        tender_toc,
        score_rules,
        must_respond,
        format_requirements,
        doc_kind=doc_kind,
        total_pages=total_pages,
        page=page,
        layout=layout,
    )
    if (review_feedback or "").strip():
        prompt += "\n\n" + review_feedback.strip()
    _write_text(workdir / "outline-brief.txt", prompt[:80000])
    _write_text(workdir / "doc_kind.txt", (doc_kind or "tech").strip().lower())
    from .tender_toc import composition_for_volume, extract_bid_composition

    _write_text(
        workdir / "composition.txt",
        "\n".join(c["title"] for c in composition_for_volume(extract_bid_composition(tender_text), doc_kind)),
    )

    async def _run() -> str:
        agent = _make_agent(
            "outline-writer",
            outline_system_prompt(doc_kind)
            + "\n招标书原文在 read_tender(section=\"original\")。先检索格式节，不要从第 1 页逐页翻到最后。"
            "一级章只用该节里属于当前分册的文件名。评标办法不进目录。"
            "依据行写「依据：T5」或「依据：B3」。"
            "目录可写入 outline.md，再用 run_skill_script 运行 bid-outline/lint_outline.py 检查标题。不要为评审标准补章。不要打开浏览器，不要导出 Word。",
            model_id,
            workdir,
            f"{user_id}-{draft_id}-{job_id}",
            _job_tools(workdir, project_id),
            16,
        )
        markdown = await _reply(agent, prompt)
        _write_text(workdir / "outline-raw.txt", markdown[:80000])
        if not re.search(r"^#{1,6}\s+\S", markdown, re.M):
            markdown = await _reply(
                agent,
                "上一次回复没有 Markdown 标题。请只重写目录，不要解释。"
                "一级标题用 #，必须使用本份组成条目的原文，可以长于12字；小章节用 ##、### 挂在对应一级标题下面。"
                "依据行保留。",
            )
            _write_text(workdir / "outline-raw.txt", markdown[:80000])
        bad = _bad_outline_headings(markdown)
        if bad:
            listed = "\n".join(f"- {item}" for item in bad[:12])
            markdown = await _reply(
                agent,
                "下列标题不合格，请只重写目录 Markdown。"
                "说明句收成不超过12字的短标题，标题不要自带编号，不要输出解释；各标题下的「依据：T5」行原样保留。\n"
                + listed,
            )
        if not re.search(r"^#{1,6}\s+\S", markdown, re.M):
            raise HarnessError("目录结果里没有 Markdown 标题")
        still = _bad_outline_headings(markdown)
        if still:
            raise HarnessError("目录标题仍是说明句，未通过验收：" + "；".join(still[:6]))
        return markdown

    return asyncio.run(_run())


ENG_OUTLINE_SYSTEM = """你是房建、市政等工程施工组织设计（技术标）目录编辑。不要按水利、农田、灌区的目录来编。

# 一级章对标
只取本份招标书技术标评分表里的评审因素，每个因素一个一级章。
章名用评分项原文，含括号里的「包括但不限于…」，不要改写、不要拆开、不要合并。
一个评分项把工期质量和安全文明写在同一格时，仍用这一格原文做章名。
形式评审、资格评审、响应性评审、商务评分、业绩、奖项、企业实力、合同条款、投标人须知不进目录。
编制说明只作封面，不要占一级章。

# 二级目录是施工理解，不是把一级章名拆开
先根据工程事实形成本工程的施工理解：有哪些单体、哪些专业、分几段施工、现场有什么约束、有哪些工艺系统。
再把这些理解挂到最对应的一级评分项下面。禁止用「保障体系」「主要措施」「检查与考核」这类套话当二级标题。
工程概述、施工总体部署（含分阶段总平面，阶段名用来自事实账的施工阶段）挂在第一个技术评分项下面，不要另起一级章。
工期、质量、安全、文明只在对应评分项下出现，标题对着本工程的管理目标写，不要空对空展开章名。
人材机拆成劳动力、主要物资、施工机械。招标写了智慧工地、绿色建筑等级的，挂在对应保障章下。

# 包括但不限于和重难点
评分项括号里点名的内容必须单独成节，放在该章最前面，节名用点名原文。
招标点名的重点难点各自成节。其余重难点只从现场约束、工艺系统、专业交叉、单体和工程量里取，必须能在事实账里找到出处。
每条下面只用两节：重难点分析、重难点解决措施。
分析只写一段：现场约束、工程量和影响，不写措施。
措施写（1）（2）（3），每条先给短措施名，再写做法、数量、机械和责任岗位。
危大工程单独一节：先清单，再保证措施。招标没写危大就不要编。
招标要求的附表按原文放在「附件」下。国家及地方工法规范里已有的内容不要重复编成章节。

# 输出
只输出 Markdown 标题：# 一级、## 二级、### 三级、#### 四级。标题不要自带编号。
每个末级节点下一行「思路：…」，不超过 200 字。除此之外不要解释。
不要写知识库、产品功能、公司业绩、获奖、人员姓名。同一内容只出现在最对应的那一章。
"""

WATER_OUTLINE_SYSTEM = """你是水利工程施工组织设计（技术标）目录编辑。只编水利、灌区、高标准农田、河道、堤防、泵站涵闸、水库塘坝。不要套房建、市政的目录。

# 一级章
只取本份招标书「施工组织设计」或技术标评分表里的评审因素，每个因素一个一级章。
章名用评分项原文，含括号里的「包括但不限于…」，不要改写、不要合并。
形式评审、资格评审、响应性评审、商务评分、合同条款、投标人须知不进目录。
不要把第一章写成「编制说明」。编制依据、工程概况、水文地质、主要工程数量放在「主要施工方案」章的第一节，不要单独成一级章。

# 二级目录是施工理解，不是把一级章名拆开
先根据工程事实形成本工程的施工理解：区段、构筑物、清单分项、工程量、汛期、灌排约束。禁止用「保障体系」「主要措施」当二级标题。
评分项是施工方案、技术措施或主要施工方法时，按工程量清单的分项工程展开，一项一节。
节名用分项名称，并写上清单里的数量，例如「农用井工程（180 眼）」「沟渠疏浚工程（80.13km）」「梁板桥工程（30 座）」。没有数量就写【待核实】。
每一分项下面按工序排：施工工艺流程、分步施工、质量控制要点。不要把所有分项揉成一节「主要施工方法」。
测量放线、施工排水与降排水、季节性施工（含农忙、灌溉期）按招标范围单列。
拦河、筑坝、沟渠截流的，必须有施工导流或围堰。跨汛或招标要求度汛的，必须有度汛。水土保持与环境保护按招标范围该有就要有。

# 重难点章
评分项是工程重难点或保证措施时，先写「工程特点与重难点识别」：用表格归纳作业面、构筑物数量、土方量、工期、灌排交叉、地质、既有设施。
然后按本工程清单自己识别 5～8 条重难点，节名写成「重难点：数量＋问题」，例如「180 眼农用井分布施工组织与成井质量」。招标点名的必须保留，其余从工程量大、点位分散、灌溉不能中断、季节窗口、交叉施工里取。节名不要用口语化问句。
每条重难点下面固定三节：重难点分析、重难点解决措施、保证措施汇总。
分析要分条，写清工程量、点位分布、地质水文、工期窗口、对灌排或度汛的影响，数字来自清单和招标原文。
解决措施用（1）（2）（3）（4），每条先给短措施名，再写时限、数量、机械、施工顺序。
保证措施汇总写成表：措施、对应难点、责任岗位、实施时间。
高标准农田、灌区还要有：施工期不得中断灌排、分段施工与临时导流、农忙保障、少占耕地、临时用地复垦。

# 资源、进度、平面
物资、机械、劳动力若评分表分列，就分章，不要合成一章人材机。进度章保留横道图或网络图节点。总平面和临时用地按招标附表名称放在「附件」下。

# 输出
只输出 Markdown 标题：# 一级、## 二级、### 三级、#### 四级。标题不要自带编号。
每个末级节点下一行「思路：…」，不超过 200 字。除此之外不要解释。
不要写知识库、产品功能、公司业绩、获奖、人员姓名。同一内容只出现在最对应的那一章。
可参考 water-bid skill。
"""


def write_engineering_outline_markdown(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    project_name: str,
    tender_text: str,
    facts: dict,
    specialty: str = "",
    track: str = "engineering",
    review_feedback: str = "",
) -> str:
    """让智能体通读招标原文编施工组织设计目录。失败时抛 HarnessError，由调用方决定是否回退骨架。"""
    from .engineering_writer import facts_brief
    from .writer_tool_runtime import (
        load_original_tender_text,
        materialize_full_tender_text,
        original_tender_page_count,
    )

    workdir = scoped_workspace(user_id, project_id, draft_id, "jobs", job_id)
    if not (tender_text or "").strip():
        tender_text = load_original_tender_text(project_id)
    materialize_full_tender_text(workdir, tender_text)
    total_pages = original_tender_page_count(tender_text)
    brief = facts_brief(facts, specialty=specialty)
    _write_text(workdir / "eng_facts.txt", brief)

    lines = [
        f"项目名称：{project_name or '（未命名项目）'}",
        f"专业：{specialty or '未标明'}",
        "",
        "请先通读本份招标文件原文，形成对本工程怎么施工的理解，再编目录。"
        "一级章只对技术评分项。二级目录不要把章名拆成套话，要用下面的施工理解（单体、专业、阶段、现场约束、工艺系统、清单分项）挂到对应评分项下。",
        "",
        "已经从本份招标文件抽出的工程事实（作为核对用，不要据此编造原文没有的内容）：",
        brief or "（没有抽出工程事实，请完全以招标原文为准）",
        "",
    ]
    if tender_text and len(tender_text) <= 16000:
        lines.append("----------招标文件原文（全文已贴在下面）----------")
        lines.append(tender_text)
    else:
        lines.append(
            f"招标文件原文较长（约 {len(tender_text or '')} 字），已存入 read_tender(section=\"original\")，共约 {total_pages} 页。"
            "不要从第 1 页逐页翻到最后。"
            + (
                "用 query 检索「评分」「施工组织设计」「工程量」「沟渠」「灌溉」「度汛」「导流」「附表」，读中后再编目录。"
                if track == "water"
                else "用 query 检索「评分」「技术标」「重点难点」「附表」「危险性较大」，读中后再编目录。"
            )
        )
    prompt = "\n".join(lines)
    if (review_feedback or "").strip():
        prompt += "\n\n" + review_feedback.strip()
    _write_text(workdir / "outline-brief.txt", prompt[:80000])
    _write_text(workdir / "doc_kind.txt", "tech")

    async def _run() -> str:
        system = (WATER_OUTLINE_SYSTEM if track == "water" else ENG_OUTLINE_SYSTEM) + (
            "\n招标原文在 read_tender(section=\"original\")，工程事实在工作区 eng_facts.txt。"
            "不要打开浏览器，不要导出 Word，不要检索知识库和产品库。"
        )
        agent = _make_agent(
            "water-outline-writer" if track == "water" else "eng-outline-writer",
            system,
            model_id,
            workdir,
            f"{user_id}-{draft_id}-{job_id}",
            _job_tools(workdir, project_id),
            16,
            track=track,
        )
        markdown = await _reply(agent, prompt)
        _write_text(workdir / "outline-raw.txt", markdown[:80000])
        if not _outline_has_heading(markdown):
            markdown = await _reply(
                agent,
                "上一次回复没有 Markdown 标题。请只重写目录，不要解释。"
                "一级标题用 #，章名用评分项原文，可以长于 12 字；下级用 ##、###、####；"
                "每个末级节点下保留一行「思路：…」。",
            )
            _write_text(workdir / "outline-raw.txt", markdown[:80000])
        return markdown

    return asyncio.run(_run())


UNGROUNDED_REWRITE_MIN = 3


def write_engineering_chapter(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    node: dict,
    outline: list[dict],
    facts: dict,
    layout: dict | None = None,
    specialty: str = "",
    plan: dict | None = None,
) -> str:
    """施工组织设计的一节正文由智能体撰写，可翻招标原文核对。

    写完查一遍数字出处，水利再过校核闸，有问题发回重写一轮。智能体失败时退回原来的单次生成，不让这一节空着。
    """
    from .engineering_check import edit_block_reason
    from .engineering_writer import (
        ENG_CHAPTER_SYSTEM,
        WATER_CHAPTER_SYSTEM,
        chapter_prompt_for,
        normalize_table_markdown,
        ungrounded_numbers,
        write_chapter,
    )

    def fallback() -> str:
        return write_chapter(
            node, outline, facts, model_id=model_id, project_id=project_id, layout=layout, specialty=specialty, plan=plan
        )

    prompt = chapter_prompt_for(
        node, outline, facts, project_id=project_id, layout=layout, specialty=specialty, plan=plan
    )
    workdir = scoped_workspace(user_id, project_id, draft_id, "jobs", job_id)
    _write_text(workdir / "chapter-brief.txt", prompt[:80000])
    from .writer_tool_runtime import load_original_tender_text, materialize_full_tender_text

    tender_text = load_original_tender_text(project_id)
    materialize_full_tender_text(workdir, tender_text)
    system = WATER_CHAPTER_SYSTEM if specialty == "水利" else ENG_CHAPTER_SYSTEM
    system += (
        "\n招标原文在 read_tender(section=\"original\")，写到工期、工程量、规范编号时先核对原文。"
        "不要检索知识库和产品库，不要编造业绩、证书和人员姓名。只输出 Markdown 表格。"
    )
    tools = [tool for tool in _job_tools(workdir, project_id) if getattr(tool, "name", "") == "read_tender"]

    async def _once(agent, ask: str) -> str:
        raw = await _reply(agent, ask)
        return normalize_table_markdown(raw)

    async def _run() -> str:
        agent = _make_agent(
            "eng-chapter-writer",
            system,
            model_id,
            workdir,
            f"{user_id}-{draft_id}-{job_id}",
            tools,
            16,
            track="water" if specialty == "水利" else "engineering",
        )
        content = await _once(agent, prompt + "\n\n请只输出本节的 Markdown 表格。")
        if not content.strip():
            return content
        advice: list[str] = []
        loose = ungrounded_numbers(content, prompt + "\n" + (tender_text or ""))
        if len(loose) >= UNGROUNDED_REWRITE_MIN:
            advice.append(
                "下面这些数字在工程事实、本节清单、施工计划账和招标原文里都找不到出处："
                + "、".join(loose[:12])
                + "。改成有出处的数字，没有出处的写【待核实】。"
            )
        if specialty == "水利":
            blocked, notes = edit_block_reason(facts, outline, {}, str(node.get("id") or ""), content)
            if blocked:
                advice.append(blocked)
            elif notes:
                advice.append("本节仍有建议：\n" + "\n".join(f"- {item}" for item in notes))
        if not advice:
            return content
        return await _once(agent, "校核未通过，只重写本节表格，改掉下面的问题，不要解释：\n" + "\n".join(advice))

    try:
        return asyncio.run(_run())
    except HarnessError:
        logger.exception("engineering chapter harness failed")
        return fallback()
    except Exception:  # noqa: BLE001 —— 智能体异常不让这一节空着
        logger.exception("engineering chapter harness crashed")
        return fallback()


def review_outline_markdown(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    outline_text: str,
    composition: list[dict],
    ledger: list[dict],
) -> list[str]:
    """第二个智能体评审目录：只对照招标原文和台账找问题，不改目录。返回问题清单，空表示通过。"""
    from .writer_tool_runtime import (
        load_original_tender_text,
        load_tender_extracts,
        materialize_full_tender_text,
        materialize_tender_extracts,
    )

    workdir = scoped_workspace(user_id, project_id, draft_id, "jobs", job_id)
    materialize_tender_extracts(workdir, load_tender_extracts(project_id))
    materialize_full_tender_text(workdir, load_original_tender_text(project_id))
    wanted = "\n".join(f"- {c.get('title')}" for c in composition) or "（本份招标书没有写明组成清单）"
    musts = "\n".join(
        f"- {e['id']} {str(e.get('text') or '')[:60]} → "
        + ("、".join(e.get("chapters") or []) or "没有章节")
        for e in ledger
        if e.get("mandatory")
    )[:6000]
    prompt = (
        "请评审下面这份投标目录是否完全应标。对照招标原文（read_tender）检查：\n"
        "1. 大章是否与本份招标书列出的投标文件或响应文件一致、顺序一致；\n"
        "2. 采购需求、技术标准、发包人要求里的必须条款是否写在对应文件下；评标办法、合同条款、投标人须知里的否决情形出现在目录里则是问题；\n"
        "3. 小章标题是否来自格式节或需求部分，有没有把评审因素、合同条款写成章节；\n"
        "4. 各章是否放在含义对应的大章下。\n"
        f"组成清单：\n{wanted}\n\n必须项与其章节：\n{musts or '（无）'}\n\n待评审目录：\n{outline_text}\n\n"
        '只返回 JSON：{"pass":true或false,"issues":["问题，说明哪个章节怎么改"]}。没有明确问题时 pass 为 true，issues 为空。'
    )

    async def _run() -> list[str]:
        agent = _make_agent(
            "outline-reviewer",
            "你是投标目录评审员，只评审、不改写。以招标原文为准，问题要具体到章节名。不要打开浏览器，不要导出 Word。",
            model_id,
            workdir,
            f"{user_id}-{draft_id}-{job_id}",
            _job_tools(workdir, project_id),
            12,
        )
        data = _extract_json_object(await _reply(agent, prompt))
        if data.get("pass") is True and not data.get("issues"):
            return []
        return [str(x).strip() for x in (data.get("issues") or []) if str(x).strip()][:12]

    return asyncio.run(_run())


def write_tech_chapter(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    prompt: str,
    product_names: list[str],
    require_gap: bool,
    chapter_id: str = "",
    chapter_title: str = "",
    chapter_idea: str = "",
    requirement: str = "",
    enable_figures: bool = True,
    fact_text: str = "",
) -> str:
    """拆义务、写解决方案，按标题、条款里的数字指标和篇幅下限验收，最多重写两轮；
    验收后由智能体判断是否配结构图。fact_text 是必须逐项应答的条款原文，为空则不查数字指标。"""
    workdir = scoped_workspace(user_id, project_id, draft_id, "jobs", job_id)
    _write_text(workdir / "chapter-brief.txt", prompt[:80000])
    from .writer_tool_runtime import (
        extract_hard_facts,
        load_original_tender_text,
        load_tender_extracts,
        materialize_full_tender_text,
        materialize_tender_extracts,
    )

    materialize_tender_extracts(workdir, load_tender_extracts(project_id))
    original_text = load_original_tender_text(project_id)
    materialize_full_tender_text(workdir, original_text)
    from .e_writer import chapter_follows_response_rule
    from .tender_toc import extract_response_rules, response_checks

    response_rule = "\n".join(extract_response_rules(original_text)).strip()
    response_marks = response_checks(response_rule) if chapter_follows_response_rule(chapter_title) else []
    _write_text(workdir / "response_rule.txt", response_rule)
    _write_text(workdir / "response_checks.txt", "\n".join(response_marks))
    if response_rule and response_marks:
        prompt += (
            "\n\n本份招标书对应答写法的规定如下，解决方案必须照这些原句写，"
            "不要改成另一套格式，也不要只写自由段落：\n"
            + response_rule
        )
        _write_text(workdir / "chapter-brief.txt", prompt[:80000])
    facts = extract_hard_facts(fact_text) if fact_text.strip() else []
    min_chars = _min_solution_chars(fact_text)
    _write_text(workdir / "requirement.txt", (requirement or fact_text or "")[:20000])
    _write_text(workdir / "facts.txt", "\n".join(facts))
    _write_text(workdir / "min_chars.txt", str(min_chars))
    binding = DraftBinding(user_id, draft_id, chapter_id)
    figure_state: dict = {
        "title": chapter_title,
        "idea": chapter_idea,
        "solution": "",
        "figures": [],
    }
    hint = f"{chapter_title}\n{chapter_idea}"
    figures_on = bool(enable_figures and chapter_id and _wants_figure(hint))
    illustration_on = bool(figures_on and _ILLUSTRATION_HINT.search(f"{hint}\n{requirement}"))
    tools = [
        *_job_tools(workdir, project_id, draft_id),
        *_extra_tools(binding, state=figure_state, chat=False, allow_illustration=illustration_on),
    ]
    if not figures_on:
        tools = [tool for tool in tools if tool.name not in ("make_diagram", "generate_illustration")]

    async def _run() -> str:
        agent = _make_agent(
            "chapter-writer",
            "你是投标文件技术标撰写专家。只根据给定材料和已绑定产品能力写作，禁止编造未列出的功能。"
            "需要核对招标条款时调用 read_tender。需要真实案例、方案、参数时调用 search_knowledge，"
            "必要时 read_knowledge_section，知识库没有的内容不要编。"
            "可把义务写成 obligations.json、正文写成 chapter.md，"
            "再用 run_skill_script 运行 bid-chapter/check_coverage.py。不要打开浏览器，不要导出 Word。"
            "本章招标条款在工作区 requirement.txt，招标书原文可用 read_tender(section=\"original\") 核对；"
            "条款里的数字、期限、数量、版本必须在正文里逐项写出，并说明本方案如何满足，不能只复述标题。"
            "make_diagram 和 generate_illustration 只在被要求配图时才调用，写正文阶段不要调用。",
            model_id,
            workdir,
            f"{user_id}-{draft_id}-{job_id}",
            tools,
            20,
        )
        raw = await _reply(
            agent,
            prompt
            + "\n\n先不要写正文。把本章拆成义务清单，只返回 JSON："
            '{"obligations":[{"title":"不超过12字","text":"对应招标要求"}]}。'
            "title 必须是短标题，不要编号。",
        )
        data = _extract_json_object(raw)
        obligations = [item for item in (data.get("obligations") or []) if isinstance(item, dict) and item.get("title")]
        if not obligations:
            raise HarnessError("没有拆出可验收的义务标题")
        obligations = obligations[:40]
        titles = "\n".join(f"- {item.get('title')}" for item in obligations)
        fact_note = ""
        if facts:
            fact_note = (
                "\n招标条款里的下列指标必须原样出现在正文，每项都要写明本方案如何满足：\n"
                + "\n".join(f"- {item}" for item in facts)
            )
        if response_marks:
            fact_note += "\n正文还必须按本份招标书的应答规定写出这些字样：" + "、".join(
                f"「{item}」" for item in response_marks
            )
        solution = await _reply(
            agent,
            "现在只写解决方案 Markdown。每个义务标题必须原样出现在正文中。"
            "不要输出「原始需求」标题，不要解释。\n义务标题：\n"
            + titles
            + fact_note,
        )
        evidence_text = prompt + "\n" + (requirement or "") + "\n" + (fact_text or "")
        problems = _coverage_problems(
            obligations, solution, product_names, require_gap, facts, min_chars, response_marks, evidence_text
        )
        for _ in range(3):
            if not problems:
                break
            solution = await _reply(
                agent,
                "验收未通过，只重写解决方案 Markdown，补上这些问题，不要解释：\n" + "\n".join(f"- {item}" for item in problems),
            )
            problems = _coverage_problems(
                obligations, solution, product_names, require_gap, facts, min_chars, response_marks, evidence_text
            )
        if problems:
            raise HarnessError("技术章验收未通过：" + "；".join(problems[:8]))
        if figures_on and _wants_figure(f"{hint}\n{solution}"):
            figure_state["solution"] = solution
            illustrate = (
                "；本章明确要求示意图时，可再调用 generate_illustration"
                if illustration_on
                else ""
            )
            try:
                await _reply(
                    agent,
                    "正文已通过验收，现在判断是否需要配图。涉及系统架构、业务流程、组织、部署、进度时，"
                    "调用 make_diagram（kind 选最贴切的类型，after_heading 填要放在哪个小节标题后面，caption 不超过 20 字）"
                    + illustrate
                    + "。整章最多 2 张，不需要就直接回复“无需配图”，不要重写正文。",
                )
            except HarnessError:
                pass  # 配图失败不影响正文
            solution = insert_figures_into_markdown(solution, figure_state["figures"]) if figure_state["figures"] else solution
        return solution

    return asyncio.run(_run())


_FIGURE_HINT = re.compile(r"架构|流程|组织|部署|拓扑|进度|施工|应急|报验|审批|总体设计|总体方案|网络")
_ILLUSTRATION_HINT = re.compile(r"示意图|效果图|配图|插图|图片|照片")


def _wants_figure(text: str) -> bool:
    return bool(_FIGURE_HINT.search(text or ""))


class DraftBinding:
    """对话工具只能改绑定的这一份草稿，每次写之前重新检查用户权限。"""

    def __init__(self, user_id: str, draft_id: str, chapter_id: str | None):
        self.user_id = user_id
        self.draft_id = draft_id
        self.chapter_id = (chapter_id or "").strip()
        self.edits: list[dict] = []

    def _open(self, for_update: bool = False):
        """for_update=True 时锁住草稿行，批量并发写章节不会互相覆盖。"""
        from fastapi import HTTPException
        from sqlalchemy.orm.attributes import flag_modified

        from ..db import SessionLocal
        from ..models import User, WriterDraft
        from ..permissions import PERM_WRITER, require_project

        db = SessionLocal()
        try:
            user = db.get(User, self.user_id)
            if for_update:
                draft = db.query(WriterDraft).filter(WriterDraft.id == self.draft_id).with_for_update().first()
            else:
                draft = db.get(WriterDraft, self.draft_id)
            if user is None or draft is None:
                raise HarnessError("草稿不存在")
            require_project(db, user, draft.project_id, PERM_WRITER)
            return db, draft, flag_modified
        except HTTPException as exc:
            db.close()
            raise HarnessError(str(exc.detail)) from exc
        except HarnessError:
            db.close()
            raise
        except Exception:
            db.close()
            raise

    def _node(self, draft, chapter_id: str) -> dict:
        node = next((item for item in (draft.outline_json or []) if item.get("id") == chapter_id), None)
        if not isinstance(node, dict):
            raise HarnessError("章节不存在")
        return node

    def read_chapter(self, chapter_id: str) -> str:
        target = (chapter_id or "").strip() or self.chapter_id
        db, draft, _flag = self._open()
        try:
            lines = ["目录："]
            for node in draft.outline_json or []:
                if not isinstance(node, dict):
                    continue
                parent = _parent_key(node) or "顶层"
                lines.append(
                    f"- {node.get('id')} {node.get('num') or ''} {node.get('title') or ''} parent={parent}".strip()
                )
            if not target:
                return "\n".join(lines[:200])
            node = self._node(draft, target)
            content = str((draft.chapter_contents_json or {}).get(target) or "")
            return (
                "\n".join(lines[:40])
                + f"\n\n当前章节 {node.get('id')} {node.get('title')}\n编写思路：{node.get('idea') or ''}\n正文：\n{content[:6000]}"
            )
        finally:
            db.close()

    def replace_chapter(self, chapter_id: str, content: str) -> str:
        target = (chapter_id or "").strip() or self.chapter_id
        if not target:
            raise HarnessError("缺少章节编号")
        body = (content or "").strip()
        if not body:
            raise HarnessError("正文不能为空")
        db, draft, flag_modified = self._open(True)
        try:
            node = self._node(draft, target)
            reason = content_edit_block_reason(node)
            if reason:
                raise HarnessError(reason)
            contents = dict(draft.chapter_contents_json or {})
            water_notes: list[str] = []
            from ..models import Project
            from .engineering_writer import TRACK_WATER, writer_track

            project = db.get(Project, draft.project_id)
            if (
                writer_track(
                    project.category if project else "",
                    project.specialty if project else "",
                    draft.doc_kind,
                )
                == TRACK_WATER
            ):
                from .engineering_check import check_inputs, edit_block_reason

                settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
                extra = check_inputs(db, draft.project_id, contents)
                blocked, water_notes = edit_block_reason(
                    settings.get("engFacts"),
                    draft.outline_json or [],
                    contents,
                    target,
                    body,
                    extra,
                )
                if blocked:
                    raise HarnessError(blocked)
            contents[target] = body
            draft.chapter_contents_json = contents
            flag_modified(draft, "chapter_contents_json")
            outline = [dict(item) for item in (draft.outline_json or [])]
            for item in outline:
                if item.get("id") == target:
                    item["status"] = "已完成"
                    item["words"] = len(body.replace(" ", "").replace("\n", ""))
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
            edit = {"chapterId": target, "content": body}
            self.edits.append(edit)
            if water_notes:
                return f"已更新章节 {target}\n本节仍有建议，请继续改到符合水利施组规则：\n" + "\n".join(
                    f"- {note}" for note in water_notes
                )
            return f"已更新章节 {target}"
        finally:
            db.close()

    def update_outline(self, chapter_id: str, title: str = "", idea: str = "") -> str:
        target = (chapter_id or "").strip() or self.chapter_id
        if not target:
            raise HarnessError("缺少章节编号")
        new_title = (title or "").strip()
        new_idea = (idea or "").strip()
        if not new_title and not new_idea:
            raise HarnessError("没有要修改的标题或编写思路")
        db, draft, flag_modified = self._open(True)
        try:
            self._node(draft, target)
            outline = [dict(item) for item in (draft.outline_json or [])]
            edit: dict = {"chapterId": target}
            for item in outline:
                if item.get("id") != target:
                    continue
                if new_title:
                    if "报价" in str(item.get("title") or "") and "报价" not in new_title:
                        raise HarnessError("不能把报价文件改成其他章节")
                    item["title"] = new_title[:80]
                    edit["title"] = item["title"]
                if new_idea:
                    item["idea"] = new_idea[:8000]
                    item["aiIdea"] = item["idea"]
                    edit["idea"] = item["idea"]
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
            self.edits.append(edit)
            return f"已修改目录节点 {target}"
        finally:
            db.close()

    def add_outline_node(
        self,
        title: str = "",
        titles: list[str] | None = None,
        parent_id: str = "",
        after_id: str = "",
        idea: str = "",
    ) -> str:
        names = [item.strip() for item in (titles or []) if (item or "").strip()]
        if (title or "").strip():
            names.insert(0, title.strip())
        db, draft, flag_modified = self._open(True)
        try:
            outline, created = outline_add(
                [item for item in (draft.outline_json or []) if isinstance(item, dict)],
                titles=names,
                parent_id=parent_id,
                after_id=after_id,
                idea=idea,
                part=(draft.doc_kind or "tech"),
            )
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
            for node in created:
                self.edits.append({"chapterId": node["id"], "title": node.get("title") or "", "added": True})
            lines = [f"{node.get('num') or ''} {node.get('title')} id={node['id']}".strip() for node in created]
            return "已新增目录：\n" + "\n".join(lines)
        finally:
            db.close()

    def delete_outline_node(self, chapter_id: str = "", chapter_ids: list[str] | None = None) -> str:
        ids = [item.strip() for item in (chapter_ids or []) if (item or "").strip()]
        if chapter_id:
            ids.extend(part.strip() for part in re.split(r"[,，\s]+", chapter_id) if part.strip())
        db, draft, flag_modified = self._open(True)
        try:
            outline, deleted = outline_delete(
                [item for item in (draft.outline_json or []) if isinstance(item, dict)],
                ids,
            )
            contents = dict(draft.chapter_contents_json or {})
            for item_id in deleted:
                contents.pop(item_id, None)
            draft.outline_json = outline
            draft.chapter_contents_json = contents
            flag_modified(draft, "outline_json")
            flag_modified(draft, "chapter_contents_json")
            db.commit()
            for item_id in deleted:
                self.edits.append({"chapterId": item_id, "deleted": True})
            return f"已删除 {len(deleted)} 个目录节点，并重新编号"
        finally:
            db.close()

    # ---- 知识库：只查本草稿已选中的文档 ----

    def search_knowledge(self, query: str, top_k: int = 4) -> str:
        from .knowledge_retrieval import retrieve_for_chapter

        text = (query or "").strip()
        if not text:
            raise HarnessError("缺少检索词")
        db, draft, _flag = self._open()
        try:
            doc_ids = [str(item) for item in (draft.selected_knowledge_json or []) if item]
            if not doc_ids:
                return "本草稿没有选择知识库文档，请先在撰写设置里勾选知识库。"
            hits = retrieve_for_chapter(db, doc_ids, text, top_k=max(1, min(int(top_k or 4), 6)))
            return _format_knowledge_hits(hits)
        finally:
            db.close()

    def read_knowledge_section(self, doc_id: str, heading: str) -> str:
        from .knowledge_retrieval import retrieve_by_doc_and_headings

        doc = (doc_id or "").strip()
        title = (heading or "").strip()
        if not doc or not title:
            raise HarnessError("缺少 doc_id 或 heading")
        db, draft, _flag = self._open()
        try:
            allowed = {str(item) for item in (draft.selected_knowledge_json or []) if item}
            if doc not in allowed:
                raise HarnessError("这份文档不在本草稿选中的知识库里")
            hits = retrieve_by_doc_and_headings(db, doc, [title], max_slices=12)
            return _format_knowledge_hits(hits, limit=9000)
        finally:
            db.close()

    # ---- 配图：结构图本地绘制，文生图走方舟，统一落成 WriterImage ----

    def chapter_text(self, chapter_id: str = "") -> tuple[str, str, str, str]:
        """返回 (章节 id, 标题, 编写思路, 已保存正文)。"""
        target = (chapter_id or "").strip() or self.chapter_id
        if not target:
            raise HarnessError("缺少章节编号")
        db, draft, _flag = self._open()
        try:
            node = self._node(draft, target)
            return (
                target,
                str(node.get("title") or ""),
                str(node.get("idea") or ""),
                str((draft.chapter_contents_json or {}).get(target) or ""),
            )
        finally:
            db.close()

    def _save_image(self, db, draft, png_or_path, *, mode: str, prompt: str, filename: str, from_path: bool) -> str:
        from .. import storage
        from ..models import WriterImage

        if from_path:
            storage_path = str(png_or_path)
        else:
            storage_path = storage.put_bytes(f"writer-images/{draft.project_id}", png_or_path, ".png", "image/png")
        img = WriterImage(
            project_id=draft.project_id,
            source="generated",
            mode=mode if mode in ("normal", "flow", "arch") else "normal",
            prompt=prompt[:500],
            filename=filename,
            storage_path=storage_path,
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return img.id

    def _figure_count(self, text: str, state: dict | None) -> int:
        count = len(re.findall(r"!\[[^\]]*\]\(/api/writer-images/", text or ""))
        if state is not None:
            count += len(state.get("figures") or [])
        return count

    def _place_figure(
        self,
        chapter_id: str,
        image_id: str,
        caption: str,
        after_heading: str,
        state: dict | None,
    ) -> None:
        md = f"![{caption}](/api/writer-images/{image_id}/file)"
        if state is not None:
            state.setdefault("figures", []).append({"markdown": md, "caption": caption, "afterHeading": after_heading})
            return
        target = (chapter_id or "").strip() or self.chapter_id
        db, draft, flag_modified = self._open(True)
        try:
            node = self._node(draft, target)
            reason = content_edit_block_reason(node)
            if reason:
                raise HarnessError(reason)
            contents = dict(draft.chapter_contents_json or {})
            body = insert_figures_into_markdown(
                str(contents.get(target) or ""),
                [{"markdown": md, "caption": caption, "afterHeading": after_heading}],
            )
            contents[target] = body
            draft.chapter_contents_json = contents
            flag_modified(draft, "chapter_contents_json")
            outline = [dict(item) for item in (draft.outline_json or [])]
            for item in outline:
                if item.get("id") == target:
                    item["words"] = len(body.replace(" ", "").replace("\n", ""))
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
            self.edits.append({"chapterId": target, "content": body})
        finally:
            db.close()

    def make_diagram(
        self, kind: str, chapter_id: str = "", after_heading: str = "", caption: str = "", state: dict | None = None
    ) -> str:
        from .writer_diagram import DIAGRAM_KINDS, DiagramError, create_diagram_png

        if kind not in DIAGRAM_KINDS:
            raise HarnessError("kind 只能是：" + "、".join(DIAGRAM_KINDS))
        if state is not None:
            title, idea, text = state.get("title") or "", state.get("idea") or "", state.get("solution") or ""
            target = (chapter_id or "").strip() or self.chapter_id
            if not text.strip():
                raise HarnessError("正文还没写好，等正文通过验收后再配图")
        else:
            target, title, idea, text = self.chapter_text(chapter_id)
        limit = 2 if state is not None else 6
        if self._figure_count(text, state) >= limit:
            raise HarnessError(f"本章已有 {limit} 张图，不再新增")
        db, draft, _flag = self._open()
        try:
            model_id = draft.model_id
        finally:
            db.close()
        try:
            png, mode, prompt, _notice = create_diagram_png(model_id, kind, title, text, idea)
        except DiagramError as exc:
            raise HarnessError(str(exc)) from exc
        db, draft, _flag = self._open()
        try:
            image_id = self._save_image(db, draft, png, mode=mode, prompt=prompt, filename=f"{prompt}.png", from_path=False)
        finally:
            db.close()
        label = (caption or prompt or DIAGRAM_KINDS[kind][0]).strip()[:40]
        self._place_figure(target, image_id, label, after_heading, state)
        return f"已生成{DIAGRAM_KINDS[kind][0]}图并写入章节，图 id={image_id}，图注：{label}"

    def make_illustration(
        self, prompt: str, mode: str = "normal", chapter_id: str = "", after_heading: str = "", caption: str = "", state: dict | None = None
    ) -> str:
        from .ark_image import ArkImageError, generate_and_save

        text = (prompt or "").strip()
        if not text:
            raise HarnessError("缺少生图描述")
        if state is not None:
            target = (chapter_id or "").strip() or self.chapter_id
            existing = state.get("solution") or ""
            if not existing.strip():
                raise HarnessError("正文还没写好，等正文通过验收后再配图")
        else:
            target, _title, _idea, existing = self.chapter_text(chapter_id)
        if self._figure_count(existing, state) >= (2 if state is not None else 6):
            raise HarnessError("本章配图已够，不再新增")
        db, draft, _flag = self._open()
        try:
            project_id = draft.project_id
        finally:
            db.close()
        try:
            storage_path, filename = generate_and_save(project_id, text, mode if mode in ("normal", "flow", "arch") else "normal")
        except ArkImageError as exc:
            raise HarnessError(str(exc)) from exc
        db, draft, _flag = self._open()
        try:
            image_id = self._save_image(db, draft, storage_path, mode=mode, prompt=text, filename=filename, from_path=True)
        finally:
            db.close()
        label = (caption or text).strip()[:40]
        self._place_figure(target, image_id, label, after_heading, state)
        return f"已生成示意图并写入章节，图 id={image_id}，图注：{label}"

    def insert_image(self, image_id: str, chapter_id: str = "", after_heading: str = "", caption: str = "") -> str:
        """把本项目已有的图片（上传、知识库、生成）插入章节。"""
        from ..models import WriterImage

        match = re.search(r"/writer-images/([^/\s)]+)/file", image_id or "")
        raw = (match.group(1) if match else (image_id or "")).strip()
        if not raw:
            raise HarnessError("缺少图片 id")
        target = self.chapter_text(chapter_id)[0]
        db, draft, _flag = self._open()
        try:
            img = db.get(WriterImage, raw)
            if img is None or img.project_id != draft.project_id:
                raise HarnessError("图片不存在或不属于本项目")
            label = (caption or img.prompt or img.filename or "插图").strip()[:40]
        finally:
            db.close()
        self._place_figure(target, raw, label, after_heading, None)
        return f"已把图片插入章节 {target}，图注：{label}"

    # ---- 排版 ----

    def set_layout(self, patch: dict) -> str:
        from .writer_layout import describe_layout, merge_layout

        if not isinstance(patch, dict) or not patch:
            raise HarnessError("没有要修改的排版项")
        db, draft, flag_modified = self._open(True)
        try:
            settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
            try:
                merged = merge_layout(settings.get("layout") if isinstance(settings.get("layout"), dict) else None, patch)
            except ValueError as exc:
                raise HarnessError(str(exc)) from exc
            settings["layout"] = merged
            draft.settings_json = settings
            flag_modified(draft, "settings_json")
            db.commit()
            self.edits.append({"layout": merged})
            return "已更新 Word 排版：\n" + describe_layout(merged)
        finally:
            db.close()

    def persist_chapter(
        self, chapter_id: str, content: str, *, status: str, ai_round: bool, part: str | None = None
    ) -> None:
        """批量并发写章节正文：锁草稿行，读最新数据再写，不会覆盖别的章节。"""
        db, draft, flag_modified = self._open(True)
        try:
            contents = dict(draft.chapter_contents_json or {})
            contents[chapter_id] = content
            draft.chapter_contents_json = contents
            flag_modified(draft, "chapter_contents_json")
            outline = [dict(item) for item in (draft.outline_json or [])]
            for item in outline:
                if item.get("id") == chapter_id:
                    item["status"] = status
                    item["words"] = len(content.replace(" ", "").replace("\n", ""))
                    if part:
                        item["part"] = part
                    if ai_round:
                        item["aiRounds"] = (item.get("aiRounds") or 0) + 1
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
        finally:
            db.close()

    def set_chapter_status(self, chapter_id: str, status: str) -> None:
        db, draft, flag_modified = self._open(True)
        try:
            outline = [dict(item) for item in (draft.outline_json or [])]
            for item in outline:
                if item.get("id") == chapter_id:
                    item["status"] = status
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
        finally:
            db.close()


def _format_knowledge_hits(hits: list[dict], limit: int = 8000) -> str:
    if not hits:
        return "知识库里没有命中的内容。"
    parts: list[str] = []
    used = 0
    for hit in hits:
        text = (hit.get("text") or "").strip()
        if not text:
            continue
        block = f"[doc_id={hit.get('docId')} 《{hit.get('docTitle') or ''}》/{hit.get('heading') or ''}]\n{text[:1800]}"
        if used + len(block) > limit:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts) if parts else "知识库里没有命中的内容。"


def insert_figures_into_markdown(markdown: str, figures: list[dict]) -> str:
    """把图和图注插进正文：优先放在指定标题所在小节的末尾，找不到就放全文最后。"""
    lines = (markdown or "").replace("\r\n", "\n").split("\n")
    for fig in figures:
        block = ["", fig["markdown"], "", f">>> 图：{fig.get('caption') or ''}".rstrip("：").rstrip(), ""]
        wanted = re.sub(r"\s+", "", str(fig.get("afterHeading") or ""))
        at = len(lines)
        if wanted:
            for i, raw in enumerate(lines):
                match = _HEADING.match(raw.strip())
                if not match:
                    continue
                if wanted in re.sub(r"\s+", "", match.group(2)):
                    level = len(match.group(1))
                    at = len(lines)
                    for j in range(i + 1, len(lines)):
                        nxt = _HEADING.match(lines[j].strip())
                        if nxt and len(nxt.group(1)) <= level:
                            at = j
                            break
                    break
        while at > 0 and not lines[at - 1].strip():
            at -= 1
        lines[at:at] = block
    return "\n".join(lines).strip() + "\n"


UPLOAD_TEXT_MAX = 20000
CHAT_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CHAT_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def is_chat_image(filename: str) -> bool:
    return os.path.splitext(filename or "")[1].lower() in CHAT_IMAGE_EXTS


def prepare_uploads(uploads: list[dict] | None) -> list[dict]:
    """同一批附件里重名时加上序号，避免读错文件。"""
    seen: dict[str, int] = {}
    ready: list[dict] = []
    for item in uploads or []:
        if not isinstance(item, dict):
            continue
        name = os.path.basename(str(item.get("filename") or "附件")).replace("\\", "/").strip() or "附件"
        count = seen.get(name, 0)
        seen[name] = count + 1
        if count:
            stem, ext = os.path.splitext(name)
            name = f"{stem}-{count + 1}{ext}"
        ready.append({"filename": name, "storagePath": str(item.get("storagePath") or "")})
    return ready


def _image_block(mime: str, data: bytes):
    """AgentScope 2.0 没有 ImageBlock，图片统一用 DataBlock + Base64Source。"""
    import base64

    from agentscope.message import Base64Source, DataBlock

    b64 = base64.b64encode(data).decode("ascii")
    return DataBlock(source=Base64Source(data=b64, media_type=mime))


def chat_user_content(text: str, uploads: list[dict] | None = None):
    """文本附件仍走 read_upload；图片随本轮 UserMsg 直接送给模型。"""
    images = [item for item in prepare_uploads(uploads) if is_chat_image(item["filename"])]
    if not images:
        return text
    from agentscope.message import TextBlock

    blocks: list = [TextBlock(text=text)]
    from .. import storage

    for item in images:
        try:
            data = storage.get_bytes(item["storagePath"])
        except Exception:  # noqa: BLE001
            continue
        if not data:
            continue
        ext = os.path.splitext(item["filename"])[1].lower()
        blocks.append(_image_block(CHAT_IMAGE_MIME.get(ext, "image/png"), data))
    return blocks if len(blocks) > 1 else text


def read_upload_text(uploads: list[dict], filename: str = "") -> str:
    """只读本次消息带上的附件。找不到时返回说明，不抛给模型。"""
    items = prepare_uploads(uploads)
    target = (filename or "").strip()
    if not target:
        if not items:
            return "本次没有上传附件。"
        lines = []
        for item in items:
            mark = "（图片，已随消息送给模型）" if is_chat_image(item["filename"]) else ""
            lines.append(f"- {item['filename']}{mark}")
        return "本次附件：\n" + "\n".join(lines)
    match = next((item for item in items if item["filename"] == target), None)
    if match is None:
        return "没有这个附件"
    if is_chat_image(target):
        return "这是图片附件，已随本轮对话直接送给模型查看。请根据画面内容回答，不要当文本文件打开。"
    from .. import storage
    from .docx_extract import extract_full_text

    try:
        with storage.as_local(match["storagePath"]) as local:
            lower = target.lower()
            if lower.endswith((".txt", ".md")):
                raw = Path(local).read_bytes()
                text = raw.decode("utf-8", errors="ignore")
                if not text.strip():
                    text = raw.decode("gbk", errors="ignore")
            else:
                text = extract_full_text(local)
    except Exception as exc:  # noqa: BLE001 —— 附件打不开时告诉模型，不要中断整段对话
        return f"附件无法阅读：{exc}"
    text = (text or "").strip()
    if not text:
        return "附件里没有可读文字"
    if len(text) > UPLOAD_TEXT_MAX:
        return text[:UPLOAD_TEXT_MAX] + "\n……（已截断）"
    return text


def _text_chunk(text: str):
    """成功结果必须显式标 SUCCESS，默认的 RUNNING 会让引擎认为工具还没结束。
    失败不要在这里返回，直接抛异常，Toolkit 会转成 ERROR 并带上原因。"""
    from agentscope.message import TextBlock, ToolResultState
    from agentscope.tool import ToolChunk

    return ToolChunk(content=[TextBlock(text=text)], state=ToolResultState.SUCCESS)


async def _offload(func, *args):
    """同步的子进程、HTTP、文件调用放进线程，别堵住事件循环。"""
    return await asyncio.to_thread(func, *args)


def _job_tools(workdir: Path, project_id: str, draft_id: str = "") -> list:
    """目录/章节生成：只读招标摘录 + Skill 脚本，不上网、不导出。draft_id 给出时，应答结论同时落库。"""
    from agentscope.permission import PermissionBehavior, PermissionContext, PermissionDecision
    from agentscope.tool import ToolBase

    from .writer_tool_runtime import (
        match_product_text,
        match_qualification_text,
        persist_response,
        read_form_registry_text,
        read_ledger_text,
        read_tender_text,
        record_response_text,
        run_skill_script,
    )

    class _ReadOnly(ToolBase):
        is_read_only = True
        is_concurrency_safe = True

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只读项目资料")

    class ReadLedger(_ReadOnly):
        name = "read_ledger"
        description = (
            "读取需求台账：每条应答要求的编号、类型（资格性/实质性/评分性/格式/应答）、是否必须（★、否决、必须）、"
            "招标书出处和逐字原文。query 可填编号（如 T5）或关键词，不填则分页列出。"
        )
        input_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}, "page": {"type": "integer"}},
            "required": [],
        }

        async def call(self, query: str = "", page: int = 1) -> object:
            return _text_chunk(await _offload(read_ledger_text, project_id, query, page))

    class ReadFormRegistry(_ReadOnly):
        name = "read_form_registry"
        description = (
            "列出招标书附录里已给出格式的文件（承诺书、授权书、偏离表、报价表、团队表等）。"
            "给 index 时返回该份格式的原文。这些章节由系统原样拷贝，不要重写。"
        )
        input_schema = {"type": "object", "properties": {"index": {"type": "integer"}}, "required": []}

        async def call(self, index: int = -1) -> object:
            return _text_chunk(await _offload(read_form_registry_text, project_id, index))

    class MatchStandardProduct(_ReadOnly):
        name = "match_standard_product"
        description = (
            "查询产品库里与一条招标要求最接近的标准功能点和应标原文摘要。有对应功能时必须以库内原文为准，"
            "没有时才自己撰写，并如实说明没有标品支撑。"
        )
        input_schema = {
            "type": "object",
            "properties": {"requirement": {"type": "string"}},
            "required": ["requirement"],
        }

        async def call(self, requirement: str) -> object:
            return _text_chunk(await _offload(match_product_text, project_id, requirement))

    class MatchQualification(_ReadOnly):
        name = "match_qualification"
        description = (
            "查询企业资质证照库里是否有满足一条招标要求的材料（证照、同类项目业绩、拟派人员等，只含已入库条目）。"
            "返回命中的条目和库内缺失的数量。库里没有的材料不得编造，须在正文空出并用红字提示用户补充。"
        )
        input_schema = {
            "type": "object",
            "properties": {"requirement": {"type": "string"}},
            "required": ["requirement"],
        }

        async def call(self, requirement: str) -> object:
            return _text_chunk(await _offload(match_qualification_text, project_id, requirement))

    class RecordResponse(ToolBase):
        name = "record_response"
        description = (
            "记录某条台账要求的应答结论（满足/部分满足/不满足）、实现方式和偏离说明，"
            "系统据此核对偏离表和追溯矩阵。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "台账编号，如 T5"},
                "status": {"type": "string", "description": "满足 / 部分满足 / 不满足"},
                "how": {"type": "string"},
                "deviation": {"type": "string"},
            },
            "required": ["item_id", "status"],
        }
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只写本任务工作区")

        async def call(self, item_id: str, status: str, how: str = "", deviation: str = "") -> object:
            text = await _offload(record_response_text, workdir, item_id, status, how, deviation)
            if draft_id and text.startswith("已记录"):
                await _offload(persist_response, draft_id, item_id, status, how, deviation)
            return _text_chunk(text)

    class ReadTender(ToolBase):
        name = "read_tender"
        description = (
            "阅读招标书材料。section=original 时读取招标书原文全文（按约 8000 字/页分页，"
            "不给 query 时按 page 翻页通读，必须逐页调用直到读完，不能只读一页就下结论；"
            "给 query 时在原文里按行检索命中）。section 还可以是 tech、business、format（已抽出的辅助摘要）或 all。"
            "不能打开原始招标包路径。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "original / tech / business / format / all"},
                "query": {"type": "string", "description": "检索词，可留空"},
                "page": {"type": "integer", "description": "section=original 且不给 query 时翻页，从 1 开始"},
            },
            "required": [],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只读招标摘录")

        async def call(self, section: str = "all", query: str = "", page: int = 1) -> object:
            return _text_chunk(await _offload(read_tender_text, workdir, project_id, section, query, page))

    class RunSkillScript(ToolBase):
        name = "run_skill_script"
        description = (
            "运行已登记 Skill 目录 scripts/ 下的 Python 脚本。只传 skill 名和脚本文件名，"
            "例如 skill=bid-outline、script=lint_outline.py。不能执行其它路径。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "script": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["skill", "script"],
        }
        is_read_only = True
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只跑登记的 Skill 脚本")

        async def call(self, skill: str, script: str, args: list[str] | None = None) -> object:
            return _text_chunk(await _offload(run_skill_script, workdir, skill, script, args or []))

    return [
        ReadTender(),
        ReadLedger(),
        ReadFormRegistry(),
        MatchStandardProduct(),
        MatchQualification(),
        RecordResponse(),
        RunSkillScript(),
    ]


def _extra_tools(
    binding: DraftBinding,
    *,
    state: dict | None,
    chat: bool,
    allow_illustration: bool = True,
) -> list:
    """知识库检索、配图、排版。state 不为空表示章节生成任务：图先登记，正文验收后统一插入。"""
    from agentscope.permission import PermissionBehavior, PermissionContext, PermissionDecision
    from agentscope.tool import ToolBase

    from .writer_diagram import DIAGRAM_KINDS

    class _Allowed(ToolBase):
        allow_note = "只访问绑定草稿"

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message=self.allow_note)

    kinds = "、".join(f"{key}={meta[0]}" for key, meta in DIAGRAM_KINDS.items())

    class SearchKnowledge(_Allowed):
        name = "search_knowledge"
        description = (
            "在本草稿已选中的知识库里按关键词检索，返回带文档名和标题的片段。"
            "写技术章前后需要真实案例、方案、参数时调用；知识库没有的内容不要编造。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词，例如章节标题加关键点"},
                "top_k": {"type": "integer", "description": "命中标题数，1 到 6，默认 4"},
            },
            "required": ["query"],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def call(self, query: str, top_k: int = 4) -> object:
            return _text_chunk(await _offload(binding.search_knowledge, query, top_k))

    class ReadKnowledgeSection(_Allowed):
        name = "read_knowledge_section"
        description = "按 doc_id 和标题读取知识库某一节及其下级的完整内容。doc_id 来自 search_knowledge 的结果。"
        input_schema = {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}, "heading": {"type": "string"}},
            "required": ["doc_id", "heading"],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def call(self, doc_id: str, heading: str) -> object:
            return _text_chunk(await _offload(binding.read_knowledge_section, doc_id, heading))

    class MakeDiagram(_Allowed):
        name = "make_diagram"
        description = (
            "按本章正文绘制中文结构图（本地绘制，不收费，首选）。类型：" + kinds + "。"
            "after_heading 填要放在哪个小节标题之后，空则放章末。每章最多 2 张，已有图不要重复生成。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "结构图类型 key"},
                "chapter_id": {"type": "string", "description": "章节 id，章节任务里可留空"},
                "after_heading": {"type": "string"},
                "caption": {"type": "string", "description": "图注，不超过 20 字"},
            },
            "required": ["kind"],
        }
        is_read_only = False
        is_concurrency_safe = False
        allow_note = "只给绑定草稿配图"

        async def call(self, kind: str, chapter_id: str = "", after_heading: str = "", caption: str = "") -> object:
            return _text_chunk(await _offload(binding.make_diagram, kind, chapter_id, after_heading, caption, state))

    class GenerateIllustration(_Allowed):
        name = "generate_illustration"
        description = (
            "用文生图生成示意图（收费，仅在章节明确需要示意图、效果图，或用户要求时使用；"
            "架构、流程、组织类请用 make_diagram）。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "画面描述，中文"},
                "mode": {"type": "string", "description": "normal / flow / arch"},
                "chapter_id": {"type": "string"},
                "after_heading": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["prompt"],
        }
        is_read_only = False
        is_concurrency_safe = False
        allow_note = "只给绑定草稿配图"

        async def call(
            self, prompt: str, mode: str = "normal", chapter_id: str = "", after_heading: str = "", caption: str = ""
        ) -> object:
            return _text_chunk(
                await _offload(binding.make_illustration, prompt, mode, chapter_id, after_heading, caption, state)
            )

    class InsertImage(_Allowed):
        name = "insert_image"
        description = "把本项目已有的图片（上传、知识库或之前生成的）按 id 插入章节，并加图注。"
        input_schema = {
            "type": "object",
            "properties": {
                "image_id": {"type": "string", "description": "图片 id，或 /api/writer-images/{id}/file 链接"},
                "chapter_id": {"type": "string"},
                "after_heading": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["image_id"],
        }
        is_read_only = False
        is_concurrency_safe = False
        allow_note = "只改绑定草稿"

        async def call(self, image_id: str, chapter_id: str = "", after_heading: str = "", caption: str = "") -> object:
            return _text_chunk(await _offload(binding.insert_image, image_id, chapter_id, after_heading, caption))

    class SetLayout(_Allowed):
        name = "set_layout"
        description = (
            "修改 Word 导出排版。patch 是要改的字段，只写要改的。可用字段：preset(模板名)、bodyFont、bodyLatinFont、"
            "bodySizePt、fontSize(小四等)、lineSpacingMul、paragraphBefore、paragraphAfter、indentChars、justify、"
            "margins{top,bottom,left,right}(cm)、headings{h1,h2,h3:{font,sizePt,bold,align,spaceBefore,spaceAfter}}、"
            "header(页眉文字)、pageNumber(none/simple/full)、orientation、cover{enabled,title,subtitle,company,date}、"
            "toc{enabled,levels}、table{headerFill,fontSizePt}、caption{font,sizePt}。"
        )
        input_schema = {
            "type": "object",
            "properties": {"patch": {"type": "object", "description": "要修改的排版字段"}},
            "required": ["patch"],
        }
        is_read_only = False
        is_concurrency_safe = False
        allow_note = "只改绑定草稿的排版"

        async def call(self, patch: dict) -> object:
            return _text_chunk(await _offload(binding.set_layout, patch))

    tools: list = [SearchKnowledge(), ReadKnowledgeSection(), MakeDiagram()]
    if allow_illustration:
        tools.append(GenerateIllustration())
    if chat:
        tools.extend([InsertImage(), SetLayout()])
    return tools


def _chat_tools(
    binding: DraftBinding, workdir: Path, project_id: str, uploads: list[dict] | None = None
) -> list:
    from agentscope.permission import PermissionBehavior, PermissionContext, PermissionDecision
    from agentscope.tool import ToolBase

    from .writer_tool_runtime import collect_material, export_bound_draft

    class ReadChapter(ToolBase):
        name = "read_chapter"
        description = "读取当前草稿的目录，或某一章的标题、编写思路和正文。chapter_id 可空，空则只列目录。"
        input_schema = {
            "type": "object",
            "properties": {"chapter_id": {"type": "string", "description": "章节 id，可留空"}},
            "required": [],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只读当前草稿")

        async def call(self, chapter_id: str = "") -> object:
            return _text_chunk(binding.read_chapter(chapter_id))

    class ReplaceChapter(ToolBase):
        name = "replace_chapter"
        description = "用完整 Markdown 替换某一技术章正文。不能用于报价、固定格式件和商务标。"
        input_schema = {
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string"},
                "content": {"type": "string", "description": "替换后的完整正文"},
            },
            "required": ["content"],
        }
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只写绑定草稿")

        async def call(self, content: str, chapter_id: str = "") -> object:
            return _text_chunk(binding.replace_chapter(chapter_id, content))

    class UpdateOutline(ToolBase):
        name = "update_outline"
        description = "修改已有目录节点的标题或编写思路。用户要求改目录名或思路时必须调用，不要只给建议。"
        input_schema = {
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string"},
                "title": {"type": "string"},
                "idea": {"type": "string"},
            },
            "required": [],
        }
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只改绑定草稿的目录")

        async def call(self, chapter_id: str = "", title: str = "", idea: str = "") -> object:
            return _text_chunk(binding.update_outline(chapter_id, title, idea))

    class AddOutlineNode(ToolBase):
        name = "add_outline_node"
        description = (
            "新增目录节点。title 加一个；titles 可一次加多个同级。parent_id 为空则顶层；"
            "after_id 表示插在该节点及其子树之后。用户要求增加章节时必须调用，不要让用户自己点目录树。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "titles": {"type": "array", "items": {"type": "string"}},
                "parent_id": {"type": "string", "description": "父节点 id，空为顶层"},
                "after_id": {"type": "string", "description": "插在此节点后面"},
                "idea": {"type": "string"},
            },
            "required": [],
        }
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只改绑定草稿的目录")

        async def call(
            self,
            title: str = "",
            titles: list[str] | None = None,
            parent_id: str = "",
            after_id: str = "",
            idea: str = "",
        ) -> object:
            return _text_chunk(binding.add_outline_node(title, titles, parent_id, after_id, idea))

    class DeleteOutlineNode(ToolBase):
        name = "delete_outline_node"
        description = (
            "删除目录节点及其全部下级，并重新编号。chapter_id 可逗号分隔多个。"
            "用户要求删投标函、授权委托、报价表等格式件或商务节点时必须调用，允许删除，不要让用户自己在左侧删。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "一个或多个章节 id，逗号分隔"},
                "chapter_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        }
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只改绑定草稿的目录")

        async def call(self, chapter_id: str = "", chapter_ids: list[str] | None = None) -> object:
            return _text_chunk(binding.delete_outline_node(chapter_id, chapter_ids))

    class ReadUpload(ToolBase):
        name = "read_upload"
        description = "读取本次对话用户上传的 Word/PDF/TXT/Markdown。filename 为空时只列出文件名。图片已随消息送给模型，不要当文本打开。不能读取其它路径。"
        input_schema = {
            "type": "object",
            "properties": {"filename": {"type": "string", "description": "附件文件名，可留空"}},
            "required": [],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="只读本次附件")

        async def call(self, filename: str = "") -> object:
            return _text_chunk(await _offload(read_upload_text, uploads or [], filename))

    class ExportDraftDocx(ToolBase):
        name = "export_draft_docx"
        description = "把当前草稿导出为 Word 投标书。不要手写 docx 文件。"
        input_schema = {"type": "object", "properties": {}, "required": []}
        is_read_only = False
        is_concurrency_safe = False

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="导出绑定草稿")

        async def call(self) -> object:
            return _text_chunk(await _offload(export_bound_draft, binding.user_id, binding.draft_id))

    class CollectMaterial(ToolBase):
        name = "collect_material"
        description = (
            "用受限浏览器搜集标书素材。action=search 需 query；action=fetch 需白名单 url；"
            "action=list 列出已保存文件；action=read 阅读文件名。浏览器未启用时会说明。"
        )
        input_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "query": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": [],
        }
        is_read_only = True
        is_concurrency_safe = True

        async def check_permissions(self, tool_input: dict, context: PermissionContext) -> PermissionDecision:
            return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="白名单取材")

        async def call(self, action: str = "list", query: str = "", url: str = "") -> object:
            return _text_chunk(await _offload(collect_material, workdir, action, query, url))

    return [
        ReadChapter(),
        ReplaceChapter(),
        UpdateOutline(),
        AddOutlineNode(),
        DeleteOutlineNode(),
        ReadUpload(),
        ExportDraftDocx(),
        CollectMaterial(),
        *_job_tools(workdir, project_id, binding.draft_id),
        *_extra_tools(binding, state=None, chat=True),
    ]


def run_chat(
    *,
    user_id: str,
    project_id: str,
    draft_id: str,
    job_id: str,
    model_id: str | None,
    chapter_id: str | None,
    history: list[dict],
    message: str,
    uploads: list[dict] | None = None,
    on_trace=None,
) -> dict:
    """在该用户自己的 chat 工作区里对话。工具写回的是同一份项目草稿。"""
    workdir = scoped_workspace(user_id, project_id, draft_id, "chat")
    binding = DraftBinding(user_id, draft_id, chapter_id)
    from .writer_tool_runtime import (
        load_original_tender_text,
        load_tender_extracts,
        materialize_full_tender_text,
        materialize_outline_snapshot,
        materialize_tender_extracts,
    )

    materialize_tender_extracts(workdir, load_tender_extracts(project_id))
    materialize_full_tender_text(workdir, load_original_tender_text(project_id))
    from ..models import Project
    from .engineering_writer import TRACK_WATER, facts_brief, writer_track

    db, draft, _flag = binding._open()
    track = "software"
    try:
        materialize_outline_snapshot(workdir, draft.outline_json)
        project = db.get(Project, draft.project_id)
        track = writer_track(
            project.category if project else "",
            project.specialty if project else "",
            draft.doc_kind,
        )
        if track == TRACK_WATER:
            settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
            _write_text(workdir / "water_facts.txt", facts_brief(settings.get("engFacts") or {}, specialty="水利"))
    finally:
        db.close()
    attached = prepare_uploads(uploads)
    transcript = []
    for item in history[-12:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            transcript.append(f"{role}: {content[:2000]}")
    transcript.append(f"user: {message.strip()[:4000]}")
    _write_text(workdir / "transcript.txt", "\n".join(transcript)[-20000:])
    focus = f"当前章节 id：{chapter_id}" if chapter_id else "用户没有指定章节，修改前先读取目录。"
    pictures = [item for item in attached if is_chat_image(item["filename"])]
    documents = [item for item in attached if not is_chat_image(item["filename"])]
    if pictures:
        names = "\n".join(f"- {item['filename']}" for item in pictures)
        focus += "\n本次消息已附上图片，请直接看图回答：\n" + names
    if documents:
        names = "\n".join(f"- {item['filename']}" for item in documents)
        focus += "\n本次上传的文档，需要内容时调用 read_upload：\n" + names
    prompt_text = focus + "\n\n" + "\n".join(transcript)
    skill_line = (
        "先用 Skill 查看器阅读 water-bid，再看 bid-export。数字以工作区 water_facts.txt 为准，不要编造。"
        "改正文必须 replace_chapter；被拒绝时按返回原因改正文再提交，不要调用 run_skill_script 做校核。"
        if track == TRACK_WATER
        else "先用 Skill 查看器阅读 bid-outline / bid-chapter / bid-research / bid-export，再按说明书调用工具或 run_skill_script。"
    )

    async def _run() -> tuple[str, list[dict]]:
        agent = _make_agent(
            "writer-chat",
            "你是慧投标撰写助手。可以读取当前草稿和招标摘录，修改技术章正文，修改目录，导出 Word，"
            "并在用户要求时用浏览器搜集白名单素材。" + skill_line +
            "用户上传了 Word/PDF/TXT/Markdown 时，先调用 read_upload 阅读。"
            "用户发送了图片时，直接根据画面内容回答，不要把图片当文本文件打开。"
            "修改目录时不要把评标办法、合同条款、投标人须知、形式评审写成章节。"
            "用户要求新增、删除或修改目录时，必须先 read_chapter 核对 id，再调用 "
            "add_outline_node / delete_outline_node / update_outline 写回。"
            "不要让用户自己在左侧目录树增删，也不要只给操作建议。"
            "删除投标函、授权委托、报价表、偏差表等格式件或商务节点是允许的；"
            "不要把这些章节改写成技术方案。"
            "用户要求改正文时必须调用 replace_chapter 写回。"
            "需要知识库里的方案、案例、参数时先 search_knowledge，必要时 read_knowledge_section，再改写；知识库没有的不要编。"
            "用户要求配图或架构图时：架构、流程、组织、部署类优先 make_diagram（本地绘制不收费），"
            "只有明确要示意图或效果图才 generate_illustration；已有图片用 insert_image。每章最多几张图，不要重复生成。"
            "用户要求改字体、字号、行距、页边距、页眉页码、封面、目录、标题样式时，调用 set_layout 写进排版设置，"
            "再用 export_draft_docx 导出；字号可用 fontSize（小四等）或 bodySizePt。"
            "导出 Word 必须调用 export_draft_docx，禁止手写 docx。"
            "不要编造未在正文或产品库中出现的资质和参数。",
            model_id,
            workdir,
            f"{user_id}-{draft_id}-chat",
            _chat_tools(binding, workdir, project_id, attached),
            20,
            stream=True,
            track=track,
        )
        return await _reply_with_trace(
            agent,
            chat_user_content(prompt_text, attached),
            on_trace,
            model_id or "",
        )

    reply, trace = asyncio.run(_run())
    return {"reply": reply, "edits": list(binding.edits), "engine": "AgentScope", "trace": trace}
