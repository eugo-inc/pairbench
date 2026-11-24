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
        "the same capture was given twice: the same id, file path or file hash, or of a file a"
        " reader splits into runs, the same run",
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


# The control characters: C0, DEL and C1.
_CONTROLS: Final = (*range(0x20), 0x7F, *range(0x80, 0xA0))
# The characters besides the control characters that end a line, as str.splitlines reads it.
_LINE_SEPARATORS: Final = (0x2028, 0x2029)
# The Bidi_Control characters, which change the order a terminal shows the text around them in.
_BIDI_CONTROLS: Final = (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A))
# The surrogates, which no output stream encodes when they stand alone in a text.
_SURROGATES: Final = range(0xD800, 0xE000)


# The characters that printable writes as an escape, besides the backslash.
ESCAPED_CHARACTERS: Final = frozenset(
    (*_CONTROLS, *_LINE_SEPARATORS, *_BIDI_CONTROLS, *_SURROGATES)
)


def _escape(code: int) -> str:
    if code < 0x100:
        return f"\\x{code:02x}"
    if code < 0x10000:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


_SHORT_ESCAPES: Final = {0x09: "\\t", 0x0A: "\\n", 0x0D: "\\r"}
_ESCAPES: Final = {
    **{c: _escape(c) for c in (*_CONTROLS, *_LINE_SEPARATORS, *_BIDI_CONTROLS, *_SURROGATES)},
    **_SHORT_ESCAPES,
    0x5C: "\\\\",
}


def printable(text: str) -> str:
    """``text`` with each character that could break its line, reorder it or fail to print
    written as an escape, so that text read from an input file stays on its line, shows in
    its own order and cannot drive a terminal.

    A control character, C0, DEL or C1, is written as ``\\t``, ``\\n``, ``\\r`` or
    ``\\xNN``, such as ``\\x1b``. The line and paragraph separators U+2028 and U+2029, the
    Bidi_Control characters U+061C, U+200E, U+200F, U+202A to U+202E and U+2066 to U+2069,
    and a surrogate that stands alone are written as ``\\uNNNN``, such as ``\\u2028``. A
    backslash is written as ``\\\\``, so each printed text stands for one text only: the
    typed four characters ``\\x1b`` print as ``\\\\x1b``. Every other character is printed
    as it is.
    """
    return text.translate(_ESCAPES)


_UNESCAPES: Final = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
_ESCAPE_WIDTHS: Final = {"x": 2, "u": 4, "U": 8}
_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_LAST_CODE_POINT: Final = 0x10FFFF


def unprintable(shown: str) -> str:
    """The text that ``printable`` wrote as ``shown``, such as a refusal's message read back
    from its line on standard error.

    Every text ``printable`` writes is read back to the text it came from. Other escapes of
    the same forms are read too, such as ``\\x41`` for ``A`` or ``\\U0000d800`` for a lone
    surrogate, which ``printable`` never writes: an escape of two, four or eight lower-case
    hex digits reads as the character of that number, from U+0000 to U+10FFFF, lone
    surrogates included. Every other backslash is kept as it is, and the text after it is
    read on: a backslash that opens no escape, such as ``\\q``, that ends the text, whose
    escape is cut short or holds a digit that is not lower-case hex, such as ``\\x1`` or
    ``\\x1B``, or whose escape is past U+10FFFF, such as ``\\Uffffffff``. It never raises.
    """
    out: list[str] = []
    at = 0
    while True:
        found = shown.find("\\", at)
        if found < 0:
            out.append(shown[at:])
            return "".join(out)
        out.append(shown[at:found])
        kind = shown[found + 1 : found + 2]
        if kind in _UNESCAPES:
            out.append(_UNESCAPES[kind])
            at = found + 2
            continue
        width = _ESCAPE_WIDTHS.get(kind, 0)
        digits = shown[found + 2 : found + 2 + width]
        if width and len(digits) == width and set(digits) <= _HEX_DIGITS:
            code = int(digits, 16)
            if code <= _LAST_CODE_POINT:
                out.append(chr(code))
                at = found + 2 + width
                continue
        out.append("\\")
        at = found + 1


def _holds_surrogate(text: str) -> bool:
    if text.isascii():
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def _any_surrogate(value: object) -> bool:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _holds_surrogate(item):
                return True
        elif isinstance(item, dict):
            if any(isinstance(key, str) and _holds_surrogate(key) for key in item):
                return True
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            stack.extend(item)
    return False


def _first_surrogate(value: object) -> tuple[str, str, bool] | None:
    """The place, the text and whether it is a key, of the first text of ``value`` that
    holds a surrogate, or ``None``."""
    if not _any_surrogate(value):
        return None
    stack: list[tuple[str, object]] = [("", value)]
    while stack:
        place, item = stack.pop()
        if isinstance(item, str):
            if _holds_surrogate(item):
                return place, item, False
        elif isinstance(item, dict):
            key = next((k for k in item if isinstance(k, str) and _holds_surrogate(k)), None)
            if key is not None:
                return place, key, True
            members = [(_member(place, str(k)), v) for k, v in item.items()]
            stack.extend(reversed(members))
        elif isinstance(item, list | tuple):
            stack.extend(reversed([(f"{place}[{i}]", v) for i, v in enumerate(item)]))
    return None


# How many characters a lone-surrogate message shows on each side of the first surrogate.
_SHOWN_AROUND: Final = 40


def _around_surrogate(text: str) -> str:
    at = next(i for i, c in enumerate(text) if "\ud800" <= c <= "\udfff")
    start = max(0, at - _SHOWN_AROUND)
    end = min(len(text), at + 1 + _SHOWN_AROUND)
    before = "..." if start else ""
    after = "..." if end < len(text) else ""
    return f"{before}{printable(text[start:end])}{after}"


def lone_surrogate(value: object) -> str | None:
    """Say which text of ``value``, a document read from JSON, holds a lone surrogate, or
    return ``None`` when none does.

    A JSON text may write a surrogate that stands alone, such as ``"\\ud800"``, and such a
    text is not UTF-8 text. The answer names the first such text, a value or a key, by its
    place in the document and shows it escaped as ``printable`` writes it, such as
    ``benchmarks[0].name: BM_\\ud800 holds a lone surrogate, which is not UTF-8 text``; it
    names no place when the document is a text itself. It shows at most 40 characters on each
    side of the first surrogate, with ``...`` where it leaves text out.
    """
    found = _first_surrogate(value)
    if found is None:
        return None
    place, text, is_key = found
    shown = _around_surrogate(text)
    what = f"the key {shown}" if is_key else shown
    where = f"{place}: " if place else ""
    return f"{where}{what} holds a lone surrogate, which is not UTF-8 text"


def surrogate_place(value: object) -> str | None:
    """Say where ``value``, a text or a document of lists and mappings, holds a text with a
    surrogate, without the text, or return ``None`` when it holds none.

    The place is written as ``lone_surrogate`` writes it, such as ``sides.new.argv[2]``;
    a key is named ``a key of`` its place, and the text itself is the empty place.
    """
    found = _first_surrogate(value)
    if found is None:
        return None
    place, _, is_key = found
    if is_key:
        return f"a key of {place}" if place else "a key"
    return place


def _member(place: str, key: str) -> str:
    return f"{place}.{printable(key)}" if place else printable(key)


def docs_line(code: str, version: str) -> str:
    """The line printed on standard error after a refusal's line: where its entry is."""
    return f"pairbench: see {docs_address(code, version)}"


class Refusal(Exception):
    """A refusal: a stable text code, an exit code, a one-line message and a scope.

    ``detail`` carries machine-readable extras for the caller, for example
    every missing figure key or every bad grid cell. It is not written to a
    results document, but for one case: ``pairbench compare --matching``
    writes the detail of a refusal of the matching mode, which holds only the
    name of a check, counts, run indices and, for a written stretch, row
    indices and whether its last row is torn, and, for two parts of runs, the
    line on which each begins, under ``matching.refusal``.
    ``results`` is the results document that describes the
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
        """The one line printed on standard error: ``CODE: message``.

        Each character of the message that could break the line, reorder it or fail to print
        is written as an escape: a control character as ``\\t``, ``\\n``, ``\\r`` or ``\\xNN``,
        a line or paragraph separator, a Bidi_Control character or a lone surrogate as
        ``\\uNNNN``, and a backslash as ``\\\\``. A name that the message quotes keeps the
        escapes of its quoting, so their backslashes show doubled here. ``message`` and
        ``to_json`` keep the message as it is.
        """
        return f"{self.code}: {printable(self.message)}"

    def to_json(self) -> dict[str, str]:
        """The entry written to ``refusals`` in a results document."""
        return {"code": self.code, "scope": self.scope, "message": self.message}
