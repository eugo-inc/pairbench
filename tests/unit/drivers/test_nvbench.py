# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The nvbench driver reads NVBench's JSON output, checked against a real run."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext, ToolVersion
from pairbench.drivers.nvbench import NvbenchDriver
from pairbench.errors import Refusal

MakeCtx = Callable[..., DriverContext]
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "drivers" / "nvbench" / "nvbench.json"
GENERATOR = Path(__file__).resolve().parents[2] / "fixtures" / "_gen" / "drivers.py"
OUTPUT = "nvbench.json"
GPU_MEAN = "nvbench.json: benchmarks[0]: states[0]: nv/cold/time/gpu/mean"


def _write(folder: Path, doc: Any) -> None:
    (folder / OUTPUT).write_text(json.dumps(doc), encoding="utf-8")


def _summary(tag: str, value: Any) -> dict[str, Any]:
    return {"tag": tag, "data": [{"name": "value", "type": "float64", "value": value}]}


def _doc(*states: dict[str, Any]) -> dict[str, Any]:
    return {"benchmarks": [{"name": "bench", "states": list(states)}]}


def _state(
    name: str = "Device=0", summaries: list[Any] | None = None, **extra: Any
) -> dict[str, Any]:
    if summaries is None:
        summaries = [_summary("nv/cold/time/gpu/mean", "0.5")]
    return {"name": name, "summaries": summaries, "is_skipped": False, **extra}


# The four states of the fixture from a real run, as the driver reads them: the
# mean GPU time and the mean CPU time of the cold measurement, in seconds, and
# the cold sample count, not the batch one.
REAL_RUN = [
    ("saxpy/Device=0 Elements=2^24", 0.0008641586857500361, 0.0008809553395522388, 1072),
    ("saxpy/Device=0 Elements=2^26", 0.0033766668494236277, 0.003393383294220664, 571),
    ("cub_sum/Device=0 Elements=2^24", 0.00035619395429437804, 0.0003740268686079549, 1408),
    ("cub_sum/Device=0 Elements=2^26", 0.0012312694129114046, 0.0012495464754901954, 816),
]


def test_the_fixture_from_a_real_run_gives_gpu_and_cpu_time_for_every_state(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURE, tmp_path / OUTPUT)
    driver = NvbenchDriver()
    samples = driver.read(make_ctx(), tmp_path)
    expected = []
    for case, gpu, cpu, count in REAL_RUN:
        expected.append((case, "gpu_time", "s", "lower", "time", gpu, count, "tool_summary"))
        expected.append(
            (f"{case}/cpu_time", "cpu_time", "s", "lower", "time", cpu, count, "tool_summary")
        )
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.value, s.n_inner, s.reducer) for s in samples
    ] == expected
    assert driver.default_primary(samples) == [case for case, _, _, _ in REAL_RUN]
    assert notes.seen == []
    assert driver.tool_version(make_ctx(), tmp_path) == ToolVersion("NVBench", "0.1.0", True)
    assert capsys.readouterr() == ("", "")


# What the fixture writer says it replaced, as its sidecar holds it.
REPLACED = (
    "devices: every hardware figure and the name replaced by made-up values, the id kept; "
    "each summary with the hint frequency (the mean SM clock rate) set to 1000000000; "
    "each nv/cold/sm_clock_rate/scaling/percent (the mean SM clock rate over the device's "
    "default clock rate) set to 1, the made-up clock rate over the made-up default clock rate; "
    "each nv/cold/bw/global/utilization (a share of the device's peak memory bandwidth) "
    "set to 0.5; "
    "the program's path in meta.argv[0] and meta.raw_argv[0] replaced by ./kernel_bench; "
    "every other measured time, count, rate and ratio kept as the run wrote it"
)


def test_the_fixture_from_a_real_run_names_its_image_and_nvbench_commit() -> None:
    sidecar = json.loads(FIXTURE.with_name(OUTPUT + ".provenance.json").read_text("utf-8"))
    assert sidecar["synthetic"] is False
    assert sidecar["image"] == (
        "docker.io/nvidia/cuda:13.4.3-devel-ubuntu24.04@sha256:"
        "5626a7d0ecafe3e7c115a452f6b05f20f214f8509346196a7835b205dc5b7fd9"
    )
    assert sidecar["nvbench_commit"] == "0f8eb2dd715f90e963a8ab0ff9374097110cc3f9"
    assert sidecar["command"] == (
        "./kernel_bench --min-samples 10 --timeout 2 --json /pairbench/artifacts/nvbench.json"
    )
    assert sidecar["replaced"] == REPLACED
    doc = json.loads(FIXTURE.read_text("utf-8"))
    assert doc["meta"]["argv"][0] == "./kernel_bench"
    assert doc["meta"]["version"]["nvbench"]["git_sha"] == sidecar["nvbench_commit"]
    assert [d["name"] for d in doc["devices"]] == ["made-up GPU"]


def test_the_fixture_from_a_real_run_holds_the_clock_ratio_its_made_up_clocks_give() -> None:
    doc = json.loads(FIXTURE.read_text("utf-8"))
    (device,) = doc["devices"]
    figures = [
        {s["tag"]: s["data"][0]["value"] for s in state["summaries"] if s["tag"] in (CLOCK, RATIO)}
        for bench in doc["benchmarks"]
        for state in bench["states"]
    ]
    assert figures == [{CLOCK: "1000000000", RATIO: "1"}] * 4
    assert device["sm_default_clock_rate"] == 1000000000
    for figure in figures:
        assert float(figure[RATIO]) * device["sm_default_clock_rate"] == float(figure[CLOCK])


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("pairbench_fixture_drivers", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A raw run as NVBench writes it, with made-up figures standing for a real device.
RAW_DEVICE = {
    "id": 0,
    "name": "Made-up Board 7",
    "sm_version": 777,
    "ptx_version": 777,
    "sm_default_clock_rate": 7777777,
    "number_of_sms": 77,
    "max_blocks_per_sm": 7,
    "max_threads_per_sm": 777,
    "max_threads_per_block": 777,
    "registers_per_sm": 7777,
    "registers_per_block": 7777,
    "global_memory_size": 77777777,
    "global_memory_bus_peak_clock_rate": 7777777,
    "global_memory_bus_width": 77,
    "global_memory_bus_bandwidth": 77777777,
    "l2_cache_size": 77777,
    "shared_memory_per_sm": 7777,
    "shared_memory_per_block": 7777,
    "ecc_state": True,
}


def _raw(argv0: str, axis: str = "7", extra: tuple[str, ...] = ()) -> dict[str, Any]:
    def summary(tag: str, hint: str, value: str) -> dict[str, Any]:
        return {
            "tag": tag,
            "hint": hint,
            "data": [{"name": "value", "type": "float64", "value": value}],
        }

    return {
        "meta": {
            "argv": [argv0, *extra, "--json", "/pairbench/artifacts/nvbench.json"],
            "raw_argv": [argv0, *extra, "--json", "/pairbench/artifacts/nvbench.json"],
        },
        "devices": [RAW_DEVICE],
        "benchmarks": [
            {
                "name": "bench",
                "states": [
                    {
                        "name": f"Device=0 N={axis}",
                        "axis_values": [{"name": "N", "type": "string", "value": axis}],
                        "summaries": [
                            summary("nv/cold/time/gpu/mean", "duration", "0.5"),
                            summary("nv/cold/bw/global/utilization", "percentage", "0.77"),
                            summary("nv/cold/sm_clock_rate/mean", "frequency", "7777777.7"),
                            summary("nv/cold/sm_clock_rate/scaling/percent", "percentage", "0.97"),
                        ],
                        "is_skipped": False,
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("program", ["/made/up/build/kernel_bench", "made/up/build/kernel_bench"])
def test_the_fixture_writer_replaces_what_describes_the_gpu_and_keeps_what_was_measured(
    tmp_path: Path, program: str
) -> None:
    _write(tmp_path, _raw(program))
    ((name, (text, extras)),) = _generator().nvbench(tmp_path).items()
    doc = json.loads(text)
    assert name == OUTPUT
    assert doc["meta"]["argv"] == ["./kernel_bench", "--json", "/pairbench/artifacts/nvbench.json"]
    assert doc["meta"]["raw_argv"] == doc["meta"]["argv"]
    (device,) = doc["devices"]
    assert device["name"] == "made-up GPU"
    assert sorted(device) == sorted(RAW_DEVICE)
    assert [key for key in RAW_DEVICE if device[key] == RAW_DEVICE[key]] == ["id"]
    values = {
        summary["tag"]: summary["data"][0]["value"]
        for summary in doc["benchmarks"][0]["states"][0]["summaries"]
    }
    assert values == {
        "nv/cold/time/gpu/mean": "0.5",
        "nv/cold/bw/global/utilization": "0.5",
        "nv/cold/sm_clock_rate/mean": "1000000000",
        "nv/cold/sm_clock_rate/scaling/percent": "1",
    }
    assert extras["command"] == (
        "./kernel_bench --min-samples 10 --timeout 2 --json /pairbench/artifacts/nvbench.json"
    )
    assert extras["replaced"] == REPLACED
    assert "7777" not in text
    assert "0.97" not in text
    assert "made/up" not in text


def test_the_generator_docstring_names_every_value_the_nvbench_writer_replaces() -> None:
    doc = " ".join((_generator().__doc__ or "").split())
    assert (
        "The device entry (its name and every hardware figure; the id stays), the mean SM clock "
        "rate, its ratio to the default clock rate and the share of peak memory bandwidth of each "
        "state, and the program's path are replaced by made-up values. Every other value is kept "
        "as the run wrote it, including those that describe the GPU: each state's GPU and CPU "
        "times, item rate and global-memory bandwidth in bytes per second."
    ) in doc


def test_the_fixture_writer_refuses_a_path_in_a_later_argument(tmp_path: Path) -> None:
    raw = _raw("/made/up/build/kernel_bench", extra=("--output", "/made/up/other.json"))
    _write(tmp_path, raw)
    with pytest.raises(SystemExit) as caught:
        _generator().nvbench(tmp_path)
    assert str(caught.value) == (
        "nvbench: paths outside the run folder are left: "
        "['/made/up/other.json', '/made/up/other.json']"
    )


def test_the_fixture_writer_refuses_a_path_in_brackets(tmp_path: Path) -> None:
    _write(tmp_path, _raw("/made/up/build/kernel_bench", axis="(/made/up/data.bin)"))
    with pytest.raises(SystemExit) as caught:
        _generator().nvbench(tmp_path)
    assert str(caught.value) == (
        "nvbench: paths outside the run folder are left: ['/made/up/data.bin', '/made/up/data.bin']"
    )


def test_the_fixture_writer_refuses_a_path_left_outside_the_run_folder(tmp_path: Path) -> None:
    _write(tmp_path, _raw("/made/up/build/kernel_bench", axis="/made/up/data.bin"))
    with pytest.raises(SystemExit) as caught:
        _generator().nvbench(tmp_path)
    assert str(caught.value) == (
        "nvbench: paths outside the run folder are left: ['/made/up/data.bin', '/made/up/data.bin']"
    )


LEFT = "nvbench: paths outside the run folder are left: "


def _refused(raw: dict[str, Any], folder: Path) -> Any:
    _write(folder, raw)
    with pytest.raises(SystemExit) as caught:
        _generator().nvbench(folder)
    return caught.value.code


# Each form of a path that does not stay in the run folder, as one argument of
# the command line NVBench records twice (meta.argv and meta.raw_argv).
@pytest.mark.parametrize(
    "argument",
    [
        "/pairbench/artifacts/../../made/up/data.bin",
        "/pairbench/artifacts/../artifacts/data.bin",
        "$HOME/made/up/data.bin",
        "${HOME}/made/up/data.bin",
        "$HOME",
        "${HOME}",
        "$_made_up",
        "-I$HOME",
        "~",
        "~made-up-user",
        "~/made/up/data.bin",
        "~made-up-user/data.bin",
        "made/up/data.bin",
        "./made/up/data.bin",
        "../../made/up/data.bin",
        "..",
        "-I/made/up/include",
        "-Imade/up/include",
        "/pairbench/artifactsX/data.bin",
    ],
)
def test_the_fixture_writer_refuses_each_form_of_a_path_outside_the_run_folder(
    tmp_path: Path, argument: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench", extra=(argument,))
    assert _refused(raw, tmp_path) == f"{LEFT}{[argument, argument]}"


def test_the_fixture_writer_refuses_a_command_substitution(tmp_path: Path) -> None:
    raw = _raw("/made/up/build/kernel_bench", extra=("$(pwd)",))
    assert _refused(raw, tmp_path) == f"{LEFT}{['$(pwd', '$(pwd']}"


def test_the_fixture_writer_refuses_a_path_after_an_equals_sign(tmp_path: Path) -> None:
    raw = _raw("/made/up/build/kernel_bench", extra=("--output=/made/up/other.json",))
    assert _refused(raw, tmp_path) == f"{LEFT}['/made/up/other.json', '/made/up/other.json']"


def test_the_fixture_writer_refuses_a_path_after_a_colon(tmp_path: Path) -> None:
    argument = "/pairbench/artifacts/made-up.json:/made/up/data.bin"
    raw = _raw("/made/up/build/kernel_bench", extra=(argument,))
    assert _refused(raw, tmp_path) == f"{LEFT}['/made/up/data.bin', '/made/up/data.bin']"


# Each character that ends a piece of a text, between a path in the run folder
# and one outside it.
SEPARATORS = [
    pytest.param(";", id="semicolon"),
    pytest.param(",", id="comma"),
    pytest.param("<", id="less-than"),
    pytest.param(">", id="greater-than"),
    pytest.param('"', id="double quote"),
    pytest.param("'", id="single quote"),
    pytest.param("[", id="opening bracket"),
    pytest.param("]", id="closing bracket"),
]


@pytest.mark.parametrize("separator", SEPARATORS)
def test_the_fixture_writer_refuses_a_path_after_each_separator(
    tmp_path: Path, separator: str
) -> None:
    argument = f"/pairbench/artifacts/made_up{separator}/made/up/data"
    raw = _raw("/made/up/build/kernel_bench", extra=(argument,))
    assert _refused(raw, tmp_path) == f"{LEFT}['/made/up/data', '/made/up/data']"


@pytest.mark.parametrize("separator", SEPARATORS)
def test_the_fixture_writer_keeps_two_paths_in_the_run_folder_joined_by_each_separator(
    tmp_path: Path, separator: str
) -> None:
    argument = f"/pairbench/artifacts/made_up{separator}/pairbench/artifacts/made_up_too"
    _write(tmp_path, _raw("/made/up/build/kernel_bench", extra=(argument,)))
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    assert json.loads(text)["meta"]["argv"][1] == argument


# Each character that is not a separator, glued between a path in the run folder
# and one outside it, and each other form that is not a plain path: the piece
# that starts at the run folder is refused whole.
@pytest.mark.parametrize(
    "argument",
    [
        *(
            pytest.param(f"/pairbench/artifacts/made_up{glue}/made/up/data", id=name)
            for glue, name in (
                ("|", "bar"),
                ("&", "ampersand"),
                ("@", "at sign"),
                ("#", "hash"),
                ("+", "plus"),
                ("{", "brace"),
                ("`", "backquote"),
                ("\\", "backslash"),
                ("!", "exclamation mark"),
                ("*", "asterisk"),
                ("?", "question mark"),
                ("%", "percent"),
                ("^", "caret"),
                ("$", "dollar"),
                ("\x00", "NUL"),
                ("\u200b", "zero width space"),
                ("\u2215", "division slash"),
                ("\uff0f", "fullwidth solidus"),
                ("\u2044", "fraction slash"),
            )
        ),
        pytest.param("/pairbench/artifacts/..%2F..%2Fmade%2Fup%2Fdata", id="percent-encoded /"),
        pytest.param("/pairbench/artifacts/made_up\\..\\..\\made\\up", id="backslash steps"),
        pytest.param("/pairbench/artifacts/..\u2215..\u2215made\u2215up", id="look-alike steps"),
        pytest.param("/pairbench/artifacts/m\u0430de_up.json", id="a letter outside ASCII"),
        pytest.param("/pairbench/artifacts/made_up\u0661.json", id="a digit outside ASCII"),
    ],
)
def test_the_fixture_writer_refuses_a_path_in_the_run_folder_that_is_not_plain(
    tmp_path: Path, argument: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench", extra=(argument,))
    assert _refused(raw, tmp_path) == f"{LEFT}{[argument, argument]}"


def test_the_fixture_writer_refuses_a_path_held_in_a_key(tmp_path: Path) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    raw["benchmarks"][0]["states"][0]["/made/up/data.bin"] = "7"
    assert _refused(raw, tmp_path) == f"{LEFT}['/made/up/data.bin']"


def _benchmark_name(raw: dict[str, Any]) -> None:
    raw["benchmarks"][0]["name"] = "made/up/data"


def _axis_description(raw: dict[str, Any]) -> None:
    raw["benchmarks"][0]["states"][0]["axis_values"][0]["description"] = "made/up/data"


def _key(raw: dict[str, Any]) -> None:
    raw["benchmarks"][0]["states"][0]["made/up/data"] = "7"


# Words joined by '/' pass only in a summary's own tag, name and description.
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_benchmark_name, id="a benchmark name"),
        pytest.param(_axis_description, id="an axis value's description"),
        pytest.param(_key, id="a key"),
    ],
)
def test_the_fixture_writer_refuses_words_joined_by_a_slash_outside_a_summary_text(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    change(raw)
    assert _refused(raw, tmp_path) == f"{LEFT}['made/up/data']"


def _summaries_in(*keys: str | int) -> Callable[[dict[str, Any]], None]:
    """Put a summaries list that holds words joined by '/' at the place KEYS name."""

    def change(raw: dict[str, Any]) -> None:
        node: Any = raw
        for key in keys:
            node = node[key]
        node["summaries"] = [{"tag": "made/up/data", "data": []}]

    return change


def _summaries_in_a_value(raw: dict[str, Any]) -> None:
    """Put a summaries list that holds words joined by '/' in the value of a data entry."""
    raw["benchmarks"][0]["states"][0]["summaries"][0]["data"][0]["value"] = {}
    _summaries_in("benchmarks", 0, "states", 0, "summaries", 0, "data", 0, "value")(raw)


def _states_in(*keys: str) -> Callable[[dict[str, Any]], None]:
    """Put a list of states whose summary holds words joined by '/' at the place KEYS name."""

    def change(raw: dict[str, Any]) -> None:
        node: Any = raw
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = [{"states": [{"summaries": [{"tag": "made/up/data", "data": []}]}]}]

    return change


# Words joined by '/' pass only in the summaries of a state, not in a list of
# that name anywhere else, nor in states that do not stand under the top-level
# benchmarks.
@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_states_in("meta", "benchmarks"), id="in benchmarks under meta"),
        pytest.param(_states_in("made_up"), id="in another list at the top level"),
        pytest.param(_summaries_in("meta"), id="in meta"),
        pytest.param(_summaries_in(), id="at the top level"),
        pytest.param(_summaries_in("benchmarks", 0), id="in a benchmark"),
        pytest.param(
            _summaries_in("benchmarks", 0, "states", 0, "axis_values", 0), id="in an axis value"
        ),
        pytest.param(_summaries_in_a_value, id="in the value of a summary's data entry"),
    ],
)
def test_the_fixture_writer_refuses_words_joined_by_a_slash_in_summaries_outside_a_state(
    tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    change(raw)
    assert _refused(raw, tmp_path) == f"{LEFT}['made/up/data']"


@pytest.mark.parametrize(
    ("field", "text", "left"),
    [
        ("description", "Bytes read from /made/up/data.bin", "/made/up/data.bin"),
        ("description", "Built with -I/made/up/include", "-I/made/up/include"),
        ("description", "Bytes read from made/up/data.bin", "made/up/data.bin"),
        ("description", "Bytes read from ./made/up", "./made/up"),
        ("name", "made/up/../data.bin", "made/up/../data.bin"),
        ("hint", "made/up/data", "made/up/data"),
        ("hide", "made/up/data", "made/up/data"),
    ],
)
def test_the_fixture_writer_refuses_a_path_in_a_summary_text(
    tmp_path: Path, field: str, text: str, left: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    raw["benchmarks"][0]["states"][0]["summaries"][0][field] = text
    assert _refused(raw, tmp_path) == f"{LEFT}{[left]}"


@pytest.mark.parametrize(
    "argument",
    [
        "/pairbench/artifacts",
        "/pairbench/artifacts/./made-up.json",
        "/pairbench//artifacts/made-up.json",
        "--output=/pairbench/artifacts/made-up.json",
        "/pairbench/artifacts/made-up.json:/pairbench/artifacts/made-up-too.json",
        "/pairbench/artifacts/made_up/Made-Up.2.json",
    ],
)
def test_the_fixture_writer_keeps_a_path_in_the_run_folder_in_any_spelling(
    tmp_path: Path, argument: str
) -> None:
    _write(tmp_path, _raw("/made/up/build/kernel_bench", extra=(argument,)))
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    assert json.loads(text)["meta"]["argv"][1] == argument


def test_the_fixture_writer_keeps_nvbench_s_own_summary_texts_that_hold_a_slash(
    tmp_path: Path,
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    summary = raw["benchmarks"][0]["states"][0]["summaries"][0]
    summary.update({"name": "Elem/s", "description": "Bytes read/written per second"})
    _write(tmp_path, raw)
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    kept = json.loads(text)["benchmarks"][0]["states"][0]["summaries"][0]
    assert (kept["tag"], kept["name"], kept["description"]) == (
        "nv/cold/time/gpu/mean",
        "Elem/s",
        "Bytes read/written per second",
    )


def test_the_fixture_writer_run_over_the_tracked_fixture_gives_it_back_byte_for_byte(
    tmp_path: Path,
) -> None:
    shutil.copy(FIXTURE, tmp_path / OUTPUT)
    ((name, (text, extras)),) = _generator().nvbench(tmp_path).items()
    sidecar = json.loads(FIXTURE.with_name(OUTPUT + ".provenance.json").read_text("utf-8"))
    assert name == OUTPUT
    assert text == FIXTURE.read_text("utf-8")
    assert (extras["command"], extras["replaced"]) == (sidecar["command"], sidecar["replaced"])


def test_the_sidecar_s_version_and_source_name_its_nvbench_commit() -> None:
    sidecar = json.loads(FIXTURE.with_name(OUTPUT + ".provenance.json").read_text("utf-8"))
    commit = sidecar["nvbench_commit"]
    assert (sidecar["version"], sidecar["source"]) == (
        f"0.1.0 (JSON file version 1.0.0), commit {commit}",
        f"https://github.com/NVIDIA/nvbench at commit {commit}",
    )


def test_the_fixture_writer_over_the_tracked_fixture_writes_its_sidecar_byte_for_byte(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw").mkdir()
    shutil.copy(FIXTURE, tmp_path / "raw" / OUTPUT)
    generator = _generator()
    generator.FIXTURES = tmp_path / "out"
    fixture, sidecar = generator.write("nvbench", tmp_path / "raw")
    assert (fixture, sidecar) == (
        tmp_path / "out" / "nvbench" / OUTPUT,
        tmp_path / "out" / "nvbench" / (OUTPUT + ".provenance.json"),
    )
    assert fixture.read_bytes() == FIXTURE.read_bytes()
    assert sidecar.read_bytes() == FIXTURE.with_name(OUTPUT + ".provenance.json").read_bytes()


# The generator's command line, run in a child process with its fixture folder
# pointed at the test's own folder, so a writer that does not refuse cannot
# touch the tracked fixtures.
WRAPPER = (
    "import importlib.util, pathlib, sys\n"
    "spec = importlib.util.spec_from_file_location('fixture_writer', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "module.FIXTURES = pathlib.Path(sys.argv[2])\n"
    "sys.exit(module.main(sys.argv[3:]))\n"
)


def _run_writer(folder: Path) -> tuple[int, str, str]:
    """Run ``drivers.py write nvbench raw`` in FOLDER; return the exit code and both streams."""
    out = str(folder / "out")
    done = subprocess.run(
        [sys.executable, "-B", "-c", WRAPPER, str(GENERATOR), out, "write", "nvbench", "raw"],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


CLOCK = "nv/cold/sm_clock_rate/mean"
SHARE = "nv/cold/bw/global/utilization"
RATIO = "nv/cold/sm_clock_rate/scaling/percent"


def _state_of(raw: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = raw["benchmarks"][0]["states"][0]
    return state


def _rename_the_clock_hint(raw: dict[str, Any]) -> None:
    for summary in _state_of(raw)["summaries"]:
        if summary["tag"] == CLOCK:
            summary["hint"] = "clock_rate"


def _drop_the_share(raw: dict[str, Any]) -> None:
    state = _state_of(raw)
    state["summaries"] = [s for s in state["summaries"] if s["tag"] != SHARE]


def _add_a_second_clock(raw: dict[str, Any]) -> None:
    (clock,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == CLOCK]
    _state_of(raw)["summaries"].append({**clock, "tag": "nv/batch/sm_clock_rate/mean"})


def _drop_the_clock_value_entry(raw: dict[str, Any]) -> None:
    (clock,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == CLOCK]
    clock["data"] = [{"name": "made_up", "type": "float64", "value": "7777777.7"}]


def _skip_the_state(raw: dict[str, Any]) -> None:
    _state_of(raw).update({"summaries": [], "is_skipped": True, "skip_reason": "made-up reason"})


def _data_beside(tag: str) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        (summary,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == tag]
        summary["data"].append({"name": "made_up", "type": "float64", "value": "7777777.7"})

    return change


def _rename_the_share(tag: str) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        (share,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == SHARE]
        share["tag"] = tag

    return change


def _add_a_second_share(raw: dict[str, Any]) -> None:
    (share,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == SHARE]
    _state_of(raw)["summaries"].append({**share, "tag": "nv/batch/bw/global/utilization"})


def _drop_the_ratio(raw: dict[str, Any]) -> None:
    state = _state_of(raw)
    state["summaries"] = [s for s in state["summaries"] if s["tag"] != RATIO]


def _rename_the_ratio(tag: str) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        (ratio,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == RATIO]
        ratio["tag"] = tag

    return change


def _add_a_second_ratio(raw: dict[str, Any]) -> None:
    (ratio,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == RATIO]
    _state_of(raw)["summaries"].append({**ratio, "tag": "nv/batch/sm_clock_rate/scaling/percent"})


FIRST = "benchmarks[0].states[0]"


def _counts(clocks: int, shares: int, ratios: int, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: values replaced under the hint frequency: {clocks}, "
        f"under a tag ending /bw/global/utilization: {shares}, under a tag ending "
        f"/sm_clock_rate/scaling/percent: {ratios}; each state needs exactly one of each, or a "
        "real clock rate, clock ratio or bandwidth share could stay in the fixture\n"
    )


# The made-up raw run's summaries: 0 the GPU time, 1 the bandwidth share, 2 the clock rate,
# 3 the clock ratio.
def _beside(index: int, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: a clock rate, clock ratio or bandwidth share summary holds data "
        f"other than its value: summaries[{index}] 'made_up'; only the value is replaced, so a "
        "real figure could stay in the fixture\n"
    )


# The made-up raw run's state holds four summaries, so one added to it is summaries[4].
def _cupti(tag: str, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: a summary NVBench measured with CUPTI: summaries[4] '{tag}'; the "
        "writer cannot vouch for a CUPTI figure, so a real figure of the device could stay in "
        "the fixture\n"
    )


# The summaries NVBench's CUPTI measurement writes, by tag, name and hint, as
# nvbench/detail/measure_cupti.cu sets them at commit
# 0f8eb2dd715f90e963a8ab0ff9374097110cc3f9:
# https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/nvbench/detail/measure_cupti.cu
CUPTI_SUMMARIES = [
    ("nv/cupti/dram__throughput.avg.pct_of_peak_sustained_elapsed", "HBWPeak", "percentage"),
    (
        "nv/cupti/smsp__sass_average_data_bytes_per_sector_mem_global_op_ld.pct",
        "LoadEff",
        "percentage",
    ),
    (
        "nv/cupti/smsp__sass_average_data_bytes_per_sector_mem_global_op_st.pct",
        "StoreEff",
        "percentage",
    ),
    ("nv/cupti/l1tex__t_sector_hit_rate.pct", "L1HitRate", "percentage"),
    ("nv/cupti/lts__t_sector_hit_rate.pct", "L2HitRate", "percentage"),
    ("nv/cupti/sample_size", "Samples", "sample_size"),
    ("nv/cupti/walltime", "Walltime", "duration"),
]


def _add_a_cupti_summary(tag: str, name: str, hint: str) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        _state_of(raw)["summaries"].append(
            {
                "tag": tag,
                "name": name,
                "hint": hint,
                "data": [{"name": "value", "type": "float64", "value": "0.77"}],
            }
        )

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(_rename_the_clock_hint, _counts(0, 1, 1), id="clock hint renamed"),
        pytest.param(_drop_the_share, _counts(1, 0, 1), id="no bandwidth share"),
        pytest.param(_add_a_second_clock, _counts(2, 1, 1), id="two clock summaries"),
        pytest.param(_drop_the_clock_value_entry, _counts(0, 1, 1), id="clock without a value"),
        pytest.param(_skip_the_state, _counts(0, 0, 0), id="skipped state"),
        pytest.param(_data_beside(CLOCK), _beside(2), id="data beside the clock value"),
        pytest.param(_data_beside(SHARE), _beside(1), id="data beside the share value"),
        pytest.param(_data_beside(RATIO), _beside(3), id="data beside the clock ratio value"),
        pytest.param(_add_a_second_share, _counts(1, 2, 1), id="a second share under nv/batch"),
        pytest.param(
            _rename_the_share("nv/cold/bw/global/utilization/made_up"),
            _counts(1, 0, 1),
            id="share tag with a step after utilization",
        ),
        pytest.param(
            _rename_the_share("nv/cold/bw/global/made_up_utilization"),
            _counts(1, 0, 1),
            id="share tag ending in a longer word",
        ),
        pytest.param(
            _rename_the_share("nv/cold/made_up/global/utilization"),
            _counts(1, 0, 1),
            id="share tag without its bw step",
        ),
        pytest.param(_drop_the_ratio, _counts(1, 1, 0), id="no clock ratio"),
        pytest.param(
            _add_a_second_ratio, _counts(1, 1, 2), id="a second clock ratio under nv/batch"
        ),
        pytest.param(
            _rename_the_ratio("nv/cold/sm_clock_rate/scaling/percent/made_up"),
            _counts(1, 1, 0),
            id="clock ratio tag with a step after percent",
        ),
        pytest.param(
            _rename_the_ratio("nv/cold/sm_clock_rate/scaling/made_up_percent"),
            _counts(1, 1, 0),
            id="clock ratio tag ending in a longer word",
        ),
        pytest.param(
            _rename_the_ratio("nv/cold/sm_clock_rate/made_up/percent"),
            _counts(1, 1, 0),
            id="clock ratio tag without its scaling step",
        ),
        pytest.param(
            _rename_the_ratio("nv/cold/made_up/scaling/percent"),
            _counts(1, 1, 0),
            id="clock ratio tag without its sm_clock_rate step",
        ),
    ],
)
def test_the_fixture_writer_refuses_unless_it_replaced_one_clock_and_one_share_in_each_state(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    change(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", message)
    assert not (tmp_path / "out").exists()


def test_the_fixture_writer_replaces_a_share_under_any_tag_that_ends_with_its_name(
    tmp_path: Path,
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _rename_the_share("nv/batch/bw/global/utilization")(raw)
    _write(tmp_path, raw)
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    values = {
        summary["tag"]: summary["data"][0]["value"]
        for summary in json.loads(text)["benchmarks"][0]["states"][0]["summaries"]
    }
    assert values["nv/batch/bw/global/utilization"] == "0.5"
    assert "0.77" not in text


def test_the_fixture_writer_replaces_a_clock_ratio_under_any_tag_that_ends_with_its_name(
    tmp_path: Path,
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _rename_the_ratio("nv/batch/sm_clock_rate/scaling/percent")(raw)
    _write(tmp_path, raw)
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    values = {
        summary["tag"]: summary["data"][0]["value"]
        for summary in json.loads(text)["benchmarks"][0]["states"][0]["summaries"]
    }
    assert values["nv/batch/sm_clock_rate/scaling/percent"] == "1"
    assert "0.97" not in text


@pytest.mark.parametrize(
    ("tag", "name", "hint"),
    [pytest.param(tag, name, hint, id=name) for tag, name, hint in CUPTI_SUMMARIES],
)
def test_the_fixture_writer_refuses_each_summary_nvbench_measures_with_cupti(
    tmp_path: Path, tag: str, name: str, hint: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _add_a_cupti_summary(tag, name, hint)(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", _cupti(tag))
    assert not (tmp_path / "out").exists()


def _a_look_alike(field: str, text: str) -> Callable[[dict[str, Any]], None]:
    """Put a summary with FIELD written as TEXT and a made-up figure beside the state's own."""

    def change(raw: dict[str, Any]) -> None:
        summary = {
            "tag": "nv/cold/made_up",
            "hint": "percentage",
            "data": [{"name": "value", "type": "float64", "value": "7777777.7"}],
        }
        summary[field] = text
        _state_of(raw)["summaries"].append(summary)

    return change


CLOCK_LIKE = "the hint frequency"
SHARE_LIKE = "a tag ending /bw/global/utilization"
RATIO_LIKE = "a tag ending /sm_clock_rate/scaling/percent"
CUPTI_LIKE = "a tag starting nv/cupti/"


# The made-up raw run's state holds four summaries, so the look-alike is summaries[4].
def _look_alike(field: str, shown: str, like: str, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: a tag or hint that differs only by case or a look-alike character "
        f"from one the writer looks for: summaries[4] {field} {shown} (like {like}); NVBench "
        "writes it exactly, so a real figure could stay in the fixture\n"
    )


def _outside(field: str, shown: str, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: a tag or hint with a character outside printable ASCII: "
        f"summaries[4] {field} {shown}; NVBench writes its tags and hints in printable ASCII, so "
        "a look-alike of one the writer looks for could keep a real figure in the fixture\n"
    )


# Each tag or hint that differs from one the writer looks for only by case or by
# a look-alike character, beside the state's own summaries, and how the refusal
# shows it: the field, the text with every character outside ASCII escaped, and
# the text it is like.
@pytest.mark.parametrize(
    ("field", "text", "shown", "like"),
    [
        pytest.param(
            "tag",
            "nv/cold/bw/global/Utilization",
            "'nv/cold/bw/global/Utilization'",
            SHARE_LIKE,
            id="share: a capital letter",
        ),
        pytest.param(
            "tag",
            "nv/cold/BW/global/utilization",
            "'nv/cold/BW/global/utilization'",
            SHARE_LIKE,
            id="share: capitals in an earlier step",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/\uff55tilization",
            "'nv/cold/bw/global/\\uff55tilization'",
            SHARE_LIKE,
            id="share: a fullwidth letter",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/\U0001d42etilization",
            "'nv/cold/bw/global/\\U0001d42etilization'",
            SHARE_LIKE,
            id="share: a mathematical bold letter",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw\uff0fglobal/utilization",
            "'nv/cold/bw\\uff0fglobal/utilization'",
            SHARE_LIKE,
            id="share: a fullwidth solidus",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw\u2044global/utilization",
            "'nv/cold/bw\\u2044global/utilization'",
            SHARE_LIKE,
            id="share: a fraction slash",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw\u2215global/utilization",
            "'nv/cold/bw\\u2215global/utilization'",
            SHARE_LIKE,
            id="share: a division slash",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw\u2571global/utilization",
            "'nv/cold/bw\\u2571global/utilization'",
            SHARE_LIKE,
            id="share: a box-drawing diagonal",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw\u29f8global/utilization",
            "'nv/cold/bw\\u29f8global/utilization'",
            SHARE_LIKE,
            id="share: a big solidus",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/g1obal/utilization",
            "'nv/cold/bw/g1obal/utilization'",
            SHARE_LIKE,
            id="share: a one for an l",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/gIobal/utilization",
            "'nv/cold/bw/gIobal/utilization'",
            SHARE_LIKE,
            id="share: a capital i for an l",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/g|obal/utilization",
            "'nv/cold/bw/g|obal/utilization'",
            SHARE_LIKE,
            id="share: a bar for an l",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/gl0bal/utilization",
            "'nv/cold/bw/gl0bal/utilization'",
            SHARE_LIKE,
            id="share: a zero for an o",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/UTlLlZATlON",
            "'nv/cold/bw/global/UTlLlZATlON'",
            SHARE_LIKE,
            id="share: in capitals, an l for each I",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/ut1lization",
            "'nv/cold/bw/global/ut1lization'",
            SHARE_LIKE,
            id="share: a one for an i",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm_clock_rate/scal|ng/percent",
            "'nv/cold/sm_clock_rate/scal|ng/percent'",
            RATIO_LIKE,
            id="clock ratio: a bar for an i",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/utilization ",
            "'nv/cold/bw/global/utilization '",
            SHARE_LIKE,
            id="share: a blank after it",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/utili\u200bzation",
            "'nv/cold/bw/global/utili\\u200bzation'",
            SHARE_LIKE,
            id="share: a zero width space",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/util\u00adization",
            "'nv/cold/bw/global/util\\xadization'",
            SHARE_LIKE,
            id="share: a soft hyphen",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/utilization\x00",
            "'nv/cold/bw/global/utilization\\x00'",
            SHARE_LIKE,
            id="share: a NUL after it",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm_clock_rate/scaling/Percent",
            "'nv/cold/sm_clock_rate/scaling/Percent'",
            RATIO_LIKE,
            id="clock ratio: a capital letter",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm\uff3fclock_rate/scaling/percent",
            "'nv/cold/sm\\uff3fclock_rate/scaling/percent'",
            RATIO_LIKE,
            id="clock ratio: a fullwidth low line",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm_cl0ck_rate/scaling/percent",
            "'nv/cold/sm_cl0ck_rate/scaling/percent'",
            RATIO_LIKE,
            id="clock ratio: a zero for an o",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm_clock_rate\u2215scaling/percent",
            "'nv/cold/sm_clock_rate\\u2215scaling/percent'",
            RATIO_LIKE,
            id="clock ratio: a division slash",
        ),
        pytest.param(
            "tag",
            "nv/cold/srn_clock_rate/scaling/percent",
            "'nv/cold/srn_clock_rate/scaling/percent'",
            RATIO_LIKE,
            id="clock ratio: 'rn' for an 'm'",
        ),
        pytest.param(
            "tag",
            "nv/cold/sRN_clock_rate/scaling/percent",
            "'nv/cold/sRN_clock_rate/scaling/percent'",
            RATIO_LIKE,
            id="clock ratio: 'RN' for an 'm'",
        ),
        pytest.param("hint", "Frequency", "'Frequency'", CLOCK_LIKE, id="hint: a capital letter"),
        pytest.param("hint", "FREQUENCY", "'FREQUENCY'", CLOCK_LIKE, id="hint: all capitals"),
        pytest.param("hint", "frequency ", "'frequency '", CLOCK_LIKE, id="hint: a blank after it"),
        pytest.param(
            "hint", " frequency", "' frequency'", CLOCK_LIKE, id="hint: a blank before it"
        ),
        pytest.param(
            "hint",
            "fre\u200bquency",
            "'fre\\u200bquency'",
            CLOCK_LIKE,
            id="hint: a zero width space",
        ),
        pytest.param(
            "hint",
            "\uff46requency",
            "'\\uff46requency'",
            CLOCK_LIKE,
            id="hint: a fullwidth letter",
        ),
        pytest.param(
            "hint", "frequency\t", "'frequency\\t'", CLOCK_LIKE, id="hint: a tab after it"
        ),
        pytest.param(
            "tag",
            "nv\u2215cupti\u2215walltime",
            "'nv\\u2215cupti\\u2215walltime'",
            CUPTI_LIKE,
            id="CUPTI: division slashes",
        ),
        pytest.param(
            "tag",
            "NV/CUPTI/walltime",
            "'NV/CUPTI/walltime'",
            CUPTI_LIKE,
            id="CUPTI: capitals",
        ),
        pytest.param(
            "tag",
            "NV/CUPTl/walltime",
            "'NV/CUPTl/walltime'",
            CUPTI_LIKE,
            id="CUPTI: in capitals, an l for the I",
        ),
        pytest.param(
            "tag",
            "nv/cupti\uff0fwalltime",
            "'nv/cupti\\uff0fwalltime'",
            CUPTI_LIKE,
            id="CUPTI: a fullwidth solidus",
        ),
    ],
)
def test_the_fixture_writer_refuses_a_tag_or_hint_that_only_looks_like_one_it_looks_for(
    tmp_path: Path, field: str, text: str, shown: str, like: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _a_look_alike(field, text)(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", _look_alike(field, shown, like))
    assert not (tmp_path / "out").exists()


# A tag or hint with a letter from another script that looks like an ASCII one,
# or any other character outside printable ASCII.
@pytest.mark.parametrize(
    ("field", "text", "shown"),
    [
        pytest.param(
            "tag",
            "nv/cold/bw/glob\u0430l/utilization",
            "'nv/cold/bw/glob\\u0430l/utilization'",
            id="share: a Cyrillic a",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/gl\u03bfbal/utilization",
            "'nv/cold/bw/gl\\u03bfbal/utilization'",
            id="share: a Greek omicron",
        ),
        pytest.param(
            "tag",
            "nv/cold/bw/global/ut\u0456lization",
            "'nv/cold/bw/global/ut\\u0456lization'",
            id="share: a Cyrillic i",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm_\u0441lock_rate/scaling/percent",
            "'nv/cold/sm_\\u0441lock_rate/scaling/percent'",
            id="clock ratio: a Cyrillic es",
        ),
        pytest.param("hint", "fr\u0435quency", "'fr\\u0435quency'", id="hint: a Cyrillic ie"),
        pytest.param(
            "hint",
            "frequency\u00e9",
            "'frequency\\xe9'",
            id="hint: longer than frequency, with an accent",
        ),
        pytest.param(
            "tag",
            "nv/cold/sm\u2010clock_rate/scaling/percent",
            "'nv/cold/sm\\u2010clock_rate/scaling/percent'",
            id="clock ratio: a hyphen for the low line",
        ),
        pytest.param(
            "tag", "nv/cold/made\u2024up", "'nv/cold/made\\u2024up'", id="another tag: a dot leader"
        ),
        pytest.param(
            "tag", "nv/cu\u0440ti/walltime", "'nv/cu\\u0440ti/walltime'", id="CUPTI: a Cyrillic er"
        ),
        pytest.param(
            "tag", "nv/cold/made_\u00e9", "'nv/cold/made_\\xe9'", id="another tag: an accent"
        ),
        pytest.param("tag", "nv/cold/made\tup", "'nv/cold/made\\tup'", id="another tag: a tab"),
        # A hint holds no '/', so no other rule of the writer refuses it: only the
        # printable-ASCII rule sees the character just past '~'.
        pytest.param(
            "hint", "made\x7fup", "'made\\x7fup'", id="another hint: the delete character"
        ),
    ],
)
def test_the_fixture_writer_refuses_a_tag_or_hint_outside_printable_ascii(
    tmp_path: Path, field: str, text: str, shown: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _a_look_alike(field, text)(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", _outside(field, shown))
    assert not (tmp_path / "out").exists()


# Hints at both ends of printable ASCII: a blank and a '~' are written as NVBench could
# write them, and the summary keeps its own figure.
@pytest.mark.parametrize("hint", ["made up", "made_up~"])
def test_the_fixture_writer_keeps_a_hint_at_either_end_of_printable_ascii(
    tmp_path: Path, hint: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    _a_look_alike("hint", hint)(raw)
    _write(tmp_path, raw)
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    summaries = json.loads(text)["benchmarks"][0]["states"][0]["summaries"]
    assert [(s["hint"], s["data"][0]["value"]) for s in summaries] == [
        ("duration", "0.5"),
        ("percentage", "0.5"),
        ("frequency", "1000000000"),
        ("percentage", "1"),
        (hint, "7777777.7"),
    ]


def _a_key_on(tag: str, key: str, entry: bool = False) -> Callable[[dict[str, Any]], None]:
    """Give the state's summary with TAG, or the value entry of its data, KEY with a figure."""

    def change(raw: dict[str, Any]) -> None:
        (summary,) = [s for s in _state_of(raw)["summaries"] if s["tag"] == tag]
        (summary["data"][0] if entry else summary)[key] = "7777777.7"

    return change


def _a_summary_keyed(key: str, text: str) -> Callable[[dict[str, Any]], None]:
    """Put a summary with a figure beside the state's own, with KEY holding TEXT."""

    def change(raw: dict[str, Any]) -> None:
        summary: dict[str, Any] = {
            "tag": "nv/cold/made_up",
            "hint": "percentage",
            "data": [{"name": "value", "type": "float64", "value": "7777777.7"}],
        }
        summary[key] = text
        _state_of(raw)["summaries"].append(summary)

    return change


def _two_keys(raw: dict[str, Any]) -> None:
    _a_key_on(SHARE, "made_up")(raw)
    _a_key_on(CLOCK, "made_up", entry=True)(raw)


def _keys(odd: str, where: str = FIRST) -> str:
    return (
        f"nvbench: {where}: a key NVBench does not write: {odd}; NVBench writes a summary "
        "with tag, name, description, hint, hide and data, and each data entry with name, "
        "type and value, so a figure under another key could stay in the fixture\n"
    )


def test_the_fixture_writer_reads_a_summary_with_every_key_nvbench_writes(tmp_path: Path) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    for summary in _state_of(raw)["summaries"]:
        summary.update(name="Made up", description="A made-up summary.", hide="Made up.")
    _write(tmp_path, raw)
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    summaries = json.loads(text)["benchmarks"][0]["states"][0]["summaries"]
    assert [sorted(s) for s in summaries] == [
        ["data", "description", "hide", "hint", "name", "tag"]
    ] * 4
    assert [sorted(s["data"][0]) for s in summaries] == [["name", "type", "value"]] * 4
    assert [s["data"][0]["value"] for s in summaries] == ["0.5", "0.5", "1000000000", "1"]


# A key NVBench's JSON printer does not write, in a summary or in an entry of its
# data: a figure beside a value the writer replaces, or a key that only looks like
# one the writer reads, which it would not read.
@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            _a_key_on(SHARE, "made_up"),
            _keys("summaries[1] 'made_up'"),
            id="a key beside the share's data",
        ),
        pytest.param(
            _a_key_on(CLOCK, "made_up"),
            _keys("summaries[2] 'made_up'"),
            id="a key beside the clock's data",
        ),
        pytest.param(
            _a_key_on(RATIO, "made_up"),
            _keys("summaries[3] 'made_up'"),
            id="a key beside the clock ratio's data",
        ),
        pytest.param(
            _a_key_on(CLOCK, "made_up", entry=True),
            _keys("summaries[2].data[0] 'made_up'"),
            id="a key beside the clock's value",
        ),
        pytest.param(
            _a_key_on("nv/cold/time/gpu/mean", "Value", entry=True),
            _keys("summaries[0].data[0] 'Value'"),
            id="a key Value beside a kept value",
        ),
        pytest.param(
            _a_summary_keyed("Hint", "frequency"),
            _keys("summaries[4] 'Hint'"),
            id="the hint key with a capital",
        ),
        pytest.param(
            _two_keys,
            _keys("summaries[1] 'made_up', summaries[2].data[0] 'made_up'"),
            id="a key on one summary and on another's value",
        ),
        pytest.param(
            _summaries_in("benchmarks", 0, "states", 0, "summaries", 0, "data", 0),
            _keys("summaries[0].data[0] 'summaries'"),
            id="a summaries list in a data entry",
        ),
        pytest.param(
            _a_summary_keyed("tag ", SHARE),
            _keys("summaries[4] 'tag '"),
            id="the tag key with a blank after it",
        ),
        pytest.param(
            _a_summary_keyed("h\u0456nt", "frequency"),
            _keys("summaries[4] 'h\\u0456nt'"),
            id="the hint key with a Cyrillic i",
        ),
    ],
)
def test_the_fixture_writer_refuses_a_key_nvbench_does_not_write(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    change(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", message)
    assert not (tmp_path / "out").exists()


def _raw_of_two_benchmarks() -> dict[str, Any]:
    """A made-up raw run of two benchmarks of two states each, every state as ``_raw`` holds it."""
    raw = _raw("/made/up/build/kernel_bench")
    raw["benchmarks"] = [
        {
            "name": name,
            "states": [
                _raw("/made/up/build/kernel_bench", axis=axis)["benchmarks"][0]["states"][0]
                for axis in ("7", "8")
            ],
        }
        for name in ("bench", "bench_too")
    ]
    return raw


def test_the_fixture_writer_replaces_the_clock_and_share_of_every_state_of_every_benchmark(
    tmp_path: Path,
) -> None:
    _write(tmp_path, _raw_of_two_benchmarks())
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    figures = [
        [
            (s["tag"], s["data"][0]["value"])
            for s in state["summaries"]
            if s["tag"] in (CLOCK, SHARE, RATIO)
        ]
        for bench in json.loads(text)["benchmarks"]
        for state in bench["states"]
    ]
    assert figures == [[(SHARE, "0.5"), (CLOCK, "1000000000"), (RATIO, "1")]] * 4
    assert "7777" not in text
    assert "0.77" not in text
    assert "0.97" not in text


def _in_state(
    b: int, s: int, change: Callable[[dict[str, Any]], None]
) -> Callable[[dict[str, Any]], None]:
    """Make CHANGE, written for the first state, apply to benchmarks[B].states[S]."""

    def apply(raw: dict[str, Any]) -> None:
        change({"benchmarks": [{"states": [raw["benchmarks"][b]["states"][s]]}]})

    return apply


CUPTI_DRAM = CUPTI_SUMMARIES[0]


# Each fault planted in a later state or a later benchmark of a raw run of two
# benchmarks of two states each; the states before it are whole.
@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            _in_state(0, 1, _drop_the_share),
            _counts(1, 0, 1, "benchmarks[0].states[1]"),
            id="no share in the second state",
        ),
        pytest.param(
            _in_state(1, 0, _drop_the_share),
            _counts(1, 0, 1, "benchmarks[1].states[0]"),
            id="no share in the second benchmark",
        ),
        pytest.param(
            _in_state(1, 1, _drop_the_share),
            _counts(1, 0, 1, "benchmarks[1].states[1]"),
            id="no share in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _rename_the_clock_hint),
            _counts(0, 1, 1, "benchmarks[1].states[1]"),
            id="clock hint renamed in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _drop_the_ratio),
            _counts(1, 1, 0, "benchmarks[1].states[1]"),
            id="no clock ratio in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _data_beside(RATIO)),
            _beside(3, "benchmarks[1].states[1]"),
            id="data beside the clock ratio in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _data_beside(SHARE)),
            _beside(1, "benchmarks[1].states[1]"),
            id="data beside the share in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _add_a_cupti_summary(*CUPTI_DRAM)),
            _cupti(CUPTI_DRAM[0], "benchmarks[1].states[1]"),
            id="a CUPTI summary in the last state",
        ),
        pytest.param(
            _in_state(1, 1, _a_key_on(SHARE, "made_up")),
            _keys("summaries[1] 'made_up'", "benchmarks[1].states[1]"),
            id="a key beside the share's data in the last state",
        ),
    ],
)
def test_the_fixture_writer_checks_every_state_of_every_benchmark(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = _raw_of_two_benchmarks()
    change(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", message)
    assert not (tmp_path / "out").exists()


def _raw_of_benchmarks(*counts: int) -> dict[str, Any]:
    """A made-up raw run of one benchmark per COUNT, each of that many states.

    Every state is as ``_raw`` holds it, with its own made-up clock rate, share
    and clock ratio: 7777771.7, 0.771 and 0.971 in the first state, 7777772.7,
    0.772 and 0.972 in the next, and so on.
    """
    raw = _raw("/made/up/build/kernel_bench")
    numbers = iter(range(1, sum(counts) + 1))
    benchmarks = []
    for b, count in enumerate(counts):
        states = []
        for _ in range(count):
            k = next(numbers)
            state = _raw("/made/up/build/kernel_bench", axis=str(k))["benchmarks"][0]["states"][0]
            for summary in state["summaries"]:
                if summary["tag"] == CLOCK:
                    summary["data"][0]["value"] = f"777777{k}.7"
                elif summary["tag"] == SHARE:
                    summary["data"][0]["value"] = f"0.77{k}"
                elif summary["tag"] == RATIO:
                    summary["data"][0]["value"] = f"0.97{k}"
            states.append(state)
        benchmarks.append({"name": f"bench_{b}", "states": states})
    raw["benchmarks"] = benchmarks
    return raw


# Three benchmarks of two, three and one states: a middle state, a third state
# and a third benchmark.
THREE_BENCHMARKS = (2, 3, 1)


def test_the_fixture_writer_replaces_the_clock_and_share_of_a_middle_and_a_third_state(
    tmp_path: Path,
) -> None:
    _write(tmp_path, _raw_of_benchmarks(*THREE_BENCHMARKS))
    ((_, (text, _)),) = _generator().nvbench(tmp_path).items()
    figures = [
        [
            (s["tag"], s["data"][0]["value"])
            for s in state["summaries"]
            if s["tag"] in (CLOCK, SHARE, RATIO)
        ]
        for bench in json.loads(text)["benchmarks"]
        for state in bench["states"]
    ]
    assert figures == [[(SHARE, "0.5"), (CLOCK, "1000000000"), (RATIO, "1")]] * 6
    assert "7777" not in text
    assert "0.77" not in text
    assert "0.97" not in text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            _in_state(1, 1, _drop_the_share),
            _counts(1, 0, 1, "benchmarks[1].states[1]"),
            id="no share in a middle state",
        ),
        pytest.param(
            _in_state(1, 2, _rename_the_clock_hint),
            _counts(0, 1, 1, "benchmarks[1].states[2]"),
            id="clock hint renamed in a third state",
        ),
        pytest.param(
            _in_state(2, 0, _drop_the_share),
            _counts(1, 0, 1, "benchmarks[2].states[0]"),
            id="no share in a third benchmark",
        ),
        pytest.param(
            _in_state(1, 1, _drop_the_ratio),
            _counts(1, 1, 0, "benchmarks[1].states[1]"),
            id="no clock ratio in a middle state",
        ),
        pytest.param(
            _in_state(2, 0, _add_a_second_ratio),
            _counts(1, 1, 2, "benchmarks[2].states[0]"),
            id="a second clock ratio in a third benchmark",
        ),
        pytest.param(
            _in_state(1, 1, _a_look_alike("tag", "nv/cold/bw/global/Utilization")),
            _look_alike(
                "tag",
                "'nv/cold/bw/global/Utilization'",
                SHARE_LIKE,
                "benchmarks[1].states[1]",
            ),
            id="a look-alike share tag in a middle state",
        ),
        pytest.param(
            _in_state(2, 0, _a_look_alike("hint", "Frequency")),
            _look_alike("hint", "'Frequency'", CLOCK_LIKE, "benchmarks[2].states[0]"),
            id="a look-alike clock hint in a third benchmark",
        ),
        pytest.param(
            _in_state(1, 2, _a_look_alike("tag", "nv/cold/bw/glob\u0430l/utilization")),
            _outside("tag", "'nv/cold/bw/glob\\u0430l/utilization'", "benchmarks[1].states[2]"),
            id="a tag outside ASCII in a third state",
        ),
    ],
)
def test_the_fixture_writer_checks_a_middle_state_and_a_third_benchmark(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = _raw_of_benchmarks(*THREE_BENCHMARKS)
    change(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", message)
    assert not (tmp_path / "out").exists()


def test_the_fixture_writer_refuses_a_path_through_its_command_line(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", _raw("/made/up/build/kernel_bench", extra=("$HOME/made-up",)))
    assert _run_writer(tmp_path) == (1, "", f"{LEFT}['$HOME/made-up', '$HOME/made-up']\n")
    assert not (tmp_path / "out").exists()


def _without(*keys: str | int) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        node: Any = raw
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]

    return change


def _set(value: Any, *keys: str | int) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        node: Any = raw
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value

    return change


def _no_id(raw: dict[str, Any]) -> None:
    raw["devices"] = [{key: value for key, value in RAW_DEVICE.items() if key != "id"}]


NOT_JSON = "nvbench: 'raw/nvbench.json' is not JSON\n"


# None: no raw folder; b"": a raw folder without nvbench.json; else the file's bytes.
@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(None, "nvbench: the raw folder 'raw' does not exist\n", id="no folder"),
        pytest.param(b"", "nvbench: the raw folder 'raw' holds no nvbench.json\n", id="no file"),
        pytest.param(b"{", NOT_JSON, id="cut short"),
        pytest.param(b"\xff", NOT_JSON, id="not UTF-8"),
        pytest.param(b"[]", "nvbench: 'raw/nvbench.json' is not a JSON object\n", id="a list"),
    ],
)
def test_the_fixture_writer_says_plainly_when_the_raw_output_is_missing(
    tmp_path: Path, content: bytes | None, message: str
) -> None:
    if content is not None:
        (tmp_path / "raw").mkdir()
    if content:
        (tmp_path / "raw" / OUTPUT).write_bytes(content)
    assert _run_writer(tmp_path) == (1, "", message)


def test_the_fixture_writer_says_plainly_when_the_raw_folder_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "raw").write_text("{}", encoding="utf-8")
    assert _run_writer(tmp_path) == (
        1,
        "",
        "nvbench: 'raw' is not a folder; name the folder that holds nvbench.json\n",
    )
    assert not (tmp_path / "out").exists()


ARGV = "nvbench: nvbench.json has no meta.argv list with the program's path first\n"
RAW_ARGV = "nvbench: nvbench.json has no meta.raw_argv list with the program's path first\n"


SUMMARIES = ("benchmarks", 0, "states", 0, "summaries")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(_without("meta"), ARGV, id="no meta"),
        pytest.param(_without("meta", "argv"), ARGV, id="no argv"),
        pytest.param(_set([], "meta", "argv"), ARGV, id="empty argv"),
        pytest.param(_without("meta", "raw_argv"), RAW_ARGV, id="no raw_argv"),
        pytest.param(_set("made-up", "meta", "raw_argv"), RAW_ARGV, id="raw_argv a text"),
        pytest.param(
            _without("devices"), "nvbench: nvbench.json has no devices list\n", id="no devices"
        ),
        pytest.param(_no_id, "nvbench: nvbench.json: devices[0] has no id\n", id="no device id"),
        pytest.param(
            _set(["made-up"], "devices"),
            "nvbench: nvbench.json: devices[0] is not an object\n",
            id="device a text",
        ),
        pytest.param(
            _without("benchmarks"),
            "nvbench: nvbench.json has no benchmarks list\n",
            id="no benchmarks",
        ),
        pytest.param(
            _set([], "benchmarks"),
            "nvbench: nvbench.json: the benchmarks list is empty; the writer needs a benchmark "
            "with a state to check\n",
            id="an empty benchmarks list",
        ),
        pytest.param(
            _without("benchmarks", 0, "states"),
            "nvbench: nvbench.json has no benchmarks[0].states list\n",
            id="no states",
        ),
        pytest.param(
            _set([], "benchmarks", 0, "states"),
            "nvbench: nvbench.json: the benchmarks[0].states list is empty; the writer needs a "
            "state in each benchmark to check\n",
            id="a benchmark with zero states",
        ),
        pytest.param(
            _set("made-up", "benchmarks", 0, "states", 0),
            "nvbench: nvbench.json: benchmarks[0].states[0] is not an object\n",
            id="state a text",
        ),
        pytest.param(
            _set("made-up", *SUMMARIES),
            "nvbench: nvbench.json has no benchmarks[0].states[0].summaries list\n",
            id="summaries a text",
        ),
        pytest.param(
            _set("made-up", *SUMMARIES, 0),
            "nvbench: nvbench.json: benchmarks[0].states[0].summaries[0] is not an object\n",
            id="summary a text",
        ),
        pytest.param(
            _set("made-up", *SUMMARIES, 0, "data"),
            "nvbench: nvbench.json has no benchmarks[0].states[0].summaries[0].data list\n",
            id="data a text",
        ),
        pytest.param(
            _set(7, *SUMMARIES, 1, "tag"),
            "nvbench: nvbench.json: benchmarks[0].states[0].summaries[1].tag is not a string\n",
            id="tag a number",
        ),
        pytest.param(
            _set(["frequency"], *SUMMARIES, 2, "hint"),
            "nvbench: nvbench.json: benchmarks[0].states[0].summaries[2].hint is not a string\n",
            id="hint a list",
        ),
    ],
)
def test_the_fixture_writer_says_plainly_what_the_raw_output_lacks(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = _raw("/made/up/build/kernel_bench")
    change(raw)
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (1, "", message)
    assert not (tmp_path / "out").exists()


def test_the_fixture_writer_refuses_a_third_benchmark_with_zero_states(tmp_path: Path) -> None:
    raw = _raw_of_benchmarks(*THREE_BENCHMARKS)
    raw["benchmarks"][2]["states"] = []
    (tmp_path / "raw").mkdir()
    _write(tmp_path / "raw", raw)
    assert _run_writer(tmp_path) == (
        1,
        "",
        "nvbench: nvbench.json: the benchmarks[2].states list is empty; the writer needs a "
        "state in each benchmark to check\n",
    )
    assert not (tmp_path / "out").exists()


# NVBench's own summary texts kept word for word in the fixture, under the
# NVBench program in the notices, with the licence NVBench's repository states.
NVBENCH_ROW = (
    "| NVBench | the `nvbench` driver reads its JSON output | Apache-2.0 with LLVM exceptions "
    "| <https://github.com/NVIDIA/nvbench> |"
)
NVBENCH_TEXTS_ROW = (
    "| NVBench's summary texts | `tests/fixtures/drivers/nvbench/nvbench.json` keeps the tag, "
    "name, description, hint and hide text of each summary word for word, as NVBench 0.1.0 at "
    "commit 0f8eb2dd715f90e963a8ab0ff9374097110cc3f9 writes them | Apache-2.0 with LLVM "
    "exceptions | <https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/"
    "LICENSE> |"
)


def test_the_notices_list_nvbench_s_own_texts_the_fixture_keeps_under_the_program(
    repo_root: Path,
) -> None:
    lines = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").splitlines()
    sidecar = json.loads(FIXTURE.with_name(OUTPUT + ".provenance.json").read_text("utf-8"))
    assert NVBENCH_ROW in lines
    assert lines[lines.index(NVBENCH_ROW) + 1] == NVBENCH_TEXTS_ROW
    assert f" commit {sidecar['nvbench_commit']} " in NVBENCH_TEXTS_ROW
    assert sidecar["version"].startswith("0.1.0 ")


def test_a_skipped_state_is_a_loud_note_and_is_missing_from_the_launch(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    skipped = _state(name="Device=0 Elements=4096", summaries=[], is_skipped=True)
    skipped["skip_reason"] = "made-up reason"
    _write(tmp_path, _doc(_timed_state("Device=0 Elements=1024"), skipped))
    samples = NvbenchDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.value) for s in samples] == [
        ("bench/Device=0 Elements=1024", 0.5),
        ("bench/Device=0 Elements=1024/cpu_time", 0.75),
    ]
    assert notes.seen == [
        (
            "case_skipped",
            "side 'new': NVBench skipped 'bench/Device=0 Elements=4096'; "
            "the case is missing from this launch",
        )
    ]
    assert capsys.readouterr() == ("", "")


def test_a_state_without_cpu_time_or_sample_size_gives_the_gpu_case_alone(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(tmp_path, _doc(_state()))
    samples = NvbenchDriver().read(make_ctx(), tmp_path)
    assert [(s.case, s.value, s.n_inner) for s in samples] == [("bench/Device=0", 0.5, 1)]


def test_a_state_without_a_name_is_named_by_its_benchmark(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(tmp_path, _doc(_state(name="")))
    assert [s.case for s in NvbenchDriver().read(make_ctx(), tmp_path)] == ["bench"]


def _timed_state(name: str) -> dict[str, Any]:
    return _state(
        name=name,
        summaries=[
            _summary("nv/cold/time/gpu/mean", "0.5"),
            _summary("nv/cold/time/cpu/mean", "0.75"),
        ],
    )


def test_a_string_axis_that_holds_a_file_address_keeps_its_file_once_the_runner_records_it(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        _doc(
            _timed_state("File=file:///made/up/home/a.bin"),
            _timed_state("File=sqlite:////made/up/home/b.db"),
        ),
    )
    driver = NvbenchDriver()
    samples = driver.read(make_ctx(), tmp_path)
    assert isinstance(driver, api.CleansCaseIds)
    assert [s.case for s in api.shown_cases(driver, samples, "side 'new'")] == [
        "bench/File=file://a.bin",
        "bench/File=file://a.bin/cpu_time",
        "bench/File=sqlite:///b.db",
        "bench/File=sqlite:///b.db/cpu_time",
    ]


def test_a_string_axis_that_holds_a_path_is_cut_before_the_cpu_time_part_is_added(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        _doc(
            _timed_state("Device=0 File=/made/up/home/a.bin"),
            _timed_state("Device=0 File=/made/up/home/b.bin"),
        ),
    )
    samples = NvbenchDriver().read(make_ctx(), tmp_path)
    assert [s.case for s in samples] == [
        "bench/Device=0 File=a.bin",
        "bench/Device=0 File=a.bin/cpu_time",
        "bench/Device=0 File=b.bin",
        "bench/Device=0 File=b.bin/cpu_time",
    ]
    assert api.public_cases(samples, "side 'new'") == samples


def test_two_states_that_differ_only_in_a_folder_are_refused(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        _doc(_timed_state("File=/made/up/v1/a.bin"), _timed_state("File=/made/up/v2/a.bin")),
    )
    with pytest.raises(Refusal) as caught:
        NvbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message.startswith("nvbench.json: two different cases")
    assert "'bench/File=a.bin'" in caught.value.message
    assert caught.value.message.endswith(
        "; give each state a name that differs outside its paths, absolute or climbing with "
        "'..', and outside its secrets"
    )
    assert "/made/up" not in caught.value.message


def test_doctor_says_what_the_driver_reads_and_does_not_mark_it_experimental() -> None:
    report = NvbenchDriver().doctor()
    assert (report.status, report.summary) == (
        "ok",
        "reads NVBench JSON output (--json), version 0.1",
    )


def test_prepare_adds_the_json_option(make_ctx: MakeCtx) -> None:
    assert NvbenchDriver().prepare(make_ctx(), ["./bench", "-d", "0"]).argv == (
        "./bench",
        "-d",
        "0",
        "--json",
        "/pairbench/artifacts/nvbench.json",
    )


def test_a_command_with_the_json_option_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        NvbenchDriver().prepare(make_ctx(), ["./bench", "--json", "stdout"])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"meta": {}}, "nvbench.json has no benchmarks"),
        ({"benchmarks": [{"name": "bench"}]}, "nvbench.json: benchmarks[0] has no states"),
        (
            _doc(_state(summaries=[])),
            "nvbench.json: benchmarks[0]: states[0]: the state 'bench/Device=0' has no summary "
            "nv/cold/time/gpu/mean",
        ),
        (
            _doc(_state(summaries=[_summary("nv/cold/time/gpu/mean", 0.5)])),
            f"{GPU_MEAN}: the value is not stored as a text",
        ),
        (
            _doc(_state(summaries=[_summary("nv/cold/time/gpu/mean", "fast")])),
            f"{GPU_MEAN}: the value 'fast' is not a number",
        ),
        (
            _doc(_state(summaries=[{"tag": "nv/cold/time/gpu/mean", "data": []}])),
            f"{GPU_MEAN}: no data entry named value",
        ),
        (
            _doc(_state(summaries=[_summary("nv/cold/time/gpu/mean", "inf")])),
            "case 'bench/Device=0': the value inf is not a finite number",
        ),
        (_doc(_state(), _state()), "nvbench.json: the case 'bench/Device=0' is given twice"),
        (_doc(_state(is_skipped=True)), "nvbench.json: the NVBench output holds no measured case"),
    ],
)
def test_a_malformed_file_is_refused(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, message: str
) -> None:
    _write(tmp_path, doc)
    with pytest.raises(Refusal) as caught:
        NvbenchDriver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_the_registry_loads_the_nvbench_driver() -> None:
    driver = registry.driver("nvbench")
    assert isinstance(driver, NvbenchDriver)
    assert (driver.name, driver.where) == ("nvbench", "in_side")
    assert isinstance(driver, api.Diagnosable)
    assert isinstance(driver, api.ReportsToolVersion)
