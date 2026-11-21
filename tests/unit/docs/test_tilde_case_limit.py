# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a home folder's name in a case id among the known limits.

A case id keeps a word ``~NAME`` with nothing after it as typed, since in the name of a test
or a benchmark such a word is often no home, and cuts a path that ends at ``/home/NAME`` or
``/Users/NAME`` to ``NAME``, as it cuts any path, since a route such as ``/users/1`` reads the
same. So a user's home shows its name in a case id, also in a case that hyperfine names after
its command, while the shown command hides it. The entry says so with made-up examples and
advice, and each example and each piece of advice behaves as the entry says.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
NEXT_HEADING = "## Known limits of the hashes"
LIMIT = (
    "- **A home folder's name in a case id.** A case id keeps the name of a home folder, since"
    " in\n"
    "  the name of a test or a benchmark such a name is often no home, and two ids that differ"
    " only\n"
    "  there are two cases. A word that starts with `~` and a name, with nothing after it, shows"
    " as\n"
    "  typed (`test_invert[~mask]`, `test_dtor[~Widget]`), and a path that ends at a folder"
    " right\n"
    "  under `/home` or `/Users`, at the root or reached by climbing with `..`, is cut to that\n"
    "  folder's name, as any path in a case id is cut to its last part, since a route reads the"
    " same\n"
    "  (`test_get[/users/1]` shows `test_get[1]`). So a user's home shows its name:\n"
    "  `test_read[~made-up-user]` shows as typed, `test_read[/home/user]` shows"
    " `test_read[user]`,\n"
    "  and so does a case that `hyperfine` names after the command `ls ~made-up-user` or\n"
    "  `ls /home/user`, while the shown command hides that home. A path that goes on into the"
    " home\n"
    "  is cut to its last part (`test_read[~made-up-user/x.csv]` shows `test_read[x.csv]`)."
    " Name a\n"
    "  file inside the home, write your own home as `~`, or give the case a name, as"
    " hyperfine's\n"
    "  `--command-name` gives one.\n"
)
# The words of the entry on case ids that say a case named after its command keeps such a home.
CASE_ITEM_WORDS = (
    "A case that `hyperfine` names after its command is cleaned as the shown command is, but for"
    " the name of a home folder, which it keeps as any case id does"
)
# The guide's words on case ids that say the same, and the page that holds them.
GUIDE = "docs/guides/index.md"
GUIDE_WORDS = (
    "A case id, the name of a case that `hyperfine` names after its command included, keeps the"
    " name of a home folder: a word that starts with `~` and a name, with nothing after it, as"
    " typed, and a path that ends at a folder right under `/home` or `/Users` cut to that"
    " folder's name"
)
# (the case id, as the entry says a results document shows it)
KEPT = ("test_invert[~mask]", "test_dtor[~Widget]", "test_read[~made-up-user]", "test_read[~]")
CHANGED = (
    ("test_get[/users/1]", "test_get[1]"),
    ("test_read[/home/user]", "test_read[user]"),
    ("test_read[../home/user]", "test_read[user]"),
    ("test_read[/Users/user]", "test_read[user]"),
    ("test_read[~made-up-user/x.csv]", "test_read[x.csv]"),
)
# Two ids that differ only in such a word, and two that differ only in such a path, each pair
# as read and as a results document shows it.
APART = (
    (("test_invert[~mask]", "test_invert[~bits]"), ("test_invert[~mask]", "test_invert[~bits]")),
    (("test_get[/users/1]", "test_get[/users/2]"), ("test_get[1]", "test_get[2]")),
)
COMMAND = "ls ~made-up-user"
PATH_COMMAND = "ls /home/user"
USER = "made-up-user"
ROUNDS = 8


def limits_text(root: Path) -> str:
    text = (root / SECURITY).read_text(encoding="utf-8")
    start = text.index(LIMITS_HEADING)
    return text[start : text.index(NEXT_HEADING, start)]


def test_the_known_limits_list_a_home_written_with_a_tilde_in_a_case_id(repo_root: Path) -> None:
    assert LIMIT in limits_text(repo_root)


def test_the_entry_on_case_ids_says_a_case_named_after_its_command_keeps_it(
    repo_root: Path,
) -> None:
    assert CASE_ITEM_WORDS in " ".join(limits_text(repo_root).split())


def test_the_guide_on_case_ids_says_a_case_id_keeps_such_a_word(repo_root: Path) -> None:
    text = (repo_root / GUIDE).read_text(encoding="utf-8")

    assert GUIDE_WORDS in " ".join(text.split())


@pytest.mark.parametrize("case", KEPT)
def test_a_case_id_the_entry_says_is_kept_shows_as_typed(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize(("case", "shown"), CHANGED)
def test_a_case_id_the_entry_says_changes_shows_what_it_says(case: str, shown: str) -> None:
    assert model.public_case(case) == shown


def _sample(case: str) -> api.Sample:
    return api.Sample(case=case, metric="time", unit="s", better="lower", kind="time", value=1.5)


@pytest.mark.parametrize(("ids", "shown"), APART)
def test_two_ids_that_differ_only_in_such_a_word_or_path_are_two_cases(
    ids: tuple[str, str], shown: tuple[str, str]
) -> None:
    read = api.public_cases([_sample(case) for case in ids], "made-up-driver")

    assert tuple(sample.case for sample in read) == shown


@pytest.mark.parametrize("command", [COMMAND, PATH_COMMAND])
def test_the_shown_command_hides_the_home_the_case_keeps(command: str) -> None:
    shown = model.public_command(("pairbench", "run", "--", *command.split()))

    assert shown == "pairbench run -- ls '<hidden>'"
    assert command.split()[-1].rsplit("/", 1)[-1].lstrip("~") not in shown


def _exports(folder: Path, name: str | None, command: str = COMMAND) -> None:
    files = folder / "files"
    files.mkdir()
    for side, base in (("new", 0.2), ("old", 0.3)):
        for r in range(1, ROUNDS + 1):
            entry: dict[str, Any] = {
                "command": command,
                "measurements": [
                    {
                        "time_wall_clock": {"value": base + r / 1000, "unit": "second"},
                        "exit_code": 0,
                    }
                ],
            }
            if name is not None:
                entry["name"] = name
            doc = {"schema_version": 2, "results": [entry]}
            (files / f"{side}-{r}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize(
    ("command", "name", "case"),
    [
        pytest.param(COMMAND, None, COMMAND, id="named-after-its-command"),
        pytest.param(PATH_COMMAND, None, "ls user", id="named-after-a-command-with-a-path"),
        pytest.param(COMMAND, "list the home", "list the home", id="given-a-command-name"),
    ],
)
def test_a_hyperfine_case_shows_as_the_entry_says(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    name: str | None,
    case: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    _exports(tmp_path, name, command)

    shown = cli(
        "compare",
        "--side",
        "new=file:files/new-*.json",
        "--side",
        "old=file:files/old-*.json",
        "--driver",
        "hyperfine",
        "--out",
        "out",
    )

    assert shown.code == EXIT_OK
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [found["case"] for found in written["comparisons"]] == [case]
