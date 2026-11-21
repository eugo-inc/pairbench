---
description: "The hyperfine driver runs hyperfine once per side per round and compares the median run time of each command from its JSON export."
---

# Compare commands timed by hyperfine

Pass `--driver hyperfine` and run hyperfine as the workload: pairbench reads its JSON export
and compares the median run time of each command.

Format read from the tool's own source, `src/export/json.rs` at v1.21.0 and v2.0.0
([source](https://github.com/sharkdp/hyperfine/blob/v2.0.0/src/export/json.rs)), and checked
against the exports of real runs of the release binaries 1.21.0 and 2.0.0.

## What it adds to the command

`--export-json <file>`. A command that already names `--export-json` is refused.

## What it reads

The driver detects the layout from the file:

- without `schema_version` (the 1.x layout), each entry of `results[]` names its command in
  `command` (the name given with `--command-name` when there is one) and lists its run times
  in seconds in `times`;
- with `schema_version` 2, each entry names its command in `name` when one was given and in
  `command` otherwise, and each of its `measurements[]` holds `time_wall_clock.value` in
  seconds.

One case per command, holding the median of its run times, primary by default. Another
schema version, another unit, or a run that exited with a code other than zero or without an
exit code is refused: a time of a failed run is no time of the command. The version is
`metadata.hyperfine_version` in the newer layout.

## Example

hyperfine runs inside each side; pairbench compares the sides.

```
pairbench run --side new=image:myorg/cli:2.0 --side old=image:myorg/cli:1.9 \
  --driver hyperfine -- hyperfine --runs 10 --command-name convert 'mytool convert input.dat'
```

Give each command a name with `--command-name` so that the case names stay the same on both
sides. A command without a name gives its case the command's text, with every absolute path, and
every relative path that climbs out of its folder with `..`, cut to its last part and every
secret form that [what the shared files hide](../reference/config.md#what-the-shared-files-hide) lists hidden,
the host of an address among them, because a case name is shown in the results. Two commands that differ only in a folder or a host, such as `/made/up/v1/bench`
and `/made/up/v2/bench`, would then have one name; they are refused with `E_USAGE` (exit 2)
until each has a name of its own. hyperfine's own comparison of several commands in one invocation is not used; each
command is a case, compared across the sides.

Tool documentation: [hyperfine README](https://github.com/sharkdp/hyperfine).
