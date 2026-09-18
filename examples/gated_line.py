"""Two stations, two brands of reader, one stream of "pail passed" windows.

No hardware: llrpkit's emulator plays an Impinj R700 at the dock (its photo eye
is ``emu.set_gpi``), and a tiny fake serial port plays a WYUAN reader on line 4
(its photo eye is a flag we flip). Three pails go by — the last one with no
readable tag — and the fleet reports each as a window, empty or not.

    python examples/gated_line.py
"""

from __future__ import annotations

import asyncio
import threading
import time

from llrpkit.emulator import EmulatedTag, LLRPEmulator

from omnitag import Fleet, LLRPDriver, WyuanReader
from omnitag.drivers.wyuan import protocol as p

DOCK_TAG = bytes.fromhex("e2000017010b016210000001")
LINE_TAG = bytes.fromhex("e2000017010b016210000002")


def _frame(re_cmd: int, status: int, data: bytes) -> bytes:
    body = bytes([len(data) + 5, 0, re_cmd, status]) + data
    crc = p.crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class FakeWyuanWithPhotoEye:
    """Answers GPIO-status and inventory polls; ``in1_high`` is the photo eye."""

    def __init__(self) -> None:
        self.in1_high = True  # pulled-up input: idle high
        self.present: list[bytes] = []
        self._buf = bytearray()
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int:
        cmd = data[2]
        with self._lock:
            if cmd == p.GPIO_GET:
                self._buf += _frame(p.GPIO_GET, 0, bytes([0x30 | int(self.in1_high)]))
            elif cmd == p.INVENTORY:
                body = bytearray([0x01, len(self.present)])
                for epc in self.present:
                    body += bytes([len(epc)]) + epc + b"\x50"
                self._buf += _frame(p.INVENTORY, p.ST_DONE, bytes(body))
            elif cmd == p.SET_WORK_MODE:
                self._buf += _frame(p.SET_WORK_MODE, 0, b"")
        return len(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            take = bytes(self._buf[:size])
            del self._buf[:size]
        if not take:
            time.sleep(0.005)
        return take

    def close(self) -> None:
        pass


async def main() -> None:
    emu = LLRPEmulator(reads_per_sec=200.0, seed=1)
    emu.tags = [EmulatedTag(epc=DOCK_TAG, antennas=(1,), rssi_dbm=-48.0)]
    await emu.start()
    fake = FakeWyuanWithPhotoEye()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="dock", gpi_trigger=1) as dock,
            WyuanReader(reader_id="line-4", transport=fake, gpi_trigger=True, scan_time=1) as line,
        ):
            fleet = Fleet([dock, line])
            print("two stations, one gated stream — three pails go by\n")

            async def pails() -> None:
                await asyncio.sleep(0.3)
                await emu.set_gpi(1, True)  # pail 1 at the dock (R700: voltage = active)
                await asyncio.sleep(0.4)
                await emu.set_gpi(1, False)

                await asyncio.sleep(0.3)
                fake.present = [LINE_TAG]
                fake.in1_high = False  # pail 2 on line 4 (WYUAN: pulled low = active)
                await asyncio.sleep(0.4)
                fake.in1_high = True

                await asyncio.sleep(0.3)
                fake.present = []  # pail 3 on line 4 — no readable tag
                fake.in1_high = False
                await asyncio.sleep(0.3)
                fake.in1_high = True

            asyncio.create_task(pails())
            n = 0
            async for sw in fleet.windows(settle=0.1):
                w = sw.window
                verdict = ", ".join(w.epcs) if w.epcs else "NOTHING READ  <-- pail with no tag"
                print(f"  [{sw.reader_id:6}] window {w.duration:.2f}s  {verdict}")
                n += 1
                if n == 3:
                    break
    finally:
        await emu.stop()


if __name__ == "__main__":
    asyncio.run(main())
