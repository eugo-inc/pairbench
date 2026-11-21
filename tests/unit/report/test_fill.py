# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Filling figure tokens: keys, formats, several results files, missing keys, --check."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.api import delegate
from pairbench.errors import EXIT_FIGURE_MISSING, EXIT_USAGE, Refusal
from pairbench.model import Results
from pairbench.report import fill
from pairbench.report.fill import fill_text, is_current, parse_token

# Made-up figures; the texts are the ones the figures module writes for them.
FIGURES: dict[str, dict[str, Any]] = {
    "matmul.new_vs_old.ratio": {"value": 0.797, "text": "0.80x"},
    "matmul.new_vs_old.verdict": {"value": "better", "text": "FASTER"},
    "matmul.new_vs_old.n": {"value": 16, "text": "16"},
    "c32/ttft_ms_median.new.median": {"value": 41.0, "text": "41.0 ms"},
    "a|b.new_vs_old.ratio": {"value": 0.5, "text": "0.50x"},
}
OTHER_FIGURES: dict[str, dict[str, Any]] = {
    "matmul.new_vs_old.ratio": {"value": 0.6, "text": "0.60x"},
    "ttft_ms_median.new.median": {"value": 7.0, "text": "7.00 ms"},
}


@pytest.fixture
def results(build: Any) -> Results:
    return build(figures=FIGURES)  # type: ignore[no-any-return]


@pytest.fixture
def other(build: Any) -> Results:
    return build(figures=OTHER_FIGURES)  # type: ignore[no-any-return]


def test_a_token_without_format_is_the_figure_text(results: Results) -> None:
    assert fill_text("ratio {{fig:matmul.new_vs_old.ratio}}.", {"": results}) == "ratio 0.80x."


def test_a_format_is_applied_to_the_value(results: Results) -> None:
    text = "{{fig:matmul.new_vs_old.ratio|.3f}} {{fig:matmul.new_vs_old.n|03d}}"
    assert fill_text(text, {"": results}) == "0.797 016"


def test_an_empty_format_writes_the_value_as_python_does(results: Results) -> None:
    assert fill_text("{{fig:matmul.new_vs_old.ratio|}}", {"": results}) == "0.797"


def test_the_format_is_split_off_at_the_last_bar(results: Results) -> None:
    assert fill_text("{{fig:a|b.new_vs_old.ratio|.2f}}", {"": results}) == "0.50"
    assert parse_token("a|b.k|.2f", {}).key == "a|b.k"
    assert parse_token("a|b.k|.2f", {}).format == ".2f"


def test_a_case_id_with_a_slash_is_a_key_when_no_results_carry_that_name(
    results: Results, other: Results
) -> None:
    text = "{{fig:c32/ttft_ms_median.new.median}}"
    assert fill_text(text, {"": results, "old": other}) == "41.0 ms"


def test_the_text_before_the_first_slash_names_results_given_under_that_name(
    results: Results, other: Results
) -> None:
    text = "{{fig:matmul.new_vs_old.ratio}} against {{fig:old/matmul.new_vs_old.ratio}}"
    assert fill_text(text, {"": results, "old": other}) == "0.80x against 0.60x"
    # A results name that equals the first part of a case id wins over the case id.
    named = "{{fig:c32/ttft_ms_median.new.median}}"
    assert fill_text(named, {"": results, "c32": other}) == "7.00 ms"


def test_every_missing_key_is_listed_and_nothing_is_written(results: Results) -> None:
    text = (
        "{{fig:matmul.new_vs_old.ratio}} {{fig:made.up.one}} {{fig:old/made.up.two|.2f}} "
        "{{fig:made.up.one}} {{fig:made.up.three}}"
    )
    with pytest.raises(Refusal) as caught:
        fill_text(text, {"": results})
    assert caught.value.code == "E_FIGURE_MISSING"
    assert caught.value.exit_code == EXIT_FIGURE_MISSING == 7
    assert caught.value.detail == {"missing": ["made.up.one", "old/made.up.two", "made.up.three"]}
    assert caught.value.message == (
        "3 figures are missing from the results: made.up.one, old/made.up.two, made.up.three"
    )


def test_one_missing_key_is_named(results: Results) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:made.up}}", {"": results})
    assert caught.value.message == "1 figure is missing from the results: made.up"


def test_a_named_key_missing_from_its_results_is_listed_with_the_name(
    results: Results, other: Results
) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:old/matmul.new_vs_old.n}}", {"": results, "old": other})
    assert caught.value.detail == {"missing": ["old/matmul.new_vs_old.n"]}


def test_a_token_without_name_is_missing_when_no_results_serve_it(other: Results) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:matmul.new_vs_old.ratio}}", {"old": other})
    assert caught.value.code == "E_FIGURE_MISSING"
    assert caught.value.detail == {"missing": ["matmul.new_vs_old.ratio"]}


def test_a_format_on_a_figure_that_is_no_number_is_a_usage_error(results: Results) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:matmul.new_vs_old.verdict|>8}}", {"": results})
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE == 2
    assert caught.value.detail == {"formats": ["{{fig:matmul.new_vs_old.verdict|>8}}"]}


def test_a_format_python_cannot_apply_is_a_usage_error(results: Results) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:matmul.new_vs_old.ratio|d}}", {"": results})
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_width_too_large_to_write_is_a_usage_error(
    results: Results, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python's own format runs out of memory for such a width; the stand-in fails the
    # same way without asking the machine for the memory.
    def out_of_memory(value: object, spec: str) -> str:
        raise MemoryError

    monkeypatch.setattr(fill, "format", out_of_memory, raising=False)
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:matmul.new_vs_old.ratio|>999999999999}}", {"": results})
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.detail == {"formats": ["{{fig:matmul.new_vs_old.ratio|>999999999999}}"]}


def test_a_document_with_both_kinds_of_problem_is_refused_as_a_usage_error(
    results: Results,
) -> None:
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:made.up}} {{fig:matmul.new_vs_old.verdict|.2f}}", {"": results})
    assert caught.value.code == "E_USAGE"


def test_text_outside_tokens_is_never_changed(results: Results) -> None:
    template = (
        "# Title {{not a token}} {{fig:unclosed\r\n"
        "{ {fig:x}} {{FIG:x}} ±1.8% ünïcode\r\n"
        "value: {{fig:matmul.new_vs_old.verdict}}!\n"
    )
    expected = (
        "# Title {{not a token}} {{fig:unclosed\r\n"
        "{ {fig:x}} {{FIG:x}} ±1.8% ünïcode\r\n"
        "value: FASTER!\n"
    )
    assert fill_text(template, {"": results}) == expected


def test_the_public_fill_reads_a_path_and_takes_one_results_document(
    results: Results, tmp_path: Path
) -> None:
    template = tmp_path / "doc.md"
    template.write_text("n = {{fig:matmul.new_vs_old.n}}\n", encoding="utf-8")
    assert pairbench.fill(template, results) == "n = 16\n"
    assert pairbench.fill("{{fig:matmul.new_vs_old.n}}", results) == "16"
    assert pairbench.fill("{{fig:matmul.new_vs_old.n}}", {"": results}) == "16"


def test_the_fill_part_is_this_function() -> None:
    assert delegate("fill") is fill_text


def test_check_compares_the_file_byte_for_byte(results: Results, tmp_path: Path) -> None:
    filled = fill_text("ratio ± {{fig:matmul.new_vs_old.ratio}}\n", {"": results})
    out = tmp_path / "out.md"
    assert is_current(filled, out) is False
    out.write_bytes("ratio ± 0.80x\n".encode())
    assert is_current(filled, out) is True
    out.write_bytes("ratio ± 0.80x\r\n".encode())
    assert is_current(filled, out) is False
    out.write_bytes("ratio ± 0.79x\n".encode())
    assert is_current(filled, out) is False
