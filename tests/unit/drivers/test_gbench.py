# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The gbench driver reads Google Benchmark's JSON output."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, ToolVersion
from pairbench.drivers.gbench import GbenchDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "gbench"


def _copy(name: str, folder: Path) -> None:
    shutil.copy(FIXTURES / name, folder / "gbench.json")


def _write(folder: Path, doc: Any) -> None:
    (folder / "gbench.json").write_text(json.dumps(doc), encoding="utf-8")


def _entry(**changes: Any) -> dict[str, Any]:
    entry = {
        "name": "BM_made_up",
        "run_name": "BM_made_up",
        "run_type": "iteration",
        "repetitions": 1,
        "repetition_index": 0,
        "threads": 1,
        "iterations": 10,
        "real_time": 2.0,
        "cpu_time": 1.0,
        "time_unit": "ms",
    }
    entry.update(changes)
    return entry


def test_the_repetitions_of_a_real_run_give_their_medians(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy("gbench.json", tmp_path)
    driver = GbenchDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.n_inner, s.reducer) for s in samples
    ] == [
        ("BM_vector_sum/64", "real_time", "s", "lower", "time", 3, "median"),
        ("BM_vector_sum/64/cpu_time", "cpu_time", "s", "lower", "time", 3, "median"),
        ("BM_vector_sum/4096", "real_time", "s", "lower", "time", 3, "median"),
        ("BM_vector_sum/4096/cpu_time", "cpu_time", "s", "lower", "time", 3, "median"),
        ("BM_string_build", "real_time", "s", "lower", "time", 3, "median"),
        ("BM_string_build/cpu_time", "cpu_time", "s", "lower", "time", 3, "median"),
    ]
    values = [s.value for s in samples]
    assert values == pytest.approx(
        [
            1.8408152072743203e-08,
            1.8408095015206153e-08,
            1.1299094184800869e-06,
            1.1298250564683307e-06,
            7.711306195477673e-07,
            7.71125529937202e-07,
        ],
        rel=1e-12,
    )
    assert driver.default_primary(samples) == [
        "BM_vector_sum/64",
        "BM_vector_sum/4096",
        "BM_string_build",
    ]
    assert notes.seen == [
        (
            "case_skipped",
            "side 'new': Google Benchmark reported an error or a skip for 'BM_needs_a_file'; "
            "the case is missing from this launch",
        )
    ]
    assert capsys.readouterr() == ("", "")


def test_one_repetition_is_taken_as_it_is(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _copy("gbench-one.json", tmp_path)
    samples = GbenchDriver().read(make_ctx(), tmp_path)
    assert samples[0].value == pytest.approx(1.7495510089350874e-08, rel=1e-12)
    assert [(s.case, s.n_inner, s.reducer) for s in samples] == [
        ("BM_vector_sum/64", 1, "identity"),
        ("BM_vector_sum/64/cpu_time", 1, "identity"),
        ("BM_vector_sum/4096", 1, "identity"),
        ("BM_vector_sum/4096/cpu_time", 1, "identity"),
    ]


@pytest.mark.parametrize(
    ("unit", "seconds"), [("ns", 2e-9), ("us", 2e-6), ("ms", 2e-3), ("s", 2.0)]
)
def test_every_time_unit_is_converted_to_seconds(
    make_ctx: MakeCtx, tmp_path: Path, unit: str, seconds: float
) -> None:
    _write(tmp_path, {"benchmarks": [_entry(time_unit=unit)]})
    assert GbenchDriver().read(make_ctx(), tmp_path)[0].value == pytest.approx(seconds)


def test_a_benchmark_with_one_skipped_repetition_is_left_out(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any
) -> None:
    _write(
        tmp_path,
        {
            "benchmarks": [
                _entry(),
                _entry(repetition_index=1, skipped=True, skip_message="made-up"),
                _entry(name="BM_other", run_name="BM_other"),
            ]
        },
    )
    assert [s.case for s in GbenchDriver().read(make_ctx(), tmp_path)] == [
        "BM_other",
        "BM_other/cpu_time",
    ]
    assert [code for code, _ in notes.seen] == ["case_skipped"]


def test_a_templated_benchmark_over_a_range_keeps_its_names_as_the_runner_records_them(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    names = ["BM_made_up<int>/8", "BM_made_up<int>/64"]
    _write(tmp_path, {"benchmarks": [_entry(name=n, run_name=n) for n in names]})
    samples = GbenchDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == [
        "BM_made_up<int>/8",
        "BM_made_up<int>/8/cpu_time",
        "BM_made_up<int>/64",
        "BM_made_up<int>/64/cpu_time",
    ]
    assert api.public_cases(samples, "side 'new'") == samples


def test_a_name_that_ends_in_a_file_address_keeps_its_file_once_the_runner_records_it(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    names = ["BM_Load/file:///made/up/home/a.gguf", "BM_Load/file://localhost/made/up/b.gguf"]
    _write(tmp_path, {"benchmarks": [_entry(name=n, run_name=n) for n in names]})
    driver = GbenchDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert isinstance(driver, api.CleansCaseIds)
    assert [s.case for s in api.shown_cases(driver, samples, "side 'new'")] == [
        "BM_Load/file://a.gguf",
        "BM_Load/file://a.gguf/cpu_time",
        "BM_Load/file://b.gguf",
        "BM_Load/file://b.gguf/cpu_time",
    ]


def test_a_name_that_ends_in_a_path_is_cut_before_its_cpu_time_part_is_added(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any
) -> None:
    names = ["BM_Load/path:/made/up/home/a.bin", "BM_Load/path:/made/up/home/b.bin"]
    skipped = "BM_Read//made/up/home/c.bin"
    _write(
        tmp_path,
        {
            "benchmarks": [
                *(_entry(name=n, run_name=n) for n in names),
                _entry(name=skipped, run_name=skipped, error_occurred=True),
            ]
        },
    )
    samples = GbenchDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == [
        "BM_Load/path:a.bin",
        "BM_Load/path:a.bin/cpu_time",
        "BM_Load/path:b.bin",
        "BM_Load/path:b.bin/cpu_time",
    ]
    assert api.public_cases(samples, "side 'new'") == samples
    assert notes.seen == [
        (
            "case_skipped",
            "side 'new': Google Benchmark reported an error or a skip for 'BM_Read/c.bin'; "
            "the case is missing from this launch",
        )
    ]


def test_two_benchmarks_that_differ_only_in_a_folder_are_refused(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    names = ["BM_Read//made/up/v1/data.bin", "BM_Read//made/up/v2/data.bin"]
    _write(tmp_path, {"benchmarks": [_entry(name=n, run_name=n) for n in names]})
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("gbench.json: two different cases")
    assert "'BM_Read/data.bin'" in caught.value.message
    assert caught.value.message.endswith(
        "; give each benchmark a name that differs outside its paths, absolute or climbing "
        "with '..', and outside its secrets"
    )
    assert "/made/up" not in caught.value.message


def test_prepare_adds_the_output_options(make_ctx: MakeCtx) -> None:
    invocation = GbenchDriver().prepare(make_ctx(), ["./bench", "--benchmark_filter=BM_x"])
    assert invocation.argv == (
        "./bench",
        "--benchmark_filter=BM_x",
        "--benchmark_out=/pairbench/artifacts/gbench.json",
        "--benchmark_out_format=json",
    )


def test_prepare_points_at_the_folder_as_a_host_side_sees_it(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(artifacts_in_side="/made/up/run/launch-3/")
    assert GbenchDriver().prepare(ctx, ["./bench"]).argv[1] == (
        "--benchmark_out=/made/up/run/launch-3/gbench.json"
    )


@pytest.mark.parametrize(
    ("arg", "option"),
    [
        ("--benchmark_out=mine.json", "--benchmark_out"),
        ("--benchmark_out_format=csv", "--benchmark_out_format"),
    ],
)
def test_a_command_with_the_output_option_is_refused(
    make_ctx: MakeCtx, arg: str, option: str
) -> None:
    with pytest.raises(Refusal) as caught:
        GbenchDriver().prepare(make_ctx(), ["./bench", arg])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        f"the gbench driver adds Google Benchmark's option {option} itself and reads the file "
        f"it names; remove {option} from the command"
    )


def test_an_empty_command_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        GbenchDriver().prepare(make_ctx(kind="image"), [])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ([], "gbench.json is not an object"),
        ({"context": {}}, "gbench.json has no benchmarks"),
        ({"benchmarks": {}}, "gbench.json: benchmarks is not a list"),
        (
            {"benchmarks": [_entry(run_type=None)]},
            "gbench.json: benchmarks[0]: run_type is not a text that is not empty",
        ),
        (
            {"benchmarks": [{k: v for k, v in _entry().items() if k != "run_type"}]},
            "gbench.json: benchmarks[0] has no run_type",
        ),
        (
            {"benchmarks": [_entry(time_unit="min")]},
            "gbench.json: benchmarks[0]: time_unit 'min' is not one of ns, us, ms, s",
        ),
        (
            {"benchmarks": [_entry(real_time="fast")]},
            "gbench.json: benchmarks[0]: real_time is not a number",
        ),
        (
            {"benchmarks": [_entry(run_type="aggregate", aggregate_name="mean")]},
            "gbench.json holds aggregate entries only; the gbench driver reads the repetitions: "
            "drop --benchmark_report_aggregates_only",
        ),
        ({"benchmarks": []}, "gbench.json: the Google Benchmark output holds no measured case"),
        (
            {"benchmarks": [_entry(error_occurred=True, error_message="x")]},
            "gbench.json: the Google Benchmark output holds no measured case",
        ),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, message: str
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_a_file_that_is_no_json_is_refused(make_ctx: MakeCtx, tmp_path: Path) -> None:
    (tmp_path / "gbench.json").write_text('{"benchmarks": [', encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert (
        caught.value.message == "gbench.json is not valid JSON (line 1, column 17): Expecting value"
    )


def test_two_repetitions_give_the_mean_of_the_two(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "benchmarks": [
                _entry(real_time=1.0, cpu_time=4.0),
                _entry(repetition_index=1, real_time=3.0, cpu_time=6.0),
            ]
        },
    )
    samples = GbenchDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.n_inner, s.reducer) for s in samples] == [
        ("BM_made_up", 2, "median"),
        ("BM_made_up/cpu_time", 2, "median"),
    ]
    assert [s.value for s in samples] == pytest.approx([0.002, 0.005], rel=1e-12)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[" * 100_000, "gbench.json is nested too deeply to read"),
        ('{"a": ' + "9" * 5000 + "}", "gbench.json holds a number with too many digits to read"),
        (
            '{"benchmarks": [{"name": "BM_made_up", "run_type": "iteration", "real_time": '
            + "9" * 400
            + ', "cpu_time": 1, "time_unit": "ns"}]}',
            "gbench.json: benchmarks[0]: real_time is not a finite number",
        ),
    ],
)
def test_a_file_that_json_cannot_hold_is_refused_not_raised(
    make_ctx: MakeCtx, tmp_path: Path, text: str, message: str
) -> None:
    (tmp_path / "gbench.json").write_text(text, encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_the_version_of_a_file_side_is_read_from_its_result_file(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    result = tmp_path / "round-1.json"
    result.write_text(
        json.dumps({"context": {"library_version": "v1.9.4"}, "benchmarks": [_entry()]}),
        encoding="utf-8",
    )
    ctx = make_ctx(kind="file", result_file=result)
    assert GbenchDriver().tool_version(ctx, tmp_path / "unused") == ToolVersion(
        "Google Benchmark", "v1.9.4", True
    )


def test_a_missing_file_is_refused(make_ctx: MakeCtx, tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(make_ctx(), tmp_path)
    assert caught.value.message == "the gbench driver found no output file gbench.json"


def test_version_1_8_names_no_version(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _copy("gbench.json", tmp_path)
    assert GbenchDriver().tool_version(make_ctx(), tmp_path) is None


@pytest.mark.parametrize(
    ("version", "tested"), [("v1.9.4", True), ("1.10.0", True), ("v2.0.0", False), ("main", False)]
)
def test_the_library_version_is_read_and_its_major_checked(
    make_ctx: MakeCtx, tmp_path: Path, version: str, tested: bool
) -> None:
    _write(tmp_path, {"context": {"library_version": version}, "benchmarks": [_entry()]})
    assert GbenchDriver().tool_version(make_ctx(), tmp_path) == ToolVersion(
        "Google Benchmark", version, tested
    )


def test_a_file_side_is_read_from_its_result_file(make_ctx: MakeCtx, tmp_path: Path) -> None:
    result = tmp_path / "round-2.json"
    shutil.copy(FIXTURES / "gbench-one.json", result)
    ctx = make_ctx(kind="file", result_file=result)
    assert len(GbenchDriver().read(ctx, tmp_path / "unused")) == 4


def test_the_registry_loads_the_gbench_driver() -> None:
    driver = registry.driver("gbench")
    assert isinstance(driver, GbenchDriver)
    assert (driver.name, driver.api_version, driver.where) == ("gbench", 1, "in_side")
    assert isinstance(driver, api.ReportsToolVersion)
    assert driver.doctor().status == "ok"
    assert api.clock_cases(driver) == ()
