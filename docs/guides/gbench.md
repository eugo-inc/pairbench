---
description: "The gbench driver runs a Google Benchmark program once per side per round and reads the median real time of each benchmark from its JSON output."
---

# Compare Google Benchmark results

Pass `--driver gbench` and run your Google Benchmark program as the workload: pairbench reads
its JSON output and compares the median real time of each benchmark.

Format read from the tool's own source, `src/json_reporter.cc` at v1.8.3 and v1.9.4
([source](https://github.com/google/benchmark/blob/v1.9.4/src/json_reporter.cc)), and
checked against the output of a real run of version 1.8.3.

## What it adds to the command

`--benchmark_out=<file> --benchmark_out_format=json`. A command that already names
`--benchmark_out` or `--benchmark_out_format` is refused.

## What it reads

The entries of `benchmarks[]` whose `run_type` is `iteration`; aggregate entries (mean,
median, standard deviation) are ignored. The entries of one benchmark name are its
repetitions. Per name:

| Case | Value | Metric | Primary |
|---|---|---|---|
| the benchmark name | median of the entries' `real_time`, converted from `time_unit` to seconds | `real_time` | yes |
| `<name>/cpu_time` | median of `cpu_time` | `cpu_time` | no |

- A benchmark that reported an error or a skip in any entry is left out and named in a note.
- A file with aggregate entries only, as `--benchmark_report_aggregates_only` writes it, has
  no repetition to read and is refused.
- The format has no per-iteration samples.
- The version is `context.library_version`, which the tool writes from 1.8.4 on.

## Example

```
pairbench run --side new=image:myorg/bench:2.0 --side old=image:myorg/bench:1.9 \
  --driver gbench -- /usr/local/bin/my_benchmarks --benchmark_repetitions=5
```

Use `--benchmark_repetitions` to give each launch several entries per benchmark; the driver
takes their median. Use `--benchmark_filter` to choose benchmarks; every benchmark it keeps
is a primary case, and the [correction for testing several cases](../method/multiple-comparisons.md)
grows with their number.

Tool documentation: [Google Benchmark user guide](https://github.com/google/benchmark/blob/main/docs/user_guide.md).
