# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The set of text codes is stable, and the changelog names every change to it.

``PINNED_CODES`` is the set of text codes of the release ``PINNED_RELEASE``. A code added
to, removed from or renamed in ``pairbench.errors.CODES`` since then must be named in the
newest release entry of ``docs/changelog.md``. A code is added only in a minor or a major
release, and renamed or removed only in a major release, as the exit-codes page promises.
When a release later than the one that changed the set is entered in the changelog, the pin
moves to the release before it.

The changelog is read by a small strict rule whose pages every CommonMark or GFM renderer
shows alike, so the check needs no renderer:

1. After the front matter, whose lines are ``key: value`` pairs of plain text, and before the
   first line that starts with ``## ``, the page holds only blank lines, one ``# `` title and
   lines of plain prose: letters, digits, spaces, commas and periods, starting with a letter.
2. That first ``## `` line is the newest release heading: ``## `` and a version of three
   numbers of at most six ASCII digits each, with no leading zero, and nothing else.
3. The newest entry runs from that heading to the next line that starts with ``## ``. It
   holds no ``<``, no ``&``, no control character but tab and newline, no footnote ``[^``, no
   table row, no link reference definition ``]:``, no heading of level 1 or 2 and no line of
   ``-`` or ``=`` only, which could make one.
4. A code is named only as the whole content of a code span, `` `E_X` ``, on a plain line of
   that entry: at most three spaces in, after an optional list marker, the line holds outside
   its code spans only ASCII letters, digits, spaces and ``,.;:/-``, holds no address, no
   double backtick and no ``|`` in a span, and no letter or digit touches the span. The line
   starts a block: it follows a blank line or the heading, or opens a list item with ``- ``,
   ``* ``, ``+ ``, ``1. `` or ``1) ``, so no link, image or code span of an earlier line runs
   into it. A plain line holds ASCII only. A code anywhere else is not named.
"""

from __future__ import annotations

import functools
import re
import time
from collections.abc import Iterable
from pathlib import Path

import pytest

import pairbench
from pairbench.errors import CODES

REPO = Path(__file__).resolve().parents[3]
CHANGELOG = "docs/changelog.md"

PINNED_RELEASE = "0.1.1"
PINNED_CODES: frozenset[str] = frozenset(
    {
        "E_USAGE",
        "E_CONFIG",
        "E_SAME_SIDE",
        "E_SIDE_UNIDENTIFIED",
        "E_SIDE_UNRESOLVED",
        "E_ENTRYPOINT_UNREADABLE",
        "E_ENGINE_UNSUPPORTED",
        "E_PROFILER_MISSING",
        "E_PLOT_EXTRA_MISSING",
        "E_TWIN_DRIFT",
        "E_GATE_FAILED",
        "E_GATE_UNAVAILABLE",
        "E_LOCK",
        "E_PIN_UNSUPPORTED",
        "E_CPUS_MIXED_TYPES",
        "E_LAUNCH_FAILED",
        "E_SIDE_CHANGED",
        "E_GPU_NOT_RELEASED",
        "E_TOO_FEW_ROUNDS",
        "E_CASES_DIFFER",
        "E_BUDGET",
        "E_CAPTURE_INCOMPLETE",
        "E_GRID",
        "E_TWIN_ORPHAN",
        "E_ORDER_NOT_VARIED",
        "E_POOL_SAME",
        "E_POOL_IDENTICAL_ROWS",
        "E_POOL_TRUNCATED_COPY",
        "E_POOL_SIDE_DRIFT",
        "E_POOL_CASES",
        "E_POOL_MACHINE",
        "E_POOL_MIXED_PURPOSE",
        "E_FIGURE_MISSING",
        "E_INTERNAL",
        "E_INTERRUPTED",
    }
)

RELEASE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
RELEASE_HEADING = re.compile(r"## " + RELEASE.pattern)

# Every pattern below runs in time linear in the page: no quantifier stands inside another
# where the two can match the same text.
ADDRESS = re.compile(r"(?<![a-zA-Z0-9+.-])[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_FRONT_LINES = re.compile(
    r"(?:(?:[ \t]*|[A-Za-z][A-Za-z0-9_-]*:(?: [A-Za-z0-9 ,.;:'\"()/?!-]*)?)\n)*"
)
_PREAMBLE_LINES = re.compile(
    r"(?:(?:[ \t]*|# [A-Za-z][A-Za-z0-9 ,.]*|[A-Za-z][A-Za-z0-9 ,.]*)(?:\n|\Z))*"
)
_FORBIDDEN = re.compile(r"[<&\x00-\x08\x0b-\x1f\x7f-\x9f]|\[\^|\]:")
_TABLE_ROW = re.compile(r"^[ \t]*\|", re.MULTILINE)
_HEADING_LINE = re.compile(
    r"^[ \t>]*(?:(?:[-*+]|[0-9]{1,9}[.)])[ \t>]+)*(?:#{1,2}(?:[ \t]|$)|-+[ \t]*$|=+[ \t]*$)",
    re.MULTILINE,
)
_PLAIN_LINE = re.compile(
    r" {0,3}(?:(?:[-*+]|[0-9]{1,9}[.)]) )?(?! )(?:[A-Za-z0-9 ,.;:/-]|`[^`|\n]+`)*"
)
_STARTS_BLOCK = re.compile(r" {0,3}(?:[-*+]|1[.)])[ \t]+\S")
_SPAN = re.compile(r"`([^`]+)`")

_ENTRY_RULE = (
    "the newest entry holds no `<`, no `&`, no control character but tab and newline, no "
    "footnote, no table, no link reference definition and no heading of level 1 or 2, so that "
    "every renderer shows it alike; take it out"
)


class Refused(ValueError):
    """A changelog the check does not read: the message says why and what to do."""


def _line_number(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _line_at(text: str, at: int) -> str:
    end = text.find("\n", at)
    return text[at : len(text) if end < 0 else end]


def _front_matter_end(changelog: str) -> int:
    """Where the page goes on after its front matter: 0 when it has none."""
    if not changelog.startswith("---\n"):
        return 0
    end = _FRONT_LINES.match(changelog, 4).end()  # type: ignore[union-attr]
    if changelog.startswith("---\n", end) or changelog[end:] == "---":
        return min(end + 4, len(changelog))
    if end == len(changelog):
        raise Refused(f"{CHANGELOG} opens front matter on line 1 that no `---` line closes")
    raise Refused(
        f"{CHANGELOG} holds {_line_at(changelog, end)[:40]!r} on line "
        f"{_line_number(changelog, end)}, in its front matter: each line of the front matter "
        "is a `key: value` pair of plain text"
    )


def _heading_start(changelog: str, start: int) -> int:
    """Where the first line at or after ``start`` that starts with ``## `` begins, or -1."""
    if changelog.startswith("## ", start):
        return start
    found = changelog.find("\n## ", start)
    return found + 1 if found >= 0 else -1


def _check_preamble(changelog: str, start: int, end: int) -> None:
    stop = _PREAMBLE_LINES.match(changelog, start, end).end()  # type: ignore[union-attr]
    preamble = changelog[start:stop]
    if stop < end or preamble.startswith("# ") + preamble.count("\n# ") > 1:
        at = stop if stop < end else changelog.rfind("\n# ", start, stop) + 1
        raise Refused(
            f"{CHANGELOG} holds {_line_at(changelog, at)[:40]!r} on line "
            f"{_line_number(changelog, at)}, above the newest release heading: above it the "
            "page holds only its front matter, blank lines, one `# ` title and lines of plain "
            "prose, of letters, digits, spaces, commas and periods"
        )


def _check_entry(changelog: str, start: int, end: int) -> None:
    entry = changelog[start:end]
    found: list[tuple[int, str]] = []
    forbidden = _FORBIDDEN.search(entry)
    if forbidden is not None:
        mark = forbidden.group()
        what = {
            "<": "a `<`",
            "&": "a `&`",
            "[^": "a footnote `[^`",
            "]:": "a link reference definition `]:`",
        }.get(mark, f"the control character U+{ord(mark[0]):04X}")
        found.append((forbidden.start(), what))
    for pattern, what in ((_TABLE_ROW, "a table row"), (_HEADING_LINE, "a heading line")):
        line = pattern.search(entry)
        if line is not None:
            found.append((line.start(), what))
    if found:
        at, what = min(found)
        raise Refused(
            f"{CHANGELOG} holds {what} on line {_line_number(changelog, start + at)}, in the "
            f"newest release entry: {_ENTRY_RULE}"
        )


def newest_entry(changelog: str) -> tuple[tuple[int, int, int], str] | None:
    """The version and the text of the newest release entry of a changelog, or ``None`` when
    it has no line that starts with ``## ``. Raises ``Refused`` for a page the rule does not
    read."""
    start = _front_matter_end(changelog)
    heading = _heading_start(changelog, start)
    _check_preamble(changelog, start, len(changelog) if heading < 0 else heading)
    if heading < 0:
        return None
    line = _line_at(changelog, heading)
    found = RELEASE_HEADING.fullmatch(line)
    if found is None:
        raise Refused(
            f"{CHANGELOG} has the release heading {line[:40]!r} on line "
            f"{_line_number(changelog, heading)}: a release heading is `## ` and a version of "
            "three numbers of at most six digits each, with no leading zero and nothing after "
            "it, such as `## 1.2.0`"
        )
    body = min(heading + len(line) + 1, len(changelog))
    end = changelog.find("\n## ", heading + len(line))
    end = len(changelog) if end < 0 else max(end, body)
    _check_entry(changelog, body, end)
    entry = changelog[body:end]
    _named, unreadable = _plain_codes(entry)
    if unreadable is not None:
        at = body + unreadable
        char = next(c for c in _line_at(changelog, at) if not c.isascii())
        raise Refused(
            f"{CHANGELOG} holds the character U+{ord(char):04X} on line "
            f"{_line_number(changelog, at)}, a plain line of the newest release entry: a plain "
            "line holds ASCII only, so that a code on it reads the same in every font"
        )
    major, minor, patch = (int(part) for part in found.groups())
    return (major, minor, patch), entry


@functools.lru_cache(maxsize=4)
def _plain_codes(entry: str) -> tuple[frozenset[str], int | None]:
    """The codes named on the plain lines of an entry, and where a plain line that holds a
    character that is not ASCII starts, or ``None``."""
    named: set[str] = set()
    starts_block = True  # the line after the heading
    at = 0
    for line in entry.split("\n"):
        if "`" in line and _PLAIN_LINE.fullmatch(line) is not None:
            if not line.isascii():
                return frozenset(), at
            if (
                (starts_block or _STARTS_BLOCK.match(line) is not None)
                and "``" not in line
                and ADDRESS.search(line) is None
            ):
                for span in _SPAN.finditer(line):
                    before = line[span.start() - 1 : span.start()]
                    after = line[span.end() : span.end() + 1]
                    if not before.isalnum() and not after.isalnum():
                        named.add(span.group(1))
        starts_block = line.strip(" \t") == ""
        at += len(line) + 1
    return frozenset(named), None


def _names(text: str, code: str) -> bool:
    """Say whether the text of a newest entry names ``code`` in a code span on a plain line."""
    return code in _plain_codes(text)[0]


def _version(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def _shown(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def code_problems(
    codes: Iterable[str], pinned: Iterable[str], pinned_release: str, changelog: str
) -> list[str]:
    """Say what is wrong with a change to the set of text codes; an empty list when nothing is.

    ``codes`` is the set the tool has, ``pinned`` the set of the release ``pinned_release``
    and ``changelog`` the text of ``docs/changelog.md``. Only a code span on a plain line of
    the newest entry names a code; a changelog the rule does not read gives the one problem
    that says why.
    """
    have, had = set(codes), set(pinned)
    added, removed = sorted(have - had), sorted(had - have)
    if not added and not removed:
        return []
    try:
        entry = newest_entry(changelog)
    except Refused as refused:
        return [str(refused)]
    if entry is None:
        return [f"{CHANGELOG} has no release entry, so no change to the text codes is named"]
    version, text = entry
    newest, base = _shown(version), _version(pinned_release)
    where = f"the newest release entry of {CHANGELOG}, {newest},"
    how = "name it in a code span on a plain line of that entry, such as"
    problems: list[str] = []
    if version <= base:
        problems.append(
            f"the text codes changed since {pinned_release}, and {where} is not a later "
            "release: add the entry of the release that changes them"
        )
    for code in added:
        if not _names(text, code):
            problems.append(
                f"the text code {code} was added since {pinned_release}, and {where} does not "
                f'name it: {how} "- Adds `{code}`.", or take it out of pairbench.errors.CODES; '
                f"if it came in a release before {newest}, move PINNED_RELEASE and PINNED_CODES "
                "to that release"
            )
        elif version[2] != 0:
            problems.append(
                f"the text code {code} was added in {newest}, a patch release: a text code "
                "is added only in a minor or a major release"
            )
    for code in removed:
        if not _names(text, code):
            problems.append(
                f"the text code {code} of {pinned_release} was removed or renamed, and {where} "
                f'does not name it: {how} "- Removes `{code}`.", or put it back in '
                "pairbench.errors.CODES"
            )
        elif version[0] == base[0]:
            problems.append(
                f"the text code {code} of {pinned_release} was removed or renamed in {newest}, "
                "which is no major release: a text code is renamed or removed only in a "
                "major release"
            )
    return problems


def _real_changelog() -> str:
    return (REPO / CHANGELOG).read_text(encoding="utf-8")


def test_every_change_to_the_text_codes_is_named_in_the_newest_release_entry() -> None:
    problems = code_problems(CODES, PINNED_CODES, PINNED_RELEASE, _real_changelog())
    assert problems == [], "\n".join(problems)


def test_the_changelog_is_read_by_the_rule_and_its_newest_entry_is_this_release() -> None:
    entry = newest_entry(_real_changelog())
    assert entry is not None
    assert entry[0] == _version(pairbench.__version__)
    assert "pairbench compare --lenient" in entry[1]
    assert "## " not in entry[1]


# The real changelog with one more line in its newest entry, after the line that ends it.
REAL_LAST_LINE = "  is that of 0.1.1.\n"


def _real_with(line: str) -> str:
    text = _real_changelog()
    assert text.count(REAL_LAST_LINE) == 1
    return text.replace(REAL_LAST_LINE, REAL_LAST_LINE + line + "\n")


def test_every_change_against_the_real_changelog_is_caught() -> None:
    newest = pairbench.__version__
    real = _real_changelog()
    added = code_problems(set(PINNED_CODES) | {"E_MADE_UP"}, PINNED_CODES, PINNED_RELEASE, real)
    assert added == [
        f"the text code E_MADE_UP was added since {PINNED_RELEASE}, and the newest release "
        f"entry of docs/changelog.md, {newest}, does not name it: name it in a code span on a "
        'plain line of that entry, such as "- Adds `E_MADE_UP`.", or take it out of '
        f"pairbench.errors.CODES; if it came in a release before {newest}, move "
        "PINNED_RELEASE and PINNED_CODES to that release"
    ]
    removed = code_problems(set(PINNED_CODES) - {"E_LOCK"}, PINNED_CODES, PINNED_RELEASE, real)
    assert removed == [
        f"the text code E_LOCK of {PINNED_RELEASE} was removed or renamed, and the newest "
        f"release entry of docs/changelog.md, {newest}, does not name it: name it in a code "
        'span on a plain line of that entry, such as "- Removes `E_LOCK`.", or put it back in '
        "pairbench.errors.CODES"
    ]
    renamed = (set(PINNED_CODES) - {"E_LOCK"}) | {"E_LOCKED"}
    assert len(code_problems(renamed, PINNED_CODES, PINNED_RELEASE, real)) == 2


def test_a_code_named_as_the_message_says_in_the_real_changelog_is_named() -> None:
    log = _real_with("- Adds `E_MADE_UP`.")
    assert code_problems(set(PINNED_CODES) | {"E_MADE_UP"}, PINNED_CODES, PINNED_RELEASE, log) == []
    log = _real_with("- Removes `E_LOCK`.")
    assert code_problems(set(PINNED_CODES) - {"E_LOCK"}, PINNED_CODES, PINNED_RELEASE, log) == [
        f"the text code E_LOCK of {PINNED_RELEASE} was removed or renamed in "
        f"{pairbench.__version__}, which is no major release: a text code is renamed or "
        "removed only in a major release"
    ]


# The check itself, on made-up sets and changelogs.

MADE_UP_PIN = frozenset({"E_ONE", "E_TWO"})
THREE = frozenset({"E_ONE", "E_TWO", "E_THREE"})


def _log(*entries: tuple[str, str]) -> str:
    parts = ["---", 'description: "made-up"', "---", "", "# Changelog", ""]
    for version, text in entries:
        parts += [f"## {version}", "", text, ""]
    return "\n".join(parts)


def _added(code: str = "E_THREE", newest: str = "4.3.0") -> list[str]:
    return [
        f"the text code {code} was added since 4.2.0, and the newest release entry of "
        f"docs/changelog.md, {newest}, does not name it: name it in a code span on a plain line "
        f'of that entry, such as "- Adds `{code}`.", or take it out of pairbench.errors.CODES; '
        f"if it came in a release before {newest}, move PINNED_RELEASE and PINNED_CODES to "
        "that release"
    ]


def _entry_refused(what: str, line: int) -> list[str]:
    return [
        f"docs/changelog.md holds {what} on line {line}, in the newest release entry: the "
        "newest entry holds no `<`, no `&`, no control character but tab and newline, no "
        "footnote, no table, no link reference definition and no heading of level 1 or 2, so "
        "that every renderer shows it alike; take it out"
    ]


def _check(entry: str) -> list[str]:
    return code_problems(THREE, MADE_UP_PIN, "4.2.0", _log(("4.3.0", entry), ("4.2.0", "x.")))


def test_the_same_set_needs_no_entry() -> None:
    assert code_problems(MADE_UP_PIN, MADE_UP_PIN, "4.2.0", "") == []


def test_a_code_added_and_named_in_a_minor_release_passes() -> None:
    log = _log(("4.3.0", "- adds `E_THREE`."), ("4.2.0", "- adds `E_TWO`."))
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == []


def test_a_code_added_without_being_named_fails_and_says_how_to_name_it() -> None:
    log = _log(("4.3.0", "- something else."), ("4.2.0", "- adds `E_THREE`."))
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == _added()


def test_a_code_whose_name_is_only_part_of_another_is_not_named() -> None:
    assert _check("- adds `E_THREE_MORE`.") == _added()


def test_a_code_added_in_a_patch_release_fails() -> None:
    log = _log(("4.2.1", "- adds `E_THREE`."))
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == [
        "the text code E_THREE was added in 4.2.1, a patch release: a text code is added only "
        "in a minor or a major release"
    ]


def test_a_code_removed_without_being_named_fails_and_says_how_to_name_it() -> None:
    log = _log(("5.0.0", "- something else."))
    assert code_problems({"E_ONE"}, MADE_UP_PIN, "4.2.0", log) == [
        "the text code E_TWO of 4.2.0 was removed or renamed, and the newest release entry of "
        "docs/changelog.md, 5.0.0, does not name it: name it in a code span on a plain line of "
        'that entry, such as "- Removes `E_TWO`.", or put it back in pairbench.errors.CODES'
    ]


def test_a_code_removed_in_a_minor_release_fails_even_when_named() -> None:
    log = _log(("4.3.0", "- removes `E_TWO`."))
    assert code_problems({"E_ONE"}, MADE_UP_PIN, "4.2.0", log) == [
        "the text code E_TWO of 4.2.0 was removed or renamed in 4.3.0, which is no major "
        "release: a text code is renamed or removed only in a major release"
    ]


@pytest.mark.parametrize(
    ("entry", "count"),
    [
        pytest.param("- renames `E_TWO` to `E_SECOND`.", 0, id="both-named"),
        pytest.param("- adds `E_SECOND`.", 1, id="old-name-missing"),
        pytest.param("- drops `E_TWO`.", 1, id="new-name-missing"),
    ],
)
def test_a_rename_in_a_major_release_names_both_names(entry: str, count: int) -> None:
    log = _log(("5.0.0", entry))
    assert len(code_problems({"E_ONE", "E_SECOND"}, MADE_UP_PIN, "4.2.0", log)) == count


def test_a_change_with_no_later_entry_than_the_pin_fails() -> None:
    log = _log(("4.2.0", "- adds `E_THREE`."))
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == [
        "the text codes changed since 4.2.0, and the newest release entry of docs/changelog.md, "
        "4.2.0, is not a later release: add the entry of the release that changes them"
    ]


def test_a_change_with_no_release_entry_at_all_fails() -> None:
    assert code_problems({"E_ONE"}, MADE_UP_PIN, "4.2.0", "# Changelog\n") == [
        "docs/changelog.md has no release entry, so no change to the text codes is named"
    ]


def test_the_newest_entry_ends_at_the_next_heading() -> None:
    log = _log(("4.3.0", "- nothing new."), ("4.2.0", "- adds `E_THREE`."))
    entry = newest_entry(log)
    assert entry is not None
    assert entry[0] == (4, 3, 0)
    assert "E_THREE" not in entry[1]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("- adds `E_THREE`.", id="list-item"),
        pytest.param("* adds `E_THREE`.", id="star-item"),
        pytest.param("+ adds `E_THREE`.", id="plus-item"),
        pytest.param("1. adds `E_THREE`.", id="ordered-item"),
        pytest.param("1) adds `E_THREE`.", id="ordered-item-parenthesis"),
        pytest.param("`E_THREE` is new.", id="paragraph-after-the-heading"),
        pytest.param("x.\n\n2. adds `E_THREE`.", id="ordered-item-after-a-blank-line"),
        pytest.param("- a\n  - adds `E_ONE`, `E_THREE`; x/y: 1.0-2.", id="nested-item"),
        pytest.param("```\nx\n```\n\n- adds `E_THREE`.", id="after-a-fence"),
        pytest.param("- adds `E_THREE`.\n\n  [codes](u) and **E_TWO**", id="links-elsewhere"),
        pytest.param("-     `E_THREE`", id="indented-code-in-an-item"),
        pytest.param('- adds `E_THREE`, read as `pairbench (x)="y"`.', id="other-spans"),
    ],
)
def test_a_code_in_a_code_span_on_a_plain_line_is_named(entry: str) -> None:
    assert _check(entry) == []


@pytest.mark.parametrize(
    "entry",
    [
        # Mentions a renderer does not show.
        pytest.param("- see [the codes](reference/exit-codes.md#E_THREE).", id="link-target"),
        pytest.param("- see ![a figure](figures/E_THREE.svg).", id="image-target"),
        pytest.param('- see [codes](exit-codes.md "E_THREE").', id="link-title"),
        pytest.param("- see ![E_THREE](figures/x.svg).", id="image-description"),
        pytest.param("- see ![`E_THREE`](figures/x.svg).", id="image-description-code"),
        pytest.param("- see [`E_THREE`](u).", id="link-text-code"),
        pytest.param("- see [the [codes]](exit-codes.md#E_THREE).", id="brackets-in-the-text"),
        pytest.param("- see https://example.invalid/codes#E_THREE for more.", id="address"),
        pytest.param("- see https://example.invalid/`E_THREE`.", id="address-before-a-span"),
        # A code span on a line that an earlier line can run into.
        pytest.param('[a](u "\n`E_THREE`\n")', id="title-over-lines"),
        pytest.param("![a\n`E_THREE`\n](u)", id="image-description-over-lines"),
        pytest.param("[a](\n`E_THREE`\n)", id="target-on-the-next-line"),
        pytest.param('[a](u "\n2. `E_THREE`\n")', id="ordered-item-that-continues"),
        pytest.param("see `a\n`E_THREE` `b`", id="code-span-from-the-line-above"),
        pytest.param("- a\n  `E_THREE`", id="continuation-line"),
        pytest.param("```\n`E_THREE`\n```", id="fenced"),
        # A span the line does not make a whole word, or a line that is no plain line.
        pytest.param("- adds x`E_THREE`.", id="letter-before"),
        pytest.param("- adds `E_THREE`s.", id="letter-after"),
        pytest.param("- adds `E_THREE``x`.", id="double-backtick"),
        pytest.param("- adds ``E_THREE``.", id="double-backtick-span"),
        pytest.param("- adds ` E_THREE `.", id="spaces-in-the-span"),
        pytest.param("- adds \\`E_THREE`.", id="escaped-backtick"),
        pytest.param("- adds **`E_THREE`**.", id="emphasis"),
        pytest.param("- adds `E_THREE` and `.", id="odd-backticks"),
        pytest.param("- adds `a|b` and `E_THREE`.", id="pipe-in-a-span"),
        pytest.param("    `E_THREE`", id="four-spaces"),
        pytest.param("> `E_THREE`", id="quote"),
        pytest.param("-\t`E_THREE`", id="tab"),
        pytest.param("- adds E_THREE.", id="no-span"),
        pytest.param("- adds _E_THREE_ and *E_THREE*.", id="emphasis-marks"),
        pytest.param("a | b\n--|--\n`x|![` `E_THREE` `](u)|`", id="table-cell-split"),
    ],
)
def test_a_code_anywhere_else_is_not_named(entry: str) -> None:
    assert _check(entry) == _added()


@pytest.mark.parametrize(
    ("entry", "what", "line"),
    [
        pytest.param("- adds <title>E_THREE</title>.", "<", 9, id="tag"),
        pytest.param("- adds `E_THREE`, read as `<b>`.", "<", 9, id="tag-in-a-span"),
        pytest.param("- adds `E_THREE`.\n<!-- x -->", "<", 10, id="comment"),
        pytest.param("- see <https://example.invalid/>.", "<", 9, id="autolink"),
        pytest.param("- adds `E_THREE`, 1 < 2.", "<", 9, id="less-than"),
        pytest.param("- adds &#69;_THREE.", "&", 9, id="entity"),
        pytest.param("- adds `E_THREE` &lt;x.", "&", 9, id="entity-and-span"),
        pytest.param("- see [^E_THREE].\n\n[^E_THREE]: a note", "[^", 9, id="fn"),
        pytest.param("- adds `E_THREE`.\n\n[c]: u#E_THREE", "]:", 11, id="def"),
        pytest.param("- adds `E_THREE`.\n\n[c\nd]: u", "]:", 12, id="def-label-over-lines"),
        pytest.param("- adds `E_THREE`.\n\n| a |\n|---|\n| x |", "table", 11, id="table"),
        pytest.param("- adds `E_THREE`.\n\n  | a |", "table", 11, id="table-indented"),
        pytest.param("- nothing.\n\n9.9.9\n-----\n\n- adds `E_THREE`.", "heading", 12, id="setext"),
        pytest.param("- nothing.\n9.9.9\n-\n\n- adds `E_THREE`.", "heading", 11, id="setext-dash"),
        pytest.param("- nothing.\n\n9.9.9\n=====", "heading", 12, id="setext-1"),
        pytest.param("- nothing.\n ## 9.9.9\n- adds `E_THREE`.", "heading", 10, id="indented-atx"),
        pytest.param("- nothing.\n##\t9.9.9\n- adds `E_THREE`.", "heading", 10, id="tab-atx"),
        pytest.param("- ## 9.9.9\n- adds `E_THREE`.", "heading", 9, id="atx-in-an-item"),
        pytest.param("> ## 9.9.9\n- adds `E_THREE`.", "heading", 9, id="atx-in-a-quote"),
        pytest.param("# 9.9.9\n- adds `E_THREE`.", "heading", 9, id="atx-level-1"),
        pytest.param("- adds `E_THREE`.\n---", "heading", 10, id="rule-under-a-line"),
        pytest.param("- nothing.\n\0## 4.4.0\n\n- adds `E_THREE`.", "U+0000", 10, id="nul"),
        pytest.param("- adds `E_THREE`.\x1b[8m", "U+001B", 9, id="escape"),
        pytest.param("- adds `E_THREE`.\r\n", "U+000D", 9, id="carriage-return"),
        pytest.param("- adds `E_THREE`.\x7f", "U+007F", 9, id="delete"),
        pytest.param("- adds `E_THREE`.\x85", "U+0085", 9, id="c1"),
    ],
)  # fmt: skip
def test_an_entry_a_renderer_could_show_otherwise_is_refused(
    entry: str, what: str, line: int
) -> None:
    what = {
        "<": "a `<`",
        "&": "a `&`",
        "[^": "a footnote `[^`",
        "]:": "a link reference definition `]:`",
        "table": "a table row",
        "heading": "a heading line",
    }.get(what, f"the control character {what}")
    assert _check(entry) == _entry_refused(what, line)


@pytest.mark.parametrize(
    ("char", "entry"),
    [
        pytest.param("U+0415", "- adds `\u0415_THREE`.", id="cyrillic-letter"),
        pytest.param("U+200B", "- adds `E_\u200bTHREE`.", id="zero-width-space"),
        pytest.param("U+00A0", "- adds `E_THREE`, `\u00a0`.", id="no-break-space"),
        pytest.param("U+FF3F", "x.\n\n`E\uff3fTHREE` is new.", id="fullwidth-low-line"),
    ],
)
def test_a_plain_line_that_holds_more_than_ascii_is_refused(char: str, entry: str) -> None:
    line = 9 + entry.count("\n")
    assert _check(entry) == [
        f"docs/changelog.md holds the character {char} on line {line}, a plain line of the "
        "newest release entry: a plain line holds ASCII only, so that a code on it reads the "
        "same in every font"
    ]


def _heading_refused(line: str, number: int = 7) -> list[str]:
    return [
        f"docs/changelog.md has the release heading {line!r} on line {number}: a release "
        "heading is `## ` and a version of three numbers of at most six digits each, with no "
        "leading zero and nothing after it, such as `## 1.2.0`"
    ]


@pytest.mark.parametrize(
    "heading",
    [
        pytest.param("## *9.0.0*", id="emphasis"),
        pytest.param("## **9.0.0**", id="strong"),
        pytest.param("## `9.0.0`", id="code"),
        pytest.param("## 9.0.0 #", id="closing-mark"),
        pytest.param("## [9.0.0](x)", id="link"),
        pytest.param("## 9&#46;0.0", id="entity"),
        pytest.param("##  9.0.0", id="two-spaces"),
        pytest.param("## 9.0.0 ", id="space-after"),
        pytest.param("## \uff19.0.0", id="fullwidth-digit"),
        pytest.param("## \u0669.0.0", id="arabic-indic-digit"),
        pytest.param("## 09.0.0", id="leading-zero"),
        pytest.param("## 1.0.1234567", id="seven-digits"),
        pytest.param("## 1.0." + "1" * 4301, id="4301-digits"),
        pytest.param("## 9.0", id="two-numbers"),
        pytest.param("## Unreleased", id="words"),
    ],
)
def test_a_release_heading_that_is_not_exactly_a_version_is_refused(heading: str) -> None:
    log = _log(("4.3.0", "- adds `E_THREE`.")).replace("## 4.3.0", heading)
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == _heading_refused(heading[:40])


def _preamble_refused(line: str, number: int) -> list[str]:
    return [
        f"docs/changelog.md holds {line!r} on line {number}, above the newest release heading: "
        "above it the page holds only its front matter, blank lines, one `# ` title and lines "
        "of plain prose, of letters, digits, spaces, commas and periods"
    ]


@pytest.mark.parametrize(
    ("above", "line", "number"),
    [
        pytest.param("```\n## 9.0.0\n```", "```", 6, id="fence"),
        pytest.param("    x", "    x", 6, id="indented"),
        pytest.param("9.0.0\n-----", "9.0.0", 6, id="setext"),
        pytest.param("x\n===", "===", 7, id="setext-1"),
        pytest.param("<div hidden>", "<div hidden>", 6, id="html"),
        pytest.param("<h2 hidden>9.9.9</h2>", "<h2 hidden>9.9.9</h2>", 6, id="hidden-heading"),
        pytest.param("[x]: /u", "[x]: /u", 6, id="definition"),
        pytest.param("| a |", "| a |", 6, id="table"),
        pytest.param("a &amp; b", "a &amp; b", 6, id="entity"),
        pytest.param("a \\", "a \\", 6, id="backslash"),
        pytest.param("##\t9.0.0", "##\t9.0.0", 6, id="tab-heading"),
        pytest.param(" ## 9.0.0", " ## 9.0.0", 6, id="indented-heading"),
        pytest.param("### x", "### x", 6, id="level-3"),
        pytest.param("- x", "- x", 6, id="list"),
        pytest.param("> x", "> x", 6, id="quote"),
        pytest.param("\ufeffx", "\ufeffx", 6, id="byte-order-mark"),
        pytest.param("x\r", "x\r", 6, id="carriage-return"),
        pytest.param("# Changelog", "# Changelog", 6, id="second-title"),
    ],
)
def test_anything_but_a_title_and_plain_prose_above_the_newest_heading_is_refused(
    above: str, line: str, number: int
) -> None:
    log = _log(("4.3.0", "- adds `E_THREE`."))
    log = log.replace("# Changelog\n", "# Changelog\n" + above + "\n\n")
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == _preamble_refused(line, number)


def test_the_first_line_that_starts_with_two_marks_is_the_newest_heading() -> None:
    log = _log(("4.3.0", "- adds `E_THREE`.")).replace("# Changelog\n", "## 9.0.0 x\n")
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == _heading_refused("## 9.0.0 x", 5)


def test_a_front_matter_line_that_is_no_key_and_value_is_refused() -> None:
    log = _log(("4.3.0", "- adds `E_THREE`.")).replace("description", "9.9.9\ndescription")
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", log) == [
        "docs/changelog.md holds '9.9.9' on line 2, in its front matter: each line of the "
        "front matter is a `key: value` pair of plain text"
    ]
    unclosed = "---\ndescription: x\n\n## 4.3.0\n\n- adds `E_THREE`.\n"
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", unclosed) == [
        "docs/changelog.md holds '## 4.3.0' on line 4, in its front matter: each line of the "
        "front matter is a `key: value` pair of plain text"
    ]
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", "---\ndescription: x\n") == [
        "docs/changelog.md opens front matter on line 1 that no `---` line closes"
    ]


def test_a_page_with_no_front_matter_or_title_is_read() -> None:
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", "## 4.3.0\n- adds `E_THREE`.") == []
    fenced = _log(("4.3.0", "```\n## 4.4.0\n```\n\n- adds `E_THREE`."))
    assert code_problems(THREE, MADE_UP_PIN, "4.2.0", fenced) == _added()


# Pages of about a megabyte, each made to slow a pattern down. The rule reads each in a small
# part of a second.
MEGABYTE = 1_000_000
HEAD = '---\ndescription: "x"\n---\n\n# Changelog\n\n## 9.0.0\n\n'
LISTS = "".join("  " * depth + "- a\n" for depth in range(31))


@pytest.mark.parametrize(
    "page",
    [
        pytest.param("## a" + " " * MEGABYTE + "b", id="heading-spaces"),
        pytest.param(HEAD + "### a" + " " * MEGABYTE + "b", id="level-3-spaces"),
        pytest.param(HEAD + "a." * (MEGABYTE // 2), id="address-dots"),
        pytest.param(HEAD + "a:" * (MEGABYTE // 2), id="address-scheme"),
        pytest.param(HEAD + "`a` a://" * (MEGABYTE // 8), id="address-on-a-plain-line"),
        pytest.param(HEAD + "`a` " + "a." * (MEGABYTE // 2) + "x", id="address-run"),
        pytest.param(HEAD + "[a](b (" * (MEGABYTE // 7), id="title-parentheses"),
        pytest.param(HEAD + "[a](b '" + "x" * MEGABYTE, id="title-quote"),
        pytest.param(HEAD + "[a](b (x" * (MEGABYTE // 8), id="title-parentheses-text"),
        pytest.param(HEAD + "![a](b (" * (MEGABYTE // 8), id="image-titles"),
        pytest.param(HEAD + "[a]: b\n" * (MEGABYTE // 7), id="definitions"),
        pytest.param(HEAD + "[a]: b 'x\n" * (MEGABYTE // 10), id="definition-titles"),
        pytest.param(HEAD + "[a]: b (" + "x" * MEGABYTE, id="definition-title-open"),
        pytest.param(HEAD + "[a][b" * (MEGABYTE // 5), id="full-references"),
        pytest.param(HEAD + "[a](<" * (MEGABYTE // 5), id="angle-targets"),
        pytest.param(HEAD + "[a](b" + "c" * MEGABYTE, id="open-target"),
        pytest.param(HEAD + "[a](b" * (MEGABYTE // 5), id="open-targets"),
        pytest.param(HEAD + "E_THREEX " * (MEGABYTE // 9), id="near-names"),
        pytest.param(HEAD + "&amp;" * (MEGABYTE // 5), id="entities"),
        pytest.param(HEAD + "<a:" * (MEGABYTE // 3), id="open-autolinks"),
        pytest.param(HEAD + "- a\n" * (MEGABYTE // 4), id="list-items"),
        pytest.param(HEAD + "a\n-\n" * (MEGABYTE // 4), id="setext-lines"),
        pytest.param(HEAD + LISTS + " " * MEGABYTE + "x", id="lists"),
        pytest.param("## 1.0." + "1" * (MEGABYTE // 2) + "\n\nE_THREE\n", id="version-digits"),
        pytest.param(HEAD + "[a]: " + "b" * MEGABYTE, id="definition-target"),
        pytest.param(HEAD + "[a\n" * (MEGABYTE // 3), id="definition-labels"),
        pytest.param(HEAD + ("[" + "a" * 998 + "]") * (MEGABYTE // 1000), id="labels"),
        pytest.param(HEAD + "[a][" * (MEGABYTE // 4), id="references"),
        pytest.param(HEAD + "*a" * (MEGABYTE // 2), id="emphasis"),
        pytest.param(HEAD + "a_" * (MEGABYTE // 2), id="underscores"),
        pytest.param(HEAD + "`a" * (MEGABYTE // 2), id="backticks"),
        pytest.param(HEAD + "`" + "a" * MEGABYTE, id="open-span"),
        pytest.param(HEAD + "`a` " * (MEGABYTE // 4) + "!", id="spans-then-a-mark"),
        pytest.param(HEAD + "- `E_THREE` " * (MEGABYTE // 12), id="one-long-plain-line"),
        pytest.param(HEAD + "- `E_THREE`\n" * (MEGABYTE // 12), id="plain-lines"),
        pytest.param(HEAD + "`a`\n" * (MEGABYTE // 4), id="short-span-lines"),
        pytest.param(HEAD + "\n" * MEGABYTE, id="blank-lines"),
        pytest.param(HEAD + "a\n" * (MEGABYTE // 2), id="short-lines"),
        pytest.param(HEAD + "```\n" + "a\n" * (MEGABYTE // 2), id="fence"),
        pytest.param(HEAD + "> a\n" + "b\n" * (MEGABYTE // 2), id="lazy-quote"),
        pytest.param(HEAD + "- " * (MEGABYTE // 2) + "x", id="markers"),
        pytest.param(HEAD + "1. " * (MEGABYTE // 3) + "x", id="ordered-markers"),
        pytest.param(HEAD + "-" * MEGABYTE + "x", id="dashes"),
        pytest.param(HEAD + "> - " * (MEGABYTE // 4) + "x", id="quote-markers"),
        pytest.param(HEAD + " " * MEGABYTE + "|", id="spaces-then-a-pipe"),
        pytest.param(HEAD + "- " * (MEGABYTE // 2), id="markers-to-the-end"),
        pytest.param("## 1.0.0\n" * (MEGABYTE // 9), id="headings"),
        pytest.param("a\n" * (MEGABYTE // 2) + "## 1.0.0", id="prose"),
        pytest.param("---\n" + "a: b\n" * (MEGABYTE // 5), id="front-matter-open"),
        pytest.param("# " + "a " * (MEGABYTE // 2) + "!", id="title"),
        pytest.param(HEAD + "<1" * (MEGABYTE // 2), id="less-thans"),
        pytest.param(HEAD + "[" * (MEGABYTE // 2) + "]" * (MEGABYTE // 2), id="brackets"),
        pytest.param(HEAD + "![" * (MEGABYTE // 4) + "](" * (MEGABYTE // 4), id="images"),
    ],
)  # fmt: skip
def test_a_page_of_a_megabyte_is_read_in_time(page: str) -> None:
    started = time.perf_counter()
    code_problems(THREE, MADE_UP_PIN, "4.2.0", page)
    assert time.perf_counter() - started < 1.0
