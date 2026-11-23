# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The mutation list: one-line changes to the source, each with the test that must fail.

Each entry names a file of the repository, under ``src/`` or ``tools/``, the
text to find (``old``, found exactly once in that file), the text to put in
its place (``new``, the same number of lines with exactly one line changed)
and the test that must fail once the change is applied. ``old`` may span
more than one line so that it is found only once; only one of its lines
changes. ``run_mutants.py`` applies each entry to a copy of the repository.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    """One change to the source and the test that must catch it."""

    id: str
    title: str
    file: str
    old: str
    new: str
    test: str


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        id="M01",
        title="count ties as trials",
        file="src/pairbench/stats/floor.py",
        old="            elif x > y:\n                higher += 1",
        new="            else:\n                higher += 1",
        test="tests/unit/stats/test_floor.py::test_a_tie_is_an_exactly_equal_pair_and_is_no_trial",
    ),
    Mutant(
        id="M02",
        title="drop the reversal from the schedule",
        file="src/pairbench/model.py",
        old="        order = tuple(reversed(order))",
        new="        order = tuple(order)",
        test="tests/unit/contracts/test_primitives.py::test_the_schedule_of_two_entries",
    ),
    Mutant(
        id="M03",
        title="turn < into <= in the significance check",
        file="src/pairbench/stats/rules.py",
        old="    return p <= rule.alpha if rule.p_inclusive else p < rule.alpha",
        new="    return p <= rule.alpha if rule.p_inclusive else p <= rule.alpha",
        test=(
            "tests/unit/stats/test_rules.py::"
            "test_a_p_value_equal_to_alpha_is_significant_only_when_inclusive"
        ),
    ),
    Mutant(
        id="M04",
        title="turn <= into < at the bar (a gap equal to the bar counts as outside it)",
        file="src/pairbench/stats/rules.py",
        old="    return gap >= bar if rule.gap_inclusive else gap > bar",
        new="    return gap >= bar if rule.gap_inclusive else gap >= bar",
        test=(
            "tests/unit/stats/test_rules.py::test_a_gap_equal_to_the_bar_is_inside_unless_inclusive"
        ),
    ),
    Mutant(
        id="M05",
        title="drop the monotone step in the correction",
        file="src/pairbench/stats/holm.py",
        old="        previous = max(previous, min(1.0, (m - rank) * values[index]))",
        new="        previous = min(1.0, (m - rank) * values[index])",
        test=(
            "tests/unit/stats/test_holm.py::"
            "test_the_running_maximum_keeps_a_larger_raw_value_from_a_smaller_adjustment"
        ),
    ),
    Mutant(
        id="M06",
        title="let a failed probe pass the quiet check",
        file="src/pairbench/gates/quiet.py",
        old="                and (probe is None or (gpu_n is not None and gpu_n == 0))",
        new="                and (probe is None or gpu_n is None or gpu_n == 0)",
        test=(
            "tests/unit/gates/test_quiet.py::"
            "test_mutant_a_failed_gpu_read_never_passes_the_quiet_check"
        ),
    ),
    Mutant(
        id="M07",
        title="proceed without a lock after a lock error",
        file="src/pairbench/gates/locks.py",
        old="                flock(fd, exclusive)\n                return fd",
        new=(
            "                with contextlib.suppress(OSError): flock(fd, exclusive)\n"
            "                return fd"
        ),
        test=(
            "tests/unit/gates/test_locks.py::test_mutant_a_lock_error_never_lets_the_run_proceed"
        ),
    ),
    Mutant(
        id="M08",
        title="skip the twin fingerprint check",
        file="src/pairbench/stats/analyse.py",
        old="        if twin.fingerprint != side.fingerprint:",
        new="        if False:",
        test=("tests/unit/stats/test_analyse.py::test_twin_drift_found_in_analysis_exits_with_six"),
    ),
    Mutant(
        id="M09",
        title="allow a pull during a round",
        file="src/pairbench/sides/container.py",
        old=(
            '            f"{RUN_LABEL}={request.run_id}",\n'
            '            "--pull",\n'
            '            "never",'
        ),
        new=(
            '            f"{RUN_LABEL}={request.run_id}",\n'
            '            "--pull",\n'
            '            "missing",'
        ),
        test=(
            "tests/unit/sides/test_container.py::test_a_launch_never_pulls_and_starts_by_image_id"
        ),
    ),
    Mutant(
        id="M10",
        title="let the decision to set a round aside read a measured value",
        file="src/pairbench/model.py",
        old=(
            "            RoundWitness(round=x.round, name=x.name, "
            "witness=Witness.from_json(x.witness))"
        ),
        new=(
            "            RoundWitness(round=x.round, name=x.name, witness=Witness.from_json("
            '{**x.witness, "busy_cores": x.timing.get("run_s")}))'
        ),
        test=(
            "tests/unit/gates/test_discard.py::"
            "test_mutant_the_decision_to_set_a_round_aside_reads_no_measured_value"
        ),
    ),
    Mutant(
        id="M11",
        title="write a host name into the results",
        file="src/pairbench/results/writer.py",
        old="    markdown = MarkdownReporter().render(written, ReportOptions())",
        new=(
            "    markdown = MarkdownReporter().render(written, ReportOptions())"
            ' + __import__("socket").gethostname()'
        ),
        test=(
            "tests/unit/results/test_privacy.py::"
            "test_no_results_file_holds_what_identifies_the_machine"
        ),
    ),
    Mutant(
        id="M12",
        title="accept a capture without an end record",
        file="src/pairbench/stats/analyse.py",
        old="    if capture.complete:\n        return\n    end = capture.end",
        new="    if True:\n        return\n    end = capture.end",
        test=(
            "tests/unit/stats/test_analyse.py::test_an_incomplete_capture_is_refused_unless_allowed"
        ),
    ),
    Mutant(
        id="M13",
        title="pool the same file twice",
        file="src/pairbench/stats/analyse.py",
        old="        if first.path is not None and first.path == second.path:",
        new="        if False:",
        test=(
            "tests/unit/stats/test_analyse.py::"
            "test_the_same_path_twice_is_the_same_file_whatever_its_hash"
        ),
    ),
    Mutant(
        id="M14",
        title="treat a missing figure as empty text",
        file="src/pairbench/report/fill.py",
        old="            if token.shown not in missing:",
        new='            if texts.setdefault(token.text, "") is None:',
        test="tests/unit/report/test_fill.py::test_one_missing_key_is_named",
    ),
    Mutant(
        id="M15",
        title="pass the positive control whatever ratio it reads",
        file="src/pairbench/stats/analyse.py",
        old=(
            "    passed = control_within(ratio, expected, tolerance) and direction "
            "and is_significant(p, rule)"
        ),
        new="    passed = direction and is_significant(p, rule)",
        test="tests/unit/stats/test_selftest.py::test_each_control_passes[C15]",
    ),
    Mutant(
        id="M16",
        title="give the launch-cost note with the share turned upside down",
        file="src/pairbench/model.py",
        old="    return median_s < cost_median_s / note_share",
        new="    return median_s < cost_median_s * note_share",
        test=(
            "tests/unit/stats/test_analyse.py::test_the_launch_cost_note_follows_the_recorded_share"
        ),
    ),
    Mutant(
        id="M17",
        title="write a text from a run into the report page without escaping it",
        file="src/pairbench/page/html.py",
        old="    return html.escape(str(value), quote=True).translate(_AS_REFERENCES)",
        new="    return str(value)",
        test=(
            "tests/unit/page/test_page_safety.py::"
            "test_text_from_a_run_becomes_no_markup_and_no_address"
        ),
    ),
    Mutant(
        id="M18",
        title="record a credential-like variable's value",
        file="src/pairbench/model.py",
        old="            return True\n    return False\n\n\ndef redact_env",
        new="            return False\n    return False\n\n\ndef redact_env",
        test=(
            "tests/unit/config/test_config.py::"
            "test_credential_like_values_are_redacted_in_the_resolved_config"
        ),
    ),
    Mutant(
        id="M19",
        title="exit 0 when a primary case has an outcome named by --fail-on",
        file="src/pairbench/cli/common.py",
        old="    return EXIT_CHECK_FAILED if matched else EXIT_OK",
        new="    return EXIT_OK",
        test=(
            "tests/unit/cli/test_run.py::test_fail_on_a_primary_outcome_exits_1_and_names_the_case"
        ),
    ),
    Mutant(
        id="M20",
        title="leave the results of an interrupted run saying pending",
        file="src/pairbench/cli/run.py",
        old="        write_results(finish.results(html=False).interrupted(), folder)",
        new="        write_results(finish.results(html=False), folder)",
        test=(
            "tests/unit/cli/test_run.py::"
            "test_an_interrupt_after_the_first_write_writes_interrupted_and_exits_130"
        ),
    ),
    Mutant(
        id="M21",
        title="skip the twin fingerprint check as the run starts",
        file="src/pairbench/runner.py",
        old="        if side.twin().fingerprint != side.fingerprint:",
        new="        if False:",
        test=(
            "tests/unit/runner/test_runner.py::"
            "test_a_twin_with_another_fingerprint_is_refused_as_the_run_starts"
        ),
    ),
    Mutant(
        id="M22",
        title="make the owner-only pass do nothing",
        file="src/pairbench/sides/base.py",
        old="    if not callable(getuid) or not _CAN_WALK:",
        new="    if True:",
        test=(
            "tests/unit/sides/test_run_file_modes.py::"
            "test_the_files_a_launch_leaves_lose_the_group_s_and_others_permissions"
        ),
    ),
    Mutant(
        id="M23",
        title="narrow a file another user owns in the owner-only pass",
        file="src/pairbench/sides/base.py",
        old="        and found.st_uid == uid",
        new="        and True",
        test="tests/unit/sides/test_run_file_modes.py::test_a_file_another_user_owns_keeps_its_mode",
    ),
    Mutant(
        id="M24",
        title="follow a link on the way down from the run folder",
        file="src/pairbench/sides/base.py",
        old='_OPEN_FOLDER: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _OPEN_AS_FOUND',
        new='_OPEN_FOLDER: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)',
        test=(
            "tests/unit/sides/test_run_file_modes.py::"
            "test_a_folder_above_a_launch_folder_replaced_by_a_link_leaves_what_it_names_alone"
        ),
    ),
    Mutant(
        id="M25",
        title="skip the owner-only pass after a timed launch",
        file="src/pairbench/runner.py",
        old=(
            "            # it, and also when one of them fails to stop.\n"
            "            make_owner_only(artifacts, within=self.held)"
        ),
        new="            # it, and also when one of them fails to stop.\n            pass",
        test=(
            "tests/unit/runner/test_launch_file_modes.py::"
            "test_every_file_the_launches_of_a_run_leave_is_owner_only_whatever_the_umask"
        ),
    ),
    Mutant(
        id="M26",
        title="skip the owner-only pass after a stopped timed launch",
        file="src/pairbench/runner.py",
        old="            make_owner_only(artifacts, within=self.held)\n            raise",
        new="            pass\n            raise",
        test=(
            "tests/unit/runner/test_launch_file_modes.py::"
            "test_a_launch_that_is_interrupted_leaves_its_files_owner_only"
        ),
    ),
    Mutant(
        id="M27",
        title="open a file of the owner-only pass through a link",
        file="src/pairbench/sides/base.py",
        old=(
            '    getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) '
            '| getattr(os, "O_NOCTTY", 0)'
        ),
        new='    0 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)',
        test=(
            "tests/unit/sides/test_run_file_modes.py::"
            "test_a_file_swapped_while_the_pass_runs_leaves_what_takes_its_place_alone"
        ),
    ),
    Mutant(
        id="M28",
        title="drop the check of the opened file in the owner-only pass",
        file="src/pairbench/sides/base.py",
        old="            if _others_may_use(opened, uid):",
        new="            if True:",
        test=(
            "tests/unit/sides/test_run_file_modes.py::"
            "test_a_file_swapped_while_the_pass_runs_leaves_what_takes_its_place_alone"
        ),
    ),
    Mutant(
        id="M29",
        title="skip the hand-back of a stopped container launch",
        file="src/pairbench/sides/container.py",
        old=(
            "            self._hand_back("
            "request.artifacts, request.seq, request.name, stopped=True)"
        ),
        new="            pass",
        test=(
            "tests/unit/sides/test_container.py::"
            "test_an_interrupted_launch_hands_its_files_back_after_removing_its_container"
        ),
    ),
    Mutant(
        id="M30",
        title="walk on from wherever the owner-only pass comes back up to",
        file="src/pairbench/sides/base.py",
        old="            if _identity(here) != open_folders[-1][0]:",
        new="            if False:",
        test=(
            "tests/unit/sides/test_run_file_modes.py::"
            "test_a_folder_moved_away_while_the_pass_runs_takes_the_pass_no_further"
        ),
    ),
    Mutant(
        id="M31",
        title="skip the hand-back of a stopped serving launch",
        file="src/pairbench/sides/serve.py",
        old="                self._hand_back(handle, request.artifacts, stopped=True)",
        new="                pass",
        test=(
            "tests/unit/sides/test_serve_hand_back.py::"
            "test_a_serving_launch_interrupted_while_its_server_stops_hands_its_files_back"
        ),
    ),
    Mutant(
        id="M32",
        title="skip the hand-back of a serving start cut short",
        file="src/pairbench/sides/serve.py",
        old="                give_back_after_stop(give_back, ctx.note, side, artifacts)",
        new="                pass",
        test=(
            "tests/unit/sides/test_serve_hand_back.py::"
            "test_a_serving_start_stopped_after_the_engine_runs_removes_the_server_and_hands_back"
        ),
    ),
    Mutant(
        id="M33",
        title="publish a sidecar that cannot be shared",
        file="tools/hash_inputs.py",
        old="        if (folder / name).is_file() and (sidecar or name != SIDECAR)",
        new="        if (folder / name).is_file()",
        test=(
            "tests/unit/docs/test_hash_inputs.py::"
            "test_publish_mode_copies_the_three_shared_files_and_keeps_a_private_sidecar_in_the_run"
        ),
    ),
    Mutant(
        id="M34",
        title="judge the twin note on the uncorrected p-value of a side",
        file="src/pairbench/stats/rules.py",
        old="            if check.p_corrected is not None and check.p_corrected < TWIN_NOTE_ALPHA",
        new="            if check.p_raw is not None and check.p_raw < TWIN_NOTE_ALPHA",
        test=(
            "tests/unit/stats/test_rules.py::"
            "test_rounds_whose_combined_score_is_zero_are_ties_and_dropped"
        ),
    ),
    Mutant(
        id="M35",
        title="score a twin round by the mean of its primary cases",
        file="src/pairbench/stats/rules.py",
        old="            sign = _median_sign(terms)",
        new="            sign = _round_sign(terms)",
        test="tests/unit/stats/test_rules.py::test_a_round_is_scored_by_the_median_of_its_primary_cases",
    ),
)
