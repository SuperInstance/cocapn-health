"""HealthReport — System-wide status report with history and formatting.

Generates structured reports combining monitor state, alerts, and trends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cocapn_health.alert import AlertManager
from cocapn_health.monitor import HealthMonitor, HealthStatus


@dataclass
class HealthReport:
    """A snapshot of system health at a point in time.

    Can be created manually or via ``from_monitor()``.
    """

    status: HealthStatus
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_services: int = 0
    services_up: int = 0
    services_down: int = 0
    failing: list[str] = field(default_factory=list)
    agent_summaries: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    system_checks: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_monitor(
        cls,
        monitor: HealthMonitor,
        alert_manager: AlertManager | None = None,
    ) -> HealthReport:
        """Create a report from a HealthMonitor (and optional AlertManager)."""
        summary = monitor.summary
        agent_summaries = [state.to_dict() for state in monitor.agent_states.values()]
        system_summaries = [state.to_dict() for state in monitor.system_states.values()]

        alert_list: list[dict[str, Any]] = []
        if alert_manager:
            alert_list = [a.to_dict() for a in alert_manager.active_alerts]

        return cls(
            status=monitor.overall_status,
            total_services=summary["total_services"],
            services_up=summary["up"],
            services_down=summary["down"],
            failing=summary["failing"],
            agent_summaries=agent_summaries,
            alerts=alert_list,
            system_checks=system_summaries,
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at,
            "total_services": self.total_services,
            "services_up": self.services_up,
            "services_down": self.services_down,
            "failing": self.failing,
            "agents": self.agent_summaries,
            "alerts": self.alerts,
            "system": self.system_checks,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Health Report",
            "",
            f"**Status:** {self.status.value.upper()} | "
            f"**{self.services_up}/{self.total_services}** services up | "
            f"**{self.services_down}** down",
            f"**Checked:** {self.checked_at}",
            "",
        ]

        if self.failing:
            lines.append("## ⚠️ Failing Services")
            for name in self.failing:
                lines.append(f"- 🔴 **{name}**")
            lines.append("")

        # Agent table
        if self.agent_summaries:
            lines.append("## Service Details")
            lines.append("")
            lines.append("| Service | Status | Availability | Avg Latency | Failures |")
            lines.append("|---------|--------|-------------|-------------|----------|")
            for agent in self.agent_summaries:
                ok = agent.get("last_ok")
                emoji = "🟢" if ok else "🔴" if ok is False else "⚪"
                lines.append(
                    f"| {emoji} {agent['name']} "
                    f"| {'UP' if ok else 'DOWN'} "
                    f"| {agent.get('availability', 'N/A')}% "
                    f"| {agent.get('avg_latency_ms', 'N/A')}ms "
                    f"| {agent.get('consecutive_failures', 0)} |"
                )
            lines.append("")

        # System checks
        if self.system_checks:
            lines.append("## System Checks")
            lines.append("")
            for check in self.system_checks:
                ok = check.get("last_ok")
                emoji = "🟢" if ok else "🔴"
                lines.append(
                    f"- {emoji} **{check['name']}**: {check.get('last_status', 'unknown')}"
                )
            lines.append("")

        # Active alerts
        if self.alerts:
            lines.append("## 🚨 Active Alerts")
            lines.append("")
            for alert in self.alerts:
                sev = alert.get("severity", "unknown")
                lines.append(
                    f"- **[{sev.upper()}]** {alert.get('message', alert.get('rule_name'))}"
                )
            lines.append("")

        return "\n".join(lines)

    def to_oneline(self) -> str:
        status_emoji = {
            HealthStatus.HEALTHY: "✅",
            HealthStatus.DEGRADED: "⚠️",
            HealthStatus.UNHEALTHY: "🔴",
        }
        emoji = status_emoji.get(self.status, "?")
        alert_count = len(self.alerts)
        alert_str = (
            f", {alert_count} alert{'s' if alert_count != 1 else ''}"
            if alert_count
            else ""
        )
        failing_str = f", failing: {', '.join(self.failing)}" if self.failing else ""
        return (
            f"{emoji} {self.status.value.upper()} | "
            f"{self.services_up}/{self.total_services} up{failing_str}{alert_str}"
        )
