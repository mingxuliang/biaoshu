"""输入闸门 / 有据预审 的轻量单测，不依赖数据库与大模型。"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from app.engines.clause_cover import lexical_covered
from app.engines.e1_veto import run as e1_run
from app.engines.e3_semantic import _normalize
from app.engines.e_parse_match import _unanswered
from app.engines.extract_quality import MIN_MAIN_HANZI, merge_stats, parse_fail_reason, usable_hanzi
from app.engines.orchestrator import _admit_findings
from app.engines.tender_package import extract_file_bundle


class ExtractQualityTests(unittest.TestCase):
    def test_placeholder_is_not_usable(self) -> None:
        self.assertEqual(usable_hanzi("已上传「包.zip」，该格式仅存档，未能抽取正文。"), 0)

    def test_empty_hanzi_fails_parse(self) -> None:
        reason = parse_fail_reason({"usableHanzi": 12, "errors": []}, filled=0)
        self.assertIsNotNone(reason)
        self.assertIn(str(MIN_MAIN_HANZI), reason or "")

    def test_enough_hanzi_ok(self) -> None:
        self.assertIsNone(parse_fail_reason({"usableHanzi": 1200, "errors": []}, filled=3))


class ArchiveExtractTests(unittest.TestCase):
    def test_zip_inner_txt_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, "pack.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("招标正文.txt", "投标人须知第一章评标办法详细评审标准" * 20)
            bundle = extract_file_bundle(zpath, kind="main", filename="pack.zip")
            self.assertGreater(usable_hanzi(bundle["text"]), 80)
            self.assertGreaterEqual(int((bundle["stats"] or {}).get("unpackedFiles") or 0), 1)

    def test_zip_inner_docx_extracted(self) -> None:
        import docx

        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "正文.docx")
            document = docx.Document()
            document.add_paragraph("投标人须知前附表评标办法详细评审标准施工组织设计" * 15)
            document.save(inner)
            zpath = os.path.join(tmp, "pack.zip")
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.write(inner, "招标正文.docx")
            bundle = extract_file_bundle(zpath, kind="main", filename="pack.zip")
            self.assertGreater(usable_hanzi(bundle["text"]), 80)

    def test_empty_pdf_fails_parse_gate(self) -> None:
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("pymupdf 未安装")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "blank.pdf")
            doc = fitz.open()
            doc.new_page()
            doc.save(path)
            doc.close()
            bundle = extract_file_bundle(path, kind="main", filename="blank.pdf")
            stats = merge_stats([{"kind": "main", "text": bundle["text"], "stats": bundle["stats"]}])
            self.assertLess(int(stats.get("usableHanzi") or 0), MIN_MAIN_HANZI)
            self.assertIsNotNone(parse_fail_reason(stats, filled=0))

    def test_scan_placeholder_cannot_lock(self) -> None:
        stats = merge_stats(
            [{"kind": "main", "text": "未识别到文字", "stats": {"ocrPages": 3, "error": "扫描件未识别到文字。"}}]
        )
        self.assertEqual(int(stats.get("usableHanzi") or 0), 0)
        self.assertIsNotNone(parse_fail_reason(stats, filled=2))


class ClauseCoverTests(unittest.TestCase):
    def test_synonym_long_window_is_covered(self) -> None:
        clause = "投标人必须提交有效营业执照副本扫描件"
        bid = "本公司现附有效营业执照副本扫描件及资质证书"
        self.assertTrue(lexical_covered(clause, bid, "营业执照"))

    def test_heading_only_is_not_covered(self) -> None:
        self.assertTrue(
            _unanswered(
                "施工进度计划应明确关键节点与工期保证措施",
                "正文未展开细节",
                "进度计划",
                "第一章 进度计划\n第二章 质量保证",
            )
        )


class EvidenceGateTests(unittest.TestCase):
    def test_score_without_excerpt_dropped(self) -> None:
        kept = _admit_findings(
            [
                {
                    "engine": "e3_semantic",
                    "level": "L3",
                    "severity": "扣分",
                    "location": "施工组织",
                    "excerpt": "模型编造的句子并不在标书里",
                    "rule": "五维语义",
                    "suggestion": "加强针对性",
                }
            ],
            "投标文件正文只有工期安排和安全措施。",
        )
        self.assertEqual(kept, [])

    def test_unanswered_with_quote_kept(self) -> None:
        kept = _admit_findings(
            [
                {
                    "engine": "e_parse_match",
                    "level": "L1",
                    "severity": "降档",
                    "location": "实质性条款",
                    "excerpt": "",
                    "rule": "须响应",
                    "tenderQuote": "投标有效期不少于 90 日历天",
                    "suggestion": "未确认",
                    "unansweredConfirmed": True,
                }
            ],
            "投标文件正文只有工期安排。",
        )
        self.assertEqual(len(kept), 1)

    def test_e3_normalize_drops_unsnapped(self) -> None:
        data = {
            "dimensions": {"completeness": {"score": 80, "reason": "ok"}},
            "issues": [{"severity": "扣分", "location": "章", "excerpt": "并不存在的摘句", "suggestion": "x"}],
        }
        out = _normalize(data, {"completeness": 100}, "本章只写了进度计划和质量保证体系。")
        self.assertEqual(out["issues"], [])

    def test_e3_normalize_drops_vague_suggestion(self) -> None:
        data = {
            "dimensions": {"completeness": {"score": 80, "reason": "ok"}},
            "issues": [
                {
                    "severity": "建议",
                    "location": "章",
                    "excerpt": "本章只写了进度计划和质量保证体系。",
                    "suggestion": "建议加强针对性",
                }
            ],
        }
        out = _normalize(data, {"completeness": 100}, "本章只写了进度计划和质量保证体系。")
        self.assertEqual(out["issues"], [])

    def test_low_confidence_veto_dropped(self) -> None:
        kept = _admit_findings(
            [
                {
                    "engine": "e3_semantic",
                    "level": "L3",
                    "severity": "降档",
                    "location": "施工组织",
                    "excerpt": "本章只写了进度计划和质量保证体系。",
                    "rule": "五维语义",
                    "suggestion": "补网络图",
                    "confidence": 0.2,
                }
            ],
            "本章只写了进度计划和质量保证体系。",
        )
        self.assertEqual(kept, [])


class TenderScoreTests(unittest.TestCase):
    def test_no_window_is_unanswered(self) -> None:
        from unittest.mock import patch

        from app.engines.e_tender_score import run as score_run

        # 关键词窗口检索找不到候选时会升级到 clause_scan 分块通读；这里模拟通读全文后
        # 仍确认未响应（而不是真的打模型接口），验证「确认未响应」这一路径的分数/状态。
        with patch("app.engines.clause_scan.scan_items") as mock_scan:
            mock_scan.return_value = {
                "tr-1": {
                    "answered": False,
                    "excerpt": "",
                    "reason": "对照本项招标要求，投标书中未见相应的实质性响应内容。",
                    "unanswered_confirmed": True,
                }
            }
            out = score_run(
                "本公司承诺依法投标并加盖公章。",
                [
                    {
                        "dimension": "施工组织",
                        "detail": "关键线路网络图（8分）须附横道图与工期保证措施",
                        "weight": 8,
                        "sourceItemId": "eval-tech",
                    }
                ],
                None,
                headings=["投标函"],
                paragraphs=[{"text": "本公司承诺依法投标并加盖公章。", "isHeading": False}],
            )
        items = [it for g in (out.get("groups") or []) for it in (g.get("items") or [])]
        self.assertTrue(items)
        self.assertTrue(
            all(it.get("status") == "未响应" and float(it.get("score") or 0) == 0 for it in items if it.get("status") != "公式项")
        )


class LocateNeedleTests(unittest.TestCase):
    def test_needles_keep_project_name(self) -> None:
        from app.engines.tender_locate import compact, needles

        keys = needles("滨湖新区环卫基地项目（招标项目名称：滨湖新区环卫基地1号施工）")
        blob = "".join(compact(k) for k in keys)
        self.assertIn("滨湖新区环卫基地", blob)

    def test_needles_strip_parenthetical_and_keep_label(self) -> None:
        from app.engines.tender_locate import compact, needles, _plain_value

        self.assertEqual(_plain_value("滨湖新区环卫基地项目（招标项目名称：其他）"), "滨湖新区环卫基地项目")
        keys = needles("滨湖新区环卫基地项目（招标项目名称：其他）", "项目名称")
        blob = "".join(compact(k) for k in keys)
        self.assertIn("项目名称", blob)
        self.assertNotIn("招标项目名称其他", blob)

    def test_placeholder_has_no_needles(self) -> None:
        from app.engines.tender_locate import needles

        self.assertEqual(needles("未从招标文件中抽取到该项内容"), [])

    def test_clause_line_outscores_cover(self) -> None:
        from app.engines.tender_locate import _score_line, compact, needles

        query = "滨湖新区环卫基地项目（招标项目名称：滨湖新区环卫电施工）"
        keys = needles(query, "项目名称")
        label_c = compact("项目名称")
        value_c = compact("滨湖新区环卫基地项目")
        cover = {"text": "滨湖新区环卫基地工程施工", "compact": compact("滨湖新区环卫基地工程施工")}
        clause = {"text": "1.1 项目名称：滨湖新区环卫基地项目", "compact": compact("1.1 项目名称：滨湖新区环卫基地项目")}
        self.assertGreater(
            _score_line(clause, keys, label_c, value_c),
            _score_line(cover, keys, label_c, value_c),
        )

    def test_locate_pdf_highlights_clause_line(self) -> None:
        import os
        import tempfile

        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("pymupdf not installed")
        font = next(
            (
                p
                for p in (
                    r"C:\Windows\Fonts\msyh.ttc",
                    r"C:\Windows\Fonts\simsun.ttc",
                    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                )
                if os.path.exists(p)
            ),
            "",
        )
        if not font:
            self.skipTest("no CJK font for PDF locate test")
        from app.engines.tender_locate import locate_in_pdf

        doc = fitz.open()
        page = doc.new_page()
        page.insert_font(fontname="cjk", fontfile=font)
        page.insert_text((72, 72), "第一章 招标公告", fontname="cjk", fontsize=14)
        page.insert_text((72, 108), "1.1 项目名称：滨湖新区环卫基地项目", fontname="cjk", fontsize=12)
        page.insert_text((72, 144), "滨湖新区环卫基地工程施工", fontname="cjk", fontsize=12)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            path = tmp.name
        try:
            doc.save(path)
            doc.close()
            hit = locate_in_pdf(path, "滨湖新区环卫基地项目（招标项目名称：滨湖新区环卫电施工）", "项目名称")
            self.assertTrue(hit["found"])
            self.assertTrue(hit["rects"])
            self.assertIn("项目名称", hit["snippet"])
            self.assertLess(hit["rects"][0]["h"], 0.12)
        finally:
            os.unlink(path)


class CollusionTests(unittest.TestCase):
    def test_same_md5_emits_finding(self) -> None:
        ctx = SimpleNamespace(
            tender_text="",
            quals=[],
            other_project_names=[],
            project_name="当前项目",
            current_hash="deadbeef",
            other_file_hashes=[("历史项目", "deadbeef")],
            other_sentences=[],
        )
        findings = e1_run([], {}, [], None, ctx, {"collusion"}, None)
        self.assertTrue(any("哈希" in (f.get("rule") or "") for f in findings))


class CustomRulesReviewTests(unittest.TestCase):
    def test_answered_rule_is_listed_even_without_finding(self) -> None:
        from app.engines import e_custom_rules

        bid = "投标有效期不少于九十天，本投标文件承诺投标有效期一百二十天。"
        pack = e_custom_rules.run(
            bid,
            [{"text": bid}],
            [
                {
                    "id": "r1",
                    "title": "投标有效期",
                    "content": "投标有效期不少于九十天",
                    "severity": "扣分",
                    "source": "tender",
                    "enabled": True,
                }
            ],
            scope="business",
        )
        self.assertEqual(pack["items"][0]["status"], "已响应")
        self.assertEqual(pack["items"][0]["title"], "投标有效期")
        self.assertEqual(pack["findings"], [])

    def test_unanswered_deduct_maps_to_business_l2(self) -> None:
        from app.engines import e_custom_rules
        from app.engines import clause_cover
        from app.engines.clause_cover import CoverResult

        def fake_check_batch(items, **_kw):
            return {
                str(it.get("id") or i): CoverResult(answered=False, reason="未覆盖", excerpt="", unanswered_confirmed=True)
                for i, it in enumerate(items)
            }

        saved = clause_cover.check_clauses_batch
        clause_cover.check_clauses_batch = fake_check_batch
        try:
            pack = e_custom_rules.run(
                "无关正文",
                [{"text": "无关正文"}],
                [{"id": "r2", "title": "ISO证书", "content": "必须提供ISO27001信息安全认证证书", "severity": "扣分", "source": "tender"}],
                scope="business",
            )
        finally:
            clause_cover.check_clauses_batch = saved
        self.assertEqual(pack["items"][0]["status"], "未响应")
        self.assertEqual(pack["findings"][0]["level"], "L2")
        self.assertEqual(pack["findings"][0]["severity"], "扣分")


if __name__ == "__main__":
    unittest.main()
