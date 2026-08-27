"""UHFReader288-family serial protocol codec (pure, hardware-free).

This is the wire format documented in the "UHF RFID Reader Series User Manual
V2.20": a byte-framed, CRC16-checked request/response protocol over serial
(default 57600 8N1, no parity, LSB first).

    Command  (host→reader):  Len  Adr  Cmd            Data[]  CRC_L CRC_H
    Response (reader→host):  Len  Adr  reCmd  Status  Data[]  CRC_L CRC_H

`Len` counts every byte after itself (so a full frame on the wire is `Len + 1`
bytes). CRC16 is computed over `Len..Data[]` (everything but the two CRC bytes)
with the manual's exact algorithm and appended little-endian.

Everything here is pure functions over bytes, so the whole protocol is tested
without a serial port — the same zero-hardware philosophy as llrpkit's emulator.

Three points are marked VERIFY: they're the fields most likely to need a tweak
against a physical reader (the manual is slightly ambiguous), and each is
isolated so a one-line change fixes it if field data disagrees.
"""

from __future__ import annotations

from dataclasses import dataclass

INVENTORY = 0x01
BROADCAST_ADR = 0xFF
DEFAULT_ADR = 0x00

# Response Status values for the 0x01 inventory command.
ST_DONE = 0x01  # all tags reported
ST_TIMEOUT = 0x02  # inventory timed out; tags so far are still valid
ST_MORE = 0x03  # more tags follow in the next frame(s)
ST_MEM_FULL = 0x04  # partial: reader ran out of memory
ST_STATISTIC = 0x26  # statistic packet (no EPCs) — Ant, ReadRate, TotalCount
ST_ANT_ERROR = 0xF8  # antenna disconnected

# Statuses whose Data[] carries tags (Ant, Num, EPC blocks).
_TAG_STATUSES = frozenset({ST_DONE, ST_TIMEOUT, ST_MORE, ST_MEM_FULL})


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
) -> bytes:
    """Build a 0x01 inventory command.

    Minimal form sends just QValue + Session. If `antenna` is given, the manual
    requires all three optional params together (Target, Ant, ScanTime), so we
    emit them as a set. Antenna is 1-based; it maps to the reader's 0x80+n-1.
    """
    data = bytes([q_value & 0xFF, session & 0xFF])
    if antenna is not None:
        ant_code = 0x80 + (antenna - 1)  # 0x80 = ant 1, 0x81 = ant 2, ...
        data += bytes([target & 0xFF, ant_code, (scan_time or 2) & 0xFF])
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
    rssi_raw: int  # VERIFY: raw reader units, NOT calibrated dBm (see driver)


def antenna_from_byte(ant: int) -> int | None:
    """Map the response Ant byte to a 1-based antenna number.

    VERIFY: for 1/4/8-port readers Ant is a one-hot bitmask (0x04 → antenna 3),
    which `bit_length()` decodes. 16-port readers instead send a plain 0..15
    index; if you run a 16-port unit, switch this to `ant + 1`.
    """
    if ant == 0:
        return None
    return ant.bit_length()


def parse_inventory(data: bytes) -> tuple[list[InventoryTag], int]:
    """Parse a tag-bearing inventory Data[]: Ant, Num, then Num EPC blocks.

    Returns (tags, antenna_byte). Each EPC block is:
        len(1) | EPC(N) | RSSI(1) [ | phase(4) + freq(3) if bit6 set ]
    where len bit7 = EPC+TID (FastID), bit6 = phase/freq present, bits5-0 = N.

    VERIFY: N is treated as a **byte** count (V2.x firmware). If first real
    reads come back half-length or misaligned, the reader is using word units —
    change `n = length & 0x3F` to `n = (length & 0x3F) * 2`.
    """
    if len(data) < 2:
        raise ProtocolError("inventory data missing Ant/Num header")
    ant_byte = data[0]
    num = data[1]
    antenna = antenna_from_byte(ant_byte)
    tags: list[InventoryTag] = []
    i = 2
    for _ in range(num):
        if i >= len(data):
            raise ProtocolError("inventory data truncated before EPC block")
        length = data[i]
        i += 1
        has_phase_freq = bool(length & 0x40)
        n = length & 0x3F  # VERIFY: byte count (see docstring)
        epc = data[i : i + n]
        i += n
        if i >= len(data):
            raise ProtocolError("inventory data truncated before RSSI")
        rssi = data[i]
        i += 1
        if has_phase_freq:
            i += 7  # phase (4) + freq (3)
        tags.append(InventoryTag(epc=bytes(epc), antenna=antenna, rssi_raw=rssi))
    return tags, ant_byte


def status_carries_tags(status: int) -> bool:
    return status in _TAG_STATUSES
