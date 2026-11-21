---
description: "The lines driver reads values the workload prints itself, to time the work alone without the start of the process or to compare any number it computes."
---

# Compare values your workload prints

Print one `::pairbench::` line per value from the workload and pass `--driver lines`: each line
becomes a case. Use it to time the work alone, without the start of the process, or to compare
any number the workload computes.

## The line

The workload prints one line per case on standard output:

```
::pairbench:: {"case": "name", "value": 1.23, "unit": "s", "better": "lower"}
```

The line starts with `::pairbench::`; the rest is one JSON object.

| Key | Required | Default | Meaning |
|---|---|---|---|
| `case` | yes | | the case name |
| `value` | yes | | a finite number |
| `unit` | no | `s` | the unit; a unit of time makes the case's kind `time` |
| `better` | no | `lower` | `lower`, `higher`, or `none` for a case that describes and does not judge |

Every other line of the output is ignored.

A launch is refused as unreadable (`E_LAUNCH_FAILED`) when it prints no such line at all, a
line whose JSON does not parse or is no object, a key other than the four above, the same
case twice, or a value that is not a finite number. A misspelt key is refused rather than
ignored, because a misspelt `better` would turn a verdict around.

## Example

<!-- example -->
```python
import json
import os
import time

factor = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
start = time.perf_counter()
for _ in range(factor):
    total = sum(i * i for i in range(2_000_000))
elapsed = time.perf_counter() - start
print("::pairbench::", json.dumps({"case": "squares", "value": elapsed}))
```

```
pairbench run --side new=python:python3.14 --side old=python:python3.13 --driver lines -- python bench.py
```

The loop over `PAIRBENCH_WORK_FACTOR` lets the
[positive control](../method/positive-control.md) ask the workload to double its work with
`controls.positive_via = "factor"`.

## Cases

Every printed case, all primary by default, except cases whose `better` is `none`, which are
always secondary. Choose others with `cases.primary`. When no case is primary, a loud note
(`no_case_primary`) says so as soon as the cases are known: the run tests no case, and no
`--fail-on` outcome can match.

For a file side, the driver reads each file as the standard output of one launch.
