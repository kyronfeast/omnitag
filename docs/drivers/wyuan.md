# WYUAN serial driver

`WyuanReader` handles **WYUAN / UHFReader288-family** readers over a serial
connection (RS232, or a USB-to-serial adapter). Serial reads block, so this driver
is built on [`ThreadedDriver`](../concurrency.md) — it runs on its own worker
thread and can share a fleet with a fast LLRP reader without slowing it down.

For the byte-level wire format, see the [WYUAN protocol
reference](../wyuan-protocol.md).

## Connecting

Install the extra first (`pip install "omnitag[wyuan]"`), then:

```python
from omnitag import WyuanReader

async with WyuanReader("COM3", reader_id="line-4", antenna=1) as reader:
    async for tag in reader.inventory():
        print(tag.epc_hex, tag.antenna)
```

- **port** (first argument) — the serial port: `COM3` on Windows,
  `/dev/ttyUSB0` on Linux.
- **baudrate** — defaults to `57600` (the reader's factory default).
- **antenna** — optional; if set, the driver asks the reader to use that antenna.
- **reader_id** — a friendly name; defaults to `wyuan:<port>`.

Serial is point-to-point: one reader per port. Several readers means several
ports (or a serial-to-Ethernet gateway).

## How it works

It **polls**: send the "inventory" command, read back the tags the reader found,
repeat. The reader's own scan time paces the loop. Multi-frame responses (a big
tag population split across several replies) are handled automatically.

## Capabilities

`WyuanReader` reports `kind="wyuan"`, `model="UHFReader288"`, and
`isolation="thread"`. GPIO and tag read/write exist in the protocol but aren't
wired into this driver yet, so it reports `gpio=False` and `tag_access=False`.
RSSI is a **raw** value, not calibrated dBm, so `rssi_dbm` is left unset.

## Testing without hardware

The serial port is injectable — pass any object with `read`/`write`/`close`. Tests
use a fake that replays canned reader frames, so the whole driver is verified with
no physical reader (the same zero-hardware idea as llrpkit's emulator).

## Verified against the vendor SDK

The wire format is checked line-by-line against the vendor's own SDK — the
UHFReader288 DLL manual and the C++/C# demo programs that ship with W-series
readers — so the fields that are easy to get wrong are settled, not assumed
(citations in the [protocol reference](../wyuan-protocol.md)):

1. **EPC length unit** — a **byte** count.
2. **Antenna byte** — a bitmask on 1/4/8-port readers, a plain index on 12/16-port
   readers. Set `antenna_count=` to your reader's port count and the driver picks
   the right decode (anything over 8 ports is index mode).
3. **RSSI** — raw units, so it stays out of `rssi_dbm`; real dBm would need a
   per-model calibration the vendor doesn't publish.

Two extras the SDK revealed: pass `fast_id=True` to get the tag's TID alongside
its EPC on Impinj Monza tags (`tag.tid`), and a reader left in the vendor's
*real-time* push mode still streams — the driver recognises those frames too.
