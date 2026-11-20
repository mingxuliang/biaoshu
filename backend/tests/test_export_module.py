"""导出模块：按分册取版本、按类别取规则、暗标默认跟随招标、脱敏干净、导出记录带分册和类别，
以及撰写工作台导出的标题层级与文件名。内存 sqlite + 内存存储，不接 Postgres / MinIO / 模型。"""

from __future__ import annotations

import io
import os
import re
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from tests.test_revision_loop import FakeStorage  # noqa: E402

COMPANY = "示范建设科技有限公司"


def make_identity_docx(body: str = "本方案采用分层架构。") -> bytes:
    """带作者、公司、页眉单位名和修订痕迹的 docx，用来验证暗标脱敏。"""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = docx.Document()
    document.core_properties.author = "张三"
    document.core_properties.last_modified_by = "李四"
    document.core_properties.title = f"{COMPANY}技术标"
    document.sections[0].header.paragraphs[0].text = f"{COMPANY} 技术方案"
    document.add_paragraph(body)
    # 一段已删除、一段已插入的修订
    para = document.add_paragraph("正文保留。")
    ins = OxmlElement("w:ins")
    ins.set(qn("w:id"), "1")
    ins.set(qn("w:author"), "张三")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "插入的文字"
    run.append(text)
    ins.append(run)
    para._p.append(ins)
    dele = OxmlElement("w:del")
    dele.set(qn("w:id"), "2")
    dele.set(qn("w:author"), "张三")
    drun = OxmlElement("w:r")
    dtext = OxmlElement("w:delText")
    dtext.text = "删除的文字"
    drun.append(dtext)
    dele.append(drun)
    para._p.append(dele)
    buf = io.BytesIO()
    document.save(buf)
    raw = buf.getvalue()

    # 公司名写进 app.xml
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "docProps/app.xml":
                text_xml = data.decode("utf-8")
                if "<Company" in text_xml:
                    text_xml = re.sub(r"<Company\s*/>|<Company>.*?</Company>", f"<Company>{COMPANY}</Company>", text_xml, flags=re.S)
                else:
                    text_xml = text_xml.replace("</Properties>", f"<Company>{COMPANY}</Company></Properties>")
                data = text_xml.encode("utf-8")
            zout.writestr(info, data)
    return out.getvalue()


class AnonymizeTests(unittest.TestCase):
    def test_properties_app_xml_header_and_revisions_are_clean(self):
        from app.engines.export_anon import anonymize_docx, residual_identity

        source = make_identity_docx()
        self.assertTrue(residual_identity(source, [COMPANY]), "构造的样本本身应当带有身份信息")

        cleaned = anonymize_docx(source, [COMPANY])
        self.assertEqual(residual_identity(cleaned, [COMPANY]), [])

        import docx

        document = docx.Document(io.BytesIO(cleaned))
        props = document.core_properties
        self.assertEqual((props.author, props.last_modified_by, props.title), ("", "", ""))
        self.assertNotIn(COMPANY, document.sections[0].header.paragraphs[0].text)
        with zipfile.ZipFile(io.BytesIO(cleaned)) as zf:
            app_xml = zf.read("docProps/app.xml").decode("utf-8")
            body_xml = zf.read("word/document.xml").decode("utf-8")
        self.assertNotIn(COMPANY, app_xml)
        self.assertNotIn("<w:del ", body_xml)
        self.assertNotIn("<w:ins ", body_xml)
        self.assertNotIn("删除的文字", body_xml)
        self.assertIn("插入的文字", body_xml, "插入的修订按接受处理，文字保留")
        self.assertIn("本方案采用分层架构。", "\n".join(p.text for p in document.paragraphs))

    def test_bad_docx_raises(self):
        from app.engines.export_anon import anonymize_docx

        with self.assertRaises(Exception):
            anonymize_docx(b"not a docx", [COMPANY])


class ModeAndRuleTests(unittest.TestCase):
    def test_blind_default_follows_tender_and_only_tech(self):
        from app.engines.category_profile import default_export_mode, effective_export_mode

        required = {"anonymity_required": True}
        self.assertEqual(default_export_mode("tech", required), "暗标")
        self.assertEqual(default_export_mode("tech", {}), "明标")
        self.assertEqual(default_export_mode("business", required), "明标")
        # 用户手动选择优先，但商务册永远明标
        self.assertEqual(effective_export_mode("tech", "明标", required), "明标")
        self.assertEqual(effective_export_mode("tech", "暗标", {}), "暗标")
        self.assertEqual(effective_export_mode("tech", None, required), "暗标")
        self.assertEqual(effective_export_mode("business", "暗标", required), "明标")

    def test_rule_bundle_reads_the_right_tables_per_category(self):
        from app.engines import category_profile, rules_config

        eng = {
            "load_enabled_veto_keys": {"eng_veto"},
            "load_enabled_package_items": ["eng_item"],
            "load_enabled_filler_words": ["eng_word"],
            "load_thresholds": {"who": "eng"},
        }
        sw = {
            "load_enabled_sw_veto_keys": {"sw_veto"},
            "load_sw_local_items": ["sw_item"],
            "load_enabled_sw_filler_words": ["sw_word"],
            "load_sw_thresholds": {"who": "sw"},
        }
        patches = [mock.patch.object(rules_config, k, return_value=v) for k, v in {**eng, **sw}.items()]
        patches.append(mock.patch.object(rules_config, "load_enabled_catalog_keys", return_value={"eng_cat"}))
        patches.append(mock.patch.object(rules_config, "load_enabled_sw_catalog_keys", return_value={"sw_cat"}))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        engineering = category_profile.load_rule_bundle(object(), "工程类")
        self.assertTrue(engineering.is_engineering)
        self.assertEqual(engineering.veto_keys, {"eng_veto"})
        self.assertEqual(engineering.word_rules, ["eng_word"])
        self.assertEqual(engineering.thresholds, {"who": "eng"})
        self.assertEqual(engineering.biz_keys, {"eng_cat"})

        software = category_profile.load_rule_bundle(object(), "软件服务类")
        self.assertFalse(software.is_engineering)
        self.assertEqual(software.veto_keys, {"sw_veto"})
        self.assertEqual(software.word_rules, ["sw_word"])
        self.assertEqual(software.thresholds, {"who": "sw"})
        self.assertEqual(software.biz_keys, {"sw_cat"})
        # 别名
        self.assertTrue(category_profile.load_rule_bundle(object(), "工程标").is_engineering)
        self.assertFalse(category_profile.load_rule_bundle(object(), "产品标").is_engineering)

    def test_labels(self):
        from app.engines.category_profile import category_key, category_label

        self.assertEqual(category_label("工程类"), "工程标")
        self.assertEqual(category_label("软件服务类"), "软件服务标")
        self.assertEqual(category_key("工程标"), "工程类")
        self.assertEqual(category_key(None), "软件服务类")


class SummarizeTests(unittest.TestCase):
    def _finding(self, rule: str, severity: str = "扣分", excerpt: str = "x") -> dict:
        return {"rule": rule, "severity": severity, "excerpt": excerpt}

    def _summarize(self, findings, scope, mode="明标", params=None):
        from app.engines import export_check

        with mock.patch.object(export_check, "get_core_author", return_value=""):
            return export_check.summarize(findings, "ignored.docx", mode, scope, params)

    def test_business_booklet_has_no_tech_items(self):
        items, blocked, _ = self._summarize([], "business")
        self.assertEqual([i["key"] for i in items], ["waste", "layout"])
        self.assertFalse(blocked)

    def test_tech_booklet_has_filler_dup_and_is_not_blocked_by_soft_findings(self):
        findings = [self._finding("F10.02 语义空话"), self._finding("F06.05 查重"), self._finding("F06.06 版式")]
        items, blocked, _ = self._summarize(findings, "tech")
        keys = [i["key"] for i in items]
        self.assertEqual(keys, ["waste", "filler", "dup", "layout"])
        self.assertFalse(blocked, "扣分级问题只提示，不拦截导出")
        self.assertTrue(all(i["ok"] is False for i in items if i["key"] != "waste"))

    def test_only_veto_findings_block(self):
        items, blocked, reason = self._summarize([self._finding("F01.01 资格", "废标", "营业执照缺失")], "business")
        self.assertTrue(blocked)
        self.assertIn("营业执照缺失", reason)
        self.assertFalse(items[0]["ok"])

    def test_anonymity_warning_follows_tender(self):
        # 招标要求暗标但选了明标：只提示，不拦截
        items, blocked, _ = self._summarize([], "tech", "明标", {"anonymity_required": True})
        warn = next(i for i in items if i["key"] == "anon_required")
        self.assertFalse(warn["ok"])
        self.assertFalse(blocked)
        # 招标没要求暗标却选了暗标：提示
        items, _, _ = self._summarize([], "tech", "暗标", {})
        self.assertTrue(any(i["key"] == "anon_required" for i in items))
        self.assertTrue(any(i["key"] == "anon" for i in items))
        # 一致时没有提示；商务册永远没有
        items, _, _ = self._summarize([], "tech", "暗标", {"anonymity_required": True})
        self.assertFalse(any(i["key"] == "anon_required" for i in items))
        items, _, _ = self._summarize([], "business", "明标", {"anonymity_required": True})
        self.assertFalse(any(i["key"] == "anon_required" for i in items))


class ExportRouteTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base
        from app.routers import export

        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.export = export
        self.fake = FakeStorage()
        self.params: dict = {}
        self.run_checks_calls: list[dict] = []

        def fake_run_checks(db, path, checklist_params, must_respond, project_id, **kwargs):
            self.run_checks_calls.append(kwargs)
            return list(self.findings)

        self.findings: list[dict] = []
        patches = [
            mock.patch.object(export, "storage", self.fake),
            mock.patch.object(export, "require_project", lambda *a, **k: None),
            mock.patch.object(export, "write_audit", lambda *a, **k: None),
            mock.patch.object(export, "project_label", lambda *a, **k: "测试项目"),
            mock.patch.object(export.rules_config, "load_locked_checklist", lambda db, pid: (self.params, [])),
            mock.patch.object(export.export_check, "run_checks", fake_run_checks),
            mock.patch.object(export.export_check, "get_core_author", return_value=""),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.user = mock.Mock()
        self.user.name = "测试员"

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        self.engine.dispose()

    def _seed(self, category: str):
        """一个项目，商务册和技术册各有一份草稿和一个已保存版本，内容能互相区分。"""
        from app.models import BidDocument, BidRevision, BidRevisionVersion, ReviewRun, Project

        project = Project(code="P1", name="示范项目", type="公开招标", category=category)
        self.db.add(project)
        self.db.flush()
        docs = {}
        for scope in ("business", "tech"):
            data = make_identity_docx(body=f"这是{scope}册的正文。")
            key = self.fake.put_bytes(f"bid-documents/{project.id}", data, ".docx")
            doc = BidDocument(project_id=project.id, filename=f"{scope}.docx", storage_path=key, size_bytes=len(data), kind=scope)
            self.db.add(doc)
            self.db.flush()
            run = ReviewRun(project_id=project.id, bid_document_id=doc.id, round=1, status="done", scope=scope)
            self.db.add(run)
            self.db.flush()
            revision = BidRevision(project_id=project.id, scope=scope, bid_document_id=doc.id, review_run_id=run.id)
            self.db.add(revision)
            self.db.flush()
            version = BidRevisionVersion(revision_id=revision.id, label=f"{scope}-v1", bid_document_id=doc.id)
            self.db.add(version)
            docs[scope] = doc
        self.db.commit()
        return project, docs

    def _payload(self, scope: str, mode=None):
        from app.schemas import CreateExportIn

        return CreateExportIn(scope=scope, mode=mode)

    def _export_text(self, record) -> str:
        import docx

        from app.models import BidDocument

        doc = self.db.get(BidDocument, self.export_record_doc_id(record))
        document = docx.Document(io.BytesIO(self.fake.get_bytes(doc.storage_path)))
        return "\n".join(p.text for p in document.paragraphs)

    def export_record_doc_id(self, out) -> str:
        from app.models import ExportRecord

        return self.db.get(ExportRecord, out.id).bid_document_id

    def test_scope_selects_its_own_revision(self):
        project, docs = self._seed("工程类")
        out_b = self.export.create_export(project.id, self._payload("business"), self.db, self.user)
        out_t = self.export.create_export(project.id, self._payload("tech"), self.db, self.user)
        self.assertIn("business册", self._export_text(out_b))
        self.assertNotIn("tech册", self._export_text(out_b))
        self.assertIn("tech册", self._export_text(out_t))
        self.assertEqual((out_b.scope, out_t.scope), ("business", "tech"))

    def test_missing_booklet_gives_readable_error(self):
        from fastapi import HTTPException

        from app.models import BidRevision, Project

        project = Project(code="P2", name="只有商务册", type="公开招标", category="软件服务类")
        self.db.add(project)
        self.db.commit()
        with self.assertRaises(HTTPException) as ctx:
            self.export.create_export(project.id, self._payload("tech"), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("技术标", ctx.exception.detail)
        self.assertEqual(self.db.query(BidRevision).count(), 0)

    def test_record_carries_scope_category_and_filename(self):
        for category, label in (("工程类", "工程类"), ("软件服务类", "软件服务类")):
            with self.subTest(category=category):
                self.setUp_clean()
                project, _ = self._seed(category)
                out = self.export.create_export(project.id, self._payload("tech", "明标"), self.db, self.user)
                self.assertEqual(out.category, label)
                self.assertEqual(out.scope, "tech")
                self.assertEqual(out.mode, "明标")
                self.assertEqual(out.filename, "示范项目-技术标-明标.docx")
                self.assertEqual(self.run_checks_calls[-1]["category"], label)
                self.assertEqual(self.run_checks_calls[-1]["scope"], "tech")
                listed = self.export.list_export_records(project.id, self.db, self.user)
                self.assertEqual((listed[0].scope, listed[0].category), ("tech", label))

    def setUp_clean(self):
        """subTest 之间重置库和存储。"""
        from app.models import Base

        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db.expire_all()
        self.fake.blobs.clear()
        self.run_checks_calls.clear()

    def test_tech_blind_follows_tender_and_cleans_identity(self):
        from app.engines.export_anon import residual_identity
        from app.models import BidDocument, QualificationAsset

        project, _ = self._seed("工程类")
        self.params.update({"anonymity_required": True})
        self.db.add(QualificationAsset(name="营业执照", kind="cert", owner=COMPANY, review_status="已入库"))
        self.db.commit()

        out = self.export.create_export(project.id, self._payload("tech"), self.db, self.user)  # 不传 mode，跟随招标
        self.assertEqual(out.mode, "暗标")
        doc = self.db.get(BidDocument, self.export_record_doc_id(out))
        self.assertEqual(doc.source, "export-anon")
        self.assertEqual(doc.kind, "tech")
        self.assertEqual(residual_identity(self.fake.get_bytes(doc.storage_path), [COMPANY]), [])
        self.assertEqual(self.run_checks_calls[-1]["mode"], "暗标")

    def test_user_can_override_to_clear_even_if_tender_requires_blind(self):
        project, _ = self._seed("软件服务类")
        self.params.update({"anonymity_required": True})
        out = self.export.create_export(project.id, self._payload("tech", "明标"), self.db, self.user)
        self.assertEqual(out.mode, "明标")
        checks = self.export.get_export_checks(project.id, "tech", "明标", self.db, self.user)
        self.assertIn("anon_required", [i.key for i in checks.items])
        self.assertEqual(checks.defaultMode, "暗标")

    def test_business_booklet_never_blind(self):
        from fastapi import HTTPException

        project, _ = self._seed("工程类")
        self.params.update({"anonymity_required": True})
        with self.assertRaises(HTTPException) as ctx:
            self.export.create_export(project.id, self._payload("business", "暗标"), self.db, self.user)
        self.assertEqual(ctx.exception.status_code, 400)
        out = self.export.create_export(project.id, self._payload("business"), self.db, self.user)
        self.assertEqual(out.mode, "明标")
        checks = self.export.get_export_checks(project.id, "business", None, self.db, self.user)
        self.assertFalse(checks.blindAllowed)
        self.assertEqual(checks.defaultMode, "明标")

    def test_checks_expose_category_and_default_mode(self):
        project, _ = self._seed("工程类")
        self.params.update({"anonymity_required": True})
        checks = self.export.get_export_checks(project.id, "tech", None, self.db, self.user)
        self.assertEqual((checks.category, checks.categoryLabel), ("工程类", "工程标"))
        self.assertEqual((checks.mode, checks.defaultMode), ("暗标", "暗标"))
        self.assertTrue(checks.anonymityRequired)
        self.assertTrue(checks.blindAllowed)

    def test_veto_blocks_export_and_records_block(self):
        from fastapi import HTTPException

        from app.models import ExportRecord

        project, _ = self._seed("软件服务类")
        self.findings = [{"rule": "F01.01 资格", "severity": "废标", "excerpt": "缺营业执照"}]
        with self.assertRaises(HTTPException):
            self.export.create_export(project.id, self._payload("business"), self.db, self.user)
        record = self.db.query(ExportRecord).one()
        self.assertEqual((record.check_status, record.scope, record.category), ("阻断", "business", "软件服务类"))


class WriterExportTests(unittest.TestCase):
    def test_deep_outline_keeps_heading_levels_beyond_three(self):
        import docx

        from app.engines.writer_export import chapters_to_docx

        outline = [{"id": "n1", "parentId": None, "title": "第一层", "num": "一、", "part": "tech"}]
        for depth in range(2, 7):
            outline.append({"id": f"n{depth}", "parentId": f"n{depth - 1}", "title": f"第{depth}层", "num": "", "part": "tech"})
        data = chapters_to_docx("深层目录", outline, {"n6": "正文。"}, {}, None)
        document = docx.Document(io.BytesIO(data))
        styles = [p.style.name for p in document.paragraphs]
        for level in range(1, 7):
            self.assertIn(f"Heading {level}", styles)

    def test_content_subtitles_do_not_use_heading_styles(self):
        import docx

        from app.engines.writer_export import chapters_to_docx

        outline = [{"id": "a", "parentId": None, "title": "技术方案", "num": "一、", "part": "tech"}]
        data = chapters_to_docx("项目", outline, {"a": "## 解决方案\n\n### 子要点\n\n正文一段。"}, {}, None)
        document = docx.Document(io.BytesIO(data))
        headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
        self.assertIn("一、 技术方案", headings)
        self.assertNotIn("解决方案", headings)
        self.assertNotIn("子要点", headings)
        sub = next(p for p in document.paragraphs if p.text == "解决方案")
        self.assertTrue(all(run.bold for run in sub.runs))

    def test_toc_allows_five_levels(self):
        from app.engines.writer_layout import merge_layout

        layout = merge_layout(None, {"preset": "工程投标标准"})
        patched = merge_layout(layout, {"toc": {"enabled": True, "levels": 5}})
        self.assertEqual(patched["toc"]["levels"], 5)
        with self.assertRaises(ValueError):
            merge_layout(layout, {"toc": {"enabled": True, "levels": 9}})

    def test_filename_and_blind_layout(self):
        from app.engines.writer_export import blind_layout, draft_filename

        self.assertEqual(draft_filename("示范项目", "tech"), "示范项目-技术标（撰写工作台导出）.docx")
        self.assertEqual(draft_filename("示范项目", "business"), "示范项目-商务标（撰写工作台导出）.docx")
        self.assertNotEqual(draft_filename("示范项目", "tech"), draft_filename("示范项目", "business"))

        layout = {"cover": {"enabled": True, "company": COMPANY, "date": "2026年1月"}, "header": f"{COMPANY} 技术标"}
        blind = blind_layout(layout, [COMPANY])
        self.assertEqual(blind["cover"]["company"], "")
        self.assertEqual(blind["cover"]["date"], "")
        self.assertNotIn(COMPANY, blind["header"])
        self.assertEqual(layout["cover"]["company"], COMPANY, "不能改动原版式")


if __name__ == "__main__":
    unittest.main()
