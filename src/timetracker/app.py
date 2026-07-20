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
    QDialogButtonBox,
    QFrame,
    QGridLayout,
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
# Green "accepted" flash when a timer starts: pulse count and speed
FLASH_PULSES = 6
FLASH_INTERVAL_MS = 90

# Quick-pick emoji for the Set emoji dialog (any emoji can still be typed)
EMOJI_CHOICES = [
    "⏱️", "🔥", "🛡️", "🌐", "🔧", "💻", "🖥️", "📞",
    "📧", "📝", "📊", "📚", "🧠", "🔐", "🔑", "🚨",
    "🧪", "⚙️", "🐍", "📦", "🏗️", "📅", "🗺️", "🤝",
    "☕", "🍔", "🏃", "💤", "🎮", "🎲", "👾", "🚂",
]


def app_icon() -> QIcon:
    """The bundled 13:37 LCD-clock icon (regenerate with scripts/make_assets.py)."""
    return QIcon(str(files("timetracker") / "assets" / "icon.png"))


def banner_pixmap() -> QPixmap:
    """The 80's arcade title-screen banner (regenerate with scripts/make_assets.py)."""
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
QFrame#taskCard[flash="true"] {
    border: 2px solid #22c55e;
    background: rgba(34, 197, 94, 0.30);
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
        self.setProperty("flash", "false")
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

    def set_flash(self, on: bool) -> None:
        if self.property("flash") != str(on).lower():
            self.setProperty("flash", str(on).lower())
            self.style().unpolish(self)
            self.style().polish(self)


class EmojiPickerDialog(QDialog):
    """Pick a task emoji: click one from the grid, or type/paste anything.
    The OS emoji palette works in the text field too (see the hint)."""

    def __init__(self, parent: QWidget | None, task_name: str, current: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set emoji")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Emoji for '{task_name}' (shown on its mini-mode button):"))

        self.edit = QLineEdit(current)
        self.edit.setPlaceholderText("…or type/paste any emoji here")

        self.grid_buttons: list[QPushButton] = []
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, emoji in enumerate(EMOJI_CHOICES):
            button = QPushButton(emoji)
            button.setFlat(True)
            button.setFixedSize(38, 38)
            font = button.font()
            font.setPointSize(18)
            button.setFont(font)
            button.setToolTip("Click to choose")
            button.clicked.connect(lambda _checked=False, e=emoji: self.edit.setText(e))
            self.grid_buttons.append(button)
            grid.addWidget(button, i // 8, i % 8)
        layout.addLayout(grid)
        layout.addWidget(self.edit)

        if sys.platform == "darwin":
            hint = "Tip: press ⌃⌘Space in the box above for the full macOS emoji picker."
        else:
            hint = "Tip: press Win+. in the box above for the full Windows emoji picker."
        hint_label = QLabel(hint)
        hint_label.setStyleSheet("color: rgba(148, 163, 184, 0.9); font-size: 11px;")
        layout.addWidget(hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def get_emoji(parent: QWidget | None, task_name: str, current: str) -> tuple[str, bool]:
        dialog = EmojiPickerDialog(parent, task_name, current)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.edit.text(), accepted


class MiniTaskButton(QPushButton):
    """Mini-mode button: a configurable emoji that scales with the button,
    plus the task name and today's time once the button is tall enough."""

    def __init__(self, task_id: str, window: "MainWindow") -> None:
        super().__init__()
        self.task_id = task_id
        self.window = window
        self.flashing = False
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

    def set_flash(self, on: bool) -> None:
        self.flashing = on
        self.update()

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

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.flashing:
            p.setPen(QPen(QColor("#22c55e"), 3))
            p.setBrush(QColor(34, 197, 94, 80))
        elif running:
            p.setPen(QPen(QColor("#f97316"), 2))
            p.setBrush(QColor(249, 115, 22, 45))
        else:
            p.setPen(QPen(QColor(148, 163, 184, 170), 1))
            p.setBrush(QColor(148, 163, 184, 28))
        p.drawRoundedRect(rect, 10, 10)

        # The name label is always shown; the time joins it once there's room
        show_time = self.shows_description()
        text_zone = 30 if show_time else 15
        emoji_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height() - text_zone)
        emoji_font = self.font()
        emoji_font.setPixelSize(
            max(12, int(min(emoji_rect.width(), emoji_rect.height()) * 0.6))
        )
        p.setFont(emoji_font)
        p.drawText(emoji_rect, Qt.AlignmentFlag.AlignCenter, self.emoji())

        small = self.font()
        small.setPixelSize(10)
        p.setFont(small)
        p.setPen(self.palette().windowText().color())
        metrics = QFontMetrics(small)
        elided = metrics.elidedText(
            name, Qt.TextElideMode.ElideRight, int(rect.width()) - 10
        )
        if show_time:
            p.drawText(
                QRectF(rect.x(), rect.bottom() - 30, rect.width(), 14),
                Qt.AlignmentFlag.AlignCenter, elided,
            )
            p.drawText(
                QRectF(rect.x(), rect.bottom() - 16, rect.width(), 14),
                Qt.AlignmentFlag.AlignCenter, today,
            )
        else:
            p.drawText(
                QRectF(rect.x(), rect.bottom() - 16, rect.width(), 14),
                Qt.AlignmentFlag.AlignCenter, elided,
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
            name = self.main.rows[button.task_id].name
            today = format_hms(self.main.today_seconds(button.task_id))
            button.setToolTip(f"{name} — {today} today")
            button.update()

    def closeEvent(self, event) -> None:
        if not self.suppress_restore:
            self.main.exit_mini()
        super().closeEvent(event)


class ArchivedTasksDialog(QDialog):
    """Manage archived tasks: restore them, or delete them forever
    (task + all logged time, behind a confirmation)."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Archived tasks")
        self.resize(460, 320)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        host = QWidget()
        host.setLayout(self.list_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Archived tasks keep their history and still "
                                "appear in weekly reports until deleted."))
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(buttons)
        self.refresh_list()

    def _archived(self) -> list:
        return [t for t in db.list_tasks(self.window.conn, include_archived=True)
                if t["archived"]]

    def refresh_list(self) -> None:
        while self.list_layout.count() > 1:  # keep the trailing stretch
            item = self.list_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        archived = self._archived()
        if not archived:
            self.list_layout.insertWidget(0, QLabel("Nothing archived."))
            return
        for task in archived:
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(4, 2, 4, 2)
            title = f"{task['emoji']} {task['name']}" if task["emoji"] else task["name"]
            total = db.total_seconds(self.window.conn, task["task_id"])
            box.addWidget(QLabel(f"{title} — {format_hms(total)} logged"), stretch=1)
            restore = QPushButton("Restore")
            restore.clicked.connect(
                lambda _c=False, tid=task["task_id"]: self.restore_task(tid))
            delete = QPushButton("Delete forever")
            delete.clicked.connect(
                lambda _c=False, tid=task["task_id"]: self.delete_task(tid))
            box.addWidget(restore)
            box.addWidget(delete)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def restore_task(self, task_id: str) -> None:
        task = self.window.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        db.unarchive_task(self.window.conn, task_id)
        self.window._add_row(task["task_id"], task["name"], task["emoji"])
        if self.window.mini is not None:
            self.window.mini.rebuild()
            self.window.mini.refresh()
        self.refresh_list()

    def delete_task(self, task_id: str, skip_confirm: bool = False) -> None:
        task = self.window.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        total = db.total_seconds(self.window.conn, task_id)
        if not skip_confirm:
            confirm = QMessageBox.warning(
                self, "Delete forever",
                f"Permanently delete '{task['name']}' and its "
                f"{format_hms(total)} of logged time?\n\n"
                "It will disappear from all weekly reports. This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        db.delete_task(self.window.conn, task_id)
        self.refresh_list()


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

        total_col = len(headers) - 1
        for r, row in enumerate(report.rows):
            put(r, 0, row.task_name)
            for c, secs in enumerate(row.daily_seconds):
                put(r, c + 1, format_hms(secs) if secs else "-")
            put(r, total_col, format_hms(row.total_seconds))
        total_r = len(report.rows)
        put(total_r, 0, "TOTAL")
        for c, secs in enumerate(report.day_totals):
            put(total_r, c + 1, format_hms(secs) if secs else "-")
        put(total_r, total_col, format_hms(report.grand_total))
        self.table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, db_path=None) -> None:
        super().__init__()
        self.conn = db.connect(db_path or db.default_db_path())
        self.engine = TimerEngine()
        self._tick_count = 0
        self._today = date.today()
        self._shutdown_done = False
        self.rows: dict[str, TaskRow] = {}
        self.mini: MiniWindow | None = None
        self._flash_target: str | None = None
        self._flash_count = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._flash_step)

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
        archived_btn = QPushButton("Archived…")
        archived_btn.setToolTip("Restore or permanently delete archived tasks")
        archived_btn.clicked.connect(lambda: ArchivedTasksDialog(self).exec())
        bottom = QHBoxLayout()
        bottom.addWidget(report_btn, stretch=1)
        bottom.addWidget(archived_btn)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addLayout(top)
        layout.addWidget(scroll, stretch=1)
        layout.addLayout(bottom)
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
        text, ok = EmojiPickerDialog.get_emoji(parent or self, row.name, row.emoji)
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
        if self.engine.running_task == task_id:
            self.flash_task(task_id)  # green "accepted" pulse on start

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
        if date.today() != self._today:
            # Midnight rollover: every card's "today" total starts from zero,
            # not just the running one's
            self._today = date.today()
            self.flush_now()
            for row in self.rows.values():
                row.refresh()
        elif self.engine.running_task in self.rows:
            self.rows[self.engine.running_task].refresh()
        if self.mini is not None and self.mini.isVisible():
            self.mini.refresh()

    # --- start flash ------------------------------------------------------

    def flash_task(self, task_id: str) -> None:
        if self._flash_target is not None:
            self._apply_flash(self._flash_target, False)
        self._flash_target = task_id
        self._flash_count = 0
        self._flash_timer.start(FLASH_INTERVAL_MS)
        self._flash_step()

    def _flash_step(self) -> None:
        if self._flash_target is None:
            self._flash_timer.stop()
            return
        if self._flash_count >= FLASH_PULSES:
            self._flash_timer.stop()
            self._apply_flash(self._flash_target, False)
            self._flash_target = None
            return
        self._apply_flash(self._flash_target, self._flash_count % 2 == 0)
        self._flash_count += 1

    def _apply_flash(self, task_id: str, on: bool) -> None:
        row = self.rows.get(task_id)
        if row is not None:
            row.set_flash(on)
        if self.mini is not None and task_id in self.mini.buttons:
            self.mini.buttons[task_id].set_flash(on)

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

    def shutdown(self) -> None:
        """Stop timers, bank all pending time, close the DB. Idempotent —
        called from closeEvent AND app.aboutToQuit, because quitting from
        mini mode may never deliver a closeEvent to the hidden main window."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self.timer.stop()
        self._flash_timer.stop()
        self.engine.stop(datetime.now())
        self.flush_now()
        self.conn.close()

    def closeEvent(self, event) -> None:
        if self.mini is not None:
            self.mini.suppress_restore = True
            self.mini.close()
        self.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())  # window icon everywhere; Dock icon on macOS
    window = MainWindow()
    # Safety net: flush even when quit arrives without a closeEvent
    # (e.g. Cmd-Q while in mini mode, where the main window is hidden)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
