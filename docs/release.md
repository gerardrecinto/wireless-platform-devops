# Release And Package Notes

This repo keeps the release path simple enough to inspect during an interview or
code review. The goal is to show the shape of the platform, not to ship private
vendor artifacts.

## Package Layout

| Package | Source | Output |
|---|---|---|
| Kernel image | `packages/build_rpm.py kernel-spec` | `kernel-image-prototype` RPM spec |
| PCIe driver | `packages/build_rpm.py driver-spec` | `kmod-<driver>` RPM spec |
| Diagnostics image | `containers/Dockerfile.dev` | Build/debug container |
| Runtime image | `containers/Dockerfile.rt` | Smaller runtime container |
| Kubernetes deploy | `containers/k8s/` | `wireless-prototype` manifests |

## Release Checklist

1. Run unit tests in the project venv.
2. Generate kernel and driver RPM specs for the target kernel.
3. Build RPMs on a RHEL-like builder with `rpmbuild`.
4. Publish RPMs to the internal YUM repository.
5. Build and tag diagnostic/runtime container images.
6. Apply Kubernetes manifests to the target prototype namespace.
7. Confirm node state with `sysperf.py` and `netdiag.py`.
8. Keep rollback simple: previous RPM, previous image tag, previous manifest.

## Capacity Assumption

For a 20M DAU product target, this layer should be designed for repeatability,
not hero debugging. That means deterministic packages, short deploy windows,
clear rollback, and diagnostics that work before the incident bridge starts.

This is a design target and tradeoff story. It is not a claim that this repo has
been load-tested to 20M DAU.
