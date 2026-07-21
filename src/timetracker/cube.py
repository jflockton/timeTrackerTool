"""Timeular Tracker (ZEI°) support — the 8-sided Bluetooth time cube.

Protocol (community-documented, e.g. github.com/codingforfun/zeipy):
service ``c7e70010-…``, characteristic ``c7e70012-…`` reports the active
side as a single byte — 1..8 for a face up, 0 for resting on its base.

``CubeListener`` runs bleak's asyncio machinery in a daemon thread and
re-emits side changes as Qt signals (cross-thread emits are queued safely
by Qt). It scans, connects, subscribes, and reconnects forever until
stopped. The official Timeular app must be closed — the tracker only
accepts one connection at a time.
"""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject, Signal

ORIENTATION_SERVICE = "c7e70010-c847-11e6-8175-8c89a55d403c"
ORIENTATION_CHAR = "c7e70012-c847-11e6-8175-8c89a55d403c"
NAME_HINTS = ("timeular", "zei")
SIDES = range(1, 9)


class CubeListener(QObject):
    side_changed = Signal(int)    # 0 = base / no side, 1..8 = face up
    status_changed = Signal(str)  # human-readable connection state

    def __init__(self) -> None:
        super().__init__()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._run()), daemon=True,
            name="timeular-cube")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # --- BLE loop (daemon thread) ----------------------------------------

    @staticmethod
    def _looks_like_tracker(device, advertisement) -> bool:
        uuids = [u.lower() for u in (advertisement.service_uuids or [])]
        if ORIENTATION_SERVICE in uuids:
            return True
        name = (device.name or "").lower()
        return any(hint in name for hint in NAME_HINTS)

    async def _run(self) -> None:
        from bleak import BleakClient, BleakScanner  # lazy: keeps tests light

        while not self._stop.is_set():
            try:
                self.status_changed.emit("Cube: scanning…")
                device = await BleakScanner.find_device_by_filter(
                    self._looks_like_tracker, timeout=10)
                if device is None:
                    self.status_changed.emit(
                        "Cube: not found — is it awake, and the Timeular app closed?")
                    await self._sleep(5)
                    continue
                async with BleakClient(device) as client:
                    self.status_changed.emit(f"Cube: connected ({device.name})")
                    initial = await client.read_gatt_char(ORIENTATION_CHAR)
                    if initial:
                        self.side_changed.emit(int(initial[0]))

                    def on_indication(_handle, data: bytearray) -> None:
                        if data:
                            self.side_changed.emit(int(data[0]))

                    await client.start_notify(ORIENTATION_CHAR, on_indication)
                    while client.is_connected and not self._stop.is_set():
                        await asyncio.sleep(0.5)
                    if client.is_connected:
                        await client.stop_notify(ORIENTATION_CHAR)
                if not self._stop.is_set():
                    self.status_changed.emit("Cube: disconnected — reconnecting…")
            except Exception as exc:  # BLE is flaky by nature; keep trying
                self.status_changed.emit(f"Cube: {exc} — retrying…")
                await self._sleep(5)
        self.status_changed.emit("Cube: off")

    async def _sleep(self, seconds: float) -> None:
        for _ in range(int(seconds * 2)):
            if self._stop.is_set():
                return
            await asyncio.sleep(0.5)
