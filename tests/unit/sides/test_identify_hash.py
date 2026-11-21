# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The output of the identify command is hashed with its credentials hidden, and nothing else.

``identify_sha256`` and a side's fingerprint are both taken over the output of
the ``launch.identify`` command. Each line of it is read by the name rules of
the shown command: a credential-like name given a value, the value after a
credential-like option, a credential header and the user part of an address
are replaced by ``<hidden>``. No rule of shape applies, since an identify
command prints what tells one build from another: a checksum, a build id and
the pin of a package whose name reads like a credential stay in the hash. So
two outputs that differ only in a credential give one hash, and any other
change still gives another. The capture keeps the output as it was printed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pairbench import model
from pairbench.model import LaunchSettings, fingerprint_of
from pairbench.sides.base import Completed
from pairbench.sides.identity import run_identify

# Two made-up tokens, and the made-up identify outputs around them.
SECRET = "kiwi7"
OTHER = "plum4"
ASSIGNED = "API_TOKEN={}\nmade-up-tool 1.2\n"
HEADER = "Authorization: Bearer {}\nmade-up-tool 1.2\n"
# SHA-256 of "API_TOKEN=<hidden>\nmade-up-tool 1.2\n".
ASSIGNED_SHA256 = "02611f029e77d5243b687a4b84b0f1efa486fc4a2845c8caf1374a3dd0eea3fe"
# SHA-256 of "Authorization: <hidden>\nmade-up-tool 1.2\n".
HEADER_SHA256 = "adaf47c45832998b56b0daf0cce6a43e5cab1c196fb325899ba44db3fe52fbbe"
IDENTIFY = ["/made/up/bin/version"]


def _identify(fake_runner: Callable[..., Any], output: str) -> dict[str, str]:
    def answer(argv: tuple[str, ...]) -> Completed:
        return Completed(rc=0, stdout=output)

    return run_identify(fake_runner(answer), IDENTIFY, side="new")


def _fingerprint(output: str) -> str:
    identity = {"executable_sha256": "e" * 64, "identify_output": output}
    return fingerprint_of(identity, LaunchSettings().effective(args=["made-up-tool"]))


@pytest.mark.parametrize(
    ("form", "expected"), [(ASSIGNED, ASSIGNED_SHA256), (HEADER, HEADER_SHA256)]
)
def test_a_secret_in_the_identify_output_is_hidden_from_its_hash(
    fake_runner: Callable[..., Any], form: str, expected: str
) -> None:
    one = _identify(fake_runner, form.format(SECRET))
    two = _identify(fake_runner, form.format(OTHER))

    assert one["identify_sha256"] == expected
    assert two["identify_sha256"] == expected


def test_the_capture_keeps_the_identify_output_as_printed(
    fake_runner: Callable[..., Any],
) -> None:
    found = _identify(fake_runner, ASSIGNED.format(SECRET))

    assert found["identify_output"] == "API_TOKEN=kiwi7\nmade-up-tool 1.2\n"


@pytest.mark.parametrize("form", [ASSIGNED, HEADER])
def test_a_secret_in_the_identify_output_is_hidden_from_the_fingerprint(form: str) -> None:
    assert _fingerprint(form.format(SECRET)) == _fingerprint(form.format(OTHER))


@pytest.mark.parametrize("form", [ASSIGNED, HEADER])
def test_an_ordinary_change_in_the_identify_output_still_changes_both_hashes(
    fake_runner: Callable[..., Any], form: str
) -> None:
    before = form.format(SECRET)
    after = before.replace("1.2", "1.3")

    assert _identify(fake_runner, before) != _identify(fake_runner, after)
    assert _fingerprint(before) != _fingerprint(after)


def test_a_header_hides_only_its_own_line() -> None:
    assert (
        model.hashed_output(HEADER.format(SECRET)) == "Authorization: <hidden>\nmade-up-tool 1.2\n"
    )


def test_an_output_without_a_secret_is_hashed_as_printed() -> None:
    text = "made-up-tool 1.2\r\nbuilt with made-up-cc 4.5\n\nlast line without an end"

    assert model.hashed_output(text) == text


# What an identify command prints to tell one build from another, before and after a change.
# Every value is made up. A checksum of a file as sha256sum and md5sum print it, a build id as
# ``readelf -n`` prints it, and the pins of packages whose names read like credentials.
BUILDS = [
    ("0123456789abcdef" * 4 + "  model.bin", "fedcba9876543210" * 4 + "  model.bin"),
    ("0123456789abcdef" * 2 + "  weights.bin", "fedcba9876543210" * 2 + "  weights.bin"),
    (
        "    Build ID: 00112233445566778899aabbccddeeff",
        "    Build ID: ffeeddccbbaa99887766554433221100",
    ),
    ("keyring==24.3.0", "keyring==25.1.0"),
    ("google-auth==2.29.0", "google-auth==2.30.0"),
    ("SecretStorage==3.3.3", "SecretStorage==3.3.4"),
    ("PyJWT==2.8.0", "PyJWT==2.9.0"),
]
BUILD_IDS = ["sha256sum", "md5sum", "build-id", "keyring", "google-auth", "secretstorage", "pyjwt"]


@pytest.mark.parametrize(("before", "after"), BUILDS, ids=BUILD_IDS)
def test_a_value_that_tells_builds_apart_is_hashed_as_printed(before: str, after: str) -> None:
    assert model.hashed_output(before + "\n") == before + "\n"
    assert model.hashed_output(after + "\n") == after + "\n"


@pytest.mark.parametrize(("before", "after"), BUILDS, ids=BUILD_IDS)
def test_a_change_in_a_value_that_tells_builds_apart_changes_both_hashes(
    fake_runner: Callable[..., Any], before: str, after: str
) -> None:
    one = _identify(fake_runner, before + "\nmade-up-tool 1.2\n")
    two = _identify(fake_runner, after + "\nmade-up-tool 1.2\n")

    assert one["identify_sha256"] != two["identify_sha256"]
    assert _fingerprint(before + "\n") != _fingerprint(after + "\n")


# Each form a credential takes in an identify line, with its two made-up values. The hash
# reads each of them as it reads a command, so the two values give one hash.
HIDDEN_FORMS = [
    ("API_TOKEN={}", "API_TOKEN=<hidden>"),
    ("export HF_TOKEN={}", "export HF_TOKEN=<hidden>"),
    ("--token {}", "--token <hidden>"),
    ("Authorization: Bearer {}", "Authorization: <hidden>"),
    ("password: {}", "password: <hidden>"),
    ("API_KEY == '{}'", "API_KEY == '<hidden>'"),
    ("API_KEY=={}", "API_KEY=<hidden>"),
    ("https://bench:{}@made-up.example/x", "https://<hidden>@made-up.example/x"),
]


@pytest.mark.parametrize(("form", "shown"), HIDDEN_FORMS, ids=[f for f, _ in HIDDEN_FORMS])
def test_a_credential_in_an_identify_line_is_still_hidden(form: str, shown: str) -> None:
    assert model.hashed_output(form.format(SECRET)) == shown
    assert model.hashed_output(form.format(OTHER)) == shown
