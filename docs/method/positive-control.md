---
description: "The positive control runs twice the work once per round and must read about twice the value; what it checks, what it does not, and what a failure means."
---

# What does the positive control check?

That twice the work reads as twice the measured value, on this machine, in this run: the
baseline runs once more per round with its workload twice over, and that launch must read as
twice the baseline. Twins are the negative control, and this is the opposite check.

## What it is

One more entry runs in every round: the baseline's environment, started once, with the
workload run twice in it, one run after the other. Its name is the baseline's name with
`~twice` added, for example `old~twice`.

| Kind of side | One launch of the control |
|---|---|
| image | one container whose command runs the workload twice |
| `cmd`, Python environment | two processes, one after the other, inside one clock interval |
| serve | one server start; the load is run twice |
| file | no control |

A time that pairbench or the engine measures (`wall`, `launch`) is the one interval around
both runs. A case that the workload or a driver reports is combined over the two runs with
values `a` and `b`: `a + b` where lower is better, `1 / (1/a + 1/b)` where higher is better.
Values of 3 and 5 give 8; rates of 3 and 6 give 2. A case whose `better` is `none` is not
recorded for the entry.

Two separate launches are never added together to stand in for the control: such a sum
reads 2x whatever the instrument measures. When a side cannot run its command twice in one
start, the control is `not_run` with a loud note that names the cause. For an image side,
the two runs keep their output apart in files pairbench creates in the folder it mounts into
the container, so the image needs a shell, and its user must be able to write those files:
root, or a user with your user id. pairbench creates them readable and writable by you only
(mode `0600`) whatever your umask, so an image whose user is anyone else gets the control
`not_run` with the loud note; `controls.positive_via = "factor"`, below, needs no such files.
pairbench checks both with one short container before the first round. No setting of
pairbench chooses the user a container runs as, so to give an image whose user is anyone else
the control, rebuild it to run as root or as your user id. When the check passes
and the shell of a control launch is still refused one of those files, the measured rounds go
on without the control, which is `not_run` with a loud note that names the cause. That needs
a "permission denied" line that names the file. A control launch that fails for any other
reason stops the run with `E_LAUNCH_FAILED`, which names the launch and its exit code. `pairbench compare --allow-incomplete` on that capture
judges the control on the rounds kept; when too few are kept, the control is `not_run` and the
note names the launch that stopped the run.

`controls.positive_via = "factor"` asks the workload to double itself instead: the control
launch runs the workload once, with `PAIRBENCH_WORK_FACTOR=2` in its environment. A workload
that honours the variable does twice the work inside its own timing; one that ignores it
reads 1.0x and the control fails. The [showcase](../showcases.md) workloads honour it.

## What it checks

The control checks that twice the work takes twice the measured time on this machine in this
run. It fails when something other than the work is inside the measurement: a start-up cost
counted once, a second run that does less because of leftover state, a processor that slows
under sustained load or has not reached full speed in a short run. For a case the workload
times itself, under `repeat`, it checks only that values are read, added and paired
correctly.

## Where it runs

The control is not part of the rotated lineup. It runs last in every round, after the
measured entries. The lineup, its balance and every round count are the same with and
without it. The entry after the control is the first of the next round, and at a balanced
round count every lineup entry holds that position equally often, so the control favours no
side. Its own order never varies; it is not a compared pair, so the refusal of an order that
never changes does not apply to it. It gets no warm-up launch, no explain launch and no
resource cases.

## How it is judged

1. The expected median ratio of the control against the baseline is 2.0 where lower is
   better and 0.5 where higher is better.
2. For every primary case the measured median ratio must lie within the tolerance of the
   expected value, and the direction must be significant by the uncorrected sign test at
   the rule's alpha. The tolerance, `controls.positive_tolerance`, is a fraction of the
   expected value; its default, 0.10, is a chosen number. With the default, 1.8 to 2.2
   passes.
3. The control's state for the run, `controls.positive.status`:

| Status | When |
|---|---|
| `ok` | every primary case passed |
| `failed` | at least one primary case did not pass |
| `not_run` | the control was off; the capture has no control entry; the side cannot run its command twice in one start, found before the first round or when a launch of the control failed; or no primary case has enough paired rounds between the control and the baseline to be judged |

The control is outside the correction family and adds nothing to the number of tests. It
needs no twins: with twins off it still runs and is judged by its tolerance and the sign
test. A control that was on and could not be judged is a loud note and changes no verdict.

## What a failed control means

A failed control gives every comparison of the run `NO VERDICT (positive_control_failed)`,
loudly: the instrument could not measure a known difference, so no difference it reports can
be trusted. The comparisons of each side with its twin are still printed. A case on which the
control read no ratio is named with the cause in the note: too few paired rounds, a value of
zero or less, or a ratio to the baseline too large or too small to be a finite number.

Known answers, each from a made-up run of 20 rounds:

- A control that reads 2.0x in every round is `ok`.
- In a run where every launch carries a constant cost inside the interval, equal to the time
  of one run of the work, the baseline reads 2 units and the control 3. The control reads
  1.5x in every round, fails the tolerance, and every comparison of the run is NO VERDICT.
- A control that reads 2.0x in 13 rounds and 0.5x in 7 has a median of exactly 2.0 and still
  fails: 13 against 7 gives p = 275960/1048576, about 0.26, so the direction is not
  significant.

When the control fails because of a constant cost, time the work alone: print the timings
from inside the workload and read them with the [`lines` driver](../guides/lines.md). See
[launch cost](launch-cost.md).

## Defaults and cost

The control is on for an experiment with no serving side and off for a serving experiment;
`--positive-control on|off` (`controls.positive`) overrides either way. It costs one more
launch per round, holding two runs of the workload: for two sides with twins a round goes
from four runs of the workload to six. The plan prints this cost and how to turn it off.

The results record what was measured, per primary case (made-up numbers):

```json
"controls": {"positive": {"status": "ok", "entry": "old~twice", "via": "repeat",
  "tolerance": 0.1, "cases": [{"case": "matmul", "expected": 2.0, "ratio": 2.01,
  "p_raw": 0.00003, "n_rounds": 16, "passed": true}]}}
```
