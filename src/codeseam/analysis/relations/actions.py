from __future__ import annotations

from codeseam.analysis.relations.kinds import PARAMETERIZED_SKELETON_RELATIONS
from codeseam.analysis.relations.models import (
    ActionKind,
    ActionStatus,
    MemberRef,
    PairActionInput,
    RefactorAction,
    RelationKind,
    RelationPair,
)
from codeseam.analysis.relations.policy import PAIR_POLICY, RELATION_ASSESSMENT_POLICY

PARAMETERIZED_SKELETON_PRECONDITIONS = (
    "same_signature_shape",
    "near_identical_body_tree",
    "parameterized_skeleton",
)


def pair_actions(context: PairActionInput) -> list[RefactorAction]:
    relation_kind = context.relation_kind
    refactorability = context.refactorability
    abstraction_cost = context.abstraction_cost
    confidence = context.confidence
    deltas = context.deltas
    delta_codes = tuple(delta.value for delta in deltas)
    applies_to = [context.left, context.right]

    if relation_kind in {RelationKind.BODY_IDENTICAL, RelationKind.BODY_PARAMETERIZED}:
        return [
            RefactorAction(
                kind=ActionKind.CONSOLIDATE_CLONE,
                status=ActionStatus.RECOMMENDED,
                confidence=round(max(0.6, refactorability, confidence), 4),
                applies_to=tuple(applies_to),
                preconditions=(
                    "same_body_after_normalization",
                    "same_signature_shape",
                    "same_parameter_use_vectors",
                ),
            )
        ]
    if relation_kind in PARAMETERIZED_SKELETON_RELATIONS and _editable_parameterized_skeleton(
        refactorability,
        abstraction_cost,
    ):
        return [
            RefactorAction(
                kind=ActionKind.CONSOLIDATE_CLONE,
                status=ActionStatus.RECOMMENDED,
                confidence=round(max(0.6, min(confidence, refactorability)), 4),
                applies_to=tuple(applies_to),
                preconditions=PARAMETERIZED_SKELETON_PRECONDITIONS,
                reason_codes=delta_codes,
            )
        ]
    if relation_kind == RelationKind.ARGUMENT_NORMALIZATION_WRAPPER:
        return [
            RefactorAction(
                kind=ActionKind.REUSE_EXISTING_HELPER,
                status=ActionStatus.RECOMMENDED,
                confidence=round(max(0.62, min(confidence, refactorability)), 4),
                applies_to=tuple(applies_to),
                preconditions=(
                    "same_return_contract",
                    "shared_operation_after_argument_normalization",
                    "simple_argument_transform",
                    "existing_helper_boundary",
                ),
                reason_codes=delta_codes,
                normalization=context.normalization,
            )
        ]
    if relation_kind == RelationKind.COMMON_PREFIX_DIVERGENT_TAIL:
        return [
            RefactorAction(
                kind=ActionKind.RECORD_SHARED_CONCERN,
                status=ActionStatus.RECOMMENDED,
                confidence=round(max(0.74, confidence), 4),
                applies_to=tuple(applies_to),
                reason_codes=delta_codes,
            ),
            RefactorAction(
                kind=ActionKind.DO_NOT_REFACTOR,
                status=ActionStatus.NOT_RECOMMENDED,
                confidence=min(0.51, refactorability),
                applies_to=tuple(applies_to),
                extracted_region_common_prefix_length=context.sequence.common_prefix_length,
                rejection_reasons=("COMMON_REGION_TOO_SMALL",),
            ),
        ]
    if relation_kind == RelationKind.COMMON_WRAPPER_DIFFERENT_CORE:
        rejection_reasons = _wrapper_rejection_reasons(abstraction_cost)
        primary_action = (
            ActionKind.DO_NOT_REFACTOR if rejection_reasons else ActionKind.INTRODUCE_ABSTRACTION
        )
        primary_status = (
            ActionStatus.NOT_RECOMMENDED if rejection_reasons else ActionStatus.RECOMMENDED
        )
        return [
            RefactorAction(
                kind=primary_action,
                status=primary_status,
                confidence=round(max(0.6, min(confidence, refactorability)), 4),
                applies_to=tuple(applies_to),
                preconditions=(
                    "same_signature_shape",
                    "shared_wrapper_sequence",
                    "different_core_operation",
                ),
                reason_codes=delta_codes,
                rejection_reasons=tuple(rejection_reasons),
            ),
            RefactorAction(
                kind=ActionKind.RECORD_SHARED_CONCERN,
                status=ActionStatus.RECOMMENDED,
                confidence=round(max(0.7, confidence), 4),
                applies_to=tuple(applies_to),
                reason_codes=delta_codes,
            ),
        ]
    return []


def refactor_action_candidates(
    relation_pairs: list[RelationPair],
    members: list[MemberRef],
) -> list[RefactorAction]:
    actions = [action for pair in relation_pairs for action in pair.refactor_action_candidates]
    if _merge_all_not_recommended(relation_pairs, members):
        actions.append(
            RefactorAction(
                kind=ActionKind.DO_NOT_REFACTOR,
                status=ActionStatus.NOT_RECOMMENDED,
                confidence=0.0,
                applies_to=tuple(members),
                rejection_reasons=("GROUP_TOO_BROAD_FOR_SINGLE_REFACTOR",),
            )
        )
    return _unique_actions(actions)[: PAIR_POLICY.action_limit]


def _wrapper_rejection_reasons(abstraction_cost: float) -> list[str]:
    return (
        ["HIGH_ABSTRACTION_COST"]
        if abstraction_cost >= RELATION_ASSESSMENT_POLICY.high_abstraction_cost_threshold
        else []
    )


def _editable_parameterized_skeleton(refactorability: float, abstraction_cost: float) -> bool:
    return (
        refactorability >= RELATION_ASSESSMENT_POLICY.refactorability_high_threshold
        and abstraction_cost
        <= RELATION_ASSESSMENT_POLICY.parameterized_skeleton_max_abstraction_cost
    )


def _merge_all_not_recommended(
    relation_pairs: list[RelationPair],
    members: list[MemberRef],
) -> bool:
    return len(members) > PAIR_POLICY.multi_member_threshold and any(
        pair.relation_kind == RelationKind.COMMON_PREFIX_DIVERGENT_TAIL for pair in relation_pairs
    )


def _unique_actions(actions: list[RefactorAction]) -> list[RefactorAction]:
    seen = set()
    unique = []
    for action in actions:
        key = (
            action.kind,
            action.status,
            action.reason_codes,
            action.rejection_reasons,
        )
        if key not in seen:
            unique.append(action)
            seen.add(key)
    return unique
