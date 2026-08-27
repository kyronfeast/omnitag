"""Mixed fleet: an async LLRP reader + a blocking-SDK reader, side by side.

The blocking reader (a stand-in for a WYUAN-style SDK) is isolated on its own
thread, so the async LLRP reader keeps streaming at full rate instead of being
gated to the slow one's pace. Run with no hardware:

    python examples/mixed_fleet.py
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

from llrpkit import TagReport
from llrpkit.emulator import LLRPEmulator

from omnitag import DriverCapabilities, Fleet, LLRPDriver, ThreadedDriver

PAIL = bytes([0xE2, 0x00, 0xAA] + [0] * 9)


class FakeBlockingDriver(ThreadedDriver):
    """A blocking vendor SDK, simulated: each read waits, then returns."""

    def _build_caps(self) -> DriverCapabilities:
        return DriverCapabilities(reader_id=self.reader_id, kind="fake", isolation="thread")

    def _read_blocking(self, stop: threading.Event) -> Iterator[TagReport]:
        while not stop.is_set():
            time.sleep(0.1)  # a slow blocking SDK (~10 reads/s)
            yield TagReport(epc=PAIL, antenna=1, rssi_dbm=-55.0)


async def main() -> None:
    emu = LLRPEmulator(reads_per_sec=400.0, seed=5)
    await emu.start()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="impinj") as fast,
            FakeBlockingDriver(reader_id="vendor") as slow,
        ):
            for c in Fleet([fast, slow]).capabilities:
                print(f"  {c.reader_id:8} kind={c.kind:5} isolation={c.isolation}")
            print()

            counts = {"impinj": 0, "vendor": 0}
            stream = Fleet([fast, slow]).stream(max_tags=10_000, duration=6.0)
            async for s in stream:
                counts[s.reader_id] += 1
                if counts["impinj"] >= 60:
                    break
    finally:
        await emu.stop()

    print(f"  impinj (async, on the loop):   {counts['impinj']} reads")
    print(f"  vendor (blocking, own thread): {counts['vendor']} reads")
    print("\n  the async reader raced ahead — the blocking SDK never gated it.")


if __name__ == "__main__":
    asyncio.run(main())
