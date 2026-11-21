# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The results document: its JSON Schemas, its writer and its figures.

The JSON Schemas of the capture, the results document, the config and the
diagnostics document ship with the package under ``schema/``.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Final

SCHEMA_NAMES: Final[tuple[str, ...]] = ("capture", "results", "config", "diagnostics")


def schema_text(name: str) -> str:
    """Return a shipped JSON Schema as text.

    ``name`` is ``capture``, ``results``, ``config`` or ``diagnostics``.
    """
    if name not in SCHEMA_NAMES:
        raise ValueError(f"no schema named {name!r}; there are {', '.join(SCHEMA_NAMES)}")
    file = resources.files(__name__).joinpath("schema", f"{name}.v1.schema.json")
    return file.read_text(encoding="utf-8")


def load_schema(name: str) -> dict[str, Any]:
    """Return a shipped JSON Schema as a dict."""
    loaded: dict[str, Any] = json.loads(schema_text(name))
    return loaded
