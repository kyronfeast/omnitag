"""UHFReader288-family serial protocol codec (pure, hardware-free).

In plain words: a serial reader and the computer talk to each other in little
packets of bytes, like short coded telegrams. This file is the "phrasebook" — it
knows how to *write* a request ("please list the tags you see") and how to *read*
the reply back into normal data. It's pure translation with no hardware involved,
so every rule in it can be tested on its own. The `driver.py` next door uses this
phrasebook to actually talk to a reader over the cable.


This is the wire format documented in the "UHF RFID Reader Series User Manual
V2.20", cross-checked against the vendor's own SDK — the ``UHFReader288.DLL``
manual V3.0 and the shipped C++ (``Page1.cpp``) and C# (``RWDev.cs``) demo code.
A byte-framed, CRC16-checked request/response protocol over serial (default
57600 8N1, no parity, LSB first):

    Command  (host→reader):  Len  Adr  Cmd            Data[]  CRC_L CRC_H
    Response (reader→host):  Len  Adr  reCmd  Status  Data[]  CRC_L CRC_H

`Len` counts every byte after itself (so a full frame on the wire is `Len + 1`
bytes). CRC16 is computed over `Len..Data[]` (everything but the two CRC bytes)
with the manual's exact algorithm and appended little-endian.

Everything here is pure functions over bytes, so the whole protocol is tested
without a serial port — the same zero-hardware philosophy as llrpkit's emulator.

Three fields were once marked VERIFY. They are now settled against the vendor
sources (see ``docs/wyuan-protocol.md`` for the citations):

* EPC length is a **byte** count — manual §8.4.22 says so outright, and both
  demos walk the buffer byte-wise.
* The antenna byte is a one-hot **bitmask** on 1/4/8-port readers and a plain
  **0-based index** on 12/16-port readers (:func:`antenna_from_byte`).
* RSSI is a **raw** one-byte reading; the vendor demo prints it as-is, with no
  dBm conversion.
"""

from __future__ import annotations

from dataclasses import dataclass

INVENTORY = 0x01
BROADCAST_ADR = 0xFF
DEFAULT_ADR = 0x00

#: reCmd of frames a reader pushes on its own in *real-time inventory mode*
#: (manual §8.4.22). Such a reader ignores 0x01 polls and streams instead.
REALTIME = 0xEE

# Response Status values for the 0x01 inventory command.
ST_DONE = 0x01  # all tags reported
ST_TIMEOUT = 0x02  # inventory timed out; tags so far are still valid
ST_MORE = 0x03  # more tags follow in the next frame(s)
ST_MEM_FULL = 0x04  # partial: reader ran out of memory
ST_STATISTIC = 0x26  # statistic packet (no EPCs) — Ant, ReadRate, TotalCount
ST_ANT_ERROR = 0xF8  # antenna disconnected

# Status values for REALTIME (0xEE) push frames.
RT_TAG = 0x00  # Data[] = Ant, Len, EPC/TID, RSSI
RT_HEARTBEAT = 0x28  # Data[] = PacketNo(4), AntStatus(1/4/8/16), TotalCount(4)

# Statuses whose Data[] carries tags (Ant, Num, EPC blocks).
_TAG_STATUSES = frozenset({ST_DONE, ST_TIMEOUT, ST_MORE, ST_MEM_FULL})

# QValue byte layout (manual §8.2.1): flags in the high nibble, Q in the low.
QF_STATISTICS = 0x80  # bit7: send a 0x26 statistic packet after the inventory
QF_STRATEGY = 0x40  # bit6: "special strategy" (vendor-defined; leave off)
QF_FAST_ID = 0x20  # bit5: Impinj FastID — EPC + TID in one block
QF_PHASE = 0x10  # bit4: append phase(4) + freq(3) after each RSSI

#: Bytes of TID appended to the EPC in a FastID block (manual §8.2.1).
FAST_ID_TID_LEN = 12

MAX_ANTENNA = 16  # Ant selector 0x80 (ant 1) .. 0x8F (ant 16)


def crc16(data: bytes) -> int:
    """CRC16 exactly as the manual's C reference (poly 0x8408, preset 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_command(cmd: int, data: bytes = b"", *, adr: int = DEFAULT_ADR) -> bytes:
    """Frame a host→reader command: Len, Adr, Cmd, Data, CRC(LSB,MSB)."""
    body = bytes([len(data) + 4, adr, cmd]) + data  # Len = Data + 4
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_inventory(
    *,
    q_value: int = 4,
    session: int = 0,
    adr: int = DEFAULT_ADR,
    antenna: int | None = None,
    scan_time: int | None = None,
    target: int = 0,
    fast_id: bool = False,
    phase: bool = False,
    statistics: bool = False,
) -> bytes:
    """Build a 0x01 inventory command.

    Minimal form sends just ``QValue, Session``. If ``antenna`` is given, the
    manual requires the optional trio ``Target, Ant, ScanTime`` together (the
    DLL calls this "express inventory", ``FastFlag=1``), so we emit all three.
    Antenna is 1-based and maps to the reader's ``0x80 + n - 1``. ``scan_time``
    is in units of 100 ms; ``0`` means "no limit" (DLL manual §3.2.1).

    The ``QValue`` byte carries flag bits above the 4-bit Q: ``fast_id`` asks
    Impinj Monza tags for EPC+TID in one block, ``phase`` appends phase and
    frequency to every tag, ``statistics`` requests a trailing ``0x26`` packet.
    """
    if not 0 <= q_value <= 15:
        raise ValueError(f"q_value must be 0-15; got {q_value}")
    if session not in (0, 1, 2, 3, 0xFF):
        raise ValueError(f"session must be 0-3 or 0xFF (smart); got {session}")
    q_byte = q_value
    if fast_id:
        q_byte |= QF_FAST_ID
    if phase:
        q_byte |= QF_PHASE
    if statistics:
        q_byte |= QF_STATISTICS
    data = bytes([q_byte, session & 0xFF])
    if antenna is not None:
        if not 1 <= antenna <= MAX_ANTENNA:
            raise ValueError(f"antenna must be 1-{MAX_ANTENNA}; got {antenna}")
        ant_code = 0x80 + (antenna - 1)  # 0x80 = ant 1, 0x81 = ant 2, ... 0x8F = 16
        scan = 2 if scan_time is None else scan_time
        data += bytes([target & 0xFF, ant_code, scan & 0xFF])
    return build_command(INVENTORY, data, adr=adr)


@dataclass(frozen=True)
class Frame:
    """A parsed, CRC-verified response frame."""

    adr: int
    re_cmd: int
    status: int
    data: bytes


class ProtocolError(Exception):
    """Malformed or CRC-failed frame."""


def parse_frame(frame: bytes) -> Frame:
    """Parse and CRC-check one complete response frame (leading Len .. trailing CRC)."""
    if len(frame) < 5:
        raise ProtocolError(f"frame too short: {len(frame)} bytes")
    declared = frame[0]
    if len(frame) != declared + 1:
        raise ProtocolError(f"length mismatch: Len={declared}, got {len(frame) - 1} following")
    if crc16(frame) != 0:  # CRC over the whole frame (incl. its CRC) is 0 when valid
        raise ProtocolError("CRC16 check failed")
    return Frame(adr=frame[1], re_cmd=frame[2], status=frame[3], data=frame[4:-2])


@dataclass(frozen=True)
class InventoryTag:
    """One tag from an inventory response."""

    epc: bytes
    antenna: int | None
    rssi_raw: int  # raw reader units, NOT calibrated dBm (vendor demo prints it as-is)
    tid: bytes | None = None  # present only for FastID blocks (len bit7 set)


def antenna_from_byte(ant: int, *, antenna_count: int = 4) -> int | None:
    """Map the response Ant byte to a 1-based antenna number.

    Settled against the vendor docs: readers with **1/4/8 ports** send a one-hot
    bitmask (``0x04`` → antenna 3; a multi-bit value such as ``0x05`` means the
    tag was seen on several — we report the highest). Readers with **12 or 16
    ports** send a plain 0-based index (``0`` → antenna 1). ``antenna_count``
    picks the decoding; anything above 8 ports is index mode.
    """
    if antenna_count > 8:
        return ant + 1
    if ant == 0:
        return None
    return ant.bit_length()


def _parse_tag_block(data: bytes, i: int, antenna: int | None) -> tuple[InventoryTag, int]:
    """Parse one ``len | EPC(N) | RSSI [| phase(4) freq(3)]`` block at ``data[i]``.

    ``len`` bit7 = FastID (the N bytes are EPC followed by a 12-byte TID), bit6 =
    phase/freq trailer present, bits 5-0 = N in **bytes**. Returns the tag and
    the index just past the block.
    """
    if i >= len(data):
        raise ProtocolError("inventory data truncated before EPC block")
    length = data[i]
    i += 1
    has_tid = bool(length & 0x80)
    has_phase_freq = bool(length & 0x40)
    n = length & 0x3F  # byte count (manual §8.4.22; both vendor demos agree)
    payload = data[i : i + n]
    if len(payload) != n:
        raise ProtocolError("inventory data truncated inside EPC")
    i += n
    if i >= len(data):
        raise ProtocolError("inventory data truncated before RSSI")
    rssi = data[i]
    i += 1
    if has_phase_freq:
        if i + 7 > len(data):
            raise ProtocolError("inventory data truncated inside phase/freq trailer")
        i += 7  # phase (4) + freq (3)
    tid: bytes | None = None
    epc = bytes(payload)
    if has_tid and n > FAST_ID_TID_LEN:
        epc, tid = bytes(payload[:-FAST_ID_TID_LEN]), bytes(payload[-FAST_ID_TID_LEN:])
    return InventoryTag(epc=epc, antenna=antenna, rssi_raw=rssi, tid=tid), i


def parse_inventory(data: bytes, *, antenna_count: int = 4) -> tuple[list[InventoryTag], int]:
    """Parse a tag-bearing 0x01 inventory Data[]: ``Ant, Num``, then Num EPC blocks.

    Returns ``(tags, antenna_byte)``. See :func:`_parse_tag_block` for the block
    layout and :func:`antenna_from_byte` for how ``antenna_count`` decodes Ant.
    """
    if len(data) < 2:
        raise ProtocolError("inventory data missing Ant/Num header")
    ant_byte = data[0]
    num = data[1]
    antenna = antenna_from_byte(ant_byte, antenna_count=antenna_count)
    tags: list[InventoryTag] = []
    i = 2
    for _ in range(num):
        tag, i = _parse_tag_block(data, i, antenna)
        tags.append(tag)
    return tags, ant_byte


def parse_realtime_tag(data: bytes, *, antenna_count: int = 4) -> InventoryTag:
    """Parse the Data[] of a ``0xEE``/status ``0x00`` push frame: one tag.

    Real-time mode frames carry exactly one tag and **no Num byte** — the layout
    is ``Ant, Len, EPC/TID(Len), RSSI [| phase(4) freq(3)]`` (manual §8.4.22,
    and what the vendor's C# demo parses in ``RWDev.workProcess``).
    """
    if len(data) < 3:
        raise ProtocolError("real-time frame too short")
    antenna = antenna_from_byte(data[0], antenna_count=antenna_count)
    tag, _ = _parse_tag_block(data, 1, antenna)
    return tag


@dataclass(frozen=True)
class InventoryStatistics:
    """The optional ``0x26`` statistic packet (requested via ``statistics=True``)."""

    antenna_byte: int
    read_rate: int  # successful identifications per second, incl. repeats
    total_count: int  # tags detected in the inventory, incl. repeats


def parse_statistics(data: bytes) -> InventoryStatistics:
    """Parse a ``0x26`` Data[]: ``Ant(1), ReadRate(2), TotalCount(4)``, big-endian."""
    if len(data) < 7:
        raise ProtocolError("statistic packet too short")
    return InventoryStatistics(
        antenna_byte=data[0],
        read_rate=int.from_bytes(data[1:3], "big"),
        total_count=int.from_bytes(data[3:7], "big"),
    )


def status_carries_tags(status: int) -> bool:
    return status in _TAG_STATUSES
