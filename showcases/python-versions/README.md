# Two Python versions

Two official Python images, one workload that uses only the standard library:

| Side | Image |
|---|---|
| `py313` (baseline) | `python:3.13-slim` |
| `py314` | `python:3.14-slim` |

Both images are pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml).

## Run it

```sh
./run.sh
```

You need pairbench and Docker. Every launch mounts this folder read-only at `/showcase`.
Options after `./run.sh` go to `pairbench run`, for example `./run.sh --cpus 2-3`.

## What it measures

[`bench.py`](bench.py) runs eight pure-Python tasks and prints one
[`lines`](../../docs/guides/lines.md) case for each: recursion, building and reading a
dictionary, joining and splitting text, a JSON round trip, a regular-expression scan, sorting
tuples, a floating-point loop, and making many small objects. Each value is the median of
seven timed calls after one untimed call, so the start of the interpreter is outside the
values.

## What to look at

- Each task gets its own verdict, and all eight are corrected together as primary cases.
- The positive control runs `bench.py` with `PAIRBENCH_WORK_FACTOR=2`
  (`controls.positive_via = "factor"`), so each timed call runs its task twice; it checks that
  this reads about twice the time.
- The identify command records `sys.version` and the build options of each interpreter.
- The images differ in more than the interpreter: the base system and its libraries can differ
  too. A verdict says the whole side differs.
- To include the start of the interpreter, time the whole launch with the
  [`wall`](../../docs/guides/wall.md) driver instead: `./run.sh --driver wall`.

## Expected result

[`expected/`](expected/) holds no result yet.
