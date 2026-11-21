---
description: "Every pairbench command with each flag it takes and the config key the flag sets: run, plan, compare, report, fill, selftest, doctor, schema, gate and more."
---

# Commands and flags

This page lists every pairbench command with each flag it takes and the config key the flag
sets; `pairbench run` is the command that measures.

```
pairbench [--version] COMMAND [FLAGS]
```

| Command | Purpose |
|---|---|
| [`run`](#run) | plan, check the machine, measure, analyse and write the run folder |
| [`plan`](#plan) | print the plan and exit; touches nothing |
| [`compare`](#compare) | analyse or pool existing captures, or compare result files from other tools |
| [`report`](#report) | render a results file |
| [`fill`](#fill) | fill a document's figure tokens from results files |
| [`selftest`](#selftest) | run the known answers and the controls |
| [`doctor`](#doctor) | what this machine supports, which external tools are found, what is degraded |
| [`schema`](#schema) | print a JSON Schema |
| [`gate`](#gate) | run one machine check on its own |
| [`profile`](#profile) | record a profile with a profiler you installed yourself |
| [`mcp`](#mcp) | start the tool server for AI agents |
| [`skill`](#skill) | copy the agent skill into a folder |

Nothing prompts and no terminal is needed. Progress goes to standard error; `--json` prints a
document on standard output. The exit code says what happened; see
[exit codes](exit-codes.md). When the reader of either stream goes away early, as
`pairbench report results.json | head` does, the rest of that stream is dropped without a
message, and the command still finishes its work and exits with its own code.

## run

```
pairbench run --side NAME=KIND:SPEC --side NAME=KIND:SPEC [FLAGS] -- WORKLOAD...
```

Plans the run, checks the sides and the machine, runs warm-up and the measured rounds,
analyses them and writes the run folder. Every flag but `--side`, `--baseline`, `--config`
and `--set` sets one [config key](config.md), shown beside it.

### Sides and workload

| Flag | Config key | Meaning |
|---|---|---|
| `--side NAME=KIND:SPEC` | `sides.NAME` | a side, repeated for each; `KIND` is `image`, `cmd`, `python`, `venv`, `conda` or `serve`; result files of another tool (`file`) are read by [`compare`](#compare) |
| `--baseline NAME` | `sides.NAME.baseline` | the side every other side is compared against; default: the last side named |
| `--driver NAME` | `workload.driver` | the driver that reads each launch; default `wall` |
| `--case GLOB` | `cases.primary` | the primary cases, repeated for more than one pattern; a pattern that matches no case of the run, or only cases that are never primary (resource cases under `res/` and cases whose better is none), is refused once the cases are known; with no pattern and no primary case, a loud note says the run tests no case and no `--fail-on` outcome can match |
| `--levels LIST` | `workload.levels` | the load levels of a serving experiment, for example `1,8,32`; default `1,8,32` requests in flight |
| `--level-duration DURATION` | `workload.level_duration` | the length of each load level; default `60s` on a serving experiment, none with `vllm-bench` |
| `-- WORKLOAD...` | `workload.argv` | the workload, shared by every side |

### Rounds

| Flag | Config key | Meaning |
|---|---|---|
| `--rounds N\|auto` | `run.rounds` | the round count; `auto` is the smallest balanced count at least four above the fewest that can give a verdict |
| `--rounds-exact` | `run.rounds_exact` | run exactly `--rounds N`, stamped `unbalanced` when it is |
| `--quick` | `run.quick` | the smallest balanced count |
| `--budget DURATION` | `run.budget` | the largest balanced count whose estimated duration fits |
| `--warmups K` | `run.warmups` | discarded launches per side before round 1; default 1 |
| `--same-vs-same on\|off\|NAME,...` | `run.same_vs_same` | which sides get a twin; default `on` |
| `--positive-control on\|off` | `controls.positive` | the positive control; on unless the experiment serves |
| `--vary-env-size` | `run.vary_env_size` | change the size of the environment from round to round |
| `--allow-underpowered` | `run.allow_underpowered` | run fewer rounds than can give a verdict; every verdict is then NO VERDICT |

### Launch

| Flag | Config key | Meaning |
|---|---|---|
| `--engine auto\|docker\|podman` | `launch.engine` | the container engine |
| `--cpus LIST` | `launch.cpus` | pin every launch to these CPUs, for example `4-7` |
| `--gpus SPEC` | `launch.gpus` | `all` or a comma-separated list of GPU indices, as `nvidia-smi` numbers them; an index this machine does not have is refused |
| `--pull missing\|never\|always` | `launch.pull` | when to pull an image; only before the run |
| `--timeout DURATION` | `launch.timeout` | the longest one launch may take; on a serving side, from the server start to the end of its load |
| `--allow-identical` | `launch.allow_identical` | allow two sides with the same fingerprint |

### Machine checks

| Flag | Config key | Meaning |
|---|---|---|
| `--gates off\|warn\|enforce` | `gates.mode` | what a failed check does; default `warn` |
| `--wait-quiet` | `gates.wait_quiet` | wait until the machine is quiet before starting; needs `--gates warn` or `enforce` |
| `--lock PATH` | `gates.locks` | take an advisory file lock (`flock`) for the run, repeated for more |
| `--lock-timeout DURATION` | `gates.lock_timeout` | the longest wait for the locks; default 30 minutes |
| `--allow-mixed-core-types` | `gates.allow_mixed_core_types` | allow a CPU set that mixes core types |

### Analysis

| Flag | Config key | Meaning |
|---|---|---|
| `--rule NAME` | `rule.name` | the verdict rule; default `strict` |
| `--fail-on better\|worse\|unresolved\|no_verdict` | `rule.fail_on` | exit 1 when a primary case has this outcome, repeated for more |
| `--explain always\|auto\|off` | `explain.mode` | the explain step after the rounds; default `always` |
| `--plots auto\|on\|off` | `plots.mode` | the charts; `on` refuses when the `plot` extra is missing |

### Output

| Flag | Config key | Meaning |
|---|---|---|
| `--out DIR` | `run.out` | the run folder |
| `--config FILE` | | the config file to read |
| `--set KEY=VALUE` | any | set a config key by its dotted path, repeated for more |
| `--print-plan` | `run.print_plan` | print the plan and exit, as `plan` does |
| `--json` | `run.json` | print the results document on standard output |
| `--no-plugins` | `run.no_plugins` | load no plug-in outside the package |

`--set` reads its value as a TOML value when it parses as one and as text otherwise:
`--set workload.level_kind=rate`, `--set run.rounds=24`. Naming one key with a flag and with
`--set`, with values that read differently, is a usage error; one value written two ways, such
as `--cpus 4` with `--set launch.cpus=4`, `--cpus 0-3` with `--set launch.cpus=0,1,2,3` (one
set of CPUs), or `--levels 1,8,32` with `--set 'workload.levels=[1, 8, 32]'`, is one value.

Once a run has written its results, also those of a run that was refused or interrupted after
it started, `run` prints one `command_shown` note on standard error: `results.json`,
`results.md` and `report.html` show the command with the spec of each `--side`, the value of
each `--set` and the forms listed in
[what the shared files hide](config.md#what-the-shared-files-hide) hidden, and each absolute
path cut to its last part, and secrets belong in environment variables. It comes after the
verdicts, and before the lines of a refusal.

Side specs by kind:

| Kind | Example |
|---|---|
| `image` | `--side new=image:myorg/app@sha256:...` |
| `cmd` | `--side new=cmd:./build-new/app`, or `--side new='cmd:taskset -c 2 {workload}'` |
| `python` | `--side new=python:python3.14` |
| `venv` | `--side new=venv:.venv-new` |
| `conda` | `--side new=conda:numpy-env` |
| `file` | `compare` only: `pairbench compare --side new=file:'results/new-*.json' ... --driver hyperfine` |

A serving side has more settings than fit on one line; it is set in a
[config file](config.md#serving-sides).

## plan

```
pairbench plan [the flags of run] -- WORKLOAD...
```

Takes every flag of [`run`](#run) and prints the plan: the lineup, the rounds requested and
planned, the launches, the balance of every pair, whether a verdict is reachable and how many
rounds must agree when none tie, the estimated duration when known, the cost of the positive control and of
the explain step, and a tab-separated table with the columns `round pos name side twin_of`.
It creates no folder, takes no lock, starts no container and pulls nothing. It exits 0, or
with the code of a refusal it can find without launching anything.

## compare

```
pairbench compare [CAPTURE...] [FLAGS]
```

Analyses one capture, pools several, or compares result files of another tool.

| Flag | Meaning |
|---|---|
| `CAPTURE...` | capture files to analyse; several are pooled |
| `--baseline NAME` | the side every other side is compared against |
| `--rule NAME` | the verdict rule |
| `--fail-on better\|worse\|unresolved\|no_verdict` | exit 1 when a primary case has this outcome, repeated for more |
| `--case GLOB` | show only these cases; the correction still counts every primary case |
| `--out DIR` | write `results.json` and `results.md` here; with `file` sides, the run folder |
| `--json` | print the results document |
| `--allow-incomplete` | analyse the complete rounds of a capture with no end record; a last round that lacks a launch or an observation, or whose file ends in a torn line, is left out with a `torn_round_left_out` note; the results are stamped |
| `--allow-mixed-machines` | pool captures from different machines; the results are stamped |
| `--assume-interleaved` | treat the result files of `file` sides as produced in alternating order; stamped |
| `--side NAME=file:GLOB` | result files of another tool, one per round, repeated for each side |
| `--driver NAME` | the driver that reads the files |
| `--levels LIST` | the load level result files of a serving load tool were made at; such a driver reads each file as one level |
| `--reader NAME` | the reader of the capture files, for the [text input format](text-format.md) or a plug-in |
| `--no-plugins` | load no plug-in outside the package |

With `file` sides, compare reads the files into a run folder, as `run` does: `capture.jsonl`,
`results.json`, `results.md` and `artifacts/`, in `--out DIR` or else in a new folder under
`pairbench-runs`. The order the files were made in is not known, so every comparison is
`NO VERDICT (order_not_recorded)` unless `--assume-interleaved` is given. A `file` side has no
twin, so even then the default rule gives `NO VERDICT (no_floor)`; the
[FAQ](../faq.md#can-i-compare-results-from-a-tool-i-already-ran) shows how to grade such a
capture with noise floors measured elsewhere.

When it writes results files or prints the results document, also those of a refusal,
`compare` prints the `command_shown` note that `run` prints.

Pooled captures must be of the same experiment: the same sides, each with the same kind,
twin and control relation, fingerprint, recorded setup and working folder, and the same shared
workload but for its credentials (`E_POOL_SIDE_DRIFT`), the same case set and units, a name that ends
with a mark made again with the key of the first capture given (`E_POOL_CASES`), the same CPU and GPU
identity unless `--allow-mixed-machines` is given
(`E_POOL_MACHINE`), and the same purpose (`E_POOL_MIXED_PURPOSE`). The same capture twice
(`E_POOL_SAME`), identical rows (`E_POOL_IDENTICAL_ROWS`) and a copy torn from another
capture (`E_POOL_TRUNCATED_COPY`) are refused. Which side is the baseline is set once for the
whole pool: `--baseline NAME`, or else the baseline of the first capture given. When the
captures name different baselines and no `--baseline` is given, a `pool_baseline` note says
which one the pool took. Ids of the pooled captures that differ only in words that hold a `/`
or in the folders of a path written with `%2F`, or only in a hidden secret, are read as one
case, and a `pool_folders_merged` or `pool_secrets_merged` note on standard error and in the
results names that case, never the words; if those folders are different inputs, keep the
captures apart. A case whose name ends with a mark is shown with the mark the first capture's
key makes, as
[case ids that read alike](config.md#what-the-shared-files-hide) says.

## report

```
pairbench report RESULTS [FLAGS]
```

| Flag | Meaning |
|---|---|
| `RESULTS` | a `results.json` file |
| `--format terminal\|markdown\|json\|html` | the format; default `terminal` |
| `--case GLOB` | show only these cases; filtering never changes the correction |
| `--all` | show every case, secondary ones included |
| `--verbose` | add each side's own floor |
| `--plots auto\|on\|off` | draw the charts again into the folder of the results; default `off` |
| `--no-plugins` | load no plug-in outside the package |

## fill

```
pairbench fill TEMPLATE --results [NAME=]FILE -o OUT [--check]
```

| Flag | Meaning |
|---|---|
| `TEMPLATE` | the document with figure tokens |
| `--results [NAME=]FILE` | a results file; with several, each but one is named, repeated for each |
| `-o`, `--output OUT` | the filled document |
| `--check` | compare with the output file instead of writing it; a difference is exit 1 |

A token is `{{fig:KEY}}`, `{{fig:KEY|FORMAT}}` with a Python format specification, or
`{{fig:NAME/KEY}}` with several results files. Text outside the tokens is never changed.
Every token is read before anything is refused: a missing key is `E_FIGURE_MISSING` (exit 7)
and every missing key is listed; a format that cannot apply is `E_USAGE` (exit 2). The keys
are listed in the [results schema](results-schema.md#figures).

## selftest

```
pairbench selftest [--live]
```

| Flag | Meaning |
|---|---|
| `--live` | add a tiny real run with two command sides |

Runs the known answers and the controls of the statistics on synthetic data. Exit 1 when any
fails. See [instrument controls](../method/instrument-controls.md).

## doctor

```
pairbench doctor [--json] [--no-plugins]
```

| Flag | Meaning |
|---|---|
| `--json` | print the document as JSON |
| `--no-plugins` | load no plug-in outside the package |

Says what this machine supports: the external programs found, the container engine, the
instruments of the explain step that can run and what forbids the others, whether the plot
extra is installed, the drivers that are experimental, containers left behind by an
interrupted run, and anything degraded. Always exits 0.

## schema

```
pairbench schema capture|results|config|diagnostics
```

Prints the JSON Schema of the capture records, the results document, the config file or the
diagnostics document.

## gate

```
pairbench gate check [--cpus LIST] [--allow-mixed-core-types] [--json] [--config FILE] [--set KEY=VALUE]
pairbench gate wait-quiet [--config FILE] [--set KEY=VALUE] -- COMMAND...
```

Both forms read the settings `run` and `plan` read: the config file that `--config` or
`PAIRBENCH_CONFIG` names, the `PAIRBENCH__` variables and `--set`, checked as strictly. A key
that does not exist, or a value of the wrong type such as `gates.quiet.max_busy_cores =
"many"`, is refused with `E_CONFIG` (exit 2) before any check runs. A flag of the gate command
wins over the file and the variables; a flag and `--set` that give one key different values are
a usage error, as in `run`. A side table that names no kind of side, because the command line
of `run` gives it, is read for its `baseline` and `launch` keys; its other keys are left to
`run`, and a key that no kind of side takes, such as a misspelt `lauch`, is refused with
`E_CONFIG`. When every side of the config is a result file, nothing is launched: the checks use
the shared launch settings, and a loud note says so.

### gate check

`gate check` runs checks once each under `enforce`: the CPU check when `--cpus LIST` is given,
on that set in place of `launch.cpus` (a side's own `cpus` from the config is checked as `run`
checks it), then each [readiness check](config.md#gates) whose key is set, in the order
`stop_file`, `gpu_memory`, `check_locks`. With no `--cpus` and no readiness key set it is a usage
error (`E_USAGE`, exit 2). Every check runs, also after one that did not pass.

Each check that passes prints `check NAME: pass`, with its message when it gave one, on
standard output. Each one that does not pass prints its line on standard error, and the command
then exits with 4, naming the first of them: `E_GATE_FAILED` when it failed,
`E_GATE_UNAVAILABLE` when it could not run fully. A CPU list that is malformed, such as a range
that runs backwards, is refused with exit code 2.

```
$ pairbench gate check --set gates.stop_file=made-up/hold.stop
check stop_file: pass
```

| Flag | Meaning |
|---|---|
| `--cpus LIST` | the CPUs to pin to; checks their core types |
| `--allow-mixed-core-types` | allow a CPU set that mixes core types |
| `--json` | print the record as JSON, whatever its status, when one check ran; a list of the records, in the order they ran, when several ran |
| `--config FILE` | the config file to read; also `PAIRBENCH_CONFIG` |
| `--set KEY=VALUE` | set one config key, as `run --set` does; repeated for more |

### gate wait-quiet

`gate wait-quiet -- COMMAND...` runs the command once the machine is quiet and exits with the
command's own exit code. If the machine does not become quiet in time, the exit code is 4 and
the command is not run. The quiet settings are those of `gates.quiet.*`, and the GPUs it
watches follow `launch.gpus` and each side's own `gpus`, as in `run`.

The wait includes the readiness checks whose key is set: a sample counts as quiet only when
each of them would pass at that sample. After the wait each of them runs once, and the command
runs only when the quiet check and every one of them passed. Otherwise the line of each check
that did not pass is printed on standard error, the command is not run, and the exit code is 4,
naming the first such check in the order `quiet`, `stop_file`, `gpu_memory`, `check_locks`.

## profile

```
pairbench profile --from RESULTS --tool nsys|ncu|perf [--case CASE] [--side NAME]
```

| Flag | Meaning |
|---|---|
| `--from RESULTS` | the run's `results.json` |
| `--tool nsys\|ncu\|perf` | the profiler |
| `--case CASE` | the case to profile |
| `--side NAME` | one side; default: every subject and the baseline |
| `--no-plugins` | load no plug-in outside the package |

Runs one extra, untimed launch per side under a profiler you installed yourself, and stores
its output under `profiles/<side>/` in the run folder; the command prints the files it wrote.
On an image side the profiler runs inside the container, in front of the image's whole command
line (its entrypoint and its command), so the image must hold it. A missing profiler is
refused and named (`E_PROFILER_MISSING`), on the host or in the image. pairbench does not
include, download or redistribute any profiler; see the
[licence notes](../licence.md#profilers).

## mcp

```
pairbench mcp [--allow-run] [--no-plugins]
```

| Flag | Meaning |
|---|---|
| `--allow-run` | add the tools that start and cancel runs; they launch commands on this machine |
| `--no-plugins` | load no plug-in outside the package |

Starts the tool server for AI agents over standard input and output. Needs the `mcp` extra.
See [tool server](tool-server.md).

## skill

```
pairbench skill install --dir PATH
```

### skill install

| Flag | Meaning |
|---|---|
| `--dir PATH` | the folder that holds your agent's skills; required |

Copies the agent skill into `PATH/pairbench/`. See [for AI agents](../agents.md).
