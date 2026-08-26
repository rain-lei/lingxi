"""Small standard-library client for StepFun Step Plan text, vision and audio APIs."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.stepfun.com/step_plan/v1"


class StepFunError(RuntimeError):
    """A sanitized upstream error safe to show in local demo logs."""


class StepFunClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 45,
        opener: Callable[..., Any] = urlopen,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener
        self.chat_model = os.getenv("STEPFUN_CHAT_MODEL", "step-3.7-flash")
        self.vision_model = os.getenv("STEPFUN_VISION_MODEL", "step-1o-turbo-vision")
        self.tts_model = "stepaudio-2.5-tts"
        self.asr_model = "stepaudio-2.5-asr"
        self.voice = os.getenv("STEPFUN_TTS_VOICE", "cixingnansheng")

    @classmethod
    def from_environment(cls) -> "StepFunClient":
        return cls(
            api_key=os.getenv("STEPFUN_API_KEY"),
            base_url=os.getenv("STEPFUN_BASE_URL", DEFAULT_BASE_URL),
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

    def stream_chat(self, messages: list[dict[str, Any]]) -> Iterable[str]:
        has_image = any(
            isinstance(message.get("content"), list)
            and any(item.get("type") == "image_url" for item in message["content"])
            for message in messages
        )
        payload = {
            "model": self.vision_model if has_image else self.chat_model,
            "modalities": ["text"],
            "messages": messages,
            "stream": True,
            "max_tokens": 180,
            "temperature": 0.45,
        }
        with self._open("/chat/completions", payload, accept="text/event-stream") as response:
            for event in self._iter_sse(response):
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield str(content)

    def synthesize(self, text: str, speech_rate: str, mode: str) -> tuple[bytes, str]:
        if not text or len(text) > 1000:
            raise StepFunError("TTS 文本长度必须在 1 到 1000 字符之间")
        speed = {"slow": 0.84, "normal": 1.0, "fast": 1.16}.get(speech_rate, 1.0)
        instruction = self._tts_instruction(mode, speech_rate)
        payload = {
            "model": self.tts_model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
            "speed": speed,
            "sample_rate": 24000,
            "text_normalization": "standard",
            "instruction": instruction,
        }
        with self._open("/audio/speech", payload, accept="audio/mpeg") as response:
            audio = response.read()
            content_type = response.headers.get_content_type() if response.headers else "audio/mpeg"
        if not audio:
            raise StepFunError("阶跃 TTS 返回了空音频")
        if content_type == "application/json":
            raise StepFunError("阶跃 TTS 未返回音频数据")
        return audio, content_type or "audio/mpeg"

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
            f"{self.base_url}{path}",
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
