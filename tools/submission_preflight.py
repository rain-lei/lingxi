"""Check public demo and repository artifacts before hackathon submission.

The script uses only the standard library. It never reads ``.env`` or prints
configuration values; it only checks that the credential file is not tracked.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://lingxi.rainlei.xyz"
REQUIRED_FILES = (
    "README.md",
    "THIRD_PARTY.md",
    "docs/project-brief.md",
    "docs/demo-video-script.md",
    "docs/user-test-plan.md",
    "docs/competition-alignment.md",
)


class PreflightError(RuntimeError):
    """A user-actionable submission readiness failure."""


def _request(url: str, timeout: float = 10) -> tuple[int, bytes]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - public URL input
        return int(response.status), response.read()


def check_required_files(root: Path = ROOT) -> list[str]:
    missing = [path for path in REQUIRED_FILES if not (root / path).is_file()]
    if missing:
        raise PreflightError(f"缺少提交材料：{', '.join(missing)}")
    return list(REQUIRED_FILES)


def check_env_is_not_tracked(root: Path = ROOT) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        raise PreflightError(".env 已被 Git 跟踪；请先移除真实密钥再提交")
    if result.returncode not in {1}:
        raise PreflightError("无法检查 Git 跟踪状态；请在 Git 仓库根目录运行")


def check_public_demo(base_url: str, allow_mock: bool = False) -> dict[str, Any]:
    base = base_url.rstrip("/")
    for path, marker in (("/demo", "在线演示"), ("/console", "系统控制台")):
        status, body = _request(f"{base}{path}")
        if status != 200 or marker.encode("utf-8") not in body:
            raise PreflightError(f"{path} 未返回可识别的页面（HTTP {status}）")

    status, body = _request(f"{base}/api/health")
    if status != 200 or not json.loads(body).get("ok"):
        raise PreflightError("/api/health 未通过")

    status, body = _request(f"{base}/api/capabilities")
    capabilities = json.loads(body)
    if status != 200:
        raise PreflightError(f"/api/capabilities 返回 HTTP {status}")
    if not allow_mock and not (
        capabilities.get("enabled")
        and capabilities.get("chat")
        and capabilities.get("vision")
    ):
        raise PreflightError("线上模型或视觉能力未启用；检查服务端密钥和模型配置")
    reminders = capabilities.get("task_center", {}).get("reminders", {})
    if not reminders.get("enabled"):
        raise PreflightError("任务提醒调度未启用")
    return capabilities


def main() -> int:
    parser = argparse.ArgumentParser(description="灵犀挂件黑客松提交前自检")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="公开 Demo 根地址")
    parser.add_argument("--skip-online", action="store_true", help="仅检查本地材料与 Git 状态")
    parser.add_argument("--allow-mock", action="store_true", help="允许线上服务处于 Mock 兜底模式")
    args = parser.parse_args()

    try:
        files = check_required_files()
        check_env_is_not_tracked()
        print(f"[PASS] 提交材料 {len(files)} 项齐全；.env 未被 Git 跟踪")
        if not args.skip_online:
            capabilities = check_public_demo(args.base_url, allow_mock=args.allow_mock)
            model = capabilities.get("models", {}).get("chat", "unknown")
            print(f"[PASS] 公开 Demo、控制台、健康检查和能力接口正常（{model}）")
    except (PreflightError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print("[PASS] 自动检查完成；仍请确认演示视频与真实用户证据已按规则脱敏。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
