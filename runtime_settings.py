"""Local provider configuration. Secrets are never served back to a browser."""
from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

CONFIG_PATH = Path(__file__).resolve().parent / "data/local-voice-settings.json"


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        return data

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError("无法保存或读取本机受保护的语音配置")
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


def load_local_settings(path: Path = CONFIG_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    encoded = base64.b64decode(document["payload"], validate=True)
    if document.get("protection") == "windows-dpapi":
        if os.name != "nt":
            return {}
        encoded = _protect(encoded, decrypt=True)
    value = json.loads(encoded.decode("utf-8"))
    return {k: str(v) for k, v in value.items()
            if k in {"api_key", "base_url", "audio_base_url", "device_token"}}


def save_local_settings(value: dict[str, str], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    document = {"protection": "windows-dpapi" if os.name == "nt" else "owner-only-file",
                "payload": base64.b64encode(_protect(raw)).decode("ascii")}
    descriptor, temporary = tempfile.mkstemp(prefix=".voice-settings-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_provider_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or url.hostname not in {"api.stepfun.com", "api.stepfun.ai"}
            or url.username or url.password or url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError("服务地址须使用阶跃官方 HTTPS API 地址")
    if url.path.rstrip("/") not in {"/v1", "/step_plan/v1"}:
        raise ValueError("服务地址路径应为 /v1 或 /step_plan/v1")
    return value.rstrip("/")
