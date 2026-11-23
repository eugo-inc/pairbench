# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each case id here shows exactly as written, through every reader of case ids.

The ids hold addresses with relative paths that stay inside their folder or climb out of it,
local addresses, paths that start with one ``/`` or more or at ``~``, and credentials, quoted
or not, with a user name before them or none, in the query or the fragment of an address with
no host, a host, an empty port or a host in brackets, glued to each other in many ways. A case
id is read apart from the shown command: ``public_case`` gives how it shows,
``public_case_drops`` gives that and whether its cut dropped a word, and ``CaseNames`` gives its
name under a fixed key, with the mark a name gets when its cut drops a word. Each row pins all
three, so a change to how a case id is read, in a way the shown command may read these texts
too, fails a row. Every folder name, host and credential here is made up.
"""

from __future__ import annotations

import pytest

from pairbench import api, model

NAME_KEY = bytes(range(32))
# As (the id, how it shows, the mark its name gets under ``NAME_KEY``, empty when its cut drops
# no word).
ROWS = (
    (
        "t[postgresql:///db?k=a/../b:/password=/x' pwone pwtwo']",
        "t[postgresql:///db?k=a/../b:/password=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/made/up/x/s3://db.example/y",
        "postgresql:///db?k=a/../b:/made/up/x/s3://db.example/y",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/x://hostq",
        "postgresql:///db?k=a/../b:/x://hostq",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/made/x://db.example",
        "postgresql:///db?k=a/../b:/made/x://db.example",
        "",
    ),
    (
        'test_conn[k=x:///db?password=a/../b:/q1/q2../token="pwA"]',
        "test_conn[k=x:///db?password=<hidden>/../b:/q1/q2../token=<hidden>]",
        "",
    ),
    (
        "test_conn[x://h.example:/db?k=a/../b:/q1/q2/q3.pem]",
        "test_conn[x://h.example:/db?k=a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "test_conn[mysql://db.example:/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[mysql://db.example:/db?k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "psql 'postgresql://db.example:/db?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql://db.example:/db?k=a/../b:/made/up/ca.pem'",
        "",
    ),
    (
        "test_conn[postgresql:///bench?x=a/../b:/zqd1/zqd2/x]",
        "test_conn[postgresql:///bench?x=a/../b:/zqd1/zqd2/x]",
        "",
    ),
    (
        "BM_Read[file://hstqc:/dirqj#dirqk/../dirqm:/dirqn/dirqp/dirqs/leafqt.pem?token=pwdqv]",
        "BM_Read[file://dirqj#dirqk/../dirqm:/dirqn/dirqp/dirqs/leafqt.pem?token=<hidden>]",
        "",
    ),
    (
        "x.y-z://#dirqz/../: #dirqcs/../:/dirqcv/dirqcw",
        "x.y-z://#/dirqz/../: #dirqcs/../:/dirqcv/dirqcw",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/PASSWORD=/pwone&k=1]",
        "postgresql:///db?k=a/../b:/PASSWORD=<hidden>/pwone&k=1]",
        "",
    ),
    (
        "t[postgresql://[fd00::1]:/db?a/../b:/PGPASSWORD=/pwone pwtwo]",
        "t[postgresql://[fd00::1]:/db?a/../b:/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "file://[::1]:/a/../b?secret=passalphah&file=a/../b:~/passwd=/passquebeco'qvh"
        "otelb qvechoc'&secret='qvindiad qvindiae'#file=\"qvromeof qvmikeg qvechoh\"",
        "file://b?secret=<hidden>&file=a/../b:~/passwd=<hidden> qvechoc'&secret=<hidd"
        'en> qvmikeg qvechoh"',
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/made/up/x&j=s3://db.example/y",
        "postgresql:///db?k=a/../b:/made/up/x&j=s3://db.example/y",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/x/s3://hostq/y",
        "postgresql:///db?k=a/../b:/x/s3://hostq/y",
        "",
    ),
    (
        'test_x[x:///db?password=a/../b:/q1/q2../token="pwA"]',
        "test_x[x:///db?password=<hidden>/../b:/q1/q2../token=<hidden>]",
        "",
    ),
    (
        "test_conn[x:///db?k=a/../b:/q1/q2/q3.pem]",
        "test_conn[x:///db?k=a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "test_conn[postgresql://db.example/db?a=/made/up&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=/up&k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "psql 'postgresql://db.example/db?a=/made/up&k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql://db.example/db?a=/up&k=a/../b:/made/up/ca.pem'",
        "",
    ),
    (
        "ws://h.example/x?path=a/../c s&k=a/../b:/d1/d2/l.txt",
        "ws://h.example/x?path=/a/../c s&k=a/../b:/d1/d2/l.txt",
        "",
    ),
    (
        "get['postgresql:///dirqg?j=dirqh/../dirqj:/dirqk/dirqm/leafqn,next=%2Fdirqp%"
        "2Fdirqs%2Fleafqt?ssl-ca=dirqv/../dirqw://dirqz/dirqcb/leafqcc.pem') y]",
        "get['postgresql:///dirqg?j=dirqh/../dirqj:/dirqk/dirqm/leafqn,next=%2Fleafqt"
        "?ssl-ca=dirqv/../dirqw://dirqz/dirqcb/leafqcc.pem') y]",
        "",
    ),
    (
        "mongodb+srv://[]#a/../leafqk.pem\t&next/../:/dirqv/leafqcb.txt",
        "mongodb+srv://[]#/a/../leafqk.pem\t&next/../:/dirqv/leafqcb.txt",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=/pwone&k=1 tail",
        "postgresql:///db#a/../b:/secret=<hidden> tail",
        "",
    ),
    (
        "t[postgresql://h.example/db?q=/a/b&k=x/./../y:/x/token=~/pwone pwtwo]",
        "t[postgresql://h.example/db?q=/b&k=x/./../y:/x/token=<hidden> pwtwo]",
        "",
    ),
    (
        "gluhotelhsqlite://userromeod@/db?passwd=a/../b::/api_key=/folddeltao/passhot"
        "elp/passyankeeb&host='qvquebece qvtangof qvcharlieg'",
        "gluhotelhsqlite://<hidden>@/db?passwd=<hidden>",
        "",
    ),
    (
        'x:///db?password=a/../b:/q1/q2../token="pwA"',
        "x:///db?password=<hidden>/../b:/q1/q2../token=<hidden>",
        "",
    ),
    (
        "test_conn[x://h.example/db?j=/q9/q8&k=a/../b:/q1/q2/q3.pem]",
        "test_conn[x://h.example/db?j=/q8&k=a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "psql 'postgresql:///db?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql:///db?k=a/../b:/made/up/ca.pem'",
        "",
    ),
    (
        "test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "https://#dirqh/../leafqj #dirqn/../:/dirqs/dirqt",
        "https://#/dirqh/../leafqj #dirqn/../:/dirqs/dirqt",
        "",
    ),
    (
        "test[postgresql:///db?k=a/../b:secret=/pwone/pwtwo",
        "test[postgresql:///db?k=a/../b:secret=<hidden>/pwone/pwtwo",
        "",
    ),
    (
        "t[mysql://u@/db?k=a/b/../c:x:/token=/pwone/pwtwo pwthree]",
        "t[mysql://<hidden>@/db?k=a/b/../c:x:/token=<hidden> pwthree]",
        "",
    ),
    (
        "postgresql:///a/../b?k=a/b/../c:~/auth_token=//passlimah&path=a/../../foldpa"
        'pal/foldechom/foldhoteln/data.csv&password="qvkiloo qvtangop qvsierraa"',
        "postgresql:///b?k=a/b/../c:~/auth_token=<hidden>",
        "",
    ),
    (
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB']",
        "test_conn['k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden> pwB']",
        "",
    ),
    (
        "test_conn[file:///q7/db?k=a/../b:/q1/q2/q3.pem]",
        "test_conn[file://db?k=a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "public_case(\"t[postgresql:///db?k=a/../b:/password=/x' pwone pwtwo']\")",
        'public_case("t[postgresql:///db?k=a/../b:/password=<hidden>]")',
        "",
    ),
    (
        "git+ssh://[]#dirqh/../leafqp.sock\t?c/../=~usrqcb/leafqcc.pem",
        "git+ssh://[]#/dirqh/../leafqp.sock\t?c/../=~usrqcb/leafqcc.pem",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/api_key=pwone:/pwtwo#f",
        "postgresql:///db?k=a/../b:/api_key=<hidden>/pwtwo#f",
        "",
    ),
    (
        "t[postgresql:///db?q=1&a/../b::/PGPASSWORD=/pwone&j=1]",
        "t[postgresql:///db?q=1&a/../b::/PGPASSWORD=<hidden>/pwone&j=1]",
        "",
    ),
    (
        "file://usermiken@/foldcharliep/foldindiaa/db?host=a/../b::/access_token=~/to"
        "kquebeci/tokgolfj&secret='qvvictoro qvkilop'?apikey='qvtangoa qvquebecb'",
        "file://db?host=a/../b::/access_token=<hidden>",
        "",
    ),
    (
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB']",
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>]",
        "",
    ),
    (
        "test_conn[unix:///q6/s.sock?k=a/../b:/q1/q2/q3.pem]",
        "test_conn[unix:///s.sock?k=a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "leafqcc.pemftp://[]///=dirqcp/../leafqcs.txt &ssl-ca/../:/dirqdc/leafqdd.txt",
        "leafqcc.pemftp://[]//leafqcs.txt &ssl-ca/../:/dirqdc/leafqdd.txt",
        "",
    ),
    (
        "postgresql:///db#a/../b:/password=/pwone pwtwo]",
        "postgresql:///db#a/../b:/password=<hidden> pwtwo]",
        "",
    ),
    (
        "t[postgresql:///db?q=/a/b&k=x/./../y:/x/PGPASSWORD='pwone pwtwo']",
        "t[postgresql:///db?q=/b&k=x/./../y:/x/PGPASSWORD=<hidden>]",
        "",
    ),
    (
        "redis:///?host=foldsierrae/../foldquebecf:~/auth_token=/folddeltaj/passvicto"
        "rk'qvsierran qvlimao';token=passcharliep#path=a/b/../c token=passcharlieg",
        "redis:///?host=foldsierrae/../foldquebecf:~/auth_token=<hidden> token=<hidden>",
        "",
    ),
    (
        "x:///db?k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB'",
        "x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "leafqz.sockftp://@localhost/../leafqcn.pem\t&dirqcs/../:/dirqcv/dirqcw",
        "leafqz.sockftp://<hidden>@/localhost/../leafqcn.pem\t&dirqcs/../:/dirqcv/dirqcw",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=/pwone&j=1",
        "postgresql:///db#a/../b:/secret=<hidden>/pwone&j=1",
        "",
    ),
    (
        "t[file:///run/x?q=/a/b&k=a/../b::/PGPASSWORD=/pwone pwtwo]",
        "t[file://x?q=/b&k=a/../b::/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "git+ssh://127.0.0.1:/db#c=foldquebecc/../foldromeod:/foldromeog/access_token"
        "=../passtangoi&password=passquebecn&api_key='qvbravoo qvbravop qvyankeea'",
        "git+ssh://127.0.0.1:/db#c=foldquebecc/../foldromeod:/foldromeog/access_token=<hidden>",
        "",
    ),
    (
        "run x:///db?k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB'",
        "run x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "ws://dirqg/=dirqn/../leafqp #dirqcc/../:/dirqcf/dirqcg",
        "ws://dirqg/=/dirqn/../leafqp #dirqcc/../:/dirqcf/dirqcg",
        "",
    ),
    (
        "postgresql:///db#a/../b:/api_key=/x' pwone pwtwo'",
        "postgresql:///db#a/../b:/api_key=<hidden>",
        "",
    ),
    (
        "t[postgresql://[fd00::1]:/db?q=1&a/../b:/x/PGPASSWORD=../pwone pwtwo]",
        "t[postgresql://[fd00::1]:/db?q=1&a/../b:/x/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "sqlite://usepassword=rlimaj@/db?file=a/../b:/PASSWORD=/../b:/PASSWORD=/foldj"
        "ulietc/tokuser:pw@'deltad tokechoe/passhotelg]",
        "sqlite://<hidden>@/db?file=a/../b:/PASSWORD=<hidden>",
        "",
    ),
    (
        'test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"]',
        "test_conn['k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden> pwB']",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/password=pwone/../pwtwo&j=1",
        "postgresql:///db?k=a/../b:/password=<hidden>/../pwtwo&j=1",
        "",
    ),
    (
        "t[postgresql:///db?q=1&k=a/b/../c:x:/PGPASSWORD=/pwone]",
        "t[postgresql:///db?q=1&k=a/b/../c:x:/PGPASSWORD=<hidden>/pwone]",
        "",
    ),
    (
        "glucharliekgit+ssh:///foldech/foldpapam/fold?deltan/db?host=a/b/../c:/passwd"
        "=/passjuliete'qvjulieth qvtangoi'&token=passromeoj]",
        "glucharliekgit+ssh:///fold?deltan/db?host=a/b/../c:/passwd=<hidden>",
        "",
    ),
    (
        'test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"]',
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/password=/x' pwone pwtwo' tail",
        "postgresql:///db?k=a/../b:/password=<hidden> tail",
        "",
    ),
    (
        "t[file:///run/x#k=x/./../y:/x/PGPASSWORD=/x' pwone pwtwo']",
        "t[file://x#k=x/./../y:/x/PGPASSWORD=<hidden>]",
        "",
    ),
    (
        "redis:////fdech/foldtangoo/foldoscarp/db?token=passkilob&k=x/./../y:/foldbra"
        "vog/passwd=/passromeoi'qvtangol qvechom'",
        "redis:///db?token=<hidden>&k=x/./../y:/foldbravog/passwd=<hidden> qvechom'",
        "",
    ),
    (
        'x:///db?k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"',
        "x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=pwone:/pwtwo",
        "postgresql:///db#a/../b:/secret=<hidden>/pwtwo",
        "",
    ),
    (
        "t[postgresql:///db#k=a/b/../c:x:/password=/x' pwone pwtwo']",
        "t[postgresql:///db#k=a/b/../c:x:/password=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?next=a/b/../c:/secret=../passgolfj poeok",
        "postgresql:///db?next=a/b/../c:/secret=<hidden> poeok",
        "",
    ),
    (
        'run x:///db?k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"',
        "run x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db#a/../b:/PASSWORD=/x' pwone pwtwo'&j=1",
        "postgresql:///db#a/../b:/PASSWORD=<hidden>",
        "",
    ),
    (
        "t[unix:///run/s.sock#k=a/b/../c:x:/api_key=/pwone&j=1]",
        "t[unix:///s.sock#k=a/b/../c:x:/api_key=<hidden>/pwone&j=1]",
        "",
    ),
    (
        'test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem../token="pwA"]',
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem../token=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b/password=/pwone/pwtwo&j=1",
        "postgresql:///db?k=a/../b/password=<hidden>/pwone/pwtwo&j=1",
        "",
    ),
    (
        "t[unix:///run/s.sock#k=a/../b:/x/api_key=/x' pwone pwtwo']",
        "t[unix:///s.sock#k=a/../b:/x/api_key=<hidden>]",
        "",
    ),
    (
        'test_x[x:///db?k=a/../b:/q1/q2/q3.pem../token="pwA"]',
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem../token=<hidden>]",
        "",
    ),
    (
        "postgresql:///db#a/../b:/PASSWORD=/pwone pwtwo]",
        "postgresql:///db#a/../b:/PASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "t[postgresql:///db?q=/a/b&k=x/./../y:/api_key=../pwone pwtwo]",
        "t[postgresql:///db?q=/b&k=x/./../y:/api_key=<hidden> pwtwo]",
        "",
    ),
    (
        'x:///db?k=a/../b:/q1/q2/q3.pem../token="pwA"',
        "x:///db?k=a/../b:/q1/q2/q3.pem../token=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/passwd=~/pwone pwtwo tail",
        "postgresql:///db?k=a/../b:/passwd=<hidden> pwtwo tail",
        "",
    ),
    (
        't[unix:///run/s.sock#a/../b:/x/token=/x" pwone]',
        "t[unix:///s.sock#a/../b:/x/token=<hidden>]",
        "",
    ),
    (
        'run x:///db?k=a/../b:/q1/q2/q3.pem../token="pwA"',
        "run x:///db?k=a/../b:/q1/q2/q3.pem../token=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/secret=/pwone&k=1]",
        "postgresql:///db?k=a/../b:/secret=<hidden>/pwone&k=1]",
        "",
    ),
    (
        "t[x://?q=/a/b&k=a/b/../c:x:/password=/pwone pwtwo]",
        "t[x://?q=/b&k=a/b/../c:x:/password=<hidden> pwtwo]",
        "",
    ),
    (
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key='lib/../lib:/q14 q16/q15.pem']",
        "test_conn['k=x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden> q16/q15.pem']",
        "",
    ),
    (
        "postgresql:///db#a/../b:/api_key=pwone:/pwtwo tail",
        "postgresql:///db#a/../b:/api_key=<hidden> tail",
        "",
    ),
    (
        "t[x://?q=/a/b&k=a/../b/c::/password=../pwone pwtwo]",
        "t[x://?q=/b&k=a/../b/c::/password=<hidden> pwtwo]",
        "",
    ),
    (
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key='lib/../lib:/q14 q16/q15.pem']",
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/PASSWORD=/x' pwone pwtwo'#f",
        "postgresql:///db?k=a/../b:/PASSWORD=<hidden>",
        "",
    ),
    (
        "t[postgresql:///db?q=/a/b&k=a/../b:/x/token=~/pwone pwtwo]",
        "t[postgresql:///db?q=/b&k=a/../b:/x/token=<hidden> pwtwo]",
        "",
    ),
    (
        "x:///db?k=a/../b:/q1/q2/q3.pem&api_key='lib/../lib:/q14 q16/q15.pem'",
        "x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db#a/../b:/PASSWORD=pwone/../pwtwo#f",
        "postgresql:///db#a/../b:/PASSWORD=<hidden>/../pwtwo#f",
        "",
    ),
    (
        "t[unix:///run/s.sock?k=a/../b::/password=~/pwone pwtwo]",
        "t[unix:///s.sock?k=a/../b::/password=<hidden> pwtwo]",
        "",
    ),
    (
        "run x:///db?k=a/../b:/q1/q2/q3.pem&api_key='lib/../lib:/q14 q16/q15.pem'",
        "run x:///db?k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/passwd=/pwone pwtwo",
        "postgresql:///db?k=a/../b:/passwd=<hidden> pwtwo",
        "",
    ),
    (
        "t[postgresql:///db?q=1&k=x/./../y:/password=/x' pwone pwtwo']",
        "t[postgresql:///db?q=1&k=x/./../y:/password=<hidden>]",
        "",
    ),
    (
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB']",
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB']",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:token=/pwone/pwtwo&j=1",
        "postgresql:///db?k=a/../b:token=<hidden>/pwone/pwtwo&j=1",
        "",
    ),
    (
        't[postgresql:///db?q=1&a/../b:/token=/x" pwone]',
        "t[postgresql:///db?q=1&a/../b:/token=<hidden>]",
        "",
    ),
    (
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB']",
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB']",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=pwone:/pwtwo tail",
        "postgresql:///db#a/../b:/secret=<hidden> tail",
        "",
    ),
    (
        't[file:///run/x?q=/a/b&a/../b:/password=/x" pwone]',
        "t[file://x?q=/b&a/../b:/password=<hidden>]",
        "",
    ),
    (
        "x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB'",
        "x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB'",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=pwone:/pwtwo&j=1",
        "postgresql:///db#a/../b:/secret=<hidden>/pwtwo&j=1",
        "",
    ),
    (
        "t[postgresql://[fd00::1]/db?q=/a/b&k=x/./../y::/PGPASSWORD=/pwone]",
        "t[postgresql://[fd00::1]/db?q=/b&k=x/./../y::/PGPASSWORD=<hidden>/pwone]",
        "",
    ),
    (
        "run x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB'",
        "run x:///db?k=a/../b:/q1/q2/q3.pem/'pwA pwB'",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:token=/pwone/pwtwo",
        "postgresql:///db?k=a/../b:token=<hidden>/pwone/pwtwo",
        "",
    ),
    (
        "t[mysql://u@/db?q=1&a/../b:/x/PGPASSWORD=/pwone pwtwo]",
        "t[mysql://<hidden>@/db?q=1&a/../b:/x/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=`pwA pwB`]",
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=<hidden> pwB`]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/password=pwone:/pwtwo#f",
        "postgresql:///db?k=a/../b:/password=<hidden>/pwtwo#f",
        "",
    ),
    (
        "t[postgresql://h.example:/db#k=a/../b:/x/api_key=/pwone pwtwo]",
        "t[postgresql://h.example:/db#k=a/../b:/x/api_key=<hidden> pwtwo]",
        "",
    ),
    (
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=`pwA pwB`]",
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=<hidden> pwB`]",
        "",
    ),
    (
        "postgresql:///db#a/../b:/PASSWORD=../pwone pwtwo&j=1",
        "postgresql:///db#a/../b:/PASSWORD=<hidden> pwtwo&j=1",
        "",
    ),
    (
        "t[postgresql://h.example:/db#k=x/./../y:/password=/pwone pwtwo]",
        "t[postgresql://h.example:/db#k=x/./../y:/password=<hidden> pwtwo]",
        "",
    ),
    (
        "x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=`pwA pwB`",
        "x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=<hidden> pwB`",
        "",
    ),
    (
        'postgresql:///db#a/../b:/passwd=/x" pwone tail',
        "postgresql:///db#a/../b:/passwd=<hidden>",
        "",
    ),
    (
        "t[postgresql://[fd00::1]:/db?q=1&k=a/../b/c:/x/PGPASSWORD=/pwone&j=1]",
        "t[postgresql://[fd00::1]:/db?q=1&k=a/../b/c:/x/PGPASSWORD=<hidden>/pwone&j=1]",
        "",
    ),
    (
        "run x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=`pwA pwB`",
        "run x:///db?k=a/../b:/q1/q2/q3.pem&x=1&token=<hidden> pwB`",
        "",
    ),
    (
        "postgresql:///db#a/../b:/token=pwone/../pwtwo&j=1",
        "postgresql:///db#a/../b:/token=<hidden>/../pwtwo&j=1",
        "",
    ),
    (
        "t[file:///run/x?q=/a/b&k=a/../b/c:/api_key=~/pwone pwtwo]",
        "t[file://x?q=/b&k=a/../b/c:/api_key=<hidden> pwtwo]",
        "",
    ),
    (
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem#password='pwA pwB']",
        "test_conn[k=x:///db?k=a/../b:/q1/q2/q3.pem#password=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/passwd=/pwone",
        "postgresql:///db?k=a/../b:/passwd=<hidden>/pwone",
        "",
    ),
    (
        "t[postgresql:///db?q=/a/b&k=a/../b:/token=/pwone pwtwo]",
        "t[postgresql:///db?q=/b&k=a/../b:/token=<hidden> pwtwo]",
        "",
    ),
    (
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem#password='pwA pwB']",
        "test_x[x:///db?k=a/../b:/q1/q2/q3.pem#password=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/token=~/pwone pwtwo",
        "postgresql:///db?k=a/../b:/token=<hidden> pwtwo",
        "",
    ),
    (
        "t[postgresql://h.example:/db?q=1&a/../b::/token=/pwone&j=1]",
        "t[postgresql://h.example:/db?q=1&a/../b::/token=<hidden>/pwone&j=1]",
        "",
    ),
    (
        "x:///db?k=a/../b:/q1/q2/q3.pem#password='pwA pwB'",
        "x:///db?k=a/../b:/q1/q2/q3.pem#password=<hidden>",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=/pwone#f",
        "postgresql:///db#a/../b:/secret=<hidden>/pwone#f",
        "",
    ),
    (
        "t[file:///run/x#k=a/../b::/PGPASSWORD=../pwone pwtwo]",
        "t[file://x#k=a/../b::/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "run x:///db?k=a/../b:/q1/q2/q3.pem#password='pwA pwB'",
        "run x:///db?k=a/../b:/q1/q2/q3.pem#password=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/PASSWORD=/x' pwone pwtwo'",
        "postgresql:///db?k=a/../b:/PASSWORD=<hidden>",
        "",
    ),
    (
        "t[mysql://u@/db?q=1&a/../b::/token=~/pwone pwtwo]",
        "t[mysql://<hidden>@/db?q=1&a/../b::/token=<hidden> pwtwo]",
        "",
    ),
    (
        'test_conn[k=postgresql:///db?j=/q9/q8.pem&password=a/../b:/q1/q2../token="pwA"]',
        "test_conn[k=postgresql:///db?j=/q8.pem&password=<hidden>/../b:/q1/q2../token=<hidden>]",
        "",
    ),
    (
        "postgresql:///db#a/../b:/secret=/pwone/pwtwo tail",
        "postgresql:///db#a/../b:/secret=<hidden> tail",
        "",
    ),
    (
        "t[unix:///run/s.sock#k=x/./../y:/x/password=/pwone&j=1]",
        "t[unix:///s.sock#k=x/./../y:/x/password=<hidden>/pwone&j=1]",
        "",
    ),
    (
        'test_x[postgresql:///db?j=/q9/q8.pem&password=a/../b:/q1/q2../token="pwA"]',
        "test_x[postgresql:///db?j=/q8.pem&password=<hidden>/../b:/q1/q2../token=<hidden>]",
        "",
    ),
    (
        "postgresql:///db#a/../b:/passwd=~/pwone pwtwo]",
        "postgresql:///db#a/../b:/passwd=<hidden> pwtwo]",
        "",
    ),
    (
        "t[unix:///run/s.sock?q=/a/b&k=x/./../y:/PGPASSWORD=/pwone]",
        "t[unix:///s.sock?q=/b&k=x/./../y:/PGPASSWORD=<hidden>/pwone]",
        "",
    ),
    (
        'postgresql:///db?j=/q9/q8.pem&password=a/../b:/q1/q2../token="pwA"',
        "postgresql:///db?j=/q8.pem&password=<hidden>/../b:/q1/q2../token=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/secret=/pwone/pwtwo]",
        "postgresql:///db?k=a/../b:/secret=<hidden>/pwone/pwtwo]",
        "",
    ),
    (
        "t[unix:///run/s.sock?q=1&k=a/b/../c:x:/token=/pwone/pwtwo pwthree]",
        "t[unix:///s.sock?q=1&k=a/b/../c:x:/token=<hidden> pwthree]",
        "",
    ),
    (
        "test_conn[k=postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB']",
        "test_conn['k=postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden> pwB']",
        "",
    ),
    (
        "postgresql:///db#a/../b:/PASSWORD=/pwone/pwtwo]",
        "postgresql:///db#a/../b:/PASSWORD=<hidden>/pwone/pwtwo]",
        "",
    ),
    (
        "t[postgresql://[fd00::1]/db?q=/a/b&k=a/../b:/x/PGPASSWORD=../pwone pwtwo]",
        "t[postgresql://[fd00::1]/db?q=/b&k=a/../b:/x/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "test_x[postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB']",
        "test_x[postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>]",
        "",
    ),
    (
        'postgresql:///db?k=a/../b:/secret=/x" pwone',
        "postgresql:///db?k=a/../b:/secret=<hidden>",
        "",
    ),
    (
        "t[postgresql://h.example:/db#k=a/../b::/api_key=/x' pwone pwtwo']",
        "t[postgresql://h.example:/db#k=a/../b::/api_key=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB'",
        "postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/token=../pwone pwtwo tail",
        "postgresql:///db?k=a/../b:/token=<hidden> pwtwo tail",
        "",
    ),
    (
        "t[mysql://u@/db?q=/a/b&a/../b:/password=/pwone/pwtwo pwthree]",
        "t[mysql://<hidden>@/db?q=/b&a/../b:/password=<hidden> pwthree]",
        "",
    ),
    (
        "run postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key='pwA pwB'",
        "run postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/password=/pwone]",
        "postgresql:///db?k=a/../b:/password=<hidden>/pwone]",
        "",
    ),
    (
        "t[s3://b?q=/a/b&a/../b::/PGPASSWORD=~/pwone pwtwo]",
        "t[s3://b?q=/b&a/../b::/PGPASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        'test_conn[k=postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"]',
        "test_conn['k=postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden> pwB']",
        "",
    ),
    (
        "postgresql:///db#a/../b:/api_key=~/pwone pwtwo#f",
        "postgresql:///db#a/../b:/api_key=<hidden> pwtwo#f",
        "",
    ),
    (
        "t[file:///run/x?q=1&k=x/./../y::/password=/pwone]",
        "t[file://x?q=1&k=x/./../y::/password=<hidden>/pwone]",
        "",
    ),
    (
        'test_x[postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"]',
        "test_x[postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>]",
        "",
    ),
    (
        "postgresql:///db#a/../b:/token=/pwone&k=1 tail",
        "postgresql:///db#a/../b:/token=<hidden> tail",
        "",
    ),
    (
        't[file:///run/x#k=a/../b:/api_key=/x" pwone]',
        "t[file://x#k=a/../b:/api_key=<hidden>]",
        "",
    ),
    (
        'postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"',
        "postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/api_key=pwone:/pwtwo]",
        "postgresql:///db?k=a/../b:/api_key=<hidden>/pwtwo]",
        "",
    ),
    (
        't[postgresql://[fd00::1]:/db#a/../b:/api_key=/x" pwone]',
        "t[postgresql://[fd00::1]:/db#a/../b:/api_key=<hidden>]",
        "",
    ),
    (
        'run postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key="pwA pwB"',
        "run postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem&api_key=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/PASSWORD=../pwone pwtwo]",
        "postgresql:///db?k=a/../b:/PASSWORD=<hidden> pwtwo]",
        "",
    ),
    (
        "t[unix:///run/s.sock?q=1&k=a/../b/c:/api_key=/pwone]",
        "t[unix:///s.sock?q=1&k=a/../b/c:/api_key=<hidden>/pwone]",
        "",
    ),
    (
        'test_conn[k=postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem../token="pwA"]',
        "test_conn[k=postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem../token=<hidden>]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/password=~/pwone pwtwo]",
        "postgresql:///db?k=a/../b:/password=<hidden> pwtwo]",
        "",
    ),
    (
        "t[postgresql:///db?q=/a/b&k=a/../b/c:/api_key=/x' pwone pwtwo']",
        "t[postgresql:///db?q=/b&k=a/../b/c:/api_key=<hidden>]",
        "",
    ),
    (
        'test_x[postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem../token="pwA"]',
        "test_x[postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem../token=<hidden>]",
        "",
    ),
    (
        "test[postgresql:///db?k=a/../b:token=/pwone/pwtwo]",
        "test[postgresql:///db?k=a/../b:token=<hidden>/pwone/pwtwo]",
        "",
    ),
    (
        "t[unix:///run/s.sock#k=a/../b:/x/api_key=../pwone pwtwo]",
        "t[unix:///s.sock#k=a/../b:/x/api_key=<hidden> pwtwo]",
        "",
    ),
    (
        'postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem../token="pwA"',
        "postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem../token=<hidden>",
        "",
    ),
    (
        "postgresql:///db?k=a/../b:/passwd=/pwone tail",
        "postgresql:///db?k=a/../b:/passwd=<hidden> tail",
        "",
    ),
    (
        't[postgresql://h.example:/db?a/../b:/password=/x" pwone]',
        "t[postgresql://h.example:/db?a/../b:/password=<hidden>]",
        "",
    ),
    (
        'run postgresql:///db?j=/q9/q8.pem&k=a/../b:/q1/q2/q3.pem../token="pwA"',
        "run postgresql:///db?j=/q8.pem&k=a/../b:/q1/q2/q3.pem../token=<hidden>",
        "",
    ),
    (
        "https://h.example/a?k=../../d/f &~ZqU/x",
        "https://h.example/a?k=f &x",
        "",
    ),
    (
        "x://<hidden>/a?k=-x/../@ZqB/../../#>~ZqU~ZqU/x/?&k=",
        "x://<hidden>/a?k=-x/../@..#>~ZqU~ZqU/x/?&k=",
        "",
    ),
    (
        "https://h.example/v1?path=lib/../lib:/opt/Zq/lib &/x",
        "https://h.example/v1?path=/lib/../lib:/opt/Zq/lib &/x",
        "",
    ),
    (
        "https://h.example/v1?path=lib/../lib:/opt/Zq/lib x&/y",
        "https://h.example/v1?path=/lib/../lib:/opt/Zq/lib x&/y",
        "",
    ),
    (
        "x://?ZqA/../../&a/../b",
        "x://?..&a/../b",
        "",
    ),
    (
        "postgresql:///db?sslrootcert=file:///a/ca.pem&replica=https://dbhost",
        "postgresql:///db?sslrootcert=file://dbhost",
        "",
    ),
    (
        ":///?unix://:/dQ39457x/Q",
        ":///?unix:///Q",
        "",
    ),
    (
        "postgresql://db.example/db?k=a/../b:/made/up/x/s3://db2.example/y",
        "postgresql://db.example/db?k=/a/../b:/made/up/x/s3://db2.example/y",
        "",
    ),
    (
        "x://h/db?c=../a/s3://hostq/x",
        "x://h/db?c=x",
        "",
    ),
    (
        "postgresql:///db?sslrootcert=FILE:///a/ca.pem&replica=https://dbhost",
        "postgresql:///db?sslrootcert=FILE://dbhost",
        "",
    ),
    (
        "https://h.example/db?k=a/../b:/x/s3://hostq/y",
        "https://h.example/db?k=/a/../b:/x/s3://hostq/y",
        "",
    ),
    (
        "s://?a/../=~4411x/dQ36307x/dQ36308x/dQ36309x",
        "s://?/a/../=~<hidden>",
        "",
    ),
    (
        "https://h.example/v1?k=~4411x/dQ36307x/dQ36308x/dQ36309x",
        "https://h.example/v1?k=dQ36309x",
        "",
    ),
    (
        ":///?e://hQ00001x=../a/b&x@c",
        ":///?e://hQ00001x=b&x@c",
        "",
    ),
    (
        "x://h?c=../a/b",
        "x://h?c=b",
        "",
    ),
    (
        "file://a.binhttps://made-up.example",
        "file://made-up.example",
        "",
    ),
    (
        "redis://#a/../l.sock\tb/../&/usrq/d",
        "redis://#/a/../l.sock\tb/../&/d",
        "",
    ),
    (
        "postgresql:///db?c=file:///made/up/ca.pem x",
        "postgresql:///db?c=file://ca.pem x",
        "",
    ),
    (
        "postgresql:///db?c=file:///made/up/ca.pem x&k=a/b",
        "postgresql:///db?c=file://b",
        "",
    ),
    (
        "https://made-up.example/v1?path=lib/../lib:/made/up/lib &x/y",
        "https://made-up.example/v1?path=/lib/../lib:/made/up/lib &x/y",
        "",
    ),
    (
        "postgresql:///db?k=a/../b x/c:/made/up/ca.pem",
        "postgresql:///db?k=a/../b x/c:ca.pem",
        "",
    ),
    (
        "s://h.example/p?k=a/../b x/../&j=/a/x",
        "s://h.example/p?k=/a/../b x/../&j=/x",
        "",
    ),
    (
        "postgresql://db.example/db?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem",
        "postgresql://db.example/db?k=/a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "",
    ),
    (
        "https://localhost/a?k=x/../y &/zqd1/zqd2/x",
        "https://localhost/a?k=/x/../y &/x",
        "",
    ),
    (
        "test_x[k=x://h.example/?k=a/../b:/q1/q2/q3.pem]",
        "test_x[k=x://h.example/?k=/a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "test_conn[postgresql://db1.example,db2.example/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db1.example,db2.example/db?k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "test_conn[postgresql://db.example/db?a=(b)&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=(b)&k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "test_conn[k=x:///db?password=a/../b&api_key='pwA pwB']",
        "test_conn['k=x:///db?password=<hidden>&api_key=<hidden> pwB']",
        "",
    ),
    (
        "test_conn[postgresql://localhost/bench?x=a/../b:/zqd1/zqd2/x]",
        "test_conn[postgresql://localhost/bench?x=/a/../b:/zqd1/zqd2/x]",
        "",
    ),
    (
        "test_conn[x://h.example/db?k=a/../b:/q1/q2/q3.pem]",
        "test_conn[x://h.example/db?k=/a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "psql 'postgresql://[fd00::1]/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://[fd00::1]/db?k=/a/../b x/../&j=/ca.pem'",
        "",
    ),
    (
        "psql 'postgresql://:5432/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://:5432/db?k=/a/../b x/../&j=/ca.pem'",
        "",
    ),
    (
        "test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]",
        "test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]",
        "",
    ),
    (
        "test_conn[k=postgresql://db.example/db#password=a/../b&api_key='zqa zqb']",
        "test_conn[k=postgresql://db.example/db#password=<hidden>]",
        " +1f8142f7",
    ),
    (
        "psql 'postgresql://[fd00::1]/db?k=a/../b:/made/up/ca.pem'",
        "psql 'postgresql://[fd00::1]/db?k=/a/../b:/made/up/ca.pem'",
        "",
    ),
    (
        "test_conn[k=postgresql://db.example/db#password=a/../b&api_key='pwA pwB']",
        "test_conn[k=postgresql://db.example/db#password=<hidden>]",
        " +a4139e59",
    ),
    (
        "&&",
        "&&",
        "",
    ),
    (
        "https://uQ02493x@hQ02683x/db,file://hQ02684x:5432/ http+unix://hQ02685x?next"
        "=~/dQ20237x/lQ10976x.sock;host:~uQ02494x/dQ20238x/dQ20239x/lQ10977x.pem,../d"
        "Q20240x/dQ20241x/lQ10978x,",
        "https://<hidden>@hQ02683x/db,file:/// http+unix:///hQ02685x?next=lQ10976x.so"
        "ck;host:lQ10977x.pem,lQ10978x,",
        "",
    ),
    (
        "BM_Read[s3://hstqc.example,hstqd.example/dirqf/leafqg.pem#file://hstqj/dirqk"
        "/dirqm/dirqn/leafqp.sock]",
        "BM_Read[s3://hstqc.example,hstqd.example/dirqf/leafqg.pem#file://leafqp.sock]",
        "",
    ),
    (
        "redis://#dirqj/../leafqp.sock\tdirqs/../&/usrqz/dirqcb",
        "redis://#/dirqj/../leafqp.sock\tdirqs/../&/dirqcb",
        "",
    ),
    (
        "postgresql://db.example/db?c=../made.up/ca.pem",
        "postgresql://db.example/db?c=ca.pem",
        "",
    ),
    (
        "test_conn[k=postgresql://db.example/db#password=a/b&api_key='pwA pwB']",
        "test_conn['k=postgresql://db.example/db#password=<hidden> pwB']",
        "",
    ),
    (
        "test_x[k=x://h.example/#password=a/../b&api_key='q14 q16/q15.pem']",
        "test_x[k=x://h.example/#password=<hidden>]",
        "",
    ),
    (
        "test_x[k=x://h.example/#password=a/../b&api_key='pwA pwB']",
        "test_x[k=x://h.example/#password=<hidden>]",
        " +a4139e59",
    ),
    (
        'x://h.example/a?b#password=a/../b;token="pA/pB/pC"',
        'x://h.example/a?b#password=<hidden>/a/../b;token=<hidden>/pB/pC"',
        "",
    ),
    (
        "test_conn[postgresql://db.example/db#password=a/../b&api_key='pwA pwB']",
        "test_conn[postgresql://db.example/db#password=<hidden>]",
        "",
    ),
    (
        'test_conn[ ?token=h://#password=a/../token="pwA"]',
        "test_conn[ ?token=<hidden>#password=<hidden>../token=<hidden>]",
        " +203272e0",
    ),
    (
        "k=postgresql://db.example/db#password=a/../b&api_key='pwA pwB'",
        "k=postgresql://db.example/db#password=<hidden>",
        " +eb56a9c8",
    ),
    (
        "test_x[k=x://[fd00::1]:5432/#password=a/../b:/qzf8x/qzf9x/qzf10x.pem&api_key"
        "='lib/../lib:/qzf14x qzf16x/qzf15x.pem',/qzf17x/qzf18x/qzf19x/qzf20x.sock]",
        "test_x[k=x://[fd00::1]:5432/#password=<hidden>]",
        "",
    ),
    (
        "test_x[k=x://h.example/#password=a/../b:/q8/q10.pem&api_key=lib/../lib:/q14 q16/q15.pem]",
        "test_x[k=x://h.example/#password=<hidden> q16/q15.pem]",
        "",
    ),
    (
        "postgresql:///db?k=a/../b api_key=pwone&j=1",
        "postgresql:///db?k=a/../b api_key=<hidden>",
        "",
    ),
    (
        "t[postgresql://[fd00::1]:/db?q=/a/b&k=a/b/../c:x/x/token=/x' pwone pwtwo']",
        "t[postgresql://[fd00::1]:/db?q=/b&k=a/b/../c:x/x/token=<hidden>]",
        "",
    ),
    (
        "https://h.example/v1?path=lib/../lib:/opt/Zq/lib &x",
        "https://h.example/v1?path=/lib/../lib:/opt/Zq/lib &x",
        "",
    ),
    (
        "https://h.example/a?k=-x/../@ZqB/../../#",
        "https://h.example/a?k=-x/../@..#",
        "",
    ),
    (
        "https://h.example/v1?path=../lib:/opt/Zq/lib &/x",
        "https://h.example/v1?path=lib &/x",
        "",
    ),
    (
        "https://h.example/v1?path=lib/../lib:/opt/Zq/lib x/y",
        "https://h.example/v1?path=/lib/../lib:/opt/Zq/lib x/y",
        "",
    ),
    (
        "x://?ZqA/../../&j=1",
        "x://?..&j=1",
        "",
    ),
    (
        "postgresql:///db?sslrootcert=file:///a/ca.pem&replica=postgresql://dbhost:54"
        "32?sslmode=require",
        "postgresql:///db?sslrootcert=file://dbhost:5432?sslmode=require",
        "",
    ),
    (
        ":///?unix:///:/dQ39457x/Q",
        ":///?unix:///Q",
        "",
    ),
    (
        "https://h.example/a?k=../a/s3://hostq/x",
        "https://h.example/a?k=x",
        "",
    ),
    (
        "postgresql:///db?c=unix:///a/s.sock&replica=https://dbhost",
        "postgresql:///db?c=unix:///dbhost",
        "",
    ),
    (
        "https://h.example/db?k=/x/s3://hostq/y",
        "https://h.example/db?k=/y",
        "",
    ),
    (
        ":///?a/../:~994x/dQ24235x/dQ24236x/dQ24237x8",
        ":///?a/../:~<hidden>",
        "",
    ),
    (
        "https://h.example/v1?k=a/../=~4411x/dQ36307x/dQ36308x/dQ36309x",
        "https://h.example/v1?k=/a/../=~<hidden>",
        "",
    ),
    (
        ":///?e://hQ00001x=../a/b@c",
        ":///?e://hQ00001x=b@c",
        "",
    ),
    (
        "x://h?c=../a/b@c",
        "x://h?c=b@c",
        "",
    ),
    (
        "postgresql:///db?sslrootcert=file:///made/up/ca.pem&replica=https://db.example",
        "postgresql:///db?sslrootcert=file://db.example",
        "",
    ),
    (
        "postgresql:///db?c=file:///made/up/ca.pem x&k=1",
        "postgresql:///db?c=file://ca.pem x&k=1",
        "",
    ),
    (
        "postgresql:///db?c=../made/up/ca.pem x&k=a/b",
        "postgresql:///db?c=ca.pem x&k=a/b",
        "",
    ),
    (
        "curl 'https://made-up.example/v1?path=lib/../lib:/made/up/lib &x/y'",
        "curl 'https://made-up.example/v1?path=/lib/../lib:/made/up/lib &x/y'",
        "",
    ),
    (
        "postgresql://db.example/db?k=a/../b x/c:/made/up/ca.pem",
        "postgresql://db.example/db?k=/a/../b x/c:/made/up/ca.pem",
        "",
    ),
    (
        "postgresql://:5432/db?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem",
        "postgresql://:5432/db?k=/a/../b x/c:/made/up/ca.pem&j=/ca.pem",
        "",
    ),
    (
        "test_get[https://localhost/a?k=x/../y &/zqd1/zqd2/x]",
        "test_get[https://localhost/a?k=/x/../y &/x]",
        "",
    ),
    (
        "test_x[k=x://h.example/?j=1&k=a/../b:/q1/q2/q3.pem]",
        "test_x[k=x://h.example/?j=1&k=/a/../b:/q1/q2/q3.pem]",
        "",
    ),
    (
        "test_conn[postgresql://db.example/db?a=b;k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a=b;k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "test_conn[postgresql://db.example/db?a='b'&k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example/db?a='b'&k=a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        "test_x[x:///db?password=a/../b&api_key='pwA pwB']",
        "test_x[x:///db?password=<hidden>&api_key=<hidden>]",
        "",
    ),
    (
        "test_conn[http://localhost/v1?next=a/../b]",
        "test_conn[http://localhost/v1?next=/a/../b]",
        "",
    ),
    (
        "test_conn[x://h.example/db?k=a/../b]",
        "test_conn[x://h.example/db?k=/a/../b]",
        "",
    ),
    (
        "psql 'postgresql://db.example:/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://db.example:/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "",
    ),
    (
        "psql 'postgresql://@/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "psql 'postgresql://<hidden>@/db?k=a/../b x/../&j=/made/up/ca.pem'",
        "",
    ),
    (
        "test_conn[postgresql://db.example:5432/db?k=a/../b:/made/up/ca.pem]",
        "test_conn[postgresql://db.example:5432/db?k=/a/../b:/made/up/ca.pem]",
        "",
    ),
    (
        'x s://h.example/?token=s3://b#password=a/../token="zqa"',
        "x s://h.example/?token=<hidden>#password=<hidden>../token=<hidden>",
        "",
    ),
    (
        "file://localhost/...",
        "file://...",
        "",
    ),
    (
        "test_db[redis://h.example/?c=:made-up@db.example:6379]",
        "test_db[redis://h.example/?c=:<hidden>@db.example:6379]",
        "",
    ),
    (
        "test_db[postgresql:///db?c=::made-up@db.example:6379]",
        "test_db[postgresql:///db?c=:<hidden>@db.example:6379]",
        "",
    ),
    (
        "test_db[https://h.example/x#k=a/../b&c=:made-up@db.example:6379]",
        "test_db[https://h.example/x#k=/a/../b&c=:<hidden>@db.example:6379]",
        "",
    ),
    (
        "test_db[postgresql:///db?k=a/../b:/x&c=:made-up@db.example:6379]",
        "test_db[postgresql:///db?k=a/../b:/x&c=:<hidden>@db.example:6379]",
        "",
    ),
    (
        "test_db[mysql://localhost:/db?c=file:///made/up/ca.pem&r=:made-up@db.example:6379]",
        "test_db[mysql://localhost:/db?c=file://ca.pem&r=:<hidden>@db.example:6379]",
        "",
    ),
    (
        "test_db[s3://bkt/x?c=../made/up&r=::made-up@db.example:1]",
        "test_db[s3://bkt/x?c=up&r=:<hidden>@db.example:1]",
        "",
    ),
    (
        "test_db[unix:///run/s.sock?c=:made-up@db.example.:6379]",
        "test_db[unix:///s.sock?c=:<hidden>@db.example.:6379]",
        "",
    ),
    (
        "run redis://h.example/?c=:made-up@db.example:6379 fast",
        "run redis://h.example/?c=:<hidden>@db.example:6379 fast",
        "",
    ),
    (
        "%://:credlalovupi@hostgefegiku.example.",
        "%://:<hidden>@hostgefegiku.example.",
        "",
    ),
    (
        ".://:credvunenira@hostkogubovu.example?",
        ".://:<hidden>@hostkogubovu.example?",
        "",
    ),
    (
        "%://:credvavutamu@hostsolenogu.example:1",
        "%://:<hidden>@hostsolenogu.example:1",
        "",
    ),
    (
        "URL=://:credvotuneba@hostpizosotu.example",
        "URL=://:<hidden>@hostpizosotu.example",
        "",
    ),
)


def test_the_rows_are_distinct_ids() -> None:
    assert len({case for case, _shown, _mark in ROWS}) == len(ROWS)


@pytest.mark.parametrize(("case", "shown", "mark"), ROWS)
def test_a_case_id_shows_as_written_through_every_reader(case: str, shown: str, mark: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case_drops(case) == (shown, mark != "")
    assert api.CaseNames(NAME_KEY).names([case], "a test", "advice") == {case: shown + mark}
