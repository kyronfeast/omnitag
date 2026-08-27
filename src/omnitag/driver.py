"""The driver seam: one interface every reader backend implements.

In plain words: this file defines the "shape" that every reader has to fit. A
reader from any brand gets a small translator (a *driver*) that turns its own
language into the same tidy tag record. Because they all fit the same shape, the
rest of the program never has to know or care which brand of reader it's talking
to. This file is that shape (`ReaderDriver`), a description of what a given reader
can do (`DriverCapabilities`), and a tag stamped with which reader saw it
(`SourcedTag`).


OmniTag's whole idea lives here. A :class:`ReaderDriver` turns some reader's
native protocol into a stream of llrpkit :class:`~llrpkit.TagReport` objects —
the normalized unit the entire value layer (policy, GS1 decode, presence,
sinks, dashboard) already consumes. llrpkit's LLRP ``Reader`` is the reference
implementation; other vendors slot in behind the same contract.

A driver advertises what it can actually do via :class:`DriverCapabilities`, so
callers branch on *capabilities*, never on vendor. The one thing every driver
must do is stream inventory; GPIO and tag memory access are optional and gated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from llrpkit import TagReport


@dataclass(frozen=True)
class DriverCapabilities:
    """What a reader behind a driver can actually do — vendor-neutral.

    Callers and the dashboard read these fields instead of special-casing a
    vendor: show the GPIO panel only when ``gpio`` is true, offer tag writes
    only when ``tag_access`` is true, and so on. ``host_side_policy`` is always
    true — OmniTag filters the normalized stream after the fact, so ignore
    policies work even on readers with no on-reader filtering of their own.
    """

    reader_id: str
    kind: str  # "llrp", "wyuan", ...
    model: str = ""
    firmware: str = ""
    antenna_count: int = 0
    #: how this driver must be run so it never starves the others:
    #: "loop"    — async-native, safe to share the event loop (llrpkit)
    #: "thread"  — wraps a blocking SDK; runs on its own worker thread
    #: "process" — flaky/native SDK; full process isolation
    #: The fleet reads this to place each driver correctly. A blocking driver
    #: declared "loop" would recreate the classic co-hosted-SDK starvation, so
    #: this field is how OmniTag makes that mistake impossible.
    isolation: str = "loop"
    #: optional features, gated by drivers that support them
    gpio: bool = False
    tag_access: bool = False
    rssi_dbm: bool = True
    #: host-side ignore policy always works — it acts on the normalized stream
    host_side_policy: bool = True
    #: room for vendor extras (Octane phase/Doppler/TID, etc.) without a schema change
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourcedTag:
    """A normalized tag plus which reader in the fleet produced it.

    A single driver yields bare :class:`~llrpkit.TagReport`. A :class:`Fleet`
    of several readers yields these, so a merged stream never loses track of
    origin.
    """

    reader_id: str
    tag: TagReport


@runtime_checkable
class ReaderDriver(Protocol):
    """The contract. Minimal on purpose: stream inventory, know your limits.

    A driver is an async context manager. ``inventory()`` is the only required
    capability — a reader that can *only* stream tags is still a valid driver.
    Optional operations (``gpio``, ``read_tag``, ``write_tag``) are advertised
    through :attr:`capabilities` and simply absent on drivers that lack them.
    """

    @property
    def capabilities(self) -> DriverCapabilities: ...

    async def __aenter__(self) -> ReaderDriver: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    def inventory(self, **opts: Any) -> AsyncIterator[TagReport]:
        """Stream normalized tags until the driver's stop condition."""
        ...
