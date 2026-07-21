import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "build_app", ROOT / "scripts" / "build_app.py")
build_app = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_app)


def test_windows_bundle_name_carries_version():
    from timetracker import __version__

    assert build_app.windows_bundle_name() == \
        f"timeTrackerTool-{__version__}-windows.zip"
    assert __version__ in build_app.BUNDLE_README


def test_no_python_installer_ships():
    ps1 = (ROOT / "packaging" / "install.ps1").read_text(encoding="utf-8")
    for needle in ("Start Menu", "LOCALAPPDATA", "ProgramFiles",
                   "-Uninstall", "RunAs", "CreateShortcut"):
        assert needle in ps1
    bat = (ROOT / "packaging" / "install.bat").read_text(encoding="utf-8")
    assert "-ExecutionPolicy Bypass" in bat
    assert "install.ps1" in bat
