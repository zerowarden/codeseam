from __future__ import annotations

from pathlib import Path

from codeseam.config import load_config
from codeseam.platform import as_json_object, runtime_lock_paths, text_list


def test_config_precedence(tmp_path: Path) -> None:
    (tmp_path / "codeseam.toml").write_text(
        '[output]\nroot = ".root-output"\n',
        encoding="utf-8",
    )
    (tmp_path / ".codeseam").mkdir()
    (tmp_path / ".codeseam" / "codeseam.toml").write_text(
        '[cache]\npath = ".project-cache"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path, {"cache.path": ".cli-cache"})

    assert config.path("output", "root") == tmp_path / ".root-output"
    assert config.cache_path() == tmp_path / ".cli-cache"
    assert config.config_hash.startswith("sha256:")
    assert config.sources == (
        "defaults",
        "codeseam.toml",
        ".codeseam/codeseam.toml",
        "cli",
    )


def test_default_config_materializes_output_root(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.path("output", "root") == tmp_path / ".codeseam" / "reports"
    assert config.cache_path() == tmp_path / ".codeseam" / "cache"
    assert config.cache_enabled is True
    assert config.cache_stage_enabled("file_analysis") is True
    assert config.cache_stage_enabled("relation_pairs") is True
    assert config.relation_policy_enabled("split_test") is True


def test_runtime_locks_live_under_codeseam_runtime(tmp_path: Path) -> None:
    audit_lock, cache_lock = runtime_lock_paths(
        tmp_path / ".codeseam" / "reports",
        tmp_path / ".codeseam" / "cache",
    )

    assert audit_lock == tmp_path / ".codeseam" / "runtime" / "locks" / "analyze.lock"
    assert cache_lock == tmp_path / ".codeseam" / "runtime" / "locks" / "cache.lock"


def test_runtime_locks_use_project_runtime_for_custom_roots(tmp_path: Path) -> None:
    audit_lock, cache_lock = runtime_lock_paths(
        tmp_path / ".root-output",
        tmp_path / ".cli-cache",
    )

    assert audit_lock == tmp_path / ".codeseam" / "runtime" / "locks" / "analyze.lock"
    assert cache_lock == tmp_path / ".codeseam" / "runtime" / "locks" / "cache.lock"


def test_codeseamignore_extends_selection_excludes(tmp_path: Path) -> None:
    (tmp_path / ".codeseamignore").write_text(
        "# generated files\ngenerated/**\n\nvendor/**\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    selection = as_json_object(config.data.get("selection"))
    exclude = text_list(selection.get("exclude"))
    assert "generated/**" in exclude
    assert "vendor/**" in exclude
    assert ".codeseamignore" in config.sources
