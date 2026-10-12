from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeseam.analysis import (
    AbstractionKind,
    ActionKind,
    ActionStatus,
    AssessmentBand,
    AssessmentBreakdown,
    CloneClass,
    Cluster,
    EvidenceItem,
    EvidenceKind,
    EvidenceStrength,
    FileRecord,
    Finding,
    FindingActionStatus,
    FindingDraft,
    FindingLocation,
    FindingMetrics,
    FindingReviewVisibility,
    FindingTargetType,
    FunctionSemanticRole,
    MemberRef,
    RecommendationCap,
    RefactorAction,
    RelationKind,
    RelationPair,
    RepositoryFacts,
    RepositoryScan,
    ReviewTier,
    SemanticCapAssessment,
    _structural_metrics,
    _sync_async_member_pair,
    apply_semantic_cap,
    assess_target,
    build_findings,
    build_repository_facts,
    semantic_cap_for,
)
from codeseam.analysis.assessment.findings import (
    _dedupe_equivalent_findings,
    _with_unique_identities,
)
from codeseam.analysis.findings.drafts import promotable_components, should_promote
from codeseam.analysis.findings.identity import with_target_identity
from codeseam.config import load_config
from codeseam.pipeline.signatures import build_signature_artifacts

POLICY = load_config(Path("/repo")).assessment
FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "signatures"
EXPECTED_MEMBER_PATH_COUNT = 2
EXPECTED_ALL_PAIR_COUNT = 2
EXPECTED_RELATEDNESS = 0.91
EXPECTED_REFACTORABILITY = 0.82
EXPECTED_CONFIDENCE = 0.94


def test_signature_only_target_is_observation() -> None:
    target = _assess({"member_count": 2}, has_signature_overlap=True)

    assert target.review_tier is ReviewTier.OBSERVATION
    assert target.evidence_strength is EvidenceStrength.WEAK
    assert target.primary_action == ActionKind.OBSERVE


def test_cross_language_signature_only_target_stays_observational() -> None:
    target = _assess(
        {
            "member_count": 2,
            "cluster_scope": "cross_language",
            "language_count": 2,
            "adapter_count": 2,
        },
        has_signature_overlap=True,
    )

    assert target.review_tier is ReviewTier.OBSERVATION
    assert target.primary_action == ActionKind.OBSERVE
    assert _assessment(target).semantic_risk.score > 0


def test_clean_clone_is_recommended_edit() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_duplicate_pair_count": 1,
            "structural_relation_pair_count": 1,
            "body_hash_match_count": 1,
            "lead_tree_similarity": 1.0,
            "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.8,
            "lead_abstraction_cost_score": 0.22,
            "lead_risk_score": 0.0,
            "__line_span": 120,
        },
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.action_status is FindingActionStatus.RECOMMENDED_EDIT
    assert target.primary_action == ActionKind.CONSOLIDATE_CLONE
    assert _assessment(target).action_recommendation.status == "recommended"


def test_small_clean_clone_is_recommended_edit() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_duplicate_pair_count": 1,
            "structural_relation_pair_count": 1,
            "body_hash_match_count": 1,
            "lead_tree_similarity": 1.0,
            "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.8,
            "lead_abstraction_cost_score": 0.22,
            "lead_risk_score": 0.0,
        },
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert _assessment(target).maintenance_payoff.band is AssessmentBand.LOW


@pytest.mark.parametrize(
    ("role_counts", "cap_counts", "expected_tier", "expected_action", "expected_status"),
    (
        (
            {
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD.value: 2,
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 2,
            },
            {"protocol_member_count": 2},
            "maintenance_note",
            ActionKind.RECORD_SHARED_CONCERN,
            "record_shared_concern",
        ),
        (
            {FunctionSemanticRole.TYPING_OVERLOAD.value: 2},
            {"interface_only_member_count": 2},
            "observation",
            ActionKind.DO_NOT_REFACTOR,
            "do_not_refactor",
        ),
        (
            {FunctionSemanticRole.ADAPTER_FORWARDER.value: 2},
            {"api_surface_member_count": 2},
            "maintenance_note",
            ActionKind.RECORD_SHARED_CONCERN,
            "record_shared_concern",
        ),
        (
            {FunctionSemanticRole.IMPLEMENTATION_CONTRACT_METHOD.value: 2},
            {"api_surface_member_count": 2},
            "maintenance_note",
            ActionKind.RECORD_SHARED_CONCERN,
            "record_shared_concern",
        ),
        (
            {FunctionSemanticRole.FRAMEWORK_CONNECTOR.value: 2},
            {"api_surface_member_count": 2},
            "maintenance_note",
            ActionKind.RECORD_SHARED_CONCERN,
            "record_shared_concern",
        ),
        (
            {FunctionSemanticRole.TRIVIAL_BODY.value: 2},
            {},
            "maintenance_note",
            ActionKind.RECORD_SHARED_CONCERN,
            "record_shared_concern",
        ),
    ),
)
def test_semantic_role_caps_demote_protocol_surface_clones(
    role_counts: dict[str, int],
    cap_counts: dict[str, int],
    expected_tier: str,
    expected_action: str,
    expected_status: str,
) -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_duplicate_pair_count": 1,
            "structural_relation_pair_count": 1,
            "body_hash_match_count": 1,
            "lead_tree_similarity": 1.0,
            "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.8,
            "lead_abstraction_cost_score": 0.22,
            "lead_risk_score": 0.0,
            "max_body_line_count": 3,
            "semantic_role_counts": role_counts,
            **cap_counts,
            "__line_span": 120,
        },
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier == expected_tier
    assert target.primary_action == expected_action
    assert target.action_status == expected_status
    assert any("Semantic role cap" in reason for reason in target.downgrade_reasons)


def test_constructor_duplication_steers_to_shared_helper_review() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_duplicate_pair_count": 1,
            "structural_relation_pair_count": 1,
            "body_hash_match_count": 1,
            "lead_tree_similarity": 1.0,
            "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.8,
            "lead_abstraction_cost_score": 0.22,
            "lead_risk_score": 0.0,
            "max_body_line_count": 14,
            "min_body_line_count": 14,
            "lead_stable_statement_count": 6,
            "min_stable_statement_count": 6,
            "same_directory_relation_count": 1,
            "semantic_role_counts": {
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD.value: 2,
                FunctionSemanticRole.CONSTRUCTOR.value: 2,
            },
            "__line_span": 160,
        },
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert target.action_status is FindingActionStatus.CAUTIOUS_CANDIDATE
    assert target.primary_action == ActionKind.EXTRACT_SMALL_HELPER


def test_constructor_majority_steers_to_shared_helper_review() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.CONSTRUCTOR.value: 4,
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD.value: 4,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 1,
            },
            body_lines=14,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={"member_count": 5},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert target.action_status is FindingActionStatus.CAUTIOUS_CANDIDATE
    assert target.primary_action == ActionKind.EXTRACT_SMALL_HELPER


def test_small_constructor_majority_still_steers_to_review() -> None:
    # Constructor merges change a class hierarchy whatever their size; only
    # one-operation constructors drop to notes, through the trivial-body cap.
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.CONSTRUCTOR.value: 4,
                FunctionSemanticRole.PYTHON_SPECIAL_METHOD.value: 4,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 1,
            },
            body_lines=3,
            stable_statements=1,
            same_directory_relation_count=1,
            cap_counts={"member_count": 5},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is not ReviewTier.RECOMMENDED_EDIT
    assert target.primary_action == ActionKind.EXTRACT_SMALL_HELPER


def test_public_api_mirror_needs_substantial_local_evidence_for_review() -> None:
    maintenance_note = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.PUBLIC_API_MIRROR.value: 2},
            body_lines=6,
            stable_statements=4,
            same_directory_relation_count=0,
            cap_counts={"api_surface_member_count": 2},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )
    review = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.PUBLIC_API_MIRROR.value: 2},
            body_lines=12,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={"api_surface_member_count": 2},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert maintenance_note.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert maintenance_note.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert review.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert review.action_status is FindingActionStatus.CAUTIOUS_CANDIDATE
    assert review.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_public_api_mirror_does_not_relax_from_one_large_member() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.PUBLIC_API_MIRROR.value: 2},
            body_lines=(20, 3),
            stable_statements=(8, 2),
            same_directory_relation_count=1,
            cap_counts={"api_surface_member_count": 2},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_command_registry_surface_caps_edit_to_maintenance_note() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.COMMAND_OR_REGISTRY_SURFACE.value: 2},
            body_lines=7,
            stable_statements=4,
            same_directory_relation_count=0,
            cap_counts={"api_surface_member_count": 2},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any("adapter/API boundary" in reason for reason in target.downgrade_reasons)


@pytest.mark.parametrize(
    ("coverage", "reason"),
    [
        ({"promoted_pair_count": 1, "promoted_member_count": 2}, "Clone evidence was promoted"),
        # A guarded pair (two `pass` stubs) is never promoted, but must not profile its parent.
        ({"pair_member_count": 2}, "Pair evidence covers only some members"),
    ],
    ids=["promoted", "not-promoted"],
)
def test_sparse_pair_evidence_caps_broad_parent_cluster(
    coverage: dict[str, int], reason: str
) -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.NORMAL_FUNCTION.value: 8},
            body_lines=12,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={
                "member_count": 8,
                "structural_duplicate_pair_count": 1,
                "structural_relation_pair_count": 1,
                **coverage,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any(reason in item for item in target.downgrade_reasons)


def test_promoted_pair_parent_cap_wins_over_test_review_cap() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.TEST_CODE.value: 1},
            body_lines=16,
            stable_statements=1,
            same_directory_relation_count=1,
            cap_counts={
                "member_count": 3,
                "structural_duplicate_pair_count": 0,
                "structural_relation_pair_count": 1,
                "promoted_pair_count": 1,
                "promoted_member_count": 2,
                "test_member_count": 3,
                "test_relation_pair_count": 1,
                "guardrail_relation_pair_count": 1,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.SIGNATURE_SHAPE_CLUSTER,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any("Clone evidence was promoted" in reason for reason in target.downgrade_reasons)


def test_promoted_pair_cap_does_not_apply_when_pair_members_cover_parent() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=3,
            structural_duplicate_pair_count=3,
            structural_relation_pair_count=3,
            promoted_pair_count=3,
            promoted_member_count=3,
            semantic_role_counts={FunctionSemanticRole.NORMAL_FUNCTION.value: 3},
        ),
        POLICY,
    )

    assert cap.cap == RecommendationCap.ALLOW_RECOMMENDED_EDIT


def test_protocol_singleton_duplicate_pair_caps_mixed_cluster() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=5,
            structural_duplicate_pair_count=1,
            semantic_role_counts={
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 2,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 3,
            },
            protocol_member_count=2,
            guardrail_relation_pair_count=10,
            protocol_duplicate_pair_count=1,
            protocol_relation_pair_count=1,
            max_body_line_count=3,
            min_body_line_count=3,
        ),
        POLICY,
    )
    capped = apply_semantic_cap(
        review_tier=ReviewTier.RECOMMENDED_EDIT,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
        cap=cap,
    )

    assert cap.cap == RecommendationCap.MAX_MAINTENANCE_NOTE
    assert capped.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any("protocol/API methods" in reason for reason in capped.downgrade_reasons)


def test_protocol_non_dominant_duplicate_pair_does_not_cap_mixed_cluster() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=5,
            structural_duplicate_pair_count=3,
            semantic_role_counts={
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 2,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 3,
            },
            protocol_member_count=2,
            guardrail_relation_pair_count=10,
            protocol_duplicate_pair_count=1,
            protocol_relation_pair_count=1,
        ),
        POLICY,
    )

    assert cap.cap == RecommendationCap.ALLOW_RECOMMENDED_EDIT


def test_non_tiny_test_duplicate_caps_to_review_candidate() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=3,
            structural_duplicate_pair_count=3,
            semantic_role_counts={FunctionSemanticRole.TEST_CODE.value: 3},
            test_member_count=3,
            max_body_line_count=12,
        ),
        POLICY,
    )

    assert cap.cap == RecommendationCap.MAX_REVIEW_CANDIDATE


def test_tiny_test_duplicate_member_family_caps_to_review_candidate_not_observation() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=3,
            structural_duplicate_pair_count=1,
            semantic_role_counts={FunctionSemanticRole.TEST_CODE.value: 3},
            test_member_count=3,
            max_body_line_count=1,
        ),
        POLICY,
    )
    capped = apply_semantic_cap(
        review_tier=ReviewTier.RECOMMENDED_EDIT,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
        cap=cap,
    )

    assert cap.cap == RecommendationCap.MAX_REVIEW_CANDIDATE
    assert capped.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_clean_exact_test_helper_clone_can_remain_recommended_edit() -> None:
    metrics = _clean_clone_metrics(
        role_counts={FunctionSemanticRole.TEST_CODE.value: 2},
        body_lines=18,
        stable_statements=5,
        same_directory_relation_count=1,
        cap_counts={
            "test_member_count": 2,
            "test_duplicate_pair_count": 1,
            "test_relation_pair_count": 1,
            "guardrail_relation_pair_count": 1,
        },
    )
    target = _assess(
        metrics,
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.primary_action is ActionKind.CONSOLIDATE_CLONE
    assert target.action_status is FindingActionStatus.RECOMMENDED_EDIT


def test_test_duplicate_pair_caps_mixed_cluster_to_review_candidate() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=8,
            structural_duplicate_pair_count=3,
            semantic_role_counts={
                FunctionSemanticRole.TEST_CODE.value: 2,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 6,
            },
            test_member_count=2,
            guardrail_relation_pair_count=8,
            test_duplicate_pair_count=1,
            test_relation_pair_count=1,
            max_body_line_count=3,
        ),
        POLICY,
    )
    capped = apply_semantic_cap(
        review_tier=ReviewTier.RECOMMENDED_EDIT,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
        cap=cap,
    )

    assert cap.cap == RecommendationCap.MAX_REVIEW_CANDIDATE
    assert capped.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_test_member_cap_does_not_promote_maintenance_note_to_review_candidate() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=8,
            structural_duplicate_pair_count=3,
            semantic_role_counts={
                FunctionSemanticRole.TEST_CODE.value: 1,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 7,
            },
            test_member_count=1,
            max_body_line_count=12,
        ),
        POLICY,
    )
    capped = apply_semantic_cap(
        review_tier=ReviewTier.MAINTENANCE_NOTE,
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        action_status=FindingActionStatus.RECORD_SHARED_CONCERN,
        cap=cap,
    )

    assert cap.cap == RecommendationCap.MAX_REVIEW_CANDIDATE
    assert capped.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert capped.action_status is FindingActionStatus.RECORD_SHARED_CONCERN
    assert capped.downgrade_reasons == ()


def test_test_duplicate_pair_with_low_value_action_stays_maintenance_note() -> None:
    metrics = _clean_clone_metrics(
        role_counts={
            FunctionSemanticRole.TEST_CODE.value: 2,
            FunctionSemanticRole.NORMAL_FUNCTION.value: 4,
        },
        body_lines=12,
        stable_statements=6,
        same_directory_relation_count=2,
        cap_counts={
            "test_member_count": 2,
            "test_duplicate_pair_count": 1,
            "test_relation_pair_count": 1,
            "guardrail_relation_pair_count": 4,
        },
    )
    metrics.update(
        {
            "member_count": 6,
            "structural_duplicate_pair_count": 2,
            "structural_relation_pair_count": 2,
        }
    )
    target = _assess(
        metrics,
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action is ActionKind.DO_NOT_REFACTOR


def test_repeated_protocol_duplicate_pairs_below_material_ratio_do_not_cap_mixed_cluster() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=8,
            structural_duplicate_pair_count=6,
            semantic_role_counts={
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 3,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 5,
            },
            protocol_member_count=3,
            guardrail_relation_pair_count=12,
            protocol_duplicate_pair_count=3,
            protocol_relation_pair_count=3,
        ),
        POLICY,
    )

    assert cap.cap == RecommendationCap.ALLOW_RECOMMENDED_EDIT


def test_repeated_protocol_duplicate_pairs_at_material_ratio_cap_mixed_cluster() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=8,
            structural_duplicate_pair_count=7,
            semantic_role_counts={
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 5,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 3,
            },
            protocol_member_count=5,
            guardrail_relation_pair_count=12,
            protocol_duplicate_pair_count=5,
            protocol_relation_pair_count=5,
        ),
        POLICY,
    )

    assert cap.cap == RecommendationCap.MAX_MAINTENANCE_NOTE


def test_example_singleton_duplicate_pair_caps_mixed_cluster_to_observation() -> None:
    cap = semantic_cap_for(
        FindingMetrics(
            member_count=5,
            structural_duplicate_pair_count=1,
            semantic_role_counts={
                FunctionSemanticRole.EXAMPLE_CODE.value: 1,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 4,
            },
            example_member_count=1,
            guardrail_relation_pair_count=10,
            example_duplicate_pair_count=1,
            example_relation_pair_count=1,
        ),
        POLICY,
    )
    capped = apply_semantic_cap(
        review_tier=ReviewTier.RECOMMENDED_EDIT,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
        cap=cap,
    )

    assert cap.cap == RecommendationCap.MAX_OBSERVATION
    assert capped.review_tier is ReviewTier.OBSERVATION
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_review_candidate_cap_downgrades_recommended_edit_status() -> None:
    capped = apply_semantic_cap(
        review_tier=ReviewTier.REVIEW_CANDIDATE,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.RECOMMENDED_EDIT,
        cap=SemanticCapAssessment(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            ("Semantic role cap: review boundary.",),
        ),
    )

    assert capped.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert capped.action_status is FindingActionStatus.CAUTIOUS_CANDIDATE
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert capped.downgrade_reasons == ("Semantic role cap: review boundary.",)


def test_single_protocol_member_does_not_poison_mixed_implementation_cluster() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.COMPARISON_PROTOCOL.value: 1,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 4,
            },
            body_lines=12,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={
                "member_count": 5,
                "protocol_member_count": 1,
                "guardrail_relation_pair_count": 1,
                "protocol_relation_pair_count": 0,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.primary_action == ActionKind.CONSOLIDATE_CLONE


def test_sync_async_mirror_is_review_capped_not_recommended() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={FunctionSemanticRole.SYNC_ASYNC_MIRROR.value: 2},
            body_lines=14,
            stable_statements=8,
            same_directory_relation_count=0,
            cap_counts={"api_surface_member_count": 2},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert target.action_status is FindingActionStatus.CAUTIOUS_CANDIDATE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_mixed_interface_member_does_not_poison_whole_target() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.TYPING_OVERLOAD.value: 1,
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB.value: 1,
            },
            body_lines=12,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={"interface_only_member_count": 1},
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.primary_action == ActionKind.CONSOLIDATE_CLONE
    assert target.action_status is FindingActionStatus.RECOMMENDED_EDIT


def test_declaration_only_cluster_is_observation_not_edit() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.DECLARATION_BOUNDARY.value: 2,
                FunctionSemanticRole.ABSTRACT_OR_INTERFACE_STUB.value: 2,
            },
            body_lines=0,
            stable_statements=0,
            same_directory_relation_count=1,
            cap_counts={
                "declaration_member_count": 2,
                "declaration_relation_pair_count": 1,
                "interface_only_member_count": 2,
                "interface_only_relation_pair_count": 1,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.OBSERVATION
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any("declaration" in reason for reason in target.downgrade_reasons)


def test_declaration_api_surface_caps_to_maintenance_note() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.DECLARATION_BOUNDARY.value: 2,
                FunctionSemanticRole.PUBLIC_API_MIRROR.value: 2,
            },
            body_lines=0,
            stable_statements=0,
            same_directory_relation_count=1,
            cap_counts={
                "declaration_member_count": 2,
                "declaration_relation_pair_count": 1,
                "api_surface_member_count": 2,
                "api_surface_relation_pair_count": 1,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert any("declaration/API" in reason for reason in target.downgrade_reasons)


def test_mixed_declaration_member_does_not_poison_implementation_clone() -> None:
    target = _assess(
        _clean_clone_metrics(
            role_counts={
                FunctionSemanticRole.DECLARATION_BOUNDARY.value: 1,
                FunctionSemanticRole.NORMAL_FUNCTION.value: 2,
            },
            body_lines=12,
            stable_statements=6,
            same_directory_relation_count=1,
            cap_counts={
                "member_count": 3,
                "declaration_member_count": 1,
                "declaration_relation_pair_count": 0,
                "interface_only_member_count": 1,
                "interface_only_relation_pair_count": 0,
            },
        ),
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
        evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
    )

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.primary_action == ActionKind.CONSOLIDATE_CLONE


def test_semantic_cap_reports_reason_when_only_action_changes() -> None:
    capped = apply_semantic_cap(
        review_tier=ReviewTier.OBSERVATION,
        primary_action=ActionKind.CONSOLIDATE_CLONE,
        action_status=FindingActionStatus.CAUTIOUS_CANDIDATE,
        cap=SemanticCapAssessment(
            RecommendationCap.MAX_OBSERVATION,
            ("Semantic role cap: fixture reason.",),
        ),
    )

    assert capped.review_tier is ReviewTier.OBSERVATION
    assert capped.primary_action == ActionKind.RECORD_SHARED_CONCERN
    assert capped.downgrade_reasons == ("Semantic role cap: fixture reason.",)


def test_token_duplicate_fixture_recommends_clone_consolidation(tmp_path: Path) -> None:
    source_path = "src/token_duplicates.py"
    source = (FIXTURE_ROOT / "token_duplicates.py").read_text(encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / source_path).write_text(source, encoding="utf-8")
    config = load_config(tmp_path)
    facts = _source_repository_facts(source_path)
    artifacts = build_signature_artifacts(
        config,
        facts,
        [],
    )

    targets = build_findings(artifacts.clusters, facts, POLICY)
    target = next(item for item in targets if item.primary_action == ActionKind.CONSOLIDATE_CLONE)

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.action_status is FindingActionStatus.RECOMMENDED_EDIT
    assert _assessment(target).action_recommendation.action_kind == ActionKind.CONSOLIDATE_CLONE


def test_exact_pair_inside_broad_cluster_is_promoted(tmp_path: Path) -> None:
    source_path = "src/promoted_pair_duplicates.py"
    source = (FIXTURE_ROOT / "promoted_pair_duplicates.py").read_text(encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / source_path).write_text(source, encoding="utf-8")
    config = load_config(tmp_path)
    facts = _source_repository_facts(source_path)
    artifacts = build_signature_artifacts(
        config,
        facts,
        [],
    )

    targets = build_findings(artifacts.clusters, facts, POLICY)
    promoted = [
        item
        for item in targets
        if item.title == "Duplicate helper pair ci_single_line / output_single_line"
    ]

    assert len(promoted) == 1
    assert promoted[0].review_tier is ReviewTier.RECOMMENDED_EDIT
    assert promoted[0].primary_action == ActionKind.CONSOLIDATE_CLONE
    assert "Inspect these duplicates" in promoted[0].suggested_refactor_direction
    assert len(promoted[0].structural_relation_pairs) == 1


SENTINEL_REPRS = """
class NotSetA:
    def __repr__(self) -> str:
        return "<notset>"


class NotSetB:
    def __repr__(self) -> str:
        return "<notset>"
"""


def test_tiny_special_method_clones_count_every_member_and_stay_notes(tmp_path: Path) -> None:
    source_path = "src/sentinels.py"
    (tmp_path / "src").mkdir()
    (tmp_path / source_path).write_text(SENTINEL_REPRS, encoding="utf-8")
    facts = _source_repository_facts(source_path)
    artifacts = build_signature_artifacts(load_config(tmp_path), facts, [])

    (target,) = build_findings(artifacts.clusters, facts, POLICY)

    special = FunctionSemanticRole.PYTHON_SPECIAL_METHOD.value
    assert target.metrics.semantic_role_counts[special] == target.metrics.member_count
    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE


def test_targets_over_same_name_members_of_one_file_keep_distinct_ids() -> None:
    target = _assess(
        {"member_count": 2, "structural_duplicate_pair_count": 1, "body_hash_match_count": 1},
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
    )

    def at(*lines: int) -> Finding:
        return replace(
            target,
            locations=tuple(
                FindingLocation("src/lexers.py", line, line + 1, "signature", "shape", "score")
                for line in lines
            ),
        )

    first, second, same = _with_unique_identities([at(10, 20), at(30, 40), at(10, 20)])

    assert first.target_id != second.target_id
    assert first.target_id == same.target_id
    assert with_target_identity(at(10, 20)).target_id == with_target_identity(at(30, 40)).target_id

    def in_classes(*containers: str) -> Finding:
        return replace(
            target,
            locations=tuple(
                FindingLocation("src/lexers.py", 1, 2, "signature", "shape", "score", "", name)
                for name in containers
            ),
        )

    assert (
        with_target_identity(in_classes("A", "B")).target_id
        != with_target_identity(in_classes("C", "D")).target_id
    )


def test_equivalent_location_targets_are_deduped_before_ranking() -> None:
    weaker = with_target_identity(
        _assess(
            {
                "member_count": 2,
                "structural_relation_pair_count": 1,
                "same_role_relation_count": 1,
                "lead_confidence_score": 0.95,
                "lead_refactorability_score": 0.2,
                "lead_risk_score": 0.1,
            },
            actions=(_action(ActionKind.RECORD_SHARED_CONCERN, confidence=0.95),),
        )
    )
    stronger = with_target_identity(
        _assess(
            {
                "member_count": 2,
                "structural_duplicate_pair_count": 1,
                "structural_relation_pair_count": 1,
                "body_hash_match_count": 1,
                "lead_tree_similarity": 1.0,
                "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
                "same_role_relation_count": 1,
                "lead_confidence_score": 0.95,
                "lead_refactorability_score": 0.8,
                "lead_abstraction_cost_score": 0.22,
                "lead_risk_score": 0.0,
                "__line_span": 120,
            },
            actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.8),),
            evidence_kinds=(EvidenceKind.STRUCTURAL_DUPLICATE,),
        )
    )

    deduped = _dedupe_equivalent_findings([weaker, stronger])

    assert weaker.target_id == stronger.target_id  # verdicts are not identity
    assert deduped == [stronger]


@pytest.mark.parametrize(
    ("fixture", "language", "symbol"),
    [
        ("intra_function_duplicate.py", "Python", "completed_result"),
        ("intra_function_duplicate.ts", "TypeScript", "completedResult"),
    ],
)
def test_intra_function_duplicate_block_recommends_local_helper(
    fixture: str,
    language: str,
    symbol: str,
) -> None:
    config = load_config(FIXTURE_ROOT)
    facts = _source_repository_facts(fixture, language=language)
    artifacts = build_signature_artifacts(config, facts, [])

    targets = build_findings(artifacts.clusters, facts, POLICY, signatures=artifacts.records)
    target = next(item for item in targets if item.title == f"Repeated local block in {symbol}")

    assert target.review_tier is ReviewTier.RECOMMENDED_EDIT
    assert target.action_status is FindingActionStatus.RECOMMENDED_EDIT
    assert target.primary_action == ActionKind.EXTRACT_SMALL_HELPER
    assert EvidenceKind.INTRA_FUNCTION_DUPLICATE in target.evidence_kinds


def test_structural_duplicate_pairs_contribute_to_relation_metrics() -> None:
    pair = _relation_pair_fixture(
        same_role=True,
        same_directory=True,
        scores=(EXPECTED_RELATEDNESS, EXPECTED_REFACTORABILITY, EXPECTED_CONFIDENCE),
    )

    metrics = _structural_metrics([pair], [], [])

    assert metrics["same_role_relation_count"] == 1
    assert metrics["same_directory_relation_count"] == 1
    assert metrics["lead_relatedness_score"] == EXPECTED_RELATEDNESS
    assert metrics["lead_refactorability_score"] == EXPECTED_REFACTORABILITY
    assert metrics["lead_confidence_score"] == EXPECTED_CONFIDENCE
    assert metrics["relation_kind_counts"] == {RelationKind.BODY_IDENTICAL.value: 1}
    assert metrics["guardrail_relation_pair_count"] == 1


def test_structural_metric_kind_counts_include_duplicate_and_variant_pairs() -> None:
    duplicate = _relation_pair_fixture(relation_kind=RelationKind.BODY_IDENTICAL)
    variant = _relation_pair_fixture(relation_kind=RelationKind.COMMON_WRAPPER_DIFFERENT_CORE)

    metrics = _structural_metrics([duplicate], [variant], [])

    assert metrics["relation_kind_counts"] == {
        RelationKind.BODY_IDENTICAL.value: 1,
        RelationKind.COMMON_WRAPPER_DIFFERENT_CORE.value: 1,
    }
    assert metrics["guardrail_relation_pair_count"] == EXPECTED_ALL_PAIR_COUNT


def test_structural_metrics_count_a_pair_listed_twice_once() -> None:
    pair = _relation_pair_fixture()

    metrics = _structural_metrics([pair], [pair], [])

    assert metrics["guardrail_relation_pair_count"] == 1
    assert metrics["body_hash_match_count"] == 1


def test_structural_metrics_profile_comes_from_one_lead_pair() -> None:
    lead_scores, lead_shape = (0.8, 0.5, 0.95), (12, 12, 2)
    weaker_scores, weaker_shape = (0.9, 0.9, 0.6), (20, 20, 6)
    lead = _relation_pair_fixture(scores=lead_scores, shape=lead_shape)
    weaker = _relation_pair_fixture(left_symbol="other", scores=weaker_scores, shape=weaker_shape)

    metrics = _structural_metrics([], [weaker, lead], [])

    # Every profile metric comes from the highest-confidence pair, not per-axis maxima.
    assert metrics["lead_confidence_score"] == lead_scores[2]
    assert metrics["lead_refactorability_score"] == lead_scores[1]
    assert metrics["lead_stable_statement_count"] == lead_shape[2]
    # Extent guards stay cluster-wide on purpose.
    assert metrics["max_body_line_count"] == weaker_shape[0]


def test_structural_metrics_count_test_duplicate_pair_guardrails() -> None:
    pair = _relation_pair_fixture(roles=(FunctionSemanticRole.TEST_CODE.value,))

    metrics = _structural_metrics([pair], [], [])

    assert metrics["test_duplicate_pair_count"] == 1
    assert metrics["test_relation_pair_count"] == 1


def test_structural_metrics_count_declaration_pair_guardrails() -> None:
    pair = _relation_pair_fixture(roles=(FunctionSemanticRole.DECLARATION_BOUNDARY.value,))

    metrics = _structural_metrics([pair], [], [])

    assert metrics["declaration_duplicate_pair_count"] == 1
    assert metrics["declaration_relation_pair_count"] == 1


def test_tiny_protocol_exact_pair_is_not_promoted_as_standalone_target() -> None:
    pair = _relation_pair_fixture(
        roles=(FunctionSemanticRole.COMPARISON_PROTOCOL.value,),
        shape=(2, 2, 1),
    )

    assert promotable_components([pair]) == []


def test_one_sided_tiny_protocol_exact_pair_is_not_promoted() -> None:
    pair = _relation_pair_fixture(
        roles=((FunctionSemanticRole.COMPARISON_PROTOCOL.value,), ()),
        shape=(12, 2, 6),
    )

    assert promotable_components([pair]) == []


def test_non_guarded_exact_pair_with_substantial_stable_body_is_promoted() -> None:
    pair = _relation_pair_fixture(shape=(12, 12, 6))

    assert promotable_components([pair]) == [[pair]]


def _near_miss(pair: RelationPair, confidence: float) -> RelationPair:
    near = cast(Any, pair)
    near.flags = SimpleNamespace(body_hash_match=False)
    near.clone_type = CloneClass.TYPE_3_NEAR_MISS
    near.scores.confidence = confidence
    return pair


@pytest.mark.parametrize(("confidence", "promoted"), [(0.8, True), (0.6, False)])
def test_near_miss_clone_pairs_are_promoted_when_the_relation_is_strong(
    confidence: float,
    promoted: bool,
) -> None:
    pair = _near_miss(_relation_pair_fixture(shape=(12, 12, 6)), confidence)

    assert promotable_components([pair]) == ([[pair]] if promoted else [])


def test_clone_pairs_sharing_members_form_one_component() -> None:
    # The fixture puts left members in src/a.py and right members in src/b.py,
    # so "b" is the same function in both of the first two pairs.
    a_b = _relation_pair_fixture(left_symbol="a", right_symbol="b", shape=(12, 12, 6))
    c_b = _relation_pair_fixture(left_symbol="c", right_symbol="b", shape=(12, 12, 6))
    d_e = _relation_pair_fixture(left_symbol="d", right_symbol="e", shape=(12, 12, 6))

    components = promotable_components([d_e, c_b, a_b])

    assert sorted(len(component) for component in components) == [1, 2]


def test_exact_pairs_covering_whole_cluster_are_not_promoted_as_duplicate_targets() -> None:
    left_middle = _relation_pair_fixture(
        left_symbol="left",
        right_symbol="middle",
        shape=(12, 12, 6),
    )
    middle_right = _relation_pair_fixture(
        left_symbol="middle",
        right_symbol="right",
        shape=(12, 12, 6),
    )

    assert (
        should_promote(
            cast(Cluster, SimpleNamespace(member_count=3)),
            [[left_middle, middle_right]],
            [left_middle, middle_right],
        )
        is False
    )


def test_disjoint_components_covering_the_cluster_are_promoted() -> None:
    first = _relation_pair_fixture(left_symbol="a", right_symbol="b", shape=(12, 12, 6))
    second = _relation_pair_fixture(left_symbol="c", right_symbol="d", shape=(12, 12, 6))

    assert should_promote(
        cast(Cluster, SimpleNamespace(member_count=4)),
        [[first], [second]],
        [first, second],
    )


def test_sparse_exact_pairs_in_broad_cluster_are_promoted_for_narrow_review() -> None:
    pair = _relation_pair_fixture(shape=(12, 12, 6))

    assert (
        should_promote(
            cast(Cluster, SimpleNamespace(member_count=6)),
            [[pair]],
            [pair],
        )
        is True
    )


def test_pair_level_sync_async_mirror_uses_normalized_symbols() -> None:
    left = SimpleNamespace(
        symbol="_memoized_method__execute",
        normalized_symbol="execute",
        file="lib/pkg/engine.py",
    )
    right = SimpleNamespace(
        symbol="execute",
        normalized_symbol="execute",
        file="lib/pkg/asyncio/engine.py",
    )

    assert _sync_async_member_pair(left, right) is True


def test_mixed_high_risk_clone_uses_safety_stop() -> None:
    target = _assess(
        {
            "member_count": 3,
            "structural_relation_pair_count": 2,
            "body_hash_match_count": 1,
            "lead_tree_similarity": 1.0,
            "relation_kind_counts": {RelationKind.BODY_PARAMETERIZED: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.97,
            "lead_refactorability_score": 0.89,
            "lead_abstraction_cost_score": 0.44,
            "lead_risk_score": 0.51,
        },
        actions=(_action(ActionKind.CONSOLIDATE_CLONE, confidence=0.97),),
    )

    assert target.review_tier is ReviewTier.OBSERVATION
    assert target.action_status is FindingActionStatus.DO_NOT_REFACTOR
    assert target.primary_action == ActionKind.DO_NOT_REFACTOR


def test_introduce_abstraction_without_hole_evidence_records_shared_concern() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_relation_pair_count": 1,
            "relation_kind_counts": {RelationKind.COMMON_WRAPPER_DIFFERENT_CORE: 1},
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.7321,
            "lead_relatedness_score": 0.7958,
            "lead_refactorability_score": 0.72,
            "lead_abstraction_cost_score": 0.22,
            "lead_risk_score": 0.16,
            "lead_stable_statement_count": 2,
            "lead_hole_count": 0,
            "lead_hole_size": 0,
        },
        actions=(_action(ActionKind.INTRODUCE_ABSTRACTION, confidence=0.72),),
        abstraction_kind=AbstractionKind.EXTRACT_HELPER,
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.action_status is FindingActionStatus.RECORD_SHARED_CONCERN
    assert target.primary_action == ActionKind.RECORD_SHARED_CONCERN


def test_high_detection_low_value_note_action_is_not_review_candidate() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_relation_pair_count": 1,
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.2,
            "lead_risk_score": 0.1,
        },
        actions=(_action(ActionKind.RECORD_SHARED_CONCERN, confidence=0.95),),
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.review_score == 0.0
    assert target.visibility is FindingReviewVisibility.GROUPED


def test_high_value_design_concern_can_be_review_candidate() -> None:
    target = _assess(
        {
            "member_count": 8,
            "structural_duplicate_pair_count": 1,
            "structural_relation_pair_count": 3,
            "same_role_relation_count": 3,
            "lead_confidence_score": 0.95,
            "lead_refactorability_score": 0.3,
            "lead_risk_score": 0.72,
            "__line_span": 200,
        },
        actions=(_action(ActionKind.RECORD_SHARED_CONCERN, confidence=0.95),),
    )

    assert target.review_tier is ReviewTier.REVIEW_CANDIDATE
    assert target.review_score > 0.0
    assert target.visibility is FindingReviewVisibility.LISTED


def test_observation_tier_forces_sidecar_visibility() -> None:
    target = _assess(
        {
            "member_count": 2,
            "structural_relation_pair_count": 1,
            "same_role_relation_count": 1,
            "lead_confidence_score": 0.1,
            "lead_refactorability_score": 0.1,
        },
        actions=(_action(ActionKind.RECORD_SHARED_CONCERN, confidence=0.8),),
    )

    assert target.review_tier is ReviewTier.OBSERVATION
    assert target.visibility is FindingReviewVisibility.SIDECAR_ONLY


def test_policy_constant_duplicate_fit_can_still_be_maintenance_note() -> None:
    target = _assess(
        {
            "member_count": 2,
            "policy_constant_duplicate_count": 1,
            "structural_relation_pair_count": 1,
            "same_role_relation_count": 1,
            "lead_relatedness_score": 1.0,
            "lead_refactorability_score": 0.92,
            "lead_confidence_score": 0.98,
            "lead_risk_score": 0.04,
        },
        actions=(_action(ActionKind.INTRODUCE_ABSTRACTION, confidence=0.96),),
        evidence_kinds=(EvidenceKind.POLICY_CONSTANT_DUPLICATE,),
        abstraction_kind=AbstractionKind.MOVE_MODULE,
    )

    assert target.review_tier is ReviewTier.MAINTENANCE_NOTE
    assert target.primary_action == ActionKind.INTRODUCE_ABSTRACTION
    assessment = _assessment(target)
    assert assessment.abstraction_fit.band is AssessmentBand.HIGH
    assert "policy_constant_duplicate" in assessment.abstraction_fit.reasons
    assert assessment.maintenance_payoff.band is AssessmentBand.LOW


def test_callable_factory_remains_low_tier_context() -> None:
    target = _assess(
        {"member_count": 2},
        evidence_kinds=(EvidenceKind.CALLABLE_FACTORY, EvidenceKind.CALLSITE_IMMEDIATE),
        abstraction_kind=AbstractionKind.COMPILER_FACTORY,
    )

    assert target.review_tier in {ReviewTier.MAINTENANCE_NOTE, ReviewTier.OBSERVATION}
    assert target.abstraction_kind == AbstractionKind.COMPILER_FACTORY
    assert "call_fingerprint_overlap" in target.evidence_classes


def _assess(
    metrics: dict[str, object],
    *,
    actions: tuple[RefactorAction, ...] = (),
    evidence_kinds: tuple[str, ...] = (),
    has_signature_overlap: bool = False,
    abstraction_kind: str = AbstractionKind.TRACK_ONLY,
) -> Finding:
    return assess_target(
        _draft(
            metrics,
            actions=actions,
            evidence_kinds=evidence_kinds,
            has_signature_overlap=has_signature_overlap,
            abstraction_kind=abstraction_kind,
        ),
        roles_by_path={"src/a.py": "source", "src/b.py": "source"},
        policy=POLICY,
    )


def _clean_clone_metrics(
    *,
    role_counts: dict[str, int],
    body_lines: int | tuple[int, int],
    stable_statements: int | tuple[int, int],
    same_directory_relation_count: int,
    cap_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    max_body_line_count, min_body_line_count = _max_min(body_lines)
    lead_stable_statement_count, min_stable_statement_count = _max_min(stable_statements)
    return {
        "member_count": 2,
        "structural_duplicate_pair_count": 1,
        "structural_relation_pair_count": 1,
        "body_hash_match_count": 1,
        "lead_tree_similarity": 1.0,
        "relation_kind_counts": {RelationKind.BODY_IDENTICAL: 1},
        "same_role_relation_count": 1,
        "lead_confidence_score": 0.95,
        "lead_refactorability_score": 0.8,
        "lead_abstraction_cost_score": 0.22,
        "lead_risk_score": 0.0,
        "max_body_line_count": max_body_line_count,
        "min_body_line_count": min_body_line_count,
        "lead_stable_statement_count": lead_stable_statement_count,
        "min_stable_statement_count": min_stable_statement_count,
        "same_directory_relation_count": same_directory_relation_count,
        "semantic_role_counts": role_counts,
        **(cap_counts or {}),
        "__line_span": 120,
    }


def _max_min(value: int | tuple[int, int]) -> tuple[int, int]:
    return value if isinstance(value, tuple) else (value, value)


def _assessment(target: Finding) -> AssessmentBreakdown:
    return cast(AssessmentBreakdown, target.assessment)


def _draft(
    metrics: dict[str, object],
    *,
    actions: tuple[RefactorAction, ...],
    evidence_kinds: tuple[str, ...],
    has_signature_overlap: bool,
    abstraction_kind: str,
) -> FindingDraft:
    values = dict(metrics)
    line_span_value = values.pop("__line_span", 6)
    line_span = line_span_value if isinstance(line_span_value, int) else 6
    return FindingDraft(
        target_type=FindingTargetType.SIGNATURE_SHAPE,
        title="fixture target",
        severity="medium",
        confidence=0.8,
        files=["src/a.py", "src/b.py"],
        locations=[
            FindingLocation("src/a.py", 1, 3, "fixture", "function", "left"),
            FindingLocation("src/b.py", 5, 7, "fixture", "function", "right"),
        ],
        metrics=_target_metrics(values),
        evidence=[EvidenceItem("fixture", "fixture")],
        reasons=["fixture"],
        risk="low",
        overlaps={},
        direction="fixture",
        member_count=_member_count(values),
        has_signature_overlap=has_signature_overlap,
        line_span=line_span,
        abstraction_kind=abstraction_kind,
        evidence_kinds=list(evidence_kinds),
        refactor_action_candidates=list(actions),
    )


def _action(
    kind: ActionKind,
    *,
    confidence: float,
    preconditions: tuple[str, ...] = (),
) -> RefactorAction:
    return RefactorAction(
        kind=kind,
        status=ActionStatus.RECOMMENDED,
        confidence=confidence,
        applies_to=(_member("left", "src/a.py"), _member("right", "src/b.py")),
        preconditions=preconditions,
    )


def _member(symbol: str, file: str) -> MemberRef:
    return MemberRef(
        signature_id=f"sig_{symbol}",
        function_id=f"fn_{symbol}",
        file=file,
        symbol=symbol,
        start_line=1,
        end_line=3,
    )


def _relation_pair_fixture(  # noqa: PLR0913
    *,
    roles: tuple[str, ...] | tuple[tuple[str, ...], tuple[str, ...]] = (),
    left_symbol: str = "left",
    right_symbol: str = "right",
    same_role: bool = True,
    same_directory: bool = True,
    scores: tuple[float, float, float] = (0.8, 0.8, 0.95),
    shape: tuple[int, int, int] = (12, 12, 6),
    relation_kind: RelationKind = RelationKind.BODY_IDENTICAL,
) -> RelationPair:
    relatedness, refactorability, confidence = scores
    max_body_line_count, min_body_line_count, stable_statement_count = shape
    left_roles, right_roles = _pair_roles(roles)
    left_file = "src/a.py"
    right_file = "src/b.py" if same_directory else "other/b.py"
    return cast(
        RelationPair,
        SimpleNamespace(
            left=_member_with_roles(left_symbol, left_file, left_roles),
            right=_member_with_roles(right_symbol, right_file, right_roles),
            same_role=same_role,
            relation_kind=relation_kind,
            flags=SimpleNamespace(body_hash_match=True),
            scores=SimpleNamespace(
                name=0.8,
                relatedness=relatedness,
                refactorability=refactorability,
                abstraction_cost=0.1,
                risk=0.0,
                confidence=confidence,
            ),
            tree=SimpleNamespace(tree_similarity=1.0, tree_node_count=12),
            anti_unification=SimpleNamespace(
                stable_statement_count=stable_statement_count,
                hole_count=0,
                max_hole_size=0,
            ),
            max_body_line_count=max_body_line_count,
            min_body_line_count=min_body_line_count,
            delta_kinds=(),
            clone_type=CloneClass.TYPE_2_PARAMETERIZED,
        ),
    )


def _member_with_roles(symbol: str, file: str, roles: tuple[str, ...]) -> MemberRef:
    return MemberRef(
        signature_id=f"sig_{symbol}",
        function_id=f"fn_{symbol}",
        file=file,
        symbol=symbol,
        start_line=1,
        end_line=3,
        semantic_roles=roles,
    )


def _pair_roles(
    roles: tuple[str, ...] | tuple[tuple[str, ...], tuple[str, ...]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if len(roles) == EXPECTED_MEMBER_PATH_COUNT and all(isinstance(item, tuple) for item in roles):
        return cast(tuple[tuple[str, ...], tuple[str, ...]], roles)
    shared = cast(tuple[str, ...], roles)
    return shared, shared


def _source_file_record(path: str, *, language: str = "Python") -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        size_bytes=0,
        line_count=0,
        content_hash="",
        role="source",
        is_generated=False,
        is_vendor=False,
        is_test=False,
        is_build_output=False,
    )


def _source_repository_facts(path: str, *, language: str = "Python") -> RepositoryFacts:
    return build_repository_facts(
        RepositoryScan(
            records=[_source_file_record(path, language=language)],
            selected_paths=[path],
        )
    )


def _member_count(metrics: dict[str, object]) -> int:
    value = _target_metrics(metrics).member_count
    return value if isinstance(value, int) else EXPECTED_MEMBER_PATH_COUNT


def _target_metrics(values: dict[str, object]) -> FindingMetrics:
    return FindingMetrics(**cast(Any, values))
