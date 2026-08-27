"""The LLRP driver satisfies the seam and streams normalized tags."""

from __future__ import annotations

import contextlib

from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy, TagReport
from llrpkit.emulator import LLRPEmulator

from omnitag import LLRPDriver, ReaderDriver


async def _collect(driver: LLRPDriver, n: int, **opts: object) -> list[TagReport]:
    seen: list[TagReport] = []
    stream = driver.inventory(max_tags=n, duration=8.0, **opts)
    async with contextlib.aclosing(stream):  # type: ignore[type-var]
        async for tag in stream:
            seen.append(tag)
    return seen


async def test_driver_is_a_readerdriver_and_streams(emulator: LLRPEmulator) -> None:
    async with LLRPDriver("127.0.0.1", emulator.port) as driver:
        assert isinstance(driver, ReaderDriver)  # structural: satisfies the Protocol
        tags = await _collect(driver, 10)
    assert tags, "driver produced no tags"
    assert all(isinstance(t, TagReport) for t in tags)


async def test_capabilities_are_vendor_neutral(emulator: LLRPEmulator) -> None:
    async with LLRPDriver("127.0.0.1", emulator.port, reader_id="dock-1") as driver:
        caps = driver.capabilities
    assert caps.reader_id == "dock-1"
    assert caps.kind == "llrp"
    assert caps.antenna_count >= 1
    assert caps.gpio is True and caps.tag_access is True
    assert caps.host_side_policy is True


async def test_host_side_policy_reused_through_the_driver(emulator: LLRPEmulator) -> None:
    # The llrpkit policy engine works unchanged behind the OmniTag seam.
    catalog = ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles-fresh"),
        ]
    )
    policy = ReaderPolicy(
        catalog=catalog,
        antennas={4: AntennaPolicy(mode="allow", categories={"pails"})},
    )
    async with LLRPDriver("127.0.0.1", emulator.port) as driver:
        tags = await _collect(driver, 20, policy=policy)

    assert tags, "policy stream produced nothing"
    assert all(t.epc[:3] == bytes([0xE2, 0x00, 0xAA]) for t in tags)  # only pails
    assert all(t.category == "pails" for t in tags)  # kept tags carry category
    snap = policy.counters()
    assert snap["dropped"] > 0
    assert snap["by_category"].get("pickles-fresh", 0) > 0


async def test_capabilities_error_before_connect(emulator: LLRPEmulator) -> None:
    driver = LLRPDriver("127.0.0.1", emulator.port)
    try:
        driver.capabilities  # noqa: B018 — asserting it raises
    except RuntimeError as exc:
        assert "connect" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("capabilities should be unavailable before connect")
