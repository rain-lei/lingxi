import tempfile
import unittest
from pathlib import Path

from server import DemoEngine, SlidingWindowRateLimiter, chunk_text


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

    def test_vision_message_uses_high_detail_data_url(self) -> None:
        profile = self.engine.get_profile(self.device_id)
        messages = self.engine.build_stepfun_messages(
            self.device_id,
            "读取图片",
            "assistant",
            profile,
            "data:image/png;base64,AA==",
        )
        image_part = messages[-1]["content"][1]["image_url"]
        self.assertEqual(image_part["detail"], "high")
        self.assertTrue(image_part["url"].startswith("data:image/png;base64,"))

    def test_feedback_rule_is_recalled_and_added_to_prompt(self) -> None:
        interaction_id = self.engine.record_interaction(
            self.device_id,
            "assistant",
            "帮我安排今天的学习任务",
            "先学习三小时，再休息。",
        )
        result = self.engine.record_feedback(
            self.device_id,
            interaction_id,
            -1,
            "以后回答更简短，先给结论",
        )
        self.assertEqual(result["metrics"]["memory_count"], 1)

        memories = self.engine.search_feedback_memories(
            self.device_id,
            "帮我安排明天的复习任务",
        )
        self.assertEqual(memories[0]["rule"], "以后回答更简短，先给结论")
        profile = self.engine.get_profile(self.device_id)
        messages = self.engine.build_stepfun_messages(
            self.device_id,
            "帮我安排明天的复习任务",
            "assistant",
            profile,
            feedback_memories=memories,
        )
        self.assertIn("以后回答更简短，先给结论", messages[0]["content"])

    def test_similar_memory_does_not_leak_into_unrelated_task(self) -> None:
        interaction_id = self.engine.record_interaction(
            self.device_id,
            "assistant",
            "图书馆找座位",
            "请查看座位系统。",
        )
        self.engine.record_feedback(
            self.device_id,
            interaction_id,
            -1,
            "先说明图书馆楼层，再推荐座位",
        )
        self.assertTrue(self.engine.search_feedback_memories(self.device_id, "图书馆哪里安静"))
        self.assertEqual(self.engine.search_feedback_memories(self.device_id, "明天天气如何"), [])

    def test_memory_can_be_listed_and_deleted_only_by_owner(self) -> None:
        interaction_id = self.engine.record_interaction(
            self.device_id,
            "assistant",
            "帮我制定复习计划",
            "先列出科目。",
        )
        self.engine.record_feedback(
            self.device_id,
            interaction_id,
            -1,
            "以后先给结论，只列三步",
        )
        memories = self.engine.list_feedback_memories(self.device_id)
        self.assertEqual(len(memories), 1)
        self.assertFalse(
            self.engine.delete_feedback_memory("another-device", int(memories[0]["id"]))
        )
        self.assertTrue(
            self.engine.delete_feedback_memory(self.device_id, int(memories[0]["id"]))
        )
        self.assertEqual(self.engine.list_feedback_memories(self.device_id), [])
        self.assertEqual(self.engine.memory_metrics(self.device_id)["memory_count"], 0)

    def test_task_lifecycle_is_persisted_scoped_and_indexed(self) -> None:
        interaction_id = self.engine.record_interaction(
            self.device_id,
            "assistant",
            "8月30日18:30主楼302有校园讲座，提前一小时提醒我报名",
            "已识别讲座时间和地点，可以生成待确认任务。",
        )
        task = self.engine.create_task_from_interaction(
            self.device_id,
            interaction_id,
            "8月30日18:30主楼302有校园讲座，提前一小时提醒我报名",
            "已识别讲座时间和地点，可以生成待确认任务。",
        )
        self.assertIsNotNone(task)
        self.assertEqual(task["kind"], "event")
        self.assertEqual(task["status"], "pending")
        self.assertIn("8月30日", task["schedule_text"])
        self.assertIn("主楼302", task["location"])
        self.assertIn("确认活动时间与地点", task["checklist"])
        self.assertEqual(self.engine.list_tasks("another-device"), [])

        with self.assertRaises(LookupError):
            self.engine.update_task_status("another-device", int(task["id"]), "confirmed")
        confirmed = self.engine.update_task_status(
            self.device_id,
            int(task["id"]),
            "confirmed",
        )
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(len(self.engine.list_tasks(self.device_id, status="confirmed")), 1)

        with self.engine._connection() as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM tasks "
                "WHERE device_id = ? AND status = ? ORDER BY id DESC LIMIT 50",
                (self.device_id, "confirmed"),
            ).fetchall()
        self.assertTrue(
            any("idx_tasks_device_status" in str(row["detail"]) for row in plan)
        )

        self.engine.reset_device(self.device_id)
        self.assertEqual(self.engine.list_tasks(self.device_id), [])

    def test_non_actionable_chat_does_not_create_task(self) -> None:
        interaction_id = self.engine.record_interaction(
            self.device_id,
            "assistant",
            "你好",
            "你好呀",
        )
        self.assertIsNone(
            self.engine.create_task_from_interaction(
                self.device_id,
                interaction_id,
                "你好",
                "你好呀",
            )
        )

    def test_conversation_history_is_bounded(self) -> None:
        for index in range(55):
            self.engine.record_interaction(
                self.device_id,
                "assistant",
                f"问题 {index}",
                f"回答 {index}",
            )
        self.assertEqual(len(self.engine.recent_history(self.device_id, limit=50)), 50)


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_blocks_after_limit(self) -> None:
        limiter = SlidingWindowRateLimiter()
        self.assertEqual(limiter.allow("client", "interactions", 2), (True, 0))
        self.assertEqual(limiter.allow("client", "interactions", 2), (True, 0))
        allowed, retry_after = limiter.allow("client", "interactions", 2)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)


if __name__ == "__main__":
    unittest.main()
