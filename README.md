# OmniTag RFID

**One interface for every RFID reader — any reader, any protocol, one normalized tag stream.**

OmniTag RFID is a multi-vendor reader layer built on top of
[llrpkit](https://pypi.org/project/llrpkit/). It defines a small **driver seam**
at the normalized `TagReport` boundary, ships the **LLRP adapter** as the
reference driver, and merges any mix of readers into a single stream with a
**fleet manager** — so one host-side ignore policy, one GS1 decode, and one
dashboard apply across the whole fleet regardless of what each reader speaks
underneath.

> 🚧 **Pre-alpha.** The driver seam, the LLRP driver, and the fleet manager are
> in place and tested against llrpkit's emulator (no hardware required).
> Proprietary-reader drivers (Impinj-E710 OEM modules and others) are next.

## Why

llrpkit speaks LLRP, and only LLRP — by design. But real deployments mix an
Impinj R700 on LLRP with cheaper OEM modules that expose a proprietary protocol
behind a vendor SDK. OmniTag turns "llrpkit only speaks LLRP" from a wall into a
*layer*: llrpkit becomes the LLRP driver, and other readers slot in behind the
same contract, feeding the same value layer you already have.

## The seam

A `ReaderDriver` turns some reader's native protocol into a stream of llrpkit
`TagReport` objects. That's the only thing a driver must do — GPIO and tag
memory access are optional and advertised through `DriverCapabilities`, so
callers branch on *capabilities*, never on vendor.

```python
import asyncio
from omnitag import Fleet, LLRPDriver

async def main() -> None:
    # a mixed fleet — here two LLRP readers; a WYUAN driver would sit alongside
    async with (
        LLRPDriver("10.0.0.1", reader_id="dock-1") as a,
        LLRPDriver("10.0.0.2", reader_id="dock-2") as b,
    ):
        fleet = Fleet([a, b])
        async for sourced in fleet.stream(policy=my_policy):
            print(sourced.reader_id, sourced.tag.epc_hex, sourced.tag.category)

asyncio.run(main())
```

The `policy=` above is a llrpkit `ReaderPolicy` — the **same ignore-policy
engine**, filtering the entire fleet host-side. Nothing about the value layer
changed; it just sees a merged stream now.

## Try it (no hardware)

```console
$ pip install -e ".[dev]"
$ python examples/demo.py
two readers, one policy: line 4 sees only pails

  reader line-a: llrp model 700 antennas=4 gpio=True
  reader line-b: llrp model 700 antennas=4 gpio=True

  [line-b] e200aa01...  ant 4  [pails]
  [line-a] e200aa02...  ant 4  [pails]
  ...
kept 8 · dropped 20 ({'pickles-fresh': 20})
```

## Architecture

See [`DESIGN.md`](DESIGN.md) for the full design — the driver abstraction, what
is reused from llrpkit vs. built new, capability negotiation, and the roadmap
for adding vendor drivers.

## Development

```console
$ pip install -e ".[dev]"
$ pytest
$ ruff check . && mypy src
```

You do not need an RFID reader — llrpkit's emulator is the development target.

## License

[MIT](LICENSE).

## Trademarks

Impinj, R700, Speedway, Octane, and related marks are trademarks of Impinj, Inc.
This project is an independent open-source effort and is not affiliated with,
sponsored, or endorsed by Impinj.
