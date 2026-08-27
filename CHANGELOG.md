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
- Tests against llrpkit's emulator (no hardware), an `examples/demo.py`, and the
  architecture note in `DESIGN.md`.

## [0.0.1] - name reservation

Placeholder release reserving the `omnitag` name on PyPI.
