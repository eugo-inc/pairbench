# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config page lists every form the shared files hide of a command, as the code holds them.

The note printed after a run points at the section; the section names every
client and option the code hides, the random-looking rule with its
constants, and says that a short plain password in any other form still
shows. The other pages that describe the shown command link to it.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model
from pairbench.errors import SHARED_COMMAND_ANCHOR

CONFIG_PAGE = "docs/reference/config.md"
HEADING = "What the shared files hide"
PLAIN_PASSWORD = "A short plain password in any other form still shows."
GENERATED_TOKEN = "A generated token that fails one of the tests still shows"
LINKING_PAGES = (
    ("docs/reference/commands.md", "config.md#what-the-shared-files-hide"),
    ("docs/reference/results-schema.md", "config.md#what-the-shared-files-hide"),
    ("docs/reference/text-format.md", "config.md#what-the-shared-files-hide"),
    ("docs/guides/hyperfine.md", "../reference/config.md#what-the-shared-files-hide"),
    ("docs/method/reporting-checklist.md", "../reference/config.md#what-the-shared-files-hide"),
    ("SECURITY.md", "docs/reference/config.md#what-the-shared-files-hide"),
)


def section(repo_root: Path) -> str:
    """The text of the section, up to the next heading of its level."""
    text = (repo_root / CONFIG_PAGE).read_text(encoding="utf-8")
    start = text.index(f"\n## {HEADING}\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def test_the_section_has_the_anchor_the_note_points_at(repo_root: Path) -> None:
    assert section(repo_root)
    assert HEADING.lower().replace(" ", "-") == SHARED_COMMAND_ANCHOR


def test_the_section_says_what_still_shows_and_where_secrets_belong(repo_root: Path) -> None:
    text = plain(section(repo_root))

    assert f"**{PLAIN_PASSWORD}**" in text
    assert "`launch.env_pass`" in text
    assert "`capture.jsonl`, keeps the command as typed" in text


def test_the_section_names_every_client_and_its_password_options(repo_root: Path) -> None:
    text = section(repo_root)
    missing: list[str] = []
    for program, options in model.CLIENT_PASSWORD_OPTIONS.items():
        rows = [line for line in text.splitlines() if f"`{program}`" in line]
        if not rows:
            missing.append(program)
            continue
        for option in (
            *options.secret,
            *options.joined,
            *options.credentials,
            *options.user_password,
            *options.sentinel,
            *options.acl_user,
        ):
            if not any(f"`{option}" in row for row in rows):
                missing.append(f"{program} {option}")
    assert missing == []


@pytest.mark.parametrize(
    "words",
    [
        *(f"`{option}`" for option in model.USER_PASSWORD_OPTIONS),
        *(f"`{header.title()}`" for header in model.SECRET_HEADERS),
        *(f"`{host.strip('[]')}`" for host in model.LOOPBACK_HOSTS),
        *(f"`{name}`" for name in model.DIGEST_NAMES),
        *(f"`{shell}`" for shell in model.SHELLS),
    ],
)
def test_the_section_names_every_option_header_host_and_digest(repo_root: Path, words: str) -> None:
    assert words in section(repo_root)


def test_the_section_states_each_constant_of_the_random_looking_rule(repo_root: Path) -> None:
    text = plain(section(repo_root))

    assert f"at least {model.RANDOM_MIN_LENGTH} characters long (`RANDOM_MIN_LENGTH`)" in text
    assert f"once in every {model.RANDOM_CHANGE_EVERY} characters (`RANDOM_CHANGE_EVERY`)" in text
    assert f"the number of changes times {model.RANDOM_CHANGE_EVERY} is at least" in text
    assert f"at least {model.RANDOM_MIN_CAPITAL_PAIRS} time (`RANDOM_MIN_CAPITAL_PAIRS`)" in text
    assert (
        f"less than {model.RANDOM_WORDS_SHOWN_PERCENT} percent of its characters "
        "(`RANDOM_WORDS_SHOWN_PERCENT`) are in words"
    ) in text
    assert (
        f"a capital followed by {model.RANDOM_WORD_SMALL_LETTERS} or more small letters "
        "(`RANDOM_WORD_SMALL_LETTERS`)"
    ) in text
    vowels = ", ".join(f"`{vowel}`" for vowel in model.RANDOM_WORD_VOWELS[:-1])
    assert (
        f"by 2 small letters one of which is a vowel, {vowels} or "
        f"`{model.RANDOM_WORD_VOWELS[-1]}` (`RANDOM_WORD_VOWELS`)"
    ) in text
    assert f"exactly {model.COMMIT_ID_LENGTH} characters is a commit id" in text
    assert f"under {model.RANDOM_MIN_LENGTH} characters it is shown" in text
    assert f"hexadecimal of {model.RANDOM_MIN_LENGTH} characters or more is hidden" in text


def test_the_section_states_the_shape_of_an_access_key_id(repo_root: Path) -> None:
    text = plain(section(repo_root))
    prefixes = " and ".join(f"`{prefix}`" for prefix in model.ACCESS_KEY_ID_PREFIXES)

    assert f"one of the prefixes {prefixes} (`ACCESS_KEY_ID_PREFIXES`)" in text
    assert (
        f"capitals and digits to {model.ACCESS_KEY_ID_LENGTH} characters in all "
        "(`ACCESS_KEY_ID_LENGTH`)"
    ) in text
    assert "so one glued to more letters or digits, as in `X` and an id, is shown" in text
    assert "unless it has the shape of an AWS access key id" in text


def test_the_section_says_which_generated_tokens_still_show(repo_root: Path) -> None:
    text = plain(section(repo_root))

    assert f"**{GENERATED_TOKEN}**" in text
    assert f"one under {model.RANDOM_MIN_LENGTH} characters" in text
    assert "without both capitals and small letters" in text


@pytest.mark.parametrize(("page", "link"), LINKING_PAGES)
def test_each_page_on_the_shown_command_links_to_the_section(
    repo_root: Path, page: str, link: str
) -> None:
    assert f"]({link})" in plain((repo_root / page).read_text(encoding="utf-8"))


def test_the_section_names_every_setting_word(repo_root: Path) -> None:
    text = plain(section(repo_root))
    words = ", ".join(f"`{word}`" for word in model.SETTING_WORDS[:-1])

    assert f"After {words} or `{model.SETTING_WORDS[-1]}` (`SETTING_WORDS`), in any case" in text
    assert "after its last `.`, `:` or `/`, looks like a credential" in text
    assert (
        "each later word of the command that is no option is hidden whatever its shape, and so "
        "is the value glued to a long option after its `=`"
    ) in text
    assert (
        "up to a separator, a line break, or the `)` or backquote that closes the command" in text
    )
    assert "names a credential setting too (`redis-cli CONFIG SET masterauth <hidden>`)" in text
    assert "A line break ends the options of `set` too" in text
    assert "`--` ends the setting" in text
    clients = ", ".join(f"`{name}`" for name in model.DATA_SET_CLIENTS[:-1])
    assert (
        f"After {clients} or `{model.DATA_SET_CLIENTS[-1]}` (`DATA_SET_CLIENTS`), `SET` writes "
        "the value of a key and starts no setting when it is the client's command"
    ) in text
    assert "and so does a `set` of a later command, after a separator or a line break" in text


def test_the_section_says_how_runs_with_a_slash_are_judged(repo_root: Path) -> None:
    text = plain(section(repo_root))

    assert (
        "A run that holds a `/` and a `+` or `=` padding, as base64 is written, and does not "
        "start with `/`, is judged whole first: when it looks random, it is hidden whole, "
        "wherever it stands"
    ) in text
    assert (
        "A run with a `+` or `=` padding that does not start with `/` is hidden whole when any "
        "part of it is, so no part of a base64 value shows beside a hidden one"
    ) in text
    assert (
        "a base64url value, written with `-` and `_`, without padding, shows its parts under "
        f"{model.RANDOM_MIN_LENGTH} characters"
    ) in text
    assert (
        "a part made only of digits, as a number argument is written, and a group name of small "
        "letters and digits that holds a `_` or `-` are left out of the share of words in test 5, "
        "each with its `/`; every other test reads the whole run"
    ) in text
    assert (
        "A run with a `/` and neither a `+` nor padding is judged whole between the words of a "
        "path at its ends"
    ) in text
    assert (
        "When what lies between them holds a `/` and looks random, it is hidden whole and the "
        "words around it stay shown"
    ) in text
    assert "When no word of a path comes before it, the whole run is hidden" in text
    assert (
        f"When what lies between them is shorter than {model.RANDOM_MIN_LENGTH} characters, it "
        "is read with up to two short words of a path on each side of it, which a key holds at "
        "an end by chance: words with no run of three small letters and no `-` or `_`"
    ) in text
    assert (
        f"When they make {model.RANDOM_MIN_LENGTH} characters or more and what lies between them "
        "passes tests 2 to 5 below, it is hidden with them"
    ) in text
    assert (
        "Inside a path, a base64 value written with `/`, with or without `+`, shows whole when "
        "what lies between the words of the path at its ends, read with up to two short words "
        f"beside it, is under {model.RANDOM_MIN_LENGTH} characters"
    ) in text
    assert (
        "An absolute path that holds one, and a path that starts with `./`, `../` or `~/`, is "
        "hidden whole"
    ) in text
    assert (
        "shows a part at either end of it that reads as a word of a path, such as `x9` or `ab`"
    ) in text


# The section's examples of a key after folders of small letters, as the page writes each value
# and what it shows, with ``<key>`` for a made-up key.
FOLDER_EXAMPLES = (
    ("srv/data/<key>/out.json", "srv/data/<hidden>/out.json"),
    ("srv/nfs/<key>/x.bin", "srv/nfs/<hidden>/x.bin"),
    ("v1/srv/nfs/<key>/x.bin", "v1/srv/nfs/<hidden>/x.bin"),
)
FOLDER_EXAMPLE_KEY = "EXAMPLETailFakezQ9/zQx9XyTAILRealUP"


def test_the_section_says_how_folders_of_small_letters_around_a_key_are_read(
    repo_root: Path,
) -> None:
    text = plain(section(repo_root))

    assert (
        "then with the parts of three small letters or more at its ends left out, and then with "
        "those parts and the words of a path before or between them left out"
    ) in text
    assert "The first of these readings that hides a key is the one used." in text
    for value, shown in FOLDER_EXAMPLES:
        assert f"`{value}` shows `{shown}`" in text
        argv = ["client", value.replace("<key>", FOLDER_EXAMPLE_KEY)]
        hidden = shown.replace("<hidden>", model.HIDDEN)
        assert model.hashed_argv(argv) == ["client", hidden]
        assert model.public_command(argv) == shlex.join(["client", hidden])


def test_the_section_says_hexadecimal_after_0x_follows_the_rule(repo_root: Path) -> None:
    text = plain(section(repo_root))

    assert "after `0x` or `0X`, the digits after it follow the same rule" in text
    assert f"`0x` and {model.COMMIT_ID_LENGTH} is shown as a commit id is" in text


# The query names the page gives for a percent-encoded base64 value hidden by its name.
QUERY_NAMES = ("token", "sig", "signature")


def test_the_section_says_which_percent_encoded_base64_values_show(repo_root: Path) -> None:
    text = plain(section(repo_root))
    names = ", ".join(f"`{name}`" for name in QUERY_NAMES[:-1])

    assert (
        "A base64 value written with percent escapes, as in a query value under a name that "
        "names nothing (`?part=`), shows whole when the text it stands for and each part of "
        "that text fail a test by chance"
    ) in text
    assert (
        f"Under a credential-like query name, such as {names} or `{QUERY_NAMES[-1]}`, it is "
        "hidden by its name."
    ) in text
    assert [name for name in QUERY_NAMES if not model.looks_like_credential(name)] == []
    assert not model.looks_like_credential("part")


# Examples on the page, as the code shows them; every value is made up.
SHOWN_EXAMPLES = (
    (
        ("aws", "configure", "set", "aws_secret_access_key", "zqm-made-up"),
        "aws configure set aws_secret_access_key <hidden>",
    ),
    (
        ("git", "config", "--global", "github.token", "zqm-made-up"),
        "git config --global github.token <hidden>",
    ),
    (
        ("redis-cli", "CONFIG", "SET", "requirepass", "zqm-made-up"),
        "redis-cli CONFIG SET requirepass <hidden>",
    ),
    (("setenv", "HF_TOKEN", "zqm-made-up"), "setenv HF_TOKEN <hidden>"),
    (
        ("redis-cli", "-h", "127.0.0.1", "SET", "key", "value"),
        "redis-cli -h 127.0.0.1 SET key value",
    ),
    (("git", "config", "credential.helper", "store"), "credential.helper store"),
    (("./bench", "sort_by_key", "64"), "./bench sort_by_key 64"),
    (("./bench", "api_key.pem", "out.json"), "./bench api_key.pem out.json"),
    (("gh", "auth", "token"), "gh auth token"),
    (("kubectl", "create", "secret", "generic", "NAME"), "kubectl create secret generic NAME"),
    (
        ("tool", "--hmac", "EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kE+Aw=="),
        "--hmac <hidden>",
    ),
    (
        ("tool", "BM_Crc32BatchNormMapTensorPut/4096/4"),
        "BM_Crc32BatchNormMapTensorPut/4096/4",
    ),
    (
        ("tool", "tree_parse/MapMaxHTTP2PopCopyCopy/16/64"),
        "tree_parse/MapMaxHTTP2PopCopyCopy/16/64",
    ),
    (("tool", "--seed", "0x" + "3f9a" * 8), "--seed <hidden>"),
    (("tool", "0xdeadbeef"), "0xdeadbeef"),
    (("tool", "data/" + "XYz9" * 10 + "/out.json"), "data/<hidden>/out.json"),
    # A key whose end parts read as short words of a path, hidden with them.
    (
        ("tool", "data/au/EXAMPLETailFakezQ9zQx9XyTAILRea/p+em2/out.json"),
        "data/<hidden>/out.json",
    ),
    (("tool", "../data/" + "XYz9" * 10 + "/out.json"), "..<hidden>.json"),
    # Hexadecimal of a commit id's length after no folder of a commit id.
    (
        ("tool", "http://localhost:8000/v1/hooks/" + "0badc0de" * 5 + "/notify"),
        "http://localhost:8000/v1/hooks/<hidden>/notify",
    ),
    (("client", "EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw"), "client <hidden>"),
    (
        (
            "tool",
            "http://localhost:8000/v1/files/EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw/raw",
        ),
        "http://localhost:8000/v1/files/<hidden>/raw",
    ),
    # A made-up access key id, as its prefix and a made-up tail.
    (("MODEL_NAME=AKIA" + "MADEUPEXAMPLE123", "tool"), "MODEL_NAME=<hidden>"),
    # The passwords of Redis and Valkey commands, and the words they keep.
    (
        ("redis-cli", "CONFIG", "SET", "masterauth", "zqm-made-up"),
        "redis-cli CONFIG SET masterauth <hidden>",
    ),
    (
        ("redis-cli", "CONFIG", "SET", "tls-key-file", "certs/redis.key"),
        "redis-cli CONFIG SET tls-key-file certs/redis.key",
    ),
    (
        ("redis-cli", "CONFIG", "SET", "tls-key-file-pass", "zqm-made-up"),
        "tls-key-file-pass <hidden>",
    ),
    (("redis-cli", "AUTH", "zqm-made-up"), "AUTH <hidden>"),
    (("redis-cli", "AUTH", "user", "zqm-made-up"), "AUTH user <hidden>"),
    (("redis-cli", "HELLO", "3", "AUTH", "user", "zqm-made-up"), "HELLO 3 AUTH user <hidden>"),
    (
        ("redis-cli", "MIGRATE", "host", "port", "key", "db", "timeout", "AUTH", "zqm-made-up"),
        "MIGRATE host port key db timeout AUTH <hidden>",
    ),
    (
        ("redis-cli", "MIGRATE", "host", "port", "key", "db", "timeout", "AUTH2", "user", "zqm-x"),
        "MIGRATE host port key db timeout AUTH2 user <hidden>",
    ),
    (("valkey-cli", "--user", "user", "--pass", "zqm-made-up"), "--user user --pass <hidden>"),
    (("redis-cli", "CONFIG", "SET", "masteruser", "NAME"), "CONFIG SET masteruser NAME"),
)
# Examples the page gives with the quotes of the shown command.
QUOTED_EXAMPLES = (
    (("redis-benchmark", "-n", "10", "AUTH zqm-made-up"), "redis-benchmark -n 10 'AUTH <hidden>'"),
    (
        ("memtier_benchmark", "--command", "set __key__ __data__ EX 60"),
        "memtier_benchmark --command 'set __key__ __data__ EX 60'",
    ),
    # A command a client reads from its input is an argument of the program that writes it.
    (("echo", "AUTH password"), "echo 'AUTH password'"),
)


@pytest.mark.parametrize(("args", "words"), QUOTED_EXAMPLES)
def test_each_quoted_example_of_the_section_is_what_the_code_shows(
    repo_root: Path, args: tuple[str, ...], words: str
) -> None:
    shown = model.public_command(("pairbench", "run", "--", *args))

    assert shown == f"pairbench run -- {words}"
    assert f"`{words}" in plain(section(repo_root))


@pytest.mark.parametrize(("args", "words"), SHOWN_EXAMPLES)
def test_each_example_of_the_section_is_what_the_code_shows(
    repo_root: Path, args: tuple[str, ...], words: str
) -> None:
    shown = model.public_command(("pairbench", "run", "--", *args))

    assert shown is not None
    assert words in shown.replace("'", "")
    assert f"`{words}" in plain(section(repo_root))
