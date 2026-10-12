from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from codeseam.cli.commands.analyze import _config_from_args
from codeseam.config import load_config
from codeseam.platform import ConfigError
from codeseam.semantics import SemanticMode


def test_default_semantic_mode_is_off(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.semantic_mode is SemanticMode.OFF


def test_cli_semantic_mode_override_is_generic(tmp_path: Path) -> None:
    config = _config_from_args(
        argparse.Namespace(
            path=None,
            repo_root=str(tmp_path),
            include=None,
            exclude=None,
            semantic_mode="project",
        )
    )

    assert config.semantic_mode is SemanticMode.PROJECT


@pytest.mark.parametrize("value", ["off", "auto", "project", "required"])
def test_supported_semantic_modes_round_trip_from_config(
    tmp_path: Path,
    value: str,
) -> None:
    (tmp_path / "codeseam.toml").write_text(
        f'[semantics]\nmode = "{value}"\ntrust_project_code = true\n',
        encoding="utf-8",
    )

    assert load_config(tmp_path).semantic_mode == SemanticMode(value)


def test_required_mode_needs_trusted_project_code(tmp_path: Path) -> None:
    (tmp_path / "codeseam.toml").write_text('[semantics]\nmode = "required"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="trust_project_code"):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["aut", "PROJECT", 1])
def test_unknown_semantic_mode_is_a_config_error(tmp_path: Path, value: object) -> None:
    rendered = f'"{value}"' if isinstance(value, str) else str(value)
    (tmp_path / "codeseam.toml").write_text(f"[semantics]\nmode = {rendered}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="semantics.mode"):
        load_config(tmp_path)
