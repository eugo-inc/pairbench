# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A showcase script runs again and again: each call writes into folders of its own.

The noisy-neighbour script is run from a copy of its folder and of the helper
beside it, with made-up ``pairbench`` and ``docker`` programs first on the
path. The made-up
``pairbench`` refuses a run folder that holds files, as the real one does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHOWCASE = ROOT / "showcases" / "noisy-neighbour"
FAKE_PAIRBENCH = """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--out" ]; then out="$2"; shift; fi
  shift
done
if [ -n "$out" ] && [ -d "$out" ] && [ -n "$(ls -A "$out")" ]; then
  echo "E_USAGE: the run folder $(basename "$out") must be empty or absent" >&2
  exit 2
fi
mkdir -p "$out" && : > "$out/results.json"
echo "$out" >> "$PAIRBENCH_FAKE_LOG"
"""
FAKE_ENGINE = "#!/bin/sh\nexit 0\n"


def _program(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def showcase(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """A copy of the showcase, the environment that puts the made-up programs first, the log."""
    if shutil.which("sh") is None:
        pytest.skip("needs a POSIX shell to run the showcase script")
    copy = tmp_path / "noisy-neighbour"
    shutil.copytree(SHOWCASE, copy)
    # Each showcase's script reads the shared helper from the folder above it.
    shutil.copy(SHOWCASE.parent / "publish.sh", tmp_path / "publish.sh")
    programs = tmp_path / "bin"
    programs.mkdir()
    _program(programs, "pairbench", FAKE_PAIRBENCH)
    _program(programs, "docker", FAKE_ENGINE)
    log = tmp_path / "outs.txt"
    environ = {
        "PATH": f"{programs}{os.pathsep}{os.environ.get('PATH', '')}",
        "PAIRBENCH_FAKE_LOG": str(log),
        "HOME": str(tmp_path),
    }
    return copy, environ, log


def test_the_noisy_neighbour_script_runs_twice_into_new_folders(
    showcase: tuple[Path, dict[str, str], Path],
) -> None:
    copy, environ, log = showcase
    for _call in range(2):
        done = subprocess.run(
            ["sh", str(copy / "run.sh")],
            env=environ,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        assert "E_USAGE" not in done.stderr

    outs = log.read_text(encoding="utf-8").split()
    assert len(outs) == 4
    assert len(set(outs)) == 4
    assert [Path(out).name for out in outs] == ["quiet", "noisy", "quiet", "noisy"]
    assert Path(outs[0]).parent == Path(outs[1]).parent != Path(outs[2]).parent
    assert all(Path(out).parent.parent == Path("pairbench-runs") for out in outs)
