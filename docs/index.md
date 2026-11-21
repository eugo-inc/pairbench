---
description: "pairbench runs two sides in paired, alternating rounds beside identical twins, measures the noise and gives each case a verdict: real difference or noise."
---

# Is a benchmark difference real or noise?

pairbench is an open-source (Apache-2.0) Python command-line tool that says whether a measured
difference between two sides of a benchmark is real or noise. It answers that for one workload
on one machine: it runs each side in paired, alternating rounds beside an identical twin,
measures the noise from the twins, and gives every case a verdict.

A difference is called real only when it is wider than the measured noise and an exact sign
test, corrected for testing several cases, says it is not luck.

```
pairbench run --side new=image:myorg/app:2.0 --side old=image:myorg/app:1.9 -- python bench.py
```

Example output (made-up numbers):

```
new against old (baseline)

case    new     old     change        noise  p        verdict
matmul  1.92 s  2.41 s  1.26x faster  ±1.8%  0.0010*  FASTER
fft     0.88 s  0.89 s  1.01x faster  ±2.1%  1.0*     TIE

Exact two-sided sign test over 16 paired rounds.
* corrected for testing 2 cases at once.
Rule: strict.
Machine state: quiet.
Baseline: old.
Positive control old~twice: ok.
```

It does not replace benchmark tools. It launches them, one launch per side per round, and
reads what they produce.

## Where to go next

- [Install](install.md) and the [quick start](quickstart.md) for a first run.
- [Concepts](concepts.md): sides, twins, rounds, cases and verdicts.
- [Method](method/index.md): how a verdict is reached, and why.
- [Guides](guides/index.md): one per benchmark tool pairbench reads.
- [Reference](reference/index.md): commands, config, files and the Python API.
- [Showcases](showcases.md): worked comparisons with pinned public images.
- [For AI agents](agents.md): the loop, the exit codes and how to report a result.

## Principles

1. A verdict needs a measured noise floor and a significant direction. Without both, the
   tool prints the numbers and says why there is no verdict.
2. The same evidence is required for a win, a loss and a tie.
3. Every figure is computed by code from the capture.
4. Every degradation is loud. A check that could not run never counts as a pass.
5. The core has no runtime dependencies beyond the Python standard library.
6. Everything is non-interactive: no prompts, no terminal needed, and the exit code says
   what happened.
