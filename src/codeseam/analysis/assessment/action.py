from __future__ import annotations

from codeseam.analysis.assessment.definitions import (
    AssessmentGate,
    FindingActionStatus,
    RecommendationStatus,
)
from codeseam.analysis.assessment.evidence import (
    EVIDENCE_ANTI_UNIFICATION_TEMPLATE,
    EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER,
)
from codeseam.analysis.assessment.metrics import metric_count, same_language_scope
from codeseam.analysis.assessment.models import (
    AbstractionFit,
    ActionAssessment,
    DetectionConfidence,
    EvidenceSummary,
    MaintenancePayoff,
    SemanticRisk,
)
from codeseam.analysis.assessment.policy import AssessmentPolicy
from codeseam.analysis.assessment.relation_evidence import (
    has_clean_clone_relation,
    has_editable_parameterized_skeleton_relation,
    relation_count,
)
from codeseam.analysis.findings import FindingMetrics
from codeseam.analysis.relations.models import (
    ActionKind,
    RefactorAction,
    RefactorActionSummary,
    RelationKind,
)
from codeseam.analysis.relations.summary import summarize_actions

LOW_CLONE_RISK = 0.30
LOW_HELPER_RISK = 0.20
LOW_INTRODUCTION_RISK = 0.20
CLEAN_CLONE_COST = 0.25
LOW_PUBLIC_API_COST = 0.25
NEAR_IDENTICAL_TREE_SIMILARITY = 0.95
MAX_INTRODUCTION_COST = 0.45
MAX_INTRODUCTION_HOLES = 2
MAX_LOW_COMPLEXITY_HOLE_SIZE = 3
MIN_COMMON_REGION_SIZE = 2
MIN_LOCAL_DUPLICATE_HELPER_LINES = 5
MAX_SMALL_HELPER_LINES = 12
RELATION_PRECONDITION_SHARED_OPERATION = "shared_operation_after_argument_normalization"
EDIT_ACTIONS = frozenset(
    (
        ActionKind.CONSOLIDATE_CLONE,
        ActionKind.EXTRACT_SMALL_HELPER,
        ActionKind.INTRODUCE_ABSTRACTION,
        ActionKind.REUSE_EXISTING_HELPER,
    )
)
RELATION_TRACKING_ACTIONS = frozenset(
    (
        ActionKind.RECORD_SHARED_CONCERN,
        ActionKind.INSPECT_SHARED_LIFECYCLE,
    )
)


def recommend_action(  # noqa: PLR0913
    actions: tuple[RefactorAction, ...],
    fallback_summary: RefactorActionSummary | None,
    *,
    detection: DetectionConfidence,
    fit: AbstractionFit,
    risk: SemanticRisk,
    payoff: MaintenancePayoff,
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    policy: AssessmentPolicy,
) -> ActionAssessment:
    """Score the best action after concept scores are known.

    This keeps action recommendation downstream from evidence assessment. A
    relation can be real while the best action is still `observe` or
    `do_not_refactor`.
    """
    summary = summarize_actions(list(actions))
    if not summary.has_actions and fallback_summary is not None:
        summary = fallback_summary
    requested_action = _primary_action(summary)
    action_preconditions = _action_preconditions(actions, requested_action)
    requested_passed, requested_failed = _preconditions(
        requested_action,
        detection,
        fit,
        risk,
        payoff,
        metrics,
        evidence,
        action_preconditions,
        policy,
    )
    action = _fallback_action(requested_action, detection, requested_failed)
    fallback_reasons: tuple[AssessmentGate, ...] = ()
    if action != requested_action:
        _, selected_failed = _preconditions(
            action,
            detection,
            fit,
            risk,
            payoff,
            metrics,
            evidence,
            (),
            policy,
        )
        passed = requested_passed
        failed = requested_failed
        fallback_reasons = tuple(requested_failed)
    else:
        passed = requested_passed
        failed = selected_failed = requested_failed
    score = _recommendation_score(action, detection, fit, risk, payoff)
    status = _status(action, score, risk, fit, selected_failed, metrics, policy)
    return ActionAssessment(
        action_kind=action,
        status=status,
        preconditions_failed=tuple(failed),
        detection_confidence=detection.score,
        abstraction_fit=fit.score,
        semantic_risk=risk.score,
        abstraction_cost=fit.cost,
        recommendation_confidence=_recommendation_confidence(actions, action, score, status),
        recommendation_score=score,
        requested_action_kind=requested_action,
        preconditions_passed=tuple(passed),
        fallback_reasons=tuple(fallback_reasons),
    )


def action_status_for(assessment: ActionAssessment) -> FindingActionStatus:
    action = assessment.action_kind
    status = assessment.status
    if action is ActionKind.DO_NOT_REFACTOR:
        return FindingActionStatus.DO_NOT_REFACTOR
    if action is ActionKind.OBSERVE:
        return FindingActionStatus.OBSERVE
    if action in {ActionKind.RECORD_SHARED_CONCERN, ActionKind.INSPECT_SHARED_LIFECYCLE}:
        return FindingActionStatus.RECORD_SHARED_CONCERN
    if status is RecommendationStatus.RECOMMENDED:
        return FindingActionStatus.RECOMMENDED_EDIT
    return FindingActionStatus.CAUTIOUS_CANDIDATE


def _primary_action(summary: RefactorActionSummary) -> ActionKind:
    if summary.primary_action:
        return summary.primary_action
    if summary.secondary_action:
        return summary.secondary_action
    if ActionKind.DO_NOT_REFACTOR in summary.not_recommended:
        return ActionKind.DO_NOT_REFACTOR
    return ActionKind.OBSERVE


def _preconditions(  # noqa: PLR0913
    action: ActionKind,
    detection: DetectionConfidence,
    fit: AbstractionFit,
    risk: SemanticRisk,
    payoff: MaintenancePayoff,
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    action_preconditions: tuple[str, ...],
    policy: AssessmentPolicy,
) -> tuple[list[AssessmentGate], list[AssessmentGate]]:
    passed: list[AssessmentGate] = []
    failed: list[AssessmentGate] = []
    if action in EDIT_ACTIONS | RELATION_TRACKING_ACTIONS:
        _check(
            passed,
            failed,
            AssessmentGate.RELATION_DETECTED,
            detection.score >= policy.detection_relation_threshold,
        )
    if action in EDIT_ACTIONS:
        _check(
            passed,
            failed,
            AssessmentGate.MAINTENANCE_PAYOFF,
            payoff.score >= policy.review_candidate_threshold
            or _substantial_intra_function_duplicate(metrics)
            or (
                action is ActionKind.CONSOLIDATE_CLONE
                and has_editable_parameterized_skeleton_relation(metrics, policy)
            ),
        )
    if action is ActionKind.CONSOLIDATE_CLONE:
        _consolidate_clone_preconditions(passed, failed, metrics, risk, fit, policy)
    elif action is ActionKind.EXTRACT_SMALL_HELPER:
        _extract_small_helper_preconditions(
            passed,
            failed,
            metrics,
            evidence,
            action_preconditions,
            risk,
            fit,
        )
    elif action is ActionKind.REUSE_EXISTING_HELPER:
        _reuse_existing_helper_preconditions(
            passed,
            failed,
            metrics,
            evidence,
            action_preconditions,
            risk,
            fit,
            policy,
        )
    elif action is ActionKind.INTRODUCE_ABSTRACTION:
        _introduce_abstraction_preconditions(
            passed,
            failed,
            metrics,
            evidence,
            risk,
            fit,
        )
    elif action is ActionKind.RECORD_SHARED_CONCERN:
        _check(passed, failed, AssessmentGate.SHARED_CONCERN_ONLY, detection.score > 0.0)
    elif action is ActionKind.INSPECT_SHARED_LIFECYCLE:
        _check(passed, failed, AssessmentGate.SHARED_LIFECYCLE_ONLY, detection.score > 0.0)
    elif action is ActionKind.OBSERVE:
        passed.append(AssessmentGate.INVENTORY_ONLY)
    elif action is ActionKind.DO_NOT_REFACTOR:
        passed.append(AssessmentGate.EXPLICIT_SAFETY_STOP)
    return passed, failed


def _check(
    passed: list[AssessmentGate],
    failed: list[AssessmentGate],
    name: AssessmentGate,
    condition: bool,
) -> None:
    (passed if condition else failed).append(name)


def _consolidate_clone_preconditions(  # noqa: PLR0913
    passed: list[AssessmentGate],
    failed: list[AssessmentGate],
    metrics: FindingMetrics,
    risk: SemanticRisk,
    fit: AbstractionFit,
    policy: AssessmentPolicy,
) -> None:
    _check(
        passed,
        failed,
        AssessmentGate.CLEAN_CLONE_RELATION,
        has_clean_clone_relation(metrics, policy),
    )
    _check(
        passed,
        failed,
        AssessmentGate.BODY_HASH_OR_NEAR_IDENTICAL_TREE,
        metrics.body_hash_match_count > 0
        or metrics.max_tree_similarity >= NEAR_IDENTICAL_TREE_SIMILARITY,
    )
    _check(passed, failed, AssessmentGate.LOW_SEMANTIC_RISK, risk.score <= LOW_CLONE_RISK)
    _check(passed, failed, AssessmentGate.LOW_ABSTRACTION_COST, fit.cost <= CLEAN_CLONE_COST)
    _check(passed, failed, AssessmentGate.SAME_ROLE_SEMANTICS, not _mixed_role_semantics(metrics))


def _extract_small_helper_preconditions(  # noqa: PLR0913
    passed: list[AssessmentGate],
    failed: list[AssessmentGate],
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    action_preconditions: tuple[str, ...],
    risk: SemanticRisk,
    fit: AbstractionFit,
) -> None:
    local_duplicate = _has_intra_function_duplicate(metrics)
    if local_duplicate:
        passed.append(AssessmentGate.INTRA_FUNCTION_DUPLICATE_BLOCK)
    _check(
        passed,
        failed,
        AssessmentGate.SUBSTANTIAL_LOCAL_DUPLICATE_BLOCK,
        not local_duplicate or _substantial_intra_function_duplicate(metrics),
    )
    _check(
        passed,
        failed,
        AssessmentGate.ARGUMENT_NORMALIZATION_DETECTED,
        local_duplicate
        or evidence.has(EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER)
        or relation_count(metrics, RelationKind.ARGUMENT_NORMALIZATION_WRAPPER) > 0,
    )
    _check(
        passed,
        failed,
        AssessmentGate.SAME_DOWNSTREAM_OPERATION,
        local_duplicate or RELATION_PRECONDITION_SHARED_OPERATION in action_preconditions,
    )
    _check(
        passed,
        failed,
        AssessmentGate.SMALL_COMMON_BODY,
        0 < metrics.max_body_line_count <= MAX_SMALL_HELPER_LINES,
    )
    _check(passed, failed, AssessmentGate.LOW_PUBLIC_API_COST, fit.cost <= LOW_PUBLIC_API_COST)
    _check(passed, failed, AssessmentGate.LOW_SEMANTIC_RISK, risk.score <= LOW_HELPER_RISK)


def _reuse_existing_helper_preconditions(  # noqa: PLR0913
    passed: list[AssessmentGate],
    failed: list[AssessmentGate],
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    action_preconditions: tuple[str, ...],
    risk: SemanticRisk,
    fit: AbstractionFit,
    policy: AssessmentPolicy,
) -> None:
    _check(
        passed,
        failed,
        AssessmentGate.ARGUMENT_NORMALIZATION_DETECTED,
        evidence.has(EVIDENCE_ARGUMENT_NORMALIZATION_WRAPPER)
        or relation_count(metrics, RelationKind.ARGUMENT_NORMALIZATION_WRAPPER) > 0,
    )
    _check(
        passed,
        failed,
        AssessmentGate.SAME_DOWNSTREAM_OPERATION,
        RELATION_PRECONDITION_SHARED_OPERATION in action_preconditions,
    )
    _check(
        passed,
        failed,
        AssessmentGate.SIMPLE_ARGUMENT_TRANSFORM,
        AssessmentGate.SIMPLE_ARGUMENT_TRANSFORM.value in action_preconditions,
    )
    _check(
        passed,
        failed,
        AssessmentGate.EXISTING_HELPER_BOUNDARY,
        AssessmentGate.EXISTING_HELPER_BOUNDARY.value in action_preconditions,
    )
    _check(
        passed,
        failed,
        AssessmentGate.REVIEWABLE_SEMANTIC_RISK,
        risk.score < policy.risk_block_threshold,
    )
    _check(
        passed,
        failed,
        AssessmentGate.BOUNDED_ABSTRACTION_COST,
        fit.cost < policy.cost_block_threshold,
    )


def _introduce_abstraction_preconditions(  # noqa: PLR0913
    passed: list[AssessmentGate],
    failed: list[AssessmentGate],
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
    risk: SemanticRisk,
    fit: AbstractionFit,
) -> None:
    policy_constant = metrics.policy_constant_duplicate_count > 0
    hole_metrics_available = policy_constant or _hole_metrics_available(metrics, evidence)
    _check(
        passed,
        failed,
        AssessmentGate.STABLE_COMMON_REGION,
        policy_constant or _common_region_size(metrics) >= MIN_COMMON_REGION_SIZE,
    )
    _check(
        passed,
        failed,
        AssessmentGate.LOW_HOLE_COUNT,
        hole_metrics_available and metrics.max_hole_count <= MAX_INTRODUCTION_HOLES,
    )
    _check(
        passed,
        failed,
        AssessmentGate.LOW_HOLE_COMPLEXITY,
        hole_metrics_available and metrics.max_hole_size <= MAX_LOW_COMPLEXITY_HOLE_SIZE,
    )
    _check(
        passed,
        failed,
        AssessmentGate.LOW_BRANCH_DELTA,
        _delta_count(metrics, "branch_delta") <= 1,
    )
    _check(passed, failed, AssessmentGate.LOW_SEMANTIC_RISK, risk.score <= LOW_INTRODUCTION_RISK)
    _check(
        passed,
        failed,
        AssessmentGate.BOUNDED_ABSTRACTION_COST,
        fit.cost <= MAX_INTRODUCTION_COST,
    )
    _check(passed, failed, AssessmentGate.CLEAR_BOUNDARY_OWNER, _clear_boundary_owner(metrics))


def _fallback_action(
    action: ActionKind,
    detection: DetectionConfidence,
    failed: list[AssessmentGate],
) -> ActionKind:
    if not failed:
        return action

    selected = action
    if AssessmentGate.RELATION_DETECTED in failed:
        selected = ActionKind.OBSERVE
    elif failed == [AssessmentGate.MAINTENANCE_PAYOFF]:
        selected = action
    elif action is ActionKind.INTRODUCE_ABSTRACTION:
        selected = ActionKind.RECORD_SHARED_CONCERN if detection.score > 0.0 else ActionKind.OBSERVE
    elif action is ActionKind.EXTRACT_SMALL_HELPER:
        selected = ActionKind.RECORD_SHARED_CONCERN if detection.score > 0.0 else ActionKind.OBSERVE
    elif action is ActionKind.CONSOLIDATE_CLONE:
        selected = ActionKind.DO_NOT_REFACTOR
    return selected


def _recommendation_score(
    action: ActionKind,
    detection: DetectionConfidence,
    fit: AbstractionFit,
    risk: SemanticRisk,
    payoff: MaintenancePayoff,
) -> float:
    if action not in EDIT_ACTIONS:
        return 0.0
    safety = max(0.0, 1.0 - max(risk.score, fit.cost))
    score = detection.score * fit.score * payoff.score * safety
    return round(max(0.0, min(1.0, score)), 4)


def _status(  # noqa: PLR0911, PLR0913
    action: ActionKind,
    score: float,
    risk: SemanticRisk,
    fit: AbstractionFit,
    failed: list[AssessmentGate],
    metrics: FindingMetrics,
    policy: AssessmentPolicy,
) -> RecommendationStatus:
    if action is ActionKind.DO_NOT_REFACTOR:
        return RecommendationStatus.NOT_RECOMMENDED
    if action in {
        ActionKind.OBSERVE,
        ActionKind.RECORD_SHARED_CONCERN,
        ActionKind.INSPECT_SHARED_LIFECYCLE,
    }:
        return RecommendationStatus.CAUTIOUS
    if risk.score >= policy.risk_block_threshold or fit.cost >= policy.cost_block_threshold:
        return RecommendationStatus.NOT_RECOMMENDED
    if failed:
        return RecommendationStatus.CAUTIOUS
    if action is ActionKind.CONSOLIDATE_CLONE and has_editable_parameterized_skeleton_relation(
        metrics,
        policy,
    ):
        return RecommendationStatus.RECOMMENDED
    if action is ActionKind.CONSOLIDATE_CLONE and score >= policy.review_candidate_threshold:
        return RecommendationStatus.RECOMMENDED
    if (
        action is ActionKind.INTRODUCE_ABSTRACTION
        and metrics.policy_constant_duplicate_count
        and risk.score <= LOW_INTRODUCTION_RISK
        and fit.cost <= MAX_INTRODUCTION_COST
    ):
        return RecommendationStatus.RECOMMENDED
    if (
        action is ActionKind.EXTRACT_SMALL_HELPER
        and _substantial_intra_function_duplicate(metrics)
        and risk.score <= LOW_HELPER_RISK
        and fit.cost <= LOW_PUBLIC_API_COST
    ):
        return RecommendationStatus.RECOMMENDED
    if score >= policy.recommended_edit_threshold and risk.score < policy.risk_cautious_threshold:
        return RecommendationStatus.RECOMMENDED
    return RecommendationStatus.CAUTIOUS


def _recommendation_confidence(
    actions: tuple[RefactorAction, ...],
    selected_action: ActionKind,
    score: float,
    status: RecommendationStatus,
) -> float:
    if status is RecommendationStatus.NOT_RECOMMENDED or selected_action not in EDIT_ACTIONS:
        return 0.0
    action_confidence = max(
        (float(action.confidence) for action in actions if action.kind is selected_action),
        default=0.0,
    )
    return round(min(0.96, max(score, action_confidence * 0.5)), 4)


def _action_preconditions(
    actions: tuple[RefactorAction, ...],
    action_kind: ActionKind,
) -> tuple[str, ...]:
    values: list[str] = []
    for action in actions:
        if action.kind is action_kind:
            values.extend(action.preconditions)
    return tuple(values)


def _has_intra_function_duplicate(metrics: FindingMetrics) -> bool:
    return metrics.intra_function_duplicate_block_count > 0


def _substantial_intra_function_duplicate(metrics: FindingMetrics) -> bool:
    return (
        _has_intra_function_duplicate(metrics)
        and metrics.max_body_line_count >= MIN_LOCAL_DUPLICATE_HELPER_LINES
    )


def _delta_count(metrics: FindingMetrics, delta_kind: str) -> int:
    return metric_count(metrics.delta_kind_counts, delta_kind)


def _mixed_role_semantics(metrics: FindingMetrics) -> bool:
    relation_count = (
        metrics.structural_duplicate_pair_count or metrics.structural_relation_pair_count
    )
    return relation_count > 0 and metrics.same_role_relation_count < relation_count


def _common_region_size(metrics: FindingMetrics) -> float:
    return float(metrics.max_stable_statement_count)


def _hole_metrics_available(
    metrics: FindingMetrics,
    evidence: EvidenceSummary,
) -> bool:
    return (
        evidence.has(EVIDENCE_ANTI_UNIFICATION_TEMPLATE)
        or metrics.max_hole_count > 0
        or metrics.max_hole_size > 0
    )


def _clear_boundary_owner(metrics: FindingMetrics) -> bool:
    if metrics.policy_constant_duplicate_count:
        return True
    return (
        metrics.language_count <= 1 and metrics.adapter_count <= 1 and same_language_scope(metrics)
    )


__all__ = ["action_status_for", "recommend_action"]
