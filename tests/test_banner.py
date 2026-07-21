"""Banner animation state machine — driven frame by frame, no timers."""

import os
import random

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from timetracker.banner import RESPAWN_AFTER, BannerWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def banner(qapp):
    widget = BannerWidget(rng=random.Random(1337))
    widget.stop()  # tests drive _step() by hand
    widget.resize(420, 104)
    yield widget
    widget.deleteLater()
    qapp.processEvents()


def test_invaders_march_back_and_forth(banner):
    offsets = set()
    for _ in range(400):
        banner._step()
        offsets.add(banner.march_offset)
    assert len(offsets) > 3           # actually moving
    assert min(offsets) < 0 < max(offsets)  # both directions


def test_prompt_blinks(banner):
    states = set()
    for _ in range(40):
        banner._step()
        states.add(banner.blink_on)
    assert states == {True, False}


def test_saucer_kills_all_then_formation_respawns(banner):
    banner.spawn_saucer()
    for _ in range(200):  # full strafing run across 420px
        banner._step()
        if banner.saucer_x is None:
            break
    assert banner.saucer_x is None  # saucer exited
    assert all(i.state == "dead" for i in banner.invaders)  # every invader shot

    for _ in range(RESPAWN_AFTER + 20):
        banner._step()
    assert all(i.state == "alive" for i in banner.invaders)  # formation is back


def test_saucer_spawns_by_itself_eventually(banner):
    for _ in range(1000):  # SAUCER_MAX_GAP is 900 frames
        banner._step()
        if banner.saucer_x is not None:
            break
    assert banner.saucer_x is not None


def test_scores_update_only_on_change(banner):
    first = banner._score_pixmap
    banner.set_scores(banner._score_text, banner._target_text)  # no change
    assert banner._score_pixmap is first
    banner.set_scores("1:23:45", "7:30:00")
    assert banner._score_pixmap is not first
    assert banner._score_text == "1:23:45"
