from __future__ import annotations

from dataclasses import dataclass

from codeseam.analysis.assessment.definitions import FindingActionStatus, ReviewTier
from codeseam.analysis.assessment.policy import (
    AssessmentPolicy,
    RecommendationCap,
    RecommendationCapLabel,
)
from codeseam.analysis.assessment.relation_evidence import (
    has_editable_parameterized_skeleton_relation,
    has_relation_kind,
)
from codeseam.analysis.findings import FindingMetrics, RoleEvidenceCounts
from codeseam.analysis.relations.models import ActionKind, RelationKind
from codeseam.analysis.semantic_roles import (
    DECLARATION_SURFACE_ROLES,
    INTERFACE_ONLY_ROLES,
    FunctionSemanticRole,
    role_set,
)

NON_EDIT_ACTIONS = frozenset(
    {
        ActionKind.OBSERVE,
        ActionKind.RECORD_SHARED_CONCERN,
        ActionKind.INSPECT_SHARED_LIFECYCLE,
        ActionKind.DO_NOT_REFACTOR,
    }
)
EDIT_STATUSES = frozenset({FindingActionStatus.RECOMMENDED_EDIT})
PREDICATE_PARAMETERIZED_RELATION_KINDS = frozenset({RelationKind.BODY_PARAMETERIZED})
TEST_HELPER_PAIR_MEMBER_COUNT = 2
CAP_ORDER: dict[ReviewTier, int] = {
    ReviewTier.RECOMMENDED_EDIT: 0,
    ReviewTier.REVIEW_CANDIDATE: 1,
    ReviewTier.TRACKING_SIGNAL: 2,
    ReviewTier.OBSERVATION: 3,
}


@dataclass(frozen=True, slots=True)
class SemanticCapAssessment:
    """Post-score actionability cap derived from semantic role priors."""

    cap: RecommendationCapLabel
    reasons: tuple[str, ...] = ()
    primary_action: ActionKind | None = None
    review_floor: ReviewTier | None = None


@dataclass(frozen=True, slots=True)
class CappedSurface:
    review_tier: ReviewTier
    primary_action: ActionKind
    action_status: FindingActionStatus
    downgrade_reasons: tuple[str, ...]


def semantic_cap_for(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> SemanticCapAssessment:
    """Return the strongest semantic cap for a target.

    Semantic caps are deliberately downstream of detection. A protocol method
    clone can still be real and useful to track, but its role makes direct edit
    recommendations risky unless the target has substantial implementation
    evidence beyond the protocol surface.
    """

    roles = role_set(metrics.semantic_role_counts)
    dominant_ratio = policy.semantic_caps.dominant_member_ratio
    for cap in (
        _declaration_or_interface_cap(metrics, dominant_ratio),
        _promoted_pair_parent_cap(metrics, policy),
        _path_context_cap(metrics, policy, dominant_ratio),
        _predicate_boundary_cap(metrics, dominant_ratio),
        _relation_surface_cap(metrics, policy, roles, dominant_ratio),
        _constructor_surface_cap(metrics, policy, dominant_ratio),
        _special_method_cap(metrics, policy, dominant_ratio),
    ):
        if cap is not None:
            return cap
    return SemanticCapAssessment(RecommendationCap.ALLOW_RECOMMENDED_EDIT)


def _declaration_or_interface_cap(
    metrics: FindingMetrics,
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    guardrails = metrics.semantic_guardrails
    if _declaration_dominates(metrics, dominant_ratio):
        if _api_surface_dominates(metrics, dominant_ratio):
            return SemanticCapAssessment(
                RecommendationCap.MAX_TRACKING_SIGNAL,
                ("Semantic role cap: declaration/API surface recurrence is tracked, not edited.",),
            )
        return SemanticCapAssessment(
            RecommendationCap.MAX_OBSERVATION,
            (
                "Semantic role cap: declaration-only API shape recurrence is an "
                "observation, not implementation reuse.",
            ),
        )
    if _dominant_members_or_relation_evidence(
        _with_member_fallback(
            guardrails.interface_only,
            _max_role_count(metrics, INTERFACE_ONLY_ROLES),
        ),
        metrics=metrics,
        threshold=dominant_ratio,
    ):
        return _cap(
            RecommendationCap.DO_NOT_REFACTOR,
            "Semantic role cap: interface-only declarations are not refactor targets.",
        )
    return None


def _path_context_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    guardrails = metrics.semantic_guardrails
    if _has_dominant_semantic_duplicate_pair(
        guardrails.example.duplicate_pairs,
        metrics.structural_duplicate_pair_count,
        policy,
    ) or _dominant_members_or_relation_evidence(
        guardrails.example,
        metrics=metrics,
        threshold=dominant_ratio,
    ):
        return _cap(
            RecommendationCap.MAX_OBSERVATION,
            "Semantic role cap: example code is usually pedagogical surface area.",
        )
    if (
        guardrails.test.members > 0
        or guardrails.test.duplicate_pairs > 0
        or _dominant_members_or_relation_evidence(
            guardrails.test,
            metrics=metrics,
            threshold=dominant_ratio,
        )
    ):
        if _clean_test_helper_edit_candidate(metrics, policy):
            return None
        return _test_cap()
    return None


def _promoted_pair_parent_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> SemanticCapAssessment | None:
    """Cap broad parents when exact-pair evidence was split out.

    Exact pair promotion means the draft builder found a narrower edit target
    inside a broader signature family. The parent still carries useful
    detection context, but it should not also become a whole-cluster edit when
    the promoted pair members do not cover most of the parent members.
    """

    if (
        metrics.promoted_exact_pair_count > 0
        and metrics.member_count > 0
        and not _all_or_most(
            metrics.promoted_exact_pair_member_count,
            metrics.member_count,
            policy.semantic_caps.dominant_member_ratio,
        )
    ):
        return _cap(
            RecommendationCap.MAX_TRACKING_SIGNAL,
            (
                "Exact pair evidence was promoted into narrower targets; the broad "
                "parent cluster is tracked instead of edited."
            ),
        )
    return None


def _predicate_boundary_cap(
    metrics: FindingMetrics,
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    """Cap parameterized predicate families without hiding exact clones.

    Tiny boolean predicates often share a control skeleton while answering
    different questions. That is useful recurrence evidence, but a
    parameterized predicate relation is not by itself a safe edit. Exact
    body-identical predicate clones still flow through the ordinary clone path.
    """

    if not _all_or_most(
        _role_count(metrics, FunctionSemanticRole.PREDICATE_BOUNDARY),
        metrics.member_count,
        dominant_ratio,
    ):
        return None
    if not has_relation_kind(metrics, PREDICATE_PARAMETERIZED_RELATION_KINDS):
        return None
    return _cap(
        RecommendationCap.MAX_TRACKING_SIGNAL,
        "Semantic role cap: predicate boundary variants are tracked instead of edited.",
    )


def _relation_surface_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    roles: frozenset[str],
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    guardrails = metrics.semantic_guardrails
    if _has_dominant_semantic_duplicate_pair(
        guardrails.protocol.duplicate_pairs,
        metrics.structural_duplicate_pair_count,
        policy,
    ):
        return _protocol_cap(metrics, policy)
    if _has_dominant_semantic_duplicate_pair(
        guardrails.api_surface.duplicate_pairs,
        metrics.structural_duplicate_pair_count,
        policy,
    ):
        return _api_surface_cap(metrics, policy, roles)
    if _dominant_members_or_relation_evidence(
        guardrails.protocol,
        metrics=metrics,
        threshold=dominant_ratio,
    ):
        return _protocol_cap(metrics, policy)
    if _api_surface_dominates(metrics, dominant_ratio):
        return _api_surface_cap(metrics, policy, roles)
    return None


def _constructor_surface_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    guardrails = metrics.semantic_guardrails
    if _dominant_members_or_relation_evidence(
        _with_member_fallback(
            guardrails.constructor,
            _role_count(metrics, FunctionSemanticRole.CONSTRUCTOR),
        ),
        metrics=metrics,
        threshold=dominant_ratio,
    ):
        return _constructor_cap(metrics, policy)
    return None


def _special_method_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    dominant_ratio: float,
) -> SemanticCapAssessment | None:
    if (
        _role_count(metrics, FunctionSemanticRole.PYTHON_SPECIAL_METHOD) >= metrics.member_count
        and metrics.max_body_line_count <= policy.semantic_caps.tiny_body_line_count
    ):
        return _cap(
            RecommendationCap.MAX_TRACKING_SIGNAL,
            "Semantic role cap: tiny protocol methods are often required duplicates.",
        )
    if _all_or_most(
        _role_count(metrics, FunctionSemanticRole.PYTHON_SPECIAL_METHOD),
        metrics.member_count,
        dominant_ratio,
    ):
        return _cap(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            "Semantic role cap: special methods need human boundary review before editing.",
        )
    if _all_or_most(
        _role_count(metrics, FunctionSemanticRole.CUSTOM_DUNDER_OR_FRAMEWORK_HOOK),
        metrics.member_count,
        dominant_ratio,
    ):
        return _cap(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            "Semantic role cap: custom dunder hooks often belong to framework contracts.",
        )
    return None


def apply_semantic_cap(
    *,
    review_tier: ReviewTier,
    primary_action: ActionKind,
    action_status: FindingActionStatus,
    cap: SemanticCapAssessment,
) -> CappedSurface:
    capped_tier = _capped_review_tier(review_tier, cap.cap)
    capped_tier = _floored_review_tier(capped_tier, cap.review_floor)
    if cap.cap == RecommendationCap.ALLOW_RECOMMENDED_EDIT:
        capped_action = primary_action
        capped_status = action_status
    elif cap.cap == RecommendationCap.MAX_REVIEW_CANDIDATE:
        action_capped = capped_tier != review_tier or action_status in EDIT_STATUSES
        capped_action = cap.primary_action or (
            ActionKind.RECORD_SHARED_CONCERN
            if primary_action not in NON_EDIT_ACTIONS
            else primary_action
        )
        capped_status = FindingActionStatus.CAUTIOUS_CANDIDATE if action_capped else action_status
    elif cap.cap in {
        RecommendationCap.MAX_TRACKING_SIGNAL,
        RecommendationCap.MAX_OBSERVATION,
    }:
        action_capped = capped_tier != review_tier or primary_action not in NON_EDIT_ACTIONS
        capped_action = ActionKind.RECORD_SHARED_CONCERN if action_capped else primary_action
        capped_status = (
            FindingActionStatus.RECORD_SHARED_CONCERN if action_capped else action_status
        )
    elif cap.cap == RecommendationCap.DO_NOT_REFACTOR:
        capped_action = ActionKind.DO_NOT_REFACTOR
        capped_status = FindingActionStatus.DO_NOT_REFACTOR
    else:
        capped_action = primary_action
        capped_status = action_status
    changed = (
        capped_tier != review_tier
        or capped_action != primary_action
        or capped_status != action_status
    )
    return CappedSurface(
        review_tier=capped_tier,
        primary_action=capped_action,
        action_status=capped_status,
        downgrade_reasons=cap.reasons if changed else (),
    )


def _protocol_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> SemanticCapAssessment:
    if _substantial_shared_logic(metrics, policy):
        return SemanticCapAssessment(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            (
                "Semantic role cap: protocol method has substantial shared body evidence, "
                "but still needs review before editing.",
            ),
        )
    return SemanticCapAssessment(
        RecommendationCap.MAX_TRACKING_SIGNAL,
        ("Semantic role cap: protocol/API methods are tracked instead of edited.",),
    )


def _api_surface_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
    roles: frozenset[str],
) -> SemanticCapAssessment:
    if FunctionSemanticRole.GENERATED_OR_CYTHON_BOUNDARY in roles:
        return SemanticCapAssessment(
            RecommendationCap.MAX_TRACKING_SIGNAL,
            ("Semantic role cap: generated/Cython boundary recurrence is tracked, not edited.",),
        )
    if FunctionSemanticRole.SYNC_ASYNC_MIRROR in roles:
        return SemanticCapAssessment(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            ("Semantic role cap: sync/async mirrors need review before editing.",),
        )
    if _substantial_shared_logic(metrics, policy):
        return SemanticCapAssessment(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            (
                "Semantic role cap: API boundary has substantial shared body evidence, "
                "but still needs review before editing.",
            ),
        )
    return SemanticCapAssessment(
        RecommendationCap.MAX_TRACKING_SIGNAL,
        ("Semantic role cap: adapter/API boundary recurrence is tracked, not edited.",),
    )


def _constructor_cap(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> SemanticCapAssessment:
    if _substantial_shared_logic(metrics, policy):
        return SemanticCapAssessment(
            RecommendationCap.MAX_REVIEW_CANDIDATE,
            (
                "Semantic role cap: constructors should share setup helpers rather than be "
                "consolidated directly.",
            ),
            primary_action=ActionKind.EXTRACT_SMALL_HELPER,
        )
    return SemanticCapAssessment(
        RecommendationCap.MAX_TRACKING_SIGNAL,
        ("Semantic role cap: small constructor duplication is usually object setup surface.",),
    )


def _cap(cap: RecommendationCapLabel, reason: str) -> SemanticCapAssessment:
    return SemanticCapAssessment(cap, (reason,))


def _test_cap() -> SemanticCapAssessment:
    return SemanticCapAssessment(
        RecommendationCap.MAX_REVIEW_CANDIDATE,
        ("Semantic role cap: test or fixture duplication needs review before editing.",),
        primary_action=ActionKind.RECORD_SHARED_CONCERN,
        review_floor=ReviewTier.REVIEW_CANDIDATE,
    )


def _clean_test_helper_edit_candidate(
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> bool:
    """Allow narrow test-helper clones through ordinary edit scoring.

    Test bodies and mixed scenario setup still need human review, but a
    standalone same-role helper pair with exact or near-identical
    parameterized-skeleton evidence is normal duplicate-code economics. If the
    action gates say it is safe, the semantic test cap should not suppress it.
    """

    if (
        metrics.member_count != TEST_HELPER_PAIR_MEMBER_COUNT
        or metrics.test_member_count != TEST_HELPER_PAIR_MEMBER_COUNT
    ):
        return False
    if has_editable_parameterized_skeleton_relation(metrics, policy):
        return metrics.test_relation_pair_count == 1
    return (
        metrics.test_duplicate_pair_count == 1
        and metrics.structural_duplicate_pair_count == 1
        and metrics.same_role_relation_count > 0
        and metrics.max_relation_risk_score <= 0.0
        and has_relation_kind(metrics, frozenset({RelationKind.BODY_IDENTICAL}))
    )


def _substantial_shared_logic(metrics: FindingMetrics, policy: AssessmentPolicy) -> bool:
    return (
        metrics.min_body_line_count >= policy.semantic_caps.substantial_body_line_count
        and metrics.min_stable_statement_count
        >= policy.semantic_caps.substantial_stable_statement_count
        and metrics.same_role_relation_count > 0
        and metrics.same_directory_relation_count > 0
    )


def _all_or_most(count: int, total: int, threshold: float) -> bool:
    return total > 0 and count / total >= threshold


def _has_dominant_semantic_duplicate_pair(
    count: int,
    total_duplicate_pairs: int,
    policy: AssessmentPolicy,
) -> bool:
    """Return whether exact duplicate evidence is guarded enough to cap.

    A singleton guarded duplicate pair is capped directly. In a broader mixed
    target, guarded pairs must reach the material duplicate-pair policy ratio
    before they cap the whole target. This avoids one-pair poisoning without
    letting protocol/API duplicate families drive edit recommendations.
    """

    return count > 0 and (
        total_duplicate_pairs <= 1
        or count / total_duplicate_pairs >= policy.semantic_caps.material_duplicate_pair_ratio
        or _all_or_most(
            count,
            total_duplicate_pairs,
            policy.semantic_caps.dominant_member_ratio,
        )
    )


def _dominant_members_or_relation_evidence(
    counts: RoleEvidenceCounts,
    *,
    metrics: FindingMetrics,
    threshold: float,
) -> bool:
    """Return whether a role dominates by members or by relation evidence.

    Member dominance prevents a single role-labelled member from poisoning a
    mixed target. Pair dominance handles the opposite case: a broad mixed
    cluster can still be driven by protocol/API duplicate evidence that should
    be capped even when the whole member set is not mostly protocol/API surface.
    """

    return (
        _all_or_most(
            counts.members,
            metrics.member_count,
            threshold,
        )
        or _all_or_most(
            counts.duplicate_pairs,
            metrics.structural_duplicate_pair_count,
            threshold,
        )
        or _relation_evidence_is_mostly(
            counts.relation_pairs,
            metrics,
            threshold,
        )
    )


def _relation_evidence_is_mostly(
    count: int,
    metrics: FindingMetrics,
    threshold: float,
) -> bool:
    return _all_or_most(
        count,
        metrics.guardrail_relation_pair_count,
        threshold,
    )


def _declaration_dominates(metrics: FindingMetrics, threshold: float) -> bool:
    """Return whether declaration-shape evidence drives the target.

    Declaration signatures are useful API topology facts, but they do not carry
    implementation bodies. We cap only when declaration evidence dominates so a
    mixed cluster can still surface a real implementation duplicate.
    """

    return _dominant_members_or_relation_evidence(
        _with_member_fallback(
            metrics.semantic_guardrails.declaration,
            _max_role_count(metrics, DECLARATION_SURFACE_ROLES),
        ),
        metrics=metrics,
        threshold=threshold,
    )


def _api_surface_dominates(metrics: FindingMetrics, threshold: float) -> bool:
    return _dominant_members_or_relation_evidence(
        metrics.semantic_guardrails.api_surface,
        metrics=metrics,
        threshold=threshold,
    )


def _with_member_fallback(
    counts: RoleEvidenceCounts,
    member_count: int,
) -> RoleEvidenceCounts:
    if counts.members:
        return counts
    return RoleEvidenceCounts(
        members=member_count,
        duplicate_pairs=counts.duplicate_pairs,
        relation_pairs=counts.relation_pairs,
    )


def _role_count(metrics: FindingMetrics, role: str) -> int:
    return (metrics.semantic_role_counts or {}).get(role, 0)


def _max_role_count(metrics: FindingMetrics, roles: frozenset[str]) -> int:
    counts = metrics.semantic_role_counts or {}
    return max((counts.get(role, 0) for role in roles), default=0)


def _capped_review_tier(review_tier: ReviewTier, cap: RecommendationCapLabel) -> ReviewTier:
    maximum = {
        RecommendationCap.ALLOW_RECOMMENDED_EDIT: ReviewTier.RECOMMENDED_EDIT,
        RecommendationCap.MAX_REVIEW_CANDIDATE: ReviewTier.REVIEW_CANDIDATE,
        RecommendationCap.MAX_TRACKING_SIGNAL: ReviewTier.TRACKING_SIGNAL,
        RecommendationCap.MAX_OBSERVATION: ReviewTier.OBSERVATION,
        RecommendationCap.DO_NOT_REFACTOR: ReviewTier.OBSERVATION,
    }.get(cap, ReviewTier.OBSERVATION)
    return maximum if _tier_rank(maximum) > _tier_rank(review_tier) else review_tier


def _floored_review_tier(review_tier: ReviewTier, floor: ReviewTier | None) -> ReviewTier:
    if not floor:
        return review_tier
    return floor if _tier_rank(floor) < _tier_rank(review_tier) else review_tier


def _tier_rank(review_tier: ReviewTier) -> int:
    return CAP_ORDER.get(review_tier, CAP_ORDER[ReviewTier.OBSERVATION])


__all__ = [
    "CappedSurface",
    "SemanticCapAssessment",
    "apply_semantic_cap",
    "semantic_cap_for",
]
