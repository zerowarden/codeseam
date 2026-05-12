from __future__ import annotations

from codeseam.analysis.relations.members import has_error_evidence, parameter_cost
from codeseam.analysis.relations.models import (
    AbstractionCostComponents,
    DeltaKind,
    MemberFeatures,
    RefactorabilityComponents,
    ScoreBand,
    SequenceComparison,
    SimilarityScores,
)
from codeseam.analysis.relations.policy import PAIR_POLICY, RELATION_ASSESSMENT_POLICY
from codeseam.analysis.relations.unification import SequenceSkeleton

type ScoreComponents = RefactorabilityComponents | AbstractionCostComponents

DELTA_RISK_WEIGHTS = {
    DeltaKind.RETURN_VALUE: 0.18,
    DeltaKind.ERROR_HANDLING: 0.18,
    DeltaKind.CONTROL_FLOW: 0.15,
    DeltaKind.LOOP: 0.14,
    DeltaKind.ARGUMENT_FLOW: 0.12,
    DeltaKind.CALLEE_NAME: 0.10,
    DeltaKind.RECEIVER_SHAPE: 0.10,
    DeltaKind.EXTRA_CONTEXT_MANAGER: 0.10,
    DeltaKind.DEFAULT_ARGUMENT: 0.06,
    DeltaKind.LITERAL_VALUE: 0.04,
    DeltaKind.EXTRA_LOCAL_TEMPORARY: 0.04,
    DeltaKind.EXTRA_ASSIGNMENT: 0.04,
    DeltaKind.EXTRA_TERMINAL_CALL: 0.08,
    DeltaKind.ARGUMENT_NORMALIZATION: 0.06,
}
DEFAULT_DELTA_RISK_WEIGHT = 0.08
BRANCH_DELTAS = {
    DeltaKind.CONTROL_FLOW,
    DeltaKind.ERROR_HANDLING,
    DeltaKind.EXTRA_CONTEXT_MANAGER,
    DeltaKind.LOOP,
}
LOCAL_TEMP_DELTAS = {DeltaKind.EXTRA_LOCAL_TEMPORARY, DeltaKind.EXTRA_ASSIGNMENT}


def relatedness_score(scores: SimilarityScores) -> float:
    score = (
        0.10
        + 0.20 * scores.parameter
        + 0.15 * scores.call
        + 0.15 * scores.sequence
        + 0.20 * scores.tree
        + 0.15 * scores.graph
        + 0.05 * scores.name
    )
    return round(min(1.0, score), 4)


def refactorability_components_features(
    left: MemberFeatures,
    right: MemberFeatures,
    *,
    sequence: SequenceComparison,
    anti_unification: SequenceSkeleton,
    abstraction_cost: float,
) -> RefactorabilityComponents:
    max_count = sequence.max_statement_count
    contiguous = max(sequence.common_prefix_length, sequence.common_suffix_length) / max_count
    return RefactorabilityComponents(
        common_region_size=round(0.22 * (sequence.lcs_length / max_count), 4),
        contiguous_common_region=round(0.18 * contiguous, 4),
        low_hole_count=round(
            0.16 * max(0.0, 1.0 - anti_unification.hole_count / 3),
            4,
        ),
        low_hole_complexity=round(
            0.14
            * max(
                0.0,
                1.0 - anti_unification.max_hole_size / max_count,
            ),
            4,
        ),
        same_return_shape=(
            0.10
            if left.return_signature and left.return_signature == right.return_signature
            else 0.0
        ),
        same_error_shape=(
            0.08
            if has_error_evidence(left.error_shape) and left.error_shape == right.error_shape
            else 0.0
        ),
        same_source_role=0.08 if left.role == right.role else 0.0,
        local_module_scope=0.04 if same_module_scope_features(left, right) else 0.0,
        abstraction_cost_penalty=-round(0.35 * abstraction_cost, 4),
    )


def abstraction_cost_components_features(
    left: MemberFeatures,
    right: MemberFeatures,
    *,
    anti_unification: SequenceSkeleton,
    deltas: tuple[DeltaKind, ...],
    parameter_similarity: float,
) -> AbstractionCostComponents:
    max_statement_count = max(left.body_line_count, right.body_line_count, 1)
    max_hole_size = anti_unification.max_hole_size
    return AbstractionCostComponents(
        parameter_count_estimate=round(
            0.18 * parameter_cost(max(left.member.parameter_count, right.member.parameter_count)),
            4,
        ),
        hole_count=round(
            0.16 * min(1.0, anti_unification.hole_count / 3),
            4,
        ),
        hole_complexity=round(0.16 * min(1.0, max_hole_size / max_statement_count), 4),
        branch_delta_count=round(0.12 * min(1.0, delta_count(deltas, BRANCH_DELTAS) / 3), 4),
        local_temp_delta_count=round(
            0.10 * min(1.0, delta_count(deltas, LOCAL_TEMP_DELTAS) / 2),
            4,
        ),
        callback_or_strategy_need=(
            0.10 if needs_callback_or_strategy_score(deltas, parameter_similarity) else 0.0
        ),
        cross_module_dependency_cost=0.10 if not same_module_scope_features(left, right) else 0.0,
        public_api_cost=0.08 if public_api_cost_features(left, right) else 0.0,
    )


def confidence_score(relatedness: float, risk_score: float) -> float:
    return round(max(0.0, min(1.0, relatedness * (1 - 0.5 * risk_score))), 4)


def component_sum(components: ScoreComponents) -> float:
    return round(
        max(
            0.0,
            min(1.0, components.total()),
        ),
        4,
    )


def risk_score(deltas: tuple[DeltaKind, ...]) -> float:
    total = sum(DELTA_RISK_WEIGHTS.get(delta, DEFAULT_DELTA_RISK_WEIGHT) for delta in deltas)
    return round(min(1.0, total), 4)


def refactorability_kind(score: float) -> ScoreBand:
    if score >= RELATION_ASSESSMENT_POLICY.refactorability_high_threshold:
        return ScoreBand.HIGH
    if score >= RELATION_ASSESSMENT_POLICY.refactorability_medium_threshold:
        return ScoreBand.MEDIUM
    if score > 0:
        return ScoreBand.LOW
    return ScoreBand.TRACK_ONLY


def delta_count(deltas: tuple[DeltaKind, ...], kinds: set[DeltaKind]) -> int:
    return sum(delta in kinds for delta in deltas)


def needs_callback_or_strategy_score(
    deltas: tuple[DeltaKind, ...],
    parameter_similarity: float,
) -> bool:
    if DeltaKind.ARGUMENT_NORMALIZATION in deltas:
        return False
    return bool(
        {DeltaKind.CALLEE_NAME, DeltaKind.RECEIVER_SHAPE, DeltaKind.ARGUMENT_FLOW} & set(deltas)
        and parameter_similarity < PAIR_POLICY.parameter_flow_threshold
    )


def same_module_scope_features(left: MemberFeatures, right: MemberFeatures) -> bool:
    return left.member.module_scope == right.member.module_scope


def public_api_cost_features(left: MemberFeatures, right: MemberFeatures) -> bool:
    return left.member.is_public_symbol or right.member.is_public_symbol
