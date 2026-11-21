# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench gate``: run machine checks on their own.

``gate check`` runs, under ``enforce``, the CPU check on the pinned set
``--cpus LIST`` gives (the core types of the set, and whether pinning can
be done here), then each readiness check whose key is set: the stop file,
the free GPU memory floor and the check-only locks. With neither it is a
usage error. A check that passed prints its status on standard output; one
that did not pass prints its line on standard error, and the first such
check is refused (``E_GATE_FAILED`` or ``E_GATE_UNAVAILABLE``, exit 4).
``gate wait-quiet -- COMMAND`` runs the command once the machine is quiet
and every readiness check that is on passes, and exits with the command's
own exit code; otherwise the command is not run and the exit code is 4.

Both read the settings ``run`` and ``plan`` read: the config file that
``--config`` or ``PAIRBENCH_CONFIG`` names, the ``PAIRBENCH__`` variables
and ``--set``, checked as strictly, so an unknown key is ``E_CONFIG``. A
flag of the gate command wins over the file and the variables; a flag and
``--set`` that give one key different values are refused, as ``run``
refuses them.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pairbench.cli.common import emit, print_note
from pairbench.errors import EXIT_OK, Refusal

if TYPE_CHECKING:
    from pairbench.model import Experiment, LaunchSettings

# The side the gate commands add to a config that declares none, so that the
# config is read as strictly as run and plan read it. No check sees it.
STAND_IN: Final = "gate"
# The command a side table stands in with when it names no kind of side: run
# takes the kind from --side, which the gate commands do not have.
STAND_IN_COMMAND: Final[tuple[str, ...]] = ("true",)
# The keys of a side table without a kind that the gate commands read.
KINDLESS_KEYS: Final[tuple[str, ...]] = ("baseline", "launch")
# The note of a config whose sides all are result files.
NOTE_SHARED_SETTINGS: Final = "checks_use_shared_settings"
# The refusal of ``gate check`` with no --cpus and no readiness check on.
NOTHING_TO_CHECK: Final = (
    "gate check has nothing to check: give --cpus LIST, or set gates.stop_file, "
    "gates.min_gpu_free_mib or gates.check_locks"
)


def _config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", metavar="FILE", help="the config file to read")
    parser.add_argument(
        "--set", action="append", default=[], dest="sets", metavar="KEY=VALUE", help="(repeat)"
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The two forms: ``check [--cpus LIST]`` and ``wait-quiet -- COMMAND``."""
    forms = parser.add_subparsers(dest="form", metavar="check|wait-quiet")
    forms.required = True
    check = forms.add_parser(
        "check",
        help="the CPU check on a pinned set and the readiness checks that are on",
        allow_abbrev=False,
    )
    check.add_argument("--cpus", metavar="LIST", help="the CPUs to pin to")
    check.add_argument("--allow-mixed-core-types", action="store_true")
    check.add_argument(
        "--json", action="store_true", help="print the record, or the list of records, as JSON"
    )
    _config_arguments(check)
    wait = forms.add_parser(
        "wait-quiet",
        help="run a command once the machine is quiet",
        allow_abbrev=False,
    )
    _config_arguments(wait)


def _experiment(
    options: argparse.Namespace, flags: Mapping[str, Any] | None = None
) -> tuple[Experiment, bool]:
    """The experiment ``run`` would read, with the gate command's own flags in ``flags``.

    The flags lay over the file and the variables, and a flag and ``--set``
    that give one key different values are refused, as ``run`` refuses them.
    The second value says whether the config declares a side; a config that
    declares none is read with the stand-in side ``STAND_IN``. A side table
    that names no kind of side, because ``run --side`` gives the kind, is
    read as a command side with its ``baseline`` and ``launch`` keys; the
    run that gives the kind reads the rest. A key in such a table that no
    kind of side takes is ``E_CONFIG``, as ``run`` refuses it.
    """
    from pairbench import config
    from pairbench.model import Experiment

    path = Path(options.config) if options.config else None
    data = config.resolve_config(path, flags=flags, sets=options.sets)
    sides = data.get("sides")
    declared = bool(sides)
    if not declared:
        data = {**data, "sides": {STAND_IN: {"cmd": list(STAND_IN_COMMAND)}}}
    elif isinstance(sides, Mapping):
        data = {
            **data,
            "sides": {name: _with_kind(str(name), table) for name, table in sides.items()},
        }
    return Experiment.from_json(data), declared


def _with_kind(name: str, table: Any) -> Any:
    """A side table as the gate commands read it: one without a kind stands in as a command.

    Each key of a table without a kind is checked first against the keys
    some kind of side takes, so a misspelt key is refused, not dropped; an
    empty table under a misspelt name is refused too.
    """
    from pairbench.config import SIDE_KIND_KEYS, dict_leaves
    from pairbench.model import CONFIG_KEYS

    if not isinstance(table, Mapping) or any(key in table for key in SIDE_KIND_KEYS):
        return table
    dict_leaves({"sides": {name: table}})
    known = {key.split(".")[2] for key in CONFIG_KEYS if key.startswith("sides.NAME.")}
    unknown = [f"sides.{name}.{key}" for key in table if str(key) not in known]
    if unknown:
        raise Refusal("E_CONFIG", f"unknown config key: {', '.join(unknown)}")
    kept = {key: table[key] for key in KINDLESS_KEYS if key in table}
    return {**kept, "cmd": list(STAND_IN_COMMAND)}


def _side_settings(
    experiment: Experiment, launch: LaunchSettings, declared: bool
) -> dict[str, LaunchSettings]:
    """The launch settings of each side the config declares that launches, by name."""
    from pairbench.model import KIND_FILE

    if not declared:
        return {}
    return {s.name: launch.for_side(s) for s in experiment.sides if s.kind != KIND_FILE}


def _checked_launch(experiment: Experiment, declared: bool) -> LaunchSettings:
    """The shared launch settings the checks read, with the overrides of sides that launch.

    A config whose sides are all result files launches nothing: the checks
    use the shared settings alone, and a loud note says so.
    """
    from pairbench.model import KIND_FILE

    launch = experiment.launch
    if not declared:
        return launch
    launched = {s.name for s in experiment.sides if s.kind != KIND_FILE}
    if not launched:
        print_note(
            NOTE_SHARED_SETTINGS,
            "the sides of the config are result files, which launch nothing; the checks use "
            "the shared launch settings",
        )
    overrides = {name: table for name, table in launch.overrides.items() if name in launched}
    return dataclasses.replace(launch, overrides=overrides)


def _machine(environ: dict[str, str]) -> tuple[bool, bool]:
    """Whether the tool runs inside a container, and in an automated pipeline."""
    from pairbench import api
    from pairbench.api import MakeFacts, delegate

    make_facts: MakeFacts = delegate("facts")
    try:
        record = make_facts().machine_record(gpus=None, node_type=None, environ=environ)
        return bool(record.in_container), api.is_ci(environ)
    except Exception:
        return False, api.is_ci(environ)


def _checked_cpus(cpus: str) -> None:
    from pairbench.model import LaunchSettings

    try:
        LaunchSettings(cpus=cpus)
    except ValueError as exc:
        raise Refusal("E_USAGE", f"--cpus: {exc}") from None
    # A range that runs backwards is malformed input, refused as the run
    # refuses it, not a check that cannot run.
    for part in cpus.split(","):
        low, dash, high = part.strip().partition("-")
        if dash and low.isdigit() and high.isdigit() and int(high) < int(low):
            raise Refusal("E_USAGE", f"--cpus: the CPU range {part.strip()} runs backwards")


def check(options: argparse.Namespace) -> int:
    """Run the CPU check when ``--cpus`` is given, then each readiness check that is on.

    Every check runs under ``enforce``, also after one that did not pass. A
    check that passed prints ``check NAME: pass`` on standard output; one
    that did not pass prints its line on standard error, and the first such
    check is refused. ``--json`` prints the record of the one check that
    ran, or the list of records when several ran.
    """
    import json

    from pairbench import registry
    from pairbench.api import GateContext, gate_line

    flags: dict[str, Any] = {}
    if options.cpus is not None:
        _checked_cpus(options.cpus)
        flags["launch"] = {"cpus": options.cpus}
    if options.allow_mixed_core_types:
        flags["gates"] = {"allow_mixed_core_types": True}
    experiment, declared = _experiment(options, flags)
    names = (["cpus"] if options.cpus is not None else []) + list(experiment.gates.readiness)
    if not names:
        raise Refusal("E_USAGE", NOTHING_TO_CHECK)
    environ = dict(os.environ)
    in_container, ci = _machine(environ)
    launch = _checked_launch(experiment, declared)
    ctx = GateContext(
        mode="enforce",
        gates=dataclasses.replace(experiment.gates, mode="enforce"),
        launch=launch,
        environ=environ,
        in_container=in_container,
        ci=ci,
        note=print_note,
        sides=_side_settings(experiment, launch, declared),
    )
    records = [registry.gate(name).check(ctx) for name in names]
    if options.json:
        shown = records[0].to_json() if len(records) == 1 else [r.to_json() for r in records]
        emit(json.dumps(shown, indent=2))
    for record in records:
        if record.status != "pass":
            print(gate_line(record), file=sys.stderr)
        elif not options.json:
            message = record.detail.get("message")
            emit(f"check {record.name}: {record.status}" + (f": {message}" if message else ""))
    missed = [record for record in records if record.status != "pass"]
    if missed:
        first = missed[0]
        reason = message_of(first.detail)
        if first.status == "fail":
            raise Refusal("E_GATE_FAILED", f"check {first.name} failed: {reason}")
        raise Refusal("E_GATE_UNAVAILABLE", f"check {first.name} could not run fully: {reason}")
    return EXIT_OK


def message_of(detail: Mapping[str, Any]) -> str:
    """The one-line reason a check gave, or a plain word when it gave none."""
    message = detail.get("message")
    return message if isinstance(message, str) and message else "no reason given"


def wait_quiet(options: argparse.Namespace) -> int:
    """Wait for a quiet machine, then run the command once; its exit code is returned."""
    from pairbench import registry
    from pairbench.gates.quiet import wait_then_run

    command = list(options.after or [])
    if not command:
        raise Refusal("E_USAGE", "gate wait-quiet needs a command after --")
    experiment, declared = _experiment(options)
    environ = dict(os.environ)
    in_container, ci = _machine(environ)
    launch = _checked_launch(experiment, declared)
    gate: Any = registry.gate("quiet")
    readiness = [registry.gate(name) for name in experiment.gates.readiness]
    return wait_then_run(
        command,
        gates=experiment.gates,
        launch=launch,
        sides=_side_settings(experiment, launch, declared),
        environ=environ,
        in_container=in_container,
        ci=ci,
        gate=gate,
        readiness=readiness,
        err=sys.stderr,
        note=print_note,
    )


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench gate``."""
    if options.form == "check":
        if options.after is not None:
            raise Refusal("E_USAGE", "gate check takes no command after --")
        return check(options)
    return wait_quiet(options)


__all__ = ["add_arguments", "check", "command", "wait_quiet"]
