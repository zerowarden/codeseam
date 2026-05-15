from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from codeseam.analysis import (
    ActionKind,
    AdapterId,
    ArgumentNormalization,
    CalleeShape,
    CallFingerprint,
    CloneClass,
    ExpressionShape,
    LanguageFamily,
    MemberFeatureCache,
    RelationKind,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    SignatureCore,
    SignatureTypeSource,
    argument_normalization_relation_features,
    has_argument_normalization_transform,
    shared_operation_candidate,
    signature_analysis_from_core,
)
from codeseam.analysis.relations.clones import (
    clone_basis_for,
    clone_classification_for,
    default_action,
)
from codeseam.analysis.relations.models import CloneClassificationInput
from codeseam.analysis.relations.policy import (
    PAIR_POLICY,
    RELATION_ASSESSMENT_POLICY,
    STRUCTURAL_POLICY,
)


def test_argument_normalization_detects_wrapper_before_shared_operation() -> None:
    wrapper = _member(
        "parse_encoded",
        parameter="bytes",
        calls=("decode(args=CONST_utf8;kwargs=)", "loads(args=ARG0;kwargs=)"),
        call_fingerprints=(
            _call("decode(args=CONST_utf8;kwargs=)", callee="decode"),
            _call("loads(args=ARG0;kwargs=)", callee="loads", arg_roles=["ARG0"]),
        ),
    )
    primitive = _member(
        "parse_text",
        parameter="str",
        calls=("loads(args=ARG0;kwargs=)",),
        call_fingerprints=(_call("loads(args=ARG0;kwargs=)", callee="loads", arg_roles=["ARG0"]),),
    )
    cache = MemberFeatureCache([wrapper, primitive])

    relation = argument_normalization_relation_features(
        cache.get(wrapper),
        cache.get(primitive),
    )

    assert relation.wrapper.endswith("parse_encoded")
    assert relation.primitive.endswith("parse_text")
    assert relation.transform_tokens == ("decode(args=CONST_utf8;kwargs=)",)
    assert relation.shared_operation_tokens == ("loads(args=ARG0;kwargs=)",)


def test_argument_normalization_helpers_expose_transform_and_shared_operation() -> None:
    wrapper = _member(
        "load_encoded",
        parameter="bytes",
        calls=("decode(args=CONST_utf8;kwargs=)", "parse(args=ARG0;kwargs=)"),
        call_fingerprints=(
            _call("decode(args=CONST_utf8;kwargs=)", callee="decode"),
            _call("parse(args=ARG0;kwargs=)", callee="parse", arg_roles=["ARG0"]),
        ),
    )
    primitive = _member(
        "load_text",
        parameter="str",
        calls=("parse(args=ARG0;kwargs=)",),
        call_fingerprints=(_call("parse(args=ARG0;kwargs=)", callee="parse", arg_roles=["ARG0"]),),
    )

    assert has_argument_normalization_transform(wrapper) is True
    assert has_argument_normalization_transform(primitive) is False
    assert shared_operation_candidate(wrapper, primitive) is True


def test_clone_default_action_applies_high_cost_before_edit_action() -> None:
    assert (
        default_action(
            RelationKind.BODY_IDENTICAL,
            CloneClass.TYPE_1_EXACT,
            RELATION_ASSESSMENT_POLICY.refactorability_high_threshold,
            RELATION_ASSESSMENT_POLICY.high_abstraction_cost_threshold,
        )
        is ActionKind.RECORD_SHARED_CONCERN
    )


def test_unmapped_clone_relation_fails_closed() -> None:
    classification = clone_classification_for(
        _clone_context(relation_kind=cast(RelationKind, "future_relation_kind"))
    )

    assert classification.clone_type is CloneClass.SIGNATURE_SIGNAL_ONLY
    assert classification.syntactic_strength == "unclassified_relation"
    assert classification.default_action is ActionKind.OBSERVE


def test_clone_basis_preserves_priority_and_thresholds_weak_evidence() -> None:
    basis = clone_basis_for(
        _clone_context(
            same_signature_shape=True,
            body_hash_match=True,
            name=STRUCTURAL_POLICY.name_similarity_threshold,
            tree_similarity=STRUCTURAL_POLICY.tree_similarity_threshold,
            tree_distance_source="ordered_tree_edit_distance",
            parameter_similarity=PAIR_POLICY.parameter_flow_threshold,
            call_similarity=PAIR_POLICY.call_fingerprint_threshold - 0.01,
            lcs_length=STRUCTURAL_POLICY.min_statement_lcs_length - 1,
            stable_statement_count=STRUCTURAL_POLICY.min_stable_statement_count - 1,
        )
    )

    assert basis == (
        "same_signature_shape",
        "normalized_body_identity",
        "normalized_name_similarity",
        "body_tree_similarity",
        "parameter_use_similarity",
    )


def _member(
    symbol: str,
    *,
    parameter: str,
    calls: tuple[str, ...],
    call_fingerprints: tuple[CallFingerprint, ...],
) -> SignatureAnalysis:
    core = SignatureCore(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.UNKNOWN,
        file=f"src/{symbol}.py",
        symbol=symbol,
        normalized_symbol=symbol,
        container=None,
        start_line=1,
        end_line=2,
        role="function",
        type_source=SignatureTypeSource.FALLBACK,
        parameters=(parameter,),
        return_type="dict",
        canonical_shape="fn(T)->dict",
        shape_hash=f"shape:{symbol}",
        body_line_count=1,
        body_shape_hash=f"body:{symbol}",
        body_tree_node_count=1,
        statement_sequence=("RETURN:ARG0",),
        call_tokens=calls,
        return_signature=("RETURN:ARG0",),
        signature_id=f"sig:{symbol}",
        function_id=f"fn:{symbol}",
    )
    return signature_analysis_from_core(
        core,
        features=SignatureAnalysisFeatures(
            signature_id=core.signature_id,
            call_fingerprints=call_fingerprints,
        ),
    )


def _clone_context(**overrides: object) -> CloneClassificationInput:
    return cast(
        CloneClassificationInput,
        SimpleNamespace(
            relation_kind=overrides.get("relation_kind", RelationKind.NONE),
            scores=SimpleNamespace(name=overrides.get("name", 0.0)),
            flags=SimpleNamespace(
                same_signature_shape=overrides.get("same_signature_shape", False),
                body_hash_match=overrides.get("body_hash_match", False),
            ),
            tree_similarity=overrides.get("tree_similarity", 0.0),
            tree_distance_source=overrides.get("tree_distance_source", ""),
            parameter_similarity=overrides.get("parameter_similarity", 0.0),
            call_similarity=overrides.get("call_similarity", 0.0),
            sequence=SimpleNamespace(lcs_length=overrides.get("lcs_length", 0)),
            anti_unification=SimpleNamespace(
                stable_statement_count=overrides.get("stable_statement_count", 0)
            ),
            deltas=(),
            refactorability=overrides.get("refactorability", 0.0),
            abstraction_cost=overrides.get("abstraction_cost", 0.0),
            argument_normalization=overrides.get("argument_normalization", ArgumentNormalization()),
        ),
    )


def _call(token: str, *, callee: str, arg_roles: list[str] | None = None) -> CallFingerprint:
    return CallFingerprint(
        kind="call",
        token=token,
        receiver_shape=ExpressionShape(base="ARG0"),
        callee_shape=CalleeShape(name_tokens=(callee,)),
        arg_roles=tuple(arg_roles or ["CONST_utf8"]),
    )
