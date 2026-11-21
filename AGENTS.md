# AGENTS.md

Guidance for agents that work on this repository. For agents that use the tool, see
[docs/agents.md](docs/agents.md).

## What the project is

pairbench is a command-line tool and Python package that says whether one side is really
faster than another on a workload, or whether the difference is noise. It runs paired,
alternating rounds with an identical twin of every side, measures the noise floor from the
twins, tests each case with an exact sign test, corrects for testing several cases, and
writes a verdict per case into `results.json`.

## Set up, test and lint

```
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[plot,mcp]" pytest jsonschema ruff mypy build hatchling
pytest tests/unit tests/mutants
ruff check .
ruff format --check .
mypy src
python3 tools/docs_site.py build # the documentation site: needs Node.js 22.23.4 or newer
pairbench fill docs/readme/README.in.md --results docs/figures/launch-cost/results.json -o README.md --check
```

Python 3.11 is the oldest version supported; the tests run on 3.11 to 3.14. Tests that need
an external program, a container engine or a GPU skip visibly and say what they need.

## Layout

| Path | Holds |
|---|---|
| `src/pairbench/model.py`, `api.py`, `errors.py`, `registry.py` | the data model, the plug-in contract, the text codes, plug-in loading |
| `src/pairbench/stats/` | the sign test, the correction, the noise floor, the rule, the analysis |
| `src/pairbench/capture/`, `plan.py`, `runner.py` | the capture, the schedule, the run |
| `src/pairbench/sides/` | the kinds of side |
| `src/pairbench/drivers/` | readers of benchmark tools |
| `src/pairbench/gates/` | machine checks: quiet wait, pinning, locks, witnesses |
| `src/pairbench/energy/`, `provenance.py`, `profile/` | GPU energy, machine facts, profilers |
| `src/pairbench/diagnose/` | the explain step, findings, flame graphs |
| `src/pairbench/report/`, `results/`, `charts/`, `page/` | reports, the results writer, charts, the report page |
| `src/pairbench/cli/`, `config.py` | the command line and the config file |
| `src/pairbench/mcp/` | the tool server for AI agents |
| `skills/pairbench/` | the agent skill, shipped in the wheel as package data |
| `tests/unit/`, `tests/e2e/`, `tests/mutants/` | tests; fixtures under `tests/fixtures/` |
| `docs/`, `site/` | the documentation pages, and the project that builds the site from them; `docs/readme/README.in.md` is the README's template |
| `showcases/` | worked comparisons with configs, scripts and pinned images |

## Rules

1. Every source file starts with the licence header:
   `# SPDX-License-Identifier: Apache-2.0` and `# Copyright (c) 2026, Eugo, Inc.`
2. Fixtures are synthetic, or from a real run of a public tool on a public image, and each has
   a `*.provenance.json` sidecar written by a generator under `tests/fixtures/_gen/`.
3. In a capture, results, config or diagnostics document, renaming or removing a field or a
   value, or changing its meaning, needs a new schema version; adding an optional field, or a
   value to a field whose schema lists its values, does not.
4. No host identity in results: no host name, user name, path outside the run folder or value
   of the environment, except an image reference the user asks for and the forms that
   [SECURITY.md](SECURITY.md#known-limits-of-the-shown-command) lists as known limits of the shown command.
   Tests check this.
5. No runtime dependencies in the core. The core imports only the standard library; an extra
   is imported only inside the function that needs it.
6. Tests assert the exact exit code and text code, the stream a message goes to, and expected
   values written as constants. A fix lands with a test that fails without it.
7. README.md is generated: edit `docs/readme/README.in.md` and run `pairbench fill`.
8. A documentation page opens with front matter that holds its `description`, and
   `site/navigation.json` lists it. `llms.txt` is generated from both: run
   `python3 tools/docs_site.py llms` after changing either.

## Do not

- Do not weaken the statistical defaults: the rule `strict`, the twins, the correction, the
  fewest rounds that can give a verdict, or the positive control.
- Do not hand-edit a results file, or type a measured number into a document.
- Do not add network calls to the tool.
- Do not bundle third-party programs; invoke them as external programs and list them in
  THIRD_PARTY_NOTICES.md.
- Do not commit a diagnostics document, flame graph or report page of a real run.
