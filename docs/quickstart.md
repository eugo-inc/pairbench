---
description: "A first comparison step by step: a workload, the plan, the run, the verdict, and a number from the results put into a document."
---

# Compare two Python environments: a first run

Write a workload that prints its timings, run `pairbench run` with two sides, and read the
verdict of each case; this page does it for two Python environments and then puts a number from
the results into a document.

<!-- steps -->

1. **Install pairbench**, with the tool you use for Python programs:

   <!-- tabs -->

   **pip**

   ```
   pip install pairbench
   ```

   **uv**

   ```
   uv tool install pairbench
   ```

   **pipx**

   ```
   pipx install pairbench
   ```

   <!-- /tabs -->

2. **Write a workload.** Any command can be a workload. A workload that times itself and
   prints its timings lets pairbench leave the start of the process out; here the script
   prints one line per case for the [`lines` driver](guides/lines.md):

   ```python
   import json
   import time

   start = time.perf_counter()
   total = sum(i * i for i in range(2_000_000))
   elapsed = time.perf_counter() - start
   print("::pairbench::", json.dumps({"case": "squares", "value": elapsed, "unit": "s"}))
   ```

   Save it as `bench.py`.

3. **Print the plan.**

   ```
   pairbench plan --side new=venv:.venv-new --side old=venv:.venv-old --driver lines -- python bench.py
   ```

   The plan prints the lineup, each side followed by its twin (`new~same`, `old~same`), the
   positive control (`old~twice`), the round count, the launches and the balance of every pair.
   It launches nothing.

4. **Run it.**

   ```
   pairbench run --side new=venv:.venv-new --side old=venv:.venv-old --driver lines -- python bench.py
   ```

   Example output (made-up numbers):

   ```
   new against old (baseline)

   case     new      old      change        noise  p         verdict
   squares  0.141 s  0.152 s  1.08x faster  ±1.5%  0.00052*  FASTER

   Exact two-sided sign test over 16 paired rounds.
   * one case tested.
   Rule: strict.
   Machine state: quiet.
   Baseline: old.
   Positive control old~twice: ok.
   ```

   What each part says:

   - **change**: the median of the per-round ratios, written as "x faster" or "x slower".
   - **noise**: the bar the gap had to exceed, the sum of both sides' noise floors measured
     from their twins.
   - **p**: the exact sign test's p-value, corrected for the number of cases tested.
   - **verdict**: FASTER, SLOWER, TIE, UNRESOLVED or NO VERDICT. See [verdicts](method/verdicts.md).
   - **footer**: the rounds, the rule, the machine state, the baseline and the positive control.

   The run folder, `pairbench-runs/<time>-<id>/`, holds `capture.jsonl` (the raw record),
   `results.json` (the analysed document), `results.md`, `plan.tsv`, `report.html`, `artifacts/`
   (what each launch printed and the files its tool wrote), and, when the explain step ran,
   `diagnostics.json` and `profiles/`.

5. **Put a number into a document.** Write a template with figure tokens:

   ```
   On this machine, new ran {{fig:squares.new_vs_old.speedup}} the speed of old
   ({{fig:squares.new_vs_old.verdict}}, noise {{fig:squares.new_vs_old.bar}}).
   ```

   and fill it from the results:

   ```
   pairbench fill notes.in.md --results pairbench-runs/RUN/results.json -o notes.md
   ```

   Every token is replaced by the text of its figure. A missing figure stops the command with
   exit code 7 and lists every missing key. In an automated pipeline,
   `pairbench fill ... --check` exits 1 when the document differs from what its results give.

<!-- /steps -->

## Next

- Compare container images: `--side new=image:REF --side old=image:REF`.
- Run on a shared machine: [shared machines](method/shared-machines.md).
- Check a pull request for slowdowns: `--fail-on worse` makes the exit code 1 when a primary
  case comes out worse.
- Read the [command reference](reference/commands.md).
