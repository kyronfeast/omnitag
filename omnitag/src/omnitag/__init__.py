"""OmniTag RFID — one interface for every RFID reader.

OmniTag is a multi-vendor reader layer built on top of llrpkit. It defines a
small driver seam (:class:`~omnitag.driver.ReaderDriver`) at the normalized
``TagReport`` boundary, ships the LLRP adapter as the reference driver, and
merges any mix of readers into one stream with :class:`~omnitag.fleet.Fleet`.
The whole llrpkit value layer — ignore policies, GS1 decode, presence events,
MQTT/webhook sinks, the dashboard — is reused unchanged on that stream.

This is an early build; the driver seam and the LLRP driver are in place, with
proprietary-reader drivers to follow.
"""

from omnitag.driver import DriverCapabilities, ReaderDriver, SourcedTag
from omnitag.drivers.llrp import LLRPDriver
from omnitag.drivers.wyuan import WyuanReader
from omnitag.fleet import Fleet
from omnitag.threaded import ThreadedDriver

__version__ = "0.0.1"

__all__ = [
    "DriverCapabilities",
    "Fleet",
    "LLRPDriver",
    "ReaderDriver",
    "SourcedTag",
    "ThreadedDriver",
    "WyuanReader",
    "__version__",
]
