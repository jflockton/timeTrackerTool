"""Code-drawn task icons — a built-in alternative to emoji for task buttons.

Six kinds (code, docs, project, meeting, call, email) in four colours each,
all drawn with QPainter at whatever size is asked for — no image files, in
keeping with the rest of the artwork.

An icon choice is stored in the tasks.emoji column as an "icon:<kind>-<colour>"
token; anything else in that column is treated as a literal emoji string.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

PREFIX = "icon:"

COLOURS = {
    "blue": "#3b82f6",
    "green": "#22c55e",
    "orange": "#f97316",
    "purple": "#a855f7",
}

KINDS = ("code", "docs", "project", "meeting", "call", "email")

KIND_NAMES = {
    "code": "Coding",
    "docs": "Documentation",
    "project": "Project work",
    "meeting": "Meeting",
    "call": "Call",
    "email": "Email",
}

ICON_CHOICES = [f"{PREFIX}{kind}-{colour}" for kind in KINDS for colour in COLOURS]


def is_icon(token: str) -> bool:
    return token.startswith(PREFIX)


def parse(token: str) -> tuple[str, str]:
    """'icon:code-blue' -> ('code', 'blue'); unknown parts fall back safely."""
    body = token[len(PREFIX):]
    kind, _, colour = body.partition("-")
    if kind not in KINDS:
        kind = KINDS[0]
    if colour not in COLOURS:
        colour = next(iter(COLOURS))
    return kind, colour


def label(token: str) -> str:
    kind, colour = parse(token)
    return f"{KIND_NAMES[kind]} ({colour})"


def _pen(colour, width: float) -> QPen:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _paint_code(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    p.setPen(_pen(fg, r.width() * 0.08))
    p.setBrush(Qt.BrushStyle.NoBrush)
    w, h = r.width(), r.height()

    def pt(fx: float, fy: float) -> QPointF:
        return QPointF(r.x() + fx * w, r.y() + fy * h)

    p.drawPolyline([pt(0.36, 0.34), pt(0.18, 0.50), pt(0.36, 0.66)])
    p.drawPolyline([pt(0.64, 0.34), pt(0.82, 0.50), pt(0.64, 0.66)])
    p.drawLine(pt(0.56, 0.28), pt(0.44, 0.72))


def _paint_docs(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    w, h = r.width(), r.height()
    page = QRectF(r.x() + 0.28 * w, r.y() + 0.18 * h, 0.44 * w, 0.64 * h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawRoundedRect(page, 0.06 * w, 0.06 * w)
    p.setBrush(bg)
    for i in range(3):
        line = QRectF(page.x() + 0.08 * w, page.y() + (0.12 + i * 0.16) * h,
                      page.width() - 0.16 * w, 0.05 * h)
        p.drawRoundedRect(line, 0.02 * w, 0.02 * w)


def _paint_project(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # Kanban columns of differing fill — work in flight
    w, h = r.width(), r.height()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    for i, bar_h in enumerate((0.58, 0.42, 0.30)):
        bar = QRectF(r.x() + (0.24 + i * 0.20) * w, r.y() + 0.21 * h,
                     0.13 * w, bar_h * h)
        p.drawRoundedRect(bar, 0.04 * w, 0.04 * w)


def _paint_meeting(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    w, h = r.width(), r.height()
    # Back person first; the front one gets a tile-coloured outline so the
    # two silhouettes read separately at small sizes.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawEllipse(QRectF(r.x() + 0.52 * w, r.y() + 0.24 * h, 0.20 * w, 0.20 * h))
    p.drawEllipse(QRectF(r.x() + 0.44 * w, r.y() + 0.46 * h, 0.36 * w, 0.34 * h))
    p.setPen(_pen(bg, w * 0.035))
    p.drawEllipse(QRectF(r.x() + 0.26 * w, r.y() + 0.28 * h, 0.22 * w, 0.22 * h))
    p.drawEllipse(QRectF(r.x() + 0.16 * w, r.y() + 0.52 * h, 0.42 * w, 0.38 * h))


def _paint_call(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A headset: band, two ear pads, mic boom — the Teams-call special
    w, h = r.width(), r.height()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.08))
    band = QRectF(r.x() + 0.24 * w, r.y() + 0.22 * h, 0.52 * w, 0.52 * h)
    p.drawArc(band, 0 * 16, 180 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawRoundedRect(QRectF(r.x() + 0.20 * w, r.y() + 0.44 * h, 0.12 * w, 0.22 * h),
                      0.03 * w, 0.03 * w)
    p.drawRoundedRect(QRectF(r.x() + 0.68 * w, r.y() + 0.44 * h, 0.12 * w, 0.22 * h),
                      0.03 * w, 0.03 * w)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.06))
    mic = QRectF(r.x() + 0.52 * w, r.y() + 0.58 * h, 0.22 * w, 0.24 * h)
    p.drawArc(mic, 200 * 16, 130 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawEllipse(QRectF(r.x() + 0.47 * w, r.y() + 0.76 * h, 0.09 * w, 0.09 * h))


def _paint_email(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    w, h = r.width(), r.height()
    envelope = QRectF(r.x() + 0.20 * w, r.y() + 0.28 * h, 0.60 * w, 0.44 * h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawRoundedRect(envelope, 0.05 * w, 0.05 * w)
    p.setPen(_pen(bg, w * 0.045))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([
        QPointF(envelope.x() + 0.02 * w, envelope.y() + 0.02 * h),
        QPointF(r.x() + 0.50 * w, r.y() + 0.52 * h),
        QPointF(envelope.right() - 0.02 * w, envelope.y() + 0.02 * h),
    ])


_PAINTERS = {
    "code": _paint_code,
    "docs": _paint_docs,
    "project": _paint_project,
    "meeting": _paint_meeting,
    "call": _paint_call,
    "email": _paint_email,
}


@lru_cache(maxsize=256)
def pixmap(token: str, size: int) -> QPixmap:
    """Render an icon token at the given pixel size (cached per size)."""
    kind, colour = parse(token)
    base = QColor(COLOURS[colour])
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, size, size).adjusted(
        size * 0.04, size * 0.04, -size * 0.04, -size * 0.04)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, base.lighter(114))
    gradient.setColorAt(1.0, base.darker(112))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(rect, size * 0.22, size * 0.22)
    _PAINTERS[kind](p, rect, QColor("white"), base)
    p.end()
    return canvas


def qicon(token: str) -> QIcon:
    return QIcon(pixmap(token, 64))
