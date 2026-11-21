---
description: "The terms pairbench uses on every page: side, baseline, twin, lineup, round, launch, case, primary case, noise floor, bar, verdict, capture and results."
---

# What are sides, twins, rounds, cases and verdicts?

pairbench compares **sides**, the things being measured, in **rounds** of launches beside a
**twin** of each side, and gives every **case** a **verdict**. This page defines each term the
other pages use, and they link here for it.

## Sides

A **side** is one thing being compared: a container image, a command, a Python environment, a
server image, or a set of result files from another tool. Each side has a name.

| Kind | Spec | What a launch is | Identity recorded |
|---|---|---|---|
| `cmd` | a full command line, or `{workload}` wrapped in one | a subprocess | hash of the resolved executable file and the argument list |
| `image` | a container image reference | a fresh named container, started by image ID, removed after | image ID, digest hashes, platform |
| `python`, `venv`, `conda` | an interpreter path, a virtual environment, or a conda environment name | the workload run with that interpreter | `python -VV` output, prefix, hash of the sorted installed-distribution list |
| `serve` | a server image, its arguments, a port and a readiness check | a server start, with a load tool driving it | image ID and arguments |
| `file` | result files from another tool, one per round | none | hash of each file |

On the command line a side is `--side NAME=KIND:SPEC`; in a config file it is a
`[sides.NAME]` table. The workload after `--` is shared by every side, with one exception: an
image side that gives its own `args` in the config runs those in place of the workload.

The **baseline** is the side every other side is compared against: the last side named,
unless `--baseline NAME` says otherwise. Every other side is a **subject**.

Every side is identified before the run and again after it. Two sides with the same identity
and launch settings that run in the same working folder are the same side and are refused
(`E_SAME_SIDE`); one program run in two working folders, such as two checkouts, is two sides,
compared with a note that never names the folders. A side whose identity changed during the
run fails the capture (`E_SIDE_CHANGED`).

## Twins

A **twin** is an identical copy of a side that runs in the same rounds. Its name ends in
`~same`. The gap between a side and its twin is the measured noise: two identical things
should read as equal, so whatever separates them is the noise of this machine, at this load,
in this run. Every side gets a twin by default; `--same-vs-same off` turns them off, and
without twins the default rule cannot give a verdict.

## The positive control

The **positive control** is one more entry in every round: the baseline started once with
the workload run twice in it. Its name ends in `~twice`. It must read as twice the value. See
[positive control](method/positive-control.md).

## Lineup, rounds and launches

The **lineup** is the ordered list of sides and twins: `new, new~same, old, old~same`. A
**round** is one launch of every lineup entry, in an order that rotates and reverses from
round to round, followed by the positive control. A **launch** is one start-to-finish
execution of one lineup entry. One discarded **warm-up** launch per side comes before the
first round. See [paired rounds](method/paired-rounds.md).

## Cases

A **case** is one named measurement a launch produces, such as a benchmark name with a
metric. A **primary case** counts toward the verdict and toward the correction for testing
several cases at once; a **secondary case** is compared and graded with its uncorrected
p-value and never changes the exit code. A case has a unit, a direction (`better`: `lower`,
`higher` or `none`) and a kind (`time`, `rate`, `efficiency`, `count` or `other`). A case whose
`better` is `none` describes and does not judge; it is always secondary. The resource
figures of every launch are such cases, under `res/`.

## Noise floor and bar

The **noise floor** of a side on a case is how far the side sits from its twin, as a
fraction: the median of the per-round ratios of side over twin, less one, without its sign.
The **bar** is the size a gap must exceed before it can be called a difference; under the
default rule it is the subject's floor plus the baseline's floor. See
[noise floor](method/noise-floor.md).

## Verdicts

For each subject and case, the values are paired round by round. The **ratio** is the median
of the per-round ratios of subject over baseline, and the **gap** is how far it lies from 1.
An exact **sign test** counts the rounds in which the subject was lower and those in which
it was higher, and the p-values of all primary cases are corrected together.

| Verdict | When |
|---|---|
| FASTER or SLOWER (BETTER or WORSE for a case that is not a time) | the gap is wider than the bar and the direction is significant |
| TIE | the gap lies inside the bar and the direction is not significant |
| UNRESOLVED | one of the two holds and the other does not, or a downgrade applies |
| NO VERDICT | the comparison cannot be graded, for a stated reason |

Programs read the stable `outcome` and `reason` fields, never the display word. See
[verdicts](method/verdicts.md).

## Capture and results

A run writes one folder. The **capture**, `capture.jsonl`, is the raw, private record of the
run, one record per line. It keeps the command line as typed, credentials included, so it is
never shared. The **results**, `results.json`, are the analysed output of one or
more captures, meant to be shared: they hold no host name, user name, path outside the run
folder or value of the environment, except an image reference you ask for and the forms that
the [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists as known limits
of the shown command. The command they show hides the secret forms that
[what the shared files hide](reference/config.md#what-the-shared-files-hide) lists, but a
short plain value that nothing on that list names, such as one given after an option of one
letter, as a plain argument or in the path of an address, is shown: give a side a secret
through the environment with `env_pass`. Every number in the results has a **figure** with its
text, which `pairbench fill` puts into documents. See the
[results schema](reference/results-schema.md).

## Explain step and diagnostics

After the measured rounds, each subject and the baseline are launched again under
instruments, untimed. The **diagnostics**, `diagnostics.json`, say how the sides differ in
what they used: resource figures, counters and sampled stacks. They describe and never name a
cause. See [diagnostics](method/diagnostics.md).
