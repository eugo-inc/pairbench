# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench mcp`` in a process of its own, with a made-up install of the tool-server library.

Each row writes a small stand-in of the ``mcp`` package, with its metadata, into
a folder that comes first on the import path, and starts ``python -m pairbench
mcp`` from a working folder of its own. A broken or too-old install is named as
such with the reinstall hint, a local module named ``mcp`` is named as the one
that shadows the library, and no path or home folder reaches either stream.
Nothing here needs the ``mcp`` extra.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

WAIT_S = 60.0
EXIT_OK = 0
EXIT_USAGE = 2
DOCS_LINE = "pairbench: see https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_usage\n"
REINSTALL = "reinstall it with pip install 'pairbench[mcp]'"

PACKAGE = {"mcp/__init__.py": "", "mcp/server/__init__.py": ""}


def missing(module: str) -> str:
    """The text of a module that fails as an import of a module that is not installed does."""
    return f"raise ModuleNotFoundError({f'No module named {module!r}'!r}, name={module!r})\n"


# A server class of the newer layout that registers nothing and serves nothing.
WORKING_SERVER = """\
class MCPServer:
    def __init__(self, name, instructions=None):
        self.name = name

    def add_tool(self, fn, name=None, description=None, structured_output=None):
        pass

    async def list_tools(self):
        return []

    def run(self, transport="stdio"):
        pass
"""

# The text of a module that fails as a library built for an older pydantic does: the
# import error names a module and carries the path of its file, under {lib}.
WRONG_PYDANTIC = """\
raise ImportError(
    "cannot import name 'made_up_name' from 'pydantic._internal._typing_extra' "
    "({lib}/pydantic/_internal/_typing_extra.py)",
    name="pydantic._internal._typing_extra",
    path="{lib}/pydantic/_internal/_typing_extra.py",
)
"""

# Each row: the release in the metadata, the files of the library, and the line the
# command prints before its documentation line.
BROKEN = {
    "newer-layout-without-mcp-types": (
        "2.3.0",
        {**PACKAGE, "mcp/server/mcpserver/__init__.py": missing("mcp_types")},
        "E_USAGE: the tool-server library mcp 2.3.0 is a broken install: it cannot import "
        f"mcp_types; {REINSTALL}",
    ),
    "newer-layout-without-starlette": (
        "2.3.0",
        {**PACKAGE, "mcp/server/mcpserver/__init__.py": missing("starlette")},
        "E_USAGE: the tool-server library mcp 2.3.0 is a broken install: it cannot import "
        f"starlette; {REINSTALL}",
    ),
    "older-layout-without-pydantic-settings": (
        "1.21.1",
        {
            "mcp/__init__.py": "",
            "mcp/server/__init__.py": "from .fastmcp import FastMCP\n",
            "mcp/server/fastmcp/__init__.py": missing("pydantic_settings"),
        },
        "E_USAGE: the tool-server library mcp 1.21.1 is a broken install: it cannot import "
        f"pydantic_settings; {REINSTALL}",
    ),
    "older-layout-without-starlette": (
        "1.21.1",
        {**PACKAGE, "mcp/server/fastmcp/__init__.py": missing("starlette")},
        "E_USAGE: the tool-server library mcp 1.21.1 is a broken install: it cannot import "
        f"starlette; {REINSTALL}",
    ),
    "too-old-for-the-installed-pydantic": (
        "1.20.0",
        {"mcp/__init__.py": "", "mcp/server/__init__.py": WRONG_PYDANTIC},
        "E_USAGE: the tool-server library mcp 1.20.0 is a broken install: it cannot import "
        "pydantic._internal._typing_extra, and pairbench supports mcp>=1.21.1,<3; "
        f"{REINSTALL}",
    ),
    "too-old-and-failing-with-another-error": (
        "1.20.0",
        {
            **PACKAGE,
            "mcp/server/mcpserver/__init__.py": (
                'raise TypeError("a made-up failure in {lib}/mcp/server/mcpserver/__init__.py")\n'
            ),
        },
        "E_USAGE: the tool-server library mcp 1.20.0 is a broken install: one of its modules "
        f"cannot be imported, and pairbench supports mcp>=1.21.1,<3; {REINSTALL}",
    ),
    "too-old-to-hold-either-layout": (
        "1.2.0",
        PACKAGE,
        "E_USAGE: the tool-server library mcp 1.2.0 is a broken install: it cannot import "
        f"mcp.server.mcpserver, and pairbench supports mcp>=1.21.1,<3; {REINSTALL}",
    ),
    "newer-layout-that-cannot-import-a-name-from-mcp": (
        "2.3.0",
        {**PACKAGE, "mcp/server/mcpserver/__init__.py": "from mcp import MadeUpSession\n"},
        "E_USAGE: the tool-server library mcp 2.3.0 is a broken install: it cannot import "
        f"mcp; {REINSTALL}",
    ),
}

# Each row: the files of a local module named mcp in the working folder, and the line.
SHADOWS = {
    "module": (
        {"mcp.py": "MADE_UP_VALUE = 1\n"},
        "E_USAGE: a local module named mcp (mcp.py) shadows the tool-server library: rename "
        "it, or start pairbench from another folder",
    ),
    "package": (
        {"mcp/__init__.py": ""},
        "E_USAGE: a local module named mcp (mcp/__init__.py) shadows the tool-server "
        "library: rename it, or start pairbench from another folder",
    ),
    "module-that-imports-a-name-from-mcp": (
        {"mcp.py": "from mcp import MadeUpSession\n"},
        "E_USAGE: a local module named mcp (mcp.py) shadows the tool-server library: rename "
        "it, or start pairbench from another folder",
    ),
    "package-that-imports-a-name-from-mcp": (
        {"mcp/__init__.py": "from mcp import MadeUpSession\n"},
        "E_USAGE: a local module named mcp (mcp/__init__.py) shadows the tool-server "
        "library: rename it, or start pairbench from another folder",
    ),
}


def write(root: Path, files: dict[str, str], lib: Path) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("{lib}", str(lib)), encoding="utf-8")


def install(home: Path, release: str, files: dict[str, str]) -> Path:
    """Write a made-up install of the library under ``home``, with its metadata."""
    lib = home / "made-up-env" / "site-packages"
    write(lib, files, lib)
    metadata = f"Metadata-Version: 2.1\nName: mcp\nVersion: {release}\n"
    write(lib, {f"mcp-{release}.dist-info/METADATA": metadata}, lib)
    return lib


def start(repo_root: Path, home: Path, lib: Path, work: Path) -> subprocess.CompletedProcess[str]:
    """``python -m pairbench mcp`` from ``work``, with ``lib`` first on the import path."""
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": os.pathsep.join([str(lib), str(repo_root / "src")]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "pairbench", "mcp"],
        cwd=work,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=WAIT_S,
        check=False,
    )


def assert_no_path(done: subprocess.CompletedProcess[str], *folders: Path) -> None:
    for folder in folders:
        assert str(folder) not in done.stdout
        assert str(folder) not in done.stderr
    assert "site-packages" not in done.stderr


@pytest.mark.parametrize("row", sorted(BROKEN))
def test_a_broken_or_too_old_install_is_named_with_the_reinstall_hint(
    row: str, repo_root: Path, tmp_path: Path
) -> None:
    release, files, line = BROKEN[row]
    home = tmp_path / "home-a"
    lib = install(home, release, files)
    work = home / "work"
    work.mkdir()

    done = start(repo_root, home, lib, work)

    assert (done.returncode, done.stdout, done.stderr) == (EXIT_USAGE, "", line + "\n" + DOCS_LINE)
    assert_no_path(done, tmp_path, home, lib)


@pytest.mark.parametrize("row", sorted(SHADOWS))
def test_a_local_module_named_mcp_is_named_as_the_one_that_shadows_the_library(
    row: str, repo_root: Path, tmp_path: Path
) -> None:
    files, line = SHADOWS[row]
    home = tmp_path / "home-a"
    lib = install(home, "2.3.0", {**PACKAGE, "mcp/server/mcpserver/__init__.py": WORKING_SERVER})
    work = home / "work"
    write(work, files, lib)

    done = start(repo_root, home, lib, work)

    assert (done.returncode, done.stdout, done.stderr) == (EXIT_USAGE, "", line + "\n" + DOCS_LINE)
    assert_no_path(done, tmp_path, home, lib, work)


def test_a_local_folder_named_mcp_without_an_init_file_does_not_shadow_the_library(
    repo_root: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home-a"
    lib = install(home, "2.3.0", {**PACKAGE, "mcp/server/mcpserver/__init__.py": WORKING_SERVER})
    work = home / "work"
    (work / "mcp").mkdir(parents=True)

    done = start(repo_root, home, lib, work)

    assert (done.returncode, done.stdout, done.stderr) == (EXIT_OK, "", "")
