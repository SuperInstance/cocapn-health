# DEVELOPER.md

> Developer guide for **cocapn-health** — lightweight fleet service health checker.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Adding a New Health Check](#2-adding-a-new-health-check)
3. [Event Types and Payloads](#3-event-types-and-payloads)
4. [Thermal Snapshot Integration](#4-thermal-snapshot-integration)
5. [Testing Patterns](#5-testing-patterns)

---

## 1. Architecture

### 1.1 Project Layout

```
cocapn-health/
├── src/cocapn_health/
│   ├── __init__.py      # Core: ServiceDef, CheckResult, HealthChecker, FLEET_SERVICES
│   ├── cli.py           # CLI entry point (argparse, watch mode, --fail)
│   ├── sunset_bridge.py # EventBus bridge + thermal snapshot
│   └── __main__.py      # python3 -m cocapn_health
├── tests/
│   ├── test_health.py          # Core health checker tests (5 tests)
│   └── test_sunset_bridge.py   # EventBus + thermal tests (14 tests)
├── pyproject.toml
└── README.md
```

### 1.2 Core Health Monitoring

The health monitoring system is built around three primitives:

| Class | Role |
|-------|------|
| `ServiceDef` | Static service configuration (name, host, port, path, timeout, expected status, JSON extraction rules) |
| `CheckResult` | Result of a single probe (name, ok, latency_ms, status string, details dict, checked_at ISO timestamp) |
| `HealthChecker` | Orchestrates checks and generates reports |

**Probe flow (`HealthChecker.check_one`)**

1. Build `http://{host}:{port}{path}`
2. `urllib.request.urlopen(req, timeout=svc.timeout)` — zero external deps
3. Read up to 2048 bytes, decode UTF-8
4. Attempt JSON parse:
   - If `svc.extract` is defined → extract named JSON paths (dot-notation, e.g. `"total_rules"` from `"grammar.total_rules"`)
   - Else → auto-extract known keys: `rooms`, `tiles`, `total_rules`, `total_matches`, `total_players`, `uptime_seconds`, `total_drills`, `streams`
5. Compare actual status code against `svc.expect_status` (if set)
6. Return `CheckResult`

**Error handling philosophy**

- `HTTPError` with codes `404`, `400`, `401` → treated as **UP** (service is alive, endpoint just missing or auth-gated)
- Any other HTTP error → DOWN
- Connection / socket / timeout errors → DOWN
- All exceptions are caught; health checks never raise.

**Reporting (`HealthChecker.report`)**

Three output formats:

| Format | Use case |
|--------|----------|
| `json` | CI pipelines, structured logging, downstream parsing |
| `markdown` | Human-readable fleet dashboard |
| `oneline` | Monitoring / alerting one-liners |

### 1.3 Event Bus Bridge

`sunset_bridge.py` extends `HealthChecker` with fleet-wide event emission:

```python
from cocapn_health.sunset_bridge import EventBusHealthChecker
from nexus.fleet_event_bus import FleetEventBus

checker = EventBusHealthChecker(FLEET_SERVICES, bus=FleetEventBus())
```

**Design principles**

- **Optional dependency** — `FleetEventBus` is imported inside a `try/except`. If `nexus.fleet_event_bus` is not installed, the bridge still works; events are simply not emitted.
- **Non-fatal** — if the bus throws an exception during `emit()`, it is swallowed. Health checks continue.
- **Duck-typed bus** — any object with an `.emit(dict)` method is accepted.
- **State tracking** — `_last_states` remembers the last known `ok` value per service. Events fire **only on transitions** (UP→DOWN or DOWN→UP), suppressing noise on stable fleets.

---

## 2. Adding a New Health Check

### 2.1 Simple endpoint check

Edit `FLEET_SERVICES` in `src/cocapn_health/__init__.py`:

```python
ServiceDef("My Service", "<BOAT_IP>", 9000, "/health"),
```

### 2.2 Check with JSON extraction

```python
ServiceDef(
    "My Service",
    "<BOAT_IP>",
    9000,
    "/health",
    extract={"active_users": "metrics.active_users", "version": "version"},
),
```

The `extract` dict maps:
- **Key** → field name in `CheckResult.details`
- **Value** → dot-separated JSON path (e.g. `"metrics.active_users"` drills into nested dicts)

### 2.3 Custom timeout / expected status / headers

```python
ServiceDef(
    "Legacy API",
    "<BOAT_IP>",
    9001,
    "/ping",
    method="POST",
    timeout=10.0,
    expect_status=204,
    headers={"Authorization": "Bearer fleet"},
),
```

### 2.4 Programmatic usage (no fleet defaults)

```python
from cocapn_health import HealthChecker, ServiceDef

checker = HealthChecker([
    ServiceDef("Alpha", "10.0.0.1", 8080, "/status"),
    ServiceDef("Beta",  "10.0.0.2", 8080, "/status"),
])

results = checker.check_all()
print(checker.report(results, format="json"))
```

### 2.5 Version bump checklist

When modifying `FLEET_SERVICES`:

1. Update the service table in `README.md`
2. Update `version` in `pyproject.toml` (patch bump for new services)
3. Add / update tests if behaviour changed
4. Run `PYTHONPATH=src pytest tests/ -v`

---

## 3. Event Types and Payloads

`EventBusHealthChecker` emits four event types.

### 3.1 `service_down`

Fired when a service transitions **UP → DOWN** (including first-ever check that is down).

```json
{
  "type": "service_down",
  "service": "MUD v3",
  "status": "DOWN | HTTP 503",
  "latency_ms": 5234.0,
  "details": {"status_code": 503, "error": "..."},
  "thermal": {"timestamp": 1716480000.0, "cpu_percent": 42.3, ...}
}
```

### 3.2 `service_recovered`

Fired when a service transitions **DOWN → UP**.

```json
{
  "type": "service_recovered",
  "service": "MUD v3",
  "status": "UP | HTTP 200",
  "latency_ms": 23.5,
  "details": {"status_code": 200, "rooms": 8, "latency_ms": 23.5},
  "thermal": {"timestamp": 1716480060.0, "cpu_percent": 38.1, ...}
}
```

### 3.3 `fleet_health`

Fired **after every `check_all()`** only when `emit_on_every_check=True`.

```json
{
  "type": "fleet_health",
  "total": 18,
  "up": 17,
  "down": 1,
  "services_down": ["Arena"],
  "thermal": {"timestamp": 1716480120.0, "cpu_percent": 55.0, ...}
}
```

Use `fleet_health` for:
- Real-time fleet dashboards
- Time-series ingestion (every check is a data point)
- Alerting on aggregate thresholds (e.g. >20% of fleet down)

### 3.4 Silent checks (no events)

If `bus=None`, or the bus lacks `.emit()`, or the service state hasn't changed, **no event is emitted**.

---

## 4. Thermal Snapshot Integration

Every emitted event includes a `_thermal_snapshot()` payload. This gives downstream consumers context about host pressure at the moment of the health event.

### 4.1 What is captured

| Metric | Source | Notes |
|--------|--------|-------|
| `timestamp` | `time.time()` | Always present |
| `cpu_percent` | `psutil.cpu_percent(interval=0.1)` | Requires `psutil` (optional dep) |
| `memory_percent` | `psutil.virtual_memory().percent` | Requires `psutil` |
| `memory_available_mb` | `psutil.virtual_memory().available` | Requires `psutil` |
| `gpu_util_percent` | `nvidia-smi` CLI | Requires NVIDIA GPU + driver |
| `gpu_memory_used_mb` | `nvidia-smi` CLI | Requires NVIDIA GPU + driver |
| `gpu_memory_total_mb` | `nvidia-smi` CLI | Requires NVIDIA GPU + driver |

### 4.2 Graceful degradation

- `psutil` not installed → CPU/memory fields omitted; snapshot still contains `timestamp`
- `nvidia-smi` missing / non-zero exit → GPU fields omitted
- All subprocess calls are wrapped in `try/except` with 2-second timeout

### 4.3 Extending thermal data

To add new sensors (e.g. disk I/O, temperature probes):

```python
def _thermal_snapshot() -> Dict[str, Any]:
    snapshot = {"timestamp": time.time()}
    # ... existing psutil + nvidia-smi code ...

    # Add custom sensor
    try:
        snapshot["disk_io_wait"] = read_iowait_from_proc()
    except Exception:
        pass

    return snapshot
```

> Keep each sensor block in its own `try/except` so one failing probe doesn't strip the rest.

---

## 5. Testing Patterns

### 5.1 Test suite overview

| File | Tests | Focus |
|------|-------|-------|
| `test_health.py` | 5 | Core `HealthChecker` + `CheckResult` + reporting formats |
| `test_sunset_bridge.py` | 14 | EventBus state transitions, thermal snapshots, graceful degradation |

**Run all tests**

```bash
cd cocapn-health
PYTHONPATH=src pytest tests/ -v
```

### 5.2 Mocking HTTP responses

Tests never hit real fleet services. Use `unittest.mock.patch` on `urllib.request.urlopen`:

```python
from unittest.mock import patch, MagicMock

def _mock_urlopen_up(*args, **kwargs):
    class MockResp:
        status = 200
        def read(self, n=-1):
            return b'{"rooms": 8}'
        def __enter__(self): return self
        def __exit__(self, *args): pass
    return MockResp()

def _mock_urlopen_down(*args, **kwargs):
    raise OSError("Connection refused")

# Usage
with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
    result = checker.check_one(svc)
    assert result.ok
```

**Key patterns**

- Return a mock with `status`, `read()`, and context-manager (`__enter__` / `__exit__`) methods
- Raise `OSError` or `urllib.error.HTTPError` to simulate failure modes
- JSON body is a UTF-8 encoded `bytes` string

### 5.3 Testing state transitions

The bridge remembers state in `_last_states`. Tests verify event emission by sequencing two `check_all()` calls with different mocks:

```python
# 1. First check: DOWN → emits service_down
with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
    checker.check_all()

# 2. Second check: UP → emits service_recovered
mock_bus.emit.reset_mock()
with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
    checker.check_all()

recovered = [c for c in mock_bus.emit.call_args_list
             if c.args[0].get("type") == "service_recovered"]
assert len(recovered) == 2
```

### 5.4 Testing thermal snapshots

Thermal tests assert shape, not exact values (host-dependent):

```python
def test_thermal_snapshot_has_basic_fields():
    snap = _thermal_snapshot()
    assert "timestamp" in snap
    assert isinstance(snap, dict)
```

For event-level thermal asserts:

```python
payload = mock_bus.emit.call_args_list[0].args[0]
assert "thermal" in payload
assert "timestamp" in payload["thermal"]
```

### 5.5 Testing graceful degradation

Verify the bridge works when optional dependencies are absent:

```python
def test_no_bus_no_crash(self, services):
    checker = EventBusHealthChecker(services, bus=None)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
        results = checker.check_all()
    assert len(results) == 2        # health checks still run
    # no events emitted, no exception raised

def test_bus_without_emit_no_crash(self, services):
    bus = MagicMock()
    del bus.emit                      # bus exists but has no emit()
    checker = EventBusHealthChecker(services, bus=bus)
    ...

def test_emit_exception_is_non_fatal(self, mock_bus, services):
    mock_bus.emit.side_effect = RuntimeError("bus exploded")
    checker = EventBusHealthChecker(services, bus=mock_bus)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_down):
        results = checker.check_all()
    assert len(results) == 2          # checks survive bus failure
```

### 5.6 Non-regression: HealthChecker API intact

Whenever `EventBusHealthChecker` is modified, verify it still behaves like the base class:

```python
def test_check_all_returns_results(self, services):
    checker = EventBusHealthChecker(services, bus=None)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
        results = checker.check_all()
    assert isinstance(results, list)
    assert all(isinstance(r, CheckResult) for r in results)

def test_report_still_works(self, services):
    checker = EventBusHealthChecker(services, bus=None)
    with patch("urllib.request.urlopen", side_effect=_mock_urlopen_up):
        results = checker.check_all()
    report = checker.report(results, format="json")
    data = json.loads(report)
    assert "summary" in data
```

### 5.7 CI

Tests run on every push via `.github/workflows/ci-python.yml`:

```yaml
# excerpt
- run: pip install pytest
- run: PYTHONPATH=src pytest tests/ -v
```

---

## Quick Reference

| Task | File / Function |
|------|-----------------|
| Add fleet service | `src/cocapn_health/__init__.py` → `FLEET_SERVICES` |
| Add CLI flag | `src/cocapn_health/cli.py` |
| Add event type | `src/cocapn_health/sunset_bridge.py` → `_emit_*` helpers |
| Add thermal sensor | `src/cocapn_health/sunset_bridge.py` → `_thermal_snapshot()` |
| Add core test | `tests/test_health.py` |
| Add bridge test | `tests/test_sunset_bridge.py` |

---

*Built by CCC (🦀) for the Cocapn Fleet.*
