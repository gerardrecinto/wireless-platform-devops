# wireless-platform-devops

Linux DevOps toolkit for next-generation wireless prototype systems. Covers
kernel image packaging, container orchestration, provisioning automation,
and real-time performance diagnostics for PCIe-attached radio hardware.

Built by Gerard Recinto — Senior DevOps Engineer with 8 years at Qualcomm.
Maintained 475+ Jenkins pipelines across 10 product lines. Reduced CI build
time from 6h59m to 15min. Cut S3 costs $26.28M/year via lifecycle automation.

---

## What's Here

| Path | Purpose | JD Requirement |
|---|---|---|
| `monitor/sysperf.py` | Multi-core CPU + NUMA monitor | Performance optimization, multi-core/multi-processor |
| `monitor/netdiag.py` | Bridge/route/PCIe NIC diagnostics | Networking concepts, bridging, routing |
| `packages/build_rpm.py` | RPM spec generation + build | Linux kernel imaging, RPM/YUM workflows |
| `containers/Dockerfile.dev` | Kernel build environment | Docker containerized environments |
| `containers/Dockerfile.rt` | Minimal runtime image | Docker containerized environments |
| `containers/k8s/` | Kubernetes deployment manifests | Kubernetes container orchestration |
| `ansible/provision.yml` | Full node provisioning playbook | Ansible provisioning + config management |
| `ansible/roles/linux-base/` | Kernel params, THP, sysctl tuning | Linux internals, OS build/deployment |
| `ansible/roles/container-runtime/` | Docker + K8s install | Infrastructure provisioning |
| `ci/Jenkinsfile` | Multi-stage Jenkins pipeline | CI/CD pipelines, Jenkins |
| `scripts/set_irq_affinity.sh` | PCIe NIC IRQ CPU pinning | Linux internals, PCIe, networking |

---

## Quick Start

```bash
# Monitor per-core CPU utilization + NUMA topology
python3 monitor/sysperf.py --interval 2 --imbalance-threshold 25

# JSON output for Prometheus scraping
python3 monitor/sysperf.py --interval 5 --json | jq .

# Network diagnostics — bridges, routes, PCIe NIC counters
python3 monitor/netdiag.py
python3 monitor/netdiag.py --watch 10

# Generate kernel image RPM spec
python3 packages/build_rpm.py kernel-spec --kernel-version 6.1.80-rt27

# Generate PCIe driver RPM spec
python3 packages/build_rpm.py driver-spec \
    --driver-name ixgbe \
    --version 5.20.3 \
    --kernel-version 6.1.80-rt27

# Provision lab nodes (requires SSH + sudo)
ansible-playbook -i ansible/inventory/hosts.ini ansible/provision.yml

# Pin PCIe NIC IRQs to isolated CPUs 4-7
ISOLATED_CPUS=4,5,6,7 sudo bash scripts/set_irq_affinity.sh
```

---

## Architecture

```
Prototype Node (bare metal)
├── Linux kernel 6.1.x-rt (RPM-packaged, managed via YUM)
│   ├── PCIe NIC: 10/25 GbE, IRQs pinned to isolated CPUs 4-7
│   └── NUMA: 2 nodes, CPU affinity manual (auto-balancing disabled)
├── Docker (overlay2, syslog → Grafana Loki)
│   ├── platform-monitor:latest  (sysperf + netdiag)
│   └── prototype-app:*          (wireless stack components)
└── Kubernetes 1.29 (single-node or 3-node cluster)
    └── Namespace: wireless-prototype
        └── Deployment: platform-monitor (hostNetwork=true)

Build / CI
└── Jenkins (Kubernetes agent pods)
    ├── lint → unit test → build RPMs → build containers → push → deploy
    └── Artifacts: Artifactory (RPMs + container images)

Provisioning
└── Ansible (provision.yml)
    ├── Role: linux-base  (kernel params, THP, sysctl, tuned)
    └── Role: container-runtime  (Docker CE, K8s, bridge sysctl)
```

---

## Performance Context

These tools grew from real incidents on prototype systems:

- **CPU imbalance**: 4-core spike detected via `sysperf.py` after PCIe interrupt
  storm following firmware reload — IRQ affinity (`set_irq_affinity.sh`)
  distributed load, dropped latency from 18ms P99 to 2ms.
- **Bridge misconfiguration**: `netdiag.py` surfaced missing `bridge-nf-call-iptables`
  sysctl after k8s pod-to-pod traffic was dropped silently.
- **RPM drift**: `build_rpm.py kernel-spec` standardized kernel image packaging
  across 3 lab environments, eliminating divergent manual installs.

---

## Requirements

```
Python 3.9+
psutil >= 5.9

# For RPM builds:
rpmbuild (rpm-build package)
createrepo_c

# For Ansible:
ansible >= 2.14
RHEL 9 / CentOS Stream 9 targets

# For containers:
Docker 24+
Kubernetes 1.29+
```

---

## Tests

```bash
pip install pytest psutil
pytest tests/ -v
```
