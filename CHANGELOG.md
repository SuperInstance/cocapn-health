# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Production-grade CI: ruff, mypy, pip caching, 75% coverage gate
- Security workflow: bandit, pip-audit, trufflehog secret scanning
- Release workflow: automated PyPI publish on `v*` tags
- Dockerfile: Python 3.12-slim, non-root user, health check
- Docker Compose service definition
- Makefile with targets: test, coverage, lint, security, docker-build, docker-run, install, clean
- CONTRIBUTING.md with setup and style guidelines
- CHANGELOG.md (this file)
- `.pre-commit-config.yaml` with ruff, mypy, and security hooks

### Changed
- CI now fails on test failure (removed `|| true`)
- CI now fails on lint errors (removed `--exit-zero`)
- Dev dependencies expanded: pytest-cov, ruff, mypy, bandit, pip-audit

## [2.0.0] - 2026-05-28

### Added
- Comprehensive health checks: HTTP, TCP, DNS, system (CPU, memory, disk)
- REST API server (`cocapn_health.api`)
- HealthMonitor with status tracking over time
- AlertManager with severity and escalation
- Custom check registry and builder
- 70 new tests across all modules

### Changed
- README expanded with code examples and API endpoint docs

## [1.0.2] - 2026-05-25

### Fixed
- Fleet host now configurable via `COCAPN_HEALTH_HOST` environment variable

## [1.0.1] - 2026-05-23

### Fixed
- The Lock v2 probed on `/status` instead of `/` (was causing 404 false-positive)
- Matrix Bridge extract removed (response is a user map, not a room list)
- Added 4 missing services: Harbor, Service Guard, Task Queue, Steward

## [1.0.0] - 2026-04-30

### Added
- Initial release: lightweight fleet health checker
- Zero runtime dependencies (stdlib only)
- CLI with `--format json/md/oneline`, `--watch`, `--fail`
- 17 fleet service definitions with health check paths
