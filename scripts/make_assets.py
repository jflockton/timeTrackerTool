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


# Seven-segment display: which segments light up per digit.
# Segments: A top, B top-right, C bottom-right, D bottom, E bottom-left,
# F top-left, G middle.
SEGMENTS = {
    "0": "ABCDEF", "1": "BC", "2": "ABGED", "3": "ABGCD", "4": "FGBC",
    "5": "AFGCD", "6": "AFGECD", "7": "ABC", "8": "ABCDEFG", "9": "ABFGCD",
}


def _seg_h(cx: float, cy: float, length: float, t: float) -> QPolygonF:
    return QPolygonF([
        QPointF(cx - length / 2, cy), QPointF(cx - length / 2 + t / 2, cy - t / 2),
        QPointF(cx + length / 2 - t / 2, cy - t / 2), QPointF(cx + length / 2, cy),
        QPointF(cx + length / 2 - t / 2, cy + t / 2), QPointF(cx - length / 2 + t / 2, cy + t / 2),
    ])


def _seg_v(cx: float, cy: float, length: float, t: float) -> QPolygonF:
    return QPolygonF([
        QPointF(cx, cy - length / 2), QPointF(cx + t / 2, cy - length / 2 + t / 2),
        QPointF(cx + t / 2, cy + length / 2 - t / 2), QPointF(cx, cy + length / 2),
        QPointF(cx - t / 2, cy + length / 2 - t / 2), QPointF(cx - t / 2, cy - length / 2 + t / 2),
    ])


def _draw_digit(p: QPainter, digit: str, x: float, y: float,
                w: float, h: float, t: float, on: QColor, off: QColor) -> None:
    gap = t * 0.18
    lv = h / 2 - t
    polys = {
        "A": _seg_h(x + w / 2, y + t / 2, w - t, t),
        "G": _seg_h(x + w / 2, y + h / 2, w - t, t),
        "D": _seg_h(x + w / 2, y + h - t / 2, w - t, t),
        "F": _seg_v(x + t / 2, y + h / 4 + gap, lv, t),
        "B": _seg_v(x + w - t / 2, y + h / 4 + gap, lv, t),
        "E": _seg_v(x + t / 2, y + 3 * h / 4 - gap, lv, t),
        "C": _seg_v(x + w - t / 2, y + 3 * h / 4 - gap, lv, t),
    }
    lit = SEGMENTS[digit]
    for name, poly in polys.items():
        if name in lit:
            p.setPen(QPen(QColor(on.red(), on.green(), on.blue(), 70), t * 0.45))
            p.setBrush(on)  # translucent fat pen = LED glow halo
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(off)
        p.drawPolygon(poly)


def make_icon() -> None:
    """A nerdy LCD clock reading 13:37 (leet o'clock) on a dark tile."""
    size = 1024
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    tile = QPainterPath()
    tile.addRoundedRect(QRectF(64, 64, size - 128, size - 128), 200, 200)
    p.setClipPath(tile)

    bg = QLinearGradient(0, 0, 0, size)
    bg.setColorAt(0.0, QColor("#10141b"))
    bg.setColorAt(1.0, QColor("#070b08"))
    p.fillPath(tile, QBrush(bg))

    # Recessed LCD screen window
    screen = QRectF(120, 300, size - 240, 424)
    p.setPen(QPen(QColor("#1f2a22"), 14))
    p.setBrush(QColor("#060a07"))
    p.drawRoundedRect(screen, 60, 60)

    on = QColor("#39ff5a")
    off = QColor(57, 255, 90, 26)

    # 13:37 — slight italic shear like a real LCD
    digit_w, digit_h, thick, gap = 138, 330, 36, 30
    colon_w = 54
    total = 4 * digit_w + 3 * gap + colon_w + gap
    p.save()
    p.translate((size - total) / 2 + 20, (size - digit_h) / 2 + 60)
    p.shear(-0.08, 0)
    x = 0.0
    for ch in "13:37":
        if ch == ":":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(on)
            for cy in (digit_h * 0.30, digit_h * 0.70):
                p.drawRoundedRect(QRectF(x, cy - colon_w / 2 + 10, colon_w * 0.8, colon_w * 0.8), 10, 10)
            x += colon_w + gap
        else:
            _draw_digit(p, ch, x, 0, digit_w, digit_h, thick, on, off)
            x += digit_w + gap
    p.restore()

    # Label above the screen, like a proper gadget
    label = _pixel_text("TIME TRACKER", QColor("#39ff5a"), 10, 5)
    p.drawPixmap(int((size - label.width()) / 2), 170, label)

    # Faint CRT scanlines across the tile
    for y in range(64, size - 64, 16):
        p.fillRect(QRectF(64, y, size - 128, 5), QColor(0, 0, 0, 60))

    p.end()
    pixmap.save(str(ASSETS / "icon.png"), "PNG")
    # Windows packaging icon (PyInstaller --icon). 256px is the max ICO size.
    pixmap.scaled(256, 256, Qt.AspectRatioMode.IgnoreAspectRatio,
                  Qt.TransformationMode.SmoothTransformation).save(
        str(ASSETS / "icon.ico"), "ICO")


from timetracker.sprites import (  # noqa: E402 (path set by poetry env)
    CANNON,
    CRAB,
    SQUID,
    draw_sprite,
    pixel_text,
)

STARS = [
    (45, 120), (120, 210), (210, 20), (300, 250), (330, 90), (420, 30),
    (500, 260), (560, 55), (640, 20), (700, 250), (760, 65), (840, 25),
    (900, 240), (955, 105), (1010, 20), (1070, 230), (1130, 130), (1170, 40),
    (85, 265), (255, 150), (1105, 275), (620, 205), (390, 160), (815, 180),
]


_draw_sprite = draw_sprite
_pixel_text = pixel_text


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
