# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The tool server for AI agents: ``pairbench mcp``, over standard input and output.

The server needs the ``mcp`` extra (the official MCP Python SDK). It is a
thin shell over the public functions of ``pairbench``: every tool calls
what the command line calls and answers with one JSON document.

Tools:

* ``doctor``: what this machine supports.
* ``plan``: the plan of an experiment; launches nothing.
* ``run_start``, ``run_status``, ``run_cancel``: start a run and return a
  handle at once, follow it, cancel it. ``run_start`` and ``run_cancel``
  are offered only when the server was started with ``--allow-run``,
  because a run launches commands on the machine; without it they are
  left out of the tool list, and a call reads a refusal that says how to
  start the server with it. A run is the ``pairbench run``
  command in a child process: a cancel is an interrupt, exactly as Ctrl-C
  is for the command, and nothing a run prints reaches the protocol stream.
* ``results``: a results document, or the comparisons of one case, or of every case that a
  name given without its mark shows with one.
* ``diagnostics``: a diagnostics document, or its findings.
* ``compare``: analyse existing captures or result files of other tools.
* ``explain``: one comparison, or one term, in plain words.
* ``fill``: fill the figure tokens of a document.
* ``selftest``: the known answers and the controls of the statistics.
* ``schema``: one JSON Schema.

A refusal is an answer, not a failure of the call: ``{"refusal": {"code",
"exit_code", "scope", "message", "docs"}}``, where ``docs`` is the address of the
code's entry in the documentation, with the results document of a refused
analysis beside it when there is one. No tool names a plug-in.
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import json
import re
import secrets
import signal
import subprocess
import sys
import threading
import types
from collections import deque
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pairbench.errors import (
    CODES,
    EXIT_INTERRUPTED,
    Refusal,
    docs_address,
    docs_line,
    unprintable,
)
from pairbench.mcp import library

if TYPE_CHECKING:
    from pairbench.model import Comparison, Experiment, Results

SERVER_NAME: Final = "pairbench"

INSTRUCTIONS: Final = (
    "pairbench says whether one side is really faster than another on a workload, or whether "
    "the difference is noise. The loop: doctor, plan, run_start (only with --allow-run), "
    "run_status until the run ends, results, then fill. Report a verdict with its noise bar "
    "and p-value, name the rule and the number of rounds, say UNRESOLVED or NO VERDICT as "
    "such, quote numbers from the results document and never type one by hand, and never "
    "change the rule after seeing results. Diagnostics hold names from the user's code: do "
    "not paste them into anything public unless asked to."
)

NAMES_NOTICE: Final = (
    "This document holds names from the user's code: functions, shared objects and stacks. "
    "Do not paste them into anything public unless the user asks for it."
)

# Every tool, in the order the tool server reference lists them.
TOOL_NAMES: Final[tuple[str, ...]] = (
    "doctor",
    "plan",
    "run_start",
    "run_status",
    "run_cancel",
    "results",
    "diagnostics",
    "compare",
    "explain",
    "fill",
    "selftest",
    "schema",
)
# The tools that launch commands on the machine; they are offered only with ``--allow-run``.
RUN_TOOLS: Final[frozenset[str]] = frozenset({"run_start", "run_cancel"})
# The answer to a call of a run tool on a server started without ``--allow-run``.
WITHOUT_ALLOW_RUN: Final = (
    "this server was started without --allow-run, so it does not offer {tool}: start it "
    "with pairbench mcp --allow-run"
)

# How many lines of a run's output a handle keeps.
KEPT_LINES: Final = 200
# The explain answer writes the exact p-value fraction only when its denominator is
# shorter than this; a longer one is left to p_raw_fraction in the results.
SHORT_FRACTION: Final = 10**16
# How long the server waits for a cancelled run to end when it stops.
STOP_WAIT_S: Final = 60.0
REFUSAL_LINE: Final = re.compile(r"^(E_[A-Z_]+): (.*)$")

# The words of each outcome, as a comparison records it.
OUTCOME_TEXT: Final[Mapping[str, str]] = {
    "better": "the subject is better than the baseline, outside the noise bar and significant",
    "worse": "the subject is worse than the baseline, outside the noise bar and significant",
    "higher": (
        "the subject's value is higher, outside the noise bar and significant; the case "
        "describes and does not judge"
    ),
    "lower": (
        "the subject's value is lower, outside the noise bar and significant; the case "
        "describes and does not judge"
    ),
    "tie": "the gap lies inside the noise bar and the direction is not significant",
    "unresolved": "the evidence does not support a win, a loss or a tie",
    "no_verdict": "the comparison cannot be graded",
}

# Why the comparison without the disturbed rounds was not computed.
NOT_COMPUTED_TEXT: Final[Mapping[str, str]] = {
    "too_few_rounds": "too few rounds would remain",
    "too_many_disturbed": "more than half of the rounds are disturbed",
}

# The words of each reason a comparison can carry.
REASON_TEXT: Final[Mapping[str, str]] = {
    "inside_noise": (
        "the direction is significant, but the gap lies inside the noise bar, so it cannot be "
        "told apart from the measured noise"
    ),
    "not_significant": (
        "the gap lies outside the noise bar, but the sign test does not find the direction "
        "significant at the rule's alpha"
    ),
    "order_unbalanced": (
        "within the pairs of this comparison one side ran first more than three times as "
        "often as the other"
    ),
    "sensitive_to_disturbed_rounds": (
        "the outcome changes when the rounds a witness marked as disturbed are set aside"
    ),
    "positive_control_failed": (
        "the positive control of the run failed: twice the work did not read as twice the "
        "value, so no difference the run reports can be trusted"
    ),
    "nonpositive_value": (
        "a value of zero or less was recorded for this case on a side or on its twin"
    ),
    "too_far_apart": (
        "the values are too far apart for a ratio this comparison needs to be a finite number: "
        "the ratio of the two sides, a noise floor from a side and its twin, or the bar the "
        "floors add up to"
    ),
    "single_measurement": "there is one pair only, and one pair gives no p-value",
    "order_not_recorded": "the order in which the values were produced is not known",
    "too_few_rounds": (
        "there are fewer paired rounds than the fewest that can give a verdict for this "
        "number of tests"
    ),
    "no_floor": "neither side has a twin, so no noise floor was measured",
    "one_sided_floor": "only one side has a twin, and the rule needs a floor on both",
    "zero_floor": "a noise floor is exactly zero, so the run gives no measure of its noise",
    "side_failed": "reserved for launchers added later: a side failed on its own account",
    "more_than_one_node": (
        "reserved for launchers added later: the sides did not all run on one node"
    ),
}

# Terms the ``explain`` tool knows, in plain words.
GLOSSARY: Final[Mapping[str, str]] = {
    "experiment": "One workload compared across two or more sides.",
    "side": (
        "One thing being compared: a container image, a command, a Python environment, a "
        "server image, or a set of result files."
    ),
    "baseline": (
        "The side every other side is compared against. Without --baseline it is the last "
        "side named."
    ),
    "subject": "A side compared against the baseline.",
    "twin": (
        "An identical copy of a side that runs in the same rounds. The gap between a side and "
        "its twin is the measured noise. A twin's name ends in ~same."
    ),
    "lineup": "The ordered list of sides and twins that run in each round.",
    "round": (
        "One launch of every entry of the lineup, in a planned order that rotates and "
        "reverses from round to round, so that no side keeps running before another."
    ),
    "launch": "One start-to-finish execution of one lineup entry.",
    "case": (
        "One named measurement a launch produces, for example a benchmark name with a metric."
    ),
    "primary case": (
        "A case that counts toward the verdict and toward the correction for testing several "
        "cases at once."
    ),
    "secondary case": (
        "A case that is compared and graded with its uncorrected p-value, and never changes "
        "the exit code."
    ),
    "noise floor": (
        "How far a side sits from its twin on a case or a group of cases, as a fraction: the "
        "median of the per-round ratios of side over twin, less one, without its sign."
    ),
    "bar": (
        "The size a gap must exceed before it can be called a difference. Under the rule "
        "strict it is the subject's floor plus the baseline's floor."
    ),
    "gap": "How far the median ratio lies from 1, without its sign.",
    "ratio": "The median of the per-round ratios of the subject's value over the baseline's.",
    "sign test": (
        "The exact two-sided sign test with probability one half: it counts the rounds in "
        "which the subject was lower and those in which it was higher. Exact ties are not "
        "trials."
    ),
    "p-value": (
        "The probability, if neither side tends to be lower, of a split at least as uneven "
        "as the one measured."
    ),
    "corrected p-value": (
        "The p-value after the Holm correction for testing every subject and primary case of "
        "the experiment at once."
    ),
    "family": (
        "Every comparison of a subject with the baseline on a primary case that has a "
        "p-value. Twins, secondary cases and the positive control are outside it."
    ),
    "verdict": (
        "FASTER or SLOWER for a case of kind time, BETTER or WORSE for other cases, HIGHER or "
        "LOWER for a case that describes, TIE, UNRESOLVED or NO VERDICT. Programs read "
        "outcome and reason, never the word."
    ),
    "outcome": "The stable word a program reads: " + ", ".join(OUTCOME_TEXT) + ".",
    "reason": "Why a comparison is UNRESOLVED or has NO VERDICT: " + ", ".join(REASON_TEXT) + ".",
    "rule": (
        "The verdict rule. The tool ships one, strict: the bar is the sum of both floors, "
        "the p-value is corrected, alpha is 0.05, and a tie needs a gap inside the bar and a "
        "direction that is not significant."
    ),
    "capture": "The raw record of one run, capture.jsonl: append-only, one record per line.",
    "results": (
        "The analysed output of one or more captures, results.json. It is meant to be shared "
        "and holds no host name, user name, path outside the run folder or value of the "
        "environment, except an image reference you ask for and the forms that SECURITY.md "
        "of the source lists under Known limits of the shown command."
    ),
    "positive control": (
        "One more entry in every round: the baseline started once with the workload run "
        "twice in it. It must read as twice the value. A failed control gives every "
        "comparison of the run NO VERDICT."
    ),
    "launch cost": (
        "What a launch costs before the workload does anything, measured in every run with "
        "an empty command when a side is a command or a Python environment."
    ),
    "explain step": (
        "Extra, untimed launches of each subject and the baseline under instruments after "
        "the last measured round. It describes; it never changes a verdict."
    ),
    "diagnostics": (
        "What the resource figures, the counters and the sampled stacks say about how two "
        "sides differ: diagnostics.json. A finding describes a difference and never names a "
        "cause. The document holds names from the user's code."
    ),
    "disturbed round": (
        "A round in which a witness that does not depend on the measurement exceeded its "
        "threshold. The analysis is repeated without such rounds; a verdict that changes is "
        "downgraded to UNRESOLVED."
    ),
    "witness": (
        "A reading taken during every launch that does not depend on the measurement: busy "
        "cores used by everything but the launch, other compute processes on the selected "
        "GPUs, and GPU throttle events."
    ),
    "figure": (
        "One number of a results document with its text, under a stable key such as "
        "matmul.new_vs_old.ratio. pairbench fill puts figures into documents."
    ),
}


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def refusal_answer(refusal: Refusal) -> dict[str, Any]:
    """A refusal as the answer of a tool, with the results document it carries.

    ``docs`` is the address of the code's entry, with its cause and fix, in the
    documentation of this version: the address the command line prints after a
    refusal.
    """
    answer: dict[str, Any] = {
        "refusal": {
            "code": refusal.code,
            "exit_code": refusal.exit_code,
            "scope": refusal.scope,
            "message": refusal.message,
            **_docs(refusal.code),
        }
    }
    if refusal.results is not None:
        answer["results"] = refusal.results.to_json()
    return answer


def _docs(code: str) -> dict[str, str]:
    """The address of a text code's entry in the documentation of this version, as
    ``{"docs": address}``; nothing for a code the table does not hold."""
    from pairbench.model import TOOL_VERSION

    try:
        return {"docs": docs_address(code, TOOL_VERSION)}
    except ValueError:
        return {}


def _text(answer: Any) -> str:
    return json.dumps(answer, indent=2, ensure_ascii=False)


# A surrogate code point, which UTF-8 cannot encode: a name read from a file system can hold one.
_SURROGATE: Final = re.compile(r"[\ud800-\udfff]")


def _encodable(text: str) -> str:
    """An answer as text the protocol can send: each surrogate is written as the escape
    ``\\uNNNN``, which in an answer of JSON is the escape of the same character."""
    return _SURROGATE.sub(lambda found: f"\\u{ord(found.group()):04x}", text)


def _document_path(path: str, name: str) -> Path:
    """A file of a run folder: the path itself, or the named file when it is a folder."""
    given = Path(path)
    return given / name if given.is_dir() else given


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _folder_time() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@dataclass
class RunHandle:
    """One run the server started: its child process, its folder and its output."""

    handle: str
    folder: Path
    process: subprocess.Popen[str]
    started_at: str
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=KEPT_LINES))
    refusal: str | None = None
    cancelled: bool = False
    reader: threading.Thread | None = None

    def state(self) -> str:
        code = self.process.poll()
        if code is None:
            return "cancelling" if self.cancelled else "running"
        if code == EXIT_INTERRUPTED:
            return "interrupted"
        return "finished" if code in (0, 1) else "refused"


def _message_of_line(shown: str) -> str:
    """A refusal's message as the refusal holds it, read back from its line on standard error,
    which escapes it as ``errors.printable`` writes it. A backslash that opens no escape
    ``errors.unprintable`` reads is kept as printed."""
    return unprintable(shown)


def _refusal_pair(line: str, after: str) -> bool:
    """Say whether ``line`` and the line ``after`` it are the two lines a refusal prints: its
    ``CODE: message`` line, for a code of the table, and the ``pairbench: see ADDRESS`` line
    of that code. A line of the report, such as a row whose case name reads like a refusal,
    is never followed by that second line."""
    from pairbench.model import TOOL_VERSION

    found = REFUSAL_LINE.match(line)
    return (
        found is not None
        and found.group(1) in CODES
        and after == docs_line(found.group(1), TOOL_VERSION)
    )


def _pump(run: RunHandle) -> None:
    """Keep the output of a run, the last refusal it printed, and copy it to the server's
    standard error."""
    stream = run.process.stdout
    if stream is None:
        return
    previous: str | None = None
    for raw in stream:
        line = raw.rstrip("\n")
        run.lines.append(line)
        if previous is not None and _refusal_pair(previous, line):
            run.refusal = previous
        previous = line
        with contextlib.suppress(OSError, ValueError):
            print(line, file=sys.stderr, flush=True)


def _progress(folder: Path) -> dict[str, Any]:
    """How far a run has come, read from the records its capture holds so far."""
    progress: dict[str, Any] = {
        "warmup_launches": 0,
        "round_launches": 0,
        "rounds_planned": None,
        "last_round": 0,
        "capture_status": None,
    }
    try:
        text = (folder / "capture.jsonl").read_text(encoding="utf-8")
    except OSError:
        return progress
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("t")
        if kind == "lineup" and isinstance(record.get("rounds"), int):
            progress["rounds_planned"] = record["rounds"]
        elif kind == "launch":
            if record.get("phase") == "warmup":
                progress["warmup_launches"] += 1
            else:
                progress["round_launches"] += 1
                if isinstance(record.get("round"), int):
                    progress["last_round"] = max(progress["last_round"], record["round"])
        elif kind == "end":
            progress["capture_status"] = record.get("status")
    return progress


# ---------------------------------------------------------------------------
# Plain words for a comparison
# ---------------------------------------------------------------------------


def _figure(results: Results, comparison: Comparison, name: str) -> str | None:
    from pairbench.model import figure_key

    found = results.figures.get(
        figure_key(comparison.case, comparison.subject, comparison.baseline, name)
    )
    return found.text if found is not None else None


def explain_comparison(results: Results, comparison: Comparison) -> str:
    """One comparison in plain words, made from the fields the results document records."""
    from pairbench.model import (
        REASON_TOO_FAR_APART,
        family_words,
        grades_raw_p,
        p_equation,
        p_written,
        too_far_apart_words,
    )

    c = comparison
    words = [f"Case {c.case}: {c.subject} against the baseline {c.baseline}."]
    if c.n_rounds == 0:
        words.append("No round holds a value of both sides for this case.")
    else:
        ties = c.n_rounds - c.n_untied
        split = f"in {c.n_rounds} paired rounds, {c.subject} was lower in {c.n_lower}"
        split += f" and higher in {c.n_higher}"
        split += f", with {ties} exact ties" if ties else ""
        words.append(split[0].upper() + split[1:] + ".")
    ratio = _figure(results, c, "ratio")
    if c.ratio is not None:
        words.append(
            f"The median of the per-round ratios ({c.subject} over {c.baseline}) is "
            f"{ratio or format(c.ratio, '.4g')}."
        )
    if c.scale == "percent" and c.statistic is not None:
        words.append(
            "The rule grades the median of the per-round percent differences, "
            f"{c.statistic:.4g} percent."
        )
    bar = _figure(results, c, "bar")
    if c.bar is not None:
        source = (
            "supplied by the caller"
            if c.floor.source == "supplied"
            else "measured from each side's twin in the same rounds"
        )
        words.append(
            f"The noise bar is {bar or format(c.bar, '.4g')}, made from the noise floors "
            f"{source} (rule {results.rule.name})."
        )
    if c.p_raw is not None:
        p = f"The exact sign test gives {p_equation(c.p_raw, '.2g')}"
        if c.p_raw_fraction is not None and c.p_raw_fraction[1] < SHORT_FRACTION:
            p += f" ({c.p_raw_fraction[0]}/{c.p_raw_fraction[1]})"
        elif c.p_raw_fraction is not None:
            p += " (the exact fraction is p_raw_fraction in the results)"
        if grades_raw_p(results.rule):
            p += f"; rule {results.rule.name} grades each case on this p-value, uncorrected"
            if c.primary and c.p_corrected is not None and results.rule.family_size > 1:
                p += (
                    f": it does not correct for testing "
                    f"{family_words(results.rule, results.comparisons)} at once, which would "
                    f"give {p_written(c.p_corrected, '.2g')} (p_corrected), never smaller"
                )
        elif c.primary and c.p_corrected is not None:
            p += f"; {results.rule.plain}, it is {p_written(c.p_corrected, '.2g')}"
        words.append(p + ".")
    reasons = [r for r in (c.reasons or ((c.reason,) if c.reason else ())) if r]
    verdict = f"Verdict: {c.verdict} (outcome {c.outcome}"
    verdict += f", reason {c.reason})" if c.reason else ")"
    words.append(f"{verdict}: {OUTCOME_TEXT.get(c.outcome, c.outcome)}.")
    for reason in reasons:
        text = REASON_TEXT.get(reason, reason)
        if reason == REASON_TOO_FAR_APART:
            text = too_far_apart_words(c)
        words.append(f"{reason}: {text}.")
    if not c.primary:
        words.append(
            "The case is secondary: it is graded with its uncorrected p-value and never "
            "changes the exit code."
        )
    s = c.sensitivity
    disturbed = len(s.rounds_set_aside)
    rounds = f"the {disturbed} disturbed round{'s' if disturbed != 1 else ''}"
    if s.not_computed is not None:
        why = NOT_COMPUTED_TEXT.get(s.not_computed, s.not_computed)
        words.append(f"The comparison without {rounds} was not computed: {why}.")
    elif disturbed and s.outcome is not None and s.agrees is not None:
        agrees = "agrees" if s.agrees else "does not agree"
        words.append(
            f"Without {rounds} the outcome is {s.outcome}, which {agrees} with the outcome "
            "over all rounds."
        )
    words.append(
        "To report it, quote the verdict with its noise bar and p-value, and name the rule "
        "and the number of rounds."
    )
    return " ".join(words)


def _term_key(term: str) -> str:
    return " ".join(term.lower().replace("_", " ").replace("-", " ").split())


def explain_term(term: str) -> str:
    """One term, outcome or reason in plain words."""
    key = _term_key(term)
    terms = {_term_key(name): text for name, text in GLOSSARY.items()}
    terms["p value"] = GLOSSARY["p-value"]
    outcomes = {_term_key(name): text for name, text in OUTCOME_TEXT.items()}
    reasons = {_term_key(name): text for name, text in REASON_TEXT.items()}
    if key in terms:
        return terms[key]
    if key in outcomes:
        return f"The outcome {term.strip()}: {outcomes[key]}."
    if key in reasons:
        return f"The reason {term.strip()}: {reasons[key]}."
    if key in ("faster", "slower", "no verdict"):
        return explain_term({"faster": "better", "slower": "worse"}.get(key, "no_verdict"))
    known = sorted({*GLOSSARY, *OUTCOME_TEXT, *REASON_TEXT})
    raise Refusal("E_USAGE", f"no term named {term!r}; the known terms are: {', '.join(known)}")


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------


def _without_plugin_names(document: Mapping[str, Any]) -> dict[str, Any]:
    """The doctor document with every table keyed by a plug-in's name replaced by counts."""
    from pairbench.cli.doctor import GROUPS

    words = [word for _group, word in GROUPS]
    kept: dict[str, Any] = {
        key: value
        for key, value in document.items()
        if key not in (*words, "plugins", "degraded", "experimental")
    }
    for word in words:
        table = document.get(word)
        statuses: dict[str, int] = {}
        if isinstance(table, Mapping):
            for report in table.values():
                status = str(report.get("status")) if isinstance(report, Mapping) else "unknown"
                statuses[status] = statuses.get(status, 0) + 1
        kept[word] = {"count": sum(statuses.values()), "by_status": statuses}
    plugins = document.get("plugins")
    if isinstance(plugins, Mapping):
        failed = plugins.get("failed")
        kept["plugins"] = {
            "enabled": plugins.get("enabled"),
            "loaded": plugins.get("loaded"),
            "failed": len(failed) if isinstance(failed, Sequence) else 0,
        }
    degraded = document.get("degraded")
    if isinstance(degraded, Sequence):
        kept["degraded_instruments"] = [
            line for line in degraded if isinstance(line, str) and line.startswith("instruments ")
        ]
        kept["degraded_plugins"] = len(degraded) - len(kept["degraded_instruments"])
    experimental = document.get("experimental")
    kept["experimental_drivers"] = len(experimental) if isinstance(experimental, Sequence) else 0
    return kept


class ToolServer:
    """The tools, without the SDK: each method takes plain values and returns a JSON document.

    ``run_command`` is the command a run starts, followed by the run's
    arguments; it is the ``pairbench run`` command of this interpreter.
    """

    def __init__(
        self,
        *,
        allow_run: bool,
        run_command: Sequence[str] = (sys.executable, "-m", "pairbench", "run"),
    ) -> None:
        self.allow_run = allow_run
        self.run_command = tuple(run_command)
        self._lock = threading.Lock()
        self._runs_lock = threading.Lock()
        self._runs: dict[str, RunHandle] = {}

    # -- calling ----------------------------------------------------------

    def names(self) -> tuple[str, ...]:
        """The tools this server offers."""
        return tuple(n for n in TOOL_NAMES if self.allow_run or n not in RUN_TOOLS)

    def call(self, tool: str, /, **arguments: Any) -> str:
        """Run one tool and return its answer as JSON text.

        Calls that read or analyse are made one at a time, with standard
        output sent to standard error, so that nothing printed can reach
        the protocol stream. A refusal is an answer; any other error is
        answered as ``E_INTERNAL``. A surrogate in the answer, which UTF-8
        cannot encode, is written as the escape ``\\uNNNN``.
        """
        if tool not in self.names():
            message = (
                WITHOUT_ALLOW_RUN.format(tool=tool)
                if tool in RUN_TOOLS
                else f"no tool named {tool!r}"
            )
            return _encodable(_text(refusal_answer(Refusal("E_USAGE", message))))
        method: Callable[..., Any] = getattr(self, tool)
        quiet = tool in ("run_status", "run_cancel")
        try:
            if quiet:
                answer = method(**arguments)
            else:
                with self._lock, contextlib.redirect_stdout(sys.stderr):
                    answer = method(**arguments)
        except Refusal as refusal:
            answer = refusal_answer(refusal)
        except Exception as error:
            answer = refusal_answer(Refusal("E_INTERNAL", f"{type(error).__name__}: {error}"))
        return _encodable(answer if isinstance(answer, str) else _text(answer))

    # -- helpers ----------------------------------------------------------

    def _experiment(
        self,
        config: str | None,
        sides: Sequence[str] | None,
        baseline: str | None,
        workload: Sequence[str] | None,
        sets: Sequence[str] | None,
    ) -> Experiment:
        from pairbench import config as configs
        from pairbench import registry
        from pairbench.api import LoadExperiment, delegate
        from pairbench.model import KIND_FILE

        flags = configs.flag_config(
            {}, sides=tuple(sides or ()), baseline=baseline, workload=tuple(workload or ()) or None
        )
        load: LoadExperiment = delegate("load_experiment")
        experiment = load(Path(config) if config else None, flags=flags, sets=tuple(sets or ()))
        if experiment.run.no_plugins:
            registry.set_plugins_enabled(False)
        files = [side.name for side in experiment.sides if side.kind == KIND_FILE]
        if files:
            raise Refusal(
                "E_USAGE",
                "sides that are result files are compared with the compare tool, not planned "
                f"or run: {', '.join(files)}",
            )
        return experiment

    # -- the tools --------------------------------------------------------

    def doctor(self) -> dict[str, Any]:
        """What this machine supports, without the name of any plug-in."""
        from pairbench.api import CollectDoctor, delegate

        collect: CollectDoctor = delegate("doctor")
        return _without_plugin_names(collect())

    def plan(
        self,
        config: str | None = None,
        sides: Sequence[str] | None = None,
        baseline: str | None = None,
        workload: Sequence[str] | None = None,
        sets: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """The plan of an experiment, as ``pairbench plan`` prints it, and its numbers."""
        import pairbench
        from pairbench import api
        from pairbench.api import FormatPlan, LookUpSides, delegate

        experiment = self._experiment(config, sides, baseline, workload, sets)
        api.require_plot_extra(experiment.plots.mode)
        look_up: LookUpSides = delegate("look_up")
        lookups = look_up(experiment)
        planned = pairbench.plan(experiment)
        format_plan: FormatPlan = delegate("format_plan")
        return {
            "text": format_plan(planned, experiment, lookups=lookups),
            "lineup": list(planned.lineup),
            "control": planned.control,
            "rounds_requested": planned.rounds_requested,
            "rounds_planned": planned.rounds_planned,
            "launches": planned.launches,
            "explain_launches": planned.explain_launches,
            "balanced": planned.is_balanced(),
            "estimate_s": planned.estimate_s,
        }

    def run_start(
        self,
        config: str | None = None,
        sides: Sequence[str] | None = None,
        baseline: str | None = None,
        workload: Sequence[str] | None = None,
        sets: Sequence[str] | None = None,
        out: str | None = None,
    ) -> dict[str, Any]:
        """Check the experiment, start ``pairbench run`` for it and return a handle at once."""
        from pairbench import api, registry
        from pairbench.model import DIR_RUNS

        if not self.allow_run:
            raise Refusal("E_USAGE", WITHOUT_ALLOW_RUN.format(tool="run_start"))
        experiment = self._experiment(config, sides, baseline, workload, sets)
        api.require_plot_extra(experiment.plots.mode)
        with self._runs_lock:
            busy = [run.handle for run in self._runs.values() if run.process.poll() is None]
        if busy:
            raise Refusal(
                "E_USAGE",
                f"run {busy[0]} has not ended; one run at a time measures a machine fairly",
            )
        handle = secrets.token_hex(6)
        # The caller's out wins over the run folder the config names, as --out
        # does on the command line; with neither, the run gets a new folder.
        if out:
            folder = Path(out)
        elif experiment.run.out:
            folder = Path(experiment.run.out)
        else:
            folder = Path(DIR_RUNS) / f"{_folder_time()}-{handle}"
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise Refusal("E_USAGE", f"the run folder {folder.name} exists and is not empty")
        command = [*self.run_command]
        if config:
            command += ["--config", config]
        for side in sides or ():
            command += ["--side", side]
        if baseline:
            command += ["--baseline", baseline]
        for item in sets or ():
            command += ["--set", item]
        if out or not experiment.run.out:
            command += ["--out", str(folder)]
        if not registry.plugins_enabled():
            command.append("--no-plugins")
        if workload:
            command += ["--", *workload]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        run = RunHandle(handle=handle, folder=folder, process=process, started_at=_now())
        run.reader = threading.Thread(target=_pump, args=(run,), daemon=True)
        run.reader.start()
        with self._runs_lock:
            self._runs[handle] = run
        return {"handle": handle, "folder": str(folder), "state": "running"}

    def _run(self, handle: str) -> RunHandle:
        with self._runs_lock:
            run = self._runs.get(handle)
        if run is None:
            hint = "" if self.allow_run else "; runs start only with --allow-run"
            raise Refusal("E_USAGE", f"no run with the handle {handle!r}{hint}")
        return run

    def run_status(self, handle: str) -> dict[str, Any]:
        """How far a run has come, and when it has ended, its exit code and verdicts."""
        run = self._run(handle)
        code = run.process.poll()
        if code is not None and run.reader is not None:
            run.reader.join(timeout=5)
        answer: dict[str, Any] = {
            "handle": run.handle,
            "folder": str(run.folder),
            "state": run.state(),
            "started_at": run.started_at,
            "exit_code": code,
            "progress": _progress(run.folder),
            "refusal": None,
            "last_lines": list(run.lines)[-20:],
        }
        # A refusal ends the run with an exit code its text code may carry.
        found = REFUSAL_LINE.match(run.refusal) if run.refusal is not None else None
        if found is not None and code is not None:
            code_text = found.group(1)
            if code in CODES[code_text].exit_codes:
                answer["refusal"] = {
                    "code": code_text,
                    "message": _message_of_line(found.group(2)),
                    **_docs(code_text),
                }
        results = run.folder / "results.json"
        if code is not None and results.is_file():
            answer["results"] = str(results)
            try:
                answer["verdicts"] = self._verdicts(results)
            except Refusal as refusal:
                answer["results_refusal"] = refusal_answer(refusal)["refusal"]
        return answer

    @staticmethod
    def _verdicts(path: Path) -> list[dict[str, Any]]:
        import pairbench

        loaded = pairbench.load_results(path)
        return [
            {
                "case": c.case,
                "subject": c.subject,
                "baseline": c.baseline,
                "verdict": c.verdict,
                "outcome": c.outcome,
                "reason": c.reason,
            }
            for c in loaded.comparisons
            if c.primary
        ]

    def run_cancel(self, handle: str) -> dict[str, Any]:
        """Interrupt a run, as Ctrl-C interrupts the command; it ends with exit code 130."""
        if not self.allow_run:
            raise Refusal("E_USAGE", WITHOUT_ALLOW_RUN.format(tool="run_cancel"))
        run = self._run(handle)
        if run.process.poll() is None:
            run.cancelled = True
            with contextlib.suppress(ProcessLookupError):
                run.process.send_signal(signal.SIGINT)
        return {"handle": run.handle, "state": run.state(), "exit_code": run.process.poll()}

    def results(
        self, path: str, case: str | None = None, subject: str | None = None
    ) -> dict[str, Any]:
        """A results document, or the comparisons of one case, named with or without its mark."""
        import pairbench
        from pairbench.model import case_unsuffixed

        loaded = pairbench.load_results(_document_path(path, "results.json"))
        if case is None:
            document: dict[str, Any] = json.loads(pairbench.render(loaded, "json"))
            return document
        chosen = [
            c.to_json()
            for c in loaded.comparisons
            if case in (c.case, case_unsuffixed(c.case))
            and (subject is None or c.subject == subject)
        ]
        if not chosen:
            cases = sorted({c.case for c in loaded.comparisons})
            raise Refusal(
                "E_USAGE",
                f"no comparison of case {case!r}"
                + (f" for side {subject!r}" if subject else "")
                + f"; the cases are: {', '.join(cases[:40]) or 'none'}",
            )
        return {"rule": loaded.rule.to_json(), "comparisons": chosen}

    def diagnostics(self, path: str, findings_only: bool = False) -> dict[str, Any]:
        """A diagnostics document, or its findings, with the notice that it holds names."""
        import pairbench

        loaded = pairbench.load_diagnostics(_document_path(path, "diagnostics.json"))
        if findings_only:
            return {"notice": NAMES_NOTICE, "findings": [f.to_json() for f in loaded.findings]}
        return {"notice": NAMES_NOTICE, "diagnostics": loaded.to_json()}

    def compare(
        self,
        captures: Sequence[str] | None = None,
        reader: str | None = None,
        sides: Sequence[str] | None = None,
        driver: str | None = None,
        levels: str | None = None,
        baseline: str | None = None,
        rule: str | None = None,
        out: str | None = None,
        allow_incomplete: bool = False,
        allow_mixed_machines: bool = False,
        assume_interleaved: bool = False,
    ) -> dict[str, Any]:
        """Analyse captures, or result files of other tools, as ``pairbench compare`` does."""
        import pairbench
        from pairbench import config as configs
        from pairbench.api import WriteResults, delegate
        from pairbench.model import KIND_FILE

        if sides and captures:
            raise Refusal("E_USAGE", "give capture files or result-file sides, not both")
        if not sides and not captures:
            raise Refusal("E_USAGE", "compare needs capture files or result-file sides")
        if reader and sides:
            raise Refusal("E_USAGE", "a reader reads capture files; result files take a driver")
        if driver and not sides:
            raise Refusal("E_USAGE", "a driver reads result files given as sides")
        if levels and not sides:
            raise Refusal("E_USAGE", "levels names the load level of result files given as sides")
        folder: Path | None
        chosen_baseline = baseline
        if sides:
            if not driver:
                raise Refusal("E_USAGE", "result files given as sides need a driver")
            flags = configs.flag_config(
                {
                    "--driver": driver,
                    "--levels": levels,
                    "--rule": rule,
                    "--out": out,
                    "--explain": "off",
                    "--plots": "off",
                },
                sides=tuple(sides),
                baseline=baseline,
            )
            load = delegate("load_experiment")
            experiment = load(None, environ={}, flags=flags)
            others = [side.name for side in experiment.sides if side.kind != KIND_FILE]
            if others:
                raise Refusal(
                    "E_USAGE",
                    "compare takes sides that are result files (NAME=file:GLOB): "
                    + ", ".join(others),
                )
            try:
                capture = pairbench.run(experiment, out=Path(out) if out else None)
            except Refusal as refusal:
                run_dir = refusal.detail.get("run_dir")
                if refusal.results is not None and isinstance(run_dir, str):
                    write: WriteResults = delegate("write_results")
                    refusal.results = write(refusal.results, Path(run_dir))
                raise
            found = [capture]
            source = capture.source.path if capture.source is not None else None
            folder = Path(source).parent if source else None
            chosen_baseline = None
        else:
            found = [
                loaded
                for path in captures or ()
                for loaded in pairbench.load_capture(path, reader=reader)
            ]
            folder = Path(out) if out else None
        write_results: WriteResults = delegate("write_results")
        try:
            analysed = pairbench.analyse(
                found,
                rule=rule or "strict",
                baseline=chosen_baseline,
                allow_incomplete=allow_incomplete,
                allow_mixed_machines=allow_mixed_machines,
                assume_interleaved=assume_interleaved,
            )
        except Refusal as refusal:
            if refusal.results is not None and folder is not None:
                refusal.results = write_results(refusal.results, folder)
            raise
        answer: dict[str, Any] = {}
        if folder is not None:
            analysed = write_results(analysed, folder)
            answer["folder"] = str(folder)
        answer["results"] = json.loads(pairbench.render(analysed, "json"))
        return answer

    def explain(
        self,
        term: str | None = None,
        results: str | None = None,
        case: str | None = None,
        subject: str | None = None,
    ) -> dict[str, Any]:
        """One term, or the comparisons of one case of a results file, in plain words."""
        import pairbench
        from pairbench.model import case_unsuffixed

        if (term is None) == (results is None):
            raise Refusal("E_USAGE", "explain takes a term, or a results file and a case")
        if term is not None:
            return {"term": term, "text": explain_term(term)}
        if case is None:
            raise Refusal("E_USAGE", "explain needs the case of the comparison to explain")
        loaded = pairbench.load_results(_document_path(str(results), "results.json"))
        chosen = [
            c
            for c in loaded.comparisons
            if case in (c.case, case_unsuffixed(c.case))
            and (subject is None or c.subject == subject)
        ]
        if not chosen:
            raise Refusal("E_USAGE", f"no comparison of case {case!r} in the results")
        return {
            "comparisons": [
                {
                    "case": c.case,
                    "subject": c.subject,
                    "baseline": c.baseline,
                    "text": explain_comparison(loaded, c),
                }
                for c in chosen
            ]
        }

    def fill(
        self,
        template: str,
        results: Sequence[str] | None = None,
        output: str | None = None,
        check: bool = False,
    ) -> dict[str, Any]:
        """Fill a document's figure tokens; with ``check``, compare with ``output`` instead."""
        import pairbench

        if check and not output:
            raise Refusal("E_USAGE", "check compares with the output file: give output")
        loaded: dict[str, Results] = {}
        for text in results or ():
            name, eq, rest = text.partition("=")
            named = bool(eq and rest and re.fullmatch(r"[A-Za-z0-9_.-]+", name))
            key, path = (name, rest) if named and not Path(text).exists() else ("", text)
            if key in loaded:
                raise Refusal("E_USAGE", "results name a file twice, or two files have no name")
            loaded[key] = pairbench.load_results(path)
        source = Path(template)
        try:
            text = source.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise Refusal(
                "E_USAGE", f"cannot read the template {source.name}: {type(error).__name__}"
            ) from error
        filled = pairbench.fill(text, loaded)
        if output is None:
            return {"text": filled}
        target = Path(output)
        if check:
            try:
                current = target.read_bytes()
            except FileNotFoundError:
                return {"output": target.name, "exists": False, "matches": False}
            except OSError as error:
                reason = error.strerror or type(error).__name__
                raise Refusal("E_USAGE", f"cannot read {target.name}: {reason}") from error
            return {
                "output": target.name,
                "exists": True,
                "matches": current == filled.encode("utf-8"),
            }
        try:
            target.write_bytes(filled.encode("utf-8"))
        except OSError as error:
            raise Refusal("E_USAGE", f"cannot write {target.name}: {error.strerror}") from error
        return {"written": target.name}

    def selftest(self) -> dict[str, Any]:
        """The known answers and the controls of the statistics; launches nothing."""
        from pairbench.api import RunSelftest, delegate

        run_selftest: RunSelftest = delegate("selftest")
        controls = [
            {"id": r.id, "title": r.title, "passed": r.passed, "detail": r.detail}
            for r in run_selftest()
        ]
        return {"passed": all(c["passed"] for c in controls), "controls": controls}

    def schema(self, name: str) -> dict[str, Any]:
        """A JSON Schema: ``capture``, ``results``, ``config`` or ``diagnostics``."""
        from pairbench.results import SCHEMA_NAMES, schema_text

        if name not in SCHEMA_NAMES:
            raise Refusal(
                "E_USAGE", f"no schema named {name!r}; there are {', '.join(SCHEMA_NAMES)}"
            )
        document: dict[str, Any] = json.loads(schema_text(name))
        return document

    def close(self) -> None:
        """Interrupt every run still going and wait for it to end."""
        with self._runs_lock:
            running = [run for run in self._runs.values() if run.process.poll() is None]
        for run in running:
            run.cancelled = True
            with contextlib.suppress(ProcessLookupError):
                run.process.send_signal(signal.SIGINT)
        for run in running:
            try:
                run.process.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                run.process.kill()
                run.process.wait()


# ---------------------------------------------------------------------------
# The tools as the SDK sees them
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One tool: its name, what it does in words, and the function the SDK calls."""

    name: str
    description: str
    fn: Callable[..., str]


SIDES_HELP: Final = (
    "config: path of a TOML config file; sides: list of NAME=KIND:SPEC, as --side; baseline: "
    "the baseline's name; workload: the workload's arguments, as after --; sets: list of "
    "KEY=VALUE, as --set."
)


def tool_specs(server: ToolServer) -> list[ToolSpec]:
    """The tools of a server, each as a function with a plain signature."""

    def doctor() -> str:
        return server.call("doctor")

    def plan(
        config: str | None = None,
        sides: list[str] | None = None,
        baseline: str | None = None,
        workload: list[str] | None = None,
        sets: list[str] | None = None,
    ) -> str:
        return server.call(
            "plan", config=config, sides=sides, baseline=baseline, workload=workload, sets=sets
        )

    def run_start(
        config: str | None = None,
        sides: list[str] | None = None,
        baseline: str | None = None,
        workload: list[str] | None = None,
        sets: list[str] | None = None,
        out: str | None = None,
    ) -> str:
        return server.call(
            "run_start",
            config=config,
            sides=sides,
            baseline=baseline,
            workload=workload,
            sets=sets,
            out=out,
        )

    def run_status(handle: str) -> str:
        return server.call("run_status", handle=handle)

    def run_cancel(handle: str) -> str:
        return server.call("run_cancel", handle=handle)

    def results(path: str, case: str | None = None, subject: str | None = None) -> str:
        return server.call("results", path=path, case=case, subject=subject)

    def diagnostics(path: str, findings_only: bool = False) -> str:
        return server.call("diagnostics", path=path, findings_only=findings_only)

    def compare(
        captures: list[str] | None = None,
        reader: str | None = None,
        sides: list[str] | None = None,
        driver: str | None = None,
        levels: str | None = None,
        baseline: str | None = None,
        rule: str | None = None,
        out: str | None = None,
        allow_incomplete: bool = False,
        allow_mixed_machines: bool = False,
        assume_interleaved: bool = False,
    ) -> str:
        return server.call(
            "compare",
            captures=captures,
            reader=reader,
            sides=sides,
            driver=driver,
            levels=levels,
            baseline=baseline,
            rule=rule,
            out=out,
            allow_incomplete=allow_incomplete,
            allow_mixed_machines=allow_mixed_machines,
            assume_interleaved=assume_interleaved,
        )

    def explain(
        term: str | None = None,
        results: str | None = None,
        case: str | None = None,
        subject: str | None = None,
    ) -> str:
        return server.call("explain", term=term, results=results, case=case, subject=subject)

    def fill(
        template: str,
        results: list[str] | None = None,
        output: str | None = None,
        check: bool = False,
    ) -> str:
        return server.call("fill", template=template, results=results, output=output, check=check)

    def selftest() -> str:
        return server.call("selftest")

    def schema(name: str) -> str:
        return server.call("schema", name=name)

    every = {
        "doctor": ToolSpec(
            "doctor",
            "What this machine supports: the external programs found, the instruments of the "
            "explain step, the plot extra, and how many plug-ins of each kind report each "
            "state. Starts and changes nothing.",
            doctor,
        ),
        "plan": ToolSpec(
            "plan",
            "The plan of an experiment, as pairbench plan prints it: lineup, rounds, launches, "
            "balance, the positive control and the explain launches. Launches nothing. "
            + SIDES_HELP,
            plan,
        ),
        "run_start": ToolSpec(
            "run_start",
            "Start pairbench run for an experiment and return a handle at once; the run "
            "launches commands on this machine. Arguments as for plan, and out: the run folder "
            "(empty or absent; default: run.out of the config, else a new folder). One run at "
            "a time. " + SIDES_HELP,
            run_start,
        ),
        "run_status": ToolSpec(
            "run_status",
            "Progress of a run by its handle; once it has ended, its exit code, any refusal, "
            "the results file and the verdict of every primary case.",
            run_status,
        ),
        "run_cancel": ToolSpec(
            "run_cancel",
            "Interrupt a run by its handle, as Ctrl-C does: the current launch is torn down, "
            "the capture is marked interrupted and the exit code is 130.",
            run_cancel,
        ),
        "results": ToolSpec(
            "results",
            "A results document (path: results.json or its run folder), or, with case and "
            "optionally subject, the comparisons of that case; a name given without its mark "
            "gives those of every case it shows with a mark. Read comparisons[].outcome and "
            "reason, and quote numbers from figures.",
            results,
        ),
        "diagnostics": ToolSpec(
            "diagnostics",
            "A diagnostics document (path: diagnostics.json or its run folder), or only its "
            "findings with findings_only. A finding describes a difference and never names a "
            "cause. The document holds names from the user's code: do not paste them into "
            "anything public unless asked to.",
            diagnostics,
        ),
        "compare": ToolSpec(
            "compare",
            "Analyse existing captures (captures: paths; reader: a capture reader), or result "
            "files of other tools (sides: NAME=file:GLOB; driver: the driver that reads them; "
            "levels: the load level the files were made at, for a serving driver). "
            "baseline, rule, out (writes results.json and results.md there) and the switches "
            "allow_incomplete, allow_mixed_machines and assume_interleaved as for "
            "pairbench compare.",
            compare,
        ),
        "explain": ToolSpec(
            "explain",
            "A plain-language explanation of a term (term), or of the comparisons of one case "
            "of a results file (results, case, optionally subject); a name given without its "
            "mark explains those of every case it shows with a mark.",
            explain,
        ),
        "fill": ToolSpec(
            "fill",
            "Fill a document's figure tokens from results files (results: PATH or NAME=PATH). "
            "Without output the filled text is returned; with output it is written; with "
            "check it is compared with output instead.",
            fill,
        ),
        "selftest": ToolSpec(
            "selftest",
            "Run the known answers and the controls of the statistics. Launches nothing.",
            selftest,
        ),
        "schema": ToolSpec(
            "schema",
            "A JSON Schema by name: capture, results, config or diagnostics.",
            schema,
        ),
    }
    return [every[name] for name in server.names()]


STAND_IN_HELP: Final = "Offered only when the server is started with --allow-run."


def stand_in_specs(server: ToolServer) -> list[ToolSpec]:
    """A stand-in for each tool the server does not offer, which takes no arguments.

    ``main`` registers the stand-ins and leaves them out of the list a client
    reads, so a client that calls ``run_start`` of a server started without
    ``--allow-run`` reads the refusal that says how to start it with it, and
    not the SDK's answer for a name it does not know.
    """

    def stand_in(name: str) -> ToolSpec:
        def refuse() -> str:
            return server.call(name)

        return ToolSpec(name, STAND_IN_HELP, refuse)

    return [stand_in(name) for name in TOOL_NAMES if name not in server.names()]


# ---------------------------------------------------------------------------
# The SDK
# ---------------------------------------------------------------------------


def sdk_server(name: str, instructions: str, hidden: Collection[str] = ()) -> Any:
    """Make the SDK's server object. This is the only place the SDK is imported.

    Two layouts of the SDK are read, as its public source shows them:
    ``mcp.server.mcpserver.MCPServer`` in the mcp 2.x releases (read at v2.3.0,
    https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0/src/mcp/server/mcpserver),
    and ``mcp.server.fastmcp.FastMCP`` in the mcp 1.x releases (read at v1.21.1,
    https://github.com/modelcontextprotocol/python-sdk/tree/v1.21.1/src/mcp/server/fastmcp).
    The 2.x layout is imported by a statement, so the type check reads the
    class against an installed 2.x release. Most 2.x releases also ship
    ``mcp.server.fastmcp`` as a typed module with no API whose import raises
    (https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/fastmcp.py),
    so the 1.x layout is imported by name: a statement that imports
    ``FastMCP`` would fail the type check against those releases.

    An import error whose module is the SDK's own (``library.in_library``)
    means the layout is absent, and the other one is read; when both are
    absent, the first error is the one reported. An import error of any
    other module, such as a dependency of the SDK that is missing, is
    reported at once, and so is any other error a layout's module raises as
    it loads. Each error becomes the refusal ``library.refusal`` words for it.

    The tools named in ``hidden`` are left out of the list the server gives a
    client, and still answer a call.
    """
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as newer:
        if not library.in_library(newer.name):
            raise library.refusal(newer) from newer
        try:
            older = importlib.import_module("mcp.server.fastmcp")
        except ImportError as error:
            first = newer if library.in_library(error.name) else error
            raise library.refusal(first) from first
        except Exception as error:
            raise library.refusal(error) from error
        base: Any = older.FastMCP
    except Exception as error:
        raise library.refusal(error) from error
    else:
        base = MCPServer
    return hiding(base, frozenset(hidden))(name, instructions=instructions)


def hiding(base: Any, hidden: frozenset[str]) -> Any:
    """The SDK's server class, or a subclass whose ``list_tools`` leaves out the ``hidden`` tools.

    Both layouts answer a client's ``tools/list`` with the server's
    ``list_tools`` method and its ``tools/call`` with the tools registered,
    so a tool left out of the list still answers a call. The 1.x layout
    binds the method when the server is made, so the method is replaced in
    a subclass and not on the object. Both are read in the ``server.py`` of
    each layout folder that ``sdk_server`` links, at v2.3.0 and at v1.21.1.
    """
    if not hidden:
        return base

    async def list_tools(self: Any, *args: Any, **kwargs: Any) -> list[Any]:
        listed = await super(made, self).list_tools(*args, **kwargs)
        return [tool for tool in listed if tool.name not in hidden]

    def body(namespace: dict[str, Any]) -> None:
        namespace.update(list_tools=list_tools, __module__=__name__)

    made: Any = types.new_class(base.__name__, (base,), exec_body=body)
    return made


def add_tool(server: Any, spec: ToolSpec) -> None:
    """Register one tool with the SDK's server; its answer is one JSON text."""
    options: dict[str, Any] = {"name": spec.name, "description": spec.description}
    if "structured_output" in inspect.signature(server.add_tool).parameters:
        options["structured_output"] = False
    server.add_tool(spec.fn, **options)


def main(*, allow_run: bool) -> int:
    """Serve the tools over standard input and output until the client leaves.

    ``allow_run`` adds ``run_start`` and ``run_cancel``; without it each is
    a stand-in, left out of the tool list, whose answer to a call is the
    refusal that says how to start the server with it. Runs still going
    when the client leaves are interrupted and waited for. A library that
    cannot be loaded is a refusal, worded by ``library.refusal``.
    """
    tools = ToolServer(allow_run=allow_run)
    stand_ins = stand_in_specs(tools)
    try:
        server = sdk_server(SERVER_NAME, INSTRUCTIONS, hidden=[spec.name for spec in stand_ins])
        for spec in [*tool_specs(tools), *stand_ins]:
            add_tool(server, spec)
        server.run("stdio")
    except ImportError as error:
        # The SDK may import a module of its own, or one it depends on, as it starts to serve.
        raise library.refusal(error) from error
    finally:
        tools.close()
    return 0


__all__ = [
    "GLOSSARY",
    "INSTRUCTIONS",
    "NAMES_NOTICE",
    "OUTCOME_TEXT",
    "REASON_TEXT",
    "RUN_TOOLS",
    "SERVER_NAME",
    "STAND_IN_HELP",
    "TOOL_NAMES",
    "WITHOUT_ALLOW_RUN",
    "RunHandle",
    "ToolServer",
    "ToolSpec",
    "add_tool",
    "explain_comparison",
    "explain_term",
    "hiding",
    "main",
    "refusal_answer",
    "sdk_server",
    "stand_in_specs",
    "tool_specs",
]
