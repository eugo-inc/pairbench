# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the pages say ``report.include_image_refs`` shows, and that the results show it.

With the option on, an image reference is shown as typed: one that names a local archive
keeps the archive's folders. Every page that documents the option says so in one sentence,
and the page that lists what a results file never contains names the option as the
exception to absolute paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench.model import KIND_IMAGE, Side, public_command

ROOT = Path(__file__).resolve().parents[3]
AS_TYPED = (
    "With `report.include_image_refs` on, the results show image references as typed, "
    "local archive paths included"
)
PAGES = (
    "docs/reference/config.md",
    "docs/reference/results-schema.md",
    "docs/reference/text-format.md",
    "SECURITY.md",
)
ARCHIVE = "oci-archive:/made/up/new.tar"


def _text(relative: str) -> str:
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("relative", PAGES)
def test_each_page_that_documents_the_option_says_it_shows_references_as_typed(
    relative: str,
) -> None:
    assert AS_TYPED in _text(relative)


def test_the_list_of_what_a_results_file_never_holds_names_the_option_as_its_exception() -> None:
    text = _text("docs/reference/results-schema.md")
    never = text.split("### What a results file never contains", 1)[1].split("## ", 1)[0]
    assert "any absolute path outside the run folder" in never
    assert AS_TYPED in never


def test_the_results_show_a_local_archive_reference_as_typed_with_the_option_on() -> None:
    argv = ("pairbench", "run", "--side", f"new=image:{ARCHIVE}", "--", "true")
    assert public_command(argv, include_image_refs=True) == (
        f"pairbench run --side new=image:{ARCHIVE} -- true"
    )
    assert public_command(argv) == "pairbench run --side 'new=image:<hidden>' -- true"
    side = Side(name="new", kind=KIND_IMAGE, spec={"image": ARCHIVE})
    assert side.for_results(include_image_ref=True).image_ref == ARCHIVE
    assert side.for_results().image_ref is None
