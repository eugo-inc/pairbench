# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Plug-in loading and lookup.

Seven groups hold plug-ins: side kinds, drivers, capture readers, gates,
rules, reporters and launchers. Built-in plug-ins are listed in ``BUILTINS``
and, under the same groups, as entry points in the package's own
``pyproject.toml``; a built-in is imported when it is first asked for.
Third-party plug-ins come from the entry points of other installed
distributions and from ``register``.

A plug-in that fails to load is printed on standard error, kept in
``failures()`` and counted in ``counts()``. Plug-in names never go into a
results document; only the counts do.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from pairbench.api import (
    API_VERSION,
    DRIVER_WHERE,
    GROUP_CAPTURE_READERS,
    GROUP_DRIVERS,
    GROUP_GATES,
    GROUP_LAUNCHERS,
    GROUP_REPORTERS,
    GROUP_RULES,
    GROUP_SIDE_KINDS,
    GROUPS,
    REQUIRED_METHODS,
    CaptureReader,
    Driver,
    Gate,
    Launcher,
    Reporter,
    RuleProvider,
    SideKind,
)
from pairbench.errors import Refusal
from pairbench.model import STRICT, TOOL_NAME, PluginCounts, Rule

# Every built-in plug-in: group, name, and where its object lives. The entry
# points in pyproject.toml list the same.
BUILTINS: Final[Mapping[str, Mapping[str, str]]] = {
    GROUP_SIDE_KINDS: {
        "cmd": "pairbench.sides.command:CommandKind",
        "image": "pairbench.sides.container:ImageKind",
        "python": "pairbench.sides.pyenv:PythonKind",
        "venv": "pairbench.sides.pyenv:VenvKind",
        "conda": "pairbench.sides.pyenv:CondaKind",
        "serve": "pairbench.sides.serve:ServeKind",
        "file": "pairbench.sides.files:FileKind",
    },
    GROUP_DRIVERS: {
        "wall": "pairbench.drivers.wall:WallDriver",
        "lines": "pairbench.drivers.lines:LinesDriver",
        "gbench": "pairbench.drivers.gbench:GbenchDriver",
        "nvbench": "pairbench.drivers.nvbench:NvbenchDriver",
        "pytest-benchmark": "pairbench.drivers.pytest_benchmark:PytestBenchmarkDriver",
        "hyperfine": "pairbench.drivers.hyperfine:HyperfineDriver",
        "perf": "pairbench.drivers.perf:PerfDriver",
        "llama-bench": "pairbench.drivers.llama_bench:LlamaBenchDriver",
        "guidellm": "pairbench.drivers.guidellm:GuidellmDriver",
        "aiperf": "pairbench.drivers.aiperf:AiperfDriver",
        "vllm-bench": "pairbench.drivers.vllm_bench:VllmBenchDriver",
    },
    GROUP_CAPTURE_READERS: {
        "jsonl": "pairbench.capture.reader:JsonlReader",
        "text": "pairbench.capture.text:TextReader",
    },
    GROUP_GATES: {
        "cpus": "pairbench.gates.cpus:CpusGate",
        "quiet": "pairbench.gates.quiet:QuietGate",
        "census": "pairbench.gates.census:CensusGate",
        "stop_file": "pairbench.gates.ready:StopFileGate",
        "gpu_memory": "pairbench.gates.ready:GpuMemoryGate",
        "check_locks": "pairbench.gates.ready:CheckLocksGate",
    },
    GROUP_RULES: {
        "strict": "pairbench.registry:StrictRule",
    },
    GROUP_REPORTERS: {
        "terminal": "pairbench.report.terminal:TerminalReporter",
        "markdown": "pairbench.report.markdown:MarkdownReporter",
        "json": "pairbench.results.writer:JsonReporter",
        "html": "pairbench.page.html:HtmlReporter",
    },
    GROUP_LAUNCHERS: {
        "docker": "pairbench.sides.serve:DockerLauncher",
        "podman": "pairbench.sides.serve:PodmanLauncher",
        "host": "pairbench.sides.serve:HostLauncher",
    },
}

Origin = Literal["builtin", "entry_point", "register"]


class StrictRule:
    """The built-in rule ``strict``."""

    name = "strict"
    api_version = API_VERSION

    def rule(self) -> Rule:
        """Return the default rule."""
        return STRICT


class PluginError(Exception):
    """A plug-in handed to ``register`` does not meet the contract of its group."""


@dataclass(frozen=True)
class LoadFailure:
    """One plug-in that failed to load, for ``pairbench doctor``."""

    group: str
    name: str
    origin: Origin
    reason: str

    @property
    def line(self) -> str:
        """The line printed on standard error."""
        return f"pairbench: plug-in failed to load: {self.group} {self.name}: {self.reason}"


class _State:
    def __init__(self) -> None:
        self.builtins: dict[tuple[str, str], Any] = {}
        self.plugins: dict[tuple[str, str], Any] = {}
        self.failures: dict[tuple[str, str], LoadFailure] = {}
        self.enabled = True
        self.discovered = False


_state = _State()


def reset() -> None:
    """Forget every loaded plug-in and failure and enable third-party plug-ins again."""
    global _state
    _state = _State()


def set_plugins_enabled(enabled: bool) -> None:
    """Enable or disable third-party plug-ins. Built-ins load either way."""
    _state.enabled = enabled


def plugins_enabled() -> bool:
    """Say whether third-party plug-ins are enabled."""
    return _state.enabled


def _group(group: str) -> str:
    if group not in GROUPS:
        raise ValueError(f"not a plug-in group: {group}")
    return group


def _fail(group: str, name: str, origin: Origin, reason: str) -> LoadFailure:
    failure = LoadFailure(group=group, name=name, origin=origin, reason=reason)
    first = (group, name) not in _state.failures
    _state.failures[(group, name)] = failure
    if first:
        print(failure.line, file=sys.stderr)
    return failure


def _problem(group: str, name: str, obj: Any) -> str | None:
    """Say what keeps an object from being a plug-in of the group, or ``None``."""
    version = getattr(obj, "api_version", None)
    if version != API_VERSION:
        return f"it declares api_version {version!r}; this pairbench speaks {API_VERSION}"
    declared = getattr(obj, "name", None)
    if declared != name:
        return f"it declares the name {declared!r}"
    missing = [m for m in REQUIRED_METHODS[group] if not callable(getattr(obj, m, None))]
    if missing:
        return f"it lacks {', '.join(missing)}"
    if group == GROUP_DRIVERS and getattr(obj, "where", None) not in DRIVER_WHERE:
        return f"it must say where it runs: {' or '.join(DRIVER_WHERE)}"
    return None


def _instance(obj: Any) -> Any:
    return obj() if isinstance(obj, type) else obj


def _load_ref(ref: str) -> Any:
    module_name, _, attr = ref.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return _instance(obj)


def register(group: str, name: str, obj: Any) -> None:
    """Register a plug-in from code that has no package metadata.

    ``obj`` is the plug-in, or a class called with no arguments to make it. A
    plug-in whose ``api_version`` differs, whose ``name`` differs from the
    name given, or which lacks a method of its group fails loudly: the
    failure is printed on standard error, recorded, and raised as
    ``PluginError``. A name a built-in or another plug-in already has is
    refused the same way.
    """
    _group(group)
    key = (group, name)
    made: Any = None
    try:
        if name in BUILTINS[group] or key in _state.plugins:
            raise PluginError("the name is taken")
        made = _instance(obj)
        problem = _problem(group, name, made)
        if problem is not None:
            raise PluginError(problem)
    except PluginError as exc:
        failure = _fail(group, name, "register", str(exc))
        raise PluginError(failure.line) from None
    except Exception as exc:
        failure = _fail(group, name, "register", f"{type(exc).__name__}: {exc}")
        raise PluginError(failure.line) from exc
    _state.plugins[key] = made


def _own(entry: importlib.metadata.EntryPoint) -> bool:
    dist = getattr(entry, "dist", None)
    owner = getattr(dist, "name", None)
    if isinstance(owner, str):
        return owner.lower().replace("_", "-") == TOOL_NAME
    return entry.value.partition(":")[0].split(".")[0] == TOOL_NAME


def load_plugins() -> None:
    """Load every third-party plug-in found in entry points, once.

    Entry points of this package itself are the built-ins and are not loaded
    here. Nothing is loaded while third-party plug-ins are disabled.
    """
    if not _state.enabled or _state.discovered:
        return
    _state.discovered = True
    for group in GROUPS:
        for entry in sorted(importlib.metadata.entry_points(group=group), key=lambda e: e.name):
            if _own(entry):
                continue
            key = (group, entry.name)
            if entry.name in BUILTINS[group] or key in _state.plugins:
                _fail(group, entry.name, "entry_point", "the name is taken")
                continue
            made: Any = None
            problem: str | None
            try:
                made = _instance(entry.load())
                problem = _problem(group, entry.name, made)
            except Exception as exc:
                problem = f"{type(exc).__name__}: {exc}"
            if problem is not None:
                _fail(group, entry.name, "entry_point", problem)
            else:
                _state.plugins[key] = made


def _builtin(group: str, name: str) -> Any:
    key = (group, name)
    if key in _state.builtins:
        return _state.builtins[key]
    made: Any = None
    problem: str | None
    try:
        made = _load_ref(BUILTINS[group][name])
        problem = _problem(group, name, made)
    except Exception as exc:
        problem = f"{type(exc).__name__}: {exc}"
    if problem is not None:
        failure = _fail(group, name, "builtin", problem)
        raise Refusal("E_INTERNAL", f"a built-in plug-in failed to load: {failure.reason}")
    _state.builtins[key] = made
    return made


def get(group: str, name: str) -> Any:
    """Return the plug-in of a group with this name.

    An unknown name, and a third-party name while third-party plug-ins are
    disabled, is refused with ``E_USAGE``. A built-in that cannot be loaded is
    refused with ``E_INTERNAL``.
    """
    _group(group)
    if name in BUILTINS[group]:
        return _builtin(group, name)
    if _state.enabled:
        load_plugins()
        if (group, name) in _state.plugins:
            return _state.plugins[(group, name)]
        failure = _state.failures.get((group, name))
        if failure is not None:
            raise Refusal("E_USAGE", f"{_kind(group)} {name!r} failed to load: {failure.reason}")
    known = ", ".join(names(group))
    raise Refusal("E_USAGE", f"unknown {_kind(group)} {name!r}; known: {known}")


def _kind(group: str) -> str:
    return group.rpartition(".")[2].rstrip("s").replace("_", " ")


def names(group: str) -> tuple[str, ...]:
    """Return the names of a group: built-ins first, then loaded third-party plug-ins."""
    _group(group)
    extra: list[str] = []
    if _state.enabled:
        load_plugins()
        extra = sorted(n for g, n in _state.plugins if g == group)
    return (*BUILTINS[group], *extra)


def is_builtin(group: str, name: str) -> bool:
    """Say whether a name of a group is a built-in."""
    return name in BUILTINS[_group(group)]


def failures() -> tuple[LoadFailure, ...]:
    """Return every plug-in that failed to load so far."""
    return tuple(_state.failures.values())


def counts() -> PluginCounts:
    """Return the counts a results document records.

    ``loaded`` counts third-party plug-ins in use; ``failed`` counts every
    load failure. With third-party plug-ins disabled, ``loaded`` is zero.
    """
    loaded = len(_state.plugins) if _state.enabled else 0
    return PluginCounts(loaded=loaded, failed=len(_state.failures))


def side_kind(name: str) -> SideKind:
    """Return the side kind with this name."""
    return cast(SideKind, get(GROUP_SIDE_KINDS, name))


def driver(name: str) -> Driver:
    """Return the driver with this name."""
    return cast(Driver, get(GROUP_DRIVERS, name))


def capture_reader(name: str) -> CaptureReader:
    """Return the capture reader with this name."""
    return cast(CaptureReader, get(GROUP_CAPTURE_READERS, name))


def gate(name: str) -> Gate:
    """Return the machine check with this name."""
    return cast(Gate, get(GROUP_GATES, name))


def rule(name: str) -> Rule:
    """Return the verdict rule with this name."""
    return cast(RuleProvider, get(GROUP_RULES, name)).rule()


def reporter(name: str) -> Reporter:
    """Return the reporter with this name."""
    return cast(Reporter, get(GROUP_REPORTERS, name))


def launcher(name: str) -> Launcher:
    """Return the launcher with this name."""
    return cast(Launcher, get(GROUP_LAUNCHERS, name))
