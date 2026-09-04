# Quickstart

Everything on this page runs with **no RFID hardware** — llrpkit's emulator plays
the part of a real reader, and a fake serial port plays the part of a WYUAN.

## Run the demos

From the project folder:

```console
$ python examples/demo.py          # two LLRP readers, one ignore policy
$ python examples/mixed_fleet.py   # an LLRP reader + a blocking reader, side by side
```

The `mixed_fleet` demo prints something like:

```
  impinj   kind=llrp  isolation=loop
  vendor   kind=fake  isolation=thread

  impinj (async, on the loop):   60 reads
  vendor (blocking, own thread): 2 reads
```

That gap is the point: the fast reader raced ahead while the slow one plodded —
they didn't drag each other down. More on why in
[Keeping it light](concurrency.md).

## The shortest real program

Point a driver at a reader, then loop over the tags it sees:

```python
import asyncio
from omnitag import LLRPDriver


async def main() -> None:
    async with LLRPDriver("192.168.1.10", reader_id="dock-1") as reader:
        async for tag in reader.inventory():
            print(reader.capabilities.reader_id, tag.epc_hex, tag.antenna)


asyncio.run(main())
```

`async with` opens the connection and cleans it up for you. `inventory()` streams
tags one at a time as they're read.

## Many readers, one stream

A `Fleet` runs several readers together and hands you one merged stream. Each item
knows which reader it came from:

```python
import asyncio
from omnitag import Fleet, LLRPDriver, WyuanReader


async def main() -> None:
    async with (
        LLRPDriver("192.168.1.10", reader_id="dock") as impinj,
        WyuanReader("COM3", reader_id="line-4") as wyuan,  # a serial reader
    ):
        fleet = Fleet([impinj, wyuan])
        async for sourced in fleet.stream():
            print(sourced.reader_id, sourced.tag.epc_hex)


asyncio.run(main())
```

## Add an ignore policy

An ignore policy decides which tags each antenna is *allowed* to see, so junk
never reaches your system. It's a [llrpkit](https://pypi.org/project/llrpkit/)
`ReaderPolicy`, and OmniTag applies the **same policy across the whole fleet**:

```python
from llrpkit import AntennaPolicy, CatalogEntry, ItemCatalog, ReaderPolicy

policy = ReaderPolicy(
    catalog=ItemCatalog(
        entries=[
            CatalogEntry(match="epc_prefix", value="e200aa", category="pails"),
            CatalogEntry(match="epc_prefix", value="e200bb", category="pickles"),
        ]
    ),
    antennas={4: AntennaPolicy(mode="allow", categories={"pails"})},  # line 4 sees only pails
)

async for sourced in fleet.stream(policy=policy):
    ...  # only the tags that survived the policy, on every reader
```

Next: [Architecture](architecture.md) for how the pieces fit, or the
[Drivers](drivers/index.md) pages to wire a specific reader.
