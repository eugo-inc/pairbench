# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench selftest``: the known answers and the controls of the statistics.

Every control is printed with its result. ``--live`` adds a tiny real run on
this machine: two command sides that print their own values, one twice the
other, measured, analysed and checked against that factor. Any control
that fails makes the exit code 1.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pairbench.cli.common import emit, say
from pairbench.errors import EXIT_CHECK_FAILED, EXIT_OK, Refusal

if TYPE_CHECKING:
    from pairbench.model import Experiment

LIVE_ID: Final = "L1"
LIVE_TITLE: Final = "a real run of two command sides reads the factor it was built with"
LIVE_FACTOR: Final = 2.0
# The workload of the live run: it prints its values as the ``lines`` driver reads them.
LIVE_SCRIPT: Final = (
    "import json, sys\n"
    "factor = float(sys.argv[1])\n"
    "for case, base in (('live-a', 0.25), ('live-b', 0.75)):\n"
    "    value = {'case': case, 'value': base * factor, 'unit': 's', 'better': 'lower'}\n"
    "    print('::pairbench:: ' + json.dumps(value))\n"
)


@dataclass(frozen=True)
class Outcome:
    """One control as the command prints it."""

    id: str
    title: str
    passed: bool
    detail: str


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``--live`` adds the tiny real run."""
    parser.add_argument(
        "--live", action="store_true", help="add a tiny real run with two command sides"
    )


def _line(outcome: Outcome) -> str:
    word = "pass" if outcome.passed else "FAIL"
    tail = "" if outcome.passed or not outcome.detail else f": {outcome.detail}"
    return f"{word}  {outcome.id:<4} {outcome.title}{tail}"


def live_experiment(folder: Path) -> Experiment:
    """The experiment of the live run, writing into ``folder``."""
    from pairbench import config

    sides = [
        f"subject=cmd:{_quote(sys.executable)} -c {_quote(LIVE_SCRIPT)} {LIVE_FACTOR}",
        f"baseline=cmd:{_quote(sys.executable)} -c {_quote(LIVE_SCRIPT)} 1.0",
    ]
    flags = config.flag_config(
        {
            "--driver": "lines",
            "--gates": "off",
            "--explain": "off",
            "--plots": "off",
            "--out": str(folder),
        },
        sides=sides,
        baseline="baseline",
    )
    return config.load_experiment(
        None,
        environ={},
        flags=flags,
        sets=["launch_cost.launches=0", "report.html=false"],
    )


def _quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


def live_check() -> Outcome:
    """Run the live experiment and check what it read."""
    import pairbench

    with tempfile.TemporaryDirectory(prefix="pairbench-selftest-") as scratch:
        try:
            experiment = live_experiment(Path(scratch) / "run")
            capture = pairbench.run(experiment, out=Path(scratch) / "run")
            results = pairbench.analyse(capture, rule=experiment.rule.name)
        except Refusal as refusal:
            return Outcome(LIVE_ID, LIVE_TITLE, False, f"the run was refused: {refusal.line}")
    found = {(c.case, c.subject): c.ratio for c in results.comparisons if c.primary}
    wanted = {("live-a", "subject"): LIVE_FACTOR, ("live-b", "subject"): LIVE_FACTOR}
    if found != wanted:
        return Outcome(LIVE_ID, LIVE_TITLE, False, f"expected ratios {wanted}, found {found}")
    control = results.controls.positive
    if control.status != "ok":
        return Outcome(LIVE_ID, LIVE_TITLE, False, f"the positive control is {control.status}")
    return Outcome(LIVE_ID, LIVE_TITLE, True, f"ratio {LIVE_FACTOR} on both cases")


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench selftest``."""
    from pairbench.api import RunSelftest, delegate

    run_selftest: RunSelftest = delegate("selftest")
    outcomes = [Outcome(r.id, r.title, r.passed, r.detail) for r in run_selftest()]
    if options.live:
        outcomes.append(live_check())
    emit("\n".join(_line(outcome) for outcome in outcomes))
    failed = [outcome for outcome in outcomes if not outcome.passed]
    if failed:
        say(f"selftest: {len(failed)} of {len(outcomes)} controls failed")
        return EXIT_CHECK_FAILED
    say(f"selftest: all {len(outcomes)} controls passed")
    return EXIT_OK


__all__ = ["LIVE_FACTOR", "add_arguments", "command", "live_check", "live_experiment"]
