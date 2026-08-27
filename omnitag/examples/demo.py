"""OmniTag demo — two emulated readers, one merged stream, one ignore policy.

Runs with zero hardware against llrpkit's emulator:

    python examples/demo.py
"""

from __future__ import annotations

import asyncio

from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy
from llrpkit.emulator import EmulatedTag, LLRPEmulator

from omnitag import Fleet, LLRPDriver

PAILS = [EmulatedTag(epc=bytes([0xE2, 0x00, 0xAA, i] + [0] * 8), antennas=(4,)) for i in range(3)]
PICKLES = [EmulatedTag(epc=bytes([0xE2, 0x00, 0xBB, i] + [0] * 8), antennas=(4,)) for i in range(3)]


def line4_policy() -> ReaderPolicy:
    catalog = ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles-fresh"),
        ]
    )
    return ReaderPolicy(
        catalog=catalog,
        antennas={4: AntennaPolicy(mode="allow", categories={"pails"})},
    )


async def main() -> None:
    a = LLRPEmulator(tags=PAILS + PICKLES, reads_per_sec=400.0, seed=2)
    b = LLRPEmulator(tags=PAILS + PICKLES, reads_per_sec=400.0, seed=3)
    await a.start()
    await b.start()

    policy = line4_policy()
    print("two readers, one policy: line 4 sees only pails\n")
    try:
        async with (
            LLRPDriver("127.0.0.1", a.port, reader_id="line-a") as da,
            LLRPDriver("127.0.0.1", b.port, reader_id="line-b") as db,
        ):
            for caps in Fleet([da, db]).capabilities:
                print(f"  reader {caps.reader_id}: {caps.kind} model {caps.model} "
                      f"antennas={caps.antenna_count} gpio={caps.gpio}")
            print()
            fleet = Fleet([da, db])
            count = 0
            stream = fleet.stream(max_tags=6, duration=6.0, policy=policy)
            async for s in stream:
                print(f"  [{s.reader_id}] {s.tag.epc_hex}  ant {s.tag.antenna}  "
                      f"[{s.tag.category}]")
                count += 1
                if count >= 8:
                    break
    finally:
        await a.stop()
        await b.stop()

    snap = policy.counters()
    print(f"\nkept {snap['kept']} · dropped {snap['dropped']} "
          f"({snap['by_category']})")


if __name__ == "__main__":
    asyncio.run(main())
