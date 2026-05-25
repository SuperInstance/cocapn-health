"""Tests for the REST API endpoint."""
import json
import threading
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import pytest

from cocapn_health.api import run_api, HealthCache
from cocapn_health import FLEET_SERVICES


@pytest.fixture(scope="module")
def api_server():
    """Start the API on a random available port."""
    # Find a free port
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    t = threading.Thread(target=run_api, args=("127.0.0.1", port, 5.0, FLEET_SERVICES[:3]),
                         daemon=True)
    t.start()
    time.sleep(0.5)
    yield port


def _get(api_server, path):
    url = f"http://127.0.0.1:{api_server}{path}"
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def test_health_endpoint(api_server):
    data = _get(api_server, "/health")
    assert "status" in data
    assert "fleet" in data
    assert "system" in data


def test_fleet_endpoint(api_server):
    data = _get(api_server, "/fleet")
    assert "services" in data
    assert "summary" in data


def test_system_endpoint(api_server):
    data = _get(api_server, "/system")
    assert "checks" in data


def test_check_cpu_endpoint(api_server):
    data = _get(api_server, "/check/cpu")
    assert "name" in data
    assert data["name"] == "cpu"


def test_check_memory_endpoint(api_server):
    data = _get(api_server, "/check/memory")
    assert "name" in data


def test_check_disk_endpoint(api_server):
    data = _get(api_server, "/check/disk")
    assert "name" in data


def test_refresh_endpoint(api_server):
    data = _get(api_server, "/refresh")
    assert data["status"] == "cache cleared"


def test_404(api_server):
    with pytest.raises(HTTPError) as exc_info:
        _get(api_server, "/nonexistent")
    assert exc_info.value.code == 404


def test_health_cache():
    cache = HealthCache(ttl=1.0)
    cache.set_services(FLEET_SERVICES[:2])
    results = cache.get_system()
    assert len(results) > 0
    # Second call should return cached
    results2 = cache.get_system()
    assert results2 is results  # same object = cached
