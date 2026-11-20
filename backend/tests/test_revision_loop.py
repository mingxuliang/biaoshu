"""修改闭环：刷新不丢改动、写回失败如实报错、材料类问题禁止采纳、工作稿原地替换，
并按工程类 / 软件服务类、商务册 / 技术册各验一遍。用内存 sqlite 和内存存储，不接 Postgres / MinIO / 模型。"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


class FakeStorage:
    """用字典顶替 MinIO：key -> bytes。"""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self._n = 0

    def put_bytes(self, prefix: str, data: bytes, ext: str = "") -> str:
        self._n += 1
        key = f"{prefix}/{self._n}{ext}"
        self.blobs[key] = data
        return key

    def exists(self, key) -> bool:
        return bool(key) and key in self.blobs

    def get_bytes(self, key) -> bytes:
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return self.blobs[key]

    def delete(self, key) -> None:
        if key and key in self.blobs:
            self.deleted.append(key)
            del self.blobs[key]

    @contextlib.contextmanager
    def as_local(self, key):
        data = self.get_bytes(key)
        fd, path = tempfile.mkstemp(suffix=".docx")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            yield path
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)


PARA_TEXT = "本项目工期方面，我司将尽力保证工期，确保按时交付。"
EXCERPT = "我司将尽力保证工期"
APPLY_TEXT = "我司承诺总工期不超过180日历天"


def make_docx(para_text: str = PARA_TEXT) -> bytes:
    import docx

    document = docx.Document()
    document.add_heading("第一章 工期响应", level=1)
    document.add_paragraph(para_text)
    document.add_paragraph("其余章节按招标文件要求逐项响应，附相关证明材料。")
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


class RevisionLoopBase(unittest.TestCase):
    category = "软件服务类"
    scope = "business"

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base
        from app.routers import revision

        # 每个用例一个独立的内存库，避免工作稿互相串
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.revision_mod = revision
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.fake = FakeStorage()
        patches = [
            mock.patch.object(revision, "storage", self.fake),
            mock.patch.object(revision, "require_project", lambda *a, **k: None),
            mock.patch.object(revision, "write_audit", lambda *a, **k: None),
            mock.patch.object(revision, "actor_from_request", lambda *a, **k: "测试"),
            mock.patch.object(revision, "project_label", lambda *a, **k: "测试项目"),
            # 任何一处走到模型都视为测试没有控制好输入
            mock.patch.object(revision, "llm_write_suggestion", side_effect=AssertionError("不该调用模型")),
            mock.patch.object(revision, "llm_rewrite_paragraph", return_value=""),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.request = mock.Mock()
        self.user = mock.Mock()
        self.project_id = self._seed_project()
        self.run, self.finding_id = self._seed_run(round_no=1)

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        self.engine.dispose()

    # ---- 造数据 ----
    def _seed_project(self) -> str:
        from app.models import Project

        project = Project(code=f"P-{self._testMethodName}", name="示范项目", type="公开招标", category=self.category)
        self.db.add(project)
        self.db.commit()
        return project.id

    def _seed_doc(self, data: bytes, source: str = "upload") -> str:
        from app.models import BidDocument

        key = self.fake.put_bytes(f"bid-documents/{self.project_id}", data, ".docx")
        doc = BidDocument(
            project_id=self.project_id, filename="投标书.docx", storage_path=key, size_bytes=len(data), source=source, kind=self.scope
        )
        self.db.add(doc)
        self.db.commit()
        return doc.id

    def _seed_run(self, round_no: int, rule: str = "工期响应", location: str = "工期方案", evidence=None):
        from app.models import ReviewFinding, ReviewRun

        doc_id = self._seed_doc(make_docx())
        level = "L2" if self.scope == "business" else "L4"
        run = ReviewRun(
            project_id=self.project_id, bid_document_id=doc_id, round=round_no, status="done", scope=self.scope
        )
        self.db.add(run)
        self.db.flush()
        finding = ReviewFinding(
            run_id=run.id,
            engine="E2" if self.scope == "business" else "E4",
            level=level,
            severity="扣分",
            location=location,
            excerpt=EXCERPT,
            rule=rule,
            suggestion=f"请改写：{APPLY_TEXT}，并按节点考核。",
            evidence_json=evidence if evidence is not None else {"applyText": APPLY_TEXT},
        )
        self.db.add(finding)
        self.db.commit()
        return run, finding.id

    def _open(self):
        return self.revision_mod.get_or_create_bid_revision(self.project_id, self.scope, self.db, self.user)

    def _apply(self, revision_id: str, issue_id: str):
        return self.revision_mod.apply_issue_suggestion(revision_id, issue_id, self.request, self.db, self.user)

    def _doc_text(self, doc_id: str) -> str:
        import docx

        from app.models import BidDocument

        doc = self.db.get(BidDocument, doc_id)
        document = docx.Document(io.BytesIO(self.fake.get_bytes(doc.storage_path)))
        return "\n".join(p.text for p in document.paragraphs)

    def _working_docs(self):
        from app.models import BidDocument

        return self.db.query(BidDocument).filter(BidDocument.source == "revision-working").all()


class _LoopCases:
    """两个类别、两个分册共用的闭环用例，由下面四个具体类各跑一遍。"""

    def test_apply_writes_back_and_reload_keeps_edit(self):
        out = self._open()
        self.assertEqual(out.category, self.category)
        self.assertEqual(out.categoryLabel, "工程标" if self.category == "工程类" else "软件服务标")
        self.assertTrue(any(i.id == self.finding_id for i in out.issues))

        applied = self._apply(out.id, self.finding_id)
        self.assertIn(self.finding_id, applied.resolvedIds)
        self.assertIn(APPLY_TEXT, self._doc_text(applied.bidDocumentId))
        self.assertNotIn(EXCERPT, self._doc_text(applied.bidDocumentId))

        # 刷新页面：同一轮预审，工作稿、已修复标记、改后的段落都应还在
        reloaded = self._open()
        self.assertEqual(reloaded.bidDocumentId, applied.bidDocumentId)
        self.assertIn(self.finding_id, reloaded.resolvedIds)
        self.assertIn(APPLY_TEXT, self._doc_text(reloaded.bidDocumentId))
        paragraphs = [p["text"] for s in reloaded.model_dump()["sections"] for p in s.get("paragraphs", [])]
        self.assertTrue(any(APPLY_TEXT in t for t in paragraphs))

    def test_working_doc_is_replaced_in_place(self):
        out = self._open()
        first = self._apply(out.id, self.finding_id)
        working = self._working_docs()
        self.assertEqual(len(working), 1)
        first_key = working[0].storage_path

        # 再来一条同类问题：工作稿仍只有一份，旧文件被清理
        from app.models import ReviewFinding

        extra = ReviewFinding(
            run_id=self.run.id,
            engine="E2",
            level="L2" if self.scope == "business" else "L4",
            severity="扣分",
            location="第一章 工期响应",
            excerpt="确保按时交付",
            rule="交付响应",
            suggestion="请改写：确保在合同签订后30日内完成交付。",
            evidence_json={"applyText": "确保在合同签订后30日内完成交付"},
        )
        self.db.add(extra)
        self.db.commit()
        regenerated = self.revision_mod.regenerate_bid_revision(first.id, self.request, self.db, self.user)
        self.assertEqual(len(self._working_docs()), 0, "重新生成回到预审原文，工作稿应被释放")
        self.assertEqual(regenerated.resolvedIds, [])

        again = self._apply(regenerated.id, self.finding_id)
        second = self._apply(again.id, extra.id)
        working = self._working_docs()
        self.assertEqual(len(working), 1)
        self.assertEqual(second.bidDocumentId, again.bidDocumentId)
        self.assertNotIn(first_key, self.fake.blobs, "旧工作稿文件应已删除")
        text = self._doc_text(second.bidDocumentId)
        self.assertIn(APPLY_TEXT, text)
        self.assertIn("30日内完成交付", text)

    def test_write_back_miss_does_not_mark_resolved(self):
        from fastapi import HTTPException

        from app.models import BidDocument

        out = self._open()
        # 把源文件换成不含该段落的版本，模拟写不回去
        doc = self.db.get(BidDocument, out.bidDocumentId)
        self.fake.blobs[doc.storage_path] = make_docx("完全不同的一段话，里面没有任何预审问题的原文内容。")
        with self.assertRaises(HTTPException) as ctx:
            self._apply(out.id, self.finding_id)
        self.assertEqual(ctx.exception.status_code, 400)

        self.db.expire_all()
        from app.models import BidRevision

        rev = self.db.get(BidRevision, out.id)
        self.assertEqual(rev.resolved_ids_json or [], [])
        self.assertEqual(self._working_docs(), [])

    def test_missing_source_file_is_reported(self):
        from fastapi import HTTPException

        from app.models import BidDocument

        out = self._open()
        doc = self.db.get(BidDocument, out.bidDocumentId)
        del self.fake.blobs[doc.storage_path]
        with self.assertRaises(HTTPException) as ctx:
            self._apply(out.id, self.finding_id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(self._working_docs(), [])

    def test_new_run_resets_to_new_source(self):
        out = self._open()
        applied = self._apply(out.id, self.finding_id)
        self.assertEqual(len(self._working_docs()), 1)

        run2, finding2 = self._seed_run(round_no=2)
        switched = self._open()
        self.assertTrue(switched.runSwitched)
        self.assertEqual(switched.reviewRunId, run2.id)
        self.assertEqual(switched.resolvedIds, [])
        self.assertNotEqual(switched.bidDocumentId, applied.bidDocumentId)
        self.assertEqual(self._working_docs(), [], "换轮次后上一轮的工作稿应被释放")


class _ManualCases:
    manual_rule = ""

    def test_manual_issue_is_rejected_with_hint(self):
        from fastapi import HTTPException

        run, finding_id = self._seed_run(round_no=2, rule=self.manual_rule, location="资格证明")
        out = self._open()
        issue = next(i for i in out.model_dump()["issues"] if i["id"] == finding_id)
        self.assertEqual(issue["fixMode"], "manual")
        self.assertTrue(issue["fixHint"])

        with self.assertRaises(HTTPException) as ctx:
            self._apply(out.id, finding_id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, issue["fixHint"])
        self.assertEqual(self._working_docs(), [])

    def test_text_issue_is_not_manual(self):
        out = self._open()
        issue = next(i for i in out.model_dump()["issues"] if i["id"] == self.finding_id)
        self.assertEqual(issue["fixMode"], "text")
        self.assertEqual(issue["fixHint"], "")


class EngineeringBusinessTests(_LoopCases, _ManualCases, RevisionLoopBase):
    category = "工程类"
    scope = "business"
    manual_rule = "安全生产许可证有效期"


class EngineeringTechTests(_LoopCases, _ManualCases, RevisionLoopBase):
    category = "工程类"
    scope = "tech"
    manual_rule = "工程量清单一致性"


class SoftwareBusinessTests(_LoopCases, _ManualCases, RevisionLoopBase):
    category = "软件服务类"
    scope = "business"
    manual_rule = "软件著作权证书"


class SoftwareTechTests(_LoopCases, _ManualCases, RevisionLoopBase):
    category = "软件服务类"
    scope = "tech"
    manual_rule = "等级保护测评报告"


class CategoryProfileTests(unittest.TestCase):
    def test_manual_keywords_differ_by_category(self):
        from app.engines.category_profile import classify_fix_mode

        # 工程量清单只在工程类算材料问题，软件服务类里不是
        issue = {"rule": "工程量清单漏项", "location": "报价"}
        self.assertEqual(classify_fix_mode(issue, "工程类")[0], "manual")
        self.assertEqual(classify_fix_mode(issue, "软件服务类")[0], "text")
        # 软著只在软件服务类算材料问题
        issue = {"rule": "软件著作权登记信息缺失", "location": "附件三"}
        self.assertEqual(classify_fix_mode(issue, "软件服务类")[0], "manual")
        self.assertEqual(classify_fix_mode(issue, "工程类")[0], "text")
        # 工程标别名按工程类处理，产品标按软件服务类处理
        self.assertEqual(classify_fix_mode({"rule": "图纸深度"}, "工程标")[0], "manual")
        self.assertEqual(classify_fix_mode({"rule": "图纸深度"}, "产品标")[0], "text")

    def test_common_manual_and_human_check(self):
        from app.engines.category_profile import classify_fix_mode

        for category in ("工程类", "软件服务类"):
            self.assertEqual(classify_fix_mode({"rule": "社保缴纳证明"}, category)[0], "manual")
            self.assertEqual(classify_fix_mode({"rule": "企业信用核验"}, category)[0], "manual")
            self.assertEqual(classify_fix_mode({"rule": "空话", "issueClass": "human_check"}, category)[0], "manual")
            self.assertEqual(classify_fix_mode({"rule": "空话过多"}, category), ("text", ""))

    def test_hints_name_the_right_materials(self):
        from app.engines.category_profile import classify_fix_mode

        _, eng_hint = classify_fix_mode({"rule": "图纸深度"}, "工程类")
        _, sw_hint = classify_fix_mode({"rule": "软著"}, "软件服务类")
        self.assertIn("清单", eng_hint)
        self.assertIn("软著", sw_hint)
        self.assertNotEqual(eng_hint, sw_hint)

    def test_rewrite_context_differs_by_category(self):
        from app.engines.category_profile import rewrite_context

        eng = rewrite_context("工程类")
        sw = rewrite_context("软件服务类")
        self.assertIn("工程类", eng)
        self.assertIn("软件服务类", sw)
        self.assertNotEqual(eng, sw)
        self.assertEqual(rewrite_context("工程标"), eng)

    def test_prompts_carry_category_context(self):
        from app.engines import revision_suggest

        captured: list[str] = []

        def fake_chat(messages, *args, **kwargs):
            captured.append(str(messages))
            return "改写后的段落内容，已落实量化指标要求。"

        issue = {"rule": "工期响应", "excerpt": EXCERPT, "tenderQuote": "工期不超过180天"}
        with mock.patch("app.engines.llm.chat_complete", fake_chat), mock.patch(
            "app.engines.llm.get_default_model_id", lambda *a, **k: "m"
        ):
            revision_suggest.llm_rewrite_paragraph(PARA_TEXT, EXCERPT, "补充量化指标", issue, "工程类")
            revision_suggest.llm_rewrite_paragraph(PARA_TEXT, EXCERPT, "补充量化指标", issue, "软件服务类")
        self.assertEqual(len(captured), 2)
        self.assertIn("工程类投标文件", captured[0])
        self.assertIn("软件服务类投标文件", captured[1])
        self.assertNotIn("软件服务类投标文件", captured[0])


if __name__ == "__main__":
    unittest.main()
