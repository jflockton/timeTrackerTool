"""Weekly/monthly day-by-day breakdowns, as pure data the GUI (or anything
else) renders, plus text and CSV renderers."""

from __future__ import annotations

import calendar
import csv
import io
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from . import db
from .core import format_hms


def week_dates(anchor: date) -> list[date]:
    """The Monday-to-Sunday week containing ``anchor``."""
    monday = anchor - timedelta(days=anchor.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def month_dates(anchor: date) -> list[date]:
    """Every date of the month containing ``anchor``."""
    days = calendar.monthrange(anchor.year, anchor.month)[1]
    return [date(anchor.year, anchor.month, d) for d in range(1, days + 1)]


@dataclass
class PeriodReportRow:
    task_id: str
    task_name: str
    daily_seconds: list[float]  # one per date in the period

    @property
    def total_seconds(self) -> float:
        return sum(self.daily_seconds)


@dataclass
class PeriodReport:
    dates: list[date]
    rows: list[PeriodReportRow]

    @property
    def day_totals(self) -> list[float]:
        return [sum(row.daily_seconds[i] for row in self.rows)
                for i in range(len(self.dates))]

    @property
    def grand_total(self) -> float:
        return sum(row.total_seconds for row in self.rows)


# Backwards-friendly aliases from when only weeks existed
WeekReportRow = PeriodReportRow
WeekReport = PeriodReport


def _build_report(conn: sqlite3.Connection, dates: list[date]) -> PeriodReport:
    """Tasks with no time in the period are omitted; archived tasks with
    time still show."""
    isos = [d.isoformat() for d in dates]
    entries = db.entries_between(conn, isos[0], isos[-1])
    names = {t["task_id"]: t["name"] for t in db.list_tasks(conn, include_archived=True)}

    rows = []
    for task_id in sorted({tid for tid, _ in entries}, key=lambda t: names.get(t, t)):
        daily = [entries.get((task_id, iso), 0.0) for iso in isos]
        if sum(daily) > 0:
            rows.append(PeriodReportRow(task_id, names.get(task_id, task_id), daily))
    return PeriodReport(dates=dates, rows=rows)


def build_week_report(conn: sqlite3.Connection, anchor: date) -> PeriodReport:
    return _build_report(conn, week_dates(anchor))


def build_month_report(conn: sqlite3.Connection, anchor: date) -> PeriodReport:
    return _build_report(conn, month_dates(anchor))


def to_csv(report: PeriodReport) -> str:
    """Spreadsheet-ready CSV: ISO-dated columns, per-task rows, totals."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Task"] + [d.isoformat() for d in report.dates] + ["Total"])
    for row in report.rows:
        writer.writerow([row.task_name]
                        + [round(s) for s in row.daily_seconds]
                        + [round(row.total_seconds)])
    writer.writerow(["TOTAL"] + [round(s) for s in report.day_totals]
                    + [round(report.grand_total)])
    writer.writerow([])
    writer.writerow(["(values are seconds)"])
    return out.getvalue()


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
