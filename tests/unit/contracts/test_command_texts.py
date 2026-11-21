# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A command text and the value of an ordinary variable are read word by word.

The shown command and every published hash read these the way they read the
text after ``sh -c``: a credential's value ends at the first blank, and the
words after it stay, so two programs stay two commands. A command text is the
remote command of ``ssh``, the commands of ``hyperfine``, ``watch``,
``parallel`` and ``tmux new``, the value of ``gcloud ... --command``, the text of
``env -S`` and the text a shell runs after an option group that holds ``c``. The
value of an ordinary ``NAME=VALUE`` is read the same way, each word still
through the shape rules, also when the value is quoted or the word is quoted
whole; a credential ``NAME`` hides its whole value. The
shared workload is read after each command side's own words, so a client named
only in a side's spec hides its password. A name that ``if``, ``lambda`` and
their kind put before ``:`` gives no value in a program's text, a value after a
bare name starts on its line, a credential query value ends at ``&``, and a
``user:password`` that is an address loses only its user part. In a text a
shell reads, a value given with ``=`` ends with its shell word, so ``NAME=``
and a blank give the empty value and the command after them is shown. A
command text that a shell runs is a shell text, so an operator outside quotes
ends a value there too, and the command after it is shown; the text of
``env -S`` and a command a runner is told to run with no shell keep the operator
in the value. Each word that such a runner passes to its program as one
argument (``watch -x``, ``parallel -q``, the words after the first of a ``tmux``
command) is read as any argument is, so a credential hides all of its word,
blanks and all; a no-shell option counts in a group (``watch -tx``) and, for
``hyperfine``, after its commands too.
"""

from __future__ import annotations

import dataclasses
import shlex
from typing import Any

import pytest

from pairbench import model
from pairbench.model import HIDDEN, canonical_json, sha256_hex
from pairbench.sides.identity import argv_sha256

# Two made-up passwords and two made-up random-looking values.
SECRET = "kiwi7"
OTHER = "plum4"
RANDOM = "X1y2Z3x4Y5z6X7y8Z9x0Y1z2X3y4Z5x6"
RANDOM_OTHER = "Q9xW7mP2vL8nR4tY6bC1dF5gH0jKzA3s"
# Two made-up random-looking values that hold a credential word, so each reads as a name too.
RANDOM_NAME = "X1y2Z3x4Y5z6TokenX7y8Z9x0Y1z2X3y4"
RANDOM_NAME_OTHER = "Q9xW7mP2vL8nTokenR4tY6bC1dF5gH0jK"

# Each form: the argument list as typed (``{s}`` the secret, ``{p}`` what tells two commands
# apart), the two values of ``{p}``, and the command shown and the list hashed with the secret
# ``SECRET`` and the first value of ``{p}``.
Form = tuple[tuple[str, ...], tuple[str, str], str, tuple[str, ...]]

THREADS = ("8", "16")
PROGRAMS = ("old", "new")

ORDINARY_VARIABLES: dict[str, Form] = {
    "env": (
        ("env", "MADE_UP_FLAGS=--api-key={s} --threads {p}", "mytool"),
        THREADS,
        "env 'MADE_UP_FLAGS=--api-key=<hidden> --threads 8' mytool",
        ("env", "MADE_UP_FLAGS=--api-key=<hidden> --threads 8", "mytool"),
    ),
    "docker-e": (
        ("docker", "run", "-e", "MADE_UP_FLAGS=--api-key={s} --threads {p}", "made-up-image"),
        THREADS,
        "docker run -e 'MADE_UP_FLAGS=--api-key=<hidden> --threads 8' made-up-image",
        ("docker", "run", "-e", "MADE_UP_FLAGS=--api-key=<hidden> --threads 8", "made-up-image"),
    ),
    "docker-env-glued": (
        ("docker", "run", "--env=MADE_UP_FLAGS=--api-key={s} --threads {p}", "made-up-image"),
        THREADS,
        "docker run '--env=MADE_UP_FLAGS=--api-key=<hidden> --threads 8' made-up-image",
        ("docker", "run", "--env=MADE_UP_FLAGS=--api-key=<hidden> --threads 8", "made-up-image"),
    ),
    "podman-env-separate-option": (
        ("podman", "run", "--env", "MADE_UP_FLAGS=--api-key {s} --threads {p}", "made-up-image"),
        THREADS,
        "podman run --env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' made-up-image",
        ("podman", "run", "--env", "MADE_UP_FLAGS=--api-key <hidden> --threads 8", "made-up-image"),
    ),
    "ssh-setenv": (
        (
            "ssh",
            "-o",
            "SetEnv=MADE_UP_FLAGS=--api-key={s} --threads {p}",
            "made-up-host",
            "./bench",
        ),
        THREADS,
        "ssh -o 'SetEnv=MADE_UP_FLAGS=--api-key=<hidden> --threads 8' made-up-host ./bench",
        (
            "ssh",
            "-o",
            "SetEnv=MADE_UP_FLAGS=--api-key=<hidden> --threads 8",
            "made-up-host",
            "./bench",
        ),
    ),
    "leading-assignment": (
        ("MADE_UP_FLAGS=--api-key={s} --threads {p}", "mytool"),
        THREADS,
        "'MADE_UP_FLAGS=--api-key=<hidden> --threads 8' mytool",
        ("MADE_UP_FLAGS=--api-key=<hidden> --threads 8", "mytool"),
    ),
    "name-with-a-dot": (
        ("mytool", "made.up=--api-key={s} --threads {p}"),
        THREADS,
        "mytool 'made.up=--api-key=<hidden> --threads 8'",
        ("mytool", "made.up=--api-key=<hidden> --threads 8"),
    ),
    "shape-hidden-word": (
        ("mytool", "flags={s} --threads {p}"),
        THREADS,
        "mytool 'flags=<hidden> --threads 8'",
        ("mytool", "flags=<hidden> --threads 8"),
    ),
}

COMMAND_TEXTS: dict[str, Form] = {
    "ssh": (
        ("ssh", "made-up-host", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "ssh made-up-host 'API_KEY=<hidden> ./bench-old'",
        ("ssh", "made-up-host", "API_KEY=<hidden> ./bench-old"),
    ),
    "ssh-options": (
        ("ssh", "-p", "2222", "-i", "./made-up-key", "made-up-host", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "ssh -p 2222 -i ./made-up-key made-up-host 'API_KEY=<hidden> ./bench-old'",
        (
            "ssh",
            "-p",
            "2222",
            "-i",
            "./made-up-key",
            "made-up-host",
            "API_KEY=<hidden> ./bench-old",
        ),
    ),
    "hyperfine": (
        ("hyperfine", "--warmup", "3", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "hyperfine --warmup 3 'API_KEY=<hidden> ./bench-old'",
        ("hyperfine", "--warmup", "3", "API_KEY=<hidden> ./bench-old"),
    ),
    "watch": (
        ("watch", "-n", "1", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "watch -n 1 'API_KEY=<hidden> ./bench-old'",
        ("watch", "-n", "1", "API_KEY=<hidden> ./bench-old"),
    ),
    "parallel": (
        ("parallel", "API_KEY={s} ./bench-{p} {}", ":::", "1", "2"),
        PROGRAMS,
        "parallel 'API_KEY=<hidden> ./bench-old {}' ::: 1 2",
        ("parallel", "API_KEY=<hidden> ./bench-old {}", ":::", "1", "2"),
    ),
    # ``hyperfine -N`` runs no shell but splits its command into words as a shell does.
    "hyperfine-without-a-shell": (
        ("hyperfine", "-N", "tool --api-key={s} --threads {p}"),
        THREADS,
        "hyperfine -N 'tool --api-key=<hidden> --threads 8'",
        ("hyperfine", "-N", "tool --api-key=<hidden> --threads 8"),
    ),
    # ``watch`` joins the words of its command with blanks and gives them to a shell, so a
    # blank in one of them ends a value as a blank in the text after ``-c`` does.
    "watch-words-joined": (
        ("watch", "tool", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "watch tool 'API_KEY=<hidden> ./bench-old'",
        ("watch", "tool", "API_KEY=<hidden> ./bench-old"),
    ),
    "tmux-new": (
        ("tmux", "new", "-d", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "tmux new -d 'API_KEY=<hidden> ./bench-old'",
        ("tmux", "new", "-d", "API_KEY=<hidden> ./bench-old"),
    ),
    "tmux-new-session": (
        ("tmux", "new-session", "-d", "-s", "made-up", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "tmux new-session -d -s made-up 'API_KEY=<hidden> ./bench-old'",
        ("tmux", "new-session", "-d", "-s", "made-up", "API_KEY=<hidden> ./bench-old"),
    ),
    "gcloud-command": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "gcloud compute ssh made-up-vm --command 'API_KEY=<hidden> ./bench-old'",
        ("gcloud", "compute", "ssh", "made-up-vm", "--command", "API_KEY=<hidden> ./bench-old"),
    ),
    "gcloud-command-glued": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command=API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "gcloud compute ssh made-up-vm '--command=API_KEY=<hidden> ./bench-old'",
        ("gcloud", "compute", "ssh", "made-up-vm", "--command=API_KEY=<hidden> ./bench-old"),
    ),
    "env-split-string": (
        ("env", "-S", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "env -S 'API_KEY=<hidden> ./bench-old'",
        ("env", "-S", "API_KEY=<hidden> ./bench-old"),
    ),
    "env-split-string-glued": (
        ("env", "--split-string=API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "env '--split-string=API_KEY=<hidden> ./bench-old'",
        ("env", "--split-string=API_KEY=<hidden> ./bench-old"),
    ),
    "sh-ce": (
        ("sh", "-ce", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "sh -ce 'API_KEY=<hidden> ./bench-old'",
        ("sh", "-ce", "API_KEY=<hidden> ./bench-old"),
    ),
    "sh-ec": (
        ("sh", "-ec", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "sh -ec 'API_KEY=<hidden> ./bench-old'",
        ("sh", "-ec", "API_KEY=<hidden> ./bench-old"),
    ),
    "bash-xc": (
        ("bash", "-xc", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "bash -xc 'API_KEY=<hidden> ./bench-old'",
        ("bash", "-xc", "API_KEY=<hidden> ./bench-old"),
    ),
    "sh-c-then-dashes": (
        ("sh", "-c", "--", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "sh -c -- 'API_KEY=<hidden> ./bench-old'",
        ("sh", "-c", "--", "API_KEY=<hidden> ./bench-old"),
    ),
    "bash-c-then-option": (
        ("bash", "-c", "-e", "API_KEY={s} ./bench-{p}"),
        PROGRAMS,
        "bash -c -e 'API_KEY=<hidden> ./bench-old'",
        ("bash", "-c", "-e", "API_KEY=<hidden> ./bench-old"),
    ),
    "ssh-inside-sh-c": (
        ("sh", "-c", "ssh made-up-host 'API_KEY={s} ./bench-{p}'"),
        PROGRAMS,
        "sh -c 'ssh made-up-host '\"'\"'API_KEY=<hidden> ./bench-old'\"'\"''",
        ("sh", "-c", "ssh made-up-host 'API_KEY=<hidden> ./bench-old'"),
    ),
    "bash-xc-inside-sh-c": (
        ("sh", "-c", "bash -xc 'API_KEY={s} ./bench-{p}'"),
        PROGRAMS,
        "sh -c 'bash -xc '\"'\"'API_KEY=<hidden> ./bench-old'\"'\"''",
        ("sh", "-c", "bash -xc 'API_KEY=<hidden> ./bench-old'"),
    ),
}

PROGRAM_TEXTS: dict[str, Form] = {
    "if-name-colon": (
        ("python3", "-c", "if token: run_{p}()"),
        PROGRAMS,
        "python3 -c 'if token: run_old()'",
        ("python3", "-c", "if token: run_old()"),
    ),
    "lambda-name-colon": (
        ("python3", "-c", "f = lambda token: run_{p}(token)"),
        PROGRAMS,
        "python3 -c 'f = lambda token: run_old(token)'",
        ("python3", "-c", "f = lambda token: run_old(token)"),
    ),
    "not-name-colon": (
        ("python3", "-c", "while not api_key: run_{p}()"),
        PROGRAMS,
        "python3 -c 'while not api_key: run_old()'",
        ("python3", "-c", "while not api_key: run_old()"),
    ),
    "if-name-colon-inside-sh-c": (
        ("sh", "-c", "python3 -c 'if token: run_{p}()'"),
        PROGRAMS,
        "sh -c 'python3 -c '\"'\"'if token: run_old()'\"'\"''",
        ("sh", "-c", "python3 -c 'if token: run_old()'"),
    ),
    "bare-name-then-line-break": (
        ("python3", "-c", "token=\n None\nrun_{p}()"),
        PROGRAMS,
        "python3 -c 'token=<hidden>\n None\nrun_old()'",
        ("python3", "-c", "token=<hidden>\n None\nrun_old()"),
    ),
}

ADDRESSES: dict[str, Form] = {
    "user-option-address": (
        ("mytool", "-u", "redis://:{s}@localhost:6379/{p}"),
        PROGRAMS,
        "mytool -u 'redis://<hidden>@localhost:6379/old'",
        ("mytool", "-u", "redis://<hidden>@localhost:6379/old"),
    ),
    "redis-cli-user-address": (
        ("redis-cli", "-u", "redis://:{s}@localhost:6379/{p}", "PING"),
        PROGRAMS,
        "redis-cli -u 'redis://<hidden>@localhost:6379/old' PING",
        ("redis-cli", "-u", "redis://<hidden>@localhost:6379/old", "PING"),
    ),
    "user-option-address-glued": (
        ("mytool", "--user=redis://:{s}@localhost:6379/{p}"),
        PROGRAMS,
        "mytool '--user=redis://<hidden>@localhost:6379/old'",
        ("mytool", "--user=redis://<hidden>@localhost:6379/old"),
    ),
    "token-query": (
        ("mytool", "--url", "http://localhost:8000/v1?token={s}&threads={p}"),
        THREADS,
        "mytool --url 'http://localhost:8000/v1?token=<hidden>&threads=8'",
        ("mytool", "--url", "http://localhost:8000/v1?token=<hidden>&threads=8"),
    ),
    "api-key-query": (
        ("mytool", "http://localhost:8000/v1?api_key={s}&n={p}"),
        THREADS,
        "mytool 'http://localhost:8000/v1?api_key=<hidden>&n=8'",
        ("mytool", "http://localhost:8000/v1?api_key=<hidden>&n=8"),
    ),
    "query-glued-to-an-option": (
        ("mytool", "--url=http://localhost:8000/v1?token={s}&threads={p}"),
        THREADS,
        "mytool '--url=http://localhost:8000/v1?token=<hidden>&threads=8'",
        ("mytool", "--url=http://localhost:8000/v1?token=<hidden>&threads=8"),
    ),
    "two-credentials-in-a-query": (
        ("mytool", "http://localhost:8000/v1?token={s}&api_key={s}&n={p}"),
        THREADS,
        "mytool 'http://localhost:8000/v1?token=<hidden>&api_key=<hidden>&n=8'",
        ("mytool", "http://localhost:8000/v1?token=<hidden>&api_key=<hidden>&n=8"),
    ),
    "query-inside-sh-c": (
        ("sh", "-c", "curl 'http://localhost:8000/v1?token={s}&threads={p}'"),
        THREADS,
        "sh -c 'curl '\"'\"'http://localhost:8000/v1?token=<hidden>&threads=8'\"'\"''",
        ("sh", "-c", "curl 'http://localhost:8000/v1?token=<hidden>&threads=8'"),
    ),
}

# Texts a shell runs, where a name glued to ``=`` and followed by a blank is given the empty
# value, as a shell gives it: the value ends where the shell word ends, and the operator and
# the command after it are shown and hashed.
EMPTY_VALUES: dict[str, Form] = {
    "empty-value-before-an-operator": (
        ("sh", "-c", "tool API_KEY= && ./bench-{p} --token {s}"),
        PROGRAMS,
        "sh -c 'tool API_KEY=<hidden> && ./bench-old --token <hidden>'",
        ("sh", "-c", "tool API_KEY=<hidden> && ./bench-old --token <hidden>"),
    ),
    "empty-value-before-a-command": (
        ("sh", "-c", "API_KEY= ./bench-{p} --token {s}"),
        PROGRAMS,
        "sh -c 'API_KEY=<hidden> ./bench-old --token <hidden>'",
        ("sh", "-c", "API_KEY=<hidden> ./bench-old --token <hidden>"),
    ),
    "random-name-ending-in-equals": (
        ("sh", "-c", "tool {s}= && ./bench-{p}"),
        PROGRAMS,
        "sh -c 'tool <hidden><hidden> && ./bench-old'",
        ("sh", "-c", "tool <hidden><hidden> && ./bench-old"),
    ),
    "random-name-ending-in-two-equals": (
        ("sh", "-c", "tool {s}== && ./bench-{p}"),
        PROGRAMS,
        "sh -c 'tool <hidden><hidden> && ./bench-old'",
        ("sh", "-c", "tool <hidden><hidden> && ./bench-old"),
    ),
    "empty-value-after-a-shell-group": (
        ("bash", "-ec", "API_KEY= ./bench-{p} --token {s}"),
        PROGRAMS,
        "bash -ec 'API_KEY=<hidden> ./bench-old --token <hidden>'",
        ("bash", "-ec", "API_KEY=<hidden> ./bench-old --token <hidden>"),
    ),
    "empty-value-in-a-runner-text": (
        ("hyperfine", "API_KEY= ./bench-{p} --token {s}"),
        PROGRAMS,
        "hyperfine 'API_KEY=<hidden> ./bench-old --token <hidden>'",
        ("hyperfine", "API_KEY=<hidden> ./bench-old --token <hidden>"),
    ),
    "empty-value-inside-ssh-inside-sh-c": (
        ("sh", "-c", "ssh made-up-host 'API_KEY= ./bench-{p} --token {s}'"),
        PROGRAMS,
        "sh -c 'ssh made-up-host '\"'\"'API_KEY=<hidden> ./bench-old --token <hidden>'\"'\"''",
        ("sh", "-c", "ssh made-up-host 'API_KEY=<hidden> ./bench-old --token <hidden>'"),
    ),
}

# Command texts a shell runs, where an operator outside quotes ends a command even when it is
# glued to the value before it: the value ends there, and the operator and the command after
# it are shown and hashed.
SHELL_OPERATORS: dict[str, Form] = {
    "operator-glued-in-sh-c": (
        ("sh", "-c", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "sh -c 'tool --api-key=<hidden>&&./bench-old'",
        ("sh", "-c", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-after-a-shell-group": (
        ("sh", "-ce", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "sh -ce 'tool --api-key=<hidden>&&./bench-old'",
        ("sh", "-ce", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-then-blank-after-a-shell-group": (
        ("sh", "-ce", "tool --api-key={s}&& ./bench-{p}"),
        PROGRAMS,
        "sh -ce 'tool --api-key=<hidden>&& ./bench-old'",
        ("sh", "-ce", "tool --api-key=<hidden>&& ./bench-old"),
    ),
    "operator-glued-after-sh-c-then-dashes": (
        ("sh", "-c", "--", "tool --api-key={s};./bench-{p}"),
        PROGRAMS,
        "sh -c -- 'tool --api-key=<hidden>;./bench-old'",
        ("sh", "-c", "--", "tool --api-key=<hidden>;./bench-old"),
    ),
    "operator-glued-after-bash-c-then-option": (
        ("bash", "-c", "-e", "tool --api-key={s}||./bench-{p}"),
        PROGRAMS,
        "bash -c -e 'tool --api-key=<hidden>||./bench-old'",
        ("bash", "-c", "-e", "tool --api-key=<hidden>||./bench-old"),
    ),
    "operator-glued-after-a-shell-option-value": (
        ("bash", "-o", "pipefail", "-c", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "bash -o pipefail -c 'tool --api-key=<hidden>|./bench-old'",
        ("bash", "-o", "pipefail", "-c", "tool --api-key=<hidden>|./bench-old"),
    ),
    "operator-glued-in-ssh": (
        ("ssh", "made-up-host", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "ssh made-up-host 'tool --api-key=<hidden>&&./bench-old'",
        ("ssh", "made-up-host", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-then-blank-in-ssh": (
        ("ssh", "made-up-host", "tool --api-key={s}&& ./bench-{p}"),
        PROGRAMS,
        "ssh made-up-host 'tool --api-key=<hidden>&& ./bench-old'",
        ("ssh", "made-up-host", "tool --api-key=<hidden>&& ./bench-old"),
    ),
    "variable-then-operator-in-ssh": (
        ("ssh", "made-up-host", "API_KEY={s};./bench-{p}"),
        PROGRAMS,
        "ssh made-up-host 'API_KEY=<hidden>;./bench-old'",
        ("ssh", "made-up-host", "API_KEY=<hidden>;./bench-old"),
    ),
    "operator-glued-in-hyperfine": (
        ("hyperfine", "tool --api-key={s};./bench-{p}"),
        PROGRAMS,
        "hyperfine 'tool --api-key=<hidden>;./bench-old'",
        ("hyperfine", "tool --api-key=<hidden>;./bench-old"),
    ),
    "operator-glued-in-watch": (
        ("watch", "-n", "1", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "watch -n 1 'tool --api-key=<hidden>&&./bench-old'",
        ("watch", "-n", "1", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-in-parallel": (
        ("parallel", "tool --api-key={s}&&./bench-{p} {}", ":::", "1"),
        PROGRAMS,
        "parallel 'tool --api-key=<hidden>&&./bench-old {}' ::: 1",
        ("parallel", "tool --api-key=<hidden>&&./bench-old {}", ":::", "1"),
    ),
    "operator-glued-in-tmux-new": (
        ("tmux", "new", "-d", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "tmux new -d 'tool --api-key=<hidden>|./bench-old'",
        ("tmux", "new", "-d", "tool --api-key=<hidden>|./bench-old"),
    ),
    # ``tmux`` runs a command given as one argument in a shell, blanks or none.
    "operator-in-tmux-word-without-a-blank": (
        ("tmux", "new", "-d", "API_KEY={s}&&./bench-{p}"),
        PROGRAMS,
        "tmux new -d 'API_KEY=<hidden>&&./bench-old'",
        ("tmux", "new", "-d", "API_KEY=<hidden>&&./bench-old"),
    ),
    # A group of short options with no option that turns the shell off leaves it on, and an
    # option at the end of a group that takes a value takes the next word.
    "operator-glued-in-watch-after-a-group": (
        ("watch", "-tb", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "watch -tb 'tool --api-key=<hidden>&&./bench-old'",
        ("watch", "-tb", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-in-hyperfine-after-a-group-naming-a-shell": (
        ("hyperfine", "-iS", "bash", "tool --api-key={s};./bench-{p}"),
        PROGRAMS,
        "hyperfine -iS bash 'tool --api-key=<hidden>;./bench-old'",
        ("hyperfine", "-iS", "bash", "tool --api-key=<hidden>;./bench-old"),
    ),
    "operator-glued-in-hyperfine-before-an-option": (
        ("hyperfine", "tool --api-key={s};./bench-{p}", "-i"),
        PROGRAMS,
        "hyperfine 'tool --api-key=<hidden>;./bench-old' -i",
        ("hyperfine", "tool --api-key=<hidden>;./bench-old", "-i"),
    ),
    "operator-glued-in-tmux-new-after-a-group": (
        ("tmux", "new", "-ds", "made-up", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "tmux new -ds made-up 'tool --api-key=<hidden>|./bench-old'",
        ("tmux", "new", "-ds", "made-up", "tool --api-key=<hidden>|./bench-old"),
    ),
    "operator-glued-in-gcloud-command": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "gcloud compute ssh made-up-vm --command 'tool --api-key=<hidden>&&./bench-old'",
        (
            "gcloud",
            "compute",
            "ssh",
            "made-up-vm",
            "--command",
            "tool --api-key=<hidden>&&./bench-old",
        ),
    ),
    "operator-glued-in-gcloud-command-glued": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command=tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "gcloud compute ssh made-up-vm '--command=tool --api-key=<hidden>&&./bench-old'",
        (
            "gcloud",
            "compute",
            "ssh",
            "made-up-vm",
            "--command=tool --api-key=<hidden>&&./bench-old",
        ),
    ),
    "operator-glued-in-ssh-inside-sh-c": (
        ("sh", "-c", "ssh made-up-host 'tool --api-key={s}&&./bench-{p}'"),
        PROGRAMS,
        "sh -c 'ssh made-up-host '\"'\"'tool --api-key=<hidden>&&./bench-old'\"'\"''",
        ("sh", "-c", "ssh made-up-host 'tool --api-key=<hidden>&&./bench-old'"),
    ),
    "operator-glued-in-ssh-named-in-quotes-inside-sh-c": (
        ("sh", "-c", "\"ss\"h made-up-host 'tool --api-key={s}&&./bench-{p}'"),
        PROGRAMS,
        "sh -c '\"ss\"h made-up-host '\"'\"'tool --api-key=<hidden>&&./bench-old'\"'\"''",
        ("sh", "-c", "\"ss\"h made-up-host 'tool --api-key=<hidden>&&./bench-old'"),
    ),
    "operator-glued-in-ssh-inside-ssh": (
        ("ssh", "made-up-host", "ssh other-host 'tool --api-key={s}&&./bench-{p}'"),
        PROGRAMS,
        "ssh made-up-host 'ssh other-host '\"'\"'tool --api-key=<hidden>&&./bench-old'\"'\"''",
        ("ssh", "made-up-host", "ssh other-host 'tool --api-key=<hidden>&&./bench-old'"),
    ),
    # Each spelling of a shell before its text: ``--``, a group of short options, an option
    # that takes a value, and long options.
    "operator-glued-after-bash-c-then-dashes": (
        ("bash", "-c", "--", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "bash -c -- 'tool --api-key=<hidden>&&./bench-old'",
        ("bash", "-c", "--", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-after-bash-ce": (
        ("bash", "-ce", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "bash -ce 'tool --api-key=<hidden>&&./bench-old'",
        ("bash", "-ce", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-after-bash-ec": (
        ("bash", "-ec", "tool --api-key={s};./bench-{p}"),
        PROGRAMS,
        "bash -ec 'tool --api-key=<hidden>;./bench-old'",
        ("bash", "-ec", "tool --api-key=<hidden>;./bench-old"),
    ),
    "operator-glued-after-bash-xc": (
        ("bash", "-xc", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "bash -xc 'tool --api-key=<hidden>|./bench-old'",
        ("bash", "-xc", "tool --api-key=<hidden>|./bench-old"),
    ),
    "operator-glued-after-sh-eu-c": (
        ("sh", "-eu", "-c", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "sh -eu -c 'tool --api-key=<hidden>&&./bench-old'",
        ("sh", "-eu", "-c", "tool --api-key=<hidden>&&./bench-old"),
    ),
    "operator-glued-after-bash-long-options": (
        ("bash", "--noprofile", "--norc", "-c", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "bash --noprofile --norc -c 'tool --api-key=<hidden>&&./bench-old'",
        ("bash", "--noprofile", "--norc", "-c", "tool --api-key=<hidden>&&./bench-old"),
    ),
    # A credential variable or header before an operator of ``sh -c``: the program after the
    # operator is shown and hashed, so two programs behind one credential are two sides.
    "variable-then-semicolon-in-sh-c": (
        ("sh", "-c", "API_KEY={s};./bench-{p}"),
        PROGRAMS,
        "sh -c 'API_KEY=<hidden>;./bench-old'",
        ("sh", "-c", "API_KEY=<hidden>;./bench-old"),
    ),
    "variable-then-semicolon-and-blank-in-sh-c": (
        ("sh", "-c", "API_KEY={s}; ./bench-{p}"),
        PROGRAMS,
        "sh -c 'API_KEY=<hidden>; ./bench-old'",
        ("sh", "-c", "API_KEY=<hidden>; ./bench-old"),
    ),
    "variable-then-and-in-sh-c": (
        ("sh", "-c", "API_KEY={s}&&./bench-{p}"),
        PROGRAMS,
        "sh -c 'API_KEY=<hidden>&&./bench-old'",
        ("sh", "-c", "API_KEY=<hidden>&&./bench-old"),
    ),
    "variable-then-pipe-in-sh-c": (
        ("sh", "-c", "API_KEY={s}|./bench-{p}"),
        PROGRAMS,
        "sh -c 'API_KEY=<hidden>|./bench-old'",
        ("sh", "-c", "API_KEY=<hidden>|./bench-old"),
    ),
    "header-then-semicolon-in-sh-c": (
        ("sh", "-c", "curl -H 'Authorization: Bearer {s}'; ./bench-{p}"),
        PROGRAMS,
        "sh -c 'curl -H '\"'\"'Authorization: <hidden>'\"'\"'; ./bench-old'",
        ("sh", "-c", "curl -H 'Authorization: <hidden>'; ./bench-old"),
    ),
    # A shell text inside a shell text, whose first word gives a credential variable its value
    # glued to an operator: the value ends there, as it does in the outer text.
    "variable-then-operator-in-sh-c-inside-sh-c": (
        ("sh", "-c", 'sh -c "API_KEY={s}&&./bench-{p}" && ls'),
        PROGRAMS,
        "sh -c 'sh -c \"API_KEY=<hidden>&&./bench-old\" && ls'",
        ("sh", "-c", 'sh -c "API_KEY=<hidden>&&./bench-old" && ls'),
    ),
    "variable-then-semicolon-in-bash-c-inside-sh-c": (
        ("sh", "-c", 'bash -c "API_KEY={s};./bench-{p}"'),
        PROGRAMS,
        "sh -c 'bash -c \"API_KEY=<hidden>;./bench-old\"'",
        ("sh", "-c", 'bash -c "API_KEY=<hidden>;./bench-old"'),
    ),
    "variable-then-pipe-in-single-quotes-inside-sh-c": (
        ("sh", "-c", "bash -c 'API_KEY={s}|./bench-{p}'"),
        PROGRAMS,
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden>|./bench-old'\"'\"''",
        ("sh", "-c", "bash -c 'API_KEY=<hidden>|./bench-old'"),
    ),
    "variable-then-operator-in-ssh-inside-sh-c": (
        ("sh", "-c", 'ssh made-up-host "API_KEY={s}&&./bench-{p}"'),
        PROGRAMS,
        "sh -c 'ssh made-up-host \"API_KEY=<hidden>&&./bench-old\"'",
        ("sh", "-c", 'ssh made-up-host "API_KEY=<hidden>&&./bench-old"'),
    ),
    "variable-then-operator-in-hyperfine-inside-sh-c": (
        ("sh", "-c", 'hyperfine "API_KEY={s};./bench-{p}"'),
        PROGRAMS,
        "sh -c 'hyperfine \"API_KEY=<hidden>;./bench-old\"'",
        ("sh", "-c", 'hyperfine "API_KEY=<hidden>;./bench-old"'),
    ),
    "variable-then-operator-in-sh-c-inside-ssh": (
        ("ssh", "made-up-host", 'sh -c "DB_PASSWORD={s}&&./bench-{p}"'),
        PROGRAMS,
        "ssh made-up-host 'sh -c \"DB_PASSWORD=<hidden>&&./bench-old\"'",
        ("ssh", "made-up-host", 'sh -c "DB_PASSWORD=<hidden>&&./bench-old"'),
    ),
    # A quoted word of a shell text that is no command text is one value, operators and all.
    "quoted-header-in-ssh": (
        ("ssh", "made-up-host", "curl -H 'Cookie: a=1; sid={s}' ./bench-{p}"),
        PROGRAMS,
        "ssh made-up-host 'curl -H '\"'\"'Cookie: <hidden>'\"'\"' ./bench-old'",
        ("ssh", "made-up-host", "curl -H 'Cookie: <hidden>' ./bench-old"),
    ),
}

# An ordinary name whose value is quoted, or a word quoted whole that gives an ordinary name its
# value, as a shell text writes the value of ``env``, ``docker run -e`` or an option: the value
# is read as the value of one argument, so a credential option there hides the next word.
QUOTED_VALUES: dict[str, Form] = {
    "quoted-value-of-env-in-a-shell-text": (
        ("sh", "-c", 'env MADE_UP_FLAGS="--api-key {s} --threads {p}" mytool'),
        THREADS,
        "sh -c 'env MADE_UP_FLAGS=\"--api-key <hidden> --threads 8\" mytool'",
        ("sh", "-c", 'env MADE_UP_FLAGS="--api-key <hidden> --threads 8" mytool'),
    ),
    "quoted-value-in-a-shell-text": (
        ("sh", "-c", 'MADE_UP_FLAGS="--api-key {s} --threads {p}" mytool'),
        THREADS,
        "sh -c 'MADE_UP_FLAGS=\"--api-key <hidden> --threads 8\" mytool'",
        ("sh", "-c", 'MADE_UP_FLAGS="--api-key <hidden> --threads 8" mytool'),
    ),
    "single-quoted-value-in-a-shell-text": (
        ("sh", "-c", "MADE_UP_FLAGS='--api-key {s} --threads {p}' mytool"),
        THREADS,
        "sh -c 'MADE_UP_FLAGS='\"'\"'--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "MADE_UP_FLAGS='--api-key <hidden> --threads 8' mytool"),
    ),
    "quoted-value-before-an-operator": (
        ("sh", "-c", 'MADE_UP_OPTS="--password {s} --threads {p}"; ./bench $MADE_UP_OPTS'),
        THREADS,
        "sh -c 'MADE_UP_OPTS=\"--password <hidden> --threads 8\"; ./bench $MADE_UP_OPTS'",
        ("sh", "-c", 'MADE_UP_OPTS="--password <hidden> --threads 8"; ./bench $MADE_UP_OPTS'),
    ),
    "quoted-value-with-a-glued-option": (
        ("sh", "-c", 'MADE_UP_OPTS="--password={s} --threads {p}" ./bench $MADE_UP_OPTS'),
        THREADS,
        "sh -c 'MADE_UP_OPTS=\"--password=<hidden> --threads 8\" ./bench $MADE_UP_OPTS'",
        ("sh", "-c", 'MADE_UP_OPTS="--password=<hidden> --threads 8" ./bench $MADE_UP_OPTS'),
    ),
    "quoted-value-in-ssh": (
        ("ssh", "made-up-host", 'MADE_UP_FLAGS="--api-key {s} --threads {p}" ./bench'),
        THREADS,
        "ssh made-up-host 'MADE_UP_FLAGS=\"--api-key <hidden> --threads 8\" ./bench'",
        ("ssh", "made-up-host", 'MADE_UP_FLAGS="--api-key <hidden> --threads 8" ./bench'),
    ),
    "quoted-value-of-docker-e": (
        ("docker", "run", "-e", 'MADE_UP_FLAGS="--password {s} --threads {p}"', "made-up-image"),
        THREADS,
        "docker run -e 'MADE_UP_FLAGS=\"--password <hidden> --threads 8\"' made-up-image",
        ("docker", "run", "-e", 'MADE_UP_FLAGS="--password <hidden> --threads 8"', "made-up-image"),
    ),
    "quoted-value-of-an-option": (
        ("mytool", '--extra="--api-key {s} --threads {p}"'),
        THREADS,
        "mytool '--extra=\"--api-key <hidden> --threads 8\"'",
        ("mytool", '--extra="--api-key <hidden> --threads 8"'),
    ),
    "whole-quoted-value-of-env-in-a-shell-text": (
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key {s} --threads {p}' mytool"),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    "whole-quoted-value-of-env-in-ssh": (
        ("ssh", "made-up-host", "env 'MADE_UP_FLAGS=--api-key {s} --threads {p}' mytool"),
        THREADS,
        "ssh made-up-host 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("ssh", "made-up-host", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    "whole-quoted-value-of-docker-e-in-a-shell-text": (
        ("sh", "-c", "docker run -e 'MADE_UP_FLAGS=--token {s} --threads {p}' made-up-image"),
        THREADS,
        "sh -c 'docker run -e '\"'\"'MADE_UP_FLAGS=--token <hidden> --threads 8'\"'\"' "
        "made-up-image'",
        ("sh", "-c", "docker run -e 'MADE_UP_FLAGS=--token <hidden> --threads 8' made-up-image"),
    ),
    "whole-quoted-option-in-a-shell-text": (
        ("sh", "-c", "mytool '--extra=--api-key {s} --threads {p}'"),
        THREADS,
        "sh -c 'mytool '\"'\"'--extra=--api-key <hidden> --threads 8'\"'\"''",
        ("sh", "-c", "mytool '--extra=--api-key <hidden> --threads 8'"),
    ),
    "whole-quoted-word-of-an-argument": (
        ("mytool", "made-up 'MADE_UP_FLAGS=--api-key {s} --threads {p}'"),
        THREADS,
        "mytool 'made-up '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"''",
        ("mytool", "made-up 'MADE_UP_FLAGS=--api-key <hidden> --threads 8'"),
    ),
    "quoted-header-value": (
        ("sh", "-c", 'MADE_UP_FLAGS="Authorization: Bearer {s}" ./bench-{p}'),
        PROGRAMS,
        "sh -c 'MADE_UP_FLAGS=\"Authorization: <hidden>\" ./bench-old'",
        ("sh", "-c", 'MADE_UP_FLAGS="Authorization: <hidden>" ./bench-old'),
    ),
    # A value of several quoted parts is read as the shell joins them, and shown quoted whole.
    "quoted-parts-of-a-value": (
        ("sh", "-c", "env MADE_UP_FLAGS=\"--api-key {s} \"'--threads {p}' mytool"),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    "quoted-word-glued-to-more": (
        ("sh", "-c", 'env "MADE_UP_FLAGS=--api-key {s} --threads "{p} mytool'),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    "double-quoted-whole-word": (
        ("sh", "-c", 'env "MADE_UP_FLAGS=--api-key {s} --threads {p}" mytool'),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    # Inside double quotes ``\"`` is a quote of the value, so the quoted word after the
    # credential option is hidden whole.
    "escaped-quotes-in-quoted-parts": (
        ("sh", "-c", 'env MADE_UP_FLAGS="--api-key \\"{s} b\\" "' + "'--threads {p}' mytool"),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=--api-key <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool"),
    ),
    "escaped-quotes-around-an-option-in-a-value": (
        ("sh", "-c", 'env MADE_UP_FLAGS="\\"--api-key\\" {s} --threads {p}" mytool'),
        THREADS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=\"--api-key\" <hidden> --threads 8'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=\"--api-key\" <hidden> --threads 8' mytool"),
    ),
}

# A word of a shell text with quoted parts gives one argument, the word with its quotes and
# escapes taken off; a second shell that runs the text, as the remote shell of ``ssh`` does,
# splits that argument into words. Each is read so, and shown quoted whole when it hides.
QUOTED_PARTS: dict[str, Form] = {
    "quoted-part-of-an-argument": (
        ("sh", "-c", 'mytool --token" {s}" --threads {p}'),
        THREADS,
        "sh -c 'mytool '\"'\"'--token <hidden>'\"'\"' --threads 8'",
        ("sh", "-c", "mytool '--token <hidden>' --threads 8"),
    ),
    "quoted-part-in-ssh-in-a-shell-text": (
        ("sh", "-c", 'ssh made-up-host ./bench --token" {s}" --threads {p}'),
        THREADS,
        "sh -c 'ssh made-up-host ./bench '\"'\"'--token <hidden>'\"'\"' --threads 8'",
        ("sh", "-c", "ssh made-up-host ./bench '--token <hidden>' --threads 8"),
    ),
    "escaped-blank-in-ssh-in-a-shell-text": (
        ("sh", "-c", "ssh made-up-host ./bench --token\\ {s} --threads {p}"),
        THREADS,
        "sh -c 'ssh made-up-host ./bench '\"'\"'--token <hidden>'\"'\"' --threads 8'",
        ("sh", "-c", "ssh made-up-host ./bench '--token <hidden>' --threads 8"),
    ),
    # The remote shell runs ``./bench-old`` with the option: the program stays shown.
    "value-of-a-name-in-ssh-in-a-shell-text": (
        ("sh", "-c", 'ssh made-up-host MADE_UP_FLAGS="--api-key ./bench-{p} --token {s}"'),
        PROGRAMS,
        "sh -c 'ssh made-up-host '\"'\"'MADE_UP_FLAGS=--api-key ./bench-old"
        " --token <hidden>'\"'\"''",
        ("sh", "-c", "ssh made-up-host 'MADE_UP_FLAGS=--api-key ./bench-old --token <hidden>'"),
    ),
    # A text with ``$`` is shown in single quotes, where a shell reads no ``$``.
    "dollar-sign-in-a-quoted-part-in-ssh-in-a-shell-text": (
        (
            "sh",
            "-c",
            "ssh made-up-host ./bench\" --token {s} '\\$MADE_UP' 'a b' --threads {p}\"",
        ),
        THREADS,
        (
            "sh -c 'ssh made-up-host '\"'\"'./bench --token <hidden> '\"'\"'\""
            "'\"'\"'\"'\"'\"'$MADE_UP'\"'\"'\"'\"'\"'\"'\"'\"' '\"'\"'\"'\"'\"'\"'\"'\"'a b'\"'"
            "\"'\"'\"'\"'\"'\"'\"' --threads 8'\"'\"''"
        ),
        (
            "sh",
            "-c",
            "ssh made-up-host './bench --token <hidden> '\"'\"'$MADE_UP'\"'\"' "
            "'\"'\"'a b'\"'\"' --threads 8'",
        ),
    ),
    # The remote shell ends the value at ``|``: the program after it stays shown.
    "operator-in-a-quoted-part-in-ssh-in-a-shell-text": (
        ("sh", "-c", 'ssh made-up-host ./bench" --token {s}|./bench-{p}"'),
        PROGRAMS,
        "sh -c 'ssh made-up-host '\"'\"'./bench --token <hidden>|./bench-old'\"'\"''",
        ("sh", "-c", "ssh made-up-host './bench --token <hidden>|./bench-old'"),
    ),
    "quoted-part-in-a-shell-text-in-a-shell-text": (
        ("sh", "-c", 'sh -c ./bench-{p}" --token {s}"'),
        PROGRAMS,
        "sh -c 'sh -c '\"'\"'./bench-old --token <hidden>'\"'\"''",
        ("sh", "-c", "sh -c './bench-old --token <hidden>'"),
    ),
    "quoted-part-in-hyperfine-in-a-shell-text": (
        ("sh", "-c", 'hyperfine ./bench-{p}" --token {s}"'),
        PROGRAMS,
        "sh -c 'hyperfine '\"'\"'./bench-old --token <hidden>'\"'\"''",
        ("sh", "-c", "hyperfine './bench-old --token <hidden>'"),
    ),
    # Inside a word in single quotes the word is shown in double quotes, inside one in double
    # quotes in single quotes, and inside both with its blank escaped, so the quotes around it
    # still hold and the shell that runs the text splits it into the words typed.
    "quoted-part-in-a-single-quoted-shell-text-in-a-shell-text": (
        ("sh", "-c", "sh -c './bench-{p} --token\" {s}\"'"),
        PROGRAMS,
        "sh -c 'sh -c '\"'\"'./bench-old \"--token <hidden>\"'\"'\"''",
        ("sh", "-c", "sh -c './bench-old \"--token <hidden>\"'"),
    ),
    "quoted-parts-around-an-operator-in-a-single-quoted-shell-text": (
        ("sh", "-c", 'sh -c \'./bench-{p} --token" {s}" && ./bench --api-key" {s}"\''),
        PROGRAMS,
        (
            "sh -c 'sh -c '\"'\"'./bench-old \"--token <hidden>\""
            " && ./bench \"--api-key <hidden>\"'\"'\"''"
        ),
        ("sh", "-c", 'sh -c \'./bench-old "--token <hidden>" && ./bench "--api-key <hidden>"\''),
    ),
    "escaped-blank-in-a-single-quoted-ssh-command": (
        ("sh", "-c", "ssh made-up-host './bench --token\\ {s} --threads {p}'"),
        THREADS,
        "sh -c 'ssh made-up-host '\"'\"'./bench \"--token <hidden>\" --threads 8'\"'\"''",
        ("sh", "-c", "ssh made-up-host './bench \"--token <hidden>\" --threads 8'"),
    ),
    "escaped-blank-in-a-double-quoted-ssh-command": (
        ("sh", "-c", 'ssh made-up-host "./bench --token\\ {s} --threads {p}"'),
        THREADS,
        "sh -c 'ssh made-up-host \"./bench '\"'\"'--token <hidden>'\"'\"' --threads 8\"'",
        ("sh", "-c", "ssh made-up-host \"./bench '--token <hidden>' --threads 8\""),
    ),
    "escaped-blank-in-ssh-in-a-single-quoted-shell-text": (
        ("sh", "-c", "sh -c 'ssh made-up-host \"./bench --token\\ {s} --threads {p}\"'"),
        THREADS,
        "sh -c 'sh -c '\"'\"'ssh made-up-host \"./bench --token\\ <hidden> --threads 8\"'\"'\"''",
        ("sh", "-c", "sh -c 'ssh made-up-host \"./bench --token\\ <hidden> --threads 8\"'"),
    ),
    # In double quotes a ``$`` is escaped, so the shell that runs the text reads none.
    "dollar-sign-in-quoted-parts-in-a-single-quoted-shell-text": (
        ("sh", "-c", "sh -c './bench --threads\" {p} $MADE_UP --token {s}\"'"),
        THREADS,
        "sh -c 'sh -c '\"'\"'./bench \"--threads 8 \\$MADE_UP --token <hidden>\"'\"'\"''",
        ("sh", "-c", "sh -c './bench \"--threads 8 \\$MADE_UP --token <hidden>\"'"),
    ),
    # The value of a name in double quotes inside single quotes keeps its escaped blank.
    "escaped-blank-in-a-quoted-value-in-a-single-quoted-shell-text": (
        ("sh", "-c", "sh -c 'env MADE_UP_FLAGS=\"--name\\ x --token\\ {s}\" ./bench-{p}'"),
        PROGRAMS,
        (
            "sh -c 'sh -c '\"'\"'env MADE_UP_FLAGS=\"--name\\ x --token\\ <hidden>\""
            " ./bench-old'\"'\"''"
        ),
        ("sh", "-c", "sh -c 'env MADE_UP_FLAGS=\"--name\\ x --token\\ <hidden>\" ./bench-old'"),
    ),
    # A word that holds a quote it cannot be written with inside both kinds is hidden whole.
    "quote-in-a-word-inside-both-kinds-of-quotes": (
        ("sh", "-c", 'sh -c \'ssh made-up-host "./bench-{p} --name\\ a\\\\\\"b\\ --token\\ {s}"\''),
        PROGRAMS,
        "sh -c 'sh -c '\"'\"'ssh made-up-host \"./bench-old <hidden>\"'\"'\"''",
        ("sh", "-c", "sh -c 'ssh made-up-host \"./bench-old <hidden>\"'"),
    ),
    # The value of a client's ``command`` option in quoted parts is that client's own command.
    "escaped-blank-in-a-client-command": (
        ("sh", "-c", "memtier_benchmark --command AUTH\\ {s} && ./bench-{p}"),
        PROGRAMS,
        "sh -c 'memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"' && ./bench-old'",
        ("sh", "-c", "memtier_benchmark --command 'AUTH <hidden>' && ./bench-old"),
    ),
    "quoted-part-of-a-client-command": (
        ("sh", "-c", 'memtier_benchmark --command AUTH" {s}" && ./bench-{p}'),
        PROGRAMS,
        "sh -c 'memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"' && ./bench-old'",
        ("sh", "-c", "memtier_benchmark --command 'AUTH <hidden>' && ./bench-old"),
    ),
}

# Quoted values of ordinary names and quoted parts of words that hold no credential: each is
# shown and hashed as typed.
QUOTED_VALUES_AS_TYPED = (
    ("sh", "-c", "env MADE_UP_FLAGS=\"a b\"'c d' mytool"),
    ("mytool", "MADE_UP_FLAGS=\"a b\"'c d'"),
    ("sh", "-c", "env 'MADE_UP_FLAGS=a b' \"made.up=c d\" mytool"),
    ("docker", "run", "-e", 'MADE_UP_FLAGS="--threads 8 --mode fast"', "made-up-image"),
    ("sh", "-c", 'ssh made-up-host ./bench --threads" 8"'),
    ("sh", "-c", 'mytool --name" made up" -n 8'),
    ("sh", "-c", 'sh -c ./bench-old" -n 8"'),
)


@pytest.mark.parametrize("argv", QUOTED_VALUES_AS_TYPED)
def test_a_quoted_value_with_no_credential_is_shown_and_hashed_as_typed(
    argv: tuple[str, ...],
) -> None:
    assert model.public_command(argv) == shlex.join(argv)
    assert model.hashed_argv(argv) == list(argv)


# How many times a remote command of ``ssh`` is written inside another, each time in quoted
# parts, in the double quotes and escapes or in the single quotes a shell writes it with.
NESTED_LEVELS = 6


def _escaped(text: str) -> str:
    """The text as it is written inside double quotes."""
    for mark in ("\\", '"', "$", "`"):
        text = text.replace(mark, "\\" + mark)
    return text


@pytest.mark.parametrize("quotes", ["double", "single"])
def test_a_word_in_quoted_parts_inside_another_is_shown_about_as_long_as_typed(
    quotes: str,
) -> None:
    text = f"./bench --token {SECRET} --threads 8"
    for _ in range(NESTED_LEVELS):
        part = f'" {_escaped(text)}"' if quotes == "double" else shlex.quote(f" {text}")
        text = "ssh made-up-host ./bench" + part
    argv = ("sh", "-c", text)

    shown = model.public_command(argv)

    assert shown is not None
    assert SECRET not in shown
    assert len(shown) <= len(shlex.join(argv))
    assert shlex.split(shown) == model.hashed_argv(argv)


# Shell texts with a credential in quoted parts inside quoted words, and how many words a
# shell splits each level into: the text, then each text after ``-c`` of a shell and each
# remote command of ``ssh`` in it, depth first.
QUOTED_PARTS_LEVELS = (
    (f"sh -c './bench-old --token\" {SECRET}\"'", (3, 2)),
    (f'sh -c \'./bench-old --token" {SECRET}" && ./bench --api-key" {SECRET}"\'', (3, 5)),
    (f"ssh made-up-host './bench --token\\ {SECRET} --threads 8'", (3, 4)),
    (f'ssh made-up-host "./bench --token\\ {SECRET} --threads 8"', (3, 4)),
    (f"sh -c 'ssh made-up-host \"./bench --token\\ {SECRET} --threads 8\"'", (3, 3, 4)),
    (f'sh -c \'echo "$HOME" && ./bench --token" {SECRET}$MADE_UP"\'', (3, 5)),
    (f"sh -c 'mytool MADE_UP_FLAGS=--api-key\" {SECRET} --threads 8\"'", (3, 2)),
    (f'sh -c \'ssh made-up-host ./bench" --token\\" {SECRET}\\""\'', (3, 3, 2)),
)


def _levels(text: str) -> tuple[int, ...]:
    """The number of words of a shell text and of each shell text in it, depth first."""
    words = shlex.split(text)
    found = [len(words)]
    if words[:1] == ["ssh"] and len(words) > 2:
        found.extend(_levels(" ".join(words[2:])))
    for at, word in enumerate(words[1:-1], start=1):
        if word == "-c" and words[at - 1] in ("sh", "bash"):
            found.extend(_levels(words[at + 1]))
    return tuple(found)


@pytest.mark.parametrize(("text", "levels"), QUOTED_PARTS_LEVELS)
def test_a_word_in_quoted_parts_inside_quoted_words_splits_into_the_words_typed(
    text: str, levels: tuple[int, ...]
) -> None:
    argv = ("sh", "-c", text)

    shown = model.public_command(argv)

    assert shown is not None
    assert SECRET not in shown
    assert _levels(text) == levels
    assert _levels(shlex.split(shown)[2]) == levels
    assert shlex.split(shown) == model.hashed_argv(argv)


READ_BY_WORDS: dict[str, Form] = {
    **ORDINARY_VARIABLES,
    **COMMAND_TEXTS,
    **PROGRAM_TEXTS,
    **ADDRESSES,
    **EMPTY_VALUES,
    **SHELL_OPERATORS,
    **QUOTED_VALUES,
    **QUOTED_PARTS,
}

# Forms whose whole value stays hidden: the words after the first blank are part of the
# value, so two values of ``{p}`` give one shown command and one hash.
WHOLE_VALUES: dict[str, Form] = {
    "credential-variable": (
        ("env", "DB_PASSWORD={s} {p}", "mytool"),
        PROGRAMS,
        "env 'DB_PASSWORD=<hidden>' mytool",
        ("env", "DB_PASSWORD=<hidden>", "mytool"),
    ),
    "lower-case-credential-name": (
        ("env", "password={s} {p}", "mytool"),
        PROGRAMS,
        "env 'password=<hidden>' mytool",
        ("env", "password=<hidden>", "mytool"),
    ),
    "mixed-case-credential-name-with-a-dash": (
        ("mytool", "Api-Key={s} {p}"),
        PROGRAMS,
        "mytool 'Api-Key=<hidden>'",
        ("mytool", "Api-Key=<hidden>"),
    ),
    "credential-name-with-a-dot": (
        ("mytool", "db.password={s} {p}"),
        PROGRAMS,
        "mytool 'db.password=<hidden>'",
        ("mytool", "db.password=<hidden>"),
    ),
    "credential-name-after-an-ordinary-one": (
        ("ssh", "-o", "SetEnv=DB_PASSWORD={s} {p}", "made-up-host", "./bench"),
        PROGRAMS,
        "ssh -o 'SetEnv=DB_PASSWORD=<hidden>' made-up-host ./bench",
        ("ssh", "-o", "SetEnv=DB_PASSWORD=<hidden>", "made-up-host", "./bench"),
    ),
    "credential-option-of-an-ordinary-program": (
        ("mytool", "--mode", "parallel", "--api-key={s} {p}"),
        PROGRAMS,
        "mytool --mode parallel '--api-key=<hidden>'",
        ("mytool", "--mode", "parallel", "--api-key=<hidden>"),
    ),
    "command-option-of-an-ordinary-program": (
        ("mytool", "--command", "DB_PASSWORD={s} {p}"),
        PROGRAMS,
        "mytool --command 'DB_PASSWORD=<hidden>'",
        ("mytool", "--command", "DB_PASSWORD=<hidden>"),
    ),
    "tmux-variable": (
        ("tmux", "new", "-e", "DB_PASSWORD={s} {p}", "./bench"),
        PROGRAMS,
        "tmux new -e 'DB_PASSWORD=<hidden>' ./bench",
        ("tmux", "new", "-e", "DB_PASSWORD=<hidden>", "./bench"),
    ),
    "credential-name-with-a-random-value": (
        ("mytool", "auth={s} {p}"),
        PROGRAMS,
        "mytool 'auth=<hidden>'",
        ("mytool", "auth=<hidden>"),
    ),
    # A credential name in the quoted value of an ordinary one hides its whole value there too.
    "credential-name-in-a-quoted-value": (
        ("sh", "-c", 'env MADE_UP_FLAGS="DB_PASSWORD={s} {p}" mytool'),
        PROGRAMS,
        "sh -c 'env MADE_UP_FLAGS=\"DB_PASSWORD=<hidden>\" mytool'",
        ("sh", "-c", 'env MADE_UP_FLAGS="DB_PASSWORD=<hidden>" mytool'),
    ),
    "credential-name-in-a-whole-quoted-value": (
        ("sh", "-c", "env 'MADE_UP_FLAGS=DB_PASSWORD={s} {p}' mytool"),
        PROGRAMS,
        "sh -c 'env '\"'\"'MADE_UP_FLAGS=DB_PASSWORD=<hidden>'\"'\"' mytool'",
        ("sh", "-c", "env 'MADE_UP_FLAGS=DB_PASSWORD=<hidden>' mytool"),
    ),
    "whole-quoted-credential-in-a-shell-text": (
        ("sh", "-c", "env 'DB_PASSWORD={s} {p}' mytool"),
        PROGRAMS,
        "sh -c 'env '\"'\"'DB_PASSWORD=<hidden>'\"'\"' mytool'",
        ("sh", "-c", "env 'DB_PASSWORD=<hidden>' mytool"),
    ),
    # ``env -S`` splits its text into words and runs no shell, so an operator there is part
    # of the word it stands in.
    "operator-in-env-split-string": (
        ("env", "-S", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "env -S 'tool --api-key=<hidden>'",
        ("env", "-S", "tool --api-key=<hidden>"),
    ),
    "operator-in-env-split-string-glued": (
        ("env", "--split-string=tool --api-key={s};./bench-{p}"),
        PROGRAMS,
        "env '--split-string=tool --api-key=<hidden>'",
        ("env", "--split-string=tool --api-key=<hidden>"),
    ),
    # A runner told to run its command with no shell passes each word to the program as it
    # stands, so an operator there is part of the word too.
    "operator-in-watch-exec": (
        ("watch", "-x", "tool", "--api-key={s};./bench-{p}"),
        PROGRAMS,
        "watch -x tool '--api-key=<hidden>'",
        ("watch", "-x", "tool", "--api-key=<hidden>"),
    ),
    "operator-in-hyperfine-without-a-shell": (
        ("hyperfine", "-N", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "hyperfine -N 'tool --api-key=<hidden>'",
        ("hyperfine", "-N", "tool --api-key=<hidden>"),
    ),
    "operator-in-hyperfine-shell-none": (
        ("hyperfine", "--shell", "none", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "hyperfine --shell none 'tool --api-key=<hidden>'",
        ("hyperfine", "--shell", "none", "tool --api-key=<hidden>"),
    ),
    "operator-in-parallel-quote": (
        ("parallel", "-q", "tool", "--api-key={s};./bench-{p}", ":::", "1"),
        PROGRAMS,
        "parallel -q tool '--api-key=<hidden>' ::: 1",
        ("parallel", "-q", "tool", "--api-key=<hidden>", ":::", "1"),
    ),
    "operator-in-tmux-arguments": (
        ("tmux", "new", "-d", "tool", "--api-key={s};./bench-{p}"),
        PROGRAMS,
        "tmux new -d tool '--api-key=<hidden>'",
        ("tmux", "new", "-d", "tool", "--api-key=<hidden>"),
    ),
    # Such a word is one argument of the program, so a blank in it is part of the value too.
    "blank-in-watch-exec": (
        ("watch", "-x", "tool", "DB_PASSWORD={s} {p}"),
        PROGRAMS,
        "watch -x tool 'DB_PASSWORD=<hidden>'",
        ("watch", "-x", "tool", "DB_PASSWORD=<hidden>"),
    ),
    "blank-in-watch-exec-long": (
        ("watch", "--exec", "tool", "--api-key={s} {p}"),
        PROGRAMS,
        "watch --exec tool '--api-key=<hidden>'",
        ("watch", "--exec", "tool", "--api-key=<hidden>"),
    ),
    "blank-in-parallel-quote": (
        ("parallel", "--quote", "tool", "DB_PASSWORD={s} {p}", ":::", "1"),
        PROGRAMS,
        "parallel --quote tool 'DB_PASSWORD=<hidden>' ::: 1",
        ("parallel", "--quote", "tool", "DB_PASSWORD=<hidden>", ":::", "1"),
    ),
    # In a shell text inside a shell text, a quoted value, one that ends in ``=`` and one with
    # an operator after a backslash are each hidden whole; the operator after them is shown.
    "quoted-variable-value-then-operator-inside-sh-c": (
        ("sh", "-c", "bash -c \"API_KEY='{s}&&{p}';./bench\""),
        PROGRAMS,
        "sh -c 'bash -c \"API_KEY=<hidden>;./bench\"'",
        ("sh", "-c", 'bash -c "API_KEY=<hidden>;./bench"'),
    ),
    "variable-value-ending-in-equals-then-operator-inside-sh-c": (
        ("sh", "-c", 'sh -c "API_KEY={s}{p}=&&./bench"'),
        PROGRAMS,
        "sh -c 'sh -c \"API_KEY=<hidden>&&./bench\"'",
        ("sh", "-c", 'sh -c "API_KEY=<hidden>&&./bench"'),
    ),
    "escaped-operator-in-variable-value-inside-sh-c": (
        ("sh", "-c", 'sh -c "API_KEY={s}\\;{p};./bench"'),
        PROGRAMS,
        "sh -c 'sh -c \"API_KEY=<hidden>;./bench\"'",
        ("sh", "-c", 'sh -c "API_KEY=<hidden>;./bench"'),
    ),
    # ``hyperfine -N`` after its text inside a shell text runs the text with no shell, so an
    # operator in it is part of the value.
    "operator-in-hyperfine-text-before-dash-n-inside-sh-c": (
        ("sh", "-c", "hyperfine 'tool --api-key={s};./bench-{p}' -N && ls"),
        PROGRAMS,
        "sh -c 'hyperfine '\"'\"'tool --api-key=<hidden>'\"'\"' -N && ls'",
        ("sh", "-c", "hyperfine 'tool --api-key=<hidden>' -N && ls"),
    ),
    # A text inside a shell text that a program runs with no shell is no shell text: an
    # operator in it is part of the value.
    "variable-then-operator-in-env-split-inside-sh-c": (
        ("sh", "-c", 'env -S "API_KEY={s}&&./bench-{p}"'),
        PROGRAMS,
        "sh -c 'env -S \"API_KEY=<hidden>\"'",
        ("sh", "-c", 'env -S "API_KEY=<hidden>"'),
    ),
    "variable-then-operator-in-hyperfine-dash-n-inside-sh-c": (
        ("sh", "-c", 'hyperfine -N "API_KEY={s}&&./bench-{p}"'),
        PROGRAMS,
        "sh -c 'hyperfine -N \"API_KEY=<hidden>\"'",
        ("sh", "-c", 'hyperfine -N "API_KEY=<hidden>"'),
    ),
    "value-after-equals-and-a-blank-in-watch-exec": (
        ("watch", "-x", "tool", "--x 1 API_KEY= {s} --y 2"),
        PROGRAMS,
        "watch -x tool '--x 1 API_KEY=<hidden> <hidden> --y 2'",
        ("watch", "-x", "tool", "--x 1 API_KEY=<hidden> <hidden> --y 2"),
    ),
    "operator-in-the-first-of-several-tmux-arguments": (
        ("tmux", "new", "-d", "API_KEY={s}&&./bench-{p}", "--made-up"),
        PROGRAMS,
        "tmux new -d 'API_KEY=<hidden>' --made-up",
        ("tmux", "new", "-d", "API_KEY=<hidden>", "--made-up"),
    ),
    "blank-in-tmux-arguments": (
        ("tmux", "new", "-d", "tool", "DB_PASSWORD={s} {p}"),
        PROGRAMS,
        "tmux new -d tool 'DB_PASSWORD=<hidden>'",
        ("tmux", "new", "-d", "tool", "DB_PASSWORD=<hidden>"),
    ),
    "blank-in-watch-exec-inside-sh-c": (
        ("sh", "-c", "watch -x tool 'DB_PASSWORD={s} {p}'"),
        PROGRAMS,
        "sh -c 'watch -x tool '\"'\"'DB_PASSWORD=<hidden>'\"'\"''",
        ("sh", "-c", "watch -x tool 'DB_PASSWORD=<hidden>'"),
    ),
    # The option that turns the shell off counts inside a group of short options, and after
    # the command where the runner reads options there too, as ``hyperfine`` does.
    "operator-in-watch-exec-in-a-group": (
        ("watch", "-tx", "tool", "--api-key={s};./bench-{p}"),
        PROGRAMS,
        "watch -tx tool '--api-key=<hidden>'",
        ("watch", "-tx", "tool", "--api-key=<hidden>"),
    ),
    "operator-in-parallel-quote-in-a-group": (
        ("parallel", "-kq", "tool", "--api-key={s};./bench-{p}", ":::", "1"),
        PROGRAMS,
        "parallel -kq tool '--api-key=<hidden>' ::: 1",
        ("parallel", "-kq", "tool", "--api-key=<hidden>", ":::", "1"),
    ),
    "operator-in-hyperfine-without-a-shell-in-a-group": (
        ("hyperfine", "-iN", "tool --api-key={s}&&./bench-{p}"),
        PROGRAMS,
        "hyperfine -iN 'tool --api-key=<hidden>'",
        ("hyperfine", "-iN", "tool --api-key=<hidden>"),
    ),
    "operator-in-hyperfine-shell-none-in-a-group": (
        ("hyperfine", "-iS", "none", "tool --api-key={s}|./bench-{p}"),
        PROGRAMS,
        "hyperfine -iS none 'tool --api-key=<hidden>'",
        ("hyperfine", "-iS", "none", "tool --api-key=<hidden>"),
    ),
    "operator-in-hyperfine-without-a-shell-after-the-command": (
        ("hyperfine", "tool --api-key={s}&&./bench-{p}", "-N"),
        PROGRAMS,
        "hyperfine 'tool --api-key=<hidden>' -N",
        ("hyperfine", "tool --api-key=<hidden>", "-N"),
    ),
    "operator-in-hyperfine-shell-none-after-the-command": (
        ("hyperfine", "tool --api-key={s};./bench-{p}", "--shell", "none"),
        PROGRAMS,
        "hyperfine 'tool --api-key=<hidden>' --shell none",
        ("hyperfine", "tool --api-key=<hidden>", "--shell", "none"),
    ),
    "operator-in-hyperfine-without-a-shell-after-the-command-inside-sh-c": (
        ("sh", "-c", "hyperfine 'tool --api-key={s}&&./bench-{p}' -N"),
        PROGRAMS,
        "sh -c 'hyperfine '\"'\"'tool --api-key=<hidden>'\"'\"' -N'",
        ("sh", "-c", "hyperfine 'tool --api-key=<hidden>' -N"),
    ),
    "operator-in-ssh-option-value": (
        ("ssh", "-o", "SetEnv=DB_PASSWORD={s};./bench-{p}", "made-up-host", "./bench"),
        PROGRAMS,
        "ssh -o 'SetEnv=DB_PASSWORD=<hidden>' made-up-host ./bench",
        ("ssh", "-o", "SetEnv=DB_PASSWORD=<hidden>", "made-up-host", "./bench"),
    ),
}

# Values given after a credential name on its line in a program's text, still hidden.
PROGRAM_VALUES: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {
    "name-colon-value": (
        ("python3", "-c", "d = {'token': '{s}'}; run()"),
        "python3 -c 'd = {'\"'\"'token'\"'\"': '\"'\"'<hidden>'\"'\"'}; run()'",
        ("python3", "-c", "d = {'token': '<hidden>'}; run()"),
    ),
    "name-type-value": (
        ("python3", "-c", "token: str = '{s}'; run()"),
        "python3 -c 'token: <hidden>'",
        ("python3", "-c", "token: <hidden>"),
    ),
    "name-equals-value": (
        ("python3", "-c", "token = '{s}'; run()"),
        "python3 -c 'token = '\"'\"'<hidden>'\"'\"'; run()'",
        ("python3", "-c", "token = '<hidden>'; run()"),
    ),
    "argument-name-colon-value": (
        ("python3", "-c", "def f(token: str = '{s}'): run()"),
        "python3 -c 'def f(token: <hidden> = '\"'\"'<hidden>'\"'\"'): run()'",
        ("python3", "-c", "def f(token: <hidden> = '<hidden>'): run()"),
    ),
    "quoted-name-value-on-the-next-line": (
        ("python3", "-c", 'd = {"api_key":\n    "{s}"}'),
        'python3 -c \'d = {"api_key":\n    "<hidden>"}\'',
        ("python3", "-c", 'd = {"api_key":\n    "<hidden>"}'),
    ),
    # A program is no shell: a value after ``=`` and a blank is still the name's value.
    "glued-equals-then-blank": (
        ("python3", "-c", "api_key= '{s}'; run()"),
        "python3 -c 'api_key=<hidden> '\"'\"'<hidden>'\"'\"'; run()'",
        ("python3", "-c", "api_key=<hidden> '<hidden>'; run()"),
    ),
    "glued-equals-then-blank-inside-sh-c": (
        ("sh", "-c", "python3 -c \"api_key= '{s}'; run()\""),
        "sh -c 'python3 -c \"api_key=<hidden> '\"'\"'<hidden>'\"'\"'; run()\"'",
        ("sh", "-c", "python3 -c \"api_key=<hidden> '<hidden>'; run()\""),
    ),
    # In a shell text, ``=`` with a blank before it is no shell word's ``=``: the value stays.
    "spaced-equals-in-a-shell-text": (
        ("sh", "-c", "echo api_key = {s} >> made-up.ini && ./bench"),
        "sh -c 'echo api_key = <hidden> >> made-up.ini && ./bench'",
        ("sh", "-c", "echo api_key = <hidden> >> made-up.ini && ./bench"),
    ),
    # The lines of a here-document of a shell text are a program's text or a file's.
    "here-document-of-a-shell-text": (
        ("sh", "-c", "python3 - <<EOF\napi_key= '{s}'\nEOF\n./bench"),
        "sh -c 'python3 - <<EOF\napi_key=<hidden> '\"'\"'<hidden>'\"'\"'\nEOF\n./bench'",
        ("sh", "-c", "python3 - <<EOF\napi_key=<hidden> '<hidden>'\nEOF\n./bench"),
    ),
    "quoted-here-document-of-a-shell-text": (
        ("sh", "-c", "cat > made-up.ini <<-'END'\n\tpassword= {s}\n\tEND\n./bench"),
        "sh -c 'cat > made-up.ini <<-'\"'\"'END'\"'\"'"
        "\n\tpassword=<hidden> <hidden>\n\tEND\n./bench'",
        ("sh", "-c", "cat > made-up.ini <<-'END'\n\tpassword=<hidden> <hidden>\n\tEND\n./bench"),
    ),
}


def typed(form: tuple[str, ...], secret: str, value: str) -> list[str]:
    """Return a form's argument list with the secret and the telling value put in."""
    return [arg.replace("{s}", secret).replace("{p}", value) for arg in form]


def secrets(name: str) -> tuple[str, str]:
    """Return the two secrets of a form: random-looking ones where a name does not hide them."""
    if name in ("shape-hidden-word", "credential-name-with-a-random-value"):
        return RANDOM, RANDOM_OTHER
    if name.startswith("random-name-ending-in-"):
        return RANDOM_NAME, RANDOM_NAME_OTHER
    return SECRET, OTHER


@pytest.mark.parametrize("name", sorted(READ_BY_WORDS))
def test_each_form_is_shown_and_hashed_with_only_its_secret_hidden(name: str) -> None:
    form, (first, _second), shown, hashed = READ_BY_WORDS[name]
    secret, _other = secrets(name)
    argv = typed(form, secret, first)

    assert model.public_command(argv) == shown
    assert model.hashed_argv(argv) == list(hashed)
    assert argv_sha256(argv) == sha256_hex(canonical_json(list(hashed)))


@pytest.mark.parametrize("name", sorted(READ_BY_WORDS))
def test_two_secrets_give_one_shown_command_and_one_hash(name: str) -> None:
    form, (first, _second), _shown, _hashed = READ_BY_WORDS[name]
    secret, other = secrets(name)
    one, two = typed(form, secret, first), typed(form, other, first)

    assert model.public_command(one) == model.public_command(two)
    assert argv_sha256(one) == argv_sha256(two)


@pytest.mark.parametrize("name", sorted(READ_BY_WORDS))
def test_two_programs_give_two_shown_commands_and_two_hashes(name: str) -> None:
    form, (first, second), _shown, _hashed = READ_BY_WORDS[name]
    secret, _other = secrets(name)
    one, two = typed(form, secret, first), typed(form, secret, second)

    assert model.public_command(one) != model.public_command(two)
    assert argv_sha256(one) != argv_sha256(two)


@pytest.mark.parametrize("name", sorted(WHOLE_VALUES))
def test_a_credential_name_hides_its_whole_value(name: str) -> None:
    form, (first, second), shown, hashed = WHOLE_VALUES[name]
    secret, other = secrets(name)
    for value in (first, second):
        for word in (secret, other):
            argv = typed(form, word, value)
            assert model.public_command(argv) == shown
            assert model.hashed_argv(argv) == list(hashed)


@pytest.mark.parametrize("name", sorted(PROGRAM_VALUES))
def test_a_value_on_the_line_of_a_credential_name_stays_hidden(name: str) -> None:
    form, shown, hashed = PROGRAM_VALUES[name]
    for word in (SECRET, OTHER):
        argv = [arg.replace("{s}", word) for arg in form]
        assert model.public_command(argv) == shown
        assert model.hashed_argv(argv) == list(hashed)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (
            "ssh made-up-host 'API_KEY=kiwi7 ./bench-old'",
            "ssh made-up-host API_KEY=<hidden> ./bench-old",
        ),
        (
            "hyperfine --warmup 3 'API_KEY=kiwi7 ./bench-old'",
            "hyperfine --warmup 3 API_KEY=<hidden> ./bench-old",
        ),
        ("sh -ce 'API_KEY=kiwi7 ./bench-old'", "sh -ce API_KEY=<hidden> ./bench-old"),
        (
            "env 'MADE_UP_FLAGS=--api-key=kiwi7 --threads 8' mytool",
            "env MADE_UP_FLAGS=--api-key=<hidden> --threads 8 mytool",
        ),
        ("env 'DB_PASSWORD=kiwi7 old' mytool", "env DB_PASSWORD=<hidden> mytool"),
        (
            "sh -c 'env MADE_UP_FLAGS=\"--api-key kiwi7 --threads 8\" mytool'",
            'sh -c env MADE_UP_FLAGS="--api-key <hidden> --threads 8" mytool',
        ),
        (
            "sh -c \"env 'MADE_UP_FLAGS=--api-key kiwi7 --threads 8' mytool\"",
            "sh -c env 'MADE_UP_FLAGS=--api-key <hidden> --threads 8' mytool",
        ),
        (
            "sh -c 'API_KEY= ./bench-old --token kiwi7'",
            "sh -c API_KEY=<hidden> ./bench-old --token <hidden>",
        ),
        (
            "ssh made-up-host 'tool --api-key=kiwi7&&./bench-old'",
            "ssh made-up-host tool --api-key=<hidden>&&./bench-old",
        ),
        ("env -S 'tool --api-key=kiwi7&&./bench-old'", "env -S tool --api-key=<hidden>"),
        (
            "hyperfine 'tool --api-key=kiwi7&&./bench-old' -N",
            "hyperfine tool --api-key=<hidden> -N",
        ),
    ],
)
def test_a_command_written_as_one_text_reads_the_same_forms(text: str, shown: str) -> None:
    assert model.public_words(text) == shown


# ---------------------------------------------------------------------------
# The shared workload after each command side's own words
# ---------------------------------------------------------------------------

# Each client: the words of the side's spec before ``{workload}`` after the program, the
# workload (``{s}`` the password), and the workload as shown and as hashed.
CLIENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]] = {
    "redis-benchmark": (
        (),
        ("-a", "{s}", "-n", "1000"),
        "-a '<hidden>' -n 1000",
        ("-a", HIDDEN, "-n", "1000"),
    ),
    "redis-cli": ((), ("-a", "{s}", "PING"), "-a '<hidden>' PING", ("-a", HIDDEN, "PING")),
    "mysql": ((), ("-p{s}", "shop"), "'-p<hidden>' shop", (f"-p{HIDDEN}", "shop")),
    "mysqlslap": (
        (),
        ("-p{s}", "--concurrency=4"),
        "'-p<hidden>' --concurrency=4",
        (f"-p{HIDDEN}", "--concurrency=4"),
    ),
    "sshpass": ((), ("-p", "{s}", "true"), "-p '<hidden>' true", ("-p", HIDDEN, "true")),
    "ab": (
        (),
        ("-A", "bench:{s}", "http://localhost:8000/"),
        "-A 'bench:<hidden>' http://localhost:8000/",
        ("-A", f"bench:{HIDDEN}", "http://localhost:8000/"),
    ),
    "mytool": (
        ("--api-key",),
        ("{s}", "-n", "1000"),
        "'<hidden>' -n 1000",
        (HIDDEN, "-n", "1000"),
    ),
}


def side_argv(client: str, build: str) -> list[str]:
    """Return the command of a side that names the client only in its spec."""
    extra, _workload, _shown, _hashed = CLIENTS[client]
    return [f"./build-{build}/{client}", *extra, model.WORKLOAD_PLACEHOLDER]


def side_specs(client: str) -> tuple[str, str]:
    """Return the specs of the two command sides, as ``--side`` takes them."""
    old, new = (" ".join(side_argv(client, build)) for build in ("old", "new"))
    return f"cmd:{old}", f"cmd:{new}"


def workload(client: str, secret: str) -> list[str]:
    """Return the shared workload of a client with the password put in."""
    return [word.replace("{s}", secret) for word in CLIENTS[client][1]]


def config(client: str, secret: str) -> dict[str, Any]:
    """Return a config that holds the two sides and the shared workload."""
    return {
        "workload": {"argv": workload(client, secret)},
        "sides": {build: {"cmd": side_argv(client, build)} for build in ("old", "new")},
    }


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_the_shown_command_reads_the_workload_after_a_side_spec(client: str) -> None:
    old, new = side_specs(client)
    _extra, _workload, shown, _hashed = CLIENTS[client]
    head = ["pairbench", "run", "--side", f"old={old}", "--side", f"new={new}", "--"]

    for secret in (SECRET, OTHER):
        command = model.public_command([*head, *workload(client, secret)])
        assert (
            command
            == f"pairbench run --side 'old=cmd:<hidden>' --side 'new=cmd:<hidden>' -- {shown}"
        )


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_the_shown_command_reads_the_workload_after_a_side_of_the_config(client: str) -> None:
    _extra, _workload, shown, _hashed = CLIENTS[client]
    head = ["pairbench", "run", "--config", "pairbench.toml", "--"]

    for secret in (SECRET, OTHER):
        argv = [*head, *workload(client, secret)]
        command = model.public_command(argv, config=config(client, secret))
        assert command == f"pairbench run --config pairbench.toml -- {shown}"


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_the_config_hash_reads_the_workload_after_each_side(client: str) -> None:
    _extra, _workload, _shown, hashed = CLIENTS[client]
    one, two = config(client, SECRET), config(client, OTHER)

    assert model.config_inputs(one)["workload"]["argv"] == list(hashed)
    assert model.config_sha256(one) == model.config_sha256(two)


def test_a_word_hidden_by_the_reading_after_any_side_is_hidden() -> None:
    # One side runs redis-benchmark, whose -a takes a password, the other a program that
    # knows no -a: the password is hidden all the same, and in the config hash too.
    argv = [
        "pairbench",
        "run",
        "--side",
        "old=cmd:./build-old/redis-benchmark {workload}",
        "--side",
        "new=cmd:./made-up-bench {workload}",
        "--",
        "-a",
        SECRET,
        "-n",
        "1000",
    ]
    shown = model.public_command(argv)
    assert shown == (
        "pairbench run --side 'old=cmd:<hidden>' --side 'new=cmd:<hidden>' -- -a '<hidden>' -n 1000"
    )
    hashed = model.config_inputs(
        {
            "workload": {"argv": ["-a", SECRET, "-n", "1000"]},
            "sides": {
                "old": {"cmd": ["./build-old/redis-benchmark", "{workload}"]},
                "new": {"cmd": ["./made-up-bench", "{workload}"]},
            },
        }
    )
    assert hashed["workload"]["argv"] == ["-a", HIDDEN, "-n", "1000"]


def test_a_workload_with_no_secret_is_shown_and_hashed_as_it_is() -> None:
    argv = [
        "pairbench",
        "run",
        "--side",
        "old=cmd:./build-old/redis-benchmark {workload}",
        "--side",
        "new=cmd:./build-new/redis-benchmark {workload}",
        "--",
        "-n",
        "1000",
        "-t",
        "get",
    ]
    assert model.public_command(argv) == (
        "pairbench run --side 'old=cmd:<hidden>' --side 'new=cmd:<hidden>' -- -n 1000 -t get"
    )
    data = {
        "workload": {"argv": ["-n", "1000", "-t", "get"]},
        "sides": {
            "old": {"cmd": ["./build-old/redis-benchmark", "{workload}"]},
            "new": {"cmd": ["./build-new/redis-benchmark", "{workload}"]},
        },
    }
    assert model.config_inputs(data)["workload"]["argv"] == ["-n", "1000", "-t", "get"]


@pytest.mark.parametrize("name", sorted(READ_BY_WORDS))
def test_a_workload_is_read_from_its_first_word_as_a_command_is(name: str) -> None:
    # The workload after ``--`` starts a command, so a wrapper there is read as it is
    # when it stands alone, and its text keeps the program after the credential.
    form, (first, _second), shown, hashed = READ_BY_WORDS[name]
    secret, _other = secrets(name)
    argv = typed(form, secret, first)

    assert model.public_command(["pairbench", "run", "--", *argv]) == f"pairbench run -- {shown}"
    assert model.config_inputs({"workload": {"argv": argv}})["workload"]["argv"] == list(hashed)


def test_a_runner_that_reads_its_options_first_turns_its_shell_off_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A runner that reads no option after its texts is told before them that it runs no
    # shell: the value ``none`` of its option that names the shell, read in order.
    runner = dataclasses.replace(model.COMMAND_TEXT_RUNNERS["hyperfine"], options_after=False)
    monkeypatch.setattr(
        model, "COMMAND_TEXT_RUNNERS", {**model.COMMAND_TEXT_RUNNERS, "hyperfine": runner}
    )
    for spelling in (("--shell", "none"), ("-S", "none"), ("-iS", "none")):
        argv = ["hyperfine", *spelling, "tool --api-key=kiwi7&&./bench-old"]
        shown = f"hyperfine {' '.join(spelling)} 'tool --api-key=<hidden>'"

        assert model.public_command(argv) == shown
        assert model.hashed_argv(argv) == [*argv[:-1], "tool --api-key=<hidden>"]
    argv = ["hyperfine", "--shell", "bash", "tool --api-key=kiwi7&&./bench-old"]

    assert model.public_command(argv) == (
        "hyperfine --shell bash 'tool --api-key=<hidden>&&./bench-old'"
    )
