"""Versioned LingXi device event protocol shared by firmware and console tools."""

from __future__ import annotations

import base64
import re
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
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and 1 <= len(item) <= 32 for item in capabilities
        ):
            raise DeviceProtocolError("device.hello requires string capabilities")
        return

    if event_type == "device.heartbeat":
        battery = payload.get("battery_percent")
        rssi = payload.get("rssi_dbm")
        if not isinstance(battery, (int, float)) or isinstance(battery, bool) or not 0 <= battery <= 100:
            raise DeviceProtocolError("heartbeat battery_percent must be between 0 and 100")
        if not isinstance(rssi, (int, float)) or isinstance(rssi, bool) or not -140 <= rssi <= 0:
            raise DeviceProtocolError("heartbeat rssi_dbm must be between -140 and 0")
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
