from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from codeseam.analysis.signatures import (
    CallsitePattern,
    OrderedTree,
    SignatureAnalysis,
    SignatureCore,
)
from codeseam.platform import is_public_identifier, parent_path

type MemberInput = SignatureAnalysis | SignatureCore


@dataclass(frozen=True, slots=True)
class RelationMemberContext:
    signature_id: str
    function_id: str | None
    file: str
    symbol: str
    start_line: int
    language: str
    return_type: str
    parameters: tuple[str, ...]
    callsite_patterns: tuple[CallsitePattern, ...] = ()
    caveats: tuple[str, ...] = ()
    role: str = ""


@dataclass(frozen=True)
class MemberRef:
    signature_id: str
    function_id: str
    file: str
    symbol: str
    start_line: int
    end_line: int
    semantic_roles: tuple[str, ...] = ()
    semantic_role_reasons: tuple[str, ...] = ()


def member_ref(source: SignatureAnalysis | SignatureCore | RelationMember) -> MemberRef:
    if isinstance(source, SignatureAnalysis):
        source = source.core
    return MemberRef(
        signature_id=source.signature_id,
        function_id=source.function_id or "",
        file=source.file,
        symbol=source.symbol,
        start_line=source.start_line,
        end_line=source.end_line,
        semantic_roles=tuple(getattr(source, "semantic_roles", ())),
        semantic_role_reasons=tuple(getattr(source, "semantic_role_reasons", ())),
    )


@dataclass(frozen=True)
class RelationMember:
    language: str
    signature_id: str
    function_id: str
    file: str
    symbol: str
    normalized_symbol: str
    start_line: int
    end_line: int
    role: str
    shape_hash: str
    body_shape_hash: str
    body_shape: str
    body_tree: OrderedTree | None
    body_tree_node_count: int
    statement_sequence: tuple[str, ...]
    control_context_vector: tuple[str, ...]
    parameters: tuple[str, ...]
    return_type: str
    caveats: tuple[str, ...]
    digest: str
    semantic_roles: tuple[str, ...] = ()
    semantic_role_reasons: tuple[str, ...] = ()
    parameter_count: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_count", len(self.parameters))

    @classmethod
    def from_signature(cls, signature: SignatureAnalysis | SignatureCore) -> RelationMember:
        core = signature.core if isinstance(signature, SignatureAnalysis) else signature
        output = signature.output if isinstance(signature, SignatureAnalysis) else None
        caveats = output.caveats if output is not None else ()
        return cls(
            language=core.language,
            signature_id=core.signature_id,
            function_id=core.function_id or "",
            file=core.file,
            symbol=core.symbol,
            normalized_symbol=core.normalized_symbol,
            start_line=core.start_line,
            end_line=core.end_line,
            role=core.role,
            shape_hash=core.shape_hash,
            body_shape_hash=core.body_shape_hash,
            body_shape=output.body_shape if output is not None else "",
            body_tree=None,
            body_tree_node_count=core.body_tree_node_count,
            statement_sequence=tuple(core.statement_sequence),
            control_context_vector=tuple(core.control_context_vector),
            parameters=tuple(core.parameters),
            return_type=core.return_type,
            caveats=tuple(caveats),
            semantic_roles=tuple(getattr(core, "semantic_roles", ())),
            semantic_role_reasons=tuple(getattr(core, "semantic_role_reasons", ())),
            digest=member_digest_from_parts(
                (
                    core.language,
                    core.signature_id,
                    core.function_id or "",
                    core.file,
                    core.symbol,
                    core.normalized_symbol,
                    str(core.start_line),
                    str(core.end_line),
                    core.role,
                    core.shape_hash,
                    core.body_shape_hash,
                    str(core.body_tree_node_count),
                    *core.statement_sequence,
                    *core.control_context_vector,
                    *core.parameters,
                    core.return_type,
                    *caveats,
                    *core.semantic_roles,
                    *core.semantic_role_reasons,
                )
            ),
        )

    @property
    def binding_key(self) -> str:
        return "::".join(
            value
            for value in (
                self.file,
                self.symbol,
                str(self.start_line) if self.start_line else "",
                self.function_id,
            )
            if value
        )

    @property
    def first_parameter(self) -> str:
        return self.parameters[0] if self.parameters else ""

    @property
    def module_scope(self) -> str:
        return parent_path(self.file)

    @property
    def is_public_symbol(self) -> bool:
        return is_public_identifier(self.symbol)


def member_digest_from_parts(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8", errors="surrogatepass")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(b";")
    return "sha256:" + digest.hexdigest()


__all__ = [
    "MemberInput",
    "MemberRef",
    "RelationMember",
    "RelationMemberContext",
    "member_digest_from_parts",
    "member_ref",
]
