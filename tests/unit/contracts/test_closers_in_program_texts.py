# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential value in a program text inside a shell text, with a closer or operator after it.

``sh -c "python3 -c ..."`` and ``bash -c "node -e ..."`` read a word both as a word of a shell
text and as a word of a program's text. Where a credential value is followed directly by a
``)``, a backquote, a ``;`` or a ``&&`` (with or without a blank before it), also inside
``$(...)`` and inside backquotes, the value is never shown and the shown command splits into
the words that are hashed, so two values give one hash. Where the closer or the operator
stands outside the value it is shown after it, and another closer gives another hash.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from pairbench import model
from pairbench.sides.identity import argv_sha256

# Two made-up passwords that hold no credential word, so only the name before them hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
SHOWN_LEAD = "pairbench run -- "

# Each form: its argument list with ``{s}`` for the value, the closer or operator typed after
# the value, and the shown command, which is also what the hash is taken over.
CLOSER_SHOWN: dict[str, tuple[tuple[str, ...], str, str]] = {
    "shell word, a bracket, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}') run"),
        ")",
        "sh -c 'python3 -c API_KEY=<hidden>) run'",
    ),
    "quoted code value, a bracket, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\")run()'"),
        ")",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\")run()'\"'\"''",
    ),
    "shell word, a backquote, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}'` run"),
        "`",
        "sh -c 'python3 -c API_KEY=<hidden>` run'",
    ),
    "shell word, a semicolon, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}'; run"),
        ";",
        "sh -c 'python3 -c API_KEY=<hidden>; run'",
    ),
    "quoted code value, a semicolon, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\";run()'"),
        ";",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\";run()'\"'\"''",
    ),
    "shell word, an and, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}'&& run"),
        "&&",
        "sh -c 'python3 -c API_KEY=<hidden>&& run'",
    ),
    "shell word, a blank and a semicolon, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}' ; run"),
        " ;",
        "sh -c 'python3 -c API_KEY=<hidden> ; run'",
    ),
    "quoted code value, a blank and a semicolon, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\" ;run()'"),
        " ;",
        "sh -c 'python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"''",
    ),
    "bare code value, a blank and a semicolon, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY={s} ;run()'"),
        " ;",
        "sh -c 'python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"''",
    ),
    "shell word, a blank and an and, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c API_KEY='{s}' && run"),
        " &&",
        "sh -c 'python3 -c API_KEY=<hidden> && run'",
    ),
    "quoted code value, a blank and an and, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\" &&run()'"),
        " &&",
        "sh -c 'python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"''",
    ),
    "bare code value, a blank and an and, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY={s} &&run()'"),
        " &&",
        "sh -c 'python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"''",
    ),
    "shell word, a bracket in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}') run)"),
        ")",
        "sh -c 'echo $(python3 -c API_KEY=<hidden>) run)'",
    ),
    "quoted code value, a bracket in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\")run()')"),
        ")",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=\"<hidden>\")run()'\"'\"')'",
    ),
    "shell word, a backquote in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}'` run)"),
        "`",
        "sh -c 'echo $(python3 -c API_KEY=<hidden>` run)'",
    ),
    "shell word, a semicolon in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}'; run)"),
        ";",
        "sh -c 'echo $(python3 -c API_KEY=<hidden>; run)'",
    ),
    "quoted code value, a semicolon in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\";run()')"),
        ";",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=\"<hidden>\";run()'\"'\"')'",
    ),
    "shell word, an and in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}'&& run)"),
        "&&",
        "sh -c 'echo $(python3 -c API_KEY=<hidden>&& run)'",
    ),
    "shell word, a blank and a semicolon in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}' ; run)"),
        " ;",
        "sh -c 'echo $(python3 -c API_KEY=<hidden> ; run)'",
    ),
    "quoted code value, a blank and a semicolon in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\" ;run()')"),
        " ;",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"')'",
    ),
    "bare code value, a blank and a semicolon in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY={s} ;run()')"),
        " ;",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"')'",
    ),
    "shell word, a blank and an and in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c API_KEY='{s}' && run)"),
        " &&",
        "sh -c 'echo $(python3 -c API_KEY=<hidden> && run)'",
    ),
    "quoted code value, a blank and an and in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\" &&run()')"),
        " &&",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"')'",
    ),
    "bare code value, a blank and an and in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY={s} &&run()')"),
        " &&",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"')'",
    ),
    "shell word, a bracket in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c API_KEY='{s}') run`"),
        ")",
        "sh -c 'echo `python3 -c API_KEY=<hidden>) run`'",
    ),
    "quoted code value, a bracket in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY=\"{s}\")run()'`"),
        ")",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=\"<hidden>\")run()'\"'\"'`'",
    ),
    "shell word, a semicolon in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c API_KEY='{s}'; run`"),
        ";",
        "sh -c 'echo `python3 -c API_KEY=<hidden>; run`'",
    ),
    "quoted code value, a semicolon in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY=\"{s}\";run()'`"),
        ";",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=\"<hidden>\";run()'\"'\"'`'",
    ),
    "shell word, an and in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c API_KEY='{s}'&& run`"),
        "&&",
        "sh -c 'echo `python3 -c API_KEY=<hidden>&& run`'",
    ),
    "shell word, a blank and a semicolon in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c API_KEY='{s}' ; run`"),
        " ;",
        "sh -c 'echo `python3 -c API_KEY=<hidden> ; run`'",
    ),
    "quoted code value, a blank and a semicolon in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY=\"{s}\" ;run()'`"),
        " ;",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"'`'",
    ),
    "bare code value, a blank and a semicolon in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY={s} ;run()'`"),
        " ;",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=<hidden> ;run()'\"'\"'`'",
    ),
    "shell word, a blank and an and in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c API_KEY='{s}' && run`"),
        " &&",
        "sh -c 'echo `python3 -c API_KEY=<hidden> && run`'",
    ),
    "quoted code value, a blank and an and in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY=\"{s}\" &&run()'`"),
        " &&",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"'`'",
    ),
    "bare code value, a blank and an and in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY={s} &&run()'`"),
        " &&",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=<hidden> &&run()'\"'\"'`'",
    ),
    "shell word, a bracket, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}') run"),
        ")",
        "bash -c 'node -e API_KEY=<hidden>) run'",
    ),
    "shell word, a backquote, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}'` run"),
        "`",
        "bash -c 'node -e API_KEY=<hidden>` run'",
    ),
    "shell word, a semicolon, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}'; run"),
        ";",
        "bash -c 'node -e API_KEY=<hidden>; run'",
    ),
    "shell word, an and, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}'&& run"),
        "&&",
        "bash -c 'node -e API_KEY=<hidden>&& run'",
    ),
    "shell word, a blank and a semicolon, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}' ; run"),
        " ;",
        "bash -c 'node -e API_KEY=<hidden> ; run'",
    ),
    "shell word, a blank and an and, node -e in bash -c": (
        ("bash", "-c", "node -e API_KEY='{s}' && run"),
        " &&",
        "bash -c 'node -e API_KEY=<hidden> && run'",
    ),
    "shell word, a bracket in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}') run)"),
        ")",
        "bash -c 'echo $(node -e API_KEY=<hidden>) run)'",
    ),
    "shell word, a backquote in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}'` run)"),
        "`",
        "bash -c 'echo $(node -e API_KEY=<hidden>` run)'",
    ),
    "shell word, a semicolon in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}'; run)"),
        ";",
        "bash -c 'echo $(node -e API_KEY=<hidden>; run)'",
    ),
    "shell word, an and in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}'&& run)"),
        "&&",
        "bash -c 'echo $(node -e API_KEY=<hidden>&& run)'",
    ),
    "shell word, a blank and a semicolon in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}' ; run)"),
        " ;",
        "bash -c 'echo $(node -e API_KEY=<hidden> ; run)'",
    ),
    "shell word, a blank and an and in $(), node -e in bash -c": (
        ("bash", "-c", "echo $(node -e API_KEY='{s}' && run)"),
        " &&",
        "bash -c 'echo $(node -e API_KEY=<hidden> && run)'",
    ),
    "shell word, a bracket in backquotes, node -e in bash -c": (
        ("bash", "-c", "echo `node -e API_KEY='{s}') run`"),
        ")",
        "bash -c 'echo `node -e API_KEY=<hidden>) run`'",
    ),
    "shell word, a semicolon in backquotes, node -e in bash -c": (
        ("bash", "-c", "echo `node -e API_KEY='{s}'; run`"),
        ";",
        "bash -c 'echo `node -e API_KEY=<hidden>; run`'",
    ),
    "shell word, an and in backquotes, node -e in bash -c": (
        ("bash", "-c", "echo `node -e API_KEY='{s}'&& run`"),
        "&&",
        "bash -c 'echo `node -e API_KEY=<hidden>&& run`'",
    ),
    "shell word, a blank and a semicolon in backquotes, node -e in bash -c": (
        ("bash", "-c", "echo `node -e API_KEY='{s}' ; run`"),
        " ;",
        "bash -c 'echo `node -e API_KEY=<hidden> ; run`'",
    ),
    "shell word, a blank and an and in backquotes, node -e in bash -c": (
        ("bash", "-c", "echo `node -e API_KEY='{s}' && run`"),
        " &&",
        "bash -c 'echo `node -e API_KEY=<hidden> && run`'",
    ),
    "quoted code value, a backquote, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\"`run()'"),
        "`",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\"`run()'\"'\"''",
    ),
    "quoted code value, an and, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\"&&run()'"),
        "&&",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\"&&run()'\"'\"''",
    ),
    "quoted code value, a pipe, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY=\"{s}\"|run()'"),
        "|",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\"|run()'\"'\"''",
    ),
    "quoted code value, an and, python3 -c": (
        ("python3", "-c", 'API_KEY="{s}"&&run()'),
        "&&",
        "python3 -c 'API_KEY=\"<hidden>\"&&run()'",
    ),
    "quoted code value, a backquote, python3 -c": (
        ("python3", "-c", 'API_KEY="{s}"`run()'),
        "`",
        "python3 -c 'API_KEY=\"<hidden>\"`run()'",
    ),
    "quoted code value, a backquote in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\"`run()')"),
        "`",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=\"<hidden>\"`run()'\"'\"')'",
    ),
    "quoted code value, an and in $(), python3 -c in sh -c": (
        ("sh", "-c", "echo $(python3 -c 'API_KEY=\"{s}\"&&run()')"),
        "&&",
        "sh -c 'echo $(python3 -c '\"'\"'API_KEY=\"<hidden>\"&&run()'\"'\"')'",
    ),
    "quoted code value, an and in backquotes, python3 -c in sh -c": (
        ("sh", "-c", "echo `python3 -c 'API_KEY=\"{s}\"&&run()'`"),
        "&&",
        "sh -c 'echo `python3 -c '\"'\"'API_KEY=\"<hidden>\"&&run()'\"'\"'`'",
    ),
    "quoted code value, a pipe, python3 -c": (
        ("python3", "-c", "API_KEY='{s}'|run()"),
        "|",
        "python3 -c 'API_KEY='\"'\"'<hidden>'\"'\"'|run()'",
    ),
    "value in three quotes, a semicolon, python3 -c": (
        ("python3", "-c", "API_KEY='''{s}''';run()"),
        ";",
        "python3 -c 'API_KEY='\"'\"'<hidden>'\"'\"';run()'",
    ),
    "value in three double quotes, an and, python3 -c in sh -c": (
        ("sh", "-c", 'python3 -c \'API_KEY="""{s}"""&&run()\''),
        "&&",
        "sh -c 'python3 -c '\"'\"'API_KEY=\"<hidden>\"&&run()'\"'\"''",
    ),
}

# Values whose operator after the closing quote joins another string to them: ``||`` joins
# strings in SQL, and an ``&&`` or a ``|`` that a quote follows starts no next part of the
# program. The whole word is hidden, as is the rest of the value, so two values give one hash.
JOINED_HIDDEN: dict[str, tuple[tuple[str, ...], str]] = {
    "a string joined with ||, psql -c": (
        ("psql", "-c", "ALTER ROLE app PASSWORD='made'||'{s}'"),
        "psql -c 'ALTER ROLE app PASSWORD=<hidden>'",
    ),
    "a string joined with ||, psql -c in sh -c": (
        ("sh", "-c", "psql -c \"ALTER ROLE app PASSWORD='made'||'{s}'\""),
        "sh -c 'psql -c \"ALTER ROLE app PASSWORD=<hidden>\"'",
    ),
    "a string joined with ||, made-up-tool -c": (
        ("made-up-tool", "-c", "API_KEY='made'||'{s}'"),
        "made-up-tool -c 'API_KEY=<hidden>'",
    ),
    "a string after a pipe, python3 -c": (
        ("python3", "-c", 'API_KEY="made"|"{s}"'),
        "python3 -c 'API_KEY=<hidden>'",
    ),
    "a string after an and, python3 -c": (
        ("python3", "-c", "API_KEY='made'&&'{s}'"),
        "python3 -c 'API_KEY=<hidden>'",
    ),
    "a call after ||, python3 -c": (
        ("python3", "-c", "API_KEY='{s}'||run()"),
        "python3 -c 'API_KEY=<hidden>'",
    ),
}

# Three quotes in a shell's text, where they are an empty string and the opening quote of the
# next: ``'''a'b''' VALUE'`` is one word, ``ab VALUE``, to the shell. The value runs at least
# to the end of that word, so nothing of it shows and two values give one hash.
THREE_QUOTES_IN_A_SHELL_TEXT: dict[str, tuple[tuple[str, ...], str]] = {
    "three quotes, sh -c": (
        ("sh", "-c", "API_KEY='''a'b''' {s}' ./bench-old"),
        "sh -c 'API_KEY=<hidden> ./bench-old'",
    ),
    "three quotes and a backslash, sh -c": (
        ("sh", "-c", "API_KEY='''a\\'''' {s}' ./bench-old"),
        "sh -c 'API_KEY=<hidden> ./bench-old'",
    ),
    "three double quotes, sh -c": (
        ("sh", "-c", 'API_KEY="""a"b""" {s}" ./bench-old'),
        "sh -c 'API_KEY=<hidden> ./bench-old'",
    ),
    "three quotes after export, sh -c": (
        ("sh", "-c", "export API_KEY='''a'b''' {s}'; ./bench-old"),
        "sh -c 'export API_KEY=<hidden>; ./bench-old'",
    ),
    "three quotes, ssh": (
        ("ssh", "made-up-host", "API_KEY='''a'b''' {s}' ./bench-old"),
        "ssh made-up-host 'API_KEY=<hidden> ./bench-old'",
    ),
    "three quotes, bash -lc": (
        ("bash", "-lc", "API_KEY='''a'b''' {s}' ./bench-old"),
        "bash -lc 'API_KEY=<hidden> ./bench-old'",
    ),
    "three quotes, sh -c in sh -c": (
        ("sh", "-c", "sh -c \"API_KEY='''a'b''' {s}' ./bench-old\""),
        "sh -c 'sh -c \"API_KEY=<hidden> ./bench-old\"'",
    ),
}

# Values in three quotes that hold a quote and an operator: the value runs to the three
# quotes that close it, as in Python, so nothing of it shows.
TRIPLE_QUOTED: dict[str, tuple[str, ...]] = {
    "three quotes, a quote and a semicolon, python3 -c": (
        "python3",
        "-c",
        "API_KEY='''a';{s}'''",
    ),
    "three quotes, a quote and a pipe, python3 -c": ("python3", "-c", "API_KEY='''a'|{s}'''"),
    "three double quotes, a quote and an and, python3 -c": (
        "python3",
        "-c",
        'API_KEY="""a"&&{s}"""',
    ),
    "three double quotes, a quote and a semicolon, python3 -c in sh -c": (
        "sh",
        "-c",
        'python3 -c \'API_KEY="""a";{s}"""\'',
    ),
    "three double quotes, a quote and an and, python3 -c in sh -c": (
        "sh",
        "-c",
        'python3 -c \'API_KEY="""a"&&{s}"""\'',
    ),
}

# Forms whose closer or operator is hidden with the value, with the rest of the word: in the
# text of ``-c`` a bare value runs to the end of the word, and the text of ``node -e`` is not
# read as code. The value is still never shown, and the shown command and the hash agree.
HIDDEN_TO_THE_END: dict[str, tuple[str, ...]] = {
    "bare code value, a bracket, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY={s})run()'",
    ),
    "bare code value, a backquote, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY={s}`run()'",
    ),
    "bare code value, a semicolon, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY={s};run()'",
    ),
    "bare code value, an and, python3 -c in sh -c": ("sh", "-c", "python3 -c 'API_KEY={s}&&run()'"),
    "bare code value, a bracket in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY={s})run()')",
    ),
    "bare code value, a backquote in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY={s}`run()')",
    ),
    "bare code value, a semicolon in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY={s};run()')",
    ),
    "bare code value, an and in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY={s}&&run()')",
    ),
    "bare code value, a bracket in backquotes, python3 -c in sh -c": (
        "sh",
        "-c",
        "echo `python3 -c 'API_KEY={s})run()'`",
    ),
    "bare code value, a semicolon in backquotes, python3 -c in sh -c": (
        "sh",
        "-c",
        "echo `python3 -c 'API_KEY={s};run()'`",
    ),
    "bare code value, an and in backquotes, python3 -c in sh -c": (
        "sh",
        "-c",
        "echo `python3 -c 'API_KEY={s}&&run()'`",
    ),
    "quoted code value, a bracket, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\")run()'",
    ),
    "bare code value, a bracket, node -e in bash -c": ("bash", "-c", "node -e 'API_KEY={s})run()'"),
    "quoted code value, a backquote, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\"`run()'",
    ),
    "bare code value, a backquote, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY={s}`run()'",
    ),
    "quoted code value, a semicolon, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\";run()'",
    ),
    "bare code value, a semicolon, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY={s};run()'",
    ),
    "quoted code value, an and, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\"&&run()'",
    ),
    "bare code value, an and, node -e in bash -c": ("bash", "-c", "node -e 'API_KEY={s}&&run()'"),
    "quoted code value, a blank and a semicolon, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\" ;run()'",
    ),
    "bare code value, a blank and a semicolon, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY={s} ;run()'",
    ),
    "quoted code value, a blank and an and, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY=\"{s}\" &&run()'",
    ),
    "bare code value, a blank and an and, node -e in bash -c": (
        "bash",
        "-c",
        "node -e 'API_KEY={s} &&run()'",
    ),
    "quoted code value, a bracket in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\")run()')",
    ),
    "bare code value, a bracket in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s})run()')",
    ),
    "quoted code value, a backquote in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\"`run()')",
    ),
    "bare code value, a backquote in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s}`run()')",
    ),
    "quoted code value, a semicolon in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\";run()')",
    ),
    "bare code value, a semicolon in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s};run()')",
    ),
    "quoted code value, an and in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\"&&run()')",
    ),
    "bare code value, an and in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s}&&run()')",
    ),
    "quoted code value, a blank and a semicolon in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\" ;run()')",
    ),
    "bare code value, a blank and a semicolon in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s} ;run()')",
    ),
    "quoted code value, a blank and an and in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY=\"{s}\" &&run()')",
    ),
    "bare code value, a blank and an and in $(), node -e in bash -c": (
        "bash",
        "-c",
        "echo $(node -e 'API_KEY={s} &&run()')",
    ),
    "quoted code value, a bracket in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY=\"{s}\")run()'`",
    ),
    "bare code value, a bracket in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY={s})run()'`",
    ),
    "quoted code value, a semicolon in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY=\"{s}\";run()'`",
    ),
    "bare code value, a semicolon in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY={s};run()'`",
    ),
    "quoted code value, an and in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY=\"{s}\"&&run()'`",
    ),
    "bare code value, an and in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY={s}&&run()'`",
    ),
    "quoted code value, a blank and a semicolon in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY=\"{s}\" ;run()'`",
    ),
    "bare code value, a blank and a semicolon in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY={s} ;run()'`",
    ),
    "quoted code value, a blank and an and in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY=\"{s}\" &&run()'`",
    ),
    "bare code value, a blank and an and in backquotes, node -e in bash -c": (
        "bash",
        "-c",
        "echo `node -e 'API_KEY={s} &&run()'`",
    ),
}


def typed(words: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in words]


def another_closer(words: tuple[str, ...], closer: str) -> list[str]:
    """Return the words with the closer after the value changed to another one."""
    other = closer.replace(closer.strip(), ")" if closer.strip() == ";" else ";")
    text = words[2]
    at = text.index("{s}")
    at = text.index(closer, at)
    return [*words[:2], text[:at] + other + text[at + len(closer) :], *words[3:]]


@pytest.mark.parametrize("name", sorted(CLOSER_SHOWN))
def test_a_value_before_a_closer_is_hidden_and_the_closer_shown(name: str) -> None:
    words, _closer, shown = CLOSER_SHOWN[name]
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(("pairbench", "run", "--", *argv)) == SHOWN_LEAD + shown
        assert model.hashed_argv(argv) == shlex.split(shown)


@pytest.mark.parametrize("name", sorted(CLOSER_SHOWN))
def test_two_values_before_a_closer_give_one_hash_and_another_closer_another(name: str) -> None:
    words, closer, _shown = CLOSER_SHOWN[name]
    one, two = (typed(words, password) for password in PASSWORDS)
    changed = typed(tuple(another_closer(words, closer)), PASSWORDS[0])

    assert argv_sha256(one) == argv_sha256(two)
    assert argv_sha256(one) == argv_sha256(typed(words, PASSWORDS[0]))
    assert argv_sha256(changed) != argv_sha256(one)


@pytest.mark.parametrize("name", sorted(HIDDEN_TO_THE_END))
def test_a_value_hidden_with_its_closer_is_never_shown(name: str) -> None:
    words = HIDDEN_TO_THE_END[name]
    hashes = set()
    for password in PASSWORDS:
        argv = typed(words, password)
        shown = model.public_command(("pairbench", "run", "--", *argv))

        assert password not in shown
        assert password not in json.dumps(model.hashed_argv(argv))
        assert model.HIDDEN in shown
        assert model.hashed_argv(argv) == shlex.split(shown)[len(shlex.split(SHOWN_LEAD)) :]
        hashes.add(argv_sha256(argv))
    assert len(hashes) == 1


@pytest.mark.parametrize("name", sorted(TRIPLE_QUOTED))
def test_a_value_in_three_quotes_is_hidden_to_the_three_that_close_it(name: str) -> None:
    words = TRIPLE_QUOTED[name]
    hashes = set()
    for password in PASSWORDS:
        argv = typed(words, password)
        shown = model.public_command(("pairbench", "run", "--", *argv))

        assert password not in shown
        assert password not in json.dumps(model.hashed_argv(argv))
        assert model.hashed_argv(argv) == shlex.split(shown)[len(shlex.split(SHOWN_LEAD)) :]
        hashes.add(argv_sha256(argv))
    assert len(hashes) == 1


@pytest.mark.parametrize("name", sorted(JOINED_HIDDEN))
def test_a_value_joined_to_another_string_is_hidden_with_it(name: str) -> None:
    words, shown = JOINED_HIDDEN[name]
    hashes = set()
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(argv) == shown
        assert model.hashed_argv(argv) == shlex.split(shown)
        hashes.add(argv_sha256(argv))
    assert len(hashes) == 1


CONFIG_PAGE = Path(__file__).resolve().parents[3] / "docs" / "reference" / "config.md"

# Examples on the config reference, each as typed and as the page says it is shown.
CONFIG_PAGE_EXAMPLES = {
    "a string joined with ||": (
        """psql -c "ALTER ROLE app PASSWORD='made'||'VALUE'\"""",
        "psql -c 'ALTER ROLE app PASSWORD=<hidden>'",
    ),
    "three quotes in a shell text": (
        """sh -c "API_KEY='''a'b''' VALUE' ./bench-old\"""",
        "sh -c 'API_KEY=<hidden> ./bench-old'",
    ),
}


@pytest.mark.parametrize("name", sorted(CONFIG_PAGE_EXAMPLES))
def test_the_config_reference_shows_each_example_as_the_command_shows_it(name: str) -> None:
    typed, shown = CONFIG_PAGE_EXAMPLES[name]
    page = " ".join(CONFIG_PAGE.read_text(encoding="utf-8").split())

    assert f"`{typed}` shows `{shown}`" in page
    assert model.public_command(shlex.split(typed)) == shown


@pytest.mark.parametrize("name", sorted(THREE_QUOTES_IN_A_SHELL_TEXT))
def test_three_quotes_in_a_shell_text_hide_the_whole_shell_word(name: str) -> None:
    words, shown = THREE_QUOTES_IN_A_SHELL_TEXT[name]
    hashes = set()
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(argv) == shown
        assert model.hashed_argv(argv) == shlex.split(shown)
        hashes.add(argv_sha256(argv))
    assert len(hashes) == 1
