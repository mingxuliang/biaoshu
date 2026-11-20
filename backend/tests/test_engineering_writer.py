"""工程类技术标（施工组织设计）：事实抽取、目录骨架、表格正文、导出样式。不调用外部模型。"""

from __future__ import annotations

import io
import unittest
from unittest import mock

LONG_SCORE = "工程重点难点及危大工程的保障体系与对应措施（包括但不限于智慧工地安全管理系统、绿色施工过程监控等）"

FACTS = {
    "projectName": "滨湖新区环卫基地工程",
    "duration": "540日历天",
    "quality": "合格",
    "smartSite": "三星级智慧工地",
    "greenBuilding": "绿色建筑二星级",
    "scoreItems": [
        {"title": LONG_SCORE, "weight": "10", "points": "重难点分析透彻"},
        {"title": "确保工期与质量的保障体系与措施", "weight": "8"},
        {"title": "确保人、材、机的保障体系与措施", "weight": "6"},
    ],
    "difficulties": [
        {"title": "深基坑支护与降水", "text": "基坑开挖深度 6.5m，地下水位高"},
        {"title": "大跨度钢结构吊装", "text": "主车间钢结构跨度 36m"},
    ],
    "extraDifficulties": [{"title": "多专业交叉施工协调", "text": ""}],
    "hazards": [{"name": "深基坑工程", "text": "开挖深度超过 5m"}],
}


def _children(nodes: list[dict], parent_id: str | None) -> list[dict]:
    return [n for n in nodes if n["parentId"] == parent_id]


def _find(nodes: list[dict], title: str) -> dict:
    return next(n for n in nodes if n["title"] == title)


class EngineeringOutlineTest(unittest.TestCase):
    def test_skeleton_follows_construction_design_template(self) -> None:
        from app.engines.engineering_writer import generate_outline

        report: dict = {}
        nodes = generate_outline(FACTS, report)
        top = _children(nodes, None)

        self.assertEqual(top[0]["title"], "编制说明")
        self.assertEqual([n["title"] for n in _children(nodes, top[0]["id"])], ["编制依据", "编制原则"])
        self.assertEqual([n["title"] for n in top[1:4]], [s["title"] for s in FACTS["scoreItems"]])
        self.assertEqual(top[1]["title"], LONG_SCORE, "评分项原文不能被截短")
        self.assertEqual(top[-1]["title"], "附件")
        self.assertEqual(len(_children(nodes, top[-1]["id"])), 7)
        self.assertTrue(all(n["part"] == "tech" and n.get("engKind") for n in nodes))
        self.assertEqual(report["difficulties"], 2)
        self.assertTrue(report["engineering"])

    def test_each_difficulty_has_analysis_and_measures(self) -> None:
        from app.engines.engineering_writer import SOURCE_EXTRA, SOURCE_TENDER, generate_outline

        nodes = generate_outline(FACTS)
        group = _find(nodes, "工程重点、难点及对应保障措施")
        diffs = _children(nodes, group["id"])
        titles = [d["title"] for d in diffs]
        for name in ("深基坑支护与降水", "大跨度钢结构吊装", "多专业交叉施工协调"):
            self.assertIn(name, titles)
        for d in diffs:
            self.assertEqual([c["title"] for c in _children(nodes, d["id"])], ["重难点分析", "重难点解决措施"])
            self.assertTrue(all(c["engKind"] == "box" for c in _children(nodes, d["id"])))
        self.assertEqual(_find(nodes, "深基坑支护与降水")["engSource"], SOURCE_TENDER)
        self.assertEqual(_find(nodes, "多专业交叉施工协调")["engSource"], SOURCE_EXTRA)

    def test_hazards_and_named_items_get_their_own_sections(self) -> None:
        from app.engines.engineering_writer import generate_outline

        titles = [n["title"] for n in generate_outline(FACTS)]
        self.assertIn("危大工程清单", titles)
        self.assertIn("危大工程保证措施", titles)
        self.assertTrue(any(t.startswith("智慧工地安全管理系统") for t in titles))
        self.assertIn("绿色施工过程监控（绿色建筑二星级）", titles)
        self.assertIn("确保人、材、机的保障体系", titles)

    def test_named_items_precede_data_tables_and_score_suffix_is_dropped(self) -> None:
        from app.engines.engineering_writer import generate_outline

        title = "确保安全文明生产的管理体系与措施（包括但不限于临近周边住宅区文明施工保障措施）"
        facts = {**FACTS, "scoreItems": [{"title": f"{title}（6分）"}, {"title": "项目质量管理（4分）", "sections": ["质量目标", "质量检查"]}]}
        nodes = generate_outline(facts)
        top = _children(nodes, None)
        self.assertEqual(top[1]["title"], title)
        kids = [n["title"] for n in _children(nodes, top[1]["id"])]
        named = kids.index("临近周边住宅区文明施工保障措施")
        smart = next(i for i, t in enumerate(kids) if t.startswith("智慧工地"))
        self.assertLess(named, smart)
        quality = [n["title"] for n in _children(nodes, top[2]["id"])]
        self.assertEqual(top[2]["title"], "项目质量管理")
        self.assertIn("质量检查", quality)

    def test_named_item_in_difficulty_chapter_becomes_first_difficulty(self) -> None:
        from app.engines.engineering_writer import SOURCE_TENDER, generate_outline

        title = "工程重点难点及危大工程的保障体系（包括但不限于周边无市政道路临时配套保障措施）"
        facts = {**FACTS, "scoreItems": [{"title": title}], "extraDifficulties": [{"title": "无市政道路临时配套", "text": "周边道路未建成"}]}
        nodes = generate_outline(facts)
        group = _find(nodes, "工程重点、难点及对应保障措施")
        diffs = _children(nodes, group["id"])
        self.assertEqual(diffs[0]["title"], "周边无市政道路临时配套保障措施")
        self.assertEqual(diffs[0]["engSource"], SOURCE_TENDER)
        self.assertEqual(diffs[0]["requirement"], "周边道路未建成")
        self.assertNotIn("无市政道路临时配套", [d["title"] for d in diffs])
        chapter = _children(nodes, None)[1]
        self.assertNotIn("周边无市政道路临时配套保障措施", [n["title"] for n in _children(nodes, chapter["id"])])

    def test_default_skeleton_without_score_items(self) -> None:
        from app.engines.engineering_writer import DEFAULT_SCORE_ITEMS, generate_outline

        report: dict = {}
        nodes = generate_outline({"difficulties": []}, report)
        top = [n["title"] for n in _children(nodes, None)]
        self.assertEqual(top[1:-1], list(DEFAULT_SCORE_ITEMS))
        self.assertTrue(report["defaultSkeleton"])


class EngineeringFactsTest(unittest.TestCase):
    def test_heuristic_difficulties_from_technical_requirements(self) -> None:
        from app.engines.engineering_writer import _heuristic_difficulties

        text = (
            "评分标准：工程重点难点分析 10 分。\n"
            "本工程重点难点：1. 深基坑支护与降水施工，基坑深度 6.5m。2. 大跨度钢结构吊装。"
            "3. 场地狭小，材料堆放困难。\n第八章 投标文件格式"
        )
        items = _heuristic_difficulties(text)
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0]["title"].startswith("深基坑支护与降水"))

    def test_model_failure_falls_back_to_rules(self) -> None:
        from app.engines import engineering_writer
        from app.engines.llm import LlmError

        tender = "计划工期：540日历天。质量要求：合格。本工程重点难点：1. 深基坑支护。2. 钢结构吊装。"
        with mock.patch.object(engineering_writer, "chat_complete", side_effect=LlmError("down")):
            facts = engineering_writer.extract_facts(tender, None, project_name="示范工程")
        self.assertIn("540", facts["duration"])
        self.assertEqual(len(facts["difficulties"]), 2)

    def test_normalize_keeps_shape(self) -> None:
        from app.engines.engineering_writer import normalize_facts

        f = normalize_facts({"difficulties": ["深基坑支护"], "pageLimit": "80", "scoreItems": [{"title": "A", "sections": ["x", ""]}]})
        self.assertEqual(f["difficulties"][0]["title"], "深基坑支护")
        self.assertEqual(f["pageLimit"], 80)
        self.assertEqual(f["scoreItems"][0]["sections"], ["x"])

    def test_facts_brief_includes_construction_understanding(self) -> None:
        from app.engines.engineering_writer import facts_brief, normalize_facts

        facts = normalize_facts(
            {
                "buildings": [{"name": "1#生活垃圾转运站", "scale": "14773㎡", "structure": "框架"}],
                "trades": ["土建", "市政道排", "机电设备安装"],
                "stages": [{"name": "地下结构期", "work": "地下室结构"}],
                "siteConstraints": [{"title": "周边无市政道路", "text": "需自建便道和临时水电"}],
                "processSystems": [{"name": "渗滤液处理", "text": "负一层管线密集"}],
            }
        )
        brief = facts_brief(facts)
        self.assertIn("1#生活垃圾转运站", brief)
        self.assertIn("机电设备安装", brief)
        self.assertIn("地下结构期", brief)
        self.assertIn("周边无市政道路", brief)
        self.assertIn("渗滤液处理", brief)

    def test_settings_save_does_not_overwrite_server_facts(self) -> None:
        from app.writer_tracks import merge_settings

        merged = merge_settings({"engFacts": {"duration": "540日历天"}}, {"layout": {}, "engFacts": {"duration": "旧"}})
        self.assertEqual(merged["engFacts"]["duration"], "540日历天")


class EngineeringBodyTest(unittest.TestCase):
    def test_section_kind_and_grid_columns(self) -> None:
        from app.engines.engineering_writer import grid_columns, section_kind

        self.assertEqual(section_kind({"title": "重难点分析"}), "box")
        self.assertEqual(section_kind({"title": "施工总平面图"}), "figure")
        self.assertEqual(section_kind({"title": "危大工程清单"}), "grid")
        self.assertEqual(section_kind({"title": "质量保证措施"}), "pairs")
        self.assertEqual(grid_columns("附表一：拟投入本标段的主要施工设备表")[1], "设备名称")

    def test_loose_text_is_wrapped_into_box_tables(self) -> None:
        from app.engines.engineering_writer import box_table, normalize_table_markdown

        self.assertEqual(box_table("第一行\n第二|行"), "| 第一行<br>第二／行 |\n| --- |")
        out = normalize_table_markdown("```markdown\n## 小标题\n说明文字\n\n| 项目 | 具体内容 |\n| 目标 | 合格 |\n```")
        blocks = out.split("\n\n")
        self.assertEqual(blocks[0], "| 小标题<br>说明文字 |\n| --- |")
        self.assertEqual(blocks[1].split("\n")[1], "| --- | --- |")
        self.assertTrue(all(line.startswith("|") for line in out.splitlines() if line))

    def test_write_chapter_uses_facts_and_tender_only(self) -> None:
        from app.engines import engineering_writer
        from app.engines.engineering_writer import generate_outline

        outline = generate_outline(FACTS)
        node = next(n for n in outline if n["title"] == "重难点解决措施")
        calls: list[list[dict]] = []

        def fake_chat(**kwargs):
            calls.append(kwargs["messages"])
            return "| 项目 | 具体内容 |\n| --- | --- |\n| 降水 | 管井降水 |"

        with mock.patch.object(engineering_writer, "chat_complete", side_effect=fake_chat), mock.patch.object(
            engineering_writer, "project_tender_text", return_value="基坑开挖深度 6.5m，地下水位高，需设置降水井。"
        ):
            content = engineering_writer.write_chapter(node, outline, FACTS, model_id=None, project_id="p1")

        self.assertEqual(len(calls), 1)
        prompt = calls[0][1]["content"]
        self.assertIn("540日历天", prompt)
        self.assertIn("深基坑支护与降水", prompt)
        self.assertIn("降水井", prompt)
        self.assertIn("（1）（2）（3）（4）", prompt)
        self.assertIn("短措施名", prompt)
        self.assertNotIn("知识库资料", prompt)
        analysis = next(n for n in outline if n["title"] == "重难点分析" and n.get("parentId") == node.get("parentId"))
        analysis_prompt = engineering_writer.build_chapter_prompt(analysis, outline, FACTS)
        self.assertIn("只写一段", analysis_prompt)
        self.assertIn("不要写措施", analysis_prompt)
        self.assertTrue(content.startswith("| 项目 | 具体内容 |"))


class EngineeringTaskWiringTest(unittest.TestCase):
    """目录任务的工程分支：内存 sqlite，模型调用打桩。"""

    @classmethod
    def setUpClass(cls) -> None:
        import os
        import tempfile

        os.environ.setdefault("WRITER_WORKSPACE_ROOT", tempfile.mkdtemp())
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base

        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        from app.models import Project, WriterDraft, WriterJob

        self.db = self.Session()
        self.project = Project(code="P1", name="示范工程", type="工程", category="工程类")
        self.db.add(self.project)
        self.db.flush()
        self.draft = WriterDraft(
            project_id=self.project.id,
            doc_kind="tech",
            settings_json={"ledger": [1], "layout": {"bodyFont": "宋体"}},
            knowledge_refs_json={"x": [{"docId": "d"}]},
            chapter_contents_json={"x": "旧正文"},
        )
        self.db.add(self.draft)
        self.db.flush()
        self.job = WriterJob(draft_id=self.draft.id, kind="outline", status="running")
        self.db.add(self.job)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def test_outline_task_builds_engineering_outline_and_clears_knowledge(self) -> None:
        from app import tasks

        with mock.patch.object(tasks.engineering_writer, "extract_facts", return_value=FACTS) as extract:
            tasks._generate_engineering_outline(self.db, self.draft, self.job, "示范工程", [], "招标原文", "", dict(self.draft.settings_json))
        self.db.refresh(self.draft)
        extract.assert_called_once()
        self.assertTrue(tasks._is_engineering_draft(self.db, self.draft))
        self.assertEqual(self.draft.outline_json[0]["title"], "编制说明")
        self.assertEqual(self.draft.knowledge_refs_json, {})
        self.assertEqual(self.draft.chapter_contents_json, {})
        self.assertNotIn("ledger", self.draft.settings_json)
        self.assertEqual(self.draft.settings_json["layout"], {"bodyFont": "宋体"})
        self.assertEqual(self.draft.settings_json["engFacts"]["duration"], "540日历天")
        self.assertEqual(self.job.status, "done")
        self.assertTrue(self.job.result_json["coverage"]["engineering"])

    def test_edited_facts_are_reused_without_model(self) -> None:
        from app import tasks

        settings = {"engFacts": {**FACTS, "duration": "600日历天", "edited": True}}
        with mock.patch.object(tasks.engineering_writer, "extract_facts") as extract:
            tasks._generate_engineering_outline(self.db, self.draft, self.job, "示范工程", [], "", "", settings)
        extract.assert_not_called()
        self.db.refresh(self.draft)
        self.assertEqual(self.draft.settings_json["engFacts"]["duration"], "600日历天")
        self.assertTrue(self.draft.settings_json["engFacts"]["edited"])

    def test_plan_ledger_is_built_once_until_facts_change(self) -> None:
        from app import tasks

        built = {"stages": [{"name": "准备", "start": "第1天", "end": "第15天", "work": ""}], "machines": [], "labor": [], "materials": []}
        with mock.patch.object(tasks.engineering_writer, "boq_rows_for", return_value=[]), mock.patch.object(
            tasks.engineering_writer, "build_plan", return_value=built
        ) as build:
            first = tasks._engineering_plan(self.db, self.draft, FACTS)
            self.db.refresh(self.draft)
            again = tasks._engineering_plan(self.db, self.draft, FACTS)
            self.db.refresh(self.draft)
            changed = tasks._engineering_plan(self.db, self.draft, {**FACTS, "duration": "600日历天"})
        self.assertEqual(build.call_count, 2)
        self.assertEqual(first["sig"], again["sig"])
        self.assertNotEqual(first["sig"], changed["sig"])
        self.db.refresh(self.draft)
        self.assertEqual(self.draft.settings_json["engPlan"]["sig"], changed["sig"])

    def test_outline_task_is_still_the_registered_celery_task(self) -> None:
        from app import tasks

        self.assertTrue(hasattr(tasks.run_outline_generate_task, "delay"))
        self.assertFalse(hasattr(tasks._generate_engineering_outline, "delay"))

    def test_software_project_is_not_engineering(self) -> None:
        from app import tasks

        self.project.category = "软件服务类"
        self.db.commit()
        self.assertFalse(tasks._is_engineering_draft(self.db, self.draft))
        self.draft.doc_kind = "business"
        self.project.category = "工程类"
        self.db.commit()
        self.assertFalse(tasks._is_engineering_draft(self.db, self.draft))


class WaterEngineeringTest(unittest.TestCase):
    TENDER = (
        "综合治理河长约 8.85km。竹园稞约 3.02km。刁林岩约 4.12km。"
        "计划工期：365日历天。度汛导流应在汛前完成。"
        "羊角堰应于2027年4月30日前具备过水条件。依据 SL/T 223-2025。"
    )

    def test_water_heuristic_ledger_and_non_water_stays_empty(self) -> None:
        from app.engines import engineering_writer
        from app.engines.llm import LlmError

        with mock.patch.object(engineering_writer, "chat_complete", side_effect=LlmError("down")):
            water = engineering_writer.extract_facts(self.TENDER, None, project_name="黑河治理", specialty="水利")
            house = engineering_writer.extract_facts(self.TENDER, None, project_name="房建", specialty="房建")
        self.assertEqual(water["regionTotalLength"], "8.85km")
        self.assertGreaterEqual(len(water["regions"]), 1)
        self.assertTrue(water["floodSeason"]["spansFlood"])
        self.assertIn("SL/T223-2025", water["standardsRefs"])
        self.assertTrue(any("羊角堰" in node["name"] for node in water["controlNodes"]))
        self.assertEqual(house["regions"], [])
        self.assertEqual(house["standardsRefs"], [])
        self.assertFalse(house["floodSeason"]["spansFlood"])

    def test_water_outline_adds_flood_chapter_and_skips_building_nodes(self) -> None:
        from app.engines.engineering_writer import generate_outline

        facts = {
            **FACTS,
            "scope": "护坡护岸、河道清淤、防汛道路、堰坝拆建",
            "regions": [{"name": "竹园稞", "length": "3.02km", "mainQuantities": "土方开挖 73585.5m³"}],
            "controlNodes": [{"name": "羊角堰", "window": "第46天至第65天", "note": "埋石率20%"}],
            "floodSeason": {"spansFlood": True, "diversionMethod": "分段分期导流", "stopWorkRule": "日降雨超过100mm停工"},
            "smartSite": "BIM",
            "greenBuilding": "二星",
        }
        nodes = generate_outline(facts, specialty="水利")
        titles = [n["title"] for n in nodes]
        self.assertIn("度汛、导流与冬雨季施工", titles)
        self.assertIn("分段分期导流", titles)
        self.assertIn("汛期应急预案", titles)
        self.assertIn("冬雨季施工参数", titles)
        self.assertIn("竹园稞施工部署", titles)
        self.assertIn("河道清淤施工方法", titles)
        self.assertNotIn("主要建（构）筑物概况", titles)
        self.assertFalse(any("绿色建筑" in title for title in titles))
        labor = next(n for n in nodes if n["title"] == "劳动力的保障措施")
        self.assertIn("增至", labor["idea"])

    def test_water_prompt_copies_ledger_and_forbids_symbols(self) -> None:
        from app.engines.engineering_writer import build_chapter_prompt

        facts = {
            "controlNodes": [{"name": "羊角堰", "window": "第46天至第65天", "note": ""}],
            "standardsRefs": ["SL/T 223-2025"],
            "floodSeason": {"spansFlood": True, "diversionMethod": "分段分期", "stopWorkRule": ""},
        }
        node = {"id": "n1", "title": "分段分期导流", "parentId": None, "idea": "按节点倒排", "engKind": "pairs"}
        prompt = build_chapter_prompt(node, [node], facts, specialty="水利")
        self.assertIn("不小于", prompt)
        self.assertIn("羊角堰", prompt)
        self.assertIn("第46天至第65天", prompt)
        self.assertIn("SL/T 223-2025", prompt)
        self.assertIn("暂无可引用规范", prompt)

    def test_figure_hint_asks_for_a_text_digest(self) -> None:
        from app.engines.engineering_writer import format_hint

        hint = format_hint({"title": "施工进度网络图", "engKind": "figure"}, "水利")
        self.assertIn("200～300", hint)

    def test_dike_style_length_and_structures_without_invented_grade(self) -> None:
        from app.engines import engineering_writer
        from app.engines.llm import LlmError

        text = (
            "无为永安河堤防治理总长 3.149km（左堤 2.919km＋窑头子埂 0.23km）。"
            "新建泵站 2 座，涵 3 座，总装机 140kW。工程等别：Ⅳ等。建筑物级别：4级。设计洪水 20年一遇。"
            "渠道衬砌与灌区渠系同期实施。"
        )
        with mock.patch.object(engineering_writer, "chat_complete", side_effect=LlmError("down")):
            facts = engineering_writer.extract_facts(text, None, project_name="永安河", specialty="水利")
        self.assertEqual(facts["regionTotalLength"], "3.149km")
        names = {row["name"] for row in facts["regions"]}
        self.assertIn("左堤", names)
        self.assertTrue(any("窑头子埂" in name for name in names))
        pumps = next(row for row in facts["structures"] if "泵站" in row["name"])
        self.assertEqual(pumps["count"], "2")
        self.assertTrue(any(row["name"] == "总装机" and "140" in row["spec"] for row in facts["structures"]))
        self.assertEqual(facts["projectGrade"]["projectLevel"], "Ⅳ等")
        self.assertEqual(facts["projectGrade"]["floodStandard"], "20年一遇")
        self.assertEqual(facts["siteSurvey"]["boundaries"], "")

    def test_subtype_outline_adds_survey_flood_and_two_part_difficulty(self) -> None:
        from app.engines.engineering_writer import generate_outline

        facts = {
            **FACTS,
            "projectName": "永安河堤防",
            "scope": "堤防填筑、水泥土搅拌桩、防洪墙、弃土外运",
            "smartSite": "BIM 巡检",
            "floodSeason": {"spansFlood": True, "diversionMethod": "", "stopWorkRule": ""},
        }
        report: dict = {}
        nodes = generate_outline(facts, report, specialty="水利")
        titles = [n["title"] for n in nodes]
        self.assertIn("堤防防洪", report["subtypes"])
        self.assertIn("现场勘察与外部条件", titles)
        self.assertIn("度汛标准与依据", titles)
        self.assertIn("围堰施工与拆除", titles)
        self.assertIn("基坑排水与降水", titles)
        self.assertIn("堤身填筑施工方法", titles)
        self.assertIn("水泥土搅拌桩施工方法", titles)
        self.assertIn("土方平衡与调配", titles)
        self.assertIn("质量验收与评定", titles)
        self.assertIn("工程观测与监测", titles)
        self.assertIn("水土保持与环境保护措施", titles)
        self.assertIn("智慧工地管理机制", titles)
        self.assertIn("重难点分析", titles)
        self.assertIn("重难点解决措施", titles)
        self.assertIn("保证措施汇总", titles)
        self.assertNotIn("难点是什么", titles)
        self.assertNotIn("为什么难", titles)
        self.assertNotIn("怎么办", titles)
        analysis = next(n for n in nodes if n["title"] == "重难点分析")
        kids = [c["title"] for c in nodes if c.get("parentId") == analysis.get("parentId")]
        self.assertEqual(kids, ["重难点分析", "重难点解决措施", "保证措施汇总"])
        flood = next(n for n in nodes if n["title"] == "汛期应急预案")
        self.assertNotIn("100mm", flood["idea"])
        self.assertIn("待核实", flood["idea"])
        self.assertGreaterEqual(len(report["siteGaps"]), 3)

    def test_farmland_subtype_uses_well_and_irrigation_difficulties(self) -> None:
        from app.data.water_craft import craft_difficulties, craft_works, detect_subtypes

        blob = "高标准农田 1.35 万亩，地力培肥，新建农用井 180 眼，沟渠疏浚 80.13km，田间道路 12.7km"
        keys = detect_subtypes(blob)
        self.assertIn("farmland", keys)
        titles = [item["title"] for item in craft_works(keys, blob)]
        self.assertTrue(any("农用井" in t for t in titles))
        self.assertTrue(any("沟渠疏浚" in t for t in titles))
        diffs = [item["title"] for item in craft_difficulties(keys, blob)]
        self.assertTrue(any("灌溉" in t or "成井" in t for t in diffs))

    def test_building_outline_keeps_two_part_difficulty(self) -> None:
        from app.engines.engineering_writer import generate_outline

        titles = [n["title"] for n in generate_outline(FACTS, specialty="房建")]
        self.assertIn("重难点分析", titles)
        self.assertNotIn("度汛标准与依据", titles)
        self.assertNotIn("现场勘察与外部条件", titles)


class WaterCheckTest(unittest.TestCase):
    def test_five_checks_split_blocking_and_advisory(self) -> None:
        from app.engines.engineering_check import blocking_message, water_check

        facts = {
            "regionTotalLength": "8.85km",
            "regions": [
                {"name": "甲段", "length": "3.02km"},
                {"name": "乙段", "length": "4.00km"},
            ],
            "controlNodes": [{"name": "羊角堰", "window": "第46天至第65天", "note": "埋石率20%"}],
            "standardsRefs": ["SL/T 223-2025"],
        }
        outline = [
            {"id": "a", "title": "河道清淤施工方法", "parentId": None, "engKind": "pairs"},
            {"id": "b", "title": "劳动力计划表", "parentId": None, "engKind": "grid"},
            {"id": "c", "title": "施工进度网络图", "parentId": None, "engKind": "figure"},
        ]
        contents = {
            "a": "采用挖掘机清淤，不小于 0.5m。",
            "b": "普工 90 人。",
            "c": "| 图表名称 | 说明 |\n| --- | --- |\n| 网络图 | 请插入图 |",
            "d": "羊角堰第80天拆除。",
        }
        outline.append({"id": "d", "title": "进度", "parentId": None, "engKind": "pairs"})
        result = water_check(facts, outline, contents)
        self.assertFalse(result["ok"])
        blocking = " ".join(item["message"] for item in result["blocking"])
        advisory = " ".join(item["message"] for item in result["advisory"])
        self.assertIn("对不上", blocking)
        self.assertIn("80", blocking)
        self.assertIn("不足 200", blocking)
        self.assertIn("规范编号", advisory)
        self.assertIn("两档", advisory)
        self.assertIn("强制导出", blocking_message(result))

    def test_matching_ledger_passes(self) -> None:
        from app.engines.engineering_check import water_check

        facts = {
            "regionTotalLength": "8.85km",
            "regions": [{"name": "甲段", "length": "3.02km"}, {"name": "乙段", "length": "5.83km"}],
            "controlNodes": [{"name": "羊角堰", "window": "第46天至第65天", "note": ""}],
            "standardsRefs": ["SL/T 223-2025"],
        }
        outline = [
            {"id": "a", "title": "河道清淤施工方法", "parentId": None, "engKind": "pairs"},
            {"id": "b", "title": "劳动力的保障措施", "parentId": None, "engKind": "pairs"},
            {"id": "c", "title": "施工总平面图", "parentId": None, "engKind": "figure"},
        ]
        digest = "关键线路为刁林岩至阳冲村河段治理及羊角堰拆建，总时差为零。布置原则是沿河一侧设置施工便道，加工场远离堤防。汛前完成围堰，人数和机械按节点进场。" * 4
        contents = {
            "a": "干地开挖分层厚度不大于 2m，执行 SL/T 223-2025。",
            "b": "普工由 65 人增至 90 人。",
            "c": f"| 图表名称 | 说明 |\n| --- | --- |\n| 总平面 | {digest} |",
            "d": "羊角堰拆除安排在第46天。",
        }
        outline.append({"id": "d", "title": "进度", "parentId": None, "engKind": "pairs"})
        result = water_check(facts, outline, contents)
        self.assertEqual(result["blocking"], [])
        self.assertTrue(result["ok"])

    def test_counts_coordinates_codes_and_coverage(self) -> None:
        from types import SimpleNamespace

        from app.engines.engineering_check import coverage_rules, water_check
        from app.engines.water_design import design_ledger, design_lines_for

        facts = {
            "structures": [{"name": "新建泵站", "count": "2", "spec": ""}, {"name": "总装机", "count": "", "spec": "140kW"}],
            "projectGrade": {"floodStandard": "20年一遇"},
            "floodSeason": {"spansFlood": True},
            "siteSurvey": {"boundaries": "东至永安河"},
            "standardsRefs": ["SL 260-2014"],
        }
        outline = [
            {"id": "a", "title": "工程概况", "parentId": None, "engKind": "pairs"},
            {"id": "b", "title": "度汛标准与依据", "parentId": None, "engKind": "pairs"},
            {"id": "c", "title": "智慧工地管理机制", "parentId": None, "engKind": "pairs"},
            {"id": "d", "title": "防洪墙施工方法", "parentId": None, "engKind": "pairs"},
        ]
        contents = {
            "a": "新建泵站 3 座，总装机 200kW。现场坐标东经 117.2831。",
            "b": "设计洪水按 10年一遇。",
            "c": "设置视频监控和 BIM 平台。",
            "d": "墙身混凝土 C25，执行 SL 721-2015。",
        }
        checklist = SimpleNamespace(
            drawing_facts=[{"object": "防洪墙", "field": "混凝土", "value": "C30W6F50", "unit": "", "drawingNo": "S-01", "page": "3"}],
            boq_rows=[{"name": "堤身填筑", "feature": "压实度不小于 95%", "qty": "1", "unit": "m3", "code": "0101"}],
            tech_rules=[{"factor": "农民工工资专户", "mustWrite": "开设农民工工资专用账户并按月拨付"}],
            project_rules=[],
        )
        ledger = design_ledger(checklist)
        self.assertTrue(any("C30W6F50" in row["text"] and "S-01" in row["text"] for row in ledger))
        self.assertTrue(design_lines_for(ledger, "防洪墙施工方法", "混凝土浇筑"))
        result = water_check(
            facts,
            outline,
            contents,
            known_codes={"SL260-2014"},
            design=ledger,
            rules=coverage_rules(checklist),
        )
        blocking = " ".join(item["message"] for item in result["blocking"])
        advisory = " ".join(item["message"] for item in result["advisory"])
        self.assertIn("3 座", blocking)
        self.assertIn("200kW", blocking)
        self.assertIn("117.2831", blocking)
        self.assertIn("10 年一遇", blocking)
        self.assertIn("SL 721-2015", advisory)
        self.assertIn("C25", advisory)
        self.assertIn("抗渗", advisory)
        self.assertIn("预警阈值", advisory)
        self.assertIn("农民工工资", advisory)
        self.assertTrue(result["siteGaps"])

    def test_export_block_message_is_empty_when_clean(self) -> None:
        from app.engines.engineering_check import blocking_message

        self.assertEqual(blocking_message({"blocking": []}), "")


class EngineeringExportTest(unittest.TestCase):
    def test_box_and_pair_tables_follow_template_style(self) -> None:
        import docx
        from docx.oxml.ns import qn

        from app.engines.writer_export import chapters_to_docx

        outline = [{"id": "o-1", "num": "一、", "title": "编制说明", "parentId": None, "part": "tech", "engKind": "box"}]
        contents = {
            "o-1": "| （1）招标文件<br>（2）GB 50502-2009 |\n| --- |\n\n"
            "| 项目 | 具体内容 |\n| --- | --- |\n| 质量目标 | 合格 |\n\n"
            "| 序号 | 设备名称 | 数量 |\n| --- | --- | --- |\n| 1 | 挖掘机 | 2 |"
        }
        data = chapters_to_docx("示范工程", outline, contents, engineering=True)
        doc = docx.Document(io.BytesIO(data))
        box, pairs, grid = doc.tables

        def fill(cell) -> str:
            shd = cell._tc.get_or_add_tcPr().find(qn("w:shd"))
            return shd.get(qn("w:fill")) if shd is not None else ""

        self.assertEqual(len(box.columns), 1)
        self.assertEqual(fill(box.cell(0, 0)), "")
        self.assertEqual(len(box.cell(0, 0).paragraphs), 2)
        self.assertTrue(fill(pairs.cell(0, 0)))
        self.assertEqual(fill(pairs.cell(1, 0)), "F2F2F2")
        self.assertEqual(fill(pairs.cell(1, 1)), "")
        self.assertTrue(fill(grid.cell(0, 2)))
        self.assertEqual(fill(grid.cell(1, 1)), "")


class WriterTrackTest(unittest.TestCase):
    def test_track_splits_three_ways(self) -> None:
        from app.engines.engineering_writer import TRACK_ENGINEERING, TRACK_SOFTWARE, TRACK_WATER, apply_detected_specialty, writer_track

        self.assertEqual(writer_track("软件服务类", "", "tech"), TRACK_SOFTWARE)
        self.assertEqual(writer_track("工程类", "房建", "tech"), TRACK_ENGINEERING)
        self.assertEqual(writer_track("工程类", "水利", "tech"), TRACK_WATER)
        self.assertEqual(writer_track("工程类", "水利", "business"), TRACK_ENGINEERING)
        self.assertEqual(apply_detected_specialty("房建", "水利"), "房建")
        self.assertEqual(apply_detected_specialty("", "水利"), "")
        self.assertEqual(apply_detected_specialty("", "市政"), "市政")

    def test_edit_blocks_own_chapter_not_neighbor(self) -> None:
        from app.engines.engineering_check import edit_block_reason

        facts = {"structures": [{"name": "新建泵站", "count": "2", "spec": ""}]}
        outline = [
            {"id": "a", "title": "工程概况", "parentId": None, "engKind": "pairs"},
            {"id": "b", "title": "施工总平面图", "parentId": None, "engKind": "figure"},
        ]
        old = {"b": "请插入图"}
        blocked, _notes = edit_block_reason(facts, outline, old, "a", "新建泵站 3 座。")
        self.assertIn("3 座", blocked)
        allowed, _notes = edit_block_reason(facts, outline, old, "a", "新建泵站 2 座。")
        self.assertEqual(allowed, "")


class AgentOutlineParseTest(unittest.TestCase):
    def test_markdown_keeps_score_titles_and_ideas(self) -> None:
        from app.engines.engineering_writer import outline_from_markdown

        markdown = "\n".join(
            [
                "# 确保工期与质量的保障体系与措施",
                "## 确保工期的保障体系与措施",
                "思路：按 540 日历天写关键节点。",
                "## 确保质量的保障体系与措施",
                "# 附件",
                "## 附表一：拟投入本标段的主要施工设备表",
            ]
        )
        nodes = outline_from_markdown(markdown, FACTS)
        titles = [node["title"] for node in nodes]
        self.assertEqual(titles[0], "确保工期与质量的保障体系与措施")
        self.assertIn("附表一：拟投入本标段的主要施工设备表", titles)
        idea = next(node for node in nodes if node["title"] == "确保工期的保障体系与措施")
        self.assertIn("540", idea["idea"])
        self.assertTrue(all(node.get("engKind") for node in nodes))

    def test_empty_markdown_does_not_invent_a_skeleton(self) -> None:
        from app.engines.engineering_writer import outline_from_markdown

        self.assertEqual(outline_from_markdown("没有标题", FACTS), [])

    def test_outline_problems_only_report_missing_items(self) -> None:
        from app.engines.engineering_writer import outline_from_markdown, outline_problems

        nodes = outline_from_markdown("# 编制说明\n## 编制依据", FACTS)
        problems = outline_problems(nodes, FACTS)
        self.assertTrue(any("深基坑支护" in item for item in problems))
        self.assertTrue(any("确保工期与质量" in item for item in problems))
        self.assertFalse(any("编制说明" in item for item in problems))


BOQ_ROWS = [
    {"code": "1.2.1", "name": "农用井工程（新建180眼，设计井深36m）", "unit": "", "qty": ""},
    {"code": "1.2.1.1", "name": "农用井成孔，井孔直径90cm", "unit": "m", "qty": "6507.00"},
    {"code": "1.2.1.11", "name": "预制C30砼井盖(含模板、运输）", "unit": "个", "qty": "180"},
    {"code": "1.2.2", "name": "疏浚沟渠工程", "unit": "", "qty": ""},
    {"code": "1.2.2.1", "name": "小沟疏浚（共计54.18km）", "unit": "", "qty": ""},
    {"code": "1.2.2.1.1", "name": "小沟土方开挖", "unit": "m3", "qty": "190741.296"},
    {"code": "1.2.2.3.1", "name": "大沟土方开挖", "unit": "m3", "qty": "329509.205", "remark": "运距自行考虑"},
    {"code": "1.3.2.2", "name": "150mm煤矸石基层", "unit": "m2", "qty": "13473.92"},
]


class EngineeringGroundingTest(unittest.TestCase):
    """正文按本节清单、施工计划账和招标原文写，不凑字、不编数。"""

    def _outline(self) -> list[dict]:
        return [
            {"id": "c1", "title": "主要施工方案", "parentId": None},
            {"id": "s1", "title": "沟渠疏浚（80.13km）", "parentId": "c1"},
            {"id": "s1a", "title": "工艺流程", "parentId": "s1"},
            {"id": "s2", "title": "农用井工程（180 眼）", "parentId": "c1"},
            {"id": "c2", "title": "施工进度计划", "parentId": None},
        ]

    def test_boq_lines_follow_section_and_expand_headings(self) -> None:
        from app.engines.engineering_writer import boq_lines_for

        outline = self._outline()
        ditch = boq_lines_for(BOQ_ROWS, outline, outline[2])
        self.assertTrue(any("小沟土方开挖 190741.296m3" in line for line in ditch), ditch)
        self.assertTrue(any("大沟土方开挖" in line and "运距" in line for line in ditch))
        self.assertFalse(any("农用井" in line or "煤矸石" in line for line in ditch))
        well = boq_lines_for(BOQ_ROWS, outline, outline[3])
        self.assertEqual(len(well), 2)
        self.assertIn("6507.00m", well[0])
        self.assertEqual(boq_lines_for(BOQ_ROWS, outline, outline[4]), [])
        self.assertEqual(boq_lines_for([], outline, outline[3]), [])

    def test_prompt_carries_boq_plan_and_length_cap(self) -> None:
        from app.engines.engineering_writer import build_chapter_prompt, plan_brief

        outline = self._outline()
        plan = {
            "stages": [{"name": "沟渠疏浚", "start": "第1天", "end": "第60天", "work": "土方68万m³"}],
            "machines": [{"name": "挖掘机", "spec": "1.0m³", "count": "12", "use": "沟渠土方"}],
            "labor": [{"trade": "普工", "normal": "60", "peak": "120"}],
            "materials": [{"name": "商品有机肥", "qty": "8100", "unit": "吨", "basis": "13500亩×600kg"}],
        }
        brief = plan_brief(plan)
        self.assertIn("挖掘机 1.0m³ 12台", brief)
        self.assertIn("常态60人／高峰120人", brief)
        prompt = build_chapter_prompt(
            outline[2], outline, FACTS, boq_lines=["1.2.2.1.1 小沟土方开挖 190741.296m3"], plan_text=brief
        )
        self.assertIn("【本节清单（工程量照抄", prompt)
        self.assertIn("190741.296", prompt)
        self.assertIn("【施工计划账", prompt)
        self.assertIn("不要为凑字", prompt)
        self.assertIn("无，正文不写规范编号", prompt)
        self.assertEqual(plan_brief({}), "")

    def test_body_system_drops_generic_template(self) -> None:
        from app.engines.engineering_writer import ENG_CHAPTER_SYSTEM, WATER_CHAPTER_SYSTEM, format_hint

        self.assertNotIn("先依据和目标", ENG_CHAPTER_SYSTEM)
        self.assertIn("施工计划账", ENG_CHAPTER_SYSTEM)
        self.assertIn("不要凑字", ENG_CHAPTER_SYSTEM)
        self.assertIn("规范、通用工法里已有的做法不要复述", ENG_CHAPTER_SYSTEM)
        self.assertIn("施工计划账", WATER_CHAPTER_SYSTEM)
        self.assertIn("不要用「目标」「组织保证」「检查考核」", format_hint({"title": "临近住宅降噪", "engKind": "pairs"}))
        self.assertIn("照抄【施工计划账】", format_hint({"title": "主要施工机械表", "engKind": "grid"}))

    def test_length_follows_score_weight(self) -> None:
        from app.engines.engineering_writer import target_chars

        facts = {
            "pageLimit": 3,
            "scoreItems": [{"title": "工程重点难点", "weight": "40%"}, {"title": "人材机保障", "weight": "30%"}],
        }
        outline = [
            {"id": "a", "title": "工程重点难点", "parentId": None},
            {"id": "a1", "title": "无市政道路", "parentId": "a"},
            {"id": "b", "title": "人材机保障", "parentId": None},
            {"id": "b1", "title": "劳动力", "parentId": "b"},
            {"id": "b2", "title": "物资", "parentId": "b"},
            {"id": "b3", "title": "机械", "parentId": "b"},
        ]
        heavy = target_chars(outline[1], outline, facts)
        light = target_chars(outline[3], outline, facts)
        self.assertLess(heavy, 3000)
        self.assertGreater(heavy, light * 2)

    def test_ungrounded_numbers_only_flags_unsourced_quantities(self) -> None:
        from app.engines.engineering_writer import ungrounded_numbers

        content = "配置挖掘机 12 台，普工 120 人，土方 190741m3，有机肥 9000 吨，开工后第 45 天完成，水准仪 4 台。"
        sources = "挖掘机 12台 普工 常态60人／高峰120人 小沟土方开挖 190741.296m3"
        self.assertEqual(ungrounded_numbers(content, sources), ["9000吨"])

    def test_build_plan_normalizes_model_json(self) -> None:
        from app.engines import engineering_writer
        from app.engines.llm import LlmError

        reply = '{"stages":[{"name":"准备","start":"第1天","end":"第15天"}],"machines":[{"name":"挖掘机","count":"8"},{"spec":"无名"}]}'
        with mock.patch.object(engineering_writer, "chat_complete", return_value=reply) as chat:
            plan = engineering_writer.build_plan(FACTS, BOQ_ROWS, None)
        self.assertIn("小沟土方开挖 190741.296m3", chat.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(plan["stages"][0]["end"], "第15天")
        self.assertEqual([m["name"] for m in plan["machines"]], ["挖掘机"])
        with mock.patch.object(engineering_writer, "chat_complete", side_effect=LlmError("down")):
            self.assertEqual(engineering_writer.build_plan(FACTS, [], None)["stages"], [])


if __name__ == "__main__":
    unittest.main()
