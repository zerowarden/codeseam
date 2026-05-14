from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from codeseam.analysis.signatures.metadata import (
    AdapterId,
    LanguageFamily,
    adapter_id,
    language_family,
)
from codeseam.analysis.signatures.tree import OrderedTree
from codeseam.analysis.signatures.types import SignatureTypeSource

NORMALIZATION_TRANSFORM_METHODS = frozenset({"decode", "encode"})
_STMT_ID_RE = re.compile(r"^STMT(?P<index>\d+)$")


class NormalizationLevel(StrEnum):
    SIGNATURE = "signature"
    CONTROL = "control"
    CALL = "call"
    LITERAL_POLICY = "literal_policy"


@dataclass(frozen=True, slots=True)
class ExpressionShape:
    base: str
    access_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CalleeShape:
    namespace_tokens: tuple[str, ...] = ()
    name_tokens: tuple[str, ...] = ()
    ## TODO: This should be some enum
    call_kind: str = "unknown"


@dataclass(frozen=True, slots=True)
class CallFingerprint:
    kind: str
    token: str
    callee_shape: CalleeShape
    receiver_shape: ExpressionShape | None = None
    arg_roles: tuple[str, ...] = ()
    kwarg_shape: tuple[tuple[str, str], ...] = ()
    reads: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterUseVector:
    access_paths: tuple[str, ...] = ()
    receiver_of_calls: tuple[str, ...] = ()
    passed_as_argument_to: tuple[str, ...] = ()
    returned: bool = False


@dataclass(frozen=True, slots=True)
class DataflowNode:
    id: str
    label: str
    kind: str
    arg_reads: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DataflowEdge:
    from_id: str
    to_id: str
    kind: str
    from_label: str = ""
    to_label: str = ""


@dataclass(frozen=True, slots=True)
class DataflowGraph:
    nodes: tuple[DataflowNode, ...] = ()
    edges: tuple[DataflowEdge, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationCompact:
    statement_sequence: tuple[str, ...] = ()
    call_tokens: tuple[str, ...] = ()
    parameter_default_roles: tuple[tuple[str, str], ...] = ()
    normalization_transform_tokens: tuple[str, ...] = ()
    graph_features: frozenset[str] = frozenset()
    literal_shapes: frozenset[str] = frozenset()
    receiver_shapes: frozenset[str] = frozenset()
    parameter_features: tuple[tuple[str, frozenset[str]], ...] = ()
    statement_arg_reads: tuple[tuple[int, tuple[str, ...]], ...] = ()
    control_context_vector: tuple[str, ...] = ()
    body_shape: str = ""
    body_shape_hash: str = ""
    body_tree_node_count: int = 0
    branch_count: int = 0
    loop_count: int = 0
    return_count: int = 0
    max_nesting: int = 0


@dataclass(frozen=True, slots=True)
class OperationFlow:
    call_fingerprints: tuple[CallFingerprint, ...] = ()
    parameter_use_vectors: tuple[tuple[str, ParameterUseVector], ...] = ()
    parameter_default_roles: tuple[tuple[str, str], ...] = ()
    local_dataflow_graph: DataflowGraph = field(default_factory=DataflowGraph)


@dataclass(frozen=True, slots=True)
class OperationFeatures:
    compact: OperationCompact = field(default_factory=OperationCompact)
    flow: OperationFlow = field(default_factory=OperationFlow)


def empty_operation_features() -> OperationFeatures:
    return OperationFeatures()


@dataclass(frozen=True, slots=True)
class CallsitePattern:
    kind: str
    symbol: str
    file: str
    line: int
    variable: str = ""


@dataclass(frozen=True, slots=True)
class DuplicateBlockOccurrence:
    start_line: int
    end_line: int
    source: str = ""


@dataclass(frozen=True, slots=True)
class IntraFunctionDuplicateBlock:
    """Exact repeated block evidence within one function body.

    Language adapters own the syntax-specific collection. The shared model only
    records compact line ranges and a stable fingerprint so assessment can treat
    the repeated block as local clone evidence without comparing every subtree.
    """

    fingerprint: str
    kind: str
    statement_count: int
    line_count: int
    occurrences: tuple[DuplicateBlockOccurrence, ...]


@dataclass(frozen=True, slots=True)
class PolicyConstant:
    language: str
    file: str
    symbol: str
    normalized_symbol: str
    start_line: int
    end_line: int
    role: str
    literal_kind: str
    literal_shape_hash: str
    literal_preview: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_line", _line_number(self.start_line, default=1))
        object.__setattr__(self, "end_line", _line_number(self.end_line, default=self.start_line))


@dataclass(slots=True)
class SignatureRecord:
    language: str
    language_family: LanguageFamily
    adapter: AdapterId
    file: str
    symbol: str
    normalized_symbol: str
    container: str | None
    start_line: int
    end_line: int
    role: str
    type_source: SignatureTypeSource
    parameters: list[str]
    return_type: str
    raw_signature: str
    canonical_shape: str
    shape_hash: str
    body_line_count: int
    body_shape: str
    body_shape_hash: str
    body_tree: OrderedTree | None
    body_tree_node_count: int
    statement_sequence: list[str] = field(default_factory=list)
    call_tokens: tuple[str, ...] = ()
    call_fingerprints: tuple[CallFingerprint, ...] = ()
    parameter_use_vectors: dict[str, ParameterUseVector] = field(default_factory=dict)
    parameter_default_roles: dict[str, str] = field(default_factory=dict)
    local_dataflow_graph: DataflowGraph = field(default_factory=DataflowGraph)
    graph_features: frozenset[str] = field(default_factory=frozenset)
    literal_shapes: frozenset[str] = field(default_factory=frozenset)
    receiver_shapes: frozenset[str] = field(default_factory=frozenset)
    parameter_features: dict[str, frozenset[str]] = field(default_factory=dict)
    normalization_transform_tokens: tuple[str, ...] = ()
    statement_arg_reads: tuple[tuple[int, tuple[str, ...]], ...] = ()
    control_context_vector: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    non_claims: list[str] = field(
        default_factory=lambda: ["Same signature shape does not imply same behavior."],
    )
    schema_version: str = "codeseam.signature.v1"
    signature_id: str = ""
    function_id: str | None = None
    is_callable_factory: bool = False
    evidence_kinds: list[str] = field(default_factory=list)
    callsite_patterns: tuple[CallsitePattern, ...] = ()
    semantic_roles: tuple[str, ...] = ()
    semantic_role_reasons: tuple[str, ...] = ()
    intra_function_duplicate_blocks: tuple[IntraFunctionDuplicateBlock, ...] = ()

    def __post_init__(self) -> None:
        self.language_family = language_family(self.language_family)
        self.adapter = adapter_id(self.adapter)
        self.type_source = _signature_type_source(self.type_source)


@dataclass(frozen=True, slots=True)
class SignatureCore:
    language: str
    language_family: LanguageFamily
    adapter: AdapterId
    file: str
    symbol: str
    normalized_symbol: str
    container: str | None
    start_line: int
    end_line: int
    role: str
    type_source: SignatureTypeSource
    parameters: tuple[str, ...]
    return_type: str
    canonical_shape: str
    shape_hash: str
    body_line_count: int
    body_shape_hash: str
    body_tree_node_count: int
    statement_sequence: tuple[str, ...] = ()
    call_tokens: tuple[str, ...] = ()
    control_context_vector: tuple[str, ...] = ()
    return_signature: tuple[str, ...] = ()
    try_statement_count: int = 0
    raise_statement_count: int = 0
    signature_id: str = ""
    function_id: str | None = None
    semantic_roles: tuple[str, ...] = ()
    semantic_role_reasons: tuple[str, ...] = ()
    intra_function_duplicate_blocks: tuple[IntraFunctionDuplicateBlock, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "language_family", language_family(self.language_family))
        object.__setattr__(self, "adapter", adapter_id(self.adapter))
        object.__setattr__(self, "type_source", _signature_type_source(self.type_source))


@dataclass(frozen=True, slots=True)
class SignatureAnalysisFeatures:
    signature_id: str
    parameter_default_roles: tuple[tuple[str, str], ...] = ()
    graph_features: frozenset[str] = field(default_factory=frozenset)
    literal_shapes: frozenset[str] = field(default_factory=frozenset)
    receiver_shapes: frozenset[str] = field(default_factory=frozenset)
    parameter_features: tuple[tuple[str, frozenset[str]], ...] = ()
    normalization_transform_tokens: frozenset[str] = field(default_factory=frozenset)
    statement_arg_reads: tuple[tuple[int, tuple[str, ...]], ...] = ()
    call_fingerprints: tuple[CallFingerprint, ...] = ()


@dataclass(frozen=True, slots=True)
class SignatureOutputDetail:
    signature_id: str
    raw_signature: str = ""
    body_shape: str = ""
    caveats: tuple[str, ...] = ()
    non_claims: tuple[str, ...] = ("Same signature shape does not imply same behavior.",)
    is_callable_factory: bool = False
    evidence_kinds: tuple[str, ...] = ()
    callsite_patterns: tuple[CallsitePattern, ...] = ()
    schema_version: str = "codeseam.signature.v1"


@dataclass(slots=True)
class SignatureAnalysis:
    core: SignatureCore
    features: SignatureAnalysisFeatures
    output: SignatureOutputDetail


def signature_analysis_key(signature: SignatureAnalysis) -> str:
    """Return the stable key used to match compact and hydrated analysis records."""

    core = signature.core
    return core.signature_id or "|".join((core.file, str(core.start_line), core.symbol))


def signature_analysis_from_core(
    core: SignatureCore,
    *,
    features: SignatureAnalysisFeatures | None = None,
    output: SignatureOutputDetail | None = None,
) -> SignatureAnalysis:
    return SignatureAnalysis(
        core=core,
        features=features or SignatureAnalysisFeatures(signature_id=core.signature_id),
        output=output or SignatureOutputDetail(signature_id=core.signature_id),
    )


def signature_core_from_record(record: SignatureRecord) -> SignatureCore:
    statements = tuple(record.statement_sequence)
    calls = record.call_fingerprints
    return _core_from_record(record, statements, calls)


def signature_analysis_from_record(record: SignatureRecord) -> SignatureAnalysis:
    statements = tuple(record.statement_sequence)
    calls = record.call_fingerprints
    return SignatureAnalysis(
        core=_core_from_record(record, statements, calls),
        features=_features_from_record(record, calls),
        output=_output_from_record(record),
    )


def operation_features_from_record(record: SignatureRecord) -> OperationFeatures:
    return OperationFeatures(
        compact=OperationCompact(
            statement_sequence=tuple(record.statement_sequence),
            call_tokens=tuple(record.call_tokens),
            parameter_default_roles=tuple(sorted(record.parameter_default_roles.items())),
            normalization_transform_tokens=tuple(record.normalization_transform_tokens),
            graph_features=record.graph_features,
            literal_shapes=record.literal_shapes,
            receiver_shapes=record.receiver_shapes,
            parameter_features=tuple(sorted(record.parameter_features.items())),
            statement_arg_reads=tuple(record.statement_arg_reads),
            control_context_vector=tuple(record.control_context_vector),
            body_shape=record.body_shape,
            body_shape_hash=record.body_shape_hash,
            body_tree_node_count=record.body_tree_node_count,
        ),
        flow=OperationFlow(
            call_fingerprints=record.call_fingerprints,
            parameter_use_vectors=tuple(sorted(record.parameter_use_vectors.items())),
            parameter_default_roles=tuple(sorted(record.parameter_default_roles.items())),
            local_dataflow_graph=record.local_dataflow_graph,
        ),
    )


def _core_from_record(
    record: SignatureRecord,
    statements: tuple[str, ...],
    calls: tuple[CallFingerprint, ...],
) -> SignatureCore:
    call_tokens = tuple(record.call_tokens) or tuple(call.token for call in calls if call.token)
    controls = tuple(record.control_context_vector)
    return SignatureCore(
        language=record.language,
        language_family=record.language_family,
        adapter=record.adapter,
        file=record.file,
        symbol=record.symbol,
        normalized_symbol=record.normalized_symbol,
        container=record.container,
        start_line=record.start_line,
        end_line=record.end_line,
        role=record.role,
        type_source=record.type_source,
        parameters=tuple(record.parameters),
        return_type=record.return_type,
        canonical_shape=record.canonical_shape,
        shape_hash=record.shape_hash,
        body_line_count=record.body_line_count,
        body_shape_hash=record.body_shape_hash,
        body_tree_node_count=record.body_tree_node_count,
        statement_sequence=statements,
        call_tokens=call_tokens,
        control_context_vector=controls,
        return_signature=tuple(item for item in statements if item.startswith("RETURN:")),
        try_statement_count=controls.count("TRY"),
        raise_statement_count=sum(item.startswith("RAISE") for item in statements),
        signature_id=record.signature_id,
        function_id=record.function_id,
        semantic_roles=tuple(record.semantic_roles),
        semantic_role_reasons=tuple(record.semantic_role_reasons),
        intra_function_duplicate_blocks=tuple(record.intra_function_duplicate_blocks),
    )


def _features_from_record(
    record: SignatureRecord,
    calls: tuple[CallFingerprint, ...],
) -> SignatureAnalysisFeatures:
    parameter_features = {
        role: frozenset(_parameter_vector_features(vector))
        for role, vector in record.parameter_use_vectors.items()
    }
    return SignatureAnalysisFeatures(
        signature_id=record.signature_id,
        call_fingerprints=calls,
        parameter_default_roles=tuple(sorted(record.parameter_default_roles.items())),
        graph_features=record.graph_features
        or frozenset(_graph_features(record.local_dataflow_graph)),
        literal_shapes=record.literal_shapes
        or frozenset(_literal_shapes(record.parameter_default_roles, calls)),
        receiver_shapes=record.receiver_shapes or frozenset(_receiver_shapes(calls)),
        parameter_features=tuple(sorted((record.parameter_features or parameter_features).items())),
        normalization_transform_tokens=frozenset(record.normalization_transform_tokens)
        or frozenset(_normalization_transform_tokens(calls)),
        statement_arg_reads=record.statement_arg_reads
        or tuple(_statement_arg_reads(record.local_dataflow_graph)),
    )


def _output_from_record(record: SignatureRecord) -> SignatureOutputDetail:
    return SignatureOutputDetail(
        signature_id=record.signature_id,
        raw_signature=record.raw_signature,
        body_shape=record.body_shape,
        caveats=tuple(record.caveats),
        non_claims=tuple(record.non_claims),
        is_callable_factory=record.is_callable_factory,
        evidence_kinds=tuple(record.evidence_kinds),
        callsite_patterns=record.callsite_patterns,
        schema_version=record.schema_version,
    )


def _signature_type_source(value: object) -> SignatureTypeSource:
    if isinstance(value, SignatureTypeSource):
        return value
    if not isinstance(value, str):
        return SignatureTypeSource.UNKNOWN
    try:
        return SignatureTypeSource(value)
    except ValueError:
        return SignatureTypeSource.UNKNOWN


def _line_number(value: object, *, default: int) -> int:
    if not isinstance(value, int | str):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _graph_features(graph: DataflowGraph) -> set[str]:
    features = {f"node:{node.kind}:{node.label}" for node in graph.nodes}
    features.update(
        f"edge:{edge.kind}:{edge.from_id}:{edge.from_label}->{edge.to_id}:{edge.to_label}"
        for edge in graph.edges
    )
    return features


def _literal_shapes(
    default_roles: dict[str, str],
    calls: tuple[CallFingerprint, ...],
) -> set[str]:
    shapes = {value for value in default_roles.values() if value.startswith("CONST_")}
    for call in calls:
        shapes.update(value for value in call.arg_roles if value.startswith("CONST_"))
        shapes.update(
            value for value in call_kwarg_shape_values(call) if value.startswith("CONST_")
        )
    return shapes


def _receiver_shapes(calls: tuple[CallFingerprint, ...]) -> set[str]:
    shapes: set[str] = set()
    for call in calls:
        receiver = call.receiver_shape
        if receiver is None:
            continue
        access = ".".join(receiver.access_path)
        if shape := f"{receiver.base}.{access}".rstrip("."):
            shapes.add(shape)
    return shapes


def _parameter_vector_features(vector: ParameterUseVector) -> set[str]:
    features: set[str] = set()
    features.update(f"access_paths:{item}" for item in vector.access_paths)
    features.update(f"receiver_of_calls:{item}" for item in vector.receiver_of_calls)
    features.update(f"passed_as_argument_to:{item}" for item in vector.passed_as_argument_to)
    features.add(f"returned:{vector.returned}")
    return features


def _normalization_transform_tokens(calls: tuple[CallFingerprint, ...]) -> set[str]:
    tokens: set[str] = set()
    for call in calls:
        receiver = call.receiver_shape
        if receiver is None or receiver.base != "ARG0" or receiver.access_path:
            continue
        if not _all_constant_roles(call.arg_roles):
            continue
        if not _all_constant_roles(call_kwarg_shape_values(call)):
            continue
        callee = "_".join(item for item in call.callee_shape.name_tokens if item)
        if callee in NORMALIZATION_TRANSFORM_METHODS and call.token:
            tokens.add(call.token)
    return tokens


def call_kwarg_shape_values(call: CallFingerprint) -> tuple[str, ...]:
    return tuple(value for _, value in call.kwarg_shape)


def _constant_roles(values: Iterable[object]) -> set[str]:
    return {item for item in values if isinstance(item, str) and item.startswith("CONST_")}


def _all_constant_roles(values: Iterable[object]) -> bool:
    values = tuple(values)
    return all(isinstance(item, str) and item.startswith("CONST_") for item in values)


def _statement_arg_reads(graph: DataflowGraph) -> list[tuple[int, tuple[str, ...]]]:
    reads: list[tuple[int, tuple[str, ...]]] = []
    for node in graph.nodes:
        if node.kind != "statement" or not node.id.startswith("STMT") or not node.arg_reads:
            continue
        match = _STMT_ID_RE.match(node.id)
        if match is not None:
            reads.append((int(match.group("index")), node.arg_reads))
    return reads


__all__ = [
    "NORMALIZATION_TRANSFORM_METHODS",
    "CallFingerprint",
    "CalleeShape",
    "CallsitePattern",
    "call_kwarg_shape_values",
    "DataflowEdge",
    "DataflowGraph",
    "DataflowNode",
    "ExpressionShape",
    "DuplicateBlockOccurrence",
    "IntraFunctionDuplicateBlock",
    "NormalizationLevel",
    "OperationCompact",
    "OperationFeatures",
    "OperationFlow",
    "ParameterUseVector",
    "PolicyConstant",
    "SignatureAnalysis",
    "SignatureAnalysisFeatures",
    "SignatureCore",
    "SignatureOutputDetail",
    "SignatureRecord",
    "empty_operation_features",
    "operation_features_from_record",
    "signature_analysis_key",
    "signature_analysis_from_core",
    "signature_analysis_from_record",
    "signature_core_from_record",
]
