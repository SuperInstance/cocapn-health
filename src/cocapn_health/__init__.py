"""cocapn_health — Lightweight fleet service health checker.

Maximum capability in minimum lines. Zero dependencies beyond stdlib.

Modules:
    cocapn_health           — Core check functions, HealthChecker, dataclasses
    cocapn_health.monitor   — HealthMonitor with status tracking over time
    cocapn_health.alert     — AlertManager with severity and escalation
    cocapn_health.report    — HealthReport with JSON/Markdown/oneline output
    cocapn_health.check     — Custom check registry and builder
    cocapn_health.api       — REST API server
    cocapn_health.cli       — Command-line interface
    cocapn_health.sunset_bridge — EventBus integration
"""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ServiceDef:
    """Service definition for health checking."""
    name: str
    host: str
    port: int
    path: str = "/"
    method: str = "GET"
    timeout: float = 5.0
    expect_status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    extract: dict[str, str] | None = None  # JSON keys to extract from response


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    ok: bool
    latency_ms: float
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Health Check Functions ──────────────────────────────────────────

def check_http(url: str, method: str = "GET", headers: dict[str, str] | None = None,
               timeout: float = 5.0, expect_status: int | None = None,
               extract: dict[str, str] | None = None) -> CheckResult:
    """Check an HTTP endpoint."""
    start = time.time()
    hdrs = headers or {}
    name = url

    try:
        req = urllib.request.Request(url, method=method, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = (time.time() - start) * 1000
            status_code = resp.status
            body = resp.read(2048).decode("utf-8", errors="replace")

            details: dict[str, Any] = {"status_code": status_code, "latency_ms": round(latency, 1)}
            try:
                data = json.loads(body)
                if extract:
                    for key, path in extract.items():
                        val = data
                        for part in path.split("."):
                            val = val.get(part, {}) if isinstance(val, dict) else None
                        details[key] = val
            except json.JSONDecodeError:
                details["body_preview"] = body[:100]

            if expect_status and status_code != expect_status:
                return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                                   status=f"HTTP {status_code} (expected {expect_status})", details=details)

            return CheckResult(name=name, ok=True, latency_ms=round(latency, 1),
                               status=f"UP | HTTP {status_code}", details=details)

    except urllib.error.HTTPError as e:
        latency = (time.time() - start) * 1000
        if e.code in (404, 400, 401):
            return CheckResult(name=name, ok=True, latency_ms=round(latency, 1),
                               status=f"UP | HTTP {e.code}", details={"status_code": e.code})
        return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | HTTP {e.code}", details={"status_code": e.code, "error": str(e)})
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | {type(e).__name__}", details={"error": str(e)})


def check_tcp(host: str, port: int, timeout: float = 5.0) -> CheckResult:
    """Check if a TCP port is reachable."""
    start = time.time()
    name = f"{host}:{port}"

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        latency = (time.time() - start) * 1000
        return CheckResult(name=name, ok=True, latency_ms=round(latency, 1),
                           status="UP | TCP connected", details={})
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | {type(e).__name__}", details={"error": str(e)})


def check_dns(hostname: str, timeout: float = 5.0) -> CheckResult:
    """Check DNS resolution."""
    start = time.time()
    try:
        socket.setdefaulttimeout(timeout)
        addrs = socket.getaddrinfo(hostname, None)
        latency = (time.time() - start) * 1000
        ips = list({addr[4][0] for addr in addrs})[:5]
        return CheckResult(name=hostname, ok=True, latency_ms=round(latency, 1),
                           status="UP | DNS resolved", details={"addresses": ips})
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=hostname, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | DNS failed: {type(e).__name__}", details={"error": str(e)})


def check_process(name: str) -> CheckResult:
    """Check if a process is running by name (uses pgrep)."""
    start = time.time()
    try:
        result = subprocess.run(["pgrep", "-c", name], capture_output=True, text=True, timeout=5)
        latency = (time.time() - start) * 1000
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return CheckResult(name=name, ok=True, latency_ms=round(latency, 1),
                               status=f"UP | {count} instances", details={"count": count})
        return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                           status="DOWN | not running", details={})
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | {type(e).__name__}", details={"error": str(e)})


def check_disk(path: str = "/", min_percent_free: float = 10.0) -> CheckResult:
    """Check disk space."""
    start = time.time()
    try:
        usage = shutil.disk_usage(path)
        latency = (time.time() - start) * 1000
        percent_free = (usage.free / usage.total) * 100
        ok = percent_free >= min_percent_free
        return CheckResult(name=path, ok=ok, latency_ms=round(latency, 1),
                           status=f"{'OK' if ok else 'LOW'} | {percent_free:.1f}% free",
                           details={
                               "total_gb": round(usage.total / (1024**3), 2),
                               "used_gb": round(usage.used / (1024**3), 2),
                               "free_gb": round(usage.free / (1024**3), 2),
                               "percent_free": round(percent_free, 1),
                           })
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=path, ok=False, latency_ms=round(latency, 1),
                           status=f"ERROR | {type(e).__name__}", details={"error": str(e)})


def check_memory(min_percent_free: float = 10.0) -> CheckResult:
    """Check system memory using /proc/meminfo (Linux) or vm_stat (macOS)."""
    start = time.time()
    try:
        if os.path.exists("/proc/meminfo"):
            info: dict[str, float] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        info[key] = float(parts[1])  # in kB
            total = info.get("MemTotal", 0) * 1024
            available = info.get("MemAvailable", info.get("MemFree", 0)) * 1024
        else:
            # Fallback: try vm_stat on macOS
            result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split("\n")
            info = {}
            for line in lines:
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = int(v.strip().rstrip("."))
            page_size = 4096
            total = info.get("Pages free", 0) * page_size + info.get("Pages active", 0) * page_size
            available = info.get("Pages free", 0) * page_size

        latency = (time.time() - start) * 1000
        if total == 0:
            return CheckResult(name="memory", ok=False, latency_ms=round(latency, 1),
                               status="ERROR | could not read memory", details={})

        percent_free = (available / total) * 100
        ok = percent_free >= min_percent_free
        return CheckResult(name="memory", ok=ok, latency_ms=round(latency, 1),
                           status=f"{'OK' if ok else 'LOW'} | {percent_free:.1f}% available",
                           details={
                               "total_mb": round(total / (1024**2), 1),
                               "available_mb": round(available / (1024**2), 1),
                               "percent_available": round(percent_free, 1),
                           })
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name="memory", ok=False, latency_ms=round(latency, 1),
                           status=f"ERROR | {type(e).__name__}", details={"error": str(e)})


def check_cpu(max_percent: float = 95.0) -> CheckResult:
    """Check CPU load average (Linux/macOS)."""
    start = time.time()
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        latency = (time.time() - start) * 1000
        utilization = (load1 / cpu_count) * 100
        ok = utilization < max_percent
        return CheckResult(name="cpu", ok=ok, latency_ms=round(latency, 1),
                           status=f"{'OK' if ok else 'HIGH'} | load {load1:.2f} ({utilization:.0f}%)",
                           details={
                               "load_1m": round(load1, 2),
                               "load_5m": round(load5, 2),
                               "load_15m": round(load15, 2),
                               "cpu_count": cpu_count,
                               "utilization_percent": round(utilization, 1),
                           })
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name="cpu", ok=False, latency_ms=round(latency, 1),
                           status=f"ERROR | {type(e).__name__}", details={"error": str(e)})


def check_system() -> list[CheckResult]:
    """Run all system-level checks: disk, memory, CPU."""
    return [check_disk(), check_memory(), check_cpu()]


# ── Fleet-Aware Checking ────────────────────────────────────────────

def check_fleet_service(service: ServiceDef) -> CheckResult:
    """Check a fleet service (HTTP by default)."""
    url = f"http://{service.host}:{service.port}{service.path}"
    start = time.time()

    try:
        req = urllib.request.Request(url, method=service.method, headers=service.headers)
        with urllib.request.urlopen(req, timeout=service.timeout) as resp:
            latency = (time.time() - start) * 1000
            status_code = resp.status
            body = resp.read(2048).decode("utf-8", errors="replace")

            details: dict[str, Any] = {"status_code": status_code, "latency_ms": round(latency, 1)}
            try:
                data = json.loads(body)
                if service.extract:
                    for key, path in service.extract.items():
                        val = data
                        for part in path.split("."):
                            val = val.get(part, {}) if isinstance(val, dict) else None
                        details[key] = val
                else:
                    for k in ["rooms", "tiles", "total_rules", "total_matches", "total_players",
                              "uptime_seconds", "total_drills", "streams"]:
                        if k in data:
                            details[k] = data[k]
            except json.JSONDecodeError:
                details["body_preview"] = body[:100]

            if service.expect_status and status_code != service.expect_status:
                return CheckResult(name=service.name, ok=False, latency_ms=round(latency, 1),
                                   status=f"HTTP {status_code} (expected {service.expect_status})", details=details)

            return CheckResult(name=service.name, ok=True, latency_ms=round(latency, 1),
                               status=f"UP | HTTP {status_code}", details=details)

    except urllib.error.HTTPError as e:
        latency = (time.time() - start) * 1000
        if e.code in (404, 400, 401):
            return CheckResult(name=service.name, ok=True, latency_ms=round(latency, 1),
                               status=f"UP | HTTP {e.code}", details={"status_code": e.code})
        return CheckResult(name=service.name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | HTTP {e.code}", details={"status_code": e.code, "error": str(e)})
    except Exception as e:
        latency = (time.time() - start) * 1000
        return CheckResult(name=service.name, ok=False, latency_ms=round(latency, 1),
                           status=f"DOWN | {type(e).__name__}", details={"error": str(e)})


class HealthChecker:
    """Check fleet services and produce reports."""

    def __init__(self, services: list[ServiceDef]):
        self.services = services

    def check_one(self, svc: ServiceDef) -> CheckResult:
        """Check a single service."""
        return check_fleet_service(svc)

    def check_all(self) -> list[CheckResult]:
        """Check all services."""
        return [self.check_one(svc) for svc in self.services]

    @staticmethod
    def report(results: list[CheckResult], format: str = "json") -> str:
        """Generate a report string."""
        up = sum(1 for r in results if r.ok)
        down = len(results) - up

        if format == "json":
            return json.dumps({
                "summary": {"total": len(results), "up": up, "down": down},
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "services": [
                    {
                        "name": r.name,
                        "ok": r.ok,
                        "status": r.status,
                        "latency_ms": r.latency_ms,
                        "details": r.details,
                    }
                    for r in results
                ],
            }, indent=2, default=str)

        elif format == "markdown":
            lines = [
                "# Fleet Health Report",
                "",
                f"**{up}/{len(results)} services UP** — {down} down",
                "",
                "| Service | Status | Latency | Details |",
                "|---------|--------|---------|---------|",
            ]
            for r in results:
                emoji = "🟢" if r.ok else "🔴"
                details = " | ".join(f"{k}={v}" for k, v in list(r.details.items())[:3])
                lines.append(f"| {emoji} {r.name} | {r.status} | {r.latency_ms:.0f}ms | {details} |")
            return "\n".join(lines)

        elif format == "oneline":
            status = "✅" if down == 0 else f"⚠️ {down} down"
            slow = [r for r in results if r.latency_ms > 1000]
            slow_str = f", {len(slow)} slow" if slow else ""
            return f"Fleet: {up}/{len(results)} up{slow_str} {status}"

        return ""


# ── Fleet defaults ──────────────────────────────────────────────────
_FLEET_HOST = os.environ.get("COCAPN_HEALTH_HOST", "147.224.38.131")

FLEET_SERVICES = [
    ServiceDef("MUD v3", _FLEET_HOST, 4042, "/status", extract={"rooms": "rooms"}),
    ServiceDef("The Lock v2", _FLEET_HOST, 4043, "/status", extract={"strategies": "strategies"}),
    ServiceDef("Arena", _FLEET_HOST, 4044, "/stats", extract={"matches": "total_matches"}),
    ServiceDef("Grammar Engine", _FLEET_HOST, 4045, "/grammar", extract={"rules": "total_rules"}),
    ServiceDef("Dashboard", _FLEET_HOST, 4046, "/"),
    ServiceDef("Federated Nexus", _FLEET_HOST, 4047, "/"),
    ServiceDef("Harbor", _FLEET_HOST, 4050, "/"),
    ServiceDef("Grammar Compactor", _FLEET_HOST, 4055, "/status", extract={"rules": "total_rules"}),
    ServiceDef("Rate-Attention", _FLEET_HOST, 4056, "/streams"),
    ServiceDef("Skill Forge", _FLEET_HOST, 4057, "/status", extract={"drills": "total_drills"}),
    ServiceDef("PLATO Terminal", _FLEET_HOST, 4060, "/"),
    ServiceDef("PLATO Gate", _FLEET_HOST, 8847, "/rooms", extract={"rooms": "rooms"}),
    ServiceDef("PLATO Shell", _FLEET_HOST, 8848, "/"),
    ServiceDef("Service Guard", _FLEET_HOST, 8899, "/"),
    ServiceDef("Task Queue", _FLEET_HOST, 8900, "/"),
    ServiceDef("Steward", _FLEET_HOST, 8901, "/"),
    ServiceDef("Matrix Bridge", _FLEET_HOST, 6168, "/status"),
    ServiceDef("Conduwuit", _FLEET_HOST, 6167, "/"),
]
