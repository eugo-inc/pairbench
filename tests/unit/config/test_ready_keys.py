# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The keys of the readiness checks: ``gates.stop_file``, ``gates.min_gpu_free_mib``
and ``gates.check_locks``, read from the file, the environment and ``--set``,
refused when bad, and left out of the recorded config when not set.
"""

from __future__ import annotations

import pytest

from pairbench import config, model
from pairbench.errors import Refusal

TWO_SIDES = ("new=cmd:python bench.py --variant b", "old=cmd:python bench.py --variant a")
# The keys of the gates table before the readiness checks, which a config that
# sets none of them still records, and nothing else.
GATE_KEYS = {
    "mode",
    "wait_quiet",
    "locks",
    "lock_timeout",
    "allow_mixed_core_types",
    "quiet",
    "census",
    "discard",
}
# The config hash of the two sides above with every default, as written in a
# capture header by a build that cannot name the readiness keys.
DEFAULT_SHA256 = "468665ed0dc0504e794d001655f70bf688b90860742c841d5a5f0b92f0715175"


def _load(sets: list[str] | None = None, environ: dict[str, str] | None = None) -> model.Experiment:
    flags = config.flag_config({}, sides=TWO_SIDES)
    return config.load_experiment(environ=environ or {}, flags=flags, sets=sets or [])


def _refused(sets: list[str]) -> Refusal:
    with pytest.raises(Refusal) as caught:
        _load(sets)
    assert caught.value.code == "E_CONFIG"
    assert caught.value.exit_code == 2
    return caught.value


def test_the_readiness_checks_are_off_by_default() -> None:
    gates = _load().gates
    assert gates.stop_file is None
    assert gates.min_gpu_free_mib is None
    assert gates.check_locks == ()


def test_a_config_that_sets_none_records_the_gates_table_it_always_did() -> None:
    recorded = _load().to_json()
    assert set(recorded["gates"]) == GATE_KEYS


def test_a_config_that_sets_none_keeps_its_config_hash() -> None:
    experiment = _load()
    assert model.config_sha256(experiment.to_json()) == DEFAULT_SHA256


def test_the_three_keys_are_read_from_set() -> None:
    gates = _load(
        [
            "gates.stop_file=made-up/hold.stop",
            "gates.min_gpu_free_mib=2000",
            'gates.check_locks=["made-up/a.lock", "made-up/b.lock"]',
        ]
    ).gates
    assert gates.stop_file == "made-up/hold.stop"
    assert gates.min_gpu_free_mib == 2000.0
    assert gates.check_locks == ("made-up/a.lock", "made-up/b.lock")


def test_the_three_keys_are_read_from_the_environment() -> None:
    gates = _load(
        environ={
            "PAIRBENCH__GATES__STOP_FILE": "made-up/hold.stop",
            "PAIRBENCH__GATES__MIN_GPU_FREE_MIB": "1500.5",
            "PAIRBENCH__GATES__CHECK_LOCKS": '["made-up/a.lock"]',
        }
    ).gates
    assert gates.stop_file == "made-up/hold.stop"
    assert gates.min_gpu_free_mib == 1500.5
    assert gates.check_locks == ("made-up/a.lock",)


def test_a_set_key_is_recorded_and_enters_the_config_hash() -> None:
    experiment = _load(
        [
            "gates.stop_file=made-up/hold.stop",
            "gates.min_gpu_free_mib=2000",
            'gates.check_locks=["made-up/a.lock"]',
        ]
    )
    gates = experiment.to_json()["gates"]
    assert gates["stop_file"] == "made-up/hold.stop"
    assert gates["min_gpu_free_mib"] == 2000.0
    assert gates["check_locks"] == ["made-up/a.lock"]
    assert model.config_sha256(experiment.to_json()) != DEFAULT_SHA256
    again = model.Experiment.from_json(experiment.to_json(redact=False))
    assert again.gates == experiment.gates


@pytest.mark.parametrize(
    ("sets", "message"),
    [
        (["gates.stop_file="], "gates.stop_file must be a text that is not empty"),
        (["gates.stop_file=7"], "gates.stop_file must be a text that is not empty"),
        (["gates.stop_file=true"], "gates.stop_file must be a text that is not empty"),
        (['gates.stop_file="made-up\\u0000x"'], "gates.stop_file must not hold a NUL character"),
        (["gates.min_gpu_free_mib=0"], "gates.min_gpu_free_mib: expected more than 0, got 0.0"),
        (["gates.min_gpu_free_mib=-5"], "gates.min_gpu_free_mib: expected more than 0, got -5.0"),
        (["gates.min_gpu_free_mib=lots"], "gates.min_gpu_free_mib must be a number"),
        (["gates.min_gpu_free_mib=nan"], "gates.min_gpu_free_mib must be a number"),
        (["gates.min_gpu_free_mib=true"], "gates.min_gpu_free_mib must be a number"),
        (
            ["gates.check_locks=made-up/a.lock"],
            "gates.check_locks must be a list of texts that are not empty",
        ),
        (
            ['gates.check_locks=["made-up/a.lock", ""]'],
            "gates.check_locks must be a list of texts that are not empty",
        ),
        (["gates.check_locks=[1]"], "gates.check_locks must be a list of texts that are not empty"),
        (
            ['gates.check_locks=["made-up\\u0000x"]'],
            "gates.check_locks must not hold a NUL character",
        ),
    ],
    ids=[
        "stop-empty",
        "stop-number",
        "stop-bool",
        "stop-nul",
        "floor-zero",
        "floor-negative",
        "floor-text",
        "floor-nan",
        "floor-bool",
        "locks-text",
        "locks-empty-entry",
        "locks-number",
        "locks-nul",
    ],
)
def test_bad_values_are_refused(sets: list[str], message: str) -> None:
    assert _refused(sets).message == message


@pytest.mark.parametrize(
    ("locks", "check"),
    [
        ('["made-up/a.lock"]', '["made-up/a.lock"]'),
        ('["made-up/a.lock"]', '["made-up/./a.lock"]'),
        ('["made-up//a.lock"]', '["made-up/a.lock"]'),
        ('["made-up/b.lock", "made-up/a.lock"]', '["made-up/c.lock", "made-up/.//a.lock"]'),
        ('["/made-up/a.lock"]', '["//made-up///./a.lock"]'),
    ],
    ids=["same", "dot", "double-slash", "second-entry", "leading-slashes"],
)
def test_a_check_only_lock_the_run_also_takes_is_refused(locks: str, check: str) -> None:
    refusal = _refused([f"gates.locks={locks}", f"gates.check_locks={check}"])
    place = 2 if "c.lock" in check else 1
    assert refusal.message == (
        f"gates.check_locks entry {place} is also in gates.locks: the run holds that lock "
        "itself during the re-check; keep it in one of the two lists"
    )


@pytest.mark.parametrize(
    "check",
    ["made-up/sub/../a.lock", "made-up/a.lock/..", "sub/../made-up/a.lock"],
)
def test_a_check_only_lock_through_a_parent_part_is_not_refused(check: str) -> None:
    # A link before '..' changes what the path names, so the text alone cannot
    # say it is the same file; the check itself tells at check time.
    gates = _load(['gates.locks=["made-up/a.lock"]', f'gates.check_locks=["{check}"]']).gates
    assert gates.check_locks == (check,)


@pytest.mark.parametrize(
    ("lock", "check"),
    [
        ("made-up/a.lock", "/made-up/a.lock"),
        ("/made-up/a.lock", "made-up/a.lock"),
        ("made-up/a.lock", "//made-up/./a.lock"),
    ],
    ids=["absolute-check-only", "absolute-run-lock", "absolute-folded"],
)
def test_an_absolute_and_a_relative_path_are_two_locks(lock: str, check: str) -> None:
    # The text alone cannot say which folder a relative path is read from, so a relative
    # path and an absolute one are two locks here.
    gates = _load([f'gates.locks=["{lock}"]', f'gates.check_locks=["{check}"]']).gates
    assert gates.locks == (lock,)
    assert gates.check_locks == (check,)


def test_different_locks_in_the_two_lists_are_accepted() -> None:
    gates = _load(['gates.locks=["made-up/a.lock"]', 'gates.check_locks=["made-up/b.lock"]']).gates
    assert gates.locks == ("made-up/a.lock",)
    assert gates.check_locks == ("made-up/b.lock",)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"stop_file": ""},
            "GateSettings.stop_file: expected a text of at least 1 characters, got ''",
        ),
        ({"stop_file": "made-up\0x"}, "gates.stop_file must not hold a NUL character"),
        ({"check_locks": ("",)}, "gates.check_locks must be a list of texts that are not empty"),
        (
            {"check_locks": ("made-up/a.lock", "")},
            "gates.check_locks must be a list of texts that are not empty",
        ),
        ({"check_locks": ("made-up\0x",)}, "gates.check_locks must not hold a NUL character"),
    ],
    ids=["stop-empty", "stop-nul", "locks-empty", "locks-second-empty", "locks-nul"],
)
def test_gate_settings_built_in_python_refuse_bad_readiness_values(
    fields: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError) as caught:
        model.GateSettings(**fields)  # type: ignore[arg-type]
    assert str(caught.value) == message


def test_gate_settings_built_in_python_keep_the_same_rules() -> None:
    with pytest.raises(ValueError, match=r"GateSettings\.min_gpu_free_mib"):
        model.GateSettings(min_gpu_free_mib=0.0)
    with pytest.raises(ValueError, match=r"also in gates\.locks"):
        model.GateSettings(locks=("made-up/a.lock",), check_locks=("made-up/a.lock",))
