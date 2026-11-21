# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The hyperfine driver reads both layouts of hyperfine's JSON export."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, ToolVersion
from pairbench.drivers.hyperfine import HyperfineDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "hyperfine"
OUTPUT = "hyperfine.json"


def _copy(name: str, folder: Path) -> None:
    shutil.copy(FIXTURES / name, folder / OUTPUT)


def _write(folder: Path, doc: Any) -> None:
    (folder / OUTPUT).write_text(json.dumps(doc), encoding="utf-8")


def _measurement(value: float, unit: str = "second", code: int | None = 0) -> dict[str, Any]:
    return {"time_wall_clock": {"value": value, "unit": unit}, "exit_code": code}


def test_the_older_layout_of_release_1_21_gives_the_median_run_time(
    make_ctx: MakeCtx, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy("hyperfine-v1.json", tmp_path)
    driver = HyperfineDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.n_inner, s.reducer) for s in samples
    ] == [
        ("short sleep", "time", "s", "lower", "time", 5, "median"),
        ("sleep 0.02", "time", "s", "lower", "time", 5, "median"),
    ]
    assert [s.value for s in samples] == pytest.approx(
        [0.011017003000000001, 0.021211955], rel=1e-12
    )
    assert driver.default_primary(samples) == ["short sleep", "sleep 0.02"]
    assert driver.tool_version(make_ctx(), tmp_path) is None
    assert capsys.readouterr() == ("", "")


def test_the_newer_layout_of_release_2_0_gives_the_median_run_time(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _copy("hyperfine-v2.json", tmp_path)
    driver = HyperfineDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [(s.case, s.n_inner, s.reducer) for s in samples] == [
        ("short sleep", 5, "median"),
        ("sleep 0.02", 5, "median"),
    ]
    assert [s.value for s in samples] == pytest.approx(
        [0.01118038, 0.021071153000000002], rel=1e-12
    )
    assert driver.tool_version(make_ctx(), tmp_path) == ToolVersion("hyperfine", "2.0.0", True)


def test_an_untested_major_version_is_reported_untested(make_ctx: MakeCtx, tmp_path: Path) -> None:
    doc = {
        "schema_version": 2,
        "metadata": {"hyperfine_version": "3.0.0"},
        "results": [{"command": "true", "measurements": [_measurement(0.5)]}],
    }
    _write(tmp_path, doc)
    assert HyperfineDriver().tool_version(make_ctx(), tmp_path) == ToolVersion(
        "hyperfine", "3.0.0", False
    )


def test_a_major_version_with_too_many_digits_is_reported_untested(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    version = "9" * 5000 + ".0.0"
    doc = {
        "schema_version": 2,
        "metadata": {"hyperfine_version": version},
        "results": [{"command": "true", "measurements": [_measurement(0.5)]}],
    }
    _write(tmp_path, doc)
    assert HyperfineDriver().tool_version(make_ctx(), tmp_path) == ToolVersion(
        "hyperfine", version, False
    )


def test_one_run_is_taken_as_it_is(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(tmp_path, {"results": [{"command": "true", "times": [0.25]}]})
    sample = HyperfineDriver().read(make_ctx(), tmp_path)[0]
    assert (sample.case, sample.value, sample.n_inner, sample.reducer) == (
        "true",
        0.25,
        1,
        "identity",
    )


PRIVATE_COMMAND = "/made/up/home/bin/tool --api-key=made-up-1 --token made-up-2 /made/up/in.txt"
PUBLIC_CASE = "tool --api-key=<hidden> --token <hidden> in.txt"


@pytest.mark.parametrize(
    "doc",
    [
        {"results": [{"command": PRIVATE_COMMAND, "times": [0.25]}]},
        {
            "schema_version": 2,
            "results": [{"command": PRIVATE_COMMAND, "measurements": [_measurement(0.25)]}],
        },
    ],
)
def test_a_case_named_after_its_command_shows_no_path_and_no_credential(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any
) -> None:
    _write(tmp_path, doc)
    (sample,) = HyperfineDriver().read(make_ctx(), tmp_path)
    assert sample.case == PUBLIC_CASE


def test_a_case_named_after_its_command_hides_the_host_of_an_address(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    command = "curl -s https://made-up.example:8443/v1/models http://localhost:8000/v1"
    _write(tmp_path, {"results": [{"command": command, "times": [0.25]}]})
    (sample,) = HyperfineDriver().read(make_ctx(), tmp_path)
    assert sample.case == "curl -s https://<hidden>:8443/v1/models http://localhost:8000/v1"


# (a command hyperfine names its case after, the case id): a word that starts with ``~`` and a
# name is kept as typed, as any case id keeps it, while a path into such a home is cut and a
# credential beside it is hidden.
TILDE_COMMANDS: dict[str, tuple[str, str]] = {
    "a tilde word": ("echo ~alpha", "echo ~alpha"),
    "a bitwise not in code": ("python3 -c 'print(~a)'", "python3 -c print(~a)"),
    "a tilde word after an assignment": ("python3 -c 'x=~a'", "python3 -c x=~a"),
    "a tilde word as the last path of a list": ("tool /usr/bin:~zq", "tool bin:~zq"),
    "a tilde word beside a credential": (
        "bench --token made-up-4 ~alpha",
        "bench --token <hidden> ~alpha",
    ),
    "a path into a tilde home": ("cat ~zq/data/x.csv", "cat x.csv"),
}

# (a command hyperfine names its case after, the case id): a path that ends at the folder right
# under /home or /Users is cut to that folder's name, as any case id cuts it, since a route such
# as /users/1 reads the same, while a credential beside it is hidden.
HOME_PATH_COMMANDS: dict[str, tuple[str, str]] = {
    "a route given as a word": ("python3 app.py --route /users/1", "python3 app.py --route 1"),
    "a route glued with =": ("python3 app.py --route=/users/1", "python3 app.py --route=1"),
    "a key of a data store": ("redis-cli GET /users/1", "redis-cli GET 1"),
    "a page under /home": ("python3 app.py /home/feed", "python3 app.py feed"),
    "a climbing route": ("python3 app.py ../users/1", "python3 app.py 1"),
    "a route beside a credential": (
        "bench --token made-up-4 /users/1",
        "bench --token <hidden> 1",
    ),
    "a path into a home folder": ("cat /home/zq/data/x.csv", "cat x.csv"),
}


@pytest.mark.parametrize("name", list(HOME_PATH_COMMANDS))
def test_a_case_named_after_its_command_cuts_a_home_folder_path_to_its_name(
    make_ctx: MakeCtx, tmp_path: Path, name: str
) -> None:
    command, case = HOME_PATH_COMMANDS[name]
    _write(tmp_path, {"results": [{"command": command, "times": [0.25]}]})
    (sample,) = HyperfineDriver().read(make_ctx(), tmp_path)
    assert sample.case == case


def test_two_commands_that_differ_only_in_a_route_are_two_cases(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    results = [
        {"command": "python3 app.py --route /users/1", "times": [0.25]},
        {"command": "python3 app.py --route /users/2", "times": [0.5]},
    ]
    _write(tmp_path, {"results": results})
    samples = HyperfineDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == ["python3 app.py --route 1", "python3 app.py --route 2"]


@pytest.mark.parametrize("name", list(TILDE_COMMANDS))
def test_a_case_named_after_its_command_keeps_a_tilde_word(
    make_ctx: MakeCtx, tmp_path: Path, name: str
) -> None:
    command, case = TILDE_COMMANDS[name]
    _write(tmp_path, {"results": [{"command": command, "times": [0.25]}]})
    (sample,) = HyperfineDriver().read(make_ctx(), tmp_path)
    assert sample.case == case


def test_two_commands_that_differ_only_in_a_tilde_word_are_two_cases(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    results = [
        {"command": "python3 -c 'print(~a)'", "times": [0.25]},
        {"command": "python3 -c 'print(~b)'", "times": [0.5]},
    ]
    _write(tmp_path, {"results": results})
    samples = HyperfineDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == ["python3 -c print(~a)", "python3 -c print(~b)"]


def test_a_name_given_to_a_command_is_kept_as_given(make_ctx: MakeCtx, tmp_path: Path) -> None:
    entry = {"command": PRIVATE_COMMAND, "name": "made-up name", "measurements": []}
    entry["measurements"] = [_measurement(0.25)]
    _write(tmp_path, {"schema_version": 2, "results": [entry]})
    (sample,) = HyperfineDriver().read(make_ctx(), tmp_path)
    assert sample.case == "made-up name"


def test_a_refusal_names_the_command_without_its_path_or_credential(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(tmp_path, {"results": [{"command": PRIVATE_COMMAND, "times": []}]})
    with pytest.raises(Refusal) as caught:
        HyperfineDriver().read(make_ctx(), tmp_path)
    assert PUBLIC_CASE in caught.value.message
    assert "made-up-1" not in caught.value.message
    assert "/made/up" not in caught.value.message


SECRET_NAME = "bench --token made-up-3 /made/up/data/x"
SHOWN_NAME = "bench --token <hidden> x"
NO_RUN_TIME = "the command {name!r} has no run time"
NON_ZERO = (
    "a run of {name!r} exited with a code other than zero; "
    "the hyperfine driver reads the times of runs that succeeded"
)
NO_EXIT_CODE = (
    "a run of {name!r} ended without an exit code, as a run stopped by a signal does; "
    "the hyperfine driver reads the times of runs that succeeded"
)


@pytest.mark.parametrize(
    ("measurements", "text"),
    [
        ([], NO_RUN_TIME),
        ([_measurement(0.25, code=1)], NON_ZERO),
        ([_measurement(0.25, code=None)], NO_EXIT_CODE),
    ],
)
@pytest.mark.parametrize(("name", "shown"), [(SECRET_NAME, SHOWN_NAME), ("made-up name", None)])
def test_a_refusal_names_a_given_name_as_the_reports_show_it(
    make_ctx: MakeCtx,
    tmp_path: Path,
    measurements: list[dict[str, Any]],
    text: str,
    name: str,
    shown: str | None,
) -> None:
    entry = {"command": "true", "name": name, "measurements": measurements}
    _write(tmp_path, {"schema_version": 2, "results": [entry]})
    with pytest.raises(Refusal) as caught:
        HyperfineDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    expected = text.format(name=name if shown is None else shown)
    assert caught.value.message == f"{OUTPUT}: results[0]: {expected}"


TWO_FOLDERS = (
    {"command": "/made/up/v1/bench --n 1", "times": [0.1, 0.1]},
    {"command": "/made/up/v2/bench --n 1", "times": [0.5, 0.5]},
)


@pytest.mark.parametrize(
    "doc",
    [
        {"results": list(TWO_FOLDERS)},
        {
            "schema_version": 2,
            "results": [
                {"command": e["command"], "measurements": [_measurement(0.25)]} for e in TWO_FOLDERS
            ],
        },
    ],
)
def test_two_commands_that_differ_only_in_a_folder_are_refused_with_the_way_to_name_them(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        HyperfineDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "'bench --n 1'" in caught.value.message
    assert "--command-name" in caught.value.message
    assert "given twice" not in caught.value.message
    assert "/made/up" not in caught.value.message


def test_two_commands_with_names_of_their_own_are_read_apart(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    results = [
        {"command": e["command"], "name": f"made-up {i}", "measurements": [_measurement(0.25)]}
        for i, e in enumerate(TWO_FOLDERS)
    ]
    _write(tmp_path, {"schema_version": 2, "results": results})
    samples = HyperfineDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == ["made-up 0", "made-up 1"]


def test_one_command_given_twice_is_still_a_case_given_twice(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(tmp_path, {"results": [TWO_FOLDERS[0], TWO_FOLDERS[0]]})
    with pytest.raises(Refusal, match="given twice") as caught:
        HyperfineDriver().read(make_ctx(), tmp_path)
    assert caught.value.code == "E_LAUNCH_FAILED"


def test_prepare_adds_the_export_option(make_ctx: MakeCtx) -> None:
    argv = HyperfineDriver().prepare(make_ctx(), ["hyperfine", "-N", "sleep 0.1"]).argv
    assert argv == (
        "hyperfine",
        "-N",
        "sleep 0.1",
        "--export-json",
        "/pairbench/artifacts/hyperfine.json",
    )


@pytest.mark.parametrize("arg", ["--export-json", "--export-json=mine.json"])
def test_a_command_with_the_export_option_is_refused(make_ctx: MakeCtx, arg: str) -> None:
    with pytest.raises(Refusal) as caught:
        HyperfineDriver().prepare(make_ctx(), ["hyperfine", arg, "mine.json", "true"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({}, "hyperfine.json has no results"),
        (
            {"schema_version": 3, "results": []},
            "hyperfine.json: schema_version 3 is not one the hyperfine driver reads (none, or 2)",
        ),
        ({"results": [{"command": "true"}]}, "hyperfine.json: results[0] has no times"),
        (
            {"results": [{"command": "true", "times": []}]},
            "hyperfine.json: results[0]: the command 'true' has no run time",
        ),
        (
            {"results": [{"command": "true", "times": [0.1, 0.2], "exit_codes": [0, 1]}]},
            "hyperfine.json: results[0]: a run of 'true' exited with a code other than zero; "
            "the hyperfine driver reads the times of runs that succeeded",
        ),
        (
            {
                "schema_version": 2,
                "results": [{"command": "true", "measurements": [_measurement(0.1, code=2)]}],
            },
            "hyperfine.json: results[0]: a run of 'true' exited with a code other than zero; "
            "the hyperfine driver reads the times of runs that succeeded",
        ),
        (
            {
                "schema_version": 2,
                "results": [{"command": "true", "measurements": [_measurement(0.1, "ms")]}],
            },
            "hyperfine.json: results[0]: measurements[0]: "
            "time_wall_clock has the unit 'ms', not 'second'",
        ),
        (
            {"schema_version": 2, "results": [{"command": "true", "measurements": [{}]}]},
            "hyperfine.json: results[0]: measurements[0] has no time_wall_clock",
        ),
        (
            {"results": [{"command": "a", "times": [1.0]}, {"command": "a", "times": [2.0]}]},
            "hyperfine.json: the case 'a' is given twice",
        ),
        (
            {"results": [{"command": "true", "times": [0.1, 0.2], "exit_codes": [None, 0]}]},
            "hyperfine.json: results[0]: a run of 'true' ended without an exit code, as a run "
            "stopped by a signal does; the hyperfine driver reads the times of runs that "
            "succeeded",
        ),
        (
            {
                "schema_version": 2,
                "results": [
                    {
                        "command": "true",
                        "measurements": [_measurement(0.1), _measurement(0.2, code=None)],
                    }
                ],
            },
            "hyperfine.json: results[0]: a run of 'true' ended without an exit code, as a run "
            "stopped by a signal does; the hyperfine driver reads the times of runs that "
            "succeeded",
        ),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, message: str
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        HyperfineDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_the_registry_loads_the_hyperfine_driver() -> None:
    driver = registry.driver("hyperfine")
    assert isinstance(driver, HyperfineDriver)
    assert (driver.name, driver.where) == ("hyperfine", "in_side")
    assert isinstance(driver, api.ReportsToolVersion)
    assert driver.doctor().status == "ok"
