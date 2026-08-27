"""OmniTag as a service — emit tags as JSON so any language can consume them.

This turns a fleet of readers into a plain stream of one-JSON-object-per-line on
stdout. A program in C#, C++, Java, Node — anything — can read that stream (or
pipe it to a file, or swap the ``emit`` function for an MQTT publish / HTTP POST)
without knowing a word of Python.

Run it against the built-in emulator (no hardware):

    python examples/service.py

Each line looks like:

    {"reader": "dock", "epc": "e2000017...", "antenna": 3, "rssi_dbm": -52.0,
     "category": null, "at": 1770950400.12}

To point it at real readers, replace the emulator block with your actual
drivers, e.g. LLRPDriver("192.168.1.10") and WyuanReader("COM3").
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from llrpkit.emulator import LLRPEmulator

from omnitag import Fleet, LLRPDriver, SourcedTag


def emit(sourced: SourcedTag) -> None:
    """Write one tag as a JSON line. Swap this for MQTT/HTTP to fan out anywhere."""
    line = json.dumps(
        {
            "reader": sourced.reader_id,
            "epc": sourced.tag.epc_hex,
            "antenna": sourced.tag.antenna,
            "rssi_dbm": sourced.tag.rssi_dbm,
            "category": sourced.tag.category,
            "at": round(time.time(), 2),
        }
    )
    sys.stdout.write(line + "\n")
    sys.stdout.flush()  # flush so consumers see each line immediately


async def main() -> None:
    # --- demo wiring: two emulated readers. Replace with your real drivers. ---
    dock_emu = LLRPEmulator(reads_per_sec=200.0, seed=1)
    line_emu = LLRPEmulator(reads_per_sec=200.0, seed=2)
    await dock_emu.start()
    await line_emu.start()
    try:
        async with (
            LLRPDriver("127.0.0.1", dock_emu.port, reader_id="dock") as a,
            LLRPDriver("127.0.0.1", line_emu.port, reader_id="line-4") as b,
        ):
            fleet = Fleet([a, b])
            count = 0
            stream = fleet.stream(max_tags=100_000, duration=3.0)
            async for sourced in stream:
                emit(sourced)
                count += 1
                if count >= 20:  # demo: stop after 20 lines
                    break
    finally:
        await dock_emu.stop()
        await line_emu.stop()


if __name__ == "__main__":
    asyncio.run(main())
