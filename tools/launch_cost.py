# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Measure what a launch costs on one class of machine, and keep the results document.

The script measures from neutral places, so that the hashes the results document shows are
taken over nothing that names the machine:

* it waits on the host for a quiet machine through the tool's own quiet check
  (``pairbench gate wait-quiet``, which refuses a machine that never becomes quiet);
* it then runs ``pairbench run`` in a pinned public Python image, with this checkout reached at
  ``/work`` and run from there, ``HOME=/home/user``, the interpreter
  ``/usr/local/bin/python3``, no network, ``--memory 8g`` with ``--memory-swap 8g`` so that it
  has no swap beyond that memory, and the container removed afterwards.
  The engine census of the quiet check cannot run inside a container, so the run there checks
  the machine under ``--gates warn``;
* the run times one fixed short workload, a few lines of Python, on two command sides: the
  interpreter as it starts by default, and the same interpreter started without the ``site``
  module (``-S``). Every run of command sides times an empty launch during warm-up, so the
  results document carries ``launch_cost`` and the figures ``launch_cost.median`` and
  ``launch_cost.spread`` beside the two sides' medians;
* the run writes into a new folder under ``pairbench-runs/`` of this checkout, which the
  repository ignores, so that its capture stays private. After a passing run,
  ``tools/hash_inputs.py`` writes ``hash_inputs.json`` there and publishes ``results.json``,
  ``results.md`` and ``report.html`` into the folder given, and the sidecar with them only
  when the shared files show each value the sidecar holds; otherwise the sidecar stays
  owner-only in the private folder and one line on standard error says so. The class of
  machine is written as ``machine-class.txt`` beside them after a publish.

The folder given must be inside this checkout. The README's section on native code is filled
from the published results document::

    pairbench fill docs/readme/README.in.md \\
        --results OUT_FOLDER/results.json -o README.md

Usage::

    python tools/launch_cost.py OUT_FOLDER --machine-class "TEXT" [--engine docker] [--dry-run]

``--machine-class`` names the class of machine in a short public form: an architecture, a
count of cores and a size of memory, as in "arm64, 4 cores, 16 GB" (made-up), or the name of a
public cloud instance type, as in "m7g.xlarge", "n2-standard-8" or "Standard_D4s_v5". Any other
text is refused before anything runs, so that no host name reaches the file. The image is
pulled before the wait when the engine does not have it. ``--dry-run`` prints the commands and
runs nothing. The exit code is that of the first step that fails, the publish included.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

# The fixed short workload: the same few lines on both sides.
WORKLOAD = "total = sum(i * i for i in range(20000))"
# The class-of-machine note written beside the results.
MACHINE_CLASS_FILE = "machine-class.txt"
# The public image the run is made in, pinned by digest, and its interpreter.
PUBLIC_IMAGE = (
    "python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"
)
PUBLIC_PYTHON = "/usr/local/bin/python3"
# The neutral places of the run: the checkout inside the container, and the home folder.
WORK = "/work"
HOME = "/home/user"
REPOSITORY = Path(__file__).resolve().parents[1]
HASH_INPUTS = Path(__file__).resolve().with_name("hash_inputs.py")
# The folder of this checkout that holds run folders; the repository ignores it.
RUNS = "pairbench-runs"
EXIT_USAGE = 2
# The short public forms a class of machine is given in: an architecture, a count of cores and
# a size of memory; or a public instance type of AWS, of Google Cloud or of Azure, each part of
# which is one of a closed list. Of AWS: the series, options and sizes
# (https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-type-names.html), and the
# options f and u its accelerated types end in, as in "g6f.large" and "trn2u.48xlarge"
# (https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html). Of Google Cloud: the types
# and endings (https://docs.cloud.google.com/compute/docs/machine-resource), and the types of
# its TPU VMs, as in "ct6e-standard-4t" (https://docs.cloud.google.com/tpu/docs/v6e). Of
# Azure: the family, additive features, accelerator and version
# (https://learn.microsoft.com/en-us/azure/virtual-machines/vm-naming-conventions), with the
# further features and parts its listed sizes carry, as in "Standard_DC4as_cc_v5" and
# "Standard_M176ds-44_3_v3"
# (https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).
# An option or additive feature is one letter given once. An AWS type has at most one
# processor letter (a, g or i), first, and at most four other options before f or u; an Azure
# size has at most four additive features. So a host name, or a word with any other letter or
# with a letter given twice, does not fit; a short word made only of those letters does, as in
# "m7bend.large" or "Standard_D4prod_v5" (both made up), since no pattern tells it from a
# public name.
ARCHITECTURES = "x86_64|amd64|arm64|aarch64|ppc64le|s390x|riscv64"
AWS_SERIES = "a|c|d|dl|f|g|gr|h|hpc|i|im|inf|is|m|mac|p|r|t|trn|u|vt|x|z"
AWS_OPTIONS = "[agi]?(?![bdehnqz]*(?P<twice>[bdehnqz])[bdehnqz]*(?P=twice))[bdehnqz]{0,4}[fu]?"
AZURE_FEATURES = (
    "(?![abdefilmnoprstvx]*(?P<twice>[abdefilmnoprstvx])[abdefilmnoprstvx]*(?P=twice))"
    "[abdefilmnoprstvx]{0,4}"
)
AWS_SIZES = r"\.(?:nano|micro|small|medium|large|[0-9]*xlarge|metal(?:-[0-9]+xl)?)"
AZURE_ACCELERATORS = (
    "A10|A100|B200|GB200|GB300|H100|H200|L4|L40S|MA35D|MI200|MI300X|NDR|RTXPRO6000BSE|T4|V100"
    "|V620|V710"
)
AZURE_PARTS = "cc|flex|noIB|xl"
MACHINE_CLASSES = (
    re.compile(rf"(?:{ARCHITECTURES}), [1-9][0-9]{{0,3}} cores, [1-9][0-9]{{0,4}} GB"),
    # A series and its generation, its options, and a flexible or Blackwell GPU type.
    re.compile(rf"(?:{AWS_SERIES})[0-9]+{AWS_OPTIONS}(?:-flex|-g?b[0-9]00)?{AWS_SIZES}"),
    # High memory, by its size in TiB, and a Mac by its Apple chip.
    re.compile(rf"u(?:[0-9]+{AWS_OPTIONS})?-[0-9]+tb[0-9]*{AWS_SIZES}"),
    re.compile(r"mac[0-9]*-m[0-9]+(?:pro|max|ultra)?\.metal"),
    # A type, its count of cores, a local disk ending and a bare-metal ending, in that order.
    re.compile(
        r"[a-z][0-9][a-z]?-(?:standard|highmem|highcpu|ultramem|megamem|hypermem|highgpu"
        r"|megagpu|ultragpu|edgegpu|medium|micro|small)(?:-[0-9]+[a-z]?)?"
        r"(?:-(?:lssd|standardlssd|highlssd|nolssd))?(?:-metal)?"
    ),
    # A TPU VM type and its count of chips.
    re.compile(r"(?:ct[0-9]+(?:e|p|lp)|tpu[0-9]+x)-(?:standard|hightpu)-[0-9]+t"),
    # Constrained cores before or after the features, and memory in TiB before the version.
    re.compile(
        rf"Standard_[A-Z]{{1,3}}[0-9]+(?:-[0-9]+)?{AZURE_FEATURES}(?:-[0-9]+)?"
        rf"(?:_(?:{AZURE_PARTS}))?(?:_(?:{AZURE_ACCELERATORS}))*(?:_[0-9]+)?(?:_v[0-9]+)?"
        r"(?:_Promo)?"
    ),
)
MACHINE_CLASS_REFUSED = (
    "--machine-class: give an architecture, cores and memory (as in 'arm64, 4 cores, 16 GB') "
    "or the name of a public cloud instance type"
)

Runner = Callable[[Sequence[str]], int]


def machine_class(text: str) -> str | None:
    """The class of machine with its spaces made single, or ``None`` outside the public forms."""
    given = " ".join(text.split())
    return given if any(form.fullmatch(given) for form in MACHINE_CLASSES) else None


def private_folder(repo: Path) -> Path:
    """A new folder under ``pairbench-runs/`` of the checkout, named by the time and the process."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return repo / RUNS / f"launch-cost-{stamp}-{os.getpid()}"


def side_specs(python: str) -> tuple[str, str]:
    """The two command sides: the interpreter as it starts, and without ``site``."""
    code = shlex.quote(WORKLOAD)
    exe = shlex.quote(python)
    return (f"default=cmd:{exe} -I -c {code}", f"nosite=cmd:{exe} -I -S -c {code}")


def inner_command(relative: str) -> list[str]:
    """The ``pairbench run`` command inside the container, writing to ``relative`` under /work."""
    default, nosite = side_specs(PUBLIC_PYTHON)
    return [
        PUBLIC_PYTHON,
        "-m",
        "pairbench",
        "run",
        "--side",
        default,
        "--side",
        nosite,
        "--baseline",
        "default",
        "--gates",
        "warn",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        relative,
    ]


def build_command(
    folder: Path,
    *,
    repo: Path = REPOSITORY,
    python: str = sys.executable,
    uid: int | None = None,
    gid: int | None = None,
    engine: str = "docker",
) -> list[str]:
    """The measuring command: wait for quiet on the host, then run in the public image."""
    relative = folder.relative_to(repo).as_posix()
    user = f"{os.getuid() if uid is None else uid}:{os.getgid() if gid is None else gid}"
    return [
        python,
        "-m",
        "pairbench",
        "gate",
        "wait-quiet",
        "--",
        engine,
        "run",
        "--rm",
        "--memory",
        "8g",
        "--memory-swap",
        "8g",
        "--network",
        "none",
        "--user",
        user,
        "--volume",
        f"{repo}:{WORK}",
        "--workdir",
        WORK,
        "--env",
        f"HOME={HOME}",
        "--env",
        f"PYTHONPATH={WORK}/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        PUBLIC_IMAGE,
        *inner_command(relative),
    ]


def look_up_command(engine: str) -> list[str]:
    """The command that says whether the engine has the image."""
    return [engine, "image", "inspect", "--format", "{{.Id}}", PUBLIC_IMAGE]


def pull_command(engine: str) -> list[str]:
    """The command that pulls the image before the wait, so that no pull follows it."""
    return [engine, "pull", PUBLIC_IMAGE]


def hash_inputs_command(
    run_folder: Path, published: Path, *, python: str = sys.executable
) -> list[str]:
    """The command that writes ``hash_inputs.json`` and publishes the run's shared files, and
    the sidecar with them only when it can be shared."""
    return [python, str(HASH_INPUTS), str(run_folder), "--publish", str(published)]


def _run(command: Sequence[str]) -> int:
    return subprocess.run(list(command), check=False).returncode


def main(argv: Sequence[str] | None = None, *, run: Runner = _run, repo: Path = REPOSITORY) -> int:
    """Run the measurement and return the exit code of the first step that fails."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("folder", type=Path, help="the run folder to write; empty or absent")
    parser.add_argument(
        "--machine-class",
        required=True,
        help="the class of machine in a short public form; never a host name",
    )
    parser.add_argument("--engine", default="docker", help="the container engine to run")
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    options = parser.parse_args(argv)
    folder: Path = options.folder
    named = machine_class(str(options.machine_class))
    if named is None:
        print(MACHINE_CLASS_REFUSED, file=sys.stderr)
        return EXIT_USAGE
    checkout = repo.resolve()
    inside = folder.resolve()
    if inside != checkout and checkout not in inside.parents:
        print(
            f"the folder {folder.name} is not inside the repository, which the run reaches "
            f"at {WORK}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        print(f"the folder {folder.name} exists and is not empty", file=sys.stderr)
        return EXIT_USAGE
    engine = str(options.engine)
    private = private_folder(checkout)
    command = build_command(private, repo=checkout, engine=engine)
    writer = hash_inputs_command(private, folder)
    if options.dry_run:
        print(shlex.join(command))
        print(shlex.join(writer))
        return 0
    if run(look_up_command(engine)) != 0:
        code = run(pull_command(engine))
        if code != 0:
            return code
    code = run(command)
    if code != 0:
        return code
    code = run(writer)
    if code != 0:
        return code
    (folder / MACHINE_CLASS_FILE).write_text(named + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
