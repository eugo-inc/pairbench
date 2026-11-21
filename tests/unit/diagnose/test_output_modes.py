# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The files the explain step writes are owner-only, and its outputs are judged only if readable.

The stacks script runs under a made-up ``perf`` on ``PATH``; the sampler runs
for real on this interpreter.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pairbench.api import InstrumentedLaunch
from pairbench.diagnose import document, instruments, pysampler

# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
# The mode a file gets under umask 022 when its program asks for 0666.
UMASK_022_MODE = 0o644
SAMPLER = Path(pysampler.__file__)
# A made-up perf: ``record`` writes a recording and runs the command, the
# other two print what perf would, and ``script`` also prints a warning.
FAKE_PERF = """#!/bin/sh
case "$1" in
record)
  while [ "$1" != "-o" ]; do shift; done
  data=$2
  while [ "$1" != "--" ]; do shift; done
  shift
  printf 'data' > "$data"
  "$@"
  exit $?
  ;;
script)
  printf 'app 1 [000] 1.0: cycles:\\n\\t aa main (/app)\\n\\n'
  echo 'a made-up warning' >&2
  ;;
buildid-list) printf '11 /app\\n' ;;
esac
"""


@pytest.fixture
def with_umask() -> Iterator[Callable[[int], None]]:
    """Set the process's umask for the test, and put the first one back after it."""
    first = os.umask(0o022)
    os.umask(first)
    yield os.umask
    os.umask(first)


def _modes(folder: Path) -> dict[str, int]:
    return {path.name: stat.S_IMODE(path.stat().st_mode) for path in sorted(folder.iterdir())}


def test_the_stacks_script_writes_what_perf_printed_owner_only_and_keeps_the_workload_s_umask(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    perf = bin_dir / "perf"
    perf.write_text(FAKE_PERF, encoding="utf-8")
    perf.chmod(0o755)
    out = tmp_path / "out"
    out.mkdir()
    made = out / "made-by-the-workload"
    wrapped = instruments.Stacks().wrap(["touch", str(made)], out=str(out), tools={})
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    done = subprocess.run(
        wrapped.argv, env=env, check=False, capture_output=True, text=True, umask=0o022
    )

    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert _modes(out) == {
        "made-by-the-workload": UMASK_022_MODE,
        "perf-buildids.txt": OWNER_ONLY,
        "perf-script.err": OWNER_ONLY,
        "perf-script.txt": OWNER_ONLY,
    }
    assert (out / "perf-script.err").read_text(encoding="utf-8") == "a made-up warning\n"


def test_the_sampler_writes_its_profile_owner_only_whatever_the_umask(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    there = out / pysampler.FOLDED_OUTPUT
    there.write_text("a made-up line 1\n", encoding="utf-8")
    there.chmod(0o644)
    program = "import time\nend = time.time() + 0.3\nwhile time.time() < end: pass\n"
    done = subprocess.run(
        [sys.executable, str(SAMPLER), "--out", str(out), "--hz", "200", "--", "-c", program],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        umask=0o022,
    )

    assert (done.returncode, done.stderr) == (0, "")
    assert _modes(out) == {pysampler.FOLDED_OUTPUT: OWNER_ONLY}
    assert "a made-up line" not in there.read_text(encoding="utf-8")


def test_the_sampler_on_an_interpreter_too_old_writes_its_file_owner_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    with_umask: Callable[[int], int],
) -> None:
    monkeypatch.setattr(pysampler, "MIN_PYTHON", (99, 0))
    there = tmp_path / pysampler.TOO_OLD_OUTPUT
    there.write_text("a made-up line\n", encoding="utf-8")
    there.chmod(0o644)
    with_umask(0o022)
    code = pysampler.main(["--out", str(tmp_path), "--", "-c", "pass"])

    assert code == pysampler.EXIT_TOO_OLD == 86
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    message = f"the sampler needs Python 99.0 or newer; this interpreter is {version}\n"
    assert there.read_text(encoding="utf-8") == message
    assert _modes(tmp_path) == {pysampler.TOO_OLD_OUTPUT: OWNER_ONLY}
    assert capsys.readouterr().err == "pysampler: " + message


@pytest.mark.parametrize(
    ("instrument", "output", "content"),
    [
        ("counters", instruments.STAT_OUTPUT, "# started on a made-up day\n"),
        ("stacks", instruments.SCRIPT_OUTPUT, "app 1 [000] 1.0: cycles:\n"),
        ("pystacks", pysampler.FOLDED_OUTPUT, "main (app.py) 3\n"),
        ("pystacks", pysampler.FOLDED_OUTPUT, ""),
    ],
    ids=["counters", "stacks", "pystacks", "pystacks-empty"],
)
def test_an_output_this_process_cannot_read_is_a_failed_launch(
    tmp_path: Path, instrument: str, output: str, content: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("needs a user other than root: root reads a file whatever its mode")
    path = tmp_path / output
    path.write_text(content, encoding="utf-8")
    path.chmod(0o000)
    launch = InstrumentedLaunch(rc=0, artifacts=tmp_path, outputs=(path,))
    try:
        judged = instruments.judge_launch(instrument, launch, "container")
    finally:
        path.chmod(OWNER_ONLY)
    assert judged == ("failed", "launch_failed")


@pytest.mark.parametrize(
    "left", ["diagnostics.json", ".diagnostics.json.partial"], ids=["the-file", "a-partial-file"]
)
def test_a_file_written_in_place_of_one_with_another_mode_is_owner_only(
    tmp_path: Path, with_umask: Callable[[int], None], left: str
) -> None:
    there = tmp_path / left
    there.write_text("a made-up older text, longer than the new one\n", encoding="utf-8")
    there.chmod(UMASK_022_MODE)
    with_umask(0o022)
    document.write_text(tmp_path / "diagnostics.json", "a made-up text\n")
    assert _modes(tmp_path) == {"diagnostics.json": OWNER_ONLY}
    assert (tmp_path / "diagnostics.json").read_text(encoding="utf-8") == "a made-up text\n"


def test_a_file_left_for_a_tool_is_empty_and_owner_only(
    tmp_path: Path, with_umask: Callable[[int], None]
) -> None:
    there = tmp_path / instruments.STAT_OUTPUT
    there.write_text("a made-up older count\n", encoding="utf-8")
    there.chmod(UMASK_022_MODE)
    with_umask(0o022)
    document.create_private(there)
    document.create_private(tmp_path / "new.txt")
    assert _modes(tmp_path) == {"new.txt": OWNER_ONLY, instruments.STAT_OUTPUT: OWNER_ONLY}
    assert there.stat().st_size == 0
