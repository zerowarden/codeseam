from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from codeseam.analysis import (
    EVIDENCE_ANTI_UNIFICATION_TEMPLATE,
    AssessmentBand,
    AssessmentPolicy,
    EvidenceSummary,
    FindingMetrics,
    score_abstraction_fit,
)
from codeseam.config import load_config

POLICY = AssessmentPolicy.from_config(load_config(Path("/repo")).data)
HIGH_COST = 0.90
LOW_COST = 0.10
HIGH_RISK = 0.50
LOW_RISK = 0.05
HIGH_HOLE_COUNT = 3
HIGH_HOLE_SIZE = 8
WEAK_REGION_SIZE = 1
STRONG_REGION_SIZE = 5


@dataclass(frozen=True)
class FitPenaltyCase:
    name: str
    higher: float
    lower: float
    apply: Callable[[FindingMetrics, float], FindingMetrics]


def test_structural_duplicate_with_low_cost_has_strong_fit() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_abstraction_cost_score=LOW_COST,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score >= POLICY.fit_high_threshold
    assert fit.reasons[:2] == ("structural_duplicate", "stable_common_statement_region")


def test_high_abstraction_cost_caps_fit() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_refactorability_score=1.0,
            max_abstraction_cost_score=HIGH_COST,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score <= POLICY.fit.high_cost_cap
    assert fit.reasons[-1] == "high_abstraction_cost_cap"


def test_weak_common_region_caps_structural_relation_fit() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            max_refactorability_score=1.0,
            max_stable_statement_count=WEAK_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score <= POLICY.fit.weak_common_region_cap
    assert fit.reasons[-1] == "weak_common_region_cap"


def test_signature_only_recurrence_is_low_fit() -> None:
    fit = score_abstraction_fit(FindingMetrics(member_count=4), POLICY)

    assert fit.score < POLICY.fit_medium_threshold
    assert fit.band is AssessmentBand.LOW


def test_structural_relation_without_hole_metrics_is_not_perfectly_simple() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            max_refactorability_score=1.0,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )

    assert "hole_metrics_unavailable" in fit.reasons
    assert fit.score < POLICY.fit_high_threshold


def test_known_zero_holes_are_perfectly_simple() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            max_refactorability_score=1.0,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
        evidence=EvidenceSummary.from_classes((EVIDENCE_ANTI_UNIFICATION_TEMPLATE,)),
    )

    assert "hole_metrics_unavailable" not in fit.reasons


def test_high_relation_risk_caps_fit() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_refactorability_score=1.0,
            max_relation_risk_score=HIGH_RISK,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score <= POLICY.fit.high_risk_cap
    assert "high_relation_risk_cap" in fit.reasons


def test_same_role_does_not_rescue_near_high_relation_risk() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            same_role_relation_count=1,
            max_refactorability_score=1.0,
            max_relation_risk_score=0.34,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
        evidence=EvidenceSummary.from_classes((EVIDENCE_ANTI_UNIFICATION_TEMPLATE,)),
    )

    assert fit.score < POLICY.fit_high_threshold


@pytest.mark.parametrize(
    "case",
    [
        FitPenaltyCase(
            "abstraction cost",
            HIGH_COST,
            LOW_COST,
            lambda metrics, value: replace(metrics, max_abstraction_cost_score=value),
        ),
        FitPenaltyCase(
            "relation risk",
            HIGH_RISK,
            LOW_RISK,
            lambda metrics, value: replace(metrics, max_relation_risk_score=value),
        ),
    ],
    ids=lambda case: case.name,
)
def test_fit_does_not_increase_when_penalty_increases(case: FitPenaltyCase) -> None:
    base = FindingMetrics(
        member_count=2,
        structural_duplicate_pair_count=1,
        max_stable_statement_count=STRONG_REGION_SIZE,
    )

    lower = score_abstraction_fit(
        case.apply(base, case.lower),
        POLICY,
    )
    higher = score_abstraction_fit(
        case.apply(base, case.higher),
        POLICY,
    )

    assert higher.score <= lower.score


def test_fit_does_not_increase_when_holes_grow() -> None:
    simple = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )
    complex_holes = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_stable_statement_count=STRONG_REGION_SIZE,
            max_hole_count=HIGH_HOLE_COUNT,
            max_hole_size=HIGH_HOLE_SIZE,
        ),
        POLICY,
    )

    assert complex_holes.score <= simple.score


def test_refactorability_score_does_not_suppress_duplicate_evidence() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_duplicate_pair_count=1,
            max_refactorability_score=0.20,
            max_stable_statement_count=STRONG_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score >= POLICY.fit_high_threshold


def test_body_hash_match_is_strong_commonality_evidence() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            structural_relation_pair_count=1,
            body_hash_match_count=1,
            max_refactorability_score=0.20,
            max_stable_statement_count=WEAK_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score >= POLICY.fit_high_threshold
    assert "body_hash_match" in fit.reasons


def test_policy_constant_duplicate_is_strong_commonality_evidence() -> None:
    fit = score_abstraction_fit(
        FindingMetrics(
            member_count=2,
            policy_constant_duplicate_count=1,
            max_stable_statement_count=WEAK_REGION_SIZE,
        ),
        POLICY,
    )

    assert fit.score >= POLICY.fit_high_threshold
    assert "policy_constant_duplicate" in fit.reasons
