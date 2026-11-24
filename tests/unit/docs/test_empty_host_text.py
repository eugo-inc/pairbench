# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""After which hosts the known limits say the path after a blank in a query parameter shows.

In the query or the fragment of an address, the words after a blank in a query parameter that
holds a relative path that stays inside its folder are kept as typed, and so is a query
parameter of such a path that holds an address with a host, after a host name or a port number,
with a path after it or none, and after an empty host, an empty port, a user, a host and an
empty port or a host in brackets with no path after it. With a path after anything else, as
with no host, with a path in a ``file://`` address, in a ``unix://`` address with no user, host
in brackets or socket path written with ``%2F``, and, for the words after a blank, in the shown
command after a scheme of one letter, both are cut. After a host in brackets in a ``unix://``
address a path in a later parameter shows too. The pages say so, and each form is read here
through the shown command and as a free text. Every folder name, host and value here is made
up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
# The words that say after which hosts the words after a blank are kept, and where they are cut.
SECURITY_SENTENCES = (
    "After a host name or a port number, with a path after it or none, and after an empty host, "
    "an empty port, a user, a host and an empty port or a host in brackets with no path after "
    "it, right before the query or the fragment, as in `postgresql://?k=x`, "
    "`postgresql://:?k=x`, `postgresql://@:?k=x`, `postgresql://db.example:?k=x` and "
    "`postgresql://[::1]?k=x`, the words after a blank in such a query parameter that no path "
    "runs on over are kept as typed to its end, so a path there shows its folders, and a path in "
    "a later parameter is cut.",
    "They are cut with a path after anything else, as in `postgresql:///db?k=x`, which has no "
    "host, `postgresql://[::1]/db?k=x` and `postgresql://db.example:/db?k=x`, with a path in a "
    "`file://` address, or one whose scheme ends in `file`, in a `unix://` address, or one whose "
    "scheme ends in `+unix`, with no user, host in brackets or socket path written with `%2F` "
    "before the query or the fragment, as in `unix://?k=x`, and in the shown command after a "
    "scheme of one letter, as in `x://?k=x`. After a host in brackets in such a `unix://` "
    "address, as in `unix://[::1]?k=x`, a path in a later parameter shows too:",
    "After the same hosts, and cut where those words are cut except after a scheme of one "
    "letter, a query parameter of such a path that holds an address with a host shows whole, "
    "with a `/` put before it, or with none after a host in brackets in a `unix://` address:",
)
CONFIG_SENTENCE = (
    "after a host name or a port number, or after an empty host, an empty port, a user, a host "
    "and an empty port or a host in brackets with no path after it, right before the query or "
    "the fragment (`postgresql://?k=x` or `postgresql://[::1]?k=x`, not `postgresql:///db?k=x`, "
    "which has no host, nor `postgresql://[::1]/db?k=x`), but for the forms the known limits "
    "name as cut,"
)
# The query parameters read here: a path after a blank, then a path in a later parameter; and
# an address with a host after an absolute path.
BLANK = "k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem"
NESTED = "k=a/../b:/made/up/x/s3://db2.example/y"
# As (the address, what the shown command shows of it, what a free text shows of it). A free
# text keeps a host; the shown command hides it.
KEPT = (
    (
        f"postgresql://?{BLANK}",
        "postgresql://?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://#{BLANK}",
        "postgresql://#k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://#k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://?{NESTED}",
        "postgresql://?k=/a/../b:/made/up/x/s3://<hidden>/y",
        "postgresql://?k=/a/../b:/made/up/x/s3://db2.example/y",
    ),
    (
        f"postgresql://:?{BLANK}",
        "postgresql://:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://:#{NESTED}",
        "postgresql://:#k=/a/../b:/made/up/x/s3://<hidden>/y",
        "postgresql://:#k=/a/../b:/made/up/x/s3://db2.example/y",
    ),
    (
        f"postgresql://@:?{BLANK}",
        "postgresql://<hidden>@:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://<hidden>@:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://db.example:?{BLANK}",
        "postgresql://<hidden>:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://db.example:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://db.example:#{NESTED}",
        "postgresql://<hidden>:#k=/a/../b:/made/up/x/s3://<hidden>/y",
        "postgresql://db.example:#k=/a/../b:/made/up/x/s3://db2.example/y",
    ),
    (
        f"s3://db.example:?{BLANK}",
        "s3://<hidden>:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "s3://db.example:?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://[::1]?{BLANK}",
        "postgresql://[::1]?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "postgresql://[::1]?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"postgresql://[::1]#{NESTED}",
        "postgresql://[::1]#k=/a/../b:/made/up/x/s3://<hidden>/y",
        "postgresql://[::1]#k=/a/../b:/made/up/x/s3://db2.example/y",
    ),
    (
        f"unix://u@?{BLANK}",
        "unix://<hidden>@?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "unix://<hidden>@?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem",
    ),
    (
        f"x://?{NESTED}",
        "x://?k=/a/../b:/made/up/x/s3://<hidden>/y",
        "x://?k=/a/../b:/made/up/x/s3://db2.example/y",
    ),
)
# After a host in brackets in a `unix://` address, a path in a later parameter shows too, and
# the parameter that holds an address with a host shows with no `/` put before it.
KEPT_IN_A_SOCKET = (
    (
        f"unix://[::1]?{BLANK}",
        "unix:///[::1]?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem",
        "unix:///[::1]?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem",
    ),
    (
        f"unix://[::1]?{NESTED}",
        "unix:///[::1]?k=a/../b:/made/up/x/s3://<hidden>/y",
        "unix:///[::1]?k=a/../b:/made/up/x/s3://db2.example/y",
    ),
)
CUT = (
    (
        f"postgresql:///db?{BLANK}",
        "postgresql:///db?k=a/../b x/c:ca.pem",
        "postgresql:///db?k=a/../b x/c:ca.pem",
    ),
    (
        f"postgresql:///db?{NESTED}",
        "postgresql:///db?k=a/../b:/y",
        "postgresql:///db?k=a/../b:/y",
    ),
    (
        f"postgresql://[::1]/db?{BLANK}",
        "postgresql://[::1]/db?k=a/../b x/c:ca.pem",
        "postgresql://[::1]/db?k=a/../b x/c:ca.pem",
    ),
    (
        f"postgresql://[::1]/db?{NESTED}",
        "postgresql://[::1]/db?k=a/../b:/y",
        "postgresql://[::1]/db?k=a/../b:/y",
    ),
    (
        f"postgresql://db.example:/db?{BLANK}",
        "postgresql://<hidden>:/db?k=a/../b x/c:ca.pem",
        "postgresql://db.example:/db?k=a/../b x/c:ca.pem",
    ),
    (
        f"postgresql://db.example:/db?{NESTED}",
        "postgresql://<hidden>:/db?k=a/../b:/y",
        "postgresql://db.example:/db?k=a/../b:/y",
    ),
    (
        f"postgresql://u@/db?{BLANK}",
        "postgresql://<hidden>@/db?k=a/../b x/c:ca.pem",
        "postgresql://<hidden>@/db?k=a/../b x/c:ca.pem",
    ),
    (
        f"file://db.example/db?{BLANK}",
        "file://db?k=a/../b x/c:ca.pem",
        "file://db?k=a/../b x/c:ca.pem",
    ),
    (
        f"git+file://db.example/db?{NESTED}",
        "git+file://db?k=a/../b:/y",
        "git+file://db?k=a/../b:/y",
    ),
    (
        f"unix://?{BLANK}",
        "unix:///?k=a/../b x/c:ca.pem",
        "unix:///?k=a/../b x/c:ca.pem",
    ),
    (
        f"unix://?{NESTED}",
        "unix:///?k=a/../b:/y",
        "unix:///?k=a/../b:/y",
    ),
)
# A scheme of one letter: the shown command cuts the words after a blank; a free text keeps them.
CUT_IN_THE_SHOWN_COMMAND = (
    (f"x://?{BLANK}", "x:ca.pem", "x://?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem"),
    (f"x://#{BLANK}", "x:ca.pem", "x://#k=a/../b x/c:/made/up/ca.pem&j=/ca.pem"),
)


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


def reads(address: str) -> tuple[str, str]:
    """What the shown command and a free text show of ``address``."""
    return model.public_command(("psql", address)), model.public_text(address)


@pytest.mark.parametrize("sentence", SECURITY_SENTENCES)
def test_the_known_limits_say_after_which_hosts_the_path_shows(
    repo_root: Path, sentence: str
) -> None:
    assert sentence in joined(repo_root, SECURITY)


def test_the_config_reference_says_after_which_hosts_the_path_shows(repo_root: Path) -> None:
    assert CONFIG_SENTENCE in joined(repo_root, CONFIG)


@pytest.mark.parametrize(("address", "shown", "text_shown"), KEPT)
def test_after_such_a_host_the_path_shows_its_folders(
    address: str, shown: str, text_shown: str
) -> None:
    assert reads(address) == (shlex.join(["psql", shown]), text_shown)
    assert "/made/up/" in shown
    assert "j=/made/" not in shown + text_shown


@pytest.mark.parametrize(("address", "shown", "text_shown"), KEPT_IN_A_SOCKET)
def test_after_a_host_in_brackets_in_a_socket_address_a_later_path_shows_too(
    address: str, shown: str, text_shown: str
) -> None:
    assert reads(address) == (shlex.join(["psql", shown]), text_shown)


@pytest.mark.parametrize(("address", "shown", "text_shown"), CUT)
def test_with_a_path_after_anything_else_the_path_is_cut(
    address: str, shown: str, text_shown: str
) -> None:
    assert reads(address) == (shlex.join(["psql", shown]), text_shown)
    assert "/made/up/" not in shown + text_shown


@pytest.mark.parametrize(("address", "shown", "text_shown"), CUT_IN_THE_SHOWN_COMMAND)
def test_after_a_scheme_of_one_letter_the_shown_command_cuts_the_path(
    address: str, shown: str, text_shown: str
) -> None:
    assert reads(address) == (shlex.join(["psql", shown]), text_shown)
    assert "/made/up/" not in shown
