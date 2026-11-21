---
description: "Each side runs beside an identical twin in the same rounds; how far the side sits from its twin is its noise floor, measured at the same load as the comparison."
---

# How is the noise floor measured?

With twins: every side runs beside an identical copy of itself in the same rounds, and how far
the median ratio of side to twin lies from one is that side's noise floor for a case.

## Twins

Every side gets a **twin** by default: an identical copy, made from the side's own resolved
settings, that runs in the same rounds. A twin's name is the side's name with `~same` added.
The twin is never declared as a separate side, and a twin whose identity differs from its
side's refuses the analysis (`E_TWIN_DRIFT`).

Two identical things should read as equal. Whatever separates a side from its twin is noise:
the noise of this machine, at this load, in this run, measured with the same workload and the
same instrument as the comparison it will judge.

## The floor

For side `X` with twin `X~same` on case `c`, over the rounds in which both have a value:

```
t_i        = X_i / X~same_i
floor(X,c) = abs(median(t_i) - 1)
```

For a group `g` of cases the floor is the largest floor of its cases:
`floor(X, g) = max(floor(X, c) for c in g)`. By default a group is every case that shares a
metric and a role (primary or secondary); a case may name a smaller group in the config
(`cases.groups.NAME`). Each resource case under `res/` is a group of its own.

What else the results hold about the floor:

- A floor computed from fewer than 8 rounds is marked `provisional`.
- Rounds whose `t_i` lies outside the Tukey fences, 1.5 times the interquartile range beyond
  the quartiles, are named. They are never dropped.
- The interquartile range of `t_i` divided by its median is recorded as `spread`, for
  information. A spread too large to be a finite number is not given.
- If a side's comparison with its own twin is significant by the sign test (uncorrected p
  below 0.05), the results carry a loud note: the side differs from an identical copy of
  itself more often than chance, so the machine or the order is biasing the run.

## The bar

Under the default rule the **bar** a gap must exceed is the subject's floor plus the
baseline's floor. Both sides need a twin: a comparison where only one side has a floor gets
`NO VERDICT (one_sided_floor)`, and one where neither has gets `NO VERDICT (no_floor)`.

A floor of exactly zero, which identical noise-free values give, gives the affected cases
`NO VERDICT (zero_floor)`: a bar of zero would call any difference real. A value of zero or
less on a side or its twin leaves that side without a floor for the group, and every case in
the group gets `NO VERDICT (nonpositive_value)`. A round is never left out to keep a floor.

A side so far from its twin that the floor is no finite number has no floor either, and every
case that uses it gets `NO VERDICT (too_far_apart)`; so does a case whose two floors are too
large to add up to a bar that is a finite number as a percentage. The ratio of a side to its
twin counts as a finite number only when its inverse and its percent difference are too.

## Why the floor must come from the same run and the same load

Noise is not a property of a workload alone. It depends on the machine, its temperature, the
other work on it, and the order of launches. A floor measured yesterday, on a quiet machine,
or with a different workload, says nothing about the noise in today's comparison. Two
failures follow from a floor taken elsewhere:

- A floor from a quieter time is too narrow. Today's noise passes the bar and reads as a
  difference.
- A floor from a busier time is too wide. A real difference hides inside it and reads as a
  tie.

Twins share every round with the sides they measure, so they see the same drift, the same
neighbours and the same positions. When the machine is busier, the twins drift apart more
and the floor widens. That is why pairbench can keep running on a busy machine under the
default `warn` mode: the bar widens with the noise instead of the run being void.

## Floor on one side only

A floor measured on one side says nothing about the other side's noise: a side that starts
more processes, reads more files or uses more cores can be noisier than its rival. The
default rule therefore needs both floors and adds them.

## Other rules

The default rule is `strict`. A caller of the Python API may build another rule with a
different floor scope (`case`, `side` or `experiment`) or bar (`twice_larger`,
`twice_experiment_max`); every field of the rule used is recorded in the results. See
[verdicts](verdicts.md).
