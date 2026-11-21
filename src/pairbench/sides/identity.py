# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""How a side's identity is read and hashed.

Every hash a side records is lower-case hexadecimal SHA-256, so that a results
document can show it (``pairbench.model.HASH_PATTERN``). What would name a
machine (a path, a prefix, the output of an ``identify`` command) stays in the
capture under a key that is not in ``pairbench.model.PUBLIC_IDENTITY_KEYS``.
The hash of the output of an ``identify`` command is taken with its recognised
secret forms hidden (``pairbench.model.hashed_output``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pairbench.errors import Refusal
from pairbench.model import (
    EXECUTABLE_KEY,
    HASH_PATTERN,
    IDENTIFY_OUTPUT_KEY,
    LaunchSettings,
    Side,
    canonical_json,
    hashed_argv,
    hashed_output,
    sha256_hex,
)
from pairbench.sides.base import CommandRunner

# Identity keys written by more than one kind.
KEY_IDENTIFY_OUTPUT: Final = IDENTIFY_OUTPUT_KEY
KEY_IDENTIFY_SHA256: Final = "identify_sha256"
KEY_EXECUTABLE: Final = EXECUTABLE_KEY
KEY_EXECUTABLE_SHA256: Final = "executable_sha256"
KEY_ARGV_SHA256: Final = "argv_sha256"
KEY_PYTHON_VERSION: Final = "python_version"
KEY_PACKAGES_SHA256: Final = "packages_sha256"
KEY_PREFIX: Final = "prefix"
KEY_SELECTION_ENV: Final = "selection_env"
KEY_IMAGE_ID: Final = "image_id"
KEY_DIGESTS: Final = "digests"
KEY_PLATFORM: Final = "platform"
KEY_FILES: Final = "files"
KEY_FILES_SHA256: Final = "files_sha256"

_CHUNK: Final = 1 << 20

# Run by the interpreter of a Python environment side. It prints one JSON
# object: the interpreter's prefix and its installed distributions as
# ``name==version``, names normalised as package indexes compare them. It keeps
# to syntax that old interpreters read, so that an old one fails on the import
# of ``importlib.metadata`` with a message, not on the syntax.
PYTHON_IDENTITY_SCRIPT: Final = """\
import json, re, sys
from importlib import metadata
seen = set()
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if not name:
        continue
    seen.add("{0}=={1}".format(re.sub(r"[-_.]+", "-", name).lower(), dist.version))
json.dump({"prefix": sys.prefix, "dists": sorted(seen)}, sys.stdout)
"""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file's bytes as lower-case hex."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def side_file_sha256(side: str, what: str, path: Path) -> str:
    """Return the SHA-256 of a file a side's identity records, or refuse naming the side.

    A file the tool may not read, such as an executable that may be run but
    not read, leaves the side without an identity: ``E_SIDE_UNIDENTIFIED``
    (exit 3). The message names the file by its last part only.
    """
    try:
        return sha256_file(path)
    except OSError as exc:
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the {what} {path.name!r} cannot be read, so its hash cannot be "
            "recorded",
            detail={what: str(path), "reason": exc.strerror or type(exc).__name__},
        ) from None


def argv_sha256(argv: Sequence[str]) -> str:
    """Return the hash of an argument list: SHA-256 of its canonical JSON form.

    The list is hashed as ``pairbench.model.hashed_argv`` reads it, with every
    secret form the shown command hides replaced by ``<hidden>``; paths, hosts
    and ordinary values are hashed as they are.
    """
    return sha256_hex(canonical_json(hashed_argv(argv)))


def hashed_sha256(hashed: Sequence[str]) -> str:
    """Return the hash of an argument list already read as its hash reads it.

    ``hashed`` is what ``pairbench.model.hashed_command`` gives for a command
    side: the command with every secret form hidden that the shown command
    hides, its shared workload also with what another side's client hides.
    """
    return sha256_hex(canonical_json(list(hashed)))


def packages_sha256(dists: Sequence[str]) -> str:
    """Return the hash of an installed-distribution list.

    The list is sorted and each entry kept once, then joined with newlines and
    hashed, so the order an interpreter lists its distributions in does not
    matter.
    """
    return sha256_hex("\n".join(sorted(set(dists))))


def digest_hashes(repo_digests: Sequence[str]) -> list[str]:
    """Return the digest hashes of an image, without registry or repository.

    An engine lists digests as ``repository@sha256:...``. Only the part after
    the last ``@`` is kept, each hash once, sorted. A value that is no hash is
    left out.
    """
    found = {item.rpartition("@")[2] for item in repo_digests if isinstance(item, str)}
    return sorted(value for value in found if re.search(HASH_PATTERN, value))


def run_identify(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    side: str,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, str]:
    """Run an ``identify`` command once and return what the identity records of it.

    The capture keeps the output as printed (``identify_output``); the
    results show only its hash (``identify_sha256``), taken over the output
    as ``pairbench.model.hashed_output`` reads it, with the recognised secret
    forms of each line hidden. Output that is empty or only white space,
    a non-zero exit, a timeout or a command that does not start is refused
    with ``E_SIDE_UNIDENTIFIED``.
    """
    done = runner(list(argv), env=env, cwd=cwd, timeout_s=timeout_s)
    if done.timed_out:
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the identify command ran into its timeout",
            detail={"argv": list(argv)},
        )
    if done.rc != 0:
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the identify command exited with code {done.rc}",
            detail={"argv": list(argv), "stderr": done.stderr[-2000:]},
        )
    if not done.stdout.strip():
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the identify command printed nothing",
            detail={"argv": list(argv)},
        )
    return {
        KEY_IDENTIFY_OUTPUT: done.stdout,
        KEY_IDENTIFY_SHA256: sha256_hex(hashed_output(done.stdout)),
    }


def python_identity(
    runner: CommandRunner,
    interpreter: str,
    *,
    side: str,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Ask an interpreter for its version line, its prefix and its distributions.

    ``python_version`` is what ``<interpreter> -VV`` prints, ``prefix`` is
    ``sys.prefix`` (kept in the capture only) and ``packages_sha256`` the hash
    of the sorted installed-distribution list. An interpreter that cannot
    answer is refused with ``E_SIDE_UNIDENTIFIED``.
    """
    version = runner([interpreter, "-VV"], env=env, cwd=cwd, timeout_s=timeout_s)
    line = (version.stdout.strip() or version.stderr.strip()).splitlines()
    if version.rc != 0 or version.timed_out or not line:
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the interpreter did not report its version",
            detail={"interpreter": interpreter, "stderr": version.stderr[-2000:]},
        )
    listing = runner(
        [interpreter, "-c", PYTHON_IDENTITY_SCRIPT], env=env, cwd=cwd, timeout_s=timeout_s
    )
    answer: Any = None
    if listing.rc == 0 and not listing.timed_out:
        try:
            answer = json.loads(listing.stdout)
        except ValueError:
            answer = None
    if (
        not isinstance(answer, dict)
        or not isinstance(answer.get("prefix"), str)
        or not isinstance(answer.get("dists"), list)
        or not all(isinstance(item, str) for item in answer["dists"])
    ):
        raise Refusal(
            "E_SIDE_UNIDENTIFIED",
            f"side {side!r}: the interpreter did not list its installed distributions",
            detail={"interpreter": interpreter, "stderr": listing.stderr[-2000:]},
        )
    return {
        KEY_PYTHON_VERSION: line[0].strip(),
        KEY_PACKAGES_SHA256: packages_sha256(answer["dists"]),
        KEY_PREFIX: answer["prefix"],
    }


def identify_on_host(
    runner: CommandRunner,
    side: Side,
    settings: LaunchSettings,
    *,
    environment: Mapping[str, str],
    cwd: str | None,
) -> dict[str, str]:
    """Run the configured ``identify`` command on the host, or return nothing without one.

    It runs with the launch environment of the side, in its working
    directory, under the launch timeout.
    """
    if not settings.identify:
        return {}
    return run_identify(
        runner,
        settings.identify,
        side=side.name,
        env=environment,
        cwd=cwd,
        timeout_s=settings.timeout_s,
    )
