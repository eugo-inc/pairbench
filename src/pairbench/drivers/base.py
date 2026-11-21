# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the drivers that wrap a benchmark tool share.

A tool driver adds the tool's own output option to the command of a launch,
pointing at the launch's folder as the launched program sees it, reads the
file the tool wrote from the same folder on the host, and turns it into one
``Sample`` per case. For a file side it reads the one result file it is
given instead.

Output that cannot be read is refused with ``E_LAUNCH_FAILED``. The message
names the file by the last part of its path and the place in it, holds no
other path, and may quote a name or value read from the file: it reaches the
results document, which is meant to be shared. A command that already holds
the tool's own output option is refused with ``E_USAGE``: the driver could
not see a file the user chose, and the two runs of a positive-control launch
would write to the same file.

A driver keeps nothing between two calls. In a launch of the positive control
it is asked to prepare and to read each of the two runs on its own.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pairbench.api import (
    API_VERSION,
    REDUCER_IDENTITY,
    REDUCER_MEDIAN,
    DoctorReport,
    DriverContext,
    Invocation,
    Sample,
    ToolVersion,
)
from pairbench.errors import Refusal
from pairbench.model import KIND_CMD, KIND_CONDA, KIND_PYTHON, KIND_VENV, public_case, quantile

# Notes a driver writes for a case the tool did not measure in a launch.
NOTE_CASE_SKIPPED: Final = "case_skipped"
NOTE_EVENT_NOT_COUNTED: Final = "event_not_counted"

# Side kinds that start the launched program as a process on this machine.
# Every other kind runs it inside a container.
HOST_KINDS: Final[tuple[str, ...]] = (KIND_CMD, KIND_PYTHON, KIND_VENV, KIND_CONDA)

# Seconds per unit of time, for the units the tools write.
SECONDS_PER: Final[Mapping[str, float]] = {
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}

_MAJOR = re.compile(r"\d+")


def launch_failed(message: str) -> Refusal:
    """Return the refusal of output that cannot be read."""
    return Refusal("E_LAUNCH_FAILED", message)


def result_path(ctx: DriverContext, artifacts: Path, file_name: str) -> Path:
    """Return the file to read: the result file of a file side, else ``artifacts/file_name``."""
    if ctx.result_file is not None:
        return ctx.result_file
    return artifacts / file_name


def path_in_side(ctx: DriverContext, file_name: str) -> str:
    """Return where the launched program writes ``file_name`` in the launch's folder."""
    folder = ctx.artifacts_in_side.rstrip("/")
    return f"{folder}/{file_name}"


def read_text(path: Path, driver: str) -> str:
    """Return the text of an output file, or refuse when there is none to read."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise launch_failed(f"the {driver} driver found no output file {path.name}") from None
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise launch_failed(f"the {driver} driver could not read {path.name}: {reason}") from None


def read_json(path: Path, driver: str) -> Any:
    """Return the JSON document of an output file, or refuse when it is not one."""
    text = read_text(path, driver)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise launch_failed(
            f"{path.name} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from None
    except ValueError:
        raise launch_failed(f"{path.name} holds a number with too many digits to read") from None
    except RecursionError:
        raise launch_failed(f"{path.name} is nested too deeply to read") from None


def mapping(value: Any, where: str) -> Mapping[str, Any]:
    """Return ``value`` when it is a JSON object, or refuse naming ``where``."""
    if not isinstance(value, dict):
        raise launch_failed(f"{where} is not an object")
    return value


def items(value: Any, where: str) -> list[Any]:
    """Return ``value`` when it is a JSON array, or refuse naming ``where``."""
    if not isinstance(value, list):
        raise launch_failed(f"{where} is not a list")
    return value


def member(obj: Mapping[str, Any], key: str, where: str) -> Any:
    """Return ``obj[key]``, or refuse naming the key that is missing."""
    if key not in obj:
        raise launch_failed(f"{where} has no {key}")
    return obj[key]


def text(value: Any, where: str) -> str:
    """Return ``value`` when it is a text that is not empty, or refuse naming ``where``."""
    if not isinstance(value, str) or not value:
        raise launch_failed(f"{where} is not a text that is not empty")
    return value


def number(value: Any, where: str) -> float:
    """Return ``value`` when it is a number, or refuse naming ``where``.

    A JSON true or false is no number. A value that is a number but not a
    finite one is refused by ``Sample`` when the sample is made.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise launch_failed(f"{where} is not a number")
    try:
        return float(value)
    except OverflowError:
        raise launch_failed(f"{where} is not a finite number") from None


def count(value: Any, where: str) -> int:
    """Return ``value`` when it is a whole number of zero or more, or refuse naming ``where``."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise launch_failed(f"{where} is not a whole number of zero or more")
    return value


def numbers(value: Any, where: str) -> list[float]:
    """Return a JSON array of numbers as floats, or refuse naming ``where``."""
    return [number(v, f"{where}[{i}]") for i, v in enumerate(items(value, where))]


def reduce(values: Sequence[float]) -> tuple[float, int, str]:
    """Return the value, the count and the reducer of a case's inner samples.

    One inner sample is taken as it is (``identity``). Two or more give their
    median, by the one quantile method of the model (``median``).
    """
    if not values:
        raise ValueError("a case needs at least one inner sample")
    if len(values) == 1:
        return values[0], 1, REDUCER_IDENTITY
    return quantile(values, 0.5), len(values), REDUCER_MEDIAN


def unique(samples: Iterable[Sample], file_name: str) -> list[Sample]:
    """Return the samples, or refuse when one case id is given twice."""
    seen: set[str] = set()
    out: list[Sample] = []
    for sample in samples:
        if sample.case in seen:
            raise launch_failed(
                f"{file_name}: the case {public_case(sample.case)!r} is given twice"
            )
        seen.add(sample.case)
        out.append(sample)
    return out


def tool_version_of(tool: str, version: str, tested_majors: Iterable[int]) -> ToolVersion:
    """Return a tool's version and whether its major version was tested.

    The major version is the first whole number in the version text. A text
    without one cannot be told to be a tested version, so it is not one.
    """
    found = _MAJOR.search(version)
    try:
        tested = found is not None and int(found.group()) in tuple(tested_majors)
    except ValueError:
        # More digits than Python converts: no major version a driver was tested with.
        tested = False
    return ToolVersion(tool=tool, version=version, tested=tested)


def own_option(argv: Sequence[str], options: Iterable[str]) -> str | None:
    """Return the first argument that is one of ``options``, alone or as ``OPTION=VALUE``."""
    wanted = tuple(options)
    for arg in argv:
        for option in wanted:
            if arg == option or arg.startswith(option + "="):
                return option
    return None


def refuse_own_option(driver: str, tool: str, option: str) -> Refusal:
    """Return the refusal of a command that already holds the driver's own output option."""
    return Refusal(
        "E_USAGE",
        f"the {driver} driver adds {tool}'s option {option} itself and reads the file it names; "
        f"remove {option} from the command",
    )


class ToolDriver:
    """The shared part of a driver that wraps a benchmark tool.

    A subclass sets ``name``, ``tool``, ``output_file``, ``tested_majors``,
    ``real_run`` and ``format_read``, and implements ``add_output``,
    ``read_file``, ``default_primary`` and, where the output names the tool's
    version, ``version_in``.

    ``real_run`` says whether the driver has a fixture from a run of the real
    tool. A driver without one reports ``experimental`` to ``pairbench
    doctor``.
    """

    name: str = ""
    api_version: int = API_VERSION
    where: Literal["in_side", "client"] = "in_side"

    tool: str = ""
    output_file: str = ""
    tested_majors: tuple[int, ...] = ()
    real_run: bool = False
    format_read: str = ""

    # -- prepare ---------------------------------------------------------------

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return the command with the tool's output option added."""
        if not argv:
            raise Refusal(
                "E_USAGE",
                f"the {self.name} driver needs the command that runs {self.tool} "
                "to add its output option to; the side gives none",
            )
        return Invocation.single(self.add_output(ctx, list(argv)))

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Return ``argv`` with the tool's output option added."""
        raise NotImplementedError

    # -- read ------------------------------------------------------------------

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return one sample per case of the tool's output file."""
        path = result_path(ctx, artifacts, self.output_file)
        samples = unique(self.read_file(ctx, path), path.name)
        if not samples:
            raise launch_failed(f"{path.name}: the {self.tool} output holds no measured case")
        return samples

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return the samples of one output file, in the order the file gives them."""
        raise NotImplementedError

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return the cases that count toward the verdict."""
        raise NotImplementedError

    # -- version and doctor ----------------------------------------------------

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        """Return the version the output file names, or ``None`` when it names none."""
        version = self.version_in(result_path(ctx, artifacts, self.output_file))
        if version is None:
            return None
        return tool_version_of(self.tool, version, self.tested_majors)

    def version_in(self, path: Path) -> str | None:
        """Return the tool's version as the output file names it, or ``None``."""
        return None

    def doctor(self) -> DoctorReport:
        """Say whether the driver has a fixture from a run of the real tool."""
        if self.real_run:
            return DoctorReport(status="ok", summary=f"reads {self.format_read}")
        return DoctorReport(
            status="experimental",
            summary=(
                f"reads {self.format_read}; no fixture from a run of the real tool yet, "
                "so the driver is experimental"
            ),
        )
