---
description: "Every public name of pairbench and pairbench.stats, and the plug-in contract of pairbench.api, with its signature and its docstring, written from the source."
---

# Every public Python name

Each public name of `pairbench` and `pairbench.stats`, the `Refusal` they raise and the plug-in
contract of `pairbench.api` is listed below with its signature and its docstring, read from the
source. [Use pairbench from Python](python-api.md) and [add a plug-in](plugin-api.md) show how
the names fit together.

This page is written by `tools/api_reference.py`; do not edit it by hand.

## <span id="pairbench"></span>Module `pairbench`

Every class of the data model is a frozen dataclass with a JSON form: `value.to_json()` gives
it, and the class method `from_json(data)` reads it back.

### <span id="pairbench.analyse"></span>`pairbench.analyse`

```python
def analyse(
    captures: Capture | Sequence[Capture],
    *,
    rule: str | Rule = 'strict',
    baseline: str | None = None,
    floors: Floors | None = None,
    allow_incomplete: bool = False,
    allow_mixed_machines: bool = False,
    assume_interleaved: bool = False,
) -> Results
```

Analyse one capture, or pool several captures of the same experiment.

`rule` is the name of a rule or a `Rule`. `baseline` names another
baseline than the recorded one. `floors` supplies noise floors measured
elsewhere. The three switches lift a refusal or a missing verdict and
stamp the results: `allow_incomplete` analyses the complete rounds of a
capture that has no end record, `allow_mixed_machines` pools captures
of different machines, `assume_interleaved` grades rows whose order was
not recorded.

A refused analysis raises `Refusal`, which carries as `results` the
results document of the refused analysis: no comparisons and the refusal
listed. Every note the analysis adds is also printed on standard error.

### <span id="pairbench.check_pool"></span>`pairbench.check_pool`

```python
def check_pool(
    captures: Sequence[Capture],
    *,
    allow_mixed_machines: bool = False,
) -> list[Refusal]
```

Run the checks that pooling `captures` in one analysis makes, and return what they refuse.

The checks and their refusals are those of `analyse`, which runs the
same code: the same capture, file or bytes given twice
(`E_POOL_SAME`), identical rows (`E_POOL_IDENTICAL_ROWS`), a truncated
copy (`E_POOL_TRUNCATED_COPY`), a capture of one side against its twins
pooled with a comparison (`E_POOL_MIXED_PURPOSE`), a side, workload,
setup or working folder that changed (`E_POOL_SIDE_DRIFT`), other cases
or units (`E_POOL_CASES`), another machine (`E_POOL_MACHINE`, not
listed with `allow_mixed_machines`) and names a run marked that cannot
be read alike (`E_USAGE`). Each is a `Refusal` with its text code,
exit code, scope, message and detail, returned, not raised, in the order
the analysis meets them. The first is the one `analyse` raises for the
captures in the same order when each is complete or incomplete captures
are allowed; `analyse` refuses an incomplete capture with
`E_CAPTURE_INCOMPLETE` once the first three checks pass. An empty list
says the captures pool. Nothing is printed. Completeness and the grid of
each capture are checked by `analyse` alone.

### <span id="pairbench.draw"></span>`pairbench.draw`

```python
def draw(
    results: Results,
    *,
    out: Path,
    diagnostics: Diagnostics | None = None,
    max_round_charts: int = 12,
    note: Notify | None = None,
) -> list[Path]
```

Draw the charts of a run into `out` and return their paths.

The charts are drawn from the results and, when given, the diagnostics
document, never from a capture. Without the `plot` extra nothing is
drawn and the list is empty. At most `max_round_charts` round-by-round
charts are drawn. Every loud note of the drawing, such as a missing
extra or charts that were left out, is printed on standard error and
handed to `note` as `(code, message)` when one is given.

### <span id="pairbench.explain"></span>`pairbench.explain`

```python
def explain(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics
```

Run the explain step for an analysed run and return the diagnostics document.

Each subject and the baseline is launched again under instruments,
untimed. `out` is the run folder: it receives `diagnostics.json` and
the files under `profiles/`. An instrument that cannot run is skipped
with a loud note; every note of the step is printed on standard error
and is in the document. A lock that cannot be taken skips every launch
of the step: the document then says so for each instrument and holds
one note. The step changes no comparison.

### <span id="pairbench.fill"></span>`pairbench.fill`

```python
def fill(template: str | Path, results: Results | Mapping[str, Results]) -> str
```

Fill the figure tokens of a document from results.

A `Path` is read as a file, its line endings kept as they are; a
`str` is the template text. One `Results` serves the tokens that
carry no results name. A mapping serves named tokens; its entry named by
the empty text serves the tokens without a name. Every missing figure is
refused, all of them listed.

### <span id="pairbench.load_capture"></span>`pairbench.load_capture`

```python
def load_capture(
    path: Path | str,
    *,
    reader: str | None = None,
    strict: bool = True,
) -> list[Capture]
```

Read the captures in a file: one per run it holds.

`reader` names a capture reader. Without it the readers are asked in
turn, built-ins first, whether the file is theirs; a file no reader
claims is refused.

`strict=False` reads the file with the lenient mode of the text
reader: a value that is no finite number is a missing cell, which the
capture notes as `value_not_finite`, one note per cell, and which
`analyse` leaves unpaired while it grades the rest; `refusals` stays
empty. A round whose order contradicts itself is read with its order not
recorded. A reader that has no lenient mode is refused with `E_USAGE`.

### <span id="pairbench.load_diagnostics"></span>`pairbench.load_diagnostics`

```python
def load_diagnostics(path: Path | str) -> Diagnostics
```

Read a diagnostics document from a file.

### <span id="pairbench.load_results"></span>`pairbench.load_results`

```python
def load_results(path: Path | str) -> Results
```

Read a results document from a file.

### <span id="pairbench.plan"></span>`pairbench.plan`

```python
def plan(experiment: Experiment) -> Plan
```

Lay out the order of every launch of an experiment.

Nothing is started, pulled, locked or written. The number of primary
cases is not known before a warm-up, so the plan is made for one.

### <span id="pairbench.render"></span>`pairbench.render`

```python
def render(
    results: Results,
    fmt: Literal['terminal', 'markdown', 'json', 'html'],
    *,
    diagnostics: Diagnostics | None = None,
    folder: Path | None = None,
    options: ReportOptions | None = None,
) -> str
```

Render a results document as a terminal report, markdown, JSON or the report page.

The function is given what it may show. With `diagnostics`, the
terminal and markdown reports add the findings and the page adds the
diagnostics. With `folder`, the page embeds the chart and flame-graph
files found there. Without either, every format is rendered from the
results alone. `options` filters what is displayed. It never changes
what was tested.

### <span id="pairbench.run"></span>`pairbench.run`

```python
def run(experiment: Experiment, *, out: Path | None = None) -> Capture
```

Run an experiment and return its capture.

`out` names the run folder itself; without it the folder is the one the
experiment's run settings name, or a new folder under `pairbench-runs`.
The folder receives the capture and the plan that was run. An experiment
whose sides are result files launches nothing and reads them.

A refusal after the capture was opened leaves the folder in place; the
raised `Refusal` then carries, as `results`, the results document of
the refused run.

### <span id="pairbench.Capture"></span>`pairbench.Capture`

```python
@dataclass(frozen=True)
class Capture:
    capture_id: str
    header: Header
    machine: MachineRecord | None = None
    sides: tuple[Side, ...] = ()
    gates: tuple[GateRecord, ...] = ()
    lineup: Lineup | None = None
    cases: tuple[Case, ...] = ()
    launches: tuple[Launch, ...] = ()
    observations: tuple[Observation, ...] = ()
    end: End | None = None
    notes: tuple[Note, ...] = ()
    source: Source | None = None
    launch_cost: LaunchCost | None = None
    case_key: str | None = None
    case_names: tuple[CaseName, ...] = ()
```

The raw record of one run.

`cases` holds every case: those of the lineup record and those recorded
later. `notes` are the loud notes of the run. `launch_cost` is the
measured cost of a launch, or `None` when none was measured. `source`
says where the capture was read from and is not part of its records.
`case_key` is the run's own key for the marks it adds to case names
(`CaseKeyRecord`), or `None` when no name needed one; `case_names`
holds the names the run gave to ids it cut or hid, from every
`case_names` record, in order.

The positive-control entry has a side record with the role `control`
and one launch per round at the position one past the lineup's length.
The explain launches are no part of a capture.

#### <span id="pairbench.Capture.complete"></span>`Capture.complete`

```python
@property
def complete(self) -> bool
```

Whether the capture has an end record that says the run completed.

#### <span id="pairbench.Capture.baseline"></span>`Capture.baseline`

```python
@property
def baseline(self) -> str | None
```

The name of the baseline side, or `None` when no side has that role.

#### <span id="pairbench.Capture.order_recorded"></span>`Capture.order_recorded`

```python
@property
def order_recorded(self) -> bool
```

Whether every round launch has a recorded position.

#### <span id="pairbench.Capture.control"></span>`Capture.control`

```python
@property
def control(self) -> Side | None
```

The positive-control entry: the side record whose role is `control`, or `None`.

The relation is the declared `control_of` field and is never told
from a name.

#### <span id="pairbench.Capture.control_settings"></span>`Capture.control_settings`

```python
def control_settings(self) -> ControlSettings
```

Return the settings of the positive control the recorded config holds.

A key the recorded config does not hold, or holds with a value that
is not valid, has its default. This is how an analysis learns the
tolerance and how the control doubled the work.

#### <span id="pairbench.Capture.launch_cost_share"></span>`Capture.launch_cost_share`

```python
def launch_cost_share(self) -> float
```

Return the recorded `launch_cost.note_share`, or its default.

#### <span id="pairbench.Capture.explain_launches"></span>`Capture.explain_launches`

```python
def explain_launches(self) -> int
```

Return the number of explain launches the run planned.

It follows from the recorded explain mode and the number of subjects
and baselines. A capture whose sides no run launched, one made from
rows or from result files, plans none.

#### <span id="pairbench.Capture.side"></span>`Capture.side`

```python
def side(self, name: str) -> Side
```

Return the side or twin with this name.

#### <span id="pairbench.Capture.round_launches"></span>`Capture.round_launches`

```python
def round_launches(self) -> tuple[Launch, ...]
```

Return the launches of the measured rounds, without the warm-ups.

#### <span id="pairbench.Capture.ref"></span>`Capture.ref`

```python
def ref(self) -> CaptureRef
```

Return the entry a results document lists for this capture.

`sha256` is the hash of the capture file, when the capture was read
from one or written to one. `rounds` is the number of completed
rounds the end record states, or the number of rounds that have a
launch when there is no end record.

#### <span id="pairbench.Capture.driver_info"></span>`Capture.driver_info`

```python
def driver_info(self) -> DriverInfo | None
```

Return the driver and the tool versions a results document shows, or `None`.

The driver is the one the recorded config names. A driver that a
plug-in provides is not named.

#### <span id="pairbench.Capture.side_drivers"></span>`Capture.side_drivers`

```python
def side_drivers(self) -> dict[str, str | None]
```

Return the name of the driver that read each side, as the run chose it.

A result file side that names its own `format` is read by that
driver; every other side by the driver the recorded config names.
`None` when neither is recorded. A plug-in's name is kept here, in
the private record; a results document never shows it.

#### <span id="pairbench.Capture.side_driver_info"></span>`Capture.side_driver_info`

```python
def side_driver_info(self, name: str) -> DriverInfo | None
```

Return the driver that read side `name` and the tool versions its launches recorded.

A driver that a plug-in provides is not named. `None` when neither
the driver nor a version is known.

#### <span id="pairbench.Capture.driver_notes"></span>`Capture.driver_notes`

```python
def driver_notes(self) -> tuple[Note, ...]
```

Return the loud note of compared sides that different drivers read, or nothing.

Each driver reads what its own tool measured, and two tools can define
the same figure differently, such as the time to a first token. A
ratio between such sides compares the tools as well as the sides. The
sides compared are the subjects and the baseline.

#### <span id="pairbench.Capture.round_observations"></span>`Capture.round_observations`

```python
def round_observations(self) -> tuple[Observation, ...]
```

Return the observations of the measured rounds, without those of the warm-ups.

#### <span id="pairbench.Capture.env_pad"></span>`Capture.env_pad`

```python
def env_pad(self) -> EnvPad
```

Return what a results document records about the size of the environment.

The size was varied when a launch of a round carries a pad length.

#### <span id="pairbench.Capture.set_aside"></span>`Capture.set_aside`

```python
def set_aside(self) -> SetAside | None
```

Return the decision on disturbed rounds, from the recorded thresholds and witnesses.

`None` when the capture records no thresholds.

#### <span id="pairbench.Capture.undecided_launches"></span>`Capture.undecided_launches`

```python
def undecided_launches(self) -> int
```

Return how many launches of the measured rounds the witnesses could not judge.

A launch is undecided when a witness that holds the launch's own load
is above its threshold (see `undecided`). It is 0 when the capture
records no thresholds.

#### <span id="pairbench.Capture.with_twins"></span>`Capture.with_twins`

```python
def with_twins(self, twins: Mapping[str, str]) -> Capture
```

Return a copy in which the named lineup entries are twins of other sides.

`twins` maps a twin's name to its side, as in `from_rows`. It is
how the caller of `load_capture` declares a twin relation that the
file itself does not state. A twin gets the kind, spec, identity and
fingerprint of its side. A name that is no entry of the capture, a
side that is itself a twin or a control, and the baseline or the
control named as a twin are refused. A twin whose side is absent is
refused with `E_TWIN_ORPHAN`, as in `from_rows`.

#### <span id="pairbench.Capture.to_records"></span>`Capture.to_records`

```python
def to_records(self) -> list[dict[str, Any]]
```

Return the records of the capture, one plain dict per line of `capture.jsonl`.

The order is: header, machine, sides, gates, lineup, later cases, the
key for the marks of case names and the names that carry one, each
launch followed by its observations, notes, end. The cost of a launch, when one was
measured, follows the warm-up launches.

#### <span id="pairbench.Capture.from_records"></span>`Capture.from_records`

```python
@classmethod
def from_records(
    cls,
    records: Iterable[Mapping[str, Any]],
    *,
    source: Source | None = None,
) -> Capture
```

Build a capture from its records, in any order. A missing header is refused.

#### <span id="pairbench.Capture.from_rows"></span>`Capture.from_rows`

```python
@classmethod
def from_rows(
    cls,
    rows: Iterable[tuple[int, str, str, float]],
    *,
    sides: Sequence[str | Side],
    twins: Mapping[str, str] | None = None,
    positions: Mapping[tuple[int, str], int] | None = None,
    cases: Sequence[Case] | None = None,
    unit: str = 's',
) -> Capture
```

Build a capture from rows of `(round, side, case, value)` produced elsewhere.

`sides` names the sides in lineup order; the last is the baseline
unless a `Side` given here says otherwise. `twins` maps a twin's
name to its side; a twin whose side is absent is refused with
`E_TWIN_ORPHAN`. `positions` maps `(round, side)` to the position
it ran in; a launch without one has no recorded order, and the capture
then says its order was not recorded.

`cases` takes the `Case` records of the rows' cases and so says
which cases are primary and what their unit and direction are; a row
that names a case they do not hold is refused. Without `cases`
every case is primary and lower-is-better, in the unit that `unit`
names, and of kind `time` when that is a unit of time. A value of
zero or less is kept; an analysis gives its case no verdict.

A round is any whole number: round numbers are labels that pair the
rows of a round. The capture numbers its rounds 1, 2, 3 and on in the
order of the labels (`round_numbers`), so rows labelled from 3 give
the capture rows labelled from 1 give, and a label no row holds is no
round. `positions` is keyed by the labels as given. When the labels
are not 1, 2, 3 and on, the capture's `source` keeps them, so that a
refusal names a round by the label the rows gave it.

### <span id="pairbench.Case"></span>`pairbench.Case`

```python
@dataclass(frozen=True)
class Case:
    id: str
    metric: str
    unit: str
    better: Better = 'lower'
    kind: CaseKind = 'other'
    primary: bool = True
    group: str | None = None
```

One named measurement a launch produces.

`primary` and `group` are decided once, when the case is recorded, by
`CaseSettings.is_primary` and `CaseSettings.group_of`. An analysis
reads them from the recorded case and never from the config. A case
without a group belongs to the group of all cases that share its metric
and its role, primary or secondary.

A case whose `better` is `none` describes and does not judge. Its
outcomes name a direction, `higher` or `lower`, and it can never be
primary: making one that is primary is refused.

### <span id="pairbench.CaseSettings"></span>`pairbench.CaseSettings`

```python
@dataclass(frozen=True)
class CaseSettings:
    primary: tuple[str, ...] = ()
    groups: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
```

Which cases are primary and how cases are grouped for the noise floor.

`primary` is a list of glob patterns; empty means the driver's own
default. `groups` maps a group name to glob patterns. A pattern matches
as `case_matches` says.

#### <span id="pairbench.CaseSettings.is_primary"></span>`CaseSettings.is_primary`

```python
def is_primary(self, case: str, default: Iterable[str], *, better: str = 'lower') -> bool
```

Say whether a case counts toward the verdict.

With patterns in `primary`, a case is primary when it matches one of
them. Without, it is primary when the driver names it: `default` is
what `Driver.default_primary` returned.

A case whose `better` is `none` is never primary. A pattern that
matches it among other cases leaves it secondary, and so does the
driver's own list, which may name every case a workload prints. A
pattern of the config that is equal to its id, with or without the
mark a run adds to it (`case_suffix`), asks for it outright: that is
refused, because nothing the user asked for is left out silently.

#### <span id="pairbench.CaseSettings.group_of"></span>`CaseSettings.group_of`

```python
def group_of(self, case: str) -> str | None
```

Return the name of the first group whose patterns match the case, or `None`.

### <span id="pairbench.Comparison"></span>`pairbench.Comparison`

```python
@dataclass(frozen=True)
class Comparison:
    case: str
    primary: bool
    subject: str
    baseline: str
    n_rounds: int
    n_unpaired: int
    n_untied: int
    n_lower: int
    n_higher: int
    subject_median: float | None
    baseline_median: float | None
    ratio: float | None
    statistic: float | None = field(default=None, kw_only=True)
    scale: Scale = field(default='ratio', kw_only=True)
    gap: float | None
    floor: FloorPair
    bar: float | None
    p_raw: float | None
    p_raw_fraction: tuple[int, int] | None
    p_corrected: float | None
    verdict: Verdict
    outcome: Outcome
    reason: Reason | None
    reasons: tuple[Reason, ...] = field(default=(), kw_only=True)
    order_split: tuple[int, int]
    sensitivity: Sensitivity = field(default_factory=Sensitivity)
```

One case compared between a subject and the baseline.

`ratio` is the median of the per-round ratios of subject over baseline,
under every scale. `statistic` is the signed value the rule graded: the
median of the per-round ratios under scale `ratio`, the median of the
per-round percent differences under scale `percent`. `scale` is the
rule's scale. `gap` is the absolute distance the rule compared with
`bar`; both are in the unit `floor.unit` names.

`reason` is the single main reason; `reasons` holds every reason that
applies. `p_raw_fraction` is the p-value as an exact fraction.
`order_split` counts how often the subject and the baseline ran first.

### <span id="pairbench.ControlSettings"></span>`pairbench.ControlSettings`

```python
@dataclass(frozen=True)
class ControlSettings:
    positive: ControlMode | None = None
    positive_tolerance: float = 0.1
    positive_via: ControlVia = 'repeat'
```

The positive control: the baseline started once with the workload run twice in it.

`positive` is `"on"`, `"off"` or `None` for the default: on,
except for an experiment of serving sides. `positive_tolerance` is how
far the control may read from its expected value, as a fraction of it.
It lies below `CONTROL_TOLERANCE_BELOW`: from there on a control that
reads no difference at all would lie within the tolerance.
`positive_via` says how the control doubles the work: `repeat` runs
the workload twice in one start, `factor` runs it once with the
variable that asks the workload for twice the work.

### <span id="pairbench.Diagnostics"></span>`pairbench.Diagnostics`

```python
@dataclass(frozen=True)
class Diagnostics:
    run: DiagnosticsRun
    holds_names: bool = True
    instruments: tuple[InstrumentRun, ...] = ()
    resources: tuple[ResourceRow, ...] = ()
    counters: tuple[CounterRow, ...] = ()
    stacks: tuple[StackSummary, ...] = ()
    objects: ObjectDiff = field(default_factory=ObjectDiff)
    findings: tuple[Finding, ...] = ()
    files: DiagnosticsFiles = field(default_factory=DiagnosticsFiles)
    name_map: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[Note, ...] = ()
    schema: Literal['pairbench/diagnostics/v1'] = SCHEMA_DIAGNOSTICS
```

What the resource figures, the counters and the sampled stacks say about two sides.

The document describes. It states no cause, changes no verdict and no
exit code. `holds_names` says the document holds names from the
user's code: function names, shared-object names and stacks live here,
in the files under `profiles/` and in the report page, and never in a
results document. `name_map` maps the real name of a case or a side to
the name it has in a file name. `schema` is the schema id; a document
that names another one is refused.

`notes` are the loud notes of the explain step: an instrument that
did not run, stacks of a subject and of the baseline that come from
different instruments. They are printed on standard error and copied
into the results of the run, so they name sides and instruments and
hold no name from the user's code.

#### <span id="pairbench.Diagnostics.to_json"></span>`Diagnostics.to_json`

```python
def to_json(self) -> dict[str, Any]
```

Return the diagnostics document as a plain dict, `schema` first.

#### <span id="pairbench.Diagnostics.state"></span>`Diagnostics.state`

```python
def state(self) -> DiagnosticsState
```

Return the state of the explain step that wrote this document.

`written` when at least one instrument ran on a side. Otherwise the
step is `skipped`: with the reason `lock` when every instrument
was skipped for a lock that could not be taken, and with
`no_instrument` when no instrument could run on any side.

#### <span id="pairbench.Diagnostics.stacks_of"></span>`Diagnostics.stacks_of`

```python
def stacks_of(self, side: str) -> StackSummary | None
```

Return the stack summary of a side, or `None` when it has none.

#### <span id="pairbench.Diagnostics.same_instrument"></span>`Diagnostics.same_instrument`

```python
def same_instrument(self, subject: str, baseline: str) -> bool
```

Say whether the stacks of a subject and of the baseline come from one instrument.

Only then is a difference file or a difference graph made.

#### <span id="pairbench.Diagnostics.shareable_findings"></span>`Diagnostics.shareable_findings`

```python
def shareable_findings(self) -> tuple[Finding, ...]
```

Return the findings made from resource figures and counters alone.

They hold no function name and no shared-object name, so a report
that may show no such name shows these.

### <span id="pairbench.EnergySettings"></span>`pairbench.EnergySettings`

```python
@dataclass(frozen=True)
class EnergySettings:
    enabled: bool = False
    interval_s: float = 0.2
    min_samples: int = 10
```

GPU power sampling.

A value is never made from one sample, so `min_samples` is at least 2.

### <span id="pairbench.Experiment"></span>`pairbench.Experiment`

```python
@dataclass(frozen=True)
class Experiment:
    sides: tuple[Side, ...]
    workload: tuple[str, ...] | None = None
    driver: str = 'wall'
    launch: LaunchSettings = field(default_factory=LaunchSettings)
    run: RunSettings = field(default_factory=RunSettings)
    gates: GateSettings = field(default_factory=GateSettings)
    rule: RuleSettings = field(default_factory=RuleSettings)
    cases: CaseSettings = field(default_factory=CaseSettings)
    energy: EnergySettings = field(default_factory=EnergySettings)
    report: ReportSettings = field(default_factory=ReportSettings)
    load: LoadSettings = field(default_factory=LoadSettings)
    controls: ControlSettings = field(default_factory=ControlSettings)
    launch_cost: LaunchCostSettings = field(default_factory=LaunchCostSettings)
    explain: ExplainSettings = field(default_factory=ExplainSettings)
    plots: PlotSettings = field(default_factory=PlotSettings)
```

One workload compared across sides.

`sides` are the user's sides, never twins. When no side has the role
`baseline` the last one becomes the baseline. `workload` is the shared
argument list, or `None`.

#### <span id="pairbench.Experiment.baseline"></span>`Experiment.baseline`

```python
@property
def baseline(self) -> str
```

The name of the baseline side.

#### <span id="pairbench.Experiment.subjects"></span>`Experiment.subjects`

```python
@property
def subjects(self) -> tuple[str, ...]
```

The names of the sides compared against the baseline.

#### <span id="pairbench.Experiment.is_serving"></span>`Experiment.is_serving`

```python
@property
def is_serving(self) -> bool
```

Whether the sides are serving sides.

#### <span id="pairbench.Experiment.side"></span>`Experiment.side`

```python
def side(self, name: str) -> Side
```

Return the side with this name.

#### <span id="pairbench.Experiment.twinned"></span>`Experiment.twinned`

```python
def twinned(self) -> tuple[str, ...]
```

Return the names of the sides that get a twin.

#### <span id="pairbench.Experiment.lineup"></span>`Experiment.lineup`

```python
def lineup(self) -> tuple[Side, ...]
```

Return the lineup: every side in the order given, each followed by its twin.

The positive control is not part of it: see `control`.

#### <span id="pairbench.Experiment.positive_control"></span>`Experiment.positive_control`

```python
@property
def positive_control(self) -> bool
```

Whether the positive control runs.

`controls.positive` decides when it is set. Left unset, the control
is on for an experiment with no serving side and off for a serving
experiment. Sides that are result files have no control, whatever the
setting says: nothing is launched for them.

#### <span id="pairbench.Experiment.control"></span>`Experiment.control`

```python
def control(self) -> Side | None
```

Return the positive-control entry, or `None` when the control does not run.

It is the baseline's control, named with the reserved suffix
`~twice`. It is no part of the lineup: it runs last in every round,
at the position one past the lineup's length, gets no warm-up launch
and no twin, and is never one of a compared pair.

#### <span id="pairbench.Experiment.explain_launches"></span>`Experiment.explain_launches`

```python
def explain_launches(self) -> int
```

Return the number of explain launches a plan of this experiment counts.

Each subject and the baseline is launched once per instrument; sides
that are result files are never launched.

#### <span id="pairbench.Experiment.to_json"></span>`Experiment.to_json`

```python
def to_json(self, *, redact: bool = True) -> dict[str, Any]
```

Return the resolved config, shaped like the config file.

Durations are numbers of seconds. A key whose value is unset is left
out. With `redact` the value of every credential-like environment
variable is replaced.

#### <span id="pairbench.Experiment.from_json"></span>`Experiment.from_json`

```python
@classmethod
def from_json(cls, data: Mapping[str, Any]) -> Experiment
```

Build an experiment from a config. An unknown key or a bad value is refused.

### <span id="pairbench.ExplainSettings"></span>`pairbench.ExplainSettings`

```python
@dataclass(frozen=True)
class ExplainSettings:
    mode: ExplainMode = 'always'
    sample_hz: int = 99
    call_graph: CallGraph = 'fp'
    top: int = 20
```

The explain step: untimed launches under instruments after the last round.

`mode` is `always`, `auto` (only when a primary case came out
better or worse) or `off`. `sample_hz` is the number of stack samples
per second, `call_graph` how call graphs are collected, and `top` how
many functions and shared objects are kept per side.

### <span id="pairbench.Floors"></span>`pairbench.Floors`

```python
@dataclass(frozen=True)
class Floors:
    value: float | Mapping[str, float]
```

Noise floors measured elsewhere: one value for all sides, or one per side name.

A value is in the unit of the scale of the rule it is analysed under: a
fraction under scale `ratio`, where 0.012 means 1.2 percent, and percent
under scale `percent`, where 1.2 means 1.2 percent.

#### <span id="pairbench.Floors.for_side"></span>`Floors.for_side`

```python
def for_side(self, name: str) -> float | None
```

Return the floor supplied for a side, or `None` when none was.

### <span id="pairbench.GateSettings"></span>`pairbench.GateSettings`

```python
@dataclass(frozen=True)
class GateSettings:
    mode: GateMode = 'warn'
    wait_quiet: bool = False
    locks: tuple[str, ...] = ()
    lock_timeout_s: float = 1800.0
    allow_mixed_core_types: bool = False
    quiet: QuietSettings = field(default_factory=QuietSettings)
    census: CensusSettings = field(default_factory=CensusSettings)
    discard: DiscardThresholds = field(default_factory=DiscardThresholds)
    stop_file: str | None = None
    min_gpu_free_mib: float | None = None
    check_locks: tuple[str, ...] = ()
```

Machine-check settings.

`stop_file`, `min_gpu_free_mib` and `check_locks` turn on the
readiness checks; each is off while unset. A path that holds a NUL
character, an empty entry of `check_locks` and a path that both
`check_locks` and `locks` name are refused: the run holds a lock of
`locks` itself in the re-check. Two paths name the same lock when they
are the same text once repeated slashes and `.` parts are folded; no
file is read, and a `..` part is kept, as a link before it changes the
file the path names.

#### <span id="pairbench.GateSettings.readiness"></span>`GateSettings.readiness`

```python
@property
def readiness(self) -> tuple[str, ...]
```

The names of the readiness checks that are on, in the order they run.

### <span id="pairbench.Launch"></span>`pairbench.Launch`

```python
@dataclass(frozen=True)
class Launch:
    seq: int
    phase: Phase
    round: int
    pos: int | None
    name: str
    rc: int = 0
    timing: Mapping[str, float] = field(default_factory=dict)
    witness: Mapping[str, Any] = field(default_factory=dict)
    energy: Mapping[str, Any] | None = None
    tool_version: str | None = None
    runs: int = 1
    env_pad: int | None = None
    timed_out: bool = False
```

One launch. A warm-up has round 0. `pos` is `None` when the order was not recorded.

`timing` holds `run_s` and `launch_s` where the side reports them.
`witness` is the JSON form of `Witness` and may hold more keys.

`runs` is how many runs of the workload the launch held: 2 for a launch
of the positive control that runs the workload twice in one start, and 1
for every other launch, the control under `factor` included. Its
timing is one interval around all its runs. `env_pad` is the length of
the environment pad of the launch, in bytes, and `None` when the
environment size is not varied. `timed_out` is true when the launch ran
into its time limit, `launch.timeout`, for every kind of side, the load
of a serving side included; `rc` is then what the side reported for the
stopped launch.

### <span id="pairbench.LaunchCostSettings"></span>`pairbench.LaunchCostSettings`

```python
@dataclass(frozen=True)
class LaunchCostSettings:
    launches: int = 20
    note_share: float = 0.01
```

The measurement of what a launch costs before the workload does anything.

`launches` empty launches are timed during warm-up; 0 turns the
measurement off. `note_share` is the share of a `wall` value above
which the launch-cost note is given.

### <span id="pairbench.LaunchSettings"></span>`pairbench.LaunchSettings`

```python
@dataclass(frozen=True)
class LaunchSettings:
    cpus: str | None = None
    gpus: str | None = None
    memory: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    env_pass: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()
    workdir: str | None = None
    network: str | None = None
    timeout_s: float | None = None
    engine: Engine = 'auto'
    pull: PullPolicy = 'missing'
    identify: tuple[str, ...] = ()
    perf_counters: bool = field(default=False, kw_only=True)
    allow_identical: bool = False
    overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
```

Launch settings shared by every side, with each side's overrides.

`overrides` maps a side name to the fields that side overrides. `env`
is a table and merges per variable: the side's variables are laid over the
shared ones, and the shared variables it does not name still apply. Every
other field is replaced whole. `env_pass` names variables forwarded to
the side whose values are never recorded. `identify` is an argument list
run once inside each side; an empty list means none. `perf_counters`
gives a container the capability to use performance counters and no
other capability; on a command side and on a Python environment side it
changes nothing.

#### <span id="pairbench.LaunchSettings.for_side"></span>`LaunchSettings.for_side`

```python
def for_side(self, side: Side) -> LaunchSettings
```

Return the settings in effect for a side, overrides merged in.

A twin gets the settings of the side its `twin_of` field names, and
the positive control those of the baseline its `control_of` field
names.

#### <span id="pairbench.LaunchSettings.differences"></span>`LaunchSettings.differences`

```python
def differences(self) -> dict[str, tuple[str, ...]]
```

Return, per side, the fields in which it differs from the shared settings.

#### <span id="pairbench.LaunchSettings.effective"></span>`LaunchSettings.effective`

```python
def effective(
    self,
    *,
    args: Sequence[str] = (),
    entrypoint: str | None = None,
    env: Mapping[str, str] | None = None,
    mounts: Sequence[str] = (),
) -> dict[str, Any]
```

Return the part of the settings that goes into a side's fingerprint.

Call it on the settings already merged for the side. `args`,
`entrypoint` and `env` are the side's own; `mounts` are the
mounts its kind adds, such as a server's model location, after the
configured ones. What a launch adds to
the environment for one round or one entry, the environment pad and
the work factor of the positive control, is no part of it: a twin's
fingerprint equals its side's with the environment size varied and
without.

### <span id="pairbench.LoadSettings"></span>`pairbench.LoadSettings`

```python
@dataclass(frozen=True)
class LoadSettings:
    levels: tuple[int, ...] = ()
    level_duration_s: float | None = None
    level_kind: LevelKind = 'concurrency'
```

The serving load: the levels, what a level counts, and the length of each.

`level_kind` is `concurrency`, a number of concurrent requests, or
`rate`, a number of requests per second. A level is a whole number of
at least 1.

#### <span id="pairbench.LoadSettings.label"></span>`LoadSettings.label`

```python
def label(self, level: int) -> str
```

Return the label of one level: `c32` or `r32`.

#### <span id="pairbench.LoadSettings.labels"></span>`LoadSettings.labels`

```python
def labels(self) -> tuple[str, ...]
```

Return the labels of the levels, in the order the levels run.

#### <span id="pairbench.LoadSettings.highest"></span>`LoadSettings.highest`

```python
def highest(self) -> str | None
```

Return the label of the highest level, or `None` when there are no levels.

### <span id="pairbench.Observation"></span>`pairbench.Observation`

```python
@dataclass(frozen=True)
class Observation:
    seq: int
    round: int
    pos: int | None
    name: str
    case: str
    value: float
    n_inner: int = 1
    reducer: str = 'identity'
    suite: str | None = None
```

One value of one case from one launch; `seq` names the launch.

`value` is a finite number; it may be zero or less, which an analysis
grades as no verdict. `suite` is the suite a row of the text input
format names. It is kept and changes neither the case id nor the floor
group.

### <span id="pairbench.Plan"></span>`pairbench.Plan`

```python
@dataclass(frozen=True)
class Plan:
    rows: tuple[PlanRow, ...]
    rounds_requested: int | None
    rounds_planned: int
    lineup: tuple[str, ...]
    balance: tuple[PairBalance, ...]
    launches: int
    estimate_s: float | None = None
    explain_launches: int = 0
    control: str | None = None
```

The order of every launch of a run.

`balance` holds, per compared pair, the order counts over `rows`.
`rounds_requested` is `None` when the count was left to the tool.
`launches` counts the warm-up launches and the launches of every round,
one per round for the positive control: `planned_launches`.
`explain_launches` counts the explain launches on their own:
`planned_explain_launches`. `control` names the positive-control
entry, or is `None`. The control is no part of `lineup`; its rows sit
at the position one past the lineup's length, and the balance, the
balanced step and every round count are the same with it and without.

#### <span id="pairbench.Plan.is_balanced"></span>`Plan.is_balanced`

```python
def is_balanced(self) -> bool
```

Say whether the planned rows are balanced, by counting over them.

Balanced means: every lineup entry occupies every position equally
often; in every compared pair each runs first equally often; and the
signed difference of positions of every compared pair sums to zero.

#### <span id="pairbench.Plan.balanced_step"></span>`Plan.balanced_step`

```python
def balanced_step(self) -> int
```

Return the smallest round count that is balanced for this lineup, found by search.

#### <span id="pairbench.Plan.to_tsv"></span>`Plan.to_tsv`

```python
def to_tsv(self) -> str
```

Return the plan table: tab-separated, with the columns round pos name side twin_of.

### <span id="pairbench.PlanRow"></span>`pairbench.PlanRow`

```python
@dataclass(frozen=True)
class PlanRow:
    round: int
    pos: int
    name: str
    side: str
    twin_of: str | None = None
```

One launch of the plan. `pos` is 1-based. `side` is the side a twin copies.

### <span id="pairbench.PlotSettings"></span>`pairbench.PlotSettings`

```python
@dataclass(frozen=True)
class PlotSettings:
    mode: PlotMode = 'auto'
    max_round_charts: int = 12
```

The charts: whether they are drawn, and the most round-by-round charts.

### <span id="pairbench.Ready"></span>`pairbench.Ready`

```python
@dataclass(frozen=True)
class Ready:
    http: str = '/health'
    timeout_s: float = 900.0
```

The readiness check of a serving side: an HTTP path polled until it answers.

### <span id="pairbench.ReportSettings"></span>`pairbench.ReportSettings`

```python
@dataclass(frozen=True)
class ReportSettings:
    include_image_refs: bool = False
    html: bool = True
```

What a results document may show, and whether a run writes the report page.

### <span id="pairbench.Results"></span>`pairbench.Results`

```python
@dataclass(frozen=True)
class Results:
    tool: Tool
    run: RunInfo
    rule: RuleInfo
    provenance: Provenance
    sides: tuple[ResultsSide, ...]
    plan: PlanSummary
    machine_state: MachineState
    cases: tuple[Case, ...] = ()
    comparisons: tuple[Comparison, ...] = ()
    same_vs_same: tuple[SameVsSame, ...] = ()
    twin_checks: tuple[TwinCheck, ...] = ()
    controls: Controls = field(default_factory=Controls)
    launch_cost: LaunchCost | None = None
    env_pad: EnvPad = field(default_factory=EnvPad)
    series: tuple[Series, ...] = ()
    plots: PlotsState = field(default_factory=PlotsState)
    diagnostics: DiagnosticsState = field(default_factory=DiagnosticsState)
    refusals: tuple[RefusalEntry, ...] = ()
    notes: tuple[Note, ...] = ()
    plugins: PluginCounts = field(default_factory=PluginCounts)
    figures: Mapping[str, Figure] = field(default_factory=dict)
    artifacts: Artifacts = field(default_factory=Artifacts)
    energy: EnergyInfo | None = None
    schema: Literal['pairbench/results/v1'] = SCHEMA_RESULTS
```

The analysed output of one or more captures.

`schema` is the schema id; a document that names another one is refused.

A results document is meant to be shared. It holds the comparisons of
the resource cases, the state of the explain step and of the charts, and
the names of the files a run wrote. It has no field for a function name,
a shared-object name or a call stack: those are held by the diagnostics
document, the files under `profiles/` and the report page alone.

`launch_cost` is `None`, and its key absent from the written
document, when no cost of a launch was measured. `twin_checks` holds
one combined check per side that has a twin; a document written without
it reads as holding none.

#### <span id="pairbench.Results.to_json"></span>`Results.to_json`

```python
def to_json(self) -> dict[str, Any]
```

Return the results document as a plain dict, `schema` first.

`energy` is present only when power was sampled, and
`launch_cost` only when the cost of a launch was measured. In a
results document the cost carries no record type.

#### <span id="pairbench.Results.has_difference"></span>`Results.has_difference`

```python
def has_difference(self) -> bool
```

Say whether a primary case came out `better` or `worse`.

The explain step runs under mode `auto` only when one did.

#### <span id="pairbench.Results.pending"></span>`Results.pending`

```python
def pending(self) -> Results
```

Return the document of the first write of a run.

The explain step and the charts have not run yet: both say
`pending`. Everything else is as analysed.

#### <span id="pairbench.Results.finished"></span>`Results.finished`

```python
def finished(
    self,
    *,
    diagnostics: DiagnosticsState,
    plots: PlotsState,
    notes: Sequence[Note] = (),
    artifacts: Artifacts | None = None,
) -> Results
```

Return the document of the second write of a run.

It holds the final state of the explain step and of the charts, the
notes those two steps added, laid after the notes already there, and
the final list of files. Nothing else differs from the first write.
Each added note is shown as every note of a results document is:
absolute paths in its message are cut to their last part.

#### <span id="pairbench.Results.interrupted"></span>`Results.interrupted`

```python
def interrupted(self) -> Results
```

Return the document of a run that was interrupted after its first write.

A state of the explain step or of the charts that still says
`pending` says `interrupted`. A state that was already final,
and everything else, stays as it is.

#### <span id="pairbench.Results.comparison"></span>`Results.comparison`

```python
def comparison(self, case: str, subject: str | None = None) -> Comparison
```

Return the comparison of a case, for one subject when there are several.

### <span id="pairbench.Rule"></span>`pairbench.Rule`

```python
@dataclass(frozen=True)
class Rule:
    name: str
    scale: Scale = 'ratio'
    floor_scope: Literal['group', 'case', 'side', 'experiment'] = 'group'
    bar: Literal['sum_of_both', 'twice_larger', 'twice_experiment_max'] = 'sum_of_both'
    bar_round_digits: int | None = None
    require_both_floors: bool = True
    p_source: Literal['corrected', 'raw'] = 'corrected'
    alpha: float = 0.05
    p_inclusive: bool = False
    gap_inclusive: bool = False
    tie: Literal['inside_and_not_significant', 'inside', 'never'] = 'inside_and_not_significant'
    min_rounds: int | None = None
```

The verdict rule. Results always record every field of the rule used.

`scale`: `ratio` grades the median of subject over baseline;
`percent` grades the median of `100.0 * (S - B) / B`.
`floor_scope`: which floor a comparison uses: that of its case group,
its own case, the largest of its side, or the largest of the experiment.
`bar`: `sum_of_both` floors, `twice_larger` of the two, or
`twice_experiment_max`. `bar_round_digits`: decimals each floor is
rounded to before the bar is formed, or `None`.
`require_both_floors`: no verdict when only one side has a twin.
`p_source`: the Holm-corrected p-value or the raw one.
`p_inclusive`: `p <= alpha` is significant. `gap_inclusive`:
`gap >= bar` is outside the bar. `tie`: when a comparison is a tie.
`min_rounds`: a fixed minimum, or `None` for `min_rounds(m, alpha)`.

#### <span id="pairbench.Rule.unit"></span>`Rule.unit`

```python
@property
def unit(self) -> FloorUnit
```

The unit of floors, bars and gaps under this rule's scale.

### <span id="pairbench.RuleSettings"></span>`pairbench.RuleSettings`

```python
@dataclass(frozen=True)
class RuleSettings:
    name: str = 'strict'
    fail_on: tuple[FailOn, ...] = ()
```

The name of the verdict rule and the outcomes that make the exit code 1.

### <span id="pairbench.RunSettings"></span>`pairbench.RunSettings`

```python
@dataclass(frozen=True)
class RunSettings:
    rounds: int | Literal['auto'] = 'auto'
    rounds_exact: bool = False
    quick: bool = False
    budget_s: float | None = None
    warmups: int = 1
    same_vs_same: Literal['on', 'off'] | tuple[str, ...] = 'on'
    allow_underpowered: bool = False
    out: str | None = None
    print_plan: bool = False
    json: bool = False
    no_plugins: bool = False
    node_type: str | None = None
    vary_env_size: bool = False
```

Round counts, warm-ups, twins and where the run folder goes.

`same_vs_same` is `"on"`, `"off"` or the names of the sides that get
a twin. `print_plan`, `json` and `no_plugins` mirror the command-line
switches of the same names. With `vary_env_size` every launch of a
round gets an environment pad whose length changes from round to round.

### <span id="pairbench.ServeSpec"></span>`pairbench.ServeSpec`

```python
@dataclass(frozen=True)
class ServeSpec:
    image: str | None = None
    args: tuple[str, ...] = ()
    port: int = 8000
    ready: Ready = DEFAULT_READY
    env: Mapping[str, str] = field(default_factory=dict)
    model: str | None = None
    model_name: str | None = None
    launcher: str | None = None
    command: tuple[str, ...] = ()
    probe: Probe = field(default_factory=Probe)
    phases: Mapping[str, str] = field(default_factory=dict)
```

What to serve, apart from how it is started.

`model` is where the model is; `model_name` is the name requests use,
and `None` asks the server's own model list. `launcher` of `None`
follows the container-engine choice. The host launcher takes `command`
in place of `image`. `phases` maps a start-up phase name to a regular
expression matched against the server's log.

#### <span id="pairbench.ServeSpec.from_json"></span>`ServeSpec.from_json`

```python
@classmethod
def from_json(cls, data: Mapping[str, Any]) -> Self
```

Build from the JSON form; an unknown key, here or in `ready` or `probe`, is refused.

A serving spec is what the user declared, so a misspelt key is an
error rather than a setting silently left at its default.

### <span id="pairbench.Side"></span>`pairbench.Side`

```python
@dataclass(frozen=True)
class Side:
    name: str
    kind: str
    role: Role = 'subject'
    twin_of: str | None = None
    control_of: str | None = field(default=None, kw_only=True)
    spec: Mapping[str, Any] = field(default_factory=dict)
    identity: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ''
    workdir_sha256: str | None = field(default=None, kw_only=True)
```

One thing being compared, or the twin of one.

`spec` holds what the user declared, shaped by kind:

* `cmd`: `{"argv": [...]}`; an argument `{workload}` is replaced by
  the shared workload;
* `image`: `{"image", "args", "env", "entrypoint"}`;
* `python`, `venv`, `conda`: `{"interpreter"}`, `{"venv"}`,
  `{"conda"}`;
* `serve`: the JSON form of `ServeSpec`;
* `file`: `{"paths": [...], "format"}`, where a path may be a glob and
  `format` names the driver that reads the files;
* any other kind, one a plug-in adds: `{"spec": text}`, or the table of
  plain values its config gave as `spec`.

`identity` and `fingerprint` are empty until the side is resolved. A
twin relation is the `twin_of` field and nothing else. The positive
control is the entry whose `control_of` field names the baseline; that
relation is never told from a name either.

`workdir_sha256` is the SHA-256 of the working folder the side ran in:
of its resolved path for a side that runs on the host, of the folder as
typed for one that runs in a container. It is `None` for a side that
runs nothing and in a capture that holds no such record. Pooling
compares it; it stays in the capture, and no results document, and no
hash a results document shows, holds it.

#### <span id="pairbench.Side.parse"></span>`Side.parse`

```python
@classmethod
def parse(cls, text: str) -> Side
```

Read `NAME=KIND:SPEC` as written after `--side`.

#### <span id="pairbench.Side.image"></span>`Side.image`

```python
@classmethod
def image(
    cls,
    name: str,
    ref: str,
    *,
    args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    entrypoint: str | None = None,
) -> Side
```

A container image. Its own `args` replace the shared workload for this side.

#### <span id="pairbench.Side.command"></span>`Side.command`

```python
@classmethod
def command(cls, name: str, argv: Sequence[str]) -> Side
```

A command. An argument `{workload}` is replaced by the shared workload.

#### <span id="pairbench.Side.python"></span>`Side.python`

```python
@classmethod
def python(
    cls,
    name: str,
    *,
    interpreter: str | None = None,
    venv: str | None = None,
    conda: str | None = None,
) -> Side
```

A Python environment: one of an interpreter, a virtual environment or a conda name.

#### <span id="pairbench.Side.serve"></span>`Side.serve`

```python
@classmethod
def serve(
    cls,
    name: str,
    image: str,
    args: Sequence[str],
    *,
    ready: Ready = DEFAULT_READY,
) -> Side
```

A server image with its arguments and readiness check.

#### <span id="pairbench.Side.files"></span>`Side.files`

```python
@classmethod
def files(cls, name: str, paths: Sequence[str], *, format: str | None) -> Side
```

Result files from another tool, one per round, read by the driver named `format`.

#### <span id="pairbench.Side.to_json"></span>`Side.to_json`

```python
def to_json(self, *, redact: bool = True) -> dict[str, Any]
```

Return the `side` record of a capture.

The spec is kept as declared, except that the value of every
credential-like environment variable in it is replaced, as it is in
the recorded config. Without `redact` the values are kept; nothing
that is written to a file may use that.

#### <span id="pairbench.Side.twin"></span>`Side.twin`

```python
def twin(self) -> Side
```

Return this side's twin: an identical copy named with the reserved suffix.

#### <span id="pairbench.Side.control"></span>`Side.control`

```python
def control(self) -> Side
```

Return the positive-control entry of this side, which must be the baseline.

It is a copy of the baseline named with the reserved suffix
`~twice`, with the role `control` and `control_of` naming the
baseline. One launch of it starts the baseline once and runs the
workload twice.

#### <span id="pairbench.Side.source"></span>`Side.source`

```python
@property
def source(self) -> str
```

The side this entry launches: its own name, or the side a twin or a control copies.

#### <span id="pairbench.Side.with_identity"></span>`Side.with_identity`

```python
def with_identity(self, identity: Mapping[str, Any], fingerprint: str) -> Side
```

Return a copy that carries a resolved identity and fingerprint.

#### <span id="pairbench.Side.with_role"></span>`Side.with_role`

```python
def with_role(self, role: Role) -> Side
```

Return a copy with another role (`subject` or `baseline`).

#### <span id="pairbench.Side.public_identity"></span>`Side.public_identity`

```python
def public_identity(self) -> dict[str, Any]
```

Return the part of the identity a results document may show.

Only the keys of `PUBLIC_IDENTITY_KEYS` are kept. A digest written
with its repository in front, as `repository@sha256:...`, is cut to
the hash. A value that is not a hash where one belongs is left out.

#### <span id="pairbench.Side.serve_spec"></span>`Side.serve_spec`

```python
def serve_spec(self) -> ServeSpec
```

Return the `ServeSpec` of a serving side.

#### <span id="pairbench.Side.for_results"></span>`Side.for_results`

```python
def for_results(
    self,
    *,
    include_image_ref: bool = False,
    driver: DriverInfo | None = None,
) -> ResultsSide
```

Return what a results document shows of this side.

The image reference is added only when the report settings ask for it.
A kind that a plug-in provides is shown as `plugin`. `driver` is
the driver that read the side, from `Capture.side_driver_info`, or
from `pooled_driver_info` for pooled captures.

### <span id="pairbench.__version__"></span>`pairbench.__version__`

The version of the installed package, a string such as `1.2.3`. It is the version that
`pairbench --version` prints and that every capture and results document records.

## <span id="pairbench.stats"></span>Module `pairbench.stats`

Every class of the data model is a frozen dataclass with a JSON form: `value.to_json()` gives
it, and the class method `from_json(data)` reads it back.

### <span id="pairbench.stats.holm"></span>`pairbench.stats.holm`

```python
def holm(pvalues: Sequence[float]) -> list[float]
```

Return the Holm-adjusted p-values, in the order the values were given.

The values are sorted ascending, ties kept in the order given, and
`adj[i] = max(adj[i - 1], min(1, (m - i) * p[i]))` for `i = 0 .. m - 1`,
with `adj[-1] = 0`. The running maximum keeps the adjusted values in
the order of the raw ones. `[0.01, 0.04, 0.5]` gives `[0.03, 0.08, 0.5]`.

### <span id="pairbench.stats.min_rounds"></span>`pairbench.stats.min_rounds`

```python
def min_rounds(n_cases: int, alpha: float = 0.05) -> int
```

Return the fewest rounds that can give a verdict for `n_cases` tested at once.

It is the smallest `n` with `n_cases * 2 ** (1 - n) < alpha`.

### <span id="pairbench.stats.paired"></span>`pairbench.stats.paired`

```python
def paired(observations: Iterable[Any], a: str, b: str) -> dict[str, Pairs]
```

Pair two lineup entries round by round, for every case either of them has.

`observations` are `pairbench.model.Observation` records, or mappings
with the keys `round`, `name`, `case` and `value`, of one capture:
the round is the pairing key. To pair across several captures, number
their rounds apart first. Observations of warm-up launches (round 0) are
left out. The rounds considered are those in which any observation was
given; a round in which either entry lacks a value for a case is not a
pair for that case and is counted in `n_unpaired`.

The same round, entry and case given twice is refused (`E_GRID`).

### <span id="pairbench.stats.sign_test"></span>`pairbench.stats.sign_test`

```python
def sign_test(n_lower: int, n_higher: int) -> SignTest
```

Return the exact two-sided sign test of `n_lower` against `n_higher` pairs.

`k = min(n_lower, n_higher)`, `tail = sum(comb(n, i) for i in 0..k)`
and `p = min(1, 2 * tail / 2 ** n)`. No pair at all gives 1.0. Twelve
against none gives 2/4096; ten against two gives 158/4096.

### <span id="pairbench.stats.Pairs"></span>`pairbench.stats.Pairs`

```python
@dataclass(frozen=True)
class Pairs:
    case: str
    a: str
    b: str
    rounds: tuple[int, ...]
    a_values: tuple[float, ...]
    b_values: tuple[float, ...]
    n_unpaired: int
```

The pairs of two lineup entries on one case.

`rounds` are the paired rounds in ascending order, and `a_values` and
`b_values` the two entries' values in those rounds. `n_unpaired`
counts the rounds considered in which either value is missing.

### <span id="pairbench.stats.SignTest"></span>`pairbench.stats.SignTest`

```python
@dataclass(frozen=True)
class SignTest:
    n_lower: int
    n_higher: int
    n: int
    p: float
    fraction: tuple[int, int]
```

The result of one sign test.

`n_lower` and `n_higher` count the pairs on each side of no
difference; ties are not trials and are counted in neither. `n` is
their sum. `p` is the two-sided p-value and `fraction` the same value
as an exact fraction `(numerator, denominator)`, with the denominator
`2 ** n`.

## <span id="pairbench.errors"></span>Module `pairbench.errors`

### <span id="pairbench.errors.Refusal"></span>`pairbench.errors.Refusal`

```python
class Refusal(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        scope: Scope = 'experiment',
        exit_code: int | None = None,
        detail: Mapping[str, Any] | None = None,
        results: Results | None = None,
    ) -> None
```

A refusal: a stable text code, an exit code, a one-line message and a scope.

`detail` carries machine-readable extras for the caller, for example
every missing figure key or every bad grid cell. It is never written to a
results document. `results` is the results document that describes the
refused run, when one could be built: no comparisons and this refusal
listed in `refusals`.

The message is printed on standard error and is also written to the
results document, which is meant to be shared. It names a side by the
name the user gave it and a file by the last part of its path, and holds
no host, no user, no image reference and no value of the environment;
such things belong in `detail`.

#### <span id="pairbench.errors.Refusal.line"></span>`Refusal.line`

```python
@property
def line(self) -> str
```

The one line printed on standard error: `CODE: message`, with each control
character of the message escaped.

#### <span id="pairbench.errors.Refusal.to_json"></span>`Refusal.to_json`

```python
def to_json(self) -> dict[str, str]
```

The entry written to `refusals` in a results document.

## <span id="pairbench.api"></span>Module `pairbench.api`

### <span id="pairbench.api.SideKind"></span>`pairbench.api.SideKind`

```python
class SideKind(Protocol):
    ...
```

A kind of side: `cmd`, `image`, `python`, `venv`, `conda`, `serve`, `file`.

`resolve` turns a declared side into something launchable and records
its identity. The image pull policy applies in `resolve` and nowhere
else. A side that cannot be found is refused with `E_SIDE_UNRESOLVED`;
one that cannot be identified, or whose `identify` command gives no
output or fails, with `E_SIDE_UNIDENTIFIED`. `resolve` starts no
workload.

`look_up` reads a side's identity for the plan command and changes
nothing: it never pulls, starts no container, runs no `identify`
command, creates no directory and takes no lock. It may inspect an image
that is already on the machine, ask an interpreter for its version and
its installed distributions, and hash files. What it reports and what it
refuses:

* an image that is not on the machine: status `absent` under pull
  policy `missing` or `always`; refused with `E_SIDE_UNRESOLVED`
  under `never`;
* no container engine reachable: status `unchecked`, never a refusal.
  It finds the engine with `find_engine`, not `choose_engine`;
* an executable, an interpreter, an environment or a result file that
  does not exist: refused with `E_SIDE_UNRESOLVED`;
* a launch setting the kind cannot honour: refused with
  `E_ENGINE_UNSUPPORTED`;
* a side that exists but whose identity cannot be read, such as an
  interpreter that gives no version: refused with
  `E_SIDE_UNIDENTIFIED` (exit 3);
* a spec the kind cannot read: refused with `E_USAGE`.

It raises no other refusal.

#### <span id="pairbench.api.SideKind.name"></span>`SideKind.name`

```python
@property
def name(self) -> str
```

#### <span id="pairbench.api.SideKind.api_version"></span>`SideKind.api_version`

```python
@property
def api_version(self) -> int
```

#### <span id="pairbench.api.SideKind.resolve"></span>`SideKind.resolve`

```python
def resolve(self, side: Side, ctx: SideContext) -> ResolvedSide
```

Resolve and identify one side.

#### <span id="pairbench.api.SideKind.look_up"></span>`SideKind.look_up`

```python
def look_up(self, side: Side, ctx: SideContext) -> SideLookup
```

Read one side's identity without changing anything.

### <span id="pairbench.api.ResolvedSide"></span>`pairbench.api.ResolvedSide`

```python
class ResolvedSide(Protocol):
    ...
```

A side that was resolved and can be identified, launched and torn down.

Required of an implementation:

* `side` carries the recorded identity and the fingerprint
  `fingerprint_of(identity, settings.effective(...))`;
* `command` is the complete command a launch of this side runs, before
  the driver prepares it. Every substitution is already made: a `cmd`
  side gives its own arguments with `{workload}` replaced by the shared
  workload; an image side gives its own `args`, else the shared
  workload, else `None` for the image's default command; a Python
  environment side gives its interpreter followed by the workload, a
  leading `python` or `python3` of the workload being replaced by the
  interpreter. A serving side and a file side give `None`. A side
  whose container runs more than `command`, an image side with an
  entrypoint or a default command, may also give `whole_command`, that
  whole command line or `None`; the explain step reads it, when given,
  in place of `command` to choose its sampler;
* `identify` reads the identity again, so the runner can compare it
  after the last round; it never pulls;
* `launch` starts a fresh launch, waits for it, tears it down and
  removes what it created, also when it is interrupted. A container is
  started by image ID with pulling disabled, named with
  `container_name` and has the artifact folder mounted at
  `ARTIFACTS_IN_CONTAINER`. Values of `env_pass` variables are
  forwarded and never recorded. A setting the kind cannot honour is
  refused with `E_ENGINE_UNSUPPORTED`, never dropped;
* a non-zero exit or a timeout is reported in the outcome, not raised:
  the runner decides what a failed launch means;
* a file side launches nothing. Its files are the matches of its paths,
  sorted by file name; `rounds_available` is their number; `launch`
  for round `r` returns `LaunchOutcome(rc=0, result_file=...)` with
  the `r`-th of them, counted from 1;
* `launch` reports the resource usage of the launch in the outcome, as
  `LaunchOutcome` states for each kind of side;
* a container is given the capability to use performance counters, and
  no other capability, exactly when the launch setting `perf_counters`
  is set. A capability that was not asked for is never added;
* `cannot_repeat` says whether the side can run two prepared commands
  in one start, which a launch of the positive control asks for with
  `LaunchRequest.second`. A command side and a Python environment side
  always can. An image side can when the image lets one container run
  two commands one after the other, for example because it holds a
  shell; when it does not, the property gives the reason in one line.
  The answer is known before the first measured launch and does not
  change during a run. A side that gave no reason and then cannot run
  the second command reports a failed launch, as for any other command
  that does not start; it never runs the two commands as two launches.
  When it can tell that cause, it says so in
  `LaunchOutcome.cannot_repeat`, and the run goes on without the
  control.

#### <span id="pairbench.api.ResolvedSide.side"></span>`ResolvedSide.side`

```python
@property
def side(self) -> Side
```

The side with its identity and fingerprint filled in.

#### <span id="pairbench.api.ResolvedSide.command"></span>`ResolvedSide.command`

```python
@property
def command(self) -> tuple[str, ...] | None
```

The complete command of a launch before the driver prepares it, or `None`.

#### <span id="pairbench.api.ResolvedSide.engine"></span>`ResolvedSide.engine`

```python
@property
def engine(self) -> EngineInfo | None
```

The container engine this side uses, or `None` when it uses none.

#### <span id="pairbench.api.ResolvedSide.rounds_available"></span>`ResolvedSide.rounds_available`

```python
@property
def rounds_available(self) -> int | None
```

How many rounds exist: the number of files of a file side, else `None`.

#### <span id="pairbench.api.ResolvedSide.cannot_repeat"></span>`ResolvedSide.cannot_repeat`

```python
@property
def cannot_repeat(self) -> str | None
```

Why the side cannot run two commands in one start, or `None` when it can.

#### <span id="pairbench.api.ResolvedSide.identify"></span>`ResolvedSide.identify`

```python
def identify(self) -> Mapping[str, Any]
```

Read the identity again.

#### <span id="pairbench.api.ResolvedSide.artifacts_in_side"></span>`ResolvedSide.artifacts_in_side`

```python
def artifacts_in_side(self, host: Path) -> str
```

Return the path under which a launch sees its artifact folder.

`host` is the launch's own folder, `LaunchRequest.artifacts`, and
never a folder under it. A side on the host sees the folder where it
is; a container side sees it at `ARTIFACTS_IN_CONTAINER`, whatever
the folder on the host. The folders of the two runs of a launch that
holds two runs are not asked for here: `run_folders` derives them
from this answer.

#### <span id="pairbench.api.ResolvedSide.tool_file_in_side"></span>`ResolvedSide.tool_file_in_side`

```python
def tool_file_in_side(self, host: Path) -> str
```

Return the path under which a launch sees a file of `LaunchRequest.tool_files`.

A side on the host sees the file where it is. A container side sees
it under `TOOLS_IN_CONTAINER`, by its own file name, mounted
read-only.

#### <span id="pairbench.api.ResolvedSide.launch"></span>`ResolvedSide.launch`

```python
def launch(self, request: LaunchRequest) -> LaunchOutcome
```

Run one launch to its end and tear it down.

A pinned CPU set the side cannot apply when it starts the launch is
refused with `E_PIN_UNSUPPORTED` (exit 4).

#### <span id="pairbench.api.ResolvedSide.close"></span>`ResolvedSide.close`

```python
def close(self) -> None
```

Release everything still held. Safe to call more than once.

### <span id="pairbench.api.SideContext"></span>`pairbench.api.SideContext`

```python
@dataclass(frozen=True)
class SideContext:
    run_id: str
    settings: LaunchSettings
    workload: tuple[str, ...] | None = None
    driver: str = 'wall'
    environ: Mapping[str, str] = field(default_factory=dict)
    gpu: GpuProbe | None = None
    mode: GateMode = 'warn'
    note: Notify = no_notes
    launch_folders: Path | None = None
    workload_hashed: tuple[str, ...] | None = None
```

What a side kind is told when it resolves or looks up a side.

`settings` are the launch settings already merged for this side.
`workload` is the shared workload. `driver` is the driver's name; a
file side reads with it when its own format is unset. `environ` is the
caller's environment: values of `env_pass` variables are taken from it,
forwarded and never recorded. `gpu` reads the selected GPUs for a serving
side's waits. `mode` is the machine-check mode. `note` receives loud
notes. `launch_folders` is the folder in which the run makes the folder
of each launch; it may not exist yet when the side is resolved, and it is
`None` for the sides of an explain or profile session. For a look-up
there is no run: `run_id` is empty, and `gpu` and `launch_folders`
are `None`. `workload_hashed` is the shared workload as the published
hash of every side's command reads it, after what each side of the
experiment runs before it (`pairbench.model.hashed_workload`): a kind
that hashes a command holding the workload hashes it through
`pairbench.model.hashed_command` with these words, so a value that the
client of one side hides is hidden in the hash of every side. `None`
leaves each side to read the workload after its own command alone.

### <span id="pairbench.api.SideLookup"></span>`pairbench.api.SideLookup`

```python
@dataclass(frozen=True)
class SideLookup:
    status: LookupStatus
    identity: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ''
    message: str = ''
```

What a read-only look-up found out about one side.

`status` is one of:

* `identified`: the side is on this machine and its identity was read.
  `identity` holds what `resolve` would record, apart from the output
  of an `identify` command, which a look-up never runs;
* `absent`: the image is not on this machine and the pull policy is
  `missing` or `always`, so a run would pull it. `identity` is
  empty;
* `unchecked`: no container engine could be reached, so the identity
  was not checked. `identity` is empty.

`fingerprint` is set only when `status` is `identified` and no
`identify` command is configured for the side: it then equals the
fingerprint `resolve` would record. Otherwise it is empty.
`message` is one line for the plan output: what a run would do about an
absent image, why nothing was checked, or that an image under pull policy
`always` is pulled again by a run.

### <span id="pairbench.api.Driver"></span>`pairbench.api.Driver`

```python
class Driver(Protocol):
    name: str
    api_version: int
    where: Literal['in_side', 'client']
```

Turns one launch into one value per case.

Required of an implementation:

* `prepare` adds the wrapped tool's own output option when the user's
  command lacks it, pointing at `ctx.artifacts_in_side`, and changes
  nothing else of the command. For an `in_side` driver `argv` is
  `ResolvedSide.command`, complete and already substituted, or empty
  when the side has none; the side then runs the returned command as it
  is. A driver that needs a command to add its option to refuses an empty
  one with `E_USAGE`; `wall` returns it unchanged. For a `client`
  driver `argv` is the shared workload, or empty; it builds one step
  per load level against `ctx.endpoint` and passes `ctx.seed` to a
  tool that accepts a seed. `prepare` is not called for a file side;
* `read` returns one `Sample` per case from `artifacts`, or from
  `ctx.result_file` for a file side. Output it cannot read is refused
  with `E_LAUNCH_FAILED`. A case the tool skipped is left out and
  reported through `ctx.note`;
* `default_primary` names the cases that count toward the verdict. It
  may name every case it read: a case whose `better` is `none` is
  recorded as secondary all the same, without a refusal.

An implementation declares `where` with its full type, for example
`where: Literal["in_side", "client"] = "in_side"`.

#### <span id="pairbench.api.Driver.prepare"></span>`Driver.prepare`

```python
def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation
```

#### <span id="pairbench.api.Driver.read"></span>`Driver.read`

```python
def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]
```

#### <span id="pairbench.api.Driver.default_primary"></span>`Driver.default_primary`

```python
def default_primary(self, samples: list[Sample]) -> list[str]
```

### <span id="pairbench.api.DriverContext"></span>`pairbench.api.DriverContext`

```python
@dataclass(frozen=True)
class DriverContext:
    run_id: str
    seq: int
    phase: LaunchPhase
    round: int
    name: str
    side: Side
    artifacts: Path
    artifacts_in_side: str
    settings: LoadSettings = field(default_factory=LoadSettings)
    seed: int = DEFAULT_SEED
    endpoint: Endpoint | None = None
    timing: Mapping[str, float] = field(default_factory=dict)
    rc: int | None = None
    energy: EnergyReading | None = None
    result_file: Path | None = None
    note: Notify = no_notes
    launch: LaunchSettings = field(default_factory=LaunchSettings)
    case_names: CaseNames | None = field(default=None, compare=False)
```

What a driver is told about one launch.

`artifacts` is the launch's folder on the host and `artifacts_in_side`
the same folder as the launched program sees it; a driver points the
tool's output option at the latter and reads from the former. `settings`
carries the load levels and the length of each. `endpoint` is set for a
`client` driver. `timing`, `rc` and `energy` are filled when
`read` is called. `result_file` is set for a file side: the one
existing file to read in place of the artifact folder. `note` receives
loud notes, for example a case the tool skipped. `launch` are the
launch settings already merged for the side; a driver that needs a
setting of the launch, such as the capability to use performance
counters, reads it there. `case_names` holds the names the run gives
to the case ids it reads (`CaseNames`); a driver that cleans its ids
itself (`CleansCaseIds`) names them with `name_tool_cases`.

In a launch of the positive control that holds two runs, the driver is
asked to prepare and to read each run on its own: `artifacts` and
`artifacts_in_side` are then the folder of that run, on the host and
as the launch sees it, the pair `run_folders` gives for the run, and
`timing` is the one interval around both runs.

### <span id="pairbench.api.Invocation"></span>`pairbench.api.Invocation`

```python
@dataclass(frozen=True)
class Invocation:
    steps: tuple[Step, ...]
```

What a driver wants run for one launch.

An `in_side` driver returns exactly one step with an empty label; the
side launches its `argv`. A `client` driver returns one step per load
level; the runner runs them in order on the host, beside the server, and
times each as one energy window.

#### <span id="pairbench.api.Invocation.single"></span>`Invocation.single`

```python
@classmethod
def single(cls, argv: Sequence[str], env: Mapping[str, str] | None = None) -> Invocation
```

Build the invocation of an `in_side` driver.

#### <span id="pairbench.api.Invocation.argv"></span>`Invocation.argv`

```python
@property
def argv(self) -> tuple[str, ...]
```

The command of a single-step invocation.

#### <span id="pairbench.api.Invocation.env"></span>`Invocation.env`

```python
@property
def env(self) -> Mapping[str, str]
```

The added environment of a single-step invocation.

### <span id="pairbench.api.Step"></span>`pairbench.api.Step`

```python
@dataclass(frozen=True)
class Step:
    label: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
```

One command of an invocation. `label` is empty, or a load-level label.

### <span id="pairbench.api.Sample"></span>`pairbench.api.Sample`

```python
@dataclass(frozen=True)
class Sample:
    case: str
    metric: str
    unit: str
    better: Better
    kind: CaseKind
    value: float
    n_inner: int = 1
    reducer: str = REDUCER_IDENTITY
```

One value of one case, as a driver or a side reads it from one launch.

When a tool gives several inner samples for a case, `value` is their
median, `n_inner` their count and `reducer` is `"median"`. When a
tool gives only its own summary, `reducer` is `"tool_summary"`.

`value` is a finite number. A value that is not one, such as the
`nan` or `inf` a tool may print, is output that cannot be read: making
the sample is refused with `E_LAUNCH_FAILED`. A value of zero or less
is kept; the analysis gives its case no verdict.

#### <span id="pairbench.api.Sample.to_case"></span>`Sample.to_case`

```python
def to_case(self, *, primary: bool, group: str | None = None) -> Case
```

Return the case this sample describes.

### <span id="pairbench.api.ToolVersion"></span>`pairbench.api.ToolVersion`

```python
@dataclass(frozen=True)
class ToolVersion:
    tool: str
    version: str
    tested: bool = True
```

The version of the tool a driver wraps, and whether its major version was tested.

### <span id="pairbench.api.CaptureReader"></span>`pairbench.api.CaptureReader`

```python
class CaptureReader(Protocol):
    name: str
    api_version: int
```

Reads captures from a file in some format.

`sniff` says whether the file looks like this reader's format, from its
path and its first bytes, without reading further. `read` returns one
capture per run in the file and sets each capture's `source`.

A reader of a format that has no end record gives each capture a lineup
record and an end record that says `complete`, as `Capture.from_rows`
does, with sides of kind `rows`; the analysis then accepts the capture
without the override for an incomplete one. Rows whose order the format
did not record have no position. A value that is not a finite number is
never read into a capture. A value that parses as a number and is zero
or less is not malformed: its row is kept, and an analysis gives its
case no verdict.

#### <span id="pairbench.api.CaptureReader.sniff"></span>`CaptureReader.sniff`

```python
def sniff(self, path: Path, head: bytes) -> bool
```

#### <span id="pairbench.api.CaptureReader.read"></span>`CaptureReader.read`

```python
def read(self, path: Path) -> list[Capture]
```

### <span id="pairbench.api.Gate"></span>`pairbench.api.Gate`

```python
class Gate(Protocol):
    ...
```

One machine check.

`check` returns a record whose status is `pass`, `fail`,
`degraded` or `unavailable`. A probe that fails to read counts as
busy. A check that could not run is `unavailable` or `degraded`,
never `pass`. `detail["message"]` is a one-line reason that names
nothing which identifies the machine: no host, no user, no path, no image
reference and no name of another container. It is what the results show;
everything else of `detail` stays in the capture. The check does not
decide what its status means under the mode: the runner does.

#### <span id="pairbench.api.Gate.name"></span>`Gate.name`

```python
@property
def name(self) -> str
```

#### <span id="pairbench.api.Gate.api_version"></span>`Gate.api_version`

```python
@property
def api_version(self) -> int
```

#### <span id="pairbench.api.Gate.check"></span>`Gate.check`

```python
def check(self, ctx: GateContext) -> GateRecord
```

Run the check once and report.

### <span id="pairbench.api.GateContext"></span>`pairbench.api.GateContext`

```python
@dataclass(frozen=True)
class GateContext:
    mode: GateMode
    gates: GateSettings
    launch: LaunchSettings
    phase: GatePhase = 'before'
    environ: Mapping[str, str] = field(default_factory=dict)
    in_container: bool = False
    ci: bool = False
    note: Notify = no_notes
    sides: Mapping[str, LaunchSettings] = field(default_factory=dict)
```

What a machine check is told.

`phase` is `before` for the checks ahead of the locks and `recheck`
for the short re-check once the locks are held; a check never waits in
the re-check. `in_container` and `ci` are the facts of the machine
record: the run is inside a container, or in an automated pipeline. A
check waits for a quiet machine only when `gates.wait_quiet` is set.
`sides` holds the launch settings each launched side runs with, by side
name, overrides merged in. It is empty when the sides are not known; a
check then reads `launch` and the sides its overrides name.

### <span id="pairbench.api.RuleProvider"></span>`pairbench.api.RuleProvider`

```python
class RuleProvider(Protocol):
    ...
```

Provides a named verdict rule.

#### <span id="pairbench.api.RuleProvider.name"></span>`RuleProvider.name`

```python
@property
def name(self) -> str
```

#### <span id="pairbench.api.RuleProvider.api_version"></span>`RuleProvider.api_version`

```python
@property
def api_version(self) -> int
```

#### <span id="pairbench.api.RuleProvider.rule"></span>`RuleProvider.rule`

```python
def rule(self) -> Rule
```

Return the rule.

### <span id="pairbench.api.Reporter"></span>`pairbench.api.Reporter`

```python
class Reporter(Protocol):
    ...
```

Renders a results document as text.

A reporter reads `Results` and, when `options.diagnostics` holds one,
the diagnostics document. It never reads a capture. Every number it
shows comes from the documents; it computes none. The terminal and the
markdown reporter show no function name and no shared-object name: of
the findings they show those of `Diagnostics.shareable_findings`. The
reporter `html` writes the report page; it may show such names, says
so at its top when it does, and embeds the chart and flame-graph files
of `options.folder`.

#### <span id="pairbench.api.Reporter.name"></span>`Reporter.name`

```python
@property
def name(self) -> str
```

#### <span id="pairbench.api.Reporter.api_version"></span>`Reporter.api_version`

```python
@property
def api_version(self) -> int
```

#### <span id="pairbench.api.Reporter.render"></span>`Reporter.render`

```python
def render(self, results: Results, options: ReportOptions) -> str
```

Return the report.

### <span id="pairbench.api.ReportOptions"></span>`pairbench.api.ReportOptions`

```python
@dataclass(frozen=True)
class ReportOptions:
    cases: tuple[str, ...] = ()
    all_cases: bool = False
    verbose: bool = False
    diagnostics: Diagnostics | None = None
    folder: Path | None = None
```

Display choices for a report, and what else a report may show.

`cases`, `all_cases` and `verbose` filter what is shown, never what
was tested. `diagnostics` is the diagnostics document of the run, when
there is one: the terminal and markdown reports add its findings and the
report page adds the diagnostics. `folder` is the run folder: the
report page embeds the chart and flame-graph files found there. Without
either, every format is rendered from the results alone.

### <span id="pairbench.api.Launcher"></span>`pairbench.api.Launcher`

```python
class Launcher(Protocol):
    ...
```

Starts what a `ServeSpec` describes: with docker, with podman, or as a host process.

`resolve` finds the image or the command, applies the pull policy and
returns the identity: the image ID and the arguments. `look_up` reads
the same identity without changing anything, under the rules
`SideKind.look_up` states; it leaves `fingerprint` empty, and the
serving side kind fills it in. `start` starts one server for one launch
and returns at once; two servers never run at the same time.

#### <span id="pairbench.api.Launcher.name"></span>`Launcher.name`

```python
@property
def name(self) -> str
```

#### <span id="pairbench.api.Launcher.api_version"></span>`Launcher.api_version`

```python
@property
def api_version(self) -> int
```

#### <span id="pairbench.api.Launcher.resolve"></span>`Launcher.resolve`

```python
def resolve(self, spec: ServeSpec, ctx: SideContext) -> Mapping[str, Any]
```

#### <span id="pairbench.api.Launcher.look_up"></span>`Launcher.look_up`

```python
def look_up(self, spec: ServeSpec, ctx: SideContext) -> SideLookup
```

#### <span id="pairbench.api.Launcher.start"></span>`Launcher.start`

```python
def start(self, spec: ServeSpec, ctx: SideContext, request: LaunchRequest) -> ServerHandle
```

### <span id="pairbench.api.ServerHandle"></span>`pairbench.api.ServerHandle`

```python
class ServerHandle(Protocol):
    ...
```

A server that was started for one launch.

Times are seconds from the start request. `wait_ready` polls the
readiness check and refuses with `E_LAUNCH_FAILED` when it does not
pass in time. `first_answer` sends one small request and waits for the
first non-empty answer. `stop` stops and removes the server and writes
its log to `server.log` in the artifact folder. `wait_released` waits
for GPU memory in use to return to within `tolerance_mib` of
`level_mib` and refuses with `E_GPU_NOT_RELEASED` when it does not.

A handle may also offer `exited_during_load() -> int | None`: the exit
status of a server that exited before its stop, else `None`. The
serving side asks it after the load and makes the launch a failed one
when the server is gone; a handle without it gets no such check.

#### <span id="pairbench.api.ServerHandle.endpoint"></span>`ServerHandle.endpoint`

```python
@property
def endpoint(self) -> Endpoint
```

#### <span id="pairbench.api.ServerHandle.wait_ready"></span>`ServerHandle.wait_ready`

```python
def wait_ready(self, ready: Ready) -> float
```

#### <span id="pairbench.api.ServerHandle.first_answer"></span>`ServerHandle.first_answer`

```python
def first_answer(self, probe: Probe) -> float
```

#### <span id="pairbench.api.ServerHandle.stop"></span>`ServerHandle.stop`

```python
def stop(self) -> None
```

#### <span id="pairbench.api.ServerHandle.wait_released"></span>`ServerHandle.wait_released`

```python
def wait_released(
    self,
    level_mib: float,
    *,
    tolerance_mib: float = GPU_RELEASE_TOLERANCE_MIB,
    timeout_s: float = GPU_RELEASE_WAIT_S,
) -> None
```

### <span id="pairbench.api.Endpoint"></span>`pairbench.api.Endpoint`

```python
@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model_name: str | None = None
    deadline: float | None = None
```

Where a started server answers: its base address and the model name requests use.

`deadline` is the `time.monotonic()` value by which the load must
end, set from the launch timeout counted from the server start; `None`
when no timeout is set.

### <span id="pairbench.api.API_VERSION"></span>`pairbench.api.API_VERSION`

```python
API_VERSION: Final = 1
```
