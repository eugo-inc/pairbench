# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Folded stacks, the difference between two sides, and where samples fell.

The folding is written for this package from the text ``perf script`` prints
and from the folded output of the ``pystacks`` sampler. The format of that
text was read from the public documentation of ``perf script`` and the source
that prints a call chain, Linux v6.12:

* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/Documentation/perf-script.txt
* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/util/evsel_fprintf.c
* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/Documentation/perf-buildid-list.txt

``perf script`` prints one sample as a header line that starts in the first
column (command, process and thread id, time, event), followed by one line
per frame of the call chain, innermost first, each indented and holding the
instruction address, the symbol and, in parentheses, the shared object. A
function the compiler inlined is a frame of its own that prints
``(inlined)`` where the shared object goes; the frame it was inlined into
follows it at the same address. A blank line ends the sample.
``perf buildid-list`` prints one line per shared object: the build id, a
space and the path.

A folded file has one line per distinct stack: the frames from the outermost
to the innermost joined by ``;``, a space, and the number of samples. Lines
are sorted by the stack text. Its first line says that the file holds names
from the user's code.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pairbench.model import ObjectDiff, TopFunction, TopObject

# The first line of every folded file and difference file.
HOLDS_NAMES_LINE = (
    "# pairbench: this file holds names from the user's code: functions, shared objects and stacks"
)
# The columns of a difference file, in order.
DIFF_COLUMNS = (
    "stack",
    "subject_samples",
    "baseline_samples",
    "subject_share",
    "baseline_share",
    "share_change",
)
# The name of a frame, or of a shared object, that the profiler could not tell.
UNKNOWN = "[unknown]"
# The shared-object name of a symbol map a process writes for code it made at run time.
PERF_MAP_OBJECT = "[perf map]"
# What perf script prints in place of the shared object of an inlined frame.
INLINED = "inlined"

_ADDRESS = re.compile(r"[0-9a-fA-F]+")
_OFFSET = re.compile(r"\+0x[0-9a-fA-F]+$")
_PERF_MAP = re.compile(r"perf-\d+\.map")
_BUILD_ID = re.compile(r"[0-9a-fA-F]+")
_SPACES = re.compile(r"[\t\r\n\v\f]")

Stack = tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    """The sampled stacks of one side.

    ``instrument`` is ``stacks`` or ``pystacks``. ``stacks`` maps a stack,
    frames from the outermost to the innermost, to its number of samples.
    ``leaves`` maps the innermost frame of a sample, as the function and the
    shared object that holds it (``None`` where the instrument gives none),
    to its number of samples. ``objects`` maps each shared object the side
    loaded to its build ids; ``pystacks`` gives none.
    """

    instrument: str
    stacks: Mapping[Stack, int] = field(default_factory=dict)
    leaves: Mapping[tuple[str, str | None], int] = field(default_factory=dict)
    objects: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def samples(self) -> int:
        """The number of samples."""
        return sum(self.stacks.values())


@dataclass(frozen=True)
class DiffRow:
    """One stack of a difference file: its samples and shares on the subject and the baseline."""

    stack: str
    subject_samples: int
    baseline_samples: int
    subject_share: float
    baseline_share: float

    @property
    def share_change(self) -> float:
        """The subject's share minus the baseline's."""
        return self.subject_share - self.baseline_share


def clean_name(text: str) -> str:
    """Return a frame or object name as a folded line can hold it.

    ``;`` separates frames, so it becomes ``:``. A tab, a carriage return,
    a line feed, a vertical tab and a form feed become a space. The ends are
    stripped; an empty name is ``[unknown]``.
    """
    cleaned = _SPACES.sub(" ", text.replace(";", ":")).strip()
    return cleaned or UNKNOWN


def object_name(path: str) -> str:
    """Return the name a shared object is listed under: the last part of its path.

    A name in brackets, such as ``[kernel.kallsyms]`` or ``[vdso]``, stays as
    it is. The symbol map ``/tmp/perf-<pid>.map`` a process writes for code it
    made at run time is ``[perf map]`` on every side, whatever the process id.
    """
    text = path.strip()
    if not text:
        return UNKNOWN
    if text.startswith("["):
        return clean_name(text)
    last = text.rstrip("/").rpartition("/")[2]
    if _PERF_MAP.fullmatch(last):
        return PERF_MAP_OBJECT
    return clean_name(last)


def _split_frame(line: str) -> tuple[str | None, str, str | None]:
    """Split a frame line into the address, the symbol and the shared object.

    The first word is the instruction address when it is a hexadecimal
    number. The shared object is the last group in parentheses, read from
    the right; the symbol is everything between, so a symbol may hold spaces
    and parentheses.
    """
    text = line.strip()
    first, _, rest = text.partition(" ")
    address = first.lower() if _ADDRESS.fullmatch(first) else None
    if address is not None and rest:
        text = rest.strip()
    elif address is not None:
        return address, "", None
    if not text.endswith(")"):
        return address, text, None
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                return address, text[:index].strip(), text[index + 1 : -1]
    return address, text, None


@dataclass(frozen=True)
class _Frame:
    """One frame line: its name, its object, its address, and whether it was inlined."""

    name: str
    obj: str
    address: str | None
    inlined: bool


def _frame(line: str) -> _Frame:
    """Read one frame line."""
    address, symbol, dso = _split_frame(line)
    inlined = dso == INLINED
    obj = object_name(dso) if dso is not None and not inlined else UNKNOWN
    symbol = _OFFSET.sub("", symbol.strip())
    if symbol and symbol != UNKNOWN:
        name = clean_name(symbol)
    elif obj == UNKNOWN:
        name = UNKNOWN
    else:
        name = obj if obj.startswith("[") else f"[{obj}]"
    return _Frame(name=name, obj=obj, address=address, inlined=inlined)


def _with_inlined_objects(frames: list[_Frame]) -> list[tuple[str, str]]:
    """Return each frame's name and object, innermost first.

    An inlined frame takes the object of the frame it was inlined into: the
    first frame after it that was not inlined, at the same address. Without
    one it has the object ``[unknown]``.
    """
    out: list[tuple[str, str]] = []
    for index, frame in enumerate(frames):
        obj = frame.obj
        if frame.inlined:
            host = next((f for f in frames[index + 1 :] if not f.inlined), None)
            same = host is not None and (
                frame.address is None or host.address is None or host.address == frame.address
            )
            obj = host.obj if host is not None and same else UNKNOWN
        out.append((frame.name, obj))
    return out


def parse_perf_script(text: str, buildids: str = "") -> Profile:
    """Fold the text ``perf script`` printed for a recording with call graphs.

    Each sample counts once. A line that starts in the first column, or an
    indented line that follows a blank line, starts a sample; perf script
    indents the command of a header line when it prints no call graphs. A
    sample whose call chain is empty counts as the one frame ``[unknown]``.
    A frame without a symbol is named after its shared object in brackets.
    An inlined frame takes the shared object of the frame it was inlined
    into, so no object is ever named ``inlined``.
    ``buildids`` is what ``perf buildid-list`` printed for the same
    recording: the shared objects the side loaded.
    """
    stacks: Counter[Stack] = Counter()
    leaves: Counter[tuple[str, str | None]] = Counter()
    frames: list[_Frame] = []
    in_sample = False

    def close() -> None:
        chain = list(reversed(_with_inlined_objects(frames))) or [(UNKNOWN, UNKNOWN)]
        stacks[tuple(name for name, _obj in chain)] += 1
        leaves[chain[-1]] += 1

    for line in text.splitlines():
        if not line.strip():
            if in_sample:
                close()
            in_sample, frames = False, []
        elif line[0].isspace() and in_sample:
            frames.append(_frame(line))
        elif line.startswith("#"):
            continue
        else:
            if in_sample:
                close()
            in_sample, frames = True, []
    if in_sample:
        close()
    return Profile(
        instrument="stacks",
        stacks=dict(stacks),
        leaves=dict(leaves),
        objects=parse_buildids(buildids),
    )


def parse_buildids(text: str) -> dict[str, tuple[str, ...]]:
    """Read what ``perf buildid-list`` printed: each object's name and its build ids."""
    found: dict[str, set[str]] = {}
    for line in text.splitlines():
        build_id, _, path = line.strip().partition(" ")
        if not path.strip() or not _BUILD_ID.fullmatch(build_id):
            continue
        found.setdefault(object_name(path), set()).add(build_id.lower())
    return {name: tuple(sorted(ids)) for name, ids in sorted(found.items())}


def parse_folded(text: str) -> dict[Stack, int]:
    """Read a folded file: one stack per line, frames joined by ``;``, a space and a count.

    Blank lines and lines that start with ``#`` are skipped. A line without
    a whole number of samples after its last space is refused with
    ``ValueError``. Two lines of the same stack add up.
    """
    stacks: Counter[Stack] = Counter()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        stack, _, count = line.rstrip().rpartition(" ")
        if not stack or not count.isdigit():
            raise ValueError(f"line {number} of a folded file has no count of samples")
        stacks[tuple(clean_name(frame) for frame in stack.split(";"))] += int(count)
    return dict(stacks)


def profile_from_folded(text: str, instrument: str = "pystacks") -> Profile:
    """Build the profile of a side from a folded file, such as the sampler of ``pystacks`` writes.

    The instrument gives no shared objects, so every leaf has none.
    """
    stacks = parse_folded(text)
    leaves: Counter[tuple[str, str | None]] = Counter()
    for stack, count in stacks.items():
        leaves[(stack[-1], None)] += count
    return Profile(instrument=instrument, stacks=stacks, leaves=dict(leaves))


def stack_text(stack: Stack) -> str:
    """Return a stack as a folded line writes it: the frames joined by ``;``."""
    return ";".join(stack)


def folded_text(stacks: Mapping[Stack, int]) -> str:
    """Return the folded file of a side: the line about names, then one line per stack, sorted."""
    lines = [HOLDS_NAMES_LINE]
    lines.extend(
        f"{text} {count}" for text, count in sorted((stack_text(s), c) for s, c in stacks.items())
    )
    return "\n".join(lines) + "\n"


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def diff_rows(subject: Mapping[Stack, int], baseline: Mapping[Stack, int]) -> tuple[DiffRow, ...]:
    """Return one row per stack seen on either side, sorted by the stack text.

    A stack one side does not have counts zero there. A share is the
    stack's samples over all samples of its side, and zero for a side
    without samples.
    """
    own = {stack_text(s): c for s, c in subject.items()}
    other = {stack_text(s): c for s, c in baseline.items()}
    total_own, total_other = sum(own.values()), sum(other.values())
    return tuple(
        DiffRow(
            stack=text,
            subject_samples=own.get(text, 0),
            baseline_samples=other.get(text, 0),
            subject_share=_share(own.get(text, 0), total_own),
            baseline_share=_share(other.get(text, 0), total_other),
        )
        for text in sorted(set(own) | set(other))
    )


def fixed(value: float) -> str:
    """Write a share with six decimals; a value that rounds to zero is written without a sign."""
    text = f"{value:.6f}"
    return "0.000000" if text == "-0.000000" else text


def diff_text(rows: Iterable[DiffRow]) -> str:
    """Return a difference file: the line about names, the header row, one row per stack."""
    lines = [HOLDS_NAMES_LINE, "\t".join(DIFF_COLUMNS)]
    for row in rows:
        lines.append(
            "\t".join(
                (
                    row.stack,
                    str(row.subject_samples),
                    str(row.baseline_samples),
                    fixed(row.subject_share),
                    fixed(row.baseline_share),
                    fixed(row.share_change),
                )
            )
        )
    return "\n".join(lines) + "\n"


def top_functions(profile: Profile, top: int) -> tuple[TopFunction, ...]:
    """Return the functions with the largest share of samples, at most ``top`` of them.

    A sample belongs to its innermost frame. Ties are ordered by name. A
    share is rounded to six decimals.
    """
    total = profile.samples
    if not total:
        return ()
    ranked = sorted(profile.leaves.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))
    return tuple(
        TopFunction(name=name, object=obj, share=round(count / total, 6))
        for (name, obj), count in ranked[:top]
    )


def top_objects(profile: Profile, top: int) -> tuple[TopObject, ...]:
    """Return the shared objects with the largest share of samples, at most ``top`` of them.

    A sample belongs to the object of its innermost frame. An instrument
    that gives no shared objects gives an empty answer.
    """
    total = profile.samples
    by_object: Counter[str] = Counter()
    for (_name, obj), count in profile.leaves.items():
        if obj is not None:
            by_object[obj] += count
    if not total or not by_object:
        return ()
    ranked = sorted(by_object.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(
        TopObject(name=name, share=round(count / total, 6)) for name, count in ranked[:top]
    )


def compare_objects(profiles: Mapping[str, Profile]) -> ObjectDiff:
    """Compare the shared objects the sides loaded.

    Only sides whose stacks came from ``stacks`` and that list loaded objects
    take part, and only when there are two or more of them. ``only_in`` maps
    each such side to the objects no other such side loaded. ``differ``
    lists each object two or more of them loaded with different build ids,
    with each of those sides' build ids, joined by ``,`` where a side loaded
    several objects of that name. A side named ``name`` cannot be given a
    build id in an entry, whose key ``name`` holds the object's name.
    """
    sides = [s for s, p in profiles.items() if p.instrument == "stacks" and p.objects]
    if len(sides) < 2:
        return ObjectDiff()
    loaded = {side: set(profiles[side].objects) for side in sides}
    only_in: dict[str, tuple[str, ...]] = {}
    for side in sides:
        others = set().union(*(loaded[s] for s in sides if s != side))
        only_in[side] = tuple(sorted(loaded[side] - others))
    differ: list[dict[str, str]] = []
    for name in sorted(set().union(*loaded.values())):
        having = [s for s in sides if name in loaded[s]]
        ids = {s: ",".join(profiles[s].objects[name]) for s in having}
        if len(having) >= 2 and len(set(ids.values())) > 1:
            entry = {"name": name}
            entry.update({s: i for s, i in ids.items() if s != "name"})
            differ.append(entry)
    return ObjectDiff(only_in=only_in, differ=tuple(differ))
