# Contributing

You do **not** need an RFID reader to work on OmniTag — llrpkit's emulator and a
fake serial port are the development targets, so the whole suite runs on any
laptop.

## Setup

```console
$ git clone https://github.com/kyronfeast/omnitag
$ cd omnitag
$ pip install -e ".[dev]"
```

## The checks

```console
$ pytest                       # the test suite (hardware-free)
$ ruff check src tests         # lint
$ ruff format src tests        # format
$ mypy src                     # type-check
$ mkdocs serve                 # preview these docs at http://127.0.0.1:8000
```

All three of tests, ruff, and mypy should be clean before a change lands.

## How the code is organized

```
src/omnitag/
  driver.py          the seam: ReaderDriver, DriverCapabilities, SourcedTag
  threaded.py        ThreadedDriver: safe base for blocking (serial) readers
  fleet.py           Fleet: merge many readers into one stream
  drivers/
    llrp.py          Impinj / LLRP driver (wraps llrpkit)
    wyuan/           WYUAN serial driver: protocol.py (codec) + driver.py
```

## Adding a driver

The common cases are covered in [Drivers → Adding a new reader](drivers/index.md).
The short version: a network reader implements the `ReaderDriver` protocol; a
blocking serial reader subclasses `ThreadedDriver` and implements
`_read_blocking` + `_build_caps`. Add tests that drive it through a fake
transport so it stays hardware-free.

## A note on comments

OmniTag aims to be readable by someone who isn't a Python expert. Every module
opens with a plain-language explanation of *why it exists* before the code
starts, and the tricky lines say *why*, not just *what*. Please keep that style.
