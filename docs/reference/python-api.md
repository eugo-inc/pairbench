---
description: "The Python API: plan, run, analyse, render, fill and the other functions, building sides, rows produced elsewhere, rules and the statistics primitives."
---

# Use pairbench from Python

Everything the command line does is available from Python. `import pairbench` imports no
sub-package; the public names load on first use.

## Functions

```python
def plan(experiment: Experiment) -> Plan
def run(experiment: Experiment, *, out: Path | None = None) -> Capture
def analyse(captures: Capture | Sequence[Capture], *, rule: str | Rule = "strict",
            baseline: str | None = None, floors: Floors | None = None,
            allow_incomplete: bool = False, allow_mixed_machines: bool = False,
            assume_interleaved: bool = False) -> Results
def load_capture(path: Path | str, *, reader: str | None = None) -> list[Capture]
def load_results(path: Path | str) -> Results
def load_diagnostics(path: Path | str) -> Diagnostics
def render(results: Results, fmt: Literal["terminal", "markdown", "json", "html"], *,
           diagnostics: Diagnostics | None = None, folder: Path | None = None) -> str
def explain(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics
def draw(results: Results, *, out: Path, diagnostics: Diagnostics | None = None) -> list[Path]
def fill(template: str | Path, results: Results | Mapping[str, Results]) -> str
```

- `plan` lays out the order of every launch and launches nothing.
- `run` runs an experiment and returns its capture.
- `analyse` analyses one capture, or pools several of the same experiment. Refusals are
  raised as `pairbench.errors.Refusal`, which carries the text code and the exit code.
- `load_capture` reads the captures in a file, one per run it holds, with the reader named or
  the one that recognises the file.
- `render` renders a results document. With `diagnostics`, the terminal and markdown reports
  add the findings and the page adds the diagnostics; with `folder`, the page embeds the
  chart and flame-graph files found there.
- `explain` runs the [explain step](../method/diagnostics.md) and writes its files under
  `out`.
- `draw` draws the charts into `out` and returns their paths; without the `plot` extra it
  returns an empty list.
- `fill` reads `template` as a file when it is a `Path` and as the template text when it is a
  `str`.

## Sides

```python
from pairbench import Side, Ready

Side.parse("new=image:myorg/app:2.0")
Side.image(name, ref, *, args=(), env=None, entrypoint=None)
Side.command(name, argv)
Side.python(name, *, interpreter=None, venv=None, conda=None)
Side.serve(name, image, args, *, ready=Ready(http="/health", timeout_s=900))
Side.files(name, paths, *, format)
```

## Rows produced elsewhere

<!-- example -->
```python
from pairbench import Capture, analyse

rows = [
    (1, "new", "matmul", 1.92),
    (1, "old", "matmul", 2.41),
    (2, "old", "matmul", 2.39),
    (2, "new", "matmul", 1.91),
]
capture = Capture.from_rows(
    rows,
    sides=["new", "old"],
    positions={(1, "new"): 1, (1, "old"): 2, (2, "old"): 1, (2, "new"): 2},
)
results = analyse(capture, baseline="old")
```

<!-- example -->
```python
>>> (comparison,) = results.comparisons
>>> comparison.outcome, comparison.reason, comparison.reasons
('no_verdict', 'too_few_rounds', ('too_few_rounds', 'no_floor'))
```

The values above are made up. `Capture.from_rows(rows, *, sides, twins=None, positions=None,
cases=None, unit="s")` takes rows of `(round, side, case, value)`. A round is any whole number,
a label that pairs the rows of a round; the capture numbers its rounds 1, 2, 3 and on in the
order of the labels, and an `E_GRID` refusal names a round by its label. `twins` maps a twin's name to its side. `positions` maps
`(round, side)` to the position it ran in; without it the capture is marked "order not
recorded" and every comparison gets `NO VERDICT (order_not_recorded)`. `cases` takes the
`Case` records of the rows' cases, which say which cases are primary and their unit and
direction; without it every case is primary and lower-is-better, in the unit `unit` names.

Two rounds are too few for a verdict, so this example gives `NO VERDICT (too_few_rounds)`. Its
`reasons` also list `no_floor`: without twins there is no noise floor, and with enough rounds
that alone gives `NO VERDICT (no_floor)`. Supply twins, or noise floors measured elsewhere:

<!-- example -->
```python
from pairbench import Floors

results = analyse(capture, baseline="old", floors=Floors(0.012))  # 1.2 percent, both sides
results = analyse(capture, baseline="old", floors=Floors({"new": 0.01, "old": 0.008}))
```

A floor is in the unit of the rule's scale: a fraction under scale `ratio`, percent under
scale `percent`. Results produced this way say `"floor": {"source": "supplied"}` and the report
footer says so. A supplied floor too large to write as a percentage is no floor, as a measured
one would be: the side has no floor and every case that uses it gets
`NO VERDICT (too_far_apart)`. The command line does not expose supplied floors.

## Rules

<!-- example -->
```python
from pairbench import Rule

lenient = Rule(
    "lenient",
    scale="ratio",
    floor_scope="case",
    bar="twice_larger",
    bar_round_digits=None,
    require_both_floors=True,
    p_source="corrected",
    alpha=0.05,
    p_inclusive=False,
    gap_inclusive=False,
    tie="inside_and_not_significant",
    min_rounds=None,
)
results = analyse(capture, baseline="old", rule=lenient, floors=Floors(0.01))
```

The fields are described in [verdicts](../method/verdicts.md#other-rules). The results record
every field of the rule used.

## Statistics primitives

<!-- example -->
```python
>>> from pairbench.stats import holm, min_rounds, sign_test
>>> sign_test(12, 0).p  # the exact two-sided p-value: 2/4096
0.00048828125
>>> holm([0.01, 0.04, 0.5])
[0.03, 0.08, 0.5]
>>> min_rounds(4, 0.05)
8
```

`paired(observations, a, b)` pairs the observations of two sides by capture and round.

## The data model

`Experiment`, `Side`, `Plan`, `Capture`, `Case`, `Comparison`, `Results`, `Diagnostics`,
`Rule` and the settings classes are frozen dataclasses. Each has a JSON form; the schemas are
printed by `pairbench schema capture|results|config|diagnostics`. See the
[results schema](results-schema.md).
