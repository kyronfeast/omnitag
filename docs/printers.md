# Encoding tags: the Zebra printer

OmniTag doesn't only *read* tags — it can *create* them. A `ZebraPrinter` drives a
Zebra RFID printer (the **ZT411** and its Link-OS kin), which prints a label and
**writes an EPC into the tag embedded in it** in one pass. That closes the loop:
read tags with a driver, mint new ones with the printer, all speaking the same
EPC.

## How it connects

A Zebra printer accepts **ZPL** — small text programs — over its raw network port,
**TCP 9100**. So a printer is a simple request/response device (send ZPL, done),
which is why `ZebraPrinter` is plain asyncio, not a blocking driver.

```python
import asyncio
from omnitag import ZebraPrinter

async def main() -> None:
    async with ZebraPrinter("192.168.1.50", printer_id="line-4") as printer:
        await printer.encode_epc(
            "E28011700000020000000042",  # a 96-bit EPC (24 hex chars)
            human_text="PAIL #42",       # printed on the label face
            barcode=True,                # a Code 128 of the EPC, too
        )

asyncio.run(main())
```

That prints one label and burns the EPC into its tag. `encode_epc` validates the
EPC **before** sending anything, so a bad value raises rather than wasting a label.

## The read → encode loop

The point of having both a reader and a printer is the loop between them:

```python
async for tag in reader.inventory(max_tags=1):
    await printer.encode_epc(derive_new_epc(tag))   # mint a fresh label
```

`examples/encode_demo.py` runs this end to end with no hardware — it reads a tag
from the emulator and prints the exact ZPL a real ZT411 would receive.

## What ZPL it sends

`encode_epc` builds this (visible any time via the `print_zpl` escape hatch or the
demo):

```zpl
^XA
^RS8
^RFW,H,,,E^FDE28011700000020000000042^FS
^FO50,50^A0N,40,40^FDPAIL #42^FS
^FO50,110^BY2^BCN,100,Y,N,N^FDE28011700000020000000042^FS
^XZ
```

`^RFW,H,,,E` is the RFID write: **W**rite, **H**ex, EPC-96 memory bank (**E**). Use
`bank="A"` for EPC lengths other than 96-bit. `print_zpl(...)` sends arbitrary ZPL
if you need a custom label template.

## Verify on the physical ZT411

The ZPL structure is straight from Zebra's ZPL RFID guide, but two details can
vary with firmware and label setup — each isolated to one place so a fix is
trivial:

1. **Memory-bank code** — `encode_epc(bank=...)`. `E` is EPC-96; `A` auto-sizes PC
   bits for other lengths.
2. **Session setup** — the leading `^RS8`. If your labels are configured
   differently, adjust it in `omnitag/printers/zpl.py` (`session_setup`).

Also confirm the printer's **media/RFID calibration** is done on the device itself
(via its display or WebUI) — OmniTag sends the encode job, but the printer must
already know where the tag sits in the label.

*Source: Zebra ZPL Programming Guide, RFID commands (`^RF` / `^RS` / `^HV`).*
