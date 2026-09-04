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
            human_text="PAIL #42",  # printed on the label face
            barcode=True,  # a Code 128 of the EPC, too
        )


asyncio.run(main())
```

That prints one label and burns the EPC into its tag. `encode_epc` validates the
EPC **before** sending anything, so a bad value raises rather than wasting a label.

## The read → encode loop

The point of having both a reader and a printer is the loop between them:

```python
async for tag in reader.inventory(max_tags=1):
    await printer.encode_epc(derive_new_epc(tag))  # mint a fresh label
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

`^RFW,H,,,E` is the RFID write: format **H**ex, Gen2 memory bank **E** (EPC-96).
On the ZT411 (a ZT400-series printer) use `bank="A"` for EPC lengths other than
96-bit — it auto-adjusts the PC bits. `print_zpl(...)` sends arbitrary ZPL if you
need a custom label template.

## Reliability: void/retry and encode position

If a tag fails to encode, a Zebra printer voids the label ("VOID" printed across
it) and retries. You can control that from `encode_epc`:

```python
await printer.encode_epc(
    epc,
    retry=3,  # attempt up to 3 labels on encode failure
    error_action="P",  # then Pause (N = drop and move on, E = Error)
    program_position="F0",  # where on the label the tag is encoded
)
```

These map to Zebra's `^RSt,p,v,n,e` setup command.

## One-time printer setup (on the device)

OmniTag sends the encode job, but the printer must know where the tag sits under
the print head. Run **RFID tag calibration** on the ZT411 itself (front-panel
menu or its WebUI) once per label stock; `program_position` fine-tunes it from
ZPL. Also point the driver at the printer's **raw ZPL port, TCP 9100** (the
default), reachable over the ZT411's standard Ethernet.

*Verified against Zebra's ZPL & ZBI2 Programming Guide (RFID commands `^RF`,
`^RS`, `^HV`) and the ZT400-series spec sheet: `^RFW,H,,,E` is correct for a
96-bit hex EPC, `bank="A"` is supported on the ZT400 series, and `^RS8` (Gen2)
is the default tag type — omittable on this Gen2-only printer.*
