"""撰写 Harness 的工作区隔离和目录、正文验收，不调用外部模型。"""

from __future__ import annotations

import os
import tempfile
import unittest

from app.engines.writer_harness import (
    HarnessError,
    _bad_outline_headings,
    _outline_has_heading,
    _coverage_problems,
    content_edit_block_reason,
    outline_add,
    outline_delete,
    renumber_outline,
    scoped_workspace,
)


class WriterHarnessIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["WRITER_WORKSPACE_ROOT"] = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_users_and_jobs_do_not_share_directories(self) -> None:
        chat_a = scoped_workspace("user-a", "proj-1", "draft-1", "chat")
        chat_b = scoped_workspace("user-b", "proj-1", "draft-1", "chat")
        job = scoped_workspace("user-a", "proj-1", "draft-1", "jobs", "wjob-1")
        self.assertNotEqual(chat_a, chat_b)
        self.assertFalse(str(job).startswith(str(chat_a)))
        self.assertTrue(chat_a.is_dir())
        self.assertTrue(job.is_dir())

    def test_path_escape_is_rejected(self) -> None:
        with self.assertRaises(HarnessError):
            scoped_workspace("../user", "proj-1", "draft-1", "chat")
        with self.assertRaises(HarnessError):
            scoped_workspace("user-a", "proj-1", "draft-1", "jobs", "..")


class WriterHarnessRulesTest(unittest.TestCase):
    def test_outline_rejects_requirement_sentences(self) -> None:
        bad = _bad_outline_headings("# 支持全天候提供咨询服务。\n## 实施方案")
        self.assertTrue(any("支持" in item or "。" in item for item in bad))
        self.assertEqual(_bad_outline_headings("# 项目实施方案\n## 进度计划"), [])

    def test_chapter_coverage_requires_titles(self) -> None:
        problems = _coverage_problems(
            [{"title": "全天候热线"}],
            "本章说明服务方式。",
            ["客服热线"],
            False,
        )
        self.assertTrue(any("全天候热线" in item for item in problems))
        self.assertEqual(
            _coverage_problems([{"title": "全天候热线"}], "全天候热线由客服热线承接。", ["客服热线"], False),
            [],
        )

    def test_form_and_price_cannot_be_rewritten(self) -> None:
        self.assertIsNotNone(content_edit_block_reason({"title": "投标报价表", "part": "form"}))
        self.assertIsNotNone(content_edit_block_reason({"title": "法定代表人授权委托书", "part": "business"}))
        self.assertIsNone(content_edit_block_reason({"title": "系统功能响应", "part": "tech", "requirement": "应实现登录"}))

    def test_outline_add_delete_and_renumber(self) -> None:
        nodes = [
            {"id": "form", "parentId": None, "title": "投标函", "num": ""},
            {"id": "tech", "parentId": None, "title": "技术方案", "num": ""},
        ]
        numbered = renumber_outline(nodes)
        self.assertEqual(numbered[0]["num"], "一、")
        self.assertEqual(numbered[1]["num"], "二、")
        added, created = outline_add(numbered, titles=["登录", "权限"], parent_id="tech")
        self.assertEqual(len(created), 2)
        self.assertEqual(added[2]["parentId"], "tech")
        self.assertEqual(added[2]["num"], "（一）")
        self.assertEqual(added[3]["num"], "（二）")
        remain, deleted = outline_delete(added, ["form"])
        self.assertEqual(deleted, ["form"])
        self.assertEqual(remain[0]["id"], "tech")
        self.assertEqual(remain[0]["num"], "一、")
        self.assertEqual(len(remain), 3)
        with self.assertRaises(HarnessError):
            outline_delete(remain, ["tech"])
        remain, deleted = outline_delete(remain, [created[0]["id"]])
        self.assertEqual(deleted, [created[0]["id"]])
        self.assertEqual(remain[1]["num"], "（一）")
        with self.assertRaises(HarnessError):
            outline_delete([{"id": "only", "parentId": None, "title": "独章"}], ["only"])

    def test_upload_reader_lists_and_rejects_unknown_names(self) -> None:
        import os
        import tempfile

        from app.engines.writer_harness import read_upload_text

        self.assertEqual(read_upload_text([], "说明.docx"), "没有这个附件")
        from app.config import get_settings

        listed = read_upload_text([{"filename": "说明.txt", "storagePath": "missing"}], "")
        self.assertIn("说明.txt", listed)
        # 历史本地路径只认上传目录下的文件
        upload_dir = get_settings().upload_dir
        os.makedirs(upload_dir, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".txt", dir=upload_dir)
        os.write(fd, "全天候热线".encode("utf-8"))
        os.close(fd)
        try:
            text = read_upload_text([{"filename": "说明.txt", "storagePath": path}], "说明.txt")
        finally:
            os.remove(path)
        self.assertIn("全天候热线", text)

    def test_upload_reader_describes_images_without_opening(self) -> None:
        from app.engines.writer_harness import read_upload_text

        listed = read_upload_text([{"filename": "截图.png", "storagePath": "missing"}], "")
        self.assertIn("截图.png", listed)
        self.assertIn("图片", listed)
        note = read_upload_text([{"filename": "截图.png", "storagePath": "missing"}], "截图.png")
        self.assertIn("画面", note)

    def test_chat_trace_keeps_thinking_tool_and_reply(self) -> None:
        from app.engines.writer_harness import apply_chat_event, chat_trace_snapshot, new_chat_trace

        class Event:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        state = new_chat_trace("deepseek-v4-flash")
        apply_chat_event(state, Event(type="MODEL_CALL_START", model_name="deepseek-v4-flash"))
        apply_chat_event(state, Event(type="THINKING_BLOCK_START", block_id="b1"))
        apply_chat_event(state, Event(type="THINKING_BLOCK_DELTA", block_id="b1", delta="先读附件"))
        apply_chat_event(state, Event(type="TOOL_CALL_START", tool_call_id="t1", tool_call_name="read_upload"))
        apply_chat_event(state, Event(type="TOOL_CALL_DELTA", tool_call_id="t1", delta='{"filename":"a.txt"}'))
        apply_chat_event(state, Event(type="TOOL_RESULT_TEXT_DELTA", tool_call_id="t1", delta="热线要求"))
        apply_chat_event(state, Event(type="TEXT_BLOCK_DELTA", block_id="x", delta="已按附件修改标题"))
        apply_chat_event(state, Event(get_text_content=lambda: "已按附件修改标题"))
        titles = [step["title"] for step in chat_trace_snapshot(state)]
        self.assertEqual(titles[0], "AgentScope")
        self.assertIn("思考", titles)
        self.assertTrue(any(title.startswith("阅读附件") for title in titles))
        self.assertEqual(state["reply"], "已按附件修改标题")
        self.assertIn("热线要求", chat_trace_snapshot(state)[3]["detail"])
        apply_chat_event(state, Event(type="TOOL_RESULT_END", tool_call_id="t1", state="ERROR"))
        self.assertEqual(chat_trace_snapshot(state)[3]["status"], "error")

    def test_reply_end_reports_limit_and_error(self) -> None:
        from app.engines.writer_harness import apply_chat_event, new_chat_trace

        class Event:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Err:
            message = "上游 429"

        state = new_chat_trace()
        apply_chat_event(state, Event(type="REPLY_END", finished_reason="exceed_max_iters"))
        apply_chat_event(state, Event(type="EXCEED_MAX_ITERS"))
        self.assertEqual(sum(1 for step in state["steps"] if step["kind"] == "limit"), 1)
        apply_chat_event(state, Event(type="REPLY_END", finished_reason="error", error=Err()))
        self.assertEqual(state["error"], "上游 429")

    def test_image_goes_to_model_as_data_block(self) -> None:
        from unittest import mock

        from agentscope.message import DataBlock, UserMsg

        from app.engines import writer_harness as harness

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
        with mock.patch("app.storage.get_bytes", return_value=png):
            content = harness.chat_user_content("看这张图", [{"filename": "a.png", "storagePath": "k"}])
        self.assertIsInstance(content, list)
        self.assertIsInstance(content[1], DataBlock)
        self.assertEqual(content[1].source.media_type, "image/png")
        msg = UserMsg(name="user", content=content)
        self.assertEqual(len([b for b in msg.content if getattr(b, "type", "") == "data"]), 1)

    def test_tool_success_is_marked_and_failure_raises(self) -> None:
        import asyncio

        from agentscope.message import ToolResultState

        from app.engines import writer_harness as harness

        self.assertEqual(harness._text_chunk("ok").state, ToolResultState.SUCCESS)

        class Binding:
            user_id = "u"
            draft_id = "d"

            def delete_outline_node(self, *_args):
                raise HarnessError("章节不存在")

        from pathlib import Path

        tools = {tool.name: tool for tool in harness._chat_tools(Binding(), Path(tempfile.gettempdir()), "p")}
        with self.assertRaises(HarnessError):
            asyncio.run(tools["delete_outline_node"].call(chapter_id="x"))

    def test_insert_figures_places_after_heading_with_caption(self) -> None:
        from app.engines.writer_harness import insert_figures_into_markdown

        md = "## 解决方案\n\n### 总体架构\n\n说明一。\n\n### 实施计划\n\n说明二。\n"
        fig = {"markdown": "![架构](/api/writer-images/wimg-1/file)", "caption": "总体架构图", "afterHeading": "总体架构"}
        out = insert_figures_into_markdown(md, [fig])
        self.assertLess(out.index("说明一"), out.index("wimg-1"))
        self.assertLess(out.index("wimg-1"), out.index("### 实施计划"))
        self.assertIn(">>> 图：总体架构图", out)
        tail = insert_figures_into_markdown(md, [{**fig, "afterHeading": "不存在"}])
        self.assertGreater(tail.index("wimg-1"), tail.index("说明二"))

    def test_knowledge_tools_stay_inside_selected_documents(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        from app.engines.writer_harness import DraftBinding

        class Db:
            def close(self):
                pass

        draft = SimpleNamespace(selected_knowledge_json=[], model_id=None, project_id="p")
        binding = DraftBinding("u", "d", "c")
        with mock.patch.object(DraftBinding, "_open", return_value=(Db(), draft, None)):
            self.assertIn("没有选择知识库", binding.search_knowledge("架构"))
            with self.assertRaises(HarnessError):
                binding.read_knowledge_section("doc-x", "标题")
            with self.assertRaises(HarnessError):
                binding.search_knowledge("  ")

    def test_diagram_tool_waits_for_solution_and_registers_figure(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        from app.engines.writer_harness import DraftBinding

        class Db:
            def close(self):
                pass

        draft = SimpleNamespace(model_id=None, project_id="p", selected_knowledge_json=[])
        binding = DraftBinding("u", "d", "c1")
        state = {"title": "总体架构", "idea": "", "solution": "", "figures": []}
        with mock.patch.object(DraftBinding, "_open", return_value=(Db(), draft, None)):
            with self.assertRaises(HarnessError):
                binding.make_diagram("technical", "", "", "", state)
            with self.assertRaises(HarnessError):
                binding.make_diagram("不存在", "", "", "", state)
            state["solution"] = "平台分为接入层、服务层和数据层。" * 10
            with mock.patch("app.engines.writer_diagram.create_diagram_png", return_value=(b"png", "arch", "技术架构", "")):
                with mock.patch.object(DraftBinding, "_save_image", return_value="wimg-9"):
                    text = binding.make_diagram("technical", "", "总体架构", "技术架构图", state)
            self.assertIn("wimg-9", text)
            self.assertEqual(len(state["figures"]), 1)
            self.assertIn("/api/writer-images/wimg-9/file", state["figures"][0]["markdown"])
            state["figures"].append({"markdown": "![x](/api/writer-images/wimg-8/file)", "caption": "x", "afterHeading": ""})
            with self.assertRaises(HarnessError):
                binding.make_diagram("technical", "", "", "", state)

    def test_export_readiness_notes_report_empty_chapters_and_missing_images(self) -> None:
        from app.engines.writer_tool_runtime import export_readiness_notes

        outline = [
            {"id": "a", "parentId": None, "title": "技术方案", "num": "一、"},
            {"id": "b", "parentId": "a", "title": "总体架构", "num": "（一）", "part": "tech"},
            {"id": "c", "parentId": "a", "title": "实施计划", "num": "（二）", "part": "tech"},
        ]
        contents = {"c": "正文\n![图](/api/writer-images/gone/file)"}
        notes = export_readiness_notes(outline, contents, set())
        self.assertTrue(any("总体架构" in item and "没有正文" in item for item in notes))
        self.assertTrue(any("gone" in item for item in notes))


class WriterLayoutTest(unittest.TestCase):
    def test_merge_layout_rules(self) -> None:
        from app.engines.writer_layout import merge_layout

        base = {"fromTender": True, "bodyFont": "仿宋", "bodySizePt": 14, "fontSize": "四号", "indentChars": 2}
        merged = merge_layout(base, {"preset": "政府采购标准"})
        self.assertEqual(merged["bodyFont"], "仿宋")
        self.assertEqual(merged["bodySizePt"], 14)
        self.assertEqual(merged["headings"]["h1"]["font"], "黑体")
        self.assertEqual(merged["pageNumber"], "full")
        merged = merge_layout(merged, {"fontSize": "小四", "headings": {"h1": {"size": "二号", "align": "center"}}})
        self.assertEqual(merged["bodySizePt"], 12)
        self.assertEqual(merged["headings"]["h1"]["sizePt"], 22)
        self.assertEqual(merged["headings"]["h1"]["font"], "黑体")
        merged = merge_layout(merged, {"lineSpacingExactPt": 28})
        self.assertIsNone(merged["lineSpacingMul"])
        for bad in ({"bodySizePt": 500}, {"preset": "不存在"}, {"pageNumber": "x"}, {"unknown": 1}, {"margins": {"top": 99}}):
            with self.assertRaises(ValueError):
                merge_layout(base, bad)

    def test_docx_export_applies_layout_features(self) -> None:
        import io

        import docx
        from docx.oxml.ns import qn

        from app.engines.writer_export import chapters_to_docx
        from app.engines.writer_layout import merge_layout

        layout = merge_layout(None, {"preset": "工程投标标准"})
        layout = merge_layout(layout, {"table": {"headerFill": "FFE699"}, "headings": {"h2": {"font": "楷体"}}})
        outline = [
            {"id": "a", "parentId": None, "title": "技术方案", "num": "一、", "part": "tech"},
            {"id": "b", "parentId": "a", "title": "总体架构", "num": "（一）", "part": "tech"},
        ]
        contents = {
            "b": "## 解决方案\n\n平台分三层。\n\n>>> 图：总体架构图\n\n| 项 | 值 |\n| --- | --- |\n| 并发 | 1000 |\n\n>>> 表：性能指标\n"
        }
        data = chapters_to_docx("测试项目", outline, contents, {}, layout)
        doc = docx.Document(io.BytesIO(data))
        xml = doc.element.xml
        self.assertIn("测试项目", xml)
        self.assertIn("TOC", xml)  # 自动目录域
        self.assertIn("SEQ 图", xml)
        self.assertIn("SEQ 表", xml)
        self.assertIn("FFE699", xml)  # 表头底色
        footer_xml = doc.sections[0].footer._element.xml
        self.assertIn("PAGE", footer_xml)
        self.assertIn("NUMPAGES", footer_xml)
        self.assertEqual(doc.sections[0].header.paragraphs[0].text, "测试项目")
        h1 = doc.styles["Heading 1"]
        self.assertEqual(h1.font.size.pt, 22)
        self.assertEqual(h1.element.rPr.rFonts.get(qn("w:eastAsia")), "黑体")
        h2 = doc.styles["Heading 2"]
        self.assertEqual(h2.element.rPr.rFonts.get(qn("w:eastAsia")), "楷体")
        normal = doc.styles["Normal"]
        self.assertEqual(normal.element.rPr.rFonts.get(qn("w:ascii")), "Times New Roman")
        self.assertEqual(normal.element.rPr.rFonts.get(qn("w:eastAsia")), "仿宋")
        self.assertEqual(normal.font.size.pt, 14)
        self.assertIsNone(h1.element.rPr.rFonts.get(qn("w:eastAsiaTheme")))
        body = next(p for p in doc.paragraphs if p.text.startswith("平台分三层"))
        self.assertEqual(body.runs[0].font.size.pt, 14)
        self.assertEqual(body.runs[0]._element.rPr.rFonts.get(qn("w:eastAsia")), "仿宋")
        mixed = chapters_to_docx(
            "混字体",
            [{"id": "a", "parentId": None, "title": "章", "num": "一、", "part": "tech"}],
            {"a": "{{楷体:10.5pt}}这段不该是楷体五号。"},
            {},
            {"fromTender": True, "bodyFont": "楷体", "bodySizePt": 10.5, "fontSize": "五号"},
        )
        mixed_doc = docx.Document(io.BytesIO(mixed))
        sample = next(p for p in mixed_doc.paragraphs if "不该是楷体" in p.text)
        self.assertEqual(sample.runs[0]._element.rPr.rFonts.get(qn("w:eastAsia")), "仿宋")
        self.assertEqual(sample.runs[0].font.size.pt, 12)
        self.assertEqual(sample.paragraph_format.first_line_indent.pt, 24)

    def test_legacy_layout_still_exports(self) -> None:
        import io

        import docx

        from app.engines.writer_export import chapters_to_docx

        legacy = {"margins": {"top": 2, "bottom": 2, "left": 2, "right": 2}, "fontSize": "小四", "lineSpacing": "1.5倍行距"}
        outline = [{"id": "a", "parentId": None, "title": "技术方案", "num": "一、", "part": "tech"}]
        data = chapters_to_docx("旧项目", outline, {"a": "## 解决方案\n\n正文一段。"}, {}, legacy)
        doc = docx.Document(io.BytesIO(data))
        self.assertEqual(doc.styles["Normal"].font.size.pt, 12)
        self.assertNotIn("TOC", doc.element.xml)


class WriterToolRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workdir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tender_search_hits_tech_section(self) -> None:
        from app.engines.writer_tool_runtime import materialize_tender_extracts, read_tender_text, skill_directories

        self.assertEqual(len(skill_directories()), 4)
        water_dirs = skill_directories("water")
        self.assertEqual(len(water_dirs), 5)
        self.assertTrue(any(path.endswith("water-bid") for path in water_dirs))
        self.assertFalse(any(path.endswith("water-bid") for path in skill_directories("engineering")))

        workdir = self.workdir
        materialize_tender_extracts(
            workdir,
            {
                "tech": "应提供全天候热线\n支持双因素登录",
                "business": "近三年业绩不少于三项",
                "format": "- 技术标\n- 商务标",
            },
        )
        listed = read_tender_text(workdir, section="tech")
        self.assertIn("全天候热线", listed)
        hit = read_tender_text(workdir, section="tech", query="热线")
        self.assertIn("全天候热线", hit)
        self.assertNotIn("双因素登录", hit)
        miss = read_tender_text(workdir, section="business", query="热线")
        self.assertIn("未命中", miss)

    def test_skill_script_rejects_escape_and_unknown(self) -> None:
        from app.engines.writer_tool_runtime import resolve_skill_script, run_skill_script

        with self.assertRaises(ValueError):
            resolve_skill_script("../bid-outline", "lint_outline.py")
        with self.assertRaises(ValueError):
            resolve_skill_script("bid-outline", "lint_outline.sh")
        text = run_skill_script(self.workdir, "bid-outline", "not_there.py")
        self.assertIn("没有这个脚本", text)
        unsafe = run_skill_script(self.workdir, "bid-outline", "lint_outline.py", ["outline.md;rm"])
        self.assertIn("参数不安全", unsafe)

    def test_requirement_pages_keep_whole_items(self) -> None:
        from app.engines.writer_tool_runtime import materialize_tender_extracts, read_tender_text

        items = [f"{index}、功能域{index}：" + ("指标" * 2000) for index in range(1, 18)]
        materialize_tender_extracts(self.workdir, {"tech": "\n".join(items), "business": "", "format": ""})
        page1 = read_tender_text(self.workdir, section="tech", page=1)
        self.assertIn("功能域1", page1)
        self.assertNotIn("功能域3", page1)
        self.assertIn("条目还没列完", page1)
        self.assertNotIn("请用 query 检索", page1)
        later = ""
        for page in range(2, 18):
            later = read_tender_text(self.workdir, section="tech", page=page)
            if "功能域17" in later:
                break
        self.assertIn("功能域17", later)

    def test_missing_original_is_loaded_for_the_workspace(self) -> None:
        from unittest.mock import patch

        from app.engines.writer_tool_runtime import read_tender_text

        with patch(
            "app.engines.writer_tool_runtime.load_original_tender_text",
            return_value="招标正文。应提供全天候热线。",
        ):
            text = read_tender_text(self.workdir, project_id="proj-1", section="original")
        self.assertIn("全天候热线", text)
        self.assertNotIn("尚未提供招标书原文", text)

    def test_read_tender_numbers_items_and_hits_keep_their_ids(self) -> None:
        from app.engines.writer_tool_runtime import materialize_tender_extracts, read_tender_text

        materialize_tender_extracts(
            self.workdir,
            {
                "tech": "1、招标范围：覆盖全部分厂\n2、提醒与消息：须提前三天提醒\n3、本地化部署：支持500并发",
                "business": "1、投标函：按格式填写\n2、实施方案：分三阶段",
                "format": "",
            },
        )
        listed = read_tender_text(self.workdir, section="tech")
        self.assertIn("【T1】1、招标范围", listed)
        self.assertIn("【T3】3、本地化部署", listed)
        hit = read_tender_text(self.workdir, section="tech", query="三天")
        self.assertIn("【T2】", hit)
        self.assertNotIn("【T3】", hit)
        business = read_tender_text(self.workdir, section="business", query="实施")
        self.assertIn("【B2】", business)

    def test_source_ref_lines_and_ids_round_trip(self) -> None:
        from app.engines.writer_tool_runtime import outline_cited_ids, parse_source_refs, requirement_item_map

        self.assertEqual(parse_source_refs("依据：T5"), ["T5"])
        self.assertEqual(parse_source_refs("- 依据: T5, b2，T7"), ["T5", "B2", "T7"])
        self.assertEqual(parse_source_refs("依据：T3-T5"), ["T3", "T4", "T5"])
        self.assertIsNone(parse_source_refs("## 依据说明"))
        self.assertEqual(outline_cited_ids("# 技术\n依据：T1\n## 部署\n依据：T2,B1\n"), {"T1", "T2", "B1"})
        mapping = requirement_item_map({"tech": "1、甲\n2、乙", "business": "1、丙"})
        self.assertEqual(mapping, {"T1": "1、甲", "T2": "2、乙", "B1": "1、丙"})

    def test_hard_facts_are_extracted_and_checked_with_numeral_variants(self) -> None:
        from app.engines.writer_tool_runtime import extract_hard_facts, missing_hard_facts

        text = "支持500并发，响应时间不超过2秒，可用性不低于99.9%，计划课程须提前三天提醒，保留一个接口。"
        facts = extract_hard_facts(text)
        self.assertIn("500并发", facts)
        self.assertIn("不低于99.9%", facts)
        self.assertIn("三天", facts)
        self.assertFalse(any(item.startswith("一") for item in facts))
        plus = extract_hard_facts("5500+注册学员，100+管理员，800+课程")
        self.assertEqual(plus, ["5500+", "100+", "800+"])
        self.assertEqual(missing_hard_facts(plus, "支持5500名以上学员、不少于100名管理员、800门课程"), [])
        self.assertEqual(missing_hard_facts(plus, "支持5000名学员"), ["5500+", "100+", "800+"])
        body = "系统按 500 个并发用户设计，响应时间控制在2 秒内，可用性达到99.9%，提前3天推送提醒。"
        self.assertEqual(missing_hard_facts(facts, body), [])
        gap = missing_hard_facts(facts, "系统支持高并发，响应很快。")
        self.assertIn("500并发", gap)
        self.assertIn("不低于99.9%", gap)

    def test_chapter_coverage_requires_facts_and_real_content(self) -> None:
        from app.engines.writer_harness import _coverage_problems, _min_solution_chars

        obligations = [{"title": "提醒策略"}]
        problems = _coverage_problems(
            obligations, "提醒策略：支持灵活配置。", [], False, ["三天", "5次"], _min_solution_chars("条款" * 100)
        )
        joined = "；".join(problems)
        self.assertIn("「三天」", joined)
        self.assertIn("「5次」", joined)
        self.assertIn("不足以逐条应答", joined)
        ok = "提醒策略" + "：系统支持提前3天提醒，每日最多推送5次，并保留触达记录。" * 20
        self.assertEqual(_coverage_problems(obligations, ok, [], False, ["三天", "5次"], 100), [])

    def test_lint_outline_script_runs(self) -> None:
        from pathlib import Path

        from app.engines.writer_tool_runtime import run_skill_script

        markdown = Path(self.workdir) / "outline.md"
        markdown.write_text("# 支持全天候提供咨询服务。\n", encoding="utf-8")
        output = run_skill_script(self.workdir, "bid-outline", "lint_outline.py", ["outline.md"])
        self.assertIn("支持全天候", output)
        self.assertIn("false", output)

    def test_coverage_script_runs(self) -> None:
        import json
        from pathlib import Path

        from app.engines.writer_tool_runtime import run_skill_script

        Path(self.workdir, "obligations.json").write_text(
            json.dumps({"obligations": [{"title": "全天候热线"}], "product_names": [], "require_gap": False}),
            encoding="utf-8",
        )
        Path(self.workdir, "chapter.md").write_text("本章说明服务方式。", encoding="utf-8")
        output = run_skill_script(self.workdir, "bid-chapter", "check_coverage.py")
        self.assertIn("全天候热线", output)

    def test_export_builds_docx_bytes(self) -> None:
        from app.engines.writer_export import chapters_to_docx

        data = chapters_to_docx(
            "示范项目",
            [{"id": "c1", "title": "实施方案", "num": "一、", "part": "tech"}],
            {"c1": "## 全天候热线\n由客服承接。"},
        )
        self.assertTrue(data.startswith(b"PK"))
        self.assertGreater(len(data), 200)

    def test_collect_material_mocks_browser_and_blocks_host(self) -> None:
        from unittest import mock

        from app.engines.writer_tool_runtime import collect_material, host_allowed

        self.assertTrue(host_allowed("https://www.gov.cn/zhengce", ["gov.cn"]))
        self.assertFalse(host_allowed("https://evil.example/x", ["gov.cn"]))
        with mock.patch(
            "app.engines.writer_tool_runtime.browser_settings",
            return_value=("http://writer-browser:8010", 5.0, ["gov.cn"]),
        ):
            blocked = collect_material(self.workdir, "fetch", url="https://evil.example/x")
        self.assertIn("白名单", blocked)

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"text": "政府采购法第三条", "source": "https://www.gov.cn/a"}

        with mock.patch(
            "app.engines.writer_tool_runtime.browser_settings",
            return_value=("http://writer-browser:8010", 5.0, ["gov.cn"]),
        ), mock.patch("httpx.post", return_value=_Resp()):
            saved = collect_material(self.workdir, "fetch", url="https://www.gov.cn/a")
        self.assertIn("已保存", saved)
        listed = collect_material(self.workdir, "list")
        self.assertIn(".txt", listed)

    def test_browser_disabled_without_url(self) -> None:
        from unittest import mock

        from app.engines.writer_tool_runtime import collect_material

        with mock.patch(
            "app.engines.writer_tool_runtime.browser_settings",
            return_value=("", 5.0, ["gov.cn"]),
        ):
            text = collect_material(self.workdir, "search", query="政府采购")
        self.assertIn("浏览器未启用", text)


class BidRequirementMergeTest(unittest.TestCase):
    def test_merge_drops_duplicate_lines_and_keeps_both_sides(self) -> None:
        from app.engines.bid_requirements import _merge

        merged = _merge(["功能登录\n功能登录", "验收标准"])
        self.assertEqual(merged, "功能登录\n验收标准")


class WaterChatGateTest(unittest.TestCase):
    def test_replace_chapter_blocks_water_and_lets_building_through(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        from app.engines.writer_harness import DraftBinding, HarnessError

        class Db:
            def __init__(self, project):
                self.project = project

            def get(self, _model, _id):
                return self.project

            def commit(self):
                return None

            def close(self):
                return None

        def flag(_obj, _name):
            return None

        outline = [{"id": "c1", "title": "工程概况", "parentId": None, "part": "tech", "engKind": "pairs"}]
        water_draft = SimpleNamespace(
            project_id="p",
            doc_kind="tech",
            settings_json={"engFacts": {"structures": [{"name": "新建泵站", "count": "2", "spec": ""}]}},
            outline_json=outline,
            chapter_contents_json={},
        )
        binding = DraftBinding("u", "d", "c1")
        with mock.patch.object(DraftBinding, "_open", return_value=(Db(SimpleNamespace(category="工程类", specialty="水利")), water_draft, flag)):
            with mock.patch("app.engines.engineering_check.check_inputs", return_value={}):
                with self.assertRaises(HarnessError) as caught:
                    binding.replace_chapter("c1", "新建泵站 3 座。")
        self.assertIn("3 座", str(caught.exception))

        house = SimpleNamespace(
            project_id="p",
            doc_kind="tech",
            settings_json={},
            outline_json=list(outline),
            chapter_contents_json={},
        )
        with mock.patch.object(DraftBinding, "_open", return_value=(Db(SimpleNamespace(category="工程类", specialty="房建")), house, flag)):
            self.assertIn("已更新", binding.replace_chapter("c1", "新建泵站 3 座。"))
        self.assertIn("3 座", house.chapter_contents_json["c1"])
