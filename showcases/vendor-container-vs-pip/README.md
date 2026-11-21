# A vendor container against a pip install

A vendor's public framework container against an official Python image with the framework
installed from pip:

| Side | Image | PyTorch |
|---|---|---|
| `pip` (baseline) | `python:3.13-slim` | `torch==2.15.0` from PyPI |
| `vendor` | `nvcr.io/nvidia/pytorch:26.10-py3` | 2.15.0a0+875d815, as the image's `PYTORCH_VERSION` variable names it |

Both images are pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml). This showcase ships its recipe only: the commands, the
config and the shape of the output, with no numbers from a run. No approved result exists yet.
Read the licence of the vendor container before you publish a result made with it.

## Run it

From this folder:

```sh
pairbench plan --config pairbench.toml
./run.sh
pairbench report pairbench-runs/<run>/results.json
```

1. `pairbench plan` prints the lineup, the number of rounds and launches and the balance of
   every pair. It launches nothing and pulls nothing.
2. `./run.sh` runs the experiment. You need pairbench, Docker with GPU support and one NVIDIA
   GPU. The first run installs PyTorch from PyPI for the pip side into `.deps/` in this folder,
   once; it is several gigabytes. Every launch then mounts this folder read-only at
   `/showcase` and runs on GPU 0. Options after `./run.sh` go to `pairbench run`. The run
   folder is `pairbench-runs/<time>-<id>/` in this folder.
3. `pairbench report` prints the report of a finished run again; `--format markdown` prints it
   as a Markdown table.

## What it measures

[`bench.py`](bench.py) times six operations on the GPU and prints one
[`lines`](../../docs/guides/lines.md) case for each: float32 and bfloat16 matrix products of
4096 x 4096, a 3x3 convolution, a softmax, a layer norm and a GELU. The GPU is synchronised
before each reading of the clock. Each value is the median of seven timed calls after three
untimed calls. The positive control runs `bench.py` with `PAIRBENCH_WORK_FACTOR=2`
(`controls.positive_via = "factor"`), so each timed call runs its operation twice.

## What to look at

- **The same TF32 settings on both sides.** The vendor image sets
  `TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1` in its environment. The config sets it to `0` on both
  sides, and `bench.py` turns TF32 off for matrix products and convolutions, so both sides
  run the float32 cases with the same settings. Remove the variable from `[launch]` to
  compare the images as shipped, and say so with the result.
- **The sides differ in more than PyTorch**: the Python version, the CUDA libraries, cuDNN and
  the base system. The identify command records the Python, PyTorch, CUDA and cuDNN versions
  of each side.
- **No explain step.** `explain.mode` is `off`, so a run makes only its measured rounds. See
  [diagnostics](../../docs/method/diagnostics.md) for what the explain step adds, and
  [an image that holds perf](../../docs/guides/perf-in-an-image.md) for what its counters and
  stacks need inside an image.
- The vendor image prints a banner when it starts. The `lines` driver reads only lines that
  start with `::pairbench::`, so the banner does not reach the values.

## Expected shape of the output

The report a run prints has this shape. Every `<...>` stands for a value the run fills in;
this showcase publishes none.

```
vendor against pip (baseline)

case              vendor  pip     change    noise    p    verdict
matmul_fp32_4096  <time>  <time>  <change>  <noise>  <p>*  <verdict>
matmul_bf16_4096  <time>  <time>  <change>  <noise>  <p>*  <verdict>
conv2d_3x3_64ch   <time>  <time>  <change>  <noise>  <p>*  <verdict>
softmax_8192      <time>  <time>  <change>  <noise>  <p>*  <verdict>
layernorm_1024    <time>  <time>  <change>  <noise>  <p>*  <verdict>
gelu              <time>  <time>  <change>  <noise>  <p>*  <verdict>

Exact two-sided sign test over <rounds> paired rounds.
* corrected for testing 6 cases at once.
Rule: strict.
Machine state: <state>.
Baseline: pip.
Positive control pip~twice: <state of the control>.
Values read by driver lines.
```

- One row per case, in the order `bench.py` prints them. `<time>` is the side's median time,
  with its unit.
- `<change>` is the median of the per-round ratios, written as "x faster" or "x slower";
  `<noise>` is the bar the gap had to exceed, a percentage after `±`.
- `<p>` is the exact sign test's p-value, corrected for testing the six cases together.
- `<verdict>` is `FASTER`, `SLOWER`, `TIE`, `UNRESOLVED` or `NO VERDICT`; see
  [verdicts](../../docs/method/verdicts.md).
- `<rounds>` is the round count the plan prints. `<state>` is the machine state after the
  machine checks. `<state of the control>` is `ok`, or the cases on which the positive control
  failed, in which case every comparison of the run is `NO VERDICT`.
- A line for each degraded machine check, or for rounds set aside as disturbed, can appear
  between the positive control and the driver line.

The run folder holds:

- `capture.jsonl`: the raw record of every launch.
- `results.json`: the analysed document.
- `results.md`: the report as Markdown.
- `plan.tsv`: the schedule of the run.
- `report.html`: the report page.
- `artifacts/`: what each launch printed.
- `charts/`: the charts, when the `plot` extra is installed.

There is no `diagnostics.json` and no `profiles/` folder, because the explain step is off.

## Expected result

[`expected/`](expected/) holds no result yet. A result is published only after a real run has
been approved, with the class of machine that produced it.
