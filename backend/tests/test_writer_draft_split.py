"""技术标/商务标分离撰写：读原文分页、目录按 doc_kind 拆分迁移、共享字段镜像，不调用外部模型/真实数据库。"""

from __future__ import annotations

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
        self.assertIn("请先通读本份招标文件全文", prompt)
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
        self.assertIn("逐页调用通读", prompt)

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
        self.assertIn("约 30 页", tech)
        self.assertIn("超过招标应答的最低要求", tech)
        self.assertIn("本次编制分册：商务标", business)
        self.assertNotIn("约 30 页", business)
        self.assertIn("不需要按篇幅扩展内容", business)
        self.assertIn("覆盖合规即可", business)

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
