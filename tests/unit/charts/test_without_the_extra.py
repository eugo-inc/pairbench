# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The three plot modes when the plot extra is missing.

The extra is made missing inside each test: ``matplotlib`` is set to
``None`` in ``sys.modules``, so importing it raises ``ImportError``. Nothing
is uninstalled.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pairbench import api
from pairbench.charts import NOT_DRAWN_MESSAGE, PLOT_EXTRA, draw_charts
from pairbench.errors import Refusal
from pairbench.model import NOTE_CHARTS_NOT_DRAWN, Results

CHART_MODULES = (
    "pairbench.charts",
    "pairbench.charts.verdict",
    "pairbench.charts.rounds",
    "pairbench.charts.noise",
    "pairbench.charts.resources",
)


@pytest.fixture
def no_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every import of matplotlib fail for the length of one test."""
    for name in [m for m in sys.modules if m == "matplotlib" or m.startswith("matplotlib.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "matplotlib", None)


@pytest.mark.usefixtures("no_extra")
def test_the_extra_counts_as_missing_under_the_switch() -> None:
    with pytest.raises(ImportError):
        importlib.import_module("matplotlib")
    assert api.plot_extra_installed() is False


@pytest.mark.usefixtures("no_extra")
def test_auto_without_the_extra_draws_nothing_and_says_so_once(
    chart_results: Results, tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    paths = draw_charts(chart_results, out=tmp_path, note=lambda c, m: calls.append((c, m)))
    assert paths == []
    assert calls == [(NOTE_CHARTS_NOT_DRAWN, NOT_DRAWN_MESSAGE)]
    assert NOTE_CHARTS_NOT_DRAWN == "charts_not_drawn"
    assert PLOT_EXTRA == "pairbench[plot]"
    assert NOT_DRAWN_MESSAGE == (
        "charts were not drawn: the plot extra is not installed; install pairbench[plot] "
        "and run pairbench report --plots on in the run folder to draw them"
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("no_extra")
def test_the_public_draw_prints_the_note_on_standard_error(
    chart_results: Results, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import pairbench

    calls: list[tuple[str, str]] = []
    assert pairbench.draw(chart_results, out=tmp_path, note=lambda c, m: calls.append((c, m))) == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"pairbench: note: charts_not_drawn: {NOT_DRAWN_MESSAGE}\n"
    assert calls == [(NOTE_CHARTS_NOT_DRAWN, NOT_DRAWN_MESSAGE)]


@pytest.mark.usefixtures("no_extra")
def test_on_without_the_extra_is_refused_before_any_launch() -> None:
    with pytest.raises(Refusal) as refused:
        api.require_plot_extra("on")
    assert refused.value.code == "E_PLOT_EXTRA_MISSING"
    assert refused.value.exit_code == 3
    assert refused.value.scope == "experiment"


@pytest.mark.usefixtures("no_extra")
@pytest.mark.parametrize("mode", ["auto", "off"])
def test_auto_and_off_without_the_extra_are_not_refused(mode: str) -> None:
    assert api.require_plot_extra(mode) is None


def test_every_chart_module_imports_without_the_extra() -> None:
    script = (
        "import importlib, sys\n"
        "sys.modules['matplotlib'] = None\n"
        f"for name in {CHART_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "print(sorted(m for m in sys.modules if m.startswith('matplotlib')))\n"
    )
    source = Path(__file__).resolve().parents[3] / "src"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source), *filter(None, [os.environ.get("PYTHONPATH")])]
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stdout, done.stderr) == (0, "['matplotlib']\n", "")
