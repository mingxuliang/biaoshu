"""硅基流动补上适合写标书的长文模型，全部是文本对话，不能是生图。"""

from __future__ import annotations

import unittest

from app.llm_catalog import PRESETS, SILICONFLOW_SCAN_MODEL, SILICONFLOW_WRITER_MODELS


class SiliconFlowWriterModelsTest(unittest.TestCase):
    def test_preset_includes_qwen72b_and_peers(self) -> None:
        silicon = next(item for item in PRESETS if item["kind"] == "siliconflow")
        apis = {row["api_model"] for row in silicon["sample_models"]}
        self.assertIn("deepseek-ai/DeepSeek-V3", apis)
        self.assertIn("Qwen/Qwen3-32B", apis)
        self.assertIn("Qwen/Qwen2.5-72B-Instruct-128K", apis)
        for row in SILICONFLOW_WRITER_MODELS:
            self.assertIn(row["api_model"], apis)
            self.assertNotEqual(row.get("task"), "image")
            self.assertTrue(row.get("id"))

    def test_new_models_are_chat_only(self) -> None:
        tasks = {row.get("task", "chat") for row in SILICONFLOW_WRITER_MODELS}
        self.assertEqual(tasks, {"chat"})

    def test_scan_model_is_cheap_vl_8b(self) -> None:
        silicon = next(item for item in PRESETS if item["kind"] == "siliconflow")
        apis = {row["api_model"] for row in silicon["sample_models"]}
        self.assertEqual(SILICONFLOW_SCAN_MODEL["api_model"], "Qwen/Qwen3-VL-8B-Instruct")
        self.assertIn(SILICONFLOW_SCAN_MODEL["api_model"], apis)
        self.assertNotIn(SILICONFLOW_SCAN_MODEL, SILICONFLOW_WRITER_MODELS)


if __name__ == "__main__":
    unittest.main()
