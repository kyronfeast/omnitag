"""WyuanReader — a serial UHFReader288-family driver for OmniTag.

A blocking serial reader, so it is a :class:`~omnitag.threaded.ThreadedDriver`:
the poll loop runs on its own worker thread and reads flow into the async merge
through the base class, meaning a WYUAN reader can share a fleet with an Impinj
LLRP reader without either starving the other.

The loop is *polled* inventory: send the 0x01 command, read the response
frame(s), yield each tag, repeat. The reader's own scan time paces it.

Transport is injectable — pass any object with ``read(n)`` / ``write(b)`` /
``close()``. In production that's a ``serial.Serial`` (pyserial, the ``[wyuan]``
extra); in tests it's a fake, so the whole driver is verified without hardware.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Protocol

from llrpkit import TagReport

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
        read_timeout: float = 3.0,
        transport: SerialTransport | None = None,
        max_queue: int = 1000,
    ) -> None:
        super().__init__(reader_id=reader_id or f"wyuan:{port}", max_queue=max_queue)
        self._port = port
        self._baudrate = baudrate
        self._adr = adr
        self._antenna = antenna
        self._antenna_count = antenna_count
        self._scan_time = scan_time
        self._q_value = q_value
        self._session = session
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
            raise RuntimeError(
                "WyuanReader needs pyserial: pip install 'omnitag[wyuan]'"
            ) from exc
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
        )

    # -- blocking poll loop (runs on the worker thread) ---------------------

    def _read_blocking(self, stop: threading.Event) -> Iterator[TagReport]:
        transport = self._transport
        assert transport is not None
        cmd = p.build_inventory(
            q_value=self._q_value,
            session=self._session,
            adr=self._adr,
            antenna=self._antenna,
            scan_time=self._scan_time,
        )
        while not stop.is_set():
            transport.write(cmd)
            yield from self._drain_inventory(transport, stop)

    def _drain_inventory(
        self, transport: SerialTransport, stop: threading.Event
    ) -> Iterator[TagReport]:
        while not stop.is_set():
            frame = _read_frame(transport)
            if frame is None:
                return  # timeout — re-poll
            try:
                resp = p.parse_frame(frame)
            except p.ProtocolError:
                return  # resync by re-polling
            if resp.re_cmd != p.INVENTORY:
                return
            if p.status_carries_tags(resp.status):
                for t in p.parse_inventory(resp.data)[0]:
                    yield TagReport(epc=t.epc, antenna=t.antenna, rssi_dbm=None)
                if resp.status == p.ST_MORE:
                    continue  # 0x03: further tags in the next frame(s)
            return  # terminal status (done / timeout / mem-full / statistic)


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
