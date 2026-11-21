# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The GPU profilers, with a made-up program finder; no profiler is run."""

from __future__ import annotations

import shutil

import pytest

from pairbench import api
from pairbench.api import ProfiledCommand, Profiler
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.profile import nsight
from pairbench.profile.nsight import NsightCompute, NsightSystems, profiler, require

COMMAND = ("./bench", "--size", "8")


def _found(name: str) -> str | None:
    return f"/opt/made-up/bin/{name}"


def _missing(name: str) -> str | None:
    return None


@pytest.fixture(autouse=True)
def _no_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(name: str) -> str | None:
        raise AssertionError(f"a test looked for the real {name!r}")

    monkeypatch.setattr(shutil, "which", refuse)


def test_nsys_and_ncu_are_the_gpu_profilers() -> None:
    systems: Profiler = profiler("nsys")
    compute: Profiler = profiler("ncu")
    assert isinstance(systems, NsightSystems)
    assert isinstance(compute, NsightCompute)
    assert systems.name == "nsys"
    assert compute.name == "ncu"
    assert api.DELEGATES["profiler"] == ("pairbench.profile.nsight", "profiler", api.MakeProfiler)


@pytest.mark.parametrize("tool", ["perf", "nvprof", "", "NSYS"])
def test_another_name_is_a_usage_error(tool: str) -> None:
    with pytest.raises(Refusal) as caught:
        profiler(tool)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE
    assert caught.value.message == (
        f"not a GPU profiler: {tool!r}; the GPU profilers are nsys and ncu"
    )


def test_nsys_wraps_a_command_and_writes_one_report_into_the_folder() -> None:
    wrapped = NsightSystems().wrap(COMMAND, "/pairbench/artifacts")
    assert wrapped == ProfiledCommand(
        argv=(
            "nsys",
            "profile",
            "-o",
            "/pairbench/artifacts/report",
            "-f",
            "true",
            "./bench",
            "--size",
            "8",
        ),
        outputs=("/pairbench/artifacts/report.nsys-rep",),
    )


def test_ncu_wraps_a_command_and_writes_one_report_into_the_folder() -> None:
    wrapped = NsightCompute().wrap(COMMAND, "profiles/new/")
    assert wrapped == ProfiledCommand(
        argv=("ncu", "-o", "profiles/new/report", "-f", "./bench", "--size", "8"),
        outputs=("profiles/new/report.ncu-rep",),
    )


def test_the_command_names_the_program_and_not_its_path_on_the_host() -> None:
    systems = NsightSystems(which=_found)
    assert systems.find() == "/opt/made-up/bin/nsys"
    assert systems.wrap(COMMAND, "out").argv[0] == "nsys"


def test_the_command_of_the_side_is_kept_as_it_is() -> None:
    command = ("python3", "-c", "print('a b')", "--flag=x y")
    wrapped = NsightCompute().wrap(command, "out")
    assert wrapped.argv[-4:] == command


def test_a_side_without_a_command_cannot_be_profiled() -> None:
    with pytest.raises(Refusal) as caught:
        NsightSystems().wrap((), "out")
    assert caught.value.code == "E_ENGINE_UNSUPPORTED"
    assert caught.value.exit_code == EXIT_SIDE
    assert "nsys" in caught.value.message


def test_a_report_without_a_folder_lies_where_the_launch_runs() -> None:
    assert NsightSystems().wrap(COMMAND, "").outputs == ("report.nsys-rep",)
    assert NsightCompute().wrap(COMMAND, "/").outputs == ("/report.ncu-rep",)


def test_an_installed_profiler_is_found_and_required() -> None:
    assert NsightCompute(which=_found).find() == "/opt/made-up/bin/ncu"
    assert NsightCompute(which=_found).require() == "/opt/made-up/bin/ncu"
    assert require(NsightSystems(which=_found)) == "/opt/made-up/bin/nsys"


@pytest.mark.parametrize(("make", "name"), [(NsightSystems, "nsys"), (NsightCompute, "ncu")])
def test_a_missing_profiler_is_refused_by_name(
    make: type[nsight.NsightProfiler], name: str
) -> None:
    missing = make(which=_missing)
    assert missing.find() is None
    with pytest.raises(Refusal) as caught:
        missing.require()
    assert caught.value.code == "E_PROFILER_MISSING"
    assert caught.value.exit_code == EXIT_SIDE
    assert caught.value.message == (
        f"the profiler {name} is not installed: pairbench does not include or download it; "
        f"install it yourself and put {name} on PATH"
    )


def test_the_licence_note_says_the_users_own_licence_governs_it() -> None:
    assert NsightSystems().licence_note == (
        "nsys: pairbench does not include, download or redistribute NVIDIA Nsight Systems; "
        "it runs the copy you installed. Your use of it, and what you may publish from its "
        "output, is governed by the licence you accepted with it."
    )
    assert NsightCompute().licence_note.startswith(
        "ncu: pairbench does not include, download or redistribute NVIDIA Nsight Compute;"
    )


def test_making_a_profiler_looks_for_nothing() -> None:
    profiler("nsys")
    profiler("ncu")


def test_the_real_finder_is_used_when_none_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    looked: list[str] = []

    def which(name: str) -> str | None:
        looked.append(name)
        return None

    monkeypatch.setattr(shutil, "which", which)
    assert profiler("ncu").find() is None
    assert looked == ["ncu"]
