"""结构图按正文抽取后用字体绘制，装饰图风格不进入结构图。"""

from __future__ import annotations

import unittest

from app.engines.ark_image import build_prompt
from app.engines.writer_diagram import (
    DiagramError,
    chapter_diagram_source,
    find_cjk_font,
    fitz,
    normalize_diagram,
    render_diagram_png,
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


if __name__ == "__main__":
    unittest.main()
