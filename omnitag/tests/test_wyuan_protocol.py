"""UHFReader288 serial protocol codec — verified without hardware."""

from __future__ import annotations

import pytest

from omnitag.drivers.wyuan import protocol as p


def _framed(len_adr_cmd_data: bytes) -> bytes:
    """Append a correct CRC to a raw [Len..Data] body (helper for building frames)."""
    crc = p.crc16(len_adr_cmd_data)
    return len_adr_cmd_data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def test_crc_self_consistency() -> None:
    # A frame's CRC recomputed over the whole frame (incl. its own CRC) is zero.
    frame = p.build_command(0x21, b"")
    assert p.crc16(frame) == 0


def test_build_command_shape() -> None:
    cmd = p.build_command(p.INVENTORY, bytes([0x04, 0x00]))
    assert cmd[0] == 0x06  # Len = len(data) + 4 = 2 + 4
    assert cmd[1] == p.DEFAULT_ADR
    assert cmd[2] == p.INVENTORY
    assert p.crc16(cmd) == 0


def test_build_inventory_optional_antenna_params() -> None:
    plain = p.build_inventory(q_value=4, session=0)
    assert plain[0] == 0x06  # Len = 2 (QValue, Session) + 4
    with_ant = p.build_inventory(antenna=3, scan_time=2)
    # QValue, Session, Target, Ant(0x82 for antenna 3), ScanTime → 5 data bytes
    assert with_ant[0] == 0x09
    assert 0x82 in with_ant  # 0x80 + (3 - 1)


def test_parse_frame_roundtrip_and_crc_error() -> None:
    # Response: Len, Adr, reCmd, Status, Data[](Ant, Num), CRC. Len = Data(2) + 5 = 7.
    good = _framed(bytes([0x07, 0x00, p.INVENTORY, p.ST_DONE, 0x00, 0x00]))
    frame = p.parse_frame(good)
    assert frame.re_cmd == p.INVENTORY
    assert frame.status == p.ST_DONE
    assert frame.data == bytes([0x00, 0x00])  # Ant, Num

    bad = bytearray(good)
    bad[-1] ^= 0xFF  # corrupt the CRC
    with pytest.raises(p.ProtocolError):
        p.parse_frame(bytes(bad))


def test_parse_inventory_multiple_tags() -> None:
    # Data[] = Ant(0x04 → antenna 3), Num=2, then two EPC blocks: len | EPC | RSSI
    epc_a = bytes.fromhex("e200aa00000000000000000a")  # 12 bytes
    epc_b = bytes.fromhex("e200bb00000000000000000b")
    block_a = bytes([len(epc_a)]) + epc_a + bytes([0x50])  # RSSI 0x50
    block_b = bytes([len(epc_b)]) + epc_b + bytes([0x4A])
    data = bytes([0x04, 0x02]) + block_a + block_b

    tags, ant_byte = p.parse_inventory(data)
    assert ant_byte == 0x04
    assert [t.epc.hex() for t in tags] == [epc_a.hex(), epc_b.hex()]
    assert all(t.antenna == 3 for t in tags)  # 0x04 bitmask → antenna 3
    assert tags[0].rssi_raw == 0x50


def test_parse_inventory_skips_phase_freq_block() -> None:
    epc = bytes.fromhex("e200cc000000000000000000")
    length = 0x40 | len(epc)  # bit6 set → phase(4)+freq(3) trailer present
    block = bytes([length]) + epc + bytes([0x55]) + bytes(7)  # RSSI + 7 trailer bytes
    data = bytes([0x01, 0x01]) + block
    tags, _ = p.parse_inventory(data)
    assert len(tags) == 1
    assert tags[0].epc == epc
    assert tags[0].antenna == 1  # 0x01 → antenna 1


def test_antenna_mapping() -> None:
    assert p.antenna_from_byte(0x01) == 1
    assert p.antenna_from_byte(0x04) == 3
    assert p.antenna_from_byte(0x08) == 4
    assert p.antenna_from_byte(0x00) is None


def test_status_helpers() -> None:
    assert p.status_carries_tags(p.ST_DONE)
    assert p.status_carries_tags(p.ST_MORE)
    assert not p.status_carries_tags(p.ST_STATISTIC)
