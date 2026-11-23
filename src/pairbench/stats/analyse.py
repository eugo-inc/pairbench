# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Turn one capture, or several pooled captures, into the results document.

``analyse_captures`` refuses a whole analysis that cannot give results,
builds the grid of values the rule grades, judges the positive control,
grades every comparison with ``pairbench.stats.rules.grade`` and assembles
every part of ``Results`` except ``figures``, ``plugins`` and ``artifacts``.

``refused`` builds the results document of a refused run or analysis: every
part that describes the captures, no comparison, and the refusal listed. It
never raises.

Rounds of pooled captures are numbered across the captures in the order
given: the rounds of the second capture follow the last round of the first.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, TypeVar, cast

from pairbench.errors import EXIT_ANALYSIS, Refusal
from pairbench.model import (
    CASE_WALL,
    LAUNCH_COST_KINDS,
    NOTE_ALLOW_INCOMPLETE,
    NOTE_ALLOW_MIXED_MACHINES,
    NOTE_ASSUME_INTERLEAVED,
    NOTE_CASE_NAMED_APART,
    NOTE_CONTROL_FAILED,
    NOTE_CONTROL_NOT_JUDGED,
    NOTE_FLOOR_ONE_SIDED,
    NOTE_FLOOR_PROVISIONAL,
    NOTE_FLOOR_SUPPLIED,
    NOTE_LAUNCH_COST_SHARE,
    NOTE_POOL_FOLDERS_MERGED,
    NOTE_POOL_SECRETS_MERGED,
    NOTE_TORN_ROUND,
    NOTE_TWIN_DIFFERS,
    NOTE_WITNESS_UNDECIDED,
    STRICT,
    Capture,
    CaptureRef,
    Case,
    Comparison,
    ControlCase,
    Controls,
    ControlStatus,
    Degraded,
    DriverInfo,
    EnergyInfo,
    EnvPad,
    Floor,
    FloorPair,
    Floors,
    GateSummary,
    LaunchCost,
    MachineState,
    MachineStatus,
    MachineSummary,
    Note,
    PlanRow,
    PlanSummary,
    PositiveControl,
    Provenance,
    RefusalEntry,
    Results,
    ResultsSide,
    Role,
    Rule,
    RuleInfo,
    RunInfo,
    SameVsSame,
    Sensitivity,
    Series,
    Side,
    Tool,
    TwinCheck,
    Verdict,
    Witness,
    canonical_json,
    case_has_suffix,
    case_marked_name,
    case_secrets_hidden,
    case_suffix,
    case_text_sha256,
    case_unsuffixed,
    combine_hashes,
    compared_pairs,
    config_sha256,
    control_expected,
    control_within,
    count_balance,
    hidden_difference,
    launch_cost_note,
    min_rounds,
    p_equation,
    pooled_driver_info,
    pooled_driver_notes,
    public_command,
    recorded_workload,
    sha256_hex,
    side_setup,
    undecided,
    verdict_word,
    workload_difference,
)
from pairbench.stats.floor import FloorStat, median, pair_rounds, usable_ratio
from pairbench.stats.rules import Graded, Grading, Grid, grade, is_significant
from pairbench.stats.signtest import sign_test

_T = TypeVar("_T")

UNKNOWN = "unknown"
"""What the results say for a machine fact a capture does not record."""

TIME_SCALE: Mapping[str, float] = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
"""Seconds per unit of time, to hold a ``wall`` median against the cost of a launch."""

MAX_CELLS_SHOWN = 5
"""How many cells of each kind an ``E_GRID`` message names; the detail holds all of them."""

NOTE_POOL_BASELINE = "pool_baseline"
"""The note that pooled captures named different baselines and which one the pool took."""

FRACTION_DIGITS = 4300
"""The most decimal digits the denominator of a written p-value fraction holds.

It is Python's default limit on turning a whole number into decimal text and
back (``sys.int_info.default_max_str_digits``), so that the results can be
written and read again. The denominator ``2 ** n`` passes it at 14285 untied
pairs; from there on a comparison keeps its float p-value and no fraction.
"""


def _written_fraction(fraction: tuple[int, int] | None) -> tuple[int, int] | None:
    """The p-value fraction the results hold: ``fraction``, or ``None`` when it is too long."""
    if fraction is None or fraction[1] >= 10**FRACTION_DIGITS:
        return None
    return fraction


def _refuse(code: str, message: str, **detail: Any) -> Refusal:
    return Refusal(code, message, exit_code=EXIT_ANALYSIS, detail=detail)


# ---------------------------------------------------------------------------
# Refusals of a pool
# ---------------------------------------------------------------------------


def _rows(capture: Capture) -> tuple[tuple[int, str, str, float], ...]:
    """Return the observation rows of a capture, in record order, without the launch numbers."""
    return tuple((o.round, o.name, o.case, o.value) for o in capture.observations)


_Row = tuple[int, str, str, float]


def _same_run(short: Sequence[_Row], long: Sequence[_Row], at: int, width: int) -> bool:
    """Say whether the first ``width`` rows of ``short`` are those of ``long`` from ``at``.

    Rows are compared by side, case and value, and by where a new round
    begins, not by round number: a copy read from rows given from outside
    the tool numbers its rounds from 1 again, whichever rounds it holds.
    """
    for k in range(width):
        mine, theirs = short[k], long[at + k]
        if mine[1:] != theirs[1:]:
            return False
        if k and (mine[0] == short[k - 1][0]) != (theirs[0] == long[at + k - 1][0]):
            return False
    return True


def _is_stretch(short: Sequence[_Row], long: Sequence[_Row]) -> bool:
    """Say whether ``short`` is a contiguous stretch of ``long`` and shorter than it."""
    width = len(short)
    if not short or width >= len(long):
        return False
    return any(_same_run(short, long, at, width) for at in range(len(long) - width + 1))


def _is_torn(short: Sequence[_Row], long: Sequence[_Row]) -> bool:
    """Say whether ``short`` is a stretch of ``long`` whose last row was cut short.

    The rows before its last are a contiguous stretch of ``long``, and its
    last row has the round, side and case of the row that follows that
    stretch, with another value: a write that stopped inside a value.
    """
    width = len(short) - 1
    if width < 1 or width >= len(long):
        return False
    last = short[-1]
    for at in range(len(long) - width):
        follow = long[at + width]
        if follow[1:3] != last[1:3] or follow[3] == last[3]:
            continue
        if (follow[0] == long[at + width - 1][0]) != (last[0] == short[-2][0]):
            continue
        if _same_run(short, long, at, width):
            return True
    return False


def _is_copy(short: Sequence[_Row], long: Sequence[_Row]) -> bool:
    """Say whether ``short`` is a stretch of ``long``, its last row torn or whole."""
    return _is_stretch(short, long) or _is_torn(short, long)


def _identity_refusals(captures: Sequence[Capture]) -> Iterator[Refusal]:
    """Yield, for each pair of captures, the first of these that holds: the same capture
    given twice, identical rows, or a truncated copy."""
    rows = [_rows(c) for c in captures]
    for i, a in enumerate(captures):
        for j in range(i + 1, len(captures)):
            found = _pair_identity(a, captures[j], rows[i], rows[j])
            if found is not None:
                yield found


def _pair_identity(
    a: Capture, b: Capture, one: Sequence[_Row], two: Sequence[_Row]
) -> Refusal | None:
    pair = f"{a.capture_id} and {b.capture_id}"
    if a.capture_id == b.capture_id:
        return _refuse(
            "E_POOL_SAME",
            f"the capture {a.capture_id} is given twice",
            capture_id=a.capture_id,
        )
    first, second = a.source, b.source
    if first is not None and second is not None:
        if first.path is not None and first.path == second.path:
            return _refuse(
                "E_POOL_SAME",
                f"the captures {pair} were read from the same file",
                captures=[a.capture_id, b.capture_id],
            )
        if first.sha256 is not None and first.sha256 == second.sha256:
            return _refuse(
                "E_POOL_SAME",
                f"the captures {pair} were read from files with the same bytes",
                captures=[a.capture_id, b.capture_id],
            )
    if len(one) == len(two) and _same_run(one, two, 0, len(one)):
        return _refuse(
            "E_POOL_IDENTICAL_ROWS",
            f"the captures {pair} hold identical observation rows",
            captures=[a.capture_id, b.capture_id],
        )
    if _is_copy(one, two) or _is_copy(two, one):
        return _refuse(
            "E_POOL_TRUNCATED_COPY",
            f"the rows of one of the captures {pair} are a stretch of the other's, "
            "its last row whole or cut short",
            captures=[a.capture_id, b.capture_id],
        )
    return None


def _raise_first(refusals: Iterable[Refusal]) -> None:
    """Raise the first refusal of ``refusals``; run them to their end when there is none."""
    for refusal in refusals:
        raise refusal


def _purpose(capture: Capture) -> str:
    """Return ``self`` for a capture of one side against its own twins, else ``compare``."""
    launched = [s for s in capture.sides if s.role in ("subject", "baseline", "twin")]
    return "self" if len({s.source for s in launched}) == 1 else "compare"


def _side_key(side: Side) -> tuple[str, str | None, str | None]:
    """What a side must keep across pooled captures, besides its name and fingerprint.

    Its kind and its twin and control relations. Whether it is a subject or the
    baseline is no part of it: rows from outside the tool take the baseline from
    the order in which they first name the sides, and the baseline of a pool is
    set once for every capture in it (``_roles``).
    """
    return (side.kind, side.twin_of, side.control_of)


def _machine_key(capture: Capture) -> tuple[Any, ...] | None:
    machine = capture.machine
    if machine is None:
        return None
    core_types = tuple(sorted({group.key for group in machine.cpu.identity}))
    gpus = tuple(sorted(gpu.model for gpu in machine.gpu))
    return (machine.cpu.model, core_types, gpus)


def _hidden_drift(first: Capture, other: Capture) -> list[str]:
    """Return the sides whose recorded setups differ in more than a credential's value, sorted.

    The raw sides come from each capture's header (``side_setup``); a side
    that either capture does not hold so is left to the fingerprint check. A
    difference only in a credential itself is no drift, as
    ``hidden_difference`` says.
    """
    found: list[str] = []
    for side in first.sides:
        if side.role in ("twin", "control"):
            continue
        one = side_setup(first.header.config, side.name)
        two = side_setup(other.header.config, side.name)
        if hidden_difference(one, two):
            found.append(side.name)
    return sorted(found)


def _workload_refusal(first: Capture, other: Capture) -> Refusal | None:
    """The refusal of two captures whose shared workloads differ, naming the first argument
    that does, or ``None``.

    The workloads are those each header's config records, compared as the
    published hashes read them after the sides each capture records
    (``workload_difference``): a difference only in a credential, or only in
    a value hidden for its shape, is left to the checks after this one. The
    message names the argument by its place and by the text the shown
    command shows of it, never by a hidden value; when both show the same
    text, the arguments differ in a part the shown command leaves out, as
    the folders of a path.
    """
    found = workload_difference(first.header.config, other.header.config, first.sides, other.sides)
    if found is None:
        return None
    place, one, two = found
    where = f"at its argument {place}"
    if one == two:
        where += ", in a part the shown command leaves out"
    else:
        shown = ["no argument" if text is None else shlex.quote(text) for text in (one, two)]
        where += f": {shown[0]} against {shown[1]}"
    return _refuse(
        "E_POOL_SIDE_DRIFT",
        f"the workload differs between the captures {first.capture_id} and "
        f"{other.capture_id} {where}",
        captures=[first.capture_id, other.capture_id],
        argument=place,
    )


def _working_folder_refusal(first: Capture, other: Capture) -> Refusal | None:
    """The refusal of two captures whose sides ran in two working folders, or that cannot
    tell, or ``None``.

    Each side's entry records a hash of the folder it ran in
    (``Side.workdir_sha256``); they are compared as a yes or no, and the
    message names the sides, never a folder. A side that neither capture
    records a folder for, as a file side, pools. A side that one capture
    records a folder for and the other does not is refused too: the folders
    cannot be compared, and the captures are not pooled on a guess.
    """
    theirs = {side.name: side for side in other.sides}
    differ: list[str] = []
    unknown: list[str] = []
    for side in first.sides:
        if side.role in ("twin", "control"):
            continue
        one, two = side.workdir_sha256, theirs[side.name].workdir_sha256
        if one == two:
            continue
        (unknown if one is None or two is None else differ).append(side.name)
    pair = [first.capture_id, other.capture_id]
    if differ:
        return _refuse(
            "E_POOL_SIDE_DRIFT",
            f"the working folder of {', '.join(sorted(differ))} differs between the captures "
            f"{first.capture_id} and {other.capture_id}",
            sides=sorted(differ),
            captures=pair,
        )
    if unknown:
        missing = next(
            capture
            for capture in (first, other)
            for side in capture.sides
            if side.name in unknown and side.workdir_sha256 is None
        )
        return _refuse(
            "E_POOL_SIDE_DRIFT",
            f"the working folder of {', '.join(sorted(unknown))} could not be compared between "
            f"the captures {first.capture_id} and {other.capture_id}: {missing.capture_id} does "
            "not record it; run it again to pool it",
            sides=sorted(unknown),
            captures=pair,
        )
    return None


def _pool_refusals(
    captures: Sequence[Capture], allow_mixed_machines: bool, notes: list[Note]
) -> Iterator[Refusal]:
    """Yield the refusals of a pool whose captures do not belong to one experiment on one
    machine, in the order the analysis meets them.

    The analysis raises the first; ``pool_refusals`` lists them all. A capture
    whose sides differ from the first capture's gives one ``E_POOL_SIDE_DRIFT``
    and none for its fingerprints, setups, working folders or workload, since
    its sides cannot be matched; its cases and its machine are checked as
    every capture's are. The note of mixed machines that were allowed is added
    to ``notes`` once every check has run.
    """
    first = captures[0]
    purposes = {_purpose(c) for c in captures}
    if len(purposes) > 1:
        yield _refuse(
            "E_POOL_MIXED_PURPOSE",
            "a capture of one side against its own twins is pooled with a capture that "
            "compares different sides",
        )
    sides = {s.name: s for s in first.sides}
    # The workload of each capture is compared with that of the first capture that records
    # one, and its side setups with those of every capture before it, so a capture that
    # records none, or only part of a setup, does not keep two others apart from each other.
    shared = next((c for c in captures if recorded_workload(c.header.config) is not None), first)
    matched: list[Capture] = [first]
    for other in captures[1:]:
        theirs = {s.name: s for s in other.sides}
        if set(theirs) != set(sides) or any(
            _side_key(theirs[n]) != _side_key(sides[n]) for n in sides
        ):
            yield _refuse(
                "E_POOL_SIDE_DRIFT",
                f"the captures {first.capture_id} and {other.capture_id} hold different sides",
                captures=[first.capture_id, other.capture_id],
            )
            continue
        workload = _workload_refusal(shared, other)
        if workload is not None:
            yield workload
        drifted = sorted(n for n in sides if theirs[n].fingerprint != sides[n].fingerprint)
        if drifted:
            yield _refuse(
                "E_POOL_SIDE_DRIFT",
                f"the fingerprint of {', '.join(drifted)} differs between the captures "
                f"{first.capture_id} and {other.capture_id}",
                sides=drifted,
            )
        for earlier in matched:
            hidden = _hidden_drift(earlier, other)
            if hidden:
                yield _refuse(
                    "E_POOL_SIDE_DRIFT",
                    f"the setup of {', '.join(hidden)} differs between the captures "
                    f"{earlier.capture_id} and {other.capture_id} in a value the results hide",
                    sides=hidden,
                    captures=[earlier.capture_id, other.capture_id],
                )
        folders = _working_folder_refusal(first, other)
        if folders is not None:
            yield folders
        matched.append(other)
    cases = {c.id: c for c in first.cases}
    for other in captures[1:]:
        theirs_cases = {c.id: c for c in other.cases}
        differ = sorted(
            set(cases) ^ set(theirs_cases)
            | {k for k in set(cases) & set(theirs_cases) if cases[k] != theirs_cases[k]}
        )
        if differ:
            yield _refuse(
                "E_POOL_CASES",
                f"the cases {', '.join(differ)} differ between the captures "
                f"{first.capture_id} and {other.capture_id}",
                cases=differ,
            )
    machines = {_machine_key(c) for c in captures}
    if len(machines) > 1:
        if not allow_mixed_machines:
            yield _refuse(
                "E_POOL_MACHINE",
                "the CPU or GPU identity differs between the pooled captures",
            )
            return
        notes.append(
            Note(
                code=NOTE_ALLOW_MIXED_MACHINES,
                message="captures of machines whose CPU or GPU identity differs were pooled, "
                "because mixed machines were allowed",
            )
        )


def pool_refusals(
    captures: Sequence[Capture], *, allow_mixed_machines: bool = False
) -> list[Refusal]:
    """Return every refusal the analysis of ``captures`` pooled would meet in its pool checks.

    The checks are those of ``analyse_captures`` and share its code: the same
    capture given twice, identical rows, a truncated copy (``E_POOL_SAME``,
    ``E_POOL_IDENTICAL_ROWS``, ``E_POOL_TRUNCATED_COPY``), names a run marked
    that cannot be read alike (``E_USAGE``), and then a capture of one side
    against its twins pooled with a comparison, sides, workloads, setups or
    working folders that differ, other cases and other machines
    (``E_POOL_MIXED_PURPOSE``, ``E_POOL_SIDE_DRIFT``, ``E_POOL_CASES``,
    ``E_POOL_MACHINE``). The list is empty when the captures pool. Its first
    refusal is the one the analysis raises for the captures in the same order
    when each is complete or incomplete captures are allowed; the analysis
    refuses an incomplete capture with ``E_CAPTURE_INCOMPLETE`` after the first
    three checks. Nothing is raised for a refusal of the pool and nothing is
    printed. Whether each capture is complete, and its own grid, are checked
    by the analysis, not here.
    """
    given = tuple(captures)
    if any(not isinstance(c, Capture) for c in given):
        raise Refusal("E_USAGE", "check_pool takes captures")
    if not isinstance(allow_mixed_machines, bool):
        raise Refusal("E_USAGE", "allow_mixed_machines is true or false")
    found = list(_identity_refusals(given))
    if len(given) < 2:
        return found
    try:
        named = _named_alike(given)
    except Refusal as refusal:
        return [*found, refusal]
    found += _pool_refusals(named, allow_mixed_machines, [])
    return found


def _case_tells(capture: Capture) -> dict[str, str]:
    """Return the tell of each name a capture's run gave; refuse a name given to two cases."""
    tells: dict[str, str] = {}
    for entry in capture.case_names:
        known = tells.setdefault(entry.name, entry.tell_sha256)
        if known != entry.tell_sha256:
            raise Refusal(
                "E_USAGE",
                f"the capture {capture.capture_id} gives the name {entry.name!r} to two different "
                "cases; it was changed after its run",
            )
    return tells


def _case_renames(capture: Capture, key: bytes | None) -> dict[str, str]:
    """Return the name each mark of ``capture`` takes under ``key``; refuse a mark no run gave.

    A name with a mark (``case_suffix``) must be one the capture's run gave
    with its own key; an id that ends like a mark and that no run gave is
    refused, as is a capture whose marks its key does not give. With ``key``
    ``None`` every name keeps its mark.
    """
    tells = _case_tells(capture)
    own = bytes.fromhex(capture.case_key) if capture.case_key is not None else None
    marked: dict[str, str] = {}
    for name, tell in tells.items():
        if case_marked_name(name) != name:
            continue
        if own is None or not name.endswith(case_suffix(own, tell)):
            raise Refusal(
                "E_USAGE",
                f"the capture {capture.capture_id} holds the case {name!r} with a mark its run's "
                "key does not give; it was changed after its run",
            )
        marked[name] = tell
    ids = {case.id for case in capture.cases} | {o.case for o in capture.observations}
    for case_id in sorted(ids):
        part = case_marked_name(case_id)
        if part is not None and part not in marked:
            raise Refusal(
                "E_USAGE",
                f"the capture {capture.capture_id} holds the case {case_id!r}, which ends like the "
                "mark pairbench adds to a name whose cut dropped words, ' +' and eight hex digits, "
                "and no run gave it that mark; give it a name that does not end so",
            )
    if key is None or key == own:
        return {}
    width = len(case_suffix(key, ""))
    return {name: name[:-width] + case_suffix(key, tell) for name, tell in marked.items()}


def _renamed(capture: Capture, renames: Mapping[str, str]) -> Capture:
    """Return ``capture`` with every name in ``renames`` replaced, in ids and note texts."""
    if not renames:
        return capture
    olds = re.compile("|".join(re.escape(old) for old in sorted(renames, key=len, reverse=True)))

    def one(case_id: str) -> str:
        name = case_marked_name(case_id)
        if name is None or name not in renames:
            return case_id
        return renames[name] + case_id[len(name) :]

    def cases(given: Sequence[Case]) -> tuple[Case, ...]:
        return tuple(replace(case, id=one(case.id)) for case in given)

    lineup = capture.lineup
    return replace(
        capture,
        lineup=None if lineup is None else replace(lineup, cases=cases(lineup.cases)),
        cases=cases(capture.cases),
        observations=tuple(replace(o, case=one(o.case)) for o in capture.observations),
        notes=tuple(
            replace(note, message=olds.sub(lambda found: renames[found.group(0)], note.message))
            for note in capture.notes
        ),
        case_names=tuple(
            replace(entry, name=renames.get(entry.name, entry.name)) for entry in capture.case_names
        ),
    )


def _named_alike(captures: Sequence[Capture]) -> tuple[Capture, ...]:
    """Return the captures with every name a run marked given under the first capture's key.

    A run marks the name of an id whose cut dropped words with its own
    random key (``case_suffix``), so two runs give one case two marks; a
    pool shows the marks of the first capture, and two different cases
    whose marks clash under that key are refused with ``E_USAGE``. One
    capture keeps its names; a mark no run gave is refused either way.
    """
    first = captures[0].case_key
    key = bytes.fromhex(first) if first is not None else None
    named = tuple(_renamed(c, _case_renames(c, key)) for c in captures)
    owner: dict[str, tuple[str, str]] = {}
    for capture in named:
        for name, tell in _case_tells(capture).items():
            known = owner.setdefault(name, (tell, capture.capture_id))
            if known[0] != tell:
                raise Refusal(
                    "E_USAGE",
                    f"two different cases of the captures {known[1]} and {capture.capture_id} "
                    f"would have the name {name!r} in the pool: the marks pairbench adds to names "
                    "whose cut dropped words clash; analyse the captures apart",
                )
    return named


def _read_as(capture: Capture) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """Return, for each side and name a capture's run recorded, the ids it read, as hashes."""
    read: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for entry in capture.case_names:
        read.setdefault((entry.side, entry.name), set()).add(
            (entry.hidden_sha256, entry.read_sha256)
        )
    return read


def _names_case(name: str, case_id: str) -> bool:
    return case_id == name or case_id.startswith(name + "/")


def _pool_merge_notes(captures: Sequence[Capture]) -> list[Note]:
    """Return the loud notes of cases the pool reads from ids that differ between captures.

    Ids that differ in a word the results show, or in a word a cut drops
    that holds no ``/``, have different names and stay apart. Ids that
    differ only in words that hold a ``/``, read as folders, or only in a
    hidden secret, have one name: each capture's run kept, in its private
    capture, the hash of every id it read under such a name, and where the
    pooled captures read a name from different ids the pool reads them as
    one case and says so here, naming the case and never the words.
    """
    if len(captures) < 2:
        return []
    reads = [_read_as(c) for c in captures]
    observed = [{(o.name, o.case) for o in c.observations} for c in captures]
    folders: set[str] = set()
    secrets: set[str] = set()
    for side, name in sorted({key for read in reads for key in read}):
        sets: list[set[tuple[str, str]]] = []
        for capture_reads, seen in zip(reads, observed, strict=True):
            found = capture_reads.get((side, name))
            if found is not None:
                sets.append(found)
            elif any(s == side and _names_case(name, case) for s, case in seen):
                hidden = case_text_sha256(case_secrets_hidden(name))
                sets.append({(hidden, case_text_sha256(name))})
        if len({frozenset(h for h, _ in one) for one in sets}) > 1:
            folders.add(name)
        elif len({frozenset(one) for one in sets}) > 1:
            secrets.add(name)
    ids = [c.id for c in captures[0].cases]
    notes: list[Note] = []
    for code, names, why in (
        (
            NOTE_POOL_FOLDERS_MERGED,
            folders,
            "from ids that differ only in words that hold a '/' or in the folders of a path "
            "written with '%2F', which pairbench reads as folders; if those folders are "
            "different inputs, keep the captures apart",
        ),
        (
            NOTE_POOL_SECRETS_MERGED,
            secrets,
            "from ids that differ only in a hidden secret; if those secrets name different "
            "inputs, keep the captures apart",
        ),
    ):
        if not names:
            continue
        shown = sorted({i for name in names for i in ids if _names_case(name, i)} or names)
        quoted = ", ".join(repr(one) for one in shown)
        which = f"the case {quoted}" if len(shown) == 1 else f"each of the cases {quoted}"
        notes.append(Note(code=code, message=f"the pooled captures read {which} as one case {why}"))
    return notes


def _named_apart_notes(captures: Sequence[Capture]) -> list[Note]:
    """Return the loud note of cases that may be one case the sides named apart.

    A name gets the mark ``case_suffix`` makes when a cut of its id dropped
    words that hold no ``/``; a folder whose name holds a space gives such
    words. Two sides that read one case under folders that differ that way
    give it two names, and each is then on one side only. The primary cases
    of a run are refused at once when the sides give different sets of them;
    this note says it of the others: the ids each read by other sides than
    the other and whose names are one name without their marks.
    """
    sides: dict[str, set[str]] = {}
    for capture in captures:
        for one in capture.observations:
            sides.setdefault(one.case, set()).add(one.name)
    groups: dict[str, list[str]] = {}
    for case in sorted(sides):
        groups.setdefault(case_unsuffixed(case), []).append(case)
    apart: set[str] = set()
    for alike in groups.values():
        for i, first in enumerate(alike):
            for second in alike[i + 1 :]:
                marked = case_has_suffix(first) or case_has_suffix(second)
                if marked and not sides[first] & sides[second]:
                    apart.update((first, second))
    if not apart:
        return []
    quoted = ", ".join(repr(one) for one in sorted(apart))
    return [
        Note(
            code=NOTE_CASE_NAMED_APART,
            message=f"the cases {quoted} are each read by other sides, and their names are one "
            "name without the mark ' +' and eight hex digits that a cut adds when it drops "
            "words that hold no '/'; if they are one case, the words a path in its id runs over "
            "differ between the sides, as a folder whose name holds a space makes them, and the "
            "sides are not compared on it",
        )
    ]


# ---------------------------------------------------------------------------
# Refusals of one capture
# ---------------------------------------------------------------------------


def _check_complete(capture: Capture, allow_incomplete: bool, notes: list[Note]) -> None:
    if capture.complete:
        return
    end = capture.end
    why = "has no end record" if end is None else f"ended with the status {end.status}"
    if not allow_incomplete:
        raise _refuse(
            "E_CAPTURE_INCOMPLETE",
            f"the capture {capture.capture_id} {why}",
            capture_id=capture.capture_id,
        )
    notes.append(
        Note(
            code=NOTE_ALLOW_INCOMPLETE,
            message=f"the capture {capture.capture_id} {why}; its complete rounds were "
            "analysed because incomplete captures were allowed",
        )
    )


def _check_twins(capture: Capture) -> None:
    """Refuse a twin without its side, or with another fingerprint.

    A capture without a lineup is left to the grid check, which names that.
    """
    if capture.lineup is None:
        return
    names = set(capture.lineup.names)
    by_name = {s.name: s for s in capture.sides}
    for twin in capture.sides:
        if twin.role != "twin" or twin.twin_of is None:
            continue
        side = by_name.get(twin.twin_of)
        if side is None or side.role not in ("subject", "baseline") or twin.twin_of not in names:
            raise _refuse(
                "E_TWIN_ORPHAN",
                f"the twin {twin.name} names the side {twin.twin_of}, which is absent",
                twin=twin.name,
            )
        if twin.fingerprint != side.fingerprint:
            raise _refuse(
                "E_TWIN_DRIFT",
                f"the fingerprint of the twin {twin.name} differs from that of {side.name}",
                twin=twin.name,
            )


def _shown(cells: Sequence[Sequence[Any]]) -> str:
    text = ", ".join(" ".join(str(part) for part in cell) for cell in cells[:MAX_CELLS_SHOWN])
    more = len(cells) - MAX_CELLS_SHOWN
    return text + (f" and {more} more" if more > 0 else "")


def _control_stopped(capture: Capture) -> int | None:
    """The round in which the run went on without the positive control, or ``None``.

    That is the round of the last launch of the control when that launch
    failed and either a later launch of another entry follows it or the
    capture completed: the control has no launch in a later round. A failed
    launch that no launch follows in a capture that did not complete is the
    one the run stopped at.
    """
    control = capture.lineup.control if capture.lineup is not None else None
    launches = capture.round_launches()
    own = [x for x in launches if x.name == control]
    if not control or not own:
        return None
    final = max(own, key=lambda x: x.seq)
    if final.rc == 0:
        return None
    if capture.complete or final.seq < max(x.seq for x in launches):
        return final.round
    return None


def _control_stopped_run(capture: Capture) -> str | None:
    """Say how a failed launch of the positive control stopped the run, or ``None``.

    That is the last launch of a capture that did not complete, when it is a
    launch of the control that failed: the run stopped at it, as at any
    failed launch, and its round is left out.
    """
    control = capture.lineup.control if capture.lineup is not None else None
    launches = capture.round_launches()
    if not control or not launches or capture.complete:
        return None
    final = max(launches, key=lambda x: x.seq)
    if final.name != control or (final.rc == 0 and not final.timed_out):
        return None
    why = "ran into its timeout" if final.timed_out else f"exited with {final.rc}"
    return (
        f"the launch of {control} in round {final.round} of the capture "
        f"{capture.header.capture_id} {why} and stopped the run"
    )


def _expected(capture: Capture, round_: int, entries: Sequence[str]) -> list[str]:
    """The entries of ``entries`` that have a launch in round ``round_`` of the capture."""
    stop = _control_stopped(capture)
    if stop is None or round_ <= stop or capture.lineup is None:
        return list(entries)
    return [e for e in entries if e != capture.lineup.control]


def _whole(capture: Capture, round_: int, entries: Sequence[str]) -> bool:
    """Say whether a round of a capture without an end record is whole.

    Every entry has exactly one launch in the round, each with exit code 0,
    and each holds an observation of every case the same entry gave in the
    round before; in round 1, of every primary case. A run writes each
    launch record and then its observations, so a run stopped hard can leave
    the last launch with some of its observations or none.
    """
    entries = _expected(capture, round_, entries)
    found = [x for x in capture.round_launches() if x.round == round_]
    names = [x.name for x in found]
    if not (all(names.count(e) == 1 for e in entries) and all(x.rc == 0 for x in found)):
        return False
    gave: dict[tuple[int, str], set[str]] = {}
    for obs in capture.round_observations():
        if obs.round in (round_ - 1, round_):
            gave.setdefault((obs.round, obs.name), set()).add(obs.case)
    primary = {c.id for c in capture.cases if c.primary}
    return all(
        (gave.get((round_ - 1, e), set()) if round_ > 1 else primary)
        <= gave.get((round_, e), set())
        for e in entries
    )


def _entries(capture: Capture) -> tuple[str, ...]:
    """The entries of every round: the lineup and the positive control, if any."""
    lineup = capture.lineup
    if lineup is None:
        return ()
    return (*lineup.names, *((lineup.control,) if lineup.control else ()))


def _kept_rounds(capture: Capture, entries: Sequence[str]) -> int:
    """Return the number of rounds an analysis of the capture keeps.

    A complete capture keeps the rounds its end record counts. Any other
    keeps the rounds that have a launch, less those after the count of its
    end record when it has one, and less its last round when that round is
    not whole or the last line of its file was torn.
    """
    if capture.complete and capture.end is not None:
        return capture.end.rounds_completed
    last = max((x.round for x in capture.round_launches()), default=0)
    counted = capture.end.rounds_completed if capture.end is not None else None
    if counted is not None and 0 <= counted < last:
        # The run said how many rounds it completed: a later round is torn
        # even when each of its launches kept exit code 0, as when a driver
        # read is refused after the launch.
        return counted
    torn = capture.source is not None and capture.source.torn
    if last >= 1 and (torn or not _whole(capture, last, entries)):
        return last - 1
    return last


def _analysed_rounds(captures: Sequence[Capture], rounds: Sequence[int] | None) -> list[int]:
    """The rounds an analysis keeps of each capture: ``rounds``, or else worked out.

    A capture whose grid cannot be read keeps the rounds its entry counts.
    """
    if rounds is not None:
        return list(rounds)
    return [
        _safe(partial(_kept_rounds, c, _entries(c)), _safe(partial(_ref_rounds, c), 0))
        for c in captures
    ]


def _check_grid(capture: Capture, notes: list[Note]) -> int:
    """Refuse a grid of rounds and entries that does not match the lineup.

    Returns the number of rounds analysed. A capture that did not complete
    loses the rounds ``_kept_rounds`` does not keep, loudly.
    """
    lineup = capture.lineup
    if lineup is None:
        raise _refuse(
            "E_GRID",
            f"the capture {capture.capture_id} has no lineup record",
            capture_id=capture.capture_id,
        )
    by_name = {s.name: s for s in capture.sides}
    unknown = [n for n in lineup.names if n not in by_name]
    if unknown:
        raise _refuse(
            "E_GRID",
            f"the lineup of the capture {capture.capture_id} names {', '.join(unknown)}, "
            "which no side record describes",
            capture_id=capture.capture_id,
            no_side_record=unknown,
        )
    entries = _entries(capture)
    launches = capture.round_launches()
    last = _kept_rounds(capture, entries)
    found = max((x.round for x in launches), default=0)
    if not capture.complete and last < found:
        one = last + 1 == found
        left_out = f"round {found}" if one else f"rounds {last + 1} to {found}"
        notes.append(
            Note(
                code=NOTE_TORN_ROUND,
                message=f"{left_out} of the capture {capture.capture_id} "
                f"{'is' if one else 'are'} incomplete and {'was' if one else 'were'} left out",
            )
        )
        launches = tuple(x for x in launches if x.round <= last)
    counts: dict[tuple[int, str], int] = {}
    unexpected: list[list[Any]] = []
    for launch in launches:
        if launch.name not in entries or launch.round > last:
            if launch.round <= last or capture.complete:
                unexpected.append([launch.round, launch.name])
            continue
        key = (launch.round, launch.name)
        counts[key] = counts.get(key, 0) + 1
    missing = [
        [r, e]
        for r in range(1, last + 1)
        for e in _expected(capture, r, entries)
        if (r, e) not in counts
    ]
    duplicated: list[list[Any]] = [[r, e] for (r, e), n in counts.items() if n > 1]
    seen: set[tuple[int, str, str]] = set()
    known_cases = {c.id for c in capture.cases}
    undeclared: list[str] = []
    for obs in capture.round_observations():
        if obs.round > last and not capture.complete:
            continue
        if (obs.round, obs.name) not in counts:
            cell = [obs.round, obs.name]
            if cell not in unexpected:
                unexpected.append(cell)
            continue
        key3 = (obs.round, obs.name, obs.case)
        if key3 in seen:
            duplicated.append([obs.round, obs.name, obs.case])
        seen.add(key3)
        if obs.case not in known_cases and obs.case not in undeclared:
            undeclared.append(obs.case)
    if missing or duplicated or unexpected or undeclared:
        # A round is named by the label its input gave it, as rows given from
        # outside the tool are numbered 1, 2, 3 in the capture.
        label = capture.source.round_label if capture.source is not None else int
        missing, duplicated, unexpected = (
            [[label(cast("int", cell[0])), *cell[1:]] for cell in cells]
            for cells in (missing, duplicated, unexpected)
        )
        parts = []
        if missing:
            parts.append(f"missing {_shown(missing)}")
        if duplicated:
            parts.append(f"duplicated {_shown(duplicated)}")
        if unexpected:
            parts.append(f"unexpected {_shown(unexpected)}")
        if undeclared:
            parts.append(f"cases no record declares {', '.join(undeclared)}")
        raise _refuse(
            "E_GRID",
            f"the grid of rounds and lineup entries of the capture {capture.capture_id} "
            f"does not match its lineup: {'; '.join(parts)}",
            capture_id=capture.capture_id,
            missing=missing,
            duplicated=duplicated,
            unexpected=unexpected,
            cases=undeclared,
        )
    return last


# ---------------------------------------------------------------------------
# Roles and the pooled grid
# ---------------------------------------------------------------------------


def _pool_baseline_notes(captures: Sequence[Capture], baseline: str | None) -> list[Note]:
    """One note when pooled captures name different baselines and none was named.

    The baseline of the first capture is then the baseline of every capture.
    """
    named = [(c.capture_id, c.baseline) for c in captures]
    if baseline is not None or len({b for _, b in named}) < 2 or named[0][1] is None:
        return []
    shown = ", ".join(f"{b} in {ident}" for ident, b in named if b is not None)
    return [
        Note(
            code=NOTE_POOL_BASELINE,
            message=f"the pooled captures do not name one baseline ({shown}); {named[0][1]}, "
            "the baseline of the first capture, is the baseline of the pool; name the "
            "baseline to choose another",
        )
    ]


def _roles(capture: Capture, baseline: str | None) -> dict[str, Role]:
    """Return the role of every side in the analysis, with another baseline when one is named.

    For pooled captures this is the first capture: its roles hold for the pool.
    """
    roles: dict[str, Role] = {s.name: s.role for s in capture.sides}
    recorded = capture.baseline
    if baseline is None:
        if recorded is None:
            raise Refusal("E_USAGE", f"the capture {capture.capture_id} names no baseline")
        return roles
    if roles.get(baseline) not in ("subject", "baseline"):
        raise Refusal("E_USAGE", f"{baseline!r} is no subject or baseline of the capture")
    if recorded is not None:
        roles[recorded] = "subject"
    roles[baseline] = "baseline"
    return roles


@dataclass(frozen=True)
class _Prepared:
    capture: Capture
    rounds: int
    offset: int


@dataclass(frozen=True)
class _Pool:
    grid: Grid
    control: Mapping[tuple[str, str], Mapping[int, float]]
    plan_rows: tuple[PlanRow, ...]
    unordered: bool
    total: int


def _pool(
    prepared: Sequence[_Prepared], roles: Mapping[str, Role], disturbed: Sequence[int]
) -> _Pool:
    first = prepared[0].capture
    assert first.lineup is not None
    names = first.lineup.names
    sides = {s.name: s for s in first.sides}
    controls = {s.name for s in first.sides if s.role == "control"}
    values: dict[tuple[str, str], dict[int, float]] = {}
    control: dict[tuple[str, str], dict[int, float]] = {}
    positions: dict[tuple[int, str], int | None] = {}
    rows: list[PlanRow] = []
    unordered = False
    for part in prepared:
        kept = range(1, part.rounds + 1)
        for obs in part.capture.round_observations():
            if obs.round not in kept:
                continue
            where = values if obs.name in names else control if obs.name in controls else None
            if where is not None:
                where.setdefault((obs.name, obs.case), {})[part.offset + obs.round] = obs.value
        for launch in part.capture.round_launches():
            if launch.round not in kept or launch.name not in names:
                continue
            g = part.offset + launch.round
            positions[(g, launch.name)] = launch.pos
            if launch.pos is None:
                unordered = True
                continue
            side = sides[launch.name]
            rows.append(
                PlanRow(
                    round=g,
                    pos=launch.pos,
                    name=launch.name,
                    side=side.source,
                    twin_of=side.twin_of,
                )
            )
    total = sum(p.rounds for p in prepared)
    twins: dict[str, str] = {}
    for name in names:
        side = sides[name]
        if side.role == "twin" and side.twin_of is not None:
            twins.setdefault(side.twin_of, name)
    baseline = next(n for n, r in roles.items() if r == "baseline")
    grid = Grid(
        rounds=tuple(range(1, total + 1)),
        values=values,
        positions=positions,
        subjects=tuple(n for n in names if roles.get(n) == "subject"),
        baseline=baseline,
        twins=twins,
        cases=first.cases,
        disturbed=tuple(disturbed),
    )
    return _Pool(
        grid=grid, control=control, plan_rows=tuple(rows), unordered=unordered, total=total
    )


def _analysis_sides(capture: Capture, roles: Mapping[str, Role]) -> tuple[Side, ...]:
    return tuple(
        s.with_role(roles[s.name]) if roles.get(s.name, s.role) != s.role else s
        for s in capture.sides
    )


def _check_order(pool: _Pool, sides: Sequence[Side], names: Sequence[str]) -> None:
    """Refuse a compared pair that ran in the same order in every one of two or more rounds."""
    lineup = [s for s in sides if s.name in names]
    for balance in count_balance(pool.plan_rows, compared_pairs(lineup)):
        counted = balance.a_first + balance.b_first
        if counted >= 2 and min(balance.a_first, balance.b_first) == 0:
            ahead = balance.a if balance.a_first else balance.b
            behind = balance.b if balance.a_first else balance.a
            raise _refuse(
                "E_ORDER_NOT_VARIED",
                f"{ahead} ran before {behind} in every one of {counted} rounds",
                pair=[balance.a, balance.b],
            )


def _disturbed(prepared: Sequence[_Prepared]) -> tuple[tuple[int, ...], str | None]:
    rounds: list[int] = []
    hashes: list[str | None] = []
    for part in prepared:
        decision = part.capture.set_aside()
        hashes.append(decision.sha256 if decision is not None else None)
        if decision is not None:
            rounds += [part.offset + r for r in decision.rounds if 1 <= r <= part.rounds]
    return tuple(sorted(set(rounds))), combine_hashes(hashes)


# ---------------------------------------------------------------------------
# The positive control
# ---------------------------------------------------------------------------


def _not_judged(
    entry: str | None, via: Any, tolerance: float, why: str
) -> tuple[PositiveControl, list[Note]]:
    note = Note(code=NOTE_CONTROL_NOT_JUDGED, message=f"the positive control was not judged: {why}")
    return PositiveControl(status="not_run", entry=entry, via=via, tolerance=tolerance), [note]


def _judge_control(
    captures: Sequence[Capture], pool: _Pool, rule: Rule
) -> tuple[PositiveControl, list[Note]]:
    """Judge the positive control of the captures and return its record and its notes."""
    settings = captures[0].control_settings()
    via, tolerance = settings.positive_via, settings.positive_tolerance
    entries = [tuple(s for s in c.sides if s.role == "control") for c in captures]
    named = [c.lineup.control if c.lineup is not None else None for c in captures]
    if not any(entries) and not any(named):
        return PositiveControl(status="not_run", via=via, tolerance=tolerance), []
    if any(len(found) > 1 for found in entries):
        return _not_judged(None, via, tolerance, "a capture holds more than one control entry")
    keys = {(found[0].name, found[0].control_of) if found else None for found in entries}
    if keys == {None}:
        return _not_judged(
            None, via, tolerance, "no side record describes the control entry the lineup names"
        )
    if len(keys) > 1:
        return _not_judged(
            None, via, tolerance, "the pooled captures do not share one control entry"
        )
    control = entries[0][0]
    if any(n is None for n in named):
        return _not_judged(
            control.name, via, tolerance, f"a lineup does not name the control entry {control.name}"
        )
    if any(n != control.name for n in named):
        return _not_judged(control.name, via, tolerance, "the lineup names another control entry")
    if any(control.control_of != c.baseline for c in captures):
        return _not_judged(
            control.name,
            via,
            tolerance,
            f"{control.name} is the control of {control.control_of}, which is not the baseline",
        )
    if any(_control_stopped(c) is not None for c in captures):
        return _not_judged(
            control.name,
            via,
            tolerance,
            f"a launch of {control.name} failed and the run went on without the control",
        )
    base = cast("str", control.control_of)
    need = min_rounds(1, rule.alpha)
    primary = [c for c in pool.grid.cases if c.primary]
    paired = {
        c.id: pair_rounds(
            pool.control.get((control.name, c.id), {}), pool.grid.of(base, c.id), pool.grid.rounds
        )
        for c in primary
    }
    if not any(len(paired[c.id][0]) >= need for c in primary):
        stopped = [why for c in captures if (why := _control_stopped_run(c)) is not None]
        return _not_judged(
            control.name,
            via,
            tolerance,
            "".join(f"{why}, so " for why in stopped[:1])
            + f"no primary case has the {need} paired rounds of the control and the baseline "
            "that judging it needs",
        )
    rows: list[ControlCase] = []
    failed: list[str] = []
    for case in primary:
        got, xs, ys = paired[case.id]
        expected = control_expected(case.better)
        assert expected is not None
        row = _control_row(case, expected, got, xs, ys, need, tolerance, rule)
        rows.append(row)
        if not row.passed:
            failed.append(_control_failure(case.id, row, need, xs, ys))
    status: ControlStatus = "failed" if failed else "ok"
    record = PositiveControl(
        status=status, entry=control.name, via=via, tolerance=tolerance, cases=tuple(rows)
    )
    if not failed:
        return record, []
    note = Note(
        code=NOTE_CONTROL_FAILED,
        message=f"the positive control failed on {', '.join(failed)}: twice the work did not "
        "read as twice the measured value, so no difference this run reports can be trusted "
        "and every comparison is NO VERDICT",
    )
    return record, [note]


def _control_failure(
    case: str, row: ControlCase, need: int, xs: Sequence[float], ys: Sequence[float]
) -> str:
    """The case a control failed on, with the cause when it read no ratio."""
    if row.n_rounds < need:
        return f"{case} (too few paired rounds)"
    if row.ratio is not None:
        return case
    if any(v <= 0 for v in (*xs, *ys)):
        return f"{case} (a value of zero or less was recorded)"
    return f"{case} (its ratio to the baseline is too large or too small to be a finite number)"


def _control_row(
    case: Case,
    expected: float,
    got: Sequence[int],
    xs: Sequence[float],
    ys: Sequence[float],
    need: int,
    tolerance: float,
    rule: Rule,
) -> ControlCase:
    n = len(got)
    if n < need or any(v <= 0 for v in (*xs, *ys)):
        return ControlCase(
            case=case.id, expected=expected, ratio=None, p_raw=None, n_rounds=n, passed=False
        )
    ratio = usable_ratio(median([x / y for x, y in zip(xs, ys, strict=True)]))
    if ratio is None:
        # The control and the baseline are too far apart for their ratio, its
        # inverse or its percent to be a finite number: twice the work did not
        # read as twice the value.
        return ControlCase(
            case=case.id, expected=expected, ratio=None, p_raw=None, n_rounds=n, passed=False
        )
    n_higher = sum(1 for x, y in zip(xs, ys, strict=True) if x > y)
    n_lower = sum(1 for x, y in zip(xs, ys, strict=True) if x < y)
    p = sign_test(n_lower, n_higher).p
    direction = n_higher > n_lower if expected > 1.0 else n_lower > n_higher
    passed = control_within(ratio, expected, tolerance) and direction and is_significant(p, rule)
    return ControlCase(
        case=case.id, expected=expected, ratio=ratio, p_raw=p, n_rounds=n, passed=passed
    )


# ---------------------------------------------------------------------------
# The parts of the results document
# ---------------------------------------------------------------------------


def _safe(make: Callable[[], _T], fallback: _T) -> _T:
    """Return what ``make`` builds, or the fallback when it raises."""
    try:
        return make()
    except Exception:
        return fallback


def _include_image_refs(capture: Capture) -> bool:
    report = capture.header.config.get("report")
    return isinstance(report, Mapping) and report.get("include_image_refs") is True


def _run_info(captures: Sequence[Capture], rounds: Sequence[int] | None = None) -> RunInfo:
    """The run entry; each capture's ``rounds`` is the number of rounds analysed."""
    if not captures:
        return RunInfo(id="no-capture", started_at=None, finished_at=None, captures=())
    first, last = captures[0], captures[-1]
    if len(captures) == 1:
        run_id = first.capture_id
    else:
        run_id = "pool-" + sha256_hex(canonical_json([c.capture_id for c in captures]))[:12]
    refs = tuple(
        replace(_safe(c.ref, CaptureRef(capture_id=c.capture_id, sha256=None, rounds=0)), rounds=n)
        for c, n in zip(captures, _analysed_rounds(captures, rounds), strict=True)
    )
    command = _safe(
        lambda: public_command(
            first.header.argv,
            include_image_refs=_include_image_refs(first),
            config=first.header.config,
            sides=first.sides,
        ),
        None,
    )
    return RunInfo(
        id=run_id,
        started_at=first.header.started_at,
        finished_at=last.end.finished_at if last.end is not None else None,
        captures=refs,
        pooled=len(captures) > 1,
        command=command,
    )


def _ref_rounds(capture: Capture) -> int:
    return capture.ref().rounds


def _plain(family_size: int) -> str:
    if family_size == 0:
        return "no case tested"
    if family_size == 1:
        return "one case tested"
    return f"corrected for testing {family_size} cases at once"


def _rule_info(rule: Rule, family_size: int) -> RuleInfo:
    return RuleInfo(
        name=rule.name, fields=rule.to_json(), family_size=family_size, plain=_plain(family_size)
    )


def _provenance(captures: Sequence[Capture]) -> Provenance:
    unknown = MachineSummary(os=UNKNOWN, arch=UNKNOWN, cpu_model=UNKNOWN)
    if not captures:
        return Provenance(machine=unknown)
    first = captures[0]
    machine = first.machine
    hashes = [_safe(partial(config_sha256, c.header.config, c.sides), None) for c in captures]
    return Provenance(
        machine=_safe(machine.summary, unknown) if machine is not None else unknown,
        gpu=machine.gpu if machine is not None else (),
        engine=machine.engine if machine is not None else None,
        node_type=machine.node_type if machine is not None else None,
        seeds=first.header.seeds,
        config_sha256=combine_hashes(hashes),
        driver=_run_driver(captures),
    )


def _run_driver(captures: Sequence[Capture]) -> DriverInfo | None:
    """Return the driver entry of the whole run, made of the entries of every side.

    It agrees with ``sides[].driver``: every tool version any side recorded,
    and a name only when every side of every capture was read by that one
    driver.
    """
    return pooled_driver_info(
        [_safe(partial(c.side_driver_info, s.name), None) for c in captures for s in c.sides]
    )


def _results_sides(
    captures: Sequence[Capture], roles: Mapping[str, Role] | None
) -> tuple[ResultsSide, ...]:
    if not captures:
        return ()
    first = captures[0]
    include = _include_image_refs(first)
    sides = first.sides if roles is None else _analysis_sides(first, roles)
    out: list[ResultsSide] = []
    for side in sides:
        driver = pooled_driver_info(
            [_safe(partial(c.side_driver_info, side.name), None) for c in captures]
        )
        shown = _safe(partial(side.for_results, include_image_ref=include, driver=driver), None)
        if shown is not None:
            out.append(shown)
    return tuple(out)


def _warmups(capture: Capture) -> int:
    counts: dict[str, int] = {}
    for launch in capture.launches:
        if launch.phase == "warmup":
            counts[launch.name] = counts.get(launch.name, 0) + 1
    return max(counts.values(), default=0)


def _requested(capture: Capture) -> int | None:
    run = capture.header.config.get("run")
    rounds = run.get("rounds") if isinstance(run, Mapping) else None
    return rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else None


def _plan(captures: Sequence[Capture], completed: Sequence[int] | None) -> PlanSummary:
    if not captures:
        return PlanSummary(
            schedule=None,
            rounds_requested=None,
            rounds_planned=0,
            rounds_completed=0,
            warmups=0,
            launches=0,
        )
    first = captures[0]
    requested = [_requested(c) for c in captures]
    completed = _analysed_rounds(captures, completed)
    return PlanSummary(
        schedule=first.lineup.schedule if first.lineup is not None else None,
        rounds_requested=None if None in requested else sum(cast("list[int]", requested)),
        rounds_planned=sum(c.lineup.rounds if c.lineup is not None else 0 for c in captures),
        rounds_completed=sum(completed),
        warmups=max(_warmups(c) for c in captures),
        launches=sum(len(c.launches) for c in captures),
        explain_launches=sum(_safe(c.explain_launches, 0) for c in captures),
    )


def _undecided_in(capture: Capture, rounds: int) -> int:
    """The launches of the first ``rounds`` rounds the busy-core witness could not judge."""
    if capture.lineup is None or capture.lineup.discard_thresholds is None:
        return 0
    thresholds = capture.lineup.discard_thresholds
    return sum(
        1
        for x in capture.round_launches()
        if x.round <= rounds and undecided(Witness.from_json(x.witness), thresholds)
    )


def _undecided(captures: Sequence[Capture], rounds: Sequence[int] | None) -> int:
    """The launches the busy-core witness could not judge, in the rounds analysed.

    A round an analysis leaves out, as a torn last round, is not counted.
    """
    kept = _analysed_rounds(captures, rounds)
    return sum(_safe(partial(_undecided_in, c, n), 0) for c, n in zip(captures, kept, strict=True))


def _launches(n: int) -> str:
    return f"{n} launch" if n == 1 else f"{n} launches"


def _machine_state(
    captures: Sequence[Capture],
    busy: bool,
    discard_sha256: str | None,
    rounds: Sequence[int] | None = None,
) -> MachineState:
    """The state of the machine during the run.

    It is busy when a check failed or more than half the analysed rounds
    were set aside; quiet when at least one check ran, every check passed
    and the busy-core witness judged every launch; unknown otherwise. A
    launch the witness could not judge does not mark its round as disturbed
    and adds one degraded entry for the CPU checks.
    """
    gates: list[GateSummary] = []
    degraded: list[Degraded] = []
    statuses: list[str] = []
    for capture in captures:
        for gate in capture.gates:
            statuses.append(gate.status)
            summary = _safe(gate.summary, None)
            if summary is not None:
                gates.append(summary)
            entry = _safe(gate.degraded, None)
            if entry is not None:
                degraded.append(entry)
    undecided = _undecided(captures, rounds)
    if undecided:
        degraded.append(
            Degraded(
                name="cpus",
                status="degraded",
                message=f"the busy-core witness could not judge {_launches(undecided)}: a side "
                "that reports no CPU time of its own was counted with its own load in; pin a "
                "CPU set with --cpus for the full witness",
            )
        )
    status: MachineStatus
    if busy or "fail" in statuses:
        status = "busy"
    elif statuses and all(s == "pass" for s in statuses) and not undecided:
        status = "quiet"
    else:
        status = "unknown"
    return MachineState(
        status=status,
        gates=tuple(gates),
        degraded=tuple(degraded),
        discard_sha256=discard_sha256,
        undecided_launches=undecided,
    )


def _undecided_notes(captures: Sequence[Capture], rounds: Sequence[int]) -> list[Note]:
    """One note when the busy-core witness could not judge a launch of the rounds analysed.

    None when a capture already holds that note, as a run writes it.
    """
    undecided = _undecided(captures, rounds)
    if not undecided:
        return []
    if any(note.code == NOTE_WITNESS_UNDECIDED for c in captures for note in c.notes):
        return []
    return [
        Note(
            code=NOTE_WITNESS_UNDECIDED,
            message=f"the busy-core witness could not judge {_launches(undecided)}: the side "
            "reports no CPU time of its own, and the busy cores counted with its own load in "
            "were above the threshold; the launches do not mark their rounds as disturbed, and "
            "the machine state is not quiet",
        )
    ]


def _capture_notes(captures: Sequence[Capture]) -> list[Note]:
    out: list[Note] = []
    for capture in captures:
        for note in capture.notes:
            out.append(_safe(note.for_results, note))
    return out


def _energy(captures: Sequence[Capture]) -> EnergyInfo | None:
    sampled = any(launch.energy for c in captures for launch in c.launches)
    return EnergyInfo() if sampled else None


def _env_pad(captures: Sequence[Capture]) -> EnvPad:
    return EnvPad.of(any(_safe(c.env_pad, EnvPad()).varied for c in captures))


def _floor(stat: FloorStat | None) -> Floor | None:
    if stat is None or stat.value is None:
        return None
    return Floor(
        value=stat.value,
        n=stat.n,
        provisional=stat.provisional,
        spread=stat.spread,
        outlier_rounds=stat.outlier_rounds,
    )


def _comparison(g: Graded, rule: Rule) -> Comparison:
    s = g.sensitivity
    return Comparison(
        case=g.case.id,
        primary=g.case.primary,
        subject=g.subject,
        baseline=g.baseline,
        n_rounds=g.n_rounds,
        n_unpaired=g.n_unpaired,
        n_untied=g.n_untied,
        n_lower=g.n_lower,
        n_higher=g.n_higher,
        subject_median=g.subject_median,
        baseline_median=g.baseline_median,
        ratio=g.ratio,
        statistic=g.statistic,
        scale=rule.scale,
        gap=g.gap,
        floor=FloorPair(
            source=g.source,
            unit=rule.unit,
            subject=_floor(g.subject_floor),
            baseline=_floor(g.baseline_floor),
            mode=g.mode,
        ),
        bar=g.bar,
        p_raw=g.p_raw,
        p_raw_fraction=_written_fraction(g.p_fraction),
        p_corrected=g.p_corrected,
        verdict=cast("Verdict", verdict_word(g.outcome, g.case.kind)),
        outcome=g.outcome,
        reason=g.reason,
        reasons=g.reasons,
        order_split=g.order_split,
        sensitivity=Sensitivity(
            rounds_set_aside=s.rounds_set_aside,
            ratio=s.ratio,
            outcome=s.outcome,
            agrees=s.agrees,
            not_computed=s.not_computed,
        ),
    )


def _series(pool: _Pool, names: Sequence[str]) -> tuple[Series, ...]:
    grid = pool.grid
    out: list[Series] = []
    for case in grid.cases:
        if not case.primary:
            continue
        for name in names:
            values = grid.of(name, case.id)
            out.append(
                Series(
                    case=case.id,
                    name=name,
                    values=tuple(values.get(r) for r in grid.rounds),
                    disturbed_rounds=grid.disturbed,
                )
            )
    return tuple(out)


def _launch_cost_notes(capture: Capture, pool: _Pool, cost: LaunchCost | None) -> list[Note]:
    if cost is None:
        return []
    wall = next((c for c in pool.grid.cases if c.id == CASE_WALL), None)
    if wall is None or wall.unit not in TIME_SCALE:
        return []
    share = capture.launch_cost_share()
    names = capture.lineup.names if capture.lineup is not None else ()
    out: list[Note] = []
    for side in capture.sides:
        if side.name not in names or side.role not in ("subject", "baseline"):
            continue
        if side.kind not in LAUNCH_COST_KINDS:
            continue
        values = list(pool.grid.of(side.name, CASE_WALL).values())
        if not values:
            continue
        median_s = median(values) * TIME_SCALE[wall.unit]
        if launch_cost_note(median_s, cost.median_s, share):
            out.append(
                Note(
                    code=NOTE_LAUNCH_COST_SHARE,
                    message=f"the median wall time of {side.name}, {median_s:.3g} s, is less "
                    f"than {1 / share:g} times the median cost of a launch, "
                    f"{cost.median_s:.3g} s: a cost that both sides pay alike moves a ratio "
                    "toward 1; the lines driver times the work alone",
                )
            )
    return out


def _grading_notes(grading: Grading, floors: Floors | None) -> list[Note]:
    out: list[Note] = []
    if floors is not None:
        out.append(
            Note(
                code=NOTE_FLOOR_SUPPLIED,
                message="the noise floors were supplied by the caller and not measured with twins",
            )
        )
    if grading.provisional():
        out.append(
            Note(
                code=NOTE_FLOOR_PROVISIONAL,
                message="a noise floor was computed from fewer than 8 rounds and is provisional",
            )
        )
    one_sided = grading.one_sided()
    if one_sided:
        out.append(
            Note(
                code=NOTE_FLOOR_ONE_SIDED,
                message=f"{len(one_sided)} comparison{'s' if len(one_sided) != 1 else ''} "
                "used the noise floor of one side only: the rule does not require both "
                "floors, and the missing one adds nothing to the bar",
            )
        )
    tested = _twin_plain(grading.twin_family_size())
    for check in grading.twin_differs():
        # twin_differs gives only sides with a corrected p-value.
        assert check.p_corrected is not None
        out.append(
            Note(
                code=NOTE_TWIN_DIFFERS,
                message=f"{check.side} differs from an identical copy of itself more often "
                f"than chance across its primary cases ({p_equation(check.p_corrected, '.3g')}, "
                f"{tested}): the machine or the order is biasing the run",
            )
        )
    return out


def _twin_plain(family_size: int) -> str:
    """Say how many sides the p-value of the twin note is corrected for."""
    if family_size == 1:
        return "one side tested"
    return f"corrected for testing {family_size} sides at once"


# ---------------------------------------------------------------------------
# The two entry points
# ---------------------------------------------------------------------------


def _given(captures: Iterable[Capture], rule: Rule, floors: Floors | None) -> tuple[Capture, ...]:
    given = tuple(captures)
    if not given:
        raise Refusal("E_USAGE", "there is no capture to analyse")
    if any(not isinstance(c, Capture) for c in given):
        raise Refusal("E_USAGE", "analyse takes captures")
    if not isinstance(rule, Rule):
        raise Refusal("E_USAGE", f"a rule is a Rule, not {type(rule).__name__}")
    if floors is not None and not isinstance(floors, Floors):
        raise Refusal("E_USAGE", f"floors are a Floors, not {type(floors).__name__}")
    return given


def analyse_captures(
    captures: Sequence[Capture],
    *,
    rule: Rule,
    baseline: str | None = None,
    floors: Floors | None = None,
    allow_incomplete: bool = False,
    allow_mixed_machines: bool = False,
    assume_interleaved: bool = False,
) -> Results:
    """Analyse one capture, or pool several, into the results document.

    Raises ``Refusal`` for every refusal of a whole analysis, with exit code 6
    for a capture that cannot be analysed and 2 for a call that is invalid.
    """
    given = _given(captures, rule, floors)
    notes: list[Note] = []
    _raise_first(_identity_refusals(given))
    for capture in given:
        _check_complete(capture, allow_incomplete, notes)
    given = _named_alike(given)
    if len(given) > 1:
        _raise_first(_pool_refusals(given, allow_mixed_machines, notes))
        notes += _pool_merge_notes(given)
    notes += _named_apart_notes(given)
    for capture in given:
        _check_twins(capture)
    prepared: list[_Prepared] = []
    offset = 0
    for capture in given:
        rounds = _check_grid(capture, notes)
        prepared.append(_Prepared(capture=capture, rounds=rounds, offset=offset))
        offset += rounds
    first = given[0]
    roles = _roles(first, baseline)
    notes += _pool_baseline_notes(given, baseline)
    disturbed, discard_sha256 = _disturbed(prepared)
    pool = _pool(prepared, roles, disturbed)
    sides = _analysis_sides(first, roles)
    assert first.lineup is not None
    names = first.lineup.names
    _check_order(pool, sides, names)
    if assume_interleaved and pool.unordered:
        notes.append(
            Note(
                code=NOTE_ASSUME_INTERLEAVED,
                message="the order of the launches was not recorded; the comparisons were "
                "graded as if the order had varied, because interleaving was assumed",
            )
        )
    control, control_notes = _judge_control(given, pool, rule)
    grading = grade(
        pool.grid,
        rule,
        floors=floors,
        control_failed=control.status == "failed",
        assume_interleaved=assume_interleaved,
    )
    notes += control_notes
    notes += _grading_notes(grading, floors)
    notes += _launch_cost_notes(first, pool, first.launch_cost)
    kept = [p.rounds for p in prepared]
    notes += _undecided_notes(given, kept)
    notes += _safe(first.driver_notes, ())
    notes += _safe(partial(pooled_driver_notes, given), ())
    return Results(
        tool=Tool(),
        run=_run_info(given, kept),
        rule=_rule_info(rule, grading.family_size),
        provenance=_provenance(given),
        sides=_results_sides(given, roles),
        plan=_plan(given, kept),
        machine_state=_machine_state(given, grading.busy, discard_sha256, kept),
        cases=first.cases,
        comparisons=tuple(_comparison(g, rule) for g in grading.comparisons),
        same_vs_same=tuple(
            SameVsSame(
                side=row.side,
                case=row.case,
                ratio=row.ratio,
                floor=row.floor,
                p_raw=row.p_raw,
                n=row.n,
                unit=rule.unit,
            )
            for row in grading.same_vs_same
        ),
        twin_checks=tuple(
            TwinCheck(
                side=check.side,
                n_rounds=check.n_rounds,
                n_better=check.n_better,
                n_worse=check.n_worse,
                p_raw=check.p_raw,
                p_corrected=check.p_corrected,
            )
            for check in grading.twin_checks
        ),
        controls=Controls(positive=control),
        launch_cost=first.launch_cost,
        env_pad=_env_pad(given),
        series=_series(pool, names),
        notes=(*_capture_notes(given), *notes),
        energy=_energy(given),
    )


def refused(captures: Sequence[Capture], refusal: Refusal, *, rule: Rule) -> Results:
    """Build the results document of a refused run or analysis.

    It describes the captures as far as they can be described, holds no
    comparison, and lists the refusal. It never raises for a capture a reader
    could load.
    """
    given = tuple(c for c in captures if isinstance(c, Capture))
    chosen = rule if isinstance(rule, Rule) else STRICT
    discard = _safe(
        lambda: combine_hashes(
            [d.sha256 if (d := c.set_aside()) is not None else None for c in given]
        ),
        None,
    )
    entry = _safe(
        lambda: RefusalEntry.of(refusal),
        RefusalEntry(code="E_INTERNAL", scope="experiment", message="the analysis was refused"),
    )
    return Results(
        tool=Tool(),
        run=_safe(
            lambda: _run_info(given),
            RunInfo(id="refused", started_at=None, finished_at=None, captures=()),
        ),
        rule=_rule_info(chosen, 0),
        provenance=_safe(lambda: _provenance(given), _provenance(())),
        sides=_safe(lambda: _results_sides(given, None), ()),
        plan=_safe(lambda: _plan(given, None), _plan((), None)),
        machine_state=_safe(
            lambda: _machine_state(given, False, discard), MachineState(status="unknown")
        ),
        cases=_safe(lambda: given[0].cases if given else (), ()),
        launch_cost=_safe(lambda: given[0].launch_cost if given else None, None),
        env_pad=_safe(lambda: _env_pad(given), EnvPad()),
        refusals=(entry,),
        notes=tuple(_safe(lambda: _capture_notes(given), [])),
        energy=_safe(lambda: _energy(given), None),
    )
