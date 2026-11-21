---
description: "The vllm-bench driver, experimental, reads the result file of vllm bench serve, one per load level, against a serving side."
---

# Compare two inference servers with vllm bench serve

Make each server a serving side and pass `--driver vllm-bench`: pairbench drives each server
with `vllm bench serve` at every load level and compares the summary values of its result
files. The driver is experimental.

> **Experimental.** This driver has no fixture from a run of the real tool yet, only one written from the
> tool's public source, and `pairbench doctor` marks it experimental.

Options and the result fields read from vLLM's public source at release v0.33.0:
`vllm/benchmarks/serve.py` and `vllm/benchmarks/datasets/datasets.py`
([source](https://github.com/vllm-project/vllm/tree/v0.33.0/vllm/benchmarks)).

Set up the serving sides as the [guidellm guide](guidellm.md#a-serving-experiment) shows,
with `driver = "vllm-bench"` and without `level_duration`.

## What it adds to the command

One `vllm bench serve` per load level, against the serving side's endpoint. A workload that is
empty or starts with an option is put after `vllm bench serve`; any other workload is the
whole command. The driver adds:

- `--base-url <endpoint>`, and `--model <name>` when the endpoint names a model and the
  workload names none;
- `--max-concurrency <level>` for a level of concurrent requests, or `--request-rate <level>`
  for a level of requests per second;
- `--seed <seed>`;
- `--save-result`, `--result-dir <launch folder>` and
  `--result-filename vllm-bench-<label>.json`.

A workload that gives `--base-url`, `--host`, `--port`, `--max-concurrency`,
`--request-rate`, `--seed`, `--result-dir`, `--result-filename` or `--append-result` is
refused with `E_USAGE`. `vllm bench serve` ends after its number of prompts, not after a time,
so a load with `workload.level_duration` is refused too: set the number of prompts in the
workload instead.

## What it reads

Per level, one case `<label>/<field>` for each summary field of the result file, with the
reducer `tool_summary`:

- `request_throughput` (requests/s);
- `output_throughput` and `total_token_throughput` (tokens/s);
- every `mean_`, `median_` and `p<N>_` field of `ttft`, `tpot`, `itl` and `e2el`, in
  milliseconds;
- `tokens_per_joule[gpu]`, the total output tokens divided by the GPU energy of the level's
  window, when power was sampled.

The output token rate at the highest level is the default primary case. A result with no
completed request, or with a negative figure, is refused. The result file names no version of
vLLM.

Time to first token is the client's own per-request value. Read what its stopwatch holds in
[first-token definitions](../method/first-token-definitions.md#vllm-benchmark-client-vllm-bench-serve-v0330).

## Rounds

The rounds of a serving experiment are those of the
[guidellm guide](guidellm.md#rounds): `--rounds auto` resolves to 8, and the plan prints the
command for 16 rounds.

The default of 8 rounds misses many small real differences. The default board of this driver
is one primary case; with the new side truly slower by twice the noise, 8 rounds give SLOWER
41 to 51 percent of the time, and 16 rounds 91 to 95 percent. With a board of 4 primary
metrics, set with `cases.primary`, 8 rounds give SLOWER for only about a third of the metrics
(33 to 39 percent on the [error-rate page](../method/error-rates.md)); 16 rounds, with
`--rounds 16`, give it for about 85 percent (83 to 88 percent). A difference of four times the
noise is caught at 8 rounds 92 to 98 percent of the time on that board. A miss at 8 rounds
reads UNRESOLVED or TIE, not a wrong verdict. Verdicts in the wrong direction across the 162
settings of that page with a real difference: none in the simulated experiments. With no real
difference, the largest share of experiments with any verdict is 1.3 percent, under the rule's
alpha of 5 percent. The report of a serving run says how often its round count catches a real
difference for the run's own number of primary cases when the error-rate page has a row for
the run: one side against the baseline, the default rule, a round count and a number of
primary cases the page simulates. For any other run it says the page has no row; for a number
of primary cases alone it also gives the figures for the numbers of primary cases the page
has. The plan says it for the chosen round
count; as the cases are known only after warm-up, it gives every number of primary cases the
error-rate page has, unless the primary cases are named one by one.

Tool documentation: [vLLM benchmark CLI](https://docs.vllm.ai/en/latest/cli/bench/serve.html).
