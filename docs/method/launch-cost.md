---
description: "Every run measures what starting a process costs with an empty command; when that cost matters, and how to time the work alone."
---

# What does a launch cost before the workload runs?

The start of a process and what pairbench does around it, which a `wall` value of a command or
Python environment side includes; every such run measures that cost with an empty command and
reports it.

## What a launch costs before the workload runs

A `wall` value of a command side or a Python environment side holds the start of a process
and what pairbench does around it, as well as the workload. Each run measures and reports
that cost.

During warm-up, when the lineup has a command side or a Python environment side, pairbench
launches an empty command, the system's `true`, through the same launch path, 20 times
(`launch_cost.launches`; 0 turns the measurement off). When `true` cannot be found, the
measurement is skipped with a loud note. The capture gets one record, and the results carry
the same under `launch_cost` (made-up numbers):

```json
{"t": "launch_cost", "command": "true", "n": 20, "median_s": 0.0005,
 "p25_s": 0.0004, "p75_s": 0.0007, "min_s": 0.0003}
```

The figures `launch_cost.median` and `launch_cost.spread` (`p75_s - p25_s`) can be filled
into a document with `pairbench fill`.

The figure is an upper bound on what pairbench adds to a `wall` value: it is the tool's own
work plus the operating system's start of a process.

## When it matters

A cost that both sides pay alike moves a ratio toward 1. If a launch costs `c` and the work
takes `a` on one side and `b` on the other, the measured ratio is `(a + c) / (b + c)`, not
`a / b`. The smaller the work, the larger the effect.

pairbench gives a loud note for every `wall` case of a command side or a Python environment
side whose median is less than the launch-cost median divided by `launch_cost.note_share`.
The default share is 0.01, a chosen number: the note appears when the cost is more than one
percent of the value. With a launch-cost median of 0.0005 s, a `wall` case with a median of
0.04 s gets the note and one with 0.06 s does not. It is a note, never a refusal.

Not affected, and given no note:

- cases timed inside the process: `lines`, `gbench`, `pytest-benchmark` and the other tool
  drivers;
- image sides, whose `wall` value is the engine's own time for the container, so pairbench
  is outside it. No cost is measured for a lineup of image sides only. An image side adds
  the secondary case `launch`, the time of the whole start.

The [positive control](positive-control.md) catches a constant cost too: with a cost inside
the interval equal to one run of the work, the control reads 1.5x instead of 2.0x and fails.

## How to time the work alone

Time the work inside the workload and print the result for the
[`lines` driver](../guides/lines.md):

```python
import json
import time

start = time.perf_counter()
run_the_work()
elapsed = time.perf_counter() - start
print("::pairbench::", json.dumps({"case": "work", "value": elapsed}))
```

The start of the process, the import of modules and pairbench's own work then fall outside
the value. A benchmark tool with its own timer, such as Google Benchmark or
pytest-benchmark, does the same through its driver.

When the start-up itself is what you want to compare, keep `wall`, and say in the report that
the value includes the start of a process.

## Where pairbench runs

With `--cpus`, pairbench moves its own process and its sampler threads onto CPUs outside the
pinned set, where the platform allows it. `import pairbench` imports no sub-package, and a
command imports only what it needs, so the tool's own start stays small and outside every
measured value.
