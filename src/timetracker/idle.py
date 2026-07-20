"""System idle detection, no extra dependencies.

`system_idle_seconds()` asks the OS how long since the last keyboard/mouse
input (macOS: ioreg HIDIdleTime; Windows: GetLastInputInfo; elsewhere: 0).

`IdleWatcher` is the pure state machine: feed it samples and it reports an
away-span exactly once, when the user comes back after being idle past the
threshold while a timer was running.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta

IDLE_THRESHOLD_S = 300  # 5 minutes away before we ask about the gap


def system_idle_seconds() -> float:
    """Seconds since last user input, best-effort. 0 if unknown."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True, text=True, timeout=2,
            ).stdout
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    return int(line.split("=")[-1].strip()) / 1_000_000_000
        elif sys.platform.startswith("win"):
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
                return millis / 1000.0
    except Exception:
        pass
    return 0.0


class IdleWatcher:
    """Reports (away_start, away_end) once when the user returns from an
    idle stretch >= threshold that happened while a timer was running."""

    def __init__(self, threshold_s: float = IDLE_THRESHOLD_S) -> None:
        self.threshold_s = threshold_s
        self._away_since: datetime | None = None

    def sample(self, now: datetime, idle_seconds: float,
               running: bool) -> tuple[datetime, datetime] | None:
        if not running:
            self._away_since = None
            return None
        if idle_seconds >= self.threshold_s:
            if self._away_since is None:
                self._away_since = now - timedelta(seconds=idle_seconds)
            return None
        if self._away_since is not None:
            span = (self._away_since, now - timedelta(seconds=idle_seconds))
            self._away_since = None
            if (span[1] - span[0]).total_seconds() >= self.threshold_s:
                return span
        return None
