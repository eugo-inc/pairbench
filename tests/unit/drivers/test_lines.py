# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The lines driver reads the ::pairbench:: lines a workload prints."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, Sample
from pairbench.drivers.lines import LinesDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "lines" / "stdout.txt"


def _write_stdout(folder: Path, text: str) -> None:
    (folder / "stdout.txt").write_text(text, encoding="utf-8")


def _refusal(make_ctx: MakeCtx, folder: Path, text: str) -> Refusal:
    _write_stdout(folder, text)
    with pytest.raises(Refusal) as caught:
        LinesDriver().read(make_ctx(), folder)
    return caught.value


def test_the_fixture_from_a_real_run_gives_its_four_cases(
    make_ctx: MakeCtx, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURE, tmp_path / "stdout.txt")
    driver = LinesDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert samples == [
        Sample("sort", "value", "s", "lower", "time", 0.0266009580809623),
        Sample("sum", "value", "ms", "lower", "time", 2.200826071202755),
        Sample("items_per_s", "value", "items/s", "higher", "other", 7518526.18959373),
        Sample("items", "value", "count", "none", "other", 200000.0),
    ]
    assert driver.default_primary(samples) == ["sort", "sum", "items_per_s", "items"]
    assert capsys.readouterr() == ("", "")


def test_unit_and_better_default_to_seconds_and_lower(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write_stdout(tmp_path, 'noise\n::pairbench:: {"case": "a", "value": 3}\nmore noise\n')
    assert LinesDriver().read(make_ctx(), tmp_path) == [
        Sample("a", "value", "s", "lower", "time", 3.0, 1, "identity")
    ]


def test_a_line_must_start_with_the_marker(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write_stdout(
        tmp_path,
        'log: ::pairbench:: {"case": "a", "value": 3}\n::pairbench:: {"case": "b", "value": 4}\n',
    )
    assert [s.case for s in LinesDriver().read(make_ctx(), tmp_path)] == ["b"]


def test_a_value_of_zero_or_less_is_kept(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write_stdout(tmp_path, '::pairbench:: {"case": "a", "value": -1.5}\n')
    assert LinesDriver().read(make_ctx(), tmp_path)[0].value == -1.5


def test_a_file_side_is_read_from_its_result_file(make_ctx: MakeCtx, tmp_path: Path) -> None:
    result = tmp_path / "round-1.txt"
    result.write_text('::pairbench:: {"case": "a", "value": 2, "unit": "ms"}\n', encoding="utf-8")
    ctx = make_ctx(kind="file", result_file=result)
    assert LinesDriver().read(ctx, tmp_path / "not-there") == [
        Sample("a", "value", "ms", "lower", "time", 2.0)
    ]


@pytest.mark.parametrize("argv", [[], ["python", "bench.py"]])
def test_prepare_returns_the_command_unchanged(make_ctx: MakeCtx, argv: list[str]) -> None:
    assert LinesDriver().prepare(make_ctx(), list(argv)).argv == tuple(argv)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("nothing to read\n", "stdout.txt holds no line that starts with ::pairbench::"),
        (
            "::pairbench:: {case: a}\n",
            "stdout.txt line 1: the JSON does not parse: "
            "Expecting property name enclosed in double quotes",
        ),
        ('::pairbench:: ["a", 1]\n', "stdout.txt line 1: the JSON is not an object"),
        (
            'x\n::pairbench:: {"case": "a", "value": 1, "beter": "higher"}\n',
            "stdout.txt line 2: unknown key 'beter'; a line holds case, value, unit, better",
        ),
        (
            '::pairbench:: {"case": "a", "value": 1, "better": "faster"}\n',
            "stdout.txt line 1: better of 'a' is 'faster'; it is one of lower, higher, none",
        ),
        ('::pairbench:: {"case": "a"}\n', "stdout.txt line 1: the case 'a' has no value"),
        (
            '::pairbench:: {"case": "a", "value": "1.5"}\n',
            "stdout.txt line 1: the value of 'a' is not a number",
        ),
        (
            '::pairbench:: {"case": "a", "value": true}\n',
            "stdout.txt line 1: the value of 'a' is not a number",
        ),
        (
            '::pairbench:: {"case": "", "value": 1}\n',
            "stdout.txt line 1: case is not a text that is not empty",
        ),
        (
            '::pairbench:: {"case": "a", "value": 1, "unit": ""}\n',
            "stdout.txt line 1: the unit of 'a' is not a text that is not empty",
        ),
        (
            '::pairbench:: {"case": "a", "value": 1}\n::pairbench:: {"case": "a", "value": 2}\n',
            "stdout.txt: the case 'a' is given twice",
        ),
        (
            '::pairbench:: {"case": "a", "value": NaN}\n',
            "case 'a': the value nan is not a finite number",
        ),
    ],
)
def test_a_malformed_output_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, text: str, message: str
) -> None:
    refusal = _refusal(make_ctx, tmp_path, text)
    assert (refusal.code, refusal.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert refusal.message == message


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("[" * 100_000, "stdout.txt line 1: the JSON is nested too deeply to read"),
        (
            '{"case": "a", "value": ' + "9" * 5000 + "}",
            "stdout.txt line 1: the JSON holds a number with too many digits to read",
        ),
    ],
)
def test_a_line_that_json_cannot_hold_is_refused_not_raised(
    make_ctx: MakeCtx, tmp_path: Path, payload: str, message: str
) -> None:
    refusal = _refusal(make_ctx, tmp_path, f"::pairbench:: {payload}\n")
    assert (refusal.code, refusal.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert refusal.message == message


def test_bytes_that_are_no_utf_8_on_other_lines_are_ignored(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    (tmp_path / "stdout.txt").write_bytes(
        b'noise \xff\xfe\x80\n::pairbench:: {"case": "a", "value": 1}\n'
    )
    assert LinesDriver().read(make_ctx(), tmp_path) == [
        Sample("a", "value", "s", "lower", "time", 1.0)
    ]


def test_a_byte_order_mark_does_not_hide_the_first_line(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write_stdout(
        tmp_path,
        '\ufeff::pairbench:: {"case": "a", "value": 1}\n::pairbench:: {"case": "b", "value": 2}\n',
    )
    assert [s.case for s in LinesDriver().read(make_ctx(), tmp_path)] == ["a", "b"]


def test_a_launch_without_standard_output_is_refused(make_ctx: MakeCtx, tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        LinesDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == "the lines driver found no output file stdout.txt"


def test_the_registry_loads_the_lines_driver() -> None:
    driver = registry.driver("lines")
    assert isinstance(driver, LinesDriver)
    assert (driver.name, driver.api_version, driver.where) == ("lines", 1, "in_side")
    assert api.clock_cases(driver) == ()
