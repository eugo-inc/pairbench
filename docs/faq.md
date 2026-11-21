---
description: "Short answers about launches, UNRESOLVED and NO VERDICT, pooling, busy machines, overhead, Python, results of other tools and your own statistics."
---

# Frequently asked questions

Short answers to the questions people ask most about pairbench, each with a link to the page
that explains it in full.

## Why so many launches?

Each round launches every side and its twin, plus the positive control. For two sides that is
five launches per round, and 16 rounds by default. The twins measure the noise in the same run,
and the control checks the instrument; without them a verdict would rest on an assumption. The
plan prints the launches and the estimated time before anything runs. `--quick` gives the
smallest balanced count; `--positive-control off` and `--same-vs-same off` remove launches,
and the plan says what each costs in evidence.

## Why did I get UNRESOLVED?

Either the gap is outside the noise but the direction is not significant
(`not_significant`): more rounds may decide it. Or the direction is significant but the gap is
inside the noise (`inside_noise`): a quieter machine, pinning with `--cpus`, or a workload with
less variation may decide it. Or one of the downgrades applied: `order_unbalanced` or
`sensitive_to_disturbed_rounds`. See [verdicts](method/verdicts.md).

## Why NO VERDICT?

The comparison could not be graded, and `reason` says why: too few rounds, no twin, a value of
zero, a failed positive control and others. See
[the reasons](method/verdicts.md#reasons-for-no-verdict).

## Can I pool two runs?

Yes: `pairbench compare runA/capture.jsonl runB/capture.jsonl`. The runs must be of the same
experiment on the same machine; the same capture twice and copies are refused.

## Can I run on a shared or busy machine?

Yes. Under the default `warn` mode a busy machine widens the noise floor instead of voiding the
run, and the results say the machine was busy. Pin with `--cpus` for the most complete
witnesses, take a lock with `--lock` if others agree to use it, or wait with `--wait-quiet`.
See [shared machines](method/shared-machines.md).

## Does pairbench slow down what it measures?

It does nothing it can avoid between the two clock readings of a launch. Each run measures and
reports the cost of a launch for command sides, gives a note when that cost is a noticeable part
of a value, and the positive control fails when a constant cost distorts a ratio. To leave the
start of a process out, time the work inside the workload with the
[`lines` driver](guides/lines.md). See [launch cost](method/launch-cost.md).

## Why is it written in Python?

The tool's own cost sits outside the measured interval: a launch is timed with one monotonic
clock read directly around the start and the end of the process. What runs inside the interval
is the workload. The README says more in "Why pairbench is not written in native code".

## Can I compare results from a tool I already ran?

Yes, with file sides: `pairbench compare --side new=file:'new-*.json' --side old=file:'old-*.json'
--driver hyperfine`. One file per round. Compare reads them into a run folder, as `run` does,
and prints the folder's report. The order the files were made in is unknown, so the verdict is
`NO VERDICT (order_not_recorded)` unless `--assume-interleaved` says they alternated, which is
stamped in the results.

A file side has no twin, so there is no noise floor: even with `--assume-interleaved`, the
default rule gives `NO VERDICT (no_floor)`. To grade such results, read the capture that compare
wrote into its run folder with the Python API, and supply noise floors measured elsewhere:

```python
from pairbench import Floors, analyse, load_capture

captures = load_capture("pairbench-runs/FOLDER/capture.jsonl")
results = analyse(captures, baseline="old", floors=Floors(0.01), assume_interleaved=True)
```

The floor of 1 percent is made up; see
[rows produced elsewhere](reference/python-api.md#rows-produced-elsewhere). Results graded this
way say so.

## Can I use my own statistics?

Use the Python API: `analyse` takes any `Rule`, and the primitives `sign_test`, `holm`,
`paired` and `min_rounds` are public. See [Python API](reference/python-api.md).

## Where do the numbers in the docs come from?

Every number in the documentation is one of four kinds: a known answer of the method,
checked by `pairbench selftest`; a made-up example that says so; a share from the simulated
experiments that `tools/error_rates.py` writes to the
[error-rate page](method/error-rates.md), which the tests check against its data; or a
figure filled in from a results file by `pairbench fill`. The showcases publish results only
after a real run has been approved.

## Is there a config file that is read by default?

No. A config file launches containers and commands, so only `--config` or `PAIRBENCH_CONFIG`
loads one. Treat a config from someone else as code.
