"""Validate or send one complete LingXi 0.4-draft upstream device sequence."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from device_protocol import PROTOCOL_VERSION, validate_device_event  # noqa: E402


def build_sequence(device_id: str) -> list[dict[str, Any]]:
    started_ms = int(time.time() * 1000)
    silent_pcm = base64.b64encode(b"\x00\x00" * 640).decode("ascii")
    payloads = [
        (
            "device.hello",
            {
                "firmware": "simulator-0.4.0",
                "capabilities": ["microphone", "speaker", "oled", "rgb", "button"],
            },
        ),
        ("device.heartbeat", {"battery_percent": 86, "rssi_dbm": -52}),
        ("input.begin", {"mode": "assistant"}),
        (
            "audio.chunk",
            {"encoding": "pcm_s16le", "sample_rate": 16_000, "data": silent_pcm},
        ),
        ("input.end", {"reason": "released"}),
        ("playback.done", {"duration_ms": 1200}),
    ]
    return [
        {
            "version": PROTOCOL_VERSION,
            "type": event_type,
            "device_id": device_id,
            "seq": index,
            "timestamp_ms": started_ms + index * 40,
            "payload": payload,
        }
        for index, (event_type, payload) in enumerate(payloads, start=1)
    ]


def post_event(base_url: str, token: str, event: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{base_url.rstrip('/')}/api/device/events",
        data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "LingXi-Device-Simulator/0.4",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"server rejected {event['type']} with HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"cannot reach device endpoint at {base_url}") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--device-id", default="lingxi-simulator-01")
    parser.add_argument(
        "--send",
        action="store_true",
        help="POST events to the server; reads LINGXI_DEVICE_TOKEN from the environment",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sequence = [validate_device_event(event) for event in build_sequence(args.device_id)]
    if not args.send:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "validate-only",
                    "protocol": PROTOCOL_VERSION,
                    "events": [event["type"] for event in sequence],
                },
                ensure_ascii=False,
            )
        )
        return

    token = os.getenv("LINGXI_DEVICE_TOKEN", "").strip()
    if not token:
        raise SystemExit("LINGXI_DEVICE_TOKEN is required with --send")
    acknowledgements = [post_event(args.base_url, token, event) for event in sequence]
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "server",
                "protocol": PROTOCOL_VERSION,
                "acknowledged": len(acknowledgements),
                "final_session": acknowledgements[-1].get("session"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
