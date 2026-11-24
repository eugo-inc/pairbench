# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the short descriptions of ``E_POOL_SAME`` say.

Two different runs of one file that a reader splits into runs are two captures and pool; the
same run given twice is refused. The code's one-line description, the rows of the exit-code
reference and of the skill, and the description of ``check_pool`` with its copy in the Python
reference say so.
"""

from __future__ import annotations

from pathlib import Path

import pairbench
from pairbench import errors

MEANING = (
    "the same capture was given twice: the same id, file path or file hash, or of a file a "
    "reader splits into runs, the same run"
)
EXIT_CODES_ROW = f"| `E_POOL_SAME` | 6 | experiment | {MEANING} |"
SKILL_ROW = f"| `E_POOL_SAME` | 6 | {MEANING} |"
CHECK_POOL = (
    "the same capture, file or bytes given twice, or of a file a reader splits into runs the "
    "same run (`E_POOL_SAME`)"
)


def joined(text: str) -> str:
    """A text on one line."""
    return " ".join(text.split())


def test_the_code_s_description_names_the_run() -> None:
    assert errors.CODES["E_POOL_SAME"].meaning == MEANING


def test_the_exit_code_reference_row_names_the_run(repo_root: Path) -> None:
    text = (repo_root / "docs/reference/exit-codes.md").read_text(encoding="utf-8")
    assert EXIT_CODES_ROW in text.splitlines()


def test_the_skill_row_names_the_run(repo_root: Path) -> None:
    text = (repo_root / "skills/pairbench/references/exit-codes.md").read_text(encoding="utf-8")
    assert SKILL_ROW in text.splitlines()


def test_check_pool_names_the_run(repo_root: Path) -> None:
    doc = pairbench.check_pool.__doc__ or ""
    names = (repo_root / "docs/reference/python-names.md").read_text(encoding="utf-8")
    assert CHECK_POOL.replace("`", "``") in joined(doc)
    assert CHECK_POOL in joined(names)
