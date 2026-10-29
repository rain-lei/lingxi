"""Exercise early audio delivery, error framing, bounds and slot cleanup."""
import json
import struct
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from conversation_service import ConversationServiceError, MAX_OUTPUT_BYTES
from providers.stepfun import StepFunError
from server import DemoEngine, LingXiHandler, LingXiServer
from streaming_conversation import STREAM_MIME, encode_frame, stream_conversation


class StreamingProvider:
    enabled = True
    api_key = "unit-test-private-value"

    def __init__(self):
        self.release = threading.Event()
        self.reached_second = threading.Event()
        self.closed = False
        self.fail = False

    def stream_chat(self, messages, **kwargs):
        yield "我在，先从你最想说的那件事聊起。"

    def iter_synthesize_pcm(self, *args, **kwargs):
        try:
            yield struct.pack("<h", 1000) * 1024
            self.reached_second.set()
            self.release.wait(timeout=3)
            if self.fail:
                raise StepFunError("upstream " + self.api_key)
            yield struct.pack("<h", -1000) * 1024
        finally:
            self.closed = True


class VoiceStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = StreamingProvider()
        self.engine = DemoEngine(Path(self.temp.name) / "stream.sqlite3", stepfun=self.provider)
        self.server = LingXiServer(("127.0.0.1", 0), self.engine)
        self.server.companion_token = ""
        self.logs = patch.object(LingXiHandler, "log_message", lambda *args: None)
        self.logs.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.provider.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.logs.stop()
        self.temp.cleanup()

    def connect(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        connection.request("POST", "/api/companion/chat", json.dumps({"device_id": "stream-box", "text": "你好"}),
                           {"Content-Type": "application/json", "Accept": STREAM_MIME})
        return connection, connection.getresponse()

    @staticmethod
    def read_frame(response):
        header = response.read(5)
        if len(header) != 5:
            raise AssertionError("missing explicit terminal frame")
        kind, size = header[:1], struct.unpack("<I", header[1:])[0]
        payload = response.read(size)
        return kind, payload if kind == b"A" else json.loads(payload)

    def test_http_first_pcm_arrives_while_provider_is_still_waiting(self):
        connection, response = self.connect()
        try:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), STREAM_MIME)
            self.assertIsNone(response.getheader("Content-Length"))
            self.assertEqual(response.read(4), b"LXS1")
            kind, metadata = self.read_frame(response)
            self.assertEqual(kind, b"J")
            self.assertEqual(metadata["audio"]["sample_rate"], 16000)
            kind, first_audio = self.read_frame(response)
            self.assertEqual(kind, b"A")
            self.assertEqual(len(first_audio), 2048)
            self.assertFalse(self.provider.release.is_set())
            self.assertEqual(self.engine.recent_history("stream-box"), [])
            self.provider.release.set()
            self.assertEqual(self.read_frame(response)[0], b"A")
            kind, final = self.read_frame(response)
            self.assertEqual(kind, b"D")
            self.assertEqual(final["audio"]["bytes"], 4096)
            self.assertIn("first_audio", final["timings_ms"])
            self.assertEqual(len(self.engine.recent_history("stream-box")), 1)
            self.assertEqual(response.read(), b"")
        finally:
            connection.close()

    def test_partial_tts_failure_is_terminal_error_and_not_complete_history(self):
        self.provider.fail = True
        self.provider.release.set()
        connection, response = self.connect()
        try:
            self.assertEqual(response.read(4), b"LXS1")
            self.assertEqual(self.read_frame(response)[0], b"J")
            self.assertEqual(self.read_frame(response)[0], b"A")
            kind, error = self.read_frame(response)
            self.assertEqual(kind, b"E")
            self.assertEqual(error["code"], "tts_failed")
            self.assertNotIn(self.provider.api_key, json.dumps(error))
            self.assertEqual(self.engine.recent_history("stream-box"), [])
        finally:
            connection.close()

    def test_close_frees_provider_and_concurrency_slot(self):
        service = self.server.companion
        stream = stream_conversation(service, "cancel-box", text="你好")
        self.assertEqual(next(stream)[0], b"J")
        self.assertEqual(next(stream)[0], b"A")
        stream.close()
        self.assertTrue(self.provider.closed)
        self.assertTrue(service._slots.acquire(blocking=False))
        self.assertTrue(service._slots.acquire(blocking=False))
        self.assertFalse(service._slots.acquire(blocking=False))
        service._slots.release(); service._slots.release()

    def test_audio_is_capped_and_large_provider_blocks_are_split(self):
        self.provider.iter_synthesize_pcm = lambda *a, **k: iter([b"\1\0" * (MAX_OUTPUT_BYTES // 2 + 10)])
        events = list(stream_conversation(self.server.companion, "long-box", text="你好"))
        blocks = [payload for kind, payload in events if kind == b"A"]
        self.assertEqual(sum(map(len, blocks)), MAX_OUTPUT_BYTES)
        self.assertTrue(all(len(block) <= 4096 for block in blocks))
        self.assertTrue(events[-1][1]["truncated"])

    def test_bad_frame_and_invalid_text_rejected(self):
        with self.assertRaises(ConversationServiceError):
            encode_frame(b"A", b"x" * 4097)
        with self.assertRaises(ConversationServiceError):
            list(stream_conversation(self.server.companion, "valid-box", text=None))


if __name__ == "__main__":
    unittest.main()
