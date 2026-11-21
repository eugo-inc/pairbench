# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The tool-server library, the ``mcp`` package of the ``mcp`` extra, as an error shows it.

The tool server is built on the official MCP Python SDK. This module imports
nothing of it. It says which module names are the library's own, and turns an
error met while the library loads, an import error or any other, into a
refusal that says what to do: install the extra, reinstall a broken or
too-old install, or move a local module named ``mcp`` out of the way. A
refusal names modules and a release, never a path: the text of an error
often holds the path of a file.
"""

from __future__ import annotations

import importlib.machinery
import importlib.metadata
import importlib.util
import re
from pathlib import Path
from typing import Final

from pairbench.errors import Refusal

PACKAGE: Final = "mcp"
# The releases the server reads, as the ``mcp`` extra bounds them: this one or newer,
# and older than the second.
LOWEST: Final[tuple[int, ...]] = (1, 21, 1)
BELOW: Final[tuple[int, ...]] = (3,)
SUPPORTED: Final = f"{PACKAGE}>={'.'.join(map(str, LOWEST))},<{'.'.join(map(str, BELOW))}"
# The server packages of the two layouts the server reads, inside ``mcp/server/``.
LAYOUTS: Final[tuple[str, ...]] = ("mcpserver", "fastmcp")

NOT_INSTALLED: Final = "the tool server is not available here (mcp): install pairbench[mcp]"
REINSTALL: Final = "reinstall it with pip install 'pairbench[mcp]'"
SHADOWED: Final = (
    "a local module named mcp ({file}) shadows the tool-server library: rename it, or start "
    "pairbench from another folder"
)

MODULE_NAME: Final = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
RELEASE: Final = re.compile(r"[0-9][0-9A-Za-z.+!_-]*", re.ASCII)
NUMBERS: Final = re.compile(r"\d+(?:\.\d+)*", re.ASCII)

# What ``found`` answers when no module named ``mcp`` can be found, and when the one
# found is the library's.
ABSENT: Final = "absent"
LIBRARY: Final = "library"


def in_library(name: str | None) -> bool:
    """Whether a module name is the library's own: ``mcp`` or a module inside it.

    The rule is the name's first dotted part: ``mcp_types``, ``mcpx`` and every
    other name are outside the library, even those that start with its letters.
    """
    return (name or "").partition(".")[0] == PACKAGE


def release() -> str | None:
    """The installed release of the library, as its metadata gives it, or ``None``."""
    try:
        version = importlib.metadata.version(PACKAGE)
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        return None
    if not isinstance(version, str) or not RELEASE.fullmatch(version):
        return None
    return version


def supported(version: str) -> bool:
    """Whether a release lies inside the bounds of the extra; one without a number counts as in."""
    numbers = NUMBERS.match(version)
    if numbers is None:
        return True
    parts = tuple(int(part) for part in numbers.group().split("."))
    return LOWEST <= parts < BELOW


def _library_file() -> Path | None:
    """The ``mcp/__init__.py`` the installed library's metadata places, when it is there."""
    try:
        distribution = importlib.metadata.distribution(PACKAGE)
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        return None
    located = Path(str(distribution.locate_file(f"{PACKAGE}/__init__.py")))
    return located if located.is_file() else None


def _same_file(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except OSError:
        return False


def _spec() -> importlib.machinery.ModuleSpec | None:
    """The spec of what the import system finds under the name ``mcp``; it imports nothing."""
    return importlib.util.find_spec(PACKAGE)


def found() -> str | None:
    """What the import system finds under the name ``mcp``, without importing it.

    ``ABSENT`` when nothing is found, or only a folder without an init file,
    which an installed library would take the place of; ``LIBRARY`` when it is
    the installed library; the file name of a local module that takes the
    library's place, ``mcp.py`` or ``mcp/__init__.py``; and ``None`` when it
    cannot be told. A module found is the library when it is the file the
    library's metadata places or, without such metadata, when its folder holds
    a server package of a layout the server reads.
    """
    try:
        spec = _spec()
    except (ImportError, ValueError):
        return None
    if spec is None:
        return ABSENT
    locations = list(spec.submodule_search_locations or ())
    origin = Path(spec.origin) if spec.origin and spec.has_location else None
    if origin is None:
        return ABSENT if locations else None
    library = _library_file()
    if library is not None:
        if _same_file(origin, library):
            return LIBRARY
    elif any(
        (Path(folder) / "server" / layout).exists() for folder in locations for layout in LAYOUTS
    ):
        return LIBRARY
    return f"{PACKAGE}/{origin.name}" if locations else origin.name


def refusal(error: Exception) -> Refusal:
    """The refusal for an error met while the library loads.

    A module ``mcp`` that is not found, or nothing found under that name,
    means the extra is not installed. Otherwise a local module that takes the
    library's place is named by its file name, even when its own error names
    ``mcp``, as a name it imports from ``mcp`` does; and any other error is a
    broken install, named with the module it cannot import when it is an
    import error, the release when the metadata gives it, the bounds of the
    extra when the release lies outside them, and the hint to reinstall. The
    text of the error is never shown.
    """
    # Only an import error names a module: the name of an attribute error is an attribute.
    name = error.name if isinstance(error, ImportError) else None
    if name == PACKAGE and isinstance(error, ModuleNotFoundError):
        return Refusal("E_USAGE", NOT_INSTALLED)
    place = found()
    if place == ABSENT:
        return Refusal("E_USAGE", NOT_INSTALLED)
    if place is not None and place != LIBRARY:
        return Refusal("E_USAGE", SHADOWED.format(file=place))
    version = release()
    library = f"{PACKAGE} {version}" if version else PACKAGE
    cannot = (
        f"it cannot import {name}"
        if name and MODULE_NAME.fullmatch(name)
        else "one of its modules cannot be imported"
    )
    outside = f", and pairbench supports {SUPPORTED}" if version and not supported(version) else ""
    return Refusal(
        "E_USAGE",
        f"the tool-server library {library} is a broken install: {cannot}{outside}; {REINSTALL}",
    )


__all__ = [
    "ABSENT",
    "LIBRARY",
    "NOT_INSTALLED",
    "PACKAGE",
    "SUPPORTED",
    "found",
    "in_library",
    "refusal",
    "release",
    "supported",
]
