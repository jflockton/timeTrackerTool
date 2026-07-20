"""PySide6 GUI: one toggle button per task, live daily totals, weekly report.

Single-active model: starting a task stops whichever task was running.
Accumulated time is flushed to SQLite every few seconds and on close, so
a crash loses at most FLUSH_EVERY_TICKS seconds.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from importlib.resources import files

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QIcon, QPainter, QPen, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import db
from .core import TimerEngine, format_hms
from .report import build_week_report, week_dates

TICK_MS = 1000
FLUSH_EVERY_TICKS = 10
# Mini-mode buttons show name + time once they are at least this tall (px)
MINI_TEXT_THRESHOLD = 96
DEFAULT_EMOJI = "⏱️"


def app_icon() -> QIcon:
    """The bundled 13:37 LCD-clock icon (regenerate with scripts/make_assets.py)."""
    return QIcon(str(files("timetracker") / "assets" / "icon.png"))


def banner_pixmap() -> QPixmap:
    """The boss-cracking-a-whip-at-a-sundial banner (scripts/make_assets.py)."""
    return QPixmap(str(files("timetracker") / "assets" / "banner.png"))


# Card styling for task rows; [running="true"] lights the active task up.
STYLESHEET = """
QFrame#taskCard {
    border: 1px solid rgba(148, 163, 184, 0.65);
    border-radius: 10px;
    background: rgba(148, 163, 184, 0.10);
}
QFrame#taskCard[running="true"] {
    border: 2px solid #f97316;
    background: rgba(249, 115, 22, 0.16);
}
QFrame#taskCard QLabel { border: none; background: transparent; }
"""


class TaskRow(QFrame):
    """One task in its own bordered card: name, today's time, start/stop."""

    def __init__(self, task_id: str, name: str, window: "MainWindow",
                 emoji: str = "") -> None:
        super().__init__()
        self.task_id = task_id
        self.name = name
        self.emoji = emoji
        self.window = window

        self.setObjectName("taskCard")
        self.setProperty("running", "false")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        self.button = QPushButton()
        self.button.setCheckable(True)
        self.button.setFixedSize(84, 36)
        self.button.clicked.connect(self._on_clicked)

        self.name_label = QLabel()
        name_font = self.name_label.font()
        name_font.setBold(True)
        name_font.setPointSize(name_font.pointSize() + 1)
        self.name_label.setFont(name_font)

        self.time_label = QLabel()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self.button)
        layout.addSpacing(6)
        layout.addWidget(self.name_label, stretch=1)
        layout.addWidget(self.time_label)
        self.refresh()

    def _on_clicked(self) -> None:
        self.window.toggle_task(self.task_id)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        emoji = menu.addAction("Set emoji…")
        archive = menu.addAction("Archive")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == rename:
            self.window.rename_task(self.task_id, self.name)
        elif chosen == emoji:
            self.window.set_emoji(self.task_id)
        elif chosen == archive:
            self.window.archive_task(self.task_id, self.name)

    def refresh(self) -> None:
        running = self.window.engine.running_task == self.task_id
        seconds = self.window.today_seconds(self.task_id)
        self.button.setText("■ Stop" if running else "▶ Start")
        self.button.setChecked(running)
        self.name_label.setText(f"{self.emoji} {self.name}" if self.emoji else self.name)
        self.time_label.setText(f"{format_hms(seconds)} today")
        if self.property("running") != str(running).lower():
            self.setProperty("running", str(running).lower())
            self.style().unpolish(self)
            self.style().polish(self)


class MiniTaskButton(QPushButton):
    """Mini-mode button: a configurable emoji that scales with the button,
    plus the task name and today's time once the button is tall enough."""

    def __init__(self, task_id: str, window: "MainWindow") -> None:
        super().__init__()
        self.task_id = task_id
        self.window = window
        self.setCheckable(True)
        self.setMinimumSize(44, 44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.clicked.connect(lambda: window.toggle_task(task_id))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def _row(self) -> "TaskRow":
        return self.window.rows[self.task_id]

    def emoji(self) -> str:
        return self._row().emoji or DEFAULT_EMOJI

    def shows_description(self) -> bool:
        return self.height() >= MINI_TEXT_THRESHOLD

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        emoji = menu.addAction("Set emoji…")
        back = menu.addAction("Back to full app")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == emoji:
            self.window.set_emoji(self.task_id, parent=self)
        elif chosen == back:
            self.window.exit_mini()

    def paintEvent(self, _event) -> None:
        running = self.window.engine.running_task == self.task_id
        name = self._row().name
        today = format_hms(self.window.today_seconds(self.task_id))
        self.setToolTip(f"{name} — {today} today")

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if running:
            p.setPen(QPen(QColor("#f97316"), 2))
            p.setBrush(QColor(249, 115, 22, 45))
        else:
            p.setPen(QPen(QColor(148, 163, 184, 170), 1))
            p.setBrush(QColor(148, 163, 184, 28))
        p.drawRoundedRect(rect, 10, 10)

        show_desc = self.shows_description()
        text_zone = 34 if show_desc else 0
        emoji_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height() - text_zone)
        emoji_font = self.font()
        emoji_font.setPixelSize(
            max(12, int(min(emoji_rect.width(), emoji_rect.height()) * 0.6))
        )
        p.setFont(emoji_font)
        p.drawText(emoji_rect, Qt.AlignmentFlag.AlignCenter, self.emoji())

        if show_desc:
            small = self.font()
            small.setPixelSize(11)
            p.setFont(small)
            p.setPen(self.palette().windowText().color())
            metrics = QFontMetrics(small)
            elided = metrics.elidedText(
                name, Qt.TextElideMode.ElideRight, int(rect.width()) - 10
            )
            p.drawText(
                QRectF(rect.x(), rect.bottom() - 32, rect.width(), 15),
                Qt.AlignmentFlag.AlignCenter, elided,
            )
            p.drawText(
                QRectF(rect.x(), rect.bottom() - 17, rect.width(), 15),
                Qt.AlignmentFlag.AlignCenter, today,
            )
        p.end()


class MiniWindow(QWidget):
    """Compact always-on-top strip of emoji task buttons. Resizable; the
    emoji grow with it, descriptions appear once there's room."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(
            None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.main = window
        self.suppress_restore = False
        self.setWindowTitle("timeTracker")
        self.buttons: dict[str, MiniTaskButton] = {}

        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.setSpacing(6)
        restore = QPushButton("⤢")
        restore.setFixedSize(24, 24)
        restore.setToolTip("Back to full app")
        restore.clicked.connect(lambda: self.main.exit_mini())
        side = QVBoxLayout()
        side.addWidget(restore)
        side.addStretch()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addLayout(self.buttons_layout, stretch=1)
        outer.addLayout(side)
        self.resize(340, 92)

    def rebuild(self) -> None:
        while self.buttons_layout.count():
            item = self.buttons_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = {}
        for task in db.list_tasks(self.main.conn):
            button = MiniTaskButton(task["task_id"], self.main)
            self.buttons[task["task_id"]] = button
            self.buttons_layout.addWidget(button)

    def refresh(self) -> None:
        for button in self.buttons.values():
            button.setChecked(self.main.engine.running_task == button.task_id)
            button.update()

    def closeEvent(self, event) -> None:
        if not self.suppress_restore:
            self.main.exit_mini()
        super().closeEvent(event)


class WeekReportDialog(QDialog):
    """Day-by-day table for one Monday–Sunday week, with prev/next paging."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.anchor = date.today()
        self.setWindowTitle("Weekly report")
        self.resize(720, 360)

        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_btn = QPushButton("◀ Previous week")
        next_btn = QPushButton("Next week ▶")
        prev_btn.clicked.connect(lambda: self._shift(-7))
        next_btn.clicked.connect(lambda: self._shift(7))

        nav = QHBoxLayout()
        nav.addWidget(prev_btn)
        nav.addWidget(self.title, stretch=1)
        nav.addWidget(next_btn)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addWidget(self.table)
        self.refresh()

    def _shift(self, days: int) -> None:
        self.anchor += timedelta(days=days)
        self.refresh()

    def refresh(self) -> None:
        self.window.flush_now()  # so the open week includes up-to-the-second time
        report = build_week_report(self.window.conn, self.anchor)
        days = week_dates(self.anchor)
        self.title.setText(
            f"{days[0].strftime('%d %b %Y')} – {days[-1].strftime('%d %b %Y')}"
        )
        headers = ["Task"] + [d.strftime("%a %d") for d in days] + ["Total"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(report.rows) + 1)

        def put(row: int, col: int, text: str) -> None:
            item = QTableWidgetItem(text)
            if col > 0:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)

        for r, row in enumerate(report.rows):
            put(r, 0, row.task_name)
            for c, secs in enumerate(row.daily_seconds):
                put(r, c + 1, format_hms(secs) if secs else "-")
            put(r, 8, format_hms(row.total_seconds))
        total_r = len(report.rows)
        put(total_r, 0, "TOTAL")
        for c, secs in enumerate(report.day_totals):
            put(total_r, c + 1, format_hms(secs) if secs else "-")
        put(total_r, 8, format_hms(report.grand_total))
        self.table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, db_path=None) -> None:
        super().__init__()
        self.conn = db.connect(db_path or db.default_db_path())
        self.engine = TimerEngine()
        self._tick_count = 0
        self.rows: dict[str, TaskRow] = {}
        self.mini: MiniWindow | None = None

        self.setWindowTitle("timeTrackerTool")
        self.resize(440, 560)
        self.setStyleSheet(STYLESHEET)

        self.banner = QLabel()
        self.banner.setPixmap(
            banner_pixmap().scaledToWidth(408, Qt.TransformationMode.SmoothTransformation)
        )
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.new_task_edit = QLineEdit()
        self.new_task_edit.setPlaceholderText("New task name…")
        self.new_task_edit.returnPressed.connect(self.add_task)
        add_btn = QPushButton("Add task")
        add_btn.clicked.connect(self.add_task)
        mini_btn = QPushButton("Mini ⤡")
        mini_btn.setToolTip("Shrink to an always-on-top emoji strip")
        mini_btn.clicked.connect(self.enter_mini)
        top = QHBoxLayout()
        top.addWidget(self.new_task_edit, stretch=1)
        top.addWidget(add_btn)
        top.addWidget(mini_btn)

        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch()
        rows_host = QWidget()
        rows_host.setLayout(self.rows_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rows_host)

        report_btn = QPushButton("Weekly report")
        report_btn.clicked.connect(self.show_report)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addLayout(top)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(report_btn)
        self.setCentralWidget(central)

        for task in db.list_tasks(self.conn):
            self._add_row(task["task_id"], task["name"], task["emoji"])

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)

    # --- task management -------------------------------------------------

    def add_task(self) -> None:
        name = self.new_task_edit.text().strip()
        if not name:
            return
        task_id = db.create_task(self.conn, name)
        self.new_task_edit.clear()
        self._add_row(task_id, name)

    def _add_row(self, task_id: str, name: str, emoji: str = "") -> None:
        row = TaskRow(task_id, name, self, emoji)
        self.rows[task_id] = row
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)

    def set_emoji(self, task_id: str, parent: QWidget | None = None) -> None:
        row = self.rows[task_id]
        text, ok = QInputDialog.getText(
            parent or self, "Set emoji",
            f"Emoji for '{row.name}' (shown on its mini-mode button):",
            text=row.emoji,
        )
        if ok:
            row.emoji = text.strip()
            db.set_task_emoji(self.conn, task_id, row.emoji)
            row.refresh()
            if self.mini is not None:
                self.mini.refresh()

    def rename_task(self, task_id: str, old_name: str) -> None:
        name, ok = QInputDialog.getText(self, "Rename task", "New name:", text=old_name)
        if ok and name.strip():
            db.rename_task(self.conn, task_id, name)
            self.rows[task_id].name = name.strip()
            self.rows[task_id].refresh()

    def archive_task(self, task_id: str, name: str) -> None:
        confirm = QMessageBox.question(
            self, "Archive task",
            f"Archive '{name}'? Its logged time is kept and still shows in reports.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self.engine.running_task == task_id:
            self.engine.stop(datetime.now())
        self.flush_now()
        db.archive_task(self.conn, task_id)
        row = self.rows.pop(task_id)
        self.rows_layout.removeWidget(row)
        row.deleteLater()

    # --- timing ----------------------------------------------------------

    def toggle_task(self, task_id: str) -> None:
        previous = self.engine.running_task
        self.engine.toggle(task_id, datetime.now())
        self.flush_now()
        for tid in {task_id, previous} - {None}:
            if tid in self.rows:
                self.rows[tid].refresh()
        if self.mini is not None:
            self.mini.refresh()

    def today_seconds(self, task_id: str) -> float:
        today = date.today().isoformat()
        stored = db.seconds_for_day(self.conn, task_id, today)
        return stored + self.engine.pending_seconds(task_id, today, datetime.now())

    def flush_now(self) -> None:
        for (task_id, entry_date), seconds in self.engine.flush(datetime.now()).items():
            db.add_seconds(self.conn, task_id, entry_date, seconds)

    def _tick(self) -> None:
        self._tick_count += 1
        if self._tick_count % FLUSH_EVERY_TICKS == 0:
            self.flush_now()
        if self.engine.running_task in self.rows:
            self.rows[self.engine.running_task].refresh()
        if self.mini is not None and self.mini.isVisible():
            self.mini.refresh()

    # --- mini mode -------------------------------------------------------

    def enter_mini(self) -> None:
        if self.mini is None:
            self.mini = MiniWindow(self)
        self.mini.rebuild()
        self.mini.refresh()
        self.mini.show()
        self.hide()

    def exit_mini(self) -> None:
        if self.mini is not None:
            self.mini.hide()
        self.show()
        self.raise_()
        for row in self.rows.values():
            row.refresh()

    # --- report / shutdown ----------------------------------------------

    def show_report(self) -> None:
        WeekReportDialog(self).exec()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        if self.mini is not None:
            self.mini.suppress_restore = True
            self.mini.close()
        self.engine.stop(datetime.now())
        self.flush_now()
        self.conn.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())  # window icon everywhere; Dock icon on macOS
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
