from datetime import date

import pytest

from timetracker import db
from timetracker.report import (
    build_month_report,
    build_week_report,
    month_dates,
    render_text,
    to_csv,
    to_markdown,
    week_dates,
)


@pytest.fixture()
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_week_dates_monday_to_sunday():
    # 2026-07-20 is a Monday
    days = week_dates(date(2026, 7, 22))
    assert days[0] == date(2026, 7, 20)
    assert days[-1] == date(2026, 7, 26)
    assert len(days) == 7
    # anchoring on the Monday or Sunday itself gives the same week
    assert week_dates(date(2026, 7, 20)) == days
    assert week_dates(date(2026, 7, 26)) == days


def test_build_week_report_day_by_day(conn):
    a = db.create_task(conn, "Alpha")
    b = db.create_task(conn, "Beta")
    db.add_seconds(conn, a, "2026-07-20", 3600)
    db.add_seconds(conn, a, "2026-07-22", 1800)
    db.add_seconds(conn, b, "2026-07-22", 60)
    db.add_seconds(conn, b, "2026-07-19", 999)  # previous week — excluded

    report = build_week_report(conn, date(2026, 7, 22))
    assert [r.task_name for r in report.rows] == ["Alpha", "Beta"]
    alpha, beta = report.rows
    assert alpha.daily_seconds == [3600, 0, 1800, 0, 0, 0, 0]
    assert alpha.total_seconds == 5400
    assert beta.daily_seconds == [0, 0, 60, 0, 0, 0, 0]
    assert report.day_totals == [3600, 0, 1860, 0, 0, 0, 0]
    assert report.grand_total == 5460


def test_report_omits_zero_tasks_but_keeps_archived_history(conn):
    active = db.create_task(conn, "NoTimeYet")  # no entries -> omitted
    archived = db.create_task(conn, "OldWork")
    db.add_seconds(conn, archived, "2026-07-21", 300)
    db.archive_task(conn, archived)

    report = build_week_report(conn, date(2026, 7, 21))
    assert [r.task_name for r in report.rows] == ["OldWork"]
    assert active not in [r.task_id for r in report.rows]


def test_month_dates_and_report(conn):
    assert len(month_dates(date(2026, 7, 15))) == 31
    assert month_dates(date(2026, 2, 1))[-1] == date(2026, 2, 28)  # not a leap year

    task = db.create_task(conn, "Alpha")
    db.add_seconds(conn, task, "2026-07-01", 100)
    db.add_seconds(conn, task, "2026-07-31", 200)
    db.add_seconds(conn, task, "2026-08-01", 999)  # next month — excluded

    report = build_month_report(conn, date(2026, 7, 20))
    assert len(report.dates) == 31
    assert report.rows[0].daily_seconds[0] == 100
    assert report.rows[0].daily_seconds[30] == 200
    assert report.grand_total == 300
    assert len(report.day_totals) == 31


def test_to_csv_round_numbers_and_totals(conn):
    task = db.create_task(conn, "Alpha")
    db.add_seconds(conn, task, "2026-07-20", 3600.4)
    text = to_csv(build_week_report(conn, date(2026, 7, 20)))
    lines = text.strip().splitlines()
    assert lines[0].startswith("Task,2026-07-20,")
    assert lines[0].endswith(",Total")
    assert "Alpha,3600," in lines[1]
    assert lines[2].startswith("TOTAL,3600,")
    assert "(values are seconds)" in lines[-1]


def test_to_markdown_note_shape(conn):
    a = db.create_task(conn, "Alpha")
    db.add_seconds(conn, a, "2026-07-20", 3723)
    note = to_markdown(build_week_report(conn, date(2026, 7, 20)),
                       "Week of 20 Jul 2026")
    assert note.startswith("---\ntags: [time-tracker, report]")
    assert "# ⏱️ timeTracker — Week of 20 Jul 2026" in note
    assert "| Alpha | 1:02:03 |" in note
    assert "| **TOTAL** | **1:02:03** |" in note
    assert "| Mon 20 Jul | 1:02:03 | 1:02:03 |" in note  # day-by-day row


def test_render_text_contains_totals(conn):
    a = db.create_task(conn, "Alpha")
    db.add_seconds(conn, a, "2026-07-20", 3723)
    text = render_text(build_week_report(conn, date(2026, 7, 20)))
    assert "Alpha" in text
    assert "1:02:03" in text
    assert "TOTAL" in text
