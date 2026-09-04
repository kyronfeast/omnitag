"""ZPL RFID codec for Zebra Link-OS printers (pure, hardware-free).

In plain words: a Zebra RFID printer is told what to do with little text programs
called **ZPL**. This file writes those programs — most importantly the one that
says "print this label *and* burn this EPC number into the tag inside it." It's
pure text-building with no printer attached, so every rule here is testable on
its own; `zebra.py` next door opens the network socket and sends what this builds.

Verified against Zebra's *ZPL & ZBI2 Programming Guide* (zpl-zbi2-pg-en). The RFID
write command is ``^RFo,f,b,n,m`` inside an ``^XA … ^XZ`` label:

* ``o`` operation — ``W`` write, ``R`` read (baked into ``^RFW`` / ``^RFR``)
* ``f`` **format** — ``H`` hex, ``A`` ASCII, ``E`` EPC (default ``H``)
* ``b`` block / password, ``n`` byte count — not needed for the EPC bank
* ``m`` Gen2 **memory bank** — ``E`` EPC 96-bit (default), ``A`` EPC + auto PC
  bits (ZT400/ZT600/ZD500R only), ``1`` EPC, ``2`` TID, ``3`` User

Note ``E``/``A`` appear in *both* the format and bank positions with different
meanings; encoding a hex EPC to the 96-bit bank is ``^RFW,H,,,E`` — format Hex,
bank E. The 96-bit bank writes exactly 12 bytes = 24 hex characters.

Encode setup uses ``^RSt,p,v,n,e``: ``t`` tag type (``8`` = Gen2, the only type on
current printers, so it may be omitted on a Gen2-only ZT411), ``p`` programming
position, ``n`` retry-on-failure count (1-10, default 3), ``e`` error action
(``N`` drop / ``P`` pause / ``E`` error). A canonical label:

    ^XA
    ^RS8
    ^RFW,H,,,E^FD112233445566778899001122^FS
    ^XZ
"""

from __future__ import annotations

#: An EPC-96 is 96 bits = 12 bytes = 24 hex characters; the "E" bank writes this.
EPC96_HEX_LEN = 24

_ERROR_ACTIONS = {"N", "P", "E"}  # ^RS 'e': drop / pause / error


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


def build_rs(
    *,
    tag_type: str = "8",
    program_position: str | None = None,
    retry: int | None = None,
    error_action: str | None = None,
) -> str:
    """Build a ``^RSt,p,v,n,e`` setup command, trimming trailing empty params.

    ``program_position`` is a ZPL position such as ``"F0"`` (leading edge) or an
    absolute dot row; ``retry`` (1-10) is how many labels to attempt on an
    encode failure; ``error_action`` is ``N``/``P``/``E``.
    """
    if retry is not None and not 1 <= retry <= 10:
        raise ZPLError(f"retry must be 1-10; got {retry}")
    if error_action is not None and error_action not in _ERROR_ACTIONS:
        raise ZPLError(
            f"error_action must be one of {sorted(_ERROR_ACTIONS)}; got {error_action!r}"
        )
    # ^RS positions: t, p, v(void len — skip), n, e
    params = [
        tag_type,
        program_position or "",
        "",
        "" if retry is None else str(retry),
        error_action or "",
    ]
    while len(params) > 1 and params[-1] == "":
        params.pop()
    return "^RS" + ",".join(params)


def build_encode(
    epc: bytes | str,
    *,
    bank: str = "E",
    human_text: str | None = None,
    barcode: bool = False,
    origin: tuple[int, int] = (50, 50),
    session_setup: bool = True,
    program_position: str | None = None,
    retry: int | None = None,
    error_action: str | None = None,
) -> bytes:
    """Build a ZPL label that encodes ``epc`` into the tag and prints it.

    ``bank="E"`` targets the EPC 96-bit bank and so requires a 24-hex EPC; use
    ``bank="A"`` (auto PC bits, ZT400/ZT600 series) for other lengths. Optionally
    print the EPC as human-readable text and/or a Code 128 barcode on the label.

    ``program_position``, ``retry`` and ``error_action`` configure the ``^RS``
    setup (void/retry handling and where on the label the tag is encoded); setting
    any of them implies ``session_setup``.
    """
    epc_hex = normalize_epc(epc)
    if bank == "E" and len(epc_hex) != EPC96_HEX_LEN:
        raise ZPLError(
            f"bank 'E' (EPC-96) needs {EPC96_HEX_LEN} hex chars; got {len(epc_hex)}. "
            "Use bank='A' for other EPC lengths."
        )
    want_rs = session_setup or any(
        p is not None for p in (program_position, retry, error_action)
    )
    x, y = origin
    lines = ["^XA"]
    if want_rs:
        lines.append(
            build_rs(
                program_position=program_position,
                retry=retry,
                error_action=error_action,
            )
        )
    lines.append(f"^RFW,H,,,{bank}^FD{epc_hex}^FS")
    if human_text is not None:
        lines.append(f"^FO{x},{y}^A0N,40,40^FD{human_text}^FS")
    if barcode:
        lines.append(f"^FO{x},{y + 60}^BY2^BCN,100,Y,N,N^FD{epc_hex}^FS")
    lines.append("^XZ")
    return ("\n".join(lines) + "\n").encode("ascii")


def build_read(*, field: int = 1, bank: str = "E", header: str = "EPC:") -> bytes:
    """Build a ZPL job that reads the tag's EPC back and returns it to the host.

    Uses ``^RFR`` to read the bank into field ``field`` and ``^HV#,n,h`` (Host
    Verification) to return it, prefixed with ``header``.
    """
    return (
        f"^XA^RFR,H,,,{bank}^FN{field}^FS^HV{field},,{header}^FS^XZ\n"
    ).encode("ascii")
