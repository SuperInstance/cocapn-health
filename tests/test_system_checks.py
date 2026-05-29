"""Tests for system health checks: TCP, DNS, disk, memory, CPU."""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cocapn_health import (
    CheckResult,
    check_cpu,
    check_disk,
    check_dns,
    check_http,
    check_memory,
    check_system,
    check_tcp,
)

# ── TCP Check ──────────────────────────────────────────────────────


class _EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def http_server():
    """Spin up a tiny HTTP server for testing."""
    server = HTTPServer(("127.0.0.1", 0), _EchoHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    yield port
    server.shutdown()


def test_check_tcp_localhost(http_server):
    result = check_tcp("127.0.0.1", http_server, timeout=2.0)
    assert result.ok
    assert "UP" in result.status


def test_check_tcp_refused():
    # Pick a port that's almost certainly not listening
    result = check_tcp("127.0.0.1", 1, timeout=1.0)
    assert not result.ok
    assert "DOWN" in result.status


# ── DNS Check ──────────────────────────────────────────────────────


def test_check_dns_localhost():
    result = check_dns("localhost", timeout=5.0)
    assert result.ok
    assert "addresses" in result.details


def test_check_dns_bad():
    result = check_dns("this-domain-does-not-exist-xyz123.invalid", timeout=2.0)
    assert not result.ok


# ── HTTP Check ─────────────────────────────────────────────────────


def test_check_http_localhost(http_server):
    url = f"http://127.0.0.1:{http_server}/"
    result = check_http(url, timeout=2.0)
    assert result.ok
    assert result.details.get("status_code") == 200


def test_check_http_bad():
    result = check_http("http://127.0.0.1:1/", timeout=1.0)
    assert not result.ok


# ── Disk Check ─────────────────────────────────────────────────────


def test_check_disk_root():
    result = check_disk("/")
    assert result.ok
    assert "total_gb" in result.details
    assert result.details["free_gb"] > 0


def test_check_disk_bad_path():
    result = check_disk("/nonexistent/path/xyz")
    assert not result.ok


# ── Memory Check ───────────────────────────────────────────────────


def test_check_memory():
    result = check_memory()
    # May not work on all platforms but shouldn't crash
    assert isinstance(result, CheckResult)
    if result.ok:
        assert "available_mb" in result.details


# ── CPU Check ──────────────────────────────────────────────────────


def test_check_cpu():
    result = check_cpu(max_percent=200.0)
    assert isinstance(result, CheckResult)
    if hasattr(os, "getloadavg"):
        assert result.ok
        assert "load_1m" in result.details


# ── System Bundle ──────────────────────────────────────────────────


def test_check_system():
    results = check_system()
    assert len(results) == 3
    names = {r.name for r in results}
    assert "memory" in names
    assert "cpu" in names
