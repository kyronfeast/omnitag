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


def test_antenna_mapping_bitmask_for_small_readers() -> None:
    # 1/4/8-port readers: one-hot bitmask (manual §8.2.1: 0x04 → antenna 3)
    assert p.antenna_from_byte(0x01) == 1
    assert p.antenna_from_byte(0x04) == 3
    assert p.antenna_from_byte(0x08) == 4
    assert p.antenna_from_byte(0x00) is None
    assert p.antenna_from_byte(0x80, antenna_count=8) == 8


def test_antenna_mapping_index_for_large_readers() -> None:
    # 12/16-port readers: plain 0-based index (DLL manual §3.2.1, manual §8.2.1)
    assert p.antenna_from_byte(0x00, antenna_count=16) == 1
    assert p.antenna_from_byte(0x0F, antenna_count=16) == 16
    assert p.antenna_from_byte(0x0B, antenna_count=12) == 12
    # parse_inventory threads antenna_count through
    epc = bytes.fromhex("e200dd000000000000000000")
    data = bytes([0x0B, 0x01, len(epc)]) + epc + bytes([0x40])
    tags, _ = p.parse_inventory(data, antenna_count=16)
    assert tags[0].antenna == 12


def test_epc_length_is_a_byte_count() -> None:
    # Manual §8.4.22: "Len: 1 byte, the byte length of the EPC/TID". A 12-byte
    # EPC is announced as 0x0C, not 0x06 words — parse must consume exactly 12.
    epc = bytes.fromhex("30395dfa4c0000000000000a")
    data = bytes([0x01, 0x01, 0x0C]) + epc + bytes([0x33])
    tags, _ = p.parse_inventory(data)
    assert tags[0].epc == epc and tags[0].rssi_raw == 0x33


def test_fast_id_block_splits_epc_and_tid() -> None:
    # bit7 set: block is EPC + 12-byte TID, N = total length (manual §8.2.1)
    epc = bytes.fromhex("e200aa00000000000000000a")
    tid = bytes.fromhex("e28011702000000000000001")
    length = 0x80 | (len(epc) + len(tid))
    data = bytes([0x01, 0x01, length]) + epc + tid + bytes([0x5A])
    tags, _ = p.parse_inventory(data)
    assert tags[0].epc == epc
    assert tags[0].tid == tid
    # a plain block has no TID
    plain = bytes([0x01, 0x01, len(epc)]) + epc + bytes([0x5A])
    assert p.parse_inventory(plain)[0][0].tid is None


def test_build_inventory_q_flags_and_validation() -> None:
    fast = p.build_inventory(q_value=4, fast_id=True, phase=True, statistics=True)
    q_byte = fast[3]  # Len, Adr, Cmd, then QValue
    assert q_byte & 0x0F == 4
    assert q_byte & p.QF_FAST_ID and q_byte & p.QF_PHASE and q_byte & p.QF_STATISTICS
    with pytest.raises(ValueError):
        p.build_inventory(q_value=16)  # Q is 4 bits
    with pytest.raises(ValueError):
        p.build_inventory(session=7)
    with pytest.raises(ValueError):
        p.build_inventory(antenna=17)
    # scan_time=0 means unlimited and must be sent as 0, not defaulted
    unlimited = p.build_inventory(antenna=1, scan_time=0)
    assert unlimited[3 + 4] == 0x00  # QValue, Session, Target, Ant, ScanTime
    assert p.build_inventory(antenna=16)[3 + 3] == 0x8F


def test_parse_realtime_push_frame() -> None:
    # 0xEE / 0x00 frames carry ONE tag with no Num byte: Ant, Len, EPC, RSSI
    epc = bytes.fromhex("e200ee000000000000000000")
    data = bytes([0x05, len(epc)]) + epc + bytes([0x48])  # Ant 0x05 → ants 1 & 3
    tag = p.parse_realtime_tag(data)
    assert tag.epc == epc and tag.rssi_raw == 0x48 and tag.antenna == 3
    with pytest.raises(p.ProtocolError):
        p.parse_realtime_tag(b"\x01\x0c")  # truncated


def test_parse_statistics_packet() -> None:
    # 0x26: Ant(1), ReadRate(2), TotalCount(4), big-endian
    stats = p.parse_statistics(bytes([0x01, 0x01, 0x2C, 0x00, 0x00, 0x03, 0xE8]))
    assert stats.antenna_byte == 1
    assert stats.read_rate == 300
    assert stats.total_count == 1000
    with pytest.raises(p.ProtocolError):
        p.parse_statistics(b"\x01\x02")


def test_truncated_blocks_raise() -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_inventory(bytes([0x01, 0x01, 0x0C, 0xAA]))  # EPC cut short
    with pytest.raises(p.ProtocolError):
        p.parse_inventory(bytes([0x01, 0x01, 0x41, 0xAA, 0x50]))  # phase trailer missing


def test_status_helpers() -> None:
    assert p.status_carries_tags(p.ST_DONE)
    assert p.status_carries_tags(p.ST_MORE)
    assert not p.status_carries_tags(p.ST_STATISTIC)
