# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""CPU pinning: core types, the refusal of a set that mixes them, and where the
tool itself runs.

The type of a core comes from the processor identification the kernel
exposes per CPU, in this order:

1. the ARM main ID register, ``cpuN/regs/identification/midr_el1``
   (https://docs.kernel.org/arch/arm64/cpu-feature-registers.html): the
   implementer and the part number;
2. ``/proc/cpuinfo``: ``vendor_id``, ``cpu family`` and ``model`` on x86,
   ``CPU implementer`` and ``CPU part`` on ARM;
3. on a machine with a hybrid processor, the CPU list of each core PMU
   under ``/sys/devices/cpu_*/cpus`` (for example ``cpu_core`` and
   ``cpu_atom``) adds the kind of core to the key.

Only where no identification is exposed at all does the maximum frequency,
``cpufreq/cpuinfo_max_freq``, stand in for it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping
from typing import Any, Final

from pairbench.api import API_VERSION, CpuFacts, DoctorReport, GateContext, ToolCpus
from pairbench.errors import Refusal
from pairbench.gates.cache import cache_domains, domain_lists
from pairbench.gates.platform import (
    CPU_DIR,
    MAX_CPU,
    Affinity,
    CpuNumberTooHigh,
    Platform,
    Root,
    System,
    cgroup_cpus,
    format_cpu_list,
    make_record,
    online_cpus,
    parse_cpu_list,
    read_cpu_list,
    this_system,
)
from pairbench.model import (
    NOTE_TOOL_ON_PINNED_CPUS,
    CpuGroup,
    GateRecord,
    GateStatus,
    LaunchSettings,
)

UNKNOWN_KEY: Final = "unknown"
NAME: Final = "cpus"
# How bad a record of the check is: the worst of several sets is the one reported.
SEVERITY: Final[Mapping[GateStatus, int]] = {"pass": 0, "degraded": 1, "unavailable": 2, "fail": 3}
# What the record of a check that passes holds about each side's own CPU set.
SIDE_FACTS: Final = ("cpus", "identity", "cache_domains", "mixed")


def _hex(text: str) -> int | None:
    try:
        return int(text.strip(), 0)
    except ValueError:
        return None


def _arm_key(implementer: int, part: int) -> str:
    return f"arm-{implementer:02x}-{part:03x}"


def _midr_key(root: Root, cpu: int) -> str | None:
    text = root.line(f"{CPU_DIR}/cpu{cpu}/regs/identification/midr_el1")
    if not text:
        return None
    value = _hex(text if text.lower().startswith("0x") else f"0x{text}")
    if value is None:
        return None
    return _arm_key((value >> 24) & 0xFF, (value >> 4) & 0xFFF)


def _cpuinfo_keys(root: Root) -> dict[int, str]:
    text = root.text("proc/cpuinfo")
    if text is None:
        return {}
    keys: dict[int, str] = {}
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for raw in block.splitlines():
            name, sep, value = raw.partition(":")
            if sep:
                fields[name.strip()] = value.strip()
        number = fields.get("processor", "")
        if not number.isdigit():
            continue
        cpu = int(number)
        if all(k in fields for k in ("vendor_id", "cpu family", "model")):
            keys[cpu] = f"{fields['vendor_id']}-{fields['cpu family']}-{fields['model']}"
            continue
        implementer = _hex(fields.get("CPU implementer", ""))
        part = _hex(fields.get("CPU part", ""))
        if implementer is not None and part is not None:
            keys[cpu] = _arm_key(implementer, part)
    return keys


def _hybrid_kinds(root: Root) -> dict[int, str]:
    kinds: dict[int, str] = {}
    for name in root.names("sys/devices") or []:
        if not name.startswith("cpu_") or len(name) <= len("cpu_"):
            continue
        listed = read_cpu_list(root, f"sys/devices/{name}/cpus")
        for cpu in listed or ():
            kinds[cpu] = name[len("cpu_") :]
    return kinds


def max_khz(root: Root, cpu: int) -> int:
    """The maximum frequency of a CPU in kHz, or 0 when the kernel does not give it."""
    text = root.line(f"{CPU_DIR}/cpu{cpu}/cpufreq/cpuinfo_max_freq")
    return int(text) if text and text.isdigit() else 0


def core_types(root: Root, cpus: Iterable[int]) -> dict[int, str]:
    """The core-type key of every CPU asked about; ``unknown`` where nothing can be read."""
    wanted = sorted(set(cpus))
    from_info = _cpuinfo_keys(root)
    hybrid = _hybrid_kinds(root)
    keys: dict[int, str] = {}
    for cpu in wanted:
        key = _midr_key(root, cpu) or from_info.get(cpu)
        if key is not None and cpu in hybrid:
            key = f"{key}-{hybrid[cpu]}"
        if key is None:
            khz = max_khz(root, cpu)
            key = f"khz-{khz}" if khz else None
        keys[cpu] = key or UNKNOWN_KEY
    return keys


def groups(root: Root, keys: Mapping[int, str]) -> tuple[CpuGroup, ...]:
    """One group per core type, in the order of its lowest CPU.

    A group's maximum frequency is the highest of its CPUs.
    """
    by_key: dict[str, list[int]] = {}
    for cpu in sorted(keys):
        by_key.setdefault(keys[cpu], []).append(cpu)
    return tuple(
        CpuGroup(
            cpus=format_cpu_list(members),
            key=key,
            max_khz=max(max_khz(root, cpu) for cpu in members),
        )
        for key, members in by_key.items()
    )


def _pinned_set(cpus: str) -> frozenset[int]:
    """The CPUs of ``--cpus``.

    A CPU above ``MAX_CPU`` is refused with ``E_PIN_UNSUPPORTED``, as a CPU
    that is not online is; text that is no CPU list with ``E_USAGE``.
    """
    try:
        pinned = parse_cpu_list(cpus)
    except CpuNumberTooHigh as exc:
        raise Refusal(
            "E_PIN_UNSUPPORTED",
            f"CPU numbers above {MAX_CPU} are not supported: {cpus!r}",
            detail={"cpus": cpus},
        ) from exc
    except ValueError as exc:
        raise Refusal("E_USAGE", f"--cpus is a list such as 4-7 or 0,2,4: {cpus!r}") from exc
    if not pinned:
        raise Refusal("E_USAGE", "--cpus names no CPU")
    return pinned


def cpu_facts(root: Root, system: System, cpus: str | None, *, allow_mixed: bool) -> CpuFacts:
    """Describe the pinned CPU set, or the machine when nothing is pinned.

    A pinned set is refused with ``E_PIN_UNSUPPORTED`` where pinning cannot
    be done: on a platform other than Linux, for a CPU that is not online, or
    for a CPU outside the CPUs this process's cgroup allows (inside a
    container, the container's own CPUs). A set whose CPUs are of more than
    one core type, or whose type cannot be read for some of its CPUs while
    it can for others, is refused with ``E_CPUS_MIXED_TYPES`` unless
    ``allow_mixed``.
    """
    if cpus is None:
        if system != "linux":
            return CpuFacts()
        online = online_cpus(root)
        if not online:
            return CpuFacts()
        keys = core_types(root, online)
        domains = cache_domains(root, online) or ()
        return CpuFacts(
            identity=groups(root, keys),
            cache_domains=domain_lists(domains),
            mixed=len(set(keys.values())) > 1,
        )
    pinned = _pinned_set(cpus)
    if system != "linux":
        raise Refusal(
            "E_PIN_UNSUPPORTED",
            "pinning to CPUs is not supported on this platform",
            detail={"cpus": cpus},
        )
    online = online_cpus(root)
    if online is not None and not pinned <= online:
        raise Refusal(
            "E_PIN_UNSUPPORTED",
            f"CPUs {format_cpu_list(pinned - online)} are not online on this machine",
            detail={"cpus": cpus, "online": format_cpu_list(online)},
        )
    allowed = cgroup_cpus(root)
    if allowed is not None and not pinned <= allowed:
        raise Refusal(
            "E_PIN_UNSUPPORTED",
            f"CPUs {format_cpu_list(pinned - allowed)} are outside the CPUs this process may use",
            detail={"cpus": cpus, "allowed": format_cpu_list(allowed)},
        )
    keys = core_types(root, pinned)
    found = set(keys.values())
    mixed = len(found) > 1
    if mixed and not allow_mixed:
        listed = ", ".join(sorted(found))
        raise Refusal(
            "E_CPUS_MIXED_TYPES",
            f"the CPU set {cpus} mixes core types ({listed}); "
            "give --allow-mixed-core-types to run on it anyway",
            detail={"cpus": cpus, "keys": {str(cpu): key for cpu, key in sorted(keys.items())}},
        )
    domains = cache_domains(root, pinned) or ()
    return CpuFacts(identity=groups(root, keys), cache_domains=domain_lists(domains), mixed=mixed)


def leave_pinned(cpus: str | None, *, system: System, affinity: Affinity) -> ToolCpus:
    """Move the tool's own threads onto CPUs outside the pinned set.

    The CPUs outside are those the calling thread may run on now, less the
    pinned set. The calling thread moves first; the other threads of the
    process follow, and a thread that has ended meanwhile is passed over.
    Threads started afterwards inherit the calling thread's CPUs.
    """
    if cpus is None:
        return ToolCpus(reason="not_pinned")
    pinned = _pinned_set(cpus)
    if system != "linux" or affinity.set is None:
        return ToolCpus(reason="unsupported")
    current = affinity.get()
    if current is None:
        return ToolCpus(reason="unsupported")
    outside = frozenset(current - pinned)
    if not outside:
        return ToolCpus(reason="none_left")
    try:
        affinity.set(0, outside)
    except OSError:
        return ToolCpus(reason="unsupported")
    try:
        threads = affinity.threads()
    except OSError:
        threads = ()
    for task in threads:
        try:
            affinity.set(task, outside)
        except OSError:
            continue
    return ToolCpus(cpus=format_cpu_list(outside))


def return_home(home: frozenset[int], *, affinity: Affinity) -> None:
    """Move the tool's threads back onto ``home``, where ``leave_pinned`` found them.

    The calling thread moves first; every other thread of the process
    follows, those started after ``leave_pinned`` included, and a thread
    that has ended meanwhile, or that cannot move, is passed over.
    """
    if affinity.set is None:
        return
    with contextlib.suppress(OSError):
        affinity.set(0, home)
    try:
        threads = affinity.threads()
    except OSError:
        threads = ()
    for task in threads:
        with contextlib.suppress(OSError):
            affinity.set(task, home)


def tool_cpus_note(answer: ToolCpus, cpus: str | None) -> tuple[str, str] | None:
    """The loud note for an answer of ``leave_pinned`` that left the tool on the pinned set."""
    if answer.reason == "none_left":
        return (
            NOTE_TOOL_ON_PINNED_CPUS,
            f"no CPU is left outside the pinned set {cpus}; "
            "the tool runs on the same CPUs as the launches",
        )
    if answer.reason == "unsupported":
        return (
            NOTE_TOOL_ON_PINNED_CPUS,
            "this platform does not let the tool move off the pinned CPUs; "
            "the tool may run on the same CPUs as the launches",
        )
    return None


def own_sets(launch: LaunchSettings) -> dict[str, str]:
    """The CPU set each side gives itself, by side name, where it differs from the shared set."""
    found: dict[str, str] = {}
    for side, table in launch.overrides.items():
        cpus = table.get("cpus")
        if isinstance(cpus, str) and cpus != launch.cpus:
            found[side] = cpus
    return found


class CpusGate:
    """The check of the pinned CPU set: one core type, every CPU usable.

    Unpinned, it describes the machine and says in the detail whether the
    machine has more than one core type; the loud note for a run that is
    not pinned on such a machine is the runner's. The CPUs and the cache
    domains go into the record's detail.

    The CPU set a side gives itself is checked as the shared set is, and a
    record about it names the side, in its message and under ``side``.
    """

    name: Final = NAME
    api_version: Final = API_VERSION

    def __init__(self, *, root: Root | None = None, system: System | None = None) -> None:
        self._root = root or Root()
        self._system = system

    def check(self, ctx: GateContext) -> GateRecord:
        """Run the check once and report.

        The shared set is checked first, then each side's own set. The worst
        record is reported, the first of them where two are as bad: a failed
        check, then one that could not run, then a degraded one. When every
        set passes, the record of the shared set also holds, under
        ``sides``, the facts of each side's own set.
        """
        platform = Platform.of(ctx, self._system)
        shared = self._check_set(ctx, platform, ctx.launch.cpus)
        own = own_sets(ctx.launch)
        if not own:
            return shared
        records = [shared]
        described: dict[str, Any] = {}
        for side, cpus in own.items():
            record = self._check_set(ctx, platform, cpus, side=side)
            records.append(record)
            described[side] = {k: record.detail[k] for k in SIDE_FACTS if k in record.detail}
        worst = max(records, key=lambda record: SEVERITY[record.status])
        if worst.status != "pass":
            return worst
        return make_record(NAME, ctx, "pass", **shared.detail, sides=described)

    def _check_set(
        self, ctx: GateContext, platform: Platform, cpus: str | None, *, side: str | None = None
    ) -> GateRecord:
        """Check one CPU set: the shared one, or the one ``side`` gives itself."""
        view: dict[str, Any] = {"where": platform.where}
        if side is not None:
            view["side"] = side

        def record(status: GateStatus, message: str = "", **detail: Any) -> GateRecord:
            said = f"side {side}: {message}" if side is not None and message else message
            return make_record(NAME, ctx, status, said, **detail, **view)

        if platform.system != "linux":
            if cpus is not None:
                return record(
                    "unavailable",
                    "pinning to CPUs is not supported on this platform",
                    code="E_PIN_UNSUPPORTED",
                    cpus=cpus,
                )
            return record("unavailable", "core types cannot be read on this platform")
        try:
            facts = cpu_facts(
                self._root, platform.system, cpus, allow_mixed=ctx.gates.allow_mixed_core_types
            )
        except Refusal as refusal:
            status: GateStatus = "fail" if refusal.code == "E_CPUS_MIXED_TYPES" else "unavailable"
            return record(status, refusal.message, code=refusal.code, cpus=cpus)
        identity = [group.to_json() for group in facts.identity]
        detail: dict[str, Any] = {
            "cpus": cpus,
            "identity": identity,
            "cache_domains": list(facts.cache_domains),
            "mixed": facts.mixed,
        }
        if not facts.identity:
            return record("unavailable", "the CPUs could not be read", **detail)
        keys = {group.key for group in facts.identity}
        if UNKNOWN_KEY in keys:
            where = "pinned CPUs" if cpus is not None else "CPUs"
            return record("degraded", f"the core type of some {where} could not be read", **detail)
        return record("pass", **detail)

    def doctor(self) -> DoctorReport:
        """What this platform lets the check do."""
        system = this_system() if self._system is None else self._system
        if system != "linux":
            return DoctorReport("unavailable", "CPU pinning and core types are Linux only")
        online = online_cpus(self._root)
        if not online:
            return DoctorReport("degraded", "the online CPUs could not be read")
        keys = set(core_types(self._root, online).values())
        if UNKNOWN_KEY in keys:
            return DoctorReport("degraded", "the core type of some CPUs could not be read")
        return DoctorReport(
            "ok", f"{len(online)} CPUs of {len(keys)} core type(s)", {"keys": sorted(keys)}
        )
