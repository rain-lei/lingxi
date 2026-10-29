"""Publish built TF firmware alongside the already rendered animation pack.

This only creates local downloadable files. It never opens a serial port or SD card.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP_PARTITION_BYTES = 0x3F0000


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "public/animations/v1/manifest.json",
                        help="Verified candidate catalog to update; defaults to the public V1 catalog.")
    args = parser.parse_args()
    firmware = args.firmware.resolve()
    size = firmware.stat().st_size
    if not (24 < size <= APP_PARTITION_BYTES):
        raise SystemExit("Firmware does not fit the existing app partition.")
    with firmware.open("rb") as source:
        if source.read(1) != b"\xe9":
            raise SystemExit("Expected an ESP application image.")
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("archive", "download"):
        file = ROOT / "public" / manifest[key]["url"].lstrip("/")
        if file.stat().st_size != manifest[key]["size_bytes"] or digest(file) != manifest[key]["sha256"]:
            raise SystemExit(f"Animation {key} no longer matches its manifest.")
    guide = ROOT / "docs/TF_ANIMATION_INSTALL_GUIDE_20261021.md"
    helper = ROOT / "tools/tf_animation_flash.ps1"
    for file in (guide, helper):
        if not file.is_file():
            raise SystemExit(f"Missing installation resource: {file}")
    output = ROOT / "public/downloads"
    output.mkdir(parents=True, exist_ok=True)
    binary = output / "lingxi-tf-animation-v1.bin"
    shutil.copy2(firmware, binary)
    firmware_hash = digest(binary)
    archive = output / "lingxi-tf-firmware-v1.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        package.write(binary, "lingxi-tf-animation.bin")
        package.write(helper, "tf_animation_flash.ps1")
        package.write(guide, "安装说明.md")
        package.writestr("SHA256SUMS.txt", f"{firmware_hash}  lingxi-tf-animation.bin\n")
        package.writestr("flash.cmd", '@echo off\r\ncd /d "%~dp0"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tf_animation_flash.ps1"\r\npause\r\n')
    manifest["firmware"] = {
        "ready": True,
        "url": "/downloads/" + archive.name,
        "filename": archive.name,
        "size_bytes": archive.stat().st_size,
        "sha256": digest(archive),
        "binary_url": "/downloads/" + binary.name,
        "binary_size_bytes": size,
        "binary_sha256": firmware_hash,
        "flash_offset": "0x10000",
        "app_partition_bytes": APP_PARTITION_BYTES,
        "compiled": True,
        "hardware_verified": False,
    }
    manifest["hardware_verified"] = False
    manifest["install"] = {
        "copy_instructions": "解压完整 TF 动画包，将其中 lingxi 文件夹复制到卡根目录，最终路径为 lingxi/animations-v1.lxaf。其余预览文件可留在电脑。已有同名资源先备份。",
        "wifi_instructions": "更新配套固件、断电插入 FAT32 TF 卡后，电脑运行 start_animations.cmd。手机连接 LingXi-922C，打开 http://192.168.4.1/，点击“从电脑安装动画”。板子通过已配置的 Wi-Fi 向电脑接收素材，手机提示无互联网正常；显示校验完成后再使用，下载过程中保持板子供电和电脑服务在线。",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"firmware": manifest["firmware"], "avatars": len(manifest["avatars"]),
                      "clips": sum(len(item["clips"]) for item in manifest["avatars"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
