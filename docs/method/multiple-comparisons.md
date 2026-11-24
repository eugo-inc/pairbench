---
description: "Testing many cases makes a lucky pass likely; pairbench corrects the p-values of the primary cases with Holm's method. What the family is and why."
---

# Why are p-values corrected for testing several cases?

Because the more cases a run tests, the more likely one of them passes by luck: pairbench
corrects the p-values of the primary cases with Holm's step-down method, which keeps the chance
of any false verdict among them at the rule's alpha.

## Why a correction is needed

A p-value below 0.05 means that, with no true difference, a result this uneven would turn up
less than one time in twenty. Test twenty cases with no true difference among them and one
of them is expected to pass by luck alone. The more cases a run tests, the more certain such
a false verdict becomes, unless every p-value is corrected for the number of tests.

## Holm's correction

pairbench corrects with Holm's step-down method. It sorts the p-values of the family in
ascending order (stable, ties broken by key) and, with `m` tests:

```
adj[i] = max(adj[i-1], min(1.0, (m - i) * p[i]))      # i = 0 .. m-1, adj[-1] = 0
```

The smallest p-value is multiplied by `m`, the next by `m - 1`, and so on, and no corrected
value is allowed to fall below the one before it. Holm's method controls the chance of any
false verdict in the family at `alpha`, like the plain Bonferroni correction, and it is never
more conservative than Bonferroni.

## Exact arithmetic for the verdict

The verdict is decided in exact arithmetic. Every p-value pairbench grades is an exact sign
test, the fraction `k / 2**n` that `results.json` keeps as `p_raw_fraction`. The correction
runs on these fractions: they are sorted by their exact values, multiplied by `m - i`, kept
from falling below the one before and capped at 1, and the corrected fraction is compared
with alpha read as its shortest decimal text, so 0.05 is exactly 1/20 and 0.01 exactly 1/100.
The same exact alpha sets the fewest rounds, the rounds that must agree and the cases a round
count can judge in the plan, and the positive control; the note that a side differs from its
twin compares its exact corrected fraction with exactly 1/20. No rounding can turn whether a
p-value passes, at any number of rounds. The gap and the bar are compared as floats.

The floats written to the results, `p_raw` and `p_corrected`, are the same correction done in
floats; they are for reading and are not compared. A float p-value passed to
`pairbench.stats.rules.is_significant` by a program of its own is compared as a float with the
float alpha; `pairbench.stats.holm_exact` corrects fractions.

Alpha is read from its shortest decimal text, so an alpha whose binary value is not that
decimal means the decimal. `2 ** -24` reads `5.960464477539063e-08`, just above `2 ** -24`, so
under such an alpha 25 rounds all one way, `p = 2 ** -24`, pass `p < alpha`, and
`min_rounds(1, 2 ** -24)` is 25. Where the decimal text lies below the binary value, as
`2 ** -25` reads `2.9802322387695312e-08`, a rule whose `p_inclusive` is true fails
`p = 2 ** -25` itself. The alpha of a rule from a plug-in, chosen with `--rule`, is read the
same way; every power of two from `2 ** -23` up reads as its own value.

### Checking a verdict by hand

Holm's method steps down: a primary case is significant only when its own check passes and the
check of every case before it in Holm order passes too. Holm order lists the primary cases that
have a p-value by their `p_raw_fraction`, the smallest first, and cases whose fractions are
equal take places next to each other. The cases before a case are the cases with a smaller
p-value and the cases with an equal p-value placed ahead of it. Cases with equal p-values pass
or fail together, whatever their order among themselves: the first of them has the largest
multiplier, so its check decides them all. The check of one case, with
`numerator / denominator` from its `p_raw_fraction`, `m` the `family_size` of the rule and `i`
its place in Holm order counted from 0, is

```
20 * (m - i) * numerator < denominator       # alpha 0.05, the rule strict
```

with `<=` in place of `<` when the rule's `p_inclusive` is true, and `b * (m - i) * numerator
< a * denominator` for an alpha of `a / b`. Two primary cases with `p_raw_fraction` `[2, 64]`
and `m` 2 both fail: the one at place 0 checks `20 * 2 * 2 = 80`, not below 64, and the one
at place 1 passes its own check, `20 * 1 * 2 = 40`, but not the check before it. A
secondary case, and every case under a rule whose `p_source` is `raw`, is checked alone on its
own `p_raw_fraction`, with `m - i` replaced by 1. In whole numbers this check is exact.

A program that holds numbers as IEEE 754 doubles holds every whole number up to `2 ** 53`
exactly, and rounds a product to the nearest double, never past a whole number it holds. For
alpha 0.05 the check then gives the exact answer while the denominator `2 ** n` lies below
`2 ** 53`, that is up to 52 untied rounds: `20 * (m - i) * numerator` never equals a power of
two, since it holds a factor 5, so a product below the denominator is a whole number below
`2 ** 53` and exact, and a product above it never rounds down onto it. A program that keeps
fewer digits of a number than a double holds is exact only as far as the digits it keeps.
`p_raw_fraction` is null from 14285 untied pairs on (see the
[results schema](../reference/results-schema.md)); there the check needs the tail worked out
again, as in the [sign test](sign-test.md).

Known answers, checked by `pairbench selftest`:

| p-values | corrected |
|---|---|
| `[0.01, 0.04, 0.5]` | `[0.03, 0.08, 0.5]` |
| `[0.01, 0.012, 0.5]` | `[0.03, 0.03, 0.5]` |
| `[0.01, 0.04, 0.03]` | `[0.03, 0.06, 0.06]` |
| `[0.03125, 0.03125, 0.21875]` | `[0.09375, 0.09375, 0.21875]` |

## What the family is

The **family** is every comparison of a subject with the baseline on a primary case that has
a p-value. Outside it:

- comparisons of a side with its own twin. For the note that a side differs from its own
  twin, each side gets one combined check across its primary cases, and the checks of the
  sides form a family of their own, corrected together with the same method and kept in
  `twin_checks`; at 8 rounds the note comes only when every untied round of the side leans
  the same way. Each same-against-same row, in `same_vs_same`, keeps its own uncorrected
  p-value;
- secondary cases, which are graded with their uncorrected p-value and never change the exit
  code;
- the positive control.

The family is fixed by the capture. Choosing which cases to display, with `--case` on
`report`, never shrinks it. Reports say "corrected for testing N cases at once", or "one case
tested" when there is one.

A rule whose `p_source` is `raw` grades every case on its uncorrected p-value. Reports then
show that p-value, without a star, and say that no p-value is corrected: the rule does not
correct for testing N cases at once, so a p-value shown can be smaller than the corrected one.
With more than one subject in the family the note counts comparisons, not cases: two subjects
on three primary cases read "testing 6 comparisons at once".
The corrected p-value, never smaller, is still kept in `results.json` as `p_corrected`. The
fewest rounds a verdict needs still grow with the family under such a rule, as the plan and the
refusal `E_TOO_FEW_ROUNDS` count them, unless the rule fixes its own minimum. The built-in rule
grades on the corrected p-value.

A split of 18 against 6 gives p = 0.0227 on its own: a verdict. When it is the smallest of
four p-values, the correction multiplies it by 4, to about 0.09, which is not below 0.05; the
same split reads UNRESOLVED.

## Choosing primary cases

The family size sets the fewest rounds that can give a verdict (see
[sign test](sign-test.md)) and how strong each direction must be. Every driver names default
primary cases; the config key `cases.primary`, a list of glob patterns, chooses others. Make
primary only the cases a decision rests on, and decide before the run. Choosing primary cases
after seeing the results makes the correction meaningless.
