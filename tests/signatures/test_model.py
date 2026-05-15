from __future__ import annotations

from typing import Any, cast

from codeseam.analysis import (
    AdapterId,
    CalleeShape,
    CallFingerprint,
    DataflowGraph,
    DataflowNode,
    ExpressionShape,
    LanguageFamily,
    SignatureBodySummary,
    SignatureCore,
    SignatureIdentity,
    SignatureRecord,
    SignatureShape,
    SignatureTypeSource,
    member_features,
    signature_analysis_from_record,
)

from .factories import signature, signature_record


def test_member_features_use_typed_signature_core() -> None:
    item = signature("sig_none", "python", "src/a.py", "", "fn()->T", "shape")

    assert member_features(item).body_hash == ""

def test_signature_record_coerces_boundary_enums() -> None:
    record = SignatureRecord(
        schema_version="codeseam.signature.v1",
        signature_id="sig_1",
        function_id=None,
        language="Python",
        language_family=cast(Any, "python"),
        adapter=cast(Any, "python_ast"),
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=1,
        role="source",
        type_source=cast(Any, "declared_syntax"),
        parameters=[],
        return_type="UNKNOWN",
        raw_signature="",
        canonical_shape="fn()->UNKNOWN",
        shape_hash="shape",
        body_line_count=1,
        body_shape="",
        body_shape_hash="",
        body_tree=None,
        body_tree_node_count=0,
    )

    assert record.language_family is LanguageFamily.PYTHON
    assert record.adapter is AdapterId.PYTHON_AST
    assert record.type_source is SignatureTypeSource.DECLARED_SYNTAX


def test_signature_core_exposes_typed_lifecycle_views() -> None:
    core = SignatureCore(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.PYTHON_AST,
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=2,
        role="source",
        type_source=SignatureTypeSource.DECLARED_SYNTAX,
        parameters=("str",),
        return_type="str",
        canonical_shape="fn(str)->str",
        shape_hash="shape",
        body_line_count=1,
        body_shape_hash="body",
        body_tree_node_count=2,
        statement_sequence=("RETURN:ARG0",),
        call_tokens=("str.strip",),
        return_signature=("RETURN:ARG0",),
        signature_id="sig_1",
        function_id="fn_1",
        semantic_roles=("api_surface",),
    )

    assert core.identity == SignatureIdentity(
        language="python",
        language_family=LanguageFamily.PYTHON,
        adapter=AdapterId.PYTHON_AST,
        file="src/a.py",
        symbol="fn",
        normalized_symbol="fn",
        container=None,
        start_line=1,
        end_line=2,
        role="source",
        signature_id="sig_1",
        function_id="fn_1",
    )
    assert core.shape == SignatureShape(
        type_source=SignatureTypeSource.DECLARED_SYNTAX,
        parameters=("str",),
        return_type="str",
        canonical_shape="fn(str)->str",
        shape_hash="shape",
    )
    assert core.body == SignatureBodySummary(
        body_line_count=1,
        body_shape_hash="body",
        body_tree_node_count=2,
        statement_sequence=("RETURN:ARG0",),
        call_tokens=("str.strip",),
        return_signature=("RETURN:ARG0",),
    )
    assert core.semantic_roles == ("api_surface",)


def test_signature_analysis_from_record_accepts_constant_kwargs() -> None:
    record = signature_record("sig_1", "python", "src/a.py", "decode_arg", "fn()->T", "h")
    token = "ARG0.decode(args=;kwargs=encoding:CONST_utf8)"
    record.call_fingerprints = (
        CallFingerprint(
            kind="CALL",
            token=token,
            callee_shape=CalleeShape(name_tokens=("decode",), call_kind="method"),
            receiver_shape=ExpressionShape(base="ARG0"),
            kwarg_shape=(("encoding", "CONST_utf8"),),
        ),
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.normalization_transform_tokens == frozenset((token,))


def test_signature_analysis_from_record_rejects_non_constant_transform_args() -> None:
    record = signature_record("sig_1", "python", "src/a.py", "decode_arg", "fn()->T", "h")
    record.call_fingerprints = (
        CallFingerprint(
            kind="CALL",
            token="ARG0.decode(args=ARG1;kwargs=)",
            callee_shape=CalleeShape(name_tokens=("decode",), call_kind="method"),
            receiver_shape=ExpressionShape(base="ARG0"),
            arg_roles=("ARG1",),
        ),
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.normalization_transform_tokens == frozenset()


def test_statement_arg_reads_ignore_malformed_statement_ids() -> None:
    record = signature_record("sig_1", "python", "src/a.py", "read_arg", "fn()->T", "h")
    record.local_dataflow_graph = DataflowGraph(
        nodes=(
            DataflowNode(id="STMTx", label="bad", kind="statement", arg_reads=("ARG0",)),
            DataflowNode(id="STMT2", label="good", kind="statement", arg_reads=("ARG1",)),
        )
    )

    analysis = signature_analysis_from_record(record)

    assert analysis.features.statement_arg_reads == ((2, ("ARG1",)),)
