# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A client named first in a text glued to its option keeps its password out of every shared file.

The shared workload gives a client's command as the text of an option of
``TEXT_OPTIONS`` glued to the option (``gcloud ... --command=mysql -pVALUE``,
``env -Sredis-cli -a VALUE``, ``env --split-string=...``). Two runs that differ
in the password alone write ``results.json``, ``results.md`` and
``report.html`` with no six characters of the password in a row, give one
shown command, one ``config_sha256`` and one fingerprint per side, and
``compare`` pools their captures with no part of either password on its
streams or in the pooled files.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_SIDE
from pairbench.model import HIDDEN

from .conftest import refusal_text

Cli = Callable[..., Any]

# Made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
)
SHARED_FILES = ("results.json", "results.md", "report.html")
# What ``compare --out`` writes.
COMPARED_FILES = ("results.json", "results.md")
# Two sides that run the shared workload, told apart by a variable.
SIDES = (
    '[sides.a]\ncmd = ["env", "PB_SIDE=1", "{workload}"]\nbaseline = true\n'
    '[sides.b]\ncmd = ["env", "PB_SIDE=2", "{workload}"]\n'
)
SHOWN_HEAD = (
    "pairbench run --config pairbench.toml --gates off --rounds 6 --same-vs-same off "
    "--positive-control off --explain off --plots off --out out --"
)

# Each client: its text with ``{s}`` for the password, and the text as shown.
CLIENT_TEXTS: dict[str, tuple[str, str]] = {
    "mysql": ("mysql -p{s} -e made-up-query", f"mysql -p{HIDDEN} -e made-up-query"),
    "mysqlslap": ("mysqlslap -p{s} -c 4", f"mysqlslap -p{HIDDEN} -c 4"),
    "redis-cli": ("redis-cli -a {s} PING", f"redis-cli -a {HIDDEN} PING"),
    "redis-benchmark": ("redis-benchmark -a {s} -n 1000", f"redis-benchmark -a {HIDDEN} -n 1000"),
    "memtier_benchmark": (
        "memtier_benchmark -a {s} -n 1000",
        f"memtier_benchmark -a {HIDDEN} -n 1000",
    ),
    "valkey-cli": ("valkey-cli -a {s} PING", f"valkey-cli -a {HIDDEN} PING"),
    "sshpass": ("sshpass -p {s} true", f"sshpass -p {HIDDEN} true"),
    "ab": (
        "ab -A bench:{s} http://localhost:8000/",
        f"ab -A bench:{HIDDEN} http://localhost:8000/",
    ),
}
# Each option of ``TEXT_OPTIONS``: the words before it and what glues the text to it.
OPTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "gcloud-command": (("gcloud", "compute", "ssh", "made-up-vm"), "--command="),
    "env-S": (("env",), "-S"),
    "env-split-string": (("env",), "--split-string="),
}


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder, with made-up ``gcloud`` and clients that do nothing first on PATH."""
    programs = tmp_path / "bin"
    programs.mkdir()
    for name in ("gcloud", *CLIENT_TEXTS):
        path = programs / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "pairbench.toml").write_text(SIDES, encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


def workload(option: str, client: str, password: str) -> list[str]:
    head, joint = OPTIONS[option]
    return [*head, joint + CLIENT_TEXTS[client][0].replace("{s}", password)]


def run(cli: Cli, work: Path, words: list[str], name: str, config: str = "pairbench.toml") -> Path:
    """Run the two sides with one workload; return the run folder, moved aside under ``name``.

    Every run writes to the same folder, which is then moved aside, so the
    configs of two runs differ in the workload alone.
    """
    result = cli("run", "--config", config, *QUICK, "--out", "out", "--", *words)
    assert result.code == EXIT_OK, result.err
    return (work / "out").rename(work / name)


def pooled(cli: Cli, work: Path, folders: list[Path]) -> dict[str, Any]:
    """Compare two runs that differ in the password alone; return the hashes they share.

    No six characters in a row of either password are in a shared file of
    either run, on a stream of ``compare`` or in the files it writes, and
    ``compare`` pools the two captures.
    """
    compared = cli(
        "compare", folders[0] / "capture.jsonl", folders[1] / "capture.jsonl", "--out", "pooled"
    )

    assert compared.code == EXIT_OK, compared.err
    assert pieces(compared.out) == []
    assert pieces(compared.err) == []
    for folder in folders:
        assert pieces(read(folder, SHARED_FILES)) == []
    assert pieces(read(work / "pooled", COMPARED_FILES)) == []
    pool = json.loads((work / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert pool["run"]["pooled"] is True
    first, second = (hashes(folder) for folder in folders)
    assert first == second
    return first


def pieces(text: str, passwords: tuple[str, ...] = PASSWORDS) -> list[str]:
    """Return each six characters in a row of any password that the text holds."""
    return [
        password[at : at + 6]
        for password in passwords
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


def read(folder: Path, names: tuple[str, ...]) -> str:
    return "".join((folder / name).read_text(encoding="utf-8") for name in names)


def hashes(folder: Path) -> dict[str, Any]:
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return {
        "config_sha256": results["provenance"]["config_sha256"],
        "fingerprints": {side["name"]: side["fingerprint"] for side in results["sides"]},
        "command": results["run"]["command"],
    }


@pytest.mark.slow
@pytest.mark.parametrize("client", sorted(CLIENT_TEXTS))
@pytest.mark.parametrize("option", sorted(OPTIONS))
def test_a_client_first_in_a_glued_text_keeps_its_password_out_of_every_shared_file(
    cli: Cli, work: Path, option: str, client: str
) -> None:
    folders = [
        run(cli, work, workload(option, client, password), password) for password in PASSWORDS
    ]

    first = pooled(cli, work, folders)
    head, joint = OPTIONS[option]
    shown = shlex.join([*head, joint + CLIENT_TEXTS[client][1]])
    assert first["command"] == f"{SHOWN_HEAD} {shown}"


# Two sides whose shell texts hand the workload to ``redis-benchmark`` as ``"$@"``.
PARAMETER_SIDES = (
    '[sides.a]\ncmd = ["sh", "-c", "redis-benchmark \\"$@\\"", "_", "{workload}"]\n'
    "baseline = true\n"
    '[sides.b]\ncmd = ["sh", "-c", "redis-benchmark -q \\"$@\\"", "_", "{workload}"]\n'
)
PARAMETER_CONFIG = "parameters.toml"
PARAMETER_SHOWN = (
    "pairbench run --config parameters.toml --gates off --rounds 6 --same-vs-same off "
    "--positive-control off --explain off --plots off --out out -- -a '<hidden>' -n 1000"
)


@pytest.mark.slow
def test_a_workload_a_side_shell_text_hands_to_a_client_keeps_its_password_out(
    cli: Cli, work: Path
) -> None:
    (work / PARAMETER_CONFIG).write_text(PARAMETER_SIDES, encoding="utf-8")
    folders = [
        run(cli, work, ["-a", password, "-n", "1000"], password, PARAMETER_CONFIG)
        for password in PASSWORDS
    ]

    assert pooled(cli, work, folders)["command"] == PARAMETER_SHOWN


SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)


def parameter_sides(work: Path, sides: list[list[str]]) -> str:
    """Write one side per command, the first the baseline; return the config's name."""
    tables = "".join(
        f"[sides.{name}]\ncmd = {json.dumps(cmd)}\n" for name, cmd in zip("ab", sides, strict=True)
    )
    (work / "sides.toml").write_text(tables + '[workload]\ndriver = "wall"\n', encoding="utf-8")
    return "sides.toml"


# Each form: a side's shell text, and its words after ``$0`` with ``{s}`` for the password
# and ``{p}`` for the program.
PARAMETER_FORMS: dict[str, tuple[str, list[str]]] = {
    "client-in-text": ('{p} "$@"', ["-a", "{s}", "-n", "1000"]),
    "client-a-parameter": ('"$1" -a "$2" -n 1000', ["{p}", "{s}"]),
    "all-parameters": ('exec "$@"', ["{p}", "-a", "{s}", "-n", "1000"]),
    "client-in-a-text-in-double-quotes": (
        'sh -c "{p} \\"\\$@\\"" _ "$@"',
        ["-a", "{s}", "-n", "1000"],
    ),
}
PROGRAMS = ("redis-benchmark", "./build-new/redis-benchmark")


def parameter_side(form: str, program: str, password: str) -> list[str]:
    text, words = PARAMETER_FORMS[form]
    filled = [word.replace("{s}", password).replace("{p}", program) for word in words]
    return ["sh", "-c", text.replace("{p}", program), "_", *filled]


@pytest.mark.parametrize("form", sorted(PARAMETER_FORMS))
def test_plan_takes_two_programs_a_shell_text_runs_with_its_parameters_as_two_sides(
    cli: Cli, work: Path, form: str
) -> None:
    config = parameter_sides(
        work, [parameter_side(form, program, PASSWORDS[0]) for program in PROGRAMS]
    )
    result = cli("plan", "--config", config)

    assert result.code == EXIT_OK, result.err
    assert pieces(result.out + result.err) == []


@pytest.mark.parametrize("form", sorted(PARAMETER_FORMS))
def test_plan_refuses_one_program_a_shell_text_runs_with_two_passwords(
    cli: Cli, work: Path, form: str
) -> None:
    config = parameter_sides(
        work, [parameter_side(form, PROGRAMS[0], password) for password in PASSWORDS]
    )
    result = cli("plan", "--config", config)

    assert result.code == EXIT_SIDE
    assert result.out == ""
    assert result.err == SAME_FINGERPRINT


# --- an image side whose own entrypoint is given the workload ----------------

ENGINE = "docker"
BASE_IMAGE = "busybox:1.37.0"
STEP_TIMEOUT_S = 120
# A stand-in for a client: it prints the time since the machine started as one value the
# ``lines`` driver reads, so that two runs never hold the same rows. ``{version}`` tells the
# images of two sides apart.
STAND_IN = (
    "#!/bin/sh\n"
    "# stand-in {version}\n"
    "read up _ < /proc/uptime\n"
    'echo "::pairbench:: {\\"case\\": \\"a\\", \\"value\\": $up, \\"unit\\": \\"s\\", '
    '\\"better\\": \\"lower\\"}"\n'
)
# A wrapper script as many images have: a first argument that is an option goes to the program
# the image's command names, anything else runs as given.
WRAPPER = '#!/bin/sh\nif [ "${1#-}" != "$1" ]; then set -- memtier_benchmark "$@"; fi\nexec "$@"\n'
# Each form: the image's entrypoint and command, the workload with ``{s}`` for the password, and
# the workload as shown.
IMAGE_FORMS: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "client-entrypoint": (
        '["memtier_benchmark"]',
        "[]",
        ("-s", "made-up-host", "-a", "{s}", "-n", "1000"),
        "-s made-up-host -a '<hidden>' -n 1000",
    ),
    "wrapper-script-then-command": (
        '["docker-entrypoint.sh"]',
        '["memtier_benchmark"]',
        ("-s", "made-up-host", "-a", "{s}", "-n", "1000"),
        "-s made-up-host -a '<hidden>' -n 1000",
    ),
    "no-entrypoint-client-first": (
        "[]",
        '["sh"]',
        ("memtier_benchmark", "-a", "{s}", "-n", "1000"),
        "memtier_benchmark -a '<hidden>' -n 1000",
    ),
}
IMAGE_SHOWN_HEAD = (
    "pairbench run --config images.toml --gates off --rounds 6 --same-vs-same off "
    "--positive-control off --explain off --plots off --out out --"
)


def _engine(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ENGINE, *args], capture_output=True, text=True, check=False, timeout=STEP_TIMEOUT_S
    )


class Images:
    """Images made from ``BASE_IMAGE`` with stand-in programs, all removed at the end.

    Each is made by committing a container that was created and never started.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._made: dict[tuple[str, str], str] = {}

    def made(self, form: str, version: str) -> str:
        if (form, version) in self._made:
            return self._made[(form, version)]
        if _engine("image", "inspect", BASE_IMAGE).returncode != 0:
            pytest.skip(f"needs the image {BASE_IMAGE} on this machine; it is never pulled here")
        entrypoint, command, _workload, _shown = IMAGE_FORMS[form]
        created = _engine(
            "create", "--rm", "--memory", "8g", "--memory-swap", "8g", "--network", "none",
            BASE_IMAGE, "true",
        )  # fmt: skip
        assert created.returncode == 0, created.stderr
        container = created.stdout.strip()
        tag = f"localhost/pairbench-client-texts:{uuid.uuid4().hex[:12]}"
        try:
            for name, text in (
                ("memtier_benchmark", STAND_IN.replace("{version}", version)),
                ("docker-entrypoint.sh", WRAPPER),
            ):
                local = self._folder / f"{tag.rsplit(':', 1)[1]}-{name}"
                local.write_text(text, encoding="utf-8")
                local.chmod(0o755)
                done = _engine("cp", str(local), f"{container}:/bin/{name}")
                assert done.returncode == 0, done.stderr
            done = _engine(
                "commit",
                "--change", f"ENTRYPOINT {entrypoint}",
                "--change", f"CMD {command}",
                container, tag,
            )  # fmt: skip
            assert done.returncode == 0, done.stderr
        finally:
            _engine("rm", "--force", container)
        self._made[(form, version)] = tag
        return tag

    def remove(self) -> None:
        for tag in self._made.values():
            _engine("rmi", "--force", tag)


@pytest.fixture(scope="module")
def images(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Images]:
    made = Images(tmp_path_factory.mktemp("image-files"))
    yield made
    made.remove()


def image_sides(work: Path, first: str, second: str) -> str:
    """Write two image sides that run the shared workload, the first the baseline."""
    (work / "images.toml").write_text(
        f'[sides.a]\nimage = "{first}"\nbaseline = true\n'
        f'[sides.b]\nimage = "{second}"\n'
        f'[launch]\nmemory = "8g"\npull = "never"\nengine = "{ENGINE}"\n'
        '[workload]\ndriver = "lines"\n',
        encoding="utf-8",
    )
    return "images.toml"


@pytest.mark.slow
@pytest.mark.parametrize("form", sorted(IMAGE_FORMS))
def test_a_client_an_image_runs_before_the_workload_keeps_its_password_out(
    cli: Cli, work: Path, needs: Any, images: Images, form: str
) -> None:
    needs.engine(ENGINE)
    config = image_sides(work, images.made(form, "1.0"), images.made(form, "2.0"))
    _entrypoint, _command, words, shown = IMAGE_FORMS[form]
    folders = [
        run(cli, work, [word.replace("{s}", password) for word in words], password, config)
        for password in PASSWORDS
    ]

    assert pooled(cli, work, folders)["command"] == f"{IMAGE_SHOWN_HEAD} {shown}"


# Inspect output with no ``Config``: the engine does not say what the image's entrypoint is.
NO_CONFIG = json.dumps(
    {
        "Id": "sha256:" + "0123456789abcdef" * 4,
        "RepoDigests": [],
        "Os": "linux",
        "Architecture": "arm64",
    }
)
UNREADABLE = refusal_text(
    "E_ENTRYPOINT_UNREADABLE: side 'a': the entrypoint of its image could not be read, so the "
    "program that runs the shared workload is not known; set sides.a.entrypoint to the program "
    "the image runs"
)


@pytest.mark.parametrize("command", ["plan", "run"])
def test_an_image_entrypoint_that_cannot_be_read_refuses_before_anything_runs(
    cli: Cli, work: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    # A stand-in for the engine: it answers what pairbench asks about the engine and the image,
    # logs each call, and fails anything else.
    programs = work.parent / "engine"
    programs.mkdir()
    log = work.parent / "engine-calls.txt"
    engine = programs / ENGINE
    engine.write_text(
        "#!/bin/sh\n"
        f'echo "$1" >> {shlex.quote(str(log))}\n'
        'case "$1" in\n'
        "  version) echo 9.9.9 ;;\n"
        "  info) echo '{}' ;;\n"
        f"  image) echo {shlex.quote(NO_CONFIG)} ;;\n"
        "  *) exit 99 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    engine.chmod(0o755)
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ['PATH']}")
    config = image_sides(work, "registry.example/tool:1", "registry.example/tool:2")
    words = ["-s", "made-up-host", "-a", PASSWORDS[0], "-n", "1000"]
    if command == "run":
        result = cli("run", "--config", config, *QUICK, "--out", "out", "--", *words)
    else:
        result = cli("plan", "--config", config, *QUICK, "--", *words)

    assert result.code == EXIT_SIDE
    assert result.out == ""
    assert result.err == UNREADABLE
    assert not (work / "out").exists()
    assert set(log.read_text(encoding="utf-8").split()) == {"version", "info", "image"}
