#!/bin/bash
# Set IRQ CPU affinity for PCIe NIC interrupts.
# Pins NIC IRQs to isolated CPUs to prevent interrupt latency jitter
# on real-time wireless prototype workloads.
# Must run as root. Safe to re-run (idempotent).

set -euo pipefail

ISOLATED_CPUS="${ISOLATED_CPUS:-4,5,6,7}"
LOG_FILE="${LOG_FILE:-/var/log/platform/irq_affinity.log}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"; }

mkdir -p "$(dirname "${LOG_FILE}")"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Must run as root" >&2; exit 1
fi

# Convert comma-separated CPU list to hex bitmask
cpu_list_to_mask() {
    local list="$1"
    local mask=0
    IFS=',' read -ra cpus <<< "$list"
    for cpu in "${cpus[@]}"; do
        mask=$(( mask | (1 << cpu) ))
    done
    printf '%x\n' "$mask"
}

AFFINITY_MASK=$(cpu_list_to_mask "${ISOLATED_CPUS}")
log "Target CPUs: ${ISOLATED_CPUS}  mask: 0x${AFFINITY_MASK}"

# Find IRQs belonging to PCIe network devices
NIC_IRQS=()
while IFS= read -r iface; do
    [[ "$iface" == "lo" ]] && continue
    dev_link="/sys/class/net/${iface}/device"
    [[ ! -e "$dev_link" ]] && continue
    real=$(readlink -f "$dev_link")
    [[ "$real" != *pci* ]] && continue

    # IRQs for this PCI device appear in /proc/irq/*/affinity_hint
    pci_addr=$(basename "$real")
    while IFS= read -r irq_dir; do
        irq=$(basename "$irq_dir")
        hint_file="${irq_dir}/affinity_hint"
        [[ ! -f "$hint_file" ]] && continue
        if grep -qr "${pci_addr}" "${irq_dir}/" 2>/dev/null || \
           ls "/sys/kernel/irq/${irq}/actions" 2>/dev/null | grep -q "$iface"; then
            NIC_IRQS+=("$irq")
        fi
    done < <(find /proc/irq -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
done < <(ls /sys/class/net/)

if [[ ${#NIC_IRQS[@]} -eq 0 ]]; then
    log "No PCIe NIC IRQs found; checking all network-related IRQs"
    # Fall back: pin all IRQs with "eth" or "enp" in name
    while IFS= read -r irq; do
        name_file="/proc/irq/${irq}/actions"
        [[ ! -f "$name_file" ]] && continue
        if grep -qE "eth|enp|mlx|ixgbe|igb" "$name_file" 2>/dev/null; then
            NIC_IRQS+=("$irq")
        fi
    done < <(ls /proc/irq/)
fi

log "Setting affinity for ${#NIC_IRQS[@]} IRQs -> CPUs ${ISOLATED_CPUS}"
PINNED=0
FAILED=0
for irq in "${NIC_IRQS[@]}"; do
    aff_file="/proc/irq/${irq}/smp_affinity"
    if [[ -w "$aff_file" ]]; then
        echo "${AFFINITY_MASK}" > "$aff_file"
        log "  IRQ ${irq}: affinity set to 0x${AFFINITY_MASK}"
        (( PINNED++ )) || true
    else
        log "  IRQ ${irq}: not writable (may need isolcpus kernel param)"
        (( FAILED++ )) || true
    fi
done

log "Done: ${PINNED} pinned, ${FAILED} skipped"
exit 0
