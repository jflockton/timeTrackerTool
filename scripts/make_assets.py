"""Regenerate the app's image assets (all drawn in code — no source images).

- src/timetracker/assets/icon.png    (1024px stopwatch app icon)
- src/timetracker/assets/banner.png  (1200x300 retro arcade title screen)

Run with: poetry run python scripts/make_assets.py
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

ASSETS = Path(__file__).resolve().parents[1] / "src" / "timetracker" / "assets"


def make_icon() -> None:
    size = 1024
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0.0, QColor("#3b82f6"))
    gradient.setColorAt(1.0, QColor("#1e3a8a"))
    p.setBrush(QBrush(gradient))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(64, 64, size - 128, size - 128), 200, 200)

    cx, cy, radius = size / 2, size / 2 + 40, 300.0

    p.setBrush(QColor("white"))
    p.drawRoundedRect(QRectF(cx - 52, cy - radius - 120, 104, 110), 30, 30)
    for angle_deg in (-45, 45):
        rad = math.radians(angle_deg - 90)
        lx = cx + (radius + 40) * math.cos(rad)
        ly = cy + (radius + 40) * math.sin(rad)
        p.save()
        p.translate(lx, ly)
        p.rotate(angle_deg)
        p.drawRoundedRect(QRectF(-38, -50, 76, 70), 22, 22)
        p.restore()

    p.drawEllipse(QPointF(cx, cy), radius, radius)
    p.setBrush(QColor("#eff6ff"))
    p.drawEllipse(QPointF(cx, cy), radius - 56, radius - 56)

    p.setPen(QPen(QColor("#1e3a8a"), 26, c=Qt.PenCapStyle.RoundCap))
    for i in range(4):
        rad = math.radians(i * 90 - 90)
        inner, outer = radius - 130, radius - 84
        p.drawLine(
            QPointF(cx + inner * math.cos(rad), cy + inner * math.sin(rad)),
            QPointF(cx + outer * math.cos(rad), cy + outer * math.sin(rad)),
        )

    hand_rad = math.radians(-60)
    p.setPen(QPen(QColor("#f97316"), 44, c=Qt.PenCapStyle.RoundCap))
    p.drawLine(
        QPointF(cx, cy),
        QPointF(cx + (radius - 140) * math.cos(hand_rad), cy + (radius - 140) * math.sin(hand_rad)),
    )
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1e3a8a"))
    p.drawEllipse(QPointF(cx, cy), 40, 40)

    p.end()
    pixmap.save(str(ASSETS / "icon.png"), "PNG")


# Pixel-art sprites, invader-style ('X' = filled cell)
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

STARS = [
    (45, 120), (120, 210), (210, 20), (300, 250), (330, 90), (420, 30),
    (500, 260), (560, 55), (640, 20), (700, 250), (760, 65), (840, 25),
    (900, 240), (955, 105), (1010, 20), (1070, 230), (1130, 130), (1170, 40),
    (85, 265), (255, 150), (1105, 275), (620, 205), (390, 160), (815, 180),
]


def _draw_sprite(p: QPainter, grid: list[str], x: float, y: float,
                 px: float, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for row, line in enumerate(grid):
        for col, cell in enumerate(line):
            if cell == "X":
                p.drawRect(QRectF(x + col * px, y + row * px, px, px))


def _pixel_text(text: str, color: QColor, pixel_size: int, scale: int) -> QPixmap:
    """Render text small without antialiasing, then nearest-neighbour upscale
    for a chunky arcade-bitmap look."""
    font = QFont("Menlo")
    font.setBold(True)
    font.setPixelSize(pixel_size)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    from PySide6.QtGui import QFontMetrics

    metrics = QFontMetrics(font)
    small = QPixmap(metrics.horizontalAdvance(text) + 2, metrics.height() + 2)
    small.fill(Qt.GlobalColor.transparent)
    sp = QPainter(small)
    sp.setFont(font)
    sp.setPen(color)
    sp.drawText(1, metrics.ascent() + 1, text)
    sp.end()
    return small.scaled(
        small.width() * scale, small.height() * scale,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def make_banner() -> None:
    """80's arcade title screen: pixel title, invaders, scanlines."""
    w, h = 1200, 300
    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)

    frame = QPainterPath()
    frame.addRoundedRect(QRectF(0, 0, w, h), 24, 24)
    p.setClipPath(frame)

    # CRT-black background with a faint blue glow at the bottom
    bg = QLinearGradient(0, 0, 0, h)
    bg.setColorAt(0.0, QColor("#050510"))
    bg.setColorAt(1.0, QColor("#0b1035"))
    p.fillPath(frame, QBrush(bg))

    # Starfield
    for x, y in STARS:
        shade = 200 if (x + y) % 3 else 130
        p.fillRect(QRectF(x, y, 3, 3), QColor(shade, shade, shade + 30))

    # Score line, arcade-style
    one_up = _pixel_text("1UP  0:00:00", QColor("#ffffff"), 10, 2)
    hi = _pixel_text("HI-SCORE  8:00:00", QColor("#ef4444"), 10, 2)
    p.drawPixmap(36, 10, one_up)
    p.drawPixmap(w - hi.width() - 36, 10, hi)

    # Invaders bouncing around the title
    _draw_sprite(p, CRAB, 80, 60, 5, QColor("#4ade80"))
    _draw_sprite(p, SQUID, 195, 75, 5, QColor("#22d3ee"))
    _draw_sprite(p, CRAB, 1055, 62, 5, QColor("#f472b6"))
    _draw_sprite(p, SQUID, 955, 80, 5, QColor("#4ade80"))
    _draw_sprite(p, SQUID, 62, 190, 5, QColor("#fb923c"))
    _draw_sprite(p, CRAB, 1075, 195, 4, QColor("#22d3ee"))
    _draw_sprite(p, SQUID, 900, 52, 4, QColor("#a78bfa"))

    # Title: yellow with a red drop-shadow, chunky pixels
    shadow = _pixel_text("TIME TRACKER", QColor("#dc2626"), 20, 6)
    title = _pixel_text("TIME TRACKER", QColor("#facc15"), 20, 6)
    tx = (w - title.width()) // 2
    p.drawPixmap(tx + 8, 88, shadow)
    p.drawPixmap(tx, 80, title)

    # Blinking-style prompt
    prompt = _pixel_text("INSERT COIN TO START", QColor("#22d3ee"), 10, 3)
    p.drawPixmap((w - prompt.width()) // 2, 226, prompt)

    # Player cannon taking a shot at that purple squid
    _draw_sprite(p, CANNON, 895, 245, 5, QColor("#4ade80"))
    p.fillRect(QRectF(915, 100, 4, 140), QColor("#facc15"))

    # CRT scanlines over everything
    for y in range(0, h, 6):
        p.fillRect(QRectF(0, y, w, 2), QColor(0, 0, 0, 70))

    p.end()
    pixmap.save(str(ASSETS / "banner.png"), "PNG")


def main() -> None:
    QGuiApplication(sys.argv)
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_icon()
    make_banner()
    print(f"wrote {ASSETS / 'icon.png'}")
    print(f"wrote {ASSETS / 'banner.png'}")


if __name__ == "__main__":
    main()
