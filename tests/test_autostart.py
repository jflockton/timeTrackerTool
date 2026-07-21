import plistlib
import sys

import pytest

from timetracker import autostart

pytestmark = pytest.mark.skipif(sys.platform != "darwin",
                                reason="macOS LaunchAgent variant")


def test_enable_writes_plist_and_disable_removes(tmp_path):
    assert not autostart.is_enabled(home=tmp_path)
    autostart.enable(home=tmp_path)
    assert autostart.is_enabled(home=tmp_path)

    plist_file = tmp_path / "Library" / "LaunchAgents" / f"{autostart.APP_ID}.plist"
    payload = plistlib.loads(plist_file.read_bytes())
    assert payload["Label"] == autostart.APP_ID
    assert payload["RunAtLoad"] is True
    assert payload["ProgramArguments"] == autostart.launch_command()

    autostart.disable(home=tmp_path)
    assert not autostart.is_enabled(home=tmp_path)
    autostart.disable(home=tmp_path)  # second disable is a no-op, not an error
