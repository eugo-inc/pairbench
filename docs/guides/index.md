---
description: "A driver turns one launch into one value per case; the table of built-in drivers, what each reads and its default primary cases."
---

# Which driver reads my benchmark?

The driver named for the tool that produces your numbers, chosen with `--driver NAME`
(`workload.driver`); without one, `wall` times each launch. A driver turns one launch into one
value per case, and pairbench never asks a tool to compare two things itself.

| Driver | Reads | Value per launch | Default primary cases | Status |
|---|---|---|---|---|
| [`wall`](wall.md) | the launch's own clock | the run time of the launch | `wall` | tested |
| [`lines`](lines.md) | lines the workload prints | the printed value | every printed case | tested |
| [`gbench`](gbench.md) | Google Benchmark JSON | median real time of the repetitions | real time of every benchmark | tested |
| [`nvbench`](nvbench.md) | NVBench JSON | the tool's mean GPU time | GPU time of every state | tested |
| [`pytest-benchmark`](pytest-benchmark.md) | pytest-benchmark JSON | median of the per-round data | every test | tested |
| [`hyperfine`](hyperfine.md) | hyperfine JSON export | median of the run times | every command | tested |
| [`perf`](perf.md) | `perf stat` output | the counter value | none: all secondary | tested |
| [`llama-bench`](llama-bench.md) | llama-bench JSON | median tokens per second | generation tests | tested |
| [`guidellm`](guidellm.md) | GuideLLM report, per load level | computed from per-request records | see the guide | tested |
| [`aiperf`](aiperf.md) | AIPerf per-request records, per load level | computed from per-request records | see the guide | tested |
| [`vllm-bench`](vllm-bench.md) | `vllm bench serve` result file, per load level | the saved summary value | output token rate | experimental |

"Tested" means the driver ships with a fixture from a real run of the tool at a recorded
version on a public image, a file that says how it was made, and a test with a malformed
file. A driver without such a fixture is marked experimental in `pairbench doctor` and here.

## What every driver shares

- **Its own output option.** A driver adds the tool's output option when the command does
  not have it, pointing at a folder of its own for each launch (mounted into container
  sides). A command that already names that option is refused, so the file read is always
  the one this launch wrote. Files a container writes there, a server's container included,
  belong to the image's user, often root; after the launch pairbench gives them back to you
  with one short container of the same image that runs `chown`, and when it cannot (no
  `chown` in the image, or a rootless engine), a loud note names the folder.
- **Inner samples.** When a tool gives several inner samples for a case, the value is their
  median and the results say so (`reducer`). When a tool gives only its own summary, the
  reducer is `tool_summary`.
- **Version.** The driver records the tool's version. A major version the driver was not
  tested with is a loud note, not a refusal.
- **Primary cases.** Each driver names default primary cases; `cases.primary`, a list of glob
  patterns, chooses others.
- **Resource cases.** Whatever the driver, a launch also gives the cases under `res/`. A
  driver's own case id may not start with `res/` or `startup/`.
- **Case ids.** A case id is shown in the results, so every absolute path in it, and every
  relative path that climbs out of its folder with `..`, is cut to its last part when the
  driver's output is read, and the capture records the id as cut. A path starts where a value
  starts (after `[`, `=`, `:` or a space, for example), also with two `/` or more at the start
  of the id or after a space (`run //made/up/in.bin` shows `run in.bin`); the `/` that joins
  the parts of a name, as in `BM_made_up<int>/8/cpu_time`, is kept. A path also starts at three
  `/` or more after one of `[`, `=`, `,`, `;`, `(`, `{`, `@` or a quote
  (`test_read[///made/up/in.bin]` shows `test_read[in.bin]`), and at two `/` or more after the
  `/` that ends a part of a name when two more parts follow (`BM_Read///made/up/in.bin` shows
  `BM_Read/in.bin`). After `:` the `/` start an address (`file:///made/up/in.bin` shows
  `file://in.bin`), and two `/` after one of the other marks start the path at the second
  (`test_read[//made/up/in.bin]` shows `test_read[/in.bin]`). The secret forms the shown
  command hides are hidden in a case id too: the user part of an address after a scheme
  (`test_get[https://bench:made-up@db.example/x]` shows
  `test_get[https://<hidden>@db.example/x]`), the value of a credential-like name or option
  glued to it with `=` or `:` (`test_db[token:made-up]` shows `test_db[token:<hidden>]`), a
  password before a host written without a scheme, and a long random-looking value, and the
  words in a pair of brackets are read as the words of a command, so
  `bench[redis-cli -a made-up PING]` shows `bench[redis-cli -a <hidden> PING]`, and a
  credential's value that a program's text in them gives as a string is hidden, so
  `bench[python -c "password = 'made-up'"]` shows `bench[python -c "password = '<hidden>'"]`.
  When the cut of an id drops a word that holds no `/`, its name ends with a mark, a space, `+`
  and eight hex digits the run makes with its own key from the words of the id that hold no
  `/`, so `test_read[/made/up/in.csv fast mode/x]` and `test_read[/made/up/in.csv slow mode/x]`
  show as `test_read[x]` with two marks, such as `test_read[x] +3c5e7a91` and
  `test_read[x] +b04d2f68`, and each keeps its mark in every launch and on every side of the
  run. Two ids of one launch that differ only in their folders, such as
  `test_read[/made/up/a/in.csv]` and `test_read[/made/up/b/in.csv]`, are refused with
  `E_USAGE`, and so are two that differ only in a hidden secret, such as
  `test_db[token:made-up]` and `test_db[token:made-up-2]`, and two that differ only in their
  folders and a hidden secret. An id whose folders or secret alone differ from one side or
  launch to the next names one case, and the run pairs it with itself.
  [Case ids that read alike](../reference/config.md#what-the-shared-files-hide) says what a
  mark does across runs. A case that
  `hyperfine` names after its command is cleaned as the shown command is, so its host is
  hidden: `curl https://db.example/x` gives `curl https://<hidden>/x`. Any other host, and a
  user written without a scheme, show in a case id, as the
  [known limits](../../SECURITY.md#known-limits-of-the-shown-command) say, so give a case that
  takes an address a name that holds none. So does a password before a host where the same part
  of the id gives a credential-like name a value with `=` after the host. A case id, the name of
  a case that `hyperfine` names after its command included, keeps the name of a home folder: a
  word that starts with `~` and a name, with nothing after it, as typed, and a path that ends
  at a folder right under `/home` or `/Users` cut to that folder's name, since such a word is
  often no home (`test_invert[~mask]`) and such a path is often a route (`test_get[/users/1]`
  shows `test_get[1]`), so a user's home shows its name; name a file inside the home instead.
- **File sides.** A `file` side hands each driver one result file per round, from a run made
  elsewhere, and the driver reads it as it would read its own output. A file side may name its
  own driver (`format`); the results then name each side's driver, and sides read by
  different drivers get the loud note `drivers_differ`.

## Other guides

- [An image that holds `perf`](perf-in-an-image.md), for counters and stacks of image sides.
- [Plug-in API](../reference/plugin-api.md), to add a driver of your own.
