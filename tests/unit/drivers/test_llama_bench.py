# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The llama-bench driver reads llama-bench's JSON output from standard output."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, ToolVersion
from pairbench.drivers.llama_bench import LlamaBenchDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "llama-bench" / "stdout.txt"
)


def _write(folder: Path, doc: Any) -> None:
    (folder / "stdout.txt").write_text(json.dumps(doc), encoding="utf-8")


def _test(**changes: Any) -> dict[str, Any]:
    test: dict[str, Any] = {
        "build_commit": "0000000",
        "build_number": 1,
        "n_prompt": 0,
        "n_gen": 8,
        "n_depth": 0,
        "avg_ts": 20.0,
        "samples_ts": [10.0, 20.0, 40.0],
    }
    test.update(changes)
    return test


def test_a_real_run_gives_the_median_rate_of_each_test(
    make_ctx: MakeCtx, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURE, tmp_path / "stdout.txt")
    driver = LlamaBenchDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.n_inner, s.reducer) for s in samples
    ] == [
        ("pp64", "tokens_per_s", "tokens/s", "higher", "rate", 3, "median"),
        ("tg16", "tokens_per_s", "tokens/s", "higher", "rate", 3, "median"),
    ]
    assert [s.value for s in samples] == [4483.86, 1141.16]
    assert driver.default_primary(samples) == ["tg16"]
    assert driver.tool_version(make_ctx(), tmp_path) == ToolVersion(
        "llama-bench", "b12375 (9d25e0014)", True
    )
    assert capsys.readouterr() == ("", "")


def test_another_build_is_reported_untested(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(tmp_path, [_test(build_number=13000, build_commit="abc1234")])
    assert LlamaBenchDriver().tool_version(make_ctx(), tmp_path) == ToolVersion(
        "llama-bench", "b13000 (abc1234)", False
    )


@pytest.mark.parametrize(
    ("changes", "case"),
    [
        ({"n_prompt": 512, "n_gen": 0}, "pp512"),
        ({"n_prompt": 0, "n_gen": 128}, "tg128"),
        ({"n_prompt": 512, "n_gen": 128}, "pp512+tg128"),
        ({"n_prompt": 0, "n_gen": 128, "n_depth": 4096}, "tg128 @ d4096"),
    ],
)
def test_tests_are_named_as_the_tools_own_table_names_them(
    make_ctx: MakeCtx, tmp_path: Path, changes: dict[str, int], case: str
) -> None:
    _write(tmp_path, [_test(**changes)])
    assert [s.case for s in LlamaBenchDriver().read(make_ctx(), tmp_path)] == [case]


def test_a_combined_test_is_secondary_and_a_test_at_depth_is_primary(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        [_test(n_prompt=8, n_gen=8), _test(n_gen=8, n_depth=64), _test(n_prompt=8, n_gen=0)],
    )
    driver = LlamaBenchDriver()
    assert driver.default_primary(driver.read(make_ctx(), tmp_path)) == ["tg8 @ d64"]


def test_without_samples_the_tools_mean_is_taken(make_ctx: MakeCtx, tmp_path: Path) -> None:
    test = _test()
    del test["samples_ts"]
    _write(tmp_path, [test])
    sample = LlamaBenchDriver().read(make_ctx(), tmp_path)[0]
    assert (sample.value, sample.n_inner, sample.reducer) == (20.0, 1, "tool_summary")


def test_prepare_asks_for_json(make_ctx: MakeCtx) -> None:
    argv = ["llama-bench", "-m", "model.gguf", "-p", "64"]
    assert LlamaBenchDriver().prepare(make_ctx(), argv).argv == (*argv, "-o", "json")


@pytest.mark.parametrize("option", ["-o", "--output"])
def test_a_command_that_asks_for_json_is_kept(make_ctx: MakeCtx, option: str) -> None:
    argv = ["llama-bench", option, "json", "-m", "model.gguf"]
    assert LlamaBenchDriver().prepare(make_ctx(), argv).argv == tuple(argv)


@pytest.mark.parametrize("argv", [["llama-bench", "-o", "md"], ["llama-bench", "--output"]])
def test_another_output_format_is_refused(make_ctx: MakeCtx, argv: list[str]) -> None:
    with pytest.raises(Refusal) as caught:
        LlamaBenchDriver().prepare(make_ctx(), argv)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("the llama-bench driver reads the output format json")


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"n_gen": 8}, "stdout.txt is not a list"),
        ([_test(n_gen=0)], "stdout.txt: [0]: a test with neither prompt nor generated tokens"),
        ([{"n_prompt": 0}], "stdout.txt: [0] has no n_gen"),
        ([_test(n_gen=-1)], "stdout.txt: [0]: n_gen is not a whole number of zero or more"),
        ([_test(samples_ts=[1.0, "x"])], "stdout.txt: [0]: samples_ts[1] is not a number"),
        ([_test(t=4), _test(t=8)], "stdout.txt: the case 'tg8' is given twice"),
        ([], "stdout.txt: the llama-bench output holds no measured case"),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, message: str
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        LlamaBenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_markdown_on_standard_output_is_refused(make_ctx: MakeCtx, tmp_path: Path) -> None:
    (tmp_path / "stdout.txt").write_text("| model | size |\n", encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        LlamaBenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert (
        caught.value.message == "stdout.txt is not valid JSON (line 1, column 1): Expecting value"
    )


def test_the_registry_loads_the_llama_bench_driver() -> None:
    driver = registry.driver("llama-bench")
    assert isinstance(driver, LlamaBenchDriver)
    assert (driver.name, driver.where) == ("llama-bench", "in_side")
    assert isinstance(driver, api.ReportsToolVersion)
    assert driver.doctor().status == "ok"
