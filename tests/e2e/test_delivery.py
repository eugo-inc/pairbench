# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The installed command, end to end: exact ratios from seeded sides, the plan, the steps after.

The sides print values from ``seeded_side.py``: in one round a side of
factor 2 reads exactly twice what a side of factor 1 reads, so the ratios
are exact and written as constants. The environment holds no ``plot``
extra and finds no profiler, which the chart and explain tests rely on.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from .conftest import Done, Installed, capture_records, primary, read_json

pytestmark = [pytest.mark.delivery, pytest.mark.slow]

CASES = ("alpha", "beta", "gamma")
MARKER = "e2e_privacy_marker_qz7"
COMMON = ("--driver", "lines", "--vary-env-size", "--gates", "off", "--rounds", "8")
RESULTS_FILES = ("results.json", "results.md")


@dataclass(frozen=True)
class Run:
    """One run of the installed command and the folder it wrote."""

    done: Done
    folder: Path

    @property
    def results(self) -> Any:
        return read_json(self.folder / "results.json")


def two_sides(installed: Installed, subject: float, baseline: float, *extra: str) -> list[str]:
    return [
        "--side",
        f"new=cmd:{installed.seeded(subject, '--name', 'new', *extra)}",
        "--side",
        f"old=cmd:{installed.seeded(baseline, '--name', 'old', *extra)}",
    ]


def start(installed: Installed, folder: Path, *args: str) -> Run:
    done = installed.run("run", *args, "--out", folder, cwd=folder.parent)
    return Run(done=done, folder=folder)


@pytest.fixture(scope="module")
def twice(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """New reads twice old; charts on auto without the extra; the document on stdout."""
    folder = tmp_path_factory.mktemp("twice") / "run"
    sides = two_sides(installed, 2.0, 1.0)
    return start(
        installed,
        folder,
        *sides,
        "--baseline",
        "old",
        *COMMON,
        "--explain",
        "off",
        "--plots",
        "auto",
        "--json",
    )


@pytest.fixture(scope="module")
def explained(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """The same sides with the explain step on; each launch waits in the marker function."""
    folder = tmp_path_factory.mktemp("explained") / "run"
    sides = two_sides(installed, 2.0, 1.0, "--wait", "0.05")
    return start(
        installed,
        folder,
        *sides,
        "--baseline",
        "old",
        *COMMON,
        "--explain",
        "always",
        "--plots",
        "off",
        "--positive-control",
        "off",
    )


# ---------------------------------------------------------------------------
# The installation itself
# ---------------------------------------------------------------------------


def test_the_installed_command_is_the_wheel_not_the_source_tree(
    installed: Installed, work: Path
) -> None:
    import subprocess

    done = subprocess.run(
        [str(installed.python), "-c", "import pairbench; print(pairbench.__file__)"],
        capture_output=True,
        text=True,
        check=False,
        cwd=work,
        env=installed.environment(),
    )

    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()).resolve().is_relative_to(installed.venv.resolve())


def test_the_installed_command_prints_its_version(installed: Installed, work: Path) -> None:
    done = installed.run("--version", cwd=work)

    assert done.code == 0
    assert done.out.startswith("pairbench ")
    assert done.err == ""


@pytest.mark.parametrize("name", ["capture", "results", "config", "diagnostics"])
def test_the_wheel_carries_every_schema(name: str, installed: Installed, work: Path) -> None:
    done = installed.run("schema", name, cwd=work)

    assert done.code == 0
    assert json.loads(done.out)["$schema"].startswith("https://json-schema.org/")


def test_selftest_with_the_live_run_passes(installed: Installed, work: Path) -> None:
    done = installed.run("selftest", "--live", cwd=work)

    assert done.code == 0, done.out + done.err
    assert "pass  L1" in done.out
    assert "FAIL" not in done.out


def test_doctor_exits_0_and_finds_no_program_outside_its_path(
    installed: Installed, work: Path
) -> None:
    env = installed.environment()
    env["PATH"] = str(installed.bin)

    done = installed.run("doctor", "--json", cwd=work, env=env)

    assert done.code == 0
    document = json.loads(done.out)
    assert [tool["name"] for tool in document["tools"] if tool["found"]] == []
    assert document["plot_extra"] == {"installed": False}


def test_the_tool_server_without_its_extra_names_the_extra(
    installed: Installed, work: Path
) -> None:
    done = installed.run("mcp", cwd=work)

    assert done.code == 2
    assert done.err.startswith("E_USAGE: the tool server is not available here")
    assert "install pairbench[mcp]" in done.err


def test_skill_install_copies_the_skill_the_wheel_carries(installed: Installed, work: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "skills" / "pairbench"
    if not (source / "SKILL.md").is_file():
        pytest.skip("SKIPPED: this tree holds no skills/pairbench/SKILL.md, so the wheel has none")

    done = installed.run("skill", "install", "--dir", work / "skills", cwd=work)

    assert done.code == 0, done.err
    copied = work / "skills" / "pairbench" / "SKILL.md"
    assert copied.read_bytes() == (source / "SKILL.md").read_bytes()


# ---------------------------------------------------------------------------
# Exact ratios
# ---------------------------------------------------------------------------


def test_twice_the_work_reads_exactly_2(twice: Run) -> None:
    assert twice.done.code == 0, twice.done.err
    found = primary(twice.results)
    assert sorted(found) == [(case, "new") for case in CASES]
    for case in CASES:
        assert found[(case, "new")]["ratio"] == 2.0
        assert found[(case, "new")]["outcome"] == "worse"


def test_json_prints_the_final_document_alone(twice: Run) -> None:
    assert json.loads(twice.done.out) == twice.results


def test_the_positive_control_reads_2(twice: Run) -> None:
    control = twice.results["controls"]["positive"]
    assert control["status"] == "ok"
    assert control["entry"] == "old~twice"
    assert [(row["case"], row["ratio"]) for row in control["cases"]] == [
        (case, 2.0) for case in CASES
    ]


def test_equal_work_reads_exactly_1(
    installed: Installed, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("equal") / "run"
    run = start(
        installed,
        folder,
        *two_sides(installed, 1.0, 1.0),
        "--baseline",
        "old",
        *COMMON,
        "--explain",
        "off",
        "--plots",
        "off",
        "--positive-control",
        "off",
    )

    assert run.done.code == 0, run.done.err
    found = primary(run.results)
    for case in CASES:
        assert found[(case, "new")]["ratio"] == 1.0
        assert found[(case, "new")]["outcome"] not in ("better", "worse")


def test_the_swapped_baseline_reads_exactly_one_half(
    installed: Installed, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("swapped") / "run"
    run = start(
        installed,
        folder,
        *two_sides(installed, 2.0, 1.0),
        "--baseline",
        "new",
        *COMMON,
        "--explain",
        "off",
        "--plots",
        "off",
        "--positive-control",
        "off",
    )

    assert run.done.code == 0, run.done.err
    found = primary(run.results)
    assert sorted(found) == [(case, "old") for case in CASES]
    for case in CASES:
        assert found[(case, "old")]["ratio"] == 0.5
        assert found[(case, "old")]["outcome"] == "better"


def test_fail_on_a_worse_primary_case_exits_1(
    installed: Installed, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("failon") / "run"
    run = start(
        installed,
        folder,
        *two_sides(installed, 2.0, 1.0),
        "--baseline",
        "old",
        *COMMON,
        "--explain",
        "off",
        "--plots",
        "off",
        "--positive-control",
        "off",
        "--fail-on",
        "worse",
    )

    assert run.done.code == 1
    assert "pairbench: --fail-on worse: case alpha of side new against old" in run.done.err
    assert (folder / "results.json").is_file()


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def plan_rows(text: str) -> list[tuple[int, int, str]]:
    rows = [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]
    assert rows[0] == ["round", "pos", "name", "side", "twin_of"]
    return [(int(row[0]), int(row[1]), row[2]) for row in rows[1:]]


def test_the_capture_launches_every_row_of_the_plan_in_place(twice: Run) -> None:
    planned = plan_rows((twice.folder / "plan.tsv").read_text(encoding="utf-8"))
    launched = [
        (record["round"], record["pos"], record["name"])
        for record in capture_records(twice.folder, "launch")
        if record["phase"] == "round"
    ]

    assert launched == planned


def test_the_printed_plan_is_the_plan_the_run_followed(
    twice: Run, installed: Installed, work: Path
) -> None:
    done = installed.run(
        "plan",
        *two_sides(installed, 2.0, 1.0),
        "--baseline",
        "old",
        *COMMON,
        "--explain",
        "off",
        "--plots",
        "auto",
        cwd=work,
    )

    assert done.code == 0, done.err
    assert plan_rows(done.out) == plan_rows((twice.folder / "plan.tsv").read_text(encoding="utf-8"))
    assert list(work.iterdir()) == []


# ---------------------------------------------------------------------------
# Charts without the plot extra
# ---------------------------------------------------------------------------


def test_charts_on_auto_without_the_extra_record_the_reason(twice: Run) -> None:
    results = twice.results
    assert results["plots"] == {"status": "not_drawn", "reason": "extra_missing"}
    assert "charts_not_drawn" in [note["code"] for note in results["notes"]]
    assert "pairbench: note: charts_not_drawn: " in twice.done.err
    assert results["artifacts"]["charts"] == []


def test_charts_on_without_the_extra_are_refused_before_any_launch(
    installed: Installed, work: Path
) -> None:
    folder = work / "run"

    done = installed.run(
        "run",
        *two_sides(installed, 2.0, 1.0),
        *COMMON,
        "--plots",
        "on",
        "--out",
        folder,
        cwd=work,
    )

    assert done.code == 3
    assert done.err.startswith("E_PLOT_EXTRA_MISSING: ")
    assert done.out == ""
    assert not folder.exists()
    assert list(work.iterdir()) == []


# ---------------------------------------------------------------------------
# The explain step: privacy and skipped instruments
# ---------------------------------------------------------------------------


def test_names_from_the_stacks_stay_out_of_the_results_files(explained: Run) -> None:
    assert explained.done.code == 0, explained.done.err
    assert explained.results["diagnostics"]["status"] == "written"
    assert MARKER in (explained.folder / "diagnostics.json").read_text(encoding="utf-8")
    for name in RESULTS_FILES:
        assert MARKER not in (explained.folder / name).read_text(encoding="utf-8"), name


def test_a_skipped_instrument_is_loud_and_changes_no_verdict(explained: Run, twice: Run) -> None:
    assert explained.done.code == 0
    skipped = [n for n in explained.results["notes"] if n["code"] == "instrument_skipped"]
    assert skipped != []
    for note in skipped:
        assert f"pairbench: note: instrument_skipped: {note['message']}" in explained.done.err

    def verdicts(run: Run) -> dict[tuple[str, str], tuple[Any, ...]]:
        return {
            key: (c["baseline"], c["ratio"], c["outcome"])
            for key, c in primary(run.results).items()
        }

    assert verdicts(explained) == verdicts(twice)


def test_the_results_name_the_diagnostics_and_profiles_by_relative_path(explained: Run) -> None:
    artifacts = explained.results["artifacts"]
    assert artifacts["diagnostics"] == "diagnostics.json"
    for name in artifacts["profiles"]:
        assert not Path(name).is_absolute()
        assert (explained.folder / name).is_file()
    assert artifacts["html"] == "report.html"
    assert (explained.folder / "report.html").is_file()


# ---------------------------------------------------------------------------
# One run with real timing
# ---------------------------------------------------------------------------


def test_a_side_that_sleeps_twice_as_long_reads_about_2(
    installed: Installed, tmp_path_factory: pytest.TempPathFactory
) -> None:
    def sleeper(seconds: float) -> str:
        code = f"import time; time.sleep({seconds})"
        return f"{shlex.quote(str(installed.python))} -c {shlex.quote(code)}"

    folder = tmp_path_factory.mktemp("timing") / "run"
    run = start(
        installed,
        folder,
        "--side",
        f"slow=cmd:{sleeper(0.2)}",
        "--side",
        f"fast=cmd:{sleeper(0.1)}",
        "--baseline",
        "fast",
        "--driver",
        "wall",
        "--gates",
        "off",
        "--rounds",
        "8",
        "--explain",
        "off",
        "--plots",
        "off",
        "--positive-control",
        "off",
    )

    assert run.done.code == 0, run.done.err
    ratios = [c["ratio"] for c in primary(run.results).values()]
    assert len(ratios) == 1
    assert 1.3 <= ratios[0] <= 3.0
