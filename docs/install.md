---
description: "Install pairbench with pip on Linux or macOS with Python 3.11 or newer; optional extras add charts, the tool server, GPU readings and load tools."
---

# Install pairbench

Install it with `pip install pairbench`; it needs Python 3.11 or newer and runs on Linux and
macOS.

```
pip install pairbench
```

The core imports only the Python standard library. Optional extras add what some features
need:

| Extra | Adds | For |
|---|---|---|
| `plot` | matplotlib | the charts of a run |
| `mcp` | the MCP Python SDK | `pairbench mcp`, the tool server for AI agents |
| `gpu` | `nvidia-ml-py` | reading GPU power and state through the management library |
| `llm` | GuideLLM, AIPerf | load tools for serving sides |
| `micro` | pytest-benchmark | the `pytest-benchmark` driver's tool |

```
pip install "pairbench[plot,mcp]"
```

## External programs

pairbench launches other programs only when a run needs them, and only if you installed them
yourself:

- **Docker or Podman** for image and serving sides.
- **`perf`** for the `perf` driver and for counters and sampled stacks in the explain step.
- **`nvidia-smi`** for GPU state and power, when the `gpu` extra is not installed.
- **Nsight Systems or Nsight Compute** for `pairbench profile --tool nsys|ncu`.
- The benchmark tools its drivers read: see the [guides](guides/index.md).

None of them is bundled, downloaded or redistributed. See the
[licence notes](licence.md).

## Check the install

```
pairbench --version
pairbench doctor
pairbench selftest
```

`pairbench doctor` says what this machine supports: the external programs found, the
container engine, which instruments of the explain step can run, whether the plot extra is
installed, and anything degraded. It always exits 0; add `--json` for a document.

`pairbench selftest` runs the known answers and controls of the statistics on synthetic data
and exits 1 if any fails. `pairbench selftest --live` adds a tiny real run with two command
sides.
