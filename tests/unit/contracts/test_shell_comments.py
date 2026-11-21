# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A comment in a shell text ends the command before it, as the shell reads it.

A word that starts with ``#`` outside quotes starts a comment, which the shell
reads to the end of its line, so a Redis or Valkey password before it is the
last word of its command: ``redis-cli AUTH PASSWORD  # log in`` gives a
password and no user name. The password is hidden whole in the shown command
of ``sh -c``, in one text and in the hash, which is the same whatever the
password; the comment is shown as typed, after a credential setting too. A
value the command still waits for, glued to the ``#`` (``-a #PASSWORD``), is
hidden as that value, since the text holds it whether or not the shell drops
it, and a word glued to the ``#`` after the password of ``AUTH`` is hidden as
well. A comment where no value is waited for is shown as typed. A
``#`` inside a word (``app#1``), inside quotes, after a backslash or after
``$`` starts no comment, so such a word before the password is the user name
and stays shown. One text that holds a line break reads the client's ``AUTH``
as one line does, while a ``SET`` of the client there still starts a
setting. Every value is made up; each password is a word of small letters
that no command writes by itself.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
# Two made-up passwords: a command with one is hashed as the command with the other is.
PASSWORDS = ("zqmkiwi", "zqmplum")

# (the shell text with ``{pw}`` where its password stands, the text in the shown command of
# ``sh -c``, the text as one text shows it)
FORMS: dict[str, tuple[str, str, str]] = {
    "a comment after two spaces, then the next line": (
        "redis-cli AUTH {pw}  # log in\n./bench",
        "redis-cli AUTH <hidden>  # log in\n./bench",
        "redis-cli AUTH <hidden> # log in ./bench",
    ),
    # The word glued to the # may be the password whose # was meant as part of it: hidden too.
    "a comment glued to its #, then the next line": (
        "redis-cli AUTH {pw} #log in\n./bench",
        "redis-cli AUTH <hidden> <hidden> in\n./bench",
        "redis-cli AUTH <hidden> <hidden> in ./bench",
    ),
    "a comment at the end of the text": (
        "redis-cli AUTH {pw} # log in",
        "redis-cli AUTH <hidden> # log in",
        "redis-cli AUTH <hidden> # log in",
    ),
    "a comment after a tab": (
        "valkey-cli AUTH {pw}\t# log in",
        "valkey-cli AUTH <hidden>\t# log in",
        "valkey-cli AUTH <hidden> # log in",
    ),
    "a bare # at the end": (
        "redis-cli AUTH {pw} #",
        "redis-cli AUTH <hidden> #",
        "redis-cli AUTH <hidden> #",
    ),
    "a user name and a comment": (
        "redis-cli AUTH made-up-user {pw} # c",
        "redis-cli AUTH made-up-user <hidden> # c",
        "redis-cli AUTH made-up-user <hidden> # c",
    ),
    "hello with a user name and a comment": (
        "redis-cli HELLO 3 AUTH made-up-user {pw} # c",
        "redis-cli HELLO 3 AUTH made-up-user <hidden> # c",
        "redis-cli HELLO 3 AUTH made-up-user <hidden> # c",
    ),
    "migrate and a comment": (
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH {pw} # c",
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH <hidden> # c",
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH <hidden> # c",
    ),
    "a separator before the comment": (
        "redis-cli AUTH {pw} ; # c",
        "redis-cli AUTH <hidden> ; # c",
        "redis-cli AUTH <hidden> ; # c",
    ),
    "a comment glued to a separator": (
        "redis-cli AUTH {pw};#c",
        "redis-cli AUTH <hidden>;#c",
        "redis-cli AUTH <hidden>;#c",
    ),
    "a comment line before": (
        "# log in first\nredis-cli AUTH {pw}",
        "# log in first\nredis-cli AUTH <hidden>",
        "# log in first redis-cli AUTH <hidden>",
    ),
    "a comment, then the next command logs in": (
        "redis-cli AUTH {pw} # c\nredis-cli AUTH {pw}",
        "redis-cli AUTH <hidden> # c\nredis-cli AUTH <hidden>",
        "redis-cli AUTH <hidden> # c redis-cli AUTH <hidden>",
    ),
    "a credential setting and a comment": (
        "redis-cli CONFIG SET requirepass {pw} # c",
        "redis-cli CONFIG SET requirepass <hidden> # c",
        "redis-cli CONFIG SET requirepass <hidden> # c",
    ),
    "a password option and a comment": (
        "redis-cli -a {pw} # c",
        "redis-cli -a <hidden> # c",
        "redis-cli -a <hidden> # c",
    ),
    "an access rule on its line, then the next line": (
        "redis-cli ACL SETUSER app on >{pw}\n./bench",
        "redis-cli ACL SETUSER app on ><hidden>\n./bench",
        "redis-cli ACL SETUSER app on ><hidden> ./bench",
    ),
    "a quoted command of a client on its line, then the next line": (
        "redis-benchmark -n 10 'AUTH {pw}'\n./bench",
        "redis-benchmark -n 10 'AUTH <hidden>'\n./bench",
        "redis-benchmark -n 10 AUTH <hidden> ./bench",
    ),
    # A credential setting hides the later words of its command, and the comment is none of them.
    "a credential setting of a tool and a comment": (
        "aws configure set aws_secret_access_key {pw} # rotate monthly",
        "aws configure set aws_secret_access_key <hidden> # rotate monthly",
        "aws configure set aws_secret_access_key <hidden> # rotate monthly",
    ),
    "a variable set by a shell and a comment": (
        "set -gx HF_TOKEN {pw} # made-up note",
        "set -gx HF_TOKEN <hidden> # made-up note",
        "set -gx HF_TOKEN <hidden> # made-up note",
    ),
    # A comment glued to its # after a value the command has taken is shown.
    "a password option, its value and a comment glued to its #": (
        "redis-cli -a {pw} #c",
        "redis-cli -a <hidden> #c",
        "redis-cli -a <hidden> #c",
    ),
    "a credential setting of a tool, its value and a comment glued to its #": (
        "aws configure set aws_secret_access_key {pw} #note",
        "aws configure set aws_secret_access_key <hidden> #note",
        "aws configure set aws_secret_access_key <hidden> #note",
    ),
    "an access rule and a comment glued to its #": (
        "redis-cli ACL SETUSER app on >{pw} #c",
        "redis-cli ACL SETUSER app on ><hidden> #c",
        "redis-cli ACL SETUSER app on ><hidden> #c",
    ),
}

# A value the command still waits for, glued to a # that starts a comment: the shell drops it,
# and the text still holds it, so it is hidden as that value. The comment ends the command.
WAITING_FORMS: dict[str, tuple[str, str, str]] = {
    "a password option": (
        "redis-cli -a #{pw} PING",
        "redis-cli -a <hidden> PING",
        "redis-cli -a <hidden> PING",
    ),
    "a password option at the end": (
        "redis-cli -a #{pw}",
        "redis-cli -a <hidden>",
        "redis-cli -a <hidden>",
    ),
    "a long password option after a user name": (
        "redis-cli --user app --pass #{pw}",
        "redis-cli --user app --pass <hidden>",
        "redis-cli --user app --pass <hidden>",
    ),
    "auth": (
        "redis-cli AUTH #{pw}",
        "redis-cli AUTH <hidden>",
        "redis-cli AUTH <hidden>",
    ),
    "auth, then more words of the comment": (
        "redis-cli AUTH #{pw} made-up",
        "redis-cli AUTH <hidden> made-up",
        "redis-cli AUTH <hidden> made-up",
    ),
    # The shell gives the user name as the password, so both are hidden.
    "auth and a user name": (
        "redis-cli AUTH made-up-user #{pw}",
        "redis-cli AUTH <hidden> <hidden>",
        "redis-cli AUTH <hidden> <hidden>",
    ),
    "hello with a user name": (
        "redis-cli HELLO 3 AUTH made-up-user #{pw}",
        "redis-cli HELLO 3 AUTH made-up-user <hidden>",
        "redis-cli HELLO 3 AUTH made-up-user <hidden>",
    ),
    "migrate": (
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH #{pw}",
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH <hidden>",
        "redis-cli MIGRATE 127.0.0.1 6380 key 0 5000 AUTH <hidden>",
    ),
    "a credential setting of the client": (
        "redis-cli CONFIG SET requirepass #{pw}",
        "redis-cli CONFIG SET requirepass <hidden>",
        "redis-cli CONFIG SET requirepass <hidden>",
    ),
    "the hash rule of an access rule list": (
        "redis-cli ACL SETUSER app on #{pw}",
        "redis-cli ACL SETUSER app on #<hidden>",
        "redis-cli ACL SETUSER app on #<hidden>",
    ),
    "a token option of a tool": (
        "./bench --token #{pw}",
        "./bench --token <hidden>",
        "./bench --token <hidden>",
    ),
    "a credential setting of a tool": (
        "aws configure set aws_secret_access_key #{pw}",
        "aws configure set aws_secret_access_key <hidden>",
        "aws configure set aws_secret_access_key <hidden>",
    ),
}

# A comment where no value is waited for is shown as typed.
# (the shell text, shown as typed in ``sh -c``, and the text as one text shows it)
COMMENTS_SHOWN: dict[str, tuple[str, str]] = {
    "after an ordinary option and its value": (
        "./bench --threads 8 #made-up-note",
        "./bench --threads 8 #made-up-note",
    ),
    "glued to its # after an ordinary option": (
        "./bench --threads #made-up-note",
        "./bench --threads #made-up-note",
    ),
    "a bare # after a password option": (
        "redis-cli -a # made-up-note",
        "redis-cli -a # made-up-note",
    ),
    "after a client's command": (
        "redis-cli PING #made-up-note",
        "redis-cli PING #made-up-note",
    ),
    "on the line after a password option": (
        "redis-cli -a\n#made-up-note",
        "redis-cli -a #made-up-note",
    ),
}

# A ``#`` that starts no comment: the word that holds it is the user name, before the password.
SHOWN_FORMS: dict[str, tuple[str, str, str]] = {
    "inside a word": (
        "redis-cli AUTH app#1 {pw}",
        "redis-cli AUTH app#1 <hidden>",
        "redis-cli AUTH app#1 <hidden>",
    ),
    "inside single quotes": (
        "redis-cli AUTH '#app' {pw}",
        "redis-cli AUTH '#app' <hidden>",
        "redis-cli AUTH #app <hidden>",
    ),
    "inside double quotes": (
        'redis-cli AUTH "#app" {pw}',
        'redis-cli AUTH "#app" <hidden>',
        "redis-cli AUTH #app <hidden>",
    ),
    "after a backslash": (
        "redis-cli AUTH \\#app {pw}",
        "redis-cli AUTH \\#app <hidden>",
        "redis-cli AUTH #app <hidden>",
    ),
    "after a dollar sign": (
        "redis-cli AUTH $# {pw}",
        "redis-cli AUTH $# <hidden>",
        "redis-cli AUTH $# <hidden>",
    ),
}

ALL_FORMS = {**FORMS, **SHOWN_FORMS, **{f"waiting: {k}": v for k, v in WAITING_FORMS.items()}}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ALL_FORMS))
def test_a_password_before_a_comment_is_hidden_in_the_shown_command(
    name: str, password: str
) -> None:
    text, shown, _words = ALL_FORMS[name]

    assert model.public_command((*LEAD, "sh", "-c", text.format(pw=password))) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", shown])
    )


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ALL_FORMS))
def test_a_password_before_a_comment_is_hidden_in_one_text(name: str, password: str) -> None:
    text, _shown, words = ALL_FORMS[name]

    assert model.public_words(text.format(pw=password)) == words


@pytest.mark.parametrize("name", list(COMMENTS_SHOWN))
def test_a_comment_where_no_value_is_waited_for_is_shown(name: str) -> None:
    text, words = COMMENTS_SHOWN[name]

    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", text]
    )
    assert model.public_words(text) == words


@pytest.mark.parametrize("password", PASSWORDS)
def test_a_set_of_a_client_in_one_text_of_several_lines_starts_a_setting(password: str) -> None:
    # On one line ``SET`` is the client's command and writes a key; with a line break in the
    # text it names a setting, whose value is hidden.
    text = f"redis-cli SET password {password}\n./bench"

    assert model.public_words(text) == "redis-cli SET password <hidden> ./bench"


@pytest.mark.parametrize("name", list(ALL_FORMS))
def test_the_hash_of_a_text_with_a_comment_is_the_same_whatever_its_password(name: str) -> None:
    text, _shown, _words = ALL_FORMS[name]
    hashed = [model.hashed_argv(("sh", "-c", text.format(pw=password))) for password in PASSWORDS]

    assert hashed[0] == hashed[1]
    for password, inputs in zip(PASSWORDS, hashed, strict=True):
        assert password not in json.dumps(inputs)
