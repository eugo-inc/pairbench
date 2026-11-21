# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Resolve the config of an experiment from the file, the environment and the command line.

Precedence, highest first: the command line (its flags and ``--set``), the
environment, the config file, the defaults. No config file is picked up by
itself: only a path given to ``load_experiment`` or the variable
``PAIRBENCH_CONFIG`` loads one, because a config launches commands.

Every source is turned into leaves, one per config key, before it is laid
over the sources below it. A leaf names its key by the parts of its dotted
path; the strict reading of the merged config is ``Experiment.from_json``,
which refuses an unknown key or a bad value with ``E_CONFIG``.

An experiment whose sides all serve gets the load levels 1, 8 and 32
requests in flight when it names no levels and counts concurrency, and
levels of 60 s each when it names no length; a driver whose levels send a
number of prompts (``vllm-bench``) gets no length.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pairbench.errors import Refusal
from pairbench.model import (
    CPU_LIST_PATTERN,
    FLAG_KEYS,
    KIND_CMD,
    KIND_CONDA,
    KIND_FILE,
    KIND_IMAGE,
    KIND_PYTHON,
    KIND_SERVE,
    KIND_VENV,
    MAX_CPU,
    Experiment,
    Side,
    match_config_key,
    parse_duration,
)

# The load levels of a serving experiment that names none: requests in flight.
SERVING_LEVELS: Final[tuple[int, ...]] = (1, 8, 32)
# The length of each load level of a serving experiment that names none, in seconds.
SERVING_LEVEL_DURATION_S: Final = 60.0
# Load drivers whose level sends a number of prompts and takes no length.
PROMPT_COUNTED_DRIVERS: Final[frozenset[str]] = frozenset({"vllm-bench"})

CONFIG_VARIABLE: Final = "PAIRBENCH_CONFIG"
OUT_VARIABLE: Final = "PAIRBENCH_OUT"
# An environment variable that starts with this sets one config key.
OVERRIDE_PREFIX: Final = "PAIRBENCH__"
OVERRIDE_SEPARATOR: Final = "__"

# The keys of a side that say what kind of side it is; a side has exactly one.
SIDE_KIND_KEYS: Final[tuple[str, ...]] = (
    "image",
    "cmd",
    "python",
    "venv",
    "conda",
    "serve",
    "file",
    "kind",
)
# The keys of a side that stay when a higher source makes it another kind.
SIDE_SHARED_KEYS: Final[tuple[str, ...]] = ("baseline", "launch")

# The keys whose value is a duration: two texts of one duration are one value.
DURATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "run.budget",
        "workload.level_duration",
        "launch.timeout",
        "sides.NAME.launch.timeout",
        "sides.NAME.serve.ready.timeout",
        "gates.lock_timeout",
    }
)
# The keys whose value is a CPU list: two lists of one set of CPUs are one value.
CPU_LIST_KEYS: Final[frozenset[str]] = frozenset({"launch.cpus", "sides.NAME.launch.cpus"})
_CPU_LIST: Final = re.compile(CPU_LIST_PATTERN, re.ASCII)

# Flags that may be given more than once; their values form a list.
REPEATED_FLAGS: Final[frozenset[str]] = frozenset({"--case", "--lock", "--fail-on"})
# Flags that take no value: given means true.
SWITCH_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--rounds-exact",
        "--quick",
        "--vary-env-size",
        "--allow-underpowered",
        "--allow-identical",
        "--wait-quiet",
        "--allow-mixed-core-types",
        "--print-plan",
        "--json",
        "--no-plugins",
    }
)
# Flags whose value is a whole number, or a word the key also accepts.
NUMBER_FLAGS: Final[frozenset[str]] = frozenset({"--rounds", "--warmups"})

Leaf = tuple[tuple[str, ...], Any]


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def parse_value(text: str) -> Any:
    """Read a value as written after ``--set KEY=`` or in an environment override.

    The text is a TOML value when ``v = <text>`` parses as a TOML document
    holding that one key, and the text itself otherwise: ``24`` is a number,
    ``[1, 8]`` a list, ``true`` a boolean, ``myorg/app:2.1`` and ``4-7`` are
    texts. A text that would make a second key is kept as a text.
    """
    try:
        data = tomllib.loads(f"v = {text}")
    except (tomllib.TOMLDecodeError, ValueError):
        return text
    if set(data) != {"v"}:
        return text
    return data["v"]


def _cpu_set(value: Any) -> frozenset[int]:
    """Read a CPU list such as ``0-3`` or ``0,1,2,3`` as the set of CPUs it names.

    A number is the list of that one CPU. A value that is no CPU list, a
    range that runs backwards, or a CPU above ``MAX_CPU`` raises
    ``ValueError``; the bound is checked before any range is expanded.
    """
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(text, str) or not _CPU_LIST.fullmatch(text):
        raise ValueError("not a CPU list")
    cpus: set[int] = set()
    for part in text.split(","):
        low, _sep, high = part.partition("-")
        first, last = int(low), int(high or low)
        if last < first or last > MAX_CPU:
            raise ValueError("not a CPU list")
        cpus.update(range(first, last + 1))
    return frozenset(cpus)


def _differ(key: str, first: Any, second: Any) -> bool:
    """Say whether two values of one key differ.

    Durations are compared in seconds and CPU lists as the sets of CPUs they
    name, so ``0-3`` and ``0,1,2,3`` are one value.
    """
    if key in DURATION_KEYS:
        try:
            return parse_duration(first) != parse_duration(second)
        except (TypeError, ValueError):
            pass
    if key in CPU_LIST_KEYS:
        try:
            return _cpu_set(first) != _cpu_set(second)
        except ValueError:
            pass
    if isinstance(first, bool) != isinstance(second, bool):
        return True
    return bool(first != second)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def read_file(path: Path) -> dict[str, Any]:
    """Read a config file. A file that cannot be read or is no TOML is ``E_CONFIG``."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise Refusal(
            "E_CONFIG", f"cannot read the config file {Path(path).name}: {exc.strerror or exc}"
        ) from exc
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise Refusal(
            "E_CONFIG", f"the config file {Path(path).name} is not valid TOML: {exc}"
        ) from exc


def environment_leaves(environ: Mapping[str, str]) -> list[Leaf]:
    """Read the config keys the environment sets.

    ``PAIRBENCH__RUN__ROUNDS=24`` sets ``run.rounds``; the parts of the path
    are lower-cased and the value is read by ``parse_value``. A variable
    that names no key is ``E_CONFIG``, and so is one that would set a single
    name inside a table of variables (``PAIRBENCH__LAUNCH__ENV__X``): the
    name would be lower-cased, so the whole table is set instead.
    ``PAIRBENCH_OUT`` sets ``run.out`` as it is written.
    """
    leaves: list[Leaf] = []
    for name in sorted(environ):
        if not name.startswith(OVERRIDE_PREFIX):
            continue
        parts = tuple(part.lower() for part in name[len(OVERRIDE_PREFIX) :].split("__"))
        if not all(parts):
            raise Refusal("E_CONFIG", f"the variable {name} names no config key")
        try:
            key, found = match_config_key(".".join(parts))
        except Refusal:
            raise Refusal("E_CONFIG", f"the variable {name} names no config key") from None
        if len(found) > len(key.split(".")):
            table = OVERRIDE_PREFIX + OVERRIDE_SEPARATOR.join(p.upper() for p in parts[:-1])
            raise Refusal(
                "E_CONFIG",
                f"the variable {name} sets one name inside {key}, and the parts of an "
                "environment override are lower-cased, which would change that name; "
                f"set the whole table instead, as {table}='{{ NAME = \"...\" }}'",
            )
        leaves.append((found, parse_value(environ[name])))
    out = environ.get(OUT_VARIABLE)
    if out:
        given = [value for parts, value in leaves if parts == ("run", "out")]
        if given and given[0] != out:
            raise Refusal(
                "E_CONFIG",
                f"{OUT_VARIABLE} and {OVERRIDE_PREFIX}RUN__OUT name different output folders",
            )
        if not given:
            leaves.append((("run", "out"), out))
    return leaves


def set_leaves(sets: Iterable[str]) -> list[Leaf]:
    """Read ``KEY=VALUE`` texts as written after ``--set``.

    The key is matched with ``match_config_key`` (``E_CONFIG`` when it names
    no key) and the value is read by ``parse_value``. A text without ``=``
    is ``E_USAGE``.
    """
    leaves: list[Leaf] = []
    for text in sets:
        key, eq, value = text.partition("=")
        if not eq or not key:
            raise Refusal("E_USAGE", f"--set is written KEY=VALUE, got {key or text!r}")
        _found, parts = match_config_key(key)
        leaves.append((parts, parse_value(value)))
    return leaves


def _is_leaf(path: tuple[str, ...], value: Any) -> bool:
    """Say whether a value of a config-shaped dict is the value of one key.

    A table that names no key is walked into; any other value that names no
    key is ``E_CONFIG``.
    """
    try:
        _key, found = match_config_key(".".join(path))
    except Refusal:
        if isinstance(value, Mapping):
            return False
        raise
    if found == path:
        return True
    if isinstance(value, Mapping):
        return False
    raise Refusal("E_CONFIG", f"unknown config key: {'.'.join(path)}")


def dict_leaves(data: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[Leaf]:
    """Split a config-shaped dict into one leaf per key it sets."""
    leaves: list[Leaf] = []
    for name, value in data.items():
        path = (*prefix, str(name))
        if _is_leaf(path, value):
            leaves.append((path, value))
        elif isinstance(value, Mapping):
            leaves.extend(dict_leaves(value, path))
    return leaves


# ---------------------------------------------------------------------------
# Flags of the command line
# ---------------------------------------------------------------------------


def side_table(text: str) -> tuple[str, dict[str, Any]]:
    """Turn ``NAME=KIND:SPEC``, as written after ``--side``, into a side's config table.

    The text is checked with ``Side.parse``. An image becomes ``image``, a
    command ``cmd`` (its arguments as a list), an interpreter ``python``,
    ``venv`` or ``conda``, a serving image ``serve.image``, a result file
    ``file``; any other kind is ``kind`` and ``spec``.
    """
    side = Side.parse(text)
    spec = side.spec
    kind = side.kind
    table: dict[str, Any]
    if kind == KIND_IMAGE:
        table = {"image": spec["image"]}
    elif kind == KIND_CMD:
        table = {"cmd": list(spec["argv"])}
    elif kind == KIND_PYTHON:
        table = {"python": spec["interpreter"]}
    elif kind in (KIND_VENV, KIND_CONDA):
        table = {kind: spec[kind]}
    elif kind == KIND_SERVE:
        table = {"serve": {"image": spec["image"]}}
    elif kind == KIND_FILE:
        table = {"file": list(spec["paths"])}
    else:
        table = {"kind": kind, "spec": spec["spec"]}
    return side.name, table


def _flag_value(flag: str, value: Any) -> Any:
    if flag in SWITCH_FLAGS:
        return bool(value)
    if flag in REPEATED_FLAGS:
        return [str(v) for v in value] if isinstance(value, list | tuple) else [str(value)]
    if flag in NUMBER_FLAGS and isinstance(value, str) and value.isdecimal():
        return int(value)
    return value


def flag_config(
    given: Mapping[str, Any],
    *,
    sides: Sequence[str] = (),
    baseline: str | None = None,
    workload: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the config-shaped dict of the flags given on the command line.

    ``given`` maps a flag of ``model.FLAG_KEYS`` to its value: ``True`` for a
    switch, a list for a repeated flag, a text otherwise. ``sides`` are the
    texts of ``--side``, ``baseline`` the name after ``--baseline``, and
    ``workload`` the arguments after ``--``. A side named twice is
    ``E_USAGE``.
    """
    config: dict[str, Any] = {}
    for flag, value in given.items():
        if flag not in FLAG_KEYS:
            raise Refusal("E_USAGE", f"{flag} sets no config key")
        if value is None:
            continue
        _put(config, tuple(FLAG_KEYS[flag].split(".")), _flag_value(flag, value))
    named: list[str] = []
    for text in sides:
        name, table = side_table(text)
        if name in named:
            raise Refusal("E_USAGE", f"--side names {name!r} twice")
        named.append(name)
        config.setdefault("sides", {})[name] = table
    if baseline is not None:
        config.setdefault("sides", {}).setdefault(baseline, {})["baseline"] = True
    if workload:
        _put(config, ("workload", "argv"), list(workload))
    return config


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def _put(config: dict[str, Any], parts: Sequence[str], value: Any) -> None:
    """Set one key of a config-shaped dict, making the tables on the way."""
    table = config
    for at, part in enumerate(parts[:-1]):
        inner = table.get(part)
        if inner is None:
            inner = table[part] = {}
        elif not isinstance(inner, dict):
            raise Refusal("E_CONFIG", f"{'.'.join(parts[: at + 1])} must be a table")
        table = inner
    table[parts[-1]] = copy.deepcopy(value)


def _side_kind(parts: Sequence[str]) -> str | None:
    if len(parts) >= 3 and parts[0] == "sides" and parts[2] in SIDE_KIND_KEYS:
        return parts[2]
    return None


def _lay(config: dict[str, Any], leaves: Sequence[Leaf]) -> None:
    """Lay the leaves of one source over the config of the sources below it.

    A side this source makes another kind keeps only its baseline mark and
    its launch overrides from below: one side is one kind.
    """
    kinds = {parts[1]: kind for parts, _v in leaves if (kind := _side_kind(parts))}
    sides = config.get("sides")
    if isinstance(sides, dict):
        for name, kind in kinds.items():
            table = sides.get(name)
            if not isinstance(table, dict):
                continue
            below = [k for k in SIDE_KIND_KEYS if k in table]
            if below and below != [kind]:
                sides[name] = {k: table[k] for k in SIDE_SHARED_KEYS if k in table}
    for parts, value in leaves:
        _put(config, parts, value)


# Two sides put into a config that declares none, so that one key can still be
# read as the experiment reads it (``_read_alike``).
_STAND_IN_SIDES: Final[Mapping[str, Mapping[str, str]]] = {
    "first": {"cmd": "true"},
    "second": {"cmd": "true x"},
}
# The value ``_read_with`` takes to leave the key out.
_LEFT_OUT: Final = object()


def _read_with(config: Mapping[str, Any], parts: Sequence[str], value: Any) -> Experiment | None:
    """Read a copy of the config with the key set to the value, or left out; ``None`` if refused."""
    trial = copy.deepcopy(dict(config))
    if not trial.get("sides"):
        trial["sides"] = copy.deepcopy(dict(_STAND_IN_SIDES))
    if value is _LEFT_OUT:
        table: Any = trial
        for part in parts[:-1]:
            table = table.get(part) if isinstance(table, dict) else None
        if isinstance(table, dict):
            table.pop(parts[-1], None)
    else:
        _put(trial, parts, value)
    try:
        return Experiment.from_json(trial)
    except Refusal:
        return None


def _read_alike(config: Mapping[str, Any], parts: Sequence[str], first: Any, second: Any) -> bool:
    """Say whether two values of one key read as one value in the experiment.

    Each value is put into a copy of the merged config, and both copies are
    read as the experiment is (``Experiment.from_json``): ``"4"`` and ``4``
    are one CPU list, ``"1,8,32"`` and ``[1, 8, 32]`` one list of levels. A
    config that declares no side, as the machine checks read, gets two stand-in
    sides for the reading. When only one of the two values can be read, they
    differ. When neither can, and the config reads with the key left out, the
    values themselves are bad: they are let through, and the reading of the
    merged config gives its own refusal. When the config cannot be read
    without the key either, the values are compared as written: they differ.
    """
    read = [_read_with(config, parts, value) for value in (first, second)]
    if read[0] is not None and read[1] is not None:
        return read[0] == read[1]
    if read[0] is None and read[1] is None:
        return _read_with(config, parts, _LEFT_OUT) is not None
    return False


def _check_same_values(
    config: Mapping[str, Any], flags: Sequence[Leaf], sets: Sequence[Leaf]
) -> None:
    """Refuse a key that a flag and ``--set`` give values that read differently.

    The values are compared as written first (durations in seconds), then
    after the reading of the key, so one value written two ways is one value.
    """
    by_path = dict(flags)
    for parts, value in sets:
        if parts not in by_path:
            continue
        key, _found = match_config_key(".".join(parts))
        if _differ(key, by_path[parts], value) and not _read_alike(
            config, parts, by_path[parts], value
        ):
            raise Refusal(
                "E_USAGE",
                f"a flag and --set give {'.'.join(parts)} different values",
            )


def _check_command_line(flags: Sequence[Leaf], sets: Sequence[Leaf]) -> None:
    """Refuse a side that ``--side`` and ``--set`` make two kinds."""
    flag_kinds = {parts[1]: kind for parts, _v in flags if (kind := _side_kind(parts))}
    for parts, _value in sets:
        kind = _side_kind(parts)
        if kind is not None and flag_kinds.get(parts[1], kind) != kind:
            raise Refusal(
                "E_USAGE",
                f"--side and --set make side {parts[1]!r} two kinds: "
                f"{flag_kinds[parts[1]]} and {kind}",
            )


def _is_baseline(parts: Sequence[str]) -> bool:
    return len(parts) == 3 and parts[0] == "sides" and parts[2] == "baseline"


def _apply_baseline(config: dict[str, Any], flags: Sequence[Leaf], sets: Sequence[Leaf]) -> None:
    """Make the side the command line names the baseline and every other side not one."""
    chosen = [parts[1] for parts, value in flags if _is_baseline(parts) and value is True]
    if not chosen:
        return
    name = chosen[0]
    sides = config.get("sides")
    table_of_sides: dict[str, Any] = sides if isinstance(sides, dict) else {}
    table = table_of_sides.get(name)
    if not isinstance(table, dict) or not any(k in table for k in SIDE_KIND_KEYS):
        raise Refusal("E_USAGE", f"--baseline names no side: {name!r}")
    for parts, value in sets:
        if _is_baseline(parts) and parts[1] != name and value is True:
            raise Refusal(
                "E_USAGE",
                f"--baseline names {name!r} and --set makes {parts[1]!r} the baseline",
            )
    for other, side in table_of_sides.items():
        if other != name and isinstance(side, dict):
            side["baseline"] = False


def config_file(path: Path | None, environ: Mapping[str, str]) -> Path | None:
    """The config file to read: the one given, or the one ``PAIRBENCH_CONFIG`` names, or none."""
    if path is not None:
        return Path(path)
    named = environ.get(CONFIG_VARIABLE)
    return Path(named) if named else None


def resolve_config(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    flags: Mapping[str, Any] | None = None,
    sets: Sequence[str] = (),
) -> dict[str, Any]:
    """Merge every source into one config-shaped dict, as ``load_experiment`` reads it."""
    env = os.environ if environ is None else environ
    file = config_file(path, env)
    config = read_file(file) if file is not None else {}
    from_env = environment_leaves(env)
    from_flags = dict_leaves(flags or {})
    from_sets = set_leaves(sets)
    _check_command_line(from_flags, from_sets)
    _lay(config, from_env)
    _lay(config, [*from_flags, *from_sets])
    _apply_baseline(config, from_flags, from_sets)
    _check_side_names(config)
    _check_same_values(config, from_flags, from_sets)
    return config


def _check_side_names(config: Mapping[str, Any]) -> None:
    """Refuse a side name that is not UTF-8 text.

    An argument or a variable can carry bytes that are not UTF-8; a side's
    name is written into the capture, the results and the reports, which are
    UTF-8 text.
    """
    sides = config.get("sides")
    if not isinstance(sides, Mapping):
        return
    for name in sides:
        try:
            str(name).encode("utf-8")
        except UnicodeEncodeError:
            raise Refusal(
                "E_USAGE", f"side name {name!a} is refused: it is not UTF-8 text"
            ) from None


def load_experiment(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    flags: Mapping[str, Any] | None = None,
    sets: Sequence[str] = (),
) -> Experiment:
    """Build the experiment from every source (``api.LoadExperiment``).

    Precedence: ``flags`` and ``sets``, then the environment, then the file,
    then the defaults. ``path`` of ``None`` means the file ``PAIRBENCH_CONFIG``
    names, or no file. ``flags`` is a config-shaped dict made from flags of
    the command line (``flag_config``). ``sets`` are ``KEY=VALUE`` texts as
    written after ``--set``. A key named by a flag and by ``--set`` with
    values that read differently is ``E_USAGE`` (one value written two ways,
    such as ``4`` and ``"4"``, is one value); an unknown key or a bad value
    is ``E_CONFIG``.
    """
    experiment = Experiment.from_json(resolve_config(path, environ=environ, flags=flags, sets=sets))
    return serving_defaults(experiment)


def serving_defaults(experiment: Experiment) -> Experiment:
    """Give a serving experiment the default load levels and level length it does not name.

    Only an experiment whose sides all serve gets them. The levels count
    requests in flight, so levels of requests per second get no default.
    """
    if not experiment.sides or not experiment.is_serving:
        return experiment
    load = experiment.load
    levels = load.levels
    if not levels and load.level_kind == "concurrency":
        levels = SERVING_LEVELS
    duration = load.level_duration_s
    if duration is None and experiment.driver not in PROMPT_COUNTED_DRIVERS:
        duration = SERVING_LEVEL_DURATION_S
    if (levels, duration) == (load.levels, load.level_duration_s):
        return experiment
    return dataclasses.replace(
        experiment, load=dataclasses.replace(load, levels=levels, level_duration_s=duration)
    )


__all__ = [
    "CONFIG_VARIABLE",
    "CPU_LIST_KEYS",
    "DURATION_KEYS",
    "OUT_VARIABLE",
    "OVERRIDE_PREFIX",
    "PROMPT_COUNTED_DRIVERS",
    "SERVING_LEVELS",
    "SERVING_LEVEL_DURATION_S",
    "SIDE_KIND_KEYS",
    "config_file",
    "dict_leaves",
    "environment_leaves",
    "flag_config",
    "load_experiment",
    "parse_value",
    "read_file",
    "resolve_config",
    "serving_defaults",
    "set_leaves",
    "side_table",
]
