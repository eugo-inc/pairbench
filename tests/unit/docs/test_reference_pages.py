# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The reference pages and the code say the same thing.

Every text code and exit code is documented with its exit code; every flag
of every command is in the command reference and every flag there exists;
every config key is in the config reference and every key there exists;
every reason a comparison can carry is on the verdicts page and in the skill.
"""

from __future__ import annotations

import argparse
import importlib
import re
from pathlib import Path

import pytest

from pairbench import errors
from pairbench.cli.main import COMMANDS, parser_for
from pairbench.model import CONFIG_KEYS, REASONS, REASONS_NO_VERDICT, REASONS_UNRESOLVED

EXIT_CODES_PAGE = "docs/reference/exit-codes.md"
COMMANDS_PAGE = "docs/reference/commands.md"
CONFIG_PAGE = "docs/reference/config.md"
SKILL_EXIT_CODES = "skills/pairbench/references/exit-codes.md"
VERDICTS_PAGE = "docs/method/verdicts.md"
SKILL_RESULTS = "skills/pairbench/references/results.md"
REASON_ROW = re.compile(r"^\| `([a-z_]+)` \| ", re.MULTILINE)

FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
CODE_ROW = re.compile(r"^\| `(E_[A-Z_]+)` \| ([0-9 or]+) \|", re.MULTILINE)
# A row of the page's table of text codes: the code, its exit codes and its scopes.
CODE_SCOPE_ROW = re.compile(r"^\| `(E_[A-Z_]+)` \| [0-9 or]+ \| ([a-z or]+) \|", re.MULTILINE)
EXIT_ROW = re.compile(r"^\| (\d+) \| ", re.MULTILINE)
# A row of the skill's table of text codes: the code, its exit codes and its meaning.
SKILL_CODE_MEANING = re.compile(r"^\| `(E_[A-Z_]+)` \| [0-9 or]+ \| (.*?) \|$", re.MULTILINE)
KEY_CELL = re.compile(r"`([a-z_]+(?:\.[A-Za-z_]+)+)`")
# Flags argparse adds by itself, and the flag that only separates the workload.
NOT_DOCUMENTED = frozenset({"--help"})
# Every ending signal ends a command with exit code 130, the code of an interrupt, not the
# code a shell gives a program that signal ends.
SIGNAL_EXIT = (
    "The exit code is 130 for each of them, not 128 plus the signal's number, which a shell "
    "reports for a program a signal ends (143 for `SIGTERM`, 129 for `SIGHUP`, 131 for "
    "`SIGQUIT`): the tool catches the signal and ends the command itself."
)
SKILL_SIGNAL_EXIT_ROW = (
    "| 130 | interrupted: Ctrl-C, `SIGTERM`, `SIGHUP` or `SIGQUIT`, each with 130, not 128 plus "
    "the signal's number (143 for `SIGTERM`) | the capture is marked `interrupted` |"
)
# The command whose section says it takes every flag of another command.
SAME_FLAGS_AS = {"plan": "run"}


def page(repo_root: Path, name: str) -> str:
    return (repo_root / name).read_text(encoding="utf-8")


def sections(text: str) -> dict[str, str]:
    """The text of each ``## name`` section of a page, by name."""
    found: dict[str, str] = {}
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        found[title.strip()] = body
    return found


def parser_flags(command: str) -> set[str]:
    """Every long flag the parser of ``command`` and its subcommands accept."""
    module_name, about = COMMANDS[command]
    module = importlib.import_module(module_name)
    parser = parser_for(command, about)
    module.add_arguments(parser)
    flags: set[str] = set()
    pending: list[argparse.ArgumentParser] = [parser]
    while pending:
        current = pending.pop()
        for action in current._actions:
            flags.update(name for name in action.option_strings if name.startswith("--"))
            if isinstance(action, argparse._SubParsersAction):
                pending.extend(action.choices.values())
    return flags - NOT_DOCUMENTED


def parser_subcommands(command: str) -> list[str]:
    """The subcommands the parser of ``command`` takes, such as ``check`` of ``gate``."""
    module_name, about = COMMANDS[command]
    parser = parser_for(command, about)
    importlib.import_module(module_name).add_arguments(parser)
    return [
        name
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
        for name in action.choices
    ]


def test_every_text_code_is_documented_with_its_exit_code(repo_root: Path) -> None:
    rows = dict(CODE_ROW.findall(page(repo_root, EXIT_CODES_PAGE)))

    assert sorted(rows) == sorted(errors.CODES)
    for code, entry in errors.CODES.items():
        documented = {int(number) for number in re.findall(r"\d+", rows[code])}
        assert documented == {entry.exit_code, *entry.also}, code


def test_every_text_code_is_documented_with_its_scopes(repo_root: Path) -> None:
    rows = dict(CODE_SCOPE_ROW.findall(page(repo_root, EXIT_CODES_PAGE)))

    assert {code: tuple(rows.get(code, "").split(" or ")) for code in errors.CODES} == {
        code: entry.scopes for code, entry in errors.CODES.items()
    }


def test_every_exit_code_is_documented(repo_root: Path) -> None:
    rows = {int(number) for number in EXIT_ROW.findall(page(repo_root, EXIT_CODES_PAGE))}

    assert rows == set(errors.EXIT_CODES)


def test_an_ending_signal_is_documented_to_exit_with_130(repo_root: Path) -> None:
    text = page(repo_root, EXIT_CODES_PAGE)
    entry = text.split("### Exit code 130\n", 1)[1].split("\n#", 1)[0]
    rows = [
        line
        for line in page(repo_root, SKILL_EXIT_CODES).splitlines()
        if line.startswith("| 130 |")
    ]

    assert SIGNAL_EXIT in " ".join(entry.split())
    assert rows == [SKILL_SIGNAL_EXIT_ROW]


def test_the_skill_names_every_text_code(repo_root: Path) -> None:
    text = page(repo_root, SKILL_EXIT_CODES)

    assert [code for code in errors.CODES if f"`{code}`" not in text] == []


def test_the_skill_gives_each_text_code_the_meaning_the_code_gives_it(repo_root: Path) -> None:
    rows = dict(SKILL_CODE_MEANING.findall(page(repo_root, SKILL_EXIT_CODES)))

    assert {code: rows.get(code) for code in errors.CODES} == {
        code: entry.meaning for code, entry in errors.CODES.items()
    }


def test_every_reason_is_on_the_verdicts_page_and_in_the_skill(repo_root: Path) -> None:
    verdicts = page(repo_root, VERDICTS_PAGE)
    # The table lists the reasons in the order that picks the main one, under a heading row.
    no_verdict = REASON_ROW.findall(sections(verdicts)["Reasons for NO VERDICT"])
    assert no_verdict == ["reason", *REASONS_NO_VERDICT]
    assert [r for r in REASONS if f"`{r}`" not in verdicts] == []
    skill = set(REASON_ROW.findall(page(repo_root, SKILL_RESULTS)))
    assert [r for r in (*REASONS_UNRESOLVED, *REASONS_NO_VERDICT) if r not in skill] == []


def test_the_command_reference_has_a_section_for_every_command(repo_root: Path) -> None:
    assert sorted(sections(page(repo_root, COMMANDS_PAGE))) == sorted(COMMANDS)


def test_every_subcommand_has_its_own_heading_in_its_command_section(repo_root: Path) -> None:
    text = sections(page(repo_root, COMMANDS_PAGE))
    expected = [f"{c} {s}" for c in sorted(COMMANDS) for s in parser_subcommands(c)]
    missing = [n for n in expected if f"\n### {n}\n" not in text[n.split(" ")[0]]]

    assert {"gate check", "gate wait-quiet", "skill install"} <= set(expected)
    assert missing == []


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_every_flag_of_a_command_is_documented_and_exists(repo_root: Path, command: str) -> None:
    text = sections(page(repo_root, COMMANDS_PAGE))
    body = text[SAME_FLAGS_AS.get(command, command)]
    documented = set(FLAG.findall(body))
    if command in SAME_FLAGS_AS:
        documented |= set(FLAG.findall(text[command]))

    accepted = parser_flags(command)

    assert sorted(accepted - documented) == []
    assert sorted(documented - accepted) == []


def test_the_flag_scan_reads_a_table_row() -> None:
    row = "| `--fail-on OUTCOME` | `rule.fail_on` | repeated; also `--no-plugins` |"

    assert FLAG.findall(row) == ["--fail-on", "--no-plugins"]
    assert FLAG.findall("pairbench run -- python bench.py") == []


def test_every_config_key_is_documented_and_exists(repo_root: Path) -> None:
    text = page(repo_root, CONFIG_PAGE)
    keys_section = text.split("## Keys", 1)[1]
    documented: set[str] = set()
    for line in keys_section.splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            documented.update(KEY_CELL.findall(first_cell))

    assert sorted(set(CONFIG_KEYS) - documented) == []
    assert sorted(documented - set(CONFIG_KEYS)) == []


def test_every_config_key_a_flag_sets_is_a_config_key(repo_root: Path) -> None:
    body = sections(page(repo_root, COMMANDS_PAGE))["run"]
    named: set[str] = set()
    for line in body.splitlines():
        cells = line.split("|")
        if line.startswith("| `-") and len(cells) > 3:
            named.update(KEY_CELL.findall(cells[2]))

    assert named
    assert sorted(named - set(CONFIG_KEYS) - {"sides.NAME"}) == []


AGENT_PAGES = (
    "docs/agents.md",
    "docs/reference/results-schema.md",
    SKILL_EXIT_CODES,
    SKILL_RESULTS,
    "skills/pairbench/SKILL.md",
)
NAMED_CODE = re.compile(r"(?<![A-Z0-9_])E_[A-Z][A-Z0-9_]*(?![A-Z0-9_])")


@pytest.mark.parametrize("name", AGENT_PAGES)
def test_the_agent_pages_name_only_text_codes_the_tool_has(repo_root: Path, name: str) -> None:
    named = set(NAMED_CODE.findall(page(repo_root, name))) - {"E_CODE"}
    assert sorted(named - set(errors.CODES)) == []


@pytest.mark.parametrize("name", AGENT_PAGES)
def test_the_agent_pages_say_a_refusal_is_a_refused_run(repo_root: Path, name: str) -> None:
    text = " ".join(page(repo_root, name).split())
    assert "beside the comparisons" not in text
    assert "can stand beside" not in text
