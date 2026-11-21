---
description: "GPU power sampled during the load phase, integrated over the window and divided into output tokens; what is measured, what is excluded, when no value is given."
---

# How is energy per token measured?

pairbench samples GPU power during the load phase of each serving launch, integrates it over
the window, and divides the output tokens the load tool reports by that energy; the value
covers the GPUs only.

## What is measured

During the load phase of a launch, a sampler thread reads GPU power every
`energy.interval_s` seconds (0.2 by default). The source is the GPU management library
through the `gpu` extra when it is installed, and otherwise one long-running `nvidia-smi`
query process; both are read the same way.

- **Energy** is the trapezoid integral of power over the sample times within the load
  window. Samples of 10, 20 and 30 W at 0, 0.5 and 1.0 s integrate to 20 J.
- Where the GPU exposes a cumulative energy counter, its difference over the window is
  recorded beside the integral, when the window holds at least `energy.min_samples`
  distinct readings of it. A disagreement above 5 percent is a loud note.
- With several selected GPUs, energy is summed.
- **Idle power**, the mean over a short window before the first launch, is recorded for the
  GPUs each side selects, one window for each selection. It is never subtracted.
- Temperature and throttle reasons from the same source are recorded as witnesses for the
  [machine checks](shared-machines.md).

## The cases

| Case | Unit | Better | Kind |
|---|---|---|---|
| `energy_j[gpu]` | J | lower | other |
| `mean_power_w[gpu]` | W | lower | other |
| `tokens_per_joule[gpu]` | tokens/J | higher | efficiency |

`tokens_per_joule[gpu]` is the output tokens the load driver reports for the window divided
by the energy over the same window. In a serving launch every load level has its own window,
so the cases exist per level, for example `c32/tokens_per_joule[gpu]`. At the highest level
it is a default primary case when present.

## What is excluded

The scope is part of the case id: `[gpu]`. Report columns read "GPU-only power". The results
carry `energy.scope = "gpu"` and
`energy.excludes = ["cpu", "memory", "storage", "cooling", "power supply losses"]`.

On a system where the GPU shares a package with the CPU, the reading still covers only what
the GPU reports, and the label does not change. Energy per token from pairbench is therefore
not the energy a request costs at the wall socket. It is comparable between two sides
measured on the same GPU in the same run, which is what a verdict needs.

## When no value is given

A value is not produced when the sampler is not healthy (fewer than two power samples, or
any query error) or when the window holds fewer than `energy.min_samples` power samples (10
by default). The case is then missing for that launch, and the report says why. A value is
never estimated from one sample. A missing value in a round makes that round unpaired for
the case; it is never filled in.

A short load level at the default interval may hold too few samples. Lengthen the level
(`--level-duration`) or shorten the interval (`energy.interval_s`) rather than lowering the
minimum.
