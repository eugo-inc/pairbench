# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A password before a host in a case id is hidden with no user before its ``:`` as well.

A case id may give a password before a host with an empty user, as an address with no user
name writes it: ``bench[:VALUE@db.example:6379]``. The password is hidden up to the ``@``, as
it is after a user, as the whole of a part and with text around it, and as the whole of a
part a quote or an angle bracket in it is hidden with the rest. With no user, a password that
starts with a ``:`` is hidden as well (``bench[::VALUE@db.example:6379]``), as the whole of a
part with a quote or an angle bracket in it too, and so is a name that starts with ``::``
before an ``@`` and a host or a version with a dot. A ``:`` with nothing to hide after it, a
``::`` after a name, as in ``Module::Name@1.23``, and a host or a port alone are shown as
typed. Every value is made up.
"""

from __future__ import annotations

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Case ids with a password before a host and no user, ``{v}`` the password, and as shown.
HIDDEN = {
    "the whole of a part": ("bench[:{v}@db.example:6379]", "bench[:<hidden>@db.example:6379]"),
    "a host with a dot": ("bench[:{v}@db.example]", "bench[:<hidden>@db.example]"),
    "a host with a port": ("bench[:{v}@cache:6379]", "bench[:<hidden>@cache:6379]"),
    "a part after a slash": (
        "BM_Connect/:{v}@db.example:6379",
        "BM_Connect/:<hidden>@db.example:6379",
    ),
    "text after the host": (
        "test_db[:{v}@db.example:5432-ro]",
        "test_db[:<hidden>@db.example:5432-ro]",
    ),
    "in quotes": (
        'test_db[{{"dsn":":{v}@db.example"}}]',
        'test_db[{{"dsn":":<hidden>@db.example"}}]',
    ),
    "beside another part": ("bench[a,:{v}@db.example]", "bench[a,:<hidden>@db.example]"),
    "a double quote in the password": (
        'bench[:made"{v}@db.example:6379]',
        "bench[:<hidden>@db.example:6379]",
    ),
    "a single quote in the password": (
        "bench[:made'{v}@db.example:6379]",
        "bench[:<hidden>@db.example:6379]",
    ),
    "an angle bracket in the password": (
        "bench[:made<{v}@db.example]",
        "bench[:<hidden>@db.example]",
    ),
    "a password that starts with a colon": (
        "bench[::{v}@db.example:6379]",
        "bench[:<hidden>@db.example:6379]",
    ),
    "a password that starts with a colon, before a host with a dot": (
        "bench[::{v}@db.example]",
        "bench[:<hidden>@db.example]",
    ),
    "a password that starts with a colon, after a slash": (
        "BM_Connect/::{v}@db.example:6379",
        "BM_Connect/:<hidden>@db.example:6379",
    ),
    "a password that starts with a colon, text after the host": (
        "test_db[::{v}@db.example:5432-ro]",
        "test_db[:<hidden>@db.example:5432-ro]",
    ),
    "a password that starts with a colon, in quotes": (
        'test_db[{{"dsn":"::{v}@db.example"}}]',
        'test_db[{{"dsn":":<hidden>@db.example"}}]',
    ),
    "a password that starts with a colon, after a name and =": (
        "test_db[dsn=::{v}@db.example:6379]",
        "test_db[dsn=:<hidden>@db.example:6379]",
    ),
    "a password that starts with a colon, beside another part": (
        "bench[a,::{v}@db.example]",
        "bench[a,:<hidden>@db.example]",
    ),
    "a password that is a colon and more colons": (
        "bench[:::{v}@db.example:6379]",
        "bench[:<hidden>@db.example:6379]",
    ),
    "a password that starts with a colon, a double quote in it": (
        'bench[::made"{v}@db.example:6379]',
        "bench[:<hidden>@db.example:6379]",
    ),
    "a password that starts with a colon, a single quote in it": (
        "bench[::made'{v}@db.example:6379]",
        "bench[:<hidden>@db.example:6379]",
    ),
    "a password that starts with a colon, an angle bracket in it": (
        "bench[::made<{v}@db.example]",
        "bench[:<hidden>@db.example]",
    ),
}


@pytest.mark.parametrize("row", sorted(HIDDEN))
def test_a_password_with_no_user_before_a_host_is_hidden(row: str) -> None:
    typed, shown = HIDDEN[row]

    for value in VALUES:
        assert model.public_case(typed.format(v=value)) == shown.format()


# Case ids with a ``:`` before or near a host that hide nothing, shown as typed.
SHOWN_AS_TYPED = (
    "bench[:6379]",
    "bench[:x]",
    "test[a:b]",
    # A ``::`` after a name joins the parts of the name, before a host or a version too.
    "test_dep[Module::Name@1.23]",
    "query[pkg::name@v2]",
    "query[Token::Kind]",
    # A name that starts with ``::`` with no host or version that holds a dot after its ``@``.
    "x[::Name@v2]",
    "test_login[bench@db.example]",
    "BM_Connect/db.example:6379",
    "test_tag[python:3.12@slim]",
    "test_tag[:3.12@slim]",
    "bench[@db.example:6379]",
)


@pytest.mark.parametrize("case", SHOWN_AS_TYPED)
def test_an_id_with_nothing_to_hide_is_shown_as_typed(case: str) -> None:
    assert model.public_case(case) == case
