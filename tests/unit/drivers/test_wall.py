# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The wall driver reads the launch's own run time."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, Sample
from pairbench.drivers.wall import WallDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]


def test_a_command_side_gives_the_case_wall_and_no_launch_case(
    make_ctx: MakeCtx, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = make_ctx(kind="cmd", timing={"run_s": 1.5, "launch_s": 1.5, "user_s": 0.25})
    assert WallDriver().read(ctx, tmp_path) == [
        Sample(case="wall", metric="wall", unit="s", better="lower", kind="time", value=1.5)
    ]
    assert capsys.readouterr() == ("", "")


def test_an_image_side_also_gives_the_secondary_case_launch(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    ctx = make_ctx(kind="image", timing={"run_s": 2.0, "launch_s": 2.75})
    driver = WallDriver()
    samples = driver.read(ctx, tmp_path)
    assert samples == [
        Sample(case="wall", metric="wall", unit="s", better="lower", kind="time", value=2.0),
        Sample(case="launch", metric="launch", unit="s", better="lower", kind="time", value=2.75),
    ]
    assert driver.default_primary(samples) == ["wall"]


@pytest.mark.parametrize("kind", ["python", "venv", "conda"])
def test_python_environment_sides_give_wall_only(
    make_ctx: MakeCtx, tmp_path: Path, kind: str
) -> None:
    ctx = make_ctx(kind=kind, timing={"run_s": 0.5, "launch_s": 0.5})
    assert [s.case for s in WallDriver().read(ctx, tmp_path)] == ["wall"]


def test_no_user_or_sys_case_comes_from_the_wall_driver(make_ctx: MakeCtx, tmp_path: Path) -> None:
    ctx = make_ctx(kind="cmd", timing={"run_s": 1.0, "user_s": 0.5, "sys_s": 0.25})
    cases = [s.case for s in WallDriver().read(ctx, tmp_path)]
    assert cases == ["wall"]


def test_a_launch_without_run_s_cannot_be_read(make_ctx: MakeCtx, tmp_path: Path) -> None:
    ctx = make_ctx(kind="cmd", timing={"launch_s": 1.0})
    with pytest.raises(Refusal) as caught:
        WallDriver().read(ctx, tmp_path)
    assert caught.value.code == "E_LAUNCH_FAILED"
    assert caught.value.exit_code == 5
    assert (
        caught.value.message
        == "side 'new': the launch reported no run_s, which the case wall needs"
    )


def test_an_image_launch_without_launch_s_cannot_be_read(make_ctx: MakeCtx, tmp_path: Path) -> None:
    ctx = make_ctx(kind="image", timing={"run_s": 1.0})
    with pytest.raises(Refusal) as caught:
        WallDriver().read(ctx, tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert "no launch_s, which the case launch needs" in caught.value.message


def test_a_run_time_that_is_no_finite_number_is_refused(make_ctx: MakeCtx, tmp_path: Path) -> None:
    ctx = make_ctx(kind="cmd", timing={"run_s": float("nan")})
    with pytest.raises(Refusal) as caught:
        WallDriver().read(ctx, tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)


def test_a_file_side_has_no_launch_clock_to_read(make_ctx: MakeCtx, tmp_path: Path) -> None:
    result = tmp_path / "result-1.json"
    result.write_text("{}", encoding="utf-8")
    ctx = make_ctx(kind="file", result_file=result)
    with pytest.raises(Refusal) as caught:
        WallDriver().read(ctx, tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "result-1.json" in caught.value.message
    assert str(tmp_path) not in caught.value.message


@pytest.mark.parametrize("argv", [[], ["./bench", "--fast"]])
def test_prepare_returns_the_command_unchanged(make_ctx: MakeCtx, argv: list[str]) -> None:
    invocation = WallDriver().prepare(make_ctx(), list(argv))
    assert invocation.argv == tuple(argv)
    assert dict(invocation.env) == {}


def test_the_clock_cases_are_wall_and_launch() -> None:
    assert api.clock_cases(WallDriver()) == ("wall", "launch")
    assert isinstance(WallDriver(), api.ReadsLaunchClock)


def test_the_registry_loads_the_wall_driver() -> None:
    driver = registry.driver("wall")
    assert isinstance(driver, WallDriver)
    assert (driver.name, driver.api_version, driver.where) == ("wall", 1, "in_side")
    assert not isinstance(driver, api.Diagnosable)
