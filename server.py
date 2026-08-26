"""LingXi Pendant software-first demo server.

The server deliberately uses only Python's standard library so the hackathon
demo can run without an install step. It serves the browser device simulator,
streams NDJSON interaction events, and persists lightweight profile memory in
SQLite.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from providers.stepfun import StepFunClient, StepFunError


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DEFAULT_DB = ROOT / "data" / "lingxi_demo.db"
ALLOWED_MODES = {"assistant", "companion", "translate"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Profile:
    device_id: str
    preferred_name: str = "朋友"
    speech_rate: str = "normal"
    updated_at: str = ""


class DemoEngine:
    """Conversation orchestration and local memory for the demo."""

    def __init__(
        self,
        database_path: Path | str = DEFAULT_DB,
        stepfun: StepFunClient | None = None,
    ):
        self.database_path = Path(database_path)
        self.stepfun = stepfun or StepFunClient()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        """Commit or roll back work and always release the SQLite file handle."""
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    device_id TEXT PRIMARY KEY,
                    preferred_name TEXT NOT NULL DEFAULT '朋友',
                    speech_rate TEXT NOT NULL DEFAULT 'normal',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'complete',
                    created_at TEXT NOT NULL
                );
                """
            )

    def get_profile(self, device_id: str) -> Profile:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None:
                now = utc_now()
                connection.execute(
                    "INSERT INTO profiles(device_id, updated_at) VALUES (?, ?)",
                    (device_id, now),
                )
                return Profile(device_id=device_id, updated_at=now)
        return Profile(
            device_id=row["device_id"],
            preferred_name=row["preferred_name"],
            speech_rate=row["speech_rate"],
            updated_at=row["updated_at"],
        )

    def update_profile_from_text(self, device_id: str, text: str) -> tuple[Profile, list[str]]:
        profile = self.get_profile(device_id)
        preferred_name = profile.preferred_name
        speech_rate = profile.speech_rate
        changes: list[str] = []

        name_match = re.search(
            r"(?:记住我叫|以后叫我|请叫我|我叫)\s*([A-Za-z\u4e00-\u9fff]{1,10})",
            text,
        )
        if name_match:
            preferred_name = name_match.group(1)
            changes.append(f"称呼：{preferred_name}")

        if any(phrase in text for phrase in ("语速慢一点", "说慢一点", "慢速播报")):
            speech_rate = "slow"
            changes.append("语速：慢")
        elif any(phrase in text for phrase in ("语速快一点", "说快一点", "快速播报")):
            speech_rate = "fast"
            changes.append("语速：快")
        elif "正常语速" in text:
            speech_rate = "normal"
            changes.append("语速：正常")

        if changes:
            now = utc_now()
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO profiles(device_id, preferred_name, speech_rate, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        preferred_name = excluded.preferred_name,
                        speech_rate = excluded.speech_rate,
                        updated_at = excluded.updated_at
                    """,
                    (device_id, preferred_name, speech_rate, now),
                )
            profile = Profile(device_id, preferred_name, speech_rate, now)
        return profile, changes

    def reset_device(self, device_id: str) -> Profile:
        with self._connection() as connection:
            connection.execute("DELETE FROM conversations WHERE device_id = ?", (device_id,))
            connection.execute("DELETE FROM profiles WHERE device_id = ?", (device_id,))
        return self.get_profile(device_id)

    def recent_history(self, device_id: str, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT mode, user_text, assistant_text, status, created_at
                FROM conversations
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def record_interaction(
        self,
        device_id: str,
        mode: str,
        user_text: str,
        assistant_text: str,
        status: str = "complete",
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    device_id, mode, user_text, assistant_text, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (device_id, mode, user_text, assistant_text, status, utc_now()),
            )

    def generate_reply(self, text: str, mode: str, profile: Profile) -> str:
        compact = " ".join(text.strip().split())
        name = profile.preferred_name

        if mode == "translate":
            return self._translation_reply(compact)

        if any(phrase in compact for phrase in ("记住我叫", "以后叫我", "请叫我", "我叫")):
            return f"记住啦，以后我就叫你{name}。"

        if any(phrase in compact for phrase in ("语速慢一点", "说慢一点", "慢速播报")):
            return f"好的，{name}。我会放慢一点说，让你听得更舒服。"

        if "心情不好" in compact or "不开心" in compact:
            return (
                f"{name}，听起来你今天有点难受。先别急着逼自己振作，"
                "慢慢吸一口气。愿意的话，跟我说说发生了什么，我陪你理一理。"
            )

        if "图书馆" in compact and any(word in compact for word in ("几点", "关门", "开放")):
            return (
                f"{name}，当前是软件演示模式，还没有接入校园实时开放数据。"
                "正式版会先确认馆区和校历，再把准确闭馆时间告诉你。"
            )

        if "天气" in compact or "带伞" in compact:
            return (
                f"{name}，演示版暂未接入实时天气。正式版会结合你的位置查询天气，"
                "并只用一句话告诉你要不要带伞。"
            )

        if mode == "companion":
            return f"{name}，我在呢。你可以慢慢说，我会认真听，也会记住你喜欢的交流方式。"

        return (
            f"收到，{name}。这是灵犀的软件闭环演示：我已经完成输入、记忆读取、"
            f"流式回复和语音播报，真实模型接入后会在这里回答“{compact[:24]}”。"
        )

    def build_stepfun_messages(
        self,
        device_id: str,
        text: str,
        mode: str,
        profile: Profile,
        image_data_url: str | None = None,
    ) -> list[dict[str, Any]]:
        mode_instruction = {
            "assistant": "直接回答问题；未知或需要实时数据时明确说明，不要编造。",
            "companion": "先共情，再给一个轻量建议；不说教，不做医疗诊断。",
            "translate": "只输出自然译文，不加解释；中文默认译成英文，其他语言默认译成中文。",
        }[mode]
        system_prompt = (
            "你是可穿戴 AI 伙伴‘灵犀’。回复要简短、口语化、有温度，适合 128x64 OLED "
            "和语音播放，通常不超过 90 个汉字，不使用 Markdown。"
            f"当前用户称呼：{profile.preferred_name}；播报语速：{profile.speech_rate}。"
            f"当前模式要求：{mode_instruction}"
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for item in self.recent_history(device_id, limit=4):
            messages.append({"role": "user", "content": item["user_text"]})
            messages.append({"role": "assistant", "content": item["assistant_text"]})
        if image_data_url:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text or "请分析这张图片，并用简短中文回答。"},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": text})
        return messages

    @staticmethod
    def _translation_reply(text: str) -> str:
        normalized = re.sub(r"^(帮我)?翻译[：:，,]?\s*", "", text).strip()
        canned = {
            "请问附近有不含花生的菜吗？": "Excuse me, are there any peanut-free dishes nearby?",
            "请问附近有不含花生的菜吗": "Excuse me, are there any peanut-free dishes nearby?",
            "你好，很高兴认识你": "Hello, it's nice to meet you.",
            "Where is the nearest subway station?": "最近的地铁站在哪里？",
        }
        if normalized in canned:
            return canned[normalized]
        if re.search(r"[\u4e00-\u9fff]", normalized):
            return f"Translation demo: {normalized}（接入翻译模型后返回自然英文）"
        return f"翻译演示：{normalized}（接入翻译模型后返回自然中文）"


def chunk_text(text: str, width: int = 5) -> Iterable[str]:
    """Yield display-friendly chunks without splitting ASCII words too aggressively."""
    buffer = ""
    for character in text:
        buffer += character
        if len(buffer) >= width or character in "，。！？；,.!?;":
            yield buffer
            buffer = ""
    if buffer:
        yield buffer


class LingXiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LingXiDemo/0.2"

    @property
    def engine(self) -> DemoEngine:
        return self.server.engine  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "service": "lingxi-demo", "time": utc_now()})
            return
        if parsed.path == "/api/capabilities":
            self._send_json(self.engine.stepfun.capabilities())
            return
        if parsed.path == "/api/profile":
            device_id = self._device_id(parsed.query)
            self._send_json(asdict(self.engine.get_profile(device_id)))
            return
        if parsed.path == "/api/history":
            device_id = self._device_id(parsed.query)
            self._send_json({"items": self.engine.recent_history(device_id)})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/audio/transcribe":
                max_length = 4_000_000
            elif parsed.path == "/api/interactions":
                max_length = 12_000_000
            else:
                max_length = 64_000
            payload = self._read_json(max_length=max_length)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/interactions":
            self._stream_interaction(payload)
            return
        if parsed.path == "/api/audio/transcribe":
            self._transcribe_audio(payload)
            return
        if parsed.path == "/api/audio/speech":
            self._synthesize_audio(payload)
            return
        if parsed.path == "/api/reset":
            device_id = self._clean_device_id(payload.get("device_id", "demo-pendant-01"))
            profile = self.engine.reset_device(device_id)
            self._send_json({"ok": True, "profile": asdict(profile)})
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _stream_interaction(self, payload: dict[str, Any]) -> None:
        device_id = self._clean_device_id(payload.get("device_id", "demo-pendant-01"))
        text = str(payload.get("text", "")).strip()
        mode = str(payload.get("mode", "assistant"))
        offline = bool(payload.get("offline", False))
        image_data_url = payload.get("image_data_url")
        if image_data_url is not None:
            image_data_url = str(image_data_url)
            if not self._valid_image_data_url(image_data_url):
                self._send_json(
                    {"error": "图片必须是 JPG、PNG、GIF 或 WebP 的 data URL，且不超过 8 MB"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

        if not text and not image_data_url:
            self._send_json({"error": "text or image_data_url is required"}, HTTPStatus.BAD_REQUEST)
            return
        if len(text) > 500:
            self._send_json({"error": "text is too long (max 500 characters)"}, HTTPStatus.BAD_REQUEST)
            return
        if mode not in ALLOWED_MODES:
            self._send_json({"error": "unsupported mode"}, HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        started = time.perf_counter()

        def emit(event: dict[str, Any], pause: float = 0.0) -> None:
            body = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii"))
            self.wfile.write(body)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
            if pause:
                time.sleep(pause)

        try:
            emit({"type": "state", "state": "listening", "label": "收到输入"}, 0.10)
            emit({"type": "transcript", "text": text or "图片输入"})

            if offline:
                reply = "网络开小差了。我已经保存当前状态，请稍后再试。"
                emit({"type": "state", "state": "offline", "label": "网络不可用"}, 0.16)
                emit({"type": "delta", "text": reply})
                self.engine.record_interaction(device_id, mode, text, reply, status="offline")
                emit(
                    {
                        "type": "complete",
                        "text": reply,
                        "profile": asdict(self.engine.get_profile(device_id)),
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                        "offline": True,
                        "provider": "offline-fallback",
                    }
                )
                self._finish_chunks()
                return

            emit({"type": "state", "state": "thinking", "label": "读取记忆并生成回复"}, 0.18)
            profile, memory_changes = self.engine.update_profile_from_text(device_id, text)
            if memory_changes:
                emit(
                    {
                        "type": "memory",
                        "changes": memory_changes,
                        "profile": asdict(profile),
                    },
                    0.08,
                )

            provider = "mock"
            reply = ""
            model_name = None
            if self.engine.stepfun.enabled:
                model_name = (
                    self.engine.stepfun.vision_model
                    if image_data_url
                    else self.engine.stepfun.chat_model
                )
                emit(
                    {
                        "type": "provider",
                        "provider": "stepfun",
                        "model": model_name,
                    }
                )
                messages = self.engine.build_stepfun_messages(
                    device_id, text, mode, profile, image_data_url=image_data_url
                )
                try:
                    for part in self.engine.stepfun.stream_chat(messages):
                        if not reply:
                            emit({"type": "state", "state": "speaking", "label": "阶跃流式回复"})
                        reply += part
                        emit({"type": "delta", "text": part})
                    if not reply.strip():
                        raise StepFunError("阶跃模型未返回文本")
                    provider = "stepfun"
                except StepFunError:
                    if reply:
                        suffix = " 抱歉，云端连接中断了，请再试一次。"
                        reply += suffix
                        emit({"type": "delta", "text": suffix})
                        provider = "stepfun-partial"
                    else:
                        emit(
                            {
                                "type": "provider",
                                "provider": "mock",
                                "fallback": True,
                                "label": "阶跃暂不可用，已切换本地兜底",
                            }
                        )

            if not reply:
                reply = self.engine.generate_reply(text, mode, profile)
                emit({"type": "state", "state": "speaking", "label": "本地兜底回复"})
                for part in chunk_text(reply):
                    emit({"type": "delta", "text": part}, 0.045)

            stored_text = f"[图片] {text}" if image_data_url else text
            self.engine.record_interaction(device_id, mode, stored_text, reply)
            emit(
                {
                    "type": "complete",
                    "text": reply,
                    "profile": asdict(profile),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                        "offline": False,
                        "provider": provider,
                        "model": model_name,
                }
            )
            emit({"type": "state", "state": "idle", "label": "待机"})
            self._finish_chunks()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _transcribe_audio(self, payload: dict[str, Any]) -> None:
        if not self.engine.stepfun.enabled:
            self._send_json({"error": "未配置阶跃音频服务"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        audio_base64 = payload.get("audio_base64")
        if not isinstance(audio_base64, str) or not audio_base64:
            self._send_json({"error": "audio_base64 is required"}, HTTPStatus.BAD_REQUEST)
            return
        if len(audio_base64) > 3_600_000:
            self._send_json({"error": "音频过长，请控制在 60 秒以内"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            text = self.engine.stepfun.transcribe_pcm(
                audio_base64,
                language=str(payload.get("language", "zh"))[:8],
            )
        except StepFunError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        self._send_json({"text": text, "provider": "stepfun", "model": self.engine.stepfun.asr_model})

    def _synthesize_audio(self, payload: dict[str, Any]) -> None:
        if not self.engine.stepfun.enabled:
            self._send_json({"error": "未配置阶跃音频服务"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        text = str(payload.get("text", "")).strip()
        mode = str(payload.get("mode", "assistant"))
        speech_rate = str(payload.get("speech_rate", "normal"))
        if mode not in ALLOWED_MODES:
            mode = "assistant"
        if speech_rate not in {"slow", "normal", "fast"}:
            speech_rate = "normal"
        try:
            audio, content_type = self.engine.stepfun.synthesize(text, speech_rate, mode)
        except StepFunError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return
        self._send_binary(audio, content_type)

    def _finish_chunks(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _read_json(self, max_length: int = 64_000) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid content length") from error
        if length <= 0 or length > max_length:
            raise ValueError("invalid request body")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _device_id(self, query: str) -> str:
        params = parse_qs(query)
        return self._clean_device_id(params.get("device_id", ["demo-pendant-01"])[0])

    @staticmethod
    def _clean_device_id(value: Any) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "", str(value))[:64]
        return cleaned or "demo-pendant-01"

    @staticmethod
    def _valid_image_data_url(value: str) -> bool:
        if len(value) > 11_000_000 or not value.startswith("data:image/"):
            return False
        header, separator, encoded = value.partition(",")
        if not separator or not encoded or ";base64" not in header:
            return False
        media_type = header[5:].split(";", 1)[0].lower()
        if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            return False
        try:
            import base64

            decoded_length = len(base64.b64decode(encoded, validate=True))
        except (ValueError, UnicodeError):
            return False
        return decoded_length <= 8 * 1024 * 1024

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (PUBLIC_DIR / relative).resolve()
        try:
            candidate.relative_to(PUBLIC_DIR.resolve())
        except ValueError:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


class LingXiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], engine: DemoEngine):
        super().__init__(server_address, LingXiHandler)
        self.engine = engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LingXi Pendant software demo")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="Bind port (default: 8787)")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB, help="SQLite database path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stepfun = StepFunClient.from_environment()
    engine = DemoEngine(args.database, stepfun=stepfun)
    server = LingXiServer((args.host, args.port), engine)
    print(f"LingXi demo is running at http://{args.host}:{args.port}")
    provider_label = "StepFun StepAudio" if stepfun.enabled else "local mock"
    print(f"AI provider: {provider_label}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LingXi demo...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
