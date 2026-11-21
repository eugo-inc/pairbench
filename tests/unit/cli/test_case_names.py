# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two case ids that read alike once their paths are cut, through the command line.

The workload prints its own values (the ``lines`` driver): two cases whose ids
hold an absolute path that runs on over a word that tells them apart. The run
gives each the cut id plus a mark, ' +' and eight hex digits made with the
run's own random key, and pairs each with itself on both sides; no word the
paths run over, no key and no hash of an id is in what the run prints or
shares. Pooled captures show the first capture's marks. Ids of one launch that
differ only in a folder or only in a hidden secret are refused; pooled
captures whose ids differ only so are read as one case, with a note. The key
is made up: each test hands the run the key it draws. Every folder, word and
key here is made up.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_FIGURE_MISSING, EXIT_OK, EXIT_USAGE
from pairbench.mcp.server import ToolServer

from .conftest import refusal_text

Cli = Callable[..., Any]

FAST = "run /made/up/a.py Zqfast data/x"
SLOW = "run /made/up/a.py Zqslow data/x"
# The same two ids as a run in another folder gives them.
MOVED_FAST = "run /other/place/a.py Zqfast data/x"
MOVED_SLOW = "run /other/place/a.py Zqslow data/x"
SHOWN = "run x"
# Two made-up keys, and the names each gives the two ids.
KEY = bytes(range(32))
KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
OTHER_KEY = bytes(range(32, 64))
OTHER_KEY_HEX = "202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f"
FAST_NAME = "run x +9337c10f"
SLOW_NAME = "run x +69c21f80"
FAST_OTHER = "run x +ac15bd41"
SLOW_OTHER = "run x +b82ae192"
HIDDEN_WORDS = ("Zqfast", "Zqslow", "made/up", "other/place", "Zqa", "Zqb")
QUICK = ("--gates", "off", "--rounds", "8", "--same-vs-same", "off", "--positive-control", "off")
SIDES = ("--side", "new=cmd:{workload}", "--side", "old=cmd:env {workload}", "--baseline", "old")
RUN = ("--driver", "lines", "--explain", "off", "--plots", "off", "--out", "run")
FILES = ("results.json", "results.md", "report.html", "capture.jsonl", "plan.tsv")
# The files a run shares.
SHARED = ("results.json", "results.md", "report.html", "plan.tsv")
HEX64 = re.compile(r"[0-9a-f]{64}")
RUN_ON_ADVICE = (
    "give them names that differ outside their paths, absolute or climbing with '..', and "
    "outside their secrets; a path runs on over the words after it that start with a letter, a "
    "digit or '_', up to the last that holds a '/', and a quote ends it"
)
SHOWN_ALIKE = (
    "two different cases have the name {shown!r} once absolute paths and paths that climb "
    "with '..' are cut and secrets hidden, as the results show it"
)
MARK_HINT = (
    "the mark ' +' and eight hex digits at the end of a name is made with each run's own key, "
    "so a name from another run's results matches no case here: give the name without its mark"
)
FOLDERS_WHY = (
    "from ids that differ only in words that hold a '/' or in the folders of a path written with "
    "'%2F', which pairbench reads as folders; if those folders are different inputs, keep the "
    "captures apart"
)
SECRETS_WHY = (
    "from ids that differ only in a hidden secret; if those secrets name different inputs, keep "
    "the captures apart"
)


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Hand each run the next made-up key of the list; the list starts with KEY."""
    given: list[bytes] = [KEY]
    drawn: Iterator[bytes] = iter(given)

    def token_bytes(count: int) -> bytes:
        assert count == len(KEY)
        return next(drawn)

    monkeypatch.setattr("pairbench.runner.secrets.token_bytes", token_bytes)
    return given


def _lines(path: Path, cases: dict[str, float]) -> Path:
    path.write_text(
        "".join(
            "::pairbench:: " + json.dumps({"case": case, "value": value}) + "\n"
            for case, value in cases.items()
        ),
        encoding="utf-8",
    )
    return path


def _hides_the_words(text: str) -> bool:
    return not any(word in text for word in HIDDEN_WORDS)


def _results(folder: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return document


def _medians(results: dict[str, Any], *names: str) -> dict[str, tuple[float, float]]:
    return {
        c["case"]: (c["subject_median"], c["baseline_median"])
        for c in results["comparisons"]
        if c["case"] in names
    }


def _records(folder: Path, kind: str) -> list[dict[str, Any]]:
    lines = (folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()
    return [record for record in map(json.loads, lines) if record["t"] == kind]


def _run(cli: Cli, out: str, *argv: str) -> Any:
    done = cli("run", *SIDES, *QUICK, *RUN[:-1], out, "--", *argv)
    assert done.code == EXIT_OK, done.err
    return done


def test_a_run_marks_two_ids_shown_alike_and_shares_no_word_key_or_hash_of_them(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    lines = _lines(tmp_path / "lines.txt", {FAST: 1.0, SLOW: 2.0})
    monkeypatch.chdir(tmp_path)

    result = cli("run", *SIDES, *QUICK, *RUN, "--", "cat", str(lines))

    assert result.code == EXIT_OK, result.err
    assert _hides_the_words(result.out + result.err), result.err
    run = tmp_path / "run"
    for name in FILES:
        assert _hides_the_words((run / name).read_text(encoding="utf-8")), name
    # Each name holds the values of one id on both sides.
    assert _medians(_results(run), FAST_NAME, SLOW_NAME) == {
        FAST_NAME: (1.0, 1.0),
        SLOW_NAME: (2.0, 2.0),
    }
    for name in ("results.md", "report.html"):
        text = (run / name).read_text(encoding="utf-8")
        assert FAST_NAME in text and SLOW_NAME in text, name
    # The private capture keeps the key once and the hashes of each id; no shared file holds
    # any of them.
    assert _records(run, "case_key") == [{"t": "case_key", "key": KEY_HEX}]
    kept = {
        value
        for record in _records(run, "case_names")
        for entry in record["names"]
        for value in entry.values()
        if HEX64.fullmatch(value)
    }
    assert len(kept) == 4
    for name in SHARED:
        text = (run / name).read_text(encoding="utf-8")
        assert KEY_HEX not in text and not any(value in text for value in kept), name
        assert "tell_sha256" not in text and "case_key" not in text, name


def _first_then(tmp_path: Path, first: dict[str, float], later: dict[str, float]) -> str:
    """A shell text that prints ``first`` in the first launch of each side, then ``later``.

    A side's launches are told apart by ``ZQ_SIDE``, which only the old side sets.
    """
    head = _lines(tmp_path / "first.txt", first)
    rest = _lines(tmp_path / "later.txt", later)
    seen = shlex.quote(str(tmp_path / "seen"))
    return (
        f'if [ -e {seen}."$ZQ_SIDE" ]; then cat {shlex.quote(str(rest))}; '
        f'else : > {seen}."$ZQ_SIDE"; cat {shlex.quote(str(head))}; fi'
    )


TWO_SIDES = (
    "--side",
    "new=cmd:{workload}",
    "--side",
    "old=cmd:env ZQ_SIDE=old {workload}",
    "--baseline",
    "old",
)


def test_a_later_launch_that_gives_another_id_gives_it_its_own_name(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    script = _first_then(tmp_path, {FAST: 1.0}, {FAST: 1.0, SLOW: 2.0})
    monkeypatch.chdir(tmp_path)

    result = cli("run", *TWO_SIDES, *QUICK, *RUN, "--case", SHOWN, "--", "sh", "-c", script)

    assert result.code == EXIT_OK, result.err
    assert _hides_the_words(result.out + result.err)
    results = _results(tmp_path / "run")
    assert SHOWN not in {c["case"] for c in results["comparisons"]}
    assert _medians(results, FAST_NAME, SLOW_NAME) == {
        FAST_NAME: (1.0, 1.0),
        SLOW_NAME: (2.0, 2.0),
    }
    named = {e["name"] for r in _records(tmp_path / "run", "case_names") for e in r["names"]}
    assert named == {FAST_NAME, SLOW_NAME}


def test_sides_whose_names_differ_only_in_the_mark_are_refused_with_a_hint(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    # The first launch of the run gives the fast id; every later launch the slow one.
    fast = _lines(tmp_path / "fast.txt", {FAST: 1.0})
    slow = _lines(tmp_path / "slow.txt", {SLOW: 2.0})
    seen = shlex.quote(str(tmp_path / "seen"))
    script = (
        f"if [ -e {seen} ]; then cat {shlex.quote(str(slow))}; "
        f"else : > {seen}; cat {shlex.quote(str(fast))}; fi"
    )
    monkeypatch.chdir(tmp_path)

    result = cli("run", *SIDES, *QUICK, *RUN, "--", "sh", "-c", script)

    assert result.code == EXIT_ANALYSIS, result.err
    message = (
        "E_CASES_DIFFER: the sides produce different sets of primary cases: new: {new}; old: "
        "{old}; names that differ only in the mark ' +' and eight hex digits come from ids whose "
        "paths run over different words; if such names are one case, a folder whose name holds "
        "a space gives such words, and the sides' folders differ that way"
    )
    assert result.err.endswith(
        refusal_text(message.format(new=FAST_NAME, old=SLOW_NAME))
    ) or result.err.endswith(refusal_text(message.format(new=SLOW_NAME, old=FAST_NAME))), result.err
    assert _hides_the_words(result.out + result.err)


# Two made-up secrets, and ids that differ in one of them.
SECRETS = ("zq-made-up-kiwi7", "zq-made-up-pear3")
SECRET_ONLY = "run /made/up/a.py token={} data/x"
SECRET_ONLY_NAME = "run x +8d43a8db"
SECRET_AND_WORD = "run /made/up/a.py {} token={} data/x"
SECRET_AND_WORD_NAMES = ("run x +1e192939", "run x +19d164f0")


def _holds_a_secret(text: str) -> bool:
    return any(secret[3:] in text for secret in SECRETS)


def _refused_on_a_side(err: str, message: str) -> bool:
    return any(err.endswith(refusal_text(message.format(side=side))) for side in ("new", "old"))


def test_ids_of_one_launch_that_differ_only_in_a_secret_are_refused(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    ids = {SECRET_ONLY.format(SECRETS[0]): 1.0, SECRET_ONLY.format(SECRETS[1]): 2.0}
    lines = _lines(tmp_path / "lines.txt", ids)
    monkeypatch.chdir(tmp_path)

    result = cli("run", *SIDES, *QUICK, *RUN, "--", "cat", str(lines))

    assert result.code == EXIT_USAGE, result.err
    message = (
        "E_USAGE: side {side!r}: "
        + SHOWN_ALIKE.format(shown=SECRET_ONLY_NAME)
        + f", and differ only in a hidden secret; {RUN_ON_ADVICE}"
    )
    assert _refused_on_a_side(result.err, message), result.err
    assert not _holds_a_secret(result.out + result.err)
    assert _hides_the_words(result.out + result.err)


def test_ids_of_one_launch_that_differ_only_in_a_folder_are_refused(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    ids = {"read /made/up/Zqa/in.csv": 1.0, "read /made/up/Zqb/in.csv": 2.0}
    lines = _lines(tmp_path / "lines.txt", ids)
    monkeypatch.chdir(tmp_path)

    result = cli("run", *SIDES, *QUICK, *RUN, "--", "cat", str(lines))

    assert result.code == EXIT_USAGE, result.err
    message = (
        "E_USAGE: side {side!r}: "
        + SHOWN_ALIKE.format(shown="read in.csv")
        + ", and differ only in words that hold a '/' once their secrets are hidden; pairbench "
        "reads such words as folders, which may differ between sides and launches; " + RUN_ON_ADVICE
    )
    assert _refused_on_a_side(result.err, message), result.err
    assert _hides_the_words(result.out + result.err)


def _per_side(tmp_path: Path, new: str, old: str) -> str:
    """A shell text that prints ``new`` on the new side and ``old`` on the old side."""
    new_lines = _lines(tmp_path / "new.txt", {new: 1.0})
    old_lines = _lines(tmp_path / "old.txt", {old: 1.0})
    return (
        f'if [ -n "$ZQ_SIDE" ]; then cat {shlex.quote(str(old_lines))}; '
        f"else cat {shlex.quote(str(new_lines))}; fi"
    )


def test_sides_whose_ids_differ_in_a_dropped_word_with_an_encoded_slash_are_two_cases(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    # '4%2Fq' and '5%2Fq' hold no '/', so they are words the path runs over, not folders.
    script = _per_side(tmp_path, "run /made/up/a.py 4%2Fq data/x", "run /made/up/a.py 5%2Fq data/x")
    monkeypatch.chdir(tmp_path)

    result = cli("run", *TWO_SIDES, *QUICK, *RUN, "--", "sh", "-c", script)

    assert result.code == EXIT_ANALYSIS, result.err
    message = (
        "E_CASES_DIFFER: the sides produce different sets of primary cases: new: run x +bf06410f; "
        "old: run x +98b84fe5; names that differ only in the mark ' +' and eight hex digits come "
        "from ids whose paths run over different words; if such names are one case, a folder "
        "whose name holds a space gives such words, and the sides' folders differ that way"
    )
    assert result.err.endswith(refusal_text(message)), result.err
    assert "%2Fq" not in result.out + result.err


def test_sides_whose_socket_folder_names_hold_a_space_pair_the_case(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    script = _per_side(tmp_path, "x unix:///made/up/my dir/s.sock", "x unix:///made/up/b/s.sock")
    monkeypatch.chdir(tmp_path)

    result = cli("run", *TWO_SIDES, *QUICK, *RUN, "--", "sh", "-c", script)

    assert result.code == EXIT_OK, result.err
    assert _medians(_results(tmp_path / "run"), "x unix:///s.sock") == {
        "x unix:///s.sock": (1.0, 1.0)
    }
    assert "made/up" not in result.out + result.err


# Ids whose path written with '%2F' holds a folder named with a blank, different on each side,
# and what each shows: a pair whose folder names differ before the blank, and a pair alike up
# to the blank that differ only after it. Then the same ids with '%20' for the blank and the
# one name both show.
ENCODED_BLANK_PAIRS = (
    (
        ("get[?host=%2Fmade%2FZq dir%2Frun]", "get[?host=%2Fmade%2FZr dir%2Frun]"),
        ("get[?host=%2FZq dir%2Frun]", "get[?host=%2FZr dir%2Frun]"),
    ),
    (
        ("get[?host=%2Fmade%2FZq dir%2Frun]", "get[?host=%2Fmade%2FZq mode%2Frun]"),
        ("get[?host=%2FZq dir%2Frun]", "get[?host=%2FZq mode%2Frun]"),
    ),
)
ENCODED_ESCAPED_IDS = (
    "get[?host=%2Fmade%2FZq%20dir%2Frun]",
    "get[?host=%2Fmade%2FZr%20dir%2Frun]",
)
ENCODED_ESCAPED_SHOWN = "get[?host=%2Frun]"


@pytest.mark.parametrize(("ids", "shown"), ENCODED_BLANK_PAIRS)
def test_sides_whose_encoded_folder_names_hold_a_blank_and_differ_are_refused(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keys: list[bytes],
    ids: tuple[str, str],
    shown: tuple[str, str],
) -> None:
    # A blank ends a path written with '%2F', so the words of the folder show on each side.
    script = _per_side(tmp_path, *ids)
    monkeypatch.chdir(tmp_path)

    result = cli("run", *TWO_SIDES, *QUICK, *RUN, "--", "sh", "-c", script)

    assert result.code == EXIT_ANALYSIS, result.err
    new, old = shown
    message = (
        f"E_CASES_DIFFER: the sides produce different sets of primary cases: new: {new}; old: {old}"
    )
    assert result.err.endswith(refusal_text(message)), result.err
    assert "%2Fmade%2F" not in result.out + result.err


def test_sides_whose_encoded_folder_names_write_the_blank_as_percent_20_pair_the_case(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    script = _per_side(tmp_path, *ENCODED_ESCAPED_IDS)
    monkeypatch.chdir(tmp_path)

    result = cli("run", *TWO_SIDES, *QUICK, *RUN, "--", "sh", "-c", script)

    assert result.code == EXIT_OK, result.err
    assert _medians(_results(tmp_path / "run"), ENCODED_ESCAPED_SHOWN) == {
        ENCODED_ESCAPED_SHOWN: (1.0, 1.0)
    }
    assert "Zq" not in result.out + result.err


def test_ids_that_differ_in_a_secret_and_a_word_their_path_runs_over_get_two_names(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    ids = {
        SECRET_AND_WORD.format("Zqfast", SECRETS[0]): 1.0,
        SECRET_AND_WORD.format("Zqslow", SECRETS[1]): 2.0,
    }
    lines = _lines(tmp_path / "lines.txt", ids)
    monkeypatch.chdir(tmp_path)

    result = cli("run", *SIDES, *QUICK, *RUN, "--", "cat", str(lines))

    assert result.code == EXIT_OK, result.err
    assert not _holds_a_secret(result.out + result.err)
    for name in FILES:
        text = (tmp_path / "run" / name).read_text(encoding="utf-8")
        assert _hides_the_words(text) and not _holds_a_secret(text), name
    fast, slow = SECRET_AND_WORD_NAMES
    assert _medians(_results(tmp_path / "run"), fast, slow) == {
        fast: (1.0, 1.0),
        slow: (2.0, 2.0),
    }


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _two_runs(
    cli: Cli, tmp_path: Path, keys: list[bytes], *launches: dict[str, float]
) -> tuple[Path, Path]:
    """Run once per dict, the first under KEY and the second under OTHER_KEY.

    A capture keeps its run's key only when one of its names carries a mark.
    """
    keys.append(OTHER_KEY)
    lines = tmp_path / "lines.txt"
    for name, key_hex, cases in zip(
        ("one", "two"), (KEY_HEX, OTHER_KEY_HEX), launches, strict=True
    ):
        _lines(lines, cases)
        _run(cli, name, "cat", str(lines))
        marked = any(case.startswith("run /") for case in cases)
        kept = [{"t": "case_key", "key": key_hex}] if marked else []
        assert _records(tmp_path / name, "case_key") == kept
    return tmp_path / "one", tmp_path / "two"


def _compare(cli: Cli, *captures: Path) -> Any:
    return cli("compare", *(c / "capture.jsonl" for c in captures), "--out", "pooled")


def test_pooled_captures_show_the_first_captures_names(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    one, two = _two_runs(cli, tmp_path, keys, {FAST: 1.0, SLOW: 2.0}, {FAST: 1.5, SLOW: 2.5})
    assert {c["case"] for c in _results(two)["comparisons"]} >= {FAST_OTHER, SLOW_OTHER}

    result = _compare(cli, one, two)

    assert result.code == EXIT_OK, result.err
    pooled = _results(tmp_path / "pooled")
    assert pooled["run"]["pooled"] is True
    assert _medians(pooled, FAST_NAME, SLOW_NAME) == {
        FAST_NAME: (1.25, 1.25),
        SLOW_NAME: (2.25, 2.25),
    }
    text = (tmp_path / "pooled" / "results.json").read_text(encoding="utf-8")
    assert FAST_OTHER not in text and SLOW_OTHER not in text
    assert KEY_HEX not in text and OTHER_KEY_HEX not in text

    # Named the other way round, the pool shows the other capture's names.
    result = _compare(cli, two, one)

    assert result.code == EXIT_OK, result.err
    assert _medians(_results(tmp_path / "pooled"), FAST_OTHER, SLOW_OTHER) == {
        FAST_OTHER: (1.25, 1.25),
        SLOW_OTHER: (2.25, 2.25),
    }


def test_captures_that_read_the_ids_in_another_order_pool_each_name_with_its_case(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    # The second run gives the slow id first.
    one, two = _two_runs(cli, tmp_path, keys, {FAST: 1.0, SLOW: 2.0}, {SLOW: 2.0, FAST: 1.0})

    result = _compare(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert _medians(_results(tmp_path / "pooled"), FAST_NAME, SLOW_NAME) == {
        FAST_NAME: (1.0, 1.0),
        SLOW_NAME: (2.0, 2.0),
    }
    assert "pool_folders_merged" not in result.err


def test_captures_whose_ids_differ_only_in_a_folder_pool_with_a_loud_note(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    # The second run's ids sit under another folder; the words their paths run over agree.
    one, two = _two_runs(
        cli, tmp_path, keys, {FAST: 1.0, SLOW: 2.0}, {MOVED_FAST: 1.0, MOVED_SLOW: 2.0}
    )

    result = _compare(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert _hides_the_words(result.out + result.err)
    message = (
        f"the pooled captures read each of the cases {SLOW_NAME!r}, {FAST_NAME!r} as one case "
        + FOLDERS_WHY
    )
    assert f"pairbench: note: pool_folders_merged: {message}\n" in result.err
    pooled = _results(tmp_path / "pooled")
    assert {"code": "pool_folders_merged", "message": message} in pooled["notes"]
    assert _medians(pooled, FAST_NAME, SLOW_NAME) == {FAST_NAME: (1.0, 1.0), SLOW_NAME: (2.0, 2.0)}
    for name in ("results.json", "results.md"):
        assert _hides_the_words((tmp_path / "pooled" / name).read_text(encoding="utf-8")), name


SECRET_CASE = "test_db[PGPASSWORD={}]"
SECRET_CASE_NAME = "test_db[PGPASSWORD=<hidden>]"


def test_captures_whose_ids_differ_only_in_a_hidden_secret_pool_with_a_loud_note(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    one, two = _two_runs(
        cli,
        tmp_path,
        keys,
        {SECRET_CASE.format(SECRETS[0]): 1.0},
        {SECRET_CASE.format(SECRETS[1]): 1.0},
    )

    result = _compare(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert not _holds_a_secret(result.out + result.err)
    message = f"the pooled captures read the case {SECRET_CASE_NAME!r} as one case {SECRETS_WHY}"
    assert f"pairbench: note: pool_secrets_merged: {message}\n" in result.err
    pooled = _results(tmp_path / "pooled")
    assert {"code": "pool_secrets_merged", "message": message} in pooled["notes"]
    for name in ("results.json", "results.md"):
        assert not _holds_a_secret((tmp_path / "pooled" / name).read_text(encoding="utf-8")), name


def test_captures_whose_ids_differ_in_a_word_their_path_runs_over_stay_two_cases(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    one, two = _two_runs(cli, tmp_path, keys, {FAST: 1.0}, {SLOW: 2.0})

    result = _compare(cli, one, two)

    assert result.code == EXIT_ANALYSIS, result.err
    assert result.err.endswith(
        refusal_text(
            f"E_POOL_CASES: the cases {SLOW_NAME}, {FAST_NAME} differ between the captures "
            f"{_capture_id(one)} and {_capture_id(two)}"
        )
    ), result.err
    assert _hides_the_words(result.out + result.err)


def test_a_case_pattern_matches_a_name_with_or_without_its_mark(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    lines = _lines(tmp_path / "lines.txt", {FAST: 1.0, SLOW: 2.0})
    monkeypatch.chdir(tmp_path)
    keys.append(KEY)

    result = cli("run", *SIDES, *QUICK, *RUN, "--case", SHOWN, "--", "cat", str(lines))

    assert result.code == EXIT_OK, result.err
    primary = {c["case"] for c in _results(tmp_path / "run")["comparisons"] if c["primary"]}
    assert primary == {FAST_NAME, SLOW_NAME}
    # A name copied from these results picks its one case out of them.
    shown = cli(
        "report", tmp_path / "run" / "results.json", "--format", "markdown", "--case", FAST_NAME
    )
    assert shown.code == EXIT_OK, shown.err
    assert FAST_NAME in shown.out and SLOW_NAME not in shown.out
    # A mark no run of this key makes matches no case.
    stale = "run x +0a0a0a0a"
    again = (*RUN[:-1], "again")
    result = cli("run", *SIDES, *QUICK, *again, "--case", stale, "--", "cat", str(lines))
    assert result.code == EXIT_USAGE, result.err
    head = (
        f"E_USAGE: the primary case pattern {stale!r} matches no case of this run; its cases are: "
    )
    line = result.err.splitlines()[-2]
    assert line.startswith(head) and line.endswith(f"; {MARK_HINT}"), result.err
    assert f"{SLOW_NAME!r}, {FAST_NAME!r}" in line


def _token(case: str) -> str:
    return "{{fig:" + case + ".new_vs_old.ratio}}"


def test_a_document_fills_from_the_results_that_named_its_cases_only(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    monkeypatch.chdir(tmp_path)
    one, two = _two_runs(cli, tmp_path, keys, {FAST: 1.0, SLOW: 2.0}, {FAST: 1.0, SLOW: 2.0})
    template = tmp_path / "doc.in.md"
    template.write_text(f"ratio {_token(FAST_NAME)}\n", encoding="utf-8")

    filled = cli("fill", template, "--results", one / "results.json", "-o", tmp_path / "doc.md")

    assert filled.code == EXIT_OK, filled.err
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "ratio 1.00x\n"

    # A separately analysed capture shows other marks: the figure is missing there.
    result = cli("fill", template, "--results", two / "results.json", "-o", tmp_path / "two.md")

    assert result.code == EXIT_FIGURE_MISSING, result.err
    assert result.err == refusal_text(
        f"E_FIGURE_MISSING: 1 figure is missing from the results: {FAST_NAME}.new_vs_old.ratio; "
        "the mark ' +' and eight hex digits at the end of a case name is made with each run's "
        "own key, so the results of another run or another compare name that case otherwise: "
        "fill from the results the document's figures came from, or from one compare of all "
        "their captures"
    ), result.err


def test_the_tool_server_gives_the_comparisons_of_a_name_given_without_its_mark(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: list[bytes]
) -> None:
    lines = _lines(tmp_path / "lines.txt", {FAST: 1.0, SLOW: 2.0})
    monkeypatch.chdir(tmp_path)
    _run(cli, "run", "cat", str(lines))

    text = ToolServer(allow_run=False).call("results", path=str(tmp_path / "run"), case=SHOWN)

    answer = json.loads(text)
    assert sorted(c["case"] for c in answer["comparisons"]) == [SLOW_NAME, FAST_NAME]
    assert KEY_HEX not in text and _hides_the_words(text)


GB_FAST = "BM_Read /made/up/{side}/in.bin Zqfast x/y"
GB_SLOW = "BM_Read /made/up/{side}/in.bin Zqslow x/y"
NV_FAST = "Device=0 Path=/made/up/{side}/a.bin Zqfast x/y"
NV_SLOW = "Device=0 Path=/made/up/{side}/a.bin Zqslow x/y"


def _gbench_doc(values: dict[str, float]) -> dict[str, Any]:
    entry = {"run_type": "iteration", "repetitions": 1, "repetition_index": 0, "threads": 1}
    return {
        "benchmarks": [
            {**entry, "name": name, "run_name": name, "iterations": 10, "time_unit": "s"}
            | {"real_time": value, "cpu_time": value}
            for name, value in values.items()
        ]
    }


def _nvbench_doc(values: dict[str, float]) -> dict[str, Any]:
    def summary(value: float) -> dict[str, Any]:
        data = [{"name": "value", "type": "float64", "value": repr(value)}]
        return {"tag": "nv/cold/time/gpu/mean", "data": data}

    states = [{"name": name, "summaries": [summary(value)]} for name, value in values.items()]
    return {"benchmarks": [{"name": "bench", "states": states}]}


@pytest.mark.parametrize(
    ("driver", "document", "fast", "slow", "first", "second"),
    [
        pytest.param(
            "gbench",
            _gbench_doc,
            GB_FAST,
            GB_SLOW,
            "BM_Read y +5a549880",
            "BM_Read y +1d96a24e",
            id="gbench",
        ),
        pytest.param(
            "nvbench",
            _nvbench_doc,
            NV_FAST,
            NV_SLOW,
            "bench/Device=0 Path=y +6ea86a25",
            "bench/Device=0 Path=y +f76693db",
            id="nvbench",
        ),
    ],
)
def test_result_files_name_benchmarks_shown_alike_with_the_compares_marks(
    cli: Cli,
    tmp_path: Path,
    keys: list[bytes],
    driver: str,
    document: Callable[[dict[str, float]], dict[str, Any]],
    fast: str,
    slow: str,
    first: str,
    second: str,
) -> None:
    for side in ("new", "old"):
        values = {fast.format(side=side): 1.0, slow.format(side=side): 2.0}
        # The second launch of each side lists the benchmarks in the other order.
        for launch, listed in ((1, values), (2, dict(reversed(list(values.items()))))):
            path = tmp_path / f"{side}{launch}.json"
            path.write_text(json.dumps(document(listed)), encoding="utf-8")
    out = tmp_path / "out"

    result = cli(
        "compare",
        "--side",
        f"new=file:{tmp_path}/new*.json",
        "--side",
        f"old=file:{tmp_path}/old*.json",
        "--driver",
        driver,
        "--out",
        out,
        "--json",
    )

    assert result.code == EXIT_OK, result.err
    assert _hides_the_words(result.out + result.err)
    # A comparison of result files writes no plan and no report page.
    for name in ("results.json", "results.md", "capture.jsonl"):
        assert _hides_the_words((out / name).read_text(encoding="utf-8")), name
    assert _records(out, "case_key") == [{"t": "case_key", "key": KEY_HEX}]
    # Each name holds the values of one benchmark on both sides and in both launches.
    assert _medians(json.loads(result.out), first, second) == {
        first: (1.0, 1.0),
        second: (2.0, 2.0),
    }
