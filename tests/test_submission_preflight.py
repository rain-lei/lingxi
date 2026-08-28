import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import submission_preflight as preflight


class SubmissionPreflightTests(unittest.TestCase):
    def test_required_files_are_checked_from_given_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for relative_path in preflight.REQUIRED_FILES:
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("ok", encoding="utf-8")
            self.assertEqual(preflight.check_required_files(root), list(preflight.REQUIRED_FILES))

    def test_public_demo_requires_pages_models_and_reminders(self) -> None:
        base_url = "https://example.test"
        responses = {
            f"{base_url}/demo": (200, "在线演示".encode("utf-8")),
            f"{base_url}/console": (200, "系统控制台".encode("utf-8")),
            f"{base_url}/api/health": (200, json.dumps({"ok": True}).encode("utf-8")),
            f"{base_url}/api/capabilities": (
                200,
                json.dumps(
                    {
                        "enabled": True,
                        "chat": True,
                        "vision": True,
                        "models": {"chat": "step-3.7-flash"},
                        "task_center": {"reminders": {"enabled": True}},
                    }
                ).encode("utf-8"),
            ),
        }
        with patch.object(preflight, "_request", side_effect=lambda url: responses[url]):
            capabilities = preflight.check_public_demo(base_url)
        self.assertEqual(capabilities["models"]["chat"], "step-3.7-flash")

    def test_public_demo_rejects_disabled_model(self) -> None:
        base_url = "https://example.test"
        responses = {
            f"{base_url}/demo": (200, "在线演示".encode("utf-8")),
            f"{base_url}/console": (200, "系统控制台".encode("utf-8")),
            f"{base_url}/api/health": (200, json.dumps({"ok": True}).encode("utf-8")),
            f"{base_url}/api/capabilities": (
                200,
                json.dumps({"enabled": False, "task_center": {"reminders": {"enabled": True}}}).encode("utf-8"),
            ),
        }
        with patch.object(preflight, "_request", side_effect=lambda url: responses[url]):
            with self.assertRaises(preflight.PreflightError):
                preflight.check_public_demo(base_url)


if __name__ == "__main__":
    unittest.main()
