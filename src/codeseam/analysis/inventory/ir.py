from __future__ import annotations

from dataclasses import dataclass, field

from codeseam.analysis.signatures import (
    AdapterId,
    IntraFunctionDuplicateBlock,
    LanguageFamily,
    SignatureTypeSource,
    adapter_id,
    canonical_shape,
    language_family,
)
from codeseam.analysis.signatures.model import OperationFeatures, empty_operation_features

UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParamIR:
    annotation: str | None
    name: str | None = None
    has_default: bool = False


@dataclass(frozen=True)
class FunctionIR:
    language: str
    language_family: LanguageFamily
    file: str
    name: str
    container: str | None
    kind: str
    start_line: int
    end_line: int
    is_async: bool
    is_exported_or_public: bool
    params: tuple[ParamIR, ...]
    return_annotation: str | None
    declared_generics: tuple[str, ...]
    raw_signature: str
    source_text: str
    body_text: str
    body_line_count: int
    branch_count: int
    loop_count: int
    return_count: int
    max_nesting: int
    adapter: AdapterId
    extraction_confidence: str
    caveats: tuple[str, ...]
    features: OperationFeatures = field(default_factory=empty_operation_features)
    syntax_kind: str = ""
    semantic_roles: tuple[str, ...] = ()
    semantic_role_reasons: tuple[str, ...] = ()
    intra_function_duplicate_blocks: tuple[IntraFunctionDuplicateBlock, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "language_family", language_family(self.language_family))
        object.__setattr__(self, "adapter", adapter_id(self.adapter))

    @property
    def has_body(self) -> bool:
        return bool(self.body_text)


@dataclass(frozen=True)
class SignatureShape:
    parameters: list[str]
    return_type: str
    canonical_shape: str
    shape_hash: str
    type_source: SignatureTypeSource
    caveats: list[str]


def signature_shape(function: FunctionIR) -> SignatureShape:
    params = [param.annotation or UNKNOWN for param in function.params]
    return_type = function.return_annotation or UNKNOWN
    shape, shape_hash = canonical_shape(params, return_type, list(function.declared_generics))
    missing_types = UNKNOWN in [*params, return_type]
    caveats = ["missing_type_annotation"] if missing_types else []
    return SignatureShape(
        parameters=params,
        return_type=return_type,
        canonical_shape=shape,
        shape_hash=shape_hash,
        type_source=(
            SignatureTypeSource.FALLBACK if missing_types else SignatureTypeSource.DECLARED_SYNTAX
        ),
        caveats=caveats,
    )


__all__ = ["FunctionIR", "ParamIR", "SignatureShape", "signature_shape"]
