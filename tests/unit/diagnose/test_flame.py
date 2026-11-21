# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The flame graph and the difference graph: repeatable, self-contained, escaped, interactive."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from pairbench.diagnose import flame
from pairbench.model import points_outside

SVG = "{http://www.w3.org/2000/svg}"
STACKS = {
    ("main", "spin"): 6,
    ("main", "nap"): 2,
    ("main",): 2,
}
BASELINE = {
    ("main", "spin"): 2,
    ("main", "nap"): 4,
    ("main", "only_in_old"): 2,
}
HOSTILE = (
    "<script>alert(1)</script>",
    '"><a href="https://example.invalid/x">made-up</a>',
    "]]><script>alert(2)</script>",
    "url(https://example.invalid/font.woff)",
    '@import "https://example.invalid/sheet.css"',
    "src=https://example.invalid/x.js",
    "bad\x01character",
)


def _frames(svg: str) -> dict[str, ET.Element]:
    """Return each frame of a graph by the name that opens its title."""
    tree = ET.fromstring(svg.encode("utf-8"))
    found: dict[str, ET.Element] = {}
    for group in tree.iter(f"{SVG}g"):
        if group.get("class") == "f":
            title = group.find(f"{SVG}title")
            assert title is not None and title.text is not None
            found[title.text.split("\n")[0]] = group
    return found


def test_two_writes_of_the_same_stacks_are_equal_byte_for_byte() -> None:
    first = flame.flame_svg(STACKS, side="new", instrument="stacks")
    assert first == flame.flame_svg(
        dict(reversed(list(STACKS.items()))), side="new", instrument="stacks"
    )
    diff = flame.flame_diff_svg(
        STACKS, BASELINE, subject="new", baseline="old", instrument="stacks"
    )
    assert diff == flame.flame_diff_svg(
        STACKS, BASELINE, subject="new", baseline="old", instrument="stacks"
    )


def test_nothing_in_a_graph_points_outside_it() -> None:
    hostile = {("main", name): 1 for name in HOSTILE}
    assert points_outside(flame.flame_svg(hostile, side="new", instrument="stacks")) == ()
    assert (
        points_outside(
            flame.flame_diff_svg(
                hostile, hostile, subject="new", baseline="old", instrument="stacks"
            )
        )
        == ()
    )
    assert (
        points_outside(
            flame.flame_diff_svg(
                {("a",): 1}, hostile, subject="new", baseline="old", instrument="stacks"
            )
        )
        == ()
    )


def test_a_name_that_looks_like_markup_or_script_stays_text() -> None:
    hostile = {("main", name): 1 for name in HOSTILE}
    svg = flame.flame_svg(hostile, side="new", instrument="stacks")
    tree = ET.fromstring(svg.encode("utf-8"))
    assert [e.tag for e in tree.iter() if e.tag in (f"{SVG}script", f"{SVG}a", "script", "a")] == [
        f"{SVG}script"
    ]
    names = set(_frames(svg))
    assert {"all", "main", "<script>alert(1)</script>", "bad�character"} <= names
    assert '"><a href="https://example.invalid/x">made-up</a>' in names
    assert "<script>alert" not in svg
    assert "href=" not in svg


def test_a_side_name_that_looks_like_markup_stays_text() -> None:
    svg = flame.flame_svg(STACKS, side="<b>new</b>", instrument="stacks")
    assert "<b>" not in svg
    assert "Flame graph of side <b>new</b>" in "".join(ET.fromstring(svg.encode()).itertext())


def test_the_script_holds_no_name() -> None:
    svg = flame.flame_svg({("marker_name_in_the_code",): 1}, side="new", instrument="stacks")
    script = svg[svg.index("<script") : svg.index("</script>")]
    assert "marker_name_in_the_code" not in script
    assert "marker_name_in_the_code" in svg


def test_the_graph_can_zoom_reset_search_and_show_a_name_with_its_share() -> None:
    svg = flame.flame_svg(STACKS, side="new", instrument="stacks")
    texts = {
        t.get("class"): t for t in ET.fromstring(svg.encode()).iter(f"{SVG}text") if t.get("class")
    }
    assert texts["pb-ctl pb-reset"].text == "Reset zoom"
    assert texts["pb-ctl pb-search"].text == "Search: type to mark frames"
    assert "pb-matched" in texts and "pb-details" in texts
    script = svg[svg.index("<script") : svg.index("</script>")]
    for word in (
        'addEventListener("click"',
        '"keydown"',
        '"mouseover"',
        'querySelector(".pb-reset")',
    ):
        assert word in script
    spin = _frames(svg)["spin"]
    title = spin.find(f"{SVG}title")
    assert title is not None and title.text == "spin\n6 samples, 60.00% of samples"
    assert (spin.get("data-s"), spin.get("data-n"), spin.get("data-d")) == ("2", "6", "2")


def test_the_root_spans_the_width_and_a_frame_sits_on_its_caller() -> None:
    frames = _frames(flame.flame_svg(STACKS, side="new", instrument="stacks"))
    rects = {name: g.find(f"{SVG}rect") for name, g in frames.items()}
    assert {
        n: (r.get("x"), r.get("y"), r.get("width")) for n, r in rects.items() if r is not None
    } == {
        "all": ("10.00", "98.00", "1180.00"),
        "main": ("10.00", "82.00", "1180.00"),
        "nap": ("10.00", "66.00", "236.00"),
        "spin": ("246.00", "66.00", "708.00"),
    }


def test_the_graph_says_which_instrument_made_it_and_that_it_holds_names() -> None:
    perf = flame.flame_svg(STACKS, side="new", instrument="stacks")
    sampler = flame.flame_svg(STACKS, side="new", instrument="pystacks")
    assert "Stacks sampled by perf record, read back with perf script" in perf
    assert "Python frames only" in sampler
    for svg in (perf, sampler):
        assert svg.splitlines()[2] == (
            "<!-- pairbench flame graph. This file holds names from the user's code. -->"
        )
        assert "This graph holds names from the user&#x27;s code." in svg


def test_a_graph_without_samples_says_so() -> None:
    svg = flame.flame_svg({}, side="new", instrument="stacks")
    assert "No samples were taken." in svg
    assert "<script" not in svg
    ET.fromstring(svg.encode())


def test_the_difference_graph_takes_its_widths_from_the_subject() -> None:
    svg = flame.flame_diff_svg(STACKS, BASELINE, subject="new", baseline="old", instrument="stacks")
    frames = _frames(svg)
    assert set(frames) == {"all", "main", "nap", "spin"}
    spin = frames["spin"]
    assert spin.get("data-n") == "6"
    title = spin.find(f"{SVG}title")
    assert title is not None and title.text == (
        "spin\nnew: 60.00% of samples (6)\nold: 25.00% of samples (2)\n"
        "change: +35.00 percentage points"
    )


def test_the_difference_graph_colours_a_frame_by_the_change_in_its_share() -> None:
    frames = _frames(
        flame.flame_diff_svg(STACKS, BASELINE, subject="new", baseline="old", instrument="stacks")
    )
    fills = {name: g.find(f"{SVG}rect").get("fill") for name, g in frames.items()}  # type: ignore[union-attr]
    assert fills["spin"] == "#ff3737"
    assert fills["nap"] == "#5151ff"
    assert fills["main"] == "#ebebeb"
    assert fills["all"] == "#c8c8c8"


def test_the_legend_says_in_words_which_colour_means_which_side() -> None:
    svg = flame.flame_diff_svg(STACKS, BASELINE, subject="new", baseline="old", instrument="stacks")
    words = " ".join(ET.fromstring(svg.encode()).itertext())
    assert (
        "Widths are the samples of new. "
        "Red: the frame has a larger share of samples on new than on old." in words
    )
    assert "Blue: the frame has a larger share of samples on old." in words


def test_stacks_only_the_baseline_has_are_listed_under_the_graph() -> None:
    svg = flame.flame_diff_svg(STACKS, BASELINE, subject="new", baseline="old", instrument="stacks")
    words = " ".join(ET.fromstring(svg.encode()).itertext())
    assert "Stacks only old has, not drawn above, largest share first:" in words
    assert re.search(r"25\.00%\s+main;only_in_old", words)
    assert "only_in_old" not in _frames(svg)


def test_a_stack_both_sides_have_is_not_listed_as_one_only_the_baseline_has() -> None:
    svg = flame.flame_diff_svg(STACKS, BASELINE, subject="new", baseline="old", instrument="stacks")
    listed = [
        group.findtext(f"{SVG}title")
        for group in ET.fromstring(svg.encode()).iter(f"{SVG}g")
        if group.get("class") is None and group.find(f"{SVG}title") is not None
    ]
    assert listed == ["main;only_in_old"]


def test_a_long_list_of_stacks_only_the_baseline_has_is_cut_and_says_so() -> None:
    baseline = {("main", f"f{i:03d}"): 1 for i in range(flame.LIST_MAX + 5)}
    svg = flame.flame_diff_svg(STACKS, baseline, subject="new", baseline="old", instrument="stacks")
    assert "and 5 more stacks only old has: see the difference file." in svg


@pytest.mark.parametrize(
    ("name", "width", "shown"),
    [("abcdefghij", 50.0, "abcd.."), ("abcdefghij", 200.0, "abcdefghij"), ("abc", 20.0, "")],
)
def test_a_name_is_shortened_inside_a_narrow_frame(name: str, width: float, shown: str) -> None:
    assert flame.fit(name, width) == shown


def test_a_name_shortened_in_its_frame_is_complete_in_its_title() -> None:
    name = "a_function_name_far_too_long_for_its_frame"
    frames = _frames(
        flame.flame_svg({("main", name): 1, ("main", "wide"): 99}, side="new", instrument="stacks")
    )
    title = frames[name].find(f"{SVG}title")
    text = frames[name].find(f"{SVG}text")
    assert title is not None and title.text is not None and title.text.startswith(name + "\n")
    assert text is not None and text.text is None


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("a<b>&c", "a&lt;b&gt;&amp;c"),
        ('x="y"', "x&#61;&quot;y&quot;"),
        ("url(z)", "url&#40;z&#41;"),
        ("@import", "&#64;import"),
        ("it's", "it&#x27;s"),
        ("nul\x00", "nul�"),
    ],
)
def test_what_escaping_does_to_a_name(raw: str, escaped: str) -> None:
    assert flame.escape(raw) == escaped
