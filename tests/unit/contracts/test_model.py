# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Sides, the experiment and its settings, the rule and the config form."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pairbench import model
from pairbench.errors import Refusal
from pairbench.model import (
    STRICT,
    Experiment,
    Floors,
    LaunchSettings,
    LoadSettings,
    Ready,
    Rule,
    RunSettings,
    ServeSpec,
    Side,
)

# ---------------------------------------------------------------------------
# Sides
# ---------------------------------------------------------------------------


def test_the_headline_side_is_parsed() -> None:
    side = Side.parse("new=image:myorg/app:2.0")
    assert side.name == "new"
    assert side.kind == "image"
    assert side.role == "subject"
    assert side.twin_of is None
    assert side.spec == {"image": "myorg/app:2.0", "args": (), "env": {}, "entrypoint": None}
    assert side.identity == {}
    assert side.fingerprint == ""


@pytest.mark.parametrize(
    ("text", "kind", "spec"),
    [
        (
            "old=image:registry.example:5000/org/app:1.9",
            "image",
            "registry.example:5000/org/app:1.9",
        ),
        (
            "a=cmd:python bench.py --size 'big one'",
            "cmd",
            ("python", "bench.py", "--size", "big one"),
        ),
        ("a=cmd:taskset -c 2 {workload}", "cmd", ("taskset", "-c", "2", "{workload}")),
        ("a=python:/opt/py/bin/python3", "python", "/opt/py/bin/python3"),
        ("a=venv:./env-a", "venv", "./env-a"),
        ("a=conda:env-a", "conda", "env-a"),
        ("a=file:results/a-*.json", "file", ("results/a-*.json",)),
        ("a=made_up:anything:at=all", "made_up", "anything:at=all"),
    ],
)
def test_a_side_of_each_kind_is_parsed(text: str, kind: str, spec: Any) -> None:
    side = Side.parse(text)
    key = {
        "image": "image",
        "cmd": "argv",
        "python": "interpreter",
        "venv": "venv",
        "conda": "conda",
        "file": "paths",
        "made_up": "spec",
    }[kind]
    assert side.kind == kind
    assert side.spec[key] == spec


def test_a_serving_side_is_parsed_with_its_defaults() -> None:
    side = Side.parse("new=serve:myorg/server:2.0")
    spec = side.serve_spec()
    assert side.kind == "serve"
    assert spec.image == "myorg/server:2.0"
    assert spec.args == ()
    assert spec.port == 8000
    assert spec.ready == Ready(http="/health", timeout_s=900.0)
    assert spec.launcher is None
    assert spec.probe.path == "/v1/chat/completions"


@pytest.mark.parametrize(
    "text", ["new", "new=image", "new=image:", "=image:x", "new=:x", "a~b=image:x", "a b=image:x"]
)
def test_a_side_that_is_not_written_as_name_kind_spec_is_refused(text: str) -> None:
    with pytest.raises(Refusal) as caught:
        Side.parse(text)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_the_side_constructors() -> None:
    image = Side.image("new", "myorg/app:2.0", args=["--fast"], env={"A": "1"}, entrypoint="/run")
    assert (image.kind, image.spec) == (
        "image",
        {"image": "myorg/app:2.0", "args": ("--fast",), "env": {"A": "1"}, "entrypoint": "/run"},
    )
    command = Side.command("new", ["python", "bench.py"])
    assert (command.kind, command.spec) == ("cmd", {"argv": ("python", "bench.py")})
    assert Side.python("a", interpreter="/usr/bin/python3").kind == "python"
    assert Side.python("a", venv="./env").spec == {"venv": "./env"}
    assert Side.python("a", conda="env-a").kind == "conda"
    files = Side.files("a", ["r1.json", "r2.json"], format="gbench")
    assert (files.kind, files.spec) == (
        "file",
        {"paths": ("r1.json", "r2.json"), "format": "gbench"},
    )


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ({"image": "img", "redy": {"http": "/ready"}}, "serve: unknown key 'redy'"),
        ({"image": "img", "ready": {"htp": "/ready"}}, "serve.ready: unknown key 'htp'"),
        ({"image": "img", "probe": {"pth": "/v1"}}, "serve.probe: unknown key 'pth'"),
        ({"image": "img", "b": 1, "a": 2}, "serve: unknown keys 'a', 'b'"),
    ],
)
def test_an_unknown_key_of_a_serving_spec_is_refused(data: dict[str, Any], words: str) -> None:
    with pytest.raises(Refusal) as caught:
        ServeSpec.from_json(data)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert words in caught.value.message
    side = Side(name="new", kind="serve", spec=data)
    with pytest.raises(Refusal):
        side.serve_spec()


def test_a_serving_spec_round_trips_through_its_json_form() -> None:
    spec = ServeSpec(image="img", ready=Ready(http="/ready", timeout_s=5), model_name="m")
    assert ServeSpec.from_json(spec.to_json()) == spec


def test_a_serving_side_is_made_with_the_default_readiness_check() -> None:
    side = Side.serve("new", "myorg/server:2.0", ["--model", "made-up-model"])
    spec = side.serve_spec()
    assert spec == ServeSpec(image="myorg/server:2.0", args=("--model", "made-up-model"))
    assert spec.ready.http == "/health"
    assert spec.ready.timeout_s == 900
    custom = Side.serve("new", "myorg/server:2.0", [], ready=Ready(http="/ready", timeout_s=30))
    assert custom.serve_spec().ready == Ready(http="/ready", timeout_s=30.0)


@pytest.mark.parametrize(
    "make",
    [
        lambda: Side.command("a", []),
        lambda: Side.command("a", "python bench.py"),  # type: ignore[arg-type]
        lambda: Side.python("a"),
        lambda: Side.python("a", interpreter="x", venv="y"),
        lambda: Side.files("a", [], format=None),
        lambda: Side.parse("a=image:x").serve_spec(),
    ],
)
def test_a_side_constructor_refuses_what_it_cannot_take(make: Any) -> None:
    with pytest.raises(Refusal) as caught:
        make()
    assert caught.value.code == "E_USAGE"


def test_a_twin_is_an_identical_copy_named_with_the_reserved_suffix() -> None:
    side = Side.image("new", "myorg/app:2.0").with_identity({"image_id": "sha256:aa"}, "ff" * 32)
    twin = side.twin()
    assert twin.name == "new~same"
    assert twin.role == "twin"
    assert twin.twin_of == "new"
    assert (twin.kind, twin.spec, twin.identity, twin.fingerprint) == (
        side.kind,
        side.spec,
        side.identity,
        side.fingerprint,
    )
    with pytest.raises(Refusal, match="is a twin and cannot have one"):
        twin.twin()


def test_the_twin_relation_is_the_declared_field_and_never_a_name() -> None:
    declared = Side(name="copy-of-new", kind="cmd", role="twin", twin_of="new")
    assert declared.twin_of == "new"
    with pytest.raises(Refusal) as by_name:
        Side(name="new~same", kind="cmd")
    assert by_name.value.code == "E_USAGE"
    with pytest.raises(Refusal, match="a twin, and only a twin, names twin_of"):
        Side(name="new", kind="cmd", role="twin")
    with pytest.raises(Refusal, match="a twin, and only a twin, names twin_of"):
        Side(name="new", kind="cmd", twin_of="old")


def test_the_identity_a_results_document_may_show() -> None:
    side = Side.image("new", "registry.example/org/app:2.0").with_identity(
        {
            "image_id": "sha256:" + "a" * 64,
            "digests": ("sha256:" + "b" * 64,),
            "platform": "os-a/arch-a",
            "prefix": "/made/up/prefix",
            "identify_output": "made-up output",
            "identify_sha256": "c" * 64,
            "machine_id": "0" * 32,
        },
        "ff" * 32,
    )
    assert side.public_identity() == {
        "image_id": "sha256:" + "a" * 64,
        "digests": ["sha256:" + "b" * 64],
        "platform": "os-a/arch-a",
        "identify_sha256": "c" * 64,
    }
    shown = side.for_results()
    assert shown.image_ref is None
    assert shown.to_json()["identity"] == side.public_identity()
    assert side.for_results(include_image_ref=True).image_ref == "registry.example/org/app:2.0"


def test_a_digest_is_shown_without_the_repository_it_was_pulled_from() -> None:
    side = Side.image("new", "registry.example/org/app:2.0").with_identity(
        {
            "image_id": "sha256:" + "a" * 64,
            "digests": (
                "registry.example/org/app@sha256:" + "b" * 64,
                "sha512:" + "c" * 128,
                "d" * 64,
            ),
        },
        "ff" * 32,
    )
    shown = side.for_results().to_json()
    assert shown["identity"]["digests"] == ["sha256:" + "b" * 64, "sha512:" + "c" * 128, "d" * 64]
    assert "registry.example" not in str(shown)


def test_a_value_that_is_no_hash_is_left_out_of_the_identity_shown() -> None:
    side = Side.image("new", "registry.example/org/app:2.0").with_identity(
        {
            "image_id": "registry.example/org/app:2.0",
            "digests": ("org/app:latest", "/made/up/path", 7, "sha256:" + "b" * 64),
            "packages_sha256": "/made/up/prefix/lib",
            "files_sha256": "not-a-list",
            "platform": 7,
            "python_version": "Python 0.0.0",
        },
        "ff" * 32,
    )
    assert side.public_identity() == {
        "digests": ["sha256:" + "b" * 64],
        "python_version": "Python 0.0.0",
    }
    assert side.for_results().identity == {
        "digests": ("sha256:" + "b" * 64,),
        "python_version": "Python 0.0.0",
    }


def test_an_image_side_needs_a_reference() -> None:
    with pytest.raises(Refusal, match="an image side needs an image reference") as caught:
        Side.image("new", "")
    assert caught.value.code == "E_USAGE"
    with pytest.raises(Refusal, match="a serving side needs an image reference") as caught:
        Side.serve("new", "", [])
    assert caught.value.code == "E_USAGE"


# ---------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------


def _two() -> tuple[Side, Side]:
    return Side.parse("new=image:myorg/app:2.0"), Side.parse("old=image:myorg/app:1.9")


def test_the_last_side_is_the_baseline_by_default() -> None:
    experiment = Experiment(sides=_two())
    assert experiment.baseline == "old"
    assert experiment.subjects == ("new",)
    assert [s.role for s in experiment.sides] == ["subject", "baseline"]


def test_a_named_baseline_is_kept() -> None:
    new, old = _two()
    experiment = Experiment(sides=(new.with_role("baseline"), old))
    assert experiment.baseline == "new"
    assert experiment.subjects == ("old",)


def test_the_defaults_of_an_experiment() -> None:
    experiment = Experiment(sides=_two())
    assert experiment.workload is None
    assert experiment.driver == "wall"
    assert experiment.run == RunSettings(rounds="auto", warmups=1, same_vs_same="on")
    assert experiment.gates.mode == "warn"
    assert experiment.gates.wait_quiet is False
    assert experiment.gates.lock_timeout_s == 1800.0
    assert (
        experiment.gates.quiet.max_busy_cores,
        experiment.gates.quiet.gpu_idle,
        experiment.gates.quiet.samples,
        experiment.gates.quiet.interval_s,
        experiment.gates.quiet.max_wait_s,
    ) == (1.0, None, 5, 2.0, 1800.0)
    assert experiment.gates.census.max_busy_cores == 0.5
    assert experiment.gates.discard.max_busy_cores == 2.0
    assert experiment.rule.name == "strict"
    assert experiment.rule.fail_on == ()
    assert experiment.cases.primary == ()
    assert experiment.cases.groups == {}
    assert (experiment.energy.enabled, experiment.energy.interval_s) == (False, 0.2)
    assert experiment.energy.min_samples == 10
    assert experiment.report.include_image_refs is False
    assert experiment.launch.engine == "auto"
    assert experiment.launch.pull == "missing"
    assert experiment.load == LoadSettings(levels=(), level_duration_s=None)
    assert experiment.load.level_kind == "concurrency"
    assert experiment.is_serving is False


def test_the_fields_of_an_experiment_come_in_the_order_of_the_data_model() -> None:
    assert [f.name for f in dataclasses.fields(Experiment)] == [
        "sides",
        "workload",
        "driver",
        "launch",
        "run",
        "gates",
        "rule",
        "cases",
        "energy",
        "report",
        "load",
        "controls",
        "launch_cost",
        "explain",
        "plots",
    ]
    new, old = _two()
    experiment = Experiment(
        (new, old),
        ("python", "bench.py"),
        "lines",
        LaunchSettings(cpus="4-7"),
        RunSettings(rounds=8),
        model.GateSettings(mode="enforce"),
        model.RuleSettings(fail_on=("worse",)),
        model.CaseSettings(primary=("mat*",)),
        model.EnergySettings(enabled=True),
        model.ReportSettings(include_image_refs=True),
    )
    assert experiment.cases.primary == ("mat*",)
    assert experiment.energy.enabled is True
    assert experiment.report.include_image_refs is True


@pytest.mark.parametrize(
    ("make", "words"),
    [
        (lambda: model.QuietSettings(samples=0), "QuietSettings.samples: expected at least 1"),
        (lambda: model.QuietSettings(interval_s=-1), "QuietSettings.interval_s: expected at least"),
        (lambda: model.QuietSettings(max_wait_s=-1), "QuietSettings.max_wait_s: expected at least"),
        (
            lambda: model.QuietSettings(max_busy_cores=-1),
            "QuietSettings.max_busy_cores: expected at least 0",
        ),
        (
            lambda: model.CensusSettings(max_busy_cores=-1),
            "CensusSettings.max_busy_cores: expected at least 0",
        ),
        (
            lambda: model.DiscardThresholds(max_gpu_other_processes=-1),
            "DiscardThresholds.max_gpu_other_processes: expected at least 0",
        ),
        (
            lambda: model.DiscardThresholds(max_gpu_throttle_events=-1),
            "DiscardThresholds.max_gpu_throttle_events: expected at least 0",
        ),
        (
            lambda: model.EnergySettings(interval_s=0),
            "EnergySettings.interval_s: expected more than 0",
        ),
        (
            lambda: model.EnergySettings(min_samples=1),
            "EnergySettings.min_samples: expected at least 2",
        ),
        (lambda: RunSettings(warmups=-1), "RunSettings.warmups: expected at least 0"),
        (lambda: RunSettings(budget_s=-1), "RunSettings.budget_s: expected at least 0"),
        (lambda: model.GateSettings(lock_timeout_s=-1), "GateSettings.lock_timeout_s: expected at"),
        (lambda: LaunchSettings(timeout_s=-1), "LaunchSettings.timeout_s: expected at least 0"),
        (lambda: LoadSettings(level_duration_s=-1), "LoadSettings.level_duration_s: expected at"),
        (lambda: Ready(timeout_s=-1), "Ready.timeout_s: expected at least 0"),
        (lambda: ServeSpec(image="img", port=0), "ServeSpec.port: expected at least 1"),
        (lambda: ServeSpec(image="img", port=70000), "ServeSpec.port: expected at most 65535"),
        (lambda: ServeSpec(image=""), "ServeSpec.image: expected a text of at least 1"),
        (lambda: model.RuleSettings(name=""), "RuleSettings.name: expected a text of at least 1"),
        (lambda: model.QuietSettings(max_wait_s=float("inf")), "expected a finite number"),
        (lambda: model.QuietSettings(samples=True), "QuietSettings.samples: expected a whole"),
    ],
)
def test_settings_keep_their_limits_however_they_are_made(make: Any, words: str) -> None:
    with pytest.raises(ValueError, match=words):
        make()


def test_an_experiment_needs_a_driver() -> None:
    with pytest.raises(ValueError, match=r"Experiment\.driver: expected a text of at least 1"):
        Experiment(sides=_two(), driver="")


def test_a_limit_is_one_of_the_known_words() -> None:
    assert model.LIMIT_WORDS == (
        "minimum",
        "exclusiveMinimum",
        "maximum",
        "exclusiveMaximum",
        "minLength",
        "pattern",
    )

    @dataclasses.dataclass(frozen=True)
    class Odd(model._Coerced):
        LIMITS = {"size": {"multipleOf": 2}}  # noqa: RUF012

        size: int = 0

    with pytest.raises(TypeError, match=r"Odd\.size: not a limit: multipleOf"):
        Odd()


def test_the_lineup_puts_each_twin_after_its_side() -> None:
    experiment = Experiment(sides=_two())
    assert [s.name for s in experiment.lineup()] == ["new", "new~same", "old", "old~same"]
    assert [s.twin_of for s in experiment.lineup()] == [None, "new", None, "old"]


def test_twins_can_be_turned_off_or_kept_for_named_sides() -> None:
    off = Experiment(sides=_two(), run=RunSettings(same_vs_same="off"))
    assert [s.name for s in off.lineup()] == ["new", "old"]
    assert off.twinned() == ()
    named = Experiment(sides=_two(), run=RunSettings(same_vs_same=("old",)))
    assert [s.name for s in named.lineup()] == ["new", "old", "old~same"]
    assert named.twinned() == ("old",)


@pytest.mark.parametrize(
    ("make", "words"),
    [
        (lambda: Experiment(sides=()), "at least one side"),
        (lambda: Experiment(sides=(_two()[0], _two()[0])), "side name given twice: new"),
        (lambda: Experiment(sides=(_two()[0], _two()[0].twin())), "a twin is never declared"),
        (
            lambda: Experiment(sides=tuple(s.with_role("baseline") for s in _two())),
            "more than one baseline: new, old",
        ),
        (
            lambda: Experiment(sides=(_two()[0], Side.parse("b=serve:myorg/server:1.0"))),
            "serve sides cannot be mixed",
        ),
        (
            lambda: Experiment(sides=(_two()[0], Side.parse("b=file:r-*.json"))),
            "file sides cannot be mixed",
        ),
        (
            lambda: Experiment(sides=_two(), run=RunSettings(same_vs_same=("nobody",))),
            "same_vs_same names no side: nobody",
        ),
        (
            lambda: Experiment(
                sides=_two(), launch=LaunchSettings(overrides={"nobody": {"cpus": "0"}})
            ),
            "launch overrides name no side: nobody",
        ),
    ],
)
def test_an_experiment_that_is_refused(make: Any, words: str) -> None:
    with pytest.raises(Refusal, match=words) as caught:
        make()
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_serving_sides_make_a_serving_experiment() -> None:
    sides = (Side.parse("new=serve:myorg/server:2.0"), Side.parse("old=serve:myorg/server:1.9"))
    assert Experiment(sides=sides).is_serving is True


# ---------------------------------------------------------------------------
# Launch settings
# ---------------------------------------------------------------------------


def test_a_side_override_merges_env_per_variable_and_replaces_every_other_key() -> None:
    shared = LaunchSettings(
        cpus="4-7",
        env={"OMP_NUM_THREADS": "4", "MODE": "shared"},
        mounts=("/data:/data",),
        env_pass=("HF_TOKEN",),
        overrides={"new": {"env": {"MODE": "own", "EXTRA": "1"}, "mounts": ("/other:/other",)}},
    )
    new, old = _two()
    for_new = shared.for_side(new)
    assert for_new.env == {"OMP_NUM_THREADS": "4", "MODE": "own", "EXTRA": "1"}
    assert for_new.mounts == ("/other:/other",)
    assert for_new.cpus == "4-7"
    assert for_new.env_pass == ("HF_TOKEN",)
    assert for_new.overrides == {}
    for_old = shared.for_side(old)
    assert for_old.env == {"OMP_NUM_THREADS": "4", "MODE": "shared"}
    assert for_old.mounts == ("/data:/data",)


def test_a_twin_gets_the_settings_of_the_side_it_copies() -> None:
    shared = LaunchSettings(overrides={"new": {"cpus": "0-3"}})
    new, _old = _two()
    assert shared.for_side(new.twin()).cpus == "0-3"


def test_the_fields_in_which_sides_differ_are_listed() -> None:
    shared = LaunchSettings(
        cpus="4-7",
        env={"A": "1"},
        overrides={"new": {"env": {"B": "2"}, "cpus": "4-7"}, "old": {"timeout_s": 60.0}},
    )
    assert shared.differences() == {"new": ("env",), "old": ("timeout_s",)}


def test_the_effective_settings_that_go_into_a_fingerprint() -> None:
    settings = LaunchSettings(
        cpus="4-7",
        gpus="0",
        memory="8g",
        env={"B": "2", "A": "1"},
        env_pass=("Z_TOKEN", "A_TOKEN"),
        mounts=("/data:/data",),
    )
    assert settings.effective(args=["--fast"], entrypoint="/run", env={"A": "own"}) == {
        "args": ["--fast"],
        "entrypoint": "/run",
        "env": {"A": "own", "B": "2"},
        "env_pass": ["A_TOKEN", "Z_TOKEN"],
        "mounts": ["/data:/data"],
        "limits": {"cpus": "4-7", "gpus": "0", "memory": "8g"},
        "perf_counters": False,
    }
    added = settings.effective(mounts=["/models/a:/models/a:ro"])
    assert added["mounts"] == ["/data:/data", "/models/a:/models/a:ro"]


@pytest.mark.parametrize(
    ("values", "words"),
    [
        ({"cpus": "four"}, "cpus is a list"),
        ({"cpus": "\u0664-\u0667"}, "cpus is a list"),
        ({"cpus": "0-100000000"}, "no CPU above 65535"),
        ({"cpus": "0,65536"}, "no CPU above 65535"),
        ({"cpus": "1" * 5000}, "no CPU above 65535"),
        ({"overrides": {"new": {"cpus": "0-100000000"}}}, "no CPU above 65535"),
        ({"overrides": {"old": {"gpus": "\u0660"}}}, "gpus is 'all' or a comma list"),
        ({"gpus": "some"}, "gpus is 'all' or a comma list"),
        ({"gpus": "\u0660"}, "gpus is 'all' or a comma list"),
        ({"gpus": "0,\uff11"}, "gpus is 'all' or a comma list"),
        ({"overrides": {"new": {"allow_identical": True}}}, "cannot override allow_identical"),
        ({"engine": "made_up"}, "one of 'auto', 'docker', 'podman'"),
        ({"pull": "sometimes"}, "one of 'missing', 'never', 'always'"),
    ],
)
def test_launch_settings_that_are_refused(values: dict[str, Any], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        LaunchSettings(**values)


def test_the_highest_cpu_number_is_accepted() -> None:
    assert model.MAX_CPU == 65535
    assert LaunchSettings(cpus="65530-65535").cpus == "65530-65535"
    assert LaunchSettings(cpus="0,065535").cpus == "0,065535"


# ---------------------------------------------------------------------------
# Load levels
# ---------------------------------------------------------------------------


def test_load_levels_are_labelled_by_what_a_level_counts() -> None:
    concurrent = LoadSettings(levels=(1, 8, 32), level_duration_s=60.0)
    assert concurrent.level_kind == "concurrency"
    assert concurrent.labels() == ("c1", "c8", "c32")
    assert concurrent.highest() == "c32"
    rate = LoadSettings(levels=(32, 1, 8), level_kind="rate")
    assert rate.labels() == ("r32", "r1", "r8")
    assert rate.highest() == "r32"
    assert LoadSettings().highest() is None


@pytest.mark.parametrize(
    "values", [{"levels": (0,)}, {"levels": (8, 8)}, {"level_kind": "made_up"}]
)
def test_load_settings_that_are_refused(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        LoadSettings(**values)


# ---------------------------------------------------------------------------
# Which cases are primary and how they are grouped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "patterns", "expected"),
    [
        ("matmul", ["matmul"], True),
        ("matmul", ["mat*"], True),
        ("matmul", ["*"], True),
        ("matmul", ["fft", "mat???"], True),
        ("matmul", ["Mat*"], False),
        ("matmul", ["fft"], False),
        ("matmul", [], False),
        ("c32/ttft_ms_median", ["c32/*"], True),
        ("c32/ttft_ms_median", ["*/ttft_ms_*"], True),
        ("c32/tokens_per_joule[gpu]", ["c32/tokens_per_joule[gpu]"], True),
        ("energy_j[gpu]", ["energy_j[gpu]"], True),
        ("energy_jg", ["energy_j[gpu]"], True),
        ("energy_jx", ["energy_j[gpu]"], False),
        ("BM_Sort/1024", ["BM_Sort/[0-9]*"], True),
    ],
)
def test_a_case_id_against_patterns(case: str, patterns: list[str], expected: bool) -> None:
    assert model.case_matches(case, patterns) is expected


def test_the_patterns_of_the_config_decide_which_cases_are_primary() -> None:
    settings = model.CaseSettings(primary=("mat*", "c32/tokens_per_joule[gpu]"))
    assert settings.is_primary("matmul", default=["fft"]) is True
    assert settings.is_primary("fft", default=["fft"]) is False
    assert settings.is_primary("c32/tokens_per_joule[gpu]", default=[]) is True


def test_without_patterns_the_driver_decides_which_cases_are_primary() -> None:
    settings = model.CaseSettings()
    assert settings.is_primary("matmul", default=["matmul"]) is True
    assert settings.is_primary("fft", default=["matmul"]) is False
    assert settings.is_primary("matmul", default=[]) is False


def test_a_case_belongs_to_the_first_group_that_matches_it() -> None:
    settings = model.CaseSettings(groups={"sorting": ("BM_Sort*",), "all": ("*",)})
    assert settings.group_of("BM_Sort/1024") == "sorting"
    assert settings.group_of("matmul") == "all"
    assert model.CaseSettings(groups={"sorting": ("BM_Sort*",)}).group_of("matmul") is None
    assert model.CaseSettings().group_of("matmul") is None


# ---------------------------------------------------------------------------
# The rule and supplied floors
# ---------------------------------------------------------------------------


def test_the_shipped_rule_is_strict() -> None:
    assert dataclasses.asdict(STRICT) == {
        "name": "strict",
        "scale": "ratio",
        "floor_scope": "group",
        "bar": "sum_of_both",
        "bar_round_digits": None,
        "require_both_floors": True,
        "p_source": "corrected",
        "alpha": 0.05,
        "p_inclusive": False,
        "gap_inclusive": False,
        "tie": "inside_and_not_significant",
        "min_rounds": None,
    }
    assert STRICT.to_json() == dataclasses.asdict(STRICT)
    assert Rule.from_json(STRICT.to_json()) == STRICT


def test_a_rule_takes_every_option() -> None:
    rule = Rule(
        "lenient",
        scale="percent",
        floor_scope="experiment",
        bar="twice_experiment_max",
        bar_round_digits=1,
        require_both_floors=False,
        p_source="raw",
        alpha=0.01,
        p_inclusive=True,
        gap_inclusive=True,
        tie="never",
        min_rounds=12,
    )
    assert rule.unit == "percent"
    assert STRICT.unit == "fraction"
    assert Rule.from_json(rule.to_json()) == rule


@pytest.mark.parametrize(
    "values",
    [
        {"scale": "log"},
        {"floor_scope": "world"},
        {"bar": "none"},
        {"p_source": "guess"},
        {"tie": "always"},
        {"alpha": 0.0},
        {"alpha": 1.0},
        {"bar_round_digits": -1},
        {"min_rounds": 0},
    ],
)
def test_a_rule_refuses_an_option_it_does_not_know(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Rule("made-up", **values)


def test_supplied_floors_are_one_value_or_one_per_side() -> None:
    assert Floors(0.012).for_side("new") == 0.012
    per_side = Floors({"new": 0.012, "old": 0.007})
    assert per_side.for_side("new") == 0.012
    assert per_side.for_side("old") == 0.007
    assert per_side.for_side("other") is None
    with pytest.raises(ValueError, match="a floor is a number of zero or more"):
        Floors(-0.1)
    with pytest.raises(ValueError, match=r"Floors\.value\.new: expected a finite number"):
        Floors({"new": float("nan")})
    with pytest.raises(ValueError, match="expected a finite number"):
        Floors(float("inf"))


def test_the_unit_of_a_floor_follows_the_scale_of_the_rule() -> None:
    assert model.FLOOR_UNITS == {"ratio": "fraction", "percent": "percent"}


# ---------------------------------------------------------------------------
# The config form
# ---------------------------------------------------------------------------


def test_the_example_config_becomes_an_experiment(example_config: dict[str, Any]) -> None:
    experiment = Experiment.from_json(example_config)
    assert [(s.name, s.kind, s.role) for s in experiment.sides] == [
        ("new", "image", "subject"),
        ("old", "image", "baseline"),
    ]
    assert experiment.sides[0].spec["image"] == "myorg/app:2.0"
    assert experiment.workload == ("python", "bench.py")
    assert experiment.driver == "lines"
    assert experiment.run.rounds == "auto"
    assert experiment.run.warmups == 1
    assert experiment.run.same_vs_same == "on"
    assert experiment.launch.cpus == "4-7"
    assert experiment.launch.env == {"OMP_NUM_THREADS": "4"}
    assert experiment.launch.env_pass == ("HF_TOKEN",)
    assert experiment.launch.timeout_s == 600.0
    assert experiment.gates.mode == "warn"
    assert experiment.rule.name == "strict"
    assert experiment.cases.primary == ("*",)
    assert experiment.energy.enabled is False
    assert experiment.report.include_image_refs is False


def test_a_config_survives_a_round_trip(example_config: dict[str, Any]) -> None:
    experiment = Experiment.from_json(example_config)
    written = experiment.to_json()
    assert Experiment.from_json(written) == experiment
    assert Experiment.from_json(written).to_json() == written
    assert written["launch"]["timeout"] == 600.0
    assert written["sides"]["old"]["baseline"] is True
    assert "baseline" not in written["sides"]["new"]


def test_the_spec_of_a_plug_in_side_kind_survives_a_round_trip(
    example_config: dict[str, Any],
) -> None:
    experiment = Experiment.from_json(example_config)
    spec = {"spec": "fast", "level": 3, "tags": ["a", "b"], "table": {"k": "v"}}
    plug_in = Side(name="new", kind="made-up-kind", spec=spec)
    sides = tuple(plug_in if s.name == "new" else s for s in experiment.sides)
    experiment = dataclasses.replace(experiment, sides=sides)
    written = experiment.to_json()
    assert written["sides"]["new"] == {"kind": "made-up-kind", "spec": spec}
    back = Experiment.from_json(written)
    assert back.side("new") == plug_in
    assert back.to_json()["sides"]["new"] == {"kind": "made-up-kind", "spec": spec}


def test_a_plug_in_side_kind_given_one_text_keeps_the_text_form(
    example_config: dict[str, Any],
) -> None:
    config = {**example_config, "sides": {**example_config["sides"]}}
    config["sides"]["new"] = {"kind": "made-up-kind", "spec": "fast"}
    experiment = Experiment.from_json(config)
    assert experiment.side("new").spec == {"spec": "fast"}
    assert experiment.to_json()["sides"]["new"] == {"kind": "made-up-kind", "spec": "fast"}


@pytest.mark.parametrize("spec", [3, ["a"], True, {"spec": {1, 2}}])
def test_a_plug_in_side_spec_that_is_neither_text_nor_a_table_is_refused(
    example_config: dict[str, Any], spec: Any
) -> None:
    config = {**example_config, "sides": {**example_config["sides"]}}
    config["sides"]["new"] = {"kind": "made-up-kind", "spec": spec}
    with pytest.raises(Refusal) as caught:
        Experiment.from_json(config)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2
    assert "sides.new.spec must be a text or a table of plain values" in caught.value.message


def test_the_serving_config_becomes_an_experiment(example_serving_config: dict[str, Any]) -> None:
    experiment = Experiment.from_json(example_serving_config)
    assert experiment.is_serving is True
    assert experiment.driver == "guidellm"
    assert experiment.load == LoadSettings(
        levels=(1, 8, 32), level_duration_s=60.0, level_kind="concurrency"
    )
    new = experiment.side("new").serve_spec()
    assert (new.image, new.args, new.port) == (
        "myorg/server:2.0",
        ("--model", "made-up-model"),
        8000,
    )
    assert new.ready == Ready(http="/health", timeout_s=900.0)
    assert Experiment.from_json(experiment.to_json()) == experiment


def test_a_level_can_count_requests_per_second(example_serving_config: dict[str, Any]) -> None:
    example_serving_config["workload"]["level_kind"] = "rate"
    experiment = Experiment.from_json(example_serving_config)
    assert experiment.load.labels() == ("r1", "r8", "r32")
    assert experiment.to_json()["workload"]["level_kind"] == "rate"


@pytest.mark.parametrize(
    ("given", "levels"), [("1,8,32", (1, 8, 32)), (" 1, 8 ", (1, 8)), (8, (8,)), ([4, 2], (4, 2))]
)
def test_load_levels_are_read_from_a_list_a_number_or_a_comma_text(
    example_serving_config: dict[str, Any], given: Any, levels: tuple[int, ...]
) -> None:
    example_serving_config["workload"]["levels"] = given
    assert Experiment.from_json(example_serving_config).load.levels == levels


@pytest.mark.parametrize(
    ("path", "value", "words"),
    [
        (("run", "made_up"), 1, "unknown config key: run.made_up"),
        (("made_up",), {}, "unknown config key: made_up"),
        (("sides", "new", "made_up"), 1, "unknown config key: sides.new.made_up"),
        (("launch", "made_up"), 1, "unknown config key: launch.made_up"),
        (("rule", "alpha"), 0.01, "unknown config key: rule.alpha"),
        (("run", "rounds"), 0, "run.rounds must be 'auto' or a whole number of at least 1"),
        (("run", "warmups"), "one", "run.warmups must be a whole number"),
        (("launch", "timeout"), "soon", "launch.timeout must be a duration"),
        (("gates", "mode"), "strict", "gates.mode must be one of off, warn, enforce"),
        (("rule", "fail_on"), ["sometimes"], "rule.fail_on must be one of"),
        (
            ("workload", "level_kind"),
            "speed",
            "workload.level_kind must be one of concurrency, rate",
        ),
        (("workload", "levels"), [0], "workload.levels must be a list of whole numbers"),
        (("launch", "cpus"), "four", "launch.cpus must be a CPU list"),
        (("launch", "cpus"), "\u0664-\u0667", "launch.cpus must be a CPU list"),
        (("launch", "cpus"), "0-65536", "launch.cpus must be a CPU list .* no CPU above 65535"),
        (("launch", "gpus"), "\u0660", "launch.gpus must be 'all' or a comma list"),
        (("launch", "timeout"), "\u0663m", "launch.timeout must be a duration"),
        (("sides", "new", "cmd"), "python x.py", "sides.new needs exactly one of"),
    ],
)
def test_a_bad_config_is_refused_with_the_key_named(
    example_config: dict[str, Any], path: tuple[str, ...], value: Any, words: str
) -> None:
    table = example_config
    for part in path[:-1]:
        table = table.setdefault(part, {})
    table[path[-1]] = value
    with pytest.raises(Refusal, match=words) as caught:
        Experiment.from_json(example_config)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2


def test_an_unknown_key_is_listed_in_the_detail(example_config: dict[str, Any]) -> None:
    example_config["run"]["made_up"] = 1
    with pytest.raises(Refusal) as caught:
        Experiment.from_json(example_config)
    assert caught.value.detail == {"unknown": ["run.made_up"]}


def test_a_config_without_sides_is_refused() -> None:
    with pytest.raises(Refusal, match="the config declares no side") as caught:
        Experiment.from_json({"run": {"rounds": 8}})
    assert caught.value.code == "E_CONFIG"


def test_credential_values_are_redacted_in_the_resolved_config(
    example_config: dict[str, Any],
) -> None:
    example_config["launch"]["env"] = {"API_KEY": "made-up-value", "OMP_NUM_THREADS": "4"}
    example_config["sides"]["new"]["env"] = {"DB_PASSWORD": "made-up-value"}
    experiment = Experiment.from_json(example_config)
    written = experiment.to_json()
    assert written["launch"]["env"] == {"API_KEY": "<redacted>", "OMP_NUM_THREADS": "4"}
    assert written["sides"]["new"]["env"] == {"DB_PASSWORD": "<redacted>"}
    assert "made-up-value" not in repr(written)
    assert experiment.to_json(redact=False)["launch"]["env"]["API_KEY"] == "made-up-value"


def test_a_side_override_in_the_config(example_config: dict[str, Any]) -> None:
    example_config["sides"]["new"]["launch"] = {"env": {"EXTRA": "1"}, "timeout": "90s"}
    experiment = Experiment.from_json(example_config)
    merged = experiment.launch.for_side(experiment.side("new"))
    assert merged.env == {"OMP_NUM_THREADS": "4", "EXTRA": "1"}
    assert merged.timeout_s == 90.0
    assert experiment.launch.for_side(experiment.side("old")).timeout_s == 600.0
    assert experiment.launch.differences() == {"new": ("env", "timeout_s")}
    assert experiment.to_json()["sides"]["new"]["launch"] == {
        "env": {"EXTRA": "1"},
        "timeout": 90.0,
    }


# ---------------------------------------------------------------------------
# Config keys as dotted paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "key", "parts"),
    [
        ("run.rounds", "run.rounds", ("run", "rounds")),
        ("workload.level_kind", "workload.level_kind", ("workload", "level_kind")),
        ("workload.levels", "workload.levels", ("workload", "levels")),
        ("sides.new.image", "sides.NAME.image", ("sides", "new", "image")),
        ("sides.v2.0.image", "sides.NAME.image", ("sides", "v2.0", "image")),
        (
            "sides.new.serve.ready.timeout",
            "sides.NAME.serve.ready.timeout",
            ("sides", "new", "serve", "ready", "timeout"),
        ),
        ("sides.new.launch.cpus", "sides.NAME.launch.cpus", ("sides", "new", "launch", "cpus")),
        ("launch.env", "launch.env", ("launch", "env")),
        ("launch.env.OMP_NUM_THREADS", "launch.env", ("launch", "env", "OMP_NUM_THREADS")),
        (
            "sides.new.launch.env.MODE",
            "sides.NAME.launch.env",
            ("sides", "new", "launch", "env", "MODE"),
        ),
        ("cases.groups.sorting", "cases.groups.NAME", ("cases", "groups", "sorting")),
        (
            "gates.quiet.max_busy_cores",
            "gates.quiet.max_busy_cores",
            ("gates", "quiet", "max_busy_cores"),
        ),
        (
            "report.include_image_refs",
            "report.include_image_refs",
            ("report", "include_image_refs"),
        ),
    ],
)
def test_a_dotted_path_names_a_config_key(path: str, key: str, parts: tuple[str, ...]) -> None:
    assert model.match_config_key(path) == (key, parts)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "run",
        "run.made_up",
        "run.rounds.more",
        "sides.new",
        "sides..image",
        "launch.cpus.more",
        "rule.alpha",
        "workload.level-kind",
        "Run.rounds",
    ],
)
def test_a_dotted_path_that_names_no_config_key_is_refused(path: str) -> None:
    with pytest.raises(Refusal) as caught:
        model.match_config_key(path)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2
    assert caught.value.detail == {"unknown": [path]}


def test_every_config_key_names_itself() -> None:
    assert len(set(model.CONFIG_KEYS)) == len(model.CONFIG_KEYS)
    for key in model.CONFIG_KEYS:
        path = key.replace("NAME", "chosen")
        assert model.match_config_key(path) == (key, tuple(path.split(".")))
    assert set(model.CONFIG_TABLE_KEYS) <= set(model.CONFIG_KEYS)


def test_the_documented_config_keys_exist() -> None:
    for key in (
        "workload.level_kind",
        "workload.levels",
        "workload.level_duration",
        "run.quick",
        "run.budget",
        "run.rounds_exact",
        "run.allow_underpowered",
        "run.out",
        "launch.allow_identical",
        "gates.wait_quiet",
        "gates.locks",
        "gates.lock_timeout",
        "rule.fail_on",
        "cases.primary",
        "cases.groups.NAME",
        "launch.cpus",
        "launch.gpus",
        "launch.memory",
        "launch.env",
        "launch.env_pass",
        "launch.mounts",
        "launch.workdir",
        "launch.network",
        "launch.timeout",
        "launch.engine",
        "launch.pull",
        "launch.identify",
        "sides.NAME.serve.launcher",
        "sides.NAME.serve.command",
    ):
        assert key in model.CONFIG_KEYS, key
