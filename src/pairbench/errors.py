# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Refusals, their stable text codes and the exit codes of the command line.

A refusal stops the work with a non-zero exit code, a stable text code and a
one-line reason. Every text code the tool can emit is listed once, in
``CODES``, with the scopes pairbench raises it with. Raising a ``Refusal``
with a code that is not in the table is a programming error; the scopes of
a row document the code and are not checked when a refusal is made.

The text codes are stable. A release adds a code only in a minor
or a major release and names it in its changelog entry; a code is renamed or
removed only in a major release.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from pairbench.model import Results

EXIT_OK: Final = 0
EXIT_CHECK_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_SIDE: Final = 3
EXIT_MACHINE: Final = 4
EXIT_LAUNCH: Final = 5
EXIT_ANALYSIS: Final = 6
EXIT_FIGURE_MISSING: Final = 7
EXIT_INTERNAL: Final = 8
EXIT_INTERRUPTED: Final = 130

EXIT_CODES: Final[Mapping[int, str]] = {
    EXIT_OK: "completed and results written, whatever the verdicts",
    EXIT_CHECK_FAILED: (
        "a requested check failed: a fail-on outcome matched, a self-test control failed, "
        "or a filled document is stale"
    ),
    EXIT_USAGE: "usage or config error",
    EXIT_SIDE: "a side was refused in preflight",
    EXIT_MACHINE: "the machine was refused: a check under enforce, or a lock",
    EXIT_LAUNCH: "a launch failed; the capture is kept and marked",
    EXIT_ANALYSIS: "the analysis was refused",
    EXIT_FIGURE_MISSING: "fill: a figure is missing",
    EXIT_INTERNAL: "internal error",
    EXIT_INTERRUPTED: "interrupted",
}

Scope = Literal["experiment", "case"]
SCOPES: Final[tuple[str, ...]] = ("experiment", "case")


@dataclass(frozen=True)
class Code:
    """One row of the text-code table.

    ``exit_code`` is the exit code a refusal with this code has unless the
    place that raises it says otherwise. ``also`` lists the other exit codes
    the same text code may carry. ``scopes`` lists the scopes pairbench
    raises a refusal with this code with: ``experiment`` refuses the whole run
    or analysis, ``case`` one case of it. It documents the code; a refusal
    with another scope is not refused for it.
    """

    code: str
    exit_code: int
    meaning: str
    also: tuple[int, ...] = ()
    scopes: tuple[Scope, ...] = ("experiment",)

    @property
    def exit_codes(self) -> tuple[int, ...]:
        """Every exit code this text code may carry, the default first."""
        return (self.exit_code, *self.also)


def _table(*rows: Code) -> dict[str, Code]:
    table: dict[str, Code] = {}
    for row in rows:
        if row.code in table:
            raise ValueError(f"text code listed twice: {row.code}")
        table[row.code] = row
    return table


CODES: Final[Mapping[str, Code]] = _table(
    # usage and config
    Code(
        "E_USAGE",
        EXIT_USAGE,
        "the command line or a library call was given something invalid",
        scopes=("experiment", "case"),
    ),
    Code("E_CONFIG", EXIT_USAGE, "the config holds an unknown key or an invalid value"),
    # sides, in preflight
    Code(
        "E_SAME_SIDE",
        EXIT_SIDE,
        "two different sides have the same fingerprint, run in the same working folder and differ "
        "at most in a credential's value",
    ),
    Code(
        "E_SIDE_UNIDENTIFIED",
        EXIT_SIDE,
        "a side could not be identified, or its identify command gave no output or failed",
    ),
    Code(
        "E_SIDE_UNRESOLVED",
        EXIT_SIDE,
        "an image, executable, interpreter or working folder was not found",
    ),
    Code(
        "E_ENTRYPOINT_UNREADABLE",
        EXIT_SIDE,
        "an image side runs the shared workload and the entrypoint of its image could not be read",
    ),
    Code(
        "E_ENGINE_UNSUPPORTED",
        EXIT_SIDE,
        "the container engine or the kind of side cannot do what was asked",
    ),
    Code("E_PROFILER_MISSING", EXIT_SIDE, "the named profiler is not installed"),
    Code(
        "E_PLOT_EXTRA_MISSING",
        EXIT_SIDE,
        "charts were asked for and the plot extra is not installed",
    ),
    Code(
        "E_TWIN_DRIFT",
        EXIT_SIDE,
        "a twin's fingerprint differs from its side's; exit 3 when found as the run starts, "
        "exit 6 when found in analysis",
        also=(EXIT_ANALYSIS,),
    ),
    # the machine
    Code("E_GATE_FAILED", EXIT_MACHINE, "a machine check failed under enforce"),
    Code("E_GATE_UNAVAILABLE", EXIT_MACHINE, "a machine check could not run under enforce"),
    Code("E_LOCK", EXIT_MACHINE, "a lock could not be taken: timeout or error"),
    Code("E_PIN_UNSUPPORTED", EXIT_MACHINE, "CPU pinning was asked for where it cannot be done"),
    Code("E_CPUS_MIXED_TYPES", EXIT_MACHINE, "the pinned CPU set mixes core types"),
    # launches
    Code(
        "E_LAUNCH_FAILED",
        EXIT_LAUNCH,
        "a launch exited non-zero, timed out, or gave output the driver cannot read",
    ),
    Code("E_SIDE_CHANGED", EXIT_LAUNCH, "a side's identity changed during the run"),
    Code("E_GPU_NOT_RELEASED", EXIT_LAUNCH, "GPU memory did not return to its level in time"),
    # analysis
    Code("E_TOO_FEW_ROUNDS", EXIT_ANALYSIS, "fewer rounds are planned than can give a verdict"),
    Code("E_CASES_DIFFER", EXIT_ANALYSIS, "the sides produce different sets of primary cases"),
    Code("E_BUDGET", EXIT_ANALYSIS, "no balanced round count fits the time budget"),
    Code("E_CAPTURE_INCOMPLETE", EXIT_ANALYSIS, "a capture has no end record"),
    Code(
        "E_GRID",
        EXIT_ANALYSIS,
        "the observed grid of rounds and lineup entries does not match the lineup",
    ),
    Code("E_TWIN_ORPHAN", EXIT_ANALYSIS, "a twin's side is absent"),
    Code("E_ORDER_NOT_VARIED", EXIT_ANALYSIS, "a compared pair ran in the same order every round"),
    Code(
        "E_POOL_SAME",
        EXIT_ANALYSIS,
        "the same capture id, file path or file hash was given twice",
    ),
    Code(
        "E_POOL_IDENTICAL_ROWS",
        EXIT_ANALYSIS,
        "two captures with different ids hold identical observation rows",
    ),
    Code(
        "E_POOL_TRUNCATED_COPY",
        EXIT_ANALYSIS,
        "one capture's rows are a contiguous stretch of another's",
    ),
    Code(
        "E_POOL_SIDE_DRIFT",
        EXIT_ANALYSIS,
        "a side's fingerprint, its recorded setup in more than a credential's value, its "
        "working folder, or the shared workload in more than a credential's value differs "
        "between captures",
    ),
    Code("E_POOL_CASES", EXIT_ANALYSIS, "the case sets or units differ between captures"),
    Code("E_POOL_MACHINE", EXIT_ANALYSIS, "the CPU or GPU identity differs between captures"),
    Code(
        "E_POOL_MIXED_PURPOSE",
        EXIT_ANALYSIS,
        "a capture of one side against its own twins is pooled with a comparison of sides",
    ),
    # fill
    Code("E_FIGURE_MISSING", EXIT_FIGURE_MISSING, "a document names a figure that is absent"),
    # everything else
    Code("E_INTERNAL", EXIT_INTERNAL, "internal error"),
    Code("E_INTERRUPTED", EXIT_INTERRUPTED, "the run was interrupted"),
)


def exit_code_for(code: str) -> int:
    """Return the default exit code of a text code."""
    return CODES[code].exit_code


# The address of the documentation: the site and its base folder, the two settings of
# site/astro.config.mjs. Each release's pages are in a folder named by its major and
# minor version.
DOCS_ADDRESS: Final = "https://eugo.io/docs/pairbench/"
CODES_PAGE: Final = "reference/exit-codes/"
CONFIG_PAGE: Final = "reference/config/"
# The section of the config page that lists what the shared files of a run hide of its command.
SHARED_COMMAND_ANCHOR: Final = "what-the-shared-files-hide"


def section_address(page: str, anchor: str, version: str) -> str:
    """Return the address of a section of a documentation page in the documentation of
    ``version``: the release folder, the page and the section's anchor."""
    folder = ".".join(version.split(".")[:2])
    return f"{DOCS_ADDRESS}{folder}/{page}#{anchor}"


def docs_address(code: str, version: str) -> str:
    """Return the address of a text code's entry, with its cause and fix, in the
    documentation of ``version``."""
    if code not in CODES:
        raise ValueError(f"text code is not in the table: {code}")
    return section_address(CODES_PAGE, code.lower(), version)


_ESCAPES: Final = {
    **{c: f"\\x{c:02x}" for c in (*range(0x20), 0x7F, *range(0x80, 0xA0))},
    0x09: "\\t",
    0x0A: "\\n",
    0x0D: "\\r",
}


def printable(text: str) -> str:
    """``text`` with each control character, C0, DEL and C1, written as an escape such as
    ``\\n`` or ``\\x1b``, so that text read from an input file stays on its line and
    cannot drive a terminal."""
    return text.translate(_ESCAPES)


def docs_line(code: str, version: str) -> str:
    """The line printed on standard error after a refusal's line: where its entry is."""
    return f"pairbench: see {docs_address(code, version)}"


class Refusal(Exception):
    """A refusal: a stable text code, an exit code, a one-line message and a scope.

    ``detail`` carries machine-readable extras for the caller, for example
    every missing figure key or every bad grid cell. It is never written to a
    results document. ``results`` is the results document that describes the
    refused run, when one could be built: no comparisons and this refusal
    listed in ``refusals``.

    The message is printed on standard error and is also written to the
    results document, which is meant to be shared. It names a side by the
    name the user gave it and a file by the last part of its path, and holds
    no host, no user, no image reference and no value of the environment;
    such things belong in ``detail``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        scope: Scope = "experiment",
        exit_code: int | None = None,
        detail: Mapping[str, Any] | None = None,
        results: Results | None = None,
    ) -> None:
        row = CODES.get(code)
        if row is None:
            raise ValueError(f"text code is not in the table: {code}")
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {', '.join(SCOPES)}: {scope}")
        chosen = row.exit_code if exit_code is None else exit_code
        if chosen not in row.exit_codes:
            raise ValueError(f"{code} cannot carry exit code {chosen}")
        self.code: str = code
        self.message: str = " ".join(str(message).split())
        self.scope: Scope = scope
        self.exit_code: int = chosen
        self.detail: dict[str, Any] = dict(detail or {})
        self.results: Results | None = results
        super().__init__(self.line)

    @property
    def line(self) -> str:
        """The one line printed on standard error: ``CODE: message``, with each control
        character of the message escaped."""
        return f"{self.code}: {printable(self.message)}"

    def to_json(self) -> dict[str, str]:
        """The entry written to ``refusals`` in a results document."""
        return {"code": self.code, "scope": self.scope, "message": self.message}
