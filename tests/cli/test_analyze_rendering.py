from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from factories import (
    analysis_payload_for_review_target,
    ci_target,
    output_options,
    report_artifacts,
)
from helpers import assert_contains, assert_not_contains

from codeseam.analysis import ActionKind, ReviewTier
from codeseam.cli import REVIEW_TIER_LABELS
from codeseam.cli.output import render_analyze_result
from codeseam.output.pipeline import threshold_breached


@dataclass(frozen=True, slots=True)
class AnalyzeOutputCase:
    id: str
    payload: dict[str, object]
    expected: tuple[str, ...]
    absent: tuple[str, ...] = ()
    color: str = "never"


def test_analyze_threshold_breach_detection() -> None:
    assert threshold_breached(report_artifacts(recommended_edit_tier_count=1)) is True
    assert threshold_breached(report_artifacts(recommended_edit_tier_count=0)) is False


@pytest.mark.parametrize(
    "case",
    [
        AnalyzeOutputCase(
            id="listed-review-target",
            payload={
                "evidence_classes": [
                    "anti_unification_template",
                    "body_tree_similarity",
                ],
                "locations": [
                    {
                        "file": "src/helper.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "build_helper",
                    }
                ],
            },
            expected=(
                "Top review required:",
                "review required  rt_review",
                "Reasons: Common code skeleton, similar body tree",
                "Action: Consolidate clone; maintenance payoff: medium",
                "src/helper.py:10-12::build_helper",
            ),
            absent=("1. rt_review",),
        ),
        AnalyzeOutputCase(
            id="sidecar-only-target",
            payload={
                "target_id": "rt_sidecar",
                "title": "Framework hook recurrence",
                "primary_action": ActionKind.RECORD_SHARED_CONCERN,
                "refactor_value": "none",
                "visibility": "sidecar_only",
                "summary_eligible": False,
            },
            expected=(),
            absent=("Top review required:", "rt_sidecar"),
        ),
        AnalyzeOutputCase(
            id="colored-location",
            payload={
                "locations": [
                    {
                        "file": "src/helper.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "build_helper",
                    }
                ],
            },
            expected=("\x1b[36m", "src/helper.py:10-12", "::build_helper"),
            color="always",
        ),
    ],
    ids=lambda case: case.id,
)
def test_analyze_review_candidate_output_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: AnalyzeOutputCase,
) -> None:
    payload = analysis_payload_for_review_target(tmp_path, overrides=case.payload)
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, output_options(color=case.color))

    output = capsys.readouterr().out
    assert_contains(output, case.expected)
    assert_not_contains(output, case.absent)


def test_analyze_styles_review_tier_labels_when_enabled(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = analysis_payload_for_review_target(tmp_path)
    targets = payload["targets"]
    assert isinstance(targets, list)
    targets.append(
        ci_target(
            "rt_fix",
            title="Duplicate helper",
            review_tier=ReviewTier.RECOMMENDED_EDIT,
        )
    )
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, output_options(color="always"))

    output = capsys.readouterr().out
    assert "recommended edits" in output
    assert "review required" in output
    assert "\x1b[1;31mrecommended edits" in output
    assert "\x1b[1;38;5;" in output and "review required" in output


def test_analyze_shows_top_ten_combined_review_targets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_review_output_count = 9
    payload = analysis_payload_for_review_target(
        tmp_path,
        target_id="rt_fix",
        title="Recommended edit",
        review_tier=ReviewTier.RECOMMENDED_EDIT,
    )
    targets = payload["targets"]
    assert isinstance(targets, list)
    for index in range(12):
        targets.append(
            ci_target(
                f"rt_review_{index}",
                title=f"Review required {index}",
                primary_action=ActionKind.RECORD_SHARED_CONCERN,
                refactor_value="low",
                review_score=1.0 - (index / 100),
            )
        )
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, output_options())

    output = capsys.readouterr().out
    assert "recommended edits  rt_fix" in output
    for index in range(expected_review_output_count):
        assert f"review required  rt_review_{index}" in output
    assert f"review required  rt_review_{expected_review_output_count}" not in output
    assert output.count("review required  rt_review_") == expected_review_output_count


def test_analyze_prints_review_tier_labels_from_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = analysis_payload_for_review_target(tmp_path)
    payload["timings"] = {"elapsed_seconds": 0.01}

    render_analyze_result(payload, output_options())

    assert_contains(
        capsys.readouterr().out,
        [
            REVIEW_TIER_LABELS[ReviewTier.RECOMMENDED_EDIT],
            REVIEW_TIER_LABELS[ReviewTier.REVIEW_CANDIDATE],
        ],
    )
