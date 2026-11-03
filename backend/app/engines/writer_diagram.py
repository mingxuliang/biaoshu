"""按章节正文抽出结构，再用中文字体画成结构图。

功能架构、技术架构、部署拓扑和人员组织不交给文生图，避免中文标签发糊。
"""

from __future__ import annotations

import json
import os
import re

from .llm import LlmError, chat_complete

try:
    import fitz
except ImportError:  # 宿主未装 PyMuPDF 时仍可做结构抽取；绘制在服务镜像里执行
    fitz = None  # type: ignore[assignment]

class DiagramError(Exception):
    """结构图无法生成（缺正文、模型失败或没有中文字体）。"""


DIAGRAM_KINDS: dict[str, tuple[str, str, str]] = {
    "function": ("功能架构", "arch", "layers"),
    "technical": ("技术架构", "arch", "layers"),
    "deployment": ("部署拓扑", "arch", "layers"),
    "organization": ("人员组织", "arch", "tree"),
    "construction": ("施工组织", "flow", "flow"),
    "schedule": ("进度计划", "flow", "flow"),
    "quality": ("质量管理", "flow", "flow"),
    "safety": ("安全应急", "flow", "flow"),
    "inspection": ("报验审批", "flow", "flow"),
}

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)

_SYSTEM = """你是投标文件结构图抽取器。只根据用户给出的本章正文抽取，禁止编造正文中没有的系统、岗位、设备或流程步骤。
必须返回 json 对象，不要使用 markdown。
格式：
{"title":"图名","nodes":[{"id":"n1","label":"不超过12字","note":"","layer":0,"parent":""}],"edges":[{"from":"n1","to":"n2","label":""}]}
规则：
- 功能架构、技术架构、部署拓扑：用 layer 从上到下分层，0 为最上层，parent 留空；
- 人员组织：用 parent 表示直接上级，根节点 parent 为空，不要画成技术分层；
- 流程图：节点按先后放在 layer 0，并用 edges 按顺序连接；
- 节点最多 12 个，label 不超过 12 个字。
"""


def find_cjk_font() -> str:
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    raise DiagramError("服务器缺少中文字体，无法绘制结构图")


def chapter_diagram_source(markdown: str, idea: str = "") -> tuple[str, str]:
    """返回 (送给模型的正文, 提示)。没有解决方案时改用编写思路。"""
    md = markdown or ""
    match = re.search(r"^##\s*解决方案\s*\n([\s\S]+)", md, re.M)
    if match and match.group(1).strip():
        return _plain(match.group(1))[:8000], ""
    plain = _plain(md)
    if len(plain) >= 80 and "原始需求" not in plain[:20]:
        return plain[:8000], ""
    idea_text = (idea or "").strip()
    if idea_text:
        return idea_text[:4000], "本章还没有解决方案正文，已按编写思路出图。建议先生成正文后再出图。"
    raise DiagramError("请先生成本章正文，或填写编写思路后再出结构图")


def _plain(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.M)
    return cleaned.strip()


def _clip(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", "", text or "")
    return compact[:limit]


def normalize_diagram(data: dict, kind: str) -> dict:
    if kind not in DIAGRAM_KINDS:
        raise DiagramError("不支持的结构图类型")
    label, mode, layout = DIAGRAM_KINDS[kind]
    if not isinstance(data, dict):
        raise DiagramError("未能从正文抽出结构图，请补充本章解决方案后再试")
    raw_nodes: list[dict] = []
    if isinstance(data.get("nodes"), list):
        raw_nodes = [node for node in data["nodes"] if isinstance(node, dict)]
    elif isinstance(data.get("layers"), list):
        for index, layer in enumerate(data["layers"]):
            if not isinstance(layer, dict):
                continue
            for node in layer.get("nodes") or []:
                if isinstance(node, dict):
                    raw_nodes.append({**node, "layer": node.get("layer", index), "layerName": layer.get("name") or ""})
    nodes: list[dict] = []
    seen: set[str] = set()
    for index, node in enumerate(raw_nodes[:12]):
        node_id = str(node.get("id") or f"n{index + 1}")
        if node_id in seen:
            node_id = f"{node_id}-{index}"
        seen.add(node_id)
        try:
            layer = int(node.get("layer") or 0)
        except (TypeError, ValueError):
            layer = 0
        nodes.append(
            {
                "id": node_id,
                "label": _clip(str(node.get("label") or node.get("name") or ""), 12) or "未命名",
                "note": _clip(str(node.get("note") or ""), 16),
                "layer": max(0, min(layer, 5)),
                "layerName": _clip(str(node.get("layerName") or ""), 8),
                "parent": str(node.get("parent") or node.get("parentId") or ""),
            }
        )
    if not nodes:
        raise DiagramError("未能从正文抽出结构图，请补充本章解决方案后再试")
    valid = {node["id"] for node in nodes}
    edges: list[dict] = []
    for edge in (data.get("edges") or [])[:24]:
        if not isinstance(edge, dict):
            continue
        src, dst = str(edge.get("from") or ""), str(edge.get("to") or "")
        if src in valid and dst in valid and src != dst:
            edges.append({"from": src, "to": dst, "label": _clip(str(edge.get("label") or ""), 8)})
    if layout == "flow" and not edges and len(nodes) > 1:
        for left, right in zip(nodes, nodes[1:]):
            edges.append({"from": left["id"], "to": right["id"], "label": ""})
    if layout == "tree":
        for node in nodes:
            if node["parent"] not in valid or node["parent"] == node["id"]:
                node["parent"] = ""
        if not any(node["parent"] for node in nodes) and len(nodes) > 1:
            root_id = nodes[0]["id"]
            for node in nodes[1:]:
                node["parent"] = root_id
    title = _clip(str(data.get("title") or label), 20) or label
    return {"title": title, "layout": layout, "kindLabel": label, "mode": mode, "nodes": nodes, "edges": edges}


def _parse_json(text: str) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise DiagramError("未能从正文抽出结构图，请补充本章解决方案后再试")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DiagramError("未能从正文抽出结构图，请补充本章解决方案后再试") from exc
    if not isinstance(data, dict):
        raise DiagramError("未能从正文抽出结构图，请补充本章解决方案后再试")
    return data


def extract_diagram(model_id: str | None, kind: str, chapter_title: str, source: str) -> dict:
    label = DIAGRAM_KINDS[kind][0]
    try:
        text = chat_complete(
            model_id=model_id,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"图种：{label}\n章节：{chapter_title or label}\n正文：\n{source}"},
            ],
            temperature=0.1,
            timeout=90,
            max_tokens=2000,
        )
    except LlmError as exc:
        raise DiagramError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 —— 网络失败要变成可读错误，而不是任务崩溃
        raise DiagramError(f"抽取结构图失败（{exc.__class__.__name__}）") from exc
    return normalize_diagram(_parse_json(text), kind)


def create_diagram_png(
    model_id: str | None,
    kind: str,
    chapter_title: str,
    markdown: str,
    idea: str = "",
) -> tuple[bytes, str, str, str]:
    if kind not in DIAGRAM_KINDS:
        raise DiagramError("不支持的结构图类型")
    source, notice = chapter_diagram_source(markdown, idea)
    spec = extract_diagram(model_id, kind, chapter_title, source)
    return render_diagram_png(spec), spec["mode"], spec["title"], notice


def render_diagram_png(spec: dict) -> bytes:
    if fitz is None:
        raise DiagramError("未安装 PyMuPDF，无法绘制结构图")
    font = find_cjk_font()
    layout = spec.get("layout")
    if layout == "tree":
        return _render_tree(spec, font)
    if layout == "flow":
        return _render_flow(spec, font)
    return _render_layers(spec, font)


def _text(page, rect: fitz.Rect, text: str, font: str, size: float, color: tuple[float, float, float]) -> None:
    if not text:
        return
    page.insert_textbox(rect, text, fontfile=font, fontsize=size, color=color, align=fitz.TEXT_ALIGN_CENTER)


def _box(page, rect: fitz.Rect, font: str, label: str, note: str = "") -> None:
    page.draw_rect(rect, color=(0.15, 0.35, 0.62), fill=(0.93, 0.96, 0.99), width=1.2)
    _text(page, fitz.Rect(rect.x0 + 4, rect.y0 + 8, rect.x1 - 4, rect.y0 + 30), label, font, 12, (0.1, 0.16, 0.28))
    if note:
        _text(page, fitz.Rect(rect.x0 + 4, rect.y0 + 30, rect.x1 - 4, rect.y1 - 4), note, font, 9, (0.35, 0.4, 0.48))


def _new_page(width: float, height: float, title: str, font: str):
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
    _text(page, fitz.Rect(24, 12, width - 24, 42), title, font, 16, (0.08, 0.16, 0.32))
    return doc, page


def _png(doc) -> bytes:
    page = doc[0]
    try:
        return page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    finally:
        doc.close()


def _render_layers(spec: dict, font: str) -> bytes:
    groups: dict[int, list[dict]] = {}
    for node in spec["nodes"]:
        groups.setdefault(int(node["layer"]), []).append(node)
    levels = [groups[key] for key in sorted(groups)]
    width = 860
    height = 64 + len(levels) * 118
    doc, page = _new_page(width, height, spec["title"], font)
    centers: dict[str, tuple[float, float]] = {}
    for row, nodes in enumerate(levels):
        top = 56 + row * 118
        gap = (width - 48) / max(len(nodes), 1)
        box_w = min(150, gap - 16)
        for col, node in enumerate(nodes):
            left = 24 + col * gap + (gap - box_w) / 2
            rect = fitz.Rect(left, top, left + box_w, top + 72)
            _box(page, rect, font, node["label"], node["note"])
            centers[node["id"]] = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
        layer_name = next((node["layerName"] for node in nodes if node["layerName"]), "")
        if layer_name:
            _text(page, fitz.Rect(24, top - 16, 180, top), layer_name, font, 9, (0.4, 0.45, 0.55))
    _draw_edges(page, spec["edges"], centers)
    return _png(doc)


def _render_flow(spec: dict, font: str) -> bytes:
    nodes = spec["nodes"]
    width = max(720, 48 + len(nodes) * 170)
    doc, page = _new_page(width, 220, spec["title"], font)
    centers: dict[str, tuple[float, float]] = {}
    box_w = 140
    for index, node in enumerate(nodes):
        left = 24 + index * 170
        rect = fitz.Rect(left, 78, left + box_w, 150)
        _box(page, rect, font, node["label"], node["note"])
        centers[node["id"]] = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    _draw_edges(page, spec["edges"], centers)
    return _png(doc)


def _render_tree(spec: dict, font: str) -> bytes:
    by_parent: dict[str, list[dict]] = {}
    for node in spec["nodes"]:
        by_parent.setdefault(node["parent"], []).append(node)
    levels: list[list[dict]] = []
    current = by_parent.get("", []) or spec["nodes"][:1]
    seen: set[str] = set()
    while current and len(levels) < 5:
        levels.append(current)
        nxt: list[dict] = []
        for node in current:
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            nxt.extend(by_parent.get(node["id"], []))
        current = nxt
    widest = max(len(level) for level in levels)
    width = max(720, 48 + widest * 170)
    height = 64 + len(levels) * 120
    doc, page = _new_page(width, height, spec["title"], font)
    centers: dict[str, tuple[float, float]] = {}
    for row, nodes in enumerate(levels):
        top = 56 + row * 120
        gap = (width - 48) / max(len(nodes), 1)
        box_w = min(140, gap - 16)
        for col, node in enumerate(nodes):
            left = 24 + col * gap + (gap - box_w) / 2
            rect = fitz.Rect(left, top, left + box_w, top + 64)
            _box(page, rect, font, node["label"], node["note"])
            centers[node["id"]] = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    parent_edges = [
        {"from": node["parent"], "to": node["id"], "label": ""}
        for node in spec["nodes"]
        if node["parent"] and node["parent"] in centers
    ]
    _draw_edges(page, parent_edges, centers)
    return _png(doc)


def _draw_edges(page, edges: list[dict], centers: dict[str, tuple[float, float]]) -> None:
    for edge in edges:
        start = centers.get(edge["from"])
        end = centers.get(edge["to"])
        if not start or not end:
            continue
        if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
            direction = 1 if end[0] >= start[0] else -1
            p1 = (start[0] + direction * 72, start[1])
            p2 = (end[0] - direction * 72, end[1])
        else:
            direction = 1 if end[1] >= start[1] else -1
            p1 = (start[0], start[1] + direction * 36)
            p2 = (end[0], end[1] - direction * 36)
        page.draw_line(p1, p2, color=(0.45, 0.55, 0.7), width=1.1)
