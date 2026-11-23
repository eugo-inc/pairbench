---
description: "What each release of pairbench added and changed, newest first."
---

# Changelog

This page lists what each release of pairbench added and changed, newest first.

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
