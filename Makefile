.PHONY: test coverage lint lint-fix security docker-build docker-run install clean

PACKAGE = cocapn_health
SRC = src/
TESTS = tests/

install:
	pip install -e ".[dev]"

test:
	python -m pytest --import-mode=importlib -x -v $(TESTS)

coverage:
	python -m pytest --import-mode=importlib -v --cov=$(PACKAGE) --cov-report=term-missing --cov-report=html --cov-fail-under=75 $(TESTS)

lint:
	ruff check $(SRC) $(TESTS)
	ruff format --check $(SRC) $(TESTS)

lint-fix:
	ruff check --fix $(SRC) $(TESTS)
	ruff format $(SRC) $(TESTS)

security:
	bandit -r $(SRC)
	pip-audit --desc

docker-build:
	docker build -t cocapn-health:latest .

docker-run:
	docker run --rm -e COCAPN_HEALTH_HOST=147.224.38.131 cocapn-health:latest

clean:
	rm -rf build/ dist/ .pytest_cache/ .mypy_cache/ .ruff_cache/ htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
