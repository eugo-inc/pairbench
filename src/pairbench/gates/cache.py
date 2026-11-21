# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Last-level cache domains: which CPUs share the largest cache.

The kernel describes each cache of a CPU under
``/sys/devices/system/cpu/cpuN/cache/indexM/`` with the files ``level``,
``type`` and ``shared_cpu_list``
(https://docs.kernel.org/admin-guide/cputopology.html). The last-level
cache of a CPU is its data or unified cache of the highest level.
"""

from __future__ import annotations

from collections.abc import Iterable

from pairbench.gates.platform import CPU_DIR, Root, format_cpu_list, online_cpus, read_cpu_list

_CACHE_TYPES = ("Unified", "Data")


def last_level_domain(root: Root, cpu: int) -> frozenset[int] | None:
    """The CPUs that share the last-level cache of one CPU, or ``None`` when unreadable."""
    base = f"{CPU_DIR}/cpu{cpu}/cache"
    names = root.names(base)
    if not names:
        return None
    best_level = -1
    best: frozenset[int] | None = None
    for name in names:
        if not name.startswith("index"):
            continue
        kind = root.line(f"{base}/{name}/type")
        level_text = root.line(f"{base}/{name}/level")
        if kind not in _CACHE_TYPES or level_text is None or not level_text.isdigit():
            continue
        level = int(level_text)
        shared = read_cpu_list(root, f"{base}/{name}/shared_cpu_list")
        if shared is None or not shared:
            continue
        if level > best_level:
            best_level, best = level, shared
    return best


def cache_domains(
    root: Root, cpus: Iterable[int] | None = None
) -> tuple[frozenset[int], ...] | None:
    """The last-level cache domains, each the full set of CPUs that share one cache.

    With ``cpus`` given, only the domains that hold at least one of them are
    returned; otherwise every domain of the machine. The domains come in the
    order of their lowest CPU. ``None`` when the topology cannot be read for
    a CPU that is asked about.
    """
    if cpus is None:
        wanted = online_cpus(root)
        if wanted is None:
            return None
    else:
        wanted = frozenset(cpus)
    domains: dict[frozenset[int], None] = {}
    covered: set[int] = set()
    for cpu in sorted(wanted):
        if cpu in covered:
            continue
        domain = last_level_domain(root, cpu)
        if domain is None:
            return None
        domains[domain | {cpu}] = None
        covered.update(domain)
    return tuple(sorted(domains, key=min))


def domain_lists(domains: Iterable[frozenset[int]]) -> tuple[str, ...]:
    """The domains written as CPU lists, as a capture records them."""
    return tuple(format_cpu_list(d) for d in domains)


def sharing_cache(root: Root, pinned: frozenset[int]) -> frozenset[int] | None:
    """Every CPU that shares a last-level cache with a CPU of the pinned set.

    The pinned CPUs are part of the answer. ``None`` when the topology
    cannot be read.
    """
    domains = cache_domains(root, pinned)
    if domains is None:
        return None
    out: set[int] = set(pinned)
    for domain in domains:
        out.update(domain)
    return frozenset(out)
