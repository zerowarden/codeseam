from __future__ import annotations

from pathlib import Path

import pytest

from codeseam.analysis import AssessmentPolicy
from codeseam.config import load_config
from codeseam.platform import ConfigError, runtime_lock_paths

HIGH_HOLE_COUNT_OVERRIDE = 5


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

    assert config.output_root == tmp_path / ".root-output"
    assert config.cache_path == tmp_path / ".cli-cache"
    assert config.config_hash.startswith("sha256:")
    assert config.sources == (
        "defaults",
        "codeseam.toml",
        ".codeseam/codeseam.toml",
        "cli",
    )


def test_default_config_materializes_output_root(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config.output_root == tmp_path / ".codeseam" / "reports"
    assert config.cache_path == tmp_path / ".codeseam" / "cache"
    assert config.cache_enabled is True
    assert config.split_test is True


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

    assert {"generated/**", "vendor/**"} <= set(config.selection.exclude)
    assert ".codeseamignore" in config.sources


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[cache]\nenabled = "false"\n', "cache.enabled"),
        ('[relations]\nsplit_test = "yes"\n', "relations.split_test"),
        ("[selection]\ninclude = 5\n", "codeseam.toml: selection.include"),
        ('[selection]\nexclude = ["ok", 1]\n', "selection.exclude"),
        ("[assessment]\nno_such_threshold = 0.5\n", "assessment.no_such_threshold"),
        ('[assessment.fit]\nhigh_hole_count_at = "4"\n', "assessment.fit.high_hole_count_at"),
        ("[assessment]\nfit = 3\n", "assessment.fit"),
        ("[output]\nroot = 5\n", "output.root must be a string, not 5"),
        ("[agent_summary]\nmax_targets = -1\n", "agent_summary.max_targets"),
        ("[agent_summary]\nmax_targets = true\n", "agent_summary.max_targets"),
        ('[semantics]\ntrust_project_code = "yes"\n', "semantics.trust_project_code"),
        ("[outputs]\nroot = 'x'\n", r"unknown section \[outputs\]"),
        ("[cache]\nenable = false\n", "unknown setting cache.enable"),
        ("output = 'x'\n", r"\[output\] must be a table"),
        ('[project]\nrepo_root = "../elsewhere"\n', "project.repo_root must be inside"),
    ],
)
def test_invalid_setting_types_are_config_errors(tmp_path: Path, toml: str, message: str) -> None:
    (tmp_path / "codeseam.toml").write_text(toml, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


def test_single_pattern_strings_become_pattern_lists(tmp_path: Path) -> None:
    (tmp_path / "codeseam.toml").write_text('[selection]\ninclude = "src/**"\n', encoding="utf-8")
    (tmp_path / ".codeseamignore").write_text("build/**\n", encoding="utf-8")

    selection = load_config(tmp_path).selection

    assert selection.include == ("src/**",)
    assert selection.exclude == ("build/**",)


def test_assessment_overrides_reach_the_policy(tmp_path: Path) -> None:
    (tmp_path / "codeseam.toml").write_text(
        "[assessment]\nrecommended_edit_threshold = 1\n[assessment.fit]\nhigh_hole_count_at = 5\n",
        encoding="utf-8",
    )

    policy = load_config(tmp_path).assessment

    assert policy.recommended_edit_threshold == 1.0
    assert policy.fit.high_hole_count_at == HIGH_HOLE_COUNT_OVERRIDE
    assert policy.payoff == AssessmentPolicy().payoff


def test_bad_values_name_their_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESEAM_CACHE_ENABLED", "maybe")

    with pytest.raises(ConfigError, match="environment: cache.enabled must be true or false"):
        load_config(tmp_path)

    monkeypatch.delenv("CODESEAM_CACHE_ENABLED")
    with pytest.raises(ConfigError, match="cli: unknown setting selection.only"):
        load_config(tmp_path, {"selection.only": ["src/**"]})


@pytest.mark.parametrize(("value", "expected"), [("5", "5"), ("true", "true")])
def test_environment_paths_stay_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setenv("CODESEAM_OUTPUT_ROOT", value)

    assert load_config(tmp_path).output_root == tmp_path / expected


def test_repo_root_may_narrow_the_scan_to_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "codeseam.toml").write_text('[project]\nrepo_root = "src"\n', encoding="utf-8")

    assert load_config(tmp_path).repo_root == tmp_path / "src"


def test_config_is_immutable(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    with pytest.raises(AttributeError):
        config.cache_enabled = False  # type: ignore[misc]
