# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say what the matching mode and its command line do, and list what a read holds.

The text-format page and the command reference say that compare --matching refuses a view whose
two sides ran in one order in every paired round, and that ``matching.refusal`` then stays null.
The text-format page says which order a round of the view takes and that the pool checks
compare kept rows without the values that are not finite too; the results-schema page says
that a refusal of the analysis leaves ``matching.refusal`` null; the exit-codes page says what a
lone-surrogate refusal of what a driver read shows. The field lists of a run of a
read on the text-format and the Python API pages name every field the record has. The
changelog names the text codes whose refusals change and the exact encoding of a capture kept in
memory, says what a lone-surrogate refusal of what a driver read shows, when ``matching.refusal`` is
null and which copies with a value that is not finite the pool checks refuse; so does the
text-format page for those copies, and the results schema says when ``matching.refusal`` is
null.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from pairbench.capture.matching import MatchingRun

TEXT_FORMAT = "docs/reference/text-format.md"
EXIT_CODES = "docs/reference/exit-codes.md"
RESULTS_SCHEMA = "docs/reference/results-schema.md"
COMMANDS = "docs/reference/commands.md"
PYTHON_API = "docs/reference/python-api.md"
CHANGELOG = "docs/changelog.md"

ROUND_ORDER = (
    "The order of a round is that of the rows that give its cells. A round whose cells come "
    "from rows of both orders, as when a reversed pass stops inside a round or gives only some "
    "of its cells, has no recorded order"
)
TEXT_FORMAT_ORDER = (
    "The analysis refuses a view whose two sides ran in the same order in every paired round "
    "with `E_ORDER_NOT_VARIED` and exit code 6"
)
COMMANDS_ORDER = (
    "view whose two sides ran in one order in every paired round is refused by the analysis "
    "with `E_ORDER_NOT_VARIED`, exit code 6 too, and, as for every refusal of the analysis, "
    "`matching.refusal` stays `null`."
)
POOL_NOT_FINITE = (
    "Then the rows of the pair are compared again with every row whose value is not finite left "
    "out: in the order of the text, in the order they ran by this mode's lines and by its lines "
    "without a tab, and in the order a text capture holds the rest, once as the strict text "
    "reader holds them"
)
POOL_EXCEPTIONS = (
    "So a copy that is refused when its runs are read as text captures is refused here too, with "
    "three exceptions. A copy that text captures find only with the rows whose value is zero or "
    "less, `0` and `0.0` say, as rows or by the sides and positions they give, pools"
)
POOL_PARTS = (
    "and a file that begins with a byte-order mark and a banner: this mode reads that line as a "
    "malformed row (reading rule 9), so the file joins the run before it, and a copy saved with a "
    "mark is refused as a part of that run."
)
POOL_ONE_PART = (
    "Where every kept row of a run stands in one part of it that text captures read as a run of "
    "its own (below), the lines are those of that part instead"
)
JSON_PRINTED = (
    "standard output can write the surrogate: where Python writes it with the error handler "
    "`surrogateescape`, as it does under a C, POSIX or C.UTF-8 locale and in its UTF-8 mode"
)
CHANGELOG_PARTS = (
    "Then the parts of one run that text captures read as runs of their own are compared in the "
    "same orders, as a first input without a banner and the input after it, or a file that "
    "begins with a byte-order mark and a banner, which joins the run before it in this mode"
)
SCHEMA_REFUSAL = (
    "A refusal of the analysis of the view, such as `E_ORDER_NOT_VARIED`, is listed under "
    "`refusals` only, and `refusal` stays `null`."
)
LAUNCH_FAILED_CAUSE = (
    "The message names the side and shows the text as the results show a case, its secret "
    "forms hidden and the folders of a path cut away, escaped, at most 40 characters on each "
    "side of the surrogate, or no text where the cut leaves the surrogate out. It names no key "
    "of the tool's output, since a key may hold a path or a "
    "secret."
)
CHANGED_CODES = (
    "- `E_USAGE`, `E_LAUNCH_FAILED`, `E_SIDE_UNIDENTIFIED`, `E_POOL_SAME`, `E_SIDE_CHANGED`, "
    "`E_POOL_SIDE_DRIFT`, `E_CAPTURE_INCOMPLETE`. - `E_POOL_IDENTICAL_ROWS`, "
    "`E_POOL_TRUNCATED_COPY`, refusals of runs of one text file that are copies, and of the "
    "matching mode. - `E_GRID`, `E_ORDER_NOT_VARIED`, refusals of the matching mode."
)
KEPT_IN_MEMORY = (
    'each record on a line of its own as `json.dumps(record, separators=(",", ":"))` writes it'
)
CHANGELOG_REFUSAL = (
    "`refusal`, the detail of a refusal of that mode with its `check`, or `null` when that mode "
    "did not refuse: a refusal of the analysis of the view, such as `E_ORDER_NOT_VARIED`, is "
    "listed under `refusals` only."
)
SCHEMA_DESCRIPTION_REFUSAL = (
    "or null when the matching mode did not refuse: a refusal of the analysis of the view, such "
    "as E_ORDER_NOT_VARIED, is listed under refusals only."
)
CHANGELOG_NOT_FINITE = (
    "so a copy that holds a `nan` or `inf` row more, wherever it sits, or such a row in place of "
    "the first or last row a text capture holds, is refused too; one that holds such a row in "
    "place of a row in between pools, as it does when its runs are read as text captures."
)
TEXT_FORMAT_NOT_FINITE = (
    "a copy that differs from its original only by a `nan` or `inf` row more, wherever it sits, "
    "or by such a row in place of the first or last row a text capture holds, is refused as it is "
    "when the runs are read as text captures. A copy that holds such a row in place of a row in "
    "between pools, as it does when the runs are read as text captures."
)
DRIVER_SURROGATE = (
    "The message names the side and shows the text as the results show a case, its secret "
    "forms hidden and its paths cut, escaped, at most 40 characters on each side of the "
    "surrogate, or no text where the cut leaves the surrogate out, and names no key of the "
    "tool's output."
)


def page(repo_root: Path, name: str) -> str:
    return " ".join((repo_root / name).read_text(encoding="utf-8").split())


def newest_entry(repo_root: Path) -> str:
    text = page(repo_root, CHANGELOG)
    start = text.index("## ")
    return text[start : text.index(" ## ", start + 3)]


@pytest.mark.parametrize(
    ("name", "sentence"),
    [
        pytest.param(TEXT_FORMAT, ROUND_ORDER, id="round-order"),
        pytest.param(TEXT_FORMAT, TEXT_FORMAT_ORDER, id="text-format-order"),
        pytest.param(COMMANDS, COMMANDS_ORDER, id="commands-order"),
        pytest.param(TEXT_FORMAT, POOL_NOT_FINITE, id="pool-not-finite"),
        pytest.param(TEXT_FORMAT, POOL_EXCEPTIONS, id="pool-exceptions"),
        pytest.param(TEXT_FORMAT, POOL_PARTS, id="pool-parts"),
        pytest.param(TEXT_FORMAT, POOL_ONE_PART, id="pool-one-part"),
        pytest.param(CHANGELOG, CHANGELOG_PARTS, id="changelog-parts"),
        pytest.param(EXIT_CODES, JSON_PRINTED, id="json-printed"),
        pytest.param(RESULTS_SCHEMA, SCHEMA_REFUSAL, id="schema-refusal"),
        pytest.param(EXIT_CODES, LAUNCH_FAILED_CAUSE, id="launch-failed-cause"),
        pytest.param(TEXT_FORMAT, TEXT_FORMAT_NOT_FINITE, id="text-format-not-finite"),
    ],
)
def test_the_pages_say_what_the_view_and_compare_matching_do(
    repo_root: Path, name: str, sentence: str
) -> None:
    assert sentence in page(repo_root, name)


@pytest.mark.parametrize(
    "sentence",
    [
        pytest.param(CHANGED_CODES, id="changed-codes"),
        pytest.param(KEPT_IN_MEMORY, id="kept-in-memory"),
        pytest.param(DRIVER_SURROGATE, id="driver-surrogate"),
        pytest.param(CHANGELOG_REFUSAL, id="matching-refusal"),
        pytest.param(CHANGELOG_NOT_FINITE, id="pool-not-finite"),
    ],
)
def test_the_newest_changelog_entry_says_it(repo_root: Path, sentence: str) -> None:
    assert sentence in newest_entry(repo_root)


def test_the_results_schema_says_when_the_matching_refusal_is_null(repo_root: Path) -> None:
    schema = json.loads(
        (repo_root / "src/pairbench/results/schema/results.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert SCHEMA_DESCRIPTION_REFUSAL in schema["$defs"]["MatchingInfo"]["description"]


def _listed(text: str, start: str, end: str) -> set[str]:
    at = text.index(start)
    return set(re.findall(r"`([a-z_]+)`", text[at : text.index(end, at)]))


@pytest.mark.parametrize(
    ("name", "start", "end"),
    [
        pytest.param(
            TEXT_FORMAT, "| `runs` | one `MatchingRun` per run", "| `run_count`", id="text-format"
        ),
        pytest.param(PYTHON_API, "- `runs`: one `MatchingRun` per run", ";", id="python-api"),
    ],
)
def test_each_list_of_the_fields_of_a_run_names_every_field(
    repo_root: Path, name: str, start: str, end: str
) -> None:
    fields = {f.name for f in dataclasses.fields(MatchingRun)}

    assert fields <= _listed(page(repo_root, name), start, end)
