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
    TwinCheck,
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
from pairbench.stats import holm, sign_test
from pairbench.stats.rules import TWIN_NOTE_ALPHA, _round_sign

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


def test_the_skill_says_what_each_mode_does_when_a_readiness_check_fails() -> None:
    (rule,) = [
        item
        for item in _read("skills/pairbench/references/sides.md").split("\n- ")
        if item.startswith("The readiness checks")
    ]
    text = " ".join(rule.split())
    assert "hold a run" not in text
    for said in (
        "Under the default `--gates warn` the run goes on and its results are stamped `busy`",
        "`--wait-quiet` waits for them",
        "`--gates enforce` stops the run (exit 4)",
        "`--gates off` skips them",
    ):
        assert said in text, said


def test_the_method_page_says_a_slow_read_can_end_the_quiet_wait_later() -> None:
    text = " ".join(_read("docs/method/shared-machines.md").split())
    assert "within `gates.quiet.max_wait_s`" not in text
    assert (
        "The time is looked at after each sample, so a slow read, such as a readiness check "
        "that waits on `nvidia-smi`, can end the wait later than that."
    ) in text


def test_the_config_page_says_a_slow_read_can_end_the_quiet_wait_later() -> None:
    meaning = _row(_read("docs/reference/config.md"), "`gates.quiet.max_wait_s`").split("|")[3]
    assert meaning.strip() == (
        "the longest wait, then the check fails; the time is looked at after each sample, "
        "so a slow read can end the wait later"
    )


# --- outcome words -------------------------------------------------------------------


def test_the_skill_says_which_p_value_grades_a_better_or_worse_case() -> None:
    page = _read("skills/pairbench/references/results.md")
    row = _row(_section(page, "## Outcomes"), "`better` / `worse`")
    assert "secondary case" in row
    assert "corrected p-value" in row and "uncorrected p-value" in row
    assert "`p_source` is `raw`" in row


def test_the_pages_say_the_twin_note_comes_from_one_combined_check_per_side() -> None:
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert (
        "Each side with a twin gets one combined check against it, kept in `twin_checks`" in noise
    )
    assert "corrected together with [Holm's method](multiple-comparisons.md)" in noise
    assert "`twin_differs`" in noise
    family = " ".join(
        _section(_read("docs/method/multiple-comparisons.md"), "## What the family is").split()
    )
    assert "each side gets one combined check across its primary cases" in family
    assert "`twin_checks`" in family
    controls = " ".join(_read("docs/method/instrument-controls.md").split())
    assert "in one combined check per side corrected for the number of sides tested" in controls
    skill = _read("skills/pairbench/references/results.md")
    assert "the correction for testing every side that has a twin" in _row(skill, "`twin_checks[]`")
    assert "uncorrected p-value" in _row(skill, "`same_vs_same[].p_raw`")
    notes = _row(skill, "`notes[]`")
    assert "`twin_differs` when a side's combined check has a corrected p-value below 0.05" in notes
    schema_page = " ".join(_read("docs/reference/results-schema.md").split())
    assert "`twin_checks[]` holds one combined check per side that has a twin" in schema_page


def test_the_noise_floor_page_says_how_many_untied_rounds_the_twin_note_needs() -> None:
    # The page's numbers, from the sign test and the correction the check uses.
    five, six, seven, eight = (sign_test(0, n).p for n in (5, 6, 7, 8))
    assert five == 1 / 16 >= TWIN_NOTE_ALPHA > six == 1 / 32
    assert holm([seven, six]) == [4 / 128, 4 / 128]
    assert holm([six, six]) == [1 / 16, 1 / 16]
    assert holm([eight] * 6)[0] < TWIN_NOTE_ALPHA <= holm([eight] * 7)[0] == 14 / 256
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert (
        "The smallest p-value of a side over `n` untied rounds is `2 / 2^n`, below 0.05 only"
        " from 6 untied rounds on, and the correction never lowers it, so no side gets the note"
        " with fewer than 6." in noise
    )
    assert (
        "The correction multiplies the smallest p-value of the run by the number of sides"
        " tested, the next smallest by one fewer, and so on, and never makes a corrected"
        " p-value smaller than the one before it, so a side gets the note only when every side"
        " with a smaller p-value gets it too." in noise
    )
    assert (
        "With two sides tested, the side with the smaller p-value needs at least 7 untied"
        " rounds, and the other can get the note with 6 that all lean one way when the first"
        " gets it too: 7 of 7 and 6 of 6 both give a corrected p-value of 4/128, about 0.031."
        in noise
    )
    assert (
        "At 8 rounds, the serving default, it can reach at most 6 sides: with 7 sides tested,"
        " even a side with 8 of 8 gets a corrected p-value of at least 14/256, about 0.055."
        in noise
    )
    assert "at least 7 when two are" not in noise


def test_the_pages_say_at_eight_rounds_the_twin_note_needs_every_untied_round_to_agree() -> None:
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert (
        "At 8 rounds the note comes only when every round of the side that is not a tie leans"
        " the same way" in noise
    )
    assert "8 of 8 give a corrected p-value of 4/256, about 0.016" in noise
    assert (
        "7 one way and 1 the other never give the note: their raw p-value is 18/256, about"
        " 0.07, and the correction never makes a p-value smaller (it gives 36/256, about 0.14,"
        " when the other side's p-value is no smaller)" in noise
    )
    assert (
        "as a verdict at 8 rounds comes only when every round that is not a tie agrees (all 8"
        " when none tie)." in noise
    )
    assert "needs all 8 rounds to agree" not in noise
    # 7 rounds that agree and 1 tie give 2/128 by themselves; 7 one way and 1 the other 18/256.
    assert sign_test(0, 7).p == 2 / 128 < TWIN_NOTE_ALPHA
    assert sign_test(1, 7).p == 18 / 256
    assert (
        "the note means that all of a side's untied rounds agreed, and its absence says nothing"
        " more" in noise
    )
    family = " ".join(
        _section(_read("docs/method/multiple-comparisons.md"), "## What the family is").split()
    )
    assert "at 8 rounds the note comes only when every untied round of the side leans" in family
    skill = _read("skills/pairbench/references/results.md")
    assert "at 8 rounds, the serving default, the note needs every untied round" in _row(
        skill, "`twin_checks[]`"
    )


def test_the_noise_floor_page_says_the_sign_of_a_round_is_found_exactly() -> None:
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert "The cases are put in order by their turned quotients, compared exactly" in noise
    assert (
        "the sign of a score is found exactly, from whether the middle quotient, or the product"
        " of the two middle quotients, is above, below or equal to 1" in noise
    )
    assert (
        "Swapping a side and its twin in one round turns each of its quotients over, so the same"
        " cases lie in the middle: that round turns the other way and the others stay as they"
        " were." in noise
    )


MEDIAN_WORDS = (
    "is the median over the primary cases on which the side and its twin both have a finite"
    " value above zero",
    "gives the log in the middle",
    "an even number the mean of the two in the middle",
)


def test_the_twin_check_docstring_and_schema_text_say_a_round_is_scored_by_the_median() -> None:
    doc = " ".join((TwinCheck.__doc__ or "").split())
    text = load_schema("results")["$defs"]["TwinCheck"]["description"]
    assert [words for words in MEDIAN_WORDS if words not in doc] == []
    assert [words for words in MEDIAN_WORDS if words not in text] == []
    assert text.endswith(
        "in a side with three or more primary cases it moves a round of the combined check only"
        " when other primary cases lean the same way."
    )


def test_the_round_sign_docstring_says_it_signs_the_middle_of_a_round() -> None:
    doc = " ".join((_round_sign.__doc__ or "").split())
    assert doc.startswith(
        "Return the sign of the mean of the turned logs of the ``(side, twin, better)`` values"
        " given."
    )
    assert "the middle value of a round, or its two middle values" in doc
    assert "so the sign is that of the round's median" in doc
    assert "a round's score" not in doc


def test_the_pages_say_what_the_twin_note_can_and_cannot_catch() -> None:
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert (
        "In each round the side's score is the median over its primary cases on which the side"
        " and its twin both have a finite value above zero in that round." in noise
    )
    assert (
        "An odd number of such cases gives the log in the middle, and an even number the mean of"
        " the two logs in the middle, so one case gives its own log and two give their mean."
        in noise
    )
    assert (
        "What the note can catch: a bias that moves most primary cases of a side the same way"
        in noise
    )
    assert (
        "such a bias is caught whether or not one of the side's cases is much noisier than the"
        " rest" in noise
    )
    assert (
        "and more often still when one of its three cases is much noisier: a round then leans"
        " with the bias mostly when both other cases do." in noise
    )
    assert (
        "A side with three primary cases misses such a bias more often than one with more, as"
        " the median of each round then rests on fewer cases. When the bias is large beside the"
        " noise, so that a side with five or more primary cases rarely misses it, one with three"
        " can miss it many times as often," in noise
    )
    assert "a little more often" not in noise
    assert (
        "It moves the median of a round only when other cases lean the same way by chance; with"
        " an odd number of cases, at least half of the others." in noise
    )
    assert (
        "It gives it more often the fewer primary cases the side has and the more rounds the run"
        " has" in noise
    )
    assert "It still shows in the same-against-same table of the reports" in noise
    assert (
        "A side with one primary case is scored on that case alone, and one with two on their"
        " mean, so there a difference on one case can give the note by itself." in noise
    )
    assert (
        "A bias shared by half or fewer of the cases, two of five say, also moves a round only"
        " when enough of the others lean the same way by chance" in noise
    )
    schema_page = " ".join(_read("docs/reference/results-schema.md").split())
    assert (
        "the rounds whose median turned log of side over twin across those cases says the side"
        " looks better or worse" in schema_page
    )
    assert (
        "where, in a side with three or more primary cases, it moves a round only when other"
        " primary cases of the side lean the same way" in schema_page
    )
    skill = _read("skills/pairbench/references/results.md")
    row = _row(skill, "`twin_checks[]`")
    assert "each round scored by the median of their turned logs, side over twin" in row


def test_the_noise_floor_page_says_a_difference_on_one_case_gives_the_note_less_often() -> None:
    noise = " ".join(_read("docs/method/noise-floor.md").split())
    assert (
        "What it catches less often: a difference on one case alone, in a side with three or"
        " more primary cases." in noise
    )
    assert (
        "it gives the note less often than the same difference on every primary case of the"
        " side would, in any run with enough untied rounds for the note." in noise
    )
    assert (
        "so in a side with three primary cases and a long run it can give the note in most"
        " runs." in noise
    )
    for words in ("seldom", "far less often", "a good share"):
        assert words not in noise, words


# --- the results example -----------------------------------------------------------

# Fields the example on the schema page shows, by their place in the document.
SHOWN_FIELDS = (
    ("provenance", "driver"),
    ("sides", 0, "image_ref"),
    ("sides", 0, "identity", "platform"),
    ("machine_state", "discard_sha256"),
    ("comparisons", 0, "sensitivity", "not_computed"),
    ("same_vs_same", 0, "unit"),
    ("twin_checks", 0, "n_better"),
    ("twin_checks", 0, "p_corrected"),
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


def _pool_paragraph(section: str, opening: str) -> str:
    start = section.index(opening)
    end = section.find("\n\n", start)
    return " ".join(section[start : end if end != -1 else len(section)].split())


def test_the_api_page_names_every_code_check_pool_gives_a_capture_with_other_sides() -> None:
    import dataclasses

    import pairbench
    from pairbench.model import CpuRecord
    from pairbench.stats.selftest import MATMUL, synthetic_capture

    def value(entry: str, case: str, round_: int, u: float) -> float:
        return (2.0 if entry.startswith("new") else 1.0) * (1 + round_ / 64) * (1 + u / 1000)

    first = synthetic_capture(value, capture_id="synthetic-a", seed=1)
    other = synthetic_capture(
        value,
        capture_id="synthetic-b",
        seed=2,
        subjects=("new", "other"),
        cases=(dataclasses.replace(MATMUL, unit="ms"),),
    )
    assert first.machine is not None
    other = dataclasses.replace(
        other, machine=dataclasses.replace(first.machine, cpu=CpuRecord(model="cpu-model-b"))
    )
    codes = [refusal.code for refusal in pairbench.check_pool([first, other])]
    assert codes == ["E_POOL_SIDE_DRIFT", "E_POOL_CASES", "E_POOL_MACHINE"]

    section = _section(_read("docs/reference/python-api.md"), "## Checking a pool")
    paragraph = _pool_paragraph(section, "Each pair of captures gives at most one")
    assert "not checked further" not in paragraph
    for code in codes:
        assert f"`{code}`" in paragraph, code


def test_the_api_page_says_when_the_first_entry_of_check_pool_is_what_analyse_raises() -> None:
    section = _section(_read("docs/reference/python-api.md"), "## Checking a pool")
    opening = " ".join(section[: section.index("| Text code |")].split())
    assert "so its first entry is the refusal" not in opening
    assert "when each capture is complete or `allow_incomplete=True` is given" in opening
    assert "`E_CAPTURE_INCOMPLETE`" in opening


def test_every_docstring_of_check_pool_says_analyse_can_refuse_an_incomplete_capture_first() -> (
    None
):
    import pairbench
    from pairbench.api import CheckPool
    from pairbench.stats.analyse import pool_refusals

    for documented in (pairbench.check_pool, pool_refusals, CheckPool):
        assert "E_CAPTURE_INCOMPLETE" in (documented.__doc__ or ""), documented


def test_the_load_capture_docstring_says_a_missing_cell_is_a_note_not_a_refusal() -> None:
    import pairbench

    doc = " ".join((pairbench.load_capture.__doc__ or "").split())
    assert "refusal of scope" not in doc
    assert "the capture notes as ``value_not_finite``, one note per cell" in doc
    assert "``refusals`` stays empty" in doc
    page = " ".join(_read("docs/reference/python-names.md").split())
    assert "refusal of scope `case`" not in page
    assert "the capture notes as `value_not_finite`, one note per cell" in page
