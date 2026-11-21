# A noisy neighbour

One image, `python:3.13-slim`, compared against itself, twice: once on a quiet machine, and
once beside a second container of the same image that runs a busy loop. Both sides are the
same, so the right answer is that there is no difference. The showcase shows what pairbench
does when the machine is shared: the noise floor widens, and no false verdict appears.

| Side | Image |
|---|---|
| `first` (baseline) | `python:3.13-slim` |
| `second` | `python:3.13-slim` |
| the neighbour (not a side) | `python:3.13-slim`, running [`neighbour.py`](neighbour.py) |

The image is pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml). Two sides with the same image need
`launch.allow_identical = true`, which the config sets and the results record.

## Run it

```sh
./run.sh
```

You need pairbench and Docker. Each call of the script makes a new folder
`pairbench-runs/<UTC time>-<process id>`, so it can be run again and again. It runs the
experiment into that folder's `quiet`, starts the neighbour, runs it again into its `noisy`,
names the folder at the end, and removes the neighbour when it ends, also on an interrupt.
`PAIRBENCH_NEIGHBOUR_LOOPS=4 ./run.sh` gives the neighbour four busy loops instead of one. Options after `./run.sh` go to both runs of `pairbench run`.

## What it measures

[`spin.py`](spin.py) does a fixed amount of pure-Python arithmetic, and the
[`wall`](../../docs/guides/wall.md) driver times each launch from outside: the start of the
container, the interpreter and the loop.

## What to look at

- **The floor.** Compare `floor_subject` and `floor_baseline` of the two runs, or the floor
  lines of the two reports. Beside the neighbour, the twins disagree more and the floors are
  wider.
- **The verdict.** Between two identical sides it should be `TIE` or `UNRESOLVED` in both
  runs. A `FASTER` or `SLOWER` here would be a false verdict.
- **The machine checks.** In the noisy run, the census reports the neighbour container, and
  the witnesses during each launch see its load. Under the default `warn` mode the run goes
  on and the results say the machine was busy. `./run.sh --gates enforce` refuses the noisy
  run instead.
- **Pinning.** `./run.sh --cpus 2-3` pins every launch. The neighbour is not pinned, so it may
  share those CPUs; the busy-core witness then cannot see load of others on the pinned CPUs
  themselves. See [shared machines](../../docs/method/shared-machines.md).

## Expected result

[`expected/`](expected/) holds no result yet.
