# OmniTag RFID — a multi-vendor RFID reader layer on top of llrpkit

**Status:** Draft design note · **Author:** kyronfeast · **Depends on:** llrpkit (LLRP driver)

> **Name:** OmniTag RFID · **PyPI / import name:** `omnitag` (confirmed free on PyPI).
> One interface for all your tags — any reader, any protocol, one normalized stream.

## The problem

llrpkit speaks **LLRP**, and only LLRP. That's correct and deliberate: it targets
Impinj Octane-class readers (R700, Speedway) and any OEM reader that chooses to
expose LLRP. But the real world has mixed fleets. A warehouse may run an Impinj
R700 on the main dock *and* a rack of cheap Impinj-E710 OEM modules (WYUAN, FOCUS,
and similar) that do **not** speak LLRP — they ship a proprietary command protocol
behind a vendor SDK, even when the transport is TCP/IP. (The tell: if a reader
ships a "C#/Java/Python SDK," it is not standard LLRP — an LLRP reader needs no
vendor SDK.)

We want one system that can drive a **mix** of readers, normalize them to a single
tag/event stream, apply one ignore policy, and show one dashboard — regardless of
which protocol each reader underneath happens to speak.

## The key insight: the protocol-agnostic seam already exists

llrpkit already separates cleanly into two halves, without having been designed
for this:

| Half | Modules | Protocol-specific? |
|---|---|---|
| **Wire / transport** | LLRP message codec, `reader.py` inventory loop | **Yes — LLRP only** |
| **Everything downstream** | `TagReport`, ignore-policy engine, GS1 decode, presence events, MQTT/webhook sinks, capture, dashboard | **No — operates on normalized tags** |

The downstream half never asks where a tag came from. It consumes `TagReport`
objects. That means the entire value layer — policy, decode, presence, sinks,
dashboard — is **already reusable across any reader protocol**. Only the wire half
is LLRP-bound.

So the design is not "teach llrpkit new protocols." It's: **define a driver
seam at the `TagReport` boundary, and let different backends fill it.**

## Goals / non-goals

**Goals**
- One `Reader` driver interface that any vendor backend implements.
- A normalized event schema (reuse llrpkit's `TagReport` / presence events verbatim).
- Reuse llrpkit's policy engine, sinks, and dashboard unchanged, driving a mixed fleet.
- llrpkit becomes *the LLRP driver* — a dependency, never forked.
- Graceful capability negotiation: readers differ (some do GPIO, some don't).

**Non-goals**
- Rewriting or absorbing llrpkit. It stays a clean, standalone, published library.
- A universal magic protocol. Each vendor family needs a hand-written driver.
- Supporting every reader on day one. Ship the seam + LLRP driver first.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │  OmniTag value layer (reused from llrpkit) │
                    │  policy · GS1 decode · presence · sinks ·  │
                    │  capture · dashboard                       │
                    └───────────────────┬─────────────────────────┘
                                        │  normalized TagReport / events
                    ┌───────────────────┴─────────────────────────┐
                    │            Reader driver interface           │
                    │   connect · inventory() -> AsyncIterator     │
                    │   capabilities · (optional) gpio, tag ops    │
                    └───┬───────────────┬───────────────┬──────────┘
                        │               │               │
                 ┌──────┴─────┐   ┌─────┴──────┐   ┌────┴───────┐
                 │  llrpkit   │   │   wyuan    │   │  <vendor>  │
                 │ LLRP driver│   │ proprietary│   │   driver   │
                 │ (R700/     │   │  TCP/serial│   │            │
                 │  Speedway) │   │  protocol  │   │            │
                 └────────────┘   └────────────┘   └────────────┘
```

### The driver interface (sketch)

A `Reader` is an async context manager that yields normalized tags. The minimum
contract is small on purpose — a driver that can only stream inventory is still a
valid driver.

```python
from typing import Protocol, AsyncIterator
from llrpkit import TagReport            # the normalized unit, reused as-is

class ReaderDriver(Protocol):
    async def __aenter__(self) -> "ReaderDriver": ...
    async def __aexit__(self, *exc) -> None: ...

    @property
    def capabilities(self) -> "ReaderCapabilities": ...
    # what this reader can actually do — antennas, gpio?, tag read/write?,
    # rssi units, max tx power, etc. Callers branch on this, not on vendor.

    def inventory(self, **opts) -> AsyncIterator[TagReport]: ...
    # the one required method. Yields normalized tags.

    # optional, guarded by capabilities:
    async def gpio(self, ...): ...
    async def read_tag(self, ...): ...
    async def write_tag(self, ...): ...
```

Each driver's job is exactly one thing: **turn its native protocol into a stream
of `TagReport`.** llrpkit's `reader.py` already does this for LLRP — it *is* the
reference driver. A `wyuan` driver does the same for WYUAN's protocol.

### Capability negotiation

Readers are not equal. An R700 does GPIO, deep tag memory access, and Octane
extensions (phase, peak RSSI); a bargain E710 module may only stream EPC + RSSI.
The `ReaderCapabilities` object is how the value layer and dashboard adapt: a panel
or CLI flag checks `reader.capabilities.gpio` before offering GPIO, and the policy
engine — which runs **host-side** — works for *every* driver regardless, because it
filters the normalized stream after the fact. That's a quiet win: **ignore policies
work on the cheap readers too**, even though they have no on-reader filtering.

### What's reused vs. new

| Component | Source | Effort |
|---|---|---|
| `TagReport`, presence events, GS1 decode | llrpkit (import) | **reuse** |
| Ignore-policy engine | llrpkit (import) | **reuse** |
| MQTT / webhook / capture sinks | llrpkit (import) | **reuse** |
| Dashboard (FastAPI + WS) | llrpkit (import / thin wrap) | **reuse, add capability gating** |
| `ReaderDriver` protocol + `ReaderCapabilities` | **new** in omnitag | small |
| Fleet manager (drive N readers, one stream) | **new** — generalize `registry.py` | medium |
| LLRP driver adapter | wrap llrpkit `reader.py` | small |
| `wyuan` driver | **new** — reverse-engineer their protocol | **large, per vendor** |

The honest cost: the *seam* and the *LLRP adapter* are small. Every **new vendor
driver is real work**, done one at a time by reverse-engineering the vendor SDK or
sniffing the wire. Start with whatever hardware is physically on the desk.

## Concurrency & CPU (decision record)

**Context.** A real mixed-reader site running Impinj's Octane SDK and a vendor
SDK *in one process* saw reads silently vanish. Not RF, not protocol confusion:
the two SDKs starved each other. Both block (wait synchronously for the next
read); co-hosted on one thread, whichever one is *inside* a blocking call freezes
the servicing of the other, whose reader buffer then overflows and drops tags.
OmniTag will host multiple readers in one place too, so it must make that failure
mode impossible — while staying CPU-light (the Odoo host is modest).

**Decision.** Drivers declare how they must run, and the model enforces it:

- **`isolation = "loop"` — async-native drivers share one event loop.** llrpkit
  is non-blocking, so any number of LLRP readers multiplex on a single thread at
  near-zero idle cost. This is the cheapest possible model and the default. The
  rule that protects it: **llrpkit stays strictly non-blocking.**
- **`isolation = "thread"` — blocking drivers run on their own worker thread.**
  A vendor SDK that blocks is bridged into the async merge through a queue
  (`ThreadedDriver`), so it can never stall the loop that serves the other
  readers. The starvation is designed out at the seam: a blocking driver
  *cannot* be placed on the shared loop by construction.
- **`isolation = "process"` — flaky/native SDKs get a full process.** For an SDK
  that hangs or crashes, a separate process keeps a bad vendor from taking the
  fleet down, at the cost of a second interpreter. Reserved for when "thread"
  isn't enough.

**Why not process-isolate everything?** It's the most robust but the least
light: N interpreters, N times the memory, IPC overhead. For a handful of
async LLRP readers that never block, isolation buys nothing and costs real CPU.
Match the isolation to the driver, don't pay for it uniformly.

**CPU-light rules that fall out of this:**

1. **Prefer presence events over the raw read firehose downstream.** A tag read
   300×/s becomes one *arrived* + one *departed*. This is the single biggest
   CPU/bandwidth saver for the Odoo path; llrpkit already has the presence
   tracker, and the fleet should default the ERP-facing stream to it.
2. **Block, never busy-poll.** A blocking driver must *wait* for the next read
   (≈0% idle CPU), not spin a `while True: poll()` loop (100% of a core doing
   nothing). Baked into the `ThreadedDriver` contract.
3. **Bounded queues (backpressure) everywhere.** The thread bridge uses a
   bounded, drop-oldest queue so a slow sink can't balloon memory or spin the
   loop. Filter early with host-side policy so dropped tags cost nothing
   downstream.

**Status:** the `isolation` capability, the `ThreadedDriver` base (thread
lifecycle, thread-safe hand-off, host-side policy, bounded backpressure), and a
test proving a blocking reader cannot starve an async one are **implemented**.
Process isolation is designed but not yet built.

## Repository shape

```
omnitag/
  src/omnitag/
    __init__.py
    driver.py          # ReaderDriver Protocol, DriverCapabilities, SourcedTag
    threaded.py        # ThreadedDriver: safe base for blocking vendor SDKs
    fleet.py           # drive many drivers → one normalized stream
    drivers/
      llrp.py          # thin adapter over llrpkit (the reference driver)
      wyuan.py         # future: subclass ThreadedDriver (blocking SDK)
    dashboard/         # reuse llrpkit's, gated by capabilities
  pyproject.toml       # name = "omnitag"; depends on: llrpkit
  docs/
```

`pyproject.toml` depends on `llrpkit` (now on PyPI), so omnitag *composes* it
rather than copying it. That's the portfolio story: a focused library that snaps
into a larger platform.

## Roadmap

1. **Seam + LLRP adapter.** ✅ `ReaderDriver` / `DriverCapabilities`; llrpkit
   wrapped as the `llrp` driver. Whole value layer runs through the seam.
2. **Fleet manager.** ✅ N mixed drivers → one stream + one policy.
3. **Concurrency model.** ✅ `isolation` capability + `ThreadedDriver` so a
   blocking driver can't starve async ones (see the decision record above).
4. **First proprietary driver.** ✅ `WyuanReader` — the UHFReader288 serial
   protocol, coded from the manual, fully tested against a fake serial port.
   **Pending: verification against a physical reader** (the three VERIFY points in
   `docs/wyuan-protocol.md`), and RSSI→dBm calibration.
5. **Dashboard capability gating.** Panels appear/disappear per
   `reader.capabilities` — not yet built.

Phases 1–4 are done and run entirely against llrpkit's emulator + a fake serial
port — no hardware in hand. Only the physical-reader confirmation remains.

## Open questions

- ~~**Do we have a WYUAN unit?**~~ Driver is built from the manual and tested
  against a fake serial port; a physical unit is needed only to confirm the three
  VERIFY points and calibrate RSSI.
- ~~**Emulator for proprietary drivers?**~~ Solved cheaply: the driver takes an
  injected transport, so a fake serial replays canned frames — no separate
  emulator process needed. (Same zero-hardware philosophy as llrpkit's emulator.)
- ~~**Naming.**~~ Settled: **OmniTag RFID**, package `omnitag`. Reserve the name on
  PyPI early (an empty first release) so nobody else claims it while you build —
  same lesson llrpkit just taught.

## Why this is the right shape

It keeps llrpkit clean (a strength, not a limitation), turns "llrpkit only speaks
LLRP" from a wall into a *layer*, and makes the hard-won downstream work — the
policy engine, the decode, the dashboard — pay off across every reader you ever
add. The mixed-fleet warehouse gets one pane of glass; you get a platform story
built on a library you already shipped.
