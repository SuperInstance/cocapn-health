# cocapn-health

Lightweight fleet service health checker for the **Cocapn Fleet**.

**Version:** 1.0.1 | **Tests:** 5 passing | **Lines:** ~400 | **Deps:** zero (stdlib only)

Probe every fleet service, diagnose failures, report in Markdown/JSON/oneline, and optionally bridge into the fleet EventBus with thermal snapshots.

---

## Table of Contents

- [What is cocapn-health?](#what-is-cocapn-health)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [EventBus Bridge](#eventbus-bridge)
- [Example Output](#example-output)
- [Architecture](#architecture)
- [Tests](#tests)
- [Fleet](#fleet)

---

## What is cocapn-health?

`cocapn-health` is a zero-dependency Python toolkit for monitoring the health of a distributed fleet of HTTP services. It was built for the Cocapn Fleet—a collection of ~18 microservices running on a single host—but works equally well for any set of HTTP endpoints you need to keep an eye on.

Core idea: **maximum capability in minimum lines**. The entire runtime fits in a single Python file with no external dependencies. You can drop it into any environment (container, bare metal, CI pipeline) and immediately know which services are up, how fast they respond, and what metrics they expose.

---

## Features

### 🔌 HTTP Probes
- **Parallel-ready** serial checking (easy to parallelise later)
- **Customisable** per-service: host, port, path, method, timeout, expected status code, custom headers
- **Smart status handling**: HTTP 404/400/401 from a live server is treated as "UP" (many fleet services expose no root handler)
- **Auto-extracted metrics**: JSON responses are parsed automatically to pull out useful keys like `rooms`, `tiles`, `total_rules`, `total_matches`, `total_players`, `uptime_seconds`, `total_drills`, `streams`
- **Custom extraction**: define your own JSON path extractions per service (`rooms: "rooms"`, `rules: "total_rules"`, etc.)

### 🌡️ Thermal Snapshots
- Optional `psutil` integration captures **CPU %**, **memory %**, and **available memory** on every check
- Optional `nvidia-smi` integration captures **GPU utilisation %**, **GPU memory used/total**
- Thermal data is attached to every EventBus event so you can correlate service health with system pressure

### 🔗 EventBus Bridge
- `EventBusHealthChecker` extends the base checker to emit fleet events:
  - `service_down` — fired when a service transitions from UP → DOWN
  - `service_recovered` — fired when a service transitions from DOWN → UP
  - `fleet_health` — optional periodic snapshot of the whole fleet + thermal data
- Integrates with the fleet `FleetEventBus` from the sunset ecosystem, but gracefully degrades if the bus is unavailable
- EventBus failures are **non-fatal**—health checks continue regardless

### 📊 Reporting Formats
- **Markdown** (`md`) — human-readable table with emojis
- **JSON** (`json`) — structured output for CI pipelines, dashboards, log aggregation
- **Oneline** (`oneline`) — compact summary for monitoring tickers and alerts

### ⚙️ CLI Modes
- One-shot check (default)
- **Watch mode** (`--watch N`) — recheck every N seconds
- **Fail mode** (`--fail`) — exit with non-zero code if any service is down (CI-friendly)

---

## Quick Start

### Install

```bash
pip install cocapn-health
```

Or clone and run directly:

```bash
git clone https://github.com/SuperInstance/cocapn-health.git
cd cocapn-health
PYTHONPATH=src python -m cocapn_health.cli
```

### CLI

```bash
# Check all fleet services (default: markdown report)
cocapn-health

# JSON output for CI pipelines
cocapn-health --format json

# One-line summary for monitoring dashboards
cocapn-health --format oneline

# Watch mode: recheck every 30 seconds
cocapn-health --watch 30

# Exit with error code if any service is down
cocapn-health --fail

# Custom host and ports
cocapn-health --host 147.224.38.131 --ports 4042,4043,4044,4045
```

### Programmatic

```python
from cocapn_health import HealthChecker, ServiceDef

checker = HealthChecker([
    ServiceDef("MUD", "147.224.38.131", 4042, "/status"),
    ServiceDef("PLATO", "147.224.38.131", 8847, "/rooms"),
])

results = checker.check_all()
print(checker.report(results, format="json"))
```

### With EventBus + Thermal

```python
from cocapn_health import FLEET_SERVICES
from cocapn_health.sunset_bridge import EventBusHealthChecker
from nexus.fleet_event_bus import FleetEventBus

bus = FleetEventBus()
checker = EventBusHealthChecker(FLEET_SERVICES, bus=bus, emit_on_every_check=True)

results = checker.check_all()
# Automatically emits:
#   - service_down / service_recovered on state transitions
#   - fleet_health snapshot with thermal data every check
```

---

## Configuration

### ServiceDef

```python
from cocapn_health import ServiceDef

ServiceDef(
    name="My Service",
    host="127.0.0.1",
    port=8080,
    path="/health",
    method="GET",
    timeout=5.0,
    expect_status=200,
    headers={"Authorization": "Bearer token"},
    extract={"version": "info.version", "users": "metrics.active_users"},
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | — | Human-readable service label |
| `host` | `str` | — | Hostname or IP |
| `port` | `int` | — | TCP port |
| `path` | `str` | `"/"` | URL path to probe |
| `method` | `str` | `"GET"` | HTTP method |
| `timeout` | `float` | `5.0` | Request timeout in seconds |
| `expect_status` | `int` | `None` | If set, require this exact status code |
| `headers` | `dict` | `{}` | Extra HTTP headers |
| `extract` | `dict` | `None` | JSON key → dot-path mapping for response extraction |

### Built-in Fleet Services

The default `FLEET_SERVICES` checks 18 services on `147.224.38.131`:

| Service | Port | Path | Extracted Metrics |
|---------|------|------|-------------------|
| MUD v3 | 4042 | /status | `rooms` |
| The Lock v2 | 4043 | /status | `strategies` |
| Arena | 4044 | /stats | `total_matches` |
| Grammar Engine | 4045 | /grammar | `total_rules` |
| Dashboard | 4046 | / | — |
| Federated Nexus | 4047 | / | — |
| Harbor | 4050 | / | — |
| Grammar Compactor | 4055 | /status | `total_rules` |
| Rate-Attention | 4056 | /streams | `streams` |
| Skill Forge | 4057 | /status | `total_drills` |
| PLATO Terminal | 4060 | / | — |
| PLATO Gate | 8847 | /rooms | `rooms` |
| PLATO Shell | 8848 | / | — |
| Service Guard | 8899 | / | — |
| Task Queue | 8900 | / | — |
| Steward | 8901 | / | — |
| Matrix Bridge | 6168 | /status | — |
| Conduwuit | 6167 | / | — |

---

## EventBus Bridge

The `sunset_bridge.py` module provides `EventBusHealthChecker`, which wraps the base checker with event emission.

### Requirements
- `nexus.fleet_event_bus` (optional—if missing, events are silently skipped)
- `psutil` (optional—for thermal snapshots)
- `nvidia-smi` (optional—for GPU metrics)

### Event Schema

**`service_down`**
```json
{
  "type": "service_down",
  "service": "Arena",
  "status": "DOWN | HTTP 503",
  "latency_ms": 42.3,
  "details": {"status_code": 503, "error": "..."},
  "thermal": {
    "timestamp": 1716480000.0,
    "cpu_percent": 12.5,
    "memory_percent": 45.2,
    "memory_available_mb": 8192.0,
    "gpu_util_percent": 30.0,
    "gpu_memory_used_mb": 2048.0,
    "gpu_memory_total_mb": 8192.0
  }
}
```

**`fleet_health`** (when `emit_on_every_check=True`)
```json
{
  "type": "fleet_health",
  "total": 18,
  "up": 17,
  "down": 1,
  "services_down": ["Arena"],
  "thermal": { ... }
}
```

---

## Example Output

### Markdown (default)

```markdown
# Fleet Health Report

**17/18 services UP** — 1 down

| Service | Status | Latency | Details |
|---------|--------|---------|---------|
| 🟢 MUD v3 | UP \| HTTP 200 | 23ms | status_code=200 latency_ms=23.1 rooms=42 |
| 🟢 The Lock v2 | UP \| HTTP 200 | 18ms | status_code=200 latency_ms=18.3 strategies=12 |
| 🔴 Arena | DOWN \| HTTP 503 | 42ms | status_code=503 error=... |
...
```

### JSON

```json
{
  "summary": {
    "total": 18,
    "up": 17,
    "down": 1
  },
  "checked_at": "2024-05-23T15:06:00+00:00",
  "services": [
    {
      "name": "MUD v3",
      "ok": true,
      "status": "UP | HTTP 200",
      "latency_ms": 23.1,
      "details": {
        "status_code": 200,
        "latency_ms": 23.1,
        "rooms": 42
      }
    },
    {
      "name": "Arena",
      "ok": false,
      "status": "DOWN | HTTP 503",
      "latency_ms": 42.3,
      "details": {
        "status_code": 503,
        "error": "Service Unavailable"
      }
    }
  ]
}
```

### Oneline

```
Fleet: 17/18 up, 1 slow ⚠️ 1 down
```

---

## Architecture

```
cocapn_health/
├── src/cocapn_health/
│   ├── __init__.py         # HealthChecker, ServiceDef, CheckResult, FLEET_SERVICES
│   ├── cli.py              # argparse CLI (json | md | oneline, watch, fail)
│   └── sunset_bridge.py    # EventBusHealthChecker + thermal snapshots
└── tests/
    └── test_health.py      # 5 unit tests
```

Design principles:
1. **Zero dependencies** for core health checking (stdlib only)
2. **Optional enrichment** via `psutil` and `nvidia-smi`
3. **Graceful degradation** — EventBus or thermal failures never break checks
4. **Minimal surface area** — ~400 lines total, easy to audit and extend

---

## Tests

```bash
cd cocapn-health
PYTHONPATH=src pytest tests/ -v
# 5 passed
```

---

## Fleet

Built by CCC (🦀) for the Cocapn Fleet.

Part of the [Cocapn Fleet ecosystem](https://github.com/SuperInstance/cocapn-health).
