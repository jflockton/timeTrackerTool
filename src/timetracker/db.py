"""SQLite schema and repository for tasks and daily time entries.

Tasks get a generated 8-hex-char ID at creation; all time is logged
against that ID, so renaming a task never orphans its history.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

APP_DIR_NAME = "timeTrackerTool"
DB_FILE_NAME = "timetracker.db"


def default_db_path() -> Path:
    """Platform-appropriate data file location, overridable for testing."""
    override = os.environ.get("TIMETRACKER_DB")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME / DB_FILE_NAME


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_timetracker_tables(conn)
    return conn


def ensure_timetracker_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id    TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL,
            archived   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS time_entries (
            task_id    TEXT NOT NULL REFERENCES tasks(task_id),
            entry_date TEXT NOT NULL,
            seconds    REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (task_id, entry_date)
        );
        """
    )
    # Migration for databases created before mini-mode existed
    columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1]
               for row in conn.execute("PRAGMA table_info(tasks)")}
    if "emoji" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN emoji TEXT NOT NULL DEFAULT ''")
    conn.commit()


def create_task(conn: sqlite3.Connection, name: str) -> str:
    """Create a task and return its generated ID."""
    name = name.strip()
    if not name:
        raise ValueError("task name must not be empty")
    while True:
        task_id = uuid.uuid4().hex[:8]
        try:
            conn.execute(
                "INSERT INTO tasks (task_id, name, created_at) VALUES (?, ?, ?)",
                (task_id, name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return task_id
        except sqlite3.IntegrityError:
            continue  # 8-hex-char collision: astronomically rare, just redraw


def list_tasks(conn: sqlite3.Connection, include_archived: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM tasks"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY created_at"
    return list(conn.execute(sql))


def rename_task(conn: sqlite3.Connection, task_id: str, new_name: str) -> None:
    conn.execute("UPDATE tasks SET name = ? WHERE task_id = ?", (new_name.strip(), task_id))
    conn.commit()


def set_task_emoji(conn: sqlite3.Connection, task_id: str, emoji: str) -> None:
    conn.execute("UPDATE tasks SET emoji = ? WHERE task_id = ?", (emoji.strip(), task_id))
    conn.commit()


def archive_task(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("UPDATE tasks SET archived = 1 WHERE task_id = ?", (task_id,))
    conn.commit()


def add_seconds(conn: sqlite3.Connection, task_id: str, entry_date: str, seconds: float) -> None:
    """Add seconds to a task's cumulative total for a date (upsert)."""
    if seconds <= 0:
        return
    conn.execute(
        """
        INSERT INTO time_entries (task_id, entry_date, seconds) VALUES (?, ?, ?)
        ON CONFLICT (task_id, entry_date) DO UPDATE SET seconds = seconds + excluded.seconds
        """,
        (task_id, entry_date, seconds),
    )
    conn.commit()


def seconds_for_day(conn: sqlite3.Connection, task_id: str, entry_date: str) -> float:
    row = conn.execute(
        "SELECT seconds FROM time_entries WHERE task_id = ? AND entry_date = ?",
        (task_id, entry_date),
    ).fetchone()
    return float(row["seconds"]) if row else 0.0


def entries_between(
    conn: sqlite3.Connection, first_date: str, last_date: str
) -> dict[tuple[str, str], float]:
    """(task_id, entry_date) -> seconds for all entries in the inclusive range."""
    rows = conn.execute(
        "SELECT task_id, entry_date, seconds FROM time_entries"
        " WHERE entry_date BETWEEN ? AND ?",
        (first_date, last_date),
    )
    return {(r["task_id"], r["entry_date"]): float(r["seconds"]) for r in rows}
