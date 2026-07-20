from datetime import date

import pytest

from timetracker import db
from timetracker.report import build_week_report, render_text, week_dates


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


def test_render_text_contains_totals(conn):
    a = db.create_task(conn, "Alpha")
    db.add_seconds(conn, a, "2026-07-20", 3723)
    text = render_text(build_week_report(conn, date(2026, 7, 20)))
    assert "Alpha" in text
    assert "1:02:03" in text
    assert "TOTAL" in text
