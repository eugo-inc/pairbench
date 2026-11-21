# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say that a file side's hashes take its result files as they are.

A file side's identity holds the SHA-256 of each result file it reads, taken over the file as it
is, and its fingerprint covers those hashes and the absolute path of each file. So a secret a
result file holds, such as a password in a case id that the results show hidden, is in both, and
the same files in two folders give two fingerprints. The security policy says so where it says
what results may hold and under the known limits of the hashes, and the results reference and the
config page say so where they say the hashes hide the recognised secret forms. The rows below
check what the pages say against the code with two made-up hyperfine exports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pairbench import model
from pairbench.model import LaunchSettings
from pairbench.sides.files import files_identity
from pairbench.sides.identity import KEY_FILES_SHA256

SECURITY = "SECURITY.md"
RESULTS = "docs/reference/results-schema.md"
CONFIG = "docs/reference/config.md"
HASH_LIMITS_HEADING = "## Known limits of the hashes"
RESULTS_HOLD_HEADING = "## What results may hold"
# The security policy, where it says what results may hold.
SECURITY_HOLD = (
    "A file side's `fingerprint` is the other exception: it covers each of the side's result "
    "files as it is, a secret in a case id the file holds included, as the "
    "[known limits of the hashes](#known-limits-of-the-hashes) say."
)
# The security policy, under the known limits of the hashes.
SECURITY_LIMIT = (
    "A file side's identity shows the SHA-256 of each result file the side reads, "
    "`files_sha256`, taken over the file as it is, and its fingerprint covers those hashes and "
    "the absolute path of each file. So a secret that a result file holds, such as a password in "
    "a case id that the results show hidden, is in both hashes, and the same files in two "
    "folders give two fingerprints: two exports that differ only in such a password give two "
    "values of `files_sha256` and two fingerprints. A reader who has the rest of such a file can "
    "confirm a guessed value by hashing the guess. Keep secrets out of the names a benchmark tool "
    "writes into its result files, as hyperfine's `--command-name` gives a case a name of your "
    "choosing."
)
# The results reference, after it says the hashes hide the recognised secret forms.
RESULTS_EXCEPTION = (
    "A file side is the exception: its `files_sha256` and its fingerprint cover each result file "
    "as it is, a secret in a case id included, and its fingerprint covers the absolute path of "
    "each file, as the [known limits](../../SECURITY.md#known-limits-of-the-hashes) say."
)
# The config page, after it says the hashes hide these forms.
CONFIG_EXCEPTION = (
    "A file side's result files are the exception: its fingerprint covers each file as it is, as "
    "the [known limits of the hashes](../../SECURITY.md#known-limits-of-the-hashes) say."
)
# Two made-up passwords, and the case id that holds one before a host with no user.
PASSWORDS = ("made-up-1", "made-up-2")
CASE = "bench_a[:{pw}@db.example:6379]"
SHOWN = "bench_a[:<hidden>@db.example:6379]"


def section(repo_root: Path, page: str, heading: str) -> str:
    """The section of a page under a heading, on one line."""
    text = (repo_root / page).read_text(encoding="utf-8")
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return " ".join(text[start : end if end != -1 else len(text)].split())


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


def test_the_security_policy_names_the_exception_where_results_are_described(
    repo_root: Path,
) -> None:
    assert SECURITY_HOLD in section(repo_root, SECURITY, RESULTS_HOLD_HEADING)


def test_the_security_policy_lists_the_limit_of_the_hashes(repo_root: Path) -> None:
    assert SECURITY_LIMIT in section(repo_root, SECURITY, HASH_LIMITS_HEADING)


def test_the_results_reference_names_the_exception(repo_root: Path) -> None:
    assert RESULTS_EXCEPTION in joined(repo_root, RESULTS)


def test_the_config_page_names_the_exception(repo_root: Path) -> None:
    assert CONFIG_EXCEPTION in joined(repo_root, CONFIG)


def _export(folder: Path, password: str) -> Path:
    """Write one made-up hyperfine export whose case id holds ``password`` before a host."""
    folder.mkdir(parents=True, exist_ok=True)
    measurement = {"time_wall_clock": {"value": 0.25, "unit": "second"}, "exit_code": 0}
    result = {
        "command": "true",
        "name": CASE.format(pw=password),
        "measurements": [measurement],
    }
    path = folder / "new-1.json"
    path.write_text(json.dumps({"schema_version": 2, "results": [result]}), encoding="utf-8")
    return path


def _hashes(path: Path) -> tuple[str, str]:
    """The ``files_sha256`` of a file side that reads ``path``, and its fingerprint."""
    identity = files_identity("new", [path])
    fingerprint = model.fingerprint_of(identity, LaunchSettings().effective())
    return identity[KEY_FILES_SHA256][0], fingerprint


@pytest.mark.parametrize("password", PASSWORDS)
def test_the_results_show_the_case_id_with_its_password_hidden(password: str) -> None:
    assert model.public_case(CASE.format(pw=password)) == SHOWN


def test_two_exports_that_differ_only_in_the_password_give_two_of_each_hash(
    tmp_path: Path,
) -> None:
    first = _hashes(_export(tmp_path / "a", PASSWORDS[0]))
    second = _hashes(_export(tmp_path / "b", PASSWORDS[1]))
    # Moved to one folder each, the paths differ too, so compare files in one folder as well.
    same_folder = _hashes(_export(tmp_path / "a", PASSWORDS[1]))

    assert first[0] != second[0]
    assert first[0] != same_folder[0]
    assert first[1] != same_folder[1]


def test_the_same_export_in_two_folders_gives_one_file_hash_and_two_fingerprints(
    tmp_path: Path,
) -> None:
    first = _hashes(_export(tmp_path / "a", PASSWORDS[0]))
    second = _hashes(_export(tmp_path / "b", PASSWORDS[0]))

    assert first[0] == second[0]
    assert first[1] != second[1]
