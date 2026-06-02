#!/usr/bin/env python3
"""
RPM spec generator and build automation for Linux platform packages.
Handles kernel image RPMs, device driver packages, and platform
component bundles for prototype wireless systems.
"""

import argparse
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PackageSpec:
    name: str
    version: str
    release: str
    summary: str
    description: str
    arch: str = "x86_64"
    license_tag: str = "Proprietary"
    requires: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    pre_install: str = ""
    post_install: str = ""
    pre_uninstall: str = ""
    files: list[str] = field(default_factory=list)
    changelog: list[tuple[str, str, str]] = field(default_factory=list)


def generate_spec(spec: PackageSpec) -> str:
    lines = [
        f"Name:           {spec.name}",
        f"Version:        {spec.version}",
        f"Release:        {spec.release}%{{?dist}}",
        f"Summary:        {spec.summary}",
        f"License:        {spec.license_tag}",
        f"BuildArch:      {spec.arch}",
        "",
    ]

    for i, src in enumerate(spec.sources):
        lines.append(f"Source{i}:        {Path(src).name}")
    if spec.sources:
        lines.append("")

    for req in spec.requires:
        lines.append(f"Requires:       {req}")
    for prov in spec.provides:
        lines.append(f"Provides:       {prov}")
    for conf in spec.conflicts:
        lines.append(f"Conflicts:      {conf}")
    if spec.requires or spec.provides or spec.conflicts:
        lines.append("")

    lines += [
        "%description",
        spec.description,
        "",
        "%prep",
        "%setup -q",
        "",
        "%build",
        "",
        "%install",
        "rm -rf %{buildroot}",
        "mkdir -p %{buildroot}",
        'tar -xf %{SOURCE0} -C "%{buildroot}/" --strip-components=1',
        "",
    ]

    if spec.pre_install:
        lines += ["%pre", spec.pre_install, ""]
    if spec.post_install:
        lines += ["%post", spec.post_install, ""]
    if spec.pre_uninstall:
        lines += ["%preun", spec.pre_uninstall, ""]

    lines += ["%files", "%defattr(-,root,root,-)"]
    lines.extend(spec.files)
    lines.append("")

    if spec.changelog:
        lines.append("%changelog")
        for date, author, msg in spec.changelog:
            lines.append(f"* {date} {author}")
            lines.append(f"  - {msg}")
        lines.append("")

    return "\n".join(lines)


def create_kernel_image_spec(kernel_version: str) -> PackageSpec:
    today = datetime.date.today().strftime("%a %b %d %Y")
    return PackageSpec(
        name="kernel-image-prototype",
        version=kernel_version.replace("-", "_"),
        release="1",
        summary=f"Pre-built kernel image {kernel_version} for prototype wireless platform",
        description=textwrap.dedent(f"""\
            Linux kernel image built for next-generation wireless prototype systems.
            Includes PCIe high-speed data transfer support, real-time scheduling
            patches, and optimized NUMA affinity for multi-processor platforms.
            Kernel version: {kernel_version}
        """).strip(),
        arch="x86_64",
        requires=["glibc >= 2.17", "kmod", "grub2-tools"],
        conflicts=["kernel-image-prototype < " + kernel_version.replace("-", "_")],
        post_install=textwrap.dedent("""\
            if [ "$1" -ge 1 ]; then
                /sbin/depmod -a "$RPM_INSTALL_PREFIX/lib/modules/%{version}" || true
                grub2-mkconfig -o /boot/grub2/grub.cfg 2>/dev/null || true
            fi
        """).strip(),
        pre_uninstall=textwrap.dedent("""\
            if [ "$1" = "0" ]; then
                /sbin/depmod -a || true
            fi
        """).strip(),
        files=[
            f"/boot/vmlinuz-{kernel_version}",
            f"/boot/initramfs-{kernel_version}.img",
            f"/boot/config-{kernel_version}",
            f"/boot/System.map-{kernel_version}",
            f"/lib/modules/{kernel_version}/",
        ],
        changelog=[(today, "Gerard Recinto <gerardrecinto@example.com>",
                    f"Build kernel {kernel_version} with PCIe + RT patches")],
    )


def create_driver_spec(driver_name: str, version: str, kernel_version: str) -> PackageSpec:
    today = datetime.date.today().strftime("%a %b %d %Y")
    return PackageSpec(
        name=f"kmod-{driver_name}",
        version=version,
        release="1",
        summary=f"{driver_name} kernel module for high-speed PCIe data transfer",
        description=textwrap.dedent(f"""\
            Kernel module providing {driver_name} support for PCIe-attached
            radio hardware on prototype wireless platforms.
            Built against kernel: {kernel_version}
        """).strip(),
        arch="x86_64",
        requires=[f"kernel-image-prototype = {kernel_version}", "kmod"],
        post_install=f"/sbin/depmod -a {kernel_version} || true",
        files=[
            f"/lib/modules/{kernel_version}/extra/{driver_name}.ko",
            f"/etc/modules-load.d/{driver_name}.conf",
        ],
        changelog=[(today, "Gerard Recinto <gerardrecinto@example.com>",
                    f"Initial build of {driver_name} {version}")],
    )


def compute_tarball_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def setup_rpmbuild_tree(topdir: str) -> None:
    for d in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        os.makedirs(f"{topdir}/{d}", exist_ok=True)


def build_rpm(spec_content: str, sources: list[str], output_dir: str,
              topdir: Optional[str] = None) -> list[str]:
    """
    Build RPM from spec + sources. Returns paths of built RPMs.
    topdir: optional persistent rpmbuild tree (uses temp dir if None)
    """
    cleanup = topdir is None
    if topdir is None:
        topdir = tempfile.mkdtemp(prefix="rpmbuild_")

    try:
        setup_rpmbuild_tree(topdir)

        spec_path = f"{topdir}/SPECS/package.spec"
        Path(spec_path).write_text(spec_content)

        for src in sources:
            src_p = Path(src)
            if src_p.exists():
                shutil.copy2(str(src_p), f"{topdir}/SOURCES/{src_p.name}")

        macros = f"_topdir {topdir}"
        cmd = ["rpmbuild", f"--define={macros}", "-bb", spec_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"rpmbuild failed (exit {result.returncode}):\n{result.stderr}"
            )

        built: list[str] = []
        for root, _, files in os.walk(f"{topdir}/RPMS"):
            for fname in files:
                if fname.endswith(".rpm"):
                    src_rpm = os.path.join(root, fname)
                    dest = os.path.join(output_dir, fname)
                    os.makedirs(output_dir, exist_ok=True)
                    shutil.copy2(src_rpm, dest)
                    built.append(dest)
        return built

    finally:
        if cleanup:
            shutil.rmtree(topdir, ignore_errors=True)


def verify_rpm(rpm_path: str) -> bool:
    result = subprocess.run(["rpm", "-Kv", rpm_path], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def create_yum_repo(repo_dir: str) -> None:
    """Run createrepo_c to generate YUM repository metadata."""
    result = subprocess.run(
        ["createrepo_c", "--update", repo_dir], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"createrepo_c failed:\n{result.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RPM spec generator + build automation for Linux platform packages"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_kernel = sub.add_parser("kernel-spec", help="Generate kernel image RPM spec")
    p_kernel.add_argument("--kernel-version", required=True)
    p_kernel.add_argument("--output", default="kernel.spec")

    p_driver = sub.add_parser("driver-spec", help="Generate kernel module RPM spec")
    p_driver.add_argument("--driver-name", required=True)
    p_driver.add_argument("--version", required=True)
    p_driver.add_argument("--kernel-version", required=True)
    p_driver.add_argument("--output", default="driver.spec")

    p_verify = sub.add_parser("verify", help="Verify RPM package signatures + checksums")
    p_verify.add_argument("rpms", nargs="+")

    p_repo = sub.add_parser("create-repo", help="Create YUM repo metadata")
    p_repo.add_argument("repo_dir")

    args = parser.parse_args()

    if args.cmd == "kernel-spec":
        spec = create_kernel_image_spec(args.kernel_version)
        spec_str = generate_spec(spec)
        Path(args.output).write_text(spec_str)
        print(f"Spec written: {args.output}")

    elif args.cmd == "driver-spec":
        spec = create_driver_spec(args.driver_name, args.version, args.kernel_version)
        spec_str = generate_spec(spec)
        Path(args.output).write_text(spec_str)
        print(f"Spec written: {args.output}")

    elif args.cmd == "verify":
        failed = 0
        for rpm_path in args.rpms:
            if verify_rpm(rpm_path):
                print(f"OK: {rpm_path}")
            else:
                failed += 1
        sys.exit(1 if failed else 0)

    elif args.cmd == "create-repo":
        create_yum_repo(args.repo_dir)
        print(f"YUM repo metadata created: {args.repo_dir}")


if __name__ == "__main__":
    main()
