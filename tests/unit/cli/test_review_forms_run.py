# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Through a real ``run``: each secret form a nested text, a rule or a case id holds stays hidden.

Two command sides run the same workload through ``env``; the clients the workload names are
made-up programs first on ``PATH`` that do nothing. The workload holds a password in one of
these forms: a nested shell text in a bracket with a credential word glued with ``=`` after
it, a rule of ``ACL SETUSER`` typed with a backslash, also in the words that ``ssh``,
``watch`` or ``parallel`` hands to a shell, after a program in front of ``ssh``, in a shell
text one word of ``ssh`` holds and after ``hyperfine -N``, an AUTH command of
``memtier_benchmark`` inside an ``eval`` whose text uses escaped single quotes, a client's
command in an ``eval`` glued to the bracket of a subshell, a client's command glued to an
option of ``hyperfine`` that runs it around the timed commands, also after an ``=`` glued to a
short option, after ``-S`` in one group and in the words of ``ssh`` or ``watch`` whose command
``hyperfine`` starts, also behind ``taskset``, a quoted word before the
bracket that closes a subshell or with a redirection glued after it, also one that names a
descriptor by its number, an AUTH command of
``memtier_benchmark`` in an ``eval`` after ``{``, ``then`` or a line continuation, a client's
password option after an operator glued to a line continuation, a credential assigned in an
``eval`` in double quotes in a command substitution or in backquotes, an AUTH command of
``memtier_benchmark`` in an ``eval`` in backquotes in double quotes, a value of ``python3``
code in an ``eval`` of words with escaped quotes, and a
relative path that climbs out of the run folder into a user's home folder, as an argument
of its own, given to a name, and in a shell text after ``./`` or after a folder, or a value a
program's text gives a credential's name as a string with a prefix, a raw string of C++ with
a prefix before its ``R``, a quote-like word of Perl, a pattern, a here-document, or a string,
a variable or a here-document joined to another by a blank or ``.``, with no blanks too and
with a backslash before the variable's ``$`` in a shell text, also in a here-document a shell
hands to the program, a variable joined across lines and an element of an array joined with
``.``. A workload that prints its own values names its
cases with a credential's value, a credential option's value, a password before a host, a long
random-looking value, the token after a scheme word glued to a credential option and a
credential's value glued to its name with ``:``, also after another name, a ``-`` join or a
quote, and a password before a host with text after the host or around it. None of these
values is in ``results.json``,
``results.md`` or ``report.html``. Every value is made up.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

# A made-up password, neither a credential word nor random-looking, and a made-up user name.
VALUE = "kiwi7mango42"
USER = "made-up-user"
# A made-up value of 32 letters and digits that reads as random.
RANDOM = "Qz7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS"
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "4",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
    "--allow-identical",
    "--allow-underpowered",
)
SIDES = ("--side", "old=cmd:env {workload}", "--side", "new=cmd:env {workload}")
SHARED_FILES = ("results.json", "results.md", "report.html")
# The words of ``ACL SETUSER`` given to ``ssh`` behind ``timeout``, up to its password rule.
TIMEOUT_SSH_RULE = (
    "timeout",
    "5",
    "ssh",
    "made-up-host",
    "redis-cli",
    "ACL",
    "SETUSER",
    "app",
    "on",
)
# The clients and interpreters the workloads name: each does nothing and succeeds.
CLIENTS = (
    "redis-cli",
    "memtier_benchmark",
    "mysql",
    "hyperfine",
    "python3",
    "perl",
    "ruby",
    "node",
    "php",
    "psql",
    "ssh",
    "watch",
    "parallel",
    "cling",
)
# Each case id the case workload prints, ``{v}`` the password and ``{r}`` the random value.
CASES = (
    "test_db[PGPASSWORD={v}]",
    "test_db[--password={v}]",
    "bench[bob:{v}@db.example:5432]",
    "bench/PGPASSWORD={v}/latency",
    "test_api[{r}]",
    "bench[token={v}]",
    "bench[api_key={v}]",
    "bench[redis-cli -a {v} PING]",
    "bench[mysql -p{v} -e select 1]",
    "bench[tool --token {v}]",
    "bench[curl -H Authorization: Bearer {v} https://db.example/]",
    "bench[tool password: {v}]",
    "bench[python -c \"password = '{v}'\"]",
    "bench[tool --auth=Basic {v}]",
    "test_api[AUTHORIZATION='Bearer {v}']",
    "test_db[token:{v}]",
    "BM_Auth/password:{v}",
    "test_db[db:password:{v}]",
    "test_db[5432-password:{v}]",
    'test_api[{"token":"{v}"}]',
    "test_api['password':'{v}']",
    "test_db[bob:{v}@db.example:5432-ro]",
    'test_db[{"dsn":"bob:{v}@db.example"}]',
)
# A workload that prints one value for each case id it holds; the ids are in the program, so
# only the case ids can show them.
CASE_PROGRAM = """\
import json
for case in json.loads({cases!r}):
    print("::pairbench:: " + json.dumps({{"case": case, "value": 1.5, "unit": "s"}}))
"""

# Each form: the workload, and the values none of the shared files may hold.
FORMS: dict[str, tuple[list[str], tuple[str, ...]]] = {
    "a nested shell text in a bracket with a later credential word": (
        ["sh", "-c", f"(sh -c 'redis-cli -a {VALUE} PING; true --token=x')"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER typed with a backslash": (
        ["sh", "-c", f"redis-cli ACL SETUSER app on \\>{VALUE}"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash in the remote command of ssh": (
        ["ssh", "made-up-host", "redis-cli", "ACL", "SETUSER", "app", "on", f"\\>{VALUE}"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash after the double dash of ssh": (
        ["ssh", "made-up-host", "--", "redis-cli", "ACL", "SETUSER", "app", "on", f"\\>{VALUE}"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash in the command of watch": (
        ["watch", "-n", "1", "redis-cli", "ACL", "SETUSER", "app", "on", f"\\>{VALUE}"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash in the command of parallel": (
        ["parallel", "redis-cli", "ACL", "SETUSER", "app", "on", f"\\>{VALUE}", ":::", "a"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash in quotes that a shell hands to watch": (
        ["sh", "-c", f"true || watch redis-cli ACL SETUSER app on '\\>{VALUE}'"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash after a program in front of ssh": (
        [*TIMEOUT_SSH_RULE, f"\\>{VALUE}"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash in a shell text one word of ssh holds": (
        ["ssh", "made-up-host", "sh", "-c", f"'redis-cli ACL SETUSER app on \\>{VALUE}'"],
        (VALUE,),
    ),
    "a rule of ACL SETUSER with a backslash after hyperfine -N": (
        ["hyperfine", "-N", f"redis-cli ACL SETUSER app on \\>{VALUE}"],
        (VALUE,),
    ),
    "an AUTH command in an eval with escaped single quotes": (
        ["sh", "-c", f"eval 'memtier_benchmark --command '\\''AUTH {VALUE}'\\'''"],
        (VALUE,),
    ),
    "a client's command in an eval glued to a subshell's bracket": (
        ["sh", "-c", f"(eval 'redis-cli -a {VALUE} PING; true --token=x')"],
        (VALUE,),
    ),
    "an AUTH command with escaped quotes in an eval glued to a subshell's bracket": (
        ["sh", "-c", f"(eval memtier_benchmark --command \\'AUTH {VALUE}\\')"],
        (VALUE,),
    ),
    "hyperfine --setup= glued to a client's command": (
        ["hyperfine", f"--setup=redis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine --setup= glued to a client's command in the words of ssh": (
        ["ssh", "made-up-host", "hyperfine", f"--setup='redis-cli -a {VALUE} FLUSHALL'", "./bench"],
        (VALUE,),
    ),
    "hyperfine --prepare= glued to a client's command in the words of watch": (
        ["watch", "hyperfine", f"--prepare='redis-cli -a {VALUE} FLUSHALL'", "./bench"],
        (VALUE,),
    ),
    "hyperfine --setup= glued to a client's command after taskset in the words of ssh": (
        [
            "ssh",
            "made-up-host",
            "taskset",
            "-c",
            "0",
            "hyperfine",
            "--runs",
            "2",
            "--style",
            "none",
            f"--setup='redis-cli -a {VALUE} FLUSHALL'",
            "true",
        ],
        (VALUE,),
    ),
    "hyperfine -s glued to a client's command after -S in one group": (
        ["hyperfine", f"-Ssredis-cli -a {VALUE} PING", "./bench"],
        (VALUE,),
    ),
    "hyperfine --prepare= glued to a client's command": (
        ["hyperfine", f"--prepare=redis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine --cleanup= glued to a client's command": (
        ["hyperfine", f"--cleanup=mysql -p{VALUE} -e made-up-query", "./bench"],
        (VALUE,),
    ),
    "hyperfine -s= glued to a client's command": (
        ["hyperfine", f"-s=redis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine -Nc= glued to a client's command": (
        ["hyperfine", f"-Nc=mysql -p{VALUE} -e made-up-query", "./bench"],
        (VALUE,),
    ),
    "hyperfine --conclude= glued to a client's command": (
        ["hyperfine", f"--conclude=redis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine -s glued to a client's command": (
        ["hyperfine", f"-sredis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine -p glued to a client's command": (
        ["hyperfine", f"-predis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine -c glued to a client's command": (
        ["hyperfine", f"-cmysql -p{VALUE} -e made-up-query", "./bench"],
        (VALUE,),
    ),
    "hyperfine --setup= glued to a client's command after -N": (
        ["hyperfine", "-N", f"--setup=redis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "hyperfine -p glued after -N in one group": (
        ["hyperfine", f"-Npredis-cli -a {VALUE} FLUSHALL", "./bench"],
        (VALUE,),
    ),
    "a quoted word before the bracket that closes a subshell, with a later credential word": (
        ["sh", "-c", f"(true '--api-key {VALUE} --token=x')"],
        (VALUE,),
    ),
    "a program's text of python3 before the bracket that closes a subshell": (
        [
            "sh",
            "-c",
            f'(python3 -c \'import os; os.system("redis-cli -a {VALUE} PING"); x="--token=y"\')',
        ],
        (VALUE,),
    ),
    "a quoted word with a redirection glued after it, with a later credential word": (
        ["sh", "-c", f"true '--api-key {VALUE} --token=x'>/dev/null"],
        (VALUE,),
    ),
    "a quoted word before a bracket that closes a subshell and a numbered redirection": (
        ["sh", "-c", f"(true '--api-key {VALUE} --token=x')2>/dev/null"],
        (VALUE,),
    ),
    "a quoted word with a numbered redirection glued after it": (
        ["sh", "-c", f"true '--api-key {VALUE} --token=x'2>&1"],
        (VALUE,),
    ),
    "an AUTH command of memtier_benchmark in an eval in braces": (
        ["sh", "-c", "{ eval 'memtier_benchmark --command '\\''AUTH " + VALUE + "'\\'''; }"],
        (VALUE,),
    ),
    "an AUTH command of memtier_benchmark in an eval after then": (
        [
            "sh",
            "-c",
            "if true; then eval 'memtier_benchmark --command '\\''AUTH " + VALUE + "'\\'''; fi",
        ],
        (VALUE,),
    ),
    "an AUTH command of memtier_benchmark in an eval after a line continuation": (
        [
            "sh",
            "-c",
            "true && \\\n  eval 'memtier_benchmark --command '\\''AUTH " + VALUE + "'\\'''",
        ],
        (VALUE,),
    ),
    "a client's password option glued to an operator and a line continuation": (
        ["sh", "-c", f"true &&\\\nredis-cli -a {VALUE} PING"],
        (VALUE,),
    ),
    "a credential assigned in an eval in double quotes in a command substitution": (
        ["sh", "-c", f'x="$(eval "PGPASSWORD=\\"made {VALUE}\\" psql -h db.example")"'],
        (VALUE,),
    ),
    "a credential assigned in an eval in backquotes": (
        ["sh", "-c", f'x=`eval "PGPASSWORD=\\\\"made {VALUE}\\\\" psql -h db.example"`'],
        (VALUE,),
    ),
    "an AUTH command of memtier_benchmark in an eval in backquotes in double quotes": (
        ["sh", "-c", f'x="`eval "memtier_benchmark --command \\\\"AUTH {VALUE}\\\\""`"'],
        (VALUE,),
    ),
    "a value of python3 code in an eval of words with escaped quotes": (
        ["sh", "-c", f"eval python3 -c \\\"token = \\'{VALUE}\\'\\\""],
        (VALUE,),
    ),
    "a relative path that climbs into a home folder, as an argument of its own": (
        ["true", f"../../../home/{USER}/data/in.csv"],
        (USER,),
    ),
    "a relative path that climbs into a user's folder, given to a name": (
        ["true", f"--data=../../{USER}/data/in.csv"],
        (USER,),
    ),
    "a relative path that climbs after ./ in a shell text": (
        ["sh", "-c", f"true ./../../../home/{USER}/in.csv"],
        (USER,),
    ),
    "a relative path that climbs after a folder in a shell text": (
        ["sh", "-c", f"true data/../../../home/{USER}/in.csv"],
        (USER,),
    ),
    "a string with a prefix in Python": (
        ["python3", "-c", f"token = f'made {VALUE}'; run_old()"],
        (VALUE,),
    ),
    "a quote-like word of Perl": (
        ["perl", "-e", f"$token = q{{made {VALUE}}}; run_old()"],
        (VALUE,),
    ),
    "a pattern of Perl after =~": (
        ["perl", "-e", f"$token =~ m/made {VALUE}/ and run_old()"],
        (VALUE,),
    ),
    "a pattern of Perl after != in a shell text": (
        ["sh", "-c", f"perl -e 'print if token!=/made {VALUE} /'"],
        (VALUE,),
    ),
    "a here-document of Ruby": (
        ["ruby", "-e", f"token = <<~EOT\n  made {VALUE}\nEOT\nrun_old"],
        (VALUE,),
    ),
    "a here-document of PHP": (
        ["php", "-r", f"$token = <<<EOT\nmade {VALUE}\nEOT;\nrun_old();"],
        (VALUE,),
    ),
    "a string in backquotes of node": (
        ["node", "-e", f"token = `made {VALUE}`; runOld()"],
        (VALUE,),
    ),
    "two strings joined by a blank in Python": (
        ["python3", "-c", f"token = 'made' '{VALUE}'; run_old()"],
        (VALUE,),
    ),
    "two strings joined by . in Perl": (
        ["perl", "-e", f"$token = 'made' . '{VALUE}'; run_old()"],
        (VALUE,),
    ),
    "a quote-like word of Perl in a here-document of a shell text": (
        ["sh", "-c", f"perl <<'END'\n$token = q/made {VALUE} /;\nEND"],
        (VALUE,),
    ),
    "a string with a prefix in a here-document of a shell text": (
        ["sh", "-c", f"python3 <<'END'\ntoken = rb'made {VALUE}'\nEND"],
        (VALUE,),
    ),
    "a quote-like word of Perl with a mark that is no bracket": (
        ["perl", "-e", f"$token = q%made {VALUE}%; run_old()"],
        (VALUE,),
    ),
    "a string with a prefix whose quotes a backslash escapes in a shell text": (
        ["sh", "-c", f'python3 -c "token = f\\"made {VALUE}\\"; run_old()"'],
        (VALUE,),
    ),
    "two strings of Perl joined across a line in a here-document": (
        ["sh", "-c", f"perl <<'END'\nmy $token = 'made' .\n  '{VALUE}';\nEND"],
        (VALUE,),
    ),
    "a variable of Perl between two joined strings": (
        ["perl", "-e", f"$token = 'made' . $x . ' {VALUE}'; run_old()"],
        (VALUE,),
    ),
    "quote-like words of Perl joined to a variable with no blanks": (
        ["perl", "-e", f"$token = q{{made}}.$x.q{{x {VALUE}}}; run_old()"],
        (VALUE,),
    ),
    "a here-document of Perl joined with .": (
        ["perl", "-e", f"$token = 'a' . <<'EOT';\n{VALUE} x\nEOT\nprint 1;"],
        (VALUE,),
    ),
    "a variable a backslash escapes in double quotes of a shell text": (
        ["sh", "-c", f"perl -e \"\\$token = 'made'.\\$x.'x {VALUE}'; run_old()\""],
        (VALUE,),
    ),
    "a raw string of C++ with u8R": (
        ["cling", "-e", f'auto token = u8R"(made {VALUE} x)"; run_old();'],
        (VALUE,),
    ),
    "a variable of Perl joined to two strings across lines": (
        ["perl", "-e", f'my $token = "made" .\n    $x .\n    "x {VALUE}";\nprint 1;'],
        (VALUE,),
    ),
    "an element of an array of Perl joined to two strings": (
        ["perl", "-e", f'$token = "made" . $a[0] . "x {VALUE}"; print 1'],
        (VALUE,),
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder, with made-up clients first on ``PATH``."""
    programs = tmp_path / "bin"
    programs.mkdir()
    for client in CLIENTS:
        program = programs / client
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(0o755)
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.chdir(folder)
    return folder


def shown(folder: Path) -> str:
    return "\n".join((folder / name).read_text(encoding="utf-8") for name in SHARED_FILES)


@pytest.mark.slow
@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_run_shows_no_value_of_a_secret_form(cli: Cli, work: Path, form: str) -> None:
    words, values = FORMS[form]

    result = cli("run", *SIDES, *QUICK, "--out", "out", "--", *words)

    assert result.code == EXIT_OK, result.err
    text = shown(work / "out")
    assert [piece for value in values for piece in pieces(text, value)] == []


@pytest.mark.slow
def test_a_run_shows_no_secret_a_case_id_holds(cli: Cli, work: Path) -> None:
    cases = [case.replace("{v}", VALUE).replace("{r}", RANDOM) for case in CASES]
    program = work / "cases.py"
    program.write_text(CASE_PROGRAM.format(cases=json.dumps(cases)), encoding="utf-8")

    result = cli(
        "run",
        *SIDES,
        *QUICK,
        "--driver",
        "lines",
        "--out",
        "out",
        "--",
        sys.executable,
        program,
    )

    assert result.code == EXIT_OK, result.err
    text = shown(work / "out")
    assert pieces(text, VALUE) == []
    assert pieces(text, RANDOM) == []
