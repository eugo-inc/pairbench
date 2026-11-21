# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each side names the driver that read it, and sides read by different drivers are flagged.

A result file side may name its own driver (``format``), so the sides of one
experiment can be read by two different tools. The results then name each
side's driver and tool version, the reports say which driver read which
side, and a loud note says that a ratio between the sides compares two tools
as well as two sides.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.model import NOTE_DRIVERS_DIFFER, Capture, DriverInfo, Header, Results
from pairbench.results import load_schema
from pairbench.results.writer import write_results
from pairbench.stats.selftest import synthetic_capture

jsonschema = pytest.importorskip(
    "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
)

PLUGIN = "made-up-plugin-driver"


def _value(entry: str, case: str, round_: int, u: float) -> float:
    return 2.0 + u if entry.startswith("new") else 1.0 + u


def _capture(
    formats: dict[str, str | None],
    versions: dict[str, str],
    *,
    driver: str = "guidellm",
    seed: int = 1,
    capture_id: str = "made-up-file-run",
) -> Capture:
    """Two file sides, ``new`` and ``old``, each with its own format, read under one workload."""
    capture = synthetic_capture(_value, twinned=(), capture_id=capture_id, seed=seed)
    sides = tuple(
        dataclasses.replace(
            side,
            kind="file",
            spec={"paths": [f"{side.name}-*.json"], "format": formats[side.name]},
        )
        for side in capture.sides
    )
    launches = tuple(
        dataclasses.replace(launch, tool_version=versions[launch.name])
        for launch in capture.launches
    )
    header: Header = dataclasses.replace(capture.header, config={"workload": {"driver": driver}})
    return dataclasses.replace(capture, sides=sides, launches=launches, header=header)


def _texts(results: Results, folder: Path) -> dict[str, str]:
    write_results(results, folder)
    return {
        "results.json": (folder / "results.json").read_text(encoding="utf-8"),
        "results.md": (folder / "results.md").read_text(encoding="utf-8"),
        "terminal": pairbench.render(results, "terminal"),
        "html": pairbench.render(results, "html"),
    }


def _drivers(results: Results) -> dict[str, DriverInfo | None]:
    return {side.name: side.driver for side in results.sides}


def test_sides_read_by_different_drivers_are_each_named_and_flagged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _capture({"new": "aiperf", "old": None}, {"new": "made-up-2.0", "old": "made-up-1.0"})
    results = pairbench.analyse(capture)
    assert f"note: {NOTE_DRIVERS_DIFFER}: the sides were read by" in capsys.readouterr().err
    assert _drivers(results) == {
        "new": DriverInfo(name="aiperf", tool_versions=("made-up-2.0",)),
        "old": DriverInfo(name="guidellm", tool_versions=("made-up-1.0",)),
    }
    (note,) = [n for n in results.notes if n.code == NOTE_DRIVERS_DIFFER]
    assert "new by driver aiperf" in note.message
    assert "old by driver guidellm" in note.message
    texts = _texts(results, tmp_path / "run")
    doc: dict[str, Any] = json.loads(texts["results.json"])
    jsonschema.Draft202012Validator(load_schema("results")).validate(doc)
    assert [s["driver"] for s in doc["sides"]] == [
        {"name": "aiperf", "tool_versions": ["made-up-2.0"]},
        {"name": "guidellm", "tool_versions": ["made-up-1.0"]},
    ]
    assert Results.from_json(doc).sides == results.sides
    fact = (
        "Values of side new read by driver aiperf, tool version made-up-2.0; "
        "of side old by driver guidellm, tool version made-up-1.0."
    )
    for where in ("results.md", "terminal", "html"):
        assert fact in texts[where], where
    for where in ("results.md", "html"):
        assert "the sides were read by different drivers" in texts[where], where


def test_sides_read_by_one_driver_keep_one_sentence_and_no_note(tmp_path: Path) -> None:
    capture = _capture(
        {"new": None, "old": "guidellm"}, {"new": "made-up-1.0", "old": "made-up-1.0"}
    )
    results = pairbench.analyse(capture)
    one = DriverInfo(name="guidellm", tool_versions=("made-up-1.0",))
    assert _drivers(results) == {"new": one, "old": one}
    assert NOTE_DRIVERS_DIFFER not in [n.code for n in results.notes]
    texts = _texts(results, tmp_path / "run")
    for where in ("results.md", "terminal", "html"):
        assert "Values read by driver guidellm, tool version made-up-1.0." in texts[where], where
        assert "Values of side" not in texts[where], where


def test_one_driver_with_two_tool_versions_names_the_version_of_each_side(tmp_path: Path) -> None:
    capture = _capture({"new": None, "old": None}, {"new": "made-up-1.1", "old": "made-up-1.0"})
    results = pairbench.analyse(capture)
    assert NOTE_DRIVERS_DIFFER not in [n.code for n in results.notes]
    fact = (
        "Values of side new read by driver guidellm, tool version made-up-1.1; "
        "of side old by driver guidellm, tool version made-up-1.0."
    )
    assert fact in _texts(results, tmp_path / "run")["results.md"]


def test_a_plug_in_driver_of_a_side_is_flagged_but_never_named(tmp_path: Path) -> None:
    capture = _capture({"new": PLUGIN, "old": None}, {"new": "made-up-3.0", "old": "made-up-1.0"})
    results = pairbench.analyse(capture)
    assert _drivers(results)["new"] == DriverInfo(name=None, tool_versions=("made-up-3.0",))
    (note,) = [n for n in results.notes if n.code == NOTE_DRIVERS_DIFFER]
    assert "new by a plug-in driver" in note.message
    for where, text in _texts(results, tmp_path / "run").items():
        assert PLUGIN not in text, where


def test_the_run_driver_of_sides_read_by_different_drivers_names_no_driver(
    tmp_path: Path,
) -> None:
    capture = _capture({"new": "aiperf", "old": None}, {"new": "made-up-2.0", "old": "made-up-1.0"})
    results = pairbench.analyse(capture)
    # The run's driver agrees with the drivers of its sides: two drivers are named as none.
    assert results.provenance.driver == DriverInfo(
        name=None, tool_versions=("made-up-1.0", "made-up-2.0")
    )
    doc: dict[str, Any] = json.loads(_texts(results, tmp_path / "run")["results.json"])
    assert doc["provenance"]["driver"] == {
        "name": None,
        "tool_versions": ["made-up-1.0", "made-up-2.0"],
    }


def test_the_run_driver_of_sides_that_each_name_one_other_driver_is_that_driver() -> None:
    capture = _capture(
        {"new": "aiperf", "old": "aiperf"}, {"new": "made-up-2.0", "old": "made-up-2.0"}
    )
    results = pairbench.analyse(capture)
    one = DriverInfo(name="aiperf", tool_versions=("made-up-2.0",))
    assert _drivers(results) == {"new": one, "old": one}
    assert results.provenance.driver == one


def _pool(
    versions: tuple[dict[str, str], dict[str, str]], drivers: tuple[str, str]
) -> list[Capture]:
    """Two captures of one experiment, each with its own tool versions and workload driver."""
    return [
        _capture(
            {"new": None, "old": None},
            versions[k],
            driver=drivers[k],
            seed=k + 1,
            capture_id=f"made-up-pool-{name}",
        )
        for k, name in enumerate("ab")
    ]


def test_a_pooled_run_lists_the_tool_versions_of_every_capture(tmp_path: Path) -> None:
    captures = _pool(
        (
            {"new": "made-up-1.0", "old": "made-up-1.0"},
            {"new": "made-up-1.1", "old": "made-up-1.0"},
        ),
        ("guidellm", "guidellm"),
    )
    results = pairbench.analyse(captures)
    assert results.run.pooled is True
    assert _drivers(results) == {
        "new": DriverInfo(name="guidellm", tool_versions=("made-up-1.0", "made-up-1.1")),
        "old": DriverInfo(name="guidellm", tool_versions=("made-up-1.0",)),
    }
    assert results.provenance.driver == DriverInfo(
        name="guidellm", tool_versions=("made-up-1.0", "made-up-1.1")
    )
    assert NOTE_DRIVERS_DIFFER not in [n.code for n in results.notes]
    texts = _texts(results, tmp_path / "run")
    doc: dict[str, Any] = json.loads(texts["results.json"])
    jsonschema.Draft202012Validator(load_schema("results")).validate(doc)
    assert doc["provenance"]["driver"] == {
        "name": "guidellm",
        "tool_versions": ["made-up-1.0", "made-up-1.1"],
    }
    fact = (
        "Values of side new read by driver guidellm, tool versions made-up-1.0, made-up-1.1; "
        "of side old by driver guidellm, tool version made-up-1.0."
    )
    assert fact in texts["results.md"]


def test_a_side_pooled_captures_read_by_different_drivers_is_flagged_and_not_named_as_one(
    tmp_path: Path,
) -> None:
    captures = _pool(
        (
            {"new": "made-up-1.0", "old": "made-up-1.0"},
            {"new": "made-up-2.0", "old": "made-up-2.0"},
        ),
        ("guidellm", "aiperf"),
    )
    results = pairbench.analyse(captures)
    both = DriverInfo(name=None, tool_versions=("made-up-1.0", "made-up-2.0"))
    assert _drivers(results) == {"new": both, "old": both}
    assert results.provenance.driver == both
    (note,) = [n for n in results.notes if n.code == NOTE_DRIVERS_DIFFER]
    assert note.message == (
        "the pooled captures read the sides by different drivers (side new by driver guidellm "
        "in made-up-pool-a and driver aiperf in made-up-pool-b; side old by driver guidellm in "
        "made-up-pool-a and driver aiperf in made-up-pool-b); each tool measures as its own "
        "documentation defines, so pooling them mixes the figures of two tools"
    )
    texts = _texts(results, tmp_path / "run")
    jsonschema.Draft202012Validator(load_schema("results")).validate(
        json.loads(texts["results.json"])
    )
    for where in ("results.md", "terminal", "html"):
        assert (
            "Values read by a driver not named, tool versions made-up-1.0, made-up-2.0."
            in texts[where]
        ), where
        assert "plug-in" not in texts[where], where
    for where in ("results.md", "html"):
        assert "the pooled captures read the sides by different drivers" in texts[where], where


def test_a_plug_in_driver_in_one_pooled_capture_is_never_named(tmp_path: Path) -> None:
    captures = _pool(
        (
            {"new": "made-up-1.0", "old": "made-up-1.0"},
            {"new": "made-up-3.0", "old": "made-up-3.0"},
        ),
        ("guidellm", PLUGIN),
    )
    results = pairbench.analyse(captures)
    (note,) = [n for n in results.notes if n.code == NOTE_DRIVERS_DIFFER]
    assert "a plug-in driver in made-up-pool-b" in note.message
    for where, text in _texts(results, tmp_path / "run").items():
        assert PLUGIN not in text, where
