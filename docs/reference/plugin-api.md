---
description: "How a package adds sides, drivers, capture readers, machine checks, rules, reporters or server launchers through entry points, and what each must do."
---

# Add a driver, reader, rule or other plug-in

pairbench loads its own sides, drivers, readers, machine checks, rules, reporters and server
launchers through package entry points, and a third-party package can add more through the
same groups.

| Group | Protocol in `pairbench.api` | Adds |
|---|---|---|
| `pairbench.side_kinds` | [`SideKind`](python-names.md#pairbench.api.SideKind) | a kind of side |
| `pairbench.drivers` | [`Driver`](python-names.md#pairbench.api.Driver) | a reader of one launch |
| `pairbench.capture_readers` | [`CaptureReader`](python-names.md#pairbench.api.CaptureReader) | a reader of a capture file for `compare --reader` |
| `pairbench.gates` | [`Gate`](python-names.md#pairbench.api.Gate) | a machine check |
| `pairbench.rules` | [`RuleProvider`](python-names.md#pairbench.api.RuleProvider) | a named verdict rule for `--rule` |
| `pairbench.reporters` | [`Reporter`](python-names.md#pairbench.api.Reporter) | a report format |
| `pairbench.launchers` | [`Launcher`](python-names.md#pairbench.api.Launcher) | a way to start a server |

## Rules for every plug-in

1. Each plug-in declares `api_version`. The current version is
   `pairbench.registry.API_VERSION` (1). A mismatch is a loud load failure.
2. Plug-ins load from package entry points and from a call,
   `pairbench.registry.register(group, name, obj)`, for code that has no package metadata.
3. A plug-in that fails to load is printed on standard error, listed by `pairbench doctor`
   and recorded in the results as a count. Plug-in names are never written to a results
   file.
4. `--no-plugins` disables every plug-in outside the package.

## A driver

<!-- example -->
```python
from pathlib import Path
from typing import Literal

from pairbench.api import DriverContext, Invocation, Sample


class MyToolDriver:
    name = "mytool"
    api_version = 1
    where: Literal["in_side", "client"] = "in_side"

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Add the tool's own output option, pointing into ctx.artifacts_in_side."""
        ...

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return one Sample per case from the files the launch wrote."""
        ...

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Name the cases that count toward the verdict."""
        ...
```

and in the plug-in's `pyproject.toml`:

```toml
[project.entry-points."pairbench.drivers"]
mytool = "mytool_pairbench:MyToolDriver"
```

What a driver must do:

- `prepare` adds the tool's own output option when the command lacks it, pointing at the
  launch's own folder, and changes nothing else. A driver that needs a command to add its
  option to refuses an empty one with `E_USAGE`.
- `read` returns one `Sample(case, metric, unit, better, kind, value, n_inner, reducer)` per
  case. When the tool gives several inner samples for a case, the value is their median.
  Output it cannot read is refused with `E_LAUNCH_FAILED`; a case the tool skipped is left
  out and reported through `ctx.note`.
- A case id may not start with `res/` or `startup/`.
- The runner cuts every absolute path in a case id, and every relative path that climbs out of
  its folder with `..`, to its last part before it records the case
  (`pairbench.model.public_case`), and names the ids through `ctx.case_names`, the names
  of the run (`pairbench.api.CaseNames`): an id whose cut drops a word that holds no `/`
  is named with a mark, ` +` and eight hex digits made with the run's own key from those
  words (`pairbench.model.case_suffix`), so two ids cut alike get two names, and an id gets
  the same name in every launch and on every side of the run. Secrets are hidden first: two
  ids that differ only in a hidden secret, or only in their folders once their secrets are
  hidden, are refused with `E_USAGE`, and so is an id whose cut ends like a mark. A path starts
  where a value starts, so the `/` that joins the parts of a name (`BM_made_up<int>/8`) is
  kept. A driver that adds a part to a name its tool gave, such as `/cpu_time`, names every
  name the tool lists, skipped ones too, with `ctx.case_names.names(...)` before it adds the
  part, and sets `cleans_case_ids = True`: the runner then records its ids as they are, so a
  name cut to a file and the part after it (`file://m.gguf/cpu_time`) are not read again as
  the host and the path of an address. Without the names of a run (`ctx.case_names` is
  `None`), as when a driver is called outside a run, a name that needs a mark is refused with
  `E_USAGE`, as is a pair that differ only in a hidden secret or in their folders.
- A driver that can tell the version of its tool implements `tool_version`, and a major
  version it was not tested with gives a loud note.

A new driver in this repository needs a link to the tool's public documentation, a fixture
from a real run with its provenance file, and a test with a malformed file. See
`CONTRIBUTING.md`.

## A capture reader

```python
class CaptureReader(Protocol):
    name: str
    api_version: int

    def sniff(self, path: Path, head: bytes) -> bool: ...
    def read(self, path: Path) -> list[Capture]: ...
```

`sniff` says whether the reader recognises a file from its first bytes. `read` returns one
capture per run the file holds; `Capture.from_rows` builds one from rows.

## A rule

A `RuleProvider` has `name`, `api_version` and `rule()`, which returns a
[`Rule`](python-api.md#rules). The results record every field of the rule used.

## The others

`SideKind` (`resolve` and `look_up`), `Gate` (`check`), `Reporter` (`render`) and `Launcher`
(`resolve`, `look_up`, `start`) are described, with every type they take and return, on
[every public Python name](python-names.md#pairbench.api), written from the docstrings of
`pairbench.api`. The built-in
implementations are registered in the package's own `pyproject.toml` and are the best
examples.
