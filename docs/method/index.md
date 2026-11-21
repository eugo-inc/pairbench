---
description: "The chain behind every verdict: paired rounds, a noise floor from twins, the exact sign test, a correction for several cases and the rule that combines them."
---

# How does pairbench decide?

In steps: paired rounds in a rotating order, a noise floor measured from twins in the same run,
an exact sign test for each case, a correction for testing several cases, and a rule that turns
them into a verdict. Each page below explains one step: what pairbench does, why, and what a
reader of a result can rely on.

## How a verdict is reached

1. [Paired rounds](paired-rounds.md): every side runs once per round, in an order that
   rotates and reverses, so that drift and position affect every side alike.
2. [Noise floor](noise-floor.md): each side runs beside an identical twin; the gap between
   them is the noise of this machine, at this load, in this run.
3. [Sign test](sign-test.md): an exact test of whether one side is lower in more rounds than
   chance would give.
4. [Multiple comparisons](multiple-comparisons.md): testing several cases at once needs a
   correction, or one of them comes out significant by luck.
5. [Verdicts](verdicts.md): the rule that combines the gap, the bar and the p-value, every
   outcome and reason, and how to report one.

## Checks on the instrument and the machine

- [Shared machines](shared-machines.md): quiet at the start is not quiet throughout; pinning,
  locks, witnesses and disturbed rounds.
- [Instrument controls](instrument-controls.md): every analysis tool needs a case that must
  pass and a case that must fail.
- [Positive control](positive-control.md): twice the work must read as twice the value.
- [Launch cost](launch-cost.md): what a launch costs before the workload runs.
- [Simulated error rates](error-rates.md): how often the default rule gives each outcome
  when the true difference is known.

## Serving and energy

- [First-token definitions](first-token-definitions.md): what each load tool puts inside its
  time-to-first-token stopwatch.
- [Energy per token](energy-per-token.md): what is measured, what is left out, and when no
  value is given.

## Beyond the verdict

- [Diagnostics](diagnostics.md): resource figures, counters, sampled stacks and flame graphs.
- [Pitfalls](pitfalls.md): common ways a benchmark fools its author.
- [Reporting checklist](reporting-checklist.md): what a published comparison should state.
