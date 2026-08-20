"""Tests for monitor/netdiag.py: pure logic only, no real /proc or /sys access."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.netdiag import (
    InterfaceStats,
    NetReport,
    _decode_route_flags,
    _hex_to_ip,
    check_error_spikes,
    format_report,
)


def _make_iface(name="eth0", rx_err=0, tx_err=0, rx_drop=0, tx_drop=0):
    return InterfaceStats(
        name=name,
        state="up",
        mtu=1500,
        driver="ixgbe",
        rx_bytes=1_000_000,
        tx_bytes=500_000,
        rx_errors=rx_err,
        tx_errors=tx_err,
        rx_dropped=rx_drop,
        tx_dropped=tx_drop,
    )


class TestHexToIp:
    def test_decodes_little_endian_hex(self):
        # 0100000A little-endian == 10.0.0.1
        assert _hex_to_ip("0100000A") == "10.0.0.1"

    def test_zero_route(self):
        assert _hex_to_ip("00000000") == "0.0.0.0"

    def test_invalid_hex_returns_zero_route(self):
        assert _hex_to_ip("not-hex") == "0.0.0.0"


class TestDecodeRouteFlags:
    def test_up_flag(self):
        assert _decode_route_flags(0x1) == "U"

    def test_up_gateway_flags(self):
        flags = _decode_route_flags(0x1 | 0x2)
        assert "U" in flags
        assert "G" in flags

    def test_no_flags_returns_placeholder(self):
        assert _decode_route_flags(0x0) == "?"


class TestCheckErrorSpikes:
    def test_no_warnings_when_clean(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface()])
        assert check_error_spikes(report) == []

    def test_warns_on_errors(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(rx_err=5)])
        warnings = check_error_spikes(report)
        assert len(warnings) == 1
        assert "eth0" in warnings[0]

    def test_warns_on_drop_over_threshold(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(rx_drop=1500)])
        warnings = check_error_spikes(report)
        assert any("drops" in w for w in warnings)

    def test_no_warning_on_drop_below_threshold(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(rx_drop=100)])
        assert check_error_spikes(report) == []

    def test_loopback_ignored(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(name="lo", rx_err=5)])
        assert check_error_spikes(report) == []


class TestFormatReport:
    def test_contains_interface_name(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface()])
        output = format_report(report)
        assert "eth0" in output

    def test_loopback_excluded_from_table(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(name="lo")])
        output = format_report(report)
        assert "lo   " not in output

    def test_warnings_section_shown_on_errors(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface(rx_err=3)])
        output = format_report(report)
        assert "WARNINGS" in output

    def test_no_warnings_section_when_clean(self):
        report = NetReport(timestamp=time.time(), interfaces=[_make_iface()])
        output = format_report(report)
        assert "WARNINGS" not in output
