# NumPy from pip against NumPy from conda

The same NumPy release, 2.5.4, on the same Python minor version, 3.13, installed two ways:

| Side | Image | NumPy from |
|---|---|---|
| `pip` (baseline) | `python:3.13-slim` | PyPI, with `pip install --target` |
| `conda` | `condaforge/miniforge3:26.9.4-2` | conda-forge, with `conda create` |

Both images are pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml).

## Run it

```sh
./run.sh
```

You need pairbench and Docker. The first run installs NumPy for each side into `.deps/` in
this folder, once; every launch then mounts this folder read-only at `/showcase`. Options
after `./run.sh` go to `pairbench run`, for example `./run.sh --cpus 2-5` to pin every
launch to those CPUs, or `./run.sh --print-plan` to see the plan without running.

## What it measures

[`bench.py`](bench.py) times eight operations and prints one
[`lines`](../../docs/guides/lines.md) case for each. Each value is the median of seven timed
calls after one untimed call; the clock covers the operation alone. The operations run on one
thread on both sides (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` are 1),
so the comparison is of the builds, not of how each picks a thread count. Remove those
variables from `[launch]` to compare with the default threading of each build.

The operations are the kinds named on the NumPy board of the public page
<https://eugo.io/benchmarks>. Only their names and sizes were taken. The workload is written
for this showcase, and no number from that page is used here.

| Case | Operation, as recorded from the page |
|---|---|
| `rfft_2m` | Real FFT, 2M points |
| `cholesky_1024` | Cholesky factorization, 1024 x 1024 |
| `arcsinh` | arcsinh, elementwise |
| `axpy` | axpy, a memory-bound vector update |
| `fft2_1024` | 2D FFT, 1024 x 1024 |
| `sqrt_mul_add` | sqrt, multiply, add: a chained elementwise expression |
| `exp` | exp, elementwise |
| `matmul_512` | Matrix multiplication, 512 x 512 |

The elementwise operations, which have no size on the page, use 4,194,304 (2^22) values.

## What to look at

- Each case gets its own verdict, and all eight are corrected together as primary cases.
- The positive control runs `bench.py` with `PAIRBENCH_WORK_FACTOR=2`
  (`controls.positive_via = "factor"`), so each timed call runs its operation twice; it checks
  that this reads about twice the time.
- The noise floor of each side comes from its twin in the same rounds.
- The identify command prints `numpy.show_config()` for each side, so the BLAS and LAPACK
  libraries each build uses are recorded with the run.
- The two sides differ in more than NumPy: the base image, the Python build and the libraries
  NumPy links to. A verdict says the whole side differs, not which part made the difference.

## Expected result

[`expected/`](expected/) holds no result yet.
