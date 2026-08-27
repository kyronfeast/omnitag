# Drivers

A **driver** teaches OmniTag how to talk to one kind of reader. Whatever the
reader speaks underneath, a driver turns its reads into the same normalized tag
the rest of OmniTag understands.

| Driver | Reader family | Connection | How it runs |
|---|---|---|---|
| [`LLRPDriver`](llrp.md) | Impinj R700 / Speedway, any LLRP reader | Network (TCP) | shares the main loop (`isolation="loop"`) |
| [`WyuanReader`](wyuan.md) | WYUAN / UHFReader288 family | Serial (RS232 / USB) | own worker thread (`isolation="thread"`) |

Every driver is an async context manager (`async with`), exposes
`capabilities`, and streams tags from `inventory()`. That sameness is what lets a
`Fleet` mix them freely.

## Adding a new reader

Writing a driver for a new reader is the *only* work needed to support it —
nothing else in OmniTag changes. Two shapes cover almost everything:

- **Network / async reader** → wrap it like `LLRPDriver`: implement the four
  `ReaderDriver` methods and declare `isolation="loop"`.
- **Serial / blocking reader** → subclass `ThreadedDriver` like `WyuanReader`:
  implement `_read_blocking` (yield tags from the blocking SDK) and `_build_caps`
  (declare `isolation="thread"`). The base class handles threads, the handoff
  queue, policy, and backpressure for you.

See [Contributing](../contributing.md) for the development setup.
