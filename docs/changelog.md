---
description: "What each release of pairbench added and changed, newest first."
---

# Changelog

This page lists what each release of pairbench added and changed, newest first.

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
