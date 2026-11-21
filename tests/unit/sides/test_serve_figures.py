# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pieces of a serving launch that need no server: phases, answers, figures, GPU waits."""

from __future__ import annotations

import io
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from pairbench.errors import EXIT_LAUNCH, Refusal
from pairbench.model import ServeSpec
from pairbench.sides.serve import (
    BUILTIN_PHASES,
    LogReader,
    answer_text,
    cgroup_figures,
    parse_cgroup,
    phase_case,
    phase_patterns,
    phase_times,
    proc_stat_fields,
    session_delta,
    session_figures,
    wait_gpu_free,
    wait_memory_back,
)

# Lines of a server's output, read 1.5 s, 2.5 s and 9.0 s after a start at 100.0.
T0 = 100.0
LINES = (
    (101.5, "INFO Model loading took 2.0 GiB and 1.2 seconds"),
    (102.5, "INFO init engine (profile, create kv cache, warmup model) took 0.9 seconds"),
    (109.0, "INFO Starting vLLM server on http://0.0.0.0:8000"),
)
PHASES_SEEN = {"weights_loaded": 1.5, "engine_ready": 2.5, "server_started": 9.0}


def test_the_built_in_phases_apply_without_phases_of_the_config() -> None:
    patterns = phase_patterns(ServeSpec(image="x"))
    assert list(patterns) == ["weights_loaded", "engine_ready", "server_started"]
    assert {name: p.pattern for name, p in patterns.items()} == dict(BUILTIN_PHASES)


def test_each_phase_is_timed_by_when_its_line_was_read() -> None:
    found = phase_times(LINES, phase_patterns(ServeSpec(image="x")), T0)
    assert found == PHASES_SEEN


def test_the_first_matching_line_of_a_phase_wins() -> None:
    lines = ((100.25, "made-up ready one"), (100.75, "made-up ready two"))
    found = phase_times(lines, {"up": re.compile("ready")}, T0)
    assert found == {"up": 0.25}


class SlowPipe:
    """The read end of a pipe whose reader waits before it takes each line."""

    def __init__(self, fd: int, wait_s: float) -> None:
        self.fd = fd
        self.wait_s = wait_s

    def fileno(self) -> int:
        return self.fd

    def read1(self, _size: int = -1) -> bytes:
        time.sleep(self.wait_s)
        out = bytearray()
        while not out.endswith(b"\n"):
            byte = os.read(self.fd, 1)
            if not byte:
                break
            out += byte
        return bytes(out)


def test_the_mark_counts_what_waits_in_the_pipe_and_only_lines_before_it_count() -> None:
    read_end, write_end = os.pipe()
    try:
        os.write(write_end, b"made-up one\nmade-up two\n")
        reader = LogReader(SlowPipe(read_end, 0.05))  # type: ignore[arg-type]
        mark = reader.mark()
        os.write(write_end, b"made-up three\n")
        assert mark == 24
        assert reader.wait_for(mark, 10.0) is True
        assert [text for _stamp, text in reader.lines_before(mark)] == [
            "made-up one",
            "made-up two",
        ]
    finally:
        os.close(write_end)
    assert reader.join(10.0) is True
    assert [text for _stamp, text in reader.snapshot()] == [
        "made-up one",
        "made-up two",
        "made-up three",
    ]
    os.close(read_end)


def test_a_reader_of_a_stream_with_no_pipe_counts_what_it_has_read() -> None:
    reader = LogReader(io.BytesIO(b"made-up one\r\nmade-up two"))
    assert reader.join(10.0) is True
    assert reader.mark() == 24
    assert [text for _stamp, text in reader.lines_before(24)] == ["made-up one", "made-up two"]
    assert [text for _stamp, text in reader.lines_before(13)] == ["made-up one"]


def test_a_wait_for_output_the_reader_never_gets_ends_at_its_time_limit() -> None:
    read_end, write_end = os.pipe()
    try:
        os.write(write_end, b"made-up one\n")
        stream = os.fdopen(read_end, "rb")
        reader = LogReader(stream)
        mark = reader.mark()
        assert mark == 12
        started = time.monotonic()
        assert reader.wait_for(mark + 1, 0.2) is False
        assert time.monotonic() - started >= 0.2
        assert reader.wait_for(mark, 10.0) is True
    finally:
        os.close(write_end)
    assert reader.join(10.0) is True
    # Once the output ends, nothing more is waited for.
    assert reader.wait_for(mark + 1, 10.0) is True
    stream.close()


def test_a_phase_case_is_named_after_the_phase() -> None:
    assert phase_case("weights_loaded") == "startup/weights_loaded_s"


@pytest.mark.parametrize(
    ("event", "text"),
    [
        ({"choices": [{"delta": {"role": "assistant", "content": None}}]}, ""),
        ({"choices": [{"delta": {"content": ""}}]}, ""),
        ({"choices": [{"delta": {"content": "Hi"}}]}, "Hi"),
        ({"choices": [{"delta": {"reasoning_content": "hm"}}]}, "hm"),
        ({"choices": [{"text": "Hello"}]}, "Hello"),
        ({"choices": [{"message": {"content": "Hey"}}]}, "Hey"),
        ({"choices": []}, ""),
        ({"error": "made-up"}, ""),
        ([], ""),
    ],
)
def test_the_text_of_an_answer(event: object, text: str) -> None:
    assert answer_text(event) == text


# Two reads of a container's cgroup files (made-up values).
BEFORE = parse_cgroup(
    "usage_usec 9\nuser_usec 1000000\nsystem_usec 500000\npgfault 100\npgmajfault 4\n"
)
AFTER = parse_cgroup(
    "usage_usec 9\nuser_usec 3500000\nsystem_usec 750000\npgfault 160\npgmajfault 6\n"
)


def test_the_cgroup_reads_give_cpu_time_and_page_faults() -> None:
    timing, usage = cgroup_figures(BEFORE, AFTER)
    assert timing == {"user_s": 2.5, "sys_s": 0.25}
    assert usage == {"faults_major": 2.0, "faults_minor": 58.0}


def test_a_cgroup_figure_that_goes_down_or_is_missing_is_left_out() -> None:
    after = dict(AFTER, user_usec=10)
    del after["pgmajfault"]
    timing, usage = cgroup_figures(BEFORE, after)
    assert timing == {"sys_s": 0.25}
    assert usage == {}


def test_lines_of_a_cgroup_file_that_are_not_key_and_number_are_skipped() -> None:
    assert parse_cgroup("a 1\nb x\nc 2 3\n\nd 4\n") == {"a": 1, "d": 4}


def _stat(pid: int, name: str, session: int, numbers: Sequence[int]) -> str:
    # pid (comm) state ppid pgrp session tty tpgid flags minflt cminflt majflt
    # cmajflt utime stime cutime cstime and the rest.
    fields = ["S", "1", str(pid), str(session), "0", "-1", "0", *map(str, numbers), "20", "0"]
    return f"{pid} ({name}) " + " ".join(fields) + "\n"


def _status(voluntary: int, involuntary: int) -> str:
    return (
        f"Name:\tx\nvoluntary_ctxt_switches:\t{voluntary}\n"
        f"nonvoluntary_ctxt_switches:\t{involuntary}\n"
    )


def _proc(root: Path, pid: int, stat: str, status: str) -> None:
    folder = root / str(pid)
    folder.mkdir(parents=True)
    (folder / "stat").write_text(stat)
    (folder / "status").write_text(status)


def test_the_session_figures_sum_every_process_of_the_session(tmp_path: Path) -> None:
    # Two processes of session 77, one with a bracket in its name, and one of
    # another session that is left out.
    _proc(tmp_path, 77, _stat(77, "serve", 77, [10, 1, 2, 0, 300, 40, 5, 6]), _status(7, 3))
    _proc(tmp_path, 78, _stat(78, "a) b", 77, [20, 0, 1, 1, 100, 10, 0, 0]), _status(1, 1))
    _proc(tmp_path, 90, _stat(90, "other", 90, [99, 9, 9, 9, 999, 99, 9, 9]), _status(9, 9))
    (tmp_path / "self").mkdir()
    figures = session_figures(77, tmp_path)
    assert figures == {
        "user_ticks": 405,
        "sys_ticks": 56,
        "faults_minor": 31,
        "faults_major": 4,
        "ctx_voluntary": 8,
        "ctx_involuntary": 4,
    }


def test_a_session_with_no_process_gives_no_figures(tmp_path: Path) -> None:
    _proc(tmp_path, 90, _stat(90, "other", 90, [1] * 8), _status(1, 1))
    assert session_figures(77, tmp_path) is None
    assert session_figures(77, tmp_path / "missing") is None


def test_the_session_delta_turns_ticks_into_seconds() -> None:
    before = {"user_ticks": 100, "sys_ticks": 50, "faults_minor": 10, "ctx_voluntary": 4}
    after = {"user_ticks": 350, "sys_ticks": 40, "faults_minor": 25, "ctx_voluntary": 9}
    timing, usage = session_delta(before, after, 100.0)
    assert timing == {"user_s": 2.5}
    assert usage == {"faults_minor": 15.0, "ctx_voluntary": 5.0}


def test_a_stat_line_too_short_or_without_a_name_is_not_read() -> None:
    assert proc_stat_fields("12 (x) S 1 2") is None
    assert proc_stat_fields("no name here") is None


class Gpu:
    def __init__(self, counts: Sequence[int | None], memory: Sequence[float | None]) -> None:
        self.counts = list(counts)
        self.memory = list(memory)
        self.reads = 0

    def compute_processes(self, exclude_pids: Sequence[int] = ()) -> int | None:
        self.reads += 1
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    def memory_used_mib(self) -> float | None:
        self.reads += 1
        return self.memory.pop(0) if len(self.memory) > 1 else self.memory[0]


def test_the_gpu_free_wait_ends_when_the_other_process_leaves() -> None:
    gpu = Gpu([1, 1, 0], [0.0])
    assert wait_gpu_free(gpu, 5.0, 0.001) is True
    assert gpu.reads == 3


def test_the_gpu_free_wait_gives_up_after_its_time() -> None:
    assert wait_gpu_free(Gpu([1], [0.0]), 0.05, 0.01) is False


def test_an_unreadable_process_count_ends_the_wait_at_once() -> None:
    gpu = Gpu([None], [0.0])
    assert wait_gpu_free(gpu, 5.0, 0.01) is False
    assert gpu.reads == 1


def test_memory_back_within_the_tolerance_ends_the_release_wait() -> None:
    gpu = Gpu([0], [2000.0, 1100.0, 1064.0])
    wait_memory_back(gpu, 1000.0, tolerance_mib=64.0, timeout_s=5.0, poll_s=0.001)
    assert gpu.reads == 3


def test_memory_that_stays_up_is_refused_with_e_gpu_not_released() -> None:
    with pytest.raises(Refusal) as caught:
        wait_memory_back(
            Gpu([0], [1065.0]), 1000.0, tolerance_mib=64.0, timeout_s=0.05, poll_s=0.01
        )
    assert (caught.value.code, caught.value.exit_code) == ("E_GPU_NOT_RELEASED", EXIT_LAUNCH)
    assert caught.value.message == (
        "GPU memory in use stayed above its level before the start for 0.05 s after the "
        "server stopped"
    )


def test_memory_that_cannot_be_read_counts_as_not_released() -> None:
    with pytest.raises(Refusal) as caught:
        wait_memory_back(Gpu([0], [None]), 1000.0, tolerance_mib=64.0, timeout_s=0.05, poll_s=0.01)
    assert caught.value.detail["used_mib"] is None


def test_no_gpu_probe_means_nothing_to_wait_for() -> None:
    wait_memory_back(None, 1000.0, tolerance_mib=64.0, timeout_s=0.0, poll_s=0.01)
