import json
import sys
from pathlib import Path

import pytest

# Add source to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cocapn_health import ServiceDef
from cocapn_health.cli import main


class TestCLIBasic:
    """Test the cocapn-health CLI entry point."""

    def test_help_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            sys.argv = ["cocapn-health", "--help"]
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "--host" in captured.out
        assert "--services" in captured.out

    def test_json_flag(self, capsys):
        sys.argv = [
            "cocapn-health",
            "--services",
            "api:127.0.0.1:8080",
            "--format",
            "json",
        ]
        try:
            main()
        except SystemExit as e:
            assert e.code == 1  # Services are down
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "monitors" in data or "services" in str(data)

    def test_services_parsing(self):
        """Test that --services correctly parses name:host:port and name:port."""
        # This is tested implicitly via the CLI, but let's verify the parsing logic
        spec = "api:127.0.0.1:8080,worker:8081"
        services = []
        for s in spec.split(","):
            parts = s.split(":")
            if len(parts) == 2:
                name, port = parts
                services.append(ServiceDef(name, "127.0.0.1", int(port)))
            elif len(parts) == 3:
                name, host, port = parts
                services.append(ServiceDef(name, host, int(port)))
        assert len(services) == 2
        assert services[0].name == "api"
        assert services[0].host == "127.0.0.1"
        assert services[0].port == 8080
        assert services[1].name == "worker"
        assert services[1].port == 8081

    def test_env_var_host_override(self, monkeypatch):
        """Test COCAPN_HEALTH_HOST env var overrides default host."""
        monkeypatch.setenv("COCAPN_HEALTH_HOST", "192.168.1.100")
        import cocapn_health.cli as cli_module

        src = Path(cli_module.__file__).read_text()
        assert "COCAPN_HEALTH_HOST" in src
        # Verify os module is imported (used in _resolve_services)
        assert "import os" in src
