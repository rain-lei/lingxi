"""Small standard-library client for StepFun Step Plan text, vision and audio APIs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from http.client import HTTPException
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.stepfun.com/step_plan/v1"
# Only pass effort controls documented by the upstream API for these models.
# https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create
REASONING_EFFORTS = {
    "step-3.7-flash": {"low", "medium", "high"},
    "step-5-preview": {"low", "medium", "high"},
    "step-3.5-flash-2603": {"low", "high"},
}


class StepFunError(RuntimeError):
    """A sanitized upstream error safe to show in local demo logs."""


class StepFunClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 45,
        opener: Callable[..., Any] = urlopen,
        audio_base_url: str | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.audio_base_url = (audio_base_url or base_url).rstrip("/")
        self.timeout = timeout
        self._opener = opener
        self.chat_model = os.getenv("STEPFUN_CHAT_MODEL", "step-3.7-flash")
        # Step 3.7 Flash has native image understanding. A dedicated vision
        # model can still be selected later with STEPFUN_VISION_MODEL.
        self.vision_model = os.getenv("STEPFUN_VISION_MODEL", self.chat_model)
        self.tts_model = "stepaudio-2.5-tts"
        self.asr_model = "stepaudio-2.5-asr"
        self.voice = os.getenv("STEPFUN_TTS_VOICE", "cixingnansheng")

    @classmethod
    def from_environment(cls) -> "StepFunClient":
        return cls(
            api_key=os.getenv("STEPFUN_API_KEY"),
            base_url=os.getenv("STEPFUN_BASE_URL", DEFAULT_BASE_URL),
            timeout=float(os.getenv("STEPFUN_TIMEOUT", "45")),
            audio_base_url=os.getenv("STEPFUN_AUDIO_BASE_URL"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": "stepfun" if self.enabled else "mock",
            "chat": self.enabled,
            "asr": self.enabled,
            "tts": self.enabled,
            "vision": self.enabled,
            "models": {
                "chat": self.chat_model if self.enabled else "lingxi-mock",
                "vision": self.vision_model if self.enabled else None,
                "asr": self.asr_model if self.enabled else None,
                "tts": self.tts_model if self.enabled else "browser-speech",
            },
        }

    def stream_chat(
        self, messages: list[dict[str, Any]], *, reasoning_effort: str | None = None,
    ) -> Iterable[str]:
        has_image = any(
            isinstance(message.get("content"), list)
            and any(item.get("type") == "image_url" for item in message["content"])
            for message in messages
        )
        # Step 3 reasoning models allocate a shared reasoning/output budget.
        # Setting max_tokens can consume the whole budget before final content
        # is emitted, so the request intentionally leaves it unset.
        payload = {
            "model": self.vision_model if has_image else self.chat_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.45,
        }
        if reasoning_effort is not None:
            if reasoning_effort not in {"low", "medium", "high"}:
                raise StepFunError("推理强度必须为 low、medium 或 high")
            supported = REASONING_EFFORTS.get(payload["model"])
            if supported is not None:
                if reasoning_effort not in supported:
                    raise StepFunError("当前模型不支持所选推理强度")
                # Low reduces reasoning effort; it does not disable thinking.
                payload["reasoning_effort"] = reasoning_effort
        if not has_image:
            payload["modalities"] = ["text"]
        with self._open("/chat/completions", payload, accept="text/event-stream") as response:
            for event in self._iter_sse(response):
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)

    def synthesize(
        self, text: str, speech_rate: str, mode: str, *,
        voice: str | None = None, tone: str | None = None,
        language: str | None = None, response_format: str = "mp3",
        sample_rate: int = 24000, max_audio_bytes: int | None = None,
    ) -> tuple[bytes, str]:
        payload = self._speech_payload(
            text, speech_rate, mode, voice=voice, tone=tone, language=language,
            response_format=response_format, sample_rate=sample_rate,
        )
        default_type = {"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "audio/pcm"}[response_format]
        with self._open("/audio/speech", payload, accept=default_type) as response:
            audio = response.read() if max_audio_bytes is None else response.read(max_audio_bytes + 1)
            content_type = response.headers.get_content_type() if response.headers else default_type
        if max_audio_bytes is not None and len(audio) > max_audio_bytes:
            raise StepFunError("阶跃 TTS 音频超过设备接收上限，请缩短回复")
        if not audio:
            raise StepFunError("阶跃 TTS 返回了空音频")
        if content_type == "application/json":
            raise StepFunError("阶跃 TTS 未返回音频数据")
        return audio, content_type or default_type

    def iter_synthesize_pcm(
        self, text: str, speech_rate: str, mode: str, *,
        voice: str | None = None, tone: str | None = None,
        language: str | None = None, sample_rate: int = 16000,
        max_audio_bytes: int = 640000, chunk_size: int = 2048,
    ) -> Iterable[bytes]:
        """Yield PCM16LE mono as it arrives, without collecting the response.

        The explicit ``stream_format=audio`` selects the upstream streaming
        path. WAV is not supported on that path, so use the documented raw PCM
        format and requested rate instead of relabelling a WAV's native rate.
        A caller stopping early must close this generator (or use closing()).
        https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio
        """
        if not isinstance(chunk_size, int) or not 2 <= chunk_size <= 16384:
            raise StepFunError("TTS 流式音频分片大小无效")
        if not isinstance(max_audio_bytes, int) or max_audio_bytes < 2:
            raise StepFunError("TTS 流式音频接收上限无效")
        payload = self._speech_payload(
            text, speech_rate, mode, voice=voice, tone=tone, language=language,
            response_format="pcm", sample_rate=sample_rate,
        )
        payload["stream_format"] = "audio"
        received = 0
        pending = b""
        try:
            with self._open("/audio/speech", payload, accept="audio/pcm") as response:
                content_type = response.headers.get_content_type() if response.headers else ""
                # The production PCM stream uses application/octet-stream.
                # Reject JSON, text errors and encoded audio before playback.
                if content_type not in {"audio/pcm", "audio/x-pcm", "application/octet-stream"}:
                    raise StepFunError("阶跃流式 TTS 未返回 PCM 音频数据")
                # HTTPResponse.read(n) may wait for n bytes; read1 returns the
                # currently available transport chunk using one bounded read.
                read_chunk = getattr(response, "read1", response.read)
                while True:
                    chunk = read_chunk(chunk_size)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > max_audio_bytes:
                        raise StepFunError("阶跃 TTS 音频超过设备接收上限，请缩短回复")
                    combined = pending + chunk
                    aligned = len(combined) & ~1
                    pending = combined[aligned:]
                    if aligned:
                        yield combined[:aligned]
                if not received:
                    raise StepFunError("阶跃 TTS 返回了空音频")
                if pending:
                    raise StepFunError("阶跃 TTS 返回了不完整的 PCM 音频采样")
        except (URLError, TimeoutError, OSError, HTTPException) as error:
            raise StepFunError("阶跃流式 TTS 连接中断，请检查网络后重试") from error

    def _speech_payload(
        self, text: str, speech_rate: str, mode: str, *,
        voice: str | None, tone: str | None, language: str | None,
        response_format: str, sample_rate: int,
    ) -> dict[str, Any]:
        if not text or len(text) > 1000:
            raise StepFunError("TTS 文本长度必须在 1 到 1000 字符之间")
        speed = {"slow": 0.84, "normal": 1.0, "fast": 1.16}.get(speech_rate, 1.0)
        if response_format not in {"mp3", "wav", "pcm"}:
            raise StepFunError("不支持的 TTS 音频格式")
        if sample_rate not in {8000, 16000, 22050, 24000, 48000}:
            raise StepFunError("不支持的 TTS 采样率")
        instruction = self._tts_instruction(mode, speech_rate)
        tones = {
            "warm": "温柔亲切，真诚地陪伴和关心对方",
            "calm": "平静沉稳，低刺激，留出自然停顿",
            "cheerful": "轻快活泼，带自然笑意，不过度兴奋",
            "direct": "简洁清晰，利落自然，不过度抒情",
        }
        if tone in tones:
            instruction += "，" + tones[tone]
        if language in {"zh", "en"}:
            instruction += "，使用普通话" if language == "zh" else "，使用自然英语发音"
        return {
            "model": self.tts_model,
            "input": text,
            "voice": voice or self.voice,
            "response_format": response_format,
            "speed": speed,
            "sample_rate": sample_rate,
            "text_normalization": "standard",
            "instruction": instruction,
        }

    def transcribe_pcm(self, audio_base64: str, language: str = "zh") -> str:
        if not audio_base64:
            raise StepFunError("没有收到音频数据")
        payload = {
            "audio": {
                "data": audio_base64,
                "input": {
                    "transcription": {
                        "model": self.asr_model,
                        "language": language,
                        "hotwords": ["灵犀", "大连理工大学"],
                        "enable_itn": True,
                        "enable_timestamp": False,
                    },
                    "format": {
                        "type": "pcm",
                        "codec": "pcm_s16le",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1,
                    },
                },
            }
        }
        final_text = ""
        deltas: list[str] = []
        with self._open("/audio/asr/sse", payload, accept="text/event-stream") as response:
            for event in self._iter_sse(response):
                event_type = event.get("type")
                if event_type == "transcript.text.delta" and event.get("delta"):
                    deltas.append(str(event["delta"]))
                elif event_type == "transcript.text.done":
                    final_text = str(event.get("text") or "")
                elif event_type == "error":
                    raise StepFunError(str(event.get("message") or "阶跃 ASR 识别失败"))
        result = final_text.strip() or "".join(deltas).strip()
        if not result:
            raise StepFunError("没有识别到清晰语音")
        return result

    def _open(self, path: str, payload: dict[str, Any], accept: str):
        if not self.enabled:
            raise StepFunError("未配置 STEPFUN_API_KEY")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.audio_base_url if path.startswith('/audio/') else self.base_url}{path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": accept,
                "User-Agent": "LingXi-Pendant-Demo/0.2",
            },
        )
        try:
            return self._opener(request, timeout=self.timeout)
        except HTTPError as error:
            message = self._safe_error_message(error)
            raise StepFunError(f"阶跃 API 返回 HTTP {error.code}：{message}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise StepFunError("无法连接阶跃 API，请检查网络后重试") from error

    @staticmethod
    def _iter_sse(response: Any) -> Iterable[dict[str, Any]]:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError as error:
                raise StepFunError("阶跃 API 返回了无效的流式事件") from error
            if isinstance(event, dict):
                yield event

    @staticmethod
    def _safe_error_message(error: HTTPError) -> str:
        try:
            raw = error.read(32_000).decode("utf-8", errors="replace")
            payload = json.loads(raw)
            detail = payload.get("error", payload)
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("code")
            else:
                message = detail
            if message:
                return str(message)[:240]
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        return "上游请求失败"

    @staticmethod
    def _tts_instruction(mode: str, speech_rate: str) -> str:
        tone = {
            "assistant": "亲切、清晰、自然，像一个随身 AI 助手",
            "companion": "温暖、有耐心、有陪伴感，语气柔和",
            "translate": "发音清楚、语调自然，适合跨语言沟通",
        }.get(mode, "亲切、清晰、自然")
        pace = {"slow": "语速偏慢", "fast": "语速偏快", "normal": "语速自然"}.get(
            speech_rate, "语速自然"
        )
        return f"{tone}，{pace}，不夸张，不播报 Markdown 符号"
