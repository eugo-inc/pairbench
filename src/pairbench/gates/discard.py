# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The decision on disturbed rounds.

A launch is disturbed when a witness exceeds its threshold, or its probe
failed; a disturbed launch marks its whole round. The decision is
``pairbench.model.set_aside``, called here unchanged. Its input,
``RoundWitness``, carries a round, an entry name and a witness, and no
measured value, so the decision cannot depend on one.
"""

from __future__ import annotations

from collections.abc import Sequence

from pairbench.model import (
    NOTE_WITNESS_FAILED,
    WITNESSES_WITH_THRESHOLD,
    DiscardThresholds,
    RoundWitness,
    SetAside,
    Witness,
    set_aside,
)

_WHAT = {
    "busy_cores": "the busy cores of the machine",
    "busy_cores_cache": "the busy cores on the CPUs sharing a cache with the pinned set",
    "gpu_other_processes": "the other compute processes on the selected GPUs",
    "gpu_throttle_events": "the GPU throttle events",
}


def decide(thresholds: DiscardThresholds, witnesses: Sequence[RoundWitness]) -> SetAside:
    """Return the rounds set aside and the hash of the decision, as the model decides them."""
    return set_aside(thresholds, witnesses)


def witness_notes(name: str, round_number: int, witness: Witness) -> list[tuple[str, str]]:
    """The loud notes for the probes that failed during one launch, one per witness.

    A failed probe of a witness with a threshold counts as exceeding it, so
    its note says the round is marked as disturbed. The witness on the CPUs
    that share a cache has no threshold and its note says so.
    """
    notes: list[tuple[str, str]] = []
    for failed in witness.failed:
        effect = (
            "the round is marked as disturbed"
            if failed in WITNESSES_WITH_THRESHOLD
            else "this witness has no threshold and marks nothing"
        )
        notes.append(
            (
                NOTE_WITNESS_FAILED,
                f"{_WHAT.get(failed, failed)} could not be read during the launch of {name} "
                f"in round {round_number}; {effect}",
            )
        )
    return notes
