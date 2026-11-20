"""业绩口径排除项：抽取、选材过滤、预审提示共用同一套类型词。"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from app.engines import business_materials as bm
from app.engines.e2_business import run as e2_run
from app.engines.parse_schema import derive_veto_params
from app.engines.performance_scope import exclusions_from_text, hits


class ScopeExtractTest(unittest.TestCase):
    def test_splits_excluded_types_and_ignores_unrelated_text(self) -> None:
        text = "类似业绩不包括水环境治理、农田整治、高标准农田等项目。报价不含税。"
        self.assertEqual(exclusions_from_text(text), ["水环境治理", "农田整治", "高标准农田"])
        self.assertEqual(exclusions_from_text("计划工期 365 日历天"), [])

    def test_hits_a_close_wording(self) -> None:
        self.assertEqual(hits("无为县水环境综合治理工程", ["水环境治理"]), ["水环境治理"])
        self.assertEqual(hits("堤防加固工程", ["水环境治理"]), [])

    def test_veto_params_keep_the_list(self) -> None:
        params = derive_veto_params([], "投标人业绩不认可高标准农田、农田整治类项目。")
        self.assertIn("高标准农田", params["performance_excluded"])
        self.assertIn("农田整治", params["performance_excluded"])


class ScopeUseTest(unittest.TestCase):
    def test_hard_filter_drops_excluded_achievements(self) -> None:
        kept = SimpleNamespace(
            id="a1", kind="achievement", name="永安河堤防加固", detail="", attrs_json={}, valid_until="长期"
        )
        dropped = SimpleNamespace(
            id="a2", kind="achievement", name="某县高标准农田建设", detail="农田整治", attrs_json={}, valid_until="长期"
        )
        out, notes = bm.hard_filter(
            {"kind": "achievement", "withinYears": 0, "minAmountWan": 0, "excludeTerms": ["高标准农田", "农田整治"]},
            [kept, dropped],
            date(2026, 11, 18),
        )
        self.assertEqual([item.id for item in out], ["a1"])
        self.assertTrue(any("排除" in note for note in notes))

    def test_review_flags_a_bid_that_uses_an_excluded_type(self) -> None:
        paragraphs = [
            {"index": 3, "text": "类似业绩：2023 年完成某县高标准农田建设项目，合同金额 800 万元。"},
            {"index": 4, "text": "附中标通知书、合同、竣工验收和官网截图。"},
        ]
        findings = e2_run(paragraphs, checklist_params={"performance_excluded": ["高标准农田"]})
        rules = [item["rule"] for item in findings]
        self.assertIn("业绩类型与招标排除项冲突", rules)
