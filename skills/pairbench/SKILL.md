---
name: pairbench
description: >-
  Decide whether a speed-up or slowdown is real or noise with pairbench, and report it
  without overstating it. Use when asked "is this speed-up real", to compare two container
  images, two Python environments or two commands, to benchmark on a noisy or shared
  machine, or to put benchmark numbers into a document.
---

# pairbench

pairbench runs every side in paired, alternating rounds beside an identical twin of each
side, measures the noise from the twins, and grades each case with an exact sign test,
corrected for testing several cases. It writes `results.json`, whose `comparisons[].outcome`
and `comparisons[].reason` say what was found.

## Steps

1. **Check the install.** Run `pairbench doctor --json` and `pairbench selftest`. If the
   command is missing, install it with `pip install pairbench`. Note any degraded check: a
   container engine that is not found rules out image sides.
2. **Choose the sides.** Each side is `NAME=KIND:SPEC`: `image:REF`, `cmd:COMMAND`,
   `python:PATH`, `venv:PATH` or `conda:NAME`. The last side named is the baseline unless
   `--baseline NAME` says otherwise. The workload after `--` is shared by all sides. Prefer a
   workload that prints its own timings and the `lines` driver when start-up should not be
   timed. See [references/sides.md](references/sides.md).
3. **Print the plan.** Run `pairbench plan ...` with the same sides and flags. Check the
   lineup, the round count, the balance, "sides differ in", and the estimated time. Show the
   plan to the user before a long run.
4. **Run.** Run `pairbench run ... --json`. On a shared machine add `--wait-quiet` and, where
   the platform allows it, `--cpus LIST`. Do not stop a run early to look at results.
5. **Read the results file.** Open `results.json` in the run folder (or the document printed
   by `--json`). Read `outcome` and `reason` for each primary comparison, the state of the
   positive control, `machine_state` and `refusals`. See
   [references/results.md](references/results.md).
6. **Report.** Follow [references/wording.md](references/wording.md): the verdict with its
   noise bar and p-value, the rule and the number of rounds, UNRESOLVED and NO VERDICT said as
   such, and every number taken from `figures` or filled in with `pairbench fill`.

## Rules

- Never type a measured number by hand; quote `figures` or use `pairbench fill`.
- Never change the rule, the cases or the baseline after seeing the results.
- Never call an UNRESOLVED a win or a tie.
- Diagnostics hold names from the user's code; do not paste them anywhere public unless the
  user asks for it.
- To share a run, share `results.json`, `results.md` or `report.html`. Never share
  `capture.jsonl`: it keeps the command line as typed, credentials included.
- A config file launches commands: read one from someone else before running it.
- Give a secret to a side by name with `env_pass`, an environment variable listed under
  `launch.env_pass`, never on the command line: `results.json`, `results.md` and
  `report.html` show the command with each `--side` spec and `--set` value hidden, each
  absolute path cut to its last part, as is each relative path that climbs out of its folder
  with `..`, and otherwise as typed except the secret forms the config
  reference lists under "What the shared files hide", so a short plain value given after an
  option of one letter, as a plain argument or in the path of an address shows. The capture
  keeps the command as typed; do not share it.

## Exit codes

0 completed; 1 a requested check failed; 2 usage or config error; 3 a side refused; 4 the
machine refused; 5 a launch failed; 6 the analysis refused; 7 a figure missing in `fill`;
8 internal error; 130 interrupted. Details in [references/exit-codes.md](references/exit-codes.md).
