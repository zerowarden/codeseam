"""The completeness summary separates "no finding" from "not enough analysis"."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from codeseam import cli
from codeseam.analysis.completeness import (
    CompletenessInputs,
    Coverage,
    FileOutcome,
    completeness_summary,
    file_outcome,
)

CLEAN = CompletenessInputs(
    source_files=10,
    diagnostics={},
    unsupported_source_files={},
    function_count=40,
    comparison_stats={"candidate_pair_count": 12},
)


@pytest.mark.parametrize(
    ("diagnostics", "outcome"),
    [
        ((), FileOutcome.ANALYSED),
        (("python_parse_error: invalid syntax (line 3)",), FileOutcome.FAILED),
        (("extraction_failed: OSError: boom",), FileOutcome.FAILED),
        (("tree_sitter_parse_error: no functions recovered",), FileOutcome.FAILED),
        (
            ("tree_sitter_parse_error: 2 function(s) recovered from syntax errors",),
            FileOutcome.PARTIAL,
        ),
        (("source_changed: a.py changed after the repository scan",), FileOutcome.CHANGED),
    ],
)
def test_diagnostics_map_to_file_outcomes(
    diagnostics: tuple[str, ...], outcome: FileOutcome
) -> None:
    assert file_outcome(diagnostics) is outcome


@pytest.mark.parametrize(
    ("change", "coverage", "reason"),
    [
        ({}, Coverage.COMPLETE, None),
        (
            {"diagnostics": {"a.py": ("python_parse_error: x",)}},
            Coverage.PARTIAL,
            "could not be parsed",
        ),
        ({"unsupported_source_files": {"Go": 3}}, Coverage.PARTIAL, "unsupported languages (Go)"),
        (
            {"comparison_stats": {"candidate_pairs_truncated_count": 5}},
            Coverage.COMPLETE,
            None,
        ),
        (
            {"semantic_requested": True, "semantic_caveats": ("semantic_provider_untrusted",)},
            Coverage.PARTIAL,
            "semantic_provider_untrusted",
        ),
        ({"function_count": 0}, Coverage.INSUFFICIENT, "no functions"),
        ({"source_files": 0}, Coverage.INSUFFICIENT, "no source files"),
        ({"unsupported_source_files": {"Java": 30}}, Coverage.INSUFFICIENT, "Java"),
        (
            {"diagnostics": {f"{index}.py": ("python_parse_error: x",) for index in range(5)}},
            Coverage.INSUFFICIENT,
            "5 file(s) could not be parsed",
        ),
    ],
    ids=[
        "complete",
        "failed-file",
        "unsupported-files",
        "comparison-limit",
        "semantic-not-run",
        "no-functions",
        "no-files",
        "mostly-unsupported",
        "half-failed",
    ],
)
def test_coverage_and_reasons(
    change: dict[str, object], coverage: Coverage, reason: str | None
) -> None:
    summary = completeness_summary(replace(CLEAN, **change))  # type: ignore[arg-type]

    assert summary.coverage is coverage
    if reason is None:
        assert summary.reasons == ()
    else:
        assert any(reason in item for item in summary.reasons)


def _analyze(
    repo: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]
) -> dict[str, object]:
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    for name, source in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    monkeypatch.chdir(repo)
    cli.main(["analyze", "--quiet"])
    metrics = json.loads((repo / ".codeseam/reports/agent/metrics.json").read_text())
    return {
        "completeness": metrics["completeness"],
        "summary": (repo / ".codeseam/reports/agent/summary.md").read_text(),
    }


def test_a_broken_file_makes_the_run_partial_and_the_summary_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _analyze(
        tmp_path,
        monkeypatch,
        {
            "src/good.py": "def run(x):\n    return x\n",
            "src/other.py": "def walk(y):\n    return y\n",
            "src/broken.py": "def broken(:\n",
        },
    )
    completeness = run["completeness"]

    assert completeness["coverage"] == "partial"  # type: ignore[index]
    assert completeness["files"] == {"analysed": 2, "changed": 0, "failed": 1, "partial": 0}  # type: ignore[index]
    assert "## Analysis Completeness" in str(run["summary"])
    assert "analysis was not complete" in str(run["summary"])


def test_a_repository_in_an_unsupported_language_is_insufficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _analyze(
        tmp_path,
        monkeypatch,
        {
            "main.go": "package main\n",
            "util.go": "package main\n",
            "tool.py": "def t():\n    pass\n",
        },
    )
    completeness = run["completeness"]

    assert completeness["coverage"] == "insufficient"  # type: ignore[index]
    assert completeness["unsupported_source_files"] == {"Go": 2}  # type: ignore[index]


def test_comparison_limits_are_notes_not_lost_coverage() -> None:
    stats = {"candidate_pairs_truncated_count": 5, "candidate_bucket_members_truncated_count": 2}
    summary = completeness_summary(replace(CLEAN, comparison_stats=stats))

    assert summary.coverage is Coverage.COMPLETE
    assert summary.notes[0].startswith("5 low-ranked candidate pair(s)")
    assert summary.notes[1].startswith("2 bucket place(s)")
