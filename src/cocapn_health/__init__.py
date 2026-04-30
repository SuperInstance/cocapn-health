"""Cocapn Health — Lightweight fleet service health checker.

Maximum capability in minimum lines. Zero dependencies beyond stdlib.
"""
import json
import urllib.request
import socket
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ServiceDef:
    """Service definition for health checking."""
    name: str
    host: str
    port: int
    path: str = "/"
    method: str = "GET"
    timeout: float = 5.0
    expect_status: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    extract: Optional[Dict[str, str]] = None  # JSON keys to extract from response


@dataclass
class CheckResult:
    """Result of a single health check."""
    name: str
    ok: bool
    latency_ms: float
    status: str
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HealthChecker:
    """Check fleet services and produce reports."""

    def __init__(self, services: List[ServiceDef]):
        self.services = services

    def check_one(self, svc: ServiceDef) -> CheckResult:
        """Check a single service."""
        url = f"http://{svc.host}:{svc.port}{svc.path}"
        start = time.time()
        
        try:
            req = urllib.request.Request(url, method=svc.method, headers=svc.headers)
            with urllib.request.urlopen(req, timeout=svc.timeout) as resp:
                latency = (time.time() - start) * 1000
                status_code = resp.status
                body = resp.read(2048).decode("utf-8", errors="replace")
                
                # Try to parse JSON and extract fields
                details = {"status_code": status_code, "latency_ms": round(latency, 1)}
                try:
                    data = json.loads(body)
                    if svc.extract:
                        for key, path in svc.extract.items():
                            val = data
                            for part in path.split("."):
                                val = val.get(part, {}) if isinstance(val, dict) else None
                            details[key] = val
                    else:
                        # Auto-extract useful metrics
                        for k in ["rooms", "tiles", "total_rules", "total_matches", "total_players", "uptime_seconds"]:
                            if k in data:
                                details[k] = data[k]
                except json.JSONDecodeError:
                    details["body_preview"] = body[:100]
                
                # Check expected status if specified
                if svc.expect_status and status_code != svc.expect_status:
                    return CheckResult(
                        name=svc.name,
                        ok=False,
                        latency_ms=round(latency, 1),
                        status=f"HTTP {status_code} (expected {svc.expect_status})",
                        details=details,
                    )
                
                return CheckResult(
                    name=svc.name,
                    ok=True,
                    latency_ms=round(latency, 1),
                    status=f"UP | HTTP {status_code}",
                    details=details,
                )
                
        except urllib.error.HTTPError as e:
            latency = (time.time() - start) * 1000
            # HTTP 404 from a live service is still "up" in many cases
            if e.code in (404, 400, 401):
                return CheckResult(
                    name=svc.name,
                    ok=True,
                    latency_ms=round(latency, 1),
                    status=f"UP | HTTP {e.code}",
                    details={"status_code": e.code},
                )
            return CheckResult(
                name=svc.name,
                ok=False,
                latency_ms=round(latency, 1),
                status=f"DOWN | HTTP {e.code}",
                details={"status_code": e.code, "error": str(e)},
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return CheckResult(
                name=svc.name,
                ok=False,
                latency_ms=round(latency, 1),
                status=f"DOWN | {type(e).__name__}",
                details={"error": str(e)},
            )

    def check_all(self) -> List[CheckResult]:
        """Check all services."""
        return [self.check_one(svc) for svc in self.services]

    @staticmethod
    def report(results: List[CheckResult], format: str = "json") -> str:
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
                f"",
                f"**{up}/{len(results)} services UP** — {down} down",
                f"",
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


# --- Fleet defaults ---

FLEET_SERVICES = [
    ServiceDef("MUD v3", "147.224.38.131", 4042, "/status", extract={"rooms": "rooms"}),
    ServiceDef("The Lock v2", "147.224.38.131", 4043, "/"),
    ServiceDef("Arena", "147.224.38.131", 4044, "/stats", extract={"matches": "total_matches"}),
    ServiceDef("Grammar Engine", "147.224.38.131", 4045, "/grammar", extract={"rules": "total_rules"}),
    ServiceDef("Dashboard", "147.224.38.131", 4046, "/"),
    ServiceDef("Federated Nexus", "147.224.38.131", 4047, "/"),
    ServiceDef("Grammar Compactor", "147.224.38.131", 4055, "/status", extract={"rules": "total_rules"}),
    ServiceDef("Rate-Attention", "147.224.38.131", 4056, "/streams"),
    ServiceDef("Skill Forge", "147.224.38.131", 4057, "/status"),
    ServiceDef("PLATO Terminal", "147.224.38.131", 4060, "/"),
    ServiceDef("PLATO Gate", "147.224.38.131", 8847, "/rooms", extract={"rooms": "rooms"}),
    ServiceDef("PLATO Shell", "147.224.38.131", 8848, "/"),
    ServiceDef("Matrix Bridge", "147.224.38.131", 6168, "/status", extract={"rooms": "rooms"}),
]
