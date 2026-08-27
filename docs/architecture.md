# Architecture

OmniTag is small on purpose. It's built around one idea — a **common shape every
reader plugs into** — and a few pieces that hang off it. This page walks through
them. (For the full design rationale and history, see `DESIGN.md` in the repo.)

## The one shape: a normalized tag

No matter which reader saw a tag, OmniTag hands your code the same object: a
llrpkit `TagReport` — an EPC (the tag's ID), which antenna saw it, signal
strength, timestamps, and (once a policy runs) a category label. Everything
downstream works on this one shape and never has to care where the tag came from.

## The seam: `ReaderDriver`

A **driver** is a translator for one kind of reader. Its whole job is to turn that
reader's native protocol into a stream of normalized tags. The contract is
deliberately tiny — the only thing a driver *must* do is stream inventory:

```python
class ReaderDriver(Protocol):
    @property
    def capabilities(self) -> DriverCapabilities: ...
    async def __aenter__(self) -> "ReaderDriver": ...
    async def __aexit__(self, *exc) -> None: ...
    def inventory(self, **opts) -> AsyncIterator[TagReport]: ...
```

Optional abilities (GPIO, reading/writing tag memory) aren't forced on every
driver. Instead a driver **advertises** what it can do through
`DriverCapabilities`, and callers check that instead of hard-coding "if it's an
Impinj…". A dashboard shows the GPIO panel only when `capabilities.gpio` is true.

## The drivers

- **`LLRPDriver`** — the reference driver. A thin adapter over
  [llrpkit](https://pypi.org/project/llrpkit/)'s `Reader`, so Impinj R700 /
  Speedway readers (and anything else speaking LLRP) are handled by mature code.
  It's async-native, so it declares `isolation="loop"`.
- **`WyuanReader`** — a serial reader (UHFReader288 family). Serial reads block,
  so it's built on `ThreadedDriver` and declares `isolation="thread"`. See the
  [WYUAN driver](drivers/wyuan.md) page.

## The fleet

`Fleet` runs many drivers at once and merges everything into one stream of
`SourcedTag` — a tag plus the id of the reader that produced it. One ignore
policy passed to `fleet.stream(policy=...)` filters the **whole** fleet. So a
mixed set of readers becomes one pane of glass.

## Why this shape

The value of an RFID system isn't the wire protocol — it's what you do with the
tags: filtering, decoding, presence tracking, feeding an ERP, a dashboard. That
work is written **once**, against the normalized tag, and every reader you ever
add gets it for free. Adding a new brand of reader means writing one driver, not
touching anything else.

## What's next

- Panels/features that light up per `DriverCapabilities` (a capability-gated
  dashboard).
- More drivers, one per vendor family, as hardware calls for them.

See [Keeping it light](concurrency.md) for how readers of very different speeds
share one program without stepping on each other.
