# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A rotated credential keeps one side; a changed word around it makes two.

The credential in a value hidden whole is the value up to its first blank, or
an Authorization scheme word with the token after it. ``plan`` refuses two
sides that differ only there with ``E_SAME_SIDE`` and ``compare`` pools two
captures that differ only there. A word after the credential, the user name or
the database of an address, and a word of a client's command glued to its
``command`` option tell two sides apart: ``plan`` takes them as two sides with
one note, and ``compare`` refuses to pool with ``E_POOL_SIDE_DRIFT``. No
shared output holds the value in either case.
"""

from __future__ import annotations

import json
import shlex
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

PYTHON = shlex.quote(sys.executable)
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
)
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
NOTE_CODE = "sides_differ_in_hidden_value"
NOTE_LINE = (
    f"pairbench: note: {NOTE_CODE}: sides 'a' and 'b' have the same fingerprint and differ "
    "only in a value the results hide; they are compared as two sides, and the results do not "
    "show the value\n"
)
# Two made-up tokens, and two made-up words around them.
OLD, NEW = "kiwi7zq", "plum4zq"
TAIL_A, TAIL_B = "zqalpha", "zqbravo"


@pytest.fixture
def clients(tmp_path: Path) -> Path:
    """A folder with a made-up program named as a client whose ``command`` option is read."""
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "memtier_benchmark"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return folder


def _words(form: str, token: str, tail: str) -> str:
    """A side's command line: the arguments of ``form``, joined by ``|``, each quoted."""
    return " ".join(shlex.quote(a) for a in form.format(t=token, w=tail).split("|"))


def _plan(cli: Cli, one: str, two: str) -> Any:
    return cli("plan", "--side", f"a=cmd:{one}", "--side", f"b=cmd:{two}")


# Each form, with ``{t}`` where the credential stands and ``{w}`` where a later word stands.
FORMS = {
    "env-authorization": "env|AUTHORIZATION=Bearer {t} {w}|true",
    "auth-option": "true|--auth=Bearer {t} {w}",
    "token-option": "true|--token=Basic {t} {w}",
    "docker-e-glued": "true|-eAUTH_TOKEN=Token {t} {w}",
    "next-argument-scheme": "true|--token|Bearer {t} {w}",
    "next-argument-password": "true|--password|{t} {w}",
}


@pytest.mark.parametrize("form", list(FORMS.values()), ids=list(FORMS))
def test_plan_refuses_sides_that_differ_only_in_a_rotated_credential(cli: Cli, form: str) -> None:
    result = _plan(cli, _words(form, OLD, TAIL_A), _words(form, NEW, TAIL_A))

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


@pytest.mark.parametrize("form", list(FORMS.values()), ids=list(FORMS))
def test_plan_takes_sides_that_differ_after_the_credential_with_one_note(
    cli: Cli, form: str
) -> None:
    result = _plan(cli, _words(form, OLD, TAIL_A), _words(form, OLD, TAIL_B))

    assert result.code == EXIT_OK, result.err
    assert result.err.count(NOTE_LINE) == 1
    for piece in (OLD, TAIL_A, TAIL_B):
        assert piece not in result.out
        assert piece not in result.err


# Pairs that differ only in a part of an address that the shown command hides.
ADDRESSES = {
    "user-name": ("true|postgres://zqalice@db/shop", "true|postgres://zqbobby@db/shop"),
    "database": (
        "env|DB_PASSWORD=redis://:{t}@localhost/0|true",
        "env|DB_PASSWORD=redis://:{t}@localhost/1|true",
    ),
    "query": (
        "true|--auth-url|http://localhost/v1?token={t}&model=zqalpha",
        "true|--auth-url|http://localhost/v1?token={t}&model=zqbravo",
    ),
}


@pytest.mark.parametrize(("one", "two"), list(ADDRESSES.values()), ids=list(ADDRESSES))
def test_plan_takes_sides_that_differ_in_a_hidden_part_of_an_address_with_one_note(
    cli: Cli, one: str, two: str
) -> None:
    result = _plan(cli, _words(one, OLD, ""), _words(two, OLD, ""))

    assert result.code == EXIT_OK, result.err
    assert result.err.count(NOTE_LINE) == 1
    for piece in (OLD, "zqalice", "zqbobby", "zqalpha", "zqbravo"):
        assert piece not in result.out
        assert piece not in result.err


GLUED = {
    "auth": "--command=AUTH {t}",
    "auth-with-user": "--command=AUTH bench {t}",
    "acl-setuser": "--command=ACL SETUSER bench on >{t}",
}


@pytest.mark.parametrize("form", list(GLUED.values()), ids=list(GLUED))
def test_plan_refuses_memtier_sides_that_differ_only_in_a_glued_command_s_password(
    cli: Cli, clients: Path, form: str
) -> None:
    head = shlex.quote(str(clients / "memtier_benchmark"))
    one = f"{head} {shlex.quote(form.format(t=OLD))}"
    two = f"{head} {shlex.quote(form.format(t=NEW))}"
    result = _plan(cli, one, two)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def test_plan_takes_memtier_sides_that_differ_in_another_word_of_a_glued_command(
    cli: Cli, clients: Path
) -> None:
    head = shlex.quote(str(clients / "memtier_benchmark"))
    one = f"{head} {shlex.quote(f'--command=ACL SETUSER bench on >{OLD} ~zqalpha*')}"
    two = f"{head} {shlex.quote(f'--command=ACL SETUSER bench on >{OLD} ~zqbravo*')}"
    result = _plan(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert OLD not in result.err


def _run(cli: Cli, folder: Path, new: str) -> Any:
    return cli(
        "run",
        "--side",
        f"new=cmd:{new}",
        "--side",
        f"old=cmd:{PYTHON} -c pass --old",
        "--baseline",
        "old",
        *QUICK,
        "--out",
        folder,
    )


def _compare(cli: Cli, tmp_path: Path, first: str, second: str) -> Any:
    for name, value in (("one", first), ("two", second)):
        done = _run(cli, tmp_path / name, value)
        assert done.code == EXIT_OK, done.err
    return cli(
        "compare",
        tmp_path / "one" / "capture.jsonl",
        tmp_path / "two" / "capture.jsonl",
        "--out",
        tmp_path / "pooled",
    )


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _refusal_line(err: str) -> str:
    (line,) = [line for line in err.splitlines() if line.startswith("E_")]
    return line


# The forms run through ``compare``, as the program after ``python -c pass``.
RUN_FORMS = {
    "auth-option": "--auth=Bearer {t} {w}",
    "next-argument-scheme": "--token|Bearer {t} {w}",
    "next-argument-password": "--password|{t} {w}",
}


@pytest.mark.parametrize("form", list(RUN_FORMS.values()), ids=list(RUN_FORMS))
def test_compare_pools_captures_whose_side_differs_only_in_a_rotated_credential(
    cli: Cli, tmp_path: Path, form: str
) -> None:
    head = f"{PYTHON} -c pass "
    result = _compare(
        cli, tmp_path, head + _words(form, OLD, TAIL_A), head + _words(form, NEW, TAIL_A)
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True


@pytest.mark.parametrize("form", list(RUN_FORMS.values()), ids=list(RUN_FORMS))
def test_compare_refuses_captures_whose_side_differs_after_the_credential(
    cli: Cli, tmp_path: Path, form: str
) -> None:
    head = f"{PYTHON} -c pass "
    result = _compare(
        cli, tmp_path, head + _words(form, OLD, TAIL_A), head + _words(form, OLD, TAIL_B)
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    for piece in (OLD, TAIL_A, TAIL_B):
        assert piece not in result.out
        assert piece not in result.err


def test_compare_pools_memtier_captures_that_differ_only_in_a_glued_command_s_password(
    cli: Cli, tmp_path: Path, clients: Path
) -> None:
    head = shlex.quote(str(clients / "memtier_benchmark"))
    result = _compare(
        cli,
        tmp_path,
        f"{head} {shlex.quote(f'--command=AUTH bench {OLD}')}",
        f"{head} {shlex.quote(f'--command=AUTH bench {NEW}')}",
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True


def test_compare_refuses_memtier_captures_that_differ_in_another_word_of_a_glued_command(
    cli: Cli, tmp_path: Path, clients: Path
) -> None:
    head = shlex.quote(str(clients / "memtier_benchmark"))
    result = _compare(
        cli,
        tmp_path,
        f"{head} {shlex.quote(f'--command=SET __key__ {TAIL_A}')}",
        f"{head} {shlex.quote(f'--command=SET __key__ {TAIL_B}')}",
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err).startswith("E_POOL_SIDE_DRIFT: the fingerprint of new")


def test_compare_refuses_captures_whose_address_differs_in_its_database(
    cli: Cli, tmp_path: Path
) -> None:
    head = f"{PYTHON} -c pass "
    result = _compare(
        cli,
        tmp_path,
        head + shlex.quote(f"--password=redis://:{OLD}@localhost/0"),
        head + shlex.quote(f"--password=redis://:{OLD}@localhost/1"),
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    assert OLD not in result.err


def test_compare_pools_captures_whose_address_differs_only_in_its_password(
    cli: Cli, tmp_path: Path
) -> None:
    head = f"{PYTHON} -c pass "
    result = _compare(
        cli,
        tmp_path,
        head + shlex.quote(f"--password=redis://:{OLD}@localhost/0"),
        head + shlex.quote(f"--password=redis://:{NEW}@localhost/0"),
    )

    assert result.code == EXIT_OK, result.err


def test_a_run_of_sides_that_differ_in_an_address_user_shares_no_user_name(
    cli: Cli, tmp_path: Path
) -> None:
    folder = tmp_path / "run"
    result = cli(
        "run",
        "--side",
        f"new=cmd:{PYTHON} -c pass postgres://zqalice@db/shop",
        "--side",
        f"old=cmd:{PYTHON} -c pass postgres://zqbobby@db/shop",
        "--baseline",
        "old",
        *QUICK,
        "--out",
        folder,
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert [n["code"] for n in results["notes"] if n["code"] == NOTE_CODE] == [NOTE_CODE]
    shared = [result.out, result.err]
    for name in ("results.json", "results.md", "report.html"):
        page = folder / name
        if page.exists():
            shared.append(page.read_text(encoding="utf-8"))
    assert len(shared) >= 4
    for text in shared:
        assert "zqalice" not in text
        assert "zqbobby" not in text


@pytest.fixture
def value_clients(tmp_path: Path) -> Path:
    """A folder with made-up programs named as clients whose password options are read."""
    folder = tmp_path / "clients"
    folder.mkdir()
    for name in ("redis-benchmark", "mysql"):
        program = folder / name
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return folder


# Each form: an ordinary name's value that a later client reads, with ``{t}`` where the
# password stands, ``{w}`` where a later word stands and ``{bin}`` where the clients' folder
# stands, its arguments joined by ``|``.
CLIENT_VALUES = {
    "spaced-before-redis-benchmark": "env|MADE_UP_FLAGS=-a {t} -n {w}|{bin}/redis-benchmark",
    "glued-before-mysql": "env|MADE_UP_FLAGS=-p{t} --port={w}|{bin}/mysql",
    "shell-text": "sh|-c|REDIS_ARGS='-a {t} -n {w}' {bin}/redis-benchmark $REDIS_ARGS",
}


def _client_words(form: str, folder: Path, token: str, tail: str) -> str:
    return _words(form.replace("{bin}", str(folder)), token, tail)


@pytest.mark.parametrize("form", list(CLIENT_VALUES.values()), ids=list(CLIENT_VALUES))
def test_plan_refuses_sides_that_differ_only_in_a_password_a_later_client_reads(
    cli: Cli, value_clients: Path, form: str
) -> None:
    one = _client_words(form, value_clients, OLD, "8")
    two = _client_words(form, value_clients, NEW, "8")
    result = _plan(cli, one, two)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


@pytest.mark.parametrize("form", list(CLIENT_VALUES.values()), ids=list(CLIENT_VALUES))
def test_plan_takes_sides_that_differ_in_a_word_after_a_password_a_later_client_reads(
    cli: Cli, value_clients: Path, form: str
) -> None:
    one = _client_words(form, value_clients, OLD, "8")
    two = _client_words(form, value_clients, OLD, "16")
    result = _plan(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert OLD not in result.out
    assert OLD not in result.err


# A scheme word that is a credential's whole value: the word after it may be a token, and the
# shown command and the hashes hide it, but it may as well be a program or a model file, so a
# difference there makes two sides. ``{w}`` is the word after the scheme word.
SCHEME_NEIGHBOURS = {
    "env-program": "env|AUTH=token|{w}",
    "next-argument-model": f"{PYTHON}|-c|pass|--auth|basic|{{w}}",
    "glued-option-model": f"{PYTHON}|-c|pass|--auth=basic|{{w}}",
}


@pytest.fixture
def neighbours(tmp_path: Path) -> tuple[str, str]:
    """Two made-up programs whose paths differ only in their names."""
    folder = tmp_path / "neighbours"
    folder.mkdir()
    paths = []
    for name in (TAIL_A, TAIL_B):
        program = folder / name
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        paths.append(str(program))
    return paths[0], paths[1]


@pytest.mark.parametrize("form", list(SCHEME_NEIGHBOURS.values()), ids=list(SCHEME_NEIGHBOURS))
def test_plan_takes_sides_that_differ_in_the_word_after_a_scheme_word_value_with_one_note(
    cli: Cli, neighbours: tuple[str, str], form: str
) -> None:
    one = " ".join(shlex.quote(a) for a in form.format(w=neighbours[0]).split("|"))
    two = " ".join(shlex.quote(a) for a in form.format(w=neighbours[1]).split("|"))
    result = _plan(cli, one, two)

    assert result.code == EXIT_OK, result.err
    assert result.err.count(NOTE_LINE) == 1
    for piece in (TAIL_A, TAIL_B):
        assert piece not in result.out
        assert piece not in result.err


def test_compare_refuses_captures_whose_word_after_a_scheme_word_value_differs(
    cli: Cli, tmp_path: Path
) -> None:
    head = f"{PYTHON} -c pass --auth basic "
    result = _compare(cli, tmp_path, head + TAIL_A, head + TAIL_B)

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    for piece in (TAIL_A, TAIL_B):
        assert piece not in result.out
        assert piece not in result.err
