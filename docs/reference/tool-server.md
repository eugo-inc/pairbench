---
description: "pairbench mcp: a Model Context Protocol server over standard input and output, its tools, its answers and what an agent should read."
---

# Drive pairbench from an AI agent through the tool server

`pairbench mcp` starts a Model Context Protocol server over standard input and output, so an AI
agent can plan, run and read comparisons through typed tools instead of parsing prose. It needs
the `mcp` extra:

```
pip install "pairbench[mcp]"
pairbench mcp                 # read-only tools
pairbench mcp --allow-run     # adds run_start and run_cancel
```

A client starts it as a command, for example in a client configuration:

```json
{"mcpServers": {"pairbench": {"command": "pairbench", "args": ["mcp"]}}}
```

Without the extra, `pairbench mcp` exits 2 with `E_USAGE` and says to install
`pairbench[mcp]`.

## Tools

| Tool | Arguments | Does |
|---|---|---|
| `doctor` | none | what this machine supports; starts and changes nothing |
| `plan` | `config`, `sides`, `baseline`, `workload`, `sets` | the plan of an experiment, as `pairbench plan` prints it; launches nothing |
| `run_start` | as `plan`, and `out` | starts `pairbench run` and returns a handle at once; one run at a time. Without `out` the run goes to `run.out` of the config, else to a new folder |
| `run_status` | `handle` | progress of a run; once it has ended, its exit code, any refusal, the results file and the verdict of every primary case |
| `run_cancel` | `handle` | interrupts a run as Ctrl-C does: the current launch is torn down, the capture is marked interrupted, the exit code is 130 |
| `results` | `path`, `case`, `subject` | a results document (`results.json` or its run folder), or the comparisons of one case; a name given without its mark gives those of every case that name shows with a mark |
| `diagnostics` | `path`, `findings_only` | a diagnostics document, or only its findings |
| `compare` | `captures`, `reader`, `sides`, `driver`, `levels`, `baseline`, `rule`, `out`, `allow_incomplete`, `allow_mixed_machines`, `assume_interleaved` | analyse existing captures or result files of other tools; `levels` names the load level of serving result files |
| `explain` | `term`, or `results`, `case`, `subject` | a plain-language explanation of a term, or of the comparisons of one case; a name given without its mark explains those of every case that name shows with a mark |
| `fill` | `template`, `results`, `output`, `check` | fill a document's figure tokens; without `output` the text is returned |
| `selftest` | none | run the known answers and the controls; launches nothing |
| `schema` | `name` | a JSON Schema: `capture`, `results`, `config` or `diagnostics` |

The arguments of `plan` and `run_start` mirror the command line: `sides` is a list of
`NAME=KIND:SPEC`, `workload` the words after `--`, and `sets` a list of `KEY=VALUE` as
`--set` takes them.

`run_start` and `run_cancel` exist only when the server is started with `--allow-run`,
because they launch commands on the machine. Treat a config or a side spec from someone else
as code before you let an agent run it.

## Answers

Every answer is JSON text. A refusal is an answer, not a protocol error:

```json
{"refusal": {"code": "E_SIDE_UNRESOLVED", "exit_code": 3, "scope": "experiment",
             "message": "image myorg/app:2.0 was not found",
             "docs": "https://eugo.io/docs/pairbench/0.1/reference/exit-codes/#e_side_unresolved"}}
```

The agent reads `code`, the same stable text code the command line prints, and decides what
to do. `docs` is the address of the code's entry, with its cause and fix, in the
documentation of the installed version: the address the command line prints after a
refusal. An unexpected failure is reported the same way with `E_INTERNAL`.

The server writes nothing but protocol messages on standard output. The output of a run goes
to standard error, and `run_status` keeps the last lines of it.

## What an agent should read

- `comparisons[].outcome` and `comparisons[].reason`: stable within a schema version, where
  a later release may add a `reason` word but never renames or removes one. The display words
  may change between versions.
- `figures`: every number with its text, to quote without retyping it.
- `findings[].id` and `findings[].evidence` from the diagnostics. A finding describes a
  difference and never names a cause. The diagnostics hold names from the user's code; an
  agent does not paste them into anything public without being asked to.

No tool lists plug-ins by name; `doctor` gives only counts. See [for AI agents](../agents.md)
for the loop and the wording of a report.
