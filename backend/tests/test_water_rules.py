"""水利规则合成、图纸事实和清单特征。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.engines.drawing_derive import derive_rules
from app.engines.drawing_facts import classify_sheet, facts_from_text, keep_grounded, regions_from_blocks
from app.engines.project_rules import compose_project_rules
from app.engines.rules_data import rule_scope
from app.engines.standard_ingest import (
    annotate_clauses,
    detect_specialty,
    extract_pdf_in_batches,
    looks_like_standard_filename,
    parse_standard_code,
    split_clauses,
)
from app.engines.standard_review import select_clauses
from app.engines.tender_package import extract_boq_items


class DrawingFactTests(unittest.TestCase):
    def test_classify_and_ground(self):
        self.assertEqual(classify_sheet("渠道配筋图"), "配筋图")
        page = "基坑开挖深度 6.5m，混凝土 C30"
        facts = facts_from_text(page, title="结构图")
        self.assertTrue(any(item["field"] == "开挖深度" for item in facts))
        self.assertEqual(keep_grounded([{"value": "C30", "evidence": "没有"}, {"value": "C50", "evidence": "不存在"}], page)[0]["value"], "C30")
        self.assertEqual(keep_grounded([{"value": "C80", "evidence": "别处"}], page), [])

    def test_derive_thresholds(self):
        rules = derive_rules(
            [
                {"field": "开挖深度", "value": "6m", "object": "泵站", "evidence": "基坑开挖 6m"},
                {"field": "导流", "value": "围堰", "object": "导流", "evidence": "围堰"},
                {"field": "混凝土强度", "value": "C30", "object": "渠道混凝土", "evidence": "C30"},
            ],
            "水利",
        )
        by_title = {row["title"]: row for row in rules}
        self.assertIn("超危大基坑", by_title)
        self.assertIn("SL 721", by_title["超危大基坑"]["requirement"])
        self.assertEqual(by_title["混凝土不低于 C30"]["checkType"], "参数一致")
        self.assertIn("导流与度汛", by_title)
        shallow = derive_rules([{"field": "开挖深度", "value": "3m", "evidence": "基坑开挖 3m"}], "水利")
        self.assertEqual(shallow[0]["title"], "危大基坑")
        self.assertNotIn("超危大", shallow[0]["title"])
        none = derive_rules([{"field": "开挖深度", "value": "2.9m", "evidence": "基坑开挖 2.9m"}], "水利")
        self.assertEqual(none, [])


class ProjectRuleTests(unittest.TestCase):
    def test_pool_only_for_water_and_suggestion_stays_soft(self):
        water = compose_project_rules(
            tech_rules=[{"factor": "施工导流", "mustWrite": "写明导流标准、围堰和度汛"}],
            boq_rows=[{"name": "渠道混凝土", "feature": "C30 抗渗 W6", "qty": "74.88", "unit": "m3"}],
            specialty="水利",
        )
        self.assertTrue(any(row["source"] == "规则池" and row["severity"] == "废标" for row in water))
        cure = next(row for row in water if "养护" in row["title"] or row["severity"] == "建议")
        self.assertEqual(cure["checkType"], "建议")
        self.assertEqual(cure["severity"], "建议")
        balance = next(row for row in water if row["title"] == "土石方平衡")
        self.assertEqual(balance["checkType"], "量与资源一致")
        other = compose_project_rules(specialty="房建")
        self.assertFalse(any(row["source"] == "规则池" for row in other))


class BoqFeatureTests(unittest.TestCase):
    def test_xlsx_code_and_feature(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl 未安装")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "boq.xlsx"
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.append(["项目编码", "项目名称", "项目特征", "计量单位", "工程数量"])
            sheet.append(["0101", "渠道混凝土", "C30 抗渗 W6", "m3", "74.88"])
            book.save(path)
            rows = extract_boq_items(str(path))
        self.assertEqual(rows[0]["code"], "0101")
        self.assertIn("C30", rows[0]["feature"])
        self.assertEqual(rows[0]["qty"], "74.88")


class ScopeAndClauseTests(unittest.TestCase):
    def test_filename_codes(self):
        self.assertEqual(parse_standard_code("SLT+223-2025+水利水电建设工程验收规程.pdf"), "SL/T223-2025")
        self.assertEqual(parse_standard_code("GB∕T 51280-2018 工程泥沙设计标准.pdf"), "GB/T51280-2018")

    def test_safety_items_are_building_only(self):
        scope = rule_scope("safety")
        self.assertIn("水利", scope["specialties"])
        self.assertEqual(scope["itemSpecialties"]["扬尘六个 100%"], ["房建", "市政"])
        self.assertEqual(rule_scope("quality")["specialties"], ["通用"])

    def test_regions_merge_nearby_blocks(self):
        regions = regions_from_blocks(
            [
                {"text": "渠身混凝土", "bbox": (0, 0, 100, 20), "kind": "视图"},
                {"text": "强度 C25", "bbox": (0, 24, 100, 40), "kind": "视图"},
                {"text": "钢筋表\n1\n2\n3\n4", "bbox": (0, 200, 100, 260), "kind": "表格"},
            ]
        )
        self.assertEqual(len(regions), 2)
        self.assertIn("C25", regions[0]["text"])

    def test_commentary_and_mandatory(self):
        text = "强制性条文 3.1.2、4.2.1\n1 总则\n3.1.2 导流标准应符合要求。\n条文说明\n3.1.2 本条说明导流。"
        pieces = annotate_clauses(split_clauses(text), text)
        by_no = {}
        for piece in pieces:
            by_no.setdefault(piece["clause_no"], []).append(piece)
        self.assertTrue(any(item["mandatory"] for item in by_no["3.1.2"]))
        self.assertTrue(any(item["is_commentary"] for item in by_no["3.1.2"]))

    def test_code_outranks_generic_words(self):
        rows = [
            {"code": "GB 50010-2010", "clause_no": "1", "text": "混凝土验收", "specialty": "通用"},
            {"code": "SL/T 223-2025", "clause_no": "3.1.2", "text": "验收", "specialty": "水利"},
        ]
        hits = select_clauses(rows, "核对 SL/T 223-2025 验收", "水利", limit=1)
        self.assertEqual(hits[0]["code"], "SL/T 223-2025")

    def test_topic_outranks_same_word(self):
        rows = [
            {"code": "SL 303", "clause_no": "1.1", "text": "导流说明", "specialty": "水利"},
            {"code": "SL 303", "clause_no": "4.2", "text": "导流说明", "specialty": "水利", "topics": ["导流"]},
        ]
        hits = select_clauses(rows, "施工导流", "水利", limit=1)
        self.assertEqual(hits[0]["clauseNo"], "4.2")

    def test_text_layer_pdf_does_not_call_mineru(self):
        import pymupdf as fitz

        from app.engines import doc_parse

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "text.pdf"
            doc = fitz.open()
            page = doc.new_page()
            line = "导流围堰和度汛方案应当写明标准、时段和超标准洪水措施。"
            for index in range(4):
                page.insert_text((72, 72 + index * 28), line, fontname="china-s")
            doc.save(path)
            doc.close()
            with mock.patch.object(doc_parse, "mineru_markdown", side_effect=AssertionError("文字层不该走 MinerU")):
                text, note = extract_pdf_in_batches(str(path), batch_pages=1)
        self.assertIn("导流围堰", text)
        self.assertEqual(note, "")

    def test_scanned_pdf_uploads_whole_file(self):
        import pymupdf as fitz

        from app.engines import doc_parse

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(path)
            doc.close()
            body = "4.1.2 导流围堰和度汛方案应当写明标准、时段和超标准洪水措施。" * 4
            seen: list[int] = []

            def upload(pdf_bytes: bytes, filename: str = "", **kwargs: object) -> str:
                seen.append(len(pdf_bytes))
                self.assertTrue(filename.endswith("scan.pdf"))
                self.assertIn("on_ticket", kwargs)
                return body

            progress: list[tuple[int, int]] = []
            with mock.patch.object(doc_parse, "mineru_markdown", side_effect=upload), mock.patch.object(
                doc_parse, "read_scan_page", side_effect=AssertionError("扫描规范不该再逐页识图")
            ):
                text, note = extract_pdf_in_batches(str(path), batch_pages=1, on_progress=lambda done, total: progress.append((done, total)))
        self.assertIn("导流围堰", text)
        self.assertEqual(note, "")
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0], 100)
        self.assertEqual(progress, [(0, 0)])

    def test_mineru_ticket_is_reused(self):
        import json

        import pymupdf as fitz

        from app.engines import doc_parse

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(path)
            doc.close()
            body = "4.1.2 导流围堰和度汛方案应当写明标准、时段和超标准洪水措施。" * 4
            (Path(str(path) + ".batches.json")).write_text(
                json.dumps({"engine": "mineru", "request_id": "std-already"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(doc_parse, "mineru_fetch", return_value=body) as fetch, mock.patch.object(
                doc_parse, "mineru_markdown", side_effect=AssertionError("已有任务号不应重新上传")
            ):
                text, note = extract_pdf_in_batches(str(path), batch_pages=1)
        fetch.assert_called_once_with("std-already")
        self.assertIn("导流围堰", text)
        self.assertEqual(note, "")

    def test_old_vl_pages_are_not_kept(self):
        import json

        import pymupdf as fitz

        from app.engines import doc_parse

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(path)
            doc.close()
            (Path(str(path) + ".batches.json")).write_text(
                json.dumps({"engine": "vl", "next": 1, "parts": ["这段文字用于续跑测试并且不该保留。"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            body = "4.1.2 导流围堰和度汛方案应当写明标准、时段和超标准洪水措施。" * 4
            with mock.patch.object(doc_parse, "mineru_markdown", return_value=body):
                text, _note = extract_pdf_in_batches(str(path), batch_pages=1)
        self.assertIn("导流围堰", text)
        self.assertNotIn("续跑测试", text)

    def test_standard_filename_is_recognized_before_upload(self):
        self.assertTrue(looks_like_standard_filename("SL 775-2018 水工混凝土结构耐久性评定规范.pdf"))
        self.assertTrue(looks_like_standard_filename("GB／T 51280-2018 工程泥沙设计标准.pdf"))
        self.assertFalse(looks_like_standard_filename("店埠河治理工程技术标.pdf"))

    def test_empty_standard_is_not_called_a_corrupt_file(self):
        from app.engines.knowledge_ingest import _standard_failure_message

        self.assertNotIn("损坏", _standard_failure_message("未识别到条号"))
        self.assertIn("条号", _standard_failure_message("未识别到条号"))
        self.assertIn("损坏", _standard_failure_message("文档无法读取"))

    def test_dianbu_tender_is_water(self):
        pdf = Path(r"C:\Users\92109\Desktop\工程标文件") / "安徽省合肥市店埠河治理工程（肥东部分） 招标文件.pdf"
        if not pdf.exists():
            self.skipTest("店埠河招标文件不在本机")
        import pymupdf as fitz

        with fitz.open(pdf) as doc:
            text = "\n".join((page.get_text("text") or "") for page in doc)
        self.assertEqual(detect_specialty(f"店埠河治理\n{text[:60000]}"), "水利")


class MineruResultTests(unittest.TestCase):
    def test_v1_result_uses_markdown_not_task_id(self):
        from app.engines.doc_parse import _find_markdown

        payload = {
            "task_id": "task-765",
            "status": "completed",
            "files": [
                {
                    "name": "p1-3.pdf",
                    "status": "completed",
                    "output_files": {"markdown": {"file_id": "file-1", "bytes": 20}},
                    "content": {"markdown": "4.1.1 安全设施应与主体工程同时设计、同时施工、同时投入使用。"},
                }
            ],
        }
        text = _find_markdown(payload)
        self.assertIn("同时设计", text)
        self.assertNotIn("task-765", text)

    def test_whole_file_is_uploaded_not_inlined(self):
        from app.engines import doc_parse

        pdf = b"%PDF-1.4 whole book"
        settings = mock.Mock()
        settings.mineru_url = "http://mineru:8000"
        settings.mineru_backend = "pipeline"
        settings.mineru_timeout_sec = 30
        calls: list[tuple[str, dict]] = []

        def post(url: str, **kwargs: object):
            calls.append((url, kwargs))
            resp = mock.Mock()
            resp.headers = {"content-type": "application/json"}
            if "/v1/" not in url:
                resp.status_code = 404
                resp.text = "missing"
                resp.content = b""
                resp.json.side_effect = ValueError("not json")
                return resp
            resp.status_code = 200
            resp.text = ""
            resp.content = b"{}"
            resp.json.return_value = {"content": {"markdown": "4.1.2 导流围堰应当写明标准。"}}
            return resp

        with mock.patch.object(doc_parse, "get_settings", return_value=settings), mock.patch.object(
            doc_parse.httpx, "post", side_effect=post
        ):
            text = doc_parse.mineru_markdown(pdf, "SL775.pdf")
        self.assertIn("导流围堰", text)
        v1 = [item for item in calls if item[0].endswith("/v1/file_parse")]
        self.assertEqual(len(v1), 1)
        kwargs = v1[0][1]
        self.assertIsNone(kwargs.get("json"))
        uploaded = kwargs["files"]["files"]
        self.assertEqual(uploaded[1], pdf)
        self.assertEqual(uploaded[0], "SL775.pdf")
        params = dict(kwargs["params"])
        self.assertEqual(params["ocr_mode"], "ocr")
        self.assertNotIn("request_id", params)
        self.assertNotIn("inline", str(kwargs))

    def test_running_job_is_polled_by_server_task_id(self):
        from app.engines import doc_parse

        settings = mock.Mock()
        settings.mineru_url = "http://mineru:8000"
        settings.mineru_backend = "pipeline"
        settings.mineru_timeout_sec = 30
        tickets: list[str] = []

        def post(url: str, **kwargs: object):
            del kwargs
            resp = mock.Mock()
            resp.headers = {"content-type": "application/json"}
            if "/v1/" not in url:
                resp.status_code = 404
                resp.text = "missing"
                resp.content = b""
                resp.json.side_effect = ValueError("not json")
                return resp
            resp.status_code = 202
            resp.text = ""
            resp.content = b"{}"
            resp.json.return_value = {"status": "running", "task_id": "job-775"}
            return resp

        def get(url: str, **kwargs: object):
            del kwargs
            resp = mock.Mock()
            resp.headers = {"content-type": "application/json"}
            resp.status_code = 200 if url.endswith("/v1/tasks/job-775/result") else 404
            resp.text = ""
            resp.content = b"{}"
            if resp.status_code == 200:
                resp.json.return_value = {
                    "status": "completed",
                    "files": [{"content": {"markdown": "4.1.2 导流围堰应当写明标准、时段和超标准洪水措施。"}}],
                }
            else:
                resp.json.side_effect = ValueError("not json")
            return resp

        with mock.patch.object(doc_parse, "get_settings", return_value=settings), mock.patch.object(
            doc_parse.httpx, "post", side_effect=post
        ), mock.patch.object(doc_parse.httpx, "get", side_effect=get):
            text = doc_parse.mineru_markdown(b"%PDF-1.4", "SL775.pdf", on_ticket=tickets.append)
        self.assertEqual(tickets, ["job-775"])
        self.assertIn("导流围堰", text)


class ChapterBatchTests(unittest.TestCase):
    def test_later_chapter_is_not_cut_off(self):
        from app.engines.tech_rules import chapter_batches, extract_tech_rules

        corpus = ("甲" * 20000) + (
            "\n第一章 总则\n施工组织应写明总体安排和现场布置，这段文字单独成章。\n"
            "第二章 导流度汛\n导流围堰和度汛方案必须写明标准、时段和超标准洪水措施。\n"
        )
        batches = chapter_batches(corpus)
        self.assertTrue(any("导流度汛" in batch for batch in batches))
        seen: list[str] = []

        def complete(chunk: str) -> str:
            seen.append(chunk)
            if "导流度汛" in chunk:
                return '{"rules":[{"factor":"导流度汛","mustWrite":"写明导流标准和度汛措施","axis":"完整性"}]}'
            return '{"rules":[]}'

        pack = extract_tech_rules([], corpus, complete=complete)
        self.assertTrue(any("导流度汛" in chunk for chunk in seen))
        self.assertEqual(pack["rules"][0]["factor"], "导流度汛")


class LaborScheduleTests(unittest.TestCase):
    def test_mandays_over_peak_times_duration(self):
        from app.engines.e_qty_logic import check_labor_schedule

        over = check_labor_schedule("工期 100 日历天。高峰人数 20 人。总工日 3000")
        self.assertEqual(len(over), 1)
        self.assertEqual(check_labor_schedule("工期 100 日历天。高峰人数 40 人。总工日 3000"), [])


class CitedStandardTests(unittest.TestCase):
    def test_replaced_catalog_is_flagged(self):
        from unittest.mock import patch

        from app.engines.standard_review import cited_standard_findings

        class Row:
            code = "SL765-2018"
            status = "废止"
            replaced_by = "SL/T223-2025"

        class Query:
            def filter(self, *_args, **_kwargs):
                return self

            def all(self):
                return [Row()]

        class Db:
            def query(self, _model):
                return Query()

            def close(self):
                return None

        with patch("app.db.platform_session", return_value=Db()):
            findings = cited_standard_findings("施工组织设计执行 SL765-2018。")
        self.assertEqual(len(findings), 1)
        self.assertIn("SL/T223-2025", findings[0]["basis"])
        self.assertIn("替代", findings[0]["rule"])

    def test_older_year_is_flagged_against_current_catalog(self):
        from app.engines.standard_review import newer_catalog_row

        rows = [
            {"code": "SL223-2008", "status": "废止"},
            {"code": "SL/T223-2025", "status": "现行"},
        ]
        newer = newer_catalog_row("SL 223-2008", rows)
        self.assertEqual(newer["code"], "SL/T223-2025")
        self.assertIsNone(newer_catalog_row("SL/T223-2025", rows))


class ClauseHeadingTests(unittest.TestCase):
    def test_clause_numbers_sort_by_numeric_parts(self):
        from app.routers.knowledge import _clause_sort_key

        self.assertLess(_clause_sort_key("3.9"), _clause_sort_key("3.10"))
        self.assertLess(_clause_sort_key("1.0.1"), _clause_sort_key("4.1.3"))


class ReviewCapAndLocalItemTests(unittest.TestCase):
    def test_pool_is_kept_when_tender_leaves_fill_the_cap(self):
        from app.engines.standard_review import MAX_POINTS, build_points

        tender = [
            {
                "source": "招标",
                "title": f"合同义务{i:03d}",
                "requirement": "这是招标文件里的一条施工内容说明",
                "checkType": "必须有",
                "enabled": True,
            }
            for i in range(MAX_POINTS + 12)
        ]
        pool = {
            "source": "规则池",
            "title": "施工导流与度汛",
            "requirement": "技术标应有施工导流、围堰和度汛方案。",
            "checkType": "必须有",
            "enabled": True,
        }
        points = build_points([], [], scope="tech", project_rules=[*tender, pool])
        names = [item["name"] for item in points]
        self.assertIn("施工导流与度汛", names)
        self.assertLessEqual(len(points), MAX_POINTS)

    def test_water_bid_does_not_take_building_dust_rules(self):
        from app.engines.category_profile import local_items_for_specialty
        from app.engines.e2_business import run as e2_run

        enabled = ["临边防护高度 1.2m", "扬尘防治 6 个 100%", "围挡率 100%"]
        water = local_items_for_specialty(enabled, "水利")
        building = local_items_for_specialty(enabled, "房建")
        self.assertEqual(building, enabled)
        self.assertEqual(water, ["围挡率 100%"])
        paragraphs = [{"text": "扬尘防治采用洒水降尘。临边设置防护栏杆。"}]

        def dust(items: list[str]) -> list[str]:
            return [
                item["rule"]
                for item in e2_run(paragraphs, local_items=items)
                if "扬尘" in item["rule"] or "临边" in item["rule"]
            ]

        self.assertEqual(len(dust(enabled)), 2)
        self.assertEqual(dust(water), [])
