"""Regenerate src/timetracker/assets/icon.png (1024px stopwatch icon).

Run with: poetry run python scripts/make_icon.py
Pure QPainter drawing — no external image assets needed.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QLinearGradient, QPainter, QPen, QPixmap

SIZE = 1024
OUT = Path(__file__).resolve().parents[1] / "src" / "timetracker" / "assets" / "icon.png"


def main() -> None:
    QGuiApplication(sys.argv)
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded-square background, deep blue gradient (macOS-style tile)
    gradient = QLinearGradient(0, 0, 0, SIZE)
    gradient.setColorAt(0.0, QColor("#3b82f6"))
    gradient.setColorAt(1.0, QColor("#1e3a8a"))
    p.setBrush(QBrush(gradient))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(64, 64, SIZE - 128, SIZE - 128), 200, 200)

    cx, cy, radius = SIZE / 2, SIZE / 2 + 40, 300.0

    # Stopwatch crown button and side lugs
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

    # Watch face: white ring with blue inner face
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    p.setBrush(QColor("#eff6ff"))
    p.drawEllipse(QPointF(cx, cy), radius - 56, radius - 56)

    # Tick marks at 12/3/6/9
    tick_pen = QPen(QColor("#1e3a8a"), 26, c=Qt.PenCapStyle.RoundCap)
    p.setPen(tick_pen)
    for i in range(4):
        rad = math.radians(i * 90 - 90)
        inner, outer = radius - 130, radius - 84
        p.drawLine(
            QPointF(cx + inner * math.cos(rad), cy + inner * math.sin(rad)),
            QPointF(cx + outer * math.cos(rad), cy + outer * math.sin(rad)),
        )

    # Hand pointing to ~1 o'clock, orange, with center dot
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(OUT), "PNG")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
