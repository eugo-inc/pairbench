---
description: "Resource figures, hardware counters, sampled stacks and flame graphs: what a finding says, and what it never says."
---

# What do the diagnostics say about how two sides differ?

They describe how two sides differ in what they used: CPU time, cores, memory, hardware
counters and where samples of the call stack fell. They never state a cause, never change a
verdict and never change an exit code.

## Resource figures of every launch

Every measured launch records these figures, where the platform or the engine reports them,
as cases under the reserved prefix `res/`. No extra launch is needed.

| Case | Unit | Value |
|---|---|---|
| `res/user` | s | CPU time in user mode |
| `res/sys` | s | CPU time in the kernel |
| `res/cores` | cores | user plus system CPU time, divided by the run time |
| `res/rss_peak` | bytes | peak resident memory |
| `res/ctx_voluntary` | count | voluntary context switches |
| `res/ctx_involuntary` | count | involuntary context switches |
| `res/faults_major` | count | page faults that needed input or output |
| `res/faults_minor` | count | every other page fault |

- **Source**: for command and Python environment sides, the resource usage the exit status
  call returns for the process and the children it waited for; for image sides, the engine's
  statistics for the container, where it has them; for serving sides, the engine's
  statistics for the server over the load phase. A figure the source does not give is a
  missing case, named once in a note.
- These cases are always secondary and their `better` is `none`: they read HIGHER or LOWER,
  never BETTER or WORSE. A report can then say "cores used: 7.8 against 1.0" (made-up
  numbers).
- Each is a floor group of its own. A zero gives that one case
  `NO VERDICT (nonpositive_value)` and touches no other case; the medians are still recorded.
- The positive control records no `res/` cases.

## The explain step

After the last measured round, each subject and the baseline are launched again under
instruments. Twins and the positive control are not. The step runs after the capture is
closed and the results are written, so it cannot change a comparison. Its launches are
untimed and are recorded in `diagnostics.json`, never in the capture.

`--explain always|auto|off` (`explain.mode`), default `always`. `auto` runs the step only when
a primary case came out `better` or `worse`. The plan prints the explain launches, their
estimated time and how to turn the step off.

| Instrument | Program | Gives |
|---|---|---|
| `counters` | `perf stat` | event counts for the whole launch: instructions, cycles, branches, branch misses, cache references, cache misses, task clock, context switches, CPU migrations, page faults |
| `stacks` | `perf record`, read back with `perf script` | sampled call stacks, native and Python frames, 99 times per second by default (`explain.sample_hz`), call graphs by frame pointer, DWARF or LBR (`explain.call_graph`) |
| `pystacks` | a sampler that is part of pairbench | sampled call stacks, Python frames only |

Counters and stacks are taken in separate launches, because sampling disturbs the counts.
For `stacks`, the launch's environment gets the variable that makes CPython report Python
function names to `perf`, where the interpreter supports it.

`pystacks` needs no privilege. It is used for a side only when `stacks` cannot run there and
the side's command starts with a Python interpreter (3.8 or newer); for an image side that
is the image's whole command line, its entrypoint first. It reads the interpreter's own
frames; what native code does shows as time in the Python function that called it. The
flame graph and the diagnostics say which instrument made them.

pairbench never changes a system setting. An instrument that cannot run is skipped for that
side with a loud note that names the instrument and the reason: the program is not
installed, the system does not permit it, the image does not hold the program, or the
container has no capability to use performance counters. A skipped instrument never fails
the run. `pairbench doctor` names the setting or capability that forbids an instrument.

An image side is measured inside its container, so the image must hold `perf`, and the
launch needs `perf_counters = true` in its launch settings, which gives the container the
capability to use performance counters and nothing else. See
[perf in an image](../guides/perf-in-an-image.md).

## What is made from the stacks

- `profiles/<side>.folded`: one line per distinct stack, frames from outermost to innermost
  joined by `;`, then a space and the number of samples.
- `profiles/<subject>_vs_<baseline>.folded-diff.tsv`: one row per stack seen on either side,
  with the samples and shares of both sides and the change in share.
- Per side, the 20 functions and shared objects with the largest share of samples
  (`explain.top`); a sample belongs to its innermost frame. A function the compiler inlined
  is a frame of its own, and it belongs to the shared object of the function it was inlined
  into.
- The shared objects each side loaded: which are on one side only, and which have the same
  name on both sides but a different build id.
- A difference is made only when both sides' stacks come from the same instrument.

## Flame graphs

pairbench writes each flame graph itself, as one self-contained SVG file per side and one
difference graph per subject. A click on a frame zooms to it, one control leads back, a text
search marks the matching frames, and pointing at a frame shows its full name and its share
of samples. A graph makes no network request and loads no outside script, font or style
sheet; it works opened as a file and embedded in `report.html`. The difference graph shows
the subject's stacks, coloured by the change in share between the subject and the baseline,
with a legend in words; stacks that only the baseline has are listed under it.

A web page that strips scripts from pictures shows the graph without the interaction.

## What a finding says and what it does not

A finding is a sentence made by code from a fixed template, together with the numbers it was
made from, for example (made-up numbers):

> new used 7.8 cores against 1.0 for old (median of 20 rounds).

The findings of this release: `cores_used`, `cpu_time_split`, `peak_memory`,
`context_switches`, `page_faults`, `instructions`, `instructions_per_cycle`, `cache_misses`,
`branch_misses`, `top_function_share`, `top_object_share`, `objects_on_one_side`,
`objects_differ`.

A finding uses descriptive words only: share of samples, differs, more, fewer, higher, lower.
It never says that one thing causes another. A side that used eight times the cores and
finished faster may be faster for that reason, or for another one the instruments do not
see; deciding which is the reader's work, with the numbers in front of them. A finding is
produced only when its numbers exist; a skipped instrument produces no finding and no
placeholder.

## Privacy

`results.json` and `results.md` hold the `res/` comparisons, the path of the diagnostics and
the state of the step, never a function name; what else they may hold, the known limits of
the shown command among it, is in the
[security policy](../../SECURITY.md#what-results-may-hold). Function names,
shared-object names and stacks appear only in `diagnostics.json`, the files under
`profiles/` and `report.html`, and each says near its top that it holds names from your
code. Read them before you share them. `diagnostics.json`, the folded stacks, differences
and flame graphs under `profiles/`, and what the instruments print while they run are readable
and writable by you only (mode `0600`) whatever your umask; `report.html` is a results file,
readable by all (mode `0644`), and it embeds the diagnostics and the flame graphs when the step
ran.

## Recording more

`pairbench profile --from results.json --tool perf` records stacks again for the named side,
or for each subject and the baseline, and refuses when `perf` is missing
(`E_PROFILER_MISSING`). `--tool nsys` and `--tool ncu` run a GPU profiler you installed
yourself. See the [command reference](../reference/commands.md#profile).

The documentation shows no diagnostics, flame graph or report page of a real run.

## What this repository publishes

pairbench gives full diagnostics for any sides you run. What the repository itself publishes
is narrower: no flame graph, folded-stack file, difference file, diagnostics document or report
page from a real run is committed here. The one exception is a showcase whose sides are all
public images and whose result the maintainers have approved. Examples in this documentation use
comparisons of public images only. [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
states the same rule.
