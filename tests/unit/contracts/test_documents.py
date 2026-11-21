# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The capture, the results document and the config: examples against the shipped
JSON Schemas, and round trips through the model."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from pairbench import model
from pairbench.errors import Refusal
from pairbench.model import (
    Capture,
    Case,
    Experiment,
    Observation,
    ReaderInfo,
    Results,
    Side,
    Source,
)
from pairbench.results import SCHEMA_NAMES, load_schema, schema_text

jsonschema = pytest.importorskip(
    "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
)


def _validator(name: str) -> Any:
    schema = load_schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _errors(name: str, document: Any) -> list[str]:
    return sorted(error.message for error in _validator(name).iter_errors(document))


def _contains(whole: Any, part: Any) -> bool:
    """Say whether every key and value of ``part`` is in ``whole``, at every depth."""
    if isinstance(part, dict):
        return isinstance(whole, dict) and all(
            key in whole and _contains(whole[key], value) for key, value in part.items()
        )
    if isinstance(part, list):
        return (
            isinstance(whole, list)
            and len(whole) == len(part)
            and all(_contains(w, p) for w, p in zip(whole, part, strict=True))
        )
    return bool(whole == part)


# ---------------------------------------------------------------------------
# The shipped schemas
# ---------------------------------------------------------------------------


def test_four_schemas_ship_with_the_package() -> None:
    assert SCHEMA_NAMES == ("capture", "results", "config", "diagnostics")


@pytest.mark.parametrize(
    ("name", "schema_id"),
    [
        ("capture", "pairbench/capture/v1"),
        ("results", "pairbench/results/v1"),
        ("config", "pairbench/config/v1"),
        ("diagnostics", "pairbench/diagnostics/v1"),
    ],
)
def test_a_schema_is_a_valid_draft_2020_12_schema_with_its_id(name: str, schema_id: str) -> None:
    schema = load_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == schema_id
    jsonschema.Draft202012Validator.check_schema(schema)
    assert json.loads(schema_text(name)) == schema


def test_an_unknown_schema_name_is_refused() -> None:
    with pytest.raises(ValueError, match="no schema named 'made_up'"):
        schema_text("made_up")


# ---------------------------------------------------------------------------
# The capture
# ---------------------------------------------------------------------------


def test_the_example_capture_records_validate(
    example_capture_records: list[dict[str, Any]],
) -> None:
    assert [record["t"] for record in example_capture_records] == [
        "header",
        "machine",
        "side",
        "gate",
        "lineup",
        "launch",
        "obs",
        "end",
    ]
    for record in example_capture_records:
        assert _errors("capture", record) == [], record["t"]


def test_the_records_with_every_key_validate(
    example_capture_additions: list[dict[str, Any]],
) -> None:
    assert [record["t"] for record in example_capture_additions] == [
        "cases",
        "launch",
        "obs",
        "note",
        "end",
    ]
    for record in example_capture_additions:
        assert _errors("capture", record) == [], record["t"]


def test_the_example_capture_survives_a_round_trip(
    example_capture_records: list[dict[str, Any]],
) -> None:
    capture = Capture.from_records(example_capture_records)
    written = capture.to_records()
    assert len(written) == len(example_capture_records)
    for out, given in zip(written, example_capture_records, strict=True):
        assert out["t"] == given["t"]
        assert _contains(out, given), given["t"]
        assert _errors("capture", out) == [], given["t"]
    assert Capture.from_records(written) == capture
    assert Capture.from_records(written).to_records() == written


def test_the_example_capture_is_read_into_the_model(
    example_capture_records: list[dict[str, Any]],
) -> None:
    capture = Capture.from_records(example_capture_records)
    assert capture.capture_id == "cap-000001"
    assert capture.header.schema == "pairbench/capture/v1"
    assert capture.machine is not None
    assert capture.machine.cpu.identity[0].cpus == "4-7"
    assert [s.name for s in capture.sides] == ["new"]
    assert capture.sides[0].spec == {"image": "registry.example/org/app:2.0"}
    assert capture.gates[0].status == "pass"
    assert capture.lineup is not None
    assert capture.lineup.names == ("new", "new~same", "old", "old~same")
    assert capture.lineup.rounds == 16
    assert capture.lineup.schedule == "rotate-reverse"
    assert [c.id for c in capture.cases] == ["wall"]
    assert capture.launches[0].timing == {"launch_s": 12.5, "run_s": 12.25}
    assert capture.launches[0].tool_version is None
    assert capture.observations == (
        Observation(seq=7, round=1, pos=1, name="new", case="wall", value=12.25),
    )
    assert capture.end is not None
    assert capture.end.status == "complete"
    assert capture.end.discard_sha256 is None
    assert capture.complete is True
    assert capture.source is None


def test_records_with_every_key_are_read_into_the_model(
    example_capture_records: list[dict[str, Any]],
    example_capture_additions: list[dict[str, Any]],
) -> None:
    records = example_capture_records[:-1] + example_capture_additions
    capture = Capture.from_records(records)
    assert [c.id for c in capture.cases] == ["wall", "launch"]
    assert capture.launches[1].tool_version == "0.0.0"
    assert capture.observations[1].suite == "suite-a"
    assert [(n.code, n.message) for n in capture.notes] == [
        ("witness_probe_failed", "a made-up note")
    ]
    assert capture.end is not None
    assert capture.end.finished_at == "2001-01-01T00:10:00Z"
    assert capture.end.discard_sha256 == "a" * 64
    decision = capture.set_aside()
    assert decision is not None
    assert decision.rounds == (1,)
    written = capture.to_records()
    assert [r["t"] for r in written] == [
        "header",
        "machine",
        "side",
        "gate",
        "lineup",
        "cases",
        "launch",
        "obs",
        "launch",
        "obs",
        "note",
        "end",
    ]
    for record in written:
        assert _errors("capture", record) == [], record["t"]
    assert Capture.from_records(written) == capture


@pytest.mark.parametrize(
    ("index", "key"),
    [
        (0, "capture_id"),
        (0, "schema"),
        (1, "cpu"),
        (2, "fingerprint"),
        (3, "status"),
        (4, "discard_thresholds"),
        (5, "witness"),
        (6, "n_inner"),
        (7, "sha256_of_preceding"),
    ],
)
def test_a_record_without_a_required_key_is_refused_by_schema_and_model(
    example_capture_records: list[dict[str, Any]], index: int, key: str
) -> None:
    record = example_capture_records[index]
    del record[key]
    assert _errors("capture", record) == [f"'{key}' is a required property"]
    with pytest.raises(Refusal, match=f"missing key '{key}'") as caught:
        model.record_from_json(record)
    assert caught.value.code == "E_USAGE"


def test_a_record_of_an_unknown_type_is_refused() -> None:
    assert _errors("capture", {"t": "made_up"}) != []
    with pytest.raises(Refusal, match="not a capture record") as caught:
        model.record_from_json({"t": "made_up"})
    assert caught.value.code == "E_USAGE"


def test_a_record_with_a_wrong_value_is_refused(
    example_capture_records: list[dict[str, Any]],
) -> None:
    launch = example_capture_records[5]
    launch["phase"] = "cooldown"
    assert _errors("capture", launch) == ["'cooldown' is not one of ['warmup', 'round']"]
    with pytest.raises(Refusal, match="not a valid Launch") as caught:
        model.record_from_json(launch)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("index", "key", "value", "message", "words"),
    [
        (
            0,
            "schema",
            "pairbench/capture/v2",
            "'pairbench/capture/v1' was expected",
            r"Header\.schema: expected one of 'pairbench/capture/v1'",
        ),
        (5, "round", -1, "is less than the minimum of 0", "Launch.round: expected at least 0"),
        (5, "pos", 0, "is less than the minimum of 1", "Launch.pos: expected at least 1"),
        (6, "round", -1, "is less than the minimum of 0", "Observation.round: expected at least"),
        (6, "pos", 0, "is less than the minimum of 1", "Observation.pos: expected at least 1"),
        (6, "n_inner", 0, "is less than the minimum of 1", "Observation.n_inner: expected at"),
        (
            4,
            "discard_thresholds",
            {"max_busy_cores": -1.0, "max_gpu_other_processes": 0, "max_gpu_throttle_events": 0},
            "is not valid under any of the given schemas",
            "DiscardThresholds.max_busy_cores: expected at least 0",
        ),
    ],
)
def test_a_record_with_a_value_outside_its_limits_is_refused_by_schema_and_model(
    example_capture_records: list[dict[str, Any]],
    index: int,
    key: str,
    value: Any,
    message: str,
    words: str,
) -> None:
    record = example_capture_records[index]
    record[key] = value
    found = _errors("capture", record)
    assert len(found) == 1
    assert message in found[0]
    with pytest.raises(Refusal, match=words) as caught:
        model.record_from_json(record)
    assert caught.value.code == "E_USAGE"


def test_a_note_code_is_lower_case_words_in_schema_and_model() -> None:
    record = {"t": "note", "code": "Not A Code", "message": "a made-up note"}
    assert len(_errors("capture", record)) == 1
    with pytest.raises(Refusal, match=r"Note\.code: expected a text that matches") as caught:
        model.record_from_json(record)
    assert caught.value.code == "E_USAGE"
    for code in (name for name in dir(model) if name.startswith("NOTE_")):
        assert model.Note(code=getattr(model, code), message="a made-up note")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_capture_holds_no_number_that_is_not_finite(
    example_capture_records: list[dict[str, Any]], value: float
) -> None:
    observation = example_capture_records[6]
    observation["value"] = value
    with pytest.raises(Refusal, match=r"Observation\.value: expected a finite number"):
        model.record_from_json(observation)
    launch = example_capture_records[5]
    launch["timing"]["run_s"] = value
    with pytest.raises(Refusal, match=r"Launch\.timing\.run_s: expected a finite number"):
        model.record_from_json(launch)
    with pytest.raises(ValueError, match="expected a finite number"):
        Observation(seq=1, round=1, pos=1, name="new", case="wall", value=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_free_table_holds_no_number_that_is_not_finite(value: float) -> None:
    launch = {"seq": 1, "phase": "round", "round": 1, "pos": 1, "name": "new"}
    with pytest.raises(ValueError, match=r"Launch\.energy\.windows\[0\]\.energy_j: expected"):
        model.Launch(**launch, energy={"windows": [{"energy_j": value}]})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"Launch\.witness\.made_up: expected a finite number"):
        model.Launch(**launch, witness={"made_up": value})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"GateRecord\.detail\.load: expected a finite number"):
        model.GateRecord(name="quiet", mode="warn", status="fail", detail={"load": value})
    with pytest.raises(ValueError, match=r"Header\.config\.gates\.quiet\.max_wait_s: expected"):
        model.Header(capture_id="cap-000003", config={"gates": {"quiet": {"max_wait_s": value}}})
    with pytest.raises(ValueError, match=r"Side\.identity\.made_up: expected a finite number"):
        Side(name="new", kind="cmd", identity={"made_up": value})
    with pytest.raises(ValueError, match=r"RuleInfo\.fields\.alpha: expected a finite number"):
        model.RuleInfo(name="strict", fields={"alpha": value}, family_size=1, plain="made-up")
    record = {
        "t": "gate",
        "name": "quiet",
        "mode": "warn",
        "status": "fail",
        "detail": {"x": value},
    }
    with pytest.raises(Refusal, match="expected a finite number") as caught:
        model.record_from_json(record)
    assert caught.value.code == "E_USAGE"


def test_every_record_a_model_object_writes_is_valid_json(
    example_capture_records: list[dict[str, Any]], example_capture_additions: list[dict[str, Any]]
) -> None:
    capture = Capture.from_records(example_capture_records[:-1] + example_capture_additions)
    for record in capture.to_records():
        assert json.loads(json.dumps(record, allow_nan=False)) == record


def test_a_value_of_zero_or_less_is_kept_for_the_analysis_to_grade() -> None:
    assert Observation(seq=1, round=1, pos=1, name="new", case="wall", value=0.0).value == 0.0
    assert Observation(seq=1, round=1, pos=1, name="new", case="wall", value=-2.5).value == -2.5


@pytest.mark.parametrize("value", [True, False])
def test_true_and_false_are_not_whole_numbers(
    example_capture_records: list[dict[str, Any]], value: bool
) -> None:
    launch = example_capture_records[5]
    launch["rc"] = value
    assert len(_errors("capture", launch)) == 1
    with pytest.raises(Refusal, match=r"Launch\.rc: expected a whole number"):
        model.record_from_json(launch)


def test_the_side_record_is_written_with_credential_values_redacted() -> None:
    side = Side.image(
        "new",
        "registry.example/org/app:2.0",
        env={"API_TOKEN": "made-up-secret", "OMP_NUM_THREADS": "4"},
    )
    written = side.to_json()
    assert written["spec"]["env"] == {"API_TOKEN": "<redacted>", "OMP_NUM_THREADS": "4"}
    assert written["spec"]["image"] == "registry.example/org/app:2.0"
    assert side.spec["env"]["API_TOKEN"] == "made-up-secret"
    assert side.to_json(redact=False)["spec"]["env"]["API_TOKEN"] == "made-up-secret"
    assert side.twin().to_json()["spec"]["env"]["API_TOKEN"] == "<redacted>"
    serving = Side(
        name="srv",
        kind="serve",
        spec=model.ServeSpec(
            image="myorg/server:2.0", env={"HF_TOKEN": "made-up-secret"}
        ).to_json(),
    )
    assert serving.to_json()["spec"]["env"] == {"HF_TOKEN": "<redacted>"}
    capture = Capture(
        capture_id="cap-000002", header=model.Header(capture_id="cap-000002"), sides=(side,)
    )
    assert "made-up-secret" not in json.dumps(capture.to_records())
    assert _errors("capture", written) == []


def test_a_failed_or_interrupted_capture_is_not_complete(
    example_capture_records: list[dict[str, Any]],
) -> None:
    for status in ("failed", "interrupted"):
        example_capture_records[-1]["status"] = status
        capture = Capture.from_records(example_capture_records)
        assert capture.end is not None
        assert capture.end.status == status
        assert capture.complete is False


def test_a_warm_up_is_no_round(example_capture_records: list[dict[str, Any]]) -> None:
    warm_up = {
        **example_capture_records[5],
        "seq": 1,
        "phase": "warmup",
        "round": 0,
        "pos": None,
        "witness": {"busy_cores": 64.0},
    }
    discovered = {**example_capture_records[6], "seq": 1, "round": 0, "pos": None, "value": 99.0}
    capture = Capture.from_records([*example_capture_records, warm_up, discovered])
    assert [launch.seq for launch in capture.round_launches()] == [7]
    assert [(o.seq, o.value) for o in capture.round_observations()] == [(7, 12.25)]
    decision = capture.set_aside()
    assert decision is not None
    assert decision.rounds == ()


def test_the_caller_of_load_capture_can_declare_a_twin() -> None:
    rows = [
        (1, "new", "matmul", 1.5),
        (1, "copy", "matmul", 1.5),
        (1, "old", "matmul", 2.0),
    ]
    capture = Capture.from_rows(rows, sides=["new", "copy", "old"])
    assert [(s.name, s.role, s.twin_of) for s in capture.sides] == [
        ("new", "subject", None),
        ("copy", "subject", None),
        ("old", "baseline", None),
    ]
    declared = capture.with_twins({"copy": "new"})
    assert [(s.name, s.role, s.twin_of) for s in declared.sides] == [
        ("new", "subject", None),
        ("copy", "twin", "new"),
        ("old", "baseline", None),
    ]
    assert declared.observations == capture.observations
    assert declared.lineup == capture.lineup
    assert capture.with_twins({}) == capture
    for twins, words in (
        ({"nobody": "new"}, "'nobody' is no side of this capture"),
        ({"copy": "copy"}, "'copy' cannot be a twin of 'copy'"),
        ({"old": "new"}, "the baseline 'old' cannot be a twin"),
        ({"copy": "new", "new": "old"}, "'copy' cannot be a twin of 'new'"),
    ):
        with pytest.raises(Refusal, match=words) as caught:
            capture.with_twins(twins)
        assert caught.value.code == "E_USAGE"
    with pytest.raises(Refusal, match="'old' cannot be a twin of 'copy'"):
        declared.with_twins({"old": "copy"})
    with pytest.raises(Refusal, match="the twin 'copy' names the side 'nobody'") as orphan:
        capture.with_twins({"copy": "nobody"})
    assert (orphan.value.code, orphan.value.exit_code) == ("E_TWIN_ORPHAN", 6)


def test_a_capture_needs_exactly_one_header(example_capture_records: list[dict[str, Any]]) -> None:
    with pytest.raises(Refusal, match="a capture needs a header record"):
        Capture.from_records(example_capture_records[1:])
    with pytest.raises(Refusal, match="a capture has two header records"):
        Capture.from_records([example_capture_records[0], *example_capture_records])


def test_a_capture_without_an_end_record_is_not_complete(
    example_capture_records: list[dict[str, Any]],
) -> None:
    capture = Capture.from_records(example_capture_records[:-1])
    assert capture.end is None
    assert capture.complete is False


def test_where_a_capture_was_read_from_is_kept_beside_its_records(
    example_capture_records: list[dict[str, Any]],
) -> None:
    reader = ReaderInfo(
        reader="text",
        run_index=1,
        metadata=(("unit", "ns"), ("sides", "new old"), ("twin", "copy:new"), ("unit", "us")),
        sides_declared=("new", "old"),
        sides_observed=("new", "old", "copy"),
        malformed_rows=2,
        comments=3,
        one_sided_keys=1,
    )
    source = Source(path="rows.txt", sha256="c" * 64, torn=True, reader=reader)
    capture = Capture.from_records(example_capture_records, source=source)
    assert capture.source == source
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.malformed_rows == 2
    assert capture.source.reader.comments == 3
    assert capture.source.reader.one_sided_keys == 1
    assert capture.source.reader.get("unit") == "us"
    assert capture.source.reader.get("made_up") is None
    assert capture.to_records() == Capture.from_records(example_capture_records).to_records()


# ---------------------------------------------------------------------------
# A capture from rows produced elsewhere
# ---------------------------------------------------------------------------

ROWS = [
    (1, "new", "matmul", 1.5),
    (1, "old", "matmul", 3.0),
    (2, "old", "matmul", 3.0),
    (2, "new", "matmul", 1.5),
]


def test_a_capture_from_rows_without_positions_has_no_recorded_order() -> None:
    capture = Capture.from_rows(ROWS, sides=["new", "old"])
    # "rows-" and the first twelve hex digits of the sha256 of the rows as canonical JSON.
    assert capture.capture_id == "rows-a2f3d851d455"
    assert capture.order_recorded is False
    assert [(s.name, s.kind, s.role, s.twin_of) for s in capture.sides] == [
        ("new", "rows", "subject", None),
        ("old", "rows", "baseline", None),
    ]
    assert capture.baseline == "old"
    assert capture.lineup is not None
    assert capture.lineup.names == ("new", "old")
    assert capture.lineup.rounds == 2
    assert capture.lineup.schedule is None
    assert [(x.seq, x.phase, x.round, x.pos, x.name) for x in capture.launches] == [
        (1, "round", 1, None, "new"),
        (2, "round", 1, None, "old"),
        (3, "round", 2, None, "new"),
        (4, "round", 2, None, "old"),
    ]
    assert [(o.seq, o.round, o.pos, o.name, o.case, o.value) for o in capture.observations] == [
        (1, 1, None, "new", "matmul", 1.5),
        (2, 1, None, "old", "matmul", 3.0),
        (3, 2, None, "new", "matmul", 1.5),
        (4, 2, None, "old", "matmul", 3.0),
    ]
    assert [c.id for c in capture.cases] == ["matmul"]
    assert capture.end is not None
    assert (capture.end.status, capture.end.rounds_completed) == ("complete", 2)
    assert capture.complete is True


def test_a_capture_from_rows_with_positions_records_the_order() -> None:
    positions = {(1, "new"): 1, (1, "old"): 2, (2, "old"): 1, (2, "new"): 2}
    capture = Capture.from_rows(ROWS, sides=["new", "old"], positions=positions)
    assert capture.order_recorded is True
    assert [(x.round, x.pos, x.name) for x in capture.launches] == [
        (1, 1, "new"),
        (1, 2, "old"),
        (2, 1, "old"),
        (2, 2, "new"),
    ]
    assert [(o.round, o.pos, o.name) for o in capture.observations] == [
        (1, 1, "new"),
        (1, 2, "old"),
        (2, 1, "old"),
        (2, 2, "new"),
    ]


def test_a_capture_from_rows_with_some_positions_missing_has_no_recorded_order() -> None:
    capture = Capture.from_rows(ROWS, sides=["new", "old"], positions={(1, "new"): 1})
    assert capture.order_recorded is False


def test_a_capture_from_rows_takes_declared_twins() -> None:
    rows = [*ROWS, (1, "copy", "matmul", 1.5), (2, "copy", "matmul", 1.5)]
    capture = Capture.from_rows(rows, sides=["new", "old"], twins={"copy": "new"})
    assert [(s.name, s.role, s.twin_of) for s in capture.sides] == [
        ("new", "subject", None),
        ("copy", "twin", "new"),
        ("old", "baseline", None),
    ]
    assert capture.lineup is not None
    assert capture.lineup.names == ("new", "copy", "old")


def test_a_capture_from_rows_keeps_a_baseline_named_by_a_side() -> None:
    sides = [Side(name="old", kind="rows", role="baseline"), "new"]
    capture = Capture.from_rows(ROWS, sides=sides)
    assert capture.baseline == "old"
    assert [s.role for s in capture.sides] == ["baseline", "subject"]


def test_captures_from_different_rows_have_different_ids() -> None:
    other = [(1, "new", "matmul", 1.5), (1, "old", "matmul", 3.25)]
    one = Capture.from_rows(ROWS, sides=["new", "old"]).capture_id
    two = Capture.from_rows(other, sides=["new", "old"]).capture_id
    assert one != two


@pytest.mark.parametrize(
    ("rows", "sides", "twins", "words"),
    [
        (ROWS, [], None, "needs at least one side"),
        (ROWS, ["new", "new"], None, "a side name twice"),
        (ROWS, ["new"], None, "'old', which is no side or twin"),
        ([(True, "new", "matmul", 1.5)], ["new"], None, "a round is a whole number"),
        ([(1.0, "new", "matmul", 1.5)], ["new"], None, "a round is a whole number"),
        ([(1, "new", "matmul", "fast")], ["new"], None, "a value is a finite number"),
        ([(1, "new", "matmul", float("nan"))], ["new"], None, "a value is a finite number"),
        ([(1, "new", "matmul", float("inf"))], ["new"], None, "a value is a finite number"),
        ([(1, "new", "matmul", True)], ["new"], None, "a value is a finite number"),
        (ROWS, ["new", "old"], {"old": "new"}, "'old' is both a side and a twin"),
    ],
)
def test_rows_that_are_refused(rows: Any, sides: Any, twins: Any, words: str) -> None:
    with pytest.raises(Refusal, match=words) as caught:
        Capture.from_rows(rows, sides=sides, twins=twins)
    assert caught.value.code == "E_USAGE"


def test_round_labels_are_numbered_from_one_in_their_order() -> None:
    rows = [
        (label, side, "matmul", value)
        for label, value in ((-4, 1.5), (7, 2.5), (0, 3.5))
        for side in ("new", "old")
    ]
    positions = {(-4, "new"): 2, (-4, "old"): 1, (7, "new"): 1, (7, "old"): 2}
    capture = Capture.from_rows(rows, sides=["new", "old"], positions=positions)
    assert [(o.round, o.name, o.value, o.pos) for o in capture.observations] == [
        (1, "old", 1.5, 1),
        (1, "new", 1.5, 2),
        (2, "new", 3.5, None),
        (2, "old", 3.5, None),
        (3, "new", 2.5, 1),
        (3, "old", 2.5, 2),
    ]
    assert capture.lineup is not None and capture.lineup.rounds == 3
    assert capture.end is not None and capture.end.rounds_completed == 3
    assert model.round_numbers([5, 3, 9, 3]) == {3: 1, 5: 2, 9: 3}


def test_without_cases_every_case_is_primary_lower_is_better_and_in_seconds() -> None:
    capture = Capture.from_rows(ROWS, sides=["new", "old"])
    assert capture.cases == (
        Case(id="matmul", metric="value", unit="s", better="lower", kind="time", primary=True),
    )
    assert capture.lineup is not None
    assert capture.lineup.cases == capture.cases


@pytest.mark.parametrize(
    ("unit", "kind"),
    [
        ("ns", "time"),
        ("us", "time"),
        ("ms", "time"),
        ("s", "time"),
        ("ops/s", "other"),
        ("", "other"),
    ],
)
def test_the_unit_named_once_is_the_unit_of_every_case(unit: str, kind: str) -> None:
    capture = Capture.from_rows(ROWS, sides=["new", "old"], unit=unit)
    assert [(c.unit, c.kind, c.better, c.primary) for c in capture.cases] == [
        (unit, kind, "lower", True)
    ]
    assert model.TIME_UNITS == ("ns", "us", "ms", "s")
    assert model.kind_of_unit(unit) == kind


def test_the_cases_given_say_which_are_primary_and_their_unit_and_direction() -> None:
    rate = Case(id="matmul", metric="rate", unit="ops/s", better="higher", kind="rate")
    cores = Case(
        id="res/cores", metric="cores", unit="cores", better="none", kind="other", primary=False
    )
    rows = [*ROWS, (1, "new", "res/cores", 7.8), (1, "old", "res/cores", 1.0)]
    capture = Capture.from_rows(rows, sides=["new", "old"], cases=[rate, cores], unit="ms")
    assert capture.cases == (rate, cores)
    assert capture.lineup is not None
    assert capture.lineup.cases == (rate, cores)
    assert [c.primary for c in capture.cases] == [True, False]
    for record in capture.to_records():
        assert _errors("capture", record) == [], record["t"]


@pytest.mark.parametrize(
    ("cases", "words"),
    [
        ([], "a row names the case 'matmul', which the cases given do not hold"),
        (
            [Case(id="fft", metric="time", unit="s")],
            "a row names the case 'matmul', which the cases given do not hold",
        ),
        (
            [Case(id="matmul", metric="time", unit="s")] * 2,
            "was given the case 'matmul' twice",
        ),
        (["matmul"], "takes Case records as cases"),
    ],
)
def test_cases_that_do_not_fit_the_rows_are_refused(cases: Any, words: str) -> None:
    with pytest.raises(Refusal, match=words) as caught:
        Capture.from_rows(ROWS, sides=["new", "old"], cases=cases)
    assert caught.value.code == "E_USAGE"


def test_a_row_whose_value_is_zero_or_less_is_kept() -> None:
    rows = [(1, "new", "matmul", 0), (1, "old", "matmul", -2.5), (2, "new", "matmul", 0.0)]
    capture = Capture.from_rows(rows, sides=["new", "old"])
    assert [o.value for o in capture.observations] == [0, -2.5, 0.0]


def test_a_twin_whose_side_is_absent_is_an_orphan() -> None:
    with pytest.raises(Refusal, match="twins name a side that is absent: copy") as caught:
        Capture.from_rows(ROWS, sides=["new", "old"], twins={"copy": "nobody"})
    assert (caught.value.code, caught.value.exit_code) == ("E_TWIN_ORPHAN", 6)


def test_a_capture_from_rows_writes_records_that_validate() -> None:
    capture = Capture.from_rows(ROWS, sides=["new", "old"], twins=None)
    for record in capture.to_records():
        assert _errors("capture", record) == [], record["t"]
    assert Capture.from_records(capture.to_records()) == capture


# ---------------------------------------------------------------------------
# The results document
# ---------------------------------------------------------------------------

RESULTS_KEYS = [
    "schema",
    "tool",
    "run",
    "rule",
    "provenance",
    "sides",
    "plan",
    "machine_state",
    "cases",
    "comparisons",
    "same_vs_same",
    "twin_checks",
    "controls",
    "launch_cost",
    "env_pad",
    "series",
    "plots",
    "diagnostics",
    "refusals",
    "notes",
    "plugins",
    "figures",
    "artifacts",
]

COMPARISON_KEYS = [
    "case",
    "primary",
    "subject",
    "baseline",
    "n_rounds",
    "n_unpaired",
    "n_untied",
    "n_lower",
    "n_higher",
    "subject_median",
    "baseline_median",
    "ratio",
    "statistic",
    "scale",
    "gap",
    "floor",
    "bar",
    "p_raw",
    "p_raw_fraction",
    "p_corrected",
    "verdict",
    "outcome",
    "reason",
    "reasons",
    "order_split",
    "sensitivity",
]


def test_the_example_results_document_validates(example_results: dict[str, Any]) -> None:
    assert list(example_results) == RESULTS_KEYS
    assert list(example_results["comparisons"][0]) == COMPARISON_KEYS
    assert _errors("results", example_results) == []


def test_the_example_results_survive_a_round_trip(example_results: dict[str, Any]) -> None:
    results = Results.from_json(example_results)
    written = results.to_json()
    assert list(written) == RESULTS_KEYS
    assert list(written["comparisons"][0]) == COMPARISON_KEYS
    assert _contains(written, example_results)
    assert "energy" not in written
    assert _errors("results", written) == []
    assert Results.from_json(written) == results
    assert Results.from_json(written).to_json() == written
    assert json.loads(json.dumps(written)) == written


def test_the_example_results_are_read_into_the_model(example_results: dict[str, Any]) -> None:
    results = Results.from_json(example_results)
    assert results.schema == "pairbench/results/v1"
    assert results.run.command is not None
    assert results.run.captures[0].rounds == 16
    assert results.rule.family_size == 2
    assert (results.plan.launches, results.plan.explain_launches) == (82, 4)
    comparison = results.comparison("matmul")
    assert comparison is results.comparison("matmul", "new")
    assert (comparison.ratio, comparison.statistic, comparison.scale) == (0.797, 0.797, "ratio")
    assert comparison.gap == 0.203
    assert comparison.floor.unit == "fraction"
    assert comparison.floor.source == "twins"
    assert comparison.floor.subject is not None
    assert comparison.floor.subject.value == 0.011
    assert comparison.p_raw_fraction == (34, 65536)
    assert (comparison.verdict, comparison.outcome, comparison.reason) == ("FASTER", "better", None)
    assert comparison.reasons == ()
    assert comparison.order_split == (8, 8)
    assert comparison.sensitivity.agrees is True
    assert results.figures["matmul.new_vs_old.ratio"].value == 0.797
    assert results.figures["matmul.new_vs_old.verdict"].value == "better"
    assert results.figures["matmul.new_vs_old.verdict"].text == "FASTER"
    assert results.energy is None
    with pytest.raises(KeyError):
        results.comparison("made_up")


def test_a_results_document_without_the_optional_keys_validates_and_is_read(
    example_results_required_only: dict[str, Any],
) -> None:
    document = example_results_required_only
    assert "command" not in document["run"]
    assert "statistic" not in document["comparisons"][0]
    assert _errors("results", document) == []
    results = Results.from_json(document)
    comparison = results.comparisons[0]
    assert results.run.command is None
    assert (comparison.statistic, comparison.scale, comparison.reasons) == (None, "ratio", ())
    assert comparison.floor.unit == "fraction"
    assert results.same_vs_same[0].unit == "fraction"
    assert results.machine_state.discard_sha256 is None
    assert results.sides[0].image_ref is None
    assert results.provenance.driver is None
    assert _contains(results.to_json(), document)


def test_a_results_document_with_every_key_validates_and_survives_a_round_trip(
    example_results_every_key: dict[str, Any],
) -> None:
    document = example_results_every_key
    assert _errors("results", document) == []
    results = Results.from_json(document)
    assert results.energy is not None
    assert results.energy.scope == "gpu"
    assert results.energy.excludes == (
        "cpu",
        "memory",
        "storage",
        "cooling",
        "power supply losses",
    )
    assert results.machine_state.status == "busy"
    assert results.machine_state.discard_sha256 == "a" * 64
    assert results.machine_state.degraded[0].status == "unavailable"
    assert results.sides[0].image_ref == "registry.example/org/app:2.0"
    assert results.provenance.driver is not None
    assert results.provenance.driver.name == "lines"
    assert results.provenance.driver.tool_versions == ("0.0.0",)
    assert results.comparisons[0].sensitivity.not_computed == "too_few_rounds"
    assert results.notes[0].code == "floor_provisional"
    written = results.to_json()
    assert list(written) == [*RESULTS_KEYS, "energy"]
    assert written["energy"] == {
        "scope": "gpu",
        "excludes": ["cpu", "memory", "storage", "cooling", "power supply losses"],
    }
    assert _contains(written, document)
    assert _errors("results", written) == []
    assert Results.from_json(written) == results


@pytest.mark.parametrize(
    "key", ["schema", "tool", "run", "plan", "comparisons", "figures", "artifacts", "plugins"]
)
def test_a_results_document_without_a_required_key_is_refused(
    example_results: dict[str, Any], key: str
) -> None:
    del example_results[key]
    assert _errors("results", example_results) == [f"'{key}' is a required property"]
    with pytest.raises(Refusal, match=f"missing key '{key}'") as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("comparisons", 0, "outcome", "faster"), "'faster' is not one of"),
        (("comparisons", 0, "reason", "made_up"), "'made_up' is not one of"),
        (("comparisons", 0, "scale", "log"), "'log' is not one of ['ratio', 'percent']"),
        (("comparisons", 0, "floor", "unit", "ppm"), "'ppm' is not one of ['fraction', 'percent']"),
        (("machine_state", "status", "idle"), "'idle' is not one of ['quiet', 'busy', 'unknown']"),
        (("schema", "pairbench/results/v2"), "'pairbench/results/v1' was expected"),
        (("refusals", 0, "scope", "side"), "'side' is not one of ['experiment', 'case']"),
        (("refusals", 0, "code", "grid"), "'grid' does not match"),
    ],
)
def test_a_results_document_with_a_value_outside_its_vocabulary_fails_schema_and_model(
    example_results: dict[str, Any], change: tuple[Any, ...], message: str
) -> None:
    target: Any = example_results
    for part in change[:-2]:
        target = target[part]
    target[change[-2]] = change[-1]
    found = _errors("results", example_results)
    assert len(found) == 1
    assert message in found[0]
    with pytest.raises(Refusal, match="not a valid Results") as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("key", "value", "message", "words"),
    [
        (
            "prefix",
            "/made/up/prefix",
            "Additional properties are not allowed ('prefix' was unexpected)",
            "a results document may not show prefix",
        ),
        (
            "identify_output",
            "made-up output",
            "Additional properties are not allowed ('identify_output' was unexpected)",
            "a results document may not show identify_output",
        ),
        (
            "digests",
            ["registry.example/org/app@sha256:" + "b" * 64],
            "does not match",
            "ResultsSide.identity.digests: expected a list of hashes",
        ),
        (
            "image_id",
            "registry.example/org/app:2.0",
            "does not match",
            "ResultsSide.identity.image_id: expected a hash",
        ),
        (
            "packages_sha256",
            "/made/up/path",
            "does not match",
            "ResultsSide.identity.packages_sha256: expected a hash",
        ),
        ("platform", 7, "is not of type 'string'", "ResultsSide.identity.platform: expected text"),
    ],
)
def test_a_results_side_may_show_only_identity_that_does_not_identify_a_machine(
    example_results: dict[str, Any], key: str, value: Any, message: str, words: str
) -> None:
    example_results["sides"][0]["identity"][key] = value
    found = _errors("results", example_results)
    assert len(found) == 1
    assert message in found[0]
    with pytest.raises(Refusal, match=words) as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("path", "value", "words"),
    [
        (("sides", 0, "kind"), "made-up-kind", "ResultsSide.kind"),
        (("provenance", "driver"), {"name": "made-up-driver", "tool_versions": []}, "DriverInfo"),
        (
            ("machine_state", "gates"),
            [{"name": "made-up-check", "mode": "warn", "status": "pass"}],
            "GateSummary.name",
        ),
        (
            ("machine_state", "degraded"),
            [{"name": "made-up-check", "status": "fail", "message": ""}],
            "Degraded.name",
        ),
    ],
)
def test_a_results_document_cannot_carry_a_name_a_plug_in_chose(
    example_results: dict[str, Any], path: tuple[Any, ...], value: Any, words: str
) -> None:
    target: Any = example_results
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    assert len(_errors("results", example_results)) >= 1
    with pytest.raises(Refusal, match=words) as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("comparisons", 0, "ratio"), float("nan")),
        (("comparisons", 0, "p_raw"), float("inf")),
        (("comparisons", 0, "floor", "subject", "value"), float("-inf")),
        (("figures", "matmul.new_vs_old.ratio", "value"), float("nan")),
    ],
)
def test_a_results_document_holds_no_number_that_is_not_finite(
    example_results: dict[str, Any], path: tuple[Any, ...], value: float
) -> None:
    target: Any = example_results
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(Refusal, match="expected a finite number") as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


def test_a_figure_value_is_a_number_or_a_text(example_results: dict[str, Any]) -> None:
    example_results["figures"]["matmul.new_vs_old.n"] = {"value": 16, "text": "16"}
    assert _errors("results", example_results) == []
    example_results["figures"]["matmul.new_vs_old.n"] = {"value": None, "text": ""}
    assert len(_errors("results", example_results)) == 1


def test_an_unknown_key_in_a_results_document_fails_the_schema_and_is_ignored_by_the_model(
    example_results: dict[str, Any],
) -> None:
    before = Results.from_json(copy.deepcopy(example_results))
    example_results["made_up"] = 1
    assert _errors("results", example_results) == [
        "Additional properties are not allowed ('made_up' was unexpected)"
    ]
    assert Results.from_json(example_results) == before


# ---------------------------------------------------------------------------
# The config
# ---------------------------------------------------------------------------


def test_the_example_configs_validate(
    example_config: dict[str, Any], example_serving_config: dict[str, Any]
) -> None:
    assert _errors("config", example_config) == []
    assert _errors("config", example_serving_config) == []


def test_the_resolved_config_validates(
    example_config: dict[str, Any], example_serving_config: dict[str, Any]
) -> None:
    for given in (example_config, example_serving_config):
        resolved = Experiment.from_json(given).to_json()
        assert _errors("config", resolved) == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("run", "made_up"), 1),
        (("made_up",), {}),
        (("sides", "new", "made_up"), 1),
        (("launch", "made_up"), 1),
        (("rule", "alpha"), 0.01),
        (("run", "rounds"), 0),
        (("gates", "mode"), "strict"),
        (("rule", "fail_on"), ["sometimes"]),
        (("workload", "level_kind"), "speed"),
        (("workload", "levels"), [0]),
        (("workload", "levels"), [8, 8]),
        (("workload", "levels"), "0,8"),
        (("workload", "levels"), "8,"),
        (("launch", "cpus"), "four"),
        (("launch", "timeout"), "soon"),
        (("gates", "quiet", "samples"), 0),
        (("gates", "quiet", "samples"), -1),
        (("gates", "quiet", "interval_s"), -1),
        (("gates", "quiet", "max_wait_s"), -1),
        (("gates", "quiet", "max_busy_cores"), -0.5),
        (("gates", "census", "max_busy_cores"), -0.5),
        (("gates", "discard", "max_busy_cores"), -0.5),
        (("gates", "lock_timeout"), -5),
        (("energy", "interval_s"), 0),
        (("energy", "interval_s"), -0.2),
        (("energy", "min_samples"), 1),
        (("energy", "min_samples"), 0),
        (("run", "warmups"), -1),
        (("run", "budget"), -1),
        (("run", "budget"), "1e3"),
        (("run", "budget"), "+5"),
        (("workload", "driver"), ""),
        (("rule", "name"), ""),
        (("sides", "new", "image"), ""),
        (("launch", "gpus"), ["0"]),
        (("launch", "gpus"), [-1]),
        (("launch", "gpus"), []),
        (("launch", "gpus"), "ALL"),
    ],
)
def test_a_config_the_model_refuses_also_fails_the_schema(
    example_config: dict[str, Any], path: tuple[str, ...], value: Any
) -> None:
    table = example_config
    for part in path[:-1]:
        table = table.setdefault(part, {})
    table[path[-1]] = value
    assert _errors("config", example_config) != []
    with pytest.raises(Refusal) as caught:
        Experiment.from_json(example_config)
    assert caught.value.code == "E_CONFIG"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("gates", "quiet", "samples"), 1),
        (("gates", "quiet", "interval_s"), 0),
        (("gates", "quiet", "max_wait_s"), 0),
        (("gates", "quiet", "max_busy_cores"), 0),
        (("gates", "discard", "max_busy_cores"), 0),
        (("gates", "lock_timeout"), 0),
        (("energy", "interval_s"), 0.01),
        (("energy", "min_samples"), 2),
        (("run", "warmups"), 0),
        (("run", "budget"), " 90s "),
        (("run", "budget"), "1.5h"),
        (("run", "budget"), 0),
        (("launch", "gpus"), [0, 1]),
        (("launch", "gpus"), 0),
        (("launch", "gpus"), "all"),
        (("launch", "cpus"), 3),
    ],
)
def test_a_value_at_its_limit_is_taken_by_schema_and_model(
    example_config: dict[str, Any], path: tuple[str, ...], value: Any
) -> None:
    table = example_config
    for part in path[:-1]:
        table = table.setdefault(part, {})
    table[path[-1]] = value
    assert _errors("config", example_config) == []
    Experiment.from_json(example_config)


@pytest.mark.parametrize(
    ("serve", "words"),
    [
        ({"image": "myorg/server:2.0", "port": 0}, "sides.new.serve.port: expected at least 1"),
        (
            {"image": "myorg/server:2.0", "port": 65536},
            "sides.new.serve.port: expected at most 65535",
        ),
        ({"image": ""}, "sides.new.serve.image: expected a text of at least 1 characters"),
        (
            {"image": "myorg/server:2.0", "command": ["server"]},
            "sides.new.serve.image or sides.new.serve.command: give exactly one",
        ),
        ({}, "sides.new.serve.image or sides.new.serve.command: give exactly one"),
        ({"command": []}, "sides.new.serve.command must not be empty"),
    ],
)
def test_a_serving_side_the_model_refuses_also_fails_the_schema(
    example_serving_config: dict[str, Any], serve: dict[str, Any], words: str
) -> None:
    example_serving_config["sides"]["new"]["serve"] = serve
    assert _errors("config", example_serving_config) != []
    with pytest.raises(Refusal, match=words) as caught:
        Experiment.from_json(example_serving_config)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2


def test_a_number_that_is_not_finite_inside_a_free_table_of_the_config_is_a_config_error(
    example_serving_config: dict[str, Any],
) -> None:
    example_serving_config["sides"]["new"]["serve"]["probe"] = {
        "body": {"temperature": float("inf")}
    }
    words = r"Probe\.body\.temperature: expected a finite number"
    with pytest.raises(Refusal, match=words) as caught:
        Experiment.from_json(example_serving_config)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2


def test_a_serving_side_started_as_a_host_process_takes_a_command(
    example_serving_config: dict[str, Any],
) -> None:
    for name in ("new", "old"):
        example_serving_config["sides"][name]["serve"] = {
            "command": ["server", "--port", "8000"],
            "launcher": "host",
            "port": 65535,
        }
    assert _errors("config", example_serving_config) == []
    spec = Experiment.from_json(example_serving_config).side("new").serve_spec()
    assert (spec.image, spec.command, spec.launcher, spec.port) == (
        None,
        ("server", "--port", "8000"),
        "host",
        65535,
    )


def test_a_side_name_with_the_reserved_character_fails_schema_and_model(
    example_config: dict[str, Any],
) -> None:
    example_config["sides"]["new~same"] = {"image": "myorg/app:2.0"}
    assert _errors("config", example_config) != []
    with pytest.raises(Refusal) as caught:
        Experiment.from_json(example_config)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


# ---------------------------------------------------------------------------
# What a results document may show of a capture
# ---------------------------------------------------------------------------


def test_the_machine_facts_a_results_document_may_show(
    example_capture_records: list[dict[str, Any]],
) -> None:
    capture = Capture.from_records(example_capture_records)
    assert capture.machine is not None
    summary = capture.machine.summary()
    assert summary.to_json() == {
        "os": "Linux 0.0",
        "arch": "arch-a",
        "cpu_model": "cpu-model-a",
        "core_types": ["core-type-a"],
    }


def test_a_machine_check_is_shown_without_its_detail(
    example_capture_records: list[dict[str, Any]],
) -> None:
    passed = Capture.from_records(example_capture_records).gates[0]
    assert passed.summary().to_json() == {"name": "quiet", "mode": "warn", "status": "pass"}
    assert passed.degraded() is None
    failed = model.GateRecord(
        name="census",
        mode="warn",
        status="unavailable",
        detail={"message": "a made-up reason", "neighbours": ["made-up-container"]},
    )
    shown = failed.degraded()
    assert shown is not None
    assert shown.to_json() == {
        "name": "census",
        "status": "unavailable",
        "message": "a made-up reason",
    }
    silent = model.GateRecord(name="quiet", mode="enforce", status="fail")
    assert silent.degraded() == model.Degraded(name="quiet", status="fail", message="")


def test_a_name_that_a_plug_in_chose_is_never_shown() -> None:
    gate = model.GateRecord(name="made-up-check", mode="warn", status="degraded")
    assert gate.summary().name == "plugin"
    degraded = gate.degraded()
    assert degraded is not None
    assert degraded.name == "plugin"
    side = Side(name="new", kind="made-up-kind", spec={"spec": "anything"})
    assert side.for_results().kind == "plugin"
    assert Side.parse("new=image:myorg/app:2.0").for_results().kind == "image"
    assert Side(name="new", kind="rows").for_results().kind == "rows"


def test_the_capture_entry_of_a_results_document(
    example_capture_records: list[dict[str, Any]],
) -> None:
    source = Source(path="capture.jsonl", sha256="c" * 64)
    capture = Capture.from_records(example_capture_records, source=source)
    assert capture.ref().to_json() == {
        "capture_id": "cap-000001",
        "sha256": "c" * 64,
        "rounds": 16,
    }
    unfinished = Capture.from_records(example_capture_records[:-1])
    assert unfinished.ref().to_json() == {"capture_id": "cap-000001", "sha256": None, "rounds": 1}


def test_the_driver_a_results_document_shows(
    example_capture_records: list[dict[str, Any]],
    example_capture_additions: list[dict[str, Any]],
) -> None:
    assert Capture.from_records(example_capture_records).driver_info() is None
    example_capture_records[0]["config"] = {"workload": {"driver": "gbench"}}
    named = Capture.from_records(example_capture_records[:-1] + example_capture_additions)
    assert named.driver_info() == model.DriverInfo(name="gbench", tool_versions=("0.0.0",))
    example_capture_records[0]["config"] = {"workload": {"driver": "made-up-driver"}}
    hidden = Capture.from_records(example_capture_records).driver_info()
    assert hidden == model.DriverInfo(name=None, tool_versions=())
