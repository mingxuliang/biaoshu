"""软件服务标：产品功能库直出应标。内存 sqlite + 桩，不接模型、不接对象存储。"""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("WRITER_WORKSPACE_ROOT", tempfile.mkdtemp())


class MatchChunkTest(unittest.TestCase):
    def _catalog(self, roots: int, kids: int) -> tuple[str, set[str]]:
        lines, ids = [], set()
        for r in range(roots):
            rid = f"r{r}"
            ids.add(rid)
            lines.append(f"{rid}\t功能{r}\t一级\t说明")
            for k in range(kids):
                kid = f"r{r}k{k}"
                ids.add(kid)
                lines.append(f"{kid}\t子功能{r}-{k}\t功能{r}\t说明")
        return "\n".join(lines), ids

    def test_big_catalog_is_split_by_root_and_results_merged(self):
        from app.engines import product_match as pm

        catalog, ids = self._catalog(roots=20, kids=9)  # 200 行，超过 120
        chunks = pm._catalog_chunks(catalog)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            first = chunk.split("\n")[0].split("\t")
            self.assertEqual(first[2], "一级")  # 不会把一级和它的下级拆开
        self.assertEqual(sum(len(c.split("\n")) for c in chunks), 200)

        seen_chunks: list[str] = []

        def fake_chat(**kwargs):
            user = kwargs["messages"][1]["content"]
            seen_chunks.append(user)
            hit = "r0k0" if "\nr0k0\t" in "\n" + user else "r19k0"
            return '{"items":[{"chapterId":"c1","featureIds":["%s"]}]}' % hit

        chapters = [{"chapterId": "c1", "num": "1", "title": "F-01", "requirement": "x"}]
        with mock.patch.object(pm, "chat_complete", fake_chat):
            out = pm.match_chapters_to_features(chapters, catalog, ids, None)
        self.assertEqual(len(seen_chunks), len(chunks))
        self.assertEqual(sorted(out["c1"]), ["r0k0", "r19k0"])

    def test_failed_batch_is_reported_not_marked_unmatched(self):
        from app.engines import product_match as pm
        from app.engines.llm import LlmError

        catalog, ids = self._catalog(2, 1)
        chapters = [{"chapterId": f"c{i}", "num": str(i), "title": f"t{i}", "requirement": "x"} for i in range(25)]
        calls = {"n": 0}

        def fake_chat(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise LlmError("boom")
            return '{"items":[{"chapterId":"c0","featureIds":["r0"]}]}'

        stats: dict = {}
        with mock.patch.object(pm, "chat_complete", fake_chat):
            out = pm.match_chapters_to_features(chapters, catalog, ids, None, stats=stats)
        self.assertEqual(out["c0"], ["r0"])
        # 第二批（c20..c24）调用失败，且没有任何结果
        self.assertEqual(stats["failedChapterIds"], [f"c{i}" for i in range(20, 25)])

    def test_all_failed_raises(self):
        from app.engines import product_match as pm
        from app.engines.llm import LlmError

        catalog, ids = self._catalog(1, 1)
        with mock.patch.object(pm, "chat_complete", mock.Mock(side_effect=LlmError("x"))):
            with self.assertRaises(LlmError):
                pm.match_chapters_to_features(
                    [{"chapterId": "c1", "num": "1", "title": "t", "requirement": "x"}], catalog, ids, None
                )


class _DbCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.models import Base

        cls.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        from app.models import (
            Base,
            ProductFeature,
            ProductFeatureImage,
            ProductLibrary,
            WriterDraft,
        )

        for table in reversed(Base.metadata.sorted_tables):
            with self.engine.begin() as conn:
                conn.execute(table.delete())
        self.db = self.Session()
        self.db.add(ProductLibrary(id="lib1", name="时光易培"))
        self.db.add(
            ProductFeature(
                id="pfe1",
                library_id="lib1",
                name="用户组织与权限管理",
                module="用户中心",
                bid_copy="一两句短摘要",
                source_text="用户中心支持多级组织架构维护。\n角色权限可按岗位配置。",
                status="待审核",
            )
        )
        self.db.add(
            ProductFeatureImage(
                id="pimg1", feature_id="pfe1", caption="组织架构图", filename="a.png", storage_path="p/a.png"
            )
        )
        self.db.add(
            ProductFeature(id="pfe2", library_id="lib1", name="考试管理", module="考试中心", status="已入库")
        )
        self.outline = [
            {"id": "sec", "num": "4.1", "title": "技术方案", "part": "tech", "parentId": None},
            {
                "id": "c1",
                "num": "4.1.1",
                "title": "F-01 组织与账号管理",
                "part": "tech",
                "parentId": "sec",
                "requirement": "支持多级组织架构与角色权限管理。",
                "idea": "依据：T1",
                "sourceRefs": ["T1"],
            },
            {
                "id": "c2",
                "num": "4.1.2",
                "title": "F-02 在线直播",
                "part": "tech",
                "parentId": "sec",
                "requirement": "支持在线直播授课。",
                "idea": "依据：T2",
                "sourceRefs": ["T2"],
            },
        ]
        self.db.add(
            WriterDraft(
                id="d1",
                project_id="p1",
                doc_kind="tech",
                selected_product_library_id="lib1",
                outline_json=self.outline,
                chapter_contents_json={},
                knowledge_refs_json={
                    "c1": [{"source": "product", "docId": "lib1", "chapters": ["pfe1"], "mode": "ai"}],
                    "c2": [],
                },
                settings_json={},
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()


class OutlineMatchStatsTest(_DbCase):
    def test_stats_report_hit_unmatched_failed_and_pending(self):
        from app.engines import product_match as pm
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.knowledge_refs_json = {}

        def fake_match(chapters, catalog, valid_ids, model_id, name_to_id=None, stats=None):
            stats["failedChapterIds"] = ["c2"]
            return {"c1": ["pfe1"]}

        stats: dict = {}
        with mock.patch.object(pm, "match_chapters_to_features", fake_match):
            hit = pm.apply_outline_product_match(self.db, draft, keep_manual=False, stats=stats)
        self.assertEqual(hit, 1)
        self.assertEqual(stats["hit"], 1)
        self.assertEqual(stats["failedChapterIds"], ["c2"])
        self.assertEqual(stats["unmatched"], [])
        self.assertEqual(stats["pendingFeatures"], 1)  # pfe1 是待审核
        refs = draft.knowledge_refs_json
        self.assertIn("c1", refs)
        self.assertNotIn("c2", refs)  # 调用失败的章节不记成「已匹配、没有功能」

    def test_unmatched_titles_listed(self):
        from app.engines import product_match as pm
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.knowledge_refs_json = {}
        stats: dict = {}
        with mock.patch.object(
            pm,
            "match_chapters_to_features",
            lambda *a, **k: {"c1": ["pfe1"], "c2": []},
        ):
            pm.apply_outline_product_match(self.db, draft, keep_manual=False, stats=stats)
        self.assertEqual(stats["unmatched"], ["F-02 在线直播"])
        self.assertEqual(stats["total"], 2)  # 只算叶子章 F-01、F-02，4.1 小节不算

    def test_single_chapter_match_writes_back(self):
        from app.engines import product_match as pm
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.knowledge_refs_json = {}
        self.db.commit()
        with mock.patch.object(pm, "match_chapters_to_features", lambda *a, **k: {"c1": ["pfe1"]}):
            ok = pm.match_single_chapter(self.db, "d1", "c1")
        self.assertTrue(ok)
        self.db.expire_all()
        refs = self.db.get(WriterDraft, "d1").knowledge_refs_json
        self.assertEqual(refs["c1"][0]["chapters"], ["pfe1"])

    def test_single_chapter_match_failure_leaves_no_record(self):
        from app.engines import product_match as pm
        from app.engines.llm import LlmError
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.knowledge_refs_json = {}
        self.db.commit()
        with mock.patch.object(pm, "match_chapters_to_features", mock.Mock(side_effect=LlmError("x"))):
            ok = pm.match_single_chapter(self.db, "d1", "c1")
        self.assertFalse(ok)
        self.db.expire_all()
        self.assertEqual(self.db.get(WriterDraft, "d1").knowledge_refs_json, {})


class _FakeBinding:
    saved: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def persist_chapter(self, chapter_id, content, *, status, ai_round, part=None):
        _FakeBinding.saved[chapter_id] = content


class DirectChapterTest(_DbCase):
    def setUp(self):
        super().setUp()
        _FakeBinding.saved = {}

    def _run(self, chapter_id: str, decision: dict | None, gap_text: str = "补充的缺口应答。"):
        from app import tasks
        from app.engines import e_writer, standard_product

        agent_calls: list[dict] = []

        def fake_generate(*args, **kwargs):
            agent_calls.append({"args": args, "kwargs": kwargs})
            return "## 原始需求\n\n条款\n\n## 解决方案\n\n" + gap_text + "【此处插入图：1】"

        with (
            mock.patch("app.engines.writer_harness.DraftBinding", _FakeBinding),
            mock.patch.object(tasks, "_fill_vision", lambda images: None),
            mock.patch.object(
                tasks,
                "_writer_markdown_for_knowledge_image",
                lambda db, draft, src, idx, mode: f"![{src.get('caption')}](/api/writer-images/{src['id']}/file)",
            ),
            mock.patch.object(tasks, "_latest_checklist_data", lambda db, pid: ([], [])),
            mock.patch.object(e_writer, "generate_chapter_content", fake_generate),
            mock.patch.object(
                standard_product,
                "judge",
                lambda *a, **k: decision or {"verdict": "无", "source": "无", "featureIds": [], "sliceIds": [], "gap": "", "reason": ""},
            ),
        ):
            result = tasks._generate_one_chapter(self.db, "d1", chapter_id, "u1", "job1", enable_figures=False)
        return result, agent_calls

    def test_satisfied_uses_library_source_text_and_original_image(self):
        decision = {"verdict": "满足", "source": "标品", "featureIds": ["pfe1"], "sliceIds": [], "gap": "", "reason": ""}
        result, agent_calls = self._run("c1", decision)
        self.assertEqual(result, "tech")
        self.assertEqual(agent_calls, [])  # 满足时不再让模型写
        content = _FakeBinding.saved["c1"]
        self.assertIn("用户中心支持多级组织架构维护。", content)  # 库原文，不是 bid_copy 摘要
        self.assertNotIn("一两句短摘要", content)
        self.assertIn("![组织架构图](/api/writer-images/pimg1/file)", content)
        self.assertIn("响应情况：满足", content)
        self.assertIn("无偏离", content)
        self.assertIn("## 原始需求", content)

    def test_partial_appends_gap_only_and_strips_image_placeholders(self):
        decision = {
            "verdict": "部分满足",
            "source": "标品",
            "featureIds": ["pfe1"],
            "sliceIds": [],
            "gap": "缺少数据导出",
            "reason": "",
        }
        result, agent_calls = self._run("c1", decision)
        self.assertEqual(result, "tech")
        self.assertEqual(len(agent_calls), 1)
        content = _FakeBinding.saved["c1"]
        self.assertIn("用户中心支持多级组织架构维护。", content)
        self.assertIn("补充的缺口应答。", content)
        self.assertIn("响应情况：部分满足", content)
        self.assertNotIn("【此处插入图", content)

    def test_ledger_records_standard_product_source_and_status(self):
        from app.models import WriterDraft

        decision = {"verdict": "满足", "source": "标品", "featureIds": ["pfe1"], "sliceIds": [], "gap": "", "reason": ""}
        self._run("c1", decision)
        self.db.expire_all()
        settings = self.db.get(WriterDraft, "d1").settings_json
        row = settings["responses"]["T1"]
        self.assertEqual(row["source"], "标品")
        self.assertEqual(row["status"], "满足")
        self.assertEqual(settings["placedFeatures"]["pfe1"]["chapterId"], "c1")

    def test_judge_none_falls_back_to_agent_with_gap_prompt_data(self):
        # c2 的匹配记录是空列表：没有绑定功能，不走直出，交给智能体按「能力缺口」写
        result, agent_calls = self._run("c2", None)
        self.assertEqual(result, "tech")
        self.assertEqual(len(agent_calls), 1)
        product_features = agent_calls[0]["args"][8]
        self.assertEqual(product_features, [])  # 选了库但没命中：智能体按能力缺口写

    def test_judge_none_for_bound_feature_falls_back_to_agent(self):
        result, agent_calls = self._run("c1", None)
        self.assertEqual(result, "tech")
        self.assertEqual(len(agent_calls), 1)
        names = [f["name"] for f in agent_calls[0]["args"][8]]
        self.assertEqual(names, ["用户组织与权限管理"])
        self.assertEqual(agent_calls[0]["args"][8][0]["status"], "待审核")

    def test_unmatched_chapter_without_record_is_matched_lazily_and_not_forced_gap(self):
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.knowledge_refs_json = {}  # 目录阶段匹配失败：没有任何记录
        self.db.commit()
        with mock.patch(
            "app.engines.product_match.match_single_chapter", mock.Mock(return_value=False)
        ) as lazy:
            result, agent_calls = self._run("c1", None)
        lazy.assert_called_once()
        self.assertEqual(result, "tech")
        # 补匹配也失败：不能当作「库里没有」，所以不传空列表（空列表会强制写能力缺口）
        self.assertIsNone(agent_calls[0]["args"][8])

    def test_business_draft_never_uses_direct_path(self):
        from app import tasks
        from app.models import WriterDraft

        draft = self.db.get(WriterDraft, "d1")
        draft.doc_kind = "business"
        self.db.commit()
        with mock.patch.object(tasks, "_standard_chapter") as std:
            try:
                self._run("c1", None)
            except Exception:  # 商务章走别的分支，这里只关心没有调用直出
                pass
        std.assert_not_called()


class CoverageReportTest(unittest.TestCase):
    def test_prompt_marks_unreviewed_features(self):
        from app.engines import e_writer

        text = e_writer._build_chapter_context(
            "项目",
            "F-01",
            "idea",
            None,
            [],
            None,
            None,
            [
                {"name": "功能A", "module": "M", "status": "待审核", "bidCopy": "原文", "images": []},
                {"name": "功能B", "module": "M", "status": "已入库", "bidCopy": "原文", "images": []},
            ],
            "库",
        )
        self.assertIn("本公司产品能力", text)
        self.assertNotIn("已审核产品能力", text)
        self.assertIn("【功能A】（待审核）", text)
        self.assertNotIn("【功能B】（待审核）", text)

    def test_prompt_keeps_reviewed_wording_when_all_reviewed(self):
        from app.engines import e_writer

        text = e_writer._build_chapter_context(
            "项目", "F-01", "idea", None, [], None, None,
            [{"name": "功能B", "module": "M", "status": "已入库", "bidCopy": "原文", "images": []}],
            "库",
        )
        self.assertIn("本公司已审核产品能力", text)


if __name__ == "__main__":
    unittest.main()
