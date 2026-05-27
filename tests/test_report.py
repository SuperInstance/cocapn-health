"""Tests for cocapn_health.report — HealthReport generation."""
import json
from unittest.mock import patch

import pytest

from cocapn_health import CheckResult, ServiceDef
from cocapn_health.alert import AlertManager, AlertRule, AlertSeverity, is_down
from cocapn_health.monitor import HealthMonitor, HealthStatus
from cocapn_health.report import HealthReport


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


class TestHealthReportManual:
    def test_basic_report(self):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            total_services=3,
            services_up=3,
            services_down=0,
        )
        assert report.status == HealthStatus.HEALTHY
        assert report.total_services == 3

    def test_to_dict(self):
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            total_services=5,
            services_up=3,
            services_down=2,
            failing=["svc-a", "svc-b"],
        )
        d = report.to_dict()
        assert d["status"] == "degraded"
        assert d["services_up"] == 3
        assert d["services_down"] == 2
        assert "svc-a" in d["failing"]

    def test_to_json(self):
        report = HealthReport(status=HealthStatus.HEALTHY, total_services=1, services_up=1)
        j = report.to_json()
        data = json.loads(j)
        assert data["status"] == "healthy"

    def test_to_markdown_healthy(self):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            total_services=3,
            services_up=3,
            services_down=0,
            agent_summaries=[
                {"name": "svc-a", "last_ok": True, "availability": 100.0,
                 "avg_latency_ms": 12.0, "consecutive_failures": 0},
            ],
        )
        md = report.to_markdown()
        assert "HEALTHY" in md
        assert "🟢" in md

    def test_to_markdown_with_failures(self):
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            total_services=3,
            services_up=2,
            services_down=1,
            failing=["svc-b"],
        )
        md = report.to_markdown()
        assert "⚠️ Failing" in md
        assert "svc-b" in md

    def test_to_markdown_with_alerts(self):
        report = HealthReport(
            status=HealthStatus.UNHEALTHY,
            total_services=1,
            services_up=0,
            services_down=1,
            failing=["svc-x"],
            alerts=[{"severity": "critical", "message": "svc-x is down", "rule_name": "down"}],
        )
        md = report.to_markdown()
        assert "🚨 Active Alerts" in md
        assert "CRITICAL" in md

    def test_to_oneline_healthy(self):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            total_services=3,
            services_up=3,
            services_down=0,
        )
        line = report.to_oneline()
        assert "✅" in line
        assert "HEALTHY" in line

    def test_to_oneline_degraded(self):
        report = HealthReport(
            status=HealthStatus.DEGRADED,
            total_services=5,
            services_up=3,
            services_down=2,
            failing=["a", "b"],
            alerts=[{"severity": "warning"}, {"severity": "warning"}],
        )
        line = report.to_oneline()
        assert "⚠️" in line
        assert "DEGRADED" in line
        assert "2 alerts" in line

    def test_to_oneline_unhealthy(self):
        report = HealthReport(
            status=HealthStatus.UNHEALTHY,
            total_services=2,
            services_up=0,
            services_down=2,
        )
        line = report.to_oneline()
        assert "🔴" in line
        assert "UNHEALTHY" in line

    def test_to_markdown_with_system_checks(self):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            total_services=1,
            services_up=1,
            system_checks=[
                {"name": "cpu", "last_ok": True, "last_status": "OK | load 0.5"},
                {"name": "memory", "last_ok": True, "last_status": "OK | 45.2% available"},
            ],
        )
        md = report.to_markdown()
        assert "System Checks" in md
        assert "cpu" in md
        assert "memory" in md


class TestHealthReportFromMonitor:
    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_up)
    def test_from_monitor_healthy(self, mock_urlopen):
        monitor = HealthMonitor(make_services(3))
        monitor.check()
        report = HealthReport.from_monitor(monitor)
        assert report.status == HealthStatus.HEALTHY
        assert report.total_services == 3
        assert report.services_up == 3
        assert report.services_down == 0
        assert len(report.agent_summaries) == 3

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_down)
    def test_from_monitor_unhealthy(self, mock_urlopen):
        monitor = HealthMonitor(make_services(2))
        monitor.check()
        report = HealthReport.from_monitor(monitor)
        assert report.status == HealthStatus.UNHEALTHY
        assert report.services_down == 2
        assert len(report.failing) == 2

    @patch("urllib.request.urlopen", side_effect=_mock_urlopen_down)
    def test_from_monitor_with_alerts(self, mock_urlopen):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down, AlertSeverity.CRITICAL))

        monitor = HealthMonitor(make_services(2))
        monitor.check()

        mgr.evaluate(monitor.agent_states)
        report = HealthReport.from_monitor(monitor, alert_manager=mgr)
        assert len(report.alerts) == 2
        assert all(a["severity"] == "critical" for a in report.alerts)
