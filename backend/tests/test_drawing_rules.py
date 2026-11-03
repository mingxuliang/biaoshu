"""施工图图签、选图、标准号保留，以及按图面参数预审。"""

from __future__ import annotations

import unittest

from app.engines.drawing_rules import (
    compose_rule,
    extract_standards,
    merge_drawing_into_leaves,
    notes_from_text,
    parse_title_block,
    select_sheets,
    strip_invented_codes,
)
from app.engines.standard_review import apply_judgments, build_points


def _dimensions() -> list[dict]:
    return [
        {
            "items": [
                {
                    "id": "qty-boq",
                    "sections": [
                        {
                            "rows": [
                                {"label": "项目名称", "content": "基坑开挖"},
                                {"label": "计量单位", "content": "m3"},
                                {"label": "工程数量", "content": "1200"},
                            ]
                        }
                    ],
                }
            ]
        }
    ]


class DrawingRuleTests(unittest.TestCase):
    def test_title_block_splits_number_and_name(self) -> None:
        parsed = parse_title_block("图号 HYXGHZNT-BRQJD-SCQ-05\n图名 过路箱涵纵断面配筋图")
        self.assertEqual(parsed["drawingNo"], "HYXGHZNT-BRQJD-SCQ-05")
        self.assertEqual(parsed["title"], "过路箱涵纵断面配筋图")

    def test_notes_keep_standard_code(self) -> None:
        text = "说明：箱涵混凝土按 GB 50010-2010 施工，并采用图集。"
        notes = notes_from_text(text)
        self.assertIn("GB 50010-2010", notes)
        self.assertEqual(extract_standards(notes), ["GB50010-2010"])

    def test_select_matching_sheet_and_skip_index(self) -> None:
        index = [
            {"title": "目录", "drawingNo": "", "page": 0},
            {"title": "过路箱涵纵断面配筋图", "drawingNo": "HYX-01", "page": 3},
            {"title": "图框", "drawingNo": "", "page": 4},
        ]
        chosen = select_sheets(index, ["箱涵", "基坑开挖"])
        self.assertEqual([item["title"] for item in chosen], ["过路箱涵纵断面配筋图"])

    def test_matched_drawing_is_a_check_point_not_a_boq_row(self) -> None:
        rule = compose_rule(
            {"title": "过路箱涵纵断面配筋图", "drawingNo": "HYX-01"},
            "说明：净宽按图施工，混凝土按 GB 50010-2010。",
            None,
        )
        self.assertEqual(rule["parameters"], "未识图")
        self.assertIn("GB50010-2010", rule["standards"])
        points = build_points([], _dimensions(), scope="tech", drawing_rules=[rule])
        self.assertEqual({item["source"] for item in points}, {"图纸"})
        self.assertNotIn("基坑开挖", " ".join(item["name"] for item in points))
        self.assertEqual(build_points([], _dimensions(), scope="business", drawing_rules=[rule]), [])

    def test_vision_cannot_invent_standard_code(self) -> None:
        cleaned = strip_invented_codes("净宽2.0m GB 99999-2010", ["GB50010-2010"])
        self.assertIn("净宽2.0m", cleaned)
        self.assertNotIn("99999", cleaned)

    def test_leaf_receives_drawing_parameters(self) -> None:
        leaves = [{"factor": "箱涵", "mustWrite": "写明箱涵做法", "parameters": "", "standards": []}]
        rules = [
            compose_rule(
                {"title": "过路箱涵纵断面配筋图", "drawingNo": "HYX-01"},
                "说明：按 GB 50010-2010 施工。",
                "净宽2.0m，C30",
            )
        ]
        merged = merge_drawing_into_leaves(leaves, rules)
        self.assertIn("净宽2.0m", merged[0]["parameters"])
        self.assertIn("GB 50010-2010", merged[0]["mustWrite"])

    def test_parameter_mismatch_without_clause(self) -> None:
        packed = [
            {
                "id": "sp-1",
                "source": "图纸",
                "name": "过路箱涵纵断面配筋图",
                "mustWrite": "说明：净宽按图施工",
                "parameters": "净宽2.0m，C30",
                "drawingNo": "HYX-01",
                "clauses": [],
            }
        ]
        raw = [{"id": "sp-1", "verdict": "参数不一致", "excerpt": "净宽1.5m", "reason": "图面为2.0m"}]
        _points, findings = apply_judgments(packed, raw, "箱涵净宽1.5m。")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "降档")
        conflict = [{"id": "sp-1", "verdict": "做法冲突", "clauseKey": "GB 99999 1.1", "excerpt": "净宽1.5m", "reason": "编造"}]
        _points, dropped = apply_judgments(packed, conflict, "箱涵净宽1.5m。")
        self.assertEqual(dropped, [])
        self.assertIn("丢弃", _points[0]["reason"])


if __name__ == "__main__":
    unittest.main()
