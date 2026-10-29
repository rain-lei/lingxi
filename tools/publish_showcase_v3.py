"""Publish an already compiled Showcase V3 image and verified local TF assets.

No serial ports, card IO, cloud requests, downloads or firmware builds are made.
Run only after the final ESP32 build passes:
    python tools/publish_showcase_v3.py --firmware <compiled-app.bin>
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
V1 = PUBLIC / "animations/v1"
V2 = PUBLIC / "animations/v2"
V3 = PUBLIC / "animations/v3"
FONTS = PUBLIC / "fonts/v1"
DEVICE_URL = "/animations/v1/lingxi-animations-v1.lxaf"
FRAME_BYTES = 128 * 128 * 3


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    pending = path.with_suffix(path.suffix + ".part")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def asset_path(url: str) -> Path:
    if not isinstance(url, str) or not url.startswith("/") or url.startswith("//") or any(c in url for c in ("\\", "?", "#", ":")):
        raise ValueError("Expected a project-local public asset URL")
    path = (PUBLIC / url.lstrip("/")).resolve()
    path.relative_to(PUBLIC.resolve())
    return path


def normalize(item: dict) -> dict:
    """Fonts use path/bytes; animations use url/size_bytes. Publish one shape."""
    url = item.get("url", item.get("path"))
    size = item.get("size_bytes", item.get("bytes"))
    sha = item.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("Resource size must be a positive integer")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid resource SHA256")
    path = asset_path(url)
    if path.stat().st_size != size or digest(path) != sha:
        raise ValueError(f"Resource size or SHA256 mismatch: {url}")
    return dict(url=url, filename=item.get("filename", path.name), size_bytes=size, sha256=sha)


def check_zip(item: dict) -> None:
    with zipfile.ZipFile(asset_path(item["url"])) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP CRC failed: {bad}")


def update_firmware_guide(firmware: dict) -> None:
    """The legacy app publisher's V2 instructions must not label a V3 image."""
    archive_path = asset_path(firmware["url"])
    pending = archive_path.with_suffix(".zip.part")
    guide = (ROOT / "docs/SHOWCASE_V3_20261023.md").read_bytes()
    font_guide = (ROOT / "docs/TF_TONE_FONTS_20261023.md").read_bytes()
    with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(
            pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for entry in source.infolist():
            if not entry.filename.lower().endswith(".md"):
                target.writestr(entry, source.read(entry))
        target.writestr("安装说明.md", guide)
        target.writestr("TF_TONE_FONTS_20261023.md", font_guide)
        badge_guide = ROOT / "docs/BADGE_CENTERING_20261023.md"
        if badge_guide.is_file():
            target.writestr(badge_guide.name, badge_guide.read_bytes())
        motion_guide = ROOT / "docs/LOCAL_JOINT_MOTION_20261024.md"
        if motion_guide.is_file():
            target.writestr(motion_guide.name, motion_guide.read_bytes())
        characters_guide = ROOT / "docs/ALL_CHARACTERS_MOTION_20261024.md"
        if characters_guide.is_file():
            target.writestr(characters_guide.name, characters_guide.read_bytes())
    with zipfile.ZipFile(pending) as checked:
        if checked.testzip() is not None or checked.read("安装说明.md") != guide:
            raise ValueError("V3 firmware instructions failed ZIP verification")
    pending.replace(archive_path)
    firmware["size_bytes"] = archive_path.stat().st_size
    firmware["sha256"] = digest(archive_path)


def validate_rle3(stream: memoryview) -> None:
    used = produced = 0
    while used < len(stream):
        control = stream[used]
        used += 1
        count = ((control & 127) + 1) * 3
        source_bytes = 3 if control & 128 else count
        if used + source_bytes > len(stream) or produced + count > FRAME_BYTES:
            raise ValueError("RLE3 packet exceeds source or frame bounds")
        used += source_bytes
        produced += count
    if produced != FRAME_BYTES:
        raise ValueError("RLE3 frame has an invalid decoded size")


def verify_lxaf_v2(path: Path) -> dict:
    blob = path.read_bytes()
    if len(blob) < 96:
        raise ValueError("Truncated LXAF")
    h = struct.unpack_from("<4sHHHHHHIIII32s", blob)
    magic, version, header, width, height, fmt, count, index, data, total, flags, sha = h
    if ((magic, version, header, width, height, fmt, index, flags) != (b"LXAF", 2, 64, 128, 128, 1, 64, 0)
            or not 1 <= count <= 64 or data != 64 + count * 32 or total != len(blob)
            or len(blob) > 256 * 1024 * 1024 or hashlib.sha256(blob[64:]).digest() != sha):
        raise ValueError("Invalid or incompatible LXAF v2 header/body SHA256")
    identifiers = set()
    cursor = data
    frames_total = 0
    view = memoryview(blob)
    for n in range(count):
        avatar, state, loop, frames, ms, offset, size, crc, reserved = struct.unpack_from("<BBHHHIII12s", blob, 64 + n * 32)
        if (avatar > 4 or state >= 12 or loop & ~3 or (avatar, state) in identifiers
                or not 1 <= frames <= 96 or not 40 <= ms <= 1000 or offset != cursor
                or offset + size > len(blob) or reserved != b"\0" * 12):
            raise ValueError(f"Invalid LXAF v2 clip index {n}")
        payload = view[offset:offset+size]
        if zlib.crc32(payload) & 0xFFFFFFFF != crc:
            raise ValueError(f"LXAF clip CRC32 mismatch at {n}")
        if loop & 2:
            if not frames * 12 <= size <= frames * (FRAME_BYTES + 128 + 8):
                raise ValueError("Invalid compressed clip size")
            expected = frames * 8
            for frame in range(frames):
                start, length = struct.unpack_from("<II", payload, frame * 8)
                if not length or start != expected or start + length > size:
                    raise ValueError("Invalid RLE3 frame directory")
                validate_rle3(payload[start:start+length])
                expected += length
            if expected != size:
                raise ValueError("Trailing compressed clip data")
        elif size != frames * FRAME_BYTES:
            raise ValueError("Invalid raw clip size")
        identifiers.add((avatar, state))
        cursor += size
        frames_total += frames
    if cursor != len(blob):
        raise ValueError("Trailing LXAF payload")
    return dict(version=version, clips=count, frames=frames_total, compressed=True,
                sha256=digest(path), size_bytes=len(blob))


def verify_fonts(manifest: dict) -> dict:
    raw = normalize(manifest["download"])
    archive = normalize(manifest["archive"])
    check_zip(archive)
    install = read_json(FONTS / "install.json")
    if normalize(install["download"]) != raw:
        raise ValueError("Small font install manifest differs from font catalog")
    blob = asset_path(raw["url"]).read_bytes()
    h = struct.unpack_from("<4sHHIHHII8s32s", blob)
    if h[:9] != (b"LXFF", 1, 64, len(blob), 4, 12, 64, 0, b"\0"*8) or hashlib.sha256(blob[64:]).digest() != h[9]:
        raise ValueError("Font package header/body SHA mismatch")
    cursor = 320
    for tone in range(4):
        ident, px, height, bits, count, go, gb, ao, ab, crc, reserved, name = struct.unpack_from("<BBBB6II32s", blob, 64+tone*64)
        if ((ident, px, height, bits, reserved) != (tone, 20, 26, 2, 0) or not 6858 <= count <= 12000
                or go != cursor or gb != count*12 or ao != go+gb or not 0 < gb+ab <= 1200*1024
                or ao+ab > len(blob) or zlib.crc32(blob[go:ao+ab]) & 0xffffffff != crc):
            raise ValueError("Invalid font range or CRC32")
        cursor = ao+ab
    if cursor != len(blob):
        raise ValueError("Trailing font data")
    styles = []
    expected_tones = ["warm", "calm", "cheerful", "direct"]
    for expected, item in zip(expected_tones, manifest["fonts"], strict=True):
        web = asset_path(item["web_path"])
        if item["id"] != expected or web.stat().st_size != item["web_bytes"] or item["license"] != "OFL-1.1":
            raise ValueError("Font style/web file does not match its manifest")
        styles.append(dict(id=item["id"], label=item["label"], family=item["family"],
                           web_url=item["web_path"], web_size_bytes=web.stat().st_size,
                           web_sha256=digest(web), license=item["license"], license_url=item["license_path"],
                           pixel_size=item["pixel_size"], glyph_count=item["glyph_count"]))
    return dict(manifest_url="/fonts/v1/manifest.json", install_manifest_url="/fonts/v1/install.json",
                card_path=manifest["card_path"], download=raw, archive=archive, styles=styles,
                preview_url=manifest.get("preview"), hardware_verified=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    args = parser.parse_args()
    firmware = args.firmware.resolve(strict=True)
    if not 24 < firmware.stat().st_size <= 0x3F0000:
        raise ValueError("Firmware does not fit existing app partition")
    with firmware.open("rb") as f:
        if f.read(1) != b"\xe9":
            raise ValueError("Expected a compiled ESP32 application")

    # Complete read-only verification before publishing any new firmware metadata.
    catalog = read_json(V3 / "manifest.json")
    if catalog.get("web_ready") is not True or catalog.get("format_version") != 2:
        raise ValueError("V3 generation is incomplete")
    raw = normalize(catalog["download"])
    archive = normalize(catalog["archive"])
    check_zip(archive)
    lxaf = verify_lxaf_v2(asset_path(raw["url"]))
    if lxaf["clips"] != sum(len(a["clips"]) for a in catalog["avatars"]):
        raise ValueError("Clip count differs from published catalog")
    blue = next(a for a in catalog["avatars"] if a["id"] == "kangaroo")
    if any(c.get("board_badge_baked") is not True or c.get("web_badge_baked") is not True for c in blue["clips"]):
        raise ValueError("Blue mascot badge must remain in every clip")
    fonts = verify_fonts(read_json(FONTS / "manifest.json"))
    original_v1 = read_json(V1 / "manifest.json")
    original_v2 = read_json(V2 / "manifest.json")
    # Validate the current candidate, rather than an obsolete archive record:
    # a corrected revision can deliberately replace a resource at the same URL.

    # Preserve old metadata once. The actual V2 assets remain in animations/v2.
    previous = V3 / "pre-publication-v1-catalog.json"
    if not previous.exists():
        write_json(previous, original_v1)
    with tempfile.TemporaryDirectory(prefix="showcase-publish-", dir=ROOT / "tmp") as staging:
        staged_manifest = Path(staging) / "manifest.json"
        staged = copy.deepcopy(catalog)
        staged.update(download=raw, archive=archive)
        write_json(staged_manifest, staged)
        subprocess.run([sys.executable, str(ROOT / "tools/publish_tf_animation_release.py"),
                        "--firmware", str(firmware), "--manifest", str(staged_manifest)],
                       cwd=ROOT, check=True)
        released = read_json(staged_manifest)
    fw = copy.deepcopy(released["firmware"])
    normalize(fw)
    update_firmware_guide(fw)
    binary = asset_path(fw["binary_url"])
    if binary.stat().st_size != fw["binary_size_bytes"] or digest(binary) != fw["binary_sha256"]:
        raise ValueError("Published firmware binary differs from build")
    if fw.get("ready") is not True or fw.get("compiled") is not True:
        raise ValueError("Firmware publisher did not confirm a compiled image")
    fw.update(animation_format_version=2, supported_lxaf_versions=[1,2], tf_fonts_supported=True,
              hardware_verified=False)
    catalog.update(firmware=fw, install=released["install"], fonts=fonts,
                   hardware_verified=False, device_download_url=DEVICE_URL,
                   animation_format_version=2, supported_lxaf_versions=[1,2], tf_fonts_supported=True)
    catalog["download"] = raw
    catalog["download"]["filename"] = "animations-v1.lxaf"
    catalog["archive"] = archive
    catalog["install"]["font_instructions"] = "字体可独立安装：在板子配置页点击“安装语气字体”，或将独立字体包里的 lingxi-fonts-v1.lxff 复制为卡上 lingxi/fonts-v1.lxff；无需重装动画。"

    # The fixed device endpoint is changed only after all assets and firmware pass.
    destination = asset_path(DEVICE_URL)
    pending = destination.with_suffix(".lxaf.part")
    shutil.copy2(asset_path(raw["url"]), pending)
    if pending.stat().st_size != raw["size_bytes"] or digest(pending) != raw["sha256"]:
        raise ValueError("Fixed device animation copy failed verification")
    pending.replace(destination)
    original_v2["firmware"] = copy.deepcopy(fw)
    write_json(V2 / "manifest.json", original_v2)
    write_json(V3 / "manifest.json", catalog)
    alias_catalog = copy.deepcopy(catalog)
    alias_catalog["download"]["url"] = DEVICE_URL
    write_json(V1 / "manifest.json", alias_catalog)
    report = dict(published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  animation=raw, archive=archive, lxaf_validation=lxaf, firmware=fw, fonts=fonts,
                  device_download_url=DEVICE_URL, device_alias_verified=True,
                  previous_catalog_url="/animations/v3/pre-publication-v1-catalog.json",
                  v2_actual_assets_unchanged=True, hardware_verified=False,
                  serial_port_opened=False, card_accessed=False)
    write_json(V3 / "publication-report-v3.json", report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
