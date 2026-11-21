# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A runner's command text is read as the runner runs it: in a shell, or as words with none.

``tmux`` runs a command given to ``new``, ``new-window``, ``split-window``,
``respawn-window``, ``respawn-pane`` and their short names as one argument
in a shell, blanks or none, and a
command given as several arguments with no shell, each word one argument.
``watch -c`` is ``watch``'s colour option, so the word after it is
``watch``'s command, read as a shell text. Only a whole word of the
command turns ``hyperfine``'s shell off (``-N``, ``--shell=none``,
``-S none``): the same letters inside one of its commands, as the ``-N`` of
``ssh -N``, belong to that command. The text of ``-c`` or ``--command`` of
``su``, ``runuser``, ``flock``, ``script`` and ``fish``, spaced or glued, is a
shell text; ``flock`` given a command as words runs it with no shell.

In a shell text an operator outside quotes ends a credential's value, so
the program after it is shown: two programs give two shown commands and two
hashes, and two passwords give one. A word run with no shell keeps its
operators, so the whole value stays hidden.
"""

from __future__ import annotations

import pytest

from pairbench import model
from pairbench.sides.identity import argv_sha256

# Made-up passwords that hold no credential word, and two programs to tell commands apart.
PASSWORDS = ("kiwi7mango", "plum4grape")
PROGRAMS = ("bench-old", "bench-new")

Form = tuple[tuple[str, ...], str, tuple[str, ...]]

# Forms whose text a shell runs: each with ``{s}`` for the password and ``{p}`` for the
# program, and the command as shown and hashed with the first password and program.
SHELL_TEXTS: dict[str, Form] = {
    "tmux-new-one-argument": (
        ("tmux", "new", "-d", "API_KEY={s};./{p}"),
        "tmux new -d 'API_KEY=<hidden>;./bench-old'",
        ("tmux", "new", "-d", "API_KEY=<hidden>;./bench-old"),
    ),
    "tmux-new-window-one-argument": (
        ("tmux", "new-window", "API_KEY={s}&&./{p}"),
        "tmux new-window 'API_KEY=<hidden>&&./bench-old'",
        ("tmux", "new-window", "API_KEY=<hidden>&&./bench-old"),
    ),
    "tmux-neww-one-argument": (
        ("tmux", "neww", "API_KEY={s}|./{p}"),
        "tmux neww 'API_KEY=<hidden>|./bench-old'",
        ("tmux", "neww", "API_KEY=<hidden>|./bench-old"),
    ),
    "tmux-splitw-one-argument": (
        ("tmux", "splitw", "-h", "API_KEY={s};./{p}"),
        "tmux splitw -h 'API_KEY=<hidden>;./bench-old'",
        ("tmux", "splitw", "-h", "API_KEY=<hidden>;./bench-old"),
    ),
    "tmux-new-session-one-argument": (
        ("tmux", "new-session", "-s", "made-up", "API_KEY={s};./{p}"),
        "tmux new-session -s made-up 'API_KEY=<hidden>;./bench-old'",
        ("tmux", "new-session", "-s", "made-up", "API_KEY=<hidden>;./bench-old"),
    ),
    "tmux-split-window-one-argument": (
        ("tmux", "split-window", "-t", "1", "API_KEY={s};./{p}"),
        "tmux split-window -t 1 'API_KEY=<hidden>;./bench-old'",
        ("tmux", "split-window", "-t", "1", "API_KEY=<hidden>;./bench-old"),
    ),
    "tmux-respawn-window-one-argument": (
        ("tmux", "respawn-window", "-k", "-t", "1", "API_KEY={s};./{p}"),
        "tmux respawn-window -k -t 1 'API_KEY=<hidden>;./bench-old'",
        ("tmux", "respawn-window", "-k", "-t", "1", "API_KEY=<hidden>;./bench-old"),
    ),
    "tmux-respawnp-one-argument": (
        ("tmux", "respawnp", "-k", "API_KEY={s}&&./{p}"),
        "tmux respawnp -k 'API_KEY=<hidden>&&./bench-old'",
        ("tmux", "respawnp", "-k", "API_KEY=<hidden>&&./bench-old"),
    ),
    "tmux-one-argument-before-its-own-separator": (
        ("tmux", "new", "-d", "API_KEY={s};./{p}", ";", "attach"),
        "tmux new -d 'API_KEY=<hidden>;./bench-old' ';' attach",
        ("tmux", "new", "-d", "API_KEY=<hidden>;./bench-old", ";", "attach"),
    ),
    "tmux-one-argument-in-sh-c": (
        ("sh", "-c", "tmux new -d 'API_KEY={s};./{p}'"),
        "sh -c 'tmux new -d '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
        ("sh", "-c", "tmux new -d 'API_KEY=<hidden>;./bench-old'"),
    ),
    "tmux-one-argument-in-ssh": (
        ("ssh", "made-up-host", "tmux new -d 'API_KEY={s};./{p}'"),
        "ssh made-up-host 'tmux new -d '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
        ("ssh", "made-up-host", "tmux new -d 'API_KEY=<hidden>;./bench-old'"),
    ),
    "tmux-one-argument-before-a-redirection-in-sh-c": (
        ("sh", "-c", "tmux new -d 'API_KEY={s};./{p}' >out.log"),
        "sh -c 'tmux new -d '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"' >out.log'",
        ("sh", "-c", "tmux new -d 'API_KEY=<hidden>;./bench-old' >out.log"),
    ),
    "watch-colour": (
        ("watch", "-c", "API_KEY={s};./{p}"),
        "watch -c 'API_KEY=<hidden>;./bench-old'",
        ("watch", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "watch-colour-in-a-group": (
        ("watch", "-tc", "API_KEY={s};./{p}"),
        "watch -tc 'API_KEY=<hidden>;./bench-old'",
        ("watch", "-tc", "API_KEY=<hidden>;./bench-old"),
    ),
    "watch-colour-before-an-interval": (
        ("watch", "-c", "-n", "1", "API_KEY={s};./{p}"),
        "watch -c -n 1 'API_KEY=<hidden>;./bench-old'",
        ("watch", "-c", "-n", "1", "API_KEY=<hidden>;./bench-old"),
    ),
    "watch-colour-in-sh-c": (
        ("sh", "-c", "watch -c 'API_KEY={s};./{p}'"),
        "sh -c 'watch -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
        ("sh", "-c", "watch -c 'API_KEY=<hidden>;./bench-old'"),
    ),
    "hyperfine-no-shell-option-of-a-remote-command": (
        ("hyperfine", "ssh -N made-up-host true", "API_KEY={s};./{p}"),
        "hyperfine 'ssh -N made-up-host true' 'API_KEY=<hidden>;./bench-old'",
        ("hyperfine", "ssh -N made-up-host true", "API_KEY=<hidden>;./bench-old"),
    ),
    "hyperfine-no-shell-option-of-a-remote-command-in-sh-c": (
        ("sh", "-c", "hyperfine 'ssh -N made-up-host true' 'API_KEY={s};./{p}'"),
        "sh -c 'hyperfine '\"'\"'ssh -N made-up-host true'\"'\"' "
        "'\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
        ("sh", "-c", "hyperfine 'ssh -N made-up-host true' 'API_KEY=<hidden>;./bench-old'"),
    ),
    "hyperfine-shell-option-of-a-remote-command": (
        ("hyperfine", "ssh -S none made-up-host true", "API_KEY={s};./{p}"),
        "hyperfine 'ssh -S none made-up-host true' 'API_KEY=<hidden>;./bench-old'",
        ("hyperfine", "ssh -S none made-up-host true", "API_KEY=<hidden>;./bench-old"),
    ),
    # The text of ``-c`` or ``--command`` that these programs hand to a shell.
    "su-command": (
        ("su", "bench", "-c", "API_KEY={s};./{p}"),
        "su bench -c 'API_KEY=<hidden>;./bench-old'",
        ("su", "bench", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "su-login-command": (
        ("su", "-", "bench", "-c", "API_KEY={s};./{p}"),
        "su - bench -c 'API_KEY=<hidden>;./bench-old'",
        ("su", "-", "bench", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "su-command-glued": (
        ("su", "bench", "--command=API_KEY={s};./{p}"),
        "su bench '--command=API_KEY=<hidden>;./bench-old'",
        ("su", "bench", "--command=API_KEY=<hidden>;./bench-old"),
    ),
    "su-command-in-sh-c": (
        ("sh", "-c", "su bench -c 'API_KEY={s};./{p}'"),
        "sh -c 'su bench -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
        ("sh", "-c", "su bench -c 'API_KEY=<hidden>;./bench-old'"),
    ),
    "runuser-command": (
        ("runuser", "-l", "bench", "-c", "API_KEY={s};./{p}"),
        "runuser -l bench -c 'API_KEY=<hidden>;./bench-old'",
        ("runuser", "-l", "bench", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "runuser-long-command": (
        ("runuser", "bench", "--command", "API_KEY={s};./{p}"),
        "runuser bench --command 'API_KEY=<hidden>;./bench-old'",
        ("runuser", "bench", "--command", "API_KEY=<hidden>;./bench-old"),
    ),
    "flock-command": (
        ("flock", "-w", "5", "made-up.lock", "-c", "API_KEY={s};./{p}"),
        "flock -w 5 made-up.lock -c 'API_KEY=<hidden>;./bench-old'",
        ("flock", "-w", "5", "made-up.lock", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "flock-long-command": (
        ("flock", "made-up.lock", "--command", "API_KEY={s};./{p}"),
        "flock made-up.lock --command 'API_KEY=<hidden>;./bench-old'",
        ("flock", "made-up.lock", "--command", "API_KEY=<hidden>;./bench-old"),
    ),
    "script-command": (
        ("script", "-q", "-c", "API_KEY={s};./{p}", "made-up.log"),
        "script -q -c 'API_KEY=<hidden>;./bench-old' made-up.log",
        ("script", "-q", "-c", "API_KEY=<hidden>;./bench-old", "made-up.log"),
    ),
    "script-command-glued-short": (
        ("script", "-q", "-cAPI_KEY={s};./{p}"),
        "script -q '-cAPI_KEY=<hidden>;./bench-old'",
        ("script", "-q", "-cAPI_KEY=<hidden>;./bench-old"),
    ),
    "fish-command": (
        ("fish", "-c", "API_KEY={s};./{p}"),
        "fish -c 'API_KEY=<hidden>;./bench-old'",
        ("fish", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "fish-command-glued": (
        ("fish", "--command=API_KEY={s};./{p}"),
        "fish '--command=API_KEY=<hidden>;./bench-old'",
        ("fish", "--command=API_KEY=<hidden>;./bench-old"),
    ),
}

# Forms whose command runs with no shell: an operator in a value is part of it, and the
# whole value stays hidden.
NO_SHELL: dict[str, Form] = {
    "hyperfine-shell-glued-none": (
        ("hyperfine", "--shell=none", "./{p} --token=kiwi7;{s}"),
        "hyperfine --shell=none './bench-old --token=<hidden>'",
        ("hyperfine", "--shell=none", "./bench-old --token=<hidden>"),
    ),
    "hyperfine-short-shell-glued-none": (
        ("hyperfine", "-Snone", "./{p} --token=kiwi7;{s}"),
        "hyperfine -Snone './bench-old --token=<hidden>'",
        ("hyperfine", "-Snone", "./bench-old --token=<hidden>"),
    ),
    "hyperfine-no-shell-in-sh-c": (
        ("sh", "-c", "hyperfine -N './{p} --token=kiwi7;{s}'"),
        "sh -c 'hyperfine -N '\"'\"'./bench-old --token=<hidden>'\"'\"''",
        ("sh", "-c", "hyperfine -N './bench-old --token=<hidden>'"),
    ),
    "hyperfine-shell-none-in-sh-c": (
        ("sh", "-c", "hyperfine -S none './{p} --token=kiwi7;{s}'"),
        "sh -c 'hyperfine -S none '\"'\"'./bench-old --token=<hidden>'\"'\"''",
        ("sh", "-c", "hyperfine -S none './bench-old --token=<hidden>'"),
    ),
    "watch-exec-colour-group": (
        ("watch", "-xc", "./{p}", "--token=kiwi7;{s}"),
        "watch -xc ./bench-old '--token=<hidden>'",
        ("watch", "-xc", "./bench-old", "--token=<hidden>"),
    ),
    "tmux-first-of-several-arguments": (
        ("tmux", "new", "-d", "--token=kiwi7;{s}", "./{p}"),
        "tmux new -d '--token=<hidden>' ./bench-old",
        ("tmux", "new", "-d", "--token=<hidden>", "./bench-old"),
    ),
    "tmux-first-of-several-arguments-in-sh-c": (
        ("sh", "-c", "tmux new -d '--token=kiwi7;{s}' ./{p}"),
        "sh -c 'tmux new -d '\"'\"'--token=<hidden>'\"'\"' ./bench-old'",
        ("sh", "-c", "tmux new -d '--token=<hidden>' ./bench-old"),
    ),
    "flock-runs-its-command-with-no-shell": (
        ("flock", "made-up.lock", "./{p}", "--token=kiwi7;{s}"),
        "flock made-up.lock ./bench-old '--token=<hidden>'",
        ("flock", "made-up.lock", "./bench-old", "--token=<hidden>"),
    ),
}

ALL = {**SHELL_TEXTS, **NO_SHELL}


def typed(form: tuple[str, ...], password: str, program: str) -> list[str]:
    return [word.replace("{s}", password).replace("{p}", program) for word in form]


@pytest.mark.parametrize("name", sorted(ALL))
def test_a_runner_s_command_is_shown_and_hashed_as_the_runner_runs_it(name: str) -> None:
    form, shown, hashed = ALL[name]
    argv = typed(form, PASSWORDS[0], PROGRAMS[0])

    assert model.public_command(argv) == shown
    assert model.hashed_argv(argv) == list(hashed)


@pytest.mark.parametrize("name", sorted(ALL))
def test_two_passwords_give_one_shown_command_and_one_hash(name: str) -> None:
    form, _shown, _hashed = ALL[name]
    one, other = (typed(form, password, PROGRAMS[0]) for password in PASSWORDS)

    assert model.public_command(one) == model.public_command(other)
    assert argv_sha256(one) == argv_sha256(other)


@pytest.mark.parametrize("name", sorted(ALL))
def test_two_programs_give_two_shown_commands_and_two_hashes(name: str) -> None:
    form, _shown, _hashed = ALL[name]
    old, new = (typed(form, PASSWORDS[0], program) for program in PROGRAMS)

    assert model.public_command(old) != model.public_command(new)
    assert argv_sha256(old) != argv_sha256(new)
