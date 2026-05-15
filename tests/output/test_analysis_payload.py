from __future__ import annotations

from pathlib import Path

from factories import (
    RECOMMENDATION_CONFIDENCE,
    REVIEW_CONFIDENCE,
    analysis_payload_for_target,
    ci_target,
)

from codeseam.analysis import ReviewTier


def test_analysis_payload_confidence_is_review_confidence(tmp_path: Path) -> None:
    payload = analysis_payload_for_target(
        tmp_path,
        {
            "target_id": "rt_confidence",
            "title": "Confidence semantics",
            "review_tier": ReviewTier.REVIEW_CANDIDATE,
            "detection_confidence": REVIEW_CONFIDENCE,
            "recommendation_confidence": RECOMMENDATION_CONFIDENCE,
            "locations": [],
        },
    )

    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert isinstance(target, dict)
    assert target["confidence"] == REVIEW_CONFIDENCE
    assert target["recommendation_confidence"] == RECOMMENDATION_CONFIDENCE
    assert target["reason"] == ""
    assert "assessment_scores" in target


def test_analysis_payload_prefers_relation_pair_members(tmp_path: Path) -> None:
    payload = analysis_payload_for_target(
        tmp_path,
        {
            **ci_target("rt_clone", title="Duplicate helper"),
            "target_id": "rt_clone",
            "locations": [
                {
                    "file": "src/noise.py",
                    "start_line": 1,
                    "end_line": 1,
                    "symbol": "same_shape_noise",
                }
            ],
            "structural_relation_pairs": [
                {
                    "left": {
                        "file": "src/a.py",
                        "start_line": 10,
                        "end_line": 12,
                        "symbol": "duplicate_helper",
                    },
                    "right": {
                        "file": "src/b.py",
                        "start_line": 20,
                        "end_line": 22,
                        "symbol": "duplicate_helper",
                    },
                }
            ],
        },
    )
    targets = payload["targets"]
    assert isinstance(targets, list)
    target = targets[0]
    assert isinstance(target, dict)

    assert target["members"] == [
        {
            "path": "src/a.py",
            "start_line": 10,
            "end_line": 12,
            "symbol": "duplicate_helper",
        },
        {
            "path": "src/b.py",
            "start_line": 20,
            "end_line": 22,
            "symbol": "duplicate_helper",
        },
    ]
