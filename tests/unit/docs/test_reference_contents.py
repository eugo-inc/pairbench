# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the reference pages, the guides and the skill say, against the names and rules in the code.

Each expectation is read from the code: the run folder's names from the
model, the built-in start-up phases from the serving side, the side name rule
from ``validate_side_name``, the reasons of the API example from running it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import ARTIFACT_SERVER_LOG, ARTIFACT_STDERR, ARTIFACT_STDOUT
from pairbench.config import flag_config, load_experiment
from pairbench.errors import Refusal
from pairbench.model import (
    DIR_ARTIFACTS,
    DIR_CHARTS,
    DIR_PROFILES,
    FILE_CAPTURE,
    FILE_DIAGNOSTICS,
    FILE_MARKDOWN,
    FILE_PLAN,
    FILE_REPORT,
    FILE_RESULTS,
    ServeSpec,
    validate_side_name,
)
from pairbench.results import load_schema
from pairbench.runner import LAUNCH_COST_FOLDER
from pairbench.sides.serve import (
    BUILTIN_PHASES,
    READER_CATCH_UP_S,
    RESERVED_PHASES,
    phase_case,
    phase_patterns,
)

ROOT = Path(__file__).resolve().parents[3]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def _row(text: str, first_cell: str) -> str:
    (row,) = [line for line in text.splitlines() if line.startswith(f"| {first_cell} |")]
    return row


# --- the run folder -----------------------------------------------------------

RUN_FOLDER_FILES = (FILE_CAPTURE, FILE_RESULTS, FILE_MARKDOWN, FILE_PLAN, FILE_REPORT)
RUN_FOLDER_DIRS = (DIR_PROFILES, DIR_CHARTS, DIR_ARTIFACTS)


def test_the_schema_page_has_a_row_for_every_file_and_folder_of_a_run_folder() -> None:
    page = _read("docs/reference/results-schema.md")
    for name in (*RUN_FOLDER_FILES, FILE_DIAGNOSTICS):
        _row(page, f"`{name}`")
    for name in RUN_FOLDER_DIRS:
        _row(page, f"`{name}/`")
    artifacts = _row(page, f"`{DIR_ARTIFACTS}/`")
    for name in (ARTIFACT_STDOUT, ARTIFACT_STDERR, ARTIFACT_SERVER_LOG, f"{LAUNCH_COST_FOLDER}/"):
        assert f"`{name}`" in artifacts, name
    assert "private" in artifacts


def test_the_quickstart_and_the_licence_page_name_the_launch_output_folder() -> None:
    assert f"`{DIR_ARTIFACTS}/`" in _read("docs/quickstart.md")
    assert f"`{DIR_ARTIFACTS}/`" in _section(_read("docs/licence.md"), "## Your results")


# --- serving start-up phases -----------------------------------------------------


def test_the_config_page_gives_the_built_in_phases_as_the_default() -> None:
    row = _row(_read("docs/reference/config.md"), "`sides.NAME.serve.phases`")
    default = row.split("|")[2]
    assert BUILTIN_PHASES
    for name in BUILTIN_PHASES:
        assert f"`{name}`" in default, name


def _phases_read_from(table: str) -> set[str]:
    """The start-up phases a serving side looks for when the config gives ``serve.phases``."""
    sides = ["new=serve:example.invalid/a:1", "old=serve:example.invalid/b:1"]
    flags = flag_config({}, sides=sides)
    experiment = load_experiment(environ={}, flags=flags, sets=[f"sides.new.serve.phases={table}"])
    (side,) = [side for side in experiment.sides if side.name == "new"]
    return set(phase_patterns(ServeSpec.from_json(side.spec)))


def test_the_config_page_says_which_phases_tables_replace_the_built_in_ones() -> None:
    meaning = _row(_read("docs/reference/config.md"), "`sides.NAME.serve.phases`").split("|")[3]
    assert _phases_read_from('{made_up = "made-up line"}') == {"made_up"}
    assert "a table that names at least one phase replaces the built-in patterns" in meaning
    assert _phases_read_from("{}") == set(BUILTIN_PHASES)
    assert "an empty table keeps them" in meaning


def test_the_serving_guide_lists_every_start_up_case_a_vllm_launch_gives() -> None:
    guide = _read("docs/guides/guidellm.md")
    for name in (*RESERVED_PHASES, *BUILTIN_PHASES):
        assert f"`{phase_case(name)}`" in guide, name


def test_the_pages_give_the_wait_for_the_reader_the_serving_side_uses() -> None:
    wait = f"{READER_CATCH_UP_S:g} s"
    meaning = _row(_read("docs/reference/config.md"), "`sides.NAME.serve.phases`").split("|")[3]
    guide = " ".join(_read("docs/guides/guidellm.md").split())

    assert f"the reader had not caught up {wait} after the first answer" in meaning
    assert f"pairbench waits up to {wait} for its reader of the server's output" in guide


# --- image sides and the workload ---------------------------------------------------


def test_the_pages_say_an_image_side_s_args_take_the_place_of_the_workload() -> None:
    # tests/unit/sides/test_container.py shows the command is the side's args, else the workload.
    row = _row(_read("docs/reference/config.md"), "`sides.NAME.args`")
    assert "in place of the shared workload" in row
    concepts = _read("docs/concepts.md")
    assert "runs those in place of the workload" in concepts


# What the shown command cannot hide, and the way to give a secret that no file records. The
# pages say a short plain value: a long random-looking one and the password options of the
# clients the config page lists are hidden, wherever they stand.
SHOWN_FORMS = (
    "short plain value",
    "option of one letter",
    "plain argument",
    "path of an address",
    "`env_pass`",
)
LIMIT_PAGES = (
    "SECURITY.md",
    "docs/agents.md",
    "docs/concepts.md",
    "docs/licence.md",
    "docs/reference/config.md",
    "docs/reference/results-schema.md",
    "docs/reference/text-format.md",
    "skills/pairbench/SKILL.md",
)


@pytest.mark.parametrize("page", LIMIT_PAGES)
def test_a_page_on_hidden_values_says_what_the_shown_command_cannot_hide(page: str) -> None:
    text = " ".join(_read(page).split())
    assert [form for form in SHOWN_FORMS if form not in text] == []


# What the agents' page says the shared files hide of the command, besides the secret forms,
# and the link to what the shown command cannot hide.
AGENT_RULE = "Do not put a secret on a side's command line."
AGENT_HIDDEN = (
    "the spec of each `--side`",
    "the value of each `--set`",
    "cut each absolute path to its last part",
    "](../SECURITY.md#known-limits-of-the-shown-command)",
)


def test_the_agents_page_says_what_the_shared_command_hides_and_links_its_limits() -> None:
    blocks = re.split(r"\n(?=- )|\n\s*\n", _read("docs/agents.md"))
    (rule,) = [" ".join(block.split()) for block in blocks if AGENT_RULE in block]

    assert [phrase for phrase in AGENT_HIDDEN if phrase not in rule] == []


def test_the_hash_of_a_command_changes_with_a_value_the_command_shows() -> None:
    from pairbench.sides.identity import argv_sha256

    # A short plain value after an option of one letter: no rule hides it, the hash covers it.
    assert argv_sha256(["tool", "-k", "made-up-a"]) != argv_sha256(["tool", "-k", "made-up-b"])


def test_the_forms_the_pages_name_are_shown_in_the_command() -> None:
    from pairbench.model import public_command

    shown = public_command(
        ["tool", "-a", "made-up-a", "made-up-b", "https://example.org/made-up-c"]
    )
    assert shown is not None
    assert [word for word in ("made-up-a", "made-up-b", "made-up-c") if word not in shown] == []


# --- schema versions ---------------------------------------------------------------

# What keeps a schema version and what needs a new one, said the same way on every page
# that states the rule: a field, and a value of a field whose schema lists its values.
VERSION_RULE = (
    "an optional field",
    "a field whose schema lists its values",
    "renaming or removing a field or a value",
)
VERSION_PAGES = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "docs/agents.md",
    "docs/reference/results-schema.md",
)


@pytest.mark.parametrize("page", VERSION_PAGES)
def test_a_page_on_schema_versions_says_a_new_value_keeps_the_version(page: str) -> None:
    text = " ".join(_read(page).split()).lower()
    assert [phrase for phrase in VERSION_RULE if phrase not in text] == []


# The pages that tell an agent which fields are stable say that a reason may be added.
NEW_REASON = "a later release may add a `reason` word"
STABLE_PAGES = ("docs/reference/tool-server.md", "skills/pairbench/references/results.md")


@pytest.mark.parametrize("page", STABLE_PAGES)
def test_a_page_on_stable_fields_says_a_reason_may_be_added(page: str) -> None:
    assert NEW_REASON in " ".join(_read(page).split())


# --- side names --------------------------------------------------------------------


def _refused(name: str) -> bool:
    try:
        validate_side_name(name)
    except Refusal:
        return True
    return False


def test_the_skill_states_the_side_name_rule_the_code_applies() -> None:
    (rule,) = [
        item
        for item in _read("skills/pairbench/references/sides.md").split("\n- ")
        if item.startswith("A name ")
    ]
    named = re.findall(r"`([^`]+)`", rule)
    single = [token for token in named if len(token) == 1 and token != "."]
    assert single
    for char in single:
        assert _refused(f"a{char}b"), char
    for whole in (".", ".."):
        assert f"`{whole}`" in rule
        assert _refused(whole)
    assert "not empty" in rule and _refused("")
    assert "white space" in rule and _refused("a b") and _refused("a\tb")
    assert not _refused("new-1.2")


# --- outcome words -------------------------------------------------------------------


def test_the_skill_says_which_p_value_grades_a_better_or_worse_case() -> None:
    page = _read("skills/pairbench/references/results.md")
    row = _row(_section(page, "## Outcomes"), "`better` / `worse`")
    assert "secondary case" in row
    assert "corrected p-value" in row and "uncorrected p-value" in row
    assert "`p_source` is `raw`" in row


# --- the results example -----------------------------------------------------------

# Fields the example on the schema page shows, by their place in the document.
SHOWN_FIELDS = (
    ("provenance", "driver"),
    ("sides", 0, "image_ref"),
    ("sides", 0, "identity", "platform"),
    ("machine_state", "discard_sha256"),
    ("comparisons", 0, "sensitivity", "not_computed"),
    ("same_vs_same", 0, "unit"),
)


def _example() -> dict[str, Any]:
    page = _read("docs/reference/results-schema.md")
    (block,) = re.findall(r"## `results.json`.*?```json\n(.*?)```", page, flags=re.DOTALL)
    loaded: dict[str, Any] = json.loads(block)
    return loaded


def _schema_has(path: tuple[Any, ...]) -> bool:
    schema = load_schema("results")
    definitions = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            node = definitions[node["$ref"].rsplit("/", 1)[1]]
        return node

    def has(node: Any, rest: tuple[Any, ...]) -> bool:
        node = resolve(node)
        if not rest:
            return True
        choices = [*node.get("anyOf", ()), *node.get("oneOf", ())]
        if any(has(choice, rest) for choice in choices):
            return True
        head, tail = rest[0], rest[1:]
        if isinstance(head, int):
            return "items" in node and has(node["items"], tail)
        properties = node.get("properties", {})
        return head in properties and has(properties[head], tail)

    return has(schema, path)


@pytest.mark.parametrize("path", SHOWN_FIELDS, ids=lambda path: ".".join(map(str, path)))
def test_the_example_shows_a_field_of_the_schema(path: tuple[Any, ...]) -> None:
    assert _schema_has(path)
    node: Any = _example()
    for step in path:
        node = node[step]


def test_the_agents_page_does_not_say_the_schema_page_lists_every_field() -> None:
    page = _read("docs/agents.md")
    assert "lists every field" not in page
    assert "`pairbench schema results` prints every field" in page


# --- the Python API example ----------------------------------------------------------


def test_the_api_page_names_the_reasons_its_two_round_example_gives() -> None:
    section = _section(_read("docs/reference/python-api.md"), "## Rows produced elsewhere")
    first = re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL)[0]
    scope: dict[str, Any] = {}
    exec(first, scope)

    (comparison,) = scope["results"].comparisons
    assert comparison.outcome == "no_verdict"
    assert f"`NO VERDICT ({comparison.reason})`" in section
    for reason in comparison.reasons:
        assert re.search(rf"`[^`]*\b{reason}\b[^`]*`", section), reason
