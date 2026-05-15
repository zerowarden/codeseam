from __future__ import annotations

from pathlib import Path

from helpers import assert_contains

from .fixtures import CliRunner


def test_init_materializes_default_config(cli_runner: CliRunner, tmp_path: Path) -> None:
    result = cli_runner(["init"])

    config_path = tmp_path / "codeseam.toml"
    assert config_path.exists()
    assert 'root = ".codeseam/reports"' in config_path.read_text(encoding="utf-8")
    assert (tmp_path / ".codeseamignore").exists()
    assert "Created:" in result.stdout

    result = cli_runner(["init"])

    assert_contains(result.stdout, ["Already existed:", "- codeseam.toml", "- .codeseamignore"])


def test_init_can_create_report_and_cache_dirs(cli_runner: CliRunner, tmp_path: Path) -> None:
    result = cli_runner(["init", "--no-ignore", "--create-dirs"])

    assert (tmp_path / "codeseam.toml").exists()
    assert not (tmp_path / ".codeseamignore").exists()
    assert (tmp_path / ".codeseam" / "reports").is_dir()
    assert (tmp_path / ".codeseam" / "cache").is_dir()
    assert_contains(result.stdout, ["- .codeseam/reports", "- .codeseam/cache"])
