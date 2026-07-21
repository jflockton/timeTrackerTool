import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "install_windows",
    Path(__file__).resolve().parents[1] / "scripts" / "install_windows.py")
install_windows = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(install_windows)

FAKE_ENV = {
    "LOCALAPPDATA": r"C:\Users\pat\AppData\Local",
    "APPDATA": r"C:\Users\pat\AppData\Roaming",
    "ProgramFiles": r"C:\Program Files",
    "ProgramData": r"C:\ProgramData",
}


def test_current_user_paths_stay_inside_the_profile():
    install_dir, shortcut = install_windows.resolve_paths("current", FAKE_ENV)
    assert install_dir == Path(r"C:\Users\pat\AppData\Local\Programs\timeTrackerTool")
    assert shortcut == Path(r"C:\Users\pat\AppData\Roaming\Microsoft\Windows"
                            r"\Start Menu\Programs\timeTrackerTool.lnk")


def test_all_users_paths_use_the_machine_locations():
    install_dir, shortcut = install_windows.resolve_paths("all", FAKE_ENV)
    assert install_dir == Path(r"C:\Program Files\timeTrackerTool")
    assert shortcut == Path(r"C:\ProgramData\Microsoft\Windows"
                            r"\Start Menu\Programs\timeTrackerTool.lnk")


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError):
        install_windows.resolve_paths("everyone", FAKE_ENV)


def test_non_windows_platforms_are_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["install_windows.py"])
    assert install_windows.main() == 1
    assert "Windows-only" in capsys.readouterr().out
