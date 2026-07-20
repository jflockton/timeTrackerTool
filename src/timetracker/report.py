"""Weekly day-by-day breakdown, as pure data the GUI (or anything else) renders."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from . import db
from .core import format_hms


def week_dates(anchor: date) -> list[date]:
    """The Monday-to-Sunday week containing ``anchor``."""
    monday = anchor - timedelta(days=anchor.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


@dataclass
class WeekReportRow:
    task_id: str
    task_name: str
    daily_seconds: list[float]  # one per day, Monday..Sunday

    @property
    def total_seconds(self) -> float:
        return sum(self.daily_seconds)


@dataclass
class WeekReport:
    dates: list[date]  # Monday..Sunday
    rows: list[WeekReportRow]

    @property
    def day_totals(self) -> list[float]:
        return [sum(row.daily_seconds[i] for row in self.rows) for i in range(7)]

    @property
    def grand_total(self) -> float:
        return sum(row.total_seconds for row in self.rows)


def build_week_report(conn: sqlite3.Connection, anchor: date) -> WeekReport:
    """Report for the week containing ``anchor``. Tasks with no time that
    week are omitted; archived tasks with time still show."""
    dates = week_dates(anchor)
    isos = [d.isoformat() for d in dates]
    entries = db.entries_between(conn, isos[0], isos[-1])
    names = {t["task_id"]: t["name"] for t in db.list_tasks(conn, include_archived=True)}

    rows = []
    for task_id in sorted({tid for tid, _ in entries}, key=lambda t: names.get(t, t)):
        daily = [entries.get((task_id, iso), 0.0) for iso in isos]
        if sum(daily) > 0:
            rows.append(WeekReportRow(task_id, names.get(task_id, task_id), daily))
    return WeekReport(dates=dates, rows=rows)


def render_text(report: WeekReport) -> str:
    """Plain-text rendering — used by the CLI report and handy in tests."""
    day_headers = [d.strftime("%a %d") for d in report.dates]
    header = ["Task"] + day_headers + ["Total"]
    lines = [[r.task_name] + [format_hms(s) if s else "-" for s in r.daily_seconds]
             + [format_hms(r.total_seconds)] for r in report.rows]
    totals = ["TOTAL"] + [format_hms(s) if s else "-" for s in report.day_totals] \
        + [format_hms(report.grand_total)]
    table = [header] + lines + [totals]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in table
    )
