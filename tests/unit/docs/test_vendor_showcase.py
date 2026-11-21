# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The vendor container showcase is a recipe: commands, config and the shape of the output.

Its README shows the report a run prints with every value left as a
``<placeholder>``. A run of the tool itself, with command sides that carry the
showcase's side names and print the showcase's case ids, checks that the
shape is the one the tool prints, so the README cannot drift from the report.
The folder holds the recipe and nothing from a run.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

SHOWCASE = Path("showcases/vendor-container-vs-pip")
SHAPE_HEADING = "## Expected shape of the output"
RUN_HEADING = "## Run it"
# The files of the recipe; anything else would be something a run produced.
RECIPE = (
    "README.md",
    "bench.py",
    "expected/README.md",
    "pairbench.toml",
    "run.sh",
    "sides.lock",
)
# Folders a run of the showcase writes beside the recipe, which git ignores.
LOCAL_ONLY = frozenset({".deps", "pairbench-runs", "__pycache__"})
COMMANDS = (
    "pairbench plan --config pairbench.toml",
    "./run.sh",
    "pairbench report pairbench-runs/<run>/results.json",
)
PLACEHOLDER = re.compile(r"<[^<>]+>")
FENCE = re.compile(r"^```")
FILE_ITEM = re.compile(r"^- `([^`]+)`: ")
# A number as a run prints one: a decimal, a ratio or a noise bar.
RUN_NUMBER = re.compile(r"\d+\.\d+|\d+(?:\.\d+)?x\b|±\s?\d|\d+(?:\.\d+)?\s?%")
CHARTS = "charts/"
NOT_WRITTEN = ("diagnostics.json", "profiles/")
# What the explain step does not do: it puts its instrument in front of an
# image's whole command line, entrypoint included.
ENTRYPOINT_CLAIM = re.compile(r"cannot\s+(?:#\s*)?put\s+(?:#\s*)?an\s+(?:#\s*)?instrument", re.I)
EXPLAIN_PAGES = ("../../docs/method/diagnostics.md", "../../docs/guides/perf-in-an-image.md")


def readme(repo_root: Path) -> str:
    return (repo_root / SHOWCASE / "README.md").read_text(encoding="utf-8")


def section(text: str, heading: str) -> list[str]:
    """The lines under a level-two heading, up to the next one."""
    lines = text.splitlines()
    assert heading in lines, f"README has no heading {heading!r}"
    start = lines.index(heading) + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def first_block(lines: list[str]) -> list[str]:
    """The lines of the first fenced code block among ``lines``."""
    fences = [i for i, line in enumerate(lines) if FENCE.match(line)]
    assert len(fences) >= 2, "the section has no fenced code block"
    return lines[fences[0] + 1 : fences[1]]


def shape(repo_root: Path) -> list[str]:
    return first_block(section(readme(repo_root), SHAPE_HEADING))


def case_ids(repo_root: Path) -> list[str]:
    """The case ids ``bench.py`` prints, in the order it prints them."""
    tree = ast.parse((repo_root / SHOWCASE / "bench.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "report"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    calls.sort(key=lambda node: (node.lineno, node.col_offset))
    return [str(node.args[0].value) for node in calls if isinstance(node.args[0], ast.Constant)]


def config(repo_root: Path) -> dict[str, Any]:
    with (repo_root / SHOWCASE / "pairbench.toml").open("rb") as handle:
        return tomllib.load(handle)


def side_names(repo_root: Path) -> tuple[str, str]:
    """The subject and the baseline of the showcase's config."""
    sides = config(repo_root)["sides"]
    baseline = [name for name, side in sides.items() if side.get("baseline") is True]
    assert len(baseline) == 1
    subject = [name for name in sides if name != baseline[0]]
    assert len(subject) == 1
    return subject[0], baseline[0]


def pattern(line: str) -> re.Pattern[str]:
    """A shape line as a pattern: a placeholder stands for any text, spaces for any spaces."""
    parts: list[str] = []
    at = 0
    for match in PLACEHOLDER.finditer(line):
        parts.append(_literal(line[at : match.start()]))
        parts.append(r"\S.*?")
        at = match.end()
    parts.append(_literal(line[at:]))
    return re.compile("^" + "".join(parts) + "$")


def _literal(text: str) -> str:
    return r"\s+".join(re.escape(word) for word in re.split(r"\s+", text)) if text else ""


def in_order(patterns: list[re.Pattern[str]], lines: list[str]) -> list[str]:
    """The patterns that no line matches, each looked for after the line the last one matched."""
    missing: list[str] = []
    at = 0
    for wanted in patterns:
        found = next((i for i in range(at, len(lines)) if wanted.match(lines[i].rstrip())), None)
        if found is None:
            missing.append(wanted.pattern)
        else:
            at = found + 1
    return missing


def test_bench_py_prints_six_cases(repo_root: Path) -> None:
    assert case_ids(repo_root) == [
        "matmul_fp32_4096",
        "matmul_bf16_4096",
        "conv2d_3x3_64ch",
        "softmax_8192",
        "layernorm_1024",
        "gelu",
    ]


def test_the_readme_gives_the_commands(repo_root: Path) -> None:
    block = first_block(section(readme(repo_root), RUN_HEADING))
    assert [line.strip() for line in block] == list(COMMANDS)
    script = (repo_root / SHOWCASE / "run.sh").read_text(encoding="utf-8")
    assert 'run_pairbench "" --config pairbench.toml' in script
    helper = (repo_root / SHOWCASE.parent / "publish.sh").read_text(encoding="utf-8")
    assert '  pairbench run "$@"\n' in helper


def test_the_shape_has_one_row_per_case_in_the_order_bench_py_prints_them(
    repo_root: Path,
) -> None:
    subject, baseline = side_names(repo_root)
    lines = shape(repo_root)
    assert lines[0] == f"{subject} against {baseline} (baseline)"
    header = lines[2].split()
    assert header == ["case", subject, baseline, "change", "noise", "p", "verdict"]
    rows = [line.split()[0] for line in lines[3 : 3 + len(case_ids(repo_root))]]
    assert rows == case_ids(repo_root)


def test_the_shape_shows_no_number_from_a_run(repo_root: Path) -> None:
    ids = case_ids(repo_root)
    found = []
    for line in shape(repo_root):
        words = [word for word in line.split() if word not in ids]
        if RUN_NUMBER.search(" ".join(words)):
            found.append(line)
    assert found == []
    assert RUN_NUMBER.search(" ".join(section(readme(repo_root), SHAPE_HEADING))) is None


def test_the_folder_holds_the_recipe_and_nothing_from_a_run(repo_root: Path) -> None:
    base = repo_root / SHOWCASE
    held = sorted(
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and not LOCAL_ONLY.intersection(path.relative_to(base).parts)
    )
    assert held == sorted(RECIPE)


def test_the_config_turns_the_explain_step_off_and_uses_the_work_factor(
    repo_root: Path,
) -> None:
    loaded = config(repo_root)
    assert loaded["explain"]["mode"] == "off"
    assert loaded["controls"]["positive_via"] == "factor"


def test_the_recipe_does_not_say_the_explain_step_cannot_instrument_an_entrypoint(
    repo_root: Path,
) -> None:
    """The explain step puts its instrument in front of an image's whole command line.

    The recipe keeps it off, and says so without giving a reason the tool
    contradicts; it points at the pages that say what the step adds and needs.
    """
    texts = {
        name: (repo_root / SHOWCASE / name).read_text(encoding="utf-8")
        for name in ("README.md", "pairbench.toml")
    }
    assert [name for name, text in texts.items() if ENTRYPOINT_CLAIM.search(text)] == []
    for page in EXPLAIN_PAGES:
        assert f"]({page})" in texts["README.md"]
        assert (repo_root / SHOWCASE / page).resolve().is_file()


STAND_IN = """\
import json, os
factor = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
spread = 1 + (os.getpid() % 89) / 10000
for case in {cases!r}:
    line = {{"case": case, "value": factor * spread, "unit": "s", "better": "lower"}}
    print("::pairbench::", json.dumps(line))
"""


def stand_in_config(repo_root: Path, workload: Path) -> str:
    """The showcase's config with command sides in place of its images.

    The side names, the baseline, the driver, the positive control and the
    explain step are the showcase's own.
    """
    subject, baseline = side_names(repo_root)
    loaded = config(repo_root)
    python = json.dumps(sys.executable)
    return (
        "[workload]\n"
        f"argv = [{json.dumps(str(workload))}]\n"
        f"driver = {json.dumps(loaded['workload']['driver'])}\n"
        f"[sides.{baseline}]\n"
        f'cmd = [{python}, "{{workload}}"]\n'
        "baseline = true\n"
        f"[sides.{subject}]\n"
        f'cmd = [{python}, "-B", "{{workload}}"]\n'
        "[controls]\n"
        f"positive_via = {json.dumps(loaded['controls']['positive_via'])}\n"
        "[explain]\n"
        f"mode = {json.dumps(loaded['explain']['mode'])}\n"
    )


def test_a_run_prints_the_shape_and_writes_the_listed_files(
    repo_root: Path, cli: Callable[..., Any], tmp_path: Path
) -> None:
    """A run with the showcase's names, cases and settings, on command sides.

    The values are not timings and are never shown; only the shape of the
    report and the files of the run folder are compared.
    """
    workload = tmp_path / "workload.py"
    workload.write_text(STAND_IN.format(cases=case_ids(repo_root)), encoding="utf-8")
    path = tmp_path / "pairbench.toml"
    path.write_text(stand_in_config(repo_root, workload), encoding="utf-8")
    out = tmp_path / "run"

    result = cli("run", "--config", path, "--gates", "off", "--plots", "off", "--out", out)

    assert result.code == 0, result.err
    patterns = [pattern(line) for line in shape(repo_root) if line.strip()]
    assert in_order(patterns, result.out.splitlines()) == []
    listed = [
        match.group(1)
        for line in section(readme(repo_root), SHAPE_HEADING)
        if (match := FILE_ITEM.match(line))
    ]
    written = sorted(item.name + ("/" if item.is_dir() else "") for item in out.iterdir())
    assert CHARTS in listed
    assert sorted(name for name in listed if name != CHARTS) == written
    assert [name for name in NOT_WRITTEN if name in listed or name in written] == []


def test_a_shape_line_matches_only_its_own_kind_of_line() -> None:
    row = pattern("gelu  <time>  <time>  <change>  <noise>  <p>*  <verdict>")
    assert row.match("gelu  1.00 s  1.00 s  1.00x slower  ±0.5%  1.0*  TIE")
    assert not row.match("conv2d_3x3_64ch  1.00 s  1.00 s  1.00x slower  ±0.5%  1.0*  TIE")
    footer = pattern("Baseline: pip.")
    assert footer.match("Baseline: pip.")
    assert not footer.match("Baseline: vendor.")
    assert in_order([footer, row], ["gelu  a  b  c  d  e*  f", "Baseline: pip."]) == [row.pattern]


def test_the_patterns_find_a_number_from_a_run() -> None:
    for text in ("1.04x faster", "±2.5%", "0.0031", "3 %"):
        assert RUN_NUMBER.search(text), text
    for text in ("<ratio>x faster", "± and a percentage", "matmul", "testing six cases"):
        assert not RUN_NUMBER.search(text), text


# What the showcase may say about the vendor image's TF32 variable is what the image sets
# and what the config and bench.py do; what the variable does inside PyTorch is not stated
# by any page the showcase cites.
TF32_FILES = ("README.md", "pairbench.toml", "bench.py")
TF32_EFFECT_CLAIMS = ("reduced precision", "whatever the workload", "full float32 precision")
TF32_VARIABLE = "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE"


def test_the_showcase_states_what_the_image_sets_and_not_what_the_variable_does(
    repo_root: Path,
) -> None:
    for name in TF32_FILES:
        text = " ".join((repo_root / SHOWCASE / name).read_text(encoding="utf-8").split())
        text = text.replace(" # ", " ")
        assert [claim for claim in TF32_EFFECT_CLAIMS if claim in text] == [], name
    readme_text = " ".join(readme(repo_root).split())
    assert f"The vendor image sets `{TF32_VARIABLE}=1`" in readme_text
