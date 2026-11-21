# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The chart files: byte-equal redraws, text kept as text, names as character data.

Every test here needs the plot extra and carries the marker ``needs_plot``,
so it is skipped with a message that names the extra where it is missing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from pairbench import model
from pairbench.charts import draw_charts, noise, resources, rounds, verdict
from pairbench.model import (
    NOTE_CHART_WITHOUT_DATA,
    NOTE_ROUND_CHARTS_LEFT_OUT,
    Diagnostics,
    Results,
)

pytestmark = pytest.mark.needs_plot

SVG = "{http://www.w3.org/2000/svg}"
# A case name that looks like markup, script and three kinds of reference.
HOSTILE_CASE = "<script>alert(1)</script> <img src=x> url(y.css) @import z &amp;"


def texts(content: bytes) -> list[str]:
    """Return the text of every text element of an SVG file, as a viewer reads it."""
    root = ET.fromstring(content)
    return ["".join(element.itertext()) for element in root.iter(f"{SVG}text")]


def element_names(content: bytes) -> set[str]:
    """Return the names of every element of an SVG file, without the SVG namespace."""
    return {element.tag.removeprefix(SVG) for element in ET.fromstring(content).iter()}


def notes_of(calls: list[tuple[str, str]]) -> list[str]:
    return [code for code, _ in calls]


# ---------------------------------------------------------------------------
# Each chart, drawn twice
# ---------------------------------------------------------------------------


def test_the_verdict_chart_is_byte_equal_twice_and_holds_its_words_as_text(
    chart_results: Results,
) -> None:
    first = verdict.draw(verdict.rows(chart_results))
    assert verdict.draw(verdict.rows(chart_results)) == first
    shown = texts(first)
    assert "matmul: new vs old" in shown
    assert "c32/ttft_ms: new vs old" in shown
    assert "1.25x faster   FASTER" in shown
    assert "1.25x slower   SLOWER" in shown
    assert "no difference (1x)" in shown
    assert [t for t in shown if t.endswith("x") and t[0].isdigit()] == [
        "0.8x",
        "0.909x",
        "1x",
        "1.1x",
        "1.25x",
    ]


def test_a_round_chart_is_byte_equal_twice_and_names_every_entry(chart_results: Results) -> None:
    chart = rounds.plan(chart_results, 12).charts[0]
    first = rounds.draw(chart)
    assert rounds.draw(chart) == first
    shown = texts(first)
    for label in (
        "Round by round: matmul",
        "new",
        "new~same",
        "old",
        "old~same",
        "disturbed round",
        "round",
        "time (s)",
    ):
        assert label in shown


def test_a_round_chart_without_disturbed_rounds_has_no_such_legend_entry(
    chart_results: Results,
) -> None:
    chart = rounds.plan(chart_results, 12).charts[1]
    shown = texts(rounds.draw(chart))
    assert "Round by round: c32/ttft_ms" in shown
    assert "ttft_ms (ms)" in shown
    assert "disturbed round" not in shown


def test_the_noise_chart_is_byte_equal_twice_and_names_each_twin(chart_results: Results) -> None:
    chart_rows = noise.rows(chart_results)
    first = noise.draw(chart_rows)
    assert noise.draw(chart_rows) == first
    shown = texts(first)
    for label in (
        "floor group: metric time, primary cases",
        "new against new~same: matmul",
        "1.004x, floor ±0.4%",
        "noise floor of the side",
    ):
        assert label in shown


def test_the_resource_chart_is_byte_equal_twice_and_writes_each_median(
    chart_results: Results,
) -> None:
    chart_panels = resources.panels(chart_results)
    first = resources.draw(chart_panels)
    assert resources.draw(chart_panels) == first
    shown = texts(first)
    for label in (
        "res/cores (cores): new against old: HIGHER",
        "res/rss_peak (bytes): new against old: LOWER",
        " 8.00 cores",
        " 1.00 cores",
        " 1000000000 bytes",
        "new",
        "old",
    ):
        assert label in shown


def test_a_resource_bar_without_a_value_says_so(chart_document: dict[str, Any]) -> None:
    chart_document["comparisons"][2]["baseline_median"] = None
    chart_panels = resources.panels(Results.from_json(chart_document))
    assert " no value" in texts(resources.draw(chart_panels))


def test_a_verdict_row_without_a_ratio_is_drawn_as_words(chart_document: dict[str, Any]) -> None:
    chart_document["comparisons"][0].update(
        ratio=None,
        bar=None,
        verdict="NO VERDICT",
        outcome="no_verdict",
        reason="nonpositive_value",
        reasons=["nonpositive_value"],
    )
    shown = texts(verdict.draw(verdict.rows(Results.from_json(chart_document))))
    assert "no ratio   NO VERDICT (nonpositive_value)" in shown


def test_a_redraw_in_another_process_is_byte_equal(chart_results: Results, tmp_path: Path) -> None:
    first = verdict.draw(verdict.rows(chart_results))
    (tmp_path / "results.json").write_text(json.dumps(chart_results.to_json()), encoding="utf-8")
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from pairbench.model import Results\n"
        "from pairbench.charts import verdict\n"
        "folder = Path(sys.argv[1])\n"
        "results = Results.from_json(json.loads((folder / 'results.json').read_text()))\n"
        "(folder / 'verdict.svg').write_bytes(verdict.draw(verdict.rows(results)))\n"
    )
    source = Path(__file__).resolve().parents[3] / "src"
    environment = dict(os.environ, PYTHONHASHSEED="12345")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source), *filter(None, [os.environ.get("PYTHONPATH")])]
    )
    done = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stderr) == (0, "")
    assert (tmp_path / "verdict.svg").read_bytes() == first


# ---------------------------------------------------------------------------
# What every chart file holds and does not hold
# ---------------------------------------------------------------------------


def test_draw_charts_writes_the_four_kinds_in_order_under_charts(
    chart_results: Results, tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    paths = draw_charts(chart_results, out=tmp_path, note=lambda c, m: calls.append((c, m)))
    assert paths == [
        tmp_path / "charts/verdict.svg",
        tmp_path / "charts/rounds.matmul.svg",
        tmp_path / "charts/rounds.c32_ttft_ms.svg",
        tmp_path / "charts/noise.svg",
        tmp_path / "charts/resources.svg",
    ]
    assert calls == []
    assert sorted(p.name for p in (tmp_path / "charts").iterdir()) == sorted(p.name for p in paths)


def test_every_chart_file_is_self_contained_dateless_and_keeps_text_as_text(
    chart_results: Results, tmp_path: Path
) -> None:
    for path in draw_charts(chart_results, out=tmp_path):
        content = path.read_bytes()
        text = content.decode("utf-8")
        assert model.points_outside(text) == (), path.name
        assert "<!DOCTYPE" not in text
        assert "<metadata" not in text
        assert "dc:date" not in text
        assert "http://www.w3.org/1999/xlink" in text
        assert "DejaVuSans-" not in text
        assert len(texts(content)) > 3


def test_a_name_that_looks_like_markup_stays_text(
    chart_document: dict[str, Any], tmp_path: Path
) -> None:
    chart_document["cases"][0]["id"] = HOSTILE_CASE
    chart_document["comparisons"][0]["case"] = HOSTILE_CASE
    chart_document["same_vs_same"][0]["case"] = HOSTILE_CASE
    for series in chart_document["series"]:
        if series["case"] == "matmul":
            series["case"] = HOSTILE_CASE
    results = Results.from_json(chart_document)
    paths = draw_charts(results, out=tmp_path)
    names = model.file_names([HOSTILE_CASE, "c32/ttft_ms"])
    assert tmp_path / model.chart_file("rounds", names[HOSTILE_CASE]) in paths
    for path in paths:
        content = path.read_bytes()
        text = content.decode("utf-8")
        assert model.points_outside(text) == (), path.name
        assert {"script", "img", "a", "foreignObject", "image"} & element_names(content) == set()
        assert "<script" not in text
    shown = texts((tmp_path / "charts/verdict.svg").read_bytes())
    assert f"{HOSTILE_CASE}: new vs old" in shown
    raw = (tmp_path / "charts/verdict.svg").read_text(encoding="utf-8")
    assert "&lt;img src&#61;x&gt; url&#40;y.css) &#64;import z &amp;amp;" in raw


@pytest.mark.filterwarnings("ignore:Glyph")
def test_a_name_with_control_characters_still_gives_well_formed_files(
    chart_document: dict[str, Any], tmp_path: Path
) -> None:
    name = "a\x01b\x1bc\x00d"
    chart_document["cases"][0]["id"] = name
    chart_document["comparisons"][0]["case"] = name
    for series in chart_document["series"]:
        if series["case"] == "matmul":
            series["case"] = name
    paths = draw_charts(Results.from_json(chart_document), out=tmp_path)
    assert len(paths) == 5
    parsed = {path.name: texts(path.read_bytes()) for path in paths}
    assert "a\ufffdb\ufffdc\ufffdd: new vs old" in parsed["verdict.svg"]
    assert "Round by round: a\ufffdb\ufffdc\ufffdd" in parsed["rounds.a_b_c_d.svg"]


@pytest.mark.filterwarnings("error")
def test_ratios_and_bars_far_beyond_any_axis_are_still_drawn(
    chart_document: dict[str, Any],
) -> None:
    chart_document["comparisons"][0].update(ratio=1e-300, statistic=1e-300)
    chart_document["comparisons"][1].update(bar=1e308)
    shown = texts(verdict.draw(verdict.rows(Results.from_json(chart_document))))
    assert [t for t in shown if t.endswith("x") and t[0].isdigit()] == ["0.001x", "1x", "1000x"]
    assert "1e+300x faster   FASTER" in shown
    assert "c32/ttft_ms: new vs old" in shown


# A value near the top of the float range: the margins and ticks of a linear
# axis around it are no finite numbers unless the axis is scaled first.
NEAR_FLOAT_MAX = 1.7e308
NEAR_FLOAT_MIN = -1e308
NUMBER = re.compile(r"\s?-?\d[\d.]*(e[+-]\d+)?")


def _axis_numbers(shown: list[str]) -> list[float]:
    return [float(text) for text in shown if NUMBER.fullmatch(text)]


def test_values_near_the_top_of_the_float_range_are_drawn_with_their_own_labels(
    chart_document: dict[str, Any], tmp_path: Path
) -> None:
    chart_document["series"][0]["values"][1] = NEAR_FLOAT_MAX
    chart_document["series"][2]["values"][1] = NEAR_FLOAT_MIN
    for comparison in chart_document["comparisons"]:
        if comparison["case"] == "res/rss_peak":
            comparison["subject_median"] = NEAR_FLOAT_MAX
    paths = draw_charts(Results.from_json(chart_document), out=tmp_path)
    assert [path.name for path in paths] == [
        "verdict.svg",
        "rounds.matmul.svg",
        "rounds.c32_ttft_ms.svg",
        "noise.svg",
        "resources.svg",
    ]
    round_labels = texts((tmp_path / "charts/rounds.matmul.svg").read_bytes())
    resource_labels = texts((tmp_path / "charts/resources.svg").read_bytes())
    assert max(_axis_numbers(round_labels)) >= 1e308
    assert min(_axis_numbers(round_labels)) <= -1e307
    assert max(_axis_numbers(resource_labels)) >= 1e308
    assert " 1.70e+308 bytes" in resource_labels
    for path in paths:
        assert not any(re.search(r"\b(inf|nan)\b", t) for t in texts(path.read_bytes()))


def test_charts_beyond_the_cap_are_a_note_with_their_count(
    chart_results: Results, tmp_path: Path
) -> None:
    calls: list[tuple[str, str]] = []
    paths = draw_charts(
        chart_results, out=tmp_path, max_round_charts=1, note=lambda c, m: calls.append((c, m))
    )
    assert [p.name for p in paths] == [
        "verdict.svg",
        "rounds.matmul.svg",
        "noise.svg",
        "resources.svg",
    ]
    assert calls == [
        (
            NOTE_ROUND_CHARTS_LEFT_OUT,
            "round-by-round charts were drawn for 1 primary cases and not for 1 more; "
            "raise plots.max_round_charts to draw them",
        )
    ]


def test_a_chart_whose_data_is_absent_is_not_drawn_and_the_reason_is_a_note(
    chart_document: dict[str, Any], tmp_path: Path
) -> None:
    chart_document["same_vs_same"] = []
    chart_document["comparisons"] = chart_document["comparisons"][:2]
    chart_document["series"] = [s for s in chart_document["series"] if s["case"] == "matmul"]
    calls: list[tuple[str, str]] = []
    paths = draw_charts(
        Results.from_json(chart_document), out=tmp_path, note=lambda c, m: calls.append((c, m))
    )
    assert [p.name for p in paths] == ["verdict.svg", "rounds.matmul.svg"]
    assert calls == [
        (
            NOTE_CHART_WITHOUT_DATA,
            "round-by-round chart of case c32/ttft_ms not drawn: the results hold no value for it",
        ),
        (
            NOTE_CHART_WITHOUT_DATA,
            "noise chart not drawn: the run had no twins, so the results hold no "
            "same-against-same row",
        ),
        (
            NOTE_CHART_WITHOUT_DATA,
            "resource chart not drawn: the results hold no res/ cases with a value",
        ),
    ]


def test_the_resource_chart_is_drawn_from_the_diagnostics_when_the_results_have_no_res_cases(
    chart_document: dict[str, Any], example_diagnostics: dict[str, Any], tmp_path: Path
) -> None:
    chart_document["comparisons"] = chart_document["comparisons"][:2]
    paths = draw_charts(
        Results.from_json(chart_document),
        out=tmp_path,
        diagnostics=Diagnostics.from_json(example_diagnostics),
    )
    assert paths[-1] == tmp_path / "charts/resources.svg"
    assert "res/cores (cores): new against old: HIGHER" in texts(paths[-1].read_bytes())


def test_results_with_nothing_to_draw_give_no_file_and_a_note_per_chart(
    example_results: dict[str, Any], tmp_path: Path
) -> None:
    example_results["comparisons"] = []
    example_results["same_vs_same"] = []
    example_results["series"] = []
    example_results["cases"] = []
    calls: list[tuple[str, str]] = []
    paths = draw_charts(
        Results.from_json(example_results), out=tmp_path, note=lambda c, m: calls.append((c, m))
    )
    assert paths == []
    assert notes_of(calls) == [NOTE_CHART_WITHOUT_DATA] * 3
    assert not (tmp_path / "charts").exists()


def test_a_failure_while_drawing_leaves_no_file_behind(
    chart_results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(chart_rows: Any) -> bytes:
        raise RuntimeError("a made-up failure")

    monkeypatch.setattr(noise, "draw", broken)
    with pytest.raises(RuntimeError, match="a made-up failure"):
        draw_charts(chart_results, out=tmp_path)
    assert not (tmp_path / "charts").exists()
