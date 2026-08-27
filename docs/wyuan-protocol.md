# WYUAN / UHFReader288 serial protocol — driver reference

Distilled from the *UHF RFID Reader Series User Manual V2.20* (and cross-checked
against the UHFReader288 DLL/demo guides). This is what the `omnitag.drivers.wyuan`
driver implements. If you have a physical reader, this page plus the three
**VERIFY** points below are all you need to confirm the driver against it.

## Link settings

Serial (UART/USB-serial): **57600 baud, 8 data bits, no parity, 1 stop bit**,
least-significant bit first. Point-to-point — one reader per port. Default device
address `0x00`; `0xFF` is broadcast.

## Framing

```
Command  (host→reader):  Len  Adr  Cmd            Data[]  CRC_L CRC_H
Response (reader→host):  Len  Adr  reCmd  Status   Data[]  CRC_L CRC_H
```

- `Len` counts every byte after itself → a full frame on the wire is `Len + 1`
  bytes. Command `Len = len(Data) + 4`; response `Len = len(Data) + 5`.
- **CRC16**: poly `0x8408`, preset `0xFFFF`, over `Len..Data[]`, appended
  little-endian (LSB then MSB). A frame is valid when CRC16 over the *entire*
  frame (including its CRC) is `0x0000`. Implemented verbatim in `protocol.crc16`.

## Inventory (command `0x01`) — what the driver polls

Command `Data[]`: `QValue, Session` (+ optional `Target, Ant, ScanTime` as a
set). The driver sends `QValue=4, Session=0` by default; pass `antenna=` to add
the optional trio (`Ant = 0x80 + (n-1)`).

Response `Data[]` (tag-bearing statuses): `Ant, Num, EPC-1, EPC-2, …` where each
EPC block is:

```
len(1) | EPC(N) | RSSI(1) [ | phase(4) + freq(3)  if len bit6 set ]
   bit7 = EPC+TID (FastID)     bit6 = phase/freq present   bits5-0 = N
```

Statuses: `0x01` done · `0x02` timeout (tags still valid) · `0x03` more frames
follow · `0x04` partial/out-of-memory · `0x26` statistic packet (no EPCs) ·
`0xF8` antenna error. The driver reads frames until a terminal status, following
`0x03` chains.

## The three VERIFY points (confirm on first real read)

The manual is slightly ambiguous on three fields. Each is isolated to one line so
a mismatch is a trivial fix:

1. **EPC length unit** (`protocol.parse_inventory`) — treated as **bytes**
   (`n = len & 0x3F`). If EPCs come back half-length/misaligned, the firmware
   uses words: change to `n = (len & 0x3F) * 2`.
2. **Antenna byte** (`protocol.antenna_from_byte`) — treated as a one-hot bitmask
   (0x04 → antenna 3), correct for 1/4/8-port readers. A **16-port** reader sends
   a plain 0–15 index instead; switch to `ant + 1`.
3. **RSSI** — the reader reports a **raw** value, not calibrated dBm, so the
   driver sets `TagReport.rssi_dbm = None` (and `capabilities.rssi_dbm = False`).
   The raw byte is available in `protocol.InventoryTag.rssi_raw`; a per-model
   calibration curve would be needed to turn it into real dBm.

## Not yet wired (present in the protocol, easy follow-ons)

Read/Write/Write-EPC/Kill (`0x02`–`0x05`), GPIO (`0x8.4.10/11`), power and
frequency config, and the streaming *real-time* / *fast inventory* modes
(`0x8.4.22`, `0x8.4.41`). The polled `0x01` path is the robust baseline; these
extend `WyuanReader` when needed and would flip the matching capability flags on.
