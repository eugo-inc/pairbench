---
description: "The default rule, strict: when a case reads FASTER, SLOWER, TIE, UNRESOLVED or NO VERDICT, every reason for the last two, and how to report one."
---

# What does each verdict mean?

A case is FASTER or SLOWER when its change is wider than the noise bar and its corrected
p-value is below 0.05, TIE when neither holds, UNRESOLVED when only one holds, and NO VERDICT,
with the reason, when it cannot be graded.

## The quantities

For case `c`, subject `S` and baseline `B`, over the pairs `i`:

| Quantity | Definition |
|---|---|
| `r_i` | `S_i / B_i` |
| `M` | the median of `r_i`; with an even count, `(a + b) / 2` of the two middle values |
| `n_lower`, `n_higher` | the pairs with `r_i < 1` and with `r_i > 1` |
| tie | a pair with `S_i == B_i` exactly; not a trial |
| `gap` | `abs(M - 1)` |
| `bar` | the subject's floor plus the baseline's floor (see [noise floor](noise-floor.md)) |
| `p` | the exact [sign test](sign-test.md), [corrected](multiple-comparisons.md) for the family |

`p` is compared with 0.05 in exact arithmetic: Holm's correction runs on the exact fractions
of the sign tests, and 0.05 is exactly 1/20, so rounding never turns whether `p` passes (see [exact arithmetic for the verdict](multiple-comparisons.md#exact-arithmetic-for-the-verdict)).

Every value must be positive. A value of zero or less recorded for a case on a side, in any
round, gives that case `NO VERDICT (nonpositive_value)`.

## The default rule, `strict`

| Condition | Verdict | `outcome` | `reason` |
|---|---|---|---|
| `M < 1 - bar` and `p < 0.05` | FASTER where lower is better; WORSE where higher is better | `better` / `worse` | none |
| `M > 1 + bar` and `p < 0.05` | SLOWER where lower is better; BETTER where higher is better | `worse` / `better` | none |
| `abs(M - 1) <= bar` and `p >= 0.05` | TIE | `tie` | none |
| `abs(M - 1) <= bar` and `p < 0.05` | UNRESOLVED | `unresolved` | `inside_noise` |
| outside the bar and `p >= 0.05` | UNRESOLVED | `unresolved` | `not_significant` |
| cannot be graded | NO VERDICT | `no_verdict` | one of the reasons below |

The same evidence is required for a win, a loss and a tie: a difference needs a gap wider
than the bar and a significant direction, and a tie needs a gap inside the bar and no
significant direction. A direction that is significant but inside the bar is never a TIE.

FASTER and SLOWER are the words for cases of kind `time`; other cases read BETTER and WORSE.
A case whose `better` is `none`, such as every resource case under `res/`, reads LOWER or
HIGHER with the outcomes `lower` and `higher`, and is always secondary.

Programs read `outcome` and `reason`, never the display word.

## Downgrades

After the table, two conditions turn a verdict into UNRESOLVED:

| `reason` | When |
|---|---|
| `order_unbalanced` | within the pairs of this comparison, one side ran first more than three times as often as the other |
| `sensitive_to_disturbed_rounds` | the outcome changes when the [disturbed rounds](shared-machines.md#disturbed-rounds) are set aside |

Setting rounds aside can only downgrade. It never produces or upgrades a verdict.

## Reasons for NO VERDICT

| `reason` | Meaning |
|---|---|
| `positive_control_failed` | the [positive control](positive-control.md) of the run failed; every comparison of the run is affected |
| `nonpositive_value` | a value of zero or less was recorded for the case, or on a side or twin in a round they share |
| `too_far_apart` | the values are so far apart that a ratio the comparison needs is no finite number: the ratio of the two sides (the reports name both medians), a noise floor from a side and its twin, or the bar the two floors add up to. A ratio counts only when its inverse and its percent difference are finite numbers too and it is above zero, so a ratio too small for a float, or one whose speed-up or percent would overflow, counts here; a floor or a bar counts only when it is a finite number as a percentage. The case keeps its p-value and stays among the cases corrected for, and it has no ratio, speed-up or percent figure |
| `single_measurement` | one paired round; no p-value |
| `order_not_recorded` | the order the sides ran in was not recorded |
| `too_few_rounds` | fewer paired rounds than the fewest that can give a verdict |
| `no_floor` | neither side has a twin |
| `one_sided_floor` | only one side has a twin |
| `zero_floor` | a floor of exactly zero on either side; every case in that group is affected |

When several apply, `reasons` lists all of them and `reason` is the first in the order of the
table. Two more reasons are reserved and are not produced by this release: `side_failed`
and `more_than_one_node`.

## Exit codes

The outcome of a comparison changes the exit code only when asked. `--fail-on OUTCOME`,
repeated for more than one, makes the exit code 1 when any primary case has one of the named
outcomes: `better`, `worse`, `unresolved` or `no_verdict`. `--fail-on worse` is the check for
a slowdown; `--fail-on worse --fail-on unresolved` also fails when the run could not decide.
Secondary cases never change the exit code. See [exit codes](../reference/exit-codes.md).

## Other rules

The package ships one named rule. The Python API accepts any `Rule`: another scale
(`percent`), floor scope, bar, alpha, inclusive or exclusive comparisons, tie handling, a
fixed minimum round count, or grading on the uncorrected p-value (see
[multiple comparisons](multiple-comparisons.md#what-the-family-is)). The results always
record every field of the rule used, so a reader can see which rule gave a verdict.

## How to report a verdict

Say the outcome with its evidence, and name the machine and the run. A sentence that holds
all of it (made-up numbers):

> On a 16-core x86-64 workstation, `new` was faster than `old` on `matmul`: 1.26x, outside a
> noise bar of ±1.8%, in 15 of 16 paired rounds (p = 0.0010, corrected for testing 2 cases
> at once). Machine state: quiet.

- **FASTER or SLOWER**: give the ratio, the bar, the p-value and the round count.
- **TIE**: say "no difference larger than the noise of ±X% was found", never "the same
  speed".
- **UNRESOLVED**: give the reason in plain words and the ratio as a measurement, never as a
  win or a loss. A gap outside the noise that is not significant may become a verdict with
  more rounds; a significant gap inside the noise needs a quieter machine.
- **NO VERDICT**: give the reason and do not compare the medians.

See the [reporting checklist](reporting-checklist.md) for what a published comparison should
state.
