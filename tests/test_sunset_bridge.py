"""Tests for cocapn-health → sunset-ecosystem EventBus bridge.

Run: pytest tests/test_sunset_bridge.py -v
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from cocapn_health import CheckResult, ServiceDef
from cocapn_health.sunset_bridge import (
    EventBusHealthChecker,
    _thermal_snapshot,
    _HAS_BUS,
)


# ── Helpers ───────────────────────────────────────────────────────

def _mock_urlopen_down(*args, **kwargs):
    """Simulate a connection refused / service down."""
    raise OSError("Connection refused")


def _mock_urlopen_up(*args, **kwargs):
    """Simulate a healthy service."""
    class MockResp:
        status = 200
        def read(self, n=-1):
            return b'{"rooms": 8}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    return MockResp()


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_bus():
    """Return a mock FleetEventBus."""
    bus = MagicMock()
    bus.emit = MagicMock()
    return bus


@pytest.fixture
def services():
    return [
        ServiceDef("MUD", "localhost", 4042, "/status", timeout=0.1),
        ServiceDef("Arena", "localhost", 4044, "/stats", timeout=0.1),
    ]


# ═══════════════════════════════════════════════════════════════════
# 1. Event emission on state transitions
# ═══════════════════════════════════════════════════════════════════

class TestStateTransitions:
    """service_down and service_recovered fire only on transitions."""

    def test_first_check_down_emits_service_down(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)

        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            checker.check_all()

        # emit is now called with {"type": event_type, **payload}
        calls = [c for c in mock_bus.emit.call_args_list
                 if c.args and c.args[0].get("type") == "service_down"]
        assert len(calls) == 2, "Both services should emit service_down on first check"
        assert calls[0].args[0]["service"] == "MUD"
        assert calls[1].args[0]["service"] == "Arena"

    def test_first_check_up_does_not_emit(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)

        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()

        mock_bus.emit.assert_not_called()

    def test_down_to_up_emits_service_recovered(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)

        # First check: DOWN
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            checker.check_all()
        down_calls = [c for c in mock_bus.emit.call_args_list
                      if c.args and c.args[0].get("type") == "service_down"]
        assert len(down_calls) == 2

        # Second check: UP
        mock_bus.emit.reset_mock()
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()

        recovered = [c for c in mock_bus.emit.call_args_list
                   if c.args and c.args[0].get("type") == "service_recovered"]
        assert len(recovered) == 2

    def test_up_to_down_emits_service_down(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)

        # First: UP
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()
        mock_bus.emit.reset_mock()

        # Second: DOWN
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            checker.check_all()

        down = [c for c in mock_bus.emit.call_args_list
                if c.args and c.args[0].get("type") == "service_down"]
        assert len(down) == 2

    def test_no_emit_when_state_unchanged(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)

        # Check twice, both UP
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()
        mock_bus.emit.reset_mock()
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()

        mock_bus.emit.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# 2. Thermal metrics in events
# ═══════════════════════════════════════════════════════════════════

class TestThermalMetrics:
    """Thermal snapshot is included in every emitted event."""

    def test_service_down_includes_thermal(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            checker.check_all()

        payload = mock_bus.emit.call_args_list[0].args[0]
        assert "thermal" in payload
        assert "timestamp" in payload["thermal"]

    def test_thermal_snapshot_has_basic_fields(self):
        snap = _thermal_snapshot()
        assert "timestamp" in snap
        assert isinstance(snap, dict)


# ═══════════════════════════════════════════════════════════════════
# 3. Graceful degradation
# ═══════════════════════════════════════════════════════════════════

class TestGracefulDegradation:
    """Bridge works without sunset-ecosystem installed."""

    def test_no_bus_no_crash(self, services):
        checker = EventBusHealthChecker(services, bus=None)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            results = checker.check_all()
        assert len(results) == 2

    def test_bus_without_emit_no_crash(self, services):
        bus = MagicMock()
        del bus.emit  # no emit method
        checker = EventBusHealthChecker(services, bus=bus)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            results = checker.check_all()
        assert len(results) == 2

    def test_emit_exception_is_non_fatal(self, mock_bus, services):
        mock_bus.emit.side_effect = RuntimeError("bus exploded")
        checker = EventBusHealthChecker(services, bus=mock_bus)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
            results = checker.check_all()
        assert len(results) == 2


# ═══════════════════════════════════════════════════════════════════
# 4. emit_on_every_check fleet_health snapshot
# ═══════════════════════════════════════════════════════════════════

class TestFleetHealthSnapshot:
    """emit_on_every_check sends a fleet_health summary."""

    def test_fleet_health_emitted_when_enabled(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus, emit_on_every_check=True)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()

        fleet = [c for c in mock_bus.emit.call_args_list
                 if c.args and c.args[0].get("type") == "fleet_health"]
        assert len(fleet) == 1
        payload = fleet[0].args[0]
        assert payload["total"] == 2
        assert payload["up"] == 2
        assert payload["down"] == 0
        assert "thermal" in payload

    def test_fleet_health_not_emitted_when_disabled(self, mock_bus, services):
        checker = EventBusHealthChecker(services, bus=mock_bus, emit_on_every_check=False)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            checker.check_all()

        fleet = [c for c in mock_bus.emit.call_args_list
                 if c.args and c.args[0].get("type") == "fleet_health"]
        assert len(fleet) == 0


# ═══════════════════════════════════════════════════════════════════
# 5. Non-regression: existing HealthChecker API intact
# ═══════════════════════════════════════════════════════════════════

class TestApiNotBroken:
    """All public HealthChecker methods still work."""

    def test_check_all_returns_results(self, services):
        checker = EventBusHealthChecker(services, bus=None)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            results = checker.check_all()
        assert isinstance(results, list)
        assert all(isinstance(r, CheckResult) for r in results)

    def test_report_still_works(self, services):
        checker = EventBusHealthChecker(services, bus=None)
        with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
            results = checker.check_all()
        report = checker.report(results, format="json")
        assert isinstance(report, str)
        data = json.loads(report)
        assert "summary" in data
