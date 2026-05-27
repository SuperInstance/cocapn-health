"""Tests for cocapn_health.monitor — HealthMonitor, AgentState, HealthStatus."""
from unittest.mock import patch

import pytest

from cocapn_health import CheckResult, ServiceDef
from cocapn_health.monitor import AgentState, HealthMonitor, HealthStatus

# ── Helpers ───────────────────────────────────────────────────────

def _mock_urlopen_up(*args, **kwargs):
    class MockResp:
        status = 200
        def read(self, n=-1):
            return b'{"ok": true}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    return MockResp()


def _mock_urlopen_down(*args, **kwargs):
    raise OSError("Connection refused")


def make_services(n=3):
    return [ServiceDef(f"svc-{i}", "127.0.0.1", 4000 + i, "/status", timeout=0.1) for i in range(n)]


# ── AgentState ────────────────────────────────────────────────────

class TestAgentState:
    def test_initial_state(self):
        state = AgentState(name="test")
        assert state.last_ok is None
        assert state.consecutive_failures == 0
        assert state.consecutive_successes == 0
        assert state.total_checks == 0
        assert state.availability == 0.0
        assert state.avg_latency_ms == 0.0

    def test_update_success(self):
        state = AgentState(name="test")
        state.update(CheckResult("test", True, 10.0, "UP"))
        assert state.last_ok is True
        assert state.consecutive_successes == 1
        assert state.consecutive_failures == 0
        assert state.total_checks == 1
        assert state.availability == 100.0

    def test_update_failure(self):
        state = AgentState(name="test")
        state.update(CheckResult("test", False, 0.0, "DOWN"))
        assert state.last_ok is False
        assert state.consecutive_failures == 1
        assert state.consecutive_successes == 0
        assert state.total_failures == 1

    def test_mixed_updates(self):
        state = AgentState(name="test")
        state.update(CheckResult("test", True, 5.0, "UP"))
        state.update(CheckResult("test", True, 8.0, "UP"))
        state.update(CheckResult("test", False, 0.0, "DOWN"))
        assert state.total_checks == 3
        assert state.total_failures == 1
        assert state.availability == pytest.approx(66.67, rel=0.01)
        assert state.consecutive_failures == 1
        assert state.consecutive_successes == 0

    def test_history_capped_at_100(self):
        state = AgentState(name="test")
        for i in range(150):
            state.update(CheckResult("test", True, float(i), "UP"))
        assert len(state.history) == 100

    def test_avg_latency(self):
        state = AgentState(name="test")
        state.update(CheckResult("test", True, 10.0, "UP"))
        state.update(CheckResult("test", True, 20.0, "UP"))
        state.update(CheckResult("test", True, 30.0, "UP"))
        assert state.avg_latency_ms == 20.0

    def test_to_dict(self):
        state = AgentState(name="test")
        state.update(CheckResult("test", True, 5.0, "UP"))
        d = state.to_dict()
        assert d["name"] == "test"
        assert d["last_ok"] is True
        assert d["availability"] == 100.0
        assert "avg_latency_ms" in d


# ── HealthMonitor ─────────────────────────────────────────────────

class TestHealthMonitor:
    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_check_all_up(self, mock_urlopen):
        monitor = HealthMonitor(make_services(3))
        results = monitor.check()
        assert len(results) == 3
        assert all(r.ok for r in results)
        assert monitor.overall_status == HealthStatus.HEALTHY

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_down)
    def test_check_all_down(self, mock_urlopen):
        monitor = HealthMonitor(make_services(3))
        results = monitor.check()
        assert all(not r.ok for r in results)
        assert monitor.overall_status == HealthStatus.UNHEALTHY

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_check_count_increments(self, mock_urlopen):
        monitor = HealthMonitor(make_services(2))
        assert monitor.check_count == 0
        monitor.check()
        assert monitor.check_count == 1
        monitor.check()
        assert monitor.check_count == 2

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_agent_states_populated(self, mock_urlopen):
        monitor = HealthMonitor(make_services(2))
        monitor.check()
        states = monitor.agent_states
        assert len(states) == 2
        assert "svc-0" in states
        assert "svc-1" in states
        assert states["svc-0"].last_ok is True

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_down)
    def test_failing_agents(self, mock_urlopen):
        monitor = HealthMonitor(make_services(3))
        monitor.check()
        assert len(monitor.failing_agents) == 3
        assert "svc-0" in monitor.failing_agents

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_summary(self, mock_urlopen):
        monitor = HealthMonitor(make_services(2))
        monitor.check()
        s = monitor.summary
        assert s["status"] == "healthy"
        assert s["up"] == 2
        assert s["down"] == 0
        assert s["total_services"] == 2
        assert s["check_count"] == 1

    def test_empty_services_is_healthy(self):
        monitor = HealthMonitor([])
        assert monitor.overall_status == HealthStatus.HEALTHY

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_degraded_threshold(self, mock_urlopen):
        """With 3 services, 1 failing means 2/3 up = 0.67 which is >= 0.5 (healthy)."""
        services = make_services(3)
        monitor = HealthMonitor(services, degraded_threshold=0.8)
        monitor.check()  # All up
        # Force one to fail
        monitor._agent_states["svc-0"].update(
            CheckResult("svc-0", False, 0.0, "DOWN")
        )
        # 2/3 = 0.67 < 0.8 threshold → degraded
        assert monitor.overall_status == HealthStatus.DEGRADED

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_unhealthy_threshold(self, mock_urlopen):
        services = make_services(3)
        monitor = HealthMonitor(services, unhealthy_threshold=0.5)
        # Force 2 of 3 to fail
        monitor._agent_states["svc-0"].update(CheckResult("svc-0", False, 0.0, "DOWN"))
        monitor._agent_states["svc-1"].update(CheckResult("svc-1", False, 0.0, "DOWN"))
        # 1/3 = 0.33 < 0.5 → unhealthy
        assert monitor.overall_status == HealthStatus.UNHEALTHY


# ── HealthStatus enum ─────────────────────────────────────────────

class TestHealthStatus:
    def test_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_string_comparison(self):
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
