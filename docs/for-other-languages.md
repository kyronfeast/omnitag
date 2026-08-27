# Using OmniTag from C#, C++, or any language

OmniTag's *library API* is Python. But you do **not** have to write Python to use
it. The trick is to integrate at the **data boundary**, not the code boundary:
run OmniTag as a small service that owns the readers and emits a plain stream of
tags, then consume that stream from your app in whatever language you like.

```
   readers ──► OmniTag service (Python)  ──►  JSON stream  ──►  your app
                (drivers + fleet + policy)     (stdout /          (C#, C++, Java,
                                                MQTT / HTTP)        Node, …)
```

Your language never links against Python. It just reads JSON — something every
language does out of the box.

## The pattern

`examples/service.py` is a complete, runnable example. Its heart is a few lines:

```python
async for sourced in fleet.stream(policy=policy):
    emit(sourced)   # one tag → one JSON message
```

The `emit` function decides *how* the tag leaves the process. Three common choices:

### 1. Standard output (simplest)

Print one JSON object per line. Your app runs the service as a subprocess and
reads its output, or you pipe it to a file. Run it now, no hardware:

```console
$ python examples/service.py
{"reader": "dock", "epc": "e2000017...", "antenna": 3, "rssi_dbm": -52.0, "category": null, "at": 1770950400.11}
{"reader": "line-4", "epc": "e2000017...", "antenna": 4, "rssi_dbm": -61.3, "category": null, "at": 1770950400.11}
```

### 2. MQTT (best for more than one consumer)

Publish each tag to a broker topic; any number of apps subscribe. Swap `emit`
for a publish (using `paho-mqtt`, `aiomqtt`, etc.):

```python
client.publish("omnitag/tags", line)   # line = the same JSON string
```

Your C# app subscribes with any MQTT client (e.g. MQTTnet) — no Python involved.

### 3. Webhook (best for one consumer)

POST batches of tags to an HTTP endpoint your app exposes. Your C# / ASP.NET (or
C++, or Node) endpoint receives ordinary JSON requests.

## The message shape

Every tag is one JSON object with these fields:

| Field | Type | Meaning |
|---|---|---|
| `reader` | string | which reader in the fleet saw it |
| `epc` | string (hex) | the tag's EPC (its ID) |
| `antenna` | number or null | antenna that read it |
| `rssi_dbm` | number or null | signal strength (null when the reader gives raw units, e.g. WYUAN) |
| `category` | string or null | label assigned by the ignore policy, if any |
| `at` | number | Unix timestamp |

`epc` is the field you can always rely on; the rest are present with `null` where
not applicable. Keep this shape stable and downstream teams can build against it
without reading any Python.

## Consuming it — a C# sketch

Reading the stdout stream from a C# app is just:

```csharp
var psi = new ProcessStartInfo("python", "examples/service.py")
    { RedirectStandardOutput = true, UseShellExecute = false };
using var proc = Process.Start(psi)!;
string? line;
while ((line = proc.StandardOutput.ReadLine()) != null)
{
    var tag = JsonSerializer.Deserialize<TagReport>(line);
    // ... your business logic ...
}
```

For MQTT, subscribe to `omnitag/tags` with MQTTnet and deserialize the same JSON.

## When you *don't* need OmniTag at all

If your shop is C# and you only run **Impinj** readers, Impinj ships the **Octane
SDK for .NET** natively — you may not need OmniTag. Its value shows up when you
have a **mix** of reader brands, or you want the host-side ignore policy applied
uniformly across them. Even then, you get it by running OmniTag as the service
behind your C# app, exactly as above.

## Reusing the protocol knowledge, not the code

You can't import OmniTag's Python into C++. But the
[WYUAN protocol reference](wyuan-protocol.md) is language-neutral — a C++ team
could implement the same serial protocol natively from that page. The MQTT and
webhook message shapes above are the contract; the protocol doc is the recipe.
