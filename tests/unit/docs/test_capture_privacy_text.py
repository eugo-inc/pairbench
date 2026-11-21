# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the pages say about sharing the capture, and that the capture keeps what they say.

The capture keeps the command line as typed: the value of a credential-like option stays in
it, and only the value of a credential-like environment variable set with ``--set`` is
replaced. The page that lists the files of a run folder, the concepts page, the agent skill,
the agent page and the security policy each say so, and the agent rules name the files to
share instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pairbench.model import REDACTED, redact_argv

ROOT = Path(__file__).resolve().parents[3]
AS_TYPED = "keeps the command line as typed, credentials included"
SHARED_FILES = ("`results.json`", "`results.md`", "`report.html`")


def _text(relative: str) -> str:
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def test_the_run_folder_page_says_the_capture_keeps_credentials_and_is_never_shared() -> None:
    page = (ROOT / "docs/reference/results-schema.md").read_text(encoding="utf-8")
    row = next(line for line in page.splitlines() if line.startswith("| `capture.jsonl` |"))
    assert AS_TYPED in row
    assert "never share it" in row
    after = _text("docs/reference/results-schema.md")
    sentence = re.search(r"The files to share are (.+?): ", after)
    assert sentence is not None
    assert [name for name in SHARED_FILES if name not in sentence[1]] == []


def test_the_concepts_page_says_the_capture_keeps_credentials_and_is_never_shared() -> None:
    text = _text("docs/concepts.md")
    assert f"It {AS_TYPED}, so it is never shared" in text


@pytest.mark.parametrize("relative", ["skills/pairbench/SKILL.md", "docs/agents.md"])
def test_the_agent_rules_say_which_files_to_share_and_never_the_capture(relative: str) -> None:
    text = _text(relative)
    rule = next(line for line in text.split("- ") if "`capture.jsonl`" in line)
    assert "Never share `capture.jsonl`" in rule
    assert AS_TYPED in rule
    assert [name for name in SHARED_FILES if name not in rule] == []


def test_the_security_policy_says_the_capture_keeps_credentials_and_is_not_shared() -> None:
    text = _text("SECURITY.md")
    assert "The capture and the diagnostics are for the person who ran the benchmark" in text
    assert f"the capture {AS_TYPED}" in text


def test_the_recorded_command_line_keeps_credential_options_and_hides_set_variables() -> None:
    argv = (
        "pairbench",
        "run",
        "--side",
        "new=cmd:tool --token zqmkzz",
        "--set",
        "launch.env.API_TOKEN=zqmkzy",
        "--",
        "curl",
        "-H",
        "Authorization: Bearer zqmkzx",
    )
    assert redact_argv(argv) == (
        *argv[:5],
        f"launch.env.API_TOKEN={REDACTED}",
        *argv[6:],
    )
