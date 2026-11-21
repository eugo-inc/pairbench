# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Generate the fixtures of the serving drivers.

``guidellm`` and ``aiperf`` have fixtures from real runs of the tools against
``llama-server`` of llama.cpp, in a short container of a public image, serving
a small openly licensed model on CPU. Each tool ran three load levels of ten
seconds: one and two concurrent requests (``c1``, ``c2``) and two requests per
second (``r2``). ``write`` reads the raw output of those runs from a folder
(``<label>.json`` for guidellm, ``<label>/`` artifact folders for aiperf),
keeps what the drivers read and drops the rest, and writes the fixtures into
``tests/fixtures/serving/<tool>/``, each with a ``*.provenance.json``
sidecar::

    python tests/fixtures/_gen/serving.py write guidellm RAW_FOLDER
    python tests/fixtures/_gen/serving.py write aiperf RAW_FOLDER

What is kept, per level:

* ``r2``: every successful request;
* ``c2``: the first ``KEEP`` successful requests by start time, with the
  tool's own summary of all of them;
* ``c1``: the tool's own summary only, for the drivers' fallback.

``vllm-bench`` has no real run yet. Its fixture is written from the result
fields of ``vllm bench serve`` in vLLM's public source at release v0.33.0,
with made-up values, and needs no raw folder::

    python tests/fixtures/_gen/serving.py write vllm-bench
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "serving"
GENERATOR = "tests/fixtures/_gen/serving.py"
SEED = 1234
KEEP = 40
SYNTHETIC_PLATFORM = "made-up-platform"
# Every clock reading of a run is moved by a whole number of seconds so that the
# run starts in the second SYNTHETIC_EPOCH; the time between two readings is kept.
SYNTHETIC_EPOCH = 1_000_000_000
SHIFTED = (
    "every clock reading moved by a whole number of seconds so that the run starts at "
    f"{SYNTHETIC_EPOCH} s since the epoch (the time between two readings is kept)"
)
SERVER_IMAGE = (
    "ghcr.io/ggml-org/llama.cpp:full"
    "@sha256:5bee33d877070ee246edb2f3442bcea4942d01d602f1abf479183c49a0f2ba7c"
)
SERVER = (
    "llama-server of llama.cpp build 12375 (commit 9d25e0014), the image's /app/llama-server, "
    "on CPU with 4 threads, a context of 4096 tokens and 4 slots, the port published on the "
    "loopback address only"
)
MODEL = (
    "the model stories15M-q4_0.gguf (sha256 "
    "66967fbece6dbe97886593fdbb73589584927e29119ec31f08090732d1861739) from "
    "https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories15M-q4_0.gguf, a "
    "conversion of https://huggingface.co/karpathy/tinyllamas (MIT licence), served under the "
    "name stories15M; the model is not part of the repository"
)
LEVELS = {
    "c1": ("--profile kind=concurrent,streams=1", "--concurrency 1"),
    "c2": ("--profile kind=concurrent,streams=2", "--concurrency 2"),
    "r2": ("--profile kind=constant,rate=2", "--request-rate 2 --arrival-pattern constant"),
}

# --- guidellm ------------------------------------------------------------------

GUIDELLM_VERSION = "0.8.1"
GUIDELLM_REQUEST_KEYS = (
    "type_",
    "request_start_time",
    "request_end_time",
    "request_latency",
    "prompt_tokens",
    "output_tokens",
    "time_to_first_token_ms",
    "time_per_output_token_ms",
    "inter_token_latency_ms",
    "output_tokens_per_second",
)
GUIDELLM_METRICS = (
    "time_to_first_token_ms",
    "inter_token_latency_ms",
    "output_tokens_per_second",
    "requests_per_second",
    "output_token_count",
)
GUIDELLM_STAT_KEYS = ("mean", "median", "min", "max", "count", "total_sum")
GUIDELLM_PERCENTILES = ("p50", "p90", "p95", "p99")


def guidellm_command(label: str) -> str:
    return (
        "guidellm run --backend kind=openai_http,target=http://127.0.0.1:8000 "
        f"{LEVELS[label][0]} --constraint kind=max_duration,seconds=10 "
        "--data kind=synthetic_text,prompt_tokens=32,output_tokens=32 "
        "--tokenizer kind=huggingface_auto,model=gpt2 --seed kind=static,value=1234 "
        f"--output kind=json,path=out/{label}.json --disable-console-interactive"
    )


def trim_guidellm(raw: Mapping[str, Any], label: str) -> tuple[dict[str, Any], str]:
    """Return the trimmed report of one level and what was replaced or dropped."""
    (benchmark,) = raw["benchmarks"]
    successful = sorted(
        benchmark["requests"]["successful"], key=lambda r: float(r["request_start_time"])
    )
    total = len(successful)
    offset = int(benchmark["start_time"]) - SYNTHETIC_EPOCH

    def request(raw_request: Mapping[str, Any]) -> dict[str, Any]:
        out = _pick(raw_request, GUIDELLM_REQUEST_KEYS)
        for key in ("request_start_time", "request_end_time"):
            out[key] = out[key] - offset
        return out

    if label == "c1":
        kept: list[dict[str, Any]] = []
        how = f"requests.successful emptied (the tool's summary of all {total} requests kept)"
    elif label == "c2":
        kept = [request(r) for r in successful[:KEEP]]
        how = (
            f"requests.successful kept to the first {KEEP} of {total} by start time (the tool's "
            "summary of all of them kept)"
        )
    else:
        kept = [request(r) for r in successful]
        how = f"every one of the {total} successful requests kept"
    metrics = {}
    for name in GUIDELLM_METRICS:
        stats = benchmark["metrics"][name]["successful"]
        trimmed = _pick(stats, GUIDELLM_STAT_KEYS)
        trimmed["percentiles"] = _pick(stats["percentiles"], GUIDELLM_PERCENTILES)
        metrics[name] = {"successful": trimmed}
    meta = dict(raw["metadata"])
    meta["platform"] = SYNTHETIC_PLATFORM
    doc = {
        "metadata": meta,
        "benchmarks": [
            {
                "type_": benchmark["type_"],
                "config": {"strategy": benchmark["config"]["strategy"]},
                "start_time": benchmark["start_time"] - offset,
                "end_time": benchmark["end_time"] - offset,
                "duration": benchmark["duration"],
                "metrics": metrics,
                "requests": {"successful": kept},
            }
        ],
    }
    replaced = (
        f"{how}; per request only {', '.join(GUIDELLM_REQUEST_KEYS)} kept (the request "
        "arguments, the output text, ids and timings dropped); metrics kept to "
        f"{', '.join(GUIDELLM_METRICS)}, each to its successful requests' "
        f"{', '.join(GUIDELLM_STAT_KEYS)} and {', '.join(GUIDELLM_PERCENTILES)}; the run "
        "configuration, the scheduler state and the conclusions dropped; metadata.platform "
        f"replaced by {SYNTHETIC_PLATFORM!r}; {SHIFTED}"
    )
    return doc, replaced


def write_guidellm(raw: Path) -> list[Path]:
    out: list[Path] = []
    for label in LEVELS:
        doc, replaced = trim_guidellm(_load(raw / f"{label}.json"), label)
        target = FIXTURES / "guidellm" / f"guidellm-{label}.json"
        _write(target, doc)
        _sidecar(target, "guidellm", GUIDELLM_VERSION, guidellm_command(label), replaced)
        out.append(target)
    return out


# --- aiperf ----------------------------------------------------------------------

AIPERF_VERSION = "0.13.0"
AIPERF_META_KEYS = (
    "session_num",
    "turn_index",
    "request_start_ns",
    "request_end_ns",
    "benchmark_phase",
    "was_cancelled",
)
AIPERF_RECORD_METRICS = (
    "time_to_first_token",
    "inter_token_latency",
    "request_latency",
    "input_sequence_length",
    "output_sequence_length",
    "output_token_count",
)
AIPERF_SUMMARY_KEYS = (
    "schema_version",
    "aiperf_version",
    "request_count",
    "time_to_first_token",
    "inter_token_latency",
    "request_latency",
    "output_sequence_length",
    "output_token_throughput",
    "request_throughput",
    "benchmark_duration",
)


def aiperf_command(label: str) -> str:
    return (
        "aiperf profile --url http://127.0.0.1:8000 --model stories15M --endpoint-type chat "
        f"--streaming {LEVELS[label][1]} --benchmark-duration 10 --isl 32 --osl 32 "
        f"--tokenizer gpt2 --random-seed 1234 --artifact-dir out/{label} --export-level records "
        "--ui none --no-gpu-telemetry --no-server-metrics"
    )


def trim_aiperf_records(text: str, label: str) -> tuple[str, str]:
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    records.sort(key=lambda r: int(r["metadata"]["request_start_ns"]))
    total = len(records)
    kept = records[:KEEP] if label == "c2" else records
    first_s = int(records[0]["metadata"]["request_start_ns"]) // 1_000_000_000
    offset_ns = (first_s - SYNTHETIC_EPOCH) * 1_000_000_000
    lines = []
    for record in kept:
        meta = _pick(record["metadata"], AIPERF_META_KEYS)
        for key in ("request_start_ns", "request_end_ns"):
            meta[key] = int(meta[key]) - offset_ns
        trimmed: dict[str, Any] = {
            "metadata": meta,
            "metrics": _pick(record["metrics"], AIPERF_RECORD_METRICS),
        }
        if record.get("error") is not None:
            trimmed["error"] = record["error"]
        lines.append(json.dumps(trimmed, sort_keys=False))
    how = (
        f"the first {KEEP} of {total} records by start time kept"
        if label == "c2"
        else f"every one of the {total} records kept"
    )
    replaced = (
        f"{how}; per record metadata kept to {', '.join(AIPERF_META_KEYS)} (ids and worker "
        f"names dropped) and metrics to {', '.join(AIPERF_RECORD_METRICS)}; {SHIFTED}"
    )
    return "".join(line + "\n" for line in lines), replaced


def trim_aiperf_summary(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    doc = _pick(raw, AIPERF_SUMMARY_KEYS)
    replaced = (
        f"kept to {', '.join(AIPERF_SUMMARY_KEYS)}; the run's command, configuration, start and "
        "end times and every other metric dropped"
    )
    return doc, replaced


def write_aiperf(raw: Path) -> list[Path]:
    out: list[Path] = []
    for label in LEVELS:
        folder = FIXTURES / "aiperf" / f"aiperf-{label}"
        summary, replaced = trim_aiperf_summary(_load(raw / label / "profile_export_aiperf.json"))
        target = folder / "profile_export_aiperf.json"
        _write(target, summary)
        _sidecar(target, "aiperf", AIPERF_VERSION, aiperf_command(label), replaced)
        out.append(target)
        if label == "c1":
            continue
        text, replaced = trim_aiperf_records(
            (raw / label / "profile_export.jsonl").read_text(encoding="utf-8"), label
        )
        target = folder / "profile_export.jsonl"
        target.write_text(text, encoding="utf-8")
        _sidecar(target, "aiperf", AIPERF_VERSION, aiperf_command(label), replaced)
        out.append(target)
    return out


# --- vllm-bench --------------------------------------------------------------------

VLLM_SOURCE = "https://github.com/vllm-project/vllm/blob/v0.33.0/vllm/benchmarks/serve.py"


def vllm_result(concurrency: int) -> dict[str, Any]:
    """A made-up result of ``vllm bench serve`` with the fields its source saves."""
    scale = float(concurrency)
    result: dict[str, Any] = {
        "date": "20000101-000000",
        "endpoint_type": "openai",
        "backend": "openai",
        "label": None,
        "model_id": "made-up-model",
        "tokenizer_id": "made-up-model",
        "num_prompts": 32,
        "request_rate": "inf",
        "burstiness": 1.0,
        "max_concurrency": concurrency,
        "duration": 16.0 / scale,
        "completed": 32,
        "failed": 0,
        "total_input_tokens": 4096,
        "total_output_tokens": 2048,
        "request_throughput": 2.0 * scale,
        "request_goodput": None,
        "output_throughput": 128.0 * scale,
        "total_token_throughput": 384.0 * scale,
        "max_output_tokens_per_s": 150.0 * scale,
        "max_concurrent_requests": concurrency,
        "rtfx": 0.0,
    }
    for metric, base in (("ttft", 20.0), ("tpot", 5.0), ("itl", 5.0)):
        result[f"mean_{metric}_ms"] = base * scale + 0.5
        result[f"median_{metric}_ms"] = base * scale
        result[f"std_{metric}_ms"] = 1.25
        result[f"p99_{metric}_ms"] = base * scale * 2.0
    return result


def write_vllm_bench() -> list[Path]:
    out: list[Path] = []
    for concurrency in (1, 4):
        target = FIXTURES / "vllm-bench" / f"vllm-bench-c{concurrency}.json"
        _write(target, vllm_result(concurrency))
        _sidecar(
            target,
            "vllm bench serve",
            "the result fields of vLLM v0.33.0",
            f"vllm bench serve --max-concurrency {concurrency} --seed 1234 --save-result",
            f"every value made up; the fields as {VLLM_SOURCE} saves them without --save-detailed",
            synthetic=True,
        )
        out.append(target)
    return out


# --- shared --------------------------------------------------------------------------


def _pick(obj: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: obj[key] for key in keys if key in obj}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def _sidecar(
    target: Path,
    tool: str,
    version: str,
    command: str,
    replaced: str,
    *,
    synthetic: bool = False,
) -> None:
    doc: dict[str, Any] = {
        "generator": GENERATOR,
        "seed": SEED,
        "tool": tool,
        "version": version,
        "synthetic": synthetic,
        "image": None if synthetic else SERVER_IMAGE,
        "server": None if synthetic else SERVER,
        "workload": None if synthetic else MODEL,
        "command": command,
        "replaced": replaced,
    }
    if not synthetic:
        doc["tool_install"] = f"{tool} {version} from PyPI, run on the host beside the server"
    sidecar = target.with_name(target.name + ".provenance.json")
    sidecar.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


WRITERS: dict[str, Callable[..., list[Path]]] = {
    "guidellm": write_guidellm,
    "aiperf": write_aiperf,
    "vllm-bench": write_vllm_bench,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write", help="write the fixtures of one tool")
    write.add_argument("tool", choices=sorted(WRITERS))
    write.add_argument("raw", nargs="?", type=Path, help="the folder of the raw run output")
    args = parser.parse_args(argv)
    if args.tool == "vllm-bench":
        written = write_vllm_bench()
    else:
        if args.raw is None:
            parser.error(f"{args.tool} needs the folder of the raw run output")
        written = WRITERS[args.tool](args.raw)
    for path in written:
        print(path.relative_to(FIXTURES.parent.parent.parent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
