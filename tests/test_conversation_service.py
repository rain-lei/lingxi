import base64
import io
import json
import struct
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from conversation_service import (
    DEFAULT_SETTINGS, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
    ConversationServiceError, HardwareConversationService, wav_to_pcm16,
)
from providers.stepfun import StepFunClient, StepFunError
from server import DemoEngine


def wav_data(samples=None, rate=16000, channels=1, frames=None):
    samples = samples if samples is not None else [1000, -1000] * 1600
    if frames is not None:
        samples = [1000] * frames * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setframerate(rate)
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return buffer.getvalue()


class FakeProvider:
    enabled = True
    api_key = "private-key-do-not-expose"

    def __init__(self):
        self.messages = []
        self.tts_options = {}
        self.transcript = "今天实验又失败了，有点难过"
        self.reply = "失败几次真的会沮丧。我陪你一起看看，先从最小的一步开始，好吗？"
        self.wav = wav_data()
        self.calls = []

    def transcribe_pcm(self, audio, language="zh"):
        self.calls.append("asr")
        self.input_pcm = base64.b64decode(audio)
        self.input_language = language
        return self.transcript

    def stream_chat(self, messages, *, reasoning_effort=None):
        self.calls.append("chat")
        self.messages = messages
        self.reasoning_effort = reasoning_effort
        yield self.reply[:10]
        yield self.reply[10:]

    def synthesize(self, text, speech_rate, mode, **kwargs):
        self.calls.append("tts")
        self.tts_text = text
        self.tts_options = dict(kwargs, speech_rate=speech_rate, mode=mode)
        return self.wav, "audio/wav"


class HardwareConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = FakeProvider()
        self.engine = DemoEngine(Path(self.temp_dir.name) / "test.sqlite3", stepfun=self.provider)
        self.service = HardwareConversationService(self.engine)
        self.device = "box-aabbccddeeff"
        self.pcm = struct.pack("<h", 300) * 4000

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_real_pipeline_order_and_raw_audio(self):
        metadata, pcm = self.service.converse_pcm(self.device, self.pcm)
        self.assertEqual(self.provider.calls, ["asr", "chat", "tts"])
        self.assertEqual(self.provider.input_pcm, self.pcm)
        self.assertEqual(metadata["transcript"], self.provider.transcript)
        self.assertEqual(metadata["reply"], self.provider.reply)
        self.assertEqual(pcm, struct.pack("<hh", 1000, -1000) * 1600)
        self.assertEqual(metadata["audio"]["sample_rate"], 16000)
        self.assertFalse(metadata["truncated"])
        self.assertEqual(metadata["provider"], "stepfun")
        self.assertEqual(self.provider.reasoning_effort, "low")
        self.assertEqual(self.engine.recent_history(self.device)[0]["assistant_text"], self.provider.reply)

    def test_stage_timings_measure_actual_work_without_logging_content(self):
        now = [100.0]
        original_asr = self.provider.transcribe_pcm
        original_chat = self.provider.stream_chat
        original_tts = self.provider.synthesize
        original_record = self.engine.record_interaction

        def timed_asr(*args, **kwargs):
            now[0] += 0.12
            return original_asr(*args, **kwargs)

        def timed_chat(*args, **kwargs):
            now[0] += 0.06
            yield ""  # An empty stream event is not the first output token.
            now[0] += 0.04
            chunks = iter(original_chat(*args, **kwargs))
            yield next(chunks)
            now[0] += 0.1
            yield from chunks

        def timed_tts(*args, **kwargs):
            now[0] += 0.3
            return original_tts(*args, **kwargs)

        def timed_record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            now[0] += 0.05
            return result

        output = io.StringIO()
        with patch("conversation_service.time.monotonic", side_effect=lambda: now[0]), \
                patch.object(self.provider, "transcribe_pcm", side_effect=timed_asr), \
                patch.object(self.provider, "stream_chat", side_effect=timed_chat), \
                patch.object(self.provider, "synthesize", side_effect=timed_tts), \
                patch.object(self.engine, "record_interaction", side_effect=timed_record), \
                redirect_stdout(output):
            metadata, pcm = self.service.converse_pcm(self.device, self.pcm)
        self.assertEqual(metadata["timings_ms"], {
            "asr": 120, "chat_first_token": 100, "chat": 200,
            "tts": 300, "total": 670,
        })
        self.assertEqual(metadata["elapsed_ms"], 670)
        diagnostic = output.getvalue()
        self.assertEqual(len(diagnostic.splitlines()), 1)
        self.assertIn(f"pcm_bytes={len(pcm)}", diagnostic)
        for private in (self.device, self.provider.transcript, self.provider.reply, self.provider.api_key):
            self.assertNotIn(private, diagnostic)

    def test_spoken_prompt_prefers_short_turns_without_cutting_model_reply(self):
        self.provider.reply = "这是模型完整返回的一段话。" * 6
        metadata, _ = self.service.converse_text(self.device, "请详细解释")
        prompt = self.provider.messages[0]["content"]
        self.assertIn("一到两句", prompt)
        self.assertIn("20–45 字", prompt)
        self.assertIn("不超过 25 词", prompt)
        self.assertNotIn("最多 65 字", prompt)
        self.assertEqual(metadata["reply"], self.provider.reply)
        self.assertEqual(self.provider.tts_text, self.provider.reply)

    def test_selected_voice_tone_language_and_history_reach_models(self):
        self.engine.record_interaction(self.device, "companion", "我在做电路实验", "慢慢来，我在听。")
        settings = self.service.update_settings(self.device, {
            "voice": "cixingnansheng", "tone": "calm", "language": "en",
            "avatar": "robot", "speech_rate": "slow", "persona": "mentor",
        })
        metadata, _ = self.service.converse_text(self.device, "I'm sad")
        self.assertEqual(metadata["settings"], settings)
        self.assertEqual(self.provider.tts_options["voice"], "cixingnansheng")
        self.assertEqual(self.provider.tts_options["tone"], "calm")
        self.assertEqual(self.provider.tts_options["language"], "en")
        self.assertEqual(self.provider.tts_options["response_format"], "wav")
        self.assertEqual(self.provider.tts_options["sample_rate"], 16000)
        self.assertEqual(self.provider.tts_options["speech_rate"], "slow")
        self.assertIn("English", self.provider.messages[0]["content"])
        self.assertIn("耐心的学长", self.provider.messages[0]["content"])
        self.assertIn({"role": "user", "content": "我在做电路实验"}, self.provider.messages)

    def test_settings_persist_per_device_and_partial_updates_merge(self):
        self.service.update_settings(self.device, {"avatar": "robot"})
        other = HardwareConversationService(self.engine)
        saved = other.update_settings(self.device, {"voice": "yuanqishaonv"})
        self.assertEqual(saved["avatar"], "robot")
        self.assertEqual(saved["voice"], "yuanqishaonv")
        self.assertEqual(other.get_settings("other-device"), DEFAULT_SETTINGS)

    def test_unsupported_setting_is_rejected_without_losing_prior_values(self):
        for invalid in ({"voice": "invented-voice"}, {"tone": "angry"}, {"language": "ja"}, {"secret": "value"}, {"mode": []}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ConversationServiceError):
                    self.service.update_settings(self.device, invalid)
        self.assertEqual(self.service.get_settings(self.device), DEFAULT_SETTINGS)

    def test_no_provider_does_not_return_canned_success(self):
        self.provider.enabled = False
        with self.assertRaises(ConversationServiceError) as caught:
            self.service.converse_text(self.device, "安慰一下我")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, "provider_not_configured")
        self.assertEqual(self.engine.recent_history(self.device), [])

    def test_provider_is_read_after_configuration_change(self):
        self.engine.stepfun = StepFunClient()
        self.assertFalse(self.service.catalog()["enabled"])
        self.engine.stepfun = self.provider
        self.assertTrue(self.service.catalog()["enabled"])
        metadata, _ = self.service.converse_text(self.device, "你好", speak=False)
        self.assertEqual(metadata["reply"], self.provider.reply)

    def test_input_limits_and_silence_rejected_before_billable_asr(self):
        for pcm in (b"", b"\x01" * 6401, b"\0" * 6400, self.pcm[:1000], b"\x01\0" * (MAX_INPUT_BYTES // 2 + 1)):
            with self.subTest(length=len(pcm)):
                with self.assertRaises(ConversationServiceError):
                    self.service.converse_pcm(self.device, pcm)
        self.assertEqual(self.provider.calls, [])

    def test_translate_uses_opposite_source_language(self):
        self.service.update_settings(self.device, {"mode": "translate", "language": "en"})
        self.service.converse_pcm(self.device, self.pcm)
        self.assertEqual(self.provider.input_language, "zh")
        self.assertIn("只给出自然译文", self.provider.messages[0]["content"])

    def test_exact_ten_second_recording_is_accepted(self):
        pcm = struct.pack("<h", 300) * 160000
        self.assertEqual(MAX_INPUT_BYTES, len(pcm))
        metadata, _ = self.service.converse_pcm(self.device, pcm)
        self.assertEqual(self.provider.input_pcm, pcm)
        self.assertEqual(metadata["transcript"], self.provider.transcript)
        self.assertEqual(self.service.catalog()["limits"]["input_seconds"], 10)

    def test_text_only_skips_tts_and_still_saves_history(self):
        metadata, pcm = self.service.converse_text(self.device, "你好", speak=False)
        self.assertEqual(self.provider.calls, ["chat"])
        self.assertEqual(pcm, b"")
        self.assertEqual(metadata["audio"]["bytes"], 0)
        self.assertEqual(metadata["timings_ms"]["asr"], 0)
        self.assertEqual(metadata["timings_ms"]["tts"], 0)
        self.assertTrue(all(type(value) is int and value >= 0 for value in metadata["timings_ms"].values()))
        self.assertEqual(len(self.engine.recent_history(self.device)), 1)

    def test_failed_asr_is_explicit_and_never_calls_chat(self):
        def failing(*args, **kwargs):
            raise StepFunError("权限不足")
        self.provider.transcribe_pcm = failing
        with self.assertRaises(ConversationServiceError) as caught:
            self.service.converse_pcm(self.device, self.pcm)
        self.assertEqual(caught.exception.code, "asr_failed")
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(self.provider.calls, [])

    def test_upstream_error_redacts_key_and_releases_slot(self):
        def failing(*args, **kwargs):
            raise StepFunError("bad " + self.provider.api_key)
        self.provider.synthesize = failing
        for _ in range(3):
            with self.assertRaises(ConversationServiceError) as caught:
                self.service.converse_text(self.device, "你好")
            self.assertEqual(caught.exception.code, "tts_failed")
            self.assertNotIn(self.provider.api_key, str(caught.exception))
        self.assertEqual(self.engine.recent_history(self.device), [])

    def test_non_wav_audio_is_not_returned_as_pcm(self):
        self.provider.wav = b"ID3this-is-mp3"
        with self.assertRaises(ConversationServiceError) as caught:
            self.service.converse_text(self.device, "你好")
        self.assertEqual(caught.exception.code, "invalid_audio")

    def test_long_reply_audio_is_bounded_and_disclosed(self):
        self.provider.wav = wav_data(rate=24000, frames=24000 * 21)
        metadata, pcm = self.service.converse_text(self.device, "你好")
        self.assertEqual(len(pcm), MAX_OUTPUT_BYTES)
        self.assertTrue(metadata["truncated"])
        self.assertEqual(pcm[-2:], b"\0\0")

    def test_busy_request_fails_before_upstream(self):
        self.service._slots.acquire()
        self.service._slots.acquire()
        try:
            with self.assertRaises(ConversationServiceError) as caught:
                self.service.converse_text(self.device, "你好")
            self.assertEqual(caught.exception.status, 429)
            self.assertEqual(self.provider.calls, [])
        finally:
            self.service._slots.release()
            self.service._slots.release()

    def test_device_id_cannot_inject_sql_or_create_unbounded_keys(self):
        for device_id in ("x' OR 1=1", "x" * 81, "", None):
            with self.assertRaises(ConversationServiceError):
                self.service.get_settings(device_id)


class WavConversionTests(unittest.TestCase):
    def test_24k_stereo_downmix_and_resample(self):
        audio = wav_data([1000, 3000, 2000, 4000, 3000, 5000, 4000, 6000, 5000, 7000, 6000, 8000], rate=24000, channels=2)
        pcm, clipped = wav_to_pcm16(audio)
        self.assertEqual(struct.unpack("<hhhh", pcm), (2000, 3500, 5000, 6500))
        self.assertFalse(clipped)

    def test_bad_wav_and_missing_samples_are_rejected(self):
        valid = wav_data()
        for audio in (b"not-wav", valid[:-10], wav_data(samples=[])):
            with self.assertRaises(ConversationServiceError):
                wav_to_pcm16(audio)


class StepFunDeviceSpeechTests(unittest.TestCase):
    class Response:
        def __init__(self, body):
            self.body = body
            self.headers = Message()
            self.headers["Content-Type"] = "audio/wav"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit=None):
            return self.body if limit is None else self.body[:limit]

    def test_voice_tone_format_and_audio_route_are_forwarded(self):
        captured = {}
        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            return self.Response(wav_data())
        client = StepFunClient("secret", opener=opener, audio_base_url="https://api.stepfun.com/v1")
        client.synthesize("你好", "slow", "companion", voice="wenrounvsheng", tone="calm", language="en", response_format="wav", sample_rate=16000, max_audio_bytes=4000000)
        self.assertEqual(captured["url"], "https://api.stepfun.com/v1/audio/speech")
        self.assertEqual(captured["body"]["voice"], "wenrounvsheng")
        self.assertEqual(captured["body"]["response_format"], "wav")
        self.assertEqual(captured["body"]["sample_rate"], 16000)
        self.assertIn("英语", captured["body"]["instruction"])
        self.assertIn("平静", captured["body"]["instruction"])

    def test_upstream_audio_bytes_are_bounded_at_read(self):
        client = StepFunClient("secret", opener=lambda *args, **kwargs: self.Response(b"x" * 100))
        with self.assertRaises(StepFunError):
            client.synthesize("你好", "normal", "companion", max_audio_bytes=20)


if __name__ == "__main__":
    unittest.main()
