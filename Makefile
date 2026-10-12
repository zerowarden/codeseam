.PHONY: check test test\:cov lint format typecheck deadcode analyze profile bench clean

# All tool caches live in .cache/ (ruff, mypy, pytest and coverage are set in
# pyproject.toml). Python bytecode follows this prefix; it cannot be set there.
PYTHON_TOOL_ENV = PYTHONPYCACHEPREFIX=.cache/pycache
STRAY_CACHES = .ruff_cache .mypy_cache .pytest_cache .coverage coverage.xml htmlcov

check: lint typecheck test deadcode

deadcode:
	$(PYTHON_TOOL_ENV) uv run vulture src

test:
	$(PYTHON_TOOL_ENV) uv run pytest

test\:cov:
	$(PYTHON_TOOL_ENV) uv run pytest --cov=codeseam --cov-report=term-missing --cov-report=html --cov-report=xml

lint:
	$(PYTHON_TOOL_ENV) uv run ruff check .

format:
	$(PYTHON_TOOL_ENV) uv run ruff format .

typecheck:
	$(PYTHON_TOOL_ENV) uv run mypy src/codeseam tests
	$(PYTHON_TOOL_ENV) uv run basedpyright src/codeseam tests

analyze:
	$(PYTHON_TOOL_ENV) uv run codeseam analyze $(ANALYZE_ARGS)

profile:
	$(PYTHON_TOOL_ENV) uv run codeseam profile $(PROFILE_ARGS)

# Score the labelled corpus; BENCH_ARGS=--update accepts the scores as the new baseline.
bench:
	$(PYTHON_TOOL_ENV) uv run python tests/benchmark.py $(BENCH_ARGS)

# Remove caches and build output written outside .cache/ (for example by a tool
# run without make). The caches in .cache/ stay.
clean:
	rm -rf $(STRAY_CACHES) build dist src/*.egg-info
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
