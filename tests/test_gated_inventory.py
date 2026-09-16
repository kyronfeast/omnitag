"""Sensor-gated inventory across both drivers — one window per pail, no hardware.

A fake serial port plays a WYUAN reader *and* its photo eye (a flag the test
flips), and llrpkit's emulator plays an Impinj R700 with ``set_gpi`` as its
photo eye. Both present the same shape upstream — an ``InventoryWindow`` per
trip, empty when nothing was read — and a ``Fleet`` merges them per station.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading

import pytest
from llrpkit import InventoryWindow, ReaderPolicy
from llrpkit.emulator import EmulatedTag, LLRPEmulator
from llrpkit.policy import AntennaPolicy, CatalogEntry, ItemCatalog

from omnitag import Fleet, LLRPDriver, WyuanReader
from omnitag.drivers.wyuan import protocol as p

PAIL = bytes.fromhex("e200aa00000000000000000a")
PICKLE = bytes.fromhex("e200bb00000000000000000b")


def _frame(re_cmd: int, status: int, data: bytes, adr: int = 0) -> bytes:
    body = bytes([len(data) + 5, adr, re_cmd, status]) + data
    crc = p.crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _inventory_frame(epcs: list[bytes]) -> bytes:
    data = bytearray([0x01, len(epcs)])
    for epc in epcs:
        data += bytes([len(epc)]) + epc + bytes([0x50])
    return _frame(p.INVENTORY, p.ST_DONE, bytes(data))


class GatedFakeSerial:
    """A WYUAN reader whose IN1 pin the test controls.

    Answers ``0x47`` with the current pin level, ``0x01`` with the tags "in
    front of the antenna" right now, ``0x76`` with OK. Records every command so
    the test can prove inventory only ran while the pin was active.
    """

    def __init__(self) -> None:
        self.in1_high = True  # pulled-up TTL input: idle high
        self.present: list[bytes] = []  # tags in the field while a pail is there
        self.commands: list[int] = []
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.inventories_while_idle = 0
        self._last_reported_high = True  # what the driver last saw on 0x47

    def write(self, data: bytes) -> int:
        cmd = data[2]
        with self._lock:
            self.commands.append(cmd)
            if cmd == p.GPIO_GET:
                self._last_reported_high = self.in1_high
                self._buf += _frame(p.GPIO_GET, 0x00, bytes([0x30 | int(self.in1_high)]))
            elif cmd == p.INVENTORY:
                # An inventory is only wrong if the pin was idle when last read;
                # a release landing mid-scan is normal (the sensor doesn't wait).
                if self._last_reported_high:
                    self.inventories_while_idle += 1
                self._buf += _inventory_frame(list(self.present))
            elif cmd == p.SET_WORK_MODE:
                self._buf += _frame(p.SET_WORK_MODE, 0x00, b"")
        return len(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            take = bytes(self._buf[:size])
            del self._buf[:size]
        if not take:
            # emulate a serial timeout without stalling the worker thread
            threading.Event().wait(0.005)
        return take

    def close(self) -> None:
        pass


def test_gpio_protocol_roundtrips() -> None:
    assert p.build_gpio_get()[2] == p.GPIO_GET
    assert p.parse_gpio_status(bytes([0x31])) == p.GPIOStatus(True, True, True)
    assert p.parse_gpio_status(bytes([0x20])) == p.GPIOStatus(False, False, True)
    with pytest.raises(p.ProtocolError):
        p.parse_gpio_status(b"")
    assert p.build_gpio_set(out1=False, out2=True)[3] == 0b10
    assert p.build_set_work_mode(p.MODE_REALTIME_TRIGGER)[3] == 2
    with pytest.raises(ValueError):
        p.build_set_work_mode(7)


async def test_wyuan_windows_one_per_pail_including_empty() -> None:
    fake = GatedFakeSerial()
    reader = WyuanReader(
        reader_id="line-4", transport=fake, gpi_trigger=True, scan_time=1, gpi_poll_interval=0.005
    )
    async with reader:
        assert reader.capabilities.gpi_trigger is True
        windows: list[InventoryWindow] = []

        async def collect() -> None:
            async for w in reader.windows(max_open=5.0):
                windows.append(w)
                if len(windows) == 2:
                    return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.15)  # idle: pin high, no windows

        fake.present = [PAIL]
        fake.in1_high = False  # pail 1 breaks the beam → relay pulls IN1 low
        await asyncio.sleep(0.15)
        fake.in1_high = True  # pail 1 clears

        await asyncio.sleep(0.1)
        fake.present = []  # pail 2 has no readable tag
        fake.in1_high = False
        await asyncio.sleep(0.1)
        fake.in1_high = True

        await asyncio.wait_for(task, timeout=5.0)

    tagged, empty = windows
    assert tagged.epcs == (PAIL.hex(),)
    assert tagged.port == 1
    assert empty.empty  # a pail went by with nothing on it — surfaced, not lost
    assert empty.opened_at > tagged.closed_at
    # the reader only ever inventoried while the pin was active
    assert fake.inventories_while_idle == 0
    assert p.SET_WORK_MODE in fake.commands  # answering mode was selected on start
    assert p.GPIO_GET in fake.commands


async def test_wyuan_windows_requires_gpi_trigger() -> None:
    fake = GatedFakeSerial()
    async with WyuanReader(reader_id="x", transport=fake) as reader:
        assert reader.capabilities.gpi_trigger is False
        with pytest.raises(RuntimeError, match="gpi_trigger"):
            async for _ in reader.windows():
                pass


async def test_wyuan_windows_apply_policy_and_active_high() -> None:
    fake = GatedFakeSerial()
    fake.in1_high = False  # opposite wiring: idle low, active high
    reader = WyuanReader(
        reader_id="line-9",
        transport=fake,
        gpi_trigger=True,
        gpi_active_high=True,
        scan_time=1,
        gpi_poll_interval=0.005,
    )
    catalog = ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles"),
        ]
    )
    policy = ReaderPolicy(
        catalog=catalog, antennas={1: AntennaPolicy(mode="allow", categories={"pails"})}
    )
    async with reader:
        got: list[InventoryWindow] = []

        async def collect() -> None:
            async for w in reader.windows(policy=policy):
                got.append(w)
                return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        fake.present = [PAIL, PICKLE]
        fake.in1_high = True  # trip
        await asyncio.sleep(0.15)
        fake.in1_high = False  # release
        await asyncio.wait_for(task, timeout=5.0)
    assert got[0].epcs == (PAIL.hex(),)  # pickles filtered by the shared policy
    assert got[0].tags[0].category == "pails"


async def test_fleet_windows_merge_impinj_and_wyuan_per_station() -> None:
    emu = LLRPEmulator(reads_per_sec=300.0, seed=5)
    emu.tags = [EmulatedTag(epc=PICKLE, antennas=(1,), rssi_dbm=-45.0)]
    await emu.start()
    fake = GatedFakeSerial()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="dock", gpi_trigger=1) as dock,
            WyuanReader(
                reader_id="line-4",
                transport=fake,
                gpi_trigger=True,
                scan_time=1,
                gpi_poll_interval=0.005,
            ) as line,
        ):
            fleet = Fleet([dock, line])
            assert all(c.gpi_trigger for c in fleet.capabilities)
            seen: dict[str, InventoryWindow] = {}

            async def collect() -> None:
                async for sw in fleet.windows(settle=0.05):
                    seen[sw.reader_id] = sw.window
                    if len(seen) == 2:
                        return

            task = asyncio.create_task(collect())
            await asyncio.sleep(0.2)
            # both photo eyes trip, on different readers, differently wired
            await emu.set_gpi(1, True)  # R700: voltage applied = active
            fake.present = [PAIL]
            fake.in1_high = False  # WYUAN: pulled low = active
            await asyncio.sleep(0.3)
            await emu.set_gpi(1, False)
            fake.in1_high = True
            await asyncio.wait_for(task, timeout=5.0)
    finally:
        await emu.stop()

    assert seen["dock"].epcs == (PICKLE.hex(),)
    assert seen["line-4"].epcs == (PAIL.hex(),)


async def test_fleet_windows_rejects_ungated_reader() -> None:
    fake = GatedFakeSerial()
    async with WyuanReader(reader_id="plain", transport=fake) as plain:
        fleet = Fleet([plain])
        with pytest.raises(RuntimeError, match="plain"):
            async for _ in fleet.windows():
                pass


async def test_inventory_stream_ignores_edges() -> None:
    # Even on a gated reader, the flat inventory() stream is just tags.
    fake = GatedFakeSerial()
    fake.present = [PAIL]
    fake.in1_high = False
    reader = WyuanReader(
        reader_id="line-4", transport=fake, gpi_trigger=True, scan_time=1, gpi_poll_interval=0.005
    )
    async with reader:
        stream = reader.inventory(max_tags=2)
        async with contextlib.aclosing(stream):  # type: ignore[type-var]
            tags = [t async for t in stream]
    assert [t.epc for t in tags] == [PAIL, PAIL]
