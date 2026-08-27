"""Shared fixtures: emulated LLRP readers, no hardware required."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from llrpkit.emulator import EmulatedTag, LLRPEmulator

# Two item families across two antennas so per-antenna policy is observable.
PAILS = [EmulatedTag(epc=bytes([0xE2, 0x00, 0xAA, i] + [0] * 8), antennas=(4,)) for i in range(3)]
PICKLES = [EmulatedTag(epc=bytes([0xE2, 0x00, 0xBB, i] + [0] * 8), antennas=(4,)) for i in range(3)]


async def _spawn(seed: int) -> LLRPEmulator:
    emu = LLRPEmulator(tags=PAILS + PICKLES, reads_per_sec=400.0, seed=seed)
    await emu.start()
    return emu


@pytest.fixture(name="emulator")
async def fixture_emulator() -> AsyncIterator[LLRPEmulator]:
    emu = await _spawn(seed=1)
    try:
        yield emu
    finally:
        await emu.stop()


@pytest.fixture(name="two_emulators")
async def fixture_two_emulators() -> AsyncIterator[tuple[LLRPEmulator, LLRPEmulator]]:
    a = await _spawn(seed=2)
    b = await _spawn(seed=3)
    try:
        yield a, b
    finally:
        await a.stop()
        await b.stop()
