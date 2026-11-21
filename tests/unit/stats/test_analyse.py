# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Analysis of captures into the results document, and the document of a refused analysis.

Captures come from the seeded generator of the self-test. Values are chosen so
that the expected numbers are exact.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest

import pairbench
from pairbench.errors import Refusal
from pairbench.model import (
    NOTE_TWIN_DIFFERS,
    NOTE_WITNESS_UNDECIDED,
    STRICT,
    Capture,
    Case,
    ControlCase,
    CpuRecord,
    End,
    EnvPad,
    Floors,
    GateRecord,
    LaunchCost,
    MachineSummary,
    Note,
    PlanSummary,
    PositiveControl,
    Results,
    Rule,
    SameVsSame,
    Side,
    Source,
    TwinCheck,
    combine_hashes,
)
from pairbench.results import load_schema
from pairbench.stats.analyse import analyse_captures, refused
from pairbench.stats.selftest import MATMUL, synthetic_capture

R16 = 16


def shared(round_: int) -> float:
    return 1.0 + round_ / 64


def known(entry: str, case: str, round_: int, u: float) -> float:
    """``new`` reads twice ``old``; a twin is 1 percent above and below its side in turn."""
    side = 2.0 * shared(round_) if entry.startswith("new") else shared(round_)
    if entry.endswith("~same"):
        return side * (1.01 if round_ % 2 else 0.99)
    return side


def twice(entry: str, case: str, round_: int, u: float) -> float:
    return 2.0 * shared(round_)


def jittered(entry: str, case: str, round_: int, u: float) -> float:
    """``known`` with a small seeded jitter, so that captures of two seeds differ."""
    return known(entry, case, round_, u) * (1.0 + u / 1000)


def analyse(captures: Capture | Sequence[Capture], **options: Any) -> Results:
    given = (captures,) if isinstance(captures, Capture) else tuple(captures)
    rule = options.pop("rule", STRICT)
    return analyse_captures(given, rule=rule, **options)


def refusal_of(make: Callable[[], Any]) -> Refusal:
    with pytest.raises(Refusal) as caught:
        make()
    return caught.value


def code_of(make: Callable[[], Any]) -> tuple[str, int]:
    """The text code and the exit code of the refusal ``make`` raises."""
    caught = refusal_of(make)
    return caught.code, caught.exit_code


def capture(**options: Any) -> Capture:
    options.setdefault("capture_id", "synthetic-doc")
    return synthetic_capture(options.pop("value", known), **options)


def replace_sides(cap: Capture, name: str, **changes: Any) -> Capture:
    sides = tuple(dataclasses.replace(s, **changes) if s.name == name else s for s in cap.sides)
    return dataclasses.replace(cap, sides=sides)


# ---------------------------------------------------------------------------
# The whole document
# ---------------------------------------------------------------------------


def test_the_whole_document_of_one_capture() -> None:
    cap = capture(control=twice)
    got = analyse(cap)
    assert got.run.id == "synthetic-doc"
    assert got.run.pooled is False
    assert got.run.command == "pairbench run"
    assert [(c.capture_id, c.rounds) for c in got.run.captures] == [("synthetic-doc", 16)]
    assert cap.source is not None
    assert got.run.captures[0].sha256 == cap.source.sha256
    assert got.rule.name == "strict"
    assert got.rule.fields == STRICT.to_json()
    assert (got.rule.family_size, got.rule.plain) == (1, "one case tested")
    assert got.provenance.machine == MachineSummary(
        os="Linux 0.0", arch="arch-a", cpu_model="cpu-model-a", core_types=("core-type-a",)
    )
    assert got.provenance.seeds == {"driver": 1}
    assert got.provenance.driver is None
    assert [s.name for s in got.sides] == ["new", "new~same", "old", "old~same", "old~twice"]
    assert [s.role for s in got.sides] == ["subject", "twin", "baseline", "twin", "control"]
    assert got.sides[-1].control_of == "old"
    assert got.plan == PlanSummary(
        schedule="rotate-reverse",
        rounds_requested=None,
        rounds_planned=16,
        rounds_completed=16,
        warmups=1,
        launches=82,
        explain_launches=4,
    )
    assert got.machine_state.status == "unknown"
    assert got.machine_state.gates == ()
    decision = cap.set_aside()
    assert decision is not None and got.machine_state.discard_sha256 == decision.sha256
    assert got.cases == (MATMUL,)
    assert got.notes == ()
    assert got.refusals == ()
    assert got.figures == {}
    assert got.energy is None
    assert got.launch_cost is None
    assert got.env_pad == EnvPad(varied=False)
    assert got.plots.status == "off"
    assert got.diagnostics.status == "off"


def test_the_plain_words_name_the_number_of_cases_corrected_for() -> None:
    got = analyse(capture(cases=(MATMUL, Case(id="b", metric="b", unit="s"))))
    assert (got.rule.family_size, got.rule.plain) == (2, "corrected for testing 2 cases at once")


def test_the_plan_takes_the_requested_rounds_from_the_settings() -> None:
    cap = capture()
    cap = dataclasses.replace(
        cap, header=dataclasses.replace(cap.header, config={"run": {"rounds": 12}})
    )
    assert analyse(cap).plan.rounds_requested == 12


def test_the_comparison_of_a_known_difference() -> None:
    c = analyse(capture(control=twice)).comparison("matmul")
    assert (c.subject, c.baseline, c.primary) == ("new", "old", True)
    assert (c.n_rounds, c.n_unpaired, c.n_untied, c.n_lower, c.n_higher) == (16, 0, 16, 0, 16)
    assert (c.ratio, c.statistic, c.scale) == (2.0, 2.0, "ratio")
    assert c.gap == 1.0
    assert (c.p_raw, c.p_raw_fraction, c.p_corrected) == (2 / 65536, (2, 65536), 2 / 65536)
    assert (c.verdict, c.outcome, c.reason, c.reasons) == ("SLOWER", "worse", None, ())
    assert (c.floor.source, c.floor.unit, c.floor.mode) == ("twins", "fraction", "TWO-SIDED")
    assert c.floor.subject is not None and c.floor.subject.n == 16
    assert c.order_split == (8, 8)
    assert c.sensitivity.agrees is True
    assert c.sensitivity.outcome == "worse"
    assert c.sensitivity.rounds_set_aside == ()


def test_the_positive_control_that_reads_twice_the_work_is_ok() -> None:
    got = analyse(capture(control=twice)).controls.positive
    assert got == PositiveControl(
        status="ok",
        entry="old~twice",
        via="repeat",
        tolerance=0.1,
        cases=(
            ControlCase(
                case="matmul", expected=2.0, ratio=2.0, p_raw=2 / 65536, n_rounds=16, passed=True
            ),
        ),
    )


def test_same_against_same_rows_and_series() -> None:
    got = analyse(capture(control=twice))
    assert [(r.side, r.case, r.n, r.unit) for r in got.same_vs_same] == [
        ("new", "matmul", 16, "fraction"),
        ("old", "matmul", 16, "fraction"),
    ]
    assert [r.p_raw for r in got.same_vs_same] == [1.0, 1.0]
    assert [(s.case, s.name) for s in got.series] == [
        ("matmul", "new"),
        ("matmul", "new~same"),
        ("matmul", "old"),
        ("matmul", "old~same"),
    ]
    old = next(s for s in got.series if s.name == "old")
    assert old.values == tuple(1.0 + r / 64 for r in range(1, 17))
    assert old.disturbed_rounds == ()


def test_secondary_cases_have_no_series() -> None:
    other = Case(id="other", metric="other", unit="s", primary=False)
    got = analyse(capture(cases=(MATMUL, other)))
    assert {s.case for s in got.series} == {"matmul"}


def test_a_capture_read_back_from_its_records_analyses_the_same() -> None:
    cap = capture(control=twice)
    again = Capture.from_records(cap.to_records(), source=cap.source)
    assert analyse(again) == analyse(cap)


def test_the_documents_are_valid_against_the_shipped_schema() -> None:
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate a document"
    )
    validator = jsonschema.Draft202012Validator(load_schema("results"))
    analysed = analyse(capture(control=twice, cases=(MATMUL, Case(id="b", metric="b", unit="s"))))
    stopped = refused([capture()], Refusal("E_GRID", "x"), rule=STRICT)
    for document in (analysed.to_json(), stopped.to_json()):
        errors = [e.message for e in validator.iter_errors(json.loads(json.dumps(document)))]
        assert errors == []


# ---------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------


def two() -> tuple[Capture, Capture]:
    return (
        capture(capture_id="synthetic-a", seed=1, value=jittered),
        capture(capture_id="synthetic-b", seed=2, value=jittered),
    )


def test_pooled_captures_keep_every_round_numbered_across_them() -> None:
    a, b = two()
    got = analyse([a, b])
    assert got.run.pooled is True
    assert got.run.id.startswith("pool-") and len(got.run.id) == 17
    assert [c.capture_id for c in got.run.captures] == ["synthetic-a", "synthetic-b"]
    assert (got.plan.rounds_planned, got.plan.rounds_completed, got.plan.launches) == (
        32,
        32,
        132,
    )
    assert got.comparison("matmul").n_rounds == 32
    assert all(len(s.values) == 32 for s in got.series)


def test_disturbed_rounds_of_pooled_captures_are_numbered_across_them() -> None:
    a = capture(capture_id="synthetic-a", value=jittered, disturbed=(2,))
    b = capture(capture_id="synthetic-b", seed=2, value=jittered, disturbed=(3,))
    got = analyse([a, b])
    assert got.series[0].disturbed_rounds == (2, 19)
    assert got.comparison("matmul").sensitivity.rounds_set_aside == (2, 19)
    da, db = a.set_aside(), b.set_aside()
    assert da is not None and db is not None
    assert got.machine_state.discard_sha256 == combine_hashes([da.sha256, db.sha256])


def test_a_side_whose_fingerprint_differs_between_captures_is_refused() -> None:
    a, b = two()
    b = replace_sides(b, "new", fingerprint="0" * 64)
    caught = refusal_of(lambda: analyse([a, b]))
    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.detail["sides"] == ["new"]


def _command_fingerprint(argv: Sequence[str]) -> str:
    """The fingerprint a command side with this argument list gets, made as the kind makes it."""
    from pairbench.model import LaunchSettings, fingerprint_of
    from pairbench.sides.identity import argv_sha256

    identity = {
        "executable": "/made/up/bin/tool",
        "executable_sha256": "ab" * 32,
        "argv_sha256": argv_sha256(argv),
    }
    return fingerprint_of(identity, LaunchSettings().effective(args=argv))


def _with_new_fingerprint(cap: Capture, fingerprint: str) -> Capture:
    for name in ("new", "new~same"):
        cap = replace_sides(cap, name, fingerprint=fingerprint)
    return cap


def test_captures_whose_side_differs_only_in_a_hidden_secret_pool() -> None:
    a, b = two()
    a = _with_new_fingerprint(a, _command_fingerprint(["made-up-tool", "--password", "kiwi7"]))
    b = _with_new_fingerprint(b, _command_fingerprint(["made-up-tool", "--password", "plum4"]))

    got = analyse([a, b])

    assert got.run.pooled is True
    assert [c.capture_id for c in got.run.captures] == ["synthetic-a", "synthetic-b"]


def test_captures_whose_side_differs_in_a_path_are_refused_as_drift() -> None:
    a, b = two()
    a = _with_new_fingerprint(a, _command_fingerprint(["/made/up/one/tool", "--size", "1"]))
    b = _with_new_fingerprint(b, _command_fingerprint(["/made/up/two/tool", "--size", "1"]))

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.detail["sides"] == ["new", "new~same"]


def _text_run(first: str, second: str, values: dict[str, float]) -> str:
    """A text run of 8 rounds over two sides, its first round in the order given."""
    lines = ["## host", "unit=s"]
    for r in range(1, 9):
        order = (first, second) if r % 2 else (second, first)
        lines.append("pass_order=" + " ".join(order))
        lines += [f"a\t{side}\t{r}\tmatmul\t{values[side] + r / 64}" for side in order]
    return "\n".join(lines) + "\n"


POOL_BASELINE_NOTE = (
    "the pooled captures do not name one baseline ({named}); old, the baseline of the "
    "first capture, is the baseline of the pool; name the baseline to choose another"
)


def test_text_captures_whose_rows_name_the_sides_in_another_order_are_pooled(
    tmp_path: Any,
) -> None:
    from pairbench.capture.text import TextReader

    (tmp_path / "a.txt").write_text(_text_run("new", "old", {"new": 1.0, "old": 2.0}))
    (tmp_path / "b.txt").write_text(_text_run("old", "new", {"new": 1.5, "old": 2.5}))
    (a,) = TextReader().read(tmp_path / "a.txt")
    (b,) = TextReader().read(tmp_path / "b.txt")
    assert (a.baseline, b.baseline) == ("old", "new")

    chosen = analyse([a, b], baseline="old")
    assert chosen.notes == ()
    assert (chosen.plan.rounds_completed, chosen.comparison("matmul").n_rounds) == (16, 16)
    assert (chosen.comparisons[0].subject, chosen.comparisons[0].baseline) == ("new", "old")

    default = analyse([a, b])
    assert (default.plan.rounds_completed, default.comparison("matmul").n_rounds) == (16, 16)
    assert (default.comparisons[0].subject, default.comparisons[0].baseline) == ("new", "old")
    named = f"old in {a.capture_id}, new in {b.capture_id}"
    assert [(n.code, n.message) for n in default.notes] == [
        ("pool_baseline", POOL_BASELINE_NOTE.format(named=named))
    ]

    other = analyse([a, b], baseline="new")
    assert (other.comparisons[0].subject, other.comparisons[0].baseline) == ("old", "new")


def test_captures_whose_sides_differ_only_in_role_are_pooled() -> None:
    a, b = two()
    b = dataclasses.replace(
        b,
        sides=tuple(
            s.with_role({"new": "baseline", "old": "subject"}.get(s.name, s.role)) for s in b.sides
        ),
    )
    got = analyse([a, b])
    assert got.comparison("matmul").n_rounds == 32
    assert (got.comparisons[0].subject, got.comparisons[0].baseline) == ("new", "old")
    named = "old in synthetic-a, new in synthetic-b"
    assert [(n.code, n.message) for n in got.notes] == [
        ("pool_baseline", POOL_BASELINE_NOTE.format(named=named))
    ]


def test_captures_with_different_sides_are_refused() -> None:
    a = capture(capture_id="synthetic-a")
    b = capture(capture_id="synthetic-b", subjects=("new", "other"))
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_SIDE_DRIFT", 6)


def test_captures_with_different_cases_are_refused() -> None:
    a = capture(capture_id="synthetic-a", value=jittered)
    b = capture(
        capture_id="synthetic-b",
        seed=2,
        value=jittered,
        cases=(dataclasses.replace(MATMUL, unit="ms"),),
    )
    caught = refusal_of(lambda: analyse([a, b]))
    assert (caught.code, caught.exit_code, caught.detail["cases"]) == (
        "E_POOL_CASES",
        6,
        ["matmul"],
    )


def test_captures_of_different_machines_are_refused_unless_allowed() -> None:
    a, b = two()
    assert b.machine is not None
    other = dataclasses.replace(b.machine, cpu=CpuRecord(model="cpu-model-b"))
    b = dataclasses.replace(b, machine=other)
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_MACHINE", 6)
    got = analyse([a, b], allow_mixed_machines=True)
    assert [n.code for n in got.notes] == ["allow_mixed_machines"]


def test_a_capture_of_one_side_against_its_twins_is_not_pooled_with_a_comparison() -> None:
    alone = capture(capture_id="synthetic-a", subjects=())
    compare = capture(capture_id="synthetic-b")
    assert code_of(lambda: analyse([alone, compare])) == ("E_POOL_MIXED_PURPOSE", 6)
    got = analyse(alone)
    assert got.comparisons == ()
    assert [r.side for r in got.same_vs_same] == ["old"]
    assert got.rule.plain == "no case tested"


def test_two_runs_of_one_file_are_the_same_file_given_twice() -> None:
    a, b = two()
    assert a.source is not None and b.source is not None
    a = dataclasses.replace(a, source=Source(path="runs.txt", sha256="f" * 64))
    b = dataclasses.replace(b, source=Source(path="runs.txt", sha256="f" * 64))
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_SAME", 6)


def test_the_same_path_twice_is_the_same_file_whatever_its_hash() -> None:
    a, b = two()
    a = dataclasses.replace(a, source=Source(path="runs.txt", sha256="e" * 64))
    b = dataclasses.replace(b, source=Source(path="runs.txt", sha256="f" * 64))
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_SAME", 6)


def test_the_same_capture_id_twice_is_refused() -> None:
    a = capture(capture_id="synthetic-a")
    b = dataclasses.replace(capture(capture_id="synthetic-a", seed=9), source=None)
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_SAME", 6)


def test_two_files_with_the_same_bytes_are_the_same_capture() -> None:
    a, b = two()
    a = dataclasses.replace(a, source=Source(path="a.jsonl", sha256="e" * 64))
    b = dataclasses.replace(b, source=Source(path="b.jsonl", sha256="e" * 64))
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_SAME", 6)


def test_two_captures_with_identical_rows_are_refused() -> None:
    a = capture(capture_id="synthetic-a", seed=1)
    b = capture(capture_id="synthetic-b", seed=2)
    assert code_of(lambda: analyse([a, b])) == ("E_POOL_IDENTICAL_ROWS", 6)


def test_a_capture_whose_rows_are_a_stretch_of_another_is_a_truncated_copy() -> None:
    long = capture(capture_id="synthetic-a", rounds=16)
    short = capture(capture_id="synthetic-b", rounds=8)
    first_eight = [o for o in long.observations if o.round <= 8]
    assert [(o.round, o.name, o.value) for o in short.observations] == [
        (o.round, o.name, o.value) for o in first_eight
    ]
    assert code_of(lambda: analyse([long, short])) == ("E_POOL_TRUNCATED_COPY", 6)
    assert code_of(lambda: analyse([short, long])) == ("E_POOL_TRUNCATED_COPY", 6)


def row_value(side: str, i: int) -> float:
    """A made-up value for the ``i``-th round of a side, the same whatever the round is called."""
    return (2.0 if side == "new" else 1.0) * (1.0 + i / 64) * (1.0 + ((i * 7) % 5) / 1000)


def labelled_rows(first: int, count: int = R16) -> list[tuple[int, str, str, float]]:
    return [
        (first + i, side, "matmul", row_value(side, i))
        for i in range(count)
        for side in ("new", "old")
    ]


def from_rows(rows: Sequence[tuple[int, str, str, float]]) -> Capture:
    return Capture.from_rows(rows, sides=["new", "old"])


def test_the_command_shown_hides_what_is_glued_to_an_option() -> None:
    cap = capture()
    argv = (
        "pairbench",
        "run",
        "--",
        "tool",
        "--env=MY_TOKEN=made-up-secret",
        "-eMY_TOKEN=made-up-secret",
        "-I/made/up/project/include",
        "-o/made/up/out.json",
    )
    cap = dataclasses.replace(cap, header=dataclasses.replace(cap.header, argv=argv))
    got = analyse(cap)
    assert got.run.command == (
        "pairbench run -- tool '--env=MY_TOKEN=<hidden>' '-eMY_TOKEN=<hidden>' -Iinclude -oout.json"
    )
    markdown = pairbench.render(got, "markdown")
    assert "made-up-secret" not in markdown and "/made/up" not in markdown


@pytest.mark.parametrize(
    ("pairs", "fraction"), [(14284, [2, 1 << 14284]), (14285, None)], ids=["kept", "too-long"]
)
def test_a_p_value_fraction_too_long_to_write_is_left_out(
    pairs: int, fraction: list[int] | None
) -> None:
    # Every round agrees, so the fraction is 2 / 2**pairs. Its denominator has
    # 4300 decimal digits at 14284 pairs and 4301 at 14285, past what Python
    # turns into decimal text and reads back by default.
    rows = [(r, side, "matmul", value) for r in range(pairs) for side, value in NEW_OLD_VALUES]
    got = analyse(from_rows(rows), floors=Floors(0.0625))
    written = json.loads(pairbench.render(got, "json"))
    assert written["comparisons"][0]["p_raw_fraction"] == fraction
    assert written["comparisons"][0]["p_raw"] == 0.0
    assert written["comparisons"][0]["n_untied"] == pairs


NEW_OLD_VALUES = (("new", 1.0), ("old", 2.0))


def test_rows_whose_rounds_start_above_one_analyse_like_rows_from_one() -> None:
    one = analyse(from_rows(labelled_rows(1)))
    three = analyse(from_rows(labelled_rows(3)))
    assert [c.to_json() for c in three.comparisons] == [c.to_json() for c in one.comparisons]
    assert three.plan.rounds_completed == one.plan.rounds_completed == R16


def test_a_round_no_side_holds_leaves_the_others_to_analyse() -> None:
    rows = [row for row in labelled_rows(1) if row[0] != 9]
    got = analyse(from_rows(rows))
    assert got.plan.rounds_completed == R16 - 1


def test_a_round_one_side_lacks_is_the_only_cell_named() -> None:
    rows = [row for row in labelled_rows(1) if row[:2] != (9, "old")]
    caught = refusal_of(lambda: analyse(from_rows(rows)))
    assert (caught.code, caught.exit_code) == ("E_GRID", 6)
    assert caught.detail["missing"] == [[9, "old"]]
    assert caught.detail["unexpected"] == []
    assert caught.detail["duplicated"] == []


def test_a_round_one_side_lacks_is_named_by_the_label_the_rows_gave_it() -> None:
    # Rows labelled 3 to 18: label 9 is the capture's round 7.
    rows = [row for row in labelled_rows(3) if row[:2] != (9, "old")]
    cap = from_rows(rows)
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_GRID", 6)
    assert caught.message == (
        f"the grid of rounds and lineup entries of the capture {cap.capture_id} does not "
        "match its lineup: missing 9 old"
    )
    assert caught.detail["missing"] == [[9, "old"]]
    assert (caught.detail["unexpected"], caught.detail["duplicated"]) == ([], [])


def test_rows_numbered_from_one_keep_their_round_numbers_in_a_refusal() -> None:
    cap = from_rows([row for row in labelled_rows(1) if row[:2] != (9, "old")])
    assert cap.source is None
    caught = refusal_of(lambda: analyse(cap))
    assert caught.message.endswith("does not match its lineup: missing 9 old")


def test_a_capture_round_with_no_label_keeps_its_number_in_a_refusal() -> None:
    cap = capture()
    gone = next(x for x in cap.launches if x.round == 3 and x.name == "old")
    holed = dataclasses.replace(
        cap,
        launches=tuple(x for x in cap.launches if x is not gone),
        observations=tuple(o for o in cap.observations if o.seq != gone.seq),
    )
    caught = refusal_of(lambda: analyse(holed))
    assert caught.message.endswith("does not match its lineup: missing 3 old")


def torn(rows: Sequence[tuple[int, str, str, float]]) -> list[tuple[int, str, str, float]]:
    """The rows with the value of the last one cut short, as a write cut off would leave it."""
    round_, side, case, value = rows[-1]
    return [*rows[:-1], (round_, side, case, float(str(value)[:1]))]


@pytest.mark.parametrize(
    ("label", "cut"),
    [
        ("a whole copy with its last value torn", slice(0, None)),
        ("the first rows with the last one torn", slice(0, 21)),
        ("a stretch from the middle with the last one torn", slice(8, 20)),
    ],
)
def test_a_copy_whose_last_row_is_torn_is_a_truncated_copy(label: str, cut: slice) -> None:
    rows = labelled_rows(1)
    original = from_rows(rows)
    copy = from_rows(torn(rows[cut]))
    assert code_of(lambda: analyse([original, copy])) == ("E_POOL_TRUNCATED_COPY", 6), label
    assert code_of(lambda: analyse([copy, original])) == ("E_POOL_TRUNCATED_COPY", 6), label


def test_a_stretch_from_the_middle_given_its_own_round_numbers_is_a_truncated_copy() -> None:
    rows = labelled_rows(1)
    original = from_rows(rows)
    middle = from_rows(rows[8:20])
    assert code_of(lambda: analyse([original, middle])) == ("E_POOL_TRUNCATED_COPY", 6)


def test_a_text_capture_cut_at_any_byte_of_its_last_rows_is_never_pooled(tmp_path: Any) -> None:
    from pairbench.capture.text import TextReader

    lines = ["## host"]
    for i in range(R16):
        order = ("new", "old") if i % 2 else ("old", "new")
        lines.append(f"pass_order={' '.join(order)}")
        lines += [f"a\t{side}\t{i + 1}\tmatmul\t{row_value(side, i):.6f}" for side in order]
    text = "\n".join(lines) + "\n"
    whole = tmp_path / "whole.txt"
    whole.write_text(text, encoding="utf-8")
    (original,) = TextReader().read(whole)
    data = text.encode("utf-8")
    start = len("\n".join(lines[:-8]).encode("utf-8")) + 1
    pooled = []
    for end in range(start, len(data)):
        cut = tmp_path / f"cut-{end}.txt"
        cut.write_bytes(data[:end])
        (copy,) = TextReader().read(cut)
        try:
            analyse([original, copy])
        except Refusal as refusal:
            assert refusal.code in ("E_POOL_TRUNCATED_COPY", "E_POOL_IDENTICAL_ROWS"), end
        else:
            pooled.append(end)
    assert pooled == []


# ---------------------------------------------------------------------------
# Refusals of one capture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "end",
    [
        None,
        End(status="failed", rounds_completed=16),
        End(status="interrupted", rounds_completed=16),
    ],
)
def test_an_incomplete_capture_is_refused_unless_allowed(end: End | None) -> None:
    cap = dataclasses.replace(capture(), end=end)
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_CAPTURE_INCOMPLETE", 6)
    got = analyse(cap, allow_incomplete=True)
    assert [n.code for n in got.notes] == ["allow_incomplete"]
    assert got.comparison("matmul").n_rounds == 16


def test_a_torn_last_round_is_left_out_loudly() -> None:
    cap = capture()
    last = max(x.seq for x in cap.launches)
    torn = dataclasses.replace(
        cap,
        end=None,
        launches=tuple(x for x in cap.launches if x.seq != last),
        observations=tuple(o for o in cap.observations if o.seq != last),
    )
    got = analyse(torn, allow_incomplete=True)
    assert [n.code for n in got.notes] == ["allow_incomplete", "torn_round_left_out"]
    assert "round 16" in got.notes[1].message
    assert got.plan.rounds_completed == 15
    assert got.comparison("matmul").n_rounds == 15
    assert all(len(s.values) == 15 for s in got.series)


FFT = Case(id="fft", metric="time", unit="s", kind="time")


def _lost_last_observation(cap: Capture) -> Capture:
    """The capture as a hard kill leaves it: no end record, the last observation not written."""
    return dataclasses.replace(cap, end=None, observations=cap.observations[:-1])


def _assert_round_16_left_out(got: Results) -> None:
    assert [n.code for n in got.notes] == ["allow_incomplete", "torn_round_left_out"]
    assert got.notes[1].message == (
        "round 16 of the capture synthetic-doc is incomplete and was left out"
    )
    assert got.plan.rounds_completed == 15
    assert [(c.capture_id, c.rounds) for c in got.run.captures] == [("synthetic-doc", 15)]
    assert all(c.n_rounds == 15 for c in got.comparisons)
    assert all(len(s.values) == 15 for s in got.series)


def test_a_last_launch_that_lost_its_observation_leaves_its_round_out() -> None:
    got = analyse(_lost_last_observation(capture()), allow_incomplete=True)
    _assert_round_16_left_out(got)


def test_a_last_launch_that_lost_one_of_two_observations_leaves_its_round_out() -> None:
    cap = _lost_last_observation(capture(cases=(MATMUL, FFT)))
    last = max(x.seq for x in cap.launches)
    assert [o.case for o in cap.observations if o.seq == last] == ["matmul"]
    _assert_round_16_left_out(analyse(cap, allow_incomplete=True))


def test_a_capture_file_whose_last_line_is_torn_leaves_its_last_round_out(tmp_path: Any) -> None:
    from pairbench.capture.reader import JsonlReader

    note = Note(code="made_up_note", message="a made-up note written after the last launch")
    records = dataclasses.replace(capture(), end=None, notes=(note,)).to_records()
    text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    path = tmp_path / "capture.jsonl"
    # The note, the last line, is cut short; every launch and observation before it is whole,
    # so only the torn line says that more of the last round may have been lost.
    path.write_text(text[: text.rindex("made-up note")])
    (cap,) = JsonlReader().read(path)
    assert cap.source is not None and cap.source.torn
    assert (cap.capture_id, cap.notes) == ("synthetic-doc", ())
    assert cap.observations == capture().observations
    _assert_round_16_left_out(analyse(cap, allow_incomplete=True))


def test_a_capture_without_an_end_record_keeps_a_last_round_that_is_whole() -> None:
    got = analyse(dataclasses.replace(capture(), end=None), allow_incomplete=True)
    assert [n.code for n in got.notes] == ["allow_incomplete"]
    assert got.plan.rounds_completed == 16
    assert [(c.capture_id, c.rounds) for c in got.run.captures] == [("synthetic-doc", 16)]


UNDECIDED = {"busy_cores": 3.5, "includes_launch": ["busy_cores"]}


@pytest.mark.parametrize(
    "cut",
    [
        lambda cap: _lost_last_observation(cap),
        lambda cap: dataclasses.replace(cap, end=End(status="failed", rounds_completed=15)),
    ],
    ids=["no-end-record", "end-record-counts-15"],
)
def test_undecided_launches_of_a_round_left_out_are_not_counted(
    cut: Callable[[Capture], Capture],
) -> None:
    cap = cut(_image_witness(capture(gates=[QUIET_GATE]), {2, 16}, UNDECIDED))
    got = analyse(cap, allow_incomplete=True)
    assert got.plan.rounds_completed == 15
    assert got.machine_state.undecided_launches == 1
    [entry] = got.machine_state.degraded
    assert entry.message.startswith("the busy-core witness could not judge 1 launch:")
    shown = refused([cap], Refusal("E_LAUNCH_FAILED", "a made-up failure"), rule=STRICT)
    assert shown.plan.rounds_completed == 15
    assert shown.machine_state.undecided_launches == 1


def test_a_machine_undecided_only_in_a_round_left_out_can_be_quiet() -> None:
    cap = _lost_last_observation(_image_witness(capture(gates=[QUIET_GATE]), {16}, UNDECIDED))
    got = analyse(cap, allow_incomplete=True)
    assert got.plan.rounds_completed == 15
    assert got.machine_state.undecided_launches == 0
    assert got.machine_state.status == "quiet"
    assert got.machine_state.degraded == ()
    assert NOTE_WITNESS_UNDECIDED not in [n.code for n in got.notes]


def test_a_failed_launch_in_the_last_round_of_an_incomplete_capture_tears_it() -> None:
    cap = capture()
    last = max(x.seq for x in cap.launches)
    failed = dataclasses.replace(
        cap,
        end=End(status="failed", rounds_completed=15),
        launches=tuple(dataclasses.replace(x, rc=1) if x.seq == last else x for x in cap.launches),
    )
    got = analyse(failed, allow_incomplete=True)
    assert got.plan.rounds_completed == 15


def test_rounds_after_the_last_one_the_end_record_counts_are_left_out_loudly() -> None:
    # The last launch of round 16 kept exit code 0 but has no observations, as
    # when its driver read is refused; the run ended failed after round 15.
    cap = capture()
    last = max(x.seq for x in cap.launches)
    failed = dataclasses.replace(
        cap,
        end=End(status="failed", rounds_completed=15),
        observations=tuple(o for o in cap.observations if o.seq != last),
    )
    got = analyse(failed, allow_incomplete=True)
    assert [n.code for n in got.notes] == ["allow_incomplete", "torn_round_left_out"]
    assert "round 16" in got.notes[1].message
    assert got.plan.rounds_completed == 15
    assert got.comparison("matmul").n_rounds == 15
    assert all(len(s.values) == 15 for s in got.series)


def test_a_round_missing_before_the_last_is_refused_even_when_incomplete() -> None:
    cap = capture()
    gone = next(x for x in cap.launches if x.round == 3 and x.name == "old")
    holed = dataclasses.replace(
        cap, end=None, launches=tuple(x for x in cap.launches if x is not gone)
    )
    caught = refusal_of(lambda: analyse(holed, allow_incomplete=True))
    assert (caught.code, caught.exit_code, caught.detail["missing"]) == ("E_GRID", 6, [[3, "old"]])


def test_a_capture_without_a_lineup_is_refused() -> None:
    cap = dataclasses.replace(capture(), lineup=None)
    assert code_of(lambda: analyse(cap)) == ("E_GRID", 6)


def test_a_lineup_entry_without_a_side_record_is_refused() -> None:
    cap = capture()
    cap = dataclasses.replace(cap, sides=tuple(s for s in cap.sides if s.name != "new~same"))
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_GRID", 6)
    assert caught.detail["no_side_record"] == ["new~same"]


def test_an_observation_of_a_case_no_record_declares_is_refused() -> None:
    cap = capture()
    first = next(o for o in cap.observations if o.round == 1)
    cap = dataclasses.replace(
        cap, observations=(*cap.observations, dataclasses.replace(first, case="ghost"))
    )
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code, caught.detail["cases"]) == ("E_GRID", 6, ["ghost"])


def test_launches_past_the_completed_rounds_are_unexpected() -> None:
    cap = dataclasses.replace(capture(), end=End(status="complete", rounds_completed=15))
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_GRID", 6)
    assert caught.detail["missing"] == []
    assert sorted(caught.detail["unexpected"]) == [
        [16, "new"],
        [16, "new~same"],
        [16, "old"],
        [16, "old~same"],
    ]


def test_a_twin_whose_side_runs_in_no_lineup_is_an_orphan() -> None:
    cap = capture()
    assert cap.lineup is not None
    names = tuple(n for n in cap.lineup.names if n != "new")
    cap = dataclasses.replace(
        cap,
        lineup=dataclasses.replace(cap.lineup, names=names),
        launches=tuple(x for x in cap.launches if x.name != "new" or x.phase == "warmup"),
        observations=tuple(o for o in cap.observations if o.name != "new"),
    )
    assert code_of(lambda: analyse(cap)) == ("E_TWIN_ORPHAN", 6)


def test_twin_drift_found_in_analysis_exits_with_six() -> None:
    cap = replace_sides(capture(), "new~same", fingerprint="0" * 64)
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_TWIN_DRIFT", 6)


def test_an_order_that_never_changes_is_refused_and_names_the_pair() -> None:
    caught = refusal_of(lambda: analyse(capture(order="fixed")))
    assert (caught.code, caught.exit_code) == ("E_ORDER_NOT_VARIED", 6)
    assert caught.detail["pair"] == ["new", "old"]


def test_a_side_and_its_twin_in_the_same_order_every_round_are_refused() -> None:
    # The side and the baseline swap places each round; each twin runs right after its side.
    def place(round_: int, name: str) -> int:
        first, second = ("new", "old") if round_ % 2 else ("old", "new")
        return [first, f"{first}~same", second, f"{second}~same"].index(name) + 1

    cap = capture()
    cap = dataclasses.replace(
        cap,
        launches=tuple(
            dataclasses.replace(x, pos=place(x.round, x.name)) if x.phase == "round" else x
            for x in cap.launches
        ),
        observations=tuple(
            dataclasses.replace(o, pos=place(o.round, o.name)) for o in cap.observations
        ),
    )
    caught = refusal_of(lambda: analyse(cap))
    assert (caught.code, caught.exit_code) == ("E_ORDER_NOT_VARIED", 6)
    assert caught.detail["pair"] == ["new", "new~same"]


def test_one_round_in_a_fixed_order_is_a_single_measurement_not_a_refusal() -> None:
    got = analyse(capture(order="fixed", rounds=1)).comparison("matmul")
    assert got.reason == "single_measurement"


def test_an_order_not_recorded_is_graded_only_when_interleaving_is_assumed() -> None:
    cap = capture(order="none")
    assert analyse(cap).comparison("matmul").reason == "order_not_recorded"
    got = analyse(cap, assume_interleaved=True)
    assert got.comparison("matmul").outcome == "worse"
    assert [n.code for n in got.notes] == ["assume_interleaved"]


@pytest.mark.parametrize(
    ("call", "code", "exit_code"),
    [
        (lambda c: analyse_captures([], rule=STRICT), "E_USAGE", 2),
        (lambda c: analyse_captures([c], rule="strict"), "E_USAGE", 2),
        (lambda c: analyse_captures([c], rule=STRICT, floors=0.1), "E_USAGE", 2),
        (lambda c: analyse_captures([c], rule=STRICT, baseline="ghost"), "E_USAGE", 2),
        (lambda c: analyse_captures([c], rule=STRICT, baseline="old~same"), "E_USAGE", 2),
    ],
    ids=["no capture", "rule by name", "floors as a number", "unknown baseline", "twin baseline"],
)
def test_an_invalid_call_is_refused_with_e_usage(
    call: Callable[[Capture], Any], code: str, exit_code: int
) -> None:
    caught = refusal_of(lambda: call(capture()))
    assert (caught.code, caught.exit_code) == (code, exit_code)


# ---------------------------------------------------------------------------
# The positive control
# ---------------------------------------------------------------------------


def test_without_a_control_entry_the_control_is_not_run_and_nothing_is_said() -> None:
    got = analyse(capture())
    assert got.controls.positive == PositiveControl(status="not_run")
    assert got.notes == ()


def test_a_control_with_too_few_rounds_is_not_judged_loudly() -> None:
    got = analyse(capture(control=twice, rounds=5))
    assert got.controls.positive.status == "not_run"
    assert got.controls.positive.entry == "old~twice"
    assert [n.code for n in got.notes if n.code.startswith("positive")] == [
        "positive_control_not_judged"
    ]
    assert got.comparison("matmul").reason != "positive_control_failed"


def test_a_control_is_judged_from_six_paired_rounds() -> None:
    got = analyse(capture(control=twice, rounds=6)).controls.positive
    assert (got.status, got.cases[0].n_rounds, got.cases[0].p_raw) == ("ok", 6, 2 / 64)


def test_the_control_is_judged_at_the_alpha_of_the_rule() -> None:
    # Twice the baseline in 13 rounds and half of it in 3: p = 1394/65536.
    def mostly_twice(entry: str, case: str, round_: int, u: float) -> float:
        return (0.5 if round_ <= 3 else 2.0) * shared(round_)

    cap = capture(control=mostly_twice)
    assert analyse(cap).controls.positive.status == "ok"
    tight = analyse(cap, rule=Rule("tight", alpha=0.01)).controls.positive
    assert tight.status == "failed"
    assert (tight.cases[0].ratio, tight.cases[0].p_raw) == (2.0, 1394 / 65536)


def test_the_control_of_a_higher_is_better_case_expects_half_the_value() -> None:
    rate = Case(id="rate", metric="rate", unit="1/s", better="higher", kind="rate")

    def half(entry: str, case: str, round_: int, u: float) -> float:
        return 0.5 * shared(round_)

    got = analyse(capture(control=half, cases=(rate,))).controls.positive
    assert got.status == "ok"
    assert [(c.case, c.expected, c.ratio, c.passed) for c in got.cases] == [
        ("rate", 0.5, 0.5, True)
    ]


def test_a_control_of_a_side_that_is_not_the_baseline_is_not_judged() -> None:
    got = analyse(replace_sides(capture(control=twice), "old~twice", control_of="new"))
    assert got.controls.positive.status == "not_run"
    assert got.notes[-1].message == (
        "the positive control was not judged: old~twice is the control of new, "
        "which is not the baseline"
    )


def test_a_second_control_entry_cannot_be_judged() -> None:
    cap = capture(control=twice)
    extra = dataclasses.replace(cap.sides[-1], name="old~again")
    got = analyse(dataclasses.replace(cap, sides=(*cap.sides, extra)))
    assert got.controls.positive.status == "not_run"
    assert "more than one control entry" in got.notes[-1].message


def test_the_control_is_judged_against_its_own_side_whatever_baseline_is_named() -> None:
    got = analyse(capture(control=twice), baseline="new")
    assert got.controls.positive.status == "ok"
    assert got.comparison("matmul", "old").ratio == 0.5


def test_a_primary_case_the_control_did_not_read_fails_the_control() -> None:
    second = Case(id="b", metric="time", unit="s", kind="time")
    cap = capture(control=twice, cases=(MATMUL, second))
    cap = dataclasses.replace(
        cap,
        observations=tuple(
            o for o in cap.observations if not (o.name == "old~twice" and o.case == "b")
        ),
    )
    got = analyse(cap)
    rows = {r.case: r for r in got.controls.positive.cases}
    assert got.controls.positive.status == "failed"
    assert rows["matmul"].passed
    assert (rows["b"].passed, rows["b"].ratio, rows["b"].n_rounds) == (False, None, 0)
    assert {(c.outcome, c.reason) for c in got.comparisons} == {
        ("no_verdict", "positive_control_failed")
    }
    failed = [n for n in got.notes if n.code == "positive_control_failed"]
    assert len(failed) == 1 and "b (too few paired rounds)" in failed[0].message


def test_a_control_value_of_zero_fails_its_case() -> None:
    def zero(entry: str, case: str, round_: int, u: float) -> float:
        return 0.0

    got = analyse(capture(control=zero))
    assert got.controls.positive.status == "failed"
    assert got.controls.positive.cases[0].ratio is None
    (failed,) = [n for n in got.notes if n.code == "positive_control_failed"]
    assert failed.message == (
        "the positive control failed on matmul (a value of zero or less was recorded): twice "
        "the work did not read as twice the measured value, so no difference this run "
        "reports can be trusted and every comparison is NO VERDICT"
    )


def test_a_control_too_far_from_its_baseline_for_a_finite_ratio_says_so() -> None:
    def huge(entry: str, case: str, round_: int, u: float) -> float:
        return 1e300

    def tiny(entry: str, case: str, round_: int, u: float) -> float:
        return known(entry, case, round_, u) * 1e-10

    got = analyse(capture(control=huge, value=tiny))
    assert got.controls.positive.status == "failed"
    assert got.controls.positive.cases[0].ratio is None
    (failed,) = [n for n in got.notes if n.code == "positive_control_failed"]
    assert failed.message.startswith(
        "the positive control failed on matmul (its ratio to the baseline is too large or too "
        "small to be a finite number): twice the work did not read as twice"
    )


def test_pooled_captures_with_one_control_entry_are_judged_over_every_round() -> None:
    a = capture(capture_id="synthetic-a", value=jittered, control=twice)
    b = capture(capture_id="synthetic-b", seed=2, value=jittered, control=twice)
    got = analyse([a, b]).controls.positive
    assert (got.status, got.cases[0].n_rounds) == ("ok", 32)


def test_a_pooled_capture_whose_lineup_names_no_control_entry_is_not_judged() -> None:
    a = capture(capture_id="synthetic-a", value=jittered, control=twice)
    b = capture(capture_id="synthetic-b", seed=2, value=jittered)
    with pytest.raises(Refusal):
        analyse([a, b])
    b_like = dataclasses.replace(b, sides=(*b.sides, a.sides[-1]))
    got = analyse([a, b_like])
    assert got.controls.positive.status == "not_run"
    assert got.notes[-1].message == (
        "the positive control was not judged: a lineup does not name the control entry old~twice"
    )


# ---------------------------------------------------------------------------
# Notes, machine state and the remaining parts
# ---------------------------------------------------------------------------


def test_supplied_floors_are_recorded_with_their_unit() -> None:
    got = analyse(capture(), floors=Floors(0.0625))
    c = got.comparison("matmul")
    assert (c.floor.source, c.floor.unit, c.bar) == ("supplied", "fraction", 0.125)
    assert c.floor.subject is not None and c.floor.subject.n is None
    assert [n.code for n in got.notes] == ["floor_supplied"]
    percent = analyse(capture(), floors=Floors(6.25), rule=Rule("p", scale="percent"))
    pc = percent.comparison("matmul")
    assert (pc.floor.unit, pc.scale, pc.statistic, pc.bar) == ("percent", "percent", 100.0, 12.5)
    assert {r.unit for r in percent.same_vs_same} == {"percent"}


def test_a_floor_from_few_rounds_and_a_one_sided_floor_are_noted() -> None:
    few = analyse(capture(rounds=6))
    assert "floor_provisional" in [n.code for n in few.notes]
    one = analyse(capture(twinned=("old",)), rule=Rule("loose", require_both_floors=False))
    assert [n.code for n in one.notes] == ["floor_one_sided"]
    assert one.comparison("matmul").floor.mode == "ONE-SIDED"


def test_a_side_that_differs_from_its_twin_is_noted() -> None:
    def lopsided(entry: str, case: str, round_: int, u: float) -> float:
        side = 2.0 if entry.startswith("new") else 1.0
        return side * 1.0625 if entry.endswith("~same") else side

    got = analyse(capture(value=lopsided))
    twins = [n for n in got.notes if n.code == "twin_differs"]
    assert [n.message.split(" ")[0] for n in twins] == ["new", "old"]


def lopsided_twins(entry: str, case: str, round_: int, u: float) -> float:
    """Every twin reads 1/16 above its side in every round: p = 2/65536 for each side."""
    side = 2.0 if entry.startswith("new") else 1.0
    return side * 1.0625 if entry.endswith("~same") else side


def twin_check_of(check: TwinCheck) -> tuple[str, int, int, int, float | None, float | None]:
    return (
        check.side,
        check.n_rounds,
        check.n_better,
        check.n_worse,
        check.p_raw,
        check.p_corrected,
    )


# The note of a side that is one of two sides tested; 2 * 2/65536 written to
# three significant digits.
TWIN_NOTE_OF_TWO = (
    "{side} differs from an identical copy of itself more often than chance across its "
    "primary cases (p = 6.1e-05, corrected for testing 2 sides at once): the machine or the "
    "order is biasing the run"
)
TWIN_NOTE_OF_ONE = (
    "new differs from an identical copy of itself more often than chance across its primary "
    "cases (p = 3.05e-05, one side tested): the machine or the order is biasing the run"
)
# 24 rounds better and 8 worse over 32 pooled rounds: 2 * (C(32,0) + ... + C(32,8)) / 2**32.
P_8_OF_32 = 30066346 / 2**32


def test_each_side_gets_one_twin_check_corrected_across_the_sides() -> None:
    got = analyse(capture(value=lopsided_twins))
    assert [twin_check_of(c) for c in got.twin_checks] == [
        ("new", 16, 16, 0, 2 / 65536, 4 / 65536),
        ("old", 16, 16, 0, 2 / 65536, 4 / 65536),
    ]
    assert [(r.side, r.p_raw) for r in got.same_vs_same] == [
        ("new", 2 / 65536),
        ("old", 2 / 65536),
    ]
    document = json.loads(json.dumps(got.to_json()))
    assert document["twin_checks"] == [
        {
            "side": side,
            "n_rounds": 16,
            "n_better": 16,
            "n_worse": 0,
            "p_raw": 2 / 65536,
            "p_corrected": 4 / 65536,
        }
        for side in ("new", "old")
    ]
    assert list(document)[list(document).index("same_vs_same") + 1] == "twin_checks"
    assert Results.from_json(document).twin_checks == got.twin_checks


def test_a_document_written_without_twin_checks_reads_as_holding_none() -> None:
    document = analyse(capture(value=lopsided_twins)).to_json()
    del document["twin_checks"]
    assert Results.from_json(document).twin_checks == ()


def test_a_twin_row_has_no_corrected_p_value() -> None:
    assert [f.name for f in dataclasses.fields(SameVsSame)] == [
        "side",
        "case",
        "ratio",
        "floor",
        "p_raw",
        "n",
        "unit",
    ]
    row = {"side": "new", "case": "matmul", "ratio": 1.0, "floor": 0.0, "p_raw": 1.0, "n": 16}
    assert SameVsSame.from_json(row).to_json() == {**row, "unit": "fraction"}


def test_the_twin_note_names_the_side_its_corrected_p_value_and_how_many_sides_it_covers() -> None:
    got = analyse(capture(value=lopsided_twins))
    assert [n.message for n in got.notes if n.code == NOTE_TWIN_DIFFERS] == [
        TWIN_NOTE_OF_TWO.format(side="new"),
        TWIN_NOTE_OF_TWO.format(side="old"),
    ]
    one = analyse(capture(value=lopsided_twins, twinned=("new",)))
    assert [twin_check_of(c) for c in one.twin_checks] == [("new", 16, 16, 0, 2 / 65536, 2 / 65536)]
    assert [n.message for n in one.notes if n.code == NOTE_TWIN_DIFFERS] == [TWIN_NOTE_OF_ONE]


def twin_of_old_in_round_one(entry: str, case: str, round_: int, u: float) -> float:
    """As lopsided_twins, but the twin of old reads 0 after round 1: no usable value there."""
    if entry == "old~same" and round_ > 1:
        return 0.0
    return lopsided_twins(entry, case, round_, u)


def test_the_twin_note_counts_only_the_sides_that_have_a_p_value() -> None:
    # Old is scored in one round only and has no p-value, so new is the one
    # side tested and its p-value is not corrected.
    got = analyse(capture(value=twin_of_old_in_round_one))
    assert [twin_check_of(c) for c in got.twin_checks] == [
        ("new", 16, 16, 0, 2 / 65536, 2 / 65536),
        ("old", 1, 1, 0, None, None),
    ]
    assert [n.message for n in got.notes if n.code == NOTE_TWIN_DIFFERS] == [TWIN_NOTE_OF_ONE]


def twin_of_new_alike_in_two_rounds(entry: str, case: str, round_: int, u: float) -> float:
    """As lopsided_twins, but the twin of new reads as new in rounds 1 and 2: those rounds tie."""
    if entry == "new~same" and round_ <= 2:
        return 2.0
    return lopsided_twins(entry, case, round_, u)


def test_a_twin_check_counts_its_tied_rounds_among_the_rounds_scored() -> None:
    # New ties its twin in rounds 1 and 2 and leans one way in the other 14:
    # 16 rounds scored, 14 better, none worse, p = 2/16384. Old leans one way
    # in all 16, so its p-value is the smaller and doubles to 4/65536.
    got = analyse(capture(value=twin_of_new_alike_in_two_rounds))
    assert [twin_check_of(c) for c in got.twin_checks] == [
        ("new", 16, 14, 0, 2 / 16384, 2 / 16384),
        ("old", 16, 16, 0, 2 / 65536, 4 / 65536),
    ]
    document = json.loads(json.dumps(got.to_json()))
    assert [(c["side"], c["n_rounds"]) for c in document["twin_checks"]] == [
        ("new", 16),
        ("old", 16),
    ]


def test_pooled_captures_give_one_twin_check_per_side_over_every_round() -> None:
    a = capture(capture_id="synthetic-a", seed=1, value=lopsided_twins)
    b = capture(capture_id="synthetic-b", seed=2, value=known)
    got = analyse([a, b])
    assert got.run.pooled is True
    assert [twin_check_of(c) for c in got.twin_checks] == [
        ("new", 32, 24, 8, P_8_OF_32, 2 * P_8_OF_32),
        ("old", 32, 24, 8, P_8_OF_32, 2 * P_8_OF_32),
    ]
    assert [n.message.split(" ")[0] for n in got.notes if n.code == NOTE_TWIN_DIFFERS] == [
        "new",
        "old",
    ]


def test_the_launch_cost_note_converts_the_unit_and_skips_image_sides() -> None:
    cost = LaunchCost(
        command="true", n=20, median_s=0.0005, p25_s=0.0004, p75_s=0.0007, min_s=0.0003
    )
    wall_ms = Case(id="wall", metric="wall", unit="ms", kind="time")

    def ms(entry: str, case: str, round_: int, u: float) -> float:
        return 40.0 * (1.0 + 0.01 * u) if entry.startswith("new") else 60.0 * (1.0 + 0.01 * u)

    got = analyse(capture(value=ms, cases=(wall_ms,), launch_cost=cost))
    noted = [n.message for n in got.notes if n.code == "launch_cost_share"]
    assert len(noted) == 1 and noted[0].startswith("the median wall time of new,")
    assert got.launch_cost == cost
    images = analyse(capture(value=ms, cases=(wall_ms,), launch_cost=cost, kind="image"))
    assert [n for n in images.notes if n.code == "launch_cost_share"] == []


def test_the_launch_cost_note_follows_the_recorded_share() -> None:
    # A launch cost of 0.5 ms is 1.25 percent of a 40 ms median: above the
    # default share of 0.01, below a recorded share of 0.02.
    cost = LaunchCost(
        command="true", n=20, median_s=0.0005, p25_s=0.0004, p75_s=0.0007, min_s=0.0003
    )
    wall_ms = Case(id="wall", metric="wall", unit="ms", kind="time")

    def ms(entry: str, case: str, round_: int, u: float) -> float:
        return 40.0 if entry.startswith("new") else 60.0

    cap = capture(value=ms, cases=(wall_ms,), launch_cost=cost)
    assert [n.code for n in analyse(cap).notes].count("launch_cost_share") == 1
    shared_more = dataclasses.replace(
        cap, header=dataclasses.replace(cap.header, config={"launch_cost": {"note_share": 0.02}})
    )
    assert "launch_cost_share" not in [n.code for n in analyse(shared_more).notes]


@pytest.mark.parametrize(
    ("statuses", "machine"),
    [
        (("pass",), "quiet"),
        (("pass", "fail"), "busy"),
        (("pass", "degraded"), "unknown"),
        ((), "unknown"),
    ],
)
def test_the_machine_state(statuses: tuple[str, ...], machine: str) -> None:
    gates = [
        GateRecord(name="quiet", mode="warn", status=s, detail={"message": "busy at /proc/x"})
        for s in statuses
    ]
    got = analyse(capture(gates=gates))
    assert got.machine_state.status == machine
    assert [g.status for g in got.machine_state.gates] == list(statuses)
    assert [d.message for d in got.machine_state.degraded] == [
        "busy at x" for s in statuses if s != "pass"
    ]


def _image_witness(cap: Capture, rounds: set[int], witness: dict[str, Any]) -> Capture:
    """The capture with the given witness on the launches of ``new`` in the given rounds."""
    launches = tuple(
        dataclasses.replace(x, witness=witness)
        if x.phase == "round" and x.round in rounds and x.name == "new"
        else x
        for x in cap.launches
    )
    return dataclasses.replace(cap, launches=launches)


QUIET_GATE = GateRecord(name="quiet", mode="warn", status="pass")


def test_an_image_launch_over_the_threshold_is_undecided_and_keeps_its_round() -> None:
    # The launch reports no CPU time of its own: its busy cores count it in.
    over = {"busy_cores": 3.5, "includes_launch": ["busy_cores"]}
    got = analyse(_image_witness(capture(gates=[QUIET_GATE]), {2, 5}, over))
    assert got.machine_state.undecided_launches == 2
    assert got.machine_state.status == "unknown"
    assert got.series[0].disturbed_rounds == ()
    assert got.comparison("matmul").sensitivity.rounds_set_aside == ()
    [entry] = got.machine_state.degraded
    assert (entry.name, entry.status) == ("cpus", "degraded")
    assert entry.message == (
        "the busy-core witness could not judge 2 launches: a side that reports no CPU time "
        "of its own was counted with its own load in; pin a CPU set with --cpus for the "
        "full witness"
    )
    assert [n.code for n in got.notes].count(NOTE_WITNESS_UNDECIDED) == 1


UNDECIDED_NOTE = (
    "the busy-core witness could not judge 2 launches: the side reports no CPU time of its "
    "own, and the busy cores counted with its own load in were above the threshold; the "
    "launches do not mark their rounds as disturbed, and the machine state is not quiet"
)


def test_the_undecided_note_stays_true_when_another_launch_disturbs_the_round() -> None:
    over = {"busy_cores": 3.5, "includes_launch": ["busy_cores"]}
    cap = _image_witness(capture(gates=[QUIET_GATE]), {2, 5}, over)
    launches = tuple(
        dataclasses.replace(x, witness={"busy_cores": 3.5})
        if x.phase == "round" and x.round == 2 and x.name == "old"
        else x
        for x in cap.launches
    )
    got = analyse(dataclasses.replace(cap, launches=launches))
    assert got.series[0].disturbed_rounds == (2,)
    assert got.machine_state.undecided_launches == 2
    [note] = [n for n in got.notes if n.code == NOTE_WITNESS_UNDECIDED]
    assert note.message == UNDECIDED_NOTE
    assert "kept" not in note.message


def test_a_run_s_own_undecided_note_is_not_given_twice() -> None:
    over = {"busy_cores": 3.5, "includes_launch": ["busy_cores"]}
    cap = _image_witness(capture(gates=[QUIET_GATE]), {2, 5}, over)
    written = Note(code=NOTE_WITNESS_UNDECIDED, message="the run's own note")
    got = analyse(dataclasses.replace(cap, notes=(*cap.notes, written)))
    assert [n for n in got.notes if n.code == NOTE_WITNESS_UNDECIDED] == [written]
    assert got.machine_state.undecided_launches == 2


def test_an_undecided_launch_does_not_hide_a_busy_machine() -> None:
    over = {"busy_cores": 3.5, "includes_launch": ["busy_cores"]}
    failed = GateRecord(name="quiet", mode="warn", status="fail")
    got = analyse(_image_witness(capture(gates=[failed]), {2}, over))
    assert got.machine_state.status == "busy"
    assert got.machine_state.undecided_launches == 1


def test_an_image_launch_under_the_threshold_leaves_the_machine_state_as_it_was() -> None:
    under = {"busy_cores": 1.5, "includes_launch": ["busy_cores"]}
    got = analyse(_image_witness(capture(gates=[QUIET_GATE]), {2, 5}, under))
    assert got.machine_state.status == "quiet"
    assert got.machine_state.undecided_launches == 0
    assert got.machine_state.degraded == ()
    assert NOTE_WITNESS_UNDECIDED not in [n.code for n in got.notes]
    assert got.series[0].disturbed_rounds == ()


def test_more_than_half_the_rounds_disturbed_makes_the_machine_busy() -> None:
    got = analyse(capture(disturbed=tuple(range(1, 10))))
    assert got.machine_state.status == "busy"
    assert got.series[0].disturbed_rounds == tuple(range(1, 10))


def test_energy_is_described_when_a_launch_recorded_some() -> None:
    cap = capture()
    first = next(x for x in cap.launches if x.phase == "round")
    cap = dataclasses.replace(
        cap,
        launches=tuple(
            dataclasses.replace(x, energy={"joules": 1.0}) if x is first else x
            for x in cap.launches
        ),
    )
    got = analyse(cap)
    assert got.energy is not None and got.energy.scope == "gpu"
    assert "energy" in got.to_json()


def test_the_notes_of_the_capture_come_first_with_paths_cut() -> None:
    cap = dataclasses.replace(
        capture(), notes=(Note(code="malformed_rows", message="2 rows skipped in /tmp/a/b.txt"),)
    )
    got = analyse(cap, floors=Floors(0.0625))
    assert [n.code for n in got.notes] == ["malformed_rows", "floor_supplied"]
    assert got.notes[0].message == "2 rows skipped in b.txt"


# ---------------------------------------------------------------------------
# Values too far apart for a ratio to be a finite number
# ---------------------------------------------------------------------------

FAR = Case(id="x", metric="x", unit="s", kind="time")
NEAR = Case(id="y", metric="y", unit="s", kind="time")


def far_apart_rows(new_x: float, old_x: float) -> list[tuple[int, str, str, float]]:
    rows: list[tuple[int, str, str, float]] = []
    for r in range(1, 17):
        rows += [(r, "new", "x", new_x), (r, "old", "x", old_x)]
        rows += [(r, "new", "y", 2.0), (r, "old", "y", 1.0)]
    return rows


def by_case(results: Results, case: str) -> Any:
    return next(c for c in results.comparisons if c.case == case)


def test_medians_too_far_apart_for_a_finite_ratio_give_no_verdict_and_judge_the_rest() -> None:
    far = pairbench.analyse(
        Capture.from_rows(far_apart_rows(1e300, 1e-10), sides=["new", "old"]), baseline="old"
    )
    usual = pairbench.analyse(
        Capture.from_rows(far_apart_rows(2.0, 1.0), sides=["new", "old"]), baseline="old"
    )
    x = by_case(far, "x")
    assert (x.verdict, x.outcome, x.reason) == ("NO VERDICT", "no_verdict", "too_far_apart")
    assert x.reasons == ("too_far_apart", "order_not_recorded", "no_floor")
    assert (x.subject_median, x.baseline_median) == (1e300, 1e-10)
    assert (x.ratio, x.statistic, x.gap, x.bar) == (None, None, None, None)
    assert x.sensitivity.ratio is None
    assert (x.n_higher, x.p_raw) == (16, by_case(usual, "x").p_raw)
    assert by_case(far, "y") == by_case(usual, "y")
    assert far.rule.family_size == usual.rule.family_size == 2


def test_a_percent_difference_too_large_to_be_finite_gives_no_verdict() -> None:
    percent = Rule("made-up-percent", scale="percent")
    got = pairbench.analyse(
        Capture.from_rows(far_apart_rows(1e307, 1.0), sides=["new", "old"]), rule=percent
    )
    x = by_case(got, "x")
    assert x.reason == "too_far_apart"
    assert (x.ratio, x.statistic, x.gap) == (None, None, None)
    shown = {k.rsplit(".", 1)[1] for k in got.figures if k.startswith("x.new_vs_old.")}
    assert RATIO_FIGURES.isdisjoint(shown)


def test_a_percent_scale_keeps_its_finite_statistic_when_the_ratio_has_no_finite_inverse() -> None:
    percent = Rule("made-up-percent", scale="percent")
    # The ratio 1e-310 has no finite inverse; the percent difference is -100.
    got = pairbench.analyse(
        Capture.from_rows(far_apart_rows(1e-10, 1e300), sides=["new", "old"]), rule=percent
    )
    x = by_case(got, "x")
    assert (x.outcome, x.reason, x.ratio) == ("no_verdict", "too_far_apart", None)
    assert (x.statistic, x.gap) == (-100.0, 100.0)
    assert got.figures["x.new_vs_old.statistic"].text == "-100.0%"
    assert "x.new_vs_old.speedup" not in got.figures


def ratio_pair(new_x: float, old_x: float) -> Callable[[str, str, int, float], float]:
    """On case x, ``new`` reads ``new_x`` and ``old`` reads ``old_x``.

    A twin sits 1 percent below its side in odd rounds and on it in even
    rounds, so no twin value is larger than its side and none overflows.
    Case y reads as ``known`` does.
    """

    def value(entry: str, case: str, round_: int, u: float) -> float:
        if case != "x":
            return known(entry, case, round_, u)
        side = new_x if entry.startswith("new") else old_x
        return side * 0.99 if entry.endswith("~same") and round_ % 2 else side

    return value


# A ratio that is a finite number but whose speed-up (1 / ratio) or percent
# (100 * (ratio - 1)) is not, and a ratio that underflows to zero.
RATIOS_WITHOUT_FINITE_FIGURES = [
    pytest.param(1.0, 1.7976931348623157e308, id="speedup-of-a-tiny-ratio-overflows"),
    pytest.param(1e307, 1.0, id="percent-of-a-huge-ratio-overflows"),
    pytest.param(5e-324, 1.0, id="speedup-of-the-smallest-number-overflows"),
    pytest.param(1e-30, 1e300, id="ratio-underflows-to-zero"),
]
# The names of the figures a comparison has only when its ratio is usable.
RATIO_FIGURES = frozenset({"ratio", "statistic", "speedup", "percent"})


@pytest.mark.parametrize(("new_x", "old_x"), RATIOS_WITHOUT_FINITE_FIGURES)
def test_a_ratio_whose_speedup_or_percent_is_no_finite_number_gives_no_verdict(
    new_x: float, old_x: float
) -> None:
    far = pairbench.analyse(capture(value=ratio_pair(new_x, old_x), cases=(FAR, NEAR)))
    usual = pairbench.analyse(capture(cases=(FAR, NEAR)))
    x = by_case(far, "x")
    assert (x.verdict, x.outcome, x.reason) == ("NO VERDICT", "no_verdict", "too_far_apart")
    assert "too_far_apart" in x.reasons
    assert (x.ratio, x.statistic, x.gap) == (None, None, None)
    assert (x.n_rounds, x.p_raw) == (R16, by_case(usual, "x").p_raw)
    shown = {k.rsplit(".", 1)[1] for k in far.figures if k.startswith("x.new_vs_old.")}
    assert RATIO_FIGURES.isdisjoint(shown)
    assert {"p", "p_corrected", "n", "verdict"} <= shown
    assert far.figures["x.new_vs_old.verdict"].value == "no_verdict"
    assert by_case(far, "y") == by_case(usual, "y")
    assert by_case(far, "y").verdict == "SLOWER"
    assert far.rule.family_size == usual.rule.family_size == 2


def far_twin(entry: str, case: str, round_: int, u: float) -> float:
    """On case x, ``new`` sits so far from its twin that their ratio is no finite number."""
    if case == "x" and entry == "new~same":
        return 1e-308
    return known(entry, case, round_, u)


def test_a_side_too_far_from_its_twin_has_no_floor_and_its_case_no_verdict() -> None:
    got = analyse(capture(value=far_twin, cases=(FAR, NEAR)))
    usual = analyse(capture(cases=(FAR, NEAR)))
    x = by_case(got, "x")
    assert (x.outcome, x.reason, x.reasons) == ("no_verdict", "too_far_apart", ("too_far_apart",))
    assert x.ratio == by_case(usual, "x").ratio
    assert (x.floor.subject, x.bar) == (None, None)
    assert x.floor.baseline == by_case(usual, "x").floor.baseline
    twin = next(row for row in got.same_vs_same if (row.side, row.case) == ("new", "x"))
    assert (twin.ratio, twin.floor, twin.n) == (None, None, R16)
    assert twin.p_raw is not None and twin.p_raw < 0.05
    assert by_case(got, "y") == by_case(usual, "y")
    assert by_case(got, "y").verdict == "SLOWER"


def huge_floors(entry: str, case: str, round_: int, u: float) -> float:
    """Each side sits 1e306 times above its twin.

    Each floor is a finite number as a percentage; the bar, their sum, is
    not. With an odd number of rounds the median of the twin ratios is the
    middle one, so no sum of two of them is taken on the way.
    """
    if case != "x":
        return known(entry, case, round_, u)
    return 1e-8 if entry.endswith("~same") else 1e298


def test_floors_too_large_to_add_into_a_finite_bar_give_no_verdict() -> None:
    got = analyse(capture(value=huge_floors, cases=(FAR, NEAR), rounds=15))
    x = by_case(got, "x")
    assert (x.outcome, x.reason) == ("no_verdict", "too_far_apart")
    assert x.ratio == 1.0
    assert x.floor.subject is not None and x.floor.baseline is not None
    assert x.floor.subject.value == x.floor.baseline.value == 1e298 / 1e-8 - 1.0
    assert x.bar is None
    assert by_case(got, "y").verdict == "SLOWER"


def floor_beyond_percent(entry: str, case: str, round_: int, u: float) -> float:
    """``new`` sits 1e307 times above its twin: a finite fraction, but not as a percentage."""
    if case == "x" and entry == "new~same":
        return 1e-9
    if case == "x" and entry == "new":
        return 1e298
    return known(entry, case, round_, u)


def test_a_floor_too_large_to_write_as_a_percentage_leaves_the_side_without_a_floor() -> None:
    got = pairbench.analyse(capture(value=floor_beyond_percent, cases=(FAR, NEAR), rounds=15))
    x = by_case(got, "x")
    assert (x.outcome, x.reason) == ("no_verdict", "too_far_apart")
    assert (x.floor.subject, x.bar) == (None, None)
    assert x.floor.baseline is not None
    twin = next(row for row in got.same_vs_same if (row.side, row.case) == ("new", "x"))
    # Its ratio 1e307 is no usable ratio either: its percent overflows.
    assert (twin.ratio, twin.floor) == (None, None)
    assert "x.new_vs_old.floor_subject" not in got.figures
    assert by_case(got, "y").verdict == "SLOWER"


def far_control(entry: str, case: str, round_: int, u: float) -> float:
    return 1e300


def tiny(entry: str, case: str, round_: int, u: float) -> float:
    return 1e-10 * known(entry, case, round_, u)


def test_a_control_too_far_from_the_baseline_for_a_finite_ratio_fails() -> None:
    got = analyse(capture(value=tiny, control=far_control))
    control = got.controls.positive
    assert control.status == "failed"
    assert [(row.ratio, row.passed) for row in control.cases] == [(None, False)]
    assert {c.reason for c in got.comparisons} == {"positive_control_failed"}


def near_zero_control(entry: str, case: str, round_: int, u: float) -> float:
    return 1e-300


def huge(entry: str, case: str, round_: int, u: float) -> float:
    return 1e10 * known(entry, case, round_, u)


def test_a_control_ratio_whose_inverse_is_no_finite_number_fails() -> None:
    # 1e-300 against about 1e10 is a ratio near 1e-310: a float, but its
    # inverse is not.
    got = analyse(capture(value=huge, control=near_zero_control))
    control = got.controls.positive
    assert control.status == "failed"
    assert [(row.ratio, row.passed) for row in control.cases] == [(None, False)]
    assert {c.reason for c in got.comparisons} == {"positive_control_failed"}


# ---------------------------------------------------------------------------
# The document of a refused analysis
# ---------------------------------------------------------------------------


def test_the_document_of_a_refused_analysis_describes_the_captures() -> None:
    cap = capture(control=twice)
    got = refused([cap], Refusal("E_ORDER_NOT_VARIED", "new ran before old"), rule=STRICT)
    assert got.comparisons == ()
    assert got.same_vs_same == ()
    assert [(r.code, r.scope, r.message) for r in got.refusals] == [
        ("E_ORDER_NOT_VARIED", "experiment", "new ran before old")
    ]
    assert got.run.id == "synthetic-doc"
    assert [s.name for s in got.sides][-1] == "old~twice"
    assert got.plan.launches == 82
    assert got.rule.family_size == 0
    assert got.controls.positive.status == "not_run"


def test_a_refused_analysis_through_the_public_function_carries_the_document() -> None:
    caught = refusal_of(lambda: pairbench.analyse(capture(order="fixed")))
    assert caught.results is not None
    assert [r.code for r in caught.results.refusals] == ["E_ORDER_NOT_VARIED"]
    assert caught.results.comparisons == ()


@pytest.mark.parametrize(
    "make",
    [
        lambda: [],
        lambda: [dataclasses.replace(capture(), machine=None, lineup=None, end=None, sides=())],
        lambda: [dataclasses.replace(capture(), launches=(), observations=())],
        lambda: [capture(capture_id="synthetic-a"), capture(capture_id="synthetic-a")],
    ],
    ids=["no capture", "bare capture", "no launch", "the same capture twice"],
)
def test_the_document_of_a_refused_analysis_is_built_for_any_loadable_capture(
    make: Callable[[], list[Capture]],
) -> None:
    got = refused(make(), Refusal("E_GRID", "the grid is broken"), rule=STRICT)
    assert [r.code for r in got.refusals] == ["E_GRID"]
    assert got.comparisons == ()
    json.dumps(got.to_json())


def test_a_refused_document_without_captures_says_unknown() -> None:
    got = refused([], Refusal("E_USAGE", "x"), rule=STRICT)
    assert got.run.id == "no-capture"
    assert got.provenance.machine.cpu_model == "unknown"
    assert got.plan.rounds_planned == 0


# ---------------------------------------------------------------------------
# What a results document must not contain
# ---------------------------------------------------------------------------

LEAKS = (
    "build-host-77",
    "someuser",
    "/opt/private",
    "registry.example.com",
    "team-images",
    "my-plugin-kind",
    "my-plugin-gate",
    "my-plugin-driver",
    "value-must-not-leak",
    "alice-host",
    "mac-made-up-0011",
    "machine-id-abc",
    "instance-id-xyz",
    "account-id-987",
    "gpu-serial-555",
)
IMAGE = "registry.example.com/team-images/bench:1"
KINDS = ("cmd", "image", "venv", "my-plugin-kind")


def leaky_capture(kind: str = "my-plugin-kind", config: dict[str, Any] | None = None) -> Capture:
    cap = capture(control=twice, kind=kind)
    spec = {
        "image": IMAGE,
        "env": {"MY_SETTING": "value-must-not-leak", "API_TOKEN": "x"},
        "argv": ("/opt/private/bin/bench",),
        "python": "/home/someuser/venv/bin/python",
    }
    identity = {
        "hostname": "build-host-77",
        "prefix": "/opt/private/env",
        "mac": "mac-made-up-0011",
        "machine_id": "machine-id-abc",
        "instance_id": "instance-id-xyz",
        "account_id": "account-id-987",
        "gpu_serial": "gpu-serial-555",
        "image_id": "sha256:" + "a" * 64,
        "digests": ["registry.example.com/team-images/bench@sha256:" + "c" * 64],
    }
    sides = tuple(dataclasses.replace(s, spec=spec, identity=identity) for s in cap.sides)
    assert cap.machine is not None
    machine = dataclasses.replace(cap.machine, tool_cpus="4-7")
    header = dataclasses.replace(
        cap.header,
        argv=(
            "/home/someuser/venv/bin/pairbench",
            "run",
            "--side",
            f"new=image:{IMAGE}",
            "--set",
            "launch.env.MY_SETTING=value-must-not-leak",
        ),
        config={
            "workload": {"driver": "my-plugin-driver"},
            "home": "/home/someuser",
            **(config or {}),
        },
    )
    gates = (
        GateRecord(
            name="my-plugin-gate",
            mode="warn",
            status="degraded",
            detail={"message": "cannot read /home/someuser/alice-host/proc", "host": "alice-host"},
        ),
    )
    notes = (
        Note(code="witness_probe_failed", message="probe failed in /opt/private/alice-host/x"),
    )
    return dataclasses.replace(
        cap,
        header=header,
        machine=machine,
        sides=sides,
        gates=gates,
        notes=notes,
        source=Source(path="/home/someuser/captures/capture.jsonl", sha256="b" * 64),
    )


def leaks_in(results: Results) -> list[str]:
    text = json.dumps(results.to_json())
    return [leak for leak in LEAKS if leak in text]


@pytest.mark.parametrize("kind", KINDS)
def test_an_analysed_document_holds_nothing_that_identifies_the_machine(kind: str) -> None:
    results = analyse(leaky_capture(kind), floors=Floors(0.0625), allow_incomplete=True)
    assert leaks_in(results) == []
    assert {s.image_ref for s in results.sides} == {None}
    assert results.sides[0].identity == {
        "image_id": "sha256:" + "a" * 64,
        "digests": ("sha256:" + "c" * 64,),
    }
    assert results.machine_state.gates[0].name == "plugin"


@pytest.mark.parametrize("kind", KINDS)
def test_a_refused_document_holds_nothing_that_identifies_the_machine(kind: str) -> None:
    caught = Refusal("E_GRID", "cannot read /home/someuser/alice-host/capture.jsonl")
    results = refused([leaky_capture(kind)], caught, rule=STRICT)
    assert leaks_in(results) == []
    assert {s.image_ref for s in results.sides} == {None}


def test_a_plug_in_kind_is_shown_as_plugin() -> None:
    results = analyse(leaky_capture("my-plugin-kind"))
    assert {s.kind for s in results.sides} == {"plugin"}


def test_the_image_reference_is_shown_as_typed_only_when_the_settings_ask() -> None:
    asked = leaky_capture("image", config={"report": {"include_image_refs": True}})
    results = analyse(asked)
    assert {s.image_ref for s in results.sides} == {IMAGE}
    assert [
        leak for leak in leaks_in(results) if leak not in ("registry.example.com", "team-images")
    ] == []
    stopped = refused([asked], Refusal("E_GRID", "x"), rule=STRICT)
    assert {s.image_ref for s in stopped.sides} == {IMAGE}


def test_every_side_kind_a_results_document_shows_is_known() -> None:
    side = Side(name="new", kind="cmd")
    assert side.for_results().kind == "cmd"


def test_a_control_entry_without_a_side_record_is_not_judged() -> None:
    cap = capture(control=twice)
    cap = dataclasses.replace(cap, sides=tuple(s for s in cap.sides if s.role != "control"))
    got = analyse(cap)
    assert got.controls.positive.status == "not_run"
    assert got.notes[-1].message == (
        "the positive control was not judged: "
        "no side record describes the control entry the lineup names"
    )


# Two made-up runs of 32 hexadecimal digits, which the shown command hides for their shape.
HEX_ONE = "3f9a1c7e5b2d4086a1c3e5f7092b4d6e"
HEX_TWO = "8e2b6d4f0a1c3e5b7d9f1a3c5e7b9d0f"


def _with_raw_side(cap: Capture, argv: Sequence[str]) -> Capture:
    """The capture with side ``new`` run as ``argv``: its fingerprint and its header's raw side."""
    cap = _with_new_fingerprint(cap, _command_fingerprint(argv))
    config = {
        "sides": {"new": {"cmd": list(argv)}, "old": {"cmd": ["made-up-tool"], "baseline": True}}
    }
    return dataclasses.replace(cap, header=dataclasses.replace(cap.header, config=config))


def _pieces(*values: str) -> list[str]:
    """Each value and every stretch of eight of its characters, as no message may hold."""
    return [v[k : k + 8] for v in values for k in range(len(v) - 7)]


def test_captures_whose_side_differs_in_a_value_hidden_for_its_shape_are_refused_as_drift() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "--run", HEX_ONE])
    b = _with_raw_side(b, ["made-up-tool", "--run", HEX_TWO])
    assert {s.fingerprint for s in a.sides if s.name == "new"} == {
        s.fingerprint for s in b.sides if s.name == "new"
    }

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.message == (
        "the setup of new differs between the captures synthetic-a and synthetic-b in a value "
        "the results hide"
    )
    assert caught.detail["sides"] == ["new"]
    assert caught.detail["captures"] == ["synthetic-a", "synthetic-b"]
    for piece in _pieces(HEX_ONE, HEX_TWO):
        assert piece not in caught.message
        assert piece not in json.dumps(caught.detail)


def _with_workload(cap: Capture, argv: Sequence[str]) -> Capture:
    """The capture with both raw sides in its header and ``argv`` as the workload's arguments."""
    config = {
        "sides": {
            "new": {"cmd": ["made-up-new"]},
            "old": {"cmd": ["made-up-old"], "baseline": True},
        },
        "workload": {"argv": list(argv)},
    }
    return dataclasses.replace(cap, header=dataclasses.replace(cap.header, config=config))


def test_captures_whose_workload_differs_in_a_value_hidden_for_its_shape_are_refused() -> None:
    a, b = two()
    a = _with_workload(a, ["--seed-file", HEX_ONE])
    b = _with_workload(b, ["--seed-file", HEX_TWO])

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.message == (
        "the setup of new, old differs between the captures synthetic-a and synthetic-b in a "
        "value the results hide"
    )
    assert caught.detail["sides"] == ["new", "old"]
    for piece in _pieces(HEX_ONE, HEX_TWO):
        assert piece not in caught.message
        assert piece not in json.dumps(caught.detail)


def test_captures_whose_side_differs_after_the_first_space_of_a_hidden_value_are_refused() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "HF_TOKEN=kiwi7 ./made-up-bench-old"])
    b = _with_raw_side(b, ["made-up-tool", "HF_TOKEN=kiwi7 ./made-up-bench-new"])
    assert {s.fingerprint for s in a.sides if s.name == "new"} == {
        s.fingerprint for s in b.sides if s.name == "new"
    }

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.detail["sides"] == ["new"]
    for piece in ("kiwi7", "bench-old", "bench-new"):
        assert piece not in caught.message
        assert piece not in json.dumps(caught.detail)


def test_captures_whose_side_differs_only_in_a_hidden_value_before_its_first_space_pool() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "HF_TOKEN=kiwi7 ./made-up-bench"])
    b = _with_raw_side(b, ["made-up-tool", "HF_TOKEN=plum4 ./made-up-bench"])

    got = analyse([a, b])

    assert got.run.pooled is True


def test_captures_whose_side_differs_in_an_ordinary_setting_are_refused_as_drift() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "--max-num-queued-tokens", "1024"])
    b = _with_raw_side(b, ["made-up-tool", "--max-num-queued-tokens", "4096"])

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.detail["sides"] == ["new", "new~same"]


def test_captures_whose_raw_side_differs_only_under_a_credential_name_pool() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "--api-key", "kiwi7"])
    b = _with_raw_side(b, ["made-up-tool", "--api-key", "plum4"])

    got = analyse([a, b])

    assert got.run.pooled is True
    assert [c.capture_id for c in got.run.captures] == ["synthetic-a", "synthetic-b"]


def test_a_header_without_the_raw_side_falls_back_to_the_fingerprint_rule() -> None:
    a, b = two()
    a = _with_raw_side(a, ["made-up-tool", "--run", HEX_ONE])
    b = _with_new_fingerprint(b, _command_fingerprint(["made-up-tool", "--run", HEX_TWO]))
    assert dict(b.header.config) == {}

    got = analyse([a, b])

    assert got.run.pooled is True


def _with_identify_output(cap: Capture, output: str) -> Capture:
    """The capture with this output of an identify command recorded for side ``new``.

    The side's identity and fingerprint are made as a command side makes them,
    so the fingerprint reads the output as every published hash does.
    """
    from pairbench.model import LaunchSettings, fingerprint_of, hashed_output, sha256_hex
    from pairbench.sides.identity import argv_sha256

    identity = {
        "executable": "/made/up/bin/tool",
        "executable_sha256": "ab" * 32,
        "argv_sha256": argv_sha256(["made-up-tool"]),
        "identify_output": output,
        "identify_sha256": sha256_hex(hashed_output(output)),
    }
    fingerprint = fingerprint_of(identity, LaunchSettings().effective(args=["made-up-tool"]))
    for name in ("new", "new~same"):
        cap = replace_sides(cap, name, identity=identity, fingerprint=fingerprint)
    return cap


def test_captures_whose_identify_output_differs_in_a_checksum_are_refused() -> None:
    # The output is hashed with only its credentials hidden, so a checksum is in the fingerprint.
    a, b = two()
    a = _with_identify_output(a, f"{HEX_ONE}  made-up-weights.bin\n")
    b = _with_identify_output(b, f"{HEX_TWO}  made-up-weights.bin\n")
    assert {s.fingerprint for s in a.sides if s.name == "new"} != {
        s.fingerprint for s in b.sides if s.name == "new"
    }

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.message == (
        "the fingerprint of new, new~same differs between the captures synthetic-a and synthetic-b"
    )
    assert caught.detail["sides"] == ["new", "new~same"]
    for piece in _pieces(HEX_ONE, HEX_TWO):
        assert piece not in caught.message
        assert piece not in json.dumps(caught.detail)


def test_captures_whose_identify_output_differs_only_in_a_credential_pool() -> None:
    a, b = two()
    a = _with_identify_output(a, "made-up-tool 1.0\nMADE_UP_TOKEN=kiwi7\n")
    b = _with_identify_output(b, "made-up-tool 1.0\nMADE_UP_TOKEN=plum4\n")

    got = analyse([a, b])

    assert got.run.pooled is True


def test_captures_whose_identify_output_differs_in_an_ordinary_line_are_refused() -> None:
    a, b = two()
    a = _with_identify_output(a, "made-up-tool 1.0\n")
    b = _with_identify_output(b, "made-up-tool 2.0\n")

    caught = refusal_of(lambda: analyse([a, b]))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", 6)
    assert caught.message == (
        "the fingerprint of new, new~same differs between the captures synthetic-a and synthetic-b"
    )
