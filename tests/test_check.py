"""Tests for cocapn_health.check — CustomCheck, CheckRegistry, CheckBuilder."""

from cocapn_health import CheckResult
from cocapn_health.check import CheckBuilder, CheckRegistry, CustomCheck

# ── CustomCheck ───────────────────────────────────────────────────


class TestCustomCheck:
    def test_run_success(self):
        def my_check():
            return CheckResult("db", True, 5.0, "UP")

        check = CustomCheck("db", my_check)
        result = check.run()
        assert result.ok
        assert result.name == "db"
        assert result.latency_ms == 5.0

    def test_run_exception(self):
        def bad_check():
            raise ValueError("connection failed")

        check = CustomCheck("bad", bad_check)
        result = check.run()
        assert not result.ok
        assert "ValueError" in result.status
        assert "connection failed" in result.details["error"]

    def test_with_tags(self):
        check = CustomCheck(
            "test", lambda: CheckResult("test", True, 1.0, "UP"), tags=["infra"]
        )
        assert "infra" in check.tags


# ── CheckRegistry ─────────────────────────────────────────────────


class TestCheckRegistry:
    def test_register_decorator(self):
        registry = CheckRegistry()

        @registry.register("my_check")
        def my_check():
            return CheckResult("my_check", True, 1.0, "UP")

        assert "my_check" in registry
        assert len(registry) == 1

    def test_register_with_tags(self):
        registry = CheckRegistry()

        @registry.register("tagged", tags=["infra", "db"])
        def tagged():
            return CheckResult("tagged", True, 1.0, "UP")

        assert "tagged" in registry
        assert "infra" in registry.checks["tagged"].tags

    def test_add_manual(self):
        check = CustomCheck("manual", lambda: CheckResult("manual", True, 1.0, "UP"))
        registry = CheckRegistry()
        registry.add(check)
        assert "manual" in registry

    def test_remove(self):
        registry = CheckRegistry()

        @registry.register("to_remove")
        def to_remove():
            return CheckResult("to_remove", True, 1.0, "UP")

        registry.remove("to_remove")
        assert "to_remove" not in registry

    def test_run_single(self):
        registry = CheckRegistry()

        @registry.register("ping")
        def ping():
            return CheckResult("ping", True, 3.0, "UP")

        result = registry.run("ping")
        assert result.ok
        assert result.name == "ping"

    def test_run_unknown(self):
        registry = CheckRegistry()
        result = registry.run("nonexistent")
        assert not result.ok
        assert "unknown check" in result.status

    def test_run_all(self):
        registry = CheckRegistry()

        @registry.register("a")
        def a():
            return CheckResult("a", True, 1.0, "UP")

        @registry.register("b")
        def b():
            return CheckResult("b", False, 0.0, "DOWN")

        results = registry.run_all()
        assert len(results) == 2
        ok_names = {r.name for r in results if r.ok}
        assert ok_names == {"a"}

    def test_run_tagged(self):
        registry = CheckRegistry()

        @registry.register("db", tags=["infra", "db"])
        def db():
            return CheckResult("db", True, 1.0, "UP")

        @registry.register("cache", tags=["infra"])
        def cache():
            return CheckResult("cache", True, 2.0, "UP")

        @registry.register("web", tags=["frontend"])
        def web():
            return CheckResult("web", True, 3.0, "UP")

        infra_results = registry.run_tagged("infra")
        assert len(infra_results) == 2
        names = {r.name for r in infra_results}
        assert names == {"db", "cache"}

        frontend_results = registry.run_tagged("frontend")
        assert len(frontend_results) == 1

    def test_run_names(self):
        registry = CheckRegistry()

        @registry.register("x")
        def x():
            return CheckResult("x", True, 1.0, "UP")

        @registry.register("y")
        def y():
            return CheckResult("y", True, 1.0, "UP")

        results = registry.run_names(["x", "z"])
        assert len(results) == 2
        assert results[0].ok  # x exists
        assert not results[1].ok  # z doesn't

    def test_check_names(self):
        registry = CheckRegistry()

        @registry.register("alpha")
        def alpha():
            return CheckResult("alpha", True, 1.0, "UP")

        @registry.register("beta")
        def beta():
            return CheckResult("beta", True, 1.0, "UP")

        assert set(registry.check_names) == {"alpha", "beta"}

    def test_len_and_contains(self):
        registry = CheckRegistry()
        assert len(registry) == 0
        assert "x" not in registry

        @registry.register("x")
        def x():
            return CheckResult("x", True, 1.0, "UP")

        assert len(registry) == 1
        assert "x" in registry


# ── CheckBuilder ──────────────────────────────────────────────────


class TestCheckBuilder:
    def test_basic_build(self):
        check = CheckBuilder("api").build(lambda: CheckResult("api", True, 5.0, "UP"))
        assert check.name == "api"
        result = check.run()
        assert result.ok

    def test_with_timeout_and_tags(self):
        check = (
            CheckBuilder("slow")
            .timeout(30.0)
            .tag("infra", "slow")
            .build(lambda: CheckResult("slow", True, 100.0, "UP"))
        )
        assert check.timeout == 30.0
        assert "infra" in check.tags
        assert "slow" in check.tags

    def test_chaining(self):
        builder = CheckBuilder("test").timeout(5.0).tag("a").tag("b")
        check = builder.build(lambda: CheckResult("test", True, 1.0, "UP"))
        assert check.tags == ["a", "b"]
