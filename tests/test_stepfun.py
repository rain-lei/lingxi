import io
import json
import unittest
from email.message import Message

from providers.stepfun import StepFunClient


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


class StepFunClientTests(unittest.TestCase):
    def test_disabled_without_key(self) -> None:
        client = StepFunClient(api_key="")
        self.assertFalse(client.enabled)
        self.assertEqual(client.capabilities()["provider"], "mock")

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
            return FakeResponse(lines=events)

        client = StepFunClient(api_key="secret", opener=opener)
        parts = list(client.stream_chat([{"role": "user", "content": "你好"}]))
        self.assertEqual(parts, ["你好", "呀"])
        self.assertTrue(captured["url"].endswith("/chat/completions"))
        self.assertEqual(captured["authorization"], "Bearer secret")

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
        self.assertEqual(captured["payload"]["model"], "step-1o-turbo-vision")

    def test_capabilities_expose_step37_and_vision(self) -> None:
        client = StepFunClient(api_key="secret")
        capabilities = client.capabilities()
        self.assertEqual(capabilities["models"]["chat"], "step-3.7-flash")
        self.assertEqual(capabilities["models"]["vision"], "step-1o-turbo-vision")
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


if __name__ == "__main__":
    unittest.main()
