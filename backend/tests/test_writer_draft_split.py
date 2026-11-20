"""技术标/商务标分离撰写：读原文分页、目录按 doc_kind 拆分迁移、共享字段镜像，不调用外部模型/真实数据库。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest


class SplitOutlineByDocKindTest(unittest.TestCase):
    def test_top_level_subtree_follows_leaf_majority_vote(self) -> None:
        from app.engines.e_writer import split_outline_by_doc_kind

        outline = [
            {"id": "a", "parentId": None, "title": "技术方案", "num": "一、"},
            {"id": "a1", "parentId": "a", "title": "总体架构", "num": "（一）", "part": "tech", "requirement": "应实现架构设计"},
            {"id": "a2", "parentId": "a", "title": "实施计划", "num": "（二）", "part": "tech", "requirement": "应实现进度计划"},
            {"id": "b", "parentId": None, "title": "商务资信", "num": "二、"},
            {"id": "b1", "parentId": "b", "title": "营业执照", "num": "（一）", "part": "business"},
            {"id": "b2", "parentId": "b", "title": "投标函", "num": "（二）", "part": "form"},
        ]
        contents = {"a1": "架构正文", "b1": "执照原文"}
        knowledge_refs = {"a1": [{"docId": "d1"}]}

        (tech_outline, tech_contents, tech_refs), (biz_outline, biz_contents, biz_refs) = split_outline_by_doc_kind(
            outline, contents, knowledge_refs
        )

        self.assertEqual({n["id"] for n in tech_outline}, {"a", "a1", "a2"})
        self.assertEqual({n["id"] for n in biz_outline}, {"b", "b1", "b2"})
        self.assertEqual(tech_contents, {"a1": "架构正文"})
        self.assertEqual(biz_contents, {"b1": "执照原文"})
        self.assertEqual(tech_refs, {"a1": [{"docId": "d1"}]})
        self.assertEqual(biz_refs, {})

    def test_empty_outline_returns_empty_bundles(self) -> None:
        from app.engines.e_writer import split_outline_by_doc_kind

        (tech_outline, tech_contents, tech_refs), (biz_outline, biz_contents, biz_refs) = split_outline_by_doc_kind(
            None, None, None
        )
        self.assertEqual(tech_outline, [])
        self.assertEqual(biz_outline, [])
        self.assertEqual(tech_contents, {})
        self.assertEqual(biz_contents, {})
        self.assertEqual(tech_refs, {})
        self.assertEqual(biz_refs, {})


class OutlinePromptDocKindTest(unittest.TestCase):
    def test_prompt_asks_to_read_original_and_drops_parsed_summaries(self) -> None:
        from app.engines.e_writer import OUTLINE_INLINE_TENDER_MAX, _build_outline_user_message

        secret_summary = "这是解析模块抽出的技术标应答摘要，不该出现在目录提示里"
        tender = "招标书原文：应建设统一门户，并提交投标函。"
        prompt = _build_outline_user_message(
            "示范项目",
            tender,
            None,
            [],
            [],
            format_requirements=[{"title": "投标函", "desc": secret_summary}],
            doc_kind="tech",
            total_pages=1,
        )
        self.assertIn("先检索格式节", prompt)
        self.assertIn(tender, prompt)
        self.assertNotIn("techBidResponseRequirements", prompt)
        self.assertNotIn("businessBidResponse", prompt)
        self.assertLessEqual(len(tender), OUTLINE_INLINE_TENDER_MAX)

    def test_long_tender_is_paged_instead_of_inlined(self) -> None:
        from app.engines.e_writer import _build_outline_user_message

        tender = "甲" * 20000
        prompt = _build_outline_user_message(
            "示范项目", tender, None, [], [], doc_kind="tech", total_pages=3
        )
        self.assertNotIn(tender, prompt)
        self.assertIn('read_tender(section="original")', prompt)
        self.assertIn("共约 3 页", prompt)
        self.assertIn("不要从第 1 页逐页翻到最后", prompt)
        self.assertIn("投标文件格式", prompt)

    def test_tech_prompt_expands_by_page_budget_business_does_not(self) -> None:
        from app.engines.e_writer import _build_outline_user_message

        page = {"total": 40, "cover": 2, "body": 30, "appendix": 8}
        tech = _build_outline_user_message(
            "示范项目", "短原文", None, [], [], doc_kind="tech", page=page, layout={}
        )
        business = _build_outline_user_message(
            "示范项目", "短原文", None, [], [], doc_kind="business", page=page, layout={}
        )
        self.assertIn("本次编制分册：技术标", tech)
        self.assertIn("采购需求", tech)
        self.assertIn("不要为凑页数自拟章节", tech)
        self.assertNotIn("超过招标应答的最低要求", tech)
        self.assertNotIn("约 30 页", tech)
        self.assertIn("本次编制分册：商务标", business)
        self.assertNotIn("约 30 页", business)
        self.assertNotIn("采购需求", business)
        self.assertIn("商务标不按篇幅加章", business)

    def test_tech_outline_backfills_missing_requirements_and_keeps_forms_out(self) -> None:
        from app.engines.e_writer import ensure_tech_requirement_coverage

        names = [
            "招标范围",
            "用户组织权限",
            "培训计划管理",
            "文件变更培训",
            "课程课件管理",
            "签到与防作弊",
            "考试评估评分",
            "报表导出归档",
            "提醒消息通知",
            "审计追踪合规",
            "系统集成方案",
            "本地化部署",
            "性能与容量",
            "安全要求",
            "实施交付验收",
            "运维与培训",
            "技术响应要求",
        ]
        tech = "\n".join(f"{index}、{name}：关键数字{index}00，期限{index}天" for index, name in enumerate(names, start=1))
        business = "1、投标函：按格式填写\n2、接口与数据迁移方案：字段、触发与失败重试\n"
        chapters = [
            {
                "title": "技术方案",
                "children": [
                    {
                        "title": "功能需求响应",
                        "children": [
                            {"title": "用户组织权限", "children": [], "idea": "对应「用户组织权限」，须严格按招标文件相关条款应答，不得漏项。"},
                            {"title": "培训计划管理", "children": []},
                        ],
                    }
                ],
            }
        ]
        covered = ensure_tech_requirement_coverage(chapters, tech, business, "tech")
        titles = []

        def walk(nodes):
            for node in nodes:
                titles.append(node.get("title") or "")
                walk(node.get("children") or [])

        walk(covered)
        for name in names:
            self.assertIn(name, titles)
        self.assertIn("接口与数据迁移方案", titles)
        self.assertNotIn("投标函", titles)
        self.assertIn("逐项需求响应表", titles)
        file_change = None

        def find(nodes):
            nonlocal file_change
            for node in nodes:
                if node.get("title") == "文件变更培训":
                    file_change = node
                if node.get("title") == "用户组织权限":
                    self.assertIn("200", node.get("idea") or "")
                    self.assertNotIn("须严格按招标文件相关条款应答，不得漏项", node.get("idea") or "")
                find(node.get("children") or [])

        find(covered)
        self.assertIsNotNone(file_change)
        self.assertIn("400", file_change.get("idea") or "")

    def _walk(self, nodes):
        for node in nodes:
            yield node
            yield from self._walk(node.get("children") or [])

    def test_source_lines_bind_clause_text_and_children_inherit_slices(self) -> None:
        from app.engines.e_writer import _chapters_from_llm_output, bind_requirements

        tech = (
            "1、提醒与消息：计划课程须提前三天提醒，提醒频率可配置，每日最多推送5次。\n"
            "2、本地化部署：支持500并发，响应时间不超过2秒，可用性99.9%。"
        )
        markdown = (
            "# 技术方案\n"
            "## 提醒与消息\n依据：T1\n"
            "### 提前三天提醒\n"
            "### 提醒触达监控\n"
            "## 本地化部署\n依据：T2\n"
            "## 无来源章节\n"
        )
        chapters = _chapters_from_llm_output(markdown)
        report = bind_requirements(chapters, tech, "", "招标原文里没有出现任何相关内容。")
        by_title = {n["title"]: n for n in self._walk(chapters)}
        self.assertIn("提前三天", by_title["提醒与消息"]["requirement"])
        self.assertIn("每日最多推送5次", by_title["提醒与消息"]["idea"])
        self.assertIn("500并发", by_title["本地化部署"]["requirement"])
        self.assertIn("99.9%", by_title["本地化部署"]["idea"])
        # 子节点沿用上级条款，只带和标题相关的分句
        self.assertIn("提前三天", by_title["提前三天提醒"]["requirement"])
        self.assertNotIn("每日最多推送5次", by_title["提前三天提醒"]["requirement"])
        # 挑不出相关分句时带上级全文并标注
        self.assertIn("上级条款全文", by_title["提醒触达监控"]["idea"])
        # 没有任何依据：如实标注，不写套话
        self.assertIn("未找到对应招标条款", by_title["无来源章节"]["idea"])
        self.assertEqual(report["noSource"], ["无来源章节"])
        for node in by_title.values():
            self.assertNotIn("须严格按招标文件相关条款应答，不得漏项", node.get("idea") or "")

    def test_facts_missing_from_every_child_slice_go_to_one_leaf(self) -> None:
        from app.engines.e_writer import _chapters_from_llm_output, bind_requirements, resolve_chapter_requirement

        tech = "1、提醒与消息：计划课程须提前三天提醒，保留触达记录，每日最多推送5次。"
        chapters = _chapters_from_llm_output(
            "# 提醒与消息\n依据：T1\n## 提前三天提醒\n## 触达记录保留\n## 发送上限\n"
        )
        bind_requirements(chapters, tech, "", "")
        leaves = {n["title"]: n for n in self._walk(chapters) if not n.get("children")}
        self.assertIn("三天", leaves["提前三天提醒"]["requirement"])
        residual_owner = [
            n for n in leaves.values() if "本章必须写明指标" in (n.get("idea") or "")
        ]
        self.assertEqual(len(residual_owner), 1)
        self.assertIn("5次", residual_owner[0]["idea"])
        req, facts = resolve_chapter_requirement(
            list(self._walk(chapters)), None, residual_owner[0].get("requirement") or "", residual_owner[0]["idea"], "", "发送上限"
        )
        self.assertIn("5次", facts)

    def test_coverage_is_counted_by_item_ids_not_title_substrings(self) -> None:
        from app.engines.e_writer import bind_requirements, ensure_tech_requirement_coverage

        names = [f"功能域{i}" for i in range(1, 18)]
        tech = "\n".join(f"{i}、{name}：关键数字{i}00，期限{i}天" for i, name in enumerate(names, start=1))
        chapters = [
            {
                "title": "技术方案",
                "children": [
                    {"title": "功能域1", "sourceRefs": ["T1"], "children": []},
                    {"title": "功能域2", "sourceRefs": ["T2", "T3"], "children": []},
                    {"title": "功能域4", "children": []},
                ],
            }
        ]
        bind_requirements(chapters, tech, "", "")
        report: dict = {}
        covered = ensure_tech_requirement_coverage(chapters, tech, "", "tech", report=report)
        titles = [n["title"] for n in self._walk(covered)]
        for name in names:
            if name == "功能域3":  # T3 由「功能域2」节点一并引用，不会再单独补章
                continue
            self.assertIn(name, titles)
        self.assertEqual(report["total"], 17)
        self.assertEqual(report["boundByModel"], 3)
        self.assertEqual(report["titleMatched"], 1)
        self.assertEqual(report["backfilled"], 13)
        for node in self._walk(covered):
            if node["title"] in names:
                self.assertTrue((node.get("requirement") or "").strip(), node["title"])
                self.assertIn("期限", node.get("requirement") or "")
            if node["title"] == "功能域2":
                self.assertIn("功能域3", node["requirement"])

    def test_container_tech_chapter_is_not_business_and_gets_no_form_text(self) -> None:
        from app.engines.e_writer import chapter_kind, fill_business_originals

        self.assertEqual(chapter_kind("总体技术方案", "tech", "", "", has_children=True), "tech")
        self.assertEqual(chapter_kind("总体技术方案", None, "", "", has_children=True), "tech")
        self.assertEqual(chapter_kind("总体技术方案", "tech", "", ""), "tech")
        self.assertEqual(chapter_kind("资格证明文件", "tech", "", ""), "business")
        outline = [
            {"id": "o-1", "parentId": None, "title": "总体技术方案", "part": "tech", "idea": "", "requirement": ""},
            {"id": "o-1-1", "parentId": "o-1", "title": "提醒与消息", "part": "tech", "requirement": "提前三天提醒"},
        ]
        contents: dict = {}
        changed = fill_business_originals(outline, contents, {"总体技术方案": "投标函 致：招标人"})
        self.assertFalse(changed)
        self.assertEqual(contents, {})

    def test_chapter_requirement_resolves_from_ancestor_and_flags_whole_parent(self) -> None:
        from app.engines.e_writer import resolve_chapter_requirement

        outline = [
            {"id": "a", "parentId": None, "title": "提醒与消息", "requirement": "须提前三天提醒；每日最多推送5次。"},
            {"id": "a1", "parentId": "a", "title": "提前三天提醒", "requirement": ""},
            {"id": "a2", "parentId": "a", "title": "审计留痕", "requirement": ""},
        ]
        req, facts = resolve_chapter_requirement(outline, "a1", "", "", "", "提前三天提醒")
        self.assertIn("提前三天", req)
        self.assertNotIn("5次", req)
        self.assertEqual(facts, req)
        req2, facts2 = resolve_chapter_requirement(outline, "a2", "", "", "", "审计留痕")
        self.assertIn("5次", req2)
        self.assertEqual(facts2, "")
        req3, facts3 = resolve_chapter_requirement(
            outline, "x", "", "【汇总章】逐项需求响应表", "", "逐项需求响应表"
        )
        self.assertEqual(facts3, "")

    def test_generic_budget_gives_each_clause_a_floor(self) -> None:
        from app.engines.e_writer import CHAPTER_MIN_CHARS, chapter_char_targets

        long_req = "条款" * 400
        outline = [
            {"id": "t", "title": "技术方案", "parentId": None, "part": "tech", "weight": 0},
            {"id": "a", "title": "短条款", "parentId": "t", "part": "tech", "weight": 0, "requirement": "须提前三天提醒"},
            {"id": "b", "title": "长条款", "parentId": "t", "part": "tech", "weight": 0, "requirement": long_req},
        ]
        page = {"total": 1, "cover": 0, "body": 1, "appendix": 0}
        targets = chapter_char_targets(outline, page, {"fontSize": "小四"})
        self.assertGreaterEqual(targets["a"], CHAPTER_MIN_CHARS)
        self.assertGreater(targets["b"], targets["a"])
        self.assertGreaterEqual(targets["b"], int(len(long_req) * 1.2))

    def test_business_volume_binds_quotes_and_deviation_without_swallowing_forms(self) -> None:
        from app.engines.e_writer import (
            _chapters_from_llm_output,
            _collapse_original_form_chapters,
            bind_requirements,
            business_item_belongs_in_tech,
            chapter_kind,
            ensure_business_requirement_coverage,
            ensure_business_response_structure,
            ensure_tech_requirement_coverage,
            fill_business_originals,
            is_original_form_title,
            should_paste_tender_original,
        )

        self.assertTrue(is_original_form_title("承诺书"))
        self.assertTrue(is_original_form_title("开标一览表"))
        self.assertFalse(is_original_form_title("报价明细表"))
        self.assertFalse(is_original_form_title("商务及需求偏离表"))
        self.assertTrue(business_item_belongs_in_tech("产品演示材料", "演示环境、演示脚本和截图"))
        self.assertFalse(business_item_belongs_in_tech("报价明细", "软件许可、课程版权"))

        collapsed = [{"title": "承诺书", "children": [{"title": "不应保留"}]}]
        kept = [{"title": "报价明细表", "children": [{"title": "软件许可"}]}]
        _collapse_original_form_chapters(collapsed)
        _collapse_original_form_chapters(kept)
        self.assertEqual(collapsed[0]["children"], [])
        self.assertEqual(kept[0]["children"][0]["title"], "软件许可")

        business = "1、投标保证金：人民币5万元，投标有效期90日。"
        chapters = _chapters_from_llm_output("# 商务文件\n## 投标保证金\n依据：B1\n## 承诺书\n")
        bind_requirements(chapters, "", business, "招标原文里没有保证金以外的句子。", "business")
        by_title = {node["title"]: node for node in self._walk(chapters)}
        self.assertIn("5万元", by_title["投标保证金"]["requirement"])
        self.assertEqual(by_title["投标保证金"]["part"], "business")
        self.assertNotIn("requirement", by_title["承诺书"])

        self.assertEqual(
            chapter_kind("付款方式及节点", "business", "", "终验通过支付40%", has_children=False),
            "response",
        )
        self.assertEqual(chapter_kind("营业执照", "business", "", "提供副本"), "business")
        self.assertFalse(
            should_paste_tender_original("付款方式及节点", "business", "", "终验通过支付40%")
        )
        outline = [
            {
                "id": "pay",
                "title": "付款方式及节点",
                "part": "business",
                "requirement": "终验通过支付40%",
                "idea": "【对应招标「付款」】终验通过支付40%",
            }
        ]
        contents: dict = {}
        self.assertFalse(fill_business_originals(outline, contents, {"付款方式及节点": "粘贴过来的格式"}))
        self.assertEqual(contents, {})
        self.assertNotIn("无需撰写应标正文", " ".join(contents.values()))

    def test_business_coverage_backfills_and_splits_quote_payment_deviation(self) -> None:
        from app.engines.e_writer import (
            ensure_business_requirement_coverage,
            ensure_business_response_structure,
            ensure_tech_requirement_coverage,
        )

        business = "\n".join(
            [
                "1、投标保证金：人民币5万元。",
                "2、付款方式：按里程碑支付，合同签订后和终验通过两个节点，写明比例。",
                "3、本地化部署方案：支持私有化部署。",
            ]
        )
        chapters = [
            {
                "title": "商务文件",
                "children": [{"title": "投标保证金", "sourceRefs": ["B1"], "children": []}],
            }
        ]
        report: dict = {}
        covered = ensure_business_requirement_coverage(chapters, business, report=report)
        titles = [node["title"] for node in self._walk(covered)]
        self.assertIn("付款方式", titles)
        self.assertNotIn("本地化部署方案", titles)
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["boundByModel"], 1)
        self.assertEqual(report["backfilled"], 1)
        pay = next(node for node in self._walk(covered) if node["title"] == "付款方式")
        self.assertEqual(pay["part"], "business")
        self.assertIn("终验", pay["requirement"])

        quote = [
            {
                "title": "商务文件",
                "children": [
                    {"title": "商务条款响应表", "children": []},
                    {
                        "title": "报价明细表",
                        "part": "business",
                        "requirement": "分项为：软件许可、实施服务、英文版、课程版权。付款方式必填，按节点支付，终验通过的比例见附件。",
                        "idea": "",
                        "children": [],
                    },
                ],
            }
        ]
        shaped = ensure_business_response_structure(
            quote,
            "商务文件须含偏离表。未列示的视为已包含在报价范围内。",
            "",
        )
        shaped_titles = [node["title"] for node in self._walk(shaped)]
        self.assertIn("商务及需求偏离表", shaped_titles)
        self.assertIn("商务条款响应表", shaped_titles)
        self.assertIn("软件许可", shaped_titles)
        self.assertIn("课程版权", shaped_titles)
        self.assertIn("付款方式及节点", shaped_titles)
        pay_node = next(node for node in self._walk(shaped) if node["title"] == "付款方式及节点")
        self.assertIn("终验", pay_node["requirement"])

        narrow = [
            {
                "title": "无重大违法",
                "sourceRefs": ["B1"],
                "requirement": "须逐项声明。",
                "children": [],
            }
        ]
        ensure_business_response_structure(
            narrow,
            "1、无重大违法及失信声明：无重大违法记录、重大安全事故、重大质量纠纷、严重失信名单。",
            "",
        )
        self.assertEqual(narrow[0]["title"], "无重大违法及失信声明")
        self.assertIn("严重失信", narrow[0]["idea"])

        tech_chapters = [{"title": "技术方案", "children": []}]
        tech_covered = ensure_tech_requirement_coverage(
            tech_chapters,
            "1、登录：支持双因素。",
            "1、报价明细：软件许可、实施服务。\n2、产品演示材料：演示环境、演示脚本和关键功能截图。",
            "tech",
        )
        tech_titles = [node["title"] for node in self._walk(tech_covered)]
        self.assertIn("登录", tech_titles)
        self.assertIn("产品演示材料", tech_titles)
        self.assertNotIn("报价明细", tech_titles)

    def test_generate_outline_requires_harness_and_drops_direct_llm(self) -> None:
        from app.engines import e_writer
        from app.engines.writer_harness import HarnessError

        self.assertFalse(hasattr(e_writer, "_call_outline_llm"))
        with self.assertRaises(HarnessError):
            e_writer.generate_outline("示范项目", [], [], harness=None)


class TenderOriginalPaginationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_text_is_materialized_untruncated_and_paged(self) -> None:
        from app.engines.writer_tool_runtime import (
            TENDER_ORIGINAL_PAGE_CHARS,
            materialize_full_tender_text,
            original_tender_page_count,
            read_tender_text,
        )

        text = "招标正文段落。" * (TENDER_ORIGINAL_PAGE_CHARS // 2)  # 刚好跨 2 页以上
        folder = materialize_full_tender_text(self.workdir, text)
        original_file = folder / "original.txt"
        self.assertTrue(original_file.exists())
        self.assertEqual(original_file.read_text(encoding="utf-8"), text)

        total_pages = original_tender_page_count(text)
        self.assertGreaterEqual(total_pages, 2)

        page1 = read_tender_text(self.workdir, section="original", page=1)
        self.assertIn(f"1/{total_pages}", page1)
        self.assertIn("还没读完", page1)

        last_page = read_tender_text(self.workdir, section="original", page=total_pages)
        self.assertIn(f"{total_pages}/{total_pages}", last_page)
        self.assertNotIn("还没读完", last_page)

    def test_keyword_query_still_works_on_original_section(self) -> None:
        from app.engines.writer_tool_runtime import materialize_full_tender_text, read_tender_text

        materialize_full_tender_text(self.workdir, "第一行：应提供全天候热线\n第二行：支持双因素登录\n")
        hit = read_tender_text(self.workdir, section="original", query="热线")
        self.assertIn("全天候热线", hit)
        self.assertNotIn("双因素登录", hit)

    def test_no_summary_fallback_when_original_present(self) -> None:
        from app.engines.writer_tool_runtime import materialize_full_tender_text, read_tender_text

        materialize_full_tender_text(self.workdir, "招标正文原文内容")
        text = read_tender_text(self.workdir, project_id="should-not-be-used", section="original")
        self.assertIn("招标正文原文内容", text)


class DraftDocKindBranchAndMirrorTest(unittest.TestCase):
    """WriterDraft 按 doc_kind 拆分 / 镜像，用内存 sqlite，不接真实 Postgres。"""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("WRITER_WORKSPACE_ROOT", tempfile.mkdtemp())
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base, WriterDraft

        cls.WriterDraft = WriterDraft
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.Session()
        self.db.query(self.WriterDraft).delete()
        self.db.commit()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def _legacy_draft(self, **overrides):
        defaults = dict(
            project_id="proj-1",
            doc_kind="tech",
            model_id="deepseek-v4-pro",
            selected_knowledge_json=["doc-1"],
            selected_product_library_id="lib-1",
            settings_json={"page": {"target": 30}},
            interpret_source="reuse",
            outline_json=[
                {"id": "a", "parentId": None, "title": "技术方案", "num": "一、"},
                {
                    "id": "a1",
                    "parentId": "a",
                    "title": "总体架构",
                    "num": "（一）",
                    "part": "tech",
                    "requirement": "应实现架构设计",
                },
                {"id": "b", "parentId": None, "title": "商务资信", "num": "二、"},
                {"id": "b1", "parentId": "b", "title": "营业执照", "num": "（一）", "part": "business"},
            ],
            chapter_contents_json={"a1": "架构正文", "b1": "执照原文"},
            knowledge_refs_json={"a1": [{"docId": "d1"}]},
            step=3,
        )
        defaults.update(overrides)
        draft = self.WriterDraft(**defaults)
        self.db.add(draft)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def test_branch_legacy_draft_splits_outline_and_keeps_shared_fields(self) -> None:
        from app.writer_tracks import branch_legacy_draft

        legacy = self._legacy_draft()
        business = branch_legacy_draft(self.db, legacy, "business")

        self.assertEqual(business.doc_kind, "business")
        self.assertEqual({n["id"] for n in business.outline_json}, {"b", "b1"})
        self.assertEqual(business.chapter_contents_json, {"b1": "执照原文"})
        self.assertEqual(business.knowledge_refs_json, {})
        # 共享字段原样拷贝（不是同一个 list/dict 引用）
        self.assertEqual(business.model_id, "deepseek-v4-pro")
        self.assertEqual(business.selected_knowledge_json, ["doc-1"])
        self.assertIsNot(business.selected_knowledge_json, legacy.selected_knowledge_json)
        self.assertEqual(business.settings_json, {"page": {"target": 30}})
        # 旧行留下技术标那一半，doc_kind 不变
        self.assertEqual(legacy.doc_kind, "tech")
        self.assertEqual({n["id"] for n in legacy.outline_json}, {"a", "a1"})
        self.assertEqual(legacy.chapter_contents_json, {"a1": "架构正文"})
        # legacy.step=3（已过第二步）时，新行从第 3 步开始，不强迫它重走标书设置/解读
        self.assertEqual(business.step, 3)

    def test_branch_keeps_early_step_for_unfinished_legacy(self) -> None:
        from app.writer_tracks import branch_legacy_draft

        legacy = self._legacy_draft(step=2, outline_json=[], chapter_contents_json={}, knowledge_refs_json={})
        business = branch_legacy_draft(self.db, legacy, "business")
        self.assertEqual(business.step, 2)

    def test_mirror_shared_fields_updates_sibling_but_not_outline(self) -> None:
        from app.writer_tracks import mirror_shared_fields

        tech = self._legacy_draft(doc_kind="tech")
        business = self._legacy_draft(
            doc_kind="business",
            model_id="old-model",
            outline_json=[{"id": "x", "parentId": None, "title": "原目录"}],
        )

        sibling = mirror_shared_fields(
            self.db, tech, {"modelId": "deepseek-v4-pro", "settings": {"page": {"target": 50}}}
        )
        self.assertIsNotNone(sibling)
        self.db.refresh(business)
        self.assertEqual(business.model_id, "deepseek-v4-pro")
        self.assertEqual(business.settings_json, {"page": {"target": 50}})
        # outline 不在共享字段里，镜像后商务标自己的目录纹丝不动
        self.assertEqual(business.outline_json, [{"id": "x", "parentId": None, "title": "原目录"}])

    def test_mirror_shared_fields_ignores_outline_only_patch(self) -> None:
        from app.writer_tracks import mirror_shared_fields

        tech = self._legacy_draft(doc_kind="tech")
        self._legacy_draft(doc_kind="business", model_id="untouched-model")

        sibling = mirror_shared_fields(self.db, tech, {"outline": [{"id": "z", "parentId": None, "title": "新目录"}]})
        self.assertIsNone(sibling)

    def test_mirror_shared_fields_noop_without_sibling(self) -> None:
        from app.writer_tracks import mirror_shared_fields

        solo = self._legacy_draft(project_id="proj-solo", doc_kind="tech")
        sibling = mirror_shared_fields(self.db, solo, {"modelId": "whatever"})
        self.assertIsNone(sibling)

    def test_step_mirrors_only_while_both_tracks_are_still_in_setup(self) -> None:
        from app.writer_tracks import mirror_shared_fields

        tech = self._legacy_draft(project_id="proj-step", doc_kind="tech", step=1)
        early = self._legacy_draft(project_id="proj-step", doc_kind="business", step=1, outline_json=[])
        mirror_shared_fields(self.db, tech, {"step": 2})
        self.db.refresh(early)
        self.assertEqual(early.step, 2)

        early.step = 4
        self.db.commit()
        mirror_shared_fields(self.db, tech, {"step": 2})
        self.db.refresh(early)
        self.assertEqual(early.step, 4)

        tech.step = 4
        self.db.commit()
        mirror_shared_fields(self.db, tech, {"step": 4})
        self.db.refresh(early)
        self.assertEqual(early.step, 4)

    def test_unique_constraint_rejects_duplicate_doc_kind(self) -> None:
        from sqlalchemy.exc import IntegrityError

        self._legacy_draft(project_id="proj-uniq", doc_kind="tech")
        with self.assertRaises(IntegrityError):
            self._legacy_draft(project_id="proj-uniq", doc_kind="tech")
        self.db.rollback()


TENDER_A = """
第四章 技术与功能需求
本章所列为投标人技术响应的核心内容。投标人应对每项需求说明“满足/部分满足/不满足”、实现方式、标准功能或定制开发属性、交付周期及偏离说明。
8.1 投标文件组成
• 投标函及投标承诺。
• 法定代表人身份证明或授权委托书。
• 投标人基本情况、资质证照、财务及信用情况。
• 同类项目案例及证明材料，重点说明医疗、制药、质量体系相关客户案例。
• 技术方案及逐项需求响应表。
• 本地化部署和安全方案。
• 系统接口与数据迁移/初始化方案。
• 项目实施计划、团队配置、风险控制方案。
• 售后服务、培训与运维方案。
• 报价明细表及商务条款响应表。
8.2 技术响应要求
投标人应按照“满足/部分满足/不满足”逐项响应，并说明实现方式。对于需要定制开发、第三方产品、额外授权或存在前提条件的内容，须在偏离表中明确列示。
第九章 合同主要条款
9.1 合同范围
"""

TENDER_B = """
二、响应文件组成
商务文件包括：
1. 投标函
2. 报价一览表
技术文件包括：
1. 技术规格偏离表
2. 项目实施计划
应答要求：投标人须对技术规格逐条作出无偏离响应，偏离处单独列表说明。
"""

TECH_A = [
    "技术方案及逐项需求响应表",
    "本地化部署和安全方案",
    "系统接口与数据迁移/初始化方案",
    "项目实施计划、团队配置、风险控制方案",
    "售后服务、培训与运维方案",
]
BIZ_A = [
    "投标函及投标承诺",
    "法定代表人身份证明或授权委托书",
    "投标人基本情况、资质证照、财务及信用情况",
    "同类项目案例及证明材料，重点说明医疗、制药、质量体系相关客户案例",
    "报价明细表及商务条款响应表",
]


class TenderSourceOutlineTest(unittest.TestCase):
    def _titles(self, nodes: list[dict]) -> list[str]:
        found: list[str] = []

        def walk(tree: list[dict]) -> None:
            for node in tree:
                found.append(node["title"])
                walk(node.get("children") or [])

        walk(nodes)
        return found

    def test_two_tenders_keep_their_own_composition_and_response_words(self) -> None:
        from app.engines.e_writer import (
            BUSINESS_OUTLINE_PROMPT,
            OUTLINE_SYSTEM_PROMPT,
            SOFTWARE_TECH_OUTLINE_PROMPT,
            _build_outline_user_message,
            _normalize_outline,
            annotate_composition,
            chapter_follows_response_rule,
        )
        from app.engines.writer_harness import ENG_OUTLINE_SYSTEM, WATER_OUTLINE_SYSTEM
        from app.engines.tender_toc import (
            composition_for_volume,
            extract_bid_composition,
            extract_response_rules,
            response_checks,
        )
        from app.engines.writer_harness import _coverage_problems

        items_a = extract_bid_composition(TENDER_A)
        items_b = extract_bid_composition(TENDER_B)
        self.assertEqual([item["title"] for item in composition_for_volume(items_a, "tech")], TECH_A)
        self.assertEqual([item["title"] for item in composition_for_volume(items_a, "business")], BIZ_A)
        self.assertEqual(
            [item["title"] for item in composition_for_volume(items_b, "tech")],
            ["技术规格偏离表", "项目实施计划"],
        )
        self.assertEqual(
            [item["title"] for item in composition_for_volume(items_b, "business")],
            ["投标函", "报价一览表"],
        )
        self.assertEqual(extract_bid_composition("项目概况如下。本合同条款如下。"), [])

        rules_a = "\n".join(extract_response_rules(TENDER_A))
        rules_b = "\n".join(extract_response_rules(TENDER_B))
        checks_a = response_checks(rules_a)
        checks_b = response_checks(rules_b)
        self.assertIn("不满足", checks_a)
        self.assertIn("实现方式", checks_a)
        self.assertTrue(any("偏离" in item for item in checks_a))
        self.assertIn("无偏离", checks_b)
        self.assertIn("逐条", checks_b)
        self.assertNotIn("部分满足", checks_b)
        self.assertNotEqual(checks_a, checks_b)

        prose = "本方案采用成熟产品实现全部功能，完全响应招标要求。"
        problems = _coverage_problems([{"title": "实现说明"}], prose, [], False, None, 0, checks_a)
        self.assertTrue(any("不满足" in item for item in problems))
        ok_b = "本条逐条作出无偏离响应，不存在额外条件。"
        self.assertEqual(
            _coverage_problems([{"title": "无偏离"}], ok_b, [], False, None, 0, checks_b),
            [],
        )

        self.assertFalse(chapter_follows_response_rule("投标函"))
        self.assertFalse(chapter_follows_response_rule("报价明细表"))
        self.assertFalse(chapter_follows_response_rule("付款方式及节点"))
        self.assertFalse(chapter_follows_response_rule("营业执照"))
        self.assertTrue(chapter_follows_response_rule("技术方案"))
        self.assertTrue(chapter_follows_response_rule("商务条款响应表"))

        model = [
            {"title": "合同主要条款", "children": [{"title": "付款节奏", "children": []}]},
            {"title": "技术方案及逐项需求响应表", "children": [{"title": "登录认证", "children": []}]},
        ]
        problems = annotate_composition(model, composition_for_volume(items_a, "tech"))
        # 智能体编的章一个都不删、不搬、不重排，只打标并报出对不上的地方
        self.assertEqual(
            [node["title"] for node in model],
            ["合同主要条款", "技术方案及逐项需求响应表"],
        )
        self.assertIn("登录认证", self._titles(model))
        self.assertTrue(model[1]["composition"])
        self.assertEqual(model[1]["part"], "tech")
        self.assertTrue(any("合同主要条款" in item for item in problems))
        self.assertTrue(any("本地化部署和安全方案" in item for item in problems))
        self.assertEqual(annotate_composition(model, []), [])

        # 打上 composition 的章保留完整章名，不被压成短标题
        business = [{"title": item, "children": []} for item in BIZ_A]
        annotate_composition(business, composition_for_volume(items_a, "business"))
        nodes = _normalize_outline({"chapters": business})
        case_title = next(node["title"] for node in nodes if "同类项目案例" in node["title"])
        self.assertIn("质量体系相关客户案例", case_title)

        tech_prompt = _build_outline_user_message("示范项目", TENDER_A, None, [], [], doc_kind="tech")
        business_prompt = _build_outline_user_message("示范项目", TENDER_A, None, [], [], doc_kind="business")
        other_prompt = _build_outline_user_message("示范项目", TENDER_B, None, [], [], doc_kind="tech")
        empty_prompt = _build_outline_user_message("示范项目", "项目概况如下。", None, [], [], doc_kind="tech")
        tech_head = tech_prompt.split("----------", 1)[0]
        business_head = business_prompt.split("----------", 1)[0]
        other_head = other_prompt.split("----------", 1)[0]
        self.assertIn("技术方案及逐项需求响应表", tech_head)
        self.assertNotIn("投标函及投标承诺", tech_head)
        self.assertIn("投标函及投标承诺", business_head)
        self.assertNotIn("本地化部署和安全方案", business_head)
        self.assertIn("满足/部分满足/不满足", tech_head)
        self.assertIn("技术规格偏离表", other_head)
        self.assertIn("无偏离", other_head)
        self.assertNotIn("部分满足", other_head)
        self.assertIn("没有抽出这份清单", empty_prompt)
        self.assertIn("不要套用「满足/部分满足/不满足」", empty_prompt)
        for prompt in (tech_prompt, business_prompt, OUTLINE_SYSTEM_PROMPT):
            self.assertNotIn("必须单独成章", prompt)
            self.assertNotIn("报价明细按", prompt)
        self.assertIn("商务标不按篇幅加章", business_prompt)
        self.assertIn("评标办法不进目录", OUTLINE_SYSTEM_PROMPT)
        self.assertIn("格式节不限章号", OUTLINE_SYSTEM_PROMPT)
        self.assertNotIn("采购需求", BUSINESS_OUTLINE_PROMPT)
        self.assertIn("采购需求", SOFTWARE_TECH_OUTLINE_PROMPT)
        self.assertNotIn("第一章写「编制说明」", ENG_OUTLINE_SYSTEM)
        self.assertNotIn("可以补 2", ENG_OUTLINE_SYSTEM)
        self.assertIn("形式评审", ENG_OUTLINE_SYSTEM)
        self.assertIn("重难点分析", ENG_OUTLINE_SYSTEM)
        self.assertIn("短措施名", ENG_OUTLINE_SYSTEM)
        self.assertIn("包括但不限于", ENG_OUTLINE_SYSTEM)
        self.assertIn("二级目录是施工理解，不是把一级章名拆开", ENG_OUTLINE_SYSTEM)
        self.assertIn("禁止用「保障体系」「主要措施」「检查与考核」", ENG_OUTLINE_SYSTEM)
        self.assertIn("二级目录是施工理解，不是把一级章名拆开", WATER_OUTLINE_SYSTEM)
        self.assertNotIn("高标准农田", ENG_OUTLINE_SYSTEM)
        self.assertNotIn("水利工程使用同一份", ENG_OUTLINE_SYSTEM)
        self.assertIn("高标准农田", WATER_OUTLINE_SYSTEM)
        self.assertIn("保证措施汇总", WATER_OUTLINE_SYSTEM)
        self.assertIn("施工期不得中断灌排", WATER_OUTLINE_SYSTEM)
        self.assertIn("重难点分析、重难点解决措施、保证措施汇总", WATER_OUTLINE_SYSTEM)
        self.assertNotIn("灌排", ENG_OUTLINE_SYSTEM)


class OutlineCheckOnlyTest(unittest.TestCase):
    def test_missing_requirement_is_reported_without_adding_a_chapter(self) -> None:
        from app.engines.e_writer import _assemble_outline

        chapters = [{"title": "技术方案", "children": [{"title": "用户组织权限", "children": [], "sourceRefs": ["T1"]}]}]
        tech = "1、用户组织权限：角色分级\n2、审计追踪合规：日志保留180天\n"
        _coverage, _ledger, notes = _assemble_outline(
            chapters,
            composition=[],
            tender_toc=None,
            score_rules=[],
            tech_text=tech,
            business_text="",
            tender_text="",
            doc_kind="tech",
        )

        def titles_of(nodes):
            found = []
            for node in nodes:
                found.append(node.get("title") or "")
                found.extend(titles_of(node.get("children") or []))
            return found

        self.assertEqual(titles_of(chapters), ["技术方案", "用户组织权限"])
        self.assertTrue(any("T2" in item for item in notes))
        self.assertFalse(any("T1" in item and "没有目录节点" in item for item in notes))

    def test_review_criterion_is_unwrapped_and_not_kept(self) -> None:
        from app.engines.e_writer import _assemble_outline

        chapters = [
            {
                "title": "符合第七章投标文件格式的要求",
                "children": [
                    {"title": "投标文件组成", "children": []},
                    {"title": "形式评审", "children": []},
                    {"title": "投标函（不含报价）", "children": []},
                    {"title": "投标有效期", "children": []},
                    {"title": "农民工工资支付保障承诺", "children": []},
                    {"title": "投标报价", "children": []},
                ],
            }
        ]
        _coverage, _ledger, _notes = _assemble_outline(
            chapters,
            composition=[
                {"title": "投标函（不含报价）", "volume": "business"},
                {"title": "农民工工资支付保障承诺", "volume": "business"},
            ],
            tender_toc=None,
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text="",
            doc_kind="business",
        )
        self.assertEqual(
            [node.get("title") for node in chapters],
            ["投标函（不含报价）", "农民工工资支付保障承诺"],
        )

    def test_format_phrase_inside_review_sentence_still_unwraps(self) -> None:
        from app.engines.e_writer import drop_review_shells

        chapters = [
            {
                "title": "符合第七章“投标文件格式”的要求",
                "children": [
                    {"title": "投标函（不含报价）", "children": []},
                    {"title": "商务文件详细评审资料", "children": []},
                ],
            }
        ]
        drop_review_shells(
            chapters,
            [{"title": "投标文件格式", "volume": "business"}],
            "business",
        )
        self.assertEqual(
            [node.get("title") for node in chapters],
            ["投标函（不含报价）", "商务文件详细评审资料"],
        )

    def test_chapter7_files_are_the_top_level(self) -> None:
        from app.engines.e_writer import _assemble_outline

        chapters = [
            {
                "title": "符合第七章“投标文件格式”的要求",
                "children": [
                    {"title": "投标函（不含报价）", "children": []},
                    {"title": "资格审查资料", "children": []},
                    {"title": "其他资料", "children": [{"title": "商务文件其他材料", "children": []}]},
                ],
            }
        ]
        composition = [
            {"title": "投标函（不含报价）", "volume": "business"},
            {"title": "资格审查资料", "volume": "business"},
            {"title": "其他资料", "volume": "business"},
        ]
        _assemble_outline(
            chapters,
            composition=composition,
            tender_toc=None,
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text="",
            doc_kind="business",
        )
        self.assertEqual([node.get("title") for node in chapters], [item["title"] for item in composition])
        other = chapters[2]
        self.assertEqual(other["children"][0]["title"], "商务文件其他材料")

    def test_missing_format_file_is_added_and_appendix_is_kept(self) -> None:
        from app.engines.e_writer import _assemble_outline, _collapse_original_form_chapters, ensure_named_roles

        chapters = [
            {
                "title": "投标函（不含报价）",
                "children": [{"title": "投标函附录", "children": [{"title": "填写栏", "children": []}]}],
            },
            {
                "title": "项目管理机构",
                "children": [
                    {"title": "项目经理资格", "children": []},
                    {"title": "施工负责人资格", "children": []},
                ],
                "requirement": "技术负责人须具备水利水电相关专业中级及以上资格。施工技术负责人每月驻场。",
            },
        ]
        _collapse_original_form_chapters(chapters)
        self.assertEqual(chapters[0]["children"][0]["title"], "投标函附录")
        self.assertEqual(chapters[0]["children"][0]["children"], [])
        ensure_named_roles(chapters)
        role_titles = [node["title"] for node in chapters[1]["children"]]
        self.assertIn("技术负责人", role_titles)
        self.assertIn("施工技术负责人", role_titles)

        _coverage, _ledger, _notes = _assemble_outline(
            [{"title": "投标函（不含报价）", "children": []}],
            composition=[
                {"title": "投标函（不含报价）", "volume": "business"},
                {"title": "商务文件详细评审资料", "volume": "business"},
            ],
            tender_toc=None,
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text="",
            doc_kind="business",
        )
        self.assertEqual(
            [node.get("title") for node in _coverage["_chapters"]],
            ["投标函（不含报价）", "商务文件详细评审资料"],
        )

    def test_eval_method_and_contract_are_not_bid_chapters(self) -> None:
        from app.engines.e_writer import _assemble_outline

        tender = "\n".join(
            [
                "第三章 评标办法",
                "形式评审",
                "二、联合体投标人",
                "三、未出现异常情形",
                "投标文件制作机器码",
                "四、未出现投标报价",
                "五、签字盖章",
                "第四章 合同条款及格式",
                "投标报价与价格清单",
                "最高投标限价",
                "第五章 发包人要求",
                "施工组织设计",
                "第七章 投标文件格式",
                "一、投标函（不含报价）",
                "二、联合体协议书（如有）",
                "三、其他资料",
            ]
        )
        chapters = [
            {
                "title": "联合体投标人",
                "children": [
                    {"title": "联合体协议书（如有）", "children": []},
                    {"title": "联合体组成与牵头人", "children": []},
                ],
            },
            {
                "title": "未出现异常情形",
                "children": [
                    {"title": "投标文件制作机器码", "children": []},
                    {"title": "联系人及联系电话", "children": []},
                ],
            },
            {
                "title": "未出现投标报价",
                "children": [
                    {"title": "投标报价与价格清单", "children": []},
                    {"title": "商务文件不含报价", "children": []},
                ],
            },
            {"title": "签字盖章", "children": [{"title": "签字盖章总体要求", "children": []}]},
            {"title": "投标函（不含报价）", "children": []},
            {"title": "其他资料", "children": [{"title": "商务文件其他材料", "children": []}]},
        ]
        coverage, _ledger, _notes = _assemble_outline(
            chapters,
            composition=[
                {"title": "投标函（不含报价）", "volume": "business"},
                {"title": "联合体协议书（如有）", "volume": "business"},
                {"title": "其他资料", "volume": "business"},
            ],
            tender_toc=None,
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text=tender,
            doc_kind="business",
        )
        titles = [node.get("title") for node in coverage["_chapters"]]
        self.assertEqual(titles, ["投标函（不含报价）", "联合体协议书（如有）", "其他资料"])
        blob = json.dumps(coverage["_chapters"], ensure_ascii=False)
        for banned in ("未出现异常情形", "未出现投标报价", "签字盖章", "投标报价与价格清单", "联合体投标人", "机器码"):
            self.assertNotIn(banned, blob)
        other = coverage["_chapters"][2]
        self.assertEqual(other["children"][0]["title"], "商务文件其他材料")

    def test_review_standards_do_not_stay_even_if_extracted(self) -> None:
        from app.engines.e_writer import _assemble_outline

        chapters = [
            {"title": "投标文件制作机器码相同", "children": []},
            {"title": "符合第七章“投标文件格式”的要求", "children": []},
            {"title": "未出现投标报价", "children": []},
            {"title": "签字盖章", "children": []},
            {"title": "投标函（不含报价）", "children": []},
            {"title": "法定代表人身份证明和授权委托书", "children": []},
        ]
        coverage, _ledger, _notes = _assemble_outline(
            chapters,
            composition=[
                {"title": "投标文件制作机器码相同", "volume": "business"},
                {"title": "符合第七章“投标文件格式”的要求", "volume": "business"},
                {"title": "投标函（不含报价）", "volume": "business"},
                {"title": "法定代表人身份证明和授权委托书", "volume": "business"},
            ],
            tender_toc=None,
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text="第三章 评标办法\n投标文件制作机器码相同\n第七章 投标文件格式\n一、投标函（不含报价）",
            doc_kind="business",
        )
        titles = [node.get("title") for node in coverage["_chapters"]]
        self.assertEqual(titles, ["投标函（不含报价）", "法定代表人身份证明和授权委托书"])


class SoftwareRequirementSkeletonTest(unittest.TestCase):
    """软件技术标：一级章是投标文件组成，二三级是招标需求原结构。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.path = os.path.join(os.path.dirname(__file__), "fixtures", "bain_tender.docx")

    def _tree_and_composition(self):
        from app.engines.docx_extract import extract_document_plain_text
        from app.engines.tender_toc import composition_for_volume, extract_bid_composition, extract_requirement_tree

        text = extract_document_plain_text(self.path)
        tree = extract_requirement_tree(self.path)
        composition = composition_for_volume(extract_bid_composition(text), "tech")
        return text, tree, composition

    def _titles(self, node: dict) -> list[str]:
        return [child.get("title") or "" for child in node.get("children") or []]

    def test_bain_tree_keeps_codes_and_bullets(self) -> None:
        from app.engines.tender_toc import extract_stipulated_toc

        _text, tree, composition = self._tree_and_composition()
        by_no = {section["clauseNo"]: section for section in tree}
        self.assertEqual(tree[0]["title"], "项目理解与建设目标")
        self.assertEqual([item["code"] for item in by_no["4.1"]["items"]], [f"F-0{n}" for n in range(1, 7)])
        self.assertEqual(by_no["4.1"]["items"][0]["name"], "组织与账号管理")
        self.assertEqual(len(by_no["4.2"]["items"]), 7)
        self.assertEqual([item["code"] for item in by_no["4.3"]["items"]], ["F-07", "F-08", "F-09", "F-10", "F-11"])
        self.assertEqual([item["code"] for item in by_no["4.5"]["items"]], ["F-12", "F-13", "F-14", "F-15", "F-16", "F-17"])
        self.assertEqual(len(by_no["5.1"]["items"]), 4)
        self.assertIn("技术方案及逐项需求响应表", [item["title"] for item in composition])
        toc = extract_stipulated_toc(self.path)
        self.assertGreater(len(toc["tech"]), 1)
        self.assertEqual(len(toc["reqTree"]), len(tree))

    def test_sections_land_under_the_matching_format_file(self) -> None:
        from app.engines.e_writer import _assemble_outline

        text, tree, composition = self._tree_and_composition()
        chapters = [{"title": item["title"], "children": []} for item in composition]
        chapters[1]["children"] = [{"title": "F-07 放错了", "children": []}]
        _assemble_outline(
            chapters,
            composition=composition,
            tender_toc={"reqTree": tree},
            score_rules=[],
            tech_text="1、组织与账号管理：支持5500名用户\n",
            business_text="",
            tender_text=text,
            doc_kind="tech",
        )
        by_title = {node["title"]: node for node in chapters}
        tech = by_title["技术方案及逐项需求响应表"]
        self.assertEqual(self._titles(tech)[0], "需求响应偏离表")
        self.assertIn("4.1 用户、组织与权限管理", self._titles(tech))
        self.assertIn("5.3 性能与容量要求", self._titles(tech))
        section = next(child for child in tech["children"] if child["title"].startswith("4.1"))
        self.assertEqual(
            self._titles(section),
            ["F-01 组织与账号管理", "F-02 超级管理员", "F-03 一般管理员", "F-04 学员角色", "F-05 临时访客角色", "F-06 权限模型"],
        )
        self.assertIn("5500", section["children"][0]["requirement"])
        self.assertIn("应答写法", section["children"][0]["idea"])
        self.assertEqual(section["children"][0]["sourceRefs"], ["T1"])
        self.assertIn("5.1 系统对接范围", self._titles(by_title["系统接口与数据迁移/初始化方案"]))
        self.assertIn("5.2 本地化部署要求", self._titles(by_title["本地化部署和安全方案"]))
        self.assertIn("5.4 安全要求", self._titles(by_title["本地化部署和安全方案"]))
        self.assertIn("6.1 实施阶段", self._titles(by_title["项目实施计划、团队配置、风险控制方案"]))
        self.assertIn("7.1 质保与服务", self._titles(by_title["售后服务、培训与运维方案"]))
        self.assertNotIn("F-07 放错了", self._titles(by_title["本地化部署和安全方案"]))
        moved = next(child for child in next(n for n in tech["children"] if n["title"].startswith("4.3"))["children"] if "F-07" in child["title"])
        self.assertEqual(moved["title"], "F-07 文件变更触发")

    def test_business_volume_ignores_the_requirement_tree(self) -> None:
        from app.engines.e_writer import _assemble_outline

        _text, tree, _composition = self._tree_and_composition()
        chapters = [{"title": "投标函及投标承诺", "children": []}]
        _assemble_outline(
            chapters,
            composition=[{"title": "投标函及投标承诺", "volume": "business"}],
            tender_toc={"reqTree": tree},
            score_rules=[],
            tech_text="",
            business_text="",
            tender_text="投标人应逐项响应。",
            doc_kind="business",
        )
        self.assertEqual(chapters[0]["children"], [])
