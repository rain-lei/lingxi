import unittest
import json
import subprocess
import sys
import tempfile
from pathlib import Path

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

    def test_cli_can_save_json_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "memory-eval.json"
            result = subprocess.run(
                [sys.executable, "tools/memory_eval.py", "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(saved["ok"])
            self.assertIn("checks", saved)


if __name__ == "__main__":
    unittest.main()
