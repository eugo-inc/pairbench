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
}

# Forms whose closer or operator is hidden with the value, with the rest of the word: in the
# text of ``-c`` a value in quotes ends at its quote only before ``;``, ``,``, ``)``, ``]`` or
# ``}``, a bare value runs to the end of the word, and the text of ``node -e`` is not read as
# code. The value is still never shown, and the shown command and the hash agree.
HIDDEN_TO_THE_END: dict[str, tuple[str, ...]] = {
    "bare code value, a bracket, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY={s})run()'",
    ),
    "quoted code value, a backquote, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY=\"{s}\"`run()'",
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
    "quoted code value, an and, python3 -c in sh -c": (
        "sh",
        "-c",
        "python3 -c 'API_KEY=\"{s}\"&&run()'",
    ),
    "bare code value, an and, python3 -c in sh -c": ("sh", "-c", "python3 -c 'API_KEY={s}&&run()'"),
    "bare code value, a bracket in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY={s})run()')",
    ),
    "quoted code value, a backquote in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY=\"{s}\"`run()')",
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
    "quoted code value, an and in $(), python3 -c in sh -c": (
        "sh",
        "-c",
        "echo $(python3 -c 'API_KEY=\"{s}\"&&run()')",
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
    "quoted code value, an and in backquotes, python3 -c in sh -c": (
        "sh",
        "-c",
        "echo `python3 -c 'API_KEY=\"{s}\"&&run()'`",
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
