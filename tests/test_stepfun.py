import io
import json
import os
import unittest
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import patch

from providers.stepfun import StepFunClient, StepFunError


class FakeResponse:
    def __init__(self, lines=None, body=b"", content_type="text/event-stream"):
        self._lines = [line.encode("utf-8") for line in (lines or [])]
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class StreamingResponse(FakeResponse):
    def __init__(self, chunks, content_type="application/octet-stream"):
        super().__init__(content_type=content_type)
        self.chunks = iter(chunks)
        self.read_sizes = []
        self.closed = False

    def read(self, *args):
        raise AssertionError("Streaming TTS must not perform a full response read")

    def read1(self, size):
        self.read_sizes.append(size)
        value = next(self.chunks, b"")
        if isinstance(value, Exception):
            raise value
        if len(value) > size:
            raise AssertionError("Invalid fake transport chunk")
        return value

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        return False


class StepFunClientTests(unittest.TestCase):
    def test_disabled_without_key(self) -> None:
        client = StepFunClient(api_key="")
        self.assertFalse(client.enabled)
        self.assertEqual(client.capabilities()["provider"], "mock")

    def test_environment_defaults_to_45_second_timeout(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = StepFunClient.from_environment()
        self.assertEqual(client.timeout, 45)

    def test_stream_chat_parses_sse_deltas(self) -> None:
        events = [
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": "你好"}, "finish_reason": ""}]},
                ensure_ascii=False,
            )
            + "\n",
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": "呀"}, "finish_reason": "stop"}]},
                ensure_ascii=False,
            )
            + "\n",
            "data: [DONE]\n",
        ]
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers["Authorization"]
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(lines=events)

        client = StepFunClient(api_key="secret", opener=opener)
        parts = list(client.stream_chat([{"role": "user", "content": "你好"}]))
        self.assertEqual(parts, ["你好", "呀"])
        self.assertTrue(captured["url"].endswith("/chat/completions"))
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertNotIn("max_tokens", captured["payload"])
        self.assertNotIn("reasoning_effort", captured["payload"])

    def test_low_effort_is_sent_only_for_documented_models(self) -> None:
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(lines=['data: {"choices":[{"delta":{"content":"你好"}}]}\n'])

        client = StepFunClient(api_key="secret", opener=opener)
        for model in ("step-3.7-flash", "step-5-preview", "step-3.5-flash-2603"):
            client.chat_model = model
            self.assertEqual(list(client.stream_chat([], reasoning_effort="low")), ["你好"])
            self.assertEqual(captured[-1]["reasoning_effort"], "low")
            self.assertNotIn("thinking", captured[-1])
            self.assertNotIn("enable_thinking", captured[-1])
        client.chat_model = "custom-model"
        list(client.stream_chat([], reasoning_effort="low"))
        self.assertNotIn("reasoning_effort", captured[-1])

    def test_effort_validation_rejects_unsupported_values_before_network(self) -> None:
        def opener(request, timeout):
            self.fail("invalid effort must not make a network request")

        client = StepFunClient(api_key="secret", opener=opener)
        with self.assertRaises(StepFunError):
            list(client.stream_chat([], reasoning_effort="none"))
        client.chat_model = "step-3.5-flash-2603"
        with self.assertRaises(StepFunError):
            list(client.stream_chat([], reasoning_effort="medium"))

    def test_vision_effort_uses_selected_model_capabilities(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse(lines=[])

        client = StepFunClient(api_key="secret", opener=opener)
        client.chat_model = "custom-model"
        client.vision_model = "step-3.7-flash"
        list(client.stream_chat([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]}], reasoning_effort="low"))
        self.assertEqual(captured["model"], "step-3.7-flash")
        self.assertEqual(captured["reasoning_effort"], "low")

    def test_vision_message_selects_vision_model(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(lines=['data: {"choices":[{"delta":{"content":"看到了"}}]}\n'])

        client = StepFunClient(api_key="secret", opener=opener)
        list(
            client.stream_chat(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "这是什么？"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                        ],
                    }
                ]
            )
        )
        self.assertEqual(captured["payload"]["model"], "step-3.7-flash")
        self.assertNotIn("max_tokens", captured["payload"])
        self.assertNotIn("modalities", captured["payload"])

    def test_capabilities_expose_step37_and_vision(self) -> None:
        client = StepFunClient(api_key="secret")
        capabilities = client.capabilities()
        self.assertEqual(capabilities["models"]["chat"], "step-3.7-flash")
        self.assertEqual(capabilities["models"]["vision"], "step-3.7-flash")
        self.assertTrue(capabilities["vision"])

    def test_transcribe_pcm_uses_done_text(self) -> None:
        events = [
            'data: {"type":"transcript.text.delta","delta":"灵犀"}\n',
            'data: {"type":"transcript.text.done","text":"灵犀你好"}\n',
            "data: [DONE]\n",
        ]
        client = StepFunClient(
            api_key="secret", opener=lambda request, timeout: FakeResponse(lines=events)
        )
        self.assertEqual(client.transcribe_pcm("AA=="), "灵犀你好")

    def test_synthesize_returns_audio_and_type(self) -> None:
        client = StepFunClient(
            api_key="secret",
            opener=lambda request, timeout: FakeResponse(
                body=b"ID3demo", content_type="audio/mpeg"
            ),
        )
        audio, content_type = client.synthesize("你好", "slow", "companion")
        self.assertEqual(audio, b"ID3demo")
        self.assertEqual(content_type, "audio/mpeg")

    def test_streaming_pcm_requests_native_format_and_yields_before_eof(self) -> None:
        captured = {}
        response = StreamingResponse([b"\x01\x00" * 512, b"\x02\x00" * 512])

        def opener(request, timeout):
            captured.update(json.loads(request.data.decode("utf8")))
            return response

        client = StepFunClient(api_key="secret", opener=opener)
        stream = client.iter_synthesize_pcm(
            "我在呢，先慢慢说。", "normal", "companion",
            voice="wenrounvsheng", tone="warm", language="zh",
        )
        self.assertEqual(next(stream), b"\x01\x00" * 512)
        self.assertEqual(response.read_sizes, [2048])
        self.assertFalse(response.closed)
        self.assertEqual(captured["response_format"], "pcm")
        self.assertEqual(captured["stream_format"], "audio")
        self.assertEqual(captured["sample_rate"], 16000)
        self.assertEqual(captured["voice"], "wenrounvsheng")
        self.assertEqual(list(stream), [b"\x02\x00" * 512])
        self.assertTrue(response.closed)

    def test_streaming_pcm_closes_response_when_consumer_aborts(self) -> None:
        response = StreamingResponse([b"\x01\x00" * 512] * 100)
        client = StepFunClient(api_key="secret", opener=lambda *a, **kw: response)
        stream = client.iter_synthesize_pcm("你好", "normal", "companion")
        next(stream)
        stream.close()
        self.assertTrue(response.closed)
        self.assertEqual(response.read_sizes, [2048])

    def test_streaming_pcm_carries_partial_samples_between_chunks(self) -> None:
        response = StreamingResponse([b"1", b"234", b"56"])
        client = StepFunClient(api_key="secret", opener=lambda *a, **kw: response)
        chunks = list(client.iter_synthesize_pcm("你好", "normal", "companion"))
        self.assertEqual(chunks, [b"1234", b"56"])
        self.assertTrue(all(len(chunk) % 2 == 0 for chunk in chunks))

    def test_streaming_pcm_rejects_truncated_sample_and_size_overflow(self) -> None:
        for chunks, limit in (([b"123"], 100), ([b"1234", b"5678"], 6)):
            with self.subTest(chunks=chunks, limit=limit):
                response = StreamingResponse(chunks)
                client = StepFunClient(api_key="secret", opener=lambda *a, **kw: response)
                with self.assertRaises(StepFunError):
                    list(client.iter_synthesize_pcm("你好", "normal", "companion", max_audio_bytes=limit))
                self.assertTrue(response.closed)

    def test_streaming_pcm_rejects_empty_or_non_pcm_responses(self) -> None:
        for content_type, chunks in (("application/octet-stream", []),
                                     ("text/plain", []),
                                     ("application/json", [b"{}"]),
                                     ("audio/wav", [b"RIFF"])):
            with self.subTest(content_type=content_type, chunks=chunks):
                response = StreamingResponse(chunks, content_type=content_type)
                client = StepFunClient(api_key="secret", opener=lambda *a, **kw: response)
                with self.assertRaises(StepFunError):
                    list(client.iter_synthesize_pcm("你好", "normal", "companion"))
                self.assertTrue(response.closed)

    def test_streaming_pcm_sanitizes_midstream_network_failure(self) -> None:
        for failure in (TimeoutError("sensitive transport detail"), IncompleteRead(b"sensitive")):
            with self.subTest(error=type(failure).__name__):
                response = StreamingResponse([b"12", failure])
                client = StepFunClient(api_key="secret", opener=lambda *a, **kw: response)
                stream = client.iter_synthesize_pcm("你好", "normal", "companion")
                self.assertEqual(next(stream), b"12")
                with self.assertRaises(StepFunError) as raised:
                    next(stream)
                self.assertNotIn("sensitive", str(raised.exception))
                self.assertTrue(response.closed)

    def test_streaming_pcm_validates_before_opening_connection(self) -> None:
        def opener(*args, **kwargs):
            self.fail("Invalid PCM options must not reach the network")

        client = StepFunClient(api_key="secret", opener=opener)
        for options in ({"chunk_size": 0}, {"chunk_size": 20000},
                        {"max_audio_bytes": 1}, {"sample_rate": 12345}):
            with self.subTest(options=options), self.assertRaises(StepFunError):
                list(client.iter_synthesize_pcm("你好", "normal", "companion", **options))


if __name__ == "__main__":
    unittest.main()
