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

## Verify on first real read

The manual is slightly ambiguous on three fields. Each is isolated to one line of
code so a mismatch is trivial to fix — details in the [protocol
reference](../wyuan-protocol.md):

1. **EPC length unit** — assumed bytes; may be words on some firmware.
2. **Antenna byte** — decoded as a 1/4/8-port bitmask; 16-port readers use a plain
   index.
3. **RSSI** — raw units; turning it into real dBm needs a per-model calibration.
