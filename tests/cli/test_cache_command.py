from __future__ import annotations

import json
from pathlib import Path

import pytest

from .fixtures import CliRunner


@pytest.mark.integration
def test_cache_clear_removes_audit_and_persistent_cache(
    app_repo: Path,
    cli_runner: CliRunner,
) -> None:
    cli_runner(["analyze", "--quiet"])
    assert (app_repo / ".codeseam" / "reports").exists()
    assert (app_repo / ".codeseam" / "cache").exists()

    cli_runner(["cache", "clear"])


@pytest.mark.integration
def test_cache_prints_stats(app_repo: Path, cli_runner: CliRunner) -> None:
    cli_runner(["analyze", "--quiet"])
    result = cli_runner(["cache"])

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "codeseam.cache_stats.v1"
    assert "entry_count" in payload
    assert payload["audit_output_exists"] is True
