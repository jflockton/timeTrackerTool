"""Build the double-clickable app with PyInstaller.

    poetry run python scripts/build_app.py

macOS  -> dist/timeTrackerTool.app  (icon converted to .icns via iconutil)
Windows -> dist/timeTrackerTool/timeTrackerTool.exe  (uses assets/icon.ico)

Run this ON the platform you are building for — PyInstaller does not
cross-compile.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from timetracker import __version__

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "timetracker" / "assets"
ENTRY = ROOT / "packaging" / "entry.py"

BUNDLE_README = f"""timeTrackerTool {__version__}
{'=' * (16 + len(__version__))}

No Python needed - the app is fully self-contained.

1. Keep everything in this folder together after unzipping.
2. Double-click install.bat and choose "Just me" or "All users".
   Windows SmartScreen may warn because the app is not code-signed:
   click "More info" then "Run anyway".
3. Press the Windows key, type "time", and there it is.

Updating: unzip the newer version and run install.bat again - it
upgrades in place.

Uninstall: run  install.bat -Uninstall
Your tracked time always survives installs and uninstalls - it lives
in %APPDATA%\\timeTrackerTool, outside the app folder.
"""


def windows_bundle_name() -> str:
    return f"timeTrackerTool-{__version__}-windows.zip"


def make_windows_bundle() -> Path:
    """Zip the built app together with the no-Python installer so the
    result can be sent to anyone: unzip, double-click install.bat, done."""
    dist = ROOT / "dist"
    app_dir = dist / "timeTrackerTool"
    zip_path = dist / windows_bundle_name()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(app_dir.rglob("*")):
            if file.is_file():
                bundle.write(
                    file, Path("timeTrackerTool") / file.relative_to(app_dir))
        bundle.write(ROOT / "packaging" / "install.ps1", "install.ps1")
        bundle.write(ROOT / "packaging" / "install.bat", "install.bat")
        bundle.writestr("README.txt", BUNDLE_README)
    return zip_path


def make_icns(png: Path, out_dir: Path) -> Path:
    """macOS only: build a multi-resolution .icns from the 1024px PNG."""
    iconset = out_dir / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = size * scale
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(png), "--out",
                 str(iconset / f"icon_{size}x{size}{suffix}.png")],
                check=True, capture_output=True)
    icns = out_dir / "icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                   check=True)
    return icns


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        if sys.platform == "darwin":
            icon = make_icns(ASSETS / "icon.png", Path(tmp))
        else:
            icon = ASSETS / "icon.ico"

        args = [
            "pyinstaller",
            "--noconfirm",
            "--windowed",                 # no console window
            "--name", "timeTrackerTool",
            "--icon", str(icon),
            "--collect-data", "timetracker",   # bundle the PNG assets
            str(ENTRY),
        ]
        print("+", " ".join(args))
        subprocess.run(args, check=True, cwd=ROOT)

    if sys.platform == "darwin":
        # macOS requires a usage string before an app may touch Bluetooth
        # (needed for the Timeular cube integration).
        import plistlib
        plist_path = ROOT / "dist" / "timeTrackerTool.app" / "Contents" / "Info.plist"
        with open(plist_path, "rb") as handle:
            info = plistlib.load(handle)
        info["NSBluetoothAlwaysUsageDescription"] = (
            "timeTrackerTool connects to your Timeular tracker so flipping "
            "the cube starts and stops timers.")
        with open(plist_path, "wb") as handle:
            plistlib.dump(info, handle)
        print(f"\nDone: {ROOT / 'dist' / 'timeTrackerTool.app'}")
        print("Drag it into /Applications, double-click, done.")
    else:
        bundle = make_windows_bundle()
        print(f"\nDone: {ROOT / 'dist' / 'timeTrackerTool' / 'timeTrackerTool.exe'}")
        print("Add it to the Start Menu with:")
        print("    poetry run python scripts/install_windows.py")
        print(f"\nShareable bundle (recipients need no Python): {bundle}")
        print("Send that zip; they unzip and double-click install.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
