# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Hashing a side's identity, the identify command and the identity of an interpreter."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_SIDE, Refusal
from pairbench.model import HASH_PATTERN
from pairbench.sides.base import Completed, run_command
from pairbench.sides.identity import (
    argv_sha256,
    digest_hashes,
    packages_sha256,
    python_identity,
    run_identify,
    sha256_file,
)

# SHA-256 of the three bytes "abc".
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
# SHA-256 of the canonical JSON text ["a","b"].
AB_ARGV_SHA256 = "0473ef2dc0d324ab659d3580c1134e9d812035905c4781fdd6d529b0c6860e13"
# SHA-256 of "a==1\nb==2".
AB_PACKAGES_SHA256 = "76457601f3989b696f764fe654a98acb7396d4db67fc3c100cce7b2e11acca15"
# SHA-256 of "v1\n".
V1_SHA256 = "2d27fbdf4e8ca207afbfa388ca9172fbcc6c70e534af2476b3b704f87debadcf"
DIGEST = "sha256:" + "ab" * 32


def test_a_file_is_hashed_by_its_bytes(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert sha256_file(path) == ABC_SHA256


def test_an_argument_list_is_hashed_by_its_canonical_json() -> None:
    assert argv_sha256(["a", "b"]) == AB_ARGV_SHA256


def test_the_package_hash_does_not_depend_on_order_or_repeats() -> None:
    assert packages_sha256(["b==2", "a==1", "a==1"]) == AB_PACKAGES_SHA256


def test_digests_keep_only_the_hash_without_registry_or_repository() -> None:
    found = digest_hashes(
        [
            "registry.example/team/app@" + DIGEST,
            "mirror.example/app@" + DIGEST,
            "app@not-a-hash",
        ]
    )
    assert found == [DIGEST]


def _answer(rc: int = 0, stdout: str = "", timed_out: bool = False) -> Any:
    def handler(argv: tuple[str, ...]) -> Completed:
        return Completed(rc=rc, stdout=stdout, stderr="made-up error", timed_out=timed_out)

    return handler


def test_the_identify_output_stays_in_the_capture_and_its_hash_goes_to_the_results(
    fake_runner: Any,
) -> None:
    runner = fake_runner(_answer(stdout="v1\n"))
    found = run_identify(runner, ["/made/up/bin/version"], side="new", timeout_s=5.0)
    assert found == {"identify_output": "v1\n", "identify_sha256": V1_SHA256}
    assert runner.calls[0].timeout_s == 5.0


@pytest.mark.parametrize(
    "answer",
    [
        _answer(stdout=""),
        _answer(stdout="  \n\t"),
        _answer(rc=1, stdout="v1\n"),
        _answer(rc=-9, stdout="v1\n", timed_out=True),
    ],
    ids=["empty", "white-space", "non-zero", "timeout"],
)
def test_an_identify_command_without_output_or_with_a_failure_is_refused(
    fake_runner: Any, answer: Any
) -> None:
    with pytest.raises(Refusal) as caught:
        run_identify(fake_runner(answer), ["/made/up/bin/version"], side="new")
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)
    assert "'new'" in caught.value.message
    assert "/made/up/bin" not in caught.value.message


def _interpreter(version: str, listing: str, listing_rc: int = 0) -> Any:
    def handler(argv: tuple[str, ...]) -> Completed:
        if argv[1:] == ("-VV",):
            return Completed(rc=0, stdout=version)
        return Completed(rc=listing_rc, stdout=listing)

    return handler


def test_an_interpreter_reports_its_version_line_prefix_and_package_hash(fake_runner: Any) -> None:
    listing = json.dumps({"prefix": "/made/up/env", "dists": ["b==2", "a==1"]})
    runner = fake_runner(_interpreter("Python 3.99.0 (made-up build)\n", listing))
    found = python_identity(runner, "/made/up/env/bin/python", side="new", env={"A": "1"})
    assert found == {
        "python_version": "Python 3.99.0 (made-up build)",
        "packages_sha256": AB_PACKAGES_SHA256,
        "prefix": "/made/up/env",
    }
    assert [call.env for call in runner.calls] == [{"A": "1"}, {"A": "1"}]


@pytest.mark.parametrize(
    "handler",
    [
        _interpreter("", "{}"),
        _interpreter("Python 3.99.0\n", "not json"),
        _interpreter("Python 3.99.0\n", json.dumps({"prefix": "/p", "dists": [1]})),
        _interpreter("Python 3.99.0\n", json.dumps({"prefix": "/p", "dists": []}), listing_rc=1),
    ],
    ids=["no-version", "not-json", "not-texts", "listing-failed"],
)
def test_an_interpreter_that_cannot_answer_is_refused(fake_runner: Any, handler: Any) -> None:
    with pytest.raises(Refusal) as caught:
        python_identity(fake_runner(handler), "/made/up/python", side="new")
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)


def test_the_identity_script_runs_on_this_interpreter() -> None:
    found = python_identity(run_command, sys.executable, side="new", env=dict(os.environ))
    assert found["python_version"].startswith("Python 3.")
    assert found["prefix"] == sys.prefix
    assert re.search(HASH_PATTERN, found["packages_sha256"])
