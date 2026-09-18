# Gated inventory: one window per pail, on every reader

A production line doesn't want a firehose of tag reads. It wants to know
*"a pail just passed station 3 carrying these tags"* — and, just as much,
*"a pail passed station 3 and we read **nothing**"*, because that's the one
that ends up in the wrong brine.

OmniTag does this the same way on every reader it drives. A photo eye wired
to the reader's input line marks when something is in front of the antenna;
the driver turns each trip into one **`InventoryWindow`** — when it opened,
when it closed, and the tags seen in between — and a `Fleet` labels each
window with the station that produced it. An **empty window is delivered too**.

```python
from omnitag import Fleet, LLRPDriver, WyuanReader

async with (
    LLRPDriver("10.0.0.10", reader_id="dock", gpi_trigger=1) as dock,
    WyuanReader("/dev/ttyUSB0", reader_id="line-4", gpi_trigger=True) as line,
):
    async for sw in Fleet([dock, line]).windows(policy=my_policy):
        w = sw.window
        if w.empty:
            alert(f"{sw.reader_id}: pail passed with NO readable tag at {w.opened_at}")
        else:
            record(sw.reader_id, w.epcs, w.opened_at, w.closed_at)
```

That's the whole integration surface for BrineTrace-style traceability: one
stream of *(station, time, tags-or-nothing)* regardless of which brand of
reader sits at which station.

## What each driver does underneath

**Impinj / LLRP (`LLRPDriver(gpi_trigger=N)`)** — the reader owns the trigger.
llrpkit builds a ROSpec with a GPI start trigger and a GPI-with-timeout stop
trigger; the reader starts reading when the line trips, stops when it releases,
re-arms for the next pail, and reports each edge as an event. No host
round-trip is in the timing path. See llrpkit's
[gated inventory](https://kyronfeast.github.io/llrpkit/field-guide/gated-inventory/)
page for the mechanics.

**WYUAN / serial (`WyuanReader(gpi_trigger=True)`)** — the driver owns the
trigger, on its worker thread. It polls the reader's IN1 pin (`0x47`) every
20 ms while idle and runs inventory (`0x01`) only while the pin is active,
re-checking the pin after each scan. Serial has nothing else to do, so the poll
is free, and the edges and tags arrive strictly in order.

!!! note "Why not the W-series' built-in trigger mode?"
    The reader *does* have one (working mode 2: inventory while GPI1 is low).
    But in that mode it stops answering every command except three — the host
    can no longer read the GPIO pin, and the push frames carry no pin state.
    Your software would see tags, never edges, so **a pail that passed with a
    dead or missing tag would be invisible**. That's the exception a line most
    needs to see, so the driver uses answering mode and does the gating itself.
    Mode 2 remains available (`protocol.build_set_work_mode(2)`) for a reader
    that must run with no host attached at all.

## Wiring

The two readers' inputs are electrically different, and the drivers' defaults
follow the natural wiring for each:

| reader | input | idle level | "object present" | driver default |
|---|---|---|---|---|
| Impinj R700 | optically isolated | **low** (nothing applied) | voltage applied → **high** | `gpi_active_high=True` |
| WYUAN W-series | TTL with pull-up | **high** | pulled to ground → **low** | `gpi_active_high=False` |

Either default can be flipped per reader. Because the level lives with the
reader's constructor, `Fleet.windows()` needs no per-reader options.

Recommendations from the bench:

- Put an **interposing relay** between an industrial 24 V photo eye and either
  reader. Don't feed 24 V into the WYUAN's TTL input. The relay isolates the
  reader, makes both readers look the same to the sensor, and its **off-delay**
  (200–500 ms) keeps the window open while the tag clears the antenna.
- Prefer an **NPN (sinking)** photo eye: it pulls low when blocked, which the
  WYUAN input wants directly and the relay coil doesn't care about.
- Mount the eye so the beam is broken *while the tag is in the antenna's field*.

## Window fields

`InventoryWindow` (from llrpkit): `port`, `opened_at`, `closed_at` (Unix
seconds), `tags` (every observation, repeats included), `epcs` (distinct, in
first-seen order), `duration`, `empty`. A `SourcedWindow` from a fleet adds
`reader_id`.

Options accepted by every `windows()`: `policy=` (the same host-side ignore
policy as `inventory`), `settle=` (grace after the closing edge for late
reports — LLRP needs ~100 ms, serial needs none), `max_open=` (force-close a
window whose release never arrives, default 30 s).

## Try it with no hardware

```console
$ python examples/gated_line.py
```

runs an emulated R700 and a fake serial WYUAN, trips their "photo eyes" a few
times — including one pail with no tag — and prints the windows each station
produced.
