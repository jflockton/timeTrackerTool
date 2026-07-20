# timeTrackerTool

A cross-platform (Windows + macOS) desktop GUI for tracking time spent on tasks,
one button per task.

## What it does

- The user configures as many **task timers** as they want; each task appears as
  a button in the GUI.
- Clicking a task's button starts/stops a **cumulative timer for the day** for
  that task. Starting a task stops whichever task was running (single-active —
  you can only be doing one thing).
- Time is stored **locally** in an SQLite file, flushed every ~10 seconds and on
  close, so a crash loses almost nothing. Timers left running over midnight book
  their seconds to the correct days.
- Every task gets a **generated 8-char ID** when created; that ID is used for
  all time logged against the task, so renames never orphan history.
- The **Weekly report** button opens a Monday–Sunday day-by-day breakdown per
  task, with day totals and a grand total; page back/forward through weeks.
- Right-click a task button to **rename** or **archive** it (archived tasks keep
  their history and still appear in reports).

## Stack

- Python 3.11+ with **PySide6** (Qt) — one codebase for Windows and macOS.
- **SQLite** storage at the platform's app-data location
  (`~/Library/Application Support/timeTrackerTool/` on macOS,
  `%APPDATA%\timeTrackerTool\` on Windows); override with the
  `TIMETRACKER_DB` environment variable.
- Layout: `core.py` (pure timer logic) / `db.py` (schema + repository) /
  `report.py` (pure report building) / `app.py` (the only Qt-aware module).
- App icon: `src/timetracker/assets/icon.png`, set at launch (Dock icon on
  macOS, window/taskbar icon elsewhere). Regenerate with
  `poetry run python scripts/make_icon.py` — it is drawn in code, no source
  image. A proper `.icns`/`.ico` comes with packaging.

## Running

```bash
poetry install
poetry run timetracker      # launch the app
poetry run pytest -q        # test suite (GUI tests run offscreen)
```

## Status

v0.1 prototype (2026-07-20): working end-to-end — add tasks, toggle timers,
live daily totals, persistent storage, weekly report dialog. Not yet done:
packaged double-clickable app (PyInstaller/briefcase), Windows testing, idle
detection, CSV/export of the weekly report.
