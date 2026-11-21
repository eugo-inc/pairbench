---
description: "A check that has never been given a known answer may say the same thing about everything; the controls pairbench runs on its own instrument."
---

# Why does every analysis need a case that must pass and one that must fail?

Because until an analysis has been given inputs whose answer is known, in both directions, its
output is a guess: a check that has only ever said "no difference" may be unable to say
anything else, and one that has only ever said "faster" may say it about everything.

## The controls a run carries

Each run carries two controls of its own instrument:

- **The negative control: twins.** Each side runs beside an identical copy of itself. Two
  identical things must read as equal. The gap between them is the
  [noise floor](noise-floor.md), and a side that differs from its own twin more often than
  chance gets a loud note.
- **The positive control: `~twice`.** The baseline runs once more per round with twice the
  work. It must read as twice the value. A failed control voids every verdict of the run.
  See [positive control](positive-control.md).

## The controls of the statistics

`pairbench selftest` runs known answers and controls on synthetic captures built by one
seeded generator. The expected values are written as constants, never computed by the code
under test, and each control is also a unit test of the package.

| # | Control |
|---|---|
| K1 | the sign-test known answers; 5 against 0 gives 0.0625 and cannot give a verdict |
| K2 | the four Holm known answers |
| K3 | the schedule for two and three entries; balance holds at the balanced count and fails one round earlier |
| K4 | the fewest rounds for 1, 2, 4, 10, 35 and 100 cases |
| C1 | a known 2.0x difference reads 2.000x and the right word |
| C2 | identical sides with realistic noise read TIE; identical noise-free values give `zero_floor` |
| C3 | swapping subject and baseline inverts the ratio and flips the word |
| C4 | three lower and three exact ties give p = 0.25, not 0.03125; nine ties give 1.0 |
| C5 | pooling keeps every pair of two valid captures; the same file twice, identical rows and a truncated copy are each refused |
| C6 | an order that never changes is refused |
| C7 | a missing twin on one side, and on both, each give NO VERDICT with the right reason |
| C8 | 18 of 24 is a verdict alone and UNRESOLVED among four cases |
| C9 | a direction that is significant but inside the bar is UNRESOLVED, never TIE |
| C10 | a missing cell plus a duplicated cell is refused and both are listed |
| C11 | twin drift and an orphan twin are refused |
| C12 | the decision to set a round aside does not change when the measured values are altered; too few remaining rounds and too large a share are refused; a disagreement downgrades |
| C13 | one fixed experiment graded under three different rules gives three recorded outcomes |
| C14 | power samples of 10, 20 and 30 W over one second integrate to 20 J |
| C15 | the three known answers of the positive control |
| C16 | a case whose `better` is `none` reads HIGHER or LOWER, never BETTER or WORSE, and is refused as a primary case |
| C17 | with a launch cost of 0.0005 s, a `wall` median of 0.04 s gets the launch-cost note and one of 0.06 s does not |

`pairbench selftest` exits 1 if any control fails. `pairbench selftest --live` adds a tiny
real run with two command sides.

## The simulated error rates

A seeded simulation reports how often the default rule gives each outcome when there is no
true difference, and when there is a known one. See [simulated error rates](error-rates.md).

## For your own analysis

The same rule holds for any analysis you add on top of pairbench, such as a script that
reads `results.json` or a dashboard that plots it. Give it a results document in which the
answer is known to be a difference, and one in which it is known to be none, and check that
it says so. `pairbench` itself can make both: compare a side with itself, and compare a side
with its own `~twice` entry.
