"""Windows-flavoured autostart logic — pure path handling, runs anywhere."""

import sys

from timetracker import autostart


def test_source_python_prefers_pythonw_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    python = tmp_path / "python.exe"
    python.touch()
    assert autostart._source_python(python) == python  # no pythonw available

    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    assert autostart._source_python(python) == pythonw  # console-less wins


def test_source_python_untouched_on_other_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    python = tmp_path / "python.exe"
    python.touch()
    (tmp_path / "pythonw.exe").touch()
    assert autostart._source_python(python) == python
