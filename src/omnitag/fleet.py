"""The fleet manager: drive N readers of mixed type as one stream.

In plain words: a "fleet" is just a group of readers running at the same time.
This file lets you hand it several readers of any mix — Impinj, WYUAN, whatever —
and get back **one** combined feed of tags, where each tag still remembers which
reader saw it. One set of ignore rules covers the whole group. It's the "one
screen for all my readers" piece.


A :class:`Fleet` runs each driver's inventory concurrently and merges every
observation into a single async stream of :class:`~omnitag.driver.SourcedTag`
— one pane of glass over a mixed set of readers. Because every driver yields
the same normalized ``TagReport``, one host-side ignore policy, one GS1 decode,
and one dashboard apply uniformly across the whole fleet, regardless of which
protocol each reader speaks underneath.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from omnitag.driver import DriverCapabilities, ReaderDriver, SourcedTag

_DONE = object()  # sentinel: one driver's inventory finished


class Fleet:
    """A set of already-connected drivers, streamed together.

    Use inside an ``async with`` block after each driver is connected::

        async with LLRPDriver("10.0.0.1") as a, LLRPDriver("10.0.0.2") as b:
            fleet = Fleet([a, b])
            async for sourced in fleet.stream(max_tags=100, policy=policy):
                handle(sourced.reader_id, sourced.tag)

    ``stream`` options are passed verbatim to every driver's ``inventory`` — so
    a single ``policy=`` filters the entire fleet host-side.
    """

    def __init__(self, drivers: Sequence[ReaderDriver]) -> None:
        if not drivers:
            raise ValueError("a fleet needs at least one driver")
        self.drivers: list[ReaderDriver] = list(drivers)

    @property
    def capabilities(self) -> list[DriverCapabilities]:
        """Each reader's capabilities — what the dashboard gates panels on."""
        return [d.capabilities for d in self.drivers]

    async def stream(self, **opts: Any) -> AsyncIterator[SourcedTag]:
        """Merge every driver's inventory into one stream, tagged by reader.

        Ends when *all* drivers' inventories end. A single driver raising does
        not sink the others: its exception is surfaced once the merged stream
        drains, so partial fleet output is never silently lost.
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        errors: list[BaseException] = []

        async def pump(driver: ReaderDriver) -> None:
            rid = driver.capabilities.reader_id
            try:
                async for tag in driver.inventory(**opts):
                    await queue.put(SourcedTag(reader_id=rid, tag=tag))
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 — reported after drain
                errors.append(exc)
            finally:
                await queue.put(_DONE)

        tasks = [asyncio.create_task(pump(d)) for d in self.drivers]
        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item is _DONE:
                    remaining -= 1
                    continue
                yield item
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if errors:
            raise errors[0]
