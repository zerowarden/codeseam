from __future__ import annotations

from codeseam.analysis import (
    AdapterId,
    CalleeShape,
    CallFingerprint,
    ExpressionShape,
    LanguageFamily,
    MemberFeatureCache,
    SignatureAnalysis,
    SignatureAnalysisFeatures,
    SignatureCore,
    SignatureTypeSource,
    argument_normalization_relation_features,
    has_argument_normalization_transform,
    shared_operation_candidate,
    signature_analysis_from_core,
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
        type_source=SignatureTypeSource.INFERRED,
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


def _call(token: str, *, callee: str, arg_roles: list[str] | None = None) -> CallFingerprint:
    return CallFingerprint(
        kind="call",
        token=token,
        receiver_shape=ExpressionShape(base="ARG0"),
        callee_shape=CalleeShape(name_tokens=(callee,)),
        arg_roles=tuple(arg_roles or ["CONST_utf8"]),
    )
