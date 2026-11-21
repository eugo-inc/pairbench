# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Cases that describe and do not judge, the reserved case prefixes and the resource cases."""

from __future__ import annotations

from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import Refusal
from pairbench.model import Case, CaseSettings
from pairbench.results import load_schema

jsonschema = pytest.importorskip(
    "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
)


def _sample(case: str, value: float = 1.5, **changes: Any) -> api.Sample:
    fields: dict[str, Any] = {
        "case": case,
        "metric": "time",
        "unit": "s",
        "better": "lower",
        "kind": "time",
        "value": value,
    }
    fields.update(changes)
    return api.Sample(**fields)


# ---------------------------------------------------------------------------
# A case whose better is "none"
# ---------------------------------------------------------------------------


def test_a_case_can_describe_without_judging() -> None:
    case = Case(id="res/cores", metric="cores", unit="cores", better="none", primary=False)
    assert case.better == "none"
    assert Case.from_json(case.to_json()) == case


def test_a_case_that_describes_is_refused_as_a_primary_case() -> None:
    with pytest.raises(Refusal, match="it cannot be a primary case") as caught:
        Case(id="made-up", metric="count", unit="count", better="none", primary=True)
    assert (caught.value.code, caught.value.exit_code, caught.value.scope) == ("E_USAGE", 2, "case")
    with pytest.raises(Refusal, match="it cannot be a primary case"):
        Case(id="made-up", metric="count", unit="count", better="none")
    with pytest.raises(Refusal, match="it cannot be a primary case") as read:
        Case.from_json(
            {
                "id": "made-up",
                "metric": "count",
                "unit": "count",
                "better": "none",
                "kind": "count",
                "primary": True,
                "group": None,
            }
        )
    assert read.value.code == "E_USAGE"


@pytest.mark.parametrize("document", ["capture", "results"])
def test_the_schemas_refuse_a_primary_case_that_describes(document: str) -> None:
    definition = load_schema(document)["$defs"]["Case"]
    assert definition["not"] == {
        "properties": {"better": {"const": "none"}, "primary": {"const": True}},
        "required": ["better", "primary"],
    }
    schema = {**definition, "$defs": {}}
    case = {
        "id": "made-up",
        "metric": "count",
        "unit": "count",
        "better": "none",
        "kind": "count",
        "primary": False,
        "group": None,
    }
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(case)) == []
    assert len(list(validator.iter_errors({**case, "primary": True}))) == 1
    assert list(validator.iter_errors({**case, "better": "lower", "primary": True})) == []


@pytest.mark.parametrize(
    ("direction", "better", "outcome"),
    [
        ("lower", "lower", "better"),
        ("higher", "lower", "worse"),
        ("lower", "higher", "worse"),
        ("higher", "higher", "better"),
        ("lower", "none", "lower"),
        ("higher", "none", "higher"),
    ],
)
def test_the_outcome_of_a_significant_difference_outside_the_bar(
    direction: str, better: str, outcome: str
) -> None:
    assert model.direction_outcome(direction, better) == outcome


def test_a_direction_and_a_better_outside_their_vocabulary_are_refused() -> None:
    with pytest.raises(ValueError, match="a direction is lower or higher"):
        model.direction_outcome("sideways", "lower")
    with pytest.raises(ValueError, match="better is one of lower, higher, none"):
        model.direction_outcome("lower", "made_up")


def test_the_outcomes_a_case_can_have_follow_its_better() -> None:
    assert model.outcomes_of("lower") == ("better", "worse", "tie", "unresolved", "no_verdict")
    assert model.outcomes_of("higher") == ("better", "worse", "tie", "unresolved", "no_verdict")
    assert model.outcomes_of("none") == ("higher", "lower", "tie", "unresolved", "no_verdict")
    with pytest.raises(ValueError, match="better is one of"):
        model.outcomes_of("made_up")


@pytest.mark.parametrize(
    ("outcome", "kind", "word"),
    [
        ("higher", "time", "HIGHER"),
        ("lower", "time", "LOWER"),
        ("higher", "count", "HIGHER"),
        ("lower", "other", "LOWER"),
    ],
)
def test_a_case_that_describes_reads_higher_or_lower(outcome: str, kind: str, word: str) -> None:
    assert model.verdict_word(outcome, kind) == word
    assert word not in ("BETTER", "WORSE", "FASTER", "SLOWER")


def test_every_outcome_has_a_display_word_for_every_kind_of_case() -> None:
    for outcome in model.OUTCOMES:
        for kind in model.CASE_KINDS:
            assert model.verdict_word(outcome, kind) in model.VERDICTS


def test_the_outcomes_that_can_fail_a_run_are_those_of_a_case_that_judges() -> None:
    assert model.FAIL_ON == ("better", "worse", "unresolved", "no_verdict")
    assert set(model.FAIL_ON) <= set(model.OUTCOMES_JUDGED)


# ---------------------------------------------------------------------------
# Which cases are primary
# ---------------------------------------------------------------------------


def test_a_pattern_that_matches_a_describing_case_among_others_leaves_it_secondary() -> None:
    cases = CaseSettings(primary=("*",))
    assert cases.is_primary("matmul", [], better="lower") is True
    assert cases.is_primary("made-up-count", [], better="none") is False
    assert cases.is_primary("res/cores", [], better="none") is False


def test_naming_a_describing_case_as_primary_is_refused() -> None:
    by_pattern = CaseSettings(primary=("made-up-count",))
    with pytest.raises(Refusal, match="'made-up-count' describes and does not judge") as caught:
        by_pattern.is_primary("made-up-count", [], better="none")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    among_others = CaseSettings(primary=("matmul", "made-up-count"))
    with pytest.raises(Refusal, match="it cannot be a primary case"):
        among_others.is_primary("made-up-count", [], better="none")
    assert among_others.is_primary("matmul", [], better="lower") is True


def test_naming_a_describing_case_without_its_mark_is_refused() -> None:
    # A pattern equal to the name a run gave, less its mark, asks for that case outright.
    marked = "copy x +1a2b3c4d"
    with pytest.raises(Refusal) as caught:
        CaseSettings(primary=("copy x",)).is_primary(marked, [], better="none")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "case 'copy x +1a2b3c4d' describes and does not judge (its better is none): it cannot be "
        "a primary case"
    )
    assert CaseSettings(primary=("copy*",)).is_primary(marked, [], better="none") is False


def test_the_list_of_a_driver_leaves_a_describing_case_secondary() -> None:
    printed = ["matmul", "made-up-count"]
    assert CaseSettings().is_primary("made-up-count", printed, better="none") is False
    assert CaseSettings().is_primary("matmul", printed, better="lower") is True
    assert CaseSettings().is_primary("made-up-count", ["matmul"], better="none") is False
    sample = _sample("made-up-count", better="none", kind="count", unit="count")
    recorded = api.case_of(sample, CaseSettings(), printed)
    assert recorded == Case(
        id="made-up-count",
        metric="time",
        unit="count",
        better="none",
        kind="count",
        primary=False,
        group=None,
    )
    assert api.case_of(_sample("matmul"), CaseSettings(), printed).primary is True


def test_the_direction_is_not_asked_for_a_case_that_judges() -> None:
    assert CaseSettings(primary=("mat*",)).is_primary("matmul", []) is True
    assert CaseSettings().is_primary("matmul", ["matmul"]) is True
    assert CaseSettings().is_primary("fft", ["matmul"], better="higher") is False


# ---------------------------------------------------------------------------
# The reserved prefixes
# ---------------------------------------------------------------------------


def test_the_reserved_case_prefixes() -> None:
    assert model.RES_PREFIX == "res/"
    assert model.STARTUP_PREFIX == "startup/"
    assert model.RESERVED_CASE_PREFIXES == ("res/", "startup/")
    assert model.CASE_STARTUP_READY.startswith(model.STARTUP_PREFIX)
    assert model.CASE_STARTUP_FIRST_ANSWER.startswith(model.STARTUP_PREFIX)


@pytest.mark.parametrize(
    ("case", "reserved"),
    [
        ("res/cores", True),
        ("res/made-up", True),
        ("startup/ready_s", True),
        ("wall", False),
        ("results/matmul", False),
        ("c32/res/cores", False),
        ("restart", False),
        ("startup", False),
    ],
)
def test_a_case_id_under_a_reserved_prefix(case: str, reserved: bool) -> None:
    assert model.is_reserved_case(case) is reserved


@pytest.mark.parametrize("case", ["res/made-up", "startup/made-up", "res/cores"])
def test_a_driver_case_under_a_reserved_prefix_is_a_failed_launch(case: str) -> None:
    with pytest.raises(Refusal, match="may not start with 'res/' or 'startup/'") as caught:
        api.refuse_reserved_cases([_sample("matmul"), _sample(case)])
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert case in caught.value.message


def test_cases_outside_the_reserved_prefixes_pass_the_check() -> None:
    assert api.refuse_reserved_cases([_sample("matmul"), _sample("c32/ttft_ms_median")]) is None
    assert api.refuse_reserved_cases([]) is None


# ---------------------------------------------------------------------------
# Case ids as the results show them
# ---------------------------------------------------------------------------


def test_a_case_id_a_driver_read_is_shown_with_its_absolute_paths_cut() -> None:
    read = [
        _sample("tests/test_io.py::test_read[/made/up/home/data.csv]", value=2.5, n_inner=3),
        _sample("BM_copy/8/64"),
        _sample("c32/ttft_ms_median"),
    ]
    shown = api.public_cases(read, "made-up-driver")
    assert [s.case for s in shown] == [
        "tests/test_io.py::test_read[data.csv]",
        "BM_copy/8/64",
        "c32/ttft_ms_median",
    ]
    assert (shown[0].value, shown[0].n_inner) == (2.5, 3)
    assert shown[1:] == read[1:]


def test_two_case_ids_that_differ_only_in_a_folder_are_refused_never_paired() -> None:
    read = [
        _sample("test_read[/made/up/small/in.csv]"),
        _sample("test_read[/made/up/large/in.csv]"),
    ]
    with pytest.raises(Refusal) as caught:
        api.public_cases(read, "made-up-driver")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("made-up-driver: two different cases")
    assert "'test_read[in.csv]'" in caught.value.message
    assert "/made/up" not in caught.value.message


def test_a_case_id_whose_cut_drops_words_is_refused_by_a_read_with_no_key() -> None:
    read = [
        _sample("read /made/up/in.csv fast mode/x"),
        _sample("read /made/up/in.csv slow mode/x"),
    ]
    with pytest.raises(Refusal) as caught:
        api.public_cases(read, "made-up-driver")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "made-up-driver: the cut of the case read as 'read x' drops words that hold no '/', so "
        "its name needs the mark a run makes with its own key, and this read has none; read it "
        "in a run, or give them names that differ outside their paths, absolute or climbing "
        "with '..', and outside their secrets; a path runs on over the words after it that "
        "start with a letter, a digit or '_', up to the last that holds a '/', and a quote ends it"
    )


def test_two_case_ids_that_differ_in_words_a_path_runs_over_get_two_marks_in_a_run() -> None:
    read = [
        _sample("read /made/up/in.csv fast mode/x"),
        _sample("read /made/up/in.csv slow mode/x"),
    ]
    names = api.CaseNames(bytes(range(32)))
    shown = [s.case for s in api.public_cases(read, "made-up-driver", names, side="new")]
    # HMAC-SHA256 under the key of the SHA-256 of ["words","read","fast"] (and "slow"), cut to 8.
    assert shown == ["read x +a0f2fbc4", "read x +7a704d69"]


def test_a_quote_ends_a_path_so_the_words_after_it_keep_two_case_ids_apart() -> None:
    read = [
        _sample("read '/made/up/in.csv' fast mode/x"),
        _sample("read '/made/up/in.csv' slow mode/x"),
    ]
    assert [sample.case for sample in api.public_cases(read, "made-up-driver")] == [
        "read 'in.csv' fast mode/x",
        "read 'in.csv' slow mode/x",
    ]


def test_one_case_id_read_twice_is_left_to_the_check_of_an_id_given_twice() -> None:
    read = [_sample("/made/up/a/bench"), _sample("/made/up/a/bench")]
    assert [s.case for s in api.public_cases(read, "made-up-driver")] == ["bench", "bench"]


@pytest.mark.parametrize(
    "case",
    [
        "BM_made_up<int>/8/cpu_time",
        "BM_made_up(x)/8",
        "made_up<T>/Device=0 T=I32/cpu_time",
        "test_made_up_div[1/2]",
    ],
)
def test_a_case_id_whose_parts_are_joined_by_a_slash_is_read_as_it_is(case: str) -> None:
    read = [_sample(case)]
    assert api.public_cases(read, "made-up-driver") == read


def test_the_cases_of_a_templated_benchmark_over_a_range_are_kept_apart() -> None:
    read = [_sample(f"BM_made_up<int>/{n}{part}") for n in (8, 64) for part in ("", "/cpu_time")]
    assert api.public_cases(read, "made-up-driver") == read


class _CleansItsIds:
    cleans_case_ids = True


class _SaysYes:
    cleans_case_ids = "yes"


# A case id as a driver that cleans its own ids gives it: a name cut to its file, then a part.
CLEANED = "BM_Load/file://a.gguf/cpu_time"


def test_the_runner_keeps_the_ids_of_a_driver_that_cleans_them_itself() -> None:
    read = [_sample(CLEANED)]
    assert isinstance(_CleansItsIds(), api.CleansCaseIds)
    assert api.shown_cases(_CleansItsIds(), read, "made-up-driver") == read


@pytest.mark.parametrize("driver", [object(), _SaysYes()], ids=["no attribute", "not true"])
def test_the_runner_cleans_the_ids_of_any_other_driver(driver: object) -> None:
    read = [_sample("test_read[/made/up/home/data.csv]"), _sample(CLEANED)]
    assert [s.case for s in api.shown_cases(driver, read, "made-up-driver")] == [
        "test_read[data.csv]",
        "BM_Load/file://cpu_time",
    ]


# ---------------------------------------------------------------------------
# The resource cases
# ---------------------------------------------------------------------------


def test_the_eight_resource_cases_and_their_units() -> None:
    assert dict(model.RESOURCE_CASES) == {
        "res/user": "s",
        "res/sys": "s",
        "res/cores": "cores",
        "res/rss_peak": "bytes",
        "res/ctx_voluntary": "count",
        "res/ctx_involuntary": "count",
        "res/faults_major": "count",
        "res/faults_minor": "count",
    }
    assert list(model.RESOURCE_CASES) == [
        model.CASE_RES_USER,
        model.CASE_RES_SYS,
        model.CASE_RES_CORES,
        model.CASE_RES_RSS_PEAK,
        model.CASE_RES_CTX_VOLUNTARY,
        model.CASE_RES_CTX_INVOLUNTARY,
        model.CASE_RES_FAULTS_MAJOR,
        model.CASE_RES_FAULTS_MINOR,
    ]


@pytest.mark.parametrize(
    ("case", "metric", "unit", "kind"),
    [
        ("res/user", "user", "s", "other"),
        ("res/sys", "sys", "s", "other"),
        ("res/cores", "cores", "cores", "other"),
        ("res/rss_peak", "rss_peak", "bytes", "other"),
        ("res/ctx_voluntary", "ctx_voluntary", "count", "count"),
        ("res/ctx_involuntary", "ctx_involuntary", "count", "count"),
        ("res/faults_major", "faults_major", "count", "count"),
        ("res/faults_minor", "faults_minor", "count", "count"),
    ],
)
def test_a_resource_case_is_secondary_describes_and_is_its_own_floor_group(
    case: str, metric: str, unit: str, kind: str
) -> None:
    assert model.resource_case(case) == Case(
        id=case, metric=metric, unit=unit, better="none", kind=kind, primary=False, group=case
    )


def test_no_resource_case_is_of_kind_time() -> None:
    assert all(model.resource_case(case).kind != "time" for case in model.RESOURCE_CASES)
    with pytest.raises(ValueError, match="not a resource case: 'res/made-up'"):
        model.resource_case("res/made-up")


def test_the_keys_of_the_usage_a_side_reports() -> None:
    assert api.USAGE_KEYS == (
        "rss_peak_bytes",
        "ctx_voluntary",
        "ctx_involuntary",
        "faults_major",
        "faults_minor",
    )
    assert api.LaunchOutcome(rc=0).usage == {}


def test_the_resource_cases_of_a_launch() -> None:
    outcome = api.LaunchOutcome(
        rc=0,
        timing={"run_s": 2.0, "launch_s": 2.0, "user_s": 3.0, "sys_s": 1.0},
        usage={
            "rss_peak_bytes": 4096,
            "ctx_voluntary": 5,
            "ctx_involuntary": 0,
            "faults_major": 0,
            "faults_minor": 7,
        },
    )
    samples = api.resource_samples(outcome)
    assert [(s.case, s.value) for s in samples] == [
        ("res/user", 3.0),
        ("res/sys", 1.0),
        ("res/cores", 2.0),
        ("res/rss_peak", 4096),
        ("res/ctx_voluntary", 5),
        ("res/ctx_involuntary", 0),
        ("res/faults_major", 0),
        ("res/faults_minor", 7),
    ]
    assert {s.better for s in samples} == {"none"}
    assert [(s.metric, s.unit, s.kind) for s in samples[:4]] == [
        ("user", "s", "other"),
        ("sys", "s", "other"),
        ("cores", "cores", "other"),
        ("rss_peak", "bytes", "other"),
    ]
    assert api.missing_resource_cases(samples) == ()


def test_cores_are_cpu_time_over_the_seconds_the_usage_covers() -> None:
    outcome = api.LaunchOutcome(rc=0, timing={"run_s": 10.0, "user_s": 3.0, "sys_s": 1.0})
    by_case = {s.case: s.value for s in api.resource_samples(outcome, seconds=2.0)}
    assert by_case["res/cores"] == 2.0
    assert {s.case: s.value for s in api.resource_samples(outcome)}["res/cores"] == 0.4


def test_a_figure_the_side_did_not_report_is_a_missing_case() -> None:
    outcome = api.LaunchOutcome(
        rc=0, timing={"run_s": 2.0, "user_s": 3.0}, usage={"rss_peak_bytes": 4096}
    )
    samples = api.resource_samples(outcome)
    assert [s.case for s in samples] == ["res/user", "res/rss_peak"]
    assert api.missing_resource_cases(samples) == (
        "res/sys",
        "res/cores",
        "res/ctx_voluntary",
        "res/ctx_involuntary",
        "res/faults_major",
        "res/faults_minor",
    )
    assert api.resource_samples(api.LaunchOutcome(rc=0)) == []


@pytest.mark.parametrize("timing", [{"user_s": 3.0, "sys_s": 1.0}, {"run_s": 0.0}])
def test_cores_need_a_length_above_zero(timing: dict[str, float]) -> None:
    outcome = api.LaunchOutcome(rc=0, timing={"user_s": 3.0, "sys_s": 1.0, **timing})
    assert "res/cores" not in {s.case for s in api.resource_samples(outcome)}


# ---------------------------------------------------------------------------
# The record a runner writes for a case
# ---------------------------------------------------------------------------


def test_a_resource_case_is_recorded_whatever_the_patterns_say() -> None:
    cases = CaseSettings(primary=("*",), groups={"everything": ("*",)})
    sample = api.resource_samples(
        api.LaunchOutcome(rc=0, timing={"run_s": 2.0, "user_s": 3.0, "sys_s": 1.0})
    )[2]
    assert api.case_of(sample, cases, []) == Case(
        id="res/cores",
        metric="cores",
        unit="cores",
        better="none",
        kind="other",
        primary=False,
        group="res/cores",
    )
    assert api.case_of(sample, cases, ["res/cores"]).primary is False


def test_a_case_is_recorded_with_the_patterns_and_the_default_of_the_driver() -> None:
    cases = CaseSettings(groups={"kernels": ("mat*",)})
    recorded = api.case_of(_sample("matmul"), cases, ["matmul"])
    assert (recorded.primary, recorded.group) == (True, "kernels")
    assert api.case_of(_sample("fft"), cases, ["matmul"]).primary is False
    late = api.case_of(_sample("matmul"), cases, ["matmul"], late=True)
    assert (late.primary, late.group) == (False, "kernels")


def test_a_describing_case_of_a_workload_is_recorded_as_secondary() -> None:
    sample = _sample("made-up-count", better="none", kind="count", unit="count")
    recorded = api.case_of(sample, CaseSettings(primary=("*",)), [])
    assert (recorded.better, recorded.primary) == ("none", False)
    with pytest.raises(Refusal, match="it cannot be a primary case"):
        api.case_of(sample, CaseSettings(primary=("made-up-count",)), [])
    assert api.case_of(sample, CaseSettings(primary=("made-up-count",)), [], late=True).primary is (
        False
    )


# ---------------------------------------------------------------------------
# The comparison and the verdict figure of a case that describes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("outcome", "word"), [("higher", "HIGHER"), ("lower", "LOWER")])
def test_the_results_carry_the_direction_of_a_describing_case(
    example_results: dict[str, Any], outcome: str, word: str
) -> None:
    example_results["cases"].append(
        {
            "id": "res/cores",
            "metric": "cores",
            "unit": "cores",
            "better": "none",
            "kind": "other",
            "primary": False,
            "group": "res/cores",
        }
    )
    comparison = dict(example_results["comparisons"][0])
    comparison.update(case="res/cores", primary=False, verdict=word, outcome=outcome)
    comparison["sensitivity"] = dict(comparison["sensitivity"], outcome=outcome)
    example_results["comparisons"].append(comparison)
    example_results["figures"]["res/cores.new_vs_old.verdict"] = {"value": outcome, "text": word}
    validator = jsonschema.Draft202012Validator(load_schema("results"))
    assert list(validator.iter_errors(example_results)) == []
    results = model.Results.from_json(example_results)
    described = results.comparison("res/cores")
    assert (described.verdict, described.outcome, described.primary) == (word, outcome, False)
    assert described.sensitivity.outcome == outcome
    figure = results.figures["res/cores.new_vs_old.verdict"]
    assert (figure.value, figure.text) == (outcome, word)
    written = results.to_json()
    assert written["figures"]["res/cores.new_vs_old.verdict"] == {"value": outcome, "text": word}
    assert written["comparisons"][1]["outcome"] == outcome
    assert model.Results.from_json(written) == results
    assert model.figure_key("res/cores", "new", "old", "verdict") == "res/cores.new_vs_old.verdict"


def test_a_word_outside_the_vocabulary_fails_schema_and_model(
    example_results: dict[str, Any],
) -> None:
    example_results["comparisons"][0].update(verdict="HIGHEST", outcome="highest")
    validator = jsonschema.Draft202012Validator(load_schema("results"))
    assert len(list(validator.iter_errors(example_results))) == 2
    with pytest.raises(Refusal) as caught:
        model.Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"
