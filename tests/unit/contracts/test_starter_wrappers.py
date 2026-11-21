# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A runner after a program that runs the command after its options is read as a runner.

``taskset``, ``numactl``, ``chrt``, ``stdbuf``, ``ionice``, ``nice``, ``nohup``, ``timeout``
and ``sudo`` each run the command that follows their options and, for ``taskset``, ``chrt``
and ``timeout``, the mask, the priority or the duration they take first. That command starts
a command as the one after ``env`` does, so ``ssh``, ``hyperfine``, ``watch`` and ``parallel``
there keep the program of their text shown and hashed, and a credential in that text stays
hidden. Two sides that run two programs behind the same wrapper are two sides; two sides that
differ only in the credential are one.
"""

from __future__ import annotations

import json

import pytest

from pairbench.model import hashed_argv, public_command
from pairbench.sides.identity import argv_sha256

# Two made-up secrets, and two made-up programs.
SECRETS = ("made-up-secret-1", "made-up-secret-2")
PROGRAMS = ("old", "new")

# Each form: the argument list with ``{v}`` where a secret stands and ``{p}`` where the
# program's name ends, and the command shown with the first secret and the first program.
WRAPPER_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "taskset with a list of CPUs": (
        ("taskset", "-c", "0-3", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "taskset -c 0-3 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "taskset with the long option of a list of CPUs": (
        ("taskset", "--cpu-list", "0-3", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "taskset --cpu-list 0-3 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "taskset with a bit mask": (
        ("taskset", "0x3", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "taskset 0x3 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "taskset with a flag and a list of CPUs in two ranges": (
        ("taskset", "-a", "-c", "0-3,8", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "taskset -a -c 0-3,8 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with a node": (
        ("numactl", "-N", "0", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl -N 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with a node glued to its long option": (
        ("numactl", "--cpunodebind=0", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl --cpunodebind=0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with the long option of a memory node": (
        ("numactl", "--membind", "0", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl --membind 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with CPUs and a memory node": (
        (
            "numactl",
            "-C",
            "0-3",
            "-m",
            "0",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "numactl -C 0-3 -m 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with interleaved nodes": (
        ("numactl", "-i", "all", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl -i all ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with a flag": (
        ("numactl", "-l", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl -l ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "numactl with the end of its options": (
        ("numactl", "--", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "numactl -- ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "chrt with a policy and a priority": (
        ("chrt", "-f", "10", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "chrt -f 10 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "chrt with a priority alone": (
        ("chrt", "10", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "chrt 10 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "chrt with the long option of a policy": (
        ("chrt", "--rr", "5", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "chrt --rr 5 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "chrt with a policy and no priority": (
        ("chrt", "-o", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "chrt -o ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "chrt with the times of a deadline": (
        (
            "chrt",
            "-T",
            "1000",
            "-P",
            "2000",
            "-D",
            "2000",
            "-d",
            "0",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "chrt -T 1000 -P 2000 -D 2000 -d 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "stdbuf with a mode glued to its option": (
        ("stdbuf", "-oL", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "stdbuf -oL ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "stdbuf with a mode after its option": (
        ("stdbuf", "-o", "L", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "stdbuf -o L ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "stdbuf with a mode glued to its long option": (
        ("stdbuf", "--output=L", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "stdbuf --output=L ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "stdbuf with two modes": (
        ("stdbuf", "-i", "0", "-e", "0", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "stdbuf -i 0 -e 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "ionice with a class and its data": (
        ("ionice", "-c", "2", "-n", "7", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "ionice -c 2 -n 7 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "ionice with a class glued to its option": (
        ("ionice", "-c2", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "ionice -c2 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "ionice with the long option of a class": (
        ("ionice", "--class", "idle", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "ionice --class idle ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "ionice with a flag and a class": (
        ("ionice", "-t", "-c", "3", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "ionice -t -c 3 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice": (
        ("nice", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice with an adjustment": (
        ("nice", "-n", "5", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice -n 5 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice with an adjustment glued to its option": (
        ("nice", "-n5", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice -n5 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice with the long option of an adjustment": (
        ("nice", "--adjustment", "5", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice --adjustment 5 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice with an adjustment glued to its long option": (
        ("nice", "--adjustment=5", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice --adjustment=5 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice with an adjustment as an option of digits": (
        ("nice", "-10", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nice -10 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nohup": (
        ("nohup", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "nohup ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with a duration": (
        ("timeout", "30", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "timeout 30 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with a duration and its unit": (
        ("timeout", "1.5m", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "timeout 1.5m ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with a signal": (
        ("timeout", "-s", "KILL", "30", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "timeout -s KILL 30 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with a time to kill after": (
        ("timeout", "-k", "5", "30", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "timeout -k 5 30 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with values glued to its long options": (
        (
            "timeout",
            "--signal=TERM",
            "--kill-after=5s",
            "30",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "timeout --signal=TERM --kill-after=5s 30 ssh made-up-host "
        "'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "timeout with flags": (
        (
            "timeout",
            "--foreground",
            "--preserve-status",
            "-v",
            "30",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "timeout --foreground --preserve-status -v 30 ssh made-up-host "
        "'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo": (
        ("sudo", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with a user": (
        ("sudo", "-u", "app", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo -u app ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with a user glued to its long option": (
        ("sudo", "--user=app", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo --user=app ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with a flag and a group": (
        ("sudo", "-E", "-g", "bench", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo -E -g bench ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with the long options of a folder and a prompt": (
        (
            "sudo",
            "--chdir",
            "work",
            "--prompt",
            "pw",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "sudo --chdir work --prompt pw ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with an assignment": (
        ("sudo", "A=1", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo A=1 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo with the end of its options": (
        ("sudo", "-u", "app", "--", "ssh", "made-up-host", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo -u app -- ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "hyperfine after nice": (
        ("nice", "-n", "5", "hyperfine", "API_KEY={v} ./made-up-bench-{p}"),
        "nice -n 5 hyperfine 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "hyperfine after timeout": (
        ("timeout", "60", "hyperfine", "API_KEY={v} ./made-up-bench-{p}"),
        "timeout 60 hyperfine 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "watch after sudo": (
        ("sudo", "-u", "app", "watch", "-n", "1", "API_KEY={v} ./made-up-bench-{p}"),
        "sudo -u app watch -n 1 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "a wrapper after nohup": (
        (
            "nohup",
            "taskset",
            "-c",
            "0",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "nohup taskset -c 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "sudo after timeout": (
        (
            "timeout",
            "30",
            "sudo",
            "-u",
            "app",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "timeout 30 sudo -u app ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "nice in a shell text": (
        ("sh", "-c", "nice -n 5 ssh made-up-host 'API_KEY={v} ./made-up-{p}'"),
        """sh -c 'nice -n 5 ssh made-up-host '"'"'API_KEY=<hidden> ./made-up-old'"'"''""",
    ),
    "hyperfine after taskset": (
        ("taskset", "-c", "0-3", "hyperfine", "API_KEY={v} ./made-up-bench-{p}"),
        "taskset -c 0-3 hyperfine 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "watch after stdbuf": (
        ("stdbuf", "-oL", "watch", "-n", "1", "API_KEY={v} ./made-up-bench-{p}"),
        "stdbuf -oL watch -n 1 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "parallel after numactl": (
        ("numactl", "-N", "0", "parallel", "API_KEY={v} ./made-up-bench-{p}", ":::", "1"),
        "numactl -N 0 parallel 'API_KEY=<hidden> ./made-up-bench-old' ::: 1",
    ),
    "a wrapper after a wrapper": (
        (
            "taskset",
            "-c",
            "0-3",
            "numactl",
            "-N",
            "0",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "taskset -c 0-3 numactl -N 0 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "a wrapper after env": (
        (
            "env",
            "A=1",
            "taskset",
            "-c",
            "0-3",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "env A=1 taskset -c 0-3 ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "a wrapper after sshpass": (
        (
            "stdbuf",
            "-oL",
            "sshpass",
            "-p",
            "{v}",
            "ssh",
            "made-up-host",
            "API_KEY={v} ./made-up-bench-{p}",
        ),
        "stdbuf -oL sshpass -p '<hidden>' ssh made-up-host 'API_KEY=<hidden> ./made-up-bench-old'",
    ),
    "a wrapper in a shell text": (
        ("sh", "-c", "taskset -c 0 ssh made-up-host 'API_KEY={v} ./made-up-{p}'"),
        """sh -c 'taskset -c 0 ssh made-up-host '"'"'API_KEY=<hidden> ./made-up-old'"'"''""",
    ),
    "a wrapper in the second command of a shell text": (
        ("sh", "-c", "true && numactl -N 0 ssh made-up-host 'API_KEY={v} ./made-up-{p}'"),
        """sh -c 'true && numactl -N 0 ssh made-up-host '"'"'"""
        """API_KEY=<hidden> ./made-up-old'"'"''""",
    ),
    "a wrapper in the remote command of ssh": (
        ("ssh", "made-up-host", "taskset -c 0 ssh made-up-host-2 'API_KEY={v} ./made-up-{p}'"),
        """ssh made-up-host 'taskset -c 0 ssh made-up-host-2 '"'"'"""
        """API_KEY=<hidden> ./made-up-old'"'"''""",
    ),
}

# A client's password behind a wrapper: hidden as it is without one.
CLIENT_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "redis-cli after taskset": (
        ("taskset", "-c", "0", "redis-cli", "-a", "{v}", "ping"),
        "taskset -c 0 redis-cli -a '<hidden>' ping",
    ),
    "redis-cli after chrt with no priority": (
        ("chrt", "-o", "redis-cli", "-a", "{v}", "ping"),
        "chrt -o redis-cli -a '<hidden>' ping",
    ),
    "redis-cli after sudo": (
        ("sudo", "-u", "app", "redis-cli", "-a", "{v}", "ping"),
        "sudo -u app redis-cli -a '<hidden>' ping",
    ),
    "redis-cli after timeout": (
        ("timeout", "5", "redis-cli", "-a", "{v}", "ping"),
        "timeout 5 redis-cli -a '<hidden>' ping",
    ),
    "sshpass after ionice": (
        ("ionice", "-c", "3", "sshpass", "-p", "{v}", "ssh", "made-up-host", "true"),
        "ionice -c 3 sshpass -p '<hidden>' ssh made-up-host true",
    ),
}


def _filled(form: tuple[str, ...], secret: str, program: str = PROGRAMS[0]) -> tuple[str, ...]:
    return tuple(word.replace("{v}", secret).replace("{p}", program) for word in form)


@pytest.mark.parametrize(
    ("form", "shown"),
    list(WRAPPER_FORMS.values()) + list(CLIENT_FORMS.values()),
    ids=list(WRAPPER_FORMS) + [f"client: {name}" for name in CLIENT_FORMS],
)
def test_the_command_behind_a_wrapper_is_shown_with_its_secret_hidden(
    form: tuple[str, ...], shown: str
) -> None:
    argv = _filled(form, SECRETS[0])

    assert public_command(argv) == shown
    assert SECRETS[0] not in json.dumps(hashed_argv(argv))


@pytest.mark.parametrize(
    "form",
    list(WRAPPER_FORMS.values()) + list(CLIENT_FORMS.values()),
    ids=list(WRAPPER_FORMS) + [f"client: {name}" for name in CLIENT_FORMS],
)
def test_two_secrets_behind_a_wrapper_give_one_hash(form: tuple[tuple[str, ...], str]) -> None:
    argv, _ = form

    assert argv_sha256(_filled(argv, SECRETS[0])) == argv_sha256(_filled(argv, SECRETS[1]))


@pytest.mark.parametrize(
    "form", [argv for argv, _ in WRAPPER_FORMS.values()], ids=list(WRAPPER_FORMS)
)
def test_two_programs_behind_a_wrapper_give_two_hashes(form: tuple[str, ...]) -> None:
    old = _filled(form, SECRETS[0], PROGRAMS[0])
    new = _filled(form, SECRETS[0], PROGRAMS[1])

    assert argv_sha256(old) != argv_sha256(new)
    assert public_command(old) != public_command(new)
