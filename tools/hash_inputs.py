# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Write ``hash_inputs.json`` beside a results file: what each of its hashes is taken over.

A results document shows hashes of each side and of the config: ``argv_sha256``,
``args_sha256`` and ``identify_sha256`` in ``sides[].identity``, ``sides[].fingerprint`` and
``provenance.config_sha256``. Each is the SHA-256 of a value with the recognised secret forms
hidden (``pairbench.model``: ``hashed_argv``, ``hashed_output``, ``fingerprint_inputs`` and
``config_inputs``). The sidecar holds those values, so a reader can recompute these five hashes
with ``pairbench.model`` of the same version and see what each covers::

    {"schema": "pairbench/hash-inputs/v1",
     "sides": {"NAME": {"argv_sha256": [...], "args_sha256": [...],
                        "identify_sha256": "...", "fingerprint": {"identity": ..., "launch": ...}}},
     "provenance": {"config_sha256": [CONFIG, ...]}}

A side's entry holds the hashes its results show, and nothing more. ``config_sha256`` holds one
config per capture the results were made from, in order; several are folded as
``pairbench.model.combine_hashes`` folds them. The values are rebuilt from the run's capture,
which keeps the identity and the config in full, and each is checked against the hash the
results show before anything is written; a value that does not give its hash is refused.

The sidecar is private, as the capture is. It holds the commands, the settings and the output
of the identify commands that the results hide (``results.json`` shows each side's spec as
``KIND:<hidden>``), with only the recognised secret forms hidden. A sidecar can be shared only
when the shared files show each value it holds. A value passes when it is of one of these
kinds (``PASSING_KINDS``), matched exactly, never by its shape and never as a part of a longer
value:

* **Shown values**: a whole value or key of ``results.json``, or a whole word of a text or a
  key of ``results.json`` or of a line of ``results.md`` (split at spaces, and as a shell splits
  it); a published hash is such a value, and so is an image reference ``results.json`` shows;
* **Neutral places**: the neutral places ``/work``, ``/home/user`` and
  ``/usr/local/bin/python3`` (``NEUTRAL_PLACES``). A neutral place passes only as itself; a
  path under one passes only when a shared file shows each of its other parts as a whole word.
  Its ``.`` and ``..`` parts are read to find the place it is under and need not be shown, so
  ``/work/./published`` passes when ``published`` is shown, ``/work/made-up-client/..`` does
  not, and ``/work/../srv`` is under no neutral place. A text that holds a space, a ``:`` or
  another character a path ends at is several values and no place;
* **Schema ids and keys**: the sidecar's schema id, and a key the sidecar, an identity, a
  launch or the config schema is written with, at the place it is written for; a key of a
  table whose keys the user names (a side, a variable, a case) is a value;
* **Config-schema values and config defaults**: a value the config schema lists for its own
  key, at that key's place in a config, and a config value equal to the tool's default at the
  same place;
* **Null, true, false and empty values**: ``null``, a truth value, an empty text, an empty
  list or an empty table, none of which can name a place, a machine or a secret.

A text passes whole or not at all: the output of an identify command, or a mount such as
``/work/a:/data:ro``, passes only when a shared file shows that whole text. The sidecar is
written owner-only (mode 0600) unless it can be shared, and one line says which. Each file the
script writes is filled owner-only beside its place and moved over it once whole, and only then
given the mode of a new file when it may be shared. The file it fills is named
``.NAME.PID.SPACE.RANDOM.tmp``: the file, the number of the process that writes it, a mark of
the process space that number belongs to (twelve hexadecimal digits taken from the boot and
the process-number namespace, all zeros where neither can be read) and a random part. A later
run removes such a file at once when a process of its own process space left it and has
ended, and any such file once it is older than ``STRAY_SECONDS`` (an hour, far longer than a
write takes); it keeps every other one, so that it never removes the file of a run that still
writes, in a container or not. A run whose own file was removed before it was moved into place
exits 2, says so, and changes nothing else.

Usage::

    python tools/hash_inputs.py RUN_FOLDER [--capture FILE ...] [--publish FOLDER]

``RUN_FOLDER`` holds ``results.json`` and, unless ``--capture`` names the captures the results
were made from, ``capture.jsonl``. Exit 0 writes ``RUN_FOLDER/hash_inputs.json`` and says on
standard output that it can be shared, or on standard error that it is private and how many
of its values the shared files do not show, never which.

``--publish FOLDER`` then copies ``results.json``, ``results.md`` and ``report.html`` into
``FOLDER``, and the sidecar with them when it can be shared, and names on standard output what
it copied. When the sidecar cannot be shared it is never copied: it stays owner-only in
``RUN_FOLDER``, one line on standard error names it and says why, and the publish exits 0, so
that a script that publishes a run exits with the run's own code. A file of these that the
publish does not copy is removed from ``FOLDER``, so the folder holds one run's files; the
sidecar of ``RUN_FOLDER`` itself is kept when ``FOLDER`` is that folder.

Exit 1 is a hash its rebuilt value does not give; exit 2 is a missing or unreadable file, or a
``results.json`` that is not a results document. Every other refusal removes the
``hash_inputs.json`` that ``RUN_FOLDER`` held when the run started, and never one that another
run moved in since; a sidecar is written whole or not at all.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import posixpath
import re
import secrets
import shlex
import sys
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from pairbench import model
from pairbench.capture.pool import load_captures
from pairbench.errors import Refusal
from pairbench.model import (
    EXECUTABLE_KEY,
    IDENTIFY_OUTPUT_KEY,
    KIND_CMD,
    KIND_CONDA,
    KIND_FILE,
    KIND_IMAGE,
    KIND_PYTHON,
    KIND_ROWS,
    KIND_SERVE,
    KIND_VENV,
    Capture,
    Experiment,
    LaunchSettings,
    Side,
    canonical_json,
    combine_hashes,
    hashed_argv,
    sha256_hex,
)
from pairbench.sides.command import declared_argv, substitute_workload
from pairbench.sides.container import _effective as image_launch
from pairbench.sides.container import image_spec
from pairbench.sides.serve import LAUNCHER_HOST, serve_spec
from pairbench.sides.serve import _effective as serve_launch

SIDECAR = "hash_inputs.json"
SCHEMA = "pairbench/hash-inputs/v1"
RESULTS = "results.json"
MARKDOWN = "results.md"
CAPTURE = "capture.jsonl"
# The files a publish shares, in this order, when the run wrote them.
SHARED = (RESULTS, MARKDOWN, "report.html")
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2
PRIVATE_MODE = 0o600
# The mode a new file is given before the umask, when it may be shared.
SHARED_MODE = 0o666
# The age past which a file that a write fills is stray whatever its name says: far longer
# than a write takes, so that no run removes the file of a write that still runs.
STRAY_SECONDS = 3600
# The mark of a process space whose boot or process-number namespace cannot be read.
NO_SPACE = "0" * 12
# The neutral places a run that may be shared is made from: the checkout reached at /work, the
# neutral home folder, and the interpreter of the public image. Each passes as itself; a path
# under one passes only when the shared files show each of its other parts.
NEUTRAL_PLACES = ("/work", "/home/user", "/usr/local/bin/python3")
# The kinds of value that may pass, as SECURITY.md lists them.
KIND_SHOWN = "Shown values"
KIND_PLACE = "Neutral places"
KIND_KEY = "Schema ids and keys"
KIND_CONFIG = "Config-schema values and config defaults"
KIND_EMPTY = "Null, true, false and empty values"
PASSING_KINDS = (KIND_SHOWN, KIND_PLACE, KIND_KEY, KIND_CONFIG, KIND_EMPTY)
# A character a path ends at, so that a text holding one is not one place.
_PLACE_END = re.compile(r"[\s:'\",;=()\[\]<>|&\\$`*?{}]")
PRIVATE_LINE = (
    f"{SIDECAR} is private: the shared files do not show {{}} of the values it holds; "
    f"keep it with {CAPTURE}"
)
SHAREABLE_LINE = f"{SIDECAR} holds only what the shared files show; it can be shared"
KEPT_LINE = (
    f"{SIDECAR} is kept private in the run folder, owner-only, and not published: "
    "the shared files do not show {} of the values it holds"
)
FINGERPRINT = "fingerprint"
ARGV = "argv_sha256"
ARGS = "args_sha256"
IDENTIFY = "identify_sha256"
CONFIG = "config_sha256"
PYTHON_KINDS = (KIND_PYTHON, KIND_VENV, KIND_CONDA)
FILE_KINDS = (KIND_FILE, KIND_ROWS)


class Mismatch(Exception):
    """A published hash that the value rebuilt from the capture does not give."""


def launches_of(side: Side, settings: LaunchSettings) -> list[dict[str, Any]]:
    """The effective launch settings a side's kind may have put into its fingerprint.

    A server in a container mounts its model location when that location existed at run
    time, at its absolute path then; so its launch is tried as this machine gives it, without
    the mount, and with the location as written.
    """
    if side.kind == KIND_CMD:
        return [settings.effective(args=declared_argv(side))]
    if side.kind == KIND_IMAGE:
        return [image_launch(settings, image_spec(side))]
    if side.kind in PYTHON_KINDS or side.kind in FILE_KINDS:
        return [settings.effective()]
    if side.kind == KIND_SERVE:
        spec = serve_spec(side)
        if spec.launcher == LAUNCHER_HOST:
            return [serve_launch(settings, spec, LAUNCHER_HOST)]
        found = [serve_launch(settings, spec, "container")]
        mounts: list[tuple[str, ...]] = [()]
        if spec.model:
            mounts.append((f"{spec.model}:{spec.model}:ro",))
        for mount in mounts:
            found.append(settings.effective(args=spec.args, env=spec.env, mounts=mount))
        return found
    raise Mismatch(f"side {side.name}: the kind {side.kind!r} is not one this script rebuilds")


def argv_of(side: Side, experiment: Experiment) -> list[str]:
    """The argument list ``argv_sha256`` of a command side or of a server on the host is over."""
    if side.kind == KIND_CMD:
        return list(substitute_workload(side, declared_argv(side), experiment.workload))
    if side.kind == KIND_SERVE:
        spec = serve_spec(side)
        return [*spec.command, *spec.args]
    raise Mismatch(f"side {side.name}: a {side.kind} side records no argv_sha256")


def hashed_argv_of(side: Side, experiment: Experiment, recorded: Sequence[Side] = ()) -> list[str]:
    """The inputs of the ``argv_sha256`` of a command side or of a server on the host.

    A command side's are its command read with the shared workload as every
    side of the experiment reads it (``pairbench.model.hashed_command``),
    also after what the image of each image side the capture records
    (``recorded``) runs before it.
    """
    if side.kind == KIND_CMD and experiment.workload:
        shared = model.hashed_workload(experiment.workload, experiment.sides, recorded)
        return model.hashed_command(declared_argv(side), experiment.workload, shared)
    return hashed_argv(argv_of(side, experiment))


def args_of(side: Side) -> list[str]:
    """The arguments ``args_sha256`` of a server in a container is over."""
    if side.kind != KIND_SERVE:
        raise Mismatch(f"side {side.name}: a {side.kind} side records no args_sha256")
    return list(serve_spec(side).args)


def _checked(name: str, key: str, inputs: Any, published: Any, digest: Callable[[Any], str]) -> Any:
    if digest(inputs) != published:
        raise Mismatch(
            f"side {name}: the inputs rebuilt from the capture do not give its {key}"
            if name
            else f"the inputs rebuilt from the captures do not give provenance.{key}"
        )
    return inputs


def _json_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))


def side_inputs(
    side: Side,
    experiment: Experiment,
    shown: Mapping[str, Any],
    fingerprint: str,
    recorded: Sequence[Side] = (),
) -> dict[str, Any]:
    """The inputs of each hash a results document shows of one side.

    ``recorded`` are the sides of the capture that records it.
    """
    entry: dict[str, Any] = {}
    identity = shown.get("identity") or {}
    if ARGV in identity:
        inputs = hashed_argv_of(side, experiment, recorded)
        entry[ARGV] = _checked(side.name, ARGV, inputs, identity[ARGV], _json_hash)
    if ARGS in identity:
        inputs = hashed_argv(args_of(side))
        entry[ARGS] = _checked(side.name, ARGS, inputs, identity[ARGS], _json_hash)
    if IDENTIFY in identity:
        output = side.identity.get(IDENTIFY_OUTPUT_KEY)
        if not isinstance(output, str):
            raise Mismatch(f"side {side.name}: the capture keeps no output of its identify command")
        inputs = model.hashed_output(output)
        entry[IDENTIFY] = _checked(side.name, IDENTIFY, inputs, identity[IDENTIFY], sha256_hex)
    candidates = [
        model.fingerprint_inputs(side.identity, launch)
        for launch in launches_of(side, experiment.launch.for_side(side))
    ]
    matching = [inputs for inputs in candidates if _json_hash(inputs) == fingerprint]
    inputs = matching[0] if matching else candidates[0]
    entry[FINGERPRINT] = _checked(side.name, FINGERPRINT, inputs, fingerprint, _json_hash)
    return entry


def _experiment(capture: Capture) -> Experiment:
    try:
        return Experiment.from_json(capture.header.config)
    except Refusal as exc:
        raise Mismatch(
            f"the config of capture {capture.capture_id} cannot be read: {exc}"
        ) from None


def hash_inputs(captures: Sequence[Capture], results: Mapping[str, Any]) -> dict[str, Any]:
    """The sidecar of a results document made from ``captures``, each value checked."""
    if not captures:
        raise Mismatch("no capture was given")
    experiments = [_experiment(capture) for capture in captures]
    sides: dict[str, Any] = {}
    for shown in results.get("sides") or []:
        name = shown.get("name")
        found = [
            (side, experiment, capture)
            for capture, experiment in zip(captures, experiments, strict=True)
            for side in capture.sides
            if side.name == name
        ]
        if not found:
            raise Mismatch(f"side {name}: no capture records it")
        side, experiment, capture = found[0]
        try:
            sides[str(name)] = side_inputs(
                side, experiment, shown, str(shown.get(FINGERPRINT)), capture.sides
            )
        except Refusal as exc:
            raise Mismatch(f"side {name}: its spec cannot be read: {exc}") from None
    out: dict[str, Any] = {"schema": SCHEMA, "sides": sides}
    published = (results.get("provenance") or {}).get(CONFIG)
    if published is not None:
        configs = [
            model.config_inputs(capture.header.config, capture.sides) for capture in captures
        ]
        given = combine_hashes([_json_hash(config) for config in configs])
        _checked("", CONFIG, configs, published, lambda _: str(given))
        out["provenance"] = {CONFIG: configs}
    return out


class NotResults(Exception):
    """A ``results.json`` that is not a results document."""


def results_document(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it has the parts of a results document this script reads."""
    if not isinstance(value, Mapping):
        raise NotResults("it is not a JSON object")
    sides = value.get("sides")
    if not isinstance(sides, list) or not all(isinstance(side, Mapping) for side in sides):
        raise NotResults("its sides are not a list of tables")
    if not sides:
        raise NotResults("it names no side")
    for side in sides:
        if not isinstance(side.get("name"), str):
            raise NotResults("a side has no name")
        if not isinstance(side.get("identity", {}), Mapping):
            raise NotResults(f"the identity of side {side['name']} is not a table")
    if not isinstance(value.get("provenance", {}), Mapping):
        raise NotResults("its provenance is not a table")
    return value


# ---------------------------------------------------------------------------
# Whether the sidecar can be shared: each value it holds is one the shared files show
# ---------------------------------------------------------------------------

IDENTITY_KEYS = frozenset(
    {
        EXECUTABLE_KEY,
        "executable_sha256",
        ARGV,
        ARGS,
        IDENTIFY_OUTPUT_KEY,
        IDENTIFY,
        "python_version",
        "packages_sha256",
        "prefix",
        "selection_env",
        "image_id",
        "digests",
        "platform",
        "files",
        "files_sha256",
    }
)
_MISSING = object()
# A place whose keys and values the sidecar's shape says nothing of.
_FREE: Mapping[str, Any] = {}


def _table(*keys: str, **shapes: Mapping[str, Any]) -> dict[str, Any]:
    """The shape of a table written with ``keys`` and ``shapes``, as a schema writes it."""
    return {"properties": {**dict.fromkeys(keys, _FREE), **shapes}}


# The shape of a sidecar, written as the config schema is written: the keys of each table it is
# written with, under any side's name. A key of a table it does not write out, such as a
# variable of ``env`` or of ``set``, is a value. A config of ``config_sha256`` is read against
# the config schema itself.
SIDECAR_SHAPE = _table(
    "schema",
    sides={
        "additionalProperties": _table(
            ARGV,
            ARGS,
            IDENTIFY,
            fingerprint=_table(
                identity=_table(
                    *sorted(IDENTITY_KEYS - {"selection_env"}),
                    selection_env=_table("set", "unset"),
                ),
                launch=_table(
                    "args",
                    "entrypoint",
                    "env",
                    "env_pass",
                    "mounts",
                    "perf_counters",
                    limits=_table("cpus", "gpus", "memory"),
                ),
            ),
        )
    },
    provenance=_table(CONFIG),
)


class _Schema:
    """The places of a schema: which keys a table there is written with, and what it lists."""

    def __init__(self, root: Mapping[str, Any]) -> None:
        self.definitions = root.get("$defs") or {}

    def expanded(self, nodes: Sequence[Any]) -> list[Mapping[str, Any]]:
        """``nodes`` with each definition they refer to.

        A key or a listed value inside a choice between schemas (``oneOf`` and the like) is
        not read, so it is a value; the config schema writes none there.
        """
        out: list[Mapping[str, Any]] = []
        for node in nodes:
            while isinstance(node, Mapping) and not any(node is seen for seen in out):
                out.append(node)
                ref = node.get("$ref")
                node = self.definitions.get(ref.removeprefix("#/$defs/")) if ref else None
        return out

    def key(self, nodes: Sequence[Any], name: str) -> tuple[bool, list[Any]]:
        """Whether a table at ``nodes`` is written with key ``name``, and the places under it.

        A key no table there is written with is a key the user names, or one of a place the
        schema says nothing of: either way it is a value.
        """
        written = False
        under: list[Any] = []
        for node in self.expanded(nodes):
            properties = node.get("properties")
            if isinstance(properties, Mapping) and name in properties:
                written = True
                under.append(properties[name])
            elif isinstance(node.get("additionalProperties"), Mapping):
                under.append(node["additionalProperties"])
        return written, under

    def items(self, nodes: Sequence[Any]) -> list[Any]:
        """The places of the items of a list at ``nodes``."""
        return [node["items"] for node in self.expanded(nodes) if "items" in node]

    def lists(self, nodes: Sequence[Any], value: str) -> bool:
        """Whether the schema lists ``value`` at ``nodes``: for its own key, at its own place."""
        return any(
            isinstance(node.get("enum"), list) and value in node["enum"]
            for node in self.expanded(nodes)
        )


def _default_config() -> dict[str, Any]:
    """The config of the tool's defaults, without a side."""
    config = Experiment.from_json({"sides": {"made-up": {"cmd": ["true"]}}}).to_json()
    config.pop("sides", None)
    return config


def neutral_place(text: str, shown: Collection[str] = ()) -> bool:
    """Whether a text is a neutral place, or a path under one whose other parts are ``shown``.

    The places are compared by path components once the ``.`` and ``..`` parts are read:
    ``/workspace`` is not under ``/work``, a longer folder name that starts with ``user`` is not
    under ``/home/user``, and a path whose ``..`` leaves ``/work`` for another folder is under
    neither. Each part of the text as written, other than ``.``, ``..`` and the place's own
    leading parts, must be in ``shown``: ``/work`` passes, ``/work/made-up-client/run`` passes
    only when both ``made-up-client`` and ``run`` are shown, and so does
    ``/work/made-up-client/../run``. A text that holds a character a path ends at (a space,
    ``:``, ``,``, ``=`` and the like) is several values, not one place: ``/work/a:/srv/b`` is
    no neutral place.
    """
    if not text.startswith("/") or text.startswith("//") or _PLACE_END.search(text):
        return False
    path = posixpath.normpath(text)
    written = [part for part in text.split("/") if part not in ("", ".")]
    for place in NEUTRAL_PLACES:
        if path != place and not path.startswith(place + "/"):
            continue
        own = place.split("/")[1:]
        rest = written[len(own) :] if written[: len(own)] == own else written
        if all(part == ".." or part in shown for part in rest):
            return True
    return False


def _words(text: str) -> Iterator[str]:
    """A text, its words split at spaces, and its words as a shell splits them."""
    yield text
    yield from text.split()
    with contextlib.suppress(ValueError):
        yield from shlex.split(text)


class Shown:
    """The values the shared files show: whole values, words and numbers."""

    def __init__(self, results: Any, markdown: str) -> None:
        self.words: set[str] = set()
        self.numbers: set[float] = set()
        self._read(results)
        for line in markdown.splitlines():
            self.words.update(_words(line))

    def _read(self, value: Any) -> None:
        if isinstance(value, str):
            self.words.update(_words(value))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self.numbers.add(float(value))
        elif isinstance(value, Mapping):
            for key, item in value.items():
                self.words.update(_words(str(key)))
                self._read(item)
        elif isinstance(value, list):
            for item in value:
                self._read(item)

    def kind(self, text: str) -> str | None:
        """The kind a text passes as: a shown value or word, or a neutral place; else ``None``."""
        if text in self.words:
            return KIND_SHOWN
        if neutral_place(text, self.words):
            return KIND_PLACE
        return None

    def number(self, value: float) -> bool:
        """Whether a number is one the shared files show, as a number or as a word."""
        return float(value) in self.numbers or json.dumps(value) in self.words


def _at(tree: Any, path: Sequence[str | int]) -> Any:
    """The value at ``path`` in ``tree``, or ``_MISSING``."""
    for part in path:
        found = isinstance(tree, Mapping) and isinstance(part, str) and part in tree
        if not found and not (
            isinstance(tree, list) and isinstance(part, int) and part < len(tree)
        ):
            return _MISSING
        tree = tree[part]
    return tree


def _text(value: Any) -> str:
    """A value as it is listed: a text as itself, an empty text and anything else as JSON."""
    return value if isinstance(value, str) and value else json.dumps(value, sort_keys=True)


class _Check:
    """Each value of a sidecar, sorted into the kind that lets it pass or the hidden ones."""

    def __init__(self, results: Any, markdown: str) -> None:
        from pairbench.results import load_schema

        self.shown = Shown(results, markdown)
        self.config = load_schema("config")
        self.schema = _Schema(self.config)
        self.defaults = _default_config()
        self.hidden: set[str] = set()
        self.passed: dict[str, set[str]] = {kind: set() for kind in PASSING_KINDS}

    def kind(
        self, value: Any, path: tuple[str | int, ...], places: Sequence[Any], config: bool
    ) -> str | None:
        """The kind a whole value at ``places`` passes as, or ``None`` if it does not pass whole."""
        default = _at(self.defaults, path) if config else _MISSING
        if value is not None and type(default) is type(value) and default == value:
            return KIND_CONFIG
        if value is None or isinstance(value, bool) or value in ("", [], {}):
            return KIND_EMPTY
        if isinstance(value, (int, float)):
            return KIND_SHOWN if self.shown.number(value) else None
        if isinstance(value, str):
            if self.schema.lists(places, value):
                return KIND_CONFIG
            return self.shown.kind(value)
        return None

    def walk(
        self, value: Any, path: tuple[str | int, ...], places: Sequence[Any], config: bool
    ) -> None:
        """Sort ``value``, at ``places`` of the sidecar's shape or the config schema."""
        kind = self.kind(value, path, places, config)
        if kind is not None:
            self.passed[kind].add(_text(value))
        elif isinstance(value, Mapping):
            for key, item in value.items():
                name = str(key)
                written, under = self.schema.key(places, name)
                named = KIND_KEY if written else self.shown.kind(name)
                if named is None:
                    self.hidden.add(name)
                else:
                    self.passed[named].add(name)
                self.walk(item, (*path, name), under, config)
        elif isinstance(value, list):
            items = self.schema.items(places)
            for index, item in enumerate(value):
                self.walk(item, (*path, index), items, config)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self.hidden.add(json.dumps(value))
        elif isinstance(value, str):
            self.hidden.add(value)
        else:
            self.hidden.add(repr(value))


def _checked_sidecar(results: Any, markdown: str, sidecar: Mapping[str, Any]) -> _Check:
    check = _Check(results, markdown)
    for key, value in sidecar.items():
        if key == "schema":
            if value == SCHEMA:
                check.passed[KIND_KEY].add(SCHEMA)
            else:
                check.hidden.add(str(value))
        elif key == "provenance" and isinstance(value, Mapping):
            _written, provenance = check.schema.key([SIDECAR_SHAPE], key)
            for name, configs in value.items():
                if name != CONFIG or not isinstance(configs, list):
                    check.walk({name: configs}, (), provenance, False)
                    continue
                check.passed[KIND_KEY].update((key, name))
                for config in configs:
                    check.walk(config, (), [check.config], True)
        else:
            check.walk({key: value}, (), [SIDECAR_SHAPE], False)
    return check


def hidden_values(results: Any, markdown: str, sidecar: Mapping[str, Any]) -> list[str]:
    """Each value of a sidecar that ``results.json`` and ``results.md`` do not show, once.

    A value is matched exactly, as the module's docstring says: never by its shape, and never
    as a part of a longer value. The values are returned so that they can be counted; nothing
    prints them.
    """
    return sorted(_checked_sidecar(results, markdown, sidecar).hidden)


def passing(results: Any, markdown: str, sidecar: Mapping[str, Any]) -> dict[str, list[str]]:
    """Each value and key of a sidecar that passes, under the kind of ``PASSING_KINDS`` it is.

    A value that is not text is given as JSON. Like ``hidden_values``, nothing prints them.
    """
    check = _checked_sidecar(results, markdown, sidecar)
    return {kind: sorted(check.passed[kind]) for kind in PASSING_KINDS}


# ---------------------------------------------------------------------------
# Writing and publishing
# ---------------------------------------------------------------------------


class TemporaryGone(OSError):
    """The file a write filled was removed by another run before it was moved into place."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"the file this run filled for {name} was removed before it was moved into place"
        )


def _space() -> str:
    """The mark of this process's process space: the boot and the process-number namespace.

    Two processes with one mark number their processes alike, so the number in a file name
    tells whether its writer runs. Every live namespace has its own number, and the boot sets
    the count apart from an earlier one. ``NO_SPACE`` where either cannot be read.
    """
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        namespace = os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        return NO_SPACE
    return hashlib.sha256(f"{boot}:{namespace}".encode()).hexdigest()[:12]


def _token() -> str:
    """The random part of the name of one write's file."""
    return secrets.token_hex(8)


def _temporary(path: Path, pid: int, space: str, token: str) -> Path:
    """The file a write of ``path`` fills before it moves it over ``path``."""
    return path.with_name(f".{path.name}.{pid}.{space}.{token}.tmp")


def _running(pid: int) -> bool:
    """Whether a process of this number runs; one that another user runs counts."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError):
        return False
    return True


def _stray(path: Path, found: re.Match[str], space: str, looked: float) -> bool:
    """Whether the file ``path`` that a write filled was left by a writer that has ended.

    Any such file older than ``STRAY_SECONDS`` is stray. A younger one is stray only when its
    name holds this process space's mark and the number of a process of this space that has
    ended; the number in a name of another space, or of none, tells nothing here. A file with
    this process's number is stray: this process has not started its write of ``path`` when
    this runs, so an ended process with the same number left it.
    """
    try:
        age = looked - os.lstat(path).st_mtime
    except OSError:
        return False
    if age > STRAY_SECONDS:
        return True
    pid, mark = int(found.group(1)), found.group(2)
    if mark is None or mark != space or space == NO_SPACE:
        return False
    return pid == os.getpid() or not _running(pid)


def _remove_left(path: Path) -> None:
    """Remove each file beside ``path`` that a write of ``path`` filled and left stray.

    Only a name of the form ``_temporary`` gives, or of the shorter form ``.NAME.PID.tmp``, is
    looked at; ``_stray`` says which of them are removed.
    """
    left = re.compile(
        rf"\.{re.escape(path.name)}\.([0-9]{{1,10}})(?:\.([0-9a-f]{{12}})\.[0-9a-f]{{16}})?\.tmp"
    )
    try:
        names = os.listdir(path.parent)
    except OSError:
        return
    space, looked = _space(), time.time()
    for name in names:
        found = left.fullmatch(name)
        if found is not None and _stray(path.parent / name, found, space, looked):
            with contextlib.suppress(OSError):
                os.unlink(path.parent / name)


def _write_whole(path: Path, data: bytes, *, private: bool) -> None:
    """Write a file whole or not at all: into a new file beside it, then moved over it.

    The new file is owner-only (mode 0600) while it is written. One that may be shared is given
    the mode of a new file under the umask only once it has replaced ``path``, so no reader sees
    it before it is whole, and a write that is killed leaves an owner-only file, which a later
    write of ``path`` removes once ``_stray`` says so. When another run removed the new file
    before it was moved, ``TemporaryGone`` is raised and nothing else is changed.
    """
    _remove_left(path)
    temporary = _temporary(path, os.getpid(), _space(), _token())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_MODE)
    try:
        os.fchmod(descriptor, PRIVATE_MODE)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            try:
                os.replace(temporary, path)
            except FileNotFoundError:
                if os.fstat(stream.fileno()).st_nlink == 0:
                    raise TemporaryGone(path.name) from None
                raise
            if not private:
                os.fchmod(stream.fileno(), SHARED_MODE & ~_umask())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _encoded(sidecar: Mapping[str, Any]) -> bytes:
    return (json.dumps(sidecar, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_results(folder: Path) -> Mapping[str, Any]:
    return results_document(json.loads((folder / RESULTS).read_text(encoding="utf-8")))


def _markdown(folder: Path) -> str:
    path = folder / MARKDOWN
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def write(folder: Path, captures: Sequence[Path] | None = None) -> tuple[Path, list[str]]:
    """Write the sidecar of the results in ``folder``; return its path and its unshown values.

    It is written owner-only when the shared files do not show a value it holds.
    """
    results = _read_results(folder)
    loaded = load_captures(list(captures) if captures else [folder / CAPTURE])
    sidecar = hash_inputs(loaded, results)
    hidden = hidden_values(results, _markdown(folder), sidecar)
    path = folder / SIDECAR
    _write_whole(path, _encoded(sidecar), private=bool(hidden))
    return path, hidden


def publish(folder: Path, into: Path, *, sidecar: bool = True) -> list[str]:
    """Copy the shared files of ``folder`` into ``into``, and its sidecar when ``sidecar``.

    Return the names copied. A file of ``SHARED`` that the run did not write, and the sidecar
    when it is not copied, are removed from ``into``, so the folder holds one run's files. When
    ``into`` is ``folder`` itself, the sidecar there is the run's own and is kept.
    """
    into.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for name in (*SHARED, SIDECAR):
        source = folder / name
        if source.is_file() and (sidecar or name != SIDECAR):
            _write_whole(into / name, source.read_bytes(), private=False)
            names.append(name)
        elif name != SIDECAR or not _same_folder(folder, into):
            _remove_left(into / name)
            with contextlib.suppress(FileNotFoundError):
                (into / name).unlink()
    return names


def _same_folder(one: Path, other: Path) -> bool:
    """Whether two paths name one folder, through a link or not."""
    try:
        return os.path.samefile(one, other)
    except OSError:
        return False


def _listed(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _identity(path: Path) -> tuple[int, int, int, int] | None:
    """What tells the file at ``path`` from one moved over it later; ``None`` when there is none."""
    try:
        found = os.lstat(path)
    except OSError:
        return None
    return (found.st_dev, found.st_ino, found.st_mtime_ns, found.st_size)


def _refused(
    folder: Path, message: str, code: int, earlier: tuple[int, int, int, int] | None
) -> int:
    """Remove the earlier sidecar of ``folder``, say why nothing was written, and give ``code``.

    ``earlier`` is ``_identity`` of the sidecar when the run started: only that file is
    removed, never one that another run moved in since. The stray files writes of the sidecar
    left are removed too.
    """
    _remove_left(folder / SIDECAR)
    if earlier is not None and _identity(folder / SIDECAR) == earlier:
        with contextlib.suppress(FileNotFoundError, IsADirectoryError, NotADirectoryError):
            (folder / SIDECAR).unlink()
    print(message, file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Write the sidecar of one run folder; see the module's docstring for the exit codes."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("folder", type=Path, help="the run folder that holds results.json")
    parser.add_argument(
        "--capture",
        action="append",
        type=Path,
        default=[],
        help="a capture the results were made from (repeat, in order)",
    )
    parser.add_argument(
        "--publish",
        type=Path,
        default=None,
        metavar="FOLDER",
        help="copy the shared files into FOLDER, and the sidecar only when it can be shared",
    )
    options = parser.parse_args(argv)
    folder: Path = options.folder
    earlier = _identity(folder / SIDECAR)
    needed = [folder / RESULTS, *(options.capture or [folder / CAPTURE])]
    missing = [path.name for path in needed if not path.is_file()]
    if missing:
        message = f"the folder {folder.name} has no {', '.join(missing)}"
        return _refused(folder, message, EXIT_USAGE, earlier)
    try:
        _path, hidden = write(folder, options.capture)
    except TemporaryGone as exc:
        print(f"no {SIDECAR} written: {exc}; nothing else was changed", file=sys.stderr)
        return EXIT_USAGE
    except NotResults as exc:
        message = f"no {SIDECAR} written: {RESULTS} is not a results document: {exc}"
        return _refused(folder, message, EXIT_USAGE, earlier)
    except Mismatch as exc:
        return _refused(folder, f"no {SIDECAR} written: {exc}", EXIT_MISMATCH, earlier)
    except (OSError, ValueError, Refusal) as exc:
        return _refused(folder, f"no {SIDECAR} written: {exc}", EXIT_USAGE, earlier)
    into: Path | None = options.publish
    if into is None:
        if hidden:
            print(PRIVATE_LINE.format(len(hidden)), file=sys.stderr)
        else:
            print(SHAREABLE_LINE)
        return EXIT_OK
    try:
        names = publish(folder, into, sidecar=not hidden)
    except OSError as exc:
        print(f"nothing published: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"published {_listed(names)} into {into.name}")
    if hidden:
        print(KEPT_LINE.format(len(hidden)), file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
