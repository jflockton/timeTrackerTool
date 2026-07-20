"""Pure timer logic — no GUI, no database.

The engine tracks which task is running and accumulates elapsed seconds
per (task_id, date) in memory. The caller periodically calls ``flush()``
and writes the returned amounts to storage; frequent flushing keeps the
in-memory pending amounts small and crash-safe.

Elapsed time that straddles midnight is split across the dates it
actually occurred on, so a timer left running overnight books its
seconds to the correct days.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


class TimerEngine:
    """Single-active timer engine: starting a task stops the running one."""

    def __init__(self) -> None:
        self.running_task: str | None = None
        self._last_mark: datetime | None = None
        self._pending: dict[tuple[str, str], float] = {}

    def toggle(self, task_id: str, now: datetime) -> bool:
        """Start ``task_id`` (stopping any other running task) or stop it
        if it is the one running. Returns True if the task is now running."""
        if self.running_task == task_id:
            self.stop(now)
            return False
        self.start(task_id, now)
        return True

    def start(self, task_id: str, now: datetime) -> None:
        if self.running_task is not None:
            self._accumulate(now)
        self.running_task = task_id
        self._last_mark = now

    def stop(self, now: datetime) -> None:
        if self.running_task is None:
            return
        self._accumulate(now)
        self.running_task = None
        self._last_mark = None

    def flush(self, now: datetime) -> dict[tuple[str, str], float]:
        """Return accumulated (task_id, date_iso) -> seconds and reset the
        pending store. Includes time up to ``now`` for a running task."""
        if self.running_task is not None:
            self._accumulate(now)
        out = self._pending
        self._pending = {}
        return out

    def pending_seconds(self, task_id: str, date_iso: str, now: datetime) -> float:
        """Unflushed seconds for a task on a date, including the live span
        of a running task. Does not mutate state."""
        total = self._pending.get((task_id, date_iso), 0.0)
        if self.running_task == task_id and self._last_mark is not None:
            for span_date, seconds in _split_by_date(self._last_mark, now):
                if span_date == date_iso:
                    total += seconds
        return total

    def _accumulate(self, now: datetime) -> None:
        assert self.running_task is not None and self._last_mark is not None
        for span_date, seconds in _split_by_date(self._last_mark, now):
            key = (self.running_task, span_date)
            self._pending[key] = self._pending.get(key, 0.0) + seconds
        self._last_mark = now


def _split_by_date(start: datetime, end: datetime) -> list[tuple[str, float]]:
    """Split the span [start, end] into per-date (date_iso, seconds) pieces."""
    if end <= start:
        return []
    pieces: list[tuple[str, float]] = []
    cursor = start
    while cursor.date() != end.date():
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min)
        pieces.append((cursor.date().isoformat(), (midnight - cursor).total_seconds()))
        cursor = midnight
    pieces.append((cursor.date().isoformat(), (end - cursor).total_seconds()))
    return [(d, s) for d, s in pieces if s > 0]


# Public alias: split an arbitrary span into per-date pieces (used by the
# idle-discard flow as well as the engine itself).
def split_span_by_date(start: datetime, end: datetime) -> list[tuple[str, float]]:
    return _split_by_date(start, end)


def format_hms(seconds: float) -> str:
    """1h 2m 3s -> '1:02:03'; always shows hours for easy scanning."""
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"
