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

## Repository shape

```
omnitag/
  src/omnitag/
    __init__.py
    driver.py          # ReaderDriver Protocol, ReaderCapabilities
    fleet.py           # drive many drivers → one normalized stream
    drivers/
      llrp.py          # thin adapter over llrpkit (the reference driver)
      wyuan.py         # stub first: connect + inventory TODO
    dashboard/         # reuse llrpkit's, gated by capabilities
  pyproject.toml       # name = "omnitag"; depends on: llrpkit
  docs/
```

`pyproject.toml` depends on `llrpkit` (now on PyPI), so omnitag *composes* it
rather than copying it. That's the portfolio story: a focused library that snaps
into a larger platform.

## Roadmap

1. **Seam + LLRP adapter.** Define `ReaderDriver` / `ReaderCapabilities`; wrap
   llrpkit as the `llrp` driver. Prove the whole value layer runs through the seam
   with zero behavior change against the emulator. *(No new hardware needed.)*
2. **Fleet manager.** Generalize llrpkit's `registry.py` to drive N drivers of
   mixed type into one stream + one policy + one dashboard.
3. **First proprietary driver.** Pick the vendor you actually own. Stub
   `inventory()`, get one EPC to flow, then fill in. Capability-flag whatever it
   can't do.
4. **Dashboard capability gating.** Panels appear/disappear per
   `reader.capabilities`.

Phase 1 is doable today entirely against llrpkit's emulator — the seam can be
proven with no WYUAN unit in hand.

## Open questions

- **Do we actually have a WYUAN (or other proprietary) unit on the way?** That
  decides whether driver #2 is a real build or stays a documented stub.
- **Emulator for proprietary drivers?** llrpkit's emulator is LLRP-only. A fake
  WYUAN would let the `wyuan` driver be CI-tested with no hardware — worth it if we
  commit to that vendor. (Mirrors how the LLRP emulator made llrpkit testable.)
- ~~**Naming.**~~ Settled: **OmniTag RFID**, package `omnitag`. Reserve the name on
  PyPI early (an empty first release) so nobody else claims it while you build —
  same lesson llrpkit just taught.

## Why this is the right shape

It keeps llrpkit clean (a strength, not a limitation), turns "llrpkit only speaks
LLRP" from a wall into a *layer*, and makes the hard-won downstream work — the
policy engine, the decode, the dashboard — pay off across every reader you ever
add. The mixed-fleet warehouse gets one pane of glass; you get a platform story
built on a library you already shipped.
