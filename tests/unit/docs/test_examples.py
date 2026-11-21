# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The examples in the documents follow the tool's own rules.

Made-up numbers are still read as the tool would read them: an example row
of a report shows the verdict the default rule gives for its own gap, noise
bar and p-value; a p-value said to come from a count of paired rounds is one
the exact sign test can give for that count; and a verdict word is one the
tool prints, for the kind of case the example is about.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from pairbench.model import VERDICTS
from pairbench.report import p_text
from pairbench.stats import holm, sign_test

ALPHA = 0.05

# One row of a report as the terminal and Markdown reports print it.
ROW = re.compile(
    r"^\s*(?P<case>\S+)\s+(?P<subject>\d+(?:\.\d+)?)\s*[a-z]*\s+(?P<baseline>\d+(?:\.\d+)?)\s*"
    r"[a-z]*\s+(?P<times>\d+\.\d+)x (?P<direction>faster|slower)\s+±(?P<bar>\d+(?:\.\d+)?)%\s+"
    r"(?P<p>\d?\.\d+)\*?\s+(?P<verdict>FASTER|SLOWER|TIE|UNRESOLVED)\b"
)
ROUNDS = re.compile(r"over (\d+) paired rounds")
FAMILY = re.compile(r"testing (\d+) cases at once")
# A sentence that gives the agreeing rounds, the rounds and the corrected p-value.
SENTENCE = re.compile(
    r"in (\d+) of (\d+) paired rounds \(p = (\d?\.\d+),\s+corrected for testing (\d+) cases",
    re.MULTILINE,
)

# A verdict word that the tool does not print.
NOT_A_VERDICT = re.compile(r"\bSAME\b")
# Words for cases that are not times; a time case reads FASTER or SLOWER.
NOT_TIME_WORDS = re.compile(r"\b(BETTER|WORSE)\b")
# The drivers whose every case is of kind ``time``.
TIME_DRIVERS = frozenset({"wall", "pytest-benchmark", "hyperfine", "nvbench"})
SHOWCASES_PAGE = "docs/showcases.md"


def strict(ratio: float, bar: float, p: float) -> str:
    """The display verdict of the default rule for a case of kind ``time``."""
    outside = abs(ratio - 1) > bar
    significant = p < ALPHA
    if outside and significant:
        return "FASTER" if ratio < 1 else "SLOWER"
    if not outside and not significant:
        return "TIE"
    return "UNRESOLVED"


def rows(text: str) -> list[tuple[int, re.Match[str]]]:
    return [
        (number, found)
        for number, line in enumerate(text.splitlines(), start=1)
        if (found := ROW.match(line))
    ]


def attainable(rounds: int, family: int) -> set[str]:
    """Every corrected p-value, as a report shows it, for one count of rounds and cases."""
    shown: set[str] = set()
    for lower in range(rounds + 1):
        p = sign_test(lower, rounds - lower).p
        for rank in range(1, family + 1):
            shown.add(p_text(min(1.0, p * rank)))
    return shown


def test_an_example_row_shows_the_verdict_the_rule_gives(repo_root: Path, kit: Any) -> None:
    checked = 0
    wrong: list[str] = []
    for path in kit.documents(repo_root):
        for number, found in rows(path.read_text(encoding="utf-8")):
            ratio = float(found["subject"]) / float(found["baseline"])
            bar = float(found["bar"]) / 100
            expected = strict(ratio, bar, float(found["p"]))
            direction = "faster" if ratio < 1 else "slower"
            times = max(ratio, 1 / ratio)
            checked += 1
            if found["verdict"] != expected:
                wrong.append(f"{path.relative_to(repo_root)}:{number}: rule gives {expected}")
            if found["direction"] != direction or abs(times - float(found["times"])) > 0.0051:
                wrong.append(f"{path.relative_to(repo_root)}:{number}: change is {times:.3f}x")
    assert checked >= 5
    assert wrong == []


def test_an_example_p_value_is_one_the_sign_test_can_give(repo_root: Path, kit: Any) -> None:
    checked = 0
    wrong: list[str] = []
    for path in kit.documents(repo_root):
        text = path.read_text(encoding="utf-8")
        for block in text.split("```"):
            counted, family = ROUNDS.search(block), FAMILY.search(block)
            if not (counted and family):
                continue
            shown = attainable(int(counted[1]), int(family[1]))
            for _number, found in rows(block):
                checked += 1
                if found["p"] not in shown:
                    wrong.append(f"{path.relative_to(repo_root)}: {found['case']} p {found['p']}")
        for found in SENTENCE.finditer(text):
            agree, rounds, p, family = int(found[1]), int(found[2]), found[3], int(found[4])
            corrected = holm([sign_test(agree, rounds - agree).p, *[1.0] * (family - 1)])[0]
            checked += 1
            if p != p_text(corrected):
                wrong.append(f"{path.relative_to(repo_root)}: p {p}, exact {p_text(corrected)}")
    assert checked >= 3
    assert wrong == []


def test_no_document_names_a_verdict_the_tool_does_not_print(repo_root: Path, kit: Any) -> None:
    hits = [
        f"{path.relative_to(repo_root)}:{number}"
        for path in kit.documents(repo_root)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if NOT_A_VERDICT.search(line)
    ]

    assert "SAME" not in VERDICTS
    assert hits == []


def test_a_showcase_of_time_cases_reads_faster_or_slower(repo_root: Path, kit: Any) -> None:
    showcases = repo_root / "showcases"
    timed = []
    for config in sorted(showcases.glob("*/pairbench.toml")):
        driver = tomllib.loads(config.read_text(encoding="utf-8"))["workload"]["driver"]
        if driver in TIME_DRIVERS:
            timed.append(config.parent)
    hits = [
        f"{path.relative_to(repo_root)}:{number}"
        for path in kit.documents(repo_root)
        if any(folder in path.parents for folder in timed)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if NOT_TIME_WORDS.search(line)
    ]

    assert len(timed) >= 3
    assert hits == []


def test_the_overview_of_a_showcase_of_time_cases_reads_faster_or_slower(
    repo_root: Path,
) -> None:
    text = (repo_root / SHOWCASES_PAGE).read_text(encoding="utf-8")
    drivers = dict(re.findall(r"^\| (\d+) \|.*\| \[`([a-z-]+)`\]", text, re.MULTILINE))
    items = dict(re.findall(r"^(\d+)\. (.*?)(?=^\d+\. |^#|\Z)", text, re.MULTILINE | re.DOTALL))
    timed = [number for number, driver in drivers.items() if driver in TIME_DRIVERS]
    hits = [number for number in timed if NOT_TIME_WORDS.search(items.get(number, ""))]

    assert len(drivers) == len(items) == 7
    assert len(timed) >= 3
    assert hits == []


def test_the_rule_and_the_attainable_values_are_read_as_the_method_says() -> None:
    assert strict(0.80, 0.018, 0.001) == "FASTER"
    assert strict(1.0099, 0.009, 0.31) == "UNRESOLVED"
    assert strict(1.0099, 0.014, 0.31) == "TIE"
    assert strict(0.97, 0.039, 0.004) == "UNRESOLVED"
    assert "0.0010" in attainable(16, 2)
    assert "0.0004" not in attainable(16, 2)
