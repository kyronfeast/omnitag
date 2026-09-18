"""WyuanReader — a serial UHFReader288-family driver for OmniTag.

In plain words: this is the translator for a WYUAN reader plugged in over a serial
cable. It uses the byte "phrasebook" from `protocol.py` to keep asking the reader
"what tags do you see?" and turns each reply into OmniTag's common tag record.
Because serial reads make the program wait, it sits on the safe background-thread
base (`ThreadedDriver`) so it can share a group with faster readers without
slowing them down.


A blocking serial reader, so it is a :class:`~omnitag.threaded.ThreadedDriver`:
the poll loop runs on its own worker thread and reads flow into the async merge
through the base class, meaning a WYUAN reader can share a fleet with an Impinj
LLRP reader without either starving the other.

The loop is *polled* inventory: send the 0x01 command, read the response
frame(s), yield each tag, repeat. The reader's own scan time paces it. If the
reader has been configured into *real-time* mode (it ignores polls and pushes
one ``0xEE`` frame per tag instead), the same loop simply consumes those pushes.

Wire format and field meanings are verified against the vendor's SDK and demo
sources — see ``docs/wyuan-protocol.md``.

**Sensor-gated reading** (``gpi_trigger=True``): a photo eye wired to the
reader's IN1 tells us when something is in front of the antenna. The worker
thread polls the pin (``0x47``) and only runs inventory while it's active,
yielding a ``GPIEdge`` at each transition so :meth:`windows` can hand back one
bundle of tags per object — including an *empty* bundle for an object that
passed with no readable tag. This uses the reader's *answering* mode rather
than its built-in trigger mode, because in the built-in mode the reader stops
answering GPIO queries and the host can no longer tell a missed tag from no
object at all.

Transport is injectable — pass any object with ``read(n)`` / ``write(b)`` /
``close()``. In production that's a ``serial.Serial`` (pyserial, the ``[wyuan]``
extra); in tests it's a fake, so the whole driver is verified without hardware.
"""

from __future__ import annotations

import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any, Protocol

from llrpkit import GPIEdge, InventoryWindow, TagReport

from omnitag.driver import DriverCapabilities
from omnitag.drivers.wyuan import protocol as p
from omnitag.threaded import ThreadedDriver


class SerialTransport(Protocol):
    """The slice of a serial port this driver needs."""

    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


class WyuanReader(ThreadedDriver):
    """Poll a UHFReader288-family reader over serial and stream normalized tags."""

    def __init__(
        self,
        port: str | None = None,
        *,
        reader_id: str | None = None,
        baudrate: int = 57600,
        adr: int = p.DEFAULT_ADR,
        antenna: int | None = None,
        antenna_count: int = 4,
        scan_time: int = 2,
        q_value: int = 4,
        session: int = 0,
        fast_id: bool = False,
        gpi_trigger: bool = False,
        gpi_active_high: bool = False,
        gpi_poll_interval: float = 0.02,
        read_timeout: float = 3.0,
        transport: SerialTransport | None = None,
        max_queue: int = 1000,
    ) -> None:
        """Configure a reader; nothing is opened until ``async with``.

        ``antenna_count`` matters beyond capabilities: readers with more than 8
        ports report the antenna as a plain index rather than a bitmask, and the
        driver decodes accordingly. ``scan_time`` is in 100 ms units (``0`` =
        unlimited). ``fast_id`` asks Impinj Monza tags for their TID alongside
        the EPC (``TagReport.tid``).

        ``gpi_trigger`` gates reading on the reader's IN1 line: inventory runs
        only while the pin is at the active level — *low* by default, since
        IN1 is a pulled-up TTL input that a sensor or relay contact pulls to
        ground (``gpi_active_high=True`` for the opposite wiring). The pin is
        polled every ``gpi_poll_interval`` seconds while idle. Use
        :meth:`windows` to consume one bundle of tags per trip. Requires the
        reader's answering mode, which the driver selects on start.
        """
        super().__init__(reader_id=reader_id or f"wyuan:{port}", max_queue=max_queue)
        self._port = port
        self._baudrate = baudrate
        self._adr = adr
        self._antenna = antenna
        self._antenna_count = antenna_count
        self._scan_time = scan_time
        self._q_value = q_value
        self._session = session
        self._fast_id = fast_id
        self._gpi_trigger = gpi_trigger
        self._gpi_active_high = gpi_active_high
        self._gpi_poll_interval = gpi_poll_interval
        self._read_timeout = read_timeout
        self._transport = transport

    async def _connect(self) -> None:
        if self._transport is not None:
            return
        if self._port is None:
            raise ValueError("WyuanReader needs a serial port (or an injected transport)")
        try:
            import serial  # type: ignore[import-untyped]  # pyserial — the [wyuan] extra
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise RuntimeError("WyuanReader needs pyserial: pip install 'omnitag[wyuan]'") from exc
        self._transport = serial.Serial(
            self._port,
            baudrate=self._baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self._read_timeout,
        )

    async def _disconnect(self) -> None:
        if self._transport is not None:
            self._transport.close()

    def _build_caps(self) -> DriverCapabilities:
        return DriverCapabilities(
            reader_id=self.reader_id,
            kind="wyuan",
            model="UHFReader288",
            antenna_count=self._antenna_count,
            isolation="thread",  # blocking serial — runs off the loop
            gpio=False,  # supported by the reader (0x8.4.10); not yet in this driver
            tag_access=False,  # read/write/kill exist in the protocol; not yet wired
            rssi_dbm=False,  # reader gives raw RSSI units, not calibrated dBm
            gpi_trigger=self._gpi_trigger,
        )

    async def windows(self, **opts: Any) -> AsyncIterator[InventoryWindow]:
        """One :class:`~llrpkit.InventoryWindow` per trip of IN1.

        Requires ``gpi_trigger=True`` at construction. The active level comes
        from the reader's own wiring config (``gpi_active_high``), so a fleet
        can pass the same options to every reader regardless of how each is
        wired. Accepts ``policy=``, ``settle=``, ``max_open=``.
        """
        if not self._gpi_trigger:
            raise RuntimeError(
                f"reader {self.reader_id!r} was not constructed with gpi_trigger=True"
            )
        opts.pop("gpi_trigger", None)  # the fleet may pass LLRP-style options through
        opts.pop("gpi_active_high", None)
        async for w in super().windows(port=1, active_high=self._gpi_active_high, **opts):
            yield w

    # -- blocking poll loop (runs on the worker thread) ---------------------

    def _read_blocking(self, stop: threading.Event) -> Iterator[TagReport | GPIEdge]:
        transport = self._transport
        assert transport is not None
        cmd = p.build_inventory(
            q_value=self._q_value,
            session=self._session,
            adr=self._adr,
            antenna=self._antenna,
            scan_time=self._scan_time,
            fast_id=self._fast_id,
        )
        if not self._gpi_trigger:
            while not stop.is_set():
                transport.write(cmd)
                yield from self._drain_inventory(transport, stop)
            return
        yield from self._gated_loop(transport, stop, cmd)

    def _gated_loop(
        self, transport: SerialTransport, stop: threading.Event, cmd: bytes
    ) -> Iterator[TagReport | GPIEdge]:
        """Poll IN1; inventory only while it's active; yield an edge per change.

        Runs on the worker thread. Each inventory poll lasts the reader's scan
        time, after which the pin is re-checked — so the release is noticed
        within one scan time, and a pail already present at start-up opens a
        window immediately.
        """
        # Answering mode is required (real-time modes ignore GPIO queries).
        # Idempotent on the reader; the reply is consumed and ignored.
        transport.write(p.build_set_work_mode(p.MODE_ANSWERING, adr=self._adr))
        _read_frame(transport)
        last: bool | None = None
        while not stop.is_set():
            status = self._query_gpio(transport)
            if status is None:
                time.sleep(self._gpi_poll_interval)  # no reply — don't spin
                continue
            high = status.in1_high
            active = high == self._gpi_active_high
            if last is None:
                last = high
                if active:  # something is already in front of the antenna
                    yield GPIEdge(port=1, high=high, at=time.time())
            elif high != last:
                last = high
                yield GPIEdge(port=1, high=high, at=time.time())
            if active:
                transport.write(cmd)
                yield from self._drain_inventory(transport, stop)
            else:
                time.sleep(self._gpi_poll_interval)

    def _query_gpio(self, transport: SerialTransport) -> p.GPIOStatus | None:
        """One ``0x47`` round trip; ``None`` on timeout or an unrelated frame."""
        transport.write(p.build_gpio_get(adr=self._adr))
        frame = _read_frame(transport)
        if frame is None:
            return None
        try:
            resp = p.parse_frame(frame)
            if resp.re_cmd != p.GPIO_GET or resp.status != 0:
                return None
            return p.parse_gpio_status(resp.data)
        except p.ProtocolError:
            return None

    def _to_report(self, t: p.InventoryTag) -> TagReport:
        # RSSI stays None: the reader's byte is raw, uncalibrated (see protocol.py).
        return TagReport(epc=t.epc, antenna=t.antenna, rssi_dbm=None, tid=t.tid)

    def _drain_inventory(
        self, transport: SerialTransport, stop: threading.Event
    ) -> Iterator[TagReport]:
        n_ant = self._antenna_count
        while not stop.is_set():
            frame = _read_frame(transport)
            if frame is None:
                return  # timeout — re-poll
            try:
                resp = p.parse_frame(frame)
            except p.ProtocolError:
                return  # resync by re-polling
            if resp.re_cmd == p.REALTIME:
                # Reader is in real-time push mode: one tag per 0xEE frame, and
                # 0x28 heartbeats when idle. Keep consuming; never re-poll.
                if resp.status == p.RT_TAG:
                    try:
                        yield self._to_report(p.parse_realtime_tag(resp.data, antenna_count=n_ant))
                    except p.ProtocolError:
                        pass
                continue
            if resp.re_cmd != p.INVENTORY:
                return
            if p.status_carries_tags(resp.status):
                try:
                    tags, _ = p.parse_inventory(resp.data, antenna_count=n_ant)
                except p.ProtocolError:
                    return  # malformed payload — drop the frame, re-poll
                for t in tags:
                    yield self._to_report(t)
                if resp.status == p.ST_MORE:
                    continue  # 0x03: further tags in the next frame(s)
            return  # terminal status (done / timeout / mem-full / statistic / ant error)


def _read_exact(transport: SerialTransport, n: int) -> bytes | None:
    """Read exactly n bytes; None if the stream times out first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = transport.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _read_frame(transport: SerialTransport) -> bytes | None:
    """Read one full response frame (Len byte, then Len more bytes)."""
    head = _read_exact(transport, 1)
    if not head:
        return None
    rest = _read_exact(transport, head[0])
    if rest is None:
        return None
    return head + rest
