"""Tests for cocapn-health."""

import json

from cocapn_health import CheckResult, HealthChecker, ServiceDef


def test_check_local_service():
    """Check a known-up service (httpbin or similar)."""
    # Use a public test endpoint
    svc = ServiceDef("httpbin", "httpbin.org", 80, "/get", timeout=10)
    checker = HealthChecker([svc])
    result = checker.check_one(svc)
    assert result.ok
    assert result.latency_ms > 0


def test_check_down_service():
    """Check a definitely-down port."""
    svc = ServiceDef("fake", "127.0.0.1", 59999, "/", timeout=1)
    checker = HealthChecker([svc])
    result = checker.check_one(svc)
    assert not result.ok
    assert "DOWN" in result.status


def test_report_json():
    results = [
        CheckResult("svc1", True, 12.3, "UP | HTTP 200"),
        CheckResult("svc2", False, 5000.0, "DOWN | timeout"),
    ]
    report = HealthChecker.report(results, format="json")
    data = json.loads(report)
    assert data["summary"]["up"] == 1
    assert data["summary"]["down"] == 1


def test_report_markdown():
    results = [
        CheckResult("svc1", True, 12.3, "UP | HTTP 200"),
        CheckResult("svc2", False, 5000.0, "DOWN | timeout"),
    ]
    report = HealthChecker.report(results, format="markdown")
    assert "Fleet Health Report" in report
    assert "🟢" in report
    assert "🔴" in report


def test_report_oneline():
    results = [
        CheckResult("svc1", True, 12.3, "UP | HTTP 200"),
        CheckResult("svc2", True, 45.0, "UP | HTTP 200"),
    ]
    report = HealthChecker.report(results, format="oneline")
    assert "2/2 up" in report
    assert "✅" in report
