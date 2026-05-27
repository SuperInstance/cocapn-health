"""Tests for cocapn_health.alert — AlertManager, AlertRule, HealthAlert, conditions."""
import time

from cocapn_health import CheckResult
from cocapn_health.alert import (
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertState,
    HealthAlert,
    always_healthy,
    consecutive_failures,
    high_latency,
    is_down,
    low_availability,
)
from cocapn_health.monitor import AgentState

# ── Helpers ───────────────────────────────────────────────────────

def make_state(name="test", ok=True, consecutive_failures=0, total_checks=1):
    state = AgentState(name=name)
    state.update(CheckResult(name, ok, 10.0, "UP" if ok else "DOWN"))
    if consecutive_failures > 0:
        state.consecutive_failures = consecutive_failures
    for _ in range(total_checks - 1):
        state.update(CheckResult(name, ok, 10.0, "UP" if ok else "DOWN"))
    return state


# ── AlertRule ─────────────────────────────────────────────────────

class TestAlertRule:
    def test_basic_rule(self):
        rule = AlertRule("test_rule", is_down)
        assert rule.name == "test_rule"
        assert rule.severity == AlertSeverity.WARNING
        assert rule.cooldown_seconds == 300.0

    def test_custom_params(self):
        rule = AlertRule(
            "custom", is_down,
            severity=AlertSeverity.CRITICAL,
            cooldown_seconds=60.0,
            escalation_after_failures=5,
        )
        assert rule.severity == AlertSeverity.CRITICAL
        assert rule.escalation_after_failures == 5


# ── Built-in conditions ───────────────────────────────────────────

class TestConditions:
    def test_is_down(self):
        assert is_down(make_state(ok=False))
        assert not is_down(make_state(ok=True))

    def test_consecutive_failures(self):
        cond = consecutive_failures(3)
        assert not cond(make_state(ok=False, consecutive_failures=2))
        assert cond(make_state(ok=False, consecutive_failures=3))
        assert cond(make_state(ok=False, consecutive_failures=5))

    def test_low_availability(self):
        cond = low_availability(90.0)
        # 50% avail with 4 checks → triggers
        state = make_state(ok=True, total_checks=4)
        state.total_failures = 2
        assert cond(state)
        # 100% avail → doesn't trigger
        state2 = make_state(ok=True, total_checks=5)
        assert not cond(state2)

    def test_low_availability_needs_min_checks(self):
        cond = low_availability(90.0)
        state = make_state(ok=True, total_checks=1)
        assert not cond(state)  # Not enough data

    def test_high_latency(self):
        cond = high_latency(1000.0)
        state = make_state(ok=True, total_checks=3)
        state.history = [CheckResult("x", True, 2000.0, "UP") for _ in range(3)]
        assert cond(state)

    def test_high_latency_not_enough_checks(self):
        cond = high_latency(1000.0)
        state = make_state(ok=True, total_checks=1)
        assert not cond(state)

    def test_always_healthy(self):
        assert not always_healthy(make_state(ok=False))


# ── HealthAlert ───────────────────────────────────────────────────

class TestHealthAlert:
    def test_basic_alert(self):
        alert = HealthAlert(
            rule_name="down", agent_name="svc", severity=AlertSeverity.WARNING,
        )
        assert alert.state == AlertState.PENDING
        assert alert.escalation_count == 0
        assert alert.resolved_at is None

    def test_duration_seconds(self):
        alert = HealthAlert(
            rule_name="down", agent_name="svc", severity=AlertSeverity.WARNING,
            fired_at=time.time() - 60,
        )
        assert alert.duration_seconds >= 59
        assert alert.duration_seconds <= 61

    def test_to_dict(self):
        alert = HealthAlert(
            rule_name="down", agent_name="svc", severity=AlertSeverity.CRITICAL,
            state=AlertState.FIRING, message="Service down",
        )
        d = alert.to_dict()
        assert d["rule_name"] == "down"
        assert d["agent_name"] == "svc"
        assert d["severity"] == "critical"
        assert d["state"] == "firing"
        assert d["message"] == "Service down"


# ── AlertManager ──────────────────────────────────────────────────

class TestAlertManager:
    def test_evaluate_fires_on_down(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down, AlertSeverity.CRITICAL))
        states = {"svc": make_state(ok=False)}
        fired = mgr.evaluate(states)
        assert len(fired) == 1
        assert fired[0].agent_name == "svc"
        assert fired[0].severity == AlertSeverity.CRITICAL

    def test_no_fire_when_healthy(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        states = {"svc": make_state(ok=True)}
        fired = mgr.evaluate(states)
        assert len(fired) == 0

    def test_resolve_on_recovery(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        # First: down → fires
        mgr.evaluate({"svc": make_state(ok=False)})
        assert len(mgr.active_alerts) == 1
        # Second: up → resolves
        mgr.evaluate({"svc": make_state(ok=True)})
        assert len(mgr.active_alerts) == 0
        alert = mgr.all_alerts[0]
        assert alert.state == AlertState.RESOLVED
        assert alert.resolved_at is not None

    def test_no_duplicate_fire_on_same_state(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down, cooldown_seconds=0.0))
        states = {"svc": make_state(ok=False)}
        mgr.evaluate(states)
        fired = mgr.evaluate(states)
        # Alert already firing, no new fire
        assert len(fired) == 0

    def test_escalation(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(
            "down", is_down, escalation_after_failures=2,
        ))
        # Fire once
        state = make_state(ok=False)
        state.consecutive_failures = 2
        mgr.evaluate({"svc": state})
        # Escalation happens on re-evaluate
        mgr.evaluate({"svc": state})
        alerts = mgr.active_alerts
        assert len(alerts) == 1
        assert alerts[0].state == AlertState.ESCALATED

    def test_multiple_agents(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        states = {
            "a": make_state(name="a", ok=False),
            "b": make_state(name="b", ok=True),
            "c": make_state(name="c", ok=False),
        }
        fired = mgr.evaluate(states)
        assert len(fired) == 2
        names = {f.agent_name for f in fired}
        assert names == {"a", "c"}

    def test_multiple_rules(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        mgr.add_rule(AlertRule("failing", consecutive_failures(2), AlertSeverity.WARNING))
        state = make_state(ok=False, consecutive_failures=3)
        fired = mgr.evaluate({"svc": state})
        assert len(fired) == 2

    def test_remove_rule(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        mgr.remove_rule("down")
        assert len(mgr.rules) == 0

    def test_clear_resolved(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule("down", is_down))
        mgr.evaluate({"svc": make_state(ok=False)})
        mgr.evaluate({"svc": make_state(ok=True)})
        removed = mgr.clear_resolved()
        assert removed == 1
        assert len(mgr.all_alerts) == 0

    def test_message_template(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(
            "down", is_down,
            message_template="{name} has {failures} failures",
        ))
        state = make_state(name="svc", ok=False)
        state.consecutive_failures = 5
        fired = mgr.evaluate({"svc": state})
        assert "svc has 5 failures" in fired[0].message
