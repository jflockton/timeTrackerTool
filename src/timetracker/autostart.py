"""Launch-at-login registration, no extra dependencies.

macOS: a LaunchAgent plist in ~/Library/LaunchAgents.
Windows: a value in the HKCU ...\\CurrentVersion\\Run registry key.
Works both packaged (PyInstaller: sys.executable IS the app) and from
source (python -m timetracker).
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

APP_ID = "com.jflockton.timetrackertool"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "timeTrackerTool"


def launch_command() -> list[str]:
    if getattr(sys, "frozen", False):  # packaged app
        return [sys.executable]
    return [sys.executable, "-m", "timetracker"]


def _plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def is_enabled(home: Path | None = None) -> bool:
    if sys.platform == "darwin":
        return _plist_path(home).exists()
    if sys.platform.startswith("win"):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, _RUN_NAME)
            return True
        except OSError:
            return False
    return False


def enable(home: Path | None = None) -> None:
    if sys.platform == "darwin":
        path = _plist_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": APP_ID,
            "ProgramArguments": launch_command(),
            "RunAtLoad": True,
        }
        with open(path, "wb") as handle:
            plistlib.dump(payload, handle)
    elif sys.platform.startswith("win"):
        import winreg
        command = subprocess.list2cmdline(launch_command())
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, command)


def disable(home: Path | None = None) -> None:
    if sys.platform == "darwin":
        _plist_path(home).unlink(missing_ok=True)
    elif sys.platform.startswith("win"):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _RUN_NAME)
        except OSError:
            pass
