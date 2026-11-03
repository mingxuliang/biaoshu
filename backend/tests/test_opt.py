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

    def test_zero_weight_contract_clause_still_checked_for_coverage(self) -> None:
        """招标解析抽出的合同条款即使没有分值，也要进预审对照；未覆盖则出缺项。"""
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
                "投标书正文完全不提这件事",
                score_rules=[
                    {
                        "dimension": "专用合同条款（技术要求）",
                        "detail": "违约、索赔与工期奖罚：逾期竣工违约金的上限：合同价款的4%",
                        "weight": 0,
                        "sourceItemId": "contract-tech",
                    }
                ],
            )
        self.assertEqual(len(findings), 1)
        self.assertIn("专用合同条款", findings[0]["rule"])

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
        """合同条款进预审，但不把段落深处的违约金比例拆成假评分点。"""
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
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["coverOnly"])
        self.assertEqual(items[0]["maxScore"], 0.0)

    def test_expand_score_items_still_picks_up_score_near_head(self) -> None:
        """条目开头附近真的标了分值（如「XX方案（10分）」），仍要正常识别为评分点。"""
        from app.engines.e_tender_score import expand_score_items

        score_rules = [{"dimension": "施工方案", "detail": "总体部署与关键节点安排（10分）", "weight": 0}]
        items = expand_score_items(score_rules, None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["maxScore"], 10.0)

    def test_expand_score_items_keeps_contract_tech_as_single_cover_item(self) -> None:
        """专用合同条款要进招标规则预审；付款/质保金百分比不能被拆成多条假评分项。"""
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
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["coverOnly"])
        self.assertIn("预付款", items[0]["rule"])


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


class PriceRegexTests(unittest.TestCase):
    """报价/基准价正则要能抓到中文标书常见的「不带千分位逗号」大数字写法，
    不能只支持带逗号分组的写法（现实中很少见），否则报价超预算/恶意低价/报价偏离
    这几项检查会在多数真实标书上直接不触发。"""

    def test_e1_budget_cap_veto_fires_without_comma_separator(self) -> None:
        from app.engines.e1_veto import run as e1_run

        paragraphs = [{"index": 0, "text": "投标总价：120000万元，大写：壹拾贰亿元整。"}]
        findings = e1_run(paragraphs, {"budget_cap_wan": 100000}, [], None, None, None, None)
        self.assertTrue(any("预算上限" in (f.get("rule") or "") for f in findings))

    def test_e1_malicious_low_price_veto_fires_without_comma_separator(self) -> None:
        from app.engines.e1_veto import run as e1_run

        text = "投标总价：70000万元。评标基准价：100000万元。"
        paragraphs = [{"index": 0, "text": text}]
        findings = e1_run(paragraphs, {}, [], {"price_deviation_malicious": 20}, None, None, None)
        self.assertTrue(any("恶意低价" in (f.get("rule") or "") for f in findings))

    def test_e2_price_deviation_fires_without_comma_separator(self) -> None:
        from app.engines.e2_business import run as e2_run

        text = "投标总价：85000万元。评标基准价：100000万元。"
        paragraphs = [{"index": 0, "text": text}]
        findings = e2_run(paragraphs, {}, None, [], None, None, None, None, {"price_deviation"})
        self.assertTrue(any("报价偏离" in (f.get("rule") or "") for f in findings))


class DataLoopWindowTests(unittest.TestCase):
    """高峰人数×宿舍/临建面积人均验算：两个数字必须出现在同一小窗口附近才能配对，
    不能在全文里各自 search 第一个命中就相除——不同章节的数字很可能说的不是同一件事，
    强行配对会把毫不相关的数字凑成一条假的「人均不足4㎡」扣分。"""

    def test_unrelated_numbers_in_far_apart_sections_do_not_pair(self) -> None:
        from app.engines.e2_business import run as e2_run

        paragraphs = [
            {"index": 0, "text": "1标段高峰人数30人，负责基础阶段施工。"},
        ] + [
            {"index": i, "text": f"第{i}节 无关内容 填充填充填充填充。"} for i in range(1, 20)
        ] + [
            {"index": 20, "text": "全场地临建总面积2000平方米，供全部标段共用。"},
        ]
        findings = e2_run(paragraphs, {}, None, [], None, None, None, {"data_loop"}, None)
        self.assertFalse(any("人均" in (f.get("suggestion") or "") for f in findings))

    def test_numbers_in_same_window_still_pair_and_flag(self) -> None:
        from app.engines.e2_business import run as e2_run

        paragraphs = [
            {"index": 0, "text": "高峰人数200人，集中安排住宿。"},
            {"index": 1, "text": "宿舍临建面积600平方米，满足基本住宿需求。"},
        ]
        findings = e2_run(paragraphs, {}, None, [], None, None, None, {"data_loop"}, None)
        self.assertTrue(any("人均" in (f.get("suggestion") or "") for f in findings))


class TextboxExtractionTests(unittest.TestCase):
    """word 文本框（形状/SmartArt）里的文字要能被抽取到，不能整段丢失。

    python-docx 的 paragraph.text 不含文本框内容；投标书封面、施组流程图、组织架构图
    常把关键说明文字放在文本框里，抽不到会导致引擎判断时看不到这段文字，误判成「未响应」。
    """

    def _make_docx_with_textbox(self, tmp_dir: str, textbox_text: str) -> str:
        from docx.oxml import OxmlElement

        document = docx.Document()
        document.add_paragraph("正文第一段，不在文本框里。")
        p = document.add_paragraph()
        run = p.add_run()
        drawing = OxmlElement("w:drawing")
        txbx = OxmlElement("w:txbxContent")
        inner_p = OxmlElement("w:p")
        inner_r = OxmlElement("w:r")
        inner_t = OxmlElement("w:t")
        inner_t.text = textbox_text
        inner_r.append(inner_t)
        inner_p.append(inner_r)
        txbx.append(inner_p)
        drawing.append(txbx)
        run._r.append(drawing)
        path = str(Path(tmp_dir) / "textbox.docx")
        document.save(path)
        return path

    def test_textbox_texts_extracts_raw_strings(self) -> None:
        from app.engines.docx_extract import textbox_texts

        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_docx_with_textbox(tmp, "临近周边住宅区文明施工保障措施：夜间22点后停止施工。")
            texts = textbox_texts(docx.Document(path))
        self.assertTrue(any("夜间22点后停止施工" in t for t in texts))

    def test_extract_paragraphs_includes_textbox_text(self) -> None:
        from app.engines.docx_extract import extract_paragraphs

        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_docx_with_textbox(tmp, "文本框专项说明：设置隔音屏障降噪。")
            paras = extract_paragraphs(path)
        self.assertTrue(any("设置隔音屏障降噪" in (p.get("text") or "") for p in paras))

    def test_extract_review_pack_includes_textbox_text(self) -> None:
        from app.engines.bid_media import _extract_docx_pack

        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_docx_with_textbox(tmp, "文本框专项说明：设置隔音屏障降噪。")
            pack = _extract_docx_pack(path)
        self.assertTrue(any("设置隔音屏障降噪" in (p.get("text") or "") for p in pack["paragraphs"]))


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
    def test_report_docx_contains_grade_and_issues(self) -> None:
        from app.engines.review_export import review_run_to_docx

        blob = review_run_to_docx(
            project_name="华北演示",
            project_code="HB-001",
            round_no=3,
            light="橙",
            waste=1,
            risk=4,
            suggest=2,
            levels=[{"key": "L1", "name": "一票否决扫描", "grade": "B", "issues": 1, "status": "风险", "desc": "否决项"}],
            dimensions=[{"name": "完整性", "weight": 20, "grade": "B"}],
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
        self.assertIn("等级 B", text)
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


class GradeScoreRemovalTests(unittest.TestCase):
    """去分数化：AI 预审报告自己的各项指标改用 A/B/C/D 等级 + 严重度直推，
    不再做加权求和/扣分算术（模拟评委打分 e_tender_score 不在此范围，继续用数字）。"""

    def test_grade_from_findings_worst_severity_wins(self) -> None:
        from app.engines.rules_data import grade_from_findings

        self.assertEqual(grade_from_findings([]), "A")
        self.assertEqual(grade_from_findings([{"severity": "建议"}]), "A")
        self.assertEqual(grade_from_findings([{"severity": "扣分"}]), "B")
        self.assertEqual(grade_from_findings([{"severity": "降档"}, {"severity": "扣分"}]), "C")
        self.assertEqual(grade_from_findings([{"severity": "废标"}, {"severity": "建议"}]), "D")

    def test_worst_grade_picks_lowest(self) -> None:
        from app.engines.rules_data import worst_grade

        self.assertEqual(worst_grade(["A", "B", "A"]), "B")
        self.assertEqual(worst_grade(["A", "D", "C"]), "D")
        self.assertEqual(worst_grade([]), "A")

    def test_status_from_grade_mapping(self) -> None:
        from app.engines.orchestrator import _status_from_grade

        self.assertEqual(_status_from_grade("A"), "通过")
        self.assertEqual(_status_from_grade("B"), "通过")
        self.assertEqual(_status_from_grade("C"), "风险")
        self.assertEqual(_status_from_grade("D"), "未达标")

    def test_e3_semantic_merge_chunk_results_takes_worst_grade_not_average(self) -> None:
        """五维评审跨分块合并：任一分块把某维评到 D，全书这一维就是 D，不能被其它分块稀释。"""
        from app.engines.e3_semantic import _merge_chunk_results

        results = [
            {"dimensions": {"completeness": {"grade": "A", "reason": "第一段没问题"}}, "issues": []},
            {"dimensions": {"completeness": {"grade": "D", "reason": "第二段严重缺项"}}, "issues": []},
            {"dimensions": {"completeness": {"grade": "B", "reason": "第三段有点小问题"}}, "issues": []},
        ]
        merged = _merge_chunk_results(results, [100, 100, 100], {"completeness": 30})
        self.assertEqual(merged["dimensions"]["completeness"]["grade"], "D")

    def test_e3_semantic_normalize_defaults_invalid_grade_to_neutral(self) -> None:
        from app.engines.e3_semantic import _normalize

        out = _normalize({"dimensions": {"completeness": {"reason": "模型没给等级"}}}, {"completeness": 30})
        self.assertEqual(out["dimensions"]["completeness"]["grade"], "C")

    def test_tech_module_entry_grade_from_severity(self) -> None:
        from app.engines.e3_tech_modules import _module_entry

        ok = _module_entry("org_outline", None)
        self.assertEqual(ok["grade"], "A")
        self.assertNotIn("score", ok)
        self.assertNotIn("maxScore", ok)

        bad = _module_entry(
            "org_outline",
            {"severity": "扣分", "suggestion": "补开篇", "rule": "T01", "excerpt": ""},
        )
        self.assertEqual(bad["grade"], "B")

    def test_booklet_grade_takes_worst_across_levels(self) -> None:
        from app.engines.bid_kind import booklet_grade

        levels = [
            {"key": "L1", "grade": "A"},
            {"key": "L2", "grade": "C"},
        ]
        self.assertEqual(booklet_grade(levels, "business"), "C")


if __name__ == "__main__":
    unittest.main()
