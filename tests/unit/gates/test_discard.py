# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The decision on disturbed rounds and the notes for witnesses that failed."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

from pairbench.gates.base import HostChecks
from pairbench.gates.discard import decide, witness_notes
from pairbench.model import (
    WITNESSES,
    Capture,
    DiscardThresholds,
    RoundWitness,
    Witness,
    set_aside,
)

THRESHOLDS = DiscardThresholds(max_busy_cores=2.0)

# round, entry, witness as a launch record holds it
LAUNCHES: list[tuple[int, str, dict[str, Any]]] = [
    (1, "new", {"busy_cores": 0.25}),
    (1, "old", {"busy_cores": 0.5, "busy_cores_cache": 0.25}),
    (2, "new", {"busy_cores": 0.75}),
    (2, "old", {"busy_cores": 3.5}),  # above the threshold
    (3, "new", {"busy_cores": 0.25, "failed": ["gpu_other_processes"]}),  # probe failed
    (3, "old", {"busy_cores": 0.25}),
    (4, "new", {"busy_cores": 0.5, "busy_cores_cache": 9.0}),  # no threshold of its own
    (4, "old", {"busy_cores": 1.5, "gpu_throttle_events": 0}),
    (5, "new", {"busy_cores": 0.25, "gpu_throttle_events": 1}),  # one throttle event
    (5, "old", {}),  # nothing applied
]
DISTURBED = (2, 3, 5)


def _records(example: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The example capture with its launches replaced by the ones above."""
    kept = [r for r in example if r["t"] not in ("launch", "obs")]
    for record in kept:
        if record["t"] == "lineup":
            record["names"] = ["new", "old"]
            record["control"] = None
            record["discard_thresholds"] = THRESHOLDS.to_json()
    added: list[dict[str, Any]] = []
    for seq, (rnd, name, witness) in enumerate(LAUNCHES, start=1):
        pos = 1 if name == "new" else 2
        added.append(
            {
                "t": "launch",
                "seq": seq,
                "phase": "round",
                "round": rnd,
                "pos": pos,
                "name": name,
                "rc": 0,
                "timing": {"launch_s": 1.5 + seq, "run_s": 1.25 + seq},
                "witness": witness,
                "energy": None,
            }
        )
        added.append(
            {
                "t": "obs",
                "seq": seq,
                "round": rnd,
                "pos": pos,
                "name": name,
                "case": "wall",
                "value": 1.25 + seq,
                "n_inner": 1,
                "reducer": "identity",
            }
        )
    end = [r for r in kept if r["t"] == "end"]
    rest = [r for r in kept if r["t"] != "end"]
    return rest + added + end


def _alter_every_measured_value(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    altered = copy.deepcopy(records)
    for record in altered:
        if record["t"] == "launch":
            record["timing"] = {k: v * 97.0 + 13.0 for k, v in record["timing"].items()}
        elif record["t"] == "obs":
            record["value"] = record["value"] * -31.0 - 7.0
    return altered


def _round_witnesses(capture: Capture) -> list[RoundWitness]:
    return [
        RoundWitness(round=x.round, name=x.name, witness=Witness.from_json(x.witness))
        for x in capture.round_launches()
    ]


def test_disturbed_rounds_are_the_ones_a_witness_marks(
    example_capture_records: list[dict[str, Any]],
) -> None:
    capture = Capture.from_records(_records(example_capture_records))
    decision = decide(THRESHOLDS, _round_witnesses(capture))
    assert decision.rounds == DISTURBED
    assert decision == set_aside(THRESHOLDS, _round_witnesses(capture))
    assert decision == capture.set_aside()


def test_mutant_the_decision_to_set_a_round_aside_reads_no_measured_value(
    example_capture_records: list[dict[str, Any]],
) -> None:
    """Every measured value and timing is altered; the rounds and the hash stay the same."""
    records = _records(example_capture_records)
    altered = _alter_every_measured_value(records)
    original = Capture.from_records(records)
    changed = Capture.from_records(altered)
    assert [o.value for o in changed.observations] != [o.value for o in original.observations]
    assert [x.timing for x in changed.launches] != [x.timing for x in original.launches]
    first = decide(THRESHOLDS, _round_witnesses(original))
    second = decide(THRESHOLDS, _round_witnesses(changed))
    assert second == first
    assert second.rounds == DISTURBED
    assert changed.set_aside() == original.set_aside() == first


def test_the_decision_takes_a_type_with_no_measurement_fields() -> None:
    assert [f.name for f in dataclasses.fields(RoundWitness)] == ["round", "name", "witness"]
    assert [f.name for f in dataclasses.fields(Witness)] == [
        *WITNESSES,
        "failed",
        "includes_launch",
    ]


def test_the_thresholds_change_the_decision_and_its_hash() -> None:
    witnesses = [RoundWitness(round=1, name="new", witness=Witness(busy_cores=3.0))]
    strict = decide(THRESHOLDS, witnesses)
    loose = decide(DiscardThresholds(max_busy_cores=4.0), witnesses)
    assert strict.rounds == (1,)
    assert loose.rounds == ()
    assert strict.sha256 != loose.sha256


def test_the_machine_checks_decide_as_the_model_does() -> None:
    witnesses = [
        RoundWitness(round=r, name=n, witness=Witness.from_json(w)) for r, n, w in LAUNCHES
    ]
    checks = HostChecks(root=None, system="linux")
    assert checks.set_aside(THRESHOLDS, witnesses) == set_aside(THRESHOLDS, witnesses)


def test_a_note_for_each_witness_that_failed() -> None:
    witness = Witness(busy_cores=0.5).with_failed("gpu_other_processes", "busy_cores_cache")
    assert witness_notes("old", 3, witness) == [
        (
            "witness_probe_failed",
            "the other compute processes on the selected GPUs could not be read during the "
            "launch of old in round 3; the round is marked as disturbed",
        ),
        (
            "witness_probe_failed",
            "the busy cores on the CPUs sharing a cache with the pinned set could not be read "
            "during the launch of old in round 3; this witness has no threshold and marks nothing",
        ),
    ]


def test_no_note_when_every_witness_was_read_or_did_not_apply() -> None:
    assert witness_notes("new", 1, Witness(busy_cores=0.5)) == []
    assert witness_notes("new", 1, Witness()) == []
