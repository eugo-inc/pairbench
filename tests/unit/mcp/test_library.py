# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Which modules are the tool-server library's, and the refusal for one that cannot be loaded.

The release and the place of the module named ``mcp`` are made up here, so the
answers do not depend on what is installed; ``test_install.py`` starts the
command with a made-up install on disk.
"""

from __future__ import annotations

import importlib.machinery
import importlib.metadata
import tomllib
from pathlib import Path

import pytest

from pairbench.errors import Refusal
from pairbench.mcp import library

EXIT_USAGE = 2
NOT_INSTALLED = "the tool server is not available here (mcp): install pairbench[mcp]"
REINSTALL = "reinstall it with pip install 'pairbench[mcp]'"
MADE_UP_RELEASE = "2.3.0"


@pytest.mark.parametrize(
    ("name", "inside"),
    [
        ("mcp", True),
        ("mcp.server", True),
        ("mcp.server.mcpserver", True),
        ("mcp.server.fastmcp.server", True),
        ("mcp_types", False),
        ("mcpx", False),
        ("mcpx.server", False),
        ("starlette", False),
        ("made_up_dependency_a", False),
        ("", False),
        (None, False),
    ],
)
def test_a_module_is_the_librarys_own_by_its_first_dotted_part(
    name: str | None, inside: bool
) -> None:
    assert library.in_library(name) is inside


def test_the_supported_releases_are_the_bounds_of_the_mcp_extra(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["optional-dependencies"]["mcp"] == [library.SUPPORTED]
    assert library.SUPPORTED == "mcp>=1.21.1,<3"


@pytest.mark.parametrize(
    ("version", "inside"),
    [
        ("1.20.0", False),
        ("1.21.0", False),
        ("1.21", False),
        ("1.21.1", True),
        ("1.30.2", True),
        ("2.0.0rc1", True),
        ("2.3.0", True),
        ("3.0.0", False),
        ("3", False),
        ("0.9.0", False),
        ("made-up", True),
    ],
)
def test_a_release_is_supported_inside_the_bounds_of_the_extra(version: str, inside: bool) -> None:
    assert library.supported(version) is inside


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module named ``mcp`` is the installed library, of a made-up supported release."""
    monkeypatch.setattr(library, "found", lambda: library.LIBRARY)
    monkeypatch.setattr(library, "release", lambda: MADE_UP_RELEASE)


def refused(error: Exception) -> tuple[str, int, str]:
    refusal = library.refusal(error)
    assert isinstance(refusal, Refusal)
    return refusal.code, refusal.exit_code, refusal.message


def test_the_error_of_the_mcp_module_itself_is_the_install_hint() -> None:
    error = ModuleNotFoundError("No module named 'mcp'", name="mcp")

    assert refused(error) == ("E_USAGE", EXIT_USAGE, NOT_INSTALLED)


def test_an_error_of_a_library_module_where_no_mcp_is_found_is_the_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "found", lambda: library.ABSENT)
    error = ModuleNotFoundError("No module named 'mcp.server'", name="mcp.server")

    assert refused(error) == ("E_USAGE", EXIT_USAGE, NOT_INSTALLED)


@pytest.mark.parametrize(
    "missing", ["mcp_types", "mcpx", "starlette", "pydantic_settings", "mcp.server.mcpserver"]
)
@pytest.mark.usefixtures("installed")
def test_any_other_error_is_a_broken_install_named_with_its_module_and_release(
    missing: str,
) -> None:
    error = ModuleNotFoundError(f"No module named {missing!r}", name=missing)

    assert refused(error) == (
        "E_USAGE",
        EXIT_USAGE,
        f"the tool-server library mcp 2.3.0 is a broken install: it cannot import {missing}; "
        f"{REINSTALL}",
    )


@pytest.mark.parametrize("release", ["1.20.0", "3.0.0"])
def test_a_release_outside_the_bounds_names_the_bounds(
    release: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library, "found", lambda: library.LIBRARY)
    monkeypatch.setattr(library, "release", lambda: release)
    error = ImportError(
        "cannot import name 'made_up_name' from 'pydantic' (/home/user-a/made-up/pydantic.py)",
        name="pydantic",
        path="/home/user-a/made-up/pydantic.py",
    )

    assert refused(error) == (
        "E_USAGE",
        EXIT_USAGE,
        f"the tool-server library mcp {release} is a broken install: it cannot import "
        f"pydantic, and pairbench supports mcp>=1.21.1,<3; {REINSTALL}",
    )


def test_a_broken_install_without_metadata_names_no_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "found", lambda: None)
    monkeypatch.setattr(library, "release", lambda: None)
    error = ModuleNotFoundError("No module named 'starlette'", name="starlette")

    assert refused(error) == (
        "E_USAGE",
        EXIT_USAGE,
        f"the tool-server library mcp is a broken install: it cannot import starlette; {REINSTALL}",
    )


@pytest.mark.parametrize(
    ("version", "shown"),
    [
        ("2.3.0", "2.3.0"),
        ("2.0.0rc1", "2.0.0rc1"),
        ("2.3.0 /home/user-a/made-up-env", None),
        ("2.3.0\nmade-up", None),
        ("", None),
    ],
)
def test_the_release_is_the_metadata_version_only_when_it_reads_as_a_release(
    version: str, shown: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda name: version)

    assert library.release() == shown


def test_a_metadata_version_that_is_not_a_release_is_left_out_of_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "found", lambda: library.LIBRARY)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.3.0 /home/user-a/made-up")
    error = ModuleNotFoundError("No module named 'starlette'", name="starlette")

    code, exit_code, message = refused(error)

    assert (code, exit_code, message) == (
        "E_USAGE",
        EXIT_USAGE,
        f"the tool-server library mcp is a broken install: it cannot import starlette; {REINSTALL}",
    )
    assert "/home" not in message


@pytest.mark.parametrize("name", [None, "/home/user-a/made-up/x.py", "made up"])
@pytest.mark.usefixtures("installed")
def test_an_error_without_a_plain_module_name_shows_no_name_and_never_its_text(
    name: str | None,
) -> None:
    error = ImportError("a made-up failure in /home/user-a/made-up/x.py", name=name)

    code, exit_code, message = refused(error)

    assert (code, exit_code, message) == (
        "E_USAGE",
        EXIT_USAGE,
        "the tool-server library mcp 2.3.0 is a broken install: one of its modules cannot be "
        f"imported; {REINSTALL}",
    )
    assert "/home" not in message


@pytest.mark.parametrize(
    "error",
    [
        TypeError("a made-up failure in /home/user-a/made-up/x.py"),
        AttributeError("made_up_name", name="made_up_name"),
        RuntimeError("a made-up failure"),
    ],
    ids=["type-error", "attribute-error-with-a-name", "runtime-error"],
)
@pytest.mark.usefixtures("installed")
def test_an_error_that_is_not_an_import_error_names_no_module_and_never_its_text(
    error: Exception,
) -> None:
    code, exit_code, message = refused(error)

    assert (code, exit_code, message) == (
        "E_USAGE",
        EXIT_USAGE,
        "the tool-server library mcp 2.3.0 is a broken install: one of its modules cannot be "
        f"imported; {REINSTALL}",
    )


@pytest.mark.parametrize("file", ["mcp.py", "mcp/__init__.py"])
def test_a_local_module_that_takes_the_librarys_place_is_named_by_its_file_name(
    file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library, "found", lambda: file)
    error = ModuleNotFoundError("No module named 'mcp.server'", name="mcp.server")

    assert refused(error) == (
        "E_USAGE",
        EXIT_USAGE,
        f"a local module named mcp ({file}) shadows the tool-server library: rename it, or "
        "start pairbench from another folder",
    )


# The import error of a module that imports a name from ``mcp`` while ``mcp`` is the
# module being imported, or one that lacks the name: it names ``mcp`` and carries a path.
NAME_FROM_MCP = ImportError(
    "cannot import name 'MadeUpSession' from partially initialized module 'mcp' (most likely "
    "due to a circular import) (/home/user-a/made-up/mcp.py)",
    name="mcp",
    path="/home/user-a/made-up/mcp.py",
)


@pytest.mark.parametrize("file", ["mcp.py", "mcp/__init__.py"])
def test_a_local_module_that_imports_a_name_from_mcp_is_named_by_its_file_name(
    file: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library, "found", lambda: file)

    assert refused(NAME_FROM_MCP) == (
        "E_USAGE",
        EXIT_USAGE,
        f"a local module named mcp ({file}) shadows the tool-server library: rename it, or "
        "start pairbench from another folder",
    )


@pytest.mark.usefixtures("installed")
def test_a_library_that_cannot_import_a_name_from_mcp_is_a_broken_install() -> None:
    code, exit_code, message = refused(NAME_FROM_MCP)

    assert (code, exit_code, message) == (
        "E_USAGE",
        EXIT_USAGE,
        f"the tool-server library mcp 2.3.0 is a broken install: it cannot import mcp; {REINSTALL}",
    )
    assert "/home" not in message


def test_an_import_error_that_names_mcp_where_no_mcp_is_found_is_the_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "found", lambda: library.ABSENT)

    assert refused(NAME_FROM_MCP) == ("E_USAGE", EXIT_USAGE, NOT_INSTALLED)


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def module_spec(origin: Path) -> importlib.machinery.ModuleSpec:
    is_package = origin.name == "__init__.py"
    spec = importlib.machinery.ModuleSpec("mcp", None, origin=str(origin), is_package=is_package)
    spec.has_location = True
    if is_package:
        spec.submodule_search_locations = [str(origin.parent)]
    return spec


def test_found_names_a_local_module_and_never_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = write(tmp_path / "work-a" / "mcp.py")
    monkeypatch.setattr(library, "_spec", lambda: module_spec(local))
    monkeypatch.setattr(library, "_library_file", lambda: None)

    assert library.found() == "mcp.py"


def test_found_names_a_local_package_and_never_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = write(tmp_path / "work-a" / "mcp" / "__init__.py")
    installed = write(tmp_path / "site-a" / "mcp" / "__init__.py")
    monkeypatch.setattr(library, "_spec", lambda: module_spec(local))
    monkeypatch.setattr(library, "_library_file", lambda: installed)

    assert library.found() == "mcp/__init__.py"


def test_found_knows_the_file_the_librarys_metadata_places(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = write(tmp_path / "site-a" / "mcp" / "__init__.py")
    monkeypatch.setattr(library, "_spec", lambda: module_spec(installed))
    monkeypatch.setattr(library, "_library_file", lambda: installed)

    assert library.found() == library.LIBRARY


@pytest.mark.parametrize(
    ("layout", "expected"), [("mcpserver", "library"), ("tools", "mcp/__init__.py")]
)
def test_found_without_metadata_knows_the_library_by_its_server_package(
    layout: str, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = write(tmp_path / "site-a" / "mcp" / "__init__.py")
    write(tmp_path / "site-a" / "mcp" / "server" / layout / "__init__.py")
    monkeypatch.setattr(library, "_spec", lambda: module_spec(package))
    monkeypatch.setattr(library, "_library_file", lambda: None)

    assert library.found() == expected


def test_found_reads_a_folder_without_an_init_file_and_nothing_found_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "work-a" / "mcp"
    folder.mkdir(parents=True)
    namespace = importlib.machinery.ModuleSpec("mcp", None, is_package=True)
    namespace.submodule_search_locations = [str(folder)]
    monkeypatch.setattr(library, "_spec", lambda: namespace)
    in_folder = library.found()
    monkeypatch.setattr(library, "_spec", lambda: None)

    assert (in_folder, library.found()) == (library.ABSENT, library.ABSENT)


def test_found_cannot_tell_a_module_without_a_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_spec() -> None:
        raise ValueError("mcp.__spec__ is None")

    monkeypatch.setattr(library, "_spec", no_spec)

    assert library.found() is None
