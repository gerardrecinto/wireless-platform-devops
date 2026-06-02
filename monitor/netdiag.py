#!/usr/bin/env python3
"""
Network diagnostics for Linux prototype wireless systems.
Reads bridge state, routing table, PCIe NIC counters, and interface errors
directly from /proc and /sys — no external tools required except for
optional ethtool integration for driver-level stats.
"""

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class InterfaceStats:
    name: str
    state: str
    mtu: int
    driver: str
    rx_bytes: int
    tx_bytes: int
    rx_errors: int
    tx_errors: int
    rx_dropped: int
    tx_dropped: int


@dataclass
class BridgeInfo:
    name: str
    members: list[str]
    state: str
    stp_enabled: bool


@dataclass
class RouteEntry:
    dest: str
    gateway: str
    iface: str
    flags: str
    metric: int


@dataclass
class PcieNic:
    interface: str
    pci_addr: str
    vendor_id: str
    device_id: str
    speed_mbps: str
    driver: str
    link_mode: str


@dataclass
class NetReport:
    timestamp: float
    interfaces: list[InterfaceStats] = field(default_factory=list)
    bridges: list[BridgeInfo] = field(default_factory=list)
    routes: list[RouteEntry] = field(default_factory=list)
    pcie_nics: list[PcieNic] = field(default_factory=list)


def _sysfs(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except (FileNotFoundError, PermissionError):
        return ""


def read_interfaces() -> list[InterfaceStats]:
    stats = []
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except FileNotFoundError:
        return stats

    for line in lines:
        parts = line.split()
        if len(parts) < 17:
            continue
        name = parts[0].rstrip(":")
        base = f"/sys/class/net/{name}"
        stats.append(InterfaceStats(
            name=name,
            state=_sysfs(f"{base}/operstate"),
            mtu=int(_sysfs(f"{base}/mtu") or 0),
            driver=_get_driver(name),
            rx_bytes=int(parts[1]),
            tx_bytes=int(parts[9]),
            rx_errors=int(parts[3]),
            tx_errors=int(parts[11]),
            rx_dropped=int(parts[4]),
            tx_dropped=int(parts[12]),
        ))
    return stats


def _get_driver(iface: str) -> str:
    driver_link = f"/sys/class/net/{iface}/device/driver"
    try:
        real = os.path.realpath(driver_link)
        return os.path.basename(real)
    except (FileNotFoundError, OSError):
        return ""


def read_bridges() -> list[BridgeInfo]:
    bridges = []
    net_dir = "/sys/class/net"
    try:
        names = os.listdir(net_dir)
    except FileNotFoundError:
        return bridges

    for name in sorted(names):
        brdir = f"{net_dir}/{name}/bridge"
        if not os.path.isdir(brdir):
            continue
        members = []
        brif = f"{net_dir}/{name}/brif"
        if os.path.isdir(brif):
            members = sorted(os.listdir(brif))
        stp = _sysfs(f"{brdir}/stp_state") == "1"
        bridges.append(BridgeInfo(
            name=name,
            members=members,
            state=_sysfs(f"{net_dir}/{name}/operstate"),
            stp_enabled=stp,
        ))
    return bridges


def read_routes() -> list[RouteEntry]:
    routes = []
    try:
        lines = Path("/proc/net/route").read_text().splitlines()[1:]
    except FileNotFoundError:
        return routes

    for line in lines:
        parts = line.split()
        if len(parts) < 11:
            continue
        dest = _hex_to_ip(parts[1])
        gw = _hex_to_ip(parts[2])
        flags = _decode_route_flags(int(parts[3], 16))
        metric = int(parts[6])
        routes.append(RouteEntry(dest=dest, gateway=gw, iface=parts[0],
                                  flags=flags, metric=metric))
    return sorted(routes, key=lambda r: r.metric)


def _hex_to_ip(h: str) -> str:
    try:
        return socket.inet_ntoa(struct.pack("<I", int(h, 16)))
    except (ValueError, struct.error):
        return "0.0.0.0"


def _decode_route_flags(flags: int) -> str:
    flag_map = {0x1: "U", 0x2: "G", 0x4: "H", 0x8: "R", 0x10: "D",
                0x20: "M", 0x40: "A", 0x100: "!", 0x200: "L"}
    return "".join(v for k, v in flag_map.items() if flags & k) or "?"


def read_pcie_nics() -> list[PcieNic]:
    nics = []
    net_dir = "/sys/class/net"
    try:
        names = os.listdir(net_dir)
    except FileNotFoundError:
        return nics

    for name in sorted(names):
        dev_path = f"{net_dir}/{name}/device"
        if not os.path.exists(dev_path):
            continue
        real = os.path.realpath(dev_path)
        if "pci" not in real.lower():
            continue
        pci_addr = os.path.basename(real)
        link_mode = _get_ethtool_speed(name)
        nics.append(PcieNic(
            interface=name,
            pci_addr=pci_addr,
            vendor_id=_sysfs(f"{dev_path}/vendor"),
            device_id=_sysfs(f"{dev_path}/device"),
            speed_mbps=_sysfs(f"{net_dir}/{name}/speed"),
            driver=_get_driver(name),
            link_mode=link_mode,
        ))
    return nics


def _get_ethtool_speed(iface: str) -> str:
    try:
        result = subprocess.run(
            ["ethtool", iface], capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Speed:") or line.startswith("Duplex:"):
                return line
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def check_error_spikes(report: NetReport) -> list[str]:
    warnings = []
    for iface in report.interfaces:
        if iface.name == "lo":
            continue
        if iface.rx_errors + iface.tx_errors > 0:
            warnings.append(
                f"{iface.name}: errors rx={iface.rx_errors} tx={iface.tx_errors}"
            )
        if iface.rx_dropped + iface.tx_dropped > 1000:
            warnings.append(
                f"{iface.name}: drops rx={iface.rx_dropped} tx={iface.tx_dropped}"
            )
    return warnings


def format_report(r: NetReport) -> str:
    lines = [f"=== netdiag {time.strftime('%H:%M:%S', time.localtime(r.timestamp))} ===", ""]

    lines.append(f"{'Interface':<16} {'State':<8} {'MTU':>5} {'Driver':<16}"
                 f"  {'RX MB':>8}  {'TX MB':>8}  {'Err':>5}  {'Drop':>6}")
    lines.append("-" * 82)
    for i in r.interfaces:
        if i.name == "lo":
            continue
        rx_mb = i.rx_bytes / 1e6
        tx_mb = i.tx_bytes / 1e6
        err = i.rx_errors + i.tx_errors
        drop = i.rx_dropped + i.tx_dropped
        err_flag = " !" if err > 0 else ""
        drop_flag = " !" if drop > 1000 else ""
        lines.append(f"{i.name:<16} {i.state:<8} {i.mtu:>5} {i.driver:<16}"
                     f"  {rx_mb:>8.1f}  {tx_mb:>8.1f}  {err:>5}{err_flag}  {drop:>6}{drop_flag}")

    if r.bridges:
        lines += ["", "Bridges:"]
        for b in r.bridges:
            m = ", ".join(b.members) if b.members else "(none)"
            stp = "STP" if b.stp_enabled else "no-STP"
            lines.append(f"  {b.name} [{b.state}] [{stp}]  members: {m}")

    if r.routes:
        lines += ["", "Routes:"]
        lines.append(f"  {'Dest':<18} {'Gateway':<18} {'Iface':<14} {'Flags':<8} {'Metric':>6}")
        lines.append("  " + "-" * 68)
        for rt in r.routes[:15]:
            lines.append(f"  {rt.dest:<18} {rt.gateway:<18} {rt.iface:<14}"
                         f" {rt.flags:<8} {rt.metric:>6}")

    if r.pcie_nics:
        lines += ["", "PCIe NICs:"]
        for nic in r.pcie_nics:
            speed = f"{nic.speed_mbps} Mbps" if nic.speed_mbps not in ("", "-1") else "link-down"
            lines.append(f"  {nic.interface:<14} pci={nic.pci_addr}  "
                         f"vendor={nic.vendor_id}  dev={nic.device_id}  "
                         f"driver={nic.driver}  {speed}")

    warnings = check_error_spikes(r)
    if warnings:
        lines += ["", "WARNINGS:"]
        for w in warnings:
            lines.append(f"  ! {w}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Network diagnostics for Linux prototype wireless systems"
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--watch", type=float, metavar="INTERVAL",
                        help="Continuous watch mode, seconds between polls")
    args = parser.parse_args()

    while True:
        report = NetReport(
            timestamp=time.time(),
            interfaces=read_interfaces(),
            bridges=read_bridges(),
            routes=read_routes(),
            pcie_nics=read_pcie_nics(),
        )
        if args.json:
            print(json.dumps(asdict(report), indent=2))
        else:
            print(format_report(report))

        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
