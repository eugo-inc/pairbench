# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The load levels and level length a serving experiment gets when the config names none."""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import config
from pairbench.model import Experiment
from pairbench.plan import build_plan, format_plan

SERVING = """
[workload]
driver = "{driver}"
{workload}

[sides.new.serve]
image = "registry.example/server:2"

[sides.old.serve]
image = "registry.example/server:1"
"""


def _load(tmp_path: Path, *, driver: str = "guidellm", workload: str = "") -> Experiment:
    path = tmp_path / "pairbench.toml"
    path.write_text(SERVING.format(driver=driver, workload=workload), encoding="utf-8")
    return config.load_experiment(path, environ={})


def test_a_serving_experiment_without_levels_gets_three_levels_of_sixty_seconds(
    tmp_path: Path,
) -> None:
    experiment = _load(tmp_path)
    assert experiment.load.levels == (1, 8, 32)
    assert experiment.load.level_duration_s == 60.0
    assert experiment.load.level_kind == "concurrency"


def test_levels_and_a_length_the_config_names_are_kept(tmp_path: Path) -> None:
    experiment = _load(tmp_path, workload='levels = [2, 4]\nlevel_duration = "15s"')
    assert experiment.load.levels == (2, 4)
    assert experiment.load.level_duration_s == 15.0


def test_named_levels_get_the_default_length_and_a_named_length_the_default_levels(
    tmp_path: Path,
) -> None:
    assert _load(tmp_path, workload="levels = [4]").load.level_duration_s == 60.0
    assert _load(tmp_path, workload='level_duration = "15s"').load.levels == (1, 8, 32)


def test_a_load_counted_in_prompts_gets_the_levels_and_no_length(tmp_path: Path) -> None:
    experiment = _load(tmp_path, driver="vllm-bench")
    assert experiment.load.levels == (1, 8, 32)
    assert experiment.load.level_duration_s is None


def test_levels_of_requests_per_second_have_no_default(tmp_path: Path) -> None:
    experiment = _load(tmp_path, workload='level_kind = "rate"')
    assert experiment.load.levels == ()


def test_an_experiment_that_does_not_serve_gets_no_levels(tmp_path: Path) -> None:
    path = tmp_path / "pairbench.toml"
    path.write_text(
        '[sides.new]\ncmd = ["./new"]\n\n[sides.old]\ncmd = ["./old"]\n', encoding="utf-8"
    )
    experiment = config.load_experiment(path, environ={})
    assert experiment.load.levels == ()
    assert experiment.load.level_duration_s is None


@pytest.mark.parametrize(
    ("workload", "line"),
    [
        (
            "",
            "# serving load per launch: levels c1, c8, c32 of 60 s each, about 3 min; about 96 min "
            "for the 32 launches of the rounds, besides the server starts\n",
        ),
        (
            'levels = [2, 4]\nlevel_duration = "90s"',
            "# serving load per launch: levels c2, c4 of 90 s each, about 3 min; about 96 min "
            "for the 32 launches of the rounds, besides the server starts\n",
        ),
    ],
)
def test_the_plan_prints_how_long_the_load_runs(tmp_path: Path, workload: str, line: str) -> None:
    experiment = _load(tmp_path, workload=workload)
    text = format_plan(build_plan(experiment), experiment)
    assert line in text


def test_the_plan_says_a_load_counted_in_prompts_has_no_known_length(tmp_path: Path) -> None:
    experiment = _load(tmp_path, driver="vllm-bench")
    text = format_plan(build_plan(experiment), experiment)
    assert (
        "# serving load per launch: levels c1, c8, c32; each level sends its number of "
        "prompts, so its length is not known before the run\n"
    ) in text


def test_the_plan_counts_the_load_of_the_positive_control_twice(tmp_path: Path) -> None:
    experiment = _load(
        tmp_path, workload='levels = [2]\nlevel_duration = "30s"\n[controls]\npositive = "on"'
    )
    plan = build_plan(experiment)
    assert plan.control is not None
    text = format_plan(plan, experiment)
    launches = plan.rounds_planned * (len(plan.lineup) + 1)
    assert (
        f"# serving load per launch: levels c2 of 30 s each, about 30 s; about 24 min for the "
        f"{launches} launches of the rounds, counting the load twice in each launch of the "
        "positive control, besides the server starts\n"
    ) in text


def _load_warning(side: str) -> str:
    return (
        f"# warning: launch.timeout of side {side} is 100 s, shorter than its serving load of "
        "about 3 min; its launches will time out\n"
    )


@pytest.mark.parametrize(
    ("launch", "control", "warnings"),
    [
        ('[launch]\ntimeout = "100s"', "off", [_load_warning("new"), _load_warning("old")]),
        ('[sides.old.launch]\ntimeout = "100s"', "off", [_load_warning("old")]),
        (
            '[launch]\ntimeout = "5m"',
            "on",
            [
                "# warning: launch.timeout of side old is 5 min, shorter than the load of about "
                "6 min that a launch of its positive control runs; those launches will time out\n"
            ],
        ),
    ],
    ids=["shared", "own", "control"],
)
def test_the_plan_warns_when_a_launch_timeout_is_shorter_than_the_serving_load(
    tmp_path: Path, launch: str, control: str, warnings: list[str]
) -> None:
    workload = f'[controls]\npositive = "{control}"\n{launch}'
    experiment = _load(tmp_path, workload=workload)
    text = format_plan(build_plan(experiment), experiment)
    lines = text.splitlines(keepends=True)
    assert [line for line in lines if line.startswith("# warning: launch.timeout")] == warnings


def test_the_plan_gives_no_timeout_warning_when_the_load_fits(tmp_path: Path) -> None:
    experiment = _load(tmp_path, workload='[controls]\npositive = "on"\n[launch]\ntimeout = "7m"')
    text = format_plan(build_plan(experiment), experiment)
    assert "launch.timeout" not in text
