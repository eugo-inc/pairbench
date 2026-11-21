# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A shell operator inside a longer word ends no command, so a client's password stays hidden.

In an argument list a word ends a command only when the word is itself an
operator (``;``, ``&&``, ``|`` and the others a shell reads), as in
``ssh HOST tool ';' ./bench``. A word that holds an operator character among
others is one argument of the command it stands in: the query of
``mysql -e 'select 1; select 2'``, a header value ``a;q=0.9``, a label
``(x)`` or a count ``$(nproc)``. The client named before such a word keeps
its options after it, so its password option still hides its value. In a
shell text an operator in quotes, or after a backslash, is a character of
its word in the same way. The shown command and the published hashes read
every form alike: two passwords give one shown command and one hash.
Ordinary arguments that hold these characters stay shown where no client
takes a password.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model
from pairbench.model import HIDDEN
from pairbench.sides.identity import argv_sha256

# Two made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
SHOWN_LEAD = "pairbench run -- "

# Each form: its argument list with ``{s}`` for the password, and the list as shown and hashed.
HIDDEN_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a-query-holding-a-semicolon": (
        ("mysql", "-e", "select 1; select 2", "-p{s}"),
        ("mysql", "-e", "select 1; select 2", f"-p{HIDDEN}"),
    ),
    "a-header-holding-a-semicolon": (
        ("ab", "-H", "Accept: a;q=0.9", "-A", "bench:{s}", "http://localhost:8000/"),
        ("ab", "-H", "Accept: a;q=0.9", "-A", f"bench:{HIDDEN}", "http://localhost:8000/"),
    ),
    "a-count-from-a-command": (
        ("redis-benchmark", "-n", "$(nproc)", "-a", "{s}"),
        ("redis-benchmark", "-n", "$(nproc)", "-a", HIDDEN),
    ),
    "a-count-from-a-command-in-backquotes": (
        ("redis-benchmark", "-n", "`nproc`", "-a", "{s}"),
        ("redis-benchmark", "-n", "`nproc`", "-a", HIDDEN),
    ),
    "a-count-from-a-command-glued": (
        ("redis-benchmark", "-n=$(nproc)", "-a", "{s}"),
        ("redis-benchmark", "-n=$(nproc)", "-a", HIDDEN),
    ),
    "a-host-from-a-command": (
        ("redis-benchmark", "-h", "$(cat host.txt)", "-a", "{s}"),
        ("redis-benchmark", "-h", "$(cat host.txt)", "-a", HIDDEN),
    ),
    "a-label-in-brackets": (
        ("redis-benchmark", "--label", "(x)", "-a", "{s}"),
        ("redis-benchmark", "--label", "(x)", "-a", HIDDEN),
    ),
    "a-user-name-holding-an-ampersand": (
        ("redis-cli", "--user", "x&y", "-a", "{s}", "PING"),
        ("redis-cli", "--user", "x&y", "-a", HIDDEN, "PING"),
    ),
    "a-prompt-holding-a-semicolon": (
        ("sshpass", "-P", "x;y", "-p", "{s}", "ssh", "made-up-host", "true"),
        ("sshpass", "-P", "x;y", "-p", HIDDEN, "ssh", "made-up-host", "true"),
    ),
    "a-key-pattern-holding-a-bar": (
        ("memtier_benchmark", "--key-pattern", "R|R", "-a", "{s}"),
        ("memtier_benchmark", "--key-pattern", "R|R", "-a", HIDDEN),
    ),
    "a-quoted-label-in-the-remote-command": (
        ("ssh", "made-up-host", "redis-benchmark", "--label", "'x;y'", "-a", "{s}"),
        ("ssh", "made-up-host", "redis-benchmark", "--label", "'x;y'", "-a", HIDDEN),
    ),
    "a-quoted-query-in-a-shell-text": (
        ("sh", "-c", "mysql -e 'select 1; select 2' -p{s}"),
        ("sh", "-c", f"mysql -e 'select 1; select 2' -p{HIDDEN}"),
    ),
    "a-user-name-in-double-quotes-in-a-shell-text": (
        ("sh", "-c", 'redis-cli --user "x;y" -a {s} PING'),
        ("sh", "-c", f'redis-cli --user "x;y" -a {HIDDEN} PING'),
    ),
    "an-escaped-semicolon-in-a-shell-text": (
        ("sh", "-c", "redis-cli --user x\\;y -a {s} PING"),
        ("sh", "-c", f"redis-cli --user x\\;y -a {HIDDEN} PING"),
    ),
    "a-host-from-a-command-in-a-shell-text": (
        ("sh", "-c", 'redis-benchmark -h "$(cat host.txt)" -a {s}'),
        ("sh", "-c", f'redis-benchmark -h "$(cat host.txt)" -a {HIDDEN}'),
    ),
    "a-count-from-a-command-in-a-shell-text": (
        ("sh", "-c", "redis-benchmark -n $(nproc) -a {s}"),
        ("sh", "-c", f"redis-benchmark -n $(nproc) -a {HIDDEN}"),
    ),
    "a-count-in-backquotes-in-a-shell-text": (
        ("sh", "-c", "redis-benchmark -n `nproc` -a {s}"),
        ("sh", "-c", f"redis-benchmark -n `nproc` -a {HIDDEN}"),
    ),
    "a-glued-count-from-a-command-in-a-shell-text": (
        ("sh", "-c", "redis-benchmark -n=$(nproc) -a {s}"),
        ("sh", "-c", f"redis-benchmark -n=$(nproc) -a {HIDDEN}"),
    ),
    "a-quoted-label-in-brackets-in-a-shell-text": (
        ("sh", "-c", "redis-benchmark --label '(x)' -a {s}"),
        ("sh", "-c", f"redis-benchmark --label '(x)' -a {HIDDEN}"),
    ),
    # A word that is an operator alone is an argument where no shell reads the list.
    "a-delimiter-that-is-a-semicolon": (
        ("redis-cli", "-d", ";", "-a", "{s}", "PING"),
        ("redis-cli", "-d", ";", "-a", HIDDEN, "PING"),
    ),
    "a-long-delimiter-option-that-is-a-semicolon": (
        ("mysql", "--delimiter", ";", "-p{s}"),
        ("mysql", "--delimiter", ";", f"-p{HIDDEN}"),
    ),
    "a-semicolon-the-client-is-given": (
        ("redis-benchmark", "-n", "1", ";", "./bench", "-a", "{s}"),
        ("redis-benchmark", "-n", "1", ";", "./bench", "-a", HIDDEN),
    ),
    "a-user-name-that-is-a-bracket": (
        ("redis-cli", "--user", "(", "-a", "{s}"),
        ("redis-cli", "--user", "(", "-a", HIDDEN),
    ),
    "a-user-name-that-is-a-closing-bracket": (
        ("redis-cli", "--user", ")", "-a", "{s}"),
        ("redis-cli", "--user", ")", "-a", HIDDEN),
    ),
    "a-user-name-that-is-two-ampersands": (
        ("redis-cli", "--user", "&&", "-a", "{s}"),
        ("redis-cli", "--user", "&&", "-a", HIDDEN),
    ),
    "a-user-name-that-is-a-bar": (
        ("redis-cli", "--user", "|", "-a", "{s}"),
        ("redis-cli", "--user", "|", "-a", HIDDEN),
    ),
    # A name's value is read with the options of the client a later word names, past a word
    # that holds an operator character among others.
    "a-variable-before-a-label-holding-a-semicolon": (
        ("env", "MADE_UP_FLAGS=-a {s}", "LABEL=x;y", "redis-benchmark", "-n", "1"),
        ("env", f"MADE_UP_FLAGS=-a {HIDDEN}", "LABEL=x;y", "redis-benchmark", "-n", "1"),
    ),
    "a-variable-before-a-label-in-brackets": (
        ("env", "MADE_UP_FLAGS=-a {s}", "LABEL=(x)", "redis-benchmark", "-n", "1"),
        ("env", f"MADE_UP_FLAGS=-a {HIDDEN}", "LABEL=(x)", "redis-benchmark", "-n", "1"),
    ),
    "a-variable-before-a-count-substitution": (
        ("env", "MADE_UP_FLAGS=-a {s}", "N=$(nproc)", "redis-benchmark", "-n", "1"),
        ("env", f"MADE_UP_FLAGS=-a {HIDDEN}", "N=$(nproc)", "redis-benchmark", "-n", "1"),
    ),
    "a-variable-before-a-quoted-label-in-a-shell-text": (
        ("sh", "-c", "MADE_UP_FLAGS='-a {s}' LABEL='x;y' redis-benchmark -n 1"),
        ("sh", "-c", f"MADE_UP_FLAGS='-a {HIDDEN}' LABEL='x;y' redis-benchmark -n 1"),
    ),
    # A command substitution is one word of the command it stands in, and its inner text is a
    # command of its own: a client named there reads its own options.
    "a-client-inside-a-substitution": (
        ("sh", "-c", "./bench --label $(redis-cli -a {s} get k) -n 5"),
        ("sh", "-c", f"./bench --label $(redis-cli -a {HIDDEN} get k) -n 5"),
    ),
    "a-client-inside-backquotes": (
        ("sh", "-c", "./bench --label `redis-cli -a {s} get k` -n 5"),
        ("sh", "-c", f"./bench --label `redis-cli -a {HIDDEN} get k` -n 5"),
    ),
    "a-client-inside-a-substitution-in-double-quotes": (
        ("sh", "-c", './bench --label "$(redis-cli -a {s} get k)" -n 5'),
        ("sh", "-c", f'./bench --label "$(redis-cli -a {HIDDEN} get k)" -n 5'),
    ),
    "a-client-inside-a-substitution-a-name-takes": (
        ("sh", "-c", "x=$(redis-cli -a {s} get k); ./bench"),
        ("sh", "-c", f"x=$(redis-cli -a {HIDDEN} get k); ./bench"),
    ),
    "a-client-inside-a-substitution-a-key-option-takes": (
        ("sh", "-c", "./bench --key $(redis-cli -a {s} get k)"),
        ("sh", "-c", f"./bench --key {HIDDEN}"),
    ),
    "a-client-inside-a-substitution-inside-another": (
        ("sh", "-c", "./bench --label $(echo $(redis-cli -a {s} get k)) -n 5"),
        ("sh", "-c", f"./bench --label $(echo $(redis-cli -a {HIDDEN} get k)) -n 5"),
    ),
    "a-client-inside-a-process-substitution": (
        ("sh", "-c", "./bench --input <(redis-cli -a {s} get k) -n 5"),
        ("sh", "-c", f"./bench --input <(redis-cli -a {HIDDEN} get k) -n 5"),
    ),
    "a-substitution-holding-operators-before-the-password": (
        ("sh", "-c", "redis-benchmark -n $(echo 1; echo 2 | wc -l) -a {s}"),
        ("sh", "-c", f"redis-benchmark -n $(echo 1; echo 2 | wc -l) -a {HIDDEN}"),
    ),
    "an-arithmetic-count-before-the-password": (
        ("sh", "-c", "redis-benchmark -n $((2 * 3)) -a {s}"),
        ("sh", "-c", f"redis-benchmark -n $((2 * 3)) -a {HIDDEN}"),
    ),
    "a-substitution-that-is-not-closed": (
        ("sh", "-c", "redis-benchmark -n $(nproc -a {s}"),
        ("sh", "-c", f"redis-benchmark -n $(nproc -a {HIDDEN}"),
    ),
    # A text that holds the characters that stand for substitutions while a text is read.
    "a-text-holding-private-use-characters": (
        ("sh", "-c", "redis-cli -n $(nproc) \ue000\ue001 -a {s} \uf8ff"),
        ("sh", "-c", f"redis-cli -n $(nproc) \ue000\ue001 -a {HIDDEN} \uf8ff"),
    ),
    # A hidden value that ends in an operator character leaves the client's options on.
    "a-password-ending-in-a-semicolon-before-another": (
        ("ab", "-A", "bench:made-up;", "-P", "proxy:{s}", "http://localhost:8000/"),
        ("ab", "-A", f"bench:{HIDDEN}", "-P", f"proxy:{HIDDEN}", "http://localhost:8000/"),
    ),
    "a-password-ending-in-a-semicolon-before-another-in-a-shell-text": (
        ("sh", "-c", "redis-cli -a 'made-up;' --pass {s}"),
        ("sh", "-c", f"redis-cli -a {HIDDEN} --pass {HIDDEN}"),
    ),
}


def typed(words: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in words]


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_an_operator_inside_a_word_keeps_the_client_and_hides_its_password(name: str) -> None:
    words, hidden = HIDDEN_FORMS[name]
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(hidden)
        )
        assert model.hashed_argv(argv) == list(hidden)


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_two_passwords_after_an_operator_inside_a_word_give_one_hash(name: str) -> None:
    words, _hidden = HIDDEN_FORMS[name]
    one, two = (typed(words, password) for password in PASSWORDS)

    assert argv_sha256(one) == argv_sha256(two)


# A side that runs a client before the shared workload, with such a word before it: the
# side's command, the workload with ``{s}`` for the password, and the workload as hashed.
HANDED_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "a-host-from-a-command-before-the-parameters": (
        ("sh", "-c", 'redis-benchmark -h "$(cat host.txt)" "$@"', "_"),
        ("-a", "{s}", "-n", "1000"),
        ("-a", HIDDEN, "-n", "1000"),
    ),
    "a-count-from-a-command-before-the-parameters": (
        ("sh", "-c", 'redis-benchmark -n $(nproc) "$@"', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "a-query-before-the-parameters": (
        ("sh", "-c", 'mysql -e "select 1; select 2" "$@"', "_"),
        ("-p{s}",),
        (f"-p{HIDDEN}",),
    ),
    "a-label-in-brackets-before-the-parameters": (
        ("sh", "-c", "redis-benchmark --label '(x)' \"$@\"", "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "a-substitution-holding-operators-before-the-parameters": (
        ("sh", "-c", 'redis-benchmark -n $(echo 1; echo 2 | wc -l) "$@"', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "the-parameters-handed-to-a-client-inside-a-substitution": (
        ("sh", "-c", './bench --label $(redis-cli "$@" get k)', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "a-label-before-the-workload": (
        ("redis-benchmark", "--label", "x|y"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "a-query-before-the-workload": (
        ("mysql", "-e", "select 1; select 2"),
        ("-p{s}",),
        (f"-p{HIDDEN}",),
    ),
}


def handed_config(name: str, password: str) -> dict[str, object]:
    head, workload, _hidden = HANDED_FORMS[name]
    return {
        "sides": {"a": {"cmd": [*head, model.WORKLOAD_PLACEHOLDER]}},
        "workload": {"argv": typed(workload, password)},
    }


@pytest.mark.parametrize("name", sorted(HANDED_FORMS))
def test_a_client_before_such_a_word_hides_the_password_of_the_shared_workload(
    name: str,
) -> None:
    head, workload, hidden = HANDED_FORMS[name]
    for password in PASSWORDS:
        config = handed_config(name, password)

        assert model.hashed_argv([*head, *typed(workload, password)]) == [*head, *hidden]
        assert model.config_inputs(config)["workload"]["argv"] == list(hidden)
        assert model.public_command(
            ("pairbench", "run", "--", *typed(workload, password)), config=config
        ) == (SHOWN_LEAD + shlex.join(hidden))
    first, second = (handed_config(name, password) for password in PASSWORDS)
    assert model.config_sha256(first) == model.config_sha256(second)


def test_a_quoted_operator_in_a_command_written_as_one_text_ends_no_command() -> None:
    # The words of the text are split as a shell splits them, so the ``;`` that reaches the
    # walk was in quotes, and the client's password option after it still hides its value.
    for password in PASSWORDS:
        assert model.public_words(f"redis-cli --user 'x;y' -a {password} PING") == (
            f"redis-cli --user x;y -a {HIDDEN} PING"
        )
        assert model.public_words(f"redis-cli -d ';' -a {password} PING") == (
            f"redis-cli -d ; -a {HIDDEN} PING"
        )


# Ordinary arguments that hold an operator character, with ``{v}`` for a value that no
# client's password option takes: each is shown as typed, and two values give two hashes.
KEPT_FORMS: dict[str, tuple[str, ...]] = {
    "a-label-holding-a-semicolon": ("./bench", "--label", "x;y", "-a", "{v}"),
    "a-label-in-brackets": ("./bench", "--label", "(x)", "-p", "{v}"),
    "an-expression": ("./bench", "--expr", "(a|b)", "-n", "{v}"),
    "a-port-after-a-query": ("mysql", "-e", "select 1; select 2", "-P", "{v}"),
    "an-operator-word-in-the-remote-command": (
        "ssh",
        "made-up-host",
        "redis-benchmark",
        "-n",
        "1",
        ";",
        "./bench",
        "-a",
        "{v}",
    ),
    "an-operator-in-a-shell-text": ("sh", "-c", "redis-benchmark -n 1 ; ./bench -a {v}"),
    "a-glued-operator-in-a-shell-text": ("sh", "-c", "redis-benchmark -n 1;./bench -a {v}"),
    "a-subshell-before-an-operator": ("sh", "-c", "(redis-benchmark -n 1) && ./bench -a {v}"),
    "a-count-from-a-command-in-a-shell-text": ("sh", "-c", "./bench -n $(nproc) -a {v}"),
    "a-quoted-label-in-a-shell-text": ("sh", "-c", "./bench --label 'x;y' -a {v}"),
    "a-variable-before-an-operator-in-a-shell-text": (
        "sh",
        "-c",
        "MADE_UP_FLAGS='-a {v}' && redis-benchmark -n 1",
    ),
    "a-substitution-of-a-client-as-a-label": (
        "sh",
        "-c",
        "./bench --label $(redis-cli get k) -a {v}",
    ),
    "a-substitution-of-a-client-a-name-takes": ("sh", "-c", "x=$(redis-cli get k) ./bench -a {v}"),
    "backquotes-of-a-client-as-a-label": ("sh", "-c", "./bench -k `redis-cli get k` -a {v}"),
    "an-operator-word-in-a-command-watch-runs": (
        "watch",
        "redis-cli",
        "-d",
        ";",
        "./bench",
        "-a",
        "{v}",
    ),
}
VALUES = ("5", "7")


@pytest.mark.parametrize("name", sorted(KEPT_FORMS))
def test_an_ordinary_argument_holding_an_operator_stays_shown(name: str) -> None:
    hashes = set()
    for value in VALUES:
        argv = [word.replace("{v}", value) for word in KEPT_FORMS[name]]

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(argv)
        )
        assert model.hashed_argv(argv) == argv
        hashes.add(argv_sha256(argv))
    assert len(hashes) == len(VALUES)


def test_a_password_ending_in_an_operator_a_shell_reads_ends_the_client_command() -> None:
    # The remote shell of ``ssh`` reads the semicolon after the password as an operator, so
    # the command after it is no command of the client and its value stays shown.
    hashes = set()
    for value in VALUES:
        argv = ["ssh", "made-up-host", "redis-cli", "-a", "made-up;", "./bench", "-a", value]
        hidden = ["ssh", "made-up-host", "redis-cli", "-a", f"{HIDDEN};", "./bench", "-a", value]

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(hidden)
        )
        assert model.hashed_argv(argv) == hidden
        hashes.add(argv_sha256(argv))
    assert len(hashes) == len(VALUES)


def test_a_client_inside_a_substitution_of_a_command_written_as_one_text_hides_its_password() -> (
    None
):
    # A command written as one text, as hyperfine gives its commands, reads a substitution in
    # it as one word and its inner text as a command of its own.
    for password in PASSWORDS:
        assert model.public_words(f"./bench --label $(redis-cli -a {password} get k) -n 5") == (
            f"./bench --label $(redis-cli -a {HIDDEN} get k) -n 5"
        )
        assert model.public_words(f"redis-benchmark -n $(echo 1; echo 2) -a {password}") == (
            f"redis-benchmark -n $(echo 1; echo 2) -a {HIDDEN}"
        )
    assert model.public_words("./bench --label $(redis-cli get k) -a 5") == (
        "./bench --label $(redis-cli get k) -a 5"
    )


# Substitutions inside substitutions are read this deep; a deeper inner text is hidden whole.
SUBSTITUTION_DEPTH = 8


def test_a_substitution_deeper_than_the_bound_is_hidden_whole() -> None:
    inner = "redis-cli -a made-up get k"
    text = (
        "./bench --label "
        + "$(echo " * SUBSTITUTION_DEPTH
        + f"$({inner})"
        + ")" * (SUBSTITUTION_DEPTH)
    )
    shown = (
        "./bench --label "
        + "$(echo " * SUBSTITUTION_DEPTH
        + f"$({HIDDEN})"
        + ")" * (SUBSTITUTION_DEPTH)
    )

    assert model.hashed_argv(["sh", "-c", text]) == ["sh", "-c", shown]
    assert model.public_command(("pairbench", "run", "--", "sh", "-c", text)) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", shown])
    )


def test_a_substitution_a_key_option_takes_is_hidden_and_the_words_after_it_shown() -> None:
    # The substitution is the key's value, so it is hidden whole; no client is named in the
    # command it stands in, so the ``-a`` after it is an ordinary option.
    for value in VALUES:
        argv = ["sh", "-c", f"./bench --key $(redis-cli get k) -a {value}"]
        shown = ["sh", "-c", f"./bench --key {HIDDEN} -a {value}"]

        assert model.hashed_argv(argv) == shown
        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(shown)
        )


# Forms the security policy lists as known limits, as it writes them and as typed: the
# password of each shows, in the shown command and in the hash.
LIMIT_FORMS = (
    (
        "**A program or an option that a command substitution gives.**",
        "`sh -c '$(which redis-cli) -a password'`",
    ),
    (
        "**A program or an option that a command substitution gives.**",
        "`sh -c 'redis-cli $(echo -a) password'`",
    ),
    (
        "**A program or an option that a command substitution gives.**",
        "`sh -c 'redis-cli CONFIG SET $(echo requirepass) password'`",
    ),
    (
        "**A `case` pattern in a command substitution.**",
        "`sh -c 'redis-benchmark -n $(case x in x) echo 1;; esac) -a password'`",
    ),
)


@pytest.mark.parametrize(("title", "words"), LIMIT_FORMS)
def test_the_security_policy_lists_a_substitution_form_that_shows_its_password(
    repo_root: Path, title: str, words: str
) -> None:
    text = " ".join((repo_root / "SECURITY.md").read_text(encoding="utf-8").split())
    section = text.split("## Known limits of the shown command", 1)[1].split(" ## ", 1)[0]
    typed = shlex.split(words.strip("`").replace("password", PASSWORDS[0]))

    assert title in section
    assert words in section
    assert model.public_command(("pairbench", "run", "--", *typed)) == (
        SHOWN_LEAD + shlex.join(typed)
    )
    assert model.hashed_argv(typed) == typed
