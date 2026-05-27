"""HealthAlert — Alert rules with severity levels and escalation.

Define when alerts should fire based on failure patterns, and track
escalation when issues persist.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from cocapn_health.monitor import AgentState


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(str, Enum):
    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


@dataclass
class AlertRule:
    """A rule that defines when an alert should fire.

    Args:
        name: Human-readable name for this alert rule.
        condition: Callable that returns True when the alert should fire.
        severity: Severity level when this alert fires.
        cooldown_seconds: Minimum time between repeated fires for the same agent.
        escalation_after_failures: After this many consecutive failures, escalate severity.
        message_template: Optional template string. Use {name}, {failures}, {availability}.
    """
    name: str
    condition: Callable[[AgentState], bool]
    severity: AlertSeverity = AlertSeverity.WARNING
    cooldown_seconds: float = 300.0
    escalation_after_failures: int = 3
    message_template: str = "{name} is failing ({failures} consecutive failures)"


@dataclass
class HealthAlert:
    """An active or resolved alert instance."""
    rule_name: str
    agent_name: str
    severity: AlertSeverity
    state: AlertState = AlertState.PENDING
    message: str = ""
    fired_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    escalation_count: int = 0
    last_fire_time: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """How long this alert has been active (or was active before resolving)."""
        end = self.resolved_at or time.time()
        return round(end - self.fired_at, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "agent_name": self.agent_name,
            "severity": self.severity.value,
            "state": self.state.value,
            "message": self.message,
            "fired_at": datetime.fromtimestamp(self.fired_at, tz=timezone.utc).isoformat(),
            "resolved_at": (
                datetime.fromtimestamp(self.resolved_at, tz=timezone.utc).isoformat()
                if self.resolved_at else None
            ),
            "duration_seconds": self.duration_seconds,
            "escalation_count": self.escalation_count,
        }


# ── Built-in alert conditions ─────────────────────────────────────

def is_down(state: AgentState) -> bool:
    """Alert when the agent is currently down."""
    return state.last_ok is False


def consecutive_failures(threshold: int = 3) -> Callable[[AgentState], bool]:
    """Alert after N consecutive failures."""
    def _check(state: AgentState) -> bool:
        return state.consecutive_failures >= threshold
    return _check


def low_availability(threshold: float = 90.0) -> Callable[[AgentState], bool]:
    """Alert when availability drops below threshold percent."""
    def _check(state: AgentState) -> bool:
        return state.total_checks >= 3 and state.availability < threshold
    return _check


def high_latency(threshold_ms: float = 5000.0) -> Callable[[AgentState], bool]:
    """Alert when average latency exceeds threshold."""
    def _check(state: AgentState) -> bool:
        return state.total_checks >= 2 and state.avg_latency_ms > threshold_ms
    return _check


def always_healthy(state: AgentState) -> bool:
    """Never fires — useful as a no-op rule."""
    return False


# ── Alert manager ──────────────────────────────────────────────────

class AlertManager:
    """Evaluates alert rules against agent states and manages alert lifecycle.

    Usage::

        manager = AlertManager()
        manager.add_rule(AlertRule("service_down", is_down, AlertSeverity.CRITICAL))
        manager.add_rule(AlertRule("flapping", low_availability(80.0), AlertSeverity.WARNING))

        # After health checks...
        manager.evaluate(monitor.agent_states)
        active = manager.active_alerts
    """

    def __init__(self) -> None:
        self._rules: list[AlertRule] = []
        self._alerts: dict[str, HealthAlert] = {}  # key: f"{rule_name}:{agent_name}"
        self._last_evaluated: float = 0.0

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, name: str) -> None:
        self._rules = [r for r in self._rules if r.name != name]

    def evaluate(self, agent_states: dict[str, AgentState]) -> list[HealthAlert]:
        """Evaluate all rules against all agent states. Returns newly fired alerts."""
        newly_fired: list[HealthAlert] = []
        now = time.time()
        self._last_evaluated = now

        for rule in self._rules:
            for agent_name, state in agent_states.items():
                key = f"{rule.name}:{agent_name}"
                existing = self._alerts.get(key)
                triggered = rule.condition(state)

                if triggered:
                    should_fire = True
                    if existing and existing.state in (AlertState.FIRING, AlertState.ESCALATED):
                        # Already firing — check escalation
                        if state.consecutive_failures >= rule.escalation_after_failures and existing.escalation_count == 0:
                                existing.state = AlertState.ESCALATED
                                existing.escalation_count = 1
                                existing.message = self._render_message(
                                    rule, state, " (ESCALATED)"
                                )
                        # Check cooldown
                        if now - existing.last_fire_time < rule.cooldown_seconds:
                            should_fire = False

                    if should_fire and (existing is None or existing.state == AlertState.RESOLVED):
                        alert = HealthAlert(
                            rule_name=rule.name,
                            agent_name=agent_name,
                            severity=rule.severity,
                            state=AlertState.FIRING,
                            message=self._render_message(rule, state),
                            fired_at=now if existing is None else existing.fired_at,
                            last_fire_time=now,
                            escalation_count=existing.escalation_count if existing else 0,
                        )
                        self._alerts[key] = alert
                        newly_fired.append(alert)

                elif existing and existing.state in (AlertState.FIRING, AlertState.ESCALATED):
                    # Condition no longer true — resolve
                    existing.state = AlertState.RESOLVED
                    existing.resolved_at = now

        return newly_fired

    @property
    def active_alerts(self) -> list[HealthAlert]:
        """All currently firing or escalated alerts."""
        return [
            a for a in self._alerts.values()
            if a.state in (AlertState.FIRING, AlertState.ESCALATED)
        ]

    @property
    def all_alerts(self) -> list[HealthAlert]:
        return list(self._alerts.values())

    @property
    def rules(self) -> list[AlertRule]:
        return list(self._rules)

    def clear_resolved(self) -> int:
        """Remove resolved alerts. Returns count removed."""
        to_remove = [
            k for k, a in self._alerts.items()
            if a.state == AlertState.RESOLVED
        ]
        for k in to_remove:
            del self._alerts[k]
        return len(to_remove)

    @staticmethod
    def _render_message(rule: AlertRule, state: AgentState, suffix: str = "") -> str:
        try:
            return rule.message_template.format(
                name=state.name,
                failures=state.consecutive_failures,
                availability=state.availability,
                avg_latency=state.avg_latency_ms,
            ) + suffix
        except KeyError:
            return rule.message_template + suffix
