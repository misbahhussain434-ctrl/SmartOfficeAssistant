from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_row_id TEXT,
  sender TEXT,
  receiver TEXT,
  subject TEXT,
  body TEXT NOT NULL DEFAULT '',
  summary TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'medium',
  assigned_to TEXT,
  status TEXT NOT NULL DEFAULT 'Pending',
  created_at TEXT NOT NULL,
  FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calendar_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_iso TEXT NOT NULL,
  end_iso TEXT NOT NULL,
  title TEXT NOT NULL
);
"""


def _ensure_parent_dir(db_path: str) -> None:
    db_file = Path(db_path)
    if db_file.parent:
        db_file.parent.mkdir(parents=True, exist_ok=True)


def make_connection(db_path: str) -> sqlite3.Connection:
    """
    Create a SQLite connection (no external dependencies).
    """
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def conn_scope(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = make_connection(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_email(
    conn: sqlite3.Connection,
    *,
    source_row_id: str | None,
    sender: str | None,
    receiver: str | None,
    subject: str | None,
    body: str,
    summary: str | None,
) -> int:
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO emails (source_row_id, sender, receiver, subject, body, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_row_id, sender, receiver, subject, body or "", summary, now_iso),
    )
    return int(cur.lastrowid)


def get_email(conn: sqlite3.Connection, email_id: int) -> Dict[str, Any] | None:
    row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return dict(row) if row else None


def count_rows(conn: sqlite3.Connection) -> Dict[str, int]:
    emails = conn.execute("SELECT COUNT(*) as c FROM emails").fetchone()["c"]
    tasks = conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
    events = conn.execute("SELECT COUNT(*) as c FROM calendar_events").fetchone()["c"]
    return {"emails": int(emails), "tasks": int(tasks), "calendar_events": int(events)}


def add_tasks(
    conn: sqlite3.Connection,
    *,
    email_id: int,
    tasks: Iterable[Dict[str, str]],
    assigned_to: str | None,
) -> int:
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    cur = conn.cursor()
    count = 0
    for t in tasks:
        title = (t.get("task") or "").strip()
        if not title:
            continue
        priority = (t.get("priority") or "medium").strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        cur.execute(
            """
            INSERT INTO tasks (email_id, title, priority, assigned_to, status, created_at)
            VALUES (?, ?, ?, ?, 'Pending', ?)
            """,
            (email_id, title[:500], priority, assigned_to, now_iso),
        )
        count += 1
    return count


def list_tasks(conn: sqlite3.Connection, *, filter_status: str = "All") -> List[Dict[str, Any]]:
    if filter_status == "All":
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (filter_status,)
        ).fetchall()
    return [dict(r) for r in rows]


def set_task_status(conn: sqlite3.Connection, task_id: int, status: str) -> bool:
    cur = conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    return cur.rowcount > 0


def list_calendar_events(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM calendar_events ORDER BY start_iso ASC").fetchall()
    return [dict(r) for r in rows]


def add_calendar_event(conn: sqlite3.Connection, *, start_iso: str, end_iso: str, title: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO calendar_events (start_iso, end_iso, title)
        VALUES (?, ?, ?)
        """,
        (start_iso, end_iso, title),
    )
    return int(cur.lastrowid)


def iter_tasks_with_email(
    conn: sqlite3.Connection,
    *,
    filter_status: str = "All",
) -> Iterator[Dict[str, Any]]:
    """
    Join tasks with the email subject for display.
    """
    if filter_status == "All":
        q = """
        SELECT
          t.*,
          e.subject as email_subject
        FROM tasks t
        LEFT JOIN emails e ON e.id = t.email_id
        ORDER BY t.created_at DESC
        """
        params: tuple[Any, ...] = ()
    else:
        q = """
        SELECT
          t.*,
          e.subject as email_subject
        FROM tasks t
        LEFT JOIN emails e ON e.id = t.email_id
        WHERE t.status = ?
        ORDER BY t.created_at DESC
        """
        params = (filter_status,)

    for row in conn.execute(q, params):
        yield dict(row)

