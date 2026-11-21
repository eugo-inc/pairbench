# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench plan``: print the plan of an experiment and exit.

The plan creates no folder, takes no lock, starts no container and pulls
nothing. It runs the checks that need no launch and the read-only identity
look-ups, then prints the plan on standard output.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from pairbench.cli.common import add_experiment_arguments, emit, experiment_from, refuse_file_sides
from pairbench.errors import EXIT_OK

if TYPE_CHECKING:
    from pairbench.model import Experiment


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The flags of ``pairbench run``; the workload follows ``--``."""
    add_experiment_arguments(parser)


def print_plan(experiment: Experiment) -> int:
    """Look up the sides, lay out the plan and print it. Exit code 0.

    What the run would refuse before any launch is refused here too:
    ``--plots on`` without the ``plot`` extra is ``E_PLOT_EXTRA_MISSING``.
    """
    import pairbench
    from pairbench import api
    from pairbench.api import LookUpSides, delegate
    from pairbench.plan import format_plan

    refuse_file_sides(experiment)
    api.require_plot_extra(experiment.plots.mode)
    look_up: LookUpSides = delegate("look_up")
    lookups = look_up(experiment)
    plan = pairbench.plan(experiment)
    emit(format_plan(plan, experiment, lookups=lookups))
    return EXIT_OK


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench plan``."""
    return print_plan(experiment_from(options))


__all__ = ["add_arguments", "command", "print_plan"]
