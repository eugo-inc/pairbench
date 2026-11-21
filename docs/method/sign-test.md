---
description: "The exact two-sided sign test pairbench applies to each case: what it counts, how ties are handled, and the fewest rounds that can give a verdict."
---

# What is the exact sign test?

It counts the rounds in which the subject was lower than the baseline and those in which it was
higher, and gives the exact probability of a split at least this uneven if neither side were
truly lower.

## The exact test

For each pair, the subject is either lower than the baseline, higher, or exactly equal. The
**sign test** asks: if neither side were truly lower, how likely is a split at least this
uneven between the rounds where the subject was lower and the rounds where it was higher?

With `n_lower` and `n_higher` the number of pairs on each side, `n` their sum, and every
untied pair a fair coin under the hypothesis of no difference:

```
k    = min(n_lower, n_higher)
tail = sum(comb(n, i) for i in range(k + 1))
p    = min(1.0, (2 * tail) / (1 << n))        # n == 0 gives 1.0
```

The test is two-sided and exact: `tail` and `1 << n` are integers, and the division is the
single floating-point step. The results store the p-value both as a number and as the
fraction `[min(2 * tail, 1 << n), 1 << n]`.

The test uses only the direction of each pair, not its size. A single extreme round cannot
carry a verdict, and no assumption about the shape of the noise is needed.

## Known answers

| Lower against higher | p |
|---|---|
| 12 against 0 | 2/4096 |
| 10 against 2 | 158/4096 |
| 6 against 0 | 0.03125 |
| 5 against 1 | 0.21875 |
| 5 against 0 | 0.0625 |
| 18 against 6 | 0.0227, to four places |
| 0 against 2 | 0.5 |
| 0 against 0 | 1.0 |

`pairbench selftest` checks these on every install.

## Ties

A pair whose two values are exactly equal is a tie. Ties are not trials: they are left out
of `n`. Three rounds lower and three exact ties give p = 0.25, the value for 3 against 0, not
the 0.03125 that counting ties as wins would give. Nine ties and nothing else give 1.0.

## One measurement

One pair gives no p-value. The report says "one measurement, no p-value" and the comparison
is `NO VERDICT (single_measurement)`.

## The fewest rounds that can give a verdict

No p below 0.05 is reachable with fewer than 6 untied pairs: even 5 against 0 gives 0.0625.
With `m` tests corrected together, the smallest p a comparison can reach after the
correction is `m * 2 ** (1 - n)`. The fewest rounds that can give a verdict is the smallest
`n` that brings this below `alpha`:

```
min_rounds(m, alpha = 0.05) = smallest n with m * 2 ** (1 - n) < alpha
```

| Tests `m` | `min_rounds` |
|---|---|
| 1 | 6 |
| 2 | 7 |
| 4 | 8 |
| 10 | 9 |
| 35 | 11 |
| 100 | 12 |

`m` is the number of subjects times the number of primary cases. A plan with fewer rounds
than this is refused before round 1 (`E_TOO_FEW_ROUNDS`, exit 6), unless
`--allow-underpowered` is given, in which case every verdict is
`NO VERDICT (too_few_rounds)`. The check is also made per comparison: a comparison with
fewer paired rounds than `min_rounds(m)` gets that reason. An experiment of one side has no
subject and seeks no verdict, so no round count is refused as too few for one; a time budget
then needs only the smallest balanced count.

At 8 rounds a verdict is possible for at most 6 primary cases, and only when every round that
is not a tie agrees (all 8 when none tie). A tie is not a trial, so 7 rounds that agree and one
tie give p = 0.015625 and can give a verdict for one primary case. The default round count is the smallest balanced count that is at least
`min_rounds(m) + 4`: 16 for two sides with twins and up to four primary cases.
