# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Python environment side kinds: ``python``, ``venv`` and ``conda``.

A launch runs the shared workload with the side's interpreter, as one process
on the host. A workload that starts with the word ``python`` or ``python3``
has that word replaced by the interpreter; any other workload is handed to the
interpreter as its arguments.

The variables that select a Python environment are set to match the side:

* ``python``: an interpreter by name or path. ``VIRTUAL_ENV``,
  ``CONDA_PREFIX`` and ``CONDA_DEFAULT_ENV`` are unset;
* ``venv``: a virtual environment folder. ``VIRTUAL_ENV`` names it, its
  ``bin`` folder goes first on ``PATH``, the conda variables are unset;
* ``conda``: a conda environment by name or prefix. ``CONDA_PREFIX`` and
  ``CONDA_DEFAULT_ENV`` name it, its ``bin`` folder goes first on ``PATH``,
  ``VIRTUAL_ENV`` is unset. The environment's activation scripts are not run.

For all three ``PYTHONHOME`` and ``PYTHONPATH`` of the caller are unset, so the
interpreter sees its own packages; the ``env`` table of the launch settings
can set them again. What was set and unset is recorded in the identity under
``selection_env`` (capture only). The identity is the ``-VV`` version line,
the hash of the sorted installed-distribution list and the interpreter's
prefix (capture only).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import KIND_CONDA, KIND_PYTHON, KIND_VENV, LaunchSettings, Side, fingerprint_of
from pairbench.sides.base import (
    CommandRunner,
    HostResolved,
    KindBase,
    find_executable,
    host_environment,
    refuse_host_settings,
    refuse_unfound,
    require_env_pass,
    resolve_workdir,
)
from pairbench.sides.identity import KEY_SELECTION_ENV, identify_on_host, python_identity

# The words of a workload that are replaced by the side's interpreter.
INTERPRETER_WORDS: Final[tuple[str, ...]] = ("python", "python3")
# Variables of the caller that would point the interpreter somewhere else.
ALWAYS_UNSET: Final[tuple[str, ...]] = ("PYTHONHOME", "PYTHONPATH")
VENV_VARIABLE: Final = "VIRTUAL_ENV"
CONDA_PREFIX_VARIABLE: Final = "CONDA_PREFIX"
CONDA_NAME_VARIABLE: Final = "CONDA_DEFAULT_ENV"
CONDA_EXE_VARIABLE: Final = "CONDA_EXE"
CONDA_BASE_NAME: Final = "base"
# The value recorded for PATH: the environment's own folder in front of the
# caller's PATH.
PATH_REST: Final = "$PATH"

_WINDOWS = os.name == "nt"


def interpreter_command(
    side: Side, interpreter: str, workload: tuple[str, ...] | None
) -> tuple[str, ...]:
    """Return the complete command of a Python environment side.

    A leading ``python`` or ``python3`` of the workload is replaced by the
    interpreter; otherwise the interpreter goes in front of the workload. A
    side without a shared workload has nothing to run and is refused with
    ``E_USAGE``.
    """
    if not workload:
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: a Python environment side runs the shared workload; "
            "give one after --",
        )
    rest = workload[1:] if workload[0] in INTERPRETER_WORDS else workload
    return (interpreter, *rest)


def _bin_folder(prefix: Path) -> Path:
    return prefix / ("Scripts" if _WINDOWS else "bin")


def _interpreter_in(prefix: Path, *, venv: bool) -> Path:
    if _WINDOWS:
        return prefix / ("Scripts" if venv else "") / "python.exe"
    return prefix / "bin" / "python"


@dataclass(frozen=True)
class Selection:
    """The variables a Python environment side sets and unsets, and its interpreter."""

    interpreter: str
    set: Mapping[str, str] = field(default_factory=dict)
    unset: tuple[str, ...] = ()
    path_first: str | None = None

    def recorded(self) -> dict[str, Any]:
        """What the identity records under ``selection_env``."""
        shown = dict(self.set)
        if self.path_first is not None:
            shown["PATH"] = f"{self.path_first}{os.pathsep}{PATH_REST}"
        return {"set": shown, "unset": tuple(sorted(self.unset))}

    def variables(self, environ: Mapping[str, str]) -> dict[str, str]:
        """The variables laid over the caller's environment."""
        out = dict(self.set)
        if self.path_first is not None:
            rest = environ.get("PATH", os.defpath)
            out["PATH"] = f"{self.path_first}{os.pathsep}{rest}" if rest else self.path_first
        return out


@dataclass(frozen=True)
class PythonPlan:
    """Everything a Python environment side needs before its identity is read."""

    side: Side
    settings: LaunchSettings
    selection: Selection
    command: tuple[str, ...]
    environment: Mapping[str, str]
    cwd: str | None


def python_side_identity(
    runner: CommandRunner, plan: PythonPlan, *, identify: bool
) -> dict[str, Any]:
    """Read the identity of a Python environment side: the one function both look-up and
    resolve use. ``identify`` runs the configured ``identify`` command as well."""
    identity = python_identity(
        runner,
        plan.selection.interpreter,
        side=plan.side.name,
        env=plan.environment,
        cwd=plan.cwd,
        timeout_s=plan.settings.timeout_s,
    )
    identity[KEY_SELECTION_ENV] = plan.selection.recorded()
    if identify:
        identity.update(
            identify_on_host(
                runner, plan.side, plan.settings, environment=plan.environment, cwd=plan.cwd
            )
        )
    return identity


class _PythonKind(KindBase):
    """What the three Python environment kinds share."""

    def _select(self, side: Side, ctx: api.SideContext, cwd: str | None) -> Selection:
        raise NotImplementedError

    def _spec_text(self, side: Side, key: str) -> str:
        value = side.spec.get(key)
        if not isinstance(value, str) or not value:
            raise Refusal("E_USAGE", f"side {side.name!r}: a {side.kind} side names its {key}")
        return value

    def _plan(self, side: Side, ctx: api.SideContext) -> PythonPlan:
        refuse_host_settings(side, ctx.settings)
        cwd = resolve_workdir(side, ctx.settings)
        selection = self._select(side, ctx, cwd)
        command = interpreter_command(side, selection.interpreter, ctx.workload)
        environment = host_environment(
            ctx.environ,
            ctx.settings,
            remove=selection.unset,
            selection=selection.variables(ctx.environ),
        )
        return PythonPlan(side, ctx.settings, selection, command, environment, cwd)

    def look_up(self, side: Side, ctx: api.SideContext) -> api.SideLookup:
        """Find the interpreter and ask it for its version and distributions."""
        plan = self._plan(side, ctx)
        identity = python_side_identity(self._runner, plan, identify=False)
        fingerprint = ""
        if not ctx.settings.identify:
            fingerprint = fingerprint_of(identity, ctx.settings.effective())
        return api.SideLookup(status="identified", identity=identity, fingerprint=fingerprint)

    def resolve(self, side: Side, ctx: api.SideContext) -> api.ResolvedSide:
        """Find the interpreter, run the identify command, record identity and fingerprint."""
        plan = self._plan(side, ctx)
        require_env_pass(side, ctx.settings, ctx.environ)
        runner = self._runner

        def read_identity() -> dict[str, Any]:
            return python_side_identity(runner, plan, identify=True)

        identity = read_identity()
        fingerprint = fingerprint_of(identity, ctx.settings.effective())
        return HostResolved(
            side=side.with_identity(identity, fingerprint),
            settings=ctx.settings,
            command=plan.command,
            executable=plan.selection.interpreter,
            environment=plan.environment,
            cwd=plan.cwd,
            read_identity=read_identity,
            host=self._host,
        )


class PythonKind(_PythonKind):
    """The ``python`` side kind: an interpreter by name or by path."""

    name = KIND_PYTHON

    def _select(self, side: Side, ctx: api.SideContext, cwd: str | None) -> Selection:
        word = self._spec_text(side, "interpreter")
        base = host_environment(ctx.environ, ctx.settings)
        found = find_executable(word, environment=base, cwd=cwd)
        if found is None:
            raise refuse_unfound(side, "interpreter", word)
        unset = (*ALWAYS_UNSET, VENV_VARIABLE, CONDA_PREFIX_VARIABLE, CONDA_NAME_VARIABLE)
        return Selection(interpreter=found, unset=unset)


class VenvKind(_PythonKind):
    """The ``venv`` side kind: a virtual environment folder."""

    name = KIND_VENV

    def _select(self, side: Side, ctx: api.SideContext, cwd: str | None) -> Selection:
        word = self._spec_text(side, "venv")
        prefix = Path(word) if Path(word).is_absolute() else Path(cwd or os.getcwd()) / word
        prefix = Path(os.path.abspath(prefix))
        interpreter = _interpreter_in(prefix, venv=True)
        if not (prefix / "pyvenv.cfg").is_file() or not interpreter.is_file():
            raise refuse_unfound(side, "virtual environment", word)
        return Selection(
            interpreter=str(interpreter),
            set={VENV_VARIABLE: str(prefix)},
            unset=(*ALWAYS_UNSET, CONDA_PREFIX_VARIABLE, CONDA_NAME_VARIABLE),
            path_first=str(_bin_folder(prefix)),
        )


class CondaKind(_PythonKind):
    """The ``conda`` side kind: a conda environment by name or by prefix.

    A name is looked up with ``conda info --json``: ``base`` is the root
    prefix, any other name the environment whose folder has that name. The
    conda program is the one ``CONDA_EXE`` names in the caller's environment,
    or ``conda`` on its ``PATH``.
    """

    name = KIND_CONDA

    def _prefix(self, side: Side, ctx: api.SideContext, word: str, cwd: str | None) -> Path:
        if os.sep in word or (os.altsep is not None and os.altsep in word):
            path = Path(word) if Path(word).is_absolute() else Path(cwd or os.getcwd()) / word
            return Path(os.path.abspath(path))
        program = ctx.environ.get(CONDA_EXE_VARIABLE) or shutil.which(
            "conda", path=ctx.environ.get("PATH", os.defpath)
        )
        if not program:
            raise Refusal(
                "E_SIDE_UNRESOLVED",
                f"side {side.name!r}: no conda program was found to look up the environment "
                f"{word!r}",
            )
        done = self._runner([program, "info", "--json"], env=dict(ctx.environ))
        info: Any = None
        if done.rc == 0 and not done.timed_out:
            try:
                info = json.loads(done.stdout)
            except ValueError:
                info = None
        if not isinstance(info, dict):
            raise Refusal(
                "E_SIDE_UNRESOLVED",
                f"side {side.name!r}: conda did not list its environments",
                detail={"stderr": done.stderr[-2000:]},
            )
        root = info.get("root_prefix")
        if word == CONDA_BASE_NAME and isinstance(root, str):
            return Path(root)
        envs = [item for item in info.get("envs", []) if isinstance(item, str)]
        matches = [item for item in envs if Path(item).name == word and item != root]
        if len(matches) != 1:
            raise refuse_unfound(side, "conda environment", word)
        return Path(matches[0])

    def _select(self, side: Side, ctx: api.SideContext, cwd: str | None) -> Selection:
        word = self._spec_text(side, "conda")
        prefix = self._prefix(side, ctx, word, cwd)
        interpreter = _interpreter_in(prefix, venv=False)
        if not (prefix / "conda-meta").is_dir() or not interpreter.is_file():
            raise refuse_unfound(side, "conda environment", word)
        name = word if os.sep not in word else prefix.name
        return Selection(
            interpreter=str(interpreter),
            set={CONDA_PREFIX_VARIABLE: str(prefix), CONDA_NAME_VARIABLE: name},
            unset=(*ALWAYS_UNSET, VENV_VARIABLE),
            path_first=str(_bin_folder(prefix)),
        )
