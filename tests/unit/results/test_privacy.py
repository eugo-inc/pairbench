# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a results file must not contain.

The machine is made to answer every question about itself with a marker
value: host name, user name, home and working folders, environment values.
The results are built from inputs that carry markers too: a command line
with an image reference from a registry, absolute paths and a value set for
a variable, notes and refusals that name absolute paths. Neither
``results.json`` nor ``results.md``, nor the terminal report, may then hold
a marker or the run folder's absolute path.
"""

from __future__ import annotations

import copy
import dataclasses
import getpass
import html
import json
import os
import platform
import shlex
import socket
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import API_VERSION, GROUP_REPORTERS, ReportOptions
from pairbench.errors import Refusal
from pairbench.model import Note, PluginCounts, RefusalEntry, Results, public_command
from pairbench.page.html import text as page_text
from pairbench.results.figures import with_figures
from pairbench.results.writer import write_results
from pairbench.stats.selftest import synthetic_capture

# Markers: made-up values that must never reach a results file. They hold
# only letters, digits, dots, slashes and hyphens, so no escaping in the
# markdown report can hide one from the search.
HOST = "markerhost-a"
USER = "markeruser-a"
HOME = "/markerhome-a/markeruser-a"
WORK = "/markerwork-a/project"
ENV_VALUE = "markerenvvalue-a"
REGISTRY = "markerregistry-a.example"
REPOSITORY = "markerrepository-a"
SERIAL = "markerserial-a"
MACHINE_ID = "markermachineid-a"
MAC = "02-00-00-00-00-0a"
DEVICE_ID = "markerdeviceid-a"
CLOUD_INSTANCE = "markerinstance-a"
CLOUD_ACCOUNT = "markeraccount-a"
PLUGIN = "markerplugin-a"
BROKEN_PLUGIN = "markerbrokenplugin-a"
FOLDER = "markerfolder-a"
MARKERS = (
    HOST,
    USER,
    "markerhome-a",
    "markerwork-a",
    ENV_VALUE,
    REGISTRY,
    REPOSITORY,
    SERIAL,
    MACHINE_ID,
    MAC,
    DEVICE_ID,
    CLOUD_INSTANCE,
    CLOUD_ACCOUNT,
    PLUGIN,
    BROKEN_PLUGIN,
    FOLDER,
)

ARGV = [
    f"{HOME}/.local/bin/pairbench",
    "run",
    "--side",
    f"new=image:{REGISTRY}/{REPOSITORY}/app:2.0",
    "--side",
    f"old=cmd:{HOME}/bin/old-build",
    "--set",
    f"launch.env.SOME_SETTING={ENV_VALUE}",
    f"--out={WORK}/runs/one",
    "--",
    f"{WORK}/bench.py",
]


@pytest.fixture
def machine_full_of_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the machine answer every question about itself with a marker."""
    monkeypatch.setattr(socket, "gethostname", lambda: HOST)
    monkeypatch.setattr(platform, "node", lambda: HOST)
    monkeypatch.setattr(getpass, "getuser", lambda: USER)
    monkeypatch.setattr(os, "getcwd", lambda: WORK)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(HOME)))
    for name, value in {
        "HOME": HOME,
        "USER": USER,
        "LOGNAME": USER,
        "HOSTNAME": HOST,
        "PWD": WORK,
        "SOME_SETTING": ENV_VALUE,
        "GPU_SERIAL": SERIAL,
        "MACHINE_ID": MACHINE_ID,
        "MAC_ADDRESS": MAC,
        "GPU_DEVICE_ID": DEVICE_ID,
        "CLOUD_INSTANCE_ID": CLOUD_INSTANCE,
        "CLOUD_ACCOUNT_ID": CLOUD_ACCOUNT,
    }.items():
        monkeypatch.setenv(name, value)


class MarkerReporter:
    """A made-up reporter plug-in whose name is a marker."""

    name = PLUGIN
    api_version = API_VERSION

    def render(self, results: Results, options: ReportOptions) -> str:
        return ""


class BrokenReporter(MarkerReporter):
    """A made-up plug-in that fails to load: it was written for another interface version."""

    name = BROKEN_PLUGIN
    api_version = API_VERSION + 1


@pytest.fixture
def plugins(capsys: pytest.CaptureFixture[str]) -> PluginCounts:
    """Register one plug-in that loads and one that fails, both named by markers."""
    registry.register(GROUP_REPORTERS, PLUGIN, MarkerReporter)
    with pytest.raises(registry.PluginError):
        registry.register(GROUP_REPORTERS, BROKEN_PLUGIN, BrokenReporter)
    assert BROKEN_PLUGIN in capsys.readouterr().err
    counts = registry.counts()
    assert counts == PluginCounts(loaded=1, failed=1)
    return counts


@pytest.fixture
def results(example_results: dict[str, Any], plugins: PluginCounts) -> Results:
    """Results built from inputs that carry markers, through the model's own rules."""
    doc = copy.deepcopy(example_results)
    doc["run"]["command"] = public_command(ARGV)
    doc["artifacts"]["profiles"] = ["profiles/new.flame.svg"]
    built = Results.from_json(doc)
    notes = (
        Note(code="explain_failed", message=f"the explain step could not write {WORK}/x.json"),
        Note(code="charts_failed", message=f"drawing failed in {HOME}/runs/one/charts"),
    )
    refusal = Refusal("E_GRID", f"a cell is missing in {HOME}/runs/one/capture.jsonl")
    built = built.finished(
        diagnostics=built.diagnostics, plots=built.plots, notes=notes, artifacts=built.artifacts
    )
    return with_figures(
        dataclasses.replace(built, refusals=(RefusalEntry.of(refusal),), plugins=plugins)
    )


def test_no_results_file_holds_what_identifies_the_machine(
    results: Results, tmp_path: Path, machine_full_of_markers: None
) -> None:
    folder = tmp_path / FOLDER / "run"
    write_results(results, folder)
    texts = {
        "results.json": (folder / "results.json").read_text(encoding="utf-8"),
        "results.md": (folder / "results.md").read_text(encoding="utf-8"),
        "terminal": pairbench.render(results, "terminal"),
        "json": pairbench.render(results, "json"),
    }
    for where, text in texts.items():
        for marker in (*MARKERS, str(tmp_path)):
            assert marker not in text, (where, marker)
    # What the results may show of the same inputs is still there.
    assert "new=image:<hidden>" in texts["results.md"]
    assert "launch.env.SOME_SETTING=<hidden>" in texts["results.json"]
    assert "could not write x.json" in texts["results.md"]
    assert "a cell is missing in capture.jsonl" in texts["results.json"]
    # Plug-ins are counted, never named.
    assert '"plugins": {\n    "loaded": 1,\n    "failed": 1\n  }' in texts["results.json"]


# A workload given as one shell text: paths glued to options, a credential
# after an option, a variable whose quoted value holds a space, a header and
# an address with a user and a password, all inside the one argument after
# ``sh -c``.
SHELL_TEXT = (
    f"./bench -I{HOME}/include -o{WORK}/out && make -C{HOME}/src "
    f"--token {ENV_VALUE}-1 'API_KEY={ENV_VALUE} 2' -H 'Authorization: Bearer {ENV_VALUE}-3' "
    f"--db postgres://{USER}:{ENV_VALUE}-4@db.example/x"
)
SHELL_ARGV = ("pairbench", "run", "--side", "new=cmd:true", "--", "sh", "-c", SHELL_TEXT)


def test_a_command_analysed_from_a_capture_shows_no_path_and_no_secret_inside_one_argument(
    tmp_path: Path, machine_full_of_markers: None
) -> None:
    def value(entry: str, case: str, round_: int, u: float) -> float:
        return 2.0 + u if entry.startswith("new") else 1.0 + u

    capture = synthetic_capture(value, capture_id="made-up-shell-run")
    capture = dataclasses.replace(
        capture, header=dataclasses.replace(capture.header, argv=SHELL_ARGV)
    )
    analysed = pairbench.analyse(capture)
    folder = tmp_path / "run"
    write_results(analysed, folder)
    texts = {
        "results.json": (folder / "results.json").read_text(encoding="utf-8"),
        "results.md": (folder / "results.md").read_text(encoding="utf-8"),
        "terminal": pairbench.render(analysed, "terminal"),
        "html": pairbench.render(analysed, "html"),
    }
    for where, text in texts.items():
        for marker in (*MARKERS, str(tmp_path)):
            assert marker not in text, (where, marker)
    assert analysed.run.command == shlex.join(
        [
            *SHELL_ARGV[:3],
            "new=cmd:<hidden>",
            "--",
            "sh",
            "-c",
            "./bench -Iinclude -oout && make -Csrc --token <hidden> 'API_KEY=<hidden>' "
            "-H 'Authorization: <hidden>' --db postgres://<hidden>@<hidden>/x",
        ]
    )


def test_a_write_asks_the_machine_nothing(
    results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a results file asked the machine about itself")

    for owner, name in (
        (socket, "gethostname"),
        (platform, "node"),
        (getpass, "getuser"),
        (os, "getcwd"),
    ):
        monkeypatch.setattr(owner, name, refuse)
    monkeypatch.setattr(Path, "home", classmethod(refuse))
    write_results(results, tmp_path / "run")
    pairbench.render(results, "terminal")
    pairbench.render(results, "markdown")


# Each form a recorded command may carry a credential in, with a made-up
# marker as the credential. Every marker is a word of six small letters that
# no report writes by itself and that holds no other marker, so neither
# quoting nor escaping can hide one and no marker is found inside another.
CREDENTIAL_FORMS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    # (arguments of the workload, the marker, a text the shown command keeps)
    (("-H", "Authorization: Bearer zqmkaa"), "zqmkaa", "Authorization: <hidden>"),
    (("--header", "X-Api-Key: zqmkab"), "zqmkab", "X-Api-Key: <hidden>"),
    (("--header=x-api-key: zqmkac",), "zqmkac", "--header=x-api-key: <hidden>"),
    (("-HX-Api-Key:zqmkad",), "zqmkad", "-HX-Api-Key: <hidden>"),
    (("--auth", "someuser:zqmkae"), "zqmkae", "--auth"),
    (("API_KEY:zqmkaf",), "zqmkaf", "API_KEY: <hidden>"),
    (("http://someuser:zqmkag@db.example/x",), "zqmkag", "/x"),
    (("-H", "Proxy-Authorization: Basic zqmkah"), "zqmkah", "Proxy-Authorization:"),
    (("KEYSTORE_PASS=zqmkai",), "zqmkai", "KEYSTORE_PASS=<hidden>"),
    (("--keypass", "zqmkaj"), "zqmkaj", "--keypass"),
    (("--storepass", "zqmkak"), "zqmkak", "--storepass"),
    (("--passphrase", "zqmkal"), "zqmkal", "--passphrase"),
    (("--bearer", "zqmkam"), "zqmkam", "--bearer"),
    (("GITHUB_PAT=zqmkan",), "zqmkan", "GITHUB_PAT=<hidden>"),
    (("MYSQL_PWD=zqmkao",), "zqmkao", "MYSQL_PWD=<hidden>"),
    (("APITOKENS=zqmkap",), "zqmkap", "APITOKENS=<hidden>"),
    (("HF_TOKENS=zqmkaq",), "zqmkaq", "HF_TOKENS=<hidden>"),
    (("TINK_KEYSET=zqmkar",), "zqmkar", "TINK_KEYSET=<hidden>"),
    (
        ("AZURE_STORAGE_CONNECTION_STRING=zqmkas",),
        "zqmkas",
        "AZURE_STORAGE_CONNECTION_STRING=<hidden>",
    ),
    (("-u", "someuser:zqmkat"), "zqmkat", "someuser:<hidden>"),
    (("--user=someuser:zqmkau",), "zqmkau", "--user=someuser:<hidden>"),
    (("-U", "proxyuser:zqmkav"), "zqmkav", "proxyuser:<hidden>"),
    (
        ("-c", 'import os; os.environ["API_KEY"] = "zqmkaw"'),
        "zqmkaw",
        'os.environ["API_KEY"] = "<hidden>"',
    ),
    # The host of an address is no credential, but no results file may name it either.
    (("https://zqmkax.example:8443/v1",), "zqmkax", "https://<hidden>:8443/v1"),
    # The user part of an address glued to an option is hidden as the user part of any address.
    (("-xhttp://someuser:zqmkay@proxy.example:3128",), "zqmkay", "-xhttp://<hidden>@<hidden>:3128"),
    # Each way to give --auth its value, also inside one argument of several words.
    (("--auth=someuser:zqmkbe",), "zqmkbe", "--auth=<hidden>"),
    (("--auth", "zqmkbf"), "zqmkbf", "--auth"),
    (("--auth", "someuser:zqmkbg@db.example"), "zqmkbg", "--auth"),
    (("tool --auth someuser:zqmkbh -v",), "zqmkbh", "tool --auth <hidden> -v"),
    # A quoted word of several words with a credential-like name after an option.
    (('echo "--token zqmkbi password=zqmkbj"',), "zqmkbi", "password=<hidden>"),
    # Names for authenticating, a short word for a password, a signature.
    (("--authenticate", "zqmkbk"), "zqmkbk", "--authenticate"),
    (("-H", "Authentication: zqmkbl"), "zqmkbl", "Authentication: <hidden>"),
    (("--pw", "zqmkbm"), "zqmkbm", "--pw"),
    (("--auth-header", "Bearer zqmkbn"), "zqmkbn", "--auth-header"),
    (("X-Amz-Signature=zqmkbo",), "zqmkbo", "X-Amz-Signature=<hidden>"),
    # A default given where a program reads a credential from its environment.
    (("-c", "API_KEY = os.getenv('X', 'zqmkbp')"), "zqmkbp", "API_KEY = <hidden>"),
    # A certificate and the password of its key.
    (("--cert", "client.pem:zqmkbq"), "zqmkbq", "client.pem:<hidden>"),
    # A file or an identity of a key or a token, glued to the word or written apart.
    (("KEYFILE=zqmkbr",), "zqmkbr", "KEYFILE=<hidden>"),
    (("--keyfile", "zqmkbs"), "zqmkbs", "--keyfile"),
    (("--keyfile=zqmkbt",), "zqmkbt", "--keyfile=<hidden>"),
    (("PRIVATEKEYFILE=zqmkbu",), "zqmkbu", "PRIVATEKEYFILE=<hidden>"),
    (("SSH_KEYFILE=zqmkbv",), "zqmkbv", "SSH_KEYFILE=<hidden>"),
    (("--tokenfile", "zqmkbw"), "zqmkbw", "--tokenfile"),
    (("HF_TOKENFILE=zqmkbx",), "zqmkbx", "HF_TOKENFILE=<hidden>"),
    (("KEYID=zqmkby",), "zqmkby", "KEYID=<hidden>"),
    (("KEY_ID=zqmkbz",), "zqmkbz", "KEY_ID=<hidden>"),
    (("AWS_ACCESS_KEY_ID=zqmkca",), "zqmkca", "AWS_ACCESS_KEY_ID=<hidden>"),
    (("--key-id", "zqmkcb"), "zqmkcb", "--key-id"),
    (("TOKENID=zqmkcc",), "zqmkcc", "TOKENID=<hidden>"),
    (("--tokenid", "zqmkcd"), "zqmkcd", "--tokenid"),
    # A path, a pair or a ring of keys or tokens, glued to the word.
    (("KEYPATH=zqmkce",), "zqmkce", "KEYPATH=<hidden>"),
    (("TOKENPATH=zqmkcf",), "zqmkcf", "TOKENPATH=<hidden>"),
    (("KEYPAIR=zqmkcg",), "zqmkcg", "KEYPAIR=<hidden>"),
    (("KEYRING=zqmkch",), "zqmkch", "KEYRING=<hidden>"),
    (("SSH_KEYPATH=zqmkci",), "zqmkci", "SSH_KEYPATH=<hidden>"),
    (("GPG_KEYRING=zqmkcj",), "zqmkcj", "GPG_KEYRING=<hidden>"),
    (("--keypath", "zqmkck"), "zqmkck", "--keypath"),
    (("--keyring", "zqmkcl"), "zqmkcl", "--keyring"),
    # A key, a token or a password glued to any word after it, as the name and as an option.
    (("KEYPEM=zqmkcm",), "zqmkcm", "KEYPEM=<hidden>"),
    (("--keypem", "zqmkcn"), "zqmkcn", "--keypem"),
    (("KEYDATA=zqmkco",), "zqmkco", "KEYDATA=<hidden>"),
    (("--keydata", "zqmkcp"), "zqmkcp", "--keydata"),
    (("KEYVALUE=zqmkcq",), "zqmkcq", "KEYVALUE=<hidden>"),
    (("--keyvalue", "zqmkcr"), "zqmkcr", "--keyvalue"),
    (("KEYPHRASE=zqmkcs",), "zqmkcs", "KEYPHRASE=<hidden>"),
    (("--keyphrase", "zqmkct"), "zqmkct", "--keyphrase"),
    (("TOKENVALUE=zqmkcu",), "zqmkcu", "TOKENVALUE=<hidden>"),
    (("--tokenvalue", "zqmkcv"), "zqmkcv", "--tokenvalue"),
    (("PASSFILE=zqmkcw",), "zqmkcw", "PASSFILE=<hidden>"),
    (("--passfile", "zqmkcx"), "zqmkcx", "--passfile"),
    (("KEYSTOREFILE=zqmkcy",), "zqmkcy", "KEYSTOREFILE=<hidden>"),
    (("--keystorefile", "zqmkcz"), "zqmkcz", "--keystorefile"),
    (("KEYSPATH=zqmkda",), "zqmkda", "KEYSPATH=<hidden>"),
    (("--keyspath", "zqmkdb"), "zqmkdb", "--keyspath"),
    (("KEYRINGPATH=zqmkdc",), "zqmkdc", "KEYRINGPATH=<hidden>"),
    (("--keyringpath", "zqmkdd"), "zqmkdd", "--keyringpath"),
    (("KEYRINGFILE=zqmkde",), "zqmkde", "KEYRINGFILE=<hidden>"),
    (("--keyringfile", "zqmkdf"), "zqmkdf", "--keyringfile"),
    (("KEYPAIRNAME=zqmkdg",), "zqmkdg", "KEYPAIRNAME=<hidden>"),
    (("--keypairname", "zqmkdh"), "zqmkdh", "--keypairname"),
    (("KEYPAIRID=zqmkdi",), "zqmkdi", "KEYPAIRID=<hidden>"),
    (("--keypairid", "zqmkdj"), "zqmkdj", "--keypairid"),
    # A word of its own glued after a key is no start of a word: the key still names a key.
    (("APIKEYCODE=zqmkdk",), "zqmkdk", "APIKEYCODE=<hidden>"),
    (("--apikeyword", "zqmkdl"), "zqmkdl", "--apikeyword"),
    (
        (
            "curl -H 'Authorization: Bearer zqmkba' --auth someuser:zqmkbb "
            "-u someuser:zqmkbc http://someuser:zqmkbd@db.example/x",
        ),
        "zqmkba",
        "Authorization: <hidden>",
    ),
    # A value that holds spaces, given in one argument.
    (("DB_PASSWORD=zqmkbr zqmkbs",), "zqmkbs", "DB_PASSWORD=<hidden>"),
    (("--api-key=zqmkbu zqmkbv",), "zqmkbv", "--api-key=<hidden>"),
    # An option and its value as two quoted texts of a list in a program.
    (
        ("-c", 'import subprocess; subprocess.run(["t", "--password", "zqmkbt"])'),
        "zqmkbt",
        '"--password", "<hidden>"',
    ),
)
NESTED_MARKERS = ("zqmkbb", "zqmkbc", "zqmkbd", "zqmkbj", "zqmkbr", "zqmkbu")
# Ordinary names that end or start like a credential word, each with its value: the shown
# command keeps both.
ORDINARY_FORMS = (
    ("SORT_KEYS=name",),
    ("--sort-keys", "name"),
    ("--tokenizer-mode", "auto"),
    ("--stop-token-ids", "2"),
    ("eos_token_id=2",),
    ("KEYBOARD=us",),
    ("MONKEY=1",),
    ("TOKENIZER_PATH=tok.json",),
    ("HOTKEYFILE=keys.txt",),
    ("EOSTOKENID=2",),
    ("--keyspace", "made_up"),
)


def test_a_run_whose_command_holds_credentials_shows_none_in_the_public_files(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workload = [word for words, _, _ in CREDENTIAL_FORMS for word in words]
    workload += [word for words in ORDINARY_FORMS for word in words]
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *workload,
    )
    assert run.code == 0, run.err
    folder = tmp_path / "run"
    texts = {
        name: (folder / name).read_text(encoding="utf-8")
        for name in ("results.json", "results.md", "report.html")
    }
    texts["stdout"] = run.out
    texts["stderr"] = run.err
    markers = [marker for _, marker, _ in CREDENTIAL_FORMS] + list(NESTED_MARKERS)
    for where, text in texts.items():
        assert [m for m in markers if m in text] == [], where
    # The command is there, with every option and name that carried a value.
    command = Results.from_json(json.loads(texts["results.json"])).run.command
    assert command is not None
    for _, _, kept in CREDENTIAL_FORMS:
        assert kept in command, kept
    for words in ORDINARY_FORMS:
        assert shlex.join(words) in command, words


# Addresses whose host is hidden, each with what the shown command keeps of it: the path and
# the query of an address without a port stay whole, as they do after a port, also after a
# host in brackets.
ADDRESSES = (
    ("https://made-up.example/api/t/x", "https://<hidden>/api/t/x"),
    ("https://made-up.example/api/q?x=1&y=2", "https://<hidden>/api/q?x=1&y=2"),
    ("https://made-up.example:8443/v1/m", "https://<hidden>:8443/v1/m"),
    ("http://localhost/a/b", "http://localhost/a/b"),
    ("http://[fd00::1]/a/b", "http://<hidden>/a/b"),
    ("http://[::1]/a/b?x=1", "http://[::1]/a/b?x=1"),
    # A file address names a path on a machine: only the name of the file is shown.
    ("file://localhost/markerhome-f/user/m.gguf", "file://m.gguf"),
    ("file://markerhost-f/markerhome-f/user/m.gguf", "file://m.gguf"),
    ("file://[::1]/markerhome-f/user/m.gguf", "file://m.gguf"),
    ("file:///markerhome-f/user/m.gguf", "file://m.gguf"),
    # A file address with a host and no path names a machine: the host is hidden.
    ("file://markerhost-g", "file://<hidden>"),
    ("file://markerhost-g:8000", "file://<hidden>:8000"),
    ("--storage=file://markerhost-g", "--storage=file://<hidden>"),
    ("file://localhost", "file://localhost"),
    # A character no host name holds ends the host of a file address before it.
    ("file://markerhost-g,", "file://<hidden>,"),
    ("file://markerhost-g=1", "file://<hidden>=1"),
    ("file://markerhost-g$x", "file://<hidden>$x"),
    ("file://markerhost-g\\x", "file://<hidden>\\x"),
    ("file://markerhost-g,file://markerhost-g", "file://<hidden>,file://<hidden>"),
    # A character no host name holds ends the address: the absolute path after it is cut.
    ("http://made-up.example,/markerhome-f/user/data.csv", "http://<hidden>"),
    ("http://made-up.example;/markerhome-f/user/bin/tool", "http://<hidden>"),
)
PATH_MARKERS = ("markerhome-f", "markerhost-f", "markerhost-g")


def _fenced(markdown: str, heading: str) -> str:
    """Return the text of the first fenced block after a heading of a markdown report."""
    after = markdown.split(heading, 1)[1].lstrip("\n").splitlines()
    fence = after[0]
    return "\n".join(after[1 : after.index(fence, 1)])


def test_results_md_shows_the_recorded_command_with_the_path_of_every_address(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *(given for given, _ in ADDRESSES),
    )
    assert run.code == 0, run.err
    assert run.out.startswith("new against old (baseline)\n")
    folder = tmp_path / "run"
    command = Results.from_json(
        json.loads((folder / "results.json").read_text(encoding="utf-8"))
    ).run.command
    assert command is not None
    assert command.endswith(" -- true " + " ".join(shlex.quote(shown) for _, shown in ADDRESSES))
    markdown = (folder / "results.md").read_text(encoding="utf-8")
    assert _fenced(markdown, "## How to reproduce") == command
    for name in ("results.json", "results.md", "report.html"):
        text = (folder / name).read_text(encoding="utf-8")
        assert [m for m in PATH_MARKERS if m in text] == [], name
    # The report page shows the command as results.json records it, escaped for HTML.
    page = (folder / "report.html").read_text(encoding="utf-8")
    assert html.escape("'file://<hidden>:8000'") in page


# Addresses whose host is empty: what follows ``scheme://`` is a path on the machine, cut to its
# last part, each with what the shown command keeps of it.
LOCAL_ADDRESSES = (
    ("sqlite:////markerhome-g/markeruser-g/db.sqlite", "sqlite:///db.sqlite"),
    ("sqlite:///markerhome-g/markeruser-g/x.db", "sqlite:///x.db"),
    ("sqlite:////markerhome-g/markeruser-g/db", "sqlite:///db"),
    ("duckdb:///markerhome-g/markeruser-g/x.duckdb", "duckdb:///x.duckdb"),
    ("unix:///markerhome-g/markeruser-g/s.sock", "unix:///s.sock"),
    ("redis+socket:///markerhome-g/markeruser-g/r.sock", "redis+socket:///r.sock"),
)
LOCAL_MARKERS = ("markerhome-g", "markeruser-g")
# Addresses with a host keep their path; the host is hidden.
REMOTE_ADDRESSES = (
    ("https://made-up.example/v1/chat/completions", "https://<hidden>/v1/chat/completions"),
    ("s3://made-up-bucket/made/up/key", "s3://<hidden>/made/up/key"),
)


def test_the_local_path_of_an_address_with_an_empty_host_is_cut_in_every_public_file(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workload: list[str] = []
    shown: list[str] = []
    for given, kept in LOCAL_ADDRESSES:
        workload += [given, f"--db={given}", f"DATABASE_URL={given}"]
        workload += ["sh", "-c", f"tool --db {given} -q"]
        shown += [kept, f"--db={kept}", f"DATABASE_URL={kept}"]
        shown += ["sh", "-c", f"tool --db {kept} -q"]
    workload += [given for given, _ in REMOTE_ADDRESSES]
    shown += [kept for _, kept in REMOTE_ADDRESSES]
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *workload,
    )
    assert run.code == 0, run.err
    assert run.out.startswith("new against old (baseline)\n")
    folder = tmp_path / "run"
    texts = {
        name: (folder / name).read_text(encoding="utf-8")
        for name in ("results.json", "results.md", "report.html")
    }
    for where, text in texts.items():
        assert [m for m in LOCAL_MARKERS if m in text] == [], where
    command = Results.from_json(json.loads(texts["results.json"])).run.command
    assert command is not None
    assert command.endswith(" -- true " + shlex.join(shown))
    assert _fenced(texts["results.md"], "## How to reproduce") == command


# Shell texts whose hidden value is glued to an operator, each with what the shown command keeps:
# the value ends at the operator, and the operator and the next command are shown.
SHELL_OPERATOR_TEXTS = (
    ("tool --api-key=markersecret-h1&& ls", "tool --api-key=<hidden>&& ls"),
    ("tool --api-key=markersecret-h2; ls", "tool --api-key=<hidden>; ls"),
    ("tool --api-key=markersecret-h3|ls", "tool --api-key=<hidden>|ls"),
    ("tool --token=markersecret-h4&& ls -l", "tool --token=<hidden>&& ls -l"),
    ("API_KEY=markersecret-h5&& ls -l", "API_KEY=<hidden>&& ls -l"),
    (
        "curl -H 'Authorization: Bearer markersecret-h6'&& ls -l",
        "curl -H 'Authorization: <hidden>'&& ls -l",
    ),
    ("curl -H 'X-Api-Key: markersecret-h7'; ls -l", "curl -H 'X-Api-Key: <hidden>'; ls -l"),
)
SHELL_OPERATOR_MARKERS = ("markersecret-h",)


def test_a_hidden_value_ends_at_a_shell_operator_in_every_public_file(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workload: list[str] = []
    shown: list[str] = []
    for given, kept in SHELL_OPERATOR_TEXTS:
        workload += ["sh", "-c", given]
        shown += ["sh", "-c", kept]
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *workload,
    )
    assert run.code == 0, run.err
    assert run.out.startswith("new against old (baseline)\n")
    folder = tmp_path / "run"
    texts = {
        name: (folder / name).read_text(encoding="utf-8")
        for name in ("results.json", "results.md", "report.html")
    }
    for where, text in texts.items():
        assert [m for m in SHELL_OPERATOR_MARKERS if m in text] == [], where
    command = Results.from_json(json.loads(texts["results.json"])).run.command
    assert command is not None
    assert command.endswith(" -- true " + shlex.join(shown))
    assert _fenced(texts["results.md"], "## How to reproduce") == command
    assert f"<code>{page_text(command)}</code>" in texts["report.html"]


# Arguments whose secret holds an operator that ends no command, each with what the shown
# command keeps: a program gets the argument whole, or the operator stands inside quotes, or
# after a backslash, of a shell text (as the remote command of ``ssh``), so the whole secret is
# hidden.
QUOTED_OPERATOR_ARGUMENTS = (
    (
        ("curl", "-H", "Cookie: a=1; sessionid=markersecret-q1", "http://localhost/x"),
        ("curl", "-H", "Cookie: <hidden>", "http://localhost/x"),
    ),
    (
        ("tool", "--opts", "--x 1 --password markersecret-q2&markersecret-q3 --y 2"),
        ("tool", "--opts", "--x 1 --password <hidden> --y 2"),
    ),
    (
        ("sh", "-c", "curl -H 'Cookie: a=1; sessionid=markersecret-q4' http://localhost/x && ls"),
        ("sh", "-c", "curl -H 'Cookie: <hidden>' http://localhost/x && ls"),
    ),
    (
        ("sh", "-c", "env -S 'tool HF_TOKEN=markersecret-q5&markersecret-q6 -q' && ls"),
        ("sh", "-c", "env -S 'tool HF_TOKEN=<hidden> -q' && ls"),
    ),
    (
        ("sh", "-c", "curl https://bench:markersecret-q7;markersecret-q8@made-up.example/x"),
        ("sh", "-c", "curl https://<hidden>@<hidden>/x"),
    ),
    (
        ("ssh", "made-up-host", "tool --password 'markersecret-q9;markersecret-qa' -q && ls"),
        ("ssh", "made-up-host", "tool --password <hidden> -q && ls"),
    ),
    (
        ("ssh", "made-up-host", "tool --password markersecret-qb\\;markersecret-qc -q"),
        ("ssh", "made-up-host", "tool --password <hidden> -q"),
    ),
)
QUOTED_OPERATOR_MARKERS = ("markersecret-q",)


def test_an_operator_that_ends_no_command_keeps_the_secret_hidden_in_every_public_file(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workload: list[str] = []
    shown: list[str] = []
    for given, kept in QUOTED_OPERATOR_ARGUMENTS:
        workload += given
        shown += kept
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *workload,
    )
    assert run.code == 0, run.err
    assert run.out.startswith("new against old (baseline)\n")
    folder = tmp_path / "run"
    texts = {
        name: (folder / name).read_text(encoding="utf-8")
        for name in ("results.json", "results.md", "report.html")
    }
    for where, text in texts.items():
        assert [m for m in QUOTED_OPERATOR_MARKERS if m in text] == [], where
    command = Results.from_json(json.loads(texts["results.json"])).run.command
    assert command is not None
    assert command.endswith(" -- true " + shlex.join(shown))
    assert _fenced(texts["results.md"], "## How to reproduce") == command
    assert f"<code>{page_text(command)}</code>" in texts["report.html"]


# Commands of three quoting layers whose secret follows an escape in a text in double quotes,
# each with what the shown command keeps: the next shell reads that text with its escapes
# taken out, so an escaped blank or escaped quotes join the option and its secret into one word.
LAYERED_ARGUMENTS = (
    (
        ("sh", "-c", 'sh -c "./bench --token\\\\ markersecret-l1"'),
        ("sh", "-c", "sh -c \"./bench '--token <hidden>'\""),
    ),
    (
        ("sh", "-c", 'sh -c "ssh made-up-host \'./bench --token\\" markersecret-l2\\"\'"'),
        ("sh", "-c", 'sh -c "ssh made-up-host \'./bench \\"--token <hidden>\\"\'"'),
    ),
    (
        ("sh", "-c", 'ssh made-up-host "./bench --token\\" markersecret-l3\\""'),
        ("sh", "-c", "ssh made-up-host \"./bench '--token <hidden>'\""),
    ),
)
LAYERED_MARKERS = ("markersecret-l",)


def test_a_secret_after_an_escape_in_three_quoting_layers_is_in_no_public_file(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workload: list[str] = []
    shown: list[str] = []
    for given, kept in LAYERED_ARGUMENTS:
        workload += given
        shown += kept
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        "true",
        *workload,
    )
    assert run.code == 0, run.err
    assert run.out.startswith("new against old (baseline)\n")
    folder = tmp_path / "run"
    texts = {
        name: (folder / name).read_text(encoding="utf-8")
        for name in ("results.json", "results.md", "report.html")
    }
    for where, text in texts.items():
        assert [m for m in LAYERED_MARKERS if m in text] == [], where
    command = Results.from_json(json.loads(texts["results.json"])).run.command
    assert command is not None
    assert command.endswith(" -- true " + shlex.join(shown))
    assert _fenced(texts["results.md"], "## How to reproduce") == command
    assert f"<code>{page_text(command)}</code>" in texts["report.html"]
