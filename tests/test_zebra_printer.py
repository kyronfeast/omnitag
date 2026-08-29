"""ZebraPrinter driven through a fake socket — no printer needed.

Also demonstrates the headline capability: read a tag off a reader, then
re-encode a fresh label with the printer, all in one flow.
"""

from __future__ import annotations

import contextlib

from llrpkit.emulator import LLRPEmulator

from omnitag import LLRPDriver, ZebraPrinter
from omnitag.printers import zpl

EPC96 = "E28011700000020000000042"


class FakePrinter:
    """Captures every ZPL job that would have gone out on the wire."""

    def __init__(self) -> None:
        self.jobs: list[bytes] = []
        self.closed = False

    async def send(self, data: bytes) -> None:
        self.jobs.append(data)

    async def close(self) -> None:
        self.closed = True


async def test_encode_sends_rfid_write_zpl() -> None:
    fake = FakePrinter()
    async with ZebraPrinter(printer_id="line-4-printer", transport=fake) as printer:
        assert printer.kind == "zebra-printer"
        returned = await printer.encode_epc(EPC96, human_text="PAIL", barcode=True)
    assert returned == EPC96
    assert fake.closed  # connection closed on exit
    assert len(fake.jobs) == 1
    job = fake.jobs[0].decode()
    assert f"^RFW,H,,,E^FD{EPC96}^FS" in job
    assert "^FDPAIL^FS" in job


async def test_bad_epc_raises_before_sending() -> None:
    fake = FakePrinter()
    async with ZebraPrinter(transport=fake) as printer:
        try:
            await printer.encode_epc("not-hex")
        except zpl.ZPLError:
            pass
        else:  # pragma: no cover
            raise AssertionError("bad EPC should raise")
    assert fake.jobs == []  # nothing was sent


async def test_print_zpl_escape_hatch() -> None:
    fake = FakePrinter()
    async with ZebraPrinter(transport=fake) as printer:
        await printer.print_zpl("^XA^FO50,50^A0N,30,30^FDhello^FS^XZ")
    assert b"hello" in fake.jobs[0]


async def test_read_a_tag_then_encode_a_new_one() -> None:
    # The loop: a reader sees a tag; the printer mints a fresh label for it.
    emu = LLRPEmulator(reads_per_sec=400.0, seed=4)
    await emu.start()
    fake = FakePrinter()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="dock") as reader,
            ZebraPrinter(transport=fake, printer_id="dock-printer") as printer,
        ):
            seen_epc = None
            stream = reader.inventory(max_tags=1, duration=6.0)
            async with contextlib.aclosing(stream):  # type: ignore[type-var]
                async for tag in stream:
                    seen_epc = tag.epc_hex
                    break
            assert seen_epc is not None
            # re-encode a label carrying the same EPC (padded to 96-bit for bank E)
            padded = (seen_epc.upper() + "0" * 24)[:24]
            await printer.encode_epc(padded)
    finally:
        await emu.stop()

    assert fake.jobs, "printer received no job"
    assert padded in fake.jobs[0].decode()
