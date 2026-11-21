# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The dataclasses of the model and the shipped JSON Schemas say the same.

The check walks every class a capture record or the results document is made
of and compares it with its schema: every field, which keys are required,
every enumeration, every fixed value and every limit on a value. It reads
only the model and the schema files. Each kind of disagreement is also shown
to be seen, on small made-up classes and on altered copies of the shipped
schemas.
"""

from __future__ import annotations

import copy
import dataclasses
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Union, get_args, get_origin, get_type_hints

import pytest

from pairbench import model
from pairbench.results import load_schema

JSON_TYPES: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _allows_null(fragment: Mapping[str, Any]) -> bool:
    kind = fragment.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    if "enum" in fragment and None in fragment["enum"]:
        return True
    return any(_allows_null(option) for option in fragment.get("anyOf", ()))


def _without_null(fragment: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(fragment)
    if isinstance(out.get("type"), list):
        kinds = [k for k in out["type"] if k != "null"]
        out["type"] = kinds[0] if len(kinds) == 1 else kinds
    if "enum" in out:
        out["enum"] = [v for v in out["enum"] if v is not None]
    if "anyOf" in out:
        options = [o for o in out["anyOf"] if o.get("type") != "null"]
        if len(options) == 1 and len(out) == 1:
            return dict(options[0])
        out["anyOf"] = options
    return out


def _kinds(fragment: Mapping[str, Any]) -> set[str]:
    kind = fragment.get("type")
    if isinstance(kind, str):
        return {kind}
    if isinstance(kind, list):
        return set(kind)
    return set()


# Words of a schema that narrow a value beyond its type and are not limits of
# the model: a field that carries one of them is not described by its type.
NARROWING_WORDS = ("const", "enum", "format", "maxLength", "multipleOf")


def _identity_fragment() -> dict[str, Any]:
    """The schema of the identity a results document may show, from the model's own lists."""
    a_hash = {"type": "string", "pattern": model.HASH_PATTERN}

    def one(key: str) -> dict[str, Any]:
        if key in model.PUBLIC_IDENTITY_TEXT_KEYS:
            return {"type": "string"}
        if key in model.PUBLIC_IDENTITY_LIST_KEYS:
            return {"type": "array", "items": a_hash}
        return a_hash

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {key: one(key) for key in model.PUBLIC_IDENTITY_KEYS},
    }


# A free table whose keys the model fixes all the same, with the schema it must have.
FIXED_TABLES: dict[tuple[str, str], dict[str, Any]] = {
    ("ResultsSide", "identity"): _identity_fragment(),
}


def _without_description(fragment: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fragment.items() if k != "description"}


def disagreements(tp: Any, fragment: Mapping[str, Any], where: str) -> list[str]:
    """Say where a schema fragment does not describe a field type."""
    if tp is Any:
        return []
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        options = [a for a in get_args(tp) if a is not type(None)]
        nullable = len(options) != len(get_args(tp))
        if nullable != _allows_null(fragment):
            return [f"{where}: the type {'allows' if nullable else 'forbids'} null"]
        inner = _without_null(fragment) if nullable else fragment
        if len(options) == 1:
            return disagreements(options[0], inner, where)
        if all(option in JSON_TYPES for option in options):
            wanted = {JSON_TYPES[option] for option in options}
            if "number" in wanted:
                wanted.discard("integer")
            return [] if _kinds(inner) == wanted else [f"{where}: expected one of {sorted(wanted)}"]
        choices = inner.get("anyOf", [])
        if len(choices) != len(options):
            return [f"{where}: expected {len(options)} alternatives"]
        found: list[str] = []
        for option, choice in zip(options, choices, strict=True):
            found += disagreements(option, choice, where)
        return found
    if origin is Literal:
        values = get_args(tp)
        if len(values) == 1:
            if _without_description(fragment) != {"const": values[0]}:
                return [f"{where}: expected the fixed value {values[0]!r}"]
            return []
        allowed = fragment.get("enum")
        if allowed is None or sorted(allowed) != sorted(values):
            return [f"{where}: expected the values {sorted(values)}, the schema has {allowed}"]
        return []
    if origin is tuple:
        if fragment.get("type") != "array":
            return [f"{where}: expected an array"]
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return disagreements(args[0], fragment.get("items", {}), f"{where}[]")
        parts = fragment.get("prefixItems", [])
        if len(parts) != len(args) or fragment.get("minItems") != len(args):
            return [f"{where}: expected an array of exactly {len(args)}"]
        if fragment.get("maxItems") != len(args):
            return [f"{where}: expected an array of exactly {len(args)}"]
        found = []
        for i, (arg, part) in enumerate(zip(args, parts, strict=True)):
            found += disagreements(arg, part, f"{where}[{i}]")
        return found
    if isinstance(origin, type) and issubclass(origin, Mapping):
        if fragment.get("type") != "object":
            return [f"{where}: expected an object"]
        value = get_args(tp)[1]
        if value is Any:
            if _without_description(fragment) != {"type": "object"}:
                return [f"{where}: the type is a free table, the schema narrows it"]
            return []
        return disagreements(value, fragment.get("additionalProperties", {}), f"{where}.*")
    if dataclasses.is_dataclass(tp):
        name = getattr(tp, "__name__", "")
        if fragment.get("$ref") != f"#/$defs/{name}":
            return [f"{where}: expected a reference to {name}"]
        return []
    if tp in JSON_TYPES:
        if JSON_TYPES[tp] not in _kinds(fragment):
            return [f"{where}: expected {JSON_TYPES[tp]}"]
        narrowed = [word for word in NARROWING_WORDS if word in fragment]
        if narrowed:
            return [f"{where}: the schema narrows the value with {narrowed}, the type does not"]
        return []
    return [f"{where}: a type this check does not know: {tp!r}"]


def limit_disagreements(cls: type, name: str, fragment: Mapping[str, Any]) -> list[str]:
    """Say where the limits a schema states for a field differ from the limits of the class."""
    declared = dict(getattr(cls, "LIMITS", {}).get(name, {}))
    stated = {word: fragment[word] for word in model.LIMIT_WORDS if word in fragment}
    if declared != stated:
        return [f"{cls.__name__}.{name}: the limits are {declared}, the schema states {stated}"]
    return []


def class_disagreements(cls: type, schema: Mapping[str, Any], *, record: bool) -> list[str]:
    """Say where the schema of one class differs from the class."""
    name = cls.__name__
    hints = get_type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    required = list(model.required_keys(cls))
    tag = getattr(cls, "RECORD", None) if record else None
    if tag is not None:
        names = ["t", *names]
        required = ["t", *required]
    found: list[str] = []
    properties = schema.get("properties", {})
    if sorted(properties) != sorted(names):
        found.append(f"{name}: the fields are {names}, the schema has {list(properties)}")
    if sorted(schema.get("required", [])) != sorted(required):
        found.append(
            f"{name}: required are {required}, the schema requires {schema.get('required')}"
        )
    if schema.get("additionalProperties") is not False:
        found.append(f"{name}: the schema lets unknown keys through")
    if tag is not None and properties.get("t") != {"const": tag}:
        found.append(f"{name}: the record type must be the constant {tag!r}")
    for f in dataclasses.fields(cls):
        if f.name not in properties:
            continue
        fixed = FIXED_TABLES.get((name, f.name))
        if fixed is not None:
            if _without_description(properties[f.name]) != fixed:
                found.append(f"{name}.{f.name}: the schema must list exactly the keys of the model")
            continue
        found += disagreements(hints[f.name], properties[f.name], f"{name}.{f.name}")
        found += limit_disagreements(cls, f.name, properties[f.name])
    stray = sorted(set(getattr(cls, "LIMITS", {})) - {f.name for f in dataclasses.fields(cls)})
    if stray:
        found.append(f"{name}: limits name no field: {stray}")
    return found


def reachable(roots: list[type]) -> list[type]:
    """Return the model classes a document is made of, each once, in order of first use."""
    seen: list[type] = []

    def walk(tp: Any) -> None:
        if dataclasses.is_dataclass(tp) and isinstance(tp, type):
            if tp in seen:
                return
            seen.append(tp)
            for hint in get_type_hints(tp).values():
                walk(hint)
            return
        for arg in get_args(tp):
            walk(arg)

    for root in roots:
        walk(root)
    return seen


def document_disagreements(
    roots: list[type], schema: Mapping[str, Any], *, record: bool, root_is_schema: bool
) -> list[str]:
    """Compare every class of a document with the schema of that document."""
    found: list[str] = []
    classes = reachable(roots)
    defs = dict(schema.get("$defs", {}))
    if root_is_schema:
        defs[roots[0].__name__] = schema
    for cls in classes:
        if getattr(cls, "OPTIONAL", None) is None:
            found.append(
                f"{cls.__name__}: is part of a document and must say which keys are optional"
            )
        if cls.__name__ not in defs:
            found.append(f"{cls.__name__}: has no schema")
            continue
        found += class_disagreements(cls, defs[cls.__name__], record=record)
    extra = sorted(set(defs) - {cls.__name__ for cls in classes})
    if extra:
        found.append(f"the schema describes classes the model does not have: {extra}")
    return found


RECORD_CLASSES = list(model.RECORD_TYPES.values())


def results_disagreements(schema: Mapping[str, Any]) -> list[str]:
    return document_disagreements([model.Results], schema, record=False, root_is_schema=True)


def diagnostics_disagreements(schema: Mapping[str, Any]) -> list[str]:
    return document_disagreements([model.Diagnostics], schema, record=False, root_is_schema=True)


def capture_disagreements(schema: Mapping[str, Any]) -> list[str]:
    found = document_disagreements(RECORD_CLASSES, schema, record=True, root_is_schema=False)
    tags = list(model.RECORD_TYPES)
    if schema.get("properties", {}).get("t") != {"enum": tags}:
        found.append(f"the record types are {tags}")
    choices = {
        choice["if"]["properties"]["t"]["const"]: choice["then"]["$ref"]
        for choice in schema.get("allOf", [])
    }
    expected = {tag: f"#/$defs/{cls.__name__}" for tag, cls in model.RECORD_TYPES.items()}
    if choices != expected:
        found.append("each record type must select the schema of its class")
    return found


# ---------------------------------------------------------------------------
# The shipped schemas agree with the model
# ---------------------------------------------------------------------------


def test_the_results_schema_agrees_with_the_model() -> None:
    assert results_disagreements(load_schema("results")) == []


def test_the_capture_schema_agrees_with_the_model() -> None:
    assert capture_disagreements(load_schema("capture")) == []


def test_the_diagnostics_schema_agrees_with_the_model() -> None:
    assert diagnostics_disagreements(load_schema("diagnostics")) == []


def test_the_classes_of_the_diagnostics_document() -> None:
    assert sorted(cls.__name__ for cls in reachable([model.Diagnostics])) == [
        "CounterRow",
        "Diagnostics",
        "DiagnosticsFiles",
        "DiagnosticsRun",
        "Finding",
        "InstrumentRun",
        "Note",
        "ObjectDiff",
        "ResourceRow",
        "StackSummary",
        "TopFunction",
        "TopObject",
    ]


def test_the_classes_of_the_results_document() -> None:
    assert sorted(cls.__name__ for cls in reachable([model.Results])) == [
        "Artifacts",
        "CaptureRef",
        "Case",
        "Comparison",
        "ControlCase",
        "Controls",
        "Degraded",
        "DiagnosticsState",
        "DriverInfo",
        "EnergyInfo",
        "EngineInfo",
        "EnvPad",
        "Figure",
        "Floor",
        "FloorPair",
        "GateSummary",
        "GpuInfo",
        "LaunchCost",
        "MachineState",
        "MachineSummary",
        "Note",
        "PlanSummary",
        "PlotsState",
        "PluginCounts",
        "PositiveControl",
        "Provenance",
        "RefusalEntry",
        "Results",
        "ResultsSide",
        "RuleInfo",
        "RunInfo",
        "SameVsSame",
        "Sensitivity",
        "Series",
        "Tool",
    ]


def test_the_record_types_of_a_capture() -> None:
    assert {tag: cls.__name__ for tag, cls in model.RECORD_TYPES.items()} == {
        "header": "Header",
        "machine": "MachineRecord",
        "side": "Side",
        "gate": "GateRecord",
        "lineup": "Lineup",
        "cases": "CasesRecord",
        "case_key": "CaseKeyRecord",
        "case_names": "CaseNamesRecord",
        "launch": "Launch",
        "obs": "Observation",
        "launch_cost": "LaunchCost",
        "note": "Note",
        "end": "End",
    }
    for tag, cls in model.RECORD_TYPES.items():
        assert tag == cls.RECORD


# Which keys may be absent when a document is read. Every other key is required.
OPTIONAL_KEYS: dict[str, set[str]] = {
    "Results": {"energy", "controls", "launch_cost", "env_pad", "series", "plots", "diagnostics"},
    "RunInfo": {"command"},
    "Comparison": {"statistic", "scale", "reasons"},
    "FloorPair": {"unit"},
    "SameVsSame": {"unit"},
    "Sensitivity": {"not_computed"},
    "MachineState": {"discard_sha256", "undecided_launches"},
    "ResultsSide": {"image_ref", "control_of", "driver"},
    "PlanSummary": {"explain_launches"},
    "Artifacts": {"html", "diagnostics", "charts"},
    "EnvPad": {"min", "max"},
    "Provenance": {"driver"},
    "Side": {"control_of", "workdir_sha256"},
    "MachineRecord": {"tool_cpus"},
    "Lineup": {"control"},
    "Launch": {"tool_version", "runs", "env_pad", "timed_out"},
    "Observation": {"suite"},
    "End": {"discard_sha256", "finished_at"},
    "Diagnostics": {"notes"},
}


def test_the_keys_that_may_be_absent_are_exactly_the_known_ones() -> None:
    declared: dict[str, set[str]] = {}
    for cls in reachable([model.Results, model.Diagnostics, *RECORD_CLASSES]):
        optional = cls.OPTIONAL  # type: ignore[attr-defined]
        assert optional is not None, cls.__name__
        if optional:
            declared[cls.__name__] = set(optional)
    assert declared == OPTIONAL_KEYS


def test_a_class_outside_the_documents_lets_every_defaulted_key_be_absent() -> None:
    assert model.Witness.OPTIONAL is None
    assert model.required_keys(model.Witness) == ()
    assert model.Witness.from_json({"busy_cores": 0.5}) == model.Witness(busy_cores=0.5)
    assert model.required_keys(model.PlanRow) == ("round", "pos", "name", "side")


def test_the_required_keys_of_a_comparison() -> None:
    assert model.required_keys(model.Comparison) == (
        "case",
        "primary",
        "subject",
        "baseline",
        "n_rounds",
        "n_unpaired",
        "n_untied",
        "n_lower",
        "n_higher",
        "subject_median",
        "baseline_median",
        "ratio",
        "gap",
        "floor",
        "bar",
        "p_raw",
        "p_raw_fraction",
        "p_corrected",
        "verdict",
        "outcome",
        "reason",
        "order_split",
        "sensitivity",
    )


# ---------------------------------------------------------------------------
# Every enumeration, written out
# ---------------------------------------------------------------------------

ENUMS: dict[tuple[str, str, str], list[Any]] = {
    ("results", "Comparison", "verdict"): [
        "FASTER",
        "SLOWER",
        "BETTER",
        "WORSE",
        "HIGHER",
        "LOWER",
        "TIE",
        "UNRESOLVED",
        "NO VERDICT",
    ],
    ("results", "Comparison", "outcome"): [
        "better",
        "worse",
        "higher",
        "lower",
        "tie",
        "unresolved",
        "no_verdict",
    ],
    ("results", "Comparison", "reason"): [
        "inside_noise",
        "not_significant",
        "order_unbalanced",
        "sensitive_to_disturbed_rounds",
        "positive_control_failed",
        "nonpositive_value",
        "too_far_apart",
        "single_measurement",
        "order_not_recorded",
        "too_few_rounds",
        "no_floor",
        "one_sided_floor",
        "zero_floor",
        "side_failed",
        "more_than_one_node",
        None,
    ],
    ("results", "Comparison", "scale"): ["ratio", "percent"],
    ("results", "FloorPair", "source"): ["twins", "supplied"],
    ("results", "FloorPair", "unit"): ["fraction", "percent"],
    ("results", "FloorPair", "mode"): ["TWO-SIDED", "ONE-SIDED", "NONE"],
    ("results", "SameVsSame", "unit"): ["fraction", "percent"],
    ("results", "Sensitivity", "not_computed"): ["too_few_rounds", "too_many_disturbed", None],
    ("results", "Sensitivity", "outcome"): [
        "better",
        "worse",
        "higher",
        "lower",
        "tie",
        "unresolved",
        "no_verdict",
        None,
    ],
    ("results", "MachineState", "status"): ["quiet", "busy", "unknown"],
    ("results", "GateSummary", "name"): ["cpus", "quiet", "census", "plugin"],
    ("results", "Degraded", "name"): ["cpus", "quiet", "census", "plugin"],
    ("results", "DriverInfo", "name"): [
        "wall",
        "lines",
        "gbench",
        "nvbench",
        "pytest-benchmark",
        "hyperfine",
        "perf",
        "llama-bench",
        "guidellm",
        "aiperf",
        "vllm-bench",
        None,
    ],
    ("results", "ResultsSide", "kind"): [
        "cmd",
        "image",
        "python",
        "venv",
        "conda",
        "serve",
        "file",
        "rows",
        "plugin",
    ],
    ("results", "GateSummary", "mode"): ["off", "warn", "enforce"],
    ("results", "GateSummary", "status"): ["pass", "fail", "degraded", "unavailable"],
    ("results", "Degraded", "status"): ["pass", "fail", "degraded", "unavailable"],
    ("results", "RefusalEntry", "scope"): ["experiment", "case"],
    ("results", "ResultsSide", "role"): ["subject", "baseline", "twin", "control"],
    ("results", "Case", "better"): ["lower", "higher", "none"],
    ("results", "Case", "kind"): ["time", "rate", "efficiency", "count", "other"],
    ("results", "PositiveControl", "status"): ["ok", "failed", "not_run"],
    ("results", "PositiveControl", "via"): ["repeat", "factor"],
    ("results", "PlotsState", "status"): ["pending", "drawn", "not_drawn", "off", "interrupted"],
    ("results", "PlotsState", "reason"): ["extra_missing", "failed", None],
    ("results", "DiagnosticsState", "status"): [
        "pending",
        "written",
        "skipped",
        "off",
        "failed",
        "interrupted",
    ],
    ("results", "DiagnosticsState", "reason"): [
        "mode_auto_no_difference",
        "lock",
        "no_instrument",
        None,
    ],
    ("diagnostics", "InstrumentRun", "name"): ["counters", "stacks", "pystacks"],
    ("diagnostics", "InstrumentRun", "status"): ["ok", "skipped", "failed"],
    ("diagnostics", "InstrumentRun", "reason"): [
        "not_installed",
        "not_permitted",
        "not_in_image",
        "no_capability",
        "launcher_cannot",
        "side_changed",
        "lock",
        "launch_failed",
        "interpreter_too_old",
        None,
    ],
    ("diagnostics", "StackSummary", "instrument"): ["stacks", "pystacks"],
    ("diagnostics", "ResourceRow", "outcome"): [
        "better",
        "worse",
        "higher",
        "lower",
        "tie",
        "unresolved",
        "no_verdict",
    ],
    ("diagnostics", "Finding", "id"): [
        "cores_used",
        "cpu_time_split",
        "peak_memory",
        "context_switches",
        "page_faults",
        "instructions",
        "instructions_per_cycle",
        "cache_misses",
        "branch_misses",
        "top_function_share",
        "top_object_share",
        "objects_on_one_side",
        "objects_differ",
    ],
    ("capture", "Side", "role"): ["subject", "baseline", "twin", "control"],
    ("capture", "GateRecord", "mode"): ["off", "warn", "enforce"],
    ("capture", "GateRecord", "status"): ["pass", "fail", "degraded", "unavailable"],
    ("capture", "Launch", "phase"): ["warmup", "round"],
    ("capture", "End", "status"): ["complete", "failed", "interrupted"],
    ("capture", "Case", "better"): ["lower", "higher", "none"],
    ("capture", "Case", "kind"): ["time", "rate", "efficiency", "count", "other"],
}


@pytest.mark.parametrize(("where", "values"), sorted(ENUMS.items(), key=lambda item: item[0]))
def test_an_enumeration_of_a_schema(where: tuple[str, str, str], values: list[Any]) -> None:
    document, name, key = where
    assert load_schema(document)["$defs"][name]["properties"][key]["enum"] == values


def test_every_enumeration_of_the_schemas_is_written_out_above() -> None:
    found: set[tuple[str, str, str]] = set()
    for document in ("results", "capture", "diagnostics"):
        for name, definition in load_schema(document)["$defs"].items():
            for key, fragment in definition["properties"].items():
                if "enum" in fragment:
                    found.add((document, name, key))
    assert found == set(ENUMS)


# Every limit on a value, written out: (document, class, field) and the limit.
LIMITS: dict[tuple[str, str, str], dict[str, Any]] = {
    ("capture", "Launch", "round"): {"minimum": 0},
    ("capture", "Launch", "pos"): {"minimum": 1},
    ("capture", "Launch", "runs"): {"minimum": 1, "maximum": 2},
    ("capture", "Launch", "env_pad"): {"minimum": 0, "maximum": 4096},
    ("capture", "LaunchCost", "command"): {"pattern": "^[^/\\\\]+$"},
    ("capture", "LaunchCost", "n"): {"minimum": 1},
    ("capture", "LaunchCost", "median_s"): {"minimum": 0},
    ("capture", "LaunchCost", "p25_s"): {"minimum": 0},
    ("capture", "LaunchCost", "p75_s"): {"minimum": 0},
    ("capture", "LaunchCost", "min_s"): {"minimum": 0},
    ("results", "LaunchCost", "command"): {"pattern": "^[^/\\\\]+$"},
    ("results", "LaunchCost", "n"): {"minimum": 1},
    ("results", "LaunchCost", "median_s"): {"minimum": 0},
    ("results", "LaunchCost", "p25_s"): {"minimum": 0},
    ("results", "LaunchCost", "p75_s"): {"minimum": 0},
    ("results", "LaunchCost", "min_s"): {"minimum": 0},
    ("results", "ControlCase", "n_rounds"): {"minimum": 0},
    ("results", "MachineState", "undecided_launches"): {"minimum": 0},
    ("results", "PositiveControl", "entry"): {"minLength": 1},
    ("results", "PositiveControl", "tolerance"): {"minimum": 0, "exclusiveMaximum": 0.5},
    ("results", "EnvPad", "min"): {"minimum": 0, "maximum": 4096},
    ("results", "EnvPad", "max"): {"minimum": 0, "maximum": 4096},
    ("results", "ResultsSide", "twin_of"): {"minLength": 1},
    ("results", "ResultsSide", "control_of"): {"minLength": 1},
    ("capture", "Side", "twin_of"): {"minLength": 1},
    ("capture", "Side", "control_of"): {"minLength": 1},
    ("capture", "Side", "workdir_sha256"): {"pattern": "^[0-9a-f]{64}$"},
    ("capture", "CaseKeyRecord", "key"): {"pattern": "^[0-9a-f]{64}$"},
    ("capture", "CaseName", "name"): {"minLength": 1},
    ("capture", "CaseName", "side"): {"minLength": 1},
    ("capture", "CaseName", "tell_sha256"): {"pattern": "^[0-9a-f]{64}$"},
    ("capture", "CaseName", "hidden_sha256"): {"pattern": "^[0-9a-f]{64}$"},
    ("capture", "CaseName", "read_sha256"): {"pattern": "^[0-9a-f]{64}$"},
    ("capture", "Lineup", "control"): {"minLength": 1},
    ("capture", "MachineRecord", "tool_cpus"): {"pattern": "^\\d+(-\\d+)?(,\\d+(-\\d+)?)*$"},
    ("diagnostics", "TopFunction", "share"): {"minimum": 0, "maximum": 1},
    ("diagnostics", "TopObject", "share"): {"minimum": 0, "maximum": 1},
    ("diagnostics", "StackSummary", "samples"): {"minimum": 0},
    ("diagnostics", "Finding", "text"): {"minLength": 1},
    ("diagnostics", "Note", "code"): {"pattern": "^[a-z][a-z0-9_]*$"},
    ("capture", "Observation", "round"): {"minimum": 0},
    ("capture", "Observation", "pos"): {"minimum": 1},
    ("capture", "Observation", "n_inner"): {"minimum": 1},
    ("capture", "Note", "code"): {"pattern": "^[a-z][a-z0-9_]*$"},
    ("capture", "DiscardThresholds", "max_busy_cores"): {"minimum": 0},
    ("capture", "DiscardThresholds", "max_gpu_other_processes"): {"minimum": 0},
    ("capture", "DiscardThresholds", "max_gpu_throttle_events"): {"minimum": 0},
    ("results", "Note", "code"): {"pattern": "^[a-z][a-z0-9_]*$"},
    ("results", "RefusalEntry", "code"): {"pattern": "^E_[A-Z0-9_]+$"},
}


def _schema_limits(document: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for name, definition in load_schema(document)["$defs"].items():
        for key, fragment in definition["properties"].items():
            stated = {word: fragment[word] for word in model.LIMIT_WORDS if word in fragment}
            if stated:
                found[(document, name, key)] = stated
    return found


def test_every_limit_of_the_schemas_is_written_out_above() -> None:
    assert {
        **_schema_limits("capture"),
        **_schema_limits("results"),
        **_schema_limits("diagnostics"),
    } == LIMITS


def test_the_schema_ids_are_fixed_values() -> None:
    assert load_schema("results")["properties"]["schema"] == {"const": "pairbench/results/v1"}
    assert load_schema("capture")["$defs"]["Header"]["properties"]["schema"] == {
        "const": "pairbench/capture/v1"
    }
    assert load_schema("diagnostics")["properties"]["schema"] == {
        "const": "pairbench/diagnostics/v1"
    }


def test_the_identity_a_results_document_may_show_is_ten_keys_of_hashes_and_two_texts() -> None:
    fragment = load_schema("results")["$defs"]["ResultsSide"]["properties"]["identity"]
    a_hash = {"type": "string", "pattern": "^([a-z0-9]+([+._-][a-z0-9]+)*:)?[0-9a-f]{12,}$"}
    assert fragment["additionalProperties"] is False
    assert fragment["properties"] == {
        "image_id": a_hash,
        "digests": {"type": "array", "items": a_hash},
        "platform": {"type": "string"},
        "python_version": {"type": "string"},
        "packages_sha256": a_hash,
        "executable_sha256": a_hash,
        "argv_sha256": a_hash,
        "args_sha256": a_hash,
        "files_sha256": {"type": "array", "items": a_hash},
        "identify_sha256": a_hash,
    }


def test_the_names_a_results_document_may_show_are_the_built_ins_and_plugin() -> None:
    assert model.BUILTIN_KINDS == ("cmd", "image", "python", "venv", "conda", "serve", "file")
    assert model.SHOWN_KINDS == (
        "cmd",
        "image",
        "python",
        "venv",
        "conda",
        "serve",
        "file",
        "rows",
        "plugin",
    )
    assert model.BUILTIN_GATES == ("cpus", "quiet", "census")
    assert model.SHOWN_GATES == ("cpus", "quiet", "census", "plugin")
    assert get_args(model.ShownDriver) == model.BUILTIN_DRIVERS
    assert model.PLUGIN_NAME == "plugin"


def test_the_vocabularies_of_the_model() -> None:
    assert model.OUTCOMES == (
        "better",
        "worse",
        "higher",
        "lower",
        "tie",
        "unresolved",
        "no_verdict",
    )
    assert model.OUTCOMES_JUDGED == ("better", "worse", "tie", "unresolved", "no_verdict")
    assert model.OUTCOMES_DESCRIBED == ("higher", "lower", "tie", "unresolved", "no_verdict")
    assert model.VERDICTS == (
        "FASTER",
        "SLOWER",
        "BETTER",
        "WORSE",
        "HIGHER",
        "LOWER",
        "TIE",
        "UNRESOLVED",
        "NO VERDICT",
    )
    assert model.BETTER == ("lower", "higher", "none")
    assert model.ROLES == ("subject", "baseline", "twin", "control")
    assert model.REASONS_UNRESOLVED == (
        "inside_noise",
        "not_significant",
        "order_unbalanced",
        "sensitive_to_disturbed_rounds",
    )
    assert model.REASONS_NO_VERDICT == (
        "positive_control_failed",
        "nonpositive_value",
        "too_far_apart",
        "single_measurement",
        "order_not_recorded",
        "too_few_rounds",
        "no_floor",
        "one_sided_floor",
        "zero_floor",
    )
    assert model.REASONS_RESERVED == ("side_failed", "more_than_one_node")
    assert (
        *model.REASONS_UNRESOLVED,
        *model.REASONS_NO_VERDICT,
        *model.REASONS_RESERVED,
    ) == model.REASONS
    assert model.ENERGY_SCOPE == "gpu"
    assert model.ENERGY_EXCLUDES == ("cpu", "memory", "storage", "cooling", "power supply losses")


# ---------------------------------------------------------------------------
# The check sees each kind of disagreement
# ---------------------------------------------------------------------------


def _results_schema() -> dict[str, Any]:
    return copy.deepcopy(load_schema("results"))


def _drop_a_property(schema: dict[str, Any]) -> None:
    del schema["$defs"]["Comparison"]["properties"]["statistic"]


def _add_a_property(schema: dict[str, Any]) -> None:
    schema["$defs"]["Floor"]["properties"]["made_up"] = {"type": "string"}


def _require_an_optional_key(schema: dict[str, Any]) -> None:
    schema["$defs"]["RunInfo"]["required"].append("command")


def _make_a_required_key_optional(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["required"].remove("outcome")


def _drop_an_enumeration_value(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["outcome"]["enum"].remove("tie")


def _add_an_enumeration_value(schema: dict[str, Any]) -> None:
    schema["$defs"]["FloorPair"]["properties"]["unit"]["enum"].append("ppm")


def _change_a_type(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["n_rounds"] = {"type": "string"}


def _forbid_null(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["ratio"] = {"type": "number"}


def _allow_unknown_keys(schema: dict[str, Any]) -> None:
    schema["$defs"]["Figure"]["additionalProperties"] = True


def _drop_a_class(schema: dict[str, Any]) -> None:
    del schema["$defs"]["Sensitivity"]


def _add_a_class(schema: dict[str, Any]) -> None:
    schema["$defs"]["MadeUp"] = {"type": "object"}


def _drop_a_top_level_key(schema: dict[str, Any]) -> None:
    del schema["properties"]["energy"]


def _require_a_top_level_optional_key(schema: dict[str, Any]) -> None:
    schema["required"].append("energy")


def _change_an_array_item(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["order_split"]["prefixItems"][0] = {
        "type": "string"
    }


def _point_at_another_class(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["floor"] = {"$ref": "#/$defs/Floor"}


def _add_a_limit(schema: dict[str, Any]) -> None:
    schema["$defs"]["Comparison"]["properties"]["n_rounds"]["minimum"] = 0


def _drop_a_limit(schema: dict[str, Any]) -> None:
    del schema["$defs"]["RefusalEntry"]["properties"]["code"]["pattern"]


def _change_a_limit(schema: dict[str, Any]) -> None:
    schema["$defs"]["Note"]["properties"]["code"]["pattern"] = "^[a-z]+$"


def _name_another_schema_id(schema: dict[str, Any]) -> None:
    schema["properties"]["schema"] = {"const": "pairbench/results/v2"}


def _let_any_schema_id_through(schema: dict[str, Any]) -> None:
    schema["properties"]["schema"] = {"type": "string"}


def _fix_a_free_text(schema: dict[str, Any]) -> None:
    schema["$defs"]["Tool"]["properties"]["name"] = {"type": "string", "const": "pairbench"}


def _let_any_kind_of_side_through(schema: dict[str, Any]) -> None:
    schema["$defs"]["ResultsSide"]["properties"]["kind"] = {"type": "string"}


def _show_one_more_identity_key(schema: dict[str, Any]) -> None:
    identity = schema["$defs"]["ResultsSide"]["properties"]["identity"]
    identity["properties"]["prefix"] = {"type": "string"}


def _let_any_identity_through(schema: dict[str, Any]) -> None:
    schema["$defs"]["ResultsSide"]["properties"]["identity"] = {"type": "object"}


def _let_a_digest_hold_any_text(schema: dict[str, Any]) -> None:
    identity = schema["$defs"]["ResultsSide"]["properties"]["identity"]
    identity["properties"]["digests"] = {"type": "array", "items": {"type": "string"}}


def _narrow_a_free_table(schema: dict[str, Any]) -> None:
    schema["$defs"]["RuleInfo"]["properties"]["fields"]["additionalProperties"] = False


@pytest.mark.parametrize(
    ("alter", "needle"),
    [
        (_drop_a_property, "Comparison: the fields are"),
        (_add_a_property, "Floor: the fields are"),
        (_require_an_optional_key, "RunInfo: required are"),
        (_make_a_required_key_optional, "Comparison: required are"),
        (_drop_an_enumeration_value, "Comparison.outcome: expected the values"),
        (_add_an_enumeration_value, "FloorPair.unit: expected the values"),
        (_change_a_type, "Comparison.n_rounds: expected integer"),
        (_forbid_null, "Comparison.ratio: the type allows null"),
        (_allow_unknown_keys, "Figure: the schema lets unknown keys through"),
        (_drop_a_class, "Sensitivity: has no schema"),
        (_add_a_class, "classes the model does not have: ['MadeUp']"),
        (_drop_a_top_level_key, "Results: the fields are"),
        (_require_a_top_level_optional_key, "Results: required are"),
        (_change_an_array_item, "Comparison.order_split[0]: expected integer"),
        (_point_at_another_class, "Comparison.floor: expected a reference to FloorPair"),
        (_add_a_limit, "Comparison.n_rounds: the limits are {}"),
        (_drop_a_limit, "RefusalEntry.code: the limits are {'pattern': '^E_[A-Z0-9_]+$'}"),
        (_change_a_limit, "Note.code: the limits are {'pattern': '^[a-z][a-z0-9_]*$'}"),
        (_name_another_schema_id, "Results.schema: expected the fixed value"),
        (_let_any_schema_id_through, "Results.schema: expected the fixed value"),
        (_fix_a_free_text, "Tool.name: the schema narrows the value with ['const']"),
        (_let_any_kind_of_side_through, "ResultsSide.kind: expected the values"),
        (_show_one_more_identity_key, "ResultsSide.identity: the schema must list exactly"),
        (_let_any_identity_through, "ResultsSide.identity: the schema must list exactly"),
        (_let_a_digest_hold_any_text, "ResultsSide.identity: the schema must list exactly"),
        (_narrow_a_free_table, "RuleInfo.fields: the type is a free table"),
    ],
)
def test_an_altered_results_schema_is_seen(alter: Any, needle: str) -> None:
    schema = _results_schema()
    alter(schema)
    found = results_disagreements(schema)
    assert len(found) == 1, found
    assert needle in found[0]


def _capture_schema() -> dict[str, Any]:
    return copy.deepcopy(load_schema("capture"))


def _drop_the_record_type(schema: dict[str, Any]) -> None:
    del schema["$defs"]["Observation"]["properties"]["t"]
    schema["$defs"]["Observation"]["required"].remove("t")


def _require_a_record_addition(schema: dict[str, Any]) -> None:
    schema["$defs"]["End"]["required"].append("finished_at")


def _drop_a_phase(schema: dict[str, Any]) -> None:
    schema["$defs"]["Launch"]["properties"]["phase"]["enum"].remove("warmup")


def _drop_a_record_choice(schema: dict[str, Any]) -> None:
    schema["allOf"].pop()


def _drop_a_record_tag(schema: dict[str, Any]) -> None:
    schema["properties"]["t"]["enum"].remove("note")


def _rename_a_record_type(schema: dict[str, Any]) -> None:
    schema["$defs"]["Note"]["properties"]["t"] = {"const": "remark"}


def _let_a_position_be_zero(schema: dict[str, Any]) -> None:
    del schema["$defs"]["Launch"]["properties"]["pos"]["minimum"]


def _name_another_capture_schema_id(schema: dict[str, Any]) -> None:
    schema["$defs"]["Header"]["properties"]["schema"] = {"const": "pairbench/capture/v2"}


def _let_a_threshold_be_negative(schema: dict[str, Any]) -> None:
    del schema["$defs"]["DiscardThresholds"]["properties"]["max_busy_cores"]["minimum"]


@pytest.mark.parametrize(
    ("alter", "needle"),
    [
        (_drop_the_record_type, "Observation: the fields are"),
        (_require_a_record_addition, "End: required are"),
        (_drop_a_phase, "Launch.phase: expected the values"),
        (_drop_a_record_choice, "each record type must select the schema of its class"),
        (_drop_a_record_tag, "the record types are"),
        (_rename_a_record_type, "Note: the record type must be the constant 'note'"),
        (_let_a_position_be_zero, "Launch.pos: the limits are {'minimum': 1}"),
        (_name_another_capture_schema_id, "Header.schema: expected the fixed value"),
        (_let_a_threshold_be_negative, "DiscardThresholds.max_busy_cores: the limits are"),
    ],
)
def test_an_altered_capture_schema_is_seen(alter: Any, needle: str) -> None:
    schema = _capture_schema()
    alter(schema)
    found = capture_disagreements(schema)
    assert found, needle
    assert any(needle in line for line in found), found


@dataclass(frozen=True)
class _MadeUpPart:
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"size": {"minimum": 0}}

    size: int = 0


@dataclass(frozen=True)
class _MadeUp:
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"note"})

    name: str
    state: Literal["on", "off"]
    version: Literal["made-up/v1"]
    parts: tuple[_MadeUpPart, ...] = ()
    limits: Mapping[str, float] = field(default_factory=dict)
    pair: tuple[int, int] | None = None
    note: str | None = None


_MADE_UP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "state", "version", "parts", "limits", "pair"],
    "properties": {
        "name": {"type": "string"},
        "state": {"enum": ["on", "off"]},
        "version": {"const": "made-up/v1"},
        "parts": {"type": "array", "items": {"$ref": "#/$defs/_MadeUpPart"}},
        "limits": {"type": "object", "additionalProperties": {"type": "number"}},
        "pair": {
            "anyOf": [
                {
                    "type": "array",
                    "prefixItems": [{"type": "integer"}, {"type": "integer"}],
                    "items": False,
                    "minItems": 2,
                    "maxItems": 2,
                },
                {"type": "null"},
            ]
        },
        "note": {"type": ["string", "null"]},
    },
    "$defs": {
        "_MadeUpPart": {
            "type": "object",
            "additionalProperties": False,
            "required": ["size"],
            "properties": {"size": {"type": "integer", "minimum": 0}},
        }
    },
}


def _made_up_disagreements(schema: Mapping[str, Any]) -> list[str]:
    return document_disagreements([_MadeUp], schema, record=False, root_is_schema=True)


def test_a_made_up_class_and_its_schema_agree() -> None:
    assert _made_up_disagreements(_MADE_UP_SCHEMA) == []


@pytest.mark.parametrize(
    ("path", "value", "needle"),
    [
        (("properties", "state"), {"enum": ["on"]}, "_MadeUp.state: expected the values"),
        (("properties", "name"), {"type": "integer"}, "_MadeUp.name: expected string"),
        (("properties", "limits"), {"type": "object"}, "_MadeUp.limits.*: expected number"),
        (("properties", "note"), {"type": "string"}, "_MadeUp.note: the type allows null"),
        (
            ("properties", "parts"),
            {"type": "array", "items": {"type": "integer"}},
            "_MadeUp.parts[]: expected a reference to _MadeUpPart",
        ),
        (("required",), ["name", "state"], "_MadeUp: required are"),
        (
            ("$defs", "_MadeUpPart", "required"),
            [],
            "_MadeUpPart: required are ['size']",
        ),
        (
            ("$defs", "_MadeUpPart", "properties", "size"),
            {"type": "integer"},
            "_MadeUpPart.size: the limits are {'minimum': 0}, the schema states {}",
        ),
        (
            ("$defs", "_MadeUpPart", "properties", "size"),
            {"type": "integer", "minimum": 1},
            "_MadeUpPart.size: the limits are {'minimum': 0}, the schema states {'minimum': 1}",
        ),
        (
            ("properties", "name"),
            {"type": "string", "minLength": 1},
            "_MadeUp.name: the limits are {}, the schema states {'minLength': 1}",
        ),
        (
            ("properties", "name"),
            {"type": "string", "enum": ["made-up"]},
            "_MadeUp.name: the schema narrows the value with ['enum']",
        ),
        (
            ("properties", "version"),
            {"type": "string"},
            "_MadeUp.version: expected the fixed value 'made-up/v1'",
        ),
        (
            ("properties", "version"),
            {"const": "made-up/v2"},
            "_MadeUp.version: expected the fixed value 'made-up/v1'",
        ),
    ],
)
def test_a_made_up_disagreement_is_seen(path: tuple[str, ...], value: Any, needle: str) -> None:
    schema = copy.deepcopy(_MADE_UP_SCHEMA)
    target: Any = schema
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    found = _made_up_disagreements(schema)
    assert len(found) == 1, found
    assert needle in found[0]


def test_a_document_class_must_say_which_keys_are_optional() -> None:
    @dataclass(frozen=True)
    class Silent:
        name: str = ""

    found = document_disagreements(
        [Silent],
        {
            "type": "object",
            "additionalProperties": False,
            "required": [],
            "properties": {"name": {"type": "string"}},
        },
        record=False,
        root_is_schema=True,
    )
    assert found == ["Silent: is part of a document and must say which keys are optional"]


def test_an_optional_key_needs_a_default_and_a_field() -> None:
    @dataclass(frozen=True)
    class NoDefault:
        OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"name"})

        name: str

    @dataclass(frozen=True)
    class NoField:
        OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"made_up"})

        name: str = ""

    with pytest.raises(TypeError, match=r"NoDefault\.name may be absent but has no default"):
        model.required_keys(NoDefault)
    with pytest.raises(TypeError, match=r"NoField\.OPTIONAL names no field: made_up"):
        model.required_keys(NoField)


# ---------------------------------------------------------------------------
# The config schema and the list of config keys
# ---------------------------------------------------------------------------


def config_paths(schema: Mapping[str, Any]) -> list[str]:
    """List the dotted path of every key the config schema allows."""
    defs = schema.get("$defs", {})
    paths: list[str] = []

    def walk(fragment: Mapping[str, Any], prefix: str) -> None:
        if "$ref" in fragment:
            name = fragment["$ref"].rpartition("/")[2]
            if name != "duration":
                walk(defs[name], prefix)
                return
        properties = fragment.get("properties")
        named = fragment.get("additionalProperties")
        if properties:
            for key, inner in properties.items():
                walk(inner, f"{prefix}.{key}" if prefix else key)
        elif isinstance(named, Mapping) and ("$ref" in named or named.get("type") == "array"):
            walk(named, f"{prefix}.NAME")
        else:
            paths.append(prefix)

    walk(schema, "")
    return paths


def test_the_config_schema_allows_exactly_the_config_keys() -> None:
    assert sorted(config_paths(load_schema("config"))) == sorted(model.CONFIG_KEYS)


def test_an_altered_config_schema_is_seen() -> None:
    schema = copy.deepcopy(load_schema("config"))
    del schema["properties"]["workload"]["properties"]["level_kind"]
    schema["properties"]["run"]["properties"]["made_up"] = {"type": "string"}
    found = set(config_paths(schema))
    assert set(model.CONFIG_KEYS) - found == {"workload.level_kind"}
    assert found - set(model.CONFIG_KEYS) == {"run.made_up"}


def test_the_config_schema_refuses_unknown_keys_at_every_level() -> None:
    schema = load_schema("config")
    tables: list[Mapping[str, Any]] = [schema, *schema["$defs"].values()]
    tables += list(schema["properties"].values())
    tables += list(schema["properties"]["gates"]["properties"].values())
    checked = 0
    for table in tables:
        if "properties" in table:
            assert table["additionalProperties"] is False
            checked += 1
    assert checked >= 12


CONFIG_ENUMS: dict[tuple[str, ...], list[str]] = {
    ("properties", "launch", "properties", "engine"): ["auto", "docker", "podman"],
    ("properties", "launch", "properties", "pull"): ["missing", "never", "always"],
    ("$defs", "launch_override", "properties", "engine"): ["auto", "docker", "podman"],
    ("$defs", "launch_override", "properties", "pull"): ["missing", "never", "always"],
    ("properties", "gates", "properties", "mode"): ["off", "warn", "enforce"],
    ("properties", "workload", "properties", "level_kind"): ["concurrency", "rate"],
    ("properties", "controls", "properties", "positive"): ["on", "off"],
    ("properties", "controls", "properties", "positive_via"): ["repeat", "factor"],
    ("properties", "explain", "properties", "mode"): ["always", "auto", "off"],
    ("properties", "explain", "properties", "call_graph"): ["fp", "dwarf", "lbr"],
    ("properties", "plots", "properties", "mode"): ["auto", "on", "off"],
}


@pytest.mark.parametrize(("path", "values"), sorted(CONFIG_ENUMS.items()))
def test_an_enumeration_of_the_config_schema(path: tuple[str, ...], values: list[str]) -> None:
    fragment: Any = load_schema("config")
    for part in path:
        fragment = fragment[part]
    assert fragment["enum"] == values


def test_the_outcomes_that_can_fail_a_run() -> None:
    fragment = load_schema("config")["properties"]["rule"]["properties"]["fail_on"]
    assert fragment["items"]["enum"] == ["better", "worse", "unresolved", "no_verdict"]
    assert model.FAIL_ON == ("better", "worse", "unresolved", "no_verdict")


def test_the_enumerations_of_the_config_follow_the_model() -> None:
    assert get_args(model.Engine) == ("auto", "docker", "podman")
    assert get_args(model.PullPolicy) == ("missing", "never", "always")
    assert model.GATE_MODES == ("off", "warn", "enforce")
    assert model.LEVEL_KINDS == ("concurrency", "rate")
    assert model.CONTROL_MODES == ("on", "off")
    assert model.CONTROL_VIAS == ("repeat", "factor")
    assert model.EXPLAIN_MODES == ("always", "auto", "off")
    assert model.CALL_GRAPHS == ("fp", "dwarf", "lbr")
    assert model.PLOT_MODES == ("auto", "on", "off")


def test_the_tables_of_user_chosen_keys_are_free_tables_in_the_schema() -> None:
    schema = load_schema("config")
    defs = schema["$defs"]

    def at(path: str) -> Mapping[str, Any]:
        fragment: Mapping[str, Any] = schema
        for part in path.split("."):
            if "$ref" in fragment:
                fragment = defs[fragment["$ref"].rpartition("/")[2]]
            if part == "NAME":
                fragment = fragment["additionalProperties"]
            else:
                fragment = fragment["properties"][part]
        if "$ref" in fragment:
            fragment = defs[fragment["$ref"].rpartition("/")[2]]
        return fragment

    for key in model.CONFIG_TABLE_KEYS:
        fragment = at(key)
        assert fragment["type"] == "object", key
        assert "properties" not in fragment, key
