# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The stack sampler of the ``pystacks`` instrument: one self-contained file.

It runs on the interpreter of a side, which may be as old as Python 3.8, and
imports only the standard library. pairbench hands this file to the side
(mounted read-only into a container) and the explain launch runs::

    python [interpreter options] pysampler.py --out DIR --hz N -- PROGRAM

where ``PROGRAM`` is a script and its arguments, ``-m MODULE`` and its
arguments, or ``-c CODE`` and its arguments, as the interpreter would take
them. The workload runs as the main program of the interpreter. A thread
reads the interpreter's own frames (``sys._current_frames``) ``N`` times per
second and counts the stack of every other thread. A frame is named
``function (file)``, with the last part of the file's path. The frames of
the sampler and of ``runpy`` are left out, so a stack starts at the
workload's own outermost frame. What native code does shows as time in the
Python function that called it. The sampler measures wall-clock time: a
thread that waits is sampled where it waits.

When the workload ends, the sampler writes ``pystacks.folded`` into ``DIR``:
one line per distinct stack, frames from the outermost to the innermost
joined by ``;``, a space, the number of samples; lines sorted. It writes it
also when the workload raises or exits with a code of its own, and then exits
with the workload's code. On an interpreter older than Python 3.8 it runs
nothing, writes ``pystacks-too-old.txt`` into ``DIR`` and exits with the code
``EXIT_TOO_OLD``. Both files are readable and writable by their owner only,
whatever the umask.

The file keeps a syntax that old interpreters can read, so it can report
that it is too old rather than fail to parse: no f-strings, no annotations
(the types are given in type comments) and no unpacking in list displays.
"""

import os
import runpy
import sys
import threading
import time
import traceback
import types

# The type checker reads these names in the type comments; the linter does not.
TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import IO, Any, Dict, List, Optional, Tuple  # noqa: F401

EXIT_TOO_OLD = 86
EXIT_USAGE = 2
MIN_PYTHON = (3, 8)
FOLDED_OUTPUT = "pystacks.folded"
TOO_OLD_OUTPUT = "pystacks-too-old.txt"
# The mode of the files the sampler writes: readable and writable by their owner only.
PRIVATE_MODE = 0o600


def open_private(path, mode):
    # type: (str, str) -> IO[Any]
    """Open ``path`` for writing, emptied, readable and writable by its owner only.

    The file is created with that mode and set to it after opening, whatever
    the umask and whether it existed. ``mode`` is ``"w"`` or ``"wb"``.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_MODE)
    try:
        change = getattr(os, "fchmod", None)
        if change is not None:
            # contextlib.suppress is missing on the oldest interpreters this file reports on.
            try:  # noqa: SIM105
                change(descriptor, PRIVATE_MODE)
            except OSError:
                pass
        return os.fdopen(descriptor, mode)
    except BaseException:
        os.close(descriptor)
        raise


def usage(message):
    # type: (str) -> int
    sys.stderr.write("pysampler: %s\n" % message)
    sys.stderr.write("usage: python pysampler.py --out DIR --hz N -- PROGRAM\n")
    return EXIT_USAGE


def parse(argv):
    # type: (List[str]) -> Tuple[Optional[str], int, List[str]]
    """Return (out, hz, program) from the arguments, or raise ValueError."""
    out = None  # type: Optional[str]
    hz = 99
    index = 0
    while index < len(argv):
        word = argv[index]
        if word == "--":
            return out, hz, list(argv[index + 1 :])
        if word in ("--out", "--hz") and index + 1 < len(argv):
            if word == "--out":
                out = argv[index + 1]
            else:
                hz = int(argv[index + 1])
            index += 2
            continue
        raise ValueError("unknown argument %r" % word)
    raise ValueError("no program after --")


def frame_name(code):
    # type: (types.CodeType) -> str
    """Return the name of a frame: the function and the last part of its file."""
    name = "%s (%s)" % (code.co_name, os.path.basename(code.co_filename))
    for bad in (";", "\n", "\r", "\t"):
        name = name.replace(bad, ":" if bad == ";" else " ")
    return name


class Sampler(object):
    """Counts the stacks of every thread but its own, ``hz`` times per second.

    A stack starts at the workload's outermost frame. Walking out from the
    innermost frame, the walk stops at the first frame of ``runpy`` or of
    this file. The stack counts only when the walk entered the workload
    there: through ``run_program`` or ``runpy``, at the module level of the
    program. Anything else is the work of the sampler or of ``runpy``, such
    as starting the thread or finding the program, and is not counted. The
    stack of a thread the workload started counts as it is.
    """

    def __init__(self, hz):
        # type: (int) -> None
        self.interval = 1.0 / max(1, hz)
        self.counts = {}  # type: Dict[str, int]
        self.go = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="pairbench-pystacks")
        self.thread.daemon = True

    def stack(self, frame):
        # type: (Optional[types.FrameType]) -> List[str]
        names = []  # type: List[str]
        outermost = None  # type: Optional[types.CodeType]
        while frame is not None:
            if frame.f_globals is _GLOBALS or frame.f_globals.get("__name__") == "runpy":
                entered = frame.f_globals is not _GLOBALS or frame.f_code is run_program.__code__
                if entered and outermost is not None and outermost.co_name == "<module>":
                    return names
                return []
            names.append(frame_name(frame.f_code))
            outermost = frame.f_code
            frame = frame.f_back
        return names

    def take(self, own):
        # type: (Optional[int]) -> None
        for ident, frame in sys._current_frames().items():
            if ident == own:
                continue
            names = self.stack(frame)
            if not names:
                continue
            names.reverse()
            key = ";".join(names)
            self.counts[key] = self.counts.get(key, 0) + 1

    def loop(self):
        # type: () -> None
        own = threading.current_thread().ident
        self.go.wait()
        due = time.monotonic()
        while not self.stop.is_set():
            self.take(own)
            due += self.interval
            self.stop.wait(max(0.0, due - time.monotonic()))

    def start(self):
        # type: () -> None
        self.thread.start()

    def finish(self):
        # type: () -> None
        self.go.set()
        self.stop.set()
        self.thread.join(5.0)

    def write(self, path):
        # type: (str) -> None
        lines = ["%s %d\n" % (stack, count) for stack, count in sorted(self.counts.items())]
        text = "".join(lines)
        # UTF-8 whatever the locale; a name that came in through the locale's
        # escape goes back out as the bytes it came from.
        try:
            data = text.encode("utf-8", "surrogateescape")
        except UnicodeEncodeError:
            data = text.encode("utf-8", "replace")
        partial = path + ".partial"
        with open_private(partial, "wb") as handle:
            handle.write(data)
        os.replace(partial, path)


def plan_program(program):
    # type: (List[str]) -> Tuple[str, str, List[str], str]
    """Return how to run the workload: (kind, target, arguments, folder), or raise ValueError.

    ``kind`` is ``module`` for ``-m MODULE``, ``code`` for ``-c CODE`` and
    ``path`` for a script. The value of ``-m`` and ``-c`` may be attached.
    ``folder`` is the first entry of the module search path: the script's
    folder, or an empty text for the current folder. Everything is worked
    out here, before sampling starts, so no sample falls on it.
    """
    if not program:
        raise ValueError("no program after --")
    first = program[0]
    for flag, kind in (("-m", "module"), ("-c", "code")):
        if first.startswith(flag):
            if first[2:]:
                return kind, first[2:], list(program[1:]), ""
            if len(program) < 2:
                raise ValueError("%s needs a value" % flag)
            return kind, program[1], list(program[2:]), ""
    return "path", first, list(program[1:]), os.path.dirname(os.path.abspath(first))


def run_program(kind, target, rest, folder):
    # type: (str, str, List[str], str) -> None
    """Run the workload as the main program of the interpreter."""
    sys.path[0] = folder
    sys.argv = ["-c" if kind == "code" else target]
    sys.argv.extend(rest)
    if kind == "module":
        runpy.run_module(target, run_name="__main__", alter_sys=True)
    elif kind == "code":
        main = types.ModuleType("__main__")
        sys.modules["__main__"] = main
        exec(compile(target, "<string>", "exec"), main.__dict__)
    else:
        runpy.run_path(target, run_name="__main__")


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    argv = sys.argv[1:] if argv is None else argv
    try:
        out, hz, program = parse(argv)
    except ValueError as error:
        return usage(str(error))
    if out is None:
        return usage("--out is required")
    if tuple(sys.version_info[:2]) < MIN_PYTHON:
        message = "the sampler needs Python %d.%d or newer; this interpreter is %d.%d\n" % (
            MIN_PYTHON[0],
            MIN_PYTHON[1],
            sys.version_info[0],
            sys.version_info[1],
        )
        sys.stderr.write("pysampler: " + message)
        with open_private(os.path.join(out, TOO_OLD_OUTPUT), "w") as handle:
            handle.write(message)
        return EXIT_TOO_OLD
    try:
        kind, target, rest, folder = plan_program(program)
    except ValueError as error:
        return usage(str(error))

    sampler = Sampler(hz)
    code = 0
    sampler.start()
    try:
        sampler.go.set()
        run_program(kind, target, rest, folder)
    except SystemExit as stop:
        if stop.code is None:
            code = 0
        elif isinstance(stop.code, int):
            code = stop.code
        else:
            sys.stderr.write("%s\n" % (stop.code,))
            code = 1
    except BaseException:
        traceback.print_exc()
        code = 1
    finally:
        sampler.finish()
        sampler.write(os.path.join(out, FOLDED_OUTPUT))
    return code


_GLOBALS = globals()

if __name__ == "__main__":
    sys.exit(main())
