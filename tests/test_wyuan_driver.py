"""WyuanReader driven through a fake serial port — no hardware needed.

Proves the driver polls, parses, and normalizes real UHFReader288 frames into
``TagReport``s, and that it drops into a fleet beside an LLRP reader under one
shared ignore policy — the whole mixed-fleet thesis, executed.
"""

from __future__ import annotations

import contextlib
import threading

from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy, TagReport
from llrpkit.emulator import LLRPEmulator

from omnitag import Fleet, LLRPDriver, WyuanReader
from omnitag.drivers.wyuan import protocol as p

PAIL = bytes.fromhex("e200aa00000000000000000a")
PICKLE = bytes.fromhex("e200bb00000000000000000b")


def make_inventory_response(
    epcs: list[bytes], *, antenna_byte: int = 0x01, status: int = p.ST_DONE, adr: int = 0
) -> bytes:
    """Build a real 0x01 inventory response frame carrying the given EPCs."""
    data = bytearray([antenna_byte, len(epcs)])
    for epc in epcs:
        data += bytes([len(epc)]) + epc + bytes([0x50])  # len | EPC | RSSI
    body = bytes([len(data) + 5, adr, p.INVENTORY, status]) + bytes(data)  # Len = Data + 5
    crc = p.crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class FakeSerial:
    """Minimal serial stand-in: each inventory command yields a canned response."""

    def __init__(self, response: bytes) -> None:
        self._response = response
        self._buf = bytearray()
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int:
        with self._lock:
            self._buf.extend(self._response)  # a poll → a fresh response
        return len(data)

    def read(self, size: int) -> bytes:
        with self._lock:
            if not self._buf:
                return b""
            take = self._buf[:size]
            del self._buf[:size]
            return bytes(take)

    def close(self) -> None:
        pass


async def _collect(driver: WyuanReader, n: int) -> list[TagReport]:
    seen: list[TagReport] = []
    stream = driver.inventory(max_tags=n)
    async with contextlib.aclosing(stream):  # type: ignore[type-var]
        async for tag in stream:
            seen.append(tag)
    return seen


async def test_wyuan_driver_streams_parsed_tags() -> None:
    fake = FakeSerial(make_inventory_response([PAIL, PICKLE]))
    driver = WyuanReader(reader_id="wyuan-1", transport=fake, antenna_count=4)
    async with driver:
        assert driver.capabilities.kind == "wyuan"
        assert driver.capabilities.isolation == "thread"
        tags = await _collect(driver, 4)
    assert {t.epc.hex() for t in tags} == {PAIL.hex(), PICKLE.hex()}
    assert all(t.antenna == 1 for t in tags)  # antenna byte 0x01


async def test_wyuan_multiframe_status_more() -> None:
    # 0x03 (more follow) then 0x01 (done): the driver must keep reading.
    first = make_inventory_response([PAIL], status=p.ST_MORE)
    second = make_inventory_response([PICKLE], status=p.ST_DONE)

    class TwoFrameSerial(FakeSerial):
        def write(self, data: bytes) -> int:  # both frames arrive for one poll
            with self._lock:
                self._buf.extend(first + second)
            return len(data)

    driver = WyuanReader(reader_id="wyuan-1", transport=TwoFrameSerial(b""))
    async with driver:
        tags = await _collect(driver, 2)
    assert {t.epc.hex() for t in tags} == {PAIL.hex(), PICKLE.hex()}


async def test_wyuan_and_llrp_in_one_fleet_under_one_policy() -> None:
    emu = LLRPEmulator(reads_per_sec=400.0, seed=9)
    await emu.start()
    fake = FakeSerial(make_inventory_response([PAIL, PICKLE], antenna_byte=0x01))
    catalog = ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles-fresh"),
        ]
    )
    # antenna 1 (the WYUAN's) allows only pails
    policy = ReaderPolicy(
        catalog=catalog, antennas={1: AntennaPolicy(mode="allow", categories={"pails"})}
    )
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="impinj") as llrp,
            WyuanReader(reader_id="wyuan", transport=fake) as wy,
        ):
            fleet = Fleet([llrp, wy])
            kinds = {c.reader_id: c.kind for c in fleet.capabilities}
            assert kinds == {"impinj": "llrp", "wyuan": "wyuan"}

            saw = {"impinj": 0, "wyuan": 0}
            wyuan_epcs: set[str] = set()
            stream = fleet.stream(max_tags=10_000, duration=6.0, policy=policy)
            async with contextlib.aclosing(stream):  # type: ignore[type-var]
                async for s in stream:
                    saw[s.reader_id] += 1
                    if s.reader_id == "wyuan":
                        wyuan_epcs.add(s.tag.epc.hex())
                    if saw["wyuan"] >= 3 and saw["impinj"] >= 3:
                        break
    finally:
        await emu.stop()

    assert saw["impinj"] >= 3 and saw["wyuan"] >= 3  # both readers in one stream
    # the shared policy dropped the WYUAN's pickles on antenna 1
    assert wyuan_epcs == {PAIL.hex()}


def make_realtime_frame(epc: bytes, *, antenna_byte: int = 0x01, adr: int = 0) -> bytes:
    """Build a 0xEE/0x00 push frame (real-time mode): Ant, Len, EPC, RSSI — no Num."""
    data = bytes([antenna_byte, len(epc)]) + epc + bytes([0x48])
    body = bytes([len(data) + 5, adr, p.REALTIME, p.RT_TAG]) + data
    crc = p.crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def make_heartbeat_frame(*, adr: int = 0) -> bytes:
    """A 0xEE/0x28 heartbeat: PacketNo(4), AntStatus(4), TotalCount(4)."""
    data = bytes(4) + bytes([1, 0, 0, 0]) + bytes(4)
    body = bytes([len(data) + 5, adr, p.REALTIME, p.RT_HEARTBEAT]) + data
    crc = p.crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


async def test_wyuan_driver_consumes_realtime_push_mode() -> None:
    # A reader left in real-time mode ignores our poll and streams 0xEE frames,
    # interleaved with heartbeats. The driver must yield the tags and skip the rest.
    pushed = make_heartbeat_frame() + make_realtime_frame(PAIL) + make_realtime_frame(PICKLE)
    driver = WyuanReader(reader_id="wyuan-rt", transport=FakeSerial(pushed))
    async with driver:
        tags = await _collect(driver, 2)
    assert {t.epc.hex() for t in tags} == {PAIL.hex(), PICKLE.hex()}
    assert all(t.rssi_dbm is None for t in tags)  # raw RSSI is never passed off as dBm


async def test_wyuan_driver_decodes_index_antenna_on_16_port_reader() -> None:
    # On a 16-port unit the Ant byte is a 0-based index: 0x0B → antenna 12.
    fake = FakeSerial(make_inventory_response([PAIL], antenna_byte=0x0B))
    driver = WyuanReader(reader_id="wyuan-16", transport=fake, antenna_count=16)
    async with driver:
        tags = await _collect(driver, 1)
    assert tags[0].antenna == 12


async def test_wyuan_driver_surfaces_fast_id_tid() -> None:
    tid = bytes.fromhex("e28011702000000000000001")
    data = bytearray([0x01, 0x01, 0x80 | (len(PAIL) + len(tid))]) + PAIL + tid + bytes([0x50])
    body = bytes([len(data) + 5, 0, p.INVENTORY, p.ST_DONE]) + bytes(data)
    crc = p.crc16(body)
    frame = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    driver = WyuanReader(reader_id="wyuan-fid", transport=FakeSerial(frame), fast_id=True)
    async with driver:
        tags = await _collect(driver, 1)
    assert tags[0].epc == PAIL and tags[0].tid == tid
