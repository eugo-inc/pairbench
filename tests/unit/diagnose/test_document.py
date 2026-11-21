# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Writing and reading diagnostics.json, validated against the shipped schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pairbench.diagnose import document
from pairbench.errors import Refusal
from pairbench.model import Diagnostics
from pairbench.results import load_schema


def test_a_written_document_validates_and_reads_back_equal(
    tmp_path: Path, example_diagnostics: dict[str, Any]
) -> None:
    made = Diagnostics.from_json(example_diagnostics)
    path = document.write_diagnostics(made, tmp_path)
    assert path == tmp_path / "diagnostics.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    jsonschema.validate(data, load_schema("diagnostics"))
    assert document.read_diagnostics(path) == made
    assert sorted(p.name for p in tmp_path.iterdir()) == ["diagnostics.json"]


def test_the_document_says_near_its_top_that_it_holds_names(
    tmp_path: Path, example_diagnostics: dict[str, Any]
) -> None:
    path = document.write_diagnostics(Diagnostics.from_json(example_diagnostics), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert list(json.loads(text))[:3] == ["schema", "run", "holds_names"]
    assert text.splitlines()[:5] == [
        "{",
        '  "schema": "pairbench/diagnostics/v1",',
        '  "run": {',
        '    "id": "cap-000001"',
        "  },",
    ]
    assert text.splitlines()[5] == '  "holds_names": true,'
    assert text.endswith("}\n")


def test_two_writes_of_one_document_are_equal(
    tmp_path: Path, example_diagnostics: dict[str, Any]
) -> None:
    made = Diagnostics.from_json(example_diagnostics)
    first = document.write_diagnostics(made, tmp_path / "a").read_bytes()
    assert first == document.write_diagnostics(made, tmp_path / "b").read_bytes()


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("not json", "is not a diagnostics document"),
        ("[1, 2]", "is not a diagnostics document"),
    ],
)
def test_a_file_that_is_no_document_is_refused(tmp_path: Path, text: str, words: str) -> None:
    path = tmp_path / "diagnostics.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        document.read_diagnostics(path)
    assert caught.value.code == "E_USAGE"
    assert words in caught.value.message


@pytest.mark.parametrize(
    ("data", "words"),
    [
        (b"\xff\xfe{}", "is not a diagnostics document: it is not UTF-8"),
        (b"[" * 200000 + b"]" * 200000, "is not a diagnostics document: it nests too deeply"),
    ],
)
def test_a_file_that_is_no_text_or_nests_too_deeply_is_refused(
    tmp_path: Path, data: bytes, words: str
) -> None:
    path = tmp_path / "diagnostics.json"
    path.write_bytes(data)
    with pytest.raises(Refusal) as caught:
        document.read_diagnostics(path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == f"diagnostics.json {words}"


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        document.read_diagnostics(tmp_path / "absent.json")
    assert caught.value.code == "E_USAGE"
    assert "cannot read the diagnostics document absent.json" in caught.value.message


def test_a_document_of_another_schema_is_refused(
    tmp_path: Path, example_diagnostics: dict[str, Any]
) -> None:
    path = tmp_path / "diagnostics.json"
    path.write_text(
        json.dumps({**example_diagnostics, "schema": "pairbench/other/v1"}), encoding="utf-8"
    )
    with pytest.raises(Refusal) as caught:
        document.read_diagnostics(path)
    assert caught.value.code == "E_USAGE"
