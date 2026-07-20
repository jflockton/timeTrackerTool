from datetime import datetime

from timetracker.core import TimerEngine, _split_by_date, format_hms


def dt(day: int, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 7, day, h, m, s)


def test_start_stop_accumulates_seconds():
    engine = TimerEngine()
    engine.start("abc", dt(20, 9, 0))
    engine.stop(dt(20, 9, 30))
    assert engine.flush(dt(20, 9, 31)) == {("abc", "2026-07-20"): 30 * 60}


def test_toggle_returns_running_state_and_single_active():
    engine = TimerEngine()
    assert engine.toggle("a", dt(20, 9)) is True
    # starting b stops a
    assert engine.toggle("b", dt(20, 10)) is True
    assert engine.running_task == "b"
    assert engine.toggle("b", dt(20, 10, 30)) is False
    flushed = engine.flush(dt(20, 11))
    assert flushed[("a", "2026-07-20")] == 3600
    assert flushed[("b", "2026-07-20")] == 30 * 60


def test_flush_includes_running_span_and_resets():
    engine = TimerEngine()
    engine.start("a", dt(20, 9))
    assert engine.flush(dt(20, 9, 10)) == {("a", "2026-07-20"): 600}
    # still running; only new time appears on the next flush
    assert engine.flush(dt(20, 9, 15)) == {("a", "2026-07-20"): 300}


def test_midnight_straddle_splits_across_dates():
    engine = TimerEngine()
    engine.start("a", dt(20, 23, 30))
    engine.stop(dt(21, 0, 45))
    flushed = engine.flush(dt(21, 1))
    assert flushed[("a", "2026-07-20")] == 30 * 60
    assert flushed[("a", "2026-07-21")] == 45 * 60


def test_pending_seconds_live_view_does_not_mutate():
    engine = TimerEngine()
    engine.start("a", dt(20, 9))
    assert engine.pending_seconds("a", "2026-07-20", dt(20, 9, 5)) == 300
    assert engine.pending_seconds("a", "2026-07-20", dt(20, 9, 5)) == 300
    assert engine.pending_seconds("other", "2026-07-20", dt(20, 9, 5)) == 0


def test_split_by_date_zero_and_negative_spans():
    assert _split_by_date(dt(20, 9), dt(20, 9)) == []
    assert _split_by_date(dt(20, 9), dt(20, 8)) == []


def test_format_hms():
    assert format_hms(0) == "0:00:00"
    assert format_hms(59) == "0:00:59"
    assert format_hms(3723) == "1:02:03"
    assert format_hms(36000) == "10:00:00"
