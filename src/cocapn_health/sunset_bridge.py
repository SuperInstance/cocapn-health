"""Sunset bridge — wires cocapn-health into the fleet EventBus + thermal system.

Usage::

    from cocapn_health.sunset_bridge import EventBusHealthChecker
    from nexus.fleet_event_bus import FleetEventBus

    bus = FleetEventBus()
    checker = EventBusHealthChecker(FLEET_SERVICES, bus=bus)
    results = checker.check_all()   # emits service_down / service_recovered
"""

from __future__ import annotations

import time
from typing import Any

from cocapn_health import CheckResult, HealthChecker, ServiceDef

# ── Optional sunset-ecosystem integration ─────────────────────────
try:
    from nexus.fleet_event_bus import FleetEventBus

    _HAS_BUS = True
except Exception:
    FleetEventBus = None  # type: ignore[misc,assignment]
    _HAS_BUS = False

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False


class EventBusHealthChecker(HealthChecker):
    """HealthChecker that also emits fleet events on state transitions.

    Inherits all HealthChecker behaviour and adds:
      • service_down  — when a service transitions from UP → DOWN
      • service_recovered — when a service transitions from DOWN → UP
      • thermal_snapshot — CPU/GPU/memory pressure included in every event
    """

    def __init__(
        self,
        services: list[ServiceDef],
        bus: Any | None = None,
        emit_on_every_check: bool = False,
    ) -> None:
        super().__init__(services)
        self._bus = bus
        self._emit_on_every_check = emit_on_every_check
        self._last_states: dict[str, bool] = {}

    # ── Overrides ───────────────────────────────────────────────────

    def check_one(self, svc: ServiceDef) -> CheckResult:
        """Check a service and emit events on state transitions."""
        result = super().check_one(svc)
        self._maybe_emit(svc.name, result)
        return result

    def check_all(self) -> list[CheckResult]:
        """Check all services; emit events; optionally emit fleet_health snapshot."""
        results = super().check_all()

        if self._emit_on_every_check and self._bus is not None:
            down = [r for r in results if not r.ok]
            self._emit(
                "fleet_health",
                {
                    "total": len(results),
                    "up": len(results) - len(down),
                    "down": len(down),
                    "services_down": [r.name for r in down],
                    "thermal": _thermal_snapshot(),
                },
            )

        return results

    # ── Internal ────────────────────────────────────────────────────

    def _maybe_emit(self, name: str, result: CheckResult) -> None:
        """Emit event if state changed since last check."""
        if self._bus is None:
            return

        last_ok = self._last_states.get(name)
        self._last_states[name] = result.ok

        if last_ok is None:
            # First check — only emit if currently DOWN
            if not result.ok:
                self._emit_service_down(name, result)
            return

        if last_ok and not result.ok:
            self._emit_service_down(name, result)
        elif not last_ok and result.ok:
            self._emit_service_recovered(name, result)

    def _emit_service_down(self, name: str, result: CheckResult) -> None:
        self._emit(
            "service_down",
            {
                "service": name,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "details": result.details,
                "thermal": _thermal_snapshot(),
            },
        )

    def _emit_service_recovered(self, name: str, result: CheckResult) -> None:
        self._emit(
            "service_recovered",
            {
                "service": name,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "details": result.details,
                "thermal": _thermal_snapshot(),
            },
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            if hasattr(self._bus, "emit"):
                self._bus.emit({"type": event_type, **payload})
        except Exception:
            # Non-fatal: EventBus failure must not break health checks
            pass


# ── Thermal snapshot helper ───────────────────────────────────────


def _thermal_snapshot() -> dict[str, Any]:
    """Return CPU / memory / thermal pressure metrics."""
    snapshot: dict[str, Any] = {"timestamp": time.time()}

    if _HAS_PSUTIL:
        try:
            snapshot["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            snapshot["memory_percent"] = mem.percent
            snapshot["memory_available_mb"] = round(mem.available / (1024 * 1024), 1)
        except Exception:
            pass

    # GPU metrics (nvidia-smi if available)
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        parts = out.strip().split(",")
        if len(parts) >= 3:
            snapshot["gpu_util_percent"] = float(parts[0].strip())
            snapshot["gpu_memory_used_mb"] = float(parts[1].strip())
            snapshot["gpu_memory_total_mb"] = float(parts[2].strip())
    except Exception:
        pass

    return snapshot
