"""Custom check types — Extensible health checks with composable builders.

Provides a registry for custom health checks and fluent builders.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from cocapn_health import CheckResult

CheckFunc = Callable[[], CheckResult]


@dataclass
class CustomCheck:
    """A user-defined health check with a name and callable.

    Args:
        name: Identifier for this check.
        func: Callable that returns a CheckResult.
        timeout: Optional timeout hint (for display/logging only).
        tags: Optional tags for grouping/filtering.
    """

    name: str
    func: CheckFunc
    timeout: float = 5.0
    tags: list[str] = field(default_factory=list)

    def run(self) -> CheckResult:
        """Execute the check and return the result."""
        start = time.time()
        try:
            result = self.func()
            return result
        except Exception as e:
            latency = (time.time() - start) * 1000
            return CheckResult(
                name=self.name,
                ok=False,
                latency_ms=round(latency, 1),
                status=f"ERROR | {type(e).__name__}",
                details={"error": str(e)},
            )


class CheckRegistry:
    """Registry for custom health checks.

    Usage::

        registry = CheckRegistry()

        @registry.register("db_ping")
        def check_db():
            # ... ping database ...
            return CheckResult(name="db_ping", ok=True, latency_ms=5.0, status="UP")

        # Or manually:
        registry.add(CustomCheck("cache", check_redis, tags=["infra"]))

        # Run all:
        results = registry.run_all()

        # Run by tag:
        results = registry.run_tagged("infra")
    """

    def __init__(self) -> None:
        self._checks: dict[str, CustomCheck] = {}

    def register(
        self, name: str, timeout: float = 5.0, tags: list[str] | None = None
    ) -> Callable:
        """Decorator to register a function as a custom check."""

        def decorator(func: CheckFunc) -> CheckFunc:
            self._checks[name] = CustomCheck(
                name=name, func=func, timeout=timeout, tags=tags or []
            )
            return func

        return decorator

    def add(self, check: CustomCheck) -> None:
        """Add a CustomCheck directly."""
        self._checks[check.name] = check

    def remove(self, name: str) -> None:
        self._checks.pop(name, None)

    def run(self, name: str) -> CheckResult:
        """Run a single named check."""
        check = self._checks.get(name)
        if check is None:
            return CheckResult(
                name=name,
                ok=False,
                latency_ms=0.0,
                status="ERROR | unknown check",
                details={"error": f"No check registered with name '{name}'"},
            )
        return check.run()

    def run_all(self) -> list[CheckResult]:
        """Run all registered checks."""
        return [check.run() for check in self._checks.values()]

    def run_tagged(self, tag: str) -> list[CheckResult]:
        """Run only checks that have the given tag."""
        return [check.run() for check in self._checks.values() if tag in check.tags]

    def run_names(self, names: list[str]) -> list[CheckResult]:
        """Run checks by specific names. Unknown names produce error results."""
        return [self.run(name) for name in names]

    @property
    def check_names(self) -> list[str]:
        return list(self._checks.keys())

    @property
    def checks(self) -> dict[str, CustomCheck]:
        return dict(self._checks)

    def __len__(self) -> int:
        return len(self._checks)

    def __contains__(self, name: str) -> bool:
        return name in self._checks


class CheckBuilder:
    """Fluent builder for creating custom checks.

    Usage::

        check = (CheckBuilder("my_api")
                 .describe("Check the internal API")
                 .tag("infra", "api")
                 .timeout(10.0)
                 .build(lambda: check_http("http://api.internal/ping")))

        result = check.run()
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._timeout: float = 5.0
        self._tags: list[str] = []

    def timeout(self, seconds: float) -> CheckBuilder:
        self._timeout = seconds
        return self

    def tag(self, *tags: str) -> CheckBuilder:
        self._tags.extend(tags)
        return self

    def build(self, func: CheckFunc) -> CustomCheck:
        return CustomCheck(
            name=self._name,
            func=func,
            timeout=self._timeout,
            tags=self._tags,
        )
