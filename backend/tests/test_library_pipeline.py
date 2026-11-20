import unittest
from unittest import mock


class TableMdTest(unittest.TestCase):
    def test_rows_to_markdown_keeps_columns_and_escapes_pipe(self):
        from app.engines.table_md import markdown_table_rows, rows_to_markdown

        md = rows_to_markdown([["姓名", "证书"], ["李翔", "PMP|高级"], ["", ""]])
        self.assertEqual(md.split("\n")[1], "| --- | --- |")
        self.assertEqual(len(md.split("\n")), 3)
        self.assertEqual(markdown_table_rows(md)[1], ["李翔", "PMP|高级"])

    def test_single_column_is_plain_text(self):
        from app.engines.table_md import rows_to_markdown

        self.assertEqual(rows_to_markdown([["第一行"], ["第二行"]]), "第一行\n第二行")

    def test_docx_merged_cells_not_duplicated(self):
        import docx

        from app.engines.table_md import docx_table_rows

        document = docx.Document()
        table = document.add_table(rows=2, cols=3)
        table.cell(0, 0).merge(table.cell(0, 1))
        table.cell(0, 0).text = "合并头"
        table.cell(0, 2).text = "C"
        table.cell(1, 0).text = "a"
        table.cell(1, 1).text = "b"
        table.cell(1, 2).text = "c"
        rows = docx_table_rows(table)
        self.assertEqual(rows[0], ["合并头", "C"])
        self.assertEqual(rows[1], ["a", "b", "c"])


class QualificationParseTest(unittest.TestCase):
    def test_fragment_names_rejected(self):
        from app.engines.qualification_schema import is_fragment_name

        for name in ("职务", "项目方", "项目覆盖人员规模", "1", "2、", "保密说明：", "ab"):
            self.assertTrue(is_fragment_name(name), name)
        for name in ("营业执照", "中国银联在线培训平台项目"):
            self.assertFalse(is_fragment_name(name), name)
        self.assertFalse(is_fragment_name("李翔", 2))
        self.assertTrue(is_fragment_name("职务", 2))

    def test_clean_attrs_keeps_only_allowed(self):
        from app.engines.qualification_schema import clean_attrs

        out = clean_attrs("contract", {"client": "A银行", "foo": "x", "amount": "158万元", "scope": "无"})
        self.assertEqual(out, {"client": "A银行", "amount": "158万元"})

    def test_candidate_from_row_builds_name_and_drops_people_without_owner(self):
        from app.engines.qualification_extract import _candidate_from_row

        cand = _candidate_from_row(
            {"kind": "contract", "name": "1", "attrs": {"client": "A银行", "projectName": "在线培训平台", "amount": "158万元"}},
            "合同", "text",
        )
        self.assertEqual(cand["name"], "A银行在线培训平台")
        self.assertEqual(cand["attrs"]["amount"], "158万元")
        self.assertIsNone(_candidate_from_row({"kind": "people", "name": "项目经理简历表", "attrs": {}}, "h", "t"))
        person = _candidate_from_row({"kind": "people", "name": "杨津", "attrs": {"role": "项目经理"}}, "h", "t")
        self.assertEqual(person["owner"], "杨津")

    def test_table_blocks_have_no_regex_fallback(self):
        from app.engines.qualification_extract import _fallback_from_block

        self.assertEqual(_fallback_from_block({"heading": "合同证明", "text": "| a | b |\n| --- | --- |", "rows": [["a", "b"]]}), [])

    def test_llm_failure_on_table_returns_nothing(self):
        from app.engines import qualification_extract as qe

        with mock.patch.object(qe, "chat_complete", side_effect=qe.LlmError("down")):
            out = qe._llm_fill_block({"heading": "业绩合同", "text": "x", "rows": [["客户", "金额"], ["A", "1"], ["B", "2"]]})
        self.assertEqual(out, [])

    def test_identity_key_for_contract_uses_client_and_project(self):
        from app.engines.qualification_dedup import identity_key

        a = {"kind": "contract", "name": "x", "attrs": {"client": "A 银行", "projectName": "培训平台"}}
        b = {"kind": "contract", "name": "y", "attrs": {"client": "A银行", "projectName": "培训平台"}}
        self.assertEqual(identity_key(a), identity_key(b))
        self.assertTrue(identity_key(a).startswith("contract|"))

    def test_describe_only_uses_library_values(self):
        from app.engines.qualification_schema import describe

        text = describe("contract", {"client": "A银行", "amount": "158万元"})
        self.assertIn("客户：A银行", text)
        self.assertIn("合同金额：158万元", text)
        self.assertNotIn("项目名称", text)

    def test_tidy_drops_bare_list_lines_and_strips_heading_number(self):
        from app.engines.qualification_extract import _tidy_candidate

        self.assertIsNone(_tidy_candidate({"name": "3、江苏银行（2012年-至今提供2018年合同）", "attrs": {}}))
        kept = _tidy_candidate({"name": "5.2.1 ISO9001质量管理体系认证证书", "attrs": {}})
        self.assertEqual(kept["name"], "ISO9001质量管理体系认证证书")
        rich = _tidy_candidate({"name": "1、某合同", "attrs": {"client": "某银行"}})
        self.assertIsNotNone(rich)


if __name__ == "__main__":
    unittest.main()


class ProductSourceTextTest(unittest.TestCase):
    def test_pipe_table_conversion_is_idempotent(self):
        from app.engines.standard_product import pipe_tables_to_markdown as f

        once = f("用途 | 系统 | CPU\n应用 | Linux | 24\n\n正文。")
        self.assertIn("| --- | --- | --- |", once)
        self.assertEqual(f(once), once)

    def test_copy_prefers_locked_then_source_then_rewrite(self):
        from app.engines.standard_product import copy_of

        base = {"bidCopy": "改写稿", "intro": "简介", "sourceText": "原文全文", "lockedCopy": False}
        self.assertEqual(copy_of(base), "原文全文")
        self.assertEqual(copy_of({**base, "lockedCopy": True}), "改写稿")
        self.assertEqual(copy_of({**base, "sourceText": ""}), "改写稿")
        self.assertEqual(copy_of({"intro": "简介"}), "简介")

    def test_source_text_capped_at_line_boundary(self):
        from app.engines.standard_product import SOURCE_TEXT_CAP, copy_of

        text = "\n".join(["第%d行" % i + "x" * 50 for i in range(400)])
        out = copy_of({"sourceText": text})
        self.assertLessEqual(len(out), SOURCE_TEXT_CAP)
        self.assertTrue(out.endswith("x"))


class KnowledgeRetrievalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        import tempfile

        os.environ.setdefault("WRITER_WORKSPACE_ROOT", tempfile.mkdtemp())
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base

        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        from app.engines import knowledge_retrieval as kr
        from app.models import KnowledgeDocument, KnowledgeSlice, KnowledgeSliceImage

        kr.clear_cache()
        self.kr = kr
        self.db = self.Session()
        for model in (KnowledgeSliceImage, KnowledgeSlice, KnowledgeDocument):
            self.db.query(model).delete()
        self.db.add(KnowledgeDocument(id="d1", scope="企业库", type="专项方案", title="方案A", filename="a.docx", storage_path="x"))
        self.db.add(KnowledgeSlice(id="s1", document_id="d1", heading="概述", seq=1, text="平台概述内容", level="一级"))
        self.db.add(KnowledgeSlice(id="s2", document_id="d1", heading="签到", seq=2, text="二维码签到与手写签名", level="一级"))
        self.db.add(KnowledgeSlice(id="s3", document_id="d1", heading="签到方式", seq=3, text="位置签到\n动态二维码", level="二级", parent_id="s2"))
        self.db.add(KnowledgeSlice(id="s4", document_id="d1", heading="概述", seq=4, text="另一处同名概述", level="一级"))
        self.db.add(KnowledgeSliceImage(id="i1", slice_id="s3", caption="图", filename="f.png", storage_path="p"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_unmatched_heading_returns_nothing_not_whole_doc(self):
        self.assertEqual(self.kr.retrieve_by_doc_and_headings(self.db, "d1", ["不存在的标题"]), [])

    def test_subtree_includes_children_and_images(self):
        out = self.kr.retrieve_by_doc_and_headings(self.db, "d1", ["签到"])
        self.assertEqual([r["heading"] for r in out], ["签到", "签到方式"])
        self.assertEqual(len(out[1]["images"]), 1)

    def test_duplicate_heading_takes_first_only_and_id_ref_works(self):
        out = self.kr.retrieve_by_doc_and_headings(self.db, "d1", ["概述"])
        self.assertEqual([r["text"] for r in out], ["平台概述内容"])
        out = self.kr.retrieve_by_doc_and_headings(self.db, "d1", ["id:s4"])
        self.assertEqual([r["text"] for r in out], ["另一处同名概述"])

    def test_char_cap_truncates_text_but_keeps_all_slices(self):
        from app.models import KnowledgeSlice

        self.db.add(KnowledgeSlice(id="s5", document_id="d1", heading="长章", seq=5, text="\n".join(["行" * 40] * 200), level="一级"))
        self.db.commit()
        self.kr.clear_cache()
        out = self.kr.retrieve_by_doc_and_headings(self.db, "d1", [], max_chars=3000)
        self.assertEqual(len(out), 5)
        long = next(r for r in out if r["heading"] == "长章")
        self.assertLess(len(long["text"]), 1500)
        self.assertIn("已截取", long["text"])

    @unittest.skipUnless(__import__("importlib").util.find_spec("rank_bm25"), "rank_bm25 not installed")
    def test_heading_is_indexed_for_retrieval(self):
        from app.models import KnowledgeSlice

        self.db.add(KnowledgeSlice(id="s6", document_id="d1", heading="防作弊机制", seq=6, text="", level="一级"))
        self.db.commit()
        self.kr.clear_cache()
        hits = self.kr.suggest_docs(self.db, ["d1"], "防作弊机制")
        self.assertEqual(hits[0]["chapters"][0], "防作弊机制")
