# OmniTag RFID

**One interface for every RFID reader — any reader, any protocol, one normalized tag stream.**

OmniTag RFID is a multi-vendor reader layer built on top of
[llrpkit](https://pypi.org/project/llrpkit/). It defines a small **driver seam**
at the normalized `TagReport` boundary, ships the **LLRP adapter** as the
reference driver, and merges any mix of readers into a single stream with a
**fleet manager** — so one host-side ignore policy, one GS1 decode, and one
dashboard apply across the whole fleet regardless of what each reader speaks
underneath.

[![PyPI](https://img.shields.io/pypi/v/omnitag.svg)](https://pypi.org/project/omnitag/)
[![Python](https://img.shields.io/pypi/pyversions/omnitag.svg)](https://pypi.org/project/omnitag/)
[![CI](https://github.com/kyronfeast/omnitag/actions/workflows/ci.yml/badge.svg)](https://github.com/kyronfeast/omnitag/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-kyronfeast.github.io%2Fomnitag-indigo)](https://kyronfeast.github.io/omnitag/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

```console
$ pip install omnitag              # core + the LLRP (Impinj) driver
$ pip install "omnitag[wyuan]"     # + the WYUAN serial driver
```

> **Alpha.** The driver seam, the LLRP driver, the WYUAN serial driver, the
> fleet manager, and a **Zebra ZT411 tag encoder** (read *and* write tags) are in
> place and tested against llrpkit's emulator and fakes — no hardware required.
> The WYUAN and ZT411 pieces are verified against their vendors' SDK sources and
> programming guides but not yet on a physical unit; field reports welcome. A
> capability-gated dashboard and more drivers are next.

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
$ git clone https://github.com/kyronfeast/omnitag && cd omnitag
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

## Documentation

Full docs are published at **[kyronfeast.github.io/omnitag](https://kyronfeast.github.io/omnitag/)**
(install guide, quickstart, architecture, a plain-language concurrency/CPU page,
per-driver guides, the WYUAN protocol reference, the ZT411 printer guide, and an
API index). They live in [`docs/`](docs/) and build locally with mkdocs:

```console
$ pip install -e ".[docs]"
$ mkdocs serve          # http://127.0.0.1:8000
```

The [`DESIGN.md`](DESIGN.md) decision record has the deeper rationale and roadmap.

## Development

```console
$ pip install -e ".[dev]"
$ pytest
$ ruff check . && mypy src
```

You do not need an RFID reader — llrpkit's emulator (and a fake serial port for
the WYUAN driver) are the development targets.

## License

[MIT](LICENSE).

## Trademarks

Impinj, R700, Speedway, Octane, and related marks are trademarks of Impinj, Inc.
This project is an independent open-source effort and is not affiliated with,
sponsored, or endorsed by Impinj.
