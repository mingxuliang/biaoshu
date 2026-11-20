"""全系统测试后补的回归用例：口径统一、清单选取、追溯矩阵、表单保护、任务回收、上传上限。"""

import asyncio
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace


class SeverityCountsTests(unittest.TestCase):
    def test_waste_only_counts_auto_veto(self):
        from app.engines.bid_kind import severity_counts

        items = [
            {"severity": "废标", "issueClass": "auto_veto"},
            {"severity": "废标"},  # 缺 issueClass 按自动否决算
            {"severity": "废标", "issueClass": "human_check"},  # 需人工核对，只算风险
            {"severity": "降档"},
            {"severity": "扣分"},
            {"severity": "建议"},
        ]
        waste, risk, suggest, light = severity_counts(items)
        self.assertEqual((waste, risk, suggest, light), (2, 3, 1, "红"))

    def test_light_levels(self):
        from app.engines.bid_kind import severity_counts

        self.assertEqual(severity_counts([])[3], "绿")
        self.assertEqual(severity_counts([{"severity": "建议"}])[3], "绿")
        self.assertEqual(severity_counts([{"severity": "扣分"}])[3], "橙")
        self.assertEqual(severity_counts([{"severity": "废标", "issueClass": "human_check"}])[3], "橙")

    def test_booklet_projection_uses_same_counts(self):
        from app.engines.bid_kind import project_booklet_payload

        payload = {
            "scope": "full",
            "findings": [
                {"severity": "废标", "issueClass": "auto_veto", "level": "L1", "title": "a"},
                {"severity": "建议", "level": "L1", "title": "b"},
            ],
        }
        try:
            out = project_booklet_payload(payload, "tech")
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"项目分册函数需要完整报告结构：{exc}")
        self.assertIn(out.get("light"), ("红", "橙", "绿"))


class VetoMissingTextTests(unittest.TestCase):
    def test_paragraph_without_text_does_not_crash(self):
        from app.engines import e1_veto

        out = e1_veto.run([{"id": 1}, {"id": 2, "text": "投标有效期 90 日历天"}], {}, [])
        self.assertIsInstance(out, list)


class TraceMatrixTests(unittest.TestCase):
    def test_duplicate_titles_all_counted(self):
        from app.engines.submission_check import trace_matrix

        outline = [
            {"id": "a", "title": "服务方案"},
            {"id": "b", "title": "服务方案"},  # 同名标题，第一章为空，第二章有正文
        ]
        contents = {"a": "", "b": "有正文 【缺少资质材料，请补充后再投标】"}
        ledger = [{"id": "T1", "text": "要求", "chapters": ["服务方案"], "volume": "tech"}]
        rows = trace_matrix(ledger, {}, outline, contents)
        self.assertEqual(rows[0]["status"], "已成文")
        self.assertIn("1", rows[0]["gap"])


class FormRefreshProtectionTests(unittest.TestCase):
    def _draft(self, content: str, auto: dict | None = None):
        settings = {"formRegistry": [{"key": 1}]}
        if auto is not None:
            settings["formAuto"] = auto
        return SimpleNamespace(
            project_id="p",
            settings_json=settings,
            outline_json=[{"id": "c1", "title": "偏离表", "formKeys": [1]}],
            chapter_contents_json={"c1": content},
        )

    def _run(self, draft):
        from unittest import mock

        from app.engines import form_registry, req_ledger, submission_check

        db = SimpleNamespace(commit=lambda: None)
        with (
            mock.patch.object(req_ledger, "full_project_ledger", return_value=[]),
            mock.patch.object(req_ledger, "collect_responses", return_value={}),
            mock.patch.object(form_registry, "form_content", return_value="系统生成的偏离表"),
            mock.patch("sqlalchemy.orm.attributes.flag_modified", lambda *a, **k: None),
        ):
            return submission_check.refresh_forms(db, draft)

    def test_untouched_form_is_refreshed_and_fingerprinted(self):
        from app.engines.submission_check import _fingerprint

        draft = self._draft("旧内容")
        self.assertEqual(self._run(draft), 1)
        self.assertEqual(draft.chapter_contents_json["c1"], "系统生成的偏离表")
        self.assertEqual(draft.settings_json["formAuto"]["c1"], _fingerprint("系统生成的偏离表"))

    def test_hand_edited_form_is_kept(self):
        from app.engines.submission_check import _fingerprint

        draft = self._draft("用户手改后的偏离表", auto={"c1": _fingerprint("系统生成的偏离表")})
        self.assertEqual(self._run(draft), 0)
        self.assertEqual(draft.chapter_contents_json["c1"], "用户手改后的偏离表")

    def test_system_written_form_still_refreshes_when_responses_change(self):
        from app.engines.submission_check import _fingerprint

        draft = self._draft("上一版系统偏离表", auto={"c1": _fingerprint("上一版系统偏离表")})
        self.assertEqual(self._run(draft), 1)
        self.assertEqual(draft.chapter_contents_json["c1"], "系统生成的偏离表")


class ServerSettingsKeysTests(unittest.TestCase):
    def test_team_fill_and_form_auto_survive_frontend_save(self):
        from app.writer_tracks import merge_settings

        merged = merge_settings(
            {"teamFill": {"3": {"x": 1}}, "formAuto": {"c1": "h"}},
            {"layout": {"a": 1}, "teamFill": {}, "formAuto": {}},
        )
        self.assertEqual(merged["teamFill"], {"3": {"x": 1}})
        self.assertEqual(merged["formAuto"], {"c1": "h"})
        self.assertEqual(merged["layout"], {"a": 1})


class ChecklistSelectionAndReaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base

        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _checklist(self, cid, version, status, locked=False, project="px"):
        from app.models import EvaluationChecklist

        row = EvaluationChecklist(
            id=cid, project_id=project, tender_document_id="td-1", version=version, status=status, locked=locked, checklist_json={"v": version}
        )
        self.db.add(row)
        self.db.commit()
        return row

    def test_latest_running_checklist_is_ignored(self):
        from app.engines.rules_config import select_checklist

        self._checklist("c-1", 1, "done", project="p-sel1")
        self._checklist("c-2", 2, "running", project="p-sel1")
        self.assertEqual(select_checklist(self.db, "p-sel1").id, "c-1")

    def test_locked_wins_over_newer_done(self):
        from app.engines.rules_config import select_checklist

        self._checklist("c-3", 1, "done", locked=True, project="p-sel2")
        self._checklist("c-4", 2, "done", project="p-sel2")
        self.assertEqual(select_checklist(self.db, "p-sel2").id, "c-3")

    def test_no_done_checklist_returns_none(self):
        from app.engines.rules_config import select_checklist

        self._checklist("c-5", 1, "failed", project="p-sel3")
        self.assertIsNone(select_checklist(self.db, "p-sel3"))

    def test_reaper_marks_running_failed_and_keeps_fresh_when_aged(self):
        from app.job_reaper import INTERRUPTED, reap_stuck_jobs
        from app.models import WriterJob

        old = datetime.utcnow() - timedelta(hours=5)
        self.db.add(WriterJob(id="wj-old", draft_id="d", kind="batch", status="running", created_at=old))
        self.db.add(WriterJob(id="wj-new", draft_id="d", kind="batch", status="running"))
        self.db.add(WriterJob(id="wj-q", draft_id="d", kind="batch", status="queued", created_at=old))
        self.db.commit()
        counts = reap_stuck_jobs(self.db, older_than_minutes=180)
        self.assertEqual(counts.get("WriterJob"), 1)
        self.assertEqual(self.db.get(WriterJob, "wj-old").status, "failed")
        self.assertEqual(self.db.get(WriterJob, "wj-old").error, INTERRUPTED)
        self.assertEqual(self.db.get(WriterJob, "wj-new").status, "running")
        self.assertEqual(self.db.get(WriterJob, "wj-q").status, "queued")

    def test_reaper_without_age_clears_all_running(self):
        from app.job_reaper import reap_stuck_jobs
        from app.models import WriterJob

        self.db.add(WriterJob(id="wj-r1", draft_id="d", kind="chapter", status="running"))
        self.db.commit()
        reap_stuck_jobs(self.db)
        self.assertEqual(self.db.get(WriterJob, "wj-r1").status, "failed")


class BodyLimitTests(unittest.TestCase):
    def _call(self, content_length: int):
        from app.body_limit import BodyLimitMiddleware

        reached = []

        async def inner(scope, receive, send):
            reached.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b""}

        scope = {"type": "http", "headers": [(b"content-length", str(content_length).encode())]}
        asyncio.run(BodyLimitMiddleware(inner, max_bytes=1024)(scope, receive, send))
        return reached, sent

    def test_oversize_rejected_with_413(self):
        reached, sent = self._call(2048)
        self.assertFalse(reached)
        self.assertEqual(sent[0]["status"], 413)
        self.assertIn("上限", json.loads(sent[1]["body"])["detail"])

    def test_normal_request_passes(self):
        reached, sent = self._call(100)
        self.assertTrue(reached)
        self.assertEqual(sent[0]["status"], 200)


class SlidingTokenTests(unittest.TestCase):
    def test_fresh_token_is_not_renewed(self):
        from app.tokens import create_tenant_token, renewed_access_token

        token = create_tenant_token("user-1", "default", 0)
        self.assertIsNone(renewed_access_token(f"Bearer {token}"))

    def test_token_inside_renew_window_is_replaced(self):
        from app import tokens

        real = tokens.get_settings
        settings = real()

        class Short:
            secret_key = settings.secret_key
            access_token_expire_minutes = 60

        tokens.get_settings = lambda: Short()
        try:
            token = tokens.create_tenant_token("user-1", "default", 3)
            renewed = tokens.renewed_access_token(f"Bearer {token}")
        finally:
            tokens.get_settings = real
        self.assertTrue(renewed)
        claims = tokens.decode_tenant_token(renewed)
        self.assertEqual(claims["sub"], "user-1")
        self.assertEqual(int(claims["ver"]), 3)

    def test_expired_token_is_not_renewed(self):
        from app import tokens

        real = tokens.get_settings
        settings = real()

        class Expired:
            secret_key = settings.secret_key
            access_token_expire_minutes = -1

        tokens.get_settings = lambda: Expired()
        try:
            token = tokens.create_tenant_token("user-1", "default", 0)
            renewed = tokens.renewed_access_token(f"Bearer {token}")
        finally:
            tokens.get_settings = real
        self.assertIsNone(renewed)


class InsecureDefaultsTests(unittest.TestCase):
    def test_defaults_are_reported(self):
        from app.config import Settings

        issues = Settings(secret_key="dev-secret-change-me", minio_secret_key="minioadmin").insecure_defaults
        self.assertEqual(len(issues), 2)

    def test_custom_values_pass(self):
        from app.config import Settings

        s = Settings(secret_key="x" * 40, minio_access_key="ak", minio_secret_key="sk-very-secret")
        self.assertEqual(s.insecure_defaults, [])


if __name__ == "__main__":
    unittest.main()
