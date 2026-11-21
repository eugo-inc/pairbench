# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench fill``: fill a document's figure tokens from results files.

``pairbench fill TEMPLATE [--results results.json] [--results NAME=other.json] -o OUT``

Without ``--results`` no figure is known: a template without tokens is
written as it is, and any token is a missing figure. The document is
written as bytes, so the line endings of the template are
kept as they are. With ``--check`` nothing is written: the filled document
is compared, byte for byte, with the output file, and a difference, or an
output file that does not exist, is exit code 1.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pairbench.cli.common import say
from pairbench.cli.pipes import write_bytes
from pairbench.errors import EXIT_CHECK_FAILED, EXIT_OK, Refusal

if TYPE_CHECKING:
    from pairbench.model import Results

# A results name: the text before ``=`` in ``--results NAME=PATH``.
RESULTS_NAME = re.compile(r"[A-Za-z0-9_.-]+")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The template, ``--results`` (repeat), ``-o`` and ``--check``."""
    parser.add_argument("template", metavar="TEMPLATE", help="the document with figure tokens")
    parser.add_argument(
        "--results",
        action="append",
        default=[],
        metavar="[NAME=]FILE",
        help="a results file; with several, each but one is named (repeat)",
    )
    parser.add_argument("-o", "--output", metavar="OUT", help="the filled document")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the output file instead of writing it; a difference is exit 1",
    )


def split_results(texts: list[str]) -> dict[str, Path]:
    """Read the ``--results`` texts: ``NAME=PATH`` names a file; a plain path is unnamed.

    A name is letters, digits, ``_``, ``.`` and ``-``. Two unnamed files, or
    one name given twice, are ``E_USAGE``.
    """
    files: dict[str, Path] = {}
    for text in texts:
        name, eq, rest = text.partition("=")
        if eq and rest and RESULTS_NAME.fullmatch(name) and not Path(text).exists():
            key, path = name, rest
        else:
            key, path = "", text
        if key in files:
            which = f"the name {key!r}" if key else "more than one results file without a name"
            raise Refusal("E_USAGE", f"--results gives {which}")
        files[key] = Path(path)
    return files


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench fill``."""
    import pairbench

    if options.check and not options.output:
        raise Refusal("E_USAGE", "--check compares with the output file: give -o OUT")
    files = split_results(options.results)
    loaded: dict[str, Results] = {
        name: pairbench.load_results(path) for name, path in files.items()
    }
    template = Path(options.template)
    if not template.is_file():
        raise Refusal("E_USAGE", f"the template {template.name} is not a file")
    try:
        text = template.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("E_USAGE", f"the template {template.name} is not UTF-8 text") from exc
    except OSError as exc:
        raise Refusal("E_USAGE", f"cannot read {template.name}: {exc.strerror or exc}") from exc
    filled = pairbench.fill(text, loaded).encode("utf-8")
    if options.output is None:
        write_bytes(filled)
        return EXIT_OK
    out = Path(options.output)
    if options.check:
        try:
            current = out.read_bytes()
        except FileNotFoundError:
            say(f"fill --check: {out.name} does not exist")
            return EXIT_CHECK_FAILED
        except OSError as exc:
            raise Refusal("E_USAGE", f"cannot read {out.name}: {exc.strerror or exc}") from exc
        if current != filled:
            say(f"fill --check: {out.name} does not match its results")
            return EXIT_CHECK_FAILED
        return EXIT_OK
    try:
        out.write_bytes(filled)
    except OSError as exc:
        raise Refusal("E_USAGE", f"cannot write {out.name}: {exc.strerror or exc}") from exc
    return EXIT_OK


__all__ = ["add_arguments", "command", "split_results"]
