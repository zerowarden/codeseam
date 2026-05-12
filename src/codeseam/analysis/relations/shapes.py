from __future__ import annotations

from codeseam.analysis.relations.models import (
    AbstractionEstimate,
    ActionKind,
    CloneClass,
    DeltaKind,
    HoleSize,
    MemberFeatures,
    RefactorHole,
    RefactorShape,
    RefactorShapeInput,
    RelationKind,
    RenderableSkeleton,
)
from codeseam.analysis.relations.unification import SequenceSkeleton

MIN_RENDERABLE_STABLE_RATIO = 0.2
MAX_INLINE_SKELETON_LINES = 12
MAX_PARAMETERIZED_HOLE_SIZE = 2
LOW_ABSTRACTION_COST_LIMIT = 0.25
MEDIUM_ABSTRACTION_COST_LIMIT = 0.6
BLOCK_DELTA_ROLES = {"branch_delta", "error_delta", "return_delta"}
EXPRESSION_DELTA_ROLES = {"literal_delta", "receiver_delta"}
HOLE_FUNCTION_NAME = "H_FUNCTION"
SKELETON_VALIDITY = "illustrative_only"
SKELETON_NOTE = "This skeleton is a structural abstraction, not executable pseudocode."
DELTA_VARIATION_POINTS = {
    DeltaKind.ARGUMENT_NORMALIZATION: "argument_normalization",
    DeltaKind.ARGUMENT_FLOW: "argument_flow",
    DeltaKind.CALLEE_NAME: "callee_name",
    DeltaKind.CONTROL_FLOW: "control_flow",
    DeltaKind.DEFAULT_ARGUMENT: "default_argument",
    DeltaKind.ERROR_HANDLING: "error_handling",
    DeltaKind.EXTRA_ASSIGNMENT: "assignment",
    DeltaKind.EXTRA_CONTEXT_MANAGER: "context_manager",
    DeltaKind.EXTRA_LOCAL_TEMPORARY: "local_temporary",
    DeltaKind.EXTRA_TERMINAL_CALL: "terminal_call",
    DeltaKind.LITERAL_VALUE: "literal_value",
    DeltaKind.LOOP: "loop",
    DeltaKind.RECEIVER_SHAPE: "receiver_shape",
    DeltaKind.RETURN_VALUE: "return_value",
}


def refactor_shape_from_features(
    left: MemberFeatures,
    right: MemberFeatures,
    *,
    shape_input: RefactorShapeInput,
) -> RefactorShape:
    holes = hole_records(left, right, shape_input.anti_unification)
    skeleton = renderable_skeleton(
        left,
        right,
        shape_input=shape_input,
        holes=holes,
    )
    recommendation = shape_recommendation(
        shape_input.relation_kind,
        shape_input.clone_type,
        shape_input.default_action,
        skeleton,
    )
    estimate = abstraction_estimate(
        holes,
        shape_input.abstraction_cost,
        delta_kinds=shape_input.delta_kinds,
        recommendation=recommendation,
    )
    return RefactorShape(
        shape_kind="statement_sequence_anti_unification_skeleton",
        abstraction_domain="normalized_statement_sequence",
        skeleton_validity=SKELETON_VALIDITY,
        renderable_skeleton=skeleton,
        holes=tuple(holes),
        abstraction_estimate=estimate,
        recommendation=recommendation,
        caveats=tuple(shape_caveats(skeleton, holes, shape_input.delta_kinds, recommendation)),
    )


def renderable_skeleton(
    left: MemberFeatures,
    right: MemberFeatures,
    *,
    shape_input: RefactorShapeInput,
    holes: list[RefactorHole],
) -> RenderableSkeleton:
    language = _language(left, right)
    suppression_reason = _suppression_reason(
        shape_input.anti_unification,
        relation_kind=shape_input.relation_kind,
        clone_type=shape_input.clone_type,
        language=language,
    )
    if suppression_reason:
        return RenderableSkeleton(
            language=language,
            lines=(),
            truncated=False,
            omitted_line_count=0,
            validity=SKELETON_VALIDITY,
            validity_note=SKELETON_NOTE,
            suppressed=True,
            suppression_reason=suppression_reason,
        )
    return_type = left.member.return_type or "unknown"
    lines = [_signature_line(left)]
    lines.extend(_template_lines(shape_input.anti_unification, holes, return_type=return_type))
    omitted = max(0, len(lines) - MAX_INLINE_SKELETON_LINES)
    return RenderableSkeleton(
        language=language,
        lines=tuple(lines[:MAX_INLINE_SKELETON_LINES]),
        truncated=omitted > 0,
        omitted_line_count=omitted,
        validity=SKELETON_VALIDITY,
        validity_note=SKELETON_NOTE,
        suppressed=False,
        suppression_reason="",
    )


def hole_records(
    left: MemberFeatures,
    right: MemberFeatures,
    anti_unification: SequenceSkeleton,
) -> list[RefactorHole]:
    bindings = anti_unification.hole_bindings
    left_key = left.member.binding_key
    right_key = right.member.binding_key
    left_bindings = _hole_binding(bindings, left_key)
    right_bindings = _hole_binding(bindings, right_key)
    holes = [item for item in anti_unification.template if item.kind == "HOLE"]
    records = []
    for index, hole in enumerate(holes):
        hole_id = hole.id or f"H{index}"
        variants = {
            left_key: tuple(left_bindings.get(hole_id, ())),
            right_key: tuple(right_bindings.get(hole_id, ())),
        }
        sizes = [len(value) for value in variants.values()]
        roles = _roles(hole)
        hole_type, parameterization = _hole_variation(roles, sizes)
        records.append(
            RefactorHole(
                id=hole_id,
                role=hole.role or "statement_sequence_delta",
                type=hole_type,
                roles=tuple(roles),
                size=HoleSize(min=min(sizes, default=0), max=max(sizes, default=0)),
                variant_count=len(set(variants.values())),
                member_bindings=variants,
                parameterization=parameterization,
            )
        )
    return records


def abstraction_estimate(
    holes: list[RefactorHole],
    abstraction_cost: float,
    *,
    delta_kinds: tuple[DeltaKind, ...],
    recommendation: ActionKind,
) -> AbstractionEstimate:
    estimated_parameters = sum(1 for hole in holes if hole.parameterization == "parameter")
    estimated_callbacks = sum(
        1 for hole in holes if hole.parameterization == "callback_or_strategy"
    )
    variation_points: tuple[str, ...] | str = tuple(_variation_points(delta_kinds))
    estimate_basis = "rendered_holes" if holes else "none"
    parameterization_confidence = "medium" if estimated_parameters or estimated_callbacks else "low"
    parameter_value: int | str = estimated_parameters
    if not holes and variation_points and recommendation != ActionKind.OBSERVE:
        estimate_basis = "relation_deltas"
        parameter_value = "unknown"
    elif not holes and recommendation == ActionKind.INTRODUCE_ABSTRACTION:
        estimate_basis = "relation_kind_only"
        parameter_value = "unknown"
        variation_points = "unavailable"
    return AbstractionEstimate(
        hole_count=len(holes),
        statement_hole_count=sum(1 for hole in holes if hole.type == "statement_block"),
        estimated_parameters=parameter_value,
        estimated_callbacks=estimated_callbacks,
        estimated_parameter_range="1-2" if estimate_basis == "relation_deltas" else "",
        parameterization_confidence=parameterization_confidence,
        variation_points=variation_points,
        estimate_basis=estimate_basis,
        abstraction_cost=_cost_label(abstraction_cost),
    )


def shape_caveats(
    skeleton: RenderableSkeleton,
    holes: list[RefactorHole],
    delta_kinds: tuple[DeltaKind, ...],
    recommendation: ActionKind,
) -> list[str]:
    caveats = [SKELETON_NOTE]
    if _template_has_return(skeleton):
        caveats.append("Return-expression tokens list dependencies, not returned values.")
    if not holes and delta_kinds:
        caveats.append("Variation points were inferred from relation deltas, not rendered holes.")
    if not holes and not delta_kinds and recommendation == ActionKind.INTRODUCE_ABSTRACTION:
        caveats.append("Abstraction need was inferred from relation kind only.")
    caveats.append(
        "The skeleton omits scope, side effects, exceptions, mutability, "
        "ownership, and call-site readability."
    )
    return caveats


def shape_recommendation(
    relation_kind: RelationKind,
    clone_type: CloneClass,
    default_action: ActionKind,
    skeleton: RenderableSkeleton,
) -> ActionKind:
    if skeleton.suppressed:
        return ActionKind.OBSERVE
    if clone_type == CloneClass.SIGNATURE_SIGNAL_ONLY or relation_kind == RelationKind.NONE:
        return ActionKind.OBSERVE
    if clone_type == CloneClass.CONTRACT_ANALOGY:
        return ActionKind.RECORD_SHARED_CONCERN
    return default_action


def _suppression_reason(
    anti_unification: SequenceSkeleton,
    *,
    relation_kind: RelationKind,
    clone_type: CloneClass,
    language: str,
) -> str:
    if language == "multiple":
        return "mixed_language"
    if relation_kind == RelationKind.NONE or clone_type == CloneClass.SIGNATURE_SIGNAL_ONLY:
        return "signature_only"
    if clone_type == CloneClass.CONTRACT_ANALOGY:
        return "contract_analogy"
    if anti_unification.stable_statement_count <= 0:
        return "no_stable_skeleton"
    if anti_unification.stable_node_ratio < MIN_RENDERABLE_STABLE_RATIO:
        return "mostly_holes"
    return ""


def _signature_line(member: MemberFeatures) -> str:
    params = ", ".join(f"arg{index}: {param}" for index, param in enumerate(_parameters(member)))
    return_type = member.member.return_type or "unknown"
    return f"function <{HOLE_FUNCTION_NAME}>({params}) -> {return_type}"


def _parameters(member: MemberFeatures) -> list[str]:
    return list(member.member.parameters)


def _template_lines(
    anti_unification: SequenceSkeleton,
    holes: list[RefactorHole],
    *,
    return_type: str,
) -> list[str]:
    holes_by_id = {hole.id: hole for hole in holes}
    lines = []
    for item in anti_unification.template:
        if item.kind == "STABLE_STATEMENT":
            lines.append("  " + _render_statement_token(item.token, return_type=return_type))
        elif item.kind == "HOLE":
            hole_id = item.id or "H0"
            role = holes_by_id[hole_id].role if hole_id in holes_by_id else item.role or "hole"
            lines.append(f"  HOLE {hole_id}: {role}")
    return lines or ["  <empty structural body>"]


def _render_statement_token(token: str, *, return_type: str) -> str:
    if token.startswith("CALL:"):
        return f"CALL {token.removeprefix('CALL:')}"
    if token.startswith("RETURN:"):
        return _return_dependency_token(token.removeprefix("RETURN:"), return_type)
    if token.startswith("ASSIGN:"):
        return f"ASSIGN {token.removeprefix('ASSIGN:')}"
    if token.startswith("WITH:"):
        return f"WITH {token.removeprefix('WITH:')}"
    return f"STMT {token}"


def _return_dependency_token(value: str, return_type: str) -> str:
    uses = [item.strip() for item in value.split(",") if item.strip()]
    if not uses:
        return f"RETURN_EXPR declared_type={return_type} uses=[]"
    return f"RETURN_EXPR declared_type={return_type} uses=[{', '.join(uses)}]"


def _hole_binding(
    bindings: dict[str, dict[str, tuple[str, ...]]],
    key: str,
) -> dict[str, tuple[str, ...]]:
    return bindings.get(key, {})


def _variation_points(delta_kinds: tuple[DeltaKind, ...]) -> list[str]:
    return sorted({DELTA_VARIATION_POINTS[delta] for delta in delta_kinds})


def _template_has_return(skeleton: RenderableSkeleton) -> bool:
    return any(line.strip().startswith("RETURN") for line in skeleton.lines)


def _roles(hole: object) -> list[str]:
    roles = getattr(hole, "roles", ())
    if roles:
        return list(roles)
    return [str(getattr(hole, "role", "statement_sequence_delta"))]


def _hole_variation(roles: list[str], sizes: list[int]) -> tuple[str, str]:
    role_set = set(roles)
    max_size = max(sizes, default=0)
    is_block = bool(role_set & BLOCK_DELTA_ROLES)
    is_expression = bool(role_set & EXPRESSION_DELTA_ROLES)
    is_call = "call_delta" in role_set

    if is_block or max_size > 1:
        hole_type = "statement_block"
    elif is_expression:
        hole_type = "expression"
    elif is_call:
        hole_type = "call"
    else:
        hole_type = "statement"

    if is_block or max_size > MAX_PARAMETERIZED_HOLE_SIZE:
        parameterization = "local_helper_or_keep_separate"
    elif is_call:
        parameterization = "callback_or_strategy"
    elif is_expression:
        parameterization = "parameter"
    else:
        parameterization = "none"

    return hole_type, parameterization


def _cost_label(value: float) -> str:
    if value < LOW_ABSTRACTION_COST_LIMIT:
        return "low"
    if value < MEDIUM_ABSTRACTION_COST_LIMIT:
        return "medium"
    return "high"


def _language(left: MemberFeatures, right: MemberFeatures) -> str:
    languages = {_member_language(left), _member_language(right)}
    return languages.pop() if len(languages) == 1 else "multiple"


def _member_language(member: MemberFeatures) -> str:
    language = member.member.language.lower()
    if language:
        return language
    file_path = member.member.file
    return "python" if file_path.endswith(".py") else "unknown"
