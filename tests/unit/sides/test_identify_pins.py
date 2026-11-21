# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A version in the output of the identify command stays in its hash, whatever names it.

A version is no credential. The pin of a package whose name reads like a
credential (``keyring``) is kept in every form a package tool prints it: pip's
``NAME==VERSION`` with or without blanks, with ``# via``, a marker or a ``\\``
after it; ``NAME: VERSION``; conda's ``- NAME=VERSION=BUILD``; and a quoted
name and version in a Python or JSON table. So is a line that names a digest
and gives one. Two versions give two hashes and two fingerprints. A credential
in the same output stays hidden: after the pin on its line, beside the pin in
a table, and in the forms that only look like a pin (``keyring=24.3.0`` alone,
a version after a colon with more words after it, a number with no dot after a
colon, a version glued to more letters).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pairbench import model
from pairbench.model import LaunchSettings, fingerprint_of
from pairbench.sides.base import Completed
from pairbench.sides.identity import run_identify

IDENTIFY = ["/made/up/bin/version"]
TAIL = "\nmade-up-tool 1.2\n"
# Made-up digests, as long as a SHA-256 digest is.
DIGEST_ONE = "0123456789abcdef" * 4
DIGEST_TWO = "fedcba9876543210" * 4

# Each row: a line an identify command prints, and the same line after a new version.
KEPT = {
    "pip-freeze": ("keyring==24.3.0", "keyring==25.1.0"),
    "blanks-around-equals": ("keyring == 24.3.0", "keyring == 25.1.0"),
    "capital-label": ("Keyring==24.3.0RC1", "Keyring==24.3.0RC2"),
    "leading-blanks": ("  keyring==24.3.0", "  keyring==25.1.0"),
    "via": ("keyring==24.3.0  # via made-up-tool", "keyring==25.1.0  # via made-up-tool"),
    "marker": (
        'keyring==24.3.0 ; python_version >= "3.8"',
        'keyring==25.1.0 ; python_version >= "3.8"',
    ),
    "marker-glued": (
        "keyring==24.3.0;python_version>'3.8'",
        "keyring==25.1.0;python_version>'3.8'",
    ),
    "continuation": ("keyring==24.3.0 \\", "keyring==25.1.0 \\"),
    "colon": ("keyring: 24.3.0", "keyring: 25.1.0"),
    "colon-leading-blanks": ("  keyring: 24.3.0", "  keyring: 25.1.0"),
    "colon-capital-label": ("Keyring: 24.3.0RC1", "Keyring: 24.3.0RC2"),
    "conda": ("  - keyring=24.3.0=pyh1a2b3c_0", "  - keyring=25.1.0=pyh1a2b3c_0"),
    "repr-table": (
        "{'keyring': '24.3.0', 'numpy': '1.26.4'}",
        "{'keyring': '25.1.0', 'numpy': '1.26.4'}",
    ),
    "json-table": ('{"keyring": "24.3.0"}', '{"keyring": "25.1.0"}'),
    "table-capital-label": ("{'Keyring': '24.3.0RC1'}", "{'Keyring': '24.3.0RC2'}"),
    "digest": (f"SECRET_SHA256={DIGEST_ONE}", f"SECRET_SHA256={DIGEST_TWO}"),
    "digest-exported": (f"export SECRET_SHA256={DIGEST_ONE}", f"export SECRET_SHA256={DIGEST_TWO}"),
    "hash-algorithm": ("password_hash: bcrypt", "password_hash: argon2id"),
}


def _identify(fake_runner: Callable[..., Any], output: str) -> str:
    def answer(argv: tuple[str, ...]) -> Completed:
        return Completed(rc=0, stdout=output)

    return run_identify(fake_runner(answer), IDENTIFY, side="new")["identify_sha256"]


def _fingerprint(output: str) -> str:
    identity = {"executable_sha256": "e" * 64, "identify_output": output}
    return fingerprint_of(identity, LaunchSettings().effective(args=["made-up-tool"]))


@pytest.mark.parametrize(("before", "after"), list(KEPT.values()), ids=list(KEPT))
def test_a_version_is_hashed_as_printed(before: str, after: str) -> None:
    assert model.hashed_output(before) == before
    assert model.hashed_output(after) == after


@pytest.mark.parametrize(("before", "after"), list(KEPT.values()), ids=list(KEPT))
def test_two_versions_make_two_sides(
    fake_runner: Callable[..., Any], before: str, after: str
) -> None:
    assert _identify(fake_runner, before + TAIL) != _identify(fake_runner, after + TAIL)
    assert _fingerprint(before + TAIL) != _fingerprint(after + TAIL)


# Each row: a line with ``VALUE`` where the value stands, the two values, and the line every
# hash reads for both.
HIDDEN = {
    "assignment-of-a-version": ("keyring=VALUE", ("24.3.0", "25.1.0"), "keyring=<hidden>"),
    "list-item-without-a-build": ("- keyring=VALUE", ("24.3.0", "25.1.0"), "- keyring=<hidden>"),
    "token-after-a-pin": (
        "keyring==24.3.0 --token VALUE",
        ("kiwi7", "plum4"),
        "keyring==24.3.0 --token <hidden>",
    ),
    "token-after-a-conda-pin": (
        "  - keyring=24.3.0=pyh1a2b3c_0 --token VALUE",
        ("kiwi7", "plum4"),
        "  - keyring=24.3.0=pyh1a2b3c_0 --token <hidden>",
    ),
    "token-beside-a-pin-in-a-table": (
        "{'keyring': '24.3.0', 'api_token': 'VALUE'}",
        ("kiwi7", "plum4"),
        "{'keyring': '24.3.0', 'api_token': '<hidden>'}",
    ),
    "pin-inside-a-quoted-value": (
        "{'token': \"VALUE 'keyring': '1.2.3'\"}",
        ("kiwi7", "plum4"),
        "{'token': \"<hidden>\"}",
    ),
    "words-after-a-colon-version": (
        "password: 1.2.3 VALUE",
        ("kiwi7", "plum4"),
        "password: <hidden>",
    ),
    "number-after-a-colon": ("password: VALUE", ("1234", "5678"), "password: <hidden>"),
    "number-in-a-table": ("{'password': 'VALUE'}", ("1234", "5678"), "{'password': '<hidden>'}"),
    "letters-glued-to-a-version": ("API_KEY==1.2.3VALUE", ("kiwi7", "plum4"), "API_KEY=<hidden>"),
    "digest-name-given-a-password": (
        "password_hash: VALUE",
        ("kiwi7", "plum4"),
        "password_hash: <hidden>",
    ),
    "digest-name-given-a-short-value": (
        "SECRET_SHA256=VALUE",
        ("kiwi7", "plum4"),
        "SECRET_SHA256=<hidden>",
    ),
    "token-as-long-as-a-digest": (
        "API_TOKEN=VALUE",
        (DIGEST_ONE, DIGEST_TWO),
        "API_TOKEN=<hidden>",
    ),
    "words-after-a-hash-algorithm": (
        "password_hash: bcrypt VALUE",
        ("kiwi7", "plum4"),
        "password_hash: <hidden>",
    ),
    # An escaped quote does not close a quoted value: the pin-like words after it are part
    # of the value and are hidden with it, up to the quote that closes it.
    "pin-after-an-escaped-quote": (
        '{"token": "VALUE\\" \'keyring\': \'1.2.3\'"}',
        ("kiwi7", "plum4"),
        '{"token": "<hidden>"}',
    ),
    "version-of-a-pin-after-an-escaped-quote": (
        '{"token": "kiwi7\\" \'keyring\': \'VALUE\'"}',
        ("1.2.3", "2.0.1"),
        '{"token": "<hidden>"}',
    ),
}


@pytest.mark.parametrize(("line", "values", "hashed"), list(HIDDEN.values()), ids=list(HIDDEN))
def test_a_credential_beside_or_like_a_pin_stays_hidden(
    fake_runner: Callable[..., Any], line: str, values: tuple[str, str], hashed: str
) -> None:
    one, two = (line.replace("VALUE", value) for value in values)

    assert model.hashed_output(one) == hashed
    assert model.hashed_output(two) == hashed
    assert _identify(fake_runner, one + TAIL) == _identify(fake_runner, two + TAIL)
    assert _fingerprint(one + TAIL) == _fingerprint(two + TAIL)


def test_a_pip_compile_block_keeps_its_pin_and_hides_its_token() -> None:
    text = (
        "keyring==24.3.0 \\\n"
        f"    --hash=sha256:{DIGEST_ONE}\n"
        "    # via made-up-tool\n"
        "API_TOKEN=kiwi7\n"
    )

    assert model.hashed_output(text) == (
        "keyring==24.3.0 \\\n"
        f"    --hash=sha256:{DIGEST_ONE}\n"
        "    # via made-up-tool\n"
        "API_TOKEN=<hidden>\n"
    )
