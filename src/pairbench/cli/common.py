# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What several commands share: the flags of an experiment, the outputs, the fail-on rule."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO, get_args

from pairbench.errors import EXIT_CHECK_FAILED, EXIT_OK, Refusal, printable
from pairbench.model import (
    CONTROL_MODES,
    EXPLAIN_MODES,
    FAIL_ON,
    FLAG_KEYS,
    GATE_MODES,
    KIND_FILE,
    PLOT_MODES,
    Engine,
    PullPolicy,
)

if TYPE_CHECKING:
    from pairbench.model import Experiment, Results

# The words each flag of a closed set accepts; any other word is ``E_USAGE``.
CHOICES: Final[dict[str, tuple[str, ...]]] = {
    "--engine": get_args(Engine),
    "--pull": get_args(PullPolicy),
    "--gates": GATE_MODES,
    "--fail-on": FAIL_ON,
    "--explain": EXPLAIN_MODES,
    "--plots": PLOT_MODES,
    "--positive-control": CONTROL_MODES,
}

METAVARS: Final[dict[str, str]] = {
    "--driver": "NAME",
    "--case": "GLOB",
    "--levels": "LIST",
    "--level-duration": "DURATION",
    "--rounds": "N|auto",
    "--budget": "DURATION",
    "--warmups": "K",
    "--same-vs-same": "on|off|NAME,...",
    "--cpus": "LIST",
    "--gpus": "SPEC",
    "--timeout": "DURATION",
    "--lock": "PATH",
    "--lock-timeout": "DURATION",
    "--rule": "NAME",
    "--out": "DIR",
}


def add_experiment_arguments(parser: argparse.ArgumentParser) -> None:
    """Add every flag of ``pairbench run``: ``model.FLAG_KEYS`` and the flags without a key."""
    from pairbench.config import REPEATED_FLAGS, SWITCH_FLAGS

    parser.add_argument(
        "--side", action="append", default=[], metavar="NAME=KIND:SPEC", help="a side (repeat)"
    )
    parser.add_argument("--baseline", action="append", default=[], metavar="NAME")
    parser.add_argument("--config", metavar="FILE", help="the config file to read")
    parser.add_argument(
        "--set", action="append", default=[], dest="sets", metavar="KEY=VALUE", help="(repeat)"
    )
    for flag, key in FLAG_KEYS.items():
        options: dict[str, Any] = {"dest": flag, "default": None, "help": f"sets {key}"}
        if flag in SWITCH_FLAGS:
            options.update(action="store_const", const=True)
        elif flag in REPEATED_FLAGS:
            options.update(action="append")
        if flag in CHOICES:
            options["choices"] = CHOICES[flag]
        if flag in METAVARS:
            options["metavar"] = METAVARS[flag]
        parser.add_argument(flag, **options)


def one_baseline(options: argparse.Namespace) -> str | None:
    """The name after ``--baseline``; two different names are ``E_USAGE``."""
    names = list(dict.fromkeys(options.baseline or []))
    if len(names) > 1:
        raise Refusal("E_USAGE", f"--baseline names more than one side: {', '.join(names)}")
    return names[0] if names else None


def experiment_from(options: argparse.Namespace) -> Experiment:
    """Build the experiment of a ``run`` or ``plan`` command from every source."""
    from pairbench import config, registry

    given = {flag: getattr(options, flag) for flag in FLAG_KEYS}
    flags = config.flag_config(
        {flag: value for flag, value in given.items() if value is not None},
        sides=options.side,
        baseline=one_baseline(options),
        workload=options.after or None,
    )
    path = Path(options.config) if options.config else None
    experiment = config.load_experiment(path, flags=flags, sets=options.sets)
    if experiment.run.no_plugins:
        registry.set_plugins_enabled(False)
    return experiment


def refuse_file_sides(experiment: Experiment) -> None:
    """``run`` and ``plan`` launch sides; result files are compared with ``pairbench compare``."""
    files = [side.name for side in experiment.sides if side.kind == KIND_FILE]
    if files:
        raise Refusal(
            "E_USAGE",
            "sides that are result files are compared with pairbench compare, not planned or "
            f"run: {', '.join(files)}",
        )


def emit(text: str, stream: TextIO | None = None) -> None:
    """Write a text as it is, ending it with a newline when it has none."""
    out = sys.stdout if stream is None else stream
    out.write(text if text.endswith("\n") or not text else text + "\n")
    out.flush()


def say(message: str) -> None:
    """Print one line of the command's own on standard error, with each control character of
    the message escaped, as a refusal's line has it."""
    print(f"pairbench: {printable(message)}", file=sys.stderr)


def print_note(code: str, message: str) -> None:
    """Print a loud note on standard error."""
    from pairbench.api import note_line

    print(note_line(code, message), file=sys.stderr)


# The note printed once by a run that wrote results: what the shared files show of the command.
NOTE_COMMAND_SHOWN: Final = "command_shown"


def command_shown_message() -> str:
    """The message of ``NOTE_COMMAND_SHOWN``, with the address of the section listing the forms."""
    from pairbench.errors import CONFIG_PAGE, SHARED_COMMAND_ANCHOR, section_address
    from pairbench.model import TOOL_VERSION

    address = section_address(CONFIG_PAGE, SHARED_COMMAND_ANCHOR, TOOL_VERSION)
    return (
        "results.json, results.md and report.html show the command with each --side spec, "
        "each --set value and the secret forms pairbench recognises hidden, and each absolute "
        "path cut to its last part (report.include_image_refs shows image references); put "
        f"secrets in environment variables: {address}"
    )


def print_command_note() -> None:
    """Print ``NOTE_COMMAND_SHOWN`` on standard error, once per run that wrote results."""
    print_note(NOTE_COMMAND_SHOWN, command_shown_message())


def fail_on_code(results: Results, fail_on: Sequence[str]) -> int:
    """Exit code 1 when a primary case has an outcome named to fail on, else 0.

    Each matching case is named on standard error.
    """
    wanted = set(fail_on)
    matched = [c for c in results.comparisons if c.primary and c.outcome in wanted]
    for comparison in matched:
        say(
            f"--fail-on {comparison.outcome}: case {comparison.case} of side "
            f"{comparison.subject} against {comparison.baseline}"
        )
    return EXIT_CHECK_FAILED if matched else EXIT_OK


def relative_to(folder: Path, paths: Sequence[Path]) -> tuple[str, ...]:
    """Name files by their path relative to a run folder, as ``Artifacts`` keeps them."""
    out: list[str] = []
    for path in paths:
        try:
            out.append(Path(path).resolve().relative_to(folder.resolve()).as_posix())
        except ValueError:
            out.append(Path(path).as_posix())
    return tuple(out)


__all__ = [
    "CHOICES",
    "NOTE_COMMAND_SHOWN",
    "add_experiment_arguments",
    "command_shown_message",
    "emit",
    "experiment_from",
    "fail_on_code",
    "one_baseline",
    "print_command_note",
    "print_note",
    "refuse_file_sides",
    "relative_to",
    "say",
]
