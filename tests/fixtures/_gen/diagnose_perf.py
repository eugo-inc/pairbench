# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Generate the ``perf`` fixtures of the diagnostics tests from a real run.

The run happens in a short container of the public image ``debian:trixie-slim``
with the capability to use performance counters (``--cap-add PERFMON``) and
nothing else. Inside it, ``linux-perf`` and ``python3-minimal`` are installed
from the distribution, and a small Python workload written below (its function
names are made up) runs once under ``perf stat`` and once under ``perf record``,
with the same options the ``counters`` and ``stacks`` instruments use.
``perf script`` and ``perf buildid-list`` read the recording inside the same
container.

Three steps::

    python tests/fixtures/_gen/diagnose_perf.py prepare --work DIR
    python tests/fixtures/_gen/diagnose_perf.py run --work DIR --name NAME
    python tests/fixtures/_gen/diagnose_perf.py write --work DIR

``write`` copies the outputs into ``tests/fixtures/diagnose/`` and replaces
these with visibly synthetic values: every instruction address and every time
stamp of ``perf script``, the start line of ``perf stat`` and the build ids of
the kernel's own objects. Everything else is kept as the run wrote it,
including values that describe the machine: the PMU names in the event names,
and every counter value of ``perf stat`` with the time each counter ran and the
figures perf derives from them, such as instructions per cycle, GHz, CPUs
utilized and rates per second. It refuses unless every step of the run exited
with zero. Each fixture gets a ``*.provenance.json`` sidecar.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

IMAGE = "debian:trixie-slim"
HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "diagnose"
GENERATOR = "tests/fixtures/_gen/diagnose_perf.py"

COUNTER_EVENTS = (
    "instructions,cycles,branches,branch-misses,cache-references,cache-misses,"
    "task-clock,context-switches,cpu-migrations,page-faults"
)
SCRIPT_FIELDS = "comm,pid,tid,time,event,ip,sym,dso"

WORKLOAD = """\
import hashlib
import json


def spin_numbers(count):
    total = 0
    for number in range(count):
        total += number * number
    return total


def hash_rounds(rounds):
    data = b"made-up input"
    for _ in range(rounds):
        data = hashlib.sha256(data).digest()
    return data


def encode_records(rounds):
    text = ""
    for number in range(rounds):
        text = json.dumps({"round": number, "items": list(range(40))})
    return text


def main():
    for _ in range(6):
        spin_numbers(300000)
        hash_rounds(60000)
        encode_records(8000)


main()
"""

INSIDE = f"""\
#!/bin/sh
# Runs inside the container; /out is the work folder.
set -u
trap 'chown -R "$HOST_UID:$HOST_GID" /out' EXIT
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/out/apt.log 2>&1
apt-get install -y -qq --no-install-recommends linux-perf python3-minimal >>/out/apt.log 2>&1
dpkg-query -W -f='${{Package}} ${{Version}}\\n' 'linux-perf*' python3-minimal \\
  >/out/packages.txt 2>&1
perf --version >/out/perf-version.txt 2>&1
python3 --version >/out/python-version.txt 2>&1
cp /out/workload.py /tmp/workload.py
cd /tmp
perf stat -x ';' -o /out/perf-stat.txt -e {COUNTER_EVENTS} -- python3 /tmp/workload.py \\
  >/out/stat-stdout.txt 2>/out/stat-stderr.txt
echo $? >/out/stat-rc.txt
PYTHONPERFSUPPORT=1 perf record -F 99 --call-graph fp --buildid-all -o /tmp/perf.data \\
  -- python3 /tmp/workload.py >/out/record-stdout.txt 2>/out/record-stderr.txt
echo $? >/out/record-rc.txt
perf script -i /tmp/perf.data -F {SCRIPT_FIELDS} >/out/perf-script.txt 2>/out/script-stderr.txt
echo $? >/out/script-rc.txt
perf buildid-list -i /tmp/perf.data >/out/perf-buildids.txt 2>/out/buildids-stderr.txt
echo $? >/out/buildids-rc.txt
echo done >/out/finished.txt
"""


def prepare(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "workload.py").write_text(WORKLOAD, encoding="utf-8")
    (work / "inside.sh").write_text(INSIDE, encoding="utf-8")


def pinned(repo_digests: str) -> str:
    """The image as ``name:tag@sha256:...``, from the image's RepoDigests list."""
    try:
        first = json.loads(repo_digests)[0]
    except (ValueError, IndexError, TypeError, KeyError):
        return IMAGE
    if not isinstance(first, str) or "@" not in first:
        return IMAGE
    return f"{IMAGE}@{first.split('@', 1)[1]}"


def run(work: Path, name: str) -> int:
    prepare(work)
    digest = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    (work / "image.txt").write_text(f"{pinned(digest.stdout)}\n", encoding="utf-8")
    argv = [
        "docker",
        "run",
        "--rm",
        "--memory",
        "8g",
        "--memory-swap",
        "8g",
        "--cpus",
        "4",
        "--name",
        name,
        "--cap-add",
        "PERFMON",
        "-e",
        f"HOST_UID={os.getuid()}",
        "-e",
        f"HOST_GID={os.getgid()}",
        "-v",
        f"{work.resolve()}:/out",
        IMAGE,
        "sh",
        "/out/inside.sh",
    ]
    return subprocess.run(argv, check=False).returncode


_ADDRESS = re.compile(r"^(\s+)([0-9a-f]+)(\s)")
_TIME = re.compile(r"(\s)(\d+\.\d{6}):")
_STARTED = re.compile(r"^# started on .*$", re.MULTILINE)


def synthetic_script(text: str) -> str:
    """Replace each instruction address and each time stamp with a made-up one."""
    addresses: dict[str, str] = {}
    out: list[str] = []
    tick = 0
    for line in text.splitlines():
        found = _ADDRESS.match(line)
        if found:
            real = found.group(2)
            made_up = addresses.setdefault(real, f"{0xAA0000 + 16 * len(addresses):x}")
            line = found.group(1) + made_up + found.group(3) + line[found.end() :]
        elif line and not line[0].isspace():
            tick += 1
            stamp = f"{1000 + tick / 100:.6f}"
            line = _TIME.sub(rf"\g<1>{stamp}:", line, count=1)
        out.append(line)
    return "\n".join(out) + "\n"


def synthetic_buildids(text: str) -> str:
    """Replace the build ids of the kernel's own objects with zeros.

    An object in brackets, such as ``[kernel.kallsyms]`` or ``[vdso]``,
    belongs to the running kernel; every other object belongs to a public
    package of the image.
    """
    out: list[str] = []
    for line in text.splitlines():
        build_id, _, path = line.partition(" ")
        if path.startswith("["):
            line = f"{'0' * len(build_id)} {path}"
        out.append(line)
    return "\n".join(out) + "\n"


def check_run(work: Path) -> None:
    """Refuse to write fixtures unless every step of the run finished and exited with zero."""
    if not (work / "finished.txt").is_file():
        raise SystemExit(f"the run in {work} did not finish")
    for step in ("stat", "record", "script", "buildids"):
        rc = (work / f"{step}-rc.txt").read_text(encoding="utf-8").strip()
        if rc != "0":
            raise SystemExit(f"step {step} of the run exited with {rc}")


def synthetic_stat(text: str) -> str:
    """Replace the start line of perf stat with a made-up date."""
    return _STARTED.sub("# started on Thu Jan  1 00:00:00 1970", text)


def _first_line(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip().splitlines()[0]


def write(work: Path) -> None:
    check_run(work)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    image = _first_line(work / "image.txt")
    perf_version = _first_line(work / "perf-version.txt")
    python_version = _first_line(work / "python-version.txt")
    made = {
        "perf-script.txt": (
            synthetic_script((work / "perf-script.txt").read_text(encoding="utf-8")),
            f"perf script -F {SCRIPT_FIELDS} of perf record -F 99 --call-graph fp --buildid-all",
            "every instruction address and every time stamp replaced by made-up values",
        ),
        "perf-buildids.txt": (
            synthetic_buildids((work / "perf-buildids.txt").read_text(encoding="utf-8")),
            "perf buildid-list of the same recording",
            "the build ids of the kernel's own objects replaced by zeros",
        ),
        "perf-stat.txt": (
            synthetic_stat((work / "perf-stat.txt").read_text(encoding="utf-8")),
            f"perf stat -x ';' -e {COUNTER_EVENTS}",
            "the start line replaced by a made-up date; every other line kept as perf printed "
            "it in the run: the counter values, how long each counter ran and for what share "
            "of the run, the figures perf derives from them (such as instructions per cycle, "
            "GHz, CPUs utilized and rates per second) and the PMU names",
        ),
    }
    for name, (text, command, replaced) in made.items():
        (FIXTURES / name).write_text(text, encoding="utf-8")
        sidecar = {
            "generator": GENERATOR,
            "seed": None,
            "tool": "perf",
            "version": perf_version,
            "synthetic": False,
            "image": image,
            "command": command,
            "workload": f"the made-up Python workload of the generator, run by {python_version}",
            "environment": "--cap-add PERFMON and no other capability",
            "replaced": replaced,
        }
        (FIXTURES / f"{name}.provenance.json").write_text(
            json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("prepare", "run", "write"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--name", default="pairbench-fixture-perf")
    args = parser.parse_args(argv)
    if args.step == "prepare":
        prepare(args.work)
        return 0
    if args.step == "run":
        return run(args.work, args.name)
    write(args.work)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
