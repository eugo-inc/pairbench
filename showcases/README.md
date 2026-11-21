# Showcases

Seven complete experiments. Each folder holds a `README.md`, a `pairbench.toml`, a `run.sh`
that runs it with one command, a `sides.lock` with the image digests, the workload files, and
`expected/`. Every image is public and pinned by digest. Every workload honours
`PAIRBENCH_WORK_FACTOR`. A container a `run.sh` starts itself, outside pairbench, gets
`--memory-swap` at the value of its `--memory`, so it has no swap beyond its memory limit.

No showcase has an approved result yet; each `expected/` folder says so in one line.

A run meant to be published is made with `PAIRBENCH_SHOWCASE_PUBLISH` set to a folder inside
the showcase, from the checkout reached at `/work`, for example
`PAIRBENCH_SHOWCASE_PUBLISH=published /work/showcases/python-versions/run.sh`. The run sees
`HOME=/home/user` and writes into a new folder under `pairbench-runs/`, which stays private.
`tools/hash_inputs.py` then writes `hash_inputs.json` there and copies `results.json`,
`results.md` and `report.html` into the published folder, and the sidecar with them only when
the shared files show every value the sidecar holds; otherwise the sidecar stays owner-only in
the private folder, one line on standard error says so, and `run.sh` exits with the run's own
code. The results hide each side's command, which the sidecar holds, so a showcase's sidecar
stays private and its three result files are published without it. A reader of a published
showcase whose sidecar was kept private cannot recompute its hashes; the showcase's public
recipe, its `pairbench.toml`, `run.sh` and `sides.lock`, says what each side ran. `run.sh`
refuses the variable when the showcase is reached elsewhere, and a value that names no folder
inside the showcase to publish into, or that reaches, through a link, the showcase itself, a
folder that holds it or `pairbench-runs`, each with its own line on standard error.

| # | Showcase | Sides | Driver |
|---|---|---|---|
| 1 | [NumPy from pip against NumPy from conda](numpy-pip-vs-conda/README.md) | `python:3.13-slim` with pip; `condaforge/miniforge3` with conda | `lines` |
| 2 | [A noisy neighbour](noisy-neighbour/README.md) | `python:3.13-slim` against itself, quiet and beside a busy loop | `wall` |
| 3 | [A slowdown check in a pipeline](pipeline-slowdown-check/README.md) | two revisions of a small library on `python:3.13-slim` | `pytest-benchmark` |
| 4 | [Two Python versions](python-versions/README.md) | `python:3.13-slim` and `python:3.14-slim` | `lines` |
| 5 | [Two versions of an inference server](inference-server-versions/README.md) | two release tags of `vllm/vllm-openai`, a small Apache-2.0 model | `guidellm` |
| 6 | [A GPU kernel](gpu-kernel/README.md) | two tags of `nvidia/cuda` development images, NVBench built inside | `nvbench` |
| 7 | [A vendor container against a pip install](vendor-container-vs-pip/README.md) | `nvcr.io/nvidia/pytorch`; `python:3.13-slim` with PyTorch from pip | `lines` |

Showcases 5, 6 and 7 need an NVIDIA GPU.
