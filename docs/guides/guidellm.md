---
description: "Serve each version as a serving side and let GuideLLM drive it: first token, token rate and tokens per joule at each load level, one report per level."
---

# Compare two inference-server versions with GuideLLM

Make each server version a serving side and pass `--driver guidellm`: pairbench starts each
server, drives it with GuideLLM at every load level, and compares the values it computes from
GuideLLM's per-request records.

Options and the report format read from GuideLLM 0.8.1: the output of `guidellm run --help`
and the package's source at that release
([source](https://github.com/vllm-project/guidellm/tree/v0.8.1)), and checked against the
reports of real runs of that version against a small model served on CPU.

GuideLLM runs beside the server, as a client (`where = "client"`). Install it on the machine
that runs pairbench, for example with the `llm` extra.

## A serving experiment

A serving side is a server plus a load tool that drives it. Each launch starts the server,
waits until it is ready, sends one small request, runs every load level in order, and stops
the server. See [concepts](../concepts.md#sides).

```toml
[workload]
driver = "guidellm"
argv = ["--data", "kind=synthetic_text,prompt_tokens=256,output_tokens=128"]
levels = [1, 8, 32]
level_kind = "concurrency"
level_duration = "60s"

[sides.new.serve]
image = "REGISTRY/server@sha256:NEW_DIGEST"
args = ["--model", "/models/m"]
port = 8000
ready = { http = "/health", timeout = "15m" }

[sides.old.serve]
image = "REGISTRY/server@sha256:OLD_DIGEST"
args = ["--model", "/models/m"]
port = 8000
ready = { http = "/health", timeout = "15m" }

[sides.old]
baseline = true
```

`--levels` and `--level-duration` set the levels and their length from the command line.
Without them a serving experiment runs the levels 1, 8 and 32 requests in flight, 60 s each,
which are the values above; `pairbench plan` prints how long the load of one launch and of
the whole run takes.

## What it adds to the command

One `guidellm run` per load level, against the serving side's endpoint. A workload that is
empty or starts with an option is put after `guidellm run`; any other workload is the whole
command. The driver adds:

- `--backend kind=openai_http,target=<endpoint>`, with `model=<name>` when the endpoint names
  a model;
- `--profile kind=concurrent,streams=<level>` for a level of concurrent requests, or
  `--profile kind=constant,rate=<level>` for a level of requests per second;
- `--constraint kind=max_duration,seconds=<s>` when `workload.level_duration` is set;
- `--seed kind=static,value=<seed>`;
- `--output kind=json,path=<launch folder>/guidellm-<label>.json`;
- `--disable-console-interactive` unless a console option is given.

A workload that gives `sample_size` or any of these options except the constraint and the
console options is refused with `E_USAGE`. A workload without `--data` is refused too:
GuideLLM then has nothing to send.

## What it reads

`benchmarks[0]` of each level's report. Its per-request records, `requests.successful`, give
the serving metrics. A report without them falls back to GuideLLM's own summary, with the
reducer `tool_summary`.

Cases are `<level>/<metric>`. The level is `c<N>` for `N` concurrent requests and `r<N>` for
`N` requests per second (`workload.level_kind`):

| Metric | Unit | Better |
|---|---|---|
| `ttft_ms_median`, `ttft_ms_p90` | ms | lower |
| `itl_ms_median` | ms | lower |
| `output_tokens_per_s` | tokens/s | higher |
| `requests_per_s` | requests/s | higher |
| `tokens_per_joule[gpu]` | tokens/J | higher, when power was sampled |

At the highest level, `ttft_ms_median`, `itl_ms_median`, `output_tokens_per_s` and, when
present, `tokens_per_joule[gpu]` are primary; everything else is secondary. pairbench computes
the percentiles from the per-request records by linear interpolation between closest ranks.

The start-up cases are secondary and labelled "warm start": the image and the model weights are
already on the machine. Every serving launch gives `startup/ready_s` and
`startup/first_answer_s`, and each phase of `serve.phases` whose line the server prints gives
`startup/<phase>_s`. Without `serve.phases` the phases are built-in patterns for the lines the
vLLM OpenAI-compatible server prints while it starts, as its
[source at v0.33.0](https://github.com/vllm-project/vllm/tree/v0.33.0) writes them, so such a
launch also gives `startup/weights_loaded_s`, `startup/engine_ready_s` and
`startup/server_started_s`. A phase is timed from the start to the moment pairbench reads its
line, and counts when the server printed the line before its first answer. After the first
answer pairbench waits up to 30 s for its reader of the server's output to read what the server
wrote before it. Two loud notes in the results, each given once per side, say when the reader
fell behind: `startup_phases_read_late` names the phases whose line was read after the first
answer, so their time comes after it; `startup_phases_left_out` names the phases that have no
time because the wait ran out first. Only the rounds give these notes: the warm-ups and the
launches of `--explain` and of `pairbench profile` are not compared, and give none.

Time to first token is GuideLLM's own per-request value. Read what its stopwatch holds in
[first-token definitions](../method/first-token-definitions.md#guidellm-081).

## Rounds

A serving launch restarts the server, so a round is slow. For a serving experiment
`--rounds auto` resolves to 8 and the positive control is off unless asked for. At 8 rounds a
verdict needs every round that is not a tie to agree (all 8 when none tie), and at most 6
primary cases can receive one. The plan prints the
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

Tool documentation: [GuideLLM](https://github.com/vllm-project/guidellm).
