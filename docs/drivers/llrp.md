# LLRP (Impinj) driver

`LLRPDriver` handles readers that speak **LLRP** — the standard network protocol
used by Impinj R700 and Speedway readers (and any other reader that exposes LLRP).
It's a thin wrapper over [llrpkit](https://pypi.org/project/llrpkit/), so all the
mature LLRP handling comes along for free.

## Connecting

```python
from omnitag import LLRPDriver

async with LLRPDriver("192.168.1.10", reader_id="dock-1") as reader:
    async for tag in reader.inventory(session=1, antennas=(1, 2)):
        print(tag.epc_hex, tag.antenna, tag.rssi_dbm)
```

- **host** (first argument) — the reader's IP address; defaults to LLRP port 5084.
- **reader_id** — a friendly name used in a fleet and on downstream data; defaults
  to `host:port`.
- Extra keyword arguments (timeouts, Impinj extensions) pass straight through to
  llrpkit's `Reader`.

## What `inventory()` accepts

Because this driver delegates to llrpkit, `inventory()` takes all of llrpkit's
options — `session`, `antennas`, `search_mode`, `tx_power_dbm`, `include_phase`,
`duration`, `max_tags`, and crucially `policy=` for host-side ignore filtering.
See the [llrpkit docs](https://kyronfeast.github.io/llrpkit/) for the full list.

## Capabilities

`LLRPDriver` reports `kind="llrp"`, `isolation="loop"` (it's async-native and
never blocks), and — because LLRP readers support them — `gpio=True` and
`tag_access=True`. RSSI is real, calibrated dBm.

## Works with the emulator

Point it at llrpkit's emulator to develop with no hardware:

```python
from llrpkit.emulator import LLRPEmulator

emu = LLRPEmulator(reads_per_sec=400.0)
await emu.start()
async with LLRPDriver("127.0.0.1", emu.port) as reader:
    ...
```
