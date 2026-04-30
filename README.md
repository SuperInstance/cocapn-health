# cocapn-health

Lightweight fleet service health checker. Zero dependencies beyond stdlib.

## Install

```bash
pip install cocapn-health
```

## Usage

```bash
# Check all fleet services (default: markdown report)
cocapn-health

# JSON output for CI pipelines
cocapn-health --format json

# One-line summary for monitoring
cocapn-health --format oneline

# Watch mode: recheck every 30 seconds
cocapn-health --watch 30

# Exit with error code if any service down
cocapn-health --fail
```

## Programmatic

```python
from cocapn_health import HealthChecker, ServiceDef

checker = HealthChecker([
    ServiceDef("MUD", "147.224.38.131", 4042, "/status"),
    ServiceDef("PLATO", "147.224.38.131", 8847, "/rooms"),
])

results = checker.check_all()
print(checker.report(results, format="json"))
```

## Fleet Services (built-in)

Checks 13 fleet services on `147.224.38.131`:
- MUD v3 (4042), The Lock v2 (4043), Arena (4044)
- Grammar Engine (4045), Dashboard (4046), Federated Nexus (4047)
- Grammar Compactor (4055), Rate-Attention (4056), Skill Forge (4057)
- PLATO Terminal (4060), PLATO Gate (8847), PLATO Shell (8848)
- Matrix Bridge (6168)

## Version

1.0.0

## Fleet

Built by CCC (🦀) for the Cocapn Fleet.
