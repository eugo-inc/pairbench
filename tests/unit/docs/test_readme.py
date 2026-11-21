# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The README is the filled template and keeps its outline.

The section on native code waits for a run until the repository keeps the launch-cost
results in ``docs/figures/launch-cost/``; from then on every number in it is a figure token
filled from them. These tests follow that file as the pipeline does: they fill with
``--results`` when it is kept. The checks of the filled state run on a made-up kept folder,
and on the kept folder once it is there.
"""

from __future__ import annotations

import contextlib
import getpass
import io
import json
import re
import shutil
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from pairbench.model import MACHINE_STATUSES

from .conftest import REPOSITORY_FILES

TEMPLATE = "docs/readme/README.in.md"
README = "README.md"
EXIT_OK = 0

# The thirteen sections of the outline, in order, after the title.
SECTIONS = (
    "The headline command",
    "Four problems it solves",
    "Install and quick start",
    "How it decides",
    "What a run tells you besides the verdict",
    "Why pairbench is not written in native code",
    "The tools it launches and reads",
    "Showcases",
    "For AI agents",
    "How it relates to other tools",
    "Limits",
    "Cite, licence, contributing, security",
)
NATIVE = "Why pairbench is not written in native code"
# The six points of the section on native code, in order, each by words it holds.
NATIVE_POINTS = (
    "does nothing it can avoid",
    "measures the cost of a launch and reports it",
    "the same on every side",
    "the start of a process and the workload dominate",
    "pure Python on the standard library",
    "native launcher can be added as a plug-in",
)
WAITING = "waiting for a run"
# The README is read on GitHub and on the package index, where a relative link leads
# nowhere: it links the pages of the documentation site and the files of the repository by
# their addresses, and the documentation near its top.
DOCS_SITE = "https://eugo.io/docs/pairbench/"
DOCS_HOME = f"{DOCS_SITE}latest/"
TOP_LINES = 10
LINKS_AT_LEAST = 40
FIGURE_TOKEN = re.compile(r"\{\{\s*fig:")
TOKEN = re.compile(r"\{\{fig:[^}]*\}\}")
HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
EXIT_CHECK_FAILED = 1
# The folder the launch-cost results are kept in once a run of tools/launch_cost.py is kept,
# and its two files: the results the section is filled from, and the class of machine.
KEPT = "docs/figures/launch-cost"
KEPT_RESULTS = f"{KEPT}/results.json"
KEPT_CLASS = f"{KEPT}/machine-class.txt"
# The figures the six points need, each a token in the section once a run is kept.
NATIVE_FIGURES = (
    "launch_cost.median",
    "launch_cost.spread",
    "wall.default.median",
    "wall.nosite.median",
)


def readme(repo_root: Path) -> str:
    return (repo_root / README).read_text(encoding="utf-8")


def section(text: str, title: str) -> str:
    return text.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


def kept_results(root: Path) -> list[Path | str]:
    """The ``--results`` of the README's fill: the kept launch-cost results, if any."""
    results = root / KEPT_RESULTS
    return ["--results", results] if results.is_file() else []


def stray_numbers(text: str, machine_class: str) -> list[str]:
    """Each word of a text that holds a digit outside its figure tokens and its class of
    machine, which the class file gives."""
    rest = TOKEN.sub(" ", text).replace(machine_class, " ")
    return re.findall(r"\S*\d\S*", rest)


def test_the_readme_is_the_filled_template(
    repo_root: Path, cli: Callable[..., Any], tmp_path: Path
) -> None:
    out = tmp_path / "README.md"

    result = cli("fill", repo_root / TEMPLATE, *kept_results(repo_root), "-o", out)

    assert result.code == EXIT_OK, result.err
    assert out.read_text(encoding="utf-8") == readme(repo_root)


def test_the_check_of_the_pipeline_passes(repo_root: Path, cli: Callable[..., Any]) -> None:
    result = cli(
        "fill", repo_root / TEMPLATE, *kept_results(repo_root), "-o", repo_root / README, "--check"
    )

    assert result.code == EXIT_OK, result.err


def test_the_fill_takes_the_kept_results_only_once_they_are_kept(tmp_path: Path) -> None:
    assert kept_results(tmp_path) == []

    (tmp_path / KEPT).mkdir(parents=True)
    (tmp_path / KEPT_RESULTS).write_text("{}\n", encoding="utf-8")

    assert kept_results(tmp_path) == ["--results", tmp_path / KEPT_RESULTS]


def test_the_readme_holds_no_unfilled_figure(repo_root: Path) -> None:
    assert not FIGURE_TOKEN.search(readme(repo_root))


def test_the_readme_follows_the_outline(repo_root: Path) -> None:
    text = readme(repo_root)

    assert text.startswith("# pairbench\n")
    assert tuple(HEADING.findall(text)) == SECTIONS


def test_the_section_on_native_code_makes_six_points_in_order(repo_root: Path) -> None:
    body = " ".join(section(readme(repo_root), NATIVE).split())
    places = [body.find(point) for point in NATIVE_POINTS]

    assert -1 not in places, places
    assert places == sorted(places)


def test_the_section_on_native_code_holds_no_number_until_a_run(repo_root: Path) -> None:
    body = section(readme(repo_root), NATIVE)
    waiting = [line for line in body.splitlines() if WAITING in line]
    tokens = TOKEN.findall(section((repo_root / TEMPLATE).read_text(encoding="utf-8"), NATIVE))

    if (repo_root / KEPT_RESULTS).is_file():
        assert waiting == []
        assert tokens != []
    else:
        assert len(waiting) == 1
        assert not re.search(r"\d", body)
        assert tokens == []


# ---------------------------------------------------------------------------
# The filled state: on a made-up kept folder, and on the kept folder once it is there
# ---------------------------------------------------------------------------


class Kept(NamedTuple):
    """A template, the launch-cost results it is filled from, their class of machine and
    the README filled from them."""

    template: Path
    results: Path
    machine_class: str
    readme: Path


# What the section says of the quiet wait: the script waits on the host, and the run inside
# the container cannot see that wait, so the section names no state of the machine.
QUIET_FIRST = (
    "The script waits for a quiet machine on the host before the run starts; inside the "
    "container the run records only what its own checks can see from there."
)
# A made-up class of machine, and a made-up form of the section with its numbers as tokens.
MADE_UP_CLASS = "arm64, 4 cores, 16 GB"
MADE_UP_SECTION = (
    f"Measured on one {MADE_UP_CLASS} machine. {QUIET_FIRST}\n\n"
    "- A launch cost {{fig:launch_cost.median}}, with {{fig:launch_cost.spread}} between the "
    "quartiles.\n"
    "- The workload took {{fig:wall.default.median}} on one side and "
    "{{fig:wall.nosite.median}} on the other.\n\n"
)


def main_of(*args: object) -> tuple[int, str]:
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = main([str(a) for a in args])
    return code, err.getvalue()


@pytest.fixture(scope="module")
def made_up_kept(repo_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Kept:
    """A made-up kept folder: the results of a short real run of two command sides named as
    the launch-cost script names them, a class of machine, a template whose section holds
    figure tokens, and the README filled from them."""
    base = tmp_path_factory.mktemp("kept")
    with contextlib.chdir(base):
        code, err = main_of(
            "run",
            "--side",
            "default=cmd:true",
            "--side",
            "nosite=cmd:env true",
            "--baseline",
            "default",
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
        )
    assert code == EXIT_OK, err
    (base / KEPT).mkdir(parents=True)
    shutil.copyfile(base / "run" / "results.json", base / KEPT_RESULTS)
    (base / KEPT_CLASS).write_text(MADE_UP_CLASS + "\n", encoding="utf-8")
    head, rest = (repo_root / TEMPLATE).read_text(encoding="utf-8").split(f"## {NATIVE}\n", 1)
    template = base / TEMPLATE
    template.parent.mkdir(parents=True)
    template.write_text(
        f"{head}## {NATIVE}\n\n{MADE_UP_SECTION}## {rest.split(chr(10) + '## ', 1)[1]}",
        encoding="utf-8",
    )
    code, err = main_of("fill", template, "--results", base / KEPT_RESULTS, "-o", base / README)
    assert code == EXIT_OK, err
    return Kept(template, base / KEPT_RESULTS, MADE_UP_CLASS, base / README)


@pytest.fixture(params=["made-up", "kept"])
def kept(request: pytest.FixtureRequest, repo_root: Path) -> Kept:
    if request.param == "made-up":
        made_up: Kept = request.getfixturevalue("made_up_kept")
        return made_up
    if not (repo_root / KEPT_RESULTS).is_file():
        pytest.skip(f"needs {KEPT_RESULTS}, which a kept run of tools/launch_cost.py adds")
    given = (repo_root / KEPT_CLASS).read_text(encoding="utf-8").removesuffix("\n")
    return Kept(repo_root / TEMPLATE, repo_root / KEPT_RESULTS, given, repo_root / README)


def test_the_readme_figures_match_the_kept_results(kept: Kept, cli: Callable[..., Any]) -> None:
    result = cli("fill", kept.template, "--results", kept.results, "-o", kept.readme, "--check")

    assert (result.code, result.err) == (EXIT_OK, "")


def test_the_check_fails_on_a_figure_the_kept_results_do_not_give(
    made_up_kept: Kept, cli: Callable[..., Any], tmp_path: Path
) -> None:
    results = json.loads(made_up_kept.results.read_text(encoding="utf-8"))
    results["figures"]["launch_cost.median"]["text"] = "0.123 s"
    changed = tmp_path / "results.json"
    changed.write_text(json.dumps(results), encoding="utf-8")

    result = cli(
        "fill", made_up_kept.template, "--results", changed, "-o", made_up_kept.readme, "--check"
    )

    assert (result.code, result.out, result.err) == (
        EXIT_CHECK_FAILED,
        "",
        "pairbench: fill --check: README.md does not match its results\n",
    )


def test_the_filled_section_holds_no_number_but_its_figures_and_its_class(kept: Kept) -> None:
    body = section(kept.template.read_text(encoding="utf-8"), NATIVE)

    assert [key for key in NATIVE_FIGURES if f"{{{{fig:{key}}}}}" not in body] == []
    assert kept.machine_class in body
    assert WAITING not in body
    assert stray_numbers(body, kept.machine_class) == []
    assert WAITING not in section(kept.readme.read_text(encoding="utf-8"), NATIVE)


def named_states(text: str) -> list[str]:
    """Each state of the machine the text names, beyond the quiet machine the script waits
    for on the host."""
    words = " ".join(text.split()).replace(QUIET_FIRST, " ")
    named = [state for state in MACHINE_STATUSES if re.search(rf"\b{state}\b", words, re.I)]
    return [*named, "machine state"] if re.search(r"machine state", words, re.I) else named


def test_the_kept_section_says_the_quiet_wait_and_names_no_machine_state(kept: Kept) -> None:
    body = " ".join(section(kept.template.read_text(encoding="utf-8"), NATIVE).split())

    assert QUIET_FIRST in body
    assert named_states(body) == []


@pytest.mark.parametrize("page", [TEMPLATE, README])
def test_the_waiting_section_names_no_machine_state(repo_root: Path, page: str) -> None:
    assert named_states(section((repo_root / page).read_text(encoding="utf-8"), NATIVE)) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (QUIET_FIRST, []),
        (f"Measured on one {MADE_UP_CLASS} machine.\n{QUIET_FIRST}", []),
        (
            "The script waits for a quiet machine on the host first, so the results record the "
            "machine state inside the container as unknown.",
            ["quiet", "unknown", "machine state"],
        ),
        ("Machine state: busy.", ["busy", "machine state"]),
        ("Measured on one quiet machine.", ["quiet"]),
        ("The run was Unknown to the host.", ["unknown"]),
        ("A launch cost {{fig:launch_cost.median}} on a made-up machine.", []),
    ],
    ids=[
        "the-sentence",
        "the-sentence-wrapped",
        "a-state-said",
        "the-report-line",
        "quiet-said-of-the-run",
        "in-another-case",
        "no-state",
    ],
)
def test_a_machine_state_the_section_names_is_found(text: str, found: list[str]) -> None:
    assert named_states(text) == found


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("A launch cost {{fig:launch_cost.median}} on one c7-made-up-2 machine.", []),
        ("A launch cost 0.5 ms on one c7-made-up-2 machine.", ["0.5"]),
        ("It took {{fig:wall.default.median}}, about 3x the launch.", ["3x"]),
        ("On one c7-made-up-3 machine.", ["c7-made-up-3"]),
    ],
    ids=["tokens-and-class", "a-typed-time", "a-typed-ratio", "another-class"],
)
def test_a_number_typed_into_the_section_is_found(text: str, found: list[str]) -> None:
    assert stray_numbers(text, "c7-made-up-2") == found


# Every machine fact a results document holds, with the form a public hardware fact takes
# there: the operating system of the run, the architecture, the CPU model string and the
# core-type keys, the model and driver of each GPU, the engine and its version, and the type
# of node the user named. None of them may name a host, a user, a folder of the machine or a
# value of its environment (AGENTS.md rule 4, SECURITY.md, "What results may hold").
PROVENANCE_FIELDS = ("config_sha256", "driver", "engine", "gpu", "machine", "node_type", "seeds")
MACHINE_FACTS = {
    "os": re.compile(r"[A-Za-z][A-Za-z0-9 ._+()/-]*"),
    "arch": re.compile(r"aarch64|arm64|x86_64|amd64|i[3-6]86|ppc64le|s390x|riscv64"),
    "cpu_model": re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()@.,_+/-]*"),
}
CORE_TYPE = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")
GPU_FACTS = {
    "model": re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._-]*"),
    "driver": re.compile(r"[0-9]+(?:\.[0-9]+)*"),
}
ENGINE_FACTS = {
    "name": re.compile(r"docker|podman"),
    "version": re.compile(r"[0-9][0-9A-Za-z.+~-]*"),
}
NODE_TYPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ,._-]*")
# The folders a kept run may name: the checkout reached at /work and the neutral home.
NEUTRAL_FOLDERS = ("/work", "/home/user")
ABSOLUTE_PATH = re.compile(r"(?<![\w.:/~-])/[\w.-]+(?:/[\w.-]+)*")
# A tool version as the package gives it.
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc|\.post|\.dev)[0-9]+)*(?:\+[\w.]+)?")


def hardware_problems(results: Any) -> list[str]:
    """Each machine fact of a results document that is not in the form of a public fact."""
    found: list[str] = []
    provenance = results["provenance"]
    if tuple(sorted(provenance)) != PROVENANCE_FIELDS:
        found.append(f"provenance holds {sorted(provenance)}")
    machine = provenance["machine"]
    if sorted(machine) != sorted([*MACHINE_FACTS, "core_types"]):
        found.append(f"provenance.machine holds {sorted(machine)}")
    for name, form in MACHINE_FACTS.items():
        if not form.fullmatch(str(machine.get(name))):
            found.append(f"provenance.machine.{name} is {machine.get(name)!r}")
    found += [
        f"provenance.machine.core_types holds {key!r}"
        for key in machine.get("core_types", [])
        if not CORE_TYPE.fullmatch(str(key))
    ]
    for index, gpu in enumerate(provenance["gpu"]):
        if sorted(gpu) != sorted(GPU_FACTS) or not all(
            form.fullmatch(str(gpu[name])) for name, form in GPU_FACTS.items()
        ):
            found.append(f"provenance.gpu[{index}] is {gpu!r}")
    engine = provenance["engine"]
    if engine is not None and (
        sorted(engine) != sorted(ENGINE_FACTS)
        or not all(form.fullmatch(str(engine[name])) for name, form in ENGINE_FACTS.items())
    ):
        found.append(f"provenance.engine is {engine!r}")
    node = provenance["node_type"]
    if node is not None and not NODE_TYPE.fullmatch(str(node)):
        found.append(f"provenance.node_type is {node!r}")
    return found


def strings(value: Any) -> Iterator[str]:
    """Every text in a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def identity_problems(results: Any) -> list[str]:
    """Each text of a results document that names this machine's host, user or home, or a
    folder outside the neutral places a kept run may name."""
    found: set[str] = set()
    names = {socket.gethostname().split(".")[0], getpass.getuser(), str(Path.home())}
    for text in strings(results):
        found |= {f"names {name!r}" for name in names if len(name) > 2 and name in text}
        found |= {
            f"holds the path {path}"
            for path in ABSOLUTE_PATH.findall(text)
            if not any(path == top or path.startswith(f"{top}/") for top in NEUTRAL_FOLDERS)
        }
    return sorted(found)


def test_the_kept_results_hold_only_public_hardware_facts(kept: Kept) -> None:
    results = json.loads(kept.results.read_text(encoding="utf-8"))

    assert hardware_problems(results) == []
    assert identity_problems(results) == []


@pytest.mark.parametrize(
    ("change", "found"),
    [
        (
            lambda p: p["machine"].update(hostname="markerhost-c"),
            ["provenance.machine holds ['arch', 'core_types', 'cpu_model', 'hostname', 'os']"],
        ),
        (
            lambda p: p["machine"].update(cpu_model="made-up CPU <markerhost-c>"),
            ["provenance.machine.cpu_model is 'made-up CPU <markerhost-c>'"],
        ),
        (
            lambda p: p.update(node_type="made-up node\n"),
            ["provenance.node_type is 'made-up node\\n'"],
        ),
        (
            lambda p: p.update(engine={"name": "made-up-engine", "version": "1.2"}),
            ["provenance.engine is {'name': 'made-up-engine', 'version': '1.2'}"],
        ),
        (
            lambda p: p.update(gpu=[{"model": "Made-Up GPU", "driver": "1.2", "uuid": "x"}]),
            ["provenance.gpu[0] is {'model': 'Made-Up GPU', 'driver': '1.2', 'uuid': 'x'}"],
        ),
        (
            lambda p: p.update(host="markerhost-c"),
            [f"provenance holds {sorted([*PROVENANCE_FIELDS, 'host'])}"],
        ),
    ],
    ids=["a-host-field", "a-cpu-model", "a-node-type", "an-engine", "a-gpu-field", "a-new-field"],
)
def test_a_machine_fact_in_no_public_form_is_found(
    made_up_kept: Kept, change: Any, found: list[str]
) -> None:
    results = json.loads(made_up_kept.results.read_text(encoding="utf-8"))
    change(results["provenance"])

    assert hardware_problems(results) == found


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("pairbench run --out pairbench-runs/launch-cost-x", []),
        ("/work/src and /home/user/.cache", []),
        ("/home/made-up-user/bench", ["holds the path /home/made-up-user/bench"]),
        ("ran from /srv/made-up/checkout", ["holds the path /srv/made-up/checkout"]),
        ("GNU/Linux and https://eugo.io/docs/pairbench/", []),
    ],
    ids=["relative", "neutral-folders", "a-home-folder", "a-machine-folder", "no-path"],
)
def test_a_folder_of_the_machine_in_the_results_is_found(text: str, found: list[str]) -> None:
    assert identity_problems({"run": {"command": text}}) == found


def test_the_kept_results_name_the_tool_and_its_version(kept: Kept) -> None:
    tool = json.loads(kept.results.read_text(encoding="utf-8"))["tool"]

    assert sorted(tool) == ["name", "version"]
    assert tool["name"] == "pairbench"
    assert VERSION.fullmatch(tool["version"]), tool


def test_every_link_of_the_readme_is_absolute(repo_root: Path, kit: Any) -> None:
    targets = kit.links(readme(repo_root))

    assert len(targets) >= LINKS_AT_LEAST
    assert [t for t in targets if not t.startswith(("https://", "#"))] == []


def test_the_readme_links_the_documentation_near_the_top(repo_root: Path) -> None:
    top = readme(repo_root).splitlines()[:TOP_LINES]

    assert [line for line in top if f"]({DOCS_HOME})" in line] != []


def test_the_readme_links_resolve(repo_root: Path, kit: Any) -> None:
    broken: list[str] = []
    for target in kit.links(readme(repo_root)):
        own = target.startswith((DOCS_SITE, *REPOSITORY_FILES))
        if target.startswith("#") or (re.match(r"^[a-z]+:", target) and not own):
            continue
        linked = kit.linked_file(repo_root, target)
        if linked is None or not linked.exists():
            broken.append(target)

    assert broken == []


@pytest.mark.parametrize(
    "target",
    [
        "https://eugo.io/docs/pairbench/latest/method/sign-tests/",
        "https://eugo.io/docs/pairbench/latest/method/sign-test",
        "https://eugo.io/docs/pairbench/latest/made-up/page/",
        "https://github.com/eugo-inc/pairbench/blob/main/CITATION.cfg",
        "docs/method/sign-tests.md",
    ],
)
def test_a_mistyped_link_names_no_file(repo_root: Path, kit: Any, target: str) -> None:
    linked = kit.linked_file(repo_root, target)

    assert linked is None or not linked.exists()


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("https://eugo.io/docs/pairbench/latest/", "docs/index.md"),
        ("https://eugo.io/docs/pairbench/latest/method/", "docs/method/index.md"),
        ("https://eugo.io/docs/pairbench/latest/method/sign-test/", "docs/method/sign-test.md"),
        ("https://eugo.io/docs/pairbench/latest/faq/#why", "docs/faq.md"),
        ("https://github.com/eugo-inc/pairbench/blob/main/CITATION.cff", "CITATION.cff"),
        ("https://github.com/eugo-inc/pairbench/tree/main/showcases", "showcases"),
    ],
)
def test_a_link_names_the_file_it_is_built_from(
    repo_root: Path, kit: Any, target: str, path: str
) -> None:
    assert kit.linked_file(repo_root, target) == repo_root / path
