# Beta Test Fleet — cocapn-health & ccc-os

*Simulated external visitors. Honest friction. No fleet context assumed.*

---

## cocapn-health — Personas

### Persona 1: DevOps Engineer ("Alex")
**Background:** Runs monitoring for a 20-service microservice cluster. Wants a lightweight health checker that doesn't pull in 50 dependencies.

**Journey:**
1. Finds repo on GitHub. README looks clean — 400 lines, zero deps. Intrigued.
2. `git clone`, `cd cocapn-health`, `PYTHONPATH=src python -m cocapn_health.cli`
3. **Friction:** FLEET_SERVICES defaults to `<BOAT_IP>` — all 18 services time out. Alex doesn't have access to the fleet host.
4. **Workaround:** Edits `__init__.py` to change host to `127.0.0.1`, adds own services.
5. `--format json` works. `--watch 30` works. `--fail` works for CI.

**Rating:** ★★★★☆ (4/5)
**Blocker:** Hardcoded fleet host. No `--config` file option to override without editing source.
**Fix:** Add `COCAPN_HEALTH_HOST` env var + `--config services.yaml` CLI flag.

---

### Persona 2: SRE On-Call ("Jordan")
**Background:** Paged at 3 AM because a service is down. Needs to quickly check if it's the service or the network.

**Journey:**
1. Installs via `pip install cocapn-health` (works, clean).
2. Runs `cocapn-health --host my-service.internal --ports 8080`
3. **Friction:** `--ports` accepts comma-separated but no `--services` flag for named services. Output says "Service-0", "Service-1" instead of meaningful names.
4. `--format oneline` gives `Fleet: 0/1 up` — useful for pagerduty but nameless.

**Rating:** ★★★☆☆ (3/5)
**Blocker:** Anonymous service names when using `--ports`. Can't quickly identify which service is down from oneline output.
**Fix:** `--names "API,Worker,Cache"` flag paired with `--ports`. Or `--services api:8080,worker:8081` syntax.

---

### Persona 3: Junior Developer ("Taylor")
**Background:** First job, asked to "set up health checks for our staging environment." Never used a health checker before.

**Journey:**
1. Reads README. "Zero deps" and "~400 lines" feels approachable.
2. Tries programmatic API:
```python
from cocapn_health import HealthChecker, ServiceDef
checker = HealthChecker([ServiceDef("API", "127.0.0.1", 8080)])
```
3. **Friction:** `ServiceDef` has 8 positional args. Taylor doesn't know what `method`, `timeout`, `expect_status` mean. No docstrings in code.
4. **Workaround:** Copies example from README. Works.

**Rating:** ★★★★☆ (4/5)
**Friction:** `ServiceDef` constructor intimidating for juniors. Missing `**kwargs` or `@dataclass` with defaults.
**Fix:** Add `ServiceDef.create_simple(name, host, port)` factory method. Or add docstrings.

---

### Persona 4: Security Auditor ("Riley")
**Background:** Auditing fleet tools for supply chain risk. Checks dependency count, network behavior, data exfiltration potential.

**Journey:**
1. Checks `pyproject.toml` / `setup.py`. Zero deps confirmed. ✅
2. Reads `sunset_bridge.py`. Sees `FleetEventBus` import wrapped in try/except.
3. **Concern:** EventBus events include thermal data (CPU%, memory%, GPU util). If EventBus is misconfigured, could these leak to wrong channel?
4. **Mitigation:** Events only emitted if bus is explicitly passed. No auto-discovery. Acceptable.

**Rating:** ★★★★★ (5/5)
**Verdict:** Clean. Minimal attack surface. Thermal data is local-only unless user explicitly wires EventBus.

---

## ccc-os — Personas

### Persona 1: Fleet Operator ("Morgan")
**Background:** Runs the Cocapn Fleet infrastructure. Wants to understand what ccc-os does and how it monitors agents.

**Journey:**
1. Opens repo. README is 320 lines — comprehensive but dense.
2. Sees `BreederMonitor` with CCC decision rubric. Understands the concept: P0 = tell Casey now, P2 = ignore.
3. **Friction:** No `pip install` or quickstart. README says "For fleet operators" but doesn't say HOW to run it.
4. Searches for `__main__` or CLI. Finds none. It's a library, not a tool.

**Rating:** ★★★☆☆ (3/5)
**Blocker:** No entry point. Morgan can't just `python -m ccc_os` and see status.
**Fix:** Add `python -m ccc_os.monitor` CLI that prints current fleet status table.

---

### Persona 2: Agent Developer ("Casey-adjacent")
**Background:** Building a new agent and wants to integrate with ccc-os monitoring.

**Journey:**
1. Reads `DEVELOPER.md`. Good architecture overview.
2. Looks at `fleet/ccc_decision_rubric.py`. Clear rules: TELL_NOW, LOG, ACT, IGNORE.
3. **Friction:** No example of how to register a new agent with the monitor. No `register_agent()` API.
4. **Workaround:** Reads source, monkey-patches. Works but fragile.

**Rating:** ★★★☆☆ (3/5)
**Blocker:** No plugin API for adding new agent types to monitoring.
**Fix:** `ccc_os.register_monitor(name, check_fn, priority="P1")` public API.

---

## Summary

| Repo | Persona | Rating | Key Blocker |
|------|---------|--------|-------------|
| cocapn-health | DevOps Engineer | ★★★★☆ | Hardcoded fleet host |
| cocapn-health | SRE On-Call | ★★★☆☆ | Anonymous service names |
| cocapn-health | Junior Developer | ★★★★☆ | ServiceDef intimidating |
| cocapn-health | Security Auditor | ★★★★★ | None — clean |
| ccc-os | Fleet Operator | ★★★☆☆ | No CLI entry point |
| ccc-os | Agent Developer | ★★★☆☆ | No plugin API |

**Average:** 3.5/5 (cocapn-health), 3.0/5 (ccc-os)

## Recommended Quick Fixes (Low Effort, High Impact)

1. **cocapn-health:** `COCAPN_HEALTH_HOST` env var + `--config` flag
2. **cocapn-health:** `--services api:8080,worker:8081` syntax for named port pairs
3. **ccc-os:** `python -m ccc_os` CLI for fleet status table
4. **ccc-os:** `register_monitor()` public API for agent integration

---

*Beta test fleet, Round 2. For the fleet, by imagined strangers.*

*kimi1, Fleet Orchestrator | Day 34*
