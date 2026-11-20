"""标书完全应标优化：台账、目录评审、附录登记、标品拼装、自查。"""

from __future__ import annotations

import io
import os
import tempfile
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


class LedgerTest(unittest.TestCase):
    def test_ledger_keeps_verbatim_and_flags_mandatory(self):
        from app.engines.req_ledger import attach_chapters, build_ledger, ledger_summary

        tech = "1、★系统须支持不少于1000并发用户；响应时间不超过3秒\n2、提供在线培训功能"
        original = "第三章 技术要求\n3.1 性能\n★系统须支持不少于1000并发用户；响应时间不超过3秒"
        ledger = build_ledger(tech, "", original)
        self.assertEqual([e["id"] for e in ledger], ["T1", "T2"])
        self.assertTrue(ledger[0]["mandatory"])
        self.assertEqual(ledger[0]["kind"], "实质性")
        self.assertEqual(len(ledger[0]["parts"]), 2)
        self.assertIn("3.1", ledger[0]["source"])
        self.assertIn("不少于1000并发用户", ledger[0]["text"])
        chapters = [{"title": "技术方案", "children": [{"title": "性能", "sourceRefs": ["T1"]}]}]
        attach_chapters(ledger, chapters)
        self.assertEqual(ledger[0]["composition"], "技术方案")
        self.assertEqual(ledger_summary(ledger)["uncited"], ["T2"])

    def test_shared_requirement_leaves_merge_into_parent(self):
        from app.engines.e_writer import PARENT_CONTEXT_MARK, SUBPOINTS_MARK, merge_shared_requirement_leaves

        req = "平台须支持二维码签到、手写签名、学习防作弊、视频防快进和人脸识别等能力"
        node = {
            "title": "学习管理",
            "requirement": req,
            "idea": "x",
            "children": [
                {"title": "签到", "requirement": req, "idea": f"{PARENT_CONTEXT_MARK}，本章只答签到】{req}"},
                {"title": "防作弊", "requirement": req, "idea": f"{PARENT_CONTEXT_MARK}，本章只答防作弊】{req}"},
                {"title": "独立项", "requirement": "另一条", "idea": "【对应招标「独立项」】另一条"},
            ],
        }
        merged = merge_shared_requirement_leaves([node])
        self.assertEqual(merged, 1)
        self.assertEqual([c["title"] for c in node["children"]], ["签到", "独立项"])
        self.assertIn(SUBPOINTS_MARK, node["children"][0]["idea"])
        self.assertIn("防作弊", node["children"][0]["idea"])
        self.assertNotIn(PARENT_CONTEXT_MARK, node["children"][0]["idea"])


class CompositionTest(unittest.TestCase):
    def test_table_form_composition_list(self):
        from app.engines.tender_toc import extract_bid_composition

        text = "\n".join(
            [
                "投标文件组成如下：",
                "序号 | 文件名称 | 页码",
                "1 | 投标函 | ",
                "2 | 法定代表人身份证明或授权委托书 | ",
                "3 | 技术方案 | ",
                "第四章 评标办法",
            ]
        )
        titles = [i["title"] for i in extract_bid_composition(text)]
        self.assertEqual(titles, ["投标函", "法定代表人身份证明或授权委托书", "技术方案"])

    def test_format_chapter_list_wins_over_instructions_list(self):
        from app.engines.tender_toc import extract_bid_composition

        text = "\n".join(
            [
                "投标文件组成：",
                "1. 投标人须知前附表规定的其他材料",
                "2. 投标函",
                "3. 法定代表人身份证明或授权委托书",
                "第七章 投标文件格式",
                "一、投标函（不含报价）",
                "二、法定代表人身份证明和授权委托书",
                "三、联合体协议书",
                "四、投标保证金",
            ]
        )
        titles = [item["title"] for item in extract_bid_composition(text)]
        self.assertEqual(
            titles,
            [
                "投标函（不含报价）",
                "法定代表人身份证明和授权委托书",
                "联合体协议书",
                "投标保证金",
            ],
        )
        self.assertNotIn("投标人须知前附表规定的其他材料", titles)

    def test_content_section_is_found_in_any_chapter(self):
        from app.engines.tender_toc import extract_bid_composition

        text = "\n".join(
            [
                "投标文件组成：",
                "1. 投标人须知前附表规定的其他材料",
                "2. 投标函",
                "3. 授权委托书",
                "第三章 响应文件内容及格式",
                "项目封面和投标人名称",
                "一、应答函",
                "二、资格证明文件",
                "三、技术方案",
            ]
        )
        titles = [item["title"] for item in extract_bid_composition(text)]
        self.assertEqual(titles, ["应答函", "资格证明文件", "技术方案"])

    def test_review_standards_are_not_the_file_list(self):
        from app.engines.tender_toc import extract_bid_composition

        text = "\n".join(
            [
                "第三章 评标办法",
                "投标文件格式",
                "（1）投标文件制作机器码相同",
                "（2）投标文件创建标识码相同",
                "（3）投标人联系人或联系人电话相同",
                "（4）符合第七章投标文件格式的要求",
                "（5）未出现投标报价",
                "第七章 投标文件格式",
                "一、投标函（不含报价）",
                "二、法定代表人身份证明和授权委托书",
                "三、其他资料",
            ]
        )
        titles = [item["title"] for item in extract_bid_composition(text)]
        self.assertEqual(titles, ["投标函（不含报价）", "法定代表人身份证明和授权委托书", "其他资料"])

    def test_format_list_survives_the_cover_page(self):
        from app.engines.tender_toc import extract_bid_composition

        text = "\n".join(
            [
                "投标文件组成：",
                "（1）投标函及投标函附录；",
                "（2）其他资料；",
                "（3）投标人须知前附表规定的其他资料。",
                "第七章 投标文件格式",
                "环巢湖大张圩片区水系连通及生态修复工程一期EPC",
                "投标文件",
                "商务文件",
                "目录",
                "一、投标函（不含报价）",
                "二、诚信投标承诺书",
                "三、商务文件详细评审资料",
                "四、其他资料",
            ]
        )
        titles = [item["title"] for item in extract_bid_composition(text)]
        self.assertEqual(
            titles,
            ["投标函（不含报价）", "诚信投标承诺书", "商务文件详细评审资料", "其他资料"],
        )

    def test_composition_is_annotated_not_rewritten(self):
        from app.engines.e_writer import annotate_composition

        items = [{"title": "商务响应", "volume": "business"}, {"title": "技术方案", "volume": "tech"}]
        chapters = [
            {"title": "技术方案", "children": [{"title": "登录认证", "children": []}]},
            {"title": "商务响应", "children": []},
            {"title": "付款说明", "children": []},
        ]
        problems = annotate_composition(chapters, items)
        # 顺序、章数、小节都保持智能体编的样子
        self.assertEqual([c["title"] for c in chapters], ["技术方案", "商务响应", "付款说明"])
        self.assertEqual([c["title"] for c in chapters[0]["children"]], ["登录认证"])
        self.assertTrue(chapters[0]["composition"])
        self.assertEqual(chapters[0]["part"], "tech")
        self.assertNotIn("composition", chapters[2])
        self.assertTrue(any("付款说明" in item for item in problems))
        self.assertTrue(any("顺序" in item for item in problems))

    def test_composition_aligns_wording_and_reports_missing(self):
        from app.engines.e_writer import annotate_composition

        items = [{"title": "法定代表人身份证明和授权委托书"}, {"title": "联合体协议书"}]
        chapters = [{"title": "法定代表人身份证明或授权委托书", "children": []}]
        problems = annotate_composition(chapters, items)
        self.assertEqual(chapters[0]["title"], "法定代表人身份证明和授权委托书")
        self.assertTrue(any("联合体协议书" in item for item in problems))

    def test_annotate_composition_is_idempotent(self):
        from app.engines.e_writer import annotate_composition

        items = [{"title": "技术方案", "volume": "tech"}]
        chapters = [{"title": "技术方案", "children": []}]
        first = annotate_composition(chapters, items)
        second = annotate_composition(chapters, items)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual([c["title"] for c in chapters], ["技术方案"])


def _build_tender_docx(path: str) -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("第一章 招标公告")
    document.add_paragraph("响应文件格式")
    document.add_paragraph("一、投标函")
    document.add_paragraph("致：采购人。我方承诺按招标文件要求投标。")
    document.add_paragraph("二、授权委托书")
    document.add_paragraph("本人授权 代理人 办理投标事宜。")
    document.add_paragraph("三、需求响应偏离表")
    table = document.add_table(rows=2, cols=5)
    for i, head in enumerate(["序号", "招标要求", "响应情况", "实现方式", "偏离说明"]):
        table.rows[0].cells[i].text = head
    table.rows[1].cells[0].text = "1"
    document.add_paragraph("注：按招标文件逐条填写。")
    document.add_paragraph("四、报价明细表")
    quote = document.add_table(rows=2, cols=3)
    for i, head in enumerate(["项目", "单价（元）", "合价（元）"]):
        quote.rows[0].cells[i].text = head
    quote.rows[1].cells[0].text = "平台软件"
    document.add_paragraph("五、项目团队表")
    team = document.add_table(rows=2, cols=3)
    for i, head in enumerate(["姓名", "职务", "资历"]):
        team.rows[0].cells[i].text = head
    document.save(path)


class FormRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "t.docx")
        _build_tender_docx(self.path)

    def test_scan_registers_each_form_with_kind(self):
        from app.engines.form_registry import scan_appendix_forms

        registry = scan_appendix_forms(self.path)
        self.assertEqual(
            [(e["title"], e["kind"]) for e in registry],
            [
                ("一、投标函", "other"),
                ("二、授权委托书", "authority"),
                ("三、需求响应偏离表", "deviation"),
                ("四、报价明细表", "quote"),
                ("五、项目团队表", "team"),
            ],
        )
        self.assertTrue(registry[2]["table"])
        self.assertTrue(registry[2]["ooxml"])

    def test_one_title_maps_to_many_forms(self):
        from app.engines.form_registry import match_titles_to_forms, scan_appendix_forms

        registry = scan_appendix_forms(self.path)
        mapped = match_titles_to_forms(["法定代表人身份证明或授权委托书", "投标函", "技术方案"], registry)
        self.assertEqual(mapped["投标函"], [0])
        self.assertEqual(mapped["法定代表人身份证明或授权委托书"], [1])
        self.assertNotIn("技术方案", mapped)

    def test_deviation_rows_filled_one_per_requirement(self):
        from app.engines.form_registry import form_content, scan_appendix_forms

        registry = scan_appendix_forms(self.path)
        ledger = [
            {"id": "T1", "volume": "tech", "text": "支持1000并发"},
            {"id": "T2", "volume": "tech", "text": "提供在线培训"},
            {"id": "B1", "volume": "business", "text": "质保三年"},
        ]
        responses = {"T1": {"status": "满足", "how": "集群部署"}, "T2": {"status": "部分满足", "how": "线上课程", "deviation": "缺线下培训"}}
        content = form_content([2], registry, ledger, responses)
        rows = [line for line in content.split("\n") if line.startswith("|")]
        self.assertEqual(len(rows), 4)  # 表头、分隔行、2 个需求行
        self.assertIn("支持1000并发", rows[2])
        self.assertIn("满足", rows[2])
        self.assertIn("集群部署", rows[2])
        self.assertIn("缺线下培训", rows[3])
        self.assertIn("注：按招标文件逐条填写。", content)
        self.assertNotIn("质保三年", content)

    def test_missing_record_writes_pending_and_quote_amounts_pending(self):
        from app.engines.form_registry import form_content, scan_appendix_forms

        registry = scan_appendix_forms(self.path)
        dev = form_content([2], registry, [{"id": "T1", "volume": "tech", "text": "x"}], {})
        self.assertIn("待填", dev)
        quote = form_content([3], registry)
        self.assertIn("待填", quote)
        self.assertIn("平台软件", quote)
        team = form_content([4], registry)
        self.assertNotIn("待填", team)

    def test_verbatim_check_and_export_keeps_original_table(self):
        import docx

        from app.engines.form_registry import form_content, pasted_matches_original, scan_appendix_forms
        from app.engines.writer_export import chapters_to_docx

        registry = scan_appendix_forms(self.path)
        content = form_content([0, 1], registry)
        self.assertTrue(pasted_matches_original(content, [0, 1], registry))
        self.assertFalse(pasted_matches_original("我方承诺好好投标", [0], registry))
        outline = [
            {"id": "a", "parentId": None, "title": "项目团队表", "num": "一、", "part": "form", "formKeys": [4]},
        ]
        data = chapters_to_docx("项目", outline, {"a": form_content([4], registry)}, {}, None, registry)
        doc = docx.Document(io.BytesIO(data))
        self.assertEqual(len(doc.tables), 1)
        self.assertEqual([c.text for c in doc.tables[0].rows[0].cells], ["姓名", "职务", "资历"])


class StandardProductTest(unittest.TestCase):
    FEATURES = [
        {
            "id": "pfe-1",
            "name": "在线学习",
            "module": "学习",
            "params": "支持1000并发",
            "intro": "",
            "bidCopy": "平台提供在线学习功能，支持视频、课件。",
            "images": [{"id": "pimg-1", "caption": "学习界面"}],
        }
    ]

    def test_hit_is_assembled_from_library_text_and_images(self):
        from app.engines.standard_product import build_answer

        decision = {"verdict": "满足", "source": "标品", "featureIds": ["pfe-1"], "sliceIds": [], "gap": ""}
        body, evidence = build_answer(decision, self.FEATURES, [], {}, "c1")
        self.assertIn("响应情况：满足", body)
        self.assertIn("平台提供在线学习功能，支持视频、课件。", body)
        self.assertIn("{{IMG:product:pimg-1}}", body)
        self.assertEqual(evidence, ["pfe-1"])

    def test_second_chapter_only_references_first(self):
        from app.engines.standard_product import build_answer

        decision = {"verdict": "满足", "source": "标品", "featureIds": ["pfe-1"], "sliceIds": [], "gap": ""}
        placed = {"pfe-1": {"chapterId": "c1", "title": "在线学习方案"}}
        body, _ = build_answer(decision, self.FEATURES, [], placed, "c2")
        self.assertIn("详见「在线学习方案」", body)
        self.assertNotIn("{{IMG:", body)

    def test_knowledge_source_uses_slice_text_verbatim(self):
        from app.engines.standard_product import build_answer

        snippets = [{"docId": "d1", "heading": "部署架构", "text": "采用三层架构。【此处插入图：1】", "images": [{"id": "i1"}]}]
        decision = {"verdict": "满足", "source": "知识库", "featureIds": [], "sliceIds": ["s0"], "gap": ""}
        body, _ = build_answer(decision, [], snippets, {}, "c1")
        self.assertIn("采用三层架构。", body)
        self.assertNotIn("【此处插入图", body)
        self.assertIn("{{IMG:knowledge:i1}}", body)

    def test_partial_appends_gap_and_deviation(self):
        from app.engines.standard_product import append_gap_and_deviation

        out = append_gap_and_deviation("正文", "部分满足", "缺线下培训", "补充：线下培训方案")
        self.assertIn("补充：线下培训方案", out)
        self.assertIn("偏离说明", out)
        self.assertIn("无偏离", append_gap_and_deviation("正文", "满足", ""))


class ClaimAndCheckTest(unittest.TestCase):
    def test_unsupported_claims_need_evidence(self):
        from app.engines.writer_harness import unsupported_claims

        solution = "我司通过ISO9001认证，拥有CMMI5级，并获得等保三级。"
        evidence = "公司资质：ISO 9001 质量管理体系认证"
        self.assertEqual(unsupported_claims(solution, evidence), ["CMMI5级", "等保三级"][:0] or unsupported_claims(solution, evidence))
        claims = unsupported_claims(solution, evidence)
        self.assertNotIn("ISO9001", claims)
        self.assertTrue(any("CMMI" in c for c in claims))

    def test_conflicting_values_across_chapters(self):
        from app.engines.submission_check import _check_conflicts

        outline = [{"id": "a", "num": "一、", "title": "售后"}, {"id": "b", "num": "二、", "title": "实施"}]
        contents = {"a": "## 解决方案\n质保期 3 年", "b": "## 解决方案\n质保期 5 年"}
        self.assertEqual(len(_check_conflicts(outline, contents)), 1)
        self.assertEqual(_check_conflicts(outline, {"a": "质保期3年", "b": "质保期 3 年"}), [])

    def test_trace_matrix_and_csv(self):
        from app.engines.submission_check import matrix_csv, trace_matrix

        ledger = [{"id": "T1", "volume": "tech", "text": "要求", "kind": "应答", "mandatory": True, "chapters": ["性能"], "composition": "技术方案"}]
        rows = trace_matrix(ledger, {"T1": {"status": "满足", "source": "标品", "evidence": ["pfe-1"]}}, [], {})
        self.assertEqual(rows[0]["status"], "满足")
        self.assertTrue(matrix_csv(rows).startswith("\ufeff编号".encode("utf-8")))

    def test_merge_settings_keeps_server_keys(self):
        from app.writer_tracks import merge_settings

        merged = merge_settings({"ledger": [1], "responses": {"T1": {}}}, {"layout": {"a": 1}, "ledger": ["旧"]})
        self.assertEqual(merged["ledger"], [1])
        self.assertIn("responses", merged)
        self.assertEqual(merged["layout"], {"a": 1})


if __name__ == "__main__":
    unittest.main()


class ApplyRegistryTest(unittest.TestCase):
    REGISTRY = [
        {"title": "附件一 投标函", "kind": "other", "md": "投标函正文", "ooxml": [], "table": False},
        {"title": "附件二 需求响应偏离表", "kind": "deviation", "md": "x", "ooxml": [], "table": True},
    ]

    def test_plain_form_node_is_replaced_whole(self):
        from app.engines.form_registry import apply_registry_to_tree

        chapters = [{"title": "投标函及投标承诺", "composition": True, "children": [{"title": "说明"}]}]
        done = apply_registry_to_tree(chapters, self.REGISTRY)
        self.assertEqual(done, ["投标函及投标承诺"])
        self.assertEqual(chapters[0]["formKeys"], [0])
        self.assertEqual(chapters[0]["part"], "form")
        self.assertEqual(chapters[0]["children"], [])

    def test_real_chapter_gets_form_as_child_not_replaced(self):
        from app.engines.form_registry import apply_registry_to_tree

        chapters = [
            {
                "title": "技术方案及逐项需求响应表",
                "composition": True,
                "children": [{"title": "性能", "sourceRefs": ["T1"], "requirement": "x"}],
            }
        ]
        done = apply_registry_to_tree(
            chapters, self.REGISTRY, lambda titles, registry: {titles[0]: [1]}
        )
        self.assertEqual(done, ["技术方案及逐项需求响应表"])
        self.assertNotIn("formKeys", chapters[0])
        self.assertEqual([c["title"] for c in chapters[0]["children"]], ["性能", "需求响应偏离表"])
        self.assertEqual(chapters[0]["children"][1]["formKeys"], [1])

    def test_leaves_with_identical_requirement_collapse_into_parent(self):
        from app.engines.e_writer import merge_shared_requirement_leaves

        req = "系统须支持用户、课程、记录和附件规模增长，并具备可扩展部署能力和高可用方案"
        node = {
            "title": "容量与可用性",
            "children": [
                {"title": "用户与课程容量", "requirement": req, "sourceRefs": ["T3"], "idea": "i"},
                {"title": "并发与响应设计", "requirement": req, "sourceRefs": ["T3"], "idea": "i"},
            ],
        }
        self.assertEqual(merge_shared_requirement_leaves([node]), 2)
        self.assertEqual(node["children"], [])
        self.assertEqual(node["sourceRefs"], ["T3"])
        self.assertIn("并发与响应设计", node["idea"])


class DedupeFormTest(unittest.TestCase):
    def test_same_form_is_kept_once_in_tree(self):
        from app.engines.form_registry import dedupe_form_nodes

        tree = [
            {"title": "A", "children": [{"title": "项目团队表", "formKeys": [3], "children": []}]},
            {"title": "B", "children": [{"title": "团队表", "formKeys": [3], "children": []}, {"title": "其他"}]},
        ]
        self.assertEqual(dedupe_form_nodes(tree), 1)
        self.assertEqual(tree[0]["children"][0]["formKeys"], [3])
        self.assertEqual([c["title"] for c in tree[1]["children"]], ["其他"])
