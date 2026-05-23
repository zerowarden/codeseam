from __future__ import annotations

import pytest

from codeseam.output.serializers.finding_buckets import (
    canonical_analysis_targets,
    is_analysis_target,
    partition_analysis_targets,
)
from codeseam.platform import Json


@pytest.mark.parametrize(
    ("review_tier", "expected"),
    (
        ("recommended_edit", True),
        ("review_candidate", True),
        ("maintenance_note", True),
        ("observation", False),
    ),
)
def test_analysis_sidecar_follows_final_review_tier(
    review_tier: str,
    expected: bool,
) -> None:
    assert is_analysis_target({"review_tier": review_tier}) is expected


def test_analysis_sidecar_excludes_suppressed_targets() -> None:
    assert (
        is_analysis_target(
            {
                "review_tier": "recommended_edit",
                "lifecycle": {"suppressed": True},
            }
        )
        is False
    )


def test_partition_keeps_observations_observation_only() -> None:
    analysis, observations = partition_analysis_targets(
        [
            _target("rt_fix", "recommended_edit"),
            _target("rt_review", "review_candidate"),
            _target("rt_note", "maintenance_note"),
            _target("rt_obs", "observation"),
        ]
    )

    assert [target["target_id"] for target in analysis] == [
        "rt_fix",
        "rt_review",
        "rt_note",
    ]
    assert [target["target_id"] for target in observations] == ["rt_obs"]


def test_canonical_analysis_targets_dedupes_by_ranked_target_id() -> None:
    canonical = canonical_analysis_targets(
        [
            _target("rt_same", "recommended_edit", title="ranked first"),
            _target("rt_other", "review_candidate"),
            _target("rt_same", "maintenance_note", title="duplicate"),
            _target("", "observation", title="anonymous"),
        ]
    )

    assert [(target["target_id"], target["title"]) for target in canonical] == [
        ("rt_same", "ranked first"),
        ("rt_other", "fixture"),
        ("", "anonymous"),
    ]


def _target(target_id: str, review_tier: str, *, title: str = "fixture") -> Json:
    return {
        "target_id": target_id,
        "review_tier": review_tier,
        "title": title,
        "lifecycle": {"suppressed": False},
    }
