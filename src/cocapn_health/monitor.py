"""HealthMonitor — Track multiple agents/services over time with status aggregation.

Provides healthy/degraded/unhealthy classification and failure streak tracking.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from cocapn_health import CheckResult, HealthChecker, ServiceDef, check_system


class HealthStatus(str, Enum):
    """Overall system health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class AgentState:
    """Tracks the health state of a single agent/service over time."""
    name: str
    last_ok: bool | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_checks: int = 0
    total_failures: int = 0
    last_check_time: float = 0.0
    last_result: CheckResult | None = None
    history: list[CheckResult] = field(default_factory=list)

    _MAX_HISTORY: int = field(default=100, repr=False)

    def update(self, result: CheckResult) -> None:
        """Update state from a new check result."""
        self.last_ok = result.ok
        self.last_result = result
        self.last_check_time = time.time()
        self.total_checks += 1

        if result.ok:
            self.consecutive_failures = 0
            self.consecutive_successes += 1
        else:
            self.consecutive_successes = 0
            self.consecutive_failures += 1
            self.total_failures += 1

        self.history.append(result)
        if len(self.history) > self._MAX_HISTORY:
            self.history = self.history[-self._MAX_HISTORY:]

    @property
    def availability(self) -> float:
        """Percentage of checks that passed (0.0-100.0)."""
        if self.total_checks == 0:
            return 0.0
        return round(((self.total_checks - self.total_failures) / self.total_checks) * 100, 2)

    @property
    def avg_latency_ms(self) -> float:
        """Average latency across all history entries."""
        if not self.history:
            return 0.0
        return round(sum(r.latency_ms for r in self.history) / len(self.history), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "last_ok": self.last_ok,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "availability": self.availability,
            "avg_latency_ms": self.avg_latency_ms,
            "last_status": self.last_result.status if self.last_result else None,
        }


class HealthMonitor:
    """Monitors fleet services and tracks health state over time.

    Usage::

        monitor = HealthMonitor(services, degraded_threshold=0.5)
        results = monitor.check()
        print(monitor.overall_status)       # HealthStatus.HEALTHY
        print(monitor.agent_states)          # Dict[str, AgentState]
    """

    def __init__(
        self,
        services: list[ServiceDef],
        degraded_threshold: float = 0.5,
        unhealthy_threshold: float = 0.2,
        include_system: bool = False,
    ) -> None:
        self._services = services
        self._checker = HealthChecker(services)
        self._degraded_threshold = degraded_threshold
        self._unhealthy_threshold = unhealthy_threshold
        self._include_system = include_system
        self._agent_states: dict[str, AgentState] = {
            svc.name: AgentState(name=svc.name) for svc in services
        }
        self._system_states: dict[str, AgentState] = {}
        self._check_count: int = 0
        self._last_check_time: float = 0.0

    def check(self) -> list[CheckResult]:
        """Run a health check cycle and update all agent states."""
        results = self._checker.check_all()
        self._check_count += 1
        self._last_check_time = time.time()

        for result in results:
            if result.name in self._agent_states:
                self._agent_states[result.name].update(result)

        # System checks
        if self._include_system:
            sys_results = check_system()
            for r in sys_results:
                if r.name not in self._system_states:
                    self._system_states[r.name] = AgentState(name=r.name)
                self._system_states[r.name].update(r)
            results.extend(sys_results)

        return results

    @property
    def overall_status(self) -> HealthStatus:
        """Compute overall health based on current service states."""
        total = len(self._services)
        if total == 0:
            return HealthStatus.HEALTHY

        up = sum(1 for s in self._agent_states.values() if s.last_ok is True)
        ratio = up / total

        if ratio >= self._degraded_threshold:
            return HealthStatus.HEALTHY
        elif ratio >= self._unhealthy_threshold:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNHEALTHY

    @property
    def agent_states(self) -> dict[str, AgentState]:
        """Current state of all tracked agents."""
        return dict(self._agent_states)

    @property
    def system_states(self) -> dict[str, AgentState]:
        """Current state of system checks."""
        return dict(self._system_states)

    @property
    def check_count(self) -> int:
        return self._check_count

    @property
    def failing_agents(self) -> list[str]:
        """Names of agents currently failing."""
        return [name for name, state in self._agent_states.items() if state.last_ok is False]

    @property
    def summary(self) -> dict[str, Any]:
        total = len(self._services)
        up = sum(1 for s in self._agent_states.values() if s.last_ok is True)
        down = total - up
        return {
            "status": self.overall_status.value,
            "total_services": total,
            "up": up,
            "down": down,
            "check_count": self._check_count,
            "failing": self.failing_agents,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
