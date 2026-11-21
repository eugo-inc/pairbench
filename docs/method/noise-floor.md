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
- Each side with a twin gets one combined check against it, kept in `twin_checks`. In each
  round the side's score is the median over its primary cases on which the side and its twin
  both have a finite value above zero in that round. Each such case gives the log of side
  over twin, turned so that a positive score means the side looks better by the case's
  better direction. An odd number of such cases gives the log in the middle, and an even
  number the mean of the two logs in the middle, so one case gives its own log and two give
  their mean. Secondary and describing cases stay out of the score. The cases are put in
  order by their turned quotients, compared exactly, and the sign of a score is found
  exactly, from whether the middle quotient, or the product of the two middle quotients, is
  above, below or equal to 1. Swapping a side and its twin in one round turns each of its
  quotients over, so the same cases lie in the middle: that round turns the other way and
  the others stay as they were. The scores are tested with the exact sign test, a score of
  exactly zero being a tie that is dropped, and the p-values of the sides are corrected
  together with [Holm's method](multiple-comparisons.md). If a side's corrected p-value is
  below 0.05, the results carry the loud note `twin_differs`: the side differs from an
  identical copy of itself more often than chance across its primary cases, so the machine
  or the order is biasing the run. The correction keeps a run with no real bias from getting
  the note more often than about 1 time in 20, however many cases it has.
- What the note can catch: a bias that moves most primary cases of a side the same way, as
  a machine or an order that treats one copy unfairly does. When more than half of a
  round's cases lean the same way, its median leans with them, however far the other cases
  lie from their twins, so such a bias is caught whether or not one of the side's cases is
  much noisier than the rest. A side with three primary cases misses such a bias more often
  than one with more, as the median of each round then rests on fewer cases. When the bias is
  large beside the noise, so that a side with five or more primary cases rarely misses it, one
  with three can miss it many times as often, and more often still when one of its three
  cases is much noisier: a round then leans with the bias mostly when both other cases do.
- What it catches less often: a difference on one case alone, in a side with three or more
  primary cases. It moves the median of a round only when other cases lean the same way by
  chance; with an odd number of cases, at least half of the others. So however large the
  difference is, and however noisy the other cases are, it gives the note less often than
  the same difference on every primary case of the side would, in any run with enough untied
  rounds for the note. It gives it more often the fewer primary cases the side has and the
  more rounds the run has, so in a side with three primary cases and a long run it can give
  the note in most runs. It still shows in the same-against-same table of the reports, and
  in `same_vs_same` of the results, with its own uncorrected p-value. A side with one
  primary case is scored on that case alone, and one with two on their mean, so there a
  difference on one case can give the note by itself. A bias shared by half or fewer of the
  cases, two of five say, also moves a round only when enough of the others lean the same
  way by chance, so it is caught less often than one shared by most.
- The note needs enough untied rounds. The smallest p-value of a side over `n` untied rounds
  is `2 / 2^n`, below 0.05 only from 6 untied rounds on, and the correction never lowers it,
  so no side gets the note with fewer than 6. The correction multiplies the smallest p-value
  of the run by the number of sides tested, the next smallest by one fewer, and so on, and
  never makes a corrected p-value smaller than the one before it, so a side gets the note
  only when every side with a smaller p-value gets it too. With two sides tested, the side
  with the smaller p-value needs at least 7 untied rounds, and the other can get the note
  with 6 that all lean one way when the first gets it too: 7 of 7 and 6 of 6 both give a
  corrected p-value of 4/128, about 0.031. At 8 rounds, the serving default, it can reach at
  most 6 sides: with 7 sides tested, even a side with 8 of 8 gets a corrected p-value of at
  least 14/256, about 0.055. A side without enough untied rounds never gets the note, and
  then its absence says nothing about bias.
- At 8 rounds the note comes only when every round of the side that is not a tie leans the
  same way, as a verdict at 8 rounds comes only when every round that is not a tie agrees
  (all 8 when none tie). With two sides tested, 8 of 8 give a corrected p-value of 4/256,
  about 0.016, while 7 one way and 1 the other never give the note: their raw p-value is
  18/256, about 0.07, and the correction never makes a p-value smaller (it gives 36/256,
  about 0.14, when the other side's p-value is no smaller). So at 8 rounds the note means
  that all of a side's untied rounds agreed, and its absence says nothing more.

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
