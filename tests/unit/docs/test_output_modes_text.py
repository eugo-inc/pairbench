# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say which files that hold what a process printed are owner-only, and which are not.

The positive control's page says the files its two runs write into are made
owner-only, and what that means for an image whose user is neither root nor
the caller. The security policy, the diagnostics page and the results
reference say the explain step's files are owner-only, that the report page
embeds what they hold, that a file another program writes into a launch's
folder loses the group's and others' permissions when the launch ends, and
that a file the container of an image side or the server's container of a
serving side wrote as another user is handed back however the launch ends,
or named when it cannot be, and that a folder such a container made keeps
its mode. The security policy, the results reference and the config
reference say the capture is owner-only; the security policy says which
files and folders keep the umask's mode; the positive control's page says
which users an image may run as for the control and that rebuilding the
image is the way to change it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CONTROL_PAGE = "docs/method/positive-control.md"
SECURITY = "SECURITY.md"
CONTROL_SENTENCES = (
    "pairbench creates them readable and writable by you only (mode `0600`) whatever your "
    "umask, so an image whose user is anyone else gets the control `not_run` with the loud "
    "note;",
    '`controls.positive_via = "factor"`, below, needs no such files.',
)
DIAGNOSTICS_PAGE = "docs/method/diagnostics.md"
RESULTS_REFERENCE = "docs/reference/results-schema.md"
SECURITY_SENTENCES = (
    "The files of the explain step, `diagnostics.json` and the folded stacks, differences and "
    "flame graphs under `profiles/`, are owner-only too, and so is what its instruments print "
    "while they run; `report.html` embeds the diagnostics and the flame graphs when the step ran.",
    "A file that another program writes into a launch's folder, such as the export a driver "
    "reads, the report `nsys` or `ncu` writes for `pairbench profile` or a file your workload "
    "writes, has the mode that program gives it while the launch runs, which under a umask of "
    "`022` lets every user read it; when the launch ends, pairbench takes the group's and "
    "others' permissions off every such file you own.",
    "A file that the container of an `image` side, or the server's container of a serving side, "
    "writes as another user, such as root, is handed back to you before that, with one short "
    "container of the same image that runs `chown`, however the launch ends, an interrupt or an "
    "error included.",
    "When pairbench cannot hand such files back, for example when the engine cannot be reached "
    "or a second interrupt stops the hand-back, a note on standard error and in the results "
    "names the launch folder whose files still belong to the image's user and may be readable "
    "by other users; such a file keeps its mode.",
    "A folder that such a program or container makes in a launch's folder keeps the mode it was "
    "made with, so other users may be able to list the names in it.",
)
DIAGNOSTICS_SENTENCE = (
    "`diagnostics.json`, the folded stacks, differences and flame graphs under `profiles/`, and "
    "what the instruments print while they run are readable and writable by you only (mode "
    "`0600`) whatever your umask; `report.html` is a results file, readable by all (mode "
    "`0644`), and it embeds the diagnostics and the flame graphs when the step ran."
)
RESULTS_ROWS = (
    "| `diagnostics.json` | the explain step's document, schema `pairbench/diagnostics/v1`, "
    "readable by its owner only (mode `0600`) | holds names from your code |",
    "| `profiles/` | folded stacks, differences and flame graphs, and the reports of "
    "`pairbench profile --tool nsys` or `ncu`, readable by their owner only (mode `0600`) | "
    "holds names from your code |",
)
CONFIG_REFERENCE = "docs/reference/config.md"
# Each phrase that says the capture, or what a process printed, is owner-only,
# or which user an image of a side with the control may run as.
OWNER_ONLY_PHRASES = {
    "security-the-capture": (
        SECURITY,
        "pairbench creates the capture, and the files that hold what each process,",
    ),
    "security-load-step": (
        SECURITY,
        "the files that hold what each process, load step and server printed, readable and "
        "writable by their owner only (mode `0600`), so other users of a shared machine cannot "
        "read them;",
    ),
    "results-capture-row": (
        RESULTS_REFERENCE,
        "| `capture.jsonl` | the raw record of the run, one JSON record per line, readable by its "
        "owner only (mode `0600`) |",
    ),
    "config-capture": (
        CONFIG_REFERENCE,
        "The capture, `capture.jsonl`, keeps the command as typed: it is private to the person "
        "who ran the benchmark, and pairbench creates it readable and writable by its owner only "
        "(mode `0600`), as it does the files that hold what each process, load step and server "
        "printed.",
    ),
    "control-user": (
        CONTROL_PAGE,
        "the image needs a shell, and its user must be able to write those files: root, or a "
        "user with your user id.",
    ),
}
UMASK_SENTENCE = (
    "`plan.tsv`, which holds the side names and the round order, and the charts under "
    "`charts/`, which draw what `results.json` holds, have the mode your umask gives, and so do "
    "the run folder and the folders pairbench makes in it: under a umask of `022` every user "
    "can read them and list the names in those folders, but cannot open a file in them that is "
    "owner-only."
)
REBUILD_SENTENCE = (
    "No setting of pairbench chooses the user a container runs as, so to give an image whose "
    "user is anyone else the control, rebuild it to run as root or as your user id."
)
ARTIFACTS_PHRASE = (
    "once a launch ends, every file in its folder that you own is readable by its owner only | "
    "private: it holds what your workload and its tools printed |"
)


def plain(name: str) -> str:
    """The text of a file with its lines joined, so a phrase broken across lines is found."""
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


def test_the_control_page_says_its_run_files_are_owner_only_and_what_that_means() -> None:
    text = plain(CONTROL_PAGE)
    assert [sentence in text for sentence in CONTROL_SENTENCES] == [True, True]


def test_the_security_policy_says_which_files_are_owner_only_and_which_keep_a_mode() -> None:
    text = plain(SECURITY)
    assert [sentence in text for sentence in SECURITY_SENTENCES] == [True] * 5


def test_the_diagnostics_page_says_its_files_are_owner_only_and_the_report_page_is_not() -> None:
    assert DIAGNOSTICS_SENTENCE in plain(DIAGNOSTICS_PAGE)


def test_the_results_reference_gives_the_mode_of_the_diagnostics_and_the_profiles() -> None:
    lines = (ROOT / RESULTS_REFERENCE).read_text(encoding="utf-8").splitlines()
    assert [row in lines for row in RESULTS_ROWS] == [True, True]


def test_the_results_reference_says_the_files_a_launch_leaves_are_owner_only() -> None:
    rows = [
        line
        for line in (ROOT / RESULTS_REFERENCE).read_text(encoding="utf-8").splitlines()
        if line.startswith("| `artifacts/` |")
    ]
    assert [row.endswith(ARTIFACTS_PHRASE) for row in rows] == [True]


@pytest.mark.parametrize("page,phrase", OWNER_ONLY_PHRASES.values(), ids=OWNER_ONLY_PHRASES.keys())
def test_the_pages_say_the_capture_is_owner_only_and_which_user_the_control_needs(
    page: str, phrase: str
) -> None:
    assert phrase in plain(page)


def test_the_security_policy_says_which_files_and_folders_keep_the_umask_s_mode() -> None:
    assert UMASK_SENTENCE in plain(SECURITY)


def test_the_control_page_says_an_image_is_rebuilt_to_change_its_user() -> None:
    assert REBUILD_SENTENCE in plain(CONTROL_PAGE)
