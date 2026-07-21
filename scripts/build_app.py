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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "timetracker" / "assets"
ENTRY = ROOT / "packaging" / "entry.py"


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
        print(f"\nDone: {ROOT / 'dist' / 'timeTrackerTool' / 'timeTrackerTool.exe'}")
        print("Add it to the Start Menu with:")
        print("    poetry run python scripts/install_windows.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
