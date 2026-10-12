from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.config import load_config
from codeseam.platform import ConfigError
from codeseam.platform.storage import (
    OWNERSHIP_MARKER,
    claim_storage_root,
    is_owned_storage_root,
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "agent").mkdir(parents=True)
    (repo / "src" / "agent" / "keep.py").write_text("x = 1\n", encoding="utf-8")
    return repo


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("output.root", "."),
        ("output.root", ".."),
        ("output.root", ""),
        ("output.root", "src"),
        ("cache.path", "."),
        ("cache.path", "src"),
        ("cache.path", ".."),
    ],
)
def test_load_config_rejects_unowned_storage_roots(tmp_path: Path, key: str, value: str) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(ConfigError):
        load_config(repo, {key: value})


@pytest.mark.parametrize("value", ["build/codeseam-reports", "empty-dir", "claimed"])
def test_load_config_accepts_new_empty_or_claimed_roots(tmp_path: Path, value: str) -> None:
    repo = _repo(tmp_path)
    (repo / "empty-dir").mkdir()
    (repo / "claimed").mkdir()
    (repo / "claimed" / "old-report.md").write_text("old\n", encoding="utf-8")
    (repo / "claimed" / OWNERSHIP_MARKER).write_text("", encoding="utf-8")

    config = load_config(repo, {"output.root": value})

    assert config.output_root == repo / value


def test_claim_marks_external_roots_but_not_project_storage(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    external = repo / "build" / "reports"
    project = repo / ".codeseam" / "reports"

    claim_storage_root(repo, external)
    claim_storage_root(repo, project)
    (external / "summary.md").write_text("report\n", encoding="utf-8")
    (project / "summary.md").write_text("report\n", encoding="utf-8")

    assert (external / OWNERSHIP_MARKER).is_file()
    assert not (project / OWNERSHIP_MARKER).exists()
    assert is_owned_storage_root(repo, external)
    assert is_owned_storage_root(repo, project)
    assert not is_owned_storage_root(repo, repo / "src")
