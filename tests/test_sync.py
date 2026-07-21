from pathlib import Path

from timetracker import db, sync


def test_sync_roundtrip_between_two_machines(tmp_path, monkeypatch):
    sync_dir = tmp_path / "dropbox"

    # Machine A tracks some time and publishes
    monkeypatch.setattr(db, "MACHINE", "mac")
    a = db.connect(tmp_path / "a.db")
    task = db.create_task(a, "Shared work")
    db.add_seconds(a, task, "2026-07-20", 3600)
    sync.export_to(a, sync_dir)

    # Machine B syncs: pulls A's history, publishes its own
    monkeypatch.setattr(db, "MACHINE", "winbox")
    b = db.connect(tmp_path / "b.db")
    stats = sync.sync(b, sync_dir)
    assert stats == {"files": 1, "tasks_added": 1, "entries_merged": 1}
    assert db.seconds_for_day(b, task, "2026-07-20") == 3600
    db.add_seconds(b, task, "2026-07-20", 1800)  # B tracks more, resyncs
    sync.sync(b, sync_dir)

    # Machine A syncs again and sees the combined day
    monkeypatch.setattr(db, "MACHINE", "mac")
    stats = sync.sync(a, sync_dir)
    assert stats["files"] == 1
    assert db.seconds_for_day(a, task, "2026-07-20") == 5400

    # Repeat syncs change nothing (idempotent)
    assert sync.sync(a, sync_dir)["entries_merged"] == 0
    a.close()
    b.close()


def test_export_ignores_own_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "MACHINE", "mac")
    conn = db.connect(tmp_path / "a.db")
    db.create_task(conn, "Task")
    sync.export_to(conn, tmp_path / "s")
    stats = sync.import_others(conn, tmp_path / "s")  # own file must be skipped
    assert stats == {"files": 0, "tasks_added": 0, "entries_merged": 0}
    conn.close()
