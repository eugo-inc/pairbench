# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The perf driver reads the machine-readable output of perf stat."""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import DriverContext, Sample
from pairbench.drivers.perf import PerfDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "perf"
OUTPUT = "perf-stat.txt"
PMU_0 = "armv8_pmuv3_0"
GENERATOR = Path(__file__).resolve().parents[2] / "fixtures" / "_gen" / "drivers.py"
# What the fixture writer says it replaced and kept, for one run and for repeats.
KEPT_ONE_RUN = (
    "the start line replaced by a made-up date; every other line kept as perf printed it in "
    "the run: the counter values, how long each counter ran and for what share of the run, the "
    "figures perf derives from them (such as instructions per cycle, GHz and CPUs utilized) and "
    "the PMU names (the Linux driver's generic names), since the per-PMU lines are what the "
    "driver reads"
)
KEPT_REPEATS = (
    "the start line replaced by a made-up date; every other line kept as perf printed it in "
    "the run: the counter values and their spread over the repeats, how long each counter ran "
    "and for what share of the run, the figures perf derives from them (such as instructions "
    "per cycle, GHz and CPUs utilized) and the PMU names (the Linux driver's generic names), "
    "since the per-PMU lines are what the driver reads"
)


def _write(folder: Path, text: str) -> None:
    (folder / OUTPUT).write_text(text, encoding="utf-8")


def test_a_real_run_gives_one_case_per_counted_event_and_ipc(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURES / "perf-stat.txt", tmp_path / OUTPUT)
    driver = PerfDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert [(s.case, s.metric, s.unit, s.better, s.kind, s.reducer) for s in samples] == [
        (
            "armv8_pmuv3_1/instructions/",
            "armv8_pmuv3_1/instructions/",
            "count",
            "lower",
            "count",
            "identity",
        ),
        ("armv8_pmuv3_1/cycles/", "armv8_pmuv3_1/cycles/", "count", "lower", "count", "identity"),
        ("task-clock", "task-clock", "s", "lower", "time", "identity"),
        ("context-switches", "context-switches", "count", "lower", "count", "identity"),
        (
            "armv8_pmuv3_1/cache-misses/",
            "armv8_pmuv3_1/cache-misses/",
            "count",
            "lower",
            "count",
            "identity",
        ),
        ("ipc", "ipc", "insn/cycle", "higher", "other", "identity"),
    ]
    assert [s.value for s in samples] == pytest.approx(
        [2833988899.0, 542063333.0, 0.14943, 10.0, 17344.0, 5.228150893947294], rel=1e-12
    )
    assert driver.default_primary(samples) == []
    assert notes.seen == [
        (
            "event_not_counted",
            f"side 'new': perf reported the event '{PMU_0}/{event}/' as not counted; "
            "the case is missing from this launch",
        )
        for event in ("instructions", "cycles", "cache-misses")
    ]
    assert capsys.readouterr() == ("", "")


def test_repeats_give_the_tools_own_mean(make_ctx: MakeCtx, tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "perf-stat-repeat.txt", tmp_path / OUTPUT)
    samples = PerfDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.reducer, s.n_inner) for s in samples] == [
        ("armv8_pmuv3_1/instructions/", "tool_summary", 1),
        ("armv8_pmuv3_1/cycles/", "tool_summary", 1),
        ("task-clock", "tool_summary", 1),
        ("ipc", "identity", 1),
    ]
    assert samples[2].value == pytest.approx(0.07345)


def test_ipc_sums_over_the_units_that_counted_both(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "300;;cpu_core/instructions/;1;100.00;;\n"
        "100;;cpu_core/cycles/;1;100.00;;\n"
        "100;;cpu_atom/instructions/;1;100.00;;\n"
        "100;;cpu_atom/cycles/;1;100.00;;\n"
        "50;;cpu_other/instructions/;1;100.00;;\n",
    )
    samples = PerfDriver().read(make_ctx(), tmp_path)
    assert samples[-1] == Sample("ipc", "ipc", "insn/cycle", "higher", "other", 2.0)


def test_ipc_of_events_without_a_unit_and_with_modifiers(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _write(tmp_path, "600;;instructions:u;1;100.00;;\n200;;cycles:u;1;100.00;;\n")
    assert PerfDriver().read(make_ctx(), tmp_path)[-1].value == 3.0


def test_no_ipc_without_cycles(make_ctx: MakeCtx, tmp_path: Path, notes: Any) -> None:
    _write(tmp_path, "600;;instructions;1;100.00;;\n<not supported>;;cycles;0;0.00;;\n")
    samples = PerfDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == ["instructions"]
    assert notes.seen[0][1].endswith(
        "perf reported the event 'cycles' as not supported; the case is missing from this launch"
    )


def test_other_units_are_kept_and_metric_lines_are_skipped(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "# started on Sat Jan  1 00:00:00 2000\n\n"
        "12.5;Joules;power/energy-pkg/;1;100.00;;\n"
        ";;;;;1.50;made-up metric\n"
        "2000;ns;duration_time;1;100.00;;\n",
    )
    samples = PerfDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.unit, s.kind) for s in samples] == [
        ("power/energy-pkg/", "Joules", "other"),
        ("duration_time", "s", "time"),
    ]
    assert samples[1].value == pytest.approx(2e-6)


@pytest.mark.parametrize(
    ("unit", "seconds"),
    [
        ("msec", 2e-3),
        ("ms", 2e-3),
        ("usec", 2e-6),
        ("us", 2e-6),
        ("nsec", 2e-9),
        ("ns", 2e-9),
        ("sec", 2.0),
        ("s", 2.0),
    ],
)
def test_every_unit_of_time_is_converted_to_seconds(
    make_ctx: MakeCtx, tmp_path: Path, unit: str, seconds: float
) -> None:
    _write(tmp_path, f"2;{unit};made-up-clock;1;100.00;;\n")
    sample = PerfDriver().read(make_ctx(), tmp_path)[0]
    assert (sample.case, sample.unit, sample.kind) == ("made-up-clock", "s", "time")
    assert sample.value == pytest.approx(seconds, rel=1e-12)


def test_no_ipc_when_the_events_carry_more_than_one_set_of_modifiers(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "12;;instructions:u;1;100.00;;\n6;;cycles:u;1;100.00;;\n"
        "12;;instructions:k;1;100.00;;\n4;;cycles:k;1;100.00;;\n",
    )
    assert [s.case for s in PerfDriver().read(make_ctx(), tmp_path)] == [
        "instructions:u",
        "cycles:u",
        "instructions:k",
        "cycles:k",
    ]


@pytest.mark.parametrize(
    ("line", "field", "found"),
    [
        ("1.000973389;149.43;msec;task-clock;149431824;100.00;;\n", "unit", "149.43"),
        ("1.000973389;12;;instructions;149431824;100.00;;\n", "unit", "12"),
        ("CPU0;12;;instructions;149431824;100.00;;\n", "unit", "12"),
        ("1.000973389;CPU0;149.43;msec;task-clock;149431824;100.00;;\n", "event", "149.43"),
        ("1.000973389;S0;4;12;;instructions;149431824;100.00;;\n", "event", "4"),
        ("1.000973389;made-up-123;12;;instructions;149431824;100.00;;\n", "event", "12"),
    ],
)
def test_interval_and_split_output_is_refused_not_read_as_events(
    make_ctx: MakeCtx, tmp_path: Path, line: str, field: str, found: str
) -> None:
    # A file side hands the driver output that prepare never saw: perf stat -I
    # writes the time of the interval first and -A, --per-... a CPU, socket or
    # thread, which moves every field one or two places on.
    _write(tmp_path, line)
    with pytest.raises(Refusal) as caught:
        PerfDriver().read(make_ctx(kind="file", result_file=tmp_path / OUTPUT), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == (
        f"perf-stat.txt line 1: the {field} field '{found}' is a number, so the line is no "
        "event over the whole launch (perf stat -I, -A and --per-... write lines like this); "
        "the perf driver reads one line per event over the whole launch"
    )


def test_prepare_puts_the_output_options_after_stat(make_ctx: MakeCtx) -> None:
    argv = ["perf", "stat", "-e", "cycles", "--", "./work", "-o", "x"]
    assert PerfDriver().prepare(make_ctx(), argv).argv == (
        "perf",
        "stat",
        "-x",
        ";",
        "-o",
        "/pairbench/artifacts/perf-stat.txt",
        "-e",
        "cycles",
        "--",
        "./work",
        "-o",
        "x",
    )


@pytest.mark.parametrize(
    ("option", "refused"),
    [
        ("-x,", "-x"),
        ("-x", "-x"),
        ("--field-separator=,", "--field-separator"),
        ("-o", "-o"),
        ("-omine.txt", "-o"),
        ("--output", "--output"),
        ("-j", "-j"),
        ("--json", "--json"),
        ("-I", "-I"),
        ("-I100", "-I"),
        ("--interval-print=100", "--interval-print"),
        ("-A", "-A"),
        ("--no-aggr", "--no-aggr"),
        ("--per-core", "--per-core"),
        ("--metric-only", "--metric-only"),
    ],
)
def test_a_perf_option_the_driver_cannot_take_is_refused(
    make_ctx: MakeCtx, option: str, refused: str
) -> None:
    with pytest.raises(Refusal) as caught:
        PerfDriver().prepare(make_ctx(), ["perf", "stat", option, "--", "./work"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith(
        f"the perf driver cannot take the perf stat option {refused}: "
    )


def test_without_dashes_the_rest_of_the_command_is_read_as_perf_options(
    make_ctx: MakeCtx,
) -> None:
    with pytest.raises(Refusal) as caught:
        PerfDriver().prepare(make_ctx(), ["perf", "stat", "./work", "-o", "x"])
    assert caught.value.code == "E_USAGE"
    assert "put -- before the workload's own command" in caught.value.message


def test_a_command_without_stat_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        PerfDriver().prepare(make_ctx(), ["perf", "record", "./work"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "the perf driver reads the output of perf stat: the command has no word stat"
    )


@pytest.mark.parametrize("kind", ["image", "serve"])
def test_a_container_side_needs_the_counter_capability(make_ctx: MakeCtx, kind: str) -> None:
    with pytest.raises(Refusal) as caught:
        PerfDriver().prepare(make_ctx(kind=kind), ["perf", "stat", "--", "./work"])
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", 3)
    assert caught.value.message == (
        "side 'new' runs in a container, which needs the capability to use performance "
        "counters for the perf driver: set the launch setting perf_counters = true"
    )


def test_a_container_side_with_the_capability_is_prepared(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(kind="image", perf_counters=True)
    assert PerfDriver().prepare(ctx, ["perf", "stat", "--", "./work"]).argv[2:4] == ("-x", ";")


@pytest.mark.parametrize("kind", ["cmd", "python", "venv", "conda"])
def test_a_host_side_needs_no_launch_setting(make_ctx: MakeCtx, kind: str) -> None:
    assert PerfDriver().prepare(make_ctx(kind=kind), ["perf", "stat", "true"]).argv[1] == "stat"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("12;\n", "perf-stat.txt line 1: fewer than three fields separated by ;"),
        (
            "12,,instructions,1,100.00,,\n",
            "perf-stat.txt line 1: fewer than three fields separated by ;",
        ),
        (
            "lots;;instructions;1;100.00;;\n",
            "perf-stat.txt line 1: the counter value of 'instructions' is not a number",
        ),
        ("12;;;1;100.00;;\n", "perf-stat.txt line 1: the event name is empty"),
        (
            "1;;cycles;1;100.00;;\n2;;cycles;1;100.00;;\n",
            "perf-stat.txt: the case 'cycles' is given twice",
        ),
        (
            "# started on Sat Jan  1 00:00:00 2000\n<not counted>;;cycles;0;0.00;;\n",
            "perf-stat.txt: the perf output holds no measured case",
        ),
        ("", "perf-stat.txt: the perf output holds no measured case"),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, text: str, message: str
) -> None:
    _write(tmp_path, text)
    with pytest.raises(Refusal) as caught:
        PerfDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_the_registry_loads_the_perf_driver(make_ctx: MakeCtx, tmp_path: Path) -> None:
    driver = registry.driver("perf")
    assert isinstance(driver, PerfDriver)
    assert (driver.name, driver.where) == ("perf", "in_side")
    assert driver.doctor().status == "ok"
    shutil.copy(FIXTURES / "perf-stat.txt", tmp_path / OUTPUT)
    assert driver.tool_version(make_ctx(), tmp_path) is None


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("pairbench_fixture_drivers", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_fixture_writer_replaces_only_the_start_line_and_says_what_it_keeps(
    tmp_path: Path,
) -> None:
    made_up = (
        "# started on Mon Jan  2 03:04:05 2001\n"
        "\n"
        "1234;;made_up_pmu_1/instructions/;5678;100.00;9.87;insn per cycle\n"
    )
    for raw in ("perf-stat-semicolon.txt", "perf-stat-semicolon-repeat.txt"):
        (tmp_path / raw).write_text(made_up, encoding="utf-8")

    fixtures = _generator().perf(tmp_path)

    expected = (
        "# started on Sat Jan  1 00:00:00 2000\n"
        "\n"
        "1234;;made_up_pmu_1/instructions/;5678;100.00;9.87;insn per cycle\n"
    )
    assert {name: text for name, (text, _extras) in fixtures.items()} == {
        "perf-stat.txt": expected,
        "perf-stat-repeat.txt": expected,
    }
    assert fixtures["perf-stat.txt"][1]["replaced"] == KEPT_ONE_RUN
    assert fixtures["perf-stat-repeat.txt"][1]["replaced"] == KEPT_REPEATS


@pytest.mark.parametrize(
    ("name", "kept"),
    [("perf-stat.txt", KEPT_ONE_RUN), ("perf-stat-repeat.txt", KEPT_REPEATS)],
)
def test_a_fixture_sidecar_says_what_the_run_kept(name: str, kept: str) -> None:
    sidecar = json.loads((FIXTURES / f"{name}.provenance.json").read_text(encoding="utf-8"))
    assert sidecar["replaced"] == kept
