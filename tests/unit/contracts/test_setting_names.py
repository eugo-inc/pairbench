# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential-like word that names a setting hides the value after it in the shown command.

After a word of ``SETTING_WORDS`` (``set``, ``config``, ``setenv``, in any case)
and any options after it, the next word names a setting, as in ``aws
configure set NAME VALUE``. When that name looks like a credential, each later
word of the command that is no option is hidden whatever its shape, and so is a
value glued to a long option, up to a separator or a line break. A credential-like
word anywhere else, such as a subcommand or a benchmark name, hides nothing.
Every value is made up.
"""

from __future__ import annotations

import shlex
import time

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "

# A made-up key of 40 characters with a `/` near its start, and a short made-up password.
KEY = "EXAMPLEk/zwE+8qv5a4ABGOFharkRfu1EbgRhq2x"
SHORT = "zqmset-made-up"


def shown(*args: str) -> str | None:
    return model.public_command((*LEAD, *args))


def test_the_setting_words() -> None:
    assert model.SETTING_WORDS == ("set", "config", "setenv")


def test_the_clients_whose_set_writes_a_key() -> None:
    assert model.DATA_SET_CLIENTS == (
        "redis-cli",
        "valkey-cli",
        "redis-benchmark",
        "valkey-benchmark",
    )
    # Each is found by its program word as the clients with password options are.
    assert [
        name for name in model.DATA_SET_CLIENTS if name not in model.CLIENT_PASSWORD_OPTIONS
    ] == []


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ("aws", "configure", "set", "aws_secret_access_key", KEY),
            ("aws", "configure", "set", "aws_secret_access_key", "<hidden>"),
        ),
        (
            ("aws", "configure", "set", "aws_secret_access_key", SHORT),
            ("aws", "configure", "set", "aws_secret_access_key", "<hidden>"),
        ),
        # Every later word that is no option is hidden, the name of a profile among them.
        (
            ("aws", "configure", "set", "aws_session_token", SHORT, "--profile", "made-up"),
            ("aws", "configure", "set", "aws_session_token", "<hidden>", "--profile", "<hidden>"),
        ),
        (
            ("redis-cli", "CONFIG", "SET", "requirepass", SHORT),
            ("redis-cli", "CONFIG", "SET", "requirepass", "<hidden>"),
        ),
        (
            ("git", "config", "--global", "github.token", SHORT),
            ("git", "config", "--global", "github.token", "<hidden>"),
        ),
        # The name starts as an absolute path does, and is cut as one.
        (
            ("npm", "config", "set", "//registry.example/:_authToken", SHORT),
            ("npm", "config", "set", ":_authToken", "<hidden>"),
        ),
        (
            ("npm", "config", "set", "registry.example/:_authToken", SHORT),
            ("npm", "config", "set", "registry.example/:_authToken", "<hidden>"),
        ),
        (
            ("yarn", "config", "set", "npmAuthToken", SHORT),
            ("yarn", "config", "set", "npmAuthToken", "<hidden>"),
        ),
        (("setenv", "HF_TOKEN", SHORT), ("setenv", "HF_TOKEN", "<hidden>")),
        (
            ("sh", "-c", f"aws configure set aws_secret_access_key {SHORT} && echo ok"),
            ("sh", "-c", "aws configure set aws_secret_access_key <hidden> && echo ok"),
        ),
        (
            ("fish", "-c", f"set -gx HF_TOKEN {SHORT}; tool"),
            ("fish", "-c", "set -gx HF_TOKEN <hidden>; tool"),
        ),
    ],
)
def test_the_value_of_a_credential_setting_is_hidden(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    text = shown(*args)

    assert text == SHOWN_LEAD + shlex.join(expected)
    assert SHORT not in text
    assert "EXAMPLEk" not in text


def test_the_aws_key_is_hidden_in_one_text_too() -> None:
    text = f"aws configure set aws_secret_access_key {KEY}"

    assert model.public_words(text) == "aws configure set aws_secret_access_key <hidden>"


# A variable the shell puts in the name of a setting is part of the name; the name's last part
# is judged as in any other name. `{value}` stands for the value typed.
VARIABLE_NAMES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a registry in braces": (
        ("npm", "config", "set", "//${REGISTRY}/:_authToken", "{value}"),
        ("npm", "config", "set", ":_authToken", "<hidden>"),
    ),
    "a registry with no braces": (
        ("npm", "config", "set", "//$REGISTRY/:_authToken", "{value}"),
        ("npm", "config", "set", ":_authToken", "<hidden>"),
    ),
    "a section of a dotted name": (
        ("git", "config", "--global", "${SECTION}.token", "{value}"),
        ("git", "config", "--global", "${SECTION}.token", "<hidden>"),
    ),
    "a profile of a dotted name": (
        ("aws", "configure", "set", "profile.${PROFILE}.aws_secret_access_key", "{value}"),
        ("aws", "configure", "set", "profile.${PROFILE}.aws_secret_access_key", "<hidden>"),
    ),
    "a shell text": (
        ("sh", "-c", "npm config set //${REGISTRY}/:_authToken {value} && ./key_bench 64"),
        ("sh", "-c", "npm config set ${REGISTRY}:_authToken <hidden> && ./key_bench 64"),
    ),
}


def _valued(args: tuple[str, ...], value: str) -> tuple[str, ...]:
    return tuple(word.replace("{value}", value) for word in args)


@pytest.mark.parametrize(("args", "expected"), VARIABLE_NAMES.values(), ids=VARIABLE_NAMES)
def test_a_variable_in_the_name_of_a_credential_setting_hides_its_value(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    text = shown(*_valued(args, SHORT))

    assert text == SHOWN_LEAD + shlex.join(expected)
    assert SHORT not in text


@pytest.mark.parametrize("args", [args for args, _ in VARIABLE_NAMES.values()], ids=VARIABLE_NAMES)
def test_two_values_of_such_a_setting_give_one_hash(args: tuple[str, ...]) -> None:
    one = model.hashed_argv(_valued(args, SHORT))
    two = model.hashed_argv(_valued(args, SHORT + "-other"))

    assert one == two
    assert SHORT not in " ".join(one)


# Values that stay shown: settings that name no credential, credential-like subcommand
# words, benchmark and file names, and a variable passed to a container by its name.
SHOWN: tuple[tuple[str, ...], ...] = (
    ("git", "config", "user.name", "Some Name"),
    ("git", "config", "--global", "user.email", "someone@made-up.example"),
    ("git", "config", "credential.helper", "store"),
    ("aws", "configure", "set", "region", "made-up-region-1"),
    ("redis-cli", "CONFIG", "SET", "maxmemory", "100mb"),
    ("kubectl", "create", "secret", "generic", "made-up-name"),
    ("gh", "auth", "token"),
    ("gh", "auth", "login", "--hostname", "made-up.example"),
    ("./bench", "BM_KeyLookup", "4096"),
    ("./bench", "sort_by_key", "64"),
    ("./bench", "test_password_hash", "8"),
    ("./bench", "api_key.pem", "out.json"),
    ("docker", "run", "-e", "HF_TOKEN", "made-up/image:1"),
    ("sh", "-c", "set -e; tool sort_by_key 64"),
    ("sh", "-c", "set -- token value; tool"),
    # A separator glued to an option of `set` in a shell text ends its options too, and so
    # does a separator that is a word of its own in an argument list.
    ("sh", "-c", "set -e; api_token made-up-arg"),
    ("set", "-e", ";", "api_token", "made-up-arg"),
    # A line break ends the options of `set`, as a separator does.
    ("sh", "-c", "set -e\n./key_bench 64"),
    ("sh", "-c", "set -eu\ntoken_tool made-up-arg"),
    # `SET` of a key-value client writes the value of a key; it names no setting.
    ("redis-cli", "SET", "key", "value"),
    ("redis-cli", "-h", "127.0.0.1", "set", "mykey", "5"),
    ("valkey-cli", "SET", "api_key", "made-up-value"),
    ("redis-benchmark", "-n", "10", "SET", "session_token", "made-up-value"),
    ("redis-cli", "-h", "127.0.0.1", "-p", "6379", "SET", "api_key", "made-up-value"),
    # A variable in the name of a setting that names no credential.
    ("git", "config", "--global", "${SECTION}.name", "made-up-name"),
    ("aws", "configure", "set", "profile.${PROFILE}.region", "made-up-region-1"),
    ("setenv", "${NAME}", "made-up-value"),
    ("sh", "-c", "set -- ${ARGS}; ./key_bench 64"),
)


@pytest.mark.parametrize("args", SHOWN)
def test_other_credential_like_words_hide_nothing_after_them(args: tuple[str, ...]) -> None:
    # The host of an address is hidden by its own rule, so a command here holds no address.
    assert shown(*args) == SHOWN_LEAD + shlex.join(args)


def test_a_long_option_after_a_credential_setting_stays_shown() -> None:
    args = ("tool", "config", "api_key", "--dry-run")

    assert shown(*args) == SHOWN_LEAD + shlex.join(args)


# The value given to an option after a credential setting's name, as `gh secret set` takes it,
# and every later word of the command that is no option: an option stays shown.
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ("gh", "secret", "set", "MY_TOKEN", "-b", SHORT),
            ("gh", "secret", "set", "MY_TOKEN", "-b", "<hidden>"),
        ),
        (
            ("gh", "secret", "set", "MY_TOKEN", "--body", SHORT),
            ("gh", "secret", "set", "MY_TOKEN", "--body", "<hidden>"),
        ),
        (
            ("gh", "secret", "set", "MY_TOKEN", f"--body={SHORT}"),
            ("gh", "secret", "set", "MY_TOKEN", "--body=<hidden>"),
        ),
        (
            ("gh", "secret", "set", "MY_TOKEN", "--env", "made-up-env", "--body", SHORT),
            ("gh", "secret", "set", "MY_TOKEN", "--env", "<hidden>", "--body", "<hidden>"),
        ),
        (
            ("sh", "-c", f"gh secret set MY_TOKEN --body {SHORT} && ./key_bench 64"),
            ("sh", "-c", "gh secret set MY_TOKEN --body <hidden> && ./key_bench 64"),
        ),
        (
            ("sh", "-c", f"gh secret set MY_TOKEN --body {SHORT}; ./key_bench 64"),
            ("sh", "-c", "gh secret set MY_TOKEN --body <hidden>; ./key_bench 64"),
        ),
        (
            ("sh", "-c", f"git config github.token {SHORT}\n./key_bench 64"),
            ("sh", "-c", "git config github.token <hidden>\n./key_bench 64"),
        ),
        (
            ("mysql", "-e", f"SET PASSWORD = '{SHORT}'"),
            ("mysql", "-e", "SET PASSWORD = <hidden>"),
        ),
    ],
    ids=[
        "short-option",
        "long-option",
        "glued",
        "after-another-option",
        "and",
        "semicolon",
        "line-break",
        "equals",
    ],
)
def test_every_value_after_a_credential_setting_is_hidden(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    text = shown(*args)

    assert text == SHOWN_LEAD + shlex.join(expected)
    assert SHORT not in text


def test_the_value_of_an_option_after_a_credential_setting_is_hidden_in_the_hash() -> None:
    argv = ["gh", "secret", "set", "MY_TOKEN", "--body", SHORT]

    assert model.hashed_argv(argv) == ["gh", "secret", "set", "MY_TOKEN", "--body", "<hidden>"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"gh secret set MY_TOKEN --body {SHORT}", "gh secret set MY_TOKEN --body <hidden>"),
        ("set -e\n./key_bench 64", "set -e ./key_bench 64"),
        (
            f"git config github.token {SHORT}\n./key_bench 64",
            "git config github.token <hidden> ./key_bench 64",
        ),
    ],
    ids=["option", "set-options-end-at-a-line", "value-ends-at-a-line"],
)
def test_one_text_hides_the_values_of_a_credential_setting_to_its_line_end(
    text: str, expected: str
) -> None:
    assert model.public_words(text) == expected


def test_config_set_of_a_key_value_client_still_hides_the_value() -> None:
    text = shown("sh", "-c", f"redis-cli SET key value && redis-cli CONFIG SET requirepass {SHORT}")

    assert text == SHOWN_LEAD + shlex.join(
        ("sh", "-c", "redis-cli SET key value && redis-cli CONFIG SET requirepass <hidden>")
    )


# Only the command word of a key-value client is its `SET`: a later command, after a line
# break or a separator, or a client alone on its line, starts a setting with `set` again.
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ("sh", "-c", f"redis-cli PING\naws configure set aws_secret_access_key {SHORT}"),
            ("sh", "-c", "redis-cli PING\naws configure set aws_secret_access_key <hidden>"),
        ),
        (
            ("sh", "-c", f"redis-cli SET key value\nset -gx HF_TOKEN {SHORT}"),
            ("sh", "-c", "redis-cli SET key value\nset -gx HF_TOKEN <hidden>"),
        ),
        (
            ("sh", "-c", f"redis-cli\nset -gx HF_TOKEN {SHORT}"),
            ("sh", "-c", "redis-cli\nset -gx HF_TOKEN <hidden>"),
        ),
        (
            ("sh", "-c", f"redis-cli PING && aws configure set aws_secret_access_key {SHORT}"),
            ("sh", "-c", "redis-cli PING && aws configure set aws_secret_access_key <hidden>"),
        ),
        (
            ("sh", "-c", f"redis-cli SET key value; setenv HF_TOKEN {SHORT}"),
            ("sh", "-c", "redis-cli SET key value; setenv HF_TOKEN <hidden>"),
        ),
        (
            ("fish", "-c", f"redis-cli PING; set -gx HF_TOKEN {SHORT}"),
            ("fish", "-c", "redis-cli PING; set -gx HF_TOKEN <hidden>"),
        ),
        (
            ("hyperfine", "redis-cli PING", f"aws configure set aws_secret_access_key {SHORT}"),
            ("hyperfine", "redis-cli PING", "aws configure set aws_secret_access_key <hidden>"),
        ),
        (
            ("redis-cli", "PING", "&&", "fish", "-c", "set", "HF_TOKEN", SHORT),
            ("redis-cli", "PING", "&&", "fish", "-c", "set", "HF_TOKEN", "<hidden>"),
        ),
        # The client's command ends at a separator after a hidden value or an option's value.
        (
            ("sh", "-c", f"redis-cli -a made-up; set -gx HF_TOKEN {SHORT}"),
            ("sh", "-c", "redis-cli -a <hidden>; set -gx HF_TOKEN <hidden>"),
        ),
        (
            ("sh", "-c", f"redis-cli -n 1; set -gx HF_TOKEN {SHORT}"),
            ("sh", "-c", "redis-cli -n 1; set -gx HF_TOKEN <hidden>"),
        ),
    ],
)
def test_a_command_after_a_key_value_client_still_hides_a_credential_setting(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    text = shown(*args)

    assert text == SHOWN_LEAD + shlex.join(expected)
    assert SHORT not in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            f"redis-cli PING\naws configure set aws_secret_access_key {SHORT}",
            "redis-cli PING aws configure set aws_secret_access_key <hidden>",
        ),
        (f"redis-cli\nset -gx HF_TOKEN {SHORT}", "redis-cli set -gx HF_TOKEN <hidden>"),
        ("redis-cli SET api_key made-up-value", "redis-cli SET api_key made-up-value"),
    ],
)
def test_one_text_after_a_key_value_client_still_hides_a_credential_setting(
    text: str, expected: str
) -> None:
    assert model.public_words(text) == expected


def test_a_long_value_of_a_credential_setting_is_hidden_quickly() -> None:
    value = "zq" * 64_000
    timings: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        text = shown("aws", "configure", "set", "aws_secret_access_key", value)
        timings.append(time.perf_counter() - start)

    assert text == SHOWN_LEAD + "aws configure set aws_secret_access_key '<hidden>'"
    assert min(timings) < 2.0
