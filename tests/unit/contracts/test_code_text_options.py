# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The text after ``node -e`` and ``perl -e`` is read as any argument is, and backquotes close.

Perl and JavaScript end a string where a reading of the text as Python's does not: Perl's
``q{...}``, ``qq/.../`` and here-documents, a pattern, Perl's ``.``, JavaScript's ``||``, ``?:``
and ``new``, a tagged template. So a credential value glued to its name in the text of
``node -e``, ``node -p``, ``perl -e`` or ``perl -lne`` hides the rest of the text, as the value of
any argument does, and two texts that differ only after the value give one hash.

A value in backquotes, a template string of JavaScript or a command of Perl or of a shell, is
hidden to the backquote that closes it, blanks and ``${...}`` parts and all, wherever a value
in code is read: after a name and `` = `` in any argument, and in the text of ``python3 -c`` or
``sh -c``.
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
QUOTED = "API_KEY='{s}';run()"
QUOTED_SHOWN = "'API_KEY=<hidden>'"
PERL_QUOTED = "$API_KEY='{s}';run()"
PERL_SHOWN = "'$API_KEY=<hidden>'"

# The text of node or perl in each way it is given, and words that are no such text: the
# argument list with ``{s}`` for the value, and the shown command, which the hash is taken over.
NODE_AND_PERL: dict[str, tuple[tuple[str, ...], str]] = {
    "node -e": (("node", "-e", QUOTED), "node -e " + QUOTED_SHOWN),
    "node --eval": (("node", "--eval", QUOTED), "node --eval " + QUOTED_SHOWN),
    "node -p": (("node", "-p", QUOTED), "node -p " + QUOTED_SHOWN),
    "node --print": (("node", "--print", QUOTED), "node --print " + QUOTED_SHOWN),
    "node -pe": (("node", "-pe", QUOTED), "node -pe " + QUOTED_SHOWN),
    "nodejs -e": (("nodejs", "-e", QUOTED), "nodejs -e " + QUOTED_SHOWN),
    "node -r MODULE -e": (
        ("node", "-r", "made-up-module", "-e", QUOTED),
        "node -r made-up-module -e " + QUOTED_SHOWN,
    ),
    "env node -e": (("env", "node", "-e", QUOTED), "env node -e " + QUOTED_SHOWN),
    "perl -e": (("perl", "-e", PERL_QUOTED), "perl -e " + PERL_SHOWN),
    "perl -E": (("perl", "-E", PERL_QUOTED), "perl -E " + PERL_SHOWN),
    "perl -lne": (("perl", "-lne", PERL_QUOTED), "perl -lne " + PERL_SHOWN),
    "perl -l -n -e": (("perl", "-l", "-n", "-e", PERL_QUOTED), "perl -l -n -e " + PERL_SHOWN),
    "perl -pi -e": (("perl", "-pi", "-e", PERL_QUOTED), "perl -pi -e " + PERL_SHOWN),
    "perl -MMODULE -e": (
        ("perl", "-MList::Util=sum", "-e", PERL_QUOTED),
        "perl -MList::Util=sum -e " + PERL_SHOWN,
    ),
    "node -e in sh -c": (
        ("sh", "-c", "node -e \"API_KEY='{s}';run()\""),
        "sh -c 'node -e \"API_KEY=<hidden>\"'",
    ),
    "grep -e": (("grep", "-e", QUOTED), "grep -e " + QUOTED_SHOWN),
    "sed -e": (("sed", "-e", QUOTED), "sed -e " + QUOTED_SHOWN),
    "perl -ie": (("perl", "-ie", QUOTED), "perl -ie " + QUOTED_SHOWN),
    "perl -Mbase": (("perl", "-Mbase", QUOTED), "perl -Mbase " + QUOTED_SHOWN),
    "a word after the text of node -e": (
        ("node", "-e", "run()", QUOTED),
        "node -e 'run()' " + QUOTED_SHOWN,
    ),
    "a word after the text of perl -e": (
        ("perl", "-e", "run()", QUOTED),
        "perl -e 'run()' " + QUOTED_SHOWN,
    ),
}

# Glued values in the text of node -e and perl -e whose end a reading of the text as Python's
# cannot find: Perl's q{...} and qq/.../, a here-document, Perl's ``.`` and JavaScript's
# ``||``, ``?:`` and ``new``, a pattern, a tagged template, and a bare value with a blank. Each
# is hidden to the end of the text, as the value of any argument is.
GLUED: dict[str, tuple[tuple[str, ...], str]] = {
    "q{...}, perl -e": (
        ("perl", "-e", "$API_KEY=q{made {s}};run()"),
        "perl -e '$API_KEY=<hidden>'",
    ),
    "q{...}, perl -lne": (
        ("perl", "-lne", "$API_KEY=q{made {s}};run()"),
        "perl -lne '$API_KEY=<hidden>'",
    ),
    "qq/.../, perl -e": (
        ("perl", "-e", "$API_KEY=qq/made {s}/;run()"),
        "perl -e '$API_KEY=<hidden>'",
    ),
    "a here-document, perl -e": (
        ("perl", "-e", "$API_KEY=<<END;\nmade {s}\nEND\nrun()"),
        "perl -e '$API_KEY=<hidden>'",
    ),
    "a join with a dot, perl -e": (
        ("perl", "-e", '$API_KEY="a" . "made {s}";run()'),
        "perl -e '$API_KEY=<hidden>'",
    ),
    "a pattern, perl -e": (
        ("perl", "-e", "$API_KEY=/made {s}/;run()"),
        "perl -e '$API_KEY=<hidden>'",
    ),
    "a bare value with a blank, perl -E": (
        ("perl", "-E", "$API_KEY=made {s};run()"),
        "perl -E '$API_KEY=<hidden>'",
    ),
    "a tagged template, node -e": (
        ("node", "-e", "API_KEY=String.raw`made {s}`;run()"),
        "node -e 'API_KEY=<hidden>'",
    ),
    "a pattern, node -e": (
        ("node", "-e", "API_KEY=/made {s}/;run()"),
        "node -e 'API_KEY=<hidden>'",
    ),
    "a choice, node -e": (
        ("node", "-e", "API_KEY=x ? 'made {s}' : y;run()"),
        "node -e 'API_KEY=<hidden>'",
    ),
    "a new object, node -e": (
        ("node", "-e", "API_KEY=new String('made {s}');run()"),
        "node -e 'API_KEY=<hidden>'",
    ),
    "an or, node -e": (
        ("node", "-e", 'API_KEY="a" || "made {s}";run()'),
        "node -e 'API_KEY=<hidden>'",
    ),
    "a bare value with a blank, node --print": (
        ("node", "--print", "API_KEY=q made {s}"),
        "node --print 'API_KEY=<hidden>'",
    ),
    "a bare value with a blank, node -e": (
        ("node", "-e", "API_KEY=made {s};run()"),
        "node -e 'API_KEY=<hidden>'",
    ),
}

# Values in backquotes that hold a blank: the value runs to the backquote that closes it.
BACKQUOTED: dict[str, tuple[tuple[str, ...], str]] = {
    "a template string, node -e": (
        ("node", "-e", "process.env.API_KEY = `made {s}`;run()"),
        "node -e 'process.env.API_KEY = <hidden>;run()'",
    ),
    "a template string as a key's value, node -e": (
        ("node", "-e", "const t = {apiKey: `made {s}`}; run(t)"),
        "node -e 'const t = {apiKey: <hidden>}; run(t)'",
    ),
    "a template string with a part, node -e": (
        ("node", "-e", "API_KEY = `a${b} {s}`;run()"),
        "node -e 'API_KEY = <hidden>;run()'",
    ),
    "a template string with a template in a part, node -e": (
        ("node", "-e", "API_KEY = `a${f(`b c`)} {s}`;run()"),
        "node -e 'API_KEY = <hidden>;run()'",
    ),
    "a template string with a brace in a string in a part, node -e": (
        ("node", "-e", "API_KEY = `a${'}'} {s}`;run()"),
        "node -e 'API_KEY = <hidden>;run()'",
    ),
    "a template string with a backquote in a string in a part, node -e": (
        ("node", "-e", "API_KEY = `a${'`'} {s}`;run()"),
        "node -e 'API_KEY = <hidden>;run()'",
    ),
    "a template string with a backquote after a backslash, node -e": (
        ("node", "-e", "API_KEY = `a\\` {s}`;run()"),
        "node -e 'API_KEY = <hidden>;run()'",
    ),
    "a template string not closed, node -e": (
        ("node", "-e", "API_KEY = `made {s}"),
        "node -e 'API_KEY = <hidden>'",
    ),
    "a template string, node -e in sh -c": (
        ("sh", "-c", "node -e 'process.env.API_KEY = `made {s}`;run()'"),
        "sh -c 'node -e '\"'\"'process.env.API_KEY = <hidden>;run()'\"'\"''",
    ),
    "a command, perl -e": (
        ("perl", "-e", "$API_KEY = `made {s}`; run()"),
        "perl -e '$API_KEY = <hidden>; run()'",
    ),
    "backquotes, python3 -c": (
        ("python3", "-c", "API_KEY = `made {s}`;run()"),
        "python3 -c 'API_KEY = <hidden>;run()'",
    ),
    "backquotes, python3 -c in sh -c": (
        ("sh", "-c", "python3 -c 'API_KEY = `made {s}`'"),
        "sh -c 'python3 -c '\"'\"'API_KEY = <hidden>'\"'\"''",
    ),
    "a command of a shell, sh -c": (
        ("sh", "-c", "API_KEY=`echo made {s}` ./run"),
        "sh -c 'API_KEY=<hidden> ./run'",
    ),
    "a command of a shell before a semicolon, sh -c": (
        ("sh", "-c", "export API_KEY=`printf made {s}`; ./run"),
        "sh -c 'export API_KEY=<hidden>; ./run'",
    ),
}

# Values that open with backquotes and go on past the closing one in the same word: what is
# glued after the closing backquote is more of the value, in a setting's text, in code and in
# a shell's word, so it is hidden with it and two values give one hash.
BACKQUOTED_GLUED: dict[str, tuple[tuple[str, ...], str]] = {
    "letters after the closing backquote, a setting": (
        ("./bench", "--config", "{password: `a`{s}}"),
        "./bench --config '{password: <hidden>}'",
    ),
    "letters after the closing backquote, a setting with more keys": (
        ("./bench", "--config", "{password: `a`{s}, threads: 8}"),
        "./bench --config '{password: <hidden>, threads: 8}'",
    ),
    "a semicolon in the letters after the closing backquote, a setting": (
        ("./bench", "--config", "{password: `a`ki;{s}}"),
        "./bench --config '{password: <hidden>}'",
    ),
    "a bracket in the letters after the closing backquote, a setting": (
        ("./bench", "--config", "{password: `a`ki){s}}"),
        "./bench --config '{password: <hidden>}'",
    ),
    "a second pair of backquotes, a setting": (
        ("./bench", "--config", "{password: `a``{s}`}"),
        "./bench --config '{password: <hidden>}'",
    ),
    "letters after the closing backquote, an argument": (
        ("./bench", "API_KEY = `a`{s}"),
        "./bench 'API_KEY = <hidden>'",
    ),
    "letters after the closing backquote, node -e": (
        ("node", "-e", "API_KEY = `a`{s};run()"),
        "node -e 'API_KEY = <hidden>'",
    ),
    "letters after the closing backquote, python3 -c": (
        ("python3", "-c", "API_KEY = `a`{s}"),
        "python3 -c 'API_KEY = <hidden>'",
    ),
    "letters after the closing backquote, a setting in sh -c": (
        ("sh", "-c", "tool --config '{password: `a`{s}}' && ./bench-old"),
        "sh -c 'tool --config '\"'\"'{password: <hidden>}'\"'\"' && ./bench-old'",
    ),
    "letters after a command of a shell, sh -c": (
        ("sh", "-c", "API_KEY=`echo a`{s} ./bench-old"),
        "sh -c 'API_KEY=<hidden> ./bench-old'",
    ),
    "letters after a command of a shell before a semicolon, sh -c": (
        ("sh", "-c", "export API_KEY=`echo a`{s}; ./bench-old"),
        "sh -c 'export API_KEY=<hidden>; ./bench-old'",
    ),
}


def typed(words: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in words]


def check_hidden(words: tuple[str, ...], shown: str) -> None:
    """Check the shown command and the hash of the form for each password."""
    hashes = set()
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(argv) == shown
        assert password not in json.dumps(model.hashed_argv(argv))
        assert model.hashed_argv(argv) == shlex.split(shown)
        hashes.add(argv_sha256(argv))
    assert len(hashes) == 1


@pytest.mark.parametrize("name", sorted(NODE_AND_PERL))
def test_a_glued_quoted_value_in_the_text_of_node_or_perl_hides_the_rest_of_it(name: str) -> None:
    check_hidden(*NODE_AND_PERL[name])


@pytest.mark.parametrize("name", sorted(NODE_AND_PERL))
def test_another_statement_after_the_value_gives_the_same_hash(name: str) -> None:
    words, _shown = NODE_AND_PERL[name]
    other = tuple(word.replace("run()", "walk()") if "{s}" in word else word for word in words)

    assert argv_sha256(typed(other, PASSWORDS[0])) == argv_sha256(typed(words, PASSWORDS[0]))


def test_a_node_named_by_its_path_hides_the_rest_of_its_text_too() -> None:
    argv = typed(("/usr/local/bin/node", "-e", QUOTED), PASSWORDS[0])

    assert model.public_command(argv) == "node -e " + QUOTED_SHOWN
    assert model.hashed_argv(argv) == ["/usr/local/bin/node", "-e", "API_KEY=<hidden>"]


@pytest.mark.parametrize("name", sorted(GLUED))
def test_a_glued_value_in_the_text_of_node_or_perl_is_hidden_to_the_end_of_the_text(
    name: str,
) -> None:
    check_hidden(*GLUED[name])


@pytest.mark.parametrize("name", sorted(BACKQUOTED))
def test_a_value_in_backquotes_is_hidden_to_the_backquote_that_closes_it(name: str) -> None:
    check_hidden(*BACKQUOTED[name])


@pytest.mark.parametrize("name", sorted(BACKQUOTED_GLUED))
def test_what_is_glued_after_a_closing_backquote_is_hidden_with_the_value(name: str) -> None:
    check_hidden(*BACKQUOTED_GLUED[name])


CONFIG_PAGE = Path(__file__).resolve().parents[3] / "docs" / "reference" / "config.md"
# Each example the config reference gives of these rules: the command as typed and as shown.
PAGE_EXAMPLES = (
    (("sh", "-c", "API_KEY=`echo made VALUE` ./bench-old"), "sh -c 'API_KEY=<hidden> ./bench-old'"),
    (
        ("node", "-e", "process.env.API_KEY = `made VALUE`;run_old()"),
        "node -e 'process.env.API_KEY = <hidden>;run_old()'",
    ),
    (("node", "-e", 'API_KEY="VALUE";run_old()'), "node -e 'API_KEY=<hidden>'"),
    (
        ("./bench", "--config", "{password: `a`VALUE}"),
        "./bench --config '{password: <hidden>}'",
    ),
)


def page_text() -> str:
    """The config reference with its lines joined, so a phrase broken across lines is found."""
    return " ".join(CONFIG_PAGE.read_text(encoding="utf-8").split())


def code_span(text: str) -> str:
    """The text as the page writes it in code: in two backquotes and blanks when it holds one."""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


@pytest.mark.parametrize(("argv", "shown"), PAGE_EXAMPLES)
def test_the_config_reference_shows_what_the_command_shows(
    argv: tuple[str, ...], shown: str
) -> None:
    assert f"{code_span(shlex.join(argv))} shows {code_span(shown)}" in page_text()
    assert model.public_command(argv) == shown
