import json
import os
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from device_protocol import PROTOCOL_VERSION
from server import DemoEngine, LingXiServer


class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        engine = DemoEngine(Path(self.temp_dir.name) / "http-test.db")
        self.server = LingXiServer(("127.0.0.1", 0), engine)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        connection = HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_static_console_has_browser_security_headers(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"feedbackCountMetric", body)
        self.assertIn(b"cancelRunButton", body)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_head_static_console_returns_headers_without_body(self) -> None:
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_feedback_memory_http_lifecycle_is_visitor_scoped(self) -> None:
        device_id = "web-http-test-01"
        status, _, body = self.request(
            "POST",
            "/api/interactions",
            {
                "device_id": device_id,
                "text": "帮我制定今晚的复习计划",
                "mode": "assistant",
                "offline": False,
            },
        )
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in body.decode("utf-8").splitlines() if line]
        self.assertTrue(any(event["type"] == "plan" for event in events))
        self.assertTrue(any(event["type"] == "tool" for event in events))
        complete = next(event for event in events if event["type"] == "complete")

        status, _, body = self.request(
            "POST",
            "/api/feedback",
            {
                "device_id": device_id,
                "interaction_id": complete["interaction_id"],
                "rating": -1,
                "correction": "以后先给结论，只列三步",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["metrics"]["memory_count"], 1)

        status, _, body = self.request("GET", f"/api/memory/items?device_id={device_id}")
        self.assertEqual(status, 200)
        memory = json.loads(body)["items"][0]
        self.assertEqual(memory["rule"], "以后先给结论，只列三步")

        status, _, _ = self.request(
            "POST",
            "/api/memory/delete",
            {"device_id": "web-http-test-02", "memory_id": memory["id"]},
        )
        self.assertEqual(status, 404)

        status, _, body = self.request(
            "POST",
            "/api/memory/delete",
            {"device_id": device_id, "memory_id": memory["id"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["metrics"]["memory_count"], 0)

    def test_task_http_lifecycle_is_visitor_scoped(self) -> None:
        device_id = "web-task-http-01"
        status, _, body = self.request(
            "POST",
            "/api/interactions",
            {
                "device_id": device_id,
                "text": "8月30日18:30主楼302有讲座，提前一小时提醒我报名",
                "mode": "assistant",
                "offline": False,
            },
        )
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in body.decode("utf-8").splitlines() if line]
        task_event = next(event for event in events if event["type"] == "task")
        task_id = int(task_event["task"]["id"])
        self.assertEqual(task_event["task"]["status"], "pending")
        self.assertTrue(
            any(
                event["type"] == "tool" and event["name"] == "task.create"
                for event in events
            )
        )

        status, _, body = self.request("GET", f"/api/tasks?device_id={device_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["id"], task_id)

        status, _, body = self.request(
            "POST",
            "/api/tasks/update",
            {"device_id": "web-task-http-02", "task_id": task_id, "status": "confirmed"},
        )
        self.assertEqual(status, 404)

        status, _, body = self.request(
            "POST",
            "/api/tasks/update",
            {"device_id": device_id, "task_id": task_id, "status": "confirmed"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["task"]["status"], "confirmed")

        status, _, body = self.request(
            "GET",
            f"/api/tasks?device_id={device_id}&status=confirmed",
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["items"]), 1)

    def test_demo_and_console_routes_are_distinct(self) -> None:
        status, _, demo_body = self.request("GET", "/demo")
        self.assertEqual(status, 200)
        self.assertIn("在线演示".encode("utf-8"), demo_body)
        self.assertIn(b"demoTaskResult", demo_body)
        self.assertIn(b"demoCancelButton", demo_body)

        status, _, console_body = self.request("GET", "/console")
        self.assertEqual(status, 200)
        self.assertIn("系统控制台".encode("utf-8"), console_body)
        self.assertIn(b"taskCenterTitle", console_body)
        self.assertNotEqual(demo_body, console_body)

    def test_device_endpoint_enforces_auth_hello_and_sequence(self) -> None:
        token = "integration-test-device-token"
        headers = {"Authorization": f"Bearer {token}"}
        timestamp_ms = int(time.time() * 1000)
        heartbeat = {
            "version": PROTOCOL_VERSION,
            "type": "device.heartbeat",
            "device_id": "lingxi-http-p01",
            "seq": 1,
            "timestamp_ms": timestamp_ms,
            "payload": {"battery_percent": 80, "rssi_dbm": -50},
        }
        hello = {
            "version": PROTOCOL_VERSION,
            "type": "device.hello",
            "device_id": "lingxi-http-p01",
            "seq": 1,
            "timestamp_ms": timestamp_ms,
            "payload": {
                "firmware": "test-0.4.0",
                "capabilities": ["microphone", "speaker"],
            },
        }
        with patch.dict(os.environ, {"LINGXI_DEVICE_TOKEN": token}):
            status, _, _ = self.request("POST", "/api/device/events", heartbeat, headers)
            self.assertEqual(status, 400)

            status, _, body = self.request("POST", "/api/device/events", hello, headers)
            self.assertEqual(status, 202)
            acknowledgement = json.loads(body)
            self.assertEqual(acknowledgement["session"]["state"], "idle")

            status, _, _ = self.request("POST", "/api/device/events", heartbeat, headers)
            self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
