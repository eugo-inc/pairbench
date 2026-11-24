# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the paths and values in an address that the shown command shows.

A relative path that stays inside its folder (``x/../y``) is kept as typed to the end of its
word, so a path after it in the same word keeps its folders; in the query of an address it ends
with its query parameter, where a climbing path after it is read with it as one path, and after
a ``;``, a comma, a bracket or a quote in the query, in the query of an address with a bracket
in its path and in the query of an address with two hosts or more the words are read as any
others. A case id keeps such a path as typed with an
absolute path right after it and a ``:``, ``=`` or ``@``, so that path keeps its folders, with
no host before them, after an empty port and after an earlier path in the query, and after a
single host, with no path and no such mark before it in the query, shows the query parameter
of such a path whole, with a ``/`` before it. The config reference says so for a case id too.
In an
address with two hosts or more, the hosts after a port or after a host in brackets show, and so
does a host in brackets after the first; a credential after a second ``?`` is read as a part of
the value before it. The security policy lists each among the known limits of the shown command
with the advice, and the config reference points to the first. Each example is read through
the shown command or as a case id here, and so is each form the entries name, shown and cut, so
a change to the code or to the text that parts them fails a row. Every folder name, host and
value here is made up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A path after a relative path that stays inside its folder.** A relative path with `..` "
    "parts that stays inside its folder, such as `x/../y` or `lib/../lib`, is kept as typed to "
    "the end of its word, so a path that follows it in the same word shows its folders: "
    "`tool --path=lib/../lib:/made/up/lib` shows whole. In the query of an address such a path "
    "ends with its query parameter, and a path that starts at one `/` or at `~`, or a local "
    "address, after it is cut: `psql 'postgresql://db.example/db?k=a/../b:/made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?k=a/../b:/ca.pem'`. After a host name or a port number, "
    "with a path after it or none, and after an empty host, an empty port, a user, a host and an "
    "empty port or a host in brackets with no path after it, right before the query or the "
    "fragment, as in `postgresql://?k=x`, `postgresql://:?k=x`, `postgresql://@:?k=x`, "
    "`postgresql://db.example:?k=x` and `postgresql://[::1]?k=x`, the words after a blank in "
    "such a query parameter that no path runs on over are kept as typed to its end, so a path "
    "there shows its folders, and a path in a later parameter is cut. They are cut with a path "
    "after anything else, as in `postgresql:///db?k=x`, which has no host, "
    "`postgresql://[::1]/db?k=x` and `postgresql://db.example:/db?k=x`, with a path in a "
    "`file://` address, or one whose scheme ends in `file`, in a `unix://` address, or one whose "
    "scheme ends in `+unix`, with no user, host in brackets or socket path written with `%2F` "
    "before the query or the fragment, as in `unix://?k=x`, and in the shown command after a "
    "scheme of one letter, as in `x://?k=x`. After a host in brackets in such a `unix://` "
    "address, as in `unix://[::1]?k=x`, a path in a later parameter shows too: "
    "`psql 'postgresql://db.example/db?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem'`. A word and two `/` "
    "after it are read as an address with a host, whose path shows: "
    "`psql 'postgresql:///db?k=a/../b://made/up/ca.pem'` shows "
    "`psql 'postgresql:///db?k=a/../b://<hidden>/up/ca.pem'`. A climbing path after it in the same "
    "query parameter is read with it as one path, in which `b:..` is a folder, so its folders "
    "show unless that one path climbs out of its folder: "
    "`psql 'postgresql://db.example/db?k=a/../b:../../made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?k=a/../b:../../made/up/ca.pem'`, and "
    "`psql 'postgresql:///db?k=a/../b:./../made/up/ca.pem'` shows whole, while "
    "`psql 'postgresql://db.example/db?k=a/../b:../../../made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?k=ca.pem'`. After a `;`, a comma, a bracket or a "
    "quote in the query, in the query of an address with a bracket in its path, and in the query "
    "of an address with two hosts or more, the words are read as any others, so a path that "
    "follows such a path there shows its folders, a local address and a climbing path too: "
    "`psql 'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'` shows whole, "
    "`psql 'postgresql:///a[b]?k=a/../b&j=/made/up/ca.pem'` shows whole, and "
    "`psql 'postgresql://db1.example,db2.example/db?a=b/../c&sslrootcert=../../made/up/ca.pem'` "
    "shows `psql 'postgresql://<hidden>/db?a=b/../c&sslrootcert=../../made/up/ca.pem'`. With no "
    "such path before it, a path there is cut: "
    "`psql 'postgresql:///db?a=b;sslrootcert=file:///made/up/ca.pem'` shows "
    "`psql 'postgresql:///db?a=b;sslrootcert=file://ca.pem'`. After the same hosts, and cut "
    "where those words are cut except after a scheme of one letter, a query parameter of such a "
    "path that holds an address with a host shows whole, with a `/` put before it, or with none "
    "after a host in brackets in a `unix://` address: "
    "`psql 'postgresql://db.example/db?k=a/../b:/made/up/x/s3://db2.example/y'` shows "
    "`psql 'postgresql://<hidden>/db?k=/a/../b:/made/up/x/s3://<hidden>/y'`. A case id keeps "
    "such a path as typed with an absolute path right after it and a `:`, `=` or `@`, so that "
    "path shows its folders, and reads a climbing path after it with it as one path, as the "
    "shown command does, with no host before them, after a host and an empty port, and after an "
    "earlier path in the query of an address with one host: "
    "`test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]` and "
    "`test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]` show whole. In a case id, after a "
    "single host, with a "
    "port number or none, in brackets or not, and with no path, `;`, comma, bracket or quote "
    "before it in the query or the fragment, the query parameter of such a path shows whole, "
    "with a `/` put before it, so a path after it in that parameter shows its folders: "
    "`test_conn[postgresql://db.example/db?k=a/../b:/made/up/ca.pem]` shows "
    "`test_conn[postgresql://db.example/db?k=/a/../b:/made/up/ca.pem]`."
)
INTO_LIMIT = (
    "**A local address or a climbing path that runs into another address.** In the query or the "
    "fragment of an address with no host, a host and an empty port, a host in brackets with no "
    "port, a `unix://` socket, the path of a `file://` address or an earlier path in the query "
    "before it, a local address ends at the next `&`, `?` or `#`. One that holds a blank before "
    "then followed by a word with a `/`, which the path runs on over as it does over the words of "
    "a folder named in words, or that holds another address before then, or a value that looks "
    "random, shows as typed, with that value hidden, and so does a climbing path that holds such a "
    "blank and word before the next `&`, `?` or `#`, another address or such a value, so the host "
    "of the other address is hidden: `psql 'postgresql:///db?c=../made/up/s3://db.example/x'` "
    "shows `psql 'postgresql:///db?c=../made/up/s3://<hidden>/x'`, and `psql "
    "'postgresql:///db?sslrootcert=file:///made/Zq Files/ca.pem'` shows whole. A blank with no "
    "such word after it ends the path, which is cut: `psql "
    "'postgresql:///db?sslrootcert=file:///made/up/ca.pem fast'` shows `psql "
    "'postgresql:///db?sslrootcert=file://ca.pem fast'`. After a host name or a port number, with "
    "no path before it in the query, a local address there ends at the next `?` or `#` only, so an "
    "address after it in the same query is read as a part of its path, whose last part shows that "
    "address's host: `psql "
    "'postgresql://db.example/db?c=unix:///made/up/s.sock&next=https://db2.example:443?x'` shows "
    "`psql 'postgresql://<hidden>/db?c=unix:///db2.example:443?x'`."
)
HOST_LIMIT = (
    "**A host after a port or a host in brackets.** In an address with two hosts or more, the "
    "hosts after a port show, and so do the hosts after a host in brackets and a host in "
    "brackets after the first: `psql 'postgresql://db1.example:5432,db2.example:5433/db'` shows "
    "`psql 'postgresql://<hidden>:5432,db2.example:5433/db'`, "
    "`psql 'postgresql://[fd00::1],db2.example:5433/db'` shows "
    "`psql 'postgresql://<hidden>,db2.example:5433/db'`, and "
    "`psql 'postgresql://db1.example,[fd00::2]:5433/db'` shows "
    "`psql 'postgresql://<hidden>[fd00::2]:5433/db'`. Host names with a port on the last host "
    "only are hidden together: `psql 'postgresql://db1.example,db2.example:5433/db'` shows "
    "`psql 'postgresql://<hidden>:5433/db'`."
)
QUERY_LIMIT = (
    "**A credential after a second `?` in an address.** In the query of an address, a `?` inside "
    "a value starts no parameter, so a credential after it is read as a part of that value and "
    "is not hidden: `curl 'https://made-up.example/v1?next=/a?token=made-up'` shows "
    "`curl 'https://<hidden>/v1?next=/a?token=made-up'`. Written before that value, it is "
    "hidden: `curl 'https://made-up.example/v1?token=made-up&next=/a?b'` shows "
    "`curl 'https://<hidden>/v1?token=<hidden>&next=/a?b'`."
)
ADVICE = (
    "Write a relative path that stays inside its folder without `..` parts "
    "(`--path=lib:/made/up/lib` shows `--path=lib:lib`), give an address with two hosts or more "
    "host names, none in brackets, and a port on the last host only, and write a credential in "
    "the query of an address before any value that holds a `?`."
)
POINTER = (
    "docs/reference/config.md",
    "So do the folders of a path that follows a relative path that stays inside its folder in "
    "the same word, as in `--path=lib/../lib:/made/up/lib`; in the query of an address, only "
    "those of a climbing path read with it as one path in its query parameter "
    "(`postgresql:///db?k=a/../b:../../made/up/ca.pem` shows whole), those of a query parameter "
    "that holds an address with a host, and those of a path after a blank in such a query "
    "parameter that no path runs on over, after a host name or a port number, or after an empty "
    "host, an empty port, a user, a host and an empty port or a host in brackets with no path "
    "after it, right before the query or the fragment (`postgresql://?k=x` or "
    "`postgresql://[::1]?k=x`, not `postgresql:///db?k=x`, which has no host, nor "
    "`postgresql://[::1]/db?k=x`), but for the forms the known limits name as cut, and those of "
    "any path "
    "after a `;`, a comma, a bracket or a quote, or with two hosts or more "
    "(`postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem` shows whole), as the known "
    "limits say too.",
)
# The config reference's sentence on a case id, after the pointer, and its examples: the id and
# how it shows.
CASE_POINTER = (
    "A case id cuts a local address and a climbing path there when no relative path that stays "
    "inside its folder stands before them in the query, one that runs into another address "
    "included (`test_conn[postgresql:///db?c=../made/up/s3://db.example/x]` shows "
    "`test_conn[postgresql:///db?c=x]`). In the query of an address with one host or none it "
    "shows the folders of an absolute path right after such a relative path and a `:`, `=` or "
    "`@` (`test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]` shows whole), as the known "
    "limits say."
)
CASE_POINTER_EXAMPLES = (
    (
        "test_conn[postgresql:///db?c=../made/up/s3://db.example/x]",
        "test_conn[postgresql:///db?c=x]",
    ),
    (
        "test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]",
    ),
)
# Each entry's examples of the shown command: the entry, a command as typed and as it shows.
EXAMPLES = (
    (LIMIT, "tool --path=lib/../lib:/made/up/lib", "tool --path=lib/../lib:/made/up/lib"),
    (
        LIMIT,
        "psql 'postgresql://db.example/db?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql://db.example/db?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql:///db?k=a/../b://made/up/ca.pem'",
        "psql 'postgresql:///db?k=a/../b://<hidden>/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql://db.example/db?k=a/../b:../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:../../made/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql:///db?k=a/../b:./../made/up/ca.pem'",
        "psql 'postgresql:///db?k=a/../b:./../made/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql://db.example/db?k=a/../b:../../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql:///a[b]?k=a/../b&j=/made/up/ca.pem'",
        "psql 'postgresql:///a[b]?k=a/../b&j=/made/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql://db1.example,db2.example/db?a=b/../c&sslrootcert=../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b/../c&sslrootcert=../../made/up/ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql:///db?a=b;sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;sslrootcert=file://ca.pem'",
    ),
    (
        LIMIT,
        "psql 'postgresql://db.example/db?k=a/../b:/made/up/x/s3://db2.example/y'",
        "psql 'postgresql://<hidden>/db?k=/a/../b:/made/up/x/s3://<hidden>/y'",
    ),
    (
        INTO_LIMIT,
        "psql 'postgresql:///db?c=../made/up/s3://db.example/x'",
        "psql 'postgresql:///db?c=../made/up/s3://<hidden>/x'",
    ),
    (
        INTO_LIMIT,
        "psql 'postgresql:///db?sslrootcert=file:///made/Zq Files/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=file:///made/Zq Files/ca.pem'",
    ),
    (
        INTO_LIMIT,
        "psql 'postgresql:///db?sslrootcert=file:///made/up/ca.pem fast'",
        "psql 'postgresql:///db?sslrootcert=file://ca.pem fast'",
    ),
    (
        INTO_LIMIT,
        "psql 'postgresql://db.example/db?c=unix:///made/up/s.sock&next=https://db2.example:443?x'",
        "psql 'postgresql://<hidden>/db?c=unix:///db2.example:443?x'",
    ),
    (
        HOST_LIMIT,
        "psql 'postgresql://db1.example:5432,db2.example:5433/db'",
        "psql 'postgresql://<hidden>:5432,db2.example:5433/db'",
    ),
    (
        HOST_LIMIT,
        "psql 'postgresql://[fd00::1],db2.example:5433/db'",
        "psql 'postgresql://<hidden>,db2.example:5433/db'",
    ),
    (
        HOST_LIMIT,
        "psql 'postgresql://db1.example,[fd00::2]:5433/db'",
        "psql 'postgresql://<hidden>[fd00::2]:5433/db'",
    ),
    (
        HOST_LIMIT,
        "psql 'postgresql://db1.example,db2.example:5433/db'",
        "psql 'postgresql://<hidden>:5433/db'",
    ),
    (
        QUERY_LIMIT,
        "curl 'https://made-up.example/v1?next=/a?token=made-up'",
        "curl 'https://<hidden>/v1?next=/a?token=made-up'",
    ),
    (
        QUERY_LIMIT,
        "curl 'https://made-up.example/v1?token=made-up&next=/a?b'",
        "curl 'https://<hidden>/v1?token=<hidden>&next=/a?b'",
    ),
)
# The first entry's examples of a case id that shows whole.
CASE_WHOLE_EXAMPLES = (
    "test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]",
    "test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]",
)
# The first entry's example of a case id whose query parameter shows whole after a host, with a
# `/` put before it: the id and how it shows.
CASE_SLASH_EXAMPLES = (
    (
        "test_conn[postgresql://db.example/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:/made/up/ca.pem]",
    ),
)
# The advice's example: the option as typed and as it shows.
ADVICE_EXAMPLE = ("--path=lib:/made/up/lib", "--path=lib:lib")
# The examples of the config reference, which show whole.
POINTER_EXAMPLES = (
    "postgresql:///db?k=a/../b:../../made/up/ca.pem",
    "postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem",
)
# Each form the first entry names as one whose folders show: in the query of an address with a
# bracket in its path, a climbing path, a local address and an absolute path after such a path,
# with no host and after a host; then a path after a relative path that
# stays inside its folder in one word, outside an address, after a ';', a comma or a bracket in
# a query, with or without a host, and in the query of an address with two hosts; bare, in
# 'sh -c', after '--opt=' and after 'NAME='. A climbing path read with such a path as one path
# in its query parameter, after a host, in a fragment, after an empty port, after a host in
# brackets and with no host. A path in a later query parameter after a blank in the query
# parameter of such a path, after a host in brackets with no port and after a host and an empty
# port. Then the hosts after a port, with three hosts, and the hosts after a host in brackets
# and a host in brackets after the first, with a port or none.
KEPT = (
    ("tool x/../y:/made/up/lib", "tool x/../y:/made/up/lib"),
    (
        "psql 'postgresql:///a[b]?k=a/../b&j=../../made/up/ca.pem'",
        "psql 'postgresql:///a[b]?k=a/../b&j=../../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql:///a[b]?k=a/../b&j=file:///made/up/ca.pem'",
        "psql 'postgresql:///a[b]?k=a/../b&j=file:///made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/a]b?k=a/../b&j=/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/a]b?k=a/../b&j=/made/up/ca.pem'",
    ),
    (
        "psql 'postgresql:///a[b]?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql:///a[b]?k=a/../b:/made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://[fd00::1]/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b x/../&j=/made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example:/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://<hidden>:/db?k=a/../b x/../&j=/made/up/ca.pem'",
    ),
    ("tool 'k=x/../y&j=/made/up/ca.pem'", "tool 'k=x/../y&j=/made/up/ca.pem'"),
    (
        "psql 'postgresql:///db?a=b;k=x/../y&j=../../made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;k=x/../y&j=../../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql:///db?a=b;k=x/../y:/made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;k=x/../y:/made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example/db?a=b/../c&sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b/../c&sslrootcert=file:///made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example/db?a=b/../c:/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b/../c:/made/up/ca.pem'",
    ),
    (
        "sh -c \"psql 'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'\"",
        "sh -c 'psql '\"'\"'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'\"'\"''",
    ),
    (
        "tool '--url=postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
        "tool '--url=postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'",
    ),
    (
        "env 'DB=postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem' tool",
        "env 'DB=postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem' tool",
    ),
    (
        "psql 'postgresql://db.example/db?a=1,k=x/../y&j=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=1,k=x/../y&j=file:///made/up/ca.pem'",
    ),
    (
        "psql 'postgresql:///db?a=1(k=x/../y&j=../../made/up/ca.pem'",
        "psql 'postgresql:///db?a=1(k=x/../y&j=../../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?k=a/../b:../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db#a/../b:../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db#a/../b:../../made/up/ca.pem'",
    ),
    (
        "psql 'mysql://db.example:/db?k=a/../b:./../made/up/ca.pem'",
        "psql 'mysql://<hidden>:/db?k=a/../b:./../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://[fd00::1]/db?k=a/../b:../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:../../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql:///db?k=lib/../lib:../made/up/lib&j=1'",
        "psql 'postgresql:///db?k=lib/../lib:../made/up/lib&j=1'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example:5433,db3.example:5434/db'",
        "psql 'postgresql://<hidden>:5433,db3.example:5434/db'",
    ),
    (
        "psql 'postgresql://[fd00::1],db2.example/db'",
        "psql 'postgresql://<hidden>,db2.example/db'",
    ),
    (
        "psql 'postgresql://[fd00::1]:5432,db2.example/db'",
        "psql 'postgresql://<hidden>:5432,db2.example/db'",
    ),
    (
        "psql 'postgresql://[fd00::1],[fd00::2]:5433/db'",
        "psql 'postgresql://<hidden>,[fd00::2]:5433/db'",
    ),
    (
        "psql 'postgresql://[fd00::1],db2.example,db3.example:5434/db'",
        "psql 'postgresql://<hidden>,db2.example,db3.example:5434/db'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example,[fd00::3]:5434/db'",
        "psql 'postgresql://<hidden>[fd00::3]:5434/db'",
    ),
)
# Each form of a case id the first entry names as one whose folders show: a climbing path read
# with such a path as one path, with no host and after a host; and after a single host, with a
# port or none, in brackets and in a fragment, the query parameter of such a path, whatever
# follows the path in it: an address with three `/` after its `:` or a `file://` address with a
# host, a word after a blank, with a `&`, a `?` or a `#` or none, that the path runs on over or
# not, an absolute path, a `file:` address with one `/`, or nothing. Then a path after such a
# path read as any other word, with two hosts and after a `;`, a comma, a bracket or a quote.
CASE_KEPT = (
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib x/y&z]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib x/y&z]",
    ),
    (
        "test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]",
        "test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:./../made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:./../made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:../../made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:../../made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://[fd00::1]:5432/db#a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://[fd00::1]:5432/db#/a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example:5432/db?a=b&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example:5432/db?a=b&k=/a/../b:/made/up/ca.pem]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib &j=1]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib &j=1]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib x &y/z]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib x &y/z]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib (&x/y)]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib (&x/y)]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:file:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:file:/made/up/ca.pem]",
    ),
    (
        'test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib "&x/y]',
        'test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib "&x/y]',
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib -&x/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib -&x/y]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib x(&/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib x(&/y]",
    ),
    (
        "test_conn[postgresql://db.example:5432/db?k=a/../b:file:///made/up/ca.pem]",
        "test_conn[postgresql://db.example:5432/db?k=/a/../b:file:///made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db#a/../b:file:///made/up/ca.pem]",
        "test_conn[postgresql://db.example/db#/a/../b:file:///made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://[fd00::1]/db?k=a/../b:file:///made/up/ca.pem]",
        "test_conn[postgresql://[fd00::1]/db?k=/a/../b:file:///made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:unix:///made/up/s.sock]",
        "test_conn[postgresql://db.example/db?k=/a/../b:unix:///made/up/s.sock]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib &/x]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib &/x]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib ?x/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib ?x/y]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib #x/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib #x/y]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib x?/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib x?/y]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib a&b/c]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib a&b/c]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib a&b c/d]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib a&b c/d]",
    ),
    (
        "test_get[https://made-up.example/v1?path=lib/../lib:/made/up/lib =&x/y]",
        "test_get[https://made-up.example/v1?path=/lib/../lib:/made/up/lib =&x/y]",
    ),
    (
        "test_conn[postgresql://db1.example,db2.example/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db1.example,db2.example/db?k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?a=b;k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=b;k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?a=b,k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=b,k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?a=(b)&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=(b)&k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?a='b'&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a='b'&k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:file://h/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:file:///made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:x:///made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=/a/../b:x:///made/up/ca.pem]",
    ),
    # An absolute path after such a path after an empty port, after an earlier path in the query
    # after a host, and with no host before a word that the path runs on over.
    (
        "test_conn[mysql://db.example:/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[mysql://db.example:/db?k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?a=/made/up&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=/up&k=a/../b:/made/up/ca.pem]",
    ),
    (
        "test_conn[postgresql:///db?k=lib/../lib:/made/up/lib &x/y]",
        "test_conn[postgresql:///db?k=lib/../lib:/made/up/lib &x/y]",
    ),
)
# The nearest forms of a case id the first entry implies as cut: a local address after such a
# path with no host and after an empty port, and a climb read with such a path as one path that
# climbs out of its folder after a host.
CASE_CUT = (
    (
        "test_conn[postgresql:///db?k=a/../b:file:///made/up/ca.pem]",
        "test_conn[postgresql:///db?k=a/../b:file://ca.pem]",
    ),
    (
        "test_conn[mysql://db.example:/db?k=a/../b:file:///made/up/ca.pem]",
        "test_conn[mysql://db.example:/db?k=a/../b:file://ca.pem]",
    ),
    (
        "test_conn[postgresql://db.example/db?k=a/../b:../../../made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?k=ca.pem]",
    ),
)
# The nearest forms the entries name or imply as cut: in the query of an address with a bracket
# in its path, a local address and a climbing path with no such path before them; a path in the
# query of an address with no host or one host, after a relative path that stays inside its
# folder or after any other path, after a ';' with no such path before it, with each outer
# form before the query; and a credential in the query of an address with two hosts and a port
# on the last only, and three hosts with a port on the last only. Then a path after such a
# path that the code reads as a path of its own, and a climb read with it as one path that
# climbs out of its folder.
CUT = (
    (
        "psql 'postgresql:///a[b]?j=file:///made/up/ca.pem'",
        "psql 'postgresql:///a[b]?j=file://ca.pem'",
    ),
    (
        "psql 'postgresql:///a[b]?j=../../made/up/ca.pem'",
        "psql 'postgresql:///a[b]?j=ca.pem'",
    ),
    (
        "psql 'postgresql:///db?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql:///db?k=a/../b:/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?k=a/../b&j=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b&j=file://ca.pem'",
    ),
    (
        "curl 'https://made-up.example/v1?path=lib/../lib&j=/made/up/lib'",
        "curl 'https://<hidden>/v1?path=lib/../lib&j=/lib'",
    ),
    (
        "psql 'postgresql:///db?a=b;k=y&j=file:///made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;k=y&j=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example/db?a=b&sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b&sslrootcert=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example/db?a=b&sslrootcert=../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=../../made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example:/db?sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>:/db?sslrootcert=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=/made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'sqlite:////made/up/db.sqlite?cert=../made/up/ca.pem'",
        "psql 'sqlite:///db.sqlite?cert=ca.pem'",
    ),
    (
        "psql 'postgresql://[fd00::1]/db?sslrootcert=./../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'unix://made/up.sock?sslrootcert=data/../../made/up/ca.pem'",
        "psql 'unix:///up.sock?sslrootcert=ca.pem'",
    ),
    (
        "psql 'file://db.example/made/up/db?sslrootcert=../made/up/ca.pem'",
        "psql 'file://db?sslrootcert=ca.pem'",
    ),
    ("psql 'postgresql:///db#../made/up/ca.pem'", "psql 'postgresql:///db#ca.pem'"),
    (
        "psql 'postgresql://db.example/db?a=//made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=~/made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=../made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=file:///made/up#../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=file://up#ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=file://localhost/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db.example:5432/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>:5432/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://bench@db.example/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>@<hidden>/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://[fd00::1]:5432/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>:5432/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db#k=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db#k=ca.pem'",
    ),
    (
        "psql 'unix://bench@made/up.sock?sslrootcert=../made/up/ca.pem'",
        "psql 'unix://<hidden>@<hidden>/up.sock?sslrootcert=ca.pem'",
    ),
    (
        "psql 'unix://[fd00::1]/db?sslrootcert=../made/up/ca.pem'",
        "psql 'unix:///[fd00::1]ca.pem'",
    ),
    (
        "psql 'postgresql:///db?a=b;sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=/made/up;sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up;sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=made/up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=file:///made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=file://ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=//made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=/ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=~/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=file:/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=file:/ca.pem'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example:5433/db?password=made-up'",
        "psql 'postgresql://<hidden>:5433/db?password=<hidden>'",
    ),
    (
        "psql 'postgresql://db1.example,db2.example,db3.example:5434/db'",
        "psql 'postgresql://<hidden>:5434/db'",
    ),
    (
        "psql 'postgresql://db.example/db?k=a/../b:~/made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?k=a/../b:file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=a/../b:file://ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?k=a/../b:x/../../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?k=ca.pem'",
    ),
    (
        "psql 'postgresql:///db?k=a/../b:../../../made/up/ca.pem'",
        "psql 'postgresql:///db?k=ca.pem'",
    ),
)


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def shown(typed: str) -> str:
    """The shown command of a command typed as a shell reads it."""
    return model.public_command(shlex.split(typed))


@pytest.mark.parametrize("entry", [LIMIT, INTO_LIMIT, HOST_LIMIT, QUERY_LIMIT])
def test_the_security_policy_lists_the_limit(repo_root: Path, entry: str) -> None:
    assert entry in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


def test_the_config_reference_points_to_the_limit(repo_root: Path) -> None:
    page, sentence = POINTER
    assert sentence in joined(repo_root, page)


@pytest.mark.parametrize(("entry", "typed", "expected"), EXAMPLES)
def test_each_example_of_a_limit_is_in_it_and_shows_as_it_says(
    entry: str, typed: str, expected: str
) -> None:
    said = f"`{typed}` shows whole" if expected == typed else f"`{typed}` shows `{expected}`"
    assert said in entry
    assert shown(typed) == expected


def test_the_case_id_examples_that_show_whole_are_in_the_limit_and_show_whole() -> None:
    first, second = CASE_WHOLE_EXAMPLES
    assert f"`{first}` and `{second}` show whole" in LIMIT
    for case in CASE_WHOLE_EXAMPLES:
        assert model.public_case(case) == case


@pytest.mark.parametrize(("case", "expected"), CASE_SLASH_EXAMPLES)
def test_each_case_id_example_whose_query_parameter_shows_whole_is_in_the_limit_and_shows(
    case: str, expected: str
) -> None:
    assert f"`{case}` shows `{expected}`" in LIMIT
    assert model.public_case(case) == expected


def test_the_config_reference_says_how_a_case_id_reads_these_paths(repo_root: Path) -> None:
    page, sentence = POINTER
    assert f"{sentence} {CASE_POINTER}" in joined(repo_root, page)


@pytest.mark.parametrize(("case", "expected"), CASE_POINTER_EXAMPLES)
def test_each_case_id_example_of_the_config_reference_is_in_it_and_shows_as_it_says(
    case: str, expected: str
) -> None:
    said = f"`{case}` shows whole" if expected == case else f"`{case}` shows `{expected}`"
    assert said in CASE_POINTER
    assert model.public_case(case) == expected


def test_the_advice_s_example_is_in_it_and_cut() -> None:
    typed, expected = ADVICE_EXAMPLE
    assert f"`{typed}` shows `{expected}`" in ADVICE
    assert model.public_command(("tool", typed)) == f"tool {expected}"


@pytest.mark.parametrize("example", POINTER_EXAMPLES)
def test_each_example_of_the_config_reference_is_in_it_and_shows_whole(example: str) -> None:
    _page, sentence = POINTER
    assert f"`{example}` shows whole" in sentence
    assert model.public_command(("psql", example)) == shlex.join(["psql", example])
    assert model.public_text(example) == example


@pytest.mark.parametrize(("typed", "expected"), KEPT)
def test_a_form_the_limit_names_shows_its_folders(typed: str, expected: str) -> None:
    assert shown(typed) == expected
    assert model.hashed_argv(shlex.split(typed)) == shlex.split(typed)


@pytest.mark.parametrize(("typed", "expected"), CUT)
def test_a_form_the_limits_name_as_cut_shows_as_said(typed: str, expected: str) -> None:
    assert shown(typed) == expected


@pytest.mark.parametrize(("case", "expected"), CASE_KEPT)
def test_a_case_id_form_the_limit_names_shows_its_folders(case: str, expected: str) -> None:
    assert model.public_case(case) == expected


@pytest.mark.parametrize(("case", "expected"), CASE_CUT)
def test_a_case_id_form_the_limit_implies_as_cut_shows_as_said(case: str, expected: str) -> None:
    assert model.public_case(case) == expected
