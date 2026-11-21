---
description: "The loop for an agent: doctor, plan, run with --json, read outcome and reason from results.json, quote figures, and report a result."
---

# Use pairbench as an AI agent

Run `pairbench run ... --json`, read the exit code, then read `comparisons[].outcome` and
`comparisons[].reason` in `results.json` and quote numbers only from its `figures`. Everything
an agent needs is in exit codes and JSON documents; nothing needs prose to be parsed.

## The loop

1. **`pairbench doctor --json`**: what this machine supports, which external programs are
   found, what is degraded. It always exits 0.
2. **`pairbench plan ...`**: the lineup, the rounds, the launches and the balance, before
   anything runs. It launches nothing.
3. **`pairbench run ... --json`**: plan, preflight, machine checks, measured rounds, analysis
   and the run folder. With `--json` the results document is printed on standard output;
   progress goes to standard error.
4. **Read `results.json`** in the run folder. Read `comparisons[].outcome` and
   `comparisons[].reason`, never the display word, and quote numbers from `figures`.
5. **`pairbench fill TEMPLATE --results results.json -o OUT`**: put the figures into a
   document instead of typing them.

```
pairbench doctor --json
pairbench plan --side new=image:myorg/app:2.0 --side old=image:myorg/app:1.9 -- python bench.py
pairbench run  --side new=image:myorg/app:2.0 --side old=image:myorg/app:1.9 --json -- python bench.py
pairbench fill report.in.md --results pairbench-runs/RUN/results.json -o report.md
```

`pairbench schema results` prints the JSON Schema of the results document, and
`pairbench schema diagnostics` that of the diagnostics document. Within a schema version,
`outcome`, `reason` and the figure keys keep their meaning; display words may change between
versions. A later release of the same schema version may add an optional field, or a value to
a field whose schema lists its values, such as a new `reason`, so read a value you do not know
as it is rather than failing; renaming or removing a field or a value, or changing its
meaning, needs a new schema version.

## What to read

| Field | Values |
|---|---|
| `comparisons[].outcome` | `better`, `worse`, `higher`, `lower`, `tie`, `unresolved`, `no_verdict` |
| `comparisons[].reason` | why a comparison is `unresolved` or `no_verdict`; `null` otherwise |
| `comparisons[].primary` | `true` for a case that counts toward the verdict and the exit code |
| `controls.positive.status` | `ok`, `failed` or `not_run`; a failed control gives every comparison `no_verdict` |
| `figures` | every number with its text, under keys such as `matmul.new_vs_old.ratio` |
| `refusals[]` | text code, scope and message of anything refused |

The [results schema](reference/results-schema.md) page shows the fields in an example and
explains the ones worth knowing; `pairbench schema results` prints every field.
[Verdicts](method/verdicts.md) says what each outcome and reason means.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | completed and results written, whatever the verdicts |
| 1 | a requested check failed: `--fail-on` matched, a self-test control failed, `fill --check` found a stale document |
| 2 | usage or config error |
| 3 | a side was refused in preflight |
| 4 | the machine was refused: a check under `enforce`, or a lock |
| 5 | a launch failed; the capture is kept and marked |
| 6 | the analysis was refused |
| 7 | `fill`: a figure is missing |
| 8 | internal error |
| 130 | interrupted |

Every refusal also has a stable text code, such as `E_TOO_FEW_ROUNDS`, on standard error and
in `refusals[]`. The line after it on standard error gives the address of the code's cause and
fix in the [exit code reference](reference/exit-codes.md), which lists them all.

## How to report a result

- Quote the verdict with its noise bar and its p-value, for example "FASTER, 1.26x, outside a
  noise bar of ±1.8%, corrected p = 0.0010" (made-up numbers).
- Name the rule and the number of paired rounds: "rule strict, 16 paired rounds" (made-up).
- Say UNRESOLVED or NO VERDICT as such, with the reason in plain words. Never round an
  UNRESOLVED up to a win or down to a tie.
- Never type a number by hand. Take it from `figures`, or fill the document with
  `pairbench fill`.
- Never change the rule, the cases or the baseline after seeing the results.
- To share a run, share `results.json`, `results.md` or `report.html`. Never share
  `capture.jsonl`: it keeps the command line as typed, credentials included.
- A verdict holds for the machine and the load it was measured on. Say which.
- Do not put a secret on a side's command line. The results hide the secret forms that
  [what the shared files hide](reference/config.md#what-the-shared-files-hide) lists, hide
  the spec of each `--side` (an image reference shows when `report.include_image_refs` is on)
  and the value of each `--set`, and cut each absolute path to its last part, as they cut each
  relative path that climbs out of its folder with `..`. They show a
  short plain value that nothing on that list names, such as one given after an option of one
  letter, as a plain argument or in the path of an address, and the forms that
  [the known limits of the shown command](../SECURITY.md#known-limits-of-the-shown-command)
  list; the capture keeps the command as typed. Hand a secret to a side by name with
  `env_pass`.

## Diagnostics

`diagnostics.json` describes how the sides differ in what they used: resource figures,
counters and sampled stacks. Read `findings[].id` and `findings[].evidence`, and say what a
finding says and no more: a finding describes a difference and never names a cause. The
document holds names from the user's code, such as functions and shared objects, so do not
paste them into anything public unless the user asks for it.

## The skill

```
pairbench skill install --dir PATH
```

copies the skill into `PATH/pairbench`. `--dir` is required; there is no default folder. The
usual folders, as each product's public documentation describes them:

| Product | Project folder | Personal folder |
|---|---|---|
| Claude Code ([skills](https://code.claude.com/docs/en/skills)) | `.claude/skills/` | `~/.claude/skills/` |
| Codex ([skills](https://learn.chatgpt.com/docs/build-skills)) | `.agents/skills/` | `~/.agents/skills/` |
| GitHub Copilot ([agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)) | `.github/skills/` | `~/.copilot/skills/` |

For example, `pairbench skill install --dir .agents/skills`.

## The tool server

`pairbench mcp` starts a tool server over standard input and output; it needs the `mcp`
extra (`pip install "pairbench[mcp]"`). Its tools are `doctor`, `plan`, `run_status`,
`results`, `diagnostics`, `compare`, `explain`, `fill`, `selftest` and `schema`; with
`--allow-run` it adds `run_start` and `run_cancel`, which launch commands on the machine. See
the [tool server reference](reference/tool-server.md).
