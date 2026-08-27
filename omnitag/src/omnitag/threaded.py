"""``ThreadedDriver`` — the safe home for blocking vendor SDKs.

A vendor SDK that *blocks* (waits synchronously for the next read) must never
run on the shared event loop: a single blocking call freezes the servicing of
every other reader, which is exactly the co-hosted-SDK starvation that takes
mixed-reader sites down. This base class runs the blocking read loop on a
dedicated worker thread and bridges each read into an asyncio queue, so the loop
stays free for async-native drivers and no reader can starve another.

A concrete driver subclasses this and implements just two things: a blocking
iterator of tags (`_read_blocking`) and its capabilities (`_build_caps`, which
should declare ``isolation="thread"``). Everything else — the thread lifecycle,
the thread-safe hand-off, host-side policy, bounded backpressure — is handled
here, once, correctly.

CPU notes baked in: the queue is *bounded* and drops oldest when full, so a slow
sink can never balloon memory or spin the loop; and subclasses must **block**
waiting for reads, never busy-poll — a ``while True: poll()`` spin burns a whole
core doing nothing.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from typing import Any

from llrpkit import TagReport

from omnitag.driver import DriverCapabilities

_STOP = object()  # sentinel: the worker thread has finished


class ThreadedDriver:
    """Base for drivers wrapping a blocking SDK. Runs it off the event loop."""

    def __init__(self, *, reader_id: str, max_queue: int = 1000) -> None:
        self.reader_id = reader_id
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._caps: DriverCapabilities | None = None

    @property
    def capabilities(self) -> DriverCapabilities:
        if self._caps is None:
            raise RuntimeError("capabilities are available only after connect()")
        return self._caps

    async def __aenter__(self) -> ThreadedDriver:
        self._loop = asyncio.get_running_loop()
        await self._connect()
        self._caps = self._build_caps()
        self._thread = threading.Thread(
            target=self._run, name=f"omnitag-{self.reader_id}", daemon=True
        )
        self._thread.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._stop.set()
        await self._disconnect()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 5.0)

    # -- worker thread ------------------------------------------------------

    def _run(self) -> None:
        """Runs on the worker thread: pump the blocking SDK into the queue."""
        try:
            for tag in self._read_blocking(self._stop):
                if self._stop.is_set():
                    break
                self._put_threadsafe(tag)
        except BaseException as exc:  # noqa: BLE001 — surfaced on the async side
            self._put_threadsafe(exc)
        finally:
            self._put_threadsafe(_STOP)

    def _put_threadsafe(self, item: Any) -> None:
        loop = self._loop
        if loop is None:
            return

        def _put() -> None:
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                # bounded backpressure: drop the oldest read to stay light
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(item)
                except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                    pass

        loop.call_soon_threadsafe(_put)

    # -- async side ---------------------------------------------------------

    async def inventory(self, **opts: Any) -> AsyncIterator[TagReport]:
        """Stream tags off the queue, applying host-side policy like llrpkit.

        Recognizes ``policy=`` (a llrpkit ``ReaderPolicy``) and ``max_tags=``;
        other options are accepted and ignored so a fleet can pass one option
        set to every driver.
        """
        policy = opts.get("policy")
        max_tags = opts.get("max_tags")
        count = 0
        while True:
            item = await self._queue.get()
            if item is _STOP:
                break
            if isinstance(item, BaseException):
                raise item
            tag: TagReport = item
            if policy is not None:
                decision = policy.evaluate(tag)
                if not decision.keep:
                    continue
                tag = replace(tag, category=decision.category, item_label=decision.item_label)
            yield tag
            count += 1
            if max_tags is not None and count >= max_tags:
                break

    # -- subclass hooks -----------------------------------------------------

    async def _connect(self) -> None:
        """Open the vendor SDK / connection. Override if needed."""

    async def _disconnect(self) -> None:
        """Close the vendor SDK / connection. Override if needed."""

    def _build_caps(self) -> DriverCapabilities:  # pragma: no cover - abstract
        raise NotImplementedError("subclasses must build DriverCapabilities(isolation='thread')")

    def _read_blocking(self, stop: threading.Event) -> Iterator[TagReport]:  # pragma: no cover
        """Yield ``TagReport``s from the blocking SDK until ``stop`` is set.

        MUST block waiting for the next read (never busy-poll) and MUST check
        ``stop.is_set()`` between reads so shutdown is prompt.
        """
        raise NotImplementedError
