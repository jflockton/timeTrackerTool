# timeTrackerTool

A cross-platform (Windows + macOS) desktop GUI for tracking time spent on tasks,
one button per task.

## What it does

- The user configures as many **task timers** as they want; each task appears as
  a button in the GUI.
- Clicking a task's button starts/stops a **cumulative timer for the day** for
  that task.
- At the end of the day, each task's total (hours, minutes, seconds) is stored
  in a **local file**.
- Every task gets a **generated ID** when created; that ID is used for all time
  logged against the task, so renames never orphan history.
- At the end of the week the user opens a report view showing a **day-by-day
  breakdown** of time per task.

## Design notes (open decisions)

- **GUI framework:** must run on Windows and macOS from one codebase.
  Candidates: Python + PySide6/Qt (fits the existing Python toolchain),
  Tkinter (stdlib, zero deps), or Tauri/Electron if a web-style UI is
  preferred. Not yet decided.
- **Storage format:** local file per the spec — likely SQLite or JSON/CSV keyed
  by task ID and date. Not yet decided.
- **Weekly report:** could be an in-app view or a generated HTML/spreadsheet
  file. Not yet decided.

## Status

Project created 2026-07-20. Empty scaffold — no code yet. See the Obsidian
vault project folder (`02 - Projects/2026-07-20_timeTrackerTool/`) for the
current-state dashboard.
