"""Assemble a local build using the user's ALIENTEK drivers, without republishing them."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENDOR = PROJECT_ROOT / "vendor/ESP32_AI_BOX1/【正点原子】ESP32 AI BOX1资料（A盘）"
DEFAULT_DESTINATION = PROJECT_ROOT / "firmware/local_projects/lingxi_audio_ram"
DRIVERS = ("KEY", "MYIIC", "LCD", "LED", "XL9555", "ES8311")


def replace_once(data: bytes, pattern: bytes, replacement: bytes) -> bytes:
    result, count = re.subn(pattern, lambda _: replacement, data, count=1)
    if count != 1:
        raise ValueError(f"Unsupported vendor driver; cannot find {pattern!r}")
    return result


def configure_audio(path: Path, server_url: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    changes = {
        # The board's CH343 UART socket works independently of application USB.
        "CONFIG_ESP_CONSOLE_UART_DEFAULT": "y",
        "CONFIG_ESP_CONSOLE_UART_CUSTOM": "n",
        "CONFIG_ESP_CONSOLE_USB_CDC": "n",
        "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG": "n",
        "CONFIG_ESP_CONSOLE_NONE": "n",
        "CONFIG_ESP_CONSOLE_UART_NUM": "0",
        "CONFIG_ESP_CONSOLE_UART_BAUDRATE": "115200",
        "CONFIG_ESP_CONSOLE_SECONDARY_NONE": "n",
        "CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG": "y",
        # Scene rendering and libc formatting share app_main's stack. Leave
        # margin and detect frame corruption before a damaged return context.
        "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "8192",
        "CONFIG_COMPILER_STACK_CHECK_MODE_NONE": "n",
        "CONFIG_COMPILER_STACK_CHECK_MODE_NORMAL": "n",
        "CONFIG_COMPILER_STACK_CHECK_MODE_STRONG": "y",
        "CONFIG_COMPILER_STACK_CHECK_MODE_ALL": "n",
        # LCD's config enables GDMA IRAM-safe callbacks. I2S must then allocate
        # its callback context and synchronization objects in internal RAM.
        "CONFIG_I2S_ISR_IRAM_SAFE": "y",
        "CONFIG_MBEDTLS_CERTIFICATE_BUNDLE": "y",
        "CONFIG_ESP_HTTP_CLIENT_ENABLE_HTTPS": "y",
        # Mobile browsers commonly exceed IDF's 512-byte aggregate header
        # default before our setup handler runs (HTTP 431 on real phones).
        "CONFIG_HTTPD_MAX_REQ_HDR_LEN": "8192",
        # Optional card resources use FAT32. Never enable on-device formatting.
        "CONFIG_FATFS_EXFAT": "n",
        "CONFIG_FATFS_LFN_NONE": "n",
        "CONFIG_FATFS_LFN_HEAP": "y",
        "CONFIG_FATFS_LFN_STACK": "n",
        "CONFIG_FATFS_MAX_LFN": "64",
    }
    if server_url is not None:
        changes["CONFIG_LINGXI_NETWORK_ENABLE"] = "y"
        changes["CONFIG_LINGXI_SERVER_URL"] = json.dumps(server_url)
    for key, value in changes.items():
        text = re.sub(rf"^(?:{key}=.*|# {key} is not set)\r?\n?", "", text, flags=re.M)
        text += f"\n{key}={value}\n"
    path.write_text(text, encoding="utf-8")


def prepare(vendor: Path, destination: Path, update: bool = False,
            server_url: str | None = None) -> None:
    template = Path(__file__).resolve().parent
    vendor, destination = vendor.resolve(), destination.resolve()
    if any(ord(c) > 127 for c in str(destination)) or " " in str(destination):
        raise ValueError("Build destination must use an ASCII path without spaces.")
    if server_url is not None:
        url = urlsplit(server_url)
        if (url.scheme not in ("http", "https") or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in ("", "/")):
            raise ValueError("Service URL must be an http(s) base URL without credentials or a path.")
    if update:
        cmake, main, config = (destination / "CMakeLists.txt",
                               destination / "main/main.c", destination / "sdkconfig")
        if not all(p.is_file() for p in (cmake, main, config)):
            raise ValueError("Update requires an existing LingXi RAM audio project.")
        if ("project(lingxi_audio_ram)" not in cmake.read_text(encoding="utf-8")
                or "LingXi: RAM-only ES8311" not in main.read_text(encoding="utf-8")):
            raise ValueError("Destination is not the generated LingXi RAM audio project.")
        configure_audio(config, server_url)
        for source in (template / "main").iterdir():
            if source.is_file():
                shutil.copy2(source, destination / "main" / source.name)
        shutil.copy2(template / "README.md", destination / "README.md")
        shutil.copy2(template / "THIRD_PARTY.md", destination / "THIRD_PARTY.md")
        shutil.copy2(template / "partitions-16MiB.csv", destination / "partitions-16MiB.csv")
        shutil.copytree(template / "assets", destination / "assets", dirs_exist_ok=True)
        print(f"Updated: {destination}")
        print("CONFIG_I2S_ISR_IRAM_SAFE=y")
        print("Next: idf.py --no-ccache build")
        return
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Destination is not empty: {destination}; choose a new folder.")
    examples = vendor / "4，程序源码/v_5.4版本例程/1，标准例程-IDF版"
    bsp = examples / "24_recoding(ES8311)/components/BSP"
    config = examples / "10_lcd/sdkconfig"
    partitions = template / "partitions-16MiB.csv"
    for item in [config, partitions, bsp / "MYI2S/myi2s.h", *(bsp / d for d in DRIVERS)]:
        if not item.exists():
            raise FileNotFoundError(item)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("CMakeLists.txt", "README.md", "THIRD_PARTY.md"):
        shutil.copy2(template / name, destination / name)
    shutil.copytree(template / "main", destination / "main")
    shutil.copytree(template / "assets", destination / "assets")
    shutil.copy2(config, destination / "sdkconfig")
    shutil.copy2(partitions, destination / partitions.name)
    for driver in DRIVERS:
        shutil.copytree(bsp / driver, destination / "components/BSP" / driver)
    headers = destination / "components/BSP/MYI2S"
    headers.mkdir()
    shutil.copy2(bsp / "MYI2S/myi2s.h", headers / "myi2s.h")

    codec_header = destination / "components/BSP/ES8311/es8311.h"
    header = replace_once(codec_header.read_bytes(), rb"(#define\s+MCLK_DIV_FRE\s+)32",
                          b"#define MCLK_DIV_FRE                   64")
    codec_header.write_bytes(
        b"/* LingXi adaptation: BCLK = 64 Fs (32-bit slots, 16-bit PCM data). */\n" + header
    )
    codec_source = destination / "components/BSP/ES8311/es8311.c"
    source = replace_once(
        codec_source.read_bytes(),
        rb"do\s*\{\s*i2c_master_bus_wait_all_done\(bus_handle,\s*1000\);\s*"
        rb"ret\s*=\s*i2c_master_transmit\(es8311_handle,\s*buf,\s*2,\s*1000\);\s*"
        rb"\}\s*while\s*\(ret\s*!=\s*ESP_OK\);",
        b"/* LingXi: bounded retries instead of an infinite loop. */\n"
        b"    for (int attempt = 0; attempt < 3; ++attempt) {\n"
        b"        ret = i2c_master_transmit(es8311_handle, buf, 2, 200);\n"
        b"        if (ret == ESP_OK) break;\n"
        b"        vTaskDelay(pdMS_TO_TICKS(10));\n"
        b"    }",
    )
    source = source.replace(
        b"i2c_master_transmit_receive(es8311_handle, &reg_addr, 1, &reg_data, 1, -1)",
        b"i2c_master_transmit_receive(es8311_handle, &reg_addr, 1, &reg_data, 1, 200)",
    )
    codec_source.write_bytes(source)
    directories = " ".join((*DRIVERS, "MYI2S"))
    component = (
        'idf_component_register(SRC_DIRS "KEY" "MYIIC" "LCD" "LED" "XL9555" "ES8311"\n'
        f"    INCLUDE_DIRS {directories}\n"
        '    REQUIRES driver esp_lcd)\n'
    )
    (destination / "components/BSP/CMakeLists.txt").write_text(component, encoding="utf-8")

    configure_audio(destination / "sdkconfig", server_url)
    print(f"Prepared: {destination}")
    print("Next: idf.py --no-ccache build")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--update", action="store_true",
                        help="Update this generated project's application and required audio configuration.")
    parser.add_argument("--server-url", help="Enable the network check and set the service base URL.")
    args = parser.parse_args()
    prepare(args.vendor_root, args.destination, args.update, args.server_url)
