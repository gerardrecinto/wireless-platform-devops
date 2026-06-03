"""Tests for packages/build_rpm.py: spec generation logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from packages.build_rpm import (
    PackageSpec,
    create_driver_spec,
    create_kernel_image_spec,
    generate_spec,
)


class TestGenerateSpec:
    def _minimal_spec(self) -> PackageSpec:
        return PackageSpec(
            name="test-pkg",
            version="1.0.0",
            release="1",
            summary="Test package",
            description="Test description",
        )

    def test_name_version_present(self):
        spec = generate_spec(self._minimal_spec())
        assert "Name:           test-pkg" in spec
        assert "Version:        1.0.0" in spec
        assert "Release:        1%{?dist}" in spec

    def test_summary_present(self):
        spec = generate_spec(self._minimal_spec())
        assert "Summary:        Test package" in spec

    def test_requires_rendered(self):
        pkg = self._minimal_spec()
        pkg.requires = ["glibc >= 2.17", "kmod"]
        spec = generate_spec(pkg)
        assert "Requires:       glibc >= 2.17" in spec
        assert "Requires:       kmod" in spec

    def test_conflicts_rendered(self):
        pkg = self._minimal_spec()
        pkg.conflicts = ["old-package < 2.0"]
        spec = generate_spec(pkg)
        assert "Conflicts:      old-package < 2.0" in spec

    def test_post_install_rendered(self):
        pkg = self._minimal_spec()
        pkg.post_install = "/sbin/depmod -a"
        spec = generate_spec(pkg)
        assert "%post" in spec
        assert "/sbin/depmod -a" in spec

    def test_pre_uninstall_rendered(self):
        pkg = self._minimal_spec()
        pkg.pre_uninstall = "echo uninstalling"
        spec = generate_spec(pkg)
        assert "%preun" in spec

    def test_files_section_present(self):
        pkg = self._minimal_spec()
        pkg.files = ["/boot/vmlinuz-6.1", "/lib/modules/6.1/"]
        spec = generate_spec(pkg)
        assert "%files" in spec
        assert "/boot/vmlinuz-6.1" in spec
        assert "/lib/modules/6.1/" in spec

    def test_changelog_rendered(self):
        pkg = self._minimal_spec()
        pkg.changelog = [("Mon Jun 02 2026", "Test Author", "Initial build")]
        spec = generate_spec(pkg)
        assert "%changelog" in spec
        assert "Initial build" in spec

    def test_sources_rendered(self):
        pkg = self._minimal_spec()
        pkg.sources = ["/tmp/mypackage-1.0.tar.gz"]
        spec = generate_spec(pkg)
        assert "Source0:" in spec
        assert "mypackage-1.0.tar.gz" in spec


class TestKernelImageSpec:
    def test_name_contains_prototype(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        assert spec.name == "kernel-image-prototype"

    def test_version_sanitized(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        # hyphens become underscores for RPM version compliance
        assert "-" not in spec.version

    def test_requires_kmod(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        assert any("kmod" in r for r in spec.requires)

    def test_post_install_runs_depmod(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        assert "depmod" in spec.post_install

    def test_files_include_boot_paths(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        assert any("/boot/vmlinuz" in f for f in spec.files)
        assert any("/lib/modules" in f for f in spec.files)

    def test_description_mentions_pcie(self):
        spec = create_kernel_image_spec("6.1.80-rt27")
        assert "PCIe" in spec.description


class TestDriverSpec:
    def test_name_includes_driver(self):
        spec = create_driver_spec("ixgbe", "5.20.3", "6.1.80-rt27")
        assert "ixgbe" in spec.name

    def test_requires_kernel_image(self):
        spec = create_driver_spec("ixgbe", "5.20.3", "6.1.80-rt27")
        assert any("kernel-image-prototype" in r for r in spec.requires)

    def test_files_include_ko(self):
        spec = create_driver_spec("ixgbe", "5.20.3", "6.1.80-rt27")
        assert any(".ko" in f for f in spec.files)

    def test_post_install_runs_depmod(self):
        spec = create_driver_spec("ixgbe", "5.20.3", "6.1.80-rt27")
        assert "depmod" in spec.post_install
