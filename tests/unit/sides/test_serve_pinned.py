# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Which rounds a pinned serving run marks as disturbed.

In a serving launch the server runs on the pinned CPUs and the load tool runs
on the host as a child of the tool, outside the pinned set. In a pinned run
the busy-core witness counts the busy cores outside the pinned set less the
tool's own CPU time, and the tool's own CPU time does not hold the time of
its children. So the load tool's work counts as load of others: a round is
marked when the load tool keeps more cores busy than the threshold, whatever
the server does on its pinned CPUs.

Without pinning, a container serving side reports no CPU time of its own and
the witness counts the launch in: it marks nothing and is undecided instead.
The kernel's counters come from a synthetic ``proc/stat``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pairbench.gates.base import HostWitnessSampler
from pairbench.gates.discard import decide
from pairbench.gates.platform import Root
from pairbench.model import DiscardThresholds, RoundWitness, Witness, undecided

# Six CPUs: the server is pinned to CPUs 4 and 5, CPUs 0 to 3 are outside.
PINNED = frozenset({4, 5})
TICKS = 1000
# Per round, the busy ticks of each CPU outside the pinned set over one
# launch of 1000 ticks a CPU: round 1 keeps 1 core busy outside, round 2
# keeps 3 cores busy, round 3 keeps 2 cores busy, exactly the threshold.
OUTSIDE_BUSY = {1: 250, 2: 750, 3: 500}
OUTSIDE_CORES = {1: 1.0, 2: 3.0, 3: 2.0}
# The rounds the default threshold (2 busy cores) marks.
MARKED_PINNED = (2,)


def _write_stat(root: Path, per_cpu: Mapping[int, tuple[int, int]]) -> None:
    lines = ["cpu  0 0 0 0 0 0 0 0 0 0"]
    lines += [
        f"cpu{c} {busy} 0 0 {idle} 0 0 0 0 0 0" for c, (busy, idle) in sorted(per_cpu.items())
    ]
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "proc" / "stat").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _launch(root: Path, round_number: int, *, pinned: frozenset[int] | None) -> Witness:
    """One serving launch: the server keeps its pinned CPUs fully busy, the load tool the rest."""
    start = dict.fromkeys(range(6), (0, 0))
    _write_stat(root, start)
    clock = iter([0.0, 10.0])
    sampler = HostWitnessSampler(
        root=Root(root),
        clock=lambda: next(clock),
        pinned=pinned,
        gpu=None,
        poll_s=None,
        tool_cpu_s=lambda: 3.0,
    )
    busy = OUTSIDE_BUSY[round_number]
    end = dict.fromkeys(range(4), (busy, TICKS - busy))
    end.update(dict.fromkeys((4, 5), (TICKS, 0)))
    _write_stat(root, end)
    # A container serving side reports no CPU time of its own.
    return sampler.stop(None)


def test_a_pinned_serving_run_marks_the_rounds_its_load_tool_keeps_busy(tmp_path: Path) -> None:
    witnesses = [
        RoundWitness(round=n, name="new", witness=_launch(tmp_path / str(n), n, pinned=PINNED))
        for n in OUTSIDE_BUSY
    ]
    assert {w.round: w.witness.busy_cores for w in witnesses} == OUTSIDE_CORES
    assert all(w.witness.includes_launch == () for w in witnesses)
    assert decide(DiscardThresholds(), witnesses).rounds == MARKED_PINNED


def test_an_unpinned_container_serving_run_marks_nothing_and_is_undecided(
    tmp_path: Path,
) -> None:
    witnesses = [
        RoundWitness(round=n, name="new", witness=_launch(tmp_path / str(n), n, pinned=None))
        for n in OUTSIDE_BUSY
    ]
    # All six CPUs are counted, the server's two busy CPUs and the launch included.
    assert {w.round: w.witness.busy_cores for w in witnesses} == {1: 3.0, 2: 5.0, 3: 4.0}
    assert all(w.witness.includes_launch == ("busy_cores",) for w in witnesses)
    assert decide(DiscardThresholds(), witnesses).rounds == ()
    assert [undecided(w.witness, DiscardThresholds()) for w in witnesses] == [("busy_cores",)] * 3
