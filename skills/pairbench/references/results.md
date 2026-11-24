# Reading the results file

`results.json` is the analysed document of a run. `pairbench schema results` prints its JSON
Schema. Read these fields; the display words beside them may change between versions. Within
a schema version a later release may add a `reason` word, but never renames or removes one,
so report a reason you do not know as it is written.

| Field | Meaning |
|---|---|
| `comparisons[]` | one entry per subject and case against the baseline |
| `comparisons[].primary` | `true` when the case counts toward the verdict and the exit code |
| `comparisons[].outcome` | `better`, `worse`, `higher`, `lower`, `tie`, `unresolved`, `no_verdict` |
| `comparisons[].reason` | the first reason for `unresolved` or `no_verdict`, else `null` |
| `comparisons[].reasons` | every reason that applies |
| `comparisons[].n_rounds` | paired rounds |
| `comparisons[].ratio` | the median of the per-round ratios, subject over baseline |
| `comparisons[].bar` | the noise bar the gap had to exceed, as a fraction |
| `comparisons[].p_corrected` | the p-value after the correction for testing several cases |
| `controls.positive.status` | `ok`, `failed` or `not_run` |
| `machine_state.status` | `quiet`, `busy` or `unknown` |
| `refusals[]` | text code, scope and message of anything refused |
| `same_vs_same[].p_raw` | the uncorrected p-value of a side against its own twin on one case |
| `twin_checks[]` | one combined check per side against its twin across its primary cases, each round scored by the median of their turned logs, side over twin: rounds scored, rounds better and worse, `p_raw`, and `p_corrected` after the correction for testing every side that has a twin; at 8 rounds, the serving default, the note needs every untied round of the side to lean the same way, and its absence says nothing more |
| `notes[]` | loud notes, such as the launch-cost note; `twin_differs` when a side's combined check has a corrected p-value below 0.05; `sides_differ_in_hidden_value` when two sides with one fingerprint differ in a value the results hide, other than a credential's value, or in their working folder; `sides_declared_identical` when sides that are one side were compared under `--allow-identical`; and `value_not_finite`, one per cell, for each value that `pairbench compare --lenient` or `pairbench compare --matching` read from a text file as a missing cell, naming the side, the round by its label (with `--matching`, also the index of its run) and the case; and `view_without_twins`, one per case of `pairbench compare --matching`, saying that the two-sided view has no twins, so no case has a noise floor and the default rule gives no verdict |
| `matching` | present only after `pairbench compare --matching`: `runs`, `malformed_rows`, `kept_rows`, `left_out_rows` (rows of the two sides the view left out for want of a pass-order line naming both), `other_side_rows`, and `refusal`, the detail of a refusal of that mode with its `check`, or `null` |
| `figures` | every number with its text, keyed `CASE.SUBJECT_vs_BASELINE.NAME` |

## Outcomes

| Outcome | Says |
|---|---|
| `better` / `worse` | outside the noise bar and significant: a primary case on its corrected p-value; a secondary case, and every case under a rule whose `p_source` is `raw`, on its uncorrected p-value |
| `higher` / `lower` | the same, for a case that describes and does not judge |
| `tie` | inside the noise bar and not significant |
| `unresolved` | the evidence supports neither; `reason` says why |
| `no_verdict` | the comparison cannot be graded; `reason` says why |

## Reasons

| Reason | Says |
|---|---|
| `inside_noise` | significant, but inside the noise bar |
| `not_significant` | outside the noise bar, but not significant |
| `order_unbalanced` | one side ran first more than three times as often as the other |
| `sensitive_to_disturbed_rounds` | the outcome changes when disturbed rounds are set aside |
| `positive_control_failed` | twice the work did not read as twice the value |
| `nonpositive_value` | a value of zero or less was recorded |
| `too_far_apart` | values too far apart for a figure made from them (a ratio, its inverse or percent, a noise floor) to be a finite number |
| `single_measurement` | one pair, no p-value |
| `order_not_recorded` | result files whose order is unknown |
| `too_few_rounds` | fewer paired rounds than can give a verdict |
| `no_floor` | no twins, so no noise floor |
| `one_sided_floor` | a twin on one side only |
| `zero_floor` | a noise floor of exactly zero |

## Diagnostics

`diagnostics.json`, when written, describes how the sides differ in what they used. Read
`findings[].id` and `findings[].evidence`. A finding describes a difference and never names a
cause. The document holds names from the user's code.
