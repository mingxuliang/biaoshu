import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

import docx

from app.engines import business_materials as bm
from app.engines import red_marker
from app.engines.form_registry import form_content, pasted_matches_original
from app.engines.submission_check import gap_chapters, trace_matrix
from app.engines.writer_export import _add_runs_with_inline_styles, _split_size_color

TODAY = date(2026, 11, 6)


def asset(id, kind, name, attrs=None, number="", owner="", valid_until="", detail="", review="已入库"):
    return SimpleNamespace(
        id=id,
        kind=kind,
        name=name,
        number=number,
        owner=owner,
        valid_until=valid_until,
        detail=detail,
        attrs_json=attrs or {},
        images=[],
        storage_path="",
        review_status=review,
    )


def need(**kw):
    base = {"label": "同类项目业绩", "kind": "contract", "count": 1, "criteria": "培训管理系统", "withinYears": 0,
            "minAmountWan": 0, "role": "", "original": ""}
    base.update(kw)
    return base


class ParseTest(unittest.TestCase):
    def test_amount(self):
        self.assertEqual(bm.parse_amount_wan("158万元"), 158)
        self.assertEqual(bm.parse_amount_wan("570 万"), 570)
        self.assertEqual(bm.parse_amount_wan("1,200,000元"), 120)
        self.assertIsNone(bm.parse_amount_wan("面议"))

    def test_date_and_expiry(self):
        self.assertEqual(bm.parse_date("2024年6月15日"), date(2024, 6, 15))
        self.assertTrue(bm.is_expired("2025-03-01", TODAY))
        self.assertFalse(bm.is_expired("长期", TODAY))
        self.assertFalse(bm.is_expired("", TODAY))


class HardFilterTest(unittest.TestCase):
    def test_window_amount_and_expiry(self):
        recent = asset("a1", "contract", "近期项目", {"signDate": "2025年3月", "amount": "200万元"})
        old = asset("a2", "contract", "旧项目", {"signDate": "2019年3月", "amount": "300万元"})
        small = asset("a3", "achievement", "小项目", {"signDate": "2025年1月", "amount": "20万元"})
        unsure = asset("a4", "contract", "无日期项目", {"amount": "面议"})
        cert = asset("c1", "cert", "证书")
        unsure_ids: set = set()
        out, notes = bm.hard_filter(
            need(withinYears=3, minAmountWan=100), [recent, old, small, unsure, cert], TODAY, unsure_ids
        )
        self.assertEqual([a.id for a in out], ["a1", "a4"])
        self.assertEqual(unsure_ids, {"a4"})
        self.assertTrue(any("超出" in n for n in notes))
        self.assertTrue(any("低于" in n for n in notes))

    def test_expired_cert_dropped(self):
        live = asset("c1", "cert", "ISO9001", valid_until="2027-01-01")
        dead = asset("c2", "cert", "ISO27001", valid_until="2024-01-01")
        out, notes = bm.hard_filter(need(kind="cert"), [live, dead], TODAY)
        self.assertEqual([a.id for a in out], ["c1"])
        self.assertTrue(any("过期" in n for n in notes))


class MatchTest(unittest.TestCase):
    def test_hit_copies_library_fields_and_missing_goes_red(self):
        proj = asset("a1", "contract", "某培训平台", {"projectName": "培训管理系统", "client": "某集团", "amount": "158万元",
                                                      "signDate": "2025年3月"})
        with mock.patch.object(bm, "_call_json", return_value={"ids": ["a1"]}):
            res = bm.match_need(need(count=2), [proj], [asset("p1", "contract", "待审", review="待审核")], TODAY, None)
        self.assertEqual(res["missing"], 1)
        out = bm.render([res])
        self.assertEqual(out["status"], "部分满足")
        self.assertIn("培训管理系统", out["body"])
        self.assertIn("158万元", out["body"])
        self.assertIn(red_marker.GAP_HEAD, out["body"])
        self.assertIn("待审核", out["body"])
        self.assertIn("缺少该材料将无法应标", out["body"])
        self.assertEqual(out["evidence"], ["a1"])
        self.assertIn("**响应情况：部分满足**", out["body"])

    def test_unsure_note_only_for_selected(self):
        unsure = asset("a4", "contract", "无日期项目", {"projectName": "培训管理系统"})
        other = asset("a5", "contract", "另一个无日期", {"projectName": "培训管理系统"})
        with mock.patch.object(bm, "_call_json", return_value={"ids": ["a4", "a5"]}):
            res = bm.match_need(need(withinYears=3), [unsure, other], [], TODAY, None)
        self.assertTrue(any("人工确认" in n for n in res["notes"]))
        with mock.patch.object(bm, "_call_json", return_value={"ids": []}):
            res = bm.match_need(need(withinYears=3), [unsure], [], TODAY, None)
        self.assertFalse(any("人工确认" in n for n in res["notes"]))

    def test_nothing_in_library_is_blank_not_invented(self):
        with mock.patch.object(bm, "_call_json", return_value={"ids": []}):
            res = bm.match_need(need(), [asset("c1", "cert", "ISO")], [], TODAY, None)
        out = bm.render([res])
        self.assertEqual(out["status"], "不满足")
        self.assertEqual(out["evidence"], [])
        self.assertIn(red_marker.GAP_HEAD, out["body"])
        self.assertIn("【缺】", out["body"])
        self.assertEqual(red_marker.count_gaps(out["body"]), 2)

    def test_pending_entries_do_not_participate(self):
        pending = asset("p1", "contract", "待审项目", {"projectName": "培训管理系统"}, review="待审核")
        with mock.patch("app.engines.business_materials.load_pool", return_value=([], [pending])), mock.patch.object(
            bm, "extract_needs", return_value=[need()]
        ):
            out = bm.build_chapter(None, "同类项目", "提供同类项目 1 个", None, TODAY)
        self.assertEqual(out["status"], "不满足")
        self.assertIn("待审核", out["body"])

    def test_llm_failure_falls_back_to_keywords(self):
        hit = asset("a1", "contract", "培训管理系统项目", {"projectName": "培训管理系统"})
        miss = asset("a2", "contract", "道路工程", {"projectName": "道路工程"})
        with mock.patch.object(bm, "_call_json", return_value={}):
            picked = bm.judge_candidates(need(), [hit, miss], None)
        self.assertEqual([a.id for a in picked], ["a1"])

    def test_no_needs_returns_none(self):
        with mock.patch.object(bm, "extract_needs", return_value=[]):
            self.assertIsNone(bm.build_chapter(None, "付款承诺", "按合同约定付款", None, TODAY))

    def test_image_tokens_match_prompt_key_format(self):
        a = asset("a1", "cert", "证")
        a.name = "营业执照"
        a.images = [
            SimpleNamespace(id="img1", storage_path="x/y.png", caption="5.1.1 营业执照"),
            SimpleNamespace(id="img2", storage_path="x/w.png", caption="附件五：投标人资格声明"),
        ]
        self.assertEqual(bm.image_keys(a), ["qual:a1:img1"])
        b = asset("b1", "cert", "证")
        b.storage_path = "x/z.png"
        self.assertEqual(bm.image_keys(b), ["qual:b1:b1"])


class TeamFormTest(unittest.TestCase):
    FORM = (
        "项目团队人员表\n\n| 序号 | 姓名 | 岗位 | 职称 | 证书 |\n| --- | --- | --- | --- | --- |\n"
        "| 1 |  | 项目经理 |  |  |\n| 2 |  | 实施工程师 |  |  |\n\n注：附证书复印件"
    )

    def test_fill_by_role_and_mark_missing(self):
        pm = asset("p1", "people", "张三", {"name": "张三", "role": "项目经理", "title": "高级工程师", "certificates": "PMP"},
                   owner="张三")
        with mock.patch("app.engines.business_materials.load_pool", return_value=([pm], [])), mock.patch.object(
            bm, "_call_json", return_value={"ids": ["p1"]}
        ):
            md, missing = bm.fill_team_form(None, self.FORM, "", None)
        self.assertEqual(missing, 1)
        self.assertIn("张三", md)
        self.assertIn("高级工程师", md)
        self.assertIn("PMP", md)
        self.assertIn("【缺人员】", md)
        self.assertIn(red_marker.GAP_HEAD, md)
        self.assertIn("注：附证书复印件", md)

    def test_filled_team_survives_form_content_and_export(self):
        registry = [{"kind": "team", "title": "项目团队", "md": self.FORM}]
        filled = {"0": "填好的团队表 张三"}
        self.assertEqual(form_content([0], registry, [], {}, filled), "填好的团队表 张三")
        self.assertEqual(form_content([0], registry, [], {}), self.FORM.strip())
        body = "项目团队人员表\n\n| 序号 | 姓名 | 岗位 | 职称 | 证书 |\n| --- | --- | --- | --- | --- |\n| 1 | 张三 | 项目经理 |  |  |"
        self.assertTrue(pasted_matches_original(body, [0], registry))


class RedMarkerTest(unittest.TestCase):
    def test_split_size_color(self):
        self.assertEqual(_split_size_color("16pt:C00000"), ("16pt", "C00000"))
        self.assertEqual(_split_size_color("12pt"), ("12pt", None))
        self.assertEqual(_split_size_color("12pt:zzz"), ("12pt", None))

    def test_docx_run_is_red_and_big(self):
        document = docx.Document()
        p = document.add_paragraph()
        _add_runs_with_inline_styles(p, red_marker.red(red_marker.GAP_HEAD, "18pt", bold=True))
        run = p.runs[0]
        self.assertEqual(str(run.font.color.rgb), "C00000")
        self.assertEqual(run.font.size.pt, 18)
        self.assertTrue(run.bold)
        self.assertEqual(run.text, red_marker.GAP_HEAD)

    def test_table_cell_red_survives(self):
        md = bm._md_table(["名称"], [[red_marker.red_cell("【缺】")]])
        self.assertIn("C00000", md)
        self.assertEqual(red_marker.count_gaps(md), 1)

    def test_self_check_lists_gap_chapters_and_matrix(self):
        outline = [{"id": "c1", "num": "1.1", "title": "同类项目"}, {"id": "c2", "num": "1.2", "title": "营业执照"}]
        contents = {"c1": red_marker.gap_block("同类项目", "", 1, 0), "c2": "有内容"}
        rows = gap_chapters(outline, contents)
        self.assertEqual([r[1] for r in rows], ["c1"])
        ledger = [{"id": "B1", "text": "x", "chapters": ["同类项目"], "volume": "business"}]
        matrix = trace_matrix(ledger, {}, outline, contents)
        self.assertIn("缺资质材料", matrix[0]["gap"])


if __name__ == "__main__":
    unittest.main()
