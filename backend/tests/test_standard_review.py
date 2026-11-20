"""规范对标：查核点、专业过滤、拒绝编造条文、空库仍能结束。"""

from __future__ import annotations

import json
import unittest

from app.engines.standard_ingest import detect_specialty, detect_work_type, parse_standard_code, split_clauses
from app.engines.standard_review import (
    CHUNK_CHARS,
    DIRECT_BID_CHARS,
    MISS,
    NO_STANDARD_NOTE,
    REPARSE_NOTE,
    apply_judgments,
    bid_chunks,
    build_points,
    expert_score,
    merge_chunk_judgments,
    relevant_knowledge,
    review,
    select_clauses,
)
from app.engines.tech_rules import _parse_rows, attach_constraints, normalize_leaves


def _dimensions() -> list[dict]:
    return [
        {
            "items": [
                {
                    "id": "qty-drawing",
                    "label": "施工图纸",
                    "sections": [
                        {
                            "rows": [
                                {
                                    "label": "设计说明",
                                    "content": "高标准农田混凝土强度 C30，压实度 0.94",
                                }
                            ]
                        }
                    ],
                },
                {
                    "id": "qty-boq",
                    "sections": [
                        {
                            "rows": [
                                {"label": "项目名称", "content": "基坑开挖"},
                                {"label": "计量单位", "content": "m3"},
                                {"label": "工程数量", "content": "1200"},
                                {"label": "备注", "content": "深度 6m"},
                            ]
                        }
                    ],
                },
            ]
        }
    ]


class ClauseSplitTests(unittest.TestCase):
    def test_split_keeps_clause_numbers_and_skips_toc(self) -> None:
        text = "\n".join(
            [
                "4.1.2 .......... 12",
                "4.1.1 基坑深度超过 5m 时应专项论证。",
                "监测点沿坡顶布置。",
                "4.1.3 回填压实度不应小于 0.94，并做环刀试验。",
            ]
        )
        clauses = split_clauses(text)
        numbers = [item["clause_no"] for item in clauses]
        self.assertEqual(numbers, ["4.1.1", "4.1.3"])
        self.assertIn("环刀", clauses[1]["text"])

    def test_code_and_specialty_from_title(self) -> None:
        self.assertEqual(parse_standard_code("JGJ120-2012_建筑基坑支护技术规程.pdf"), "JGJ120-2012")
        self.assertEqual(detect_specialty("高标准农田灌溉"), "水利")
        self.assertEqual(detect_specialty("建筑基坑支护"), "房建")

    def test_specialty_not_confused_by_generic_engineering_words(self) -> None:
        """水利渠道、堤防工程也大量出现混凝土/结构/基坑等通用工程词，不能被误判成房建。"""
        blob = (
            "本工程为河道治理堤防加固工程，渠道开挖基坑后浇筑混凝土挡墙结构，"
            "围堰导流后进行水下作业，资质要求：水利水电工程施工总承包三级。"
        )
        self.assertEqual(detect_specialty(blob), "水利")

    def test_specialty_qualification_name_is_strong_signal(self) -> None:
        self.assertEqual(
            detect_specialty("投标人须具备市政公用工程施工总承包贰级及以上资质"), "市政"
        )
        self.assertEqual(
            detect_specialty("投标人须具备公路工程施工总承包贰级及以上资质"), "公路"
        )

    def test_detect_work_type(self) -> None:
        self.assertEqual(detect_work_type("本工程为水库除险加固工程"), "除险加固")
        self.assertEqual(detect_work_type("堤防维修养护工程"), "维修养护")
        self.assertEqual(detect_work_type("泵站改扩建及提升工程"), "改建")
        self.assertEqual(detect_work_type("灌区扩建工程"), "扩建")
        self.assertEqual(detect_work_type("新建渠道工程"), "新建")
        self.assertEqual(detect_work_type("没有任何工程类型关键词"), "新建")
        self.assertEqual(
            detect_work_type("安徽省合肥市店埠河治理工程。本次对未治理河道进行整治，未达标段进行提标建设。承包人对其使用的交通道路进行必要的维修加固。"),
            "改建",
        )
        self.assertEqual(detect_work_type("交通道路进行必要的维修加固"), "新建")


class ParseRowTests(unittest.TestCase):
    def test_object_wrapper_keeps_bracket_inside_text(self) -> None:
        raw = json.dumps(
            {
                "rules": [
                    {
                        "factor": "闸门",
                        "mustWrite": "孔宽按说明[1]写明",
                        "axis": "完整性",
                    }
                ]
            },
            ensure_ascii=False,
        )
        rows = _parse_rows(raw)
        self.assertEqual(rows[0]["factor"], "闸门")

    def test_truncated_json_keeps_closed_rules(self) -> None:
        closed = json.dumps(
            {"factor": "渠道", "mustWrite": "写明渠道断面和垫层", "axis": "完整性"},
            ensure_ascii=False,
        )
        raw = '{"rules":[' + closed + ',{"factor":"箱涵","mustWrite":"未写完'
        rows = _parse_rows(raw)
        self.assertEqual([item["factor"] for item in rows], ["渠道"])


class IndicatorTests(unittest.TestCase):
    def _leaves(self) -> list[dict]:
        return normalize_leaves(
            [
                {
                    "factor": "类似业绩",
                    "mustWrite": "近五年同类项目业绩",
                    "axis": "完整性",
                },
                {
                    "factor": "混凝土强度",
                    "mustWrite": "写明结构混凝土强度等级",
                    "standards": ["GB 50010-2010"],
                    "chapter": "施工方案",
                    "axis": "合规性",
                },
                {
                    "factor": "投标保证金证明材料",
                    "mustWrite": "附基本存款账户证明扫描件",
                    "axis": "规范性",
                },
                {
                    "factor": "工程保险",
                    "mustWrite": "承包人投保建筑工程一切险",
                    "axis": "合规性",
                },
                {
                    "factor": "导流方案",
                    "mustWrite": "写明导流、围堰和度汛措施",
                    "axis": "完整性",
                },
            ]
        )

    def test_tech_leaves_drop_business_and_keep_must_write(self) -> None:
        leaves = self._leaves()
        self.assertEqual([item["factor"] for item in leaves], ["混凝土强度", "导流方案"])
        score_rules = [
            {
                "dimension": "商务标",
                "detail": "类似业绩：近五年同类项目",
                "weight": 5,
                "sourceItemId": "eval-business",
            }
        ]
        tech = build_points(score_rules, _dimensions(), scope="tech", tech_rules=leaves)
        names = " ".join(item["name"] for item in tech)
        self.assertNotIn("业绩", names)
        self.assertIn("混凝土强度", names)
        self.assertEqual(tech[0]["mustWrite"], "写明结构混凝土强度等级")
        self.assertEqual(tech[0]["axis"], "合规性")
        self.assertTrue(all(item["source"] == "招标书" for item in tech))
        business = build_points(score_rules, _dimensions(), scope="business", tech_rules=leaves)
        self.assertIn("业绩", " ".join(item["name"] for item in business))
        self.assertNotIn("混凝土", " ".join(item["name"] for item in business))

    def test_drawing_param_attaches_and_boq_is_not_its_own_point(self) -> None:
        leaves = attach_constraints(self._leaves(), _dimensions())
        self.assertIn("C30", leaves[0]["parameters"])
        self.assertNotIn("基坑开挖", leaves[0]["parameters"])
        points = build_points([], _dimensions(), scope="tech", tech_rules=leaves)
        sources = {item["source"] for item in points}
        self.assertEqual(sources, {"招标书"})
        self.assertNotIn("基坑开挖", " ".join(item["name"] for item in points))

    def test_missing_tech_rules_asks_to_reparse(self) -> None:
        class _Query:
            def filter(self, *_args, **_kwargs):
                return self

            def limit(self, _count):
                return self

            def all(self):
                return []

        class _Db:
            def query(self, _model):
                return _Query()

        result = review(
            _Db(),
            score_rules=[],
            dimensions=_dimensions(),
            bid_text="本工程采用 C25 混凝土。",
            scope="tech",
        )
        self.assertEqual(result["points"], [])
        self.assertIn(REPARSE_NOTE, result["note"])

    def test_must_write_without_clause_can_be_missing(self) -> None:
        packed = [
            {
                "id": "sp-1",
                "source": "招标书",
                "name": "混凝土强度",
                "mustWrite": "写明结构混凝土强度等级",
                "parameters": "图纸混凝土强度C30",
                "axis": "完整性",
                "chapter": "施工方案",
                "clauses": [],
            }
        ]
        raw = [
            {
                "id": "sp-1",
                "verdict": "应有未写",
                "excerpt": "",
                "reason": "标书未写混凝土强度",
            }
        ]
        points, findings = apply_judgments(packed, raw, "本工程采用普通混凝土。")
        self.assertEqual(points[0]["verdict"], "应有未写")
        self.assertEqual(len(findings), 1)
        self.assertIn("完整性", points[0]["reason"])
        self.assertIn("写明结构混凝土强度等级", findings[0]["tenderQuote"])


class RetrieveJudgeTests(unittest.TestCase):
    def test_specialty_filter_drops_other_discipline(self) -> None:
        rows = [
            {
                "code": "JGJ120-2012",
                "clause_no": "4.1.3",
                "specialty": "房建",
                "text": "基坑支护应布置监测点",
            },
            {
                "code": "SL252-2017",
                "clause_no": "3.1.1",
                "specialty": "水利",
                "text": "基坑支护应布置监测点",
            },
        ]
        hits = select_clauses(rows, "基坑支护监测点", "房建")
        self.assertEqual([item["code"] for item in hits], ["JGJ120-2012"])

    def test_fabricated_clause_is_dropped(self) -> None:
        packed = [
            {
                "id": "sp-1",
                "source": "图纸",
                "name": "混凝土强度 C30",
                "detail": "C30",
                "clauses": [
                    {
                        "key": "JGJ1-2014 4.1.1",
                        "code": "JGJ1-2014",
                        "clauseNo": "4.1.1",
                        "excerpt": "混凝土强度等级不应低于 C30",
                    }
                ],
            }
        ]
        raw = [
            {
                "id": "sp-1",
                "verdict": "参数不一致",
                "clauseKey": "GB 99999 1.1.1",
                "excerpt": "采用 C25 混凝土",
                "reason": "写错标号",
            }
        ]
        points, findings = apply_judgments(packed, raw, "本工程采用 C25 混凝土。")
        self.assertEqual(findings, [])
        self.assertIn("丢弃", points[0]["reason"])

    def test_matching_clause_becomes_finding(self) -> None:
        packed = [
            {
                "id": "sp-1",
                "source": "图纸",
                "name": "混凝土强度 C30",
                "detail": "C30",
                "clauses": [
                    {
                        "key": "JGJ1-2014 4.1.1",
                        "code": "JGJ1-2014",
                        "clauseNo": "4.1.1",
                        "excerpt": "混凝土强度等级不应低于 C30",
                    }
                ],
            }
        ]
        raw = [
            {
                "id": "sp-1",
                "verdict": "参数不一致",
                "clauseKey": "JGJ1-2014 4.1.1",
                "excerpt": "采用 C25 混凝土",
                "reason": "图纸为 C30",
            }
        ]
        _points, findings = apply_judgments(packed, raw, "本工程采用 C25 混凝土。")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["level"], "L3")
        self.assertEqual(findings[0]["severity"], "降档")
        self.assertIn("JGJ1-2014", findings[0]["tenderQuote"])


class FullTextTests(unittest.TestCase):
    def test_short_bid_stays_one_piece(self) -> None:
        text = "危大工程专项方案" * 20
        self.assertEqual(bid_chunks(text), [text])

    def test_long_bid_covers_every_character(self) -> None:
        text = "".join(f"{index:05d}" for index in range(14000)) + "结尾隐蔽工程"
        chunks = bid_chunks(text)
        self.assertGreater(len(text), DIRECT_BID_CHARS)
        self.assertGreater(len(chunks), 1)
        cursor = 0
        for chunk in chunks:
            found = text.find(chunk, max(0, cursor - CHUNK_CHARS))
            self.assertGreaterEqual(found, 0)
            self.assertLessEqual(found, cursor)
            cursor = found + len(chunk)
        self.assertEqual(cursor, len(text))
        self.assertIn("结尾隐蔽工程", chunks[-1])

    def test_written_chapter_overrides_opening_miss(self) -> None:
        merged = merge_chunk_judgments(
            [
                {"id": "sp-1", "verdict": "应有未写", "excerpt": "", "reason": "开头只有编制依据"},
                {"id": "sp-1", "verdict": "已响应", "excerpt": "编制深基坑专项方案", "reason": "完整性：后文已写专项方案"},
            ]
        )
        self.assertEqual(merged["verdict"], "已响应")

    def test_score_snaps_to_tender_band_and_weight(self) -> None:
        scored = expert_score(
            {
                "grades": "优/良/中等/一般/差五档，对应赋分100/90/80/70/60",
                "ruleScore": "权重30%，赋分优100分、良90分",
            },
            {"score": 85, "grade": "良", "problems": "缺专家论证", "suggestion": "补论证", "strategy": "按基坑专项写"},
        )
        self.assertEqual(scored["score"], 80)
        self.assertEqual(scored["grade"], "中等")
        self.assertEqual(scored["weight"], "30%")
        self.assertEqual(scored["weightedScore"], 24.0)
        self.assertIn("专家论证", scored["problems"])

    def test_unscored_format_rule_has_no_invented_points(self) -> None:
        scored = expert_score(
            {"grades": "不符合编制要求按相应评审因素扣分", "ruleScore": "不单独赋分，作为技术标编制合规性"},
            {"score": 90, "grade": "符合", "verdict": "已响应"},
        )
        self.assertIsNone(scored["score"])
        self.assertEqual(scored["grade"], "符合")

    def test_knowledge_drops_unrelated_software_text(self) -> None:
        hits = relevant_knowledge(
            [
                {"title": "积分平台", "heading": "评分标准", "excerpt": "学员完成任务获得积分"},
                {"title": "基坑规程", "heading": "危大工程", "excerpt": "危大工程中的深基坑专项方案应组织专家论证"},
            ],
            "工程重点难点及危大工程",
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("专家论证", hits[0]["excerpt"])

    def test_quote_missing_from_bid_is_dropped(self) -> None:
        points, _findings = apply_judgments(
            [
                {
                    "id": "sp-1",
                    "source": "招标书",
                    "name": "混凝土强度",
                    "mustWrite": "写明结构混凝土强度等级",
                    "clauses": [],
                }
            ],
            [
                {
                    "id": "sp-1",
                    "verdict": "已响应",
                    "excerpts": ["本工程采用 C30 混凝土。", "招标书写明必须使用 C40。"],
                    "checks": [
                        {"item": "强度等级", "bid": "本工程采用 C30 混凝土。", "result": "已对上"},
                        {"item": "垫层", "bid": "投标书没有这句话。", "result": "已对上"},
                    ],
                }
            ],
            "本工程采用 C30 混凝土。",
        )
        self.assertEqual(points[0]["excerpts"], ["本工程采用 C30 混凝土。"])
        self.assertEqual(points[0]["checks"][0]["bid"], "本工程采用 C30 混凝土。")
        self.assertEqual(points[0]["checks"][1]["bid"], "")
        self.assertEqual(points[0]["checks"][1]["result"], "未见")

    def test_conflict_without_clause_is_cleared(self) -> None:
        points, _findings = apply_judgments(
            [
                {
                    "id": "sp-1",
                    "source": "招标书",
                    "name": "混凝土强度",
                    "mustWrite": "写明结构混凝土强度等级",
                    "clauses": [],
                    "knowledge": [],
                }
            ],
            [
                {
                    "id": "sp-1",
                    "verdict": "已响应",
                    "checks": [
                        {"item": "强度等级", "bid": "本工程采用 C30 混凝土。", "result": "与规范不符"},
                    ],
                    "noncompliance": "不符合 GB 99999 第 1 条",
                    "excerpts": ["本工程采用 C30 混凝土。"],
                }
            ],
            "本工程采用 C30 混凝土。",
        )
        self.assertNotEqual(points[0]["checks"][0]["result"], "与规范不符")
        self.assertEqual(points[0]["noncompliance"], NO_STANDARD_NOTE)
        self.assertNotIn("GB 99999", points[0]["noncompliance"])


class EmptyLibraryTests(unittest.TestCase):
    def test_review_finishes_when_library_is_empty(self) -> None:
        class _Query:
            def filter(self, *_args, **_kwargs):
                return self

            def limit(self, _count):
                return self

            def all(self):
                return []

        class _Db:
            def query(self, _model):
                return _Query()

        result = review(
            _Db(),
            score_rules=[],
            dimensions=_dimensions(),
            bid_text="本工程采用 C25 混凝土。",
            scope="tech",
        )
        self.assertEqual(result["points"], [])
        self.assertEqual(result["findings"], [])
        self.assertIn(REPARSE_NOTE, result["note"])


if __name__ == "__main__":
    unittest.main()
