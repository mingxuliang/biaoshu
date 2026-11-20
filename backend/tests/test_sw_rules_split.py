"""AI预审 + 预审规则按标书类别拆分（工程类 / 软件服务类）：

- rules_config.load_enabled_sw_* 系列函数：空库回退 rules_data.SW_* 常量、DB 有行时按 enabled 过滤。
- rules_data.catalog_bundle(is_engineering)：两套目录彻底独立，互不包含对方专属 key。
- e3_semantic._build_system_prompt：is_engineering=False 时不得出现工程类专属的属地合规细节。
- standard_review._judge_system_for：按 is_engineering 选对应系统提示词。
- orchestrator.run_prereview：按 project.category 分流到 load_enabled_* 还是 load_enabled_sw_*，
  并把 is_engineering 正确透传给 e3_semantic.run / e3_tech_modules.evaluate / standard_review.review。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


class CatalogBundleTests(unittest.TestCase):
    """rules_data.catalog_bundle：两套常量彻底独立，不是同一份数据加 if 过滤。"""

    def test_engineering_bundle_has_no_sw_only_keys(self) -> None:
        from app.engines import rules_data

        bundle = rules_data.catalog_bundle(True)
        tech_keys = {m["key"] for m in bundle["tech"]}
        self.assertIn("qty_logic", tech_keys)
        self.assertIn("schedule", tech_keys)
        self.assertNotIn("architecture", tech_keys)
        self.assertNotIn("deployment_plan", tech_keys)
        self.assertIs(bundle["local_item_checks"], None)
        self.assertIs(bundle["veto"], rules_data.VETO_CHECK_POINTS)
        self.assertIs(bundle["dimension_rubric"], rules_data.DIMENSION_RUBRIC)

    def test_software_bundle_has_no_engineering_only_keys(self) -> None:
        from app.engines import rules_data

        bundle = rules_data.catalog_bundle(False)
        tech_keys = {m["key"] for m in bundle["tech"]}
        self.assertIn("architecture", tech_keys)
        self.assertIn("deployment_plan", tech_keys)
        self.assertIn("data_security", tech_keys)
        self.assertNotIn("qty_logic", tech_keys)
        self.assertNotIn("schedule", tech_keys)
        self.assertIsNotNone(bundle["local_item_checks"])
        self.assertIs(bundle["veto"], rules_data.SW_VETO_CHECK_POINTS)
        self.assertIs(bundle["dimension_rubric"], rules_data.SW_DIMENSION_RUBRIC)
        # 技术评分模块分值须凑满 100，与工程类一样遵循同一约束
        self.assertEqual(sum(m["score"] for m in bundle["tech"]), 100)


class RulesConfigSwFallbackTests(unittest.TestCase):
    """rules_config.load_enabled_sw_*：空表回退常量，有表则按 enabled 过滤，彻底不碰工程类四张表。"""

    @classmethod
    def setUpClass(cls) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base

        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def test_sw_veto_keys_fallback_to_constants_when_table_empty(self) -> None:
        from app.engines import rules_config, rules_data

        keys = rules_config.load_enabled_sw_veto_keys(self.db)
        self.assertEqual(keys, {item["key"] for item in rules_data.SW_VETO_CHECK_POINTS})

    def test_sw_veto_keys_respect_disabled_rows(self) -> None:
        from app.models import SwVetoRule
        from app.engines import rules_config, rules_data

        for item in rules_data.SW_VETO_CHECK_POINTS:
            self.db.add(
                SwVetoRule(
                    key=item["key"],
                    category=item["category"],
                    point=item["point"],
                    enabled=(item["key"] != "price"),
                )
            )
        self.db.commit()
        keys = rules_config.load_enabled_sw_veto_keys(self.db)
        self.assertNotIn("price", keys)
        self.assertIn("file_form", keys)

    def test_sw_catalog_keys_fallback_and_db_hit(self) -> None:
        from app.models import SwCatalogRule
        from app.engines import rules_config, rules_data

        fallback = rules_config.load_enabled_sw_catalog_keys(self.db, "tech")
        self.assertEqual(fallback, {m["key"] for m in rules_data.SW_TECH_SCORE_MODULES})
        self.assertIn("architecture", fallback)

        for item in rules_data.SW_TECH_SCORE_MODULES:
            self.db.add(
                SwCatalogRule(
                    kind="tech",
                    key=item["key"],
                    category=item["category"],
                    point=item["point"],
                    enabled=(item["key"] != "architecture"),
                )
            )
        self.db.commit()
        db_hit = rules_config.load_enabled_sw_catalog_keys(self.db, "tech")
        self.assertNotIn("architecture", db_hit)
        self.assertIn("deployment_plan", db_hit)

        # 工程类四个 load_enabled_* 函数不受 sw_ 表影响，彻底独立
        eng_tech = rules_config.load_enabled_catalog_keys(self.db, "tech")
        self.assertIn("qty_logic", eng_tech)
        self.assertNotIn("architecture", eng_tech)

    def test_sw_local_items_fallback_and_db_hit(self) -> None:
        from app.models import SwRulePackage
        from app.engines import rules_config, rules_data

        fallback_items = rules_config.load_sw_local_items(self.db)
        expected = [
            item
            for pkg in rules_data.SW_RULE_PACKAGES
            if pkg.get("status") == "启用"
            for item in (pkg.get("items") or [])
        ]
        self.assertEqual(fallback_items, expected)

        self.db.add(SwRulePackage(name="自定义合规包", region="行业通用", status="启用", items_json=["专属条目A"]))
        self.db.commit()
        db_items = rules_config.load_sw_local_items(self.db)
        self.assertEqual(db_items, ["专属条目A"])
        # 工程类属地细则包不受影响
        self.assertNotEqual(rules_config.load_enabled_package_items(self.db), db_items)


class E3SemanticPromptCategoryTests(unittest.TestCase):
    """e3_semantic._build_system_prompt：软件服务类版本不得混入工程类专属的属地合规细节。"""

    def test_engineering_prompt_includes_local_compliance_detail(self) -> None:
        from app.engines.e3_semantic import _build_system_prompt

        prompt = _build_system_prompt({"completeness": 20}, is_engineering=True)
        self.assertIn("临边防护", prompt)

    def test_software_prompt_excludes_engineering_local_compliance_detail(self) -> None:
        from app.engines.e3_semantic import _build_system_prompt
        from app.engines import rules_data

        prompt = _build_system_prompt(
            {"completeness": 20},
            dimension_rubric=rules_data.SW_DIMENSION_RUBRIC,
            tech_modules=rules_data.SW_TECH_SCORE_MODULES,
            high_score_strategies=rules_data.SW_HIGH_SCORE_STRATEGIES,
            is_engineering=False,
        )
        self.assertNotIn("临边防护", prompt)
        self.assertNotIn("扬尘六个", prompt)

    def test_software_prompt_uses_sw_tech_catalog(self) -> None:
        from app.engines.e3_semantic import _build_system_prompt
        from app.engines import rules_data

        prompt = _build_system_prompt(
            {"completeness": 20},
            tech_modules=rules_data.SW_TECH_SCORE_MODULES,
            is_engineering=False,
        )
        sw_module_names = "".join(m["module"] for m in rules_data.SW_TECH_SCORE_MODULES)
        # 至少一个软件服务类模块名称出现在拼好的技术标评分模块段落里
        self.assertTrue(any(m["module"] in prompt for m in rules_data.SW_TECH_SCORE_MODULES), sw_module_names)


class StandardReviewJudgeSystemTests(unittest.TestCase):
    """standard_review._judge_system_for：按 is_engineering 二选一，互不混用措辞。"""

    def test_engineering_judge_system(self) -> None:
        from app.engines.standard_review import _JUDGE_SYSTEM, _JUDGE_SYSTEM_SW, _judge_system_for

        prompt = _judge_system_for(True)
        self.assertIs(prompt, _JUDGE_SYSTEM)
        self.assertIn("工程标预审员", prompt)
        self.assertIsNot(prompt, _JUDGE_SYSTEM_SW)

    def test_software_judge_system(self) -> None:
        from app.engines.standard_review import _JUDGE_SYSTEM_SW, _judge_system_for

        prompt = _judge_system_for(False)
        self.assertIs(prompt, _JUDGE_SYSTEM_SW)
        self.assertIn("软件服务类标书预审员", prompt)


class OrchestratorCategoryWiringTests(unittest.TestCase):
    """run_prereview：project.category 决定走工程类四个 load_enabled_* 还是并列的 load_enabled_sw_*，
    并把 is_engineering 透传给 e3_semantic / e3_tech_modules / standard_review。

    为隔离测试目标（分流逻辑本身），mock 掉实际会读写文件/调用大模型的引擎实现，只捕获
    编排层传给它们的 key 集合与 is_engineering 标记。"""

    @classmethod
    def setUpClass(cls) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import Base

        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def _make_run(self, category: str):
        from app.models import BidDocument, Project, ReviewRun

        project = Project(code="P-" + category, name="测试项目", type=category, category=category)
        self.db.add(project)
        self.db.flush()
        # storage_path 留空：orchestrator 会判定文件不存在，走 _run_with_path(None) 的纯内存分支，
        # 不需要真实文件也不需要 mock storage 模块。
        doc = BidDocument(project_id=project.id, filename="x.docx", storage_path="", kind="combined")
        self.db.add(doc)
        self.db.flush()
        run = ReviewRun(project_id=project.id, bid_document_id=doc.id, round=1, status="queued", scope="tech")
        self.db.add(run)
        self.db.commit()
        return run

    def _run_and_capture(self, category: str) -> dict:
        from app.engines import orchestrator

        run = self._make_run(category)
        captured: dict = {}

        def fake_e3_semantic_run(text, weights, tech_keys, strategy_keys, dup_keys, score_rules, images=None, **kwargs):
            captured["e3_semantic_tech_keys"] = tech_keys
            captured["e3_semantic_strategy_keys"] = strategy_keys
            captured["e3_semantic_kwargs"] = kwargs
            return {"dimensions": {k: {"score": 0.0, "grade": "A", "reason": ""} for k in weights}, "issues": []}

        def fake_tech_modules_evaluate(text, paras, project_name, tech_keys, images=None, dimensions=None, thresholds=None, **kwargs):
            captured["tech_modules_tech_keys"] = tech_keys
            captured["tech_modules_kwargs"] = kwargs
            return [], []

        def fake_standard_review(db, **kwargs):
            captured["standard_review_category"] = kwargs.get("category")
            return {"specialty": "通用", "note": "", "points": [], "findings": []}

        with (
            patch.object(orchestrator.e3_semantic, "run", side_effect=fake_e3_semantic_run),
            patch.object(orchestrator.e3_tech_modules, "evaluate", side_effect=fake_tech_modules_evaluate),
            patch.object(orchestrator.e4_duplicate_filler, "run", return_value=[]),
            patch.object(orchestrator.e_custom_rules, "run", return_value={"findings": [], "items": []}),
            patch.object(orchestrator.e_tender_score, "run", return_value={}),
            patch.object(orchestrator.standard_review, "review", side_effect=fake_standard_review),
        ):
            orchestrator.run_prereview(self.db, run.id)
        return captured

    def test_engineering_project_routes_to_engineering_catalogs(self) -> None:
        captured = self._run_and_capture("工程类")
        self.assertIn("qty_logic", captured["e3_semantic_tech_keys"])
        self.assertIn("schedule", captured["e3_semantic_tech_keys"])
        self.assertNotIn("architecture", captured["e3_semantic_tech_keys"])
        self.assertTrue(captured["e3_semantic_kwargs"]["is_engineering"])
        self.assertTrue(captured["tech_modules_kwargs"]["is_engineering"])
        self.assertEqual(captured["standard_review_category"], "工程类")

    def test_software_project_routes_to_sw_catalogs(self) -> None:
        captured = self._run_and_capture("软件服务类")
        self.assertIn("architecture", captured["e3_semantic_tech_keys"])
        self.assertIn("data_security", captured["e3_semantic_tech_keys"])
        self.assertNotIn("qty_logic", captured["e3_semantic_tech_keys"])
        self.assertNotIn("schedule", captured["e3_semantic_tech_keys"])
        self.assertFalse(captured["e3_semantic_kwargs"]["is_engineering"])
        self.assertFalse(captured["tech_modules_kwargs"]["is_engineering"])
        self.assertEqual(captured["standard_review_category"], "软件服务类")
        self.assertIsNotNone(captured["e3_semantic_kwargs"]["dimension_rubric"])

    def test_legacy_engineering_label_also_routes_correctly(self) -> None:
        # is_engineering_category 把历史遗留的"工程标"也算工程类，确保分流对旧数据同样生效。
        captured = self._run_and_capture("工程标")
        self.assertIn("qty_logic", captured["e3_semantic_tech_keys"])
        self.assertTrue(captured["e3_semantic_kwargs"]["is_engineering"])


if __name__ == "__main__":
    unittest.main()
