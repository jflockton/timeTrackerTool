"""Regenerate the app's image assets (all drawn in code — no source images).

- src/timetracker/assets/icon.png    (1024px stopwatch app icon)
- src/timetracker/assets/banner.png  (1200x300 boss-cracking-whip-at-sundial)

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


def make_banner() -> None:
    """The boss cracking a whip at a sweating sundial. Art."""
    w, h = 1200, 300
    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Sky
    sky = QLinearGradient(0, 0, 0, h)
    sky.setColorAt(0.0, QColor("#1e3a8a"))
    sky.setColorAt(1.0, QColor("#3b82f6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(sky))
    p.drawRoundedRect(QRectF(0, 0, w, h), 24, 24)

    # Sun (a sundial needs one) — top right, with rays
    p.setBrush(QColor("#facc15"))
    sun = QPointF(1100, 60)
    p.drawEllipse(sun, 40, 40)
    p.setPen(QPen(QColor("#facc15"), 8, c=Qt.PenCapStyle.RoundCap))
    for i in range(8):
        rad = math.radians(i * 45)
        p.drawLine(
            QPointF(sun.x() + 52 * math.cos(rad), sun.y() + 52 * math.sin(rad)),
            QPointF(sun.x() + 74 * math.cos(rad), sun.y() + 74 * math.sin(rad)),
        )

    # Ground
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#166534"))
    p.drawRoundedRect(QRectF(0, 252, w, 48), 24, 24)
    p.drawRect(QRectF(0, 252, w, 24))  # square off the top edge of the ground

    # --- Sundial (right) -------------------------------------------------
    p.setBrush(QColor("#9ca3af"))  # stone pedestal
    p.drawPolygon(QPolygonF([QPointF(870, 260), QPointF(980, 260),
                             QPointF(962, 168), QPointF(888, 168)]))
    p.setBrush(QColor("#d1d5db"))  # dial plate
    p.drawEllipse(QPointF(925, 160), 95, 34)
    p.setPen(QPen(QColor("#4b5563"), 5, c=Qt.PenCapStyle.RoundCap))
    for i in range(12):  # hour marks
        rad = math.radians(i * 30)
        p.drawLine(
            QPointF(925 + 70 * math.cos(rad), 160 + 24 * math.sin(rad)),
            QPointF(925 + 88 * math.cos(rad), 160 + 30 * math.sin(rad)),
        )
    p.setPen(Qt.PenStyle.NoPen)  # gnomon
    p.setBrush(QColor("#374151"))
    p.drawPolygon(QPolygonF([QPointF(925, 162), QPointF(925, 92), QPointF(880, 158)]))

    # Sweat drops flying off the terrified sundial
    p.setBrush(QColor("#7dd3fc"))
    for dx, dy, r in [(-130, -55, 9), (-105, -90, 7), (115, -70, 8), (95, -35, 6)]:
        drop = QPointF(925 + dx, 160 + dy)
        p.drawEllipse(drop, r, r * 1.3)

    # --- The Boss (left) -------------------------------------------------
    # Legs
    p.setBrush(QColor("#111827"))
    p.drawRect(QRectF(232, 210, 16, 50))
    p.drawRect(QRectF(258, 210, 16, 50))
    # Suit body
    p.setBrush(QColor("#1f2937"))
    p.drawRoundedRect(QRectF(218, 130, 70, 90), 16, 16)
    # Tie
    p.setBrush(QColor("#dc2626"))
    p.drawPolygon(QPolygonF([QPointF(253, 135), QPointF(263, 135),
                             QPointF(258, 185), QPointF(253, 175)]))
    # Head
    p.setBrush(QColor("#fcd9b8"))
    p.drawEllipse(QPointF(253, 95), 32, 32)
    # Angry eyebrows + eyes
    p.setPen(QPen(QColor("#111827"), 5, c=Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(238, 84), QPointF(252, 90))
    p.drawLine(QPointF(272, 84), QPointF(258, 90))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#111827"))
    p.drawEllipse(QPointF(245, 96), 4, 4)
    p.drawEllipse(QPointF(263, 96), 4, 4)
    # Shouting mouth
    p.drawEllipse(QPointF(254, 112), 9, 6)
    # Raised arm holding the whip handle
    p.setPen(QPen(QColor("#1f2937"), 16, c=Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(282, 145), QPointF(330, 92))
    p.setPen(QPen(QColor("#92400e"), 12, c=Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(322, 100), QPointF(352, 68))  # handle

    # The whip: long curve from handle toward the sundial
    whip = QPainterPath(QPointF(352, 68))
    whip.cubicTo(QPointF(520, -10), QPointF(680, 30), QPointF(760, 90))
    whip.cubicTo(QPointF(800, 120), QPointF(818, 118), QPointF(834, 104))
    p.setPen(QPen(QColor("#b45309"), 7, c=Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(whip)

    # CRACK! flash at the whip tip
    p.setPen(QPen(QColor("#fde047"), 6, c=Qt.PenCapStyle.RoundCap))
    tip = QPointF(838, 100)
    for angle_deg in (-80, -30, 20, 60, 110):
        rad = math.radians(angle_deg)
        p.drawLine(
            QPointF(tip.x() + 12 * math.cos(rad), tip.y() + 12 * math.sin(rad)),
            QPointF(tip.x() + 34 * math.cos(rad), tip.y() + 34 * math.sin(rad)),
        )

    # Speech bubble
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    bubble = QRectF(60, 24, 210, 62)
    p.drawRoundedRect(bubble, 18, 18)
    p.drawPolygon(QPolygonF([QPointF(200, 82), QPointF(232, 78), QPointF(238, 100)]))
    p.setPen(QColor("#1e3a8a"))
    font = QFont()
    font.setPixelSize(30)
    font.setBold(True)
    p.setFont(font)
    p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, "TICK TOCK!!")

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
