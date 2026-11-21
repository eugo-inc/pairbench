# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``cmd`` side kind: a command line that runs as one process on the host.

A command that holds the argument ``{workload}`` has the shared workload put in
its place; one without it runs exactly as written, and giving a shared workload
as well is a usage error. The identity records the hash of the executable file
the command starts and the hash of the complete argument list; the path of the
file stays in the capture.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import (
    KIND_CMD,
    WORKLOAD_PLACEHOLDER,
    LaunchSettings,
    Side,
    fingerprint_of,
    hashed_command,
)
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
from pairbench.sides.identity import (
    KEY_ARGV_SHA256,
    KEY_EXECUTABLE,
    KEY_EXECUTABLE_SHA256,
    hashed_sha256,
    identify_on_host,
    side_file_sha256,
)


def substitute_workload(
    side: Side, argv: Sequence[str], workload: Sequence[str] | None
) -> tuple[str, ...]:
    """Return the complete command of a ``cmd`` side, ``{workload}`` replaced.

    The argument ``{workload}`` is replaced by the arguments of the shared
    workload. Refused with ``E_USAGE``: ``{workload}`` without a shared
    workload, a shared workload with a command that has no ``{workload}``,
    and ``{workload}`` inside a longer argument, where it cannot be replaced
    by a list of arguments.
    """
    shared = tuple(workload or ())
    if any(WORKLOAD_PLACEHOLDER in arg and arg != WORKLOAD_PLACEHOLDER for arg in argv):
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: {WORKLOAD_PLACEHOLDER} must be an argument of its own",
        )
    holds = WORKLOAD_PLACEHOLDER in argv
    if holds and not shared:
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: the command holds {WORKLOAD_PLACEHOLDER} and no shared "
            "workload was given after --",
        )
    if shared and not holds:
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: a shared workload was given but the command has no "
            f"{WORKLOAD_PLACEHOLDER}; add {WORKLOAD_PLACEHOLDER} where the workload goes",
        )
    out: list[str] = []
    for arg in argv:
        out.extend(shared if arg == WORKLOAD_PLACEHOLDER else (arg,))
    return tuple(out)


def declared_argv(side: Side) -> tuple[str, ...]:
    """Return the argument list a ``cmd`` side declares, or refuse a spec that holds none.

    An empty argument is refused by its place in the list, counted from 1 for the program;
    the other arguments are not printed, as one of them may be a secret.
    """
    argv = side.spec.get("argv")
    if (
        isinstance(argv, str)
        or not isinstance(argv, Sequence)
        or not argv
        or not all(isinstance(arg, str) for arg in argv)
    ):
        raise Refusal("E_USAGE", f"side {side.name!r}: a cmd side is a non-empty list of arguments")
    for place, arg in enumerate(argv, start=1):
        if not arg:
            raise Refusal(
                "E_USAGE",
                f"side {side.name!r}: argument {place} of the command is empty; "
                "a cmd side is a list of non-empty arguments",
            )
    return tuple(argv)


@dataclass(frozen=True)
class CommandPlan:
    """Everything a ``cmd`` side needs before its identity is read.

    ``hashed`` is the command as its ``argv_sha256`` reads it
    (``pairbench.model.hashed_command``).
    """

    side: Side
    settings: LaunchSettings
    declared: tuple[str, ...]
    command: tuple[str, ...]
    executable: str
    environment: Mapping[str, str]
    cwd: str | None
    hashed: tuple[str, ...]


def plan_command(side: Side, ctx: api.SideContext) -> CommandPlan:
    """Check a ``cmd`` side and find what it starts, without running anything.

    The command is hashed with the shared workload read as every side of the
    run reads it (``api.SideContext.workload_hashed``).
    """
    declared = declared_argv(side)
    command = substitute_workload(side, declared, ctx.workload)
    refuse_host_settings(side, ctx.settings)
    cwd = resolve_workdir(side, ctx.settings)
    environment = host_environment(ctx.environ, ctx.settings)
    executable = find_executable(command[0], environment=environment, cwd=cwd)
    if executable is None:
        raise refuse_unfound(side, "executable", command[0])
    hashed = tuple(hashed_command(declared, ctx.workload, ctx.workload_hashed))
    return CommandPlan(side, ctx.settings, declared, command, executable, environment, cwd, hashed)


def command_identity(runner: CommandRunner, plan: CommandPlan, *, identify: bool) -> dict[str, Any]:
    """Read the identity of a ``cmd`` side: the one function ``look_up`` and ``resolve`` share.

    ``identify`` runs the configured ``identify`` command as well; a look-up
    never does.
    """
    identity: dict[str, Any] = {
        KEY_EXECUTABLE: plan.executable,
        KEY_EXECUTABLE_SHA256: side_file_sha256(
            plan.side.name, "executable", Path(plan.executable)
        ),
        KEY_ARGV_SHA256: hashed_sha256(plan.hashed),
    }
    if identify:
        identity.update(
            identify_on_host(
                runner, plan.side, plan.settings, environment=plan.environment, cwd=plan.cwd
            )
        )
    return identity


class CommandKind(KindBase):
    """The ``cmd`` side kind."""

    name = KIND_CMD

    def look_up(self, side: Side, ctx: api.SideContext) -> api.SideLookup:
        """Find the executable and hash it; run nothing."""
        plan = plan_command(side, ctx)
        identity = command_identity(self._runner, plan, identify=False)
        fingerprint = ""
        if not ctx.settings.identify:
            fingerprint = fingerprint_of(identity, ctx.settings.effective(args=plan.declared))
        return api.SideLookup(status="identified", identity=identity, fingerprint=fingerprint)

    def resolve(self, side: Side, ctx: api.SideContext) -> api.ResolvedSide:
        """Find the executable, run the identify command, record identity and fingerprint."""
        plan = plan_command(side, ctx)
        require_env_pass(side, ctx.settings, ctx.environ)
        runner = self._runner

        def read_identity() -> dict[str, Any]:
            return command_identity(runner, plan, identify=True)

        identity = read_identity()
        fingerprint = fingerprint_of(identity, ctx.settings.effective(args=plan.declared))
        return HostResolved(
            side=side.with_identity(identity, fingerprint),
            settings=ctx.settings,
            command=plan.command,
            executable=plan.executable,
            environment=plan.environment,
            cwd=plan.cwd,
            read_identity=read_identity,
            host=self._host,
        )
