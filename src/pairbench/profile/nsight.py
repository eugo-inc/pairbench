# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""NVIDIA Nsight Systems and NVIDIA Nsight Compute, as profilers the user installed.

``profiler(tool)`` gives the profiler for ``nsys`` or ``ncu`` and refuses any
other name with ``E_USAGE``; ``perf`` is recorded by the diagnostics part.
A profiler is used for one extra, untimed launch per side, never during a
measured round. pairbench does not include, download or redistribute a
profiler: ``find`` only looks for the program on ``PATH``, and ``require``
refuses with ``E_PROFILER_MISSING``, naming the profiler, when it is not
there. ``licence_note`` is the note printed when a profiler is first used.

``wrap(argv, out)`` puts the profiler's program in front of the launch's
command and points its report into ``out``, the folder as the launch sees
it. The command names the program by its bare name, so that a launch finds
it on its own ``PATH``; the path ``find`` returned is where it lies on the
host, which a container does not share. The report is named
``report.nsys-rep`` or ``report.ncu-rep``, so each side's launch needs a
folder of its own under ``profiles/``. An existing report of the same name
is overwritten. An empty command has nothing to put under a profiler and
is refused with ``E_ENGINE_UNSUPPORTED``; an image side hands over the
image's whole command line, so it is empty only when the image names none.

The command lines, from each tool's public documentation:

* Nsight Systems user guide, version 2026.6
  (https://docs.nvidia.com/nsight-systems/UserGuide/index.html):
  ``nsys profile -o <file> -f true <application> [arguments]``; ``-o`` names
  the report and ``.nsys-rep`` is added to the name; ``-f true`` overwrites
  an existing report of that name;
* Nsight Compute command line interface, version 2026.4.0
  (https://docs.nvidia.com/nsight-compute/NsightComputeCli/index.html):
  ``ncu -o <file> -f <application> [arguments]``; ``-o`` names the report
  and ``.ncu-rep`` is added to the name; ``-f`` overwrites existing files.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from typing import Final

from pairbench.api import ProfiledCommand, Profiler
from pairbench.errors import Refusal

REPORT_STEM: Final = "report"
GPU_PROFILERS: Final[tuple[str, ...]] = ("nsys", "ncu")

Which = Callable[[str], str | None]


class NsightProfiler:
    """What both profilers share: finding the program, the note, the refusal."""

    name: str = ""
    title: str = ""
    extension: str = ""

    def __init__(self, *, which: Which | None = None) -> None:
        self._which = which

    @property
    def program(self) -> str:
        """Return the program's name, as a launch finds it on ``PATH``."""
        return self.name

    @property
    def licence_note(self) -> str:
        """Return the note printed when the profiler is first used."""
        return (
            f"{self.name}: pairbench does not include, download or redistribute "
            f"{self.title}; it runs the copy you installed. Your use of it, and what "
            "you may publish from its output, is governed by the licence you accepted with it."
        )

    def find(self) -> str | None:
        """Return the program's path, or ``None`` when it is not installed."""
        which = self._which or shutil.which
        return which(self.program)

    def require(self) -> str:
        """Return the program's path, or refuse with ``E_PROFILER_MISSING``."""
        return require(self)

    def _report(self, out: str) -> str:
        """Return the report's name without its extension: ``<out>/report``."""
        if not out:
            return REPORT_STEM
        return f"{out.rstrip('/')}/{REPORT_STEM}"

    def _options(self, report: str) -> tuple[str, ...]:
        raise NotImplementedError

    def wrap(self, argv: Sequence[str], out: str) -> ProfiledCommand:
        """Return the command to launch and the report it writes under ``out``."""
        if not argv:
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"there is no command to run under {self.name}: the side names none and its "
                "image names none; give the side a command to profile",
            )
        report = self._report(out)
        return ProfiledCommand(
            argv=(self.program, *self._options(report), *argv),
            outputs=(f"{report}{self.extension}",),
        )


class NsightSystems(NsightProfiler):
    """NVIDIA Nsight Systems: ``nsys profile``, one ``.nsys-rep`` report."""

    name = "nsys"
    title = "NVIDIA Nsight Systems"
    extension = ".nsys-rep"

    def _options(self, report: str) -> tuple[str, ...]:
        return ("profile", "-o", report, "-f", "true")


class NsightCompute(NsightProfiler):
    """NVIDIA Nsight Compute: ``ncu``, one ``.ncu-rep`` report."""

    name = "ncu"
    title = "NVIDIA Nsight Compute"
    extension = ".ncu-rep"

    def _options(self, report: str) -> tuple[str, ...]:
        return ("-o", report, "-f")


def require(profiler: Profiler) -> str:
    """Return the path of an installed profiler, or refuse with ``E_PROFILER_MISSING``.

    The message names the profiler and says that pairbench does not provide
    it.
    """
    found = profiler.find()
    if found is None:
        raise Refusal(
            "E_PROFILER_MISSING",
            f"the profiler {profiler.name} is not installed: pairbench does not include or "
            f"download it; install it yourself and put {profiler.name} on PATH",
        )
    return found


def profiler(tool: str) -> NsightProfiler:
    """Return the GPU profiler named ``nsys`` or ``ncu`` (``pairbench.api.MakeProfiler``).

    Any other name is refused with ``E_USAGE``, ``perf`` included: its stacks
    are recorded by the diagnostics part.
    """
    if tool == NsightSystems.name:
        return NsightSystems()
    if tool == NsightCompute.name:
        return NsightCompute()
    raise Refusal(
        "E_USAGE",
        f"not a GPU profiler: {tool!r}; the GPU profilers are {' and '.join(GPU_PROFILERS)}",
    )
