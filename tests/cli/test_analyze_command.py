from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import (
    assert_contains,
    assert_not_contains,
    assert_paths_absent,
    assert_paths_exist,
    repo_dir,
)

from codeseam.analysis import ReviewTier
from codeseam.cli import CONFIG_ERROR, REPOSITORY_CONTEXT_ERROR, REVIEW_TIER_LABELS

from .fixtures import CliRunner


@pytest.mark.integration
def test_analyze_writes_artifacts(cli_runner: CliRunner, tmp_path: Path) -> None:
    cli_runner(["analyze"])
    output_root = tmp_path / ".codeseam" / "reports"
    assert_paths_exist(
        output_root,
        [
            "manifest.json",
            "README.md",
            "agent/summary.md",
            "agent/analysis.jsonl",
            "agent/observations.jsonl",
            "agent/metrics.json",
        ],
    )
    assert_paths_absent(
        output_root,
        [
            "raw",
            "context",
            "functions.jsonl",
            "function_inventory_summary.json",
            "signatures.jsonl",
            "signature_clusters.json",
            "findings.jsonl",
        ],
    )


@pytest.mark.integration
def test_analyze_prints_human_summary(cli_runner: CliRunner) -> None:
    output = cli_runner(["analyze"]).stdout
    assert_contains(
        output,
        [
            "Analyzed",
            "Discovered",
            "functions. Made",
            "Analysis:",
            REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT],
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
            REVIEW_TIER_LABELS[ReviewTier.MAINTENANCE_NOTE],
            "observations.",
        ],
    )
    assert_not_contains(output, ["total"])


@pytest.mark.integration
def test_analyze_show_exclusions_prints_default_patterns(cli_runner: CliRunner) -> None:
    output = cli_runner(["analyze", "--show-exclusions", "--color", "never"]).stdout
    assert_contains(output, ["Default exclusions:", "- node_modules/**"])


@pytest.mark.integration
def test_analyze_explain_files_summarizes_skipped_groups(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("def app() -> int:\n    return 1\n", encoding="utf-8")
    (tmp_path / "src" / "ignored.py").write_text(
        "def ignored() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("function x() {}", encoding="utf-8")

    output = cli_runner(
        [
            "analyze",
            "--explain-files",
            "--include",
            "src/*.py",
            "--exclude",
            "src/ignored.py",
            "--color",
            "never",
        ]
    ).stdout

    assert_contains(
        output,
        [
            "Analysed: 1 files",
            "Skipped:",
            "Top skipped groups:",
            "- node_modules/: 1",
            "- src/: 1",
        ],
    )


@pytest.mark.integration
def test_analyze_debug_writes_debug_bundle_only(cli_runner: CliRunner, tmp_path: Path) -> None:
    cli_runner(["analyze", "--debug"])
    output_root = tmp_path / ".codeseam" / "reports"
    assert_paths_exist(output_root, ["debug.jsonl.gz"])
    assert_paths_absent(output_root, ["raw", "context", "normalized", "evidence"])


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["analyze", "--repo-root", "repo"], id="option"),
        pytest.param(["analyze", "repo", "--quiet"], id="positional"),
    ],
)
@pytest.mark.integration
def test_analyze_accepts_repo_path(
    cli_runner: CliRunner,
    tmp_path: Path,
    args: list[str],
) -> None:
    repo = repo_dir(tmp_path)
    cli_runner(args)

    assert (repo / ".codeseam" / "reports" / "manifest.json").exists()


@pytest.mark.parametrize(
    ("path", "create_file"),
    [
        pytest.param("missing", False, id="missing"),
        pytest.param("repo.txt", True, id="file"),
    ],
)
@pytest.mark.parametrize(
    "repo_arg_style",
    [
        pytest.param("positional", id="positional"),
        pytest.param("option", id="option"),
    ],
)
def test_analyze_invalid_repo_path_returns_repository_context_error(
    cli_runner: CliRunner,
    tmp_path: Path,
    path: str,
    create_file: bool,
    repo_arg_style: str,
) -> None:
    repo_path = tmp_path / path
    if create_file:
        repo_path.write_text("not a directory", encoding="utf-8")

    args = ["analyze", path] if repo_arg_style == "positional" else ["analyze", "--repo-root", path]
    cli_runner(args, expected=REPOSITORY_CONTEXT_ERROR)
    assert repo_path.is_dir() is False
    assert repo_path.exists() is create_file


@pytest.mark.integration
def test_analyze_json_format_outputs_machine_summary(cli_runner: CliRunner) -> None:
    output = cli_runner(["analyze", "--format", "json", "--target-limit", "1", "--timings"]).stdout
    payload = json.loads(output)
    assert payload["schema_version"] == "1.0"
    assert payload["codeseam_version"] == "0.1.0"
    assert payload["summary"]["files_analysed"] >= 0
    assert payload["summary"]["files_skipped"] >= 0
    assert payload["summary"]["functions_seen"] >= 0
    assert "findings" in payload
    assert payload["target_limit"] == 1
    assert "targets" in payload
    assert "timings" in payload
    assert payload["timings"]["cache"]["schema_version"] == "codeseam.cache_run_stats.v1"
    assert "namespaces" in payload["timings"]["cache"]


@pytest.mark.integration
def test_analyze_json_format_can_write_output_file(
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    output = tmp_path / "report.json"

    result = cli_runner(["analyze", "--format", "json", "--output", str(output)])

    assert result.stdout == ""
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_analyze_sarif_format_is_reserved(cli_runner: CliRunner) -> None:
    cli_runner(["analyze", "--format", "sarif"], expected=CONFIG_ERROR)
