# Keeping it light (concurrency & CPU)

This page explains, in plain terms, one design choice that matters a lot when you
run more than one reader in the same program.

## The problem: a slow reader dragging down a fast one

Imagine two people sharing one phone line. Person A takes quick calls; person B
takes calls that put them on hold for two minutes each. If they share the *same*
line, A can't take a call while B is on hold — A is stuck waiting. Worse, calls
for A pile up and some get dropped.

Software readers have the same trap. A fast network reader (Impinj/LLRP) can hand
you hundreds of reads a second. A cheap serial reader might *block* — sit and wait
— between reads. Run them in the same "line" (the program's event loop) and the
blocking one freezes the fast one. Reads pile up in the reader's small memory
buffer and get thrown away. From the outside it just looks like "tags are going
missing."

## The fix: give the slow reader its own line

Each OmniTag driver declares how it needs to run, in one field —
`DriverCapabilities.isolation`:

| isolation | meaning | used by |
|---|---|---|
| `"loop"` | Well-behaved, never blocks — safe to share the main line | LLRP / Impinj |
| `"thread"` | Blocks between reads — gets its own worker line | WYUAN / serial |
| `"process"` | Prone to hanging or crashing — gets a whole separate program | (reserved) |

A blocking driver is built on **`ThreadedDriver`**, which runs its read loop on
its own worker thread and passes reads back to the main program through a small
handoff queue. The fast reader never waits on the slow one — proven by a test and
visible in the `mixed_fleet` demo, where the fast reader gets ~60 reads while the
slow one gets ~2 in the same window.

## Why not just isolate everything?

Because isolation isn't free. A whole separate program per reader uses more
memory and CPU. Well-behaved readers that never block are happiest sharing one
line — it's the cheapest option and costs nothing. **Match the isolation to the
reader; don't pay for it when you don't need it.**

## Three habits that keep CPU low

1. **Send summaries, not the firehose.** A tag read 300 times a second can become
   one "arrived" and one "left" event. That single change is the biggest saver
   for a modest server (llrpkit's presence tracker does this).
2. **Wait, don't spin.** A blocking reader must *wait* for the next read (using
   almost no CPU), never loop asking "anything yet? anything yet?" (which pins a
   whole CPU core doing nothing). OmniTag's `ThreadedDriver` is built to wait.
3. **Cap the buffers.** The handoff queue is bounded and drops the oldest read
   when full, so a slow downstream system can never balloon memory or spin the
   program.
