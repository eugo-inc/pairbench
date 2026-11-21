---
description: "What hyperfine, pyperf, benchstat, Google Benchmark's compare.py and asv do, from their own documentation, and where pairbench differs in approach."
---

# How does pairbench compare with other benchmarking tools?

Most of these pieces exist in other tools. pairbench combines paired alternating rounds, a
measured same-against-same noise floor, an exact sign test and a correction for testing several
cases, with container images as first-class sides and built-in readers for several benchmark
tools.

If you know a tool that does the same, tell us.

The tools below are described only by what their own documentation says, at the version
read. A tool may do more than its documentation states; corrections are welcome as issues.

## hyperfine

Read: the [README](https://github.com/sharkdp/hyperfine/blob/v2.0.0/README.md) at v2.0.0.

- A command-line benchmarking tool. It runs warm-up runs (`--warmup`), at least 10 runs by
  default, and "statistical outlier detection to detect interference from other programs and
  caching effects".
- It benchmarks several commands in one invocation, in the order given, the first as the
  reference, and its Markdown export has a relative-speed column.
- Parameter scans (`--parameter-scan`), preparation commands (`--prepare`) and JSON export.
- The README does not say whether runs of different commands are interleaved.

pairbench can launch hyperfine inside each side and read its JSON export with the
[`hyperfine` driver](guides/hyperfine.md); the comparison between sides is then pairbench's.

## pyperf

Read: the [command-line documentation](https://github.com/psf/pyperf/blob/2.11.0/doc/cli.rst)
and [how a benchmark is run](https://github.com/psf/pyperf/blob/2.11.0/doc/run_benchmark.rst)
at 2.11.0.

- A toolkit for Python benchmarks. It runs a benchmark in several processes and ignores the
  first value of each process as a warm-up.
- `pyperf compare_to` compares saved results with Student's two-sample, two-tailed t-test;
  its example table shows "Not significant" for a difference that is not.
- `pyperf system tune` changes system settings to make results more stable.

## benchstat

Read: the
[package documentation](https://pkg.go.dev/golang.org/x/perf@v0.0.0-20261009192801-be2c69fb417e/cmd/benchstat)
at commit `be2c69f`.

- Computes statistical summaries of Go benchmark results and A/B comparisons: a median with a
  confidence interval per benchmark, and a Mann-Whitney U-test with α = 0.05 between
  configurations; `~` marks a difference that is not significant.
- It recommends interleaving the runs of the configurations being compared, and at least 10
  runs, ideally 20.
- It warns that running the benchmarks again until a difference appears is a form of multiple
  testing.

## Google Benchmark's compare.py

Read: [`docs/tools.md`](https://github.com/google/benchmark/blob/v1.10.0/docs/tools.md) at
v1.10.0.

- Compares two benchmark runs, or two filters of one run, and prints the relative difference
  `(new - old) / |old|` for time and CPU time.
- With repetitions, it runs a Mann-Whitney U test; the documentation asks for no fewer than 9
  repetitions for the test to be meaningful.

pairbench can launch a Google Benchmark binary inside each side and read its JSON output with
the [`gbench` driver](guides/gbench.md).

## asv (airspeed velocity)

Read: the [user documentation](https://asv.readthedocs.io/en/v0.6.6/using.html) and the
[command reference](https://asv.readthedocs.io/en/v0.6.6/commands.html) at 0.6.6.

- Benchmarks a Python project over its commit history and publishes the results as a web
  site.
- Each benchmark runs in its own process, in environments that asv builds (conda,
  virtualenv, rattler, uv).
- `asv compare` and `asv continuous` list a benchmark whose ratio is beyond `--factor`, 1.1 by
  default; `asv compare` marks statistically insignificant results with `~`.

## Where pairbench differs in approach

These are differences of design, each with its cost:

| | pairbench |
|---|---|
| What is compared | whole sides: container images, Python environments, commands, servers, or result files |
| Order | every side once per round, the order rotating and reversing; balance checked |
| Noise | measured by twins in the same rounds, per side and group of cases |
| Test | the exact sign test on paired rounds, Holm-corrected over the primary cases |
| Verdict | needs both a gap wider than the noise and a significant direction; a tie needs the opposite |
| Cost | twins and the positive control double the launches or more; a run takes longer than a single comparison of two tools would |

pairbench does not replace the tools above. It launches several of them, reads what they
produce, and compares the sides round by round.
