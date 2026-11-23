# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config reference says a path nested in the query of an address is cut after any host.

A local address and a climbing path in the query or the fragment of an address are cut in the
shown command as they are after a host, whatever stands before them, and one that holds a
blank, another address or a random-looking value is kept as typed, so the host of the other
address is hidden. The config reference says so with three examples, and each example shows
what it says. Every folder name and host here is made up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG = "docs/reference/config.md"
NESTED = (
    "In the shown command, a local address and a climbing path in the query or the fragment of an "
    "address are cut as they are after a host, whatever stands before them: no host, a host and an "
    "empty port, a host in brackets with no port, a `unix://` socket, the path of a `file://` "
    "address or an earlier path in the query "
    "(`postgresql:///db?sslrootcert=file:///made/up/ca.pem` shows "
    "`postgresql:///db?sslrootcert=file://ca.pem`, and "
    "`mysql://localhost:/db?ssl-ca=../../made/up/ca.pem` shows "
    "`mysql://localhost:/db?ssl-ca=ca.pem`), but a path inside a word that starts with three `/` "
    "or more, as in `--in=///made/up/x.txt`, is not read as a path, so its folders show, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say. After one of those, "
    "a local address ends at the next `&`, `?` or `#`, and one that holds a blank before then "
    "followed by a word with a `/`, which the path runs on over as it does over the words of a "
    "folder named in words, or that holds another address before then, or a value that looks "
    "random, shows as typed, as does a climbing path that holds such a blank and word before the "
    "next `&`, `?` or `#`, another address or such a value, so the host of the other address is "
    "hidden (`postgresql:///db?c=../made/up/s3://db.example/x` shows "
    "`postgresql:///db?c=../made/up/s3://<hidden>/x`), as the known limits say too. A blank with "
    "no such word after it ends the path, which is cut "
    "(`postgresql:///db?sslrootcert=file:///made/up/ca.pem fast` shows "
    "`postgresql:///db?sslrootcert=file://ca.pem fast`)."
)
# Each example of the sentence: an address, and what the shown command holds of it.
EXAMPLES = (
    (
        "postgresql:///db?sslrootcert=file:///made/up/ca.pem",
        "postgresql:///db?sslrootcert=file://ca.pem",
    ),
    ("mysql://localhost:/db?ssl-ca=../../made/up/ca.pem", "mysql://localhost:/db?ssl-ca=ca.pem"),
    (
        "postgresql:///db?sslrootcert=file:///made/up/ca.pem fast",
        "postgresql:///db?sslrootcert=file://ca.pem fast",
    ),
)
# The example of a climbing path kept as typed: an address, and what the shown command holds of
# it.
KEPT_EXAMPLE = (
    "postgresql:///db?c=../made/up/s3://db.example/x",
    "postgresql:///db?c=../made/up/s3://<hidden>/x",
)


def test_the_config_reference_says_where_a_nested_path_is_cut(repo_root: Path) -> None:
    assert NESTED in " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())


@pytest.mark.parametrize(("address", "shown"), EXAMPLES)
def test_each_example_shows_what_the_reference_says(address: str, shown: str) -> None:
    assert f"`{address}` shows `{shown}`" in NESTED
    assert model.public_command(("client", address)) == shlex.join(["client", shown])
    assert model.public_text(address) == shown
    assert model.hashed_argv(("client", address)) == ["client", address]


def test_the_example_of_a_kept_climbing_path_shows_what_the_reference_says() -> None:
    address, shown = KEPT_EXAMPLE
    assert f"`{address}` shows `{shown}`" in NESTED
    assert model.public_command(("client", address)) == shlex.join(["client", shown])
    assert model.public_text(address) == address
