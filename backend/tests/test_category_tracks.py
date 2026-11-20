"""标书类别按选择原样生效：软件服务类不改写成产品标，且不抽图纸/清单。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch


class CategoryNormalizeTests(unittest.TestCase):
    def test_software_choice_is_kept(self) -> None:
        from app.engines.parse_schema import DEFAULT_CATEGORY, normalize_category

        self.assertEqual(DEFAULT_CATEGORY, "软件服务类")
        self.assertEqual(normalize_category("软件服务类"), "软件服务类")
        self.assertNotEqual(normalize_category("软件服务类"), "产品标")
        self.assertEqual(normalize_category("产品标"), "软件服务类")
        self.assertEqual(normalize_category(""), "软件服务类")
        self.assertEqual(normalize_category(None), "软件服务类")

    def test_engineering_choice_is_kept(self) -> None:
        from app.engines.parse_schema import ENGINEERING_CATEGORY, is_engineering_category, normalize_category

        self.assertEqual(ENGINEERING_CATEGORY, "工程类")
        self.assertEqual(normalize_category("工程类"), "工程类")
        self.assertEqual(normalize_category("工程标"), "工程类")
        self.assertTrue(is_engineering_category("工程类"))
        self.assertTrue(is_engineering_category("工程标"))
        self.assertFalse(is_engineering_category("软件服务类"))
        self.assertFalse(is_engineering_category("产品标"))
        self.assertFalse(is_engineering_category(""))
        self.assertFalse(is_engineering_category(None))


class ProductKindTests(unittest.TestCase):
    def test_product_slots_hide_drawing_and_boq(self) -> None:
        from app.engines.tender_package import kind_slots_for

        keys = [spec["key"] for spec in kind_slots_for("产品标")]
        self.assertEqual(keys, ["main", "addendum", "quote"])
        old_keys = [spec["key"] for spec in kind_slots_for("软件服务类")]
        self.assertEqual(old_keys, keys)
        eng = [spec["key"] for spec in kind_slots_for("工程类")]
        self.assertIn("boq", eng)
        self.assertIn("drawing", eng)

    def test_product_does_not_guess_drawing_or_boq(self) -> None:
        from app.engines.tender_package import effective_kind, guess_kind, normalize_kind

        self.assertEqual(guess_kind("施工图纸.pdf", "产品标"), "quote")
        self.assertEqual(guess_kind("工程量清单.xlsx", "软件服务类"), "quote")
        self.assertEqual(normalize_kind("drawing", "a.pdf", "产品标"), "quote")
        self.assertEqual(normalize_kind("boq", "a.xlsx", "产品标"), "quote")
        self.assertEqual(effective_kind("drawing", "施工图.pdf", "产品标"), "quote")
        self.assertEqual(effective_kind("main", "工程量清单.xlsx", "产品标"), "quote")
        self.assertEqual(guess_kind("施工图纸.pdf", "工程标"), "drawing")
        self.assertEqual(guess_kind("工程量清单.xlsx", "工程类"), "boq")

    def test_product_package_slots_omit_engineering(self) -> None:
        from app.engines.tender_package import package_slots

        docs = [SimpleNamespace(id="1", filename="施工图纸.pdf", kind="drawing", size_bytes=10)]
        slots = package_slots(docs, "产品标")
        self.assertEqual([slot["kind"] for slot in slots], ["main", "addendum", "quote"])
        quote = next(slot for slot in slots if slot["kind"] == "quote")
        self.assertTrue(quote["uploaded"])
        self.assertEqual(quote["files"][0]["filename"], "施工图纸.pdf")


class ProductFillTests(unittest.TestCase):
    def test_product_extra_fills_skip_boq_and_drawing(self) -> None:
        from app.engines.tender_package import extra_fills_from_package

        parts = [
            {
                "kind": "boq",
                "filename": "清单.xlsx",
                "text": "项目",
                "boqItems": [{"name": "土方", "unit": "m3", "qty": "100", "remark": ""}],
            }
        ]
        notes = {"drawing": ["施工图.pdf"], "boq": ["清单.xlsx"]}
        fills = extra_fills_from_package(parts, notes, category="产品标")
        self.assertNotIn("qty-boq", fills)
        self.assertNotIn("qty-drawing", fills)
        self.assertNotIn("contract-tech", fills)

        old_fills = extra_fills_from_package(parts, notes, category="软件服务类")
        self.assertNotIn("qty-boq", old_fills)
        self.assertNotIn("qty-drawing", old_fills)

    def test_engineering_extra_fills_keep_boq(self) -> None:
        from app.engines.tender_package import extra_fills_from_package

        parts = [
            {
                "kind": "boq",
                "filename": "清单.xlsx",
                "text": "项目",
                "boqItems": [{"name": "土方开挖", "unit": "m3", "qty": "100", "remark": ""}],
            }
        ]
        fills = extra_fills_from_package(parts, {"drawing": ["图.pdf"]}, category="工程标")
        self.assertIn("qty-boq", fills)
        self.assertIn("qty-drawing", fills)

    def test_product_schema_has_no_quantity_dimension(self) -> None:
        from app.engines.parse_schema import empty_tree, load_schema

        keys = [dim["key"] for dim in load_schema("产品标")]
        self.assertNotIn("quantity", keys)
        ids = [item["id"] for dim in empty_tree("软件服务类") for item in dim["items"]]
        self.assertNotIn("qty-boq", ids)
        self.assertNotIn("qty-drawing", ids)
        eng_ids = [item["id"] for dim in empty_tree("工程类") for item in dim["items"]]
        self.assertIn("qty-boq", eng_ids)
        self.assertIn("qty-drawing", eng_ids)

    def test_extract_bundle_drops_boq_items_for_product(self) -> None:
        from app.engines.tender_package import extract_file_bundle

        payload = ("text", {"boqItems": [{"name": "土方"}]})
        with patch("app.engines.tender_package._extract_file_inner", return_value=payload):
            bundle = extract_file_bundle("x.xlsx", kind="boq", filename="清单.xlsx", category="产品标")
        self.assertEqual(bundle["boqItems"], [])
        with patch("app.engines.tender_package._extract_file_inner", return_value=payload):
            bundle = extract_file_bundle("x.xlsx", kind="boq", filename="清单.xlsx", category="工程标")
        self.assertEqual(bundle["boqItems"], [{"name": "土方"}])


if __name__ == "__main__":
    unittest.main()
