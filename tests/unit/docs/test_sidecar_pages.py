# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages that describe ``hash_inputs.json`` say it is private unless the check passes.

``tools/hash_inputs.py`` writes the sidecar owner-only when the shared files hide a value it
holds. ``--publish`` copies ``results.json``, ``results.md`` and ``report.html``, and the
sidecar with them only when the shared files show each value it holds; otherwise the sidecar
stays owner-only in the run folder and the publish exits 0. The run-folder table lists the
sidecar as private, the five pages on publishing say what a publish copies and what it keeps
private, no page says a publish of a private sidecar publishes nothing, the pages on the
showcases say a reader of one published without its sidecar cannot recompute its hashes, no
page says a reader can recompute every hash, and the two pages on the limits of the hashes
say a fingerprint covers the last part of an executable's path, not its folder.
The neutral places and the kinds of value that may pass are each one list in the script, and
the pages and the script's own description name the same lists and the same rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .conftest import load_tool

RESULTS = "docs/reference/results-schema.md"
SECURITY = "SECURITY.md"
SIDECAR_ROW = (
    "| `hash_inputs.json` | not written by a run: `tools/hash_inputs.py` of the source "
    "repository writes it, with what each published hash is taken over | private, like the "
    "capture: it holds each side's whole command; the script writes it owner-only and says "
    "so, unless each value it holds passes as one of the kinds that `SECURITY.md` lists: shown "
    "values, which `results.json` and `results.md` show, neutral places, schema ids and keys, "
    "config-schema values and config defaults, or null, true, false and empty values; of the "
    "neutral places `/work`, `/home/user` and `/usr/local/bin/python3` each passes only as "
    "itself, and a path under one only when they show each of its other parts |"
)
CAPTURE_ROW = "| `capture.jsonl` |"
# A publish of a run whose sidecar cannot be shared copies the three shared files, keeps the
# sidecar owner-only in the run folder and exits with the run's own code.
PUBLISH_PAGES = {
    SECURITY: (
        "`--publish FOLDER` copies `results.json`, `results.md` and `report.html` into the "
        "folder, and the sidecar with them only when it may be shared; otherwise it keeps the "
        "sidecar owner-only in the run folder, says so on standard error and exits 0."
    ),
    "CONTRIBUTING.md": (
        "`tools/hash_inputs.py RUN_FOLDER --publish FOLDER` copies `results.json`, `results.md` "
        "and `report.html` into the folder, and the sidecar with them only when the shared files "
        "show every value the sidecar holds; otherwise the sidecar stays owner-only in the run "
        "folder and is not published."
    ),
    "showcases/README.md": (
        "copies `results.json`, `results.md` and `report.html` into the published folder, and "
        "the sidecar with them only when the shared files show every value the sidecar holds; "
        "otherwise the sidecar stays owner-only in the private folder, one line on standard "
        "error says so, and `run.sh` exits with the run's own code."
    ),
    "docs/reference/environment.md": (
        "publishes `results.json`, `results.md` and `report.html` into the named folder, and "
        "`hash_inputs.json` with them only when the shared files show every value the sidecar "
        "holds; otherwise the sidecar stays owner-only in the private folder and `run.sh` exits "
        "with the run's own code."
    ),
    RESULTS: (
        "`tools/hash_inputs.py RUN_FOLDER --publish FOLDER` copies `results.json`, `results.md` "
        "and `report.html` into the folder, and the sidecar with them only when it can be "
        "shared; otherwise the sidecar stays owner-only in the run folder and is not published."
    ),
}
# A sentence that says a publish of a private sidecar copies nothing or exits 3.
NOTHING_PUBLISHED = re.compile(r"publishes\s+nothing|nothing\s+is\s+published|exits\s+3\b")
# A reader of a showcase published without its sidecar is pointed to the showcase's recipe.
READER = (
    "A reader of a published showcase whose sidecar was kept private cannot recompute its "
    "hashes; the showcase's public recipe, its `pairbench.toml`, `run.sh` and `sides.lock`, "
    "says what each side ran."
)
READER_PAGES = ("showcases/README.md", "docs/showcases.md")
# The launch-cost script's command for the writer names the sidecar as the one file it may keep.
LAUNCH_COST_COMMAND = (
    "The command that writes ``hash_inputs.json`` and publishes the run's shared files, and "
    "the sidecar with them only when it can be shared."
)
PRIVATE = {
    SECURITY: "so it is private like the capture",
    RESULTS: "so it is private like the capture",
}
EVERY_HASH = re.compile(r"recompute(?:s)?\s+every\s+hash", re.IGNORECASE)
WALK_TEST = "tests/unit/docs/test_hash_inputs.py"
EXECUTABLE_PART = "of its executable it covers the last part of the path, not the folder."
EXECUTABLE_PATH = "the path of its executable"
# The neutral places, each of which passes as itself, and the rule for a path under one.
NEUTRAL_PLACES = ("/work", "/home/user", "/usr/local/bin/python3")
PLACES = re.compile(r"the neutral places ((?:`+[^`]+`+(?:, | and ))*`+[^`]+`+)")
CODE = re.compile(r"`+([^`]+)`+")
PLACE_RULE = (
    "A neutral place passes only as itself; a path under one passes only when a shared file "
    "shows each of its other parts as a whole word."
)
# The kinds of value that may pass, in the order the script and the policy list them.
PASSING_KINDS = (
    "Shown values",
    "Neutral places",
    "Schema ids and keys",
    "Config-schema values and config defaults",
    "Null, true, false and empty values",
)
LIMITS_OF_THE_HASHES = "## Known limits of the hashes"
# A key of `results.json` is a shown value too, and so is each word of it.
SHOWN_KEYS = {
    SECURITY: (
        "a whole value or key of `results.json`, or a whole word of one of its texts or keys"
    ),
    "tools/hash_inputs.py": (
        "a whole value or key of ``results.json``, or a whole word of a text or a key of "
        "``results.json``"
    ),
}
# A path under a neutral place stays private only while no shared file shows its other parts.
SHOWN_PARTS = (
    "keeps its sidecar private as long as no shared file shows each of the path's other parts: "
    "the results show the last part of a path at most, but a case whose id is "
    "`made-up-folder run` shows both words and lets that path pass."
)
# The shown command hides each `--set` value, so the policy says what that does to the sidecar.
SET_VALUES = (
    "The shown command hides the value of each `--set`, so such a value passes only as another "
    "kind: a memory cap such as `--set launch.memory=8g`, or any other `--set` value that is not "
    "a neutral place, a listed value, a default or an empty value, keeps the sidecar private "
    "unless a shared file shows that value in another place, such as the word `8g` in the "
    "workload's command."
)


def flat(path: Path) -> str:
    """The text of a page with each run of spaces and line breaks made one space."""
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def writer(repo_root: Path) -> ModuleType:
    return load_tool(repo_root, "hash_inputs")


def test_the_run_folder_table_lists_the_sidecar_as_private(repo_root: Path) -> None:
    lines = (repo_root / RESULTS).read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if line.startswith("| `")]

    assert SIDECAR_ROW in rows
    assert rows[0].startswith(CAPTURE_ROW)


@pytest.mark.parametrize("page", sorted(PRIVATE))
def test_a_page_on_the_hashes_calls_the_sidecar_private(repo_root: Path, page: str) -> None:
    assert PRIVATE[page] in flat(repo_root / page)


@pytest.mark.parametrize("page", sorted(PUBLISH_PAGES))
def test_a_page_on_publishing_says_a_private_sidecar_stays_and_the_shared_files_are_published(
    repo_root: Path, page: str
) -> None:
    assert PUBLISH_PAGES[page] in flat(repo_root / page)


def test_no_public_page_says_a_publish_of_a_private_sidecar_publishes_nothing(
    repo_root: Path, kit: Any
) -> None:
    pages = [*kit.documents(repo_root), repo_root / "docs" / "reference" / "environment.md"]
    saying = [
        path.relative_to(repo_root).as_posix()
        for path in pages
        if NOTHING_PUBLISHED.search(" ".join(path.read_text(encoding="utf-8").split()))
    ]

    assert {repo_root / page for page in PUBLISH_PAGES} <= set(pages)
    assert saying == []


@pytest.mark.parametrize("page", READER_PAGES)
def test_a_page_on_the_showcases_says_a_reader_of_one_without_its_sidecar_reads_its_recipe(
    repo_root: Path, page: str
) -> None:
    assert READER in flat(repo_root / page)


def test_the_launch_cost_script_says_its_writer_publishes_the_sidecar_only_when_it_can_be_shared(
    repo_root: Path,
) -> None:
    command = load_tool(repo_root, "launch_cost").hash_inputs_command

    assert " ".join((command.__doc__ or "").split()) == LAUNCH_COST_COMMAND


def test_no_public_page_says_a_reader_can_recompute_every_hash(repo_root: Path, kit: Any) -> None:
    pages = [*kit.documents(repo_root), repo_root / WALK_TEST]
    saying = [
        path.relative_to(repo_root).as_posix()
        for path in pages
        if EVERY_HASH.search(path.read_text(encoding="utf-8"))
    ]

    assert len(pages) > len(PUBLISH_PAGES)
    assert saying == []


@pytest.mark.parametrize("page", [SECURITY, RESULTS])
def test_a_page_on_the_limits_says_the_fingerprint_keeps_the_executable_name_only(
    repo_root: Path, page: str
) -> None:
    text = flat(repo_root / page)

    assert EXECUTABLE_PART in text
    assert EXECUTABLE_PATH not in text


def places_named(text: str) -> list[tuple[str, ...]]:
    """The places each phrase "the neutral places ..." of a text names, in order."""
    joined = " ".join(text.split())
    return [tuple(CODE.findall(found.group(1))) for found in PLACES.finditer(joined)]


def described(writer: ModuleType) -> str:
    return writer.__doc__ or ""


@pytest.mark.parametrize("page", [SECURITY, RESULTS, "tools/hash_inputs.py"])
def test_each_page_names_the_neutral_places_the_script_holds(
    repo_root: Path, writer: ModuleType, page: str
) -> None:
    text = described(writer) if page.endswith(".py") else flat(repo_root / page)

    assert writer.NEUTRAL_PLACES == NEUTRAL_PLACES
    assert places_named(text) == [NEUTRAL_PLACES]


@pytest.mark.parametrize("page", [SECURITY, "tools/hash_inputs.py"])
def test_the_policy_and_the_script_say_a_neutral_place_passes_only_as_itself(
    repo_root: Path, writer: ModuleType, page: str
) -> None:
    text = described(writer) if page.endswith(".py") else (repo_root / page).read_text("utf-8")

    assert PLACE_RULE in " ".join(text.split())


def kinds_listed(text: str) -> list[str]:
    """The bold label of each list item of a text, in order."""
    return re.findall(r"^\s*[-*] \*\*([^*]+)\*\*:", text, re.MULTILINE)


def test_the_policy_and_the_script_list_every_kind_of_value_that_may_pass(
    repo_root: Path, writer: ModuleType
) -> None:
    policy = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = policy.partition(LIMITS_OF_THE_HASHES)[2].partition("\n## ")[0]

    assert writer.PASSING_KINDS == PASSING_KINDS
    assert kinds_listed(section) == list(PASSING_KINDS)
    assert kinds_listed(described(writer)) == list(PASSING_KINDS)


def test_the_run_folder_table_names_each_kind_of_value_that_may_pass_in_order(
    repo_root: Path, writer: ModuleType
) -> None:
    row = next(
        line
        for line in (repo_root / RESULTS).read_text(encoding="utf-8").splitlines()
        if line.startswith("| `hash_inputs.json` |")
    )
    places = [row.find(kind.lower()) for kind in writer.PASSING_KINDS]

    assert writer.PASSING_KINDS == PASSING_KINDS
    assert -1 not in places
    assert places == sorted(places)


@pytest.mark.parametrize("page", sorted(SHOWN_KEYS))
def test_the_policy_and_the_script_say_a_key_of_the_results_is_shown(
    repo_root: Path, writer: ModuleType, page: str
) -> None:
    text = described(writer) if page.endswith(".py") else (repo_root / page).read_text("utf-8")

    assert SHOWN_KEYS[page] in " ".join(text.split())


def test_the_policy_says_a_path_under_a_neutral_place_passes_once_its_parts_are_shown(
    repo_root: Path,
) -> None:
    section = flat(repo_root / SECURITY).partition(LIMITS_OF_THE_HASHES)[2]

    assert SHOWN_PARTS in section.partition(" ## ")[0]


def test_the_policy_says_a_value_given_with_set_keeps_the_sidecar_private_unless_shown(
    repo_root: Path,
) -> None:
    section = flat(repo_root / SECURITY).partition(LIMITS_OF_THE_HASHES)[2]

    assert SET_VALUES in section.partition(" ## ")[0]
