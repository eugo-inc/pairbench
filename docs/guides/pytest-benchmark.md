---
description: "The pytest-benchmark driver runs your benchmark tests once per side per round and compares the median of each test's timings."
---

# Compare pytest-benchmark results

Pass `--driver pytest-benchmark` and run your benchmark tests as the workload: pairbench reads
pytest-benchmark's JSON output and compares the median of each test's timings.

Format read from the tool's own documentation and source at version 5.3.1
([source](https://github.com/ionelmc/pytest-benchmark/tree/v5.3.1), `stats.py` and
`session.py`), and checked against the output of a real run of pytest-benchmark 5.3.1 under
pytest 9.2.0.

## What it adds to the command

`--benchmark-json=<file>`. A command that already names `--benchmark-json` is refused.

## What it reads

One case per entry of `benchmarks[]`, named by the test's full name (`fullname`), in seconds.
A test named after a file by its absolute path gives a case id with that path cut to its last
part (`test_read[/made/up/data.csv]` gives `test_read[data.csv]`), as every driver's case ids
are. The path runs on over the words after it up to the last that holds a `/`, as
[the shown command reads it](../reference/config.md#what-the-shared-files-hide)
(`test_read[/made/up/in.csv fast mode/x]` is cut to `test_read[x]` and shows with a mark, such
as `test_read[x] +3c5e7a91`), and its secrets are hidden as
in every driver's case ids (`test_db[token:made-up]` gives `test_db[token:<hidden>]`). Two tests
whose cut drops a word without a `/`, such as that one and
`test_read[/made/up/in.csv slow mode/x]`, end with a mark, a space, `+` and eight hex digits the
run makes with its own key from the words of the id that hold no `/`, as `test_read[x] +3c5e7a91`
and `test_read[x] +b04d2f68`, and keep that mark in every launch and on every side of the run.
Two ids of one launch that differ only in their folders, such as `test_read[/made/up/a/in.csv]`
and `test_read[/made/up/b/in.csv]`, are refused with `E_USAGE`, and so are two that differ only in
a hidden secret, such as `test_db[token:made-up]` and `test_db[token:made-up-2]`, and two that
differ only in their folders and a hidden secret. An id whose folders or secret alone differ from
one side or launch to the next names one case, and the run pairs it with itself. The value is:

- when `stats.data` holds the time of each round, the value is the median of those times;
- otherwise, as in a file saved without the data of each round, the value is the tool's own
  `stats.median`, with the reducer `tool_summary`.

Every test is a primary case by default. The version is the file's top-level `version`.

## Example

```
pairbench run --side new=venv:.venv-new --side old=venv:.venv-old \
  --driver pytest-benchmark --fail-on worse -- python -m pytest benchmarks/ -q
```

A workload that starts with `python` runs with each side's own interpreter. `--fail-on worse`
makes the exit code 1 when any primary case comes out worse: a check for slowdowns in an
automated pipeline. See the [pipeline showcase](../showcases.md).

pytest-benchmark's own `--benchmark-compare` compares saved runs; pairbench does not use it.
It launches the tests once per side per round and compares the rounds itself.

Tool documentation: [pytest-benchmark](https://pytest-benchmark.readthedocs.io/).
