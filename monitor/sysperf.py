#!/usr/bin/env python3
"""
Linux multi-core performance monitor for wireless prototype platforms.
Tracks per-core utilization, IRQ distribution, memory pressure,
and NUMA topology, used to diagnose workload imbalance on PCIe-attached
radio hardware where CPU affinity misconfig causes latency spikes.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

try:
    import psutil
except ImportError:
    sys.exit("psutil required: pip install psutil")


@dataclass
class CoreStats:
    core_id: int
    util_pct: float
    freq_mhz: float
    irq_count: int


@dataclass
class MemStats:
    total_gb: float
    used_gb: float
    available_gb: float
    swap_used_gb: float
    page_faults: int


@dataclass
class NumaNode:
    node_id: int
    cpu_list: list[int]
    mem_used_gb: float
    mem_total_gb: float


@dataclass
class SampleSnapshot:
    timestamp: float
    cores: list[CoreStats] = field(default_factory=list)
    mem: MemStats = field(default_factory=lambda: MemStats(0, 0, 0, 0, 0))
    numa: list[NumaNode] = field(default_factory=list)
    load_avg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    context_switches: int = 0


def _read_irq_counts() -> dict[int, int]:
    counts: dict[int, int] = {}
    try:
        with open("/proc/interrupts") as f:
            lines = f.readlines()
        if not lines:
            return counts
        header = lines[0].split()
        cpu_count = len(header)
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < cpu_count + 1:
                continue
            for i in range(cpu_count):
                try:
                    counts[i] = counts.get(i, 0) + int(parts[i + 1])
                except (ValueError, IndexError):
                    pass
    except FileNotFoundError:
        pass
    return counts


def _read_numa_nodes() -> list[NumaNode]:
    nodes = []
    numa_base = "/sys/devices/system/node"
    if not os.path.isdir(numa_base):
        return nodes
    for entry in sorted(os.listdir(numa_base)):
        if not entry.startswith("node"):
            continue
        try:
            node_id = int(entry[4:])
        except ValueError:
            continue
        cpu_list = _parse_cpu_list(f"{numa_base}/{entry}/cpulist")
        mem_used, mem_total = _read_numa_meminfo(f"{numa_base}/{entry}/meminfo", node_id)
        nodes.append(NumaNode(node_id=node_id, cpu_list=cpu_list,
                               mem_used_gb=mem_used, mem_total_gb=mem_total))
    return nodes


def _parse_cpu_list(path: str) -> list[int]:
    try:
        with open(path) as f:
            text = f.read().strip()
        cpus = []
        for part in text.split(","):
            if "-" in part:
                start, end = part.split("-")
                cpus.extend(range(int(start), int(end) + 1))
            else:
                cpus.append(int(part))
        return cpus
    except (FileNotFoundError, ValueError):
        return []


def _read_numa_meminfo(path: str, node_id: int) -> tuple[float, float]:
    used = total = 0.0
    try:
        with open(path) as f:
            for line in f:
                # format: "Node N MemTotal:   X kB"
                if f"Node {node_id} MemTotal:" in line:
                    total = int(line.split()[-2]) / 1e6
                elif f"Node {node_id} MemUsed:" in line:
                    used = int(line.split()[-2]) / 1e6
    except (FileNotFoundError, ValueError):
        pass
    return used, total


def collect_core_stats() -> list[CoreStats]:
    per_cpu = psutil.cpu_percent(percpu=True, interval=None)
    freqs = psutil.cpu_freq(percpu=True) or []
    irq_counts = _read_irq_counts()
    stats = []
    for i, util in enumerate(per_cpu):
        freq = freqs[i].current if i < len(freqs) else 0.0
        stats.append(CoreStats(core_id=i, util_pct=util,
                                freq_mhz=freq, irq_count=irq_counts.get(i, 0)))
    return stats


def collect_mem_stats() -> MemStats:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    page_faults = 0
    try:
        with open("/proc/vmstat") as f:
            for line in f:
                if line.startswith("pgmajfault"):
                    page_faults = int(line.split()[1])
                    break
    except FileNotFoundError:
        pass
    return MemStats(
        total_gb=vm.total / 1e9,
        used_gb=vm.used / 1e9,
        available_gb=vm.available / 1e9,
        swap_used_gb=swap.used / 1e9,
        page_faults=page_faults,
    )


def collect_snapshot() -> SampleSnapshot:
    snap = SampleSnapshot(timestamp=time.time())
    snap.cores = collect_core_stats()
    snap.mem = collect_mem_stats()
    snap.numa = _read_numa_nodes()
    snap.load_avg = os.getloadavg()
    snap.context_switches = psutil.cpu_stats().ctx_switches
    return snap


def detect_imbalance(snap: SampleSnapshot, threshold: float = 30.0) -> list[str]:
    if not snap.cores:
        return []
    utils = [c.util_pct for c in snap.cores]
    mean = sum(utils) / len(utils)
    return [
        f"Core {c.core_id} over-loaded: {c.util_pct:.1f}% vs mean {mean:.1f}%"
        for c in snap.cores
        if c.util_pct - mean > threshold
    ]


def format_snapshot(snap: SampleSnapshot) -> str:
    ts = time.strftime("%H:%M:%S", time.localtime(snap.timestamp))
    lines = [f"=== sysperf {ts} ==="]
    lines.append(
        f"Load:  {snap.load_avg[0]:.2f}/{snap.load_avg[1]:.2f}/{snap.load_avg[2]:.2f}"
        f"  ctx_sw={snap.context_switches}"
    )
    lines.append(
        f"Mem:   used={snap.mem.used_gb:.1f}G  avail={snap.mem.available_gb:.1f}G"
        f"  pgmajfault={snap.mem.page_faults}"
    )
    if snap.mem.swap_used_gb > 0.01:
        lines.append(f"Swap:  {snap.mem.swap_used_gb:.2f}G  [WARN]")

    if snap.numa:
        lines.append("NUMA:")
        for n in snap.numa:
            cpus = ",".join(str(c) for c in n.cpu_list[:8])
            if len(n.cpu_list) > 8:
                cpus += "..."
            lines.append(f"  node{n.node_id}: cpus=[{cpus}]"
                         f"  mem={n.mem_used_gb:.1f}/{n.mem_total_gb:.1f}G")

    lines.append("")
    lines.append(f"  {'Core':>4}  {'Util%':>6}  {'MHz':>7}  {'IRQs':>10}")
    lines.append("  " + "-" * 36)
    for c in snap.cores:
        flag = " !" if c.util_pct > 90 else ""
        lines.append(f"  {c.core_id:>4}  {c.util_pct:>6.1f}  {c.freq_mhz:>7.0f}  {c.irq_count:>10}{flag}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Linux multi-core performance monitor for wireless prototype platforms"
    )
    parser.add_argument("-i", "--interval", type=float, default=2.0)
    parser.add_argument("-n", "--count", type=int, default=0, help="0=infinite")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--imbalance-threshold", type=float, default=30.0,
                        help="CPU imbalance alert threshold %%")
    args = parser.parse_args()

    psutil.cpu_percent(percpu=True, interval=None)
    time.sleep(0.1)

    count = 0
    while True:
        snap = collect_snapshot()
        if args.json:
            print(json.dumps(asdict(snap), indent=2))
        else:
            print(format_snapshot(snap))
            for w in detect_imbalance(snap, args.imbalance_threshold):
                print(f"  WARN: {w}")
            print()

        count += 1
        if args.count and count >= args.count:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
