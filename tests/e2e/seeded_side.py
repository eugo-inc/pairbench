# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A side for the end-to-end tests: it prints made-up values as the ``lines`` driver reads them.

    python seeded_side.py --factor F [--name N] [--seed S | --seed-file PATH] [--wait SECONDS]
        [--folder FOLDER [--form addresses]]

Each value is ``F`` times a base value of its case, times a small seeded
wobble. The wobble depends on the seed, the case, the round and whether the
launch is a twin; it never depends on the factor or the name. So in one
round every side reads exactly ``F`` times what a side of factor 1 reads,
which makes the ratio of two sides exact, while a side and its twin read a
little apart, which gives the noise floor a width above zero.

The round is told by the length of the environment pad the runner adds
under ``--vary-env-size``; without it every round reads the same wobble.
A twin is told by the folder of the launch's own output file, whose name
ends in ``_same``. ``--name`` only makes two sides of one factor differ.
``--wait`` sleeps that long inside ``e2e_privacy_marker_qz7``, a function
whose name a stack sampler records and no results file may hold.
``--seed-file`` reads the seed from a file, so two runs of one command can
read different values. ``--folder`` names each case by a path under that
folder that runs on over a word of its own, ``read FOLDER/in.bin Zq<case> x/y``;
the wobble stays keyed on the case alone, so sides that name other folders
still read exact ratios. ``--form slashes`` starts that path with one more
``/``. ``--form addresses`` names each case instead by two addresses and a
path in a query under that folder, with a word of the case between them, as
``FORMS`` writes it. ``--form credential`` names each case by a credential
written as a path under that folder, and ``--form credential-blank`` by the
same through one more folder whose name holds a blank. ``--form bracket``
names each case by a path under that folder that starts with three ``/``
after a bracket. ``--form nested`` names each case by a local address under
that folder in the query of an address with no host, and ``--form climb`` by a
path that climbs two folders up and then down to that folder, in the same place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

BASES = {"alpha": 0.125, "beta": 0.5, "gamma": 2.0}
WOBBLE = 0.05
PAD_VARIABLE = "PAIRBENCH_ENV_PAD"
# The case names of ``--folder``, by ``--form``.
FORMS = {
    "path": "read {folder}/in.bin Zq{case} x/y",
    "slashes": "read /{folder}/in.bin Zq{case} x/y",
    "addresses": "get unix://{folder}/Zq dir/s.sock?db=0 {case} "
    "https://h.example/p?next={folder}/Zq dir/d unix://{folder}/Zqhome/t.sock",
    "credential": "test_db[token:{folder}/x.pem] {case}",
    "credential-blank": "test_db[token:{folder}/Zq dir/x.pem] {case}",
    "bracket": "test_read[//{folder}/Zqhome/in.bin] {case}",
    "nested": "test_conn[postgresql:///db?sslrootcert=file://{folder}/Zqhome/ca.pem] {case}",
    "climb": "x postgresql:///db?sslrootcert=../..{folder}/Zqhome/ca.pem {case}",
}


def is_twin() -> bool:
    """Say whether the launch's output goes into the folder of a twin."""
    try:
        target = os.readlink("/proc/self/fd/1")
    except OSError:
        return False
    return any(part.endswith("_same") for part in Path(target).parts)


def wobble(seed: int, case: str, round_key: int, twin: bool) -> float:
    """A factor near 1, the same for every side of one round, different for a twin."""
    digest = hashlib.sha256(f"{seed}/{case}/{round_key}/{int(twin)}".encode()).digest()
    unit = int.from_bytes(digest[:8], "big") / 2**64
    return 1.0 + WOBBLE * (2.0 * unit - 1.0)


def e2e_privacy_marker_qz7(seconds: float) -> None:
    """Wait inside a function whose name is the privacy marker."""
    time.sleep(seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factor", type=float, required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--wait", type=float, default=0.0)
    parser.add_argument("--seed-file", default="")
    parser.add_argument("--folder", default="")
    parser.add_argument("--form", choices=sorted(FORMS), default="path")
    options = parser.parse_args(argv)
    seed = options.seed
    if options.seed_file:
        seed = int(Path(options.seed_file).read_text(encoding="utf-8"))
    round_key = len(os.environ.get(PAD_VARIABLE, ""))
    twin = is_twin()
    for case, base in BASES.items():
        value = options.factor * base * wobble(seed, case, round_key, twin)
        name = FORMS[options.form].format(folder=options.folder, case=case)
        name = name if options.folder else case
        record = {"case": name, "value": value, "unit": "s", "better": "lower"}
        print("::pairbench:: " + json.dumps(record))
    if options.wait > 0:
        e2e_privacy_marker_qz7(options.wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
