---
description: "The llama-bench driver reads llama.cpp's benchmark program in JSON output and compares the median tokens per second of each test."
---

# Compare llama.cpp token rates with llama-bench

Pass `--driver llama-bench` and run llama.cpp's benchmark program as the workload: pairbench
reads its JSON output and compares the median tokens per second of each test.

Field names taken from the output of a real run of `llama-bench` (llama.cpp build 12375,
commit `9d25e0014`) on CPU with a small openly licensed model, and checked against the tool's
own source, `tools/llama-bench/llama-bench.cpp` at that commit
([source](https://github.com/ggml-org/llama.cpp/blob/9d25e0014/tools/llama-bench/llama-bench.cpp)).

## What it adds to the command

`-o json` when the command names no output format; the tool then prints a JSON array on
standard output, which the driver reads. `-o json` or `--output json` already in the command
is kept; any other output format is refused.

## What it reads

One case per test, named as the tool's own table names it:

| Case | Test |
|---|---|
| `pp<N>` | a prompt of N tokens |
| `tg<N>` | N generated tokens |
| `pp<N>+tg<M>` | both |
| `... @ d<D>` | the test starts at a context depth of D tokens |

The value is the median of the test's `samples_ts` (tokens per second, one per repetition); a
test without them gives the tool's own `avg_ts` as a `tool_summary`. Higher is better. The
pure generation tests count toward the verdict by default. Two tests of one name, as a sweep
over threads or models gives them, are refused: sweep with separate sides instead.

The version is `b<build_number> (<build_commit>)`. llama.cpp numbers its builds and has no
major version, so every build but the one the driver was tested with gives the note of an
untested version.

## Example

```
pairbench run --side new=image:REGISTRY/llama.cpp:NEW --side old=image:REGISTRY/llama.cpp:OLD \
  --driver llama-bench -- llama-bench -m /models/model.gguf -p 512 -n 128 -r 3
```

Mount the model into both sides with the launch setting `mounts`, read-only.

Tool documentation: [llama-bench README](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench).
