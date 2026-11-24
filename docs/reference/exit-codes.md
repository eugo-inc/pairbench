---
description: "What each exit code and each stable text code of a refusal means, with its cause and its fix."
---

# Exit codes and text codes

pairbench exits 0 when a run completed, whatever the verdicts, and with another code when
something was refused or failed; every refusal also prints a stable text code with the address
of its entry on this page.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | completed and results written, whatever the verdicts |
| 1 | a requested check failed: `--fail-on` matched, a self-test control failed, `fill --check` found a stale document |
| 2 | usage or config error |
| 3 | a side was refused before the run |
| 4 | the machine was refused: a check under `enforce`, or a lock |
| 5 | a launch failed; the capture is kept and marked |
| 6 | the analysis was refused |
| 7 | `fill`: a figure is missing |
| 8 | internal error |
| 130 | interrupted |

`pairbench doctor` always exits 0. `pairbench gate wait-quiet` exits with the code of the
command it ran, or 4 when the machine did not become quiet in time.

## Text codes

Every refusal also has a stable text code. It is printed on standard error as
`E_CODE: message`, followed by a line `pairbench: see ADDRESS` that names the code's entry
below in the documentation of the installed version, and recorded in `refusals[]` of the
results with its scope, `experiment` or `case`. Programs read the text code; the message is for
people. The scope column of the table below lists the scopes pairbench raises each code with; it
documents the code, and a plug-in that raises a code with another scope is not stopped for it.

On standard error the message is escaped, so that it stays on its line and shows in its own
order: a control character is written as `\t`, `\n`, `\r` or `\xNN`, a line or paragraph
separator, a Bidi_Control character or a lone surrogate as `\uNNNN`, and a backslash as `\\`,
so each printed message stands for one text only. A name that a message quotes keeps the
escapes of its quoting, and their backslashes then show doubled: a side named `a\b` is quoted
as `'a\\b'` and shows as `'a\\\\b'`, and an escape character in a quoted name shows as
`\\x1b`. Notes, the lines of machine checks, and each line of the header and each cell of the
table that `pairbench plan` prints are escaped the same way; the tab between two cells is
written as it is. The terminal report shows a control character, a separator, a Bidi_Control
character or a lone surrogate as `?` and prints a backslash as it is. `refusals[]` in the
results keeps the message as it is.

<!-- example -->
```console
$ pairbench compare
E_USAGE: compare needs capture files or --side NAME=file:GLOB
pairbench: see https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_usage
```

| Text code | Exit | Scope | When |
|---|---|---|---|
| `E_USAGE` | 2 | experiment or case | the command line or a library call was given something invalid, or two flags conflict |
| `E_CONFIG` | 2 | experiment | the config holds an unknown key or an invalid value |
| `E_SAME_SIDE` | 3 | experiment | two different sides have the same fingerprint, run in the same working folder and differ at most in a credential's value (allow with `--allow-identical`) |
| `E_SIDE_UNIDENTIFIED` | 3 | experiment | a side could not be identified, or its `identify` command gave no output or failed |
| `E_SIDE_UNRESOLVED` | 3 | experiment | an image, executable, interpreter or working folder was not found |
| `E_ENTRYPOINT_UNREADABLE` | 3 | experiment | an image side runs the shared workload and the entrypoint of its image could not be read |
| `E_ENGINE_UNSUPPORTED` | 3 | experiment | the container engine or the kind of side cannot do what was asked |
| `E_PROFILER_MISSING` | 3 | experiment | the named profiler is not installed |
| `E_PLOT_EXTRA_MISSING` | 3 | experiment | `--plots on` was given and the `plot` extra is not installed |
| `E_TWIN_DRIFT` | 3 or 6 | experiment | a twin's fingerprint differs from its side's: 3 when found as the run starts, 6 when found in the analysis |
| `E_GATE_FAILED` | 4 | experiment | a machine check failed under `enforce` |
| `E_GATE_UNAVAILABLE` | 4 | experiment | a machine check could not run under `enforce` |
| `E_LOCK` | 4 | experiment | a lock could not be taken: timeout or error |
| `E_PIN_UNSUPPORTED` | 4 | experiment | CPU pinning was asked for where it cannot be done |
| `E_CPUS_MIXED_TYPES` | 4 | experiment | the pinned CPU set mixes core types (allow with `--allow-mixed-core-types`) |
| `E_LAUNCH_FAILED` | 5 | experiment | a launch exited non-zero, timed out, or gave output the driver cannot read |
| `E_SIDE_CHANGED` | 5 | experiment | a side's identity changed during the run; the capture is marked failed |
| `E_GPU_NOT_RELEASED` | 5 | experiment | GPU memory did not return to its level in time after a server stopped |
| `E_TOO_FEW_ROUNDS` | 6 | experiment | fewer rounds are planned than can give a verdict (allow with `--allow-underpowered`) |
| `E_CASES_DIFFER` | 6 | experiment | the sides produce different sets of primary cases |
| `E_BUDGET` | 6 | experiment | no balanced round count fits the time budget |
| `E_CAPTURE_INCOMPLETE` | 6 | experiment | a capture has no end record (analyse the complete rounds with `--allow-incomplete`) |
| `E_GRID` | 6 | experiment | the observed grid of rounds and lineup entries does not match the lineup; every missing, duplicated and unexpected cell is listed |
| `E_TWIN_ORPHAN` | 6 | experiment | a twin's side is absent |
| `E_ORDER_NOT_VARIED` | 6 | experiment | a compared pair ran in the same order every round |
| `E_POOL_SAME` | 6 | experiment | the same capture was given twice: the same id, file path or file hash, or of a file a reader splits into runs, the same run |
| `E_POOL_IDENTICAL_ROWS` | 6 | experiment | two captures with different ids hold identical observation rows |
| `E_POOL_TRUNCATED_COPY` | 6 | experiment | one capture's rows are a contiguous stretch of another's, a torn last row included |
| `E_POOL_SIDE_DRIFT` | 6 | experiment | a side's fingerprint, its recorded setup in more than a credential's value, its working folder, or the shared workload in more than a credential's value differs between captures |
| `E_POOL_CASES` | 6 | experiment | the case sets or units differ between captures |
| `E_POOL_MACHINE` | 6 | experiment | the CPU or GPU identity differs between captures (allow with `--allow-mixed-machines`) |
| `E_POOL_MIXED_PURPOSE` | 6 | experiment | a capture of one side against its own twins is pooled with a comparison of sides |
| `E_FIGURE_MISSING` | 7 | experiment | a document names a figure that is absent; every missing key is listed |
| `E_INTERNAL` | 8 | experiment | internal error |
| `E_INTERRUPTED` | 130 | experiment | the run was interrupted |

## Stability of the text codes

Programs that read the text codes can rely on them. The table above is the
whole set, and the same set is `pairbench.errors.CODES`.

- A release adds a text code only when it is a minor or a major release, never a patch
  release, and the changelog entry of that release names the new code.
- A text code is never renamed or removed, and keeps its meaning, until a new major release;
  the changelog entry of that release names it.
- An exit code a text code carries, and the scopes pairbench raises it with, change only in a
  major release; a minor release may add a scope to a code and names it in its changelog entry.

The [changelog](../changelog.md) names every code a release adds. The messages after the code
are for people and can change in any release.

## What each exit code means

### Exit code 0

**Cause.** The command completed and its results were written. The verdicts do not change the
exit code: a run whose cases read SLOWER still exits 0.

**Fix.** Nothing to fix. Read `comparisons[].outcome` and `comparisons[].reason` in
`results.json`; to make a verdict change the exit code, pass `--fail-on`.

### Exit code 1

**Cause.** A check you asked for failed: an outcome named by `--fail-on` occurred, a control of
`pairbench selftest` failed, or `pairbench fill --check` found that the filled document differs
from what the template gives now.

**Fix.** For `--fail-on`, read the verdicts in the report. For `selftest`, the failed control
is printed by name. For `fill --check`, run the same `pairbench fill` command without `--check`
to write the document again.

### Exit code 2

**Cause.** The command line, the config file or a library call was given something invalid:
`E_USAGE` or `E_CONFIG`.

**Fix.** Read the text code's entry below. `pairbench COMMAND --help` lists the flags of a
command, and the [config reference](config.md) every key.

### Exit code 3

**Cause.** A side was refused before the run started: it could not be found, identified or
launched as asked, or two sides are the same.

**Fix.** Read the text code's entry below; it says what to change about the side.

### Exit code 4

**Cause.** The machine was refused: a check failed or could not run while checks are under
`enforce`, or a lock could not be taken.

**Fix.** Read the text code's entry below. `pairbench doctor` says what this machine supports,
and [shared machines](../method/shared-machines.md) how the checks work.

### Exit code 5

**Cause.** A launch failed: it exited non-zero, timed out or gave output the driver cannot
read, or a side changed during the run. The run stops, and the capture is kept and marked
`failed`.

**Fix.** Run the workload by hand on the failing side to see its error. The rounds that
completed can still be analysed with `pairbench compare --allow-incomplete`.

### Exit code 6

**Cause.** The analysis was refused: the captures cannot give a fair comparison, for the reason
the text code names.

**Fix.** Read the text code's entry below. The results are written with the refusal listed and
no comparisons.

### Exit code 7

**Cause.** `pairbench fill` found a token whose figure is not in the results; every missing key
is listed.

**Fix.** Check each key against the `figures` of `results.json`, and correct the template or
name the right results file.

### Exit code 8

**Cause.** The tool hit an error it does not expect. The message names the kind of error.

**Fix.** Report it as an issue with the command, the message and the output of `pairbench
doctor`.

### Exit code 130

**Cause.** The run was interrupted: by Ctrl-C, a termination request, a hangup or a quit
request. The current launch is torn down and the capture's end record says `interrupted`.
The exit code is 130 for each of them, not 128 plus the signal's number, which a shell
reports for a program a signal ends (143 for `SIGTERM`, 129 for `SIGHUP`, 131 for
`SIGQUIT`): the tool catches the signal and ends the command itself. A script that stops
pairbench with `kill` sees 130, as after Ctrl-C.

**Fix.** Run again. The rounds that completed can be analysed with `pairbench compare
--allow-incomplete`.

## What each text code means

Each entry's address is the one a refusal prints on its second line, for example
`pairbench: see https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_usage`.

### E_USAGE

Exit code 2.

**Cause.** The command line or a library call was given something invalid, or two flags
conflict; the message names the flag or the value. `pairbench mcp` refuses with it as well
when the tool-server library is not installed, is a broken install, or has a local module
named `mcp` in its place; the message says which, and what to do. `pairbench run` refuses with it,
before it makes the run folder, an argument that holds a byte that is not UTF-8 where the results
would show it, such as an argument of the workload or the results folder, as the results are
UTF-8 text; the message names the argument by its number and does not show the text. It refuses
the setting `run.node_type` with such a byte, from `--set` or a variable, the same way, as the
results show it. Such a byte where the results hide it or cut it away, in a `--side` spec, a
`--set` value of another setting or a folder of an absolute path, is kept in the capture as an
escape and runs. `pairbench compare` and `pairbench.load_capture` read a capture that holds a
lone surrogate, and the terminal report shows it as `?`. A results document that would hold a
lone surrogate, such as one formed from a capture that holds one in a case, a unit, a tool
version or the command line where the results show it, is refused with it before either results
file is written. The JSON that `pairbench compare --json` prints without `--out` is printed where
standard output can write the surrogate: where Python writes it with the error handler
`surrogateescape`, as it does under a C, POSIX or C.UTF-8 locale and in its UTF-8 mode, which
writes one from U+DC80 to U+DCFF as the byte it stands for, and where standard output is a text
buffer that holds any text. It is refused with it where standard output cannot write it, as
where Python encodes it as UTF-8 with the error handler `strict`, its default under a locale
such as `en_US.UTF-8`. A run of the Python API,
`pairbench.run`, writes no results: it makes none of the early refusals of such a text on this
page, keeps the text in the capture as an escape, and leaves the refusal to what then writes
the results.

**Fix.** Correct the flag or value the message names. `pairbench COMMAND --help` lists the
flags of a command.

### E_CONFIG

Exit code 2.

**Cause.** The config file, a `--set` value or a `PAIRBENCH__` variable holds an unknown key or
an invalid value.

**Fix.** Correct the key or value the message names; the [config reference](config.md) lists
every key with its type and default.

### E_SAME_SIDE

Exit code 3.

**Cause.** Two sides with different names have the same fingerprint: they would run the same
thing, and the comparison would only measure noise. The fingerprint is computed with the
secret forms of [what the shared files hide](config.md#what-the-shared-files-hide) hidden, so
two sides that differ only in such a value, such as `--api-key`, have the same fingerprint and
are refused. A path or a host is hashed as typed, except the parts the shared files hide for
their shape: a random-looking value in a path, such as a run of 32 or 64 hexadecimal digits,
which takes the rest of the path with it when the path starts with `/`, `./`, `../` or `~/`; the port
and path of an address that holds a `+/` run; and a value glued to an option of one letter that
holds a `/` and a random-looking part. Two sides whose specs differ only in such a hidden
part are not refused: `plan` and `run` compare them and give the note
`sides_differ_in_hidden_value`, which names both sides and never the value. The same holds for
what a hidden credential value holds besides the credential itself, as
[hidden values that tell two sides apart](config.md#hidden-values-that-tell-two-sides-apart)
lists: the words after it, such as `HF_TOKEN=t ./bench-old` against `HF_TOKEN=t ./bench-new` in
one argument, the other words of a client's command, and the user, host, path and other query
parameters of an address. The credential itself, an Authorization scheme word and its token,
such as `Bearer t`, or else the value up to its first space, is no difference: two sides that
differ only in it, as in a rotated token, are refused; a password that holds a space and differs
after it, such as `DB_PASSWORD=a b c` against `DB_PASSWORD=a b d`, makes two sides.
Two sides with the same fingerprint that run in two working folders are two sides, and are not
refused either: one program run from two checkouts is what an A/B of two builds often looks
like. `plan` and `run` compare them and give the note `sides_differ_in_hidden_value`, which
names both sides and never a folder. A side's working folder is its `launch.workdir`, read
against the folder pairbench runs from, or that folder itself when none is set. For a side that
runs on the host it is compared by its resolved path, with links followed: a folder and a link
to it are one folder, and one relative path typed from two places names two. For a side that
runs in a container it is compared as typed. The folder is compared as a yes or no and is in
no shared file. A working folder that does not exist is refused with `E_SIDE_UNRESOLVED`.

**Fix.** Check that each side names what you mean to compare. To compare a side with an
identical copy on purpose, pass `--allow-identical`: the results then carry the note
`sides_declared_identical`, which names both sides.

### E_SIDE_UNIDENTIFIED

Exit code 3.

**Cause.** A side could not be identified: its identity could not be read, or its `identify`
command gave no output or failed. `pairbench run` refuses with it, before it makes the run
folder, a side whose identity, as the results show it, holds a text that is not UTF-8; the
message names the place in what the results show of the side. `pairbench.run` from Python keeps
such an identity in the capture as an escape.

**Fix.** Check that the side starts at all, and that the command in `launch.identify` runs
inside it and prints something.

### E_SIDE_UNRESOLVED

Exit code 3.

**Cause.** An image, an executable or an interpreter a side names was not found, or the
working folder of a side that runs on the host, its `launch.workdir` or the folder pairbench
runs from, does not exist or cannot be resolved.

**Fix.** Check the name: pull the image, or give the full path of the executable, interpreter
or environment.

### E_ENTRYPOINT_UNREADABLE

Exit code 3.

**Cause.** An image side that names no `entrypoint` and no `args` runs the shared workload
behind its image's own entrypoint, and the engine's details of the image do not say what that
entrypoint is. The shared files hide a client's password by the program that is given the
workload, so the run does not start: nothing is launched and no capture or results are written.

**Fix.** Set `sides.NAME.entrypoint` to the program the image runs, so that the workload is
read as the words after that program; see
[what the shared files hide](config.md#what-the-shared-files-hide).

### E_ENGINE_UNSUPPORTED

Exit code 3.

**Cause.** The container engine, or the kind of side, cannot do what was asked.

**Fix.** Choose another engine with `--engine`, or drop the setting the message names for that
kind of side.

### E_PROFILER_MISSING

Exit code 3.

**Cause.** The profiler named with `pairbench profile --tool` is not installed.

**Fix.** Install the profiler, or name another with `--tool`.

### E_PLOT_EXTRA_MISSING

Exit code 3.

**Cause.** `--plots on` was given and the `plot` extra is not installed.

**Fix.** Install it with `pip install "pairbench[plot]"`, or leave out `--plots on`.

### E_TWIN_DRIFT

Exit code 3 or 6.

**Cause.** A twin's fingerprint differs from its side's, so the twin does not measure the
side's own noise: exit 3 when found as the run starts, 6 when found in the analysis.

**Fix.** Make the side and its twin the same thing: name an image by its digest, and do not
change an environment while a run uses it.

### E_GATE_FAILED

Exit code 4.

**Cause.** A machine check failed while checks are under `enforce`, for example the machine was
not quiet.

**Fix.** Wait for the machine to become quiet, or pass `--wait-quiet`. Under `--gates warn`,
the default, the run goes on and records the check that failed.

### E_GATE_UNAVAILABLE

Exit code 4.

**Cause.** A machine check could not run while checks are under `enforce`, for example because
the platform does not offer what it reads.

**Fix.** `pairbench doctor` says what this machine supports. Under `--gates warn`, the default,
the run goes on and records the check that could not run.

### E_LOCK

Exit code 4.

**Cause.** A lock named in `gates.locks` could not be taken: another run held it longer than
`gates.lock_timeout`, or it could not be opened.

**Fix.** Wait for the other run to end, raise the wait with `--lock-timeout`, or check that the
lock file can be created.

### E_PIN_UNSUPPORTED

Exit code 4.

**Cause.** CPU pinning was asked for where it cannot be done: the platform, or the kind of
side, cannot apply the pinned set at launch.

**Fix.** Leave out `--cpus` for that side, or run it as a kind of side that can apply a CPU
set.

### E_CPUS_MIXED_TYPES

Exit code 4.

**Cause.** The pinned CPU set mixes core types, for example performance and efficiency cores,
which run the same work at different speeds.

**Fix.** Pin CPUs of one core type; `pairbench gate check --cpus LIST` says whether a set mixes
them. To accept the mix, pass `--allow-mixed-core-types`.

### E_LAUNCH_FAILED

Exit code 5.

**Cause.** A launch exited non-zero, timed out, or gave output the driver cannot read. A case,
a metric, a unit or a tool version that the driver read into what the launch records and that
holds a lone surrogate, an escape from `\ud800` to `\udfff` with no partner, is refused as
well, as the results show it and it is not UTF-8 text; so is a tool name that holds one where
the note of an untested version would show it. The message names the side and shows the text
as the results show a case, its secret forms hidden and the folders of a path cut away,
escaped, at most 40 characters on each side of the surrogate, or no text where the cut leaves
the surrogate out. It names no key of the tool's output, since a key may hold a path or a
secret. A lone surrogate in a part of the output the driver does not
read, in a folder of a path that the results cut away, or in a case the positive control does
not record (a case only one of its two runs gave, which a note names escaped, or a case whose
`better` is `none`), is no reason to refuse. The check is made where a command line is
recorded: by `pairbench run`, `pairbench compare` and `pairbench selftest --live`, and by the
tool server that `pairbench mcp` starts, whose runs are started as `pairbench run`. A call from
Python, of `pairbench.run` or of the compare tool of a tool server built in Python, records
none: it makes none of these early refusals and keeps such a text in the capture as an escape,
and results that would hold it are refused with `E_USAGE` when they are written. A call from
Python inside `pairbench.api.command_line` makes them as the command line does.

**Fix.** Run the workload by hand on the side to see its error, check that `--driver` names the
tool whose output the workload prints, and raise `--timeout` if the launch needs longer.

### E_SIDE_CHANGED

Exit code 5.

**Cause.** A side's identity changed during the run, for example an image tag was moved to
another image; the capture is marked failed.

**Fix.** Name images by digest, and leave the sides' environments alone while a run uses them.

### E_GPU_NOT_RELEASED

Exit code 5.

**Cause.** After a server stopped, the GPU's memory did not return to its level from before the
launch in time, so the next launch would not start from the same state.

**Fix.** Check for another process on the GPU, and that the server's container stops when it is
told to.

### E_TOO_FEW_ROUNDS

Exit code 6.

**Cause.** Fewer rounds are planned than can give a verdict for the number of primary cases
under the rule's alpha.

**Fix.** Plan more rounds with `--rounds`, or let the planner choose with `--rounds auto`.
`--allow-underpowered` runs anyway and every comparison reads NO VERDICT.

### E_CASES_DIFFER

Exit code 6.

**Cause.** The sides produce different sets of primary cases, so some cases have nothing to
compare with. When names differ only in the mark ` +` and eight hex digits, the sides' ids run
over different words that hold no `/`, as a folder whose name holds a space and differs between
the sides gives. A path written with `%2F` ends at a blank, so the words of a folder named with
blanks in such a path show, and sides whose folders differ there name the case apart.

**Fix.** Make every side produce the same cases, or choose the shared ones with `--case`. For
names that differ only in the mark, give the cases names that differ before the path, or put
the path in quotes. In a path written with `%2F`, write each blank of a folder name as `%20`.

### E_BUDGET

Exit code 6.

**Cause.** No balanced number of rounds fits the time budget.

**Fix.** Give a larger `--budget`, or compare fewer sides or cases.

### E_CAPTURE_INCOMPLETE

Exit code 6.

**Cause.** A capture has no end record: the run that wrote it did not finish.

**Fix.** Run again, or analyse the complete rounds with `pairbench compare --allow-incomplete`.

### E_GRID

Exit code 6.

**Cause.** The observed rounds and lineup entries do not match the lineup: a cell is missing,
duplicated or unexpected. Every such cell is listed. With `pairbench compare --matching`, no
round of the two-sided view holds both sides: no pass-order line names both sides before
their rows, a name matches no row, or the two sides never share a round label within a run;
the message gives the number of rows the view keeps and the number it left out.

**Fix.** Give one value per case for every entry in every round. For rows produced elsewhere,
check the round labels and side names of the listed cells. For `--matching`, check the
`pass_order=` lines of each run, the round labels of the two sides within each run, and the
names given to `--subject` and `--baseline`.

### E_TWIN_ORPHAN

Exit code 6.

**Cause.** A twin is present but the side it is the twin of is absent.

**Fix.** Include the side, or leave out its twin.

### E_ORDER_NOT_VARIED

Exit code 6.

**Cause.** A compared pair ran in the same order in every round, so the order cannot be told
apart from the sides.

**Fix.** Run with the schedule pairbench plans, which varies the order every round. For rows
produced elsewhere, give the positions each side ran in. For a text capture, let its
`pass_order=` lines turn the order of the sides from round to round; with
`compare --matching`, a reversed pass that reuses every round label of a forward pass gives
every cell, so give it labels of its own.

### E_POOL_SAME

Exit code 6.

**Cause.** The same capture was given twice: the same id, file path or file content. A
reader that splits a file into runs, as the `text` reader does, gives one capture per run, and
two different runs of one file are two captures; the same run given twice is refused.

**Fix.** Give each capture once.

### E_POOL_IDENTICAL_ROWS

Exit code 6.

**Cause.** Two captures with different ids hold identical observation rows: one is a copy of
the other.

**Fix.** Leave out the copy.

### E_POOL_TRUNCATED_COPY

Exit code 6.

**Cause.** One capture's rows are a contiguous stretch of another's, a torn last row included:
one is a partial copy of the other.

**Fix.** Leave out the partial copy.

### E_POOL_SIDE_DRIFT

Exit code 6.

**Cause.** A side's fingerprint differs between the captures being pooled: they did not compare
the same things. A side whose setup, as each capture records it, differs only in a value the
shared files hide for its shape, such as a run of hexadecimal digits in a path, or in what a
hidden credential value holds besides the credential itself, such as
`HF_TOKEN=t ./bench-old` against `HF_TOKEN=t ./bench-new` or the database number of
`redis://:t@localhost/0`, is refused too, though its fingerprint is the same; the message names
the side and the two captures, never the value.
[Hidden values that tell two sides apart](config.md#hidden-values-that-tell-two-sides-apart)
lists what counts. A side whose `identify` command printed, in one capture and the other, a
different checksum, build id or version, such as the checksum `md5sum` prints of a weights file
that has changed, has a different fingerprint: that output is hashed with only its credentials
hidden. A side that differs only in the credential itself, such as the value of `--api-key` up
to its first space, or a token after `Bearer` in the same value, is the same side, and its
captures pool, so a token rotated between two runs does not stop them pooling; a password that
holds a space and differs after it, such as `DB_PASSWORD=a b c` against `DB_PASSWORD=a b d`, is
drift. A capture that does not record a side's setup is checked by the fingerprint alone.
A side that ran in two working folders, one capture against the other, is drift too, with the
same fingerprint: each capture records a hash of the folder each side ran in, the resolved path
for a side that runs on the host, and the message names the side and the two captures, never
the folder. A capture that records no working folder for a side is not pooled with one that
records it: the message says the folder could not be compared, and names the capture to run
again. Two captures whose shared workloads, the arguments after `--` or `workload.argv`, differ are
drift too, whatever the kind of their sides: `--size 10` against `--size 20`, an argument added,
left out or moved, a value glued to its option (`--size=10` against `--size=20`, and also
`--size=10` against `--size 10`), or a word inside a shell text such as
`sh -c "bench --size 10"`. The workloads are compared as `provenance.config_sha256` hashes them:
a difference only in a credential, such as the value of `--api-key` or a client's password
option, pools, and so does a difference only in the value of an option whose name reads as a
credential's, such as `--password-length 8` against `--password-length 12`, as the hash hides
that value too; a difference only in a value hidden for its shape gives the hidden-value message
above. The message names the first argument that differs, by its place and by the text the
results show of it, such as
`the workload differs between the captures A and B at its argument 4: 10 against 20`, with
`no argument` for a workload that ends before that place; when both show the same text, as two
paths in different folders do, it says the arguments differ in a part the shown command leaves
out. A label such as `run.node_type` and a case selection are no part of the workload.

**Fix.** Pool only captures of the same sides and the same workload, or compare the captures one
at a time.

### E_POOL_CASES

Exit code 6.

**Cause.** The case sets or their units differ between the captures being pooled. A case
whose name ends with a mark, ` +` and eight hex digits, is named again with the key of the
first capture given, so two captures whose ids differ in a word a path runs over that holds no
`/` name different cases.

**Fix.** Pool only captures with the same cases in the same units. Give cases names that
differ outside their absolute paths, as
[what the shared files hide](config.md#what-the-shared-files-hide) says of case ids that read
alike.

### E_POOL_MACHINE

Exit code 6.

**Cause.** The CPU or GPU identity differs between the captures being pooled.

**Fix.** Pool captures of one machine. To pool across machines on purpose, pass
`--allow-mixed-machines`; the results say so.

### E_POOL_MIXED_PURPOSE

Exit code 6.

**Cause.** A capture of one side against its own twins is pooled with a comparison of sides.

**Fix.** Pool captures of the same purpose only.

### E_FIGURE_MISSING

Exit code 7.

**Cause.** A document given to `pairbench fill` names a figure that is not in the results;
every missing key is listed. A case name that ends with a mark, ` +` and eight hex digits, is
made with its run's own key, so results of another run, or of another compare, name that case
with another mark.

**Fix.** Check each key against the `figures` of `results.json`, and correct the template or
name the right results file. For a key with a mark, fill from the results the document's
figures came from, or pool all the captures with one `pairbench compare` and fill from that.

### E_INTERNAL

Exit code 8.

**Cause.** The tool hit an error it does not expect; the message names the kind of error.

**Fix.** Report it as an issue with the command, the message and the output of `pairbench
doctor`.

### E_INTERRUPTED

Exit code 130.

**Cause.** The run was interrupted by Ctrl-C, a termination request, a hangup or a quit
request.

**Fix.** Run again, or analyse the complete rounds with `pairbench compare --allow-incomplete`.

## After a refusal

A run writes its folder even when it ends in a refusal after the capture was opened. A launch
that fails stops the run at once: the capture is kept with the status `failed`, and the
results are written with the refusal and no comparisons. The rounds that completed can still
be analysed with `pairbench compare --allow-incomplete`.

On an interrupt, the current launch is torn down, the capture's end record says
`interrupted`, and the exit code is 130. Ctrl-C, a termination request (`SIGTERM`), a
hangup (`SIGHUP`, sent when the terminal or the remote session closes) and a quit request
(`SIGQUIT`) are all interrupts. When the terminal has closed, the line that says so has
nowhere to go and is dropped; the exit code is still 130. A signal the tool was started with
ignored stays ignored: under `nohup`, which ignores the hangup, a run goes on after its
terminal closes.
