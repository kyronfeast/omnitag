# WYUAN / UHFReader288 serial protocol — driver reference

Distilled from the *UHF RFID Reader Series User Manual V2.20* and **verified
against the vendor's own SDK**: the *UHFReader288.DLL manual V3.0*, the C++ demo
(`UHFReader288VC/Page1.cpp`) and the C# demo (`UHFReader288Demo/RWDev.cs`) that
ship with W-series readers. This is what `omnitag.drivers.wyuan` implements.

## Link settings

Serial (UART/USB-serial): **57600 baud, 8 data bits, no parity, 1 stop bit**,
least-significant bit first. Point-to-point — one reader per port. Default device
address `0x00`; `0xFF` is broadcast. Bytes within a frame must arrive less than
15 ms apart or the reader discards the partial frame (manual §2).

## Framing

```
Command  (host→reader):  Len  Adr  Cmd            Data[]  CRC_L CRC_H
Response (reader→host):  Len  Adr  reCmd  Status   Data[]  CRC_L CRC_H
```

- `Len` counts every byte after itself → a full frame on the wire is `Len + 1`
  bytes. Command `Len = len(Data) + 4`; response `Len = len(Data) + 5`.
- **CRC16**: poly `0x8408`, preset `0xFFFF`, over `Len..Data[]`, appended
  little-endian (LSB then MSB). A frame is valid when CRC16 over the *entire*
  frame (including its CRC) is `0x0000`. Implemented verbatim from the manual's C
  reference in `protocol.crc16`.

## Inventory (command `0x01`) — what the driver polls

Command `Data[]`: `QValue, Session` (+ optional `Target, Ant, ScanTime` as a
set — the DLL calls this "express inventory"). The driver sends `Q=4, S0` by
default; pass `antenna=` to add the optional trio (`Ant = 0x80 + (n-1)`, up to
`0x8F` = antenna 16). `ScanTime` is in 100 ms units; `0` = no limit.

The `QValue` byte is **flags + Q**, not just Q:

| bit | meaning | driver knob |
|---|---|---|
| 7 | send a `0x26` statistic packet after the inventory | `statistics=True` |
| 6 | "special strategy" (vendor-defined) | — |
| 5 | Impinj **FastID**: EPC + TID in one block | `fast_id=True` |
| 4 | append phase + frequency to every tag | `phase=True` |
| 3–0 | Q (0–15) | `q_value=` |

Response `Data[]` (tag-bearing statuses): `Ant, Num, EPC-1, EPC-2, …` where each
EPC block is:

```
len(1) | EPC(N) | RSSI(1) [ | phase(4) + freq(3)  if len bit6 set ]
   bit7 = EPC+TID (FastID; last 12 bytes are TID)   bit6 = phase/freq   bits5-0 = N
```

Statuses: `0x01` done · `0x02` timeout (tags still valid) · `0x03` more frames
follow · `0x04` partial/out-of-memory · `0x26` statistic packet (no EPCs) ·
`0xF8` antenna error. The driver reads frames until a terminal status, following
`0x03` chains.

## Real-time push mode (reCmd `0xEE`)

A reader configured into *real-time inventory mode* (manual §8.4.22) **ignores
`0x01` polls** and pushes frames on its own. The driver recognises these and
consumes them in the same loop, so a reader left in that mode still streams:

```
status 0x00  Data[] = Ant, Len, EPC/TID(Len), RSSI      ← one tag, NO Num byte
status 0x28  Data[] = PacketNo(4), AntStatus(1/4/8/16), TotalCount(4)   ← heartbeat
```

This is exactly what the vendor's C# demo parses in `RWDev.workProcess` (it
hunts for the `EE 00` header, then reads Ant at offset 4 and Len at offset 5).

## The three fields that used to be marked VERIFY — now settled

| field | verdict | source |
|---|---|---|
| **EPC length unit** | **bytes** — `N = len & 0x3F` is a byte count | Manual §8.4.22: "Len: 1 byte, the **byte** length of the EPC/TID." C++ demo: `memcpy(EPC1, &EPC[m], EPClen)`. C# demo: `Substring(12, (length & 0x3F) * 2)` (hex chars = bytes × 2). |
| **Antenna byte** | **bitmask on 1/4/8-port** readers (`0x04` → ant 3); **0-based index on 12/16-port** readers (`0` → ant 1) | Manual §8.2.1 and DLL manual §3.2.1 (which adds the 12-port case). `WyuanReader(antenna_count=…)` selects the decode: > 8 ports = index mode. |
| **RSSI** | **raw** one-byte reading, not dBm | Vendor demo displays the byte with `%d`; no calibration anywhere in the SDK. Driver sets `TagReport.rssi_dbm=None`, keeps the byte in `InventoryTag.rssi_raw`. |

## Not yet wired (present in the protocol, easy follow-ons)

Read/Write/Write-EPC/Kill (`0x02`–`0x05`), GPIO (`0x8.4.10/11`), power and
frequency config, the buffered-inventory commands, and *switching* a reader into
or out of real-time mode (`0x8.4.22`). The polled `0x01` path is the robust
baseline; these extend `WyuanReader` when needed and would flip the matching
capability flags on.
