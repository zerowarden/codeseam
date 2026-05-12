from __future__ import annotations

from pathlib import Path

from codeseam.analysis import (
    AssessmentBand,
    AssessmentPolicy,
    FindingMetrics,
    RelationKind,
    score_maintenance_payoff,
)
from codeseam.config import load_config

POLICY = AssessmentPolicy.from_config(load_config(Path("/repo")).data)
GENERATED_VENDOR_CAP = 0.1


def test_relation_kind_count_does_not_create_spread() -> None:
    payoff = score_maintenance_payoff(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            relation_kind_counts={
                RelationKind.BODY_PARAMETERIZED: 1,
                RelationKind.COMMON_WRAPPER_DIFFERENT_CORE: 1,
            },
        ),
        roles=["source"],
        line_span=0,
        distinct_file_count=None,
        policy=POLICY,
    )

    assert payoff.reasons == ("structural_relation", "recurrent_members", "source_code")


def test_distinct_files_are_explicit_spread_signal() -> None:
    payoff = score_maintenance_payoff(
        FindingMetrics(member_count=2, structural_relation_pair_count=1),
        roles=["source"],
        line_span=0,
        distinct_file_count=2,
        policy=POLICY,
    )

    assert "file_spread" in payoff.reasons


def test_generated_or_vendor_payoff_is_capped() -> None:
    payoff = score_maintenance_payoff(
        FindingMetrics(member_count=12, structural_duplicate_pair_count=6),
        roles=["generated"],
        line_span=500,
        distinct_file_count=12,
        policy=POLICY,
    )

    assert payoff.score == GENERATED_VENDOR_CAP
    assert payoff.band is AssessmentBand.LOW


def test_test_only_payoff_uses_lower_exposure() -> None:
    source_payoff = score_maintenance_payoff(
        FindingMetrics(member_count=4, structural_relation_pair_count=2),
        roles=["source"],
        line_span=40,
        distinct_file_count=2,
        policy=POLICY,
    )
    test_payoff = score_maintenance_payoff(
        FindingMetrics(member_count=4, structural_relation_pair_count=2),
        roles=["test", "fixture"],
        line_span=40,
        distinct_file_count=2,
        policy=POLICY,
    )

    assert test_payoff.score < source_payoff.score
    assert "test_or_fixture_only" in test_payoff.reasons
