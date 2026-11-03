"""豆包同时接入文本模型和 Seedream 生图，生图不能拿去写正文。"""

from __future__ import annotations

import unittest

from app.engines.llm import LlmError, _from_row
from app.llm_catalog import PRESETS
from app.models import LlmModel, LlmProvider


class DoubaoModelsTest(unittest.TestCase):
    def test_preset_has_text_and_image(self) -> None:
        doubao = next(item for item in PRESETS if item["kind"] == "doubao")
        tasks = {row.get("task") for row in doubao["sample_models"]}
        self.assertEqual(tasks, {"chat", "image"})
        image = next(row for row in doubao["sample_models"] if row.get("task") == "image")
        self.assertIn("seedream", image["api_model"])

    def test_image_model_is_rejected_for_writing(self) -> None:
        provider = LlmProvider(
            kind="doubao",
            name="豆包",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="k",
            enabled=True,
        )
        model = LlmModel(name="豆包 Seedream 生图", api_model="doubao-seedream-4-0-250828", task="image", enabled=True)
        with self.assertRaises(LlmError):
            _from_row(model, provider)


if __name__ == "__main__":
    unittest.main()
