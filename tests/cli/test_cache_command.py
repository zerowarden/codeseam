from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeseam.cli import CONFIG_ERROR

from .fixtures import CliRunner


@pytest.mark.integration
def test_cache_clear_removes_only_persistent_cache(
    app_repo: Path,
    cli_runner: CliRunner,
) -> None:
    cli_runner(["analyze", "--quiet"])
    assert (app_repo / ".codeseam" / "reports").exists()
    assert (app_repo / ".codeseam" / "cache").exists()

    cli_runner(["cache", "clear"])

    assert (app_repo / ".codeseam" / "reports" / "manifest.json").exists()
    assert not (app_repo / ".codeseam" / "cache").exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("config", "command"),
    [
        ('[output]\nroot = "."\n', ["cache", "clear"]),
        ('[output]\nroot = "src"\n', ["analyze", "--quiet"]),
        ('[cache]\npath = "src"\n', ["cache", "clear"]),
    ],
)
def test_unowned_storage_config_is_rejected_before_deleting_anything(
    app_repo: Path,
    cli_runner: CliRunner,
    config: str,
    command: list[str],
) -> None:
    sentinel = app_repo / "src" / "agent" / "keep.py"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("x = 1\n", encoding="utf-8")
    (app_repo / "codeseam.toml").write_text(config, encoding="utf-8")

    cli_runner(command, expected=CONFIG_ERROR)

    assert sentinel.exists()
    assert (app_repo / "src" / "app.py").exists()


@pytest.mark.integration
def test_cache_prints_stats(app_repo: Path, cli_runner: CliRunner) -> None:
    cli_runner(["analyze", "--quiet"])
    result = cli_runner(["cache"])

    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "codeseam.cache_stats.v1"
    assert "entry_count" in payload
    assert payload["audit_output_exists"] is True
