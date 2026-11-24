# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The self-test: controls of the statistics on synthetic captures.

``synthetic_capture`` is the one seeded generator of synthetic captures. It
builds a capture record by record, as a run writes one: a header, a machine
record with made-up facts, the sides with their twins and, on request, the
positive control, one warm-up launch per side, the lineup, one launch per
lineup entry and round in the order of the ``rotate-reverse`` schedule, the
observations and the end record. The values come from a function of the
entry, the case, the round and one uniform draw of the seeded generator.

``run_selftest`` runs the controls K1 to K4 and C1 to C17 in that
order. Every expected value is a constant written
here. A control that fails, or raises, is reported as failed; the function
itself never raises.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from pairbench.errors import Refusal
from pairbench.model import (
    SCHEDULE,
    STRICT,
    Capture,
    Case,
    Comparison,
    CpuGroup,
    CpuRecord,
    DiscardThresholds,
    End,
    GateRecord,
    Header,
    Launch,
    LaunchCost,
    Lineup,
    MachineRecord,
    Observation,
    Plan,
    Results,
    Rule,
    Side,
    Source,
    compared_pairs,
    count_balance,
    launch_cost_note,
    min_rounds,
    plan_rows,
    resource_case,
    rotate_reverse,
    sha256_hex,
    trapezoid,
)
from pairbench.stats.analyse import analyse_captures
from pairbench.stats.holm import holm, holm_exact
from pairbench.stats.rules import is_significant
from pairbench.stats.signtest import sign_test

ValueFn = Callable[[str, str, int, float], float]
"""A value of the generator: ``(entry, case, round, u)`` to a number, ``u`` uniform in [0, 1)."""

MATMUL = Case(id="matmul", metric="time", unit="s", kind="time")
WALL = Case(id="wall", metric="wall", unit="s", kind="time")
BUSY_CORES = 8.0
"""The busy cores a disturbed launch's witness reads: above the default threshold of 2."""


@dataclass(frozen=True)
class ControlResult:
    """The result of one control: its id, a title, whether it passed, and what was found."""

    id: str
    title: str
    passed: bool
    detail: str


def _fingerprint(name: str) -> str:
    return sha256_hex(f"synthetic side {name}")


def synthetic_capture(
    value: ValueFn,
    *,
    seed: int = 1,
    rounds: int = 16,
    subjects: Sequence[str] = ("new",),
    baseline: str = "old",
    twinned: Sequence[str] | None = None,
    control: ValueFn | None = None,
    cases: Sequence[Case] = (MATMUL,),
    kind: str = "cmd",
    order: str = "schedule",
    disturbed: Sequence[int] = (),
    warmups: int = 1,
    capture_id: str | None = None,
    launch_cost: LaunchCost | None = None,
    gates: Sequence[GateRecord] = (),
) -> Capture:
    """Build a complete synthetic capture.

    ``twinned`` names the sides that get a twin; all of them by default.
    ``control`` gives the values of the positive-control entry, which is
    then added; it runs last in every round. ``order`` is ``schedule`` for
    the ``rotate-reverse`` order, ``fixed`` for the same order in every
    round, or ``none`` for no recorded order. Every launch of a round named
    in ``disturbed`` has a witness above the threshold of busy cores.
    """
    rng = random.Random(seed)
    declared = [
        Side(name=n, kind=kind, role="subject", spec={"argv": ("bench",)}) for n in subjects
    ]
    declared.append(Side(name=baseline, kind=kind, role="baseline", spec={"argv": ("bench",)}))
    declared = [s.with_identity({}, _fingerprint(s.name)) for s in declared]
    with_twin = set(twinned if twinned is not None else (s.name for s in declared))
    lineup: list[Side] = []
    for side in declared:
        lineup.append(side)
        if side.name in with_twin:
            lineup.append(side.twin())
    entry = declared[-1].control() if control is not None else None
    names = tuple(s.name for s in lineup)
    rows = plan_rows(lineup, rounds, entry)
    ident = capture_id or "synthetic-" + sha256_hex(f"{seed}/{rounds}/{names}")[:12]
    launches: list[Launch] = []
    observations: list[Observation] = []
    seq = 0
    for side in declared:
        for _ in range(warmups):
            seq += 1
            launches.append(Launch(seq=seq, phase="warmup", round=0, pos=None, name=side.name))
    for row in rows:
        seq += 1
        if order == "fixed" and row.name in names:
            pos: int | None = names.index(row.name) + 1
        elif order == "none":
            pos = None
        else:
            pos = row.pos
        busy = BUSY_CORES if row.round in disturbed else 0.0
        launches.append(
            Launch(
                seq=seq,
                phase="round",
                round=row.round,
                pos=pos,
                name=row.name,
                witness={"busy_cores": busy},
            )
        )
        make = control if entry is not None and row.name == entry.name else value
        assert make is not None
        for case in cases:
            if entry is not None and row.name == entry.name and case.better == "none":
                continue
            observations.append(
                Observation(
                    seq=seq,
                    round=row.round,
                    pos=pos,
                    name=row.name,
                    case=case.id,
                    value=make(row.name, case.id, row.round, rng.random()),
                )
            )
    sides = (*lineup, *((entry,) if entry is not None else ()))
    return Capture(
        capture_id=ident,
        header=Header(capture_id=ident, argv=("pairbench", "run"), seeds={"driver": seed}),
        machine=MachineRecord(
            os="Linux 0.0",
            arch="arch-a",
            cpu=CpuRecord(model="cpu-model-a", identity=(CpuGroup(cpus="0-3", key="core-type-a"),)),
        ),
        sides=sides,
        gates=tuple(gates),
        lineup=Lineup(
            names=names,
            control=entry.name if entry is not None else None,
            rounds=rounds,
            schedule=SCHEDULE,
            cases=tuple(cases),
            discard_thresholds=DiscardThresholds(),
        ),
        cases=tuple(cases),
        launches=tuple(launches),
        observations=tuple(observations),
        end=End(status="complete", rounds_completed=rounds),
        source=Source(path=f"{ident}.jsonl", sha256=sha256_hex(ident)),
        launch_cost=launch_cost,
    )


# ---------------------------------------------------------------------------
# Value functions
# ---------------------------------------------------------------------------


def _noisy(base: Mapping[str, float], spread: float) -> ValueFn:
    """Each entry's base value times ``1 + spread * (2u - 1)``; a twin has its side's base."""

    def value(entry: str, case: str, round_: int, u: float) -> float:
        side = entry.split("~")[0]
        return base[side] * (1.0 + spread * (2.0 * u - 1.0))

    return value


def _exact(table: Mapping[str, Callable[[int], float]]) -> ValueFn:
    """A value per entry that depends on the round alone."""

    def value(entry: str, case: str, round_: int, u: float) -> float:
        return table[entry](round_)

    return value


def _known_difference(entry: str, case: str, round_: int, u: float) -> float:
    """``new`` reads twice ``old`` in every round; a twin is within 1 percent of its side."""
    shared = 1.0 + 0.25 * ((round_ * 7) % 5) / 4.0
    if entry == "old":
        return shared
    if entry == "new":
        return 2.0 * shared
    side = 2.0 * shared if entry.startswith("new") else shared
    return side * (1.0 + 0.01 * (2.0 * u - 1.0))


def _first(results: Results, case: str = "matmul", subject: str | None = None) -> Comparison:
    return results.comparison(case, subject)


def _code(make: Callable[[], Any]) -> str | None:
    try:
        make()
    except Refusal as refusal:
        return refusal.code
    return None


def _expect(*checks: tuple[str, Any, Any]) -> tuple[bool, str]:
    """Compare each found value with its expected constant; say what differed."""
    wrong = [
        f"{label}: expected {want!r}, found {got!r}" for label, want, got in checks if want != got
    ]
    return (not wrong, "; ".join(wrong) if wrong else "every value as expected")


def _analyse(captures: Capture | Sequence[Capture], **options: Any) -> Results:
    given = (captures,) if isinstance(captures, Capture) else tuple(captures)
    rule = options.pop("rule", STRICT)
    return analyse_captures(given, rule=rule, **options)


# ---------------------------------------------------------------------------
# The controls
# ---------------------------------------------------------------------------


def _k1() -> tuple[bool, str]:
    known = {
        (12, 0): (2, 4096),
        (10, 2): (158, 4096),
        (6, 0): (2, 64),
        (5, 1): (14, 64),
        (0, 2): (2, 4),
        (0, 0): (1, 1),
        (13, 7): (275960, 1048576),
    }
    checks: list[tuple[str, Any, Any]] = [
        (f"sign test {k}", v, sign_test(*k).fraction) for k, v in known.items()
    ]
    checks.append(("18 against 6 to four places", 0.0227, round(sign_test(18, 6).p, 4)))
    five = sign_test(5, 0)
    verdict = is_significant(Fraction(*five.fraction), STRICT)
    checks += [("5 against 0", 0.0625, five.p), ("5 against 0 gives a verdict", False, verdict)]
    return _expect(*checks)


def _k2() -> tuple[bool, str]:
    known = [
        ([0.01, 0.04, 0.5], [0.03, 0.08, 0.5]),
        ([0.01, 0.012, 0.5], [0.03, 0.03, 0.5]),
        ([0.01, 0.04, 0.03], [0.03, 0.06, 0.06]),
        ([0.03125, 0.03125, 0.21875], [0.09375, 0.09375, 0.21875]),
    ]
    checks: list[tuple[str, Any, Any]] = []
    for raw, adjusted in known:
        got = holm(raw)
        close = all(abs(a - b) <= 1e-15 for a, b in zip(got, adjusted, strict=True))
        checks.append((f"holm {raw}", True, close))
        # The exact correction of the same values, read as their decimal text.
        exact = holm_exact([Fraction(repr(p)) for p in raw])
        checks.append((f"exact holm {raw}", [Fraction(repr(a)) for a in adjusted], exact))
    return _expect(*checks)


def _plan(lineup: Sequence[Side], rounds: int) -> Plan:
    rows = plan_rows(lineup, rounds)
    return Plan(
        rows=rows,
        rounds_requested=rounds,
        rounds_planned=rounds,
        lineup=tuple(s.name for s in lineup),
        balance=count_balance(rows, compared_pairs(lineup)),
        launches=len(rows),
    )


def _k3() -> tuple[bool, str]:
    two = [Side(name="new", kind="rows"), Side(name="old", kind="rows", role="baseline")]
    three = [*two, two[1].twin()]
    two_names = [s.name for s in two]
    three_names = [s.name for s in three]
    return _expect(
        (
            "two entries",
            [("new", "old"), ("old", "new"), ("old", "new"), ("new", "old")],
            [rotate_reverse(two_names, r) for r in range(1, 5)],
        ),
        (
            "three entries",
            [
                ("new", "old", "old~same"),
                ("old", "old~same", "new"),
                ("old~same", "new", "old"),
                ("old~same", "old", "new"),
                ("new", "old~same", "old"),
                ("old", "new", "old~same"),
            ],
            [rotate_reverse(three_names, r) for r in range(1, 7)],
        ),
        ("two entries balanced at 2", True, _plan(two, 2).is_balanced()),
        ("two entries balanced at 1", False, _plan(two, 1).is_balanced()),
        ("three entries balanced at 6", True, _plan(three, 6).is_balanced()),
        ("three entries balanced at 5", False, _plan(three, 5).is_balanced()),
    )


def _k4() -> tuple[bool, str]:
    known = {1: 6, 2: 7, 4: 8, 10: 9, 35: 11, 100: 12}
    return _expect(*((f"min_rounds({m})", n, min_rounds(m)) for m, n in known.items()))


def _c1() -> tuple[bool, str]:
    got = _first(_analyse(synthetic_capture(_known_difference)))
    return _expect(
        ("ratio", 2.0, got.ratio),
        ("ratio as written", "2.000x", f"{got.ratio:.3f}x" if got.ratio is not None else None),
        ("verdict", "SLOWER", got.verdict),
        ("outcome", "worse", got.outcome),
    )


def _c2() -> tuple[bool, str]:
    noisy = _first(_analyse(synthetic_capture(_noisy({"new": 1.0, "old": 1.0}, 0.02), seed=3)))
    flat = _first(
        _analyse(
            synthetic_capture(
                _exact(dict.fromkeys(("new", "new~same", "old", "old~same"), lambda r: 1.0))
            )
        )
    )
    return _expect(
        ("identical sides with noise", "tie", noisy.outcome),
        ("identical values", "no_verdict", flat.outcome),
        ("reason of identical values", "zero_floor", flat.reason),
    )


def _c3() -> tuple[bool, str]:
    capture = synthetic_capture(_known_difference)
    swapped = _first(_analyse(capture, baseline="new"), subject="old")
    return _expect(
        ("ratio swapped", 0.5, swapped.ratio),
        ("verdict swapped", "FASTER", swapped.verdict),
        ("subject swapped", "old", swapped.subject),
        ("baseline swapped", "new", swapped.baseline),
    )


def _c4() -> tuple[bool, str]:
    rows = [1.0, 1.0, 1.0, 2.0, 2.0, 2.0]
    six = synthetic_capture(
        _exact({"new": lambda r: rows[r - 1], "old": lambda r: 2.0}),
        rounds=6,
        twinned=(),
    )
    nine = synthetic_capture(
        _exact({"new": lambda r: 2.0, "old": lambda r: 2.0}), rounds=9, twinned=()
    )
    three = _first(_analyse(six))
    ties = _first(_analyse(nine))
    return _expect(
        ("untied of three lower and three ties", 3, three.n_untied),
        ("p of three lower and three ties", 0.25, three.p_raw),
        ("p of nine ties", 1.0, ties.p_raw),
    )


def _c5() -> tuple[bool, str]:
    value = _noisy({"new": 1.0, "old": 2.0}, 0.02)
    a = synthetic_capture(value, seed=11, capture_id="synthetic-a")
    b = synthetic_capture(value, seed=12, capture_id="synthetic-b")
    pooled = _first(_analyse([a, b]))
    same_file = dataclasses.replace(b, source=a.source)
    copied = dataclasses.replace(
        a,
        capture_id="synthetic-c",
        header=dataclasses.replace(a.header, capture_id="synthetic-c"),
        source=None,
    )
    truncated = dataclasses.replace(copied, observations=a.observations[:-3])
    return _expect(
        ("paired rounds of two captures", 32, pooled.n_rounds),
        ("the same file twice", "E_POOL_SAME", _code(lambda: _analyse([a, same_file]))),
        ("identical rows", "E_POOL_IDENTICAL_ROWS", _code(lambda: _analyse([a, copied]))),
        ("a truncated copy", "E_POOL_TRUNCATED_COPY", _code(lambda: _analyse([a, truncated]))),
    )


def _c6() -> tuple[bool, str]:
    capture = synthetic_capture(_noisy({"new": 1.0, "old": 2.0}, 0.02), order="fixed")
    return _expect(
        ("an order that never changes", "E_ORDER_NOT_VARIED", _code(lambda: _analyse(capture)))
    )


def _c7() -> tuple[bool, str]:
    value = _noisy({"new": 1.0, "old": 2.0}, 0.02)
    one = _first(_analyse(synthetic_capture(value, twinned=("old",))))
    none = _first(_analyse(synthetic_capture(value, twinned=())))
    return _expect(
        ("one twin missing", ("no_verdict", "one_sided_floor"), (one.outcome, one.reason)),
        ("both twins missing", ("no_verdict", "no_floor"), (none.outcome, none.reason)),
    )


def _eighteen_of_24(entry: str, case: str, round_: int, u: float) -> float:
    side = entry.split("~")[0]
    base = 2.0 if side == "old" else (1.0 if round_ <= 18 else 2.125)
    return base * (1.0 + 0.002 * (2.0 * u - 1.0)) if entry.endswith("~same") else base


def _c8() -> tuple[bool, str]:
    four = tuple(Case(id=f"case{i}", metric="time", unit="s", kind="time") for i in range(4))
    alone = _first(_analyse(synthetic_capture(_eighteen_of_24, rounds=24)))
    among = _analyse(synthetic_capture(_eighteen_of_24, rounds=24, cases=four))
    outcomes = sorted({(c.outcome, c.reason) for c in among.comparisons})
    return _expect(
        ("18 of 24 alone", "better", alone.outcome),
        ("18 of 24 among four cases", [("unresolved", "not_significant")], outcomes),
    )


def _c9() -> tuple[bool, str]:
    def value(entry: str, case: str, round_: int, u: float) -> float:
        side = 0.99 if entry.startswith("new") else 1.0
        return side * 1.0625 if entry.endswith("~same") else side

    got = _first(_analyse(synthetic_capture(value)))
    return _expect(
        (
            "significant and inside the bar",
            ("unresolved", "inside_noise"),
            (got.outcome, got.reason),
        )
    )


def _c10() -> tuple[bool, str]:
    capture = synthetic_capture(_noisy({"new": 1.0, "old": 2.0}, 0.02))
    gone = next(x for x in capture.launches if x.round == 3 and x.name == "old")
    twice = next(x for x in capture.launches if x.round == 5 and x.name == "new")
    broken = dataclasses.replace(
        capture,
        launches=(
            *(x for x in capture.launches if x is not gone),
            dataclasses.replace(twice, seq=999),
        ),
        observations=tuple(o for o in capture.observations if o.seq != gone.seq),
    )
    try:
        _analyse(broken)
    except Refusal as refusal:
        return _expect(
            ("code", "E_GRID", refusal.code),
            ("missing", [[3, "old"]], refusal.detail.get("missing")),
            ("duplicated", [[5, "new"]], refusal.detail.get("duplicated")),
        )
    return False, "expected E_GRID, the analysis was not refused"


def _c11() -> tuple[bool, str]:
    capture = synthetic_capture(_noisy({"new": 1.0, "old": 2.0}, 0.02))
    drifted = dataclasses.replace(
        capture,
        sides=tuple(
            dataclasses.replace(s, fingerprint=_fingerprint("other")) if s.name == "old~same" else s
            for s in capture.sides
        ),
    )
    orphan = dataclasses.replace(
        capture,
        sides=tuple(
            dataclasses.replace(s, twin_of="gone") if s.name == "old~same" else s
            for s in capture.sides
        ),
    )
    drift_exit: int | None = None
    try:
        _analyse(drifted)
    except Refusal as refusal:
        drift_exit = refusal.exit_code if refusal.code == "E_TWIN_DRIFT" else None
    return _expect(
        ("twin drift", "E_TWIN_DRIFT", _code(lambda: _analyse(drifted))),
        ("exit code of twin drift found in analysis", 6, drift_exit),
        ("an orphan twin", "E_TWIN_ORPHAN", _code(lambda: _analyse(orphan))),
    )


def _thirteen_of_16(entry: str, case: str, round_: int, u: float) -> float:
    side = entry.split("~")[0]
    base = 2.0 if side == "old" else (1.0 if round_ <= 13 else 2.125)
    return base * 1.0625 if entry.endswith("~same") else base


def _c12() -> tuple[bool, str]:
    value = _noisy({"new": 1.0, "old": 2.0}, 0.02)
    marked = synthetic_capture(value, disturbed=(2, 5))
    altered = dataclasses.replace(
        marked,
        observations=tuple(
            dataclasses.replace(o, value=o.value * 3.0) for o in marked.observations
        ),
    )
    first, second = marked.set_aside(), altered.set_aside()
    few = _first(_analyse(synthetic_capture(value, rounds=8, disturbed=(1, 2, 3))))
    many = _analyse(synthetic_capture(value, disturbed=tuple(range(1, 10))))
    shaky = _first(_analyse(synthetic_capture(_thirteen_of_16, disturbed=(1, 2))))
    return _expect(
        ("rounds set aside", (2, 5), first.rounds if first else None),
        ("same decision with altered values", True, first == second),
        ("too few rounds remain", "too_few_rounds", few.sensitivity.not_computed),
        ("too large a share", "too_many_disturbed", _first(many).sensitivity.not_computed),
        ("machine state with too large a share", "busy", many.machine_state.status),
        (
            "a disagreement",
            ("unresolved", "sensitive_to_disturbed_rounds"),
            (shaky.outcome, shaky.reason),
        ),
    )


def _c13() -> tuple[bool, str]:
    other = Case(id="other", metric="other", unit="s", kind="time", primary=False)
    twin_value = {
        ("new", "matmul"): 1.5,
        ("old", "matmul"): 2.0,
        ("new", "other"): 1.0,
        ("old", "other"): 1.0,
    }
    side_factor = {
        ("new", "matmul"): 1.0625,
        ("old", "matmul"): 1.0625,
        ("new", "other"): 1.5,
        ("old", "other"): 1.0625,
    }

    def value(entry: str, case: str, round_: int, u: float) -> float:
        side = entry.split("~")[0]
        twin = twin_value[(side, case)]
        return twin if entry.endswith("~same") else twin * side_factor[(side, case)]

    capture = synthetic_capture(value, cases=(MATMUL, other))
    rules = [
        STRICT,
        Rule("experiment-bar", bar="twice_experiment_max"),
        Rule("experiment-bar-tie", bar="twice_experiment_max", tie="inside"),
    ]
    outcomes = [_first(_analyse(capture, rule=rule)).outcome for rule in rules]
    return _expect(("outcomes under three rules", ["better", "unresolved", "tie"], outcomes))


def _c14() -> tuple[bool, str]:
    return _expect(
        (
            "energy of 10, 20, 30 W over one second",
            20.0,
            trapezoid([0.0, 0.5, 1.0], [10.0, 20.0, 30.0]),
        )
    )


def _c15() -> tuple[bool, str]:
    work = _noisy({"new": 1.0, "old": 2.0}, 0.02)

    def two_units(entry: str, case: str, round_: int, u: float) -> float:
        return 2.0 if entry.startswith("old") else work(entry, case, round_, u)

    def twice(entry: str, case: str, round_: int, u: float) -> float:
        return 4.0

    def with_cost(entry: str, case: str, round_: int, u: float) -> float:
        return 3.0

    def mixed(entry: str, case: str, round_: int, u: float) -> float:
        return 4.0 if round_ <= 13 else 1.0

    ok = _analyse(synthetic_capture(two_units, rounds=20, control=twice))
    cost = _analyse(synthetic_capture(two_units, rounds=20, control=with_cost))
    split = _analyse(synthetic_capture(two_units, rounds=20, control=mixed))
    split_row = split.controls.positive.cases[0] if split.controls.positive.cases else None
    return _expect(
        ("2.0x in every round", "ok", ok.controls.positive.status),
        ("1.5x in every round", "failed", cost.controls.positive.status),
        (
            "every comparison of that run",
            {("no_verdict", "positive_control_failed")},
            {(c.outcome, c.reason) for c in cost.comparisons},
        ),
        ("13 at 2.0x and 7 at 0.5x", "failed", split.controls.positive.status),
        ("its median ratio", 2.0, split_row.ratio if split_row else None),
        ("its p-value", 275960 / 1048576, split_row.p_raw if split_row else None),
    )


def _c16() -> tuple[bool, str]:
    cores = resource_case("res/cores")

    def value(entry: str, case: str, round_: int, u: float) -> float:
        base = (4.0 if entry.startswith("new") else 1.0) if case == "res/cores" else 1.0
        return base * (1.0 + 0.02 * u)

    got = _analyse(synthetic_capture(value, cases=(MATMUL, cores)))
    row = _first(got, "res/cores")
    refused = _code(lambda: Case(id="x", metric="x", unit="x", better="none", primary=True))
    return _expect(
        ("outcome", "higher", row.outcome),
        ("verdict", "HIGHER", row.verdict),
        ("as a primary case", "E_USAGE", refused),
    )


def _c17() -> tuple[bool, str]:
    cost = LaunchCost(
        command="true", n=20, median_s=0.0005, p25_s=0.0004, p75_s=0.0007, min_s=0.0003
    )

    def value(entry: str, case: str, round_: int, u: float) -> float:
        return 0.04 if entry.startswith("new") else 0.06

    got = _analyse(synthetic_capture(value, cases=(WALL,), twinned=(), launch_cost=cost))
    noted = [n.message for n in got.notes if n.code == "launch_cost_share"]
    return _expect(
        ("0.04 s against a cost of 0.0005 s", True, launch_cost_note(0.04, 0.0005)),
        ("0.06 s against a cost of 0.0005 s", False, launch_cost_note(0.06, 0.0005)),
        ("notes in the results", 1, len(noted)),
        ("the side noted", True, bool(noted) and "of new," in noted[0]),
    )


CONTROLS: tuple[tuple[str, str, Callable[[], tuple[bool, str]]], ...] = (
    ("K1", "sign-test known answers; 5 against 0 cannot give a verdict", _k1),
    ("K2", "the four Holm known answers", _k2),
    ("K3", "the schedule for two and three entries and when it balances", _k3),
    ("K4", "min_rounds for 1, 2, 4, 10, 35 and 100 cases", _k4),
    ("C1", "a known 2.0x difference reads 2.000x and the right word", _c1),
    ("C2", "identical sides read TIE; identical values give zero_floor", _c2),
    ("C3", "swapping subject and baseline inverts the ratio and flips the word", _c3),
    ("C4", "ties are no trials", _c4),
    ("C5", "pooling keeps all pairs and refuses copies", _c5),
    ("C6", "an order that never changes is refused", _c6),
    ("C7", "a missing twin gives NO VERDICT with the right reason", _c7),
    ("C8", "18 of 24 is a verdict alone and UNRESOLVED among four cases", _c8),
    ("C9", "significant but inside the bar is UNRESOLVED, never TIE", _c9),
    ("C10", "a missing and a duplicated cell are refused and listed", _c10),
    ("C11", "twin drift and an orphan twin are refused", _c11),
    ("C12", "setting disturbed rounds aside", _c12),
    ("C13", "one experiment under three rules gives three outcomes", _c13),
    ("C14", "power samples integrate to energy", _c14),
    ("C15", "the positive control", _c15),
    ("C16", "a case that describes reads HIGHER or LOWER and is never primary", _c16),
    ("C17", "the launch-cost note", _c17),
)


def run_control(control_id: str) -> ControlResult:
    """Run one control by its id. A control that raises is reported as failed."""
    for ident, title, check in CONTROLS:
        if ident == control_id:
            try:
                passed, detail = check()
            except Exception as exc:
                passed, detail = False, f"raised {type(exc).__name__}: {exc}"
            return ControlResult(id=ident, title=title, passed=passed, detail=detail)
    raise KeyError(control_id)


def run_selftest() -> list[ControlResult]:
    """Run every control, in the order of ``CONTROLS``. Never raises for a failed control."""
    return [run_control(ident) for ident, _title, _check in CONTROLS]
