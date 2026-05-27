# Contributing to cocapn-health

Thank you for helping make the fleet healthier.

## Quick Start

```bash
git clone https://github.com/SuperInstance/cocapn-health.git
cd cocapn-health
make install        # Installs in editable mode with dev deps
make test           # Run the test suite
make lint           # Check formatting and ruff rules
```

## Development Setup

We use Python 3.10+ and standard tooling:

- **ruff** — linting and formatting
- **mypy** — type checking (allowed to fail in CI for now)
- **pytest + pytest-cov** — tests with 75% coverage gate
- **bandit + pip-audit** — security scanning

## Making Changes

1. **Open an issue first** for non-trivial changes.
2. **Write tests** for any new behavior. We gate on 75% coverage.
3. **Run the full check** before pushing:
   ```bash
   make test && make lint && make security
   ```
4. **Use conventional commits** where possible:
   - `feat:` new check type or API endpoint
   - `fix:` bug fix
   - `docs:` README or spec change
   - `ci:` workflow change
   - `security:` vulnerability fix

## Code Style

- Follow PEP 8 (enforced by ruff).
- Keep the stdlib-only constraint for runtime deps.
- Add type hints for new public APIs.
- Docstrings are appreciated but not mandatory for trivial helpers.

## Release Process

Maintainers:
1. Update `CHANGELOG.md` with the new version.
2. Bump version in `pyproject.toml`.
3. Tag with `vX.Y.Z` and push — the release workflow publishes automatically.

## Questions?

Ping `@Casey` or open a discussion in `#fleet-ops`.
