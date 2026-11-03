"""标书页数按版式换算成技术章目标字数。"""

from __future__ import annotations

import unittest

from app.engines.e_writer import _build_chapter_context, chapter_char_targets, chars_per_page, resolve_body_pages


def _outline() -> list[dict]:
    return [
        {"id": "biz", "title": "商务标", "parentId": None, "part": "business", "weight": 10},
        {"id": "tech", "title": "技术方案", "parentId": None, "part": "tech", "weight": 0},
        {"id": "a", "title": "施工组织", "parentId": "tech", "part": "tech", "weight": 30},
        {"id": "b", "title": "质量措施", "parentId": "tech", "part": "tech", "weight": 10},
        {"id": "form", "title": "投标函", "parentId": None, "part": "form", "weight": 5},
    ]


class PageBudgetTest(unittest.TestCase):
    def test_fixed_line_spacing_ignores_previous_multiple(self) -> None:
        normal = chars_per_page(
            {"fontSize": "小四", "lineSpacing": "1.5倍行距", "lineSpacingMul": 1.5, "margins": {"top": 2, "bottom": 2, "left": 2, "right": 2}}
        )
        fixed = chars_per_page(
            {"fontSize": "小四", "lineSpacing": "固定值28磅", "lineSpacingMul": 1.5, "margins": {"top": 2, "bottom": 2, "left": 2, "right": 2}}
        )
        self.assertLess(fixed, normal)

    def test_inconsistent_pages_use_total_minus_cover_and_appendix(self) -> None:
        self.assertEqual(resolve_body_pages({"total": 200, "cover": 6, "body": 140, "appendix": 30}), 164)

    def test_weights_split_only_tech_leaves(self) -> None:
        page = {"total": 100, "cover": 0, "body": 100, "appendix": 0}
        layout = {"fontSize": "小四", "lineSpacing": "1.5倍行距", "lineSpacingMul": 1.5}
        targets = chapter_char_targets(_outline(), page, layout)
        self.assertEqual(set(targets), {"a", "b"})
        self.assertEqual(sum(targets.values()), 100 * chars_per_page(layout))
        self.assertEqual(targets["a"], targets["b"] * 3)

    def test_prompt_states_the_chapter_band(self) -> None:
        page = {"total": 40, "cover": 0, "body": 40, "appendix": 0}
        layout = {"fontSize": "小四", "lineSpacing": "1.5倍行距", "lineSpacingMul": 1.5}
        text = _build_chapter_context(
            "水安",
            "施工组织",
            "",
            None,
            [],
            writing_prefs={"page": page, "layout": layout},
            outline=_outline(),
            chapter_id="a",
        )
        target = chapter_char_targets(_outline(), page, layout)["a"]
        self.assertIn(f"本章目标约 {target} 字", text)
        self.assertIn("0.8 倍到 1.2 倍", text)

    def test_parent_and_business_have_no_target(self) -> None:
        page = {"total": 40, "cover": 0, "body": 40, "appendix": 0}
        targets = chapter_char_targets(_outline(), page, {"fontSize": "小四"})
        self.assertNotIn("tech", targets)
        self.assertNotIn("biz", targets)


if __name__ == "__main__":
    unittest.main()
