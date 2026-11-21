# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pytest-benchmark driver reads pytest-benchmark's JSON output."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, ToolVersion
from pairbench.drivers.pytest_benchmark import PytestBenchmarkDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "pytest-benchmark"
OUTPUT = "pytest-benchmark.json"
TESTS = (
    "test_made_up.py::test_build_list[16]",
    "test_made_up.py::test_build_list[256]",
    "test_made_up.py::test_join_text",
)


def _write(folder: Path, doc: Any) -> None:
    (folder / OUTPUT).write_text(json.dumps(doc), encoding="utf-8")


def test_the_data_of_each_round_give_their_median(
    make_ctx: MakeCtx, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURES / OUTPUT, tmp_path / OUTPUT)
    driver = PytestBenchmarkDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.n_inner, s.reducer) for s in samples
    ] == [(name, "time", "s", "lower", "time", 7, "median") for name in TESTS]
    assert [s.value for s in samples] == pytest.approx(
        [2.4805194698274136e-07, 4.847999662160873e-06, 2.686314186767528e-07], rel=1e-12
    )
    assert driver.default_primary(samples) == list(TESTS)
    assert capsys.readouterr() == ("", "")


def test_a_saved_run_without_the_data_gives_the_tools_median(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    shutil.copy(FIXTURES / "saved.json", tmp_path / OUTPUT)
    samples = PytestBenchmarkDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.n_inner, s.reducer) for s in samples] == [
        (name, 7, "tool_summary") for name in TESTS
    ]
    assert [s.value for s in samples] == pytest.approx(
        [2.3771454358384723e-07, 4.464061930775642e-06, 2.600019797682762e-07], rel=1e-12
    )


def test_one_round_of_data_is_taken_as_it_is(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(tmp_path, {"benchmarks": [{"fullname": "t.py::a", "stats": {"data": [0.5]}}]})
    sample = PytestBenchmarkDriver().read(make_ctx(), tmp_path)[0]
    assert (sample.value, sample.n_inner, sample.reducer) == (0.5, 1, "identity")


def test_the_version_is_read_from_the_file(make_ctx: MakeCtx, tmp_path: Path) -> None:
    shutil.copy(FIXTURES / OUTPUT, tmp_path / OUTPUT)
    driver = PytestBenchmarkDriver()
    assert driver.tool_version(make_ctx(), tmp_path) == ToolVersion(
        "pytest-benchmark", "5.3.1", True
    )
    _write(tmp_path, {"version": "4.0.0", "benchmarks": []})
    assert driver.tool_version(make_ctx(), tmp_path) == ToolVersion(
        "pytest-benchmark", "4.0.0", False
    )


def test_prepare_adds_the_output_option(make_ctx: MakeCtx) -> None:
    argv = PytestBenchmarkDriver().prepare(make_ctx(), ["python", "-m", "pytest", "bench/"]).argv
    assert argv == (
        "python",
        "-m",
        "pytest",
        "bench/",
        "--benchmark-json=/pairbench/artifacts/pytest-benchmark.json",
    )


@pytest.mark.parametrize("arg", ["--benchmark-json=out.json", "--benchmark-json"])
def test_a_command_with_the_output_option_is_refused(make_ctx: MakeCtx, arg: str) -> None:
    with pytest.raises(Refusal) as caught:
        PytestBenchmarkDriver().prepare(make_ctx(), ["pytest", arg, "out.json"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "--benchmark-json" in caught.value.message


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"benchmarks": None}, "pytest-benchmark.json: benchmarks is not a list"),
        ({"benchmarks": [{"stats": {}}]}, "pytest-benchmark.json: benchmarks[0] has no fullname"),
        (
            {"benchmarks": [{"fullname": "t.py::a"}]},
            "pytest-benchmark.json: benchmarks[0] has no stats",
        ),
        (
            {"benchmarks": [{"fullname": "t.py::a", "stats": {"data": [0.5, "x"]}}]},
            "pytest-benchmark.json: benchmarks[0]: stats.data[1] is not a number",
        ),
        (
            {"benchmarks": [{"fullname": "t.py::a", "stats": {"rounds": 3}}]},
            "pytest-benchmark.json: benchmarks[0]: stats has no median",
        ),
        (
            {"benchmarks": [{"fullname": "t.py::a", "stats": {"median": 1.0, "rounds": -1}}]},
            "pytest-benchmark.json: benchmarks[0]: "
            "stats.rounds is not a whole number of zero or more",
        ),
        (
            {"benchmarks": [{"fullname": "t.py::a", "stats": {"median": 1.0}}] * 2},
            "pytest-benchmark.json: the case 't.py::a' is given twice",
        ),
        (
            {"benchmarks": []},
            "pytest-benchmark.json: the pytest-benchmark output holds no measured case",
        ),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, message: str
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        PytestBenchmarkDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_the_registry_loads_the_pytest_benchmark_driver() -> None:
    driver = registry.driver("pytest-benchmark")
    assert isinstance(driver, PytestBenchmarkDriver)
    assert (driver.name, driver.where) == ("pytest-benchmark", "in_side")
    assert isinstance(driver, api.ReportsToolVersion)
    assert driver.doctor().status == "ok"
