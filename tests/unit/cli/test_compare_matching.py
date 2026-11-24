# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare --matching: text capture files read together in the matching mode, two sides compared.

Every value below is made up.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from pairbench import model
from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_USAGE
from pairbench.results import load_schema

from .conftest import COMMAND_NOTE, refusal_text

Cli = Callable[..., Any]

ROUNDS = 12
MATCHING = ("--matching", "--subject", "new", "--baseline", "old")


def row(side: str, round_: int, case: str, value: str | float, suite: str = "s") -> str:
    return f"{suite}\t{side}\t{round_}\t{case}\t{value}"


def rounds(first: int, last: int, *, step: float = 0.0, suite: str = "s") -> list[str]:
    """Rounds of new and old, each ordered by its own pass-order line, the order turning."""
    lines: list[str] = []
    for r in range(first, last + 1):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        values = {"new": 100 + r + step, "old": 120 + r + step}
        lines += [row(side, r, "c1", values[side], suite) for side in order]
    return lines


def run(*, step: float = 0.0, suite: str = "s") -> list[str]:
    return ["## host", *rounds(1, ROUNDS, step=step, suite=suite)]


def write(folder: Path, name: str, lines: Sequence[str]) -> Path:
    path = folder / name
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def matching_of(document: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = document["matching"]
    return found


def valid(document: dict[str, Any]) -> None:
    """Check a results document against the shipped schema."""
    jsonschema = pytest.importorskip("jsonschema", reason="SKIPPED: needs the jsonschema module")
    jsonschema.validate(document, load_schema("results"))


def comparison_rows(document: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (c["case"], c["subject"], c["baseline"], c["n_rounds"], c["subject_median"], c["verdict"])
        for c in document["comparisons"]
    ]


# ---------------------------------------------------------------------------
# a. The flag, and compare without it
# ---------------------------------------------------------------------------


def test_matching_reads_the_files_in_the_matching_mode(cli: Cli, tmp_path: Path) -> None:
    lines = run()
    lines.insert(3, row("new", 1, "c1", "abc"))
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document) == {
        "runs": 1,
        "malformed_rows": 1,
        "kept_rows": 2 * ROUNDS,
        "left_out_rows": 0,
        "other_side_rows": 0,
        "refusal": None,
    }
    assert comparison_rows(document) == [("c1", "new", "old", ROUNDS, 106.5, "NO VERDICT")]
    assert [c["reasons"] for c in document["comparisons"]] == [["no_floor"]]
    assert document["refusals"] == []
    assert got.err.endswith(COMMAND_NOTE)


def test_without_matching_the_results_hold_no_matching_key(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, "--reader", "text", "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert "matching" not in document
    assert comparison_rows(document) == [("c1", "new", "old", ROUNDS, 106.5, "NO VERDICT")]


def test_subject_without_matching_is_refused(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, "--subject", "new", "--baseline", "old")

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text("E_USAGE: --subject names the compared side of --matching")


# ---------------------------------------------------------------------------
# b. Every file read as one text; the pool checks in their order
# ---------------------------------------------------------------------------


def test_the_files_are_read_as_one_text(cli: Cli, tmp_path: Path) -> None:
    # The second file has no banner: its rows belong to the last run of the first file,
    # under the pass-order line in force there.
    first = write(tmp_path, "a.txt", ["## host", *rounds(1, 6)])
    second = write(tmp_path, "b.txt", [row("old", 7, "c1", 127), row("new", 7, "c1", 107)])

    got = cli("compare", first, second, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["runs"] == 1
    assert matching_of(document)["kept_rows"] == 14
    assert [c["n_rounds"] for c in document["comparisons"]] == [7]
    assert document["run"]["pooled"] is False


def test_a_run_given_twice_is_refused_by_identical_written_rows(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())
    out = tmp_path / "out"

    got = cli("compare", path, path, *MATCHING, "--json", "--out", out)

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_POOL_IDENTICAL_ROWS: the runs 0 and 1 hold the same 24 rows as written"
    )
    detail = {"check": "identical_written_rows", "runs": [0, 1], "rows": 24}
    for document in (json.loads(got.out), json.loads((out / "results.json").read_text())):
        assert document["refusals"] == [
            {
                "code": "E_POOL_IDENTICAL_ROWS",
                "scope": "experiment",
                "message": "the runs 0 and 1 hold the same 24 rows as written",
            }
        ]
        assert matching_of(document) == {
            "runs": 2,
            "malformed_rows": 0,
            "kept_rows": 4 * ROUNDS,
            "left_out_rows": 0,
            "other_side_rows": 0,
            "refusal": detail,
        }
        assert document["comparisons"] == []
        assert [s["name"] for s in document["sides"]] == ["new", "old"]
        assert model.Results.from_json(document).to_json() == document
        valid(document)


def test_identical_runs_are_found_before_a_torn_copy_between_them(cli: Cli, tmp_path: Path) -> None:
    whole = run()
    torn = [*whole[:5], row("new", 2, "c1", 999)]
    path = write(tmp_path, "a.txt", [*whole, *torn, *whole])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert matching_of(json.loads(got.out))["refusal"] == {
        "check": "identical_written_rows",
        "runs": [0, 2],
        "rows": 24,
    }


def test_a_torn_copy_is_refused_by_the_written_stretch(cli: Cli, tmp_path: Path) -> None:
    whole = run()
    # The banner, then the rows of round 1 and the first row of round 2, the last torn.
    torn = [*whole[:5], row("new", 2, "c1", 999)]
    path = write(tmp_path, "a.txt", [*whole, *torn])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_POOL_TRUNCATED_COPY: the rows of run 1 are a stretch of run 0's from its row 0, "
        "its last row torn"
    )
    assert matching_of(json.loads(got.out))["refusal"] == {
        "check": "written_stretch",
        "copy_run": 1,
        "original_run": 0,
        "copy_rows": 3,
        "original_rows": 2 * ROUNDS,
        "start_row": 0,
        "last_row": 2,
        "torn": True,
        "rows_matched": 2,
    }


def test_runs_that_differ_only_in_suite_are_refused_by_the_copy_checks(
    cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", [*run(), *run(suite="t")])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_POOL_IDENTICAL_ROWS: the runs 0 and 1 hold identical rows"
    )
    assert matching_of(json.loads(got.out))["refusal"] == {
        "check": "identical_rows",
        "runs": [0, 1],
    }


def test_runs_of_one_file_that_differ_pool(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", [*run(), "unit=ms", *run(step=0.5)])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["runs"] == 2
    assert matching_of(document)["refusal"] is None
    # A round is a run index and a round label: the two runs give twice the rounds.
    assert [c["n_rounds"] for c in document["comparisons"]] == [2 * ROUNDS]


# ---------------------------------------------------------------------------
# c. Two sides: --subject is the view's first side, --baseline its second
# ---------------------------------------------------------------------------


def test_the_subject_is_compared_against_the_baseline_and_a_third_side_is_left_out(
    cli: Cli, tmp_path: Path
) -> None:
    lines = run()
    lines[1] = "pass_order=new mid old"
    lines.insert(2, row("mid", 1, "c1", 50))
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, "--matching", "--subject", "old", "--baseline", "new", "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert [(s["name"], s["role"]) for s in document["sides"]] == [
        ("old", "subject"),
        ("new", "baseline"),
    ]
    assert comparison_rows(document) == [("c1", "old", "new", ROUNDS, 126.5, "NO VERDICT")]
    assert matching_of(document)["other_side_rows"] == 1


def test_the_later_row_of_a_cell_wins_within_a_run(cli: Cli, tmp_path: Path) -> None:
    lines = run()
    lines.insert(2, row("new", 1, "c1", 500))
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["kept_rows"] == 2 * ROUNDS + 1
    assert comparison_rows(document) == [("c1", "new", "old", ROUNDS, 106.5, "NO VERDICT")]


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (
            ("--baseline", "old"),
            "E_USAGE: --matching compares two sides: name them with --subject and --baseline",
        ),
        (
            ("--subject", "new"),
            "E_USAGE: --matching compares two sides: name them with --subject and --baseline",
        ),
        (
            ("--subject", "new", "--subject", "mid", "--baseline", "old"),
            "E_USAGE: --subject names more than one side: new, mid",
        ),
        (
            ("--subject", "old", "--baseline", "old"),
            "E_USAGE: --subject and --baseline name the same side 'old'",
        ),
    ],
)
def test_matching_needs_two_different_sides(
    names: tuple[str, ...], message: str, cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, "--matching", *names)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text(message)


def test_a_refusal_of_the_analysis_keeps_the_matching_object(cli: Cli, tmp_path: Path) -> None:
    lines = ["## host", "pass_order=new old", row("new", 1, "c1", 110), row("old", 1, "c1", 100)]
    lines += [row("new", 2, "c1", 111), row("old", 2, "c1", 101)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_ORDER_NOT_VARIED: new ran before old in every one of 2 rounds"
    )
    document = json.loads(got.out)
    assert [r["code"] for r in document["refusals"]] == ["E_ORDER_NOT_VARIED"]
    assert matching_of(document) == {
        "runs": 1,
        "malformed_rows": 0,
        "kept_rows": 4,
        "left_out_rows": 0,
        "other_side_rows": 0,
        "refusal": None,
    }


# ---------------------------------------------------------------------------
# d. A view without a round of both sides
# ---------------------------------------------------------------------------

NO_PAIR = (
    "E_GRID: no round of the two-sided view holds both new and old: the view keeps {kept} of "
    "the two sides; {left_out} left out because no pass-order line of their run named both "
    "sides before them"
)


def test_a_view_without_a_pass_order_line_naming_both_sides_is_refused(
    cli: Cli, tmp_path: Path
) -> None:
    lines = ["## host", row("new", 1, "c1", 110), row("old", 1, "c1", 100), "pass_order=new"]
    lines += [row("new", 2, "c1", 111), row("old", 2, "c1", 101), row("mid", 2, "c1", 7)]
    path = write(tmp_path, "a.txt", lines)
    out = tmp_path / "out"

    got = cli("compare", path, *MATCHING, "--out", out)

    assert got.code == EXIT_ANALYSIS
    assert got.out == ""
    assert got.err == COMMAND_NOTE + refusal_text(NO_PAIR.format(kept="0 rows", left_out="4 rows"))
    document = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [r["code"] for r in document["refusals"]] == ["E_GRID"]
    assert matching_of(document) == {
        "runs": 1,
        "malformed_rows": 0,
        "kept_rows": 5,
        "left_out_rows": 4,
        "other_side_rows": 1,
        "refusal": {
            "check": "paired_rounds",
            "view_rows": 0,
            "left_out_rows": 4,
            "other_side_rows": 1,
        },
    }


def test_a_pass_order_line_does_not_count_after_a_banner(cli: Cli, tmp_path: Path) -> None:
    lines = ["## host", "pass_order=old new", row("old", 1, "c1", 100)]
    lines += ["## host", row("new", 1, "c1", 112), row("old", 1, "c1", 102)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING)

    assert got.code == EXIT_ANALYSIS
    assert got.out == ""
    assert got.err == refusal_text(NO_PAIR.format(kept="1 row", left_out="2 rows"))


def test_a_side_no_row_names_gives_an_empty_view(cli: Cli, tmp_path: Path) -> None:
    # No pass-order line names nwe, so the rows of old are left out too.
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, "--matching", "--subject", "nwe", "--baseline", "old")

    assert got.code == EXIT_ANALYSIS
    assert got.err == refusal_text(
        "E_GRID: no round of the two-sided view holds both nwe and old: the view keeps 0 rows "
        "of the two sides; 12 rows left out because no pass-order line of their run named "
        "both sides before them"
    )


def test_sides_that_never_share_a_round_label_within_a_run_are_refused(
    cli: Cli, tmp_path: Path
) -> None:
    lines = ["## host", "pass_order=new old", row("new", 1, "c1", 100), row("old", 2, "c1", 120)]
    lines += ["## host", "pass_order=new old", row("old", 1, "c1", 100)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(NO_PAIR.format(kept="3 rows", left_out="0 rows"))
    assert matching_of(json.loads(got.out))["refusal"] == {
        "check": "paired_rounds",
        "view_rows": 3,
        "left_out_rows": 0,
        "other_side_rows": 0,
    }


def test_there_is_no_default_order_option(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *MATCHING, "--default-order", "new old")

    assert got.code == EXIT_USAGE
    assert got.err == refusal_text(
        "E_USAGE: pairbench compare: unrecognized arguments: --default-order new old"
    )


# ---------------------------------------------------------------------------
# e. Flags of other inputs, and names a capture cannot hold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--lenient",), "E_USAGE: --lenient does not apply to --matching"),
        (
            ("--reader", "jsonl"),
            "E_USAGE: --matching reads with the text reader, not the reader jsonl",
        ),
        (
            ("--side", "x=file:y"),
            "E_USAGE: --matching reads text capture files and takes no --side; "
            "name the compared side with --subject NAME",
        ),
        (("--allow-incomplete",), "E_USAGE: --allow-incomplete does not apply to --matching"),
        (
            ("--allow-mixed-machines",),
            "E_USAGE: --allow-mixed-machines does not apply to --matching",
        ),
        (("--assume-interleaved",), "E_USAGE: --assume-interleaved does not apply to --matching"),
        (("--driver", "gbench"), "E_USAGE: --driver does not apply to --matching"),
        (("--levels", "1,2"), "E_USAGE: --levels does not apply to --matching"),
    ],
)
def test_flags_of_other_inputs_are_refused(
    extra: tuple[str, ...], message: str, cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *MATCHING, *extra)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text(message)


def test_matching_needs_capture_files(cli: Cli) -> None:
    got = cli("compare", *MATCHING)

    assert got.code == EXIT_USAGE
    assert got.err == refusal_text("E_USAGE: --matching needs text capture files")


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (
            ("--subject", "~a", "--baseline", "old"),
            "E_USAGE: --subject: side name '~a' is refused: it must be non-empty and hold no "
            "'~', '=' or space",
        ),
        (
            ("--subject", "new", "--baseline", "x=y"),
            "E_USAGE: --baseline: side name 'x=y' is refused: it must be non-empty and hold no "
            "'~', '=' or space",
        ),
        (
            ("--subject", "..", "--baseline", "old"),
            "E_USAGE: --subject: side name '..' is refused: '.' and '..' name folders, not sides",
        ),
    ],
)
def test_a_name_a_capture_cannot_hold_is_refused(
    names: tuple[str, ...], message: str, cli: Cli, tmp_path: Path
) -> None:
    lines = ["## host", "pass_order=~a old", row("~a", 1, "c1", 110), row("old", 1, "c1", 100)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, "--matching", *names)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text(message)


def test_the_text_reader_may_be_named_and_other_names_in_the_text_are_read(
    cli: Cli, tmp_path: Path
) -> None:
    lines = run()
    lines += [row("x y", 1, "c1", 5), row("~a", 1, "c1", 5), row("", 1, "c1", 5), "sides=new new"]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--reader", "text", "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["other_side_rows"] == 3
    assert comparison_rows(document) == [("c1", "new", "old", ROUNDS, 106.5, "NO VERDICT")]


# ---------------------------------------------------------------------------
# f. What results.json records
# ---------------------------------------------------------------------------


def test_results_json_records_the_matching_mode(cli: Cli, tmp_path: Path) -> None:
    lines = ["## host", row("new", 1, "c1", 110), row("old", 1, "c1", 100), *run()[1:]]
    lines += [row("new", 3, "c1", "-5"), row("mid", 3, "c1", 50)]
    path = write(tmp_path, "a.txt", ["x=1", *lines, "## host"])
    out = tmp_path / "out"

    got = cli("compare", path, *MATCHING, "--out", out)

    assert got.code == EXIT_OK
    document = json.loads((out / "results.json").read_text(encoding="utf-8"))
    expected = {
        "runs": 2,
        "malformed_rows": 1,
        "kept_rows": 2 * ROUNDS + 3,
        "left_out_rows": 2,
        "other_side_rows": 1,
        "refusal": None,
    }
    assert matching_of(document) == expected
    assert list(document)[-1] == "matching"
    assert model.Results.from_json(document).matching == model.MatchingInfo(**expected)
    valid(document)


def test_a_results_document_without_the_mode_has_no_matching_key(
    example_results: dict[str, Any],
) -> None:
    loaded = model.Results.from_json(example_results)

    assert loaded.matching is None
    assert "matching" not in loaded.to_json()
    info = model.MatchingInfo(
        runs=3, malformed_rows=2, kept_rows=7, left_out_rows=1, other_side_rows=0, refusal=None
    )
    again = model.Results.from_json({**loaded.to_json(), "matching": info.to_json()})
    assert again.matching == info


# ---------------------------------------------------------------------------
# The unit and the direction of the view's capture
# ---------------------------------------------------------------------------


def throughput(*metadata: str, first: int = 1, last: int = 8) -> list[str]:
    """A run of a figure where higher is better: new near 101, old near 122, on c1 and c2."""
    lines = ["## host", *metadata]
    for r in range(first, last + 1):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        values = {"new": 100 + r % 3, "old": 121 + r % 3}
        lines += [row(side, r, case, values[side]) for case in ("c1", "c2") for side in order]
    return lines


def units_of(document: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(c["id"], c["unit"], c["better"]) for c in document["cases"]]


def test_the_unit_and_the_direction_come_from_the_files(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", throughput("unit=tok/s", " better = higher "))

    shown = cli("compare", path, *MATCHING)
    got = cli("compare", path, *MATCHING, "--json")

    assert shown.code == EXIT_OK
    table = shown.out.splitlines()[3]
    assert table.split()[:6] == ["c1", "101", "tok/s", "122", "tok/s", "1.21x"]
    assert table.split()[6] == "lower"
    assert " ns " not in shown.out
    assert "faster" not in shown.out
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert units_of(document) == [("c1", "tok/s", "higher"), ("c2", "tok/s", "higher")]
    valid(document)


def test_a_unit_one_run_gives_holds_for_the_view(cli: Cli, tmp_path: Path) -> None:
    lines = [*throughput("unit=tok/s", last=4), *throughput("better=higher", first=5)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["runs"] == 2
    assert units_of(document) == [("c1", "tok/s", "higher"), ("c2", "tok/s", "higher")]


TWO_VALUES = "E_USAGE: the runs that give the view a paired round give {key}= more than one value: "


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (
            [*throughput("unit=ms", last=4), *throughput("unit=s", first=5)],
            TWO_VALUES.format(key="unit") + "ms (run 0), s (run 1)",
        ),
        (
            [*throughput("better=lower", last=4), *throughput("better=higher", first=5)],
            TWO_VALUES.format(key="better") + "higher (run 1), lower (run 0)",
        ),
        (
            [
                *throughput("unit=ms", last=3),
                *throughput("unit=s", first=4, last=6),
                *throughput("unit=ms", first=7),
            ],
            TWO_VALUES.format(key="unit") + "ms (runs 0 and 2), s (run 1)",
        ),
        (
            [*throughput("unit=tok/s", "unit=req/s")],
            TWO_VALUES.format(key="unit") + "req/s (run 0), tok/s (run 0)",
        ),
        ([*throughput("better=more")], "E_USAGE: run 0: better= is lower or higher, not 'more'"),
        ([*throughput(" better = ")], "E_USAGE: run 0: better= is lower or higher, not ''"),
        (
            [*throughput("better=", last=4), *throughput("better=lower", first=5)],
            TWO_VALUES.format(key="better") + "'' (run 0), lower (run 1)",
        ),
        (
            [*throughput("better=Higher", last=4), *throughput("better=Higher", first=5)],
            "E_USAGE: runs 0 and 1: better= is lower or higher, not 'Higher'",
        ),
    ],
    ids=[
        "two-units",
        "two-directions",
        "three-runs",
        "two-units-in-one-run",
        "more",
        "empty",
        "empty-and-lower",
        "Higher",
    ],
)
@pytest.mark.parametrize("flags", [(), ("--unit", "tok/s", "--better", "higher")])
def test_values_that_disagree_or_name_no_direction_are_refused(
    lines: list[str], message: str, flags: tuple[str, ...], cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, *flags, "--json", "--out", tmp_path / "out")

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text(message)
    assert not (tmp_path / "out").exists()


def test_a_unit_line_with_an_empty_value_states_nothing(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", throughput("unit=", " unit = "))

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    assert units_of(json.loads(got.out)) == [("c1", "ns", "lower"), ("c2", "ns", "lower")]


def test_only_the_runs_that_give_the_view_rows_count(cli: Cli, tmp_path: Path) -> None:
    other = ["## host", "unit=ms", "better=more", "pass_order=a b", row("a", 1, "c1", 5)]
    path = write(tmp_path, "a.txt", [*other, *throughput("unit=tok/s", "better=higher")])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["runs"] == 2
    assert units_of(document) == [("c1", "tok/s", "higher"), ("c2", "tok/s", "higher")]


def test_a_run_whose_rows_never_pair_states_nothing(cli: Cli, tmp_path: Path) -> None:
    # Run 0 gives the view one row of new, which no row of old pairs.
    unpaired = ["## host", "unit=ms", "better=lower", "pass_order=new old", row("new", 1, "c1", 5)]
    path = write(tmp_path, "a.txt", [*unpaired, *throughput("unit=tok/s", "better=higher")])

    got = cli("compare", path, *MATCHING, "--json")

    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert matching_of(document)["runs"] == 2
    assert units_of(document) == [("c1", "tok/s", "higher"), ("c2", "tok/s", "higher")]


@pytest.mark.parametrize(
    ("metadata", "flags", "expected"),
    [
        (("unit=tok/s",), ("--unit", "req/s"), ("req/s", "lower")),
        (("better=higher",), ("--better", "lower"), ("ns", "lower")),
        (("better=lower",), ("--better", "higher"), ("ns", "higher")),
        (
            ("unit=tok/s", "better=higher"),
            ("--unit", "req/s", "--better", "lower"),
            ("req/s", "lower"),
        ),
        ((), ("--unit", "tok/s", "--better", "higher"), ("tok/s", "higher")),
    ],
    ids=["unit", "better-lower", "better-higher", "both", "no-lines"],
)
def test_unit_and_better_win_over_lines_that_agree(
    metadata: tuple[str, ...],
    flags: tuple[str, ...],
    expected: tuple[str, str],
    cli: Cli,
    tmp_path: Path,
) -> None:
    lines = [*throughput(*metadata, last=4), *throughput(*metadata, first=5)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, *flags, "--json")

    assert got.code == EXIT_OK
    unit, better = expected
    assert units_of(json.loads(got.out)) == [("c1", unit, better), ("c2", unit, better)]


def test_a_refused_pool_keeps_the_unit_and_the_direction(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", throughput("unit=tok/s", "better=higher"))

    got = cli("compare", path, path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    document = json.loads(got.out)
    assert [r["code"] for r in document["refusals"]] == ["E_POOL_IDENTICAL_ROWS"]
    assert units_of(document) == [("c1", "tok/s", "higher"), ("c2", "tok/s", "higher")]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--unit", "ms"), "E_USAGE: --unit names the unit of --matching"),
        (("--better", "higher"), "E_USAGE: --better names the direction of --matching"),
    ],
)
def test_unit_and_better_without_matching_are_refused(
    extra: tuple[str, ...], message: str, cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *extra)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text(message)


def test_an_empty_unit_is_refused(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *MATCHING, "--unit", " ")

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text("E_USAGE: --unit names a unit: give a text that is not empty")


def _one_pass(order: tuple[str, str], labels: range, values: dict[str, int]) -> list[str]:
    lines = ["pass_order=" + " ".join(order)]
    for r in labels:
        lines += [row(side, r, "c1", values[side] + r) for side in order]
    return lines


@pytest.mark.parametrize(
    ("lines", "said"),
    [
        pytest.param(
            [
                "## host",
                *_one_pass(("new", "old"), range(1, 11), {"new": 110, "old": 100}),
                *_one_pass(("old", "new"), range(1, 11), {"new": 90, "old": 101}),
            ],
            "old ran before new in every one of 10 rounds",
            id="forward-and-reversed-pass-reuse-labels",
        ),
        pytest.param(
            ["## host", *_one_pass(("new", "old"), range(1, 4), {"new": 110, "old": 100})],
            "new ran before old in every one of 3 rounds",
            id="one-pass-order",
        ),
    ],
)
def test_a_view_whose_sides_ran_in_one_order_in_every_round_is_refused(
    lines: list[str], said: str, cli: Cli, tmp_path: Path
) -> None:
    # The later row of a cell wins, so a reversed pass that reuses every round label of a
    # forward pass gives every value of the view, and every round the order old new.
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, *MATCHING, "--out", tmp_path / "o")

    assert got.code == EXIT_ANALYSIS
    assert got.out == ""
    assert got.err == COMMAND_NOTE + refusal_text(f"E_ORDER_NOT_VARIED: {said}")
    document = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert [(r["code"], r["message"]) for r in document["refusals"]] == [
        ("E_ORDER_NOT_VARIED", said)
    ]
    assert matching_of(document)["refusal"] is None


@pytest.mark.parametrize("flags", [("--json",), ("--out", "o")])
def test_a_unit_that_is_not_utf8_text_is_refused_before_anything_is_written(
    flags: tuple[str, ...], cli: Cli, tmp_path: Path
) -> None:
    # A byte that is not UTF-8 in an argument reaches the tool as a lone surrogate.
    path = write(tmp_path, "a.txt", run())
    out = tmp_path / "o"
    given = tuple(str(out) if flag == "o" else flag for flag in flags)

    got = cli("compare", path, *MATCHING, "--unit", "ns\udcff", *given)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text("E_USAGE: --unit names a unit: 'ns\\\\udcff' is not UTF-8 text")
    assert not out.exists()


@pytest.mark.parametrize("direction", ["up", "more", "Higher"])
def test_a_direction_other_than_lower_or_higher_is_refused(
    direction: str, cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *MATCHING, "--better", direction)

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err.startswith(
        "E_USAGE: pairbench compare: argument --better: invalid choice: "
        f"'{direction}' (choose from "
    )
    assert "lower" in got.err.splitlines()[0]
    assert "higher" in got.err.splitlines()[0]


# ---------------------------------------------------------------------------
# A pool refusal comes first; --rule and a repeated --subject
# ---------------------------------------------------------------------------


def test_a_pool_refusal_comes_before_a_view_without_a_paired_round(
    cli: Cli, tmp_path: Path
) -> None:
    lines = ["## host", "pass_order=new", row("new", 1, "c1", 1), row("old", 1, "c1", 2)]
    path = write(tmp_path, "a.txt", lines)

    got = cli("compare", path, path, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_POOL_IDENTICAL_ROWS: the runs 0 and 1 hold the same 2 rows as written"
    )
    document = json.loads(got.out)
    assert [r["code"] for r in document["refusals"]] == ["E_POOL_IDENTICAL_ROWS"]
    assert matching_of(document)["refusal"] == {
        "check": "identical_written_rows",
        "runs": [0, 1],
        "rows": 2,
    }


def test_the_rule_is_looked_up_before_a_pool_refusal(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, path, *MATCHING, "--rule", "nosuch")

    assert got.code == EXIT_USAGE
    assert got.out == ""
    assert got.err == refusal_text("E_USAGE: unknown rule 'nosuch'; known: strict")


def test_a_subject_named_twice_is_one_side(cli: Cli, tmp_path: Path) -> None:
    path = write(tmp_path, "a.txt", run())

    got = cli("compare", path, *MATCHING, "--subject", "new", "--json")

    assert got.code == EXIT_OK
    assert comparison_rows(json.loads(got.out)) == [
        ("c1", "new", "old", ROUNDS, 106.5, "NO VERDICT")
    ]


# ---------------------------------------------------------------------------
# The view has no twins
# ---------------------------------------------------------------------------

NO_TWINS = (
    "pairbench: note: view_without_twins: the case '{case}' has no noise floor: the two-sided "
    "view of new and old has no twins, so the rule strict gives it no verdict; "
    "pairbench.analyse grades the view's capture with noise floors measured elsewhere"
)


@pytest.mark.parametrize(
    ("last", "reason"), [(1, "single_measurement"), (3, "too_few_rounds"), (12, "no_floor")]
)
def test_every_case_carries_the_note_that_the_view_has_no_twins(
    last: int, reason: str, cli: Cli, tmp_path: Path
) -> None:
    path = write(tmp_path, "a.txt", throughput(last=last))

    shown = cli("compare", path, *MATCHING)
    got = cli("compare", path, *MATCHING, "--json")

    notes = [NO_TWINS.format(case=case) for case in ("c1", "c2")]
    assert shown.code == EXIT_OK
    assert shown.err.splitlines() == notes
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert [c["reason"] for c in document["comparisons"]] == [reason, reason]
    assert all("no_floor" in c["reasons"] for c in document["comparisons"])
    assert [
        (n["code"], "pairbench: note: view_without_twins: " + n["message"])
        for n in document["notes"]
    ] == [("view_without_twins", note) for note in notes]
    valid(document)


# ---------------------------------------------------------------------------
# What the shared files of compare --matching do not hold
# ---------------------------------------------------------------------------

# Made-up markers. The machine answers with them, and the files sit in a folder named by them.
MARKER_HOST = "markerhost-m"
MARKER_USER = "markeruser-m"
MARKER_HOME = "/markerhome-m/markeruser-m"
MARKERS = (MARKER_HOST, MARKER_USER, "markerhome-m", "markerfolder-m")


@pytest.mark.parametrize("pooled", ["pools", "refused"])
def test_the_shared_files_of_compare_matching_hold_no_marker_of_the_machine(
    pooled: str, cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import getpass
    import platform
    import socket

    monkeypatch.setattr(socket, "gethostname", lambda: MARKER_HOST)
    monkeypatch.setattr(platform, "node", lambda: MARKER_HOST)
    monkeypatch.setattr(getpass, "getuser", lambda: MARKER_USER)
    for name, value in {"HOME": MARKER_HOME, "USER": MARKER_USER, "HOSTNAME": MARKER_HOST}.items():
        monkeypatch.setenv(name, value)
    folder = tmp_path / "markerfolder-m" / MARKER_USER
    folder.mkdir(parents=True)
    first = write(folder, "a.txt", run())
    # A copy in another suite: the pool checks refuse it, naming the two runs.
    given = [first, write(folder, "b.txt", run(suite="t"))] if pooled == "refused" else [first]
    out = tmp_path / "o"

    got = cli("compare", *given, *MATCHING, "--out", out)

    assert got.code == (EXIT_ANALYSIS if pooled == "refused" else EXIT_OK)
    texts = {
        name: (out / name).read_text(encoding="utf-8") for name in ("results.json", "results.md")
    }
    for name, shared in texts.items():
        for marker in (*MARKERS, str(tmp_path)):
            assert marker not in shared, (name, marker)
    document = json.loads(texts["results.json"])
    assert document["run"]["captures"] != []
    if pooled == "refused":
        assert matching_of(document)["refusal"] is not None


def test_a_copy_of_rows_that_stand_outside_the_input_of_their_banner_is_refused(
    cli: Cli, tmp_path: Path
) -> None:
    # The header file opens run 0 and holds its metadata; the marked file joins run 0, so
    # every row of run 0 stands outside the header. The header's pass order orders round 1
    # old first in this mode; a text capture of the marked file orders it new first, as the
    # copy is written.
    header = write(tmp_path, "a.txt", ["## host", "sides=old new", "pass_order=old new"])
    first_round = [row("old", 1, "c1", 121), row("new", 1, "c1", 101)]
    marked = tmp_path / "b.txt"
    body = ["## host", "sides=new old", *first_round, *rounds(2, ROUNDS)]
    marked.write_bytes(b"\xef\xbb\xbf" + ("\n".join(body) + "\n").encode("utf-8"))
    copy = write(tmp_path, "c.txt", ["## host", *first_round[::-1], *rounds(2, ROUNDS)])

    assert cli("compare", header, marked, copy).code == EXIT_ANALYSIS
    got = cli("compare", header, marked, copy, *MATCHING, "--json")

    assert got.code == EXIT_ANALYSIS
    assert got.err == COMMAND_NOTE + refusal_text(
        "E_POOL_IDENTICAL_ROWS: the runs 0 and 1 hold identical rows"
    )
    document = json.loads(got.out)
    assert [r["code"] for r in document["refusals"]] == ["E_POOL_IDENTICAL_ROWS"]
    assert matching_of(document)["refusal"] == {"check": "identical_rows", "runs": [0, 1]}
    assert matching_of(document)["kept_rows"] == 4 * ROUNDS
