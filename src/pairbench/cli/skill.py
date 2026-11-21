# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench skill install --dir PATH``: copy the agent skill into a folder.

``--dir`` is required: there is no default folder. The skill is copied into
``PATH/pairbench``. A folder of that name that already holds files is left
as it is and the copy is refused.
"""

from __future__ import annotations

import argparse
import importlib.resources
import shutil
from pathlib import Path
from typing import Any, Final

from pairbench.cli.common import emit
from pairbench.errors import EXIT_OK, Refusal

SKILL_NAME: Final = "pairbench"
SKILL_FILE: Final = "SKILL.md"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``install --dir PATH``."""
    actions = parser.add_subparsers(dest="action", metavar="install")
    actions.required = True
    install = actions.add_parser("install", help="copy the skill into a folder", allow_abbrev=False)
    install.add_argument(
        "--dir", dest="folder", metavar="PATH", help="the folder that holds your agent's skills"
    )


def skill_source() -> Any:
    """The skill as this installation carries it: package data in a wheel, or the source tree."""
    packaged = importlib.resources.files("pairbench") / "skill"
    if packaged.is_dir() and (packaged / SKILL_FILE).is_file():
        return packaged
    tree = Path(__file__).resolve().parents[3] / "skills" / SKILL_NAME
    if (tree / SKILL_FILE).is_file():
        return tree
    raise Refusal("E_INTERNAL", "this installation carries no agent skill")


def _copy(source: Any, target: Path) -> list[str]:
    """Copy a folder of the package (or of the source tree) file by file."""
    copied: list[str] = []
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda entry: entry.name):
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        if item.is_dir():
            copied += [f"{item.name}/{name}" for name in _copy(item, target / item.name)]
        else:
            (target / item.name).write_bytes(item.read_bytes())
            copied.append(item.name)
    return copied


def command(options: argparse.Namespace) -> int:
    """Copy the skill into ``--dir``/pairbench and list the files copied."""
    if not options.folder:
        raise Refusal(
            "E_USAGE",
            "skill install needs --dir PATH, the folder that holds your agent's skills; "
            "there is no default folder",
        )
    target = Path(options.folder) / SKILL_NAME
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise Refusal(
            "E_USAGE",
            f"{target.name} already exists in {Path(options.folder).name or options.folder}; "
            "remove it first to install the skill again",
        )
    source = skill_source()
    try:
        files = _copy(source, target)
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise Refusal("E_USAGE", f"cannot copy the skill: {exc.strerror or exc}") from exc
    emit("\n".join(f"{SKILL_NAME}/{name}" for name in files))
    return EXIT_OK


__all__ = ["SKILL_NAME", "add_arguments", "command", "skill_source"]
