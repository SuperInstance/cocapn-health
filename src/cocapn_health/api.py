"""REST API endpoint for cocapn-health.

Provides a lightweight HTTP API for querying health status.
Uses only stdlib — no dependencies required.

Usage:
    from cocapn_health.api import run_api
    run_api(host="0.0.0.0", port=8902)

Or via CLI:
    cocapn-health --serve 8902
"""
from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from cocapn_health import (
    HealthChecker, ServiceDef, CheckResult, FLEET_SERVICES,
    check_system, check_tcp, check_dns, check_http, check_disk, check_memory, check_cpu,
)


class HealthCache:
    """Cache health results with TTL to avoid hammering services."""

    def __init__(self, ttl: float = 30.0):
        self._ttl = ttl
        self._fleet_results: List[CheckResult] = []
        self._system_results: List[CheckResult] = []
        self._last_fleet: float = 0.0
        self._last_system: float = 0.0
        self._lock = threading.Lock()
        self._services = FLEET_SERVICES

    def set_services(self, services: List[ServiceDef]) -> None:
        self._services = services

    def get_fleet(self) -> List[CheckResult]:
        now = time.time()
        with self._lock:
            if now - self._last_fleet > self._ttl or not self._fleet_results:
                checker = HealthChecker(self._services)
                self._fleet_results = checker.check_all()
                self._last_fleet = now
            return self._fleet_results

    def get_system(self) -> List[CheckResult]:
        now = time.time()
        with self._lock:
            if now - self._last_system > self._ttl or not self._system_results:
                self._system_results = check_system()
                self._last_system = now
            return self._system_results

    def force_refresh(self) -> None:
        with self._lock:
            self._last_fleet = 0.0
            self._last_system = 0.0

    @property
    def last_fleet_check(self) -> float:
        return self._last_fleet

    @property
    def last_system_check(self) -> float:
        return self._last_system


def _results_to_dict(results: List[CheckResult]) -> List[Dict[str, Any]]:
    return [
        {
            "name": r.name,
            "ok": r.ok,
            "status": r.status,
            "latency_ms": r.latency_ms,
            "details": r.details,
            "checked_at": r.checked_at,
        }
        for r in results
    ]


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health API."""
    cache: HealthCache  # set by run_api

    def log_message(self, format, *args):
        pass  # suppress default logging

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        if path == "/" or path == "/health":
            # Combined status
            fleet = self.cache.get_fleet()
            system = self.cache.get_system()
            all_results = fleet + system
            up = sum(1 for r in all_results if r.ok)
            self._send_json({
                "status": "ok" if all(r.ok for r in all_results) else "degraded",
                "summary": {
                    "total": len(all_results),
                    "up": up,
                    "down": len(all_results) - up,
                    "fleet": len(fleet),
                    "system": len(system),
                },
                "fleet": _results_to_dict(fleet),
                "system": _results_to_dict(system),
            })

        elif path == "/fleet":
            results = self.cache.get_fleet()
            up = sum(1 for r in results if r.ok)
            self._send_json({
                "summary": {"total": len(results), "up": up, "down": len(results) - up},
                "services": _results_to_dict(results),
            })

        elif path == "/system":
            results = self.cache.get_system()
            self._send_json({
                "checks": _results_to_dict(results),
            })

        elif path == "/check/tcp":
            host = params.get("host", ["127.0.0.1"])[0]
            port = int(params.get("port", ["80"])[0])
            result = check_tcp(host, port)
            self._send_json(_results_to_dict([result])[0])

        elif path == "/check/dns":
            hostname = params.get("host", ["localhost"])[0]
            result = check_dns(hostname)
            self._send_json(_results_to_dict([result])[0])

        elif path == "/check/http":
            url = params.get("url", ["http://localhost"])[0]
            result = check_http(url)
            self._send_json(_results_to_dict([result])[0])

        elif path == "/check/disk":
            path_arg = params.get("path", ["/"])[0]
            result = check_disk(path_arg)
            self._send_json(_results_to_dict([result])[0])

        elif path == "/check/memory":
            result = check_memory()
            self._send_json(_results_to_dict([result])[0])

        elif path == "/check/cpu":
            result = check_cpu()
            self._send_json(_results_to_dict([result])[0])

        elif path == "/refresh":
            self.cache.force_refresh()
            self._send_json({"status": "cache cleared", "message": "Next request will perform fresh checks."})

        else:
            self._send_json({"error": "not found", "available_endpoints": [
                "/", "/health", "/fleet", "/system",
                "/check/tcp?host=x&port=y", "/check/dns?host=x",
                "/check/http?url=x", "/check/disk?path=x",
                "/check/memory", "/check/cpu", "/refresh",
            ]}, status=404)


def run_api(host: str = "0.0.0.0", port: int = 8902, ttl: float = 30.0,
            services: Optional[List[ServiceDef]] = None) -> None:
    """Start the health API server."""
    cache = HealthCache(ttl=ttl)
    if services:
        cache.set_services(services)
    HealthHandler.cache = cache

    server = HTTPServer((host, port), HealthHandler)
    print(f"cocapn-health API listening on {host}:{port} (cache TTL: {ttl}s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down health API.")
        server.shutdown()
