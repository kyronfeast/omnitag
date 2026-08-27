# OmniTag RFID

**One interface for every RFID reader.**

Warehouses rarely run just one kind of RFID reader. You might have a premium
Impinj reader on the main dock and a rack of cheaper readers on the pick lines —
and each brand speaks its own language to your software. OmniTag is the layer
that makes them all look the same to the rest of your system.

## The idea, in plain words

Every RFID reader ultimately does one job: it sees a tag and reports it. But a
reader from one company talks over the network in a protocol called *LLRP*, while
a reader from another company talks over a serial cable in its own private
format. Written separately, that's two codebases, two data shapes, two headaches.

OmniTag puts a **translator** in front of each reader — a *driver* — so that no
matter which reader saw a tag, your software receives the **same tidy record**.
From there, one set of rules (an "ignore policy"), one dashboard, and one data
feed cover the whole mixed fleet.

```
   Impinj reader ─┐
   (LLRP)         │   ┌───────────┐   one normalized
                  ├──►│  OmniTag   ├──► stream of tags ──► your policy,
   WYUAN reader ─┘    │  (drivers  │                        dashboard, ERP
   (serial)           │  + fleet)  │
                      └───────────┘
```

## What's here today

- A **driver seam** — the common shape every reader plugs into.
- A **fleet manager** — run many readers at once, merged into one stream.
- Two real drivers: **LLRP** (Impinj R700 / Speedway, via
  [llrpkit](https://pypi.org/project/llrpkit/)) and **WYUAN** (a serial
  UHFReader288-family reader).
- A **concurrency model** that keeps a slow reader from dragging down a fast one,
  and keeps CPU use low — see [Keeping it light](concurrency.md).

## Where to start

- New here? Read [Install](install.md), then [Quickstart](quickstart.md) — it
  runs a two-reader demo with **no hardware required**.
- Want the big picture of how it fits together? See [Architecture](architecture.md).
- Wiring a specific reader? See the [Drivers](drivers/index.md) pages.

!!! note "Built on llrpkit"
    OmniTag stands on top of [llrpkit](https://pypi.org/project/llrpkit/), a
    focused LLRP library. llrpkit handles Impinj readers; OmniTag adds the
    driver layer that lets *other* readers join the same fleet.
