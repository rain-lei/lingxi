"""Local HTTP contract and Windows secret-store checks; never call cloud APIs."""

import io
import json
import os
import struct
import tempfile
import threading
import unittest
import wave
from email.message import Message
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from conversation_service import HardwareConversationService, MAX_INPUT_BYTES
from providers.stepfun import StepFunClient
from runtime_settings import load_local_settings, save_local_settings
from server import DemoEngine, LingXiHandler, LingXiServer
from streaming_conversation import STREAM_MIME


class LocalFakeProvider:
    enabled = True
    api_key = "nonsecret-unit-test-placeholder"
    base_url = "https://api.stepfun.com/v1"
    audio_base_url = base_url

    def __init__(self):
        self.calls = []

    def transcribe_pcm(self, audio, language="zh"):
        self.calls.append("asr")
        return "今天有点累，想找人说说话"

    def stream_chat(self, messages, *, reasoning_effort=None):
        self.calls.append("chat")
        self.messages = messages
        self.reasoning_effort = reasoning_effort
        yield "辛苦了，我在这里。想从今天最累的那件事聊起吗？"

    def synthesize(self, text, speech_rate, mode, **options):
        self.calls.append("tts")
        self.options = options
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setframerate(16000)
            output.setnchannels(1)
            output.setsampwidth(2)
            output.writeframes(struct.pack("<h", 1000) * 3200)
        return buffer.getvalue(), "audio/wav"

    def iter_synthesize_pcm(self, text, speech_rate, mode, **options):
        self.calls.append("tts_stream")
        self.options = options
        # Deterministic local PCM; never create a provider/network client.
        yield struct.pack("<h", 1000) * 1600
        yield struct.pack("<h", 1000) * 1600


class CompanionHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "http.sqlite3"
        self.secret_path = Path(self.temp.name) / "test-settings.json"
        self.env_patch = patch.dict(os.environ, {"LINGXI_DEVICE_TOKEN": ""})
        self.env_patch.start()
        self.log_patch = patch.object(LingXiHandler, "log_message", lambda *args: None)
        self.log_patch.start()
        self.save_patch = patch("server.save_local_settings", side_effect=lambda value: save_local_settings(value, self.secret_path))
        self.save_mock = self.save_patch.start()
        self.provider = LocalFakeProvider()
        self.engine = DemoEngine(self.database, stepfun=self.provider)
        self.server = LingXiServer(("127.0.0.1", 0), self.engine)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.save_patch.stop()
        self.log_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def request(self, method, path, payload=None, headers=None, raw=None):
        headers = dict(headers or {})
        body = raw
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection = HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def unpack(self, body):
        self.assertEqual(body[:4], b"LXI1")
        metadata_length, pcm_length = struct.unpack("<II", body[4:12])
        self.assertLessEqual(metadata_length, 8192)
        self.assertLessEqual(pcm_length, 640000)
        self.assertEqual(len(body), 12 + metadata_length + pcm_length)
        metadata = json.loads(body[12:12 + metadata_length].decode("utf-8"))
        pcm = body[12 + metadata_length:]
        self.assertEqual(metadata["audio"]["bytes"], len(pcm))
        return metadata, pcm

    def unpack_stream(self, body):
        self.assertEqual(body[:4], b"LXS1")
        offset, events = 4, []
        while offset < len(body):
            self.assertGreaterEqual(len(body) - offset, 5)
            kind = body[offset:offset + 1]
            length = struct.unpack_from("<I", body, offset + 1)[0]
            offset += 5
            self.assertLessEqual(length, 4096 if kind == b"A" else 8192)
            self.assertLessEqual(offset + length, len(body))
            payload = body[offset:offset + length]
            events.append((kind, payload if kind == b"A" else json.loads(payload)))
            offset += length
        self.assertEqual([event[0] for event in events], [b"J", b"A", b"A", b"D"])
        self.assertEqual(sum(len(value) for kind, value in events if kind == b"A"), 6400)
        return events[0][1], events[-1][1]

    def test_catalog_and_settings_persist_with_partial_update(self):
        status, _, body = self.request("GET", "/api/companion/catalog")
        self.assertEqual(status, 200)
        catalog = json.loads(body)
        self.assertTrue(catalog["enabled"])
        self.assertEqual(catalog["limits"]["input_seconds"], 10)
        self.assertIn("wenrounvsheng", [item["id"] for item in catalog["options"]["voice"]])
        status, _, _ = self.request("POST", "/api/companion/settings", {
            "device_id": "http-box", "settings": {"voice": "cixingnansheng", "avatar": "robot"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(HardwareConversationService(self.engine).get_settings("http-box")["avatar"], "robot")
        status, _, body = self.request("GET", "/api/companion/settings?device_id=http-box")
        self.assertEqual(json.loads(body)["settings"]["voice"], "cixingnansheng")

    def test_raw_pcm_lxi1_lengths_and_real_pipeline(self):
        status, headers, body = self.request("POST", "/api/device/conversation", raw=struct.pack("<h", 300) * 3200, headers={"Content-Type": "audio/pcm", "X-Device-Id": "http-box"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/vnd.lingxi.voice+binary")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        metadata, pcm = self.unpack(body)
        self.assertEqual(self.provider.calls, ["asr", "chat", "tts"])
        self.assertIn("今天有点累", metadata["transcript"])
        self.assertEqual(metadata["audio"]["sample_rate"], 16000)
        self.assertEqual(len(pcm), 6400)

    def test_hardware_tone_header_applies_before_both_voice_pipelines_and_preserves_other_settings(self):
        device_id = "tone-button-box"
        baseline = {"tone": "warm", "voice": "cixingnansheng", "avatar": "otter",
                    "persona": "mentor", "language": "zh", "speech_rate": "slow"}
        transcribe = self.provider.transcribe_pcm
        seen_at_asr = []

        def observe_asr(*args, **kwargs):
            seen_at_asr.append(self.server.companion.get_settings(device_id))
            return transcribe(*args, **kwargs)

        with patch.object(self.provider, "transcribe_pcm", side_effect=observe_asr):
            for streaming in (False, True):
                for tone in ("warm", "calm", "cheerful", "direct"):
                    with self.subTest(streaming=streaming, tone=tone):
                        # A different stored tone proves this request's header
                        # takes effect before ASR, rather than a later save.
                        stored = {**baseline, "tone": "calm" if tone == "warm" else "warm"}
                        before = self.server.companion.update_settings(device_id, stored)
                        expected = {**before, "tone": tone}
                        self.provider.calls.clear()
                        headers = {"Content-Type": "audio/pcm", "X-Device-Id": device_id,
                                   "X-Lingxi-Tone": tone}
                        if streaming:
                            headers["Accept"] = STREAM_MIME
                        status, response_headers, body = self.request(
                            "POST", "/api/device/conversation",
                            raw=struct.pack("<h", 300) * 3200, headers=headers)
                        self.assertEqual(status, 200)
                        self.assertEqual(seen_at_asr[-1], expected)
                        self.assertEqual(self.server.companion.get_settings(device_id), expected)
                        if streaming:
                            self.assertEqual(response_headers["Content-Type"], STREAM_MIME)
                            first, final = self.unpack_stream(body)
                            self.assertEqual(first["settings"], expected)
                            self.assertEqual(final["settings"], expected)
                        else:
                            metadata, pcm = self.unpack(body)
                            self.assertEqual(metadata["settings"], expected)
                            self.assertEqual(len(pcm), 6400)
                        self.assertEqual(self.provider.calls, ["asr", "chat", "tts_stream" if streaming else "tts"])
                        self.assertEqual(self.provider.options["tone"], tone)
                        self.assertEqual(self.provider.options["voice"], baseline["voice"])
        self.assertEqual(len(seen_at_asr), 8)

    def test_hardware_invalid_tone_header_rejects_before_provider_or_settings_mutation(self):
        device_id = "invalid-tone-box"
        expected = self.server.companion.update_settings(device_id, {
            "tone": "calm", "voice": "yuanqishaonv", "avatar": "cat", "persona": "playful"})
        with patch.object(self.provider, "transcribe_pcm") as asr, \
                patch.object(self.provider, "synthesize") as tts, \
                patch.object(self.provider, "iter_synthesize_pcm") as streaming_tts:
            for streaming in (False, True):
                for tone in ("whisper", "CALM", "calm,direct", ""):
                    with self.subTest(streaming=streaming, tone=tone):
                        headers = {"Content-Type": "audio/pcm", "X-Device-Id": device_id,
                                   "X-Lingxi-Tone": tone}
                        if streaming:
                            headers["Accept"] = STREAM_MIME
                        status, response_headers, body = self.request(
                            "POST", "/api/device/conversation",
                            raw=struct.pack("<h", 300) * 3200, headers=headers)
                        self.assertEqual(status, 400)
                        self.assertTrue(response_headers["Content-Type"].startswith("application/json"))
                        self.assertIn("error", json.loads(body))
                        self.assertEqual(self.server.companion.get_settings(device_id), expected)
            asr.assert_not_called()
            tts.assert_not_called()
            streaming_tts.assert_not_called()
        self.assertEqual(self.provider.calls, [])

    def test_hardware_absent_tone_header_keeps_selected_tone_for_both_voice_formats(self):
        device_id = "existing-tone-box"
        expected = self.server.companion.update_settings(device_id, {
            "tone": "direct", "voice": "cixingnansheng", "avatar": "sprout", "persona": "mentor"})
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                headers = {"Content-Type": "audio/pcm", "X-Device-Id": device_id}
                if streaming:
                    headers["Accept"] = STREAM_MIME
                status, _, body = self.request("POST", "/api/device/conversation",
                    raw=struct.pack("<h", 300) * 3200, headers=headers)
                self.assertEqual(status, 200)
                metadata = self.unpack_stream(body)[0] if streaming else self.unpack(body)[0]
                self.assertEqual(metadata["settings"], expected)
                self.assertEqual(self.server.companion.get_settings(device_id), expected)
                self.assertEqual(self.provider.options["tone"], "direct")

    def test_text_chat_uses_selected_voice_and_can_skip_audio(self):
        self.request("POST", "/api/companion/settings", {"device_id": "http-box", "settings": {"voice": "yuanqishaonv", "tone": "cheerful"}})
        status, _, body = self.request("POST", "/api/companion/chat", {"device_id": "http-box", "text": "今天还好吗", "speak": True})
        self.assertEqual(status, 200)
        metadata, _ = self.unpack(body)
        self.assertEqual(metadata["transcript"], "今天还好吗")
        self.assertEqual(self.provider.options["voice"], "yuanqishaonv")
        self.assertEqual(self.provider.options["tone"], "cheerful")
        self.provider.calls.clear()
        status, _, body = self.request("POST", "/api/companion/chat", {"device_id": "http-box", "text": "谢谢你", "speak": False})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["audio"]["bytes"], 0)
        self.assertEqual(self.provider.calls, ["chat"])

    def test_unconfigured_provider_returns_503_json(self):
        self.engine.stepfun = StepFunClient()
        for path, payload, raw, headers in (
            ("/api/companion/chat", {"device_id": "http-box", "text": "你好"}, None, {}),
            ("/api/device/conversation", None, struct.pack("<h", 300) * 3200, {"Content-Type": "audio/pcm"}),
        ):
            status, _, body = self.request("POST", path, payload, raw=raw, headers=headers)
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body)["code"], "provider_not_configured")
            self.assertNotEqual(body[:4], b"LXI1")

    def test_recording_format_and_oversize_are_rejected(self):
        status, _, _ = self.request("POST", "/api/device/conversation", raw=b"x" * 6400, headers={"Content-Type": "audio/wav"})
        self.assertEqual(status, 400)
        status, _, body = self.request("POST", "/api/device/conversation", raw=b"\x01\0" * (MAX_INPUT_BYTES // 2 + 1), headers={"Content-Type": "audio/pcm"})
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["code"], "audio_too_long")
        self.assertEqual(self.provider.calls, [])

    def test_setup_rejects_wrong_host_or_cross_origin_before_saving(self):
        payload = {"api_key": "nonsecret-test-placeholder", "base_url": "https://api.stepfun.com/v1"}
        for headers in (
            {"Host": "evil.example"},
            {"Origin": "https://evil.example"},
            {"Origin": f"http://127.0.0.1:{self.port + 1}"},
        ):
            status, _, _ = self.request("POST", "/api/companion/setup", payload, headers=headers)
            self.assertEqual(status, 403)
        self.save_mock.assert_not_called()
        self.assertFalse(self.secret_path.exists())

    def test_same_origin_loopback_setup_uses_temp_store_and_hides_secret(self):
        fake_key = "nonsecret-test-placeholder"
        status, _, body = self.request("POST", "/api/companion/setup", {"api_key": fake_key, "base_url": "https://api.stepfun.com/v1", "device_token": "test-pair-code"}, headers={"Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["configured"])
        self.assertNotIn(fake_key.encode(), body)
        self.assertTrue(self.secret_path.exists())
        self.assertEqual(load_local_settings(self.secret_path)["api_key"], fake_key)
        self.assertEqual(self.engine.stepfun.audio_base_url, "https://api.stepfun.com/v1")
        status, _, body = self.request("GET", "/api/companion/setup")
        self.assertNotIn(fake_key.encode(), body)
        self.assertTrue(json.loads(body)["device_token_required"])

    def test_pair_token_blocks_lan_requests_and_accepts_header_or_bearer(self):
        self.server.companion_token = "test-token"
        path = "/api/companion/settings?device_id=http-box"
        status, _, body = self.request("GET", path, headers={"Host": f"192.0.2.20:{self.port}"})
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["code"], "invalid_device_token")
        for auth in ({"X-Device-Token": "test-token"}, {"Authorization": "Bearer test-token"}):
            status, _, _ = self.request("GET", path, headers={"Host": f"192.0.2.20:{self.port}", **auth})
            self.assertEqual(status, 200)

    def test_non_ascii_presented_token_cannot_crash_get_handler(self):
        self.server.companion_token = "test-token"
        status, _, body = self.request("GET", "/api/companion/settings?device_id=http-box", headers={"Host": f"192.0.2.20:{self.port}", "X-Device-Token": "caf\u00e9"})
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["code"], "invalid_device_token")

    def test_non_loopback_socket_cannot_configure_even_with_local_host(self):
        handler = object.__new__(LingXiHandler)
        handler.client_address = ("192.0.2.50", 1234)
        handler.headers = Message()
        handler.headers["Host"] = f"127.0.0.1:{self.port}"
        self.assertFalse(handler._local_setup_allowed())

    def test_original_routes_cannot_bypass_device_pairing(self):
        self.server.companion_token = 'test-token'
        headers = {'Host': 'lingxi.example'}
        for path in ('/api/tasks', '/api/profile', '/api/history', '/api/memory/items', '/api/memory/metrics'):
            self.assertEqual(self.request('GET', path + '?device_id=physical:box', headers=headers)[0], 401)
            self.assertEqual(self.request('GET', path + '?device_id=physical:box', headers={**headers, 'X-Device-Token': 'test-token'})[0], 200)
        self.assertEqual(self.request('POST', '/api/reset', {'device_id': 'physical:box'}, headers=headers)[0], 401)
        # Web sessions remain publicly usable without borrowing a hardware ID.
        self.assertEqual(self.request('GET', '/api/companion/settings?device_id=web-isolated-test', headers=headers)[0], 200)

    def test_task_is_shared_between_companion_and_console_with_scoped_updates(self):
        identity = 'web-shared-test'
        status, _, body = self.request('POST', '/api/companion/learning/task/create', {'device_id': identity, 'title': '完成复习'})
        self.assertEqual(status, 200)
        task = json.loads(body)['task']
        status, _, body = self.request('GET', '/api/tasks?device_id=' + identity)
        self.assertEqual(json.loads(body)['items'][0]['id'], task['id'])
        self.assertEqual(self.request('POST', '/api/tasks/update', {'device_id': 'web-another-test', 'task_id': task['id'], 'status': 'completed'})[0], 404)
        self.assertEqual(self.request('POST', '/api/tasks/update', {'device_id': identity, 'task_id': task['id'], 'status': 'completed'})[0], 200)
        status, _, body = self.request('GET', '/api/companion/learning?device_id=' + identity)
        self.assertEqual(json.loads(body)['tasks'][0]['status'], 'completed')
        self.assertEqual(self.request('POST', '/api/companion/learning/task/delete', {'device_id': identity, 'id': task['id']})[0], 200)
        self.assertEqual(json.loads(self.request('GET', '/api/tasks?device_id=' + identity)[2])['items'], [])

    def test_companion_requires_explicit_identity(self):
        self.assertEqual(self.request('POST', '/api/companion/chat', {'text': '你好'})[0], 400)
        self.assertIsNone(json.loads(self.request('GET', '/api/companion/setup')[2])['default_device_id'])

    def test_memory_and_task_flow_for_text_and_hardware_stream(self):
        identity = 'web-flow-test'
        original = self.engine.record_interaction(identity, 'assistant', '明天讲座', '已整理')
        self.engine.record_feedback(identity, original, -1, '以后讲座提醒提前一小时，不要默认提前十分钟。')
        self.server.companion.experience._remember(identity, '我喜欢数学')
        messages = self.engine.build_stepfun_messages(identity, '你好', 'assistant', self.engine.get_profile(identity))
        self.assertIn('我喜欢数学', messages[0]['content'])
        status, _, body = self.request('POST', '/api/companion/chat', {'device_id': identity, 'text': '明天18:30图书馆有讲座，请提醒我参加', 'speak': False})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result['experience']['feedback_memory_ids'])
        self.assertIn('提前一小时', self.provider.messages[0]['content'])
        self.assertEqual(self.engine.list_tasks(identity)[0]['status'], 'pending')
        self.assertEqual(self.server.companion.learning.inspect(identity)['reminders'], [])
        with patch.object(self.provider, 'transcribe_pcm', return_value='明天18:30图书馆有讲座，请提醒我参加'):
            status, _, body = self.request('POST', '/api/device/conversation', raw=struct.pack('<h', 300) * 3200,
                headers={'Content-Type': 'audio/pcm', 'X-Device-Id': identity, 'Accept': STREAM_MIME})
        self.assertEqual(status, 200)
        first, last = self.unpack_stream(body)
        self.assertIn('task', last)
        self.assertEqual(self.engine.list_tasks(identity)[0]['source'], 'voice')
        count = len(self.engine.list_tasks(identity))
        self.request('POST', '/api/companion/chat', {'device_id': identity, 'text': '添加待办：整理笔记', 'speak': False})
        self.assertEqual(len(self.engine.list_tasks(identity)), count + 1)


class LocalSecretStoreTests(unittest.TestCase):
    def test_dpapi_round_trip_in_temporary_directory_without_disclosing_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            original = {"api_key": "nonsecret-dpapi-roundtrip-test", "base_url": "https://api.stepfun.com/v1", "device_token": "test-token"}
            save_local_settings(original, path)
            self.assertEqual(load_local_settings(path), original)
            self.assertNotIn(original["api_key"], path.read_text(encoding="utf-8"))
            if os.name == "nt":
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["protection"], "windows-dpapi")


if __name__ == "__main__":
    unittest.main()
