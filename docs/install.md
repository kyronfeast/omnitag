# Install

OmniTag needs **Python 3.11 or newer**. You do not need any RFID hardware to try
it — a built-in emulator stands in for a real reader.

## From PyPI

```console
$ pip install omnitag
```

That gives you the core (driver seam, fleet manager, Zebra printer) plus the LLRP
(Impinj) driver — its dependency, [`llrpkit`](https://pypi.org/project/llrpkit/),
is always installed.

## Optional extras

Some readers need an extra library. Install only what you use:

```console
$ pip install "omnitag[wyuan]"    # serial (WYUAN / UHFReader288) readers — adds pyserial
```

The quotes matter on most shells — without them the square brackets get
interpreted by the shell.

## From source (for development)

To hack on OmniTag itself, or to run the examples and tests:

```console
$ git clone https://github.com/kyronfeast/omnitag
$ cd omnitag
$ pip install -e ".[dev]"
```

The `-e` means "editable" — changes you make to the code take effect without
reinstalling. The `[dev]` part pulls in the test and lint tools.

## Check it worked

```console
$ python -c "import omnitag; print(omnitag.__version__)"
0.1.0
```

Then head to the [Quickstart](quickstart.md) to see it stream tags.

!!! note "What's proven, and what isn't"
    The LLRP driver runs on the same protocol stack llrpkit ships for Impinj
    readers and is exercised against its emulator. The WYUAN serial driver and
    the Zebra ZT411 encoder are verified line-by-line against their vendors' SDK
    sources and programming guides — but not yet on a physical unit. If you run
    either on real hardware, an issue with what you saw (working or not) is the
    most valuable contribution you can make right now.
