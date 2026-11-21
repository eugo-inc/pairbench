# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Ordinary settings stay in the shown command and in the hashes; secrets stay hidden.

An option whose name counts, sizes, bounds, prefixes, patterns or measures keys
or tokens (``--key-size``, ``--max-num-queued-tokens``, ``--token-budget``) is
no credential: its value is shown and tells two sides apart in every hash. So
is a compiler pass's table (``"pass_config"``), the axis ``Key`` of a
benchmark (``-a Key=I32``) and the word after a switch whose name only looks
like a credential (``--allow-credentials``). Every credential form of the
serving and load tools stays hidden, and its value changes no hash.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pairbench.model import (
    HIDDEN,
    Experiment,
    Side,
    config_sha256,
    hashed_argv,
    looks_like_credential,
    public_command,
    public_words,
)

# Two made-up passwords.
SECRET = "kiwi7"
OTHER = "plum4"

VLLM = ("vllm", "serve", "org/model-a")
MEMTIER = ("memtier_benchmark",)
TOOL = ("made-up-tool",)
BENCH = ("made-up-bench",)
AIPERF = ("aiperf", "profile")

# Each ordinary setting: the argument list with one value, with another, and how the
# first is shown.
ORDINARY: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "queued-tokens": (
        (*VLLM, "--max-num-queued-tokens", "1024"),
        (*VLLM, "--max-num-queued-tokens", "4096"),
        "vllm serve org/model-a --max-num-queued-tokens 1024",
    ),
    "queued-tokens-with-equals": (
        (*VLLM, "--max-num-queued-tokens=1024"),
        (*VLLM, "--max-num-queued-tokens=4096"),
        "vllm serve org/model-a --max-num-queued-tokens=1024",
    ),
    "scheduled-tokens": (
        (*VLLM, "--max-num-scheduled-tokens", "512"),
        (*VLLM, "--max-num-scheduled-tokens", "2048"),
        "vllm serve org/model-a --max-num-scheduled-tokens 512",
    ),
    "scheduled-tokens-with-equals": (
        (*VLLM, "--max-num-scheduled-tokens=512"),
        (*VLLM, "--max-num-scheduled-tokens=2048"),
        "vllm serve org/model-a --max-num-scheduled-tokens=512",
    ),
    "token-threshold": (
        (*VLLM, "--dbo-decode-token-threshold", "32"),
        (*VLLM, "--dbo-decode-token-threshold", "64"),
        "vllm serve org/model-a --dbo-decode-token-threshold 32",
    ),
    "token-threshold-with-equals": (
        (*VLLM, "--dbo-decode-token-threshold=32"),
        (*VLLM, "--dbo-decode-token-threshold=64"),
        "vllm serve org/model-a --dbo-decode-token-threshold=32",
    ),
    "pass-config": (
        (*VLLM, "--compilation-config", '{"pass_config": {"enable_noop": true}}'),
        (*VLLM, "--compilation-config", '{"pass_config": {"enable_noop": false}}'),
        'vllm serve org/model-a --compilation-config \'{"pass_config": {"enable_noop": true}}\'',
    ),
    "allow-credentials-before-the-model": (
        ("vllm", "serve", "--allow-credentials", "org/model-a"),
        ("vllm", "serve", "--allow-credentials", "org/model-b"),
        "vllm serve --allow-credentials org/model-a",
    ),
    "no-allow-credentials-before-the-model": (
        ("vllm", "serve", "--no-allow-credentials", "org/model-a"),
        ("vllm", "serve", "--no-allow-credentials", "org/model-b"),
        "vllm serve --no-allow-credentials org/model-a",
    ),
    "token-ids-switch-before-the-model": (
        ("vllm", "serve", "--return-tokens-as-token-ids", "org/model-a"),
        ("vllm", "serve", "--return-tokens-as-token-ids", "org/model-b"),
        "vllm serve --return-tokens-as-token-ids org/model-a",
    ),
    "no-token-ids-switch-before-the-model": (
        ("vllm", "serve", "--no-return-tokens-as-token-ids", "org/model-a"),
        ("vllm", "serve", "--no-return-tokens-as-token-ids", "org/model-b"),
        "vllm serve --no-return-tokens-as-token-ids org/model-a",
    ),
    "allowed-token-ids": (
        (*VLLM, "--override-generation-config", '{"allowed_token_ids": [11, 12]}'),
        (*VLLM, "--override-generation-config", '{"allowed_token_ids": [13, 14]}'),
        "vllm serve org/model-a --override-generation-config '{\"allowed_token_ids\": [11, 12]}'",
    ),
    "key-prefix": (
        (*MEMTIER, "--key-prefix", "made-up-a-"),
        (*MEMTIER, "--key-prefix", "made-up-b-"),
        "memtier_benchmark --key-prefix made-up-a-",
    ),
    "key-minimum": (
        (*MEMTIER, "--key-minimum", "1"),
        (*MEMTIER, "--key-minimum", "2"),
        "memtier_benchmark --key-minimum 1",
    ),
    "key-maximum": (
        (*MEMTIER, "--key-maximum", "999"),
        (*MEMTIER, "--key-maximum", "888"),
        "memtier_benchmark --key-maximum 999",
    ),
    "key-pattern": (
        (*MEMTIER, "--key-pattern", "R:R"),
        (*MEMTIER, "--key-pattern", "G:G"),
        "memtier_benchmark --key-pattern R:R",
    ),
    "key-stddev": (
        (*MEMTIER, "--key-stddev", "2.5"),
        (*MEMTIER, "--key-stddev", "3.5"),
        "memtier_benchmark --key-stddev 2.5",
    ),
    "key-median": (
        (*MEMTIER, "--key-median", "50"),
        (*MEMTIER, "--key-median", "60"),
        "memtier_benchmark --key-median 50",
    ),
    "key-size-glued": (
        ("db_bench", "--key_size=16"),
        ("db_bench", "--key_size=32"),
        "db_bench --key_size=16",
    ),
    "keys-per-prefix": (
        ("db_bench", "--keys_per_prefix", "4"),
        ("db_bench", "--keys_per_prefix", "8"),
        "db_bench --keys_per_prefix 4",
    ),
    "keys-per-prefix-glued": (
        ("db_bench", "--keys_per_prefix=4"),
        ("db_bench", "--keys_per_prefix=8"),
        "db_bench --keys_per_prefix=4",
    ),
    "key-size": (
        (*TOOL, "--key-size", "16"),
        (*TOOL, "--key-size", "32"),
        "made-up-tool --key-size 16",
    ),
    "num-keys": (
        (*TOOL, "--num-keys", "9"),
        (*TOOL, "--num-keys", "7"),
        "made-up-tool --num-keys 9",
    ),
    "token-budget": (
        (*TOOL, "--token-budget", "64"),
        (*TOOL, "--token-budget", "128"),
        "made-up-tool --token-budget 64",
    ),
    "keys": (
        (*TOOL, "--keys", "7"),
        (*TOOL, "--keys", "9"),
        "made-up-tool --keys 7",
    ),
    "max-keys": (
        (*TOOL, "--max-keys", "8"),
        (*TOOL, "--max-keys", "6"),
        "made-up-tool --max-keys 8",
    ),
    "benchmark-filter": (
        (*BENCH, "--benchmark_filter=BM_x/key_size:16"),
        (*BENCH, "--benchmark_filter=BM_x/key_size:32"),
        "made-up-bench --benchmark_filter=BM_x/key_size:16",
    ),
    "benchmark-context": (
        (*BENCH, "--benchmark_context=key_size=16"),
        (*BENCH, "--benchmark_context=key_size=32"),
        "made-up-bench --benchmark_context=key_size=16",
    ),
    "axis-key": (
        (*BENCH, "-a", "Key=I32"),
        (*BENCH, "-a", "Key=I64"),
        "made-up-bench -a Key=I32",
    ),
    "axis-long-key": (
        (*BENCH, "--axis", "Key=I32"),
        (*BENCH, "--axis", "Key=I64"),
        "made-up-bench --axis Key=I32",
    ),
    "axis-num-keys": (
        (*BENCH, "-a", "NumKeys=16"),
        (*BENCH, "-a", "NumKeys=32"),
        "made-up-bench -a NumKeys=16",
    ),
    "axis-glued": (
        (*BENCH, "--axis=Key=I32"),
        (*BENCH, "--axis=Key=I64"),
        "made-up-bench --axis=Key=I32",
    ),
    "axis-short-glued": (
        (*BENCH, "-aKey=I32"),
        (*BENCH, "-aKey=I64"),
        "made-up-bench -aKey=I32",
    ),
    "goodput": (
        (*AIPERF, "--goodput", "inter_token_latency:10"),
        (*AIPERF, "--goodput", "inter_token_latency:20"),
        "aiperf profile --goodput inter_token_latency:10",
    ),
    "passages-token-mean": (
        (*AIPERF, "--rankings-passages-prompt-token-mean", "64"),
        (*AIPERF, "--rankings-passages-prompt-token-mean", "32"),
        "aiperf profile --rankings-passages-prompt-token-mean 64",
    ),
    "passages-token-stddev": (
        (*AIPERF, "--rankings-passages-prompt-token-stddev", "4"),
        (*AIPERF, "--rankings-passages-prompt-token-stddev", "8"),
        "aiperf profile --rankings-passages-prompt-token-stddev 4",
    ),
    "query-token-mean": (
        (*AIPERF, "--rankings-query-prompt-token-mean", "32"),
        (*AIPERF, "--rankings-query-prompt-token-mean", "16"),
        "aiperf profile --rankings-query-prompt-token-mean 32",
    ),
    "query-token-stddev": (
        (*AIPERF, "--rankings-query-prompt-token-stddev", "2"),
        (*AIPERF, "--rankings-query-prompt-token-stddev", "3"),
        "aiperf profile --rankings-query-prompt-token-stddev 2",
    ),
    "command-text": (
        ("hyperfine", "made-up-tool --key-size 16"),
        ("hyperfine", "made-up-tool --key-size 32"),
        "hyperfine 'made-up-tool --key-size 16'",
    ),
}

# Each secret form: the argument list, ``{}`` standing for the secret, and how it is shown.
SECRETS: dict[str, tuple[tuple[str, ...], str]] = {
    "api-key": ((*VLLM, "--api-key", "{}"), "vllm serve org/model-a --api-key '<hidden>'"),
    "hf-token": ((*VLLM, "--hf-token", "{}"), "vllm serve org/model-a --hf-token '<hidden>'"),
    "s3-access-key-id": (
        (*VLLM, "--s3-access-key-id", "{}"),
        "vllm serve org/model-a --s3-access-key-id '<hidden>'",
    ),
    "s3-secret-access-key": (
        (*VLLM, "--s3-secret-access-key", "{}"),
        "vllm serve org/model-a --s3-secret-access-key '<hidden>'",
    ),
    "ssl-keyfile": (
        (*VLLM, "--ssl-keyfile", "made-up/{}.pem"),
        "vllm serve org/model-a --ssl-keyfile '<hidden>'",
    ),
    "encryption-keyfile": (
        (*VLLM, "--encryption-keyfile", "made-up/{}"),
        "vllm serve org/model-a --encryption-keyfile '<hidden>'",
    ),
    "aiperf-api-key": ((*AIPERF, "--api-key", "{}"), "aiperf profile --api-key '<hidden>'"),
    "guidellm-api-key": (
        ("guidellm", "benchmark", "--backend-kwargs", "api_key={}"),
        "guidellm benchmark --backend-kwargs 'api_key=<hidden>'",
    ),
    "guidellm-api-key-in-json": (
        ("guidellm", "benchmark", "--backend-kwargs", '{"api_key": "{}"}'),
        'guidellm benchmark --backend-kwargs \'{"api_key": "<hidden>"}\'',
    ),
    "redis-benchmark-a": (("redis-benchmark", "-a", "{}"), "redis-benchmark -a '<hidden>'"),
    "memtier-authenticate": (
        (*MEMTIER, "--authenticate", "{}"),
        "memtier_benchmark --authenticate '<hidden>'",
    ),
    "memtier-authenticate-with-equals": (
        (*MEMTIER, "--authenticate={}"),
        "memtier_benchmark '--authenticate=<hidden>'",
    ),
    "memtier-a": ((*MEMTIER, "-a", "{}"), "memtier_benchmark -a '<hidden>'"),
    # A switch word at the start of a name does not make an option a switch.
    "with-password": ((*TOOL, "--with-password", "{}"), "made-up-tool --with-password '<hidden>'"),
    "use-auth-token": (
        (*TOOL, "--use-auth-token", "{}"),
        "made-up-tool --use-auth-token '<hidden>'",
    ),
    "with-token": ((*TOOL, "--with-token", "{}"), "made-up-tool --with-token '<hidden>'"),
    "require-pass": ((*TOOL, "--require-pass", "{}"), "made-up-tool --require-pass '<hidden>'"),
    # A measure after a key or a token of a credential still names a credential.
    "api-key-prefix": (
        (*TOOL, "--api-key-prefix", "{}"),
        "made-up-tool --api-key-prefix '<hidden>'",
    ),
    "access-token-limit": (
        (*TOOL, "--access-token-limit", "{}"),
        "made-up-tool --access-token-limit '<hidden>'",
    ),
    "key-alone": ((*TOOL, "--key", "{}"), "made-up-tool --key '<hidden>'"),
    "pass-alone": ((*TOOL, "--pass", "{}"), "made-up-tool --pass '<hidden>'"),
    "pass-in-a-table": (
        (*TOOL, "--config", '{"pass": "{}"}'),
        'made-up-tool --config \'{"pass": "<hidden>"}\'',
    ),
    "pass-config-after-a-word": (
        (*TOOL, "--config", '{"db_pass_config": "{}"}'),
        'made-up-tool --config \'{"db_pass_config": "<hidden>"}\'',
    ),
    # Only the axis named Key or Keys, after -a or --axis or glued to it, is shown.
    "key-variable": (("env", "KEY={}", "made-up-tool"), "env 'KEY=<hidden>' made-up-tool"),
    "key-variable-option": ((*TOOL, "-e", "KEY={}"), "made-up-tool -e 'KEY=<hidden>'"),
    "axis-password": ((*BENCH, "-a", "Password={}"), "made-up-bench -a 'Password=<hidden>'"),
    "axis-glued-token": ((*BENCH, "--axis=Token={}"), "made-up-bench '--axis=Token=<hidden>'"),
}


def typed(form: tuple[str, ...], secret: str) -> list[str]:
    return [arg.replace("{}", secret) for arg in form]


@pytest.mark.parametrize(("one", "two", "shown"), list(ORDINARY.values()), ids=list(ORDINARY))
def test_an_ordinary_setting_is_shown_and_changes_the_argument_hash(
    one: tuple[str, ...], two: tuple[str, ...], shown: str
) -> None:
    assert public_command(one) == shown
    assert hashed_argv(one) == list(one)
    assert hashed_argv(one) != hashed_argv(two)


@pytest.mark.parametrize(("form", "shown"), list(SECRETS.values()), ids=list(SECRETS))
def test_a_secret_of_the_serving_and_load_tools_stays_hidden_in_the_hash(
    form: tuple[str, ...], shown: str
) -> None:
    assert public_command(typed(form, SECRET)) == shown
    assert SECRET not in shown
    assert hashed_argv(typed(form, SECRET)) == hashed_argv(typed(form, OTHER))
    assert hashed_argv(typed(form, SECRET)) == hashed_argv(typed(form, HIDDEN))


def _plug_in_config(spec: Any) -> dict[str, Any]:
    """A config of two sides of a plug-in kind; the baseline's spec is ``spec``."""
    return Experiment.from_json(
        {
            "sides": {
                "e": {"kind": "made-up", "spec": spec, "baseline": True},
                "f": {"kind": "made-up", "spec": "made-up-thing"},
            }
        }
    ).to_json()


def test_a_plug_in_spec_given_as_a_list_hides_its_credential_in_the_config_hash() -> None:
    def config(word: str) -> dict[str, Any]:
        return _plug_in_config({"args": ["--token", word]})

    hidden = config_sha256(config(HIDDEN))
    assert [config_sha256(config(word)) for word in (SECRET, OTHER)] == [hidden, hidden]
    assert config_sha256(_plug_in_config({"args": ["--size", "1"]})) != config_sha256(
        _plug_in_config({"args": ["--size", "2"]})
    )


def test_a_plug_in_side_made_in_python_with_a_list_spec_hides_its_credential() -> None:
    def config(word: str) -> dict[str, Any]:
        sides = (
            Side(name="e", kind="made-up", spec={"spec": ["--token", word]}).with_role("baseline"),
            Side(name="f", kind="made-up", spec={"spec": "made-up-thing"}),
        )
        return Experiment(sides=sides).to_json()

    hidden = config_sha256(config(HIDDEN))
    assert [config_sha256(config(word)) for word in (SECRET, OTHER)] == [hidden, hidden]


# A folder named with ``++`` inside a relative path, and the forms around it that stay cut or
# hidden: an absolute path after one ``+``, and a random-looking run that holds ``+/``.
PLUS_PATHS: dict[str, tuple[tuple[str, ...], str]] = {
    "relative": (("g++", "proj/c++/bench.cc"), "g++ proj/c++/bench.cc"),
    "after-an-option": (
        ("made-up-tool", "--src=lib/c++/v1/x.h"),
        "made-up-tool --src=lib/c++/v1/x.h",
    ),
    "absolute": (("g++", "/made/up/c++/bench.cc"), "g++ bench.cc"),
    "after-one-plus": (("made-up-tool", "x+/home/made-up-user/f"), "made-up-tool x+f"),
    "random-run": (
        ("made-up-tool", "ab+/cdEFghIJklMNopQRstUVwxYZ0123456789+/abcdEFGH=="),
        "made-up-tool '<hidden>'",
    ),
}


@pytest.mark.parametrize(("argv", "shown"), list(PLUS_PATHS.values()), ids=list(PLUS_PATHS))
def test_a_folder_named_with_two_plus_signs_is_shown_as_written(
    argv: tuple[str, ...], shown: str
) -> None:
    assert public_command(argv) == shown


# A name far longer than any typed one, made of words that ask each measure and count rule;
# each is judged in a small part of a second.
LONG = 128_000
QUICK_S = 2.0
LONG_NAMES = {
    "plain-words": "-".join(["made"] * (LONG // 5)),
    "counted-keys": "-".join(["max", "key"] * (LONG // 8)),
    "measured-keys": "_".join(["key", "size"] * (LONG // 9)),
    "measure-at-the-end": "-".join([*["made"] * (LONG // 5), "key", "size"]),
    "glued-key-measure": "made" * (LONG // 4) + "keysize",
    "glued-token-measure": "made" * (LONG // 4) + "tokensize",
}


def _shortest(judge: Any, *args: Any) -> float:
    """The shortest of three timings of one call, in seconds."""
    times = []
    for _ in range(3):
        start = time.perf_counter()
        judge(*args)
        times.append(time.perf_counter() - start)
    return min(times)


@pytest.mark.parametrize("name", list(LONG_NAMES.values()), ids=list(LONG_NAMES))
def test_a_long_name_is_judged_quickly(name: str) -> None:
    assert looks_like_credential(name) is False
    assert _shortest(looks_like_credential, name) < QUICK_S


def test_an_axis_option_ends_at_a_command_separator() -> None:
    # After ``;`` the next command starts afresh: its ``Key=`` names a credential, not an axis.
    shown = public_words(f"made-up-bench -a; Key={SECRET} ./made-up-tool")
    assert shown == "made-up-bench -a; Key=<hidden> ./made-up-tool"
    assert public_words("made-up-bench -a Key=I32") == "made-up-bench -a Key=I32"
