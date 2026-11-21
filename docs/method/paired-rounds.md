---
description: "Why each side runs once per round in an order that rotates and reverses, and how pairing by round takes slow drift of the machine out of every comparison."
---

# Why does pairbench run the sides in paired, alternating rounds?

So that a slow drift of the machine falls on both sides alike: every side runs once per round,
in an order that rotates and reverses, and the sides are compared round by round, where the
drift drops out of the ratio of each pair.

## Why alternate

A machine does not stay the same for the length of a run. Its clocks change with
temperature, caches fill and empty, other work comes and goes. If side A runs all its
launches first and side B all of its launches after, every slow drift of the machine lands
on one side and reads as a difference between the sides.

pairbench runs each side once per **round**, and compares the sides round by round. A drift
that is slow next to one round affects both values of a pair alike and drops out of their
ratio. This is the pairing: a subject value and a baseline value form a pair only when they
come from the same round of the same capture. A round that lacks either value for a case is
not a pair for that case and is counted as unpaired; a value is never guessed or carried
over from another round.

## Why rotate and reverse

Inside a round, position matters too. The first launch after a pause may find cold caches;
the launch after a heavy one may find a hot processor. A fixed order would give one side the
same position in every round. pairbench rotates the order by one place each round and
reverses it on every second pass through the rotations. The schedule is called
`rotate-reverse`.

For round `r` (counted from 1) over a lineup `g` of `n` entries:

```
off = (r - 1) % n
cyc = ((r - 1) // n) % 2
order[k] = g[(k + off) % n]          for k in 0..n-1
if cyc == 1: order = reversed(order)
```

Two entries A and B give the rounds AB, BA, BA, AB. Three entries A, B and C give ABC, BCA,
CAB, CBA, ACB, BAC.

## What balance means

A round count is **balanced** when all three hold:

1. every lineup entry occupies every position equally often;
2. for every compared pair, each subject with the baseline and each side with its twin, each
   of the two runs first equally often;
3. the signed differences of position of every compared pair sum to zero.

The planner counts over the planned rows to check this; it does not rely on a formula. For
two sides with twins, a lineup of four, 8, 16 and 24 rounds are balanced on every pair. At 12
and 20 rounds the subject and the baseline still run first equally often, but each side runs
before its own twin 7 times to 5 and 11 times to 9.

`--rounds N` rounds an unbalanced count up to the next balanced one and records both
numbers; `--rounds-exact` runs exactly `N` and stamps the capture `unbalanced` when it is.

## Order checks in the analysis

Two checks guard the order after the run:

- A compared pair that ran in the same order in every round, over at least two paired
  rounds, refuses the analysis (`E_ORDER_NOT_VARIED`, exit 6).
- Within the pairs of one comparison, if one side ran first more than three times as often
  as the other, the verdict is downgraded to `UNRESOLVED (order_unbalanced)`.

## The positive control is outside the rotation

The [positive control](positive-control.md) runs last in every round, at the position one
past the lineup's length. The lineup, its balance and every round count are the same with
and without it. The entry that follows the control is the first entry of the next round; at a
balanced count every lineup entry holds that position equally often, so the control favours
no side.

## Warm-up

Before round 1, each side gets one discarded launch. It discovers the cases, proves the
driver can read the output, and times a launch for the estimate of the run's duration. It is
kept in the capture, marked as warm-up, and never compared. Twins and the positive control
get no warm-up launch.
