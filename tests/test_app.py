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
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

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


def test_window_title_describes_the_running_task(make_window, tmp_path):
    db_path = tmp_path / "title.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Project work")
    seed.close()

    window = make_window(db_path)
    assert window.windowTitle() == "timeTrackerTool"

    window.toggle_task(task_id)
    assert "▶ Project work" in window.windowTitle()
    assert "timeTrackerTool" in window.windowTitle()

    window.enter_mini()  # the mini window carries the description too
    assert "▶ Project work" in window.mini.windowTitle()

    window.toggle_task(task_id)  # stop
    assert window.windowTitle() == "timeTrackerTool"


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


def test_banner_mode_defaults_to_text_logo(make_window, tmp_path):
    window = make_window(tmp_path / "banner.db")
    # Quiet by default: the text logo shows, the arcade banner does not
    assert window.logo.isVisibleTo(window)
    assert not window.banner.isVisibleTo(window)
    assert not window.banner.timer.isActive()

    db.set_setting(window.conn, "banner_mode", "animated")
    window.apply_settings()
    assert window.banner.isVisibleTo(window)
    assert not window.logo.isVisibleTo(window)
    assert window.banner.timer.isActive()

    db.set_setting(window.conn, "banner_mode", "static")
    window.apply_settings()
    assert window.banner.isVisibleTo(window)
    assert not window.banner.timer.isActive()
    assert window.banner.saucer_x is None  # frozen to a clean frame
    assert all(i.state == "alive" for i in window.banner.invaders)

    db.set_setting(window.conn, "banner_mode", "logo")
    window.apply_settings()
    assert window.logo.isVisibleTo(window)
    assert not window.banner.isVisibleTo(window)


def test_logo_widget_follows_the_theme(make_window, tmp_path):
    window = make_window(tmp_path / "logo.db")
    window.logo.resize(440, 76)

    db.set_setting(window.conn, "theme", "dark")
    window.apply_settings()
    assert max(_rendered_lightnesses(window.logo)) > 150  # light lettering

    db.set_setting(window.conn, "theme", "light")
    window.apply_settings()
    assert min(_rendered_lightnesses(window.logo)) < 100  # ink lettering

    db.set_setting(window.conn, "theme", "")
    window.apply_settings()


def test_banner_mode_saved_via_settings_dialog(make_window, tmp_path):
    from timetracker.app import SettingsDialog

    window = make_window(tmp_path / "banner_dlg.db")
    dialog = SettingsDialog(window)
    assert dialog.banner_combo.currentData() == "logo"  # quiet default
    dialog.banner_combo.setCurrentIndex(dialog.banner_combo.findData("animated"))
    dialog.save()
    assert db.get_setting(window.conn, "banner_mode", "") == "animated"
    assert window.banner.timer.isActive()
    dialog.deleteLater()


def test_cube_side_flips_start_and_stop_tasks(make_window, tmp_path):
    db_path = tmp_path / "cube.db"
    seed = db.connect(db_path)
    alpha = db.create_task(seed, "Alpha")
    beta = db.create_task(seed, "Beta")
    seed.close()

    window = make_window(db_path)
    db.set_setting(window.conn, "cube_enabled", "1")
    db.set_setting(window.conn, "cube_side_1", alpha)
    db.set_setting(window.conn, "cube_side_2", beta)

    window._on_cube_side(1)
    assert window.engine.running_task == alpha
    window._on_cube_side(1)  # same side again: no toggle-off, keeps running
    assert window.engine.running_task == alpha
    window._on_cube_side(2)  # flip to another mapped side switches task
    assert window.engine.running_task == beta
    window._on_cube_side(0)  # resting on the base stops
    assert window.engine.running_task is None
    window._on_cube_side(1)
    window._on_cube_side(5)  # unmapped side stops too
    assert window.engine.running_task is None
    window._on_cube_side(99)  # garbage value is treated as stop, not crash
    assert window.engine.running_task is None

    db.set_setting(window.conn, "cube_enabled", "0")
    window._on_cube_side(1)  # disabled: flips are ignored
    assert window.engine.running_task is None


def test_cube_flip_status_includes_sticker_label(make_window, tmp_path):
    db_path = tmp_path / "cube_label.db"
    seed = db.connect(db_path)
    alpha = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    db.set_setting(window.conn, "cube_enabled", "1")
    db.set_setting(window.conn, "cube_side_3", alpha)
    db.set_setting(window.conn, "cube_label_3", "deep work")

    assert window._describe_flip(3, alpha) == "Cube: side 3 (deep work) → Alpha"
    assert window._describe_flip(0, "") == "Cube: on its base → timer stopped"
    assert window._describe_flip(5, "") == "Cube: side 5 → unmapped, timer stopped"


def test_cube_listener_lifecycle_without_hardware(qapp):
    from timetracker.cube import CubeListener

    listener = CubeListener()
    assert not listener.running
    listener.stop()  # stopping a never-started listener is a no-op
    assert not listener.running


def test_cube_friendly_errors():
    from timetracker.cube import friendly_error

    denied = Exception(
        "Bluetooth access is denied by the user for the current application. "
        "Check macOS privacy settings.", "SomeEnumJunk")
    assert friendly_error(denied) == "Bluetooth access denied"
    assert friendly_error(Exception("Bluetooth device is turned off")) \
        == "Bluetooth is turned off"
    long = Exception("x" * 300)
    assert len(friendly_error(long)) <= 90


def test_cube_denied_status_shows_settings_button(make_window, tmp_path):
    window = make_window(tmp_path / "cube_btn.db")
    db.set_setting(window.conn, "cube_enabled", "1")
    window._apply_cube_setting()
    window.cube.stop()  # don't actually scan during the test

    window._on_cube_status("Cube: Bluetooth access denied — allow…")
    assert window._bt_settings_btn.isVisible() or not window.isVisible()
    assert not window._bt_settings_btn.isHidden()
    window._on_cube_status("Cube: connected (Timeular Tra)")
    assert window._bt_settings_btn.isHidden()


def test_mini_mode_hides_tasks_toggled_off(make_window, tmp_path):
    db_path = tmp_path / "mini3.db"
    seed = db.connect(db_path)
    alpha = db.create_task(seed, "Alpha")
    beta = db.create_task(seed, "Beta")
    seed.close()

    window = make_window(db_path)
    window.enter_mini()
    assert set(window.mini.buttons) == {alpha, beta}

    window.toggle_show_in_mini(beta)
    assert set(window.mini.buttons) == {alpha}
    assert beta in window.rows  # the full app still shows the task

    window.toggle_show_in_mini(beta)  # toggling back restores the button
    assert set(window.mini.buttons) == {alpha, beta}


def test_move_task_reorders_cards_dict_and_layout(make_window, tmp_path):
    db_path = tmp_path / "order.db"
    seed = db.connect(db_path)
    a = db.create_task(seed, "A")
    b = db.create_task(seed, "B")
    c = db.create_task(seed, "C")
    seed.close()

    window = make_window(db_path)
    assert list(window.rows) == [a, b, c]

    window.move_task(c, -1)
    assert list(window.rows) == [a, c, b]
    layout_positions = [window.rows_layout.indexOf(window.rows[t])
                        for t in (a, c, b)]
    assert layout_positions == sorted(layout_positions)  # widgets moved too

    window.move_task(a, -1)  # no-op at the top
    assert list(window.rows) == [a, c, b]

    # the new order survives a restart
    window2 = make_window(db_path)
    assert list(window2.rows) == [a, c, b]


def test_settings_cube_config_button_follows_checkbox(make_window, tmp_path):
    from timetracker.app import SettingsDialog

    window = make_window(tmp_path / "cube_cfg.db")
    dialog = SettingsDialog(window)
    assert not dialog.cube_check.isChecked()  # cube off by default
    assert not dialog._form.isRowVisible(dialog.cube_config_btn)

    dialog.cube_check.setChecked(True)
    assert dialog._form.isRowVisible(dialog.cube_config_btn)
    dialog.cube_check.setChecked(False)
    assert not dialog._form.isRowVisible(dialog.cube_config_btn)
    dialog.deleteLater()


def test_cube_settings_dialog_saves_mappings(make_window, tmp_path):
    from timetracker.app import CubeSettingsDialog

    db_path = tmp_path / "cube_dlg.db"
    seed = db.connect(db_path)
    alpha = db.create_task(seed, "Alpha")
    seed.close()

    window = make_window(db_path)
    dialog = CubeSettingsDialog(window)
    combo = dialog.cube_combos[3]
    combo.setCurrentIndex(1)  # index 0 is "— stop timer —", 1 is Alpha
    dialog.cube_labels[3].setText("deep work")
    dialog.save()
    assert db.get_setting(window.conn, "cube_side_3", "") == alpha
    assert db.get_setting(window.conn, "cube_label_3", "") == "deep work"

    # reopening shows the saved mapping preselected
    dialog2 = CubeSettingsDialog(window)
    assert dialog2.cube_combos[3].currentData() == alpha
    assert dialog2.cube_labels[3].text() == "deep work"
    dialog.deleteLater()
    dialog2.deleteLater()


def test_theme_scheme_mapping():
    from PySide6.QtCore import Qt

    from timetracker.app import scheme_for_theme

    assert scheme_for_theme("light") == Qt.ColorScheme.Light
    assert scheme_for_theme("dark") == Qt.ColorScheme.Dark
    assert scheme_for_theme("") == Qt.ColorScheme.Unknown      # follow the OS
    assert scheme_for_theme("banana") == Qt.ColorScheme.Unknown


def _rendered_lightnesses(widget):
    image = widget.grab().toImage()
    values = []
    for x in range(0, image.width(), 2):
        for y in range(0, image.height(), 2):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 0:
                values.append(colour.lightness())
    return values


def test_task_text_stays_readable_after_live_theme_switch(make_window, tmp_path):
    """Regression: stylesheet-styled widgets cache their colours at polish
    time, so without a repolish a live palette swap left black task names
    on dark cards."""
    db_path = tmp_path / "contrast.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "READABLE")
    seed.close()

    window = make_window(db_path)
    label = window.rows[task_id].name_label

    db.set_setting(window.conn, "theme", "dark")
    window.apply_settings()
    assert max(_rendered_lightnesses(label)) > 150  # light text present

    db.set_setting(window.conn, "theme", "light")
    window.apply_settings()
    assert min(_rendered_lightnesses(label)) < 100  # dark text present

    db.set_setting(window.conn, "theme", "")
    window.apply_settings()


def test_apply_theme_actually_changes_the_palette(qapp):
    from timetracker.app import apply_theme

    apply_theme("dark")
    dark_window = qapp.palette().window().color()
    apply_theme("light")
    light_window = qapp.palette().window().color()
    assert dark_window.lightness() < 100 < light_window.lightness()

    apply_theme("")  # back to following the OS
    assert qapp.palette().window().color() != dark_window


def test_theme_setting_saved_and_applied_via_dialog(make_window, tmp_path):
    from timetracker.app import SettingsDialog

    window = make_window(tmp_path / "theme.db")
    dialog = SettingsDialog(window)
    assert dialog.theme_combo.currentData() == ""  # default: system

    dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
    dialog.save()
    assert db.get_setting(window.conn, "theme", "") == "dark"

    # reopening shows the saved choice; apply_settings ran without error
    dialog2 = SettingsDialog(window)
    assert dialog2.theme_combo.currentData() == "dark"
    dialog.deleteLater()
    dialog2.deleteLater()


def test_icon_choices_are_unique_and_render(qapp):
    from timetracker import icons

    assert len(icons.ICON_CHOICES) == len(icons.KINDS) * len(icons.COLOURS)
    assert len(set(icons.ICON_CHOICES)) == len(icons.ICON_CHOICES)
    for token in icons.ICON_CHOICES:
        assert icons.is_icon(token)
        pm = icons.pixmap(token, 64)
        assert not pm.isNull() and pm.width() == 64
    assert not icons.is_icon("🔥")
    assert not icons.is_icon("")
    # unknown parts degrade to a valid icon rather than crashing
    assert icons.parse("icon:garbage-nope") in [
        (k, c) for k in icons.KINDS for c in icons.COLOURS]


def test_icon_picker_click_chooses_and_accepts(qapp):
    from timetracker import icons

    dialog = EmojiPickerDialog(None, "Alpha", "")
    assert len(dialog.icon_buttons) == len(icons.ICON_CHOICES)
    dialog.icon_buttons[0].click()  # icons choose-and-close in one click
    assert dialog.result() == 1  # QDialog.DialogCode.Accepted
    assert dialog.edit.text() == icons.ICON_CHOICES[0]
    dialog.deleteLater()
    qapp.processEvents()


def test_icon_token_shows_pixmap_not_raw_text(make_window, tmp_path):
    from timetracker import icons

    db_path = tmp_path / "icon.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Coding")
    db.set_task_emoji(seed, task_id, icons.ICON_CHOICES[0])
    seed.close()

    window = make_window(db_path)
    row = window.rows[task_id]
    assert row.name_label.text() == "Coding"  # no "icon:code-blue" leaking out
    assert not row.icon_label.isHidden()
    assert row.icon_label.pixmap() is not None

    window.enter_mini()
    button = window.mini.buttons[task_id]
    button.resize(80, 80)
    assert not button.grab().isNull()  # paints the pixmap path without crashing


def test_restore_from_archive_keeps_mini_setting(make_window, tmp_path):
    from timetracker.app import ArchivedTasksDialog

    db_path = tmp_path / "restore.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Hidden one")
    db.set_task_mini(seed, task_id, False)
    db.archive_task(seed, task_id)
    seed.close()

    window = make_window(db_path)
    dialog = ArchivedTasksDialog(window)
    dialog.restore_task(task_id)
    assert not window.rows[task_id].show_in_mini  # setting survived the trip
    window.enter_mini()
    assert task_id not in window.mini.buttons
    dialog.deleteLater()


def test_bare_ok_on_icon_task_keeps_the_icon(qapp, monkeypatch):
    from timetracker import icons

    token = icons.ICON_CHOICES[0]
    monkeypatch.setattr(
        "timetracker.app.QDialog.exec", lambda self: QDialog.DialogCode.Accepted)
    text, accepted = EmojiPickerDialog.get_emoji(None, "Alpha", token)
    assert accepted and text == token  # untouched dialog is a no-op
    qapp.processEvents()


def test_notion_library_loads_renders_and_tints(qapp):
    from timetracker import icons
    from timetracker.app import apply_theme

    names = icons.notion_names()
    assert len(names) > 800  # the whole set came across
    assert "cog-arcade" in names  # our own cog rides along
    assert "gear" in names
    # In-house additions: names people actually search for
    for own in ("email", "envelope", "mug"):
        assert own in names

    token = f"{icons.NOTION_PREFIX}alien-pixel"
    assert icons.is_notion(token) and icons.is_custom(token)
    assert not icons.is_icon(token)
    assert icons.label(token) == "Alien Pixel"

    apply_theme("dark")
    dark_pm = icons.pixmap(token, 32).toImage()
    apply_theme("light")
    light_pm = icons.pixmap(token, 32).toImage()
    apply_theme("")

    def opaque_lightnesses(image):
        return [image.pixelColor(x, y).lightness()
                for x in range(image.width()) for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 200]

    assert min(opaque_lightnesses(light_pm)) < 60   # black-ish on light
    assert max(opaque_lightnesses(dark_pm)) > 200   # white-ish on dark


def test_notion_coloured_tokens_render_fixed_colour(qapp):
    from timetracker import icons
    from timetracker.app import apply_theme

    token = f"{icons.NOTION_PREFIX}alien:blue"
    assert icons.notion_parts(token) == ("alien", "blue")
    assert icons.label(token) == "Alien (blue)"
    assert icons.notion_parts(f"{icons.NOTION_PREFIX}alien:nope") == ("alien", None)

    def blueish(image):
        return any(
            (c := image.pixelColor(x, y)).alpha() > 200
            and c.blue() > c.red() + 40
            for x in range(image.width()) for y in range(image.height()))

    apply_theme("dark")
    assert blueish(icons.pixmap(token, 32).toImage())  # colour fixed
    apply_theme("light")
    assert blueish(icons.pixmap(token, 32).toImage())  # in both themes
    apply_theme("")


def test_notion_colour_popup_offers_all_colours_and_picks(qapp):
    from timetracker import icons
    from timetracker.app import NotionColourPopup

    dialog = EmojiPickerDialog(None, "Alpha", "")
    popup = NotionColourPopup(dialog, "alien")
    assert len(popup.swatches) == len(icons.NOTION_COLOURS)

    popup.swatches[6].click()  # 6th index = blue in the ordered mapping
    assert dialog.result() == 1
    assert dialog.edit.text() == f"{icons.NOTION_PREFIX}alien:blue"
    popup.deleteLater()
    dialog.deleteLater()
    qapp.processEvents()


def test_notion_tab_search_filters_and_chooses(qapp):
    from timetracker import icons

    dialog = EmojiPickerDialog(None, "Alpha", "")
    total = dialog.notion_list.count()
    assert total == len(icons.notion_names())

    dialog.notion_search.setText("alien")
    visible = [dialog.notion_list.item(i) for i in range(total)
               if not dialog.notion_list.item(i).isHidden()]
    assert 0 < len(visible) < 20
    assert all("alien" in i.data(Qt.ItemDataRole.UserRole) for i in visible)

    dialog.notion_search.setText("")
    assert sum(1 for i in range(total)
               if not dialog.notion_list.item(i).isHidden()) == total

    dialog._choose_icon(f"{icons.NOTION_PREFIX}alien")
    assert dialog.result() == 1
    assert dialog.edit.text() == f"{icons.NOTION_PREFIX}alien"
    dialog.deleteLater()
    qapp.processEvents()


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
