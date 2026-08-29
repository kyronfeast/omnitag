"""Read a tag, then encode a fresh label for it — the full loop, no hardware.

A reader (emulated) sees a tag; the printer (faked here, printing the ZPL it
would send to stdout) mints a new RFID label carrying an EPC. Run:

    python examples/encode_demo.py
"""

from __future__ import annotations

import asyncio

from llrpkit.emulator import LLRPEmulator

from omnitag import LLRPDriver, ZebraPrinter


class PrintToStdout:
    """A fake printer transport that shows the ZPL instead of sending it."""

    async def send(self, data: bytes) -> None:
        print(data.decode().rstrip())

    async def close(self) -> None:
        pass


async def main() -> None:
    emu = LLRPEmulator(reads_per_sec=200.0, seed=1)
    await emu.start()
    try:
        async with (
            LLRPDriver("127.0.0.1", emu.port, reader_id="dock") as reader,
            ZebraPrinter(transport=PrintToStdout(), printer_id="dock-printer") as printer,
        ):
            print("read one tag from the reader...\n")
            async for tag in reader.inventory(max_tags=1, duration=6.0):
                seen = tag.epc_hex.upper()
                print(f"  saw EPC {seen} on antenna {tag.antenna}\n")
                # mint a fresh label carrying a 96-bit EPC (pad the sample EPC)
                new_epc = (seen + "0" * 24)[:24]
                print(f"encode + print a new label for EPC {new_epc}:\n")
                await printer.encode_epc(new_epc, human_text="PAIL", barcode=True)
                break
    finally:
        await emu.stop()


if __name__ == "__main__":
    asyncio.run(main())
