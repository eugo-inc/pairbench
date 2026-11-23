# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A path that ends at a home folder shows ``<hidden>`` in the shown command.

A path is shown as its last part, and the last part of ``/home/NAME``,
``/Users/NAME``, ``../home/NAME`` or ``~NAME`` is a user's name. Such a path
shows ``<hidden>`` in the shown command, while the hash takes it as typed, as
the known limits of the hashes say. A case id keeps the name, as the known
limits of the shown command say: a word ``~NAME`` with nothing after it as
typed, and a path that ends at the folder cut to that name, since a name
cannot tell such a home from a word such as ``~mask`` or a route such as
``/users/1``, so two ids that differ only there stay two cases. A path that
goes on into the folder, or a folder of that name elsewhere, shows its last
part as any path does. Every name is made up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import api, model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
H = model.HIDDEN
NAME = "zqname"
# Two made-up words that name a route under /users, as a web benchmark names one.
ROUTE_WORDS = ("new", "edit")

# (the argument, as the shown command gives it)
HOME_FORMS: dict[str, tuple[str, str]] = {
    "an absolute home folder": (f"/home/{NAME}", H),
    "an absolute home folder with a slash after it": (f"/home/{NAME}/", H),
    "a home folder under /Users": (f"/Users/{NAME}", H),
    "a home folder under /users": (f"/users/{NAME}", H),
    "a home folder after two slashes": (f"//home/{NAME}", H),
    "a home folder after a dot part": (f"/./home/{NAME}", H),
    "a home folder reached by climbing back": (f"/srv/../home/{NAME}", H),
    "a climbing home folder": (f"../home/{NAME}", H),
    "a home folder climbing twice": (f"../../home/{NAME}/", H),
    "a home folder climbing after a dot": (f"./../home/{NAME}", H),
    "a home folder climbing out of a folder": (f"data/../../home/{NAME}", H),
    "a user's home written with a tilde": (f"~{NAME}", H),
    "a user's home written with a tilde and a slash": (f"~{NAME}/", H),
    "a home folder given to an option": (f"--in=/home/{NAME}", f"--in={H}"),
    "a climbing home folder given to an option": (f"--in=../home/{NAME}", f"--in={H}"),
    "a home folder glued to an option": (f"-L/home/{NAME}", f"-L{H}"),
    "a home folder after a drive letter": (f"--in=C:/Users/{NAME}", f"--in=C:{H}"),
    "a home folder in a file address": (f"file:///home/{NAME}", f"file://{H}"),
    "a home folder in an address with no host": (f"sqlite:////Users/{NAME}", f"sqlite:///{H}"),
    "a home folder written with percent escapes": (f"--next=%2Fhome%2F{NAME}", f"--next=%2F{H}"),
    "a home folder whose name holds a blank": ("/home/zq name", H),
    "a home folder after a folder and its climb": (f"/home/zq/../{NAME}", H),
    "a home folder under /Users after a folder and its climb": (f"/Users/{NAME}/../{NAME}/", H),
    "a home folder as the last path of a list": (f"/usr/bin:/home/{NAME}", H),
    "a home folder with a mount mode as the last path of a list": (f"/data:/home/{NAME}:ro", H),
    "a home folder as the last path of a list joined by a comma": (f"/data,/home/{NAME}", H),
    "a tilde home as the last path of a list": (f"/usr/bin:~{NAME}", H),
    "a climbing home folder as the last path of a list": (f"/usr/bin:../home/{NAME}", H),
    "a list given to an option": (f"--in=/usr/bin:/home/{NAME}", f"--in={H}"),
    "a list in an assignment": (f"PATH=/usr/bin:/home/{NAME}", f"PATH={H}"),
    "a home folder after an equals sign in a path": (f"/srv/k=/home/{NAME}", H),
    "a home folder after an equals sign in a nested local address": (
        f"postgresql:///db?c=file:///made/k=/home/{NAME}&j=1",
        f"postgresql:///db?c=file://{H}&j=1",
    ),
    "a home folder after an equals sign in a climbing path in a query": (
        f"postgresql:///db?c=../made=/Users/{NAME}/",
        f"postgresql:///db?c={H}",
    ),
}

# (the argument, as the shown command gives it): a path that goes on into a home folder, a
# folder of that name elsewhere, and the folders that hold home folders.
KEPT_FORMS: dict[str, tuple[str, str]] = {
    "a path into a home folder": (f"/home/{NAME}/data", "data"),
    "a path into a user's home written with a tilde": (f"~{NAME}/data", "data"),
    "a folder under another folder": (f"/srv/{NAME}", NAME),
    "a folder under a home folder of a deeper folder": (f"/srv/app/home/{NAME}", NAME),
    "a folder under a climbing folder": (f"../x/home/{NAME}", NAME),
    "the folder of home folders": ("/home", "home"),
    "the folder of home folders with a slash": ("/home/", "home"),
    "a relative path that stays inside": (f"home/{NAME}", f"home/{NAME}"),
    "the user's own home": ("~", "~"),
    "the working folder of the shell": ("~+", "~+"),
    "the folder before it": ("~-", "~-"),
    "a folder of the folder stack": ("~1", "~1"),
    "a list whose last path is an ordinary folder": (f"/home/{NAME}:/data:ro", "data:ro"),
    "a list joined by a comma whose last path is an ordinary folder": (
        f"/home/{NAME},/data",
        "data",
    ),
    "a folder after a climb out of the folder of home folders": (f"/home/../srv/{NAME}", NAME),
}


def shown(arg: str) -> str:
    """Return the argument as the shown command gives it, the leading words left out."""
    return model.public_command((*LEAD, "made-up-tool", arg))[len(SHOWN_LEAD) :]


@pytest.mark.parametrize("name", list(HOME_FORMS))
def test_a_path_that_ends_at_a_home_folder_shows_hidden(name: str) -> None:
    arg, expected = HOME_FORMS[name]

    assert shown(arg) == "made-up-tool " + shlex.quote(expected)


@pytest.mark.parametrize("name", list(HOME_FORMS))
def test_the_hash_takes_a_home_folder_as_typed(name: str) -> None:
    arg, _expected = HOME_FORMS[name]

    assert model.hashed_argv(("made-up-tool", arg)) == ["made-up-tool", arg]


def test_two_home_folders_are_hashed_apart() -> None:
    first = model.hashed_argv(("made-up-tool", f"/home/{NAME}"))
    second = model.hashed_argv(("made-up-tool", "/home/zqother"))

    assert first != second


@pytest.mark.parametrize("name", list(KEPT_FORMS))
def test_other_paths_show_their_last_part(name: str) -> None:
    arg, expected = KEPT_FORMS[name]

    assert shown(arg) == "made-up-tool " + shlex.quote(expected)


# (the shell text, as shown): a shell reads ``~NAME`` as the user's home.
SHELL_FORMS: dict[str, tuple[str, str]] = {
    "a tilde home word": (f"made-up-tool ~{NAME}", f"made-up-tool {H}"),
    "a tilde home word with a slash": (f"made-up-tool ~{NAME}/", f"made-up-tool {H}"),
    "a tilde home word given to an option": (
        f"made-up-tool --in=~{NAME}",
        f"made-up-tool --in={H}",
    ),
    "a tilde home word in an assignment": (f"DATA=~{NAME} made-up-tool", f"DATA={H} made-up-tool"),
    "a tilde home before a variable of a list": (
        f"PATH=~{NAME}:$PATH made-up-tool",
        f"PATH={H}:$PATH made-up-tool",
    ),
    "an absolute home folder": (f"made-up-tool /home/{NAME}", f"made-up-tool {H}"),
    "a climbing home folder": (f"made-up-tool ../home/{NAME}", f"made-up-tool {H}"),
    "a path into a tilde home": (f"made-up-tool ~{NAME}/data", "made-up-tool data"),
    "the user's own home": ("made-up-tool ~ ~/", "made-up-tool ~ ~"),
    "a tilde inside a word": ("made-up-tool a~b HEAD~1", "made-up-tool a~b HEAD~1"),
}


@pytest.mark.parametrize("name", list(SHELL_FORMS))
def test_a_shell_text_shows_a_home_folder_hidden(name: str) -> None:
    text, expected = SHELL_FORMS[name]

    assert model.public_command((*LEAD, "sh", "-c", text)) == (
        SHOWN_LEAD + "sh -c " + shlex.quote(expected)
    )


# (the case id, as a results document shows it): a path that ends at a home folder is cut to the
# folder's name, as any path in a case id is cut to its last part, while a file inside the folder
# shows the file.
CASE_FORMS: dict[str, tuple[str, str]] = {
    "a home folder in brackets": (f"test_read[/home/{NAME}]", f"test_read[{NAME}]"),
    "a home folder under /Users": (f"test_read[/Users/{NAME}]", f"test_read[{NAME}]"),
    "a climbing home folder in brackets": (f"test_read[../home/{NAME}]", f"test_read[{NAME}]"),
    "a home folder reached through ..": (f"test_read[/home/a/../{NAME}]", f"test_read[{NAME}]"),
    "a file in a home folder": (f"test_read[/home/{NAME}/x.csv]", "test_read[x.csv]"),
    "a file in a tilde home": (f"test_read[~{NAME}/x.csv]", "test_read[x.csv]"),
    "a list that ends at a home folder": (f"bench[/usr/bin:/home/{NAME}]", f"bench[{NAME}]"),
    "a path that ends at a home folder after an equals sign": (
        f"bench[/srv/k=/home/{NAME}]",
        f"bench[{NAME}]",
    ),
}


@pytest.mark.parametrize("name", list(CASE_FORMS))
def test_a_case_id_cuts_a_home_folder_to_its_name(name: str) -> None:
    case, expected = CASE_FORMS[name]

    assert model.public_case(case) == expected
    assert model.public_case(expected) == expected
    assert model.public_words(case, case=True) == expected


@pytest.mark.parametrize("name", list(CASE_FORMS))
def test_the_shown_command_hides_a_home_folder_that_a_case_id_keeps(name: str) -> None:
    case, expected = CASE_FORMS[name]
    shown_text = expected.replace(NAME, H) if expected.endswith(f"{NAME}]") else expected

    # Read in both orders in one process, so that neither reading leaves the other's rule behind.
    assert model.public_words(case) == shown_text
    assert model.public_case(case) == expected
    assert model.public_words(case) == shown_text
    assert model.public_command((*LEAD, "made-up-tool", case)) == (
        SHOWN_LEAD + "made-up-tool " + shlex.quote(shown_text)
    )


def _sample(case: str) -> api.Sample:
    return api.Sample(case=case, metric="time", unit="s", better="lower", kind="time", value=1.5)


# Two case ids that differ only in the last part of a path under /home or /Users, each pair as
# read and as a results document shows it: a case id cannot tell such a path from a route, so it
# cuts each to its last part, as it cuts any path, and the two ids stay two cases.
ROUTE_CASE_PAIRS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "two routes in brackets": (
        ("test_get[/users/1]", "test_get[/users/2]"),
        ("test_get[1]", "test_get[2]"),
    ),
    "two routes after a method": (
        ("GET /users/7", "GET /users/8"),
        ("GET 7", "GET 8"),
    ),
    "two routes named by a word": (
        (f"test_x[/users/{ROUTE_WORDS[0]}]", f"test_x[/users/{ROUTE_WORDS[1]}]"),
        (f"test_x[{ROUTE_WORDS[0]}]", f"test_x[{ROUTE_WORDS[1]}]"),
    ),
    "two pages under /home": (
        ("test_route[/home/feed]", "test_route[/home/settings]"),
        ("test_route[feed]", "test_route[settings]"),
    ),
    "two routes under /Users": (
        ("test_api[/Users/1]", "test_api[/Users/2]"),
        ("test_api[1]", "test_api[2]"),
    ),
    "two routes glued with a colon": (("GET:/users/1", "GET:/users/2"), ("GET:1", "GET:2")),
    "two routes that end with a slash": (
        ("test_get[/users/1/]", "test_get[/users/2/]"),
        ("test_get[1]", "test_get[2]"),
    ),
    "two routes reached through ..": (
        ("t[/api/../users/1]", "t[/api/../users/2]"),
        ("t[1]", "t[2]"),
    ),
    "two home folders": (
        (f"test_read[/home/{NAME}]", "test_read[/home/zqother]"),
        (f"test_read[{NAME}]", "test_read[zqother]"),
    ),
    "two climbing home folders": (
        (f"test_read[../home/{NAME}]", "test_read[../home/zqother]"),
        (f"test_read[{NAME}]", "test_read[zqother]"),
    ),
}


@pytest.mark.parametrize("name", list(ROUTE_CASE_PAIRS))
def test_two_case_ids_that_differ_only_in_a_home_folder_path_stay_two_cases(name: str) -> None:
    ids, expected = ROUTE_CASE_PAIRS[name]

    read = api.public_cases([_sample(raw) for raw in ids], "made-up-driver")

    assert tuple(sample.case for sample in read) == expected


# Two case ids that differ only in a word that starts with ``~`` and a name, each pair as read
# and as a results document shows it: a case id cannot tell such a word from a user's home, so
# it keeps the word as typed and the two ids stay two cases.
TILDE_CASE_PAIRS: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "two words in a name": (("t ~alpha", "t ~beta"), ("t ~alpha", "t ~beta")),
    "two words in brackets": (("t[~alpha]", "t[~beta]"), ("t[~alpha]", "t[~beta]")),
    "two test parameters": (
        ("test_invert[~mask]", "test_invert[~bits]"),
        ("test_invert[~mask]", "test_invert[~bits]"),
    ),
    "two bitwise nots in code": (
        ("python3 -c 'print(~a)'", "python3 -c 'print(~b)'"),
        ("python3 -c 'print(~a)'", "python3 -c 'print(~b)'"),
    ),
    "two destructors": (
        ("BM_Dtor ~Widget", "BM_Dtor ~Gadget"),
        ("BM_Dtor ~Widget", "BM_Dtor ~Gadget"),
    ),
    "two values after a name": (("k=~v", "k=~w"), ("k=~v", "k=~w")),
    "two brace lists": (("x {~a,~b}", "x {~c,~d}"), ("x {~a,~b}", "x {~c,~d}")),
    "two words after a bracket": (("x(~a)", "x(~b)"), ("x(~a)", "x(~b)")),
    "two tilde homes": (
        (f"test_read[~{NAME}]", "test_read[~zqother]"),
        (f"test_read[~{NAME}]", "test_read[~zqother]"),
    ),
    "two tilde homes as the last path of a list": (
        ("bench /usr/bin:~zqa", "bench /usr/bin:~zqb"),
        ("bench bin:~zqa", "bench bin:~zqb"),
    ),
    "two tilde homes before a path of a list": (
        ("bench ~zqa:/data", "bench ~zqb:/data"),
        ("bench ~zqa:data", "bench ~zqb:data"),
    ),
}


@pytest.mark.parametrize("name", list(TILDE_CASE_PAIRS))
def test_two_case_ids_that_differ_only_in_a_tilde_word_stay_two_cases(name: str) -> None:
    ids, expected = TILDE_CASE_PAIRS[name]

    read = api.public_cases([_sample(raw) for raw in ids], "made-up-driver")

    assert tuple(sample.case for sample in read) == expected


def test_the_shown_command_hides_a_tilde_home_that_a_case_id_keeps() -> None:
    assert model.public_command((*LEAD, "made-up-tool", f"~{NAME}")) == (
        SHOWN_LEAD + "made-up-tool '<hidden>'"
    )
    assert model.public_words(f"made-up-tool ~{NAME}") == f"made-up-tool {H}"
    assert model.public_case(f"made-up-tool ~{NAME}") == f"made-up-tool ~{NAME}"


# (the text, as a message, a case id and a shell text show it): a ``~`` that starts no home
# folder of its own, as in a destructor's name, a call or a key pattern of a Redis access rule.
NOT_HOME_TEXTS: tuple[str, ...] = (
    "Widget::~Widget()",
    "BM_Dtor<Widget>::~Widget",
    "~Widget()",
    "obj.~Widget",
    "on ~jobs:* resetkeys",
    "on ~jobs:42 resetkeys",
    "on ~jobs:$TENANT:* resetkeys",
    "t ~alpha:$N",
    "~jobs* allcommands",
    "a~b HEAD~1",
)


@pytest.mark.parametrize("text", NOT_HOME_TEXTS)
def test_a_tilde_that_starts_no_home_folder_is_kept(text: str) -> None:
    assert model.public_text(text) == text
    assert model.public_case(text) == text
    assert model.public_command((*LEAD, "sh", "-c", f"made-up-tool {text}")) == (
        SHOWN_LEAD + "sh -c " + shlex.quote(f"made-up-tool {text}")
    )


# (the text, as shown): a tilde home word wherever it ends a word, also before another path.
TEXT_FORMS: dict[str, tuple[str, str]] = {
    "a tilde home word in a message": (f"cannot read ~{NAME}", f"cannot read {H}"),
    "a tilde home before another path of a list": (
        f"PATH=~{NAME}:/usr/bin",
        f"PATH={H}:bin",
    ),
    "a tilde home in a brace list": (f"{{~{NAME},~zqother}}", f"{{{H},{H}}}"),
    "a tilde home before a semicolon": (f"cd ~{NAME}; ls", f"cd {H}; ls"),
    "a tilde home before a variable of a list": (f"PATH=~{NAME}:$PATH", f"PATH={H}:$PATH"),
    "a tilde home before a braced variable of a list": (
        f"PATH=~{NAME}:${{PATH}}",
        f"PATH={H}:${{PATH}}",
    ),
}


@pytest.mark.parametrize("name", list(TEXT_FORMS))
def test_a_tilde_home_word_in_a_text_is_hidden(name: str) -> None:
    text, expected = TEXT_FORMS[name]

    assert model.public_text(text) == expected
    assert model.public_text(expected) == expected
