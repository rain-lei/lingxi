"""Publish refined animation resources while keeping existing BOX firmware compatible.

Only local resource files are changed; this never accesses a card or serial port.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
V1 = PUBLIC / "animations/v1"
V2 = PUBLIC / "animations/v2"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_asset(item: dict) -> Path:
    path = (PUBLIC / item["url"].lstrip("/")).resolve()
    path.relative_to(PUBLIC.resolve())
    if path.stat().st_size != item["size_bytes"] or digest(path) != item["sha256"]:
        raise ValueError("Release file does not match its manifest: " + path.name)
    return path


def verify_lxaf(path: Path) -> None:
    blob = path.read_bytes()
    magic, version, header, width, height, fmt, count, index, data, total, flags, sha = struct.unpack_from("<4sHHHHHHIIII32s", blob)
    if ((magic, version, header, width, height, fmt, index, flags) != (b"LXAF", 1, 64, 128, 128, 1, 64, 0)
            or not 1 <= count <= 30 or data != 64 + count * 32 or total != len(blob)
            or len(blob) > 64 * 1024 * 1024 or hashlib.sha256(blob[64:]).digest() != sha):
        raise ValueError("Incompatible or damaged LXAF")
    identifiers = set()
    cursor = data
    for n in range(count):
        avatar, state, loop, frames, ms, offset, size, crc, reserved = struct.unpack_from("<BBHHHIII12s", blob, 64 + n * 32)
        if (avatar > 4 or state > 5 or loop & ~1 or (avatar, state) in identifiers
                or not 1 <= frames <= 96 or not 40 <= ms <= 1000 or offset != cursor
                or size != frames * 128 * 128 * 3 or offset + size > len(blob)
                or reserved != b"\0" * 12 or zlib.crc32(blob[offset:offset+size]) & 0xFFFFFFFF != crc):
            raise ValueError("Invalid LXAF clip")
        identifiers.add((avatar, state))
        cursor += size
    if cursor != len(blob):
        raise ValueError("Trailing LXAF data")


def write_json(path: Path, data: dict) -> None:
    pending = path.with_suffix(path.suffix + ".part")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def main() -> None:
    original = json.loads((V1 / "manifest.json").read_text(encoding="utf-8"))
    refined = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
    if refined.get("web_ready") is not True:
        raise ValueError("Refined animation generation is not complete")
    raw = check_asset(refined["download"])
    check_asset(refined["archive"])
    if refined.get("web_archive"):
        check_asset(refined["web_archive"])
    verify_lxaf(raw)
    blue = next(item for item in refined["avatars"] if item["id"] == "kangaroo")
    if len(blue["clips"]) != 6 or any(item.get("web_badge_baked") is not True or item.get("board_badge_baked") is not True for item in blue["clips"]):
        raise ValueError("The six blue mascot clips must explicitly include the official badge")
    if not original.get("firmware", {}).get("ready"):
        raise ValueError("Compatible compiled firmware has not been published")
    check_asset(original["firmware"])
    # Preserve the first release so the original comparison remains reproducible.
    backup = PUBLIC / "animations/archive/20261021-v1"
    if not backup.exists():
        backup.mkdir(parents=True)
        for name in ("manifest.json", "pack-report.json", "lingxi-animations-v1.lxaf", "lingxi-tf-animations-v1.zip"):
            shutil.copy2(V1 / name, backup / name)
    refined["firmware"] = original["firmware"]
    refined["install"] = original["install"]
    refined["hardware_verified"] = False
    refined["device_download_url"] = "/animations/v1/lingxi-animations-v1.lxaf"
    refined["format_version"] = 1
    refined["download"]["filename"] = "animations-v1.lxaf"
    destination = V1 / "lingxi-animations-v1.lxaf"
    pending = destination.with_suffix(".lxaf.part")
    shutil.copy2(raw, pending)
    if digest(pending) != refined["download"]["sha256"]:
        raise ValueError("Compatibility resource copy failed")
    pending.replace(destination)
    write_json(V2 / "manifest.json", refined)
    # Old entry points see the same refined catalog; the fixed firmware URL is an alias.
    write_json(V1 / "manifest.json", refined)
    report = {"resource": refined["download"], "archive": refined["archive"],
              "web_archive": refined.get("web_archive"),
              "compatibility_url": refined["device_download_url"],
              "firmware_unchanged": refined["firmware"]["binary_sha256"],
              "hardware_verified": False}
    write_json(V2 / "publication-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
