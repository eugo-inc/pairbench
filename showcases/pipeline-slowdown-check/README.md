# A slowdown check in a pipeline

Two revisions of a small example library, the same image and the same benchmark tests. The run
exits with code 1 when a primary case of the new revision is `SLOWER` than the old one (the
outcome `worse`, which the config names in `rule.fail_on`), so a pipeline step that runs it
fails on a slowdown and passes on `TIE`, `FASTER` and `UNRESOLVED`.

| Side | Image | Library |
|---|---|---|
| `a` (baseline) | `python:3.13-slim` | [`revisions/a`](revisions/a/examplelib/__init__.py) |
| `b` | `python:3.13-slim` | [`revisions/b`](revisions/b/examplelib/__init__.py) |

Revision b changes one function: `dedupe` keeps the items it has seen in a list instead of a
set, so each membership test walks the list. That is the kind of change this check is for.
Whether it reads as `SLOWER` on your machine is what the run decides; no result is published
here yet.

The image is pinned by digest in [`sides.lock`](sides.lock) and
[`pairbench.toml`](pairbench.toml); pytest 9.2.0 and pytest-benchmark 5.3.1 are pinned in
[`run.sh`](run.sh).

## Run it

```sh
./run.sh
echo "exit code: $?"
```

You need pairbench and Docker. The first run installs pytest and pytest-benchmark into
`.deps/` in this folder, once; every launch then mounts this folder read-only at
`/showcase`. Options after `./run.sh` go to `pairbench run`.

## What it measures

[`tests/test_examplelib.py`](tests/test_examplelib.py) has two benchmarks, read by the
[`pytest-benchmark`](../../docs/guides/pytest-benchmark.md) driver. Each case is the median of
the benchmark's own rounds within one launch; pairbench then pairs the launches round by
round.

The positive control runs the tests with `PAIRBENCH_WORK_FACTOR=2`
(`controls.positive_via = "factor"`), so each benchmarked call does its work twice; it checks
that this reads about twice the time.

## In a pipeline

[`example-workflow.yml`](example-workflow.yml) is an example GitHub Actions workflow. It checks
out the base and the head of a pull request side by side, points side `a` at the base and side
`b` at the head, and runs the check with `--fail-on worse`. The exit codes are in
[exit codes](../../docs/reference/exit-codes.md): 0 when the run completed and no primary case
matched `--fail-on`, 1 when one did, and other codes when the run could not be made.

A shared runner is a noisy machine. The twins measure that noise in the same run, so a noisy
run reads `UNRESOLVED` rather than `SLOWER`; failing only on `worse` keeps the step from failing
on noise. Add `unresolved` to `--fail-on` only on a machine quiet enough to decide.

## Expected result

[`expected/`](expected/) holds no result yet. A result is published only after a real run has
been approved, with the class of machine that produced it.
