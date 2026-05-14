from __future__ import annotations

from codeseam.analysis.relations.models import (
    ActionKind,
    CloneClass,
    CloneClassification,
    CloneClassificationInput,
    RelationKind,
)
from codeseam.analysis.relations.policy import (
    PAIR_POLICY,
    RELATION_ASSESSMENT_POLICY,
    STRUCTURAL_POLICY,
)

type CloneMetadata = tuple[CloneClass, str]

EXTRACT_REGION_RELATIONS: frozenset[RelationKind] = frozenset(
    {
        RelationKind.COMMON_PREFIX_DIVERGENT_TAIL,
        RelationKind.COMMON_SUFFIX_DIVERGENT_SETUP,
        RelationKind.SAME_CORE_DIFFERENT_WRAPPER,
    }
)

RELATION_CLONE_METADATA: dict[RelationKind, CloneMetadata] = {
    RelationKind.NONE: (
        CloneClass.SIGNATURE_SIGNAL_ONLY,
        "boundary_only",
    ),
    RelationKind.BODY_IDENTICAL: (
        CloneClass.TYPE_1_EXACT,
        "exact_normalized_body",
    ),
    RelationKind.BODY_PARAMETERIZED: (
        CloneClass.TYPE_2_PARAMETERIZED,
        "parameterized_normalized_body",
    ),
    RelationKind.SAME_SKELETON_DIFFERENT_LITERALS: (
        CloneClass.TYPE_2_PARAMETERIZED,
        "parameterized_normalized_body",
    ),
    RelationKind.ARGUMENT_NORMALIZATION_WRAPPER: (
        CloneClass.TYPE_3_NEAR_MISS,
        "typed_argument_normalization_wrapper",
    ),
    RelationKind.SAME_SKELETON_DIFFERENT_CALLEES: (
        CloneClass.TYPE_3_NEAR_MISS,
        "same_skeleton_different_callees",
    ),
    RelationKind.COMMON_PREFIX_DIVERGENT_TAIL: (
        CloneClass.TYPE_3_NEAR_MISS,
        "common_prefix_divergent_tail",
    ),
    RelationKind.COMMON_SUFFIX_DIVERGENT_SETUP: (
        CloneClass.TYPE_3_NEAR_MISS,
        "common_suffix_divergent_setup",
    ),
    RelationKind.COMMON_WRAPPER_DIFFERENT_CORE: (
        CloneClass.TYPE_3_NEAR_MISS,
        "common_wrapper_different_core",
    ),
    RelationKind.SAME_CORE_DIFFERENT_WRAPPER: (
        CloneClass.TYPE_3_NEAR_MISS,
        "same_core_different_wrapper",
    ),
    RelationKind.SAME_ARGUMENT_FLOW_DIFFERENT_CONTROL: (
        CloneClass.CONTRACT_ANALOGY,
        "contract_analogy",
    ),
    RelationKind.SAME_CALL_SET_DIFFERENT_ORDER: (
        CloneClass.CONTRACT_ANALOGY,
        "contract_analogy",
    ),
}
DEFAULT_CLONE_METADATA: CloneMetadata = (
    CloneClass.SIGNATURE_SIGNAL_ONLY,
    "unclassified_relation",
)


def clone_metadata(relation_kind: RelationKind) -> CloneMetadata:
    return RELATION_CLONE_METADATA.get(relation_kind, DEFAULT_CLONE_METADATA)


def clone_classification_for(context: CloneClassificationInput) -> CloneClassification:
    clone_type, syntactic_strength = clone_metadata(context.relation_kind)
    return CloneClassification(
        clone_type=clone_type,
        syntactic_strength=syntactic_strength,
        default_action=default_action(
            context.relation_kind,
            clone_type,
            context.refactorability,
            context.abstraction_cost,
        ),
        basis=clone_basis_for(context),
    )


def default_action(
    relation_kind: RelationKind,
    clone_type: CloneClass,
    refactorability: float,
    abstraction_cost: float,
) -> ActionKind:
    action = ActionKind.RECORD_SHARED_CONCERN
    if clone_type == CloneClass.SIGNATURE_SIGNAL_ONLY:
        action = ActionKind.OBSERVE
    elif clone_type == CloneClass.CONTRACT_ANALOGY:
        action = ActionKind.RECORD_SHARED_CONCERN
    elif abstraction_cost >= RELATION_ASSESSMENT_POLICY.high_abstraction_cost_threshold:
        action = ActionKind.RECORD_SHARED_CONCERN
    elif relation_kind == RelationKind.ARGUMENT_NORMALIZATION_WRAPPER:
        action = ActionKind.REUSE_EXISTING_HELPER
    elif clone_type in {CloneClass.TYPE_1_EXACT, CloneClass.TYPE_2_PARAMETERIZED}:
        action = ActionKind.CONSOLIDATE_CLONE
    elif (
        relation_kind == RelationKind.COMMON_WRAPPER_DIFFERENT_CORE
        and refactorability >= RELATION_ASSESSMENT_POLICY.refactorability_medium_threshold
    ):
        action = ActionKind.INTRODUCE_ABSTRACTION
    elif relation_kind in EXTRACT_REGION_RELATIONS:
        action = ActionKind.INSPECT_SHARED_LIFECYCLE
    return action


def clone_basis_for(context: CloneClassificationInput) -> tuple[str, ...]:
    basis: list[str] = []
    if context.flags.same_signature_shape:
        basis.append("same_signature_shape")
    if context.argument_normalization.is_detected:
        basis.append("typed_argument_normalization_wrapper")
    if context.flags.body_hash_match:
        basis.append("normalized_body_identity")
    if context.scores.name >= STRUCTURAL_POLICY.name_similarity_threshold:
        basis.append("normalized_name_similarity")
    if (
        context.tree_distance_source in {"body_hash", "ordered_tree_edit_distance"}
        and context.tree_similarity >= STRUCTURAL_POLICY.tree_similarity_threshold
    ):
        basis.append("body_tree_similarity")
    if context.parameter_similarity >= PAIR_POLICY.parameter_flow_threshold:
        basis.append("parameter_use_similarity")
    if context.call_similarity >= PAIR_POLICY.call_fingerprint_threshold:
        basis.append("call_fingerprint_overlap")
    if context.sequence.lcs_length >= STRUCTURAL_POLICY.min_statement_lcs_length:
        basis.append("statement_sequence_alignment")
    if (
        context.anti_unification.stable_statement_count
        >= STRUCTURAL_POLICY.min_stable_statement_count
    ):
        basis.append("anti_unification_template")
    if context.deltas:
        basis.append("structural_delta_classification")
    return tuple(dict.fromkeys(basis))
