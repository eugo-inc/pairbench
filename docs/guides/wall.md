---
description: "The wall driver, the default: the run time of each launch from the launch's own clock, for image, command and Python environment sides."
---

# Compare the run time of two images or commands

Give two sides and no driver: the default driver, `wall`, records the run time of each launch
as the case `wall`, from the launch's own clock.

## What it reads

- **Command and Python environment sides**: the interval around the process.
- **Image sides**: the container's own start-to-finish time, from the engine. An image side
  also gives the secondary case `launch`: the time on this machine from the start request to
  the exit.
- **File sides**: nothing; a file side has no launch clock.

Both values come from the launch's own clock, not from anything the workload printed. The
driver wraps no tool and reads no file.

## Example

```
pairbench run --side new=image:myorg/app:2.0 --side old=image:myorg/app:1.9 -- python bench.py
```

## What the value includes

A `wall` value of a command side includes the start of a process and what pairbench does
around it. A cost that both sides pay alike moves a ratio toward 1. Each run measures that
cost and gives a note when it is more than one percent of a `wall` median; see
[launch cost](../method/launch-cost.md). To time the work alone, print timings from inside the
workload and use the [`lines`](lines.md) driver.

The value also includes everything the workload does before and after its work: importing
modules, reading input, writing output. When those differ between the sides, the difference
is part of the result.

## Cases

| Case | Unit | Better | Kind | Primary |
|---|---|---|---|---|
| `wall` | s | lower | time | yes |
| `launch` (image sides) | s | lower | time | no |

Plus the resource cases under `res/` that every launch gives.
