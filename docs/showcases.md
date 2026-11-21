---
description: "Seven worked comparisons with configs, scripts and pinned images: pip against conda, a noisy neighbour, a pipeline gate, Python versions, servers and more."
---

# Showcases: complete comparisons you can run

Seven complete comparisons you can run with one command each live in the
[`showcases/`](../showcases) folder of the
repository. Each one holds:

- a `README.md` that says what is compared, how to run it and what to look at;
- a `pairbench.toml` with the experiment;
- a `run.sh` that runs it with one command, including any one-time preparation such as
  installing a package into a folder the sides mount; a container it starts itself, for that
  preparation or beside the run, gets `--memory-swap` at the value of its `--memory`, so it
  has no swap beyond its memory limit;
- a `sides.lock` with the digest of every image;
- the workload files, which honour `PAIRBENCH_WORK_FACTOR` (see
  [positive control](method/positive-control.md));
- `expected/`, which holds only a `README.md` with one line saying that no approved result
  exists yet: no showcase holds a result.

Every image is public and pinned by digest. Read the licence of each image and model before
you publish a result made with it.

| # | Showcase | Sides | Driver |
|---|---|---|---|
| 1 | [NumPy from pip against NumPy from conda](../showcases/numpy-pip-vs-conda) | `python:3.13-slim` with NumPy from pip; `condaforge/miniforge3` with NumPy from conda-forge | [`lines`](guides/lines.md) |
| 2 | [A noisy neighbour](../showcases/noisy-neighbour) | `python:3.13-slim` against itself, once quiet and once beside a second container running a busy loop | [`wall`](guides/wall.md) |
| 3 | [A slowdown check in a pipeline](../showcases/pipeline-slowdown-check) | two revisions of a small example library on `python:3.13-slim`, with `--fail-on worse` and an example GitHub Actions workflow | [`pytest-benchmark`](guides/pytest-benchmark.md) |
| 4 | [Two Python versions](../showcases/python-versions) | `python:3.13-slim` and `python:3.14-slim` | [`lines`](guides/lines.md) |
| 5 | [Two versions of an inference server](../showcases/inference-server-versions) | two release tags of the vLLM OpenAI-compatible server image, a small model under the Apache-2.0 licence | [`guidellm`](guides/guidellm.md) |
| 6 | [A GPU kernel](../showcases/gpu-kernel) | two tags of the public CUDA development image, with NVBench built inside each | [`nvbench`](guides/nvbench.md) |
| 7 | [A vendor container against a pip install](../showcases/vendor-container-vs-pip) | NVIDIA's public PyTorch container; `python:3.13-slim` with PyTorch from pip | [`lines`](guides/lines.md) |

Showcases 5, 6 and 7 need an NVIDIA GPU. Showcase 7 ships its recipe only: the commands, the
config and the shape of its output, with no numbers from a run. No approved result exists yet.

## What each one shows

1. **Packaging.** The same NumPy release on the same Python minor version, built and packaged
   two ways. Each operation gets its own verdict, corrected together.
2. **A shared machine.** Two identical sides should never get `FASTER` or `SLOWER`. Beside a
   busy neighbour the noise floor widens and the verdict stays `TIE` or `UNRESOLVED`. See
   [shared machines](method/shared-machines.md).
3. **A pipeline gate.** The exit code is 1 when the new revision is `SLOWER`; noise reads as
   `UNRESOLVED` and passes. See [exit codes](reference/exit-codes.md).
4. **Interpreters.** One standard-library workload on two Python versions.
5. **Serving.** Time to first token, token rate and tokens per joule at three load levels, with
   the server's start-up phases. See [first-token definitions](method/first-token-definitions.md)
   and [energy per token](method/energy-per-token.md).
6. **Toolkits.** The same CUDA source built with two toolkit releases, timed by NVBench.
7. **Vendor builds.** A vendor's framework container against the same framework from pip, with
   the TF32 settings made the same on both sides.

## Results

No `expected/` folder holds a result; each holds only the one line above. A reader of a
published showcase whose sidecar was kept private cannot recompute its hashes; the showcase's
public recipe, its `pairbench.toml`, `run.sh` and `sides.lock`, says what each side ran.
Diagnostics, flame graphs and report pages of a showcase follow the stricter rule in
[diagnostics](method/diagnostics.md).
