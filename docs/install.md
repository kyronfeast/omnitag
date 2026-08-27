# Install

OmniTag needs **Python 3.11 or newer**. You do not need any RFID hardware to try
it — a built-in emulator stands in for a real reader.

## From source (today)

OmniTag is developed in the open on GitHub. Until the first PyPI release, install
it straight from the repository:

```console
$ git clone https://github.com/kyronfeast/omnitag
$ cd omnitag
$ pip install -e ".[dev]"
```

The `-e` means "editable" — changes you make to the code take effect without
reinstalling. The `[dev]` part pulls in the test and lint tools.

## Optional extras

Some readers need an extra library. Install only what you use:

```console
$ pip install -e ".[wyuan]"    # serial (WYUAN / UHFReader288) readers — adds pyserial
```

The LLRP (Impinj) driver needs nothing extra — its dependency, `llrpkit`, is
always installed.

## From PyPI (coming with the first release)

Once OmniTag cuts its first versioned release, installing will be a single line:

```console
$ pip install omnitag            # core + LLRP driver
$ pip install "omnitag[wyuan]"   # add the serial WYUAN driver
```

!!! note "Why not yet?"
    The package name is already reserved on PyPI, but a real release waits until
    the WYUAN serial driver is confirmed against a physical reader. Publishing is
    a promise that `pip install omnitag` gives you working code, and version
    numbers can't be reused — so we hold the first release until it's proven.

## Check it worked

```console
$ python -c "import omnitag; print(omnitag.__version__)"
0.0.1
```

Then head to the [Quickstart](quickstart.md) to see it stream tags.
