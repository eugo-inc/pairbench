# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Which parts of a hidden credential's value set two sides apart.

The shown command and every published hash hide a credential's value whole.
The comparison of two sides, or of one side in two captures, reads the value
with only the credential itself hidden: the value up to its first blank, or an
Authorization scheme word (``Bearer``, ``Basic`` or ``Token``) with the token
after it. A rotated token is then no difference, and a changed word after it
is one. That holds for a value given after ``=``, glued to an option and given
as the next argument. An address keeps its user name, its host, its path and
its query, and loses only its password and the values of its credential-like
query parameters. A client's command glued to its ``command`` option keeps
every word of the command but the password.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pairbench.model import (
    AUTH_SCHEME_WORDS,
    hashed_argv,
    hidden_difference,
    public_command,
    side_setup,
)

REPO = Path(__file__).resolve().parents[3]

# Two made-up tokens, as the rows rotate one for the other.
OLD, NEW = "kiwi7zq", "plum4zq"
# Two made-up words that stand after a credential's value.
TAIL_A, TAIL_B = "alpha", "beta"


def _sides_apart(one: list[str], two: list[str]) -> bool:
    """Whether two command sides are two sides: their hashes differ, or the comparison says so."""
    config: dict[str, Any] = {"sides": {"a": {"cmd": one}, "b": {"cmd": two}}}
    if hashed_argv(one) != hashed_argv(two):
        return True
    return hidden_difference(side_setup(config, "a"), side_setup(config, "b"))


def _rotated(form: str) -> tuple[list[str], list[str]]:
    return form.format(t=OLD, w=TAIL_A).split("|"), form.format(t=NEW, w=TAIL_A).split("|")


def _tail(form: str) -> tuple[list[str], list[str]]:
    return form.format(t=OLD, w=TAIL_A).split("|"), form.format(t=OLD, w=TAIL_B).split("|")


# Each form, with ``{t}`` where the token stands and ``{w}`` where a later word stands; the
# arguments are joined by ``|``.
SCHEME_FORMS = {
    "env-assignment": "env|AUTHORIZATION=Bearer {t} {w}|./made-up-bench",
    "docker-e": "docker|run|-e|AUTHORIZATION=Bearer {t} {w}|made-up/image:1",
    "auth-option": "made-up-bench|--auth=Bearer {t} {w}",
    "token-option": "made-up-bench|--token=Bearer {t} {w}",
    "docker-e-glued": "docker|run|-eAUTH_TOKEN=Bearer {t} {w}|made-up/image:1",
    "basic-scheme": "made-up-bench|--auth=Basic {t} {w}",
    "token-scheme": "made-up-bench|--auth=Token {t} {w}",
    "lower-case-scheme": "made-up-bench|--auth=bearer {t} {w}",
    "next-argument": "made-up-bench|--token|Bearer {t} {w}",
}


@pytest.mark.parametrize("form", list(SCHEME_FORMS.values()), ids=list(SCHEME_FORMS))
def test_a_rotated_token_after_a_scheme_word_sets_no_two_sides_apart(form: str) -> None:
    one, two = _rotated(form)

    assert _sides_apart(one, two) is False


@pytest.mark.parametrize("form", list(SCHEME_FORMS.values()), ids=list(SCHEME_FORMS))
def test_a_changed_word_after_a_scheme_word_and_its_token_sets_two_sides_apart(
    form: str,
) -> None:
    one, two = _tail(form)

    assert _sides_apart(one, two) is True


# A value given as the next argument, hidden whole in the shown command and the hashes.
NEXT_FORMS = {
    "password": "made-up-bench|--password|{t} {w}",
    "token": "made-up-bench|--token|{t} {w}",
    "client-password": "redis-cli|-a|{t} {w}",
}


@pytest.mark.parametrize("form", list(NEXT_FORMS.values()), ids=list(NEXT_FORMS))
def test_a_changed_word_after_the_first_blank_of_a_next_argument_value_sets_two_sides_apart(
    form: str,
) -> None:
    one, two = _tail(form)

    assert _sides_apart(one, two) is True


@pytest.mark.parametrize("form", list(NEXT_FORMS.values()), ids=list(NEXT_FORMS))
def test_a_rotated_first_word_of_a_next_argument_value_sets_no_two_sides_apart(
    form: str,
) -> None:
    one, two = _rotated(form)

    assert _sides_apart(one, two) is False


@pytest.mark.parametrize(
    "form",
    ["made-up-bench|--password|{t}", "redis-cli|-a|{t}|PING", "made-up-bench|--token|{t}"],
)
def test_a_rotated_next_argument_value_of_one_word_sets_no_two_sides_apart(form: str) -> None:
    one, two = _rotated(form)

    assert _sides_apart(one, two) is False


# A client's command glued to its ``command`` option, with two passwords.
GLUED_COMMANDS = {
    "auth": "memtier_benchmark|--command=AUTH {t}",
    "auth-with-user": "memtier_benchmark|--command=AUTH bench {t}",
    "acl-setuser": "memtier_benchmark|--command=ACL SETUSER bench on >{t}",
    "quoted": "memtier_benchmark|'--command=AUTH bench {t}'",
}


@pytest.mark.parametrize("form", list(GLUED_COMMANDS.values()), ids=list(GLUED_COMMANDS))
def test_a_rotated_password_in_a_glued_client_command_sets_no_two_sides_apart(form: str) -> None:
    one, two = _rotated(form)

    assert _sides_apart(one, two) is False


@pytest.mark.parametrize(
    ("one", "two"),
    [
        (
            ["memtier_benchmark", f"--command=AUTH alice {OLD}"],
            ["memtier_benchmark", f"--command=AUTH bob {OLD}"],
        ),
        (
            ["memtier_benchmark", f"--command=ACL SETUSER bench on >{OLD} ~alpha*"],
            ["memtier_benchmark", f"--command=ACL SETUSER bench on >{OLD} ~beta*"],
        ),
        (
            ["memtier_benchmark", "--command=SET __key__ alpha"],
            ["memtier_benchmark", "--command=SET __key__ beta"],
        ),
    ],
    ids=["user-name", "acl-key-pattern", "set-value"],
)
def test_another_word_of_a_glued_client_command_sets_two_sides_apart(
    one: list[str], two: list[str]
) -> None:
    assert _sides_apart(one, two) is True


# Pairs that differ only in a part of an address that the shown command and the hashes hide.
ADDRESS_PARTS = {
    "user-name": (
        ["made-up-bench", "postgres://alice@db/shop"],
        ["made-up-bench", "postgres://bob@db/shop"],
    ),
    "user-name-with-password": (
        ["made-up-bench", f"postgres://alice:{OLD}@db/shop"],
        ["made-up-bench", f"postgres://bob:{OLD}@db/shop"],
    ),
    "database-after-a-credential-name": (
        ["env", f"DB_PASSWORD=redis://:{OLD}@localhost/0", "./made-up-bench"],
        ["env", f"DB_PASSWORD=redis://:{OLD}@localhost/1", "./made-up-bench"],
    ),
    "database-after-a-glued-option": (
        ["made-up-bench", f"--password=redis://:{OLD}@localhost/0"],
        ["made-up-bench", f"--password=redis://:{OLD}@localhost/1"],
    ),
    "database-after-an-option": (
        ["made-up-bench", "--password", f"redis://:{OLD}@localhost/0"],
        ["made-up-bench", "--password", f"redis://:{OLD}@localhost/1"],
    ),
    "query-after-a-glued-option": (
        ["made-up-bench", f"--auth-url=http://localhost/v1?token={OLD}&model=alpha"],
        ["made-up-bench", f"--auth-url=http://localhost/v1?token={OLD}&model=beta"],
    ),
    "query-after-an-option": (
        ["made-up-bench", "--auth-url", f"http://localhost/v1?api_key={OLD}&model=alpha"],
        ["made-up-bench", "--auth-url", f"http://localhost/v1?api_key={OLD}&model=beta"],
    ),
}


@pytest.mark.parametrize(("one", "two"), list(ADDRESS_PARTS.values()), ids=list(ADDRESS_PARTS))
def test_a_hidden_part_of_an_address_other_than_its_password_sets_two_sides_apart(
    one: list[str], two: list[str]
) -> None:
    assert hashed_argv(one) == hashed_argv(two)
    assert public_command(one) == public_command(two)
    assert _sides_apart(one, two) is True


# The same addresses with only the password, or a credential's value in the query, rotated.
ADDRESS_SECRETS = {
    "password": "made-up-bench|postgres://alice:{t}@db/shop",
    "database-after-a-credential-name": "env|DB_PASSWORD=redis://:{t}@localhost/0|./made-up-bench",
    "database-after-a-glued-option": "made-up-bench|--password=redis://:{t}@localhost/0",
    "database-after-an-option": "made-up-bench|--password|redis://:{t}@localhost/0",
    "query-after-a-glued-option": "made-up-bench|--auth-url=http://localhost/v1?token={t}&model=a",
    "query-after-an-option": "made-up-bench|--auth-url|http://localhost/v1?api_key={t}&model=a",
}


@pytest.mark.parametrize("form", list(ADDRESS_SECRETS.values()), ids=list(ADDRESS_SECRETS))
def test_a_rotated_password_or_query_credential_of_an_address_sets_no_two_sides_apart(
    form: str,
) -> None:
    one, two = _rotated(form)

    assert _sides_apart(one, two) is False


# A token after a scheme word given as a word of its own: the shown command and the hashes hide
# the scheme word and the token, and show what follows.
SEPARATE_SCHEMES = {
    "next-argument": (
        ["made-up-bench", "--token", "Bearer", OLD, "-n", "8"],
        "made-up-bench --token '<hidden>' '<hidden>' -n 8",
        ["made-up-bench", "--token", "<hidden>", "<hidden>", "-n", "8"],
    ),
    "glued-option": (
        ["made-up-bench", "--auth=Basic", OLD, "model-a"],
        "made-up-bench '--auth=<hidden>' '<hidden>' model-a",
        ["made-up-bench", "--auth=<hidden>", "<hidden>", "model-a"],
    ),
    "shell-text": (
        ["sh", "-c", f"made-up-bench --token Bearer {OLD} -n 8"],
        "sh -c 'made-up-bench --token <hidden> <hidden> -n 8'",
        ["sh", "-c", "made-up-bench --token <hidden> <hidden> -n 8"],
    ),
    "shell-text-glued": (
        ["sh", "-c", f"made-up-bench --auth=Bearer {OLD}"],
        "sh -c 'made-up-bench --auth=<hidden> <hidden>'",
        ["sh", "-c", "made-up-bench --auth=<hidden> <hidden>"],
    ),
    "ordinary-name-value": (
        ["env", f"MADE_UP_FLAGS=--token Bearer {OLD} -n 8", "./made-up-bench"],
        "env 'MADE_UP_FLAGS=--token <hidden> <hidden> -n 8' ./made-up-bench",
        ["env", "MADE_UP_FLAGS=--token <hidden> <hidden> -n 8", "./made-up-bench"],
    ),
}


@pytest.mark.parametrize(
    ("argv", "shown", "hashed"), list(SEPARATE_SCHEMES.values()), ids=list(SEPARATE_SCHEMES)
)
def test_a_token_after_a_scheme_word_of_its_own_is_hidden(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed


# Words after a scheme word that are no token: an option, a word after a client's password
# option, and a scheme word that is no credential's value.
NO_TOKEN = {
    "option-after-the-scheme-word": (
        ["made-up-bench", "--token", "Bearer", "--threads", "8"],
        "made-up-bench --token '<hidden>' --threads 8",
        ["made-up-bench", "--token", "<hidden>", "--threads", "8"],
    ),
    "short-option-after-the-scheme-word": (
        ["made-up-bench", "--token", "Bearer", "-n", "8"],
        "made-up-bench --token '<hidden>' -n 8",
        ["made-up-bench", "--token", "<hidden>", "-n", "8"],
    ),
    "client-password-option": (
        ["redis-cli", "-a", "Bearer", "PING"],
        "redis-cli -a '<hidden>' PING",
        ["redis-cli", "-a", "<hidden>", "PING"],
    ),
    "ordinary-option": (
        ["made-up-bench", "--auth-type", "Bearer", "model-a"],
        "made-up-bench --auth-type Bearer model-a",
        ["made-up-bench", "--auth-type", "Bearer", "model-a"],
    ),
    "token-first": (
        ["made-up-bench", "--token", OLD, "Bearer"],
        "made-up-bench --token '<hidden>' Bearer",
        ["made-up-bench", "--token", "<hidden>", "Bearer"],
    ),
}


@pytest.mark.parametrize(("argv", "shown", "hashed"), list(NO_TOKEN.values()), ids=list(NO_TOKEN))
def test_a_word_after_a_scheme_word_that_is_no_token_is_shown(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed


# A client's password option that is also an axis option, and an axis option ahead of a later
# credential: the axis ``Key`` is shown only as the value of the axis option itself.
AXIS_AND_CREDENTIAL = {
    "word-after-a-client-password": (
        ["redis-cli", "-a", OLD, f"Key={NEW}"],
        "redis-cli -a '<hidden>' 'Key=<hidden>'",
        ["redis-cli", "-a", "<hidden>", "Key=<hidden>"],
    ),
    "client-password-shaped-as-an-axis": (
        ["redis-cli", "-a", f"Key={OLD}", "PING"],
        "redis-cli -a '<hidden>' PING",
        ["redis-cli", "-a", "<hidden>", "PING"],
    ),
    "word-after-an-axis-value": (
        ["./made-up-bench", "-a", "Key=I32", f"Key={OLD}"],
        "./made-up-bench -a Key=I32 'Key=<hidden>'",
        ["./made-up-bench", "-a", "Key=I32", "Key=<hidden>"],
    ),
    "word-after-an-axis-value-and-a-word": (
        ["./made-up-bench", "--axis", "Key=I32", "-n", f"Key={OLD}"],
        "./made-up-bench --axis Key=I32 -n 'Key=<hidden>'",
        ["./made-up-bench", "--axis", "Key=I32", "-n", "Key=<hidden>"],
    ),
}


@pytest.mark.parametrize(
    ("argv", "shown", "hashed"), list(AXIS_AND_CREDENTIAL.values()), ids=list(AXIS_AND_CREDENTIAL)
)
def test_an_axis_key_is_shown_only_as_the_value_of_an_axis_option(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed


def _setup(side: dict[str, Any], launch: dict[str, Any] | None = None) -> dict[str, Any] | None:
    config: dict[str, Any] = {"sides": {"new": side}}
    if launch is not None:
        config["launch"] = launch
    return side_setup(config, "new")


# Two setups that differ in a value the shared files show: no hidden difference, however the
# rest reads. The fingerprint, not this comparison, tells such setups apart.
SHOWN_DIFFERENCES = {
    "argument": (
        _setup({"cmd": ["./made-up-bench", "-n", "8"]}),
        _setup({"cmd": ["./made-up-bench", "-n", "16"]}),
    ),
    "argument-beside-a-credential": (
        _setup({"cmd": ["./made-up-bench", "--token", OLD, "-n", "8"]}),
        _setup({"cmd": ["./made-up-bench", "--token", OLD, "-n", "16"]}),
    ),
    "shared-launch-setting": (
        _setup({"cmd": ["./made-up-bench"]}, {"timeout": 30}),
        _setup({"cmd": ["./made-up-bench"]}, {"timeout": 60}),
    ),
    "shared-launch-variable": (
        _setup({"cmd": ["./made-up-bench"]}, {"env": {"MADE_UP_MODE": "alpha"}}),
        _setup({"cmd": ["./made-up-bench"]}, {"env": {"MADE_UP_MODE": "beta"}}),
    ),
    "side-launch-variable": (
        _setup({"cmd": ["./made-up-bench"], "launch": {"env": {"MADE_UP_MODE": "alpha"}}}),
        _setup({"cmd": ["./made-up-bench"], "launch": {"env": {"MADE_UP_MODE": "beta"}}}),
    ),
}


@pytest.mark.parametrize(
    ("one", "two"), list(SHOWN_DIFFERENCES.values()), ids=list(SHOWN_DIFFERENCES)
)
def test_a_difference_in_a_shown_value_is_no_hidden_difference(one: Any, two: Any) -> None:
    assert hidden_difference(one, two) is False


# A run of 64 hexadecimal digits, made up, that a path hides with the rest of the path.
HEX = "0123456789abcdef" * 4


def test_the_shared_launch_table_is_part_of_a_side_s_setup() -> None:
    launch = {"env": {"MADE_UP_DIR": f"/made/up/{HEX}/a"}, "timeout": 30}
    config = {"sides": {"new": {"cmd": ["./made-up-bench"], "baseline": True}}, "launch": launch}

    assert side_setup(config, "new") == {
        "side": {"cmd": ["./made-up-bench"]},
        "launch": launch,
        "argv": None,
    }


def test_a_hidden_difference_in_the_shared_launch_table_is_a_hidden_difference() -> None:
    one = _setup({"cmd": ["./made-up-bench"]}, {"env": {"MADE_UP_DIR": f"/made/up/{HEX}/a"}})
    two = _setup({"cmd": ["./made-up-bench"]}, {"env": {"MADE_UP_DIR": f"/made/up/{HEX}/b"}})

    assert hidden_difference(one, two) is True


def test_the_config_page_names_each_authorization_scheme_word() -> None:
    page = " ".join((REPO / "docs" / "reference" / "config.md").read_text("utf-8").split())
    words = sorted(word.capitalize() for word in AUTH_SCHEME_WORDS)

    assert words == ["Basic", "Bearer", "Token"]
    assert "an Authorization scheme word, `Bearer`, `Basic` or `Token` in any case" in page
