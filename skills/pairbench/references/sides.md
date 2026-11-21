# Choosing the sides

A side is one thing being compared. On the command line it is `--side NAME=KIND:SPEC`,
repeated; in a config file it is a `[sides.NAME]` table.

| Kind | Spec | A launch is |
|---|---|---|
| `image` | a container image reference | a fresh container, started by image ID and removed after |
| `cmd` | a full command line, or one with `{workload}` in it | one process on the host |
| `python` | an interpreter path | the workload run with that interpreter |
| `venv` | a virtual environment folder | the workload run with its interpreter |
| `conda` | a conda environment name | the workload run with its interpreter |
| `serve` | a server image, from the config file | a server start with a load tool driving it |
| `file` | a glob of result files from another tool | nothing; only `pairbench compare` reads them |

- The baseline is the last side named, or the one given by `--baseline NAME`.
- A name is not empty and holds no `~`, `=` or white space, and is not `.` or `..`; `~` is kept
  for the twin (`NAME~same`) and the positive control (`NAME~twice`).
- A `cmd` side without `{workload}` runs exactly its own command; giving a shared workload as
  well is a usage error.
- Two sides that are the same thing (equal fingerprints, one working folder) are refused with
  `E_SAME_SIDE`. Two sides that differ only in a value hidden for its shape, such as a run of
  hexadecimal digits in a path, in what a hidden credential value holds besides the credential
  itself (the words after it, a client command's other words, an address's user, host and
  path), or in their working folder (one program run from two checkouts), are compared, with
  the note `sides_differ_in_hidden_value`. With `--allow-identical`, sides that are one side are
  compared with the note `sides_declared_identical`.

## Choosing the driver

The driver says what a launch's values are.

| Driver | Values |
|---|---|
| `wall` (default) | the run time of each launch, start-up included |
| `lines` | `::pairbench::` lines the workload prints, for timings it takes itself |
| `gbench`, `nvbench`, `pytest-benchmark`, `hyperfine`, `llama-bench` | that tool's JSON output |
| `perf` | `perf stat` counters |
| `guidellm`, `aiperf`, `vllm-bench` | load-tool reports for a serving side |

When a `wall` value is short, the cost of starting a process can move the ratio toward 1;
the run says so in a note. Use `lines` to time the work alone.

## On a shared machine

- `--wait-quiet` waits for a quiet machine before the first round; with `--gates off` it is refused (`E_USAGE`), because off skips the checks before the run.
- `--cpus LIST` pins every launch to a CPU set; pairbench moves itself off it where it can.
- `--lock PATH` takes a lock that other runs on the machine also take.
- Rounds a witness marks as disturbed are set aside in a second analysis; a verdict that
  changes is downgraded to UNRESOLVED.
