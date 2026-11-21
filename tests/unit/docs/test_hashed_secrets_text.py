# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the pages say about the hashes the shared files show and the secrets in them.

The security policy and the results reference each say three things: the hashes are computed
with the recognised secret forms hidden, a value in a form the tool does not recognise is still
in the hash and can be confirmed by guessing, and secrets belong in the environment through
``launch.env_pass``. The page that lists the recognised forms says the first two. The hashed
forms they promise are checked against the code: a secret in a recognised form leaves the hash
as it is, a value in another form changes it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pairbench.model import PRIVATE_FILE_MODE
from pairbench.results.writer import NEW_FILE_MODE
from pairbench.sides.identity import argv_sha256

ROOT = Path(__file__).resolve().parents[3]
# Each ends a code span: `fingerprint` and `sides[].fingerprint` both name the field.
HASHES = ("argv_sha256`", "args_sha256`", "fingerprint`", "config_sha256`")
HIDDEN_IN_HASH = "computed with the recognised secret forms hidden"
GUESS_CHECKED = "a guess at it cannot be checked against a hash"
UNRECOGNISED = "A value in a form the tool does not recognise is still in the hash"
CONFIRMED = "can confirm a guess at it by hashing the guess"
ENV_PASS = "env_pass`"
CONFIG_HIDDEN = (
    "The hashes the shared files show of each side and of the config are computed with these "
    "forms hidden too, so a guess at a hidden value cannot be checked against them."
)
CONFIG_UNRECOGNISED = (
    "A value in any other form is in the hashes as typed, and someone who knows the rest of the "
    "command can confirm a guess at it by hashing the guess."
)
CONFIG_NARROWER = "One of them is narrower there: an address keeps its host in the hashes."
# The pages give the hashes no narrower rule for an absolute path: it is hidden as it is shown.
PATH_NARROWER = "an absolute path that holds no `+/` keeps its other parts"
SAME_SIDE_KEPT = (
    "A path or a host is hashed as typed, except the parts the shared files hide for their "
    "shape: a random-looking value in a path, such as a run of 32 or 64 hexadecimal digits, "
    "which takes the rest of the path with it when the path starts with `/`, `./`, `../` or `~/`; "
    "the port and path of an address that holds a `+/` run; and a value glued to an option of one "
    "letter that holds a `/` and a random-looking part."
)
SAME_SIDE_OVERSTATED = (
    "A path or a host is hashed as typed, so two sides that differ in one have different "
    "fingerprints."
)
SAME_SIDE_HIDDEN_CAUSE = (
    "Two sides whose specs differ only in such a hidden part are not refused: `plan` and `run` "
    "compare them and give the note `sides_differ_in_hidden_value`, which names both sides and "
    "never the value."
)
SAME_SIDE_TAIL_CAUSE = (
    "The same holds for what a hidden credential value holds besides the credential itself, as "
    "[hidden values that tell two sides apart](config.md#hidden-values-that-tell-two-sides-apart) "
    "lists: the words after it, such as `HF_TOKEN=t ./bench-old` against "
    "`HF_TOKEN=t ./bench-new` in one argument, the other words of a client's command, and the "
    "user, host, path and other query parameters of an address. The credential itself, an "
    "Authorization scheme word and its token, such as `Bearer t`, or else the value up to its "
    "first space, is no difference: two sides that differ only in it, as in a rotated token, are "
    "refused; a password that holds a space and differs after it, such as `DB_PASSWORD=a b c` "
    "against `DB_PASSWORD=a b d`, makes two sides."
)
POOL_TAIL_CAUSE = (
    "or in what a hidden credential value holds besides the credential itself, such as "
    "`HF_TOKEN=t ./bench-old` against `HF_TOKEN=t ./bench-new` or the database number of "
    "`redis://:t@localhost/0`, is refused too"
)
POOL_IDENTIFY_CAUSE = (
    "A side whose `identify` command printed, in one capture and the other, a different "
    "checksum, build id or version, such as the checksum `md5sum` prints of a weights file that "
    "has changed, has a different fingerprint: that output is hashed with only its credentials "
    "hidden."
)
CONFIG_IDENTIFY_POOL = (
    "a change in them changes `identify_sha256` and the side's fingerprint, and captures made "
    "before and after it do not pool (`E_POOL_SIDE_DRIFT`)."
)
RESULTS_IDENTIFY_POOL = (
    "A checksum, a build id or a version an `identify` command prints is in `identify_sha256` "
    "and the fingerprint, so captures that differ in one are not pooled either."
)
SECURITY_IDENTIFY = (
    "The output of a side's `identify` command is read line by line for its credentials only: a "
    "checksum, a build id or another long value it prints is in the hash as printed"
)
POOL_SPACED_PASSWORD = (
    "a password that holds a space and differs after it, such as `DB_PASSWORD=a b c` against "
    "`DB_PASSWORD=a b d`, is drift."
)
OWNER_ONLY_FILES = "readable and writable by their owner only (mode `0600`)"
RESULTS_FILE_MODES = (
    "a new results file (`results.json`, `results.md`, `report.html`) is made readable by all "
    "(mode `0644`) whatever the umask, and one already there keeps its mode, since they are "
    "meant to be shared."
)
RESULTS_DEFAULT_MODE = "keep the default mode"
SECURITY = "SECURITY.md"
RESULTS = "docs/reference/results-schema.md"
CONFIG = "docs/reference/config.md"
EXIT_CODES = "docs/reference/exit-codes.md"
RANDOM_A = "X1y2Z3x4Y5z6X7y8Z9x0Y1z2X3y4Z5x6"
RANDOM_B = "Q9xW7mP2vL8nR4tY6bC1dF5gH0jKzA3s"


def _text(relative: str) -> str:
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def _paragraph(relative: str, words: str) -> str:
    """Return the one paragraph or list item that holds ``words``, on one line."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    joined = [" ".join(part.split()) for part in re.split(r"\n\s*\n|\n- ", text)]
    found = [part for part in joined if words in part]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("relative", [SECURITY, RESULTS])
def test_the_page_says_how_the_hashes_treat_a_secret(relative: str) -> None:
    passage = _paragraph(relative, HIDDEN_IN_HASH)
    assert [name for name in HASHES if name not in passage] == []
    assert GUESS_CHECKED in passage
    assert UNRECOGNISED in passage
    assert CONFIRMED in passage
    assert ENV_PASS in passage
    assert passage.index(HIDDEN_IN_HASH) < passage.index(UNRECOGNISED) < passage.index(ENV_PASS)


def test_the_page_of_recognised_forms_says_the_hashes_hide_them_and_only_them() -> None:
    text = _text(CONFIG)
    assert CONFIG_HIDDEN in text
    assert CONFIG_UNRECOGNISED in text


def test_the_pages_say_the_hashes_keep_hosts_and_paths() -> None:
    assert CONFIG_NARROWER in _text(CONFIG)
    assert PATH_NARROWER not in _text(CONFIG)
    assert SAME_SIDE_KEPT in _text(EXIT_CODES)


def test_the_same_side_entry_names_a_hidden_value_as_a_cause() -> None:
    passage = _paragraph(EXIT_CODES, "Two sides with different names have the same fingerprint")
    assert SAME_SIDE_OVERSTATED not in _text(EXIT_CODES)
    assert SAME_SIDE_HIDDEN_CAUSE in _text(EXIT_CODES)
    assert passage.index("**Cause.**") < passage.index(SAME_SIDE_KEPT)
    assert passage.index(SAME_SIDE_HIDDEN_CAUSE) < passage.index(SAME_SIDE_TAIL_CAUSE)


def test_the_pool_drift_entry_names_the_words_after_a_hidden_value_s_first_space() -> None:
    passage = _paragraph(
        EXIT_CODES, "A side's fingerprint differs between the captures being pooled"
    )
    assert POOL_TAIL_CAUSE in passage
    assert POOL_SPACED_PASSWORD in passage


def test_the_pages_say_a_checksum_in_the_identify_output_still_stops_a_pool() -> None:
    passage = _paragraph(
        EXIT_CODES, "A side's fingerprint differs between the captures being pooled"
    )
    assert POOL_IDENTIFY_CAUSE in passage
    assert CONFIG_IDENTIFY_POOL in _text(CONFIG)
    assert RESULTS_IDENTIFY_POOL in _text(RESULTS)
    assert SECURITY_IDENTIFY in _text(SECURITY)


HEX_A = "3f9a1c7e5b2d4086a1c3e5f7092b4d6e"
HEX_B = "8e2b6d4f0a1c3e5b7d9f1a3c5e7b9d0f"


@pytest.mark.parametrize(
    ("one", "two"),
    [
        (f"/data/{HEX_A}/w.bin", f"/data/{HEX_B}/w.bin"),
        (
            f"https://h.made-up.example:8000/a+/{RANDOM_A}",
            f"https://h.made-up.example:9000/b+/{RANDOM_A}",
        ),
        (f"-xone/{RANDOM_A}", f"-xtwo/{RANDOM_A}"),
    ],
    ids=["hex-run-in-a-path", "address-with-a-plus-slash-run", "glued-to-a-one-letter-option"],
)
def test_the_parts_the_same_side_entry_names_are_hidden_in_the_hash(one: str, two: str) -> None:
    assert argv_sha256(["made-up-tool", one]) == argv_sha256(["made-up-tool", two])


def test_the_hashes_keep_hosts_and_paths_as_the_pages_say() -> None:
    host_a = argv_sha256(["made-up-tool", "--url", "https://a.made-up.example/v1"])
    host_b = argv_sha256(["made-up-tool", "--url", "https://b.made-up.example/v1"])
    path_a = argv_sha256(["made-up-tool", "/made/up/a/w.bin"])
    path_b = argv_sha256(["made-up-tool", "/made/up/b/w.bin"])
    # A path that holds a random-looking value is hidden whole, as the shared files show it.
    random_a = argv_sha256(["made-up-tool", f"/made/up/a/{RANDOM_A}/w.bin"])
    random_b = argv_sha256(["made-up-tool", f"/made/up/b/{RANDOM_A}/w.bin"])
    other_random = argv_sha256(["made-up-tool", f"/made/up/a/{RANDOM_B}/w.bin"])
    plus_slash_a = argv_sha256(["made-up-tool", f"/made/up/a+/{RANDOM_A}/w.bin"])
    plus_slash_b = argv_sha256(["made-up-tool", f"/made/up/b+/{RANDOM_A}/w.bin"])
    assert host_a != host_b
    assert path_a != path_b
    assert random_a == random_b == other_random
    assert plus_slash_a == plus_slash_b


def test_the_security_page_gives_the_mode_of_each_kind_of_run_file() -> None:
    # The run files that hold raw values are made with PRIVATE_FILE_MODE; a new results file
    # gets NEW_FILE_MODE whatever the umask, and one already there keeps its own mode.
    passage = _paragraph(SECURITY, OWNER_ONLY_FILES)
    assert PRIVATE_FILE_MODE == 0o600
    assert NEW_FILE_MODE == 0o644
    assert RESULTS_FILE_MODES in passage
    assert RESULTS_DEFAULT_MODE not in passage


def test_no_page_says_a_recognised_secret_is_in_the_hash() -> None:
    pages = [SECURITY, RESULTS, CONFIG, "docs/agents.md", "skills/pairbench/SKILL.md"]
    said = [page for page in pages if "a secret in them included" in _text(page)]
    assert said == []


def test_the_forms_the_pages_promise_hold_for_the_argument_hash() -> None:
    hidden_a = argv_sha256(["made-up-tool", "--api-key", "kiwi7"])
    hidden_b = argv_sha256(["made-up-tool", "--api-key", "plum4"])
    shown_a = argv_sha256(["made-up-tool", "-k", "kiwi7"])
    shown_b = argv_sha256(["made-up-tool", "-k", "plum4"])
    assert hidden_a == hidden_b
    assert shown_a != shown_b
