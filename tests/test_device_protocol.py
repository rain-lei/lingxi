import base64
import unittest

from device_protocol import (
    PROTOCOL_VERSION,
    DeviceProtocolError,
    protocol_manifest,
    validate_device_event,
)


class DeviceProtocolTests(unittest.TestCase):
    def test_manifest_exposes_audio_and_event_contract(self) -> None:
        manifest = protocol_manifest()
        self.assertEqual(manifest["version"], PROTOCOL_VERSION)
        self.assertEqual(manifest["audio"]["sample_rate"], 16_000)
        self.assertIn("device.hello", manifest["upstream_events"])
        self.assertIn("session.state", manifest["downstream_events"])

    def test_validates_hello_event(self) -> None:
        event = validate_device_event(
            {
                "version": PROTOCOL_VERSION,
                "type": "device.hello",
                "device_id": "lingxi-p01",
                "seq": 1,
                "timestamp_ms": 1_800_000_000_000,
                "payload": {
                    "firmware": "0.4.0",
                    "capabilities": ["microphone", "oled", "rgb", "speaker"],
                },
            }
        )
        self.assertEqual(event["device_id"], "lingxi-p01")

    def test_validates_pcm_audio_constraints(self) -> None:
        audio = base64.b64encode(b"\x00\x00" * 320).decode("ascii")
        event = validate_device_event(
            {
                "version": PROTOCOL_VERSION,
                "type": "audio.chunk",
                "device_id": "lingxi-p01",
                "seq": 2,
                "timestamp_ms": 1_800_000_000_040,
                "payload": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 16_000,
                    "data": audio,
                },
            }
        )
        self.assertEqual(event["seq"], 2)

    def test_rejects_unsupported_version(self) -> None:
        with self.assertRaises(DeviceProtocolError):
            validate_device_event(
                {
                    "version": "0.3",
                    "type": "input.begin",
                    "device_id": "lingxi-p01",
                    "seq": 1,
                    "timestamp_ms": 1_800_000_000_000,
                    "payload": {},
                }
            )


if __name__ == "__main__":
    unittest.main()
