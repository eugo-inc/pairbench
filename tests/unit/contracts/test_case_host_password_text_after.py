# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A case id hides a password before a host with text before or after the host.

``pytest`` joins the values of a test with two parameters with ``-``, so a test given a
connection text ``bob:V@db.example:5432`` and a mode ``ro`` has the id
``test_db[bob:V@db.example:5432-ro]``; JSON, quotes, a query, a name before the user and
another host after it put text around the same form. The password is hidden from the ``:``
after the user up to the ``@`` before the host, and the user, the host and the text around
them are kept. Each row is cleaned with two made-up values: no six characters in a row of
either show, both give the same id, and the id shown is cleaned to itself. An address with no
password, an image with a digest, a version after ``@`` and a name with ``::`` are kept as
they are. Two ids that differ only in the password are refused with ``E_USAGE``.
"""

from __future__ import annotations

import pytest

from pairbench import api, model
from pairbench.errors import Refusal

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum3fig88qz")
# Each case id with a password before a host, ``{v}`` the password, and what it shows.
HIDDEN = {
    "test_db[bob:{v}@db.example:5432-ro]": "test_db[bob:<hidden>@db.example:5432-ro]",
    'test_db[{"dsn":"bob:{v}@db.example"}]': 'test_db[{"dsn":"bob:<hidden>@db.example"}]',
    'test_db["bob:{v}@db.example"]': 'test_db["bob:<hidden>@db.example"]',
    "test_db['bob:{v}@db.example']": "test_db['bob:<hidden>@db.example']",
    "test_db[<bob:{v}@db.example>]": "test_db[<bob:<hidden>@db.example>]",
    "test_db[bob:{v}@db.example?sslmode=require]": (
        "test_db[bob:<hidden>@db.example?sslmode=require]"
    ),
    "test_db[bob:{v}@db.example#x]": "test_db[bob:<hidden>@db.example#x]",
    "test_db[bob:{v}@db.example:5432=x]": "test_db[bob:<hidden>@db.example:5432=x]",
    "test_db[bob:{v}@db.example:5432:x]": "test_db[bob:<hidden>@db.example:5432:x]",
    "test_db[bob:{v}@db.example:5432-1]": "test_db[bob:<hidden>@db.example:5432-1]",
    "test_db[bob:{v}@db.example|x]": "test_db[bob:<hidden>@db.example|x]",
    "test_db[bob:{v}@db.example&x]": "test_db[bob:<hidden>@db.example&x]",
    "test_db[bob:{v}@db.example_1]": "test_db[bob:<hidden>@db.example_1]",
    "test_db[bob:{v}@db_1.example]": "test_db[bob:<hidden>@db_1.example]",
    "test_db[dsn=bob:{v}@db.example]": "test_db[dsn=bob:<hidden>@db.example]",
    "test_db[url=bob:{v}@db.example:5432]": "test_db[url=bob:<hidden>@db.example:5432]",
    "test_db[$bob:{v}@db.example]": "test_db[$bob:<hidden>@db.example]",
    "test_db[bob@corp:{v}@db.example-ro]": "test_db[bob@corp:<hidden>@db.example-ro]",
    "test_db[bob%40corp:{v}@db.example-ro]": "test_db[bob%40corp:<hidden>@db.example-ro]",
    "test_db[db:bob:{v}@db.example-ro]": "test_db[db:<hidden>@db.example-ro]",
    "test_db[x@h.example:bob:{v}@db.example-ro]": "test_db[x@h.example:<hidden>@db.example-ro]",
    "test_db[bob:{v}@db.example:5432-ro-bob:{v}@db2.example-x]": (
        "test_db[bob:<hidden>@db.example:<hidden>@db2.example-x]"
    ),
    "test_db[bob:{v}@192.0.2.10:5432-ro]": "test_db[bob:<hidden>@192.0.2.10:5432-ro]",
    "test_db[bob:{v}@localhost:6379-ro]": "test_db[bob:<hidden>@localhost:6379-ro]",
}
# Ids with an ``@`` that are kept as they are: an address with no password, an image with a
# tag or a digest, a version, a name with ``::``, a user with an empty password, a benchmark's
# named argument, and ids already shown.
SHOWN = (
    "test[python:3.12@slim]",
    "bench[pkg::name@v2]",
    "test_img[python:3.12@sha256:0a1b2c3d4e5f]",
    "test_img[node:20@sha256:0123456789abcdef]",
    "test_mail[alice@example.com]",
    "test_mail[to=alice@example.com-x]",
    "test_v[pkg@1.2.3-x]",
    "BM_x/key:3",
    "test_dep[a::b@c.d-x]",
    "test_x[user@db.example:5432-ro]",
    "test_db[bob:@db.example-ro]",
    "test_x[a:b@c]",
    "test_x[x@h.example-y@h.example]",
    "test_db[bob:<hidden>@db.example:5432-ro]",
    'test_db[{"dsn":"bob:<hidden>@db.example"}]',
)


def _filled(case: str, at: int) -> str:
    return case.replace("{v}", VALUES[at])


def _pieces(text: str) -> list[str]:
    """Return each six characters in a row of a made-up value that the text holds."""
    found = (value[at : at + 6] for value in VALUES for at in range(len(value) - 5))
    return [piece for piece in found if piece in text]


@pytest.mark.parametrize(("case", "shown"), list(HIDDEN.items()))
def test_a_password_before_a_host_with_text_around_it_is_hidden(case: str, shown: str) -> None:
    first, second = (model.public_case(_filled(case, at)) for at in (0, 1))

    assert (first, second) == (shown, shown)
    assert _pieces(first + second) == []


@pytest.mark.parametrize("case", list(HIDDEN))
def test_a_case_id_with_its_password_hidden_is_cleaned_to_itself(case: str) -> None:
    shown = model.public_case(_filled(case, 0))

    assert model.public_case(shown) == shown


@pytest.mark.parametrize("case", SHOWN)
def test_a_case_id_with_an_at_sign_and_no_password_is_kept(case: str) -> None:
    assert model.public_case(case) == case


def test_two_case_ids_that_differ_only_in_a_password_before_a_host_are_refused() -> None:
    ids = [_filled("test_db[bob:{v}@db.example:5432-ro]", at) for at in (0, 1)]
    samples = [
        api.Sample(case=raw, metric="time", unit="s", better="lower", kind="time", value=1.5)
        for raw in ids
    ]

    with pytest.raises(Refusal) as caught:
        api.public_cases(samples, "bench.json")

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith(
        "bench.json: two different cases have the name "
        "'test_db[bob:<hidden>@db.example:5432-ro]' once "
    )
    assert _pieces(caught.value.message) == []
