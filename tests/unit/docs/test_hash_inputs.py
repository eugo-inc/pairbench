# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every results file the repository keeps has the inputs of its hashes beside it.

A results document shows hashes: each side's ``argv_sha256``, ``args_sha256``
and ``identify_sha256``, its fingerprint, and ``provenance.config_sha256``.
``hash_inputs.json`` beside it holds what each was computed over, after the
secret forms were hidden, so a reader can recompute these five hashes with
``pairbench.model`` of the same version and see what each covers. These tests
walk each tracked ``results.json``, if the repository keeps any, recompute
its five hashes from its sidecar, and hold the sidecar and each
``machine-class.txt`` to the privacy rules of a results file: no host name,
no user name, no address, no path of a machine and no value of its
environment.
Planted pairs in a temporary folder show that each check can fail. The
sidecar writer, ``tools/hash_inputs.py``, is run on a real run of two
``true`` sides, and on the run the launch-cost script would make.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import errno
import getpass
import hashlib
import importlib.util
import io
import ipaddress
import itertools
import json
import os
import posixpath
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

import pytest

from pairbench import model
from pairbench.model import (
    Capture,
    Header,
    canonical_json,
    combine_hashes,
    config_sha256,
    fingerprint_of,
    hashed_argv,
    sha256_hex,
)
from pairbench.sides.identity import argv_sha256

SIDECAR = "hash_inputs.json"
RESULTS = "results.json"
SCHEMA = "pairbench/hash-inputs/v1"
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2
# The places a kept run may name: the checkout reached at /work, the neutral home folder, the
# system folders of a public image, and the folders the showcases mount inside their containers.
NEUTRAL_ROOTS = (
    "/work",
    "/home/user",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/etc",
    "/dev",
    "/opt/conda",
    "/showcase",
    "/models",
)
NEUTRAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "0.0.0.0"})
NEUTRAL_WORDS = frozenset({"user", "root", "localhost"})
# A value of the environment shorter than this is too common a word to tell a machine apart.
SHORTEST_ENV_VALUE = 8
# The registries of public images, whose names name no machine.
NEUTRAL_REGISTRIES = frozenset(
    {
        "docker.io",
        "index.docker.io",
        "registry-1.docker.io",
        "ghcr.io",
        "quay.io",
        "nvcr.io",
        "gcr.io",
        "registry.k8s.io",
        "mcr.microsoft.com",
        "public.ecr.aws",
    }
)
# An address, with the part after its host: the path of a network address names no folder of
# the machine, and the path of a file address does.
ADDRESS = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://(?P<authority>[^/\s'\"?#]*)(?P<rest>[^\s'\"]*)")
# A path starts a text, follows a separator or a shell operator, or is glued to a short option.
PATH = re.compile(
    r"(?:(?<![^\s=:'\"(,\[<>@|;&])|(?<=(?<![^\s'\"])-[A-Za-z]))/[^\s:'\",;=()\[\]<>|&]*"
)
# The hashes a side's entry may hold inputs for, besides its fingerprint.
IDENTITY_HASHES = ("argv_sha256", "args_sha256", "identify_sha256")
# Host names that name no machine: the loopback name, the documentation domains and the
# registries of public images. A name under the documentation top-level domain ``.example``
# names none either. Every other name in a place that holds a host is flagged.
PUBLIC_HOSTS = frozenset({"localhost", "example.com", "example.org", "example.net"})
# Four numbers of 0 to 255 joined by dots, not part of a longer run of numbers and dots.
IPV4 = re.compile(r"(?<![\w.])(?P<address>\d{1,3}(?:\.\d{1,3}){3})(?!\.?\w)")
# What before four numbers says they are a version: a comparison of a requirement. A ``v``
# right before them says so too; it is a letter, so IPV4 never starts there.
VERSION_BEFORE = ("==", ">=", "<=", "~=", "!=", "<", ">")
# A run of hexadecimal groups and colons: an IPv6 address when it holds ``::`` or eight groups,
# and a digit, and Python's ipaddress reads it as one.
IPV6 = re.compile(r"(?<![\w:.])(?P<address>[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})(?![\w:])")
NEUTRAL_IPV6 = frozenset({"::", "::1"})
# The places a text holds a host name in, besides an address with a scheme: the host of
# user@host, a name before :PORT, the value of --host, --hostname, -h or -H, and a value of a
# variable whose name ends in HOST or HOSTNAME, such as DB_HOST or PGHOST.
# The ``@sha256:`` of an image digest names an algorithm, not a host.
USER_AT_HOST = re.compile(
    r"(?<![\w.%+-])[\w.%+-]+@(?!sha\d+:)(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)"
)
HOST_PORT = re.compile(
    r"(?<![\w.:/@%-])(?P<host>[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*)"
    r":(?P<port>\d{2,5})(?=$|[/\s'\",])"
)
# The value of a host option may stand in quotes.
HOST_OPTION = re.compile(r"(?<![\w-])--host(?:name)?[= ]['\"]?(?P<host>[^\s'\",]+)")
# A short host option takes a value shaped as a name, bare or whole in quotes: after -H, curl
# takes a header, which holds a space or a colon.
SHORT_HOST_OPTION = re.compile(
    r"(?<![\w-])-[hH][= ](?:(?P<quote>['\"])(?=[A-Za-z0-9][A-Za-z0-9.-]*(?P=quote)))?"
    r"(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*)(?=$|[\s'\",:])"
)
# A host glued to -h or -H holds a number, so that a group of one-letter options such as -hv
# reads as no host.
SHORT_HOST_GLUED = re.compile(
    r"(?<![\w-])-[hH](?P<host>[A-Za-z][A-Za-z0-9.-]*[0-9][A-Za-z0-9.-]*)(?=$|[\s'\",:])"
)
HOST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
HOST_VARIABLE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z0-9_]*(?:HOST|HOSTNAME)=(?P<host>[^\s'\",]+)", re.IGNORECASE
)
HOST_KEY = re.compile(r"[A-Za-z0-9_]*(?:HOST|HOSTNAME)", re.IGNORECASE)
HOST_FLAGS = frozenset({"--host", "--hostname"})
SHORT_HOST_FLAGS = frozenset({"-h", "-H"})
# The four numbers of an address written in a name, as a cloud names a machine by its address:
# joined by dashes (ip-10-0-0-1, 10-0-0-1), or by underscores after a name (ip_10_0_0_1), with
# or without a domain after it. Four numbers joined by underscores alone read as one number.
DASHED_ADDRESS = re.compile(
    r"(?<![\w.-])(?P<host>(?:[A-Za-z][A-Za-z0-9]*(?P<joint>[-_]))?"
    r"(?P<numbers>\d{1,3}(?P<between>(?(joint)(?P=joint)|-))\d{1,3}(?P=between)\d{1,3}"
    r"(?P=between)\d{1,3})(?:\.[A-Za-z0-9-]+)*)(?![\w-])"
)
# A name under a public top-level domain, with or without the dot that ends a whole name: a
# generic one, or a country's that no common file ends in. A name ending in .py, .sh or .txt
# reads as a file.
PUBLIC_NAME = re.compile(
    r"(?<![\w.@/-])(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
    r"\.(?:com|net|org|edu|gov|mil|int|io|ai|co|dev|app|cloud|info|biz|tech|xyz|us|uk|de|fr"
    r"|jp|cn|ru|eu|ca|au|nl|ch|se|me|tv|tw|kr|br|sg|hk|nz|za|mx|ar|cl|es|be|dk|fi|ie|il|tr|ua"
    r"|cz|hu|vn|ph|pk|ae))\.?(?![\w.-])",
    re.IGNORECASE,
)
# A name of three parts or more under any two letters, as a country's top-level domain is
# written, except the endings of common files and the short words code puts after a dot.
FILE_ENDINGS = (
    "ac|am|at|cc|cs|cu|db|el|fs|gz|hh|id|in|is|it|jl|js|ko|kt|la|md|mk|ml|mo|nn|pl|pm|po|ps|pt"
    "|py|rb|rs|sh|so|to|ts|ui|xz"
)
COUNTRY_NAME = re.compile(
    rf"(?<![\w.@/-])(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\.(?!(?:{FILE_ENDINGS})\b)"
    r"[A-Za-z]{2})\.?(?![\w.-])",
    re.IGNORECASE,
)
# An address of four numbers written as one hexadecimal number of 32 bits, as one decimal
# number from 1.0.0.0 up, or as four numbers of which one at least is hexadecimal or octal
# (written with a leading 0), which the C library reads as an address too.
HEX_ADDRESS = re.compile(r"(?<![\w.])(?P<address>0[xX][0-9A-Fa-f]{7,8})(?![\w.])")
DECIMAL_ADDRESS = re.compile(r"[1-9][0-9]{7,9}")
LOWEST_DECIMAL_ADDRESS, HIGHEST_DECIMAL_ADDRESS = 1 << 24, (1 << 32) - 1
DOTTED_HEX_ADDRESS = re.compile(
    r"(?<![\w.])(?P<address>(?:0[xX][0-9A-Fa-f]{1,2}|0[0-7]{1,3}|[0-9]{1,3})"
    r"(?:\.(?:0[xX][0-9A-Fa-f]{1,2}|0[0-7]{1,3}|[0-9]{1,3})){3})(?![\w.])"
)
OCTAL_PART = re.compile(r"(?:^|\.)0[0-7]+(?=\.|$)")
# A whole value made of a name and a number, as a machine is often named (db7, web01), and
# such a word in a text, standing alone or after = or a quote (connect db7, server=db7). A walk
# cannot tell it from a host, so it flags it, except a run of 32 or more hexadecimal digits,
# such as a hash, and a public technical word of one of these families, with a number that
# the family has: a number type, an architecture, a hash or text encoding, an address family,
# the tag of an interpreter this tool runs on (3.11 to 3.14) or of its major version, and the
# tag of a CUDA or ROCm version by its major and minor numbers or of a compute capability,
# which side names and fingerprints hold (float32, aarch64, sha256, py313, cuda1343, cu121,
# rocm62, sm90).
NUMBERED_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]*[0-9]")
NUMBERED_WORD = re.compile(r"(?<![\w.:/@%+~$-])[A-Za-z][A-Za-z0-9-]*[0-9](?![\w.:/@%+-])")
HEXADECIMAL_RUN = re.compile(r"[0-9A-Fa-f]{32,}")
TECHNICAL_WORD = re.compile(
    r"(?:b?float|u?int|fp)(?:4|8|16|32|64|128)|bf16|tf32|complex(?:64|128|256)"
    r"|(?:aarch|arm|amd|ppc|riscv)64"
    r"|sha-?(?:1|224|256|384|512)|md5|crc32|blake2|base(?:32|64)|utf-?(?:8|16|32)|ipv[46]"
    r"|(?:py|cp|pypy|python)(?:[23]|31[1-4])|cu(?:da)?(?:[7-9]|1[0-9])[0-9]{1,2}|rocm[1-9][0-9]{1,2}"
    r"|sm(?:[2-9][0-9]|1[0-9]{2})",
    re.IGNORECASE,
)
# A name under a top-level domain of private networks names a machine wherever it stands.
PRIVATE_NAME = re.compile(
    r"(?<![\w.-])(?P<host>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
    r"\.(?:internal|local|lan|corp|intranet|localdomain))(?![\w.-])",
    re.IGNORECASE,
)
# A home folder by name (~name/), a Windows drive path and a Windows network path.
TILDE_HOME = re.compile(r"(?<![\w~])~(?P<name>[A-Za-z_][\w.-]*)(?=/|$)")
WINDOWS_PATH = re.compile(r"(?<![\w./\\-])(?P<path>[A-Za-z]:[\\/][^\s'\",;]*)")
UNC_PATH = re.compile(r"(?<![\w\\])(?P<path>\\\\[A-Za-z0-9._-]+\\[^\s'\",;]*)")

# A made-up machine: every value it would leak is a marker.
HOST = "markerhost-a"
USER = "markeruser-a"
ENV_VALUE = "markerenvvalue-a"
HOME_PATH = "/home/markeruser-a/bin/true"
TOKEN = "kiwi7"
IDENTIFY = '["echo", "API_TOKEN=kiwi7 made-up-tool 1.2"]'


class Machine(NamedTuple):
    """What would name the measuring machine."""

    host: str
    user: str
    environ: Mapping[str, str]


MARKED = Machine(host=HOST, user=USER, environ={"MADE_UP_SETTING": ENV_VALUE})


def this_machine() -> Machine:
    return Machine(host=socket.gethostname(), user=getpass.getuser(), environ=dict(os.environ))


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def texts(value: Any) -> Iterator[str]:
    """Every text of a JSON value: its keys and its texts, in tables and lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item)


def neutral_path(path: str) -> bool:
    """Whether a path lies under a neutral root once its ``.`` and ``..`` parts are read."""
    path = posixpath.normpath(path)
    return path == "/" or any(path == root or path.startswith(root + "/") for root in NEUTRAL_ROOTS)


def names(name: str, text: str) -> bool:
    """Whether a text holds a name as a word: no letter or digit right before or after it.

    A dash, a dot or an underscore ends a word here, so a name joined to other words by one
    (``bench-NAME``, ``NAME_cache``) is found, and a longer word that holds it is not.
    """
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text) is not None


def local_part(address: re.Match[str]) -> str:
    """What of an address names a place on the machine: the path of a file address."""
    return " " if address.group("authority") else " " + address.group("rest")


def images(value: Any) -> Iterator[str]:
    """Every image reference of a JSON value: the texts under an ``image`` key."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "image" and isinstance(item, str):
                yield item
            else:
                yield from images(item)
    elif isinstance(value, list):
        for item in value:
            yield from images(item)


def server_paths(value: Any) -> set[str]:
    """The paths a serving side asks its server for, which name no folder of the machine."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "serve" and isinstance(item, Mapping):
                for table, name in (("ready", "http"), ("probe", "path")):
                    asked = (item.get(table) or {}).get(name)
                    if isinstance(asked, str):
                        found.add(asked)
            found |= server_paths(item)
    elif isinstance(value, list):
        for item in value:
            found |= server_paths(item)
    return found


def registry_of(reference: str) -> str:
    """The host of the registry an image reference names, or ``""`` for the default one."""
    first, slash, _ = reference.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        return first.partition(":")[0]
    return ""


def public_host(host: str) -> bool:
    """Whether a host name names no machine: the loopback, a documentation name, a registry."""
    name = host.lower().rstrip(".")
    return (
        name in NEUTRAL_HOSTS
        or name in PUBLIC_HOSTS
        or name in NEUTRAL_REGISTRIES
        or name == "example"
        or name.endswith(".example")
    )


def host_values(value: Any) -> Iterator[str]:
    """The values a JSON value gives in a host's place: after --host or -h, under a HOST key."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, str) and HOST_KEY.fullmatch(str(key)):
                yield item
            else:
                yield from host_values(item)
    elif isinstance(value, list):
        for flag, item in itertools.pairwise(value):
            if not isinstance(item, str):
                continue
            if flag in HOST_FLAGS or (flag in SHORT_HOST_FLAGS and HOST_NAME.fullmatch(item)):
                yield item
        for item in value:
            yield from host_values(item)


def whole_values(value: Any) -> Iterator[str]:
    """Every text of a JSON value that is a value, not a key."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from whole_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from whole_values(item)


def address_problems(text: str, where: str) -> set[str]:
    """The addresses, host names and paths of other machines a text holds.

    Four numbers joined by dots are an address unless a comparison or a ``v`` before them says
    they are a version: a text that does not say which is flagged.
    """
    found: set[str] = set()
    for match in IPV4.finditer(text):
        address = match.group("address")
        if not all(int(part) <= 255 for part in address.split(".")):
            continue
        if address in NEUTRAL_HOSTS or text[: match.start()].endswith(VERSION_BEFORE):
            continue
        found.add(f"{where}: holds the address of the host {address}")
    for match in IPV6.finditer(text):
        address = match.group("address")
        if ("::" not in address and address.count(":") != 7) or not re.search(r"\d", address):
            continue
        try:
            ipaddress.IPv6Address(address)
        except ValueError:
            continue
        if address not in NEUTRAL_IPV6:
            found.add(f"{where}: holds the address of the host {address}")
    for match in HEX_ADDRESS.finditer(text):
        found.add(f"{where}: holds the address of the host {match.group('address')}")
    for match in DOTTED_HEX_ADDRESS.finditer(text):
        address = match.group("address")
        if "0x" in address.lower() or OCTAL_PART.search(address):
            found.add(f"{where}: holds the address of the host {address}")
    for match in DASHED_ADDRESS.finditer(text):
        if all(int(part) <= 255 for part in re.split("[-_]", match.group("numbers"))):
            found.add(f"{where}: holds the host name {match.group('host')}")
    hosts = [match.group("host") for match in USER_AT_HOST.finditer(text)]
    hosts += [
        match.group("host") for match in HOST_PORT.finditer(text) if int(match["port"]) <= 65535
    ]
    hosts += [match.group("host") for match in HOST_OPTION.finditer(text)]
    hosts += [match.group("host") for match in SHORT_HOST_OPTION.finditer(text)]
    hosts += [match.group("host") for match in SHORT_HOST_GLUED.finditer(text)]
    hosts += [match.group("host") for match in HOST_VARIABLE.finditer(text)]
    hosts += [match.group("host") for match in PRIVATE_NAME.finditer(text)]
    hosts += [match.group("host") for match in PUBLIC_NAME.finditer(text)]
    hosts += [match.group("host") for match in COUNTRY_NAME.finditer(text)]
    hosts += [
        match.group()
        for match in NUMBERED_WORD.finditer(text)
        if not HEXADECIMAL_RUN.fullmatch(match.group())
        and not TECHNICAL_WORD.fullmatch(match.group())
    ]
    for host in hosts:
        if re.search(r"[A-Za-z]", host) and not IPV4.fullmatch(host) and not public_host(host):
            found.add(f"{where}: holds the host name {host}")
    for match in TILDE_HOME.finditer(text):
        if match.group("name") != "user":
            found.add(f"{where}: holds the home folder ~{match.group('name')}")
    for pattern in (WINDOWS_PATH, UNC_PATH):
        for match in pattern.finditer(text):
            found.add(f"{where}: holds the path {match.group('path')}")
    return found


def privacy_problems(sidecar: Any, where: str, machine: Machine) -> list[str]:
    """What in a sidecar would name the machine it was made on."""
    found: set[str] = set()
    host_words = {machine.host, machine.host.split(".")[0]} - NEUTRAL_WORDS - {""}
    values = {
        name: value
        for name, value in machine.environ.items()
        if len(value) >= SHORTEST_ENV_VALUE
        and not all(neutral_path(part) for part in value.split(":") if part)
    }
    asked = server_paths(sidecar)
    for host in host_values(sidecar):
        if re.search(r"[A-Za-z]", host) and not IPV4.fullmatch(host) and not public_host(host):
            found.add(f"{where}: holds the host name {host}")
    for value in whole_values(sidecar):
        if (
            NUMBERED_NAME.fullmatch(value)
            and not HEXADECIMAL_RUN.fullmatch(value)
            and not TECHNICAL_WORD.fullmatch(value)
        ):
            found.add(f"{where}: holds the host name {value}")
        if (
            DECIMAL_ADDRESS.fullmatch(value)
            and LOWEST_DECIMAL_ADDRESS <= int(value) <= HIGHEST_DECIMAL_ADDRESS
        ):
            found.add(f"{where}: holds the address of the host {value}")
    for text in texts(sidecar):
        found |= address_problems(ADDRESS.sub(" ", text), where)
        for address in ADDRESS.finditer(text):
            host = address.group("authority").rpartition("@")[2]
            host = host[1:].partition("]")[0] if host.startswith("[") else host.partition(":")[0]
            if host not in NEUTRAL_HOSTS:
                found.add(f"{where}: holds the address of the host {host}")
        for path in PATH.findall(ADDRESS.sub(local_part, text)) if text not in asked else ():
            if not neutral_path(path):
                found.add(f"{where}: holds the path {path}")
        if any(names(word, text) for word in host_words):
            found.add(f"{where}: holds the host name")
        if machine.user and machine.user not in NEUTRAL_WORDS and names(machine.user, text):
            found.add(f"{where}: holds the user name")
        for name, value in values.items():
            if names(value, text):
                found.add(f"{where}: holds the value of the environment variable {name}")
    for reference in images(sidecar):
        registry = registry_of(reference)
        if registry not in NEUTRAL_HOSTS and registry not in NEUTRAL_REGISTRIES:
            found.add(f"{where}: holds the image registry {registry}")
    return sorted(found)


def hash_problems(results: Any, sidecar: Any, where: str) -> list[str]:
    """Each published hash that its inputs do not give, or whose inputs show a hidden value."""
    found: list[str] = []
    if sidecar.get("schema") != SCHEMA:
        found.append(f"{where}: the schema is not {SCHEMA}")
    entries = dict(sidecar.get("sides") or {})
    for side in results.get("sides", []):
        name = side["name"]
        entry = entries.pop(name, None)
        if entry is None:
            found.append(f"{where}: side {name}: no inputs")
            continue
        shown = {key: side["identity"][key] for key in IDENTITY_HASHES if key in side["identity"]}
        shown["fingerprint"] = side["fingerprint"]
        for key in sorted(set(entry) - set(shown)):
            found.append(f"{where}: side {name}: inputs of a hash the results do not show: {key}")
        for key, published in sorted(shown.items()):
            if key not in entry:
                found.append(f"{where}: side {name}: no inputs for its {key}")
                continue
            inputs = entry[key]
            if key == "identify_sha256":
                given, again = sha256_hex(inputs), model.hashed_output(inputs)
            elif key == "fingerprint":
                given = sha256_hex(canonical_json(inputs))
                again = model.fingerprint_inputs(inputs["identity"], inputs["launch"])
            else:
                given, again = sha256_hex(canonical_json(inputs)), hashed_argv(inputs)
            if given != published:
                found.append(f"{where}: side {name}: {key} is not the hash of its inputs")
            elif again != inputs:
                found.append(f"{where}: side {name}: the inputs of {key} hold a hidden value")
    for name in sorted(entries):
        found.append(f"{where}: inputs for a side the results do not name: {name}")
    published = results.get("provenance", {}).get("config_sha256")
    configs = sidecar.get("provenance", {}).get("config_sha256")
    if published is None:
        if configs is not None:
            found.append(f"{where}: inputs of provenance.config_sha256, which the results lack")
    elif not isinstance(configs, list) or not configs:
        found.append(f"{where}: no inputs for provenance.config_sha256")
    elif combine_hashes([sha256_hex(canonical_json(c)) for c in configs]) != published:
        found.append(f"{where}: provenance.config_sha256 is not the hash of its inputs")
    elif [model.config_inputs(c) for c in configs] != configs:
        found.append(f"{where}: the inputs of provenance.config_sha256 hold a hidden value")
    return found


def problems_of(results_path: Path, root: Path, machine: Machine) -> list[str]:
    """Every problem of one results file and its sidecar."""
    where = results_path.relative_to(root).as_posix()
    sidecar_path = results_path.with_name(SIDECAR)
    if not sidecar_path.is_file():
        return [f"{where}: no {SIDECAR} beside it"]
    results = json.loads(results_path.read_text(encoding="utf-8"))
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    return hash_problems(results, sidecar, where) + privacy_problems(sidecar, where, machine)


def tracked_files(repo_root: Path) -> list[str]:
    """Each file the checkout tracks, or would track: added, or new and not ignored.

    Inside a checkout (a folder with ``.git``) a listing git refuses fails the test, since
    the walk would otherwise check nothing; outside one the walk is skipped.
    """
    done = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=repo_root,
        env={name: value for name, value in os.environ.items() if not name.startswith("GIT_")},
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        if (repo_root / ".git").exists():
            pytest.fail(f"git cannot list the files of this checkout: {done.stderr.strip()}")
        pytest.skip(f"needs a git checkout of the repository: {done.stderr.strip()}")
    return [name for name in done.stdout.split("\0") if name]


def tracked_results(repo_root: Path) -> list[Path]:
    """Each results file the checkout tracks, or would track."""
    return [
        repo_root / name
        for name in tracked_files(repo_root)
        if Path(name).name == RESULTS and (repo_root / name).is_file()
    ]


# The file the launch-cost script writes beside its results: the class of machine in words.
MACHINE_CLASS = "machine-class.txt"
REPOSITORY = Path(__file__).resolve().parents[3]


def class_problems(path: Path, root: Path, machine: Machine) -> list[str]:
    """What in a machine-class.txt is not a class in the public form, or names a machine."""
    where = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    given = text.removesuffix("\n")
    machine_class = load(REPOSITORY, "launch_cost").machine_class
    # An instance type whose name ends in a number, such as a type and its count of cores, has
    # the shape of a numbered host name; one in a public form names a type, not a machine.
    problems = [
        problem
        for problem in privacy_problems([given], where, machine)
        if not (
            problem.startswith(f"{where}: holds the host name ")
            and machine_class(problem.removeprefix(f"{where}: holds the host name ")) is not None
        )
    ]
    if machine_class(given) != given:
        problems.insert(0, f"{where}: is not a class of machine in a public form")
    return problems


# The folder the launch-cost script publishes into, and the files kept there. The launch-cost
# results are kept without their sidecar because the results hide the two side commands; the
# commands are the constants of tools/launch_cost.py, so a reader runs that script to repeat
# the run rather than recomputing the hashes. That holds only while the results show each
# side as KIND:<hidden> and no sidecar is beside them; a sidecar there is checked as anywhere,
# and holds only values the shared files beside it show. The folder holds no symbolic link.
KEPT_COST = "docs/figures/launch-cost"
KEPT_COST_FILES = (RESULTS, MACHINE_CLASS, SIDECAR)
HIDDEN_SIDE = re.compile(r"(?P<name>[^=]+)=[a-z]+:<hidden>")


def shown_sides(command: str) -> list[str] | None:
    """The value of each ``--side`` of a shown command, or None if it cannot be read."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return [
        word.removeprefix("--side=") if word.startswith("--side=") else word
        for before, word in itertools.pairwise(["", *words])
        if before == "--side" or word.startswith("--side=")
    ]


def cost_problems(results_path: Path, root: Path) -> list[str]:
    """What keeps the launch-cost results from being kept without their sidecar."""
    where = results_path.relative_to(root).as_posix()
    results = json.loads(results_path.read_text(encoding="utf-8"))
    primary = sorted(
        side["name"]
        for side in results.get("sides", [])
        if side.get("twin_of") is None and side.get("control_of") is None
    )
    command = (results.get("run") or {}).get("command")
    shown = (shown_sides(command) if isinstance(command, str) else None) or []
    typed = sorted({spec.partition("=")[0] for spec in shown if not HIDDEN_SIDE.fullmatch(spec)})
    problems = [
        f"{where}: no {SIDECAR} beside it, and run.command shows the side {name} as typed"
        for name in typed
    ]
    hidden = sorted(found["name"] for found in map(HIDDEN_SIDE.fullmatch, shown) if found)
    if not typed and (not primary or hidden != primary):
        problems.append(
            f"{where}: no {SIDECAR} beside it, and run.command does not show each side "
            "as KIND:<hidden>"
        )
    if not results_path.with_name(MACHINE_CLASS).is_file():
        problems.append(f"{where}: no {MACHINE_CLASS} beside it")
    return problems


def private_beside_cost(results_path: Path, root: Path) -> list[str]:
    """Whether the sidecar beside the launch-cost results holds a value the results do not
    show, by the check the writer makes before it shares a sidecar. The folder keeps no
    results.md, so the results are the one shared file read."""
    where = results_path.relative_to(root).as_posix()
    unshown = load(REPOSITORY, "hash_inputs").hidden_values(
        json.loads(results_path.read_text(encoding="utf-8")),
        "",
        json.loads(results_path.with_name(SIDECAR).read_text(encoding="utf-8")),
    )
    if not unshown:
        return []
    return [
        f"{where}: the {SIDECAR} beside it is private: the shared files do not show "
        f"{len(unshown)} of the values it holds"
    ]


def walk_problems(repo_root: Path, machine: Machine) -> list[str]:
    """Every problem of each results file the checkout tracks or would track, and its sidecar,
    of each file kept with the launch-cost results, and of each machine-class.txt."""
    problems: list[str] = []
    files = tracked_files(repo_root)
    # Git keeps a symbolic link as the path it points to, not the file there, so nothing in the
    # launch-cost folder, nor the folder itself, is read through one.
    linked = {
        name
        for name in files
        if (name == KEPT_COST or name.startswith(f"{KEPT_COST}/"))
        and (repo_root / name).is_symlink()
    }
    for path in sorted(tracked_results(repo_root)):
        if path.relative_to(repo_root).as_posix() in linked:
            continue
        if path != repo_root / KEPT_COST / RESULTS:
            problems += problems_of(path, repo_root, machine)
        elif f"{KEPT_COST}/{SIDECAR}" in linked or not path.with_name(SIDECAR).is_file():
            problems += cost_problems(path, repo_root)
        else:
            problems += problems_of(path, repo_root, machine)
            problems += private_beside_cost(path, repo_root)
    for name in sorted(files):
        inside = name.removeprefix(f"{KEPT_COST}/")
        if name in linked:
            problems.append(
                f"{name}: is a symbolic link; the launch-cost results are kept as files"
            )
        elif inside != name and inside not in KEPT_COST_FILES and (repo_root / name).is_file():
            problems.append(f"{name}: is not kept beside the launch-cost results")
    for name in sorted(name for name in files if Path(name).name == MACHINE_CLASS):
        if name not in linked and (repo_root / name).is_file():
            problems += class_problems(repo_root / name, repo_root, machine)
    return problems


def test_the_walk_lists_the_files_of_this_checkout(repo_root: Path) -> None:
    files = tracked_files(repo_root)

    assert "tests/unit/docs/test_hash_inputs.py" in files
    assert "tools/hash_inputs.py" in files


def test_a_listing_git_refuses_inside_a_checkout_fails_the_walk(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    (tmp_path / ".git").mkdir()

    try:
        walk_problems(tmp_path, MARKED)
    except pytest.fail.Exception as failure:
        assert str(failure).startswith("git cannot list the files of this checkout: ")
    except pytest.skip.Exception:
        pytest.fail("a listing git refuses inside a checkout skipped the walk")
    else:
        pytest.fail("a listing git refuses inside a checkout let the walk pass")


def test_a_folder_that_is_no_checkout_skips_the_walk(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")

    with pytest.raises(pytest.skip.Exception, match="needs a git checkout of the repository"):
        walk_problems(tmp_path, MARKED)


def test_every_tracked_results_file_has_a_sidecar_that_gives_each_hash(repo_root: Path) -> None:
    assert walk_problems(repo_root, this_machine()) == []


def test_the_fixture_generators_write_no_results_document(repo_root: Path) -> None:
    generators = sorted((repo_root / "tests" / "fixtures" / "_gen").glob("*.py"))
    writing = [
        path.name
        for path in generators
        if RESULTS in path.read_text(encoding="utf-8")
        or "pairbench/results/" in path.read_text(encoding="utf-8")
    ]

    assert generators
    assert writing == []


# ---------------------------------------------------------------------------
# The writer, on a real run of two command sides
# ---------------------------------------------------------------------------


def load(repo_root: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"{name}_under_test", repo_root / "tools" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def writer(repo_root: Path) -> ModuleType:
    return load(repo_root, "hash_inputs")


def run_cli(*args: str) -> tuple[int, str]:
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, err.getvalue()


def write_sidecar(writer: ModuleType, folder: Path) -> tuple[int, str]:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = writer.main([str(folder)])
    return code, err.getvalue()


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real run of two command sides, made in a temporary folder, without its sidecar."""
    base = tmp_path_factory.mktemp("made")
    here = Path.cwd()
    os.chdir(base)
    try:
        code, err = run_cli(
            "run",
            "--side",
            "a=cmd:true",
            "--side",
            "b=cmd:env true",
            "--baseline",
            "b",
            "--gates",
            "off",
            "--rounds",
            "6",
            "--explain",
            "off",
            "--plots",
            "off",
            "--set",
            f"launch.identify={IDENTIFY}",
            "--out",
            "run",
        )
    finally:
        os.chdir(here)
    assert code == EXIT_OK, err
    return base / "run"


@pytest.fixture
def pair(made: Path, tmp_path: Path, writer: ModuleType) -> Path:
    """A copy of the real run with the sidecar the writer writes; its folder is ``run``."""
    folder = tmp_path / "run"
    shutil.copytree(made, folder)
    code, err = write_sidecar(writer, folder)
    assert (code, err) == (EXIT_OK, PRIVATE.format(len(hidden(writer, folder))))
    return folder


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def plant(folder: Path, name: str, key: str, change: Any) -> None:
    """Change the inputs of one hash of a side and write the hash they give into the results."""
    sidecar = read(folder / SIDECAR)
    results = read(folder / RESULTS)
    entry = sidecar["sides"][name]
    entry[key] = change(copy.deepcopy(entry[key]))
    inputs = entry[key]
    given = sha256_hex(inputs) if key == "identify_sha256" else sha256_hex(canonical_json(inputs))
    for side in results["sides"]:
        if side["name"] == name:
            if key == "fingerprint":
                side["fingerprint"] = given
            else:
                side["identity"][key] = given
    write(folder / SIDECAR, sidecar)
    write(folder / RESULTS, results)


def test_a_neutral_matching_pair_passes(pair: Path) -> None:
    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []
    assert problems_of(pair / RESULTS, pair.parent, this_machine()) == []


def test_the_sidecar_holds_each_published_hash_s_inputs_with_the_secrets_hidden(
    pair: Path,
) -> None:
    sidecar = read(pair / SIDECAR)
    text = (pair / SIDECAR).read_text(encoding="utf-8")
    entry = sidecar["sides"]["a"]

    assert sidecar["schema"] == SCHEMA
    assert sorted(entry) == ["argv_sha256", "fingerprint", "identify_sha256"]
    assert entry["argv_sha256"] == ["true"]
    assert entry["identify_sha256"] == "API_TOKEN=<hidden> made-up-tool 1.2\n"
    assert entry["fingerprint"]["identity"]["identify_output"] == entry["identify_sha256"]
    assert sidecar["provenance"]["config_sha256"][0]["run"]["out"] == "run"
    assert TOKEN not in text


def test_a_results_file_without_its_sidecar_fails(pair: Path) -> None:
    (pair / SIDECAR).unlink()

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: no hash_inputs.json beside it"
    ]


def test_inputs_that_give_another_hash_fail(pair: Path) -> None:
    sidecar = read(pair / SIDECAR)
    sidecar["sides"]["a"]["argv_sha256"].append("--made-up")
    write(pair / SIDECAR, sidecar)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: side a: argv_sha256 is not the hash of its inputs"
    ]


def test_a_side_left_out_of_the_sidecar_fails(pair: Path) -> None:
    sidecar = read(pair / SIDECAR)
    del sidecar["sides"]["b"]
    write(pair / SIDECAR, sidecar)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: side b: no inputs"
    ]


def test_inputs_that_show_a_value_the_hashes_hide_fail(pair: Path) -> None:
    sidecar = read(pair / SIDECAR)
    results = read(pair / RESULTS)
    config = sidecar["provenance"]["config_sha256"][0]
    config["launch"]["env"] = {"API_TOKEN": TOKEN}
    results["provenance"]["config_sha256"] = sha256_hex(canonical_json(config))
    write(pair / SIDECAR, sidecar)
    write(pair / RESULTS, results)

    # The token, a whole value made of a name and a number, is also one the walk cannot tell
    # from a host.
    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: the inputs of provenance.config_sha256 hold a hidden value",
        f"run/results.json: holds the host name {TOKEN}",
    ]


def test_a_sidecar_that_holds_a_home_path_fails(pair: Path) -> None:
    def moved(fingerprint: dict[str, Any]) -> dict[str, Any]:
        fingerprint["identity"]["executable"] = HOME_PATH
        return fingerprint

    plant(pair, "a", "fingerprint", moved)

    # The fingerprint holds the executable by the last part of its path, so a whole path there
    # is also a value the hash does not take.
    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: side a: the inputs of fingerprint hold a hidden value",
        f"run/results.json: holds the path {HOME_PATH}",
        "run/results.json: holds the user name",
    ]


def test_a_sidecar_that_holds_the_host_name_fails(pair: Path) -> None:
    plant(pair, "a", "identify_sha256", lambda text: text + f"built on {HOST}\n")

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: holds the host name"
    ]


def test_a_sidecar_that_holds_the_address_of_a_host_fails(pair: Path) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, "https://build.example.org/a"])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: holds the address of the host build.example.org"
    ]


def test_the_path_of_a_loopback_address_passes(pair: Path) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, "http://localhost:8000/v1/made-up"])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []


# Another machine than the one the test runs on: a check that knows only this machine's names
# passes these.
OTHER_HOST = "markerhost-b"
OTHER_USER = "markeruser-b"


@pytest.mark.parametrize(
    ("planted", "problem"),
    [
        ("192.0.2.7", "holds the address of the host 192.0.2.7"),
        ("--bind=192.0.2.7:8000", "holds the address of the host 192.0.2.7"),
        (f"{OTHER_USER}@192.0.2.7", "holds the address of the host 192.0.2.7"),
        ("fe80::7", "holds the address of the host fe80::7"),
        ("[2001:db8::7]:8000", "holds the address of the host 2001:db8::7"),
        (f"{OTHER_HOST}:8080", f"holds the host name {OTHER_HOST}"),
        (f"{OTHER_USER}@{OTHER_HOST}", f"holds the host name {OTHER_HOST}"),
        (f"--host={OTHER_HOST}", f"holds the host name {OTHER_HOST}"),
        (f"DB_HOST={OTHER_HOST}", f"holds the host name {OTHER_HOST}"),
        (f"{OTHER_HOST}.lab.corp", f"holds the host name {OTHER_HOST}.lab.corp"),
        (f"~{OTHER_USER}/bench", f"holds the home folder ~{OTHER_USER}"),
        (f"C:\\Users\\{OTHER_USER}\\bench", f"holds the path C:\\Users\\{OTHER_USER}\\bench"),
        (f"\\\\{OTHER_HOST}\\share", f"holds the path \\\\{OTHER_HOST}\\share"),
        # A version and an address the text does not tell apart: flagged.
        ("1.2.3.4", "holds the address of the host 1.2.3.4"),
        ("made-up:20", "holds the host name made-up"),
        # A name and a number, a short host option, a variable whose name ends in HOST, the
        # four numbers of an address written in a name, a name under a public top-level
        # domain and an address written as one hexadecimal number: each flagged.
        ("db7", "holds the host name db7"),
        ("-H db7", "holds the host name db7"),
        ("PGHOST=db7", "holds the host name db7"),
        ("ip-192-0-2-9", "holds the host name ip-192-0-2-9"),
        ("connect ip-192-0-2-9", "holds the host name ip-192-0-2-9"),
        ("db7.madeup-corp.com", "holds the host name db7.madeup-corp.com"),
        ("0xc0000209", "holds the address of the host 0xc0000209"),
        # A host glued to a short host option, an address written as four hexadecimal
        # numbers, and names with a number that no public technical word of their family has.
        ("-hdb7", "holds the host name db7"),
        ("-Hdb7-replica", "holds the host name db7-replica"),
        ("0xc0.0x00.0x02.0x09", "holds the address of the host 0xc0.0x00.0x02.0x09"),
        ("sm7", "holds the host name sm7"),
        ("int7", "holds the host name int7"),
        ("cu7", "holds the host name cu7"),
        ("py4", "holds the host name py4"),
        ("tf3", "holds the host name tf3"),
        # A whole name written with the dot that ends it, a name under a country's domain,
        # tags with a number their family does not have, a name and a number in a text, after
        # = or in quotes after a short host option, and an address written as one decimal
        # number, as four numbers of which some are octal, or with underscores in a name.
        ("db7.madeup-corp.net.", "holds the host name db7.madeup-corp.net"),
        ("db7.madeup-corp.tw", "holds the host name db7.madeup-corp.tw"),
        ("db7.madeup-corp.lv", "holds the host name db7.madeup-corp.lv"),
        ("cuda01", "holds the host name cuda01"),
        ("rocm6", "holds the host name rocm6"),
        ("sm900", "holds the host name sm900"),
        ("py310", "holds the host name py310"),
        ("connect db7 now", "holds the host name db7"),
        ("server=db7", "holds the host name db7"),
        ("psql -H 'db7'", "holds the host name db7"),
        ("167780105", "holds the address of the host 167780105"),
        ("012.0115.037.011", "holds the address of the host 012.0115.037.011"),
        ("ip_10_77_31_9", "holds the host name ip_10_77_31_9"),
        # A CUDA tag longer than any version has, and an address as a hexadecimal number of
        # seven digits.
        ("cuda12345", "holds the host name cuda12345"),
        ("0xa4d1f09", "holds the address of the host 0xa4d1f09"),
    ],
    ids=[
        "an-ip-address",
        "an-ip-address-and-port",
        "a-user-at-an-ip-address",
        "an-ipv6-address",
        "an-ipv6-address-and-port",
        "a-host-and-port",
        "a-user-at-a-host",
        "a-host-option",
        "a-host-variable",
        "a-private-domain",
        "a-home-folder-by-name",
        "a-windows-drive-path",
        "a-windows-network-path",
        "four-numbers-without-a-sign-of-a-version",
        "a-name-and-a-number-read-as-a-port",
        "a-name-and-a-number",
        "a-short-host-option",
        "a-variable-whose-name-ends-in-host",
        "an-address-written-in-a-name",
        "an-address-written-in-a-name-in-a-text",
        "a-name-under-a-public-domain",
        "an-address-as-one-hexadecimal-number",
        "a-host-glued-to-a-short-host-option",
        "a-longer-host-glued-to-a-short-host-option",
        "an-address-as-four-hexadecimal-numbers",
        "a-name-shaped-as-a-compute-capability-tag",
        "a-name-shaped-as-a-number-type",
        "a-name-shaped-as-a-cuda-tag",
        "a-name-shaped-as-an-interpreter-tag",
        "a-name-shaped-as-a-tensor-float-type",
        "a-whole-name-with-its-ending-dot",
        "a-name-under-a-country-domain",
        "a-name-of-three-parts-under-any-country-domain",
        "a-cuda-tag-with-a-leading-zero",
        "a-rocm-tag-of-one-digit",
        "a-compute-capability-tag-of-a-wrong-number",
        "an-interpreter-tag-the-tool-does-not-run-on",
        "a-name-and-a-number-in-a-text",
        "a-name-and-a-number-after-an-equals-sign",
        "a-name-and-a-number-in-quotes-after-a-short-host-option",
        "an-address-as-one-decimal-number",
        "an-address-as-four-octal-numbers",
        "an-address-written-in-a-name-with-underscores",
        "a-cuda-tag-longer-than-a-version",
        "an-address-as-seven-hexadecimal-digits",
    ],
)
def test_an_address_a_host_or_a_path_of_another_machine_fails(
    pair: Path, planted: str, problem: str
) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [f"run/results.json: {problem}"]


def test_a_host_given_as_the_word_after_host_or_under_a_host_key_fails(pair: Path) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, "--host", OTHER_HOST])
    plant(
        pair,
        "b",
        "fingerprint",
        lambda inputs: {**inputs, "launch": {**inputs["launch"], "env": {"DB_HOST": "db7"}}},
    )

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: holds the host name db7",
        f"run/results.json: holds the host name {OTHER_HOST}",
    ]


@pytest.mark.parametrize(
    ("planted", "host"),
    [
        (["-H", "made-up-db"], "made-up-db"),
        (["-h", "made-up-db"], "made-up-db"),
        ({"PGHOST": "made-up-db"}, "made-up-db"),
        (["psql -H 'made-up-db'"], "made-up-db"),
        (['--host "made-up-db"'], "made-up-db"),
    ],
    ids=[
        "after-capital-h",
        "after-small-h",
        "under-a-key-that-ends-in-host",
        "in-quotes-after-capital-h",
        "in-quotes-after-the-long-option",
    ],
)
def test_a_host_given_after_a_short_host_option_or_under_a_glued_host_key_fails(
    pair: Path, planted: Any, host: str
) -> None:
    if isinstance(planted, dict):
        plant(
            pair,
            "b",
            "fingerprint",
            lambda inputs: {**inputs, "launch": {**inputs["launch"], "env": planted}},
        )
    else:
        plant(pair, "a", "argv_sha256", lambda argv: [*argv, *planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        f"run/results.json: holds the host name {host}"
    ]


@pytest.mark.parametrize(
    "planted",
    [
        "numpy==1.2.3.4",
        "v1.2.3.4",
        "127.0.0.1:8000",
        "0.0.0.0:8000",
        "localhost:8000",
        "::1",
        "--host=0.0.0.0",
        f"{OTHER_USER}@example.com",
        "made-up.example:8080",
        "std::chrono::steady_clock",
        "12:34:56",
        "/work/a:/showcase:ro",
        "~user/bench",
        "~/bench",
        "python:3.13-slim@sha256:" + "e4" * 32,
        "redis:7.2",
        "4096.3.2.1",
        "bench.py",
        "requirements.txt",
        "made-up.bench.py",
        "torch.version.cuda",
        "qwen2.5-0.5b-instruct",
        "0x1f",
        "0x00000000000000a4",
        "-H 'Accept: text/plain'",
        "python3",
        # Whole numbers below the lowest address of one decimal number, or above the highest.
        "16777215",
        "4294967296",
        "1_000_000_000",
        # Words with a number that the showcases and their fingerprints hold.
        "py313",
        "cuda1343",
        "float32",
        "bfloat16",
        "TF32",
        "aarch64",
        "SHA-256",
        "sha256",
        "sm90",
        "cu121",
        "int8",
        "uint16",
        "fp8",
        "py3",
        "cp312",
        "rocm62",
        # A group of one-letter options, and a header glued to -H.
        "-hv",
        "-HAccept:text/plain",
    ],
)
def test_a_version_a_loopback_or_a_documentation_name_passes(pair: Path, planted: str) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []


@pytest.mark.parametrize(
    ("shape", "planted"),
    [
        ("file-address", f"file://{HOME_PATH}"),
        ("glued-to-a-short-option", f"-L{HOME_PATH}"),
        ("after-a-redirection", f"made-up-tool>{HOME_PATH}"),
        ("after-a-pipe", f"made-up-tool|{HOME_PATH}"),
        ("after-an-at-sign", f"@{HOME_PATH}"),
    ],
)
def test_a_home_path_in_each_shape_fails(pair: Path, shape: str, planted: str) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        f"run/results.json: holds the path {HOME_PATH}",
        "run/results.json: holds the user name",
    ]


def plant_config(folder: Path, change: Any) -> None:
    """Change the config inputs and write the hash they give into the results."""
    sidecar = read(folder / SIDECAR)
    results = read(folder / RESULTS)
    configs = sidecar["provenance"]["config_sha256"]
    configs[0] = change(configs[0])
    results["provenance"]["config_sha256"] = combine_hashes(
        [sha256_hex(canonical_json(config)) for config in configs]
    )
    write(folder / SIDECAR, sidecar)
    write(folder / RESULTS, results)


def test_an_image_of_a_registry_that_names_a_machine_fails(pair: Path) -> None:
    def imaged(config: dict[str, Any]) -> dict[str, Any]:
        config["sides"]["a"]["image"] = "registry.markerhost-b.example:5000/made-up:1"
        return config

    plant_config(pair, imaged)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: holds the image registry registry.markerhost-b.example"
    ]


def test_a_server_path_passes_and_a_home_path_beside_it_fails(pair: Path) -> None:
    def served(config: dict[str, Any]) -> dict[str, Any]:
        config["sides"]["a"]["serve"] = {
            "ready": {"http": "/made-up/health"},
            "probe": {"path": "/v1/made-up"},
            "model": HOME_PATH,
        }
        return config

    plant_config(pair, served)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        f"run/results.json: holds the path {HOME_PATH}",
        "run/results.json: holds the user name",
    ]


@pytest.mark.parametrize(
    "reference",
    ["python:3.13-slim", "library/python:3.13", "docker.io/library/python:3.13", "nvcr.io/x/y:1"],
)
def test_an_image_of_a_public_registry_passes(pair: Path, reference: str) -> None:
    def imaged(config: dict[str, Any]) -> dict[str, Any]:
        config["sides"]["a"]["image"] = reference
        return config

    plant_config(pair, imaged)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []


def test_a_sidecar_that_holds_a_value_of_the_environment_fails(pair: Path) -> None:
    plant(pair, "a", "identify_sha256", lambda text: text + f"made-up {ENV_VALUE}\n")

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        "run/results.json: holds the value of the environment variable MADE_UP_SETTING"
    ]


@pytest.mark.parametrize(
    ("planted", "problem"),
    [
        (f"bench-{HOST}", "holds the host name"),
        (f"{HOST}_build", "holds the host name"),
        (f"--name={USER}-cache", "holds the user name"),
        (f"made-up_{USER}", "holds the user name"),
        (f"{ENV_VALUE}-made-up", "holds the value of the environment variable MADE_UP_SETTING"),
        (f"made-up.{ENV_VALUE}", "holds the value of the environment variable MADE_UP_SETTING"),
    ],
)
def test_a_name_joined_to_other_words_by_a_dash_a_dot_or_an_underscore_fails(
    pair: Path, planted: str, problem: str
) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [f"run/results.json: {problem}"]


@pytest.mark.parametrize(
    "planted", [f"x{HOST}", f"{USER}2b", f"{ENV_VALUE}x", f"made-up-{HOST[:-2]}"]
)
def test_a_longer_word_that_holds_a_name_passes(pair: Path, planted: str) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []


@pytest.mark.parametrize(
    "planted", ["/work/../srv/made-up/bin/tool", "--log=/usr/../srv/made-up/log"]
)
def test_a_path_that_climbs_out_of_a_neutral_folder_fails(pair: Path, planted: str) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, planted])
    path = planted.partition("=")[2] or planted

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        f"run/results.json: holds the path {path}"
    ]


def test_a_path_that_stays_inside_a_neutral_folder_passes(pair: Path) -> None:
    plant(pair, "a", "argv_sha256", lambda argv: [*argv, "/usr/bin/../lib/made-up"])

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == []


@pytest.mark.parametrize(
    ("key", "change", "problems"),
    [
        # The token, as a whole value or as a word after =, is also one the walk cannot tell
        # from a host.
        (
            "argv_sha256",
            lambda argv: [*argv, f"--api-key={TOKEN}"],
            [
                "side a: the inputs of argv_sha256 hold a hidden value",
                f"holds the host name {TOKEN}",
            ],
        ),
        (
            "identify_sha256",
            lambda text: text + f"API_TOKEN={TOKEN}\n",
            [
                "side a: the inputs of identify_sha256 hold a hidden value",
                f"holds the host name {TOKEN}",
            ],
        ),
        (
            "fingerprint",
            lambda inputs: {**inputs, "launch": {**inputs["launch"], "env": {"API_TOKEN": TOKEN}}},
            [
                "side a: the inputs of fingerprint hold a hidden value",
                f"holds the host name {TOKEN}",
            ],
        ),
    ],
    ids=["argv_sha256", "identify_sha256", "fingerprint"],
)
def test_inputs_of_a_side_that_show_a_value_the_hashes_hide_fail(
    pair: Path, key: str, change: Any, problems: list[str]
) -> None:
    plant(pair, "a", key, change)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [
        f"run/results.json: {problem}" for problem in problems
    ]


def _extra_hash(sidecar: dict[str, Any]) -> None:
    sidecar["sides"]["a"]["args_sha256"] = ["made-up-server"]


def _extra_side(sidecar: dict[str, Any]) -> None:
    sidecar["sides"]["c"] = copy.deepcopy(sidecar["sides"]["a"])


def _other_schema(sidecar: dict[str, Any]) -> None:
    sidecar["schema"] = "pairbench/hash-inputs/v0"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (_extra_hash, "side a: inputs of a hash the results do not show: args_sha256"),
        (_extra_side, "inputs for a side the results do not name: c"),
        (_other_schema, "the schema is not pairbench/hash-inputs/v1"),
    ],
    ids=["a-hash-not-shown", "a-side-not-named", "another-schema"],
)
def test_a_sidecar_that_does_not_match_its_results_fails(
    pair: Path, change: Any, problem: str
) -> None:
    sidecar = read(pair / SIDECAR)
    change(sidecar)
    write(pair / SIDECAR, sidecar)

    assert problems_of(pair / RESULTS, pair.parent, MARKED) == [f"run/results.json: {problem}"]


def _git(root: Path, *args: str) -> None:
    environ = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", *args], cwd=root, env=environ, check=True, capture_output=True)


def test_the_walk_finds_each_results_file_a_checkout_tracks_or_would_track(
    tmp_path: Path,
) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    _git(tmp_path, "init", "-q")
    for name in (
        "kept/results.json",
        "kept/other.json",
        "kept/results.json.old",
        "new/results.json",
        "ignored/results.json",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text('{"sides": []}\n', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _git(tmp_path, "add", "kept/results.json", "kept/other.json", ".gitignore")

    assert sorted(tracked_results(tmp_path)) == [
        tmp_path / "kept" / "results.json",
        tmp_path / "new" / "results.json",
    ]
    assert walk_problems(tmp_path, MARKED) == [
        "kept/results.json: no hash_inputs.json beside it",
        "new/results.json: no hash_inputs.json beside it",
    ]


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        ("arm64, 4 cores, 16 GB\n", []),
        ("m7g.xlarge\n", []),
        (
            "markerhost-b.lab.internal\n",
            [
                "kept/machine-class.txt: is not a class of machine in a public form",
                "kept/machine-class.txt: holds the host name markerhost-b.lab.internal",
            ],
        ),
        (
            f"a laptop called {HOST}\n",
            [
                "kept/machine-class.txt: is not a class of machine in a public form",
                "kept/machine-class.txt: holds the host name",
            ],
        ),
        (
            "arm64, 4 cores, 16 GB at 192.0.2.7\n",
            [
                "kept/machine-class.txt: is not a class of machine in a public form",
                "kept/machine-class.txt: holds the address of the host 192.0.2.7",
            ],
        ),
    ],
    ids=["cores-and-memory", "an-instance-type", "a-host-name", "the-machine-s-name", "an-address"],
)
def test_the_walk_holds_each_class_of_machine_to_the_public_form(
    tmp_path: Path, text: str, problems: list[str]
) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    _git(tmp_path, "init", "-q")
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / MACHINE_CLASS).write_text(text, encoding="utf-8")

    assert walk_problems(tmp_path, MARKED) == problems


# Instance types whose names end in a number, as the script accepts them: a number at the end
# of a word reads as a host name elsewhere, but not in a class the script's own forms accept.
NUMBERED_CLASSES = (
    "n2-standard-4",
    "n2d-standard-4",
    "c3-standard-4",
    "c4-standard-4",
    "c4a-standard-4",
    "t2a-standard-4",
    "e2-standard-4",
)


@pytest.mark.parametrize("given", NUMBERED_CLASSES)
def test_the_walk_keeps_an_instance_type_whose_name_ends_in_a_number(
    tmp_path: Path, given: str
) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    _git(tmp_path, "init", "-q")
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / MACHINE_CLASS).write_text(given + "\n", encoding="utf-8")

    assert walk_problems(tmp_path, MARKED) == []


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        (
            "made-up-host-01\n",
            [
                "kept/machine-class.txt: is not a class of machine in a public form",
                "kept/machine-class.txt: holds the host name made-up-host-01",
            ],
        ),
        (
            "c4a-standard-4 on made-up-host-01\n",
            [
                "kept/machine-class.txt: is not a class of machine in a public form",
                "kept/machine-class.txt: holds the host name made-up-host-01",
            ],
        ),
    ],
    ids=["a-numbered-host", "an-instance-type-and-a-host"],
)
def test_the_walk_reads_a_numbered_word_outside_the_public_forms_as_a_host_name(
    tmp_path: Path, text: str, problems: list[str]
) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    _git(tmp_path, "init", "-q")
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / MACHINE_CLASS).write_text(text, encoding="utf-8")

    assert walk_problems(tmp_path, MARKED) == problems


# A made-up class of machine in the short public form.
MADE_UP_CLASS = "arm64, 4 cores, 16 GB\n"
KEPT_RESULTS = f"{KEPT_COST}/{RESULTS}"
NO_SIDECAR = f"{KEPT_RESULTS}: no {SIDECAR} beside it, and run.command"


def keep_cost(root: Path, run: Path) -> Path:
    """A made-up checkout keeping a run's results and a class of machine in the launch-cost
    folder, as the launch-cost results are kept: without their sidecar."""
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    _git(root, "init", "-q")
    folder = root / KEPT_COST
    folder.mkdir(parents=True)
    shutil.copyfile(run / RESULTS, folder / RESULTS)
    (folder / MACHINE_CLASS).write_text(MADE_UP_CLASS, encoding="utf-8")
    _git(root, "add", KEPT_COST)
    return folder


def show_command(folder: Path, change: Any) -> None:
    results = read(folder / RESULTS)
    results["run"]["command"] = change(results["run"]["command"])
    write(folder / RESULTS, results)


def test_the_walk_keeps_the_launch_cost_results_without_their_sidecar(
    made: Path, tmp_path: Path
) -> None:
    folder = keep_cost(tmp_path, made)

    assert (
        "--side 'a=cmd:<hidden>' --side 'b=cmd:<hidden>'"
        in read(folder / RESULTS)["run"]["command"]
    )
    assert walk_problems(tmp_path, MARKED) == []


@pytest.mark.parametrize(
    ("change", "problems"),
    [
        (
            lambda c: c.replace("'a=cmd:<hidden>'", "'a=cmd:true'"),
            [f"{NO_SIDECAR} shows the side a as typed"],
        ),
        (
            lambda c: c.replace("--side 'a=cmd:<hidden>'", "--side='a=image:made/up:1.2'"),
            [f"{NO_SIDECAR} shows the side a as typed"],
        ),
        (
            lambda c: c.replace("--side 'a=cmd:<hidden>' ", ""),
            [f"{NO_SIDECAR} does not show each side as KIND:<hidden>"],
        ),
        (
            lambda c: c.replace("--side 'a=cmd:<hidden>' --side 'b=cmd:<hidden>' ", ""),
            [f"{NO_SIDECAR} does not show each side as KIND:<hidden>"],
        ),
        (
            lambda c: c.replace("'b=cmd:<hidden>'", "'c=cmd:<hidden>'"),
            [f"{NO_SIDECAR} does not show each side as KIND:<hidden>"],
        ),
        (
            lambda c: c + " 'unclosed",
            [f"{NO_SIDECAR} does not show each side as KIND:<hidden>"],
        ),
    ],
    ids=[
        "a-side-as-typed",
        "an-image-reference",
        "a-side-left-out",
        "no-side",
        "another-side",
        "unreadable",
    ],
)
def test_the_walk_keeps_no_launch_cost_results_that_show_a_side(
    made: Path, tmp_path: Path, change: Any, problems: list[str]
) -> None:
    folder = keep_cost(tmp_path, made)
    show_command(folder, change)

    assert walk_problems(tmp_path, MARKED) == problems


def test_the_walk_keeps_no_launch_cost_results_without_the_class_of_machine(
    made: Path, tmp_path: Path
) -> None:
    folder = keep_cost(tmp_path, made)
    (folder / MACHINE_CLASS).unlink()

    assert walk_problems(tmp_path, MARKED) == [f"{KEPT_RESULTS}: no {MACHINE_CLASS} beside it"]


def test_the_walk_refuses_a_class_of_machine_the_script_refuses_beside_the_cost_results(
    made: Path, tmp_path: Path
) -> None:
    folder = keep_cost(tmp_path, made)
    (folder / MACHINE_CLASS).write_text("arm64, 4 cores, 16GB\n", encoding="utf-8")

    assert walk_problems(tmp_path, MARKED) == [
        f"{KEPT_COST}/{MACHINE_CLASS}: is not a class of machine in a public form"
    ]


@pytest.mark.parametrize(
    "name",
    [
        "report.html",
        "results.md",
        "diagnostics.json",
        "profiles/flame.svg",
        "capture.jsonl",
        "old/results.json",
    ],
)
def test_the_walk_refuses_any_other_file_beside_the_cost_results(
    made: Path, tmp_path: Path, name: str
) -> None:
    folder = keep_cost(tmp_path, made)
    (folder / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(made / RESULTS, folder / name)
    _git(tmp_path, "add", f"{KEPT_COST}/{name}")
    beside = [f"{KEPT_COST}/{name}: no {SIDECAR} beside it"] if name.endswith(RESULTS) else []

    assert walk_problems(tmp_path, MARKED) == [
        *beside,
        f"{KEPT_COST}/{name}: is not kept beside the launch-cost results",
    ]


@pytest.mark.parametrize(
    "folder",
    ["docs/figures/other", "docs/figures/launch-cost-made-up", "docs/launch-cost", "launch-cost"],
)
def test_the_walk_keeps_results_elsewhere_only_with_their_sidecar(
    made: Path, tmp_path: Path, folder: str
) -> None:
    keep_cost(tmp_path, made)
    (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(made / RESULTS, tmp_path / folder / RESULTS)
    (tmp_path / folder / MACHINE_CLASS).write_text(MADE_UP_CLASS, encoding="utf-8")

    assert walk_problems(tmp_path, MARKED) == [f"{folder}/{RESULTS}: no {SIDECAR} beside it"]


def test_the_walk_checks_a_sidecar_beside_the_cost_results_as_anywhere(
    showcase: Path, tmp_path: Path
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    folder = keep_cost(root, showcase)
    shutil.copyfile(showcase / SIDECAR, folder / SIDECAR)

    assert walk_problems(root, MARKED) == []

    sidecar = read(folder / SIDECAR)
    sidecar["schema"] = "pairbench/hash-inputs/v0"
    write(folder / SIDECAR, sidecar)

    # The shared files do not show the one value changed: the schema the sidecar names.
    assert walk_problems(root, MARKED) == [
        f"{KEPT_RESULTS}: the schema is not {SCHEMA}",
        PRIVATE_BESIDE.format(1),
    ]


# What the walk says of a sidecar beside the launch-cost results that the shared files do not
# show every value of: a launch-cost run's own sidecar is such a one, since its results hide
# each side command.
PRIVATE_BESIDE = (
    f"{KEPT_RESULTS}: the {SIDECAR} beside it is private: the shared files do not show {{}} "
    "of the values it holds"
)


@pytest.fixture
def showcase(tmp_path: Path, writer: ModuleType) -> Path:
    """A run of the showcase sides, written without measuring, with the sidecar the writer
    writes: one whose values the shared files all show."""
    folder = showcase_run(tmp_path / "showcase-run")
    assert write_sidecar(writer, folder) == (EXIT_OK, "")
    return folder


def test_the_walk_refuses_a_private_sidecar_beside_the_cost_results(
    pair: Path, tmp_path: Path
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    folder = keep_cost(root, pair)
    shutil.copyfile(pair / SIDECAR, folder / SIDECAR)

    # The results show each side as cmd:<hidden>, so four values the sidecar holds for the
    # sides are not shown.
    assert walk_problems(root, MARKED) == [PRIVATE_BESIDE.format(4)]


# What the walk says of a symbolic link in the launch-cost folder, or of the folder as one: git
# keeps the link and not the file it names, so the files the walk reads through it are not the
# ones the repository holds.
LINKED = "is a symbolic link; the launch-cost results are kept as files"


@pytest.mark.parametrize(
    ("name", "target"),
    [
        (RESULTS, "outside"),
        (MACHINE_CLASS, "outside"),
        (RESULTS, "refused"),
        (MACHINE_CLASS, "refused"),
        (SIDECAR, "nowhere"),
        ("report.html", "nowhere"),
        ("run", "a-folder"),
    ],
    ids=[
        "the-results",
        "the-class",
        "results-that-show-a-side",
        "a-class-that-names-a-host",
        "a-sidecar-to-nowhere",
        "a-page-to-nowhere",
        "a-folder",
    ],
)
def test_the_walk_refuses_a_symbolic_link_beside_the_cost_results(
    made: Path, tmp_path: Path, name: str, target: str
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    folder = keep_cost(root, made)
    outside = tmp_path / "outside"
    outside.mkdir()
    if target in ("outside", "refused"):
        shutil.copyfile(folder / name, outside / name)
        (folder / name).unlink()
        os.symlink(outside / name, folder / name)
        # A file the walk would refuse if it read it through the link: it reads none.
        if target == "refused" and name == RESULTS:
            show_command(outside, lambda c: c.replace("'a=cmd:<hidden>'", "'a=cmd:true'"))
        elif target == "refused":
            (outside / name).write_text("made-up-host-01\n", encoding="utf-8")
    elif target == "a-folder":
        os.symlink(outside, folder / name)
    else:
        os.symlink(tmp_path / "nowhere" / name, folder / name)
    _git(root, "add", f"{KEPT_COST}/{name}")

    assert walk_problems(root, MARKED) == [f"{KEPT_COST}/{name}: {LINKED}"]


def test_the_walk_reads_no_sidecar_beside_the_cost_results_through_a_symbolic_link(
    pair: Path, tmp_path: Path
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    folder = keep_cost(root, pair)
    # The run's own sidecar, outside the checkout: private, so read as one it would be refused.
    os.symlink(pair / SIDECAR, folder / SIDECAR)
    _git(root, "add", f"{KEPT_COST}/{SIDECAR}")

    assert walk_problems(root, MARKED) == [f"{KEPT_COST}/{SIDECAR}: {LINKED}"]


def test_the_walk_refuses_the_cost_folder_as_a_symbolic_link(made: Path, tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git to list the files of a checkout")
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q")
    (tmp_path / "real").mkdir()
    real = keep_cost(tmp_path / "real", made)
    (root / KEPT_COST).parent.mkdir(parents=True)
    os.symlink(real, root / KEPT_COST)
    _git(root, "add", KEPT_COST)

    assert walk_problems(root, MARKED) == [f"{KEPT_COST}: {LINKED}"]


def test_the_writer_refuses_a_run_whose_recorded_hashes_it_cannot_give(
    made: Path, tmp_path: Path, writer: ModuleType
) -> None:
    folder = tmp_path / "run"
    shutil.copytree(made, folder)
    results = read(folder / RESULTS)
    results["sides"][0]["fingerprint"] = "f" * 64
    write(folder / RESULTS, results)

    code, err = write_sidecar(writer, folder)

    assert code == EXIT_MISMATCH
    assert f"side {results['sides'][0]['name']}: " in err
    assert "fingerprint" in err
    assert not (folder / SIDECAR).exists()


def test_the_writer_refuses_a_folder_without_results(tmp_path: Path, writer: ModuleType) -> None:
    code, err = write_sidecar(writer, tmp_path)

    assert code == EXIT_USAGE
    assert "results.json" in err
    assert not (tmp_path / SIDECAR).exists()


NOT_RESULTS = "no hash_inputs.json written: results.json is not a results document: {}\n"


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ([], "it is not a JSON object"),
        ("made-up text", "it is not a JSON object"),
        ({"sides": "a"}, "its sides are not a list of tables"),
        ({"sides": ["a"]}, "its sides are not a list of tables"),
        ({}, "its sides are not a list of tables"),
        ({"sides": []}, "it names no side"),
        ({"sides": [{"identity": {}}]}, "a side has no name"),
        ({"sides": [{"name": "a", "identity": []}]}, "the identity of side a is not a table"),
        ({"sides": [{"name": "a"}], "provenance": "x"}, "its provenance is not a table"),
    ],
    ids=[
        "a-list",
        "a-string",
        "sides-as-a-string",
        "sides-as-a-list-of-strings",
        "an-empty-object",
        "no-side",
        "a-side-without-a-name",
        "an-identity-that-is-a-list",
        "provenance-as-a-string",
    ],
)
def test_the_writer_refuses_a_file_that_is_not_a_results_document(
    made: Path, tmp_path: Path, writer: ModuleType, document: Any, reason: str
) -> None:
    folder = tmp_path / "run"
    shutil.copytree(made, folder)
    write(folder / RESULTS, document)

    assert run_writer(writer, folder) == (EXIT_USAGE, "", NOT_RESULTS.format(reason))
    assert not (folder / SIDECAR).exists()


def test_a_refusal_removes_the_sidecar_of_the_results_before_the_change(
    pair: Path, writer: ModuleType
) -> None:
    results = read(pair / RESULTS)
    results["sides"][0]["fingerprint"] = "f" * 64
    write(pair / RESULTS, results)

    code, out, err = run_writer(writer, pair)

    assert (code, out) == (EXIT_MISMATCH, "")
    assert err.startswith("no hash_inputs.json written: ")
    assert not (pair / SIDECAR).exists()


def test_a_results_file_that_is_no_results_document_removes_the_earlier_sidecar(
    pair: Path, writer: ModuleType
) -> None:
    write(pair / RESULTS, [])

    assert run_writer(writer, pair) == (
        EXIT_USAGE,
        "",
        NOT_RESULTS.format("it is not a JSON object"),
    )
    assert not (pair / SIDECAR).exists()


def test_a_write_that_fails_leaves_no_sidecar_and_no_other_file(
    pair: Path, writer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = sorted(path.name for path in pair.iterdir())

    def refuse(source: object, target: object) -> None:
        raise OSError("made-up full disk")

    monkeypatch.setattr(writer.os, "replace", refuse)
    code, out, err = run_writer(writer, pair)

    assert (code, out, err) == (EXIT_USAGE, "", "no hash_inputs.json written: made-up full disk\n")
    assert SIDECAR in names
    assert sorted(path.name for path in pair.iterdir()) == [n for n in names if n != SIDECAR]


# ---------------------------------------------------------------------------
# The run the launch-cost script makes, built without measuring
# ---------------------------------------------------------------------------


def experiment_of(command: list[str]) -> Any:
    """The experiment ``pairbench run`` builds from an argument list."""
    from pairbench.cli.common import add_experiment_arguments, experiment_from

    parser = argparse.ArgumentParser()
    add_experiment_arguments(parser)
    parser.set_defaults(after=[])
    return experiment_from(parser.parse_args(command[command.index("run") + 1 :]))


def would_write(
    writer: ModuleType, folder: Path, experiment: Any, sides: list[Any], typed: list[str]
) -> Any:
    """Write the results and the sidecar a run of ``experiment`` with these sides would keep.

    ``typed`` is the ``pairbench run`` command. The results show it, and each side, the way a
    run's results show them.
    """
    config = experiment.to_json()
    include = experiment.report.include_image_refs
    capture = Capture(
        capture_id="made-up-run",
        header=Header(capture_id="made-up-run", config=config),
        sides=tuple(sides),
    )
    results = {
        "schema": "pairbench/results/v1",
        "run": {"command": model.public_command(tuple(typed), include_image_refs=include)},
        "sides": [s.for_results(include_image_ref=include).to_json() for s in sides],
        "provenance": {"config_sha256": config_sha256(config)},
    }
    folder.mkdir(parents=True)
    write(folder / RESULTS, results)
    write(folder / SIDECAR, writer.hash_inputs([capture], results))
    return read(folder / SIDECAR)


# What the sidecar of the launch-cost run holds that its results hide: the options and the
# workload of its two sides, which the results show as `cmd:<hidden>`, and the interpreter's
# name, which only the sidecar holds. So the script's publish keeps the sidecar private and
# publishes the shared files without it.
LAUNCH_COST_UNSHOWN = [
    "-I",
    "-S",
    "-c",
    "python3",
    "total = sum(i * i for i in range(20000))",
]


def test_the_launch_cost_run_would_write_a_neutral_sidecar_that_stays_private(
    repo_root: Path, writer: ModuleType, tmp_path: Path
) -> None:
    launch_cost = load(repo_root, "launch_cost")
    relative = "pairbench-runs/launch-cost-made-up"
    inner = launch_cost.inner_command(relative)
    experiment = experiment_of(inner)
    sides = []
    for side in experiment.sides:
        command = tuple(side.spec["argv"])
        identity = {
            "executable": launch_cost.PUBLIC_PYTHON,
            "executable_sha256": "e" * 64,
            "argv_sha256": argv_sha256(command),
        }
        launch = experiment.launch.for_side(side).effective(args=command)
        sides.append(side.with_identity(identity, fingerprint_of(identity, launch)))
    folder = tmp_path / relative
    sidecar = would_write(writer, folder, experiment, sides, ["pairbench", *inner[3:]])

    assert problems_of(folder / RESULTS, tmp_path, MARKED) == []
    assert writer.hidden_values(read(folder / RESULTS), "", sidecar) == LAUNCH_COST_UNSHOWN
    assert sorted(sidecar["sides"]) == ["default", "nosite"]
    assert {e["fingerprint"]["identity"]["executable"] for e in sidecar["sides"].values()} == {
        "python3"
    }
    assert sidecar["provenance"]["config_sha256"][0]["run"]["out"] == relative


# ---------------------------------------------------------------------------
# The runs each showcase publishes, built without measuring
# ---------------------------------------------------------------------------

SHOWCASES = sorted(
    path.parent.name for path in (Path(__file__).parents[3] / "showcases").glob("*/pairbench.toml")
)
# The mount each run.sh types, after the showcase's folder.
MOUNT = re.compile(r'launch\.mounts=\[\\"\$here([^\\"]*)\\"\]')
IMAGE_IDENTITY = {
    "image_id": "sha256:" + "a" * 64,
    "digests": ["sha256:" + "b" * 64],
    "platform": "linux/amd64",
}
# A program or file each showcase's sides run. The sidecar holds it, and the results show
# each side as `KIND:<hidden>`, so no shared file shows it: publish mode keeps each of these
# sidecars private and publishes the shared files without it.
SHOWCASE_WORKLOAD = {
    "gpu-kernel": "/showcase/.build/cuda1343/kernel_bench",
    "inference-server-versions": "/models/Qwen2.5-0.5B-Instruct",
    "noisy-neighbour": "/showcase/spin.py",
    "numpy-pip-vs-conda": "/showcase/bench.py",
    "pipeline-slowdown-check": "/showcase/tests",
    "python-versions": "/showcase/bench.py",
    "vendor-container-vs-pip": "/showcase/bench.py",
}


@pytest.mark.parametrize("name", SHOWCASES)
def test_each_showcase_would_write_a_neutral_sidecar_that_stays_private(
    repo_root: Path, writer: ModuleType, tmp_path: Path, name: str
) -> None:
    from pairbench.config import load_experiment
    from pairbench.sides import container, serve

    base = repo_root / "showcases" / name
    found = MOUNT.findall((base / "run.sh").read_text(encoding="utf-8"))
    mounts = sorted({f"/work/showcases/{name}{rest}" for rest in found})
    experiment = load_experiment(
        base / "pairbench.toml", environ={}, sets=[f"launch.mounts={json.dumps(mounts)}"]
    )
    sides = []
    for side in experiment.sides:
        settings = experiment.launch.for_side(side)
        identity: dict[str, Any] = dict(IMAGE_IDENTITY)
        if side.kind == "serve":
            spec = serve.serve_spec(side)
            identity["args_sha256"] = argv_sha256(spec.args)
            launch = serve._effective(settings, spec, "docker")
        else:
            launch = container._effective(settings, container.image_spec(side))
        sides.append(side.with_identity(identity, fingerprint_of(identity, launch)))
    published = tmp_path / "showcases" / name / "published"
    typed = [
        "pairbench",
        "run",
        "--config",
        "pairbench.toml",
        "--set",
        f"launch.mounts={json.dumps(mounts)}",
        "--out",
        f"pairbench-runs/publish-made-up/{published.name}",
    ]
    sidecar = would_write(writer, published, experiment, sides, typed)

    assert len(found) >= 1
    assert problems_of(published / RESULTS, tmp_path, MARKED) == []
    assert sorted(sidecar["sides"]) == sorted(side.name for side in experiment.sides)
    assert sidecar["provenance"]["config_sha256"][0]["launch"]["mounts"] == mounts
    assert SHOWCASE_WORKLOAD[name] in writer.hidden_values(read(published / RESULTS), "", sidecar)


# ---------------------------------------------------------------------------
# Who may read the sidecar: private unless the shared files show each value it holds
# ---------------------------------------------------------------------------

PRIVATE = (
    "hash_inputs.json is private: the shared files do not show {} of the values it holds; "
    "keep it with capture.jsonl\n"
)
SHAREABLE = "hash_inputs.json holds only what the shared files show; it can be shared\n"
PUBLISHED = "published results.json, results.md and hash_inputs.json into {}\n"
# A publish of a run whose sidecar cannot be shared: the three shared files on standard output,
# and on standard error which file stays private and why.
PUBLISHED_WITHOUT_SIDECAR = "published results.json, results.md and report.html into {}\n"
KEPT_PRIVATE = (
    "hash_inputs.json is kept private in the run folder, owner-only, and not published: "
    "the shared files do not show {} of the values it holds\n"
)
PRIVATE_MODE = 0o600
# The files a publish shares, when the run wrote them.
SHARED = ("results.json", "results.md", "report.html")
# A made-up report page, written beside a run made without measuring.
REPORT_PAGE = "<!doctype html><title>made-up report</title>\n"
# A run shaped as a showcase publishes one: two public images shown by reference, the workload
# typed after --, and the folder each side runs in, the neutral place /work, named by a setting
# the results hide.
WORKDIR = "launch.workdir=/work"
SHOWCASE = (
    "run",
    "--side",
    "a=image:python:3.12-slim",
    "--side",
    "b=image:python:3.13-slim",
    "--baseline",
    "b",
    "--set",
    "report.include_image_refs=true",
    "--set",
    WORKDIR,
    "--out",
    "published",
    "--",
    "python",
    "-c",
    "pass",
)
IMAGE_IDS = {"a": "sha256:" + "a1" * 32, "b": "sha256:" + "b2" * 32}
DIGESTS = {"a": "sha256:" + "c3" * 32, "b": "sha256:" + "d4" * 32}


def typed_experiment(typed: tuple[str, ...]) -> Any:
    """The experiment ``pairbench run`` builds from ``typed``, its workload after ``--``."""
    from pairbench.cli.common import add_experiment_arguments, experiment_from

    parser = argparse.ArgumentParser()
    add_experiment_arguments(parser)
    cut = typed.index("--") if "--" in typed else len(typed)
    options = parser.parse_args(list(typed[1:cut]))
    options.after = list(typed[cut + 1 :])
    return experiment_from(options)


def showcase_run(
    folder: Path, typed: tuple[str, ...] = SHOWCASE, printed: Mapping[str, str] | None = None
) -> Path:
    """Write the capture, results.json and results.md of a run of ``typed``, without measuring.

    ``printed`` gives what a side's identify command printed. Every hash is made by the
    functions a real run makes it with.
    """
    from pairbench.capture.writer import CaptureWriter
    from pairbench.sides import container

    experiment = typed_experiment(typed)
    config = experiment.to_json()
    include = experiment.report.include_image_refs
    sides = []
    for side in experiment.sides:
        identity: dict[str, Any] = {
            "image_id": IMAGE_IDS[side.name],
            "digests": [DIGESTS[side.name]],
            "platform": "linux/amd64",
        }
        output = (printed or {}).get(side.name)
        if output is not None:
            identity["identify_output"] = output
            identity["identify_sha256"] = sha256_hex(model.hashed_output(output))
        launch = container._effective(experiment.launch.for_side(side), container.image_spec(side))
        sides.append(side.with_identity(identity, fingerprint_of(identity, launch)))
    argv = ("pairbench", *typed)
    folder.mkdir(parents=True)
    with CaptureWriter(folder / "capture.jsonl") as capture:
        capture.write(Header(capture_id="made-up-run", config=config, argv=argv))
        for side in sides:
            capture.write(side)
        capture.end("complete", 0)
    command = model.public_command(argv, include_image_refs=include)
    write(
        folder / RESULTS,
        {
            "schema": "pairbench/results/v1",
            "run": {"command": command},
            "sides": [side.for_results(include_image_ref=include).to_json() for side in sides],
            "provenance": {"config_sha256": config_sha256(config)},
        },
    )
    (folder / "results.md").write_text(
        f"# pairbench results\n\n## How to reproduce\n\n```\n{command}\n```\n", encoding="utf-8"
    )
    return folder


def run_writer(writer: ModuleType, *args: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = writer.main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


def mode_of(path: Path) -> int:
    return path.stat().st_mode & 0o777


def default_mode() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def test_a_sidecar_of_shown_values_published_hashes_and_neutral_places_can_be_shared(
    writer: ModuleType, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert hidden(writer, folder) == []
    assert mode_of(folder / SIDECAR) == default_mode()


def hidden(writer: ModuleType, folder: Path) -> list[str]:
    """The values of the sidecar in ``folder`` that its results.json and results.md do not show."""
    markdown = (folder / "results.md").read_text(encoding="utf-8")
    return list(writer.hidden_values(read(folder / RESULTS), markdown, read(folder / SIDECAR)))


def test_publish_mode_copies_the_shared_files_and_a_sidecar_that_can_be_shared(
    writer: ModuleType, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    published = tmp_path / "showcase" / "published"

    code, out, err = run_writer(writer, folder, "--publish", published)

    assert (code, out, err) == (EXIT_OK, PUBLISHED.format("published"), "")
    assert sorted(path.name for path in published.iterdir()) == [
        SIDECAR,
        "results.json",
        "results.md",
    ]
    for name in (SIDECAR, "results.json", "results.md"):
        assert (published / name).read_bytes() == (folder / name).read_bytes()
    assert problems_of(published / RESULTS, tmp_path, MARKED) == []


def _with_setting(old: str, new: str) -> tuple[str, ...]:
    return tuple(new if part == old else part for part in SHOWCASE)


# Each value the shared files do not show, in the place a run would hold it, and how many
# values of the sidecar it leaves unshown. Every value is made up.
PRIVATE_ROWS = {
    "a-64-hex-secret": ({"a": "5e" * 32 + "\n"}, SHOWCASE, 1),
    "a-40-hex-secret": ({"a": "7c" * 20 + "\n"}, SHOWCASE, 1),
    "a-64-hex-secret-alone": ({"a": "5e" * 32}, SHOWCASE, 1),
    "a-40-hex-secret-alone": ({"a": "7c" * 20}, SHOWCASE, 1),
    "a-piece-of-a-published-hash": ({"a": IMAGE_IDS["b"][17:29] + "\n"}, SHOWCASE, 1),
    "an-internal-image-not-shown": (
        None,
        tuple(
            {
                "a=image:python:3.12-slim": "a=image:registry.made-up.internal:5000/bench:1",
                "report.include_image_refs=true": "report.include_image_refs=false",
            }.get(part, part)
            for part in SHOWCASE
        ),
        2,
    ),
    "a-folder-beside-work": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/workspace/x"),
        1,
    ),
    "a-folder-that-climbs-out-of-work": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/work/../home/name"),
        1,
    ),
    "a-home-folder-beside-the-neutral-one": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/home/username"),
        1,
    ),
    "a-folder-list-that-starts-under-work": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/work/bin:/home/name/bin"),
        1,
    ),
    "a-mount-from-work-to-a-home-folder": (
        None,
        (*SHOWCASE[:-4], "--set", 'launch.mounts=["/work/a:/home/name/b:ro"]', *SHOWCASE[-4:]),
        1,
    ),
    # A folder under a neutral place whose name no shared file shows: as the working folder, in
    # the workload (the results show its last part only), as a mount, and left by its dots.
    "a-made-up-folder-under-work-as-the-working-folder": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/work/made-up-client/run"),
        1,
    ),
    "a-made-up-folder-under-work-in-the-workload": (
        None,
        (*SHOWCASE[:-3], "echo", "/work/made-up-client/data"),
        1,
    ),
    "a-made-up-folder-under-the-neutral-home-in-the-workload": (
        None,
        (*SHOWCASE[:-3], "echo", "/home/user/made-up-project/data"),
        1,
    ),
    "a-made-up-folder-under-work-as-a-mount": (
        None,
        (*SHOWCASE[:-4], "--set", 'launch.mounts=["/work/made-up-client"]', *SHOWCASE[-4:]),
        1,
    ),
    "a-made-up-folder-under-work-left-by-its-dots": (
        None,
        _with_setting(WORKDIR, "launch.workdir=/work/made-up-client/../published"),
        1,
    ),
    # The shown command hides each `--set` value, and a memory cap is of no kind that passes.
    "a-memory-cap-given-with-set": (
        None,
        (*SHOWCASE[:-4], "--set", "launch.memory=8g", *SHOWCASE[-4:]),
        1,
    ),
    # A folder written before the neutral place it leaves by its dots: the results show the
    # last part, work, and no shared file shows the folder.
    "a-made-up-folder-before-work-left-by-its-dots": (
        None,
        (*SHOWCASE[:-3], "echo", "/made-up-client/../work"),
        1,
    ),
}


@pytest.mark.parametrize(
    ("printed", "typed", "count"), list(PRIVATE_ROWS.values()), ids=list(PRIVATE_ROWS)
)
def test_a_value_the_shared_files_do_not_show_keeps_the_sidecar_private(
    writer: ModuleType,
    tmp_path: Path,
    printed: Mapping[str, str] | None,
    typed: tuple[str, ...],
    count: int,
) -> None:
    folder = showcase_run(tmp_path / "run", typed, printed)

    assert run_writer(writer, folder) == (EXIT_OK, "", PRIVATE.format(count))
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE
    assert len(hidden(writer, folder)) == count


@pytest.mark.parametrize(
    ("printed", "typed", "count"), list(PRIVATE_ROWS.values()), ids=list(PRIVATE_ROWS)
)
def test_publish_mode_copies_the_three_shared_files_and_keeps_a_private_sidecar_in_the_run(
    writer: ModuleType,
    tmp_path: Path,
    printed: Mapping[str, str] | None,
    typed: tuple[str, ...],
    count: int,
) -> None:
    folder = with_report(showcase_run(tmp_path / "run", typed, printed))
    published = tmp_path / "published"

    assert run_writer(writer, folder, "--publish", published) == (
        EXIT_OK,
        PUBLISHED_WITHOUT_SIDECAR.format("published"),
        KEPT_PRIVATE.format(count),
    )
    assert sorted(path.name for path in published.iterdir()) == sorted(SHARED)
    for name in SHARED:
        assert (published / name).read_bytes() == (folder / name).read_bytes()
        assert mode_of(published / name) == default_mode()
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE
    assert len(hidden(writer, folder)) == count


def with_report(folder: Path) -> Path:
    """``folder`` with a made-up report page beside its results, as a run writes one."""
    (folder / "report.html").write_text(REPORT_PAGE, encoding="utf-8")
    return folder


def test_publish_mode_removes_an_earlier_sidecar_from_the_folder_when_the_new_one_is_private(
    writer: ModuleType, tmp_path: Path
) -> None:
    printed, typed, count = PRIVATE_ROWS["a-64-hex-secret"]
    published = tmp_path / "published"
    earlier = run_writer(writer, showcase_run(tmp_path / "shared"), "--publish", published)
    stray = published / f".{SIDECAR}.{ended_pid()}.{space_mark()}.{MADE_UP_PART}.tmp"
    stray.write_text("made-up\n", encoding="utf-8")
    folder = with_report(showcase_run(tmp_path / "run", typed, printed))

    later = run_writer(writer, folder, "--publish", published)

    assert earlier == (EXIT_OK, PUBLISHED.format("published"), "")
    assert later == (
        EXIT_OK,
        PUBLISHED_WITHOUT_SIDECAR.format("published"),
        KEPT_PRIVATE.format(count),
    )
    assert sorted(path.name for path in published.iterdir()) == sorted(SHARED)
    assert (published / RESULTS).read_bytes() == (folder / RESULTS).read_bytes()


# A --publish value that names no folder, or names the run folder or a folder inside it, is
# refused before any file is read or written: the shared copies would land among the run's own
# private files, and the removal that keeps a published folder to one run's files would remove
# the run's own sidecar.
NO_FOLDER = "nothing written: --publish names no folder; give the folder to publish into\n"
NAMELESS = (
    "nothing written: --publish {} names no folder by its last part; give the folder to "
    "publish into by its name\n"
)
INTO_THE_RUN = (
    "nothing written: --publish names the run folder {}; publish into a folder outside it\n"
)
INSIDE_THE_RUN = (
    "nothing written: --publish names {} inside the run folder {}; publish into a folder "
    "outside it\n"
)


def files_under(top: Path) -> dict[str, tuple[bytes, int, int, int]]:
    """Each file and folder under ``top``: its bytes, mode, inode and change time."""
    found: dict[str, tuple[bytes, int, int, int]] = {}
    for path in sorted(top.rglob("*")):
        state = path.lstat()
        held = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        found[path.relative_to(top).as_posix()] = (
            held,
            state.st_mode,
            state.st_ino,
            state.st_mtime_ns,
        )
    return found


def private_run_with_its_sidecar(writer: ModuleType, folder: Path) -> Path:
    """A run folder whose private sidecar an earlier write left, beside a report page."""
    printed, typed, count = PRIVATE_ROWS["a-64-hex-secret"]
    with_report(showcase_run(folder, typed, printed))
    assert run_writer(writer, folder) == (EXIT_OK, "", PRIVATE.format(count))
    return folder


@pytest.mark.parametrize(
    ("spelled", "said"),
    [
        ("", NO_FOLDER),
        (".", NAMELESS.format(".")),
        ("./", NAMELESS.format("./")),
        ("./.", NAMELESS.format("./.")),
    ],
    ids=["empty", "dot", "dot-slash", "dot-slash-dot"],
)
def test_publish_mode_refuses_a_value_that_names_no_folder_and_writes_nothing(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spelled: str,
    said: str,
) -> None:
    private_run_with_its_sidecar(writer, tmp_path / "run")
    monkeypatch.chdir(tmp_path)
    before = files_under(tmp_path)

    assert run_writer(writer, "run", "--publish", spelled) == (EXIT_USAGE, "", said)
    assert files_under(tmp_path) == before


@pytest.mark.parametrize(
    ("at", "run", "spelled", "named"),
    [
        (".", "run", "run", "run"),
        (".", "run", "run/", "run"),
        (".", "run", "run/.", "run"),
        (".", "run", "link-to-run", "run"),
        (".", "link-to-run", "run", "link-to-run"),
        ("run", ".", "../run", "run"),
        ("run", ".", "../link-to-run", "run"),
        (".", "run", "run/inside/..", "run"),
        (".", "run", "link-to-inside/..", "run"),
    ],
    ids=[
        "by-its-name",
        "with-a-slash",
        "with-a-dot",
        "through-a-link",
        "named-through-a-link",
        "from-inside-it",
        "from-inside-it-through-a-link",
        "climbing-back-to-it",
        "climbing-out-of-a-link-into-it",
    ],
)
def test_publish_mode_refuses_the_run_folder_itself_and_keeps_its_private_sidecar(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    at: str,
    run: str,
    spelled: str,
    named: str,
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / "run")
    (tmp_path / "link-to-run").symlink_to(folder, target_is_directory=True)
    (folder / "inside").mkdir()
    (tmp_path / "link-to-inside").symlink_to(folder / "inside", target_is_directory=True)
    monkeypatch.chdir(tmp_path / at)
    before = files_under(tmp_path)

    assert run_writer(writer, run, "--publish", spelled) == (
        EXIT_USAGE,
        "",
        INTO_THE_RUN.format(named),
    )
    assert files_under(tmp_path) == before
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE


@pytest.mark.parametrize(
    ("spelled", "named"),
    [
        ("run/inside", "inside"),
        ("run/a/b", "b"),
        ("run/./inside", "inside"),
        ("link-to-run/inside", "inside"),
        ("published/../run/inside", "inside"),
        ("run/a/b/..", "a"),
        ("link-to-b/..", "a"),
    ],
    ids=[
        "one-down",
        "two-down",
        "with-a-dot",
        "through-a-link",
        "climbing-into-it",
        "climbing-back-up-in-it",
        "climbing-out-of-a-link-in-it",
    ],
)
def test_publish_mode_refuses_a_folder_inside_the_run_folder_and_writes_nothing(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spelled: str,
    named: str,
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / "run")
    (folder / "inside").mkdir()
    (folder / "a" / "b").mkdir(parents=True)
    (tmp_path / "link-to-run").symlink_to(folder, target_is_directory=True)
    (tmp_path / "link-to-b").symlink_to(folder / "a" / "b", target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    before = files_under(tmp_path)

    assert run_writer(writer, "run", "--publish", spelled) == (
        EXIT_USAGE,
        "",
        INSIDE_THE_RUN.format(named, "run"),
    )
    assert files_under(tmp_path) == before


# A direct call of the publish refuses the run folder and a folder inside it as well.
NOT_INTO_THE_RUN = "the folder {} is the run folder or a folder inside it"


@pytest.mark.parametrize(("into", "named"), [("run", "run"), ("run/inside", "inside")])
def test_publish_refuses_to_copy_into_the_run_folder_or_a_folder_inside_it(
    writer: ModuleType, tmp_path: Path, into: str, named: str
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / "run")
    before = files_under(tmp_path)

    with pytest.raises(ValueError) as caught:
        writer.publish(folder, tmp_path / into, sidecar=False)

    assert str(caught.value) == NOT_INTO_THE_RUN.format(named)
    assert files_under(tmp_path) == before


# A --publish value that names a folder holding the run folder, at any depth, is refused before
# any file is read or written as well: the run's own capture and sidecar would lie inside the
# published folder.
HOLDS_THE_RUN = (
    "nothing written: --publish names {}, which holds the run folder {} and so its private "
    "files; publish into a folder that does not hold the run folder\n"
)


@pytest.mark.parametrize(
    ("made", "run", "spelled", "named"),
    [
        ("holder/run", "holder/run", "holder", "holder"),
        ("holder/run", "holder/run", "holder/", "holder"),
        ("holder/run", "holder/run", "./holder/.", "holder"),
        ("T/a/b/run", "T/a/b/run", "T", "T"),
        ("T/a/b/run", "T/a/b/run", "T/a", "a"),
        ("holder/run", "holder/run", "link-to-top", "holder"),
        ("T/a/b/run", "T/a/b/run", "link-to-top/a", "a"),
        ("holder/run", "holder/run", "holder/run/..", "holder"),
        ("holder/run", "holder/run", "elsewhere/../holder", "holder"),
        ("holder/run", "holder/run", "holder/run/inside/../..", "holder"),
        ("holder/run", "link-to-top/run", "holder", "holder"),
        ("holder/run", "near/run-link", "near", "near"),
        ("holder/run", "near/run-link", "holder", "holder"),
        ("holder/run", "holder/run", "absent/../holder", "holder"),
        ("holder/run", "holder/run", "holder/absent/..", "holder"),
        ("T/a/b/run", "T/a/b/run", "T/absent/x/../..", "T"),
    ],
    ids=[
        "one-level-up",
        "one-level-up-with-a-slash",
        "one-level-up-with-dots",
        "two-levels-up",
        "one-of-two-levels-up",
        "through-a-link",
        "through-a-link-two-levels-up",
        "climbing-out-of-the-run-folder",
        "climbing-through-another-folder",
        "climbing-out-of-a-folder-inside-it",
        "the-run-named-through-a-link",
        "a-folder-that-holds-a-link-to-the-run-folder",
        "the-folder-the-link-to-the-run-folder-leads-into",
        "climbing-out-of-a-folder-that-does-not-exist",
        "climbing-out-of-a-folder-in-it-that-does-not-exist",
        "climbing-out-of-two-folders-that-do-not-exist",
    ],
)
def test_publish_mode_refuses_a_folder_that_holds_the_run_folder_and_writes_nothing(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    made: str,
    run: str,
    spelled: str,
    named: str,
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / made)
    (folder / "inside").mkdir()
    (tmp_path / "elsewhere").mkdir()
    top = tmp_path / made.split("/")[0]
    (tmp_path / "link-to-top").symlink_to(top, target_is_directory=True)
    (tmp_path / "near").mkdir()
    (tmp_path / "near" / "run-link").symlink_to(folder, target_is_directory=True)
    monkeypatch.chdir(tmp_path)
    before = files_under(tmp_path)

    assert run_writer(writer, run, "--publish", spelled) == (
        EXIT_USAGE,
        "",
        HOLDS_THE_RUN.format(named, Path(run).name),
    )
    assert files_under(tmp_path) == before
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE


@pytest.mark.parametrize(
    "spelled",
    ["../work", "absent/..", "absent/x/../..", "runs/absent/../.."],
    ids=[
        "out-and-back-in",
        "out-of-a-folder-that-does-not-exist",
        "out-of-two-folders-that-do-not-exist",
        "out-of-the-runs-and-a-folder-that-does-not-exist",
    ],
)
def test_publish_mode_refuses_the_working_folder_named_by_a_path_that_climbs_back_to_it(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelled: str
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / "work" / "runs" / "run")
    monkeypatch.chdir(tmp_path / "work")
    before = files_under(tmp_path)

    assert run_writer(writer, "runs/run", "--publish", spelled) == (
        EXIT_USAGE,
        "",
        HOLDS_THE_RUN.format("work", "run"),
    )
    assert files_under(tmp_path) == before
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE


# A direct call of the publish refuses a folder that holds the run folder as well.
HOLDS_THE_RUN_FOLDER = "the folder {} holds the run folder"


@pytest.mark.parametrize(
    ("into", "named"),
    [
        ("T/holder", "holder"),
        ("T", "T"),
        ("T/absent/..", "T"),
        ("T/holder/absent/x/../..", "holder"),
    ],
    ids=[
        "one-level-up",
        "two-levels-up",
        "climbing-out-of-a-folder-that-does-not-exist",
        "climbing-out-of-two-folders-that-do-not-exist",
    ],
)
def test_publish_refuses_to_copy_into_a_folder_that_holds_the_run_folder(
    writer: ModuleType, tmp_path: Path, into: str, named: str
) -> None:
    folder = private_run_with_its_sidecar(writer, tmp_path / "T" / "holder" / "run")
    before = files_under(tmp_path)

    with pytest.raises(ValueError) as caught:
        writer.publish(folder, tmp_path / into, sidecar=False)

    assert str(caught.value) == HOLDS_THE_RUN_FOLDER.format(named)
    assert files_under(tmp_path) == before


@pytest.mark.parametrize(
    ("run", "spelled", "published"),
    [
        ("run", "run/../published", "published"),
        ("holder/run", "holder/published", "published"),
        ("holder/run", "other/published", "published"),
        ("holder/run", "holder/run2", "run2"),
        ("holder/run2", "holder/run", "run"),
        ("holder/run", "holder/ru", "ru"),
        ("holder/run", "link-to-holder/published", "published"),
    ],
    ids=[
        "named-through-the-run-folder",
        "a-folder-beside-it",
        "a-folder-in-another-parent",
        "a-name-that-starts-with-the-run-folder-name",
        "a-name-the-run-folder-name-starts-with",
        "a-name-that-is-the-start-of-the-run-folder-name",
        "a-folder-beside-it-through-a-link",
    ],
)
def test_publish_mode_into_a_folder_outside_the_run_folder_publishes_the_shared_files(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run: str,
    spelled: str,
    published: str,
) -> None:
    count = PRIVATE_ROWS["a-64-hex-secret"][2]
    folder = private_run_with_its_sidecar(writer, tmp_path / run)
    sidecar = (folder / SIDECAR).read_bytes()
    (tmp_path / "link-to-holder").symlink_to(tmp_path / "holder", target_is_directory=True)
    monkeypatch.chdir(tmp_path)

    assert run_writer(writer, run, "--publish", spelled) == (
        EXIT_OK,
        PUBLISHED_WITHOUT_SIDECAR.format(published),
        KEPT_PRIVATE.format(count),
    )
    for name in SHARED:
        assert (tmp_path / spelled / name).read_bytes() == (folder / name).read_bytes()
    assert not (tmp_path / spelled / SIDECAR).exists()
    assert (folder / SIDECAR).read_bytes() == sidecar
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE


def test_a_run_folder_named_by_a_dot_is_named_by_its_name_when_it_is_refused(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")

    assert run_writer(writer, ".") == (
        EXIT_USAGE,
        "",
        "the folder empty has no results.json, capture.jsonl\n",
    )


# The process-space mark in a write's file name is all zeros when either of its two parts, the
# boot or the process-number namespace, cannot be read; and the publish refuses a folder that
# is no place to publish into.
SPACE_MARK = "all zeros where either cannot be read"
PUBLISH_REFUSED = (
    "`--publish` refuses, with exit 2 and before it reads or writes any file, a `FOLDER` that "
    "is empty, whose last part names no folder, such as `.`, or that is the run folder or a "
    "folder inside it, through a link or not."
)


def test_the_script_says_what_its_process_space_mark_and_its_publish_refuse(
    writer: ModuleType, repo_root: Path
) -> None:
    said = " ".join((writer.__doc__ or "").replace("``", "`").split())
    policy = " ".join((repo_root / "SECURITY.md").read_text(encoding="utf-8").split())

    assert SPACE_MARK in said
    assert "where neither can be read" not in said
    assert PUBLISH_REFUSED in said
    assert PUBLISH_REFUSED in policy


# The sentence of the script that says a folder holding the run folder is refused as well.
PUBLISH_REFUSES_A_HOLDER = (
    "It refuses the same way a `FOLDER` that holds the run folder, at any depth, through a link "
    "or not, since the run's own private files would then lie inside the published folder."
)


def test_the_script_says_it_refuses_a_folder_that_holds_the_run_folder(writer: ModuleType) -> None:
    said = " ".join((writer.__doc__ or "").replace("``", "`").split())

    assert PUBLISH_REFUSES_A_HOLDER in said


# The policy says what the script and the results schema page say of a publish: a folder that
# holds the run folder is refused, and every file is checked before the first copy.
PUBLISH_CHECKS_FIRST = (
    "It checks every file before it copies any: a publish that fails before its first copy "
    'leaves `FOLDER` as it was and says "nothing published", and one that fails after it says '
    '"partly published" and names exactly the files it copied, both with exit 2.'
)


def test_the_policy_says_a_publish_refuses_a_holder_and_checks_every_file_first(
    repo_root: Path,
) -> None:
    policy = " ".join((repo_root / "SECURITY.md").read_text(encoding="utf-8").split())
    schema = " ".join(
        (repo_root / "docs/reference/results-schema.md").read_text(encoding="utf-8").split()
    )

    assert PUBLISH_REFUSES_A_HOLDER in policy
    assert PUBLISH_CHECKS_FIRST in policy
    assert PUBLISH_CHECKS_FIRST.removeprefix("It ") in schema


@pytest.mark.parametrize(
    "workdir",
    [
        "/work/.",
        "/home/user",
        "/home/user/",
        "/work/published",
        "/work/./published",
        "/home/user/published/.",
        "/home/user/published/../published",
    ],
)
def test_a_neutral_place_or_a_path_under_one_whose_parts_are_shown_can_be_shared(
    writer: ModuleType, tmp_path: Path, workdir: str
) -> None:
    # `published` is shown: the results show `--out published`.
    typed = _with_setting(WORKDIR, f"launch.workdir={workdir}")

    assert run_writer(writer, showcase_run(tmp_path / "run", typed)) == (EXIT_OK, SHAREABLE, "")


def test_an_image_reference_the_results_show_can_be_shared(
    writer: ModuleType, tmp_path: Path
) -> None:
    typed = _with_setting("a=image:python:3.12-slim", "a=image:registry.made-up.internal:5000/b:1")

    assert run_writer(writer, showcase_run(tmp_path / "run", typed)) == (EXIT_OK, SHAREABLE, "")


def test_a_value_given_with_set_passes_when_a_shared_file_shows_it_in_another_place(
    writer: ModuleType, tmp_path: Path
) -> None:
    # The shown command hides the memory cap, but the workload's command shows the word `8g`.
    typed = (*SHOWCASE[:-4], "--set", "launch.memory=8g", "--", "python", "-c", "pass", "8g")
    folder = showcase_run(tmp_path / "run", typed)

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    markdown = (folder / "results.md").read_text(encoding="utf-8")
    passed = writer.passing(read(folder / RESULTS), markdown, read(folder / SIDECAR))
    assert "8g" in passed["Shown values"]


# One value of each kind that may pass, and the kind each passes as. The side's name and the
# workload word are shown by the results, `/work` is a neutral place, the keys are those the
# sidecar and the config schema are written with, `podman` is listed by the config schema and
# `missing` is the default, and the rest are null, true or empty: an empty text, list or table.
KIND_SIDECAR = {
    "schema": SCHEMA,
    "sides": {
        "a": {
            "argv_sha256": ["made-up-word", "/work", ""],
            "fingerprint": {
                "identity": {"prefix": None},
                "launch": {"perf_counters": True, "mounts": [], "env": {}},
            },
        }
    },
    "provenance": {"config_sha256": [{"launch": {"engine": "podman", "pull": "missing"}}]},
}
KIND_RESULTS = {"run": {"command": "pairbench run -- made-up-word"}, "sides": [{"name": "a"}]}
PASSING = {
    "Shown values": ["a", "made-up-word"],
    "Neutral places": ["/work"],
    "Schema ids and keys": [
        "argv_sha256",
        "config_sha256",
        "engine",
        "env",
        "fingerprint",
        "identity",
        "launch",
        "mounts",
        SCHEMA,
        "perf_counters",
        "prefix",
        "provenance",
        "pull",
        "sides",
    ],
    "Config-schema values and config defaults": ["missing", "podman"],
    "Null, true, false and empty values": ['""', "[]", "null", "true", "{}"],
}


def test_each_kind_of_value_that_may_pass_lets_its_value_pass(writer: ModuleType) -> None:
    assert writer.passing(KIND_RESULTS, "", KIND_SIDECAR) == PASSING
    assert writer.hidden_values(KIND_RESULTS, "", KIND_SIDECAR) == []
    assert tuple(PASSING) == writer.PASSING_KINDS


def test_a_value_whose_kind_does_not_apply_is_hidden(writer: ModuleType) -> None:
    sidecar = copy.deepcopy(KIND_SIDECAR)
    sidecar["sides"]["a"]["argv_sha256"] = ["made-up-word", "/srv/made-up", "made-up-key"]
    sidecar["provenance"]["config_sha256"][0]["made-up-key"] = "podman"

    assert writer.hidden_values({"sides": [{"name": "a"}]}, "", sidecar) == [
        "/srv/made-up",
        "made-up-key",
        "made-up-word",
        "podman",
    ]


# A text that is no neutral place, nor a path under one, though the results show each of its
# other parts: a path whose dots leave /work, two values joined by a colon, a path written with
# three slashes first, and a folder whose name only starts like a neutral place.
NOT_A_PLACE = {
    "left-by-its-dots": ("/work/../srv/zqmadeup", "srv zqmadeup"),
    "two-values-joined-by-a-colon": ("/work/zqa:/srv/zqmadeup", "zqa: srv zqmadeup"),
    "three-slashes-first": ("///work/zqmadeup", "zqmadeup"),
    "a-folder-beside-work": ("/workspace/zqmadeup", "workspace zqmadeup"),
    "a-folder-beside-the-neutral-home": ("/home/username/zqmadeup", "home username zqmadeup"),
}


@pytest.mark.parametrize(("value", "shown"), list(NOT_A_PLACE.values()), ids=list(NOT_A_PLACE))
def test_a_path_that_is_no_neutral_place_is_hidden_though_its_parts_are_shown(
    writer: ModuleType, value: str, shown: str
) -> None:
    results = {"run": {"command": f"pairbench run -- {shown}"}, "sides": [{"name": "a"}]}
    sidecar = {"schema": SCHEMA, "sides": {"a": {"argv_sha256": [value]}}}

    assert writer.hidden_values(results, "", sidecar) == [value]
    assert writer.neutral_place(value, set(shown.split())) is False


def test_a_key_of_the_results_and_each_of_its_words_are_shown(writer: ModuleType) -> None:
    results = {"sides": [{"name": "a"}], "made-up-key made-up-word": None}
    sidecar = {
        "schema": SCHEMA,
        "sides": {"a": {"argv_sha256": ["made-up-key made-up-word", "made-up-word", "zqhidden"]}},
    }

    assert writer.hidden_values(results, "", sidecar) == ["zqhidden"]


@pytest.mark.parametrize(
    ("cases", "hidden"),
    [([{"id": "made-up-client run"}], []), ([{"id": "run"}], ["/work/made-up-client/run"])],
    ids=["a-case-shows-each-other-part", "the-results-show-the-last-part-only"],
)
def test_a_path_under_a_neutral_place_passes_once_the_results_show_its_other_parts(
    writer: ModuleType, cases: list[dict[str, str]], hidden: list[str]
) -> None:
    results = {"sides": [{"name": "a"}], "cases": cases}
    sidecar = {"schema": SCHEMA, "sides": {"a": {"argv_sha256": ["/work/made-up-client/run"]}}}

    assert writer.hidden_values(results, "", sidecar) == hidden


def test_a_shown_word_matches_only_as_written(writer: ModuleType) -> None:
    results = {"run": {"command": "pairbench run -- MADE-UP-WORD Made-Up-Word"}}
    sidecar = {"schema": SCHEMA, "sides": {"a": {"argv_sha256": ["made-up-word"]}}}

    assert writer.hidden_values(results, "", sidecar) == ["a", "made-up-word"]


# A key of a table the user names, spelt like a key the sidecar, an identity, a launch or the
# config schema is written with, and where it sits; each is a value, which the results hide.
USER_NAMED_KEYS = {
    "a-variable-of-the-launch": (
        {"provenance": {"config_sha256": [{"launch": {"env": {"memory": ""}}}]}},
        "memory",
    ),
    "a-variable-of-a-side": (
        {"provenance": {"config_sha256": [{"sides": {"a": {"env": {"engine": ""}}}}]}},
        "engine",
    ),
    "a-variable-of-a-server": (
        {"provenance": {"config_sha256": [{"sides": {"a": {"serve": {"env": {"args": ""}}}}}]}},
        "args",
    ),
    "a-side-of-the-config": (
        {"provenance": {"config_sha256": [{"sides": {"launch": {}}}]}},
        "launch",
    ),
    "a-group-of-cases": (
        {"provenance": {"config_sha256": [{"cases": {"groups": {"pull": []}}}]}},
        "pull",
    ),
    "a-variable-of-a-fingerprint": (
        {"sides": {"a": {"fingerprint": {"launch": {"env": {"platform": ""}}}}}},
        "platform",
    ),
    "a-variable-an-environment-sets": (
        {"sides": {"a": {"fingerprint": {"identity": {"selection_env": {"set": {"prefix": ""}}}}}}},
        "prefix",
    ),
    "a-side-of-the-sidecar": ({"sides": {"identity": {}}}, "identity"),
    "a-table-no-schema-names": (
        {"sides": {"a": {"fingerprint": {"identity": {"digests": {"mounts": ""}}}}}},
        "mounts",
    ),
}


@pytest.mark.parametrize(
    ("sidecar", "key"), list(USER_NAMED_KEYS.values()), ids=list(USER_NAMED_KEYS)
)
def test_a_key_of_a_table_the_user_names_is_a_value(
    writer: ModuleType, sidecar: dict[str, Any], key: str
) -> None:
    assert writer.hidden_values({"sides": [{"name": "a"}]}, "", sidecar) == [key]


# A value the config schema lists for one key, under a key of that name the user named; the
# results show the key, so only the value is left to pass.
LISTED_ELSEWHERE = {
    "a-variable-of-the-launch": (
        {"provenance": {"config_sha256": [{"launch": {"env": {"call_graph": "dwarf"}}}]}},
        "call_graph",
        "dwarf",
    ),
    "a-variable-of-a-side": (
        {"provenance": {"config_sha256": [{"sides": {"a": {"env": {"pull": "always"}}}}]}},
        "pull",
        "always",
    ),
    "a-variable-of-a-fingerprint": (
        {"sides": {"a": {"fingerprint": {"launch": {"env": {"engine": "podman"}}}}}},
        "engine",
        "podman",
    ),
}


@pytest.mark.parametrize(
    ("sidecar", "key", "value"), list(LISTED_ELSEWHERE.values()), ids=list(LISTED_ELSEWHERE)
)
def test_a_listed_value_passes_only_under_its_own_key(
    writer: ModuleType, sidecar: dict[str, Any], key: str, value: str
) -> None:
    results = {"run": {"command": f"pairbench run -- {key}"}, "sides": [{"name": "a"}]}

    assert writer.hidden_values(results, "", sidecar) == [value]


# A value the config schema lists for its own key, at its own place: under the key, and as an
# item of a list under it; none of them is the tool's default.
LISTED_AT_ITS_PLACE = {
    "under-its-key": ({"explain": {"call_graph": "dwarf"}}, ["dwarf"]),
    "under-a-side-s-launch": ({"sides": {"a": {"launch": {"pull": "always"}}}}, ["always"]),
    "items-of-a-list": ({"rule": {"fail_on": ["better", "unresolved"]}}, ["better", "unresolved"]),
}


@pytest.mark.parametrize(
    ("config", "listed"), list(LISTED_AT_ITS_PLACE.values()), ids=list(LISTED_AT_ITS_PLACE)
)
def test_a_listed_value_at_its_own_place_passes(
    writer: ModuleType, config: dict[str, Any], listed: list[str]
) -> None:
    sidecar = {"provenance": {"config_sha256": [config]}}

    assert writer.hidden_values({"sides": [{"name": "a"}]}, "", sidecar) == []
    passed = writer.passing({"sides": [{"name": "a"}]}, "", sidecar)
    assert passed["Config-schema values and config defaults"] == listed


# The name of the file a write of the sidecar fills before it moves it over the sidecar: the
# number of the process that writes it, the mark of the process space it runs in and a random
# part.
TEMPORARY = re.compile(r"\.hash_inputs\.json\.([0-9]+)\.([0-9a-f]{12})\.([0-9a-f]{16})\.tmp")
# The age past which a later run removes such a file whatever its number says, and a short
# stand-in for it.
STRAY_SECONDS = 3600
SHORT_AGE = 0.2
# A random part, made up, and the mark of a process space that is not this one.
MADE_UP_PART = "5eed5eed5eed5eed"
OTHER_SPACE = "0123456789ab"
# What a writer whose own file was removed before it was moved into place says.
TEMPORARY_GONE = (
    "no hash_inputs.json written: the file this run filled for hash_inputs.json was removed "
    "before it was moved into place; nothing else was changed\n"
)
# Runs the writer and kills it with SIGKILL when it would move its whole file over the sidecar.
KILLED_WRITER = """
import importlib.util, os, signal, sys
spec = importlib.util.spec_from_file_location("hash_inputs", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
os.umask(0o002)
def killed(*args, **kwargs):
    os.kill(os.getpid(), signal.SIGKILL)
tool.os.replace = killed
tool.main([sys.argv[2]])
"""
# Runs the writer and holds it when it would move its whole file over the sidecar: it writes
# `ready` into the control folder, and goes on once `go` is there.
PAUSED_WRITER = """
import importlib.util, os, sys, time
spec = importlib.util.spec_from_file_location("hash_inputs", sys.argv[1])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
control = sys.argv[3]
replace = os.replace
def paused(source, target):
    open(os.path.join(control, "ready"), "w").close()
    while not os.path.exists(os.path.join(control, "go")):
        time.sleep(0.05)
    replace(source, target)
tool.os.replace = paused
raise SystemExit(tool.main([sys.argv[2]]))
"""
SHARED_MODE = 0o664


def space_mark() -> str:
    """The mark of the process space this process runs in: the boot and its process numbers."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        inode = os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        return "0" * 12
    return hashlib.sha256(f"{boot}:{inode}".encode()).hexdigest()[:12]


def temporary_names(folder: Path) -> list[str]:
    """The names of the files in ``folder`` that a write of the sidecar fills."""
    return sorted(path.name for path in folder.iterdir() if TEMPORARY.fullmatch(path.name))


def wait_for(found: Any, what: str, timeout: float = 300.0) -> None:
    """Wait until ``found()`` is true, or fail the test after ``timeout`` seconds."""
    end = time.monotonic() + timeout
    while not found():
        if time.monotonic() > end:
            pytest.fail(f"gave up waiting for {what}")
        time.sleep(0.02)


def test_a_sidecar_that_can_be_shared_is_owner_only_until_it_is_whole(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = showcase_run(tmp_path / "run")
    seen: list[tuple[str, int]] = []
    rename = os.replace

    def watched(source: Any, target: Any) -> None:
        seen.append((Path(source).name, mode_of(Path(source))))
        rename(source, target)

    monkeypatch.setattr(writer.os, "replace", watched)
    monkeypatch.setattr(writer, "_token", lambda: MADE_UP_PART)
    mask = os.umask(0o002)
    try:
        result = run_writer(writer, folder)
    finally:
        os.umask(mask)

    assert result == (EXIT_OK, SHAREABLE, "")
    assert seen == [(f".{SIDECAR}.{os.getpid()}.{space_mark()}.{MADE_UP_PART}.tmp", PRIVATE_MODE)]
    assert mode_of(folder / SIDECAR) == SHARED_MODE


def test_two_writes_by_one_process_fill_files_of_different_names(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = showcase_run(tmp_path / "run")
    seen: list[str] = []
    rename = os.replace

    def watched(source: Any, target: Any) -> None:
        seen.append(Path(source).name)
        rename(source, target)

    monkeypatch.setattr(writer.os, "replace", watched)

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    found = [TEMPORARY.fullmatch(name) for name in seen]
    assert [(m.group(1), m.group(2)) if m else None for m in found] == [
        (str(os.getpid()), space_mark()),
        (str(os.getpid()), space_mark()),
    ]
    assert len(set(seen)) == len(seen)


def test_a_writer_killed_before_its_file_is_whole_leaves_it_owner_only_and_a_later_run_removes_it(
    writer: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    environ = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    script = repo_root / "tools" / "hash_inputs.py"

    killed = subprocess.run(
        [sys.executable, "-c", KILLED_WRITER, str(script), str(folder)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=environ,
    )
    left = [path for path in folder.iterdir() if TEMPORARY.fullmatch(path.name)]
    modes = [mode_of(path) for path in left]
    later = run_writer(writer, folder)

    assert killed.returncode == -signal.SIGKILL, killed.stderr
    assert [killed_space(left)] == [space_mark()]
    assert killed_pid(left) not in ("none", str(os.getpid()))
    assert modes == [PRIVATE_MODE]
    assert later == (EXIT_OK, SHAREABLE, "")
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]


def killed_pid(left: list[Path]) -> str:
    """The process number in the name of the one file a killed writer left."""
    found = TEMPORARY.fullmatch(left[0].name) if len(left) == 1 else None
    return found.group(1) if found else "none"


def killed_space(left: list[Path]) -> str:
    """The mark of the process space in the name of the one file a killed writer left."""
    found = TEMPORARY.fullmatch(left[0].name) if len(left) == 1 else None
    return found.group(2) if found else "none"


def test_a_refused_run_removes_the_file_a_killed_writer_left(
    writer: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    environ = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    script = repo_root / "tools" / "hash_inputs.py"
    subprocess.run(
        [sys.executable, "-c", KILLED_WRITER, str(script), str(folder)],
        capture_output=True,
        check=False,
        timeout=300,
        env=environ,
    )
    (folder / "capture.jsonl").unlink()

    assert run_writer(writer, folder) == (
        EXIT_USAGE,
        "",
        "the folder run has no capture.jsonl\n",
    )
    assert sorted(path.name for path in folder.iterdir()) == ["results.json", "results.md"]


def ended_pid() -> int:
    """The number of a process that has ended."""
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait(timeout=60)
    return done.pid


def test_publish_mode_removes_the_files_a_killed_write_left_in_the_folder_it_fills(
    writer: ModuleType, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    published = tmp_path / "showcase" / "published"
    published.mkdir(parents=True)
    pid = ended_pid()
    # One beside a file the run wrote, which is copied, and one beside a file it did not write,
    # which is removed from the folder; both left in this process space by an ended writer.
    for name in (
        f".results.json.{pid}.{space_mark()}.{MADE_UP_PART}.tmp",
        f".report.html.{pid}.{space_mark()}.{MADE_UP_PART}.tmp",
        "report.html",
    ):
        (published / name).write_text("made-up\n", encoding="utf-8")

    assert run_writer(writer, folder, "--publish", published) == (
        EXIT_OK,
        PUBLISHED.format("published"),
        "",
    )
    assert sorted(path.name for path in published.iterdir()) == [
        SIDECAR,
        "results.json",
        "results.md",
    ]


# Files a later run keeps while they are younger than the age: a writer of this process space
# that still runs, any file of another process space or of no known one (its number tells
# nothing here), and files of other names.
KEPT_WHILE_YOUNG = {
    "a-writer-still-running-in-this-space": "{this}",
    "an-ended-writer-of-another-space": "{other}",
    "this-process-number-in-another-space": "{own_other}",
    "a-number-only-of-an-ended-writer": "{number_only}",
    "a-number-only-of-a-running-writer": f".{SIDECAR}.1.tmp",
    "no-number": f".{SIDECAR}.made-up.tmp",
    "a-longer-name": f".{SIDECAR}.4194305.{OTHER_SPACE}.{MADE_UP_PART}.tmp.made-up",
    "another-file": f".results.json.4194305.{OTHER_SPACE}.{MADE_UP_PART}.tmp",
    "no-dot": f"{SIDECAR}.4194305.{OTHER_SPACE}.{MADE_UP_PART}.tmp",
    "a-short-random-part": f".{SIDECAR}.1.{OTHER_SPACE}.5eed.tmp",
    "a-long-random-part": f".{SIDECAR}.1.{OTHER_SPACE}.{MADE_UP_PART}5.tmp",
    "an-upper-case-mark": f".{SIDECAR}.1.{OTHER_SPACE.upper()}.{MADE_UP_PART}.tmp",
    "a-short-mark": f".{SIDECAR}.1.{OTHER_SPACE[:4]}.{MADE_UP_PART}.tmp",
    "an-empty-number": f".{SIDECAR}..tmp",
}
# The names of ``KEPT_WHILE_YOUNG`` that are not of the forms a write gives: a later run never
# looks at them, so it keeps them whatever their age.
OTHER_NAMES = (
    "no-number",
    "a-longer-name",
    "another-file",
    "no-dot",
    "a-short-random-part",
    "a-long-random-part",
    "an-upper-case-mark",
    "a-short-mark",
    "an-empty-number",
)


def kept_name(form: str) -> str:
    """A name of ``KEPT_WHILE_YOUNG`` with the process numbers and marks of this machine."""
    return form.format(
        this=f".{SIDECAR}.1.{space_mark()}.{MADE_UP_PART}.tmp",
        other=f".{SIDECAR}.{ended_pid()}.{OTHER_SPACE}.{MADE_UP_PART}.tmp",
        own_other=f".{SIDECAR}.{os.getpid()}.{OTHER_SPACE}.{MADE_UP_PART}.tmp",
        number_only=f".{SIDECAR}.{ended_pid()}.tmp",
    )


@pytest.mark.parametrize("form", list(KEPT_WHILE_YOUNG.values()), ids=list(KEPT_WHILE_YOUNG))
def test_a_later_run_keeps_a_young_file_it_cannot_tell_is_stray_and_files_of_other_names(
    writer: ModuleType, tmp_path: Path, form: str
) -> None:
    folder = showcase_run(tmp_path / "run")
    name = kept_name(form)
    (folder / name).write_text("made-up\n", encoding="utf-8")

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert (folder / name).read_text(encoding="utf-8") == "made-up\n"


@pytest.mark.parametrize("which", OTHER_NAMES)
def test_a_later_run_keeps_a_file_of_another_name_whatever_its_age(
    writer: ModuleType, tmp_path: Path, which: str
) -> None:
    folder = showcase_run(tmp_path / "run")
    left = folder / KEPT_WHILE_YOUNG[which]
    left.write_text("made-up\n", encoding="utf-8")
    old = time.time() - STRAY_SECONDS - 60
    os.utime(left, (old, old))

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert left.read_text(encoding="utf-8") == "made-up\n"


# Files a later run removes once they are older than the age, whatever their number says.
STRAY_WHEN_OLD = (
    "a-writer-still-running-in-this-space",
    "an-ended-writer-of-another-space",
    "this-process-number-in-another-space",
    "a-number-only-of-an-ended-writer",
    "a-number-only-of-a-running-writer",
)


@pytest.mark.parametrize("which", STRAY_WHEN_OLD)
def test_a_later_run_removes_a_file_older_than_the_age_whatever_its_number(
    writer: ModuleType, tmp_path: Path, which: str
) -> None:
    folder = showcase_run(tmp_path / "run")
    left = folder / kept_name(KEPT_WHILE_YOUNG[which])
    left.write_text("made-up\n", encoding="utf-8")
    old = time.time() - STRAY_SECONDS - 60
    os.utime(left, (old, old))

    assert writer.STRAY_SECONDS == STRAY_SECONDS
    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]


def test_a_later_run_removes_a_file_left_in_this_space_under_its_own_process_number(
    writer: ModuleType, tmp_path: Path
) -> None:
    # A process of this number that runs in this space is this one, which has not started its
    # own write when it looks: the file was left by an ended writer that had the same number.
    folder = showcase_run(tmp_path / "run")
    name = f".{SIDECAR}.{os.getpid()}.{space_mark()}.{MADE_UP_PART}.tmp"
    (folder / name).write_text("made-up\n", encoding="utf-8")

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]


def test_where_the_process_space_cannot_be_read_a_young_file_is_kept_whatever_its_number(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = showcase_run(tmp_path / "run")
    name = f".{SIDECAR}.{ended_pid()}.{'0' * 12}.{MADE_UP_PART}.tmp"
    (folder / name).write_text("made-up\n", encoding="utf-8")
    monkeypatch.setattr(writer, "_space", lambda: "0" * 12)

    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert (folder / name).read_text(encoding="utf-8") == "made-up\n"


def test_a_writer_held_past_the_age_loses_its_file_exits_2_and_changes_nothing_else(
    writer: ModuleType, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = showcase_run(tmp_path / "run")
    control = tmp_path / "control"
    control.mkdir()
    environ = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
    script = repo_root / "tools" / "hash_inputs.py"
    held = subprocess.Popen(
        [sys.executable, "-c", PAUSED_WRITER, str(script), str(folder), str(control)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environ,
    )
    try:
        wait_for(lambda: (control / "ready").exists(), "the held writer")
        (filled,) = (folder / name for name in temporary_names(folder))
        wait_for(lambda: time.time() - filled.stat().st_mtime > SHORT_AGE, "the short age")
        monkeypatch.setattr(writer, "STRAY_SECONDS", SHORT_AGE)

        later = run_writer(writer, folder)
        written = (folder / SIDECAR).read_bytes()
        mode = mode_of(folder / SIDECAR)
        left = temporary_names(folder)
    finally:
        (control / "go").touch()
        out, err = held.communicate(timeout=300)

    assert later == (EXIT_OK, SHAREABLE, "")
    assert left == []
    assert (held.returncode, out, err) == (EXIT_USAGE, "", TEMPORARY_GONE)
    assert (folder / SIDECAR).read_bytes() == written
    assert mode_of(folder / SIDECAR) == mode
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]


def test_a_write_whose_own_file_was_removed_exits_2_and_keeps_the_earlier_sidecar(
    pair: Path, writer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = (pair / SIDECAR).read_bytes()
    rename = os.replace

    def removed(source: Any, target: Any) -> None:
        Path(source).unlink()
        rename(source, target)

    monkeypatch.setattr(writer.os, "replace", removed)

    assert run_writer(writer, pair) == (EXIT_USAGE, "", TEMPORARY_GONE)
    assert (pair / SIDECAR).read_bytes() == earlier
    assert mode_of(pair / SIDECAR) == PRIVATE_MODE
    assert temporary_names(pair) == []


@pytest.mark.parametrize(
    "spelled", ["published", "absent/../published"], ids=["by-its-name", "climbing-out-of-another"]
)
def test_publish_mode_whose_own_file_was_removed_exits_2_with_a_plain_message(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelled: str
) -> None:
    folder = showcase_run(tmp_path / "run")
    published = tmp_path / spelled
    rename = os.replace

    def removed(source: Any, target: Any) -> None:
        if Path(target).parent.name == "published":
            Path(source).unlink()
        rename(source, target)

    monkeypatch.setattr(writer.os, "replace", removed)

    assert run_writer(writer, folder, "--publish", published) == (
        EXIT_USAGE,
        "",
        "nothing published: the file this run filled for results.json was removed before it "
        "was moved into place\n",
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run"]


# A publish checks every file it would write or remove before it copies any: a folder at the name
# of one of them in the published folder is refused, and the published folder is left as it was.
FOLDER_IN_THE_WAY = (
    "nothing published: {} in {} is a folder, which a publish neither replaces nor removes; "
    "remove it or publish into another folder\n"
)


@pytest.mark.parametrize(
    ("name", "report", "private"),
    [
        ("report.html", True, False),
        ("report.html", False, False),
        ("results.md", True, False),
        ("results.json", True, False),
        (SIDECAR, True, True),
        (SIDECAR, True, False),
    ],
    ids=[
        "the-report-page-the-run-wrote",
        "the-report-page-the-run-did-not-write",
        "the-markdown-results",
        "the-results",
        "the-sidecar-kept-private",
        "the-sidecar-to-be-copied",
    ],
)
def test_publish_into_a_folder_with_a_folder_at_a_published_name_copies_nothing(
    writer: ModuleType, tmp_path: Path, name: str, report: bool, private: bool
) -> None:
    if private:
        printed, typed, _count = PRIVATE_ROWS["a-64-hex-secret"]
        folder = showcase_run(tmp_path / "run", typed, printed)
    else:
        folder = showcase_run(tmp_path / "run")
    if report:
        with_report(folder)
    published = tmp_path / "published"
    (published / name).mkdir(parents=True)
    (published / name / "keep").write_text("made-up\n", encoding="utf-8")
    before = files_under(published)

    assert run_writer(writer, folder, "--publish", published) == (
        EXIT_USAGE,
        "",
        FOLDER_IN_THE_WAY.format(name, "published"),
    )
    assert files_under(published) == before
    assert mode_of(folder / SIDECAR) == (PRIVATE_MODE if private else default_mode())


def listing(folder: Path) -> dict[str, tuple[bytes, int, int, int]] | None:
    """``files_under`` of ``folder``, or ``None`` when there is no such folder."""
    return files_under(folder) if folder.exists() else None


# A file of the run that cannot be read is found before anything is copied.
@pytest.mark.skipif(
    os.geteuid() == 0, reason="needs a user that cannot read a file of mode 000; root reads it"
)
@pytest.mark.parametrize(
    "earlier", [False, True], ids=["a-new-folder", "a-folder-published-before"]
)
def test_publish_of_a_file_it_cannot_read_copies_nothing(
    writer: ModuleType, tmp_path: Path, earlier: bool
) -> None:
    published = tmp_path / "published"
    if earlier:
        first = run_writer(
            writer, with_report(showcase_run(tmp_path / "earlier")), "--publish", published
        )
        assert first[0] == EXIT_OK
    folder = with_report(showcase_run(tmp_path / "run"))
    (folder / "report.html").chmod(0)
    before = listing(published)

    try:
        result = run_writer(writer, folder, "--publish", published)
    finally:
        (folder / "report.html").chmod(0o600)

    assert result == (
        EXIT_USAGE,
        "",
        f"nothing published: [Errno 13] Permission denied: '{folder / 'report.html'}'\n",
    )
    assert listing(published) == before


# A move that fails after an earlier one landed: the line names exactly the files copied, those
# not copied, and those of an earlier publish still in the folder; no file a write filled is left.
FAILED_PART = "made-up full disk"


@pytest.mark.parametrize(
    ("earlier", "failing", "said"),
    [
        (
            False,
            "results.md",
            "partly published: copied results.json into published, then stopped: made-up full "
            "disk; not copied: results.md and report.html\n",
        ),
        (
            True,
            "report.html",
            "partly published: copied results.json and results.md into published, then stopped: "
            "made-up full disk; not copied: report.html; still there from before: report.html and "
            "hash_inputs.json\n",
        ),
    ],
    ids=["into-a-new-folder", "into-a-folder-published-before"],
)
def test_publish_whose_later_move_fails_says_exactly_what_it_copied(
    writer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    earlier: bool,
    failing: str,
    said: str,
) -> None:
    published = tmp_path / "published"
    if earlier:
        first = run_writer(
            writer, with_report(showcase_run(tmp_path / "earlier")), "--publish", published
        )
        assert first[0] == EXIT_OK
    printed, typed, _count = PRIVATE_ROWS["a-64-hex-secret"]
    folder = with_report(showcase_run(tmp_path / "run", typed, printed))
    before = listing(published) or {}
    rename = os.replace

    def failing_move(source: Any, target: Any) -> None:
        if Path(target) == published / failing:
            raise OSError(FAILED_PART)
        rename(source, target)

    monkeypatch.setattr(writer.os, "replace", failing_move)

    assert run_writer(writer, folder, "--publish", published) == (EXIT_USAGE, "", said)
    after = files_under(published)
    copied = SHARED[: SHARED.index(failing)]
    for name in copied:
        assert (published / name).read_bytes() == (folder / name).read_bytes()
        assert mode_of(published / name) == default_mode()
    assert sorted(after) == sorted({*copied, *before})
    for name in before:
        if name not in copied:
            assert after[name] == before[name]


# A removal of a file an earlier publish left that fails, once every file is copied, says so too.
def test_publish_whose_removal_of_an_earlier_file_fails_says_what_it_copied(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = tmp_path / "published"
    first = run_writer(
        writer, with_report(showcase_run(tmp_path / "earlier")), "--publish", published
    )
    assert first[0] == EXIT_OK
    printed, typed, _count = PRIVATE_ROWS["a-64-hex-secret"]
    folder = with_report(showcase_run(tmp_path / "run", typed, printed))
    before = files_under(published)
    remove = os.unlink

    def failing_removal(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path) == published / SIDECAR:
            raise OSError("made-up busy file")
        remove(path, *args, **kwargs)

    monkeypatch.setattr(writer.os, "unlink", failing_removal)

    assert run_writer(writer, folder, "--publish", published) == (
        EXIT_USAGE,
        "",
        "partly published: copied results.json, results.md and report.html into published, then "
        "stopped: made-up busy file; still there from before: hash_inputs.json\n",
    )
    after = files_under(published)
    assert sorted(after) == sorted([*SHARED, SIDECAR])
    for name in SHARED:
        assert (published / name).read_bytes() == (folder / name).read_bytes()
    assert after[SIDECAR] == before[SIDECAR]


# Stands in for `pairbench run` in a showcase publish: copies a prepared run into the folder
# named after --out.
COPYING_RUN = """#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = --out ]; then
    mkdir -p "$2" && cp -R "{prepared}/." "$2" && exit 0
    exit 1
  fi
  shift
done
exit 1
"""
# Stands in for python3: the interpreter that runs the tests.
THIS_PYTHON = """#!/bin/sh
exec "{python}" "$@"
"""


def test_a_showcase_publish_into_a_folder_with_a_folder_at_a_published_name_copies_nothing(
    writer: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    prepared = with_report(showcase_run(tmp_path / "prepared"))
    checkout = tmp_path / "checkout"
    showcase = checkout / "showcases" / "made-up"
    showcase.mkdir(parents=True)
    for part in ("src", "tools"):
        (checkout / part).symlink_to(repo_root / part, target_is_directory=True)
    blocked = showcase / "published" / "report.html"
    blocked.mkdir(parents=True)
    (blocked / "keep").write_text("made-up\n", encoding="utf-8")
    before = files_under(showcase / "published")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "pairbench").write_text(COPYING_RUN.format(prepared=prepared), encoding="utf-8")
    (stubs / "python3").write_text(THIS_PYTHON.format(python=sys.executable), encoding="utf-8")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ.get('PATH', '')}",
        "PAIRBENCH_SHOWCASE_PUBLISH": "published",
    }
    script = 'set -eu; here=/work/showcases/made-up; cd "$1"; . "$2"; run_pairbench "" --made-up'

    done = subprocess.run(
        ["sh", "-c", script, "sh", str(showcase), str(repo_root / "showcases" / "publish.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )

    assert (done.returncode, done.stdout, done.stderr) == (
        EXIT_USAGE,
        "",
        FOLDER_IN_THE_WAY.format("report.html", "published"),
    )
    assert files_under(showcase / "published") == before


# A move that fails while the file it moves is still there is a failed write like any other.
FAILED_MOVE = "no hash_inputs.json written: [Errno 2] made-up failed move\n"


def test_a_move_that_fails_while_its_own_file_is_there_is_an_ordinary_refusal(
    pair: Path, writer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(source: Any, target: Any) -> None:
        assert Path(source).is_file()
        raise FileNotFoundError(errno.ENOENT, "made-up failed move")

    monkeypatch.setattr(writer.os, "replace", failed)

    assert run_writer(writer, pair) == (EXIT_USAGE, "", FAILED_MOVE)
    assert not (pair / SIDECAR).exists()
    assert temporary_names(pair) == []


def test_a_failed_write_keeps_a_sidecar_another_run_moved_in_after_it_started(
    pair: Path, writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other-run.json"
    other.write_text('{"made-up": "written by another run"}\n', encoding="utf-8")
    rename = os.replace

    def raced(source: Any, target: Any) -> None:
        rename(other, target)
        raise OSError("made-up full disk")

    monkeypatch.setattr(writer.os, "replace", raced)

    assert run_writer(writer, pair) == (
        EXIT_USAGE,
        "",
        "no hash_inputs.json written: made-up full disk\n",
    )
    assert (pair / SIDECAR).read_text(encoding="utf-8") == (
        '{"made-up": "written by another run"}\n'
    )
    assert temporary_names(pair) == []


# The values the medium's run plants in its commands, all made up: a secret glued to a short
# option, a positional one, one in the path and one in the query of an address.
PLANTED = ("madeupglued1", "madeuppositional2", "madeuppath3", "madeupquery4")
LOGIN = "madeupuser-z"


def test_a_run_from_a_home_folder_publishes_no_value_its_results_hide(
    writer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home" / LOGIN
    (home / "bin").mkdir(parents=True)
    (home / "bench").mkdir()
    program = home / "bin" / "madeup-bench"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{home / 'bin'}:{os.environ.get('PATH', '')}")
    monkeypatch.chdir(home / "bench")
    sides = [
        f"{name}=cmd:madeup-bench -k{PLANTED[0]} {PLANTED[1]} --api "
        f"https://api.example/v1/{PLANTED[2]}/run?q={PLANTED[3]} --size {size}"
        for name, size in (("a", 1), ("b", 2))
    ]
    code, err = run_cli(
        "run",
        "--side",
        sides[0],
        "--side",
        sides[1],
        "--gates",
        "off",
        "--rounds",
        "6",
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "out",
    )
    assert code == EXIT_OK, err
    folder = home / "bench" / "out"
    published = tmp_path / "published"

    plain = run_writer(writer, folder)
    publish = run_writer(writer, folder, "--publish", published)

    count = len(hidden(writer, folder))
    assert count >= len(PLANTED)
    assert plain == (EXIT_OK, "", PRIVATE.format(count))
    assert publish == (
        EXIT_OK,
        PUBLISHED_WITHOUT_SIDECAR.format("published"),
        KEPT_PRIVATE.format(count),
    )
    assert sorted(path.name for path in published.iterdir()) == sorted(SHARED)
    for name in SHARED:
        assert (published / name).read_bytes() == (folder / name).read_bytes()
    assert mode_of(folder / SIDECAR) == PRIVATE_MODE
    sidecar = (folder / SIDECAR).read_text(encoding="utf-8")
    assert all(value in sidecar for value in PLANTED)
    assert str(home) not in sidecar
    assert LOGIN not in sidecar
    machine = this_machine()
    for name in SHARED:
        text = (folder / name).read_text(encoding="utf-8")
        for value in (*PLANTED, str(home), LOGIN):
            assert value not in text, (name, value)
        assert not names(machine.host, text) or machine.host in NEUTRAL_WORDS, name
        assert not names(machine.user, text) or machine.user in NEUTRAL_WORDS, name


# ---------------------------------------------------------------------------
# A real showcase script and the real writer, inside a container that reaches the copy at /work
# ---------------------------------------------------------------------------

# A small public image with a shell and Python. It is never pulled here.
SCRIPT_IMAGE = "python:3.12-slim"
# Stands in for pairbench: copies a run made by this file into the last folder given to --out.
STUB_PAIRBENCH = """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--out" ]; then out="$2"; shift; fi
  shift
done
mkdir -p "$out" && cp -R /made/. "$out"
"""
STUB_ENGINE = "#!/bin/sh\nexit 0\n"
NEIGHBOUR = "noisy-neighbour"
# The memory the container may use, and the memory and swap together: the same, so it never swaps.
SCRIPT_MEMORY = "8g"


def run_showcase_script(
    needs: Any, repo_root: Path, tmp_path: Path, made: Path
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the noisy-neighbour script with publish mode on, from a copy reached at /work."""
    engine = needs.engine("docker")
    found = subprocess.run(
        [engine, "image", "inspect", SCRIPT_IMAGE], capture_output=True, check=False, timeout=60
    )
    if found.returncode != 0:
        pytest.skip(f"needs the image {SCRIPT_IMAGE} on this machine; it is never pulled here")
    checkout = tmp_path / "checkout"
    shutil.copytree(repo_root / "showcases" / NEIGHBOUR, checkout / "showcases" / NEIGHBOUR)
    shutil.copy(repo_root / "showcases" / "publish.sh", checkout / "showcases" / "publish.sh")
    for part in ("src", "tools"):
        (checkout / part).mkdir()
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, text in (("pairbench", STUB_PAIRBENCH), ("docker", STUB_ENGINE)):
        (stubs / name).write_text(text, encoding="utf-8")
        (stubs / name).chmod(0o755)
    done = subprocess.run(
        script_container(engine, repo_root, checkout, stubs, made),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    return done, checkout / "showcases" / NEIGHBOUR


def script_container(
    engine: str, repo_root: Path, checkout: Path, stubs: Path, made: Path
) -> list[str]:
    """The engine command that runs the noisy-neighbour script on a copy reached at /work."""
    return [
        engine,
        "run",
        "--rm",
        "--pull",
        "never",
        "--memory",
        SCRIPT_MEMORY,
        "--memory-swap",
        SCRIPT_MEMORY,
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{checkout}:/work",
        "--volume",
        f"{repo_root / 'src'}:/work/src:ro",
        "--volume",
        f"{repo_root / 'tools'}:/work/tools:ro",
        "--volume",
        f"{stubs}:/stubs:ro",
        "--volume",
        f"{made}:/made:ro",
        "--env",
        "PATH=/stubs:/usr/local/bin:/usr/bin:/bin",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PAIRBENCH_SHOWCASE_PUBLISH=published",
        SCRIPT_IMAGE,
        "sh",
        f"/work/showcases/{NEIGHBOUR}/run.sh",
    ]


def test_the_script_container_may_not_swap_past_its_memory_limit(tmp_path: Path) -> None:
    command = script_container("docker", tmp_path, tmp_path, tmp_path, tmp_path)

    assert command.count("--memory") == 1
    assert command.count("--memory-swap") == 1
    assert command[command.index("--memory") + 1] == SCRIPT_MEMORY
    assert command[command.index("--memory-swap") + 1] == SCRIPT_MEMORY


def test_a_real_showcase_script_publishes_a_sidecar_that_can_be_shared(
    needs: Any, repo_root: Path, tmp_path: Path
) -> None:
    made = showcase_run(tmp_path / "made")

    done, folder = run_showcase_script(needs, repo_root, tmp_path, made)

    assert done.returncode == EXIT_OK, done.stderr
    assert done.stdout == PUBLISHED.format("quiet") + PUBLISHED.format("noisy")
    assert done.stderr == f"the two runs are in /work/showcases/{NEIGHBOUR}/published\n"
    for part in ("quiet", "noisy"):
        published = folder / "published" / part
        assert sorted(path.name for path in published.iterdir()) == sorted(
            ["results.json", "results.md", SIDECAR]
        )
        assert read(published / RESULTS) == read(made / RESULTS)
    (private,) = (folder / "pairbench-runs").iterdir()
    assert re.fullmatch(r"publish-[0-9]{8}T[0-9]{6}Z-[0-9]+", private.name)
    assert (private / "published" / "quiet" / "capture.jsonl").is_file()


def test_a_real_showcase_script_publishes_the_shared_files_when_the_sidecar_is_private(
    needs: Any, repo_root: Path, tmp_path: Path
) -> None:
    printed, typed, count = PRIVATE_ROWS["a-64-hex-secret"]
    made = with_report(showcase_run(tmp_path / "made", typed, printed))

    done, folder = run_showcase_script(needs, repo_root, tmp_path, made)

    assert (done.returncode, done.stdout, done.stderr) == (
        EXIT_OK,
        PUBLISHED_WITHOUT_SIDECAR.format("quiet") + PUBLISHED_WITHOUT_SIDECAR.format("noisy"),
        KEPT_PRIVATE.format(count) * 2
        + f"the two runs are in /work/showcases/{NEIGHBOUR}/published\n",
    )
    (private,) = (folder / "pairbench-runs").iterdir()
    for part in ("quiet", "noisy"):
        published = folder / "published" / part
        assert sorted(path.name for path in published.iterdir()) == sorted(SHARED)
        assert read(published / RESULTS) == read(made / RESULTS)
        sidecar = private / "published" / part / SIDECAR
        assert mode_of(sidecar) == PRIVATE_MODE
        assert "5e" * 32 in sidecar.read_text(encoding="utf-8")


# Stands in for pairbench on the host: copies a run made by this file into the folder given to
# --out, then exits with the code of the run it stands for.
STUB_RUN = """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--out" ]; then out="$2"; shift; fi
  shift
done
mkdir -p "$out" && cp -R "{made}/." "$out"
exit {code}
"""
# Runs the interpreter of this test as python3, so the helper runs the real writer.
PYTHON_SHIM = '#!/bin/sh\nexec "{python}" "$@"\n'
# The helper as a showcase's run.sh reads it, with the showcase reached under /work.
HELPER = (
    'set -eu; here=/work/showcases/made-up; cd "$1"; . "$2"; '
    'run_pairbench "" --config pairbench.toml'
)


@pytest.mark.parametrize("code", [EXIT_OK, EXIT_MISMATCH])
def test_the_showcase_helper_publishes_the_shared_files_of_a_private_run_with_the_run_s_code(
    repo_root: Path, tmp_path: Path, code: int
) -> None:
    printed, typed, count = PRIVATE_ROWS["a-64-hex-secret"]
    made = with_report(showcase_run(tmp_path / "made", typed, printed))
    checkout = tmp_path / "checkout"
    showcase = checkout / "showcases" / "made-up"
    showcase.mkdir(parents=True)
    for part in ("src", "tools"):
        (checkout / part).symlink_to(repo_root / part, target_is_directory=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, text in (
        ("pairbench", STUB_RUN.format(made=made, code=code)),
        ("python3", PYTHON_SHIM.format(python=sys.executable)),
    ):
        (stubs / name).write_text(text, encoding="utf-8")
        (stubs / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ.get('PATH', '')}"}
    env["PAIRBENCH_SHOWCASE_PUBLISH"] = "published"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    done = subprocess.run(
        ["sh", "-c", HELPER, "sh", str(showcase), str(repo_root / "showcases" / "publish.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )

    assert (done.returncode, done.stdout, done.stderr) == (
        code,
        PUBLISHED_WITHOUT_SIDECAR.format("published"),
        KEPT_PRIVATE.format(count),
    )
    assert sorted(path.name for path in (showcase / "published").iterdir()) == sorted(SHARED)
    (private,) = (showcase / "pairbench-runs").iterdir()
    assert mode_of(private / "published" / SIDECAR) == PRIVATE_MODE
    assert sorted(path.name for path in (private / "published").iterdir()) == sorted(
        [*SHARED, "capture.jsonl", SIDECAR]
    )


def test_the_launch_cost_script_publishes_the_shared_files_and_the_class_of_a_private_run(
    repo_root: Path, tmp_path: Path
) -> None:
    launch_cost = load(repo_root, "launch_cost")
    printed, typed, count = PRIVATE_ROWS["a-64-hex-secret"]
    out = tmp_path / "docs" / "figures" / "launch-cost"
    said: list[tuple[int, str, str]] = []

    def run(command: list[str]) -> int:
        """Look the image up and measure without running anything; run the real writer."""
        if "inspect" in command:
            return EXIT_OK
        if "wait-quiet" in command:
            with_report(showcase_run(tmp_path / command[-1], typed, printed))
            return EXIT_OK
        env = {**os.environ, "PYTHONPATH": str(repo_root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run(
            command, capture_output=True, text=True, env=env, check=False, timeout=300
        )
        said.append((done.returncode, done.stdout, done.stderr))
        return done.returncode

    code = launch_cost.main(
        [str(out), "--machine-class", "arm64, 4 cores, 16 GB"], run=run, repo=tmp_path
    )

    assert code == EXIT_OK
    assert said == [
        (EXIT_OK, PUBLISHED_WITHOUT_SIDECAR.format("launch-cost"), KEPT_PRIVATE.format(count))
    ]
    assert sorted(path.name for path in out.iterdir()) == sorted(
        [*SHARED, launch_cost.MACHINE_CLASS_FILE]
    )
    (private,) = (tmp_path / "pairbench-runs").iterdir()
    assert mode_of(private / SIDECAR) == PRIVATE_MODE


# ---------------------------------------------------------------------------
# Writers in containers, whose process numbers start from one in a process space of their own
# ---------------------------------------------------------------------------


# The mode of a sidecar that can be shared, written under the engine's default mask.
CONTAINER_MODE = 0o644


def writer_container(
    needs: Any, repo_root: Path, tmp_path: Path, folder: Path, *command: str
) -> list[str]:
    """The engine command that runs ``command`` on ``folder``, reached at /data/run."""
    engine = needs.engine("docker")
    found = subprocess.run(
        [engine, "image", "inspect", SCRIPT_IMAGE], capture_output=True, check=False, timeout=60
    )
    if found.returncode != 0:
        pytest.skip(f"needs the image {SCRIPT_IMAGE} on this machine; it is never pulled here")
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "killed.py").write_text(KILLED_WRITER, encoding="utf-8")
    (scripts / "paused.py").write_text(PAUSED_WRITER, encoding="utf-8")
    control = tmp_path / "control"
    control.mkdir(exist_ok=True)
    return [
        engine,
        "run",
        "--rm",
        "--pull",
        "never",
        "--memory",
        SCRIPT_MEMORY,
        "--memory-swap",
        SCRIPT_MEMORY,
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{folder}:/data/run",
        "--volume",
        f"{control}:/control",
        "--volume",
        f"{scripts}:/scripts:ro",
        "--volume",
        f"{repo_root / 'src'}:/src:ro",
        "--volume",
        f"{repo_root / 'tools'}:/tools:ro",
        "--env",
        "PYTHONPATH=/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        SCRIPT_IMAGE,
        *command,
    ]


def test_a_file_a_writer_killed_in_a_container_left_is_kept_while_young_and_removed_when_old(
    needs: Any, writer: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    published = tmp_path / "published"
    # The shell is the container's first process, so the writer is not, and SIGKILL ends it.
    command = writer_container(
        needs,
        repo_root,
        tmp_path,
        folder,
        "sh",
        "-c",
        "python3 /scripts/killed.py /tools/hash_inputs.py /data/run; exit $?",
    )

    killed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)
    left = [path for path in folder.iterdir() if TEMPORARY.fullmatch(path.name)]
    modes = [mode_of(path) for path in left]
    young = run_writer(writer, folder)
    publish = run_writer(writer, folder, "--publish", published)
    kept = temporary_names(folder)
    for path in left:
        old = time.time() - STRAY_SECONDS - 60
        os.utime(path, (old, old))
    aged = run_writer(writer, folder)

    assert killed.returncode == 128 + signal.SIGKILL, killed.stderr
    assert modes == [PRIVATE_MODE]
    assert killed_space(left) not in ("none", space_mark())
    assert young == (EXIT_OK, SHAREABLE, "")
    assert publish == (EXIT_OK, PUBLISHED.format("published"), "")
    assert kept == [path.name for path in left]
    assert aged == (EXIT_OK, SHAREABLE, "")
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]


def test_two_writers_of_one_process_number_in_two_containers_leave_a_whole_sidecar(
    needs: Any, writer: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    folder = showcase_run(tmp_path / "run")
    # Each writer is the first process of its container, so both have the number one.
    held = writer_container(
        needs,
        repo_root,
        tmp_path,
        folder,
        "python3",
        "/scripts/paused.py",
        "/tools/hash_inputs.py",
        "/data/run",
        "/control",
    )
    other = writer_container(
        needs, repo_root, tmp_path, folder, "python3", "/tools/hash_inputs.py", "/data/run"
    )
    control = tmp_path / "control"
    first = subprocess.Popen(held, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for(lambda: (control / "ready").exists(), "the held writer")
        filled = temporary_names(folder)
        second = subprocess.run(other, capture_output=True, text=True, check=False, timeout=300)
        between = temporary_names(folder)
    finally:
        (control / "go").touch()
        out, err = first.communicate(timeout=300)

    assert [killed_pid([folder / name for name in filled])] == ["1"]
    assert (second.returncode, second.stdout, second.stderr) == (EXIT_OK, SHAREABLE, "")
    assert between == filled
    assert (first.returncode, out, err) == (EXIT_OK, SHAREABLE, "")
    assert mode_of(folder / SIDECAR) == CONTAINER_MODE
    whole = (folder / SIDECAR).read_bytes()
    assert run_writer(writer, folder) == (EXIT_OK, SHAREABLE, "")
    assert (folder / SIDECAR).read_bytes() == whole
    assert sorted(path.name for path in folder.iterdir()) == [
        "capture.jsonl",
        SIDECAR,
        "results.json",
        "results.md",
    ]
