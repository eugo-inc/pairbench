---
description: "The perf driver reads hardware and software counters from perf stat; every counter is a secondary case."
---

# Compare hardware counters from perf stat

Run the workload under `perf stat` and pass `--driver perf`: pairbench reads each hardware and
software counter perf reports as a secondary case.

Format read from the tool's own documentation, `tools/perf/Documentation/perf-stat.txt` of
Linux v6.12, section "CSV FORMAT"
([source](https://github.com/torvalds/linux/blob/v6.12/tools/perf/Documentation/perf-stat.txt)),
and checked against the output of a real run of perf 6.12.

## What it adds to the command

`-x ; -o <file>`, right after the word `stat`: perf then writes one line per event, its
fields separated by `;`. Event names can hold commas, which perf does not quote, so the
driver uses another separator.

The driver reads perf's own options from `stat` up to `--`, or to the end of the command when
there is no `--`, and refuses a command that names its output options there (`-x`,
`--field-separator`, `-o`, `--output`, `-j`, `--json`) or a mode whose lines it does not
read: interval printing (`-I`), no aggregation (`-A`, `--no-aggr`), counts per socket, die,
cluster, cache, core, thread or node (`--per-...`) and `--metric-only`. Put `--` before the
workload's own command when it has options like these.

## What it reads

One case per event, plus `ipc` when both instructions and cycles are counted. Every case is
secondary: counters describe, and the verdict rests on a measured time. Make a counter
primary with `cases.primary` if a decision rests on it. An event reported as not counted or
not supported is a missing case and is named in a note.

## Example

```
pairbench run --side new=image:myorg/app:2.0 --side old=image:myorg/app:1.9 \
  --set launch.perf_counters=true \
  --driver perf -- perf stat -e instructions,cycles,cache-misses -- /app/run
```

The image must hold `perf`; `launch.perf_counters` gives the containers the capability to use
performance counters.

## Permissions

- A command or Python environment side: the system's own setting decides what perf may
  count. pairbench never changes it.
- An image side: the image must hold `perf`, and the launch needs the capability to use
  performance counters, the launch setting `perf_counters = true`. Without it the driver
  refuses with `E_ENGINE_UNSUPPORTED`. See [an image that holds perf](perf-in-an-image.md).

`perf` is an external program, not bundled. The [explain step](../method/diagnostics.md)
uses it too, untimed, after the measured rounds.

Tool documentation: [perf-stat](https://man7.org/linux/man-pages/man1/perf-stat.1.html).
