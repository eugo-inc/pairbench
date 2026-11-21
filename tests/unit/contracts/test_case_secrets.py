# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A case id hides the secret forms the shown command hides.

The id a driver reads for a case is shown in ``results.json``, ``results.md`` and
``report.html``, and the capture records it as shown. So the value of a credential-like name
or option (``test_db[PGPASSWORD=V]``, ``test_db[--password=V]``, ``bench[token=V]``,
``bench[api_key=V]``, ``bench/PGPASSWORD=V/latency``), a password before a host written
without a scheme (``bench[bob:V@db.example:5432]``) and a long random-looking value
(``test_api[R]``) are hidden in it, and the words in a pair of brackets, or of an id with no
brackets, are read as the words of a command: a client's password option
(``bench[redis-cli -a V PING]``, ``bench[mysql -pV]``), a credential-like option and its next
word (``bench[tool --token V]``), a scheme word glued to such an option and the token after it
(``bench[tool --auth=Basic V]``) and a credential header (``bench[curl -H Authorization:
Bearer V]``) hide their value. A credential-like name glued to its value with ``:``
(``test_db[token:V]``, ``BM_Auth/password:V``) hides it too, but a whole number after a ``/``
is a benchmark's named argument and is kept (``BM_Hash/key:3``). Each row is cleaned with two
made-up values: no six characters in a row of either show, and both give the same id. A host
or a user alone, a path's last part and the ``/`` that joins the parts of a name are kept. Two
ids that read the same once hidden are refused with ``E_USAGE``, never pooled into one case,
and the refusal names only the id as shown.
"""

from __future__ import annotations

import pytest

from pairbench import api, model
from pairbench.errors import Refusal

# Two made-up values for ``{v}``, and two made-up values of 32 letters and digits that read as
# random for ``{r}``.
VALUES = ("zq-made-up-kiwi7", "zq-made-up-pear3")
RANDOMS = ("EXAMPLEqQ7xK2mP9vL4nR8tW3yZ6bC1d", "EXAMPLEwM4cT8bN2xQ6zK9pL3vR7yH1g")
# Each case id with a secret, and what every fill of it shows.
HIDDEN = {
    "test_db[PGPASSWORD={v}]": "test_db[PGPASSWORD=<hidden>]",
    "test_db[--password={v}]": "test_db[--password=<hidden>]",
    "bench[bob:{v}@db.example:5432]": "bench[bob:<hidden>@db.example:5432]",
    "bench/PGPASSWORD={v}/latency": "bench/PGPASSWORD=<hidden>/latency",
    "test_api[{r}]": "test_api[<hidden>]",
    "bench[token={v}]": "bench[token=<hidden>]",
    "bench[api_key={v}]": "bench[api_key=<hidden>]",
    "bench[a=1,api_key={v},b=2]": "bench[a=1,api_key=<hidden>,b=2]",
    "bench[bob:{v}@db.example]": "bench[bob:<hidden>@db.example]",
    "bench[bob:{v}@192.0.2.10]": "bench[bob:<hidden>@192.0.2.10]",
    "bench[bob:{v}@localhost:6379]": "bench[bob:<hidden>@localhost:6379]",
    "bench/token={v}": "bench/token=<hidden>",
    "test_x[{r}]/cpu_time": "test_x[<hidden>]/cpu_time",
    # The words in a pair of brackets, read as the words of a command.
    "bench[redis-cli -a {v} PING]": "bench[redis-cli -a <hidden> PING]",
    "bench[mysql -p{v} -e select 1]": "bench[mysql -p<hidden> -e select 1]",
    "bench[tool --token {v}]": "bench[tool --token <hidden>]",
    "bench[curl -H Authorization: Bearer {v} https://db.example/]": (
        "bench[curl -H Authorization: <hidden>]"
    ),
    "bench[tool password: {v}]": "bench[tool password: <hidden>]",
    "test_db[--password {v}]": "test_db[--password <hidden>]",
    "bench[test [ -f x ] && tool --token {v}]": "bench[test [ -f x ] && tool --token <hidden>]",
    "test_x[a b]/y[tool --token {v}]/cpu_time": "test_x[a b]/y[tool --token <hidden>]/cpu_time",
    "bench[redis-cli -a {v}": "bench[redis-cli -a <hidden>",
    # The words of an id with no brackets, read the same way.
    "redis-cli -a {v} PING": "redis-cli -a <hidden> PING",
    # A credential's value that a program's text in the brackets gives it, as a string.
    "bench[python -c \"password = '{v}'\"]": "bench[python -c \"password = '<hidden>'\"]",
    "bench[password = '{v}']": "bench[password = '<hidden>']",
    "test_cfg[x = {'password': '{v}'}]": "test_cfg[x = {'password': '<hidden>'}]",
    "bench[python -c \"token = rb'{v}'\"]": 'bench[python -c "token = <hidden>"]',
    'bench[perl -e "$token = q/{v}/"]': 'bench[perl -e "$token = <hidden>"]',
    # A scheme word glued to a credential-like name or option with ``=``: the token after it is
    # hidden too, as the words of one argument hide it.
    "bench[tool --auth=Basic {v}]": "bench[tool --auth=<hidden> <hidden>]",
    "bench[tool --auth=Basic {v} -n 8]": "bench[tool --auth=<hidden> <hidden> -n 8]",
    "bench[tool --token=Bearer {v}]": "bench[tool --token=<hidden> <hidden>]",
    "test_login[--auth=Basic {v}]": "test_login[--auth=<hidden> <hidden>]",
    "bench[Authorization=Bearer {v}]": "bench[Authorization=<hidden> <hidden>]",
    "test_api[AUTHORIZATION='Bearer {v}']": "test_api[AUTHORIZATION=<hidden>]",
    "token=Bearer {v}": "token=<hidden> <hidden>",
    # A credential-like name or option glued to its value with ``:``, in a text with no blank.
    "test_db[token:{v}]": "test_db[token:<hidden>]",
    "test_db[password:{v}]": "test_db[password:<hidden>]",
    "test_db[PGPASSWORD:{v}]": "test_db[PGPASSWORD:<hidden>]",
    "test_db[api_key:{v}]": "test_db[api_key:<hidden>]",
    "test_db[secret:{v}]": "test_db[secret:<hidden>]",
    "test_db[Authorization:{v}]": "test_db[Authorization:<hidden>]",
    "test_db[X-Api-Key:{v}]": "test_db[X-Api-Key:<hidden>]",
    "test_db[--password:{v}]": "test_db[--password:<hidden>]",
    "test_db[password:{v},other]": "test_db[password:<hidden>,other]",
    "test_db[a=1,password:{v}]": "test_db[a=1,password:<hidden>]",
    "bench[pass:{v}]": "bench[pass:<hidden>]",
    "bench/password:{v}/latency": "bench/password:<hidden>/latency",
    "BM_Auth/password:{v}": "BM_Auth/password:<hidden>",
    "password:{v}": "password:<hidden>",
    # Such a name after another name's ``:`` or ``=``, after a ``-`` that joins two values, as
    # pytest joins them, or after another mark, and in quotes, as JSON writes a key.
    "test_db[db:password:{v}]": "test_db[db:password:<hidden>]",
    "test_db[redis:token:{v}]": "test_db[redis:token:<hidden>]",
    "test_db[cfg=password:{v}]": "test_db[cfg=password:<hidden>]",
    "test_db[5432-password:{v}]": "test_db[5432-password:<hidden>]",
    "test_api[1-token:{v}]": "test_api[1-token:<hidden>]",
    "test_db[0-api_key:{v}]": "test_db[0-api_key:<hidden>]",
    "test_db[3.5-password:{v}]": "test_db[3.5-password:<hidden>]",
    "test_x[$token:{v}]": "test_x[$token:<hidden>]",
    "@token:{v}": "@token:<hidden>",
    ".token:{v}": ".token:<hidden>",
    'test_api[{"token":"{v}"}]': 'test_api[{"token":"<hidden>"}]',
    'test_api[{"api_key":"{v}","n":1}]': 'test_api[{"api_key":"<hidden>","n":1}]',
    'test_api["password":"{v}"]': 'test_api["password":"<hidden>"]',
    "test_api['token':'{v}']": "test_api['token':'<hidden>']",
    'bench/{"token":"{v}"}': 'bench/{"token":"<hidden>"}',
    'test_x["token:{v}"]': 'test_x["token:<hidden>"]',
    'test_x[token:"{v}"]': 'test_x[token:"<hidden>"]',
}
# Ids the case cleaner keeps as they are: names of benchmarks and their arguments, a host or a
# user alone, ordinary values, a commit id, a version before a tag, and ids already shown.
ORDINARY = (
    "BM_Vec<int>/8/cpu_time",
    "BM_Seq<Queue, int>/8",
    "BM_Sort/1024/real_time",
    "test_x[1-2-3]",
    "test_x[a=1,b=2]",
    "test_model[meta-llama/Llama-3.1-8B-Instruct]",
    "bench[Elements=2^20,Type=F32]",
    "bench[KeyType=I32]",
    "test_tokens[max_tokens=128]",
    "query[--threads=8]",
    "test_auth[auth_mode=none]",
    "test_login[bench@db.example]",
    "BM_Connect/db.example:6379",
    "test_get[https://db.example/x]",
    "test_commit[0123456789abcdef0123456789abcdef01234567]",
    "bench[pkg::name@v2]",
    "test[python:3.12@slim]",
    "test_parse[x@y]",
    "ttft_ms@8",
    "test_db[PGPASSWORD=<hidden>]",
    "bench[bob:<hidden>@db.example:5432]",
    "test_api[<hidden>]",
    # Words in brackets that name no secret: an option with no word after it, an option of a
    # program that is no client, an option whose name only starts like a credential's, a
    # header that is no credential, a host and the state of an nvbench benchmark.
    "bench[tool -a]",
    "bench[ls -a data]",
    "bench[tool --token-count 8]",
    "bench[mysql -p]",
    "bench[mysql -P 3306]",
    "bench[curl -H Accept: text/plain]",
    "test_header[Authorization]",
    "bench[grep -p x]",
    "test_tokenize[hello]",
    "test_password_reset[ok]",
    "n=1024",
    "saxpy/Device=0 Elements=2^24",
    "bench[curl https://db.example/x -o out]",
    "test_login[bench@db.example two]",
    "bench[redis-cli -a <hidden> PING]",
    # A program's text in brackets that gives no credential a value.
    "test_x[x = 'plain']",
    "test_say[name = 'kiwi' 'pear']",
    "bench[python -c \"print('hello world')\"]",
    "bench[a == b]",
    "bench[password = '<hidden>']",
    # A name glued to its value with ``:`` that names no credential, a credential's name with
    # no value, and a whole number after a ``/``, which a benchmark's named argument gives.
    "BM_Hash/key:3",
    "BM_Hash/key:3/value:5",
    "BM_Auth/password:3",
    "BM_Map/keys:1024/threads:8",
    "BM_Gen/tokens:128",
    "BM_Gen/max_tokens:128/min_time:0.500",
    "test_db[db:postgres]",
    "test_db[token:]",
    "BM_Map<std::string>/8",
    "test_db[token:<hidden>]",
    # A name glued with ``:`` after a join or a quote that names no credential, a ``::``, which
    # gives no value, and ids already shown.
    "test_x[1-tokens:8]",
    "test_x[1-host:db.example]",
    "test_x[a-b:c]",
    "test_x[x:y:z]",
    "test_x['a':'b']",
    'test_x[{"n":1}]',
    "test_db[mode:token]",
    "bench[Token::Kind]",
    'test_api[{"token":"<hidden>"}]',
    "test_db[5432-password:<hidden>]",
)
# A path in a case id is cut to its last part, also where the id holds no secret.
PATHS = (("test_read[/home/zq-made-up-user/data.csv]", "test_read[data.csv]"),)


def _filled(case: str, at: int) -> str:
    return case.replace("{v}", VALUES[at]).replace("{r}", RANDOMS[at])


def _pieces(text: str) -> list[str]:
    """Return each six characters in a row of a made-up value that the text holds."""
    values = (*VALUES, *RANDOMS)
    found = (value[at : at + 6] for value in values for at in range(len(value) - 5))
    return [piece for piece in found if piece in text]


@pytest.mark.parametrize(("case", "shown"), list(HIDDEN.items()))
def test_a_secret_in_a_case_id_is_hidden(case: str, shown: str) -> None:
    first, second = (model.public_case(_filled(case, at)) for at in (0, 1))

    assert (first, second) == (shown, shown)
    assert _pieces(first + second) == []


@pytest.mark.parametrize("case", list(HIDDEN))
def test_a_case_id_with_its_secret_hidden_is_cleaned_to_itself(case: str) -> None:
    shown = model.public_case(_filled(case, 0))

    assert model.public_case(shown) == shown


@pytest.mark.parametrize("case", ORDINARY)
def test_an_ordinary_case_id_is_kept(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize(("case", "shown"), PATHS)
def test_a_path_in_a_case_id_is_still_cut_to_its_last_part(case: str, shown: str) -> None:
    assert model.public_case(case) == shown


@pytest.mark.parametrize(
    "word",
    [
        "PGPASSWORD={v}",
        "--password={v}",
        "token={v}",
        "api_key={v}",
        "{r}",
        "token:{v}",
        "test_db[X-Api-Key:{v}]",
        "--auth=Basic {v}",
    ],
)
def test_the_shown_command_hides_what_a_case_id_hides(word: str) -> None:
    shown = model.public_command(("tool", _filled(word, 0)))

    assert "<hidden>" in shown
    assert _pieces(shown) == []


def _sample(case: str) -> api.Sample:
    return api.Sample(case=case, metric="time", unit="s", better="lower", kind="time", value=1.5)


def test_two_case_ids_that_read_the_same_once_their_secrets_are_hidden_are_refused() -> None:
    ids = [_filled("test_db[PGPASSWORD={v}]", at) for at in (0, 1)]

    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "bench.json")

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith(
        "bench.json: two different cases have the name 'test_db[PGPASSWORD=<hidden>]' once "
        "absolute paths and paths that climb with '..' are cut and secrets hidden, as the "
        "results show it, and differ only in a hidden secret; give them names that differ "
        "outside their paths, absolute or climbing with '..', and outside their secrets;"
    )
    assert _pieces(caught.value.message) == []


def test_two_case_ids_whose_words_read_the_same_once_hidden_are_refused() -> None:
    ids = [_filled("bench[redis-cli -a {v} PING]", at) for at in (0, 1)]

    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "bench.json")

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith(
        "bench.json: two different cases have the name 'bench[redis-cli -a <hidden> PING]' once "
    )
    assert _pieces(caught.value.message) == []


@pytest.mark.parametrize(
    ("case", "shown"),
    [
        ("test_db[token:{v}]", "test_db[token:<hidden>]"),
        ("bench[tool --auth=Basic {v}]", "bench[tool --auth=<hidden> <hidden>]"),
    ],
)
def test_two_case_ids_whose_glued_value_or_token_reads_the_same_once_hidden_are_refused(
    case: str, shown: str
) -> None:
    ids = [_filled(case, at) for at in (0, 1)]

    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "bench.json")

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith(
        f"bench.json: two different cases have the name '{shown}' once "
    )
    assert _pieces(caught.value.message) == []


def test_a_driver_s_cases_keep_their_secrets_hidden_and_apart() -> None:
    read = [_sample(_filled(case, 0)) for case in ("bench[token={v}]", "bench[api_key={v}]")]

    shown = [sample.case for sample in api.public_cases(read, "bench.json")]

    assert shown == ["bench[token=<hidden>]", "bench[api_key=<hidden>]"]
