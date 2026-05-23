from __future__ import annotations

import json

import pytest
from factories import ci_member, ci_summary, ci_target
from helpers import assert_contains

from codeseam.analysis import ReviewTier
from codeseam.cli import REVIEW_TIER_LABELS

from .fixtures import CliRunner


@pytest.mark.integration
def test_analyze_ci_outputs_compact_summary_only(cli_runner: CliRunner) -> None:
    result = cli_runner(["analyze", "--ci"])
    assert result.stderr == ""
    assert_contains(
        result.stdout,
        [
            "Analysis completed.",
            "Files analysed:",
            "Files skipped:",
            "Analysis:",
            f"{REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT]}: 0",
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
            REVIEW_TIER_LABELS[ReviewTier.MAINTENANCE_NOTE],
            REVIEW_TIER_LABELS[ReviewTier.OBSERVATION],
            "CI surface:",
            "No failing targets surfaced.",
            "Full results kept in artifacts:",
            "- .codeseam/reports/ci/codeseam-report.json",
            "- .codeseam/reports/ci/codeseam-report.sarif",
            "- .codeseam/reports/ci/codeseam-summary.md",
        ],
    )


def test_ci_summary_lists_failing_recommended_edits() -> None:
    output = ci_summary(
        [
            ci_target(
                "rt_low",
                confidence=0.99,
                review_score=0.1,
                title="High confidence but lower score",
            ),
            ci_target(
                "rt_high",
                confidence=0.5,
                review_score=0.8,
                title="Higher review score",
                members=[ci_member("src/high.py", 10, 12, "\nhigh")],
            ),
            ci_target(
                "rt_fix",
                review_tier=ReviewTier.RECOMMENDED_EDIT,
                confidence=0.95,
                review_score=0.2,
                title="Recommended edit",
                members=[ci_member("src/fix.py", 10, 12, "fix")],
            ),
            ci_target(
                "rt_not_summary",
                confidence=1.0,
                title="Not summary eligible",
                summary_eligible=False,
            ),
            ci_target(
                "rt_low_value",
                confidence=1.0,
                title="Low-value low-refactorability",
                refactor_value="low",
                refactorability_score=0.9,
            ),
        ],
    )

    assert_contains(
        output,
        [
            "Failing targets:",
            "rt_fix",
            "Reason: Review supporting evidence",
            "Action: Consolidate clone",
            "Members:",
            "   - src/fix.py:10-12 fix",
        ],
    )
    assert "Scores:" not in output


@pytest.mark.integration
def test_analyze_ci_json_outputs_machine_payload_only(cli_runner: CliRunner) -> None:
    result = cli_runner(["analyze", "--ci", "--format", "json"])
    payload = json.loads(result.stdout)
    assert result.stderr == ""
    assert payload["schema_version"] == "codeseam.ci_report.v1"
    assert payload["ci"]["enabled"] is True
    assert "threshold_breached" not in payload["ci"]
