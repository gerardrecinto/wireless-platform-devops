"""Tests for monitor/sysperf.py: run without real /proc by patching reads."""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.sysperf import (
    CoreStats,
    MemStats,
    SampleSnapshot,
    detect_imbalance,
    format_snapshot,
)


def _make_snapshot(utils: list[float]) -> SampleSnapshot:
    cores = [CoreStats(core_id=i, util_pct=u, freq_mhz=3600.0, irq_count=i * 100)
             for i, u in enumerate(utils)]
    mem = MemStats(total_gb=32.0, used_gb=12.0, available_gb=20.0,
                   swap_used_gb=0.0, page_faults=0)
    snap = SampleSnapshot(timestamp=time.time(), cores=cores, mem=mem)
    snap.load_avg = (1.2, 1.0, 0.9)
    snap.context_switches = 5000
    return snap


class TestDetectImbalance:
    def test_no_imbalance_below_threshold(self):
        snap = _make_snapshot([50.0, 52.0, 48.0, 50.0])
        warnings = detect_imbalance(snap, threshold=30.0)
        assert warnings == []

    def test_detects_overloaded_core(self):
        snap = _make_snapshot([10.0, 10.0, 10.0, 95.0])
        warnings = detect_imbalance(snap, threshold=30.0)
        assert len(warnings) == 1
        assert "Core 3" in warnings[0]
        assert "95.0%" in warnings[0]

    def test_multiple_overloaded_cores(self):
        snap = _make_snapshot([5.0, 5.0, 90.0, 88.0])
        warnings = detect_imbalance(snap, threshold=30.0)
        assert len(warnings) == 2

    def test_empty_cores_no_crash(self):
        snap = _make_snapshot([])
        warnings = detect_imbalance(snap)
        assert warnings == []

    def test_all_equal_no_imbalance(self):
        snap = _make_snapshot([50.0] * 8)
        warnings = detect_imbalance(snap, threshold=30.0)
        assert warnings == []

    def test_custom_threshold(self):
        snap = _make_snapshot([20.0, 20.0, 20.0, 55.0])
        # default threshold=30 → mean=28.75, core3=55, delta=26.25 < 30 → no warning
        assert detect_imbalance(snap, threshold=30.0) == []
        # with threshold=20 → delta=26.25 > 20 → warning
        assert detect_imbalance(snap, threshold=20.0) != []


class TestFormatSnapshot:
    def test_contains_core_ids(self):
        snap = _make_snapshot([10.0, 90.0, 50.0, 50.0])
        output = format_snapshot(snap)
        assert "0" in output
        assert "1" in output

    def test_contains_load_avg(self):
        snap = _make_snapshot([50.0])
        output = format_snapshot(snap)
        assert "1.20" in output

    def test_contains_mem_stats(self):
        snap = _make_snapshot([50.0])
        output = format_snapshot(snap)
        assert "12.0G" in output
        assert "20.0G" in output

    def test_high_util_flagged(self):
        snap = _make_snapshot([10.0, 95.0])
        output = format_snapshot(snap)
        assert "!" in output

    def test_swap_warning_shown(self):
        snap = _make_snapshot([50.0])
        snap.mem.swap_used_gb = 2.5
        output = format_snapshot(snap)
        assert "WARN" in output or "Swap" in output

    def test_no_swap_warning_when_zero(self):
        snap = _make_snapshot([50.0])
        snap.mem.swap_used_gb = 0.0
        output = format_snapshot(snap)
        assert "Swap" not in output


class TestMemStats:
    def test_page_faults_shown(self):
        snap = _make_snapshot([50.0])
        snap.mem.page_faults = 42
        output = format_snapshot(snap)
        assert "42" in output
