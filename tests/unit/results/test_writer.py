# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Writing and reading results.json and results.md: replacement in one step, the two writes."""

from __future__ import annotations

import dataclasses
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import ReportOptions, delegate
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import (
    SECOND_WRITE_KEYS,
    DiagnosticsState,
    Note,
    PlotsState,
    Results,
    second_write_changes,
)
from pairbench.report.markdown import MarkdownReporter
from pairbench.results import load_schema
from pairbench.results.figures import with_figures
from pairbench.results.writer import (
    JsonReporter,
    read_results,
    results_text,
    write_results,
)

# The sections of results.md that may change between the two writes of a run.
SECOND_WRITE_SECTIONS = ("## Diagnostics and report page", "## Refusals and notes")


@pytest.fixture
def results(build: Any) -> Results:
    return with_figures(build())


def _files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_write_can_be_read_back_unchanged(results: Results, tmp_path: Path) -> None:
    written = write_results(results, tmp_path)
    assert read_results(tmp_path / "results.json") == written
    assert pairbench.load_results(tmp_path / "results.json") == written
    assert _files(tmp_path) == ["results.json", "results.md"]


def test_artifacts_name_the_files_of_the_folder_that_exist(
    results: Results, tmp_path: Path
) -> None:
    written = write_results(results, tmp_path)
    assert (written.artifacts.capture, written.artifacts.plan) == (None, None)
    assert written.artifacts.markdown == "results.md"
    (tmp_path / "capture.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "plan.tsv").write_text("x\n", encoding="utf-8")
    again = write_results(results, tmp_path)
    assert (again.artifacts.capture, again.artifacts.plan) == ("capture.jsonl", "plan.tsv")
    # The files the run lists itself stay as the results name them.
    assert (again.artifacts.html, again.artifacts.diagnostics) == (
        "report.html",
        "diagnostics.json",
    )


def test_profiles_are_kept_or_replaced(build: Any, tmp_path: Path) -> None:
    artifacts = {
        "capture": None,
        "markdown": None,
        "plan": None,
        "charts": [],
        "profiles": ["profiles/new.folded"],
    }
    results = build(artifacts=artifacts)
    assert write_results(results, tmp_path).artifacts.profiles == ("profiles/new.folded",)
    replaced = write_results(results, tmp_path, profiles=["profiles/new.flame.svg"])
    assert replaced.artifacts.profiles == ("profiles/new.flame.svg",)


def test_a_profile_named_from_the_root_is_refused_before_anything_is_written(
    results: Results, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="relative to the run folder"):
        write_results(results, tmp_path, profiles=["/abs/profiles/new.folded"])
    assert _files(tmp_path) == []


def test_the_json_file_is_the_json_report_and_keeps_the_shipped_schema(
    results: Results, tmp_path: Path
) -> None:
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    written = write_results(results, tmp_path)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert text == JsonReporter().render(written, ReportOptions()) == results_text(written)
    assert pairbench.render(written, "json") == text
    assert text.endswith("}\n")
    assert json.loads(text) == written.to_json()
    jsonschema.Draft202012Validator(load_schema("results")).validate(json.loads(text))


def test_the_markdown_file_is_the_markdown_report(results: Results, tmp_path: Path) -> None:
    written = write_results(results, tmp_path)
    text = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert text == MarkdownReporter().render(written, ReportOptions())


def test_the_folder_is_made_when_it_does_not_exist(results: Results, tmp_path: Path) -> None:
    write_results(results, tmp_path / "a" / "run")
    assert _files(tmp_path / "a" / "run") == ["results.json", "results.md"]


def test_a_folder_that_is_a_file_is_refused_with_its_name_only(
    results: Results, tmp_path: Path
) -> None:
    (tmp_path / "taken").write_text("kept\n")
    with pytest.raises(Refusal) as caught:
        write_results(results, tmp_path / "taken")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "the results folder taken is a file, not a folder"
    assert (tmp_path / "taken").read_text() == "kept\n"


def test_a_folder_under_a_file_is_refused_with_its_name_only(
    results: Results, tmp_path: Path
) -> None:
    (tmp_path / "taken").write_text("kept\n")
    with pytest.raises(Refusal) as caught:
        write_results(results, tmp_path / "taken" / "run")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("the results folder run cannot be written: ")
    assert str(tmp_path) not in caught.value.message


def test_a_folder_that_cannot_be_written_into_is_refused_with_its_name_only(
    results: Results, tmp_path: Path
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this user may write into a folder without write permission")
        with pytest.raises(Refusal) as caught:
            write_results(results, locked)
    finally:
        locked.chmod(0o700)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "the results folder locked cannot be written: Permission denied"


def _sections(text: str) -> dict[str, list[str]]:
    """Split a markdown report into its sections, keyed by their ``## `` headings."""
    out: dict[str, list[str]] = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line
        out.setdefault(heading, []).append(line)
    return out


def test_only_diagnostics_plots_artifacts_and_added_notes_differ_between_the_two_writes(
    results: Results, tmp_path: Path
) -> None:
    (tmp_path / "capture.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "plan.tsv").write_text("x\n", encoding="utf-8")
    write_results(results.pending(), tmp_path)
    first = read_results(tmp_path / "results.json")
    first_doc = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    first_md = _sections((tmp_path / "results.md").read_text(encoding="utf-8"))
    assert (first.diagnostics.status, first.plots.status) == ("pending", "pending")

    finished = first.finished(
        diagnostics=DiagnosticsState(status="written"),
        plots=PlotsState(status="not_drawn", reason="extra_missing"),
        notes=[Note(code="charts_not_drawn", message="a made-up note from the charts")],
        artifacts=dataclasses.replace(
            first.artifacts, html="report.html", charts=("charts/verdict.svg",)
        ),
    )
    write_results(finished, tmp_path, profiles=["profiles/new.flame.svg"])
    second = read_results(tmp_path / "results.json")
    second_doc = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    second_md = _sections((tmp_path / "results.md").read_text(encoding="utf-8"))

    assert second_write_changes(first, second) == ()
    changed = {
        key
        for key in first_doc.keys() | second_doc.keys()
        if first_doc.get(key) != second_doc.get(key)
    }
    assert changed == set(SECOND_WRITE_KEYS) == {"diagnostics", "plots", "artifacts", "notes"}
    assert second.notes[: len(first.notes)] == first.notes
    assert second.artifacts.profiles == ("profiles/new.flame.svg",)
    # In results.md only the sections of those keys differ.
    assert list(first_md) == list(second_md)
    differing = {heading for heading in first_md if first_md[heading] != second_md[heading]}
    assert differing == set(SECOND_WRITE_SECTIONS)


def test_a_second_write_that_changed_a_comparison_is_told(results: Results, tmp_path: Path) -> None:
    write_results(results.pending(), tmp_path)
    first = read_results(tmp_path / "results.json")
    changed = dataclasses.replace(
        first.finished(diagnostics=DiagnosticsState(status="off"), plots=PlotsState()),
        comparisons=(),
    )
    write_results(changed, tmp_path)
    assert second_write_changes(first, read_results(tmp_path / "results.json")) == ("comparisons",)


def test_each_file_is_replaced_in_one_step_and_the_markdown_first(
    results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_results(results.pending(), tmp_path)
    old = {name: (tmp_path / name).read_bytes() for name in ("results.json", "results.md")}
    finished = results.finished(diagnostics=DiagnosticsState(status="written"), plots=PlotsState())
    expected = {
        "results.json": None,
        "results.md": None,
    }
    seen: list[str] = []
    real_replace = os.replace

    def replace(src: Any, dst: Any) -> None:
        final = Path(dst)
        seen.append(final.name)
        # Up to this moment the final name holds the whole earlier document.
        assert final.read_bytes() == old[final.name]
        assert Path(src).parent == final.parent
        expected[final.name] = Path(src).read_text(encoding="utf-8")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    written = write_results(finished, tmp_path)
    assert seen == ["results.md", "results.json"]
    assert expected["results.json"] == results_text(written)
    assert expected["results.md"] == MarkdownReporter().render(written, ReportOptions())
    assert _files(tmp_path) == ["results.json", "results.md"]


def test_each_new_file_is_flushed_to_the_disk_before_it_replaces_the_old_one(
    results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(handle: int) -> None:
        events.append("fsync folder" if stat.S_ISDIR(os.fstat(handle).st_mode) else "fsync file")
        real_fsync(handle)

    def replace(src: Any, dst: Any) -> None:
        events.append(f"replace {Path(dst).name}")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    write_results(results, tmp_path)
    assert events == [
        "fsync file",
        "replace results.md",
        "fsync folder",
        "fsync file",
        "replace results.json",
        "fsync folder",
    ]


def test_a_failed_replacement_leaves_the_earlier_file_and_no_stray_file(
    results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_results(results.pending(), tmp_path)
    before = (tmp_path / "results.json").read_bytes()
    real_replace = os.replace

    def replace(src: Any, dst: Any) -> None:
        if Path(dst).name == "results.json":
            raise OSError(28, "No space left on device")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    finished = results.finished(diagnostics=DiagnosticsState(status="written"), plots=PlotsState())
    with pytest.raises(OSError, match="No space left"):
        write_results(finished, tmp_path)
    assert (tmp_path / "results.json").read_bytes() == before
    assert _files(tmp_path) == ["results.json", "results.md"]


def test_a_file_keeps_its_mode_and_a_new_one_is_readable_by_all(
    results: Results, tmp_path: Path
) -> None:
    write_results(results, tmp_path)
    assert stat.S_IMODE((tmp_path / "results.json").stat().st_mode) == 0o644
    os.chmod(tmp_path / "results.json", 0o600)
    write_results(results, tmp_path)
    assert stat.S_IMODE((tmp_path / "results.json").stat().st_mode) == 0o600


def test_a_missing_results_file_is_a_usage_error_naming_only_the_file(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        read_results(tmp_path / "nothing.json")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE == 2
    assert caught.value.message == "results file not found: nothing.json"
    assert str(tmp_path) not in caught.value.message


def test_a_file_that_is_not_json_is_a_usage_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{\n  not json\n", encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        read_results(bad)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "results file is not JSON: bad.json, line 2"


def test_a_document_that_is_no_results_document_is_a_usage_error(
    tmp_path: Path, example_results: dict[str, Any]
) -> None:
    other = tmp_path / "other.json"
    other.write_text(
        json.dumps({**example_results, "schema": "pairbench/results/v2"}), encoding="utf-8"
    )
    with pytest.raises(Refusal) as caught:
        read_results(other)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_a_number_that_is_not_finite_is_refused(
    tmp_path: Path, example_results: dict[str, Any]
) -> None:
    text = json.dumps(example_results).replace('"ratio": 0.797', '"ratio": NaN', 1)
    assert "NaN" in text
    nan = tmp_path / "nan.json"
    nan.write_text(text, encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        read_results(nan)
    assert caught.value.code == "E_USAGE"


def test_a_file_nested_too_deeply_is_a_usage_error(tmp_path: Path) -> None:
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        read_results(deep)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "results file is nested too deeply: deep.json"


def test_a_number_too_long_to_read_is_a_usage_error(tmp_path: Path) -> None:
    long = tmp_path / "long.json"
    long.write_text('{"schema": ' + "9" * 5000 + "}", encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        read_results(long)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("results file is not JSON: long.json: ")
    assert str(tmp_path) not in caught.value.message


def test_the_parts_and_the_reporter_are_these() -> None:
    assert delegate("write_results") is write_results
    assert delegate("load_results") is read_results
    assert delegate("figures") is with_figures
    reporter = registry.reporter("json")
    assert isinstance(reporter, JsonReporter)
    assert (reporter.name, reporter.api_version) == ("json", 1)


def test_the_json_report_ignores_the_display_options(results: Results) -> None:
    filtered = ReportOptions(cases=("nothing",), all_cases=True, verbose=True)
    assert JsonReporter().render(results, filtered) == results_text(results)


# The first lines of results.json: indented by two spaces, ``schema`` first.
RESULTS_JSON_HEAD = """\
{
  "schema": "pairbench/results/v1",
  "tool": {
    "name": "pairbench",
    "version": "0.1.0"
  },
  "run": {
    "id": "cap-000001",
"""


def test_the_text_form_of_results_json(build: Any, tmp_path: Path) -> None:
    name = "größe-ünïcode"
    results = build(comparisons=[{"case": name}], cases=((name, "s", "lower", "time", True),))
    write_results(results, tmp_path)
    raw = (tmp_path / "results.json").read_bytes()
    assert raw.startswith(RESULTS_JSON_HEAD.encode())
    assert f'"case": "{name}"'.encode() in raw
    assert b"\\u00" not in raw
    assert raw.endswith(b"\n}\n")
