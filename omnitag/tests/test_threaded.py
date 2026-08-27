"""A blocking driver runs off the loop and cannot starve async readers.

This is the design guarantee made executable: a driver that wraps a *blocking*
SDK (simulated here with ``time.sleep``) is isolated on a worker thread, so an
async LLRP reader in the same fleet keeps streaming at full rate while the
blocking one plods along. That's the co-hosted-SDK starvation — designed out.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator, Sequence

from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy, TagReport
from llrpkit.emulator import LLRPEmulator

from omnitag import DriverCapabilities, Fleet, LLRPDriver, ThreadedDriver

PAIL = bytes([0xE2, 0x00, 0xAA] + [0] * 9)
PICKLE = bytes([0xE2, 0x00, 0xBB] + [0] * 9)


class FakeBlockingDriver(ThreadedDriver):
    """Stands in for a WYUAN-style blocking SDK: each read blocks, then returns."""

    def __init__(self, epcs: Sequence[bytes], reader_id: str, sleep: float = 0.05) -> None:
        super().__init__(reader_id=reader_id)
        self._epcs = list(epcs)
        self._sleep = sleep

    def _build_caps(self) -> DriverCapabilities:
        return DriverCapabilities(
            reader_id=self.reader_id,
            kind="fake",
            isolation="thread",  # the fleet must run this off the loop
            antenna_count=1,
            gpio=False,
            tag_access=False,
        )

    def _read_blocking(self, stop: threading.Event) -> Iterator[TagReport]:
        i = 0
        while not stop.is_set():
            time.sleep(self._sleep)  # a blocking SDK waiting for the next read
            yield TagReport(epc=self._epcs[i % len(self._epcs)], antenna=1, rssi_dbm=-50.0)
            i += 1


async def test_blocking_driver_streams_and_declares_thread_isolation() -> None:
    driver = FakeBlockingDriver([PAIL, PICKLE], reader_id="fake-1", sleep=0.02)
    async with driver:
        assert driver.capabilities.isolation == "thread"
        seen: list[TagReport] = []
        stream = driver.inventory(max_tags=5)
        async with contextlib.aclosing(stream):  # type: ignore[type-var]
            async for tag in stream:
                seen.append(tag)
    assert len(seen) == 5
    assert all(isinstance(t, TagReport) for t in seen)


async def test_blocking_driver_does_not_starve_the_async_reader() -> None:
    emu = LLRPEmulator(tags=None, reads_per_sec=400.0, seed=7)
    await emu.start()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="llrp") as llrp,
            FakeBlockingDriver([PAIL], reader_id="slow", sleep=0.1) as slow,
        ):
            assert llrp.capabilities.isolation == "loop"
            assert slow.capabilities.isolation == "thread"

            fleet = Fleet([llrp, slow])
            per_reader: dict[str, int] = {"llrp": 0, "slow": 0}
            stream = fleet.stream(max_tags=1000, duration=8.0)
            async with contextlib.aclosing(stream):  # type: ignore[type-var]
                async for sourced in stream:
                    per_reader[sourced.reader_id] += 1
                    if per_reader["llrp"] >= 40:
                        break
    finally:
        await emu.stop()

    # The async reader raced ahead at ~400/s while the blocking one dripped at
    # ~10/s. If the blocking SDK were on the loop, the fast reader would be
    # gated to the slow one's pace. It isn't — that's the guarantee.
    assert per_reader["llrp"] >= 40
    assert per_reader["llrp"] > per_reader["slow"] * 3


async def test_one_policy_filters_a_blocking_driver_too() -> None:
    # Host-side policy applies to blocking drivers exactly as to LLRP ones.
    catalog = ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles-fresh"),
        ]
    )
    policy = ReaderPolicy(
        catalog=catalog,
        antennas={1: AntennaPolicy(mode="allow", categories={"pails"})},
    )
    driver = FakeBlockingDriver([PAIL, PICKLE], reader_id="fake-1", sleep=0.01)
    async with driver:
        seen: list[TagReport] = []
        stream = driver.inventory(max_tags=6, policy=policy)
        async with contextlib.aclosing(stream):  # type: ignore[type-var]
            async for tag in stream:
                seen.append(tag)
    assert seen, "policy stream produced nothing"
    assert all(t.epc[:3] == bytes([0xE2, 0x00, 0xAA]) for t in seen)  # only pails
    assert all(t.category == "pails" for t in seen)
    assert policy.counters()["by_category"].get("pickles-fresh", 0) > 0
