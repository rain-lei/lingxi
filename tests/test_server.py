import tempfile
import unittest
from pathlib import Path

from server import DemoEngine, chunk_text


class DemoEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        self.engine = DemoEngine(database)
        self.device_id = "test-device"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_profile_defaults_and_memory_updates(self) -> None:
        default = self.engine.get_profile(self.device_id)
        self.assertEqual(default.preferred_name, "朋友")
        self.assertEqual(default.speech_rate, "normal")

        updated, changes = self.engine.update_profile_from_text(
            self.device_id, "记住我叫小林，语速慢一点"
        )
        self.assertEqual(updated.preferred_name, "小林")
        self.assertEqual(updated.speech_rate, "slow")
        self.assertIn("称呼：小林", changes)
        self.assertIn("语速：慢", changes)

    def test_companion_reply_uses_memory(self) -> None:
        profile, _ = self.engine.update_profile_from_text(self.device_id, "请叫我爷爷")
        reply = self.engine.generate_reply("今天心情不好怎么办", "companion", profile)
        self.assertIn("爷爷", reply)
        self.assertIn("我陪你", reply)

    def test_translation_demo_path(self) -> None:
        profile = self.engine.get_profile(self.device_id)
        reply = self.engine.generate_reply(
            "翻译：请问附近有不含花生的菜吗？", "translate", profile
        )
        self.assertEqual(reply, "Excuse me, are there any peanut-free dishes nearby?")

    def test_history_and_reset(self) -> None:
        self.engine.record_interaction(self.device_id, "assistant", "你好", "你好呀")
        self.assertEqual(len(self.engine.recent_history(self.device_id)), 1)
        self.engine.reset_device(self.device_id)
        self.assertEqual(self.engine.recent_history(self.device_id), [])

    def test_chunk_text_reassembles_original(self) -> None:
        original = "灵犀正在流式回复，你好！"
        self.assertEqual("".join(chunk_text(original, width=3)), original)


if __name__ == "__main__":
    unittest.main()
