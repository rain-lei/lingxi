import unittest

from tools.memory_eval import run_replay


class MemoryReplayTests(unittest.TestCase):
    def test_replay_measures_recall_precision_and_prompt_injection(self) -> None:
        report = run_replay()
        self.assertTrue(report["ok"])
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["baseline"]["hits"], 0)
        self.assertGreaterEqual(report["similar_task"]["hits"], 1)
        self.assertEqual(report["unrelated_task"]["hits"], 0)
        self.assertGreater(report["similar_task"]["estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
