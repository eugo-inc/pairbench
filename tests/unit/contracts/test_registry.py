# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Plug-in loading and lookup."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model, registry
from pairbench.errors import Refusal
from pairbench.model import STRICT, PluginCounts, Rule

REPO = Path(__file__).resolve().parents[3]

GROUPS = (
    "pairbench.side_kinds",
    "pairbench.drivers",
    "pairbench.capture_readers",
    "pairbench.gates",
    "pairbench.rules",
    "pairbench.reporters",
    "pairbench.launchers",
)

BUILTIN_NAMES: dict[str, tuple[str, ...]] = {
    "pairbench.side_kinds": ("cmd", "image", "python", "venv", "conda", "serve", "file"),
    "pairbench.drivers": (
        "wall",
        "lines",
        "gbench",
        "nvbench",
        "pytest-benchmark",
        "hyperfine",
        "perf",
        "llama-bench",
        "guidellm",
        "aiperf",
        "vllm-bench",
    ),
    "pairbench.capture_readers": ("jsonl", "text"),
    "pairbench.gates": ("cpus", "quiet", "census", "stop_file", "gpu_memory", "check_locks"),
    "pairbench.rules": ("strict",),
    "pairbench.reporters": ("terminal", "markdown", "json", "html"),
    "pairbench.launchers": ("docker", "podman", "host"),
}


class MadeUpDriver:
    name = "made-up"
    api_version = 1
    where = "in_side"

    def prepare(self, ctx: Any, argv: list[str]) -> Any:
        return argv

    def read(self, ctx: Any, artifacts: Path) -> list[Any]:
        return []

    def default_primary(self, samples: list[Any]) -> list[str]:
        return []


class MadeUpRule:
    name = "made-up"
    api_version = 1

    def rule(self) -> Rule:
        return Rule("made-up", alpha=0.01)


class NowhereDriver(MadeUpDriver):
    where = "elsewhere"


class SilentDriver:
    name = "made-up"
    api_version = 1

    def prepare(self, ctx: Any, argv: list[str]) -> Any:
        return argv

    def read(self, ctx: Any, artifacts: Path) -> list[Any]:
        return []

    def default_primary(self, samples: list[Any]) -> list[str]:
        return []


class FakeEntry:
    """Stands in for an installed entry point."""

    def __init__(self, name: str, obj: Any, *, owner: str = "made-up-dist") -> None:
        self.name = name
        self.value = "made_up_module:thing"
        self.dist = type("Dist", (), {"name": owner})()
        self._obj = obj

    def load(self) -> Any:
        if isinstance(self._obj, Exception):
            raise self._obj
        return self._obj


def _entry_points(
    monkeypatch: pytest.MonkeyPatch, by_group: dict[str, list[FakeEntry]]
) -> list[str]:
    asked: list[str] = []

    def fake(*, group: str) -> list[FakeEntry]:
        asked.append(group)
        return by_group.get(group, [])

    monkeypatch.setattr(importlib.metadata, "entry_points", fake)
    return asked


# ---------------------------------------------------------------------------
# Groups and built-ins
# ---------------------------------------------------------------------------


def test_the_seven_groups() -> None:
    assert api.GROUPS == GROUPS
    assert tuple(registry.BUILTINS) == GROUPS
    assert tuple(api.PROTOCOLS) == GROUPS
    assert tuple(api.REQUIRED_METHODS) == GROUPS


def test_the_built_in_names_of_every_group() -> None:
    assert {group: tuple(names) for group, names in registry.BUILTINS.items()} == BUILTIN_NAMES
    for group, names in BUILTIN_NAMES.items():
        assert registry.names(group)[: len(names)] == names
        assert all(registry.is_builtin(group, name) for name in names)


def test_the_package_registers_every_built_in_as_an_entry_point() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["entry-points"] == {
        group: dict(entries) for group, entries in registry.BUILTINS.items()
    }


def test_a_built_in_reference_names_a_module_of_the_package_and_an_object() -> None:
    for entries in registry.BUILTINS.values():
        for ref in entries.values():
            module, _, name = ref.partition(":")
            assert module.startswith("pairbench.")
            assert name.isidentifier()


def test_the_model_knows_the_names_of_the_built_ins_a_results_document_may_show() -> None:
    assert BUILTIN_NAMES["pairbench.side_kinds"] == model.BUILTIN_KINDS
    assert BUILTIN_NAMES["pairbench.drivers"] == model.BUILTIN_DRIVERS
    assert BUILTIN_NAMES["pairbench.gates"] == (*model.BUILTIN_GATES, *model.READINESS_GATES)
    assert model.PLUGIN_NAME == "plugin"


def test_the_built_in_rule_is_loaded_through_its_group() -> None:
    assert registry.rule("strict") is STRICT
    assert registry.get("pairbench.rules", "strict").api_version == 1
    assert registry.counts() == PluginCounts(loaded=0, failed=0)


def test_an_unknown_group_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match=r"not a plug-in group: pairbench\.made_up"):
        registry.get("pairbench.made_up", "x")
    with pytest.raises(ValueError, match="not a plug-in group"):
        registry.register("pairbench.made_up", "x", MadeUpDriver)


def test_an_unknown_name_is_refused_with_the_known_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _entry_points(monkeypatch, {})
    with pytest.raises(Refusal, match="unknown rule 'made-up'; known: strict") as caught:
        registry.rule("made-up")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_built_in_that_cannot_be_loaded_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(
        registry.BUILTINS["pairbench.drivers"],  # type: ignore[index]
        "made-up",
        "pairbench.made_up_module:MadeUp",
    )
    with pytest.raises(Refusal, match="a built-in plug-in failed to load") as caught:
        registry.driver("made-up")
    assert caught.value.code == "E_INTERNAL"
    assert caught.value.exit_code == 8
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err.startswith(
        "pairbench: plug-in failed to load: pairbench.drivers made-up: ModuleNotFoundError"
    )
    (failure,) = registry.failures()
    assert (failure.group, failure.name, failure.origin) == (
        "pairbench.drivers",
        "made-up",
        "builtin",
    )
    assert registry.counts() == PluginCounts(loaded=0, failed=1)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_a_registered_plug_in_is_found_by_group_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _entry_points(monkeypatch, {})
    made = MadeUpDriver()
    registry.register("pairbench.drivers", "made-up", made)
    assert registry.get("pairbench.drivers", "made-up") is made
    assert registry.driver("made-up") is made
    assert registry.names("pairbench.drivers") == (*BUILTIN_NAMES["pairbench.drivers"], "made-up")
    assert registry.is_builtin("pairbench.drivers", "made-up") is False
    assert registry.counts() == PluginCounts(loaded=1, failed=0)
    assert registry.failures() == ()


def test_a_registered_class_is_called_to_make_the_plug_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _entry_points(monkeypatch, {})
    registry.register("pairbench.rules", "made-up", MadeUpRule)
    assert isinstance(registry.get("pairbench.rules", "made-up"), MadeUpRule)
    assert registry.rule("made-up") == Rule("made-up", alpha=0.01)


def test_a_plug_in_with_another_api_version_fails_loudly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Newer(MadeUpDriver):
        api_version = 2

    with pytest.raises(registry.PluginError) as caught:
        registry.register("pairbench.drivers", "made-up", Newer)
    line = (
        "pairbench: plug-in failed to load: pairbench.drivers made-up: "
        "it declares api_version 2; this pairbench speaks 1"
    )
    assert str(caught.value) == line
    streams = capsys.readouterr()
    assert streams.err == line + "\n"
    assert streams.out == ""
    (failure,) = registry.failures()
    assert (failure.group, failure.name, failure.origin, failure.line) == (
        "pairbench.drivers",
        "made-up",
        "register",
        line,
    )
    assert registry.counts() == PluginCounts(loaded=0, failed=1)
    with pytest.raises(Refusal, match="driver 'made-up' failed to load") as refused:
        registry.driver("made-up")
    assert refused.value.code == "E_USAGE"


def test_a_plug_in_without_an_api_version_fails_loudly(capsys: pytest.CaptureFixture[str]) -> None:
    class Silent:
        name = "made-up"

        def rule(self) -> Rule:
            return STRICT

    with pytest.raises(registry.PluginError, match="it declares api_version None"):
        registry.register("pairbench.rules", "made-up", Silent)
    assert "it declares api_version None; this pairbench speaks 1" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("group", "name", "obj", "reason"),
    [
        ("pairbench.drivers", "other-name", MadeUpDriver, "it declares the name 'made-up'"),
        ("pairbench.side_kinds", "made-up", MadeUpRule, "it lacks resolve, look_up"),
        ("pairbench.launchers", "made-up", MadeUpRule, "it lacks resolve, look_up, start"),
        ("pairbench.drivers", "made-up", MadeUpRule, "it lacks prepare, read, default_primary"),
        ("pairbench.capture_readers", "made-up", MadeUpRule, "it lacks sniff, read"),
        ("pairbench.gates", "made-up", MadeUpRule, "it lacks check"),
        ("pairbench.reporters", "made-up", MadeUpRule, "it lacks render"),
        ("pairbench.rules", "made-up", MadeUpDriver, "it lacks rule"),
        ("pairbench.rules", "strict", MadeUpRule, "the name is taken"),
        (
            "pairbench.drivers",
            "made-up",
            NowhereDriver,
            "it must say where it runs: in_side or client",
        ),
        (
            "pairbench.drivers",
            "made-up",
            SilentDriver,
            "it must say where it runs: in_side or client",
        ),
    ],
)
def test_a_plug_in_that_does_not_meet_its_group_fails_loudly(
    group: str, name: str, obj: Any, reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(registry.PluginError):
        registry.register(group, name, obj)
    streams = capsys.readouterr()
    assert streams.err == f"pairbench: plug-in failed to load: {group} {name}: {reason}\n"
    assert streams.out == ""
    assert registry.counts().failed == 1


def test_a_name_can_be_registered_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(monkeypatch, {})
    registry.register("pairbench.rules", "made-up", MadeUpRule)
    with pytest.raises(registry.PluginError, match="the name is taken"):
        registry.register("pairbench.rules", "made-up", MadeUpRule)
    assert "the name is taken" in capsys.readouterr().err


def test_a_plug_in_whose_class_cannot_be_made_fails_loudly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Broken:
        def __init__(self) -> None:
            raise RuntimeError("made-up failure")

    with pytest.raises(registry.PluginError):
        registry.register("pairbench.rules", "made-up", Broken)
    assert "RuntimeError: made-up failure" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def test_plug_ins_are_loaded_from_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _entry_points(monkeypatch, {"pairbench.rules": [FakeEntry("made-up", MadeUpRule)]})
    assert registry.rule("made-up") == Rule("made-up", alpha=0.01)
    assert sorted(asked) == sorted(GROUPS)
    assert registry.names("pairbench.rules") == ("strict", "made-up")
    assert registry.counts() == PluginCounts(loaded=1, failed=0)
    registry.load_plugins()
    assert len(asked) == len(GROUPS)


def test_an_entry_point_with_another_api_version_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Older(MadeUpRule):
        api_version = 0

    _entry_points(monkeypatch, {"pairbench.rules": [FakeEntry("made-up", Older)]})
    registry.load_plugins()
    streams = capsys.readouterr()
    assert streams.err == (
        "pairbench: plug-in failed to load: pairbench.rules made-up: "
        "it declares api_version 0; this pairbench speaks 1\n"
    )
    assert streams.out == ""
    assert registry.counts() == PluginCounts(loaded=0, failed=1)
    assert [f.origin for f in registry.failures()] == ["entry_point"]
    assert registry.names("pairbench.rules") == ("strict",)
    with pytest.raises(Refusal, match="rule 'made-up' failed to load") as caught:
        registry.rule("made-up")
    assert caught.value.code == "E_USAGE"


def test_an_entry_point_that_raises_or_takes_a_built_in_name_is_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(
        monkeypatch,
        {
            "pairbench.rules": [
                FakeEntry("broken", ImportError("made-up failure")),
                FakeEntry("strict", MadeUpRule),
            ]
        },
    )
    registry.load_plugins()
    err = capsys.readouterr().err.splitlines()
    assert err == [
        "pairbench: plug-in failed to load: pairbench.rules broken: ImportError: made-up failure",
        "pairbench: plug-in failed to load: pairbench.rules strict: the name is taken",
    ]
    assert registry.counts() == PluginCounts(loaded=0, failed=2)
    assert registry.rule("strict") is STRICT


def test_the_entry_points_of_the_package_itself_are_not_loaded_as_plug_ins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own = FakeEntry("made-up", MadeUpRule, owner="pairbench")
    _entry_points(monkeypatch, {"pairbench.rules": [own]})
    registry.load_plugins()
    assert registry.names("pairbench.rules") == ("strict",)
    assert registry.counts() == PluginCounts(loaded=0, failed=0)


def test_third_party_plug_ins_can_be_disabled_while_built_ins_still_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _entry_points(monkeypatch, {"pairbench.rules": [FakeEntry("from-entry", MadeUpRule)]})
    registry.register("pairbench.rules", "made-up", MadeUpRule)
    assert registry.plugins_enabled() is True
    registry.set_plugins_enabled(False)
    assert registry.plugins_enabled() is False
    assert registry.rule("strict") is STRICT
    assert registry.names("pairbench.rules") == ("strict",)
    with pytest.raises(Refusal, match="unknown rule 'made-up'; known: strict") as caught:
        registry.rule("made-up")
    assert caught.value.code == "E_USAGE"
    with pytest.raises(Refusal, match="unknown rule 'from-entry'"):
        registry.rule("from-entry")
    assert registry.counts() == PluginCounts(loaded=0, failed=0)
    assert asked == []
    registry.set_plugins_enabled(True)
    assert registry.rule("made-up") == Rule("made-up", alpha=0.01)


def test_reset_forgets_plug_ins_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _entry_points(monkeypatch, {})
    registry.register("pairbench.rules", "made-up", MadeUpRule)
    registry.set_plugins_enabled(False)
    registry.reset()
    assert registry.plugins_enabled() is True
    assert registry.names("pairbench.rules") == ("strict",)
    assert registry.counts() == PluginCounts(loaded=0, failed=0)


def test_plug_in_names_never_reach_the_counts() -> None:
    assert [f.name for f in PluginCounts.__dataclass_fields__.values() if f.name != "OPTIONAL"] == [
        "loaded",
        "failed",
    ]


def test_a_load_failure_line_escapes_its_name_and_reason() -> None:
    failure = registry.LoadFailure(
        group="pairbench.drivers",
        name="made\x1b[2Jup",
        origin="entry_point",
        reason="ValueError: a\\b\u202ec",
    )
    assert failure.line == (
        "pairbench: plug-in failed to load: pairbench.drivers made\\x1b[2Jup: "
        "ValueError: a\\\\b\\u202ec"
    )


# A plug-in name with an escape character, registered from inside the loading of another.
INNER = "in\x1bner"
INNER_TEXT = (
    "pairbench: plug-in failed to load: pairbench.rules in\x1bner: "
    "it declares api_version None; this pairbench speaks 1"
)
INNER_LINE = (
    "pairbench: plug-in failed to load: pairbench.rules in\\x1bner: "
    "it declares api_version None; this pairbench speaks 1"
)


class RegisteringEntry(FakeEntry):
    """An entry point whose module registers a plug-in that fails when it is loaded."""

    def load(self) -> Any:
        registry.register("pairbench.rules", INNER, object())
        return MadeUpRule


def test_a_registration_that_fails_inside_an_entry_point_is_escaped_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(monkeypatch, {"pairbench.rules": [RegisteringEntry("outer", None)]})

    registry.load_plugins()

    outer = "pairbench: plug-in failed to load: pairbench.rules outer: PluginError: "
    outer_text = outer + INNER_TEXT
    outer_line = outer + INNER_LINE
    streams = capsys.readouterr()
    assert (streams.out, streams.err) == ("", f"{INNER_LINE}\n{outer_line}\n")
    assert [failure.text for failure in registry.failures()] == [INNER_TEXT, outer_text]
    assert [failure.line for failure in registry.failures()] == [INNER_LINE, outer_line]


def test_a_refusal_raised_inside_an_entry_point_is_escaped_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    refused = Refusal("E_USAGE", "made\x1bup")
    _entry_points(monkeypatch, {"pairbench.rules": [FakeEntry("outer", refused)]})

    registry.load_plugins()

    streams = capsys.readouterr()
    assert (streams.out, streams.err) == (
        "",
        "pairbench: plug-in failed to load: pairbench.rules outer: Refusal: E_USAGE: made\\x1bup\n",
    )
    assert [failure.text for failure in registry.failures()] == [
        "pairbench: plug-in failed to load: pairbench.rules outer: Refusal: E_USAGE: made\x1bup"
    ]


def test_a_registration_that_fails_inside_a_registration_is_escaped_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(monkeypatch, {})

    class Outer(MadeUpRule):
        name = "outer"

        def __init__(self) -> None:
            registry.register("pairbench.rules", INNER, object())

    with pytest.raises(registry.PluginError) as caught:
        registry.register("pairbench.rules", "outer", Outer)

    outer_text = f"pairbench: plug-in failed to load: pairbench.rules outer: {INNER_TEXT}"
    outer_line = f"pairbench: plug-in failed to load: pairbench.rules outer: {INNER_LINE}"
    assert str(caught.value) == outer_line
    assert caught.value.text == outer_text
    streams = capsys.readouterr()
    assert (streams.out, streams.err) == ("", f"{INNER_LINE}\n{outer_line}\n")
    assert [failure.text for failure in registry.failures()] == [INNER_TEXT, outer_text]


class _OwnPluginError(registry.PluginError):
    """A plug-in's own error that skips the constructor of ``PluginError``."""

    def __init__(self, what: str) -> None:
        Exception.__init__(self, "mine: " + what)


def test_a_plug_in_error_needs_no_message() -> None:
    error = registry.PluginError()
    assert str(error) == ""
    assert error.text == ""


def test_a_plug_in_error_that_skips_its_constructor_is_read_by_its_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(monkeypatch, {})

    class Own(MadeUpRule):
        name = "own"

        def __init__(self) -> None:
            raise _OwnPluginError("in\x1bit")

    with pytest.raises(registry.PluginError) as caught:
        registry.register("pairbench.rules", "own", Own)

    text = "pairbench: plug-in failed to load: pairbench.rules own: mine: in\x1bit"
    line = "pairbench: plug-in failed to load: pairbench.rules own: mine: in\\x1bit"
    assert str(caught.value) == line
    assert caught.value.text == text
    streams = capsys.readouterr()
    assert (streams.out, streams.err) == ("", f"{line}\n")
    assert [failure.text for failure in registry.failures()] == [text]


def test_an_entry_point_that_raises_a_plug_in_error_without_its_constructor_is_one_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _entry_points(monkeypatch, {"pairbench.rules": [FakeEntry("own", _OwnPluginError("load"))]})

    registry.load_plugins()

    text = "pairbench: plug-in failed to load: pairbench.rules own: _OwnPluginError: mine: load"
    streams = capsys.readouterr()
    assert (streams.out, streams.err) == ("", f"{text}\n")
    assert [failure.text for failure in registry.failures()] == [text]
