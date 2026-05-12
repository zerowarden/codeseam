from __future__ import annotations

from functools import lru_cache

from codeseam.analysis import (
    AbstractionCostComponents,
    ActionKind,
    ActionStatus,
    ArgumentNormalization,
    CloneClass,
    CloneClassification,
    ContextClassification,
    DeltaKind,
    MemberRef,
    RefactorabilityComponents,
    RefactorAction,
    RefactorShape,
    RelationBasis,
    RelationFlags,
    RelationKind,
    RelationPair,
    RelationScores,
    ScoreBand,
    SequenceComparison,
    SequenceSkeleton,
    SequenceTemplateItem,
    TreeComparison,
    sequence_skeleton_summary,
)
from codeseam.platform import Json, json_float, json_int, json_text_list, string_tuple


@lru_cache(maxsize=8192)
def member_ref_payload(member: MemberRef) -> Json:
    return {
        "signature_id": member.signature_id,
        "function_id": member.function_id,
        "file": member.file,
        "symbol": member.symbol,
        "start_line": member.start_line,
        "end_line": member.end_line,
        "semantic_roles": list(member.semantic_roles),
        "semantic_role_reasons": list(member.semantic_role_reasons),
    }


def member_ref_from_payload(data: object) -> MemberRef:
    payload = data if isinstance(data, dict) else {}
    return MemberRef(
        signature_id=str(payload.get("signature_id", "")),
        function_id=str(payload.get("function_id", "")),
        file=str(payload.get("file", "")),
        symbol=str(payload.get("symbol", "")),
        start_line=json_int(payload.get("start_line")),
        end_line=json_int(payload.get("end_line")),
        semantic_roles=tuple(json_text_list(payload, "semantic_roles")),
        semantic_role_reasons=tuple(json_text_list(payload, "semantic_role_reasons")),
    )


@lru_cache(maxsize=8192)
def action_payload(action: RefactorAction) -> Json:
    """Serialize immutable action models once per run.

    The same `RefactorAction` objects are emitted through relation, cluster, and
    target artifacts. Caching keeps the hot output path from rebuilding identical
    nested member-ref and normalization dictionaries hundreds of times.
    """
    payload: Json = {
        "kind": action.kind.value,
        "status": action.status.value,
        "confidence": action.confidence,
        "applies_to": [member_ref_payload(member) for member in action.applies_to],
    }
    if action.preconditions:
        payload["preconditions"] = list(action.preconditions)
    if action.reason_codes:
        payload["reason_codes"] = list(action.reason_codes)
    if action.normalization:
        payload["normalization"] = argument_normalization_payload(action.normalization)
    if action.extracted_region_common_prefix_length:
        payload["extracted_region"] = {
            "common_prefix_length": action.extracted_region_common_prefix_length,
        }
    if action.rejection_reasons:
        payload["rejection_reasons"] = list(action.rejection_reasons)
    return payload


def action_from_payload(data: object) -> RefactorAction:
    payload = data if isinstance(data, dict) else {}
    return RefactorAction(
        kind=_action_kind(payload.get("kind")),
        status=_action_status(payload.get("status")),
        confidence=json_float(payload.get("confidence")),
        applies_to=tuple(
            member_ref_from_payload(item)
            for item in payload.get("applies_to", [])
            if isinstance(item, dict)
        ),
        preconditions=_str_tuple(payload.get("preconditions")),
        reason_codes=_str_tuple(payload.get("reason_codes")),
        normalization=(
            argument_normalization_from_payload(payload.get("normalization"))
            if isinstance(payload.get("normalization"), dict)
            else None
        ),
        extracted_region_common_prefix_length=extracted_region_common_prefix_length(
            payload.get("extracted_region")
        ),
        rejection_reasons=_str_tuple(payload.get("rejection_reasons")),
    )


def relation_pair_payload(pair: RelationPair) -> Json:
    payload: Json = {
        "schema_version": pair.schema_version,
        "left": member_ref_payload(pair.left),
        "right": member_ref_payload(pair.right),
        "name_similarity": pair.scores.name,
        **tree_comparison_payload(pair.tree),
        **sequence_comparison_payload(pair.sequence),
        "parameter_use_similarity": pair.scores.parameter_use,
        "call_multiset_similarity": pair.scores.call_multiset,
        "graph_similarity": pair.scores.graph,
        "relatedness_score": pair.scores.relatedness,
        "refactorability_score": pair.scores.refactorability,
        "refactorability_components": refactorability_components_payload(
            pair.refactorability_components
        ),
        "abstraction_cost_score": pair.scores.abstraction_cost,
        "abstraction_cost_components": abstraction_cost_components_payload(
            pair.abstraction_cost_components
        ),
        "confidence_score": pair.scores.confidence,
        "pair_confidence": pair.scores.confidence,
        "risk_score": pair.scores.risk,
        "score_model": pair.score_model,
        "score_interpretation": pair.score_interpretation,
        "relation_kind": pair.relation_kind.value,
        "relation_basis": relation_basis_payload(pair.relation_basis),
        "relation_kinds": [kind.value for kind in pair.relation_kinds],
        "relation_candidates": [kind.value for kind in pair.relation_kinds],
        "clone_family": pair.clone_family.value,
        "clone_type": pair.clone_type.value,
        "recommended_action": pair.recommended_action.value,
        "clone_classification": clone_classification_payload(pair.clone_classification),
        "refactorability_kind": pair.refactorability_kind.value,
        "delta_kinds": [delta.value for delta in pair.delta_kinds],
        "anti_unification": sequence_skeleton_payload(pair.anti_unification),
        "refactor_action_candidates": [
            action_payload(action) for action in pair.refactor_action_candidates
        ],
        "same_role": pair.same_role,
        "role": pair.role,
        "max_body_line_count": pair.max_body_line_count,
        "min_body_line_count": pair.min_body_line_count,
        "body_hash_match": pair.flags.body_hash_match,
    }
    if pair.refactor_shape is not None:
        payload["refactor_shape"] = refactor_shape_payload(pair.refactor_shape)
    return payload


def relation_pair_from_payload(data: object) -> RelationPair:
    payload = data if isinstance(data, dict) else {}
    tree = TreeComparison(
        tree_similarity=json_float(payload.get("tree_similarity")),
        tree_distance=json_float(payload.get("tree_distance")),
        tree_edit_distance=(
            json_int(payload.get("tree_edit_distance"))
            if payload.get("tree_edit_distance") is not None
            else None
        ),
        tree_node_count=json_int(payload.get("tree_node_count")),
        tree_distance_source=str(payload.get("tree_distance_source", "")),
    )
    sequence = SequenceComparison(
        lcs_length=json_int(payload.get("lcs_length")),
        common_prefix_length=json_int(payload.get("common_prefix_length")),
        common_suffix_length=json_int(payload.get("common_suffix_length")),
        inserted_block_count=json_int(payload.get("inserted_block_count")),
        inserted_block_position=str(payload.get("inserted_block_position", "")),
        shared_argument_flow_in_tail=bool(payload.get("shared_argument_flow_in_tail")),
        sequence_similarity=json_float(payload.get("sequence_similarity")),
        left_statement_count=json_int(payload.get("left_statement_count")),
        right_statement_count=json_int(payload.get("right_statement_count")),
    )
    scores = RelationScores(
        name=json_float(payload.get("name_similarity")),
        parameter_use=json_float(payload.get("parameter_use_similarity")),
        call_multiset=json_float(payload.get("call_multiset_similarity")),
        graph=json_float(payload.get("graph_similarity")),
        relatedness=json_float(payload.get("relatedness_score")),
        refactorability=json_float(payload.get("refactorability_score")),
        abstraction_cost=json_float(payload.get("abstraction_cost_score")),
        confidence=json_float(payload.get("confidence_score")),
        risk=json_float(payload.get("risk_score")),
    )
    relation_basis = relation_basis_from_payload(payload.get("relation_basis"))
    anti_unification = sequence_skeleton_from_payload(payload.get("anti_unification"))
    return RelationPair(
        left=member_ref_from_payload(payload.get("left")),
        right=member_ref_from_payload(payload.get("right")),
        scores=scores,
        tree=tree,
        sequence=sequence,
        refactorability_components=refactorability_components_from_payload(
            payload.get("refactorability_components")
        ),
        abstraction_cost_components=abstraction_cost_components_from_payload(
            payload.get("abstraction_cost_components")
        ),
        relation_kind=_relation_kind(payload.get("relation_kind")),
        relation_basis=relation_basis,
        flags=relation_basis.flags,
        relation_kinds=_relation_kind_tuple(payload.get("relation_kinds")),
        clone_family=_clone_class(payload.get("clone_family")),
        clone_type=_clone_class(payload.get("clone_type")),
        recommended_action=_action_kind(payload.get("recommended_action")),
        clone_classification=clone_classification_from_payload(payload.get("clone_classification")),
        refactorability_kind=_score_band(payload.get("refactorability_kind")),
        delta_kinds=_delta_kind_tuple(payload.get("delta_kinds")),
        anti_unification=anti_unification,
        anti_unification_summary=sequence_skeleton_summary(anti_unification),
        refactor_action_candidates=tuple(
            action_from_payload(item)
            for item in payload.get("refactor_action_candidates", [])
            if isinstance(item, dict)
        ),
        same_role=bool(payload.get("same_role")),
        role=str(payload.get("role", "")),
        max_body_line_count=json_int(payload.get("max_body_line_count")),
        min_body_line_count=json_int(payload.get("min_body_line_count")),
        refactor_shape=None,
    )


def sequence_comparison_payload(sequence: SequenceComparison) -> Json:
    return {
        "lcs_length": sequence.lcs_length,
        "common_prefix_length": sequence.common_prefix_length,
        "common_suffix_length": sequence.common_suffix_length,
        "inserted_block_count": sequence.inserted_block_count,
        "inserted_block_position": sequence.inserted_block_position,
        "shared_argument_flow_in_tail": sequence.shared_argument_flow_in_tail,
        "sequence_similarity": sequence.sequence_similarity,
        "left_statement_count": sequence.left_statement_count,
        "right_statement_count": sequence.right_statement_count,
    }


def tree_comparison_payload(tree: TreeComparison) -> Json:
    return {
        "tree_similarity": tree.tree_similarity,
        "tree_distance": tree.tree_distance,
        "tree_edit_distance": tree.tree_edit_distance,
        "tree_node_count": tree.tree_node_count,
        "tree_distance_source": tree.tree_distance_source,
    }


def argument_normalization_payload(normalization: ArgumentNormalization) -> Json:
    if not normalization.is_detected:
        return {}
    return {
        "detected": True,
        "wrapper": normalization.wrapper,
        "primitive": normalization.primitive,
        "wrapper_parameter_type": normalization.wrapper_parameter_type,
        "primitive_parameter_type": normalization.primitive_parameter_type,
        "transform_tokens": list(normalization.transform_tokens),
        "shared_operation_tokens": list(normalization.shared_operation_tokens),
        "interpretation": normalization.interpretation,
    }


def argument_normalization_from_payload(data: object) -> ArgumentNormalization:
    payload = data if isinstance(data, dict) else {}
    return ArgumentNormalization(
        wrapper=str(payload.get("wrapper", "")),
        primitive=str(payload.get("primitive", "")),
        wrapper_parameter_type=str(payload.get("wrapper_parameter_type", "")),
        primitive_parameter_type=str(payload.get("primitive_parameter_type", "")),
        transform_tokens=_str_tuple(payload.get("transform_tokens")),
        shared_operation_tokens=_str_tuple(payload.get("shared_operation_tokens")),
        interpretation=str(payload.get("interpretation", "")),
    )


def relation_basis_payload(basis: RelationBasis) -> Json:
    return {
        "body_hash_match": basis.flags.body_hash_match,
        "same_signature_shape": basis.flags.same_signature_shape,
        "argument_normalization_wrapper": basis.argument_normalization_wrapper,
        "argument_normalization": argument_normalization_payload(basis.argument_normalization),
        "same_tree": basis.flags.same_tree,
        "literal_shapes_differ": basis.flags.literal_shapes_differ,
        "call_multiset_differs": basis.flags.call_multiset_differs,
        "same_call_multiset": basis.flags.same_call_multiset,
        "control_vector_differs": basis.flags.control_vector_differs,
        "parameter_flow_match": basis.flags.parameter_flow_match,
        "shared_prefix_length": basis.shared_prefix_length,
        "shared_suffix_length": basis.shared_suffix_length,
        "lcs_length": basis.lcs_length,
        "same_return_shape": basis.flags.same_return_shape,
        "same_error_shape": basis.flags.same_error_shape,
        "shared_argument_flow_through_tail": basis.flags.shared_argument_flow_through_tail,
    }


def relation_basis_from_payload(data: object) -> RelationBasis:
    payload = data if isinstance(data, dict) else {}
    flags = RelationFlags(
        body_hash_match=bool(payload.get("body_hash_match")),
        same_signature_shape=bool(payload.get("same_signature_shape")),
        same_tree=bool(payload.get("same_tree")),
        literal_shapes_differ=bool(payload.get("literal_shapes_differ")),
        call_multiset_differs=bool(payload.get("call_multiset_differs")),
        same_call_multiset=bool(payload.get("same_call_multiset")),
        control_vector_differs=bool(payload.get("control_vector_differs")),
        parameter_flow_match=bool(payload.get("parameter_flow_match")),
        same_return_shape=bool(payload.get("same_return_shape")),
        same_error_shape=bool(payload.get("same_error_shape")),
        shared_argument_flow_through_tail=bool(payload.get("shared_argument_flow_through_tail")),
    )
    return RelationBasis(
        flags=flags,
        argument_normalization=argument_normalization_from_payload(
            payload.get("argument_normalization")
        ),
        shared_prefix_length=json_int(payload.get("shared_prefix_length")),
        shared_suffix_length=json_int(payload.get("shared_suffix_length")),
        lcs_length=json_int(payload.get("lcs_length")),
    )


def clone_classification_payload(classification: CloneClassification) -> Json:
    return {
        "clone_type": classification.clone_type.value,
        "syntactic_strength": classification.syntactic_strength,
        "default_action": classification.default_action.value,
        "basis": list(classification.basis),
    }


def clone_classification_from_payload(data: object) -> CloneClassification:
    payload = data if isinstance(data, dict) else {}
    return CloneClassification(
        clone_type=_clone_class(payload.get("clone_type")),
        syntactic_strength=str(payload.get("syntactic_strength", "")),
        default_action=_action_kind(payload.get("default_action")),
        basis=_str_tuple(payload.get("basis")),
    )


def refactorability_components_payload(components: RefactorabilityComponents) -> Json:
    return {
        "common_region_size": components.common_region_size,
        "contiguous_common_region": components.contiguous_common_region,
        "low_hole_count": components.low_hole_count,
        "low_hole_complexity": components.low_hole_complexity,
        "same_return_shape": components.same_return_shape,
        "same_error_shape": components.same_error_shape,
        "same_source_role": components.same_source_role,
        "local_module_scope": components.local_module_scope,
        "abstraction_cost_penalty": components.abstraction_cost_penalty,
    }


def refactorability_components_from_payload(data: object) -> RefactorabilityComponents:
    payload = data if isinstance(data, dict) else {}
    return RefactorabilityComponents(
        common_region_size=json_float(payload.get("common_region_size")),
        contiguous_common_region=json_float(payload.get("contiguous_common_region")),
        low_hole_count=json_float(payload.get("low_hole_count")),
        low_hole_complexity=json_float(payload.get("low_hole_complexity")),
        same_return_shape=json_float(payload.get("same_return_shape")),
        same_error_shape=json_float(payload.get("same_error_shape")),
        same_source_role=json_float(payload.get("same_source_role")),
        local_module_scope=json_float(payload.get("local_module_scope")),
        abstraction_cost_penalty=json_float(payload.get("abstraction_cost_penalty")),
    )


def abstraction_cost_components_payload(components: AbstractionCostComponents) -> Json:
    return {
        "parameter_count_estimate": components.parameter_count_estimate,
        "hole_count": components.hole_count,
        "hole_complexity": components.hole_complexity,
        "branch_delta_count": components.branch_delta_count,
        "local_temp_delta_count": components.local_temp_delta_count,
        "callback_or_strategy_need": components.callback_or_strategy_need,
        "cross_module_dependency_cost": components.cross_module_dependency_cost,
        "public_api_cost": components.public_api_cost,
    }


def abstraction_cost_components_from_payload(data: object) -> AbstractionCostComponents:
    payload = data if isinstance(data, dict) else {}
    return AbstractionCostComponents(
        parameter_count_estimate=json_float(payload.get("parameter_count_estimate")),
        hole_count=json_float(payload.get("hole_count")),
        hole_complexity=json_float(payload.get("hole_complexity")),
        branch_delta_count=json_float(payload.get("branch_delta_count")),
        local_temp_delta_count=json_float(payload.get("local_temp_delta_count")),
        callback_or_strategy_need=json_float(payload.get("callback_or_strategy_need")),
        cross_module_dependency_cost=json_float(payload.get("cross_module_dependency_cost")),
        public_api_cost=json_float(payload.get("public_api_cost")),
    )


def sequence_skeleton_payload(skeleton: SequenceSkeleton) -> Json:
    return {
        "template": [_sequence_template_item_payload(item) for item in skeleton.template],
        "hole_bindings": {
            member: {hole: list(tokens) for hole, tokens in bindings.items()}
            for member, bindings in skeleton.hole_bindings.items()
        },
        "stable_statement_count": skeleton.stable_statement_count,
        "stable_node_ratio": skeleton.stable_node_ratio,
        "common_prefix_length": skeleton.common_prefix_length,
        "common_suffix_length": skeleton.common_suffix_length,
        "common_prefix_ratio": skeleton.common_prefix_ratio,
        "hole_count": skeleton.hole_count,
        "max_hole_size": skeleton.max_hole_size,
        "hole_size_variance": skeleton.hole_size_variance,
        "shared_param_flow_through_holes": skeleton.shared_param_flow_through_holes,
    }


def _sequence_template_item_payload(item: SequenceTemplateItem) -> Json:
    payload: Json = {"kind": item.kind}
    if item.token:
        payload["token"] = item.token
    if item.id:
        payload["id"] = item.id
    if item.role:
        payload["role"] = item.role
    if item.roles:
        payload["roles"] = list(item.roles)
    return payload


def sequence_skeleton_from_payload(data: object) -> SequenceSkeleton:
    payload = data if isinstance(data, dict) else {}
    template = tuple(
        SequenceTemplateItem(
            kind=str(item.get("kind", "")),
            token=str(item.get("token", "")),
            id=str(item.get("id", "")),
            role=str(item.get("role", "")),
            roles=_str_tuple(item.get("roles")),
        )
        for item in payload.get("template", [])
        if isinstance(item, dict)
    )
    bindings: dict[str, dict[str, tuple[str, ...]]] = {}
    raw_bindings = payload.get("hole_bindings", {})
    if isinstance(raw_bindings, dict):
        for member, holes in raw_bindings.items():
            if not isinstance(holes, dict):
                continue
            bindings[str(member)] = {
                str(hole): _str_tuple(tokens) for hole, tokens in holes.items()
            }
    return SequenceSkeleton(
        template=template,
        hole_bindings=bindings,
        stable_statement_count=json_int(payload.get("stable_statement_count")),
        stable_node_ratio=json_float(payload.get("stable_node_ratio")),
        common_prefix_length=json_int(payload.get("common_prefix_length")),
        common_suffix_length=json_int(payload.get("common_suffix_length")),
        common_prefix_ratio=json_float(payload.get("common_prefix_ratio")),
        hole_count=json_int(payload.get("hole_count")),
        max_hole_size=json_int(payload.get("max_hole_size")),
        hole_size_variance=str(payload.get("hole_size_variance", "")),
        shared_param_flow_through_holes=bool(payload.get("shared_param_flow_through_holes")),
    )


def refactor_shape_payload(shape: RefactorShape) -> Json:
    skeleton = shape.renderable_skeleton
    return {
        "schema_version": shape.schema_version,
        "shape_kind": shape.shape_kind,
        "abstraction_domain": shape.abstraction_domain,
        "skeleton_validity": shape.skeleton_validity,
        "renderable_skeleton": {
            "language": skeleton.language,
            "lines": list(skeleton.lines),
            "truncated": skeleton.truncated,
            "omitted_line_count": skeleton.omitted_line_count,
            "validity": skeleton.validity,
            "validity_note": skeleton.validity_note,
            "suppressed": skeleton.suppressed,
            "suppression_reason": skeleton.suppression_reason,
        },
        "holes": [
            {
                "id": hole.id,
                "role": hole.role,
                "type": hole.type,
                "roles": list(hole.roles),
                "size": {"min": hole.size.min, "max": hole.size.max},
                "variant_count": hole.variant_count,
                "member_bindings": {
                    member: list(tokens) for member, tokens in hole.member_bindings.items()
                },
                "parameterization": hole.parameterization,
            }
            for hole in shape.holes
        ],
        "abstraction_estimate": {
            "hole_count": shape.abstraction_estimate.hole_count,
            "statement_hole_count": shape.abstraction_estimate.statement_hole_count,
            "estimated_parameters": shape.abstraction_estimate.estimated_parameters,
            "estimated_callbacks": shape.abstraction_estimate.estimated_callbacks,
            "estimated_parameter_range": shape.abstraction_estimate.estimated_parameter_range,
            "parameterization_confidence": (shape.abstraction_estimate.parameterization_confidence),
            "variation_points": (
                list(shape.abstraction_estimate.variation_points)
                if isinstance(shape.abstraction_estimate.variation_points, tuple)
                else shape.abstraction_estimate.variation_points
            ),
            "estimate_basis": shape.abstraction_estimate.estimate_basis,
            "abstraction_cost": shape.abstraction_estimate.abstraction_cost,
        },
        "recommendation": shape.recommendation.value,
        "caveats": list(shape.caveats),
    }


def extracted_region_common_prefix_length(data: object) -> int:
    if not isinstance(data, dict):
        return 0
    return json_int(data.get("common_prefix_length"))


def context_classification_payload(classification: ContextClassification) -> Json:
    return {
        "kind": classification.kind,
        "context_tags": list(classification.context_tags),
        "visibility": classification.visibility.value,
        "summary_eligible": classification.summary_eligible,
        "action": classification.action.value,
        "refactor_value": classification.refactor_value,
        "refactor_safety": classification.refactor_safety,
        "downgrade_reasons": list(classification.downgrade_reasons),
        **({"review_tier": classification.review_tier.value} if classification.review_tier else {}),
        **(
            {"evidence_strength": classification.evidence_strength.value}
            if classification.evidence_strength
            else {}
        ),
        **(
            {"boundary_specificity": classification.boundary_specificity.value}
            if classification.boundary_specificity
            else {}
        ),
        **(
            {"corroborating_signals": list(classification.corroborating_signals)}
            if classification.corroborating_signals
            else {}
        ),
    }


def _str_tuple(value: object) -> tuple[str, ...]:
    return string_tuple(value, coerce=True)


def _action_kind(value: object) -> ActionKind:
    if isinstance(value, ActionKind):
        return value
    try:
        return ActionKind(str(value))
    except (TypeError, ValueError):
        return ActionKind.OBSERVE


def _action_status(value: object) -> ActionStatus:
    if isinstance(value, ActionStatus):
        return value
    try:
        return ActionStatus(str(value))
    except (TypeError, ValueError):
        return ActionStatus.CONDITIONAL


def _relation_kind(value: object) -> RelationKind:
    if isinstance(value, RelationKind):
        return value
    try:
        return RelationKind(str(value))
    except (TypeError, ValueError):
        return RelationKind.NONE


def _relation_kind_tuple(value: object) -> tuple[RelationKind, ...]:
    return tuple(_relation_kind(item) for item in string_tuple(value, coerce=True))


def _delta_kind(value: object) -> DeltaKind | None:
    if isinstance(value, DeltaKind):
        return value
    try:
        return DeltaKind(str(value))
    except (TypeError, ValueError):
        return None


def _delta_kind_tuple(value: object) -> tuple[DeltaKind, ...]:
    return tuple(
        delta
        for item in string_tuple(value, coerce=True)
        if (delta := _delta_kind(item)) is not None
    )


def _clone_class(value: object) -> CloneClass:
    if isinstance(value, CloneClass):
        return value
    try:
        return CloneClass(str(value))
    except (TypeError, ValueError):
        return CloneClass.SIGNATURE_SIGNAL_ONLY


def _score_band(value: object) -> ScoreBand:
    if isinstance(value, ScoreBand):
        return value
    try:
        return ScoreBand(str(value))
    except (TypeError, ValueError):
        return ScoreBand.TRACK_ONLY


__all__ = [
    "action_payload",
    "context_classification_payload",
    "member_ref_payload",
    "relation_pair_from_payload",
    "relation_pair_payload",
]
