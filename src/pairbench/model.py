# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The data model: frozen dataclasses, their JSON forms and the pure rules they share.

This module is pure. It reads no file, starts no process and imports only the
standard library and ``pairbench.errors``.

Every document type converts to and from its JSON form here, so that modules
which read and write files do input and output only:

* a capture is a list of records, one plain dict per line of ``capture.jsonl``
  (``Capture.to_records`` and ``Capture.from_records``);
* a results document is one plain dict (``Results.to_json`` and
  ``Results.from_json``);
* a config is one plain dict shaped like the config file
  (``Experiment.to_json`` and ``Experiment.from_json``).

Field names equal JSON keys. Every field is written. Which keys may be absent
when a document is read is declared once per class, in ``OPTIONAL``; the JSON
Schemas shipped with the package require exactly the other keys.

The pure rules more than one part of the package needs live here as well, so
that each exists once: the ``rotate-reverse`` schedule, the plan rows and the
balance count, ``min_rounds``, the trapezoid integral, the quantile, the
decision on disturbed rounds, the fingerprint, credential redaction and
duration parsing.
"""

from __future__ import annotations

import bisect
import dataclasses
import fnmatch
import functools
import hashlib
import hmac
import itertools
import json
import math
import re
import shlex
import string
import types
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Final,
    Literal,
    Self,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pairbench.errors import Refusal

# ---------------------------------------------------------------------------
# Names and vocabularies
# ---------------------------------------------------------------------------

TOOL_NAME: Final = "pairbench"
TOOL_VERSION: Final = "0.1.0"

SCHEMA_CAPTURE: Final = "pairbench/capture/v1"
SCHEMA_RESULTS: Final = "pairbench/results/v1"
SCHEMA_CONFIG: Final = "pairbench/config/v1"
SCHEMA_DIAGNOSTICS: Final = "pairbench/diagnostics/v1"

# Names inside a run folder.
FILE_CAPTURE: Final = "capture.jsonl"
FILE_RESULTS: Final = "results.json"
FILE_MARKDOWN: Final = "results.md"
FILE_PLAN: Final = "plan.tsv"
FILE_DIAGNOSTICS: Final = "diagnostics.json"
FILE_REPORT: Final = "report.html"
DIR_ARTIFACTS: Final = "artifacts"
DIR_PROFILES: Final = "profiles"
DIR_CHARTS: Final = "charts"
# The mode of a run file that keeps values as typed: the capture, and what a
# process, a load step or a server printed. Only the owner may read it.
PRIVATE_FILE_MODE: Final = 0o600
# Where run folders go when no output folder is named.
DIR_RUNS: Final = "pairbench-runs"

# The reserved suffixes of the two kinds of entry the tool adds itself: the
# twin of a side and the positive control of the baseline.
TWIN_SUFFIX: Final = "~same"
CONTROL_SUFFIX: Final = "~twice"
SCHEDULE: Final = "rotate-reverse"
REDACTED: Final = "<redacted>"
# The words that make a name look like a credential (``looks_like_credential``).
CREDENTIAL_WORDS: Final[tuple[str, ...]] = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL")
# Of those, the ones that count anywhere in a name, also inside a longer word.
CREDENTIAL_ANYWHERE: Final[tuple[str, ...]] = ("SECRET", "PASSWORD", "CREDENTIAL")
# What a word of a name ends in when it names a key, read with the word before it.
KEY_ENDINGS: Final[tuple[str, ...]] = (
    "KEY",
    "KEYS",
    "KEYSTORE",
    "KEYSTORES",
    "KEYSET",
    "KEYSETS",
)
# What a word of a name ends in after a word of a password when it names where the password
# is, what holds it or the form it takes (``PASSFILE``, ``PGPASSFILE``, ``PWDFILE``,
# ``PASSFILEPATH``, ``PASSWDHASH``, ``PASSWDTEXT``): such a word is read as the words written
# apart (``PASS_FILE``). A key or a token is read apart before any word that follows it
# (``_glued_apart``).
GLUED_ENDINGS: Final[tuple[str, ...]] = (
    "FILE",
    "FILES",
    "PATH",
    "PATHS",
    "ID",
    "IDS",
    "PAIR",
    "PAIRS",
    "RING",
    "RINGS",
    "VALUE",
    "VALUES",
    "DATA",
    "PEM",
    "HASH",
    "HASHES",
    "TEXT",
)
# The words of a key, the longest first: a word of a name in which one is followed by more
# letters is read as written apart after it (``KEYSTOREFILE`` as ``KEYSTORE_FILE``). One whose
# last letter starts a word of ``CREDENTIAL_ANYWHERE`` is not taken there (``HOTKEYSECRET`` as
# ``HOTKEY_SECRET``).
_KEY_HEADS: Final[tuple[str, ...]] = ("KEYSTORES", "KEYSTORE", "KEYSETS", "KEYSET", "KEYS", "KEY")
# Words of their own that start with KEY or TOKEN. One that starts with KEY is read whole at
# the start of a word of a name, and one that starts with TOKEN wherever it stands, so it names
# no key and no token there (``KEYBOARD``, ``--keyspace``, ``-keyint``, ``TOKENIZER_PATH``,
# ``--detokenize``); after more letters a KEY word is a key (``APIKEYWORD``).
ORDINARY_STARTS: Final[tuple[str, ...]] = (
    "KEYBOARD",
    "KEYWORD",
    "KEYSPACE",
    "KEYFRAME",
    "KEYINT",
    "KEYNOTE",
    "KEYSTROKE",
    "KEYPAD",
    "KEYMAP",
    "KEYCODE",
    "KEYSYM",
    "KEYBIND",
    "KEYPRESS",
    "KEYPOINT",
    "KEYSTONE",
    "KEYHOLE",
    "KEYED",
    "KEYLESS",
    "KEYCLOAK",
    "KEYDB",
    "TOKENIZE",
    "TOKENIZATION",
    "TOKENIZING",
    "TOKENISE",
    "TOKENISATION",
    "TOKENISING",
)
_KEY_OR_TOKEN = re.compile("KEY|TOKEN")
# What a word of a name is, or ends in, when it names a password, a pass code
# or a personal access token.
PASSWORD_ENDINGS: Final[tuple[str, ...]] = (
    "PASS",
    "PASSWD",
    "PWD",
    "PW",
    "PASSPHRASE",
    "PASSCODE",
    "PAT",
)
# Words that are a credential when they are a whole word of a name: a bearer
# token, a JSON web token, the short words for credentials, and the pass phrase
# arguments ``-passin`` and ``-passout``.
CREDENTIAL_WHOLE_WORDS: Final[frozenset[str]] = frozenset(
    {"BEARER", "JWT", "JWTS", "CRED", "CREDS", "PASSIN", "PASSOUT"}
)
# Words that name an authentication. Such a word makes a name a credential
# wherever it stands (``--auth``, ``--auth-header``, ``DOCKER_AUTH_CONFIG``,
# ``--authenticate``), unless the first word makes the name a switch or the
# word after it is one of ``AUTH_SETTINGS`` (``--auth-type``).
AUTH_WORDS: Final[frozenset[str]] = frozenset(
    {"AUTH", "OAUTH", "AUTHORIZATION", "AUTHENTICATE", "AUTHENTICATION"}
)
# What a word of a name may glue before a word of ``AUTH_WORDS`` and still name no credential:
# a word of ``SWITCH_WORDS`` (``NOAUTH``) or a start that undoes or repeats the authentication
# (``DEAUTH``, ``REAUTH``, ``UNAUTH``, ``NONAUTH``). Any other start glued to it names one
# (``MASTERAUTH``, ``BASICAUTH``).
AUTH_LEADS_NOT_SECRET: Final[frozenset[str]] = frozenset({"DE", "RE", "UN", "NON"})
# The words of ``AUTH_WORDS`` a glued word may end in, the longest first.
_AUTH_ENDS: Final[tuple[str, ...]] = ("AUTHENTICATION", "AUTHORIZATION", "AUTHENTICATE", "AUTH")
# A word after one of ``AUTH_WORDS`` that names a kind or a setting of the
# authentication, not the credential itself.
AUTH_SETTINGS: Final[frozenset[str]] = frozenset(
    {
        "TYPE",
        "TYPES",
        "MODE",
        "MODES",
        "METHOD",
        "METHODS",
        "SCHEME",
        "SCHEMES",
        "MECHANISM",
        "MECHANISMS",
        "PROTOCOL",
        "PROVIDER",
        "BACKEND",
        "PLUGIN",
        "SOURCE",
        "VERSION",
        "TIMEOUT",
        "PORT",
        "LEVEL",
    }
)
# Words that are a credential when they are the last word of a name
# (``--cookie``, ``X-Amz-Signature``, ``sig``), unless the first word makes
# the name a switch.
CREDENTIAL_LAST_WORDS: Final[frozenset[str]] = frozenset(
    {"COOKIE", "COOKIES", "SIGNATURE", "SIGNATURES", "SIG", "SAS"}
)
# A first word that makes a name a switch that turns something on or off (``--no-auth``).
SWITCH_WORDS: Final[frozenset[str]] = frozenset(
    {"NO", "ENABLE", "DISABLE", "SKIP", "REQUIRE", "USE", "WITH", "WITHOUT", "ALLOW", "ANONYMOUS"}
)
# Words that end like a credential word but name something ordinary.
ORDINARY_WORDS: Final[frozenset[str]] = frozenset(
    {
        "HOTKEY",
        "MONKEY",
        "TURKEY",
        "DONKEY",
        "HOCKEY",
        "JOCKEY",
        "WHISKEY",
        "LACKEY",
        "TURNKEY",
        "SECRETARY",
        "BYPASS",
        "SURPASS",
        "OVERPASS",
        "UNDERPASS",
        "TRESPASS",
        "COMPASS",
        "ENCOMPASS",
        "COMPAT",
        "EXPAT",
        "LIBEXPAT",
        "SPAT",
    }
)
# Names made of exactly these words name no credential (``--token-file``, ``TOKEN_FILE``); the
# same words glued together or after another word still do (``TOKENFILE``, ``HF_TOKEN_FILE``).
NAMES_NOT_SECRET: Final[frozenset[tuple[str, ...]]] = frozenset({("TOKEN", "FILE")})
# A word before KEY that names a key which orders, places or groups data, not a secret
# (``--sort-key``, ``--multi-key-get``, ``--merge_keys``, ``--use_existing_keys``).
KEYS_NOT_SECRET: Final[frozenset[str]] = frozenset(
    {"SORT", "PARTITION", "SHARD", "JOIN", "FOREIGN", "ROW", "HOT", "MULTI", "MERGE", "EXISTING"}
)
# A word before TOKEN that names one token of a model's vocabulary, not a secret.
TOKEN_NOT_SECRET: Final[frozenset[str]] = frozenset(
    {
        "BOS",
        "EOS",
        "PAD",
        "UNK",
        "SEP",
        "CLS",
        "MASK",
        "STOP",
        "SPECIAL",
        "FIRST",
        "PREFILL",
        "SEED",
    }
)
# A word before TOKENS that names tokens which are secrets, whatever comes before it.
TOKENS_SECRET: Final[frozenset[str]] = frozenset(
    {"API", "ACCESS", "AUTH", "BEARER", "REFRESH", "SESSION"}
)
# Words before TOKENS that make the name a count or a size of tokens (``--max-tokens``,
# ``--max-num-batched-tokens``). TOKENS after any other word looks like a credential.
TOKENS_COUNTED: Final[tuple[str, ...]] = (
    "MAX",
    "MIN",
    "NUM",
    "N",
    "TOTAL",
    "COUNT",
    "LIMIT",
    "BUDGET",
    "INPUT",
    "OUTPUT",
    "PROMPT",
    "COMPLETION",
    "RESPONSE",
    "REQUEST",
    "NEW",
    "PREFILL",
    "DECODE",
    "BATCH",
    "BATCHED",
    "WAITING",
    "QUEUED",
    "SCHEDULED",
    "SPECIAL",
    "SPECULATIVE",
    "SPEC",
    "DRAFT",
    "LOOKAHEAD",
    "CONTEXT",
    "PREFIX",
    "CACHED",
    "GENERATED",
    "GEN",
    "REASONING",
    "THINKING",
    "EXTRA",
    "ADDED",
    "STOP",
    "BAD",
    "EOS",
    "BOS",
    "PAD",
    "PADDING",
    "IMAGE",
    "TEXT",
    "AUDIO",
    "VIDEO",
    "VISION",
    "CHUNK",
    "WINDOW",
    "OVERLAP",
    "TARGET",
)
# A text that is only words of ``TOKENS_COUNTED`` and digits, as ``MAXNEW`` in ``MAXNEWTOKENS``.
_COUNTED_LEAD = re.compile("(?:[0-9]+|" + "|".join(TOKENS_COUNTED) + ")+")
# Words right after KEY, KEYS, TOKEN or TOKENS that make the name a size, a bound, a count, a
# prefix, a pattern, a range, a rate, a kind or another measure or treatment of keys or tokens,
# not a credential (``--key-size``, ``--key-prefix``, ``--keys-per-prefix``, ``--keybits``,
# ``--keyrange_num``, ``--key-type``, ``--token-budget``, ``--token-rate``,
# ``--token-healing``, ``--dbo-decode-token-threshold``, ``inter_token_latency``).
KEY_MEASURES: Final[frozenset[str]] = frozenset(
    {
        "SIZE",
        "SIZES",
        "LEN",
        "LENGTH",
        "BITS",
        "COUNT",
        "NUM",
        "MIN",
        "MAX",
        "MINIMUM",
        "MAXIMUM",
        "PREFIX",
        "PATTERN",
        "RANGE",
        "RATE",
        "TYPE",
        "STDDEV",
        "MEDIAN",
        "MEAN",
        "THRESHOLD",
        "LIMIT",
        "BUDGET",
        "PER",
        "LATENCY",
        "HEALING",
    }
)
# The words of an id after KEY or TOKEN: a measure after them still makes a measure of keys
# or tokens (``--key_id_range``), while the id alone names a credential (``--key-id``).
_ID_WORDS: Final[tuple[str, ...]] = ("ID", "IDS")
# Words before KEY, KEYS or TOKEN that make the name a bound or a count of keys or tokens, not
# a credential (``--max-keys``, ``--num-keys``, ``NumKeys``, ``MAX_TOKEN``, ``MAXTOKEN``).
KEYS_COUNTED: Final[frozenset[str]] = frozenset(
    {"MAX", "MIN", "NUM", "TOTAL", "COUNT", "MAXIMUM", "MINIMUM"}
)
# Words that name a credential when they stand anywhere before KEY or TOKEN: a name that holds
# one stays a credential after a measure or a count (``--api-key-prefix``,
# ``--access-token-limit``, ``MAX_API_KEYS``).
CREDENTIAL_LEADS: Final[frozenset[str]] = TOKENS_SECRET | {"PRIVATE"}
# One word that glues a count to KEY, KEYS or TOKEN (``MAXKEYS``, ``numkeys``, ``MAXTOKEN``).
_COUNTED_KEYS = re.compile(r"(?:MAX|MIN|NUM)(?:KEYS?|TOKEN)")

Role = Literal["subject", "baseline", "twin", "control"]
Better = Literal["lower", "higher", "none"]
# The way a statistic lies from no difference: below it or above it.
Direction = Literal["lower", "higher"]
CaseKind = Literal["time", "rate", "efficiency", "count", "other"]
Phase = Literal["warmup", "round"]
GateMode = Literal["off", "warn", "enforce"]
GateStatus = Literal["pass", "fail", "degraded", "unavailable"]
EndStatus = Literal["complete", "failed", "interrupted"]
PullPolicy = Literal["missing", "never", "always"]
Engine = Literal["auto", "docker", "podman"]
Outcome = Literal["better", "worse", "higher", "lower", "tie", "unresolved", "no_verdict"]
Reason = Literal[
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
]
Verdict = Literal[
    "FASTER", "SLOWER", "BETTER", "WORSE", "HIGHER", "LOWER", "TIE", "UNRESOLVED", "NO VERDICT"
]
# The positive control: whether it runs, how it doubles the work, how it came out.
ControlMode = Literal["on", "off"]
ControlVia = Literal["repeat", "factor"]
ControlStatus = Literal["ok", "failed", "not_run"]
# The explain step and the charts.
ExplainMode = Literal["always", "auto", "off"]
CallGraph = Literal["fp", "dwarf", "lbr"]
PlotMode = Literal["auto", "on", "off"]
InstrumentName = Literal["counters", "stacks", "pystacks"]
StackInstrument = Literal["stacks", "pystacks"]
InstrumentStatus = Literal["ok", "skipped", "failed"]
InstrumentReason = Literal[
    "not_installed",
    "not_permitted",
    "not_in_image",
    "no_capability",
    "launcher_cannot",
    "side_changed",
    "lock",
    "launch_failed",
    "interpreter_too_old",
]
FindingId = Literal[
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
]
DiagnosticsStatus = Literal["pending", "written", "skipped", "off", "failed", "interrupted"]
DiagnosticsReason = Literal["mode_auto_no_difference", "lock", "no_instrument"]
PlotsStatus = Literal["pending", "drawn", "not_drawn", "off", "interrupted"]
PlotsReason = Literal["extra_missing", "failed"]
MachineStatus = Literal["quiet", "busy", "unknown"]
FloorSource = Literal["twins", "supplied"]
FloorMode = Literal["TWO-SIDED", "ONE-SIDED", "NONE"]
Scale = Literal["ratio", "percent"]
FloorUnit = Literal["fraction", "percent"]
LevelKind = Literal["concurrency", "rate"]
FailOn = Literal["better", "worse", "unresolved", "no_verdict"]
# What a results document may name: the built-in kinds of side, drivers and
# machine checks, ``rows`` for a capture made from rows, and ``plugin`` in
# place of every name a plug-in chose.
ShownKind = Literal["cmd", "image", "python", "venv", "conda", "serve", "file", "rows", "plugin"]
ShownGate = Literal["cpus", "quiet", "census", "plugin"]
ShownDriver = Literal[
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
]
RefusalScope = Literal["experiment", "case"]
NotComputed = Literal["too_few_rounds", "too_many_disturbed"]

ROLES: Final[tuple[str, ...]] = get_args(Role)
BETTER: Final[tuple[str, ...]] = get_args(Better)
CASE_KINDS: Final[tuple[str, ...]] = get_args(CaseKind)
GATE_MODES: Final[tuple[str, ...]] = get_args(GateMode)
GATE_STATUSES: Final[tuple[str, ...]] = get_args(GateStatus)
END_STATUSES: Final[tuple[str, ...]] = get_args(EndStatus)
OUTCOMES: Final[tuple[str, ...]] = get_args(Outcome)
VERDICTS: Final[tuple[str, ...]] = get_args(Verdict)
MACHINE_STATUSES: Final[tuple[str, ...]] = get_args(MachineStatus)
FAIL_ON: Final[tuple[str, ...]] = get_args(FailOn)
SCALES: Final[tuple[str, ...]] = get_args(Scale)
LEVEL_KINDS: Final[tuple[str, ...]] = get_args(LevelKind)
CONTROL_MODES: Final[tuple[str, ...]] = get_args(ControlMode)
CONTROL_VIAS: Final[tuple[str, ...]] = get_args(ControlVia)
CONTROL_STATUSES: Final[tuple[str, ...]] = get_args(ControlStatus)
EXPLAIN_MODES: Final[tuple[str, ...]] = get_args(ExplainMode)
CALL_GRAPHS: Final[tuple[str, ...]] = get_args(CallGraph)
PLOT_MODES: Final[tuple[str, ...]] = get_args(PlotMode)
INSTRUMENTS: Final[tuple[str, ...]] = get_args(InstrumentName)
STACK_INSTRUMENTS: Final[tuple[str, ...]] = get_args(StackInstrument)
INSTRUMENT_STATUSES: Final[tuple[str, ...]] = get_args(InstrumentStatus)
INSTRUMENT_REASONS: Final[tuple[str, ...]] = get_args(InstrumentReason)
FINDING_IDS: Final[tuple[str, ...]] = get_args(FindingId)
DIAGNOSTICS_STATUSES: Final[tuple[str, ...]] = get_args(DiagnosticsStatus)
DIAGNOSTICS_REASONS: Final[tuple[str, ...]] = get_args(DiagnosticsReason)
PLOTS_STATUSES: Final[tuple[str, ...]] = get_args(PlotsStatus)
PLOTS_REASONS: Final[tuple[str, ...]] = get_args(PlotsReason)

# The outcomes of a case that judges, and of a case whose ``better`` is
# ``none``: it describes, so its outcomes name a direction and no judgement.
OUTCOMES_JUDGED: Final[tuple[str, ...]] = ("better", "worse", "tie", "unresolved", "no_verdict")
OUTCOMES_DESCRIBED: Final[tuple[str, ...]] = ("higher", "lower", "tie", "unresolved", "no_verdict")

# The findings made from resource figures and counters alone. They hold no
# name from the user's code; every other finding names a function or a shared
# object and is shown only where such names may be shown.
FINDINGS_WITHOUT_NAMES: Final[tuple[str, ...]] = (
    "cores_used",
    "cpu_time_split",
    "peak_memory",
    "context_switches",
    "page_faults",
    "instructions",
    "instructions_per_cycle",
    "cache_misses",
    "branch_misses",
)
# Words a finding never uses: a finding describes a difference and names no cause.
FINDING_FORBIDDEN_WORDS: Final[tuple[str, ...]] = (
    "because",
    "causes",
    "due to",
    "explains",
    "faster thanks to",
)
# The events the ``counters`` instrument counts, as ``perf`` names them.
COUNTER_EVENTS: Final[tuple[str, ...]] = (
    "instructions",
    "cycles",
    "branches",
    "branch-misses",
    "cache-references",
    "cache-misses",
    "task-clock",
    "context-switches",
    "cpu-migrations",
    "page-faults",
)
# Why an instrument did not run, in words a loud note uses. Where a setting or
# a capability forbids the instrument, the words name it.
INSTRUMENT_REASON_WORDS: Final[Mapping[str, str]] = {
    "not_installed": "its program is not installed",
    "not_permitted": (
        "the system does not permit it: the kernel setting perf_event_paranoid forbids it"
    ),
    "not_in_image": "the image does not hold its program",
    "no_capability": (
        "the container has no capability to use performance counters: "
        "the launch setting perf_counters gives it"
    ),
    "launcher_cannot": "the side cannot be started under the instrument",
    "side_changed": "the identity of the side differs from the one the run recorded",
    "lock": "a lock could not be taken",
    "launch_failed": "the launch under the instrument failed",
    "interpreter_too_old": "the interpreter of the side is older than Python 3.8",
}
# The explain step launches each side once under each of two instruments:
# counters, and one of the two that sample stacks.
EXPLAIN_LAUNCHES_PER_SIDE: Final = 2
# The oldest interpreter of a side the sampler of ``pystacks`` runs on.
PYSAMPLER_MIN_PYTHON: Final[tuple[int, int]] = (3, 8)
# The charts a run can draw, by the first part of their file names.
CHARTS: Final[tuple[str, ...]] = ("verdict", "rounds", "noise", "resources")

# The unit of a noise floor, a bar and a gap under each scale of a rule.
FLOOR_UNITS: Final[Mapping[str, FloorUnit]] = {"ratio": "fraction", "percent": "percent"}
# The first letter of a load-level label under each kind of level.
LEVEL_PREFIXES: Final[Mapping[str, str]] = {"concurrency": "c", "rate": "r"}

# The witnesses of a launch. The first three have a threshold; the busy cores
# on the CPUs that share a cache with the pinned set are recorded and decide
# nothing.
WITNESS_BUSY_CORES: Final = "busy_cores"
WITNESS_BUSY_CORES_CACHE: Final = "busy_cores_cache"
WITNESS_GPU_OTHER_PROCESSES: Final = "gpu_other_processes"
WITNESS_GPU_THROTTLE_EVENTS: Final = "gpu_throttle_events"
WITNESSES_WITH_THRESHOLD: Final[tuple[str, ...]] = (
    WITNESS_BUSY_CORES,
    WITNESS_GPU_OTHER_PROCESSES,
    WITNESS_GPU_THROTTLE_EVENTS,
)
WITNESSES: Final[tuple[str, ...]] = (
    WITNESS_BUSY_CORES,
    WITNESS_BUSY_CORES_CACHE,
    WITNESS_GPU_OTHER_PROCESSES,
    WITNESS_GPU_THROTTLE_EVENTS,
)
# The witnesses that count busy cores: the only ones whose value can hold the
# launch's own load.
WITNESSES_BUSY_CORES: Final[tuple[str, ...]] = (WITNESS_BUSY_CORES, WITNESS_BUSY_CORES_CACHE)

# The bits of a GPU's active clock reasons mask that are no throttle event:
# an idle GPU (0x1), the applications clocks setting (0x2) and the display
# clock setting (0x100). Every other bit counts, including bits a later
# driver adds.
CLOCK_REASONS_NOT_COUNTED: Final = 0x1 | 0x2 | 0x100


def clock_events(before: int, mask: int) -> int:
    """Count the throttle events in one reading of a GPU's clock reasons mask.

    ``before`` is the mask of the same GPU's reading before it, 0 for its
    first reading. An event is a counted reason that is active in ``mask``
    and was not active in ``before``: a reason held over many readings is
    one event, however often the GPU is read.
    """
    return (mask & ~before & ~CLOCK_REASONS_NOT_COUNTED).bit_count()


# Reasons, grouped by the outcome they belong to.
REASONS_UNRESOLVED: Final[tuple[str, ...]] = (
    "inside_noise",
    "not_significant",
    "order_unbalanced",
    "sensitive_to_disturbed_rounds",
)
# In the order that picks the single main reason when several apply.
REASONS_NO_VERDICT: Final[tuple[str, ...]] = (
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
# Reserved for launchers added later; never produced by this release.
REASONS_RESERVED: Final[tuple[str, ...]] = ("side_failed", "more_than_one_node")
REASONS: Final[tuple[str, ...]] = get_args(Reason)

# Side kinds built into the package.
KIND_CMD: Final = "cmd"
KIND_IMAGE: Final = "image"
KIND_PYTHON: Final = "python"
KIND_VENV: Final = "venv"
KIND_CONDA: Final = "conda"
KIND_SERVE: Final = "serve"
KIND_FILE: Final = "file"
KIND_ROWS: Final = "rows"
BUILTIN_KINDS: Final[tuple[str, ...]] = (
    KIND_CMD,
    KIND_IMAGE,
    KIND_PYTHON,
    KIND_VENV,
    KIND_CONDA,
    KIND_SERVE,
    KIND_FILE,
)
SHOWN_KINDS: Final[tuple[str, ...]] = get_args(ShownKind)
WORKLOAD_PLACEHOLDER: Final = "{workload}"
# The kinds of side whose ``wall`` value holds the start of a process on the
# host. The cost of a launch is measured when the lineup has one of them.
LAUNCH_COST_KINDS: Final[tuple[str, ...]] = (KIND_CMD, KIND_PYTHON, KIND_VENV, KIND_CONDA)

# Drivers and machine checks built into the package.
BUILTIN_DRIVERS: Final[tuple[str, ...]] = (
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
)
BUILTIN_GATES: Final[tuple[str, ...]] = ("cpus", "quiet", "census")
SHOWN_GATES: Final[tuple[str, ...]] = get_args(ShownGate)
# What a results document shows in place of a name that a plug-in chose: the
# kind of a side, the name of a machine check. Plug-in names are never written.
PLUGIN_NAME: Final = "plugin"

# The identity key of the output of a side's identify command. It stays in the
# capture; the hashes read it as ``hashed_output`` says.
IDENTIFY_OUTPUT_KEY: Final = "identify_output"
# The key of the identity that holds the path of a command side's executable.
EXECUTABLE_KEY: Final = "executable"
# The identity keys of an image side that runs the shared workload behind its image's own
# entrypoint: that entrypoint, a sequence of texts that is empty when the image has none, and the
# first word of the image's command. They stay in the capture, and no published hash reads
# them: the image ID already tells one image from another.
IMAGE_ENTRYPOINT_KEY: Final = "image_entrypoint"
IMAGE_COMMAND_PROGRAM_KEY: Final = "image_command_program"

# Identity keys a results document may show. Everything else a side records
# about itself (paths, prefixes, command output) stays in the capture.
PUBLIC_IDENTITY_KEYS: Final[tuple[str, ...]] = (
    "image_id",
    "digests",
    "platform",
    "python_version",
    "packages_sha256",
    "executable_sha256",
    "argv_sha256",
    "args_sha256",
    "files_sha256",
    "identify_sha256",
)

# The shape of each of those values. A hash is lower-case hex, with or without
# the name of its algorithm in front, as in ``sha256:0f3a...``. It holds no
# registry, no repository and no path.
PUBLIC_IDENTITY_TEXT_KEYS: Final[tuple[str, ...]] = ("platform", "python_version")
PUBLIC_IDENTITY_LIST_KEYS: Final[tuple[str, ...]] = ("digests", "files_sha256")
HASH_PATTERN: Final = r"^([a-z0-9]+([+._-][a-z0-9]+)*:)?[0-9a-f]{12,}$"

# Case ids and metric names that more than one module writes or reads.
CASE_WALL: Final = "wall"
CASE_LAUNCH: Final = "launch"
CASE_STARTUP_READY: Final = "startup/ready_s"
CASE_STARTUP_FIRST_ANSWER: Final = "startup/first_answer_s"

# Case ids under these prefixes are the tool's own: the resource figures of a
# launch and the start-up cases of a serving side. A driver's own case id may
# not start with one of them.
RES_PREFIX: Final = "res/"
STARTUP_PREFIX: Final = "startup/"
RESERVED_CASE_PREFIXES: Final[tuple[str, ...]] = (RES_PREFIX, STARTUP_PREFIX)

# The resource figures of a launch: case id and unit. Each describes and does
# not judge: its ``better`` is ``none`` and it is always secondary.
CASE_RES_USER: Final = "res/user"
CASE_RES_SYS: Final = "res/sys"
CASE_RES_CORES: Final = "res/cores"
CASE_RES_RSS_PEAK: Final = "res/rss_peak"
CASE_RES_CTX_VOLUNTARY: Final = "res/ctx_voluntary"
CASE_RES_CTX_INVOLUNTARY: Final = "res/ctx_involuntary"
CASE_RES_FAULTS_MAJOR: Final = "res/faults_major"
CASE_RES_FAULTS_MINOR: Final = "res/faults_minor"
UNIT_COUNT: Final = "count"
RESOURCE_CASES: Final[Mapping[str, str]] = {
    CASE_RES_USER: "s",
    CASE_RES_SYS: "s",
    CASE_RES_CORES: "cores",
    CASE_RES_RSS_PEAK: "bytes",
    CASE_RES_CTX_VOLUNTARY: UNIT_COUNT,
    CASE_RES_CTX_INVOLUNTARY: UNIT_COUNT,
    CASE_RES_FAULTS_MAJOR: UNIT_COUNT,
    CASE_RES_FAULTS_MINOR: UNIT_COUNT,
}
# Units of time. A case made from rows or from the text input format is of
# kind ``time`` when its unit is one of them.
TIME_UNITS: Final[tuple[str, ...]] = ("ns", "us", "ms", "s")

# The positive control. The median ratio of the control against the baseline
# that twice the work must read, by the direction of the case.
CONTROL_EXPECTED: Final[Mapping[str, float]] = {"lower": 2.0, "higher": 0.5}
# A tolerance of the control lies below this. At one half of the expected 2.0
# the tolerance reaches a ratio of 1.0, which is what a run reads whose work
# did not double: with such a tolerance that control would not fail.
CONTROL_TOLERANCE_BELOW: Final = 0.5
# The length of the environment pad of a round, in bytes: from zero to this.
ENV_PAD_MAX: Final = 4096
# Keys of the ``seeds`` table of a capture header.
SEED_DRIVER: Final = "driver"
SEED_ENV_PAD: Final = "env_pad"
# The empty command whose launches measure what a launch costs.
EMPTY_COMMAND: Final = "true"
METRIC_ENERGY_J: Final = "energy_j[gpu]"
METRIC_MEAN_POWER_W: Final = "mean_power_w[gpu]"
METRIC_TOKENS_PER_JOULE: Final = "tokens_per_joule[gpu]"
ENERGY_SCOPE: Final = "gpu"
ENERGY_EXCLUDES: Final[tuple[str, ...]] = (
    "cpu",
    "memory",
    "storage",
    "cooling",
    "power supply losses",
)

# Names of the figures of one comparison.
FIGURE_NAMES: Final[tuple[str, ...]] = (
    "ratio",
    "statistic",
    "speedup",
    "percent",
    "p",
    "p_corrected",
    "bar",
    "floor_subject",
    "floor_baseline",
    "n",
    "verdict",
)
# The figures of a run that measured the cost of a launch.
FIGURE_LAUNCH_COST_MEDIAN: Final = "launch_cost.median"
FIGURE_LAUNCH_COST_SPREAD: Final = "launch_cost.spread"

# Note codes for the stamps the analysis and the runner put on their output.
NOTE_UNBALANCED: Final = "unbalanced"
NOTE_ALLOW_INCOMPLETE: Final = "allow_incomplete"
NOTE_ALLOW_MIXED_MACHINES: Final = "allow_mixed_machines"
NOTE_ASSUME_INTERLEAVED: Final = "assume_interleaved"
NOTE_FLOOR_SUPPLIED: Final = "floor_supplied"
NOTE_FLOOR_PROVISIONAL: Final = "floor_provisional"
NOTE_FLOOR_ONE_SIDED: Final = "floor_one_sided"
NOTE_TWIN_DIFFERS: Final = "twin_differs"
# Two sides with one fingerprint whose specs differ in more than a credential's value.
NOTE_HIDDEN_DIFFERENCE: Final = "sides_differ_in_hidden_value"
# Two sides that are one side, compared because identical sides were allowed.
NOTE_DECLARED_IDENTICAL: Final = "sides_declared_identical"
NOTE_UNDERPOWERED: Final = "underpowered"
NOTE_NEW_CASE: Final = "case_after_warmup"
NOTE_TOOL_VERSION_UNTESTED: Final = "tool_version_untested"
NOTE_DRIVERS_DIFFER: Final = "drivers_differ"
NOTE_UNPINNED_MIXED_CORES: Final = "unpinned_mixed_core_types"
NOTE_ENERGY_COUNTER_DISAGREES: Final = "energy_counter_disagrees"
NOTE_WITNESS_FAILED: Final = "witness_probe_failed"
NOTE_WITNESS_UNDECIDED: Final = "witness_undecided"
NOTE_IDENTITY_UNCHECKED: Final = "identity_not_checked"
NOTE_GPU_BUSY_BEFORE_START: Final = "gpu_busy_before_start"
NOTE_TORN_ROUND: Final = "torn_round_left_out"
NOTE_MALFORMED_ROWS: Final = "malformed_rows"
# Pooled captures that read one case from ids differing only in folders, or only in a secret.
NOTE_POOL_FOLDERS_MERGED: Final = "pool_folders_merged"
NOTE_POOL_SECRETS_MERGED: Final = "pool_secrets_merged"
# Two cases, each on one side only, whose names differ only in the mark of a cut that dropped words.
NOTE_CASE_NAMED_APART: Final = "case_named_apart"
# The positive control, the cost of a launch and where the tool runs.
NOTE_CONTROL_FAILED: Final = "positive_control_failed"
NOTE_CONTROL_NOT_JUDGED: Final = "positive_control_not_judged"
NOTE_CONTROL_CANNOT_REPEAT: Final = "positive_control_cannot_repeat"
NOTE_CONTROL_CASE_MISSING: Final = "positive_control_case_missing"
NOTE_LAUNCH_COST_SHARE: Final = "launch_cost_share"
NOTE_LAUNCH_COST_NOT_MEASURED: Final = "launch_cost_not_measured"
NOTE_TOOL_ON_PINNED_CPUS: Final = "tool_on_pinned_cpus"
NOTE_RESOURCE_FIGURE_MISSING: Final = "resource_figure_missing"
# The explain step, the charts and the report page.
NOTE_INSTRUMENT_SKIPPED: Final = "instrument_skipped"
NOTE_EXPLAIN_SKIPPED: Final = "explain_skipped"
NOTE_EXPLAIN_FAILED: Final = "explain_failed"
NOTE_STACK_INSTRUMENTS_DIFFER: Final = "stack_instruments_differ"
NOTE_STACKS_NOT_SAMPLED: Final = "stacks_not_sampled"
NOTE_FINDING_LEFT_OUT: Final = "finding_left_out"
NOTE_CHARTS_NOT_DRAWN: Final = "charts_not_drawn"
NOTE_CHARTS_FAILED: Final = "charts_failed"
NOTE_ROUND_CHARTS_LEFT_OUT: Final = "round_charts_left_out"
NOTE_CHART_WITHOUT_DATA: Final = "chart_without_data"
NOTE_PAGE_FAILED: Final = "report_page_failed"

_T = TypeVar("_T")
_D = TypeVar("_D")

# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Serialise to the one JSON text used wherever a hash is taken."""
    return json.dumps(_encode(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(text: str) -> str:
    """Return the SHA-256 of a text as lower-case hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# One word of a name: a run of capitals not followed by a small letter, a
# capital with the small letters after it, a run of small letters, or digits.
_NAME_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def name_words(name: str) -> tuple[str, ...]:
    """Split a name into its words, in capitals.

    Words end at every character that is no letter or digit (``-``, ``_``,
    ``.`` and others), where small letters turn to capitals, and between
    letters and digits: ``apiKey``, ``API_KEY`` and ``api-key`` all give
    ``("API", "KEY")``.
    """
    return tuple(word.upper() for word in _NAME_WORD.findall(name))


def _ordinary_word(word: str) -> bool:
    """Say whether a word of a name is an ordinary word that only ends like a credential word."""
    return word in ORDINARY_WORDS or (word.endswith("S") and word[:-1] in ORDINARY_WORDS)


def _secret_tokens(word: str, before: str | None) -> bool:
    """Say whether a word that ends in ``TOKENS`` names secrets, read with what comes before it.

    What comes before is the start of the word when ``TOKENS`` is glued to it
    (``APITOKENS``), else the word before. Nothing before (``tokens``) and a
    count (``max-tokens``, ``MAXNEWTOKENS``) name no secret; any other word does.
    """
    lead = word[: -len("TOKENS")] or before
    if lead is None:
        return False
    if lead in TOKENS_SECRET:
        return True
    return _COUNTED_LEAD.fullmatch(lead) is None


def _connection_string(words: Sequence[str], k: int) -> bool:
    """Say whether word ``k`` ends a connection string's name (``CONNECTION_STRING``)."""
    word = words[k]
    if word.endswith(("CONNECTIONSTRING", "CONNECTIONSTRINGS", "CONNSTRING", "CONNSTR")):
        return True
    return k > 0 and word in ("STRING", "STRINGS", "STR") and words[k - 1] in ("CONNECTION", "CONN")


def _first_lead(words: Sequence[str]) -> int:
    """Return where the first word that holds a word of ``CREDENTIAL_LEADS`` stands, or the length.

    A word that glues other letters to such a word counts as it does, as the
    same words written apart would: ``MYAPI_KEY_PREFIX`` and ``MYAPIKEYPREFIX``
    are read as ``MY_API_KEY_PREFIX`` is.
    """
    return next(
        (k for k, word in enumerate(words) if any(lead in word for lead in CREDENTIAL_LEADS)),
        len(words),
    )


def _measured(words: Sequence[str], k: int, lead: int) -> bool:
    """Say whether word ``k``, a KEY, KEYS, TOKEN or TOKENS, names a measure or a count of them.

    It does when the next word is one of ``KEY_MEASURES`` (``--key-size``,
    ``--token-budget``), or is ``ID`` or ``IDS`` followed by one
    (``--key_id_range``), when the word is KEY, KEYS or TOKEN after one of
    ``KEYS_COUNTED`` (``--max-keys``, ``MAX_TOKEN``) or glues such a count to
    itself (``MAXKEYS``, ``MAXTOKEN``), or when it is KEYS alone (``--keys``),
    unless a word that holds a word of ``CREDENTIAL_LEADS`` comes before it
    (``--api-key-prefix``, ``--myapi-key-prefix``): ``lead`` is where the
    first such word stands (``_first_lead``).
    """
    word = words[k]
    if lead < k:
        return False
    after = words[k + 1] if k + 1 < len(words) else None
    if after in _ID_WORDS and k + 2 < len(words):
        after = words[k + 2]
    if word in ("KEY", "KEYS", "TOKEN", "TOKENS") and after in KEY_MEASURES:
        return True
    if word in ("KEY", "KEYS", "TOKEN") and k and words[k - 1] in KEYS_COUNTED:
        return True
    if _COUNTED_KEYS.fullmatch(word) is not None:
        return True
    return word == "KEYS" and len(words) == 1


def _secret_word(words: Sequence[str], k: int, lead: int) -> bool:
    """Say whether word ``k`` of a name, read with the words around it, makes it a credential.

    ``lead`` is where the first word that holds a word of ``CREDENTIAL_LEADS``
    stands (``_first_lead``).
    """
    word = words[k]
    before = words[k - 1] if k else None
    if _ordinary_word(word) or _measured(words, k, lead):
        return False
    if k == 0 and word == "PASS" and len(words) > 1 and words[1] == "CONFIG":
        return False
    if word in CREDENTIAL_WHOLE_WORDS:
        return True
    switch = k > 0 and words[0] in SWITCH_WORDS
    if word in AUTH_WORDS or _glued_auth(word):
        after = words[k + 1] if k + 1 < len(words) else None
        return not switch and after not in AUTH_SETTINGS
    if word in CREDENTIAL_LAST_WORDS and k == len(words) - 1:
        return not switch
    if word.endswith(PASSWORD_ENDINGS):
        return True
    if word.endswith(KEY_ENDINGS):
        return before not in KEYS_NOT_SECRET
    if word == "TOKEN":
        return before not in TOKEN_NOT_SECRET and not _vocabulary_ids(words, k, lead)
    if word.endswith("TOKEN"):
        return True
    if word.endswith("TOKENS"):
        return _secret_tokens(word, before)
    return _connection_string(words, k)


def _glued_auth(word: str) -> bool:
    """Say whether a word of a name glues another word before a word of ``AUTH_WORDS``.

    ``MASTERAUTH`` and ``PROXYAUTHORIZATION`` do; ``NOAUTH`` and ``DEAUTH``
    start with a word of ``SWITCH_WORDS`` or ``AUTH_LEADS_NOT_SECRET`` and do not.
    """
    end = next((end for end in _AUTH_ENDS if word.endswith(end)), None)
    if end is None or len(word) == len(end):
        return False
    lead = word[: -len(end)]
    return lead not in SWITCH_WORDS and lead not in AUTH_LEADS_NOT_SECRET


def _vocabulary_ids(words: Sequence[str], k: int, lead: int) -> bool:
    """Say whether word ``k``, a TOKEN, names a list of the ids of a model's vocabulary tokens.

    It does when IDS comes after it and a word before it, none of them
    holding a word of ``CREDENTIAL_LEADS`` (``allowed_token_ids``,
    ``logprob_token_ids``); ``lead`` is where the first such word stands
    (``_first_lead``). One id (``TOKEN_ID``), ids alone (``token_ids``) and ids
    after such a word (``api_token_ids``, ``myapi_token_ids``) name a credential.
    """
    return 0 < k < lead and k + 1 < len(words) and words[k + 1] == "IDS"


def _glued_apart(words: Sequence[str], *, tokens_whole: bool = True) -> tuple[str, ...]:
    """Write apart each word that glues more letters to a key, a token or a password.

    A word in which ``KEY`` or ``TOKEN`` is followed by more letters reads as
    written apart after it, the word before a key kept glued to it:
    ``SSHKEYFILE`` reads as ``SSHKEY`` and ``FILE``, so an ordinary word
    before the rest still names nothing secret (``HOTKEYFILE``), and
    ``KEYRINGPATH`` as ``KEY`` and ``RINGPATH``. The longest word of
    ``_KEY_HEADS`` there is taken, unless its last letter starts a word of
    ``CREDENTIAL_ANYWHERE``, or starts a word of ``KEY_MEASURES`` that ends
    the word: ``HOTKEYSECRET`` reads as ``HOTKEY`` and ``SECRET``, not as
    ``HOTKEYS`` and ``ECRET``, and ``KEYSIZE`` as ``KEY`` and ``SIZE``.
    ``TOKEN`` is also written apart from the word before it: ``EOSTOKENID``
    reads as ``EOS``, ``TOKEN`` and ``ID``, so one token of a model's
    vocabulary is shown as ``eos_token_id`` is. So is ``KEY`` or ``KEYS``
    followed by a word of ``KEY_MEASURES`` that ends the word, as a measure
    of keys reads written apart (``SSHKEYSIZE`` as ``SSH``, ``KEY`` and
    ``SIZE``), and ``TOKENS`` is not taken there (``HFTOKENSIZE`` as ``HF``,
    ``TOKEN`` and ``SIZE``). A word of ``ORDINARY_STARTS`` is read whole where a
    word starts (``KEYBOARDLAYOUT``), and one that starts with ``TOKEN``
    wherever it stands (``DETOKENIZE``). ``TOKENS`` followed by more letters
    is read as ``TOKENS`` with ``tokens_whole`` and as ``TOKEN`` and the rest
    without it. What is left after the last key or token is written apart after a
    word of a password before ``GLUED_ENDINGS`` (``PGPASSFILE`` as ``PGPASS``
    and ``FILE``). Each word is read once from start to end.
    """
    out: list[str] = []
    for word in words:
        start = at = 0
        while (found := _KEY_OR_TOKEN.search(word, at)) is not None:
            at = found.start()
            own = next((plain for plain in ORDINARY_STARTS if word.startswith(plain, at)), None)
            if own is not None and (at == start or found.group() == "TOKEN"):
                at += len(own)
                continue
            if found.group() == "KEY":
                head = next(
                    head
                    for head in _KEY_HEADS
                    if word.startswith(head, at)
                    and not word.startswith(CREDENTIAL_ANYWHERE, at + len(head) - 1)
                    and not _measure_ends(word, at + len(head) - 1)
                )
                end = at + len(head)
                lead = at if head in ("KEY", "KEYS") and _measure_ends(word, end) else start
            else:
                lead = at
                end = at + len("TOKEN")
                if (
                    word.startswith("S", end)
                    and not _measure_ends(word, end)
                    and (tokens_whole or end + 1 == len(word))
                ):
                    end += 1
            if end == len(word):
                break
            if lead > start:
                out.append(word[start:lead])
            out.append(word[lead:end])
            start = at = end
        out += _password_apart(word[start:])
    return tuple(out)


# The longest word of ``KEY_MEASURES``: a rest of a word longer than it is no measure.
_LONGEST_MEASURE = max(map(len, KEY_MEASURES))


def _measure_ends(word: str, at: int) -> bool:
    """Say whether what a word holds from ``at`` to its end is one word of ``KEY_MEASURES``."""
    return len(word) - at <= _LONGEST_MEASURE and word[at:] in KEY_MEASURES


def _password_apart(word: str) -> list[str]:
    """Write a word apart after a word of a password glued to ``GLUED_ENDINGS``.

    ``PASSFILEPATH`` reads as ``PASS`` and ``FILEPATH``; any other word is
    returned whole. The endings are taken off from the end of the word, one
    after the other, so the word is read once.
    """
    cut = len(word)
    while (
        end := next((end for end in GLUED_ENDINGS if word.endswith(end, 0, cut)), None)
    ) is not None:
        cut -= len(end)
    if cut < len(word) and word.endswith(PASSWORD_ENDINGS, 0, cut):
        return [word[:cut], word[cut:]]
    return [word]


def _anywhere(name: str, words: Sequence[str]) -> bool:
    """Say whether a word of ``CREDENTIAL_ANYWHERE`` is in a name outside an ordinary word."""
    upper = name.upper()
    if not any(part in upper for part in CREDENTIAL_ANYWHERE):
        return False
    if not any(_ordinary_word(word) for word in words):
        return True
    rest = "_".join(word for word in words if not _ordinary_word(word))
    return any(part in rest for part in CREDENTIAL_ANYWHERE)


def looks_like_credential(name: str) -> bool:
    """Say whether the name of a variable or of an option looks like a credential.

    The name is split into its words (``name_words``). It looks like one when
    it holds ``SECRET``, ``PASSWORD`` or ``CREDENTIAL`` anywhere, or when one
    of its words

    * ends in ``KEY``, ``KEYS``, ``KEYSTORE`` or ``KEYSET`` (``API_KEY``,
      ``APIKEY``, ``TINK_KEYSET``), unless the word before is one of
      ``KEYS_NOT_SECRET`` (``sort-key``, ``--multi-key-get``);
    * is or ends in ``PASS``, ``PASSWD``, ``PWD``, ``PW``, ``PASSPHRASE``,
      ``PASSCODE`` or ``PAT`` (``KEYSTORE_PASS``, ``--storepass``,
      ``MYSQL_PWD``, ``DB_PW``, ``GITHUB_PAT``);
    * is or ends in ``TOKEN`` (``HF_TOKEN``, ``auth-token``), unless the word
      is ``TOKEN`` after a word of ``TOKEN_NOT_SECRET``, which names one token
      of a model's vocabulary (``eos_token_id``, ``--seed-token``);
    * ends in ``TOKENS`` after any word, glued or not (``APITOKENS``,
      ``HF_TOKENS``), unless that word is a count of ``TOKENS_COUNTED``
      (``max-tokens``, ``MAX_NEW_TOKENS``, ``maxtokens``); ``tokens`` alone
      is shown;
    * is ``BEARER``, ``JWT``, ``JWTS``, ``CRED``, ``CREDS``, ``PASSIN`` or
      ``PASSOUT``;
    * is ``AUTH``, ``OAUTH``, ``AUTHORIZATION``, ``AUTHENTICATE`` or
      ``AUTHENTICATION``, wherever it stands (``--auth``, ``BASIC_AUTH``,
      ``--auth-header``, ``--authenticate``), or ends in one glued to the
      letters before it (``MASTERAUTH``, ``BASICAUTH``), unless the first word
      makes the name a switch (``--no-auth``), the glued letters make a switch
      or are one of ``AUTH_LEADS_NOT_SECRET`` (``NOAUTH``, ``--deauth``), or
      the next word is one of ``AUTH_SETTINGS`` (``--auth-type``);
    * is the last word and is ``COOKIE``, ``COOKIES``, ``SIGNATURE``,
      ``SIGNATURES``, ``SIG`` or ``SAS`` (``--cookie``, ``X-Amz-Signature``),
      unless the first word makes the name a switch;
    * ends a connection string's name (``AZURE_STORAGE_CONNECTION_STRING``).

    A word that glues more letters to ``KEY`` or ``TOKEN`` is read as the
    words written apart after it (``_glued_apart``), so ``KEYFILE``,
    ``--keyfile``, ``KEYID``, ``KEYPATH``, ``KEYPAIR``, ``GPG_KEYRING``,
    ``KEYPEM``, ``KEYVALUE``, ``TOKENVALUE`` and ``KEYRINGPATH`` look like
    credentials as ``KEY_FILE``, ``--key-id`` and ``AWS_ACCESS_KEY_ID`` do,
    while a word that starts with a word of ``ORDINARY_STARTS`` (``KEYBOARD``,
    ``TOKENIZER``) is read as that word. A word of a password glued to one of ``GLUED_ENDINGS``
    (``PASSFILE``, ``PGPASSFILE``, ``PASSWDHASH``, ``PASSPHRASETEXT``) is read
    as ``PASS_FILE`` is. A word that
    glues ``TOKENS`` to more letters looks like a credential when either
    ``TOKENS`` or ``TOKEN`` written apart there does (``TOKENSTORE``).

    A word of ``ORDINARY_WORDS`` (``MONKEY``, ``BYPASS``, ``COMPAT``,
    ``SECRETARY``) makes no name a credential. Nor does a ``KEY``, ``KEYS``,
    ``TOKEN`` or ``TOKENS`` word that a setting of size or count reads:

    * one followed by a word of ``KEY_MEASURES``, written apart or glued,
      maybe with ``ID`` or ``IDS`` between them (``--key-size``,
      ``--keysize``, ``--keybits``, ``--key-type``, ``--key_id_range``,
      ``--token-budget``, ``--token-rate``, ``inter_token_latency``);
    * a ``KEY``, ``KEYS`` or ``TOKEN`` after a word of ``KEYS_COUNTED``
      (``--max-keys``, ``--num-keys``, ``MAX_TOKEN``), or glued to one
      (``NumKeys``, ``MAXTOKEN``);
    * ``KEYS`` alone (``--keys``);
    * a ``TOKEN`` after another word and before ``IDS`` (``allowed_token_ids``);

    unless a word that is or holds a word of ``CREDENTIAL_LEADS`` stands
    before it, so ``--api-key-prefix``, ``MAX_API_KEYS`` and
    ``MYAPI_KEY_PREFIX`` still look like credentials.
    ``PASS`` as the first word before ``CONFIG`` names a compiler setting
    (``pass_config``), a name made of the words of ``NAMES_NOT_SECRET`` and
    nothing else is no credential (``--token-file``), and the switches of
    ``CREDENTIAL_SWITCHES`` (``--allow-credentials``) take no value.
    """
    if len(name) <= _KEPT_NAME_LENGTH:
        return _kept_credential_name(name)
    return _name_looks_secret(name)


# The same names of options and variables come back again and again in a command and in the
# commands of a run, so what ``looks_like_credential`` says of each name up to this length is
# kept, for the last ``_KEPT_NAMES`` names read.
_KEPT_NAME_LENGTH: Final = 64
_KEPT_NAMES: Final = 4096


@functools.lru_cache(maxsize=_KEPT_NAMES)
def _kept_credential_name(name: str) -> bool:
    """Say what ``_name_looks_secret`` says of a name, kept for the names read last."""
    return _name_looks_secret(name)


def _name_looks_secret(name: str) -> bool:
    """Say what ``looks_like_credential`` says of a name."""
    found = name_words(name)
    if found in NAMES_NOT_SECRET:
        return False
    for tokens_whole in (True, False) if "TOKENS" in name.upper() else (True,):
        words = _glued_apart(found, tokens_whole=tokens_whole)
        if _anywhere(name, words):
            return True
        lead = _first_lead(words)
        if any(_secret_word(words, k, lead) for k in range(len(words))):
            return True
    return False


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    """Replace the value of every credential-like variable by ``"<redacted>"``."""
    return {k: (REDACTED if looks_like_credential(k) else v) for k, v in env.items()}


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)", re.ASCII)
_DURATION_NUMBER = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
_DURATION_SCALE: Final[Mapping[str, float]] = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(value: str | float | int) -> float:
    """Read a duration in seconds.

    A number, or a text that is a bare number written with digits, is
    seconds. Otherwise the text is one or more parts of a number followed by
    ``ms``, ``s``, ``m`` or ``h``, such as ``90s``, ``10m`` or ``1h30m``.
    White space around the text is ignored. Raises ``ValueError`` on anything
    else, on a negative value and on a value that is not finite.
    """
    if isinstance(value, bool):
        raise ValueError(f"not a duration: {value!r}")
    if isinstance(value, int | float):
        seconds = float(value)
    else:
        text = value.strip()
        if _DURATION_NUMBER.fullmatch(text):
            seconds = float(text)
        else:
            total, at = 0.0, 0
            for part in _DURATION_PART.finditer(text):
                if part.start() != at:
                    raise ValueError(f"not a duration: {value!r}")
                total += float(part.group(1)) * _DURATION_SCALE[part.group(2)]
                at = part.end()
            if at == 0 or at != len(text):
                raise ValueError(f"not a duration: {value!r}")
            seconds = total
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"not a duration: {value!r}")
    return seconds


def min_rounds(n_cases: int, alpha: float = 0.05) -> int:
    """Return the fewest rounds that can give a verdict for ``n_cases`` tested at once.

    It is the smallest ``n`` with ``n_cases * 2 ** (1 - n) < alpha``.
    """
    if n_cases < 1:
        raise ValueError("n_cases must be at least 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie between 0 and 1")
    n = 1
    while n_cases * 2.0 ** (1 - n) >= alpha:
        n += 1
    return n


def trapezoid(times_s: Sequence[float], values: Sequence[float]) -> float:
    """Integrate values over their sample times with the trapezoid rule.

    Fewer than two samples integrate to zero. Times must not decrease.
    """
    if len(times_s) != len(values):
        raise ValueError("times and values differ in length")
    total = 0.0
    for i in range(1, len(times_s)):
        step = times_s[i] - times_s[i - 1]
        if step < 0:
            raise ValueError("sample times must not decrease")
        total += step * (values[i] + values[i - 1]) / 2.0
    return total


def quantile(values: Sequence[float], q: float) -> float:
    """Return the quantile ``q`` of values by linear interpolation between closest ranks.

    ``q`` runs from 0 to 1. The sorted values sit at ranks ``0 .. n - 1``; the
    result lies at rank ``q * (n - 1)``, interpolated between the two values
    around it. ``q = 0.5`` is the median: with an even count, ``(a + b) / 2``
    of the two middle values, evaluated in exactly that order, which is the
    value ``statistics.median`` returns. Percentiles, quartiles and medians
    all use this one method. Where that sum or the difference of the two
    values is beyond the largest float, as for values near it, each value is
    weighted on its own instead (``a / 2 + b / 2``), so finite values give a
    finite quantile.
    """
    if not values:
        raise ValueError("a quantile needs at least one value")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must lie between 0 and 1")
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    a, b = ordered[low], ordered[high]
    if q == 0.5:
        value = (a + b) / 2
        weights = (0.5, 0.5)
    else:
        value = a + (b - a) * (rank - low)
        weights = (high - rank, rank - low)
    if math.isinf(value) and math.isfinite(a) and math.isfinite(b):
        return a * weights[0] + b * weights[1]
    return value


def rotate_reverse(lineup: Sequence[str], round: int) -> tuple[str, ...]:
    """Return the order of one round under the ``rotate-reverse`` schedule.

    ``round`` is 1-based. The lineup is rotated by one entry per round, and
    every second pass through the lineup runs in reverse.
    """
    n = len(lineup)
    if n == 0:
        return ()
    if round < 1:
        raise ValueError("rounds are numbered from 1")
    off = (round - 1) % n
    cyc = ((round - 1) // n) % 2
    order = tuple(lineup[(k + off) % n] for k in range(n))
    if cyc == 1:
        order = tuple(reversed(order))
    return order


def verdict_word(outcome: str, kind: str) -> str:
    """Return the display word for an outcome on a case of the given kind.

    The outcomes ``higher`` and ``lower`` belong to a case whose ``better``
    is ``none``; their words are the same for every kind of case.
    """
    timed = kind == "time"
    words = {
        "better": "FASTER" if timed else "BETTER",
        "worse": "SLOWER" if timed else "WORSE",
        "higher": "HIGHER",
        "lower": "LOWER",
        "tie": "TIE",
        "unresolved": "UNRESOLVED",
        "no_verdict": "NO VERDICT",
    }
    return words[outcome]


def direction_outcome(direction: str, better: str) -> Outcome:
    """Return the outcome of a difference that is significant and lies outside the bar.

    ``direction`` says where the graded statistic lies from no difference:
    ``lower`` when the subject's value is the lower one, ``higher`` when it
    is the higher one. A lower value is ``better`` where lower is better and
    ``worse`` where higher is better, and the other way round for a higher
    value. A case whose ``better`` is ``none`` is not judged: its outcome is
    the direction itself.
    """
    if direction not in ("lower", "higher"):
        raise ValueError(f"a direction is lower or higher: {direction!r}")
    if better not in BETTER:
        raise ValueError(f"better is one of {', '.join(BETTER)}: {better!r}")
    if better == "none":
        return cast("Outcome", direction)
    return "better" if direction == better else "worse"


def outcomes_of(better: str) -> tuple[str, ...]:
    """Return the outcomes a comparison of a case with this ``better`` can have."""
    if better not in BETTER:
        raise ValueError(f"better is one of {', '.join(BETTER)}: {better!r}")
    return OUTCOMES_DESCRIBED if better == "none" else OUTCOMES_JUDGED


def is_reserved_case(case: str) -> bool:
    """Say whether a case id lies under a prefix reserved for the tool's own cases."""
    return case.startswith(RESERVED_CASE_PREFIXES)


def kind_of_unit(unit: str) -> CaseKind:
    """Return the kind of a case told by its unit alone: ``time`` for a unit of time."""
    return "time" if unit in TIME_UNITS else "other"


def combine_control(a: float, b: float, better: str) -> float | None:
    """Combine the values two runs of one control launch report for a case.

    Where lower is better the values add up: 3 and 5 give 8. Where higher is
    better the two rates combine into the rate over both runs,
    ``1 / (1/a + 1/b)``: 3 and 6 give 2. A value of zero or less on either
    run gives zero where higher is better, so the case is graded as holding
    no positive value. A case whose ``better`` is ``none`` is not recorded
    for the control: the answer is ``None``.

    Only a case that the workload or a driver reports is combined. A time
    that the tool or the engine measures is the one interval around both
    runs and never passes through this function.
    """
    if better == "none":
        return None
    if better == "lower":
        return a + b
    if better != "higher":
        raise ValueError(f"better is one of {', '.join(BETTER)}: {better!r}")
    if a <= 0 or b <= 0:
        return 0.0
    return 1.0 / (1.0 / a + 1.0 / b)


def control_expected(better: str) -> float | None:
    """Return the median ratio of the control against the baseline that twice the work reads.

    2.0 where lower is better, 0.5 where higher is better, and ``None`` for a
    case whose ``better`` is ``none``, which the control does not record.
    """
    if better not in BETTER:
        raise ValueError(f"better is one of {', '.join(BETTER)}: {better!r}")
    return CONTROL_EXPECTED.get(better)


def control_within(ratio: float, expected: float, tolerance: float) -> bool:
    """Say whether a measured ratio lies within the tolerance of its expected value.

    The tolerance is a fraction of the expected value, and both ends count as
    inside: with 0.10 and an expected 2.0, every ratio from 1.8 to 2.2 does.
    """
    if tolerance < 0:
        raise ValueError("a tolerance is zero or more")
    return expected * (1.0 - tolerance) <= ratio <= expected * (1.0 + tolerance)


def launch_cost_note(median_s: float, cost_median_s: float, note_share: float = 0.01) -> bool:
    """Say whether a ``wall`` median is short enough to get the launch-cost note.

    It is when the median is less than the median cost of a launch divided by
    ``note_share``: the cost is then more than that share of the value. With
    a cost of 0.0005 s and a share of 0.01, a median of 0.04 s gets the note
    and one of 0.06 s does not.
    """
    if not 0.0 < note_share <= 1.0:
        raise ValueError("note_share lies above 0 and at most at 1")
    return median_s < cost_median_s / note_share


def _env_pad_draw(seed: int, round: int, again: bool = False) -> int:
    """Return one draw of the seeded generator of pad lengths: a hash of the seed and the round."""
    text = f"pairbench/env_pad/{seed}/{round}" + ("/again" if again else "")
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def env_pad_length(seed: int, round: int) -> int:
    """Return the length of the environment pad of one round, in bytes.

    It lies from 0 to ``ENV_PAD_MAX`` and follows from the seed and the round
    alone, through a hash, so that every Python version and every caller
    gives the same length. ``round`` is 1-based. A warm-up launch and an
    explain launch get a length of 0 and do not ask this function.

    The length changes from every round to the next. The length of a round
    is its own draw; where that equals the length of the round before, the
    round takes a second draw that moves it to another length.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"a seed is a whole number: {seed!r}")
    if isinstance(round, bool) or not isinstance(round, int):
        raise ValueError(f"a round is a whole number: {round!r}")
    if round < 1:
        raise ValueError("rounds are numbered from 1")
    lengths = ENV_PAD_MAX + 1
    length = -1
    for r in range(1, round + 1):
        drawn = _env_pad_draw(seed, r) % lengths
        if drawn == length:
            drawn = (drawn + 1 + _env_pad_draw(seed, r, again=True) % ENV_PAD_MAX) % lengths
        length = drawn
    return length


def planned_launches(*, entries: int, rounds: int, sides: int, warmups: int, control: bool) -> int:
    """Return the number of launches a plan counts.

    ``entries`` is the length of the lineup and ``sides`` the number of sides
    that get warm-up launches. Every round launches every entry once, and the
    positive control once more when there is one. The empty launches that
    measure the cost of a launch and the explain launches are not counted.
    """
    if min(entries, rounds, sides, warmups) < 0:
        raise ValueError("a count is zero or more")
    return rounds * (entries + (1 if control else 0)) + sides * warmups


def planned_explain_launches(sides: int, mode: str) -> int:
    """Return the number of explain launches a plan counts.

    ``sides`` is the number of subjects plus the baseline; twins and the
    positive control are not launched again. Each side is launched once for
    the counters and once for the stacks. Mode ``off`` plans none. Mode
    ``auto`` plans them all, because whether they run is known only after
    the analysis.
    """
    if mode not in EXPLAIN_MODES:
        raise ValueError(f"the explain mode is one of {', '.join(EXPLAIN_MODES)}: {mode!r}")
    if sides < 0:
        raise ValueError("a count is zero or more")
    return 0 if mode == "off" else EXPLAIN_LAUNCHES_PER_SIDE * sides


_UNSAFE_IN_FILE_NAME = re.compile(r"[^A-Za-z0-9._-]")
# The longest a name is written in a file name, so that the longest file name
# built from two names (a difference graph) stays well inside the 255 bytes a
# file system allows for one part of a path.
FILE_NAME_LIMIT = 100
_FILE_NAME_HASH = 16


def safe_file_name(name: str) -> str:
    """Return a case or side name as it is written in a file name.

    Every character outside the letters ``A`` to ``Z`` and ``a`` to ``z``,
    the digits, ``.``, ``_`` and ``-`` is replaced by ``_``:
    ``c32/ttft_ms_median`` gives ``c32_ttft_ms_median``. A written name
    longer than ``FILE_NAME_LIMIT`` keeps its first characters and ends in
    ``-`` and the first 16 hexadecimal digits of the SHA-256 of the real
    name, ``FILE_NAME_LIMIT`` characters in all, so two long names stay
    apart. Whoever writes the file records the mapping from the real name to
    the file name.
    """
    written = _UNSAFE_IN_FILE_NAME.sub("_", name)
    if len(written) <= FILE_NAME_LIMIT:
        return written
    digest = hashlib.sha256(name.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{written[: FILE_NAME_LIMIT - _FILE_NAME_HASH - 1]}-{digest[:_FILE_NAME_HASH]}"


def file_names(names: Iterable[str]) -> dict[str, str]:
    """Return, for each case or side name, the name it has in a file name, each one different.

    A name is written by ``safe_file_name``. Two names that differ only in
    characters a file name cannot hold would be written alike and one file
    would replace the other: ``c32/ttft`` and ``c32_ttft`` both give
    ``c32_ttft``. A name that is written as it stands keeps its own form.
    Every other name takes its written form when no name before it has
    taken it, and else that form followed by ``-2``, ``-3`` and so on, cut
    first where it would grow past ``FILE_NAME_LIMIT``.

    The answer is the mapping a diagnostics document records as its
    ``name_map``. Each of its values is safe as it stands, so it can be
    handed to ``folded_file``, ``flame_file``, ``chart_file`` and the other
    functions that build a file name.
    """
    wanted = list(dict.fromkeys(names))
    out = {name: name for name in wanted if name and safe_file_name(name) == name}
    taken = set(out.values())
    for name in wanted:
        if name in out:
            continue
        written = safe_file_name(name)
        chosen, count = written, 1
        while chosen in taken or not chosen:
            count += 1
            tail = f"-{count}"
            chosen = f"{written[: FILE_NAME_LIMIT - len(tail)]}{tail}"
        out[name] = chosen
        taken.add(chosen)
    return {name: out[name] for name in wanted}


def folded_file(side: str) -> str:
    """Return the folded-stack file of a side, relative to the run folder."""
    return f"{DIR_PROFILES}/{safe_file_name(side)}.folded"


def folded_diff_file(subject: str, baseline: str) -> str:
    """Return the difference file of a subject against the baseline, relative to the run folder."""
    pair = f"{safe_file_name(subject)}_vs_{safe_file_name(baseline)}"
    return f"{DIR_PROFILES}/{pair}.folded-diff.tsv"


def flame_file(side: str) -> str:
    """Return the flame graph of a side, relative to the run folder."""
    return f"{DIR_PROFILES}/{safe_file_name(side)}.flame.svg"


def flame_diff_file(subject: str, baseline: str) -> str:
    """Return the difference graph of a subject against the baseline, relative to the run folder."""
    pair = f"{safe_file_name(subject)}_vs_{safe_file_name(baseline)}"
    return f"{DIR_PROFILES}/{pair}.flame-diff.svg"


def chart_file(chart: str, case: str | None = None) -> str:
    """Return the file of a chart, relative to the run folder.

    ``chart`` is one of ``CHARTS``. The round-by-round chart exists per
    primary case and takes the case: ``charts/rounds.<case>.svg``.
    """
    if chart not in CHARTS:
        raise ValueError(f"a chart is one of {', '.join(CHARTS)}: {chart!r}")
    if (chart == "rounds") != (case is not None):
        raise ValueError("the round-by-round chart, and only it, is drawn per case")
    middle = "" if case is None else f".{safe_file_name(case)}"
    return f"{DIR_CHARTS}/{chart}{middle}.svg"


def forbidden_words(text: str) -> tuple[str, ...]:
    """Name the words of ``FINDING_FORBIDDEN_WORDS`` a text uses.

    A word counts where it stands as a whole word or phrase, in upper or
    lower case. A finding, and every template a finding is made from, uses
    none of them.
    """
    found: list[str] = []
    for words in FINDING_FORBIDDEN_WORDS:
        pattern = r"\b" + r"\s+".join(re.escape(word) for word in words.split()) + r"\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(words)
    return tuple(found)


_ATTRIBUTE_REFERENCE = re.compile(
    r"""(?<![\w-])(?:[\w-]+:)?(?:href|src|srcset|poster)\s*=\s*"""
    r"""(?:"([^"]*)"|'([^']*)'|([^\s"'<>=`]+))""",
    re.IGNORECASE,
)
_URL_REFERENCE = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)""", re.IGNORECASE)
_IMPORT_REFERENCE = re.compile(r"@import\b[^;{}<]*", re.IGNORECASE)


def _stays_inside(target: str) -> bool:
    """Say whether the target of a reference lies in the file that holds the reference."""
    address = target.strip().lower()
    return not address or address.startswith(("#", "data:"))


def points_outside(text: str) -> tuple[str, ...]:
    """Name what in an SVG or HTML text makes a viewer fetch something from outside the file.

    A chart, a flame graph and the report page are self-contained: nothing
    in them points outside the file. What counts is a ``src``, an ``href``,
    a ``srcset`` or a ``poster`` (with or without a prefix such as
    ``xlink:``, as an attribute or assigned in a script, with its value in
    quotes or without, so the ``href`` of a ``<link>`` counts) and a
    ``url(...)`` whose target is neither a fragment of the same file
    (``#...``) nor a ``data:`` address, and every ``@import``. The name of an
    XML namespace is no address to fetch and does not count. The answer
    lists each such reference as it is written, in the order of the text;
    an empty answer says the text points nowhere outside itself.
    """
    found: list[tuple[int, str]] = []
    for pattern in (_ATTRIBUTE_REFERENCE, _URL_REFERENCE):
        for match in pattern.finditer(text):
            target = next((group for group in match.groups() if group is not None), "")
            if not _stays_inside(target):
                found.append((match.start(), match.group(0)))
    for match in _IMPORT_REFERENCE.finditer(text):
        found.append((match.start(), match.group(0).strip()))
    return tuple(reference for _start, reference in sorted(found))


_PYTHON_WORD = re.compile(r"python(\d+(\.\d+)*)?")


def starts_with_python(command: Sequence[str] | None) -> bool:
    """Say whether a command starts with a Python interpreter.

    It does when the last part of the path of its first word is ``python``,
    or ``python`` followed by a version such as ``python3`` or
    ``python3.12``. A side whose command does not is never given the sampler
    of the ``pystacks`` instrument.
    """
    if not command:
        return False
    return _PYTHON_WORD.fullmatch(command[0].rpartition("/")[2]) is not None


def figure_key(case: str, subject: str, baseline: str, name: str) -> str:
    """Return the key of one figure of a comparison: ``<case>.<subject>_vs_<baseline>.<name>``."""
    if name not in FIGURE_NAMES:
        raise ValueError(f"not a figure name: {name}")
    return f"{case}.{subject}_vs_{baseline}.{name}"


def median_key(case: str, side: str) -> str:
    """Return the key of a side's median on a case: ``<case>.<side>.median``."""
    return f"{case}.{side}.median"


def level_label(level: int, kind: str = "concurrency") -> str:
    """Return the label of a serving load level.

    ``c<level>`` when a level counts concurrent requests, ``r<level>`` when it
    counts requests per second: ``c32``, ``r32``.
    """
    if kind not in LEVEL_PREFIXES:
        raise ValueError(f"a load level counts one of {', '.join(LEVEL_PREFIXES)}: {kind!r}")
    return f"{LEVEL_PREFIXES[kind]}{level}"


def case_id(label: str, metric: str) -> str:
    """Join a load-level label and a metric into a case id; an empty label gives the metric."""
    return f"{label}/{metric}" if label else metric


def case_matches(case: str, patterns: Iterable[str]) -> bool:
    """Say whether a case id matches one of the patterns.

    A pattern matches an id that is equal to it, or that it matches as a
    shell-style glob with ``*``, ``?`` and ``[...]``, with upper and lower case
    kept apart. The equal test comes first because a case id may itself hold
    brackets, as ``energy_j[gpu]`` does. An id that holds the mark a run adds
    to a name whose cut dropped words (``case_suffix``) is matched with the
    mark and without it, so ``copy x`` matches ``copy x +1a2b3c4d``.
    """
    forms = (case, case_unsuffixed(case)) if case_has_suffix(case) else (case,)
    return any(
        one == pattern or fnmatch.fnmatchcase(one, pattern) for one in forms for pattern in patterns
    )


# A file of a run folder is named relative to that folder. This matches a name
# that is not: one that starts at the root or at the home folder, or that has a
# part ``..``.
OUTSIDE_RUN_FOLDER: Final = r"^[/~]|(^|/)\.\.(/|$)"

# What ``validate_side_name`` takes, as a pattern a JSON Schema states.
SIDE_NAME_PATTERN: Final = r"^(?!\.\.?$)[^~=\s]+$"

# A SHA-256 as lower-case hex, as a side records the hash of its working folder.
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"


def validate_side_name(name: str) -> str:
    """Return a user side name, or refuse it.

    ``~`` is reserved for the names of twins (``~same``) and of the positive
    control (``~twice``). Empty names, white space and ``=`` cannot be
    written on the command line or in the text input format. A side's name
    also names its folders in a run folder, so ``.`` and ``..`` are refused,
    and every file it names is UTF-8 text, so a name that cannot be written
    as UTF-8 is refused too.
    """
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise Refusal("E_USAGE", f"side name {name!r} is refused: it is not UTF-8 text") from None
    if not name or "~" in name or "=" in name or any(ch.isspace() for ch in name):
        raise Refusal(
            "E_USAGE",
            f"side name {name!r} is refused: it must be non-empty and hold no '~', '=' or space",
        )
    if name in (".", ".."):
        raise Refusal(
            "E_USAGE", f"side name {name!r} is refused: '.' and '..' name folders, not sides"
        )
    return name


def fingerprint_of(identity: Mapping[str, Any], launch: Mapping[str, Any]) -> str:
    """Return a side's fingerprint: the hash of its identity and effective launch settings.

    It is the SHA-256 of the canonical JSON of ``fingerprint_inputs``. The
    side's name is not part of it. The launch settings are hashed with every
    secret form the shown command hides replaced by ``HIDDEN``, as
    ``hashed_argv`` reads the entrypoint and the arguments and with the value
    of each credential-like variable hidden (``_hashed_launch``), and the
    output of the ``identify`` command as ``hashed_output`` reads it, so two
    sides that differ only in such a secret have one fingerprint. The rest of
    the identity, the names of passed variables, the mounts and the limits
    are hashed as they are.
    """
    return sha256_hex(canonical_json(fingerprint_inputs(identity, launch)))


def fingerprint_inputs(identity: Mapping[str, Any], launch: Mapping[str, Any]) -> dict[str, Any]:
    """Return what a side's fingerprint is the hash of, with the recognised secrets hidden.

    The value is ``{"identity": ..., "launch": ...}``. The identity is kept
    as it is, except four keys: its ``identify_output``, read as
    ``hashed_output`` reads it, its ``executable``, the path of a command
    side's program, cut to its last part as ``public_path`` cuts a path and
    as the look-up line of a plan shows it, and the image's entrypoint and
    command an image side records (``IMAGE_ENTRYPOINT_KEY``), which are left
    out. So the fingerprint names no folder of the machine: one program in
    two folders, with the same bytes and the same typed arguments, is one
    side. The launch
    settings are read as ``_hashed_launch`` says: the entrypoint and the
    arguments as one argument list, and the value of each credential-like
    variable hidden. Hiding the result a second time changes nothing.
    """
    shown = _encode(identity)
    output = shown.get(IDENTIFY_OUTPUT_KEY) if isinstance(shown, dict) else None
    if isinstance(output, str):
        shown[IDENTIFY_OUTPUT_KEY] = hashed_output(output)
    executable = shown.get(EXECUTABLE_KEY) if isinstance(shown, dict) else None
    if isinstance(executable, str):
        shown[EXECUTABLE_KEY] = public_path(executable)
    if isinstance(shown, dict):
        shown.pop(IMAGE_ENTRYPOINT_KEY, None)
        shown.pop(IMAGE_COMMAND_PROGRAM_KEY, None)
    return {"identity": shown, "launch": _hashed_launch(_encode(launch))}


def config_sha256(config: Mapping[str, Any], sides: Sequence[Side] = ()) -> str:
    """Return the hash of a resolved config as it is written in a capture header.

    It is the SHA-256 of the canonical JSON of ``config_inputs``: the config
    with the secrets the fingerprint hides replaced by ``HIDDEN`` in its
    commands, arguments and environments; paths and every other value are
    hashed as they are. ``sides`` are the sides a capture records, whose
    image entrypoints say what runs the shared workload (``_image_heads``).
    """
    return sha256_hex(canonical_json(config_inputs(config, sides)))


def config_inputs(config: Mapping[str, Any], sides: Sequence[Side] = ()) -> Any:
    """Return what ``config_sha256`` is the hash of: the config with its secrets hidden.

    The commands, arguments, environments, serving checks and identify
    commands of the config are read as ``_hashed_config`` says, the shared
    workload also after what each of ``sides`` recorded its image runs
    before it; every other key is kept as it is. Hiding the result again
    changes nothing.
    """
    return _hashed_config(_encode(config), sides)


def combine_hashes(hashes: Sequence[str | None]) -> str | None:
    """Fold the hashes of several captures into one.

    One hash is returned unchanged. No hash at all gives ``None``. Several are
    hashed together in the order given, an absent one counting as empty text.
    """
    present = [h for h in hashes if h is not None]
    if not present:
        return None
    if len(hashes) == 1:
        return present[0]
    return sha256_hex("\n".join(h or "" for h in hashes))


# ---------------------------------------------------------------------------
# Conversion between dataclasses and JSON, driven by the field types
# ---------------------------------------------------------------------------


_FIELD_TYPES: dict[type, tuple[tuple[str, Any], ...]] = {}


def _field_types(cls: type) -> tuple[tuple[str, Any], ...]:
    cached = _FIELD_TYPES.get(cls)
    if cached is None:
        hints = get_type_hints(cls)
        cached = tuple((f.name, hints[f.name]) for f in dataclasses.fields(cls))
        _FIELD_TYPES[cls] = cached
    return cached


def _freeze(value: Any, where: str = "a free value") -> Any:
    """Copy a free-form JSON value into plain dicts and tuples.

    A number that is not finite is refused here as it is in a typed field.
    """
    if isinstance(value, _Coerced):
        return _freeze(_encode(value), where)
    if isinstance(value, Mapping):
        return {str(k): _freeze(v, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list | tuple):
        return tuple(_freeze(v, f"{where}[{i}]") for i, v in enumerate(value))
    if isinstance(value, float) and not math.isfinite(value):
        raise _wrong(where, "a finite number", value)
    return value


def _encode(value: Any, *, top: bool = False) -> Any:
    """Turn a model value into plain JSON data."""
    if isinstance(value, _Coerced):
        out: dict[str, Any] = {}
        record = type(value).RECORD
        if top and record is not None:
            out["t"] = record
        for f in dataclasses.fields(value):  # type: ignore[arg-type]
            out[f.name] = _encode(getattr(value, f.name))
        return out
    if isinstance(value, Mapping):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    return value


def _wrong(where: str, expected: str, value: Any) -> ValueError:
    return ValueError(f"{where}: expected {expected}, got {value!r}")


def _convert(tp: Any, value: Any, where: str) -> Any:
    """Check a value against a field type and build nested model objects."""
    if tp is Any:
        return _freeze(value, where)
    origin = get_origin(tp)
    if origin is None:
        if isinstance(tp, type) and issubclass(tp, _Coerced):
            if isinstance(value, tp):
                return value
            if isinstance(value, Mapping):
                return _build(tp, value)
            raise _wrong(where, "an object", value)
        if tp is float:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise _wrong(where, "a number", value)
            if not math.isfinite(value):
                raise _wrong(where, "a finite number", value)
            return value
        if tp is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise _wrong(where, "a whole number", value)
            return value
        if tp is str:
            if not isinstance(value, str):
                raise _wrong(where, "text", value)
            return value
        if tp is bool:
            if not isinstance(value, bool):
                raise _wrong(where, "true or false", value)
            return value
        if tp is type(None):
            if value is not None:
                raise _wrong(where, "nothing", value)
            return None
        return value
    if origin is Literal:
        allowed = get_args(tp)
        if isinstance(value, bool) or value not in allowed:
            raise _wrong(where, "one of " + ", ".join(repr(a) for a in allowed), value)
        return value
    if origin is Union or origin is types.UnionType:
        options = get_args(tp)
        if value is None:
            if type(None) in options:
                return None
            raise _wrong(where, "a value", value)
        errors: list[ValueError] = []
        for option in options:
            if option is type(None):
                continue
            try:
                return _convert(option, value, where)
            except ValueError as exc:
                errors.append(exc)
        if not errors:
            raise _wrong(where, "a value", value)
        # The alternative that got furthest into the value says best what is wrong.
        raise max(errors, key=lambda exc: len(str(exc).partition(": expected")[0]))
    if origin is tuple:
        if isinstance(value, str) or not isinstance(value, list | tuple):
            raise _wrong(where, "a list", value)
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v, f"{where}[{i}]") for i, v in enumerate(value))
        if len(args) != len(value):
            raise _wrong(where, f"a list of {len(args)}", value)
        return tuple(
            _convert(a, v, f"{where}[{i}]")
            for i, (a, v) in enumerate(zip(args, value, strict=True))
        )
    if isinstance(origin, type) and issubclass(origin, Mapping):
        if not isinstance(value, Mapping):
            raise _wrong(where, "an object", value)
        value_type = get_args(tp)[1]
        return {str(k): _convert(value_type, v, f"{where}.{k}") for k, v in value.items()}
    return value


LIMIT_WORDS: Final[tuple[str, ...]] = (
    "minimum",
    "exclusiveMinimum",
    "maximum",
    "exclusiveMaximum",
    "minLength",
    "pattern",
)


def _keep_limits(where: str, value: Any, limits: Mapping[str, Any]) -> None:
    """Refuse a value that breaks a limit of its field. ``None`` keeps every limit."""
    unknown = sorted(set(limits) - set(LIMIT_WORDS))
    if unknown:
        raise TypeError(f"{where}: not a limit: {', '.join(unknown)}")
    if value is None:
        return
    if "minimum" in limits and value < limits["minimum"]:
        raise _wrong(where, f"at least {limits['minimum']}", value)
    if "exclusiveMinimum" in limits and value <= limits["exclusiveMinimum"]:
        raise _wrong(where, f"more than {limits['exclusiveMinimum']}", value)
    if "maximum" in limits and value > limits["maximum"]:
        raise _wrong(where, f"at most {limits['maximum']}", value)
    if "exclusiveMaximum" in limits and value >= limits["exclusiveMaximum"]:
        raise _wrong(where, f"less than {limits['exclusiveMaximum']}", value)
    if "minLength" in limits and len(value) < limits["minLength"]:
        raise _wrong(where, f"a text of at least {limits['minLength']} characters", value)
    if "pattern" in limits and re.search(limits["pattern"], value) is None:
        raise _wrong(where, f"a text that matches {limits['pattern']}", value)


class _Coerced:
    """Base of every model class: checks field types and freezes containers on creation.

    ``RECORD`` is the record type of a capture record. ``OPTIONAL`` names the
    keys that may be absent when the JSON form is read: a class that is part
    of a capture record or of the results document states them exactly, and
    every other key is required. ``None`` means every field that has a default
    may be absent; it is the setting of the classes that are no part of those
    documents.

    ``LIMITS`` states, per field, what a value must keep beyond its type:
    ``minimum``, ``exclusiveMinimum``, ``maximum`` and ``exclusiveMaximum``
    for a number, ``minLength`` and ``pattern`` for a text. A value of
    ``None`` keeps every limit. The JSON Schemas state the same limits with
    the same words.
    """

    RECORD: ClassVar[str | None] = None
    OPTIONAL: ClassVar[frozenset[str] | None] = None
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {}

    def __post_init__(self) -> None:
        cls = type(self)
        for name, tp in _field_types(cls):
            value = getattr(self, name)
            new = _convert(tp, value, f"{cls.__name__}.{name}")
            if new is not value:
                object.__setattr__(self, name, new)
        for name, limits in cls.LIMITS.items():
            _keep_limits(f"{cls.__name__}.{name}", getattr(self, name), limits)


class _Model(_Coerced):
    """A model class whose JSON form is one object with a key per field."""

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form: a plain dict with one key per field.

        A capture record also carries its record type under ``"t"``.
        """
        encoded: dict[str, Any] = _encode(self, top=True)
        return encoded

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        """Build from the JSON form. Unknown keys are ignored; a bad value is refused."""
        if not isinstance(data, Mapping):
            raise Refusal(
                "E_USAGE", f"{cls.__name__}: expected an object, got {type(data).__name__}"
            )
        try:
            return _build(cls, data)
        except (ValueError, TypeError) as exc:
            raise Refusal("E_USAGE", f"not a valid {cls.__name__}: {exc}") from exc


_M = TypeVar("_M", bound=_Coerced)


def _build(cls: type[_M], data: Mapping[str, Any]) -> _M:
    """Build a model object from JSON data, ignoring keys it does not know.

    A key is required unless the class lets it be absent: see ``OPTIONAL``.
    """
    required = required_keys(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if f.name in data:
            kwargs[f.name] = data[f.name]
        elif f.name in required:
            raise ValueError(f"{cls.__name__}: missing key {f.name!r}")
    return cls(**kwargs)


_REQUIRED_KEYS: dict[type, tuple[str, ...]] = {}


def required_keys(cls: type) -> tuple[str, ...]:
    """Return the keys the JSON form of a model class must hold, in field order.

    The record type key ``"t"`` of a capture record is not among them.
    """
    cached = _REQUIRED_KEYS.get(cls)
    if cached is not None:
        return cached
    optional: frozenset[str] | None = getattr(cls, "OPTIONAL", None)
    out: list[str] = []
    for f in dataclasses.fields(cls):
        has_default = (
            f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        )
        if optional is None:
            if not has_default:
                out.append(f.name)
        elif f.name not in optional:
            out.append(f.name)
        elif not has_default:
            raise TypeError(f"{cls.__name__}.{f.name} may be absent but has no default")
    unknown = sorted((optional or frozenset()) - {f.name for f in dataclasses.fields(cls)})
    if unknown:
        raise TypeError(f"{cls.__name__}.OPTIONAL names no field: {', '.join(unknown)}")
    _REQUIRED_KEYS[cls] = tuple(out)
    return _REQUIRED_KEYS[cls]


# ---------------------------------------------------------------------------
# Sides
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ready(_Model):
    """The readiness check of a serving side: an HTTP path polled until it answers."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"timeout_s": {"minimum": 0}}

    http: str = "/health"
    timeout_s: float = 900.0


DEFAULT_READY: Final = Ready()


@dataclass(frozen=True)
class Probe(_Model):
    """The first-answer request sent to a serving side once it is ready.

    ``body`` of ``None`` asks for the default: one small streaming chat request.
    """

    path: str = "/v1/chat/completions"
    body: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ServeSpec(_Model):
    """What to serve, apart from how it is started.

    ``model`` is where the model is; ``model_name`` is the name requests use,
    and ``None`` asks the server's own model list. ``launcher`` of ``None``
    follows the container-engine choice. The host launcher takes ``command``
    in place of ``image``. ``phases`` maps a start-up phase name to a regular
    expression matched against the server's log.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "image": {"minLength": 1},
        "port": {"minimum": 1, "maximum": 65535},
    }

    image: str | None = None
    args: tuple[str, ...] = ()
    port: int = 8000
    ready: Ready = DEFAULT_READY
    env: Mapping[str, str] = field(default_factory=dict)
    model: str | None = None
    model_name: str | None = None
    launcher: str | None = None
    command: tuple[str, ...] = ()
    probe: Probe = field(default_factory=Probe)
    phases: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        """Build from the JSON form; an unknown key, here or in ``ready`` or ``probe``, is refused.

        A serving spec is what the user declared, so a misspelt key is an
        error rather than a setting silently left at its default.
        """
        if isinstance(data, Mapping):
            _refuse_unknown_keys(cls, data, "serve")
            for key, part in (("ready", Ready), ("probe", Probe)):
                inner = data.get(key)
                if isinstance(inner, Mapping):
                    _refuse_unknown_keys(part, inner, f"serve.{key}")
        return super().from_json(data)


def _refuse_unknown_keys(cls: type, data: Mapping[str, Any], where: str) -> None:
    known = {name for name, _ in _field_types(cls)}
    unknown = sorted(str(key) for key in data if key not in known)
    if unknown:
        keys = "key" if len(unknown) == 1 else "keys"
        raise Refusal("E_USAGE", f"{where}: unknown {keys} {', '.join(repr(k) for k in unknown)}")


@dataclass(frozen=True)
class Side(_Model):
    """One thing being compared, or the twin of one.

    ``spec`` holds what the user declared, shaped by kind:

    * ``cmd``: ``{"argv": [...]}``; an argument ``{workload}`` is replaced by
      the shared workload;
    * ``image``: ``{"image", "args", "env", "entrypoint"}``;
    * ``python``, ``venv``, ``conda``: ``{"interpreter"}``, ``{"venv"}``,
      ``{"conda"}``;
    * ``serve``: the JSON form of ``ServeSpec``;
    * ``file``: ``{"paths": [...], "format"}``, where a path may be a glob and
      ``format`` names the driver that reads the files;
    * any other kind, one a plug-in adds: ``{"spec": text}``, or the table of
      plain values its config gave as ``spec``.

    ``identity`` and ``fingerprint`` are empty until the side is resolved. A
    twin relation is the ``twin_of`` field and nothing else. The positive
    control is the entry whose ``control_of`` field names the baseline; that
    relation is never told from a name either.

    ``workdir_sha256`` is the SHA-256 of the working folder the side ran in:
    of its resolved path for a side that runs on the host, of the folder as
    typed for one that runs in a container. It is ``None`` for a side that
    runs nothing and in a capture that holds no such record. Pooling
    compares it; it stays in the capture, and no results document, and no
    hash a results document shows, holds it.
    """

    RECORD: ClassVar[str | None] = "side"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"control_of", "workdir_sha256"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "twin_of": {"minLength": 1},
        "control_of": {"minLength": 1},
        "workdir_sha256": {"pattern": SHA256_PATTERN},
    }

    name: str
    kind: str
    role: Role = "subject"
    twin_of: str | None = None
    control_of: str | None = field(default=None, kw_only=True)
    spec: Mapping[str, Any] = field(default_factory=dict)
    identity: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    workdir_sha256: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        if (self.role == "twin") != (self.twin_of is not None):
            raise Refusal("E_USAGE", f"side {self.name!r}: a twin, and only a twin, names twin_of")
        if (self.role == "control") != (self.control_of is not None):
            raise Refusal(
                "E_USAGE", f"side {self.name!r}: a control, and only a control, names control_of"
            )
        if self.role in ("twin", "control"):
            if not self.name:
                raise Refusal("E_USAGE", f"a {self.role} needs a name")
        else:
            validate_side_name(self.name)
        if not self.kind:
            raise Refusal("E_USAGE", f"side {self.name!r} has no kind")

    @classmethod
    def parse(cls, text: str) -> Side:
        """Read ``NAME=KIND:SPEC`` as written after ``--side``."""
        name, eq, rest = text.partition("=")
        kind, colon, spec = rest.partition(":")
        if not eq or not colon or not kind or not spec:
            raise Refusal("E_USAGE", f"a side is written NAME=KIND:SPEC, got {text!r}")
        return cls(name=name, kind=kind, spec=_spec_from_text(kind, spec))

    @classmethod
    def image(
        cls,
        name: str,
        ref: str,
        *,
        args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
        entrypoint: str | None = None,
    ) -> Side:
        """A container image. Its own ``args`` replace the shared workload for this side."""
        if not isinstance(ref, str) or not ref:
            raise Refusal("E_USAGE", f"side {name!r}: an image side needs an image reference")
        spec = {"image": ref, "args": tuple(args), "env": dict(env or {}), "entrypoint": entrypoint}
        return cls(name=name, kind=KIND_IMAGE, spec=spec)

    @classmethod
    def command(cls, name: str, argv: Sequence[str]) -> Side:
        """A command. An argument ``{workload}`` is replaced by the shared workload."""
        if isinstance(argv, str) or not argv:
            raise Refusal("E_USAGE", f"side {name!r}: a command is a non-empty list of arguments")
        return cls(name=name, kind=KIND_CMD, spec={"argv": tuple(argv)})

    @classmethod
    def python(
        cls,
        name: str,
        *,
        interpreter: str | None = None,
        venv: str | None = None,
        conda: str | None = None,
    ) -> Side:
        """A Python environment: one of an interpreter, a virtual environment or a conda name."""
        given = {
            k: v for k, v in (("interpreter", interpreter), ("venv", venv), ("conda", conda)) if v
        }
        if len(given) != 1:
            raise Refusal(
                "E_USAGE", f"side {name!r}: give exactly one of interpreter, venv and conda"
            )
        key = next(iter(given))
        kind = {"interpreter": KIND_PYTHON, "venv": KIND_VENV, "conda": KIND_CONDA}[key]
        return cls(name=name, kind=kind, spec=given)

    @classmethod
    def serve(
        cls, name: str, image: str, args: Sequence[str], *, ready: Ready = DEFAULT_READY
    ) -> Side:
        """A server image with its arguments and readiness check."""
        if not isinstance(image, str) or not image:
            raise Refusal("E_USAGE", f"side {name!r}: a serving side needs an image reference")
        spec = ServeSpec(image=image, args=tuple(args), ready=ready)
        return cls(name=name, kind=KIND_SERVE, spec=spec.to_json())

    @classmethod
    def files(cls, name: str, paths: Sequence[str], *, format: str | None) -> Side:
        """Result files from another tool, one per round, read by the driver named ``format``."""
        if isinstance(paths, str) or not paths:
            raise Refusal("E_USAGE", f"side {name!r}: files are a non-empty list of paths")
        spec = {"paths": tuple(str(p) for p in paths), "format": format}
        return cls(name=name, kind=KIND_FILE, spec=spec)

    def to_json(self, *, redact: bool = True) -> dict[str, Any]:
        """Return the ``side`` record of a capture.

        The spec is kept as declared, except that the value of every
        credential-like environment variable in it is replaced, as it is in
        the recorded config. Without ``redact`` the values are kept; nothing
        that is written to a file may use that.
        """
        out = super().to_json()
        env = out["spec"].get("env")
        if redact and isinstance(env, dict):
            out["spec"]["env"] = {
                k: (REDACTED if looks_like_credential(k) else v) for k, v in env.items()
            }
        return out

    def twin(self) -> Side:
        """Return this side's twin: an identical copy named with the reserved suffix."""
        if self.role == "twin":
            raise Refusal("E_USAGE", f"side {self.name!r} is a twin and cannot have one")
        if self.role == "control":
            raise Refusal(
                "E_USAGE", f"side {self.name!r} is the positive control and cannot have a twin"
            )
        return dataclasses.replace(
            self, name=self.name + TWIN_SUFFIX, role="twin", twin_of=self.name
        )

    def control(self) -> Side:
        """Return the positive-control entry of this side, which must be the baseline.

        It is a copy of the baseline named with the reserved suffix
        ``~twice``, with the role ``control`` and ``control_of`` naming the
        baseline. One launch of it starts the baseline once and runs the
        workload twice.
        """
        if self.role != "baseline":
            raise Refusal(
                "E_USAGE", f"side {self.name!r} is not the baseline and has no positive control"
            )
        return dataclasses.replace(
            self, name=self.name + CONTROL_SUFFIX, role="control", control_of=self.name
        )

    @property
    def source(self) -> str:
        """The side this entry launches: its own name, or the side a twin or a control copies."""
        return self.twin_of or self.control_of or self.name

    def with_identity(self, identity: Mapping[str, Any], fingerprint: str) -> Side:
        """Return a copy that carries a resolved identity and fingerprint."""
        return dataclasses.replace(self, identity=identity, fingerprint=fingerprint)

    def with_role(self, role: Role) -> Side:
        """Return a copy with another role (``subject`` or ``baseline``)."""
        return dataclasses.replace(self, role=role)

    def public_identity(self) -> dict[str, Any]:
        """Return the part of the identity a results document may show.

        Only the keys of ``PUBLIC_IDENTITY_KEYS`` are kept. A digest written
        with its repository in front, as ``repository@sha256:...``, is cut to
        the hash. A value that is not a hash where one belongs is left out.
        """
        shown: dict[str, Any] = {}
        for key in PUBLIC_IDENTITY_KEYS:
            if key not in self.identity:
                continue
            value = _encode(self.identity[key])
            if key in PUBLIC_IDENTITY_TEXT_KEYS:
                if isinstance(value, str):
                    shown[key] = value
            elif key in PUBLIC_IDENTITY_LIST_KEYS:
                if isinstance(value, list):
                    hashes = [_hash_only(item) for item in value]
                    shown[key] = [item for item in hashes if item is not None]
            else:
                found = _hash_only(value)
                if found is not None:
                    shown[key] = found
        return shown

    def serve_spec(self) -> ServeSpec:
        """Return the ``ServeSpec`` of a serving side."""
        if self.kind != KIND_SERVE:
            raise Refusal("E_USAGE", f"side {self.name!r} is not a serving side")
        return ServeSpec.from_json(self.spec)

    def for_results(
        self, *, include_image_ref: bool = False, driver: DriverInfo | None = None
    ) -> ResultsSide:
        """Return what a results document shows of this side.

        The image reference is added only when the report settings ask for it.
        A kind that a plug-in provides is shown as ``plugin``. ``driver`` is
        the driver that read the side, from ``Capture.side_driver_info``, or
        from ``pooled_driver_info`` for pooled captures.
        """
        ref = self.spec.get("image") if include_image_ref else None
        shown = self.kind in BUILTIN_KINDS or self.kind == KIND_ROWS
        return ResultsSide(
            name=self.name,
            kind=cast("ShownKind", self.kind if shown else PLUGIN_NAME),
            role=self.role,
            twin_of=self.twin_of,
            control_of=self.control_of,
            identity=self.public_identity(),
            fingerprint=self.fingerprint,
            image_ref=ref if isinstance(ref, str) else None,
            driver=driver,
        )


def launch_cost_side(sides: Sequence[Side]) -> Side | None:
    """Return the side through whose launch path the cost of a launch is measured.

    It is the first side, in the order given, that is a command side or a
    Python environment side. ``None`` when there is none: an image side is
    timed by the engine, so the tool is outside its time and no cost is
    measured for a lineup of image sides only.
    """
    return next(
        (s for s in sides if s.kind in LAUNCH_COST_KINDS and s.role in ("subject", "baseline")),
        None,
    )


def _not_a_hash(value: Any) -> bool:
    """Say whether a value is anything but a hash written without a repository in front."""
    return not isinstance(value, str) or _hash_only(value) != value


def _hash_only(value: Any) -> str | None:
    """Return the hash in a value, without a repository in front of it, or ``None``."""
    if not isinstance(value, str):
        return None
    found = value.rpartition("@")[2]
    return found if re.search(HASH_PATTERN, found) else None


def _spec_from_text(kind: str, text: str) -> Mapping[str, Any]:
    if kind == KIND_IMAGE:
        return {"image": text, "args": (), "env": {}, "entrypoint": None}
    if kind == KIND_CMD:
        try:
            argv = tuple(shlex.split(text))
        except ValueError as exc:
            raise Refusal("E_USAGE", f"cannot read the command {text!r}: {exc}") from exc
        if not argv:
            raise Refusal("E_USAGE", "a cmd side needs a command")
        return {"argv": argv}
    if kind == KIND_PYTHON:
        return {"interpreter": text}
    if kind == KIND_VENV:
        return {"venv": text}
    if kind == KIND_CONDA:
        return {"conda": text}
    if kind == KIND_SERVE:
        return ServeSpec(image=text).to_json()
    if kind == KIND_FILE:
        return {"paths": (text,), "format": None}
    return {"spec": text}


@dataclass(frozen=True)
class Case(_Model):
    """One named measurement a launch produces.

    ``primary`` and ``group`` are decided once, when the case is recorded, by
    ``CaseSettings.is_primary`` and ``CaseSettings.group_of``. An analysis
    reads them from the recorded case and never from the config. A case
    without a group belongs to the group of all cases that share its metric
    and its role, primary or secondary.

    A case whose ``better`` is ``none`` describes and does not judge. Its
    outcomes name a direction, ``higher`` or ``lower``, and it can never be
    primary: making one that is primary is refused.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    id: str
    metric: str
    unit: str
    better: Better = "lower"
    kind: CaseKind = "other"
    primary: bool = True
    group: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.better == "none" and self.primary:
            raise Refusal(
                "E_USAGE",
                f"case {self.id!r} describes and does not judge (its better is none): "
                "it cannot be a primary case",
                scope="case",
            )


def resource_case(case: str) -> Case:
    """Return the record of one resource case of ``RESOURCE_CASES``.

    Its metric is the part of its id after ``res/``, its ``better`` is
    ``none``, it is secondary and it is a floor group of its own: the group
    is named by the case id. The four counts are of kind ``count`` and the
    other figures of kind ``other``, so that no report calls one of them
    faster or slower.
    """
    unit = RESOURCE_CASES.get(case)
    if unit is None:
        raise ValueError(f"not a resource case: {case!r}")
    return Case(
        id=case,
        metric=case.removeprefix(RES_PREFIX),
        unit=unit,
        better="none",
        kind="count" if unit == UNIT_COUNT else "other",
        primary=False,
        group=case,
    )


# ---------------------------------------------------------------------------
# The experiment and its settings groups
# ---------------------------------------------------------------------------

# Digits are the ASCII digits only, as in a JSON Schema pattern.
_CPUS = re.compile(r"\d+(-\d+)?(,\d+(-\d+)?)*", re.ASCII)
# The same form as a pattern a JSON Schema states: a CPU list such as 4-7 or 0,2,4.
CPU_LIST_PATTERN: Final = r"^\d+(-\d+)?(,\d+(-\d+)?)*$"
_GPUS = re.compile(r"all|\d+(,\d+)*", re.ASCII)
# The highest CPU number a CPU list may name. A list is refused above it
# before any parser expands a range into a set.
MAX_CPU: Final = 65535
_CPU_NUMBER = re.compile(r"\d+", re.ASCII)


def _cpu_list(text: str) -> bool:
    """Say whether ``text`` is a CPU list that names no CPU above ``MAX_CPU``."""
    if not _CPUS.fullmatch(text):
        return False
    return all(
        len(n.lstrip("0")) <= len(str(MAX_CPU)) and int(n) <= MAX_CPU
        for n in _CPU_NUMBER.findall(text)
    )


@dataclass(frozen=True)
class LaunchSettings(_Model):
    """Launch settings shared by every side, with each side's overrides.

    ``overrides`` maps a side name to the fields that side overrides. ``env``
    is a table and merges per variable: the side's variables are laid over the
    shared ones, and the shared variables it does not name still apply. Every
    other field is replaced whole. ``env_pass`` names variables forwarded to
    the side whose values are never recorded. ``identify`` is an argument list
    run once inside each side; an empty list means none. ``perf_counters``
    gives a container the capability to use performance counters and no
    other capability; on a command side and on a Python environment side it
    changes nothing.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"timeout_s": {"minimum": 0}}

    cpus: str | None = None
    gpus: str | None = None
    memory: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    env_pass: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()
    workdir: str | None = None
    network: str | None = None
    timeout_s: float | None = None
    engine: Engine = "auto"
    pull: PullPolicy = "missing"
    identify: tuple[str, ...] = ()
    perf_counters: bool = field(default=False, kw_only=True)
    allow_identical: bool = False
    overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    OVERRIDABLE: ClassVar[tuple[str, ...]] = (
        "cpus",
        "gpus",
        "memory",
        "env",
        "env_pass",
        "mounts",
        "workdir",
        "network",
        "timeout_s",
        "engine",
        "pull",
        "identify",
        "perf_counters",
    )
    # The overridable fields that are tables: an override merges into them per key.
    MERGED_PER_KEY: ClassVar[tuple[str, ...]] = ("env",)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.cpus is not None and not _cpu_list(self.cpus):
            raise ValueError(
                f"cpus is a list such as 4-7 or 0,2,4 with no CPU above {MAX_CPU}: "
                f"{self.cpus[:80]!r}"
            )
        if self.gpus is not None and not _GPUS.fullmatch(self.gpus):
            raise ValueError(f"gpus is 'all' or a comma list of indices: {self.gpus!r}")
        for side, table in self.overrides.items():
            unknown = sorted(set(table) - set(self.OVERRIDABLE))
            if unknown:
                raise ValueError(f"side {side!r} cannot override {', '.join(unknown)}")
            # Each side's merged settings are checked now, not when first used.
            self._merged(side)

    def _merged(self, name: str) -> LaunchSettings:
        own = dict(self.overrides.get(name, {}))
        for key in self.MERGED_PER_KEY:
            if key in own:
                own[key] = {**getattr(self, key), **own[key]}
        return dataclasses.replace(self, overrides={}, **own)

    def for_side(self, side: Side) -> LaunchSettings:
        """Return the settings in effect for a side, overrides merged in.

        A twin gets the settings of the side its ``twin_of`` field names, and
        the positive control those of the baseline its ``control_of`` field
        names.
        """
        return self._merged(side.source)

    def differences(self) -> dict[str, tuple[str, ...]]:
        """Return, per side, the fields in which it differs from the shared settings."""
        out: dict[str, tuple[str, ...]] = {}
        for side in self.overrides:
            merged = self._merged(side)
            changed = tuple(k for k in self.OVERRIDABLE if getattr(merged, k) != getattr(self, k))
            if changed:
                out[side] = changed
        return out

    def effective(
        self,
        *,
        args: Sequence[str] = (),
        entrypoint: str | None = None,
        env: Mapping[str, str] | None = None,
        mounts: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Return the part of the settings that goes into a side's fingerprint.

        Call it on the settings already merged for the side. ``args``,
        ``entrypoint`` and ``env`` are the side's own; ``mounts`` are the
        mounts its kind adds, such as a server's model location, after the
        configured ones. What a launch adds to
        the environment for one round or one entry, the environment pad and
        the work factor of the positive control, is no part of it: a twin's
        fingerprint equals its side's with the environment size varied and
        without.
        """
        merged = {**self.env, **(env or {})}
        return {
            "args": list(args),
            "entrypoint": entrypoint,
            "env": {k: merged[k] for k in sorted(merged)},
            "env_pass": sorted(self.env_pass),
            "mounts": [*self.mounts, *mounts],
            "limits": {"cpus": self.cpus, "gpus": self.gpus, "memory": self.memory},
            "perf_counters": self.perf_counters,
        }


@dataclass(frozen=True)
class RunSettings(_Model):
    """Round counts, warm-ups, twins and where the run folder goes.

    ``same_vs_same`` is ``"on"``, ``"off"`` or the names of the sides that get
    a twin. ``print_plan``, ``json`` and ``no_plugins`` mirror the command-line
    switches of the same names. With ``vary_env_size`` every launch of a
    round gets an environment pad whose length changes from round to round.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "budget_s": {"minimum": 0},
        "warmups": {"minimum": 0},
    }

    rounds: int | Literal["auto"] = "auto"
    rounds_exact: bool = False
    quick: bool = False
    budget_s: float | None = None
    warmups: int = 1
    same_vs_same: Literal["on", "off"] | tuple[str, ...] = "on"
    allow_underpowered: bool = False
    out: str | None = None
    print_plan: bool = False
    json: bool = False
    no_plugins: bool = False
    node_type: str | None = None
    vary_env_size: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.rounds, int) and self.rounds < 1:
            raise ValueError("rounds must be at least 1")


@dataclass(frozen=True)
class QuietSettings(_Model):
    """The quiet-machine check. ``gpu_idle`` of ``None`` means: true when a GPU is requested."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "max_busy_cores": {"minimum": 0},
        "samples": {"minimum": 1},
        "interval_s": {"minimum": 0},
        "max_wait_s": {"minimum": 0},
    }

    max_busy_cores: float = 1.0
    gpu_idle: bool | None = None
    samples: int = 5
    interval_s: float = 2.0
    max_wait_s: float = 1800.0


@dataclass(frozen=True)
class CensusSettings(_Model):
    """The neighbour census."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"max_busy_cores": {"minimum": 0}}

    max_busy_cores: float = 0.5


@dataclass(frozen=True)
class Witness(_Model):
    """What was seen of the machine during one launch. It holds no measurement.

    A witness without a value is in one of two states, and they are kept
    apart:

    * it does not apply: there was nothing to watch, for example the GPU
      witnesses when no GPU is selected, the cache witness when no CPU set is
      pinned, or every witness on a platform that has no independent one. Its
      value is ``None`` and its name is not in ``failed``. It exceeds nothing;
    * its probe failed: it applies but could not be read for this launch. Its
      value is ``None`` and its name is in ``failed``. It counts as exceeding
      its threshold, so the round is marked as disturbed.

    ``failed`` holds names out of ``WITNESSES``. A witness named there has no
    value.

    ``includes_launch`` names the busy-core witnesses whose value counts the
    launch's own load in, because the side could not report the CPU time of
    its own processes. Such a value is an upper bound on the load of others:
    at or under its threshold the launch is not disturbed; above it the
    launch is undecided (see ``undecided``), which is neither exceeding the
    threshold nor a pass.
    """

    busy_cores: float | None = None
    busy_cores_cache: float | None = None
    gpu_other_processes: int | None = None
    gpu_throttle_events: int | None = None
    failed: tuple[str, ...] = ()
    includes_launch: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        unknown = sorted((set(self.failed) | set(self.includes_launch)) - set(WITNESSES))
        if unknown:
            raise ValueError(f"not a witness: {', '.join(unknown)}")
        valued = sorted(name for name in self.failed if getattr(self, name) is not None)
        if valued:
            raise ValueError(f"a failed witness has no value: {', '.join(valued)}")
        if len(set(self.failed)) != len(self.failed):
            raise ValueError("a failed witness is named once")
        other = sorted(set(self.includes_launch) - set(WITNESSES_BUSY_CORES))
        if other:
            raise ValueError(
                f"only the busy-core witnesses can hold the launch: {', '.join(other)}"
            )
        empty = sorted(name for name in self.includes_launch if getattr(self, name) is None)
        if empty:
            raise ValueError(f"a witness with the launch in it has a value: {', '.join(empty)}")
        if len(set(self.includes_launch)) != len(self.includes_launch):
            raise ValueError("a witness with the launch in it is named once")

    def with_failed(self, *names: str) -> Witness:
        """Return a copy in which the probes of the named witnesses failed."""
        cleared: dict[str, Any] = dict.fromkeys(names)
        merged = tuple(dict.fromkeys((*self.failed, *names)))
        kept = tuple(name for name in self.includes_launch if name not in names)
        return dataclasses.replace(self, failed=merged, includes_launch=kept, **cleared)


@dataclass(frozen=True)
class DiscardThresholds(_Model):
    """The thresholds above which a witness marks a launch as disturbed."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "max_busy_cores": {"minimum": 0},
        "max_gpu_other_processes": {"minimum": 0},
        "max_gpu_throttle_events": {"minimum": 0},
    }

    max_busy_cores: float = 2.0
    max_gpu_other_processes: int = 0
    max_gpu_throttle_events: int = 0


@dataclass(frozen=True)
class RoundWitness(_Model):
    """The witness of one launch with the round it belongs to. It holds no measurement."""

    round: int
    name: str
    witness: Witness


@dataclass(frozen=True)
class SetAside(_Model):
    """The decision on disturbed rounds: the rounds set aside and the hash of the decision."""

    rounds: tuple[int, ...]
    sha256: str


def exceeded(witness: Witness, thresholds: DiscardThresholds) -> tuple[str, ...]:
    """Name the witnesses of one launch that exceed their threshold.

    A witness that does not apply exceeds nothing. A witness whose probe
    failed counts as exceeding its threshold. A witness whose value holds the
    launch's own load exceeds nothing: above its threshold it is undecided
    instead (see ``undecided``). The busy cores on the CPUs that share a
    cache have no threshold and are never named.
    """
    limits = _witness_limits(thresholds)
    over: list[str] = []
    for name in WITNESSES_WITH_THRESHOLD:
        if name in witness.includes_launch:
            continue
        value = getattr(witness, name)
        if name in witness.failed or (value is not None and value > limits[name]):
            over.append(name)
    return tuple(over)


def undecided(witness: Witness, thresholds: DiscardThresholds) -> tuple[str, ...]:
    """Name the witnesses of one launch that cannot judge it.

    A witness is undecided when its value holds the launch's own load and is
    above its threshold: the load of others may or may not be. An undecided
    launch does not mark its round as disturbed. It is kept apart from a
    failed probe, which exceeds its threshold. The busy cores on the CPUs
    that share a cache have no threshold and are never named.
    """
    limits = _witness_limits(thresholds)
    return tuple(
        name
        for name in WITNESSES_WITH_THRESHOLD
        if name in witness.includes_launch and getattr(witness, name) > limits[name]
    )


def _witness_limits(thresholds: DiscardThresholds) -> dict[str, float]:
    return {
        WITNESS_BUSY_CORES: thresholds.max_busy_cores,
        WITNESS_GPU_OTHER_PROCESSES: thresholds.max_gpu_other_processes,
        WITNESS_GPU_THROTTLE_EVENTS: thresholds.max_gpu_throttle_events,
    }


def set_aside(thresholds: DiscardThresholds, witnesses: Sequence[RoundWitness]) -> SetAside:
    """Decide which rounds are disturbed.

    A launch whose witness exceeds a threshold, or whose probe failed, marks
    its whole round. The input holds no measured value, so the decision
    cannot depend on one. The hash covers the thresholds and the rounds set
    aside.
    """
    rounds = tuple(sorted({w.round for w in witnesses if exceeded(w.witness, thresholds)}))
    digest = sha256_hex(canonical_json({"thresholds": thresholds, "rounds": rounds}))
    return SetAside(rounds=rounds, sha256=digest)


@dataclass(frozen=True)
class GateSettings(_Model):
    """Machine-check settings."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"lock_timeout_s": {"minimum": 0}}

    mode: GateMode = "warn"
    wait_quiet: bool = False
    locks: tuple[str, ...] = ()
    lock_timeout_s: float = 1800.0
    allow_mixed_core_types: bool = False
    quiet: QuietSettings = field(default_factory=QuietSettings)
    census: CensusSettings = field(default_factory=CensusSettings)
    discard: DiscardThresholds = field(default_factory=DiscardThresholds)


@dataclass(frozen=True)
class RuleSettings(_Model):
    """The name of the verdict rule and the outcomes that make the exit code 1."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"name": {"minLength": 1}}

    name: str = "strict"
    fail_on: tuple[FailOn, ...] = ()


@dataclass(frozen=True)
class CaseSettings(_Model):
    """Which cases are primary and how cases are grouped for the noise floor.

    ``primary`` is a list of glob patterns; empty means the driver's own
    default. ``groups`` maps a group name to glob patterns. A pattern matches
    as ``case_matches`` says.
    """

    primary: tuple[str, ...] = ()
    groups: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def is_primary(self, case: str, default: Iterable[str], *, better: str = "lower") -> bool:
        """Say whether a case counts toward the verdict.

        With patterns in ``primary``, a case is primary when it matches one of
        them. Without, it is primary when the driver names it: ``default`` is
        what ``Driver.default_primary`` returned.

        A case whose ``better`` is ``none`` is never primary. A pattern that
        matches it among other cases leaves it secondary, and so does the
        driver's own list, which may name every case a workload prints. A
        pattern of the config that is equal to its id, with or without the
        mark a run adds to it (``case_suffix``), asks for it outright: that is
        refused, because nothing the user asked for is left out silently.
        """
        if better == "none":
            if case in self.primary or case_unsuffixed(case) in self.primary:
                raise Refusal(
                    "E_USAGE",
                    f"case {case!r} describes and does not judge (its better is none): "
                    "it cannot be a primary case",
                    scope="case",
                )
            return False
        if self.primary:
            return case_matches(case, self.primary)
        return case in set(default)

    def group_of(self, case: str) -> str | None:
        """Return the name of the first group whose patterns match the case, or ``None``."""
        for name, patterns in self.groups.items():
            if case_matches(case, patterns):
                return name
        return None


@dataclass(frozen=True)
class EnergySettings(_Model):
    """GPU power sampling.

    A value is never made from one sample, so ``min_samples`` is at least 2.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "interval_s": {"exclusiveMinimum": 0},
        "min_samples": {"minimum": 2},
    }

    enabled: bool = False
    interval_s: float = 0.2
    min_samples: int = 10


@dataclass(frozen=True)
class ReportSettings(_Model):
    """What a results document may show, and whether a run writes the report page."""

    include_image_refs: bool = False
    html: bool = True


@dataclass(frozen=True)
class ControlSettings(_Model):
    """The positive control: the baseline started once with the workload run twice in it.

    ``positive`` is ``"on"``, ``"off"`` or ``None`` for the default: on,
    except for an experiment of serving sides. ``positive_tolerance`` is how
    far the control may read from its expected value, as a fraction of it.
    It lies below ``CONTROL_TOLERANCE_BELOW``: from there on a control that
    reads no difference at all would lie within the tolerance.
    ``positive_via`` says how the control doubles the work: ``repeat`` runs
    the workload twice in one start, ``factor`` runs it once with the
    variable that asks the workload for twice the work.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "positive_tolerance": {"minimum": 0, "exclusiveMaximum": CONTROL_TOLERANCE_BELOW}
    }

    positive: ControlMode | None = None
    positive_tolerance: float = 0.10
    positive_via: ControlVia = "repeat"


@dataclass(frozen=True)
class LaunchCostSettings(_Model):
    """The measurement of what a launch costs before the workload does anything.

    ``launches`` empty launches are timed during warm-up; 0 turns the
    measurement off. ``note_share`` is the share of a ``wall`` value above
    which the launch-cost note is given.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "launches": {"minimum": 0},
        "note_share": {"exclusiveMinimum": 0, "maximum": 1},
    }

    launches: int = 20
    note_share: float = 0.01


@dataclass(frozen=True)
class ExplainSettings(_Model):
    """The explain step: untimed launches under instruments after the last round.

    ``mode`` is ``always``, ``auto`` (only when a primary case came out
    better or worse) or ``off``. ``sample_hz`` is the number of stack samples
    per second, ``call_graph`` how call graphs are collected, and ``top`` how
    many functions and shared objects are kept per side.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "sample_hz": {"minimum": 1},
        "top": {"minimum": 1},
    }

    mode: ExplainMode = "always"
    sample_hz: int = 99
    call_graph: CallGraph = "fp"
    top: int = 20


@dataclass(frozen=True)
class PlotSettings(_Model):
    """The charts: whether they are drawn, and the most round-by-round charts."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"max_round_charts": {"minimum": 0}}

    mode: PlotMode = "auto"
    max_round_charts: int = 12


@dataclass(frozen=True)
class LoadSettings(_Model):
    """The serving load: the levels, what a level counts, and the length of each.

    ``level_kind`` is ``concurrency``, a number of concurrent requests, or
    ``rate``, a number of requests per second. A level is a whole number of
    at least 1.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"level_duration_s": {"minimum": 0}}

    levels: tuple[int, ...] = ()
    level_duration_s: float | None = None
    level_kind: LevelKind = "concurrency"

    def __post_init__(self) -> None:
        super().__post_init__()
        if any(level < 1 for level in self.levels):
            raise ValueError("a load level is a whole number of at least 1")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("a load level is given once")

    def label(self, level: int) -> str:
        """Return the label of one level: ``c32`` or ``r32``."""
        return level_label(level, self.level_kind)

    def labels(self) -> tuple[str, ...]:
        """Return the labels of the levels, in the order the levels run."""
        return tuple(self.label(level) for level in self.levels)

    def highest(self) -> str | None:
        """Return the label of the highest level, or ``None`` when there are no levels."""
        return self.label(max(self.levels)) if self.levels else None


@dataclass(frozen=True)
class Experiment(_Coerced):
    """One workload compared across sides.

    ``sides`` are the user's sides, never twins. When no side has the role
    ``baseline`` the last one becomes the baseline. ``workload`` is the shared
    argument list, or ``None``.
    """

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"driver": {"minLength": 1}}

    sides: tuple[Side, ...]
    workload: tuple[str, ...] | None = None
    driver: str = "wall"
    launch: LaunchSettings = field(default_factory=LaunchSettings)
    run: RunSettings = field(default_factory=RunSettings)
    gates: GateSettings = field(default_factory=GateSettings)
    rule: RuleSettings = field(default_factory=RuleSettings)
    cases: CaseSettings = field(default_factory=CaseSettings)
    energy: EnergySettings = field(default_factory=EnergySettings)
    report: ReportSettings = field(default_factory=ReportSettings)
    load: LoadSettings = field(default_factory=LoadSettings)
    controls: ControlSettings = field(default_factory=ControlSettings)
    launch_cost: LaunchCostSettings = field(default_factory=LaunchCostSettings)
    explain: ExplainSettings = field(default_factory=ExplainSettings)
    plots: PlotSettings = field(default_factory=PlotSettings)

    def __post_init__(self) -> None:
        super().__post_init__()
        sides = self.sides
        if not sides:
            raise Refusal("E_USAGE", "an experiment needs at least one side")
        names = [s.name for s in sides]
        doubled = sorted({n for n in names if names.count(n) > 1})
        if doubled:
            raise Refusal("E_USAGE", f"side name given twice: {', '.join(doubled)}")
        if any(s.role == "twin" for s in sides):
            raise Refusal("E_USAGE", "a twin is never declared as a side; use same_vs_same")
        if any(s.role == "control" for s in sides):
            raise Refusal(
                "E_USAGE", "the positive control is never declared as a side; use controls.positive"
            )
        baselines = [s.name for s in sides if s.role == "baseline"]
        if len(baselines) > 1:
            raise Refusal("E_USAGE", f"more than one baseline: {', '.join(baselines)}")
        if not baselines:
            sides = (*sides[:-1], sides[-1].with_role("baseline"))
            object.__setattr__(self, "sides", sides)
        kinds = {s.kind for s in sides}
        for alone in (KIND_SERVE, KIND_FILE):
            if alone in kinds and len(kinds) > 1:
                raise Refusal("E_USAGE", f"{alone} sides cannot be mixed with other kinds of side")
        if isinstance(self.run.same_vs_same, tuple):
            unknown = sorted(set(self.run.same_vs_same) - set(names))
            if unknown:
                raise Refusal("E_USAGE", f"same_vs_same names no side: {', '.join(unknown)}")
        unknown = sorted(set(self.launch.overrides) - set(names))
        if unknown:
            raise Refusal("E_USAGE", f"launch overrides name no side: {', '.join(unknown)}")

    @property
    def baseline(self) -> str:
        """The name of the baseline side."""
        return next(s.name for s in self.sides if s.role == "baseline")

    @property
    def subjects(self) -> tuple[str, ...]:
        """The names of the sides compared against the baseline."""
        return tuple(s.name for s in self.sides if s.role == "subject")

    @property
    def is_serving(self) -> bool:
        """Whether the sides are serving sides."""
        return all(s.kind == KIND_SERVE for s in self.sides)

    def side(self, name: str) -> Side:
        """Return the side with this name."""
        for s in self.sides:
            if s.name == name:
                return s
        raise Refusal("E_USAGE", f"no side named {name!r}")

    def twinned(self) -> tuple[str, ...]:
        """Return the names of the sides that get a twin."""
        choice = self.run.same_vs_same
        if choice == "on":
            return tuple(s.name for s in self.sides)
        if choice == "off":
            return ()
        return tuple(s.name for s in self.sides if s.name in choice)

    def lineup(self) -> tuple[Side, ...]:
        """Return the lineup: every side in the order given, each followed by its twin.

        The positive control is not part of it: see ``control``.
        """
        twinned = set(self.twinned())
        out: list[Side] = []
        for s in self.sides:
            out.append(s)
            if s.name in twinned:
                out.append(s.twin())
        return tuple(out)

    @property
    def positive_control(self) -> bool:
        """Whether the positive control runs.

        ``controls.positive`` decides when it is set. Left unset, the control
        is on for an experiment with no serving side and off for a serving
        experiment. Sides that are result files have no control, whatever the
        setting says: nothing is launched for them.
        """
        if any(s.kind == KIND_FILE for s in self.sides):
            return False
        if self.controls.positive is not None:
            return self.controls.positive == "on"
        return not self.is_serving

    def control(self) -> Side | None:
        """Return the positive-control entry, or ``None`` when the control does not run.

        It is the baseline's control, named with the reserved suffix
        ``~twice``. It is no part of the lineup: it runs last in every round,
        at the position one past the lineup's length, gets no warm-up launch
        and no twin, and is never one of a compared pair.
        """
        if not self.positive_control:
            return None
        return self.side(self.baseline).control()

    def explain_launches(self) -> int:
        """Return the number of explain launches a plan of this experiment counts.

        Each subject and the baseline is launched once per instrument; sides
        that are result files are never launched.
        """
        if any(s.kind == KIND_FILE for s in self.sides):
            return 0
        return planned_explain_launches(len(self.sides), self.explain.mode)

    def to_json(self, *, redact: bool = True) -> dict[str, Any]:
        """Return the resolved config, shaped like the config file.

        Durations are numbers of seconds. A key whose value is unset is left
        out. With ``redact`` the value of every credential-like environment
        variable is replaced.
        """
        return _experiment_to_config(self, redact=redact)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Experiment:
        """Build an experiment from a config. An unknown key or a bad value is refused."""
        return _experiment_from_config(data)


# ---------------------------------------------------------------------------
# Config: the strict reading of a config-shaped dict
# ---------------------------------------------------------------------------


def _config_error(message: str, **detail: Any) -> Refusal:
    return Refusal("E_CONFIG", message, detail=detail)


class _Table:
    """A config table being read. A key nobody asked for is refused as unknown."""

    def __init__(self, data: Any, path: str) -> None:
        if not isinstance(data, Mapping):
            raise _config_error(f"{path or 'the config'} must be a table")
        self._data: dict[str, Any] = {str(k): v for k, v in data.items()}
        self._path = path
        self._seen: set[str] = set()

    @property
    def path(self) -> str:
        return self._path

    def key(self, name: str) -> str:
        return f"{self._path}.{name}" if self._path else name

    def has(self, name: str) -> bool:
        return name in self._data

    def names(self) -> tuple[str, ...]:
        return tuple(self._data)

    def take(self, name: str, kind: Callable[[Any, str], _T], default: _D) -> _T | _D:
        self._seen.add(name)
        if name not in self._data:
            return default
        return kind(self._data[name], self.key(name))

    def table(self, name: str) -> _Table:
        self._seen.add(name)
        return _Table(self._data.get(name, {}), self.key(name))

    def done(self) -> None:
        unknown = [self.key(k) for k in self._data if k not in self._seen]
        if unknown:
            raise _config_error(f"unknown config key: {', '.join(unknown)}", unknown=unknown)


def _c_str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise _config_error(f"{key} must be text")
    return value


def _c_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise _config_error(f"{key} must be true or false")
    return value


def _c_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _config_error(f"{key} must be a whole number")
    return value


def _c_number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise _config_error(f"{key} must be a number")
    return float(value)


def _c_limited(
    kind: Callable[[Any, str], _T], owner: type[_Coerced], name: str
) -> Callable[[Any, str], _T]:
    """Wrap a reader so that the value also keeps the limits of the field it fills."""
    limits = owner.LIMITS[name]

    def read(value: Any, key: str) -> _T:
        out = kind(value, key)
        try:
            _keep_limits(key, out, limits)
        except ValueError as exc:
            raise _config_error(str(exc)) from None
        return out

    return read


def _c_duration(value: Any, key: str) -> float:
    if not isinstance(value, str | int | float):
        raise _config_error(f"{key} must be a duration such as 90s, 10m or 1h30m")
    try:
        return parse_duration(value)
    except ValueError:
        raise _config_error(f"{key} must be a duration such as 90s, 10m or 1h30m") from None


def _c_strs(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
        raise _config_error(f"{key} must be a list of texts")
    return tuple(value)


def _c_ints(value: Any, key: str) -> tuple[int, ...]:
    """Read whole numbers of at least 1: a list, one number, or a text such as ``1,8,32``."""
    items: Any = value
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        items = [int(part) if part.isdecimal() else part for part in parts]
    elif isinstance(value, int) and not isinstance(value, bool):
        items = [value]
    if not isinstance(items, list | tuple) or not all(
        isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in items
    ):
        raise _config_error(f"{key} must be a list of whole numbers of at least 1")
    return tuple(items)


def _c_env(value: Any, key: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise _config_error(f"{key} must be a table of text values")
    return dict(value)


def _c_mapping(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _config_error(f"{key} must be a table")
    return {str(k): v for k, v in value.items()}


def _c_enum(*allowed: str) -> Callable[[Any, str], Any]:
    def read(value: Any, key: str) -> Any:
        if not isinstance(value, str) or value not in allowed:
            raise _config_error(f"{key} must be one of {', '.join(allowed)}")
        return value

    return read


def _c_cpus(value: Any, key: str) -> str:
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(text, str) or not _cpu_list(text):
        raise _config_error(
            f"{key} must be a CPU list such as 4-7 or 0,2,4 with no CPU above {MAX_CPU}"
        )
    return text


def _c_gpus(value: Any, key: str) -> str:
    text = value
    if isinstance(value, int) and not isinstance(value, bool):
        text = str(value)
    elif isinstance(value, list | tuple):
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            raise _config_error(f"{key} must be 'all' or a comma list of GPU indices")
        text = ",".join(str(v) for v in value)
    if not isinstance(text, str) or not _GPUS.fullmatch(text):
        raise _config_error(f"{key} must be 'all' or a comma list of GPU indices")
    return text


def _c_rounds(value: Any, key: str) -> int | Literal["auto"]:
    if value == "auto":
        return "auto"
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _config_error(f"{key} must be 'auto' or a whole number of at least 1")
    return value


def _c_same_vs_same(value: Any, key: str) -> Literal["on", "off"] | tuple[str, ...]:
    if value == "on":
        return "on"
    if value == "off":
        return "off"
    if isinstance(value, str):
        names = tuple(part.strip() for part in value.split(","))
    elif isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
        names = tuple(value)
    else:
        raise _config_error(f"{key} must be on, off or a list of side names")
    if not names or not all(names):
        raise _config_error(f"{key} must be on, off or a list of side names")
    return names


def _c_argv(value: Any, key: str) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            argv = tuple(shlex.split(value))
        except ValueError:
            raise _config_error(f"{key} is not a readable command line") from None
    else:
        argv = _c_strs(value, key)
    if not argv:
        raise _config_error(f"{key} must not be empty")
    return argv


def _c_argv_list(value: Any, key: str) -> tuple[str, ...]:
    argv = _c_strs(value, key)
    if not argv:
        raise _config_error(f"{key} must not be empty")
    return argv


def _c_plugin_spec(value: Any, key: str) -> dict[str, Any]:
    if isinstance(value, str):
        return {"spec": value}
    if isinstance(value, Mapping) and _plain(value):
        return dict(json.loads(json.dumps(value)))
    raise _config_error(f"{key} must be a text or a table of plain values")


def _plain(value: Any) -> bool:
    """Say whether ``value`` is made of tables, lists, text, numbers and true or false."""
    if isinstance(value, Mapping):
        return all(isinstance(k, str) and _plain(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return all(_plain(v) for v in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str | int | bool)


def _c_text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise _config_error(f"{key} must be a text that is not empty")
    return value


def _c_paths(value: Any, key: str) -> tuple[str, ...]:
    paths = (value,) if isinstance(value, str) else _c_strs(value, key)
    if not paths or not all(paths):
        raise _config_error(f"{key} must name at least one file")
    return paths


# (config key, field name, reader) for every launch setting a side may override.
_LAUNCH_KEYS: Final[tuple[tuple[str, str, Callable[[Any, str], Any]], ...]] = (
    ("cpus", "cpus", _c_cpus),
    ("gpus", "gpus", _c_gpus),
    ("memory", "memory", _c_str),
    ("env", "env", _c_env),
    ("env_pass", "env_pass", _c_strs),
    ("mounts", "mounts", _c_strs),
    ("workdir", "workdir", _c_str),
    ("network", "network", _c_str),
    ("timeout", "timeout_s", _c_duration),
    ("engine", "engine", _c_enum(*get_args(Engine))),
    ("pull", "pull", _c_enum(*get_args(PullPolicy))),
    ("identify", "identify", _c_strs),
    ("perf_counters", "perf_counters", _c_bool),
)

_SIDE_KIND_KEYS: Final[tuple[str, ...]] = (
    "image",
    "cmd",
    "python",
    "venv",
    "conda",
    "serve",
    "file",
    "kind",
)


def _launch_values(table: _Table) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, name, kind in _LAUNCH_KEYS:
        if table.has(key):
            out[name] = table.take(key, kind, None)
    return out


def _serve_from_config(table: _Table) -> ServeSpec:
    ready = table.table("ready")
    probe = table.table("probe")
    spec = ServeSpec(
        image=table.take("image", _c_limited(_c_str, ServeSpec, "image"), None),
        args=table.take("args", _c_strs, ()),
        port=table.take("port", _c_limited(_c_int, ServeSpec, "port"), 8000),
        ready=Ready(
            http=ready.take("http", _c_str, DEFAULT_READY.http),
            timeout_s=ready.take("timeout", _c_duration, DEFAULT_READY.timeout_s),
        ),
        env=table.take("env", _c_env, {}),
        model=table.take("model", _c_str, None),
        model_name=table.take("model_name", _c_str, None),
        launcher=table.take("launcher", _c_str, None),
        command=table.take("command", _c_argv_list, ()),
        probe=Probe(
            path=probe.take("path", _c_str, "/v1/chat/completions"),
            body=probe.take("body", _c_mapping, None),
        ),
        phases=table.take("phases", _c_env, {}),
    )
    ready.done()
    probe.done()
    table.done()
    if (spec.image is None) == (not spec.command):
        raise _config_error(f"{table.key('image')} or {table.key('command')}: give exactly one")
    return spec


def _side_from_config(name: str, table: _Table) -> tuple[Side, dict[str, Any]]:
    given = [k for k in _SIDE_KIND_KEYS if table.has(k)]
    if len(given) != 1:
        raise _config_error(f"{table.path} needs exactly one of {', '.join(_SIDE_KIND_KEYS)}")
    key = given[0]
    baseline = table.take("baseline", _c_bool, False)
    overrides = _launch_values(launch := table.table("launch"))
    launch.done()
    if key == "image":
        side = Side.image(
            name,
            table.take("image", _c_text, ""),
            args=table.take("args", _c_strs, ()),
            env=table.take("env", _c_env, {}),
            entrypoint=table.take("entrypoint", _c_str, None),
        )
    elif key == "cmd":
        side = Side.command(name, table.take("cmd", _c_argv, ()))
    elif key in ("python", "venv", "conda"):
        value = table.take(key, _c_text, "")
        field_name = "interpreter" if key == "python" else key
        side = Side.python(name, **{field_name: value})
    elif key == "serve":
        spec = _serve_from_config(table.table("serve"))
        side = Side(name=name, kind=KIND_SERVE, spec=spec.to_json())
    elif key == "file":
        side = Side.files(
            name, table.take("file", _c_paths, ()), format=table.take("format", _c_str, None)
        )
    else:
        kind = table.take("kind", _c_text, "")
        side = Side(name=name, kind=kind, spec=table.take("spec", _c_plugin_spec, {"spec": ""}))
    table.done()
    return (side.with_role("baseline") if baseline else side), overrides


def _experiment_from_config(data: Mapping[str, Any]) -> Experiment:
    try:
        return _read_config(data)
    except ValueError as exc:
        raise _config_error(str(exc)) from exc


def _read_config(data: Mapping[str, Any]) -> Experiment:
    top = _Table(data, "")

    run_t = top.table("run")
    run = _settings(
        RunSettings,
        rounds=run_t.take("rounds", _c_rounds, "auto"),
        rounds_exact=run_t.take("rounds_exact", _c_bool, False),
        quick=run_t.take("quick", _c_bool, False),
        budget_s=run_t.take("budget", _c_duration, None),
        warmups=run_t.take("warmups", _c_limited(_c_int, RunSettings, "warmups"), 1),
        same_vs_same=run_t.take("same_vs_same", _c_same_vs_same, "on"),
        allow_underpowered=run_t.take("allow_underpowered", _c_bool, False),
        out=run_t.take("out", _c_str, None),
        print_plan=run_t.take("print_plan", _c_bool, False),
        json=run_t.take("json", _c_bool, False),
        no_plugins=run_t.take("no_plugins", _c_bool, False),
        node_type=run_t.take("node_type", _c_str, None),
        vary_env_size=run_t.take("vary_env_size", _c_bool, False),
    )
    run_t.done()

    work_t = top.table("workload")
    workload = work_t.take("argv", _c_argv, None)
    driver = work_t.take("driver", _c_text, "wall")
    load = _settings(
        LoadSettings,
        levels=work_t.take("levels", _c_ints, ()),
        level_duration_s=work_t.take("level_duration", _c_duration, None),
        level_kind=work_t.take("level_kind", _c_enum(*LEVEL_KINDS), "concurrency"),
    )
    work_t.done()

    launch_t = top.table("launch")
    launch_values = _launch_values(launch_t)
    allow_identical = launch_t.take("allow_identical", _c_bool, False)
    launch_t.done()

    sides_t = top.table("sides")
    sides: list[Side] = []
    overrides: dict[str, dict[str, Any]] = {}
    for name in sides_t.names():
        side, own = _side_from_config(name, sides_t.table(name))
        sides.append(side)
        if own:
            overrides[name] = own
    sides_t.done()
    if not sides:
        raise _config_error("the config declares no side")
    launch = _settings(
        LaunchSettings, **launch_values, allow_identical=allow_identical, overrides=overrides
    )

    gates_t = top.table("gates")
    quiet_t = gates_t.table("quiet")
    census_t = gates_t.table("census")
    discard_t = gates_t.table("discard")
    gates = _settings(
        GateSettings,
        mode=gates_t.take("mode", _c_enum(*GATE_MODES), "warn"),
        wait_quiet=gates_t.take("wait_quiet", _c_bool, False),
        locks=gates_t.take("locks", _c_strs, ()),
        lock_timeout_s=gates_t.take("lock_timeout", _c_duration, 1800.0),
        allow_mixed_core_types=gates_t.take("allow_mixed_core_types", _c_bool, False),
        quiet=QuietSettings(
            max_busy_cores=quiet_t.take(
                "max_busy_cores", _c_limited(_c_number, QuietSettings, "max_busy_cores"), 1.0
            ),
            gpu_idle=quiet_t.take("gpu_idle", _c_bool, None),
            samples=quiet_t.take("samples", _c_limited(_c_int, QuietSettings, "samples"), 5),
            interval_s=quiet_t.take(
                "interval_s", _c_limited(_c_number, QuietSettings, "interval_s"), 2.0
            ),
            max_wait_s=quiet_t.take(
                "max_wait_s", _c_limited(_c_number, QuietSettings, "max_wait_s"), 1800.0
            ),
        ),
        census=CensusSettings(
            max_busy_cores=census_t.take(
                "max_busy_cores", _c_limited(_c_number, CensusSettings, "max_busy_cores"), 0.5
            )
        ),
        discard=DiscardThresholds(
            max_busy_cores=discard_t.take(
                "max_busy_cores", _c_limited(_c_number, DiscardThresholds, "max_busy_cores"), 2.0
            )
        ),
    )
    for t in (quiet_t, census_t, discard_t, gates_t):
        t.done()

    rule_t = top.table("rule")
    rule = _settings(
        RuleSettings,
        name=rule_t.take("name", _c_text, "strict"),
        fail_on=tuple(
            _c_enum(*FAIL_ON)(v, rule_t.key("fail_on")) for v in rule_t.take("fail_on", _c_strs, ())
        ),
    )
    rule_t.done()

    cases_t = top.table("cases")
    groups_t = cases_t.table("groups")
    cases = _settings(
        CaseSettings,
        primary=cases_t.take("primary", _c_strs, ()),
        groups={name: groups_t.take(name, _c_strs, ()) for name in groups_t.names()},
    )
    groups_t.done()
    cases_t.done()

    energy_t = top.table("energy")
    energy = _settings(
        EnergySettings,
        enabled=energy_t.take("enabled", _c_bool, False),
        interval_s=energy_t.take(
            "interval_s", _c_limited(_c_number, EnergySettings, "interval_s"), 0.2
        ),
        min_samples=energy_t.take(
            "min_samples", _c_limited(_c_int, EnergySettings, "min_samples"), 10
        ),
    )
    energy_t.done()

    report_t = top.table("report")
    report = _settings(
        ReportSettings,
        include_image_refs=report_t.take("include_image_refs", _c_bool, False),
        html=report_t.take("html", _c_bool, True),
    )
    report_t.done()

    controls_t = top.table("controls")
    controls = _settings(
        ControlSettings,
        positive=controls_t.take("positive", _c_enum(*CONTROL_MODES), None),
        positive_tolerance=controls_t.take(
            "positive_tolerance",
            _c_limited(_c_number, ControlSettings, "positive_tolerance"),
            0.10,
        ),
        positive_via=controls_t.take("positive_via", _c_enum(*CONTROL_VIAS), "repeat"),
    )
    controls_t.done()

    cost_t = top.table("launch_cost")
    launch_cost = _settings(
        LaunchCostSettings,
        launches=cost_t.take("launches", _c_limited(_c_int, LaunchCostSettings, "launches"), 20),
        note_share=cost_t.take(
            "note_share", _c_limited(_c_number, LaunchCostSettings, "note_share"), 0.01
        ),
    )
    cost_t.done()

    explain_t = top.table("explain")
    explain = _settings(
        ExplainSettings,
        mode=explain_t.take("mode", _c_enum(*EXPLAIN_MODES), "always"),
        sample_hz=explain_t.take("sample_hz", _c_limited(_c_int, ExplainSettings, "sample_hz"), 99),
        call_graph=explain_t.take("call_graph", _c_enum(*CALL_GRAPHS), "fp"),
        top=explain_t.take("top", _c_limited(_c_int, ExplainSettings, "top"), 20),
    )
    explain_t.done()

    plots_t = top.table("plots")
    plots = _settings(
        PlotSettings,
        mode=plots_t.take("mode", _c_enum(*PLOT_MODES), "auto"),
        max_round_charts=plots_t.take(
            "max_round_charts", _c_limited(_c_int, PlotSettings, "max_round_charts"), 12
        ),
    )
    plots_t.done()
    top.done()

    return Experiment(
        sides=tuple(sides),
        workload=workload,
        driver=driver,
        launch=launch,
        run=run,
        gates=gates,
        rule=rule,
        cases=cases,
        energy=energy,
        report=report,
        load=load,
        controls=controls,
        launch_cost=launch_cost,
        explain=explain,
        plots=plots,
    )


def _settings(cls: type[_M], **values: Any) -> _M:
    try:
        return cls(**values)
    except ValueError as exc:
        raise _config_error(str(exc)) from exc


def _drop_unset(table: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in table.items() if v is not None}


def _env_out(env: Mapping[str, str], redact: bool) -> dict[str, str]:
    return redact_env(env) if redact else dict(env)


def _launch_to_config(values: Mapping[str, Any], redact: bool) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, name, _kind in _LAUNCH_KEYS:
        if name not in values or values[name] is None:
            continue
        value = values[name]
        out[key] = _env_out(value, redact) if name == "env" else _encode(value)
    return out


def _side_to_config(side: Side, overrides: Mapping[str, Any], redact: bool) -> dict[str, Any]:
    spec = side.spec
    out: dict[str, Any]
    if side.kind == KIND_IMAGE:
        out = {
            "image": spec.get("image"),
            "args": _encode(spec.get("args", ())),
            "env": _env_out(spec.get("env", {}), redact),
            "entrypoint": spec.get("entrypoint"),
        }
    elif side.kind == KIND_CMD:
        out = {"cmd": _encode(spec.get("argv", ()))}
    elif side.kind == KIND_PYTHON:
        out = {"python": spec.get("interpreter")}
    elif side.kind in (KIND_VENV, KIND_CONDA):
        out = {side.kind: spec.get(side.kind)}
    elif side.kind == KIND_SERVE:
        serve = side.serve_spec()
        out = {
            "serve": _drop_unset(
                {
                    "image": serve.image,
                    "args": list(serve.args),
                    "port": serve.port,
                    "ready": {"http": serve.ready.http, "timeout": serve.ready.timeout_s},
                    "env": _env_out(serve.env, redact),
                    "model": serve.model,
                    "model_name": serve.model_name,
                    "launcher": serve.launcher,
                    "command": list(serve.command) or None,
                    "probe": _drop_unset(
                        {"path": serve.probe.path, "body": _encode(serve.probe.body)}
                    ),
                    "phases": dict(serve.phases),
                }
            )
        }
    elif side.kind == KIND_FILE:
        out = {"file": _encode(spec.get("paths", ())), "format": spec.get("format")}
    else:
        text = spec.get("spec", "")
        one_text = set(spec) <= {"spec"} and isinstance(text, str)
        out = {"kind": side.kind, "spec": text if one_text else _encode(spec)}
    if side.role == "baseline":
        out["baseline"] = True
    if overrides:
        out["launch"] = _launch_to_config(overrides, redact)
    return _drop_unset(out)


def _experiment_to_config(exp: Experiment, *, redact: bool) -> dict[str, Any]:
    run = exp.run
    same = run.same_vs_same
    launch = exp.launch
    shared = {name: getattr(launch, name) for _key, name, _kind in _LAUNCH_KEYS}
    quiet = exp.gates.quiet
    return {
        "run": _drop_unset(
            {
                "rounds": run.rounds,
                "rounds_exact": run.rounds_exact,
                "quick": run.quick,
                "budget": run.budget_s,
                "warmups": run.warmups,
                "same_vs_same": same if isinstance(same, str) else list(same),
                "allow_underpowered": run.allow_underpowered,
                "out": run.out,
                "print_plan": run.print_plan,
                "json": run.json,
                "no_plugins": run.no_plugins,
                "node_type": run.node_type,
                "vary_env_size": run.vary_env_size,
            }
        ),
        "workload": _drop_unset(
            {
                "argv": None if exp.workload is None else list(exp.workload),
                "driver": exp.driver,
                "levels": list(exp.load.levels),
                "level_duration": exp.load.level_duration_s,
                "level_kind": exp.load.level_kind,
            }
        ),
        "sides": {
            s.name: _side_to_config(s, launch.overrides.get(s.name, {}), redact) for s in exp.sides
        },
        "launch": {
            **_launch_to_config(shared, redact),
            "allow_identical": launch.allow_identical,
        },
        "gates": {
            "mode": exp.gates.mode,
            "wait_quiet": exp.gates.wait_quiet,
            "locks": list(exp.gates.locks),
            "lock_timeout": exp.gates.lock_timeout_s,
            "allow_mixed_core_types": exp.gates.allow_mixed_core_types,
            "quiet": _drop_unset(
                {
                    "max_busy_cores": quiet.max_busy_cores,
                    "gpu_idle": quiet.gpu_idle,
                    "samples": quiet.samples,
                    "interval_s": quiet.interval_s,
                    "max_wait_s": quiet.max_wait_s,
                }
            ),
            "census": {"max_busy_cores": exp.gates.census.max_busy_cores},
            "discard": {"max_busy_cores": exp.gates.discard.max_busy_cores},
        },
        "rule": {"name": exp.rule.name, "fail_on": list(exp.rule.fail_on)},
        "cases": {
            "primary": list(exp.cases.primary),
            "groups": {k: list(v) for k, v in exp.cases.groups.items()},
        },
        "energy": {
            "enabled": exp.energy.enabled,
            "interval_s": exp.energy.interval_s,
            "min_samples": exp.energy.min_samples,
        },
        "report": {"include_image_refs": exp.report.include_image_refs, "html": exp.report.html},
        "controls": _drop_unset(
            {
                "positive": exp.controls.positive,
                "positive_tolerance": exp.controls.positive_tolerance,
                "positive_via": exp.controls.positive_via,
            }
        ),
        "launch_cost": {
            "launches": exp.launch_cost.launches,
            "note_share": exp.launch_cost.note_share,
        },
        "explain": {
            "mode": exp.explain.mode,
            "sample_hz": exp.explain.sample_hz,
            "call_graph": exp.explain.call_graph,
            "top": exp.explain.top,
        },
        "plots": {"mode": exp.plots.mode, "max_round_charts": exp.plots.max_round_charts},
    }


# Every config key, as a dotted path. NAME stands for a name the user chooses.
CONFIG_KEYS: Final[tuple[str, ...]] = (
    "run.rounds",
    "run.rounds_exact",
    "run.quick",
    "run.budget",
    "run.warmups",
    "run.same_vs_same",
    "run.allow_underpowered",
    "run.out",
    "run.print_plan",
    "run.json",
    "run.no_plugins",
    "run.node_type",
    "run.vary_env_size",
    "workload.argv",
    "workload.driver",
    "workload.levels",
    "workload.level_duration",
    "workload.level_kind",
    "sides.NAME.image",
    "sides.NAME.args",
    "sides.NAME.env",
    "sides.NAME.entrypoint",
    "sides.NAME.cmd",
    "sides.NAME.python",
    "sides.NAME.venv",
    "sides.NAME.conda",
    "sides.NAME.file",
    "sides.NAME.format",
    "sides.NAME.kind",
    "sides.NAME.spec",
    "sides.NAME.baseline",
    "sides.NAME.serve.image",
    "sides.NAME.serve.args",
    "sides.NAME.serve.port",
    "sides.NAME.serve.ready.http",
    "sides.NAME.serve.ready.timeout",
    "sides.NAME.serve.env",
    "sides.NAME.serve.model",
    "sides.NAME.serve.model_name",
    "sides.NAME.serve.launcher",
    "sides.NAME.serve.command",
    "sides.NAME.serve.probe.path",
    "sides.NAME.serve.probe.body",
    "sides.NAME.serve.phases",
    *(f"sides.NAME.launch.{key}" for key, _name, _kind in _LAUNCH_KEYS),
    *(f"launch.{key}" for key, _name, _kind in _LAUNCH_KEYS),
    "launch.allow_identical",
    "gates.mode",
    "gates.wait_quiet",
    "gates.locks",
    "gates.lock_timeout",
    "gates.allow_mixed_core_types",
    "gates.quiet.max_busy_cores",
    "gates.quiet.gpu_idle",
    "gates.quiet.samples",
    "gates.quiet.interval_s",
    "gates.quiet.max_wait_s",
    "gates.census.max_busy_cores",
    "gates.discard.max_busy_cores",
    "rule.name",
    "rule.fail_on",
    "cases.primary",
    "cases.groups.NAME",
    "energy.enabled",
    "energy.interval_s",
    "energy.min_samples",
    "report.include_image_refs",
    "report.html",
    "controls.positive",
    "controls.positive_tolerance",
    "controls.positive_via",
    "launch_cost.launches",
    "launch_cost.note_share",
    "explain.mode",
    "explain.sample_hz",
    "explain.call_graph",
    "explain.top",
    "plots.mode",
    "plots.max_round_charts",
)

# The config keys whose value is a table of keys the user chooses. A dotted
# path may name one key inside such a table, as in ``launch.env.OMP_NUM_THREADS``.
CONFIG_TABLE_KEYS: Final[tuple[str, ...]] = (
    "sides.NAME.env",
    "sides.NAME.serve.env",
    "sides.NAME.serve.probe.body",
    "sides.NAME.serve.phases",
    "sides.NAME.launch.env",
    "launch.env",
)


# The config key each flag of the ``run`` command sets. A flag named here has
# exactly one key; the command line reads this table and holds no second one.
FLAG_KEYS: Final[Mapping[str, str]] = {
    "--driver": "workload.driver",
    "--case": "cases.primary",
    "--levels": "workload.levels",
    "--level-duration": "workload.level_duration",
    "--rounds": "run.rounds",
    "--rounds-exact": "run.rounds_exact",
    "--quick": "run.quick",
    "--budget": "run.budget",
    "--warmups": "run.warmups",
    "--same-vs-same": "run.same_vs_same",
    "--positive-control": "controls.positive",
    "--vary-env-size": "run.vary_env_size",
    "--allow-underpowered": "run.allow_underpowered",
    "--engine": "launch.engine",
    "--cpus": "launch.cpus",
    "--gpus": "launch.gpus",
    "--pull": "launch.pull",
    "--timeout": "launch.timeout",
    "--allow-identical": "launch.allow_identical",
    "--gates": "gates.mode",
    "--wait-quiet": "gates.wait_quiet",
    "--lock": "gates.locks",
    "--lock-timeout": "gates.lock_timeout",
    "--allow-mixed-core-types": "gates.allow_mixed_core_types",
    "--rule": "rule.name",
    "--fail-on": "rule.fail_on",
    "--explain": "explain.mode",
    "--plots": "plots.mode",
    "--out": "run.out",
    "--print-plan": "run.print_plan",
    "--json": "run.json",
    "--no-plugins": "run.no_plugins",
}
# The flags of the ``run`` command that set no single key: a side is a whole
# table, the baseline is a key of the side it names, the config file has no
# key and ``--set`` names its key itself. The workload after ``--`` is
# ``workload.argv``.
FLAGS_WITHOUT_KEY: Final[tuple[str, ...]] = ("--side", "--baseline", "--config", "--set")


def _match_key(
    pattern: Sequence[str], tokens: Sequence[str], table: bool
) -> tuple[str, ...] | None:
    if not pattern:
        if not tokens:
            return ()
        return (".".join(tokens),) if table else None
    if not tokens:
        return None
    head, rest = pattern[0], pattern[1:]
    if head != "NAME":
        if tokens[0] != head:
            return None
        found = _match_key(rest, tokens[1:], table)
        return None if found is None else (head, *found)
    for take in range(1, len(tokens) - len(rest) + 1):
        found = _match_key(rest, tokens[take:], table)
        if found is not None:
            return (".".join(tokens[:take]), *found)
    return None


def match_config_key(path: str) -> tuple[str, tuple[str, ...]]:
    """Match a dotted path, as written after ``--set``, against ``CONFIG_KEYS``.

    Returns the entry of ``CONFIG_KEYS`` the path names and the parts to walk
    in a config-shaped dict: ``sides.new.image`` gives
    ``("sides.NAME.image", ("sides", "new", "image"))``. A name the user chose
    may hold dots; it takes as few parts of the path as leave a known key. A
    path one part longer than an entry of ``CONFIG_TABLE_KEYS`` names one key
    inside that table: ``launch.env.OMP_NUM_THREADS`` gives
    ``("launch.env", ("launch", "env", "OMP_NUM_THREADS"))``. A path that
    names no config key is refused with ``E_CONFIG``.
    """
    tokens = path.split(".")
    best: tuple[str, tuple[str, ...]] | None = None
    if all(tokens):
        for key in CONFIG_KEYS:
            parts = _match_key(key.split("."), tokens, key in CONFIG_TABLE_KEYS)
            if parts is not None and (best is None or len(parts) > len(best[1])):
                best = (key, parts)
    if best is None:
        raise _config_error(f"unknown config key: {path}", unknown=[path])
    return best


# ---------------------------------------------------------------------------
# The command line of a run: what a capture keeps and what results may show
# ---------------------------------------------------------------------------

HIDDEN: Final = "<hidden>"
FLAG_SIDE: Final = "--side"
FLAG_SET: Final = "--set"
WORKLOAD_SEPARATOR: Final = "--"
# The kinds of side whose spec is an image reference.
IMAGE_REF_KINDS: Final[tuple[str, ...]] = (KIND_IMAGE, KIND_SERVE)
# The config tables that hold environment variables.
_ENV_TABLES: Final[tuple[str, ...]] = tuple(
    key for key in CONFIG_TABLE_KEYS if key.rpartition(".")[2] == "env"
)


def _flag_values(argv: Sequence[str]) -> Iterable[tuple[str | None, str, bool]]:
    """Walk a command line: yield ``(flag, text, joined)`` for every argument.

    ``flag`` is ``--side`` or ``--set`` for the value of one of them, given
    as the next argument or after ``=``, and ``None`` otherwise. ``joined``
    says the flag and its value are one argument. Everything after ``--`` is
    the workload and belongs to no flag.
    """
    flags = (FLAG_SIDE, FLAG_SET)
    pending: str | None = None
    workload = False
    for arg in argv:
        if workload:
            yield None, arg, False
        elif pending is not None:
            yield pending, arg, False
            pending = None
        elif arg == WORKLOAD_SEPARATOR:
            workload = True
            yield None, arg, False
        elif arg in flags:
            pending = arg
            yield None, arg, False
        else:
            flag = next((f for f in flags if arg.startswith(f + "=")), None)
            if flag is None:
                yield None, arg, False
            else:
                yield flag, arg[len(flag) + 1 :], True


def _redacted_set(text: str) -> str:
    """Redact the value of one ``KEY=VALUE`` when it sets a credential-like variable."""
    key, eq, value = text.partition("=")
    if not eq:
        return text
    try:
        found, parts = match_config_key(key)
    except Refusal:
        return text
    if found not in _ENV_TABLES:
        return text
    inside = len(parts) > len(found.split("."))
    secret = looks_like_credential(parts[-1]) if inside else looks_like_credential(value)
    return f"{key}={REDACTED}" if secret else text


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Return a command line as a capture keeps it.

    It is kept as typed, except that a ``--set`` which sets a credential-like
    environment variable, such as ``--set launch.env.API_TOKEN=...``, has its
    value replaced by ``"<redacted>"``, as the recorded config does. A
    ``--set`` of a whole environment table whose value names such a variable
    is replaced as a whole.
    """
    out: list[str] = []
    for flag, text, joined in _flag_values(argv):
        shown = _redacted_set(text) if flag == FLAG_SET else text
        out.append(f"{flag}={shown}" if joined else shown)
    return tuple(out)


def _last_part(text: str) -> str:
    """Cut an absolute path to its last part; leave every other text as it is.

    A relative path that climbs with ``..`` (``_climbs``) is cut the same way,
    as it may name a folder outside the run folder.
    """
    if not text.startswith(("/", "~")) and not _climbs(text):
        return text
    return text.rstrip("/").rpartition("/")[2] or text[:1]


# The start of a relative path that climbs with ``..``: folders of letters, digits, ``_``,
# ``.`` and ``-``, maybe none, then ``../``.
_CLIMBS = re.compile(r"(?:[\w.-]+/)*\.\./")


def _climbs(text: str) -> bool:
    """Say whether ``text`` is a relative path that climbs out of its folder with ``..``.

    It starts as ``_CLIMBS`` says, and its ``..`` parts, read in turn, come
    to more than the folders before them: ``../a/notes.txt``,
    ``./../a/notes.txt`` and ``data/../../a/notes.txt`` climb out, while
    ``a/../b`` and ``s/../X/``, a text of ``sed``, stay inside.
    """
    if _CLIMBS.match(text) is None:
        return False
    depth = 0
    for part in text.split("/"):
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        elif part not in ("", "."):
            depth += 1
    return False


def _local_address_path(path: str, before: str) -> str:
    """Cut the path that follows ``scheme://`` with no host between, as ``before`` ends.

    A ``file://`` address loses the path's folders with the ``/`` before them
    (``file:///a/m.gguf`` shows ``file://m.gguf``). Any other address keeps
    its empty host and the path its last part: ``sqlite:////a/db.sqlite``
    shows ``sqlite:///db.sqlite``. A path of ``/`` alone is left as it is.
    """
    if before[-7:].lower() == "file://":
        return _last_part(path)
    if not path.strip("/"):
        return path
    return "/" + _last_part(path)


# A character a path may hold in a free text, and one that is no ``/`` either.
_PATH_CHAR = r"""[^\s'"`,;()\[\]{}<>]"""
_NO_SLASH = r"""[^\s/'"`,;()\[\]{}<>]"""


def _run_on(path_char: str, no_slash: str) -> str:
    """Return how a path whose characters are ``path_char`` runs on over blanks.

    A folder whose name holds spaces is cut whole: the path runs on over the
    next word when it holds a ``/`` and starts no option and no path of its
    own, absolute or climbing with ``..`` (``/a/Zq Files/x``), or over words
    that start with a letter, a digit or ``_`` up to one such word that holds
    a ``/`` (``/a/Zq One Two/x``). A word that starts with any other
    character, as ``&&`` or ``./run`` does, ends the path before the words
    without a ``/``, and so does a word that holds ``://``, which writes an
    address of its own (``unix:///a/s.sock?db=0 y unix:///b/s.sock``).
    ``no_slash`` is ``path_char`` without ``/``.
    """
    return (
        r"""(?:[ \t]+(?![-/~]|(?:\./)*\.\./|\S*://)"""
        + no_slash
        + r"""*/"""
        + path_char
        + r"""*|(?:[ \t]+(?=\w)"""
        + no_slash
        + r"""+)+[ \t]+(?=\w)(?!\S*://)"""
        + no_slash
        + r"""*/"""
        + path_char
        + r"""*)*"""
    )


# How a path in a free text runs on over blanks (``_run_on``).
_RUN_ON = _run_on(_PATH_CHAR, _NO_SLASH)
# What follows the ``../`` of a path that climbs: a part that is no ``..``. A path of ``..``
# parts alone names no folder and is left as it is (``cd ../..``).
_CLIMB_END = r"""(?!\.\.(?:/|(?!""" + _PATH_CHAR + r""")))(?=""" + _PATH_CHAR + r""")"""
# The start of a relative path that climbs with ``..``: folders, maybe none, then ``../`` and
# a part that is no ``..`` (``../../a/notes.txt``, ``./../a/notes.txt``,
# ``data/../../a/notes.txt``). The folders hold letters, digits, ``_``, ``.`` and ``-``, none
# of which may stand before the path's start, so each run of them is read once; the first
# does not start with ``-``, so an option at the start of a word is no folder.
_CLIMB = r"""(?!-)(?:[\w.-]+/)*\.\./""" + _CLIMB_END
# The start of a path glued to an option that climbs with ``..``: it starts with ``.``, which
# no option's name holds, so the option ends where it starts (``-I../a/include``,
# ``-I./../a/include``, ``-I./data/../../a/include``).
_GLUED_CLIMB = r"""(?=\.)(?:[\w.-]+/)*\.\./""" + _CLIMB_END
# An absolute path: one that starts at ``/``, at ``//`` that does not follow a
# ``:`` as in an address, at ``~/`` or ``~user/`` (``~user@domain/`` too), or
# right after ``scheme://``, where the host of an address is empty and what
# follows is a local path (``file:///a/m.gguf``, ``sqlite:////a/db.sqlite``).
# A ``/`` after ``++`` goes on a relative path, as in ``proj/c++/bench.cc``. A
# relative path that climbs out of its folder (``_CLIMB``) is found as one too,
# where an absolute path may start. It runs on over blanks as ``_RUN_ON`` says.
_ABSOLUTE_PATH = re.compile(
    r"""(?:(?<![\w/.~-])(?:~[\w.@-]*/|(?<!\+\+)/(?!/)|""" + _CLIMB + r""")|(?<=://)/"""
    r"""|(?<![\w/.~:-])//(?=[^\s/'"`,;()\[\]{}<>]))""" + _PATH_CHAR + r"""*""" + _RUN_ON
)


# An option at the start of a word with an absolute path glued to it, as
# ``-I/a/include`` or ``-L~user/lib``. The option's name starts with a letter,
# or is a number when the path holds two folders or more and the first starts
# with a letter (``-1/a/b``); the path's first folder does not start with
# ``-``. So ``-1/2``, ``-1/2/3`` and ``-v/--verbose`` are no such option. A
# relative path that climbs out of its folder (``-I../../a/include``) is glued
# to its option the same way. The path runs on over blanks as in
# ``_ABSOLUTE_PATH``. A name of more than one letter is glued to a path only
# when the path holds two parts or more or starts at ``~`` (``_glued_path_cut``).
_GLUED_PATH = re.compile(
    r"""(?<![^\s'"=])(-{1,2}(?:[A-Za-z][A-Za-z0-9_-]*?|[0-9]+(?=/[A-Za-z_.][^\s/]*/)))"""
    r"""((?:/(?![/-])|~[\w.@-]*/|"""
    + _GLUED_CLIMB
    + r""")"""
    + _PATH_CHAR
    + r"""*"""
    + _RUN_ON
    + r""")"""
)
# What may stand between the quote that opens a quoted path and the path: names given a
# value (``--in=``, ``DATA=``), then a drive letter (``C:``) or an option the path is glued
# to (``-I``), as in ``'--in=C:/a b/x'`` and ``'-I/a b/include'``.
_QUOTED_PATH_LEAD = re.compile(
    r"(?:-{1,2}[A-Za-z0-9][A-Za-z0-9_.-]*=|[A-Za-z_][A-Za-z0-9_.-]*=)*"
    r"(?:[A-Za-z]:|-{1,2}[A-Za-z0-9][A-Za-z0-9_-]*)?"
)
# The characters of such a lead, read back from the path, and how far back they are read.
_QUOTED_PATH_LEAD_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-=:"
)
_QUOTED_PATH_REACH: Final = 256
# The rest of a path in double quotes in a text that is no shell text, up to the double quote
# that may close it, a line end or the end of the text: a backslash keeps the character after
# it in the path.
_QUOTED_PATH_REST = re.compile(r'(?:[^"\\\n]|\\[^\n])*')


def _quote_spans(text: str) -> dict[int, int]:
    """Return where each quoted part of a shell text opens and closes.

    The keys are the places of the quotes that open a part, as a shell
    reads them (``_QUOTED_PART``); each value is the place of its closing
    quote, or the end of the text when the part is not closed.
    """
    spans: dict[int, int] = {}
    for found in _QUOTED_PART.finditer(text):
        inside = found.group(1) if found.group(1) is not None else found.group(2)
        if inside is None:
            continue
        closed = len(found.group(0)) == len(inside) + 2
        spans[found.start()] = found.end() - 1 if closed else found.end()
    return spans


def _quoted_path_end(
    text: str, start: int, quotes: dict[int, int] | None, read: list[int]
) -> int | None:
    """Return where the closing quote of a quoted path that starts at ``start`` stands, or ``None``.

    A quoted path is one that a quote opens, maybe after names given a value
    and a drive letter (``_QUOTED_PATH_LEAD``): ``'/a b/x'``, ``--in="/a b/x"``,
    ``'--in=C:/a b/x'``. In a shell text (``quotes``, from ``_quote_spans``)
    the quote must open a part, and the path runs to the quote that closes
    it. In any other text the path runs to the next quote of the same kind
    on the same line, and when there is none it is no quoted path; a double
    quote with a backslash before it closes none (``_double_quote_close``,
    which keeps what it read of the text in ``read``).
    """
    lead = start
    while (
        lead > 0 and start - lead < _QUOTED_PATH_REACH and text[lead - 1] in _QUOTED_PATH_LEAD_CHARS
    ):
        lead -= 1
    if lead == 0 or text[lead - 1] not in "'\"":
        return None
    if _QUOTED_PATH_LEAD.fullmatch(text, lead, start) is None:
        return None
    if quotes is not None:
        return quotes.get(lead - 1)
    quote = text[lead - 1]
    if quote == "'":
        close = text.find("'", start)
        line = text.find("\n", start, close if close != -1 else len(text))
        return close if close != -1 and line == -1 else None
    return _double_quote_close(text, start, read)


def _double_quote_close(text: str, start: int, read: list[int]) -> int | None:
    """Return where the double quote that closes a path read from ``start`` stands, or ``None``.

    The path runs over the rest of its line (``_QUOTED_PATH_REST``) to a
    double quote that no backslash escapes. ``read`` holds the last such
    read of the text as ``[from, to, close]``, ``close`` being -1 when it
    found no closing quote. A path that starts inside that span ends where
    that read ended, since the character before a path is never a
    backslash, so the reading of many paths on one line, each after a quote
    that opens no part, takes time in proportion to the line.
    """
    if read[0] < start < read[1]:
        return read[2] if read[2] >= 0 else None
    rest = _QUOTED_PATH_REST.match(text, start)
    to = start if rest is None else rest.end()
    close = to if to < len(text) and text[to] == '"' else -1
    read[:] = [start, to, close]
    return close if close >= 0 else None


def _paths_cut(
    pattern: re.Pattern[str],
    text: str,
    shown: Callable[[re.Match[str], str], str | tuple[str, int] | None],
    quotes: dict[int, int] | None,
    group: int = 0,
) -> str:
    """Return ``text`` with each path ``pattern`` finds replaced as ``shown`` says.

    ``shown`` gets the match and the path, which ends where the match ends
    or, for a quoted path (``_quoted_path_end``), at its closing quote; it
    returns what stands in the place of the match and the path, or ``None``
    to leave the match as it is. It may also return what stands in the place
    of the text up to an index past the path's start, with that index: the
    search for the next path then starts there. ``group`` is the group of
    the match the path is.
    """
    out: list[str] = []
    end = 0
    at = 0
    read = [0, 0, -1]
    while (found := pattern.search(text, at)) is not None:
        start, stop = found.start(group), found.end()
        close = _quoted_path_end(text, start, quotes, read)
        if close is not None and close >= stop:
            stop = close
        replaced = shown(found, text[start:stop])
        if replaced is None:
            at = found.end()
            continue
        if isinstance(replaced, tuple):
            replaced, stop = replaced
        out.append(text[end : found.start()])
        out.append(replaced)
        end = at = stop
    if not out:
        return text
    out.append(text[end:])
    return "".join(out)


# The user part of an address, as ``madeup:secret@`` in ``scheme://madeup:secret@host/``. It
# runs to the last ``@`` before the first ``/`` or white space, so a password that holds an ``@``
# or a quote is hidden whole. An address glued to an option (``-xhttp://madeup:secret@host``)
# is read with the option's letters in its scheme, which hides its user part all the same.
_ADDRESS_USER = re.compile(r"""([A-Za-z][A-Za-z0-9+.-]*://)[^\s/]*@""")
# The same user part read in two: the user name up to the first ``:``, and the password
# after it, when there is one.
_ADDRESS_USER_PASSWORD = re.compile(r"""([A-Za-z][A-Za-z0-9+.-]*://)([^\s/:@]*)(:[^\s/]*)?@""")
# An address, from its scheme and ``://``.
_ADDRESS_START = re.compile(r"""[A-Za-z][A-Za-z0-9+.-]*://""")
# The first word of a value and the word after it, when there is one: ``Bearer VALUE``.
_CREDENTIAL_WORDS = re.compile(r"""\s*(\S+)(\s+(\S+))?""")
# The characters of a scheme, and the letters it starts with, as ``[A-Za-z][A-Za-z0-9+.-]*``
# reads them in the patterns of an address.
_SCHEME_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+.-"
)
_SCHEME_LETTERS: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _scheme_start(text: str, at: int, lowest: int) -> int | None:
    """Return where a scheme that ends at the ``://`` at ``at`` starts, not before ``lowest``.

    It is the first letter of the run of scheme characters right before ``at``.
    A scheme holds no ``:``, so every start in that run reads the same text
    after it, and a pattern that starts with a scheme matches from this one
    start if it matches from any of them.
    """
    start = at
    while start > lowest and text[start - 1] in _SCHEME_CHARS:
        start -= 1
    while start < at and text[start] not in _SCHEME_LETTERS:
        start += 1
    return start if start < at else None


def _address_matches(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """Yield the matches of ``pattern.finditer(text)``, reading the text once.

    ``pattern`` starts with a scheme and ``://``. A search for it would try
    every start in a long run of letters and read the run again from each;
    this tries only the start of a scheme before each ``://``.
    """
    end = 0
    at = text.find("://")
    while at != -1:
        start = _scheme_start(text, at, end)
        found = None if start is None else pattern.match(text, start)
        if found is None:
            at = text.find("://", at + 1)
            continue
        yield found
        end = found.end()
        at = text.find("://", end)


def _address_sub(pattern: re.Pattern[str], shown: Callable[[re.Match[str]], str], text: str) -> str:
    """Return ``pattern.sub(shown, text)`` for a pattern that starts with a scheme and ``://``."""
    out: list[str] = []
    end = 0
    for found in _address_matches(pattern, text):
        out.append(text[end : found.start()])
        out.append(shown(found))
        end = found.end()
    if not out:
        return text
    out.append(text[end:])
    return "".join(out)


# What stands between ``file://`` and the path of a file address: a host (a name of letters of
# any script, digits, ``.``, ``-``, ``_``, ``~`` and ``%``, ``<hidden>``, or one in brackets),
# maybe after the hidden user part and before a port, and the further ``/`` of a share
# (``file:////share/x``). A file address names a path on a machine, so that part goes with the
# folders of the path: ``file://localhost/a/m.gguf`` shows ``file://m.gguf``, as
# ``file:///a/m.gguf`` does. A character no host holds ends the address, so a file name
# already cut and what follows it (``file://a.bin,b/c``, ``[file://x.bin]/8``) stay as they are.
_FILE_AUTHORITY = re.compile(
    r"""((?i:file)://)(?:"""
    + re.escape(HIDDEN)
    + r"""@)?(?:"""
    + re.escape(HIDDEN)
    + r"""|\[[0-9A-Za-z:.%_~-]*\]|[\w.%~-]*)(?::[0-9]*)?/+"""
)
# A socket address whose path is written with no ``/`` after ``://``
# (``unix://a/b/s.sock``, ``redis+unix://a/s.sock``): it names a local path,
# and is read as ``unix:///a/b/s.sock`` is. One whose path is percent-encoded
# where a host stands (``http+unix://%2Fa%2Fs.sock/v1``) is left as it is.
_SOCKET_NO_ROOT = re.compile(r"""((?i:(?:[a-z][a-z0-9.-]*\+)?unix)://)(?=[^\s/%<'"`])""")
# A path written with percent escapes, as an address carries one in a query value or where a
# host stands (``?host=%2Fa%2Fb%2Frun``, ``postgresql://%2Fa%2Frun/db``): ``%2F`` that no
# letter, digit or escape comes right before, then the characters such a path holds.
_PERCENT_PATH = re.compile(r"""(?<![\w%.~-])%2[Ff](?:[\w.~+:@!$-]|%[0-9A-Fa-f]{2})*""")
_PERCENT_SLASH = re.compile(r"%2[Ff]")
# An address: its scheme, a user part, a host as ``_AUTHORITY_END`` reads one (or none) and a
# port, then from a ``/``, ``?`` or ``#`` to the first character no address holds: white
# space, a quote, a comma, a semicolon or a bracket. A character no host holds right after
# the host ends the address (``http://h+/a/b``), so a path after it is no part of it.
_ADDRESS_SPAN = re.compile(
    r"""[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/@]*@)?(?:"""
    + re.escape(HIDDEN)
    + r"""|\[[0-9A-Za-z:.%_~-]*\]|[0-9A-Za-z.%_~-]*)(?::[0-9]*)?"""
    r"""(?:[/?#][^\s'"`,;()\[\]{}]*)?"""
)
# Where the local path of an address with no host ends, and where a path in the rest of an
# address ends: at its query or its fragment, and a path in a query also at the next parameter.
_LOCAL_PATH_END = re.compile(r"[?#]")
_ADDRESS_PART_END = re.compile(r"[?&#]")
# A character a path inside an address may hold, and one that is no ``/`` either: one a path
# in a free text holds that ends no query parameter.
_PART_CHAR = r"""[^\s'"`,;()\[\]{}<>?&#]"""
_PART_NO_SLASH = r"""[^\s/'"`,;()\[\]{}<>?&#]"""
# An absolute path inside an address, after its host: it starts as one does in a free text
# (``_ABSOLUTE_PATH``), runs on over blanks as one does there (``_run_on``), so a folder whose
# name holds spaces is cut whole (``?host=/a/Zq Files/run``), and ends at the end of its query
# parameter (``?next=/a/b&x=1``).
_ADDRESS_INNER_PATH = re.compile(
    r"""(?:(?<![\w/.~-])(?:~[\w.@-]*/|(?<!\+\+)/(?!/))"""
    r"""|(?<![\w/.~:-])//(?=[^\s/'"`,;()\[\]{}<>]))"""
    + _PART_CHAR
    + r"""*"""
    + _run_on(_PART_CHAR, _PART_NO_SLASH)
)
# The same inside an address in a case id, where a path may start with three ``/`` or more
# too, as one may after ``=`` in a case id (``_CASE_PATH``): ``postgresql:///db?host=///a/run``
# shows ``postgresql:///db?host=/run``. A path may also start there as a relative path that
# climbs with ``..`` does anywhere in a case id (``_CLIMB``), so one that climbs out of its
# folder is cut wherever it stands in the address: ``postgresql:///db?c=../../a/ca.pem``
# shows ``postgresql:///db?c=ca.pem``. ``_address_rest`` keeps as typed one that stays
# inside its folder (``?c=data/../ca.pem``).
_CASE_INNER_PATH = re.compile(
    r"""(?:(?<![\w/.~-])(?:~[\w.@-]*/|(?<!\+\+)/(?!/)|""" + _CLIMB + r""")"""
    r"""|(?<![\w/.~:-])//+(?=[^\s/'"`,;()\[\]{}<>]))"""
    + _PART_CHAR
    + r"""*"""
    + _run_on(_PART_CHAR, _PART_NO_SLASH)
)


def _glued_path_cut(found: re.Match[str], path: str) -> str | None:
    """Cut a path glued to an option (``_GLUED_PATH``) to its last part, after the option.

    An option whose name is more than one letter is glued to the path only
    when the path holds two parts or more, its blanks included, as one that
    starts at ``~`` always does (``~/x``, ``~user/x``):
    ``-isystem/a/include`` shows ``-isysteminclude``, while ``-Ia/b``, which
    may be ``-I`` and the relative path ``a/b``, and ``-isystem/x``, which
    names no folder, are left as they are.
    """
    option = found.group(1)
    name = option.lstrip("-")
    if len(name) > 1 and name[0].isalpha() and "/" not in path[1:]:
        return None
    return option + _last_part(path)


def case_percent_paths(case: str) -> list[str]:
    """Return the paths written with percent escapes in a case id, as written and in order.

    Such a path is ``%2F`` that no letter, digit or escape comes right
    before, then the characters such a path holds (``?host=%2Fa%2Fb%2Frun``
    gives ``%2Fa%2Fb%2Frun``); ``public_case`` cuts each to ``%2F`` and its
    last part.
    """
    return _PERCENT_PATH.findall(case)


def _percent_path_cut(found: re.Match[str]) -> str:
    """Cut a path written with percent escapes to ``%2F`` and its last part.

    ``%2Fa%2Fb%2Frun`` shows ``%2Frun``.
    """
    run = found.group(0)
    parts = [part for part in _PERCENT_SLASH.split(run) if part]
    return run[:3] + parts[-1] if parts else run


def _address_part(path: str) -> str:
    """Cut an absolute path inside an address to ``/`` and its last part.

    An address with no host shows its path the same way
    (``_local_address_path``), so the ``/`` that tells a path from a word
    stays: ``?next=/a/b`` shows ``?next=/b``. A path under ``~``, and one that
    climbs out of its folder (``?next=../a/b``), shows its last part alone.
    """
    if path.startswith("~") or _climbs(path):
        return _last_part(path)
    return _local_address_path(path, "")


def _last_part_start(path: str) -> int:
    """Return where the part of ``path`` that ``_last_part`` keeps starts in it.

    It is right after the last ``/`` before the end ``/`` of an absolute
    path or one that climbs with ``..``; ``0`` for any other text, which is
    kept whole, and for a path of ``/`` alone.
    """
    if not path.startswith(("/", "~")) and not _climbs(path):
        return 0
    return path.rstrip("/").rfind("/") + 1


# White space, which ends the rest of an address outside a path in it.
_ADDRESS_REST_END = re.compile(r"\s")


def _address_rest(
    text: str,
    begin: int,
    end: int,
    dropped: list[tuple[int, int]],
    inner: re.Pattern[str] = _ADDRESS_INNER_PATH,
    in_case: bool = False,
) -> tuple[str, int]:
    """Return the rest of an address from ``begin`` with each path in it cut, and where it ends.

    The rest ends at the first white space before ``end`` that no path in
    it runs over; a path that runs on over blanks (``?host=/a/Zq Files/run``)
    is part of it. Each path is cut as ``_address_part`` says, and the
    stretch the cut leaves out, from the path's start to its last part, is
    added to ``dropped``. What follows the rest is no part of the address:
    a path runs on over it only as it runs on over any word, so it is read
    again as a free text. ``inner`` finds the paths: ``_ADDRESS_INNER_PATH``
    in a free text, ``_CASE_INNER_PATH`` in a case id, which finds a relative
    path with ``..`` in it too: it is cut when it climbs out of its folder
    (``?c=../a/ca.pem`` shows ``?c=ca.pem``) and kept as typed when it stays
    inside it (``?c=data/../ca.pem``). In a case id
    (``in_case``) the rest also ends where the local path of an address in
    it starts, so that path is read again as the local path of an address
    with no host: ``postgresql:///db?c=file:///a/ca.pem`` shows
    ``postgresql:///db?c=file://ca.pem``, as it does with a host before it.
    """
    if in_case and (local := text.find(":///", begin, end)) != -1:
        end = local + 3
    out: list[str] = []
    at = begin
    stop = end
    for found in inner.finditer(text, begin, end):
        blank = _ADDRESS_REST_END.search(text, at, found.start())
        if blank is not None:
            stop = blank.start()
            break
        path = found.group(0)
        if not path.startswith(("/", "~")) and not _climbs(path):
            continue
        out.append(text[at : found.start()])
        out.append(_address_part(path))
        dropped.append((found.start(), found.start() + _last_part_start(path)))
        at = found.end()
    else:
        blank = _ADDRESS_REST_END.search(text, at, end)
        if blank is not None:
            stop = blank.start()
    out.append(text[at:stop])
    return "".join(out), stop


def _part_end(pattern: re.Pattern[str], text: str, start: int, stop: int) -> int:
    found = pattern.search(text, start, stop)
    return stop if found is None else found.start()


def _path_cutter(
    text: str,
    dropped: list[tuple[int, int]] | None = None,
    inner: re.Pattern[str] = _ADDRESS_INNER_PATH,
    in_case: bool = False,
) -> Callable[[re.Match[str], str], str | tuple[str, int] | None]:
    """Return how ``public_text`` and ``public_case`` show each absolute path in ``text``.

    The callable gets a match whose path starts where the match starts, and
    the path (``_paths_cut``). A path right after ``scheme://`` is the local
    path of an address with no host: it ends at the query or the fragment,
    and is cut as ``_local_address_path`` says (``sqlite:////a/db.sqlite?mode=ro``
    shows ``sqlite:///db.sqlite?mode=ro``). The path of an address right
    after its host is kept (``https://<hidden>/api``,
    ``http://[fd00::1]/v1``, ``http://host:/v1``). Any other path inside an
    address, as in a query value or after ``=`` in the address's path, is cut
    as ``_address_part`` says and ends at the end of its query parameter. A
    path after a ``>`` that closes the arguments of a template is kept, and
    any other path shows its last part. The rest of an address ends as
    ``_address_rest`` says, and the callable then gives what stands in the
    place of the path up to there with where that is, so the words after
    it are read again as a free text. Each stretch of ``text`` a cut leaves
    out, from a path's start to its last part, is added to ``dropped``.
    ``inner`` finds the paths in the rest of an address (``_address_rest``),
    which ends as ``in_case`` says there. In a case id (``in_case``) a path
    may start right after ``?``, ``&`` or ``#`` (``_CASE_PATH``): inside an
    address it is cut as one after ``=`` there (``?/a/ca.pem`` shows
    ``?/ca.pem``). Outside one such a mark joins the parts of a name
    (``BM_x#/8/cpu_time``): its ``/`` is kept, and the search for a path
    goes on right after it, so a path later in the id is cut as it is
    without the mark (``BM_x&/b tail k=/a/x.bin`` shows ``BM_x&/b tail k=x.bin``).
    """
    spans = [found.span() for found in _address_matches(_ADDRESS_SPAN, text)]
    starts = [one for one, _two in spans]
    left: list[tuple[int, int]] = [] if dropped is None else dropped

    def inside(at: int) -> bool:
        k = bisect.bisect_right(starts, at) - 1
        return k >= 0 and at < spans[k][1]

    def kept(start: int, end: int) -> None:
        left.append((start, start + _last_part_start(text[start:end])))

    def cut(found: re.Match[str], path: str) -> str | tuple[str, int] | None:
        start = found.start()
        stop = start + len(path)
        if text[max(0, start - 3) : start] == "://":
            end = _part_end(_LOCAL_PATH_END, text, start, stop)
            local = _local_address_path(text[start:end], text[max(0, start - 7) : start])
            kept(start, end)
            rest, last = _address_rest(text, end, stop, left, inner, in_case)
            return local + rest, last
        if start and text[start - 1] == ">" and _template_open(text, start - 1):
            return None
        if _AUTHORITY_END.search(text, max(0, start - _AUTHORITY_REACH), start):
            rest, last = _address_rest(text, start + 1, stop, left, inner, in_case)
            return text[start] + rest, last
        if inside(start):
            end = _part_end(_ADDRESS_PART_END, text, start, stop)
            kept(start, end)
            rest, last = _address_rest(text, end, stop, left, inner, in_case)
            return _address_part(text[start:end]) + rest, last
        if in_case and text[start - 1 : start] in ("?", "&", "#"):
            return text[start], start + 1
        kept(start, stop)
        return _last_part(path)

    return cut


def public_text(text: str) -> str:
    """Return a free text as a results document may show it.

    Every absolute path in it is cut to its last part, also one under
    ``~user/``, one in a ``file://`` address with whatever stands before its
    path (``file://localhost/a/m.gguf`` shows ``file://m.gguf``), one whose
    folder names hold a space and one glued to an option at the start of a
    word (``-I/a/include`` shows ``-Iinclude``). So is a relative path
    that climbs out of its folder with ``..`` (``_climbs``):
    ``../../a/in.csv`` shows ``in.csv``. The user part of an
    address, a user name and maybe a password before ``@``
    (``scheme://madeup:secret@host``), is hidden.
    The rest of an address such as ``https://...`` and a relative path that
    stays inside its folder (``a/../b``) are left as they are: the path of an
    address stays whole also after a host in brackets, a hidden host or an
    empty port (``http://[fd00::1]/v1``,
    ``https://<hidden>/api``, ``http://host:/v1``). So is the ``/`` after a
    ``>`` that closes the arguments of a template, as in the names
    ``BM_Vec<int>/8`` and ``BM_Seq<Queue, int>/8``; after any other ``>``,
    as in ``2>/dev/null`` or ``<in.txt>/a/out``, a path is cut. Nothing else
    can be told from the text alone: whoever writes a message that reaches a
    results document names no host, no user, no image reference and no value
    of the environment in it.
    """
    return _public_text(text, shell=False)


def _public_text(text: str, *, shell: bool) -> str:
    """Return a text as ``public_text`` shows it; with ``shell`` the text is a shell text.

    A path that a quote opens runs to the quote that closes it
    (``_quoted_path_end``): in a shell text to the quote that closes the
    quoted part as a shell reads it, in any other text to the next quote of
    the same kind on its line.
    """
    text = _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", text)
    text = _FILE_AUTHORITY.sub(lambda found: f"{found.group(1)}/", text)
    text = _address_sub(_SOCKET_NO_ROOT, lambda found: f"{found.group(1)}/", text)
    text = _PERCENT_PATH.sub(_percent_path_cut, text)
    text = _paths_cut(
        _GLUED_PATH, text, _glued_path_cut, _quote_spans(text) if shell else None, group=2
    )
    return _paths_cut(
        _ABSOLUTE_PATH, text, _path_cutter(text), _quote_spans(text) if shell else None
    )


# The start of an absolute path at the start of a word: ``/`` or ``~``, maybe after a drive
# letter and its colon (``C:/``).
_WORD_PATH = re.compile(r"[A-Za-z]:(?=/)|(?=[/~])")


def _path_to_its_end(word: str) -> str | None:
    """Return a word that holds a blank and starts as an absolute path, cut as one path.

    The word, or the value of an ordinary name at its start
    (``_ordinary_value_start``: ``--in=``, ``DATA=``), starts with ``/``,
    with ``~`` or with a drive letter and ``/``. All of it to its end is one
    path, whatever blanks and marks it holds, as a program gets it, and shows
    its last part with the name and the drive letter before it:
    ``/a/Zq Files/x`` shows ``x`` and ``--in=C:/a/Zq (x86)/x`` shows
    ``--in=C:x``. A relative path that climbs out of its folder
    (``_climbs``) is one path the same way: ``../../a/Zq Files/x`` shows
    ``x``. A word with no blank, or one that starts as no path, gives
    ``None`` and is left to ``public_text``.
    """
    if not _SPACE.search(word):
        return None
    at = _ordinary_value_start(word) or 0
    found = _WORD_PATH.match(word, at)
    if found is None:
        return word[:at] + _last_part(word[at:]) if _climbs(word[at:]) else None
    return word[: found.end()] + _last_part(word[found.end() :])


def public_path(path: str) -> str:
    """Return a path as a results document may show it.

    A path that starts as an absolute one (``/``, ``~`` or a drive letter and
    ``/``), or a relative one that climbs out of its folder with ``..``
    (``_climbs``), is one path to its end, whatever blanks it holds, and
    shows its last part: ``/opt/Zq Tools (x86)/made-up-tool`` and
    ``../../Zq Tools/made-up-tool`` show ``made-up-tool``.
    Any other text is shown as ``public_text`` shows it.
    """
    whole = _path_to_its_end(path)
    return public_text(path) if whole is None else whole


# The start of an address up to its path, at the end of a text: ``scheme://``, the user part, if
# any, a host (a name of letters, digits, ``.``, ``-``, ``_``, ``~`` and ``%``, ``<hidden>``, or
# one in brackets) and a port, maybe empty. The ``/`` that follows starts the address's path,
# not an absolute path: ``https://<hidden>/api``, ``http://[fd00::1]/v1`` and
# ``http://host:/v1`` keep it. Any other character ends the address, so the path after
# ``http://host,`` or ``http://host;`` is an absolute path of its own and is cut.
_AUTHORITY_END = re.compile(
    r"""[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/]*@)?(?:"""
    + re.escape(HIDDEN)
    + r"""|\[[0-9A-Za-z:.%_~-]*\]|[0-9A-Za-z.%_~-]+)(?::[0-9]*)?$"""
)
# How far before a path ``_AUTHORITY_END`` looks: the start of an address that reaches further
# back is not read as one, and its path is cut.
_AUTHORITY_REACH = 1024


# The open arguments of a template at the end of a text: a ``<`` right after a
# name, then type names, ``::``, ``*``, ``&``, commas and one level of nested
# arguments (``BM_Seq<Queue, std::vector<int>``). A ``<`` after a space or one
# followed by a file name (``<in.txt``) opens a redirection, not a template.
_TEMPLATE_OPEN = re.compile(r"\w<(?:[\w:*&]|, ?|<[\w:*&, ]*>)*$")


def _template_open(text: str, end: int) -> bool:
    """Say whether ``_TEMPLATE_OPEN`` finds open arguments at the end of ``text[:end]``.

    The arguments hold no ``/``, so the search starts after the last ``/``
    before ``end`` and reads each part of a path once.
    """
    return _TEMPLATE_OPEN.search(text, text.rfind("/", 0, end) + 1, end) is not None


# An absolute path inside a case id. A name uses ``/`` to join its parts
# (``BM_Vec<int>/8/cpu_time``), so a path starts only where a value starts: at
# the start of the id, after white space or after one of ``= : , ; [ ( { ' " @``
# (``test_read[/a/data.csv]``, ``File=/a/data.bin``) or of ``? & #`` inside an
# address (``_path_cutter`` keeps a path after those outside one), there also at
# ``~/`` or ``~user/``, right after ``scheme://`` as in ``_ABSOLUTE_PATH``, or after the
# ``/`` that ends one part of a name when two more parts follow, with one ``/``
# or more (``BM_Read//a/data.bin``, ``BM_Read///a/data.bin``). At the start of
# the id or after white space a path may start with two ``/`` or more, as the
# shown command reads an argument that starts so (``run //a/data.bin``), and
# after one of ``= , ; [ ( { ' " @`` with three or more
# (``test_read[///a/data.csv]``). Two ``/`` after one of those start the path at
# the second (``test_read[//a/data.csv]`` shows ``test_read[/data.csv]``), and
# ``:`` is not one of those, so the ``/`` after it start an address
# (``k:///a/data.csv``). It runs on over blanks as in ``_ABSOLUTE_PATH``.
_CASE_PATH = re.compile(
    r"""(?:(?:^|(?<=[\s=:,;\[({'"@?&#]))(?:~[\w.@-]*/|/(?![/-])|""" + _CLIMB + r""")|(?<=://)/"""
    r"""|(?:(?:^|(?<=\s))//+|(?<=[=,;\[({'"@])///+)(?=[^\s/'"`,;()\[\]{}<>-])"""
    r"""|(?<=[^\s/:]/)/+(?![/-])(?=""" + _PATH_CHAR + r"""+/))""" + _PATH_CHAR + r"""*""" + _RUN_ON
)


# A part of a case id that may hold a value of its own: a run of characters other than white
# space, the brackets, ``,``, ``;`` and ``/``, which join the parts and the values of a name
# (``test_db[PGPASSWORD=V]``, ``bench/token=V/latency``, ``bench[a=1,api_key=V]``).
_CASE_PART = re.compile(r"""[^\s\[\](){},;/]+""")
# A password before a host, written without a scheme, as one part of a case id:
# ``bob:VALUE@db.example`` and ``bob:VALUE@db.example:5432``. The user is a name of letters,
# digits, ``_``, ``.``, ``+`` and ``-``, the password does not start with ``:``, so
# ``pkg::name@v2`` is no such form, and the host is a name of letters, digits, ``.`` and
# ``-`` that starts with a letter or a digit and holds a ``.`` or is followed by a port, so
# ``python:3.12@slim`` names no host.
_CASE_HOST_PASSWORD = re.compile(
    r"""([\w.+-]+:)(?!:)[^@]+"""
    r"""(@[A-Za-z0-9][A-Za-z0-9-]*(?:(?:\.[A-Za-z0-9-]*)+(?::[0-9]*)?|:[0-9]+))"""
)
# The ``@`` and the host of a password before a host inside a part of a case id, with text
# after it (``bob:VALUE@db.example:5432-ro``, ``"bob:VALUE@db.example"``,
# ``bob:VALUE@db.example?sslmode=require``). The host is a name of letters, digits, ``_``,
# ``.`` and ``-`` that starts with a letter or a digit and holds a ``.`` or is followed by a
# port, and a port is digits that no letter, digit or ``_`` follows, so the digest of an image
# (``python:3.12@sha256:0a1b...``) names no host.
_CASE_HOST_AT = re.compile(
    r"""@[A-Za-z0-9][\w-]*(?:(?:\.[\w-]*)+(?::[0-9]+(?!\w))?|:[0-9]+(?!\w))"""
)
# The user of such a password: a run of letters, digits, ``_``, ``.``, ``+``, ``%`` and ``-``
# that no such character or ``:`` comes right before, then one ``:``.
_CASE_HOST_USER = re.compile(r"""(?<![\w.+%:-])[\w.+%-]+:(?!:)""")
# What a password before a host may hold: no ``@``, white space, quote or angle bracket.
_CASE_HOST_PASSWORD_STOP = frozenset("@\"'<> \t\r\n")
# A name or an option glued to its value by ``:`` in one part of a case id: ``token:VALUE``,
# ``--password:VALUE`` and ``X-Api-Key:VALUE``, also after another name's ``:`` or ``=``, a
# ``-`` that joins two values or any other character that is no letter, digit, ``_`` or ``-``
# (``db:password:VALUE``, ``cfg=password:VALUE``, ``5432-password:VALUE``, ``$token:VALUE``),
# and in quotes, as JSON writes a key (``"token":"VALUE"``). The name is the whole run of
# letters, digits, ``_`` and ``-`` before the ``:``, as ``_credential_name`` reads it, and it
# may stand in a pair of quotes. A ``::`` gives no value, so ``pkg::name`` and ``Token::Kind``
# give none. A match starts only where a run starts, so the parts are read in linear time.
_CASE_KEY = re.compile(r"""(?<![A-Za-z0-9_-])(["']?)([A-Za-z0-9_-]+)(["']?):(?!:)""")
# A whole number: the value of a named argument of a benchmark, as ``BM_Hash/key:3`` writes
# one after the ``/`` that joins the parts of its name.
_CASE_NUMBER = re.compile(r"""-?[0-9]+""")


def public_case(case: str) -> str:
    """Return a case id as a results document may show it.

    Every absolute path in it, and every relative path that climbs out of
    its folder with ``..``, is cut to its last part, as ``_CASE_PATH`` finds
    it: ``test_read[/a/b/data.csv]`` and ``test_read[../../a/data.csv]`` show
    ``test_read[data.csv]``, and ``BM_Read//a/b/data.bin`` shows
    ``BM_Read/data.bin``. The ``/`` that joins the parts of a name is no
    path, so ``BM_Vec<int>/8/cpu_time`` is shown as it is. The user part of
    an address (``scheme://user:password@``) is hidden, and a ``file://``
    address loses what stands before its path with the path's folders
    (``test_load[file://localhost/a/x.bin]`` shows
    ``test_load[file://x.bin]``). The secrets of each part of the id and of
    the words in its brackets, or of its words when it has no bracket
    (``_case_secrets_hidden``), and its long random-looking values
    (``looks_random``) are hidden as the shown command hides them. An id
    that holds none of these is returned unchanged, and so is an id this
    function returned.
    """
    return _public_case(case)[0]


def public_case_drops(case: str) -> tuple[str, bool]:
    """Return ``public_case(case)`` and whether its cut dropped a word that holds no ``/``.

    A path in a case id runs on over the words after it that start with a
    letter, a digit or ``_``, up to the last that holds a ``/``, and the cut
    keeps only its last part: ``copy /a/in.bin fast mode/x`` shows
    ``copy x``, and the word ``fast`` is dropped. Two ids that differ only
    in such a word would show alike, so a run adds a mark to the shown name
    of every id whose cut drops one (``case_suffix``). A cut that drops only
    words that hold a ``/``, the folders of a path, does not:
    ``test_read[/a/b/data.csv]`` shows ``test_read[data.csv]`` with no mark.
    """
    return _public_case(case)


def _public_case(case: str) -> tuple[str, bool]:
    """Return ``case`` as ``public_case`` shows it, and whether its cut dropped a word.

    A word is dropped when it holds no ``/`` and starts in a stretch the cut
    of a path leaves out (``_drops_words``), or when a word that tells the id
    apart (``case_tell_words``) is not among the words shown, in order: a
    secret read with a path's last part as its value hides a word that the
    id with its paths in place shows.

    The words that tell the id apart are read only where one can be lost
    that way: when a secret is hidden in the cut text, or when a cut runs
    over a blank and so leaves out a whole word that holds a ``/``. Otherwise
    every word shown is the word the id holds, and reading the secrets of the
    id a second time would only double the time a long id takes.
    """
    read = _case_addresses_read(case)
    left: list[tuple[int, int]] = []
    cutter = _path_cutter(read, left, _CASE_INNER_PATH, in_case=True)
    cut = _paths_cut(_CASE_PATH, read, cutter, None)
    shown = _hidden_random(_case_secrets_hidden(cut), paths=False)
    dropped = _drops_words(read, left) or (
        (shown != cut or any(_SPACE.search(read, start, end) for start, end in left))
        and not _words_kept(_case_tell_words(_case_folders_out(read, left)), shown)
    )
    return shown, dropped


def _case_addresses_read(case: str) -> str:
    """Return ``case`` with its addresses read as ``public_case`` reads them, before the cut.

    The user part of an address after a scheme is hidden, a ``file://``
    address loses what stands before its path, a socket address written
    with no ``/`` after ``://`` gains one, and a path written with percent
    escapes is cut to ``%2F`` and its last part (``_percent_path_cut``).
    """
    case = _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", case)
    case = _FILE_AUTHORITY.sub(lambda found: f"{found.group(1)}/", case)
    case = _address_sub(_SOCKET_NO_ROOT, lambda found: f"{found.group(1)}/", case)
    return _PERCENT_PATH.sub(_percent_path_cut, case)


# A word of a case id: a run of characters that are no white space.
_CASE_WORD = re.compile(r"\S+")


def _case_folders_out(text: str, left: list[tuple[int, int]]) -> str:
    """Return ``text`` with the folders of each path its cut leaves out read alike.

    ``left`` holds the stretches of ``text`` that the cuts of its paths leave
    out, each from a path's start to its last part (``_path_cutter``). In
    each stretch, a word that holds no ``/`` (``_drops_words``) is kept, and
    so is a word that holds a ``/`` and a secret (``API_KEY=q/a``), as its
    secret may hide its ``/``; the folder words right after such a word go
    on with its path, so they join it as one word. Each run of other words,
    blanks and all, becomes the one folder word ``/_/``:
    ``copy /a/in.bin fast mode/x`` reads as ``copy /_/ fast /_/x``. So the
    words of an id that hold no ``/`` are read the same whatever folders
    its paths name, blanks included, also when a secret takes a path as its
    value: ``test_db[token:/a/my dir/x.pem]`` and ``test_db[token:/b/x.pem]``
    both read as ``test_db[token:/_/x.pem]``, and
    ``run /a/s.sock API_KEY=b/my dir/x.pem`` reads as
    ``run /_/ API_KEY=b/my/x.pem``, its secret one word as with ``b/up``.
    """
    out: list[str] = []
    at = 0
    for start, end in sorted(left):
        start = max(start, at)
        if end <= start:
            continue
        # Each word kept from the stretch, in order, with None for a run of folder words.
        words: list[str | None] = []
        # Whether the last word kept holds a secret, so the folder words after it go on its path.
        on_secret = False
        for found in _CASE_WORD.finditer(text, start, end):
            whole = _CASE_WORD.match(text, found.start())
            if whole is not None and not case_folder_word(whole.group()):
                words.append(whole.group())
                on_secret = False
            elif whole is not None and HIDDEN in _case_secrets_hidden(whole.group()):
                words.append(found.group())
                on_secret = True
            elif on_secret:
                kept = words[-1] or ""
                words[-1] = kept if kept.endswith("/") else kept + "/"
            elif not words or words[-1] is not None:
                words.append(None)
        out.append(text[at:start])
        out.append(" ".join("/_/" if word is None else word for word in words))
        at = end
    out.append(text[at:])
    return "".join(out)


def _drops_words(text: str, left: list[tuple[int, int]]) -> bool:
    """Say whether a word of ``text`` that holds no ``/`` starts in a stretch the cut leaves out.

    ``left`` holds the stretches of ``text`` that the cuts of its paths leave
    out, each from a path's start to its last part (``_path_cutter``). A word
    that starts in one and holds no ``/`` is dropped: a word the path runs
    over (``copy /a/in.bin fast mode/x`` shows ``copy x``), or the middle
    word of a folder named in three words. A word is judged whole, so the
    last word of a folder name with a space holds the ``/`` after it however
    much of the word the cut kept: ``unix:///a/my dir/s.sock`` shows
    ``unix:///s.sock``, and ``dir/s.sock`` is a folder word. A word that
    starts before a path, as ``host=/a/b`` does, is judged where it starts.
    """
    for start, end in left:
        for found in _CASE_WORD.finditer(text, start, end):
            at = found.start()
            if at == start and at and not text[at - 1].isspace():
                continue
            word = _CASE_WORD.match(text, at)
            if word is not None and not case_folder_word(word.group()):
                return True
    return False


def _words_kept(words: list[str], shown: str) -> bool:
    """Say whether every word of ``words`` stands in the text ``shown``, in the same order.

    A word stands whole, with white space or an end on each side. A word
    that holds a hidden secret stands when each piece around ``HIDDEN``
    does, anywhere in a word: a secret read with the paths in place may
    hide more than it hides once they are cut (``'KEY=<hidden>'`` against
    ``'KEY=<hidden> --out=x'``), and every word it leaves is still shown.
    """
    at = 0
    for word in words:
        if HIDDEN in word:
            for piece in filter(None, word.split(HIDDEN)):
                at = shown.find(piece, at)
                if at < 0:
                    return False
                at += len(piece)
            continue
        found = re.compile(rf"(?<!\S){re.escape(word)}(?!\S)").search(shown, at)
        if found is None:
            return False
        at = found.end()
    return True


def case_folder_word(word: str) -> bool:
    """Say whether a word of a case id is read as a folder: it holds a ``/``.

    A ``%2F`` is no ``/``: a path written with percent escapes is cut to
    ``%2F`` and its last part before the words of an id are read
    (``case_tell_words``), so its folders are gone by then, and a word
    such as ``4%2Fq``, where a digit stands before the ``%2F``, is a plain
    word.
    """
    return "/" in word


# The mark a run adds to the shown name of a case id whose cut drops a word that holds no
# ``/`` (``public_case_drops``): a space, ``+`` and eight lower-case hex digits, at the end
# of the name or right before a ``/`` a driver adds after it (``copy x +1a2b3c4d``,
# ``BM_Read/x +1a2b3c4d/cpu_time``).
CASE_SUFFIX_HEX: Final = 8
CASE_KEY_BYTES: Final = 32
"""How many random bytes a run's key for the marks of case names holds."""
_CASE_SUFFIX = re.compile(r" \+[0-9a-f]{8}(?=/|$)")


def case_suffix(key: bytes, tell_sha256: str) -> str:
    """Return the mark a run with ``key`` adds to the shown name of a case told by ``tell_sha256``.

    It is ``" +"`` and the first ``CASE_SUFFIX_HEX`` hex digits of the
    HMAC-SHA256 of the tell's hash under the run's own random key, so the
    mark tells cases apart and shows nothing of the words that tell them
    apart: without the key, a reader of the results cannot confirm a guess
    of those words by hashing it.
    """
    digest = hmac.new(key, tell_sha256.encode("ascii"), hashlib.sha256).hexdigest()
    return " +" + digest[:CASE_SUFFIX_HEX]


def case_has_suffix(case: str) -> bool:
    """Say whether a case id holds a word shaped like the mark ``case_suffix`` gives."""
    return _CASE_SUFFIX.search(case) is not None


def case_marked_name(case: str) -> str | None:
    """Return the part of a case id up to the end of its first mark, or ``None`` without one.

    It is the name a run gave (``case_suffix``): ``BM_Read/x +1a2b3c4d/cpu_time``
    gives ``BM_Read/x +1a2b3c4d``, the name the driver added ``/cpu_time`` to.
    """
    found = _CASE_SUFFIX.search(case)
    return None if found is None else case[: found.end()]


def case_text_sha256(text: str) -> str:
    """Return the SHA-256 of a text of a case id as lower-case hex, lone surrogates kept."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def case_unsuffixed(case: str) -> str:
    """Return a case id without the mark a run added to it (``case_suffix``).

    ``copy x +1a2b3c4d`` gives ``copy x`` and ``BM_Read/x +1a2b3c4d/cpu_time``
    gives ``BM_Read/x/cpu_time``; an id with no mark is returned as it is.
    """
    return _CASE_SUFFIX.sub("", case)


def case_secrets_hidden(case: str) -> str:
    """Return a case id with its secrets hidden as ``public_case`` hides them, and its paths kept.

    The user part of an address after a scheme, the secrets of the id's
    words and parts (``_case_secrets_hidden``) and its long random-looking
    values (``looks_random``) are hidden; every path, absolute or climbing
    with ``..``, is kept as written. Two ids that differ only in a hidden
    secret give the same text, and an id that holds no path to cut gives
    what ``public_case`` gives.
    """
    case = _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", case)
    return _hidden_random(_case_secrets_hidden(case), paths=False)


def case_tell_words(case: str) -> list[str]:
    """Return the words that tell a case id apart from the ids its cut shows alike.

    They are the words of the id, split on white space and in order, that
    hold no ``/`` (``case_folder_word``), read with its addresses read as
    ``public_case`` reads them and its secrets hidden as it hides them. The
    words a path runs over are among them; a word that holds a ``/`` is
    read as a folder, which may differ between sides and launches; a path
    written with percent escapes counts as ``%2F`` and its last part alone,
    as it is shown, so its folders are read as folders too; the folders of
    each path the cut leaves out are read as folders, a folder name with
    blanks included (``_case_folders_out``), so a secret written as a path
    through such a folder tells the id apart as one through a plain folder
    does; and a secret never tells two ids apart.
    """
    read = _case_addresses_read(case)
    left: list[tuple[int, int]] = []
    _paths_cut(_CASE_PATH, read, _path_cutter(read, left, _CASE_INNER_PATH, in_case=True), None)
    return _case_tell_words(_case_folders_out(read, left))


def _case_tell_words(read: str) -> list[str]:
    """Return ``case_tell_words`` of an id read as ``_case_folders_out`` reads it."""
    hidden = _hidden_random(_case_secrets_hidden(read), paths=False)
    return [word for word in hidden.split() if not case_folder_word(word)]


def _case_secrets_hidden(case: str) -> str:
    """Hide the secrets of a case id: those of its words, then those of each of its parts.

    The words of the id are read first as the words of a command
    (``_case_words_hidden``), so a word that a hidden value's first word
    gives a value of its own is read with that first word in place:
    ``bench[tool --auth=Basic V]`` shows ``bench[tool --auth=<hidden>
    <hidden>]``. Then a part, as ``_CASE_PART`` splits the id, that gives a
    credential-like name or option its value loses the value, as an
    argument of the shown command does (``_hidden_credential``):
    ``test_db[PGPASSWORD=V]``, ``test_db[--password=V]``,
    ``bench[token=V]`` and ``bench/api_key=V/latency`` show the name and
    ``<hidden>``. A part that is a password before a host, written without
    a scheme (``_CASE_HOST_PASSWORD``), loses the password:
    ``bench[bob:V@db.example:5432]`` shows
    ``bench[bob:<hidden>@db.example:5432]``, and so does a part with text
    before the user or after the host (``_case_host_passwords_hidden``), up
    to the ``@``: ``test_db[bob:V@db.example:5432-ro]`` shows
    ``test_db[bob:<hidden>@db.example:5432-ro]``. A part that glues a
    credential-like name or option to its value with ``:`` (``_CASE_KEY``),
    also after another name, a ``-`` join or in quotes
    (``_case_key_hidden``), loses the value: ``test_db[token:V]`` and
    ``BM_Auth/password:V`` show ``test_db[token:<hidden>]`` and
    ``BM_Auth/password:<hidden>``; a whole
    number right after a ``/`` is a benchmark's named argument and is kept
    (``BM_Hash/key:3``). Such a value ends where its part ends, so the
    brackets and the parts after it are kept. A user or a host alone is
    shown.
    """
    case = _case_words_hidden(case)
    if "=" in case or "@" in case or ":" in case:

        def shown(found: re.Match[str]) -> str:
            part = found.group(0)
            hidden = _hidden_credential(part) if "=" in part else None
            if hidden is not None:
                return hidden
            password = _CASE_HOST_PASSWORD.fullmatch(part)
            if password is not None:
                return f"{password.group(1)}{HIDDEN}{password.group(2)}"
            if "@" in part:
                part = _case_host_passwords_hidden(part)
            after_slash = found.string[found.start() - 1 : found.start()] == "/"
            return _case_key_hidden(part, after_slash=after_slash)

        case = _CASE_PART.sub(shown, case)
    return case


def _case_host_passwords_hidden(part: str) -> str:
    """Hide each password before a host, written without a scheme, inside a part of a case id.

    The host is found as ``_CASE_HOST_AT`` finds it, with any text after it
    kept: ``bob:VALUE@db.example:5432-ro`` shows
    ``bob:<hidden>@db.example:5432-ro``, and ``"bob:VALUE@db.example"``,
    ``dsn=bob:VALUE@db.example`` and ``bob:VALUE@db.example?sslmode=require``
    keep their quotes, their name and their query. The password runs back
    from the ``@`` over what a password may hold to the first user before it
    (``_CASE_HOST_USER``), so a user with ``%40`` keeps it and
    ``db:bob:VALUE@db.example`` hides ``bob:VALUE``. A host with no user and
    password before it is left as it is. The text between two ``@`` is read
    back once, so a long part is read in linear time.
    """
    pieces: list[str] = []
    done = 0
    for host in _CASE_HOST_AT.finditer(part):
        at = host.start()
        start = at
        while start > 0 and part[start - 1] not in _CASE_HOST_PASSWORD_STOP:
            start -= 1
        user = _CASE_HOST_USER.search(part, start, at)
        if user is None or user.end() >= at:
            continue
        pieces.append(part[done : user.end()])
        pieces.append(HIDDEN)
        done = at
    if not pieces:
        return part
    pieces.append(part[done:])
    return "".join(pieces)


def _case_key_hidden(part: str, *, after_slash: bool) -> str:
    """Hide the value that the first credential-like name glued to it with ``:`` gives in a part.

    The names are found as ``_CASE_KEY`` finds them, in turn, so the one of
    ``db:password:VALUE`` is ``password``. A quote after the name closes one
    before it (``"token":``); a quote before it alone opens a text that the
    name starts (``"token:VALUE"``). The value runs to the end of the part
    and keeps the quote that closes it: ``"token":"<hidden>"`` and
    ``"token:<hidden>"``. A part right after a ``/`` whose first name is a
    credential's and whose value is a whole number is a benchmark's named
    argument and is kept (``BM_Hash/key:3``). A name with no value after it
    gives none (``token:``), and a part with no such name is returned as it
    is.
    """
    if ":" not in part:
        return part
    for key in _CASE_KEY.finditer(part):
        opened, name, closed = key.groups()
        if (closed and opened != closed) or not _credential_name(name):
            continue
        value = part[key.end() :]
        if not value:
            return part
        if after_slash and key.start() == 0 and _CASE_NUMBER.fullmatch(value):
            return part
        head = part[: key.end()]
        if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
            return f"{head}{value[0]}{HIDDEN}{value[0]}"
        if opened and not closed and len(value) > 1 and value[-1] == opened:
            return f"{head}{HIDDEN}{opened}"
        return f"{head}{HIDDEN}"
    return part


# A bracket of a case id, which opens or closes the text of its arguments.
_CASE_BRACKET = re.compile(r"[\[\]]")


def _case_texts(case: str) -> list[tuple[int, int]]:
    """Return where each text of a case id that may hold words starts and ends.

    An id with no ``[`` is one text. In any other, each text in a pair of
    brackets that stands in no other pair is one, the pairs inside it
    counted, so ``bench[test [ -f x ] && tool --token V]`` is one text; the
    text of a ``[`` that is not closed runs to the end of the id. What
    stands outside the brackets is no such text.
    """
    if "[" not in case:
        return [(0, len(case))]
    texts: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for found in _CASE_BRACKET.finditer(case):
        if found.group(0) == "[":
            if depth == 0:
                start = found.end()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                texts.append((start, found.start()))
    if depth:
        texts.append((start, len(case)))
    return texts


def _case_words_hidden(case: str) -> str:
    """Hide the secrets of the words of a case id, as the shown command hides them.

    Each text of the id (``_case_texts``) that holds a blank, as the id of a
    test named after a command does, is read as a program's text is
    (``_hidden_code``), so a credential's value that a string gives it is
    hidden (``bench[python -c "password = 'V'"]`` shows ``bench[python -c
    "password = '<hidden>'"]``), and then as the words of one argument of a
    command (``_hidden_words``): a client's password option hides the
    word after it (``bench[redis-cli -a V PING]`` shows ``bench[redis-cli -a
    <hidden> PING]``) and the password glued to it (``bench[mysql -pV]``), a
    credential-like option hides the next word (``bench[tool --token V]``),
    and a header or a name with a ``:`` whose name is a credential hides what
    follows it up to the end of the text (``bench[curl -H Authorization:
    Bearer V https://db.example/]`` shows ``bench[curl -H Authorization:
    <hidden>]``, ``bench[tool password: V]`` shows ``bench[tool password:
    <hidden>]``). An option that names no credential, or one with no word
    after it, keeps what follows (``bench[tool --token-count 8]``,
    ``bench[mysql -P 3306]``, ``bench[mysql -p]``), and so do the hosts and
    the users the words name. A text with no blank is left as it is.
    """
    if not _SPACE.search(case):
        return case
    out: list[str] = []
    end = 0
    for start, stop in _case_texts(case):
        text = case[start:stop]
        if not _SPACE.search(text):
            continue
        out.append(case[end:start])
        out.append(_hidden_words(_hidden_code(text)))
        end = stop
    out.append(case[end:])
    return "".join(out)


# The characters of the name that ends the text before an ``=``: an option's or a variable's.
_NAME_CHARS: Final = string.ascii_letters + string.digits + "_-"


def _name_before(text: str) -> str:
    """Return the run of letters, digits, ``_`` and ``-`` that ends the text, maybe empty.

    One pass from the end of the text: a long run of such characters that
    ends in another character gives the empty name at once.
    """
    return text[len(text.rstrip(_NAME_CHARS)) :]


# The blanks between words, and the characters that end a plain run of a word and a part of
# it in double quotes, as ``shlex.split`` reads them.
_SPLIT_BLANKS: Final = " \t\r\n"
_SPLIT_PLAIN_END = re.compile(r"""[ \t\r\n'"\\]""")
_SPLIT_DOUBLE_END = re.compile(r"""["\\]""")
# The characters a backslash in double quotes escapes, as ``shlex.split`` reads them and as a
# shell does: a shell also takes the backslash away before ``$``, a backquote and a line break,
# and the line break with it.
_SPLIT_DOUBLE_ESCAPES: Final = '"\\'
_SHELL_DOUBLE_ESCAPES: Final = '"\\$`\n'


def _shell_split(text: str, *, as_shell: bool = False) -> list[str]:
    """Return the words of a shell text as ``shlex.split`` returns them, reading the text once.

    A word joins its plain runs, its parts in single quotes as they stand,
    its parts in double quotes, where a backslash keeps only a ``"`` or a
    ``\\`` after it, and each character after a backslash outside quotes;
    a word of quotes alone is an empty word. Raises ``ValueError`` where
    ``shlex.split`` does: on a quote that is not closed and on a backslash
    at the end. ``shlex.split`` grows a word one character at a time, which
    takes time in proportion to the square of a long word.

    With ``as_shell``, a backslash in double quotes also keeps only a ``$``
    or a backquote after it, and a line break after it goes with it, as a
    shell reads them: the word is what the command the text runs is given,
    so ``"redis-cli \\"\\$@\\""`` gives ``redis-cli "$@"``.
    """
    escapes = _SHELL_DOUBLE_ESCAPES if as_shell else _SPLIT_DOUBLE_ESCAPES
    words: list[str] = []
    word: list[str] = []
    in_word = False
    at = 0
    while at < len(text):
        char = text[at]
        if char in _SPLIT_BLANKS:
            if in_word:
                words.append("".join(word))
                word = []
                in_word = False
            at += 1
            continue
        in_word = True
        if char == "'":
            close = text.find("'", at + 1)
            if close == -1:
                raise ValueError("No closing quotation")
            word.append(text[at + 1 : close])
            at = close + 1
        elif char == '"':
            at += 1
            while True:
                stop = _SPLIT_DOUBLE_END.search(text, at)
                if stop is None:
                    raise ValueError("No closing quotation")
                word.append(text[at : stop.start()])
                at = stop.start()
                if text[at] == '"':
                    at += 1
                    break
                if at + 1 == len(text):
                    raise ValueError("No escaped character")
                escaped = text[at + 1]
                if escaped not in escapes:
                    word.append("\\" + escaped)
                elif escaped != "\n":
                    word.append(escaped)
                at += 2
        elif char == "\\":
            if at + 1 == len(text):
                raise ValueError("No escaped character")
            word.append(text[at + 1])
            at += 2
        else:
            stop = _SPLIT_PLAIN_END.search(text, at)
            end = len(text) if stop is None else stop.start()
            word.append(text[at:end])
            at = end
    if in_word:
        words.append("".join(word))
    return words


# A word of a shell command: a run of characters that are no white space, in
# which a quoted part may hold white space. A quote that is not closed runs to
# the end of the text, so nothing after it is split off.
_SHELL_WORD = re.compile(
    r"""(?:[^\s'"\\]|\\.|\\\Z|'[^']*(?:'|\Z)|"(?:[^"\\]|\\.|\\\Z)*(?:"|\Z))+""", re.DOTALL
)
# A word of a shell text, as ``_SHELL_WORD`` reads it, or an operator that ends a command
# there: ``&&``, ``||``, ``;``, ``&`` or ``|`` outside quotes. A redirection to a descriptor
# (``2>&1``, ``>&-``), ``&>`` and the ``>|`` that writes over a file belong to the word; the
# ``>`` that closes the mark of a hidden value starts none. A backslash before a line break
# outside quotes joins two lines, as a shell reads it: inside a word it joins the word's two
# parts, and it starts no word, so after a blank or an operator it is read with the blanks
# around it as one gap (``_breaks_line``).
_SHELL_TOKEN_PART = (
    r"""[<>]&(?=[0-9-])|&>|(?<!"""
    + re.escape(HIDDEN[:-1])
    + r""")>\||[^\s'"\\;&|]|\\[^\n]|\\\Z|'[^']*(?:'|\Z)|"(?:[^"\\]|\\.|\\\Z)*(?:"|\Z)"""
)
_SHELL_TOKEN = re.compile(
    rf"""(?P<word>(?:{_SHELL_TOKEN_PART})(?:{_SHELL_TOKEN_PART}|\\\n)*)"""
    r"""|(?P<operator>&&|\|\||[;&|])""",
    re.DOTALL,
)


def _breaks_line(gap: str) -> bool:
    """Say whether the blanks between two tokens of a shell text hold a line break.

    A backslash before a line break joins the two lines, as a shell reads
    it, so that line break ends no command: ``true && \\`` and an ``eval``
    on the next line are one command line.
    """
    return "\n" in gap.replace("\\\n", "")


# A quoted part of a shell word, or an escaped character, which no quote opens.
_QUOTED_PART = re.compile(r"""'([^']*)(?:'|\Z)|"((?:[^"\\]|\\.|\\\Z)*)(?:"|\Z)|\\.""", re.DOTALL)
# How deep ``_operator_spans`` reads quoted texts inside quoted texts.
_SHELL_DEPTH: Final = 8
# An option that gives a program its text to run: ``-c``, as of ``sh -c`` and ``python -c``,
# also among other short options (``bash -lc``, ``sh -ec``).
_CODE_OPTION = re.compile(r"-[A-Za-z]*c")
# Shells: the text after ``-c`` given to one of them is a shell text.
SHELLS: Final[tuple[str, ...]] = (
    "sh",
    "bash",
    "dash",
    "zsh",
    "ksh",
    "mksh",
    "ash",
    "yash",
    "fish",
)


class _ShellText:
    """Say, word by word, whether the next word is the text that ``-c`` gives a shell to run.

    The shell is the last word before ``-c`` that is no option, by the last
    part of its path: ``sh -c``, ``/bin/bash -lc`` and ``bash -l -c`` give
    their next word a shell text; ``python -c`` does not.
    """

    def __init__(self) -> None:
        self.shell = False
        self.next = False

    def read(self, word: str) -> bool:
        """Take in a word; return whether this word is a shell text."""
        this = self.next
        plain = _plain_word(word)
        self.next = self.shell and _CODE_OPTION.fullmatch(plain) is not None
        if not plain.startswith("-"):
            self.shell = plain.rpartition("/")[2] in SHELLS
        return this


_QUOTES: Final = "'\""


def _operator_spans(text: str, depth: int = 0, *, shell: bool = True) -> list[tuple[int, int]]:
    """Return where the operators that end a command lie in a shell text, in order.

    An operator outside quotes ends a command. One inside quotes is part of
    a word and ends nothing (``curl -H 'Cookie: a=1; b=2'``), unless the
    quoted word is a shell text of its own: the text after ``-c`` of a
    shell (``_ShellText``), as in ``sh -c 'tool ...; ls'``, or another
    command text a shell runs (``_CommandWalk.shell_run``), as the remote
    command of ``ssh`` in ``ssh HOST 'tool ...; ls'``. Such a text in double
    quotes is read as the next shell gets it, with its escapes taken out
    (``_double_quoted_text``): in ``sh -c "tool --config \\"a; b\\""`` the
    ``;`` stands between quotes and ends nothing, and in ``bash -c "dash -c
    \\"tool; ls\\""`` it ends a command of the third shell. Quoted texts are
    read ``_SHELL_DEPTH`` shells deep; an operator deeper than that ends no
    command, so a value before it is hidden to its end.

    Without ``shell`` the text is no shell text but its words end as a
    shell's do, as the text of ``env -S`` or ``hyperfine -N``: an operator
    outside quotes is part of a word and ends nothing, and only the shell
    texts in its quoted words (``env -S "sh -c 'tool; ls'"``) hold operators.
    """
    spans: list[tuple[int, int]] = []
    shells = _ShellText()
    walk = _CommandWalk(ahead=text) if _names_shell_runner(_plain_word(text)) else None
    tokens = list((_SHELL_TOKEN if shell else _SHELL_WORD).finditer(text))
    # A runner given its command as one word runs it in a shell only when no other word of
    # the command follows it (``tmux new -d 'tool; ls'``), so the walk is told the next word.
    aheads = _words_ahead(tokens, text, shell=shell)[0] if walk is not None else []
    end = 0
    for k, found in enumerate(tokens):
        if found.lastgroup == "operator":
            shells = _ShellText()
            if walk is not None:
                walk.reset()
        elif _breaks_line(text[end : found.start()]):
            shells = _ShellText()
            if walk is not None:
                walk.end_line()
        end = found.end()
        if found.lastgroup == "operator":
            spans.append(found.span())
            continue
        nested = shells.read(found.group(0))
        if walk is not None:
            walk.followed = _another_word(found.group(0), aheads[k])
            nested = walk.shell_run(found.group(0)) or nested
            walk.read(found.group(0), token=shell)
        if not nested or depth >= _SHELL_DEPTH:
            continue
        if not any(char in found.group(0) for char in _QUOTES):
            continue
        for part in _QUOTED_PART.finditer(found.group(0)):
            if part.group(1) is not None:
                at = found.start() + part.start(1)
                inner = _operator_spans(part.group(1), depth + 1)
                spans.extend((at + one, at + two) for one, two in inner)
            elif part.group(2) is not None:
                at = found.start() + part.start(2)
                read, where = _double_quoted_text(part.group(2))
                inner = _operator_spans(read, depth + 1)
                # No operator holds an escaped character, so each lies whole in the typed text.
                spans.extend((at + where[one], at + where[two - 1] + 1) for one, two in inner)
    spans.sort()
    return spans


def _double_quoted_text(text: str) -> tuple[str, Sequence[int]]:
    """Return the text of a word in double quotes as a shell reads it, and where each part stands.

    The shell takes the backslash off ``\\"``, ``\\\\``, ``\\$``, a backquote
    and a line break. The line break is kept, where ``_shell_unquoted`` takes
    it out with its backslash: here it can only end a command, so fewer
    quoted texts are read as shell texts and fewer operators are found, and
    no value ends sooner than the shell ends it. The second item gives, for
    each character of the text read, where it stands in ``text``.
    """
    if _DOUBLE_QUOTED_ESCAPE.search(text) is None:
        return text, range(len(text))
    out: list[str] = []
    where: list[int] = []
    end = 0
    for found in _DOUBLE_QUOTED_ESCAPE.finditer(text):
        out.append(text[end : found.start()])
        where.extend(range(end, found.start()))
        out.append(found.group(1))
        where.append(found.start(1))
        end = found.end()
    out.append(text[end:])
    where.extend(range(end, len(text)))
    return "".join(out), where


# A header, ``Name: value``, at the start of a word, after ``=``, after a quote or glued to
# a short option at the start of the word (``-HAuthorization: ...``).
_HEADER_NAME = re.compile(r"""(?:^|(?<=[='"])|(?<=^-[A-Za-z]))([A-Za-z][A-Za-z0-9_-]*)[ \t]*:""")
# Header names whose value is a credential whatever the words of the name say.
SECRET_HEADERS: Final[tuple[str, ...]] = ("AUTHORIZATION", "PROXY-AUTHORIZATION", "COOKIE")


def _credential_name(text: str) -> bool:
    """Say whether the text before an ``=`` ends with a credential-like name.

    The name is the run of letters, digits, ``_`` and ``-`` at the end of the
    text, without its leading dashes, so ``db.password``, ``--api-key`` and
    ``-eMY_TOKEN`` end with one and ``made.up`` does not. The test of the
    name ignores case (``looks_like_credential``).
    """
    name = _name_before(text).lstrip("-")
    return bool(name) and looks_like_credential(name)


# A parameter of the query of an address: ``?`` or ``&``, a name, ``=`` and a
# value that ends at the next ``&`` or ``#``.
_QUERY_PARAMETER = re.compile(r"([?&])([^=&#?]*)=([^&#]*)")


def _hidden_query(query: str) -> str:
    """Hide the value of each parameter of a query whose name looks like a credential.

    ``?token=V&threads=W`` shows ``?token=<hidden>&threads=W``: each value
    ends at the next ``&`` or ``#``, and every other parameter is kept.
    """

    def shown(found: re.Match[str]) -> str:
        if not _credential_name(found.group(2)):
            return found.group(0)
        return f"{found.group(1)}{found.group(2)}={HIDDEN}"

    return _QUERY_PARAMETER.sub(shown, query)


def _hidden_credential(arg: str) -> str | None:
    """Hide what follows the first ``=`` that ends a credential-like name, or ``None``.

    The name is that of a variable or of an option, alone or glued to an
    option: ``API_TOKEN=...``, ``--api-key=...``, ``--env=MY_TOKEN=...`` and
    ``-eMY_TOKEN=...`` keep the name and lose the value. A name that is a
    parameter of the query of an address, after its ``?`` or an ``&``, loses
    only its value, up to the next ``&`` or ``#``, and the other parameters
    are read the same way (``_hidden_query``). A quote that the hidden value
    closed is closed after it again (``_quote_closed``), so
    ``print('--token=...')`` shows ``print('--token=<hidden>'``.
    """
    parts = arg.split("=")
    for k in range(len(parts) - 1):
        name = _name_before(parts[k])
        if not _credential_name(name):
            continue
        head = "=".join(parts[: k + 1])
        start = len(head) - len(name)
        query = arg.find("?")
        if 0 <= query < start and arg[start - 1] in "?&":
            return _quote_closed(arg[:query] + _hidden_query(arg[query:]), arg)
        return _quote_closed(head + f"={HIDDEN}", arg)
    return None


def _quote_closed(shown: str, typed: str) -> str:
    """Close the quote that a text shown with a value hidden leaves open, as the typed text does.

    A value hidden to the end of a text takes the closing quote of the text
    with it: ``"token='...'"`` would show as ``"token=<hidden>``. When the
    typed text closes every quote it opens, the quote the shown text leaves
    open is closed after it, so the shown text splits into words as a shell
    splits the typed one. The quote comes from the text before the value,
    never from the value.
    """
    if _unclosed_quote(typed) >= 0:
        return shown
    opened = _unclosed_quote(shown)
    return shown if opened < 0 else shown + shown[opened]


# The start of an argument that gives a name its value: an option glued to its
# value by ``=`` (``--env=``, ``-eNAME=``) or a variable (``NAME=``), its name
# letters, digits, ``_``, ``-`` and ``.``, as ``made.up=`` is written.
_OPTION_ASSIGNED = re.compile(r"-{1,2}[A-Za-z0-9][A-Za-z0-9_.-]*=")
_VARIABLE_ASSIGNED = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*=")


def _ordinary_value_start(word: str) -> int | None:
    """Return where the value of an ordinary name starts in a word, or ``None``.

    The word starts with an option glued to its value by ``=`` or with a
    variable, and its name is no credential (``_credential_name``):
    ``MADE_UP_FLAGS=``, ``made.up=`` and ``--env=``. Variables that start the
    value and are no credential are passed over, so ``--env=MADE_UP_FLAGS=``
    and ``SetEnv=MADE_UP_FLAGS=`` give where the value of the last one
    starts. ``None`` when the word starts with no such name, or with one that
    is a credential.
    """
    found = _OPTION_ASSIGNED.match(word) or _VARIABLE_ASSIGNED.match(word)
    if found is None or _credential_name(found.group(0)[:-1]):
        return None
    at = found.end()
    while (more := _VARIABLE_ASSIGNED.match(word, at)) is not None:
        if _credential_name(more.group(0)[:-1]):
            break
        at = more.end()
    return at


# An option alone, as ``--token`` or ``-storepass``: dashes, then a name of
# letters, digits, ``_``, ``.`` and ``-``. An address glued to an option
# (``-xhttp://...``) is no option name.
_OPTION_NAME = re.compile(r"-{1,2}[A-Za-z0-9][A-Za-z0-9_.-]*")


# Options that take no value though their names look like a credential: switches of the
# servers and tools the drivers cover, each in its ``--no-`` form too. The argument after one
# is read as it stands, so ``--allow-credentials org/model`` keeps the model.
CREDENTIAL_SWITCHES: Final[frozenset[str]] = frozenset(
    {
        "--allow-credentials",
        "--no-allow-credentials",
        "--return-tokens-as-token-ids",
        "--no-return-tokens-as-token-ids",
    }
)


def _names_credential(arg: str) -> bool:
    """Say whether an argument is an option, without ``=``, whose name looks like a credential.

    The value of such an option is the next argument, as in ``--token VALUE``.
    A switch of ``CREDENTIAL_SWITCHES`` takes no value and names none.
    """
    if _OPTION_NAME.fullmatch(arg) is None or arg in CREDENTIAL_SWITCHES:
        return False
    return looks_like_credential(arg.lstrip("-"))


# Words that start a setting, in any case: the next word that is no option names the
# setting and the word after it is its value, as in ``aws configure set NAME VALUE``,
# ``git config --global NAME VALUE``, ``redis-cli CONFIG SET NAME VALUE`` and ``setenv NAME
# VALUE``. Options between them are passed over, up to ``--``. A name that looks like a
# credential hides its value.
SETTING_WORDS: Final[tuple[str, ...]] = ("set", "config", "setenv")
# Words that make the ``set`` right after them set a secret, in any case, as in ``gh secret set
# NAME --body VALUE`` and ``fly secrets set NAME=VALUE``: the setting is a credential whatever
# its name (``_NEXT_SECRET_NAME``).
SECRET_SETTING_WORDS: Final[tuple[str, ...]] = ("secret", "secrets")
# Clients whose ``SET`` writes the value of a key, as in ``redis-cli SET key value``: there
# ``set`` starts no setting when it is the client's command, the first word after the client
# that is no option and no value of an option. ``CONFIG SET NAME VALUE`` starts one, and so
# does a ``set`` of a later command, after a separator or a line break.
DATA_SET_CLIENTS: Final[tuple[str, ...]] = (
    "redis-cli",
    "valkey-cli",
    "redis-benchmark",
    "valkey-benchmark",
)
# Clients of a data store that send no web request, so an argument of theirs that is one word
# with no blank in it is a key, a key prefix or a value of the store and never a header:
# ``auth:`` in ``memtier_benchmark --key-prefix auth:`` or ``redis-cli GET auth:`` is shown as
# typed. An argument with a blank in it (``'Authorization: VALUE'``), and a word of a shell
# text, whose next words are the store's next arguments, are read as a header still.
_KEY_CLIENTS: Final[tuple[str, ...]] = (*DATA_SET_CLIENTS, "memtier_benchmark")
# The name of a setting: letters, digits, ``_``, ``.``, ``:``, ``/`` and ``-``, as
# ``aws_secret_access_key``, ``github.token`` and ``//registry.example/:_authToken`` are written,
# and the ``$``, ``{`` and ``}`` of a variable the shell puts in it, as in
# ``//${REGISTRY}/:_authToken`` and ``profile.${PROFILE}.aws_secret_access_key``.
_SETTING_NAME = re.compile(r"[A-Za-z0-9_.:/${}-]+")
# What parts the name of a setting: its last part is the name that is judged.
_SETTING_NAME_PARTS = re.compile(r"[.:/]")


# The ends of a setting's name that say its value is a password, glued to the word before
# them or not: ``masterauth``, ``sentinel-auth``.
_SETTING_SECRET_ENDS: Final[tuple[str, ...]] = ("AUTH",)
# The ends of a setting's name that say its value names a file or a folder, as
# ``tls-key-file``, ``ssl_cert_path`` and ``tls-ca-cert-dir`` do: the value is a path, shown
# as the rules for paths say.
_SETTING_FILE_ENDS: Final[tuple[str, ...]] = ("FILE", "PATH", "DIR")


def _names_secret_setting(word: str) -> bool:
    """Say whether a word, read after a word of ``SETTING_WORDS``, names a credential setting.

    The name is read as ``_hidden_credential`` reads the name before an
    ``=``: its part after the last ``.``, ``:`` or ``/``. So ``github.token``
    and ``//registry.example/:_authToken`` name credentials, and
    ``credential.helper`` and ``user.name`` do not. A name that ends in one
    of ``_SETTING_SECRET_ENDS`` names one too (``masterauth``), and a name
    that ends in one of ``_SETTING_FILE_ENDS`` names a file, whose value is
    a path, not a secret (``tls-key-file``).
    """
    if _SETTING_NAME.fullmatch(word) is None:
        return False
    name = _SETTING_NAME_PARTS.split(word)[-1].lstrip("-")
    upper = name.upper()
    if upper.endswith(_SETTING_SECRET_ENDS):
        return True
    if upper.endswith(_SETTING_FILE_ENDS):
        return False
    return bool(name) and looks_like_credential(name)


# The last words of a setting's name that say its value is a user name, as in ``auth-user``
# and ``sentinel-user`` of a Redis Sentinel.
_USER_NAME_WORDS: Final[tuple[str, ...]] = ("USER", "USERNAME")
# The setting of a line of a Sentinel's config that gives a master's password after the
# master's name: ``sentinel auth-pass NAME PASSWORD``.
_SENTINEL_MASTER_PASSWORD: Final = "auth-pass"


def _names_sentinel_secret(word: str) -> bool:
    """Say whether a word names a setting of a Redis Sentinel whose value is a password.

    The settings are those of ``SENTINEL SET``, ``SENTINEL CONFIG SET`` and
    the lines of a Sentinel's config, as ``src/sentinel.c`` reads them in
    any case
    ([Redis 7.4.0](https://github.com/redis/redis/blob/7.4.0/src/sentinel.c)):
    a name is judged as ``_names_secret_setting`` judges one, so
    ``auth-pass`` and ``sentinel-pass`` name a password, unless its last
    word names a user (``_USER_NAME_WORDS``): ``auth-user`` and
    ``sentinel-user`` give a user name, which is shown.
    """
    words = name_words(word)
    return bool(words) and words[-1] not in _USER_NAME_WORDS and _names_secret_setting(word)


# Options whose value is ``user:password``, as curl's ``-u``/``--user`` and
# ``-U``/``--proxy-user`` take it, or ``certificate:password``, as its
# ``--cert`` and ``--proxy-cert`` take it: what follows the first ``:`` is hidden.
USER_PASSWORD_OPTIONS: Final[tuple[str, ...]] = (
    "-u",
    "--user",
    "-U",
    "--proxy-user",
    "--cert",
    "--proxy-cert",
)
# Such an option with its value in the same argument: ``--user=user:password``,
# ``-uuser:password``, ``--cert=client.pem:password``.
_GLUED_USER_PASSWORD = re.compile(
    r"""(--user=|--proxy-user=|--cert=|--proxy-cert=|-[uU](?=[^\s:=-]))([^:\s]*):(.+)""",
    re.DOTALL,
)
# What the next argument is, after an option: a value hidden whole, or the
# password of a ``user:password``; after the name of a credential setting,
# each later word of the command that is no option.
_NEXT_SECRET: Final = "secret"
_NEXT_PASSWORD: Final = "password"
_NEXT_SETTING_VALUES: Final = "setting values"
# After ``set`` of a secret (``SECRET_SETTING_WORDS``): the next word is the secret's name, shown,
# or its name and value (``NAME=VALUE``), which loses its value. Each later word is read as after
# the name of a credential setting; an option there leaves the name unknown, so every later word
# that is no option is hidden.
_NEXT_SECRET_NAME: Final = "secret name"
# After ``AUTH`` as a client's command: the password, or the user name when another word of
# the command follows it, the password after that (``AUTH [user] password``).
_NEXT_AUTH: Final = "auth"
# A name, shown, and then a password hidden whole: the user name after ``AUTH`` of ``HELLO``
# and ``AUTH2`` of ``MIGRATE``, and the master's name after ``auth-pass`` on a line of a
# Sentinel's config.
_NEXT_USER: Final = "user"
# A command of the client's own, read as one text, as the value of ``--command``.
_NEXT_COMMAND: Final = "command"
# A password, or ``user:password`` with the user shown, as the value of a client's
# ``credentials`` option (``_hidden_credentials``).
_NEXT_CREDENTIALS: Final = "credentials"
# The rules after the user name of ``ACL SETUSER``: a rule that adds or removes a password
# (``>password``, ``<password``) or the hash of one (``#hash``, ``!hash``) keeps only its
# first character, and any other rule is read as it stands.
_NEXT_ACL_RULES: Final = "acl rules"
# The values of a client's option that takes one secret or more (``many_secrets``): each
# next word is hidden whole up to a word that starts with ``-`` or is an operator.
_NEXT_SECRETS: Final = "secrets"
# The token after an Authorization scheme word that is a credential's value, hidden whole
# unless it starts an option: ``--token Bearer VALUE`` and ``--auth=Basic VALUE``.
_NEXT_TOKEN: Final = "token"
# The schemes of an Authorization header whose token follows the scheme word
# (https://www.rfc-editor.org/rfc/rfc9110#name-authorization), compared in lower case: the
# scheme word and the token after it are one credential.
AUTH_SCHEME_WORDS: Final[frozenset[str]] = frozenset({"bearer", "basic", "token"})
# The user name after a server's ``acl_user`` option, shown, and then that user's rules, read
# as the rules of ``ACL SETUSER`` (``_NEXT_ACL_RULES``).
_NEXT_ACL_USER: Final = "acl user"
# The first characters of the rules of ``ACL SETUSER`` that give a password or its hash.
_ACL_PASSWORD_RULES: Final = (">", "<", "#", "!")
# A word after a credential setting's name that is passed over: an option with no
# value glued to it, ``--`` and a bare ``=``.
_SETTING_PASSED_OVER = re.compile(r"--[A-Za-z0-9][A-Za-z0-9_.-]*|-[A-Za-z]|--|=")
# A long option with its value glued after ``=``.
_LONG_OPTION_GLUED = re.compile(r"(--[A-Za-z0-9][A-Za-z0-9_.-]*=).+", re.DOTALL)
# A character that starts what a shell expands outside quotes: a parameter, a command's
# output (``$(...)``) or a text in backquotes. A substitution read as one word stands as
# one mark of ``_SUBSTITUTION_MARK``.
_SHELL_EXPANSION = re.compile(r"[$`]")
# What a shell makes a word of each item of even in double quotes: ``$@``, ``${@...}`` and
# a whole list, as ``${NAME[@]}``.
_LIST_EXPANSION = re.compile(r"\$\{?@|\[@\]")
# A word made only of command separators, such as ``;`` or ``&&``.
_SEPARATOR_WORD = re.compile(r"[;&|()`]+")


@dataclass(frozen=True)
class ClientOptions:
    """The options of one client program that take a password, though no name says so.

    ``secret`` options take a value that is hidden whole, given as the next
    argument or glued to the option (``-a VALUE``, ``-aVALUE``,
    ``--authenticate=VALUE``). ``joined`` options hide a value only when it is
    glued to them: ``mysql -pVALUE`` hides it, while ``-p`` alone asks for the
    password and the next argument is something else, such as a database
    name. ``user_password`` options take ``user:password`` and lose the
    password, separate or glued (``ab -A user:<hidden>``). A client that
    ``runs_command`` runs the command written after its options (``sshpass``):
    its first argument that is no option and no value of an option starts
    that command, which is read with its own options. ``takes_value`` names
    the client's other options that take the next argument as their value.
    ``command`` options take a command of the data store the client talks
    to, as one text, the next argument or glued after ``=``
    (``memtier_benchmark --command 'AUTH VALUE'``): it is read as the command
    of a client of ``DATA_SET_CLIENTS`` is read, so ``AUTH`` in it hides its
    password and ``SET`` in it writes a key. A ``sentinel`` option starts a
    line of a Sentinel's config, its setting and the setting's arguments
    written after it (``redis-server --sentinel auth-pass master VALUE``):
    the value of a password setting there is hidden
    (``_names_sentinel_secret``), after the master's name for ``auth-pass``.
    ``switches`` are options whose name says password but that take no value
    (``redis-cli --askpass`` asks for the password): the word after one is
    read as it stands. ``credentials`` options take a password, or a user and
    a password written ``user:password``: as the next argument or glued to a
    short option, a value with a ``:`` after its first character shows the
    user and hides what follows the first ``:`` (``--authenticate
    app:<hidden>``, ``-aapp:<hidden>``), and any other value is hidden whole
    (``_hidden_credentials``, ``_hidden_credentials_glued``); glued after ``=``
    to a long option, the value is hidden whole, as any credential option's.
    An ``acl_user`` option starts a ``user`` line of a server's config: the
    next word is the user name, which is shown, and each word after it up to
    the next long option or command separator is a rule of that user, read
    as a rule of ``ACL SETUSER`` is (``_NEXT_ACL_RULES``), so
    ``redis-server --user app on >VALUE`` shows ``><hidden>``. A
    ``many_secrets`` option takes one secret or more as its next arguments,
    each hidden whole up to the next word that starts with ``-`` or is an
    operator (``_NEXT_SECRETS``), so ``vllm serve m --api-key VALUE VALUE
    --port 8000`` shows ``--api-key <hidden> <hidden> --port 8000``; a value
    glued after ``=`` is its only one, as for any option whose name says
    credential.
    """

    secret: tuple[str, ...] = ()
    credentials: tuple[str, ...] = ()
    joined: tuple[str, ...] = ()
    user_password: tuple[str, ...] = ()
    takes_value: tuple[str, ...] = ()
    runs_command: bool = False
    command: tuple[str, ...] = ()
    sentinel: tuple[str, ...] = ()
    switches: tuple[str, ...] = ()
    acl_user: tuple[str, ...] = ()
    many_secrets: tuple[str, ...] = ()


# The options of the Redis and Valkey clients and benchmarks that take the next argument as
# their value in each of them: host, port, socket, address, database or request count,
# repeat or key-space count, delimiter or value size, database number, user name, and the
# name of a server and the files and ciphers of TLS.
_REDIS_VALUE_OPTIONS: Final = (
    "-h",
    "-p",
    "-s",
    "-u",
    "-n",
    "-r",
    "-d",
    "--dbnum",
    "--user",
    "--sni",
    "--cacert",
    "--cacertdir",
    "--cert",
    "--key",
    "--tls-ciphers",
    "--tls-ciphersuites",
)
# The other options of the clients that take a value: time limit, interval, delimiter, the
# files of a dump and a script, a key pattern and count, the counts of the pipe and memory
# modes, the tag of the argument read from the input (``-X``), whether to show pushed
# messages, the sample size of the LRU test, and the cursor and the count of the largest keys
# of the key statistics. ``--askpass`` and ``--cluster-from-askpass`` take no value: they
# ask for the password. So the option parsing of ``src/redis-cli.c`` says
# ([Redis 8.0.0](https://github.com/redis/redis/blob/8.0.0/src/redis-cli.c)), and of
# ``src/valkey-cli.c`` ([Valkey 8.1.1](https://github.com/valkey-io/valkey/blob/8.1.1/src/valkey-cli.c)),
# which has no ``--cursor`` or ``--top`` and refuses them.
_REDIS_CLIENT: Final = ClientOptions(
    secret=("-a",),
    takes_value=(
        *_REDIS_VALUE_OPTIONS,
        "-t",
        "-i",
        "-D",
        "-X",
        "--rdb",
        "--functions-rdb",
        "--eval",
        "--pattern",
        "--quoted-pattern",
        "--count",
        "--pipe-timeout",
        "--memkeys-samples",
        "--intrinsic-latency",
        "--show-pushes",
        "--lru-test",
        "--cursor",
        "--top",
    ),
    switches=("--askpass", "--cluster-from-askpass"),
)
# The other options of the benchmarks that take a value: clients, pipeline, tests, keep alive,
# threads, precision and the seed of the random keys.
_REDIS_BENCHMARK: Final = ClientOptions(
    secret=("-a",),
    takes_value=(
        *_REDIS_VALUE_OPTIONS,
        "-c",
        "-P",
        "-t",
        "-k",
        "--threads",
        "--precision",
        "--seed",
    ),
)
_MYSQL_CLIENT: Final = ClientOptions(joined=("-p",))
# The servers of Redis and Valkey and their Sentinels. A server reads each ``--NAME`` of its
# command line and the words after it as a line of its config file, and ``--sentinel``
# alone starts it as a Sentinel, as the usage text and ``main`` of ``src/server.c`` say
# ([Redis 7.4.0](https://github.com/redis/redis/blob/7.4.0/src/server.c),
# [Valkey 8.0.0](https://github.com/valkey-io/valkey/blob/8.0.0/src/server.c)). So
# ``--sentinel auth-pass mymaster VALUE`` gives a Sentinel the password of a master. The
# passwords a server takes by a name that says so (``--requirepass``, ``--masterauth``,
# ``--primaryauth``) are hidden by that name. ``--user NAME RULE ...`` is the ``user`` line
# of the config, whose rules give the user's passwords as ``ACL SETUSER`` does
# (``user worker on >VALUE ~* +@all`` in ``redis.conf`` and ``sentinel.conf``).
_REDIS_SERVER: Final = ClientOptions(sentinel=("--sentinel",), acl_user=("--user",))
# ``memtier_benchmark -a`` and ``--authenticate`` take a password, or ``user:password``: the
# text before the first ``:`` is the user, and a value that starts with ``:`` is a password
# alone (``redis_protocol::authenticate`` in ``protocol.cpp`` and the help text of
# ``memtier_benchmark.cpp``,
# [memtier_benchmark 2.1.4](https://github.com/RedisLabs/memtier_benchmark/blob/2.1.4/protocol.cpp)).
_MEMTIER_BENCHMARK: Final = ClientOptions(
    credentials=("-a", "--authenticate"), command=("--command",)
)
# The OpenAI-compatible server of vLLM takes one API key or more after ``--api-key``: the field
# ``FrontendArgs.api_key`` of ``vllm/entrypoints/common/cli_args.py`` is a list, which
# ``collection_to_kwargs`` of ``vllm/engine/arg_utils.py`` gives ``nargs="+"``, and the parser of
# ``vllm/utils/argparse_utils.py`` reads ``--api_key`` as ``--api-key``, in
# [vLLM 0.33.0](https://github.com/vllm-project/vllm/tree/v0.33.0). The server is started as
# ``vllm serve`` or as the module ``vllm.entrypoints.openai.api_server``.
_VLLM_SERVER: Final = ClientOptions(many_secrets=("--api-key", "--api_key"))
# The clients whose password options are hidden, by the name of the program. A
# program is found by its name at the start of any word, also after a path
# (``/usr/bin/redis-benchmark``), after a command separator (``true;mysql``) or
# as the command that ``env``, ``sudo``, ``docker exec`` or a shell runs; its
# options apply up to the end of its command: an operator a shell reads, never one inside
# a longer argument or in quotes. The text of a command substitution is a command of its own.
CLIENT_PASSWORD_OPTIONS: Final[Mapping[str, ClientOptions]] = {
    "redis-benchmark": _REDIS_BENCHMARK,
    "redis-cli": _REDIS_CLIENT,
    "redis-sentinel": _REDIS_SERVER,
    "redis-server": _REDIS_SERVER,
    "valkey-benchmark": _REDIS_BENCHMARK,
    "valkey-cli": _REDIS_CLIENT,
    "valkey-sentinel": _REDIS_SERVER,
    "valkey-server": _REDIS_SERVER,
    "memtier_benchmark": _MEMTIER_BENCHMARK,
    "mysql": _MYSQL_CLIENT,
    "mysqlslap": _MYSQL_CLIENT,
    "mysqladmin": _MYSQL_CLIENT,
    "mariadb": _MYSQL_CLIENT,
    "mariadb-slap": _MYSQL_CLIENT,
    "mariadb-admin": _MYSQL_CLIENT,
    "sshpass": ClientOptions(secret=("-p",), takes_value=("-f", "-d", "-P"), runs_command=True),
    "ab": ClientOptions(user_password=("-A", "-P")),
    "vllm": _VLLM_SERVER,
    "vllm.entrypoints.openai.api_server": _VLLM_SERVER,
}
# What ends one command of a shell text and starts the next: ``;``, ``&``,
# ``|``, a bracket or a backquote. The ``&`` of a redirection (``2>&1``, ``&>out``) ends none.
_COMMAND_SEPARATOR = re.compile(r"(?<![<>])&(?!>)|[;|()`]")


def _client_named(plain: str) -> str:
    """Return the client a word names, after any command separator and path, or ``""``."""
    last = _COMMAND_SEPARATOR.split(plain)[-1].lstrip("$")
    name = last.rpartition("/")[2]
    return name if name in CLIENT_PASSWORD_OPTIONS else ""


# The operators of a shell that end a command, as a word of an argument list that a shell
# joins may be one whole (``ssh HOST tool ';' ./bench``). An operator inside a longer word is
# part of that word: ``mysql -e 'select 1; select 2' -p...`` is one command.
_OPERATOR_WORDS: Final = frozenset((";", "&", "&&", "|", "||", ";;", ";&", ";;&", "|&"))


def _next_rule(plain: str, program: str = "") -> str:
    """Say how the argument after this one is shown: hidden whole, its password hidden, or as is.

    ``program`` is the client whose options apply here, or ``""``.
    """
    client = CLIENT_PASSWORD_OPTIONS.get(program)
    if client is not None and plain in client.switches:
        return ""
    # A client's option that takes ``user:password`` shows the user, though its name says
    # credential (``memtier_benchmark --authenticate``).
    if client is not None and plain in client.credentials:
        return _NEXT_CREDENTIALS
    # A server's ``--user`` takes a user name and that user's rules, not ``user:password``.
    if client is not None and plain in client.acl_user:
        return _NEXT_ACL_USER
    # A password glued to a client's option (``-aVALUE``) ends with its word, whatever words
    # the value holds: the next word is no value of it.
    if client is not None and _hidden_client_glued(plain, program) is not None:
        return ""
    # A client's option that takes several keys hides each of them, though its name says
    # credential (``vllm serve --api-key``).
    if client is not None and plain in client.many_secrets:
        return _NEXT_SECRETS
    if _names_credential(plain):
        return _NEXT_SECRET
    if plain in USER_PASSWORD_OPTIONS:
        return _NEXT_PASSWORD
    if client is not None:
        if plain in client.secret:
            return _NEXT_SECRET
        if plain in client.user_password:
            return _NEXT_PASSWORD
        if plain in client.command:
            return _NEXT_COMMAND
    return ""


def _hidden_client_glued(word: str, program: str) -> str | None:
    """Hide the value a client's password option has glued to it, or ``None``.

    ``-aVALUE`` and ``--authenticate=VALUE`` show ``-a<hidden>`` and
    ``--authenticate=<hidden>``, ``mysql -pVALUE`` shows ``-p<hidden>`` and
    ``ab -Auser:VALUE`` shows ``-Auser:<hidden>``; the quotes around the
    word are kept.
    """
    client = CLIENT_PASSWORD_OPTIONS.get(program)
    if client is None:
        return None
    quote = _quoted_whole(word)
    plain = _plain_word(word)
    for option in (*client.secret, *client.joined):
        glued = option + "=" if option.startswith("--") else option
        if plain.startswith(glued) and len(plain) > len(glued):
            return f"{quote}{glued}{HIDDEN}{quote}"
    credentials = _hidden_credentials_glued(word, program)
    if credentials is not None:
        return credentials
    for option in client.user_password:
        value = plain[len(option) :]
        if plain.startswith(option) and ":" in value:
            return f"{quote}{option}{value.partition(':')[0]}:{HIDDEN}{quote}"
    return None


def _hidden_value_glued(word: str, program: str) -> str | None:
    """Hide a client's password glued to its option where an ordinary name's value starts.

    Read with the options of the client ``program``, ``MADE_UP_FLAGS=-pVALUE``
    shows ``MADE_UP_FLAGS=-p<hidden>`` (``mysql``) and
    ``MADE_UP_FLAGS=-aVALUE`` shows ``MADE_UP_FLAGS=-a<hidden>``
    (``redis-cli``), as ``_hidden_client_glued`` hides the option alone; the
    quotes around the word or around the value are kept
    (``MADE_UP_FLAGS="-p<hidden>"``). A value that holds a blank is read word
    by word (``_hidden_quoted_value``), where this reads its first word.
    ``None`` when the word gives no ordinary name a value
    (``_ordinary_value_start``) or its value starts with no such option.
    """
    if program not in CLIENT_PASSWORD_OPTIONS:
        return None
    quote = _quoted_whole(word)
    inner = word[1:-1] if quote else word
    at = _ordinary_value_start(inner)
    if at is None or _SPACE.search(inner, at) is not None:
        return None
    shown = _hidden_client_glued(inner[at:], program)
    return None if shown is None else quote + inner[:at] + shown + quote


def _hidden_credentials_glued(word: str, program: str) -> str | None:
    """Hide the value glued to a client's short ``credentials`` option, or return ``None``.

    ``-aapp:VALUE`` shows the user, ``-aapp:<hidden>``, and a password alone
    is hidden whole (``_credentials_shown``). The quotes around the word are
    kept. A value glued after ``=`` to a long option
    (``--authenticate=app:VALUE``) is no business of this rule: the reading of
    a program's text (``_hidden_code``) hides it whole first, as the value of
    any option whose name says credential.
    """
    client = CLIENT_PASSWORD_OPTIONS.get(program)
    if client is None:
        return None
    quote = _quoted_whole(word)
    plain = _plain_word(word)
    for option in client.credentials:
        if not option.startswith("--") and plain.startswith(option) and len(plain) > len(option):
            return f"{quote}{option}{_credentials_shown(plain[len(option) :])}{quote}"
    return None


def _hidden_command_glued(word: str, program: str) -> str | None:
    """Read the command glued to a client's ``command`` option as that client's own, or ``None``.

    ``--command=AUTH VALUE`` shows ``--command=AUTH <hidden>``: the text after
    the ``=`` is read as ``_hidden_words`` reads a command of the client
    (``command``). The quotes around the word, or around the text after the
    ``=``, are kept.
    """
    client = CLIENT_PASSWORD_OPTIONS.get(program)
    if client is None or not client.command:
        return None
    quote = _quoted_whole(word)
    inner = word[1:-1] if quote else word
    for option in client.command:
        head = option + "="
        if inner.startswith(head):
            rest = inner[len(head) :]
            rest_quote = _quoted_whole(rest)
            text = rest[1:-1] if rest_quote else rest
            shown = _hidden_words(text, program, command=True)
            return f"{quote}{head}{rest_quote}{shown}{rest_quote}{quote}"
    return None


# The fixed arguments of ``MIGRATE`` before its options: host, port, key, database and time
# limit. ``AUTH`` and ``AUTH2`` after them give a password.
_MIGRATE_ARGUMENTS: Final = 5
# The words after ``SENTINEL`` that set settings, ``SET <master> name value ...`` and
# ``CONFIG SET name value ...``, as the help text of ``src/sentinel.c`` gives them
# ([Redis 7.4.0](https://github.com/redis/redis/blob/7.4.0/src/sentinel.c)). The walk holds
# ``CONFIG SET`` as one subcommand once it has read ``SET``.
_SENTINEL_CONFIG_SET: Final = "config set"
_SENTINEL_SETTINGS: Final[tuple[str, ...]] = ("set", _SENTINEL_CONFIG_SET)


# A run of command separators at the end of a word, as in ``VALUE;``: shown after the value.
_TRAILING_SEPARATORS = re.compile(r"[;&|]+\Z")
# What ends a command at the end of a word: a separator, or the ``)`` or backquote that
# closes a command inside a shell text, as in ``(... VALUE)``. In a shell text a ``)`` or
# backquote glued to a hidden value is shown after it (``_closing_tail``); in an argument, or a
# text whose quotes are already gone, it is hidden with the value, as it may be part of it.
_COMMAND_END = re.compile(r"[;&|)`]+\Z")
# The word after a group of the short options of a shell of ``SHELLS`` that
# holds ``c`` and is no option is the text the shell runs, also when ``--`` or
# other options come between: ``sh -ce TEXT``, ``bash -c -e TEXT`` and
# ``sh -c -- TEXT``.
# A shell's options that take the next argument as their value, as ``-o pipefail``.
_SHELL_VALUE_OPTIONS: Final[tuple[str, ...]] = ("-o", "+o", "-O", "+O")
# A group of a shell's short options that holds ``c``.
_SHELL_TEXT_GROUP = re.compile(r"-[A-Za-z]*c[A-Za-z]*")


@dataclass(frozen=True)
class TextRunner:
    """A program that runs commands given to it as texts, read when it starts a command.

    Its operands, the arguments that are no option and no value of one of
    its ``takes_value`` options, are command texts once the first ``before``
    operands are read (``ssh``'s host, ``tmux``'s command). With
    ``commands`` the first operand must be one of them, or no operand is a
    text (``tmux new`` runs one, ``tmux ls`` none). With ``rest`` every word
    after the first text belongs to the command, options too. A word of
    ``ends`` ends the texts: what follows is no command (``parallel ... :::``).
    The program runs its texts in a shell, where an operator outside quotes
    ends a command, unless one of its ``no_shell`` options comes first
    (``watch -x``, ``hyperfine -N``), alone or in a group of short options
    (``watch -tx``), or the value of one of its ``shell_options`` is
    ``none`` (``hyperfine --shell none``). With ``options_after`` it reads
    options after its texts too, so such an option anywhere in the words
    read turns its shell off (``hyperfine 'TEXT' -N``). Run with no shell,
    each word of its command is one argument of the program, blanks and
    all, unless it ``splits`` each text into words itself, as ``hyperfine
    -N`` does. With ``spaced`` a command given whole as one argument runs
    in a shell, and a command given as several arguments with none, as
    ``tmux`` runs them; a text that holds a blank is read as a shell text
    either way. Its ``flags`` are options of its own that take no value,
    alone or last in a group of short options, though their name is that
    of an option before a program's code (``watch -c`` is ``--color``).
    """

    takes_value: tuple[str, ...] = ()
    before: int = 0
    commands: tuple[str, ...] = ()
    rest: bool = False
    ends: tuple[str, ...] = ()
    no_shell: tuple[str, ...] = ()
    shell_options: tuple[str, ...] = ()
    spaced: bool = False
    options_after: bool = False
    splits: bool = False
    flags: tuple[str, ...] = ()


# The options of OpenSSH's ``ssh`` that take the next argument as their value.
_SSH_VALUE_OPTIONS: Final = tuple(f"-{letter}" for letter in "BbcDEeFIiJLlmOoPpQRSWw")
# The programs that run a command text, by the last part of their path, as their own
# manuals give their options: OpenSSH's ``ssh`` runs the words after the host on that host,
# ``hyperfine`` runs each command it is given, ``watch`` and GNU ``parallel`` run the words
# of their command (``parallel`` up to ``:::`` or ``::::``), and ``tmux`` runs the command
# of a new or respawned session, window or pane. Each runs its commands in a shell but where
# its manual names a way to run them with none: ``watch -x`` / ``--exec``, ``hyperfine -N`` /
# ``--shell=none``, ``parallel -q`` / ``--quote``, and ``tmux`` given a command as several
# arguments (tmux(1) at tag 3.5a: a single argument is passed to ``/bin/sh -c``).
COMMAND_TEXT_RUNNERS: Final[Mapping[str, TextRunner]] = {
    "ssh": TextRunner(takes_value=_SSH_VALUE_OPTIONS, before=1, rest=True),
    "hyperfine": TextRunner(
        takes_value=("-S", "--shell"),
        no_shell=("-N", "--shell=none", "-Snone"),
        shell_options=("-S", "--shell"),
        options_after=True,
        splits=True,
    ),
    "watch": TextRunner(
        takes_value=("-n", "--interval"), rest=True, no_shell=("-x", "--exec"), flags=("-c",)
    ),
    "parallel": TextRunner(
        rest=True, ends=(":::", ":::+", "::::", "::::+"), no_shell=("-q", "--quote")
    ),
    "tmux": TextRunner(
        takes_value=("-c", "-e", "-F", "-f", "-L", "-l", "-n", "-S", "-s", "-T", "-t", "-x", "-y"),
        before=1,
        commands=(
            "new",
            "new-session",
            "new-window",
            "neww",
            "split-window",
            "splitw",
            "respawn-window",
            "respawnw",
            "respawn-pane",
            "respawnp",
        ),
        rest=True,
        spaced=True,
    ),
}
# Options whose value is a command text, given as the next argument or glued to the option
# (``--command=TEXT``, ``-STEXT``), of the program that starts a command: ``gcloud ...
# --command``, ``env -S`` / ``--split-string``, the commands ``hyperfine`` runs around the
# ones it times (``-s`` / ``--setup``, ``-p`` / ``--prepare``, ``-C`` / ``--conclude``,
# ``-c`` / ``--cleanup``) and its ``--reference``, as its source at v1.19.0 gives them, and
# the ``-c`` / ``--command`` of ``su``,
# ``runuser``, ``flock`` and ``script``, which hand their text to a shell, and of ``fish``.
TEXT_OPTIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "gcloud": ("--command",),
    "env": ("-S", "--split-string"),
    "hyperfine": (
        "-s",
        "--setup",
        "-p",
        "--prepare",
        "-C",
        "--conclude",
        "-c",
        "--cleanup",
        "--reference",
    ),
    "su": ("-c", "--command"),
    "runuser": ("-c", "--command"),
    "flock": ("-c", "--command"),
    "script": ("-c", "--command"),
    "fish": ("-c", "--command"),
}
# The short options of a program of ``TEXT_OPTIONS`` that take no value, so a group of short
# options may hold them before the option of a text and its text glued to it: ``hyperfine
# -NpTEXT`` is ``-N`` and ``-p TEXT``. Those of hyperfine are ``-N``, ``-i`` and the ``-V`` and
# ``-h`` its parser adds, as its source gives them
# (https://github.com/sharkdp/hyperfine/blob/v1.19.0/src/cli.rs), and ``-S``, which takes no
# value from v2.0.0 on, where it is ``--shell=default``
# (https://github.com/sharkdp/hyperfine/blob/v2.0.0/src/cli.rs): ``-SsTEXT`` is ``-S`` and
# ``-s TEXT`` there. An older hyperfine takes the rest of such a word as the command line of
# its shell, and a value in it is hidden when it is read as a text too.
TEXT_OPTION_FLAGS: Final[Mapping[str, str]] = {"hyperfine": "NiVhS"}
# The programs of ``TEXT_OPTIONS`` whose parser takes one ``=`` between a short option and
# the value glued to it off the value, so ``-s=TEXT`` and ``-Ns=TEXT`` give ``TEXT``: hyperfine,
# whose parser is clap 4.5.20 (its ``parse_short_arg``,
# https://github.com/clap-rs/clap/blob/v4.5.20/clap_builder/src/parser/parser.rs).
_SHORT_EQUALS: Final[frozenset[str]] = frozenset({"hyperfine"})
# The programs of ``TEXT_OPTIONS`` that split the text of their option into words and run
# them with no shell, as GNU ``env -S`` does: an operator in that text is part of a word.
_SPLIT_TEXTS: Final[tuple[str, ...]] = ("env",)
# The names of the programs whose command text a shell runs, and of the shells, longest first.
_SHELL_RUN_ALTERNATIVES: Final = "|".join(
    re.escape(name)
    for name in sorted(
        {*COMMAND_TEXT_RUNNERS, *TEXT_OPTIONS, *SHELLS} - set(_SPLIT_TEXTS),
        key=lambda name: (-len(name), name),
    )
)
# One of those names as a word of a text with its quotes taken out. A text that names none
# holds no command text a shell runs.
_SHELL_RUN_NAMES: Final = re.compile(r"(?<!\w)(?:" + _SHELL_RUN_ALTERNATIVES + r")(?!\w)")
# One of those names anywhere, a word or not: a search with no look behind at its start skips
# quickly to the next place a name could start.
_SHELL_RUN_LETTERS: Final = re.compile(_SHELL_RUN_ALTERNATIVES)


def _names_shell_runner(plain: str) -> bool:
    """Say whether a text with its quotes taken out names a shell or a program that runs one.

    This is whether ``_SHELL_RUN_NAMES`` finds a match: each place one of
    the names starts is tried as a word in turn, so a long text with no name
    in it is passed over at the speed of a plain search.
    """
    at = 0
    while (found := _SHELL_RUN_LETTERS.search(plain, at)) is not None:
        if _SHELL_RUN_NAMES.match(plain, found.start()) is not None:
            return True
        at = found.start() + 1
    return False


# A group of short options, as ``-tx`` or ``-n1``: its letters are options, and one that
# takes a value takes the rest of the group, or the next word when it ends the group.
_OPTION_GROUP: Final = re.compile(r"-[A-Za-z][A-Za-z0-9]+")


def _no_shell_after() -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Return the words that turn a runner's shell off, and the words that name its shell.

    Those are whole words, with their quotes taken out, of each runner of
    ``COMMAND_TEXT_RUNNERS`` that reads options after its texts
    (``TextRunner.options_after``): one of its ``no_shell`` options, a short
    one in a group of a few short options (``-iN``), or one of its
    ``shell_options`` with ``none`` glued to it. The second pattern is one
    of its ``shell_options``, alone or last in such a group, whose value
    ``none`` is the next word.
    """
    spellings: list[str] = []
    named: list[str] = []
    for runner in COMMAND_TEXT_RUNNERS.values():
        if not runner.options_after:
            continue
        for option in runner.no_shell:
            spellings.append(re.escape(option))
            if len(option) == 2:
                spellings.append(f"-[A-Za-z]{{0,3}}{re.escape(option[1])}[A-Za-z]{{0,3}}")
        for option in runner.shell_options:
            if len(option) == 2:
                spellings.append(f"-[A-Za-z]{{0,3}}{re.escape(option[1])}none")
                named.append(f"-[A-Za-z]{{0,3}}{re.escape(option[1])}")
            else:
                spellings.append(f"{re.escape(option)}=none")
                named.append(re.escape(option))
    return re.compile("|".join(spellings)), re.compile("|".join(named))


_NO_SHELL_AFTER, _SHELL_NAMED_AFTER = _no_shell_after()
# Programs whose first operand starts the command they run, with their options that take
# the next argument as their value: ``env`` after its options and assignments; ``taskset``,
# ``numactl``, ``chrt``, ``stdbuf``, ``ionice``, ``nice``, ``nohup``, ``timeout`` and
# ``sudo`` after their options, their assignments and the operand of ``_STARTER_LEADS``, as
# their own manuals give their options (taskset(1), chrt(1) and ionice(1) of util-linux
# 2.42, numactl(8) of numactl 2.0.19, stdbuf(1), nice(1), nohup(1) and timeout(1) of GNU
# coreutils 9.11, and sudo(8) of sudo 1.9.17p2); and each client of
# ``CLIENT_PASSWORD_OPTIONS`` that ``runs_command``. An adjustment ``nice`` takes as
# an option of digits (``nice -10``) starts with ``-`` as any option does.
_COMMAND_STARTERS: Final[Mapping[str, tuple[str, ...]]] = {
    "env": ("-u", "--unset", "-C", "--chdir"),
    "nice": ("-n", "--adjustment"),
    "nohup": (),
    "timeout": ("-k", "--kill-after", "-s", "--signal"),
    "sudo": (
        "-a",
        "--auth-type",
        "-C",
        "--close-from",
        "-c",
        "--login-class",
        "-D",
        "--chdir",
        "-g",
        "--group",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-R",
        "--chroot",
        "-r",
        "--role",
        "-t",
        "--type",
        "-T",
        "--command-timeout",
        "-U",
        "--other-user",
        "-u",
        "--user",
    ),
    "taskset": (),
    "numactl": (
        "-i",
        "--interleave",
        "-w",
        "--weighted-interleave",
        "-m",
        "--membind",
        "-N",
        "--cpunodebind",
        "-C",
        "--physcpubind",
        "-p",
        "--preferred",
        "-P",
        "--preferred-many",
        "--cpubind",
        "--offset",
        "--shmmode",
        "--length",
        "--shmid",
        "--shm",
        "--file",
    ),
    "chrt": ("-T", "--sched-runtime", "-P", "--sched-period", "-D", "--sched-deadline"),
    "stdbuf": ("-i", "--input", "-o", "--output", "-e", "--error"),
    "ionice": ("-c", "--class", "-n", "--classdata", "-p", "--pid", "-P", "--pgid", "-u", "--uid"),
    "time": ("-f", "--format", "-o", "--output"),
}
# The operand a starter of ``_COMMAND_STARTERS`` takes before the command it runs, when the
# operand has this form: the mask of ``taskset``, a bit mask or with ``-c`` a list of CPUs
# (``0x3``, ``0-3,8``), the priority of ``chrt``, which a policy other than ``--fifo`` and
# ``--rr`` may leave out, and the duration of ``timeout``, which is always its first operand
# (``30``, ``1.5m``), so any word is read as it.
_STARTER_LEADS: Final[Mapping[str, re.Pattern[str]]] = {
    "taskset": re.compile(r"(?:0[xX])?[0-9A-Fa-f,:-]+"),
    "chrt": re.compile(r"[0-9]+"),
    "timeout": re.compile(r".+", re.DOTALL),
}


def _text_option(plain: str, options: Sequence[str]) -> bool:
    """Say whether a word is one of the ``options`` of ``TEXT_OPTIONS`` whose text is the next word.

    That is the option itself, or a short one last in a group of short
    options, as ``script -qc`` and ``su -lc`` give ``-c``.
    """
    if plain in options:
        return True
    group = _SHORT_GROUP.fullmatch(plain)
    return group is not None and any(
        len(option) == 2 and not option.startswith("--") and plain.endswith(option[1])
        for option in options
    )


# A group of two or more short options of letters, as ``-qc``.
_SHORT_GROUP: Final = re.compile(r"-[A-Za-z]{2,}")


def _glued_text(plain: str, option: str) -> bool:
    """Say whether a word is an option of ``TEXT_OPTIONS`` with its text glued to it."""
    glued = option + "=" if option.startswith("--") else option
    return plain.startswith(glued) and len(plain) > len(glued)


def _glued_head(plain: str, option: str, program: str) -> str:
    """Return what stands before the text glued to an option of ``TEXT_OPTIONS``, or ``""``.

    That is ``--NAME=`` of a long option and ``-X`` of a short one, or
    ``-X=`` when the program's parser takes that ``=`` off the text
    (``_SHORT_EQUALS``: ``hyperfine -s=TEXT``).
    """
    equals = option.startswith("--") or (
        program in _SHORT_EQUALS and plain.startswith(option + "=") and len(plain) > len(option) + 1
    )
    head = option + "=" if equals else option
    return head if plain.startswith(head) and len(plain) > len(head) else ""


def _glued_group(plain: str, program: str) -> int:
    """Return the length of the group of short options before a text glued to it, or ``0``.

    The group is one or more short options of ``program`` that take no value
    (``TEXT_OPTION_FLAGS``) and then a short option of ``TEXT_OPTIONS`` whose
    text follows it in the same word: ``-NpTEXT`` gives 3, and ``-Np=TEXT``
    gives 4 when the parser takes the ``=`` off the text (``_SHORT_EQUALS``).
    A word that is no such group, or whose text is empty, gives ``0``.
    """
    flags = TEXT_OPTION_FLAGS.get(program, "")
    if not flags or plain[:1] != "-":
        return 0
    at = 1
    while at < len(plain) and plain[at] in flags:
        at += 1
    if at == 1 or at + 1 >= len(plain) or f"-{plain[at]}" not in TEXT_OPTIONS[program]:
        return 0
    if program in _SHORT_EQUALS and plain[at + 1] == "=" and at + 2 < len(plain):
        return at + 2
    return at + 1


def _glued_shown(before: str, shown: str) -> str:
    """Join what stands before a glued text (``--command=``, ``'-S``) to the text as shown.

    A quote that opens the word before the option takes the place of the
    quote that opens the text, so ``'--command=TEXT'`` stays one quoted word.
    """
    quote = before[:1] if before[:1] in _QUOTES else ""
    if quote and shown.startswith(quote):
        return before + shown[1:]
    return before + quote + shown if quote else before + shown


# The options that give a benchmark an axis and its values as the next argument
# (``-a Key=I32``, ``--axis NumKeys=64``), as nvbench takes them, unless a client's own
# options say the option takes a password.
AXIS_OPTIONS: Final[tuple[str, ...]] = ("-a", "--axis")
# Shell builtins that give variables values, whose ``-a`` makes an array
# (``declare -a NAME=...``): their ``-a`` is no axis option.
_DECLARING_BUILTINS: Final[frozenset[str]] = frozenset({"declare", "local", "readonly", "typeset"})
# Words after which a shell reads the next word as the name of a command to run, as
# ``declare`` in ``then declare -a NAME=...`` or ``builtin declare -a NAME=...``.
_COMMAND_LEADS: Final[frozenset[str]] = frozenset(
    {
        "!",
        "builtin",
        "command",
        "do",
        "elif",
        "else",
        "eval",
        "if",
        "then",
        "time",
        "until",
        "while",
    }
)
# The reserved words of a shell after which the next word starts a command, as ``eval`` in
# ``{ eval ...; }`` or ``if true; then eval ...; fi`` does; ``time`` is a program of
# ``_COMMAND_STARTERS``, its ``-p`` passed over.
_SHELL_LEAD_WORDS: Final[frozenset[str]] = frozenset(
    {"!", "{", "do", "elif", "else", "if", "then", "until", "while"}
)
# An axis named ``Key`` or ``Keys``, maybe with flags, and its values: shown as typed after
# an axis option.
_AXIS_KEY = re.compile(r"keys?(?:\[[^\]\s=]*\])?=\S*", re.IGNORECASE)
# The name of the axis ``Key`` or ``Keys`` and its ``=`` in an axis value, after any quotes.
_AXIS_NAME = re.compile(r"keys?(?:\[[^\]\s=]*\])?=", re.IGNORECASE)


def _axis_value(word: str, axis: bool, program: str = "") -> bool:
    """Say whether a word names the axis ``Key`` or ``Keys`` and its values after an axis option.

    After an axis option (``axis``) the word is the axis (``-a Key=I32``); it
    may also be glued to the option (``--axis=Key=I32``, ``-aKeys=4``) where
    the option takes no password of the client ``program`` (``redis-cli
    -aVALUE`` gives one). The word is read without its quotes and
    backslashes, so an axis value in escaped quotes, as ``\\"Key=I32\\"`` in
    a text in double quotes, is one too.
    """
    plain = _plain_word(word).replace("\\", "")
    if axis:
        return _AXIS_KEY.fullmatch(plain) is not None
    for option in AXIS_OPTIONS:
        glued = option + "=" if option.startswith("--") else option
        if (
            plain.startswith(glued)
            and _AXIS_KEY.fullmatch(plain, len(glued)) is not None
            and not _next_rule(option, program)
        ):
            return True
    return False


def _after_axis_option(text: str, at: int) -> bool:
    """Say whether the name at ``at`` of a text gives the axis ``Key`` its values.

    That is so when the name opens the word after an axis option on the same
    line, at any depth of quotes: ``-a Key=I32``, ``-a 'Key=I32'``, ``--opts
    '-a Key=I32'``, ``sh -c "bench -a \\"Key=I32\\""``. Quotes and escapes may
    stand around either word, and a blank after a backslash joins the two
    words into one. The rule of a client whose ``-a`` takes a password is left
    to the words of the text (``_hidden_words``), which hide that password.
    """
    if _AXIS_KEY.match(text, at) is None:
        return False
    start = at
    while start > 0 and text[start - 1] in "'\"\\":
        start -= 1
    end = start
    while end > 0 and text[end - 1] in " \t":
        end -= 1
    if end in (start, 0) or text[end - 1] == "\\":
        return False
    begin = end
    while begin > 0 and not text[begin - 1].isspace():
        begin -= 1
    return text[begin:end].strip("'\"\\") in AXIS_OPTIONS and not _declared_before(text, begin)


# What may stand right before the first word of a command glued to it: a quote that opens
# a shell text, a bracket, a backquote, ``$(``, ``!`` or an operator, as in ``x=$(declare``.
_COMMAND_OPENERS: Final = "'\"\\({`$!;&|"
# The last character of a word after which a command starts: an operator or a bracket.
_COMMAND_ENDS: Final = ";&|({`"


def _declared_before(text: str, begin: int) -> bool:
    """Say whether the option that starts at ``begin`` of a text is one of a declaring builtin.

    The words right before it that start with ``-`` or ``+`` are options of
    the same command; the word before them names a builtin of
    ``_DECLARING_BUILTINS`` (``declare -g -a``) where a command starts: at
    the start of the text or of a line, glued after a quote, a bracket or an
    operator (``_COMMAND_OPENERS``), or after an operator, a word of
    ``_COMMAND_LEADS`` or an assignment. So ``local`` given to an option
    (``--mode local -a Key=I32``) leaves the axis rule as it is.
    """
    start = end = begin
    while True:
        end = start
        while end > 0 and text[end - 1] in " \t":
            end -= 1
        start = end
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        if start == end:
            return False
        if not text[start:end].strip("'\"\\").startswith(("-", "+")):
            break
    word = text[start:end]
    glued = max(word.rfind(one) for one in _COMMAND_OPENERS)
    if word[glued + 1 :] not in _DECLARING_BUILTINS:
        return False
    if glued >= 0:
        return True
    before = start
    while before > 0 and text[before - 1] in " \t":
        before -= 1
    if before == 0 or text[before - 1] == "\n":
        return True
    first = before
    while first > 0 and not text[first - 1].isspace():
        first -= 1
    previous = text[first:before]
    return (
        previous[-1] in _COMMAND_ENDS
        or previous.strip("'\"\\") in _COMMAND_LEADS
        or _VARIABLE_ASSIGNED.match(previous) is not None
    )


def _hidden_axis_value(word: str) -> str:
    """Hide the credentials an axis value holds after the name of the axis ``Key``.

    ``Key=I32,TOKEN=VALUE`` shows ``Key=I32,TOKEN=<hidden>``: only the axis
    ``Key`` keeps its values.
    """
    name = _AXIS_NAME.search(word)
    if name is None:
        return _hidden_code_here(word)
    return word[: name.end()] + _hidden_code_here(word[name.end() :])


class _JoinedCommand:
    """Find where the commands start in the command a runner joins from its words.

    ``ssh``, ``watch`` and ``parallel`` join their words with blanks into one
    command that a shell runs (``COMMAND_TEXT_RUNNERS``), so a command
    starts there as in any shell text: at the first word, after an operator
    (``&&``, ``;``, ``|``) or a ``(``, after the assignments that lead it,
    after the options of a program of ``_COMMAND_STARTERS`` or of a client
    that ``runs_command`` and the operand of ``_STARTER_LEADS``, and after
    the options and the first operand (a host) of a runner of its own, as
    in ``ssh HOST taskset -c 0 hyperfine ...`` or ``ssh JUMP ssh HOST
    hyperfine ...``.
    """

    def __init__(self) -> None:
        self.start = True
        self.starter = ""
        self.value = self.lead = False
        self.runner: TextRunner | None = None
        self.operands = 0

    def restart(self) -> None:
        """Start a command: the next word that leads nothing names its program."""
        self.start = True
        self.starter = ""
        self.value = self.lead = False
        self.runner = None
        self.operands = 0

    def program(self, plain: str) -> str | None:
        """Take in one word, as the shell reads it; return the program it names, or ``None``."""
        runner = self.runner
        if runner is not None:
            skipped, self.value = self.value, plain in runner.takes_value
            if skipped or plain.startswith("-"):
                return None
            if self.operands < runner.before:
                self.operands += 1
                return None
            self.restart()
        if not self.start:
            return None
        if self.starter:
            skipped, self.value = self.value, plain in _COMMAND_STARTERS.get(self.starter, ())
            client = CLIENT_PASSWORD_OPTIONS.get(self.starter)
            if client is not None and plain in client.takes_value:
                self.value = True
            if skipped or plain.startswith("-") or _VARIABLE_ASSIGNED.match(plain):
                return None
            lead = _STARTER_LEADS.get(self.starter)
            if lead is not None and not self.lead and lead.fullmatch(plain):
                self.lead = True
                return None
        elif _VARIABLE_ASSIGNED.match(plain) or plain in _SHELL_LEAD_WORDS:
            return None
        name = plain.rpartition("/")[2]
        self.restart()
        self.start = False
        client = CLIENT_PASSWORD_OPTIONS.get(name)
        nested = COMMAND_TEXT_RUNNERS.get(name)
        if name in _COMMAND_STARTERS or (client is not None and client.runs_command):
            self.start, self.starter = True, name
        elif nested is not None and nested.rest:
            self.runner = nested
        return name


class _CommandWalk:
    """What the words read so far say about the next one.

    It holds the rule for the next word (``_next_rule``), the client whose
    options apply (``CLIENT_PASSWORD_OPTIONS``), whether the next word is
    the value of an option, whether it names a setting, and whether it is
    the command of a client of ``DATA_SET_CLIENTS``: only the words read
    since that client are its options and their values, on one line and
    with no separator. With ``data_sets`` false a ``SET`` there still starts
    a setting, while ``AUTH`` and the other commands below are read as they
    are anywhere else; with ``command`` and ``data_sets`` the first word read
    is one, as in the text of a client's ``command`` option. In the client's
    command, ``AUTH`` gives a password, after a user name when another word
    follows it (``AUTH [user] password``); so does ``AUTH`` after the
    protocol version of ``HELLO``, with a user name, and ``AUTH`` or ``AUTH2``, with a user
    name, after the fixed arguments of ``MIGRATE``. ``CONFIG SET`` takes
    several settings, each name followed by its value, and the value of each
    credential setting is hidden (``_names_secret_setting``); ``ACL SETUSER``
    loses the passwords and hashes of its rules (``_NEXT_ACL_RULES``). The
    password is hidden whole and the user name is shown.
    It also holds whether a word is a command text (``text``): the word after
    ``-c`` alone or at the end of a group of options (``sh -c``, ``bash
    -lc``, ``python -c``), the text of a shell after a group that holds
    ``c`` (``SHELLS``), an operand of a program of ``COMMAND_TEXT_RUNNERS``
    and the value of an option of ``TEXT_OPTIONS``. Those programs are read
    where a command starts: its first word, after a separator or a line
    break, after the assignments that lead it, or as the command that
    ``env``, ``sshpass`` or a program of ``_COMMAND_STARTERS`` runs, as
    ``taskset -c 0-3 ssh HOST TEXT``. ``public_command``, ``public_words``,
    ``hashed_argv`` and ``_hidden_words`` read their words through it.
    ``ahead`` holds every word the walk is to read, the text or the
    argument list, so an option that a runner reads after its texts
    (``TextRunner.options_after``) counts from its first text on.
    """

    def __init__(
        self,
        program: str = "",
        *,
        data_sets: bool = True,
        command: bool = False,
        ahead: str | Sequence[str] = "",
        split: bool = False,
    ) -> None:
        # Whether the words were split out of a shell text with its operators taken out and
        # its quotes removed, so that no word is an operator: a ``;`` there was quoted.
        self.split = split
        self.program = program
        self.rule = ""
        # Whether the rule has hidden a value since the last word read.
        self.taken = False
        self.value = False
        self.setting = False
        # Whether the word just read is a word of ``SECRET_SETTING_WORDS``, so a ``set`` next
        # sets a secret.
        self.secret_word = False
        self.data_sets = data_sets
        self.data_command = data_sets and command
        self.axis = False
        # Whether the next word is the value of a credential-like name, which, when it is an
        # Authorization scheme word, has the token after it (``AUTH_SCHEME_WORDS``).
        self.scheme = False
        # Whether the command runs a shell builtin of ``_DECLARING_BUILTINS``.
        self.declaring = False
        # The client's command once read, as ``auth`` or ``migrate``, the first word after it,
        # as ``set`` after ``config``, and the count of the words after it. A word a shell may
        # split into any number of words leaves the turn of its names and values unknown.
        self.client_command = ""
        self.subcommand = ""
        self.command_words = 0
        self.pairs_unknown = False
        # Whether the word before was a server's ``sentinel`` option, so this one names the
        # setting of a line of a Sentinel's config.
        self.sentinel_line = False
        # The command texts: whether the next word starts a command, the program that
        # started it, its operands so far, and the options whose value comes next.
        self.start = True
        self.leader = ""
        self.operands = 0
        self.leader_value = False
        self.all_texts = False
        self.starter = ""
        self.starter_value = False
        # The program of ``TEXT_OPTIONS`` that starts a command a runner of
        # ``COMMAND_TEXT_RUNNERS`` is given in words of its own (``hyperfine`` in ``ssh HOST
        # hyperfine --setup=TEXT``, or in ``ssh HOST taskset -c 0 hyperfine --setup=TEXT``):
        # its options of a text are read in the runner's later words as in its own
        # (``_text_program``). ``joined`` finds where those words start a command.
        self.runs = ""
        self.joined = _JoinedCommand()
        # Whether the starter's operand of ``_STARTER_LEADS`` is read.
        self.starter_lead = False
        # Whether the next word names the function that ``function`` starts.
        self.function_name = False
        self.next_text = False
        self.next_shell = False
        self.shell = False
        self.shell_text = False
        self.shell_value = False
        # Whether the program that started the command runs its texts with no shell, and
        # whether the next word is the value of its option that names the shell.
        self.unshelled = False
        self.shell_named = False
        # The words to be read, and whether one of them is a word of ``_NO_SHELL_AFTER``,
        # read when a runner that reads options after its texts starts a command.
        self.ahead = ahead
        self.unshelled_ahead: bool | None = None
        # Whether another word of the same command follows the word being read, as
        # ``shown_next`` was told, or ``None`` when that is not known.
        self.followed: bool | None = None
        # Whether the next word is the file of a redirection that stood alone (``>`` ``out``).
        self.redirect_file = False

    def _no_shell_ahead(self) -> bool:
        """Say whether a word to be read turns off the shell of a runner that reads it late.

        Only a whole word counts, or a word that names the shell and the
        word ``none`` after it: a ``-N`` inside a text, as the ``-N`` of
        ``hyperfine 'ssh -N HOST true'``, is a word of that text's command.
        """
        if self.unshelled_ahead is None:
            if isinstance(self.ahead, str):
                words = [found.group(0) for found in _SHELL_WORD.finditer(self.ahead)]
            else:
                words = list(self.ahead)
            plain = [_plain_word(word) for word in words]
            self.unshelled_ahead = any(
                _NO_SHELL_AFTER.fullmatch(word) is not None
                or (
                    _SHELL_NAMED_AFTER.fullmatch(word) is not None
                    and plain[k + 1 : k + 2] == ["none"]
                )
                for k, word in enumerate(plain)
            )
        return self.unshelled_ahead

    def _argument_words(self) -> bool:
        """Say whether each word of the command is one argument its runner passes as it stands.

        That is so when the runner runs the command with no shell and does
        not split its texts (``TextRunner.splits``), as ``watch -x`` does,
        and for each word after the first of a ``spaced`` runner's command.
        """
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if runner is None:
            return False
        if self.unshelled:
            return not runner.splits
        return runner.spaced and self.all_texts

    def end_line(self) -> None:
        """End the command at a line break: no client's command and no setting goes on."""
        self.redirect_file = False
        self.data_command = False
        self.setting = False
        self.client_command = ""
        self.subcommand = ""
        self.command_words = 0
        self.pairs_unknown = False
        self.secret_word = False
        self.sentinel_line = False
        if self.rule in (
            _NEXT_SETTING_VALUES,
            _NEXT_SECRET_NAME,
            _NEXT_AUTH,
            _NEXT_USER,
            _NEXT_ACL_RULES,
            _NEXT_ACL_USER,
            _NEXT_SECRETS,
        ):
            self.rule = ""
            self.value = False
        self.new_command()

    def new_command(self) -> None:
        """Start a command: the next word that is no assignment names its program."""
        self.start = True
        self.leader = self.starter = self.runs = ""
        self.operands = 0
        self.leader_value = self.all_texts = self.starter_value = self.starter_lead = False
        self.function_name = False
        self.next_text = self.next_shell = False
        self.shell = self.shell_text = self.shell_value = False
        self.unshelled = self.shell_named = False
        self.declaring = False

    def skip(self) -> None:
        """Take in a word that is no argument of the command, as the value of a flag."""
        self.rule, self.value, self.next_text, self.next_shell = "", False, False, False
        self.axis = self.secret_word = False

    def waiting(self) -> bool:
        """Say whether the next word is the value of an option or a command text."""
        return bool(self.rule) or self.value or self.next_text or self.shell_text

    def _text_program(self) -> str:
        """Return the program whose options of a text (``TEXT_OPTIONS``) the next word may be.

        That is the program that started the command, or else the one that
        starts the command its runner is given in words of its own
        (``runs``).
        """
        return self.leader if self.leader in TEXT_OPTIONS else self.runs

    def text(self, word: str) -> bool:
        """Say whether a word, not yet read, is a command text, read as the text after ``-c`` is."""
        if self.next_text:
            return True
        if not self.shell_text and not self.leader:
            return False
        plain = _plain_word(word)
        if self.shell_text and not self.shell_value and not plain.startswith(("-", "+")):
            return True
        program = self._text_program()
        if any(_glued_text(plain, option) for option in TEXT_OPTIONS.get(program, ())):
            return True
        if _glued_group(plain, program):
            return True
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if runner is None or self.leader_value or plain in runner.ends:
            return False
        if self.all_texts:
            return True
        return not plain.startswith("-") and self.operands >= runner.before

    def code(self, word: str) -> bool:
        """Say whether a word, not yet read, is a command text read as a program's text.

        That is every command text (``text``) but a word that its runner
        passes to the program as one argument (``_argument_words``), which is
        read as any argument is: the text after ``-c`` and the text of a
        shell stay command texts there too.
        """
        if not self.next_text and not self.shell_text and not self.leader:
            return False
        plain = _plain_word(word)
        shell_text = self.shell_text and not self.shell_value and not plain.startswith(("-", "+"))
        if self._argument_words() and not self.next_text and not shell_text:
            return False
        return self.text(word)

    def reset(self) -> None:
        """Start a new command, as after ``;`` or ``&&``: no client, rule or setting goes on."""
        self.end_line()
        self.program = ""
        self.rule = ""
        self.value = False
        self.axis = False

    def shell_word(self, word: str) -> bool:
        """Say whether a word, not yet read, is a command text whose words end as a shell's do.

        That is every command text (``text``) but the text after ``-c`` of a
        program that is no shell, as ``python -c``: the text of a shell, an
        operand of a program of ``COMMAND_TEXT_RUNNERS`` and the value of an
        option of ``TEXT_OPTIONS``. A word that its runner passes to the
        program as one argument (``_argument_words``) is none.
        """
        if not self.next_text and not self.shell_text and not self.leader:
            return False
        plain = _plain_word(word)
        if self.shell_text and not self.shell_value and not plain.startswith(("-", "+")):
            return True
        if self.next_text:
            return self.next_shell
        if self._argument_words():
            return False
        return self.text(word)

    def shell_run(self, word: str) -> bool:
        """Say whether a word, not yet read, is a command text that a shell runs.

        That is every command text whose words end as a shell's do
        (``shell_word``) but two: the text of an option of a program of
        ``_SPLIT_TEXTS`` (``env -S``), which that program splits into words
        and runs with no shell, and a command its runner runs with no shell
        (``TextRunner``: ``hyperfine -N``, the words of a command that ``tmux
        new`` is given as several arguments; each word of ``watch -x`` is no
        command text to read at all, ``_argument_words``). A ``spaced``
        runner's command given as one argument is a shell text, blanks or
        none, when no other word of the command is known to follow it
        (``shown_next`` tells). In a text a shell runs, an operator outside
        quotes ends a command, as in the text after ``-c`` of a shell
        (``_ShellText``).
        """
        if not self.shell_text and not self.leader:
            return False
        plain = _plain_word(word)
        if self.shell_text and not self.shell_value and not plain.startswith(("-", "+")):
            return True
        if self.leader in _SPLIT_TEXTS or self.unshelled:
            return False
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if (
            runner is not None
            and runner.spaced
            and not _SPACE.search(word)
            and (self.all_texts or self.followed is not False)
        ):
            return False
        return self.shell_word(word)

    def passes_over(self, word: str) -> bool:
        """Say whether a word, not yet read, is one a shell takes out of the command's words.

        That is a redirection (``_REDIRECTION_WORD``: ``2>&1``, ``>out``,
        ``<<<text``, ``>|out``) and the file after a redirection that stands
        alone (``>`` ``out``). Where a shell reads the word, as a word of a
        shell text or of a command text whose words end as a
        shell's do (``shell_word``), the program never sees them; in an
        argument list that no shell reads, such a word was most likely meant
        for a shell. Either way ``read`` passes over them, so the client stays
        as it is: the option before one still gives the word after it its
        rule, ``sshpass`` reads its options on, and a client's own command
        (``AUTH``) is the next word. ``shown_next`` hides one that stands
        where the option before it takes a value outside a shell text. Two
        words are read though they look like one, as the text holds them
        either way: a rule of ``ACL SETUSER`` that gives a password
        (``>VALUE``, ``<VALUE``, ``\\>VALUE``) and an option standing as the
        file (``> -a VALUE``). A word split out of a shell text with its quotes
        removed (``split``) may have been quoted, and is read as it stands.
        """
        if self.rule == _NEXT_ACL_RULES and _hidden_acl_rule(word) is not None:
            return False
        if self.redirect_file:
            return not _plain_word(word).startswith("-")
        if self.split:
            return False
        return _REDIRECTION_WORD.match(word) is not None

    def shown_next(
        self,
        word: str,
        ahead: str | None = None,
        *,
        comment: bool = False,
        closers: bool = False,
        token: bool = False,
    ) -> str | None:
        """Return how a word is shown because of the option before it, or ``None`` to read it.

        ``ahead`` is the next word of the same command, or ``None`` when this
        word ends the command: after ``AUTH`` a word that another follows is
        a user name, read as it stands. ``comment`` says a comment follows the
        word on its line (``AUTH WORD #VALUE``): the word is then the password,
        as the shell reads it, and ``comment`` hides the word glued to the
        comment's ``#`` too, as the password it is when its ``#`` was meant
        as part of it. A next word that reads as an option or a redirection
        (``_read_apart``) makes the word the password the same way, and the
        next word is hidden as well. With ``closers`` the word is a word of a
        shell text, and the ``)`` or backquote that closes a command after the
        value (``_closing_tail``) is shown after it; a word made only of them
        holds no value: it ends the command, and is read as it stands. Whether
        another word follows is kept for ``shell_run``. A hidden value that
        ends in an operator or in the ``)`` that closes a command ends its
        command only where a shell reads the word: as a word of a shell text
        (``token``), a command text whose words end as a shell's do
        (``shell_word``), or with a ``)`` or a backquote, a word split out of
        a shell text. Elsewhere the operator is a character of the value.
        A word the walk passes over
        (``passes_over``) is read as it stands, but for one that is not a
        word of a shell text and that the option before it would hide. A
        redirection with a file glued to it (``'>VALUE'``) there may be the
        value as typed, so it is hidden as the value. A redirection that
        stands alone or gives one descriptor to another (``2>&1``), and the
        file after one that stands alone, may be the value as typed too, and
        a shell would give the option the word after them: they are hidden,
        and the option keeps its rule for the next word.
        """
        if self.passes_over(word):
            passed = None if token else _hidden_next(self.rule, word)
            if passed is None:
                return None
            if self.redirect_file or _BARE_REDIRECTION.fullmatch(word) is not None:
                redirect = None if self.redirect_file else _REDIRECTION_WORD.match(word)
                self.redirect_file = redirect is not None and redirect.end() == len(word)
                return passed
        self.followed = _another_word(word, ahead)
        auth = self.rule == _NEXT_AUTH
        if auth and self.followed and not _read_apart(ahead):
            return None
        tail = _closing_tail(word) if closers else ""
        body = word[: len(word) - len(tail)]
        if closers and not body:
            self._end_command()
            return None
        spaced = self._spaced_setting(body)
        if spaced is not None:
            shown: str | None = spaced
        else:
            shown = _hidden_next(self.rule, body)
        if shown is None:
            return None
        self.redirect_file = False
        ends = token or self.shell_word(word) or (self.split and word.endswith((")", "`")))
        scheme, self.scheme = self.scheme, False
        self.secret_word = False
        if self.rule == _NEXT_SECRET_NAME:
            self.rule = _NEXT_SETTING_VALUES
        elif self.rule not in (_NEXT_SETTING_VALUES, _NEXT_ACL_RULES, _NEXT_SECRETS):
            self.rule = ""
        self.taken = not (auth and (comment or _read_apart(ahead)))
        if not self.taken:
            self.rule = _NEXT_SECRET
        self.value = False
        # The word after a scheme word that is the whole value may be a token: the shown
        # command and the hashes hide it, and the comparison reads it as typed, as a program
        # or a model file may stand there too.
        if scheme and _ALL_HIDDEN.get() and _plain_word(word).lower() in AUTH_SCHEME_WORDS:
            self.rule, self.value = _NEXT_TOKEN, True
        self.next_text = self.next_shell = False
        # A hidden value is a word of the client's command: the names of ``CONFIG SET`` are
        # counted past it, and past a name and its value written as one word as two words.
        if self.client_command:
            self.command_words += 1 if spaced is None else 2
        if ends and _COMMAND_END.search(word) is not None:
            self._end_command()
            shown = shown + tail if closers else _separators_kept(shown, word)
        return shown

    def _end_command(self) -> None:
        """Take in the end of a command at the end of a word: the next word starts another."""
        self.rule = ""
        self.program = ""
        self.data_command = False
        self.client_command = ""
        self.subcommand = ""
        self.pairs_unknown = False
        self.new_command()

    def _setting_pair(self, plain: str) -> list[str] | None:
        """Split a ``CONFIG SET`` name written with its value in one word, or return ``None``.

        The parts are the name, the blanks after it and the value. Such a word
        counts as two words, a name and its value, so the names after it are
        read as names. A word in the place of a value is ``None``.
        """
        if (self.client_command, self.subcommand) != ("config", "set"):
            return None
        if self.command_words % 2 == 0:
            return None
        parts = _BLANK_RUN.split(plain, maxsplit=1)
        return parts if len(parts) == 3 and parts[0] else None

    def _spaced_setting(self, word: str) -> str | None:
        """Hide the value of a ``CONFIG SET`` name written with its value in one word, or ``None``.

        ``CONFIG SET 'requirepass VALUE'`` shows ``'requirepass <hidden>'``:
        the name is shown and the rest of the word hidden, its quotes kept. A
        word in the place of a value, or one whose first word names no
        credential setting, is read as it stands.
        """
        parts = self._setting_pair(_plain_word(word))
        if parts is None or not _names_secret_setting(parts[0].lower()):
            return None
        quote = _quoted_whole(word)
        return f"{quote}{parts[0]}{parts[1]}{HIDDEN}{quote}"

    def comment(self, word: str) -> str | None:
        """Return how the first word of a comment is shown, or ``None`` to read it as a comment.

        A comment ends the command before it, but where an option or a
        command before it still waits for its value (``-a #VALUE``, ``AUTH
        #VALUE``), the word glued to the ``#`` is hidden as that value: the
        text holds it whether or not the shell drops it. A bare ``#`` is
        shown, and so is a comment after a value.
        """
        if self.taken or word == _SHELL_COMMENT:
            return None
        return self.shown_next(word)

    def command_text(self, word: str) -> bool:
        """Say whether a word is a command of the client's own, read as one text.

        It is the value of a client's ``command`` option, or the client's
        command written as one quoted word of several words
        (``redis-benchmark 'AUTH VALUE'``).
        """
        if self.rule == _NEXT_COMMAND:
            return True
        if not self.data_command or self.value:
            return False
        plain = _plain_word(word)
        return not plain.startswith("-") and _SPACE.search(plain) is not None

    def _command_rule(self, word_lower: str, pending: str, command_word: bool) -> str:
        """Return the rule a word of a client's own command gives the next word, or ``""``."""
        if pending in (_NEXT_AUTH, _NEXT_USER):
            return _NEXT_SECRET
        # The user name of a server's ``user`` line is followed by its rules, and each rule by
        # the next, up to a long option or a command separator. Such a word is read as it
        # stands, also in the place of the user name (``--user --requirepass VALUE``).
        if (
            pending in (_NEXT_ACL_USER, _NEXT_ACL_RULES)
            and not word_lower.startswith("--")
            and _COMMAND_SEPARATOR.search(word_lower) is None
        ):
            return _NEXT_ACL_RULES
        if command_word:
            return _NEXT_AUTH if word_lower == "auth" else ""
        if self.client_command == "hello" and word_lower == "auth":
            return _NEXT_USER
        # After a word a shell may split, the five fixed arguments of MIGRATE may be over.
        if self.client_command == "migrate" and (
            self.command_words >= _MIGRATE_ARGUMENTS or self.pairs_unknown
        ):
            return {"auth": _NEXT_SECRET, "auth2": _NEXT_USER}.get(word_lower, "")
        # The names of CONFIG SET are its odd words after SET: name, value, name, value; after
        # a word a shell may split (``pairs_unknown``) a name is read in either place.
        if (
            (self.client_command, self.subcommand) == ("config", "set")
            and (self.command_words % 2 == 1 or self.pairs_unknown)
            and _names_secret_setting(word_lower)
        ):
            return _NEXT_SECRET
        # The rules of ACL SETUSER follow its user name.
        if (self.client_command, self.subcommand) == ("acl", "setuser"):
            return _NEXT_ACL_RULES
        # The names of SENTINEL SET follow the master's name, and those of SENTINEL CONFIG SET
        # follow SET: name, value, name, value from the second word after SENTINEL on.
        if (
            self.subcommand in _SENTINEL_SETTINGS
            and self.client_command == "sentinel"
            and self.command_words >= 2
            and (self.command_words % 2 == 0 or self.pairs_unknown)
            and _names_sentinel_secret(word_lower)
        ):
            return _NEXT_SECRET
        # The setting of a line of a Sentinel's config, after a server's ``--sentinel``.
        if self.sentinel_line and _names_sentinel_secret(word_lower):
            return _NEXT_USER if word_lower == _SENTINEL_MASTER_PASSWORD else _NEXT_SECRET
        return ""

    def glued_text(self, word: str) -> tuple[str, str, str] | None:
        """Split an option of ``TEXT_OPTIONS`` from the text glued to it, or return ``None``.

        The parts are the option (``--command``), what stands before the text
        in the word (``--command=``, or ``'--command=`` when a quote opens the
        word) and the text as a word of its own (``'TEXT'``), so the word is
        read as the option and its text written apart are.
        """
        program = self._text_program()
        options = TEXT_OPTIONS.get(program)
        if not options or self.next_text:
            return None
        plain = _plain_word(word)
        quote = _quoted_whole(word)
        heads = [
            (option, head) for option in options if (head := _glued_head(plain, option, program))
        ]
        group = _glued_group(plain, program)
        if group:
            # The group itself is read as the option, as a group that ends with it is.
            heads.append((plain[:group], plain[:group]))
        for option, head in heads:
            if quote and word.startswith(quote + head):
                return option, quote + head, quote + word[len(quote) + len(head) :]
            if word.startswith(head):
                return option, head, word[len(head) :]
        return None

    def read(self, word: str, *, token: bool = False) -> None:
        """Take in a word read as it stands: the rule for the next word and the client.

        An option of ``TEXT_OPTIONS`` with its text glued to it is read as
        the option and then its text (``glued_text``). A word a shell takes
        out of the command (``passes_over``, ``token`` as there) changes
        nothing.
        """
        if self.passes_over(word):
            redirect = None if self.redirect_file else _REDIRECTION_WORD.match(word)
            self.redirect_file = redirect is not None and redirect.end() == len(word)
            return
        self.redirect_file = False
        split = self.glued_text(word)
        if split is not None:
            self.read(split[0])
            self.read(split[2])
            return
        pending = self.rule
        plain = _plain_word(word)
        # A word a shell may make any number of words of (``$X``, ``$(...)``, ``"$@"``) leaves
        # the names and values of ``CONFIG SET`` after it without their turn, and the fixed
        # arguments of ``MIGRATE`` without their count.
        expands = (
            bool(self.client_command) and (token or self.shell_word(word)) and _splits_unknown(word)
        )
        was_value = self.value
        text = self.text(word)
        ends = not self.split and word in _OPERATOR_WORDS and self.shell_word(word)
        operand = not self.value and not plain.startswith("-")
        client = CLIENT_PASSWORD_OPTIONS.get(self.program)
        # Whether this word is the client's own command, as ``AUTH`` or ``SET`` is.
        command_word = self.data_command and operand
        after_secret, self.secret_word = self.secret_word, False
        if pending == _NEXT_SECRET_NAME and (
            _SETTING_NAME.fullmatch(plain) or _SETTING_PASSED_OVER.fullmatch(plain)
        ):
            # The secret's name, or an option before it, which leaves the name unknown.
            self.rule = _NEXT_SETTING_VALUES
        elif self.setting and operand and _names_secret_setting(plain):
            self.rule = _NEXT_SETTING_VALUES
        elif self.rule == _NEXT_SETTING_VALUES and _SETTING_PASSED_OVER.fullmatch(plain):
            pass
        else:
            self.rule = "" if _SPACE.search(plain) else _next_rule(plain, self.program)
        word_lower = plain.lower()
        command_rule = self._command_rule(word_lower, pending, command_word)
        if command_rule:
            self.rule = command_rule
        # A credential-like option's value may be a scheme word, its token after it; one that
        # gives a credential-like name a scheme word (``--auth=Bearer``) has the token next.
        self.scheme = (
            self.rule == _NEXT_SECRET
            and not command_rule
            and not self.client_command
            and (client is None or plain not in client.secret)
        )
        if not self.rule and _ALL_HIDDEN.get() and _gives_scheme_word(plain):
            self.rule = _NEXT_TOKEN
        self.taken = False
        if command_word:
            # A client named again before an operator is an argument of the command still
            # open, so a turn left unknown stays unknown until a line break or an operator.
            self.client_command, self.subcommand, self.command_words = word_lower, "", 0
        elif self.client_command:
            # Every word after the client's command goes to the server, one that starts with
            # a dash (``-1``) as well, so the names and values of ``CONFIG SET`` keep their turn.
            if not self.command_words:
                self.subcommand = word_lower
            elif self.command_words == 1 and (self.client_command, self.subcommand, word_lower) == (
                "sentinel",
                "config",
                "set",
            ):
                self.subcommand = _SENTINEL_CONFIG_SET
            self.command_words += 1 if self._setting_pair(plain) is None else 2
            self.pairs_unknown = self.pairs_unknown or expands
        # Only a word that is itself an operator ends the command (``_OPERATOR_WORDS``), and
        # only where a shell reads it (``shell_word``): elsewhere ``;`` is an argument.
        separator = ends
        data_set = word_lower == "set" and operand and self.data_command and self.data_sets
        self.setting = (word_lower in SETTING_WORDS and not data_set) or (
            self.setting and plain.startswith("-") and plain != "--" and not separator
        )
        if after_secret and word_lower == "set" and not data_set:
            self.rule = _NEXT_SECRET_NAME
        self.secret_word = operand and not self.rule and word_lower in SECRET_SETTING_WORDS
        self.value = bool(self.rule) or (client is not None and plain in client.takes_value)
        named = _client_named(plain)
        if named:
            self.program = named
        elif separator or (client is not None and client.runs_command and operand):
            self.program = ""
        self.data_command = named in DATA_SET_CLIENTS or (
            self.data_command and not operand and not separator
        )
        self.axis = not self.rule and not self.declaring and plain in AXIS_OPTIONS
        self.sentinel_line = client is not None and plain in client.sentinel
        self._read_texts(plain, word, was_value=was_value, text=text)

    def _read_texts(self, plain: str, word: str, *, was_value: bool, text: bool) -> None:
        """Take in what a word says of the command texts after it."""
        self.next_shell = _text_option(plain, TEXT_OPTIONS.get(self._text_program(), ()))
        code = _CODE_OPTION.fullmatch(plain) is not None and not self._runner_flag(plain)
        self.next_text = self.next_shell or code
        self._read_shell(plain, text=text)
        if not text and not _SPACE.search(plain) and _COMMAND_SEPARATOR.search(plain):
            self.new_command()
            rest = _COMMAND_SEPARATOR.split(plain)[-1]
            if rest:
                self._read_shell(rest, text=False)
                self._read_start(rest)
            return
        if self.start:
            self._read_start(plain, value=was_value or text)
            return
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if runner is None:
            return
        value, self.leader_value = self.leader_value, False
        if value:
            self.unshelled = self.unshelled or (self.shell_named and plain == "none")
            self.shell_named = False
            return
        if plain in runner.ends:
            self.leader = ""
        elif self.all_texts:
            self._read_joined(word)
        elif text:
            self.all_texts = runner.rest
            self.runs = ""
            if runner.rest:
                self.joined.restart()
                self._read_joined(word)
        elif plain in runner.no_shell:
            self.unshelled = True
        elif plain in runner.takes_value:
            self.leader_value = True
            self.shell_named = plain in runner.shell_options
        elif _OPTION_GROUP.fullmatch(plain):
            self._read_group(runner, plain)
        elif not plain.startswith("-"):
            if not self.operands and runner.commands and plain not in runner.commands:
                self.leader = ""
            self.operands += 1

    def _read_joined(self, word: str) -> None:
        """Take in a word of the command a runner of ``COMMAND_TEXT_RUNNERS`` joins from its words.

        The word is read as the shell that runs the joined command reads it,
        word by word and operator by operator (``_JoinedCommand``); a word of
        a shell text first loses its quotes there, as the runner gets it. The
        program each command there starts with is ``runs`` when it is one of
        ``TEXT_OPTIONS``, so ``hyperfine`` after ``taskset -c 0``, ``env
        A=1``, ``cd DIR &&`` or ``ssh HOST`` reads its glued texts as it does
        first.
        """
        if isinstance(self.ahead, str) and not self.split:
            word = _shell_unquoted(word)
        for found in _SHELL_TOKEN.finditer(word):
            token = found.group("word")
            if token is None:
                self.joined.restart()
                self.runs = ""
                continue
            body = token.lstrip("(")
            if body != token:
                self.joined.restart()
                self.runs = ""
            name = self.joined.program(_plain_word(body)) if body else None
            if name is not None:
                self.runs = name if name in TEXT_OPTIONS else ""

    def _runner_flag(self, plain: str) -> bool:
        """Say whether a word is a runner's own option before its texts that takes no value.

        It is one of the runner's ``TextRunner.flags``, alone or last in a
        group of short options (``watch -tc``), and no value of an option.
        """
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if runner is None or self.start or self.all_texts or self.leader_value:
            return False
        if plain in runner.flags:
            return True
        return _OPTION_GROUP.fullmatch(plain) is not None and f"-{plain[-1]}" in runner.flags

    def _read_group(self, runner: TextRunner, group: str) -> None:
        """Take in a group of a runner's short options (``-tx``), its options one by one."""
        for at, letter in enumerate(group[1:], start=2):
            option = "-" + letter
            if option in runner.no_shell:
                self.unshelled = True
            elif option in runner.takes_value:
                value = group[at:]
                if not value:
                    self.leader_value = True
                    self.shell_named = option in runner.shell_options
                elif option in runner.shell_options and value == "none":
                    self.unshelled = True
                return

    def _read_start(self, plain: str, *, value: bool = False) -> None:
        """Take in a word where a command starts: it names the program, unless it leads it."""
        if self.starter:
            values = _COMMAND_STARTERS.get(self.starter, ())
            skipped, self.starter_value = self.starter_value, plain in values
            client = CLIENT_PASSWORD_OPTIONS.get(self.starter)
            if client is not None and plain in client.takes_value:
                self.starter_value = True
            if value or skipped or plain.startswith("-") or _VARIABLE_ASSIGNED.match(plain):
                return
            lead = _STARTER_LEADS.get(self.starter)
            if lead is not None and not self.starter_lead and lead.fullmatch(plain):
                self.starter_lead = True
                return
        elif _VARIABLE_ASSIGNED.match(plain) or plain in _SHELL_LEAD_WORDS:
            return
        elif self.function_name or plain == "function":
            # ``function NAME`` leads the body of a function, whose first word starts a command.
            self.function_name = not self.function_name
            return
        name = plain.rpartition("/")[2]
        self.start = False
        self.starter = ""
        self.declaring = self.declaring or plain in _DECLARING_BUILTINS
        self.operands = 0
        self.leader_value = self.all_texts = self.unshelled = self.shell_named = False
        self.leader = name if name in COMMAND_TEXT_RUNNERS or name in TEXT_OPTIONS else ""
        self.runs = ""
        runner = COMMAND_TEXT_RUNNERS.get(self.leader)
        if runner is not None and runner.options_after:
            self.unshelled = self._no_shell_ahead()
        client = CLIENT_PASSWORD_OPTIONS.get(name)
        if name in _COMMAND_STARTERS or (client is not None and client.runs_command):
            self.start = True
            self.starter = name
            self.starter_lead = False

    def _read_shell(self, plain: str, *, text: bool) -> None:
        """Take in what a word says of a shell's text: the shell, its group with ``c``, the text."""
        if text and self.shell_text and not plain.startswith(("-", "+")):
            self.shell = self.shell_text = self.shell_value = False
            return
        if not self.shell:
            self.shell = not plain.startswith(("-", "+")) and plain.rpartition("/")[2] in SHELLS
            return
        if self.shell_value:
            self.shell_value = False
        elif plain in _SHELL_VALUE_OPTIONS:
            self.shell_value = True
        elif _SHELL_TEXT_GROUP.fullmatch(plain):
            self.shell_text = True
        elif not plain.startswith(("-", "+")):
            self.shell = plain.rpartition("/")[2] in SHELLS

    def glued(self, word: str, *, closers: bool = False) -> str | None:
        """Hide a password glued to its option, or return ``None``.

        A command glued to a client's ``command`` option is read as that
        client's own (``_hidden_command_glued``). With ``closers`` the word is
        a word of a shell text, and the ``)`` or backquote that closes a
        command after the value is shown (``_closing_tail``).
        """
        tail = _closing_tail(word) if closers else ""
        body = word[: len(word) - len(tail)]
        shown = _hidden_glued_password(body)
        if shown is None:
            shown = _hidden_client_glued(body, self.program)
        if shown is None:
            shown = _hidden_command_glued(body, self.program)
        if shown is None:
            return None
        return shown + tail if closers else _separators_kept(shown, word)


class _LaterClients:
    """For each word of a command line or a text, the client a later word of its command names.

    That is the client of ``CLIENT_PASSWORD_OPTIONS`` named by the first word
    after it that names one (``_client_named``), up to the end of its command:
    a word that is an operator (``_OPERATOR_WORDS``), or a line break before a
    word (``breaks``). An operator inside a longer word, as in ``LABEL='x;y'``
    or ``N=$(nproc)``, is part of that word. The words are read once, from the
    last back, when the first word is asked for, so a text is read in linear
    time. A word is a text or the match of a word of a text.
    """

    def __init__(
        self,
        words: Sequence[str] | Sequence[re.Match[str]],
        breaks: Callable[[int], bool] | None = None,
    ) -> None:
        self._words = words
        self._breaks = breaks
        self._clients: list[str] | None = None

    def at(self, k: int) -> str:
        """Return the client a later word of word ``k``'s command names, or ``""``."""
        if self._clients is None:
            self._clients = self._read()
        return self._clients[k]

    def _read(self) -> list[str]:
        clients = [""] * len(self._words)
        client = ""
        for k in range(len(self._words) - 1, -1, -1):
            clients[k] = client
            word = self._words[k]
            plain = _plain_word(word if isinstance(word, str) else word.group(0))
            client = "" if plain in _OPERATOR_WORDS else _client_named(plain) or client
            if self._breaks is not None and self._breaks(k):
                client = ""
        return clients


def _value_client(walk: _CommandWalk, word: str, later: _LaterClients, k: int) -> str:
    """Return the client whose options read a name's value that no client's options reach.

    Where no client's options apply (``_CommandWalk.program``), word ``k``
    that gives a variable or an option its value after ``=``
    (``MADE_UP_FLAGS=...``, ``--env=MADE_UP_FLAGS=...``) is read with the
    options of the client a later word of the same command names
    (``_LaterClients``): ``env 'MADE_UP_FLAGS=-a VALUE' redis-benchmark``
    reads ``-a`` as the password option of ``redis-benchmark``. ``""`` for
    any other word.
    """
    if walk.program:
        return ""
    plain = _plain_word(word)
    if _OPTION_ASSIGNED.match(plain) is None and _VARIABLE_ASSIGNED.match(plain) is None:
        return ""
    return later.at(k)


def _gives_scheme_word(plain: str) -> bool:
    """Say whether a word gives a credential-like name an Authorization scheme word as its value.

    ``--auth=Bearer`` and ``AUTHORIZATION=basic`` do (``AUTH_SCHEME_WORDS``),
    and the word after them is the token. A word that holds a blank gives
    no such value.
    """
    head, equals, value = plain.rpartition("=")
    if not equals or value.lower() not in AUTH_SCHEME_WORDS or _SPACE.search(plain):
        return False
    return _hidden_credential(plain) == f"{head}={HIDDEN}"


def _another_word(word: str, ahead: str | None) -> bool:
    """Say whether another word of the same command follows a word: ``ahead`` is the next one.

    A word that ends a command (``VALUE;``, ``VALUE)``) ends it, and so does
    a next word made only of separators.
    """
    if ahead is None or _COMMAND_END.search(word) is not None:
        return False
    return _SEPARATOR_WORD.fullmatch(_plain_word(ahead)) is None


def _read_apart(ahead: str | None) -> bool:
    """Say whether the word after a word of ``AUTH`` reads as an option, a redirection or a comment.

    ``AUTH VALUE --raw``, ``AUTH VALUE '>out.log'`` and ``AUTH VALUE '#'``
    given as arguments pass the client that word as the password, though it
    was likely meant as an option, a file or a comment: the word before it is
    read as the password, and the word itself is hidden too unless it is a
    long option (``shown_next``).
    """
    if ahead is None:
        return False
    plain = _plain_word(ahead)
    return plain.startswith(("-", "#")) or _REDIRECTION.match(plain) is not None


def _separators_kept(shown: str, word: str) -> str:
    """Give a word whose value ends hidden back the command separators it ends with.

    ``-pVALUE;`` shows ``-p<hidden>;``, so the next command stays apart.
    """
    tail = _TRAILING_SEPARATORS.search(word)
    if tail is None or not shown.endswith(HIDDEN):
        return shown
    return shown + tail.group(0)


def _shell_text_split(word: str) -> tuple[str, str] | None:
    """Split a word of a shell text that gives a shell its text into that text and what follows.

    The text ends at the first ``<``, ``>`` or ``&>`` outside quotes after its
    start, which starts a redirection of the outer shell (``'tool ...'>out``,
    ``'tool ...'2>/dev/null``, where the ``2`` is part of the text, as a shell
    reads it), and before the ``)`` or backquote that closes a command around
    it (``(sh -c 'tool ...')``, ``_closing_tail``). A ``)`` outside quotes
    that closes no ``(`` of the word ends the word, as a shell reads it, so
    what follows it is no part of the text: in ``(tool '...')2>/dev/null`` the
    ``2>`` redirects the subshell. ``None`` when the word holds no quote and
    no escape, so the shell passes it on as typed.
    """
    if not any(mark in word for mark in "'\"\\"):
        return None
    at = 0
    # The brackets the word opens outside quotes, as ``$(`` does, that a ``)`` of it closes.
    depth = 0
    while at < len(word):
        char = word[at]
        if char == "\\":
            at += 2
            continue
        if char in _QUOTES:
            part = _QUOTED_PART.match(word, at)
            at = len(word) if part is None else part.end()
            continue
        if word.startswith(HIDDEN, at):
            # The mark of a value hidden at a deeper level is no redirection.
            at += len(HIDDEN)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if not depth:
                break
            depth -= 1
        if at and char in "<>&" and _REDIRECTION_WORD.match(word, at) is not None:
            break
        at += 1
    body = word[:at]
    tail = _closing_tail(body)
    return body[: len(body) - len(tail)], tail + word[at:]


def _closing_tail(word: str) -> str:
    """Return the characters that close a command at the end of a word of a shell text, or ``""``.

    In a shell text, a ``)`` or backquote at the end of a word, outside
    quotes and not escaped, closes a command (``(tool --token VALUE)``,
    ``echo `tool --token VALUE```): it is shell syntax, never part of the
    value, and is shown after the hidden value. One escaped by a backslash
    (``VALUE\\)``) is part of the value, and so is one inside quotes, which
    the quote at the end of the word keeps out of the tail.
    """
    found = _COMMAND_END.search(word)
    if found is None:
        return ""
    head = word[: found.start()]
    escaped = (len(head) - len(head.rstrip("\\"))) % 2
    return found.group(0)[escaped:]


def _hidden_password(word: str) -> str | None:
    """Hide what follows the first ``:`` of a ``user:password`` word, or ``None`` when it has none.

    A word that starts an option is no value, and neither is one without a
    ``:``. A word that is an address with a user part loses only that part,
    as ``_hidden_address_user`` says, so the host, the port and the path of
    ``redis://:password@localhost:6379/0`` stay.
    """
    plain = _plain_word(word)
    if plain.startswith("-") or ":" not in plain:
        return None
    quote = _quoted_whole(word)
    if _ADDRESS_USER.match(plain):
        return f"{quote}{_hidden_address_user(plain)}{quote}"
    return f"{quote}{plain.partition(':')[0]}:{HIDDEN}{quote}"


def _hidden_address_password(text: str) -> str:
    """Hide only the password of the user part of every address in a text.

    ``postgres://alice:V@db/shop`` reads ``postgres://alice:<hidden>@db/shop``
    and ``postgres://alice@db/shop`` stays as it is: the reading of
    ``hidden_difference``, in which a user name tells two setups apart.
    """
    return _address_sub(
        _ADDRESS_USER_PASSWORD,
        lambda found: f"{found.group(1)}{found.group(2)}{':' + HIDDEN if found.group(3) else ''}@",
        text,
    )


def _hidden_credentials(word: str) -> str | None:
    """Hide the value of a client's ``credentials`` option, or return ``None`` for an option.

    ``app:VALUE`` shows ``app:<hidden>``; a value with no ``:`` after its
    first character is a password alone and is hidden whole
    (``_credentials_shown``). A word that starts a long option is no value.
    The quotes around the word are kept.
    """
    plain = _plain_word(word)
    if plain.startswith("--"):
        return None
    shown = _credentials_shown(plain)
    return shown if shown == HIDDEN else f"{_quoted_whole(word)}{shown}{_quoted_whole(word)}"


def _credentials_shown(value: str) -> str:
    """Show the user of ``user:password`` and hide the rest, or hide a password alone whole."""
    user, colon, _ = value.partition(":")
    return f"{user}:{HIDDEN}" if colon and user else HIDDEN


def _hidden_address_user(text: str) -> str:
    """Hide the user part of every address in a text: ``redis://:V@host/W`` shows ``redis://<hidden>@host/W``."""
    return _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", text)


def _hidden_next(rule: str, word: str) -> str | None:
    """Return how an argument is shown after an option that names how, or ``None`` to read it."""
    if rule in (_NEXT_SECRET, _NEXT_AUTH):
        return None if _plain_word(word).startswith("--") else HIDDEN
    if rule == _NEXT_TOKEN:
        return None if _plain_word(word).startswith("-") else HIDDEN
    if rule == _NEXT_SECRETS:
        plain = _plain_word(word)
        return None if plain.startswith("-") or plain in _OPERATOR_WORDS else HIDDEN
    if rule == _NEXT_PASSWORD:
        return _hidden_password(word)
    if rule == _NEXT_CREDENTIALS:
        return _hidden_credentials(word)
    if rule == _NEXT_SETTING_VALUES:
        return _hidden_setting_value(word)
    if rule == _NEXT_SECRET_NAME:
        return _hidden_secret_name(word)
    if rule == _NEXT_ACL_RULES:
        return _hidden_acl_rule(word)
    return None


def _hidden_acl_rule(word: str) -> str | None:
    """Hide the password or hash of a rule of ``ACL SETUSER``, or return ``None`` to read it.

    ``>password`` shows ``><hidden>``, and ``<``, ``#`` and ``!`` keep their
    first character the same way; any other rule (``on``, ``~*``,
    ``+@all``) is read as it stands. A password may hold blanks, so all of
    the argument after the first rule that gives one is hidden, as in
    ``'>made up'`` and ``'> made up'``: rules written as one word with
    blanks between them (``'on >password +@all'``) show the rules before
    the password (``'on ><hidden>'``). A rule character with nothing after
    it is shown. The quotes around the word are kept. In a shell text a
    ``>`` or ``<`` outside quotes starts a redirection, so a rule is typed in
    quotes or with a backslash before its first character, which a shell
    takes off; a program that splits a text into words with no shell
    (``hyperfine -N``) takes it off too, and a text handed on through several
    shells may hold several. No rule of ``ACL SETUSER`` starts with a
    backslash, so the backslashes before a rule's first character are read
    as such a shell's, wherever the word stands: ``\\>password`` shows
    ``\\><hidden>``.
    """
    plain = _plain_word(word)
    for found in _ACL_RULE_START.finditer(plain):
        if found.end() < len(plain):
            quote = _quoted_whole(word)
            return f"{quote}{plain[: found.start()]}{found.group()}{HIDDEN}{quote}"
    return None


# A run of blanks, kept when a word is split at it.
_BLANK_RUN = re.compile(r"(\s+)")
# The first character of a rule of ``ACL SETUSER`` that gives a password or its hash, at the
# start of the argument or after a blank, with the backslashes in front of it that keep a ``>``
# or a ``<`` from starting a redirection.
_ACL_RULE_START: Final = re.compile(
    "(?:(?<=\\s)|^)\\\\*[" + re.escape("".join(_ACL_PASSWORD_RULES)) + "]"
)


def _hidden_setting_value(word: str) -> str | None:
    """Hide a word after the name of a credential setting, or return ``None`` to read it.

    An option is read, and so are ``--``, a bare ``=`` and a word made only of
    command separators. A long option keeps its name and loses the value glued
    after its ``=`` (``--body=<hidden>``); any other word is hidden whole.
    """
    plain = _plain_word(word)
    if _SETTING_PASSED_OVER.fullmatch(plain) or _SEPARATOR_WORD.fullmatch(plain):
        return None
    glued = _LONG_OPTION_GLUED.fullmatch(plain)
    if glued is not None:
        quote = _quoted_whole(word)
        return f"{quote}{glued.group(1)}{HIDDEN}{quote}"
    return HIDDEN


def _hidden_secret_name(word: str) -> str | None:
    """Hide the value of a secret's first word after ``set``, or return ``None`` to read it.

    ``NAME=VALUE`` keeps its name and loses its value (``MADE_UP_NAME=<hidden>``),
    an option is read as after the name of a credential setting
    (``_hidden_setting_value``), and a plain name is read as it stands.
    """
    plain = _plain_word(word)
    if plain.startswith("-"):
        return _hidden_setting_value(word)
    name, equals, _ = plain.partition("=")
    if not equals or _SETTING_NAME.fullmatch(name) is None:
        return None
    quote = _quoted_whole(word)
    return f"{quote}{name}={HIDDEN}{quote}"


def _hidden_glued_password(word: str) -> str | None:
    """Hide the password of a ``user:password`` glued to its option, or ``None``.

    ``--user=user:password`` shows ``--user=user:<hidden>`` and
    ``-uuser:password`` shows ``-uuser:<hidden>``. A value that is an address
    with a user part loses only that part:
    ``--user=redis://<hidden>@localhost:6379/0``.
    """
    quote = _quoted_whole(word)
    plain = _plain_word(word)
    found = _GLUED_USER_PASSWORD.fullmatch(plain)
    if found is None:
        return None
    if _ADDRESS_USER.match(plain, len(found.group(1))):
        return f"{quote}{found.group(1)}{_hidden_address_user(plain[len(found.group(1)) :])}{quote}"
    return f"{quote}{found.group(1)}{found.group(2)}:{HIDDEN}{quote}"


# White space anywhere in a text.
_SPACE = re.compile(r"\s")


def _plain_word(word: str) -> str:
    """Return a word without its quotes, as near as needed to read an option's name."""
    if "'" not in word and '"' not in word:
        return word
    return word.replace("'", "").replace('"', "")


def _secret_header(name: str) -> bool:
    """Say whether a header of this name carries a credential."""
    return name.upper() in SECRET_HEADERS or looks_like_credential(name)


def _hidden_header(word: str) -> tuple[str, bool] | None:
    """Hide the value of a header whose name says it is a credential, or ``None``.

    The header, ``Name: value``, starts the word, follows ``=``, follows a
    quote or is glued to a short option (``-HAuthorization: ...``). Returns
    the word as shown and whether the value runs on to the end of the
    argument: it does unless a quote that opens just before the name closes
    the word.
    """
    for found in _HEADER_NAME.finditer(word):
        if not _secret_header(found.group(1)):
            continue
        head = word[: found.end()]
        start = found.start()
        quote = word[start - 1] if start and word[start - 1] in _QUOTES else ""
        rest = word[found.end() :]
        if quote and rest.endswith(quote) and quote not in rest[:-1]:
            return f"{head} {HIDDEN}{quote}", False
        return f"{head} {HIDDEN}", True
    return None


def _splits_unknown(word: str) -> bool:
    """Say whether a shell may make no word or several of a word of a shell text.

    A parameter, a command's output or a text in backquotes outside quotes may
    give any number of words, and so may ``"$@"`` or ``"${NAME[@]}"`` in double
    quotes. A word in single quotes is one word as it stands.
    """
    quote = _quoted_whole(word)
    if quote == "'":
        return False
    if quote:
        return _LIST_EXPANSION.search(word) is not None
    return (_SHELL_EXPANSION.search(word) or _SUBSTITUTION_MARK.search(word)) is not None


def _quoted_whole(word: str) -> str:
    """Return the quote that opens a word and closes it, or an empty text."""
    quote = word[:1]
    if quote in _QUOTES and quote and len(word) > 1 and word.endswith(quote):
        return quote
    return ""


def _unclosed_quote(word: str) -> int:
    """Return where a quote that is not closed opens in a shell word, or ``-1``.

    A backslash outside single quotes keeps the next character from opening or
    closing a quote, as a shell reads it.
    """
    quote = ""
    opened = -1
    i = 0
    while i < len(word):
        char = word[i]
        if quote == "'":
            if char == "'":
                quote = ""
        elif char == "\\":
            i += 1
        elif quote:
            if char == quote:
                quote = ""
        elif char in _QUOTES:
            quote, opened = char, i
        i += 1
    return opened if quote else -1


def _words_before_value(word: str) -> bool:
    """Say whether a quoted word holds several words before its first ``=``, or no ``=`` at all.

    Such a word, as ``'tool --token VALUE API_KEY=VALUE'``, is read word by
    word; a word whose first ``=`` comes before any space, as
    ``'API_KEY=a value'``, gives one name its value.
    """
    space = _SPACE.search(word)
    if space is None:
        return False
    equals = word.find("=")
    return equals < 0 or space.start() < equals


def _value_rule(walk: _CommandWalk, plain: str) -> None:
    """Give the next word the rule of the option an ordinary name's value starts with.

    ``MADE_UP_FLAGS=--api-key`` hides the next word, as ``--api-key`` does.
    """
    at = _ordinary_value_start(plain)
    if at is not None and not walk.rule:
        walk.rule = _next_rule(plain[at:], walk.program)
        walk.value = bool(walk.rule)
        walk.scheme = _names_credential(plain[at:])


def _hidden_value_text(text: str, program: str = "", *, inside: str = "") -> str:
    """Hide the credentials of the text of one argument, read as an argument of a command is.

    An argument whose first word gives a credential-like name a value is that
    value to its end (``_hidden_to_the_end``), unless only the credentials are
    hidden (``_ALL_HIDDEN`` off); any other is read word by word as the value
    of one argument (``_hidden_words``), so ``MADE_UP_FLAGS=--api-key VALUE
    --threads 8`` shows ``MADE_UP_FLAGS=--api-key <hidden> --threads 8``.
    """
    whole = _hidden_to_the_end(text, program) if _ALL_HIDDEN.get() else None
    return whole if whole is not None else _hidden_words(text, program, value=True, inside=inside)


def _hidden_quoted_value(word: str, program: str = "", *, inside: str = "") -> str | None:
    """Hide the credentials of a word that gives an ordinary name a quoted value, or ``None``.

    The value holds a blank and is one argument's text, as a shell passes it
    on, so it is read as ``_hidden_value_text`` reads one. A value in one pair
    of quotes keeps them where they stand:
    ``MADE_UP_FLAGS="--api-key VALUE --threads 8"`` shows
    ``MADE_UP_FLAGS="--api-key <hidden> --threads 8"``, and a credential name
    hides its whole value: ``MADE_UP_FLAGS="DB_PASSWORD=a b"`` shows
    ``MADE_UP_FLAGS="DB_PASSWORD=<hidden>"``. Any other word with quotes, one
    quoted whole as the name of an ``env`` or ``docker run -e`` argument
    inside a shell text is written (``'MADE_UP_FLAGS=--api-key VALUE
    --threads 8'``) or one of several quoted parts, is read as the shell
    passes it on (``_shell_unquoted``) and, when that hides a value, is shown
    quoted whole: ``'MADE_UP_FLAGS=--api-key <hidden> --threads 8'``, in
    quotes that keep the quotes around it (``inside``, ``_shell_quoted``).
    ``None`` when the word gives no ordinary name (``_ordinary_value_start``)
    such a value, or when it is read so and hides nothing.
    """
    at = _ordinary_value_start(word)
    part = None if at is None else _QUOTED_PART.fullmatch(word, at)
    if at is not None and part is not None and word[at] in _QUOTES:
        inner = part.group(1) if part.group(1) is not None else part.group(2)
        if not _SPACE.search(inner):
            return None
        if part.group(1) is not None or not _DOUBLE_QUOTED_ESCAPE.search(inner):
            head, mark = word[:at], word[at]
            shown = _hidden_value_text(head + inner, program, inside=_within(inside, mark))
            value = shown[at:] if shown.startswith(head) else HIDDEN
            closed = mark if word.endswith(mark) and len(word) > at + 1 else ""
            return head + mark + value + closed
    if not any(quote in word for quote in _QUOTES):
        return None
    plain = _shell_unquoted(word)
    if _ordinary_value_start(plain) is None or not _SPACE.search(plain):
        return None
    shown = _hidden_value_text(plain, program, inside=_ALL_QUOTES if inside else "")
    return None if shown == plain else _shell_quoted(shown, inside)


def _hidden_quoted_parts(
    word: str,
    program: str = "",
    *,
    shell: bool = False,
    command: bool = False,
    inside: str = "",
    closers: bool = False,
) -> str | None:
    """Hide the credentials of a word of a shell text with quoted parts, or ``None``.

    A shell takes the quotes and escapes off the word and passes it on as one
    argument, so ``mytool --token" VALUE"`` gives ``mytool`` the argument
    ``--token VALUE``, which is read as the text of one argument is. With
    ``shell`` the word is in a text that a second shell runs, as the remote
    command of ``ssh`` or the text after ``-c`` of a shell inside a shell
    text, and that shell splits the argument into words:
    ``sh -c 'ssh HOST ./bench --token" VALUE"'`` runs ``./bench --token
    VALUE`` on the host, so the argument is read as a shell text. When the
    reading hides a value the word is shown quoted whole:
    ``'--token <hidden>'``, in quotes that keep the quotes around it
    (``inside``, ``_shell_quoted``). With ``command`` the argument is a
    command of the client's own, as the value of its ``command`` option is:
    ``--command AUTH\\ VALUE`` shows ``--command 'AUTH <hidden>'``. ``None``
    when the word holds no quote and no escape, gives an argument with no
    blank, or hides nothing read so. With ``closers`` the word is a word of a
    shell text, and the ``)`` that closes a command around it or the
    redirection after it (``_shell_text_split``) is shown after it as typed:
    ``(mytool '--token VALUE')`` shows ``(mytool '--token <hidden>')``.
    """
    split = _shell_text_split(word)
    if split is None:
        return None
    body, after = split if closers else (word, "")
    plain = _shell_unquoted(body)
    if not _SPACE.search(plain):
        return None
    within = _ALL_QUOTES if inside else ""
    shown = _hidden_words(plain, program, shell=shell, command=command, inside=within)
    return None if shown == plain else _shell_quoted(shown, inside) + after


def _shell_quoted(text: str, inside: str = "") -> str:
    """Quote a text as one shell word, in single or in double quotes, whichever is shorter.

    So a word quoted in parts inside a word quoted in parts, as each level of
    the remote command of ``ssh`` writes it, is shown about as long as it is
    typed, in either kind of quotes. In double quotes only ``\\`` and ``"``
    are escaped, so a text that holds ``$`` or a backquote, which a shell
    reads there, is quoted in single quotes. ``inside`` holds the quotes of
    the words the text stands in, as ``'`` for a word of ``sh -c './bench
    --token" VALUE"'``: a quote among them would end that word, so the text
    is quoted in the other kind (``'./bench "--token <hidden>"'``), in double
    quotes with its own ``"`` escaped, or, inside both kinds, written with its
    blanks and backslashes escaped. A text that holds a quote it cannot be
    written with there is shown as ``<hidden>``.
    """
    if not inside:
        single = shlex.quote(text)
        if "$" in text or "`" in text:
            return single
        double = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return double if len(double) < len(single) else single
    if "'" not in inside and "'" not in text:
        return "'" + text + "'"
    if '"' not in inside:
        return '"' + _DOUBLE_QUOTED_SPECIAL.sub(r"\\\g<0>", text) + '"'
    if not any(quote in text for quote in _QUOTES):
        return _ESCAPED_IN_A_WORD.sub(r"\\\g<0>", text)
    return HIDDEN


def _within(inside: str, quote: str) -> str:
    """Return the quotes of the words a text stands in, with one more quote around it."""
    return inside if not quote or quote in inside else inside + quote


# Both kinds of quotes: what a text inside a word that is quoted inside another stands in.
_ALL_QUOTES = "'\""
# The characters a backslash writes inside double quotes, and those it writes in a bare word
# that stands inside both kinds of quotes.
_DOUBLE_QUOTED_SPECIAL = re.compile(r"""[\\$`"]""")
_ESCAPED_IN_A_WORD = re.compile(r"[\\\s]")


# A character a backslash keeps from a shell's reading inside double quotes.
_DOUBLE_QUOTED_ESCAPE = re.compile(r"""\\([$`"\\\n])""")


def _read_escape(found: re.Match[str]) -> str:
    """Return what an escape gives a shell's reading: the character after the backslash.

    A backslash before a line break gives nothing, as the shell joins the two lines.
    """
    char = found.group(0)[1:]
    return "" if char == "\n" else char


def _shell_unquoted(word: str) -> str:
    """Return one shell word as the shell passes it on: its quotes taken off, its escapes read.

    A backslash before a line break, in double quotes or outside quotes, is
    taken out with the line break (``_read_escape``), so ``"--token a\\<line
    break>b"`` passes on ``--token ab``.
    """
    out: list[str] = []
    end = 0
    for part in _QUOTED_PART.finditer(word):
        out.append(word[end : part.start()])
        single, double = part.group(1), part.group(2)
        if single is not None:
            out.append(single)
        elif double is not None:
            out.append(_DOUBLE_QUOTED_ESCAPE.sub(_read_escape, double))
        else:
            out.append(_read_escape(part))
        end = part.end()
    out.append(word[end:])
    return "".join(out)


# The private-use characters that stand for the command substitutions of a shell text while
# the text around them is read; a text that holds some of them already takes the others.
_SUBSTITUTION_BLOCKS: Final = (
    range(0xE000, 0xF900),
    range(0xF0000, 0xFFFFE),
    range(0x100000, 0x10FFFE),
)
_SUBSTITUTION_MARK = re.compile("[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
# How deep the texts read inside other texts are being read: the substitutions inside
# substitutions (``_substitutions_restored``) and the texts of ``eval`` (``_evaluated``).
_SUBSTITUTION_DEPTH: ContextVar[int] = ContextVar("_SUBSTITUTION_DEPTH", default=0)
# The characters a backslash escapes in the inner text of backquotes: the shell takes that
# backslash off before it runs the text, and in backquotes inside double quotes it does so
# before a double quote too, so ``x="`eval "tool \\"AUTH V\\""`"`` runs ``eval "tool \"AUTH
# V\""`` (POSIX.1-2024, Shell Command Language, 2.2.3 Double-Quotes and 2.6.3 Command
# Substitution, https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html).
_BACKQUOTE_ESCAPES: Final = "\\`$"
_QUOTED_BACKQUOTE_ESCAPES: Final = '\\`$"'
_BACKQUOTE_ESCAPE: Final = re.compile(r"\\([\\`$])")
_QUOTED_BACKQUOTE_ESCAPE: Final = re.compile(r'\\([\\`$"])')


def _substitution_spans(text: str) -> list[tuple[int, int, int, int, str]]:
    """Return the command substitutions of a shell text that no other substitution holds.

    Each is ``(start, inner start, inner end, end, escapes)``: ``$(...)``, a
    text in backquotes, or ``<(...)`` and ``>(...)`` outside double quotes,
    found outside single quotes and also inside double quotes, where a shell
    runs them too. Inside one, quotes, brackets and other substitutions are
    read, so its own closing ``)`` is found: ``$(echo "(a)")`` is one. One
    that is not closed is no substitution here, and its words are read as
    words of the command it stands in. A backslash keeps the character after
    it from this reading. ``escapes`` holds the characters a backslash
    escapes in the inner text of backquotes, which the shell takes off before
    it runs that text (``_BACKQUOTE_ESCAPES``, and ``_QUOTED_BACKQUOTE_ESCAPES``
    in double quotes); it is empty for the others. The text is read once.
    """
    spans: list[tuple[int, int, int, int, str]] = []
    # The open contexts: "(" a substitution or a bracket inside one, '"' double quotes, "`"
    # backquotes; ``depth`` counts the first and the last.
    stack: list[str] = []
    depth = start = inner = 0
    escapes = ""
    at, size = 0, len(text)
    while at < size:
        char = text[at]
        top = stack[-1] if stack else ""
        step = 1
        if char == "\\":
            step = 2
        elif (top == "`" and char == "`") or (top == "(" and char == ")"):
            stack.pop()
            depth -= 1
            if not depth:
                spans.append((start, inner, at, at + 1, escapes))
        elif top == "`":
            pass
        elif top == '"' and char == '"':
            stack.pop()
        elif char == "`" or (
            text.startswith("(", at + 1) and (char == "$" or (char in "<>" and top != '"'))
        ):
            if not depth:
                start, inner = at, at + (1 if char == "`" else 2)
                escapes = ""
                if char == "`":
                    escapes = _QUOTED_BACKQUOTE_ESCAPES if top == '"' else _BACKQUOTE_ESCAPES
            stack.append("`" if char == "`" else "(")
            depth += 1
            step = 1 if char == "`" else 2
        elif top == '"':
            pass
        elif char == "'":
            close = text.find("'", at + 1)
            step = (size if close < 0 else close + 1) - at
        elif char == '"':
            stack.append('"')
        elif top == "(" and char == "(":
            stack.append("(")
            depth += 1
        at += step
    return spans


def _substitutions_masked(
    text: str,
) -> tuple[str, dict[str, tuple[str, str, str, str]]] | None:
    """Return a shell text with each command substitution in it put as one mark, or ``None``.

    The marks are characters of ``_SUBSTITUTION_BLOCKS`` that the text does
    not hold; each stands for the opening, the inner text, the closing and
    the characters a backslash escapes in the inner text of its substitution
    (``_substitution_spans``). ``None`` when the text holds no substitution.
    A text with more substitutions than there are free marks is given as
    ``HIDDEN``, with none.
    """
    if "$(" not in text and "`" not in text and "<(" not in text and ">(" not in text:
        return None
    spans = _substitution_spans(text)
    if not spans:
        return None
    taken = set(_SUBSTITUTION_MARK.findall(text))
    free = (chr(code) for block in _SUBSTITUTION_BLOCKS for code in block if chr(code) not in taken)
    out: list[str] = []
    pieces: dict[str, tuple[str, str, str, str]] = {}
    end = 0
    for start, inner, inner_end, stop, escapes in spans:
        mark = next(free, None)
        if mark is None:
            return HIDDEN, {}
        out.append(text[end:start])
        out.append(mark)
        pieces[mark] = (text[start:inner], text[inner:inner_end], text[inner_end:stop], escapes)
        end = stop
    out.append(text[end:])
    return "".join(out), pieces


def _substitutions_restored(
    shown: str, pieces: Mapping[str, tuple[str, str, str, str]], read: Callable[[str], str]
) -> str:
    """Put each command substitution back in place of its mark, its inner text read by ``read``.

    A mark the reading of the text around it took into a hidden value is
    gone, and so is the substitution it stood for. The inner texts are read
    as texts of their own, ``_SHELL_DEPTH`` substitutions deep at most;
    deeper, an inner text is shown as ``HIDDEN``. The inner text of
    backquotes is read as the shell runs it, with the backslashes before the
    characters it escapes taken off (``_backquote_unescaped``); where that
    reading hides a value, it is shown with them put back
    (``_backquote_escaped``), so
    ``x="`eval "memtier_benchmark --command \\\\"AUTH VALUE\\\\""`"`` shows
    ``x="`eval 'memtier_benchmark --command "AUTH <hidden>"'`"``.
    """
    if not pieces:
        return shown

    def restored(found: re.Match[str]) -> str:
        piece = pieces.get(found.group(0))
        if piece is None:
            return found.group(0)
        opening, inner, closing, escapes = piece
        depth = _SUBSTITUTION_DEPTH.get()
        if depth >= _SHELL_DEPTH:
            return opening + HIDDEN + closing
        token = _SUBSTITUTION_DEPTH.set(depth + 1)
        try:
            plain = _backquote_unescaped(inner, escapes)
            if plain != inner:
                read_plain = read(plain)
                if read_plain != plain:
                    return opening + _backquote_escaped(read_plain) + closing
            return opening + read(inner) + closing
        finally:
            _SUBSTITUTION_DEPTH.reset(token)

    return _SUBSTITUTION_MARK.sub(restored, shown)


def _backquote_unescaped(inner: str, escapes: str) -> str:
    """Return the inner text of backquotes as the shell runs it, or ``inner`` itself.

    A backslash before one of ``escapes`` (``_BACKQUOTE_ESCAPES`` or
    ``_QUOTED_BACKQUOTE_ESCAPES``) is taken off; one before any other
    character stays. ``escapes`` is empty for a substitution other than
    backquotes, whose inner text the shell runs as it is.
    """
    if not escapes or "\\" not in inner:
        return inner
    pattern = _QUOTED_BACKQUOTE_ESCAPE if '"' in escapes else _BACKQUOTE_ESCAPE
    return pattern.sub(r"\1", inner)


def _backquote_escaped(text: str) -> str:
    """Return a text to stand between backquotes so that the shell runs it as it is.

    A backslash and a backquote get a backslash before them, which the shell
    takes off again (``_backquote_unescaped``); every other character is
    kept, as a backslash before none of them is needed.
    """
    return text.replace("\\", "\\\\").replace("`", "\\`")


# What closes a command in a shell text where it stands outside quotes: a subshell's ``)`` and
# the backquote that ends a command substitution.
_SUBSHELL_CLOSERS: Final = ")`"


# The words that run ``eval`` as the builtin it is, before it: ``builtin eval``, ``command eval``.
_EVAL_RUNNERS: Final = ("builtin", "command")


def _evaluated(
    tokens: Sequence[re.Match[str]], at: int, text: str, inside: str
) -> tuple[str, int] | None:
    """Return the ``eval`` at ``tokens[at]`` with the words of the shell text it runs shown.

    ``eval`` joins its words with blanks, each with its quotes taken off and
    its escapes read (``_shell_unquoted``), and runs what it joined as a
    shell text: ``eval 'tool --command '\\''AUTH VALUE'\\'''`` and ``eval tool
    --command \\'AUTH VALUE\\'`` both run ``tool --command 'AUTH VALUE'``. It
    may stand after ``builtin`` or ``command`` (``_EVAL_RUNNERS``), also
    right after the ``(`` that opens a subshell (``(eval 'tool ...')``), and
    a ``--`` right after it ends its options and is none of its words. Its
    words run up to the operator, line break or comment that ends its
    command, or up to the ``)`` or backquote that closes it
    (``_subshell_closed``), which is shown after them as typed. When some
    word of them is quoted or escaped and the text they run hides a value,
    or holds one an earlier reading hid, that text is read as any shell
    text is, its programs' code included (``_hidden_code``), so
    ``eval 'PGPASSWORD=VALUE psql'`` shows ``eval 'PGPASSWORD=<hidden> psql'``
    with its program, as it would outside an ``eval``, and
    ``eval python3 -c \\"token = \\'VALUE\\'\\"`` hides the value as
    ``python3 -c "token = 'VALUE'"`` does. Then the ``eval`` is returned from
    its first word, its text written as it was typed where it can be (``_evaluated_words``),
    with the index of the token after its words; otherwise ``None``, and
    the words are read one by one as any others are, which reads words with
    no quote the same. The texts of ``eval`` inside ``eval`` are read
    ``_SHELL_DEPTH`` deep at most, as command substitutions are; deeper, the
    text is shown as ``HIDDEN``.
    """
    first = at
    name = tokens[first].group(0).lstrip("(")
    if name in _EVAL_RUNNERS and first + 1 < len(tokens):
        first += 1
        name = tokens[first].group(0)
    if name != "eval" or _breaks_line(text[tokens[at].end() : tokens[first].start()]):
        return None
    begin = first + 1
    if begin < len(tokens) and tokens[begin].group(0) == "--":
        begin += 1
    words: list[str] = []
    after = ""
    stop = begin
    while stop < len(tokens) and not after:
        token = tokens[stop]
        between = text[tokens[stop - 1].end() : token.start()]
        if token.lastgroup == "operator" or _breaks_line(between) or _shell_comment(token.group(0)):
            break
        word, after = _subshell_closed(token.group(0))
        if not word:
            # A word that starts with what closes the command is read after the ``eval``.
            after = ""
            break
        words.append(word)
        stop += 1
    plain = [_shell_unquoted(word) for word in words]
    if plain == words:
        return None
    lead = text[tokens[at].start() : tokens[begin].start()]
    depth = _SUBSTITUTION_DEPTH.get()
    if depth >= _SHELL_DEPTH:
        return lead + HIDDEN, stop
    joined = " ".join(plain)
    reset = _SUBSTITUTION_DEPTH.set(depth + 1)
    try:
        shown = _hidden_words(
            _hidden_code(joined, shell=True), shell=True, inside=_ALL_QUOTES if inside else ""
        )
    finally:
        _SUBSTITUTION_DEPTH.reset(reset)
    if shown == joined and HIDDEN not in joined:
        return None
    return lead + _evaluated_words(words, shown, inside) + after, stop


def _subshell_closed(word: str) -> tuple[str, str]:
    """Split a word of a shell text at the ``)`` or backquote that closes a command, if any.

    Outside quotes and not escaped, the shell reads a ``)`` or a backquote as
    the end of the command that it closes, never as a part of a word: ``x)``
    in ``(eval x)`` and ``'tool ...')`` in ``(eval 'tool ...')`` give the
    ``eval`` the word ``x`` and ``'tool ...'``. Returned are the part of the
    word before that character and the rest, which a redirection may follow
    (``'tool ...')2>/dev/null``); a word that closes no command is returned
    whole, with ``""``.
    """
    at = 0
    while at < len(word):
        char = word[at]
        if char == "\\":
            at += 2
        elif char in _QUOTES:
            part = _QUOTED_PART.match(word, at)
            at = len(word) if part is None else part.end()
        elif char in _SUBSHELL_CLOSERS:
            return word[:at], word[at:]
        else:
            at += 1
    return word, ""


# What a shell reads inside double quotes, which a text keeps there only as it was typed there.
_DOUBLE_QUOTED_READ: Final = "$`"


def _evaluated_words(words: Sequence[str], shown: str, inside: str) -> str:
    """Write the text an ``eval`` runs, with its values hidden, as its words were typed.

    When the words are one word in single quotes, or in double quotes with
    no escape in it, and ``shown`` can stand in that kind of quotes with the
    same reading (no ``'`` in single quotes; no ``"`` or ``\\`` in double
    quotes, and each ``$`` and backquote of the word kept), the text is
    written in that kind of quotes: ``eval "redis-cli -a VALUE PING $PORT"``
    shows ``eval "redis-cli -a <hidden> PING $PORT"``. A quote that the text
    stands in (``inside``) is not used. Otherwise the text is quoted whole
    (``_shell_quoted``).
    """
    if len(words) == 1 and len(words[0]) > 1 and words[0][0] == words[0][-1]:
        quote, body = words[0][0], words[0][1:-1]
        if quote == "'" and quote not in inside and "'" not in body + shown:
            return quote + shown + quote
        if (
            quote == '"'
            and quote not in inside
            and _shell_unquoted(words[0]) == body
            and not any(char in shown for char in '"\\')
            and all(shown.count(char) == body.count(char) for char in _DOUBLE_QUOTED_READ)
        ):
            return quote + shown + quote
    return _shell_quoted(shown, inside)


def _hidden_words(
    text: str,
    program: str = "",
    *,
    shell: bool = False,
    command: bool = False,
    value: bool = False,
    inside: str = "",
    code: bool = False,
    walk: _CommandWalk | None = None,
) -> str:
    """Hide the credentials among the words of one argument, keeping what lies between the words.

    The words are read as a shell reads them; a quote that is not closed
    runs to the end of the text, and what follows it is read as words too,
    unless a credential-like name or header comes before it in the same word
    and hides the rest. With ``shell`` the text is a shell text: an
    operator outside quotes (``&&``, ``||``, ``;``, ``&``, ``|``) or a line
    break ends a command, so a value hidden before it ends there, the
    operator and the next command are shown, and the next command is read
    afresh; a header that hides the rest hides it up to there. Without
    ``shell`` an operator is part of the word it stands in. A word after a
    credential-like option (``--token VALUE``) is hidden whole, unless it is
    another long option. A credential-like variable or option keeps its name
    and loses what follows its ``=``, up to the end of the word, quoted
    spaces included. A quoted word that holds several words is read the
    same way; it is a shell text of its own only when it is the text after
    ``-c`` of a shell (``_ShellText``), as in ``sh -c 'tool ...; ls'``, and
    an operator in any other quoted word is part of the value it stands in.
    Such a shell text is read word by word also when it holds no blank but
    an operator, so in ``sh -c "API_KEY=VALUE&&./bench"`` inside a shell
    text the value ends at ``&&``, as it does in the outer text.
    A header whose name is a credential keeps its name and loses its value
    (``Authorization: <hidden>``); a header that is not closed by a quote
    hides the rest of the argument. The password of a
    ``user:password`` after ``-u``, ``--user``, ``-U`` or ``--proxy-user`` is
    hidden, also when it is glued to the option. The password options of
    the clients of ``CLIENT_PASSWORD_OPTIONS`` are read with the program
    they belong to: ``program`` is the client whose options apply at the
    start of the text, and each word that names a client starts its own.
    With ``command`` the text is a command of that client's own, as the
    value of its ``command`` option is (``_CommandWalk``).
    A quoted word that is a command text (``_CommandWalk.text``), as the
    remote command of ``ssh`` inside ``sh -c``, is read word by word too.
    Such a word, a nested shell text or a command of the client's own, in
    double quotes and holding an escape (``\\"``, ``\\\\``), is read as the
    next shell gets it, with its escapes taken out (``_hidden_quoted_parts``):
    in ``sh -c "tool --token\\" VALUE\\""`` the option and its value are one
    word, hidden whole. With ``value`` the text is the value of one argument: when its first
    word gives an ordinary name its value (``_ordinary_value_start``), as
    ``MADE_UP_FLAGS=--api-key VALUE --threads 8`` does, the rest of that
    first word is read as an option, so a credential option there hides
    the next word. A name followed by ``:`` right after a keyword of a
    program (``if token:``, ``lambda token:``) is no header. ``inside`` holds
    the quotes of the words the text stands in, which a word shown quoted
    whole there keeps (``_shell_quoted``). With ``code`` the text is the text
    of a program that no shell reads, as the one after ``python -c``: a
    header that is not closed hides up to the end of its line, a line break
    after a backslash aside, and a credential-like word whose quoted value
    ``_hidden_code`` hid keeps what follows the closing quote, read as words
    (``_code_value_rest``), so in ``API_KEY='VALUE';run_old()`` the
    statement after the value stays shown. ``walk`` reads the words in place
    of a fresh walk, as for the text glued to an option of ``TEXT_OPTIONS``,
    which is read as the option's next word. In a shell text a command
    substitution (``$(...)``, a text in backquotes, ``<(...)``) is one word
    of the command it stands in, which is read as if the substitution were
    any other word, and its inner text is a shell text of its own, read
    afresh: the client a word before it names keeps its options after it,
    and a client named inside it reads its own. In a shell text the words
    of an ``eval`` are read as the one shell text it runs, their quotes
    taken off and their escapes read (``_evaluated``), so ``eval
    tool --command \\'AUTH VALUE\\'`` hides the password as ``tool
    --command 'AUTH VALUE'`` does.
    """
    masked = _substitutions_masked(text) if shell else None
    if masked is not None:
        outer, pieces = masked
        shown = _hidden_words(
            outer, program, shell=True, command=command, value=value, inside=inside, walk=walk
        )
        return _substitutions_restored(
            shown, pieces, lambda inner: _hidden_words(inner, shell=True, inside=inside)
        )
    out: list[str] = []
    end = 0
    walk = _CommandWalk(program, command=command, ahead=text) if walk is None else walk
    shells = _ShellText()
    # Whether a header hides the words up to the end of the command.
    hiding = False
    first = value
    tokens = list((_SHELL_TOKEN if shell else _SHELL_WORD).finditer(text))
    later = _LaterClients(
        tokens, lambda k: k > 0 and _breaks_line(text[tokens[k - 1].end() : tokens[k].start()])
    )
    aheads, comments = _words_ahead(tokens, text, shell=shell)
    # The words of a comment read as words of the client of the command before it.
    remark: _RemarkWalk | None = None
    # The first token after the words of an ``eval`` read as one shell text (``_evaluated``).
    resume = 0
    # What follows the closing quote of a word read as the quoted word alone, shown after it.
    after_word = ""
    for k, found in enumerate(tokens):
        out.append(after_word)
        after_word = ""
        if k < resume:
            continue
        word = found.group(0)
        gap = text[end : found.start()]
        end = found.end()
        operator = found.lastgroup == "operator"
        comment = shell and _shell_comment(word)
        # A value the command still waits for is read from the comment's first word.
        held = walk.comment(word) if comment and not _breaks_line(gap) else None
        if _breaks_line(gap):
            remark = None
        elif comment and walk.program:
            remark = _RemarkWalk(walk.program)
        # A comment ends the command before it; its words are read as a command of their own,
        # and on the line of a client's command as the client reads them too (``_RemarkWalk``).
        if operator or (shell and (_breaks_line(gap) or comment)):
            walk.reset()
            shells = _ShellText()
            hiding = False
        elif _breaks_line(gap):
            walk.end_line()
            # In a program's text a header ends with its line.
            hiding = hiding and not code
        if hiding:
            continue
        out.append(gap)
        if operator or held is not None:
            if operator and remark is not None:
                remark = _RemarkWalk(remark.client)
            out.append(held or word)
            continue
        evaluated = None
        if shell and walk.start and remark is None:
            evaluated = _evaluated(tokens, k, text, inside)
        if evaluated is not None:
            # The words of an ``eval``, read as the one shell text it runs, hide a value.
            shown, resume = evaluated
            out.append(shown)
            end = tokens[resume - 1].end()
            walk.read(word, token=shell)
            continue
        if remark is not None:
            # A word the client would hide is hidden; any other is read as the comment's own.
            said = remark.hidden(word[1:] if comment else word, aheads[k])
            if said is not None:
                out.append(_SHELL_COMMENT + said if comment else said)
                walk.read(word, token=shell)
                continue
        # A redirection is no word of the command: the walk and the shell's ``-c`` pass over it.
        passed = walk.passes_over(word)
        # Whether this word is the text after ``-c`` of a shell, a shell text of its own.
        nested = False if passed else shells.read(word)
        shown_next = walk.shown_next(
            word,
            aheads[k],
            comment=shell and comments[k],
            closers=shell,
            token=shell,
        )
        if shown_next is not None:
            out.append(shown_next)
            first = False
            continue
        split = walk.glued_text(word)
        if split is not None:
            # An option with its text glued to it: the text is read as the option's next word.
            walk.read(split[0])
            inner = _hidden_words(split[2], walk.program, shell=shell, inside=inside, walk=walk)
            out.append(_glued_shown(split[1], inner))
            first = False
            continue
        axis = _axis_value(word, walk.axis, walk.program)
        glued = walk.glued(word, closers=shell)
        # Whether this word is a command of the client's own, read as one text.
        own = walk.command_text(word)
        command_text = walk.code(word)
        # A command text a shell runs, as the remote command of ``ssh``, is a shell text too.
        nested = walk.shell_run(word) or nested
        # An ordinary name's value is read with the options of the client that applies where
        # it stands, or else of the client a later word of the command names.
        argument = not (own or command_text or nested)
        client = _value_client(walk, word, later, k) if argument else ""
        if glued is None and argument:
            glued = _hidden_value_glued(word, walk.program or client)
        # Whether this word is the text of a program that is no shell, as after ``python -c``.
        program_text = command_text and not nested and not walk.shell_word(word)
        walk.read(word, token=shell)
        if first:
            first = False
            _value_rule(walk, _plain_word(word))
        if glued is not None:
            out.append(glued)
            continue
        if axis:
            out.append(word)
            continue
        opened = _unclosed_quote(word)
        if opened >= 0:
            head = word[: opened + 1]
            if _hidden_credential(head) is None and _hidden_header(head) is None:
                rest = word[opened + 1 :]
                within = _within(inside, word[opened])
                inner = _hidden_words(rest, walk.program, shell=shell, command=own, inside=within)
                out.append(head + inner)
                continue
        quote = _quoted_whole(word)
        split_text = _shell_text_split(word) if nested else None
        if split_text is not None and (split_text[1] or not quote):
            # A shell text with quoted parts that the word does not start and end with, as
            # ``'tool ...')`` in ``(sh -c 'tool ...')`` or ``'tool ...'>out``: the shell takes its
            # quotes off, so that is read as the shell text, and what closes a command or redirects
            # after it is shown as typed.
            body, after = split_text
            plain = _shell_unquoted(body)
            within = _ALL_QUOTES if inside else ""
            shown = _hidden_words(plain, walk.program, shell=True, command=own, inside=within)
            out.append(word if shown == plain else _shell_quoted(shown, inside) + after)
            continue
        if nested and quote and _QUOTED_PART.fullmatch(word) is None:
            # A shell text that starts and ends with a quote but is quoted in parts, as
            # ``'bash -c '"'"'...'"'"''`` writes a quote inside single quotes, is not the text
            # between its first and last quote: the shell takes its quotes off, so that is read
            # as the shell text, and the word is quoted whole again when a value is hidden.
            plain = _shell_unquoted(word)
            within = _ALL_QUOTES if inside else ""
            shown = _hidden_words(plain, walk.program, shell=True, command=own, inside=within)
            out.append(word if shown == plain else _shell_quoted(shown, inside))
            continue
        if shell and not quote:
            # A word quoted whole but for the ``)`` that closes a command after it or a
            # redirection glued to it (``'tool ...')``, ``'tool ...'>out``) is read as the
            # quoted word alone, and what follows its closing quote is shown after it as typed.
            # The number of a descriptor glued before such a redirection (``'tool ...'2>&1``)
            # joins the word's last part, as a shell reads it, and is shown after the quote too.
            closed = _shell_text_split(word)
            if closed is not None and closed[1]:
                body, rest = closed
                number = _GLUED_DESCRIPTOR.search(body) if rest[:1] in "<>&" else None
                if number is not None and _quoted_whole(body[: number.start()]):
                    body, rest = body[: number.start()], number.group(0) + rest
                if _quoted_whole(body):
                    word, after_word = body, rest
                    quote = _quoted_whole(word)
        if quote and (
            own
            or program_text
            or _words_before_value(word)
            or (command_text and _SPACE.search(word))
            or (nested and _operator_spans(word[1:-1]))
        ):
            # A text in double quotes that a shell or the client reads gets it with its
            # escapes taken out: ``\"`` and ``\\`` there end no word and open no quote.
            escaped = quote == '"' and _DOUBLE_QUOTED_ESCAPE.search(word[1:-1]) is not None
            parts = (
                _hidden_quoted_parts(word, walk.program, shell=nested, command=own, inside=inside)
                if escaped and (own or command_text or nested)
                else None
            )
            if parts is not None:
                out.append(parts)
                continue
            within = _within(inside, quote)
            inner = _hidden_words(
                word[1:-1],
                walk.program,
                shell=nested,
                command=own,
                inside=within,
                code=program_text,
            )
            out.append(quote + inner + quote)
            continue
        assigned = (
            None
            if command_text or nested
            else _hidden_quoted_value(word, walk.program or client, inside=inside)
        )
        if assigned is not None:
            out.append(assigned)
            continue
        # In a shell text, the ``)`` or backquote that closes a command after the value is shown.
        tail = _closing_tail(word) if shell else ""
        hidden = _hidden_credential(word[: len(word) - len(tail)])
        value_rest = _code_value_rest(word) if code and hidden is not None else None
        if value_rest is not None:
            head, after = value_rest
            out.append(head + _hidden_words(after, walk.program, inside=inside, code=True))
            continue
        if hidden is not None:
            hidden = hidden + tail if shell else _separators_kept(hidden, word)
            out.append(hidden + quote if quote and hidden.count(quote) % 2 else hidden)
            continue
        if quote and _SPACE.search(word):
            within = _within(inside, quote)
            inner = _hidden_words(
                word[1:-1], walk.program, shell=nested, command=own, inside=within
            )
            out.append(quote + inner + quote)
            continue
        header = _hidden_header(word)
        if header is not None and (
            _after_keyword(text, found.start())
            or (text.strip() == word and walk.program in _KEY_CLIENTS)
        ):
            header = None
        if header is not None:
            shown, runs_on = header
            out.append(shown)
            if runs_on and not shell and not code:
                return "".join(out)
            hiding = runs_on
            continue
        parts = _hidden_quoted_parts(
            word, walk.program, shell=nested, command=own, inside=inside, closers=shell
        )
        out.append(word if parts is None else parts)
    out.append(after_word)
    rest_of_text = text[end:]
    if hiding and code:
        # The lines after the one a header hides stay.
        line = rest_of_text.find("\n")
        rest_of_text = rest_of_text[line:] if line >= 0 else ""
    elif hiding:
        rest_of_text = ""
    out.append(rest_of_text)
    return "".join(out)


# A word of a program's text that gives a credential-like name a quoted value that
# ``_hidden_code`` hid, and the rest of the word after the closing quote, when that rest
# starts as the next part of the program does: ``API_KEY='<hidden>';run_old()``. No
# string goes on past its closing quote before one of these, in a program's text or a
# shell's: a backquote ends it as ``;`` does, and so do ``&&`` and ``|`` that no quote
# follows. ``||`` ends none, as it joins two strings in SQL (``'a'||'b'``), and neither does
# an ``&&`` or a ``|`` before a quote, which starts more of the value rather than a command.
_HIDDEN_QUOTED_VALUE = re.compile(
    r"""([^\s'"=]+=)(['"])""" + re.escape(HIDDEN) + r"""\2(?=[;,)\]}`]|(?:&&|\|(?!\|))(?!['"]))"""
)


def _code_value_rest(word: str) -> tuple[str, str] | None:
    """Split a word of a program's text after the closing quote of a hidden value, or ``None``.

    Returns the word up to that quote, which shows the name and the hidden
    value in its quotes, and the rest of the word, which ``_hidden_words``
    reads as words. Statements of that shape that follow one another
    (``A_KEY='<hidden>';B_KEY='<hidden>';run_old()``) are all kept in the
    first part, so the rest is read once. A value of any other shape is
    hidden to the end of the word, as ``_hidden_credential`` says.
    """
    end = 0
    while True:
        found = _HIDDEN_QUOTED_VALUE.match(word, end)
        if found is None or _hidden_credential(found.group(1)) is None:
            break
        end = found.end()
    if end == 0:
        return None
    return word[:end], word[end:]


def _words_ahead(
    tokens: Sequence[re.Match[str]], text: str, *, shell: bool = False
) -> tuple[list[str | None], list[bool]]:
    """Return, for each word of a text, the next word of its command, or ``None`` at its end.

    An operator or a line break ends a command. In a shell text (``shell``)
    a redirection (``_REDIRECTION_WORD``), and the file after one that
    stands alone, is no word of the command: the word after them is the
    next, or ``None`` when none follows. A comment (``_shell_comment``)
    ends the command too; the second list says, for each word, whether a
    comment follows it, past any redirection (``AUTH VALUE >out #note``).
    The text is read twice, once each way, so the time is in proportion to
    its length.
    """
    size = len(tokens)
    passed = [False] * size
    breaks = [False] * size
    starts = [False] * size
    file_next = False
    for k, found in enumerate(tokens):
        breaks[k] = found.lastgroup == "operator" or (
            k > 0 and _breaks_line(text[tokens[k - 1].end() : found.start()])
        )
        if breaks[k]:
            file_next = False
        if found.lastgroup == "operator" or not shell:
            continue
        if file_next:
            passed[k], file_next = True, False
            continue
        if _shell_comment(found.group(0)):
            starts[k] = True
            continue
        redirect = _REDIRECTION_WORD.match(found.group(0))
        if redirect is not None:
            passed[k] = True
            file_next = redirect.end() == len(found.group(0))
    out: list[str | None] = [None] * size
    comments = [False] * size
    after: str | None = None
    commented = False
    for k in range(size - 1, -1, -1):
        out[k], comments[k] = after, commented
        if tokens[k].lastgroup == "operator":
            after, commented = None, False
        elif starts[k]:
            after, commented = None, True
        elif not passed[k]:
            after, commented = tokens[k].group(0), False
        if breaks[k]:
            after, commented = None, False
    return out, comments


# A redirection of a shell text, as a word starts: ``>out``, ``>``, ``>>``, ``2>&1``, ``<in``,
# ``&>out``.
_REDIRECTION = re.compile(r"[0-9]*[<>]|&>")
# What starts a comment in a shell text: a word that starts with it, outside quotes.
_SHELL_COMMENT: Final = "#"


class _RemarkWalk:
    """Read the words of a shell comment as the client of the command before it reads them.

    A comment after ``redis-cli -h HOST PING`` holds words the shell drops,
    but a password typed there (``# -a VALUE``, ``#AUTH VALUE``) stays in
    the text: each word of the comment is read as a word given to the client
    afresh, and one the client would hide (``hidden``) is hidden. An
    operator in the comment starts the client's command again.
    """

    def __init__(self, client: str) -> None:
        self.client = client
        self.walk = _CommandWalk()
        self.walk.read(client)

    def hidden(self, word: str, ahead: str | None) -> str | None:
        """Return the word as the client hides it, or ``None`` when the client shows it."""
        if not word:
            return None
        walk = self.walk
        said = walk.shown_next(word, ahead, closers=True, token=True)
        if said is None:
            said = walk.glued(word, closers=True) or _hidden_value_glued(word, walk.program)
        walk.read(word, token=True)
        return said


def _shell_comment(token: str) -> bool:
    """Say whether a token of a shell text, as ``_SHELL_TOKEN`` finds it, starts a comment.

    A ``#`` that starts a word starts a comment, which the shell reads to
    the end of its line, so the word before it ends its command
    ([POSIX.1-2024, Shell Command Language, 2.3 Token Recognition, rule 9](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html)).
    A ``#`` inside a word (``a#b``), inside quotes (``'#a'``), after a
    backslash (``\\#a``) or after ``$`` (``$#``) starts none.
    """
    return token.startswith(_SHELL_COMMENT)


# A redirection of a shell text as a word starts, all of it but the file it takes: the file
# glued after it (``2>/dev/null``, ``<<<text``, ``>|out``, ``2>&1``) or the next word when
# nothing follows it in its word (``>`` ``out``). A process substitution (``<(...)``) is a
# command of its own and the mark of a hidden value is a value, so neither is one.
_REDIRECTION_WORD = re.compile(
    r"(?!" + re.escape(HIDDEN) + r")[0-9]*(?:&>>?|<<<|<<-?|<>|>>|>\||>&|<&|[<>])(?!\()"
)
# The number of a descriptor at the end of a word, right before a redirection glued to it.
_GLUED_DESCRIPTOR = re.compile(r"[0-9]+\Z")
# A redirection with no file glued to it: one that stands alone (``>``, ``2>>``) or gives one
# descriptor to another (``2>&1``, ``>&-``).
_BARE_REDIRECTION = re.compile(
    r"[0-9]*(?:&>>?|<<<|<<-?|<>|>>|>\||>&|<&|[<>])|[0-9]*[<>]&(?:[0-9]+|-)"
)


def _shell_word_ahead(word: str | None) -> str | None:
    """Return the next word of a command in a shell text, or ``None`` when it is a redirection.

    A redirection gives the shell a file, not the program a word, so after
    ``AUTH`` the word before ``>/dev/null`` is a password, not a user name.
    """
    if word is None or _REDIRECTION.match(word) is not None:
        return None
    return word


# Blanks inside a statement of a program, a backslash before a line break among them.
_CODE_BLANKS = r"""(?:[ \t]|\\\n)*"""
# Blanks after the sign that gives a name its value, line breaks among them, so a
# value written on the next line of a list, a call or a table is read as well:
# ``{"api_key":\n    "..."}`` and ``["--token",\n    "..."]``.
_CODE_GAP = r"""(?:\s|\\\n)*"""
# A name given a value in the text of a program: the name, maybe closed by a
# quote and a bracket, then ``=``, ``==``, ``:=`` or ``:``, as in
# ``os.environ['API_KEY'] = ...``, ``$ENV{API_KEY} = ...``,
# ``settings.api_key = ...`` and ``{"api_key": ...}``. A name compared with a
# value is read the same way, after ``===``, ``!==``, ``!=``, ``=~`` or ``!~``,
# or after ``eq`` or ``ne`` with blanks around it, as in ``token != '...'``,
# ``$token =~ m/.../`` and ``$token eq q{...}``.
_CODE_ASSIGNMENT = re.compile(
    r"""(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)(['"]?[\]}]?['"]?)"""
    + _CODE_BLANKS
    + r"""(:=|===|==|=~|!==|!=|!~|=|:|(?<=[ \t])(?:eq|ne)(?=[ \t]))("""
    + _CODE_GAP
    + ")"
)
# A run of the characters of a name in the text of a program, and the start of a name in it.
_CODE_NAME_RUN = re.compile(r"[A-Za-z0-9_-]+")
_CODE_NAME_START = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_]")


def _code_assignments(text: str) -> Iterator[re.Match[str]]:
    """Yield the matches of ``_CODE_ASSIGNMENT.finditer(text)``, reading the text once.

    A name runs on over letters, digits, ``_`` and ``-`` to the end of their
    run, and what may follow it holds none of them, so every start in one
    run reads the same text after the run: only its first start is tried. A
    search would try each start of a name joined by dashes (``a-a-a``) and
    read the rest of the run again from each.
    """
    at = 0
    while True:
        run = _CODE_NAME_RUN.search(text, at)
        if run is None:
            return
        start = _CODE_NAME_START.search(text, run.start(), run.end())
        found = None if start is None else _CODE_ASSIGNMENT.match(text, start.start())
        if found is None:
            at = run.end()
            continue
        yield found
        at = found.end()


# Keywords of a program after which a name and ``:`` start a block or the body
# of a function, and give the name no value: ``if token:``, ``while not
# token:``, ``lambda token:`` and ``lambda a, token:``.
CODE_KEYWORDS: Final[tuple[str, ...]] = (
    "if",
    "elif",
    "while",
    "for",
    "in",
    "with",
    "as",
    "except",
    "lambda",
    "not",
    "and",
    "or",
    "is",
    "case",
    "match",
)
_AFTER_KEYWORD = re.compile(
    r"(?<![A-Za-z0-9_.])(?:(?:"
    + "|".join(CODE_KEYWORDS)
    + r")[ \t]+|lambda[ \t]+(?:[A-Za-z_][A-Za-z0-9_]*[ \t]*,[ \t]*)+)\Z"
)
# How far before a name a keyword of ``CODE_KEYWORDS`` is looked for.
_KEYWORD_REACH: Final = 64


def _after_keyword(text: str, at: int) -> bool:
    """Say whether a keyword of ``CODE_KEYWORDS`` and blanks come right before ``at`` in a text."""
    return _AFTER_KEYWORD.search(text, max(0, at - _KEYWORD_REACH), at) is not None


def _gives_no_value(
    found: re.Match[str],
    text: str,
    *,
    shell_words: bool = False,
    documents: Sequence[tuple[int, int]] = (),
) -> bool:
    """Say whether a match of ``_CODE_ASSIGNMENT`` gives its name no value.

    After a bare name, one with no quote or bracket closing it, the value
    starts on the same line: ``token=`` at the end of a line gives none, and
    the next line stays as it is. A bare name followed by ``:`` right after a
    keyword of ``CODE_KEYWORDS`` gives none either (``if token:``). A name
    that is a parameter of the query of an address, after its ``?`` or an
    ``&``, is left to ``_hidden_credential``, whose value ends at the next
    ``&``. In a text whose words end as a shell's do (``shell_words``), as
    the text after ``sh -c`` and the remote command of ``ssh``, the value of a bare name
    glued to ``=`` or ``==`` ends where the shell word ends, so the sign
    followed by a blank gives the empty value, as a shell gives it: in
    ``tool API_KEY= && ./bench`` the operator and the command after it are
    no value. A line of one of the here-documents of such a text
    (``documents``, as ``_here_documents`` finds them) is a program's text or
    a file's, and is read as one.
    """
    if found.group(2):
        return False
    start = found.start()
    gap = found.group(4).replace("\\\n", "")
    if "\n" in gap:
        return True
    if found.group(3) == ":" and _after_keyword(text, start):
        return True
    if (
        shell_words
        and gap
        and found.group(3) in ("=", "==")
        and found.start(3) == found.end(1)
        and not _in_spans(documents, start)
    ):
        return True
    return _in_query(text, start)


def _in_spans(spans: Sequence[tuple[int, int]], at: int) -> bool:
    """Say whether ``at`` lies in one of ``spans``, which are in order and do not overlap."""
    index = bisect.bisect_right(spans, (at, math.inf)) - 1
    return index >= 0 and at < spans[index][1]


# The start of a here-document in a shell text: ``<<`` or ``<<-`` and the word, maybe
# quoted or after a backslash (``<<'END'``, ``<<\END``), that ends it on a line of its own.
# ``<<<`` gives a word, not a document.
_HERE_DOCUMENT = re.compile(r"""(?<!<)<<(-?)[ \t]*\\?(['"]?)([A-Za-z_][A-Za-z0-9_]*)\2""")


def _here_documents(text: str) -> list[tuple[int, int]]:
    """Return where the lines of each here-document of a shell text start and end.

    They start on the line after ``<<WORD`` and end before the line that
    holds only ``WORD`` (after tabs, for ``<<-``), or at the end of the text.
    """
    spans: list[tuple[int, int]] = []
    done = 0
    for found in _HERE_DOCUMENT.finditer(text):
        if found.start() < done:
            continue
        line_end = text.find("\n", found.end())
        if line_end < 0:
            break
        tabs = "\t*" if found.group(1) else ""
        close = re.compile(f"^{tabs}{re.escape(found.group(3))}$", re.MULTILINE)
        last = close.search(text, line_end + 1)
        done = len(text) if last is None else last.start()
        spans.append((line_end + 1, done))
    return spans


# How far before a name the ``?`` of a query is looked for.
_QUERY_REACH: Final = 2048


def _in_query(text: str, at: int) -> bool:
    """Say whether a name at ``at`` is a parameter of the query of an address in a text.

    It follows ``?``, or ``&`` with a ``?`` before it in the same word.
    """
    before = text[at - 1 : at]
    if before == "?":
        return True
    if before != "&":
        return False
    lowest = max(0, at - _QUERY_REACH)
    query = text.rfind("?", lowest, at)
    return query >= 0 and _SPACE.search(text, query, at) is None


# A quoted name and a comma before its value, as in ``setdefault('HF_TOKEN', ...)``,
# or a quoted option and a comma before the next text of a list, as in
# ``["--password", ...]``.
_CODE_ARGUMENT = re.compile(
    r"""(['"])(-{0,2}[A-Za-z_][A-Za-z0-9_-]*)\1""" + _CODE_BLANKS + "," + _CODE_GAP
)
# A piece of a value that is no quoted text and no bracket: up to white space, a quote, an
# opening bracket, a comma or a closing bracket. A character after a backslash belongs to
# the value, so ``made\ up`` is one value, as a shell reads it; a line break after a
# backslash does too, as a shell joins the two lines in double quotes and a program joins
# them in its text. ``;`` and a closing bracket
# belong to the value too, as a password may hold them (``{password: a;b}``): a closing
# bracket ends it only where it closes a bracket open before the value (``_OpenBrackets``),
# as in ``connect(password=VALUE)``, and ``;`` only where it is an operator of a shell text.
# A run of ``;`` before a blank or the end of the text separates what follows, as it does
# after a word (``_separators_kept``), and is no part of the value.
_CODE_BARE = re.compile(r"""(?:\\[\s\S]|;++(?=\S)|[^\s'",;(\[\\)\]}])+""")
# A variable of Perl or PHP that a ``.`` joins to what comes after it, with blanks around the
# ``.`` or none, or a line break before or after it: a name, a quote, a backquote or another
# variable (``$x.q{...}``, ``$x . '...'``, ``$x.$y``, ``$x .`` and then ``'...'`` on the next
# line). Its ``$`` may have a backslash before it, as a shell writes it inside double quotes
# (``\$x.'...'``), and an element of an array or a hash may follow its name, with ``->`` or
# none (``$a[0]``, ``$x->[0]``, ``$x['k']``, ``$h{a}``).
_CODE_JOINED_VARIABLE = re.compile(
    r"""\\?\$[A-Za-z_][A-Za-z0-9_]*(?:(?:->)?(?:\[[^\]\n]*\]|\{[^}\n]*\}))*"""
    r"""(?=(?:[ \t]*\\?\r?\n)*[ \t]*\.(?:[ \t]*\\?\r?\n)*[ \t]*(?:[A-Za-z_$'"`]|\\\$))"""
)
_OPENING: Final[Mapping[str, str]] = {")": "(", "]": "[", "}": "{"}
_BRACKET = re.compile(r"[()\[\]{}]")
# The rest of a value in double quotes after its opening quote, up to its closing quote: a
# quote after a backslash does not close it (``"a\"b"``), as in a shell, JSON or a program.
_DOUBLE_QUOTED_REST = re.compile(r"""[^"\\]*(?:\\.[^"\\]*)*""", re.DOTALL)
# The same in single quotes, in the text of a program, where a backslash escapes ``'`` too.
_SINGLE_QUOTED_REST = re.compile(r"""[^'\\]*(?:\\.[^'\\]*)*""", re.DOTALL)
# The rest of a value in three quotes, as a program's string, up to the three that close
# it: one or two quotes, and a quote after a backslash, belong to it (``'''a';b'''``).
_TRIPLE_QUOTED_REST: Final[Mapping[str, re.Pattern[str]]] = {
    quote: re.compile(rf"""(?:[^{quote}\\]|\\.|{quote}(?!{quote}{quote}))*""", re.DOTALL)
    for quote in ("'", '"')
}
# The rest of a word of a shell text from a place in it, read with the shell's quotes and
# escapes, up to a blank or an operator; a quote that is not closed runs to the end of the text.
_SHELL_WORD_REST = re.compile(
    r"""(?:'[^']*'?|"[^"\\]*(?:\\[\s\S][^"\\]*)*"?|\\[\s\S]|[^\s'"\\;&|()<>`])*"""
)
# More of one statement after a value: ``= ...`` after a type, as in ``api_key: str = ...``.
_CODE_MORE = re.compile(_CODE_BLANKS + r""":?=""" + _CODE_BLANKS)
# What joins a value to more of the same value: a call or an index right after
# it (``os.getenv(...)``, ``x[...]``), a quote right after a quoted value
# (``'a''b'``), an attribute
# (``.strip()``), or ``+``, ``%``, ``or``, ``and``, ``if`` or ``else``
# (``'a' + '...'``, ``x or '...'``).
_CODE_JOIN = re.compile(
    r"""[ \t]*[+%][ \t]*|[ \t]+(?:or|and|if|else)[ \t]+|\.(?=[A-Za-z_])|(?=['"(\[])"""
)
# The prefix of a string in the text of a program, right before its opening quote:
# one or two of Python's letters (``f"..."``, ``rb'...'``, ``Rb"..."``, ``t"..."``),
# ``L`` or ``u8`` of C and C++, with the ``R`` of a raw string after them or not
# (``u8R"(...)"``, ``LR"(...)"``), and ``@`` or ``$`` of C# (``@"..."``, ``$@"..."``).
_STRING_PREFIX = r"""(?:[rRuUfFbBtT]{1,2}|u8R?|LR?|[@$]{1,2})"""
_PREFIXED_STRING = re.compile(_STRING_PREFIX + r"""(?=['"])""")
# The same string with a backslash before its opening quote, as a shell writes it inside
# a part in double quotes (``"... f\"...\" ..."``).
_ESCAPED_PREFIXED_STRING = re.compile(_STRING_PREFIX + r"""\\['"]""")
# A raw string of Rust: ``r#"..."#``, closed by ``"`` and as many ``#`` as opened it.
_RAW_STRING = re.compile(r"""b?r(#+)\"""")
# A quote-like word of Perl or a ``%`` of Ruby and the mark that opens what it quotes:
# ``q{...}``, ``qq/.../``, ``qw(...)``, ``qr/.../i``, ``m/.../``, ``%q{...}``,
# ``%Q(...)``, ``%w[...]``, ``%r{...}`` and ``%(...)``. ``s``, ``tr`` and ``y`` of Perl
# quote two parts, a pattern and what replaces it (``s/.../.../``, ``s{...}{...}``).
_QUOTE_LIKE = re.compile(r"""(?:q[qwrx]?|m|(s|tr|y)|%[qQwWiIr]?)([{(\[<]|[/|!#~'"])""")
# The same words of Perl after a name of Perl (``$token``, ``_perl_name``): Perl takes any
# mark that is no letter, digit, ``_``, blank or backslash, right after the word or after
# blanks (``q%...%``, ``qq;...;``, ``q {...}``). After blanks a ``#`` starts a comment and
# ``=``, ``,`` or ``;`` ends the word, so none of them opens a string there, and neither
# does the ``=`` of ``=>``, which quotes the word before it.
_PERL_QUOTE_LIKE = re.compile(
    r"""(?:q[qwrx]?|m|(s|tr|y))(?:(?!=>)([^\w\s\\])|[ \t]+([^\w\s\\#=,;]))"""
)
# What stands right before the name of a variable of Perl: ``$``, as in ``$token``, or a
# ``$`` and the name of a hash with its key's brace, as in ``$ENV{TOKEN}`` and
# ``$cfg->{'token'}``.
_PERL_NAME_LEAD = re.compile(r"""\$(?:[A-Za-z_][A-Za-z0-9_]*(?:->)?\{['"]?)?\Z""")
# How far before a name the ``$`` of ``_PERL_NAME_LEAD`` is looked for.
_PERL_LEAD_REACH: Final = 64


def _perl_name(text: str, at: int) -> bool:
    """Say whether the name at ``at`` in a text is the name of a variable of Perl (``$token``)."""
    return _PERL_NAME_LEAD.search(text, max(0, at - _PERL_LEAD_REACH), at) is not None


_CODE_PAIRS: Final[Mapping[str, str]] = {"{": "}", "(": ")", "[": "]", "<": ">"}
# The start of a here-document in the text of a program: ``<<WORD``, ``<<"WORD"``,
# ``<<'WORD'``, ``<<\WORD``, ``<<~WORD`` and ``<<-WORD`` of Perl and Ruby, and ``<<<WORD``
# of PHP.
_CODE_HERE_DOCUMENT = re.compile(r"""<<<?[-~]?[ \t]*\\?(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
# The rest of a string in backquotes after its opening one, up to its closing one.
_BACKQUOTED_REST = re.compile(r"""[^`\\]*(?:\\.[^`\\]*)*""", re.DOTALL)
# The flags after a pattern or a quote-like word of Perl or Ruby (``/.../i``).
_PATTERN_FLAGS = re.compile(r"[A-Za-z]*")
_TAB_OR_SPACE_RUN = re.compile(r"[ \t]*")
# What joins a string to the next string of the same value in the text of a program:
# blanks, as in ``"a" "b"`` of Python and C, or ``.`` or ``..``, with blanks around it or
# not, as in ``"a" . "b"`` of Perl and PHP, before a quote, a backquote or a prefixed string,
# and ``.`` before a quote-like word of Perl or Ruby too, as in ``'a' . q{...}``, before
# a variable of Perl or PHP, as in ``'a' . $x . '...'``, or before a here-document of Perl
# or PHP, as in ``'a' . <<'EOT'`` and ``'a' . <<<EOT``.
_CODE_STRING_JOIN = re.compile(
    r"""(?:[ \t]*\.\.?[ \t]*(?=(?:q[qwr]?|%[qQ]?)[ \t]*[^\w\s\\])|"""
    r"""[ \t]*\.[ \t]*(?=\\?\$[A-Za-z_{]|<<<?[-~]?[ \t]*\\?['"]?[A-Za-z_])|"""
    r"""(?:[ \t]*\.\.?[ \t]*|[ \t]+)(?=""" + _STRING_PREFIX + r"""?['"`]))"""
)
# The same across the end of a line, in the text of a program: ``.``, ``..`` or ``+`` at the
# end of one line or at the start of the next (``'a' .``, then ``'...'``; ``'a'``, then
# ``. '...'``), or a backslash at the end of a line, which carries the statement on to the
# next one, as in Python and Ruby (``'a' \``, then ``'...'``). A line break with nothing of
# these joins no string, since it may end the statement.
_CODE_LINE_JOIN = re.compile(
    r"""(?:[ \t]*(?:\.\.?|\+)(?:[ \t]*\\?\r?\n)+[ \t]*"""
    r"""|(?:[ \t]*\\?\r?\n)+[ \t]*(?:\.\.?|\+)(?:(?:[ \t]*\\?\r?\n)+[ \t]*|[ \t]*)"""
    r"""|(?:[ \t]*\\\r?\n)+[ \t]*)"""
    r"""(?=""" + _STRING_PREFIX + r"""?['"`]|(?:q[qwr]?|%[qQ]?)[ \t]*[^\w\s\\]|\\?\$[A-Za-z_{])"""
)
_CLOSING: Final[Mapping[str, str]] = {"(": ")", "[": "]", "{": "}"}


class _OpenBrackets:
    """Count the brackets of each kind open before a place in a text, the places asked in order.

    A closing bracket with none of its kind open is passed over. The text is
    read once, and only as far as the places asked, so a text whose values
    hold no closing bracket is not read at all.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._marks: Iterator[re.Match[str]] | None = None
        self._ahead: re.Match[str] | None = None
        self._open = dict.fromkeys(_CLOSING, 0)

    def before(self, at: int) -> Mapping[str, int]:
        """Return how many brackets of each opening kind are open before ``at``."""
        if self._marks is None:
            self._marks = _BRACKET.finditer(self._text)
            self._ahead = next(self._marks, None)
        while self._ahead is not None and self._ahead.start() < at:
            mark = self._ahead.group()
            if mark in self._open:
                self._open[mark] += 1
            else:
                opener = _OPENING[mark]
                self._open[opener] = max(0, self._open[opener] - 1)
            self._ahead = next(self._marks, None)
        return self._open


def _quoted_value_end(text: str, at: int, *, code: bool = False) -> int:
    """Return where the value in quotes that starts at ``at`` ends: after its closing quote.

    A ``"`` after a backslash does not close a value in double quotes; in the
    text of a program (``code``) a ``'`` after a backslash does not close one
    in single quotes either, while a shell's single quotes hold no escape. A
    value that opens with three quotes, as a program's string may, ends at the
    three that close it (``_TRIPLE_QUOTED_REST``). In a shell's text the same
    quotes are an empty string and the opening quote of the next, so there
    the value runs at least to the end of the shell word
    (``_SHELL_WORD_REST``): ``'''a'b''' VALUE'`` is one word there. A value
    that is not closed runs to the end of the text.
    """
    quote = text[at]
    if text.startswith(quote * 3, at):
        inside = _TRIPLE_QUOTED_REST[quote].match(text, at + 3)
        close = inside.end() if inside is not None else at + 3
        end = close + 3 if text.startswith(quote * 3, close) else len(text)
        if not code:
            word = _SHELL_WORD_REST.match(text, at)
            if word is not None:
                end = max(end, word.end())
        return end
    if quote == '"' or code:
        rest = (_DOUBLE_QUOTED_REST if quote == '"' else _SINGLE_QUOTED_REST).match(text, at + 1)
        close = rest.end() if rest is not None else at + 1
        return close + 1 if close < len(text) else len(text)
    close = text.find(quote, at + 1)
    return len(text) if close < 0 else close + 1


def _backquoted_value_end(text: str, at: int) -> int:
    """Return where the value in backquotes that starts at ``at`` ends.

    It ends after the backquote that closes it, as a template string of
    JavaScript and a command of Perl or of a shell do. A character after a
    backslash does not close it, and neither does a backquote inside a
    ``${...}`` part, which runs to the ``}`` that closes it and may hold
    strings, braces and templates of its own. A value that is not closed
    runs to the end of the text. The text is read once.
    """
    # Each part open at a place: a backquote for a template, ``{`` for a ``${...}`` part or
    # a brace in one, or the quote of a string in one.
    open_parts = ["`"]
    i = at + 1
    while i < len(text):
        char = text[i]
        inside = open_parts[-1]
        if char == "\\":
            i += 2
            continue
        if inside in _QUOTES:
            if char == inside:
                open_parts.pop()
        elif inside == "`":
            if char == "`":
                open_parts.pop()
                if not open_parts:
                    return i + 1
            elif text.startswith("${", i):
                open_parts.append("{")
                i += 1
        elif char in "`{" or char in _QUOTES:
            open_parts.append(char)
        elif char == "}":
            open_parts.pop()
        i += 1
    return len(text)


def _code_value_end(
    text: str,
    at: int,
    stops: Sequence[int] = (),
    brackets: _OpenBrackets | None = None,
    *,
    code: bool = False,
    quoted: Sequence[tuple[int, int]] = (),
    program: bool = False,
    lines: _LineEnds | None = None,
    perl: bool = False,
) -> int | None:
    """Return where the value that starts at ``at`` in a program's text ends, or ``None``.

    A quoted value ends at its closing quote (``_quoted_value_end``, which
    ``code`` steers) and a value in brackets at its closing bracket, quoted
    brackets aside; either runs to the end of the text when it is not
    closed. A value in backquotes, a template string or a command of a
    program or of a shell, ends at the backquote that closes it
    (``_backquoted_value_end``); where more of the same word is glued after
    that backquote, the rest is read on as a bare value, so all of the value
    in ``{password: `a`b}`` is hidden. Any other value is bare (``_CODE_BARE``):
    ``;`` belongs to it, and a closing bracket ends it only where it closes
    a bracket open before it (``brackets``, made from the text when none is
    given), so ``{password: a;b)c}`` hides all of ``a;b)c``. In a shell
    text it also ends at the first of ``stops``, the operators of the text
    (``_operator_spans``), after its start. A value that starts with a
    backslash, or a quote that only holds the other quote (``'"'``), is how
    a shell writes a quote inside a quoted word: it is left to the reading
    of that word without its quotes, and ``None`` is returned. So is a
    string with a prefix whose opening quote a backslash escapes inside one
    of the ``quoted`` parts in double quotes (``"token = f\\"...\\""``).
    In the text of a program (``code``) a string that a mark of its own
    opens ends where that mark says (``_code_string_end``), and so does a string in three
    quotes, at its three closing quotes. In any other text such a string is
    read so only inside one of the ``quoted`` parts of the text (each as
    (its opening quote, its closing quote), as ``_quoted_parts`` gives
    them), as the text of a program after ``sh -c '... -e '...''`` is: it
    ends inside that part. There a pattern in ``/`` is read so only for a
    value given as a program gives it (``program``: ``$token = /.../``,
    ``token =~ /.../``), and a string given as a shell gives it
    (``NAME=q/...``) ends nowhere its last ``/`` starts a path
    (``_starts_path``). ``lines`` finds the ends of the lines of the text
    (``_LineEnds``). ``perl`` says that the value is given to a name of Perl
    (``_perl_name``), whose quote-like words take any mark. A string a mark
    of its own opens that a ``.`` follows ends there, though the bare
    reading runs on, so what the ``.`` joins to it is read as a piece of
    its own (``_code_expression_end``): ``q{a}.q{...}``. So does a variable
    of Perl or PHP that a ``.`` follows (``_CODE_JOINED_VARIABLE``):
    ``$x.q{...}``.
    """
    first = text[at : at + 1]
    joined = _CODE_JOINED_VARIABLE.match(text, at) if code or perl else None
    if joined is not None and joined.end() <= _stop_after(stops, at, len(text)):
        # A variable a ``.`` follows ends there, and what the ``.`` joins to it is read as a
        # piece of its own (``_code_expression_end``): ``$x.q{...}``.
        return joined.end()
    if first == "\\":
        return None
    if not code and _ESCAPED_PREFIXED_STRING.match(text, at) is not None:
        close = _quoted_part_end(at, quoted)
        if close is not None and text[close : close + 1] == '"':
            return None
    start = at
    if first == "`":
        start = _backquoted_value_end(text, at)
        if start >= len(text) or text[start].isspace() or text[start] in ";,)]}":
            return start
    if first in _QUOTES and first:
        between = text[at + 1 : at + 2]
        if between in _QUOTES and between not in ("", first) and text[at + 2 : at + 3] == first:
            return None
        if code and text.startswith(first * 3, at):
            close = text.find(first * 3, at + 3)
            return len(text) if close < 0 else close + 3
        return _quoted_value_end(text, at, code=code)
    if first in _CLOSING:
        depth = 0
        quote = ""
        for i in range(at, len(text)):
            char = text[i]
            if quote:
                quote = "" if char == quote else quote
            elif char in _QUOTES:
                quote = char
            elif char in _CLOSING:
                depth += 1
            elif char in _CLOSING.values():
                depth -= 1
                if depth == 0:
                    return i + 1
        return len(text)
    limit = _stop_after(stops, start, len(text))
    # The value is read in pieces between closing brackets, and no further than one
    # character past the operator that ends it, so a text of many values is read once.
    end = start
    while True:
        piece = _CODE_BARE.match(text, end, limit + 1)
        if piece is not None:
            end = piece.end()
        if end >= limit or text[end] not in _OPENING:
            break
        open_before = (_OpenBrackets(text) if brackets is None else brackets).before(at)
        if open_before[_OPENING[text[end]]]:
            break
        end += 1
    end = min(end, limit)
    bound = len(text) if code else _quoted_part_end(at, quoted)
    if bound is not None:
        # A string a mark of its own opens is hidden to its end, and never less of it
        # than the bare reading takes.
        marked = _code_string_end(
            text, at, bound, pattern=code or program, lines=lines or _LineEnds(text), perl=perl
        )
        if (
            marked is not None
            and (marked > end or ((code or perl) and marked < end and text[marked] == "."))
            and (code or program or not _starts_path(text, at, marked))
        ):
            return marked
    return end if end > at else None


def _stop_after(stops: Sequence[int], at: int, default: int) -> int:
    """Return the first of ``stops`` at or after ``at``, or ``default`` if none is."""
    stop = bisect.bisect_left(stops, at)
    return stops[stop] if stop < len(stops) else default


def _quoted_parts(text: str) -> list[tuple[int, int]]:
    """Return each part of a shell text in quotes, as (its opening quote, its closing quote).

    The parts are read as a shell reads them (``_QUOTED_PART``), and a part
    that nothing closes ends at the end of the text.
    """
    parts: list[tuple[int, int]] = []
    for found in _QUOTED_PART.finditer(text):
        quote = found.group()[0]
        if quote not in _QUOTES:
            continue
        closed = len(found.group()) > 1 and found.group().endswith(quote)
        parts.append((found.start(), found.end() - 1 if closed else len(text)))
    return parts


def _quoted_part_end(at: int, quoted: Sequence[tuple[int, int]]) -> int | None:
    """Return the closing quote of the one of ``quoted`` that ``at`` lies inside, or ``None``."""
    index = bisect.bisect_right(quoted, (at, math.inf)) - 1
    if index < 0 or not quoted[index][0] < at < quoted[index][1]:
        return None
    return quoted[index][1]


# What may stand between a blank and the ``/`` that starts a path: ``.``, ``..`` or ``~``.
_PATH_LEAD = re.compile(r"(?:\.\.?|~)?\Z")


def _starts_path(text: str, at: int, end: int) -> bool:
    """Say whether the last mark of a string from ``at`` to ``end`` is a ``/`` that starts a path.

    It does where the ``/`` comes right after a blank, ``=`` or ``:``, or
    after ``.``, ``..`` or ``~`` that come right after one, as in ``/a ./b``,
    ``/a --out=/b`` and ``/a http://b``: the string is no pattern but a word
    and the start of the next one, as a shell reads them.
    """
    body = text[at:end].rstrip(string.ascii_letters)
    if not body.endswith("/") or len(body) < 2:
        return False
    before = body[:-1]
    lead = _PATH_LEAD.search(before)
    rest = before[: lead.start()] if lead is not None else before
    return rest.endswith((" ", "\t", "=", ":"))


class _LineEnds:
    """Find where the line that holds a place in a text ends, the places asked mostly in order.

    The text after the last place asked is read again only past the line end
    found for it, so asking for each place of a long line reads it once.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._from = 0
        self._end = -1

    def after(self, at: int) -> int:
        """Return the place of the first line break at ``at`` or after it, or the text's length."""
        if not self._from <= at <= self._end:
            found = self._text.find("\n", at)
            self._from = at
            self._end = len(self._text) if found < 0 else found
        return self._end


def _delimited_end(
    text: str, opening: int, bound: int, lines: _LineEnds, *, one_line: bool = True
) -> int | None:
    """Return where what the mark at ``opening`` opens ends: after the mark that closes it.

    A bracket (``{``, ``(``, ``[``, ``<``) is closed by its pair, with the
    pairs inside it counted, and what it opens runs to ``bound`` when nothing
    closes it before. Any other mark is closed by the next one of the same on
    its line (on any line before ``bound`` without ``one_line``), and
    ``None`` is returned when there is none. A mark after a backslash closes
    nothing.
    """
    mark = text[opening]
    pair = _CODE_PAIRS.get(mark)
    if pair is None:
        line_end = min(lines.after(opening + 1), bound) if one_line else bound
        at = opening + 1
        while True:
            close = text.find(mark, at, line_end)
            if close < 0:
                return None
            escapes = 0
            while text[close - 1 - escapes] == "\\":
                escapes += 1
            if escapes % 2 == 0:
                return close + 1
            at = close + 1
    depth = 0
    at = opening
    while at < bound:
        char = text[at]
        if char == "\\":
            at += 2
            continue
        if char == mark:
            depth += 1
        elif char == pair:
            depth -= 1
            if depth == 0:
                return at + 1
        at += 1
    return bound


def _code_string_end(
    text: str, at: int, bound: int, *, pattern: bool, lines: _LineEnds, perl: bool = False
) -> int | None:
    """Return where a string of a program's text that a mark of its own opens at ``at`` ends.

    The marks are a backquote (``\\`...\\```), a raw string of Rust
    (``r#"..."#``), a prefix before a quote (``_STRING_PREFIX``: ``f"..."``,
    ``rb'...'``, ``@"..."``), a quote-like word of Perl or a ``%`` of Ruby
    and its mark (``q{...}``, ``qq/.../``, ``m/.../``, ``s/.../.../``,
    ``%q(...)``), with ``pattern`` a pattern (``/.../``), and a
    here-document, whose value runs to the end of the line that holds its
    end word (``<<EOT`` ... ``EOT``). The flags after a pattern or a
    quote-like word (``/.../i``) are part of it. A string that nothing
    closes runs to ``bound``, except one whose mark is no bracket, which
    ends on its line: ``None`` is returned for it, and for a value that opens
    with none of these marks. Nothing past ``bound`` is read. With ``perl``
    a quote-like word of Perl takes any mark, after blanks or not
    (``_PERL_QUOTE_LIKE``), and one whose mark is no bracket may close on a
    later line (``q/...`` on one line, ``.../`` on the next).
    """
    first = text[at : at + 1]
    if first == "`":
        rest = _BACKQUOTED_REST.match(text, at + 1, bound)
        close = rest.end() if rest is not None else at + 1
        return close + 1 if close < bound else bound
    raw = _RAW_STRING.match(text, at, bound)
    if raw is not None:
        close = text.find('"' + raw.group(1), raw.end(), bound)
        return bound if close < 0 else close + 1 + len(raw.group(1))
    prefixed = _PREFIXED_STRING.match(text, at, bound)
    if prefixed is not None:
        quote = prefixed.end()
        mark = text[quote]
        if text.startswith(mark * 3, quote, bound):
            close = text.find(mark * 3, quote + 3, bound)
            return bound if close < 0 else close + 3
        rest = (_DOUBLE_QUOTED_REST if mark == '"' else _SINGLE_QUOTED_REST).match(
            text, quote + 1, bound
        )
        close = rest.end() if rest is not None else quote + 1
        return close + 1 if close < bound else bound
    like = _QUOTE_LIKE.match(text, at, bound)
    if like is None and perl:
        like = _PERL_QUOTE_LIKE.match(text, at, bound)
    opening = -1
    if like is not None:
        # The mark right after the word, or the one after blanks (``_PERL_QUOTE_LIKE``).
        opening = like.start(2) if like.group(2) is not None else like.start(3)
    elif first == "/" and pattern:
        opening = at
    if opening >= 0:
        # A quote-like word given to a name of Perl may run over lines, as Perl reads it.
        one_line = not (perl and like is not None)
        ends = _delimited_end(text, opening, bound, lines, one_line=one_line)
        if ends is None:
            return None
        if like is not None and like.group(1) and ends < bound:
            # The second part of ``s``, ``tr`` or ``y``: up to the next of the same mark
            # (``s/.../.../``), or in a bracket of its own after blanks (``s{...} {...}``).
            second = ends - 1
            if text[opening] in _CODE_PAIRS:
                blanks = _TAB_OR_SPACE_RUN.match(text, ends, bound)
                second = blanks.end() if blanks is not None else ends
            if second < bound and (text[second] == text[opening] or text[second] in _CODE_PAIRS):
                replaced = _delimited_end(text, second, bound, lines, one_line=one_line)
                ends = ends if replaced is None else replaced
        flags = _PATTERN_FLAGS.match(text, ends, bound)
        return flags.end() if flags is not None else ends
    here = _CODE_HERE_DOCUMENT.match(text, at, bound)
    if here is not None:
        line_end = lines.after(here.end())
        if line_end >= bound:
            return None
        word = re.escape(here.group(2))
        last = re.compile(rf"^[ \t]*{word}[ \t;,)]*$", re.MULTILINE).search(
            text, line_end + 1, bound
        )
        return bound if last is None else last.end()
    return None


def _code_expression_end(
    text: str,
    at: int,
    stops: Sequence[int] = (),
    brackets: _OpenBrackets | None = None,
    *,
    code: bool = False,
    quoted: Sequence[tuple[int, int]] = (),
    program: bool = False,
    lines: _LineEnds | None = None,
    perl: bool = False,
) -> int | None:
    """Return where the value that starts at ``at`` ends with all that ``_CODE_JOIN`` joins to it.

    ``os.getenv('X', '...')``, ``'a' + '...'`` and ``x or '...'`` are each
    one value, so a default or a part written after the first piece is
    hidden with it; so is what is joined to a value hidden before. ``None``
    as ``_code_value_end`` says; ``stops``, ``brackets``, ``code``,
    ``quoted``, ``program``, ``lines`` and ``perl`` as it says too,
    ``program`` for the first piece only. In the text of a
    program (``code``) a string written after a string, with blanks, ``.``
    or ``..`` between them (``_CODE_STRING_JOIN``),
    is part of the same value, as ``"a" "..."`` and ``"a" . "..."`` are, and
    so is a string right after a value hidden before, or after one with
    blanks or ``.`` between them, as the string after a prefix or a first
    string that an earlier reading hid. A string after a quote-like word,
    and a quote-like word after a string and a ``.``, are joined the same
    way: ``q{a} . '...'``, ``%q{a} '...'`` and ``'a' . q{...}``.
    """
    piece = at
    if text.startswith(HIDDEN, at):
        end: int | None = at + len(HIDDEN)
    else:
        end = _code_value_end(
            text,
            at,
            stops,
            brackets,
            code=code,
            quoted=quoted,
            program=program,
            lines=lines,
            perl=perl,
        )
    while end is not None:
        # A string, or a value hidden before, may have more strings joined to it.
        joins_strings = (
            code
            and end > at
            and (
                text[end - 1] in "'\"`"
                or text.endswith(HIDDEN, at, end)
                or _QUOTE_LIKE.match(text, piece) is not None
                or (perl and _PERL_QUOTE_LIKE.match(text, piece) is not None)
            )
        )
        # A variable of Perl or PHP (``$x``) has more joined to it with a ``.`` only.
        variable = code and end > at and not joins_strings and text[piece] in "$\\"
        join = _CODE_LINE_JOIN.match(text, end) if joins_strings or variable else None
        if join is None:
            join = _CODE_JOIN.match(text, end)
        if join is None and (joins_strings or variable):
            join = _CODE_STRING_JOIN.match(text, end)
        if join is not None and variable and "." not in join.group():
            join = _CODE_JOIN.match(text, end)
        if join is None:
            break
        if (
            join.end() == end
            and text[end] in _QUOTES
            and text[end - 1] not in _QUOTES
            and not (code and text.endswith(HIDDEN, at, end))
            and not (code and text[piece] == "$" and text[end - 1] == ".")
        ):
            # A quote right after a bare value closes the text around it, unless the value
            # is a variable that a ``.`` joins to the quote (``$x.'...'``).
            break
        opening = text[join.end() : join.end() + 1]
        if opening and opening in _QUOTES and text.find(opening, join.end() + 1) < 0:
            # A quote that nothing closes after it closes the text around the value.
            break
        more = _code_value_end(
            text, join.end(), stops, brackets, code=code, quoted=quoted, lines=lines, perl=perl
        )
        if more is None:
            break
        piece = join.end()
        end = more
    return end


# The token after an Authorization scheme word given as a bare value: the next word, after
# blanks on the same line, that starts no option and holds no quote, operator or escape.
_SCHEME_TOKEN = re.compile(r"""([ \t]+)[^\s'"`\\;&|()<>-][^\s'"`\\;&|()<>]*""")


def _hidden_value(value: str) -> str:
    """Return a value of a program's text hidden, keeping the quotes around it."""
    quote = value[:1] if value[:1] in _QUOTES else ""
    close = quote if quote and len(value) > 1 and value.endswith(quote) else ""
    return f"{quote}{HIDDEN}{close}"


def _hidden_code(
    text: str, *, shell: bool = False, shell_words: bool = False, code: bool = False
) -> str:
    """Hide the value a credential-like name is given in the text of a program.

    ``os.environ['API_KEY'] = '...'``, ``{"api_key": "..."}``,
    ``API_KEY == '...'`` and ``setdefault('HF_TOKEN', '...')`` keep the name
    and lose the value; after a type, as in ``api_key: str = '...'``, the
    value that follows ``=`` is hidden too. A value in quotes or brackets is
    hidden whole, as in ``auth=('user', '...')``, and so is a value built of
    several pieces, as ``os.getenv('X', '...')`` and ``'a' + '...'``
    (``_code_expression_end``). With ``shell_words``, or ``shell``, the
    words of the text end where a shell's words end, so a value given with
    ``=`` ends with its shell word (``_gives_no_value``). The text is read as it
    stands first; then each quoted word of it, as the program after
    ``sh -c 'python -c ...'``, is read without its shell quotes, and when a
    value is hidden there that the first reading missed, the word is shown
    quoted afresh. With ``shell`` the text is a shell text, and a bare
    value ends at an operator that ends a command (``_operator_spans``); an
    operator is no part of the word before it. A quoted word is a shell text
    of its own only when it is the text after ``-c`` of a shell
    (``_ShellText``). Its words end as a shell's do when the words before it
    say so as a command's do (``_CommandWalk.shell_word``), as the remote
    command of ``ssh`` in ``sh -c "ssh HOST '...'"``. A bare value holds
    ``;`` but where it is an operator of a shell text, and ends at a closing
    bracket only where that closes one open before it (``_code_value_end``),
    so ``tool --config '{password: a;b}'`` hides all of ``a;b``, in a shell
    text too. With ``code`` the text is a program's, unless its words end as
    a shell's. A backslash escapes a quote in single quotes as well as in
    double quotes, as in a program or a setting, except in a text whose
    words end as a shell's, whose single quotes hold no escape. In a shell
    text a command substitution (``$(...)``, a text in backquotes, ``<(...)``)
    is one word of the text around it, and its inner text is a shell text of
    its own, read afresh (``_substitutions_masked``), as ``_hidden_words``
    reads them: the quotes inside ``x="$(eval "...")"`` are the inner text's.
    """
    masked = _substitutions_masked(text) if shell else None
    if masked is not None:
        outer, pieces = masked
        shown = _hidden_code(outer, shell=True, code=code)
        return _substitutions_restored(
            shown, pieces, lambda inner: _hidden_code(inner, shell=True, code=code)
        )
    shell_words = shell_words or shell
    # Only a text whose words do not end as a shell's is a program's (``python -c``).
    code = code and not shell_words
    if shell_words and "<<" in text:
        text = _hidden_documents(text)
    text = _hidden_code_here(
        text, shell=shell, shell_words=shell_words, code=not shell_words, axis=not code
    )
    out: list[str] = []
    end = 0
    shells = _ShellText()
    walk = _CommandWalk(ahead=text) if any(char in text for char in "'\"\\") else None
    # Only a word with a quote or an escape is read again (``_hidden_code_word``), so the
    # reading stops after the last such word and the rest of the text is shown as it is.
    last = max(text.rfind(char) for char in "'\"\\")
    for found in (_SHELL_TOKEN if shell else _SHELL_WORD).finditer(text):
        if found.start() > last:
            break
        between = text[end : found.start()]
        if found.lastgroup == "operator" or _breaks_line(between):
            shells = _ShellText()
            if walk is not None:
                walk.reset() if found.lastgroup == "operator" else walk.end_line()
        out.append(between)
        end = found.end()
        if found.lastgroup == "operator":
            out.append(found.group(0))
            continue
        word = found.group(0)
        nested = shells.read(word)
        nested_words = nested
        # A quoted word of a program's text is read as a program's too, and so is the text
        # after ``-c`` of a program that is no shell (``python -c``) in any text.
        program = code
        axis_value = False
        if walk is not None:
            axis_value = not code and walk.axis and _axis_value(word, axis=True)
            nested = walk.shell_run(word) or nested
            nested_words = walk.shell_word(word) or nested
            program = program or (walk.code(word) and not nested_words)
            walk.read(word, token=shell)
        if axis_value:
            # The axis ``Key`` after an axis option keeps its values; what else the word
            # holds was read with the text (``_after_axis_option``).
            out.append(word)
            continue
        out.append(
            _hidden_code_word(
                word, shell=shell, nested=nested, nested_words=nested_words, code=program
            )
        )
    out.append(text[end:])
    return "".join(out)


def _hidden_documents(text: str) -> str:
    """Hide the credentials of each here-document of a shell text, read as the text of a program.

    The lines of a here-document (``_here_documents``) are the text a program
    reads, as the script after ``perl <<'END'``: they are read as
    ``_hidden_code`` reads the text after ``perl -e``, so a string a mark of
    its own opens, a pattern, and a string joined to another are hidden
    whole there too.
    """
    out: list[str] = []
    end = 0
    for start, stop in _here_documents(text):
        out.append(text[end:start])
        out.append(_hidden_code(text[start:stop], code=True))
        end = stop
    out.append(text[end:])
    return "".join(out)


def _hidden_code_word(
    word: str,
    *,
    shell: bool = False,
    nested: bool = False,
    nested_words: bool = False,
    code: bool = False,
) -> str:
    """Hide the credentials of one shell word read without its quotes, as ``_hidden_code`` says.

    ``nested`` says that the word is the text after ``-c`` of a shell, which
    is read as a shell text, and ``nested_words`` that the words of the word
    without its quotes end as a shell's do; the word as it stands, quotes
    and all, is read as what it holds. With ``code`` the word without its
    quotes is the text of a program, as the one after ``python -c``. With
    ``shell`` the word is one of a shell text, and a ``)`` or a backquote
    outside quotes that closes a command (``_subshell_closed``) is no part of
    it: the word before it is read, and what follows is kept as it stands, so
    ``(eval '...')`` keeps its ``)`` after the quoted text.
    """
    if not any(char in word for char in "'\"\\"):
        return word
    if shell:
        head, closed = _subshell_closed(word)
        if closed and head:
            return (
                _hidden_code_word(
                    head, shell=shell, nested=nested, nested_words=nested_words, code=code
                )
                + closed
            )
    try:
        parts = _shell_split(word)
    except ValueError:
        return word
    if len(parts) != 1:
        return word
    inner = _hidden_code(parts[0], shell=nested, shell_words=nested_words, code=code)
    if inner == parts[0]:
        return word
    as_is = _hidden_code_here(word, shell=shell, shell_words=nested_words, axis=not code)
    try:
        same = _shell_split(as_is) == [inner]
    except ValueError:
        same = False
    return as_is if same else shlex.quote(inner)


# A single quote that closes a part in single quotes and a single quote written right after
# it, escaped or in double quotes, as a text in single quotes writes one: ``'\\''``, ``'"'"'``.
_QUOTE_IN_QUOTES = re.compile(r"""'(?:\\'|"'")""")


def _hidden_code_here(
    text: str,
    *,
    shell: bool = False,
    shell_words: bool = False,
    code: bool = False,
    axis: bool = False,
) -> str:
    """Hide the value a credential-like name is given in a text, read as it stands.

    With ``shell_words`` the words of the text end as a shell's do, as
    ``_gives_no_value`` says; with ``shell`` a bare value ends at an
    operator that ends a command, and also where ``_code_value_end`` says.
    Without ``shell`` a bare value ends at an operator of a shell text
    inside a quoted word of the text, as in ``env -S "sh -c
    'API_KEY=VALUE;./bench'"`` (``_operator_spans``). With ``code`` a
    backslash escapes a quote in single quotes too (``_quoted_value_end``).
    With ``axis`` the axis ``Key`` after an axis option keeps its values
    (``_after_axis_option``). Without ``code`` a string a mark of its own
    opens, as ``q{...}`` or ``m/.../`` of Perl, is read whole only inside a
    quoted part of the text (``_quoted_parts``), as the text of a program
    there is, and a pattern in ``/`` only for a name given its value as a
    program gives it (``$token = /.../``, ``token =~ /.../``).
    """
    documents = _here_documents(text) if shell_words and "<<" in text else []
    matches: tuple[tuple[Callable[[str], Iterator[re.Match[str]]], int], ...] = (
        (_code_assignments, 1),
        (_CODE_ARGUMENT.finditer, 2),
    )
    for found_in, group in matches:
        out: list[str] = []
        end = 0
        # The operators are read once a value is to be hidden. A text that is no shell text
        # holds one only in a quoted word that a shell runs, so only in a text with a quote
        # and the name of a shell or of a program that runs a shell text.
        stops: list[int] | None = None
        brackets = _OpenBrackets(text)
        lines = _LineEnds(text)
        # The quoted parts of a text that is no program's are read once a value is to be
        # hidden, and only in a text with a quote: a string a mark of its own opens is read
        # whole only inside one (``_code_value_end``).
        quoted: list[tuple[int, int]] | None = None
        for found in found_in(text):
            if found.start() < end or not looks_like_credential(found.group(group).lstrip("-")):
                continue
            if found_in is _code_assignments and (
                _gives_no_value(found, text, shell_words=shell_words, documents=documents)
                or (axis and _after_axis_option(text, found.start()))
            ):
                continue
            if stops is None:
                stops = (
                    [one for one, _ in _operator_spans(text, shell=shell)]
                    if shell
                    or (
                        any(quote in text for quote in _QUOTES)
                        and _names_shell_runner(_plain_word(text))
                    )
                    else []
                )
            if quoted is None:
                quoted = (
                    _quoted_parts(text)
                    if not code and any(quote in text for quote in _QUOTES)
                    else []
                )
            # A name given its value as a program gives it (``$token = ...``,
            # ``token =~ ...``, ``token==...``), not as a shell does (``NAME=value``, the
            # sign right after the name).
            program = found_in is _code_assignments and not (
                found.group(3) in ("=", ":") and found.end(1) == found.start(3)
            )
            # A name of Perl (``$token``) takes a quote-like word with any mark.
            perl = found_in is _code_assignments and _perl_name(text, found.start())
            at = found.end()
            if (
                shell_words
                and _QUOTE_IN_QUOTES.match(text, at)
                and _quoted_part_end(found.start(), quoted) == at
            ):
                # The value closes the quotes the name stands in to quote itself one level
                # down (``'NAME='\\''VALUE'\\'' tool'``): it is read in the word without its
                # quotes, as the program that word goes to reads it.
                continue
            out.append(text[end:at])
            while True:
                value_end = _code_expression_end(
                    text,
                    at,
                    stops,
                    brackets,
                    code=code,
                    quoted=quoted,
                    program=program,
                    lines=lines,
                    perl=perl,
                )
                if value_end is None:
                    break
                value = text[at:value_end]
                out.append(_hidden_value(value))
                at = value_end
                # An Authorization scheme word given as the value has its token after it. In a
                # shell text the comparison reads the word after it as typed, as a command or
                # an argument may stand there.
                scheme = value.lower() in AUTH_SCHEME_WORDS and (
                    _ALL_HIDDEN.get() or not (shell or shell_words)
                )
                token = _SCHEME_TOKEN.match(text, at) if scheme else None
                if token is not None:
                    out.append(token.group(1) + HIDDEN)
                    at = token.end()
                more = _CODE_MORE.match(text, at)
                if more is None:
                    break
                out.append(more.group(0))
                at = more.end()
            end = at
        out.append(text[end:])
        text = "".join(out)
    return text


# The random-looking rule: a value this long or longer may be hidden by its shape alone.
RANDOM_MIN_LENGTH: Final = 32
# A random-looking value changes kind of character (capital, small letter,
# digit) between neighbours at least once in this many characters.
RANDOM_CHANGE_EVERY: Final = 3
# A random-looking value has a capital followed by another capital or a digit
# at least this many times; many words written in CamelCase have none.
RANDOM_MIN_CAPITAL_PAIRS: Final = 1
# A word, to the random-looking rule: a capital followed by at least this many
# small letters, as in ``Tensor``, or by two small letters one of which is a
# vowel of ``RANDOM_WORD_VOWELS``, as in ``Get``.
RANDOM_WORD_SMALL_LETTERS: Final = 3
RANDOM_WORD_VOWELS: Final = "aeiouy"
# A value whose words cover this percentage of its characters or more is
# written in words, as a name in CamelCase is, and is shown.
RANDOM_WORDS_SHOWN_PERCENT: Final = 60
# The length of a commit id in hexadecimal: hexadecimal of this length is shown on its own,
# and in a path right after a folder of ``COMMIT_ID_FOLDERS``.
COMMIT_ID_LENGTH: Final = 40
# The names of digests: hexadecimal right after one of them and a ``:``,
# ``=``, ``/`` or ``-`` is a digest and is shown, as in ``sha256:...``.
DIGEST_NAMES: Final[tuple[str, ...]] = (
    "md5",
    "sha1",
    "sha224",
    "sha256",
    "sha384",
    "sha512",
    "blake2b",
    "blake2s",
    "blake3",
)
# An AWS access key id is one of these prefixes, which AWS's page of IAM identifiers gives
# for an access key and a temporary access key, and capitals or digits to this length in all.
# It is hidden by its shape, though it is shorter than ``RANDOM_MIN_LENGTH``.
ACCESS_KEY_ID_PREFIXES: Final[tuple[str, ...]] = ("AKIA", "ASIA")
ACCESS_KEY_ID_LENGTH: Final = 20
_ACCESS_KEY_ID = re.compile(
    "(?:"
    + "|".join(ACCESS_KEY_ID_PREFIXES)
    + rf")[A-Z0-9]{{{ACCESS_KEY_ID_LENGTH - len(ACCESS_KEY_ID_PREFIXES[0])}}}"
)
# A run of the characters of a token: letters, digits, ``+``, ``/``, ``_``,
# ``-`` and percent escapes such as ``%2F``, with up to two ``=`` of padding
# at its end.
_TOKEN_RUN = re.compile(r"(?:[A-Za-z0-9+/_-]|%[0-9A-Fa-f]{2})+(?:={1,2}(?![A-Za-z0-9+/_=%-]))?")
# The fewest characters of a value that ``looks_random`` hides: an access key id, or any other
# value of ``RANDOM_MIN_LENGTH``. A shorter token run holds no such value, and neither does the
# text its percent escapes stand for, which is shorter than the run.
_SHORTEST_RANDOM: Final = min(ACCESS_KEY_ID_LENGTH, RANDOM_MIN_LENGTH)
# Characters in a row that a token run of ``_SHORTEST_RANDOM`` or more is made of: a text with no
# such row holds no token run long enough to hold a random-looking value.
_LONG_RUN = re.compile(rf"[A-Za-z0-9+/_%=-]{{{_SHORTEST_RANDOM},}}")
# A percent escape of an address, as in ``%2F`` for ``/``.
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
# The letters and digits of a token, between its other characters.
_ALPHANUMERIC = re.compile(r"[A-Za-z0-9]+")
_HEX_CHARACTERS: Final = frozenset("0123456789abcdefABCDEF")
# A part of a run between two ``/`` that is left out of the share of words when the run is
# judged whole: digits only, as a number argument is written, or small letters and digits
# that hold a ``_`` or ``-``, as a group name is written (``tree_parse``). Base64 holds
# neither ``_`` nor ``-``.
_PLAIN_PART = re.compile(r"[0-9]+|[a-z0-9]*[_-][a-z0-9_-]*")
# What may stand in front of hexadecimal digits to say they are hexadecimal, as in ``0x3f9a``.
_HEX_PREFIXES: Final = ("0x", "0X")
# A word, to the random-looking rule: a capital and three or more small letters,
# or a capital and two small letters that hold a vowel.
_RANDOM_WORD = re.compile(
    rf"[A-Z](?:[a-z]{{{RANDOM_WORD_SMALL_LETTERS},}}"
    rf"|[{RANDOM_WORD_VOWELS}][a-z]|[a-z][{RANDOM_WORD_VOWELS}])(?![a-z])"
)
# A UUID, which is an id and is shown, also after a word as in ``GPU-<uuid>``.
_UUID = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
# A run that starts with an option of one letter and a value glued to it, as ``-kVALUE``.
_SHORT_OPTION = re.compile(r"-[A-Za-z](?=[^-])")
# A digest name and its separator at the end of the text before a value.
_DIGEST_BEFORE = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(DIGEST_NAMES) + r")[:=/-]\Z", re.IGNORECASE
)
# How much of the text before a value ``_DIGEST_BEFORE`` reads: the longest digest name, its
# separator and the character before the name.
_DIGEST_REACH: Final = max(len(name) for name in DIGEST_NAMES) + 2


def _before(text: str, at: int) -> str:
    """Return the end of ``text[:at]`` that ``looks_random`` reads, which it reads as all of it."""
    return text[max(0, at - _DIGEST_REACH) : at]


def _character_kind(char: str) -> str:
    """Return ``"A"`` for a capital, ``"a"`` for a small letter, ``"0"`` for a digit, or ``""``."""
    if "A" <= char <= "Z":
        return "A"
    if "a" <= char <= "z":
        return "a"
    return "0" if "0" <= char <= "9" else ""


def looks_random(value: str, before: str = "") -> bool:
    """Say whether a value is hidden by its shape alone, wherever it stands in a command.

    ``before`` is the text in front of the value. Trailing ``=`` padding is
    left out, and so is the ``0x`` or ``0X`` in front of hexadecimal digits.
    An AWS access key id, a prefix of ``ACCESS_KEY_ID_PREFIXES`` and capitals
    or digits to ``ACCESS_KEY_ID_LENGTH`` characters in all, is hidden. Any
    other value shorter than ``RANDOM_MIN_LENGTH`` is shown, and so is
    one made only of digits. Hexadecimal (digits and the letters ``a`` to
    ``f`` in either case) is hidden, unless it is ``COMMIT_ID_LENGTH`` long or
    ``before`` ends with a name of ``DIGEST_NAMES`` and a ``:``, ``=``, ``/``
    or ``-`` (``sha256:...``). Any other value is hidden when it holds both
    capitals and small letters, changes kind of character between
    neighbours at least once in every ``RANDOM_CHANGE_EVERY`` characters,
    has a capital followed by another capital or a digit at least
    ``RANDOM_MIN_CAPITAL_PAIRS`` times, and has less than
    ``RANDOM_WORDS_SHOWN_PERCENT`` percent of its characters in words: a
    capital followed by ``RANDOM_WORD_SMALL_LETTERS`` or more small letters,
    or by two small letters one of which is in ``RANDOM_WORD_VOWELS``.
    """
    return _looks_random(value, before)


def _looks_random(value: str, before: str, left_out: int = 0, *, commit_id: bool = True) -> bool:
    """Say what ``looks_random`` says, with ``left_out`` characters left out of the share of words.

    The share of characters in words is taken over the length of the value
    less ``left_out``; every other test reads the whole value. Without
    ``commit_id``, hexadecimal of ``COMMIT_ID_LENGTH`` is judged as
    hexadecimal of any other length is.
    """
    value = value.rstrip("=")
    if _ACCESS_KEY_ID.fullmatch(value):
        return True
    if value.startswith(_HEX_PREFIXES) and set(value[2:]) <= _HEX_CHARACTERS:
        value = value[2:]
    if len(value) < RANDOM_MIN_LENGTH or value.isdigit():
        return False
    if set(value) <= _HEX_CHARACTERS:
        commit = commit_id and len(value) == COMMIT_ID_LENGTH
        return not commit and _DIGEST_BEFORE.search(before) is None
    return _random_shape(value, left_out)


def _random_shape(value: str, left_out: int = 0) -> bool:
    """Say whether a value of any length passes tests 2 to 5 of ``looks_random``.

    It holds both capitals and small letters, changes kind of character at
    least once in every ``RANDOM_CHANGE_EVERY`` characters, has
    ``RANDOM_MIN_CAPITAL_PAIRS`` capitals followed by a capital or a digit,
    and less than ``RANDOM_WORDS_SHOWN_PERCENT`` percent of its characters,
    over its length less ``left_out``, in words.
    """
    kinds = [_character_kind(char) for char in value]
    if "A" not in kinds or "a" not in kinds:
        return False
    neighbours = list(itertools.pairwise(kinds))
    changes = sum(1 for one, two in neighbours if one and two and one != two)
    capital_pairs = sum(1 for one, two in neighbours if one == "A" and two in ("A", "0"))
    in_words = sum(len(word.group(0)) for word in _RANDOM_WORD.finditer(value))
    return (
        changes * RANDOM_CHANGE_EVERY >= len(value)
        and capital_pairs >= RANDOM_MIN_CAPITAL_PAIRS
        and in_words * 100 < RANDOM_WORDS_SHOWN_PERCENT * (len(value) - left_out)
    )


# A piece of a part of a run, between its ``-`` and ``_``, written in CamelCase: words of a
# capital and small letters, maybe ending in capitals and digits, as ``MadeUpV2`` or
# ``SweepFP16`` is written.
_CAMEL_CASE = re.compile(r"(?:[A-Z][a-z]+)+(?:[A-Z]{1,4}[0-9]{0,3}|[0-9]{1,3})?")
# What splits a part of a run into the pieces of a name, as ``Model-3B_Chat`` is written.
_NAME_JOINERS = re.compile(r"[_-]+")
# What splits a part of a run into the pieces of a word of a path, as ``run_01`` and
# ``c+x`` are written.
_PATH_JOINERS = re.compile(r"[_+-]+")
# A piece of a name that reads as a word of a path: small letters and digits after them, or
# digits and small letters after them, as ``run01``, ``x86`` and ``7b`` are written.
_WORD_PIECE = re.compile(r"[a-z]+[0-9]*|[0-9]+[a-z]*")
# A short tag of capitals and digits, as a format or a size is written: ``INT4``, ``W4A16``,
# ``EXL2``, ``70B``.
_NAME_TAG = re.compile(r"[A-Z0-9]{1,8}")
# The runs of one kind of character in a piece of a part: capitals, small letters or digits.
_KIND_RUN = re.compile(r"[A-Z]+|[a-z]+|[0-9]+")
# Small letters that stand alone between digits and capitals in a tag of an experiment, as in
# ``8x7B``, ``v0p6`` and ``Q100x8``.
_TAG_LETTERS: Final = frozenset({"x", "v", "p"})
# The vowels a word in a tag holds. ``y`` is left out: a run such as ``yy`` after a capital is
# as common in a key as in a word.
_TAG_VOWELS: Final = frozenset("aeiou")
# A part of a run that reads as a word of a path on its own: digits, one or two small letters
# (``up``, ``w``), a small letter and digits (``v1``, ``x86``), three or more small letters
# with a vowel and maybe digits (``data``, ``python3``), or digits and one small letter
# (``7b``).
_PATH_WORD = re.compile(
    rf"[0-9]+|[a-z]{{1,2}}|[a-z][0-9]+|(?=[a-z]*[{RANDOM_WORD_VOWELS}])[a-z]{{3,}}[0-9]*"
    r"|[0-9]+[a-z]"
)
# The folders a commit id follows in a path, as a code host or a model hub writes it:
# ``org/repo/commit/<id>``, ``org/repo/blob/<id>/src``, ``org/Model-3B/resolve/<id>/config``,
# ``models--org--Model-3B/snapshots/<id>/config``. Elsewhere between two ``/`` hexadecimal of
# ``COMMIT_ID_LENGTH`` is judged as hexadecimal of any other length is.
COMMIT_ID_FOLDERS: Final[tuple[str, ...]] = (
    "archive",
    "blob",
    "commit",
    "commits",
    "resolve",
    "snapshots",
    "tree",
)
# A commit id right after a folder of ``COMMIT_ID_FOLDERS`` in a run, between two ``/`` or at
# the end of the run, as in ``org/repo/resolve/<id>/``: an id, shown, that the parts on either
# side of are read apart from, as a UUID is. The id is the group of the match.
_PATH_COMMIT_ID = re.compile(
    r"(?<![^/])(?:"
    + "|".join(COMMIT_ID_FOLDERS)
    + rf")/([0-9A-Fa-f]{{{COMMIT_ID_LENGTH}}})(?![^/])"
)


def _path_word(part: str) -> bool:
    """Say whether a part of a run between two ``/`` reads as a word of a path.

    It does when it is empty, is one ``_PATH_WORD``, or holds a ``-``, a
    ``_`` or a ``+`` and each piece between them is a ``_WORD_PIECE``, as
    ``run_01``, ``step-000100``, ``x86_64`` and ``c+x`` are written.
    """
    part = part.rstrip("=")
    if not _PATH_JOINERS.search(part):
        return not part or _PATH_WORD.fullmatch(part) is not None
    return all(_WORD_PIECE.fullmatch(piece) for piece in _PATH_JOINERS.split(part) if piece)


def _tag_word(piece: str) -> bool:
    """Say whether a piece of a part is written as the tags of an experiment are.

    It is made of letters and digits, is shorter than ``RANDOM_MIN_LENGTH``,
    and each run of small letters in it is one of ``_TAG_LETTERS`` alone, or
    holds one of ``_TAG_VOWELS`` and follows a capital, as the end of a word
    in CamelCase does: ``TP8PP2DP4``, ``BS256xSeq4096``, ``Q100x8``,
    ``NeoX20B``. A word of three small letters or more with a vowel may open
    the piece when every later run of small letters is one of
    ``_TAG_LETTERS``: ``madeLLMv0p6``, ``sampleV3x8``.
    """
    if not piece.isascii() or not piece.isalnum() or len(piece) >= RANDOM_MIN_LENGTH:
        return False
    previous = ""
    opened = False
    for found in _KIND_RUN.finditer(piece):
        run = found.group(0)
        if run.islower() and run not in _TAG_LETTERS:
            opens = not previous and len(run) >= 3
            if opened or not (previous.isupper() or opens) or _TAG_VOWELS.isdisjoint(run):
                return False
            opened = opens
        previous = run
    return True


def _name_part(part: str) -> bool:
    """Say whether a part of a run between two ``/`` is written in the order of the words of a name.

    It is when it holds a ``-`` or a ``_``, which base64 holds neither of
    (``Model-3B``, ``Q4_K_M``), or when it is empty, hexadecimal, written in
    CamelCase (``_CAMEL_CASE``), a ``_WORD_PIECE``, a ``_NAME_TAG`` or tags
    of an experiment (``_tag_word``): ``MadeUpV2``, ``data``, ``run01``,
    ``W4A16``, ``TP8PP2DP4``.
    """
    part = part.rstrip("=")
    if _NAME_JOINERS.search(part) or set(part) <= _HEX_CHARACTERS:
        return True
    return _tag_word(part) or any(
        pattern.fullmatch(part) is not None for pattern in (_CAMEL_CASE, _WORD_PIECE, _NAME_TAG)
    )


def _ordinary_part(part: str, before: str) -> bool:
    """Say whether a part of a run between two ``/`` reads as a name, not as a piece of a key.

    It does when it does not look random (``looks_random``) and it is
    hexadecimal, as a short id is, or each piece of it between its ``-`` and
    ``_`` is written in CamelCase (``_CAMEL_CASE``) or as tags of an
    experiment (``_tag_word``), or fails one of tests 2 to 5 of
    ``looks_random`` (``_random_shape``), whatever its length. So
    ``Model-3.1-8B-Instruct``, ``run_01``, ``MadeUpV2`` and ``Q100x8`` read as
    names.
    """
    part = part.rstrip("=")
    if looks_random(part, before):
        return False
    if set(part) <= _HEX_CHARACTERS:
        return True
    return all(
        _CAMEL_CASE.fullmatch(piece) or _tag_word(piece) or not _random_shape(piece)
        for piece in _NAME_JOINERS.split(part)
        if piece
    )


def _segment_spans(run: str, start: int, at: int, text: str) -> list[tuple[int, int]]:
    """Return the parts of a run that look random on their own, as spans within the run.

    Each part between two ``/`` that looks random is a span, and in any other
    part each run of letters and digits that looks random is, as a part of
    hidden hexadecimal is. In a run that holds a ``/``, a part of
    ``COMMIT_ID_LENGTH`` hexadecimal digits is judged as hexadecimal of any
    other length is: the commit ids a run holds right after a folder of
    ``COMMIT_ID_FOLDERS`` are read apart before this (``_random_spans``).
    """
    spans: list[tuple[int, int]] = []
    path = "/" in run[start:]
    for segment in re.finditer(r"[^/]+", run[start:]):
        begin, end = start + segment.start(), start + segment.end()
        if _looks_random(segment.group(0), _before(text, at + begin), commit_id=not path):
            spans.append((begin, end))
            continue
        for part in _ALPHANUMERIC.finditer(segment.group(0)):
            part_at = begin + part.start()
            if looks_random(part.group(0), _before(text, at + part_at)):
                spans.append((part_at, part_at + len(part.group(0))))
    return spans


def _random_core(run: str, start: int, parts: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Return where the core of a run lies, between its words of a path, or ``None``.

    The core runs from the first part to the last part that is no word of
    a path (``_path_word``), with the ``/`` around it taken in, but for one
    ``/`` between it and a word it keeps: ``data/<core>/out``. A core that
    starts at the first part takes in the ``/`` before it too. ``None`` when
    every part is a word of a path.
    """
    other = [k for k, (begin, end) in enumerate(parts) if not _path_word(run[begin:end])]
    if not other:
        return None
    begin, end = parts[other[0]][0], parts[other[-1]][1]
    while begin > start and run[begin - 1] == "/":
        begin -= 1
    if begin > start:
        begin += 1
    while end < len(run) and run[end] == "/":
        end += 1
    if end < len(run):
        end -= 1
    return begin, end


# A word of a path long enough to stand as a word on its own: three small letters or more, or a
# ``-`` or ``_`` between its pieces, as ``data``, ``files``, ``python3`` and ``x86_64`` are
# written.
_WHOLE_WORD = re.compile(r"[a-z]{3,}|[_-]")
# How many short words of a path on each side of a core too short to judge its length is read
# with: a random value holds one or two at an end by chance, while a path may hold many.
_SHORT_WORDS_BESIDE: Final = 2


def _short_word(part: str) -> bool:
    """Say whether a part of a run between two ``/`` is a short word of a path.

    It is when it is a word of a path (``_path_word``) and no ``_WHOLE_WORD``
    is in it: empty, digits, one or two small letters, a small letter and
    digits, digits and a small letter, or such pieces joined by ``+``, as
    ``8``, ``au``, ``j0``, ``7b`` and ``p+em2`` are written. A random value
    holds such parts by chance as often as a path does.
    """
    return _path_word(part) and _WHOLE_WORD.search(part) is None


def _short_words_around(run: str, parts: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Return where the core of a run lies with the short words of a path on either side of it.

    The core runs from the first part to the last part that is no word of a
    path (``_path_word``); it is widened over up to ``_SHORT_WORDS_BESIDE``
    parts on each side of it that are short words (``_short_word``), up to
    a longer word or an end of the run, as ``data/<core>/out`` is not and
    ``data/au/<core>/p+em2/out`` is, to ``au/<core>/p+em2``. ``None`` when
    every part is a word of a path or no short word is next to the core.
    """
    other = [k for k, (begin, end) in enumerate(parts) if not _path_word(run[begin:end])]
    if not other:
        return None
    first, last = other[0], other[-1]
    while (
        first > 0
        and other[0] - first < _SHORT_WORDS_BESIDE
        and _short_word(run[parts[first - 1][0] : parts[first - 1][1]])
    ):
        first -= 1
    while (
        last < len(parts) - 1
        and last - other[-1] < _SHORT_WORDS_BESIDE
        and _short_word(run[parts[last + 1][0] : parts[last + 1][1]])
    ):
        last += 1
    if (first, last) == (other[0], other[-1]):
        return None
    return parts[first][0], parts[last][1]


# How many longer words of a path at each end of a core are read as words of the path around a
# key, not as pieces of it: a path holds one or two between a folder that is no word of a path
# and a key, as ``data`` in ``srv/data/<key>/out.json``.
_WORDS_AROUND: Final = 2
# A part of a run made of three small letters or more only, as the folders ``srv``, ``nfs`` and
# ``data`` are written: no piece of a key that looks random.
_SMALL_LETTERS = re.compile(r"[a-z]{3,}")


def _cores_within(run: str, parts: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Return the lists of parts of a run to read its core in, the whole list first.

    The core runs from the first part to the last part that is no word of a
    path (``_path_word``). A longer word of a path inside it, a word of a
    path that is no short word (``_short_word``), is either a folder of the
    path around a key, as ``data`` in ``srv/data/<key>/out.json`` is, or a
    piece of the key that reads as a word by chance. So the parts are also
    read from after each of the first ``_WORDS_AROUND`` longer words in the
    core and up to each of its last ``_WORDS_AROUND``, fewest words cut
    first. After those lists come the same lists with the parts of three
    small letters or more at their ends left out (``_SMALL_LETTERS``), as
    the folders ``srv/nfs`` before a key are, and the empty part before the
    ``/`` an absolute path starts with. Last come the same lists read at each
    end past such parts and the words of a path before or between them, as
    ``v1`` in ``v1/srv/nfs/<key>`` is, and left out up to the last such part
    on the way. A word of a path between that part and the key stays, so a
    key that holds a short word at an end is still read with it. The lists
    are read in this order, and the first that hides a core is used. Each
    list holds a part that is no word of a path.
    """
    other = [k for k, (begin, end) in enumerate(parts) if not _path_word(run[begin:end])]
    if not other:
        return []
    words = [
        k
        for k in range(other[0] + 1, other[-1])
        if _path_word(run[parts[k][0] : parts[k][1]])
        and not _short_word(run[parts[k][0] : parts[k][1]])
    ]
    cores: list[list[tuple[int, int]]] = []
    for cut in range(min(len(words), 2 * _WORDS_AROUND) + 1):
        for left in range(min(cut, _WORDS_AROUND), -1, -1):
            right = cut - left
            if right > _WORDS_AROUND:
                break
            low = words[left - 1] + 1 if left else 0
            high = words[len(words) - right] if right else len(parts)
            if any(low <= k < high for k in other):
                cores.append(parts[low:high])

    def folder(part: tuple[int, int]) -> bool:
        """Say whether a part is made of three small letters or more only."""
        return bool(_SMALL_LETTERS.fullmatch(run[part[0] : part[1]]))

    def word(part: tuple[int, int]) -> bool:
        """Say whether a part reads as a word of a path."""
        return _path_word(run[part[0] : part[1]])

    def first_empty(part: tuple[int, int]) -> bool:
        """Say whether a part is the empty part before the `/` an absolute path starts with."""
        return part == parts[0] == (part[0], part[0])

    def add(within: list[tuple[int, int]]) -> None:
        """Append a list of parts that holds a part that is no word of a path, once."""
        if within not in cores and any(not word(part) for part in within):
            cores.append(within)

    read_first = list(cores)
    for within in read_first:
        # Each end is left out while it is a folder of small letters or the empty first part.
        low, high = 0, len(within)
        while low < high and (folder(within[low]) or first_empty(within[low])):
            low += 1
        while high > low and (folder(within[high - 1]) or first_empty(within[high - 1])):
            high -= 1
        add(within[low:high])
    for within in read_first:
        # Each end is read past folders of small letters and words of a path up to the first
        # part that is neither, and left out up to the last such folder on the way.
        low, high = 0, len(within)
        k = 0
        while k < len(within) and (folder(within[k]) or word(within[k])):
            if folder(within[k]):
                low = k + 1
            k += 1
        k = len(within) - 1
        while k >= low and (folder(within[k]) or word(within[k])):
            if folder(within[k]):
                high = k
            k -= 1
        add(within[low:high])
    return cores


def _random_parts(run: str, at: int, text: str) -> list[tuple[int, int]]:
    """Return where the random-looking parts of a token run lie, as spans within the run.

    The run, found at ``at`` in ``text``, is written as base64 when it does
    not start with ``/`` and holds a ``+`` or ends in ``=`` padding, or is
    followed by one. A run with no ``/`` is judged as ``_segment_spans``
    says, and a run written as base64 is hidden whole when any part of it
    is, so no part of a base64 value shows beside a hidden one. A run with a
    ``/`` is read in this order:

    * written as base64, it is judged whole first: if it looks random, it is
      hidden whole, so no part of it between two ``/`` shows;
    * when every part between two ``/`` reads as a name (``_ordinary_part``),
      as a path or a model id is written, only the parts that look random on
      their own are hidden (``_segment_spans``). When the run, or its core
      between the words of a path at its ends (``_random_core``), looks
      random as a whole, each part of the core must also be written in the
      order of the words of a name (``_name_part``);
    * otherwise its core, between the words of a path at either end of it
      (``_random_core``), is judged whole: if the core holds a ``/`` and
      looks random, the core is hidden, ``/`` and all, and the words around
      it are kept (``data/<hidden>/out``, ``/v1/files/<hidden>/raw``). So a
      key written with ``/`` and neither ``+`` nor padding is hidden whole.
      A core that does not look random is also read in the parts
      ``_cores_within`` gives, so a folder that is no word of a path, next to
      a key or further up, does not join the key's core
      (``srv/data/<hidden>/out``, ``srv/nfs/<hidden>/out``).
      A core shorter than ``RANDOM_MIN_LENGTH`` is read with the short words
      of a path beside it (``_short_words_around``), which a key holds at its
      ends by chance: when they make ``RANDOM_MIN_LENGTH`` characters or more
      and the core passes tests 2 to 5 (``_random_shape``), the core and
      those words are hidden (``data/<hidden>/out`` for ``data/au/<key>/out``);
    * otherwise the parts that look random on their own are hidden; one of
      them in a core of several parts hides the core, or the whole run when
      it is written as base64; and when none does, the run is judged whole,
      with its parts made only of digits, as number arguments are written,
      and its group names in small letters with a ``_`` or ``-`` left out of
      the share of words, each with its ``/`` (``bench_group/BM_Name/4096/4``).

    A core that is hidden and starts at the first part of the run hides the
    rest of the run too: a run whose first part reads as no word of a path
    is no path, and no part of it is a word of one. Leading dashes, as of an
    option, are kept, and so is the letter of an option of one letter
    (``-kVALUE``).
    """
    start = len(run) - len(run.lstrip("-"))
    if _SHORT_OPTION.match(run):
        start = 2
    body = run[start:]
    whole = [(start, len(run))]
    # A run written as base64 is: a `+`, or `=` padding at its end or right after it, as
    # before the `/` of an address path; an absolute path is read part by part.
    base64 = not body.startswith("/") and (
        "+" in body or body.endswith("=") or text.startswith("=", at + len(run))
    )
    if "/" not in body:
        spans = _segment_spans(run, start, at, text)
        return whole if spans and base64 else spans
    random_whole = looks_random(body, _before(text, at + start))
    if base64 and random_whole:
        return whole
    # The parts between the `/` of the body, as spans within the run.
    parts: list[tuple[int, int]] = []
    begin = start
    for part in body.split("/"):
        parts.append((begin, begin + len(part)))
        begin += len(part) + 1
    spans = _segment_spans(run, start, at, text)
    core = _random_core(run, start, parts)
    begin, end = core if core is not None else (start, len(run))
    inner = run[begin:end].strip("/")
    # Whether the core, between the words of a path, looks random as a whole.
    core_random = "/" in inner and looks_random(inner, _before(text, at + begin))
    # A core that does not look random is also read with up to two of its longer words at each
    # end cut off, and with its parts of small letters at its ends left out, so a folder around a
    # key does not join it.
    cores = _cores_within(run, parts) if core is not None and not core_random else []
    for within in cores[1:]:
        found = _random_core(run, start, within)
        if found is not None:
            piece = run[found[0] : found[1]].strip("/")
            if "/" in piece and looks_random(piece, _before(text, at + found[0])):
                core, (begin, end), inner, core_random = found, found, piece, True
                break
    # Whether the core starts at the first part of the run, which reads as no word of a path.
    first = begin == start
    names = core_random or random_whole
    if all(
        _ordinary_part(run[one:two], _before(text, at + one))
        and (not names or not begin <= one < end or _name_part(run[one:two]))
        for one, two in parts
    ):
        return whole if spans and base64 else spans
    if core is not None:
        for within in cores if not core_random else ():
            # A core too short to judge: its length is read with the short words beside it.
            found = _random_core(run, start, within)
            if found is None:
                continue
            piece = run[found[0] : found[1]].strip("/")
            wider = _short_words_around(run, within)
            if (
                len(piece) < RANDOM_MIN_LENGTH
                and wider is not None
                and wider[1] - wider[0] >= RANDOM_MIN_LENGTH
            ):
                digits = sum(len(part) + 1 for part in piece.split("/") if part.isdigit())
                if _random_shape(piece, left_out=digits):
                    (begin, end), first, core_random = wider, found[0] == start, True
                    break
        inside = [span for span in spans if begin <= span[0] and span[1] <= end]
        if first and (core_random or inside):
            return whole
        if core_random:
            return [(begin, end)]
        if inside and "/" in inner:
            if base64:
                return whole
            return sorted([core, *(span for span in spans if span not in inside)])
    if spans:
        return whole if base64 else spans
    plain = sum(len(part) + 1 for part in body.split("/") if _PLAIN_PART.fullmatch(part))
    if _looks_random(body, _before(text, at + start), left_out=plain):
        return whole
    return []


def _random_spans(run: str, at: int, text: str) -> list[tuple[int, int]]:
    """Return where the random-looking parts of a token run lie, every id in it left shown.

    The parts of the run between its UUIDs and the commit ids right after a
    folder of ``COMMIT_ID_FOLDERS`` (``_PATH_COMMIT_ID``) are read as
    ``_random_parts`` reads a run, so an id such as ``GPU-<uuid>`` is shown,
    and so is a path pinned to a commit, as
    ``org/Model-3B/resolve/<commit id>/config`` is written.
    """
    spans: list[tuple[int, int]] = []
    begin = 0
    ids = sorted(
        (
            *(found.span() for found in _UUID.finditer(run)),
            *(found.span(1) for found in _PATH_COMMIT_ID.finditer(run)),
        )
    )
    for found in (*ids, None):
        end = len(run) if found is None else found[0]
        if found is not None and end < begin:
            continue
        piece = run[begin:end]
        spans.extend(
            (begin + one, begin + two) for one, two in _random_parts(piece, at + begin, text)
        )
        if found is not None:
            begin = found[1]
    return spans


def _cut_as_path(run: str, at: int, text: str) -> bool:
    """Say whether ``public_text`` may cut a token run as an absolute path.

    It may when the run starts with ``/``, except ``//`` after ``:`` as in an
    address whose host is not empty and whose scheme is not ``file``, when it
    starts with an option and holds a ``/``, and when it holds a ``/`` right
    after a ``+``, where ``public_text`` starts a path.
    """
    if run.startswith("//") and text[at - 1 : at] == ":":
        return run.startswith("///") or text[max(0, at - 5) : at].lower() == "file:"
    return run.startswith("/") or (run.startswith("-") and "/" in run) or "+/" in run


def _hidden_random(text: str, *, paths: bool) -> str:
    """Hide the random-looking values in a text, as ``looks_random`` says.

    With ``paths`` only the runs that ``public_text`` may cut as a path are
    read, and such a run is hidden whole when any part of it looks random,
    so no part of a value is shown as the last part of a path. Without it,
    every run is read and only its random-looking parts are hidden: a path
    segment, a query value of an address, or the value itself. A run that
    holds percent escapes is judged as the text they stand for, and is
    hidden whole when any part of that text looks random.
    """

    def shown(found: re.Match[str]) -> str:
        run = found.group(0)
        if len(run) < _SHORTEST_RANDOM:
            return run
        # What stays of a run hidden whole: its leading dashes, or an option of one letter.
        kept = 2 if _SHORT_OPTION.match(run) else len(run) - len(run.lstrip("-"))
        if _PERCENT_ESCAPE.search(run):
            meant = _PERCENT_ESCAPE.sub(lambda escape: chr(int(escape.group(1), 16)), run)
            before = _before(text, found.start())
            if _random_spans(meant, len(before), before + meant):
                return run[:kept] + HIDDEN
            return run
        if paths:
            if not _cut_as_path(run, found.start(), text):
                return run
            spans = _random_spans(run, found.start(), text)
            if not spans:
                return run
            return run[:kept] + HIDDEN
        out: list[str] = []
        end = 0
        for begin, finish in _random_spans(run, found.start(), text):
            out.append(run[end:begin] + HIDDEN)
            end = finish
        out.append(run[end:])
        return "".join(out)

    if _LONG_RUN.search(text) is None:
        return text
    return _TOKEN_RUN.sub(shown, text)


def _hidden_to_the_end(arg: str, program: str = "") -> str | None:
    """Hide the rest of an argument whose first word gives a credential-like name a value.

    Such an argument is one value, spaces included: ``DB_PASSWORD=a b c``,
    ``--api-key=a b``, ``--env=MY_TOKEN=a b`` and ``-eMY_TOKEN=a b`` keep
    the name and lose everything after its ``=``, and ``--user=user:a b``
    loses everything after its first ``:``. A password option of the client
    ``program`` with its value glued to it is one value too: ``mysql -pa b``
    shows ``-p<hidden>`` and ``ab -Auser:a b`` shows ``-Auser:<hidden>``.
    The name is the first one of the argument, or one that starts the value
    of ordinary names (``SetEnv=DB_PASSWORD=a b``); an ordinary name whose
    value holds a credential option further on, as
    ``MADE_UP_FLAGS=--api-key=a --threads 8``, is read word by word, and so
    is a form whose hidden value ends before the end of the word, as a query
    parameter does. A command glued to a ``command`` option of the client is
    read whole as that client's own: ``--command=AUTH a`` shows
    ``--command=AUTH <hidden>``. Returns ``None`` when the first word gives
    no such name a value.
    """
    if not _SPACE.search(arg):
        return None
    command = _hidden_command_glued(arg, program)
    if command is not None:
        return command
    first = _SPACE.split(arg, maxsplit=1)[0]
    at = _ordinary_value_start(first)
    if at is None:
        named = _hidden_credential(first)
    else:
        credential = _VARIABLE_ASSIGNED.match(first, at)
        named = None if credential is None else first[: credential.end()] + HIDDEN
    for hidden in (named, _hidden_glued_password(first), _hidden_client_glued(first, program)):
        if hidden is not None and hidden.rstrip(_QUOTES).endswith(HIDDEN):
            return hidden
    return None


def _public_argument(
    arg: str,
    program: str = "",
    *,
    code: bool = False,
    shell: bool = False,
    shell_words: bool = False,
    axis: bool = False,
    command: bool = False,
) -> str:
    """Return one argument of a command as a results document may show it.

    The argument may hold several words, as the text after ``sh -c`` does.
    One that ``shell`` says is a shell text (the text after ``-c`` of a
    shell, ``_ShellText``) is read as a shell reads it, where a value ends at
    an operator that ends a command. Any other argument is read as the
    program gets it, and an operator in it is part of the value it stands
    in: ``-H 'Cookie: a=1; b=2'`` hides all of ``a=1; b=2``.
    Its credentials are hidden as ``_hidden_code`` and ``_hidden_words`` say,
    ``program`` being the client whose options apply where it stands, and its
    absolute paths are cut as ``public_text`` cuts them: also after ``=``,
    after a colon and glued to an option (``-I/a/include`` shows
    ``-Iinclude``). An argument that is one absolute path is cut to its last
    part. The host of a ``file://`` address that has no path is hidden
    first, as ``_hidden_file_host`` says, while the address still reads as
    typed. A random-looking value (``looks_random``) is hidden wherever it
    stands; a path that holds one is hidden whole before it is cut, also the
    path of an address whose host is empty and the host and path of a
    ``file://`` address. Unless the argument is the text of a command or a
    program (``code``) or a command of the client's own (``command``), one
    whose first word gives a credential-like name a value is that value to
    its end, as ``_hidden_to_the_end`` says. A command of the client's own,
    as the value of its ``command`` option, is read as ``_hidden_words``
    reads one. ``shell_words`` says that the words of the text end as a
    shell's do (``_CommandWalk.shell_word``), as ``_hidden_code`` reads them.
    After an axis option (``axis``), or glued to one, the axis ``Key`` keeps
    its values: ``-a Key=I32``, ``--axis=Key=I32`` (``_axis_value``); a
    credential after them stays hidden (``_hidden_axis_value``).
    """
    typed = _hidden_file_host(arg)
    if _axis_value(typed, axis, program):
        return _hidden_random(public_text(_hidden_axis_value(typed)), paths=False)
    whole = None if code or command else _hidden_to_the_end(typed, program)
    if whole is not None:
        return _hidden_random(public_text(whole), paths=False)
    code_shown = _hidden_code(typed, shell=shell, shell_words=shell_words, code=code)
    shown = _hidden_words(
        code_shown,
        program,
        shell=shell,
        command=command,
        value=not code,
        code=code and not (shell or shell_words),
    )
    # The user part and the host of a file address go first, as in ``public_text``, so a
    # random-looking value in the path after them is read as part of a path to cut.
    shown = _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", shown)
    shown = _FILE_AUTHORITY.sub(lambda found: f"{found.group(1)}/", shown)
    shown = _hidden_random(shown, paths=True)
    if shown.startswith(("/", "~")) and not _SPACE.search(shown):
        return _hidden_random(_last_part(shown), paths=False)
    whole = None if code or shell or shell_words or command else _path_to_its_end(shown)
    if whole is not None:
        return _hidden_random(whole, paths=False)
    return _hidden_random(_public_text(shown, shell=shell or shell_words), paths=False)


# The host of an address: after ``scheme://`` and the user part, if any, up to
# the port, the path or the end of the address. A host in brackets is an IPv6
# address, maybe with a zone (``[fe80::1%25eth0]``). ``file:///...`` has no
# host. An address glued to an option (``-xhttp://...``) is read with the
# option's letters in its scheme, which hides its host all the same.
_ADDRESS_HOST = re.compile(
    r"""([A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/]*@)?)"""
    r"""(\[[^\s/\]]*\]|[^\s/:?#'"\[\]@<>]+)"""
)
# Hosts that name the machine to itself: an address that goes to one is shown whole.
LOOPBACK_HOSTS: Final[tuple[str, ...]] = ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0")


# A ``file://`` address with a host and no path, as typed: the host (a name of letters of any
# script, digits, ``.``, ``-``, ``_``, ``~`` and ``%`` that holds a letter or a digit, or one in
# brackets) and maybe a port, then the end of the text or any character that no host name holds
# and that starts no port, path or user part: white space, a quote, ``?``, ``#``, a shell
# operator, a bracket or brace (``[file://made-up-host]``, ``${STORE:-file://made-up-host}``),
# a comma (``file://made-up-host,file://other-host``), ``=``, ``+``, ``$``, ``\`` and any other
# mark of any script. A ``/`` starts the path, which the rules for paths cut with the host; a
# ``:`` with no port number after it (``file://h:x/y``) means no host stands there, and the
# address is left to the rules for paths; an ``@`` ends a user part.
_FILE_HOST_ALONE = re.compile(
    r"""((?i:file)://)(\[[0-9A-Za-z:.%_~-]*\]|(?=[\w.%~-]*?[^\W_])[\w.%~-]+)((?::[0-9]*)?)"""
    r"""(?![\w.%~/:@-])"""
)


def _hidden_file_host(text: str) -> str:
    """Hide the host of every ``file://`` address in a text that has no path.

    ``file://made-up-host`` shows ``file://<hidden>`` and
    ``file://made-up-host:8000`` shows ``file://<hidden>:8000``; a loopback name
    is kept (``file://localhost``). The
    host ends at any character no host name holds but the ``:`` of a port, the
    ``/`` of a path and the ``@`` of a user part, so
    ``file://made-up-host,file://other-host`` shows
    ``file://<hidden>,file://<hidden>``. A file
    name typed with no path before it is read as the host it stands for:
    ``file://m.gguf`` shows ``file://<hidden>``. This reads the address as
    typed, before ``public_text`` cuts the path of a file address with what
    stands before it: ``file:///a/m.gguf`` and ``file://made-up-host/a/m.gguf``
    show ``file://m.gguf``, a name no cleaner reads again as a host.
    """

    def shown(found: re.Match[str]) -> str:
        if found.group(2).lower() in LOOPBACK_HOSTS:
            return found.group(0)
        return found.group(1) + HIDDEN + found.group(3)

    return _FILE_HOST_ALONE.sub(shown, text)


def _hidden_host(text: str, *, shell: bool = False) -> str:
    """Hide the host of every address in a text, unless it is a loopback name.

    The scheme, the user part, the port and the path are kept as they are:
    ``https://made-up.example:8443/v1`` shows ``https://<hidden>:8443/v1``,
    and ``http://localhost:8000/v1`` is shown whole. A ``file://`` address
    is left as it is: one with a path has lost what stood before the path
    with the path's folders (``public_text``), and one with a host and no
    path has lost its host (``_hidden_file_host``). With ``shell`` the text
    is a shell text, and a host ends at an operator that ends a command
    (``_operator_spans``): ``curl http://made-up.example&& ls`` shows
    ``curl http://<hidden>&& ls``.
    """

    def shown(found: re.Match[str]) -> str:
        if found.group(2).lower() in LOOPBACK_HOSTS or found.group(1).lower().endswith("file://"):
            return found.group(0)
        return found.group(1) + HIDDEN

    # Every address holds ``://``: a text with none has no host to hide.
    if "://" not in text:
        return text
    if not shell or not any(char in text for char in ";&|"):
        return _address_sub(_ADDRESS_HOST, shown, text)
    out: list[str] = []
    end = 0
    for one, two in _operator_spans(text):
        out.append(_address_sub(_ADDRESS_HOST, shown, text[end:one]))
        out.append(text[one:two])
        end = two
    out.append(_address_sub(_ADDRESS_HOST, shown, text[end:]))
    return "".join(out)


def _public_side(text: str, include_image_refs: bool) -> str:
    name, eq, rest = text.partition("=")
    kind, colon, _spec = rest.partition(":")
    if not eq or not colon:
        return HIDDEN
    if include_image_refs and kind in IMAGE_REF_KINDS:
        return text
    return f"{name}={kind}:{HIDDEN}"


def public_words(text: str) -> str:
    """Return a command written as one text, as a results document may show it.

    The text is split as a shell would split it, or into the words
    ``_hidden_words`` reads when its quotes do not pair, and each word is
    shown as ``public_command`` shows an argument of the workload: absolute
    paths cut to their last part, the value of a credential-like variable,
    option or header hidden, also when it is the next word or sits inside
    the word, as in ``sh -c 'tool --token VALUE'``, and the host of an
    address hidden unless it is a loopback name. The words are joined by
    single spaces. An operator outside quotes (``&&``, ``||``, ``;``, ``&``,
    ``|``), a line break or a comment (``_shell_comment``) ends a command:
    the operator is shown with the spaces it had around it, a value before
    it ends there, and the next command is read afresh, so a setting ends
    there too. Where the command before a comment still waits for a value,
    the word glued to the comment's ``#`` is hidden as that value
    (``_CommandWalk.comment``). A header that hides the rest of its argument
    hides the words after it up to the end of its command, and is shown with
    ``<hidden>`` after it, also as a data store client's one-word key
    (``memtier_benchmark --key-prefix auth: VALUE`` shows ``auth: <hidden>``).
    The word after ``-c`` of a shell (``_ShellText``) is a shell text, as
    ``_public_argument`` reads it. In a
    text that holds a line break, ``set`` after a client of
    ``DATA_SET_CLIENTS`` starts a setting as it does anywhere else, while
    ``AUTH`` and the client's other commands are read as on one line. The
    word after each word is read as typed, so a redirection quoted or escaped
    there (``AUTH VALUE '>out.log'``) is an argument of the command, as in
    a shell text, while one written bare is a redirection.
    A command substitution is one word of the command it stands in, and its
    inner text is read as a command written as one text of its own
    (``_hidden_words``).
    """
    masked = _substitutions_masked(text)
    if masked is not None:
        return _substitutions_restored(public_words(masked[0]), masked[1], public_words)
    pieces: list[tuple[str, bool]] = []
    walk = _CommandWalk(data_sets="\n" not in text, ahead=text, split=True)
    shell_text = _ShellText()
    hiding = False
    start = 0
    # Whether the command before ended at a comment, whose first word may hold its value.
    open_before = False
    # The words of a comment read as words of the client of the command before it.
    remark: _RemarkWalk | None = None
    for one, two in (*_command_ends(text), (len(text), len(text))):
        typed = [found.group(0) for found in _SHELL_WORD.finditer(text[start:one])]
        try:
            words = _shell_split(text[start:one])
        except ValueError:
            words = typed
        later = _LaterClients(words)
        # The next word is read as typed, quotes and backslashes kept, where the words stand
        # one for one: a redirection quoted or escaped (``'>out.log'``) is an argument.
        if len(typed) != len(words):
            typed = words
        at_comment = text.startswith(_SHELL_COMMENT, one)
        for k, word in enumerate(words):
            first = open_before
            if open_before:
                open_before = False
                held = walk.comment(word)
                if walk.program:
                    remark = _RemarkWalk(walk.program)
                walk.reset()
                shell_text = _ShellText()
                hiding = False
                if held is not None:
                    pieces.append((held, False))
                    continue
            if hiding:
                continue
            last = k + 1 == len(words)
            ahead = _shell_word_ahead(None if last else typed[k + 1])
            said = None if remark is None else remark.hidden(word[1:] if first else word, ahead)
            if said is not None:
                pieces.append((_SHELL_COMMENT + said if first else said, False))
                walk.read(word)
                continue
            shell = shell_text.read(word)
            shown_next = walk.shown_next(word, ahead, comment=last and at_comment)
            if shown_next is not None:
                pieces.append((_hidden_host(shown_next), False))
                continue
            client = _value_client(walk, word, later, k)
            shown = _shown_argument(walk, word, shell=shell, client=client)
            header = None if _SPACE.search(word) else _hidden_header(word)
            hiding = header is not None and header[1]
            # A header that hides the words after it is shown with its value hidden, as in a
            # shell text, also where a data store client's argument alone is a key.
            if header is not None and hiding and HIDDEN not in shown:
                shown = header[0]
            pieces.append((shown, False))
        if two > one:
            glued = one > 0 and not text[one - 1].isspace()
            pieces.append((text[one:two], glued))
            pieces.append(("", two < len(text) and not text[two].isspace()))
        open_before = at_comment
        if not open_before:
            walk.reset()
            shell_text = _ShellText()
            hiding = False
        # A line break ends the comment; an operator in it starts the client's command again.
        if remark is not None and two > one:
            remark = _RemarkWalk(remark.client)
        elif not at_comment:
            remark = None
        start = two
    out: list[str] = []
    glue = False
    for piece, glued in pieces:
        if not piece:
            glue = glued
            continue
        if out and not (glued or glue):
            out.append(" ")
        out.append(piece)
        glue = False
    return "".join(out)


def _command_ends(text: str) -> list[tuple[int, int]]:
    """Return where the commands of a shell text end: the span of each operator or line break.

    A line break ends a command with no span of its own, and so does a
    comment (``_shell_comment``), whose words are read as a command of their
    own, and as the client of the command before it reads them
    (``_RemarkWalk``). Only an operator or a line break outside quotes ends
    a command. An operator in the user part of an address
    (``https://user:a;b@host``) ends none: the user part is hidden whole, as
    ``_public_argument`` hides it in the text after ``-c``.
    """
    # The user parts in the order they stand; ``user`` is the first that ends after an operator.
    users = [found.span() for found in _address_matches(_ADDRESS_USER, text)]
    user = 0
    ends: list[tuple[int, int]] = []
    end = 0
    for found in _SHELL_TOKEN.finditer(text):
        newline = text.find("\n", end, found.start())
        if newline >= 0:
            ends.append((newline, newline))
        if found.lastgroup == "operator":
            while user < len(users) and users[user][1] <= found.start():
                user += 1
            if user == len(users) or not users[user][0] < found.start():
                ends.append(found.span())
        elif _shell_comment(found.group(0)):
            ends.append((found.start(), found.start()))
        end = found.end()
    return ends


# What each argument reads as, kept while the positional parameters of a shell text are read
# (``_with_parameters``): every command of the text that uses them reads the same arguments
# again, each with the same client and the same kind of text. ``None`` keeps nothing.
_READ_ARGUMENTS: ContextVar[dict[tuple[object, ...], str] | None] = ContextVar(
    "_READ_ARGUMENTS", default=None
)


def _read_once(reader: Callable[..., str], arg: str, program: str, **kinds: bool) -> str:
    """Return ``reader(arg, program, **kinds)``, read once while ``_READ_ARGUMENTS`` keeps it.

    The reading of an argument depends on it, on the client, on the kinds
    of text and on what is hidden (``_ALL_HIDDEN``), and on nothing else.
    """
    kept = _READ_ARGUMENTS.get()
    if kept is None:
        return reader(arg, program, **kinds)
    key = (
        reader,
        arg,
        program,
        *sorted(kinds.items()),
        _ALL_HIDDEN.get(),
        _SUBSTITUTION_DEPTH.get(),
    )
    found = kept.get(key)
    if found is None:
        found = kept[key] = reader(arg, program, **kinds)
    return found


def _public_shown(
    arg: str,
    program: str = "",
    *,
    code: bool = False,
    shell: bool = False,
    shell_words: bool = False,
    axis: bool = False,
    command: bool = False,
) -> str:
    """Return one argument as ``_public_argument`` shows it, the hosts of its addresses hidden."""
    shown = _public_argument(
        arg, program, code=code, shell=shell, shell_words=shell_words, axis=axis, command=command
    )
    return _hidden_host(shown, shell=shell)


def _shown_argument(walk: _CommandWalk, word: str, *, shell: bool = False, client: str = "") -> str:
    """Read one argument through a walk and return it as a results document may show it.

    A command text (``_CommandWalk.text``) is read as the text after ``-c`` is,
    and a shell text (``shell``) as ``_public_shown`` says. The words of a
    command text end as a shell's do when ``_CommandWalk.shell_word`` says so.
    A word after an axis option (``_CommandWalk.axis``) is read as one. Any
    other argument is read with the options of the client the walk holds, or
    else of ``client``, the client a later word of the command names, as
    ``_value_client`` gives it. An option with its text glued to it
    (``_CommandWalk.glued_text``) is shown with its text read as the
    option's next word.
    """
    split = walk.glued_text(word)
    if split is not None:
        walk.read(split[0])
        inner = _shown_argument(walk, split[2], shell=shell, client=client)
        return _glued_shown(split[1], inner)
    axis = walk.axis
    own = walk.command_text(word)
    code = walk.code(word)
    program = walk.program or ("" if own or code else client)
    shell = walk.shell_run(word) or shell
    shell_words = walk.shell_word(word)
    walk.read(word)
    return _read_once(
        _public_shown,
        word,
        program,
        code=code,
        shell=shell,
        shell_words=shell_words,
        axis=axis,
        command=own,
    )


def _shown_run(
    walk: _CommandWalk, words: Sequence[str], shells: _ShellText | None = None
) -> list[str]:
    """Return arguments read in order through a walk, each as a results document may show it.

    ``shells`` reads the same words to say which is the text after ``-c`` of a
    shell (``_ShellText``); a fresh one is used when none is given.
    """
    shells = _ShellText() if shells is None else shells
    later = _LaterClients(words)
    out: list[str] = []
    for k, word in enumerate(words):
        shell = shells.read(word)
        shown_next = walk.shown_next(word, _argument_ahead(words[k + 1 : k + 2]))
        if shown_next is not None:
            out.append(_hidden_host(_public_argument(shown_next)))
            continue
        client = _value_client(walk, word, later, k)
        out.append(_shown_argument(walk, word, shell=shell, client=client))
    return out


def _shown_length(text: str) -> int:
    """Return how many characters of a shown or hashed text are not hidden."""
    return len(text) - text.count(HIDDEN) * len(HIDDEN)


def _fewest_shown(readings: Sequence[Sequence[str]]) -> list[str]:
    """Return, argument by argument, the reading that shows the fewest characters of it.

    The readings are of one argument list; the first reading wins a tie.
    """
    return [min(column, key=_shown_length) for column in zip(*readings, strict=True)]


# A positional parameter of a shell text, as a word or within one: ``$@``, ``$*``, ``$1`` to
# ``$9`` and the braced forms (``${@}``, ``${12}``).
_PARAMETER = re.compile(r"\$(?:([@*1-9])|\{([@*]|[1-9][0-9]*)\})")
# How a list of arguments is read through a walk: ``_shown_run`` or ``_hashed_run``.
_RunReader = Callable[[_CommandWalk, Sequence[str], _ShellText | None], list[str]]


def _parameters_start(words: Sequence[str]) -> int | None:
    """Return where the positional parameters of a shell text start in an argument list.

    In ``sh -c TEXT NAME ARG...`` the text gets ``NAME`` as ``$0`` and each
    ``ARG`` as ``$1``, ``$2`` and so on. ``None`` says the list gives a shell
    text no parameter, or uses none in it.
    """
    if not any(_PARAMETER.search(word) for word in words):
        return None
    walk = _CommandWalk(ahead=words)
    for k, word in enumerate(words):
        if (
            walk.shell_text
            and not walk.shell_value
            and not _plain_word(word).startswith(("-", "+"))
        ):
            if _PARAMETER.search(word) is None or k + 2 >= len(words):
                return None
            return k + 2
        walk.read(word)
    return None


# What stands for a parameter's use in a word while the word is split; no argument holds it.
_MARK = "\x00"


def _expanded_parameters(word: str) -> list[re.Match[str]]:
    """Return the uses of a positional parameter in one shell word that a shell expands.

    A use inside single quotes or after a backslash (``'$@'``, ``\\$1``) is
    text and is left out; one inside double quotes is expanded.
    """
    uses: list[re.Match[str]] = []
    quote = ""
    at = 0
    while at < len(word):
        char = word[at]
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\":
            at += 1
        elif char in _QUOTES and (not quote or char == quote):
            quote = "" if quote else char
        elif char == "$" and (found := _PARAMETER.match(word, at)) is not None:
            uses.append(found)
            at = found.end()
            continue
        at += 1
    return uses


def _substitution_words(token: str) -> list[str]:
    """Return the words of one word of a shell text as a shell gives them to the command.

    A command substitution in it (``_substitutions_masked``) stays one word
    whatever it holds, as an unknown value is: ``-P $(echo 1; echo 2)`` is
    an option and its value, not five words. A substitution that holds the
    marked use of a parameter (``_MARK``) stands as that use alone. Raises
    ``ValueError`` where ``_shell_split`` does.
    """
    masked = _substitutions_masked(token)
    if masked is None or not masked[1]:
        return _shell_split(token, as_shell=True)
    outer, pieces = masked

    def whole(found: re.Match[str]) -> str:
        piece = pieces.get(found.group(0))
        if piece is None:
            return found.group(0)
        # A parameter used inside the substitution is read as a word of this command too,
        # as the substitution may give it back: the commands of its own text read it there.
        text = "".join(piece[:3])
        return _MARK if _MARK in text else text

    return [_SUBSTITUTION_MARK.sub(whole, word) for word in _shell_split(outer, as_shell=True)]


def _text_commands(text: str, depth: int = 0) -> list[list[str]]:
    """Return the commands of a shell text, each as its words.

    An operator or a line break ends a command. A command substitution is
    kept whole in the word it stands in, and the commands of its inner text
    follow, ``_SHELL_DEPTH`` substitutions deep at most.
    """
    masked = _substitutions_masked(text)
    outer, pieces = (text, {}) if masked is None else masked

    def whole(found: re.Match[str]) -> str:
        piece = pieces.get(found.group(0))
        return found.group(0) if piece is None else "".join(piece[:3])

    commands: list[list[str]] = [[]]
    end = 0
    for found in _SHELL_TOKEN.finditer(outer):
        if found.lastgroup == "operator" or _breaks_line(outer[end : found.start()]):
            commands.append([])
        end = found.end()
        if found.lastgroup != "operator":
            word = found.group(0)
            commands[-1].append(_SUBSTITUTION_MARK.sub(whole, word) if pieces else word)
    out = [command for command in commands if command]
    if depth < _SHELL_DEPTH:
        for _opening, inner, _closing, escapes in pieces.values():
            out.extend(_text_commands(_backquote_unescaped(inner, escapes), depth + 1))
    return out


# How many characters, beyond those of the argument list itself, the uses of the positional
# parameters of a shell text may read; each word read counts one more.
_PARAMETER_READ_SPARE = 65_536


def _parameter_readings(
    words: Sequence[str], read: _RunReader, spare: list[int] | None = None
) -> dict[int, str]:
    """Return how each positional parameter of a shell text reads where the text uses it.

    ``words`` is an argument list such as ``sh -c 'redis-benchmark "$@"' _ ARG...``
    (``_parameters_start``). Each command of the text that uses a parameter
    is read with every parameter put in its place, ``$@`` and ``$*`` giving
    one word for each, so a client the text names reads its own options
    among them: the password after ``-a`` there is hidden. A parameter glued
    to more of its word (``-p"$1"``) is hidden whole when the word it makes
    hides more than it holds. Each parameter, by its place in ``words``,
    gets the reading of its uses that shows the fewest characters of it,
    the first winning a tie; a text that cannot be split as a shell splits
    it gives none. A shell text a command of the text runs is read the same
    way, its parameters taken from that command.

    A command the text repeats word for word is read once. The uses read,
    with those of the texts they run, no more characters in all than the
    argument list holds and ``_PARAMETER_READ_SPARE`` (``spare`` holds what
    is left, shared with those texts), so the reading takes time in
    proportion to the list; a parameter that a use past that bound would
    take is hidden.
    """
    first = _parameters_start(words)
    if first is None:
        return {}
    out: dict[int, str] = {}

    def take(place: int, shown: str) -> None:
        if place not in out or _shown_length(shown) < _shown_length(out[place]):
            out[place] = shown

    if spare is None:
        spare = [sum(len(word) + 1 for word in words) + _PARAMETER_READ_SPARE]
    hidden_all = False
    seen: set[tuple[str, ...]] = set()
    for command in _text_commands(words[first - 2]):
        if tuple(command) in seen:
            continue
        seen.add(tuple(command))
        expanded: list[str] = []
        # For each word put in: the place of its parameter, and whether more of a word is
        # glued to it.
        origins: list[tuple[int, bool] | None] = []
        file_next = False
        for token in command:
            # A redirection, and the file after one that stands alone, is no word of the
            # command: the shell takes it out before the program runs.
            if file_next:
                file_next = False
                continue
            redirect = _REDIRECTION_WORD.match(token)
            if redirect is not None:
                file_next = redirect.end() == len(token)
                continue
            uses = _expanded_parameters(token)
            if len(uses) == 1:
                # The use is marked so that the word it stands in is known once split.
                token = token[: uses[0].start()] + _MARK + token[uses[0].end() :]
            try:
                split = _substitution_words(token)
            except ValueError:
                return out
            for word in split:
                if len(uses) != 1 or _MARK not in word:
                    expanded.append(word)
                    origins.append(None)
                    continue
                name = uses[0].group(1) or uses[0].group(2)
                places = (
                    range(first, len(words))
                    if name in "@*"
                    else range(first + int(name) - 1, min(first + int(name), len(words)))
                )
                before, _mark, after = word.partition(_MARK)
                if spare[0] < 0:
                    # Past the bound a use is not read: each parameter it takes is hidden,
                    # every one of them only once.
                    expanded.append(HIDDEN)
                    origins.append(None)
                    if name not in "@*" or not hidden_all:
                        for place in places:
                            take(place, HIDDEN)
                        hidden_all = hidden_all or name in "@*"
                    continue
                for at, place in enumerate(places):
                    lead = before if at == 0 else ""
                    tail = after if at == len(places) - 1 else ""
                    expanded.append(lead + words[place] + tail)
                    origins.append((place, bool(lead or tail)))
                    spare[0] -= len(words[place]) + 1
        if not any(origins):
            continue
        if spare[0] < 0:
            for origin in origins:
                if origin is not None:
                    take(origin[0], HIDDEN)
            continue
        reading = read(_CommandWalk(ahead=expanded, split=True), expanded, _ShellText())
        reading = _with_parameters(expanded, reading, read, spare)
        for typed, shown, origin in zip(expanded, reading, origins, strict=True):
            if origin is None:
                continue
            place, glued = origin
            if not glued:
                take(place, shown)
            elif shown.count(HIDDEN) > typed.count(HIDDEN):
                take(place, HIDDEN)
    return out


def _after_head(head: Sequence[str], workload: Sequence[str], read: _RunReader) -> list[str]:
    """Return a reading of the shared workload after what one side runs before it.

    The words are read in order through one walk, the side's first, and a
    workload word that a shell text of the side takes as a positional
    parameter is read where the text uses it (``_with_parameters``), as
    ``sh -c 'redis-benchmark "$@"' _ {workload}`` hands the workload to
    ``redis-benchmark``. The workload starts a command of its own
    (``_CommandWalk.new_command``), as it does after ``--`` in
    ``public_command``, unless the head leaves its last word waiting for
    the workload: the value of an option, a command text, the operands of a
    runner of ``COMMAND_TEXT_RUNNERS`` or of a program of ``TEXT_OPTIONS``
    (``ssh HOST {workload}``), the options of a shell (``bash {workload}``)
    or a command a starter such as ``env`` runs. So a runner the workload
    names (``ssh``, ``hyperfine``) reads its texts after any other head as
    it does alone (``timeout 60 {workload}``, ``./runner {workload}``),
    while the client the head names keeps its options for the workload
    (``redis-benchmark {workload}``).
    """
    words = [*head, *workload]
    walk, shells = _CommandWalk(ahead=words), _ShellText()
    reading = read(walk, head, shells)
    if not (walk.waiting() or walk.start or walk.leader or walk.shell):
        walk.new_command()
    reading.extend(read(walk, workload, shells))
    return _with_parameters(words, reading, read)[len(head) :]


def _spec_heads(sides: Sequence[Side]) -> list[list[str]]:
    """Return what each side's spec runs before the shared workload, one head per side.

    That is the words of a ``cmd`` side before its first ``{workload}`` and
    the ``entrypoint`` of an image side that has no ``args`` of its own, as
    ``_workload_heads`` reads them from a config. What an image side
    records of its image (``_image_heads``) is read by ``hashed_workload``
    from the sides it is given as resolved.
    """
    heads: list[list[str]] = []
    for side in sides:
        if side.kind == KIND_CMD:
            argv = side.spec.get("argv")
            if isinstance(argv, (list, tuple)) and WORKLOAD_PLACEHOLDER in argv:
                head = list(argv[: list(argv).index(WORKLOAD_PLACEHOLDER)])
                if all(isinstance(word, str) for word in head):
                    heads.append(head)
        elif side.kind == KIND_IMAGE:
            entrypoint = side.spec.get("entrypoint")
            if isinstance(entrypoint, str) and entrypoint and not side.spec.get("args"):
                heads.append([entrypoint])
    unique: dict[tuple[str, ...], list[str]] = {}
    for head in heads:
        unique.setdefault(tuple(head), head)
    return list(unique.values())


def hashed_workload(
    workload: Sequence[str], sides: Sequence[Side], recorded: Sequence[Side] = ()
) -> list[str]:
    """Return the shared workload as the published hash of every side's command reads it.

    The workload is read alone, as ``hashed_argv`` reads it, after what the
    spec of each of ``sides`` runs before it (``_spec_heads``), and after
    what the image of each image side of ``recorded``, the sides as
    resolved or looked up, runs before it (``_image_heads``); each argument
    is taken from the reading that hides the most of it. So a word the
    client of one side hides, as the ``-a VALUE`` of ``redis-benchmark
    {workload}`` or of an image whose entrypoint is that client, is hidden
    in the hash of every side's command (``hashed_command``), also of a side
    whose program is no client, as the shown command hides it.
    """
    readings = [hashed_argv(workload)]
    for head in [*_spec_heads(sides), *_image_heads(recorded, workload)]:
        readings.append(_after_head(head, workload, _hashed_run))
    return _fewest_shown(readings)


def hashed_command(
    declared: Sequence[str],
    workload: Sequence[str] | None,
    shared: Sequence[str] | None = None,
) -> list[str]:
    """Return the command of a ``cmd`` side, its ``{workload}`` put in, as its hash reads it.

    ``declared`` is the command the side declares, and each ``{workload}``
    in it stands for the words of ``workload``. The command is read as
    ``hashed_argv`` reads it, but the words of the workload at its first
    ``{workload}``, which are read as ``_after_head`` reads them after the
    words before them: so a runner the workload names reads its texts
    whatever program the side runs before it. ``shared`` is the workload
    as every side of the run hashes it (``hashed_workload``): a word it
    hides is hidden at each ``{workload}`` too, so no side's hash holds a
    value that another side's client hides.
    A command with no ``{workload}``, or no workload, is read as
    ``hashed_argv`` reads it.
    """
    places = [k for k, word in enumerate(declared) if word == WORKLOAD_PLACEHOLDER]
    if not places or not workload:
        return hashed_argv(declared)
    words = list(workload)
    command: list[str] = []
    starts: list[int] = []
    for word in declared:
        if word == WORKLOAD_PLACEHOLDER:
            starts.append(len(command))
            command.extend(words)
        else:
            command.append(word)
    out = hashed_argv(command)
    own = _after_head(declared[: places[0]], words, _hashed_run)
    out[starts[0] : starts[0] + len(words)] = own
    if shared is not None and len(shared) == len(words):
        for start in starts:
            place = slice(start, start + len(words))
            out[place] = _fewest_shown([out[place], list(shared)])
    return out


def _with_parameters(
    words: Sequence[str],
    reading: Sequence[str],
    read: _RunReader,
    spare: list[int] | None = None,
) -> list[str]:
    """Return a reading of an argument list with each positional parameter read where it is used.

    Each parameter of a shell text (``_parameter_readings``, which ``spare``
    bounds) is taken from the reading that shows the fewest characters of
    it, ``reading`` winning a tie.
    """
    out = list(reading)
    # The arguments are read once for all the commands that use them.
    token = _READ_ARGUMENTS.set({}) if _READ_ARGUMENTS.get() is None else None
    try:
        readings = _parameter_readings(words, read, spare)
    finally:
        if token is not None:
            _READ_ARGUMENTS.reset(token)
    for place, shown in readings.items():
        if _shown_length(shown) < _shown_length(out[place]):
            out[place] = shown
    return out


def _workload_heads(argv: Sequence[str], config: Mapping[str, Any] | None) -> list[list[str]]:
    """Return what each side runs before the shared workload, as each side's spec gives it.

    That is the words of a ``cmd`` side before ``{workload}``, from each
    ``--side NAME=cmd:SPEC`` of the command line (read as ``_spec_from_text``
    reads it) and from the ``cmd`` of each side of the config, and the
    entrypoint of an image side of the config that has no arguments of its
    own. A spec that cannot be read gives nothing. A command is a list or a
    tuple of texts, as a config read from a capture holds it.
    """
    commands: list[list[str]] = []
    for flag, text, _joined in _flag_values(argv):
        if flag != FLAG_SIDE:
            continue
        _name, eq, rest = text.partition("=")
        kind, colon, spec = rest.partition(":")
        if eq and colon and kind == KIND_CMD:
            try:
                commands.append(list(_spec_from_text(KIND_CMD, spec)["argv"]))
            except Refusal:
                continue
    sides = config.get("sides") if isinstance(config, Mapping) else None
    for side in sides.values() if isinstance(sides, Mapping) else ():
        if not isinstance(side, Mapping):
            continue
        cmd = side.get("cmd")
        entrypoint = side.get("entrypoint")
        if isinstance(cmd, (list, tuple)) and all(isinstance(word, str) for word in cmd):
            commands.append(list(cmd))
        elif isinstance(entrypoint, str) and entrypoint and not side.get("args"):
            commands.append([entrypoint, WORKLOAD_PLACEHOLDER])
    return [
        words[: words.index(WORKLOAD_PLACEHOLDER)]
        for words in commands
        if WORKLOAD_PLACEHOLDER in words
    ]


def _image_heads(sides: Sequence[Side], workload: Sequence[str]) -> list[list[str]]:
    """Return what the image of each image side runs before the shared workload, as recorded.

    An image side with no ``entrypoint`` key and no arguments of its own runs
    the workload behind its image's entrypoint, which it records in its
    identity (``IMAGE_ENTRYPOINT_KEY``). That entrypoint is a head; an empty
    one is none, since the workload's first word is then the program. When
    the entrypoint names no client of ``CLIENT_PASSWORD_OPTIONS`` and the
    workload starts with an option, the first word of the image's command
    (``IMAGE_COMMAND_PROGRAM_KEY``) is a head as well: a wrapper script such
    as ``docker-entrypoint.sh`` commonly puts that program in front of
    arguments that start with ``-``. A side that recorded neither gives
    nothing.
    """
    heads: list[list[str]] = []
    for side in sides:
        if side.kind != KIND_IMAGE:
            continue
        entrypoint = side.identity.get(IMAGE_ENTRYPOINT_KEY)
        if not isinstance(entrypoint, (list, tuple)) or not entrypoint:
            continue
        if not all(isinstance(word, str) for word in entrypoint):
            continue
        heads.append(list(entrypoint))
        program = side.identity.get(IMAGE_COMMAND_PROGRAM_KEY)
        if (
            isinstance(program, str)
            and program
            and workload
            and workload[0].startswith("-")
            and not any(_client_named(word) for word in entrypoint)
        ):
            heads.append([program])
    unique: dict[tuple[str, ...], list[str]] = {}
    for head in heads:
        unique.setdefault(tuple(head), head)
    return list(unique.values())


def public_command(
    argv: Sequence[str],
    *,
    include_image_refs: bool = False,
    config: Mapping[str, Any] | None = None,
    sides: Sequence[Side] = (),
) -> str | None:
    """Return the command of a run as a results document may show it, or ``None``.

    It is made from the command line a capture header keeps and is one text,
    quoted for a shell. Nothing in it identifies the machine or shows a
    value of the environment, except the forms SECURITY.md lists under Known
    limits of the shown command:

    * the spec of every ``--side`` is hidden: ``new=image:<hidden>``. With
      ``include_image_refs`` an image reference, the spec of an ``image`` or
      ``serve`` side, is shown as typed; the spec of every other kind stays
      hidden;
    * the value of every ``--set`` is hidden: ``launch.cpus=<hidden>``;
    * every absolute path is cut to its last part, also where it follows
      ``=`` and where it sits inside an argument (after a space or a
      colon): the program, flag values and the arguments of the workload;
      an absolute path glued to an option, as in ``-I/a/include``, is cut
      to its last part, also inside an argument that holds several words;
    * an argument that assigns a credential-like variable or option, as
      ``API_TOKEN=...`` and ``--api-key=...`` do, keeps the name and loses
      the value, also when it is glued to an option, as in
      ``--env=MY_TOKEN=...`` and ``-eMY_TOKEN=...``; the value runs to the
      end of the argument, spaces included, unless the argument is a
      command text, whose next words are read as words. A command text is
      the text after ``-c`` (``sh -c``, ``bash -lc``, ``python -c``), the
      text a shell runs after an option group that holds ``c`` (``sh -ce``),
      an operand of a program of ``COMMAND_TEXT_RUNNERS`` (the remote
      command of ``ssh``, the commands of ``hyperfine``, ``watch``,
      ``parallel`` and ``tmux new``) and the value of an option of
      ``TEXT_OPTIONS`` (``gcloud ... --command``, ``env -S``), also glued
      to the option, where it is read as the same text given apart, so its
      first word names a client (``_CommandWalk.glued_text``). In each but
      the text after ``-c`` of a program that is no shell, a value given
      with ``=`` ends where its shell word ends (``_gives_no_value``), so
      ``sh -c 'tool API_KEY= && ./bench'`` keeps ``&& ./bench``. The ones
      a shell runs are shell texts, where an operator outside quotes ends
      a hidden value (``_CommandWalk.shell_run``): the text after ``-c`` of
      a shell and every one of these but two: the text of ``env -S``, which
      ``env`` splits with no shell, and a command a runner is told to run
      with no shell (``watch -x``, also in a group as ``watch -tx``,
      ``hyperfine -N`` anywhere on its command line, ``parallel -q``, a word
      with no blank of ``tmux new``). Each word of such a command but one
      that ``hyperfine -N`` splits, and each word after the first of a
      ``tmux new`` command, is one argument of the program and is read as
      any argument is (``_CommandWalk.code``);
    * an argument that gives a name that is no credential a value, as
      ``MADE_UP_FLAGS=--api-key=... --threads 8`` does, has its value read
      word by word, each word through every rule here, so the
      ``--threads 8`` after the hidden key stays;
    * a credential-like option given without ``=``, as ``--token VALUE``,
      keeps its name, and the next argument is hidden unless it is another
      long option;
    * a header whose name is a credential, as ``Authorization: ...`` or
      ``X-Api-Key: ...``, keeps its name and loses its value, and the user
      part of an address (``scheme://user:password@``) is hidden;
    * the password of a ``user:password`` given to ``-u``, ``--user``,
      ``-U`` or ``--proxy-user``, as the next argument or glued to the
      option, is hidden: ``-u user:<hidden>``;
    * the password options of the clients in ``CLIENT_PASSWORD_OPTIONS``,
      whose names say nothing of a password, lose their value:
      ``redis-benchmark -a <hidden>``, ``mysql -p<hidden>`` and
      ``ab -A user:<hidden>``. A client is found by its program word, also
      after a path, ``env``, ``sudo``, ``docker exec`` or a command
      separator, and its options apply up to the next separator. They
      also read the value of an ordinary name given before a later word
      of the same command that names the client (``_LaterClients``):
      ``env 'MADE_UP_FLAGS=-a <hidden> -n 8' redis-benchmark``;
    * a credential-like name given a value in the text of a program, as in
      ``os.environ['API_KEY'] = '...'`` or ``{"api_key": "..."}``, keeps
      its name and loses the value;
    * the host of an address is hidden unless it is a loopback name, as
      ``_hidden_host`` says: ``https://<hidden>:8443/v1``, and so is the
      host of a ``file://`` address that has no path, as
      ``_hidden_file_host`` says: ``file://<hidden>:8000``;
    * a long random-looking value, as ``looks_random`` says, is hidden
      wherever it stands: a plain argument, the value of an option, a path
      segment or a query value of an address (``/v1/<hidden>?part=<hidden>``).
      An absolute path that holds one is hidden whole.

    The last nine hold for the words inside one argument too, as in
    ``sh -c 'tool --token VALUE'``: they are read as a shell reads them,
    and a quoted part that is not closed runs to the end of the argument.

    The shared workload after ``--`` starts a command. It is read on its
    own and after the words each command side runs before it
    (``_workload_heads``, which reads the side specs of ``argv`` and the
    sides of ``config``), and each argument is shown as the reading that
    shows the least of it, so a password option of a client named only in
    a side's spec is hidden. An argument a shell text takes as a positional
    parameter is read where the text uses it too (``_with_parameters``), so
    ``sh -c 'redis-benchmark "$@"' _ {workload}`` hides the password of its
    workload. ``sides`` are the sides a capture records: the workload is
    also read after what the image of each image side runs before it
    (``_image_heads``), so the password option of a client an image starts
    as its entrypoint is hidden too.

    An empty command line gives ``None``.
    """
    if not argv:
        return None
    out: list[str] = []
    walk = _CommandWalk(ahead=argv)
    shell_text = _ShellText()
    values = list(_flag_values(argv))
    later = _LaterClients([text if flag is None else "" for flag, text, _joined in values])
    for index, (flag, text, joined) in enumerate(values):
        shell = shell_text.read(text) if flag is None else False
        ahead = _argument_ahead(
            [value[1] for value in values[index + 1 : index + 2] if value[0] is None]
        )
        shown_next = walk.shown_next(text, ahead) if flag is None else None
        if shown_next is not None:
            out.append(_hidden_host(_public_argument(shown_next)))
            continue
        if flag == FLAG_SIDE:
            walk.skip()
            shown = _public_side(text, include_image_refs)
        elif flag == FLAG_SET:
            walk.skip()
            key, eq, _value = text.partition("=")
            shown = f"{key}={HIDDEN}" if eq else HIDDEN
        else:
            client = _value_client(walk, text, later, index)
            shown = _shown_argument(walk, text, shell=shell, client=client)
        out.append(f"{flag}={shown}" if joined else shown)
        if flag is None and text == WORKLOAD_SEPARATOR:
            workload = argv[index + 1 :]
            if not walk.waiting():
                walk.new_command()
            alone = _shown_run(walk, workload, shell_text)
            readings = [_with_parameters(workload, alone, _shown_run)]
            for head in [*_workload_heads(argv, config), *_image_heads(sides, workload)]:
                readings.append(_after_head(head, workload, _shown_run))
            out.extend(_fewest_shown(readings))
            break
    return shlex.join(out)


def _argument_ahead(following: Sequence[str]) -> str | None:
    """Return the next argument of a command line, from a list of none or one, or ``None``."""
    return following[0] if following else None


# ---------------------------------------------------------------------------
# What a published hash is taken over
# ---------------------------------------------------------------------------


# Whether a setup is read as the published hashes read it. ``hidden_difference`` turns it
# off to read a setup with only its credentials hidden: a value hidden for its shape (a
# random-looking value, a run ``_hashed_whole_runs`` hides whole) is then read as typed, and
# a value hidden whole keeps all but its credential, as ``hidden_difference`` says.
_ALL_HIDDEN: ContextVar[bool] = ContextVar("_ALL_HIDDEN", default=True)


def _shapes_hidden(text: str) -> str:
    """Hide the values of a text that are hidden for their shape, unless that is turned off."""
    if not _ALL_HIDDEN.get():
        return text
    return _hidden_random(_hashed_whole_runs(text), paths=False)


def _hashed_argument(
    arg: str,
    program: str = "",
    *,
    code: bool = False,
    shell: bool = False,
    shell_words: bool = False,
    axis: bool = False,
    command: bool = False,
) -> str:
    """Return one argument of a command with its secrets hidden as ``public_command`` hides them.

    An argument whose first word gives a credential-like name a value, or
    holds a client's password glued to its option, is that value to the end
    of the argument, spaces included (``_hidden_to_the_end``), unless the
    argument is the text of a command or a program (``code``), as the one
    after ``sh -c`` or ``python -c`` is, or a command of the client's own
    (``command``): then it is read word by word, as ``_hashed_text`` reads
    it. When only the credentials are hidden (``_ALL_HIDDEN`` off) it is read
    as ``_typed_credential_argument`` says, or word by word. After an axis
    option (``axis``), or glued to one, the axis ``Key`` keeps its values
    (``_axis_value``) and a credential after them stays hidden
    (``_hidden_axis_value``). Every other
    argument is read as ``_hashed_text`` says, a shell text (``shell``) as a
    shell reads it, as ``public_command`` reads it, and its words ending as a
    shell's do when ``shell_words`` says so.
    """
    if _axis_value(arg, axis, program):
        return _shapes_hidden(_hidden_axis_value(arg))
    if code or command:
        whole = None
    elif _ALL_HIDDEN.get():
        whole = _hidden_to_the_end(arg, program)
    else:
        whole = _typed_credential_argument(arg, program)
    if whole is not None:
        return _shapes_hidden(whole)
    return _hashed_text(
        arg,
        program,
        value=not code,
        shell=shell,
        shell_words=shell_words,
        command=command,
        code=code,
    )


def _typed_credential_argument(arg: str, program: str) -> str | None:
    """Return an argument with only its credentials hidden, where reading its words hides more.

    This is the reading of ``hidden_difference``. A command glued to a
    client's ``command`` option is read whole as that client's own, as the
    shown command reads it (``_hidden_command_glued``), so the words of the
    command other than its password stay. A credential-like name or option
    whose value is an address (``DB_PASSWORD=redis://...``,
    ``--auth-url=http://...``) keeps the name and reads the address with only
    its password and its credential query values hidden. ``None`` for any
    other argument, which is read word by word.
    """
    if _SPACE.search(arg):
        command = _hidden_command_glued(arg, program)
        if command is not None:
            return command
    first = _SPACE.split(arg, maxsplit=1)[0]
    named = _hidden_credential(first)
    if named is None or not named.endswith("=" + HIDDEN):
        return None
    kept = named[: -len(HIDDEN)]
    if not arg.startswith(kept) or _ADDRESS_START.match(arg, len(kept)) is None:
        return None
    return kept + _hashed_text(arg[len(kept) :], program)


def _typed_next_value(arg: str, program: str) -> str | None:
    """Return a value hidden whole after an option with only its credential hidden, or ``None``.

    This is the reading of ``hidden_difference``. An address keeps all but
    its password and its credential query values. A value of several words
    loses its first word, or an Authorization scheme word and the token after
    it (``AUTH_SCHEME_WORDS``), and its later words are read as words:
    ``--password 'VALUE --threads 8'`` reads ``<hidden> --threads 8``.
    ``None`` for a value of one word, which stays hidden whole.
    """
    if _ADDRESS_START.match(arg) is not None:
        return _hashed_text(arg, program)
    words = _CREDENTIAL_WORDS.match(arg)
    if words is None or words.group(2) is None:
        return None
    scheme = words.group(1).lower() in AUTH_SCHEME_WORDS and words.group(3) is not None
    rest = arg[words.end() if scheme else words.end(1) :]
    return HIDDEN + _hashed_text(rest, program)


def _hashed_text(
    text: str,
    program: str = "",
    *,
    value: bool = False,
    shell: bool = False,
    shell_words: bool = False,
    command: bool = False,
    code: bool = False,
) -> str:
    """Return one argument or text with its recognised secrets hidden, and nothing else changed.

    The secrets ``public_command`` hides are replaced by ``HIDDEN`` in the
    same way: a credential-like name given a value in a program's text
    (``_hidden_code``); the credentials among the words of the text
    (``_hidden_words``: credential-like variables, options and headers, the
    word after a credential-like option, a ``user:password`` and the
    password options of a client, ``program`` being the client whose
    options apply where the text stands); the user part of an address; and
    each random-looking value (``looks_random``). Paths, hosts and every
    other value are kept as they are, so they still tell two texts apart.
    A text that is no argument of a command, as the value of a variable, is
    read word by word, so the words after a credential at its start stay.
    With ``command`` the text is a command of the client's own. With
    ``value`` the text is one argument, and when it gives an ordinary
    name its value its words are read as ``_hidden_words`` says. With
    ``shell`` the text is a shell text, read as ``public_command`` reads
    one, where a value ends at an operator that ends a command; with
    ``shell_words`` the words of the text end as a shell's do
    (``_hidden_code``). With ``code`` the text is the text of a command or a
    program, read as ``public_command`` reads it (``_hidden_words``).
    """
    hidden = _hidden_code(text, shell=shell, shell_words=shell_words, code=code)
    words = _hidden_words(
        hidden,
        program,
        shell=shell,
        command=command,
        value=value,
        code=code and not (shell or shell_words),
    )
    if not _ALL_HIDDEN.get():
        return _hidden_address_password(words)
    return _shapes_hidden(_hidden_address_user(words))


def _hashed_whole_runs(text: str) -> str:
    """Hide whole each run that ``public_command`` hides whole.

    These are the runs ``_cut_as_path`` accepts that hold a random-looking
    part: a run that holds ``+/``, as base64 does, a run that starts with
    ``/``, as an absolute path or a base64 value may, alone or glued to an
    option, and a run that starts with an option and holds a ``/``, which
    keeps its dashes or its option of one letter (``-k<hidden>``). So a value
    the shown command hides whole leaves no part of it in the hash, whatever
    its first character. A run that holds percent escapes is left to
    ``_hidden_random``, which hides it whole.
    """

    def shown(found: re.Match[str]) -> str:
        run = found.group(0)
        if _PERCENT_ESCAPE.search(run) or not _cut_as_path(run, found.start(), text):
            return run
        kept = 2 if _SHORT_OPTION.match(run) else len(run) - len(run.lstrip("-"))
        if not _random_spans(run, found.start(), text):
            return run
        return run[:kept] + HIDDEN

    if _LONG_RUN.search(text) is None:
        return text
    return _TOKEN_RUN.sub(shown, text)


def hashed_argv(argv: Sequence[str]) -> list[str]:
    """Return an argument list as every published hash of it reads it: its secrets hidden.

    The arguments are read in order, as ``public_command`` reads a command
    line, so the argument after a credential-like option (``--token VALUE``)
    or after ``-u`` is hidden too, and each client's password options apply
    after its program word. Each argument is then read as
    ``_hashed_argument`` says, a command text (the one after ``-c``, the
    remote command of ``ssh`` and the others ``public_command`` lists) as
    the text of a command, as ``public_command`` reads it. Paths, hosts and
    ordinary values are kept, and a list that holds no secret is returned
    as it is.
    """
    reading = _hashed_run(_CommandWalk(ahead=argv), argv)
    return _with_parameters(argv, reading, _hashed_run)


def _hashed_run(
    walk: _CommandWalk, argv: Sequence[str], shells: _ShellText | None = None
) -> list[str]:
    """Return arguments read in order through a walk, each as every published hash reads it.

    A shell text (the text after ``-c`` of a shell, ``shells``, or another
    command text a shell runs, ``_CommandWalk.shell_run``) is read as
    ``public_command`` reads it; a fresh ``shells`` is used when none is given.
    """
    shells = _ShellText() if shells is None else shells
    later = _LaterClients(argv)
    out: list[str] = []
    for k, arg in enumerate(argv):
        shell = shells.read(arg)
        program = walk.program
        shown_next = walk.shown_next(arg, _argument_ahead(argv[k + 1 : k + 2]))
        if shown_next is not None:
            typed = None
            if shown_next == HIDDEN and not _ALL_HIDDEN.get():
                typed = _typed_next_value(arg, program)
            out.append(_hashed_argument(shown_next) if typed is None else typed)
            continue
        # As ``_shown_argument`` reads it: with the client of the walk, or a later one.
        out.append(_hashed_one(walk, arg, shell=shell, client=_value_client(walk, arg, later, k)))
    return out


def _hashed_one(walk: _CommandWalk, arg: str, *, shell: bool = False, client: str = "") -> str:
    """Read one argument through a walk and return it as every published hash reads it.

    It is read with the options of the client the walk holds, or else of
    ``client``, and an option with its text glued to it
    (``_CommandWalk.glued_text``) is read with its text as the option's
    next word, as ``_shown_argument`` reads it.
    """
    split = walk.glued_text(arg)
    if split is not None:
        walk.read(split[0])
        return _glued_shown(split[1], _hashed_one(walk, split[2], shell=shell, client=client))
    axis = walk.axis
    own = walk.command_text(arg)
    code = walk.code(arg)
    program = walk.program or ("" if own or code else client)
    shell = walk.shell_run(arg) or shell
    shell_words = walk.shell_word(arg)
    walk.read(arg)
    return _read_once(
        _hashed_argument,
        arg,
        program,
        code=code,
        shell=shell,
        shell_words=shell_words,
        axis=axis,
        command=own,
    )


def _hashed_workload(
    argv: Sequence[str], config: Mapping[str, Any], sides: Sequence[Side] = ()
) -> list[str]:
    """Return the shared workload as ``config_sha256`` hashes it: read after each side.

    The workload is read alone, as ``hashed_argv`` reads it, and after what
    each side runs before it (``_workload_heads``, and ``_image_heads`` of
    the recorded ``sides``); an argument is taken from the reading that
    hides the most of it, so a value one side's program hides is hidden for
    all.
    """
    readings = [hashed_argv(argv)]
    for head in [*_workload_heads((), config), *_image_heads(sides, argv)]:
        readings.append(_after_head(head, argv, _hashed_run))
    return _fewest_shown(readings)


# A version by the pattern of PEP 440 (https://peps.python.org/pep-0440/, appendix B): an
# epoch, the release numbers, a pre, post or dev release and a local label, each but the
# release maybe left out.
_PEP440_LABELS = (
    r"(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?"
    r"(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?"
    r"(?:[-_.]?dev[-_.]?[0-9]*)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?"
)
_PEP440_VERSION = r"v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*" + _PEP440_LABELS
# The same with two release numbers or more (``24.3.0``): after a colon, as a setting is also
# written, only such a version is told from a password or a number.
_DOTTED_VERSION = r"v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)+" + _PEP440_LABELS
# A distribution name by the pattern of PEP 508 (https://peps.python.org/pep-0508/#names).
_DIST_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
# The pin of a distribution that starts a line, up to a blank, a ``;`` or the end of the line:
# ``NAME==VERSION`` as ``pip freeze`` prints it, also with blanks around ``==``, and
# ``- NAME=VERSION=BUILD`` as ``conda env export`` prints it. What follows the pin on its line
# (``# via``, an environment marker, a ``\``, an option) is read as any other text.
_PIN_HEAD = re.compile(
    r"[ \t]*(?:"
    + _DIST_NAME
    + r"[ \t]*==[ \t]*"
    + _PEP440_VERSION
    + r"|-[ \t]+"
    + _DIST_NAME
    + "="
    + _PEP440_VERSION
    + r"=[A-Za-z0-9_.]+)(?=[ \t;]|$)",
    re.IGNORECASE,
)
# A line that is a name and a dotted version alone, after a colon (``keyring: 24.3.0``).
_PIN_COLON = re.compile(r"[ \t]*" + _DIST_NAME + r":[ \t]*" + _DOTTED_VERSION + r"[ \t]*", re.I)
# A name and a dotted version in quotes, as a Python or JSON table prints them
# (``'keyring': '24.3.0'``).
_PIN_PAIR = re.compile(
    r"(['\"])" + _DIST_NAME + r"\1[ \t]*:[ \t]*(['\"])" + _DOTTED_VERSION + r"\2", re.I
)
# A line that names a digest and gives one: a name whose last word names a digest
# (``SECRET_SHA256``, ``password_hash``), ``=`` or ``:``, and a value of hexadecimal digits as
# long as a digest is, or the name of a way to hash a password.
_DIGEST_LINE = re.compile(
    r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*[=:][ \t]*"
    r"(?:[0-9a-f]{128}|[0-9a-f]{96}|[0-9a-f]{64}|[0-9a-f]{56}|[0-9a-f]{40}|[0-9a-f]{32}"
    r"|bcrypt|scrypt|yescrypt|argon2(?:i|d|id)?|pbkdf2(?:[_-]sha(?:1|256|512))?"
    r"|sha(?:1|224|256|384|512)|md5)[ \t]*",
    re.IGNORECASE,
)
# The last words of a name that names a digest.
_DIGEST_ENDS: Final[frozenset[tuple[str, ...]]] = frozenset(
    {("HASH",), ("DIGEST",), ("CHECKSUM",), ("MD", "5")}
    | {("SHA", bits) for bits in ("1", "224", "256", "384", "512")}
)


def hashed_output(text: str) -> str:
    """Return the output of an ``identify`` command as every published hash reads it.

    An identify command prints what tells one build from another, so each
    line keeps every value but a credential. The name rules of the shown
    command apply (``_hidden_code`` and ``_hidden_words``): a credential-like
    name given a value, the value after a credential-like option or setting,
    a credential header, a ``user:password`` and the password options of a
    client are replaced by ``HIDDEN``, and so is the user part of an address.
    No rule of shape applies: a checksum, a build id, a key size and any
    other long or random-looking value are kept, so a change in them changes
    the hash. A version is no credential, whatever the name before it reads
    like: the pin that starts a line (``keyring==24.3.0``,
    ``keyring == 24.3.0``, ``- keyring=24.3.0=pyh0_0``) is kept and the rest
    of its line is read as any other text; a line of a name and a dotted
    version alone (``keyring: 24.3.0``) and a quoted name and dotted version
    of a table (``{'keyring': '24.3.0'}``) are kept, and so is a line that
    names a digest and gives one (``SECRET_SHA256=<hex>``,
    ``password_hash: bcrypt``). ``keyring=24.3.0`` alone is hidden, as a
    variable is. A form that runs to the end of its text, as a header does,
    ends at the end of its line, so a change on any other line still changes
    the hash. The line ends are kept, and an output that holds no credential
    is returned as it is.
    """
    out: list[str] = []
    for line in text.split("\n"):
        body = line.removesuffix("\r")
        out.append(_identified_line(body) + line[len(body) :])
    return "\n".join(out)


def _identified_line(line: str) -> str:
    """Return one line of an identify command's output with its credentials hidden."""
    if _PIN_COLON.fullmatch(line) or _names_a_digest(line):
        return line
    head = _PIN_HEAD.match(line)
    if head is not None:
        return head.group() + _identified_text(line[head.end() :])
    out: list[str] = []
    at = 0
    for start, end in _pin_pairs(line):
        out += [_identified_text(line[at:start]), line[start:end]]
        at = end
    out.append(_identified_text(line[at:]))
    return "".join(out)


def _identified_text(text: str) -> str:
    """Return a piece of an identify line with its credentials hidden, by the command's rules."""
    shown = _hidden_words(_hidden_code(text))
    return _address_sub(_ADDRESS_USER, lambda found: f"{found.group(1)}{HIDDEN}@", shown)


def _names_a_digest(line: str) -> bool:
    """Say whether a line is a name that names a digest, given a digest or a way to hash."""
    found = _DIGEST_LINE.fullmatch(line)
    if found is None:
        return False
    words = name_words(found.group(1))
    return words[-1:] in _DIGEST_ENDS or words[-2:] in _DIGEST_ENDS


def _pin_pairs(line: str) -> list[tuple[int, int]]:
    """Return where a line holds a quoted name and dotted version outside any other quotes.

    A pair inside a quoted value (``{'token': "x 'keyring': '1.2'"}``) is part
    of that value, so it is no pair. One pass over the line.
    """
    if "'" not in line and '"' not in line:
        return []
    found = list(_PIN_PAIR.finditer(line))
    if not found:
        return []
    pairs: list[tuple[int, int]] = []
    pending = iter(found)
    nearest = next(pending, None)
    quote = ""
    at = 0
    while at < len(line):
        while nearest is not None and nearest.start() < at:
            nearest = next(pending, None)
        if nearest is None:
            break
        if not quote and at == nearest.start():
            pairs.append(nearest.span())
            at = nearest.end()
            continue
        char = line[at]
        if quote and char == "\\":
            at += 2
            continue
        if quote and char == quote:
            quote = ""
        elif not quote and char in "'\"":
            quote = char
        at += 1
    return pairs


def _hashed_value(value: Any) -> Any:
    """Return a value of a table read as one text, or as it is when it is no text."""
    return _hashed_text(value) if isinstance(value, str) else value


def _hashed_env(env: Any) -> Any:
    """Return an environment table with the value of each credential-like name hidden.

    Every other value is read as one text (``_hashed_text``). What is no
    table is returned as it is.
    """
    if not isinstance(env, Mapping):
        return env
    return {
        name: HIDDEN if looks_like_credential(str(name)) else _hashed_value(value)
        for name, value in env.items()
    }


def _hashed_free(value: Any) -> Any:
    """Return a free value, as a probe's body or a plug-in's spec, with its secrets hidden.

    In a table the text value of a credential-like key is hidden; every
    other text is read as ``_hashed_text`` says, also inside nested tables.
    A list that holds only texts is read as an argument list, as
    ``hashed_argv`` reads one, so the text after a credential-like option
    (``["--token", VALUE]``) is hidden too; any other list is read item by
    item. Numbers and the rest are kept.
    """
    if isinstance(value, str):
        return _hashed_text(value)
    texts = _texts(value)
    if texts is not None:
        return hashed_argv(texts)
    if isinstance(value, Mapping):
        return {
            key: HIDDEN
            if isinstance(item, str) and looks_like_credential(str(key))
            else _hashed_free(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_hashed_free(item) for item in value]
    return value


def _texts(value: Any) -> list[str] | None:
    """Return a list of texts as it is, or ``None`` when it is not one."""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _hashed_command(head: list[str], args: list[str]) -> tuple[list[str], list[str]]:
    """Hide the secrets of a program and its arguments read as one argument list.

    ``head`` is what starts the command (an image's entrypoint, a server's
    command) and ``args`` what follows it; they are read together, so an
    option at the end of one and its value at the start of the other are
    one pair, and they are returned apart.
    """
    hashed = hashed_argv([*head, *args])
    return hashed[: len(head)], hashed[len(head) :]


def _hashed_launch(launch: Any) -> Any:
    """Return the launch part of a fingerprint with its secrets hidden.

    The entrypoint and the arguments are read as one argument list, and the
    environment as ``_hashed_env`` says. The names of passed variables, the
    mounts, the limits and every other key are kept as they are; what is no
    table is returned as it is.
    """
    if not isinstance(launch, Mapping):
        return launch
    out = dict(launch)
    entrypoint = launch.get("entrypoint")
    head = [entrypoint] if isinstance(entrypoint, str) else []
    args = _texts(launch.get("args"))
    if args is not None:
        hashed_head, out["args"] = _hashed_command(head, args)
        if head:
            out["entrypoint"] = hashed_head[0]
    elif head:
        out["entrypoint"] = hashed_argv(head)[0]
    if "env" in launch:
        out["env"] = _hashed_env(launch["env"])
    return out


def _hashed_launch_table(table: Any) -> Any:
    """Return a ``launch`` table of a config with its environment and identify command hidden."""
    if not isinstance(table, Mapping):
        return table
    out = dict(table)
    if "env" in table:
        out["env"] = _hashed_env(table["env"])
    identify = _texts(table.get("identify"))
    if identify is not None:
        out["identify"] = hashed_argv(identify)
    return out


def _hashed_serve(serve: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``serve`` table of a side with its secrets hidden.

    The command and the arguments are read as one argument list, the
    environment as ``_hashed_env`` says, the address paths of the readiness
    check and the probe as texts, and the probe's body as a free value.
    """
    out = dict(serve)
    command = _texts(serve.get("command")) or []
    args = _texts(serve.get("args"))
    if args is not None:
        hashed_command, out["args"] = _hashed_command(command, args)
        if command:
            out["command"] = hashed_command
    elif command:
        out["command"] = hashed_argv(command)
    if "env" in serve:
        out["env"] = _hashed_env(serve["env"])
    ready = serve.get("ready")
    if isinstance(ready, Mapping):
        out["ready"] = (
            {**ready, "http": _hashed_value(ready.get("http"))} if "http" in ready else dict(ready)
        )
    probe = serve.get("probe")
    if isinstance(probe, Mapping):
        out["probe"] = {
            key: _hashed_free(item) if key == "body" else _hashed_value(item)
            for key, item in probe.items()
        }
    return out


def _hashed_side(side: Any) -> Any:
    """Return one side's table of a config with its secrets hidden, as its fingerprint has them."""
    if not isinstance(side, Mapping):
        return side
    out = dict(side)
    cmd = _texts(side.get("cmd"))
    if cmd is not None:
        out["cmd"] = hashed_argv(cmd)
    if "image" in side:
        entrypoint = side.get("entrypoint")
        head = [entrypoint] if isinstance(entrypoint, str) else []
        args = _texts(side.get("args"))
        if args is not None:
            hashed_head, out["args"] = _hashed_command(head, args)
            if head:
                out["entrypoint"] = hashed_head[0]
        elif head:
            out["entrypoint"] = hashed_argv(head)[0]
        if "env" in side:
            out["env"] = _hashed_env(side["env"])
    if isinstance(side.get("serve"), Mapping):
        out["serve"] = _hashed_serve(side["serve"])
    if "kind" in side and "spec" in side:
        out["spec"] = _hashed_free(side["spec"])
    if "launch" in side:
        out["launch"] = _hashed_launch_table(side["launch"])
    return out


def _hashed_config(config: Any, recorded: Sequence[Side] = ()) -> Any:
    """Return a config as ``config_sha256`` hashes it: every secret its sides would get hidden.

    The workload's arguments, each side's command, image arguments and
    entrypoint, environment, serving command, arguments, readiness check and
    probe, a plug-in side's spec, and the environment and identify command of
    the shared and of each side's launch table are read as the fingerprint
    reads them; the workload also after what the image of each ``recorded``
    side runs before it (``_hashed_workload``). Every other key, the paths
    among them, is kept as it is; what is no table is returned as it is.
    """
    if not isinstance(config, Mapping):
        return config
    out = dict(config)
    workload = config.get("workload")
    if isinstance(workload, Mapping):
        argv = _texts(workload.get("argv"))
        if argv is not None:
            out["workload"] = {**workload, "argv": _hashed_workload(argv, config, recorded)}
    sides = config.get("sides")
    if isinstance(sides, Mapping):
        out["sides"] = {name: _hashed_side(side) for name, side in sides.items()}
    if "launch" in config:
        out["launch"] = _hashed_launch_table(config["launch"])
    return out


def side_setup(config: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """Return what a recorded config says side ``name`` runs, or ``None`` when it does not say.

    The setup is the side's table without its baseline mark, the shared
    ``launch`` table and the workload's arguments: what ``hidden_difference``
    compares between two sides, or between one side in two captures. A
    config that holds no table for the side gives ``None``.
    """
    plain = _encode(config) if isinstance(config, Mapping) else None
    sides = plain.get("sides") if isinstance(plain, dict) else None
    side = sides.get(name) if isinstance(sides, dict) else None
    if not isinstance(side, dict):
        return None
    workload = plain.get("workload") if isinstance(plain, dict) else None
    return {
        "side": {key: value for key, value in side.items() if key != "baseline"},
        "launch": plain.get("launch") if isinstance(plain, dict) else None,
        "argv": workload.get("argv") if isinstance(workload, dict) else None,
    }


def _hashed_setup(setup: Mapping[str, Any]) -> dict[str, Any]:
    """Return a setup of ``side_setup`` read as the published hashes read it."""
    argv = _texts(setup.get("argv"))
    return {
        "side": _hashed_side(setup.get("side")),
        "launch": _hashed_launch_table(setup.get("launch")),
        "argv": hashed_argv(argv) if argv is not None else setup.get("argv"),
    }


def _shape_only(shown: tuple[Any, Any], typed: tuple[Any, Any]) -> bool:
    """Say whether some value is equal in both ``shown`` readings and differs in ``typed``.

    The two pairs hold the same structure read two ways; a table or a list
    that is not alike in both setups is passed over.
    """
    (one, two), (first, second) = shown, typed
    if all(isinstance(v, Mapping) for v in (one, two, first, second)):
        keys = set(one) & set(two) & set(first) & set(second)
        return any(_shape_only((one[k], two[k]), (first[k], second[k])) for k in sorted(keys))
    if all(isinstance(v, list) for v in (one, two, first, second)):
        if not len(one) == len(two) == len(first) == len(second):
            return False
        return any(
            _shape_only((a, b), (c, d)) for a, b, c, d in zip(one, two, first, second, strict=True)
        )
    return bool(one == two and first != second)


def hidden_difference(one: Mapping[str, Any] | None, two: Mapping[str, Any] | None) -> bool:
    """Say whether two setups of ``side_setup`` differ in more than a credential.

    Each setup is read twice: as the published hashes read it, with every
    recognised secret and every value hidden for its shape hidden (a
    random-looking value, a run of hexadecimal digits in a path, a run that
    ``public_command`` hides whole), and with only the credentials
    themselves hidden. In the second reading a value the hashes hide whole
    keeps all but its credential:
    an argument whose value the hashes hide to its end, spaces included, and
    a value of several words after a credential-like option, are read word
    by word, so only the value up to its first blank stays hidden, or an
    Authorization scheme word and the token after it
    (``AUTH_SCHEME_WORDS``); a client's command glued to its ``command``
    option keeps every word but its password; and an address keeps its user
    name, host, path and query, and loses only its password and the values
    of its credential-like query parameters, also when it is the value of a
    credential-like name. The word after a scheme word that is a credential's
    whole value (``--auth basic WORD``, ``AUTH=token WORD``), which the hashes
    hide as a token, is read as typed. The setups differ in a hidden value when some
    value reads the same in both setups the first way and differs the second
    way. A difference only in a credential, or in a value the hashes show,
    is no such difference, and neither is a missing setup. The answer is a
    yes or no: nothing of the second reading is kept or shown.
    """
    if one is None or two is None:
        return False
    shown = (_hashed_setup(one), _hashed_setup(two))
    token = _ALL_HIDDEN.set(False)
    try:
        typed = (_hashed_setup(one), _hashed_setup(two))
    finally:
        _ALL_HIDDEN.reset(token)
    return _shape_only(shown, typed)


def recorded_workload(config: Mapping[str, Any] | None) -> list[str] | None:
    """Return the shared workload's arguments a recorded config holds, or ``None``.

    A config with a ``workload`` table that names no arguments holds an empty
    workload. A config with no ``workload`` table, as a header that records
    no config, and arguments that are not a list of texts give ``None``:
    there is no workload to compare.
    """
    plain = _encode(config) if isinstance(config, Mapping) else None
    workload = plain.get("workload") if isinstance(plain, dict) else None
    if not isinstance(workload, dict):
        return None
    argv = workload.get("argv")
    if argv is None:
        return []
    return _texts(argv)


def _shown_workload(
    argv: Sequence[str], configs: Sequence[Mapping[str, Any]], recorded: Sequence[Side] = ()
) -> list[str]:
    """Return each argument of a workload as the shown command shows it, after every side.

    The workload is read as ``public_command`` reads it, after what every
    side of each of ``configs`` runs before it and after what each of the
    ``recorded`` sides recorded its image runs before it, so a value any of
    them hides is hidden. When the shown command does not give one text per
    argument, every argument is shown as ``HIDDEN``.
    """
    sides: dict[str, Any] = {}
    for k, config in enumerate(configs):
        own = config.get("sides")
        for name, side in own.items() if isinstance(own, Mapping) else ():
            sides[f"{k}-{name}"] = side
    command = public_command([WORKLOAD_SEPARATOR, *argv], config={"sides": sides}, sides=recorded)
    words = shlex.split(command)[1:] if command is not None else []
    return words if len(words) == len(argv) else [HIDDEN] * len(argv)


def workload_difference(
    one: Mapping[str, Any],
    two: Mapping[str, Any],
    one_sides: Sequence[Side] = (),
    two_sides: Sequence[Side] = (),
) -> tuple[int, str | None, str | None] | None:
    """Return where the shared workloads of two recorded configs differ, or ``None``.

    Each workload (``recorded_workload``) is read as the published hashes
    read it under its own config and the sides its capture records
    (``config_inputs``): alone, after what each side runs before it and
    after what each recorded image side's image runs before it
    (``one_sides``, ``two_sides``), with every recognised secret and every
    value hidden for its shape hidden. The answer is the 1-based place of
    the first argument at which the two readings differ, and the text the
    shown command shows of that argument in each workload, read after the
    sides of both configs and both captures; ``None`` stands for a workload
    that has no argument there. Two texts alike say that the arguments
    differ in a part the shown command leaves out, as the folders of a path.
    Two workloads typed alike, two that differ only in a credential or in a
    value hidden for its shape, and a config that holds no workload give
    ``None``.
    """
    first, second = recorded_workload(one), recorded_workload(two)
    if first is None or second is None or first == second:
        return None
    one, two = _encode(one), _encode(two)
    readings = (_hashed_workload(first, one, one_sides), _hashed_workload(second, two, two_sides))
    if readings[0] == readings[1]:
        return None
    place = next(
        (k for k, (a, b) in enumerate(zip(*readings, strict=False)) if a != b),
        min(len(r) for r in readings),
    )
    recorded = (*one_sides, *two_sides)
    texts: list[str | None] = []
    for argv in (first, second):
        shown = _shown_workload(argv, (one, two), recorded)
        texts.append(shown[place] if place < len(argv) else None)
    return place + 1, texts[0], texts[1]


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanRow(_Model):
    """One launch of the plan. ``pos`` is 1-based. ``side`` is the side a twin copies."""

    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "round": {"minimum": 1},
        "pos": {"minimum": 1},
    }

    round: int
    pos: int
    name: str
    side: str
    twin_of: str | None = None


@dataclass(frozen=True)
class PairBalance(_Model):
    """How often each of a compared pair ran first, and the signed sum of their positions."""

    a: str
    b: str
    a_first: int
    b_first: int
    position_sum: int

    @property
    def balanced(self) -> bool:
        """Whether each ran first equally often and the position differences sum to zero."""
        return self.a_first == self.b_first and self.position_sum == 0


def _rows(
    twin_of: Mapping[str, str | None], rounds: int, control: tuple[str, str] | None = None
) -> tuple[PlanRow, ...]:
    names = list(twin_of)
    rows: list[PlanRow] = []
    for r in range(1, rounds + 1):
        for pos, name in enumerate(rotate_reverse(names, r), start=1):
            of = twin_of[name]
            rows.append(PlanRow(round=r, pos=pos, name=name, side=of or name, twin_of=of))
        if control is not None:
            name, baseline = control
            rows.append(PlanRow(round=r, pos=len(names) + 1, name=name, side=baseline))
    return tuple(rows)


def plan_rows(
    lineup: Sequence[Side], rounds: int, control: Side | None = None
) -> tuple[PlanRow, ...]:
    """Lay out ``rounds`` rounds of a lineup under the ``rotate-reverse`` schedule.

    The positive control is no part of the lineup and is not rotated. Given
    one, every round ends with one more row for it, at the position one past
    the lineup's length; the row names the baseline under ``side`` and has no
    ``twin_of``. The rows of the lineup are the same with a control and
    without.
    """
    entry: tuple[str, str] | None = None
    if control is not None:
        if control.control_of is None:
            raise ValueError(f"side {control.name!r} is not a positive control")
        if any(s.role == "control" for s in lineup):
            raise ValueError("the positive control is no part of the lineup")
        entry = (control.name, control.control_of)
    return _rows({s.name: s.twin_of for s in lineup}, rounds, entry)


def compared_pairs(sides: Sequence[Side]) -> tuple[tuple[str, str], ...]:
    """Return the compared pairs: each subject with the baseline, each side with its twin.

    The positive control is not one of a compared pair: it always runs last,
    so the refusal of an order that never changes does not apply to it.
    """
    names = {s.name for s in sides}
    baseline = next((s.name for s in sides if s.role == "baseline"), None)
    pairs = [(s.name, baseline) for s in sides if s.role == "subject" and baseline is not None]
    pairs += [(s.twin_of, s.name) for s in sides if s.twin_of is not None and s.twin_of in names]
    return tuple(pairs)


def count_balance(
    rows: Sequence[PlanRow], pairs: Sequence[tuple[str, str]]
) -> tuple[PairBalance, ...]:
    """Count, over planned rows, how often each of a pair ran first.

    A round in which either of the pair has no row, or no position, is not
    counted.
    """
    position: dict[tuple[int, str], int] = {(r.round, r.name): r.pos for r in rows}
    rounds = sorted({r.round for r in rows})
    out: list[PairBalance] = []
    for a, b in pairs:
        a_first = b_first = total = 0
        for r in rounds:
            pa, pb = position.get((r, a)), position.get((r, b))
            if pa is None or pb is None:
                continue
            a_first += pa < pb
            b_first += pb < pa
            total += pa - pb
        out.append(PairBalance(a=a, b=b, a_first=a_first, b_first=b_first, position_sum=total))
    return tuple(out)


def _positions_even(rows: Sequence[PlanRow], lineup: Sequence[str]) -> bool:
    if not rows or not lineup:
        return False
    counts: dict[tuple[str, int], int] = {}
    for row in rows:
        counts[(row.name, row.pos)] = counts.get((row.name, row.pos), 0) + 1
    rounds = len({row.round for row in rows})
    share, rest = divmod(rounds, len(lineup))
    if rest:
        return False
    return all(
        counts.get((name, pos), 0) == share for name in lineup for pos in range(1, len(lineup) + 1)
    )


@dataclass(frozen=True)
class Plan(_Model):
    """The order of every launch of a run.

    ``balance`` holds, per compared pair, the order counts over ``rows``.
    ``rounds_requested`` is ``None`` when the count was left to the tool.
    ``launches`` counts the warm-up launches and the launches of every round,
    one per round for the positive control: ``planned_launches``.
    ``explain_launches`` counts the explain launches on their own:
    ``planned_explain_launches``. ``control`` names the positive-control
    entry, or is ``None``. The control is no part of ``lineup``; its rows sit
    at the position one past the lineup's length, and the balance, the
    balanced step and every round count are the same with it and without.
    """

    rows: tuple[PlanRow, ...]
    rounds_requested: int | None
    rounds_planned: int
    lineup: tuple[str, ...]
    balance: tuple[PairBalance, ...]
    launches: int
    estimate_s: float | None = None
    explain_launches: int = 0
    control: str | None = None

    def _pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple((p.a, p.b) for p in self.balance)

    def is_balanced(self) -> bool:
        """Say whether the planned rows are balanced, by counting over them.

        Balanced means: every lineup entry occupies every position equally
        often; in every compared pair each runs first equally often; and the
        signed difference of positions of every compared pair sums to zero.
        """
        if not _positions_even(self.rows, self.lineup):
            return False
        return all(p.balanced for p in count_balance(self.rows, self._pairs()))

    def balanced_step(self) -> int:
        """Return the smallest round count that is balanced for this lineup, found by search."""
        recorded = {r.name: r.twin_of for r in self.rows}
        twin_of = {name: recorded.get(name) for name in self.lineup}
        pairs = self._pairs()
        for rounds in range(1, 2 * len(twin_of) + 1):
            rows = _rows(twin_of, rounds)
            if _positions_even(rows, self.lineup) and all(
                p.balanced for p in count_balance(rows, pairs)
            ):
                return rounds
        raise ValueError("no balanced round count exists for an empty lineup")

    def to_tsv(self) -> str:
        """Return the plan table: tab-separated, with the columns round pos name side twin_of."""
        lines = ["round\tpos\tname\tside\ttwin_of"]
        lines += [f"{r.round}\t{r.pos}\t{r.name}\t{r.side}\t{r.twin_of or ''}" for r in self.rows]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The capture and its records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Header(_Model):
    """The first record of a capture.

    ``config`` is the resolved config with credential-like values redacted.
    ``schema`` is the schema id; a record that names another one is refused.
    """

    RECORD: ClassVar[str | None] = "header"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    capture_id: str
    tool_version: str = TOOL_VERSION
    started_at: str | None = None
    argv: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    seeds: Mapping[str, Any] = field(default_factory=dict)
    schema: Literal["pairbench/capture/v1"] = SCHEMA_CAPTURE


@dataclass(frozen=True)
class CpuGroup(_Model):
    """A set of CPUs of one core type: the CPU list, the type key, the maximum frequency."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    cpus: str
    key: str
    max_khz: int = 0


@dataclass(frozen=True)
class CpuRecord(_Model):
    """The CPU of the machine. ``cache_domains`` lists the CPUs that share a last-level cache."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    model: str
    identity: tuple[CpuGroup, ...] = ()
    cache_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpuInfo(_Model):
    """A GPU's model and driver version."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    model: str
    driver: str


@dataclass(frozen=True)
class EngineInfo(_Model):
    """A container engine's name and version."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: str
    version: str


@dataclass(frozen=True)
class MachineRecord(_Model):
    """The machine a capture was taken on.

    ``tool_cpus`` is the CPU list the tool moved its own process and its
    sampler threads to, outside the pinned set, so that the tool shares no
    CPU with a launch. It is ``None`` when the tool did not move: no CPU set
    was pinned, the platform does not allow it, or no CPU is left outside
    the set.
    """

    RECORD: ClassVar[str | None] = "machine"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"tool_cpus"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"tool_cpus": {"pattern": CPU_LIST_PATTERN}}

    os: str
    arch: str
    cpu: CpuRecord
    gpu: tuple[GpuInfo, ...] = ()
    engine: EngineInfo | None = None
    in_container: bool = False
    ci: bool = False
    node_type: str | None = None
    tool_cpus: str | None = None

    def summary(self) -> MachineSummary:
        """Return the machine facts a results document may show."""
        keys = tuple(dict.fromkeys(group.key for group in self.cpu.identity))
        return MachineSummary(os=self.os, arch=self.arch, cpu_model=self.cpu.model, core_types=keys)


@dataclass(frozen=True)
class GateRecord(_Model):
    """The result of one machine check.

    ``detail["message"]``, when present, is a one-line reason that holds
    nothing which identifies the machine; it is what a results document shows.
    """

    RECORD: ClassVar[str | None] = "gate"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: str
    mode: GateMode
    status: GateStatus
    detail: Mapping[str, Any] = field(default_factory=dict)

    def _shown_name(self) -> ShownGate:
        return cast("ShownGate", self.name if self.name in BUILTIN_GATES else PLUGIN_NAME)

    def summary(self) -> GateSummary:
        """Return the check as a results document shows it, without its detail.

        A check that a plug-in provides is shown under the name ``plugin``.
        """
        return GateSummary(name=self._shown_name(), mode=self.mode, status=self.status)

    def degraded(self) -> Degraded | None:
        """Return the entry for a check that did not pass, or ``None`` for one that passed.

        An absolute path in the reason is cut to its last part.
        """
        if self.status == "pass":
            return None
        message = self.detail.get("message")
        text = public_text(message) if isinstance(message, str) else ""
        return Degraded(name=self._shown_name(), status=self.status, message=text)


@dataclass(frozen=True)
class Lineup(_Model):
    """The lineup, the planned rounds, the cases and the thresholds, written before round 1.

    ``control`` names the positive-control entry, which is no part of
    ``names``: it runs last in every round, at the position one past the
    length of ``names``. It is ``None`` when the run has no control.
    """

    RECORD: ClassVar[str | None] = "lineup"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"control"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"control": {"minLength": 1}}

    names: tuple[str, ...]
    control: str | None = field(default=None, kw_only=True)
    rounds: int
    schedule: str | None = SCHEDULE
    cases: tuple[Case, ...] = ()
    discard_thresholds: DiscardThresholds | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.control is not None and self.control in self.names:
            raise ValueError("the positive control is no part of the lineup's names")


@dataclass(frozen=True)
class CasesRecord(_Model):
    """Cases that were not known when the lineup record was written."""

    RECORD: ClassVar[str | None] = "cases"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    cases: tuple[Case, ...]


@dataclass(frozen=True)
class CaseName(_Model):
    """The name a run gave to a case id that a side read, when the run cut or hid part of it.

    ``name`` is the id as ``public_case`` shows it; when the cut dropped
    words that hold no ``/`` (``public_case_drops``) it ends with the mark
    ``case_suffix`` gives for the run's key and the tell. ``side`` is the
    side that read the id. ``tell_sha256`` is the SHA-256 of what tells the
    case apart from ids cut alike: the words of its id that hold no ``/``,
    read with its secrets hidden (``case_secrets_hidden``) and the folders
    of a path written with ``%2F`` cut (``case_tell_words``), for a name
    with a mark, and the name itself for any other. ``hidden_sha256`` is the
    SHA-256 of the id with its secrets hidden, and ``read_sha256`` of the id
    as read, so pooled captures can say whether the ids they read as one
    case differ in a folder or in a secret. A run writes one entry for each
    side and id of a name it cut or hid; an id it shows as read, of such a
    name, has one too. The capture holds these entries and the capture is
    private: no results document holds a hash of them.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "name": {"minLength": 1},
        "side": {"minLength": 1},
        "tell_sha256": {"pattern": SHA256_PATTERN},
        "hidden_sha256": {"pattern": SHA256_PATTERN},
        "read_sha256": {"pattern": SHA256_PATTERN},
    }

    name: str
    side: str
    tell_sha256: str
    hidden_sha256: str
    read_sha256: str


@dataclass(frozen=True)
class CaseKeyRecord(_Model):
    """The run's own random key for the marks it adds to case names (``case_suffix``).

    A run draws it from the operating system's source of random numbers and
    writes it once, before the first ``case_names`` record; no flag, setting
    or variable gives it. It stays in the capture, which is private: the
    results show the marks it makes, never the key.
    """

    RECORD: ClassVar[str | None] = "case_key"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"key": {"pattern": SHA256_PATTERN}}

    key: str


@dataclass(frozen=True)
class CaseNamesRecord(_Model):
    """Names a launch gave to case ids it cut or hid (``CaseName``).

    It is written before the launch record of the launch whose output first
    gave them, after the run's key (``CaseKeyRecord``) when a name carries a
    mark. A run gives an id the same name in every launch.
    """

    RECORD: ClassVar[str | None] = "case_names"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    names: tuple[CaseName, ...]


@dataclass(frozen=True)
class Launch(_Model):
    """One launch. A warm-up has round 0. ``pos`` is ``None`` when the order was not recorded.

    ``timing`` holds ``run_s`` and ``launch_s`` where the side reports them.
    ``witness`` is the JSON form of ``Witness`` and may hold more keys.

    ``runs`` is how many runs of the workload the launch held: 2 for a launch
    of the positive control that runs the workload twice in one start, and 1
    for every other launch, the control under ``factor`` included. Its
    timing is one interval around all its runs. ``env_pad`` is the length of
    the environment pad of the launch, in bytes, and ``None`` when the
    environment size is not varied. ``timed_out`` is true when the launch ran
    into its time limit, ``launch.timeout``, for every kind of side, the load
    of a serving side included; ``rc`` is then what the side reported for the
    stopped launch.
    """

    RECORD: ClassVar[str | None] = "launch"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset(
        {"tool_version", "runs", "env_pad", "timed_out"}
    )
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "round": {"minimum": 0},
        "pos": {"minimum": 1},
        "runs": {"minimum": 1, "maximum": 2},
        "env_pad": {"minimum": 0, "maximum": ENV_PAD_MAX},
    }

    seq: int
    phase: Phase
    round: int
    pos: int | None
    name: str
    rc: int = 0
    timing: Mapping[str, float] = field(default_factory=dict)
    witness: Mapping[str, Any] = field(default_factory=dict)
    energy: Mapping[str, Any] | None = None
    tool_version: str | None = None
    runs: int = 1
    env_pad: int | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class LaunchCost(_Model):
    """What a launch costs before the workload does anything.

    An empty command is launched ``n`` times through the launch path of a
    command side during warm-up; the times are in seconds. The figure is an
    upper bound on what the tool adds to a ``wall`` value: the tool's own
    work plus the start of a process. In a capture this is the record
    ``launch_cost``, written after the warm-up launches; a results document
    carries the same object. ``command`` is the name of the empty command,
    never the path it was found at.
    """

    RECORD: ClassVar[str | None] = "launch_cost"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "command": {"pattern": r"^[^/\\]+$"},
        "n": {"minimum": 1},
        "median_s": {"minimum": 0},
        "p25_s": {"minimum": 0},
        "p75_s": {"minimum": 0},
        "min_s": {"minimum": 0},
    }

    command: str
    n: int
    median_s: float
    p25_s: float
    p75_s: float
    min_s: float

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.min_s <= self.p25_s <= self.median_s <= self.p75_s:
            raise ValueError(
                "LaunchCost: the least time, the first quartile, the median and the third "
                "quartile come in that order"
            )

    @classmethod
    def of(cls, command: str, times_s: Sequence[float]) -> LaunchCost:
        """Build the record from the times of the empty launches.

        The median and the quartiles use ``quantile``.
        """
        if not times_s:
            raise ValueError("the cost of a launch needs at least one timed launch")
        return cls(
            command=command,
            n=len(times_s),
            median_s=quantile(times_s, 0.5),
            p25_s=quantile(times_s, 0.25),
            p75_s=quantile(times_s, 0.75),
            min_s=min(times_s),
        )

    @property
    def spread_s(self) -> float:
        """The spread of the cost: the third quartile minus the first."""
        return self.p75_s - self.p25_s


@dataclass(frozen=True)
class Observation(_Model):
    """One value of one case from one launch; ``seq`` names the launch.

    ``value`` is a finite number; it may be zero or less, which an analysis
    grades as no verdict. ``suite`` is the suite a row of the text input
    format names. It is kept and changes neither the case id nor the floor
    group.
    """

    RECORD: ClassVar[str | None] = "obs"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"suite"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "round": {"minimum": 0},
        "pos": {"minimum": 1},
        "n_inner": {"minimum": 1},
    }

    seq: int
    round: int
    pos: int | None
    name: str
    case: str
    value: float
    n_inner: int = 1
    reducer: str = "identity"
    suite: str | None = None


@dataclass(frozen=True)
class Note(_Model):
    """A loud note: a stable code and a plain-language message."""

    RECORD: ClassVar[str | None] = "note"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"code": {"pattern": "^[a-z][a-z0-9_]*$"}}

    code: str
    message: str

    def for_results(self) -> Note:
        """Return the note as a results document shows it: absolute paths cut to their last part."""
        return dataclasses.replace(self, message=public_text(self.message))


@dataclass(frozen=True)
class End(_Model):
    """The last record of a capture. Without it the capture is incomplete.

    ``sha256_of_preceding`` is the hash of every line before this record, and
    ``None`` for a capture that was never a file. ``discard_sha256`` is the
    hash of the decision on disturbed rounds.
    """

    RECORD: ClassVar[str | None] = "end"
    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"discard_sha256", "finished_at"})

    status: EndStatus
    rounds_completed: int
    sha256_of_preceding: str | None = None
    discard_sha256: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class ReaderInfo(_Model):
    """What the reader of another input format reports about one run it read.

    ``run_index`` is the position of the run in its file, from 0.
    ``metadata`` holds every metadata line of the run as a ``(key, value)``
    pair, verbatim and in file order, repeated keys included.
    ``sides_declared`` are the names the input declares and ``sides_observed``
    the names its data rows hold, each in order of first appearance.
    ``malformed_rows`` counts the rows skipped as malformed, ``comments`` the
    comment lines, and ``one_sided_keys`` the keys of round and case that hold
    a value for one side only.
    """

    reader: str
    run_index: int = 0
    metadata: tuple[tuple[str, str], ...] = ()
    sides_declared: tuple[str, ...] = ()
    sides_observed: tuple[str, ...] = ()
    malformed_rows: int = 0
    comments: int = 0
    one_sided_keys: int = 0

    def get(self, key: str) -> str | None:
        """Return the value of the last metadata line with this key, or ``None``."""
        found = [value for name, value in self.metadata if name == key]
        return found[-1] if found else None


@dataclass(frozen=True)
class Source(_Coerced):
    """Where a capture was read from. It is not part of the capture's records.

    ``path`` and ``sha256`` are the file and the hash of its bytes. ``torn``
    says the file's last line was cut short. ``reader`` is set by a reader of
    another input format and carries its counts. ``round_labels`` holds the
    round number the input gave each round of the capture, round 1 first,
    when those labels are not 1, 2, 3 and on; it is empty otherwise. A
    refusal names a round by its label.
    """

    path: str | None = None
    sha256: str | None = None
    torn: bool = False
    reader: ReaderInfo | None = None
    round_labels: tuple[int, ...] = ()

    def round_label(self, number: int) -> int:
        """Return the label the input gave the capture's round ``number``."""
        if 1 <= number <= len(self.round_labels):
            return self.round_labels[number - 1]
        return number


RECORD_TYPES: Final[Mapping[str, type[_Model]]] = {
    "header": Header,
    "machine": MachineRecord,
    "side": Side,
    "gate": GateRecord,
    "lineup": Lineup,
    "cases": CasesRecord,
    "case_key": CaseKeyRecord,
    "case_names": CaseNamesRecord,
    "launch": Launch,
    "obs": Observation,
    "launch_cost": LaunchCost,
    "note": Note,
    "end": End,
}

Record = (
    Header
    | MachineRecord
    | Side
    | GateRecord
    | Lineup
    | CasesRecord
    | CaseKeyRecord
    | CaseNamesRecord
    | Launch
    | Observation
    | LaunchCost
    | Note
    | End
)


def record_from_json(data: Mapping[str, Any]) -> Record:
    """Build one capture record from its JSON form, chosen by its ``"t"`` key."""
    kind = data.get("t") if isinstance(data, Mapping) else None
    cls = RECORD_TYPES.get(kind) if isinstance(kind, str) else None
    if cls is None:
        raise Refusal("E_USAGE", f"not a capture record: record type {kind!r}")
    return cast("Record", cls.from_json(data))


def _merge_cases(first: Sequence[Case], more: Sequence[Case]) -> tuple[Case, ...]:
    seen = {c.id for c in first}
    out = list(first)
    for case in more:
        if case.id not in seen:
            seen.add(case.id)
            out.append(case)
    return tuple(out)


def round_numbers(labels: Iterable[int]) -> dict[int, int]:
    """Number round labels 1, 2, 3 and on in their order: ``{label: round}``.

    Round numbers given from outside the tool are labels that pair the rows
    of a round; any whole number is one. A capture numbers its rounds from 1
    with no gap, so the smallest label becomes round 1, the next round 2, and
    so on. Labels that already run 1, 2, 3 keep their numbers.
    """
    return {label: number for number, label in enumerate(sorted(set(labels)), start=1)}


@dataclass(frozen=True)
class Capture(_Coerced):
    """The raw record of one run.

    ``cases`` holds every case: those of the lineup record and those recorded
    later. ``notes`` are the loud notes of the run. ``launch_cost`` is the
    measured cost of a launch, or ``None`` when none was measured. ``source``
    says where the capture was read from and is not part of its records.
    ``case_key`` is the run's own key for the marks it adds to case names
    (``CaseKeyRecord``), or ``None`` when no name needed one; ``case_names``
    holds the names the run gave to ids it cut or hid, from every
    ``case_names`` record, in order.

    The positive-control entry has a side record with the role ``control``
    and one launch per round at the position one past the lineup's length.
    The explain launches are no part of a capture.
    """

    capture_id: str
    header: Header
    machine: MachineRecord | None = None
    sides: tuple[Side, ...] = ()
    gates: tuple[GateRecord, ...] = ()
    lineup: Lineup | None = None
    cases: tuple[Case, ...] = ()
    launches: tuple[Launch, ...] = ()
    observations: tuple[Observation, ...] = ()
    end: End | None = None
    notes: tuple[Note, ...] = ()
    source: Source | None = None
    launch_cost: LaunchCost | None = None
    case_key: str | None = None
    case_names: tuple[CaseName, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether the capture has an end record that says the run completed."""
        return self.end is not None and self.end.status == "complete"

    @property
    def baseline(self) -> str | None:
        """The name of the baseline side, or ``None`` when no side has that role."""
        return next((s.name for s in self.sides if s.role == "baseline"), None)

    @property
    def order_recorded(self) -> bool:
        """Whether every round launch has a recorded position."""
        launches = self.round_launches()
        return bool(launches) and all(launch.pos is not None for launch in launches)

    @property
    def control(self) -> Side | None:
        """The positive-control entry: the side record whose role is ``control``, or ``None``.

        The relation is the declared ``control_of`` field and is never told
        from a name.
        """
        return next((s for s in self.sides if s.role == "control"), None)

    def _recorded(self, table: str) -> Mapping[str, Any]:
        found = self.header.config.get(table)
        return found if isinstance(found, Mapping) else {}

    def control_settings(self) -> ControlSettings:
        """Return the settings of the positive control the recorded config holds.

        A key the recorded config does not hold, or holds with a value that
        is not valid, has its default. This is how an analysis learns the
        tolerance and how the control doubled the work.
        """
        recorded = self._recorded("controls")
        chosen: dict[str, Any] = {}
        for name in ("positive", "positive_tolerance", "positive_via"):
            if name in recorded:
                try:
                    ControlSettings(**{name: recorded[name]})
                except ValueError:
                    continue
                chosen[name] = recorded[name]
        return ControlSettings(**chosen)

    def launch_cost_share(self) -> float:
        """Return the recorded ``launch_cost.note_share``, or its default."""
        default = LaunchCostSettings().note_share
        share: Any = self._recorded("launch_cost").get("note_share", default)
        try:
            return LaunchCostSettings(note_share=share).note_share
        except ValueError:
            return default

    def explain_launches(self) -> int:
        """Return the number of explain launches the run planned.

        It follows from the recorded explain mode and the number of subjects
        and baselines. A capture whose sides no run launched, one made from
        rows or from result files, plans none.
        """
        launched = [s for s in self.sides if s.role in ("subject", "baseline")]
        if not launched or any(s.kind in (KIND_ROWS, KIND_FILE) for s in launched):
            return 0
        mode = self._recorded("explain").get("mode", ExplainSettings().mode)
        if mode not in EXPLAIN_MODES:
            mode = ExplainSettings().mode
        return planned_explain_launches(len(launched), mode)

    def side(self, name: str) -> Side:
        """Return the side or twin with this name."""
        for s in self.sides:
            if s.name == name:
                return s
        raise KeyError(name)

    def round_launches(self) -> tuple[Launch, ...]:
        """Return the launches of the measured rounds, without the warm-ups."""
        return tuple(launch for launch in self.launches if launch.phase == "round")

    def ref(self) -> CaptureRef:
        """Return the entry a results document lists for this capture.

        ``sha256`` is the hash of the capture file, when the capture was read
        from one or written to one. ``rounds`` is the number of completed
        rounds the end record states, or the number of rounds that have a
        launch when there is no end record.
        """
        if self.end is not None:
            rounds = self.end.rounds_completed
        else:
            rounds = len({launch.round for launch in self.round_launches()})
        digest = self.source.sha256 if self.source is not None else None
        return CaptureRef(capture_id=self.capture_id, sha256=digest, rounds=rounds)

    def driver_info(self) -> DriverInfo | None:
        """Return the driver and the tool versions a results document shows, or ``None``.

        The driver is the one the recorded config names. A driver that a
        plug-in provides is not named.
        """
        workload = self.header.config.get("workload")
        named = workload.get("driver") if isinstance(workload, Mapping) else None
        versions = tuple(sorted({x.tool_version for x in self.launches if x.tool_version}))
        if named is None and not versions:
            return None
        name = named if isinstance(named, str) and named in BUILTIN_DRIVERS else None
        return DriverInfo(name=cast("ShownDriver | None", name), tool_versions=versions)

    def side_drivers(self) -> dict[str, str | None]:
        """Return the name of the driver that read each side, as the run chose it.

        A result file side that names its own ``format`` is read by that
        driver; every other side by the driver the recorded config names.
        ``None`` when neither is recorded. A plug-in's name is kept here, in
        the private record; a results document never shows it.
        """
        workload = self.header.config.get("workload")
        named = workload.get("driver") if isinstance(workload, Mapping) else None
        default = named if isinstance(named, str) and named else None
        drivers: dict[str, str | None] = {}
        for side in self.sides:
            own = side.spec.get("format") if side.kind == KIND_FILE else None
            drivers[side.name] = own if isinstance(own, str) and own else default
        return drivers

    def side_driver_info(self, name: str) -> DriverInfo | None:
        """Return the driver that read side ``name`` and the tool versions its launches recorded.

        A driver that a plug-in provides is not named. ``None`` when neither
        the driver nor a version is known.
        """
        driver = self.side_drivers().get(name)
        versions = tuple(
            sorted({x.tool_version for x in self.launches if x.name == name and x.tool_version})
        )
        if driver is None and not versions:
            return None
        shown = driver if driver in BUILTIN_DRIVERS else None
        return DriverInfo(name=cast("ShownDriver | None", shown), tool_versions=versions)

    def driver_notes(self) -> tuple[Note, ...]:
        """Return the loud note of compared sides that different drivers read, or nothing.

        Each driver reads what its own tool measured, and two tools can define
        the same figure differently, such as the time to a first token. A
        ratio between such sides compares the tools as well as the sides. The
        sides compared are the subjects and the baseline.
        """
        drivers = self.side_drivers()
        compared = [s.name for s in self.sides if s.role in ("subject", "baseline")]
        if len({drivers[name] for name in compared}) < 2:
            return ()
        read = ", ".join(f"{name} by {_driver_words(drivers[name])}" for name in compared)
        return (
            Note(
                code=NOTE_DRIVERS_DIFFER,
                message=f"the sides were read by different drivers ({read}); each tool "
                "measures as its own documentation defines, so a ratio between these sides "
                "compares the tools as well as the sides",
            ),
        )

    def round_observations(self) -> tuple[Observation, ...]:
        """Return the observations of the measured rounds, without those of the warm-ups."""
        warm = {launch.seq for launch in self.launches if launch.phase == "warmup"}
        return tuple(o for o in self.observations if o.seq not in warm and o.round >= 1)

    def env_pad(self) -> EnvPad:
        """Return what a results document records about the size of the environment.

        The size was varied when a launch of a round carries a pad length.
        """
        return EnvPad.of(any(x.env_pad is not None for x in self.round_launches()))

    def set_aside(self) -> SetAside | None:
        """Return the decision on disturbed rounds, from the recorded thresholds and witnesses.

        ``None`` when the capture records no thresholds.
        """
        if self.lineup is None or self.lineup.discard_thresholds is None:
            return None
        witnesses = [
            RoundWitness(round=x.round, name=x.name, witness=Witness.from_json(x.witness))
            for x in self.round_launches()
        ]
        return set_aside(self.lineup.discard_thresholds, witnesses)

    def undecided_launches(self) -> int:
        """Return how many launches of the measured rounds the witnesses could not judge.

        A launch is undecided when a witness that holds the launch's own load
        is above its threshold (see ``undecided``). It is 0 when the capture
        records no thresholds.
        """
        if self.lineup is None or self.lineup.discard_thresholds is None:
            return 0
        thresholds = self.lineup.discard_thresholds
        return sum(
            1 for x in self.round_launches() if undecided(Witness.from_json(x.witness), thresholds)
        )

    def with_twins(self, twins: Mapping[str, str]) -> Capture:
        """Return a copy in which the named lineup entries are twins of other sides.

        ``twins`` maps a twin's name to its side, as in ``from_rows``. It is
        how the caller of ``load_capture`` declares a twin relation that the
        file itself does not state. A twin gets the kind, spec, identity and
        fingerprint of its side. A name that is no entry of the capture, a
        side that is itself a twin or a control, and the baseline or the
        control named as a twin are refused. A twin whose side is absent is
        refused with ``E_TWIN_ORPHAN``, as in ``from_rows``.
        """
        by_name = {s.name: s for s in self.sides}
        changed: dict[str, Side] = {}
        for twin, of in twins.items():
            if twin not in by_name:
                raise Refusal("E_USAGE", f"{twin!r} is no side of this capture")
            side = by_name.get(of)
            if side is None:
                raise Refusal(
                    "E_TWIN_ORPHAN", f"the twin {twin!r} names the side {of!r}, which is absent"
                )
            if of == twin or side.role in ("twin", "control") or of in twins:
                raise Refusal("E_USAGE", f"{twin!r} cannot be a twin of {of!r}")
            if by_name[twin].role in ("baseline", "control"):
                raise Refusal("E_USAGE", f"the {by_name[twin].role} {twin!r} cannot be a twin")
            changed[twin] = dataclasses.replace(side, name=twin, role="twin", twin_of=of)
        sides = tuple(changed.get(s.name, s) for s in self.sides)
        return dataclasses.replace(self, sides=sides)

    def to_records(self) -> list[dict[str, Any]]:
        """Return the records of the capture, one plain dict per line of ``capture.jsonl``.

        The order is: header, machine, sides, gates, lineup, later cases, the
        key for the marks of case names and the names that carry one, each
        launch followed by its observations, notes, end. The cost of a launch, when one was
        measured, follows the warm-up launches.
        """
        out: list[dict[str, Any]] = [self.header.to_json()]
        if self.machine is not None:
            out.append(self.machine.to_json())
        out += [s.to_json() for s in self.sides]
        out += [g.to_json() for g in self.gates]
        known: set[str] = set()
        if self.lineup is not None:
            out.append(self.lineup.to_json())
            known = {c.id for c in self.lineup.cases}
        later = tuple(c for c in self.cases if c.id not in known)
        if later:
            out.append(CasesRecord(cases=later).to_json())
        if self.case_key is not None:
            out.append(CaseKeyRecord(key=self.case_key).to_json())
        if self.case_names:
            out.append(CaseNamesRecord(names=self.case_names).to_json())
        by_seq: dict[int, list[Observation]] = {}
        for obs in self.observations:
            by_seq.setdefault(obs.seq, []).append(obs)
        cost = self.launch_cost
        for launch in self.launches:
            if cost is not None and launch.phase != "warmup":
                out.append(cost.to_json())
                cost = None
            out.append(launch.to_json())
            out += [o.to_json() for o in by_seq.pop(launch.seq, [])]
        for rest in by_seq.values():
            out += [o.to_json() for o in rest]
        if cost is not None:
            out.append(cost.to_json())
        out += [n.to_json() for n in self.notes]
        if self.end is not None:
            out.append(self.end.to_json())
        return out

    @classmethod
    def from_records(
        cls, records: Iterable[Mapping[str, Any]], *, source: Source | None = None
    ) -> Capture:
        """Build a capture from its records, in any order. A missing header is refused."""
        header: Header | None = None
        machine: MachineRecord | None = None
        lineup: Lineup | None = None
        end: End | None = None
        cost: LaunchCost | None = None
        sides: list[Side] = []
        gates: list[GateRecord] = []
        later: list[Case] = []
        key: str | None = None
        names: list[CaseName] = []
        launches: list[Launch] = []
        observations: list[Observation] = []
        notes: list[Note] = []
        for data in records:
            record = record_from_json(data)
            if isinstance(record, Observation):
                observations.append(record)
            elif isinstance(record, Launch):
                launches.append(record)
            elif isinstance(record, Side):
                sides.append(record)
            elif isinstance(record, GateRecord):
                gates.append(record)
            elif isinstance(record, Note):
                notes.append(record)
            elif isinstance(record, CasesRecord):
                later += record.cases
            elif isinstance(record, CaseNamesRecord):
                names += record.names
            elif isinstance(record, CaseKeyRecord):
                if key is not None:
                    raise Refusal("E_USAGE", "a capture has two case_key records")
                key = record.key
            elif isinstance(record, Header):
                if header is not None:
                    raise Refusal("E_USAGE", "a capture has two header records")
                header = record
            elif isinstance(record, MachineRecord):
                machine = record
            elif isinstance(record, Lineup):
                if lineup is not None:
                    raise Refusal("E_USAGE", "a capture has two lineup records")
                lineup = record
            elif isinstance(record, End):
                end = record
            elif isinstance(record, LaunchCost):
                if cost is not None:
                    raise Refusal("E_USAGE", "a capture has two launch_cost records")
                cost = record
        if header is None:
            raise Refusal("E_USAGE", "a capture needs a header record")
        return cls(
            capture_id=header.capture_id,
            header=header,
            machine=machine,
            sides=tuple(sides),
            gates=tuple(gates),
            lineup=lineup,
            cases=_merge_cases(lineup.cases if lineup else (), later),
            launches=tuple(launches),
            observations=tuple(observations),
            end=end,
            notes=tuple(notes),
            source=source,
            launch_cost=cost,
            case_key=key,
            case_names=tuple(names),
        )

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[tuple[int, str, str, float]],
        *,
        sides: Sequence[str | Side],
        twins: Mapping[str, str] | None = None,
        positions: Mapping[tuple[int, str], int] | None = None,
        cases: Sequence[Case] | None = None,
        unit: str = "s",
    ) -> Capture:
        """Build a capture from rows of ``(round, side, case, value)`` produced elsewhere.

        ``sides`` names the sides in lineup order; the last is the baseline
        unless a ``Side`` given here says otherwise. ``twins`` maps a twin's
        name to its side; a twin whose side is absent is refused with
        ``E_TWIN_ORPHAN``. ``positions`` maps ``(round, side)`` to the position
        it ran in; a launch without one has no recorded order, and the capture
        then says its order was not recorded.

        ``cases`` takes the ``Case`` records of the rows' cases and so says
        which cases are primary and what their unit and direction are; a row
        that names a case they do not hold is refused. Without ``cases``
        every case is primary and lower-is-better, in the unit that ``unit``
        names, and of kind ``time`` when that is a unit of time. A value of
        zero or less is kept; an analysis gives its case no verdict.

        A round is any whole number: round numbers are labels that pair the
        rows of a round. The capture numbers its rounds 1, 2, 3 and on in the
        order of the labels (``round_numbers``), so rows labelled from 3 give
        the capture rows labelled from 1 give, and a label no row holds is no
        round. ``positions`` is keyed by the labels as given. When the labels
        are not 1, 2, 3 and on, the capture's ``source`` keeps them, so that a
        refusal names a round by the label the rows gave it.
        """
        declared = [s if isinstance(s, Side) else Side(name=s, kind=KIND_ROWS) for s in sides]
        if not declared:
            raise Refusal("E_USAGE", "from_rows needs at least one side")
        if not any(s.role == "baseline" for s in declared):
            declared[-1] = declared[-1].with_role("baseline")
        by_name = {s.name: s for s in declared}
        if len(by_name) != len(declared):
            raise Refusal("E_USAGE", "from_rows was given a side name twice")
        lineup: list[Side] = []
        twin_names = dict(twins or {})
        for side in declared:
            lineup.append(side)
            for twin, of in twin_names.items():
                if of == side.name:
                    if twin in by_name:
                        raise Refusal("E_USAGE", f"{twin!r} is both a side and a twin")
                    lineup.append(dataclasses.replace(side, name=twin, role="twin", twin_of=of))
        orphans = sorted(t for t, of in twin_names.items() if of not in by_name)
        if orphans:
            raise Refusal(
                "E_TWIN_ORPHAN", f"twins name a side that is absent: {', '.join(orphans)}"
            )
        order = {s.name: i for i, s in enumerate(lineup)}

        declared_cases: dict[str, Case] | None = None
        if cases is not None:
            declared_cases = {}
            for given in cases:
                if not isinstance(given, Case):
                    raise Refusal("E_USAGE", f"from_rows takes Case records as cases: {given!r}")
                if given.id in declared_cases:
                    raise Refusal("E_USAGE", f"from_rows was given the case {given.id!r} twice")
                declared_cases[given.id] = given
        if not isinstance(unit, str):
            raise Refusal("E_USAGE", f"a unit is a text: {unit!r}")

        cells: dict[tuple[int, str], list[tuple[str, float]]] = {}
        found_cases: dict[str, Case] = {}
        plain: list[list[Any]] = []
        for row in rows:
            round_, name, case, value = row
            if isinstance(round_, bool) or not isinstance(round_, int):
                raise Refusal("E_USAGE", f"a round is a whole number: {round_!r}")
            if name not in order:
                raise Refusal("E_USAGE", f"a row names {name!r}, which is no side or twin")
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise Refusal("E_USAGE", f"a value is a finite number: {value!r}")
            cells.setdefault((round_, name), []).append((case, value))
            if declared_cases is None:
                found_cases.setdefault(
                    case, Case(id=case, metric="value", unit=unit, kind=kind_of_unit(unit))
                )
            elif case not in declared_cases:
                raise Refusal(
                    "E_USAGE", f"a row names the case {case!r}, which the cases given do not hold"
                )
            plain.append([round_, name, case, value])
        recorded = tuple((declared_cases if declared_cases is not None else found_cases).values())
        numbers = round_numbers(label for label, _ in cells)
        cells = {(numbers[label], name): values for (label, name), values in cells.items()}
        positions = {
            (numbers[label], name): pos
            for (label, name), pos in (positions or {}).items()
            if label in numbers
        }

        def sort_key(cell: tuple[int, str]) -> tuple[int, int, int]:
            pos = positions.get(cell)
            return (cell[0], pos if pos is not None else len(order) + 1, order[cell[1]])

        launches: list[Launch] = []
        observations: list[Observation] = []
        for seq, cell in enumerate(sorted(cells, key=sort_key), start=1):
            round_, name = cell
            pos = positions.get(cell)
            launches.append(Launch(seq=seq, phase="round", round=round_, pos=pos, name=name))
            observations += [
                Observation(seq=seq, round=round_, pos=pos, name=name, case=case, value=value)
                for case, value in cells[cell]
            ]
        rounds = len({cell[0] for cell in cells})
        capture_id = "rows-" + sha256_hex(canonical_json(plain))[:12]
        labels = tuple(sorted(numbers))
        return cls(
            capture_id=capture_id,
            header=Header(capture_id=capture_id),
            sides=tuple(lineup),
            lineup=Lineup(
                names=tuple(s.name for s in lineup),
                rounds=rounds,
                schedule=None,
                cases=recorded,
            ),
            cases=recorded,
            launches=tuple(launches),
            observations=tuple(observations),
            end=End(status="complete", rounds_completed=rounds),
            source=Source(round_labels=labels) if labels != tuple(numbers.values()) else None,
        )


# ---------------------------------------------------------------------------
# The verdict rule and supplied floors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule(_Model):
    """The verdict rule. Results always record every field of the rule used.

    ``scale``: ``ratio`` grades the median of subject over baseline;
    ``percent`` grades the median of ``100.0 * (S - B) / B``.
    ``floor_scope``: which floor a comparison uses: that of its case group,
    its own case, the largest of its side, or the largest of the experiment.
    ``bar``: ``sum_of_both`` floors, ``twice_larger`` of the two, or
    ``twice_experiment_max``. ``bar_round_digits``: decimals each floor is
    rounded to before the bar is formed, or ``None``.
    ``require_both_floors``: no verdict when only one side has a twin.
    ``p_source``: the Holm-corrected p-value or the raw one.
    ``p_inclusive``: ``p <= alpha`` is significant. ``gap_inclusive``:
    ``gap >= bar`` is outside the bar. ``tie``: when a comparison is a tie.
    ``min_rounds``: a fixed minimum, or ``None`` for ``min_rounds(m, alpha)``.
    """

    name: str
    scale: Scale = "ratio"
    floor_scope: Literal["group", "case", "side", "experiment"] = "group"
    bar: Literal["sum_of_both", "twice_larger", "twice_experiment_max"] = "sum_of_both"
    bar_round_digits: int | None = None
    require_both_floors: bool = True
    p_source: Literal["corrected", "raw"] = "corrected"
    alpha: float = 0.05
    p_inclusive: bool = False
    gap_inclusive: bool = False
    tie: Literal["inside_and_not_significant", "inside", "never"] = "inside_and_not_significant"
    min_rounds: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("Rule.alpha must lie between 0 and 1")
        if self.bar_round_digits is not None and self.bar_round_digits < 0:
            raise ValueError("Rule.bar_round_digits must not be negative")
        if self.min_rounds is not None and self.min_rounds < 1:
            raise ValueError("Rule.min_rounds must be at least 1")

    @property
    def unit(self) -> FloorUnit:
        """The unit of floors, bars and gaps under this rule's scale."""
        return FLOOR_UNITS[self.scale]


STRICT: Final = Rule(
    "strict",
    scale="ratio",
    floor_scope="group",
    bar="sum_of_both",
    bar_round_digits=None,
    require_both_floors=True,
    p_source="corrected",
    alpha=0.05,
    p_inclusive=False,
    gap_inclusive=False,
    tie="inside_and_not_significant",
    min_rounds=None,
)


@dataclass(frozen=True)
class Floors(_Coerced):
    """Noise floors measured elsewhere: one value for all sides, or one per side name.

    A value is in the unit of the scale of the rule it is analysed under: a
    fraction under scale ``ratio``, where 0.012 means 1.2 percent, and percent
    under scale ``percent``, where 1.2 means 1.2 percent.
    """

    value: float | Mapping[str, float]

    def __post_init__(self) -> None:
        super().__post_init__()
        values = self.value.values() if isinstance(self.value, Mapping) else [self.value]
        for v in values:
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"a floor is a number of zero or more: {v!r}")

    def for_side(self, name: str) -> float | None:
        """Return the floor supplied for a side, or ``None`` when none was."""
        if isinstance(self.value, Mapping):
            return self.value.get(name)
        return self.value


# ---------------------------------------------------------------------------
# The results document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool(_Model):
    """The tool that wrote a results document."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: str = TOOL_NAME
    version: str = TOOL_VERSION


@dataclass(frozen=True)
class CaptureRef(_Model):
    """One capture a results document was computed from."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    capture_id: str
    sha256: str | None
    rounds: int


@dataclass(frozen=True)
class RunInfo(_Model):
    """The run. ``command`` is how to reproduce it, with nothing that identifies the machine
    except the forms SECURITY.md lists under Known limits of the shown command."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"command"})

    id: str
    started_at: str | None
    finished_at: str | None
    captures: tuple[CaptureRef, ...]
    pooled: bool = False
    command: str | None = None


@dataclass(frozen=True)
class RuleInfo(_Model):
    """The rule used: every field of it, the family size, and the family in plain words."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: str
    fields: Mapping[str, Any]
    family_size: int
    plain: str


def grades_raw_p(rule: RuleInfo) -> bool:
    """Whether the rule grades every case on its uncorrected p-value."""
    return rule.fields.get("p_source") == "raw"


# A p-value below this is written as the bound ``< 1e-300``: the float of an
# exact p-value from more than about a thousand untied pairs has lost its
# digits or is zero.
P_SMALLEST_WRITTEN = 1e-300


def p_written(p: float, spec: str) -> str:
    """Write a p-value in a format specification, or ``< 1e-300`` below ``P_SMALLEST_WRITTEN``."""
    if p < P_SMALLEST_WRITTEN:
        return f"< {P_SMALLEST_WRITTEN:g}"
    return format(p, spec)


def p_equation(p: float, spec: str) -> str:
    """Write ``p = 0.023`` in a sentence, or ``p < 1e-300`` below ``P_SMALLEST_WRITTEN``."""
    text = p_written(p, spec)
    return f"p {text}" if text.startswith("<") else f"p = {text}"


def family_words(rule: RuleInfo, comparisons: Sequence[Comparison] = ()) -> str:
    """Name the size of the family a correction covers: ``3 cases`` or ``6 comparisons``.

    The family holds one comparison per subject and primary case with a
    p-value. With one subject in it, each comparison is a case; with more,
    the count is of comparisons, so two subjects on three cases read
    ``6 comparisons``, never ``6 cases``.
    """
    subjects = {c.subject for c in comparisons if c.primary and c.p_raw is not None}
    noun = "comparisons" if len(subjects) > 1 else "cases"
    return f"{rule.family_size} {noun}"


def raw_p_note(rule: RuleInfo, comparisons: Sequence[Comparison] = ()) -> str:
    """The sentence a report gives under a rule that grades on uncorrected p-values.

    It says that no p-value is corrected and why the corrected p-value of a
    case, which ``results.json`` keeps as ``p_corrected``, can differ: the
    correction accounts for every comparison of the family at once, and the
    rule does not apply it. ``comparisons`` are the comparisons of the
    results; they tell cases from comparisons (``family_words``). A
    corrected p-value is never smaller than the uncorrected one, and is the
    same when one case is tested.
    """
    said = f"No p-value is corrected: rule {rule.name} grades each case on its own p-value"
    if rule.family_size == 1:
        return f"{said}; with one case tested, the corrected p-value is the same."
    if rule.family_size < 1:
        return f"{said}."
    return (
        f"{said} and does not correct for testing {family_words(rule, comparisons)} at once, "
        "so a p-value here can be smaller than the corrected one, which results.json keeps "
        "as p_corrected."
    )


def _driver_words(name: str | None) -> str:
    """Name a driver as a results document may: a plug-in's name is never shown."""
    if name is None:
        return "a driver not recorded"
    return f"driver {name}" if name in BUILTIN_DRIVERS else "a plug-in driver"


def pooled_driver_info(infos: Sequence[DriverInfo | None]) -> DriverInfo | None:
    """Return one driver entry for several entries, or ``None``.

    ``infos`` holds one entry per pooled capture of a side, or one per side
    of a run; ``None`` where neither the driver nor a tool version is
    recorded. Each tool version is kept once, sorted. The name is kept when
    every entry names the same driver; when they differ it is ``None``, and
    the ``drivers_differ`` note names each one.
    """
    known = [info for info in infos if info is not None]
    if not known:
        return None
    names = {info.name if info is not None else None for info in infos}
    versions = tuple(sorted({v for info in known for v in info.tool_versions}))
    return DriverInfo(name=known[0].name if len(names) == 1 else None, tool_versions=versions)


def pooled_driver_notes(captures: Sequence[Capture]) -> tuple[Note, ...]:
    """Return the loud note of compared sides that pooled captures read by different drivers.

    Pooling the values of one side read by two tools mixes two definitions
    of a figure. The note names, for each such subject or baseline, the
    driver of each capture; a plug-in's name is never shown. Nothing when
    fewer than two captures are given or every side was read alike.
    """
    if len(captures) < 2:
        return ()
    each = [capture.side_drivers() for capture in captures]
    parts: list[str] = []
    for side in captures[0].sides:
        if side.role not in ("subject", "baseline"):
            continue
        by: dict[str, list[str]] = {}
        for capture, drivers in zip(captures, each, strict=True):
            by.setdefault(_driver_words(drivers.get(side.name)), []).append(capture.capture_id)
        if len(by) > 1:
            read = " and ".join(f"{words} in {', '.join(ids)}" for words, ids in by.items())
            parts.append(f"side {side.name} by {read}")
    if not parts:
        return ()
    return (
        Note(
            code=NOTE_DRIVERS_DIFFER,
            message=f"the pooled captures read the sides by different drivers "
            f"({'; '.join(parts)}); each tool measures as its own documentation defines, "
            "so pooling them mixes the figures of two tools",
        ),
    )


def _read_by(driver: DriverInfo) -> str:
    said = _driver_words(driver.name) if driver.name else "a driver not named"
    if not driver.tool_versions:
        return said
    label = "tool version" if len(driver.tool_versions) == 1 else "tool versions"
    return f"{said}, {label} {', '.join(driver.tool_versions)}"


def driver_text(results: Results) -> str | None:
    """The sentence a report gives on the drivers that read the values, or ``None``.

    When every subject and the baseline were read alike it names the driver
    once; when the results name no side's driver, it names the one of
    ``provenance.driver``. When the driver or the tool version differs
    between the sides it names the driver of each side.
    """
    sides = [s for s in results.sides if s.role in ("subject", "baseline")]
    read = [(s.name, s.driver) for s in sides if s.driver is not None]
    if len({driver for _, driver in read}) > 1:
        (first, by), *rest = [(name, _read_by(driver)) for name, driver in read]
        others = "".join(f"; of side {name} by {said}" for name, said in rest)
        return f"Values of side {first} read by {by}{others}."
    driver = read[0][1] if read else results.provenance.driver
    if driver is None or (driver.name is None and not driver.tool_versions):
        return None
    return f"Values read by {_read_by(driver)}."


@dataclass(frozen=True)
class MachineSummary(_Model):
    """The machine facts a results document may show. ``core_types`` are core-type keys."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    os: str
    arch: str
    cpu_model: str
    core_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class DriverInfo(_Model):
    """The driver that read the values, and the versions of the tool it wraps.

    ``name`` is the name of a built-in driver; a driver that a plug-in
    provides is not named. ``tool_versions`` holds each version the launches
    recorded, once, sorted.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: ShownDriver | None
    tool_versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Provenance(_Model):
    """Where the numbers came from, with nothing that identifies the machine, except that
    ``config_sha256`` can confirm a guessed path or host, as SECURITY.md says under Known
    limits of the hashes."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"driver"})

    machine: MachineSummary
    gpu: tuple[GpuInfo, ...] = ()
    engine: EngineInfo | None = None
    node_type: str | None = None
    seeds: Mapping[str, Any] = field(default_factory=dict)
    config_sha256: str | None = None
    driver: DriverInfo | None = None


@dataclass(frozen=True)
class ResultsSide(_Model):
    """A side as a results document shows it. ``image_ref`` is set only on request.

    ``identity`` holds only keys of ``PUBLIC_IDENTITY_KEYS``, and hashes where
    hashes belong: no path, no repository and no output of a command.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"image_ref", "control_of", "driver"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "twin_of": {"minLength": 1},
        "control_of": {"minLength": 1},
    }

    name: str
    kind: ShownKind
    role: Role
    twin_of: str | None
    control_of: str | None = field(default=None, kw_only=True)
    identity: Mapping[str, Any]
    fingerprint: str
    image_ref: str | None = None
    driver: DriverInfo | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if (self.role == "twin") != (self.twin_of is not None):
            raise ValueError("ResultsSide.twin_of: a twin, and only a twin, names twin_of")
        if (self.role == "control") != (self.control_of is not None):
            raise ValueError("ResultsSide.control_of: a control, and only a control, names it")
        unknown = sorted(set(self.identity) - set(PUBLIC_IDENTITY_KEYS))
        if unknown:
            raise ValueError(
                f"ResultsSide.identity: a results document may not show {', '.join(unknown)}"
            )
        for key, value in self.identity.items():
            where = f"ResultsSide.identity.{key}"
            if key in PUBLIC_IDENTITY_TEXT_KEYS:
                if not isinstance(value, str):
                    raise _wrong(where, "text", value)
            elif key in PUBLIC_IDENTITY_LIST_KEYS:
                if not isinstance(value, tuple) or any(_not_a_hash(v) for v in value):
                    raise _wrong(where, "a list of hashes", value)
            elif _not_a_hash(value):
                raise _wrong(where, "a hash", value)


@dataclass(frozen=True)
class PlanSummary(_Model):
    """The plan as it was run.

    ``launches`` counts the warm-up launches and the launches of every
    round, one per round for the positive control. ``explain_launches``
    counts the explain launches the run planned, on their own.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"explain_launches"})

    schedule: str | None
    rounds_requested: int | None
    rounds_planned: int
    rounds_completed: int
    warmups: int
    launches: int
    explain_launches: int = 0


@dataclass(frozen=True)
class GateSummary(_Model):
    """One machine check as a results document shows it.

    ``name`` is the name of a built-in check, or ``plugin``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: ShownGate
    mode: GateMode
    status: GateStatus


@dataclass(frozen=True)
class Degraded(_Model):
    """A check that failed, was degraded or could not run, with a one-line reason.

    ``name`` is the name of a built-in check, or ``plugin``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: ShownGate
    status: GateStatus
    message: str


@dataclass(frozen=True)
class MachineState(_Model):
    """The state of the machine during the run.

    ``undecided_launches`` counts the launches the busy-core witness could
    not judge, because the side reports no CPU time of its own and the count
    with its own load in was above the threshold. Such launches keep their
    round.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"discard_sha256", "undecided_launches"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"undecided_launches": {"minimum": 0}}

    status: MachineStatus
    gates: tuple[GateSummary, ...] = ()
    degraded: tuple[Degraded, ...] = ()
    discard_sha256: str | None = None
    undecided_launches: int = 0


@dataclass(frozen=True)
class Floor(_Model):
    """One side's noise floor. ``n`` is the number of rounds it was computed from.

    ``outlier_rounds`` names the rounds outside the Tukey fences. Where
    several captures are pooled, rounds are numbered across the captures in
    the order the captures were given.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    value: float
    n: int | None = None
    provisional: bool = False
    spread: float | None = None
    outlier_rounds: tuple[int, ...] = ()


@dataclass(frozen=True)
class FloorPair(_Model):
    """The floors of a comparison, where they came from and the unit they are in.

    ``unit`` is ``fraction`` under a rule of scale ``ratio`` and ``percent``
    under a rule of scale ``percent``. It is the unit of both floors and of
    the comparison's ``bar`` and ``gap``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"unit"})

    source: FloorSource
    unit: FloorUnit = field(default="fraction", kw_only=True)
    subject: Floor | None = None
    baseline: Floor | None = None
    mode: FloorMode = "NONE"


@dataclass(frozen=True)
class Sensitivity(_Model):
    """The comparison repeated without the disturbed rounds.

    ``not_computed`` says why there is no repeat; the other fields are then unset.
    Where several captures are pooled, ``rounds_set_aside`` numbers the rounds
    across the captures in the order the captures were given.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"not_computed"})

    rounds_set_aside: tuple[int, ...] = ()
    ratio: float | None = None
    outcome: Outcome | None = None
    agrees: bool | None = None
    not_computed: NotComputed | None = None


@dataclass(frozen=True)
class Comparison(_Model):
    """One case compared between a subject and the baseline.

    ``ratio`` is the median of the per-round ratios of subject over baseline,
    under every scale. ``statistic`` is the signed value the rule graded: the
    median of the per-round ratios under scale ``ratio``, the median of the
    per-round percent differences under scale ``percent``. ``scale`` is the
    rule's scale. ``gap`` is the absolute distance the rule compared with
    ``bar``; both are in the unit ``floor.unit`` names.

    ``reason`` is the single main reason; ``reasons`` holds every reason that
    applies. ``p_raw_fraction`` is the p-value as an exact fraction.
    ``order_split`` counts how often the subject and the baseline ran first.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"reasons", "scale", "statistic"})

    case: str
    primary: bool
    subject: str
    baseline: str
    n_rounds: int
    n_unpaired: int
    n_untied: int
    n_lower: int
    n_higher: int
    subject_median: float | None
    baseline_median: float | None
    ratio: float | None
    statistic: float | None = field(default=None, kw_only=True)
    scale: Scale = field(default="ratio", kw_only=True)
    gap: float | None
    floor: FloorPair
    bar: float | None
    p_raw: float | None
    p_raw_fraction: tuple[int, int] | None
    p_corrected: float | None
    verdict: Verdict
    outcome: Outcome
    reason: Reason | None
    reasons: tuple[Reason, ...] = field(default=(), kw_only=True)
    order_split: tuple[int, int]
    sensitivity: Sensitivity = field(default_factory=Sensitivity)


REASON_TOO_FAR_APART: Final = "too_far_apart"


RatioFault = Literal["large", "zero", "inverse", "percent"]
# What each fault of a ratio leaves out, in the words "too far apart for ...".
_RATIO_FAULT_WORDS: Final[Mapping[str, str]] = {
    "large": "their ratio to be a finite number",
    "zero": "their ratio to be told from zero",
    "inverse": "the inverse of their ratio to be a finite number",
    "percent": "their difference in percent to be a finite number",
}


def ratio_fault(ratio: float) -> RatioFault | None:
    """Say which figure made from a ratio of two positive values is unusable, or ``None``.

    ``large``: the ratio is no finite number. ``zero``: it is too small for a
    float, so it reads zero. ``inverse``: its inverse, the speed-up where
    lower is better, is no finite number. ``percent``: its difference in
    percent, ``100 * (ratio - 1)``, is no finite number.
    """
    if not math.isfinite(ratio):
        return "large"
    if ratio <= 0:
        return "zero"
    if not math.isfinite(1.0 / ratio):
        return "inverse"
    if not math.isfinite(100.0 * (ratio - 1.0)):
        return "percent"
    return None


def too_far_apart_words(comparison: Comparison) -> str:
    """Say in plain words why a comparison has the reason ``too_far_apart``.

    When the comparison's own ratio, or the percent difference its rule
    grades, is unusable, the words name the two medians and the figure of
    their ratio that is unusable (``ratio_fault``): the ratio itself, its
    inverse or its difference in percent is no finite number, or the ratio
    cannot be told from zero. Otherwise the floors are what overflowed: a
    floor made from a side and its twin, a floor the caller supplied, or
    the bar the two floors add up to.
    """
    s, b = comparison.subject_median, comparison.baseline_median
    # A comparison with no pair, or with a value of zero or less, has no ratio
    # for its own reasons; only the floors can have overflowed.
    measured = comparison.n_rounds > 0 and "nonpositive_value" not in comparison.reasons
    if measured and (comparison.ratio is None or comparison.statistic is None):
        if comparison.ratio is not None:
            what = "their percent difference to be a finite number"
        else:
            positive = s is not None and b is not None and s > 0 and b > 0
            fault = ratio_fault(s / b) if positive and s is not None and b is not None else None
            if fault is None:
                return (
                    "the values are too far apart for their ratio, its inverse and its "
                    "difference in percent all to be finite numbers"
                )
            what = _RATIO_FAULT_WORDS[fault]
        if s is None or b is None:
            return f"the values are too far apart for {what}"
        return f"the medians {s:.3g} and {b:.3g} are too far apart for {what}"
    floors = comparison.floor
    if floors.subject is not None and floors.baseline is not None:
        return "the noise floors are too large for the bar made from them to be a finite number"
    if floors.source == "supplied":
        return "a supplied noise floor is too large to be a finite number as a percentage"
    return "a side and its twin are too far apart for the noise floor to be a finite number"


@dataclass(frozen=True)
class SameVsSame(_Model):
    """A side compared with its own twin on one case.

    ``floor`` is in the unit ``unit`` names: ``fraction`` under a rule of
    scale ``ratio``, ``percent`` under a rule of scale ``percent``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"unit"})

    side: str
    case: str
    ratio: float | None
    floor: float | None
    p_raw: float | None
    n: int
    unit: FloorUnit = "fraction"


@dataclass(frozen=True)
class TwinCheck(_Model):
    """A side compared with its own twin over its primary cases combined.

    In each round the side's score is the median over the primary cases on
    which the side and its twin both have a finite value above zero: each
    gives the log of the side's value over its twin's, turned so that a
    positive score means the side looks better by the case's better
    direction. An odd number of cases gives the log in the middle and an even
    number the mean of the two in the middle, so one case gives its own log
    and two give their mean. ``n_rounds`` counts the rounds scored,
    ``n_better`` and ``n_worse`` the rounds whose score lies above and below
    zero; a score of zero is a tie. ``p_raw`` is the exact sign test of those
    rounds, ``None`` when at most one round was scored. ``p_corrected`` is
    ``p_raw`` corrected with Holm's method across the sides of the run that
    have one, and ``None`` where ``p_raw`` is; the note ``twin_differs`` is
    given for a side whose ``p_corrected`` lies below 0.05.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "n_rounds": {"minimum": 0},
        "n_better": {"minimum": 0},
        "n_worse": {"minimum": 0},
    }

    side: str
    n_rounds: int
    n_better: int
    n_worse: int
    p_raw: float | None
    p_corrected: float | None


@dataclass(frozen=True)
class RefusalEntry(_Model):
    """A refusal as a results document lists it."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"code": {"pattern": "^E_[A-Z0-9_]+$"}}

    code: str
    scope: RefusalScope
    message: str

    @classmethod
    def of(cls, refusal: Refusal) -> RefusalEntry:
        """Build the entry for a raised refusal.

        An absolute path in the message is cut to its last part.
        """
        return cls(code=refusal.code, scope=refusal.scope, message=public_text(refusal.message))


@dataclass(frozen=True)
class PluginCounts(_Model):
    """How many third-party plug-ins loaded and how many plug-ins failed to load."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    loaded: int = 0
    failed: int = 0


@dataclass(frozen=True)
class Figure(_Model):
    """One figure: its value and its text. Rounding happens only in the text."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    value: float | int | str
    text: str


@dataclass(frozen=True)
class Artifacts(_Model):
    """The files of the run folder, as names relative to it.

    ``html`` is the report page and ``diagnostics`` the diagnostics
    document. ``charts`` lists the chart files and ``profiles`` the folded
    stacks, the difference files, the flame graphs and what a profiler
    wrote. A results document lists these files by name and never holds
    what is in them. A name that starts at the root or at the home folder,
    or that leaves the run folder, is refused: it would show where on a
    machine the run was made.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"html", "diagnostics", "charts"})

    capture: str | None = None
    markdown: str | None = None
    plan: str | None = None
    html: str | None = None
    diagnostics: str | None = None
    charts: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        single = (self.capture, self.markdown, self.plan, self.html, self.diagnostics)
        for name in (*single, *self.charts, *self.profiles):
            if name is not None and (not name or re.search(OUTSIDE_RUN_FOLDER, name)):
                raise ValueError(
                    "Artifacts: a file is named relative to the run folder, "
                    "by no path from the root or the home folder and none that leaves it"
                )


@dataclass(frozen=True)
class EnergyInfo(_Model):
    """What the energy cases cover and what they leave out."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    scope: str = ENERGY_SCOPE
    excludes: tuple[str, ...] = ENERGY_EXCLUDES


@dataclass(frozen=True)
class ControlCase(_Model):
    """What the positive control read on one primary case.

    ``expected`` is the median ratio twice the work must read: 2.0 where
    lower is better, 0.5 where higher is better. ``ratio`` is the measured
    median ratio of the control against the baseline, ``p_raw`` the
    uncorrected sign-test p-value of its direction and ``n_rounds`` the
    number of paired rounds. ``passed`` says the ratio lies within the
    tolerance and the direction is significant.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"n_rounds": {"minimum": 0}}

    case: str
    expected: float
    ratio: float | None
    p_raw: float | None
    n_rounds: int
    passed: bool


@dataclass(frozen=True)
class PositiveControl(_Model):
    """The state of the positive control of a run.

    ``status`` is ``ok`` when every primary case passed, ``failed`` when at
    least one did not, and ``not_run`` when the control was off, the capture
    has no control entry, the side cannot run its command twice in one
    start, or no primary case has enough paired rounds to be judged.
    ``entry`` names the control entry, or is ``None`` when there is none.
    ``via`` says how the control doubled the work and ``tolerance`` how far
    it may read from its expected value, as a fraction of it. ``cases``
    holds one row per primary case that was judged. A control that is ``ok``
    names its entry and lists at least one case, every one of them passed;
    one that is ``failed`` names its entry and lists a case that did not
    pass.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "entry": {"minLength": 1},
        "tolerance": {"minimum": 0, "exclusiveMaximum": CONTROL_TOLERANCE_BELOW},
    }

    status: ControlStatus = "not_run"
    entry: str | None = None
    via: ControlVia = "repeat"
    tolerance: float = 0.10
    cases: tuple[ControlCase, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.status == "not_run":
            return
        if self.entry is None:
            raise ValueError(
                f"PositiveControl.entry: a control that is {self.status} names its entry"
            )
        passed = [row.passed for row in self.cases]
        if self.status == "ok" and not (passed and all(passed)):
            raise ValueError(
                "PositiveControl.cases: a control is ok when every case it lists passed"
            )
        if self.status == "failed" and all(passed):
            raise ValueError(
                "PositiveControl.cases: a failed control lists a case that did not pass"
            )


@dataclass(frozen=True)
class Controls(_Model):
    """The controls of a run. Twins are the negative control; this holds the positive one."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    positive: PositiveControl = field(default_factory=PositiveControl)


@dataclass(frozen=True)
class EnvPad(_Model):
    """Whether the size of the environment was varied from round to round.

    ``min`` and ``max`` are the ends of the range the pad lengths were drawn
    from, in bytes; both are unset when the size was not varied.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"min", "max"})
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {
        "min": {"minimum": 0, "maximum": ENV_PAD_MAX},
        "max": {"minimum": 0, "maximum": ENV_PAD_MAX},
    }

    varied: bool = False
    min: int | None = None
    max: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if (self.min is not None) != self.varied or (self.max is not None) != self.varied:
            raise ValueError(
                "EnvPad: min and max are given when the size was varied, and only then"
            )

    @classmethod
    def of(cls, varied: bool) -> EnvPad:
        """Return the record of a run that varied the size, or of one that did not."""
        return cls(varied=True, min=0, max=ENV_PAD_MAX) if varied else cls()


@dataclass(frozen=True)
class Series(_Model):
    """The values of one primary case on one lineup entry, round by round.

    ``values[i]`` belongs to round ``i + 1``; a round without a value holds
    ``None``. ``disturbed_rounds`` names the rounds set aside as disturbed.
    Only primary cases have series, and the positive control has none: it
    is no lineup entry.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    case: str
    name: str
    values: tuple[float | None, ...] = ()
    disturbed_rounds: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if any(round < 1 for round in self.disturbed_rounds):
            raise ValueError("Series.disturbed_rounds: rounds are numbered from 1")


@dataclass(frozen=True)
class PlotsState(_Model):
    """Whether the charts of a run were drawn.

    ``pending`` in the first write of the results, then ``drawn``,
    ``not_drawn`` with the reason ``extra_missing`` or ``failed``, ``off``,
    or ``interrupted``. A reason is given only with ``not_drawn``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    status: PlotsStatus = "off"
    reason: PlotsReason | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.reason is not None and self.status != "not_drawn":
            raise ValueError("PlotsState.reason: a reason is given only with not_drawn")


@dataclass(frozen=True)
class DiagnosticsState(_Model):
    """The state of the explain step of a run.

    ``pending`` in the first write of the results, then ``written``,
    ``skipped`` with the reason ``mode_auto_no_difference``, ``lock`` or
    ``no_instrument``, ``off``, ``failed`` or ``interrupted``. A reason is
    given with ``skipped`` and only with it.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    status: DiagnosticsStatus = "off"
    reason: DiagnosticsReason | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if (self.reason is not None) != (self.status == "skipped"):
            raise ValueError(
                "DiagnosticsState.reason: a reason is given with skipped and only with it"
            )


@dataclass(frozen=True)
class Results(_Model):
    """The analysed output of one or more captures.

    ``schema`` is the schema id; a document that names another one is refused.

    A results document is meant to be shared. It holds the comparisons of
    the resource cases, the state of the explain step and of the charts, and
    the names of the files a run wrote. It has no field for a function name,
    a shared-object name or a call stack: those are held by the diagnostics
    document, the files under ``profiles/`` and the report page alone.

    ``launch_cost`` is ``None``, and its key absent from the written
    document, when no cost of a launch was measured. ``twin_checks`` holds
    one combined check per side that has a twin; a document written without
    it reads as holding none.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset(
        {
            "energy",
            "controls",
            "launch_cost",
            "env_pad",
            "series",
            "plots",
            "diagnostics",
            "twin_checks",
        }
    )

    tool: Tool
    run: RunInfo
    rule: RuleInfo
    provenance: Provenance
    sides: tuple[ResultsSide, ...]
    plan: PlanSummary
    machine_state: MachineState
    cases: tuple[Case, ...] = ()
    comparisons: tuple[Comparison, ...] = ()
    same_vs_same: tuple[SameVsSame, ...] = ()
    twin_checks: tuple[TwinCheck, ...] = ()
    controls: Controls = field(default_factory=Controls)
    launch_cost: LaunchCost | None = None
    env_pad: EnvPad = field(default_factory=EnvPad)
    series: tuple[Series, ...] = ()
    plots: PlotsState = field(default_factory=PlotsState)
    diagnostics: DiagnosticsState = field(default_factory=DiagnosticsState)
    refusals: tuple[RefusalEntry, ...] = ()
    notes: tuple[Note, ...] = ()
    plugins: PluginCounts = field(default_factory=PluginCounts)
    figures: Mapping[str, Figure] = field(default_factory=dict)
    artifacts: Artifacts = field(default_factory=Artifacts)
    energy: EnergyInfo | None = None
    schema: Literal["pairbench/results/v1"] = SCHEMA_RESULTS

    def to_json(self) -> dict[str, Any]:
        """Return the results document as a plain dict, ``schema`` first.

        ``energy`` is present only when power was sampled, and
        ``launch_cost`` only when the cost of a launch was measured. In a
        results document the cost carries no record type.
        """
        body = super().to_json()
        for key in ("energy", "launch_cost"):
            if body[key] is None:
                del body[key]
        return {"schema": body.pop("schema"), **body}

    def has_difference(self) -> bool:
        """Say whether a primary case came out ``better`` or ``worse``.

        The explain step runs under mode ``auto`` only when one did.
        """
        return any(c.primary and c.outcome in ("better", "worse") for c in self.comparisons)

    def pending(self) -> Results:
        """Return the document of the first write of a run.

        The explain step and the charts have not run yet: both say
        ``pending``. Everything else is as analysed.
        """
        return dataclasses.replace(
            self,
            diagnostics=DiagnosticsState(status="pending"),
            plots=PlotsState(status="pending"),
        )

    def finished(
        self,
        *,
        diagnostics: DiagnosticsState,
        plots: PlotsState,
        notes: Sequence[Note] = (),
        artifacts: Artifacts | None = None,
    ) -> Results:
        """Return the document of the second write of a run.

        It holds the final state of the explain step and of the charts, the
        notes those two steps added, laid after the notes already there, and
        the final list of files. Nothing else differs from the first write.
        Each added note is shown as every note of a results document is:
        absolute paths in its message are cut to their last part.
        """
        return dataclasses.replace(
            self,
            diagnostics=diagnostics,
            plots=plots,
            notes=(*self.notes, *(note.for_results() for note in notes)),
            artifacts=self.artifacts if artifacts is None else artifacts,
        )

    def interrupted(self) -> Results:
        """Return the document of a run that was interrupted after its first write.

        A state of the explain step or of the charts that still says
        ``pending`` says ``interrupted``. A state that was already final,
        and everything else, stays as it is.
        """
        diagnostics, plots = self.diagnostics, self.plots
        if diagnostics.status == "pending":
            diagnostics = DiagnosticsState(status="interrupted")
        if plots.status == "pending":
            plots = PlotsState(status="interrupted")
        return dataclasses.replace(self, diagnostics=diagnostics, plots=plots)

    def comparison(self, case: str, subject: str | None = None) -> Comparison:
        """Return the comparison of a case, for one subject when there are several."""
        found = [c for c in self.comparisons if c.case == case and subject in (None, c.subject)]
        if len(found) != 1:
            raise KeyError((case, subject))
        return found[0]


# The keys of a results document that may differ between the two writes of a
# run: the first before the explain step and the charts, the second after.
SECOND_WRITE_KEYS: Final[tuple[str, ...]] = ("diagnostics", "plots", "artifacts", "notes")


def second_write_changes(first: Results, second: Results) -> tuple[str, ...]:
    """Name what the second write of a run changed that it may not change.

    Only the keys of ``SECOND_WRITE_KEYS`` may differ, and the notes of the
    first write stay where they are: the second write adds notes after them.
    An empty answer says the second write kept the rule. A key that differs
    is named; ``notes`` is named when a note of the first write is missing
    or was moved.
    """
    before, after = first.to_json(), second.to_json()
    changed = [
        key
        for key in sorted(set(before) | set(after))
        if key not in SECOND_WRITE_KEYS and before.get(key) != after.get(key)
    ]
    if second.notes[: len(first.notes)] != first.notes:
        changed.append("notes")
    return tuple(changed)


# ---------------------------------------------------------------------------
# The diagnostics document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticsRun(_Model):
    """The run a diagnostics document belongs to: the id its results carry."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    id: str


@dataclass(frozen=True)
class InstrumentRun(_Model):
    """One instrument on one side: whether it ran, and why not when it did not.

    ``status`` is ``ok``, ``skipped`` or ``failed``. ``reason`` is set unless
    the status is ``ok``: the program is not installed, the system does not
    permit it, the image does not hold the program, the container has no
    capability to use performance counters, the launcher cannot start the
    server under the instrument, the side's identity changed, a lock could
    not be taken, the launch failed, or the side's interpreter is older than
    the sampler runs on. ``rc`` is the exit code of the launch, or ``None``
    when nothing was launched.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    name: InstrumentName
    side: str
    status: InstrumentStatus
    reason: InstrumentReason | None = None
    rc: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if (self.reason is None) != (self.status == "ok"):
            raise ValueError(
                "InstrumentRun.reason: a reason is given unless the instrument ran, and only then"
            )

    def note(self) -> Note | None:
        """Return the loud note of an instrument that did not run, or ``None`` for one that ran.

        The note names the instrument, the side and the reason in words. It
        holds no name from the user's code, so a results document may show it.
        """
        if self.reason is None:
            return None
        words = INSTRUMENT_REASON_WORDS[self.reason]
        return Note(
            code=NOTE_INSTRUMENT_SKIPPED,
            message=f"instrument {self.name} did not run for side {self.side}: {words}",
        )


@dataclass(frozen=True)
class ResourceRow(_Model):
    """One resource case of a subject against the baseline: the medians and the outcome."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    case: str
    subject: str
    baseline: str
    subject_median: float | None
    baseline_median: float | None
    outcome: Outcome


@dataclass(frozen=True)
class CounterRow(_Model):
    """One counted event of a subject against the baseline.

    ``ratio`` is the subject's count over the baseline's, or ``None`` where
    one of them is missing or the baseline's is zero.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    event: str
    subject: str
    baseline: str
    subject_value: float | None
    baseline_value: float | None
    ratio: float | None


@dataclass(frozen=True)
class TopFunction(_Model):
    """A function with its share of the samples of one side.

    A sample belongs to its innermost frame. ``object`` is the shared object
    that holds the function, or ``None`` where the instrument gives none.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"share": {"minimum": 0, "maximum": 1}}

    name: str
    object: str | None
    share: float


@dataclass(frozen=True)
class TopObject(_Model):
    """A shared object with its share of the samples of one side."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"share": {"minimum": 0, "maximum": 1}}

    name: str
    share: float


@dataclass(frozen=True)
class StackSummary(_Model):
    """The sampled stacks of one side: which instrument took them, and where samples fell.

    ``instrument`` is ``stacks`` or ``pystacks``. A difference file and a
    difference graph of a subject against the baseline are made only when
    both summaries name the same instrument. ``pystacks`` gives Python
    frames only and no shared objects.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"samples": {"minimum": 0}}

    side: str
    instrument: StackInstrument
    samples: int
    top_functions: tuple[TopFunction, ...] = ()
    top_objects: tuple[TopObject, ...] = ()


@dataclass(frozen=True)
class ObjectDiff(_Model):
    """The shared objects the sides loaded, compared.

    ``only_in`` maps a side name to the objects only that side loaded.
    ``differ`` lists the objects that have the same name on both sides and a
    different build id: each entry holds ``name`` and, under each side's
    name, that side's build id.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    only_in: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    differ: tuple[Mapping[str, str], ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if any("name" not in entry for entry in self.differ):
            raise ValueError("ObjectDiff.differ: every entry names its object under 'name'")


@dataclass(frozen=True)
class Finding(_Model):
    """A sentence about how two sides differ, with the numbers it was made from.

    The text is produced by code from a fixed template. It describes and
    never names a cause: it uses none of ``FINDING_FORBIDDEN_WORDS``.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()
    LIMITS: ClassVar[Mapping[str, Mapping[str, Any]]] = {"text": {"minLength": 1}}

    id: FindingId
    text: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        used = forbidden_words(self.text)
        if used:
            raise ValueError(f"Finding.text: a finding never says {', '.join(used)}")


@dataclass(frozen=True)
class DiagnosticsFiles(_Model):
    """The files the explain step wrote, as names relative to the run folder."""

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset()

    folded: tuple[str, ...] = ()
    folded_diff: tuple[str, ...] = ()
    flame: tuple[str, ...] = ()
    flame_diff: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostics(_Model):
    """What the resource figures, the counters and the sampled stacks say about two sides.

    The document describes. It states no cause, changes no verdict and no
    exit code. ``holds_names`` says the document holds names from the
    user's code: function names, shared-object names and stacks live here,
    in the files under ``profiles/`` and in the report page, and never in a
    results document. ``name_map`` maps the real name of a case or a side to
    the name it has in a file name. ``schema`` is the schema id; a document
    that names another one is refused.

    ``notes`` are the loud notes of the explain step: an instrument that
    did not run, stacks of a subject and of the baseline that come from
    different instruments. They are printed on standard error and copied
    into the results of the run, so they name sides and instruments and
    hold no name from the user's code.
    """

    OPTIONAL: ClassVar[frozenset[str] | None] = frozenset({"notes"})

    run: DiagnosticsRun
    holds_names: bool = True
    instruments: tuple[InstrumentRun, ...] = ()
    resources: tuple[ResourceRow, ...] = ()
    counters: tuple[CounterRow, ...] = ()
    stacks: tuple[StackSummary, ...] = ()
    objects: ObjectDiff = field(default_factory=ObjectDiff)
    findings: tuple[Finding, ...] = ()
    files: DiagnosticsFiles = field(default_factory=DiagnosticsFiles)
    name_map: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[Note, ...] = ()
    schema: Literal["pairbench/diagnostics/v1"] = SCHEMA_DIAGNOSTICS

    def to_json(self) -> dict[str, Any]:
        """Return the diagnostics document as a plain dict, ``schema`` first."""
        body = super().to_json()
        return {"schema": body.pop("schema"), **body}

    def state(self) -> DiagnosticsState:
        """Return the state of the explain step that wrote this document.

        ``written`` when at least one instrument ran on a side. Otherwise the
        step is ``skipped``: with the reason ``lock`` when every instrument
        was skipped for a lock that could not be taken, and with
        ``no_instrument`` when no instrument could run on any side.
        """
        if any(row.status == "ok" for row in self.instruments):
            return DiagnosticsState(status="written")
        if self.instruments and all(row.reason == "lock" for row in self.instruments):
            return DiagnosticsState(status="skipped", reason="lock")
        return DiagnosticsState(status="skipped", reason="no_instrument")

    def stacks_of(self, side: str) -> StackSummary | None:
        """Return the stack summary of a side, or ``None`` when it has none."""
        return next((s for s in self.stacks if s.side == side), None)

    def same_instrument(self, subject: str, baseline: str) -> bool:
        """Say whether the stacks of a subject and of the baseline come from one instrument.

        Only then is a difference file or a difference graph made.
        """
        a, b = self.stacks_of(subject), self.stacks_of(baseline)
        return a is not None and b is not None and a.instrument == b.instrument

    def shareable_findings(self) -> tuple[Finding, ...]:
        """Return the findings made from resource figures and counters alone.

        They hold no function name and no shared-object name, so a report
        that may show no such name shows these.
        """
        return tuple(f for f in self.findings if f.id in FINDINGS_WITHOUT_NAMES)


__all__ = [
    "BETTER",
    "BUILTIN_DRIVERS",
    "BUILTIN_GATES",
    "BUILTIN_KINDS",
    "CALL_GRAPHS",
    "CASE_KEY_BYTES",
    "CASE_SUFFIX_HEX",
    "CHARTS",
    "CLOCK_REASONS_NOT_COUNTED",
    "CONFIG_KEYS",
    "CONFIG_TABLE_KEYS",
    "CONTROL_EXPECTED",
    "CONTROL_MODES",
    "CONTROL_STATUSES",
    "CONTROL_SUFFIX",
    "CONTROL_TOLERANCE_BELOW",
    "CONTROL_VIAS",
    "COUNTER_EVENTS",
    "CPU_LIST_PATTERN",
    "DIAGNOSTICS_REASONS",
    "DIAGNOSTICS_STATUSES",
    "EMPTY_COMMAND",
    "ENV_PAD_MAX",
    "EXPLAIN_LAUNCHES_PER_SIDE",
    "EXPLAIN_MODES",
    "FIGURE_NAMES",
    "FINDINGS_WITHOUT_NAMES",
    "FINDING_FORBIDDEN_WORDS",
    "FINDING_IDS",
    "FLAGS_WITHOUT_KEY",
    "FLAG_KEYS",
    "FLOOR_UNITS",
    "HASH_PATTERN",
    "HIDDEN",
    "IDENTIFY_OUTPUT_KEY",
    "IMAGE_COMMAND_PROGRAM_KEY",
    "IMAGE_ENTRYPOINT_KEY",
    "INSTRUMENTS",
    "INSTRUMENT_REASONS",
    "INSTRUMENT_REASON_WORDS",
    "INSTRUMENT_STATUSES",
    "LAUNCH_COST_KINDS",
    "LEVEL_KINDS",
    "LIMIT_WORDS",
    "MAX_CPU",
    "OUTCOMES",
    "OUTCOMES_DESCRIBED",
    "OUTCOMES_JUDGED",
    "OUTSIDE_RUN_FOLDER",
    "PLOTS_REASONS",
    "PLOTS_STATUSES",
    "PLOT_MODES",
    "PLUGIN_NAME",
    "PUBLIC_IDENTITY_KEYS",
    "PUBLIC_IDENTITY_LIST_KEYS",
    "PUBLIC_IDENTITY_TEXT_KEYS",
    "PYSAMPLER_MIN_PYTHON",
    "P_SMALLEST_WRITTEN",
    "REASONS",
    "REASONS_NO_VERDICT",
    "REASONS_RESERVED",
    "REASONS_UNRESOLVED",
    "REASON_TOO_FAR_APART",
    "RESERVED_CASE_PREFIXES",
    "RESOURCE_CASES",
    "RES_PREFIX",
    "SCALES",
    "SCHEDULE",
    "SCHEMA_CAPTURE",
    "SCHEMA_CONFIG",
    "SCHEMA_DIAGNOSTICS",
    "SCHEMA_RESULTS",
    "SECOND_WRITE_KEYS",
    "SHOWN_GATES",
    "SHOWN_KINDS",
    "SIDE_NAME_PATTERN",
    "STACK_INSTRUMENTS",
    "STARTUP_PREFIX",
    "STRICT",
    "TIME_UNITS",
    "TOOL_NAME",
    "TOOL_VERSION",
    "TWIN_SUFFIX",
    "VERDICTS",
    "WITNESSES",
    "WITNESSES_BUSY_CORES",
    "WITNESSES_WITH_THRESHOLD",
    "Artifacts",
    "Capture",
    "CaptureRef",
    "Case",
    "CaseKeyRecord",
    "CaseName",
    "CaseNamesRecord",
    "CaseSettings",
    "CasesRecord",
    "CensusSettings",
    "Comparison",
    "ControlCase",
    "ControlSettings",
    "Controls",
    "CounterRow",
    "CpuGroup",
    "CpuRecord",
    "Degraded",
    "Diagnostics",
    "DiagnosticsFiles",
    "DiagnosticsRun",
    "DiagnosticsState",
    "DiscardThresholds",
    "DriverInfo",
    "End",
    "EnergyInfo",
    "EnergySettings",
    "EngineInfo",
    "EnvPad",
    "Experiment",
    "ExplainSettings",
    "Figure",
    "Finding",
    "Floor",
    "FloorPair",
    "Floors",
    "GateRecord",
    "GateSettings",
    "GateSummary",
    "GpuInfo",
    "Header",
    "InstrumentRun",
    "Launch",
    "LaunchCost",
    "LaunchCostSettings",
    "LaunchSettings",
    "Lineup",
    "LoadSettings",
    "MachineRecord",
    "MachineState",
    "MachineSummary",
    "Note",
    "ObjectDiff",
    "Observation",
    "PairBalance",
    "Plan",
    "PlanRow",
    "PlanSummary",
    "PlotSettings",
    "PlotsState",
    "PluginCounts",
    "PositiveControl",
    "Probe",
    "Provenance",
    "QuietSettings",
    "RatioFault",
    "ReaderInfo",
    "Ready",
    "RefusalEntry",
    "ReportSettings",
    "ResourceRow",
    "Results",
    "ResultsSide",
    "RoundWitness",
    "Rule",
    "RuleInfo",
    "RuleSettings",
    "RunInfo",
    "RunSettings",
    "SameVsSame",
    "Sensitivity",
    "Series",
    "ServeSpec",
    "SetAside",
    "Side",
    "Source",
    "StackSummary",
    "Tool",
    "TopFunction",
    "TopObject",
    "TwinCheck",
    "Witness",
    "canonical_json",
    "case_folder_word",
    "case_has_suffix",
    "case_id",
    "case_marked_name",
    "case_matches",
    "case_percent_paths",
    "case_suffix",
    "case_tell_words",
    "case_text_sha256",
    "case_unsuffixed",
    "chart_file",
    "clock_events",
    "combine_control",
    "combine_hashes",
    "compared_pairs",
    "config_inputs",
    "config_sha256",
    "control_expected",
    "control_within",
    "count_balance",
    "direction_outcome",
    "driver_text",
    "env_pad_length",
    "exceeded",
    "family_words",
    "figure_key",
    "file_names",
    "fingerprint_inputs",
    "fingerprint_of",
    "flame_diff_file",
    "flame_file",
    "folded_diff_file",
    "folded_file",
    "forbidden_words",
    "grades_raw_p",
    "hashed_argv",
    "hashed_output",
    "hidden_difference",
    "is_reserved_case",
    "kind_of_unit",
    "launch_cost_note",
    "launch_cost_side",
    "level_label",
    "looks_like_credential",
    "match_config_key",
    "median_key",
    "min_rounds",
    "name_words",
    "outcomes_of",
    "p_equation",
    "p_written",
    "parse_duration",
    "plan_rows",
    "planned_explain_launches",
    "planned_launches",
    "points_outside",
    "public_case",
    "public_case_drops",
    "public_command",
    "public_path",
    "public_text",
    "quantile",
    "ratio_fault",
    "raw_p_note",
    "record_from_json",
    "recorded_workload",
    "redact_argv",
    "redact_env",
    "required_keys",
    "resource_case",
    "rotate_reverse",
    "round_numbers",
    "safe_file_name",
    "second_write_changes",
    "set_aside",
    "sha256_hex",
    "side_setup",
    "starts_with_python",
    "too_far_apart_words",
    "trapezoid",
    "undecided",
    "validate_side_name",
    "verdict_word",
    "workload_difference",
]
