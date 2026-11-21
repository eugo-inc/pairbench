---
description: "pairbench is Apache-2.0; the programs, images, models and profilers it runs keep their own licences, and so do your results."
---

# Which licences apply to pairbench and what it runs?

pairbench is licensed under the Apache License 2.0; the programs, images, models and profilers
it runs keep their own licences. The licence text is in
[`LICENSE`](../LICENSE) and the notice in
[`NOTICE`](../NOTICE).

Every source file starts with:

```
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
```

## Programs pairbench launches

pairbench launches other programs only when a run needs them and only when you installed them
yourself. It does not bundle, download or redistribute any of them. Each is listed in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)
as "invoked as an external program, not bundled", with its licence and source: the container
engines, `perf`, `nvidia-smi`, the GPU profilers, and the benchmark and load tools the drivers
read.

The optional extras (`plot`, `mcp`, `gpu`, `llm`, `micro`) are installed by your package
manager from their own projects, under their own licences, and are not bundled either.

Fixtures in the repository are synthetic, or come from a real run of a public tool on a public
image; each has a provenance file next to it that says how it was made.

## The documentation site

The documentation site is built with Astro and Starlight. Its pages carry the scripts and
styles of Astro, Starlight, Expressive Code and Pagefind, and Pagefind's highlighter carries
mark.js, each under the MIT licence. [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)
lists each with its version and source. None of it is in the Python package.

## Images and models

The showcases name public images pinned by digest and, for serving, an openly licensed model.
pairbench does not redistribute them. Read the licence of each image and model before you
publish results made with it.

## Profilers

pairbench can call a profiler if you have installed it yourself: a GPU profiler, or `perf` for
counters and sampled stacks. It does not include, download or redistribute one. Your use of a
profiler, and what you may publish from its output, is governed by the licence you accepted
with it. Read it before publishing results. Its output holds names from your code. The
showcases here publish no output of a GPU profiler.

## Your results

The results of a run are yours. `results.json` and `results.md` are made to be shared and hold
no host name, user name or environment value, except an image reference you ask for and the
forms that the [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists as
known limits of the shown command. The command they show hides the secret forms that
[what the shared files hide](reference/config.md#what-the-shared-files-hide) lists, but a
short plain value that nothing on that list names, such as one given after an option of one
letter, as a plain argument or in the path of an address, is shown: give a side a secret
through the environment with `env_pass`. The capture, what each launch printed in
`artifacts/`, the diagnostics, the profiles and the report page hold more: names from your code
and details of your machine. Read them before you share them.
