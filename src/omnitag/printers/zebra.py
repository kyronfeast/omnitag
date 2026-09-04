"""ZebraPrinter — encode + print RFID labels on a Zebra ZT411 (and Link-OS kin).

In plain words: this is the translator for a Zebra RFID *printer*. Where a reader
*sees* tags, a printer *creates* them — it prints a label and writes an EPC into
the tag embedded in it. It talks ZPL (built next door in ``zpl.py``) over the
printer's raw network port (TCP 9100). This closes OmniTag's loop: read tags with
a reader, make new ones with the printer, all speaking the same EPC.

Unlike the blocking serial WYUAN reader, a printer is a simple request/response
device, so this is plain asyncio — connect, send ZPL, done. The transport is
injectable, so the whole thing is tested with no printer attached.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from omnitag.printers import zpl


class PrinterTransport(Protocol):
    """The slice of a socket this printer needs (async send + close)."""

    async def send(self, data: bytes) -> None: ...
    async def close(self) -> None: ...


class _SocketTransport:
    """Real transport: a raw TCP connection to the printer's ZPL port (9100)."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer

    async def send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


class ZebraPrinter:
    """An RFID label printer/encoder. Async context manager.

    ``host`` is the printer's IP; ``port`` defaults to 9100 (raw ZPL). Pass a
    ``transport`` to test without hardware. ``printer_id`` names it in logs and
    on downstream records; it defaults to ``zebra:<host>:<port>``.
    """

    kind = "zebra-printer"

    def __init__(
        self,
        host: str | None = None,
        port: int = 9100,
        *,
        printer_id: str | None = None,
        transport: PrinterTransport | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.printer_id = printer_id or f"zebra:{host}:{port}"
        self._transport = transport

    async def __aenter__(self) -> ZebraPrinter:
        if self._transport is None:
            if self.host is None:
                raise ValueError("ZebraPrinter needs a host (or an injected transport)")
            _reader, writer = await asyncio.open_connection(self.host, self.port)
            self._transport = _SocketTransport(writer)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._transport is not None:
            await self._transport.close()

    async def encode_epc(
        self,
        epc: bytes | str,
        *,
        bank: str = "E",
        human_text: str | None = None,
        barcode: bool = False,
        retry: int | None = None,
        error_action: str | None = None,
        program_position: str | None = None,
    ) -> str:
        """Print one label and encode ``epc`` into its tag. Returns the EPC hex.

        ``human_text`` prints readable text on the label; ``barcode=True`` adds a
        Code 128 of the EPC. ``retry`` (1-10) sets how many labels the printer
        attempts if encoding fails (it voids and re-tries); ``error_action``
        (``N``/``P``/``E``) is what to do if it still fails; ``program_position``
        (e.g. ``"F0"``) sets where on the label the tag is encoded. Raises
        :class:`~omnitag.printers.zpl.ZPLError` on bad input before anything is sent.
        """
        job = zpl.build_encode(
            epc,
            bank=bank,
            human_text=human_text,
            barcode=barcode,
            retry=retry,
            error_action=error_action,
            program_position=program_position,
        )
        await self._send(job)
        return zpl.normalize_epc(epc)

    async def print_zpl(self, raw: str | bytes) -> None:
        """Escape hatch: send arbitrary ZPL to the printer as-is."""
        await self._send(raw.encode("ascii") if isinstance(raw, str) else raw)

    async def _send(self, data: bytes) -> None:
        assert self._transport is not None, "printer is not connected"
        await self._transport.send(data)
