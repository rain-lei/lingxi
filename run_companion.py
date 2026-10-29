"""Start the local companion and open its setup page without exposing secrets."""
from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

PAGE = "http://127.0.0.1:8787/" + ("animations.html" if "--animations" in sys.argv[1:] else "companion")
ROOT = Path(__file__).resolve().parent


def prepare_device_link() -> None:
    """Restore the nearby link only on a machine configured to use this mode."""
    marker = ROOT / "data/local-device-link.json"
    if os.name != "nt" or not marker.exists():
        return
    try:
        if not json.loads(marker.read_text(encoding="utf8")).get("enabled"):
            return
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(ROOT / "tools/device_hotspot.ps1")]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode:
            print("Device hotspot could not start. Open Windows Mobile hotspot settings.")
        else:
            print("Device hotspot checked; leave this computer online for the companion.")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print("Device hotspot unavailable. Check Windows Mobile hotspot settings.")


def running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8787/api/companion/setup", timeout=1) as response:
            data = json.load(response)
        return data.get("local_setup_allowed") is True and "configured" in data
    except (OSError, ValueError):
        return False


def open_when_ready() -> None:
    for _ in range(30):
        if running():
            webbrowser.open(PAGE)
            return
        time.sleep(0.5)


if __name__ == "__main__":
    # Also makes a fresh git checkout usable without a manual LFS setup.
    from tools.fetch_assets import main as fetch_assets
    if fetch_assets(['--scope', 'runtime']):
        raise SystemExit(1)
    prepare_device_link()
    if running():
        webbrowser.open(PAGE)
        print("LingXi is already running: " + PAGE)
    else:
        from server import main

        root = ROOT
        sys.argv = [str(root / "server.py"), "--host", "0.0.0.0", "--port", "8787",
                    "--database", str(root / "data/lingxi_demo.db")]
        threading.Thread(target=open_when_ready, daemon=True).start()
        main()
