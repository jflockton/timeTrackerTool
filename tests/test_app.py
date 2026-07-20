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
from timetracker.app import DEFAULT_EMOJI, MainWindow, app_icon  # noqa: E402


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
