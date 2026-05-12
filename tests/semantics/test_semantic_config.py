from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from codeseam.cli.commands.analyze import _config_from_args
from codeseam.config import load_config
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
        f'[semantics]\nmode = "{value}"\n',
        encoding="utf-8",
    )

    assert load_config(tmp_path).semantic_mode == SemanticMode(value)
