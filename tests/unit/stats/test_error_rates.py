# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The error-rate simulation: seeded, both noise models, the page and the data file it writes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pairbench.report import odds

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "error_rates.py"
PAGE = ROOT / "docs" / "method" / "error-rates.md"
DATA = ROOT / "src" / "pairbench" / "report" / "error_rates.json"
SEED = 12345
EXPERIMENTS = 1500
SETTINGS = 216


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("error_rates_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_setting_of_the_error_rate_grid_is_simulated(tool: ModuleType) -> None:
    cells = tool.all_cells()
    assert len(cells) == 216
    assert {c.rounds for c in cells} == {8, 16, 24}
    assert {c.cases for c in cells} == {1, 4, 10}
    assert {c.noise for c in cells} == {0.01, 0.03, 0.10}
    assert {c.difference for c in cells} == {0, 1, 2, 4}
    assert {c.model for c in cells} == {"independent", "drift"}


def test_the_simulation_is_seeded(tool: ModuleType) -> None:
    cell = tool.Cell("drift", 8, 1, 0.03, 1)
    a = tool.simulate(cell, 5, 7)
    b = tool.simulate(cell, 5, 7)
    assert a == b
    assert a.experiments == 5
    assert a.comparisons == 5


def test_the_drift_model_shares_one_term_across_a_round(tool: ModuleType) -> None:
    import random

    cases = tool._cases(1)
    grid = tool.experiment(tool.Cell("drift", 4, 1, 0.01, 0), random.Random(1), cases)
    same = tool.experiment(tool.Cell("independent", 4, 1, 0.01, 0), random.Random(1), cases)
    assert grid.of("new", "case0") != same.of("new", "case0")


def test_a_large_true_difference_reads_slower(tool: ModuleType) -> None:
    tally = tool.simulate(tool.Cell("independent", 16, 1, 0.01, 4), 5, 3)
    assert tally.outcomes["worse"] == 5
    assert tally.verdict_rate == 1.0


def test_ten_cases_in_eight_rounds_give_no_verdict(tool: ModuleType) -> None:
    tally = tool.simulate(tool.Cell("independent", 8, 10, 0.03, 4), 2, 3)
    assert tally.outcomes["no_verdict"] == 20


def test_the_page_states_both_models_the_seed_and_the_count(tool: ModuleType) -> None:
    cells = [tool.Cell("independent", 8, 1, 0.01, 0), tool.Cell("drift", 8, 1, 0.01, 0)]
    page = tool.render(tool.run(3, 99, cells), 3, 99)
    assert "Seed: `99`" in page
    assert "Simulated experiments per setting: 3." in page
    assert "**Independent noise.**" in page
    assert "**Shared drift.**" in page
    assert "not frozen" not in page


def test_a_setting_without_a_difference_above_alpha_puts_a_note_at_the_top(
    tool: ModuleType,
) -> None:
    cell = tool.Cell("independent", 8, 1, 0.01, 0)
    tally = tool.Tally(experiments=10, comparisons=10, any_verdict=1)
    page = tool.render({cell: tally}, 10, 1)
    assert tool.over_alpha({cell: tally}) == [cell]
    front_matter, title, opening, note = page.split("\n\n")[:4]
    assert front_matter.startswith("---\ndescription: ")
    assert title.startswith("# ")
    assert opening[:1].isalpha()
    assert note.startswith("> **The default rule is not frozen.**")
    assert "10.0 percent" in page


def test_main_writes_the_page_and_the_data_file_and_returns_zero(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    few = [tool.Cell("independent", 8, 1, 0.01, 0)]
    monkeypatch.setattr(tool, "all_cells", lambda: few)
    out = tmp_path / "page.md"
    data = tmp_path / "rates.json"
    argv = ["--experiments", "2", "--seed", "4", "--out", str(out), "--data", str(data)]
    assert tool.main(argv) == 0
    assert "Seed: `4`" in out.read_text(encoding="utf-8")
    written = json.loads(data.read_text(encoding="utf-8"))
    assert (written["seed"], written["experiments"], written["rule"]) == (4, 2, "strict")
    assert len(written["settings"]) == 1


def test_the_data_file_holds_every_count_and_reads_back(tool: ModuleType) -> None:
    cells = [tool.Cell("drift", 8, 4, 0.03, 2), tool.Cell("independent", 16, 1, 0.01, 0)]
    results = tool.run(3, 5, cells)
    rates = odds.from_data(json.loads(tool.data_text(results, 3, 5)))
    assert (rates.seed, rates.experiments, rates.rule, rates.alpha) == (5, 3, "strict", 0.05)
    assert tool.results_of(rates) == results
    assert tool.render_data(rates) == tool.render(results, 3, 5)


def test_the_data_file_lists_the_settings_in_the_order_of_the_page(tool: ModuleType) -> None:
    cells = [tool.Cell("drift", 8, 1, 0.01, 0), tool.Cell("independent", 24, 10, 0.1, 4)]
    text = tool.data_text(tool.run(1, 1, cells), 1, 1)
    models = [json.loads(line.rstrip(","))["model"] for line in text.splitlines()[6:8]]
    assert models == ["independent", "drift"]


def test_the_package_carries_the_data_of_the_published_page(tool: ModuleType) -> None:
    rates = odds.error_rates()
    assert (rates.seed, rates.experiments) == (SEED, EXPERIMENTS)
    assert len(rates.settings) == SETTINGS
    assert tool.render_data(rates) == PAGE.read_text(encoding="utf-8")
    assert DATA.read_text(encoding="utf-8") == tool.data_text(
        tool.results_of(rates), EXPERIMENTS, SEED
    )
