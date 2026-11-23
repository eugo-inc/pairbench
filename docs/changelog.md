---
description: "What each release of pairbench added and changed, newest first."
---

# Changelog

This page lists what each release of pairbench added and changed, newest first.

## 0.2.1

A fix to what the terminal shows of a text read from an input.

- **Lines on standard error**: a refusal, a note, a machine check that did not pass and a line
  of the command's own write a line or paragraph separator (U+2028, U+2029), a character that
  changes the order the text around it shows in (U+061C, U+200E, U+200F, U+202A to U+202E,
  U+2066 to U+2069) and a lone surrogate as an escape such as `\uNNNN`, as they write a
  control character, so a name read from an input stays on its line, shows in its own order
  and always prints. A backslash is written as `\\`, so each printed line stands for one text
  only: the typed text `\x1b` prints as `\\x1b`, and an escape character as `\x1b`. A name
  that a message quotes keeps the escapes of its quoting, and their backslashes then show
  doubled: a side named `a\b` is quoted as `'a\\b'` and shows as `'a\\\\b'`, and an escape
  character in a quoted name shows as `\\x1b`. `results.json` keeps every message as it is,
  and the tool server gives the refusal of a run it started as the refusal holds it. The
  [exit-codes page](reference/exit-codes.md#text-codes) says how a message is escaped.
- **Plan text**: `pairbench plan`, and the text the tool server's plan tool answers, escape
  every line in the same way, the header and the table alike. The numbers of
  the plan and `plan.tsv` keep each name as it is.
- **Terminal report**: a line or paragraph separator, a character that changes the order of
  the text and a lone surrogate show as `?`, as a control character does.
- **Plug-ins and the self-test**: the line of a plug-in that failed to load and the detail of
  a failed self-test control are escaped as the lines on standard error are. The text of
  `pairbench doctor` prints the failed plug-in line escaped, and its `--json` output keeps the
  text as it is.
- **Changelog check**: the test that every change to the text codes is named in the changelog
  refuses a newest entry that holds directive syntax, a line that starts with two colons or a
  colon before a letter on a line with a code span, which the documentation site would drop
  with what it holds. The set of text codes is that of 0.2.0.

## 0.2.0

A lenient mode of the text reader, the pool checks on their own, and text codes that stay
stable.

- **Lenient text reader**: `pairbench compare --lenient`, and
  `pairbench.load_capture(path, reader="text", strict=False)` and `load_captures` from Python,
  read a value that is not a finite number as a missing cell instead of a malformed row. The
  new note `value_not_finite`, one per missing cell, names the side, the round and the case;
  the capture's records and the results carry it, the analysis goes on and the round counts
  in `n_unpaired`. A round that gives a side two positions is read with its order not
  recorded, with the new note `order_contradicted`, so the cases that use it get
  `NO VERDICT (order_not_recorded)`. The strict mode stays the default and reads as in 0.1.1.
  See
  [lenient reading](reference/text-format.md#lenient-reading).
- **Pool checks on their own**: `pairbench.check_pool(captures)` runs the checks that pooling
  captures in one analysis makes, with the same code as `analyse`, and returns every refusal
  they find instead of raising the first. See
  [checking a pool](reference/python-api.md#checking-a-pool).
- **Stable text codes**: the
  [exit-codes page](reference/exit-codes.md#stability-of-the-text-codes) gives the scope of
  every text code and says when a code may be added, renamed or removed. The set of text codes
  is that of 0.1.1.

## 0.1.1

A fix to what a results file shows of a command.

- **Shown command**: a local address (`file:` and `scheme:///` forms) and a climbing relative
  path (`../`, `./../`, `data/../../`) in the query or the fragment of an address are cut as
  they are after a host, whatever stands before them, so their folders and the hosts and
  credentials around them are hidden in the shown command, in `sh -c` texts and in `--opt=`
  values. A path that ends at a home folder after a `=` shows `<hidden>`. The
  [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists what still shows.
- **Case ids** are read as in 0.1.0. The names of `hyperfine` cases come from their commands,
  so a command with such a path can name its case differently in 0.1.1: pooling a capture of
  0.1.0 with one of 0.1.1 is then refused with `E_POOL_CASES`, and a `cases.groups` pattern
  written for the 0.1.0 name may miss the 0.1.1 name.
- **Publishing**: the release is built again from its tag before the upload, which goes ahead
  only when the attached files are the files that build makes.

## 0.1.0

The first release.

- **Comparing sides**: container images, commands, Python interpreters, virtual
  environments, conda environments, inference servers and result files of other tools, each
  identified before and after the run.
- **Method**: paired rounds in a rotating and reversing order with checked balance; twins
  that measure the noise floor of each side in the same run; the exact sign test; Holm's
  correction over the primary cases; the `strict` rule; a positive control in every round;
  the measured cost of a launch.
- **Machine checks**: a quiet check that can wait, CPU pinning with one type of core, a
  census of other containers, advisory locks, witnesses during every launch, and disturbed
  rounds that can only downgrade a verdict.
- **Drivers**: `wall`, `lines`, `gbench`, `nvbench`, `pytest-benchmark`,
  `hyperfine`, `perf`, `llama-bench`, `guidellm`, `aiperf` and `vllm-bench` (experimental).
- **Energy**: GPU power sampling and energy per token, labelled as GPU-only.
- **Diagnostics**: resource figures for every launch, an explain step with counters and
  sampled stacks, and interactive flame graphs written by the package itself.
- **Outputs**: `results.json`, meant to be shared, with the known limits the
  [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists; terminal,
  Markdown and HTML reports, charts with the `plot` extra, and `pairbench fill` for figures
  in documents.
- **For AI agents**: `llms.txt`, an agent skill, and a tool server with the `mcp` extra.
- **Python API** and a plug-in API with seven groups.
