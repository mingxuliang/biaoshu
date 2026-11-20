"""结构图按正文抽取后用字体绘制，装饰图风格不进入结构图。"""

from __future__ import annotations

import unittest

from app.engines.ark_image import build_prompt
from app.engines.writer_diagram import (
    DiagramError,
    chapter_diagram_source,
    find_cjk_font,
    fitz,
    layout_diagram,
    normalize_diagram,
    _new_page,
    render_diagram_png,
    route_between,
)


class WriterDiagramTest(unittest.TestCase):
    def test_solution_beats_idea(self) -> None:
        text, notice = chapter_diagram_source(
            "## 原始需求\n\n招标原文\n\n## 解决方案\n\n门户、业务中台和数据中台分层部署。",
            "编写思路",
        )
        self.assertIn("数据中台", text)
        self.assertNotIn("编写思路", text)
        self.assertEqual(notice, "")

    def test_idea_is_used_when_body_is_missing(self) -> None:
        text, notice = chapter_diagram_source("", "项目经理统筹，技术负责人分管实施。")
        self.assertIn("项目经理", text)
        self.assertIn("建议先生成正文", notice)

    def test_empty_source_is_rejected(self) -> None:
        with self.assertRaises(DiagramError):
            chapter_diagram_source("短", "")

    def test_organization_is_a_tree(self) -> None:
        spec = normalize_diagram(
            {
                "title": "项目部",
                "nodes": [
                    {"id": "pm", "label": "项目经理"},
                    {"id": "tech", "label": "技术负责人", "parent": "pm"},
                ],
            },
            "organization",
        )
        self.assertEqual(spec["layout"], "tree")
        self.assertEqual(spec["mode"], "arch")
        tech = next(node for node in spec["nodes"] if node["id"] == "tech")
        self.assertEqual(tech["parent"], "pm")

    def test_layers_keep_order(self) -> None:
        spec = normalize_diagram(
            {
                "nodes": [
                    {"id": "app", "label": "业务应用", "layer": 0},
                    {"id": "data", "label": "数据中台", "layer": 1},
                ],
                "edges": [{"from": "app", "to": "data"}],
            },
            "function",
        )
        self.assertEqual(spec["layout"], "layers")
        self.assertEqual([node["label"] for node in spec["nodes"]], ["业务应用", "数据中台"])

    def test_child_hangs_under_its_zone(self) -> None:
        spec = normalize_diagram(
            {
                "title": "三段部署",
                "nodes": [
                    {"id": "in", "label": "内网", "layer": 0},
                    {"id": "out", "label": "外网", "layer": 0},
                    {"id": "a", "label": "门户", "layer": 1, "parent": "in"},
                    {"id": "b", "label": "微服务", "layer": 1, "parent": "in"},
                    {"id": "c", "label": "移动端", "layer": 1, "parent": "out"},
                ],
                "edges": [{"from": "in", "to": "out"}],
            },
            "deployment",
        )
        self.assertEqual(next(node for node in spec["nodes"] if node["id"] == "a")["parent"], "in")
        self.assertEqual(spec["edges"], [{"from": "in", "to": "out", "label": ""}])
        rects = layout_diagram(spec)

        def center_x(node_id: str) -> float:
            rect = rects[node_id]
            return (rect[0] + rect[2]) / 2

        self.assertLess(rects["in"][3], rects["a"][1])
        self.assertLess(abs(center_x("in") - (center_x("a") + center_x("b")) / 2), 1)
        self.assertLess(center_x("a"), center_x("c"))
        self.assertLess(rects["in"][2], rects["out"][0])

    def test_cross_layer_edge_becomes_parent(self) -> None:
        spec = normalize_diagram(
            {
                "nodes": [
                    {"id": "zone", "label": "内网", "layer": 0},
                    {"id": "svc", "label": "门户", "layer": 1},
                ],
                "edges": [{"from": "zone", "to": "svc"}],
            },
            "technical",
        )
        self.assertEqual(next(node for node in spec["nodes"] if node["id"] == "svc")["parent"], "zone")
        self.assertEqual(spec["edges"], [])

    def test_same_layer_parent_is_dropped(self) -> None:
        spec = normalize_diagram(
            {
                "nodes": [
                    {"id": "a", "label": "甲", "layer": 0, "parent": "b"},
                    {"id": "b", "label": "乙", "layer": 0},
                ],
            },
            "deployment",
        )
        self.assertEqual(next(node for node in spec["nodes"] if node["id"] == "a")["parent"], "")

    def test_linked_zones_sit_in_link_order(self) -> None:
        spec = normalize_diagram(
            {
                "nodes": [
                    {"id": "in", "label": "内网", "layer": 0},
                    {"id": "out", "label": "外网", "layer": 0},
                    {"id": "edge", "label": "边界", "layer": 0},
                ],
                "edges": [{"from": "in", "to": "edge"}, {"from": "edge", "to": "out"}],
            },
            "deployment",
        )
        rects = layout_diagram(spec)
        self.assertLess(rects["in"][2], rects["edge"][0])
        self.assertLess(rects["edge"][2], rects["out"][0])

    def test_route_touches_box_borders(self) -> None:
        side = route_between((0, 10, 100, 80), (180, 10, 280, 80))
        self.assertEqual(side[0], (100, 45))
        self.assertEqual(side[-1], (180, 45))
        down = route_between((40, 0, 140, 70), (40, 140, 140, 210))
        self.assertEqual(down[0], (90, 70))
        self.assertEqual(down[-1], (90, 140))
        around = route_between((0, 10, 100, 80), (300, 10, 400, 80), [(140, 10, 260, 80)])
        self.assertLess(around[1][1], 10)

    def test_style_applies_only_to_decorative_photos(self) -> None:
        photo = build_prompt("项目现场", "normal", "简约扁平风")
        diagram = build_prompt("系统分层", "arch", "简约扁平风")
        self.assertIn("简约扁平", photo)
        self.assertNotIn("简约扁平", diagram)

    @unittest.skipUnless(fitz is not None, "未安装 PyMuPDF")
    def test_render_png_has_chinese_font(self) -> None:
        self.assertTrue(find_cjk_font())
        spec = normalize_diagram(
            {
                "title": "功能架构",
                "nodes": [
                    {"id": "a", "label": "门户", "layer": 0},
                    {"id": "b", "label": "中台", "layer": 1},
                ],
                "edges": [{"from": "a", "to": "b"}],
            },
            "function",
        )
        png = render_diagram_png(spec)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png), 1000)
        doc, page = _new_page(480, 160, "功能架构", find_cjk_font())
        try:
            self.assertIn("功能架构", page.get_text())
            self.assertNotIn("?", page.get_text())
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
