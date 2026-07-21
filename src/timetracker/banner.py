"""The animated arcade banner.

Invaders march side to side; INSERT COIN blinks; the 1UP counter shows
today's real tracked time. At random intervals a saucer blasts across and
shoots every invader it passes — each explodes — then the formation
respawns a few seconds later. All state stepping lives in ``_step`` (frame
counters + injectable RNG) so tests can drive it deterministically.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from .sprites import (
    CRAB,
    EXPLOSION,
    SAUCER,
    SQUID,
    draw_sprite,
    pixel_text,
    sprite_width,
)

BANNER_H = 104
FPS_MS = 50                     # 20 fps
MARCH_EVERY = 8                 # frames between formation shuffles
MARCH_STEP = 3
MARCH_RANGE = 18
BLINK_EVERY = 16
SAUCER_SPEED = 6
SAUCER_MIN_GAP = 300            # frames (15 s) between saucer runs…
SAUCER_MAX_GAP = 900            # …and at most 45 s
EXPLOSION_FRAMES = 12
RESPAWN_AFTER = 70              # ~3.5 s after the saucer leaves

INVADER_COLORS = ["#4ade80", "#22d3ee", "#f472b6", "#fb923c", "#a78bfa", "#4ade80"]
# (x fraction of width, y px, sprite) — scattered like the title screen
INVADER_SLOTS = [
    (0.06, 40, CRAB), (0.17, 56, SQUID), (0.30, 34, SQUID),
    (0.68, 34, SQUID), (0.80, 54, SQUID), (0.91, 38, CRAB),
]


@dataclass
class Invader:
    x_frac: float
    y: float
    grid: list
    color: str
    state: str = "alive"        # alive | exploding | dead
    frame: int = 0              # explosion progress


class BannerWidget(QWidget):
    def __init__(self, rng: random.Random | None = None) -> None:
        super().__init__()
        self.setFixedHeight(BANNER_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rng = rng or random.Random()

        self.frame = 0
        self.march_offset = 0
        self.march_dir = 1
        self.blink_on = True
        self.invaders = [Invader(x, y, grid, INVADER_COLORS[i % len(INVADER_COLORS)])
                         for i, (x, y, grid) in enumerate(INVADER_SLOTS)]
        self.saucer_x: float | None = None
        self.lasers: list[tuple[float, float, int]] = []  # x, y_target, ttl
        self._next_saucer = self.rng.randint(SAUCER_MIN_GAP, SAUCER_MAX_GAP)
        self._last_kill_frame = 0

        self.stars = [(self.rng.random(), self.rng.random(), self.rng.random())
                      for _ in range(26)]
        self._title = pixel_text("TIME TRACKER", QColor("#facc15"), 20, 2)
        self._title_shadow = pixel_text("TIME TRACKER", QColor("#dc2626"), 20, 2)
        self._prompt = pixel_text("INSERT COIN TO START", QColor("#22d3ee"), 10, 1)
        self._score_text = ""
        self._score_pixmap = None
        self._target_text = ""
        self._target_pixmap = None
        self.set_scores("0:00:00", "8:00:00")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(FPS_MS)

    def stop(self) -> None:
        self.timer.stop()

    def set_scores(self, today: str, target: str) -> None:
        """1UP = today's tracked time; HI-SCORE = the daily target."""
        if today != self._score_text:
            self._score_text = today
            self._score_pixmap = pixel_text(f"1UP  {today}", QColor("#ffffff"), 10, 1)
        if target != self._target_text:
            self._target_text = target
            self._target_pixmap = pixel_text(
                f"HI-SCORE  {target}", QColor("#ef4444"), 10, 1)

    # --- animation state --------------------------------------------------

    def spawn_saucer(self) -> None:
        if self.saucer_x is None:
            self.saucer_x = -80.0

    def _tick(self) -> None:
        self._step()
        self.update()

    def _step(self) -> None:
        self.frame += 1
        if self.frame % MARCH_EVERY == 0:
            self.march_offset += MARCH_STEP * self.march_dir
            if abs(self.march_offset) >= MARCH_RANGE:
                self.march_dir *= -1
        if self.frame % BLINK_EVERY == 0:
            self.blink_on = not self.blink_on

        if self.saucer_x is None and self.frame >= self._next_saucer:
            self.spawn_saucer()

        if self.saucer_x is not None:
            self.saucer_x += SAUCER_SPEED
            saucer_mid = self.saucer_x + sprite_width(SAUCER, 3) / 2
            for invader in self.invaders:
                if invader.state == "alive":
                    ix = invader.x_frac * max(1, self.width()) + self.march_offset
                    mid = ix + sprite_width(invader.grid, 3) / 2
                    if abs(saucer_mid - mid) < SAUCER_SPEED:
                        invader.state = "exploding"
                        invader.frame = 0
                        self.lasers.append((mid, invader.y, 4))
                        self._last_kill_frame = self.frame
            if self.saucer_x > self.width() + 80:
                self.saucer_x = None
                self._next_saucer = self.frame + self.rng.randint(
                    SAUCER_MIN_GAP, SAUCER_MAX_GAP)

        self.lasers = [(x, y, ttl - 1) for x, y, ttl in self.lasers if ttl > 0]

        for invader in self.invaders:
            if invader.state == "exploding":
                invader.frame += 1
                if invader.frame >= EXPLOSION_FRAMES:
                    invader.state = "dead"

        if (self.saucer_x is None
                and any(i.state == "dead" for i in self.invaders)
                and self.frame - self._last_kill_frame >= RESPAWN_AFTER):
            for invader in self.invaders:
                if invader.state == "dead":
                    invader.state = "alive"
                    invader.frame = 0

    # --- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        w, h = self.width(), self.height()
        p = QPainter(self)

        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor("#050510"))
        bg.setColorAt(1.0, QColor("#0b1035"))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), 10, 10)

        for i, (fx, fy, phase) in enumerate(self.stars):
            twinkle = 140 + int(90 * math.sin(self.frame / 9 + phase * 6.3))
            p.fillRect(QRectF(fx * w, 14 + fy * (h - 20), 2, 2),
                       QColor(twinkle, twinkle, min(255, twinkle + 30)))

        if self._score_pixmap is not None:
            p.drawPixmap(10, 4, self._score_pixmap)
        if self._target_pixmap is not None:
            p.drawPixmap(w - self._target_pixmap.width() - 10, 4, self._target_pixmap)

        # Invaders march behind the title so the lettering stays readable
        for invader in self.invaders:
            x = invader.x_frac * w + self.march_offset
            if invader.state == "alive":
                bob = 2 * math.sin(self.frame / 14 + invader.x_frac * 7)
                draw_sprite(p, invader.grid, x, invader.y + bob, 3,
                            QColor(invader.color))

        title_x = (w - self._title.width()) // 2
        title_y = (h - self._title.height()) // 2 - 2
        p.drawPixmap(title_x + 3, title_y + 3, self._title_shadow)
        p.drawPixmap(title_x, title_y, self._title)
        if self.blink_on:
            p.drawPixmap((w - self._prompt.width()) // 2,
                         h - self._prompt.height() - 6, self._prompt)

        # Explosions render on top of everything — they earned it
        for invader in self.invaders:
            if invader.state == "exploding":
                x = invader.x_frac * w + self.march_offset
                color = QColor("#fde047") if invader.frame % 4 < 2 else QColor("#f97316")
                px = 3 + invader.frame / 6  # explosion grows as it burns out
                draw_sprite(p, EXPLOSION, x, invader.y, px, color)

        for x, y_target, _ttl in self.lasers:
            p.fillRect(QRectF(x - 1.5, 16, 3, y_target - 12), QColor("#fde047"))

        if self.saucer_x is not None:
            draw_sprite(p, SAUCER, self.saucer_x, 8, 3, QColor("#ef4444"))

        p.setPen(Qt.PenStyle.NoPen)
        for y in range(0, h, 4):
            p.fillRect(QRectF(0, y, w, 1), QColor(0, 0, 0, 60))
        p.end()
