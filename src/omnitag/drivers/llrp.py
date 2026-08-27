"""The LLRP driver — a thin adapter over llrpkit's ``Reader``.

This is the reference driver and the reason OmniTag can exist cheaply: llrpkit
already turns the LLRP wire protocol into a stream of ``TagReport``, so the
adapter is almost pure delegation. It maps llrpkit's connection lifecycle and
its LLRP-specific ``ReaderCapabilities`` onto OmniTag's vendor-neutral
:class:`~omnitag.driver.DriverCapabilities`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from llrpkit import Reader, TagReport

from omnitag.driver import DriverCapabilities


class LLRPDriver:
    """Drive one LLRP reader (Impinj R700/Speedway, or the llrpkit emulator).

    ``reader_id`` names this reader in a fleet and on downstream payloads;
    it defaults to ``host:port``. Extra keyword arguments flow straight to
    llrpkit's :class:`~llrpkit.Reader` (timeouts, Impinj extensions).
    """

    def __init__(
        self,
        host: str,
        port: int = 5084,
        *,
        reader_id: str | None = None,
        **reader_kwargs: Any,
    ) -> None:
        self.host = host
        self.port = port
        self.reader_id = reader_id or f"{host}:{port}"
        self._reader = Reader(host, port, **reader_kwargs)
        self._caps: DriverCapabilities | None = None

    @property
    def capabilities(self) -> DriverCapabilities:
        if self._caps is None:
            raise RuntimeError("capabilities are available only after connect()")
        return self._caps

    async def __aenter__(self) -> LLRPDriver:
        await self._reader.connect()
        self._caps = self._build_caps()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._reader.close()

    def _build_caps(self) -> DriverCapabilities:
        c = self._reader.capabilities
        is_impinj = getattr(c, "is_impinj", False)
        return DriverCapabilities(
            reader_id=self.reader_id,
            kind="llrp",
            model=str(getattr(c, "model_number", "") or ""),
            firmware=getattr(c, "firmware", "") or "",
            antenna_count=getattr(c, "max_antennas", 0),
            gpio=True,  # LLRP readers support GPIO
            tag_access=True,  # ...and Gen2 tag memory access
            rssi_dbm=True,
            extras={"impinj_octane": bool(is_impinj)},
        )

    def inventory(self, **opts: Any) -> AsyncIterator[TagReport]:
        """Stream normalized tags. Accepts every ``Reader.inventory`` option,
        including ``policy=`` for host-side ignore filtering."""
        return self._reader.inventory(**opts)

    # -- optional capabilities, present because LLRP supports them ----------

    async def get_gpio(self) -> Any:
        """Read GPI/GPO state — delegates to the underlying LLRP reader."""
        return await self._reader.get_gpio()

    async def set_gpo(self, port: int, state: bool) -> None:
        """Drive a GPO output line."""
        await self._reader.set_gpo(port, state)
