# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The entry point of the ``pairbench`` command.

``main`` reads the arguments, runs one command and returns its exit code; it
never calls ``sys.exit`` and never prompts. A refusal prints its line
(``CODE: message``) on standard error and returns its exit code. An
interrupt returns 130 and any other error ``E_INTERNAL``, 8. A reader of
standard output or standard error that goes away early (``| head``) ends
nothing: the rest of that stream is dropped, the command finishes and
returns its own code, with no message (``pairbench.cli.pipes``). The modules of
the commands are imported only once their command is chosen, so
``pairbench --version`` loads none of them.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from types import FrameType
from typing import Any, Final, NoReturn

from pairbench.cli.pipes import quiet_when_closed
from pairbench.errors import EXIT_INTERNAL, EXIT_INTERRUPTED, EXIT_OK, Refusal, docs_line

PROGRAM: Final = "pairbench"
SEPARATOR: Final = "--"
# Flags whose value is the next argument even when it looks like the separator,
# as the recorded command line reads them (``model.redact_argv``).
VALUE_FLAGS_BEFORE_SEPARATOR: Final[tuple[str, ...]] = ("--side", "--set")

# Each command: the module that holds it and the line ``--help`` shows.
COMMANDS: Final[dict[str, tuple[str, str]]] = {
    "run": (
        "pairbench.cli.run",
        "plan, check the machine, measure, analyse and write the run folder",
    ),
    "plan": ("pairbench.cli.plan", "print the plan and exit; touches nothing"),
    "compare": (
        "pairbench.cli.compare",
        "analyse or pool existing captures, or compare result files from other tools",
    ),
    "report": ("pairbench.cli.report", "render a results file"),
    "fill": ("pairbench.cli.fill", "fill a document's figure tokens from results files"),
    "selftest": ("pairbench.cli.selftest", "run the known answers and the controls"),
    "doctor": (
        "pairbench.cli.doctor",
        "what this machine supports, which external tools are found, what is degraded",
    ),
    "schema": ("pairbench.cli.schema", "print a JSON Schema"),
    "gate": ("pairbench.cli.gate", "run one machine check on its own"),
    "profile": (
        "pairbench.cli.profile",
        "record a profile with a profiler you installed yourself",
    ),
    "mcp": ("pairbench.cli.mcp", "start the tool server for AI agents"),
    "skill": ("pairbench.cli.skill", "copy the agent skill into a folder"),
}
# Commands whose arguments after the separator are a command to run, not flags.
SPLIT_COMMANDS: Final[frozenset[str]] = frozenset({"run", "plan", "gate"})


class Done(Exception):
    """Raised by the parser where argparse would exit: after ``--help``."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class Parser(argparse.ArgumentParser):
    """An argument parser that refuses with ``E_USAGE`` instead of exiting."""

    def error(self, message: str) -> NoReturn:
        raise Refusal("E_USAGE", f"{self.prog}: {message}")

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            sys.stderr.write(message)
        raise Done(status)


def parser_for(name: str, description: str) -> Parser:
    """A parser of one command, with abbreviated flags turned off."""
    return Parser(
        prog=f"{PROGRAM} {name}",
        description=description,
        allow_abbrev=False,
    )


def split_separator(args: Sequence[str]) -> tuple[list[str], list[str] | None]:
    """Split arguments at the first ``--`` that is not the value of ``--side`` or ``--set``.

    Returns the arguments before it and those after it, or ``None`` when
    there is no separator.
    """
    before: list[str] = []
    waiting = False
    for at, arg in enumerate(args):
        if waiting:
            before.append(arg)
            waiting = False
        elif arg == SEPARATOR:
            return before, list(args[at + 1 :])
        else:
            before.append(arg)
            waiting = arg in VALUE_FLAGS_BEFORE_SEPARATOR
    return before, None


def version_text() -> str:
    """The line ``pairbench --version`` prints."""
    from pairbench.model import TOOL_VERSION

    return f"{PROGRAM} {TOOL_VERSION}"


def usage_text() -> str:
    """The text ``pairbench --help`` prints."""
    width = max(len(name) for name in COMMANDS)
    lines = [f"usage: {PROGRAM} COMMAND [ARGUMENTS]", "", "commands:"]
    lines += [f"  {name.ljust(width)}  {about}" for name, (_module, about) in COMMANDS.items()]
    lines += [
        "",
        f"{PROGRAM} COMMAND --help shows the arguments of one command.",
        f"{PROGRAM} --version prints the version.",
    ]
    return "\n".join(lines) + "\n"


def _dispatch(args: Sequence[str]) -> int:
    if not args:
        raise Refusal("E_USAGE", f"a command is needed; {PROGRAM} --help lists them")
    first = args[0]
    if first == "--version":
        if len(args) > 1:
            raise Refusal("E_USAGE", "--version takes no other argument")
        sys.stdout.write(version_text() + "\n")
        return EXIT_OK
    if first in ("--help", "-h"):
        sys.stdout.write(usage_text())
        return EXIT_OK
    if first not in COMMANDS:
        raise Refusal("E_USAGE", f"no command named {first!r}; {PROGRAM} --help lists them")
    module_name, about = COMMANDS[first]
    module = importlib.import_module(module_name)
    rest = list(args[1:])
    after: list[str] | None = None
    if first in SPLIT_COMMANDS:
        rest, after = split_separator(rest)
    parser = parser_for(first, about)
    module.add_arguments(parser)
    try:
        options = parser.parse_args(rest)
    except Done as done:
        return done.code
    options.after = after
    command: Callable[[argparse.Namespace], int] = module.command
    return command(options)


def _raise_interrupt(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt


# The signals that end a command as an interrupt does: a termination request,
# a hangup (the terminal or the remote session closed) and a quit request,
# each where the platform has it. A launch runs in a session of its own and
# never sees them, so the tool tears it down and writes the end record. A
# signal the tool was started with ignored stays ignored: ``nohup`` ignores
# the hangup so that a run outlives its terminal.
ENDING_SIGNALS: tuple[str, ...] = ("SIGTERM", "SIGHUP", "SIGQUIT")


def _catch_terminate() -> dict[int, Any]:
    """Treat an ending signal as an interrupt while a command runs in the main thread.

    A signal that is ignored is left ignored. Returns the handler each caught
    signal had before, to give back afterwards.
    """
    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: dict[int, Any] = {}
    for name in ENDING_SIGNALS:
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            if signal.getsignal(number) is signal.SIG_IGN:
                continue
            previous[number] = signal.signal(number, _raise_interrupt)
        except (ValueError, OSError):
            continue
    return previous


def _restore_terminate(previous: dict[int, Any]) -> None:
    for number, handler in previous.items():
        if handler is None:
            continue
        with contextlib.suppress(ValueError, OSError, TypeError):
            signal.signal(number, handler)


def _print_error(refusal: Refusal) -> None:
    """Print a refusal's line and the address of its entry in the documentation."""
    from pairbench.model import TOOL_VERSION

    with contextlib.suppress(OSError, ValueError):
        print(refusal.line, file=sys.stderr)
        print(docs_line(refusal.code, TOOL_VERSION), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one ``pairbench`` command and return its exit code (``api.CliMain``)."""
    args = list(sys.argv[1:] if argv is None else argv)
    from pairbench import api, registry

    enabled = registry.plugins_enabled()
    previous = _catch_terminate()
    try:
        with quiet_when_closed():
            try:
                with api.command_line([PROGRAM, *args]):
                    return _dispatch(args)
            except Refusal as refusal:
                _print_error(refusal)
                return refusal.exit_code
            except KeyboardInterrupt:
                _print_error(Refusal("E_INTERRUPTED", "interrupted"))
                return EXIT_INTERRUPTED
            except Exception as exc:
                _print_error(Refusal("E_INTERNAL", f"{type(exc).__name__}: {exc}"))
                return EXIT_INTERNAL
    finally:
        registry.set_plugins_enabled(enabled)
        _restore_terminate(previous)


__all__ = ["COMMANDS", "Done", "Parser", "main", "parser_for", "split_separator", "version_text"]
