"""Pixel-art sprites and helpers shared by the live banner widget and the
static asset generator (scripts/make_assets.py)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap

CRAB = [
    "..X.....X..",
    "...X...X...",
    "..XXXXXXX..",
    ".XX.XXX.XX.",
    "XXXXXXXXXXX",
    "X.XXXXXXX.X",
    "X.X.....X.X",
    "...XX.XX...",
]
SQUID = [
    "...XX...",
    "..XXXX..",
    ".XXXXXX.",
    "XX.XX.XX",
    "XXXXXXXX",
    "..X..X..",
    ".X.XX.X.",
    "X.X..X.X",
]
CANNON = [
    "....X....",
    "...XXX...",
    "...XXX...",
    ".XXXXXXX.",
    "XXXXXXXXX",
    "XXXXXXXXX",
]
SAUCER = [
    "......XXXX......",
    "....XXXXXXXX....",
    "..XXXXXXXXXXXX..",
    ".XX.XX.XX.XX.XX.",
    "XXXXXXXXXXXXXXXX",
    "...XX......XX...",
]
EXPLOSION = [
    "X..X.X..X",
    ".X..X..X.",
    "..XX.XX..",
    "XX..X..XX",
    "..XX.XX..",
    ".X..X..X.",
    "X..X.X..X",
]


def draw_sprite(p: QPainter, grid: list[str], x: float, y: float,
                px: float, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for row, line in enumerate(grid):
        for col, cell in enumerate(line):
            if cell == "X":
                p.drawRect(QRectF(x + col * px, y + row * px, px, px))


def sprite_width(grid: list[str], px: float) -> float:
    return len(grid[0]) * px


def pixel_text(text: str, color: QColor, pixel_size: int, scale: int) -> QPixmap:
    """Render text small without antialiasing, then nearest-neighbour upscale
    for a chunky arcade-bitmap look."""
    font = QFont()
    font.setFamilies(["Menlo", "Consolas", "Courier New"])
    font.setBold(True)
    font.setPixelSize(pixel_size)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    metrics = QFontMetrics(font)
    small = QPixmap(metrics.horizontalAdvance(text) + 2, metrics.height() + 2)
    small.fill(Qt.GlobalColor.transparent)
    painter = QPainter(small)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(1, metrics.ascent() + 1, text)
    painter.end()
    return small.scaled(
        small.width() * scale, small.height() * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
