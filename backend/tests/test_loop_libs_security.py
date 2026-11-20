"""本轮改造的回归用例：业务闭环（版本恢复、类别改动解锁、分类权重、工程缺件）、
三库（解析路由、文件去重、近重复、资质判同失败）、安全（注册、越权、SSRF、本地路径、限速、
请求体、CSV、密钥加密、令牌作废、解压炸弹）。全部用内存 sqlite 和桩，不接外部服务。"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

from fastapi import Request

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from tests.test_revision_loop import APPLY_TEXT, EXCERPT, RevisionLoopBase, make_docx  # noqa: E402


def _memory_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import platform_models  # noqa: F401
    from app.db import PlatformBase
    from app.models import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    PlatformBase.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    db.info["tenant_id"] = "default"
    return engine, db


def session_factories(engine):
    """sqlite 没有 schema，企业会话和平台会话都指向同一个内存库。"""
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, autoflush=False)

    def tenant(tid):
        s = maker()
        s.info["tenant_id"] = tid
        return s

    return tenant, maker


class DbCase(unittest.TestCase):
    def setUp(self):
        self.engine, self.db = _memory_db()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_user(self, role="管理员", name="u"):
        from app.auth import hash_password
        from app.models import User

        user = User(name=name, email=f"{name}@x.cn", password_hash=hash_password("abc12345"), role=role)
        self.db.add(user)
        self.db.commit()
        return user


# ---------------------------------------------------------------------------
# 业务闭环
# ---------------------------------------------------------------------------


class RestoreVersionTests(RevisionLoopBase):
    category = "工程类"
    scope = "tech"

    def test_restore_replaces_working_doc(self):
        from app.models import BidDocument, BidRevisionVersion

        out = self._open()
        applied = self._apply(out.id, self.finding_id)
        self.assertIn(APPLY_TEXT, self._doc_text(applied.bidDocumentId))

        old_key = self.fake.put_bytes(f"bid-documents/{self.project_id}", make_docx(), ".docx")
        old_doc = BidDocument(project_id=self.project_id, filename="v1.docx", storage_path=old_key, source="revision", kind=self.scope)
        self.db.add(old_doc)
        self.db.flush()
        version = BidRevisionVersion(
            revision_id=out.id, label="V1", bid_document_id=old_doc.id, content_state_json={"marker": "v1"}
        )
        self.db.add(version)
        self.db.commit()

        restored = self.revision_mod.restore_bid_revision_version(out.id, version.id, self.db, self.user)
        self.assertEqual(restored.versionId, version.id)
        self.assertEqual(restored.bidDocumentId, old_doc.id)
        self.assertEqual(restored.contentState, {"marker": "v1"})
        reopened = self._open()
        text = self._doc_text(reopened.bidDocumentId)
        self.assertIn(EXCERPT, text, "恢复后工作稿应回到该版本的原文")
        self.assertNotIn(APPLY_TEXT, text)

    def test_restore_without_file_is_404(self):
        from fastapi import HTTPException

        from app.models import BidRevisionVersion

        out = self._open()
        version = BidRevisionVersion(revision_id=out.id, label="V0", bid_document_id=None, content_state_json={})
        self.db.add(version)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            self.revision_mod.restore_bid_revision_version(out.id, version.id, self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 404)


class CategoryChangeTests(DbCase):
    def _project_with_locked_checklist(self, category="工程类"):
        from app.models import EvaluationChecklist, Project

        project = Project(code="P1", name="项目", type="工程", category=category)
        self.db.add(project)
        self.db.flush()
        self.db.add(EvaluationChecklist(project_id=project.id, tender_document_id="t1", status="done", locked=True))
        self.db.commit()
        return project

    def _patch(self, project, category):
        from app.routers import projects
        from app.schemas import UpdateProjectIn

        user = SimpleNamespace(id="u1", name="测试", role="管理员")
        with mock.patch.object(projects, "require_project", return_value=project), mock.patch.object(
            projects, "write_audit", lambda *a, **k: None
        ):
            return projects.update_project(project.id, UpdateProjectIn(category=category), self.db, user)

    def test_switching_category_unlocks_checklist(self):
        from app.engines.rules_config import checklist_locked

        project = self._project_with_locked_checklist("工程类")
        self.assertTrue(checklist_locked(self.db, project.id))
        out = self._patch(project, "软件服务类")
        self.assertTrue(out.needsReparse)
        self.assertFalse(checklist_locked(self.db, project.id))

    def test_same_category_alias_keeps_lock(self):
        from app.engines.rules_config import checklist_locked

        project = self._project_with_locked_checklist("工程类")
        out = self._patch(project, "工程标")
        self.assertFalse(out.needsReparse)
        self.assertTrue(checklist_locked(self.db, project.id))


class CategoryWeightTests(DbCase):
    def test_software_falls_back_to_sw_defaults(self):
        from app.engines import rules_data
        from app.engines.rules_config import load_active_weights
        from app.models import WeightTemplate

        self.db.add(WeightTemplate(name="工程", completeness=40, relevance=20, compliance=20, feasibility=10, standardization=10, active=True, category="工程类"))
        self.db.commit()
        sw = load_active_weights(self.db, "软件服务类")
        self.assertEqual(sw["relevance"], rules_data.SW_DEFAULT_WEIGHTS["relevance"])
        eng = load_active_weights(self.db, "工程类")
        self.assertEqual(eng["completeness"], 40)

    def test_each_category_uses_its_active_template(self):
        from app.engines.rules_config import load_active_weight_name, load_active_weights
        from app.models import WeightTemplate

        self.db.add(WeightTemplate(name="工程", completeness=40, relevance=20, compliance=20, feasibility=10, standardization=10, active=True, category="工程类"))
        self.db.add(WeightTemplate(name="软件", completeness=10, relevance=50, compliance=20, feasibility=10, standardization=10, active=True, category="软件服务类"))
        self.db.commit()
        self.assertEqual(load_active_weights(self.db, "软件服务类")["relevance"], 50)
        self.assertEqual(load_active_weight_name(self.db, "工程类"), "工程")
        self.assertEqual(load_active_weight_name(self.db, "软件服务类"), "软件")


class EngineeringWarningTests(unittest.TestCase):
    def test_missing_boq_and_drawing(self):
        from app.engines.tender_package import engineering_package_warnings

        warnings = engineering_package_warnings([{"kind": "main", "filename": "招标文件.docx"}])
        self.assertEqual(len(warnings), 2)
        self.assertIn("工程量清单", warnings[0])
        self.assertIn("图纸", warnings[1])

    def test_unrecognized_boq_and_failed_drawings(self):
        from app.engines.tender_package import engineering_package_warnings

        parts = [{"kind": "boq", "filename": "清单.pdf", "boqItems": []}, {"kind": "drawing", "filename": "图.pdf"}]
        warnings = engineering_package_warnings(parts, drawing_intel_failed=True)
        self.assertTrue(any("清单.pdf" in w for w in warnings))
        self.assertTrue(any("没有抽出评审规则" in w for w in warnings))

    def test_complete_package_has_no_warning(self):
        from app.engines.tender_package import engineering_package_warnings

        parts = [{"kind": "boq", "boqItems": [{"name": "土方"}]}, {"kind": "drawing"}]
        self.assertEqual(engineering_package_warnings(parts, drawing_pack={"rules": [{"id": 1}]}), [])


# ---------------------------------------------------------------------------
# 三库：解析路由、去重
# ---------------------------------------------------------------------------


def _pdf_with_blank_page(text: str = "这是一段带文字层的正文，用来确认文字页直接走 PyMuPDF。") -> str:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontname="china-s")
    doc.new_page()  # 第二页无文字层，模拟扫描页
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


class DocParseRoutingTests(unittest.TestCase):
    def setUp(self):
        self.path = _pdf_with_blank_page()

    def tearDown(self):
        os.remove(self.path)

    def test_scan_page_uses_vl_not_mineru(self):
        from app.engines import doc_parse

        with mock.patch.object(doc_parse, "read_scan_page", return_value="营业执照 统一社会信用代码 91310000XXXX") as read, mock.patch.object(
            doc_parse.httpx, "post", side_effect=AssertionError("暂时不走 MinerU")
        ), mock.patch.object(doc_parse, "_tesseract_page", side_effect=AssertionError("不该走 OCR")):
            pages = doc_parse.extract_pdf_pages(self.path)
        self.assertEqual(pages[0]["source"], doc_parse.SOURCE_TEXT)
        self.assertEqual(pages[1]["source"], doc_parse.SOURCE_VL)
        self.assertIn("营业执照", pages[1]["text"])
        self.assertEqual(read.call_count, 1, "只有扫描页才识图")

    def test_falls_back_to_tesseract_when_vl_fails(self):
        from app.engines import doc_parse

        with mock.patch.object(doc_parse, "read_scan_page", return_value=""), mock.patch.object(
            doc_parse, "_tesseract_page", return_value="OCR 识别出的文字内容"
        ):
            pages = doc_parse.extract_pdf_pages(self.path)
        self.assertEqual(pages[1]["source"], doc_parse.SOURCE_OCR)

    def test_no_vl_goes_straight_to_ocr(self):
        from app.engines import doc_parse

        with mock.patch.object(doc_parse, "read_scan_page", return_value=""), mock.patch.object(
            doc_parse, "_tesseract_page", return_value=""
        ):
            pages = doc_parse.extract_pdf_pages(self.path)
        self.assertEqual(pages[1]["text"], "")

    def test_vision_only_when_ocr_weak(self):
        from app.engines.qualification_extract import needs_vision

        self.assertTrue(needs_vision("", "", ""))
        long_text = "安全生产许可证 " * 10
        self.assertFalse(needs_vision(long_text, "（皖）JZ安许证字[2020]000123", ""))
        self.assertTrue(needs_vision(long_text, "", ""))


class _Upload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FileHashDedupTests(DbCase):
    def test_product_upload_skips_same_file(self):
        from app.models import ProductLibrary, ProductSourceDoc
        from app.routers import products

        lib = ProductLibrary(name="库")
        self.db.add(lib)
        self.db.commit()
        user = self.make_user()
        data = make_docx()
        storage = mock.Mock()
        storage.put_bytes.side_effect = lambda prefix, content, ext: f"{prefix}/x{ext}"
        task = mock.Mock()
        with mock.patch.object(products, "storage", storage), mock.patch.object(products, "write_audit", lambda *a, **k: None), mock.patch(
            "app.tasks.run_product_extract_task", task
        ):
            first = asyncio.run(products.upload_source_docs(lib.id, [_Upload("a.docx", data), _Upload("a副本.docx", data)], self.db, user))
            second = asyncio.run(products.upload_source_docs(lib.id, [_Upload("b.docx", data)], self.db, user))
        self.assertEqual(len(first), 1, "同一批里的相同文件只建一份")
        self.assertEqual(len(second), 1)
        self.assertTrue(second[0].duplicate)
        self.assertEqual(self.db.query(ProductSourceDoc).count(), 1)
        self.assertEqual(task.delay.call_count, 1)

    def test_qualification_upload_allows_retry_after_failure(self):
        from app.models import QualificationSourceDoc
        from app.routers import qualifications

        user = self.make_user()
        data = make_docx("营业执照 统一社会信用代码 913100001234567890")
        storage = mock.Mock()
        storage.put_bytes.side_effect = lambda prefix, content, ext: f"{prefix}/x{ext}"
        with mock.patch.object(qualifications, "storage", storage), mock.patch.object(
            qualifications, "write_audit", lambda *a, **k: None
        ), mock.patch("app.tasks.run_qualification_extract_task", mock.Mock()):
            asyncio.run(qualifications.upload_source_docs([_Upload("a.docx", data)], self.db, user))
            self.db.query(QualificationSourceDoc).update({QualificationSourceDoc.status: "failed"})
            self.db.commit()
            again = asyncio.run(qualifications.upload_source_docs([_Upload("a.docx", data)], self.db, user))
        self.assertFalse(again[0].duplicate, "抽取失败的文件允许重新上传")


class SimhashTests(unittest.TestCase):
    def test_near_duplicate_text(self):
        from app.engines.knowledge_ingest import hamming, simhash64

        base = "本工程施工组织设计包括施工部署、进度计划、质量保证措施、安全文明施工措施和环境保护措施。" * 8
        edited = base.replace("环境保护措施", "环境保护方案", 1)
        other = "软件系统采用微服务架构，前端基于 React，后端提供 RESTful 接口并支持统一身份认证。" * 8
        self.assertLessEqual(hamming(simhash64(base), simhash64(edited)), 3)
        self.assertGreater(hamming(simhash64(base), simhash64(other)), 3)
        self.assertEqual(simhash64("太短"), "")


class QualificationUndecidedTests(DbCase):
    def test_llm_failure_marks_suspected(self):
        from app.engines import qualification_dedup
        from app.models import QualificationAsset, QualificationSourceDoc

        existing = QualificationAsset(name="质量管理体系认证证书", kind="cert", review_status="待审核")
        self.db.add(existing)
        src = QualificationSourceDoc(filename="商务标.docx", storage_path="k")
        self.db.add(src)
        self.db.commit()
        cand = {"name": "质量体系认证", "kind": "cert", "images": []}
        with mock.patch.object(qualification_dedup, "_best_match", return_value=(existing, 0.5, False)), mock.patch.object(
            qualification_dedup, "_llm_same_asset", return_value=qualification_dedup.UNDECIDED
        ):
            stats = qualification_dedup.apply_to_library(self.db, src, [cand])
        self.assertEqual(stats["suspected"], 1)
        self.assertEqual(stats["merged"], 0)


# ---------------------------------------------------------------------------
# 安全
# ---------------------------------------------------------------------------


class RegistrationTests(DbCase):
    def _register(self, allow: bool):
        from app.routers import auth as auth_router
        from app.schemas import RegisterIn

        settings = SimpleNamespace(allow_register=allow)
        tenant, platform = session_factories(self.engine)
        with mock.patch.object(auth_router, "get_settings", return_value=settings), mock.patch.object(
            auth_router, "tenant_session", tenant
        ), mock.patch.object(auth_router, "platform_session", platform):
            return auth_router.register(RegisterIn(name="新人", email="new@x.cn", password="abc12345"))

    def test_register_disabled_by_default(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._register(False)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_first_registered_user_is_not_admin(self):
        out = self._register(True)
        self.assertEqual(out.user.role, "成员")

    def test_weak_password_rejected(self):
        from fastapi import HTTPException

        from app.routers import auth as auth_router
        from app.schemas import RegisterIn

        with mock.patch.object(auth_router, "get_settings", return_value=SimpleNamespace(allow_register=True)):
            with self.assertRaises(HTTPException):
                auth_router.register(RegisterIn(name="a", email="a@x.cn", password="123456"))


class MemberManagementTests(DbCase):
    def test_manager_cannot_create_or_touch_admin(self):
        from fastapi import HTTPException

        from app.routers import users
        from app.schemas import InviteUserIn, UpdateUserIn

        manager = self.make_user("项目经理", "pm")
        admin = self.make_user("管理员", "boss")
        _, platform = session_factories(self.engine)
        patcher = mock.patch.object(users, "platform_session", platform)
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.assertRaises(HTTPException):
            users.invite_user(InviteUserIn(name="x", email="x@x.cn", role="管理员"), self.db, manager)
        with self.assertRaises(HTTPException):
            users.update_user(admin.id, UpdateUserIn(disabled=True), self.db, manager)
        writer = users.invite_user(InviteUserIn(name="w", email="w@x.cn", role="撰写专家"), self.db, manager)
        self.assertGreaterEqual(len(writer.initialPassword), 12, "留空时生成随机密码，不再是 123456")
        self.assertNotEqual(writer.initialPassword, "123456")


class KnowledgeVisibilityTests(DbCase):
    def test_personal_and_project_docs_are_isolated(self):
        from app.models import KnowledgeDocument, Project
        from app.routers.knowledge import _visible_filter, can_view_doc

        alice = self.make_user("撰写专家", "alice")
        bob = self.make_user("撰写专家", "bob")
        project = Project(code="P", name="p", type="工程", category="工程类", owner_id=alice.id)
        self.db.add(project)
        self.db.flush()
        docs = [
            KnowledgeDocument(scope="个人库", type="专项方案", title="alice私有", filename="a", storage_path="a", owner_id=alice.id),
            KnowledgeDocument(scope="项目库", type="专项方案", title="项目文档", filename="b", storage_path="b", project_id=project.id),
            KnowledgeDocument(scope="企业库", type="专项方案", title="公共", filename="c", storage_path="c"),
        ]
        self.db.add_all(docs)
        self.db.commit()
        self.assertTrue(can_view_doc(self.db, alice, docs[0]))
        self.assertFalse(can_view_doc(self.db, bob, docs[0]))
        self.assertFalse(can_view_doc(self.db, bob, docs[1]))
        self.assertTrue(can_view_doc(self.db, bob, docs[2]))
        titles = {d.title for d in _visible_filter(self.db, bob, self.db.query(KnowledgeDocument)).all()}
        self.assertEqual(titles, {"公共"})


class LibraryReadPermissionTests(unittest.TestCase):
    def test_plain_member_cannot_read_libraries(self):
        from fastapi import HTTPException

        from app.permissions import require_library_read

        with self.assertRaises(HTTPException):
            require_library_read(SimpleNamespace(role="成员"))
        require_library_read(SimpleNamespace(role="评标专家"))


class SsrfGuardTests(unittest.TestCase):
    def test_private_and_metadata_rejected(self):
        from fastapi import HTTPException

        from app.net_guard import validate_base_url

        for url in ("http://127.0.0.1:11434/v1", "http://10.0.0.5/v1", "file:///etc/passwd", "http://user:pw@api.x.com"):
            with self.assertRaises(HTTPException, msg=url):
                validate_base_url(url)
        with self.assertRaises(HTTPException):
            validate_base_url("http://169.254.169.254/latest", allow_private=True)
        self.assertEqual(validate_base_url("http://10.0.0.5/v1/", allow_private=True), "http://10.0.0.5/v1")

    def test_public_ip_allowed(self):
        from app.net_guard import validate_base_url

        self.assertEqual(validate_base_url("https://8.8.8.8/v1"), "https://8.8.8.8/v1")


class LocalPathTests(unittest.TestCase):
    def test_only_upload_dir_is_readable(self):
        from app import storage

        upload = tempfile.mkdtemp()
        settings = SimpleNamespace(upload_dir=upload, sample_dir="")
        inside = os.path.join(upload, "a.txt")
        with open(inside, "w", encoding="utf-8") as fh:
            fh.write("x")
        fd, outside = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with mock.patch.object(storage, "get_settings", return_value=settings):
                self.assertTrue(storage.is_local_file(inside))
                self.assertFalse(storage.is_local_file(outside))
                self.assertFalse(storage.is_local_file(os.path.join(upload, "..", os.path.basename(outside))))
        finally:
            os.remove(inside)
            os.remove(outside)
            os.rmdir(upload)


class LoginRateLimitTests(unittest.TestCase):
    def test_locks_after_max_failures(self):
        from app import ratelimit

        settings = SimpleNamespace(login_max_failures=3, login_lock_minutes=1, redis_url="")
        with mock.patch.object(ratelimit, "_redis", return_value=None), mock.patch.object(
            ratelimit, "get_settings", return_value=settings
        ):
            key = "acct:test-lock"
            ratelimit.reset(key)
            for _ in range(3):
                self.assertFalse(ratelimit.is_locked(key))
                ratelimit.record_failure(key)
            self.assertTrue(ratelimit.is_locked(key))
            ratelimit.reset(key)
            self.assertFalse(ratelimit.is_locked(key))


class TokenRevocationTests(DbCase):
    def test_password_change_invalidates_old_token(self):
        from fastapi import HTTPException

        from app.auth import get_current_user, revoke_tokens, token_for

        user = self.make_user()
        token = token_for(user)
        self.assertEqual(get_current_user(f"Bearer {token}", self.db).id, user.id)
        revoke_tokens(user)
        self.db.commit()
        with self.assertRaises(HTTPException):
            get_current_user(f"Bearer {token}", self.db)
        self.assertEqual(get_current_user(f"Bearer {token_for(user)}", self.db).id, user.id)


class BodyLimitTests(unittest.TestCase):
    def test_chunked_body_over_limit_is_413(self):
        from fastapi import FastAPI

        from app.body_limit import BodyLimitMiddleware

        inner = FastAPI()

        @inner.post("/up")
        async def up(request: Request):
            return {"n": len(await request.body())}

        app = BodyLimitMiddleware(inner, max_bytes=10)
        chunks = [b"x" * 8, b"x" * 8]
        sent: list[dict] = []

        async def receive():
            if chunks:
                return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/up", "headers": [], "query_string": b"", "http_version": "1.1"}
        asyncio.run(app(scope, receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        self.assertEqual(start["status"], 413)


class CsvEscapeTests(unittest.TestCase):
    def test_formula_cells_are_quoted(self):
        from app.engines.submission_check import csv_cell, matrix_csv

        self.assertEqual(csv_cell("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(csv_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(csv_cell("正常文字"), "正常文字")
        blob = matrix_csv([{"requirement": "=1+1"}]).decode("utf-8-sig")
        self.assertIn("'=1+1", blob)


class SecretBoxTests(unittest.TestCase):
    def test_roundtrip_and_plaintext_compat(self):
        from app.secret_box import decrypt, encrypt, is_encrypted

        token = encrypt("sk-abc")
        self.assertTrue(is_encrypted(token))
        self.assertNotIn("sk-abc", token)
        self.assertEqual(decrypt(token), "sk-abc")
        self.assertEqual(decrypt("sk-legacy-plain"), "sk-legacy-plain")

    def test_orm_column_stores_ciphertext(self):
        from sqlalchemy import text

        from app.models import LlmProvider

        engine, db = _memory_db()
        try:
            db.add(LlmProvider(id="lp1", name="ds", kind="deepseek", base_url="https://api.deepseek.com", api_key="sk-secret"))
            db.commit()
            raw = db.execute(text("SELECT api_key FROM llm_providers WHERE id='lp1'")).scalar()
            self.assertTrue(raw.startswith("enc:v1:"))
            db.expire_all()
            self.assertEqual(db.get(LlmProvider, "lp1").api_key, "sk-secret")
        finally:
            db.close()
            engine.dispose()


class ZipBombTests(unittest.TestCase):
    def test_high_ratio_entry_rejected(self):
        from app.engines.safe_office import UnsafeArchive, check_zip_bytes

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"0" * (12 * 1024 * 1024))
        with self.assertRaises(UnsafeArchive):
            check_zip_bytes(buf.getvalue())

    def test_normal_docx_passes_and_xxe_not_resolved(self):
        from app.engines.safe_office import check_zip_bytes, safe_fromstring

        check_zip_bytes(make_docx())
        evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
        root = safe_fromstring(evil)
        self.assertNotIn("root:", "".join(root.itertext()))


if __name__ == "__main__":
    unittest.main()
