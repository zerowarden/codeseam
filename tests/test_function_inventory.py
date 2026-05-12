from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeseam.analysis import (
    FileWithoutFunctionUnits,
    FunctionRecord,
    build_repository_facts,
)
from codeseam.config import load_config
from codeseam.pipeline.inventory import build_function_inventory
from codeseam.pipeline.repository import scan_repository
from codeseam.platform import OutputPaths, write_atomic, write_jsonl_jsonable_atomic

TOP_PARAMETER_COUNT = 2
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "function_inventory"


def test_inventory_ids_are_deterministic_and_role_propagates(tmp_path: Path) -> None:
    write_atomic(tmp_path / "src" / "b.py", "def b():\n    return 1\n")
    write_atomic(tmp_path / "tests" / "test_a.py", "def test_a():\n    return 1\n")

    first = _inventory(tmp_path)
    second = _inventory(tmp_path)

    assert [record.function_id for record in first] == ["fn_000001", "fn_000002"]
    assert first == second
    assert {record.symbol: record.role for record in first} == {
        "b": "source",
        "test_a": "test",
    }


def test_function_record_serializes_without_generic_dataclass_walk(tmp_path: Path) -> None:
    write_atomic(tmp_path / "src" / "app.py", "def app(value):\n    return value\n")

    [record] = _inventory(tmp_path)
    payload = record.to_json_object()

    assert payload["schema_version"] == "codeseam.function_unit.v1"
    assert payload["function_id"] == "fn_000001"
    assert payload["file"] == "src/app.py"
    assert payload["symbol"] == "app"
    assert payload["line_span"] == record.line_span


def test_audit_writes_schema_valid_functions_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    write_atomic(tmp_path / "src" / "app.py", "def app():\n    return 1\n")
    config = load_config(tmp_path)
    paths = OutputPaths(config.path("output", "root"))
    paths.ensure_audit()
    records = _inventory(tmp_path)

    assert records
    line = (paths.artifact("functions")).read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line)["schema_version"] == "codeseam.function_unit.v1"


def _inventory(root: Path) -> tuple[FunctionRecord, ...]:
    config = load_config(root)
    paths = OutputPaths(config.path("output", "root"))
    paths.ensure_audit()
    context = scan_repository(config, paths)
    inventory = build_function_inventory(config, build_repository_facts(context))

    write_jsonl_jsonable_atomic(
        paths.artifact("functions"),
        [record.to_json_object() for record in inventory.records],
    )
    return inventory.records


def test_inventory_summary_records_files_without_function_units(tmp_path: Path) -> None:
    write_atomic(tmp_path / "src" / "empty.py", "VALUE = 1\n")
    write_atomic(tmp_path / "src" / "app.py", "def app():\n    return 1\n")
    config = load_config(tmp_path)
    paths = OutputPaths(config.path("output", "root"))
    paths.ensure_audit()
    context = scan_repository(config, paths)

    inventory = build_function_inventory(config, build_repository_facts(context))

    assert inventory.function_count == 1
    assert inventory.files_without_function_units == (
        FileWithoutFunctionUnits(
            file="src/empty.py",
            language="python",
            caveats=("no_function_units_found",),
        ),
    )
