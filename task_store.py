"""One durable task store shared by the console, companion and device APIs."""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return closing(db)


def initialize_tasks(path):
    with connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
            conversation_id INTEGER, kind TEXT NOT NULL DEFAULT 'note',
            status TEXT NOT NULL DEFAULT 'pending', title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '', schedule_text TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '', scheduled_at TEXT NOT NULL DEFAULT '',
            remind_at TEXT NOT NULL DEFAULT '', reminder_state TEXT NOT NULL DEFAULT 'none',
            reminder_source TEXT NOT NULL DEFAULT 'none', checklist_json TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'system', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(device_id, conversation_id))""")
        db.execute("BEGIN IMMEDIATE")
        columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}
        additions = {'subject': "TEXT NOT NULL DEFAULT ''", 'priority': "TEXT NOT NULL DEFAULT 'normal'",
                     'completed_at': 'TEXT', 'reminder_acked_at': 'TEXT', 'deleted_at': 'TEXT'}
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {declaration}')
        db.execute('CREATE TABLE IF NOT EXISTS integration_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS learning_task_migration (legacy_id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL)')
        old = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='companion_learning_tasks'").fetchone()
        if old and not db.execute("SELECT 1 FROM integration_migrations WHERE name='shared-tasks-v1'").fetchone():
            for row in db.execute('SELECT * FROM companion_learning_tasks ORDER BY id').fetchall():
                state = ('dismissed' if row['reminder_acked_at'] or row['status'] == 'completed'
                         else 'scheduled' if row['remind_at'] else 'none')
                result = db.execute("""INSERT INTO tasks
                    (device_id,kind,status,title,subject,priority,scheduled_at,remind_at,
                     reminder_state,reminder_source,source,created_at,updated_at,completed_at,reminder_acked_at)
                    VALUES (?,'note',?,?,?,?,?,?,?,?,'system',?,?,?,?)""",
                    (row['device_id'], 'completed' if row['status'] == 'completed' else 'confirmed',
                     row['title'], row['subject'], row['priority'], row['due_at'] or '', row['remind_at'] or '',
                     state, 'explicit' if row['remind_at'] else 'none', row['created_at'], row['updated_at'],
                     row['completed_at'], row['reminder_acked_at']))
                db.execute('INSERT INTO learning_task_migration VALUES (?,?)', (row['id'], result.lastrowid))
            db.execute('INSERT INTO integration_migrations VALUES (?,?)',
                       ('shared-tasks-v1', datetime.now(timezone.utc).isoformat()))
        db.commit()


def learning_task(row):
    result = {key: row[key] for key in ('id', 'title', 'subject', 'priority', 'created_at', 'updated_at', 'completed_at')}
    result.update(due_at=row['scheduled_at'] or None, remind_at=row['remind_at'] or None,
                  status='completed' if row['status'] == 'completed' else 'pending',
                  confirmation_required=row['status'] == 'pending', reminder_source=row['reminder_source'])
    return result
