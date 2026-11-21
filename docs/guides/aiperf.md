---
description: "Serve each side as a serving side and let AIPerf drive it; pairbench reads AIPerf's per-request records, one artifact folder per load level."
---

# Compare two inference servers with AIPerf

Make each server a serving side and pass `--driver aiperf`: pairbench starts each server,
drives it with AIPerf at every load level, and compares the values it computes from AIPerf's
per-request records.

Options and file formats read from AIPerf 0.13.0: the output of `aiperf profile --help` and
the package's source at that release
([source](https://github.com/ai-dynamo/aiperf/tree/v0.13.0)), and checked against the files
of real runs of that version against a small model served on CPU.

AIPerf runs beside the server, as a client. Install it on the machine that runs pairbench,
for example with the `llm` extra. Set up the serving sides as the
[guidellm guide](guidellm.md#a-serving-experiment) shows, with `driver = "aiperf"`.

## What it adds to the command

One `aiperf profile` per load level, against the serving side's endpoint. A workload that is
empty or starts with an option is put after `aiperf profile`; any other workload is the whole
command. The driver adds:

- `--url <endpoint>`, and `--model <name>` when the endpoint names a model and the workload
  names none;
- `--endpoint-type chat`, `--streaming` and `--ui none` unless the workload chooses an
  endpoint type, streaming or a user interface itself;
- `--concurrency <level>` for a level of concurrent requests, or `--request-rate <level>` for
  a level of requests per second;
- `--benchmark-duration <s>` when `workload.level_duration` is set;
- `--random-seed <seed>`;
- `--artifact-dir <launch folder>/aiperf-<label>` and `--export-level records`, which makes
  AIPerf write the per-request file `profile_export.jsonl`.

A workload that gives any option of the last four points, under any of its names, is refused
with `E_USAGE`.

## What it reads

Each level's `profile_export.jsonl`, one JSON object per line: the records whose
`metadata.benchmark_phase` is `profiling`, that were not cancelled and carry no error. Each
gives a time to first token, an inter-token latency, its output tokens and its start and end.
A level without the per-request file falls back to AIPerf's own summary, with the reducer
`tool_summary`.

The cases and the default primary cases are those of the
[guidellm driver](guidellm.md#what-it-reads): `<level>/ttft_ms_median`, `ttft_ms_p90`,
`itl_ms_median`, `output_tokens_per_s`, `requests_per_s` and `tokens_per_joule[gpu]`.

Time to first token is AIPerf's own per-request value. Read what its stopwatch holds in
[first-token definitions](../method/first-token-definitions.md#aiperf-0130). Do not compare it
with a value from another load tool.

## Rounds

The rounds of a serving experiment are those of the
[guidellm guide](guidellm.md#rounds): `--rounds auto` resolves to 8, and the plan prints the
command for 16 rounds.

The default of 8 rounds misses many small real differences. With a board of 4 primary metrics,
the default when power is sampled, and the new side truly slower by twice the noise, 8 rounds
give SLOWER for only about a third of the metrics (33 to 39 percent on the
[error-rate page](../method/error-rates.md)); 16 rounds, with `--rounds 16`, give it for about
85 percent (83 to 88 percent). A difference of four times the noise is caught at 8 rounds 92
to 98 percent of the time. A miss at 8 rounds reads UNRESOLVED or TIE, not a wrong verdict.
Verdicts in the wrong direction across the 162 settings of that page with a real difference:
none in the simulated experiments. With no real difference, the largest share of experiments
with any verdict is 1.3 percent, under the rule's alpha of 5 percent. The report of a serving
run says how often its round count catches a real difference for the run's own number of
primary cases when the error-rate page has a row for the run: one side against the baseline,
the default rule, a round count and a number of primary cases the page simulates. For any
other run it says the page has no row; for a number of primary cases alone it also gives the
figures for the numbers of primary cases the page has. The plan says it for the chosen round count; as the cases are known only after
warm-up, it gives every number of primary cases the error-rate page has, unless the primary
cases are named one by one.

Tool documentation: [AIPerf](https://github.com/ai-dynamo/aiperf).
