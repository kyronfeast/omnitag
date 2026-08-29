# API reference

Everything you normally need is importable straight from the top-level package:

```python
from omnitag import (
    Fleet,              # run many drivers as one merged stream
    LLRPDriver,         # driver for Impinj / LLRP readers
    WyuanReader,        # driver for WYUAN / UHFReader288 serial readers
    ZebraPrinter,       # encode + print RFID labels (ZT411 and Link-OS kin)
    ReaderDriver,       # the driver contract (a typing Protocol)
    ThreadedDriver,     # base class for blocking-SDK drivers
    DriverCapabilities, # what a reader can do (vendor-neutral)
    SourcedTag,         # a tag + the id of the reader that produced it
)
```

## Fleet

`Fleet(drivers)` — run a set of already-connected drivers together.

- `fleet.stream(**opts) -> AsyncIterator[SourcedTag]` — merge every driver's
  inventory into one stream. Options (including `policy=` and `max_tags=`) are
  passed to every driver, so one policy filters the whole fleet.
- `fleet.capabilities -> list[DriverCapabilities]` — each reader's capabilities.

## Drivers

Both drivers are async context managers (`async with`), expose `capabilities`
after connecting, and stream tags from `inventory(**opts)`.

- `LLRPDriver(host, port=5084, *, reader_id=None, **reader_kwargs)` — see the
  [LLRP driver](drivers/llrp.md) page.
- `WyuanReader(port, *, reader_id=None, baudrate=57600, antenna=None, transport=None, ...)`
  — see the [WYUAN driver](drivers/wyuan.md) page.

## ZebraPrinter

`ZebraPrinter(host, port=9100, *, printer_id=None, transport=None)` — encode and
print RFID labels on a Zebra ZT411 (and Link-OS kin). Async context manager.

- `await printer.encode_epc(epc, *, bank="E", human_text=None, barcode=False) -> str`
  — print one label and write `epc` into its tag; returns the EPC hex. Validates
  the EPC before sending.
- `await printer.print_zpl(raw)` — send arbitrary ZPL (custom label templates).

See [Encoding tags](printers.md).

## DriverCapabilities

A frozen record of what a reader can do — read by callers and dashboards instead
of special-casing a vendor.

| Field | Meaning |
|---|---|
| `reader_id` | friendly name of this reader |
| `kind` | `"llrp"`, `"wyuan"`, … |
| `model`, `firmware` | reader identity, when known |
| `antenna_count` | number of antenna ports |
| `isolation` | `"loop"` / `"thread"` / `"process"` — how the driver must run |
| `gpio`, `tag_access` | optional features, when supported |
| `rssi_dbm` | true if RSSI is calibrated dBm |
| `host_side_policy` | always true — policies act on the normalized stream |
| `extras` | vendor-specific extras (e.g. Octane phase/Doppler) |

## SourcedTag

`SourcedTag(reader_id, tag)` — a llrpkit `TagReport` plus which reader produced
it. This is what a `Fleet` yields.

## The normalized tag

Tags themselves are llrpkit `TagReport` objects (`epc`, `epc_hex`, `antenna`,
`rssi_dbm`, timestamps, and `category` once a policy runs). See the
[llrpkit docs](https://kyronfeast.github.io/llrpkit/) for its full API.

## Writing your own driver

Subclass `ThreadedDriver` for a blocking reader, or implement the `ReaderDriver`
protocol for an async one. See [Drivers → Adding a new reader](drivers/index.md).
