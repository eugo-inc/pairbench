# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The report page is self-contained and turns no run text into markup, script or an address."""

from __future__ import annotations

import base64
import copy
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from pairbench import model
from pairbench.api import ReportOptions
from pairbench.model import Diagnostics, Results
from pairbench.page.html import NAMES_LINE, embed, render_page, text

# Text that looks like markup, script, an event handler and three kinds of reference.
HOSTILE = (
    "<script>alert(1)</script><img src=x onerror=alert(2)> url(evil.css) "
    "@import 'x.css'; href=\"//example.invalid\" & </td></table>"
)
# A side name a results document may hold: no white space.
HOSTILE_SIDE = "<i>side</i>"
# The elements the page is made of. Nothing else may appear in it.
ALLOWED_TAGS = frozenset(
    {
        "html",
        "head",
        "meta",
        "title",
        "style",
        "body",
        "header",
        "main",
        "section",
        "h1",
        "h2",
        "h3",
        "h4",
        "p",
        "ul",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "code",
        "figure",
        "figcaption",
        "img",
        "iframe",
    }
)


class _Reader(HTMLParser):
    """Collects every start tag with its attributes and all character data of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, list[tuple[str, str | None]]]] = []
        self.data: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, attrs))

    def handle_data(self, data: str) -> None:
        self.data.append(data)


def read(page: str) -> _Reader:
    reader = _Reader()
    reader.feed(page)
    reader.close()
    return reader


def hostile_documents(
    page_document: dict[str, Any], example_diagnostics: dict[str, Any]
) -> tuple[Results, Diagnostics]:
    """Put hostile text in every free-text field the page shows."""
    doc = copy.deepcopy(page_document)
    doc["run"]["id"] = HOSTILE
    doc["run"]["command"] = HOSTILE
    doc["run"]["captures"][0]["capture_id"] = HOSTILE
    doc["rule"]["plain"] = HOSTILE
    doc["rule"]["name"] = HOSTILE
    doc["provenance"]["config_sha256"] = HOSTILE
    doc["machine_state"]["degraded"] = [
        {"name": "census", "status": "unavailable", "message": HOSTILE}
    ]
    doc["cases"][0]["id"] = HOSTILE
    doc["comparisons"][0]["case"] = HOSTILE
    doc["comparisons"][0]["subject"] = HOSTILE_SIDE
    doc["comparisons"][1]["subject"] = HOSTILE_SIDE
    doc["same_vs_same"][0].update(case=HOSTILE, side=HOSTILE_SIDE)
    doc["controls"]["positive"]["cases"][0]["case"] = HOSTILE
    doc["refusals"] = [{"code": "E_GRID", "scope": "case", "message": HOSTILE}]
    doc["notes"] = [{"code": "floor_provisional", "message": HOSTILE}]
    doc["artifacts"]["charts"] = [f"charts/{HOSTILE_SIDE}.svg"]
    doc["artifacts"]["profiles"] = [f"profiles/{HOSTILE_SIDE}.flame.svg"]
    diagnostics = copy.deepcopy(example_diagnostics)
    diagnostics["findings"][0]["text"] = HOSTILE
    diagnostics["stacks"][0]["side"] = HOSTILE_SIDE
    diagnostics["stacks"][0]["top_functions"][0].update(name=HOSTILE, object=HOSTILE)
    diagnostics["stacks"][0]["top_objects"][0]["name"] = HOSTILE
    diagnostics["objects"] = {
        "only_in": {HOSTILE_SIDE: [HOSTILE], "old": []},
        "differ": [{"name": HOSTILE, HOSTILE_SIDE: HOSTILE, "old": "bb22"}],
    }
    diagnostics["counters"][0].update(event=HOSTILE, subject=HOSTILE_SIDE)
    diagnostics["instruments"][0]["side"] = HOSTILE_SIDE
    diagnostics["notes"] = [{"code": "instrument_skipped", "message": HOSTILE}]
    return Results.from_json(doc), Diagnostics.from_json(diagnostics)


def test_text_from_a_run_becomes_no_markup_and_no_address() -> None:
    assert text('<a href="x">(@)</a> & \'') == (
        "&lt;a href&#61;&quot;x&quot;&gt;&#40;&#64;)&lt;/a&gt; &amp; &#x27;"
    )


def test_hostile_text_in_every_field_stays_text(
    page_document: dict[str, Any], example_diagnostics: dict[str, Any], tmp_path: Path
) -> None:
    results, document = hostile_documents(page_document, example_diagnostics)
    flame = tmp_path / "profiles" / f"{HOSTILE_SIDE}.flame.svg"
    flame.parent.mkdir(parents=True)
    flame.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    page = render_page(results, ReportOptions(diagnostics=document, folder=tmp_path))
    reader = read(page)
    assert {tag for tag, _ in reader.tags} <= ALLOWED_TAGS
    for tag, attrs in reader.tags:
        for name, _value in attrs:
            assert not name.startswith("on"), (tag, name)
    assert "<script" not in page.lower()
    assert "<img src=x" not in page
    assert model.points_outside(page) == ()
    shown = "".join(reader.data)
    assert shown.count(HOSTILE) >= 15
    assert HOSTILE_SIDE in shown
    iframes = [dict(attrs) for tag, attrs in reader.tags if tag == "iframe"]
    assert [frame["title"] for frame in iframes] == [
        f"flame graph profiles/{HOSTILE_SIDE}.flame.svg"
    ]


def test_the_page_points_nowhere_outside_itself(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    results = Results.from_json(with_files)
    document = Diagnostics.from_json(example_diagnostics)
    for options in (
        ReportOptions(),
        ReportOptions(folder=run_folder),
        ReportOptions(diagnostics=document, folder=run_folder),
    ):
        page = render_page(results, options)
        assert model.points_outside(page) == ()
        assert re.findall(r"""(?:src|href)\s*=\s*["']?(?!data:)[^"'\s>]+""", page) == []


def test_the_page_forbids_every_fetch_and_allows_scripts_only_for_flame_graphs(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    results = Results.from_json(with_files)
    plain = render_page(results, ReportOptions(folder=run_folder))
    policy = (
        '<meta http-equiv="Content-Security-Policy" content="default-src '
        "'none'; img-src data:; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'\">"
    )
    assert policy in plain
    framed = render_page(
        results,
        ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics), folder=run_folder),
    )
    assert (
        "content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\""
    ) in framed


# The frame document a flame graph is embedded in, around the graph's own text.
FRAME_HEAD = (
    "<!DOCTYPE html><html><head><style>body{margin:0}svg{display:block}</style></head><body>"
)
FRAME_TAIL = "</body></html>"
# A browser may refuse an address of this length or more; no address on the page reaches it.
LONGEST_ADDRESS = 2 * 1024 * 1024


def test_an_embedded_flame_graph_keeps_its_script_inside_a_sandboxed_frame(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    page = render_page(
        Results.from_json(with_files),
        ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics), folder=run_folder),
    )
    frames = [dict(attrs) for tag, attrs in read(page).tags if tag == "iframe"]
    assert len(frames) == 1
    frame = frames[0]
    assert frame["sandbox"] == "allow-scripts"
    assert frame["style"] == "height: 200px"
    assert "src" not in frame
    flame = (run_folder / "profiles" / "new.flame.svg").read_text(encoding="utf-8")
    assert frame["srcdoc"] == FRAME_HEAD + flame + FRAME_TAIL
    assert "<script" not in page


def test_a_flame_graph_larger_than_any_address_is_still_embedded(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    path = run_folder / "profiles" / "new.flame.svg"
    frames_of_graph = "".join(
        f"<g><title>made_up_{i} (0.1%)</title><rect width='1' height='16'/></g>"
        for i in range(40000)
    )
    flame = path.read_text(encoding="utf-8").replace("</svg>", frames_of_graph + "</svg>")
    assert len(flame) > LONGEST_ADDRESS
    path.write_text(flame, encoding="utf-8")
    page = render_page(
        Results.from_json(with_files),
        ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics), folder=run_folder),
    )
    reader = read(page)
    frames = [dict(attrs) for tag, attrs in reader.tags if tag == "iframe"]
    assert len(frames) == 1
    assert frames[0]["srcdoc"] == FRAME_HEAD + flame + FRAME_TAIL
    addresses = [
        value or "" for _, attrs in reader.tags for name, value in attrs if name in ("src", "href")
    ]
    assert max(map(len, addresses)) < LONGEST_ADDRESS
    assert model.points_outside(page) == ()


def test_a_flame_graph_that_would_point_outside_once_embedded_is_named(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    path = run_folder / "profiles" / "new.flame.svg"
    flame = path.read_text(encoding="utf-8").replace("<g>", "<g><a href='#made-up'/>", 1)
    assert model.points_outside(flame) == ()
    path.write_text(flame, encoding="utf-8")
    page = render_page(
        Results.from_json(with_files),
        ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics), folder=run_folder),
    )
    assert [tag for tag, _ in read(page).tags if tag == "iframe"] == []
    assert (
        "Flame graph profiles/new.flame.svg is not shown: embedded in the page, it would read "
        "as pointing outside the page."
    ) in page
    assert model.points_outside(page) == ()


def test_a_page_that_would_point_outside_itself_is_refused(
    page_document: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import pairbench.page.html as page_html

    monkeypatch.setattr(page_html, "text", str)
    page_document["run"]["command"] = "<img src=https://example.invalid/made-up.png>"
    with pytest.raises(
        ValueError,
        match=r"^the report page points outside itself: src=https://example\.invalid/made-up\.png$",
    ):
        render_page(Results.from_json(page_document), ReportOptions())


def test_a_chart_is_embedded_as_a_picture_with_words_for_it(
    with_files: dict[str, Any], run_folder: Path
) -> None:
    page = render_page(Results.from_json(with_files), ReportOptions(folder=run_folder))
    pictures = [dict(attrs) for tag, attrs in read(page).tags if tag == "img"]
    assert [p["alt"] for p in pictures] == [
        "Verdict of each primary case",
        "Round by round: matmul",
    ]
    prefix = "data:image/svg+xml;base64,"
    for picture, name in zip(pictures, ("verdict.svg", "rounds.matmul.svg"), strict=True):
        source = picture["src"] or ""
        assert (
            base64.b64decode(source.removeprefix(prefix))
            == (run_folder / "charts" / name).read_bytes()
        )


@pytest.mark.parametrize(
    ("file", "content", "problem"),
    [
        ("charts/verdict.svg", None, "it is missing"),
        ("charts/verdict.png", "made-up", "it is not an SVG file"),
        ("charts/verdict.svg", "made-up text", "it is not an SVG file"),
        (
            "charts/verdict.svg",
            '<svg><image href="https://example.invalid/a.png"/></svg>',
            "it points outside itself",
        ),
        ("charts/verdict.svg", b"\xff\xfe<svg/>", "it cannot be read as UTF-8 text"),
    ],
)
def test_a_file_that_cannot_be_embedded_is_named_with_the_reason(
    tmp_path: Path, file: str, content: str | bytes | None, problem: str
) -> None:
    (tmp_path / "charts").mkdir()
    if isinstance(content, str):
        (tmp_path / file).write_text(content, encoding="utf-8")
    elif isinstance(content, bytes):
        (tmp_path / file).write_bytes(content)
    assert embed(tmp_path, file) == embed(tmp_path, file)
    found = embed(tmp_path, file)
    assert (found.data, found.problem) == (None, problem)


def test_a_file_outside_the_run_folder_is_not_embedded(tmp_path: Path) -> None:
    outside = tmp_path / "outside.svg"
    outside.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    folder = tmp_path / "run"
    (folder / "charts").mkdir(parents=True)
    (folder / "charts" / "linked.svg").symlink_to(outside)
    for file in ("../outside.svg", "/outside.svg", "charts/linked.svg"):
        found = embed(folder, file)
        assert (found.data, found.problem) == (None, "it lies outside the run folder"), file
    assert embed(None, "charts/verdict.svg").problem == "the page was made without the run folder"


def test_a_chart_that_points_outside_itself_is_left_out_of_the_page(
    with_files: dict[str, Any], run_folder: Path
) -> None:
    (run_folder / "charts" / "verdict.svg").write_text(
        "<svg><style>@import 'made-up.css';</style></svg>", encoding="utf-8"
    )
    page = render_page(Results.from_json(with_files), ReportOptions(folder=run_folder))
    assert "Chart charts/verdict.svg is not shown: it points outside itself." in page
    assert len([tag for tag, _ in read(page).tags if tag == "img"]) == 1
    assert model.points_outside(page) == ()


def test_the_line_about_names_is_there_exactly_when_the_diagnostics_are(
    with_files: dict[str, Any], example_diagnostics: dict[str, Any], run_folder: Path
) -> None:
    results = Results.from_json(with_files)
    document = Diagnostics.from_json(example_diagnostics)
    escaped = (
        "This page holds names from the user&#x27;s code: function names, shared-object "
        "names and sampled call stacks. results.json and results.md hold none of them."
    )
    with_names = render_page(results, ReportOptions(diagnostics=document))
    assert with_names.count(escaped) == 1
    assert with_names.index(escaped) < with_names.index("<main>")
    assert '<p class="names">' in with_names
    for options in (ReportOptions(), ReportOptions(folder=run_folder)):
        page = render_page(results, options)
        assert escaped not in page
        assert 'class="names"' not in page
        assert "made_up_function" not in page
        assert "libmade-up.so" not in page
    assert NAMES_LINE == (
        "This page holds names from the user's code: function names, shared-object names and "
        "sampled call stacks. results.json and results.md hold none of them."
    )


def test_flame_graphs_are_not_embedded_without_the_diagnostics(
    with_files: dict[str, Any], run_folder: Path
) -> None:
    page = render_page(Results.from_json(with_files), ReportOptions(folder=run_folder))
    assert [tag for tag, _ in read(page).tags if tag == "iframe"] == []
    assert (
        "Flame graphs hold names from the user&#x27;s code and are shown only on a page made "
        "with the diagnostics document. They are files in the run folder: "
        "profiles/new.flame.svg."
    ) in page
    assert "script-src" not in page
