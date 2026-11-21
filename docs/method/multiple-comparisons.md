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
