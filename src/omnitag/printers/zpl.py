"""ZPL RFID codec for Zebra Link-OS printers (pure, hardware-free).

In plain words: a Zebra RFID printer is told what to do with little text programs
called **ZPL**. This file writes those programs — most importantly the one that
says "print this label *and* burn this EPC number into the tag inside it." It's
pure text-building with no printer attached, so every rule here is testable on
its own; `zebra.py` next door opens the network socket and sends what this builds.

The RFID write command is ``^RFW,o,f,b,n,m`` inside an ``^XA … ^XZ`` label:

* ``o`` operation — ``W`` write, ``R`` read
* ``f`` format — ``H`` hex, ``A`` ASCII
* ``b`` block, ``n`` byte count — left default here
* ``m`` Gen2 memory bank — ``E`` EPC 96-bit, ``A`` EPC (auto PC bits), ``1`` EPC,
  ``2`` TID, ``3`` User

A canonical "encode a hex EPC" label (straight from Zebra's ZPL guide):

    ^XA
    ^RS8
    ^RFW,H,,,E^FD1122334455667788^FS
    ^XZ

VERIFY on the physical ZT411: the exact memory-bank code and whether ``^RS8`` is
needed can vary by firmware/label setup — both are isolated here so a mismatch is
a one-line change (see ``bank`` and ``session_setup``).
"""

from __future__ import annotations

#: An EPC-96 is 96 bits = 24 hex characters; the "E" bank expects exactly this.
EPC96_HEX_LEN = 24


class ZPLError(Exception):
    """Malformed input for a ZPL RFID command (bad EPC, bank mismatch, …)."""


def normalize_epc(epc: bytes | str) -> str:
    """Accept an EPC as bytes or a hex string; return clean uppercase hex.

    Raises :class:`ZPLError` if it isn't valid, even-length hexadecimal.
    """
    if isinstance(epc, bytes):
        return epc.hex().upper()
    text = epc.strip().replace(" ", "").upper()
    if not text or len(text) % 2 != 0:
        raise ZPLError(f"EPC must be non-empty, even-length hex; got {epc!r}")
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise ZPLError(f"EPC is not valid hex: {epc!r}") from exc
    return text


def build_encode(
    epc: bytes | str,
    *,
    bank: str = "E",
    human_text: str | None = None,
    barcode: bool = False,
    origin: tuple[int, int] = (50, 50),
    session_setup: bool = True,
) -> bytes:
    """Build a ZPL label that encodes ``epc`` into the tag and prints it.

    ``bank="E"`` targets the EPC 96-bit bank and so requires a 24-hex EPC; use
    ``bank="A"`` (auto PC bits) for other lengths. Optionally print the EPC as
    human-readable text and/or a Code 128 barcode on the label face.
    """
    epc_hex = normalize_epc(epc)
    if bank == "E" and len(epc_hex) != EPC96_HEX_LEN:
        raise ZPLError(
            f"bank 'E' (EPC-96) needs {EPC96_HEX_LEN} hex chars; got {len(epc_hex)}. "
            "Use bank='A' for other EPC lengths."
        )
    x, y = origin
    lines = ["^XA"]
    if session_setup:
        lines.append("^RS8")
    lines.append(f"^RFW,H,,,{bank}^FD{epc_hex}^FS")
    if human_text is not None:
        lines.append(f"^FO{x},{y}^A0N,40,40^FD{human_text}^FS")
    if barcode:
        lines.append(f"^FO{x},{y + 60}^BY2^BCN,100,Y,N,N^FD{epc_hex}^FS")
    lines.append("^XZ")
    return ("\n".join(lines) + "\n").encode("ascii")


def build_read(*, field: int = 1, bank: str = "E") -> bytes:
    """Build a ZPL job that reads the tag's EPC back and returns it to the host."""
    return (
        f"^XA^RFR,H,,,{bank}^FN{field}^FS^HV{field}^FS^XZ\n"
    ).encode("ascii")
