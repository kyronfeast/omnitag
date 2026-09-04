"""ZPL RFID codec — verified without a printer."""

from __future__ import annotations

import pytest

from omnitag.printers import zpl

EPC96 = "E28011700000020000000001"  # 24 hex chars = 96 bits


def test_normalize_accepts_bytes_and_hex() -> None:
    assert zpl.normalize_epc(bytes.fromhex(EPC96)) == EPC96
    assert zpl.normalize_epc(EPC96.lower()) == EPC96
    assert zpl.normalize_epc("e280 1170 0000") == "E28011700000"


def test_normalize_rejects_bad_input() -> None:
    with pytest.raises(zpl.ZPLError):
        zpl.normalize_epc("XYZ")  # not hex
    with pytest.raises(zpl.ZPLError):
        zpl.normalize_epc("ABC")  # odd length
    with pytest.raises(zpl.ZPLError):
        zpl.normalize_epc("")


def test_build_encode_has_the_rfid_write_command() -> None:
    job = zpl.build_encode(EPC96).decode()
    assert job.startswith("^XA")
    assert job.strip().endswith("^XZ")
    assert "^RS8" in job
    assert f"^RFW,H,,,E^FD{EPC96}^FS" in job  # write, hex, EPC-96 bank


def test_build_encode_optional_text_and_barcode() -> None:
    job = zpl.build_encode(EPC96, human_text="PAIL #42", barcode=True).decode()
    assert "^FDPAIL #42^FS" in job
    assert f"^BCN,100,Y,N,N^FD{EPC96}^FS" in job  # Code 128 of the EPC


def test_bank_e_enforces_epc96_length() -> None:
    with pytest.raises(zpl.ZPLError, match="EPC-96"):
        zpl.build_encode("E28011", bank="E")  # too short for the E bank
    # bank A accepts other lengths
    job = zpl.build_encode("E28011", bank="A").decode()
    assert "^RFW,H,,,A^FDE28011^FS" in job


def test_build_read() -> None:
    job = zpl.build_read(field=1).decode()
    assert "^RFR,H,,,E^FN1^FS" in job
    assert "^HV1,,EPC:^FS" in job  # host verification returns the read value


def test_encode_with_void_retry_and_position() -> None:
    job = zpl.build_encode(EPC96, retry=2, error_action="P", program_position="F0").decode()
    # ^RSt,p,v,n,e  ->  tag 8, position F0, void skip, retry 2, error Pause
    assert "^RS8,F0,,2,P" in job


def test_rs_defaults_to_bare_rs8() -> None:
    assert zpl.build_rs() == "^RS8"
    assert zpl.build_rs(retry=5) == "^RS8,,,5"


def test_rs_validates_params() -> None:
    with pytest.raises(zpl.ZPLError):
        zpl.build_rs(retry=99)  # out of 1-10 range
    with pytest.raises(zpl.ZPLError):
        zpl.build_rs(error_action="Z")  # not N/P/E
