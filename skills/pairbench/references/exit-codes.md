# Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | completed and results written, whatever the verdicts | read `results.json` |
| 1 | a requested check failed: `--fail-on` matched, a self-test control failed, `fill --check` found a stale document | report which check |
| 2 | usage or config error (`E_USAGE`, `E_CONFIG`) | fix the command or the config |
| 3 | a side was refused in preflight | read the text code: an image not found, two sides that are the same, a side that cannot be identified |
| 4 | the machine was refused: a check under `enforce`, or a lock | wait, or run with `--gates warn` and say so in the report |
| 5 | a launch failed; the capture is kept and marked | read the launch's output in the run folder; `pairbench compare --allow-incomplete` analyses the complete rounds |
| 6 | the analysis was refused | read the text code, such as `E_TOO_FEW_ROUNDS` or `E_GRID` |
| 7 | `fill`: a figure is missing | every missing key is listed |
| 8 | internal error | report it as a bug |
| 130 | interrupted | the capture is marked `interrupted` |

Every refusal prints its line on standard error, `E_CODE: message`, then a line
`pairbench: see ADDRESS` with the address of the code's cause and fix in the documentation. It
is listed in `refusals[]` of the results when results were written. `pairbench doctor` always
exits 0.

## Text codes

| Text code | Exit | Meaning |
|---|---|---|
| `E_USAGE` | 2 | the command line or a library call was given something invalid |
| `E_CONFIG` | 2 | the config holds an unknown key or an invalid value |
| `E_SAME_SIDE` | 3 | two different sides have the same fingerprint, run in the same working folder and differ at most in a credential's value |
| `E_SIDE_UNIDENTIFIED` | 3 | a side could not be identified, or its identify command gave no output or failed |
| `E_SIDE_UNRESOLVED` | 3 | an image, executable, interpreter or working folder was not found |
| `E_ENTRYPOINT_UNREADABLE` | 3 | an image side runs the shared workload and the entrypoint of its image could not be read |
| `E_ENGINE_UNSUPPORTED` | 3 | the container engine or the kind of side cannot do what was asked |
| `E_PROFILER_MISSING` | 3 | the named profiler is not installed |
| `E_PLOT_EXTRA_MISSING` | 3 | charts were asked for and the plot extra is not installed |
| `E_TWIN_DRIFT` | 3 or 6 | a twin's fingerprint differs from its side's; exit 3 when found as the run starts, exit 6 when found in analysis |
| `E_GATE_FAILED` | 4 | a machine check failed under enforce |
| `E_GATE_UNAVAILABLE` | 4 | a machine check could not run under enforce |
| `E_LOCK` | 4 | a lock could not be taken: timeout or error |
| `E_PIN_UNSUPPORTED` | 4 | CPU pinning was asked for where it cannot be done |
| `E_CPUS_MIXED_TYPES` | 4 | the pinned CPU set mixes core types |
| `E_LAUNCH_FAILED` | 5 | a launch exited non-zero, timed out, or gave output the driver cannot read |
| `E_SIDE_CHANGED` | 5 | a side's identity changed during the run |
| `E_GPU_NOT_RELEASED` | 5 | GPU memory did not return to its level in time |
| `E_TOO_FEW_ROUNDS` | 6 | fewer rounds are planned than can give a verdict |
| `E_CASES_DIFFER` | 6 | the sides produce different sets of primary cases |
| `E_BUDGET` | 6 | no balanced round count fits the time budget |
| `E_CAPTURE_INCOMPLETE` | 6 | a capture has no end record |
| `E_GRID` | 6 | the observed grid of rounds and lineup entries does not match the lineup |
| `E_TWIN_ORPHAN` | 6 | a twin's side is absent |
| `E_ORDER_NOT_VARIED` | 6 | a compared pair ran in the same order every round |
| `E_POOL_SAME` | 6 | the same capture id, file path or file hash was given twice |
| `E_POOL_IDENTICAL_ROWS` | 6 | two captures with different ids hold identical observation rows |
| `E_POOL_TRUNCATED_COPY` | 6 | one capture's rows are a contiguous stretch of another's |
| `E_POOL_SIDE_DRIFT` | 6 | a side's fingerprint, its recorded setup in more than a credential's value, its working folder, or the shared workload in more than a credential's value differs between captures |
| `E_POOL_CASES` | 6 | the case sets or units differ between captures |
| `E_POOL_MACHINE` | 6 | the CPU or GPU identity differs between captures |
| `E_POOL_MIXED_PURPOSE` | 6 | a capture of one side against its own twins is pooled with a comparison of sides |
| `E_FIGURE_MISSING` | 7 | a document names a figure that is absent |
| `E_INTERNAL` | 8 | internal error |
| `E_INTERRUPTED` | 130 | the run was interrupted |
