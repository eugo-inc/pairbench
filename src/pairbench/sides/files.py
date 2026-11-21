# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``file`` side kind: result files another tool wrote, one per round.

A file side launches nothing. Its paths may be globs (``**`` matches folders
at any depth); the files they match are sorted by file name, the full path
breaking a tie, and round ``r`` reads the ``r``-th of them, counted from 1.
The identity records the hash of every file in that order and, in the capture
only, the paths.
"""

from __future__ import annotations

import glob
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import KIND_FILE, LaunchSettings, Side, fingerprint_of
from pairbench.sides.base import KindBase
from pairbench.sides.identity import KEY_FILES, KEY_FILES_SHA256, side_file_sha256

# Launch settings that choose how an image is found. They have nothing to
# honour on a file side and are not refused there.
NOT_LAUNCH_SETTINGS: Final[tuple[str, ...]] = ("engine", "pull")

CANNOT_REPEAT: Final = "a file side launches nothing, so it has no positive control"


def refuse_file_settings(side: Side, settings: LaunchSettings) -> None:
    """Refuse every launch setting a file side would have to honour by launching.

    Every overridable setting that differs from its default is refused with
    ``E_ENGINE_UNSUPPORTED``, apart from ``engine`` and ``pull``.
    """
    plain = LaunchSettings()
    for key in LaunchSettings.OVERRIDABLE:
        if key in NOT_LAUNCH_SETTINGS:
            continue
        if getattr(settings, key) != getattr(plain, key):
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {side.name!r}: a file side launches nothing and cannot honour the "
                f"launch setting {key}",
            )


def matched_files(side: Side) -> list[Path]:
    """Return the files a file side names, sorted by file name; refuse when there are none."""
    paths = side.spec.get("paths")
    if isinstance(paths, str) or not isinstance(paths, Sequence) or not paths:
        raise Refusal("E_USAGE", f"side {side.name!r}: a file side names one or more paths")
    found: dict[str, Path] = {}
    for pattern in paths:
        if not isinstance(pattern, str) or not pattern:
            raise Refusal("E_USAGE", f"side {side.name!r}: a path of a file side is a text")
        for match in glob.glob(os.path.expanduser(pattern), recursive=True):
            path = Path(os.path.abspath(match))
            if path.is_file():
                found.setdefault(str(path), path)
    if not found:
        raise Refusal(
            "E_SIDE_UNRESOLVED",
            f"side {side.name!r}: no result file matches its paths",
            detail={"paths": list(paths)},
        )
    return sorted(found.values(), key=lambda path: (path.name, str(path)))


def files_identity(side: str, files: Sequence[Path]) -> dict[str, Any]:
    """Read the identity of a file side: the one function both look-up and resolve use."""
    return {
        KEY_FILES: tuple(str(path) for path in files),
        KEY_FILES_SHA256: tuple(side_file_sha256(side, "result file", path) for path in files),
    }


class FileResolved:
    """A resolved file side: round ``r`` gives the ``r``-th file."""

    def __init__(self, side: Side, files: Sequence[Path]) -> None:
        self._side = side
        self._files = tuple(files)

    @property
    def side(self) -> Side:
        return self._side

    @property
    def command(self) -> tuple[str, ...] | None:
        return None

    @property
    def engine(self) -> None:
        return None

    @property
    def rounds_available(self) -> int | None:
        return len(self._files)

    @property
    def cannot_repeat(self) -> str | None:
        return CANNOT_REPEAT

    def identify(self) -> Mapping[str, Any]:
        return files_identity(self._side.name, self._files)

    def artifacts_in_side(self, host: Path) -> str:
        return str(host)

    def tool_file_in_side(self, host: Path) -> str:
        return str(host)

    def launch(self, request: api.LaunchRequest) -> api.LaunchOutcome:
        """Return the file of the round. Nothing is started."""
        if not 1 <= request.round <= len(self._files):
            raise Refusal(
                "E_USAGE",
                f"side {self._side.name!r} holds {len(self._files)} result files; "
                f"there is no round {request.round}",
            )
        return api.LaunchOutcome(rc=0, result_file=self._files[request.round - 1])

    def close(self) -> None:
        return None


class FileKind(KindBase):
    """The ``file`` side kind."""

    name = KIND_FILE

    def look_up(self, side: Side, ctx: api.SideContext) -> api.SideLookup:
        """Find and hash the files; change nothing."""
        refuse_file_settings(side, ctx.settings)
        identity = files_identity(side.name, matched_files(side))
        fingerprint = ""
        if not ctx.settings.identify:
            fingerprint = fingerprint_of(identity, ctx.settings.effective())
        return api.SideLookup(status="identified", identity=identity, fingerprint=fingerprint)

    def resolve(self, side: Side, ctx: api.SideContext) -> api.ResolvedSide:
        """Find the files and record their hashes in file order."""
        refuse_file_settings(side, ctx.settings)
        files = matched_files(side)
        identity = files_identity(side.name, files)
        fingerprint = fingerprint_of(identity, ctx.settings.effective())
        return FileResolved(side.with_identity(identity, fingerprint), files)
