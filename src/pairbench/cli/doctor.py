# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench doctor``: what this machine supports, what is found and what is degraded.

``collect`` gathers the document ``pairbench doctor --json`` prints: the
external programs found, what each side kind, driver and machine check
reports about itself (``api.Diagnosable``), the plug-ins that failed to
load, the containers runs left behind, the drivers that are experimental,
the instruments of the explain step that can run here, and whether the
``plot`` extra is installed. Nothing is started, pulled or changed. A part
that cannot be asked is reported as such; the command always exits 0.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
from collections.abc import Mapping
from typing import Any, Final

from pairbench.cli.common import emit
from pairbench.errors import EXIT_OK, printable

# The plug-in groups asked for a report, and the word each is shown under.
GROUPS: Final[tuple[tuple[str, str], ...]] = (
    ("pairbench.side_kinds", "side_kinds"),
    ("pairbench.drivers", "drivers"),
    ("pairbench.gates", "gates"),
    ("pairbench.capture_readers", "capture_readers"),
    ("pairbench.reporters", "reporters"),
    ("pairbench.launchers", "launchers"),
)
NOT_ASKED: Final = "unavailable"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``--json`` prints the document instead of the lines."""
    parser.add_argument("--json", action="store_true", help="print the document as JSON")
    parser.add_argument("--no-plugins", action="store_true", dest="no_plugins")


def _plain(value: Any) -> Any:
    """Return the value as JSON holds it: text keys, lists, text, finite numbers.

    A plug-in's detail can hold any object; anything else becomes its text,
    a set becomes a sorted list.
    """
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)


def _report(status: str, summary: str, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"status": str(status), "summary": str(summary), "detail": _plain(dict(detail or {}))}


def _failed(error: BaseException) -> dict[str, Any]:
    return _report(NOT_ASKED, f"could not be asked ({type(error).__name__})")


def _plugin_reports(group: str) -> dict[str, dict[str, Any]]:
    """Ask each plug-in of a group that has something to tell for its report."""
    from pairbench import api, registry

    reports: dict[str, dict[str, Any]] = {}
    for name in registry.names(group):
        try:
            plugin = registry.get(group, name)
            if not isinstance(plugin, api.Diagnosable):
                reports[name] = _report("ok", "loaded")
                continue
            found = plugin.doctor()
            reports[name] = _report(found.status, found.summary, found.detail)
        except Exception as error:
            reports[name] = _failed(error)
    return reports


def _tools() -> list[dict[str, Any]]:
    from pairbench.api import MakeFacts, delegate

    make_facts: MakeFacts = delegate("facts")
    return [
        {"name": t.name, "found": t.found, "version": t.version, "note": t.note}
        for t in make_facts().tools()
    ]


def _instruments(environ: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    from pairbench.api import InstrumentReports, delegate

    reports: InstrumentReports = delegate("instruments")
    return {
        name: _report(found.status, found.summary, found.detail)
        for name, found in reports(environ).items()
    }


def collect(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the document ``pairbench doctor --json`` prints (``api.CollectDoctor``)."""
    from pairbench import api, registry
    from pairbench.model import TOOL_NAME, TOOL_VERSION

    env = dict(os.environ if environ is None else environ)
    document: dict[str, Any] = {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "python": platform.python_version(),
        "system": platform.system(),
        "ci": api.is_ci(env),
    }
    try:
        document["tools"] = _tools()
    except Exception as error:
        document["tools"] = []
        document["tools_error"] = _failed(error)["summary"]
    for group, word in GROUPS:
        try:
            document[word] = _plugin_reports(group)
        except Exception as error:
            document[word] = {"": _failed(error)}
    try:
        document["instruments"] = _instruments(env)
    except Exception as error:
        document["instruments"] = {"": _failed(error)}
    document["plot_extra"] = {"installed": api.plot_extra_installed()}
    document["plugins"] = {
        "enabled": registry.plugins_enabled(),
        "loaded": registry.counts().loaded,
        "failed": [failure.text for failure in registry.failures()],
    }
    document["degraded"] = [
        f"{word} {name}: {report['summary']}"
        for _group, word in (*GROUPS, ("", "instruments"))
        for name, report in document[word].items()
        if report["status"] in ("degraded", NOT_ASKED)
    ]
    document["experimental"] = [
        name for name, report in document["drivers"].items() if report["status"] == "experimental"
    ]
    document["leftover_containers"] = [
        str(container)
        for report in document["side_kinds"].values()
        for container in report["detail"].get("leftover_containers", [])
    ]
    return document


def _lines(document: Mapping[str, Any]) -> list[str]:
    lines = [
        f"{document['tool']['name']} {document['tool']['version']} on Python "
        f"{document['python']}, {document['system']}"
        + (", in an automated pipeline" if document["ci"] else ""),
        "",
        "external programs:",
    ]
    for tool in document["tools"]:
        state = f"found {tool['version'] or ''}".rstrip() if tool["found"] else "not found"
        note = f" ({tool['note']})" if tool.get("note") and tool["found"] else ""
        lines.append(f"  {tool['name']}: {state}{note}")
    for _group, word in (*GROUPS, ("", "instruments")):
        lines += ["", f"{word.replace('_', ' ')}:"]
        for name, report in document[word].items():
            lines.append(f"  {name or '(all)'}: {report['status']}: {report['summary']}")
    extra = "installed" if document["plot_extra"]["installed"] else "not installed"
    lines += ["", f"plot extra: {extra}"]
    plugins = document["plugins"]
    lines.append(
        f"plug-ins: {'on' if plugins['enabled'] else 'off'}, {plugins['loaded']} loaded, "
        f"{len(plugins['failed'])} failed to load"
    )
    lines += [f"  {printable(text)}" for text in plugins["failed"]]
    if document["leftover_containers"]:
        lines.append("containers left behind by runs:")
        lines += [f"  {name}" for name in document["leftover_containers"]]
    if document["experimental"]:
        lines.append(f"experimental drivers: {', '.join(document['experimental'])}")
    if document["degraded"]:
        lines.append("degraded or unavailable:")
        lines += [f"  {line}" for line in document["degraded"]]
    return lines


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench doctor``. It always exits 0."""
    from pairbench import registry

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    try:
        document = collect()
        text = json.dumps(document, indent=2) if options.json else "\n".join(_lines(document))
    except Exception as error:
        document = {"error": f"the machine could not be described ({type(error).__name__})"}
        text = json.dumps(document, indent=2) if options.json else document["error"]
    emit(text)
    return EXIT_OK


__all__ = ["GROUPS", "add_arguments", "collect", "command"]
