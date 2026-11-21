# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What every test shares.

* Every ``PAIRBENCH_*`` variable is removed from the environment of every test.
* The plug-in registry starts empty for every test and is emptied after it.
* A test that needs a container engine, a GPU or an external program says so
  with a marker, or asks the ``needs`` fixture. When the need is not met the
  test is skipped with a message naming what is missing, and the skip is
  listed in a banner at the end of the session.
* With ``PAIRBENCH_REQUIRE_ENGINE=docker`` (or ``podman``) set, a test that is
  skipped for want of that engine fails.
* GPU tests run only with ``PAIRBENCH_TEST_GPU=1`` set, so a machine that
  happens to have a GPU does not start GPU work by running the tests.
* A test that draws a chart needs the ``plot`` extra and says so with the
  marker ``needs_plot`` or with ``needs.plot()``. With
  ``PAIRBENCH_REQUIRE_PLOT=1`` set, a test that is skipped for want of the
  extra fails.
* ``cli`` calls the command line in this process and returns the exit code,
  standard output and standard error.
* The ``example_*`` fixtures give a fresh copy of an example document with
  made-up values: capture records, results documents, a diagnostics document
  and configs.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import os
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pytest

ENGINES = ("docker", "podman")

# Read once, before the fixture below removes the variables for each test.
REQUIRE_ENGINE = os.environ.get("PAIRBENCH_REQUIRE_ENGINE", "").strip().lower()
GPU_TESTS = os.environ.get("PAIRBENCH_TEST_GPU", "").strip().lower() in ("1", "true", "yes")
REQUIRE_PLOT = os.environ.get("PAIRBENCH_REQUIRE_PLOT", "").strip().lower() in ("1", "true", "yes")

# The module the ``plot`` extra provides.
PLOT_MODULE = "matplotlib"

_unmet: list[tuple[str, str]] = []


def _unmet_need(
    nodeid: str, reason: str, *, required: bool = False, switch: str | None = None
) -> None:
    if required:
        setting = switch or f"PAIRBENCH_REQUIRE_ENGINE={REQUIRE_ENGINE}"
        pytest.fail(f"{reason} ({setting} turns this skip into a failure)")
    _unmet.append((nodeid, reason))
    pytest.skip(reason)


def _engine(nodeid: str, name: str | None) -> str:
    wanted = (name,) if name else ((REQUIRE_ENGINE,) if REQUIRE_ENGINE else ENGINES)
    for engine in wanted:
        if shutil.which(engine):
            return engine
    asked = name or REQUIRE_ENGINE or "docker or podman"
    required = bool(REQUIRE_ENGINE) and name in (None, REQUIRE_ENGINE)
    _unmet_need(nodeid, f"needs a container engine: {asked} is not on PATH", required=required)
    raise AssertionError("unreachable")


def _gpu(nodeid: str) -> None:
    if not GPU_TESTS:
        _unmet_need(nodeid, "needs a GPU: set PAIRBENCH_TEST_GPU=1 on a machine that has one")


def _tool(nodeid: str, name: str) -> str:
    found = shutil.which(name)
    if not found:
        _unmet_need(nodeid, f"needs the external program {name!r} on PATH")
        raise AssertionError("unreachable")
    return found


def _plot_installed() -> bool:
    try:
        return importlib.util.find_spec(PLOT_MODULE) is not None
    except (ImportError, ValueError):
        return False


def _plot(nodeid: str) -> None:
    if not _plot_installed():
        _unmet_need(
            nodeid,
            f"needs the plot extra: {PLOT_MODULE} is not installed",
            required=REQUIRE_PLOT,
            switch="PAIRBENCH_REQUIRE_PLOT=1",
        )


def pytest_runtest_setup(item: pytest.Item) -> None:
    for mark in item.iter_markers("needs_engine"):
        _engine(item.nodeid, mark.args[0] if mark.args else None)
    for _mark in item.iter_markers("needs_gpu"):
        _gpu(item.nodeid)
    for mark in item.iter_markers("needs_tool"):
        for name in mark.args:
            _tool(item.nodeid, name)
    for _mark in item.iter_markers("needs_plot"):
        _plot(item.nodeid)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    if not _unmet:
        return
    terminalreporter.section("skipped for a missing engine, GPU or external program", sep="=")
    for nodeid, reason in _unmet:
        terminalreporter.write_line(f"SKIPPED {nodeid}: {reason}")
    terminalreporter.write_line(f"{len(_unmet)} test(s) did not run for that reason.")


def _remove_pairbench_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("PAIRBENCH_"):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_pairbench_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _remove_pairbench_variables(monkeypatch)


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    from pairbench import registry

    registry.reset()
    yield
    registry.reset()


class _Test(Protocol):
    nodeid: str

    def get_closest_marker(self, name: str) -> object | None: ...


UNMARKED_ENGINE = (
    "this test asks for a container engine without the needs_engine mark: mark it with "
    "pytest.mark.needs_engine, so a run that leaves out that mark leaves this test out too"
)


class Needs:
    """Ask for an engine, a GPU or an external program from inside a test."""

    def __init__(self, node: _Test) -> None:
        self._node = node
        self._nodeid = node.nodeid

    def engine(self, name: str | None = None) -> str:
        """Return the name of an available container engine, or skip.

        A test that starts a container carries the ``needs_engine`` mark, so a run that
        leaves out the tests marked so (``-m "not needs_engine"``) starts no container.
        A test that asks without the mark fails before any engine is looked for.
        """
        if self._node.get_closest_marker("needs_engine") is None:
            pytest.fail(UNMARKED_ENGINE)
        return _engine(self._nodeid, name)

    def gpu(self) -> None:
        """Skip unless GPU tests were asked for."""
        _gpu(self._nodeid)

    def tool(self, name: str) -> str:
        """Return the path of an external program, or skip."""
        return _tool(self._nodeid, name)

    def plot(self) -> None:
        """Skip unless the ``plot`` extra is installed."""
        _plot(self._nodeid)


@pytest.fixture
def needs(request: pytest.FixtureRequest) -> Needs:
    return Needs(request.node)


@dataclass(frozen=True)
class CliResult:
    """What one call of the command line gave: exit code, standard output, standard error."""

    code: int
    out: str
    err: str


@pytest.fixture
def cli() -> Callable[..., CliResult]:
    """Return a function that runs the command line in this process."""

    def call(*args: object) -> CliResult:
        from pairbench.api import CliMain, delegate

        main: CliMain = delegate("main")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main([str(a) for a in args])
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        return CliResult(code=code, out=out.getvalue(), err=err.getvalue())

    return call


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The root of the repository."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Example documents with made-up values
# ---------------------------------------------------------------------------

_SHA_A = "a" * 64
_SHA_B = "b" * 64

_EXAMPLE_CAPTURE_RECORDS: list[dict[str, Any]] = [
    {
        "t": "header",
        "schema": "pairbench/capture/v1",
        "capture_id": "cap-000001",
        "tool_version": "0.1.0",
        "started_at": "2001-01-01T00:00:00Z",
        "argv": ["pairbench", "run"],
        "config": {"rule": {"name": "strict"}},
        "seeds": {"driver": 1234},
    },
    {
        "t": "machine",
        "os": "Linux 0.0",
        "arch": "arch-a",
        "cpu": {
            "model": "cpu-model-a",
            "identity": [{"cpus": "4-7", "key": "core-type-a", "max_khz": 0}],
            "cache_domains": ["0-7"],
        },
        "gpu": [{"model": "gpu-model-a", "driver": "0.0"}],
        "engine": {"name": "docker", "version": "0.0"},
        "in_container": False,
        "ci": False,
        "node_type": None,
    },
    {
        "t": "side",
        "name": "new",
        "kind": "image",
        "role": "subject",
        "twin_of": None,
        "control_of": None,
        "spec": {"image": "registry.example/org/app:2.0"},
        "identity": {"image_id": "sha256:" + _SHA_A, "digests": ["sha256:" + _SHA_B]},
        "fingerprint": _SHA_A,
    },
    {"t": "gate", "name": "quiet", "mode": "warn", "status": "pass", "detail": {}},
    {
        "t": "lineup",
        "names": ["new", "new~same", "old", "old~same"],
        "control": "old~twice",
        "rounds": 16,
        "schedule": "rotate-reverse",
        "cases": [
            {
                "id": "wall",
                "metric": "wall",
                "unit": "s",
                "better": "lower",
                "kind": "time",
                "primary": True,
                "group": None,
            }
        ],
        "discard_thresholds": {
            "max_busy_cores": 2.0,
            "max_gpu_other_processes": 0,
            "max_gpu_throttle_events": 0,
        },
    },
    {
        "t": "launch",
        "seq": 7,
        "phase": "round",
        "round": 1,
        "pos": 1,
        "name": "new",
        "rc": 0,
        "timing": {"launch_s": 12.5, "run_s": 12.25},
        "witness": {"busy_cores": 0.25},
        "energy": None,
    },
    {
        "t": "obs",
        "seq": 7,
        "round": 1,
        "pos": 1,
        "name": "new",
        "case": "wall",
        "value": 12.25,
        "n_inner": 1,
        "reducer": "identity",
    },
    {
        "t": "end",
        "status": "complete",
        "rounds_completed": 16,
        "sha256_of_preceding": _SHA_B,
    },
]

_EXAMPLE_RESULTS: dict[str, Any] = {
    "schema": "pairbench/results/v1",
    "tool": {"name": "pairbench", "version": "0.1.0"},
    "run": {
        "id": "cap-000001",
        "started_at": "2001-01-01T00:00:00Z",
        "finished_at": "2001-01-01T00:10:00Z",
        "captures": [{"capture_id": "cap-000001", "sha256": _SHA_A, "rounds": 16}],
        "pooled": False,
        "command": "pairbench run --side new=image:<hidden> --side old=image:<hidden> -- bench.py",
    },
    "rule": {
        "name": "strict",
        "fields": {"name": "strict", "alpha": 0.05},
        "family_size": 2,
        "plain": "corrected for testing 2 cases at once",
    },
    "provenance": {
        "machine": {
            "os": "Linux 0.0",
            "arch": "arch-a",
            "cpu_model": "cpu-model-a",
            "core_types": [],
        },
        "gpu": [{"model": "gpu-model-a", "driver": "0.0"}],
        "engine": {"name": "docker", "version": "0.0"},
        "node_type": None,
        "seeds": {"driver": 1234},
        "config_sha256": _SHA_B,
    },
    "sides": [
        {
            "name": "new",
            "kind": "image",
            "role": "subject",
            "twin_of": None,
            "control_of": None,
            "identity": {"image_id": "sha256:" + _SHA_A, "digests": ["sha256:" + _SHA_B]},
            "fingerprint": _SHA_A,
        }
    ],
    "plan": {
        "schedule": "rotate-reverse",
        "rounds_requested": 16,
        "rounds_planned": 16,
        "rounds_completed": 16,
        "warmups": 1,
        "launches": 82,
        "explain_launches": 4,
    },
    "machine_state": {"status": "quiet", "gates": [], "degraded": []},
    "cases": [
        {
            "id": "matmul",
            "metric": "time",
            "unit": "s",
            "better": "lower",
            "kind": "time",
            "primary": True,
            "group": None,
        }
    ],
    "comparisons": [
        {
            "case": "matmul",
            "primary": True,
            "subject": "new",
            "baseline": "old",
            "n_rounds": 16,
            "n_unpaired": 0,
            "n_untied": 16,
            "n_lower": 15,
            "n_higher": 1,
            "subject_median": 1.92,
            "baseline_median": 2.41,
            "ratio": 0.797,
            "statistic": 0.797,
            "scale": "ratio",
            "gap": 0.203,
            "floor": {
                "source": "twins",
                "unit": "fraction",
                "subject": {
                    "value": 0.011,
                    "n": 16,
                    "provisional": False,
                    "spread": 0.02,
                    "outlier_rounds": [],
                },
                "baseline": {
                    "value": 0.007,
                    "n": 16,
                    "provisional": False,
                    "spread": 0.02,
                    "outlier_rounds": [],
                },
                "mode": "TWO-SIDED",
            },
            "bar": 0.018,
            "p_raw": 0.0005,
            "p_raw_fraction": [34, 65536],
            "p_corrected": 0.001,
            "verdict": "FASTER",
            "outcome": "better",
            "reason": None,
            "reasons": [],
            "order_split": [8, 8],
            "sensitivity": {
                "rounds_set_aside": [],
                "ratio": 0.797,
                "outcome": "better",
                "agrees": True,
            },
        }
    ],
    "same_vs_same": [
        {"side": "new", "case": "matmul", "ratio": 1.004, "floor": 0.004, "p_raw": 0.80, "n": 16}
    ],
    "twin_checks": [
        {
            "side": "new",
            "n_rounds": 16,
            "n_better": 7,
            "n_worse": 9,
            "p_raw": 0.80,
            "p_corrected": 0.80,
        }
    ],
    "controls": {
        "positive": {
            "status": "ok",
            "entry": "old~twice",
            "via": "repeat",
            "tolerance": 0.1,
            "cases": [
                {
                    "case": "matmul",
                    "expected": 2.0,
                    "ratio": 2.01,
                    "p_raw": 0.00003,
                    "n_rounds": 16,
                    "passed": True,
                }
            ],
        }
    },
    "launch_cost": {
        "command": "true",
        "n": 20,
        "median_s": 0.0005,
        "p25_s": 0.0004,
        "p75_s": 0.0007,
        "min_s": 0.0003,
    },
    "env_pad": {"varied": False},
    "series": [{"case": "matmul", "name": "new", "values": [1.92, 1.91], "disturbed_rounds": []}],
    "plots": {"status": "drawn", "reason": None},
    "diagnostics": {"status": "written", "reason": None},
    "refusals": [{"code": "E_GRID", "scope": "experiment", "message": "a made-up refusal"}],
    "notes": [],
    "plugins": {"loaded": 0, "failed": 0},
    "figures": {
        "matmul.new_vs_old.ratio": {"value": 0.797, "text": "0.80x"},
        "matmul.new_vs_old.verdict": {"value": "better", "text": "FASTER"},
    },
    "artifacts": {
        "capture": "capture.jsonl",
        "markdown": "results.md",
        "plan": "plan.tsv",
        "html": "report.html",
        "diagnostics": "diagnostics.json",
        "charts": [],
        "profiles": [],
    },
}

# The keys of a results document that may be absent, beside those of a comparison.
_OPTIONAL_RESULTS_KEYS = (
    "controls",
    "launch_cost",
    "env_pad",
    "series",
    "plots",
    "diagnostics",
    "twin_checks",
)

_EXAMPLE_DIAGNOSTICS: dict[str, Any] = {
    "schema": "pairbench/diagnostics/v1",
    "run": {"id": "cap-000001"},
    "holds_names": True,
    "instruments": [
        {"name": "counters", "side": "new", "status": "ok", "reason": None, "rc": 0},
        {
            "name": "stacks",
            "side": "old",
            "status": "skipped",
            "reason": "not_permitted",
            "rc": None,
        },
    ],
    "resources": [
        {
            "case": "res/cores",
            "subject": "new",
            "baseline": "old",
            "subject_median": 7.8,
            "baseline_median": 1.0,
            "outcome": "higher",
        }
    ],
    "counters": [
        {
            "event": "instructions",
            "subject": "new",
            "baseline": "old",
            "subject_value": 1000,
            "baseline_value": 2000,
            "ratio": 0.5,
        }
    ],
    "stacks": [
        {
            "side": "new",
            "instrument": "stacks",
            "samples": 1234,
            "top_functions": [
                {"name": "made_up_function", "object": "libmade-up.so", "share": 0.25}
            ],
            "top_objects": [{"name": "libmade-up.so", "share": 0.5}],
        }
    ],
    "objects": {
        "only_in": {"new": ["libmade-up.so"], "old": []},
        "differ": [{"name": "libother-made-up.so", "new": "aa11", "old": "bb22"}],
    },
    "findings": [
        {
            "id": "cores_used",
            "text": "new used 7.8 cores against 1.0 for old (median of 20 rounds).",
            "evidence": {
                "case": "res/cores",
                "subject_median": 7.8,
                "baseline_median": 1.0,
                "n_rounds": 20,
            },
        }
    ],
    "files": {"folded": [], "folded_diff": [], "flame": [], "flame_diff": []},
    "name_map": {},
}

_EXAMPLE_CONFIG: dict[str, Any] = {
    "run": {"rounds": "auto", "warmups": 1, "same_vs_same": "on"},
    "workload": {"argv": ["python", "bench.py"], "driver": "lines"},
    "sides": {
        "new": {"image": "myorg/app:2.0"},
        "old": {"image": "myorg/app:1.9", "baseline": True},
    },
    "launch": {
        "cpus": "4-7",
        "env": {"OMP_NUM_THREADS": "4"},
        "env_pass": ["HF_TOKEN"],
        "timeout": "10m",
    },
    "gates": {"mode": "warn"},
    "rule": {"name": "strict"},
    "cases": {"primary": ["*"]},
    "energy": {"enabled": False},
    "report": {"include_image_refs": False},
}


def _results_without_optional_keys() -> dict[str, Any]:
    doc = copy.deepcopy(_EXAMPLE_RESULTS)
    del doc["run"]["command"]
    for key in _OPTIONAL_RESULTS_KEYS:
        del doc[key]
    del doc["plan"]["explain_launches"]
    for side in doc["sides"]:
        del side["control_of"]
    for key in ("html", "diagnostics", "charts"):
        del doc["artifacts"][key]
    for comparison in doc["comparisons"]:
        del comparison["statistic"]
        del comparison["scale"]
        del comparison["reasons"]
        del comparison["floor"]["unit"]
    return doc


def _results_with_every_key() -> dict[str, Any]:
    doc = copy.deepcopy(_EXAMPLE_RESULTS)
    doc["energy"] = {
        "scope": "gpu",
        "excludes": ["cpu", "memory", "storage", "cooling", "power supply losses"],
    }
    doc["machine_state"] = {
        "status": "busy",
        "gates": [{"name": "quiet", "mode": "warn", "status": "fail"}],
        "degraded": [{"name": "census", "status": "unavailable", "message": "a made-up reason"}],
        "discard_sha256": _SHA_A,
    }
    doc["sides"][0]["image_ref"] = "registry.example/org/app:2.0"
    doc["env_pad"] = {"varied": True, "min": 0, "max": 4096}
    doc["artifacts"]["charts"] = ["charts/verdict.svg", "charts/rounds.matmul.svg"]
    doc["artifacts"]["profiles"] = ["profiles/new.folded", "profiles/new.flame.svg"]
    doc["provenance"]["driver"] = {"name": "lines", "tool_versions": ["0.0.0"]}
    doc["same_vs_same"][0]["unit"] = "fraction"
    doc["notes"] = [{"code": "floor_provisional", "message": "a made-up note"}]
    doc["comparisons"][0]["sensitivity"] = {
        "rounds_set_aside": [3, 4],
        "ratio": None,
        "outcome": None,
        "agrees": None,
        "not_computed": "too_few_rounds",
    }
    return doc


_EXAMPLE_CAPTURE_ADDITIONS: list[dict[str, Any]] = [
    {
        "t": "cases",
        "cases": [
            {
                "id": "launch",
                "metric": "launch",
                "unit": "s",
                "better": "lower",
                "kind": "time",
                "primary": False,
                "group": None,
            }
        ],
    },
    {
        "t": "launch",
        "seq": 8,
        "phase": "round",
        "round": 1,
        "pos": 2,
        "name": "new~same",
        "rc": 0,
        "timing": {"launch_s": 12.75, "run_s": 12.5},
        "witness": {"busy_cores": None, "failed": ["busy_cores"]},
        "energy": None,
        "tool_version": "0.0.0",
        "runs": 1,
        "env_pad": 512,
    },
    {
        "t": "obs",
        "seq": 8,
        "round": 1,
        "pos": 2,
        "name": "new~same",
        "case": "wall",
        "value": 12.5,
        "n_inner": 1,
        "reducer": "identity",
        "suite": "suite-a",
    },
    {"t": "note", "code": "witness_probe_failed", "message": "a made-up note"},
    {
        "t": "end",
        "status": "complete",
        "rounds_completed": 16,
        "sha256_of_preceding": _SHA_B,
        "discard_sha256": _SHA_A,
        "finished_at": "2001-01-01T00:10:00Z",
    },
]


# What a run with the positive control, a measured launch cost and a pinned CPU
# set writes beside the records above.
_EXAMPLE_CAPTURE_RUN_RECORDS: list[dict[str, Any]] = [
    {
        "t": "machine",
        "os": "Linux 0.0",
        "arch": "arch-a",
        "cpu": {
            "model": "cpu-model-a",
            "identity": [{"cpus": "4-7", "key": "core-type-a", "max_khz": 0}],
            "cache_domains": ["0-7"],
        },
        "gpu": [],
        "engine": None,
        "in_container": False,
        "ci": False,
        "node_type": None,
        "tool_cpus": "0-3",
    },
    {
        "t": "side",
        "name": "old~twice",
        "kind": "cmd",
        "role": "control",
        "twin_of": None,
        "control_of": "old",
        "spec": {"argv": ["made-up-workload"]},
        "identity": {"executable_sha256": _SHA_A, "argv_sha256": _SHA_B},
        "fingerprint": _SHA_B,
    },
    {
        "t": "launch_cost",
        "command": "true",
        "n": 20,
        "median_s": 0.0005,
        "p25_s": 0.0004,
        "p75_s": 0.0007,
        "min_s": 0.0003,
    },
    {
        "t": "launch",
        "seq": 11,
        "phase": "round",
        "round": 1,
        "pos": 5,
        "name": "old~twice",
        "rc": 0,
        "timing": {"launch_s": 25.0, "run_s": 25.0},
        "witness": {"busy_cores": 0.25},
        "energy": None,
        "runs": 2,
        "env_pad": 512,
    },
    {
        "t": "obs",
        "seq": 11,
        "round": 1,
        "pos": 5,
        "name": "old~twice",
        "case": "wall",
        "value": 25.0,
        "n_inner": 1,
        "reducer": "identity",
    },
]


@pytest.fixture
def example_capture_records() -> list[dict[str, Any]]:
    """One record of each type the capture format shows, with made-up values."""
    return copy.deepcopy(_EXAMPLE_CAPTURE_RECORDS)


@pytest.fixture
def example_capture_additions() -> list[dict[str, Any]]:
    """Capture records that carry every key a record may also hold, with made-up values."""
    return copy.deepcopy(_EXAMPLE_CAPTURE_ADDITIONS)


@pytest.fixture
def example_capture_run_records() -> list[dict[str, Any]]:
    """The records a run with the positive control, a launch cost and pinned CPUs adds."""
    return copy.deepcopy(_EXAMPLE_CAPTURE_RUN_RECORDS)


@pytest.fixture
def example_diagnostics() -> dict[str, Any]:
    """A diagnostics document with the keys of the format's example and made-up values."""
    return copy.deepcopy(_EXAMPLE_DIAGNOSTICS)


@pytest.fixture
def example_results() -> dict[str, Any]:
    """A results document with the keys of the format's example and made-up values."""
    return copy.deepcopy(_EXAMPLE_RESULTS)


@pytest.fixture
def example_results_required_only() -> dict[str, Any]:
    """The example results document without any key that may be absent."""
    return _results_without_optional_keys()


@pytest.fixture
def example_results_every_key() -> dict[str, Any]:
    """The example results document with every key the format knows."""
    return _results_with_every_key()


_EXAMPLE_SERVING_CONFIG: dict[str, Any] = {
    "workload": {
        "driver": "guidellm",
        "levels": [1, 8, 32],
        "level_kind": "concurrency",
        "level_duration": "60s",
    },
    "sides": {
        "new": {
            "serve": {
                "image": "myorg/server:2.0",
                "args": ["--model", "made-up-model"],
                "port": 8000,
                "ready": {"http": "/health", "timeout": "15m"},
            }
        },
        "old": {"serve": {"image": "myorg/server:1.9", "args": ["--model", "made-up-model"]}},
    },
}


@pytest.fixture
def example_config() -> dict[str, Any]:
    """The config example of the command-line reference, as a dict."""
    return copy.deepcopy(_EXAMPLE_CONFIG)


@pytest.fixture
def example_serving_config() -> dict[str, Any]:
    """The config of a serving experiment, as the command-line reference shows it."""
    return copy.deepcopy(_EXAMPLE_SERVING_CONFIG)
