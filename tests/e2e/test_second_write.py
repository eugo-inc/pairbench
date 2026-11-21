# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A real run through the command line, every write of the results recorded.

The run measures two seeded sides, then runs the explain step, the charts
and the report page. The second write may change only the keys the model
allows, and the first write's notes stay first.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.model import Results, second_write_changes
from pairbench.results import writer

from .conftest import SEEDED_SIDE, read_json

pytestmark = pytest.mark.slow


def seeded(factor: float, name: str) -> str:
    words = [sys.executable, str(SEEDED_SIDE), "--factor", repr(factor), "--name", name]
    return " ".join(shlex.quote(word) for word in words) + " --wait 0.05"


def test_the_second_write_changes_only_what_the_steps_after_the_analysis_own(
    cli: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    found = shutil.which("true")
    assert found is not None
    (tools / "true").symlink_to(found)
    monkeypatch.setenv("PATH", str(tools))
    written: list[Results] = []
    real = writer.write_results

    def record(results: Results, folder: Path, **kwargs: Any) -> Results:
        done = real(results, folder, **kwargs)
        written.append(done)
        return done

    monkeypatch.setattr(writer, "write_results", record)
    folder = tmp_path / "run"

    result = cli(
        "run",
        "--side",
        f"new=cmd:{seeded(2.0, 'new')}",
        "--side",
        f"old=cmd:{seeded(1.0, 'old')}",
        "--baseline",
        "old",
        "--driver",
        "lines",
        "--vary-env-size",
        "--gates",
        "off",
        "--rounds",
        "8",
        "--explain",
        "always",
        "--plots",
        "auto",
        "--positive-control",
        "off",
        "--out",
        str(folder),
    )

    assert result.code == 0, result.err
    assert len(written) == 2
    first, second = written
    assert first.diagnostics.status == "pending"
    assert first.plots.status == "pending"
    assert second_write_changes(first, second) == ()
    assert second.diagnostics.status == "written"
    assert second.plots.status in ("drawn", "not_drawn")
    assert read_json(folder / "results.json") == second.to_json()
    assert (folder / "report.html").is_file()
    assert second.artifacts.html == "report.html"
