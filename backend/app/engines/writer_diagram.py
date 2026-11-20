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
- 功能架构、技术架构、部署拓扑：layer 从上到下，0 为最上层。每个非根节点的 parent 必须写成它所属的直接上层节点 id，绘图会从父框下沿连到子框上沿。根节点 parent 为空。
- edges 只表示正文写明的连接、访问或数据交换，不要把“属于某一层/区域”再写成 edge。同一层不要按出现顺序串成一条链；部署拓扑只连接正文里真正相邻互通的两端，例如内网连边界、边界连外网。
- 人员组织：用 parent 表示直接上级，根节点 parent 为空，不要画成技术分层。
- 流程图：节点按先后放在 layer 0，并用 edges 按顺序连接，parent 留空。
- 节点最多 12 个，label 不超过 12 个字，note 不超过 10 个字。
"""

_BOX_W = 150.0
_BOX_H = 78.0
_GAP_X = 22.0
_GAP_Y = 56.0
_MARGIN = 28.0
_TOP = 84.0


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
    if layout == "layers":
        edges = _bind_layer_parents(nodes, edges)
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


def _bind_layer_parents(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """包含关系走 parent，连线只保留跨节点的真实连接。"""
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        parent = by_id.get(node["parent"])
        if parent is None or parent["id"] == node["id"] or parent["layer"] >= node["layer"]:
            node["parent"] = ""
    kept: list[dict] = []
    for edge in edges:
        src = by_id.get(edge["from"])
        dst = by_id.get(edge["to"])
        if src is None or dst is None:
            continue
        if src["layer"] < dst["layer"] and not dst["parent"]:
            dst["parent"] = src["id"]
            continue
        if dst["layer"] < src["layer"] and not src["parent"]:
            src["parent"] = dst["id"]
            continue
        if dst["parent"] == src["id"] or src["parent"] == dst["id"]:
            continue
        kept.append(edge)
    return kept


def layout_diagram(spec: dict) -> dict[str, tuple[float, float, float, float]]:
    """返回每个节点的 (x0, y0, x1, y1)。有父子关系时，子节点排在父节点正下方。"""
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    if spec.get("layout") == "flow":
        return _layout_flow(nodes)
    if any(node.get("parent") for node in nodes):
        return _layout_forest(nodes, edges)
    return _layout_rows(nodes, edges)


def _order_by_links(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """同一层按真实连线排成相邻顺序，避免线条跨过中间的框。"""
    if len(nodes) < 3:
        return nodes
    ids = [node["id"] for node in nodes]
    idset = set(ids)
    adj: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if src in idset and dst in idset and src != dst:
            adj[src].add(dst)
            adj[dst].add(src)
    if not any(adj.values()) or any(len(links) > 2 for links in adj.values()):
        return nodes
    starts = [node_id for node_id in ids if len(adj[node_id]) == 1]
    start = starts[0] if starts else next((node_id for node_id in ids if adj[node_id]), None)
    if start is None:
        return nodes
    ordered: list[str] = []
    seen: set[str] = set()
    current: str | None = start
    while current and current not in seen:
        seen.add(current)
        ordered.append(current)
        nxt = [node_id for node_id in ids if node_id in adj[current] and node_id not in seen]
        current = nxt[0] if len(nxt) == 1 else None
    if len(ordered) < 2:
        return nodes
    ordered.extend(node_id for node_id in ids if node_id not in seen)
    by_id = {node["id"]: node for node in nodes}
    return [by_id[node_id] for node_id in ordered]


def route_between(
    src: tuple[float, float, float, float],
    dst: tuple[float, float, float, float],
    obstacles: list[tuple[float, float, float, float]] | None = None,
) -> list[tuple[float, float]]:
    """从源框边框走到目标框边框，避开中间的框。"""
    ax0, ay0, ax1, ay1 = src
    bx0, by0, bx1, by1 = dst
    acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
    bcx, bcy = (bx0 + bx1) / 2, (by0 + by1) / 2
    blockers = obstacles or []

    def clear(points: list[tuple[float, float]]) -> bool:
        return all(not any(_segment_hits(p, q, rect) for rect in blockers) for p, q in zip(points, points[1:]))

    if ay1 <= by0 + 0.5:
        mid = (ay1 + by0) / 2
        if abs(acx - bcx) < 0.5:
            return [(acx, ay1), (bcx, by0)]
        return [(acx, ay1), (acx, mid), (bcx, mid), (bcx, by0)]
    if by1 <= ay0 + 0.5:
        mid = (by1 + ay0) / 2
        if abs(acx - bcx) < 0.5:
            return [(acx, ay0), (bcx, by1)]
        return [(acx, ay0), (acx, mid), (bcx, mid), (bcx, by1)]
    side = [(ax1, acy), (bx0, bcy)] if acx <= bcx else [(ax0, acy), (bx1, bcy)]
    if clear(side):
        return side
    above = min(ay0, by0) - 20
    return [(acx, ay0), (acx, above), (bcx, above), (bcx, by0)]


def _segment_hits(
    p: tuple[float, float], q: tuple[float, float], rect: tuple[float, float, float, float]
) -> bool:
    (ax, ay), (bx, by) = p, q
    x0, y0, x1, y1 = rect
    if abs(ay - by) <= 0.6:
        if ay < y0 or ay > y1:
            return False
        lo, hi = (ax, bx) if ax <= bx else (bx, ax)
        return hi > x0 and lo < x1
    if abs(ax - bx) <= 0.6:
        if ax < x0 or ax > x1:
            return False
        lo, hi = (ay, by) if ay <= by else (by, ay)
        return hi > y0 and lo < y1
    return False


def _layout_flow(nodes: list[dict]) -> dict[str, tuple[float, float, float, float]]:
    rects: dict[str, tuple[float, float, float, float]] = {}
    for index, node in enumerate(nodes):
        left = _MARGIN + index * (_BOX_W + 36)
        rects[node["id"]] = (left, 78, left + _BOX_W, 78 + _BOX_H)
    return rects


def _layout_rows(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float, float, float]]:
    groups: dict[int, list[dict]] = {}
    for node in nodes:
        groups.setdefault(int(node["layer"]), []).append(node)
    rects: dict[str, tuple[float, float, float, float]] = {}
    for row, key in enumerate(sorted(groups)):
        for col, node in enumerate(_order_by_links(groups[key], edges)):
            left = _MARGIN + col * (_BOX_W + _GAP_X)
            top = _TOP + row * (_BOX_H + _GAP_Y)
            rects[node["id"]] = (left, top, left + _BOX_W, top + _BOX_H)
    return rects


def _forest(nodes: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    ids = {node["id"] for node in nodes}
    parent_of: dict[str, str] = {}
    for node in nodes:
        parent = node.get("parent") or ""
        if parent in ids and parent != node["id"]:
            parent_of[node["id"]] = parent
    for node in nodes:
        seen: list[str] = []
        current = node["id"]
        while current in parent_of:
            if current in seen:
                parent_of.pop(node["id"], None)
                break
            seen.append(current)
            current = parent_of[current]
    kids: dict[str, list[dict]] = {node["id"]: [] for node in nodes}
    for node in nodes:
        parent = parent_of.get(node["id"])
        if parent:
            kids[parent].append(node)
    roots = [node for node in nodes if node["id"] not in parent_of]
    return kids, roots or nodes[:1]


def _span(node_id: str, kids: dict[str, list[dict]]) -> float:
    group = kids.get(node_id) or []
    if not group:
        return _BOX_W
    return max(_BOX_W, sum(_span(child["id"], kids) for child in group) + _GAP_X * (len(group) - 1))


def _place(
    node: dict,
    left: float,
    top: float,
    kids: dict[str, list[dict]],
    rects: dict[str, tuple[float, float, float, float]],
) -> None:
    span = _span(node["id"], kids)
    x = left + (span - _BOX_W) / 2
    rects[node["id"]] = (x, top, x + _BOX_W, top + _BOX_H)
    cursor = left
    for child in kids.get(node["id"]) or []:
        child_span = _span(child["id"], kids)
        _place(child, cursor, top + _BOX_H + _GAP_Y, kids, rects)
        cursor += child_span + _GAP_X


def _layout_forest(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float, float, float]]:
    kids, roots = _forest(nodes)
    kids = {node_id: _order_by_links(group, edges) for node_id, group in kids.items()}
    roots = _order_by_links(roots, edges)
    rects: dict[str, tuple[float, float, float, float]] = {}
    cursor = _MARGIN
    for root in roots:
        _place(root, cursor, _TOP, kids, rects)
        cursor += _span(root["id"], kids) + _GAP_X * 2
    return rects


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
    rects = layout_diagram(spec)
    width, height = _canvas(rects)
    doc, page = _new_page(width, height, spec.get("title") or "", font)
    for node in spec.get("nodes") or []:
        x0, y0, x1, y1 = rects[node["id"]]
        _box(page, fitz.Rect(x0, y0, x1, y1), font, node["label"], node.get("note") or "")
    if spec.get("layout") != "flow":
        _draw_containment(page, spec.get("nodes") or [], rects)
    _draw_links(page, spec.get("edges") or [], rects)
    return _png(doc)


def _canvas(rects: dict[str, tuple[float, float, float, float]]) -> tuple[float, float]:
    if not rects:
        return 720, 220
    return max(720, max(rect[2] for rect in rects.values()) + _MARGIN), max(200, max(rect[3] for rect in rects.values()) + 36)


def _wrap(text: str, width: float, size: float, max_lines: int) -> str:
    per = max(1, int(width / max(size, 1)))
    lines = [text[i : i + per] for i in range(0, len(text), per)]
    return "\n".join(lines[:max_lines])


def _ensure_cjk(page, font: str) -> None:
    # fontfile 直接传给 insert_textbox 时，ttc 里的汉字会被画成问号。先注册字体名再写。
    names = {item[4] for item in (page.get_fonts() or []) if len(item) > 4}
    if "cjk" not in names:
        page.insert_font(fontname="cjk", fontfile=font)


def _text(page, rect: fitz.Rect, text: str, font: str, size: float, color: tuple[float, float, float]) -> None:
    if not text:
        return
    _ensure_cjk(page, font)
    page.insert_textbox(rect, text, fontname="cjk", fontsize=size, color=color, align=fitz.TEXT_ALIGN_CENTER)


def _box(page, rect: fitz.Rect, font: str, label: str, note: str = "") -> None:
    page.draw_rect(rect, color=(0.15, 0.35, 0.62), fill=(0.93, 0.96, 0.99), width=1.2)
    inner_w = (rect.x1 - rect.x0) - 12
    if note:
        _text(page, fitz.Rect(rect.x0 + 6, rect.y0 + 6, rect.x1 - 6, rect.y0 + 42), _wrap(label, inner_w, 12, 2), font, 12, (0.1, 0.16, 0.28))
        _text(page, fitz.Rect(rect.x0 + 6, rect.y0 + 42, rect.x1 - 6, rect.y1 - 4), _wrap(note, inner_w, 9, 2), font, 9, (0.35, 0.4, 0.48))
    else:
        _text(page, fitz.Rect(rect.x0 + 6, rect.y0 + 8, rect.x1 - 6, rect.y1 - 6), _wrap(label, inner_w, 12, 3), font, 12, (0.1, 0.16, 0.28))


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


def _stroke(page, points: list[tuple[float, float]]) -> None:
    for start, end in zip(points, points[1:]):
        if abs(start[0] - end[0]) < 0.4 and abs(start[1] - end[1]) < 0.4:
            continue
        page.draw_line(start, end, color=(0.45, 0.55, 0.7), width=1.2)


def _draw_containment(page, nodes: list[dict], rects: dict[str, tuple[float, float, float, float]]) -> None:
    children: dict[str, list[tuple[float, float, float, float]]] = {}
    for node in nodes:
        parent = node.get("parent") or ""
        if parent in rects and node["id"] in rects:
            children.setdefault(parent, []).append(rects[node["id"]])
    for parent_id, child_rects in children.items():
        parent = rects[parent_id]
        pcx = (parent[0] + parent[2]) / 2
        bus_y = (parent[3] + min(rect[1] for rect in child_rects)) / 2
        centers = [((rect[0] + rect[2]) / 2, rect[1]) for rect in child_rects]
        xs = [point[0] for point in centers] + [pcx]
        _stroke(page, [(pcx, parent[3]), (pcx, bus_y)])
        _stroke(page, [(min(xs), bus_y), (max(xs), bus_y)])
        for cx, top in centers:
            _stroke(page, [(cx, bus_y), (cx, top)])


def _draw_links(page, edges: list[dict], rects: dict[str, tuple[float, float, float, float]]) -> None:
    for edge in edges:
        src = rects.get(edge.get("from") or "")
        dst = rects.get(edge.get("to") or "")
        if src is None or dst is None:
            continue
        obstacles = [rect for node_id, rect in rects.items() if node_id not in (edge.get("from"), edge.get("to"))]
        _stroke(page, route_between(src, dst, obstacles))
