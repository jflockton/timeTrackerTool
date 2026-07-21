"""PySide6 GUI: one toggle button per task, live daily totals, weekly report.

Single-active model: starting a task stops whichever task was running.
Accumulated time is flushed to SQLite every few seconds and on close, so
a crash loses at most FLUSH_EVERY_TICKS seconds.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time as dtime, timedelta
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QLockFile, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFontMetrics, QIcon, QPainter, QPen, QColor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from . import autostart, db, icons, sync
from .banner import BannerWidget
from .cube import SIDES, CubeListener, open_bluetooth_settings
from .core import TimerEngine, format_hms, split_span_by_date
from .idle import IDLE_THRESHOLD_S, IdleWatcher, system_idle_seconds
from .report import (
    build_month_report,
    build_week_report,
    month_dates,
    to_csv,
    to_markdown,
    week_dates,
)

TICK_MS = 1000
FLUSH_EVERY_TICKS = 10
# Mini-mode buttons show name + time once they are at least this tall (px)
MINI_TEXT_THRESHOLD = 96
DEFAULT_EMOJI = "⏱️"
# Green "accepted" flash when a timer starts: pulse count and speed
FLASH_PULSES = 6
FLASH_INTERVAL_MS = 90
# System-idle poll cadence (the ioreg call is cheap but not free)
IDLE_CHECK_EVERY_TICKS = 5
# Single-instance local-socket name (per-user)
INSTANCE_SERVER = f"timeTrackerTool-{os.environ.get('USER') or os.environ.get('USERNAME') or 'user'}"
# Settings defaults (stored in the settings table once changed)
DEFAULT_TARGET_HOURS = "7.5"
DEFAULT_NUDGE_STOP = "18:30"
DEFAULT_NUDGE_START = "09:30"
DEFAULT_OBSIDIAN_DIR = "~/Dropbox/obsidianVault/00 - Inbox"
NUDGE_CHECK_EVERY_TICKS = 30


def _parse_hhmm(value: str) -> dtime | None:
    try:
        hours, minutes = value.split(":")
        return dtime(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return None

# Quick-pick emoji for the Set emoji dialog (any emoji can still be typed)
EMOJI_CHOICES = [
    "⏱️", "🔥", "🛡️", "🌐", "🔧", "💻", "🖥️", "📞",
    "📧", "📝", "📊", "📚", "🧠", "🔐", "🔑", "🚨",
    "🧪", "⚙️", "🐍", "📦", "🏗️", "📅", "🗺️", "🤝",
    "☕", "🍔", "🏃", "💤", "🎮", "🎲", "👾", "🚂",
]


def app_icon() -> QIcon:
    """The bundled 13:37 LCD-clock icon (regenerate with scripts/make_assets.py).
    Pre-scaled smoothly to the common small sizes — letting the platform
    scale the 1024px original down to 16px is what made it look muddy in
    the taskbar."""
    from PySide6.QtGui import QPixmap

    source = QPixmap(str(files("timetracker") / "assets" / "icon.png"))
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(source.scaled(
            size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
    return icon


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

THEME_CHOICES = [("", "System default"), ("light", "Light"), ("dark", "Dark")]

# The OS-provided palette, captured the first time a theme is applied so
# "System default" can restore it after a forced light/dark palette.
_system_palette = None


def scheme_for_theme(theme: str) -> Qt.ColorScheme:
    """Map the stored theme setting to a Qt colour scheme; anything
    unrecognised (including the empty default) means follow the OS."""
    return {"light": Qt.ColorScheme.Light,
            "dark": Qt.ColorScheme.Dark}.get(theme, Qt.ColorScheme.Unknown)


def _palette_for_theme(theme: str) -> "QPalette":
    """Explicit palettes for the forced modes. setColorScheme alone is not
    enough — with the default Windows style it leaves the palette untouched
    (verified), so the task area kept the old colours when the OS and the
    chosen theme disagreed."""
    from PySide6.QtGui import QPalette

    palette = QPalette()
    if theme == "dark":
        colours = {
            QPalette.ColorRole.Window: "#2b2b2b",
            QPalette.ColorRole.WindowText: "#f0f0f0",
            QPalette.ColorRole.Base: "#232323",
            QPalette.ColorRole.AlternateBase: "#2b2b2b",
            QPalette.ColorRole.ToolTipBase: "#2b2b2b",
            QPalette.ColorRole.ToolTipText: "#f0f0f0",
            QPalette.ColorRole.Text: "#f0f0f0",
            QPalette.ColorRole.Button: "#333333",
            QPalette.ColorRole.ButtonText: "#f0f0f0",
            QPalette.ColorRole.BrightText: "#ff5555",
            QPalette.ColorRole.Link: "#60a5fa",
            QPalette.ColorRole.Highlight: "#2a82da",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.PlaceholderText: "#909090",
        }
        disabled_text = "#7f7f7f"
    else:
        colours = {
            QPalette.ColorRole.Window: "#efefef",
            QPalette.ColorRole.WindowText: "#1a1a1a",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#f3f4f6",
            QPalette.ColorRole.ToolTipBase: "#ffffdc",
            QPalette.ColorRole.ToolTipText: "#1a1a1a",
            QPalette.ColorRole.Text: "#1a1a1a",
            QPalette.ColorRole.Button: "#e7e7e7",
            QPalette.ColorRole.ButtonText: "#1a1a1a",
            QPalette.ColorRole.BrightText: "#d92626",
            QPalette.ColorRole.Link: "#1d4ed8",
            QPalette.ColorRole.Highlight: "#2a82da",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.PlaceholderText: "#8a8a8a",
        }
        disabled_text = "#a0a0a0"
    for role, colour in colours.items():
        palette.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role,
                         QColor(disabled_text))
    return palette


def apply_theme(theme: str) -> None:
    """Switch the whole app between light / dark / follow-the-OS. The card
    styling uses translucent colours, so it reads fine on both palettes."""
    global _system_palette
    app = QApplication.instance()
    if _system_palette is None:
        from PySide6.QtGui import QPalette
        _system_palette = QPalette(app.palette())
    app.styleHints().setColorScheme(scheme_for_theme(theme))
    if theme in ("light", "dark"):
        app.setPalette(_palette_for_theme(theme))
    else:
        app.setPalette(_system_palette)
    # Stylesheet-styled widgets (the task cards and everything inside the
    # main window) cache their resolved colours at polish time and do NOT
    # pick up an application palette change on their own. Clear any
    # per-widget palette a style's polish() may have stamped on (that stamp
    # blocks all later propagation), then repolish with the widget's OWN
    # style — using app.style() here re-stamps and breaks the next switch.
    from PySide6.QtGui import QPalette as _QPalette
    for widget in app.allWidgets():
        widget.setPalette(_QPalette())
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class TaskRow(QFrame):
    """One task in its own bordered card: name, today's time, start/stop."""

    def __init__(self, task_id: str, name: str, window: "MainWindow",
                 emoji: str = "", show_in_mini: bool = True) -> None:
        super().__init__()
        self.task_id = task_id
        self.name = name
        self.emoji = emoji
        self.show_in_mini = show_in_mini
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

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(22, 22)

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
        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label, stretch=1)
        layout.addWidget(self.time_label)
        self.refresh()

    def _on_clicked(self) -> None:
        self.window.toggle_task(self.task_id)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        emoji = menu.addAction("Set icon…")
        menu.addSeparator()
        move_up = menu.addAction("Move up")
        move_down = menu.addAction("Move down")
        menu.addSeparator()
        mini = menu.addAction("Show in mini tracker")
        mini.setCheckable(True)
        mini.setChecked(self.show_in_mini)
        menu.addSeparator()
        archive = menu.addAction("Archive")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen == rename:
            self.window.rename_task(self.task_id, self.name)
        elif chosen == emoji:
            self.window.set_emoji(self.task_id)
        elif chosen == move_up:
            self.window.move_task(self.task_id, -1)
        elif chosen == move_down:
            self.window.move_task(self.task_id, +1)
        elif chosen == mini:
            self.window.toggle_show_in_mini(self.task_id)
        elif chosen == archive:
            self.window.archive_task(self.task_id, self.name)

    def refresh(self) -> None:
        running = self.window.engine.running_task == self.task_id
        seconds = self.window.today_seconds(self.task_id)
        self.button.setText("■ Stop" if running else "▶ Start")
        self.button.setChecked(running)
        if icons.is_custom(self.emoji):
            self.icon_label.setPixmap(
                icons.pixmap(self.emoji, 22, self.devicePixelRatioF()))
            self.icon_label.show()
            self.name_label.setText(self.name)
        else:
            self.icon_label.hide()
            self.name_label.setText(
                f"{self.emoji} {self.name}" if self.emoji else self.name)
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
    """Pick a task icon: a code-drawn icon from the Icons tab (coding, docs,
    project work, meetings, calls, email — four colours each), a monochrome
    icon from the searchable Library tab (the free Notion set — tinted to
    the theme), or any emoji from the Emoji tab. Clicking an icon chooses
    it immediately; the emoji tab keeps the type-anything field and OK."""

    def __init__(self, parent: QWidget | None, task_name: str, current: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set icon")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(f"Icon for '{task_name}' (shown on its mini-mode button):"))
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- Icons tab: click-to-choose, closes the dialog -----------------
        icons_page = QWidget()
        icons_layout = QVBoxLayout(icons_page)
        self.icon_buttons: list[QPushButton] = []
        icon_grid = QGridLayout()
        icon_grid.setSpacing(2)
        per_row = len(icons.COLOURS) * 2
        for i, token in enumerate(icons.ICON_CHOICES):
            button = QPushButton()
            button.setFlat(True)
            button.setFixedSize(38, 38)
            button.setIcon(icons.qicon(token))
            button.setIconSize(button.size() * 0.85)
            button.setToolTip(icons.label(token))
            button.clicked.connect(
                lambda _checked=False, t=token: self._choose_icon(t))
            self.icon_buttons.append(button)
            icon_grid.addWidget(button, i // per_row, i % per_row)
        icons_layout.addLayout(icon_grid)
        icon_hint = QLabel("Click an icon to use it.")
        icon_hint.setStyleSheet("color: rgba(148, 163, 184, 0.9); font-size: 11px;")
        icons_layout.addWidget(icon_hint)
        icons_layout.addStretch()
        tabs.addTab(icons_page, "Icons")

        # --- Library tab: the Notion monochrome set, searchable -------------
        # Free Notion icon library via files2notion.com, tinted at render
        # time to follow the theme (white in dark mode, black in light).
        # No captions under the icons — hover for the name.
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        self.notion_search = QLineEdit()
        self.notion_search.setPlaceholderText(
            f"Search {len(icons.notion_names())} icons…")
        self.notion_search.setClearButtonEnabled(True)
        library_layout.addWidget(self.notion_search)
        self.notion_list = QListWidget()
        self.notion_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.notion_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.notion_list.setMovement(QListWidget.Movement.Static)
        self.notion_list.setUniformItemSizes(True)
        self.notion_list.setIconSize(QSize(30, 30))
        self.notion_list.setGridSize(QSize(42, 42))
        self.notion_list.setMinimumSize(420, 300)
        dpr = self.devicePixelRatioF()
        for name in icons.notion_names():
            token = f"{icons.NOTION_PREFIX}{name}"
            item = QListWidgetItem()
            item.setIcon(QIcon(icons.pixmap(token, 30, dpr)))
            item.setToolTip(icons.label(token))
            item.setData(Qt.ItemDataRole.UserRole, token)
            self.notion_list.addItem(item)
        self.notion_list.itemClicked.connect(
            lambda item: self._choose_icon(item.data(Qt.ItemDataRole.UserRole)))
        self.notion_search.textChanged.connect(self._filter_notion)
        library_layout.addWidget(self.notion_list, stretch=1)
        tabs.addTab(library_page, "Library")

        # --- Emoji tab: the classic grid + type-anything field --------------
        emoji_page = QWidget()
        emoji_layout = QVBoxLayout(emoji_page)
        self.edit = QLineEdit("" if icons.is_custom(current) else current)
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
        emoji_layout.addLayout(grid)
        emoji_layout.addWidget(self.edit)

        if sys.platform == "darwin":
            hint = "Tip: press ⌃⌘Space in the box above for the full macOS emoji picker."
        else:
            hint = "Tip: press Win+. in the box above for the full Windows emoji picker."
        hint_label = QLabel(hint)
        hint_label.setStyleSheet("color: rgba(148, 163, 184, 0.9); font-size: 11px;")
        emoji_layout.addWidget(hint_label)
        tabs.addTab(emoji_page, "Emoji")

        # Open on the tab matching the current pick
        if icons.is_notion(current):
            tabs.setCurrentIndex(1)
        elif current and not icons.is_custom(current):
            tabs.setCurrentIndex(2)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_icon(self, token: str) -> None:
        self.edit.setText(token)
        self.accept()

    def _filter_notion(self, text: str) -> None:
        needle = text.strip().lower().replace(" ", "-")
        for i in range(self.notion_list.count()):
            item = self.notion_list.item(i)
            token = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(bool(needle) and needle not in token)

    @staticmethod
    def get_emoji(parent: QWidget | None, task_name: str, current: str) -> tuple[str, bool]:
        dialog = EmojiPickerDialog(parent, task_name, current)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        text = dialog.edit.text()
        if accepted and not text.strip() and icons.is_custom(current):
            # The field starts blank for icon tasks; a bare OK means
            # "no change", not "remove my icon".
            text = current
        return text, accepted


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
        emoji = menu.addAction("Set icon…")
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
        token = self.emoji()
        if icons.is_custom(token):
            # Render at the exact size (and DPR) needed — scaling a fixed
            # bitmap here is what made icons look blocky next to emoji.
            side = max(12, int(min(emoji_rect.width(), emoji_rect.height()) * 0.8))
            pm = icons.pixmap(token, side, self.devicePixelRatioF())
            p.drawPixmap(
                int(emoji_rect.center().x() - side / 2),
                int(emoji_rect.center().y() - side / 2), pm)
        else:
            emoji_font = self.font()
            emoji_font.setPixelSize(
                max(12, int(min(emoji_rect.width(), emoji_rect.height()) * 0.6))
            )
            p.setFont(emoji_font)
            p.drawText(emoji_rect, Qt.AlignmentFlag.AlignCenter, token)

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
            if not task["show_in_mini"]:
                continue
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


class CubeSettingsDialog(QDialog):
    """Map each side of the Timeular cube to a task, with optional sticker
    labels. Saves straight to the settings table — the mappings are only
    acted on while the cube is enabled in the main Settings dialog."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        conn = window.conn
        self.setWindowTitle("Bluetooth time-tracker cube")
        form = QFormLayout(self)

        # The side numbers are fixed in the tracker's firmware — flip the
        # cube and watch the status bar to see which face is which number,
        # then note your sticker here and map it to a task.
        tasks = db.list_tasks(conn)
        self.cube_combos: dict[int, QComboBox] = {}
        self.cube_labels: dict[int, QLineEdit] = {}
        for side in SIDES:
            sticker = QLineEdit(db.get_setting(conn, f"cube_label_{side}", ""))
            sticker.setPlaceholderText("your sticker…")
            sticker.setMaximumWidth(130)
            combo = QComboBox()
            combo.addItem("— stop timer —", "")
            current = db.get_setting(conn, f"cube_side_{side}", "")
            for task in tasks:
                if icons.is_custom(task["emoji"]):
                    combo.addItem(icons.qicon(task["emoji"]), task["name"],
                                  task["task_id"])
                else:
                    label = (f"{task['emoji']} {task['name']}" if task["emoji"]
                             else task["name"])
                    combo.addItem(label, task["task_id"])
                if task["task_id"] == current:
                    combo.setCurrentIndex(combo.count() - 1)
            self.cube_labels[side] = sticker
            self.cube_combos[side] = combo
            row = QHBoxLayout()
            row.addWidget(sticker)
            row.addWidget(combo, stretch=1)
            form.addRow(f"🎲 Side {side}:", row)
        hint = QLabel("Side numbers are fixed by the cube itself — flip a face "
                      "up and the status bar shows its number.")
        hint.setStyleSheet("color: rgba(148, 163, 184, 0.9); font-size: 11px;")
        form.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> None:
        conn = self.window.conn
        for side, combo in self.cube_combos.items():
            db.set_setting(conn, f"cube_side_{side}", combo.currentData() or "")
            db.set_setting(conn, f"cube_label_{side}",
                           self.cube_labels[side].text().strip())
        self.accept()


class SettingsDialog(QDialog):
    """Sync folder, launch at login, daily target, nudges, Obsidian folder."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        conn = window.conn
        self.setWindowTitle("Settings")
        form = QFormLayout(self)

        self.sync_edit = QLineEdit(db.get_setting(conn, "sync_dir", ""))
        self.sync_edit.setPlaceholderText("e.g. ~/Dropbox/timeTrackerSync (empty = off)")
        sync_browse = QPushButton("Browse…")
        sync_browse.clicked.connect(lambda: self._browse(self.sync_edit))
        sync_now = QPushButton("Sync now")
        sync_now.clicked.connect(self._sync_now)
        sync_row = QHBoxLayout()
        sync_row.addWidget(self.sync_edit, stretch=1)
        sync_row.addWidget(sync_browse)
        sync_row.addWidget(sync_now)
        form.addRow("🔀 Sync folder:", sync_row)

        self.login_check = QCheckBox("Start timeTrackerTool when I log in")
        self.login_check.setChecked(autostart.is_enabled())
        form.addRow("🚀 Autostart:", self.login_check)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0, 24.0)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.setSuffix(" h")
        self.target_spin.setSpecialValueText("off")
        self.target_spin.setValue(
            float(db.get_setting(conn, "target_hours", DEFAULT_TARGET_HOURS)))
        form.addRow("🎯 Daily target:", self.target_spin)

        self.nudge_stop_check = QCheckBox("Nudge if a timer is still running after")
        self.nudge_stop_time = QTimeEdit()
        stop_setting = db.get_setting(conn, "nudge_stop_time", DEFAULT_NUDGE_STOP)
        self.nudge_stop_check.setChecked(bool(stop_setting))
        parsed = _parse_hhmm(stop_setting or DEFAULT_NUDGE_STOP)
        self.nudge_stop_time.setTime(parsed if parsed else dtime(18, 30))
        stop_row = QHBoxLayout()
        stop_row.addWidget(self.nudge_stop_check)
        stop_row.addWidget(self.nudge_stop_time)
        form.addRow("🌙 Evening:", stop_row)

        self.nudge_start_check = QCheckBox("Nudge if nothing is tracked by")
        self.nudge_start_time = QTimeEdit()
        start_setting = db.get_setting(conn, "nudge_start_time", DEFAULT_NUDGE_START)
        self.nudge_start_check.setChecked(bool(start_setting))
        parsed = _parse_hhmm(start_setting or DEFAULT_NUDGE_START)
        self.nudge_start_time.setTime(parsed if parsed else dtime(9, 30))
        start_row = QHBoxLayout()
        start_row.addWidget(self.nudge_start_check)
        start_row.addWidget(self.nudge_start_time)
        form.addRow("🌅 Morning:", start_row)

        self.banner_check = QCheckBox("Animated banner (marching invaders, saucer raids)")
        self.banner_check.setChecked(
            db.get_setting(conn, "banner_animated", "1") == "1")
        form.addRow("👾 Banner:", self.banner_check)

        self.theme_combo = QComboBox()
        for value, text in THEME_CHOICES:
            self.theme_combo.addItem(text, value)
        current_theme = db.get_setting(conn, "theme", "")
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(current_theme)))
        form.addRow("🎨 Theme:", self.theme_combo)

        self.cube_check = QCheckBox(
            "Enable Timeular tracker (close the official Timeular app first)")
        self.cube_check.setChecked(db.get_setting(conn, "cube_enabled", "0") == "1")
        form.addRow("🎲 Cube:", self.cube_check)

        self.cube_config_btn = QPushButton("Configure bluetooth time-tracker cube…")
        self.cube_config_btn.clicked.connect(
            lambda: CubeSettingsDialog(self.window).exec())
        form.addRow("", self.cube_config_btn)
        self._form = form
        self.cube_check.toggled.connect(self._update_cube_button)
        self._update_cube_button(self.cube_check.isChecked())

        self.obsidian_edit = QLineEdit(
            db.get_setting(conn, "obsidian_dir", DEFAULT_OBSIDIAN_DIR))
        obsidian_browse = QPushButton("Browse…")
        obsidian_browse.clicked.connect(lambda: self._browse(self.obsidian_edit))
        obsidian_row = QHBoxLayout()
        obsidian_row.addWidget(self.obsidian_edit, stretch=1)
        obsidian_row.addWidget(obsidian_browse)
        form.addRow("🧠 Obsidian folder:", obsidian_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_cube_button(self, checked: bool) -> None:
        # Hide the whole form row, not just the button, so no blank gap is
        # left behind when the cube is disabled.
        self._form.setRowVisible(self.cube_config_btn, checked)
        self.adjustSize()

    def _browse(self, edit: QLineEdit) -> None:
        start = str(Path(edit.text()).expanduser()) if edit.text() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if folder:
            edit.setText(folder)

    def _sync_now(self) -> None:
        db.set_setting(self.window.conn, "sync_dir", self.sync_edit.text().strip())
        stats = self.window.sync_now()
        if stats is None:
            QMessageBox.warning(self, "Sync", "Set a valid sync folder first.")
        else:
            QMessageBox.information(
                self, "Sync",
                f"Merged {stats['files']} other machine file(s): "
                f"{stats['tasks_added']} new task(s), "
                f"{stats['entries_merged']} entrie(s) updated.\n"
                "This machine's snapshot has been published.")

    def save(self) -> None:
        conn = self.window.conn
        db.set_setting(conn, "sync_dir", self.sync_edit.text().strip())
        db.set_setting(conn, "target_hours", str(self.target_spin.value()))
        db.set_setting(conn, "nudge_stop_time",
                       self.nudge_stop_time.time().toString("HH:mm")
                       if self.nudge_stop_check.isChecked() else "")
        db.set_setting(conn, "nudge_start_time",
                       self.nudge_start_time.time().toString("HH:mm")
                       if self.nudge_start_check.isChecked() else "")
        db.set_setting(conn, "obsidian_dir", self.obsidian_edit.text().strip())
        db.set_setting(conn, "banner_animated",
                       "1" if self.banner_check.isChecked() else "0")
        db.set_setting(conn, "theme", self.theme_combo.currentData())
        db.set_setting(conn, "cube_enabled",
                       "1" if self.cube_check.isChecked() else "0")
        try:
            if self.login_check.isChecked():
                autostart.enable()
            else:
                autostart.disable()
        except Exception as exc:  # registry/plist hiccups shouldn't eat settings
            QMessageBox.warning(self, "Autostart", f"Couldn't update autostart: {exc}")
        self.window.apply_settings()
        self.accept()


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
            if icons.is_custom(task["emoji"]):
                title = task["name"]  # the raw icon:… token is not for humans
            elif task["emoji"]:
                title = f"{task['emoji']} {task['name']}"
            else:
                title = task["name"]
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
        self.window._add_row(task["task_id"], task["name"], task["emoji"],
                             bool(task["show_in_mini"]))
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
    """Day-by-day table, week or month view, with paging and CSV export."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.anchor = date.today()
        self.mode = "week"
        self.setWindowTitle("Report")
        self.resize(760, 380)

        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_btn = QPushButton("◀ Previous")
        self.next_btn = QPushButton("Next ▶")
        self.prev_btn.clicked.connect(lambda: self._shift(-1))
        self.next_btn.clicked.connect(lambda: self._shift(1))
        self.mode_btn = QPushButton("Month view")
        self.mode_btn.clicked.connect(self.toggle_mode)
        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self.export_csv)
        obsidian_btn = QPushButton("→ Obsidian")
        obsidian_btn.setToolTip("Save this view as a markdown note in the vault")
        obsidian_btn.clicked.connect(self.export_obsidian)

        nav = QHBoxLayout()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.title, stretch=1)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.mode_btn)
        nav.addWidget(export_btn)
        nav.addWidget(obsidian_btn)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addWidget(self.table)
        self.refresh()

    def toggle_mode(self) -> None:
        self.mode = "month" if self.mode == "week" else "week"
        self.mode_btn.setText("Week view" if self.mode == "month" else "Month view")
        self.refresh()

    def _shift(self, direction: int) -> None:
        if self.mode == "week":
            self.anchor += timedelta(days=7 * direction)
        else:
            first = self.anchor.replace(day=1)
            if direction < 0:
                self.anchor = (first - timedelta(days=1)).replace(day=1)
            else:
                self.anchor = (first + timedelta(days=32)).replace(day=1)
        self.refresh()

    def _current_report(self):
        if self.mode == "week":
            return build_week_report(self.window.conn, self.anchor)
        return build_month_report(self.window.conn, self.anchor)

    def _period_label(self) -> str:
        if self.mode == "week":
            days = week_dates(self.anchor)
            return f"Week of {days[0].strftime('%d %b %Y')}"
        return self.anchor.strftime("%B %Y")

    def export_obsidian(self) -> None:
        folder = Path(db.get_setting(
            self.window.conn, "obsidian_dir", DEFAULT_OBSIDIAN_DIR)).expanduser()
        if not folder.is_dir():
            QMessageBox.warning(
                self, "Obsidian export",
                f"Folder not found:\n{folder}\n\nSet it in Settings (☰) first.")
            return
        self.window.flush_now()
        label = self._period_label()
        note = to_markdown(self._current_report(), label)
        filename = f"{date.today().isoformat()}_timeTracker {label}.md"
        path = folder / filename
        path.write_text(note, encoding="utf-8")
        QMessageBox.information(self, "Obsidian export", f"Saved:\n{path}")

    def export_csv(self) -> None:
        if self.mode == "week":
            stamp = week_dates(self.anchor)[0].isoformat()
            default = f"timetracker_week_{stamp}.csv"
        else:
            default = f"timetracker_{self.anchor.strftime('%Y-%m')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", default, "CSV files (*.csv)")
        if not path:
            return
        self.window.flush_now()
        with open(path, "w", newline="", encoding="utf-8") as handle:
            handle.write(to_csv(self._current_report()))

    def refresh(self) -> None:
        self.window.flush_now()  # so the open period includes up-to-the-second time
        report = self._current_report()
        days = report.dates
        if self.mode == "week":
            self.title.setText(
                f"{days[0].strftime('%d %b %Y')} – {days[-1].strftime('%d %b %Y')}"
            )
            day_headers = [d.strftime("%a %d") for d in days]
        else:
            self.title.setText(days[0].strftime("%B %Y"))
            day_headers = [d.strftime("%d") for d in days]
        headers = ["Task"] + day_headers + ["Total"]
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
        self.idle_watcher = IdleWatcher()
        self.cube: CubeListener | None = None
        self.tray: QSystemTrayIcon | None = None
        self.tray_task_actions: dict[str, QAction] = {}

        self.setWindowTitle("timeTrackerTool")
        self.resize(440, 560)
        self.setStyleSheet(STYLESHEET)

        # Live arcade banner: marching invaders, blinking prompt, and a
        # saucer strafing run at random intervals. 1UP shows real time.
        self.banner = BannerWidget()

        self.new_task_edit = QLineEdit()
        self.new_task_edit.setPlaceholderText("New task name…")
        edit_font = self.new_task_edit.font()
        edit_font.setPointSize(edit_font.pointSize() + 2)
        self.new_task_edit.setFont(edit_font)
        self.new_task_edit.setFixedHeight(
            int(self.new_task_edit.sizeHint().height() * 1.25))
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

        report_btn = QPushButton("Reports")
        report_btn.clicked.connect(self.show_report)
        archived_btn = QPushButton("Archived…")
        archived_btn.setToolTip("Restore or permanently delete archived tasks")
        archived_btn.clicked.connect(lambda: ArchivedTasksDialog(self).exec())
        settings_btn = QPushButton("☰")
        # Match the neighbouring buttons' height exactly; scale the glyph
        # to the button rather than hardcoding a font size.
        btn_height = archived_btn.sizeHint().height()
        settings_btn.setFixedSize(int(btn_height * 1.4), btn_height)
        burger_font = settings_btn.font()
        burger_font.setPixelSize(max(12, int(btn_height * 0.5)))
        settings_btn.setFont(burger_font)
        settings_btn.setToolTip("Settings: sync, autostart, daily target, nudges")
        settings_btn.clicked.connect(lambda: SettingsDialog(self).exec())
        bottom = QHBoxLayout()
        bottom.addWidget(report_btn, stretch=1)
        bottom.addWidget(archived_btn)
        bottom.addWidget(settings_btn)

        # Daily target progress ("1UP" bar); hidden when target is off
        self.target_bar = QProgressBar()
        self.target_bar.setRange(0, 100)
        self.target_bar.setTextVisible(True)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addLayout(top)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self.target_bar)
        layout.addLayout(bottom)
        self.setCentralWidget(central)

        for task in db.list_tasks(self.conn):
            self._add_row(task["task_id"], task["name"], task["emoji"],
                          bool(task["show_in_mini"]))

        # Menu-bar / system-tray presence (skipped where no tray exists,
        # e.g. offscreen test runs)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.activated.connect(self._tray_activated)
            self._rebuild_tray_menu()
            self.tray.show()

        self._nudged_stop: date | None = None
        self._nudged_start: date | None = None
        self.apply_settings()
        self.sync_now()  # pull other machines' history on startup (if configured)

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

    def _add_row(self, task_id: str, name: str, emoji: str = "",
                 show_in_mini: bool = True) -> None:
        row = TaskRow(task_id, name, self, emoji, show_in_mini)
        self.rows[task_id] = row
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self._rebuild_tray_menu()

    def toggle_show_in_mini(self, task_id: str) -> None:
        row = self.rows[task_id]
        row.show_in_mini = not row.show_in_mini
        db.set_task_mini(self.conn, task_id, row.show_in_mini)
        if self.mini is not None:
            self.mini.rebuild()
            self.mini.refresh()

    def move_task(self, task_id: str, delta: int) -> None:
        if not db.move_task(self.conn, task_id, delta):
            return  # already at the top/bottom
        row = self.rows[task_id]
        index = self.rows_layout.indexOf(row)
        self.rows_layout.removeWidget(row)
        self.rows_layout.insertWidget(index + delta, row)
        # Keep the rows dict in display order — the tray menu is built from it
        self.rows = {t["task_id"]: self.rows[t["task_id"]]
                     for t in db.list_tasks(self.conn)}
        self._rebuild_tray_menu()
        if self.mini is not None:
            self.mini.rebuild()
            self.mini.refresh()

    def set_emoji(self, task_id: str, parent: QWidget | None = None) -> None:
        row = self.rows[task_id]
        text, ok = EmojiPickerDialog.get_emoji(parent or self, row.name, row.emoji)
        if ok:
            row.emoji = text.strip()
            db.set_task_emoji(self.conn, task_id, row.emoji)
            row.refresh()
            if self.mini is not None:
                self.mini.refresh()
            self._rebuild_tray_menu()

    def rename_task(self, task_id: str, old_name: str) -> None:
        name, ok = QInputDialog.getText(self, "Rename task", "New name:", text=old_name)
        if ok and name.strip():
            db.rename_task(self.conn, task_id, name)
            self.rows[task_id].name = name.strip()
            self.rows[task_id].refresh()
            self._rebuild_tray_menu()
            self._update_window_title()

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
        self._rebuild_tray_menu()

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
        self._update_tray_state()
        self._update_window_title()
        if self.engine.running_task == task_id:
            self.flash_task(task_id)  # green "accepted" pulse on start

    def _update_window_title(self) -> None:
        """Carry the running task in the title, like Excel carries the
        document — so the taskbar and Alt-Tab say what's being tracked."""
        running = self.engine.running_task
        if running is not None and running in self.rows:
            title = (f"▶ {self.rows[running].name} · "
                     f"{format_hms(self.today_seconds(running))} today"
                     " — timeTrackerTool")
        else:
            title = "timeTrackerTool"
        if self.windowTitle() != title:
            self.setWindowTitle(title)
        if self.mini is not None and self.mini.windowTitle() != title:
            self.mini.setWindowTitle(title)

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
        if self._tick_count % IDLE_CHECK_EVERY_TICKS == 0:
            self._check_idle()
        if self._tick_count % NUDGE_CHECK_EVERY_TICKS == 0:
            self._nudge_check(datetime.now())
        if self.target_hours > 0:
            self._update_target_bar()
        self.banner.set_scores(
            format_hms(self.today_total()),
            format_hms(self.target_hours * 3600) if self.target_hours > 0 else "8:00:00",
        )
        if self.tray is not None:
            self._update_tray_state()
        self._update_window_title()
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

    # --- settings / sync / target / nudges --------------------------------

    def apply_settings(self) -> None:
        self.target_hours = float(
            db.get_setting(self.conn, "target_hours", DEFAULT_TARGET_HOURS))
        self.target_bar.setVisible(self.target_hours > 0)
        self._update_target_bar()
        self.banner.set_animated(
            db.get_setting(self.conn, "banner_animated", "1") == "1")
        apply_theme(db.get_setting(self.conn, "theme", ""))
        # Notion-library icons are tinted to the theme — re-render the card
        # chips and tray icons so they flip black/white with the palette.
        for row in self.rows.values():
            row.refresh()
        self._rebuild_tray_menu()
        self._apply_cube_setting()

    # --- Timeular cube ----------------------------------------------------

    def _apply_cube_setting(self) -> None:
        enabled = db.get_setting(self.conn, "cube_enabled", "0") == "1"
        if enabled and self.cube is None:
            if not hasattr(self, "_bt_settings_btn"):
                self._bt_settings_btn = QPushButton("Open Bluetooth settings")
                self._bt_settings_btn.setToolTip(
                    "Allow timeTrackerTool in Privacy & Security ▸ Bluetooth, "
                    "then restart the app")
                self._bt_settings_btn.clicked.connect(open_bluetooth_settings)
                self._bt_settings_btn.hide()
                self.statusBar().addPermanentWidget(self._bt_settings_btn)
            self.cube = CubeListener()
            self.cube.side_changed.connect(self._on_cube_side)
            self.cube.status_changed.connect(self._on_cube_status)
            self.cube.start()
        elif not enabled and self.cube is not None:
            self.cube.stop()
            self.cube = None
            self.statusBar().clearMessage()
            if hasattr(self, "_bt_settings_btn"):
                self._bt_settings_btn.hide()

    def _on_cube_status(self, message: str) -> None:
        self.statusBar().showMessage(message)
        if hasattr(self, "_bt_settings_btn"):
            self._bt_settings_btn.setVisible("denied" in message.lower())

    def _on_cube_side(self, side: int) -> None:
        """A cube flip: mapped side up starts that task; the base, an
        unmapped side, or an unknown value stops the running timer."""
        if db.get_setting(self.conn, "cube_enabled", "0") != "1":
            return
        task_id = (db.get_setting(self.conn, f"cube_side_{side}", "")
                   if side in SIDES else "")
        if not task_id or task_id not in self.rows:
            self.stop_running()
        elif task_id != self.engine.running_task:
            self.toggle_task(task_id)
        self.statusBar().showMessage(self._describe_flip(side, task_id))

    def _describe_flip(self, side: int, task_id: str) -> str:
        """'Cube: side 3 (deep work) → Project work' — sticker label included
        so identifying/naming faces is just flip-and-read."""
        if side == 0:
            return "Cube: on its base → timer stopped"
        text = f"Cube: side {side}"
        sticker = db.get_setting(self.conn, f"cube_label_{side}", "")
        if sticker:
            text += f" ({sticker})"
        if task_id and task_id in self.rows:
            text += f" → {self.rows[task_id].name}"
        else:
            text += " → unmapped, timer stopped"
        return text

    def stop_running(self) -> None:
        running = self.engine.running_task
        if running is None:
            return
        self.engine.stop(datetime.now())
        self.flush_now()
        if running in self.rows:
            self.rows[running].refresh()
        if self.mini is not None:
            self.mini.refresh()
        self._update_tray_state()
        self._update_window_title()

    def today_total(self) -> float:
        """All tasks' seconds today, including the running timer's live span."""
        today = date.today().isoformat()
        total = db.seconds_for_day_all_tasks(self.conn, today)
        running = self.engine.running_task
        if running is not None:
            total += self.engine.pending_seconds(running, today, datetime.now())
        return total

    def _update_target_bar(self) -> None:
        if self.target_hours <= 0:
            return
        total = self.today_total()
        target = self.target_hours * 3600
        percent = min(100, int(total / target * 100))
        self.target_bar.setValue(percent)
        if total >= target:
            self.target_bar.setFormat(
                f"🏆 {format_hms(total)} / {format_hms(target)} — HI-SCORE BEATEN!")
        else:
            self.target_bar.setFormat(
                f"🎯 {format_hms(total)} / {format_hms(target)} today (%p%)")

    def sync_now(self) -> dict | None:
        """Folder sync (if configured): import other machines, publish ours."""
        sync_dir = db.get_setting(self.conn, "sync_dir", "")
        if not sync_dir:
            return None
        path = Path(sync_dir).expanduser()
        if not path.is_dir():
            return None
        self.flush_now()
        stats = sync.sync(self.conn, path)
        if stats["entries_merged"] or stats["tasks_added"]:
            # another machine's history arrived — rebuild what's visible
            for task in db.list_tasks(self.conn):
                if task["task_id"] not in self.rows:
                    self._add_row(task["task_id"], task["name"], task["emoji"],
                                  bool(task["show_in_mini"]))
            for row in self.rows.values():
                row.refresh()
            if self.mini is not None:
                self.mini.rebuild()
                self.mini.refresh()
        return stats

    def _nudge_check(self, now: datetime) -> list[str]:
        """Once-per-day reminders. Returns which nudges fired (for tests)."""
        fired = []
        today = now.date()
        stop_at = _parse_hhmm(db.get_setting(self.conn, "nudge_stop_time",
                                             DEFAULT_NUDGE_STOP))
        if (stop_at and self.engine.running_task is not None
                and now.time() >= stop_at and self._nudged_stop != today):
            self._nudged_stop = today
            fired.append("stop")
            name = self.rows[self.engine.running_task].name \
                if self.engine.running_task in self.rows else "a task"
            self._notify("Still tracking?",
                         f"'{name}' is still running — end of day?")
        start_at = _parse_hhmm(db.get_setting(self.conn, "nudge_start_time",
                                              DEFAULT_NUDGE_START))
        if (start_at and self.engine.running_task is None
                and now.time() >= start_at and self._nudged_start != today
                and self.today_total() == 0):
            self._nudged_start = today
            fired.append("start")
            self._notify("Nothing tracked yet",
                         "The working day has started — insert coin?")
        return fired

    def _notify(self, title: str, message: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, message, app_icon())

    # --- system tray ------------------------------------------------------

    def _rebuild_tray_menu(self) -> None:
        if self.tray is None:
            return
        menu = QMenu()
        self.tray_task_actions = {}
        for task_id, row in self.rows.items():
            if icons.is_custom(row.emoji):
                action = QAction(icons.qicon(row.emoji), row.name, menu)
            else:
                label = f"{row.emoji} {row.name}" if row.emoji else row.name
                action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(self.engine.running_task == task_id)
            action.triggered.connect(
                lambda _checked=False, tid=task_id: self.toggle_task(tid))
            self.tray_task_actions[task_id] = action
            menu.addAction(action)
        if self.rows:
            menu.addSeparator()
        open_action = QAction("Open timeTrackerTool", menu)
        open_action.triggered.connect(self.present)
        mini_action = QAction("Mini mode", menu)
        mini_action.triggered.connect(self.enter_mini)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(open_action)
        menu.addAction(mini_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self._update_tray_state()

    def _update_tray_state(self) -> None:
        if self.tray is None:
            return
        running = self.engine.running_task
        for task_id, action in self.tray_task_actions.items():
            action.setChecked(task_id == running)
        if running and running in self.rows:
            name = self.rows[running].name
            self.tray.setToolTip(
                f"⏱ {name} — {format_hms(self.today_seconds(running))} today")
        else:
            self.tray.setToolTip("timeTrackerTool — nothing running")

    def _tray_activated(self, reason) -> None:
        # Windows: single-click the tray icon to bring the app up.
        # macOS ignores this (the menu opens instead), which is native behaviour.
        if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform != "darwin":
            self.present()

    def present(self) -> None:
        """Bring whichever window is current to the front (also called when a
        second instance is launched)."""
        if self.mini is not None and self.mini.isVisible():
            self.mini.raise_()
            self.mini.activateWindow()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # --- idle detection ---------------------------------------------------

    def _check_idle(self) -> None:
        span = self.idle_watcher.sample(
            datetime.now(), system_idle_seconds(),
            self.engine.running_task is not None,
        )
        if span is not None and self.engine.running_task is not None:
            self._prompt_idle(self.engine.running_task, span[0], span[1])

    def _prompt_idle(self, task_id: str, away_start: datetime,
                     away_end: datetime) -> None:
        minutes = int((away_end - away_start).total_seconds() // 60)
        name = self.rows[task_id].name if task_id in self.rows else task_id
        choice = QMessageBox.question(
            self, "Welcome back",
            f"You were away for ~{minutes} minutes while '{name}' was running.\n\n"
            "Keep that time, or discard the away gap?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        # Yes = keep. No = discard the away span from the logged totals.
        if choice == QMessageBox.StandardButton.No:
            self.discard_span(task_id, away_start, away_end)

    def discard_span(self, task_id: str, start: datetime, end: datetime) -> None:
        """Remove an away span from a task's stored totals (timer keeps
        running — only the gap is dropped)."""
        self.flush_now()  # make sure the span is on disk before deducting
        for entry_date, seconds in split_span_by_date(start, end):
            db.deduct_seconds(self.conn, task_id, entry_date, seconds)
        for row in self.rows.values():
            row.refresh()
        if self.mini is not None:
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
        self._update_window_title()
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
        self.banner.stop()
        if self.cube is not None:
            self.cube.stop()
        if self.tray is not None:
            self.tray.hide()
        self.engine.stop(datetime.now())
        self.flush_now()
        try:
            self.sync_now()  # publish final state to the sync folder
        except Exception:
            pass  # a broken sync folder must never block shutdown
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

    # Single-instance guard. QLockFile is the authority — it detects stale
    # locks from crashed/killed instances by PID, which a bare local socket
    # cannot. If a live instance holds the lock, poke it to the front
    # (best-effort) and exit instead of opening a second window on the DB.
    lock_dir = db.default_db_path().parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_dir / "timetracker.lock"))
    if not lock.tryLock(100):
        probe = QLocalSocket()
        probe.connectToServer(INSTANCE_SERVER)
        if probe.waitForConnected(200):
            probe.write(b"show")
            probe.flush()
            if probe.state() == QLocalSocket.LocalSocketState.ConnectedState:
                probe.waitForBytesWritten(200)
            probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(INSTANCE_SERVER)  # clear any stale socket file

    window = MainWindow()
    window._instance_lock = lock  # held for the app's lifetime

    server = QLocalServer()
    server.listen(INSTANCE_SERVER)

    def _on_second_instance() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.readAll()
            connection.disconnectFromServer()
        window.present()

    server.newConnection.connect(_on_second_instance)
    window._instance_server = server  # keep it alive for the app's lifetime

    # Safety net: flush even when quit arrives without a closeEvent
    # (e.g. Cmd-Q while in mini mode, where the main window is hidden)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
