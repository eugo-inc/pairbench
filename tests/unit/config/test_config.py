# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The resolved config: file, environment, command line, defaults, and what is refused."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pairbench import config, model
from pairbench.errors import Refusal

TWO_SIDES = ("new=cmd:python bench.py --variant b", "old=cmd:python bench.py --variant a")

FILE_TEXT = """
[run]
rounds = 8
warmups = 2
budget = "1h30m"

[workload]
argv = ["python", "bench.py"]
driver = "lines"

[sides.new]
image = "example.invalid/app:2.0"
args = ["--fast"]

[sides.old]
image = "example.invalid/app:1.9"
baseline = true

[launch]
timeout = 90
env = { OMP_NUM_THREADS = "4" }
"""


def _write(tmp_path: Path, text: str = FILE_TEXT, name: str = "experiment.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _refused(code: str, exit_code: int, **kwargs: Any) -> Refusal:
    with pytest.raises(Refusal) as caught:
        config.load_experiment(**{"environ": {}, **kwargs})
    assert caught.value.code == code
    assert caught.value.exit_code == exit_code
    return caught.value


def _at(data: Mapping[str, Any], parts: tuple[str, ...]) -> Any:
    value: Any = data
    for part in parts:
        value = value[part]
    return value


# ---------------------------------------------------------------------------
# The file and the defaults
# ---------------------------------------------------------------------------


def test_file_values_and_defaults(tmp_path: Path) -> None:
    experiment = config.load_experiment(_write(tmp_path), environ={})
    assert experiment.run.rounds == 8
    assert experiment.run.warmups == 2
    assert experiment.run.budget_s == 5400.0
    assert experiment.launch.timeout_s == 90.0
    assert experiment.driver == "lines"
    assert experiment.baseline == "old"
    assert experiment.subjects == ("new",)
    assert experiment.gates.mode == "warn"
    assert experiment.explain.mode == "always"
    assert experiment.plots.mode == "auto"


def test_no_config_file_is_picked_up_by_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("pairbench.toml", ".pairbench.toml", "pyproject.toml", "config.toml"):
        _write(tmp_path, FILE_TEXT, name)
    monkeypatch.chdir(tmp_path)
    refusal = _refused("E_CONFIG", 2)
    assert refusal.message == "the config declares no side"


def test_the_variable_names_the_config_file(tmp_path: Path) -> None:
    path = _write(tmp_path)
    experiment = config.load_experiment(environ={config.CONFIG_VARIABLE: str(path)})
    assert experiment.run.rounds == 8


def test_a_path_given_wins_over_the_variable(tmp_path: Path) -> None:
    given = _write(tmp_path, FILE_TEXT.replace("rounds = 8", "rounds = 10"), "given.toml")
    named = _write(tmp_path, FILE_TEXT, "named.toml")
    experiment = config.load_experiment(given, environ={config.CONFIG_VARIABLE: str(named)})
    assert experiment.run.rounds == 10


def test_unknown_key_in_the_file_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, FILE_TEXT + "\n[run.extra]\nflavour = 1\n")
    refusal = _refused("E_CONFIG", 2, path=path)
    assert "run.extra" in refusal.message


def test_unknown_table_in_the_file_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, FILE_TEXT + "\n[colours]\nnew = 'blue'\n")
    refusal = _refused("E_CONFIG", 2, path=path)
    assert refusal.message == "unknown config key: colours"


def test_missing_config_file_is_refused(tmp_path: Path) -> None:
    refusal = _refused("E_CONFIG", 2, path=tmp_path / "absent.toml")
    assert refusal.message.startswith("cannot read the config file absent.toml")


def test_file_that_is_not_toml_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "[run\nrounds = ")
    refusal = _refused("E_CONFIG", 2, path=path)
    assert refusal.message.startswith("the config file experiment.toml is not valid TOML")


@pytest.mark.parametrize(
    ("written", "seconds"),
    [("90s", 90.0), ("10m", 600.0), ("1h30m", 5400.0), ("250ms", 0.25), ("45", 45.0), (12, 12.0)],
)
def test_durations(tmp_path: Path, written: object, seconds: float) -> None:
    value = f'"{written}"' if isinstance(written, str) else str(written)
    path = _write(tmp_path, FILE_TEXT.replace('budget = "1h30m"', f"budget = {value}"))
    assert config.load_experiment(path, environ={}).run.budget_s == seconds


@pytest.mark.parametrize("written", ['"ten minutes"', '"10x"', '"-5s"', "true"])
def test_bad_durations_are_refused(tmp_path: Path, written: str) -> None:
    path = _write(tmp_path, FILE_TEXT.replace('budget = "1h30m"', f"budget = {written}"))
    refusal = _refused("E_CONFIG", 2, path=path)
    assert refusal.message == "run.budget must be a duration such as 90s, 10m or 1h30m"


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_precedence_command_line_then_environment_then_file(tmp_path: Path) -> None:
    path = _write(tmp_path)
    environ = {"PAIRBENCH__RUN__ROUNDS": "12", "PAIRBENCH__RUN__WARMUPS": "3"}
    flags = config.flag_config({"--rounds": "24"})
    experiment = config.load_experiment(path, environ=environ, flags=flags)
    assert experiment.run.rounds == 24
    assert experiment.run.warmups == 3
    assert experiment.run.budget_s == 5400.0
    assert experiment.run.quick is False


def test_set_has_the_precedence_of_the_command_line(tmp_path: Path) -> None:
    path = _write(tmp_path)
    environ = {"PAIRBENCH__RUN__ROUNDS": "12"}
    experiment = config.load_experiment(path, environ=environ, sets=["run.rounds=16"])
    assert experiment.run.rounds == 16


def test_environment_overrides_one_key_of_a_side(tmp_path: Path) -> None:
    path = _write(tmp_path)
    environ = {"PAIRBENCH__SIDES__NEW__IMAGE": "example.invalid/app:2.1"}
    experiment = config.load_experiment(path, environ=environ)
    assert experiment.side("new").spec["image"] == "example.invalid/app:2.1"
    assert experiment.side("new").spec["args"] == ("--fast",)


def test_command_line_side_of_another_kind_replaces_the_file_side(tmp_path: Path) -> None:
    text = FILE_TEXT + '\n[sides.new.launch]\ncpus = "4-7"\n'
    path = _write(tmp_path, text)
    flags = config.flag_config({}, sides=["new=cmd:python other.py"])
    experiment = config.load_experiment(path, environ={}, flags=flags)
    new = experiment.side("new")
    assert new.kind == model.KIND_CMD
    assert new.spec["argv"] == ("python", "other.py")
    assert experiment.launch.overrides["new"] == {"cpus": "4-7"}


def test_flag_side_of_another_kind_keeps_the_baseline_mark(tmp_path: Path) -> None:
    path = _write(tmp_path)
    flags = config.flag_config({}, sides=["old=cmd:python old.py"])
    experiment = config.load_experiment(path, environ={}, flags=flags)
    assert experiment.baseline == "old"
    assert experiment.side("old").kind == model.KIND_CMD


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def test_environment_parts_are_lower_cased() -> None:
    environ = {"PAIRBENCH__RUN__ROUNDS": "24", "PAIRBENCH__Gates__Mode": "off"}
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ=environ, flags=flags)
    assert experiment.run.rounds == 24
    assert experiment.gates.mode == "off"


def test_environment_side_name_is_lower_cased() -> None:
    environ = {
        "PAIRBENCH__SIDES__NEW__CMD": "python b.py",
        "PAIRBENCH__SIDES__OLD__CMD": "python a.py",
    }
    experiment = config.load_experiment(environ=environ)
    assert [side.name for side in experiment.sides] == ["new", "old"]


def test_environment_variable_naming_no_key_is_refused() -> None:
    refusal = _refused(
        "E_CONFIG",
        2,
        environ={"PAIRBENCH__RUN__ROUND": "24"},
        flags=config.flag_config({}, sides=TWO_SIDES),
    )
    assert refusal.message == "the variable PAIRBENCH__RUN__ROUND names no config key"


def test_environment_variable_with_an_empty_part_is_refused() -> None:
    refusal = _refused(
        "E_CONFIG",
        2,
        environ={"PAIRBENCH__RUN____ROUNDS": "24"},
        flags=config.flag_config({}, sides=TWO_SIDES),
    )
    assert refusal.message == "the variable PAIRBENCH__RUN____ROUNDS names no config key"


def test_environment_variable_inside_a_table_of_names_is_refused() -> None:
    refusal = _refused(
        "E_CONFIG",
        2,
        environ={"PAIRBENCH__LAUNCH__ENV__OMP_NUM_THREADS": "4"},
        flags=config.flag_config({}, sides=TWO_SIDES),
    )
    assert "PAIRBENCH__LAUNCH__ENV='{ NAME" in refusal.message
    assert "lower-cased" in refusal.message


def test_environment_sets_a_whole_table_of_names() -> None:
    environ = {"PAIRBENCH__LAUNCH__ENV": '{ OMP_NUM_THREADS = "4" }'}
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ=environ, flags=flags)
    assert experiment.launch.env == {"OMP_NUM_THREADS": "4"}


def test_other_pairbench_variables_are_not_config_keys() -> None:
    environ = {"PAIRBENCH_WORK_FACTOR": "2", "PAIRBENCH_REQUIRE_ENGINE": "docker", "CI": "1"}
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ=environ, flags=flags)
    assert experiment.run.rounds == "auto"


def test_out_variable_sets_the_output_folder() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={config.OUT_VARIABLE: "runs/a"}, flags=flags)
    assert experiment.run.out == "runs/a"


def test_out_flag_wins_over_the_out_variable() -> None:
    flags = config.flag_config({"--out": "runs/b"}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={config.OUT_VARIABLE: "runs/a"}, flags=flags)
    assert experiment.run.out == "runs/b"


def test_out_variable_and_out_override_that_differ_are_refused() -> None:
    environ = {config.OUT_VARIABLE: "runs/a", "PAIRBENCH__RUN__OUT": "runs/b"}
    refusal = _refused(
        "E_CONFIG", 2, environ=environ, flags=config.flag_config({}, sides=TWO_SIDES)
    )
    assert refusal.message == (
        "PAIRBENCH_OUT and PAIRBENCH__RUN__OUT name different output folders"
    )


def test_engine_variable_is_the_launch_engine_key() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(
        environ={"PAIRBENCH__LAUNCH__ENGINE": "podman"}, flags=flags
    )
    assert experiment.launch.engine == "podman"


# ---------------------------------------------------------------------------
# --set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("24", 24),
        ("2.5", 2.5),
        ("true", True),
        ("[1, 8, 32]", [1, 8, 32]),
        ('"24"', "24"),
        ("auto", "auto"),
        ("4-7", "4-7"),
        ("example.invalid/app:2.1", "example.invalid/app:2.1"),
        ("8g", "8g"),
        ("", ""),
        ("1\nw = 2", "1\nw = 2"),
        ('{ A = "1" }', {"A": "1"}),
        ("1979-05-27", datetime.date(1979, 5, 27)),
    ],
)
def test_values_are_toml_when_they_parse_and_text_otherwise(text: str, value: object) -> None:
    assert config.parse_value(text) == value
    assert type(config.parse_value(text)) is type(value)


def test_set_reaches_a_key_of_every_table() -> None:
    sets = [
        "workload.level_kind=rate",
        "launch.cpus=4-7",
        'launch.env.OMP_NUM_THREADS="4"',
        "gates.quiet.samples=7",
        "controls.positive=off",
        "explain.mode=off",
        "plots.max_round_charts=3",
        "report.html=false",
        "launch_cost.launches=0",
        "sides.new.launch.timeout=30s",
    ]
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={}, flags=flags, sets=sets)
    assert experiment.load.level_kind == "rate"
    assert experiment.launch.cpus == "4-7"
    assert experiment.launch.env == {"OMP_NUM_THREADS": "4"}
    assert experiment.gates.quiet.samples == 7
    assert experiment.controls.positive == "off"
    assert experiment.explain.mode == "off"
    assert experiment.plots.max_round_charts == 3
    assert experiment.report.html is False
    assert experiment.launch_cost.launches == 0
    assert experiment.launch.overrides["new"] == {"timeout_s": 30.0}


def _sample_value(key: str) -> Any:
    if key in model.CONFIG_TABLE_KEYS:
        return {"A": "1"}
    return "made-up-value"


@pytest.mark.parametrize("key", model.CONFIG_KEYS)
def test_every_config_key_can_be_set_on_the_command_line(key: str) -> None:
    path = key.replace("NAME", "s1")
    value = _sample_value(key)
    text = '{ A = "1" }' if isinstance(value, dict) else str(value)
    merged = config.resolve_config(environ={}, sets=[f"{path}={text}"])
    assert _at(merged, tuple(path.split("."))) == value


@pytest.mark.parametrize("key", model.CONFIG_KEYS)
def test_every_config_key_can_be_set_in_the_environment(key: str) -> None:
    path = key.replace("NAME", "s1")
    value = _sample_value(key)
    text = '{ A = "1" }' if isinstance(value, dict) else str(value)
    name = config.OVERRIDE_PREFIX + "__".join(part.upper() for part in path.split("."))
    merged = config.resolve_config(environ={name: text})
    assert _at(merged, tuple(path.split("."))) == value


def test_set_without_equals_is_a_usage_error() -> None:
    refusal = _refused("E_USAGE", 2, sets=["run.rounds"])
    assert refusal.message == "--set is written KEY=VALUE, got 'run.rounds'"


def test_set_of_an_unknown_key_is_a_config_error() -> None:
    refusal = _refused("E_CONFIG", 2, sets=["run.colour=blue"])
    assert refusal.message == "unknown config key: run.colour"


def test_set_of_a_bad_value_is_a_config_error() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    refusal = _refused("E_CONFIG", 2, flags=flags, sets=["gates.mode=loud"])
    assert refusal.message == "gates.mode must be one of off, warn, enforce"


def test_flag_and_set_with_different_values_are_a_usage_error() -> None:
    flags = config.flag_config({"--rounds": "8"}, sides=TWO_SIDES)
    refusal = _refused("E_USAGE", 2, flags=flags, sets=["run.rounds=9"])
    assert refusal.message == "a flag and --set give run.rounds different values"


def test_flag_and_set_with_the_same_value_agree() -> None:
    flags = config.flag_config({"--rounds": "8", "--quick": True}, sides=TWO_SIDES)
    experiment = config.load_experiment(
        environ={}, flags=flags, sets=["run.rounds=8", "run.quick=true"]
    )
    assert experiment.run.rounds == 8


def test_flag_and_set_of_one_duration_written_two_ways_agree() -> None:
    flags = config.flag_config({"--budget": "600s"}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={}, flags=flags, sets=["run.budget=10m"])
    assert experiment.run.budget_s == 600.0


@pytest.mark.parametrize(
    ("flag", "written", "setting", "read"),
    [
        ("--cpus", "4", "launch.cpus=4", lambda e: e.launch.cpus),
        ("--cpus", "4-7", 'launch.cpus="4-7"', lambda e: e.launch.cpus),
        ("--gpus", "0,1", "launch.gpus=[0, 1]", lambda e: e.launch.gpus),
        ("--levels", "1,8,32", "workload.levels=[1, 8, 32]", lambda e: e.load.levels),
        ("--levels", "4", "workload.levels=4", lambda e: e.load.levels),
        (
            "--same-vs-same",
            "new,old",
            'run.same_vs_same=["new", "old"]',
            lambda e: e.run.same_vs_same,
        ),
        ("--timeout", "90", "launch.timeout=90", lambda e: e.launch.timeout_s),
    ],
)
def test_flag_and_set_of_one_value_written_two_ways_agree(
    flag: str, written: str, setting: str, read: Any
) -> None:
    flags = config.flag_config({flag: written}, sides=TWO_SIDES)
    both = config.load_experiment(environ={}, flags=flags, sets=[setting])
    alone = config.load_experiment(environ={}, flags=flags)
    assert read(both) == read(alone)


@pytest.mark.parametrize(
    ("written", "setting", "kept"),
    [
        ("0-3", 'launch.cpus="0,1,2,3"', "0,1,2,3"),
        ("0,1,2,3", 'launch.cpus="0-3"', "0-3"),
        ("2,0-1", 'launch.cpus="0-2"', "0-2"),
        ("4", 'launch.cpus="4-4"', "4-4"),
        ("4-5", "launch.cpus=4,5", "4,5"),
    ],
)
def test_flag_and_set_of_one_cpu_set_written_two_ways_agree(
    written: str, setting: str, kept: str
) -> None:
    flags = config.flag_config({"--cpus": written}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={}, flags=flags, sets=[setting])
    assert experiment.launch.cpus == kept


@pytest.mark.parametrize(
    ("flag", "written", "setting"),
    [
        ("--cpus", "4", "launch.cpus=5"),
        ("--cpus", "0-3", 'launch.cpus="0-4"'),
        ("--cpus", "0-3", 'launch.cpus="0,1,3"'),
        ("--cpus", "0-99999", 'launch.cpus="0-3"'),
        ("--gpus", "0,1", "launch.gpus=[0]"),
        ("--levels", "1,8", "workload.levels=[1, 8, 32]"),
        ("--same-vs-same", "new", 'run.same_vs_same=["old"]'),
    ],
)
def test_flag_and_set_of_two_values_that_read_differently_are_a_usage_error(
    flag: str, written: str, setting: str
) -> None:
    flags = config.flag_config({flag: written}, sides=TWO_SIDES)
    key = setting.partition("=")[0]
    refusal = _refused("E_USAGE", 2, flags=flags, sets=[setting])
    assert refusal.message == f"a flag and --set give {key} different values"


def test_a_config_without_sides_still_compares_a_flag_and_set_after_reading() -> None:
    alike = config.resolve_config(
        None, environ={}, flags=config.flag_config({"--cpus": "4"}), sets=["launch.cpus=4"]
    )
    assert alike["launch"]["cpus"] == 4
    with pytest.raises(Refusal) as caught:
        config.resolve_config(
            None, environ={}, flags=config.flag_config({"--cpus": "4"}), sets=["launch.cpus=5"]
        )
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "a flag and --set give launch.cpus different values",
    )


def test_two_values_in_a_config_unreadable_for_another_reason_are_compared_as_written() -> None:
    flags = config.flag_config({"--cpus": "4"}, sides=TWO_SIDES)
    refusal = _refused("E_USAGE", 2, flags=flags, sets=["launch.cpus=5", 'run.rounds="x"'])
    assert refusal.message == "a flag and --set give launch.cpus different values"


def test_flag_and_set_of_one_bad_value_leave_the_refusal_to_the_reading() -> None:
    flags = config.flag_config({"--cpus": "x"}, sides=TWO_SIDES)
    refusal = _refused("E_CONFIG", 2, flags=flags, sets=['launch.cpus="y"'])
    assert refusal.message.startswith("launch.cpus must be a CPU list")


def test_flag_and_set_of_a_switch_against_a_number_differ() -> None:
    flags = config.flag_config({"--quick": True}, sides=TWO_SIDES)
    _refused("E_USAGE", 2, flags=flags, sets=["run.quick=1"])


def test_side_flag_and_set_of_the_same_side_spec_differ() -> None:
    flags = config.flag_config({}, sides=("new=image:example.invalid/a:1", TWO_SIDES[1]))
    refusal = _refused("E_USAGE", 2, flags=flags, sets=["sides.new.image=example.invalid/b:1"])
    assert refusal.message == "a flag and --set give sides.new.image different values"


def test_side_flag_and_set_of_another_kind_are_a_usage_error() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    refusal = _refused("E_USAGE", 2, flags=flags, sets=["sides.new.image=example.invalid/a:1"])
    assert refusal.message == "--side and --set make side 'new' two kinds: cmd and image"


def test_set_inside_a_table_of_names_keeps_the_name() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    experiment = config.load_experiment(environ={}, flags=flags, sets=['launch.env.Mixed_Case="x"'])
    assert experiment.launch.env == {"Mixed_Case": "x"}


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def _flag_sample(flag: str) -> Any:
    if flag in config.SWITCH_FLAGS:
        return True
    if flag in config.REPEATED_FLAGS:
        return ["made-up"]
    return "made-up"


@pytest.mark.parametrize("flag", sorted(model.FLAG_KEYS))
def test_every_flag_sets_its_key(flag: str) -> None:
    built = config.flag_config({flag: _flag_sample(flag)})
    assert _at(built, tuple(model.FLAG_KEYS[flag].split("."))) == _flag_sample(flag)


def test_number_flags_become_numbers() -> None:
    built = config.flag_config({"--rounds": "12", "--warmups": "0"})
    assert built == {"run": {"rounds": 12, "warmups": 0}}


def test_rounds_auto_stays_a_word() -> None:
    assert config.flag_config({"--rounds": "auto"}) == {"run": {"rounds": "auto"}}


def test_flag_without_a_key_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        config.flag_config({"--colour": "blue"})
    assert caught.value.code == "E_USAGE"


def test_workload_after_the_separator_is_the_workload_argv() -> None:
    built = config.flag_config({}, workload=["python", "bench.py", "--size", "3"])
    assert built == {"workload": {"argv": ["python", "bench.py", "--size", "3"]}}


@pytest.mark.parametrize(
    ("text", "table"),
    [
        ("a=image:example.invalid/app:2.0", {"image": "example.invalid/app:2.0"}),
        ("a=cmd:python bench.py 'two words'", {"cmd": ["python", "bench.py", "two words"]}),
        ("a=python:/opt/made-up/python3", {"python": "/opt/made-up/python3"}),
        ("a=venv:.venv-a", {"venv": ".venv-a"}),
        ("a=conda:env-a", {"conda": "env-a"}),
        ("a=serve:example.invalid/server:1", {"serve": {"image": "example.invalid/server:1"}}),
        ("a=file:results/a-*.json", {"file": ["results/a-*.json"]}),
        ("a=plugkind:made-up-spec", {"kind": "plugkind", "spec": "made-up-spec"}),
    ],
)
def test_side_flag_becomes_a_side_table(text: str, table: dict[str, Any]) -> None:
    assert config.side_table(text) == ("a", table)


@pytest.mark.parametrize("text", ["a", "a=", "a=cmd", "a=cmd:", "=cmd:x", "a~b=cmd:x"])
def test_malformed_side_flag_is_a_usage_error(text: str) -> None:
    with pytest.raises(Refusal) as caught:
        config.side_table(text)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_side_named_twice_is_a_usage_error() -> None:
    with pytest.raises(Refusal) as caught:
        config.flag_config({}, sides=["a=cmd:x", "a=cmd:y"])
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    "source",
    [
        {"environ": {"PAIRBENCH__SIDES__\udcff__CMD": "x"}, "sets": ["sides.b.cmd=y"]},
        {"sets": ["sides.\udcff.cmd=x", "sides.b.cmd=y"]},
    ],
)
def test_a_side_name_that_is_not_utf8_text_is_a_usage_error(source: dict[str, Any]) -> None:
    refused = _refused("E_USAGE", 2, **source)

    assert refused.line == "E_USAGE: side name '\\udcff' is refused: it is not UTF-8 text"


def test_a_flag_side_name_that_is_not_utf8_text_is_a_usage_error() -> None:
    with pytest.raises(Refusal) as caught:
        config.flag_config({}, sides=["\udcff=cmd:x", "b=cmd:y"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.line == "E_USAGE: side name '\\udcff' is refused: it is not UTF-8 text"


def test_command_line_sides_keep_their_order() -> None:
    flags = config.flag_config({}, sides=["c=cmd:x", "a=cmd:y", "b=cmd:z"])
    experiment = config.load_experiment(environ={}, flags=flags)
    assert [side.name for side in experiment.sides] == ["c", "a", "b"]
    assert experiment.baseline == "b"


def test_baseline_flag_names_the_baseline(tmp_path: Path) -> None:
    flags = config.flag_config({}, baseline="new")
    experiment = config.load_experiment(_write(tmp_path), environ={}, flags=flags)
    assert experiment.baseline == "new"
    assert experiment.subjects == ("old",)


def test_baseline_flag_naming_no_side_is_a_usage_error() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES, baseline="other")
    refusal = _refused("E_USAGE", 2, flags=flags)
    assert refusal.message == "--baseline names no side: 'other'"


def test_baseline_flag_and_set_naming_another_baseline_are_a_usage_error() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES, baseline="new")
    refusal = _refused("E_USAGE", 2, flags=flags, sets=["sides.old.baseline=true"])
    assert refusal.message == "--baseline names 'new' and --set makes 'old' the baseline"


# ---------------------------------------------------------------------------
# What a capture keeps
# ---------------------------------------------------------------------------


def test_credential_like_values_are_redacted_in_the_resolved_config() -> None:
    flags = config.flag_config({}, sides=TWO_SIDES)
    sets = ['launch.env.API_TOKEN="x"', 'launch.env.OMP_NUM_THREADS="4"']
    experiment = config.load_experiment(environ={}, flags=flags, sets=sets)
    kept = experiment.to_json()
    assert kept["launch"]["env"] == {"API_TOKEN": model.REDACTED, "OMP_NUM_THREADS": "4"}
    assert experiment.launch.env["API_TOKEN"] == "x"


def test_set_of_a_credential_like_variable_is_redacted_on_the_recorded_command_line() -> None:
    argv = ["pairbench", "run", "--set", "launch.env.API_TOKEN=x", "--side", "a=cmd:y"]
    assert model.redact_argv(argv) == (
        "pairbench",
        "run",
        "--set",
        f"launch.env.API_TOKEN={model.REDACTED}",
        "--side",
        "a=cmd:y",
    )
