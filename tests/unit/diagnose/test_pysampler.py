# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The stack sampler of ``pystacks``, run as the explain launch runs it: a separate interpreter."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pairbench.diagnose import pysampler

SAMPLER = Path(pysampler.__file__)

WORK = textwrap.dedent(
    """\
    import sys
    import time


    def nap():
        time.sleep(0.4)


    def spin():
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            pass


    nap()
    spin()
    print(repr(sys.argv), __name__)
    sys.exit(int(sys.argv[1]))
    """
)


def _sample(
    tmp_path: Path, *program: str, hz: int = 200
) -> tuple[subprocess.CompletedProcess[str], str]:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    done = subprocess.run(
        [sys.executable, str(SAMPLER), "--out", str(out), "--hz", str(hz), "--", *program],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    folded = out / "pystacks.folded"
    return done, folded.read_text(encoding="utf-8") if folded.exists() else "<none>"


def _stacks(folded: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in folded.splitlines():
        stack, _, count = line.rpartition(" ")
        counts[stack] = int(count)
    return counts


def test_the_sampler_keeps_a_syntax_that_old_interpreters_read() -> None:
    tree = ast.parse(SAMPLER.read_text(encoding="utf-8"), feature_version=(3, 8))
    nodes = list(ast.walk(tree))
    assert [n for n in nodes if isinstance(n, ast.JoinedStr)] == []
    assert [n for n in nodes if isinstance(n, ast.AnnAssign)] == []
    functions = [n for n in nodes if isinstance(n, ast.FunctionDef)]
    assert functions
    for function in functions:
        assert function.returns is None, function.name
        assert all(a.annotation is None for a in function.args.args), function.name
    starred = [
        n
        for n in nodes
        if isinstance(n, ast.List) and any(isinstance(e, ast.Starred) for e in n.elts)
    ]
    assert starred == []


def test_the_imports_of_the_sampler_are_the_standard_library_only() -> None:
    tree = ast.parse(SAMPLER.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names)


def test_a_script_is_sampled_from_its_own_outermost_frame(tmp_path: Path) -> None:
    (tmp_path / "work.py").write_text(WORK, encoding="utf-8")
    done, folded = _sample(tmp_path, "work.py", "3")
    assert done.returncode == 3
    assert done.stdout == "['work.py', '3'] __main__\n"
    stacks = _stacks(folded)
    assert stacks, folded
    assert all(s.startswith("<module> (work.py)") for s in stacks), folded
    assert stacks.get("<module> (work.py);nap (work.py)", 0) > 0, folded
    assert any(s.startswith("<module> (work.py);spin (work.py)") for s in stacks), folded
    assert "pysampler.py" not in folded
    assert "runpy" not in folded
    assert folded.splitlines() == sorted(folded.splitlines())


def test_a_module_is_run_with_dash_m(tmp_path: Path) -> None:
    (tmp_path / "workmod.py").write_text(WORK, encoding="utf-8")
    done, folded = _sample(tmp_path, "-m", "workmod", "0")
    assert (done.returncode, done.stdout) == (
        0,
        f"[{str(tmp_path / 'workmod.py')!r}, '0'] __main__\n",
    )
    stacks = _stacks(folded)
    assert stacks.get("<module> (workmod.py);nap (workmod.py)", 0) > 0, folded
    assert all(s.startswith("<module> (workmod.py)") for s in stacks), folded


def test_a_name_outside_ascii_is_written_as_utf8_under_an_ascii_locale(tmp_path: Path) -> None:
    (tmp_path / "work.py").write_text(
        "import time\ndef naïve():\n    time.sleep(0.3)\nnaïve()\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    out.mkdir()
    env = {
        **os.environ,
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONIOENCODING": "",
    }
    done = subprocess.run(
        [sys.executable, str(SAMPLER), "--out", str(out), "--hz", "200", "--", "work.py"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert (done.returncode, done.stderr) == (0, "")
    assert sorted(p.name for p in out.iterdir()) == ["pystacks.folded"]
    folded = (out / "pystacks.folded").read_text(encoding="utf-8")
    assert _stacks(folded).get("<module> (work.py);naïve (work.py)", 0) > 0, folded


def test_code_is_run_with_dash_c(tmp_path: Path) -> None:
    code = "import sys, time\ndef nap():\n    time.sleep(0.3)\nnap()\nprint(sys.argv, __name__)\n"
    done, folded = _sample(tmp_path, f"-c{code}", "a")
    assert (done.returncode, done.stdout) == (0, "['-c', 'a'] __main__\n")
    assert _stacks(folded).get("<module> (<string>);nap (<string>)", 0) > 0, folded


def test_a_thread_the_workload_starts_is_sampled_as_it_is(tmp_path: Path) -> None:
    (tmp_path / "threads.py").write_text(
        textwrap.dedent(
            """\
            import threading
            import time


            def worker():
                time.sleep(0.4)


            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            """
        ),
        encoding="utf-8",
    )
    done, folded = _sample(tmp_path, "threads.py")
    assert done.returncode == 0
    assert any(s.endswith(";worker (threads.py)") for s in _stacks(folded)), folded


def test_a_workload_that_raises_exits_with_1_and_its_stacks_are_still_written(
    tmp_path: Path,
) -> None:
    (tmp_path / "boom.py").write_text(
        "import time\ndef nap():\n    time.sleep(0.2)\nnap()\nraise ValueError('x')\n",
        encoding="utf-8",
    )
    done, folded = _sample(tmp_path, "boom.py")
    assert done.returncode == 1
    assert done.stderr.splitlines()[-1] == "ValueError: x"
    assert _stacks(folded).get("<module> (boom.py);nap (boom.py)", 0) > 0, folded


def test_an_exit_with_a_text_exits_with_1(tmp_path: Path) -> None:
    (tmp_path / "say.py").write_text("import sys\nsys.exit('stopped')\n", encoding="utf-8")
    done, folded = _sample(tmp_path, "say.py")
    assert (done.returncode, done.stderr) == (1, "stopped\n")
    assert set(_stacks(folded)) <= {"<module> (say.py)"}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--hz", "9", "--", "x.py"], "pysampler: --out is required\n"),
        (["--out", "o", "--bogus", "--", "x.py"], "pysampler: unknown argument '--bogus'\n"),
        (["--out", "o"], "pysampler: no program after --\n"),
        (["--out", "o", "--"], "pysampler: no program after --\n"),
        (["--out", "o", "--", "-m"], "pysampler: -m needs a value\n"),
    ],
)
def test_a_wrong_call_is_a_usage_error(
    arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert pysampler.main(arguments) == pysampler.EXIT_USAGE == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == message + "usage: python pysampler.py --out DIR --hz N -- PROGRAM\n"


def test_an_interpreter_too_old_runs_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pysampler, "MIN_PYTHON", (99, 0))
    ran = tmp_path / "ran"
    code = pysampler.main(["--out", str(tmp_path), "--", "-c", f"open({str(ran)!r}, 'w')"])
    assert code == pysampler.EXIT_TOO_OLD == 86
    version = f"{sys.version_info[0]}.{sys.version_info[1]}"
    message = f"the sampler needs Python 99.0 or newer; this interpreter is {version}\n"
    assert (tmp_path / "pystacks-too-old.txt").read_text(encoding="utf-8") == message
    assert capsys.readouterr().err == "pysampler: " + message
    assert not ran.exists()
    assert not (tmp_path / "pystacks.folded").exists()


@pytest.mark.parametrize(
    ("program", "plan"),
    [
        (["-m", "pkg.mod", "a"], ("module", "pkg.mod", ["a"], "")),
        (["-mpkg", "a"], ("module", "pkg", ["a"], "")),
        (["-c", "pass", "a", "b"], ("code", "pass", ["a", "b"], "")),
        (["-cpass"], ("code", "pass", [], "")),
        (["/w/x/run.py", "-m"], ("path", "/w/x/run.py", ["-m"], "/w/x")),
    ],
)
def test_plan_program(program: list[str], plan: tuple[str, str, list[str], str]) -> None:
    assert pysampler.plan_program(program) == plan


def test_a_frame_name_holds_no_separator_of_the_folded_format() -> None:
    code = compile("pass", "/a/b/w.py", "exec").replace(co_name="f;g\th\ni")
    assert pysampler.frame_name(code) == "f:g h i (w.py)"
