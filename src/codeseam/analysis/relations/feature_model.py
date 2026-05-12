from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

from codeseam.analysis.relations.member_model import (
    MemberInput,
    MemberRef,
    RelationMember,
    member_ref,
)
from codeseam.analysis.signatures import (
    CallFingerprint,
    DataflowGraph,
    OrderedTree,
    ParameterUseVector,
)

type ErrorShape = tuple[tuple[str, ...], int, int]


@dataclass(frozen=True)
class MemberFeatures:
    key: tuple[str, ...]
    member: RelationMember
    body_hash: str
    body_shape: str
    body_tree_payload: OrderedTree | None
    tree_node_count: int
    normalized_name: str
    role: str
    statements: tuple[str, ...]
    statement_fingerprint: int
    calls: tuple[str, ...]
    call_set: frozenset[str]
    call_fingerprints: tuple[CallFingerprint, ...]
    call_counts: Counter[str]
    parameter_default_roles: dict[str, str]
    parameter_vectors: dict[str, ParameterUseVector]
    local_dataflow_graph: DataflowGraph
    graph_features: frozenset[str]
    literal_shapes: frozenset[str]
    receiver_shapes: frozenset[str]
    parameter_features: dict[str, frozenset[str]]
    normalization_transform_tokens: frozenset[str]
    statement_arg_reads: tuple[tuple[int, tuple[str, ...]], ...]
    control_vector: tuple[str, ...]
    control_set: frozenset[str]
    return_signature: tuple[str, ...]
    error_shape: ErrorShape
    body_line_count: int

    @cached_property
    def body_tree(self) -> OrderedTree | None:
        return self.body_tree_payload

    @cached_property
    def ref(self) -> MemberRef:
        return member_ref(self.member)


class MemberFeatureCache:
    def __init__(self, members: Sequence[MemberInput] = ()) -> None:
        self._features: dict[tuple[str, ...], MemberFeatures] = {}
        for member in members:
            self.get(member)

    def get(self, member: MemberInput) -> MemberFeatures:
        from codeseam.analysis.relations.features import (  # noqa: PLC0415
            _cache_key,
            member_features,
        )

        key = _cache_key(member)
        if key not in self._features:
            self._features[key] = member_features(member, key=key)
        return self._features[key]

    def entries(self, members: Sequence[MemberInput]) -> list[tuple[MemberInput, MemberFeatures]]:
        from codeseam.analysis.relations.features import (  # noqa: PLC0415
            _cache_key,
            member_features,
        )

        entries = []
        for member in members:
            key = _cache_key(member)
            if key not in self._features:
                self._features[key] = member_features(member, key=key)
            entries.append((member, self._features[key]))
        return entries


__all__ = ["ErrorShape", "MemberFeatureCache", "MemberFeatures", "MemberInput"]
