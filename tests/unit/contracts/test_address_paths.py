# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The folders of a local path inside an address are cut, and a '/' that is no path stays.

A database or socket address names a local path in a query value
(``?host=``, ``?sslrootcert=``, ``?unix_socket=``), percent-encoded in a query
value or where the host stands, or after ``unix://`` with no ``/`` before it.
Each such path keeps ``/`` (or ``%2F``) and its last part, as the path of an
address with no host does, and the rest of the address is kept: the database
name, the other parameters. A relative path glued to ``-I`` and a ``/`` after
``=`` in the path of an address are shown as typed. The hashes read every
address as typed. Every folder name here is made up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

# The made-up folders of every local path here; none of them may be shown.
FOLDERS = ("zqd1", "zqd2")

# An address, how a free text shows it and how the shown command shows it.
ADDRESSES = (
    (
        "postgresql://localhost/bench?host=%2Fzqd1%2Fzqd2%2Frun",
        "postgresql://localhost/bench?host=%2Frun",
        "postgresql://localhost/bench?host=%2Frun",
    ),
    (
        "postgresql://localhost/bench?port=5432&host=%2Fzqd1%2Fzqd2%2Frun",
        "postgresql://localhost/bench?port=5432&host=%2Frun",
        "postgresql://localhost/bench?port=5432&host=%2Frun",
    ),
    (
        "postgresql://localhost/bench?port=5432&host=/zqd1/zqd2/run",
        "postgresql://localhost/bench?port=5432&host=/run",
        "postgresql://localhost/bench?port=5432&host=/run",
    ),
    (
        "postgresql:///bench?host=%2Fzqd1%2Fzqd2%2Frun&port=5432",
        "postgresql:///bench?host=%2Frun&port=5432",
        "postgresql:///bench?host=%2Frun&port=5432",
    ),
    (
        "postgresql:///bench?host=/zqd1/zqd2/run&port=5432",
        "postgresql:///bench?host=/run&port=5432",
        "postgresql:///bench?host=/run&port=5432",
    ),
    (
        "postgres:///bench?host=/zqd1/zqd2/run",
        "postgres:///bench?host=/run",
        "postgres:///bench?host=/run",
    ),
    (
        "postgresql:///bench?sslmode=verify-full&sslrootcert=/zqd1/zqd2/root.crt&port=5432",
        "postgresql:///bench?sslmode=verify-full&sslrootcert=/root.crt&port=5432",
        "postgresql:///bench?sslmode=verify-full&sslrootcert=/root.crt&port=5432",
    ),
    (
        "postgresql://localhost/bench?sslrootcert=%2Fzqd1%2Fzqd2%2Froot.crt",
        "postgresql://localhost/bench?sslrootcert=%2Froot.crt",
        "postgresql://localhost/bench?sslrootcert=%2Froot.crt",
    ),
    (
        "mysql:///bench?unix_socket=/zqd1/zqd2/mysqld.sock",
        "mysql:///bench?unix_socket=/mysqld.sock",
        "mysql:///bench?unix_socket=/mysqld.sock",
    ),
    (
        "mysql://localhost/bench?unix_socket=%2Fzqd1%2Fzqd2%2Fmysqld.sock&charset=utf8",
        "mysql://localhost/bench?unix_socket=%2Fmysqld.sock&charset=utf8",
        "mysql://localhost/bench?unix_socket=%2Fmysqld.sock&charset=utf8",
    ),
    (
        "postgresql://%2Fzqd1%2Fzqd2%2Frun/bench",
        "postgresql://%2Frun/bench",
        "postgresql://<hidden>/bench",
    ),
    (
        "redis://localhost:6379/0?ssl_ca_certs=/zqd1/zqd2/ca.pem",
        "redis://localhost:6379/0?ssl_ca_certs=/ca.pem",
        "redis://localhost:6379/0?ssl_ca_certs=/ca.pem",
    ),
    ("unix://zqd1/zqd2/run.sock", "unix:///run.sock", "unix:///run.sock"),
    ("UNIX://zqd1/zqd2/run.sock", "UNIX:///run.sock", "UNIX:///run.sock"),
    (
        "redis+unix://zqd1/zqd2/r.sock?db=0",
        "redis+unix:///r.sock?db=0",
        "redis+unix:///r.sock?db=0",
    ),
    (
        "http://localhost:8000/v1?next=/zqd1/zqd2/models",
        "http://localhost:8000/v1?next=/models",
        "http://localhost:8000/v1?next=/models",
    ),
)


@pytest.mark.parametrize(("address", "text", "command"), ADDRESSES)
def test_a_local_path_inside_an_address_shows_its_last_part_and_the_rest_of_the_address(
    address: str, text: str, command: str
) -> None:
    assert model.public_text(f"open {address} now") == f"open {text} now"
    assert model.public_text(text) == text
    assert model.public_case(f"test_open[{address}]") == f"test_open[{text}]"
    shown = model.public_command(("tool", address))
    assert shown == shlex.join(["tool", command])
    assert model.public_command(("sh", "-c", f"tool '{address}'")) == shlex.join(
        ["sh", "-c", f"tool '{command}'"]
    )
    assert model.public_words(f"tool '{address}'") == f"tool {command}"
    assert model.public_command(shlex.split(str(shown))) == shown
    assert not any(folder in str(shown) for folder in FOLDERS)
    assert model.hashed_argv(("tool", address)) == ["tool", address]


# A '/' that is no absolute path: shown as typed. The hashes read each as typed too.
KEPT = (
    ("tool", "-Ia/b", "-q"),
    ("tool", "-Iinclude/zq", "-q"),
    ("curl", "http://localhost:8001/v1/abc=/x"),
    ("curl", "http://localhost:8000/v1?next=/models"),
)


@pytest.mark.parametrize("argv", KEPT)
def test_a_slash_that_starts_no_absolute_path_is_kept(argv: tuple[str, ...]) -> None:
    assert model.public_command(argv) == shlex.join(argv)
    assert model.public_command(("sh", "-c", shlex.join(argv))) == shlex.join(
        ["sh", "-c", shlex.join(argv)]
    )
    assert model.public_text(" ".join(argv)) == " ".join(argv)
    assert model.hashed_argv(argv) == list(argv)


# An absolute path glued to an option, of one letter or more: cut to its last part. A
# relative path of three parts or more glued to a one-letter option reads as an option of
# more letters with an absolute path glued to it (``-Ia`` and ``/zqd1/zqd2``), as
# ``-isystem/a/include`` is, so it is cut too. A path that starts at ``~`` names a home
# folder, so it is cut after an option of more letters even when one part follows it.
GLUED = (
    ("-I/zqd1/zqd2/include", "-Iinclude"),
    ("-isystem/zqd1/zqd2/include", "-isysteminclude"),
    ("-MF/zqd1/zqd2/x.d", "-MFx.d"),
    ("-L~/zqd1/zqd2/lib", "-Llib"),
    ("-Ia/zqd1/zqd2", "-Iazqd2"),
    ("-isystem~/zqd1", "-isystemzqd1"),
    ("-isystem~zqdu/inc", "-isysteminc"),
    ("-MF~/x.d", "-MFx.d"),
)
# An absolute path of one part glued to an option of more letters names no folder: kept.
GLUED_KEPT = ("-isystem/include", "-MF/x.d")


@pytest.mark.parametrize(("arg", "shown"), GLUED)
def test_an_absolute_path_glued_to_an_option_is_cut(arg: str, shown: str) -> None:
    assert model.public_command(("cc", arg)) == shlex.join(["cc", shown])
    assert model.public_text(f"cc {arg} -c x.c") == f"cc {shown} -c x.c"


@pytest.mark.parametrize("arg", GLUED_KEPT)
def test_a_path_of_one_part_glued_to_an_option_of_more_letters_is_kept(arg: str) -> None:
    assert model.public_command(("cc", arg)) == shlex.join(["cc", arg])
    assert model.public_text(f"cc {arg} -c x.c") == f"cc {arg} -c x.c"
