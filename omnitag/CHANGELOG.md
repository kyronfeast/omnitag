# Changelog

All notable changes to OmniTag RFID are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Driver seam** (`omnitag.driver`): `ReaderDriver` protocol, vendor-neutral
  `DriverCapabilities`, and `SourcedTag` (a normalized `TagReport` tagged with
  its origin reader). The one required capability is streaming inventory; GPIO
  and tag access are optional and advertised, not assumed.
- **LLRP driver** (`omnitag.drivers.llrp.LLRPDriver`): the reference driver,
  a thin adapter over llrpkit's `Reader`. Maps llrpkit's LLRP capabilities onto
  `DriverCapabilities` and passes `inventory(policy=...)` straight through, so
  the llrpkit ignore-policy engine works unchanged behind the seam.
- **Fleet manager** (`omnitag.fleet.Fleet`): runs many drivers concurrently and
  merges them into one `SourcedTag` stream. A single `policy=` filters the whole
  fleet host-side; a driver raising does not sink the others.
- **Concurrency model** — drivers declare `isolation` (`"loop"` | `"thread"` |
  `"process"`) on `DriverCapabilities`, and `ThreadedDriver` (`omnitag.threaded`)
  is the safe base for blocking vendor SDKs: it runs the blocking read loop on a
  worker thread and bridges reads into the async merge through a bounded,
  drop-oldest queue, applying host-side policy on the way. A blocking reader
  therefore cannot starve async readers sharing the fleet — the co-hosted-SDK
  failure mode, designed out. See the "Concurrency & CPU" decision record in
  `DESIGN.md`.
- **WYUAN driver** (`omnitag.drivers.wyuan`): a serial UHFReader288-family driver
  built on `ThreadedDriver`. A pure protocol codec (`protocol.py`: CRC16, command
  build, frame + multi-tag inventory parse) and `WyuanReader`, which polls the
  `0x01` inventory command and normalizes tags into `TagReport`. Transport is
  injectable, so the driver is fully tested without hardware (fake serial). Adds
  the `[wyuan]` extra (pyserial) and a protocol reference (`docs/wyuan-protocol.md`)
  including the three fields to VERIFY against a physical reader.
- Tests against llrpkit's emulator (no hardware) including one proving a blocking
  reader does not gate an async one, and one running the WYUAN driver beside an
  LLRP reader in a single fleet under one shared ignore policy; `examples/demo.py`
  and `examples/mixed_fleet.py`; the architecture note in `DESIGN.md`.

## [0.0.1] - name reservation

Placeholder release reserving the `omnitag` name on PyPI.
