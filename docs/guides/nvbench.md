---
description: "The nvbench driver reads the mean GPU time of each state from NVBench's JSON output, checked against a real run."
---

# Compare NVBench GPU kernel times

Pass `--driver nvbench` and run your NVBench program as the workload: pairbench reads its JSON
output and compares the mean GPU time of each state.

Format read from the tool's own source at commit `0f8eb2dd715f` (project version 0.1.0, JSON
file version 1.0.0): `nvbench/json_printer.cu`, `nvbench/detail/measure_cold.cu`,
`nvbench/state.cxx` and `docs/cli_help.md`
([source](https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/nvbench/json_printer.cu)),
and checked against the output of a real run of NVBench at that commit on one NVIDIA GPU.

## What it adds to the command

`--json <file>`. A command that already names `--json` is refused.

## What it reads

`benchmarks[].states[]`. A state's case is named by the benchmark's `name` and the state's
`name` (its axis values, for example `Device=0 Elements=2^20`), joined by `/`.

| Case | Value | Metric | Primary |
|---|---|---|---|
| `<benchmark>/<state>` | the summary tagged `nv/cold/time/gpu/mean`, its `data` entry `value`, in seconds | `gpu_time` | yes |
| `<case>/cpu_time` | the summary tagged `nv/cold/time/cpu/mean`, when present | `cpu_time` | no |

- Both are the tool's own means (`tool_summary`); the count of inner samples is the summary
  tagged `nv/cold/sample_size`, or 1.
- A state the tool skipped is a missing case and is named in a note. A state that was not
  skipped and has no GPU-time mean is refused.
- The version is `meta.version.nvbench.string`.

## Example

```
pairbench run --side new=image:REGISTRY/kernels:new --side old=image:REGISTRY/kernels:old \
  --gpus 0 --driver nvbench -- /bench/my_kernels
```

`--gpus` selects the GPUs a container side may use. The quiet check then also requires that
no other compute process runs on them, and the witnesses record GPU throttle events.

Tool documentation: [NVBench](https://github.com/NVIDIA/nvbench).
