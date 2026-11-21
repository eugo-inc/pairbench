# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Standard output and standard error that go quiet when their reader has gone.

A reader that stops early, as ``pairbench report results.json | head`` does,
closes its end of the pipe, and the next write to it fails with
``BrokenPipeError``. A terminal that closes makes the next write to it fail
with an I/O error (``EIO``). While a command runs, its two output streams
are wrapped: the first such failure sends the rest of that stream to the
null device and every later write is dropped, so the command goes on to its
end, writes its files and returns its own exit code, with no message.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from collections.abc import Iterator
from typing import Any, TextIO


def reader_gone(exc: OSError, *, terminal: bool) -> bool:
    """Say whether a failed write means the reader of the stream has gone.

    A closed pipe always does. An I/O error (``EIO``) does on a stream that
    was a terminal: the terminal has closed. On a file it is a real failure.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    return terminal and exc.errno == errno.EIO


def _is_terminal(stream: Any) -> bool:
    """Say whether the stream is a terminal, ``False`` when that cannot be told."""
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def discard(stream: TextIO) -> None:
    """Point the descriptor of the interpreter's own output stream at the null device.

    Only ``sys.__stdout__`` and ``sys.__stderr__`` are touched: what they still
    hold is then flushed to the null device at exit instead of failing there.
    Any other stream, such as one a test put in place, keeps its descriptor.
    """
    if stream is not sys.__stdout__ and stream is not sys.__stderr__:
        return
    with contextlib.suppress(OSError, ValueError):
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, stream.fileno())
        finally:
            os.close(null)


class QuietWhenClosed:
    """A text stream that writes through to another until its reader has gone.

    The reader has gone when a write fails as on a closed pipe, or with an
    I/O error on a stream that was a terminal when it was wrapped; any other
    failure is raised.
    """

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.gone = False
        self.terminal = _is_terminal(stream)

    def _close(self) -> None:
        self.gone = True
        discard(self.stream)

    def write(self, text: str) -> int:
        if not self.gone:
            try:
                return self.stream.write(text)
            except OSError as exc:
                if not reader_gone(exc, terminal=self.terminal):
                    raise
                self._close()
        return len(text)

    def flush(self) -> None:
        if not self.gone:
            try:
                self.stream.flush()
            except OSError as exc:
                if not reader_gone(exc, terminal=self.terminal):
                    raise
                self._close()

    def write_bytes(self, data: bytes) -> None:
        """Write bytes as they are, through the binary buffer when the stream has one."""
        if self.gone:
            return
        try:
            self.stream.flush()
            binary = getattr(self.stream, "buffer", None)
            if binary is not None:
                binary.write(data)
                binary.flush()
            else:
                self.stream.write(data.decode("utf-8"))
                self.stream.flush()
        except OSError as exc:
            if not reader_gone(exc, terminal=self.terminal):
                raise
            self._close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


def write_bytes(data: bytes) -> None:
    """Write bytes to standard output as they are, quietly once its reader has gone."""
    out: Any = sys.stdout
    if not isinstance(out, QuietWhenClosed):
        out = QuietWhenClosed(out)
    out.write_bytes(data)


@contextlib.contextmanager
def quiet_when_closed() -> Iterator[None]:
    """Wrap standard output and standard error for the time of one command.

    Both are flushed before the streams that were in place come back, so
    nothing is left to fail at exit.
    """
    out, err = sys.stdout, sys.stderr
    quiet_out, quiet_err = QuietWhenClosed(out), QuietWhenClosed(err)
    sys.stdout = quiet_out
    sys.stderr = quiet_err
    try:
        yield
    finally:
        for stream in (quiet_out, quiet_err):
            with contextlib.suppress(OSError, ValueError):
                stream.flush()
        sys.stdout, sys.stderr = out, err


__all__ = ["QuietWhenClosed", "discard", "quiet_when_closed", "reader_gone", "write_bytes"]
