# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Generate the fixtures of the driver tests.

Every driver but ``wall`` has fixtures from a real run of the tool it reads,
each in a short container of a public image. The programs the runs measured
are written below (``program`` prints one) or named, and so are the commands.
``write`` reads the raw output of such a run from a folder, replaces the fields
listed below with visibly synthetic values, and writes the fixtures into
``tests/fixtures/drivers/<tool>/``, each with a ``*.provenance.json`` sidecar
that names what was replaced::

    python tests/fixtures/_gen/drivers.py program gbench > bench.cc
    python tests/fixtures/_gen/drivers.py write gbench RAW_FOLDER

What ``write`` replaces, by tool: for ``gbench``, the date, host name, CPU
count, clock rate, caches and load average of the context; for
``pytest-benchmark``, the machine information and the date; for ``hyperfine``,
the start time and the platform of the newer layout, and nothing in the older
one; for ``perf``, the start line; for ``llama-bench``, the model's path, the
test time and the CPU's name; for ``lines``, nothing. Everything else is kept
as the run wrote it: every measured time, count, rate and ratio, and with them
values that describe the machine, among them the PMU names ``perf stat``
prints, the GHz and instructions per cycle it derives from its counters,
whether Google Benchmark saw CPU frequency scaling on, and the backends
``llama-bench`` used.

``nvbench`` reads ``nvbench.json`` from RAW_FOLDER: the output of one run of
the gpu-kernel showcase's ``kernel_bench`` on one NVIDIA GPU, built inside the
showcase's pinned CUDA development image by its ``build.sh`` (which pins the
NVBench commit and the CMake release), and run with ``NVBENCH_OPTIONS`` and
``--json`` into the folder a launch gives the driver. The device entry (its
name and every hardware figure; the id stays), the mean SM clock rate and the
share of peak memory bandwidth of each state, and the program's path are
replaced by made-up values. Every other value is kept as the run wrote it,
including those that describe the GPU: each state's GPU and CPU times, item
rate, global-memory bandwidth in bytes per second and clock scaling. A path
left outside the run folder stops the writer, and so does a path in the run
folder with a step that is not plain (ASCII letters, digits, '.', '_' and '-'),
a state in which it did not replace exactly one mean clock rate and one share
of peak memory bandwidth, or in which either summary holds data beside the
value it replaces, and a summary NVBench measured with CUPTI (a tag that starts
with nv/cupti/), whose figures the writer cannot vouch for. Its sidecar names
the image with its digest, the NVBench commit, the command and what was
replaced.

``wall`` reads no file and has no fixture.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "drivers"
GENERATOR = "tests/fixtures/_gen/drivers.py"
SYNTHETIC_DATE = "2000-01-01T00:00:00+00:00"
SYNTHETIC_HOST = "host-a"

GBENCH_PROGRAM = """\
// A tiny Google Benchmark program for a fixture: two families, one with
// arguments, one reported in microseconds, and one that skips with an error.
#include <benchmark/benchmark.h>

#include <numeric>
#include <string>
#include <vector>

static void BM_vector_sum(benchmark::State& state) {
  std::vector<int> v(static_cast<size_t>(state.range(0)), 1);
  for (auto _ : state) {
    benchmark::DoNotOptimize(std::accumulate(v.begin(), v.end(), 0));
  }
}
BENCHMARK(BM_vector_sum)->Arg(64)->Arg(4096);

static void BM_string_build(benchmark::State& state) {
  for (auto _ : state) {
    std::string s;
    for (int i = 0; i < 256; ++i) s += 'x';
    benchmark::DoNotOptimize(s);
  }
}
BENCHMARK(BM_string_build)->Unit(benchmark::kMicrosecond);

static void BM_needs_a_file(benchmark::State& state) {
  state.SkipWithError("made-up reason: the input file is absent");
  for (auto _ : state) {
  }
}
BENCHMARK(BM_needs_a_file);

BENCHMARK_MAIN();
"""

PYTEST_BENCHMARK_PROGRAM = '''\
"""Two tiny benchmarks for a fixture, one of them parametrised."""

import pytest


def build_list(n):
    return [i * i for i in range(n)]


@pytest.mark.parametrize("n", [16, 256])
def test_build_list(benchmark, n):
    benchmark(build_list, n)


def test_join_text(benchmark):
    benchmark("-".join, ["x"] * 128)
'''

LINES_PROGRAM = (
    '''\
"""A tiny workload that times its own work and prints pairbench lines."""

import random
import time

rng = random.Random(7)
values = [rng.random() for _ in range(200_000)]

print("preparing: this line is ignored by the reader")
start = time.perf_counter()
ordered = sorted(values)
sort_s = time.perf_counter() - start
print(f'::pairbench:: {{"case": "sort", "value": {sort_s!r}}}')

start = time.perf_counter()
total = sum(ordered)
sum_s = time.perf_counter() - start
print(f'::pairbench:: {{"case": "sum", "value": {sum_s * 1000.0!r}, "unit": "ms"}}')
print(
    f'::pairbench:: {{"case": "items_per_s", "value": {len(values) / sort_s!r}, '
    '"unit": "items/s", "better": "higher"}'
)
print(f'::pairbench:: {{"case": "items", "value": {len(values)}, '''
    """"unit": "count", "better": "none"}}')
print(f"done: total {total:.3f}")
"""
)

PROGRAMS = {
    "gbench": GBENCH_PROGRAM,
    "pytest-benchmark": PYTEST_BENCHMARK_PROGRAM,
    "lines": LINES_PROGRAM,
}

DEBIAN = (
    "debian:trixie-slim@sha256:"
    + "a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2"
)
PYTHON = (
    "python:3.12-slim@sha256:" + "5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"
)
UBUNTU = "ubuntu:24.04@sha256:" + "2198e4c65076e9cb0b3d695219df667c0e3b0072da64ca3c2648aca17dcecaf5"
CUDA = (
    "docker.io/nvidia/cuda:13.4.3-devel-ubuntu24.04@sha256:"
    + "5626a7d0ecafe3e7c115a452f6b05f20f214f8509346196a7835b205dc5b7fd9"
)
NVBENCH_COMMIT = "0f8eb2dd715f90e963a8ab0ff9374097110cc3f9"
NVBENCH_OPTIONS = "--min-samples 10 --timeout 2"
NVBENCH_RUN_FOLDER = "/pairbench/artifacts/"
NVBENCH_PROGRAM = "./kernel_bench"
NVBENCH_CLOCK = "1000000000"
# A state's share of the device's peak memory bandwidth gives that peak back
# from the state's bytes per second, so it is made up too.
NVBENCH_UTILIZATION = "0.5"

# Made-up values for every hardware figure of a device entry. The id stays:
# the states name the device by it.
NVBENCH_DEVICE: dict[str, Any] = {
    "name": "made-up GPU",
    "sm_version": 0,
    "ptx_version": 0,
    "sm_default_clock_rate": 1000000000,
    "number_of_sms": 1,
    "max_blocks_per_sm": 1,
    "max_threads_per_sm": 1,
    "max_threads_per_block": 1,
    "registers_per_sm": 1,
    "registers_per_block": 1,
    "global_memory_size": 1000000000,
    "global_memory_bus_peak_clock_rate": 1000000000,
    "global_memory_bus_width": 1,
    "global_memory_bus_bandwidth": 1000000000,
    "l2_cache_size": 1000000,
    "shared_memory_per_sm": 1000,
    "shared_memory_per_block": 1000,
    "ecc_state": False,
}

# Where each real run happened and what it ran. The image digests are those
# the public registries gave for the tag when the run was made.
RUNS: dict[str, dict[str, Any]] = {
    "gbench": {
        "tool": "Google Benchmark",
        "version": "1.8.3 (Ubuntu package libbenchmark-dev 1.8.3-3), built with g++ 13.3.0",
        "image": UBUNTU,
        "workload": "the program GBENCH_PROGRAM of the generator, as bench.cc, compiled with "
        "g++ -O2 -std=c++17 bench.cc -lbenchmark -lpthread",
    },
    "pytest-benchmark": {
        "tool": "pytest-benchmark",
        "version": "5.3.1 (with pytest 9.2.0)",
        "image": PYTHON,
        "workload": "the tests PYTEST_BENCHMARK_PROGRAM of the generator, as test_made_up.py",
    },
    "hyperfine": {
        "tool": "hyperfine",
        "image": DEBIAN,
        "workload": "the release binary for aarch64 Linux from "
        "https://github.com/sharkdp/hyperfine/releases, timing sleep 0.01 and sleep 0.02",
    },
    "perf": {
        "tool": "perf",
        "version": "perf version 6.12.117 (Debian package linux-perf 6.12.117-1)",
        "image": DEBIAN,
        "workload": "a shell loop counting to a fixed number",
        "environment": "--cap-add PERFMON and no other capability",
    },
    "llama-bench": {
        "tool": "llama-bench",
        "version": "llama.cpp build 12375, commit 9d25e0014",
        "image": "ghcr.io/ggml-org/llama.cpp:full@sha256:"
        "5bee33d877070ee246edb2f3442bcea4942d01d602f1abf479183c49a0f2ba7c",
        "workload": "the model stories15M-q4_0.gguf (sha256 "
        "66967fbece6dbe97886593fdbb73589584927e29119ec31f08090732d1861739) from "
        "https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories15M-q4_0.gguf, "
        "a conversion of https://huggingface.co/karpathy/tinyllamas (MIT licence), on CPU; "
        "the model is not part of the repository",
    },
    "lines": {
        "tool": "Python",
        "version": "Python 3.12.16",
        "image": PYTHON,
        "workload": "the program LINES_PROGRAM of the generator, as workload.py",
    },
    "nvbench": {
        "tool": "NVBench",
        "version": f"0.1.0 (JSON file version 1.0.0), commit {NVBENCH_COMMIT}",
        "image": CUDA,
        "workload": "kernel_bench of showcases/gpu-kernel (kernel_bench.cu: saxpy and cub_sum at "
        "2^24 and 2^26 elements), built inside the image by showcases/gpu-kernel/build.sh with "
        "the image's own toolkit",
        "environment": "docker run --rm --memory 8g --cpus 4 --gpus device=0, one NVIDIA GPU",
        "nvbench_commit": NVBENCH_COMMIT,
        "source": f"https://github.com/NVIDIA/nvbench at commit {NVBENCH_COMMIT}",
    },
}


def _json(doc: Any) -> str:
    return json.dumps(doc, indent=2) + "\n"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# -- one function per tool: raw folder -> {fixture name: (text, sidecar extras)} --


Fixtures = dict[str, tuple[str, dict[str, Any]]]


def gbench(raw: Path) -> Fixtures:
    """Google Benchmark: three repetitions with aggregates, and one run of one benchmark."""
    out: Fixtures = {}
    for raw_name, name, options in (
        ("gbench.json", "gbench.json", "--benchmark_repetitions=3 --benchmark_min_time=0.05s"),
        (
            "gbench-one.json",
            "gbench-one.json",
            "--benchmark_min_time=0.05s --benchmark_filter=BM_vector_sum",
        ),
    ):
        doc = _read_json(raw / raw_name)
        context = doc["context"]
        context.update(
            {
                "date": SYNTHETIC_DATE,
                "host_name": SYNTHETIC_HOST,
                "num_cpus": 4,
                "mhz_per_cpu": 1000,
                "caches": [],
                "load_avg": [0.0, 0.0, 0.0],
            }
        )
        command = f"./bench {options} --benchmark_out={name} --benchmark_out_format=json"
        replaced = (
            "context.date, host_name, num_cpus, mhz_per_cpu, caches and load_avg replaced "
            "by made-up values"
        )
        out[name] = (_json(doc), {"command": command, "replaced": replaced})
    return out


def pytest_benchmark(raw: Path) -> Fixtures:
    """pytest-benchmark: a JSON report with the data of each round, and a saved run without."""
    out: Fixtures = {}
    saved = sorted((raw / "storage").glob("*/*.json"))
    if len(saved) != 1:
        raise SystemExit("expected one saved run under storage/")
    sources = (
        (
            raw / "pytest-benchmark.json",
            "pytest-benchmark.json",
            "--benchmark-json=pytest-benchmark.json",
        ),
        (saved[0], "saved.json", "--benchmark-storage=file://storage --benchmark-save=made_up"),
    )
    for source, name, option in sources:
        doc = _read_json(source)
        doc["machine_info"] = {
            "processor": "",
            "machine": "machine-a",
            "python_compiler": "made-up compiler",
            "python_implementation": "CPython",
            "python_version": "3.12.16",
            "release": "0.0.0-made-up",
            "system": "Linux",
            "cpu": {"brand_raw": "made-up CPU", "count": 4},
        }
        doc["datetime"] = SYNTHETIC_DATE
        command = (
            "python -m pytest -q -p no:cacheprovider test_made_up.py --benchmark-min-rounds=7 "
            f"--benchmark-max-time=0.000001 --benchmark-warmup=off {option}"
        )
        replaced = "machine_info replaced by made-up values without a node name; datetime made up"
        out[name] = (_json(doc), {"command": command, "replaced": replaced})
    return out


def hyperfine(raw: Path) -> Fixtures:
    """hyperfine: the export of release 1.21.0 (older layout) and of 2.0.0 (newer layout)."""
    out: Fixtures = {}
    for tag, version in (("v1", "1.21.0"), ("v2", "2.0.0")):
        doc = _read_json(raw / f"hyperfine-{tag}.json")
        replaced = "nothing: the export names no machine"
        if "metadata" in doc:
            doc["metadata"]["start_time"] = "2000-01-01T00:00:00Z"
            doc["metadata"]["platform"] = {"os": "Linux", "architecture": "machine-a"}
            replaced = "metadata.start_time and metadata.platform replaced by made-up values"
        name = f"hyperfine-{tag}.json"
        command = (
            "hyperfine -N --runs 5 --warmup 1 -n 'short sleep' 'sleep 0.01' 'sleep 0.02' "
            f"--export-json {name}"
        )
        out[name] = (
            _json(doc),
            {"command": command, "replaced": replaced, "version": f"hyperfine {version}"},
        )
    return out


def perf(raw: Path) -> Fixtures:
    """perf stat with ``;`` as separator: one run, and three repeats with ``-r 3``."""
    out: Fixtures = {}
    for raw_name, name, options in (
        (
            "perf-stat-semicolon.txt",
            "perf-stat.txt",
            "-e instructions,cycles,task-clock,context-switches,cache-misses",
        ),
        (
            "perf-stat-semicolon-repeat.txt",
            "perf-stat-repeat.txt",
            "-r 3 -e instructions,cycles,task-clock",
        ),
    ):
        lines = (raw / raw_name).read_text(encoding="utf-8").splitlines()
        lines = [
            "# started on Sat Jan  1 00:00:00 2000" if line.startswith("# started on") else line
            for line in lines
        ]
        command = f"perf stat -x ';' -o {name} {options} -- sh -c '<loop>'"
        spread = " and their spread over the repeats" if " -r " in f" {options}" else ""
        replaced = (
            "the start line replaced by a made-up date; every other line kept as perf printed "
            f"it in the run: the counter values{spread}, how long each counter ran and for "
            "what share of the run, the figures perf derives from them (such as instructions "
            "per cycle, GHz and CPUs utilized) and the PMU names (the Linux driver's generic "
            "names), since the per-PMU lines are what the driver reads"
        )
        out[name] = ("\n".join(lines) + "\n", {"command": command, "replaced": replaced})
    return out


def llama_bench(raw: Path) -> Fixtures:
    """llama-bench: one prompt test and one generation test, three repetitions each."""
    doc = _read_json(raw / "stdout.txt")
    for test in doc:
        test["model_filename"] = "models/stories15M-q4_0.gguf"
        test["test_time"] = "2000-01-01T00:00:00Z"
        test["cpu_info"] = "made-up CPU"
    command = "llama-bench -m models/stories15M-q4_0.gguf -p 64 -n 16 -r 3 -t 4 -o json"
    replaced = "model_filename, test_time and cpu_info replaced by made-up values"
    return {"stdout.txt": (_json(doc), {"command": command, "replaced": replaced})}


def lines(raw: Path) -> Fixtures:
    """lines: the standard output of a Python workload that prints its own timings."""
    text = (raw / "stdout.txt").read_text(encoding="utf-8")
    return {
        "stdout.txt": (
            text,
            {"command": "python workload.py", "replaced": "nothing: the output names no machine"},
        )
    }


# A piece of a text: a run of characters between blanks, ( ) [ ] < >, quotes
# and , ; = : -- a '$(' stays in its piece, so a command substitution is seen.
_PIECE = re.compile(r"(?:\$\(|[^\s()\[\]<>'\",;=:])+")
# A variable or command substitution: '$HOME', '${HOME}', '$(pwd)'.
_VARIABLE = re.compile(r"\$[A-Za-z_{(]")
# Words joined by '/', as in a summary's tag ('nv/cold/time/gpu/mean'), name
# ('Elem/s') or description ('read/written').
_WORDS = re.compile(r"[A-Za-z]\w*(?:/[A-Za-z]\w*)+")
# The texts NVBench writes for each summary that may hold such words.
_SUMMARY_TEXTS = frozenset({"tag", "name", "description"})
# Where a state's summaries stand: the keys from the top of the document to
# benchmarks[*].states[*].summaries[*], None standing for a place in a list.
_STATE_SUMMARY: tuple[str | None, ...] = ("benchmarks", None, "states", None, "summaries", None)
_RUN_FOLDER = NVBENCH_RUN_FOLDER.rstrip("/")
# The steps of a path below the run folder, each made of ASCII letters, digits,
# '.', '_' and '-'.
_PLAIN_STEPS = re.compile(r"(?:/[A-Za-z0-9._-]+)*")


def _texts(node: Any, keys: tuple[str | None, ...] = ()) -> Iterator[tuple[str, bool]]:
    """Yield every key and text of NODE, each with whether it is a state summary's own text.

    KEYS lead from the top of the document to NODE. A state summary's own texts
    are the tag, name and description of an object at benchmarks[*].states[*].summaries[*];
    a list named 'summaries' anywhere else holds none.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), False
            if isinstance(value, str):
                yield value, keys == _STATE_SUMMARY and key in _SUMMARY_TEXTS
            else:
                yield from _texts(value, (*keys, str(key)))
    elif isinstance(node, list):
        for item in node:
            yield from _texts(item, (*keys, None))
    elif isinstance(node, str):
        yield node, False


def _outside(piece: str, nvbench_words: bool) -> bool:
    """Whether PIECE names a place outside the run folder.

    A home folder ('~'), a variable ('$') and a parent step ('..') are outside
    wherever they stand. A piece with '/' is outside unless it is an absolute
    path that stays in the run folder once '.' steps and repeated '/' are taken
    out and whose every step below the run folder is plain, or, in a state
    summary's own texts, words joined by '/'. So a relative path, one glued to
    an option such as '-I/x', and one glued to the run folder's path by any
    other character, a backslash, a '%2F' or a look-alike slash are outside.
    """
    if piece.startswith("~") or _VARIABLE.search(piece) or ".." in piece.split("/"):
        return True
    if "/" not in piece:
        return False
    if piece.startswith("/"):
        path = posixpath.normpath(piece)
        if path != _RUN_FOLDER and not path.startswith(_RUN_FOLDER + "/"):
            return True
        return not _PLAIN_STEPS.fullmatch(path[len(_RUN_FOLDER) :])
    return not (nvbench_words and _WORDS.fullmatch(piece))


def _paths_outside_the_run_folder(node: Any) -> list[str]:
    """Return every piece of the document's keys and texts that is outside the run folder."""
    return [
        piece
        for text, nvbench_words in _texts(node)
        for piece in _PIECE.findall(text)
        if _outside(piece, nvbench_words)
    ]


def _refuse(message: str) -> NoReturn:
    raise SystemExit(f"nvbench: {message}")


def _read_nvbench(raw: Path) -> dict[str, Any]:
    """Read RAW/nvbench.json, refusing in plain words when it is missing or not a JSON object."""
    path = raw / "nvbench.json"
    if raw.exists() and not raw.is_dir():
        _refuse(f"'{raw}' is not a folder; name the folder that holds nvbench.json")
    if not raw.is_dir():
        _refuse(f"the raw folder '{raw}' does not exist")
    if not path.is_file():
        _refuse(f"the raw folder '{raw}' holds no nvbench.json")
    try:
        doc = _read_json(path)
    except ValueError:
        _refuse(f"'{path}' is not JSON")
    if not isinstance(doc, dict):
        _refuse(f"'{path}' is not a JSON object")
    return doc


def _objects(
    node: dict[str, Any], key: str, where: str, missing: list[Any] | None = None
) -> list[dict[str, Any]]:
    """Return NODE[KEY], a list of JSON objects, or refuse; MISSING stands for an absent KEY."""
    items = node.get(key, missing)
    if not isinstance(items, list):
        _refuse(f"nvbench.json has no {where} list")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _refuse(f"nvbench.json: {where}[{index}] is not an object")
    return items


def _replace_clock_and_share(state: dict[str, Any], where: str) -> None:
    """Replace the state's mean clock rate and share of peak memory bandwidth.

    Refuses unless exactly one value of each was replaced, and when such a
    summary holds data other than its value, so a renamed hint or tag, or a
    figure beside the value, cannot leave a real figure in the fixture. Refuses
    a summary NVBench measured with CUPTI, whose tag starts with nv/cupti/: the
    writer cannot vouch for a figure CUPTI read from the device.
    """
    replaced = {NVBENCH_CLOCK: 0, NVBENCH_UTILIZATION: 0}
    beside: list[str] = []
    cupti: list[str] = []
    summaries = _objects(state, "summaries", f"{where}.summaries", [])
    for index, summary in enumerate(summaries):
        data = _objects(summary, "data", f"{where}.summaries[{index}].data", [])
        tag = str(summary.get("tag", ""))
        if tag.startswith("nv/cupti/"):
            cupti.append(f"summaries[{index}] '{tag}'")
        made_up = None
        if summary.get("hint") == "frequency":
            made_up = NVBENCH_CLOCK
        elif tag.endswith("/bw/global/utilization"):
            made_up = NVBENCH_UTILIZATION
        for entry in data if made_up else []:
            if entry.get("name") == "value":
                entry["value"] = made_up
                replaced[made_up] += 1
            else:
                beside.append(f"summaries[{index}] '{entry.get('name')}'")
    if cupti:
        _refuse(
            f"{where}: a summary NVBench measured with CUPTI: {', '.join(cupti)}; the writer "
            "cannot vouch for a CUPTI figure, so a real figure of the device could stay in the "
            "fixture"
        )
    clocks, shares = replaced[NVBENCH_CLOCK], replaced[NVBENCH_UTILIZATION]
    if (clocks, shares) != (1, 1):
        _refuse(
            f"{where}: values replaced under the hint frequency: {clocks}, under a tag ending "
            f"/bw/global/utilization: {shares}; each state needs exactly one of each, or a real "
            "clock rate or bandwidth share could stay in the fixture"
        )
    if beside:
        _refuse(
            f"{where}: a clock rate or bandwidth share summary holds data other than its value: "
            f"{', '.join(beside)}; only the value is replaced, so a real figure could stay in "
            "the fixture"
        )


def nvbench(raw: Path) -> Fixtures:
    """nvbench: one run of the gpu-kernel showcase's kernel_bench, four states."""
    doc = _read_nvbench(raw)
    meta = doc.get("meta")
    for key in ("argv", "raw_argv"):
        argv = meta.get(key) if isinstance(meta, dict) else None
        if not isinstance(meta, dict) or not isinstance(argv, list) or not argv:
            _refuse(f"nvbench.json has no meta.{key} list with the program's path first")
        meta[key] = [NVBENCH_PROGRAM, *argv[1:]]
    devices = _objects(doc, "devices", "devices")
    for index, device in enumerate(devices):
        if "id" not in device:
            _refuse(f"nvbench.json: devices[{index}] has no id")
    doc["devices"] = [{"id": device["id"], **NVBENCH_DEVICE} for device in devices]
    for b, bench in enumerate(_objects(doc, "benchmarks", "benchmarks")):
        for s, state in enumerate(_objects(bench, "states", f"benchmarks[{b}].states")):
            _replace_clock_and_share(state, f"benchmarks[{b}].states[{s}]")
    # The program's path in argv[0] is the writer's own made-up value.
    checked = {**doc, "meta": {**meta, "argv": meta["argv"][1:], "raw_argv": meta["raw_argv"][1:]}}
    left = _paths_outside_the_run_folder(checked)
    if left:
        raise SystemExit(f"nvbench: paths outside the run folder are left: {left}")
    command = f"{NVBENCH_PROGRAM} {NVBENCH_OPTIONS} --json {NVBENCH_RUN_FOLDER}nvbench.json"
    replaced = (
        "devices: every hardware figure and the name replaced by made-up values, the id kept; "
        f"each summary with the hint frequency (the mean SM clock rate) set to {NVBENCH_CLOCK}; "
        "each nv/cold/bw/global/utilization (a share of the device's peak memory bandwidth) "
        f"set to {NVBENCH_UTILIZATION}; "
        f"the program's path in meta.argv[0] and meta.raw_argv[0] replaced by {NVBENCH_PROGRAM}; "
        "every other measured time, count, rate and ratio kept as the run wrote it"
    )
    return {"nvbench.json": (_json(doc), {"command": command, "replaced": replaced})}


WRITERS: dict[str, Callable[[Path], Fixtures]] = {
    "gbench": gbench,
    "pytest-benchmark": pytest_benchmark,
    "hyperfine": hyperfine,
    "perf": perf,
    "llama-bench": llama_bench,
    "lines": lines,
    "nvbench": nvbench,
}


def write(tool: str, raw: Path) -> list[Path]:
    """Write the fixtures and sidecars of one tool."""
    fixtures = WRITERS[tool](raw)
    folder = FIXTURES / tool
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (text, extras) in fixtures.items():
        sidecar: dict[str, Any] = {
            "generator": GENERATOR,
            "seed": None,
            "tool": RUNS.get(tool, {}).get("tool", tool),
            "version": RUNS.get(tool, {}).get("version"),
            "synthetic": False,
            "image": RUNS.get(tool, {}).get("image"),
        }
        for key in ("workload", "environment", "nvbench_commit", "source"):
            if key in RUNS.get(tool, {}):
                sidecar[key] = RUNS[tool][key]
        sidecar.update(extras)
        (folder / name).write_text(text, encoding="utf-8")
        (folder / f"{name}.provenance.json").write_text(_json(sidecar), encoding="utf-8")
        written += [folder / name, folder / f"{name}.provenance.json"]
    return written


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("program", help="print the program a real run measured")
    show.add_argument("tool", choices=sorted(PROGRAMS))
    make = sub.add_parser("write", help="write the fixtures of one tool")
    make.add_argument("tool", choices=sorted(WRITERS))
    make.add_argument("raw", type=Path, help="the folder of the raw output of the run")
    args = parser.parse_args(argv)
    if args.command == "program":
        sys.stdout.write(PROGRAMS[args.tool])
        return 0
    for path in write(args.tool, args.raw):
        print(path.relative_to(HERE.parent.parent.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
