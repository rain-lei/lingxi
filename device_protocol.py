"""Versioned LingXi device event protocol shared by firmware and console tools."""

from __future__ import annotations

import base64
import math
import re
import threading
import time
from typing import Any


PROTOCOL_VERSION = "0.4-draft"
DEVICE_STATES = ("idle", "listening", "thinking", "speaking", "offline", "error")
UPSTREAM_EVENTS = (
    "device.hello",
    "device.heartbeat",
    "input.begin",
    "audio.chunk",
    "input.end",
    "playback.done",
)
DOWNSTREAM_EVENTS = (
    "event.ack",
    "session.state",
    "transcript.partial",
    "transcript.final",
    "reply.delta",
    "reply.done",
    "audio.chunk",
    "memory.updated",
    "error",
)
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class DeviceProtocolError(ValueError):
    """Raised when a device event cannot safely enter the orchestrator."""


class DeviceSessionRegistry:
    """Track authenticated device sessions and enforce monotonic event order."""

    def __init__(self, max_sessions: int = 256) -> None:
        self.max_sessions = max(1, max_sessions)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def accept(self, event: dict[str, Any]) -> dict[str, Any]:
        device_id = str(event["device_id"])
        event_type = str(event["type"])
        seq = int(event["seq"])
        now_ms = int(time.time() * 1000)

        with self._lock:
            previous = self._sessions.get(device_id)
            if event_type == "device.hello":
                session = {
                    "state": "idle",
                    "last_seq": seq,
                    "last_event": event_type,
                    "connected_at_ms": now_ms,
                    "last_seen_at_ms": now_ms,
                    "firmware": event["payload"]["firmware"],
                    "capabilities": list(event["payload"]["capabilities"]),
                }
            else:
                if previous is None:
                    raise DeviceProtocolError("device.hello is required before session events")
                if seq <= int(previous["last_seq"]):
                    raise DeviceProtocolError("seq must increase monotonically within the session")
                session = dict(previous)
                session["last_seq"] = seq
                session["last_event"] = event_type
                session["last_seen_at_ms"] = now_ms
                if event_type in {"input.begin", "audio.chunk"}:
                    session["state"] = "listening"
                elif event_type == "input.end":
                    session["state"] = "thinking"
                elif event_type == "playback.done":
                    session["state"] = "idle"

            self._sessions[device_id] = session
            if len(self._sessions) > self.max_sessions:
                oldest_device = min(
                    self._sessions,
                    key=lambda key: int(self._sessions[key]["last_seen_at_ms"]),
                )
                if oldest_device != device_id:
                    self._sessions.pop(oldest_device, None)
            return dict(session)


def protocol_manifest() -> dict[str, Any]:
    """Return a machine-readable manifest suitable for firmware generation."""
    return {
        "version": PROTOCOL_VERSION,
        "status": "draft-ready-for-device-integration",
        "transport": {
            "preferred": "websocket",
            "validation_endpoint": "/api/device/events",
            "authentication": "Bearer device token",
        },
        "audio": {
            "encoding": "pcm_s16le",
            "sample_rate": 16_000,
            "bits": 16,
            "channels": 1,
            "recommended_chunk_ms": 40,
        },
        "states": list(DEVICE_STATES),
        "upstream_events": list(UPSTREAM_EVENTS),
        "downstream_events": list(DOWNSTREAM_EVENTS),
        "envelope": {
            "required": ["version", "type", "device_id", "seq", "timestamp_ms", "payload"],
            "sequence": "monotonic per device connection",
            "timestamp": "Unix epoch milliseconds",
        },
        "payloads": {
            "device.hello": {
                "required": ["firmware", "capabilities"],
                "capabilities_max_items": 16,
            },
            "device.heartbeat": {
                "required": ["battery_percent", "rssi_dbm"],
            },
            "input.begin": {
                "required": ["mode"],
                "mode": ["assistant", "companion", "translate"],
            },
            "audio.chunk": {
                "required": ["encoding", "sample_rate", "data"],
                "max_decoded_bytes": 65_536,
            },
            "input.end": {
                "required": ["reason"],
                "reason": ["released", "cancelled", "timeout"],
            },
            "playback.done": {
                "optional": ["duration_ms"],
            },
        },
    }


def validate_device_event(event: Any) -> dict[str, Any]:
    """Validate and normalize one JSON device event envelope."""
    if not isinstance(event, dict):
        raise DeviceProtocolError("device event must be a JSON object")

    version = str(event.get("version", ""))
    if version != PROTOCOL_VERSION:
        raise DeviceProtocolError(f"unsupported protocol version: {version or 'missing'}")

    event_type = str(event.get("type", ""))
    if event_type not in UPSTREAM_EVENTS:
        raise DeviceProtocolError("unsupported device event type")

    device_id = str(event.get("device_id", ""))
    if not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise DeviceProtocolError("invalid device_id")

    seq = event.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq <= 2_147_483_647:
        raise DeviceProtocolError("seq must be an unsigned 31-bit integer")

    timestamp_ms = event.get("timestamp_ms")
    if (
        not isinstance(timestamp_ms, int)
        or isinstance(timestamp_ms, bool)
        or timestamp_ms < 1_600_000_000_000
    ):
        raise DeviceProtocolError("timestamp_ms must be a Unix epoch timestamp in milliseconds")

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise DeviceProtocolError("payload must be a JSON object")

    _validate_event_payload(event_type, payload)
    return {
        "version": version,
        "type": event_type,
        "device_id": device_id,
        "seq": seq,
        "timestamp_ms": timestamp_ms,
        "payload": payload,
    }


def _validate_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "device.hello":
        firmware = payload.get("firmware")
        capabilities = payload.get("capabilities")
        if not isinstance(firmware, str) or not 1 <= len(firmware) <= 64:
            raise DeviceProtocolError("device.hello requires firmware")
        if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 16 or not all(
            isinstance(item, str) and 1 <= len(item) <= 32 for item in capabilities
        ):
            raise DeviceProtocolError("device.hello requires string capabilities")
        if len(set(capabilities)) != len(capabilities):
            raise DeviceProtocolError("device.hello capabilities must be unique")
        return

    if event_type == "device.heartbeat":
        battery = payload.get("battery_percent")
        rssi = payload.get("rssi_dbm")
        if (
            not isinstance(battery, (int, float))
            or isinstance(battery, bool)
            or not math.isfinite(battery)
            or not 0 <= battery <= 100
        ):
            raise DeviceProtocolError("heartbeat battery_percent must be between 0 and 100")
        if (
            not isinstance(rssi, (int, float))
            or isinstance(rssi, bool)
            or not math.isfinite(rssi)
            or not -140 <= rssi <= 0
        ):
            raise DeviceProtocolError("heartbeat rssi_dbm must be between -140 and 0")
        return

    if event_type == "input.begin":
        if payload.get("mode") not in {"assistant", "companion", "translate"}:
            raise DeviceProtocolError("input.begin mode is unsupported")
        return

    if event_type == "audio.chunk":
        if payload.get("encoding") != "pcm_s16le" or payload.get("sample_rate") != 16_000:
            raise DeviceProtocolError("audio.chunk must use 16 kHz pcm_s16le")
        encoded = payload.get("data")
        if not isinstance(encoded, str) or not encoded or len(encoded) > 120_000:
            raise DeviceProtocolError("audio.chunk data is missing or too large")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError) as error:
            raise DeviceProtocolError("audio.chunk data must be valid base64") from error
        if not audio or len(audio) > 64 * 1024:
            raise DeviceProtocolError("audio.chunk decoded payload is too large")
        if len(audio) % 2:
            raise DeviceProtocolError("audio.chunk pcm_s16le data must contain complete samples")
        return

    if event_type == "input.end":
        if payload.get("reason") not in {"released", "cancelled", "timeout"}:
            raise DeviceProtocolError("input.end reason is unsupported")
        return

    if event_type == "playback.done":
        duration_ms = payload.get("duration_ms")
        if duration_ms is not None and (
            not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or not 0 <= duration_ms <= 600_000
        ):
            raise DeviceProtocolError("playback.done duration_ms is invalid")
