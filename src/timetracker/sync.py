"""Folder-based cross-machine sync (Dropbox, OneDrive, a USB stick…).

Each machine drops a consistent snapshot of its own database into the sync
folder as ``timetracker-<machine>.db`` and merges in everyone else's file.
Merging is idempotent (origin-stamped rows, larger value wins), so machines
can sync in any order, as often as they like.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db


def export_to(conn: sqlite3.Connection, sync_dir: Path) -> Path:
    """Snapshot this machine's database into the sync folder."""
    sync_dir.mkdir(parents=True, exist_ok=True)
    dest_path = sync_dir / f"timetracker-{db.MACHINE}.db"
    dest = sqlite3.connect(str(dest_path))
    with dest:
        conn.backup(dest)  # consistent copy even while the app is running
    dest.close()
    return dest_path


def import_others(conn: sqlite3.Connection, sync_dir: Path) -> dict[str, int]:
    """Merge every other machine's snapshot from the sync folder."""
    stats = {"files": 0, "tasks_added": 0, "entries_merged": 0}
    own = f"timetracker-{db.MACHINE}.db"
    for snapshot in sorted(sync_dir.glob("timetracker-*.db")):
        if snapshot.name == own:
            continue
        other = db.connect(snapshot)
        merged = db.merge_from(conn, other)
        other.close()
        stats["files"] += 1
        stats["tasks_added"] += merged["tasks_added"]
        stats["entries_merged"] += merged["entries_merged"]
    return stats


def sync(conn: sqlite3.Connection, sync_dir: Path) -> dict[str, int]:
    """Import everyone else's history, then publish our own. Returns import
    stats so the caller knows whether anything changed."""
    stats = import_others(conn, sync_dir)
    export_to(conn, sync_dir)
    return stats
