"""Bounded LXS1 voice frames, played as they arrive by the browser and BOX.

This protocol is opt-in. LXI1 remains available for older firmware. Audio is
real provider output; a progress event is never counted as first audio.
"""

from __future__ import annotations

import base64
import json
import struct
import time
from typing import Iterator

from conversation_service import (
    ConversationServiceError, MAX_INPUT_BYTES, MAX_METADATA_BYTES,
    MAX_OUTPUT_BYTES, SAMPLE_RATE, validate_device_id,
)
from providers.stepfun import StepFunError

STREAM_MIME = "application/vnd.lingxi.voice-stream"
MAX_AUDIO_FRAME = 4096


def encode_frame(kind: bytes, payload: dict | bytes) -> bytes:
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    limit = MAX_AUDIO_FRAME if kind == b"A" else MAX_METADATA_BYTES
    if kind not in {b"J", b"A", b"D", b"E"} or len(payload) > limit:
        raise ConversationServiceError("流式回复帧大小异常", 502, "response_too_large")
    return kind + struct.pack("<I", len(payload)) + payload


def stream_conversation(service, device_id: str, *, text: str | None = None,
                        pcm: bytes | None = None) -> Iterator[tuple[bytes, dict | bytes]]:
    """Yield metadata, PCM, then an explicit terminal event; always free slot.

    The handler primes this generator before sending HTTP 200, so input/ASR/
    chat errors retain their HTTP status. TTS errors after headers become E.
    """
    validate_device_id(device_id)
    if pcm is not None:
        if not isinstance(pcm, bytes) or len(pcm) % 2 or len(pcm) < 6400:
            raise ConversationServiceError("请提供至少 0.2 秒的 16kHz 单声道 PCM16 录音", 400, "invalid_pcm")
        if len(pcm) > MAX_INPUT_BYTES:
            raise ConversationServiceError("单次录音最长 10 秒", 413, "audio_too_long")
        if max(abs(v[0]) for v in struct.iter_unpack("<h", pcm)) < 8:
            raise ConversationServiceError("录音中没有可识别的声音，请靠近麦克风重试", 422, "silent_audio")
    else:
        service._validate_text(text)
    provider = service._provider()
    if not service._slots.acquire(blocking=False):
        raise ConversationServiceError("正在处理其他对话，请稍后重试", 429, "busy")
    started = time.monotonic()
    try:
        settings = service.get_settings(device_id)
        asr_ms = 0
        if pcm is not None:
            asr_started = time.monotonic()
            language = settings["language"]
            if settings["mode"] == "translate":
                language = "zh" if language == "en" else "en"
            try:
                text = provider.transcribe_pcm(base64.b64encode(pcm).decode("ascii"), language=language)
            except (StepFunError, TimeoutError, OSError) as error:
                raise service._upstream_error(error, provider, "asr_failed", "语音识别失败") from error
            asr_ms = round((time.monotonic() - asr_started) * 1000)
        metadata, _ = service._converse(device_id, text.strip(), settings, provider, False, started, asr_ms, record=False, input_source='voice' if pcm is not None else 'text')
        metadata["streaming"] = True
        yield b"J", metadata
        tts_started = time.monotonic()
        total_bytes = 0
        first_audio = None
        truncated = False
        audio_stream = None
        try:
            audio_stream = iter(provider.iter_synthesize_pcm(
                metadata["reply"], settings["speech_rate"], settings["mode"],
                voice=settings["voice"], tone=settings["tone"], language=settings["language"],
                sample_rate=SAMPLE_RATE, max_audio_bytes=MAX_OUTPUT_BYTES + MAX_AUDIO_FRAME,
            ))
            for block in audio_stream:
                if not isinstance(block, bytes) or len(block) % 2:
                    raise StepFunError("流式语音须为完整的 PCM16 采样")
                available = MAX_OUTPUT_BYTES - total_bytes
                if len(block) > available:
                    block = block[:available]
                    truncated = True
                for offset in range(0, len(block), MAX_AUDIO_FRAME):
                    chunk = block[offset:offset + MAX_AUDIO_FRAME]
                    if first_audio is None:
                        first_audio = round((time.monotonic() - started) * 1000)
                    total_bytes += len(chunk)
                    yield b"A", chunk
                if truncated:
                    break
            if total_bytes == 0:
                raise StepFunError("语音服务返回了空音频")
        except (StepFunError, TimeoutError, OSError) as error:
            raise service._upstream_error(error, provider, "tts_failed", "语音合成失败") from error
        finally:
            if audio_stream is not None:
                close = getattr(audio_stream, "close", None)
                if close:
                    close()
        metadata["audio"].update(bytes=total_bytes, duration_ms=total_bytes * 1000 // (SAMPLE_RATE * 2))
        metadata["truncated"] = truncated
        timings = metadata["timings_ms"]
        timings["tts"] = round((time.monotonic() - tts_started) * 1000)
        timings["first_audio"] = first_audio
        service.record_result(device_id, metadata)
        timings["total"] = round((time.monotonic() - started) * 1000)
        metadata["elapsed_ms"] = timings["total"]
        print("companion stream timings_ms=" + json.dumps(timings, separators=(",", ":")) + f" pcm_bytes={total_bytes}", flush=True)
        yield b"D", metadata
    finally:
        service._slots.release()
