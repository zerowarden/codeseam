from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from codeseam.analysis.relations.feature_model import (
    ErrorShape,
    MemberFeatureCache,
    MemberFeatures,
    MemberInput,
)
from codeseam.analysis.relations.member_model import (
    RelationMember,
)
from codeseam.analysis.signatures import (
    DataflowGraph,
    SignatureAnalysis,
    SignatureCore,
)


def member_features(member: MemberInput, *, key: tuple[str, ...] | None = None) -> MemberFeatures:
    return _signature_features(member, key=key)


def _signature_features(
    signature: SignatureAnalysis | SignatureCore,
    *,
    key: tuple[str, ...] | None = None,
) -> MemberFeatures:
    core = signature.core if isinstance(signature, SignatureAnalysis) else signature
    analysis_features = signature.features if isinstance(signature, SignatureAnalysis) else None
    output = signature.output if isinstance(signature, SignatureAnalysis) else None
    relation_member = RelationMember.from_signature(signature)
    statements = tuple(core.statement_sequence)
    calls = core.call_tokens
    return MemberFeatures(
        key=key or _cache_key(signature),
        member=relation_member,
        body_hash=relation_member.body_shape_hash,
        body_shape=relation_member.body_shape,
        body_tree_payload=None,
        tree_node_count=core.body_tree_node_count or 0,
        normalized_name=core.normalized_symbol or core.symbol,
        role=core.role,
        statements=statements,
        statement_fingerprint=hash(statements),
        calls=calls,
        call_set=frozenset(calls),
        call_fingerprints=analysis_features.call_fingerprints if analysis_features else (),
        call_counts=Counter(calls),
        parameter_default_roles=dict(analysis_features.parameter_default_roles)
        if analysis_features
        else {},
        parameter_vectors={},
        local_dataflow_graph=DataflowGraph(),
        graph_features=analysis_features.graph_features if analysis_features else frozenset(),
        literal_shapes=analysis_features.literal_shapes if analysis_features else frozenset(),
        receiver_shapes=analysis_features.receiver_shapes if analysis_features else frozenset(),
        parameter_features=dict(analysis_features.parameter_features) if analysis_features else {},
        normalization_transform_tokens=(
            analysis_features.normalization_transform_tokens if analysis_features else frozenset()
        ),
        statement_arg_reads=analysis_features.statement_arg_reads if analysis_features else (),
        control_vector=tuple(core.control_context_vector),
        control_set=frozenset(core.control_context_vector),
        return_signature=core.return_signature,
        error_shape=_error_shape(
            output.caveats if output else (),
            core.try_statement_count,
            core.raise_statement_count,
        ),
        body_line_count=core.body_line_count,
    )


def _cache_key(member: MemberInput) -> tuple[str, ...]:
    if isinstance(member, SignatureCore):
        return (
            member.file,
            str(member.start_line),
            member.symbol,
            member.signature_id,
            member.function_id or "",
            "core",
            str(id(member)),
        )
    if isinstance(member, SignatureAnalysis):
        core = member.core
        return (
            core.file,
            str(core.start_line),
            core.symbol,
            core.signature_id,
            core.function_id or "",
            "analysis",
            str(id(member)),
        )
    raise TypeError(f"unsupported relation member input: {type(member).__name__}")


def _error_shape(
    caveats: Sequence[str],
    controls: Sequence[str] | int,
    statements: Sequence[str] | int,
) -> ErrorShape:
    try_count = controls if isinstance(controls, int) else controls.count("TRY")
    raise_count = (
        statements
        if isinstance(statements, int)
        else sum(item.startswith("RAISE") for item in statements)
    )
    return (
        tuple(caveats),
        try_count,
        raise_count,
    )


__all__ = ["ErrorShape", "MemberFeatureCache", "MemberFeatures", "MemberInput", "member_features"]
