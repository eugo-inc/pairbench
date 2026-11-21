# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A client's password is hidden wherever the client is named in a command text.

The text of an option of ``TEXT_OPTIONS`` (``gcloud ... --command``, ``env -S``,
``env --split-string``, the ``-c`` and ``--command`` of ``su``, ``runuser``,
``flock``, ``script`` and ``fish``) is read the same way whether it follows the option as
the next word or is glued to it (``--command=TEXT``, ``-STEXT``), so the first
word of a glued text names a client as the first word of a spaced one does,
and the client's password option hides its value. This holds for the text as
an argument, as a word quoted whole in a shell text, with the quote after the
option, and in the remote command of ``ssh``. The shown command and the
published hashes read it alike: two passwords give one shown command and one
hash, and two programs give two.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model
from pairbench.model import HIDDEN
from pairbench.sides.identity import argv_sha256

# Two made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
PROGRAMS = ("old", "new")

# Each client: its text with ``{s}`` for the password, and the text as shown and hashed.
CLIENT_TEXTS: dict[str, tuple[str, str]] = {
    "mysql": ("mysql -p{s} -e made-up-query", f"mysql -p{HIDDEN} -e made-up-query"),
    "mysqlslap": ("mysqlslap -p{s} -c 4", f"mysqlslap -p{HIDDEN} -c 4"),
    "redis-cli": ("redis-cli -a {s} PING", f"redis-cli -a {HIDDEN} PING"),
    "redis-benchmark": ("redis-benchmark -a {s} -n 1000", f"redis-benchmark -a {HIDDEN} -n 1000"),
    "memtier_benchmark": (
        "memtier_benchmark -a {s} -n 1000",
        f"memtier_benchmark -a {HIDDEN} -n 1000",
    ),
    "valkey-cli": ("valkey-cli -a {s} PING", f"valkey-cli -a {HIDDEN} PING"),
    "sshpass": (
        "sshpass -p {s} ssh made-up-host true",
        f"sshpass -p {HIDDEN} ssh made-up-host true",
    ),
    "ab": (
        "ab -A bench:{s} http://localhost:8000/",
        f"ab -A bench:{HIDDEN} http://localhost:8000/",
    ),
}

# The words before the option, for each program of ``TEXT_OPTIONS``.
HEADS: dict[str, str] = {
    "gcloud": "gcloud compute ssh made-up-vm",
    "env": "env",
    "hyperfine": "hyperfine",
    "su": "su bench",
    "runuser": "runuser -l bench",
    "flock": "flock made-up.lock",
    "script": "script -q",
    "fish": "fish",
}
# What stands before a glued text, for each option of ``TEXT_OPTIONS``.
JOINTS: dict[str, str] = {
    "--command": "--command=",
    "-S": "-S",
    "--split-string": "--split-string=",
    "-c": "-c",
    "-s": "-s",
    "--setup": "--setup=",
    "-p": "-p",
    "--prepare": "--prepare=",
    "-C": "-C",
    "--conclude": "--conclude=",
    "--cleanup": "--cleanup=",
    "--reference": "--reference=",
}

# Each placement of the text: the argument list, with ``{head}`` the words before the option,
# ``{option}`` the option and what follows it (a blank, or what glues the text to it),
# ``{text}`` the text and ``{p}`` the program that tells two commands apart.
PLACEMENTS: dict[str, tuple[str, ...]] = {
    "argument": ("{head}", "{option}{text}", "./bench-{p}"),
    "quoted-whole": ("sh", "-c", "{head} '{option}{text}' && ./bench-{p}"),
    "quote-after-option": ("sh", "-c", "{head} {option}'{text}' && ./bench-{p}"),
    "ssh-remote": ("ssh", "made-up-host", "{head} {option}'{text}' && ./bench-{p}"),
}


def placed(placement: str, head: str, option: str, text: str, program: str) -> list[str]:
    """Return the argument list of one placement with its parts put in."""
    out: list[str] = []
    for word in PLACEMENTS[placement]:
        if word == "{head}":
            out.extend(head.split())
            continue
        filled = word.replace("{head}", head).replace("{option}", option)
        out.append(filled.replace("{text}", text).replace("{p}", program))
    return out


def spaced(placement: str, option: str) -> str:
    """Return how the option stands before its text written apart from it in a text."""
    return f"{option} " if placement != "argument" else ""


def glued_argv(
    placement: str, program_name: str, option: str, client: str, password: str, program: str
) -> list[str]:
    text = CLIENT_TEXTS[client][0].replace("{s}", password)
    return placed(placement, HEADS[program_name], JOINTS[option], text, program)


def spaced_argv(
    placement: str, program_name: str, option: str, client: str, password: str, program: str
) -> list[str]:
    text = CLIENT_TEXTS[client][0].replace("{s}", password)
    if placement == "argument":
        argv = placed(placement, HEADS[program_name], "", text, program)
        at = len(HEADS[program_name].split())
        return [*argv[:at], option, *argv[at:]]
    return placed(placement, HEADS[program_name], spaced(placement, option), text, program)


def expected(placement: str, program_name: str, joint: str, client: str) -> list[str]:
    """Return the argument list as hashed and as the shown command splits back into."""
    return placed(placement, HEADS[program_name], joint, CLIENT_TEXTS[client][1], PROGRAMS[0])


OPTIONS = [
    (program_name, option)
    for program_name, options in sorted(model.TEXT_OPTIONS.items())
    for option in options
]


def test_every_option_of_text_options_has_a_row() -> None:
    assert sorted(HEADS) == sorted(model.TEXT_OPTIONS)
    assert sorted(JOINTS) == sorted({option for _program, option in OPTIONS})


@pytest.mark.parametrize("placement", sorted(PLACEMENTS))
@pytest.mark.parametrize("client", sorted(CLIENT_TEXTS))
@pytest.mark.parametrize(("program_name", "option"), OPTIONS)
def test_a_client_first_in_a_glued_text_hides_its_password(
    program_name: str, option: str, client: str, placement: str
) -> None:
    hashed = expected(placement, program_name, JOINTS[option], client)
    for password in PASSWORDS:
        argv = glued_argv(placement, program_name, option, client, password, PROGRAMS[0])
        shown = model.public_command(argv)

        assert shown == shlex.join(hashed)
        assert shlex.split(shown) == hashed
        assert model.hashed_argv(argv) == hashed
        for at in range(len(password) - 5):
            assert password[at : at + 6] not in shown


@pytest.mark.parametrize("placement", sorted(PLACEMENTS))
@pytest.mark.parametrize("client", sorted(CLIENT_TEXTS))
@pytest.mark.parametrize(("program_name", "option"), OPTIONS)
def test_a_glued_text_reads_as_the_same_text_written_apart(
    program_name: str, option: str, client: str, placement: str
) -> None:
    if placement == "argument":
        hashed = expected(placement, program_name, "", client)
        at = len(HEADS[program_name].split())
        hashed = [*hashed[:at], option, *hashed[at:]]
    else:
        hashed = expected(placement, program_name, spaced(placement, option), client)
    argv = spaced_argv(placement, program_name, option, client, PASSWORDS[0], PROGRAMS[0])

    assert model.public_command(argv) == shlex.join(hashed)
    assert model.hashed_argv(argv) == hashed


@pytest.mark.parametrize("placement", sorted(PLACEMENTS))
@pytest.mark.parametrize("client", sorted(CLIENT_TEXTS))
@pytest.mark.parametrize(("program_name", "option"), OPTIONS)
def test_two_passwords_in_a_glued_text_give_one_hash_and_two_programs_two(
    program_name: str, option: str, client: str, placement: str
) -> None:
    one, two = (
        glued_argv(placement, program_name, option, client, password, PROGRAMS[0])
        for password in PASSWORDS
    )
    other = glued_argv(placement, program_name, option, client, PASSWORDS[0], PROGRAMS[1])

    assert argv_sha256(one) == argv_sha256(two)
    assert model.public_command(one) == model.public_command(two)
    assert argv_sha256(one) != argv_sha256(other)
    assert model.public_command(one) != model.public_command(other)


# Rows written out whole, one per option and placement.
WRITTEN: dict[str, tuple[tuple[str, ...], str]] = {
    "gcloud-command-argument": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command=mysql -pkiwi7mango", "./bench-old"),
        "gcloud compute ssh made-up-vm '--command=mysql -p<hidden>' ./bench-old",
    ),
    "env-S-argument-then-words": (
        ("env", "-Sredis-cli", "-a", "kiwi7mango", "PING"),
        "env -Sredis-cli -a '<hidden>' PING",
    ),
    "env-split-string-quoted-whole": (
        ("sh", "-c", "env '--split-string=redis-benchmark -a kiwi7mango' && ./bench-old"),
        "sh -c 'env '\"'\"'--split-string=redis-benchmark -a <hidden>'\"'\"' && ./bench-old'",
    ),
    "env-S-escaped-blanks": (
        ("sh", "-c", "env -Sredis-cli\\ -a\\ kiwi7mango && ./bench-old"),
        "sh -c 'env -S'\"'\"'redis-cli -a <hidden>'\"'\"' && ./bench-old'",
    ),
    "env-S-after-unset": (
        ("env", "-uMADE_UP", "-Ssshpass -p kiwi7mango ssh made-up-host", "./bench-old"),
        "env -uMADE_UP '-Ssshpass -p <hidden> ssh made-up-host' ./bench-old",
    ),
    "gcloud-command-double-quotes-in-ssh": (
        ("ssh", "made-up-host", 'gcloud compute ssh vm --command="valkey-cli -a kiwi7mango"'),
        "ssh made-up-host 'gcloud compute ssh vm --command=\"valkey-cli -a <hidden>\"'",
    ),
}


@pytest.mark.parametrize("name", sorted(WRITTEN))
def test_a_glued_text_written_out_is_shown_with_its_password_hidden(name: str) -> None:
    form, shown = WRITTEN[name]
    for password in PASSWORDS:
        argv = [word.replace(PASSWORDS[0], password) for word in form]
        assert model.public_command(argv) == shown
        assert password not in "".join(model.hashed_argv(argv))


# A side whose shell text hands the workload on: the words before ``{workload}``, the
# workload (``{s}`` the password), and, with the first password, the side's whole command as
# hashed and the workload as the shown command gives it after ``--``.
Parameters = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str]
# Shell texts that run a shell text of their own and hand it their parameters.
NESTED = 'sh -c \'redis-cli "$@"\' _ "$@"'
NESTED_AFTER_ENV = 'env MADE_UP=1 bash -ec \'exec redis-cli "${@}"\' _ "$@"'
# The same written in double quotes, where the shell that runs the outer text takes away the
# backslash before each ``$`` and ``"``, so the inner text it runs is ``redis-cli "$@"``.
NESTED_DOUBLE = 'sh -c "redis-cli \\"\\$@\\"" _ "$@"'
NESTED_DOUBLE_BARE = 'sh -c "redis-cli \\$@" _ "$@"'
NESTED_DOUBLE_NUMBERED = 'sh -c "redis-cli -a \\"\\$1\\" PING" _ "$@"'
# The inner text it runs is ``redis-cli -a \$1; ./bench "$1"``: its ``\$1`` is text.
NESTED_DOUBLE_KEPT = 'sh -c "redis-cli -a \\\\\\$1; ./bench \\"\\$1\\"" _ "$@"'
# A backslash and a line break in double quotes are taken away together: the inner text is
# ``redis-cli "$@"`` whether the break falls between two words or inside the client's name.
NESTED_DOUBLE_CONTINUED = 'sh -c "redis-cli \\\n\\"\\$@\\"" _ "$@"'
NESTED_DOUBLE_JOINED = 'sh -c "redis-\\\ncli \\"\\$@\\"" _ "$@"'

SHELL_PARAMETERS: dict[str, Parameters] = {
    "at-quoted": (
        ("sh", "-c", 'redis-benchmark "$@"', "_"),
        ("-a", "{s}", "-n", "1000"),
        ("sh", "-c", 'redis-benchmark "$@"', "_", "-a", HIDDEN, "-n", "1000"),
        "-a '<hidden>' -n 1000",
    ),
    "at-bare": (
        ("sh", "-c", "redis-benchmark $@", "_"),
        ("-a", "{s}", "-n", "1000"),
        ("sh", "-c", "redis-benchmark $@", "_", "-a", HIDDEN, "-n", "1000"),
        "-a '<hidden>' -n 1000",
    ),
    "star": (
        ("sh", "-c", 'valkey-cli "$*"', "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", 'valkey-cli "$*"', "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "braced-at": (
        ("bash", "-c", 'redis-cli "${@}"', "made-up-name"),
        ("-a", "{s}", "PING"),
        ("bash", "-c", 'redis-cli "${@}"', "made-up-name", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "numbered": (
        ("sh", "-c", 'sshpass -p "$1" ssh made-up-host "$2"', "_"),
        ("{s}", "true"),
        ("sh", "-c", 'sshpass -p <hidden> ssh made-up-host "$2"', "_", HIDDEN, "true"),
        "'<hidden>' true",
    ),
    "numbered-glued": (
        ("sh", "-c", 'mysql -p"$1" -e "$2"', "_"),
        ("{s}", "made-up-query"),
        ("sh", "-c", 'mysql -p<hidden> -e "$2"', "_", HIDDEN, "made-up-query"),
        "'<hidden>' made-up-query",
    ),
    "after-an-operator": (
        ("sh", "-c", 'cd made-up-folder && memtier_benchmark "$@"', "_"),
        ("-a", "{s}", "-n", "1000"),
        (
            "sh",
            "-c",
            'cd made-up-folder && memtier_benchmark "$@"',
            "_",
            "-a",
            HIDDEN,
            "-n",
            "1000",
        ),
        "-a '<hidden>' -n 1000",
    ),
    "env-and-option-group": (
        ("env", "MADE_UP=1", "sh", "-ec", 'exec ab "$@"', "runner"),
        ("-A", "bench:{s}", "http://localhost:8000/"),
        (
            "env",
            "MADE_UP=1",
            "sh",
            "-ec",
            'exec ab "$@"',
            "runner",
            "-A",
            f"bench:{HIDDEN}",
            "http://localhost:8000/",
        ),
        "-A 'bench:<hidden>' http://localhost:8000/",
    ),
    "options-ended": (
        ("bash", "-c", "--", 'mysqlslap "$@"', "_"),
        ("-p{s}", "-c", "4"),
        ("bash", "-c", "--", 'mysqlslap "$@"', "_", f"-p{HIDDEN}", "-c", "4"),
        "'-p<hidden>' -c 4",
    ),
    "a-shell-text-run-by-the-text": (
        ("sh", "-c", NESTED, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-shell-text-run-after-env": (
        ("sh", "-c", NESTED_AFTER_ENV, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED_AFTER_ENV, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-shell-text-in-double-quotes-run-by-the-text": (
        ("sh", "-c", NESTED_DOUBLE, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED_DOUBLE, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-line-continuation-in-double-quotes-run-by-the-text": (
        ("sh", "-c", NESTED_DOUBLE_CONTINUED, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED_DOUBLE_CONTINUED, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-client-name-joined-by-a-line-continuation-run-by-the-text": (
        ("sh", "-c", NESTED_DOUBLE_JOINED, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED_DOUBLE_JOINED, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-bare-parameter-in-double-quotes-run-by-the-text": (
        ("sh", "-c", NESTED_DOUBLE_BARE, "_"),
        ("-a", "{s}", "PING"),
        ("sh", "-c", NESTED_DOUBLE_BARE, "_", "-a", HIDDEN, "PING"),
        "-a '<hidden>' PING",
    ),
    "a-numbered-parameter-in-double-quotes-run-by-the-text": (
        ("sh", "-c", NESTED_DOUBLE_NUMBERED, "_"),
        ("{s}",),
        ("sh", "-c", "sh -c 'redis-cli -a <hidden> PING' _ \"$@\"", "_", HIDDEN),
        "'<hidden>'",
    ),
    # A parameter the text uses twice is read once for each program that takes it, and once
    # for each way the same program takes it: a command that shows it first leaves it hidden.
    "used-first-by-a-program-with-no-password": (
        ("sh", "-c", 'echo "$1"; redis-cli "$1" PING', "_"),
        ("-a{s}",),
        ("sh", "-c", 'echo "$1"; redis-cli "$1" PING', "_", f"-a{HIDDEN}"),
        "'-a<hidden>'",
    ),
    "used-first-after-the-client-command": (
        ("sh", "-c", 'redis-cli PING "$1"; redis-cli "$1"', "_"),
        ("AUTH {s}",),
        ("sh", "-c", 'redis-cli PING "$1"; redis-cli "$1"', "_", f"AUTH {HIDDEN}"),
        "'AUTH <hidden>'",
    ),
}


def parameters_config(name: str, password: str) -> dict[str, object]:
    head, workload, _hashed, _shown = SHELL_PARAMETERS[name]
    return {
        "sides": {"a": {"cmd": [*head, model.WORKLOAD_PLACEHOLDER]}},
        "workload": {"argv": [word.replace("{s}", password) for word in workload]},
    }


@pytest.mark.parametrize("name", sorted(SHELL_PARAMETERS))
def test_a_parameter_a_side_shell_text_hands_to_a_client_is_hidden(name: str) -> None:
    head, workload, hashed, shown = SHELL_PARAMETERS[name]
    for password in PASSWORDS:
        typed = [word.replace("{s}", password) for word in workload]
        config = parameters_config(name, password)

        assert model.hashed_argv([*head, *typed]) == list(hashed)
        assert model.config_inputs(config)["workload"]["argv"] == list(hashed[len(head) :])
        assert model.public_command(("pairbench", "run", "--", *typed), config=config) == (
            f"pairbench run -- {shown}"
        )


@pytest.mark.parametrize("name", sorted(SHELL_PARAMETERS))
def test_two_passwords_a_side_shell_text_hands_on_give_one_hash(name: str) -> None:
    head, workload, _hashed, _shown = SHELL_PARAMETERS[name]
    one, two = ([*head, *(w.replace("{s}", p) for w in workload)] for p in PASSWORDS)

    assert argv_sha256(one) == argv_sha256(two)
    first, second = (parameters_config(name, password) for password in PASSWORDS)
    assert model.config_sha256(first) == model.config_sha256(second)


def test_a_program_a_shell_text_runs_from_its_parameters_tells_two_sides_apart() -> None:
    # The text runs its parameters as the command: the client named first among them hides
    # its password, and the program word stays, so two programs are two sides.
    head = ["sh", "-c", '"$@"', "_"]
    one, two, other = (
        [*head, program, "-a", password, "-n", "1000"]
        for program, password in (
            ("redis-benchmark", PASSWORDS[0]),
            ("redis-benchmark", PASSWORDS[1]),
            ("./build-new/redis-benchmark", PASSWORDS[0]),
        )
    )

    assert model.hashed_argv(one) == [*head, "redis-benchmark", "-a", HIDDEN, "-n", "1000"]
    assert argv_sha256(one) == argv_sha256(two)
    assert argv_sha256(one) != argv_sha256(other)


def test_a_parameter_the_shell_text_does_not_hand_to_a_client_is_kept() -> None:
    # ``tool`` takes no password option, a word the text never uses is no parameter of it, and
    # a parameter in single quotes or after a backslash is text the shell does not expand: the
    # ``$1`` after ``-a`` is hidden as text, and the parameter goes to ``./bench`` alone. In
    # double quotes the outer shell turns ``\\\$1`` into the ``\$1`` the inner text keeps.
    for argv, kept in (
        (["sh", "-c", 'tool "$@"', "_", "-a", "made-up-value"], 2),
        (["sh", "-c", 'redis-benchmark "$1"', "_", "-n", "-a", "made-up-value"], 2),
        (["sh", "-c", "redis-cli -a '$1'; ./bench \"$1\"", "_", "made-up-value"], 3),
        (["sh", "-c", 'redis-cli -a \\$1; ./bench "$1"', "_", "made-up-value"], 3),
        (["sh", "-c", NESTED_DOUBLE_KEPT, "_", "made-up-value"], 3),
    ):
        assert model.hashed_argv(argv)[kept:] == argv[kept:]
        assert model.public_command(("pairbench", "run", "--", *argv)).endswith(
            " " + shlex.join(argv[kept:])
        )


# What an image side that runs the shared workload behind its image's own entrypoint records in
# its identity: the image's entrypoint (``None`` for an identity that records none) and the first
# word of the image's command (``None`` for none).
IMAGE_IDENTITY = {
    "image_id": "sha256:" + "0123456789abcdef" * 4,
    "digests": (),
    "platform": "linux/amd64",
}
# Each image: what it records, the workload with ``{s}`` for the password, and the workload as
# shown after ``pairbench run --``.
IMAGE_HEADS: dict[str, tuple[list[str] | None, str | None, tuple[str, ...], str]] = {
    "client-entrypoint": (
        ["memtier_benchmark"],
        None,
        ("-s", "made-up-host", "-a", "{s}", "-n", "1000"),
        "-s made-up-host -a '<hidden>' -n 1000",
    ),
    "client-entrypoint-by-path": (
        ["/usr/local/bin/redis-benchmark"],
        None,
        ("-a", "{s}", "-n", "1000"),
        "-a '<hidden>' -n 1000",
    ),
    "shell-text-entrypoint": (
        ["sh", "-c", 'redis-benchmark "$@"', "_"],
        None,
        ("-a", "{s}", "-n", "1000"),
        "-a '<hidden>' -n 1000",
    ),
    "wrapper-script-then-command": (
        ["docker-entrypoint.sh"],
        "memtier_benchmark",
        ("-s", "made-up-host", "-a", "{s}", "-n", "1000"),
        "-s made-up-host -a '<hidden>' -n 1000",
    ),
    "no-entrypoint-client-first": (
        [],
        "sh",
        ("memtier_benchmark", "-a", "{s}", "-n", "1000"),
        "memtier_benchmark -a '<hidden>' -n 1000",
    ),
}
# Each image whose recorded program is given no password: the workload is shown as typed, and two
# values are two hashes.
IMAGE_KEPT: dict[str, tuple[list[str] | None, str | None, tuple[str, ...]]] = {
    # An image with no entrypoint runs the workload's first word, which is no client.
    "no-entrypoint": ([], "memtier_benchmark", ("-a", "{s}", "-n", "1000")),
    # A wrapper script handed a workload that starts with a program runs that program.
    "wrapper-script-then-program": (
        ["docker-entrypoint.sh"],
        "memtier_benchmark",
        ("./bench", "-a", "{s}"),
    ),
    # An entrypoint that is a client is the program; the image's command is not read, and
    # ``-a`` is no password option of ``mysql``.
    "client-entrypoint-command-not-read": (["mysql"], "redis-cli", ("-a", "{s}", "-e", "query")),
    "entrypoint-no-client": (["./bench"], "./other", ("-a", "{s}")),
    # A side that records nothing, as one with its own entrypoint or arguments.
    "nothing-recorded": (None, None, ("-a", "{s}")),
}


def image_side(entrypoint: list[str] | None, program: str | None) -> model.Side:
    identity: dict[str, object] = dict(IMAGE_IDENTITY)
    if entrypoint is not None:
        identity[model.IMAGE_ENTRYPOINT_KEY] = entrypoint
    if program is not None:
        identity[model.IMAGE_COMMAND_PROGRAM_KEY] = program
    side = model.Side.image("a", "registry.example/tool:1")
    return model.Side(
        name=side.name, kind=side.kind, spec=side.spec, identity=identity, fingerprint="0" * 64
    )


def image_config(workload: tuple[str, ...], password: str) -> dict[str, object]:
    return {
        "sides": {"a": {"image": "registry.example/tool:1"}},
        "workload": {"argv": [word.replace("{s}", password) for word in workload]},
    }


@pytest.mark.parametrize("name", sorted(IMAGE_HEADS))
def test_a_client_an_image_runs_before_the_workload_hides_its_password(name: str) -> None:
    entrypoint, program, workload, shown = IMAGE_HEADS[name]
    side = image_side(entrypoint, program)
    hashed = [HIDDEN if word == "{s}" else word for word in workload]
    for password in PASSWORDS:
        config = image_config(workload, password)
        typed = config["workload"]["argv"]  # type: ignore[index]

        assert model.public_command(("pairbench", "run", "--", *typed), sides=[side]) == (
            f"pairbench run -- {shown}"
        )
        assert model.config_inputs(config, [side])["workload"]["argv"] == hashed
    first, second = (model.config_sha256(image_config(workload, p), [side]) for p in PASSWORDS)
    assert first == second


@pytest.mark.parametrize("name", sorted(IMAGE_KEPT))
def test_a_workload_an_image_gives_no_client_keeps_its_words(name: str) -> None:
    entrypoint, program, workload = IMAGE_KEPT[name]
    side = image_side(entrypoint, program)
    for password in PASSWORDS:
        config = image_config(workload, password)
        typed = config["workload"]["argv"]  # type: ignore[index]

        assert model.public_command(("pairbench", "run", "--", *typed), sides=[side]) == (
            f"pairbench run -- {shlex.join(typed)}"  # type: ignore[arg-type]
        )
        assert model.config_inputs(config, [side])["workload"]["argv"] == typed
    first, second = (model.config_sha256(image_config(workload, p), [side]) for p in PASSWORDS)
    assert first != second


def test_what_an_image_runs_before_the_workload_leaves_the_fingerprint_alone() -> None:
    launch = model.LaunchSettings().to_json()
    recorded = {
        **IMAGE_IDENTITY,
        model.IMAGE_ENTRYPOINT_KEY: ["docker-entrypoint.sh"],
        model.IMAGE_COMMAND_PROGRAM_KEY: "memtier_benchmark",
    }

    assert model.fingerprint_of(recorded, launch) == model.fingerprint_of(IMAGE_IDENTITY, launch)
    assert model.fingerprint_inputs(recorded, launch) == model.fingerprint_inputs(
        IMAGE_IDENTITY, launch
    )
