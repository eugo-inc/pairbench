# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``hyperfine`` driver: hyperfine's JSON export.

Format read from the tool's own source, ``src/export/json.rs`` at the tags
v1.21.0 and v2.0.0 (https://github.com/sharkdp/hyperfine/blob/v2.0.0/src/export/json.rs),
and checked against the exports of real runs of the release binaries 1.21.0
and 2.0.0.

``prepare`` adds ``--export-json <file>``. A command that already names
``--export-json`` is refused.

``read`` detects the layout from the file:

* without ``schema_version`` (the 1.x layout), each entry of ``results[]``
  names its command in ``command`` (the name given with ``--command-name``
  when one was given) and lists its run times in seconds in ``times``;
* with ``schema_version`` 2, each entry names its command in ``name`` when
  one was given and in ``command`` otherwise, and each of its
  ``measurements[]`` holds ``time_wall_clock.value`` with the unit
  ``second``.

One case per command, holding the median of its run times. A case named
after its command shows it as a results document may: every absolute path
cut to its last part and the value of every credential hidden. Two different
commands shown alike, such as two that differ only in a folder, are refused
with ``E_USAGE``: each needs its own name, given with ``--command-name``.
Another
``schema_version``, another unit, or a run that exited with a code other
than zero or without an exit code (which hyperfine records under
``--ignore-failure``; a run stopped by a signal has no exit code and is
written as ``null``) is refused: a time of a failed run is no time of the
command.

The version is ``metadata.hyperfine_version`` in the newer layout; the older
layout names none.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pairbench.api import DriverContext, Sample, refuse_shown_alike
from pairbench.drivers.base import (
    ToolDriver,
    count,
    items,
    launch_failed,
    mapping,
    member,
    number,
    numbers,
    own_option,
    path_in_side,
    read_json,
    reduce,
    refuse_own_option,
    text,
)
from pairbench.model import public_case, public_words

OUTPUT_FILE: Final = "hyperfine.json"
OWN_OPTIONS: Final[tuple[str, ...]] = ("--export-json",)
SCHEMA_VERSION: Final = 2
SECOND: Final = "second"
METRIC: Final = "time"


class HyperfineDriver(ToolDriver):
    """Reads the run times of each command from hyperfine's JSON export."""

    name = "hyperfine"
    tool = "hyperfine"
    output_file = OUTPUT_FILE
    tested_majors = (1, 2)
    real_run = True
    format_read = "hyperfine JSON export (--export-json), versions 1 and 2"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Add ``--export-json``."""
        found = own_option(argv, OWN_OPTIONS)
        if found is not None:
            raise refuse_own_option(self.name, self.tool, found)
        return [*argv, "--export-json", path_in_side(ctx, OUTPUT_FILE)]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return one case per command."""
        doc = mapping(read_json(path, self.name), path.name)
        newer = _newer_layout(doc, path.name)
        results = items(member(doc, "results", path.name), f"{path.name}: results")
        samples = []
        names: list[tuple[str, str]] = []
        for i, raw in enumerate(results):
            where = f"{path.name}: results[{i}]"
            entry = mapping(raw, where)
            if newer:
                given, name, times = _newer_entry(entry, where)
            else:
                given, name, times = _older_entry(entry, where)
            names.append((given, name))
            if not times:
                raise launch_failed(f"{where}: the command {public_case(name)!r} has no run time")
            value, n_inner, reducer = reduce(times)
            samples.append(
                Sample(
                    case=name,
                    metric=METRIC,
                    unit="s",
                    better="lower",
                    kind="time",
                    value=value,
                    n_inner=n_inner,
                    reducer=reducer,
                )
            )
        refuse_shown_alike(
            names, path.name, "give each command its own name with hyperfine's --command-name"
        )
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return every command."""
        return [sample.case for sample in samples]

    def version_in(self, path: Path) -> str | None:
        """Return ``metadata.hyperfine_version`` of the newer layout."""
        doc = mapping(read_json(path, self.name), path.name)
        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            return None
        version = metadata.get("hyperfine_version")
        return version if isinstance(version, str) and version else None


def _newer_layout(doc: Mapping[str, Any], file_name: str) -> bool:
    if "schema_version" not in doc:
        return False
    version = doc["schema_version"]
    if version != SCHEMA_VERSION or isinstance(version, bool):
        raise launch_failed(
            f"{file_name}: schema_version {version!r} is not one the hyperfine driver reads "
            f"(none, or {SCHEMA_VERSION})"
        )
    return True


def _command_name(entry: Mapping[str, Any], where: str) -> tuple[str, str]:
    """Return a command as written and the name of its case, as a results document may show it.

    The command often holds a path under a home folder or a credential, so
    the name keeps the last part of every path and hides credential values.
    It is read as a case id, so the name of a home folder is kept, as any
    case id keeps it: a word ``~NAME`` with nothing after it as typed
    (``echo ~alpha``), and ``/home/NAME`` or ``/users/NAME`` cut to ``NAME``
    (``python3 app.py --route /users/1`` names ``python3 app.py --route 1``).
    """
    command = text(member(entry, "command", where), f"{where}: command")
    return command, public_words(command, case=True)


def _older_entry(entry: Mapping[str, Any], where: str) -> tuple[str, str, list[float]]:
    given, name = _command_name(entry, where)
    times = numbers(member(entry, "times", where), f"{where}: times")
    codes = entry.get("exit_codes")
    if codes is not None:
        for j, code in enumerate(items(codes, f"{where}: exit_codes")):
            _check_exit_code(code, name, where, f"{where}: exit_codes[{j}]")
    return given, name, times


def _newer_entry(entry: Mapping[str, Any], where: str) -> tuple[str, str, list[float]]:
    if entry.get("name") is None:
        given, name = _command_name(entry, where)
    else:
        given = name = text(entry["name"], f"{where}: name")
    times = []
    measurements = items(member(entry, "measurements", where), f"{where}: measurements")
    for j, raw in enumerate(measurements):
        at = f"{where}: measurements[{j}]"
        measurement = mapping(raw, at)
        wall = mapping(member(measurement, "time_wall_clock", at), f"{at}: time_wall_clock")
        unit = member(wall, "unit", f"{at}: time_wall_clock")
        if unit != SECOND:
            raise launch_failed(f"{at}: time_wall_clock has the unit {unit!r}, not {SECOND!r}")
        times.append(number(member(wall, "value", f"{at}: time_wall_clock"), f"{at}: value"))
        if "exit_code" in measurement:
            _check_exit_code(measurement["exit_code"], name, where, f"{at}: exit_code")
    return given, name, times


def _check_exit_code(code: Any, name: str, where: str, at: str) -> None:
    if code is None:
        raise launch_failed(
            f"{where}: a run of {public_case(name)!r} ended without an exit code, as a run "
            "stopped by a signal does; the hyperfine driver reads the times of runs that succeeded"
        )
    if count(code, at) != 0:
        raise launch_failed(
            f"{where}: a run of {public_case(name)!r} exited with a code other than zero; "
            "the hyperfine driver reads the times of runs that succeeded"
        )
