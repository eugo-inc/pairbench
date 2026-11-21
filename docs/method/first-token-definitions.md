---
description: "No: each load tool starts and stops its first-token stopwatch at its own point; what each tool measures, read from its public source."
---

# Can times to first token from two load tools be compared?

No: each load tool starts and stops its first-token stopwatch at its own point, so a time to
first token from one tool is not comparable with one from another. pairbench reads each tool's
own value and names the tool and version beside it.

Compare first-token times only between runs measured by the same tool, at the same version,
with the same request settings. pairbench does not refuse other comparisons: a result file
side may name its own driver (`format`), so two sides of one experiment can be read by two
different tools. The results then name the driver and tool version of each side
(`sides[].driver`), the reports say which driver read which side, and the comparison carries
the loud note `drivers_differ`: its ratio compares the two tools as well as the two sides.

The descriptions below are read from each tool's public source at the version stated. A
later version may change them; the driver records the version of every launch.

## GuideLLM 0.8.1

Source: [`schemas/base/request_stats.py`](https://github.com/vllm-project/guidellm/blob/v0.8.1/src/guidellm/schemas/base/request_stats.py)
and [`backends/openai/http.py`](https://github.com/vllm-project/guidellm/blob/v0.8.1/src/guidellm/backends/openai/http.py).

- **Formula**: `time_to_first_token_ms = 1000 * (first_token_iteration - request_start)`.
- **Start**: `request_start` is the wall-clock time (`time.time()`) at which the HTTP client
  starts writing the request headers, taken from a trace hook of the client. It is first set
  just before the streaming request is opened, and the trace hook replaces it.
- **Stop**: `first_token_iteration` is the wall-clock time of the first streamed line that the
  request handler counts as one or more generated tokens. Reasoning tokens count; the time
  to the first non-reasoning token is a separate value.
- **Inter-token latency**: `(last_token_iteration - first_token_iteration)` divided by the
  output tokens less one, in milliseconds.

## AIPerf 0.13.0

Source: [`metrics/types/ttft_metric.py`](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/src/aiperf/metrics/types/ttft_metric.py),
[`transports/aiohttp_client.py`](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/src/aiperf/transports/aiohttp_client.py)
and the [metrics reference](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/docs/metrics-reference.md).

- **Formula**: `ttft_ns = content_responses[0].perf_ns - request.start_perf_ns`.
- **Start**: `start_perf_ns` is a monotonic clock reading (`time.perf_counter_ns()`) taken
  after the client session is set up and immediately before the request is issued, so a
  connection that has to be opened falls inside the interval.
- **Stop**: the receive time of the first streamed message with non-empty content.
- **Scope**: the metrics reference says the value includes network latency, queuing time,
  prompt processing and the generation of the first token or chunk of tokens.

## vLLM benchmark client (`vllm bench serve`), v0.33.0

Source: [`benchmarks/lib/endpoint_request_func.py`](https://github.com/vllm-project/vllm/blob/v0.33.0/vllm/benchmarks/lib/endpoint_request_func.py).

- **Formula**: `ttft = timestamp - st`, in seconds.
- **Start**: `st` is a monotonic clock reading (`time.perf_counter()`) taken just before the
  POST request is issued.
- **Stop**: for the completions endpoint, the first server-sent data message that holds
  `choices`, even when its text is empty, for example for special tokens; the clock is read
  after the message is parsed. For the chat completions endpoint, the first data message
  whose first choice carries streamed output; the clock is read before the message is
  parsed. Comment lines, which servers send as pings, are skipped.
- **Inter-token latency**: the list of gaps between consecutive such messages.

pairbench reads the saved result file of the vLLM client. Its `vllm-bench` driver is marked
experimental until it has a fixture from a real run.

## What differs

| | GuideLLM 0.8.1 | AIPerf 0.13.0 | vLLM client v0.33.0 |
|---|---|---|---|
| clock | wall clock | monotonic | monotonic |
| start | first header write | before the request is issued | before the POST is issued |
| stop | first line with a counted token | first message with non-empty content | first message with choices (completions) or streamed output (chat) |

A difference in where the clock starts or stops is a constant added to every request. It
moves a ratio toward 1 and changes an absolute value; pairbench's paired comparison of two
server versions with one tool is still sound, but a first-token time quoted next to a
number from another tool is not.
