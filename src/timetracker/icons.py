"""The task icon system — everything that isn't a literal emoji.

Two families, both rendered DPI-exact at whatever size is asked for:

- Coloured tiles: 16 kinds covering the IT working week, four colours
  each, drawn entirely with QPainter (no image files). Stored in the
  tasks.emoji column as "icon:<kind>-<colour>" tokens.
- The Library: the free Notion icon set (884 bundled SVGs, via
  files2notion.com — credited in the README) plus a few drawn in-house,
  tinted at render time. Stored as "notion:<name>" (auto: black/white
  follows the theme) or "notion:<name>:<colour>" for a fixed colour.

Anything else in the emoji column is treated as a literal emoji string.
"""

from __future__ import annotations

from functools import lru_cache

from importlib.resources import files

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

PREFIX = "icon:"
# The monochrome Notion icon library (free set via files2notion.com) —
# tokens are "notion:<name>" (auto: black/white follows the theme) or
# "notion:<name>:<colour>" for a fixed Notion-style colour.
NOTION_PREFIX = "notion:"

NOTION_COLOURS = {
    "auto": None,  # follow the theme: near-black on light, near-white on dark
    "gray": "#9ca3af",
    "brown": "#a47148",
    "orange": "#f97316",
    "yellow": "#d9a80b",
    "green": "#22c55e",
    "blue": "#3b82f6",
    "purple": "#a855f7",
    "pink": "#ec4899",
    "red": "#ef4444",
}

COLOURS = {
    "blue": "#3b82f6",
    "green": "#22c55e",
    "orange": "#f97316",
    "purple": "#a855f7",
}

KINDS = ("code", "docs", "project", "meeting", "call", "email",
         "support", "network", "security", "server", "terminal",
         "bug", "database", "cloud", "monitoring", "admin")

KIND_NAMES = {
    "code": "Coding",
    "docs": "Documentation",
    "project": "Project work",
    "meeting": "Meeting",
    "call": "Call",
    "email": "Email",
    "support": "Support / helpdesk",
    "network": "Networking",
    "security": "Security",
    "server": "Servers / infrastructure",
    "terminal": "Terminal / scripting",
    "bug": "Debugging",
    "database": "Database",
    "cloud": "Cloud",
    "monitoring": "Monitoring / dashboards",
    "admin": "Admin / config",
}

ICON_CHOICES = [f"{PREFIX}{kind}-{colour}" for kind in KINDS for colour in COLOURS]


def is_icon(token: str) -> bool:
    return token.startswith(PREFIX)


def is_notion(token: str) -> bool:
    return token.startswith(NOTION_PREFIX)


def is_custom(token: str) -> bool:
    """Any non-emoji icon token (coloured tile or Notion monochrome)."""
    return is_icon(token) or is_notion(token)


@lru_cache(maxsize=1)
def notion_names() -> tuple[str, ...]:
    """All bundled Notion-library icon names, sorted."""
    folder = files("timetracker") / "assets" / "notion_icons"
    return tuple(sorted(
        entry.name[:-4] for entry in folder.iterdir()
        if entry.name.endswith(".svg")))


def _dark_ui() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return False
    return app.palette().window().color().lightness() < 128


def parse(token: str) -> tuple[str, str]:
    """'icon:code-blue' -> ('code', 'blue'); unknown parts fall back safely."""
    body = token[len(PREFIX):]
    kind, _, colour = body.partition("-")
    if kind not in KINDS:
        kind = KINDS[0]
    if colour not in COLOURS:
        colour = next(iter(COLOURS))
    return kind, colour


def notion_parts(token: str) -> tuple[str, str | None]:
    """'notion:alien' -> ('alien', None); 'notion:alien:blue' -> colour set.
    Unknown colours degrade to auto rather than crashing."""
    body = token[len(NOTION_PREFIX):]
    name, _, colour = body.partition(":")
    if colour not in NOTION_COLOURS or NOTION_COLOURS[colour] is None:
        return name, None
    return name, colour


def label(token: str) -> str:
    if is_notion(token):
        name, colour = notion_parts(token)
        pretty = name.replace("-", " ").title()
        return f"{pretty} ({colour})" if colour else pretty
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


def _paint_support(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A life buoy: thick ring with four tile-coloured segment cuts
    w, h = r.width(), r.height()
    ring = QRectF(r.x() + 0.26 * w, r.y() + 0.26 * h, 0.48 * w, 0.48 * h)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.13))
    p.drawEllipse(ring)
    p.setPen(_pen(bg, w * 0.05))
    c = ring.center()
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        # Cut only across the ring band, not past it — otherwise it reads
        # as an X over a circle instead of a segmented buoy.
        p.drawLine(QPointF(c.x() + dx * 0.115 * w, c.y() + dy * 0.115 * h),
                   QPointF(c.x() + dx * 0.215 * w, c.y() + dy * 0.215 * h))


def _paint_network(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # Three linked nodes
    w, h = r.width(), r.height()
    top = QPointF(r.x() + 0.50 * w, r.y() + 0.30 * h)
    left = QPointF(r.x() + 0.30 * w, r.y() + 0.68 * h)
    right = QPointF(r.x() + 0.70 * w, r.y() + 0.68 * h)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.055))
    p.drawLine(top, left)
    p.drawLine(top, right)
    p.drawLine(left, right)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    for node in (top, left, right):
        p.drawEllipse(node, 0.10 * w, 0.10 * h)


def _paint_security(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A shield with a tick
    w, h = r.width(), r.height()
    path = QPainterPath()
    path.moveTo(r.x() + 0.50 * w, r.y() + 0.18 * h)
    path.lineTo(r.x() + 0.76 * w, r.y() + 0.28 * h)
    path.cubicTo(r.x() + 0.76 * w, r.y() + 0.58 * h,
                 r.x() + 0.66 * w, r.y() + 0.76 * h,
                 r.x() + 0.50 * w, r.y() + 0.84 * h)
    path.cubicTo(r.x() + 0.34 * w, r.y() + 0.76 * h,
                 r.x() + 0.24 * w, r.y() + 0.58 * h,
                 r.x() + 0.24 * w, r.y() + 0.28 * h)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(bg, w * 0.06))
    p.drawPolyline([QPointF(r.x() + 0.38 * w, r.y() + 0.50 * h),
                    QPointF(r.x() + 0.47 * w, r.y() + 0.60 * h),
                    QPointF(r.x() + 0.63 * w, r.y() + 0.38 * h)])


def _paint_server(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A rack: three slats, each with an LED
    w, h = r.width(), r.height()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(3):
        slat = QRectF(r.x() + 0.24 * w, r.y() + (0.24 + i * 0.20) * h,
                      0.52 * w, 0.15 * h)
        p.setBrush(fg)
        p.drawRoundedRect(slat, 0.03 * w, 0.03 * w)
        p.setBrush(bg)
        p.drawEllipse(QPointF(slat.right() - 0.07 * w, slat.center().y()),
                      0.030 * w, 0.030 * h)


def _paint_terminal(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A screen with a "> _" prompt
    w, h = r.width(), r.height()
    screen = QRectF(r.x() + 0.20 * w, r.y() + 0.24 * h, 0.60 * w, 0.52 * h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawRoundedRect(screen, 0.05 * w, 0.05 * w)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(bg, w * 0.06))
    p.drawPolyline([QPointF(r.x() + 0.30 * w, r.y() + 0.38 * h),
                    QPointF(r.x() + 0.40 * w, r.y() + 0.48 * h),
                    QPointF(r.x() + 0.30 * w, r.y() + 0.58 * h)])
    p.drawLine(QPointF(r.x() + 0.48 * w, r.y() + 0.62 * h),
               QPointF(r.x() + 0.62 * w, r.y() + 0.62 * h))


def _paint_bug(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    w, h = r.width(), r.height()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.045))
    body = QRectF(r.x() + 0.36 * w, r.y() + 0.36 * h, 0.28 * w, 0.40 * h)
    for side in (-1, 1):
        x_edge = body.center().x() + side * body.width() / 2
        for i, y_frac in enumerate((0.44, 0.56, 0.68)):
            p.drawLine(QPointF(x_edge, r.y() + y_frac * h),
                       QPointF(x_edge + side * 0.11 * w,
                               r.y() + (y_frac + (i - 1) * 0.05) * h))
        p.drawLine(QPointF(body.center().x() + side * 0.06 * w, body.top()),
                   QPointF(body.center().x() + side * 0.13 * w,
                           body.top() - 0.09 * h))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawEllipse(body)
    p.setPen(_pen(bg, w * 0.035))
    p.drawLine(QPointF(body.center().x(), body.top() + 0.06 * h),
               QPointF(body.center().x(), body.bottom() - 0.06 * h))


def _paint_database(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # The classic cylinder
    w, h = r.width(), r.height()
    x, top, width = r.x() + 0.28 * w, r.y() + 0.22 * h, 0.44 * w
    cap = 0.14 * h
    body_h = 0.48 * h
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawRect(QRectF(x, top + cap / 2, width, body_h))
    p.drawEllipse(QRectF(x, top + body_h, width, cap))
    p.drawEllipse(QRectF(x, top, width, cap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(bg, w * 0.035))
    for frac in (0.36, 0.54):
        p.drawArc(QRectF(x, top + frac * h, width, cap), 180 * 16, 180 * 16)


def _paint_cloud(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    w, h = r.width(), r.height()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawEllipse(QRectF(r.x() + 0.24 * w, r.y() + 0.42 * h, 0.26 * w, 0.26 * h))
    p.drawEllipse(QRectF(r.x() + 0.36 * w, r.y() + 0.30 * h, 0.32 * w, 0.32 * h))
    p.drawEllipse(QRectF(r.x() + 0.52 * w, r.y() + 0.42 * h, 0.26 * w, 0.26 * h))
    p.drawRect(QRectF(r.x() + 0.32 * w, r.y() + 0.52 * h, 0.38 * w, 0.16 * h))


def _paint_monitoring(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # Axes with a rising line and an end dot
    w, h = r.width(), r.height()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(fg, w * 0.05))
    p.drawPolyline([QPointF(r.x() + 0.26 * w, r.y() + 0.26 * h),
                    QPointF(r.x() + 0.26 * w, r.y() + 0.74 * h),
                    QPointF(r.x() + 0.78 * w, r.y() + 0.74 * h)])
    p.setPen(_pen(fg, w * 0.06))
    p.drawPolyline([QPointF(r.x() + 0.32 * w, r.y() + 0.62 * h),
                    QPointF(r.x() + 0.46 * w, r.y() + 0.50 * h),
                    QPointF(r.x() + 0.56 * w, r.y() + 0.58 * h),
                    QPointF(r.x() + 0.72 * w, r.y() + 0.34 * h)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    p.drawEllipse(QPointF(r.x() + 0.72 * w, r.y() + 0.34 * h),
                  0.045 * w, 0.045 * h)


def _paint_admin(p: QPainter, r: QRectF, fg: QColor, bg: QColor) -> None:
    # A gear: eight teeth, ring, hollow centre
    w = r.width()
    c = r.center()
    p.save()
    p.translate(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fg)
    for _ in range(8):
        p.drawRect(QRectF(-0.055 * w, -0.34 * w, 0.11 * w, 0.12 * w))
        p.rotate(45)
    p.drawEllipse(QPointF(0, 0), 0.26 * w, 0.26 * w)
    p.setBrush(bg)
    p.drawEllipse(QPointF(0, 0), 0.11 * w, 0.11 * w)
    p.restore()


_PAINTERS = {
    "code": _paint_code,
    "docs": _paint_docs,
    "project": _paint_project,
    "meeting": _paint_meeting,
    "call": _paint_call,
    "email": _paint_email,
    "support": _paint_support,
    "network": _paint_network,
    "security": _paint_security,
    "server": _paint_server,
    "terminal": _paint_terminal,
    "bug": _paint_bug,
    "database": _paint_database,
    "cloud": _paint_cloud,
    "monitoring": _paint_monitoring,
    "admin": _paint_admin,
}


def pixmap(token: str, size: int, dpr: float = 1.0) -> QPixmap:
    """Render an icon token at the given logical size (cached per size).

    Everything is vector-drawn, so always render at the exact size needed —
    never scale a pixmap afterwards, that's what looks blocky next to
    text-rendered emoji. Pass the target widget's devicePixelRatioF() so
    high-DPI displays get a full-resolution render too. Notion-library
    icons with no fixed colour are tinted to the current theme (white on
    dark, black on light), so the cache key includes the tint."""
    dark = False
    if is_notion(token) and notion_parts(token)[1] is None:
        dark = _dark_ui()
    return _render(token, size, dpr, dark)


@lru_cache(maxsize=2048)
def _render(token: str, size: int, dpr: float, dark: bool) -> QPixmap:
    if is_notion(token):
        name, colour = notion_parts(token)
        return _render_notion(name, size, dpr, dark, colour)
    kind, colour = parse(token)
    base = QColor(COLOURS[colour])
    px = max(1, int(round(size * dpr)))
    canvas = QPixmap(px, px)
    canvas.fill(Qt.GlobalColor.transparent)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, px, px).adjusted(
        px * 0.04, px * 0.04, -px * 0.04, -px * 0.04)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, base.lighter(114))
    gradient.setColorAt(1.0, base.darker(112))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(rect, px * 0.22, px * 0.22)
    _PAINTERS[kind](p, rect, QColor("white"), base)
    p.end()
    canvas.setDevicePixelRatio(dpr)
    return canvas


def _render_notion(name: str, size: int, dpr: float, dark: bool,
                   colour: str | None = None) -> QPixmap:
    """Render a Notion-library SVG tinted to a single colour: a fixed
    Notion-style colour if one was picked, otherwise near-white on a dark
    theme / near-black on a light one."""
    from PySide6.QtSvg import QSvgRenderer

    try:
        data = (files("timetracker") / "assets" / "notion_icons"
                / f"{name}.svg").read_bytes()
    except (FileNotFoundError, OSError):
        data = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>'
    if colour:
        tint = QColor(NOTION_COLOURS[colour])
    else:
        tint = QColor("#f2f2f2" if dark else "#161616")
    px = max(1, int(round(size * dpr)))
    canvas = QPixmap(px, px)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(data).render(p, QRectF(0, 0, px, px))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(0, 0, px, px, tint)
    p.end()
    canvas.setDevicePixelRatio(dpr)
    return canvas


def qicon(token: str) -> QIcon:
    """Multi-resolution QIcon so menus, tabs, and combos all pick a render
    made for their exact display size instead of scaling one bitmap."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128):
        icon.addPixmap(pixmap(token, size))
    return icon
