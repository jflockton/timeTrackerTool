"""CLI: merge another machine's timetracker database into this one.

    poetry run timetracker-merge /path/to/other/timetracker.db

Safe to run repeatedly — rows are keyed by (task, date, machine) and the
larger value wins, so re-merging the same file changes nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge another timetracker.db (e.g. from your other machine) "
                    "into this machine's database.")
    parser.add_argument("other", help="Path to the other timetracker.db file")
    parser.add_argument("--into", default=None,
                        help="Target DB (default: this machine's data file)")
    args = parser.parse_args()

    other_path = Path(args.other)
    if not other_path.exists():
        print(f"error: {other_path} does not exist", file=sys.stderr)
        return 1

    target = db.connect(args.into or db.default_db_path())
    other = db.connect(other_path)
    stats = db.merge_from(target, other)
    other.close()
    target.close()
    print(f"merged: {stats['tasks_added']} new task(s), "
          f"{stats['entries_merged']} time entrie(s) added/updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
