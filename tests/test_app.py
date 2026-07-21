"""GUI smoke tests — run offscreen; skipped entirely if PySide6 is absent.

Windows are torn down deterministically (close + deleteLater + processEvents)
so no Qt widget is left for the garbage collector to destroy mid-run later,
which segfaults.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from timetracker import db  # noqa: E402
from timetracker.app import (  # noqa: E402
    DEFAULT_EMOJI,
    EMOJI_CHOICES,
    ArchivedTasksDialog,
    EmojiPickerDialog,
    MainWindow,
    app_icon,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def make_window(qapp, tmp_path):
    windows = []

    def _make(db_path) -> MainWindow:
        window = MainWindow(db_path=db_path)
        windows.append(window)
        return window

    yield _make
    for window in windows:
        window.close()
        if window.mini is not None:
            window.mini.deleteLater()
        window.deleteLater()
    qapp.processEvents()


def test_window_builds_rows_and_toggles(make_window, tmp_path):
    db_path = tmp_path / "test.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Seeded task")
    seed.close()

    window = make_window(db_path)
    assert list(window.rows) == [task_id]

    window.toggle_task(task_id)
    assert window.engine.running_task == task_id
    assert window.rows[task_id].button.isChecked()

    window.toggle_task(task_id)
    assert window.engine.running_task is None
    assert not window.rows[task_id].button.isChecked()


def test_app_icon_asset_loads(qapp):
    icon = app_icon()
    assert not icon.isNull()
    assert icon.availableSizes()  # the bundled PNG actually decoded


def test_add_task_via_ui(make_window, tmp_path):
    window = make_window(tmp_path / "test2.db")
    window.new_task_edit.setText("From the UI")
    window.add_task()
    tasks = db.list_tasks(window.conn)
    assert [t["name"] for t in tasks] == ["From the UI"]
    assert list(window.rows) == [tasks[0]["task_id"]]
    assert window.new_task_edit.text() == ""


def test_start_flash_pulses_then_clears(make_window, tmp_path):
    db_path = tmp_path / "flash.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    row = window.rows[task_id]

    window.toggle_task(task_id)  # starting → flash begins immediately
    assert row.property("flash") == "true"
    assert window._flash_timer.isActive()

    for _ in range(10):  # drive the pulse timer to completion by hand
        window._flash_step()
    assert row.property("flash") == "false"
    assert not window._flash_timer.isActive()
    assert window.engine.running_task == task_id  # flash is cosmetic only

    window.toggle_task(task_id)  # stopping does not flash
    assert row.property("flash") == "false"
    assert not window._flash_timer.isActive()


def test_mini_mode_swaps_windows_and_stays_on_top(make_window, tmp_path):
    db_path = tmp_path / "mini.db"
    seed = db.connect(db_path)
    a = db.create_task(seed, "Alpha")
    b = db.create_task(seed, "Beta")
    db.set_task_emoji(seed, a, "🔥")
    seed.close()

    window = make_window(db_path)
    window.show()
    window.enter_mini()
    mini = window.mini
    assert mini.isVisible() and not window.isVisible()
    assert bool(mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    assert set(mini.buttons) == {a, b}
    assert mini.buttons[a].emoji() == "🔥"
    assert mini.buttons[b].emoji() == DEFAULT_EMOJI  # unconfigured fallback

    # toggling from the shared engine reflects on the mini buttons
    window.toggle_task(a)
    mini.refresh()
    assert mini.buttons[a].isChecked()
    assert not mini.buttons[b].isChecked()

    window.exit_mini()
    assert window.isVisible() and not mini.isVisible()


def test_shutdown_flushes_pending_time_and_is_idempotent(qapp, tmp_path):
    db_path = tmp_path / "shutdown.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = MainWindow(db_path=db_path)
    window.toggle_task(task_id)  # timer running with unflushed live seconds
    window.shutdown()
    window.shutdown()  # second call (closeEvent after aboutToQuit) must not blow up
    assert window.engine.running_task is None

    check = db.connect(db_path)  # reopen: the flush must have hit the disk file
    from datetime import date as date_mod
    assert db.seconds_for_day(check, task_id, date_mod.today().isoformat()) >= 0
    assert db.total_seconds(check, task_id) >= 0
    check.close()
    window.deleteLater()
    qapp.processEvents()


def test_midnight_rollover_refreshes_every_card(make_window, tmp_path):
    from datetime import date as date_mod, timedelta as td

    db_path = tmp_path / "midnight.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    window._today = date_mod.today() - td(days=1)  # pretend we crossed midnight
    window._tick()
    assert window._today == date_mod.today()  # rollover detected and rebaselined


def test_archived_dialog_restore_and_delete(make_window, tmp_path):
    db_path = tmp_path / "arch.db"
    seed = db.connect(db_path)
    a = db.create_task(seed, "Alpha")
    b = db.create_task(seed, "Beta")
    db.add_seconds(seed, a, "2026-07-20", 100)
    db.add_seconds(seed, b, "2026-07-20", 200)
    db.archive_task(seed, a)
    db.archive_task(seed, b)
    seed.close()

    window = make_window(db_path)
    assert window.rows == {}  # both archived, so no cards
    dialog = ArchivedTasksDialog(window)
    assert {t["task_id"] for t in dialog._archived()} == {a, b}

    dialog.restore_task(a)
    assert a in window.rows  # card is back in the main window
    assert {t["task_id"] for t in dialog._archived()} == {b}

    dialog.delete_task(b, skip_confirm=True)
    assert dialog._archived() == []
    all_ids = [t["task_id"] for t in db.list_tasks(window.conn, include_archived=True)]
    assert all_ids == [a]
    assert db.total_seconds(window.conn, b) == 0  # logged time gone too
    dialog.deleteLater()


def test_discard_span_removes_away_time(make_window, tmp_path):
    from datetime import datetime

    db_path = tmp_path / "idle.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    db.add_seconds(seed, task_id, "2026-07-20", 3600)
    seed.close()

    window = make_window(db_path)
    window.discard_span(task_id,
                        datetime(2026, 7, 20, 10, 0, 0),
                        datetime(2026, 7, 20, 10, 10, 0))
    assert db.seconds_for_day(window.conn, task_id, "2026-07-20") == 3000


def test_report_dialog_month_toggle_and_csv(make_window, tmp_path):
    from timetracker.app import WeekReportDialog

    db_path = tmp_path / "report.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    from datetime import date as date_mod
    db.add_seconds(window.conn, task_id, date_mod.today().isoformat(), 600)

    dialog = WeekReportDialog(window)
    assert dialog.table.columnCount() == 9  # Task + 7 days + Total
    dialog.toggle_mode()
    assert dialog.mode == "month"
    assert dialog.table.columnCount() >= 30  # Task + 28..31 days + Total
    dialog.toggle_mode()
    assert dialog.mode == "week"
    dialog.deleteLater()


def test_nudges_fire_once_per_day(make_window, tmp_path):
    from datetime import datetime

    db_path = tmp_path / "nudge.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    late = datetime(2026, 7, 20, 19, 0)

    # nothing tracked + past morning time -> start nudge, exactly once
    assert window._nudge_check(late) == ["start"]
    assert window._nudge_check(late) == []

    # timer running past evening time -> stop nudge, exactly once
    window.toggle_task(task_id)
    assert window._nudge_check(late) == ["stop"]
    assert window._nudge_check(late) == []
    window.toggle_task(task_id)


def test_nudges_respect_disabled_and_early_times(make_window, tmp_path):
    from datetime import datetime

    db_path = tmp_path / "nudge2.db"
    seed = db.connect(db_path)
    db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    early = datetime(2026, 7, 20, 8, 0)
    assert window._nudge_check(early) == []  # before both nudge times

    db.set_setting(window.conn, "nudge_start_time", "")  # disabled
    db.set_setting(window.conn, "nudge_stop_time", "")
    late = datetime(2026, 7, 20, 23, 0)
    assert window._nudge_check(late) == []


def test_daily_target_bar_math(make_window, tmp_path):
    from datetime import date as date_mod

    db_path = tmp_path / "target.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    assert window.target_hours == 7.5  # default on
    db.add_seconds(window.conn, task_id, date_mod.today().isoformat(), 3.75 * 3600)
    window._update_target_bar()
    assert window.target_bar.value() == 50
    assert window.today_total() == 3.75 * 3600


def test_sync_now_pulls_other_machine_into_open_window(make_window, tmp_path):
    from timetracker import sync as sync_mod

    sync_dir = tmp_path / "dropbox"
    other = db.connect(tmp_path / "other.db")
    task = db.create_task(other, "From the winbox")
    db.add_seconds(other, task, "2026-07-19", 900, "winbox")
    # publish the other machine's snapshot under its own name
    sync_dir.mkdir()
    import sqlite3 as sqlite3_mod
    dest = sqlite3_mod.connect(str(sync_dir / "timetracker-winbox.db"))
    other.backup(dest)
    dest.close()
    other.close()

    window = make_window(tmp_path / "local.db")
    db.set_setting(window.conn, "sync_dir", str(sync_dir))
    stats = window.sync_now()
    assert stats["tasks_added"] == 1
    assert task in window.rows  # merged task appeared in the UI live
    assert db.seconds_for_day(window.conn, task, "2026-07-19") == 900


def test_banner_animation_toggle_via_settings(make_window, tmp_path):
    window = make_window(tmp_path / "banner.db")
    assert window.banner.timer.isActive()  # animated by default

    db.set_setting(window.conn, "banner_animated", "0")
    window.apply_settings()
    assert not window.banner.timer.isActive()
    assert window.banner.saucer_x is None  # frozen to a clean frame
    assert all(i.state == "alive" for i in window.banner.invaders)

    db.set_setting(window.conn, "banner_animated", "1")
    window.apply_settings()
    assert window.banner.timer.isActive()


def test_emoji_picker_grid_fills_the_field(qapp):
    dialog = EmojiPickerDialog(None, "Alpha", "")
    assert len(dialog.grid_buttons) == len(EMOJI_CHOICES)
    dialog.grid_buttons[1].click()
    assert dialog.edit.text() == EMOJI_CHOICES[1]
    dialog.grid_buttons[5].click()  # picking again replaces, not appends
    assert dialog.edit.text() == EMOJI_CHOICES[5]
    dialog.deleteLater()
    qapp.processEvents()


def test_mini_button_description_appears_with_size(make_window, tmp_path):
    db_path = tmp_path / "mini2.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    window.enter_mini()
    button = window.mini.buttons[task_id]
    button.resize(60, 60)
    assert not button.shows_description()
    button.resize(150, 150)
    assert button.shows_description()
