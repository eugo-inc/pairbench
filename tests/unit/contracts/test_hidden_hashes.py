# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every published hash is taken over values whose recognised secret forms are hidden.

``argv_sha256``, ``args_sha256``, a side's fingerprint and
``provenance.config_sha256`` are each computed with every secret form the
shown command hides replaced by ``<hidden>``: a credential-like name, the
value of a credential-like option, a credential header, the user part of an
address, a ``user:password``, a client's password option, a credential name
given a value in a program's text, and a random-looking value. A value the
shown command hides to the end of its argument, spaces included, is hidden to
the end in the hash too, except in the text after ``-c``, whose other words
stay. So a word list tried against a published hash tells nothing about such a
value. Paths, hosts and every other value stay in the hash as they are, and a
hash of values that hold no secret is the plain SHA-256 of their canonical JSON.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pairbench import model
from pairbench.model import (
    HIDDEN,
    Experiment,
    LaunchSettings,
    canonical_json,
    config_sha256,
    fingerprint_of,
    sha256_hex,
)
from pairbench.sides.identity import argv_sha256

# Two made-up passwords and two made-up random-looking values.
SECRET = "kiwi7"
OTHER = "plum4"
RANDOM = "X1y2Z3x4Y5z6X7y8Z9x0Y1z2X3y4Z5x6"
RANDOM_OTHER = "Q9xW7mP2vL8nR4tY6bC1dF5gH0jKzA3s"
WORDS = (SECRET, OTHER)

# Each recognised form: the argument list as typed, ``{}`` standing for the secret, and the
# list the hash is taken over.
FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "credential-option": (
        ("made-up-tool", "--password", "{}"),
        ("made-up-tool", "--password", HIDDEN),
    ),
    "credential-option-with-equals": (
        ("made-up-tool", "--api-key={}"),
        ("made-up-tool", f"--api-key={HIDDEN}"),
    ),
    "credential-variable": (
        ("env", "API_TOKEN={}", "made-up-tool"),
        ("env", f"API_TOKEN={HIDDEN}", "made-up-tool"),
    ),
    "credential-header": (
        ("curl", "-H", "Authorization: Bearer {}", "http://localhost:8000/v1"),
        ("curl", "-H", f"Authorization: {HIDDEN}", "http://localhost:8000/v1"),
    ),
    "address-user-part": (
        ("made-up-tool", "--url", "https://madeup:{}@made-up.example/v1"),
        ("made-up-tool", "--url", f"https://{HIDDEN}@made-up.example/v1"),
    ),
    "user-and-password": (
        ("curl", "-u", "madeup:{}", "http://localhost:8000/"),
        ("curl", "-u", f"madeup:{HIDDEN}", "http://localhost:8000/"),
    ),
    "client-password-option": (
        ("redis-benchmark", "-a", "{}"),
        ("redis-benchmark", "-a", HIDDEN),
    ),
    "client-password-glued": (
        ("mysql", "-p{}"),
        ("mysql", f"-p{HIDDEN}"),
    ),
    "name-in-program-text": (
        ("python3", "-c", "import os; os.environ['API_KEY'] = '{}'"),
        ("python3", "-c", f"import os; os.environ['API_KEY'] = '{HIDDEN}'"),
    ),
    "nested-shell-command": (
        ("sh", "-c", "made-up-tool --token {}"),
        ("sh", "-c", f"made-up-tool --token {HIDDEN}"),
    ),
}
# The random-looking rule hides a value by its shape, so its form is tried with values of
# that shape.
RANDOM_FORM = (("made-up-tool", "--model", "{}"), ("made-up-tool", "--model", HIDDEN))

# Two made-up values that hold a space and differ after it, and the same two written with
# the space escaped by a backslash, as a shell text writes one value.
SPACED = ("made kiwi7", "made plum4")
ESCAPED = ("made\\ kiwi7", "made\\ plum4")
# Each form whose value the shown command hides to the end of its argument, spaces included:
# a credential-like variable or option given a value in the first word of the argument, the
# password of a ``user:password`` glued to its option, and a client's password option with
# its value glued to it.
WHOLE_VALUE_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "spaced-variable": (
        ("env", "DB_PASSWORD={}", "made-up-tool"),
        ("env", f"DB_PASSWORD={HIDDEN}", "made-up-tool"),
    ),
    "spaced-option-with-equals": (
        ("made-up-tool", "--api-key={}", "-v"),
        ("made-up-tool", f"--api-key={HIDDEN}", "-v"),
    ),
    "spaced-variable-after-an-option": (
        ("docker", "run", "-e", "X_TOKEN={}", "made-up-image"),
        ("docker", "run", "-e", f"X_TOKEN={HIDDEN}", "made-up-image"),
    ),
    "spaced-variable-in-an-option": (
        ("docker", "run", "--env=MY_TOKEN={}", "made-up-image"),
        ("docker", "run", f"--env=MY_TOKEN={HIDDEN}", "made-up-image"),
    ),
    "spaced-variable-glued-to-an-option": (
        ("made-up-bench", "-eMY_TOKEN={}"),
        ("made-up-bench", f"-eMY_TOKEN={HIDDEN}"),
    ),
    "spaced-user-and-password-with-equals": (
        ("curl", "--user=madeup:{}", "http://localhost:8000/"),
        ("curl", f"--user=madeup:{HIDDEN}", "http://localhost:8000/"),
    ),
    "spaced-user-and-password-glued": (
        ("curl", "-umadeup:{}", "http://localhost:8000/"),
        ("curl", f"-umadeup:{HIDDEN}", "http://localhost:8000/"),
    ),
    "spaced-client-password-glued": (
        ("mysql", "-p{}", "shop"),
        ("mysql", f"-p{HIDDEN}", "shop"),
    ),
    "spaced-key-value-client-password-glued": (
        ("redis-cli", "-a{}", "ping"),
        ("redis-cli", f"-a{HIDDEN}", "ping"),
    ),
    "spaced-password-of-a-command-runner": (
        ("sshpass", "-p{}", "ssh", "made-up-host"),
        ("sshpass", f"-p{HIDDEN}", "ssh", "made-up-host"),
    ),
    "spaced-client-user-and-password-glued": (
        ("ab", "-Amadeup:{}", "http://localhost:8000/"),
        ("ab", f"-Amadeup:{HIDDEN}", "http://localhost:8000/"),
    ),
    "spaced-client-password-after-env": (
        ("env", "mysqladmin", "-p{}", "status"),
        ("env", "mysqladmin", f"-p{HIDDEN}", "status"),
    ),
}
# Each form of a credential given a value in a program's text that holds the value apart from
# its name: an option and its value as two quoted texts of a list, and a value written on the
# next line of a table, a call or a list.
CODE_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "option-and-value-in-a-list": (
        ("python3", "-c", 'subprocess.run(["made-up-tool", "--password", "{}"])'),
        ("python3", "-c", f'subprocess.run(["made-up-tool", "--password", "{HIDDEN}"])'),
    ),
    "short-dash-option-and-value-in-a-list": (
        ("python3", "-c", "args = ['-api-key', '{}']"),
        ("python3", "-c", f"args = ['-api-key', '{HIDDEN}']"),
    ),
    "value-on-the-next-line-of-a-table": (
        ("python3", "-c", 'd = {"api_key":\n    "{}"}'),
        ("python3", "-c", f'd = {{"api_key":\n    "{HIDDEN}"}}'),
    ),
    "value-on-the-next-line-of-a-call": (
        ("python3", "-c", "os.environ.setdefault('HF_TOKEN',\n    '{}')"),
        ("python3", "-c", f"os.environ.setdefault('HF_TOKEN',\n    '{HIDDEN}')"),
    ),
    "value-on-the-next-line-of-a-list": (
        ("python3", "-c", 'args = ["--token",\n    "{}"]'),
        ("python3", "-c", f'args = ["--token",\n    "{HIDDEN}"]'),
    ),
}
ESCAPED_FORM = (
    ("sh", "-c", "HF_TOKEN={} made-up-tool"),
    ("sh", "-c", f"HF_TOKEN={HIDDEN} made-up-tool"),
)

# Differences that are no secret, so each still changes every hash: a path, a host, an
# ordinary value, and a password given in no form the tool recognises.
KEPT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "path": (("/made/up/one/tool", "--size", "1"), ("/made/up/two/tool", "--size", "1")),
    "host": (
        ("made-up-tool", "--host", "one.example"),
        ("made-up-tool", "--host", "two.example"),
    ),
    "ordinary-value": (("made-up-tool", "--size", "1"), ("made-up-tool", "--size", "2")),
    "unrecognised-password": (("made-up-tool", SECRET), ("made-up-tool", OTHER)),
    # Values with spaces that no credential name gives, and ordinary values in a program.
    "spaced-ordinary-option": (
        ("made-up-tool", "--label=made one", "-v"),
        ("made-up-tool", "--label=made two", "-v"),
    ),
    "client-option-that-takes-no-password": (
        ("mysql", "-eSELECT 1", "shop"),
        ("mysql", "-eSELECT 2", "shop"),
    ),
    "ordinary-option-and-value-in-a-list": (
        ("python3", "-c", 'args = ["--max-tokens", "64"]'),
        ("python3", "-c", 'args = ["--max-tokens", "65"]'),
    ),
}

IDENTITY = {"executable": "/made/up/bin/tool", "executable_sha256": "ab" * 32}
# The identity as a fingerprint takes it: of the executable, the last part of its path.
HASHED_IDENTITY = {"executable": "tool", "executable_sha256": "ab" * 32}
# A hash of values without a secret is the plain formula: these hold paths, hosts, the
# names of passed variables and ordinary values, and nothing is hidden in them.
PLAIN_ARGV = ("/made/up/bin/tool", "--host", "made-up.example", "--size", "1", "{workload}")
PLAIN_LAUNCH = LaunchSettings(
    env={"MADE_UP_MODE": "fast", "MADE_UP_HOME": "/made/up/home"},
    env_pass=("API_TOKEN", "HF_TOKEN"),
    mounts=("/made/up/models:/models:ro",),
    cpus="0-3",
)
PLAIN_FINGERPRINT_LAUNCH = PLAIN_LAUNCH.effective(args=PLAIN_ARGV, entrypoint="/made/up/entry")


def typed(form: tuple[str, ...], secret: str) -> list[str]:
    return [part.replace("{}", secret) for part in form]


ALL_FORMS = [
    *((name, typed_form, shown, WORDS) for name, (typed_form, shown) in FORMS.items()),
    ("random-looking-value", *RANDOM_FORM, (RANDOM, RANDOM_OTHER)),
    *((name, typed_form, shown, SPACED) for name, (typed_form, shown) in WHOLE_VALUE_FORMS.items()),
    *((name, typed_form, shown, WORDS) for name, (typed_form, shown) in CODE_FORMS.items()),
    ("escaped-value-in-a-shell-command", *ESCAPED_FORM, ESCAPED),
]
FORM_IDS = [form[0] for form in ALL_FORMS]


# --- the argument list a hash is taken over ---------------------------------------


@pytest.mark.parametrize(("name", "form", "shown", "secrets"), ALL_FORMS, ids=FORM_IDS)
def test_the_hashed_argument_list_hides_each_recognised_form(
    name: str, form: tuple[str, ...], shown: tuple[str, ...], secrets: tuple[str, str]
) -> None:
    for secret in secrets:
        assert model.hashed_argv(typed(form, secret)) == list(shown)
    assert model.hashed_argv(list(shown)) == list(shown)


@pytest.mark.parametrize(("name", "form", "shown", "secrets"), ALL_FORMS, ids=FORM_IDS)
def test_the_argument_hash_of_a_secret_is_the_hash_of_the_hidden_marker(
    name: str, form: tuple[str, ...], shown: tuple[str, ...], secrets: tuple[str, str]
) -> None:
    expected = sha256_hex(canonical_json(list(shown)))
    assert [argv_sha256(typed(form, secret)) for secret in secrets] == [expected, expected]
    assert argv_sha256(typed(form, HIDDEN)) == expected


# A run the shown command hides whole, as typed and as the hash reads it: a run that holds
# ``+/``, as base64 does, and a value glued to an option of one letter that holds a ``/``.
# Its short parts change between the two values, so a part kept would tell them apart.
WHOLE_RUNS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "plus-slash-argument": (
        ("made-up-tool", f"{RANDOM}+/ab/{RANDOM}"),
        ("made-up-tool", f"{RANDOM}+/cd/{RANDOM}"),
        ("made-up-tool", HIDDEN),
    ),
    "plus-slash-option-value": (
        ("made-up-tool", "--model", f"ab+/{RANDOM}"),
        ("made-up-tool", "--model", f"cd+/{RANDOM}"),
        ("made-up-tool", "--model", HIDDEN),
    ),
    "plus-slash-after-equals": (
        ("made-up-tool", f"--model={RANDOM}+/ab"),
        ("made-up-tool", f"--model={RANDOM}+/cd"),
        ("made-up-tool", f"--model={HIDDEN}"),
    ),
    "plus-slash-in-a-shell-command": (
        ("sh", "-c", f"made-up-tool --model {RANDOM}+/ab/{RANDOM} --fast"),
        ("sh", "-c", f"made-up-tool --model {RANDOM}+/cd/{RANDOM} --fast"),
        ("sh", "-c", f"made-up-tool --model {HIDDEN} --fast"),
    ),
    "glued-to-a-short-option": (
        ("made-up-tool", f"-kab/{RANDOM}"),
        ("made-up-tool", f"-kcd/{RANDOM}"),
        ("made-up-tool", f"-k{HIDDEN}"),
    ),
    "plus-slash-in-an-absolute-path": (
        ("made-up-tool", f"/made/ab+/{RANDOM}"),
        ("made-up-tool", f"/made/cd+/{RANDOM}"),
        ("made-up-tool", HIDDEN),
    ),
    # A base64 value whose random part is hidden: its parts made of words go with it.
    "base64-with-a-hidden-part": (
        (
            "made-up-tool",
            f"{RANDOM}/MadeUpExampleTensorBatchNormLayer+MadeUpExampleKernelQueueVectorTable=",
        ),
        (
            "made-up-tool",
            f"{RANDOM}/MadeUpExampleKernelVectorTableLayer+MadeUpExampleTensorBatchNormQueue=",
        ),
        ("made-up-tool", HIDDEN),
    ),
}
# A run that starts with ``/`` and holds a random-looking part, as an absolute path or a
# base64 value may, is hidden whole in the hash, as the shown command hides it: its short
# parts change between the two values, so a part kept would tell them apart.
SLASH_RUNS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "absolute-path": (
        ("made-up-tool", f"/made/up/{RANDOM}/w.bin"),
        ("made-up-tool", f"/made/ab/{RANDOM}/w.bin"),
        ("made-up-tool", f"{HIDDEN}.bin"),
    ),
    "path-glued-to-a-short-option": (
        ("made-up-tool", f"-I/made/up/{RANDOM}"),
        ("made-up-tool", f"-I/made/ab/{RANDOM}"),
        ("made-up-tool", f"-I{HIDDEN}"),
    ),
    "absolute-path-with-a-plus": (
        ("made-up-tool", f"/made/up+x/{RANDOM}/w.bin"),
        ("made-up-tool", f"/made/ab+y/{RANDOM}/w.bin"),
        ("made-up-tool", f"{HIDDEN}.bin"),
    ),
    "path-from-the-working-folder": (
        ("made-up-tool", f"./made/up/{RANDOM}/w.bin"),
        ("made-up-tool", f"./made/ab/{RANDOM}/w.bin"),
        ("made-up-tool", f".{HIDDEN}.bin"),
    ),
    "path-from-the-home-folder": (
        ("made-up-tool", f"~/made/up/{RANDOM}/w.bin"),
        ("made-up-tool", f"~/made/ab/{RANDOM}/w.bin"),
        ("made-up-tool", f"~{HIDDEN}.bin"),
    ),
    "base64-that-starts-with-a-slash": (
        ("made-up-tool", f"/v/{RANDOM}"),
        ("made-up-tool", f"/ab/{RANDOM}"),
        ("made-up-tool", HIDDEN),
    ),
    "after-a-name": (
        ("made-up-tool", f"MODEL_NAME=/v/{RANDOM}"),
        ("made-up-tool", f"MODEL_NAME=/n6/{RANDOM}"),
        ("made-up-tool", f"MODEL_NAME={HIDDEN}"),
    ),
    "after-a-colon": (
        ("made-up-tool", f"name:/n6/{RANDOM}"),
        ("made-up-tool", f"name:/v/{RANDOM}"),
        ("made-up-tool", f"name:{HIDDEN}"),
    ),
    "after-an-option-and-equals": (
        ("made-up-tool", f"--model=/abc/{RANDOM}"),
        ("made-up-tool", f"--model=/xyz/{RANDOM}"),
        ("made-up-tool", f"--model={HIDDEN}"),
    ),
    "in-a-shell-command": (
        ("sh", "-c", f"made-up-tool /v/{RANDOM} && echo ok"),
        ("sh", "-c", f"made-up-tool /ab/{RANDOM} && echo ok"),
        ("sh", "-c", f"made-up-tool {HIDDEN} && echo ok"),
    ),
}


@pytest.mark.parametrize(("one", "two", "shown"), list(WHOLE_RUNS.values()), ids=list(WHOLE_RUNS))
def test_a_run_the_shown_command_hides_whole_is_hidden_whole_in_the_hash(
    one: tuple[str, ...], two: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    assert [model.hashed_argv(list(one)), model.hashed_argv(list(two))] == [list(shown)] * 2
    assert argv_sha256(one) == argv_sha256(two) == argv_sha256(shown)


@pytest.mark.parametrize(("one", "two", "shown"), list(SLASH_RUNS.values()), ids=list(SLASH_RUNS))
def test_a_run_that_starts_with_a_slash_is_hidden_whole_in_the_hash_as_it_is_shown(
    one: tuple[str, ...], two: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    assert [model.hashed_argv(list(one)), model.hashed_argv(list(two))] == [list(shown)] * 2
    assert argv_sha256(one) == argv_sha256(two) == argv_sha256(shown)
    assert model.public_command(one) == model.public_command(two)


@pytest.mark.parametrize(("one", "two"), list(KEPT.values()), ids=list(KEPT))
def test_a_path_a_host_and_an_ordinary_value_still_change_the_argument_hash(
    one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    assert model.hashed_argv(list(one)) == list(one)
    assert argv_sha256(one) != argv_sha256(two)


def test_an_argument_list_without_a_secret_hashes_as_its_plain_canonical_json() -> None:
    assert model.hashed_argv(list(PLAIN_ARGV)) == list(PLAIN_ARGV)
    assert argv_sha256(PLAIN_ARGV) == sha256_hex(canonical_json(list(PLAIN_ARGV)))


@pytest.mark.parametrize("option", ["-c", "-lc"])
def test_the_text_after_c_keeps_its_other_words_in_the_hash(option: str) -> None:
    # The text after -c is a command: only the value of the name is hidden, so the words
    # after it still tell two commands apart.
    one = ("sh", option, f"API_KEY={SECRET} ./made-up-one -v")
    two = ("sh", option, f"API_KEY={SECRET} ./made-up-two -v")
    assert model.hashed_argv(list(one)) == ["sh", option, f"API_KEY={HIDDEN} ./made-up-one -v"]
    assert argv_sha256(one) != argv_sha256(two)


def test_an_argument_after_the_text_of_c_is_read_whole_again() -> None:
    # Only the one argument after -c is read word by word; the next one is a value again.
    one = ("sh", "-c", 'made-up-tool "$1"', "--api-key=made kiwi7")
    two = ("sh", "-c", 'made-up-tool "$1"', "--api-key=made plum4")
    assert model.hashed_argv(list(one)) == ["sh", "-c", 'made-up-tool "$1"', f"--api-key={HIDDEN}"]
    assert argv_sha256(one) == argv_sha256(two)


# --- the fingerprint ----------------------------------------------------------------

# Launch settings that hold a secret, each made with a word in its place: a side's
# arguments, an image's entrypoint read with its arguments, a side's environment and the
# shared environment.
LAUNCHES: dict[str, Callable[[str], dict[str, Any]]] = {
    "arguments": lambda s: LaunchSettings().effective(args=("made-up-tool", "--password", s)),
    "entrypoint-and-arguments": lambda s: LaunchSettings().effective(
        args=("-a", s), entrypoint="redis-benchmark"
    ),
    "credential-variable": lambda s: LaunchSettings().effective(env={"API_TOKEN": s}),
    "address-in-a-variable": lambda s: LaunchSettings().effective(
        env={"MADE_UP_URL": f"postgres://madeup:{s}@made-up.example/db"}
    ),
    "options-in-a-variable": lambda s: LaunchSettings().effective(
        env={"MADE_UP_FLAGS": f"--fast --token {s}"}
    ),
    "shared-environment": lambda s: LaunchSettings(env={"HF_TOKEN": s}).effective(),
}


@pytest.mark.parametrize("make", list(LAUNCHES.values()), ids=list(LAUNCHES))
def test_the_fingerprint_of_a_secret_is_the_fingerprint_of_the_hidden_marker(
    make: Callable[[str], dict[str, Any]],
) -> None:
    hidden = fingerprint_of(IDENTITY, make(HIDDEN))
    assert [fingerprint_of(IDENTITY, make(word)) for word in WORDS] == [hidden, hidden]


@pytest.mark.parametrize(("name", "form", "shown", "secrets"), ALL_FORMS, ids=FORM_IDS)
def test_the_fingerprint_hides_each_recognised_form_in_the_arguments(
    name: str, form: tuple[str, ...], shown: tuple[str, ...], secrets: tuple[str, str]
) -> None:
    expected = sha256_hex(
        canonical_json(
            {"identity": HASHED_IDENTITY, "launch": LaunchSettings().effective(args=list(shown))}
        )
    )
    for secret in secrets:
        launch = LaunchSettings().effective(args=typed(form, secret))
        assert fingerprint_of(IDENTITY, launch) == expected


@pytest.mark.parametrize(("one", "two"), list(KEPT.values()), ids=list(KEPT))
def test_a_path_a_host_and_an_ordinary_value_still_change_the_fingerprint(
    one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    first = fingerprint_of(IDENTITY, LaunchSettings().effective(args=one))
    second = fingerprint_of(IDENTITY, LaunchSettings().effective(args=two))
    assert first != second


# Launch settings that hold a value with a space, each made with such a value in its place:
# a side's arguments, a client's glued password read with the image's entrypoint, and a
# variable whose value is a text of options, the value quoted in it.
SPACED_LAUNCHES: dict[str, Callable[[str], dict[str, Any]]] = {
    "arguments": lambda s: LaunchSettings().effective(args=("made-up-tool", f"--api-key={s}")),
    "entrypoint-and-glued-password": lambda s: LaunchSettings().effective(
        args=(f"-a{s}", "ping"), entrypoint="redis-cli"
    ),
    "options-in-a-variable": lambda s: LaunchSettings().effective(
        env={"MADE_UP_FLAGS": f"--api-key='{s}' --fast"}
    ),
}


@pytest.mark.parametrize("make", list(SPACED_LAUNCHES.values()), ids=list(SPACED_LAUNCHES))
def test_the_fingerprint_of_a_spaced_secret_is_the_fingerprint_of_the_hidden_marker(
    make: Callable[[str], dict[str, Any]],
) -> None:
    hidden = fingerprint_of(IDENTITY, make(HIDDEN))
    assert [fingerprint_of(IDENTITY, make(value)) for value in SPACED] == [hidden, hidden]


# A text that is no argument of a command, as the value of a variable, is read word by word:
# a credential at its start hides its own value only, and the words after it still tell two
# sides apart, so two sides that differ in them are not one side and do not pool.
FLAGS_TYPED = ("--api-key=madeup --threads 8", "--api-key=madeup --threads 16")
FLAGS_HASHED = (f"--api-key={HIDDEN} --threads 8", f"--api-key={HIDDEN} --threads 16")


def test_a_variable_that_starts_with_a_credential_keeps_its_other_words_in_the_fingerprint() -> (
    None
):
    def launch(text: str) -> dict[str, Any]:
        return LaunchSettings().effective(env={"MADE_UP_FLAGS": text})

    expected = [
        sha256_hex(canonical_json({"identity": HASHED_IDENTITY, "launch": launch(text)}))
        for text in FLAGS_HASHED
    ]
    assert [fingerprint_of(IDENTITY, launch(text)) for text in FLAGS_TYPED] == expected
    assert expected[0] != expected[1]


def test_a_variable_that_starts_with_a_credential_keeps_its_other_words_in_the_config_hash() -> (
    None
):
    def config(text: str) -> dict[str, Any]:
        sides = {"a": {"cmd": ["made-up-tool"], "baseline": True}, "b": {"cmd": ["made-up-other"]}}
        experiment = {"sides": sides, "launch": {"env": {"MADE_UP_FLAGS": text}}}
        return Experiment.from_json(experiment).to_json()

    expected = [sha256_hex(canonical_json(config(text))) for text in FLAGS_HASHED]
    assert [config_sha256(config(text)) for text in FLAGS_TYPED] == expected
    assert expected[0] != expected[1]


def test_launch_settings_without_a_secret_fingerprint_as_the_plain_formula() -> None:
    plain = {"identity": HASHED_IDENTITY, "launch": PLAIN_FINGERPRINT_LAUNCH}
    assert fingerprint_of(IDENTITY, PLAIN_FINGERPRINT_LAUNCH) == sha256_hex(canonical_json(plain))


def test_the_hash_of_the_executable_is_hashed_whole() -> None:
    # A bare hash is random-looking; in the identity it is no typed value and stays whole.
    other = {**IDENTITY, "executable_sha256": "cd" * 32}
    launch = LaunchSettings().effective()
    assert fingerprint_of(IDENTITY, launch) != fingerprint_of(other, launch)


def test_the_names_of_passed_variables_and_the_mounts_are_hashed_as_they_stand() -> None:
    launch = dict(PLAIN_FINGERPRINT_LAUNCH)
    passed = {**launch, "env_pass": ["API_KEY"]}
    mounted = {**launch, "mounts": ["/made/up/other:/models:ro"]}
    hashes = {fingerprint_of(IDENTITY, each) for each in (launch, passed, mounted)}
    assert len(hashes) == 3


# --- the hash of the config ---------------------------------------------------------


def command_config(secret: str) -> dict[str, Any]:
    """A config of command and image sides with ``secret`` in every field the hash reads."""
    return Experiment.from_json(
        {
            "workload": {"argv": ["made-up-load", "--token", secret]},
            "sides": {
                "a": {
                    "cmd": ["made-up-tool", "--password", secret, "{workload}"],
                    "baseline": True,
                    "launch": {
                        "env": {"API_TOKEN": secret},
                        "identify": ["made-up-tool", f"--api-key={secret}", "--version"],
                    },
                },
                "b": {
                    "image": "registry.example/made-up:1",
                    "entrypoint": "redis-benchmark",
                    "args": ["-a", secret],
                    "env": {
                        "MADE_UP_URL": f"postgres://madeup:{secret}@made-up.example/db",
                        "HF_TOKEN": secret,
                    },
                },
            },
            "launch": {
                "env": {"MADE_UP_FLAGS": f"--token {secret}"},
                "identify": ["made-up-tool", "-H", f"Authorization: Bearer {secret}"],
            },
        }
    ).to_json()


def serving_config(secret: str) -> dict[str, Any]:
    """A config of serving sides with ``secret`` in every field the hash reads."""
    return Experiment.from_json(
        {
            "workload": {"driver": "guidellm", "levels": [1]},
            "sides": {
                "c": {
                    "baseline": True,
                    "serve": {
                        "image": "registry.example/made-up:1",
                        "args": ["--api-key", secret],
                        "env": {"MADE_UP_FLAGS": f"--token {secret}"},
                        "ready": {"http": f"/health?token={secret}"},
                        "probe": {
                            "path": f"/v1/check?api_key={secret}",
                            "body": {"api_key": secret, "prompt": "made up", "max_tokens": 4},
                        },
                    },
                },
                "d": {
                    "serve": {
                        "launcher": "host",
                        "command": ["made-up-server", "--token", secret],
                        "args": ["--port", "8000", f"API_KEY={secret}"],
                    }
                },
            },
        }
    ).to_json()


def plug_in_config(secret: str) -> dict[str, Any]:
    """A config of sides of a plug-in kind, whose spec is one text with ``secret`` in it."""
    return Experiment.from_json(
        {
            "sides": {
                "e": {
                    "kind": "made-up",
                    "spec": f"made-up-thing --token {secret}",
                    "baseline": True,
                },
                "f": {"kind": "made-up", "spec": "made-up-thing"},
            }
        }
    ).to_json()


CONFIGS = {"command": command_config, "serving": serving_config, "plug-in": plug_in_config}


@pytest.mark.parametrize("make", list(CONFIGS.values()), ids=list(CONFIGS))
def test_the_config_hash_of_a_secret_is_the_config_hash_of_the_hidden_marker(
    make: Callable[[str], dict[str, Any]],
) -> None:
    hidden = config_sha256(make(HIDDEN))
    assert [config_sha256(make(word)) for word in WORDS] == [hidden, hidden]
    assert config_sha256(make(SECRET)) != sha256_hex(canonical_json(make(SECRET)))


def test_a_config_without_a_secret_hashes_as_its_plain_canonical_json() -> None:
    config = Experiment.from_json(
        {
            "sides": {
                "a": {"cmd": list(PLAIN_ARGV), "baseline": True},
                "b": {"cmd": ["/made/up/other/tool", "--size", "2"]},
            },
            "launch": {
                "env": {"MADE_UP_MODE": "fast"},
                "env_pass": ["API_TOKEN"],
                "mounts": ["/made/up/models:/models:ro"],
            },
        }
    ).to_json()
    assert config_sha256(config) == sha256_hex(canonical_json(config))


def _command_config(argv: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """A config of two command sides, the baseline running ``argv``."""
    sides = {"a": {"cmd": list(argv), "baseline": True}, "b": {"cmd": ["made-up-other"]}}
    return Experiment.from_json({"sides": sides}).to_json()


@pytest.mark.parametrize(("name", "form", "shown", "secrets"), ALL_FORMS, ids=FORM_IDS)
def test_the_config_hash_hides_each_recognised_form_in_a_command(
    name: str, form: tuple[str, ...], shown: tuple[str, ...], secrets: tuple[str, str]
) -> None:
    expected = sha256_hex(canonical_json(_command_config(shown)))
    hashes = [config_sha256(_command_config(typed(form, secret))) for secret in secrets]
    assert hashes == [expected, expected]


@pytest.mark.parametrize(("one", "two"), list(KEPT.values()), ids=list(KEPT))
def test_a_path_a_host_and_an_ordinary_value_still_change_the_config_hash(
    one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    def config(argv: tuple[str, ...]) -> dict[str, Any]:
        sides = {"a": {"cmd": list(argv), "baseline": True}, "b": {"cmd": ["made-up-other"]}}
        return Experiment.from_json({"sides": sides}).to_json()

    assert config_sha256(config(one)) != config_sha256(config(two))
