# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench gate`` reads the settings ``run`` and ``plan`` read, and says once what failed."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.errors import EXIT_MACHINE, EXIT_OK, EXIT_USAGE
from pairbench.model import GateRecord

from .conftest import DOCS_LINE, refusal_text

Cli = Any
EXIT_ZERO = (sys.executable, "-c", "import sys; sys.exit(0)")


class RecordingGate:
    """A check that records the context it is handed and answers with a fixed status."""

    def __init__(self, name: str, status: str = "pass", message: str = "") -> None:
        self.name = name
        self.status = status
        self.message = message
        self.contexts: list[Any] = []

    def check(self, ctx: Any) -> GateRecord:
        self.contexts.append(ctx)
        detail = {"message": self.message} if self.message else {}
        return GateRecord(name=self.name, mode="enforce", status=self.status, detail=detail)  # type: ignore[arg-type]


@pytest.fixture
def no_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pairbench.cli.gate._machine", lambda environ: (False, False))


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch, no_machine: None) -> RecordingGate:
    gate = RecordingGate("quiet")
    monkeypatch.setattr(registry, "gate", lambda name: gate)
    return gate


@pytest.fixture
def cpus(monkeypatch: pytest.MonkeyPatch, no_machine: None) -> RecordingGate:
    gate = RecordingGate("cpus")
    monkeypatch.setattr(registry, "gate", lambda name: gate)
    return gate


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pairbench.toml"
    path.write_text(text, encoding="utf-8")
    return path


# --- the settings the wait reads ---------------------------------------------


def test_an_override_reaches_the_wait(
    cli: Cli, quiet: RecordingGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAIRBENCH__GATES__QUIET__MAX_WAIT_S", "7")
    monkeypatch.setenv("PAIRBENCH__GATES__QUIET__MAX_BUSY_CORES", "3.5")
    monkeypatch.setenv("PAIRBENCH__LAUNCH__GPUS", "1")

    result = cli("gate", "wait-quiet", "--", *EXIT_ZERO)

    assert result.code == EXIT_OK
    (ctx,) = quiet.contexts
    assert ctx.gates.quiet.max_wait_s == 7.0
    assert ctx.gates.quiet.max_busy_cores == 3.5
    assert ctx.gates.wait_quiet is True
    assert ctx.mode == "enforce"
    assert ctx.launch.gpus == "1"


def test_a_config_file_reaches_the_wait(
    cli: Cli, quiet: RecordingGate, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _config(
        tmp_path,
        "[gates.quiet]\nsamples = 2\n\n"
        '[sides.new]\ncmd = ["./new"]\n\n[sides.new.launch]\ngpus = "1"\n\n'
        '[sides.old]\ncmd = ["./old"]\n',
    )
    monkeypatch.setenv("PAIRBENCH_CONFIG", str(path))

    result = cli("gate", "wait-quiet", "--", *EXIT_ZERO)

    assert result.code == EXIT_OK
    (ctx,) = quiet.contexts
    assert ctx.gates.quiet.samples == 2
    assert {name: s.gpus for name, s in ctx.sides.items()} == {"new": "1", "old": None}


def test_a_config_whose_sides_take_their_kind_from_run_reaches_the_wait(
    cli: Cli, quiet: RecordingGate, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # run --side gives each side its kind; the file gives only launch settings,
    # as in `gate wait-quiet -- pairbench run --side new=cmd:./new ...`.
    path = _config(
        tmp_path,
        '[sides.new.launch]\ngpus = "1"\n\n[sides.old]\nbaseline = true\n\n'
        '[sides.old.launch]\ncpus = "4-5"\n',
    )
    monkeypatch.setenv("PAIRBENCH_CONFIG", str(path))

    result = cli("gate", "wait-quiet", "--", *EXIT_ZERO)

    assert result.code == EXIT_OK
    assert result.err == ""
    (ctx,) = quiet.contexts
    assert {name: (s.cpus, s.gpus) for name, s in ctx.sides.items()} == {
        "new": (None, "1"),
        "old": ("4-5", None),
    }


def test_config_and_set_reach_the_wait(cli: Cli, quiet: RecordingGate, tmp_path: Path) -> None:
    path = _config(tmp_path, "[gates.quiet]\nsamples = 2\ninterval_s = 0.5\n")

    result = cli(
        "gate", "wait-quiet", "--config", path, "--set", "gates.quiet.samples=4", "--", *EXIT_ZERO
    )

    assert result.code == EXIT_OK
    (ctx,) = quiet.contexts
    assert (ctx.gates.quiet.samples, ctx.gates.quiet.interval_s) == (4, 0.5)
    assert ctx.sides == {}


@pytest.mark.parametrize(
    ("text", "line"),
    [
        (
            '[sides.new]\nlauch = "x"\n\n[sides.old]\nbaseline = true\n',
            "E_CONFIG: unknown config key: sides.new.lauch",
        ),
        (
            '[sides.new.lauch]\ngpus = "1"\n\n[sides.old]\nbaseline = true\n',
            "E_CONFIG: unknown config key: sides.new.lauch.gpus",
        ),
        (
            "[sides.new.lauch]\n\n[sides.old]\nbaseline = true\n",
            "E_CONFIG: unknown config key: sides.new.lauch",
        ),
    ],
    ids=["key", "table", "empty-table"],
)
@pytest.mark.parametrize(
    "args",
    [("check", "--cpus", "2-3"), ("wait-quiet", "--", "touch", "{marker}")],
    ids=["check", "wait-quiet"],
)
def test_a_misspelt_key_in_a_side_table_without_a_kind_is_refused_as_run_refuses_it(
    text: str,
    line: str,
    args: tuple[str, ...],
    cli: Cli,
    quiet: RecordingGate,
    tmp_path: Path,
) -> None:
    path = _config(tmp_path, text)
    marker = tmp_path / "ran"

    form, *rest = (a.format(marker=marker) for a in args)
    result = cli("gate", form, "--config", str(path), *rest)

    assert result.code == EXIT_USAGE
    assert (result.out, result.err) == ("", refusal_text(line))
    assert quiet.contexts == []
    assert not marker.exists()


def test_a_key_that_a_kind_of_side_takes_is_left_to_the_run_that_gives_the_kind(
    cli: Cli, quiet: RecordingGate, tmp_path: Path
) -> None:
    # `args` belongs to an image side; run --side new=image:... gives the kind.
    path = _config(
        tmp_path,
        '[sides.new]\nargs = ["--fast"]\n\n[sides.new.launch]\ncpus = "4-5"\n\n'
        "[sides.old]\nbaseline = true\n",
    )

    result = cli("gate", "wait-quiet", "--config", path, "--", *EXIT_ZERO)

    assert result.code == EXIT_OK
    assert result.err == ""
    (ctx,) = quiet.contexts
    assert {name: s.cpus for name, s in ctx.sides.items()} == {"new": "4-5", "old": None}


FILE_SIDES_NOTE = (
    "pairbench: note: checks_use_shared_settings: the sides of the config are result files, "
    "which launch nothing; the checks use the shared launch settings\n"
)


@pytest.mark.parametrize(
    "args",
    [("check", "--cpus", "2-3"), ("wait-quiet", "--", *EXIT_ZERO)],
    ids=["check", "wait-quiet"],
)
def test_a_config_of_result_files_only_says_the_checks_use_the_shared_settings(
    args: tuple[str, ...], cli: Cli, quiet: RecordingGate, tmp_path: Path
) -> None:
    path = _config(
        tmp_path,
        '[launch]\ngpus = "0"\n\n'
        '[sides.new]\nfile = ["new-*.json"]\n\n[sides.new.launch]\ngpus = "1"\n\n'
        '[sides.old]\nfile = ["old-*.json"]\n',
    )

    result = cli("gate", args[0], "--config", str(path), *args[1:])

    assert result.code == EXIT_OK
    assert result.err == FILE_SIDES_NOTE
    (ctx,) = quiet.contexts
    assert ctx.sides == {}
    assert ctx.launch.overrides == {}
    assert ctx.launch.gpus == "0"


# --- the settings the check reads --------------------------------------------


def test_an_override_reaches_the_check(
    cli: Cli, cpus: RecordingGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAIRBENCH__GATES__ALLOW_MIXED_CORE_TYPES", "true")
    monkeypatch.setenv("PAIRBENCH__LAUNCH__CPUS", "0-7")

    result = cli("gate", "check", "--cpus", "2-3")

    assert result.code == EXIT_OK
    (ctx,) = cpus.contexts
    assert ctx.gates.allow_mixed_core_types is True
    assert ctx.mode == "enforce"
    assert ctx.launch.cpus == "2-3"


def test_a_config_file_reaches_the_check(
    cli: Cli, cpus: RecordingGate, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _config(
        tmp_path,
        '[sides.new]\ncmd = ["./new"]\n\n[sides.new.launch]\ncpus = "4-5"\n\n'
        '[sides.old]\ncmd = ["./old"]\n',
    )
    monkeypatch.setenv("PAIRBENCH_CONFIG", str(path))

    result = cli("gate", "check", "--cpus", "2-3")

    assert result.code == EXIT_OK
    (ctx,) = cpus.contexts
    assert ctx.launch.overrides == {"new": {"cpus": "4-5"}}
    assert {name: s.cpus for name, s in ctx.sides.items()} == {"new": "4-5", "old": "2-3"}


def test_the_flag_of_the_check_wins_over_the_config(
    cli: Cli, cpus: RecordingGate, tmp_path: Path
) -> None:
    path = _config(tmp_path, "[gates]\nallow_mixed_core_types = false\n")

    result = cli("gate", "check", "--cpus", "2-3", "--allow-mixed-core-types", "--config", path)

    assert result.code == EXIT_OK
    assert cpus.contexts[0].gates.allow_mixed_core_types is True


def test_a_flag_and_set_that_disagree_are_refused_as_run_refuses_them(
    cli: Cli, cpus: RecordingGate
) -> None:
    result = cli("gate", "check", "--cpus", "2-3", "--set", "launch.cpus=4-5")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: a flag and --set give launch.cpus different values")
    assert cpus.contexts == []


def test_a_flag_and_set_that_write_one_cpu_set_two_ways_reach_the_check(
    cli: Cli, cpus: RecordingGate
) -> None:
    result = cli("gate", "check", "--cpus", "0-3", "--set", "launch.cpus=0,1,2,3")

    assert result.code == EXIT_OK
    assert result.err == ""
    (ctx,) = cpus.contexts
    assert ctx.launch.cpus == "0,1,2,3"


@pytest.mark.parametrize(
    "args",
    [("check", "--cpus", "2-3"), ("wait-quiet", "--", "touch", "{marker}")],
    ids=["check", "wait-quiet"],
)
@pytest.mark.parametrize("source", ["variable", "file"])
def test_an_unknown_key_is_refused_before_any_check(
    source: str,
    args: tuple[str, ...],
    cli: Cli,
    monkeypatch: pytest.MonkeyPatch,
    no_machine: None,
    tmp_path: Path,
) -> None:
    gate = RecordingGate("quiet")
    monkeypatch.setattr(registry, "gate", lambda name: gate)
    if source == "variable":
        monkeypatch.setenv("PAIRBENCH__GATES__QUIET__MAX_WAIT", "1")
    else:
        path = _config(tmp_path, "[gates.quiet]\nmax_wait = 1\n")
        monkeypatch.setenv("PAIRBENCH_CONFIG", str(path))
    marker = tmp_path / "ran"

    result = cli("gate", *(a.format(marker=marker) for a in args))

    assert result.code == EXIT_USAGE
    assert result.out == ""
    assert result.err.startswith("E_CONFIG: ")
    assert "max_wait" in result.err.lower()
    assert gate.contexts == []
    assert not marker.exists()


@pytest.mark.parametrize(
    "args",
    [("check", "--cpus", "2-3"), ("wait-quiet", "--", "touch", "{marker}")],
    ids=["check", "wait-quiet"],
)
@pytest.mark.parametrize("source", ["variable", "file"])
def test_a_bad_value_of_a_quiet_setting_is_refused_before_any_check(
    source: str,
    args: tuple[str, ...],
    cli: Cli,
    quiet: RecordingGate,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if source == "variable":
        monkeypatch.setenv("PAIRBENCH__GATES__QUIET__MAX_BUSY_CORES", "notanumber")
    else:
        path = _config(tmp_path, '[gates.quiet]\nmax_busy_cores = "notanumber"\n')
        monkeypatch.setenv("PAIRBENCH_CONFIG", str(path))
    marker = tmp_path / "ran"

    result = cli("gate", *(a.format(marker=marker) for a in args))

    assert result.code == EXIT_USAGE
    assert (result.out, result.err) == (
        "",
        refusal_text("E_CONFIG: gates.quiet.max_busy_cores must be a number"),
    )
    assert quiet.contexts == []
    assert not marker.exists()


# --- what a check that did not pass prints -----------------------------------


@pytest.mark.parametrize(
    ("status", "line"),
    [
        ("fail", "E_GATE_FAILED: check cpus failed: mixed core types"),
        ("degraded", "E_GATE_UNAVAILABLE: check cpus could not run fully: mixed core types"),
    ],
)
def test_a_check_that_did_not_pass_says_so_once_on_standard_error(
    status: str, line: str, cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    gate = RecordingGate("cpus", status, "mixed core types")
    monkeypatch.setattr(registry, "gate", lambda name: gate)

    result = cli("gate", "check", "--cpus", "0-7")

    assert result.code == EXIT_MACHINE
    assert result.out == ""
    assert result.err.splitlines() == [
        f"pairbench: check cpus: {status}: mixed core types",
        line,
        DOCS_LINE + line.split(":", 1)[0].lower(),
    ]


def test_a_check_that_did_not_pass_still_prints_its_record_as_json(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: RecordingGate("cpus", "fail", "busy"))

    result = cli("gate", "check", "--cpus", "0-7", "--json")

    assert result.code == EXIT_MACHINE
    assert '"status": "fail"' in result.out
    assert result.err.splitlines()[-2:] == [
        "E_GATE_FAILED: check cpus failed: busy",
        DOCS_LINE + "e_gate_failed",
    ]
