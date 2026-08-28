"""LingXi Pendant orchestration and system-console server.

The server deliberately uses only Python's standard library so the hackathon
demo can run without an install step. It serves the browser device simulator,
streams NDJSON interaction events, and persists lightweight profile memory in
SQLite.
"""

from __future__ import annotations

import argparse
import hmac
import json
import math
import mimetypes
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from providers.stepfun import StepFunClient, StepFunError
from device_protocol import (
    PROTOCOL_VERSION,
    DeviceProtocolError,
    DeviceSessionRegistry,
    protocol_manifest,
    validate_device_event,
)


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DEFAULT_DB = ROOT / "data" / "lingxi_demo.db"
ALLOWED_MODES = {"assistant", "companion", "translate"}
TASK_STATUSES = {"pending", "confirmed", "completed", "cancelled"}
TASK_KINDS = {"event", "reminder", "checklist", "plan", "note"}
TASK_REMINDER_STATES = {"none", "scheduled", "due", "dismissed"}
TASK_REMINDER_SOURCES = {"none", "explicit", "memory"}
MAX_CONVERSATIONS_PER_DEVICE = 50
MAX_TASKS_PER_DEVICE = 100
# China Standard Time is UTC+8 and has no daylight-saving transitions. A fixed
# standard-library timezone keeps the zero-install demo portable on Windows,
# where the IANA zone database is not necessarily present.
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Profile:
    device_id: str
    preferred_name: str = "朋友"
    speech_rate: str = "normal"
    updated_at: str = ""


class SlidingWindowRateLimiter:
    """Thread-safe in-process limiter for the public demo API."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._checks = 0

    def allow(
        self,
        subject: str,
        bucket: str,
        limit: int,
        window_seconds: float = 60.0,
    ) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        key = (subject, bucket)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, math.ceil(window_seconds - (now - events[0])))
                return False, retry_after
            events.append(now)
            self._checks += 1
            if self._checks % 256 == 0:
                self._events = defaultdict(
                    deque,
                    {event_key: values for event_key, values in self._events.items() if values},
                )
        return True, 0


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
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
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
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
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

                CREATE INDEX IF NOT EXISTS conversations_device_id_idx
                    ON conversations(device_id, id DESC);

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    conversation_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL CHECK(rating IN (-1, 1)),
                    correction TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    UNIQUE(device_id, conversation_id)
                );

                CREATE INDEX IF NOT EXISTS feedback_device_id_idx
                    ON feedback(device_id, id DESC);

                CREATE TABLE IF NOT EXISTS feedback_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('global', 'similar')),
                    context TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    uses INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(device_id, rule)
                );

                CREATE INDEX IF NOT EXISTS feedback_memories_device_id_idx
                    ON feedback_memories(device_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    conversation_id INTEGER,
                    kind TEXT NOT NULL CHECK(kind IN ('event', 'reminder', 'checklist', 'plan', 'note')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'confirmed', 'completed', 'cancelled')),
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    schedule_text TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    remind_at TEXT NOT NULL DEFAULT '',
                    reminder_state TEXT NOT NULL DEFAULT 'none'
                        CHECK(reminder_state IN ('none', 'scheduled', 'due', 'dismissed')),
                    reminder_source TEXT NOT NULL DEFAULT 'none'
                        CHECK(reminder_source IN ('none', 'explicit', 'memory')),
                    checklist_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL CHECK(source IN ('text', 'image', 'voice', 'system')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
                    UNIQUE(device_id, conversation_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_device_status
                    ON tasks(device_id, status, id DESC);

                """
            )
            task_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            migrations = {
                "scheduled_at": "ALTER TABLE tasks ADD COLUMN scheduled_at TEXT NOT NULL DEFAULT ''",
                "remind_at": "ALTER TABLE tasks ADD COLUMN remind_at TEXT NOT NULL DEFAULT ''",
                "reminder_state": "ALTER TABLE tasks ADD COLUMN reminder_state TEXT NOT NULL DEFAULT 'none'",
                "reminder_source": "ALTER TABLE tasks ADD COLUMN reminder_source TEXT NOT NULL DEFAULT 'none'",
            }
            for column, statement in migrations.items():
                if column not in task_columns:
                    connection.execute(statement)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_reminder_due "
                "ON tasks(reminder_state, remind_at, status)"
            )
            connection.execute("PRAGMA optimize")

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
            connection.execute("DELETE FROM tasks WHERE device_id = ?", (device_id,))
            connection.execute("DELETE FROM conversations WHERE device_id = ?", (device_id,))
            connection.execute("DELETE FROM feedback_memories WHERE device_id = ?", (device_id,))
            connection.execute("DELETE FROM profiles WHERE device_id = ?", (device_id,))
        return self.get_profile(device_id)

    def recent_history(self, device_id: str, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.mode, c.user_text, c.assistant_text, c.status, c.created_at,
                       (
                           SELECT f.rating FROM feedback AS f
                           WHERE f.conversation_id = c.id AND f.device_id = c.device_id
                           ORDER BY f.id DESC LIMIT 1
                       ) AS feedback_rating
                FROM conversations AS c
                WHERE c.device_id = ?
                ORDER BY c.id DESC
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
    ) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversations(
                    device_id, mode, user_text, assistant_text, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (device_id, mode, user_text, assistant_text, status, utc_now()),
            )
            interaction_id = int(cursor.lastrowid)
            connection.execute(
                """
                DELETE FROM conversations
                WHERE device_id = ? AND id NOT IN (
                    SELECT id FROM conversations
                    WHERE device_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (device_id, device_id, MAX_CONVERSATIONS_PER_DEVICE),
            )
        return interaction_id

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        raw_checklist = task.pop("checklist_json", "[]")
        try:
            checklist = json.loads(raw_checklist)
        except (TypeError, json.JSONDecodeError):
            checklist = []
        task["checklist"] = [str(item)[:80] for item in checklist if str(item).strip()][:8]
        return task

    @staticmethod
    def _task_kind(user_text: str, source: str) -> str | None:
        compact = " ".join(user_text.strip().split())
        if any(marker in compact for marker in ("讲座", "活动", "比赛", "会议", "报名", "海报")):
            return "event"
        if "提醒" in compact or "别忘" in compact or "到点" in compact:
            return "reminder"
        if any(marker in compact for marker in ("清单", "准备什么", "待办")):
            return "checklist"
        if any(marker in compact for marker in ("计划", "安排", "复习", "学习", "作业", "考试")):
            return "plan"
        if any(marker in compact for marker in ("任务", "记录", "记下", "保存")):
            return "note"
        return "note" if source == "image" else None

    @staticmethod
    def _task_title(user_text: str, assistant_text: str, kind: str) -> str:
        combined = f"{user_text} {assistant_text}"
        if kind == "event":
            if "讲座" in combined:
                return "校园讲座"
            if "比赛" in combined:
                return "校园比赛"
            if "报名" in combined:
                return "活动报名"
            return "校园活动"
        if kind == "plan":
            if "复习" in combined:
                return "复习计划"
            if "作业" in combined:
                return "作业计划"
            if "考试" in combined:
                return "考试准备计划"
            return "学习计划"
        if kind == "reminder":
            return "提醒事项"
        if kind == "checklist":
            return "准备清单"
        for candidate in (user_text, assistant_text):
            clean = re.sub(r"^(?:请|帮我|请帮我|把|将)\s*", "", " ".join(candidate.split()))
            clean = re.split(r"[。！？；\n]", clean)[0].strip(" ：:，,")
            if clean:
                return clean[:32]
        return "灵犀任务"

    @staticmethod
    def _task_schedule_text(user_text: str, assistant_text: str) -> str:
        combined = " ".join(f"{user_text} {assistant_text}".split())
        values: list[str] = []
        date_match = re.search(
            r"(?:今天|今晚|明天|明晚|后天|本周[一二三四五六日天]|下周[一二三四五六日天]|\d{1,2}月\d{1,2}日)",
            combined,
        )
        time_match = re.search(r"\d{1,2}[:：]\d{2}", combined)
        reminder_match = re.search(r"提前[^，。；\n]{1,12}提醒", combined)
        for match in (date_match, time_match, reminder_match):
            if match:
                value = match.group(0).strip().replace("：", ":")
                if value and value not in values:
                    values.append(value[:24])
        return " · ".join(values[:3])

    @staticmethod
    def _chinese_number(value: str) -> int | None:
        if value.isdigit():
            return int(value)
        values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if value == "十":
            return 10
        if "十" in value:
            before, _, after = value.partition("十")
            tens = values.get(before, 1) if before else 1
            ones = values.get(after, 0) if after else 0
            return tens * 10 + ones
        return values.get(value)

    @classmethod
    def _reminder_lead_minutes(cls, text: str) -> int | None:
        """Read a bounded lead time such as ``提前一小时提醒`` from text."""
        compact = " ".join(text.strip().split()).replace("：", ":")
        lead = re.search(
            r"提前\s*([0-9一二两三四五六七八九十]+)\s*(小时|分钟|分)\s*提醒",
            compact,
        )
        if not lead:
            return None
        amount = cls._chinese_number(lead.group(1))
        if not amount or amount > 168:
            return None
        return amount * 60 if lead.group(2) == "小时" else amount

    @classmethod
    def _reminder_default_from_memories(
        cls, feedback_memories: list[dict[str, Any]] | None
    ) -> int | None:
        """Use only memories selected for this task, never all visitor data."""
        for memory in feedback_memories or []:
            minutes = cls._reminder_lead_minutes(str(memory.get("rule", "")))
            if minutes is not None:
                return minutes
        return None

    @classmethod
    def _task_timing(
        cls,
        user_text: str,
        default_reminder_minutes: int | None = None,
        schedule_text: str | None = None,
    ) -> tuple[str, str, str]:
        """Extract an explicit time and resolve an explicit or remembered lead.

        A task must always contain both a date and a clock time. For image
        tasks, ``schedule_text`` may include structured facts extracted from
        the image; the reminder lead itself still comes only from the user's
        wording or a selected feedback-memory rule.
        """
        compact = " ".join((schedule_text or user_text).strip().split()).replace("：", ":")
        user_compact = " ".join(user_text.strip().split()).replace("：", ":")
        clock = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", compact)
        if not clock:
            return "", "", "none"
        now = datetime.now(LOCAL_TIMEZONE)
        event_date = None
        month_day = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", compact)
        if month_day:
            month, day = int(month_day.group(1)), int(month_day.group(2))
            try:
                event_date = now.date().replace(year=now.year, month=month, day=day)
            except ValueError:
                return "", "", "none"
            if event_date < now.date():
                try:
                    event_date = event_date.replace(year=now.year + 1)
                except ValueError:
                    return "", "", "none"
        elif "明天" in compact or "明晚" in compact:
            event_date = (now + timedelta(days=1)).date()
        elif "后天" in compact:
            event_date = (now + timedelta(days=2)).date()
        elif "今天" in compact or "今晚" in compact:
            event_date = now.date()
        else:
            weekday = re.search(r"(本|这|下)周([一二三四五六日天])", compact)
            if weekday:
                weekday_index = {
                    "一": 0,
                    "二": 1,
                    "三": 2,
                    "四": 3,
                    "五": 4,
                    "六": 5,
                    "日": 6,
                    "天": 6,
                }[weekday.group(2)]
                if weekday.group(1) == "下":
                    days_until = 7 - now.weekday() + weekday_index
                else:
                    days_until = weekday_index - now.weekday()
                    if days_until < 0:
                        # “本周一”在周四说已经是过去的日期，不能悄悄改排到
                        # 下一周；用户需要给出一个仍有效的明确日期。
                        return "", "", "none"
                event_date = (now + timedelta(days=days_until)).date()
        if event_date is None:
            return "", "", "none"

        event_at = datetime(
            event_date.year,
            event_date.month,
            event_date.day,
            int(clock.group(1)),
            int(clock.group(2)),
            tzinfo=LOCAL_TIMEZONE,
        ).astimezone(timezone.utc)
        if event_at <= now.astimezone(timezone.utc):
            # A same-day clock time that already passed should never fire a
            # surprise immediate reminder. Ask for a future explicit date.
            return "", "", "none"
        scheduled_at = event_at.isoformat(timespec="seconds")
        explicit_minutes = cls._reminder_lead_minutes(user_compact)
        if explicit_minutes is not None:
            reminder_at = event_at - timedelta(minutes=explicit_minutes)
            return scheduled_at, reminder_at.isoformat(timespec="seconds"), "explicit"
        if re.search(r"(?:不|不用|无需|别)\s*(?:再)?提醒", user_compact):
            return scheduled_at, "", "none"
        if default_reminder_minutes is not None:
            reminder_at = event_at - timedelta(minutes=default_reminder_minutes)
            return scheduled_at, reminder_at.isoformat(timespec="seconds"), "memory"
        return scheduled_at, "", "none"

    @staticmethod
    def _task_location(user_text: str, assistant_text: str) -> str:
        combined = " ".join(f"{user_text} {assistant_text}".split())
        explicit = re.search(r"(?:地点|地址)[:：]\s*([^，。；\n]{2,30})", combined)
        if explicit:
            return explicit.group(1).strip()[:40]
        campus = re.search(
            r"((?:主楼|教学楼|图书馆|实验室|体育馆|礼堂|报告厅|校区)"
            r"[A-Za-z0-9一二三四五六七八九十号楼\- ]{0,16})",
            combined,
        )
        return campus.group(1).strip()[:40] if campus else ""

    @staticmethod
    def _task_checklist(user_text: str, assistant_text: str, kind: str) -> list[str]:
        checklist = [
            " ".join(item.split())[:80]
            for item in re.findall(
                r"(?:^|[。；\n])\s*(?:\d+[.、)]|[一二三四五六]+[、.])\s*([^。；\n]{2,80})",
                assistant_text,
            )
        ]
        if kind == "event":
            checklist.insert(0, "确认活动时间与地点")
            if "报名" in f"{user_text} {assistant_text}":
                checklist.append("完成活动报名")
        elif kind in {"plan", "checklist"} and not checklist:
            checklist = [
                " ".join(item.split())[:80]
                for item in re.split(r"[。；\n]", assistant_text)
                if len(" ".join(item.split())) >= 4
            ][:3]
        deduplicated: list[str] = []
        for item in checklist:
            if item and item not in deduplicated:
                deduplicated.append(item)
        return deduplicated[:8]

    def create_task_from_interaction(
        self,
        device_id: str,
        conversation_id: int,
        user_text: str,
        assistant_text: str,
        source: str = "text",
        feedback_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        safe_source = source if source in {"text", "image", "voice", "system"} else "text"
        kind = self._task_kind(user_text, safe_source)
        if kind is None or kind not in TASK_KINDS:
            return None
        title = self._task_title(user_text, assistant_text, kind)
        summary = " ".join(assistant_text.strip().split())[:280]
        schedule_text = self._task_schedule_text(user_text, assistant_text)
        location = self._task_location(user_text, assistant_text)
        timing_text = f"{user_text} {assistant_text}" if safe_source == "image" else user_text
        scheduled_at, remind_at, reminder_source = self._task_timing(
            user_text,
            self._reminder_default_from_memories(feedback_memories),
            schedule_text=timing_text,
        )
        reminder_state = "scheduled" if remind_at else "none"
        checklist = self._task_checklist(user_text, assistant_text, kind)
        now = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks(
                    device_id, conversation_id, kind, status, title, summary,
                    schedule_text, location, scheduled_at, remind_at, reminder_state, reminder_source,
                    checklist_json, source, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, conversation_id) DO UPDATE SET
                    kind = excluded.kind,
                    title = excluded.title,
                    summary = excluded.summary,
                    schedule_text = excluded.schedule_text,
                    location = excluded.location,
                    scheduled_at = excluded.scheduled_at,
                    remind_at = excluded.remind_at,
                    reminder_state = excluded.reminder_state,
                    reminder_source = excluded.reminder_source,
                    checklist_json = excluded.checklist_json,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    device_id,
                    conversation_id,
                    kind,
                    title,
                    summary,
                    schedule_text,
                    location,
                    scheduled_at,
                    remind_at,
                    reminder_state,
                    reminder_source,
                    json.dumps(checklist, ensure_ascii=False),
                    safe_source,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE device_id = ? AND conversation_id = ?",
                (device_id, conversation_id),
            ).fetchone()
            connection.execute(
                """
                DELETE FROM tasks
                WHERE device_id = ? AND id NOT IN (
                    SELECT id FROM tasks WHERE device_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (device_id, device_id, MAX_TASKS_PER_DEVICE),
            )
        return self._task_row(row) if row else None

    def list_tasks(
        self,
        device_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.mark_due_reminders()
        safe_limit = max(1, min(limit, MAX_TASKS_PER_DEVICE))
        if status is not None and status not in TASK_STATUSES:
            raise ValueError("unsupported task status")
        query = "SELECT * FROM tasks WHERE device_id = ?"
        parameters: list[Any] = [device_id]
        if status:
            query += " AND status = ?"
            parameters.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(safe_limit)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._task_row(row) for row in rows]

    def update_task_status(
        self,
        device_id: str,
        task_id: int,
        status: str,
    ) -> dict[str, Any]:
        if status not in TASK_STATUSES:
            raise ValueError("unsupported task status")
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT reminder_state, remind_at FROM tasks WHERE id = ? AND device_id = ?",
                (task_id, device_id),
            ).fetchone()
            if existing is None:
                raise LookupError("task not found for this visitor")
            now = utc_now()
            reminder_state = str(existing["reminder_state"] or "none")
            remind_at = str(existing["remind_at"] or "")
            if status in {"completed", "cancelled"} and reminder_state in {"scheduled", "due"}:
                reminder_state = "dismissed"
            elif status == "confirmed" and reminder_state == "dismissed" and remind_at > now:
                reminder_state = "scheduled"
            cursor = connection.execute(
                """
                UPDATE tasks SET status = ?, reminder_state = ?, updated_at = ?
                WHERE id = ? AND device_id = ?
                """,
                (status, reminder_state, now, task_id, device_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("task not found for this visitor")
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ? AND device_id = ?",
                (task_id, device_id),
            ).fetchone()
        if row is None:
            raise LookupError("task not found for this visitor")
        return self._task_row(row)

    def mark_due_reminders(self, now: str | None = None) -> int:
        """Persist reminders that became due while no browser was open."""
        current_time = now or utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET reminder_state = 'due', updated_at = ?
                WHERE status = 'confirmed'
                  AND reminder_state = 'scheduled'
                  AND remind_at != ''
                  AND remind_at <= ?
                """,
                (current_time, current_time),
            )
        return int(cursor.rowcount)

    def record_feedback(
        self,
        device_id: str,
        conversation_id: int,
        rating: int,
        correction: str,
    ) -> dict[str, Any]:
        clean_correction = " ".join(correction.strip().split())[:240]
        with self._connection() as connection:
            conversation = connection.execute(
                """
                SELECT id, user_text FROM conversations
                WHERE id = ? AND device_id = ?
                """,
                (conversation_id, device_id),
            ).fetchone()
            if conversation is None:
                raise ValueError("interaction not found for this visitor")
            connection.execute(
                """
                INSERT INTO feedback(device_id, conversation_id, rating, correction, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id, conversation_id) DO UPDATE SET
                    rating = excluded.rating,
                    correction = excluded.correction,
                    created_at = excluded.created_at
                """,
                (device_id, conversation_id, rating, clean_correction, utc_now()),
            )
            feedback_id = int(
                connection.execute(
                    "SELECT id FROM feedback WHERE device_id = ? AND conversation_id = ?",
                    (device_id, conversation_id),
                ).fetchone()["id"]
            )

            memory = None
            if clean_correction:
                scope = self._feedback_scope(clean_correction)
                now = utc_now()
                connection.execute(
                    """
                    INSERT INTO feedback_memories(
                        device_id, scope, context, rule, uses, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, ?, ?)
                    ON CONFLICT(device_id, rule) DO UPDATE SET
                        scope = excluded.scope,
                        context = excluded.context,
                        updated_at = excluded.updated_at
                    """,
                    (
                        device_id,
                        scope,
                        str(conversation["user_text"])[:500],
                        clean_correction,
                        now,
                        now,
                    ),
                )
                memory_row = connection.execute(
                    """
                    SELECT id, scope, context, rule, uses, updated_at
                    FROM feedback_memories WHERE device_id = ? AND rule = ?
                    """,
                    (device_id, clean_correction),
                ).fetchone()
                memory = dict(memory_row) if memory_row else None

        return {
            "feedback_id": feedback_id,
            "memory": memory,
            "metrics": self.memory_metrics(device_id),
        }

    def search_feedback_memories(
        self,
        device_id: str,
        task_text: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 5))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, scope, context, rule, uses, updated_at
                FROM feedback_memories
                WHERE device_id = ?
                ORDER BY updated_at DESC
                LIMIT 100
                """,
                (device_id,),
            ).fetchall()

            task_fingerprint = self._text_fingerprint(task_text)
            ranked: list[tuple[float, sqlite3.Row]] = []
            for row in rows:
                if row["scope"] == "global":
                    score = 1.0
                else:
                    memory_fingerprint = self._text_fingerprint(str(row["context"]))
                    union = task_fingerprint | memory_fingerprint
                    score = len(task_fingerprint & memory_fingerprint) / len(union) if union else 0.0
                if score >= 0.08:
                    ranked.append((score, row))

            selected = sorted(
                ranked,
                key=lambda item: (item[0], item[1]["updated_at"]),
                reverse=True,
            )[:safe_limit]
            selected_ids = [int(row["id"]) for _, row in selected]
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                connection.execute(
                    f"UPDATE feedback_memories SET uses = uses + 1 WHERE id IN ({placeholders})",
                    selected_ids,
                )

        return [
            {
                "id": int(row["id"]),
                "scope": row["scope"],
                "rule": row["rule"],
                "score": round(score, 3),
                "estimated_tokens": self._estimate_tokens(str(row["rule"])),
            }
            for score, row in selected
        ]

    def memory_metrics(self, device_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            memory_row = connection.execute(
                """
                SELECT COUNT(*) AS memory_count, COALESCE(SUM(uses), 0) AS recall_uses,
                       COALESCE(SUM(LENGTH(rule)), 0) AS stored_characters
                FROM feedback_memories WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            feedback_row = connection.execute(
                """
                SELECT COUNT(*) AS feedback_count,
                       COALESCE(SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END), 0) AS positive_count
                FROM feedback WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
        feedback_count = int(feedback_row["feedback_count"])
        positive_count = int(feedback_row["positive_count"])
        return {
            "memory_count": int(memory_row["memory_count"]),
            "feedback_count": feedback_count,
            "positive_rate": round(positive_count / feedback_count, 3) if feedback_count else None,
            "recall_uses": int(memory_row["recall_uses"]),
            "stored_characters": int(memory_row["stored_characters"]),
        }

    def list_feedback_memories(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, scope, context, rule, uses, created_at, updated_at
                FROM feedback_memories
                WHERE device_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (device_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_feedback_memory(self, device_id: str, memory_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM feedback_memories WHERE id = ? AND device_id = ?",
                (memory_id, device_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _feedback_scope(rule: str) -> str:
        global_markers = ("每次", "总是", "回答", "语气", "格式", "简短", "详细", "称呼")
        domain_markers = (
            "活动",
            "讲座",
            "会议",
            "比赛",
            "课程",
            "复习",
            "作业",
            "考试",
            "图书馆",
            "通勤",
        )
        if "以后" in rule and not any(marker in rule for marker in domain_markers):
            return "global"
        return "global" if any(marker in rule for marker in global_markers) else "similar"

    @staticmethod
    def _text_fingerprint(text: str) -> set[str]:
        lowered = text.lower()
        words = set(re.findall(r"[a-z0-9]{2,}", lowered))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        words.update(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
        return words

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        other_count = len(text) - chinese_count
        return max(1, chinese_count + math.ceil(other_count / 4))

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
            f"收到，{name}。这是灵犀控制台的本地兜底回复：输入、记忆读取、"
            f"流式输出和语音状态均正常，在线模型恢复后会继续回答“{compact[:24]}”。"
        )

    def build_stepfun_messages(
        self,
        device_id: str,
        text: str,
        mode: str,
        profile: Profile,
        image_data_url: str | None = None,
        feedback_memories: list[dict[str, Any]] | None = None,
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
        if feedback_memories:
            rules = "；".join(
                f"{index}. {memory['rule']}" for index, memory in enumerate(feedback_memories, 1)
            )
            system_prompt += (
                "以下规则来自用户对过往结果的主动反馈。只在与当前任务相关且不冲突时遵循，"
                f"不要向用户复述规则本身：{rules}"
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
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url, "detail": "high"},
                        },
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
    server_version = "LingXi/0.5"
    sys_version = ""

    @property
    def engine(self) -> DemoEngine:
        return self.server.engine  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_HEAD(self) -> None:  # noqa: N802
        """Serve static resource headers for uptime checks and CDNs."""
        parsed = urlparse(self.path)
        if not self._enforce_rate_limit("read", 240):
            return
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", "GET, POST")
            self._send_security_headers()
            self.end_headers()
            return
        self._serve_static(parsed.path, head_only=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._enforce_rate_limit("read", 240):
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "service": "lingxi-demo", "time": utc_now()})
            return
        if parsed.path == "/api/capabilities":
            capabilities = self.engine.stepfun.capabilities()
            capabilities["device_bridge"] = {
                "protocol_version": PROTOCOL_VERSION,
                "ingest_enabled": bool(os.getenv("LINGXI_DEVICE_TOKEN", "").strip()),
            }
            capabilities["task_center"] = {
                "enabled": True,
                "statuses": sorted(TASK_STATUSES),
                "kinds": sorted(TASK_KINDS),
                "reminders": {
                    "enabled": True,
                    "states": sorted(TASK_REMINDER_STATES),
                    "sources": sorted(TASK_REMINDER_SOURCES),
                    "delivery": "persistent scheduler + console polling",
                },
            }
            self._send_json(capabilities)
            return
        if parsed.path == "/api/device/protocol":
            self._send_json(protocol_manifest())
            return
        if parsed.path == "/api/profile":
            device_id = self._device_id(parsed.query)
            self._send_json(asdict(self.engine.get_profile(device_id)))
            return
        if parsed.path == "/api/history":
            device_id = self._device_id(parsed.query)
            self._send_json({"items": self.engine.recent_history(device_id)})
            return
        if parsed.path == "/api/tasks":
            device_id = self._device_id(parsed.query)
            params = parse_qs(parsed.query)
            status = params.get("status", [None])[0]
            try:
                tasks = self.engine.list_tasks(device_id, status=status)
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"items": tasks})
            return
        if parsed.path == "/api/memory/metrics":
            device_id = self._device_id(parsed.query)
            self._send_json(self.engine.memory_metrics(device_id))
            return
        if parsed.path == "/api/memory/items":
            device_id = self._device_id(parsed.query)
            self._send_json({"items": self.engine.list_feedback_memories(device_id)})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        post_limits = {
            "/api/interactions": ("interactions", 20),
            "/api/audio/transcribe": ("audio", 12),
            "/api/audio/speech": ("audio", 12),
            "/api/feedback": ("feedback", 40),
            "/api/tasks/update": ("task-update", 60),
            "/api/memory/delete": ("memory-delete", 30),
            "/api/device/events": ("device-events", 240),
            "/api/reset": ("reset", 8),
        }
        bucket, limit = post_limits.get(parsed.path, ("write", 60))
        if not self._enforce_rate_limit(bucket, limit):
            return
        try:
            if parsed.path == "/api/audio/transcribe":
                max_length = 4_000_000
            elif parsed.path == "/api/interactions":
                max_length = 12_000_000
            elif parsed.path == "/api/device/events":
                max_length = 256_000
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
        if parsed.path == "/api/feedback":
            self._record_feedback(payload)
            return
        if parsed.path == "/api/tasks/update":
            self._update_task(payload)
            return
        if parsed.path == "/api/memory/delete":
            self._delete_memory(payload)
            return
        if parsed.path == "/api/device/events":
            self._handle_device_event(payload)
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
        self._send_security_headers()
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
                interaction_id = self.engine.record_interaction(
                    device_id, mode, text, reply, status="offline"
                )
                emit(
                    {
                        "type": "complete",
                        "interaction_id": interaction_id,
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
            emit(
                {
                    "type": "plan",
                    "steps": [
                        "识别任务与当前模式",
                        "调用 feedback_memory.search",
                        "调用多模态模型生成结果",
                        "提取并保存可执行任务",
                    ],
                }
            )
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

            recall_started = time.perf_counter()
            feedback_memories = self.engine.search_feedback_memories(device_id, text, limit=3)
            recall_ms = round((time.perf_counter() - recall_started) * 1000, 2)
            estimated_memory_tokens = sum(
                int(memory["estimated_tokens"]) for memory in feedback_memories
            )
            emit(
                {
                    "type": "tool",
                    "name": "feedback_memory.search",
                    "status": "complete",
                    "hits": len(feedback_memories),
                    "latency_ms": recall_ms,
                    "estimated_tokens": estimated_memory_tokens,
                }
            )
            if feedback_memories:
                emit(
                    {
                        "type": "memory_recall",
                        "count": len(feedback_memories),
                        "latency_ms": recall_ms,
                        "estimated_tokens": estimated_memory_tokens,
                        "items": [memory["rule"] for memory in feedback_memories],
                    }
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
                    device_id,
                    text,
                    mode,
                    profile,
                    image_data_url=image_data_url,
                    feedback_memories=feedback_memories,
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
            interaction_id = self.engine.record_interaction(device_id, mode, stored_text, reply)
            task = None
            if mode == "assistant":
                task_started = time.perf_counter()
                task = self.engine.create_task_from_interaction(
                    device_id,
                    interaction_id,
                    text,
                    reply,
                    source="image" if image_data_url else "text",
                    feedback_memories=feedback_memories,
                )
                if task:
                    task_ms = round((time.perf_counter() - task_started) * 1000, 2)
                    emit(
                        {
                            "type": "tool",
                            "name": "task.create",
                            "status": "complete",
                            "hits": 1,
                            "latency_ms": task_ms,
                            "estimated_tokens": 0,
                        }
                    )
                    emit({"type": "task", "action": "created", "task": task})
            emit(
                {
                    "type": "complete",
                    "interaction_id": interaction_id,
                    "task_id": task["id"] if task else None,
                    "text": reply,
                    "profile": asdict(profile),
                    "memory_metrics": self.engine.memory_metrics(device_id),
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

    def _record_feedback(self, payload: dict[str, Any]) -> None:
        device_id = self._clean_device_id(payload.get("device_id", ""))
        interaction_id = payload.get("interaction_id")
        rating = payload.get("rating")
        correction = str(payload.get("correction", ""))
        if not isinstance(interaction_id, int) or isinstance(interaction_id, bool):
            self._send_json({"error": "interaction_id must be an integer"}, HTTPStatus.BAD_REQUEST)
            return
        if rating not in {-1, 1}:
            self._send_json({"error": "rating must be -1 or 1"}, HTTPStatus.BAD_REQUEST)
            return
        if len(correction) > 240:
            self._send_json({"error": "correction is too long (max 240 characters)"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = self.engine.record_feedback(
                device_id,
                interaction_id,
                int(rating),
                correction,
            )
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            return
        self._send_json({"ok": True, **result})

    def _update_task(self, payload: dict[str, Any]) -> None:
        device_id = self._clean_device_id(payload.get("device_id", ""))
        task_id = payload.get("task_id")
        status = str(payload.get("status", ""))
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            self._send_json({"error": "task_id must be a positive integer"}, HTTPStatus.BAD_REQUEST)
            return
        if status not in TASK_STATUSES:
            self._send_json({"error": "unsupported task status"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            task = self.engine.update_task_status(device_id, task_id, status)
        except LookupError as error:
            self._send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            return
        self._send_json({"ok": True, "task": task})

    def _delete_memory(self, payload: dict[str, Any]) -> None:
        device_id = self._clean_device_id(payload.get("device_id", ""))
        memory_id = payload.get("memory_id")
        if not isinstance(memory_id, int) or isinstance(memory_id, bool) or memory_id <= 0:
            self._send_json({"error": "memory_id must be a positive integer"}, HTTPStatus.BAD_REQUEST)
            return
        if not self.engine.delete_feedback_memory(device_id, memory_id):
            self._send_json({"error": "memory not found for this visitor"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(
            {
                "ok": True,
                "memory_id": memory_id,
                "metrics": self.engine.memory_metrics(device_id),
            }
        )

    def _handle_device_event(self, payload: dict[str, Any]) -> None:
        expected_token = os.getenv("LINGXI_DEVICE_TOKEN", "").strip()
        if not expected_token:
            self._send_json(
                {"error": "device ingest is disabled until hardware pairing"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {expected_token}"
        if not hmac.compare_digest(supplied, expected):
            self._send_json({"error": "invalid device token"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            event = validate_device_event(payload)
            session = self.server.device_sessions.accept(event)  # type: ignore[attr-defined]
        except DeviceProtocolError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(
            {
                "version": PROTOCOL_VERSION,
                "type": "event.ack",
                "device_id": event["device_id"],
                "seq": event["seq"],
                "session": session,
                "accepted_at": utc_now(),
            },
            HTTPStatus.ACCEPTED,
        )

    def _finish_chunks(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _enforce_rate_limit(self, bucket: str, limit: int) -> bool:
        forwarded_ip = self.headers.get("X-Real-IP", "").strip()
        client_ip = forwarded_ip or str(self.client_address[0])
        allowed, retry_after = self.server.rate_limiter.allow(  # type: ignore[attr-defined]
            client_ip,
            bucket,
            limit,
        )
        if allowed:
            return True
        self._send_json(
            {"error": "请求过于频繁，请稍后再试", "retry_after": retry_after},
            HTTPStatus.TOO_MANY_REQUESTS,
            extra_headers={"Retry-After": str(retry_after)},
        )
        return False

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

    def _serve_static(self, request_path: str, head_only: bool = False) -> None:
        if request_path in ("", "/", "/console", "/console/"):
            relative = "index.html"
        elif request_path in ("/demo", "/demo/"):
            relative = "demo.html"
        else:
            relative = request_path.lstrip("/")
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
        self._send_security_headers(include_csp=True)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_json(
        self,
        payload: Any,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_security_headers(self, include_csp: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(self), payment=(), usb=()",
        )
        if include_csp:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )


class LingXiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], engine: DemoEngine):
        super().__init__(server_address, LingXiHandler)
        self.engine = engine
        self.rate_limiter = SlidingWindowRateLimiter()
        self.device_sessions = DeviceSessionRegistry()
        self._scheduler_stop = threading.Event()
        self._reminder_thread = threading.Thread(
            target=self._run_reminder_scheduler,
            name="lingxi-reminder-scheduler",
            daemon=True,
        )
        self.engine.mark_due_reminders()
        self._reminder_thread.start()

    def _run_reminder_scheduler(self) -> None:
        while not self._scheduler_stop.wait(15):
            try:
                due_count = self.engine.mark_due_reminders()
                if due_count:
                    print(f"[reminder] marked {due_count} task(s) due")
            except (OSError, sqlite3.Error) as error:
                print(f"[reminder] scheduler error: {error}")

    def server_close(self) -> None:
        self._scheduler_stop.set()
        if self._reminder_thread.is_alive():
            self._reminder_thread.join(timeout=1)
        super().server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LingXi Pendant system console")
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
