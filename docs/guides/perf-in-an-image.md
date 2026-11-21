---
description: "What an image side needs for the perf driver and for the counters and stacks of the explain step: the program in the image and the capability to count."
---

# Build an image that holds perf

Install `perf` in the image and give the container the capability to use performance counters;
both the `perf` driver and the explain step run `perf` inside the side.

The [`perf` driver](perf.md) and the counters and stacks of the
[explain step](../method/diagnostics.md) run `perf` inside the side. For an image side, the
image must hold the program and the container needs the capability to use performance
counters. For the counters and stacks of the explain step, `perf` runs in front of the whole
command line the container would run, the image's entrypoint followed by the side's arguments
or the image's default command, and takes the entrypoint's place for that launch; an image
with an entrypoint is instrumented the same way. The `perf` driver's command is the side's
arguments, so an image with an entrypoint receives it as the entrypoint's arguments.

## The recipe

Add `perf` to an image derived from the one you compare. On a Debian-based image the package
is `linux-perf`:

```dockerfile
FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends linux-perf \
 && rm -rf /var/lib/apt/lists/*
```

On an Ubuntu-based image the program comes with the `linux-tools-common` and
`linux-tools-generic` packages; on a Fedora-based image the package is `perf`. Check the
result with `docker run --rm IMAGE perf --version`.

Build the derived image of both sides in the same way, so that they differ in nothing but the
change you compare.

## The capability

```toml
[launch]
perf_counters = true
```

or `--set launch.perf_counters=true`. This gives the container the capability to use
performance counters, and nothing else. Its default is `false`; pairbench never adds a
capability that was not asked for.

The host's own setting for performance events still decides what may be counted. pairbench
never changes it; when it forbids an instrument, the skip note and `pairbench doctor` name
the setting.

## Without perf in the image

When the image does not hold `perf`, the explain step skips the `counters` and `stacks`
instruments for that side with a loud note. If the image's whole command line, its
entrypoint followed by the command, starts with a Python interpreter, the explain step uses
its own Python-frame sampler, `pystacks`, which needs no privilege and nothing in the image.
The resource figures under `res/` come from the engine and need nothing either.

`perf` is an external program, not bundled. Its output holds names from your code; read it
before you publish it.
