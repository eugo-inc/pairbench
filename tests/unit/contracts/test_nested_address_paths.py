# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A local address or a climbing path in the query or fragment of an address shows its last part.

An address may name a local file in a query value or its fragment: a local
address (``file:`` with three or four ``/``, ``file://localhost/``, a ``file``
address with a host, ``sqlite:///``, ``unix:///``) or a relative path that
climbs out of its folder (``../``, ``./../``, ``data/../../``). Each is cut as
it is in the query of an address with a host, whatever stands before the query:
no host (``scheme:///db``), a host and an empty port (``scheme://host:/db``),
a host in brackets, ``unix://`` with no ``/`` before its path, or an earlier
path in the same query. It is cut so in a word of its own, inside ``sh -c``,
after ``--opt=`` and after ``NAME=``. An absolute path that starts at ``~`` or
at two ``/`` is cut there too, and a climbing path whose first folder starts
with ``-`` is read as it is after a host. A relative path that stays inside its
folder (``a/../b``) is shown as typed, with or without a host, and so is a path
of ``..`` parts alone with no host; after a host, a query parameter that climbs
out of its folder is cut to its last part, ``..`` parts alone included. An
absolute path after such a relative path in its query parameter is cut; the
shown command and a free text keep such a query parameter as typed from a
blank in it to its end and cut the paths after it. A case id keeps such a
relative path as typed with an absolute path right after it and a ``:``,
``=`` or ``@``, and after a host cuts that query parameter whole, with a ``/`` put before it, so a
quoted credential after it is hidden whole. The hashes
read every address as typed. Each is cleaned in time in proportion to its
length. Every folder name here is made up.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable

import pytest

from pairbench import api, model

# The made-up folders of every nested path cut here; none of them may be shown.
FOLDERS = ("zqd1", "zqd2")

# An address and how the shown command and a free text show it.
NESTED = (
    # A local address in the query of an address with no host.
    (
        "postgresql:///bench?sslrootcert=file:///zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=file://ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=file:////zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=file://ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=file://localhost/zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=file://ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=file://zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=file://ca.pem",
    ),
    (
        "postgresql:///bench?sslmode=verify-full&sslrootcert=file:///zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslmode=verify-full&sslrootcert=file://ca.pem",
    ),
    (
        "redis:///0?sock=unix:///zqd1/zqd2/redis.sock",
        "redis:///0?sock=unix:///redis.sock",
    ),
    (
        "mysql:///bench?db=sqlite:///zqd1/zqd2/bench.db",
        "mysql:///bench?db=sqlite:///bench.db",
    ),
    # A local address in the fragment of an address with no host.
    (
        "postgresql:///bench#file:///zqd1/zqd2/ca.pem",
        "postgresql:///bench#file://ca.pem",
    ),
    # A climbing path in the query and the fragment of an address with no host.
    (
        "postgresql:///bench?sslrootcert=../../zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=./../zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=data/../../zqd1/zqd2/ca.pem&port=5432",
        "postgresql:///bench?sslrootcert=ca.pem&port=5432",
    ),
    (
        "redis:///0#../../zqd1/zqd2/dump.rdb",
        "redis:///0#dump.rdb",
    ),
    # After a host and an empty port, and after a host in brackets.
    (
        "mysql://localhost:/bench?ssl-ca=../../zqd1/zqd2/ca.pem",
        "mysql://localhost:/bench?ssl-ca=ca.pem",
    ),
    (
        "mysql://localhost:/bench?ssl-ca=file:///zqd1/zqd2/ca.pem",
        "mysql://localhost:/bench?ssl-ca=file://ca.pem",
    ),
    (
        "http://[::1]/v1?cert=file:///zqd1/zqd2/ca.pem",
        "http://[::1]/v1?cert=file://ca.pem",
    ),
    (
        "http://[::1]/v1?cert=../../zqd1/zqd2/ca.pem",
        "http://[::1]/v1?cert=ca.pem",
    ),
    # After ``unix://``, with and without a ``/`` before the socket's path.
    (
        "unix:///run/bench.sock?cert=file:///zqd1/zqd2/ca.pem",
        "unix:///bench.sock?cert=file://ca.pem",
    ),
    (
        "unix://run/bench.sock?cert=../zqd1/zqd2/ca.pem",
        "unix:///bench.sock?cert=ca.pem",
    ),
    # After an earlier path or local address in the same query, with and without a host.
    (
        "postgresql:///bench?a=/zqd1/x&sslrootcert=file:///zqd1/zqd2/ca.pem",
        "postgresql:///bench?a=/x&sslrootcert=file://ca.pem",
    ),
    (
        "postgresql:///bench?a=/zqd1/x&sslrootcert=../../zqd1/zqd2/ca.pem",
        "postgresql:///bench?a=/x&sslrootcert=ca.pem",
    ),
    (
        "postgresql://localhost/bench?a=/zqd1/x&sslrootcert=file:///zqd1/zqd2/ca.pem",
        "postgresql://localhost/bench?a=/x&sslrootcert=file://ca.pem",
    ),
    (
        "postgresql://localhost/bench?a=/zqd1/x&sslrootcert=../../zqd1/zqd2/ca.pem",
        "postgresql://localhost/bench?a=/x&sslrootcert=ca.pem",
    ),
    (
        "postgresql:///bench?a=../zqd1/x&sslrootcert=../zqd2/ca.pem",
        "postgresql:///bench?a=x&sslrootcert=ca.pem",
    ),
    # An absolute path that starts at ``~`` or at two ``/`` in the query of an address with no host.
    (
        "postgresql:///bench?sslrootcert=~/zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=ca.pem",
    ),
    (
        "postgresql:///bench?sslrootcert=//zqd1/zqd2/ca.pem",
        "postgresql:///bench?sslrootcert=/ca.pem",
    ),
    # A climbing path and an absolute path after a relative path that stays in its folder.
    (
        "postgresql:///bench?next=a/../b&sslrootcert=../../zqd1/zqd2/ca.pem",
        "postgresql:///bench?next=a/../b&sslrootcert=ca.pem",
    ),
    (
        "postgresql:///bench?next=a/../b#/zqd1/zqd2/ca.pem",
        "postgresql:///bench?next=a/../b#/ca.pem",
    ),
    # Two local addresses, each in a query of its own.
    (
        "postgresql:///bench?sslcert=file:///zqd1/client.pem?sslkey=file:///zqd2/client.key",
        "postgresql:///bench?sslcert=file://client.pem?sslkey=file://client.key",
    ),
)


@pytest.mark.parametrize(("address", "shown"), NESTED)
def test_a_nested_local_address_or_climbing_path_shows_its_last_part(
    address: str, shown: str
) -> None:
    assert model.public_command(("psql", address)) == shlex.join(["psql", shown])
    assert model.public_text(f"open {address} now") == f"open {shown} now"
    assert model.public_text(shown) == shown


@pytest.mark.parametrize(("address", "shown"), NESTED)
def test_a_nested_local_address_or_climbing_path_shows_its_last_part_in_every_wrap(
    address: str, shown: str
) -> None:
    assert model.public_command(("sh", "-c", f"psql '{address}' && echo ok")) == shlex.join(
        ["sh", "-c", f"psql '{shown}' && echo ok"]
    )
    assert model.public_command(("tool", f"--url={address}")) == shlex.join(
        ["tool", f"--url={shown}"]
    )
    assert model.public_command(("env", f"BENCH_DB={address}", "tool")) == shlex.join(
        ["env", f"BENCH_DB={shown}", "tool"]
    )
    assert model.public_words(f"psql '{address}'") == f"psql {shown}"
    command = model.public_command(("psql", address))
    assert not any(folder in str(command) for folder in FOLDERS)
    # A cut file address (``file://ca.pem``) reads as one with a host when it is read again, as a
    # cut bare one does; every other shown command reads the same again.
    if "file://" not in shown:
        assert model.public_command(shlex.split(str(command))) == command


@pytest.mark.parametrize(("address", "shown"), NESTED)
def test_the_hashes_read_a_nested_path_as_typed(address: str, shown: str) -> None:
    assert model.hashed_argv(("psql", address)) == ["psql", address]
    assert model.hashed_argv(("tool", f"--url={address}")) == ["tool", f"--url={address}"]


# The query of an address with a host, before which each other outer form is shown
# alike: the nested path is cut as it is after the host.
HOST_FORM = "http://localhost/v1"
# Each outer form, and what a free text shows of it.
OUTER_FORMS = (
    ("http:///v1", "http:///v1"),
    ("http:////zqd1/v1", "http:///v1"),
    ("http://localhost:/v1", "http://localhost:/v1"),
    ("http://[::1]/v1", "http://[::1]/v1"),
    ("unix:///v1", "unix:///v1"),
    ("unix://zqd1/v1", "unix:///v1"),
    ("file://localhost/zqd1/v1", "file://v1"),
)
# Each query, and what a free text shows of it after the host and after every outer form.
QUERIES = (
    ("?cert=file:///zqd1/zqd2/ca.pem", "?cert=file://ca.pem"),
    ("?a=1&cert=file://localhost/zqd1/zqd2/ca.pem", "?a=1&cert=file://ca.pem"),
    ("#file:////zqd1/zqd2/ca.pem", "#file://ca.pem"),
    ("?cert=../zqd1/zqd2/ca.pem", "?cert=ca.pem"),
    ("?a=1&cert=../../zqd1/zqd2/ca.pem", "?a=1&cert=ca.pem"),
    ("#./../zqd1/zqd2/ca.pem", "#ca.pem"),
    ("?cert=data/../../zqd1/zqd2/ca.pem&a=1", "?cert=ca.pem&a=1"),
    (
        "?cert=file:///zqd1/zqd2/client.pem?key=../zqd1/zqd2/client.key",
        "?cert=file://client.pem?key=client.key",
    ),
)


@pytest.mark.parametrize(("outer", "outer_shown"), OUTER_FORMS)
@pytest.mark.parametrize(("query", "query_shown"), QUERIES)
def test_a_nested_path_is_cut_after_any_outer_form_as_after_a_host(
    outer: str, outer_shown: str, query: str, query_shown: str
) -> None:
    shown = model.public_text(outer + query)

    assert model.public_text(HOST_FORM + query) == HOST_FORM + query_shown
    assert shown == outer_shown + query_shown
    assert not any(folder in shown for folder in FOLDERS)


# A climbing path whose first folder starts with ``-``, in the fragment after each outer form:
# it is read as it is after the host, which shows it as typed.
DASH_LED = ("#-a/../../made/up/x", "#--x/../../made/up/y")


@pytest.mark.parametrize(("outer", "outer_shown"), OUTER_FORMS)
@pytest.mark.parametrize("fragment", DASH_LED)
def test_a_dash_led_climb_reads_after_any_outer_form_as_after_a_host(
    outer: str, outer_shown: str, fragment: str
) -> None:
    assert model.public_text(HOST_FORM + fragment) == HOST_FORM + fragment
    assert model.public_text(outer + fragment) == outer_shown + fragment


# Addresses whose query or fragment holds a '/' that names no folder outside: each is shown
# as typed by the shown command and a free text.
KEPT = (
    "postgresql:///bench?next=a/../b",
    "postgresql:///bench?expr=s/../X/",
    "postgresql:///bench?up=../..",
    "postgresql:///bench?v=v1/../v2&w=1/2",
    "postgresql:///bench?next=https://localhost/a/b",
    "postgresql:///bench?redirect=app:///home",
    "http://localhost:/v1/../../x",
    "postgresql:///bench?next=a/../b#top",
    "postgresql:///bench?up=../",
    "postgresql:///bench?up=../../&w=1",
    "redis:///0#../",
    "postgresql:///bench?src=proj/c++/src/bench.cc",
    # After a host too, where no ``/`` is put before the relative path.
    "http://localhost/v1?next=a/../b",
    "postgresql://localhost/bench?v=v1/../v2&w=1/2",
)


@pytest.mark.parametrize("address", KEPT)
def test_a_path_that_names_no_folder_outside_is_shown_as_typed(address: str) -> None:
    assert model.public_command(("curl", address)) == shlex.join(["curl", address])
    assert model.public_text(address) == address


# A relative path that stays inside its folder, and an absolute path that starts in it after
# a mark: the relative part is kept, and the absolute path shows its last part.
INSIDE = (
    (
        "postgresql:///bench?x=a/../b:/zqd1/zqd2/x",
        "postgresql:///bench?x=a/../b:/x",
    ),
    (
        "postgresql:///bench?x=a/../b:file:///zqd1/zqd2/x",
        "postgresql:///bench?x=a/../b:file://x",
    ),
    # The same after a host, and a path after the relative one in the next parameter.
    (
        "postgresql://localhost/bench?x=a/../b:/zqd1/zqd2/x",
        "postgresql://localhost/bench?x=a/../b:/x",
    ),
    (
        "postgresql://localhost/bench?x=a/../b:file:///zqd1/zqd2/x&y=1",
        "postgresql://localhost/bench?x=a/../b:file://x&y=1",
    ),
    (
        "http://localhost/v1?path=lib/../lib&j=/zqd1/zqd2/lib",
        "http://localhost/v1?path=lib/../lib&j=/lib",
    ),
    # A relative path that stays in its folder before a climbing one in the next parameter.
    (
        "postgresql://localhost/bench?k=x/../y&host=d/../../zqd1/zqd2/f",
        "postgresql://localhost/bench?k=x/../y&host=f",
    ),
)


@pytest.mark.parametrize(("address", "shown"), INSIDE)
def test_a_path_inside_a_relative_path_that_stays_in_its_folder_is_cut(
    address: str, shown: str
) -> None:
    assert model.public_command(("psql", address)) == shlex.join(["psql", shown])
    assert model.public_text(address) == shown


# The same paths in a case id, after each outer form whose rest a case id reads alone: the
# relative path is kept as typed with an absolute path right after it and a ``:``, ``=`` or
# ``@``, so that path shows its folders, as the security policy says.
CASE_INSIDE_KEPT = (
    (
        "test_conn[postgresql:///bench?x=a/../b:/zqd1/zqd2/x]",
        "test_conn[postgresql:///bench?x=a/../b:/zqd1/zqd2/x]",
    ),
    (
        "test_conn[mysql://localhost:/bench#a/../b=/zqd1/zqd2/x]",
        "test_conn[mysql://localhost:/bench#a/../b=/zqd1/zqd2/x]",
    ),
    (
        "test_conn[unix:///bench.sock?x=a/../b@/zqd1/zqd2/x]",
        "test_conn[unix:///bench.sock?x=a/../b@/zqd1/zqd2/x]",
    ),
    (
        "test_conn[file://localhost/zqd1/v1?x=a/../b:/zqd1/zqd2/x]",
        "test_conn[file://v1?x=a/../b:/zqd1/zqd2/x]",
    ),
)


@pytest.mark.parametrize(("case", "shown"), CASE_INSIDE_KEPT)
def test_a_case_id_keeps_a_path_inside_a_relative_path_that_stays_in_its_folder(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown


# An absolute path after a host in a case id keeps its own reading: its folders are cut.
CASE_INSIDE = (
    (
        "test_get[https://localhost////zqd1/zqd2/x]",
        "test_get[https://localhost//x]",
    ),
    (
        "test_conn[postgresql://localhost/db?a=b&///zqd1/zqd2/c]",
        "test_conn[postgresql://localhost/db?a=b&//c]",
    ),
)


@pytest.mark.parametrize(("case", "shown"), CASE_INSIDE)
def test_an_absolute_path_after_a_host_is_cut_in_a_case_id(case: str, shown: str) -> None:
    assert model.public_case(case) == shown


# The same relative path in a case id after a host, with no path before it in the query: its
# query parameter is cut whole, as an absolute path is, with a ``/`` put before it, so a path
# after it in that parameter shows its folders.
CASE_AFTER_HOST = (
    (
        "test_conn[postgresql://localhost/bench?x=a/../b:/zqd1/zqd2/x]",
        "test_conn[postgresql://localhost/bench?x=/a/../b:/zqd1/zqd2/x]",
    ),
    (
        "test_conn[http://localhost/v1?next=a/../b]",
        "test_conn[http://localhost/v1?next=/a/../b]",
    ),
)


@pytest.mark.parametrize(("case", "shown"), CASE_AFTER_HOST)
def test_a_case_id_cuts_the_query_parameter_of_a_relative_path_that_stays_whole_after_a_host(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown


# A relative path that stays inside its folder as the first value of the fragment of an address
# after a host, and a quoted credential after it: as (the id, how it shows, whether its cut
# drops a word, its name under ``NAME_KEY``). The secrets of a case id are read after the cut,
# so the query parameter of the relative path is cut whole, with a ``/`` put before it, and no
# part of the credential shows. The credentials and folders are made up.
NAME_KEY = bytes(range(32))
CREDENTIAL_AFTER_STAY = (
    (
        "test_conn[k=postgresql://db.example/db#password=a/../b&api_key='zqa zqb']",
        "test_conn[k=postgresql://db.example/db#password=<hidden>]",
        True,
        "test_conn[k=postgresql://db.example/db#password=<hidden>] +1f8142f7",
    ),
    (
        'x s://h.example/?token=s3://b#password=a/../token="zqa"',
        "x s://h.example/?token=<hidden>#password=<hidden>../token=<hidden>",
        False,
        "x s://h.example/?token=<hidden>#password=<hidden>../token=<hidden>",
    ),
    (
        "test_x[k=x://h.example/#password=a/../b&api_key='lib/../lib:/zqd1 zqd2/x.pem']",
        "test_x[k=x://h.example/#password=<hidden>]",
        False,
        "test_x[k=x://h.example/#password=<hidden>]",
    ),
)


@pytest.mark.parametrize(("case", "shown", "drops", "name"), CREDENTIAL_AFTER_STAY)
def test_no_part_of_a_credential_after_a_relative_path_that_stays_shows_in_a_case_id(
    case: str, shown: str, drops: bool, name: str
) -> None:
    assert model.public_case(case) == shown
    assert model.public_case_drops(case) == (shown, drops)
    assert api.CaseNames(NAME_KEY).names([case], "a test", "advice") == {case: name}
    for word in ("zqa", "zqb", "zqd1", "zqd2"):
        assert word not in name


# A relative path in the query of an address after a host, whose query parameter ends at a
# blank and a mark, or holds the local path of an address: as (the text, how a case id shows
# it, how a free text shows it). A query parameter that climbs out of its folder is cut whole,
# so the path after the mark is read with the rest of the address and shows ``/`` and its last
# part. One that stays inside its folder is cut whole so in a case id only; a free text reads
# the words after its blank again and cuts that path to its last part.
CASE_WHOLE = (
    (
        "https://localhost/a?k=../../zqd1/f &/zqd1/zqd2/x",
        "https://localhost/a?k=f &/x",
        "https://localhost/a?k=f &/x",
    ),
    (
        "https://localhost/a?k=../../zqd1/f &~zqd2/x",
        "https://localhost/a?k=f &x",
        "https://localhost/a?k=f &x",
    ),
    (
        "https://localhost/a?k=../../zqd1/f\t&/zqd1/zqd2/x",
        "https://localhost/a?k=f\t&/x",
        "https://localhost/a?k=f\t&/x",
    ),
    (
        "https://localhost/a?k=../../zqd1/f ?/zqd1/zqd2/x",
        "https://localhost/a?k=f ?/x",
        "https://localhost/a?k=f ?/x",
    ),
    (
        "https://localhost/a?k=../../zqd1/f #/zqd1/zqd2/x",
        "https://localhost/a?k=f #/x",
        "https://localhost/a?k=f #/x",
    ),
    (
        "https://localhost/a=../../zqd1/f &/zqd1/zqd2/x",
        "https://localhost/a=f &/x",
        "https://localhost/a=f &/x",
    ),
    (
        "https://localhost/a?k=x/../y &/zqd1/zqd2/x",
        "https://localhost/a?k=/x/../y &/x",
        "https://localhost/a?k=x/../y &/x",
    ),
    (
        "test_get[https://localhost/a?k=../../zqd1/f &/zqd1/zqd2/x]",
        "test_get[https://localhost/a?k=f &/x]",
        "test_get[https://localhost/a?k=f &/x]",
    ),
    (
        "test_get[https://localhost/a?k=x/../y &/zqd1/zqd2/x]",
        "test_get[https://localhost/a?k=/x/../y &/x]",
        "test_get[https://localhost/a?k=x/../y &/x]",
    ),
    # A climbing path whose last folder comes right before the local path of an address.
    (
        "https://localhost/a?k=../../zqd1/zqd2:///a/x",
        "https://localhost/a?k=x",
        "https://localhost/a?k=x",
    ),
    (
        "test_get[https://localhost/a?k=../../zqd1/zqd2:///a/x]",
        "test_get[https://localhost/a?k=x]",
        "test_get[https://localhost/a?k=x]",
    ),
    # A query parameter that climbs out of its folder in ``..`` parts right before its mark.
    (
        "https://localhost/a?k=zqd1/../../&j=1",
        "https://localhost/a?k=..&j=1",
        "https://localhost/a?k=..&j=1",
    ),
    (
        "https://localhost/a?k=zqd1/../..&j=1",
        "https://localhost/a?k=..&j=1",
        "https://localhost/a?k=..&j=1",
    ),
    (
        "x://?zqd1/../../&j=1",
        "x://?..&j=1",
        "x://?..&j=1",
    ),
    (
        "http://localhost/v1?up=../..&w=1",
        "http://localhost/v1?up=..&w=1",
        "http://localhost/v1?up=..&w=1",
    ),
    (
        "http://localhost/v1#a/b#../..&w=1",
        "http://localhost/v1#a/b#..&w=1",
        "http://localhost/v1#a/b#..&w=1",
    ),
)


@pytest.mark.parametrize(("text", "case_shown", "text_shown"), CASE_WHOLE)
def test_a_case_id_cuts_a_query_parameter_that_ends_at_a_blank_or_a_local_path_whole(
    text: str, case_shown: str, text_shown: str
) -> None:
    assert model.public_case(text) == case_shown
    assert model.public_text(text) == text_shown
    assert model.public_command(("tool", text)) == shlex.join(["tool", text_shown])


# A relative path that stays in its folder, in a query parameter that holds a blank no path runs
# on over, after a host name, a port number or an empty host: the parameter is kept as typed
# from the blank to its end, and a path in a later parameter is cut, in a word of its own,
# inside 'sh -c' and after '--opt='. As (the address, what the shown command shows of it, what a
# free text shows of it).
STAY_BLANK = (
    (
        "postgresql://made-up.example/db?k=a/../b x/../&host=/zqd1/zqd2/ca.pem",
        "postgresql://<hidden>/db?k=a/../b x/../&host=/ca.pem",
        "postgresql://made-up.example/db?k=a/../b x/../&host=/ca.pem",
    ),
    (
        "postgresql://made-up.example/db?k=a/../b x/../&host=~zqd1/zqd2/ca.pem",
        "postgresql://<hidden>/db?k=a/../b x/../&host=ca.pem",
        "postgresql://made-up.example/db?k=a/../b x/../&host=ca.pem",
    ),
    (
        "postgresql://made-up.example:5432/db?k=a/../b\tx/../&j=../../zqd1/zqd2/ca.pem",
        "postgresql://<hidden>:5432/db?k=a/../b\tx/../&j=ca.pem",
        "postgresql://made-up.example:5432/db?k=a/../b\tx/../&j=ca.pem",
    ),
    (
        "ws://made-up.example/x?path=a/../c s&k=a/../b:/zqd1/zqd2/l.txt",
        "ws://<hidden>/x?path=a/../c s&k=a/../b:/l.txt",
        "ws://made-up.example/x?path=a/../c s&k=a/../b:/l.txt",
    ),
    (
        "redis://#a/../l.sock\tb/../&/zqd1/zqd2/d",
        "redis://#a/../l.sock\tb/../&/d",
        "redis://#a/../l.sock\tb/../&/d",
    ),
    (
        "http://?a/../l.sock\tb/../?/zqd1/zqd2/w",
        "http://?a/../l.sock\tb/../?/w",
        "http://?a/../l.sock\tb/../?/w",
    ),
    (
        "ws://@made-up.example/../l.sock\tb/../&/zqd1/zqd2/d",
        "ws://<hidden>@<hidden>/../l.sock\tb/../&/d",
        "ws://<hidden>@made-up.example/../l.sock\tb/../&/d",
    ),
)


@pytest.mark.parametrize(("address", "shown", "text_shown"), STAY_BLANK)
def test_a_staying_query_parameter_with_a_blank_leaves_the_paths_after_it_cut(
    address: str, shown: str, text_shown: str
) -> None:
    assert model.public_command(("psql", address)) == shlex.join(["psql", shown])
    assert model.public_command(("sh", "-c", f"psql '{address}' && echo ok")) == shlex.join(
        ["sh", "-c", f"psql '{shown}' && echo ok"]
    )
    assert model.public_command(("tool", f"--url={address}")) == shlex.join(
        ["tool", f"--url={shown}"]
    )
    assert model.public_text(f"open {address} now") == f"open {text_shown} now"
    assert not any(folder in shown or folder in text_shown for folder in FOLDERS)


# A local address nested in the query of an address with no host ends at the next query
# parameter, and one that holds another address, or a climbing path that does, is kept as typed:
# the shown command hides the host of the other address, in a word of its own and inside
# 'sh -c'. As (the address, what the shown command shows of it).
INTO_ADDRESS = (
    (
        "postgresql:///db?sslrootcert=file:///zqd1/zqd2/ca.pem&replica=https://made-up.example",
        "postgresql:///db?sslrootcert=file://ca.pem&replica=https://<hidden>",
    ),
    (
        "postgresql:///db?sslrootcert=file:///zqd1/zqd2/ca.pem"
        "&replica=postgresql://made-up.example:5432?sslmode=require",
        "postgresql:///db?sslrootcert=file://ca.pem"
        "&replica=postgresql://<hidden>:5432?sslmode=require",
    ),
    (
        "postgresql:///db?c=unix:///zqd1/zqd2/s.sock&next=https://made-up.example",
        "postgresql:///db?c=unix:///s.sock&next=https://<hidden>",
    ),
    (
        "postgresql:///db?sslrootcert=file:///zqd1/zqd2/ca.pem,https://made-up.example",
        "postgresql:///db?sslrootcert=file://ca.pem,https://<hidden>",
    ),
    (
        "postgresql:///db?c=file:///zqd1/zqd2/ca.pem&k=x/y",
        "postgresql:///db?c=file://ca.pem&k=x/y",
    ),
    (
        "postgresql:///db?c=../zqk1/s3://u:pw@made-up.example/x",
        "postgresql:///db?c=../zqk1/s3://<hidden>@<hidden>/x",
    ),
    ("mysql:///db#../zqk1/s3://made-up.example/?y", "mysql:///db#../zqk1/s3://<hidden>/?y"),
    (
        "mysql://localhost:/db?k=../zqk1=s3://made-up.example/?y",
        "mysql://localhost:/db?k=../zqk1=s3://<hidden>/?y",
    ),
    ("mysql:///db?k=../zqk1/s3://[fd00::9]/y", "mysql:///db?k=../zqk1/s3://<hidden>/y"),
    # A relative path that stays in its folder after a host name, with another address in its
    # query parameter: the parameter shows whole, the host hidden.
    ("s://#a/../:/x://hQ00676x", "s://#/a/../:/x://<hidden>"),
    # A cut that leaves what stands before an '@' to be read as a user part: it is hidden with
    # the host after it.
    (":///?e://hQ00001x=../a/b&x@c", ":///?e://<hidden>@<hidden>"),
    (":///?e://hQ05352x?../@Q", ":///?e://<hidden>@<hidden>"),
    ("s://made-up.example?~/&../@h", "s://<hidden>@<hidden>"),
    (":///#file:///.&@Q://dQ34596x", ":///#file://<hidden>@<hidden>://<hidden>"),
    ("unix://?file:///b;/Q,s://hQ06582x", "unix:///?file://b;Q,s://<hidden>"),
    # A nested path that holds a blank is kept as typed, and the paths in it are read as the
    # address's own.
    (":///?unix://:/dQ39457x x/Q", ":///?unix:///:/Q"),
    (":///?../x =/dQ05706x#/d", ":///?../x =d"),
)


@pytest.mark.parametrize(("address", "shown"), INTO_ADDRESS)
def test_a_nested_path_that_runs_into_another_address_leaves_its_host_hidden(
    address: str, shown: str
) -> None:
    assert model.public_command(("psql", address)) == shlex.join(["psql", shown])
    assert model.public_command(("sh", "-c", f"psql '{address}' && echo ok")) == shlex.join(
        ["sh", "-c", f"psql '{shown}' && echo ok"]
    )


# A nested path that a random-looking run reaches into is kept as typed, so the shown command
# hides the run as it does in the typed text, and so is the query parameter of a relative path
# that stays in its folder in a case id. As (the address, what the shown command shows of it).
RANDOM_RUN = (
    ("s://?a/../=~4411x/dQ36307x/dQ36308x/dQ36309x", "s://?/a/../=~<hidden>"),
    (":///?k=../a/~4411x/dQ36307x/dQ36308x/dQ36309x", ":///?k=../a/~<hidden>"),
    ("unix://?unix://:5432//dQ27812x/dQ27813x/dQ27814x", "unix:///?unix:///:<hidden>"),
)
# As (a case id, how it shows).
CASE_RANDOM_RUN = (
    (
        "test_conn[s://?a/../=~4411x/dQ36307x/dQ36308x/dQ36309x]",
        "test_conn[s://?/a/../=~<hidden>]",
    ),
    (
        "test_conn[:///?a/../:~994x/dQ24235x/dQ24236x/dQ24237x8]",
        "test_conn[:///?a/../:~<hidden>]",
    ),
    # A relative path that stays in its folder and runs on over a blank: the paths in it are
    # read as the id's own.
    ("test_conn[:///?a/../=/ =/#dQ08636x/Q]", "test_conn[:///?a/../=/ =Q]"),
)


@pytest.mark.parametrize(("address", "shown"), RANDOM_RUN)
def test_a_nested_path_with_a_random_looking_run_in_it_is_kept_and_the_run_hidden(
    address: str, shown: str
) -> None:
    assert model.public_command(("psql", address)) == shlex.join(["psql", shown])


@pytest.mark.parametrize(("case", "shown"), CASE_RANDOM_RUN)
def test_a_case_id_keeps_a_relative_path_with_a_random_looking_run_in_it(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown


# A nested path whose folder looks random: the shown command and the hash hide the run whole.
RANDOM_FOLDER = "Zq8f3kQ2xT9vLp4mW7nB5cY1"


@pytest.mark.parametrize(
    "address",
    [
        f"postgresql:///bench?k=file:///zqd1/{RANDOM_FOLDER}/ca.pem",
        f"postgresql:///bench?k=../zqd1/{RANDOM_FOLDER}/ca.pem",
        f"mysql://localhost:/bench?k=../../zqd1/{RANDOM_FOLDER}/ca.pem",
    ],
)
def test_a_random_looking_folder_of_a_nested_path_is_hidden_in_the_command_and_the_hash(
    address: str,
) -> None:
    shown = str(model.public_command(("psql", address)))
    hashed = model.hashed_argv(("psql", address))[1]

    assert RANDOM_FOLDER not in shown
    assert RANDOM_FOLDER not in hashed
    assert model.HIDDEN in hashed


# The lengths timed: one address of each shape, and one eight times as long.
SHORT = 16_000
LONG = 128_000
# The longest one cleaner may take on the long address, in seconds of CPU.
LONG_LIMIT_S = 1.0
# How many times as long the long address may take as the short one: eight times as long is
# in proportion, and sixty-four times would be the square.
RATIO_LIMIT = 24.0
# A time shorter than this is read as this long, so that the timer's grain makes no ratio.
TIMER_GRAIN_S = 0.002
TRIES = 3
# The longest the process that times one test may take, in seconds on the clock of the wall.
TIME_LIMIT_S = 60

# Addresses of one piece repeated, as (what stands before, the piece, what the shown command
# holds of each piece).
SHAPES: dict[str, tuple[str, str, str]] = {
    "climbing paths in a query": ("postgresql:///db?", "k=../a/b&", "k=b&"),
    "local addresses in queries": ("postgresql:///db", "?k=file:///a/b", "?k=file://b"),
    "local addresses after an empty port": (
        "mysql://localhost:/db",
        "?k=file:///a/b",
        "?k=file://b",
    ),
    "relative paths that stay in their folder": ("postgresql:///db?k=", "a/../b=", "a/../b="),
    "paths after a staying query parameter with a blank": (
        "postgresql://localhost/db?k=a/../b x/../",
        "&j=/a/b",
        "&j=/b",
    ),
}
# A relative path that stays in its folder, with an absolute path in it after a mark, after no
# host and after a host: only the last part of the last such path is shown.
INSIDE_SHAPES = {
    "no host": ("postgresql:///db?k=", "a/../b:/c/d="),
    "a host": ("postgresql://localhost/db?k=", "a/../b:/c/d="),
}


def _psql(arg: str) -> str:
    return str(model.public_command(("psql", arg)))


TIMED: dict[str, Callable[[str], str]] = {
    "public_command": _psql,
    "public_text": model.public_text,
    "public_case": model.public_case,
}
# The cleaners timed on the addresses of the shapes above.
SHOWN_TIMED = ("public_command", "public_text")


def _shaped(shape: str, length: int) -> tuple[str, str]:
    """An address of ``shape`` about ``length`` long, and what a free text shows of it."""
    before, piece, cut = SHAPES[shape]
    count = (length - len(before)) // len(piece)
    return before + piece * count, before + cut * count


def _expected(name: str, shown: str) -> str:
    return shlex.join(["psql", shown]) if name == "public_command" else shown


@pytest.mark.parametrize("name", SHOWN_TIMED)
@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_long_address_with_nested_paths_is_cleaned_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    (short, short_shown), (long, long_shown) = _shaped(shape, SHORT), _shaped(shape, LONG)
    answers = cpu_times([(name, short), (name, long)], TRIES, 4 * LONG_LIMIT_S, TIME_LIMIT_S)
    (short_s, short_text), (long_s, long_text) = answers

    assert short_text == _expected(name, short_shown)
    assert long_text == _expected(name, long_shown)
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize("name", SHOWN_TIMED)
@pytest.mark.parametrize("outer", list(INSIDE_SHAPES))
def test_a_long_relative_path_with_absolute_paths_in_it_is_cleaned_in_proportion_to_its_length(
    name: str, outer: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    before, piece = INSIDE_SHAPES[outer]
    short, long = (before + piece * ((n - len(before)) // len(piece)) for n in (SHORT, LONG))
    answers = cpu_times([(name, short), (name, long)], TRIES, 4 * LONG_LIMIT_S, TIME_LIMIT_S)
    (short_s, short_text), (long_s, long_text) = answers

    assert short_text == _expected(name, before + "a/../b:/d=")
    assert long_text == _expected(name, before + "a/../b:/d=")
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# Addresses after a host, each with a relative path that stays inside its folder in a query
# parameter that ends at a blank and a mark, as (the piece repeated, what a case id shows of
# each piece): a case id cuts each such query parameter whole.
CASE_WHOLE_PIECE = ("https://localhost/a?k=c/../d &/e/f ", "https://localhost/a?k=/c/../d &/f ")


def test_a_long_case_id_with_query_parameters_cut_whole_is_cleaned_in_proportion_to_its_length(
    cpu_times: Callable[..., list[tuple[float, str]]],
) -> None:
    piece, cut = CASE_WHOLE_PIECE
    short, long = (piece * (n // len(piece)) for n in (SHORT, LONG))
    calls = [("public_case", short), ("public_case", long)]
    answers = cpu_times(calls, TRIES, 4 * LONG_LIMIT_S, TIME_LIMIT_S)
    (short_s, short_text), (long_s, long_text) = answers

    assert short_text == cut * (SHORT // len(piece))
    assert long_text == cut * (LONG // len(piece))
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT
