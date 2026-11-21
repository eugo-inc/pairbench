# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The project files, the agent files, the fixtures' sidecars and the launch-cost script."""

from __future__ import annotations

import ast
import gzip
import importlib.util
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .conftest import documents

LICENCE_HEADER = (
    "# SPDX-License-Identifier: Apache-2.0",
    "# Copyright (c) 2026, Eugo, Inc.",
)
SOURCE_FILES = (
    "src/pairbench/mcp/__init__.py",
    "src/pairbench/mcp/library.py",
    "src/pairbench/mcp/server.py",
    "tools/launch_cost.py",
    "tools/hash_inputs.py",
    "tools/docs_site.py",
    "tools/api_reference.py",
    "tools/share_image.py",
)
SOURCE_FOLDERS = ("tests/unit/docs", "tests/unit/mcp")
PROJECT_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CITATION.cff",
    "THIRD_PARTY_NOTICES.md",
    "llms.txt",
    "AGENTS.md",
    "docs/agents.md",
    "skills/pairbench/SKILL.md",
)
NOT_BUNDLED = "invoked as an external program, not bundled"
SITE_HEADING = "## The documentation site"
# A path inside the repository, as a docstring names one.
REPOSITORY_PATH = re.compile(r"(?<![\w/])((?:docs|tools|src|tests|showcases)/[\w./-]*\w)")
# What every number in a document is, each by words its sentence holds: a known answer of
# the method, a made-up example, a share from the simulated experiments, or a figure
# filled in from a results file.
NUMBER_KINDS = ("known answer", "made-up example", "tools/error_rates.py", "pairbench fill")
# The packages whose code the built pages of the site carry, besides the site's own
# dependencies, and the plug-in that writes its site map.
SITE_PARTS = ("astro-expressive-code", "@pagefind/default-ui", "pagefind", "@astrojs/sitemap")
# Pagefind's search interface, and the packages built into its prebuilt scripts, which the
# site's lockfile does not list: each with the version that Pagefind's own lockfile for the
# interface installs, read at the interface's version that the site locks, from
# https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_ui/default/package-lock.json
SEARCH_UI = "@pagefind/default-ui"
SEARCH_UI_READ = "1.6.0"
SEARCH_UI_PACKAGES = {
    "svelte": "4.2.20",
    "bcp-47": "2.1.2",
    "is-alphabetical": "2.0.1",
    "is-alphanumerical": "2.0.1",
    "is-decimal": "2.0.1",
}
# The Pagefind program, which writes the scripts of its component interface into the built
# site, and the packages built into them, read the same way at the program's version that the
# site locks, from
# https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_ui/component/package-lock.json
PAGEFIND = "pagefind"
COMPONENT_UI_PACKAGES = {
    "adequate-little-templates": "1.0.2",
    "bcp-47": "2.1.2",
    "is-alphabetical": "2.0.1",
    "is-alphanumerical": "2.0.1",
    "is-decimal": "2.0.1",
}
# The program writes the script of its modular interface into the built site too. It is
# Pagefind's own code: the language tag parser, which its package lists for its build in
# https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_ui/modular/package.json, is not in
# the script, as the built site shows.
MODULAR_UI_SAYS = (
    "the script of its modular interface, which is Pagefind's own code with none of these "
    "packages built in"
)
# The interfaces the language tag parser is built into, as its row names them, and the scripts
# of the built site that hold it: each holds the parser's list of tags, which names this one.
BCP47_ROW_SAYS = (
    "inside the prebuilt scripts of the search interface and of the component interface"
)
LANGUAGE_TAG_PARSER_SCRIPTS = ("pagefind/pagefind-component-ui.js", "pagefind/pagefind-ui.js")
LANGUAGE_TAG_PARSER_TAG = '"art-lojban"'
# The theme Starlight makes its code themes from, read in the copy Starlight 0.42.8 ships,
# https://unpkg.com/@astrojs/starlight@0.42.8/dist/integrations/expressive-code/themes/night-owl-dark.js
NIGHT_OWL_ROW = "| Night Owl, in Starlight 0.42.8 |"
NIGHT_OWL_LICENCE = "MIT"
NIGHT_OWL_SOURCE = "<https://github.com/sdras/night-owl-vscode-theme>"
# The prebuilt script of the interface that the site's pages load, and how it names the source
# of each package built into it: a comment line "// node_modules/NAME/PATH".
SEARCH_UI_SCRIPT = "site/node_modules/@pagefind/default-ui/npm_dist/mjs/ui-core.mjs"
BUILT_IN = re.compile(r"^// node_modules/((?:@[\w.-]+/)?[\w.-]+)/", re.MULTILINE)
PAGEFIND_SCOPE = "node_modules/@pagefind/"
# Pagefind's search programs in the built site: WebAssembly built from Rust, compressed, after
# a short signature of Pagefind's own.
SEARCH_PROGRAMS = ("pagefind/wasm.en.pagefind", "pagefind/wasm.unknown.pagefind")
WASM_START = b"\x00asm"
# The start of a WebAssembly module of the format's first version, and of a gzip stream.
WASM_MODULE = WASM_START + b"\x01\x00\x00\x00"
GZIP_START = b"\x1f\x8b"
# The crates the search programs name, read from the built files at the Pagefind version the
# site locks: a crate whose source path is in them, and each tool their producers section
# names. A date in a tool's version is left out.
SEARCH_PROGRAM_CRATES = {
    "minicbor": "2.3.1",
    "std": "1.101.0-nightly (f9ceb4a4d)",
    "rustc": "1.101.0-nightly (f9ceb4a4d)",
    "walrus": "0.27.2",
    "wasm-bindgen": "0.2.129 (165586f85)",
}
CRATES_HEADING = "| Crate and version |"
# What the programs name that is no crate of the lock file: the compiler and its standard
# library, and the tools in their producers section.
SEARCH_PROGRAM_TOOLS = ("rustc", "std", "walrus", "wasm-bindgen")
# The crates compiled into the search programs, each with its version and the licence its own
# Cargo.toml.orig states at that version. They are the crates Pagefind's own crate
# ``pagefind_web`` depends on for the WebAssembly target, as Pagefind 1.6.0 gives them in
# https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_web/Cargo.toml and
# https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_web/Cargo.lock: the dependencies of
# its dependencies too, each at the version the lock file names, and none that only runs while
# the programs are built (a procedural macro, a build script's dependency) or that no enabled
# feature turns on. With them are the crates from crates.io that the standard library depends
# on for the WebAssembly target with the features Cargo turns on for it by default, as Pagefind
# compiles the standard library from its source with the programs (see STD_BUILT_CRATES below):
# the dependencies of its backtrace support too, and not hashbrown's default hasher, which the
# standard library leaves off.
COMPILED_CRATES_READ = "1.6.0"
COMPILED_CRATES = {
    "addr2line": ("0.27.1", "Apache-2.0 OR MIT"),
    "adler2": ("2.0.1", "0BSD OR MIT OR Apache-2.0"),
    "bit-set": ("0.11.1", "Apache-2.0 OR MIT"),
    "bit-vec": ("0.10.1", "Apache-2.0 OR MIT"),
    "cfg-if": ("1.0.4", "MIT OR Apache-2.0"),
    "dlmalloc": ("0.2.14", "MIT/Apache-2.0"),
    "gimli": ("0.34.0", "MIT OR Apache-2.0"),
    "hashbrown": ("0.17.1", "MIT OR Apache-2.0"),
    "hifijson": ("0.5.0", "MIT"),
    "libc": ("0.2.191", "MIT OR Apache-2.0"),
    "memchr": ("2.8.3", "Unlicense OR MIT"),
    "minicbor": ("2.3.1", "BlueOak-1.0.0"),
    "miniz_oxide": ("0.9.1", "MIT OR Zlib OR Apache-2.0"),
    "object": ("0.39.1", "Apache-2.0 OR MIT"),
    "once_cell": ("1.21.4", "MIT OR Apache-2.0"),
    "pagefind_stem": ("1.0.0", "MIT, and BSD-3-Clause for its Snowball tables"),
    "rustc-demangle": ("0.1.28", "MIT/Apache-2.0"),
    "unicode-ident": ("1.0.24", "(MIT OR Apache-2.0) AND Unicode-3.0"),
    "wasm-bindgen": ("0.2.129", "MIT OR Apache-2.0"),
    "wasm-bindgen-shared": ("0.2.129", "MIT OR Apache-2.0"),
    "write-json": ("0.1.4", "MIT OR Apache-2.0"),
}
# Where a crate's licence is read: its Cargo.toml.orig as published at that version.
CRATE_SOURCE = "<https://docs.rs/crate/{name}/{version}/source/Cargo.toml.orig>"
# Pagefind builds the programs with -Z build-std=panic_abort,std
# (https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_web/local_build.sh) and no
# -Z build-std-features, so the standard library is built with the features Cargo turns on for
# it by default, read in the book of the Cargo that the compiler's commit carries as its
# src/tools/cargo, and the crates of its own lock file at the compiler's commit that it depends
# on for the target are compiled in: those from crates.io above, and compiler_builtins, whose
# source is in the compiler's repository.
STD_COMMIT = "f9ceb4a4d45a471eed7bd8c40dddb7c38e749e21"
CARGO_COMMIT = "31d3246e0e8d3a80d4a90b54aa48ff180adb408b"
STD_BUILT_CRATES = {
    "compiler_builtins": (
        "0.1.160",
        "MIT AND Apache-2.0 WITH LLVM-exception AND (MIT OR Apache-2.0)",
        f"<https://github.com/rust-lang/rust/blob/{STD_COMMIT}/library/compiler-builtins/"
        "compiler-builtins/Cargo.toml>",
    ),
}
BUILD_STD = "`-Z build-std=panic_abort,std`"
BUILD_STD_FEATURES = (
    "the features Cargo turns on for it by default, `backtrace` and `panic-unwind`, as the book "
    "of the Cargo that the compiler's commit carries says "
    f"(<https://github.com/rust-lang/cargo/blob/{CARGO_COMMIT}/doc/book/src/reference/"
    "unstable.md#build-std-features>)"
)
STD_KEPT = (
    "A crate compiled in is listed even where the files do not show that the programs keep any "
    "of its code."
)
# Snowball writes the stemmer's word tables; its licence is in its COPYING file at
# the release the generated files name ("Generated from english.sbl by Snowball 3.0.0").
SNOWBALL_COPYING = "<https://github.com/snowballstem/snowball/blob/v3.0.0/COPYING>"
STEMMER_NOTICES = "<https://docs.rs/crate/pagefind_stem/1.0.0/source/src/lib.rs>"
# The source path of a crate from a registry, and of a crate of the Rust toolchain's library,
# whose version is the version of the compiler that built it.
# Both are read from the whole program, so a path glued to the text after it is still read.
REGISTRY_CRATE = re.compile(
    r"/registry/src/[\x21-\x2e\x30-\x7e]+/([A-Za-z0-9_-]+?)-(\d+\.\d+\.\d+[\w.+-]*)/"
)
TOOLCHAIN_CRATE = re.compile(r"/lib/rustlib/src/rust/library/(\w+)/")
# The path of a source file, up to the first ``.rs``, whatever text is glued after it.
SOURCE_PATH = re.compile(r"/[\x21-\x7e]*?\.rs")
COMPILER = "rustc"
VERSION_DATE = re.compile(r" \d{4}-\d{2}-\d{2}\)$")
# The fields of a producers section that name a tool, not a language.
TOOL_FIELDS = ("processed-by", "sdk")
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2
EXIT_LAUNCH = 5
SKILL_LINK = re.compile(r"\]\((references/[\w.-]+\.md)\)")


def header_of(path: Path) -> tuple[str, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 1 if lines and lines[0].startswith("#!") else 0
    return tuple(lines[start : start + 2])


def owned_sources(repo_root: Path) -> list[Path]:
    paths = [repo_root / name for name in SOURCE_FILES]
    for name in SOURCE_FOLDERS:
        paths += sorted((repo_root / name).glob("*.py"))
    return paths


def test_every_source_file_starts_with_the_licence_header(repo_root: Path) -> None:
    missing = [
        path.relative_to(repo_root).as_posix()
        for path in owned_sources(repo_root)
        if header_of(path) != LICENCE_HEADER
    ]

    assert missing == []


@pytest.mark.parametrize("name", PROJECT_FILES)
def test_a_project_file_exists_and_is_not_empty(repo_root: Path, name: str) -> None:
    path = repo_root / name

    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip()


def test_the_third_party_notices_list_perf_and_matplotlib(repo_root: Path) -> None:
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    perf_rows = [line for line in text.splitlines() if line.startswith("| `perf` |")]
    plot_rows = [line for line in text.splitlines() if "matplotlib" in line.lower()]

    assert NOT_BUNDLED in text
    assert len(perf_rows) == 1
    assert any("optional extra that is not bundled" in line for line in plot_rows)


@pytest.mark.parametrize("program", ["true", "sysctl"])
def test_the_third_party_notices_list_each_system_program_the_core_runs(
    repo_root: Path, program: str
) -> None:
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith(f"| `{program}` |")]

    assert len(rows) == 1


def _site_section(repo_root: Path) -> list[str]:
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    return text.split(f"\n{SITE_HEADING}\n", 1)[1].split("\n## ", 1)[0].splitlines()


def _locked_version(repo_root: Path, package: str) -> str:
    """The version the site's lockfile installs, read from npm's default lockfile format."""
    lock = json.loads((repo_root / "site" / "package-lock.json").read_text(encoding="utf-8"))
    version: str = lock["packages"][f"node_modules/{package}"]["version"]
    return version


def test_the_third_party_notices_list_every_package_the_documentation_site_is_built_with(
    repo_root: Path,
) -> None:
    manifest = json.loads((repo_root / "site" / "package.json").read_text(encoding="utf-8"))
    rows = [line for line in _site_section(repo_root) if line.startswith("| ")]
    for package in [*manifest["dependencies"], *SITE_PARTS]:
        version = _locked_version(repo_root, package)
        found = [row for row in rows if row.startswith(f"| `{package}` {version} |")]
        assert len(found) == 1, (package, version)


def _listed(repo_root: Path) -> set[tuple[str, str]]:
    """Each package of the site section's table with its version: a row's first cell names
    one or more packages in backquotes and ends with the version they share."""
    listed: set[tuple[str, str]] = set()
    for line in _site_section(repo_root):
        if line.startswith("| ") and not line.startswith("| Package"):
            cell = line[2:].split(" | ", 1)[0]
            version = cell.rsplit(" ", 1)[-1]
            listed.update((name, version) for name in re.findall(r"`([^`]+)`", cell))
    return listed


def test_the_third_party_notices_list_every_package_the_lockfile_installs_for_pagefind(
    repo_root: Path,
) -> None:
    lock = json.loads((repo_root / "site" / "package-lock.json").read_text(encoding="utf-8"))
    installed = {
        (key.removeprefix("node_modules/"), entry["version"])
        for key, entry in lock["packages"].items()
        if key.startswith(PAGEFIND_SCOPE)
    }

    assert (SEARCH_UI, SEARCH_UI_READ) in installed
    assert sorted(installed - _listed(repo_root)) == []


def test_the_third_party_notices_list_the_packages_built_into_the_search_interface(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, SEARCH_UI) == SEARCH_UI_READ
    assert sorted(set(SEARCH_UI_PACKAGES.items()) - _listed(repo_root)) == []


def test_the_third_party_notices_list_the_packages_built_into_the_component_interface(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, PAGEFIND) == SEARCH_UI_READ
    assert sorted(set(COMPONENT_UI_PACKAGES.items()) - _listed(repo_root)) == []


def test_the_packages_built_into_the_search_interface_are_the_ones_its_script_names(
    repo_root: Path,
) -> None:
    script = repo_root / SEARCH_UI_SCRIPT
    if not script.is_file():
        pytest.skip(f"needs the site's packages installed, for {SEARCH_UI_SCRIPT}: npm ci in site/")
    named = set(BUILT_IN.findall(script.read_text(encoding="utf-8")))

    assert sorted(named) == sorted(SEARCH_UI_PACKAGES)


def _leb128(data: bytes, at: int) -> tuple[int, int]:
    """An unsigned LEB128 number of a WebAssembly module, and where the next field starts."""
    value = shift = 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, at


def _name(data: bytes, at: int) -> tuple[str, int]:
    size, at = _leb128(data, at)
    return data[at : at + size].decode("utf-8"), at + size


def _producers(module: bytes) -> dict[str, str]:
    """Each tool a WebAssembly module's producers section names, with its version."""
    tools: dict[str, str] = {}
    at = len(WASM_START) + 4
    while at < len(module):
        kind = module[at]
        size, start = _leb128(module, at + 1)
        at = start + size
        if kind != 0:
            continue
        section, body = _name(module, start)
        if section != "producers":
            continue
        fields, body = _leb128(module, body)
        for _ in range(fields):
            field, body = _name(module, body)
            values, body = _leb128(module, body)
            for _ in range(values):
                tool, body = _name(module, body)
                version, body = _name(module, body)
                if field in TOOL_FIELDS:
                    tools[tool] = VERSION_DATE.sub(")", version)
    return tools


def search_program_crates(data: bytes) -> dict[str, str]:
    """The crates a built search program of Pagefind names, each with its version.

    A source path that is not a crate's of a registry or of the toolchain's library raises
    ``ValueError``, so a crate named some other way is not missed.
    """
    raw = _unpacked(data)
    module = raw[raw.index(WASM_START) :]
    tools = _producers(module)
    crates = dict(tools)
    text = module.decode("latin-1")
    for path in sorted(set(SOURCE_PATH.findall(text))):
        if not REGISTRY_CRATE.search(path) and not TOOLCHAIN_CRATE.search(path):
            raise ValueError(f"a source path of no known crate: {path}")
    crates.update((found[1], found[2]) for found in REGISTRY_CRATE.finditer(text))
    crates.update((found[1], tools[COMPILER]) for found in TOOLCHAIN_CRATE.finditer(text))
    return crates


def _unpacked(data: bytes) -> bytes:
    """A file's bytes, unpacked when gzip packs them."""
    if data[: len(GZIP_START)] != GZIP_START:
        return data
    try:
        return gzip.decompress(data)
    except (OSError, EOFError):
        return data


def search_programs(site: Path) -> list[str]:
    """Every program in a built site, at any depth, as a path from the site's folder: each file
    named ``*.pagefind``, and each file of another name that holds a WebAssembly module, packed
    with gzip or not."""
    return sorted(
        path.relative_to(site).as_posix()
        for path in site.rglob("*")
        if path.is_file()
        and (path.suffix == ".pagefind" or WASM_MODULE in _unpacked(path.read_bytes()))
    )


def crates_listed(repo_root: Path) -> set[tuple[str, str]]:
    """Each crate of the notices' table of crates with its version: a row's first cell names
    one or more crates in backquotes, followed by the version they share."""
    lines = _site_section(repo_root)
    headings = [at for at, line in enumerate(lines) if line.startswith(CRATES_HEADING)]
    listed: set[tuple[str, str]] = set()
    for line in lines[headings[0] + 2 :] if headings else ():
        if not line.startswith("| "):
            break
        cell = line[2:].split(" | ", 1)[0]
        version = cell.rsplit("`", 1)[-1].strip()
        listed.update((name, version) for name in re.findall(r"`([^`]+)`", cell))
    return listed


def _number(value: int) -> bytes:
    """An unsigned LEB128 number, as a WebAssembly module writes a size."""
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _text(text: str) -> bytes:
    return _number(len(text.encode("utf-8"))) + text.encode("utf-8")


def _module(*sections: tuple[int, bytes]) -> bytes:
    """A small WebAssembly module of the given sections, behind Pagefind's signature, packed
    the way a built search program is."""
    body = WASM_START + b"\x01\x00\x00\x00"
    for kind, content in sections:
        body += bytes([kind]) + _number(len(content)) + content
    return gzip.compress(b"pagefind_dcd" + body)


def _producers_section(fields: dict[str, dict[str, str]]) -> tuple[int, bytes]:
    content = _text("producers") + _number(len(fields))
    for field, values in fields.items():
        content += _text(field) + _number(len(values))
        for name, version in values.items():
            content += _text(name) + _text(version)
    return 0, content


MADE_UP_PRODUCERS = _producers_section(
    {
        "language": {"Rust": ""},
        "processed-by": {"rustc": "9.8.7-nightly (abc1234 2001-02-03)", "made-up-gen": "5.4.3"},
    }
)
# Paths as a built program holds them: each ended by a zero byte, or glued to the next text.
MADE_UP_PATHS = (
    b"/cargo/registry/src/index.example-0a1b/made-up-crate-1.2.3/src/lib.rs\x00"
    b"/toolchain/lib/rustlib/src/rust/library/core/src/fmt/mod.rs\x00"
    b"/cargo/registry/src/index.example-0a1b/glued-crate-0.1.0/src/lib.rsmade-up text\x00"
)


def test_the_crates_of_a_search_program_are_read_from_its_paths_and_producers() -> None:
    data = _module((1, b"\x00"), MADE_UP_PRODUCERS, (11, MADE_UP_PATHS))

    assert search_program_crates(data) == {
        "made-up-crate": "1.2.3",
        "glued-crate": "0.1.0",
        "core": "9.8.7-nightly (abc1234)",
        "rustc": "9.8.7-nightly (abc1234)",
        "made-up-gen": "5.4.3",
    }


def test_the_crates_of_an_unpacked_program_are_read_the_same_way() -> None:
    data = _module((1, b"\x00"), MADE_UP_PRODUCERS, (11, MADE_UP_PATHS))
    unpacked = gzip.decompress(data)

    assert search_program_crates(unpacked) == search_program_crates(data)
    assert search_program_crates(unpacked[unpacked.index(WASM_START) :]) == search_program_crates(
        data
    )


# The programs of a made-up built site, beside the other files of its search.
MADE_UP_SITE_PROGRAMS = ("pagefind/wasm.en.pagefind", "pagefind/wasm.unknown.pagefind")
# Files other than programs: a page, and a packed piece of the search index.
MADE_UP_SITE_FILES = {
    "latest/index.html": b"<!doctype html><title>made-up page</title>\n",
    "pagefind/fragment/en_made-up.pf_fragment": gzip.compress(b'pagefind_dcd{"url":"/made-up/"}'),
}


@pytest.mark.parametrize(
    ("path", "content", "found"),
    [
        ("pagefind/extra/wasm.de.pagefind", "packed", True),
        ("0.1/pagefind/wasm.unknown.pagefind", "packed", True),
        ("0.1/pagefind/extra/deeper/wasm.de.pagefind", "packed", True),
        ("pagefind/made-up-program.bin", "packed", True),
        ("_astro/made-up.wasm", "bare", True),
        ("_astro/made-up-program", "bare", True),
        ("pagefind/wasm.made-up.pagefind", "text", True),
        ("pagefind/fragment/en_other.pf_fragment", "piece", False),
        ("latest/guides/made-up/index.html", "text", False),
    ],
)
def test_every_search_program_of_a_built_site_is_found_at_any_depth(
    tmp_path: Path, path: str, content: str, found: bool
) -> None:
    program = _module(MADE_UP_PRODUCERS)
    contents = {
        "packed": program,
        "bare": gzip.decompress(program)[len(b"pagefind_dcd") :],
        "text": b"made-up text\n",
        "piece": gzip.compress(b'pagefind_dcd{"url":"/other/"}'),
    }
    files = dict.fromkeys(MADE_UP_SITE_PROGRAMS, program) | MADE_UP_SITE_FILES
    for name, data in (files | {path: contents[content]}).items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)

    expected = sorted([*MADE_UP_SITE_PROGRAMS, *([path] if found else [])])
    assert search_programs(tmp_path) == expected


def test_a_source_path_of_no_known_crate_is_refused() -> None:
    data = _module(MADE_UP_PRODUCERS, (11, b"/somewhere/vendor/made-up/src/lib.rsglued\x00"))

    with pytest.raises(ValueError) as refused:
        search_program_crates(data)
    assert (
        str(refused.value)
        == "a source path of no known crate: /somewhere/vendor/made-up/src/lib.rs"
    )


def test_the_third_party_notices_list_every_crate_the_search_programs_name(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, PAGEFIND) == SEARCH_UI_READ
    assert sorted(set(SEARCH_PROGRAM_CRATES.items()) - crates_listed(repo_root)) == []


def _cells(row: str) -> list[str]:
    """The cells of a row of a Markdown table."""
    return [cell.strip() for cell in row.strip().strip("|").split(" | ")]


def test_the_third_party_notices_list_every_crate_compiled_into_the_search_programs(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, PAGEFIND) == COMPILED_CRATES_READ
    listed = crates_listed(repo_root)
    rows = [line for line in _site_section(repo_root) if line.startswith("| `")]
    wrong: dict[str, list[str]] = {}
    for name, (version, licence) in COMPILED_CRATES.items():
        found = [row for row in rows if row.startswith(f"| `{name}` {version} |")]
        cells = [_cells(row) for row in found]
        if (name, version) not in listed or [(c[2], c[3].split(", ")[0]) for c in cells] != [
            (licence, CRATE_SOURCE.format(name=name, version=version))
        ]:
            wrong[name] = found
    assert wrong == {}


def test_the_third_party_notices_list_the_crates_of_the_standard_library_build(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, PAGEFIND) == COMPILED_CRATES_READ
    listed = crates_listed(repo_root)
    rows = [line for line in _site_section(repo_root) if line.startswith("| `")]
    wrong: dict[str, list[str]] = {}
    for name, (version, licence, source) in STD_BUILT_CRATES.items():
        found = [row for row in rows if row.startswith(f"| `{name}` {version} |")]
        if (name, version) not in listed or [_cells(row)[2:] for row in found] != [
            [licence, source]
        ]:
            wrong[name] = found
    assert wrong == {}
    text = " ".join(_site_section(repo_root))
    parts = (BUILD_STD, BUILD_STD_FEATURES, STD_KEPT, STD_COMMIT)
    assert [part for part in parts if part not in text] == []


def test_the_third_party_notices_say_the_modular_interface_carries_none_of_the_packages(
    repo_root: Path,
) -> None:
    assert _locked_version(repo_root, PAGEFIND) == SEARCH_UI_READ
    text = " ".join(_site_section(repo_root))
    (row,) = [line for line in _site_section(repo_root) if line.startswith("| `bcp-47` ")]

    assert MODULAR_UI_SAYS in text
    assert BCP47_ROW_SAYS in row


def test_the_third_party_notices_name_the_theme_of_the_code_blocks(repo_root: Path) -> None:
    rows = [line for line in _site_section(repo_root) if line.startswith(NIGHT_OWL_ROW)]

    assert len(rows) == 1
    cells = _cells(rows[0])
    assert cells[2] == NIGHT_OWL_LICENCE
    assert cells[3].split(", ")[0] == NIGHT_OWL_SOURCE


def test_the_stemmer_row_names_the_licence_of_its_snowball_tables(repo_root: Path) -> None:
    version, _ = COMPILED_CRATES["pagefind_stem"]
    rows = [
        line
        for line in _site_section(repo_root)
        if line.startswith(f"| `pagefind_stem` {version} |")
    ]
    assert len(rows) == 1
    row = rows[0]
    source = _cells(row)[3]

    assert "Snowball 3.0.0" in row
    assert source.split(", ") == [
        CRATE_SOURCE.format(name="pagefind_stem", version=version),
        STEMMER_NOTICES,
        SNOWBALL_COPYING,
    ]


def test_each_crate_the_search_programs_name_by_its_source_is_a_compiled_crate() -> None:
    # The crates the built programs name by the path of their source are a part of the crates
    # worked out from Pagefind's lock file, at the same version.
    by_source = {
        name: version
        for name, version in SEARCH_PROGRAM_CRATES.items()
        if name not in SEARCH_PROGRAM_TOOLS
    }

    assert by_source == {"minicbor": "2.3.1"}
    assert all(COMPILED_CRATES[name][0] == version for name, version in by_source.items())


def test_the_third_party_notices_say_the_documentation_site_carries_third_party_code(
    repo_root: Path,
) -> None:
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    opening = text.split("\n## ", 1)[0]
    assert "pairbench bundles no third-party program" not in opening
    assert any("mark.js" in line for line in _site_section(repo_root))


@pytest.mark.parametrize("name", ["docs/faq.md", "CONTRIBUTING.md"])
def test_the_rule_on_numbers_names_every_kind_of_number_a_document_holds(
    repo_root: Path, name: str
) -> None:
    text = (repo_root / name).read_text(encoding="utf-8")
    (paragraph,) = [block for block in text.split("\n\n") if "made-up example" in block]
    folded = " ".join(paragraph.split())
    assert [kind for kind in NUMBER_KINDS if kind not in folded] == []


def test_the_citation_names_the_project_and_its_version(repo_root: Path) -> None:
    from pairbench.model import TOOL_VERSION

    text = (repo_root / "CITATION.cff").read_text(encoding="utf-8")

    assert text.startswith("cff-version: ")
    assert 'title: "pairbench"' in text
    assert f'version: "{TOOL_VERSION}"' in text
    assert "license: Apache-2.0" in text


def test_the_skill_has_its_front_matter_and_every_reference_it_links(repo_root: Path) -> None:
    skill = repo_root / "skills" / "pairbench"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    linked = SKILL_LINK.findall(text)

    assert text.startswith("---\nname: pairbench\ndescription: ")
    assert linked
    assert [name for name in linked if not (skill / name).is_file()] == []


def test_the_skill_installs_into_a_folder(cli: Callable[..., Any], tmp_path: Path) -> None:
    result = cli("skill", "install", "--dir", tmp_path)

    assert result.code == EXIT_OK, result.err
    assert (tmp_path / "pairbench" / "SKILL.md").is_file()
    assert (tmp_path / "pairbench" / "references" / "wording.md").is_file()


def test_llms_txt_links_the_agent_pages(repo_root: Path) -> None:
    text = (repo_root / "llms.txt").read_text(encoding="utf-8")

    assert text.startswith("# pairbench\n")
    assert "agents" in text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def fixtures(repo_root: Path) -> list[Path]:
    base = repo_root / "tests" / "fixtures"
    return [
        path
        for path in sorted(base.rglob("*"))
        if path.is_file()
        and "_gen" not in path.relative_to(base).parts
        and "__pycache__" not in path.parts
        and not path.name.endswith(".provenance.json")
    ]


def test_every_fixture_has_its_sidecar(repo_root: Path) -> None:
    found = fixtures(repo_root)
    problems: list[str] = []
    for path in found:
        sidecar = path.with_name(path.name + ".provenance.json")
        if not sidecar.is_file():
            problems.append(f"{path.relative_to(repo_root)}: no sidecar")
            continue
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not (repo_root / str(data.get("generator", ""))).is_file():
            problems.append(f"{path.relative_to(repo_root)}: no generator")
        if data.get("synthetic") is not True and not data.get("image"):
            problems.append(f"{path.relative_to(repo_root)}: neither synthetic nor an image")
    assert found
    assert problems == []


def test_every_sidecar_belongs_to_a_fixture(repo_root: Path) -> None:
    base = repo_root / "tests" / "fixtures"
    orphans = [
        path.relative_to(repo_root).as_posix()
        for path in sorted(base.rglob("*.provenance.json"))
        if "_gen" not in path.relative_to(base).parts
        and not path.with_name(path.name.removesuffix(".provenance.json")).is_file()
    ]

    assert orphans == []


# ---------------------------------------------------------------------------
# The launch-cost script; it is never run for real here
# ---------------------------------------------------------------------------


@pytest.fixture
def launch_cost(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "launch_cost_under_test", repo_root / "tools" / "launch_cost.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRun:
    """Stands in for running each step: records the commands and returns the codes in turn."""

    def __init__(self, *codes: int) -> None:
        self.codes = list(codes)
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> int:
        self.commands.append(list(command))
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


# A made-up checkout, the folder the launch-cost run is kept in, and a made-up caller.
CHECKOUT = Path("/made/up/checkout")
KEPT = "docs/figures/launch-cost"
UID, GID = 4242, 4343
# A class of machine in the short public form, made up.
MADE_UP_CLASS = "arm64, 4 cores, 16 GB"
# The private run folder of the script, under pairbench-runs/ of the checkout.
PRIVATE = re.compile(r"pairbench-runs/launch-cost-[0-9]{8}T[0-9]{6}Z-[0-9]+")
MACHINE_CLASS_REFUSED = (
    "--machine-class: give an architecture, cores and memory (as in 'arm64, 4 cores, 16 GB') "
    "or the name of a public cloud instance type"
)
PUBLIC_IMAGE = (
    "python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"
)
WORKLOAD = "'total = sum(i * i for i in range(20000))'"
INNER = [
    "/usr/local/bin/python3",
    "-m",
    "pairbench",
    "run",
    "--side",
    f"default=cmd:/usr/local/bin/python3 -I -c {WORKLOAD}",
    "--side",
    f"nosite=cmd:/usr/local/bin/python3 -I -S -c {WORKLOAD}",
    "--baseline",
    "default",
    "--gates",
    "warn",
    "--explain",
    "off",
    "--plots",
    "off",
    "--out",
    KEPT,
]
MEASURE = [
    "py",
    "-m",
    "pairbench",
    "gate",
    "wait-quiet",
    "--",
    "docker",
    "run",
    "--rm",
    "--memory",
    "8g",
    "--memory-swap",
    "8g",
    "--network",
    "none",
    "--user",
    f"{UID}:{GID}",
    "--volume",
    f"{CHECKOUT}:/work",
    "--workdir",
    "/work",
    "--env",
    "HOME=/home/user",
    "--env",
    "PYTHONPATH=/work/src",
    "--env",
    "PYTHONDONTWRITEBYTECODE=1",
    PUBLIC_IMAGE,
    *INNER,
]
LOOK_UP = ["docker", "image", "inspect", "--format", "{{.Id}}", PUBLIC_IMAGE]
PULL = ["docker", "pull", PUBLIC_IMAGE]
# What the script says of a word made only of option letters, which no pattern tells from a
# public name.
SHORT_WORD_FITS = (
    'a short word made only of those letters does, as in "m7bend.large" or "Standard_D4prod_v5" '
    "(both made up), since no pattern tells it from a public name."
)


def test_the_command_waits_for_quiet_on_the_host_then_runs_from_neutral_places(
    launch_cost: ModuleType,
) -> None:
    command = launch_cost.build_command(
        CHECKOUT / KEPT, repo=CHECKOUT, python="py", uid=UID, gid=GID
    )

    assert command == MEASURE


def test_the_run_inside_the_container_hashes_only_neutral_places(launch_cost: ModuleType) -> None:
    assert launch_cost.inner_command(KEPT) == INNER


def test_the_image_is_the_one_the_showcases_pin(launch_cost: ModuleType, repo_root: Path) -> None:
    lock = (repo_root / "showcases" / "python-versions" / "pairbench.toml").read_text(
        encoding="utf-8"
    )

    assert launch_cost.PUBLIC_IMAGE == PUBLIC_IMAGE
    assert f'image = "{PUBLIC_IMAGE}"' in lock


def test_a_dry_run_prints_the_command_and_runs_nothing(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", MADE_UP_CLASS, "--dry-run"],
        run=run,
        repo=tmp_path,
    )

    assert code == EXIT_OK
    assert run.commands == []
    assert "pairbench run" in capsys.readouterr().out
    assert not (tmp_path / KEPT).exists()


# The engine options a dry run prints for the container, up to the user it runs as.
CONTAINER_OPTIONS = ["run", "--rm", "--memory", "8g", "--memory-swap", "8g", "--network", "none"]


def test_a_dry_run_prints_a_memory_limit_with_no_swap_beyond_it(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--dry-run", "--machine-class", "c7gn.xlarge"],
        run=run,
        repo=tmp_path,
    )

    printed = shlex.split(capsys.readouterr().out.splitlines()[0])
    after_wait = printed[printed.index("--") + 2 :]
    assert code == EXIT_OK
    assert run.commands == []
    assert after_wait[: after_wait.index("--user")] == CONTAINER_OPTIONS


def test_a_folder_that_is_not_empty_is_refused(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / KEPT).mkdir(parents=True)
    (tmp_path / KEPT / "kept.txt").write_text("x", encoding="utf-8")
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path
    )

    assert code == EXIT_USAGE
    assert run.commands == []
    assert "not empty" in capsys.readouterr().err


# A folder value that climbs out of a folder that does not exist names the folder it climbs
# back to, and that folder is refused when it holds files, as one named directly is. The
# checkout itself, named so, is refused as the folder that would hold the private folder, below.
NOT_EMPTY = "the folder {} exists and is not empty\n"


@pytest.mark.parametrize(
    ("typed", "named"),
    [("kept/absent/..", "kept"), ("kept/sub/absent/../..", "kept")],
    ids=["back-to-a-folder-in-it", "two-levels-back-to-a-folder-in-it"],
)
@pytest.mark.parametrize("dry", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_a_folder_value_that_climbs_back_into_a_folder_with_files_is_refused(
    launch_cost: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
    named: str,
    dry: list[str],
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "kept").mkdir(parents=True)
    (checkout / "kept" / "kept.txt").write_text("x", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    monkeypatch.chdir(checkout)
    run = FakeRun(EXIT_OK)

    code = launch_cost.main([typed, "--machine-class", MADE_UP_CLASS, *dry], run=run, repo=checkout)

    printed = capsys.readouterr()
    assert code == EXIT_USAGE
    assert run.commands == []
    assert printed.out == ""
    assert printed.err == NOT_EMPTY.format(named)
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == before


# A folder that would hold the private folder the run writes under pairbench-runs: refused before
# anything runs, empty or absent, by whatever path it is named.
HOLDS_THE_PRIVATE_FOLDER = (
    "the folder {} would hold the run's private folder, which is written under pairbench-runs; "
    "name another folder inside the repository\n"
)


def listed(top: Path) -> list[str]:
    """Every path under ``top``, links not followed."""
    found = []
    for folder, folders, files in os.walk(top):
        for name in (*folders, *files):
            found.append((Path(folder) / name).relative_to(top).as_posix())
    return sorted(found)


@pytest.mark.parametrize(
    ("typed", "runs", "named"),
    [
        ("pairbench-runs", "absent", "pairbench-runs"),
        ("pairbench-runs", "empty", "pairbench-runs"),
        ("pairbench-runs/", "empty", "pairbench-runs"),
        ("kept/../pairbench-runs", "absent", "pairbench-runs"),
        ("link-to-runs", "empty", "pairbench-runs"),
        ("link-to-runs/", "empty", "pairbench-runs"),
        ("absent/..", "absent", "checkout"),
        ("link-to-checkout", "absent", "checkout"),
    ],
    ids=[
        "the-private-runs-folder-absent",
        "the-private-runs-folder-empty",
        "the-private-runs-folder-with-a-slash",
        "climbing-back-to-it",
        "through-a-link",
        "through-a-link-with-a-slash",
        "the-checkout-climbing-back-to-it",
        "the-checkout-through-a-link",
    ],
)
@pytest.mark.parametrize("dry", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_a_folder_that_would_hold_the_private_folder_is_refused_before_anything_runs(
    launch_cost: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
    runs: str,
    named: str,
    dry: list[str],
) -> None:
    # An empty checkout stands in for one whose only files are the run's own.
    checkout = tmp_path / "checkout"
    (checkout / "kept").mkdir(parents=True)
    if runs == "empty":
        (checkout / "pairbench-runs").mkdir()
    (checkout / "link-to-runs").symlink_to(checkout / "pairbench-runs", target_is_directory=True)
    (checkout / "link-to-checkout").symlink_to(checkout, target_is_directory=True)
    before = listed(tmp_path)
    monkeypatch.chdir(checkout)
    run = FakeRun(EXIT_OK)

    code = launch_cost.main([typed, "--machine-class", MADE_UP_CLASS, *dry], run=run, repo=checkout)

    printed = capsys.readouterr()
    assert code == EXIT_USAGE
    assert run.commands == []
    assert printed.out == ""
    assert printed.err == HOLDS_THE_PRIVATE_FOLDER.format(named)
    assert listed(tmp_path) == before


@pytest.mark.parametrize(
    "typed", ["pairbench-runs2", "pairbench-run", "kept", "kept/pairbench-runs"]
)
def test_a_folder_beside_the_private_runs_folder_is_accepted(
    launch_cost: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "pairbench-runs").mkdir(parents=True)
    monkeypatch.chdir(checkout)
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [typed, "--machine-class", MADE_UP_CLASS, "--dry-run"], run=run, repo=checkout
    )

    printed = capsys.readouterr()
    assert (code, printed.err) == (EXIT_OK, "")
    assert run.commands == []
    assert printed.out.splitlines()[1].endswith(f"--publish {typed}")


def test_a_folder_outside_the_repository_is_refused(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / "elsewhere"), "--machine-class", MADE_UP_CLASS],
        run=run,
        repo=tmp_path / "checkout",
    )

    assert code == EXIT_USAGE
    assert run.commands == []
    assert capsys.readouterr().err == (
        "the folder elsewhere is not inside the repository, which the run reaches at /work\n"
    )


def test_a_folder_value_that_climbs_out_of_the_repository_names_where_it_lands(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "checkout").mkdir()
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / "elsewhere" / "absent" / ".."), "--machine-class", MADE_UP_CLASS],
        run=run,
        repo=tmp_path / "checkout",
    )

    printed = capsys.readouterr()
    assert code == EXIT_USAGE
    assert run.commands == []
    assert printed.out == ""
    assert printed.err == (
        "the folder elsewhere is not inside the repository, which the run reaches at /work\n"
    )


# The two lines that refuse a folder value naming no folder, before anything runs.
NO_OUT_FOLDER = "the folder is given as an empty value; give the folder to write\n"
NAMELESS_OUT_FOLDER = (
    "the folder {typed} names no folder by its last part; give the folder to write by its name\n"
)


@pytest.mark.parametrize(
    ("typed", "refused"),
    [
        ("", NO_OUT_FOLDER),
        (".", NAMELESS_OUT_FOLDER.format(typed=".")),
        ("./", NAMELESS_OUT_FOLDER.format(typed="./")),
        ("./.", NAMELESS_OUT_FOLDER.format(typed="./.")),
    ],
    ids=["empty", "dot", "dot-slash", "dot-slash-dot"],
)
@pytest.mark.parametrize("holds", ["nothing", "a file"])
@pytest.mark.parametrize("dry", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_a_folder_value_that_names_no_folder_is_refused_by_what_was_typed(
    launch_cost: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    typed: str,
    refused: str,
    holds: str,
    dry: list[str],
) -> None:
    if holds == "a file":
        (tmp_path / "kept.txt").write_text("x", encoding="utf-8")
    before = sorted(path.name for path in tmp_path.iterdir())
    monkeypatch.chdir(tmp_path)
    run = FakeRun(EXIT_OK)

    code = launch_cost.main([typed, "--machine-class", MADE_UP_CLASS, *dry], run=run, repo=tmp_path)

    printed = capsys.readouterr()
    assert code == EXIT_USAGE
    assert run.commands == []
    assert printed.out == ""
    assert printed.err == refused
    assert "  " not in printed.err
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_a_passing_run_runs_privately_and_publishes_through_the_sidecar_check(
    launch_cost: ModuleType, tmp_path: Path
) -> None:
    out = tmp_path / KEPT
    out.mkdir(parents=True)
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(out), "--machine-class", "  arm64,  4 cores, 16 GB "], run=run, repo=tmp_path
    )

    assert code == EXIT_OK
    assert len(run.commands) == 3
    assert run.commands[0] == LOOK_UP
    assert run.commands[1][-2] == "--out"
    private = run.commands[1][-1]
    assert PRIVATE.fullmatch(private), private
    assert run.commands[1][run.commands[1].index("--volume") + 1] == f"{tmp_path}:/work"
    assert run.commands[2][1:] == [
        str(launch_cost.HASH_INPUTS),
        str(tmp_path / private),
        "--publish",
        str(out),
    ]
    assert (out / launch_cost.MACHINE_CLASS_FILE).read_text(encoding="utf-8") == (
        f"{MADE_UP_CLASS}\n"
    )


@pytest.mark.parametrize("writer_code", [EXIT_MISMATCH, EXIT_USAGE])
def test_a_publish_the_writer_refuses_writes_no_class_of_machine(
    launch_cost: ModuleType, tmp_path: Path, writer_code: int
) -> None:
    out = tmp_path / KEPT
    out.mkdir(parents=True)
    run = FakeRun(EXIT_OK, EXIT_OK, writer_code)

    code = launch_cost.main([str(out), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path)

    assert code == writer_code
    assert len(run.commands) == 3
    assert not (out / launch_cost.MACHINE_CLASS_FILE).exists()


@pytest.mark.parametrize(
    "given",
    [
        "arm64, 4 cores, 16 GB",
        "x86_64, 8 cores, 32 GB",
        "m7g.xlarge",
        "c7i.48xlarge",
        "m5.metal",
        "n2-standard-8",
        "e2-medium",
        "a2-highgpu-1g",
        "Standard_D4s_v5",
        "Standard_NC24ads_A100_v4",
        "c7i-flex.large",
        "x2iedn.32xlarge",
        "u-6tb1.112xlarge",
        "u7i-12tb.224xlarge",
        "mac2-m2pro.metal",
        "p6-b200.48xlarge",
        "Standard_M8-2ms_v2",
        "Standard_M48ds_1_v3",
        "Standard_NV16as_v4",
        "Standard_NC4as_T4_v3",
        "Standard_E96bds_v5",
        "Standard_B2s",
        "m4-hypermem-16",
        "c4a-standard-4-lssd",
        "c3d-highmem-360-lssd",
        "z3-highmem-22-standardlssd",
        "z4d-highmem-96-highlssd",
        "a3-edgegpu-8g-nolssd",
        "c3-highcpu-192-metal",
        "z3-highmem-192-highlssd-metal",
        "z4d-highmem-384-standardlssd-metal",
        # The options f and u of accelerated AWS types, and a processor letter before four others.
        "trn2u.48xlarge",
        "gr6f.4xlarge",
        "g6f.large",
        "x8aedz.12xlarge",
        "u7inh-32tb.480xlarge",
        # Azure sizes with further features and parts, and constrained cores after the features.
        "Standard_DC4as_cc_v5",
        "Standard_M176ds-44_3_v3",
        "Standard_M896ixds_24_v3",
        "Standard_ND96is_flex_H100_v5",
        "Standard_ND96is_noIB_H100_v5",
        "Standard_NC128lds_xl_RTXPRO6000BSE_v6",
        "Standard_NM16ads_MA35D",
        "Standard_D48vds_v7",
        "Standard_E96ias_v5",
        "Standard_D2alds_v6",
        # Google Cloud TPU VM types.
        "ct6e-standard-4t",
        "ct5lp-hightpu-8t",
        "ct5p-hightpu-4t",
        "tpu7x-standard-4t",
    ],
)
def test_a_class_of_machine_in_a_public_form_is_kept(launch_cost: ModuleType, given: str) -> None:
    assert launch_cost.machine_class(given) == given


@pytest.mark.parametrize(
    "given",
    [
        "an eight-core laptop on mains power",
        "markerhost-a",
        "markerhost-a.example.org",
        "build7.lab.internal",
        "web1.large",
        "e2-build",
        "arm64, 4 cores, 16 GB on markerhost-a",
        "192.0.2.7",
        "",
        "m7-zqhost.xlarge",
        "c7gn-zqhost.large",
        "c7i-zqhost.large",
        "u-zqhost.metal",
        "mac2-zqhost.metal",
        "m7zqhost.large",
        "Standard_D4_ZQHOST01",
        "Standard_NC4as_ZQHOST_v3",
        "Standard_D4zqhost_v5",
        "n2-standard-zqhost",
        # Words made only of the option or feature letters, with a letter twice or too many.
        "m7hanna.large",
        "m7edge.large",
        "u7inna-6tb1.112xlarge",
        "Standard_D4berlin",
        "Standard_D4deeds_v5",
        "c3-standard-88-zqhost",
        "c3-standard-88-metal-lssd",
        # A processor letter after another option, two processor letters, an option after f, and
        # more than four options besides the processor letter.
        "m7dang.xlarge",
        "c7ga.large",
        "g6fd.large",
        "trn2uu.48xlarge",
        "m7zqhind.large",
        "m7ibdehn.large",
        # More than four Azure features, and a part of no listed size.
        "Standard_D4prods_v5",
        "Standard_DC4as_zq_v5",
        "Standard_DC4as_cc_zqhost_v5",
        # A TPU VM type with a free word in any of its parts.
        "ct6e-standard-zqhost",
        "ct6e-zqhost-4t",
        "zq6e-standard-4t",
        "tpu7x-standard-4",
    ],
)
def test_a_class_of_machine_outside_the_public_forms_is_refused_before_anything_runs(
    launch_cost: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    run = FakeRun(EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", given], run=run, repo=tmp_path
    )

    assert code == EXIT_USAGE
    assert run.commands == []
    assert capsys.readouterr() == ("", f"{MACHINE_CLASS_REFUSED}\n")
    assert not (tmp_path / KEPT).exists()


@pytest.mark.parametrize(
    "given", ["m7bend.large", "Standard_D4prod_v5", "Standard_E4bird_v5", "Standard_D2lab"]
)
def test_a_short_word_made_only_of_option_letters_fits_as_the_script_says(
    launch_cost: ModuleType, repo_root: Path, given: str
) -> None:
    lines = (repo_root / "tools" / "launch_cost.py").read_text("utf-8").splitlines()
    comments = " ".join(line.strip().removeprefix("#") for line in lines if line.startswith("#"))

    assert launch_cost.machine_class(given) == given
    assert SHORT_WORD_FITS in " ".join(comments.split())


def test_an_image_the_engine_lacks_is_pulled_before_the_wait(
    launch_cost: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / KEPT).mkdir(parents=True)
    run = FakeRun(EXIT_USAGE, EXIT_OK)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path
    )

    assert code == EXIT_OK
    assert run.commands[:2] == [LOOK_UP, PULL]
    assert run.commands[2][3:6] == ["gate", "wait-quiet", "--"]
    assert len(run.commands) == 4


def test_a_failed_pull_stops_before_the_wait(launch_cost: ModuleType, tmp_path: Path) -> None:
    run = FakeRun(EXIT_USAGE, EXIT_LAUNCH)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path
    )

    assert code == EXIT_LAUNCH
    assert run.commands == [LOOK_UP, PULL]


def test_a_failed_run_writes_no_class_of_machine_and_no_hash_inputs(
    launch_cost: ModuleType, tmp_path: Path
) -> None:
    out = tmp_path / KEPT
    out.mkdir(parents=True)
    run = FakeRun(EXIT_OK, EXIT_LAUNCH)

    code = launch_cost.main([str(out), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path)

    assert code == EXIT_LAUNCH
    assert len(run.commands) == 2
    assert not (out / launch_cost.MACHINE_CLASS_FILE).exists()


def test_every_repository_path_the_script_names_exists(
    launch_cost: ModuleType, repo_root: Path
) -> None:
    named = REPOSITORY_PATH.findall(launch_cost.__doc__ or "")
    assert named
    assert [path for path in named if not (repo_root / path).exists()] == []


def test_the_exit_code_of_the_hash_inputs_writer_is_the_script_s(
    launch_cost: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / KEPT).mkdir(parents=True)
    run = FakeRun(EXIT_OK, EXIT_OK, EXIT_MISMATCH)

    code = launch_cost.main(
        [str(tmp_path / KEPT), "--machine-class", MADE_UP_CLASS], run=run, repo=tmp_path
    )

    assert code == EXIT_MISMATCH
    assert len(run.commands) == 3
    assert not (tmp_path / KEPT / launch_cost.MACHINE_CLASS_FILE).exists()


def test_the_script_imports_only_the_standard_library(repo_root: Path) -> None:
    tree = ast.parse((repo_root / "tools" / "launch_cost.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


# The rule for keeping the launch-cost results without their sidecar, which each page that
# says which kept results carry a sidecar says in these words, and what the section on native
# code says of the machine state those results record.
KEEP_RULE = (
    "the launch-cost results are kept without their sidecar because the results hide the two "
    "side commands; the commands are the constants of tools/launch_cost.py, so a reader runs "
    "that script to repeat the run rather than recomputing the hashes."
)
KEEP_RULE_PAGES = (
    "SECURITY.md",
    "CONTRIBUTING.md",
    "docs/reference/results-schema.md",
    "docs/readme/README.in.md",
    "README.md",
)
QUIET_FIRST = (
    "the script waits for a quiet machine on the host before the run starts; inside the "
    "container the run records only what its own checks can see from there."
)
QUIET_FIRST_PAGES = ("docs/readme/README.in.md", "README.md")
MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def words_of(markdown: str) -> str:
    """A Markdown text as its words read: each link as its text, no code marks, one space
    between words, in one case."""
    return " ".join(MARKDOWN_LINK.sub(r"\1", markdown).replace("`", "").split()).casefold()


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("Kept in\n[`tools/x.py`](https://example.invalid/x).", "kept in tools/x.py."),
        ("Two  `words`,\n  Wrapped.", "two words, wrapped."),
    ],
    ids=["a-link", "code-and-lines"],
)
def test_a_page_is_read_as_its_words(text: str, words: str) -> None:
    assert words_of(text) == words


@pytest.mark.parametrize("page", KEEP_RULE_PAGES)
def test_a_page_on_kept_results_says_the_launch_cost_rule_in_its_words(
    repo_root: Path, page: str
) -> None:
    assert KEEP_RULE in words_of((repo_root / page).read_text(encoding="utf-8"))


@pytest.mark.parametrize("page", QUIET_FIRST_PAGES)
def test_the_section_on_native_code_says_the_container_cannot_see_the_quiet_wait(
    repo_root: Path, page: str
) -> None:
    assert QUIET_FIRST in words_of((repo_root / page).read_text(encoding="utf-8"))


def _first_block_after(text: str, heading: str) -> list[str]:
    body = text.split(heading + "\n", 1)[1]
    block = body.split("```\n", 2)[1]
    return [line.split(" # ", 1)[0].strip() for line in block.splitlines() if line.strip()]


# A step that makes a Python environment, with the interpreter it names.
MAKES_AN_ENVIRONMENT = re.compile(r"(?<![\w./-])(python[\w.]*)\s+-m\s+venv\b")
# The interpreter a guide names for that step: the command a Python 3 install provides on
# Linux and macOS, where a plain python command may be missing.
ENVIRONMENT_PYTHON = "python3"
SET_UP_GUIDES = ("AGENTS.md", "CONTRIBUTING.md")


def test_every_guide_makes_the_environment_with_python3(repo_root: Path) -> None:
    named: dict[str, list[str]] = {}
    for path in documents(repo_root):
        text = path.read_text(encoding="utf-8")
        found = [match.group(1) for match in MAKES_AN_ENVIRONMENT.finditer(text)]
        if found:
            named[path.relative_to(repo_root).as_posix()] = found

    assert {name: named.get(name) for name in SET_UP_GUIDES} == {
        name: [ENVIRONMENT_PYTHON] for name in SET_UP_GUIDES
    }
    assert {
        name: found for name, found in named.items() if set(found) != {ENVIRONMENT_PYTHON}
    } == {}


# pairbench started as a module, which runs on the reader's own machine and not inside a side.
STARTS_PAIRBENCH = re.compile(r"(?<![\w./-])(python[\w.]*)\s+-m\s+pairbench\b")


def test_every_page_starts_pairbench_as_a_module_with_python3(repo_root: Path) -> None:
    named: dict[str, list[str]] = {}
    for path in documents(repo_root):
        text = path.read_text(encoding="utf-8")
        found = [match.group(1) for match in STARTS_PAIRBENCH.finditer(text)]
        if any(interpreter != ENVIRONMENT_PYTHON for interpreter in found):
            named[path.relative_to(repo_root).as_posix()] = found

    assert named == {}


def test_the_contributing_guide_runs_every_check_agents_md_runs(repo_root: Path) -> None:
    setup = ("python3 -m venv ", ". .venv/", "pip install ")
    checks = [
        line
        for line in _first_block_after(
            (repo_root / "AGENTS.md").read_text(encoding="utf-8"), "## Set up, test and lint"
        )
        if not line.startswith(setup)
    ]
    guide = _first_block_after(
        (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8"), "## Setting up"
    )

    assert checks
    assert [line for line in checks if line not in guide] == []
