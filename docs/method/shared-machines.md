---
description: "How pairbench works on a machine others use: the quiet check, pinning, locks, witnesses during every launch and rounds set aside when disturbed."
---

# Can I benchmark on a shared or busy machine?

Yes, with care: pairbench checks the machine before the run, records witnesses during every
launch, widens the noise floor with the load the twins see, and says loudly whatever it could
not check. It does not pretend the machine is empty.

## Modes

`gates.mode`, or `--gates`, is `off`, `warn` (the default) or `enforce`.

- **`warn`**: checks run and findings are printed. When one fails, the results are stamped
  `machine_state.status = "busy"` and the run goes on. The twins run under the same load, so
  the noise floor widens instead of the run being void.
- **`enforce`**: a failed check refuses with exit 4.
- **`off`**: the checks before the run are skipped. Witnesses are still recorded and
  disturbed rounds are still reported.

A check that cannot run has the status `unavailable` or `degraded`. Under `enforce` that is a
refusal; under `warn` it is a loud note. It is never a pass. Every degraded, unavailable or
failed check appears in three places: a line on standard error, a record in the capture, and
`machine_state.degraded` in the results, with a footnote in every report. The checks run once
before the locks and once at the short re-check after them, and pooled results hold the checks
of every capture, so an entry can be in the results more than once; a report says each entry
once, and two entries of one check that differ in status or reason both appear.

## Quiet at the start is not quiet throughout

The quiet check samples the machine and passes when it has been quiet for a streak of
samples. With `--wait-quiet` it keeps sampling until the streak is reached or
`gates.quiet.max_wait_s` has passed; without it the check takes one streak, records pass or
fail, and the run goes on as the mode says.

| Setting | Default | Meaning |
|---|---|---|
| `gates.quiet.max_busy_cores` | 1.0 | busy cores, summed over the machine, from processor time counters |
| `gates.quiet.gpu_idle` | true when a side selects a GPU | no other compute process on the GPUs any side selects |
| `gates.quiet.samples` | 5 | consecutive quiet samples needed |
| `gates.quiet.interval_s` | 2 | seconds between samples |
| `gates.quiet.max_wait_s` | 1800 | then the check fails |

A probe that fails to read counts as busy. `pairbench gate wait-quiet -- COMMAND` runs a
command once the machine is quiet and exits with the command's own exit code, or with 4,
without running it, when the machine does not become quiet in time. It reads the same config
file, `PAIRBENCH__` variables and `--set` as `run`.

A quiet start says nothing about the next hour. Someone else's job can start in round 3.
That is what the witnesses are for.

## Pinning

`--cpus LIST` pins every launch to the same CPUs.

- **One type of core.** The set must hold one type of core, read from the processor
  identification the kernel gives per CPU, with the maximum frequency as a fallback. A set
  that mixes types is refused (`E_CPUS_MIXED_TYPES`) unless `--allow-mixed-core-types` is
  given. A side's own set (`sides.NAME.launch.cpus`) is checked the same way, and the
  refusal names the side. Running unpinned on a machine with more than one type of core is
  a loud note.
- **Recorded.** A line describing the CPUs of every set a side runs on, its own set or the
  shared one, is written into the capture, and two captures pooled together must have the
  same set of core types.
- **The tool moves aside.** pairbench moves its own process and its sampler threads onto
  CPUs outside the pinned set, where the platform allows it, and records where it moved.
  When no CPU is left outside the set, it stays where it is and says so. When the run ends,
  also when it fails or is interrupted, the tool moves back. A side with no set of its own
  runs on the CPUs the tool could use before it moved, not on those left outside another
  side's set.
- **Every side applies it.** A side that cannot apply a pinned set at launch is refused
  before the run (`E_PIN_UNSUPPORTED`, exit 4).

## Neighbour census

The census lists the other running containers and, over one second, how much CPU each used
and which CPUs it may use. An unpinned container using more than
`gates.census.max_busy_cores` (0.5 by default) fails the check and is named; so does a
container allowed on CPUs that share a last-level cache with the pinned set and using more
than that. The pinned set covers every side's set; when one side runs unpinned, nothing
counts as pinned and every busy container fails the check. Without access to the container
engine the census is `unavailable`. The census looks at CPUs only: it does not read which
GPUs a container may use, so a container busy on a selected GPU is not counted here. The
quiet check counts the other compute processes on the GPUs the sides select. The capture
keeps how many containers the census saw and, for each container that failed the check, its
name, its CPUs, the cores it used and the rule it broke; it keeps no container id and no name
of a container that broke no rule.

## Locks

`--lock PATH`, repeated, takes advisory file locks in the order given, after the quiet wait
and until the end of the run. An existing lock file is opened read-only, so a file owned by
another user can still be locked; a missing one is created. `--lock-timeout` bounds the wait,
30 minutes by default. A timeout or any error is exit 4 (`E_LOCK`) in every mode: a run never
proceeds without a lock it was asked to take. Locks work only between programs that take the
same lock; agree on a path with the other users of the machine.

The order of events is: refusals that need no launch, the plan exit if asked for, the quiet
wait (holding no lock), the locks, one short re-check, then warm-up.

## Witnesses

During every launch the runner records witnesses that do not depend on the measurement:

- busy cores used by everything except the launch itself;
- the same, restricted to the CPUs that share a cache with the pinned set (recorded, with no
  threshold of its own);
- the number of other compute processes on the selected GPUs;
- any throttle events the GPU reports.

### The busy-core witness

The busy-core witness is counted in one of three ways:

1. **A pinned run** (`--cpus`): the busy cores on the CPUs outside the pinned set, less the
   CPU time of pairbench's own process and its witness thread. The launch's own CPU time is
   not needed, so this works for every kind of side. Load of others on the pinned CPUs
   themselves is not seen. The helper processes of a container engine count as load of
   others in a pinned run. When every CPU is pinned, the run is counted as an unpinned one.
2. **An unpinned run whose side reports the CPU time of its own processes** (command and
   Python environment sides): the busy cores of the whole machine, less that time.
3. **An unpinned run whose side reports none** (image and serving sides): the busy cores of
   the whole machine with the launch's own load in, marked as such in the witness
   (`includes_launch`). This is an upper bound on the load of others. At or under the
   threshold, the launch is not disturbed. Above it, the launch is **undecided**: it neither
   exceeds the threshold nor passes, and it does not mark its round as disturbed. Another
   launch in the same round can still mark it as disturbed, and a last round that lacks a
   launch is left out under `--allow-incomplete`. The results count the undecided launches
   in `machine_state.undecided_launches`, list the CPU checks as degraded with one message
   saying how many launches could not be judged, add the note `witness_undecided`, and give
   `machine_state.status` as `unknown` unless it is `busy`.

For image and serving sides, `--cpus` gives the full witness: pin the launches and the
witness counts the load of others on the CPUs outside the set, whatever the side reports.

A witness that could not be read counts as exceeding its threshold; that is kept apart from
an undecided launch. The GPU witnesses are counted the same way in every case.

## Disturbed rounds

A launch is **disturbed** when a witness exceeds its threshold: more than
`gates.discard.max_busy_cores` busy cores (2.0 by default), any other GPU compute process, or
any throttle event. A disturbed launch marks its whole round, for every lineup entry.

The thresholds are written into the capture before round 1, and the function that decides
takes a type that has no measurement fields: the decision cannot depend on the values being
compared. A hash of the decision is recorded in the capture and in the results.

The verdict is computed from all rounds. The analysis is then repeated without the disturbed
rounds and printed beside it. If the outcome differs, the verdict is downgraded to
`UNRESOLVED (sensitive_to_disturbed_rounds)`. Setting rounds aside never produces or upgrades
a verdict. The repeat is not computed, and the report says why, when fewer than the fewest
rounds that can give a verdict would remain, or when more than half of the rounds are
disturbed; in the second case the machine state is `busy`.

## By platform

| Check | Linux host | Inside a container | macOS | Automated pipelines |
|---|---|---|---|---|
| Quiet wait | full | machine-wide view, labelled | load average only, `degraded` | recorded; not waited on unless asked |
| Pinning and core types | full | limited to the container's own CPUs | refused with the reason | full |
| Neighbour census | full | `unavailable` without the engine socket | scoped to the engine's virtual machine, labelled | full |
| Locks | full | full | full | full |
| Disturbed rounds | full | full | off: no independent witness | full |

"Full" means the check works there; it does not mean the run waits. An automated pipeline is
detected by the `CI` environment variable holding a true value.
