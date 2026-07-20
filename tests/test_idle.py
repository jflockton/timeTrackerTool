from datetime import datetime, timedelta

from timetracker.idle import IdleWatcher


def dt(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 20, 10, minute, second)


def test_reports_away_span_once_on_return():
    watcher = IdleWatcher(threshold_s=300)
    assert watcher.sample(dt(0), 0, running=True) is None
    # user goes idle; crossing the threshold arms the watcher
    assert watcher.sample(dt(6), 360, running=True) is None
    # still away
    assert watcher.sample(dt(10), 600, running=True) is None
    # back at the keyboard: one span, from when input stopped until now-ish
    span = watcher.sample(dt(10, 30), 2, running=True)
    assert span is not None
    start, end = span
    assert start == dt(10, 30) - timedelta(seconds=2) - timedelta(seconds=628)
    assert end == dt(10, 30) - timedelta(seconds=2)
    # and only once
    assert watcher.sample(dt(11), 5, running=True) is None


def test_short_absences_are_ignored():
    watcher = IdleWatcher(threshold_s=300)
    assert watcher.sample(dt(0), 0, running=True) is None
    assert watcher.sample(dt(2), 120, running=True) is None  # 2 min: under threshold
    assert watcher.sample(dt(3), 1, running=True) is None


def test_no_timer_running_means_no_prompt():
    watcher = IdleWatcher(threshold_s=300)
    assert watcher.sample(dt(0), 900, running=False) is None
    # stopping the timer while away disarms the watcher
    assert watcher.sample(dt(1), 960, running=True) is None
    assert watcher.sample(dt(2), 0, running=False) is None
    assert watcher.sample(dt(3), 2, running=True) is None
