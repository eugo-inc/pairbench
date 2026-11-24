---
description: "The files of a run folder, the fields of results.json a program reads, the figure keys for documents, and diagnostics.json."
---

# What is in a run folder and in results.json?

A run folder holds the raw capture, the analysed `results.json`, the reports and, when asked
for, charts, profiles and the diagnostics; this page lists each file and the fields a program
reads. A run writes these files into its folder:

| File | Holds | Share it? |
|---|---|---|
| `capture.jsonl` | the raw record of the run, one JSON record per line, readable by its owner only (mode `0600`) | never share it: it keeps the command line as typed, credentials included, and details of the machine and the sides |
| `results.json` | the analysed document, schema `pairbench/results/v1` | meant to be shared |
| `results.md` | the report in Markdown | meant to be shared |
| `plan.tsv` | the planned rows: `round pos name side twin_of` | yes |
| `report.html` | one self-contained page with the report, charts and flame graphs | holds names from your code when diagnostics ran |
| `diagnostics.json` | the explain step's document, schema `pairbench/diagnostics/v1`, readable by its owner only (mode `0600`) | holds names from your code |
| `profiles/` | folded stacks, differences and flame graphs, and the reports of `pairbench profile --tool nsys` or `ncu`, readable by their owner only (mode `0600`) | holds names from your code |
| `charts/` | the charts, when the `plot` extra is installed | yes |
| `hash_inputs.json` | not written by a run: `tools/hash_inputs.py` of the source repository writes it, with what each published hash is taken over | private, like the capture: it holds each side's whole command; the script writes it owner-only and says so, unless each value it holds passes as one of the kinds that `SECURITY.md` lists: shown values, which `results.json` and `results.md` show, neutral places, schema ids and keys, config-schema values and config defaults, or null, true, false and empty values; of the neutral places `/work`, `/home/user` and `/usr/local/bin/python3` each passes only as itself, and a path under one only when they show each of its other parts |
| `artifacts/` | one folder per launch, named by its number and lineup entry, with what it printed (`stdout.txt`, `stderr.txt`), the files its tool wrote and, for a server, `server.log`; `cost/` holds the launches that measure the tool's own cost; once a launch ends, every file in its folder that you own is readable by its owner only | private: it holds what your workload and its tools printed |

The capture keeps every argument of the command line and every side as you typed it: the
value of an option such as `--token`, a header or a password in an address stays in it. Only
the value of an environment variable whose name looks like a credential, in the recorded
config or in a `--set` on the command line, is replaced by `"<redacted>"`. The files to share
are `results.json`, `results.md` and `report.html`: they hide the values of credential-like
names and headers, host names and paths outside the run folder, except an image reference you
ask for and the forms that the
[security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists as known limits
of the shown command.

`pairbench schema capture|results|config|diagnostics` prints each JSON Schema. Adding an
optional field, or a value to a field whose schema lists its values (such as a new `reason`),
keeps the schema version; renaming or removing a field or a value, or changing its meaning,
needs a new version. Each schema refuses a field it does not list, so check a document against
the schema printed by the release that wrote it or a later one.

## `results.json`

Numbers in this example are made up.

```json
{"schema": "pairbench/results/v1",
 "tool": {"name": "pairbench", "version": ""},
 "run": {"id": "", "started_at": "", "finished_at": "",
         "captures": [{"capture_id": "", "sha256": "", "rounds": 16}],
         "pooled": false, "command": ""},
 "rule": {"name": "strict", "fields": {}, "family_size": 2,
          "plain": "corrected for testing 2 cases at once"},
 "provenance": {"machine": {"os": "", "arch": "", "cpu_model": "", "core_types": []},
                "gpu": [{"model": "", "driver": ""}],
                "engine": {"name": "", "version": ""}, "node_type": null,
                "driver": {"name": "wall", "tool_versions": []},
                "seeds": {}, "config_sha256": ""},
 "sides": [{"name": "", "kind": "", "role": "", "twin_of": null, "control_of": null,
            "identity": {"image_id": "", "digests": [], "platform": ""}, "fingerprint": "",
            "image_ref": null}],
 "plan": {"schedule": "rotate-reverse", "rounds_requested": 16, "rounds_planned": 16,
          "rounds_completed": 16, "warmups": 1, "launches": 82, "explain_launches": 4},
 "machine_state": {"status": "quiet", "gates": [], "degraded": [], "undecided_launches": 0,
                   "discard_sha256": null},
 "cases": [{"id": "", "metric": "", "unit": "", "better": "lower", "kind": "time",
            "primary": true, "group": null}],
 "comparisons": [{"case": "", "primary": true, "subject": "", "baseline": "",
   "n_rounds": 16, "n_unpaired": 0, "n_untied": 16, "n_lower": 15, "n_higher": 1,
   "subject_median": 0, "baseline_median": 0, "ratio": 0.797, "statistic": 0.797,
   "scale": "ratio", "gap": 0.203,
   "floor": {"source": "twins", "unit": "fraction",
             "subject": {"value": 0.011, "n": 16, "provisional": false, "spread": 0.02,
                         "outlier_rounds": []},
             "baseline": {"value": 0.007, "n": 16, "provisional": false, "spread": 0.02,
                          "outlier_rounds": []}, "mode": "TWO-SIDED"},
   "bar": 0.018, "p_raw": 0.0005, "p_raw_fraction": [34, 65536], "p_corrected": 0.001,
   "verdict": "FASTER", "outcome": "better", "reason": null, "reasons": [],
   "order_split": [8, 8],
   "sensitivity": {"rounds_set_aside": [], "ratio": 0.797, "outcome": "better",
                   "agrees": true, "not_computed": null}}],
 "same_vs_same": [{"side": "", "case": "", "ratio": 1.004, "floor": 0.004, "unit": "fraction",
                   "p_raw": 0.80, "n": 16}],
 "twin_checks": [{"side": "", "n_rounds": 16, "n_better": 7, "n_worse": 9, "p_raw": 0.80,
                  "p_corrected": 0.80}],
 "controls": {"positive": {"status": "ok", "entry": "old~twice", "via": "repeat",
   "tolerance": 0.1, "cases": [{"case": "", "expected": 2.0, "ratio": 2.01,
   "p_raw": 0.00003, "n_rounds": 16, "passed": true}]}},
 "launch_cost": {"command": "true", "n": 20, "median_s": 0.0005, "p25_s": 0.0004,
                 "p75_s": 0.0007, "min_s": 0.0003},
 "env_pad": {"varied": false},
 "series": [{"case": "", "name": "", "values": [], "disturbed_rounds": []}],
 "plots": {"status": "drawn", "reason": null},
 "diagnostics": {"status": "written", "reason": null},
 "refusals": [{"code": "", "scope": "experiment", "message": ""}],
 "notes": [],
 "plugins": {"loaded": 0, "failed": 0},
 "figures": {"matmul.new_vs_old.ratio": {"value": 0.797, "text": "0.80x"},
             "matmul.new_vs_old.verdict": {"value": "better", "text": "FASTER"}},
 "artifacts": {"capture": "capture.jsonl", "markdown": "results.md", "plan": "plan.tsv",
               "html": "report.html", "diagnostics": "diagnostics.json", "charts": [],
               "profiles": []}}
```

### Fields worth knowing

- `comparisons[].outcome` is `better`, `worse`, `higher`, `lower`, `tie`, `unresolved` or
  `no_verdict`; `reason` is the main reason and `reasons` lists every one that applies. See
  [verdicts](../method/verdicts.md). Programs read these, never `verdict`, the display word.
- `statistic` is the signed value the rule graded and `scale` is the rule's scale; `ratio`
  is the median of the per-round ratios under every scale. `floor.unit` is `fraction` or
  `percent`.
- `p_raw_fraction` is the uncorrected p-value as an exact fraction whose denominator is 2 to
  the power of the untied pairs. It is null for a single measurement, and from 14285 untied
  pairs on, where the denominator has more than 4300 digits; `p_raw` is still given. 4300
  digits is the default limit on converting between a whole number and decimal text in
  Python 3.11
  ([integer string conversion length limitation](https://docs.python.org/3.11/library/stdtypes.html#int-max-str-digits)),
  so a results file stays readable.
- `same_vs_same[]` holds a side against its own twin on each case, with its own uncorrected
  `p_raw`. A difference on one case shows here, and gives the loud note only through the
  combined check below, where, in a side with three or more primary cases, it moves a round
  only when other primary cases of the side lean the same way.
- `twin_checks[]` holds one combined check per side that has a twin, across its primary
  cases: `n_rounds` rounds scored, `n_better` and `n_worse` the rounds whose median turned
  log of side over twin across those cases says the side looks better or worse, the sign
  test's `p_raw`, and `p_corrected`, corrected with Holm's method across the sides that have
  a p-value. Both are null for a side scored in at most one round. A side whose corrected
  p-value is below 0.05 gives the loud note `twin_differs`; the compare is made on the exact
  Holm correction of the sign test's fraction against exactly 1/20, not on the float
  `p_corrected`. A document written without
  `twin_checks` reads as holding none, and `pairbench report --format json` then gives an
  empty list. See the [noise floor](../method/noise-floor.md).
- `run.command` is the command that was run, for the "how to reproduce" line of the reports.
  Side specs are hidden unless `report.include_image_refs` is on, which shows the spec of an
  image or serving side. The value of every `--set` is hidden whatever its key, and its key is
  kept: `--set launch.cpus=0-3` shows `--set 'launch.cpus=<hidden>'`. With
  `report.include_image_refs` on, the results show image references as typed, local archive
  paths included (`new=image:oci-archive:/made/up/new.tar` stays whole). Other absolute paths,
  including those that start with `~/`, `~user/` or `//`, the path of a `file://` address with
  what stands before it (`file://localhost/a/m.gguf` shows `file://m.gguf`) and the path of any
  other address whose host is empty (`sqlite:////a/db.sqlite` shows `sqlite:///db.sqlite`), are
  cut to their last part, also when glued to an option (`-I/a/include` shows `-Iinclude`) or
  written after a redirection (`<in.txt>/a/out`), while the `/` after the arguments of a name
  such as `BM_made_up<A, int>/8` is kept. A relative path that climbs out of its folder with `..`
  is cut the same way (`../../a/in.csv` shows `in.csv`). A path whose last part is a home
  folder, the folder right under `/home` or `/Users` or a home written `~made-up-user`, shows
  `<hidden>` in place of that folder's name (`../home/user` shows `<hidden>`), while the
  hashes take it as typed. A `file://` address with a host and no
  path loses the host (`file://made-up-host` shows `file://<hidden>`). Secrets are replaced by `<hidden>` in the forms that
  [what the shared files hide](config.md#what-the-shared-files-hide) lists: the value of a
  credential-like name, the value of a credential header, the user part and the host of an
  address, the password of a `user:password` value, the password options of benchmark
  clients such as `redis-benchmark -a` and `mysql -p`, the passwords in the
  [commands of Redis and Valkey clients](config.md#passwords-in-the-commands-of-redis-and-valkey)
  (`ACL SETUSER`, `AUTH`, `CONFIG SET`, `HELLO`, `MIGRATE`, `SENTINEL CONFIG SET`,
  `SENTINEL SET`), and long random-looking values. These
  rules also hold inside one argument that holds several words, such as the text after
  `sh -c` or the remote command of `ssh`, and inside a quoted word of it. The workload after
  `--` is read after the words each command side runs before `{workload}` too, so a client
  named only in a side's spec hides its password there (`-- -a '<hidden>' -n 1000`). A short
  plain value that nothing on that list names, such as one given after an option of one
  letter, as a plain argument or in the path of an address, is shown; a secret given to a side through the environment with `env_pass`
  is never recorded.
- The hashes of a side and of the config, `argv_sha256`, `args_sha256` and `identify_sha256`
  in `sides[].identity`, `sides[].fingerprint` and `provenance.config_sha256`, are computed
  with the recognised secret forms hidden, and the output of an `identify` command with only
  its credentials hidden, line by line:
  each such value is replaced by `<hidden>` before hashing, so a guess at it cannot be
  checked against a hash, and two sides or captures that differ only in such a value have
  the same hash. A file side is the exception: its `files_sha256` and its fingerprint cover
  each result file as it is, a secret in a case id included, and its fingerprint covers the
  absolute path of each file, as the
  [known limits](../../SECURITY.md#known-limits-of-the-hashes) say. The case patterns of the config are in `provenance.config_sha256` as typed,
  as the [known limits](../../SECURITY.md#known-limits-of-the-shown-command) say. Hosts and ordinary values are hashed as they are, and so is a path but for
  its random-looking parts. Two sides whose specs differ only in a value hidden for its shape,
  or in what a hidden credential value holds besides the credential itself, as
  [hidden values that tell two sides apart](config.md#hidden-values-that-tell-two-sides-apart)
  lists, have the same fingerprint: `plan` and `run` still compare them, with the note
  `sides_differ_in_hidden_value`, which names both sides and never the value, and captures
  whose sides differ so are not pooled (`E_POOL_SIDE_DRIFT`). So are two sides, or captures,
  that run one program in two working folders: the working folder is compared by a hash the
  capture keeps, never shown, and the note names the sides, never the folders. Sides that are
  one side, compared because `--allow-identical` was given, get the note
  `sides_declared_identical`. A checksum, a build id or a
  version an `identify` command prints is in `identify_sha256` and the fingerprint, so captures
  that differ in one are not pooled either. Nor are captures whose shared workloads differ, read
  as `provenance.config_sha256` reads them: a difference only in a credential pools. A value in a form the tool does not recognise is
  still in the hash, and someone who knows the rest of the command can confirm a guess at it
  by hashing the guess; give secrets to a side through the environment with `env_pass`, which
  no hash covers.
- A published hash covers paths and hosts as typed, so a reader who knows the rest of a side's
  command can confirm a guessed user name, host or path by hashing the guess. A fingerprint
  covers the side's identity the same way, such as its command as typed; of its executable it
  covers the last part of the path, not the folder. To avoid it, keep such values out of the
  side's command: run it from a neutral folder, and pass values to it through
  `launch.env_pass`, which no hash covers. In the source repository,
  `tools/hash_inputs.py RUN_FOLDER` writes `hash_inputs.json` into a run folder: what each of
  the five published hashes (`argv_sha256`, `args_sha256`, `identify_sha256`, the fingerprint
  and `provenance.config_sha256`) is taken over, rebuilt from the capture and checked against
  the results, so that `pairbench.model` of the same version recomputes those five from it.
  This page does not define how those inputs are written out before hashing. The sidecar
  holds each side's whole command with only the recognised secret forms hidden, so it is
  private like the capture; see the run-folder table above.
  `tools/hash_inputs.py RUN_FOLDER --publish FOLDER` copies `results.json`, `results.md` and
  `report.html` into the folder, and the sidecar with them only when it can be shared;
  otherwise the sidecar stays owner-only in the run folder and is not published. It refuses a
  `FOLDER` that is the run folder, lies inside it or holds it, and it checks every file before
  it copies any: a publish that fails before its first copy leaves `FOLDER` as it was and says
  "nothing published", and one that fails after it says "partly published" and names exactly
  the files it copied, both with exit 2. A results
  file kept in the source repository has a sidecar that passed this check beside it, except
  one: the launch-cost results are kept without their sidecar because the results hide the
  two side commands; the commands are the constants of `tools/launch_cost.py`, so a reader
  runs that script to repeat the run rather than recomputing the hashes.
- `sides[].driver`, when known, is `{"name": "", "tool_versions": []}`: the driver that read
  that side and the tool versions its launches recorded. A result file side may name its own
  driver (`format`); when the subjects and the baseline were read by different drivers, the
  results carry the note `drivers_differ`, because two tools may define the same figure
  differently. A driver that a plug-in provides is never named (`name` is `null`).
  `provenance.driver` is the driver of the whole run, made of the drivers of its sides:
  `tool_versions` lists every version the launches recorded, and `name` is kept only when
  every side names the same driver; otherwise it is `null`. For pooled captures this holds
  across every capture, and the note `drivers_differ` names the driver of each capture.
- `machine_state.status` is `quiet`, `busy` or `unknown`. It also carries the hash of the
  decision to set rounds aside and `undecided_launches`; an absent count is 0. Each entry
  of `machine_state.gates` and `machine_state.degraded` names a built-in check (`cpus`,
  `quiet`, `census`, and the readiness checks `stop_file`, `gpu_memory` and `check_locks`)
  or `plugin` for a check a plug-in provides; a readiness check that is off has no entry. See
  [shared machines](../method/shared-machines.md).
- `energy`, present when power was sampled:
  `{"scope": "gpu", "excludes": ["cpu", "memory", "storage", "cooling", "power supply losses"]}`.
- `matching`, present only when `pairbench compare --matching` read the captures:
  `{"runs": 2, "malformed_rows": 1, "kept_rows": 40, "left_out_rows": 3, "other_side_rows": 0,
  "refusal": null}`. `runs` counts the runs of the text the files make together, one per
  banner or one when there is none; `malformed_rows` the rows that did not read and
  `kept_rows` the rows kept; `left_out_rows` the kept rows of the two compared sides that the
  two-sided view left out because no pass-order line of their run named both sides before
  them; `other_side_rows` the kept rows of every other side. When the matching mode refused
  the comparison, `refusal` holds the refusal's detail, and its `check` names the check:
  `identical_written_rows`, `written_stretch`, `identical_rows` or `truncated_copy` for the
  [pool checks](text-format.md#pool-checks-of-a-matching-read), or `paired_rounds` for a view
  without a round that holds both sides. A refusal of the analysis of the view, such as
  `E_ORDER_NOT_VARIED`, is listed under `refusals` only, and `refusal` stays `null`. The view
  has no twins, so each case of it also gets
  the note `view_without_twins` in `notes`. See [compare](commands.md#compare).
- `plan.launches` counts warm-up and round launches, one per round for the positive control;
  `plan.explain_launches` counts the explain launches.
- `diagnostics.status` is `pending`, `written`, `skipped`, `off`, `failed` or `interrupted`;
  `reason` says why a step was skipped: `mode_auto_no_difference`, `lock` or `no_instrument`.

### What a results file never contains

`results.json` and `results.md` never contain a host name, a user name, a home or working
directory or any absolute path outside the run folder; a GPU serial number or unique device
id, a network hardware address, a machine id, or a cloud instance or account id; environment
variable values; the registry or repository part of an image reference; the names of
plug-ins; or a function name, shared-object name or call stack, except an image reference you
ask for and the forms that the
[security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists as known limits
of the shown command, such as a host or a user written without a scheme. With
`report.include_image_refs` on, the results show image
references as typed, local archive paths included, so a reference names its registry and a
local archive names its folders.

Machine facts are limited to the operating system name and version, the CPU architecture and
model string, a summary of core types, the GPU model and driver version, the container engine
name and version, and a `node_type` you may set.

## Figures

`figures` is a flat map from a stable key to `{"value": ..., "text": string}`. A value is a
number, except for `verdict`, whose value is the outcome word and whose text is the display
word. `pairbench fill` puts the text into documents.

| Key | Figure |
|---|---|
| `<case>.<subject>_vs_<baseline>.ratio` | the median of the per-round ratios |
| `<case>.<subject>_vs_<baseline>.statistic` | the value the rule graded |
| `<case>.<subject>_vs_<baseline>.speedup` | how many times faster or better the subject is |
| `<case>.<subject>_vs_<baseline>.percent` | the ratio as a signed percent change |
| `<case>.<subject>_vs_<baseline>.p` | the uncorrected p-value |
| `<case>.<subject>_vs_<baseline>.p_corrected` | the corrected p-value |
| `<case>.<subject>_vs_<baseline>.bar` | the noise bar |
| `<case>.<subject>_vs_<baseline>.floor_subject` | the subject's floor |
| `<case>.<subject>_vs_<baseline>.floor_baseline` | the baseline's floor |
| `<case>.<subject>_vs_<baseline>.n` | the untied paired rounds |
| `<case>.<subject>_vs_<baseline>.verdict` | the verdict |
| `<case>.<side>.median` | a side's median on the case |
| `launch_cost.median`, `launch_cost.spread` | the cost of a launch and its interquartile range, in seconds |

A key under which two different figures would be written, for example because a name holds a
dot, is left out; a document that names it is refused when it is filled. A figure whose text
would be no finite number is left out the same way, such as a floor too large to write as a
percentage in a document written by hand. Rounding happens only when the text is formed.

The texts are the ones every report writes. A ratio has two decimals (`0.80x`), a percentage,
a bar or a floor one decimal (`-20.3%`, `±1.8%`), a p-value two significant digits and a median
three significant digits with its unit (`1.92 s`). A number far from 1 has the short form,
three significant digits and an exponent: a ratio of a million or more or below 0.01
(`2.5e+07x`, `0.0099x`), a percentage, bar or floor of a million percent or more (`+1e+08%`),
and a median below 0.0001 or of 10^15 or more (`1.23e-05 s`, `1.00e+300 s`). A p-value below
1e-300 is written as the bound `< 1e-300`: with more than about a thousand untied pairs its
float can be zero, while `p_raw_fraction` keeps the exact fraction.

## `diagnostics.json`

Schema `pairbench/diagnostics/v1`. Numbers in this example are made up.

```json
{"schema": "pairbench/diagnostics/v1",
 "run": {"id": ""},
 "holds_names": true,
 "instruments": [{"name": "counters", "side": "new", "status": "ok", "reason": null, "rc": 0},
                 {"name": "stacks", "side": "old", "status": "skipped",
                  "reason": "not_permitted", "rc": null}],
 "resources": [{"case": "res/cores", "subject": "new", "baseline": "old",
                "subject_median": 7.8, "baseline_median": 1.0, "outcome": "higher"}],
 "counters": [{"event": "instructions", "subject": "new", "baseline": "old",
               "subject_value": 1000, "baseline_value": 2000, "ratio": 0.5}],
 "stacks": [{"side": "new", "instrument": "stacks", "samples": 1234,
             "top_functions": [{"name": "", "object": "", "share": 0.25}],
             "top_objects": [{"name": "", "share": 0.5}]}],
 "objects": {"only_in": {"new": [], "old": []}, "differ": [{"name": "", "new": "", "old": ""}]},
 "findings": [{"id": "cores_used",
               "text": "new used 7.8 cores against 1.0 for old (median of 20 rounds).",
               "evidence": {"case": "res/cores", "subject_median": 7.8,
                            "baseline_median": 1.0, "n_rounds": 20}}],
 "files": {"folded": [], "folded_diff": [], "flame": [], "flame_diff": []},
 "name_map": {}}
```

- `instruments[].status` is `ok`, `skipped` or `failed`; `reason` is one of `not_installed`,
  `not_permitted`, `not_in_image`, `no_capability`, `launcher_cannot`, `side_changed`,
  `lock`, `launch_failed`, `interpreter_too_old`, or null.
- A finding is a sentence made by code from a fixed template, with the numbers it was made
  from. See [diagnostics](../method/diagnostics.md#what-a-finding-says-and-what-it-does-not).
- `name_map` maps a real name to the file name used for it, where the real name is unsafe in
  a file name.
