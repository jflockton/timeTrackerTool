import sqlite3

import pytest

from timetracker import db


@pytest.fixture()
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_create_task_generates_stable_id(conn):
    task_id = db.create_task(conn, "Migration work")
    assert len(task_id) == 8
    tasks = db.list_tasks(conn)
    assert [t["task_id"] for t in tasks] == [task_id]
    assert tasks[0]["name"] == "Migration work"


def test_create_task_rejects_blank_name(conn):
    with pytest.raises(ValueError):
        db.create_task(conn, "   ")


def test_rename_keeps_id_and_history(conn):
    task_id = db.create_task(conn, "Old name")
    db.add_seconds(conn, task_id, "2026-07-20", 120)
    db.rename_task(conn, task_id, "New name")
    tasks = db.list_tasks(conn)
    assert tasks[0]["task_id"] == task_id
    assert tasks[0]["name"] == "New name"
    assert db.seconds_for_day(conn, task_id, "2026-07-20") == 120


def test_archive_hides_from_default_listing(conn):
    keep = db.create_task(conn, "Keep")
    gone = db.create_task(conn, "Gone")
    db.archive_task(conn, gone)
    assert [t["task_id"] for t in db.list_tasks(conn)] == [keep]
    all_ids = [t["task_id"] for t in db.list_tasks(conn, include_archived=True)]
    assert sorted(all_ids) == sorted([keep, gone])


def test_add_seconds_is_cumulative_upsert(conn):
    task_id = db.create_task(conn, "Task")
    db.add_seconds(conn, task_id, "2026-07-20", 10)
    db.add_seconds(conn, task_id, "2026-07-20", 5.5)
    db.add_seconds(conn, task_id, "2026-07-21", 7)
    assert db.seconds_for_day(conn, task_id, "2026-07-20") == 15.5
    assert db.seconds_for_day(conn, task_id, "2026-07-21") == 7
    assert db.seconds_for_day(conn, task_id, "2026-07-22") == 0


def test_add_seconds_ignores_non_positive(conn):
    task_id = db.create_task(conn, "Task")
    db.add_seconds(conn, task_id, "2026-07-20", 0)
    db.add_seconds(conn, task_id, "2026-07-20", -5)
    assert db.seconds_for_day(conn, task_id, "2026-07-20") == 0


def test_entries_between_is_inclusive(conn):
    task_id = db.create_task(conn, "Task")
    for day, secs in [("2026-07-19", 1), ("2026-07-20", 2), ("2026-07-26", 3), ("2026-07-27", 4)]:
        db.add_seconds(conn, task_id, day, secs)
    entries = db.entries_between(conn, "2026-07-20", "2026-07-26")
    assert entries == {(task_id, "2026-07-20"): 2, (task_id, "2026-07-26"): 3}


def test_emoji_column_migrates_old_databases_and_updates():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    # A pre-mini-mode schema without the emoji column
    connection.execute(
        "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
        " created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)"
    )
    db.ensure_timetracker_tables(connection)
    task_id = db.create_task(connection, "Task")
    assert db.list_tasks(connection)[0]["emoji"] == ""
    db.set_task_emoji(connection, task_id, "🔥")
    assert db.list_tasks(connection)[0]["emoji"] == "🔥"
    connection.close()


def test_default_db_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "custom.db"))
    assert db.default_db_path() == tmp_path / "custom.db"
