# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say what each showcase's ``expected/`` folder holds, and promise nothing more.

Both ways: a file in an ``expected/`` folder that the showcases page does not
name, or a sentence on a page about the showcases that speaks of a result in
``expected/`` (held now, or once something has happened) that no folder holds,
is a disagreement. A folder that holds only its ``README.md``, whose one line
says that no approved result exists yet, holds no result.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from .conftest import FRONT_MATTER, documents, prose

PAGE = "docs/showcases.md"
EXPECTED = "expected"
README = "README.md"
NO_RESULT = "No approved result exists yet"
# The pages about the showcases, read whether or not they name the folder.
PAGES = (
    PAGE,
    "docs/faq.md",
    "showcases/README.md",
    "docs/readme/README.in.md",
    "README.md",
    "llms.txt",
)
# Where any other page that names the folder is looked for.
PAGE_ROOTS = ("docs", "showcases", "skills")
LEFT_OUT = frozenset({"spec", EXPECTED, "pairbench-runs", "node_modules"})
FOLDER_NAMED = "expected/"
# The page's sentence that every expected/ folder holds only its one-line README.md.
HOLDS_ONLY = re.compile(
    r"`expected/`[^.]*\bholds only (?:a |its )?`README\.md`[^.]*\bno approved result exists yet",
)
# A sentence about the folder or an approval that speaks of a result, its numbers, its figures,
# its verdicts or its outcome.
ABOUT = re.compile(r"expected/|\bapproved\b", re.IGNORECASE)
RESULT = re.compile(r"\b(?:results?|numbers|figures|verdicts?|outcomes?)\b", re.IGNORECASE)
NEGATED = re.compile(r"\b(?:no|not|none|nothing|never|without)\b", re.IGNORECASE)
LATER = re.compile(
    r"\b(?:once|until|after|before|when|whenever|will|later|soon)\b",
    re.IGNORECASE,
)
BULLET = re.compile(r"^(?:[-*+]|\d+\.)\s+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[`\[(*_A-Z0-9])")

SAYS_NOTHING = (
    f"{PAGE} does not say what every expected/ folder holds: only a README.md whose one line "
    "says that no approved result exists yet"
)


def sentences(text: str) -> list[str]:
    """The sentences of a Markdown text outside code blocks and front matter, each on one line."""
    if text.startswith(FRONT_MATTER):
        end = text.find("\n" + FRONT_MATTER, len(FRONT_MATTER))
        if end >= 0:
            text = text[end + 1 + len(FRONT_MATTER) :]
    blocks: list[str] = []
    block: list[str] = []
    for _number, line in prose(text):
        stripped = line.strip()
        alone = stripped.startswith(("#", "|"))
        if not stripped or alone or BULLET.match(stripped):
            if block:
                blocks.append(" ".join(block))
            block = []
            if alone:
                blocks.append(stripped)
            elif stripped:
                block = [BULLET.sub("", stripped)]
            continue
        block.append(stripped)
    if block:
        blocks.append(" ".join(block))
    return [part for item in blocks for part in SENTENCE_END.split(item) if part]


def promises(sentence: str) -> bool:
    """Whether a sentence speaks of a result in the folder, now or once something happens."""
    if not (ABOUT.search(sentence) and RESULT.search(sentence)):
        return False
    return bool(LATER.search(sentence)) or not NEGATED.search(sentence)


def says_no_result(path: Path) -> bool:
    """Whether a folder's README.md is the one line that says no approved result exists."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return len(lines) == 1 and lines[0].startswith(NO_RESULT)


def showcase_folders(root: Path) -> list[Path]:
    """The showcase folders: each folder under showcases/ that holds a config."""
    base = root / "showcases"
    return sorted(path for path in base.iterdir() if (path / "pairbench.toml").is_file())


def held_results(root: Path) -> list[str]:
    """Every file in an expected/ folder that is not its one-line README.md, dot-files included."""
    held: list[str] = []
    for showcase in showcase_folders(root):
        folder = showcase / EXPECTED
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            if path == folder / README and says_no_result(path):
                continue
            held.append(path.relative_to(root).as_posix())
    return held


def pages_about_expected(root: Path) -> list[str]:
    """The pages about the showcases, and every other page that names the expected/ folder."""
    found = [name for name in PAGES if (root / name).is_file()]
    candidates = sorted(root.glob("*.md"))
    for name in PAGE_ROOTS:
        candidates += sorted((root / name).rglob("*.md"))
    for path in candidates:
        relative = path.relative_to(root)
        if LEFT_OUT.intersection(relative.parts[:-1]) or relative.as_posix() in found:
            continue
        text = path.read_text(encoding="utf-8")
        if any(FOLDER_NAMED in line for _number, line in prose(text)):
            found.append(relative.as_posix())
    return found


def disagreements(root: Path) -> list[str]:
    """Where the pages and the expected/ folders under ``root`` disagree, one line each."""
    problems: list[str] = []
    held = held_results(root)
    page = sentences((root / PAGE).read_text(encoding="utf-8"))
    says_only = any(HOLDS_ONLY.search(sentence) for sentence in page)
    named = " ".join(page)
    for showcase in showcase_folders(root):
        readme = showcase / EXPECTED / README
        if says_only and not readme.is_file():
            problems.append(
                f"{PAGE} says every expected/ folder holds its README.md, but "
                f"{readme.relative_to(root).as_posix()} is not there"
            )
    if not held and not says_only:
        problems.append(SAYS_NOTHING)
    for path in held:
        if says_only:
            problems.append(
                f"{PAGE} says every expected/ folder holds only README.md, but {path} is there"
            )
        if path.removeprefix("showcases/") not in named:
            problems.append(f"{path} is a result that {PAGE} does not name")
    for name in pages_about_expected(root):
        for sentence in sentences((root / name).read_text(encoding="utf-8")):
            if not promises(sentence):
                continue
            if not held:
                problems.append(
                    f'{name}: "{sentence}" promises a result that no expected/ folder holds'
                )
            elif not any(path.removeprefix("showcases/") in sentence for path in held):
                problems.append(f'{name}: "{sentence}" speaks of a result it does not name')
    return problems


def copy_of(repo_root: Path, into: Path) -> Path:
    """A copy of the pages about the showcases and of each showcase's README, config and folder."""
    root = into / "copy"
    for name in pages_about_expected(repo_root):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_root / name, root / name)
    for showcase in showcase_folders(repo_root):
        target = root / showcase.relative_to(repo_root)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(showcase / "pairbench.toml", target / "pairbench.toml")
        shutil.copyfile(showcase / README, target / README)
        shutil.copytree(showcase / EXPECTED, target / EXPECTED)
    return root


def plant(root: Path, name: str, sentence: str) -> None:
    """Add a sentence to a page as a paragraph of its own."""
    path = root / name
    path.write_text(path.read_text(encoding="utf-8") + f"\n{sentence}\n", encoding="utf-8")


def drop(root: Path, name: str, sentence: str) -> None:
    """Remove one sentence from a page, however its lines are wrapped."""
    path = root / name
    text = path.read_text(encoding="utf-8")
    words = r"\s+".join(re.escape(word) for word in sentence.split())
    changed, count = re.subn(words, "", text, count=1)
    assert count == 1, sentence
    path.write_text(changed, encoding="utf-8")


def holds_only_sentence(root: Path) -> str:
    """The page's sentence that every expected/ folder holds only its README.md."""
    page = sentences((root / PAGE).read_text(encoding="utf-8"))
    return next(sentence for sentence in page if HOLDS_ONLY.search(sentence))


def test_the_pages_agree_with_what_the_expected_folders_hold(repo_root: Path) -> None:
    assert disagreements(repo_root) == []


def test_every_public_page_that_names_the_folder_is_read(repo_root: Path) -> None:
    read = set(pages_about_expected(repo_root))
    naming = [
        path.relative_to(repo_root).as_posix()
        for path in documents(repo_root)
        if path.suffix in {".md", ".txt"}
        and EXPECTED not in path.relative_to(repo_root).parts[:-1]
        and any(FOLDER_NAMED in line for _number, line in prose(path.read_text(encoding="utf-8")))
    ]

    assert [name for name in naming if name not in read] == []
    assert PAGE in read


# A result file planted in one expected/ folder, by showcase and by its path in the folder.
PLANTED_RESULTS = (
    ("numpy-pip-vs-conda", "results.json"),
    ("gpu-kernel", "report.html"),
    ("python-versions", ".results.json"),
    ("noisy-neighbour", "run/results.md"),
)


@pytest.mark.parametrize(("showcase", "planted"), PLANTED_RESULTS)
def test_a_result_the_page_does_not_name_turns_the_row_red(
    repo_root: Path, tmp_path: Path, showcase: str, planted: str
) -> None:
    root = copy_of(repo_root, tmp_path)
    path = root / "showcases" / showcase / EXPECTED / planted
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"made-up": true}\n', encoding="utf-8")
    held = f"showcases/{showcase}/{EXPECTED}/{planted}"

    assert disagreements(root) == [
        f"{PAGE} says every expected/ folder holds only README.md, but {held} is there",
        f"{held} is a result that {PAGE} does not name",
    ]


def test_a_readme_that_holds_a_result_turns_the_row_red(repo_root: Path, tmp_path: Path) -> None:
    root = copy_of(repo_root, tmp_path)
    readme = root / "showcases" / "python-versions" / EXPECTED / README
    readme.write_text("| case | verdict |\n|---|---|\n| made-up | TIE |\n", encoding="utf-8")
    held = f"showcases/python-versions/{EXPECTED}/{README}"

    assert disagreements(root) == [
        f"{PAGE} says every expected/ folder holds only README.md, but {held} is there",
        f"{held} is a result that {PAGE} does not name",
    ]


def test_a_missing_readme_turns_the_row_red(repo_root: Path, tmp_path: Path) -> None:
    root = copy_of(repo_root, tmp_path)
    (root / "showcases" / "gpu-kernel" / EXPECTED / README).unlink()

    assert disagreements(root) == [
        f"{PAGE} says every expected/ folder holds its README.md, but "
        f"showcases/gpu-kernel/{EXPECTED}/{README} is not there",
    ]


def test_a_page_that_names_the_result_it_holds_agrees(repo_root: Path, tmp_path: Path) -> None:
    root = copy_of(repo_root, tmp_path)
    folder = root / "showcases" / "numpy-pip-vs-conda" / EXPECTED
    (folder / "results.json").write_text('{"made-up": true}\n', encoding="utf-8")
    drop(root, PAGE, holds_only_sentence(root))
    plant(root, PAGE, "`numpy-pip-vs-conda/expected/results.json` holds a made-up result.")

    assert disagreements(root) == []


def test_a_page_that_does_not_say_what_the_folders_hold_turns_the_row_red(
    repo_root: Path, tmp_path: Path
) -> None:
    root = copy_of(repo_root, tmp_path)
    drop(root, PAGE, holds_only_sentence(root))

    assert disagreements(root) == [SAYS_NOTHING]


# Sentences that promise a result no folder holds, each with the page it is planted on.
PROMISES = (
    (
        PAGE,
        "`expected/`, which holds the result of a real run and the class of machine that "
        "produced it, once that result has been approved.",
    ),
    (PAGE, "Until then it holds one line saying that no approved result exists yet."),
    (
        PAGE,
        "Its `expected/` folder stays without a result until the maintainers have read the "
        "licence of the vendor container.",
    ),
    (
        PAGE,
        "Results are published in `expected/` only after a real run has been approved, with the "
        "class of machine that produced it.",
    ),
    (PAGE, "Each `expected/` folder holds the approved result of a real run."),
    (
        "showcases/python-versions/README.md",
        "A result is published only after a real run has been approved, with the class of "
        "machine that produced it.",
    ),
    (
        "showcases/vendor-container-vs-pip/README.md",
        "[`expected/`](expected/) holds no result, and none is published until the licence of "
        "the vendor container has been read by the maintainers and a real run has been approved.",
    ),
    ("docs/faq.md", "The showcases publish results only after a real run has been approved."),
    (PAGE, "Each showcase will ship its numbers in `expected/` once a run is approved."),
    ("showcases/README.md", "The approved figures and verdicts go into each `expected/` folder."),
    (
        "docs/readme/README.in.md",
        "Approved results will be published in each showcase's `expected/` folder.",
    ),
)


@pytest.mark.parametrize(("name", "sentence"), PROMISES)
def test_a_promise_no_folder_keeps_turns_the_row_red(
    repo_root: Path, tmp_path: Path, name: str, sentence: str
) -> None:
    root = copy_of(repo_root, tmp_path)
    plant(root, name, sentence)

    assert disagreements(root) == [
        f'{name}: "{sentence}" promises a result that no expected/ folder holds'
    ]


def test_a_promise_beside_a_result_it_does_not_name_turns_the_row_red(
    repo_root: Path, tmp_path: Path
) -> None:
    root = copy_of(repo_root, tmp_path)
    folder = root / "showcases" / "numpy-pip-vs-conda" / EXPECTED
    (folder / "results.json").write_text('{"made-up": true}\n', encoding="utf-8")
    drop(root, PAGE, holds_only_sentence(root))
    plant(root, PAGE, "`numpy-pip-vs-conda/expected/results.json` holds a made-up result.")
    sentence = "Each `expected/` folder holds the approved result of a real run."
    plant(root, PAGE, sentence)

    assert disagreements(root) == [f'{PAGE}: "{sentence}" speaks of a result it does not name']


# Sentences that promise nothing about the folder and keep passing on the page.
NOT_A_PROMISE = (
    "Read the licence of each image and model before you publish a result made with it.",
    "No approved result is published for any of them yet.",
    "[`expected/`](expected/) holds no result yet.",
    "A run writes `results.json` into a new folder under `pairbench-runs/`, never into "
    "`expected/`.",
    "The approved list of drivers is on the guide's page.",
    "[`expected/`](expected/) holds no numbers, figures or verdicts yet.",
)


@pytest.mark.parametrize("sentence", NOT_A_PROMISE)
def test_a_sentence_that_promises_nothing_keeps_passing(
    repo_root: Path, tmp_path: Path, sentence: str
) -> None:
    root = copy_of(repo_root, tmp_path)
    plant(root, PAGE, sentence)

    assert disagreements(root) == []
