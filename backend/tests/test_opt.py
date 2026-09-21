"""修改闭环 / 约定对照 / 标题识别 的轻量单测，不依赖数据库。"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import docx

from app.engines.e3_semantic import CHUNK_CHARS, MAX_REVIEW_CHARS, _split_chunks
from app.engines.e_parse_match import _unanswered, run as parse_match_run
from app.engines.revision_build import _heading_level, writeback_docx


class HeadingLevelTests(unittest.TestCase):
    def test_plain_numbered_body_is_not_h1(self) -> None:
        para = {"text": "1. 投标人应具备独立法人资格", "bold": False, "fontSizePt": 12}
        self.assertIsNone(_heading_level(para, 12.0))

    def test_bold_short_numbered_is_h1(self) -> None:
        para = {"text": "1. 编制说明", "bold": True, "fontSizePt": 16}
        self.assertEqual(_heading_level(para, 12.0), 1)

    def test_chapter_heading(self) -> None:
        para = {"text": "第一章 施工组织设计", "bold": False, "fontSizePt": 12}
        self.assertEqual(_heading_level(para, 12.0), 1)

    def test_stamp_issue_chapters_from_paragraph_problem(self) -> None:
        from app.engines.revision_build import stamp_issue_chapters

        sections = [
            {
                "id": "sec-1",
                "heading": "第一章 施工组织",
                "paragraphs": [
                    {
                        "id": "p-1",
                        "text": "工期90天",
                        "problem": {"issueId": "i1", "highlight": "工期90天"},
                    }
                ],
            }
        ]
        issues = [{"id": "i1", "excerpt": "工期90天"}]
        stamp_issue_chapters(sections, issues)
        self.assertEqual(issues[0]["sectionId"], "sec-1")
        self.assertEqual(issues[0]["chapter"], "第一章 施工组织")


class ParseMatchTests(unittest.TestCase):
    def test_title_in_bid_is_covered(self) -> None:
        self.assertFalse(
            _unanswered(
                "投标人须提供有效营业执照副本扫描件",
                "详见附件：本公司营业执照及资质证书",
                "营业执照",
            )
        )

    def test_heading_does_not_cover_dimension(self) -> None:
        self.assertTrue(
            _unanswered(
                "施工进度计划应明确关键节点与工期保证措施",
                "正文未展开细节",
                "进度计划",
                "第一章 进度计划\n第二章 质量保证",
            )
        )

    def test_single_short_window_is_uncovered(self) -> None:
        self.assertTrue(
            _unanswered(
                "投标人必须提交完全无关的专项核验材料并加盖鲜章",
                "本公司依法设立，具有独立承担民事责任能力",
                "专项核验材料",
            )
        )

    def test_score_rule_title_hit_skips_finding(self) -> None:
        findings = parse_match_run(
            "技术标目录含进度计划与质量保证体系",
            score_rules=[{"dimension": "进度计划", "detail": "应说明关键线路", "weight": 5}],
            strategy_keys={"checklist_map"},
            headings=["进度计划"],
        )
        self.assertEqual(findings, [])

    def test_zero_weight_score_rule_is_not_treated_as_answer_item(self) -> None:
        """没有分值的条目（如「专用合同条款」违约金/验收期限、"本段未出现XX公式"占位说明）
        不是真正的评分点，不应被当成「必须在投标书里出现」的应答项，也不该触发任何模型调用。"""
        findings = parse_match_run(
            "投标书正文完全不提这件事",
            score_rules=[
                {
                    "dimension": "专用合同条款（技术要求）",
                    "detail": "违约、索赔与工期奖罚：逾期竣工违约金的上限：合同价款的4%",
                    "weight": 0,
                    "sourceItemId": "contract-tech",
                }
            ],
            strategy_keys={"checklist_map"},
        )
        self.assertEqual(findings, [])

    def test_grading_language_score_rule_is_not_treated_as_answer_item(self) -> None:
        """评委打分/分档语言（如「分档/赋分规则」）本就是评标口径，投标书原文搜不到这些
        字；不应被当成「必须在投标书里出现」的应答项，也不应触发任何模型调用。"""
        findings = parse_match_run(
            "投标书正文完全不提这件事",
            score_rules=[{"dimension": "评分办法", "detail": "分档/赋分规则：优得100分，良得80分"}],
            strategy_keys={"checklist_map"},
        )
        self.assertEqual(findings, [])

    def test_empty_candidates_escalate_to_chunk_scan_instead_of_direct_unanswered(self) -> None:
        """关键词窗口检索完全找不到候选时，不再直接判未响应，而是升级到分块通读；
        分块通读确认已响应则不应出现在问题清单里。"""
        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {"0": {"answered": True, "excerpt": "本工程已设置应急预案", "reason": "已通读确认"}}
            findings = parse_match_run(
                "投标书正文与关键词完全不重合，但别处其实写了应急预案",
                must_respond=[{"id": "mr-1", "clause": "投标人必须提交完全无关的专项应急预案并编号存档"}],
            )
        mock_scan.assert_called_once()
        self.assertEqual(findings, [])

    def test_chunk_scan_confirmed_unanswered_still_produces_finding(self) -> None:
        """分块通读之后仍确认未响应，才报缺项，且带上确认标记。"""
        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {
                "0": {
                    "answered": False,
                    "excerpt": "",
                    "reason": "对照本项招标要求，投标书中未见相应的实质性响应内容。",
                    "unanswered_confirmed": True,
                }
            }
            findings = parse_match_run(
                "投标书正文与关键词完全不重合",
                must_respond=[{"id": "mr-1", "clause": "投标人必须提交完全无关的专项应急预案并编号存档"}],
            )
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["unansweredConfirmed"])
        self.assertIn("未见相应的实质性响应", findings[0]["suggestion"])


class GradingFilterTests(unittest.TestCase):
    def test_grading_label_is_skipped(self) -> None:
        from app.engines.e_tender_score import is_grading_rule, split_label_content

        label, content = split_label_content("分档/赋分规则：优得100分，良得80分")
        self.assertEqual(label, "分档/赋分规则")
        self.assertTrue(is_grading_rule(label, content))

    def test_normal_score_point_is_not_grading_language(self) -> None:
        from app.engines.e_tender_score import is_grading_rule, split_label_content

        label, content = split_label_content("危大工程保障方案（7分）")
        self.assertFalse(is_grading_rule(label, content))

    def test_scoring_committee_procedure_text_is_grading_language(self) -> None:
        """评标委员会怎么由高到低取前N家、怎么算有效评标价，这类评标办法说明性文字本就是
        评委口径，不是投标人该写进正文的应答项（真实项目里出现过被误判成缺项的案例）。"""
        from app.engines.e_tender_score import is_grading_rule, split_label_content

        label, content = split_label_content(
            "技术标评分门槛：（2）技术评审标准：1）技术评审标准部分得分＞70 分，"
            "由高到低取前9 家（得分相同且排序最末的均计入）为A；2）技术评审标准部分得分≤70 分为C。"
        )
        self.assertTrue(is_grading_rule(label, content))

    def test_expand_score_items_ignores_stray_percent_deep_in_clause_text(self) -> None:
        """weight 缺省时，只在条目开头附近找「（N分）/N%」标注；专用合同条款里散落在段落
        深处、与分值无关的百分比（如违约金上限）不能被误当成本条评分权重。"""
        from app.engines.e_tender_score import expand_score_items

        score_rules = [
            {
                "dimension": "专用合同条款（技术要求）",
                "detail": (
                    "违约、索赔与工期奖罚：因承包人原因造成工期延误，逾期竣工违约金：竣工验收每延期"
                    "一天，承包人支付发包人违约金5万元/天；逾期竣工违约金的上限：合同价款的4%；"
                    "提前竣工的奖励：/。"
                ),
                "weight": 0,
                "sourceItemId": "contract-tech",
            }
        ]
        items = expand_score_items(score_rules, None)
        self.assertEqual(items, [])

    def test_expand_score_items_still_picks_up_score_near_head(self) -> None:
        """条目开头附近真的标了分值（如「XX方案（10分）」），仍要正常识别为评分点。"""
        from app.engines.e_tender_score import expand_score_items

        score_rules = [{"dimension": "施工方案", "detail": "总体部署与关键节点安排（10分）", "weight": 0}]
        items = expand_score_items(score_rules, None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["maxScore"], 10.0)

    def test_expand_score_items_excludes_contract_tech_payment_clause(self) -> None:
        """专用合同条款（付款进度/质保金等履约条款）不是投标时的评分点；文字里散落多处
        百分比时，不能被 _split_factors 误拆成好几条名字截断的假「评分项」。"""
        from app.engines.e_tender_score import expand_score_items

        score_rules = [
            {
                "dimension": "专用合同条款（技术要求）",
                "detail": (
                    "工程价款结算与支付：预付款按合同价款的10%支付；进度款按已完合同价款的85%"
                    "累计支付，剩余15%作为质保金分15个月扣回，扣回期满后一次性支付余款。"
                ),
                "weight": 0,
                "sourceItemId": "contract-tech",
            }
        ]
        items = expand_score_items(score_rules, None)
        self.assertEqual(items, [])


class ClauseScanTests(unittest.TestCase):
    """clause_scan.scan_items 的分块通读合并：命中/未命中/模型异常三种结果。"""

    def test_no_model_configured_marks_answered_safely(self) -> None:
        from app.engines import clause_scan

        with patch.object(clause_scan, "get_default_model_id", side_effect=Exception("未配置模型")):
            out = clause_scan.scan_items([{"id": "a", "query": "危大工程保障方案"}], "投标书正文" * 50)
        self.assertTrue(out["a"]["answered"])
        self.assertIn("宁缺毋滥", out["a"]["reason"])

    def test_all_calls_failed_marks_answered_safely(self) -> None:
        from app.engines import clause_scan

        long_text = "正文内容。" * 12000  # 一条超长无换行正文，硬切成多块
        with patch.object(clause_scan, "get_default_model_id", return_value="fake-model"), patch.object(
            clause_scan, "chat_complete", side_effect=Exception("model down")
        ):
            out = clause_scan.scan_items([{"id": "a", "query": "危大工程保障方案"}], long_text)
        self.assertTrue(out["a"]["answered"])
        self.assertIn("模型调用失败", out["a"]["reason"])

    def test_hit_in_any_chunk_marks_answered_with_excerpt(self) -> None:
        from app.engines import clause_scan

        with patch.object(clause_scan, "get_default_model_id", return_value="fake-model"), patch.object(
            clause_scan,
            "chat_complete",
            return_value='{"hits":[{"id":"a","excerpt":"本工程已制定危大工程保障方案","reason":"第三节已写明"}]}',
        ):
            out = clause_scan.scan_items([{"id": "a", "query": "危大工程保障方案"}], "投标书正文" * 50)
        self.assertTrue(out["a"]["answered"])
        self.assertEqual(out["a"]["excerpt"], "本工程已制定危大工程保障方案")

    def test_no_hit_after_full_read_is_confirmed_unanswered(self) -> None:
        from app.engines import clause_scan

        with patch.object(clause_scan, "get_default_model_id", return_value="fake-model"), patch.object(
            clause_scan, "chat_complete", return_value='{"hits":[]}'
        ):
            out = clause_scan.scan_items([{"id": "a", "query": "危大工程保障方案"}], "投标书正文" * 50)
        self.assertFalse(out["a"]["answered"])
        self.assertTrue(out["a"]["unanswered_confirmed"])


class TenderScoreScanTests(unittest.TestCase):
    """e_tender_score 打分证据接入同一次分块扫描：命中不再直接判未响应。"""

    def test_score_point_without_keyword_window_escalates_to_chunk_scan(self) -> None:
        from app.engines import e_tender_score

        score_rules = [
            {
                "dimension": "危大工程保障方案",
                "detail": "危大工程保障方案（7分）",
                "weight": 7,
                "sourceItemId": "eval-tech",
            }
        ]
        with patch("app.engines.clause_scan.scan_items") as mock_scan, patch.object(
            e_tender_score, "get_default_model_id", side_effect=Exception("未配置模型")
        ):
            mock_scan.return_value = {
                "tr-1": {"answered": True, "excerpt": "本工程危大工程保障方案已在第五章详述", "reason": "已通读确认"}
            }
            result = e_tender_score.run(
                "投标书正文完全不含关键词，但第五章其实写了危大工程应对措施",
                score_rules=score_rules,
            )
        mock_scan.assert_called_once()
        items = [i for g in result["groups"] for i in g["items"]]
        self.assertEqual(len(items), 1)
        # 命中分块扫描后不再直接判「未响应」；因无可用模型评委无法打分，只能标记为
        # 「未能评审」等待人工复核，而不是错误地扣成「未响应」。
        self.assertEqual(items[0]["status"], "未能评审")

    def test_score_point_confirmed_unanswered_after_scan_stays_unanswered(self) -> None:
        from app.engines import e_tender_score

        score_rules = [
            {
                "dimension": "危大工程保障方案",
                "detail": "危大工程保障方案（7分）",
                "weight": 7,
                "sourceItemId": "eval-tech",
            }
        ]
        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {
                "tr-1": {"answered": False, "excerpt": "", "reason": "通读未找到", "unanswered_confirmed": True}
            }
            result = e_tender_score.run(
                "投标书正文完全不含关键词",
                score_rules=score_rules,
            )
        items = [i for g in result["groups"] for i in g["items"]]
        self.assertEqual(items[0]["status"], "未响应")


class CustomRulesScanTests(unittest.TestCase):
    """e_custom_rules 自定义规则接入 check_clauses_batch：空候选升级分块扫描。"""

    def test_custom_rule_without_candidates_escalates_and_can_be_answered(self) -> None:
        from app.engines.e_custom_rules import run as custom_rules_run

        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {"0": {"answered": True, "excerpt": "已在附件中提供", "reason": "已通读确认"}}
            result = custom_rules_run(
                "投标书正文与规则关键词完全不重合",
                None,
                [{"id": "cr-1", "title": "特殊材料证明", "content": "须提供特殊材料的第三方检测报告原件"}],
            )
        mock_scan.assert_called_once()
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["items"][0]["status"], "已响应")

    def test_custom_rule_confirmed_unanswered_produces_finding(self) -> None:
        from app.engines.e_custom_rules import run as custom_rules_run

        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {
                "0": {"answered": False, "excerpt": "", "reason": "通读未找到", "unanswered_confirmed": True}
            }
            result = custom_rules_run(
                "投标书正文与规则关键词完全不重合",
                None,
                [{"id": "cr-1", "title": "特殊材料证明", "content": "须提供特殊材料的第三方检测报告原件"}],
            )
        self.assertEqual(len(result["findings"]), 1)
        self.assertTrue(result["findings"][0]["unansweredConfirmed"])
        self.assertEqual(result["items"][0]["status"], "未响应")


class ChunkTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self) -> None:
        chunks = _split_chunks("短文")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "短文")

    def test_long_text_covers_all_characters(self) -> None:
        blob = ("章节\n" + "正文" * 5000) * 8
        chunks = _split_chunks(blob)
        self.assertGreater(len(chunks), 4)
        joined = "\n".join(c["text"] for c in chunks)
        self.assertGreaterEqual(len(joined.replace("\n", "")), len(blob.replace("\n", "")) - 50)

    def test_prefers_chapter_breaks(self) -> None:
        chapter = "第一章 施工组织\n" + ("措施。" * 4000) + "\n第二章 质量保证\n" + ("验收。" * 4000)
        chunks = _split_chunks(chapter)
        self.assertGreaterEqual(len(chunks), 2)
        headings = " ".join(c["heading"] for c in chunks)
        self.assertTrue("第一章" in headings or "第二章" in headings)

    def test_chunk_size_stays_bounded(self) -> None:
        blob = "正文" * 20000
        chunks = _split_chunks(blob)
        for chunk in chunks[:-1]:
            self.assertLessEqual(len(chunk["text"]), CHUNK_CHARS + 100)

    def test_review_cap_is_about_300k(self) -> None:
        blob = ("章节标题足够长但不是标题\n" + "正文内容" * 8000) * 12
        chunks = _split_chunks(blob)
        total = sum(len(c["text"]) for c in chunks)
        self.assertLessEqual(len(chunks), 19)
        self.assertLessEqual(total, MAX_REVIEW_CHARS + 500)
        self.assertGreater(total, MAX_REVIEW_CHARS * 0.8)


class WritebackTests(unittest.TestCase):
    def test_writeback_replaces_text_keeps_bold(self) -> None:
        document = docx.Document()
        para = document.add_paragraph()
        run = para.add_run("甲方承诺投标有效期90天")
        run.bold = True
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "src.docx")
            document.save(path)
            out = writeback_docx(path, [{"type": "paragraph", "text": "甲方承诺投标有效期120天"}])
        loaded = docx.Document(io.BytesIO(out))
        para = next(p for p in loaded.paragraphs if "120" in (p.text or ""))
        self.assertIn("120", para.text)
        self.assertTrue(any(run.bold for run in para.runs))


class ReviewExportTests(unittest.TestCase):
    def test_report_docx_contains_score_and_issues(self) -> None:
        from app.engines.review_export import review_run_to_docx

        blob = review_run_to_docx(
            project_name="华北演示",
            project_code="HB-001",
            round_no=3,
            overall=82.5,
            light="橙",
            waste=1,
            risk=4,
            suggest=2,
            levels=[{"key": "L1", "name": "一票否决扫描", "score": 90, "issues": 1, "status": "风险", "desc": "否决项"}],
            dimensions=[{"name": "完整性", "weight": 20, "score": 80}],
            issues=[
                {
                    "severity": "废标",
                    "rule": "未盖公章",
                    "level": "L1",
                    "location": "封面",
                    "excerpt": "投标函未加盖公章",
                    "tenderQuote": "投标文件须加盖公章",
                    "suggestion": "在投标函落款处加盖公章",
                }
            ],
        )
        loaded = docx.Document(io.BytesIO(blob))
        text = "\n".join(p.text for p in loaded.paragraphs)
        self.assertTrue("预审报告" in text)
        self.assertIn("82.5", text)
        self.assertIn("未盖公章", text)
        self.assertIn("投标函未加盖公章", text)
        self.assertIn("自定义规则对照", text)


class ComposeTableMigrateTests(unittest.TestCase):
    def test_old_compose_blob_splits_into_file_rows(self) -> None:
        from app.engines.parse_schema import derive_engine_fields, merge_tree

        stored = [
            {
                "key": "bidReq",
                "items": [
                    {
                        "id": "req-compose",
                        "sections": [
                            {
                                "id": "rq-2",
                                "rows": [
                                    {
                                        "label": "投标文件组成清单（文件名/格式/是否必须/备注）",
                                        "content": (
                                            "投标函及投标函附录 / 按第八章格式填写 / 是 / 加盖公章\n"
                                            "施工组织设计 / 暗标总页数不超过400页 / 是 / 不得出现投标人身份"
                                        ),
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        tree = merge_tree(stored, "工程类")
        item = next(
            i for d in tree for i in d["items"] if i["id"] == "req-compose"
        )
        by = {row["label"]: row["content"] for row in item["sections"][0]["rows"]}
        self.assertIn("投标函及投标函附录", by["文件名称"])
        self.assertIn("施工组织设计", by["文件名称"])
        self.assertEqual(by["是否必须"].split("\n"), ["是", "是"])
        derived = derive_engine_fields(tree, "工程类")
        titles = [x["title"] for x in derived["formatRequirements"]]
        self.assertIn("投标函及投标函附录", titles)
        self.assertIn("施工组织设计", titles)


class DistillDisplayTests(unittest.TestCase):
    def test_clause_dump_is_distilled_and_original_kept_for_ruler(self) -> None:
        from app.engines.parse_schema import (
            derive_engine_fields,
            distill_display,
            empty_tree,
            ensure_originals,
            merge_tree,
        )

        blob = (
            "投标人应当具备市政公用工程施工总承包一级及以上资质。"
            "投标人必须提供有效的安全生产许可证，否则按废标处理。详见招标文件。"
        )
        tree = empty_tree("工程类")
        row = next(
            r
            for dim in tree
            for item in dim["items"]
            if item["id"] == "qual-license"
            for sec in item["sections"]
            for r in sec["rows"]
        )
        row["content"] = blob
        ensure_originals(tree)
        engine = derive_engine_fields(tree, "工程类")
        distill_display(tree)
        self.assertEqual(row["original"], blob)
        self.assertNotEqual(row["content"].strip(), blob)
        self.assertNotIn("投标人应当", row["content"])
        self.assertIn("市政公用工程", row["content"])
        joined = " ".join(x["desc"] for x in engine["qualification"])
        self.assertIn("投标人应当", joined)

        stored = [
            {
                "key": "qualification",
                "items": [
                    {
                        "id": "qual-license",
                        "sections": [{"id": "ql-1", "rows": [{"label": row["label"], "content": blob}]}],
                    }
                ],
            }
        ]
        merged = merge_tree(stored, "工程类")
        merged_row = next(
            r
            for dim in merged
            for item in dim["items"]
            if item["id"] == "qual-license"
            for sec in item["sections"]
            for r in sec["rows"]
            if r["label"] == row["label"]
        )
        self.assertEqual(merged_row["original"], blob)
        self.assertNotEqual(merged_row["content"].strip(), blob)


if __name__ == "__main__":
    unittest.main()
