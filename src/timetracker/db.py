"""SQLite schema and repository for tasks and daily time entries.

Tasks get a generated 8-hex-char ID at creation; all time is logged
against that ID, so renaming a task never orphans its history.
"""

from __future__ import annotations

import os
import platform
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

APP_DIR_NAME = "timeTrackerTool"
DB_FILE_NAME = "timetracker.db"

# Which machine wrote a time entry. Makes cross-machine merges idempotent:
# the same (task, date, machine) row can never be double-counted.
MACHINE = re.sub(r"[^A-Za-z0-9._-]", "", platform.node()) or "local"


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
            origin     TEXT NOT NULL DEFAULT '',
            seconds    REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (task_id, entry_date, origin)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # Migration for databases created before mini-mode existed
    columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1]
               for row in conn.execute("PRAGMA table_info(tasks)")}
    if "emoji" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN emoji TEXT NOT NULL DEFAULT ''")
    # Migration for databases created before cross-machine origins existed:
    # the primary key changes, so the table has to be rebuilt.
    entry_columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1]
                     for row in conn.execute("PRAGMA table_info(time_entries)")}
    if "origin" not in entry_columns:
        conn.executescript(
            """
            ALTER TABLE time_entries RENAME TO time_entries_old;
            CREATE TABLE time_entries (
                task_id    TEXT NOT NULL REFERENCES tasks(task_id),
                entry_date TEXT NOT NULL,
                origin     TEXT NOT NULL DEFAULT '',
                seconds    REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (task_id, entry_date, origin)
            );
            INSERT INTO time_entries (task_id, entry_date, origin, seconds)
                SELECT task_id, entry_date, '', seconds FROM time_entries_old;
            DROP TABLE time_entries_old;
            """
        )
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


def unarchive_task(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("UPDATE tasks SET archived = 0 WHERE task_id = ?", (task_id,))
    conn.commit()


def delete_task(conn: sqlite3.Connection, task_id: str) -> None:
    """Permanently remove a task AND all its logged time. No undo."""
    conn.execute("DELETE FROM time_entries WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
    conn.commit()


def total_seconds(conn: sqlite3.Connection, task_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) AS s FROM time_entries WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return float(row["s"])


def add_seconds(conn: sqlite3.Connection, task_id: str, entry_date: str,
                seconds: float, origin: str | None = None) -> None:
    """Add seconds to a task's cumulative total for a date (upsert),
    recorded against this machine's origin by default."""
    if seconds <= 0:
        return
    conn.execute(
        """
        INSERT INTO time_entries (task_id, entry_date, origin, seconds)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (task_id, entry_date, origin)
        DO UPDATE SET seconds = seconds + excluded.seconds
        """,
        (task_id, entry_date, MACHINE if origin is None else origin, seconds),
    )
    conn.commit()


def deduct_seconds(conn: sqlite3.Connection, task_id: str, entry_date: str,
                   seconds: float) -> None:
    """Remove seconds from this machine's entry for a date (used by idle
    discard), clamping at zero — never goes negative."""
    if seconds <= 0:
        return
    conn.execute(
        """
        UPDATE time_entries SET seconds = MAX(0, seconds - ?)
        WHERE task_id = ? AND entry_date = ? AND origin = ?
        """,
        (seconds, task_id, entry_date, MACHINE),
    )
    conn.commit()


def seconds_for_day(conn: sqlite3.Connection, task_id: str, entry_date: str) -> float:
    """Total for a task on a date, summed across all machine origins."""
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) AS s FROM time_entries"
        " WHERE task_id = ? AND entry_date = ?",
        (task_id, entry_date),
    ).fetchone()
    return float(row["s"])


def entries_between(
    conn: sqlite3.Connection, first_date: str, last_date: str
) -> dict[tuple[str, str], float]:
    """(task_id, entry_date) -> seconds (all origins summed) in the range."""
    rows = conn.execute(
        "SELECT task_id, entry_date, SUM(seconds) AS s FROM time_entries"
        " WHERE entry_date BETWEEN ? AND ? GROUP BY task_id, entry_date",
        (first_date, last_date),
    )
    return {(r["task_id"], r["entry_date"]): float(r["s"]) for r in rows}


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def seconds_for_day_all_tasks(conn: sqlite3.Connection, entry_date: str) -> float:
    """Total across every task for a date (all origins) — daily-target math."""
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) AS s FROM time_entries WHERE entry_date = ?",
        (entry_date,),
    ).fetchone()
    return float(row["s"])


def merge_from(conn: sqlite3.Connection, other: sqlite3.Connection) -> dict[str, int]:
    """Merge another timetracker database into this one. Idempotent: rows are
    keyed by (task, date, origin) and the larger seconds value wins, so
    merging the same file twice never double-counts."""
    stats = {"tasks_added": 0, "entries_merged": 0}
    for task in other.execute("SELECT * FROM tasks"):
        cur = conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, name, created_at, archived, emoji)"
            " VALUES (?, ?, ?, ?, ?)",
            (task["task_id"], task["name"], task["created_at"],
             task["archived"], task["emoji"]),
        )
        stats["tasks_added"] += cur.rowcount
    for entry in other.execute("SELECT * FROM time_entries"):
        existing = conn.execute(
            "SELECT seconds FROM time_entries"
            " WHERE task_id = ? AND entry_date = ? AND origin = ?",
            (entry["task_id"], entry["entry_date"], entry["origin"]),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO time_entries (task_id, entry_date, origin, seconds)"
                " VALUES (?, ?, ?, ?)",
                (entry["task_id"], entry["entry_date"], entry["origin"],
                 entry["seconds"]),
            )
            stats["entries_merged"] += 1
        elif entry["seconds"] > existing["seconds"]:
            conn.execute(
                "UPDATE time_entries SET seconds = ?"
                " WHERE task_id = ? AND entry_date = ? AND origin = ?",
                (entry["seconds"], entry["task_id"], entry["entry_date"],
                 entry["origin"]),
            )
            stats["entries_merged"] += 1
    conn.commit()
    return stats
