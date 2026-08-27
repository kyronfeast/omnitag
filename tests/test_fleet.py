"""A fleet merges several readers into one normalized, reader-tagged stream."""

from __future__ import annotations

import contextlib

from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy
from llrpkit.emulator import LLRPEmulator

from omnitag import Fleet, LLRPDriver, SourcedTag


async def _drain(fleet: Fleet, cap: int, **opts: object) -> list[SourcedTag]:
    out: list[SourcedTag] = []
    stream = fleet.stream(max_tags=8, duration=8.0, **opts)
    async with contextlib.aclosing(stream):  # type: ignore[type-var]
        async for sourced in stream:
            out.append(sourced)
            if len(out) >= cap:
                break
    return out


async def test_fleet_merges_two_readers(
    two_emulators: tuple[LLRPEmulator, LLRPEmulator],
) -> None:
    a, b = two_emulators
    async with (
        LLRPDriver("127.0.0.1", a.port, reader_id="line-a") as da,
        LLRPDriver("127.0.0.1", b.port, reader_id="line-b") as db,
    ):
        fleet = Fleet([da, db])
        assert {c.reader_id for c in fleet.capabilities} == {"line-a", "line-b"}
        sourced = await _drain(fleet, cap=12)

    assert sourced, "fleet produced nothing"
    # every item knows which reader it came from...
    assert all(isinstance(s, SourcedTag) for s in sourced)
    seen_readers = {s.reader_id for s in sourced}
    # ...and over enough reads, both readers appear in the merged stream
    assert seen_readers == {"line-a", "line-b"}


async def test_one_policy_filters_the_whole_fleet(
    two_emulators: tuple[LLRPEmulator, LLRPEmulator],
) -> None:
    a, b = two_emulators
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
    async with (
        LLRPDriver("127.0.0.1", a.port, reader_id="line-a") as da,
        LLRPDriver("127.0.0.1", b.port, reader_id="line-b") as db,
    ):
        fleet = Fleet([da, db])
        sourced = await _drain(fleet, cap=10, policy=policy)

    assert sourced, "policy fleet stream produced nothing"
    # the single shared policy filters both readers host-side
    assert all(s.tag.epc[:3] == bytes([0xE2, 0x00, 0xAA]) for s in sourced)
    assert all(s.tag.category == "pails" for s in sourced)


async def test_empty_fleet_rejected() -> None:
    try:
        Fleet([])
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("empty fleet should raise")
