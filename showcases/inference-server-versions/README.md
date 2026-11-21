# Two versions of an inference server

Two release tags of the vLLM OpenAI-compatible server image serve the same small model, and
GuideLLM drives the same load against each:

| Side | Image |
|---|---|
| `old` (baseline) | `vllm/vllm-openai:v0.32.0` |
| `new` | `vllm/vllm-openai:v0.33.0` |

The model is [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), under
the Apache-2.0 licence, at revision `7ae557604adf67be50417f59c2c2f167def9a775`. The images are
pinned by digest in [`sides.lock`](sides.lock) and [`pairbench.toml`](pairbench.toml); the
model revision is pinned in [`run.sh`](run.sh). Read the licence of each image and of the
model before you publish a result made with them.

## Run it

```sh
pip install 'pairbench[llm,gpu]' guidellm==0.8.1
./run.sh
```

You need Docker with GPU support and one NVIDIA GPU. The first run downloads the model into
`models/` in this folder, once; every server then mounts that folder read-only at `/models`.
GuideLLM runs on this machine and reads the tokenizer from the same folder. Options after
`./run.sh` go to `pairbench run`, for example `./run.sh --levels 1,8` for other load levels.

## What it measures

Each launch starts the server, waits until `/health` answers, sends one small request, runs
the three load levels in order (1, 4 and 16 concurrent requests, 60 seconds each), and stops
the server. The [`guidellm`](../../docs/guides/guidellm.md) driver reads, at each level:

- the time to first token, median and 90th percentile, as GuideLLM measures it (see
  [first-token definitions](../../docs/method/first-token-definitions.md));
- the inter-token latency and the output token rate;
- tokens per joule, from GPU power sampled during the load (`[energy] enabled = true`); this
  counts the GPU only, and is labelled `[gpu]`.

The start-up phases of each server (model loading, engine start, first answer) are recorded as
`startup/` cases. The cases at the highest level count toward the verdict.

## What to look at

- A serving round is long, so the default round count is small. The time a round takes is not
  known before a launch has been timed, so with `--budget` the plan prints the smallest count
  that can give a verdict, and the run fixes the count that fits the budget after warm-up.
- The default of 8 rounds misses many small real differences. This board has 4 primary metrics
  at the highest level; with `new` truly slower by twice the noise, 8 rounds give SLOWER for
  only about a third of them (33 to 39 percent on the
  [error-rate page](../../docs/method/error-rates.md)), and 16 rounds, with
  `./run.sh --rounds 16`, for about 85 percent (83 to 88 percent). A difference of four times
  the noise is caught at 8 rounds 92 to 98 percent of the time. A miss at 8 rounds reads
  UNRESOLVED or TIE, not a wrong verdict. Verdicts in the wrong direction across the 162
  settings of that page with a real difference: none in the simulated experiments. With no
  real difference, the largest share of experiments with any verdict is 1.3 percent, under the
  rule's alpha of 5 percent. The plan and the report say how often the round count chosen
  catches a real difference.
- The positive control is off by default for a serving experiment.
- Between two server versions, defaults can change as well as speed. The server's log of each
  launch is kept in the run folder; compare the settings it prints before reading a verdict.

## Expected result

[`expected/`](expected/) holds no result yet.
