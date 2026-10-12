.PHONY: check test test\:cov lint format typecheck deadcode analyze profile bench

PYTHON_TOOL_ENV = PYTHONPYCACHEPREFIX=.cache/pycache

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
