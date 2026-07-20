"""GUI smoke tests — run offscreen; skipped entirely if PySide6 is absent."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from timetracker import db  # noqa: E402
from timetracker.app import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_window_builds_rows_and_toggles(qapp, tmp_path):
    db_path = tmp_path / "test.db"
    seed = db.connect(db_path)
    task_id = db.create_task(seed, "Seeded task")
    seed.close()

    window = MainWindow(db_path=db_path)
    assert list(window.rows) == [task_id]

    window.toggle_task(task_id)
    assert window.engine.running_task == task_id
    assert window.rows[task_id].button.isChecked()

    window.toggle_task(task_id)
    assert window.engine.running_task is None
    assert not window.rows[task_id].button.isChecked()
    window.close()


def test_add_task_via_ui(qapp, tmp_path):
    window = MainWindow(db_path=tmp_path / "test2.db")
    window.new_task_edit.setText("From the UI")
    window.add_task()
    tasks = db.list_tasks(window.conn)
    assert [t["name"] for t in tasks] == ["From the UI"]
    assert list(window.rows) == [tasks[0]["task_id"]]
    assert window.new_task_edit.text() == ""
    window.close()
