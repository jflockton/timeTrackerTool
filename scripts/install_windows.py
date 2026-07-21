"""Install the built Windows app with a Start Menu shortcut.

    poetry run python scripts/build_app.py             # build first
    poetry run python scripts/install_windows.py       # then install

Asks whether to install for just you or for all users, copies
dist/timeTrackerTool to a proper install location, and creates a Start
Menu shortcut pointing at the exe:

    just me    -> %LOCALAPPDATA%\\Programs\\timeTrackerTool   (no admin)
    all users  -> %ProgramFiles%\\timeTrackerTool             (admin required)

Re-run after a rebuild to upgrade in place. Remove everything again with:

    poetry run python scripts/install_windows.py --uninstall

Windows only — on macOS just drag the .app into /Applications.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "timeTrackerTool"
APP_NAME = "timeTrackerTool"
SHORTCUT_NAME = f"{APP_NAME}.lnk"


def resolve_paths(scope: str, env: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Return (install_dir, shortcut_path) for 'current' or 'all' scope.

    Pure — reads only the mapping passed in, so tests can drive it with a
    fake environment on any platform.
    """
    env = os.environ if env is None else env
    if scope == "current":
        install_dir = Path(env["LOCALAPPDATA"]) / "Programs" / APP_NAME
        menu = Path(env["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    elif scope == "all":
        install_dir = Path(env["ProgramFiles"]) / APP_NAME
        menu = Path(env["ProgramData"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    else:
        raise ValueError(f"unknown scope: {scope!r}")
    return install_dir, menu / SHORTCUT_NAME


def is_admin() -> bool:
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def ask_scope() -> str:
    print("Install timeTrackerTool for:")
    print("  [1] Just me     (no admin needed)")
    print("  [2] All users   (needs an Administrator prompt)")
    while True:
        choice = input("Choose 1 or 2: ").strip()
        if choice == "1":
            return "current"
        if choice == "2":
            return "all"
        print("Please type 1 or 2.")


def create_shortcut(shortcut: Path, target: Path, workdir: Path) -> None:
    """Create/overwrite a .lnk via the WScript.Shell COM object."""
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.WorkingDirectory = '{workdir}'; "
        f"$s.IconLocation = '{target},0'; "
        f"$s.Description = 'timeTrackerTool - one big button per task'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True, capture_output=True)


def install(scope: str) -> int:
    if not (DIST / f"{APP_NAME}.exe").exists():
        print("No built app found. Run this first:")
        print("    poetry run python scripts/build_app.py")
        return 1

    install_dir, shortcut = resolve_paths(scope)
    if scope == "all" and not is_admin():
        print("Installing for all users writes to Program Files, which needs")
        print("an Administrator prompt. Open one (Win+X -> Terminal (Admin)),")
        print("then run:")
        print(f"    cd {ROOT}")
        print("    poetry run python scripts/install_windows.py --all-users")
        return 1

    print(f"Installing to {install_dir} ...")
    try:
        if install_dir.exists():
            shutil.rmtree(install_dir)
        shutil.copytree(DIST, install_dir)
    except PermissionError:
        print("Could not replace the installed app — if timeTrackerTool is")
        print("running, quit it (tray icon -> Quit) and re-run the install.")
        return 1

    exe = install_dir / f"{APP_NAME}.exe"
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    create_shortcut(shortcut, exe, install_dir)
    print(f"Start Menu shortcut: {shortcut}")
    print("Done — press the Windows key and type 'time' to find it.")
    return 0


def uninstall(scope: str) -> int:
    install_dir, shortcut = resolve_paths(scope)
    if scope == "all" and not is_admin():
        print("Removing an all-users install needs an Administrator prompt;")
        print("re-run there with:  poetry run python scripts/install_windows.py"
              " --uninstall --all-users")
        return 1
    removed = False
    if shortcut.exists():
        shortcut.unlink()
        print(f"Removed {shortcut}")
        removed = True
    if install_dir.exists():
        shutil.rmtree(install_dir)
        print(f"Removed {install_dir}")
        removed = True
    if not removed:
        print(f"Nothing installed for scope '{scope}' — nothing removed.")
    print("Your tracked time is untouched (it lives in %APPDATA%\\timeTrackerTool).")
    return 0


def main() -> int:
    if sys.platform != "win32":
        print("This installer is Windows-only. On macOS drag "
              "dist/timeTrackerTool.app into /Applications.")
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--current-user", action="store_true",
                     help="install for just this user (no prompt)")
    who.add_argument("--all-users", action="store_true",
                     help="install for all users (requires admin)")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove the installed app and its shortcut")
    args = parser.parse_args()

    if args.current_user:
        scope = "current"
    elif args.all_users:
        scope = "all"
    else:
        scope = ask_scope()

    return uninstall(scope) if args.uninstall else install(scope)


if __name__ == "__main__":
    raise SystemExit(main())
