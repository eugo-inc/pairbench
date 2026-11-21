# A GPU kernel

The same CUDA source, built with two releases of the CUDA toolkit, each inside its own public
development image, and timed with NVBench:

| Side | Image |
|---|---|
| `cuda1343` (baseline) | `nvidia/cuda:13.4.3-devel-ubuntu24.04` |
| `cuda1350` | `nvidia/cuda:13.5.0-devel-ubuntu24.04` |

Both images are pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml). [`build.sh`](build.sh) pins the NVBench commit and the
CMake release it builds with, and checks the SHA-256 of the CMake download.

The [`nvbench`](../../docs/guides/nvbench.md) driver reads NVBench's JSON output. Its test
fixture is the output of one run of this showcase's `kernel_bench`, built by `build.sh`
inside the `cuda1343` image. In it, the description of the device, each state's mean SM clock
rate and each state's share of the peak memory bandwidth are made up; the GPU and CPU times,
the item rate, the global-memory bandwidth in bytes per second and the clock scaling are kept
as measured.

## Run it

```sh
./run.sh
```

You need pairbench, Docker with GPU support and one NVIDIA GPU. The first run builds
`kernel_bench` once inside each image, with that image's own toolkit, into `.build/` in this
folder; the build downloads CMake, NVBench and NVBench's dependencies. Every launch then mounts
this folder read-only at `/showcase` and runs the binary built for its side on GPU 0. Options
after `./run.sh` go to `pairbench run`.

## What it measures

[`kernel_bench.cu`](kernel_bench.cu) holds two NVBench benchmarks, each at two sizes, 2^24 and
2^26 elements:

- `saxpy`: a hand-written kernel, `y = a * x + y`, so the difference between the sides is the
  code the compiler makes of it;
- `cub_sum`: a sum with CUB's device-wide reduction, so the difference includes the library
  shipped with each toolkit.

Each case is NVBench's own mean GPU time for one state, for example
`saxpy/Device=0 Elements=2^26`. NVBench repeats each measurement until its own stopping rule is
met, and pairbench then pairs the launches round by round.

## What to look at

- The identify command records `nvcc --version` for each side.
- Both sides run on the same GPU and the same driver; only the toolkit, its compiler and its
  libraries differ.
- GPU clocks change with temperature and load. The positive control runs the binary with
  `PAIRBENCH_WORK_FACTOR=2` (`controls.positive_via = "factor"`), so each benchmark processes
  twice the elements; it checks that this reads about twice the time on this GPU in this run.

## Expected result

[`expected/`](expected/) holds no result yet.
