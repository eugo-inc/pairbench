# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Python environment side kinds: interpreter word, selection variables, identity."""

from __future__ import annotations

import json
import os
import sys
import venv
from pathlib import Path
from typing import Any

import pytest

from pairbench import api
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.model import LaunchSettings, Side
from pairbench.sides.base import Completed
from pairbench.sides.pyenv import CondaKind, PythonKind, VenvKind, interpreter_command

# SHA-256 of "a==1\nb==2".
AB_PACKAGES_SHA256 = "76457601f3989b696f764fe654a98acb7396d4db67fc3c100cce7b2e11acca15"
VERSION_LINE = "Python 3.99.0 (made-up build)"


def _interpreter_answers(prefix: str = "/made/up/env") -> Any:
    def handler(argv: tuple[str, ...]) -> Completed:
        if argv[1:] == ("-VV",):
            return Completed(rc=0, stdout=VERSION_LINE + "\n")
        if argv[1] == "-c":
            return Completed(rc=0, stdout=json.dumps({"prefix": prefix, "dists": ["b==2", "a==1"]}))
        raise AssertionError(f"unexpected command {argv}")

    return handler


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def _ctx(environ: dict[str, str] | None = None, **extra: Any) -> api.SideContext:
    settings = extra.pop("settings", LaunchSettings())
    workload = extra.pop("workload", ("python", "bench.py"))
    return api.SideContext(
        run_id="run-a", settings=settings, environ=environ or {}, workload=workload, **extra
    )


# --- the interpreter word ---------------------------------------------------


@pytest.mark.parametrize(
    ("workload", "command"),
    [
        (("python", "bench.py"), ("/env/bin/python", "bench.py")),
        (("python3", "-m", "mod"), ("/env/bin/python", "-m", "mod")),
        (("bench.py", "--n", "3"), ("/env/bin/python", "bench.py", "--n", "3")),
        (("python3.12", "bench.py"), ("/env/bin/python", "python3.12", "bench.py")),
    ],
    ids=["python", "python3", "script", "versioned-word-is-an-argument"],
)
def test_only_the_words_python_and_python3_are_replaced_by_the_interpreter(
    workload: tuple[str, ...], command: tuple[str, ...]
) -> None:
    side = Side.python("new", interpreter="python3")
    assert interpreter_command(side, "/env/bin/python", workload) == command


def test_a_python_side_without_a_workload_is_a_usage_error() -> None:
    with pytest.raises(Refusal) as caught:
        interpreter_command(Side.python("new", interpreter="python3"), "/env/bin/python", None)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


# --- python -----------------------------------------------------------------


def test_an_interpreter_side_unsets_the_variables_of_other_environments(
    tmp_path: Path, fake_runner: Any
) -> None:
    interpreter = _executable(tmp_path / "bin" / "python3")
    environ = {
        "PATH": str(tmp_path / "bin"),
        "VIRTUAL_ENV": "/made/up/other",
        "CONDA_PREFIX": "/made/up/conda",
        "CONDA_DEFAULT_ENV": "other",
        "PYTHONPATH": "/made/up/src",
        "PYTHONHOME": "/made/up/home",
        "KEPT": "yes",
    }
    runner = fake_runner(_interpreter_answers())
    resolved = PythonKind(runner=runner).resolve(
        Side.python("new", interpreter="python3"), _ctx(environ)
    )
    assert resolved.command == (str(interpreter), "bench.py")
    assert runner.calls[0].env == {"PATH": str(tmp_path / "bin"), "KEPT": "yes"}
    assert resolved.side.identity == {
        "python_version": VERSION_LINE,
        "packages_sha256": AB_PACKAGES_SHA256,
        "prefix": "/made/up/env",
        "selection_env": {
            "set": {},
            "unset": (
                "CONDA_DEFAULT_ENV",
                "CONDA_PREFIX",
                "PYTHONHOME",
                "PYTHONPATH",
                "VIRTUAL_ENV",
            ),
        },
    }
    assert resolved.side.public_identity() == {
        "python_version": VERSION_LINE,
        "packages_sha256": AB_PACKAGES_SHA256,
    }


def test_the_look_up_asks_the_interpreter_and_matches_resolve(
    tmp_path: Path, fake_runner: Any
) -> None:
    _executable(tmp_path / "bin" / "python3")
    ctx = _ctx({"PATH": str(tmp_path / "bin")})
    side = Side.python("new", interpreter="python3")
    runner = fake_runner(_interpreter_answers())
    found = PythonKind(runner=runner).look_up(side, ctx)
    resolved = PythonKind(runner=fake_runner(_interpreter_answers())).resolve(side, ctx)
    assert len(runner.calls) == 2
    assert found.identity == resolved.side.identity
    assert found.fingerprint == resolved.side.fingerprint


def test_an_interpreter_that_is_not_there_is_refused(fake_runner: Any) -> None:
    side = Side.python("new", interpreter="/made/up/bin/python9")
    with pytest.raises(Refusal) as caught:
        PythonKind(runner=fake_runner(_interpreter_answers())).look_up(side, _ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert "/made/up/bin" not in caught.value.message


@pytest.mark.parametrize("key", ["memory", "network"])
def test_a_python_side_refuses_container_settings(
    tmp_path: Path, fake_runner: Any, key: str
) -> None:
    _executable(tmp_path / "bin" / "python3")
    settings = LaunchSettings(memory="8g") if key == "memory" else LaunchSettings(network="none")
    with pytest.raises(Refusal) as caught:
        PythonKind(runner=fake_runner(_interpreter_answers())).resolve(
            Side.python("new", interpreter="python3"),
            _ctx({"PATH": str(tmp_path / "bin")}, settings=settings),
        )
    assert caught.value.code == "E_ENGINE_UNSUPPORTED"


# --- venv -------------------------------------------------------------------


def _fake_venv(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /made/up\n")
    _executable(root / "bin" / "python")
    return root


def test_a_virtual_environment_side_sets_its_variables_and_records_them(
    tmp_path: Path, fake_runner: Any
) -> None:
    root = _fake_venv(tmp_path / "env")
    runner = fake_runner(_interpreter_answers(str(root)))
    environ = {"PATH": "/made/up/bin", "CONDA_PREFIX": "/made/up/conda"}
    resolved = VenvKind(runner=runner).resolve(Side.python("new", venv=str(root)), _ctx(environ))
    assert resolved.command == (str(root / "bin" / "python"), "bench.py")
    assert runner.calls[0].env == {
        "PATH": f"{root / 'bin'}{os.pathsep}/made/up/bin",
        "VIRTUAL_ENV": str(root),
    }
    assert resolved.side.identity["selection_env"] == {
        "set": {"VIRTUAL_ENV": str(root), "PATH": f"{root / 'bin'}{os.pathsep}$PATH"},
        "unset": ("CONDA_DEFAULT_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH"),
    }


def test_a_folder_that_is_no_virtual_environment_is_refused(
    tmp_path: Path, fake_runner: Any
) -> None:
    folder = tmp_path / "plain"
    _executable(folder / "bin" / "python")
    with pytest.raises(Refusal) as caught:
        VenvKind(runner=fake_runner(_interpreter_answers())).look_up(
            Side.python("new", venv=str(folder)), _ctx()
        )
    assert caught.value.code == "E_SIDE_UNRESOLVED"


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="needs os.wait4 for the resource usage")
def test_a_real_virtual_environment_runs_the_workload_inside_it(tmp_path: Path) -> None:
    root = tmp_path / "env"
    venv.create(root, with_pip=False, symlinks=os.name != "nt")
    script = tmp_path / "bench.py"
    script.write_text("import os, sys; print(sys.prefix == os.environ['VIRTUAL_ENV'])\n")
    ctx = _ctx(dict(os.environ), workload=("python", str(script)))
    resolved = VenvKind().resolve(Side.python("new", venv=str(root)), ctx)
    assert resolved.side.identity["python_version"].startswith("Python 3.")
    assert resolved.side.identity["prefix"] == str(root)
    request = api.LaunchRequest(
        run_id="run-a",
        seq=1,
        phase="round",
        round=1,
        pos=1,
        name="new",
        artifacts=tmp_path,
        argv=resolved.command,
    )
    outcome = resolved.launch(request)
    assert outcome.rc == 0
    assert (tmp_path / "stdout.txt").read_text() == "True\n"
    assert outcome.cpu_s is not None


# --- conda ------------------------------------------------------------------


def _fake_conda(root: Path) -> Path:
    (root / "conda-meta").mkdir(parents=True)
    _executable(root / "bin" / "python")
    return root


def test_a_conda_environment_given_by_prefix_needs_no_conda_program(
    tmp_path: Path, fake_runner: Any
) -> None:
    prefix = _fake_conda(tmp_path / "envs" / "fast")
    runner = fake_runner(_interpreter_answers(str(prefix)))
    resolved = CondaKind(runner=runner).resolve(
        Side.python("new", conda=str(prefix)), _ctx({"PATH": "/made/up/bin"})
    )
    assert resolved.side.identity["selection_env"] == {
        "set": {
            "CONDA_PREFIX": str(prefix),
            "CONDA_DEFAULT_ENV": "fast",
            "PATH": f"{prefix / 'bin'}{os.pathsep}$PATH",
        },
        "unset": ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"),
    }


def _conda_info(root: Path) -> Any:
    answers = _interpreter_answers(str(root))

    def handler(argv: tuple[str, ...]) -> Completed:
        if argv[1:] == ("info", "--json"):
            envs = [str(root), str(root / "envs" / "fast")]
            return Completed(rc=0, stdout=json.dumps({"root_prefix": str(root), "envs": envs}))
        result: Completed = answers(argv)
        return result

    return handler


def test_a_conda_environment_given_by_name_is_found_with_conda_info(
    tmp_path: Path, fake_runner: Any
) -> None:
    root = _fake_conda(tmp_path / "conda")
    fast = _fake_conda(root / "envs" / "fast")
    runner = fake_runner(_conda_info(root))
    environ = {"CONDA_EXE": "/made/up/bin/conda"}
    named = CondaKind(runner=runner).resolve(Side.python("new", conda="fast"), _ctx(environ))
    assert named.command == (str(fast / "bin" / "python"), "bench.py")
    assert runner.argvs()[0] == ("/made/up/bin/conda", "info", "--json")
    base = CondaKind(runner=fake_runner(_conda_info(root))).resolve(
        Side.python("old", conda="base"), _ctx(environ)
    )
    assert base.command == (str(root / "bin" / "python"), "bench.py")


def test_an_unknown_conda_name_or_a_missing_conda_program_is_refused(
    tmp_path: Path, fake_runner: Any
) -> None:
    root = _fake_conda(tmp_path / "conda")
    with pytest.raises(Refusal) as caught:
        CondaKind(runner=fake_runner(_conda_info(root))).look_up(
            Side.python("new", conda="nothing"), _ctx({"CONDA_EXE": "/made/up/bin/conda"})
        )
    assert caught.value.code == "E_SIDE_UNRESOLVED"
    with pytest.raises(Refusal) as caught:
        CondaKind(runner=fake_runner(_conda_info(root))).look_up(
            Side.python("new", conda="fast"), _ctx({"PATH": ""})
        )
    assert caught.value.code == "E_SIDE_UNRESOLVED"


def test_this_interpreter_resolves_as_a_python_side() -> None:
    ctx = _ctx(dict(os.environ))
    resolved = PythonKind().resolve(Side.python("new", interpreter=sys.executable), ctx)
    assert resolved.side.identity["python_version"].startswith("Python 3.")
    assert resolved.command == (sys.executable, "bench.py")
