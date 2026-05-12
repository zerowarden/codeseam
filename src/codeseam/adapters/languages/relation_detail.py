from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from codeseam.adapters.languages.base import LanguageAnalysisContext
from codeseam.adapters.languages.capabilities import SupportsAdapterCapabilities
from codeseam.analysis import FunctionRecord, SignatureAnalysis, SignatureAnalysisFeatures


@dataclass(frozen=True, slots=True)
class RelationDetailRequest:
    """Selected signature anchor for adapter-owned relation enrichment.

    The generic pipeline chooses which signatures need richer relation facts.
    The adapter owns how those facts are hydrated: a native adapter can reuse a
    run-local AST, a Tree-sitter adapter can reuse source/function handles, and
    compiler-backed adapters can batch requests to a semantic worker.
    """

    context: LanguageAnalysisContext
    signature: SignatureAnalysis
    function: FunctionRecord | None = None


class RelationDetailProvider(Protocol):
    def hydrate_relation_detail(
        self,
        request: RelationDetailRequest,
    ) -> SignatureAnalysisFeatures: ...


def relation_detail_provider(
    adapter: SupportsAdapterCapabilities | None,
) -> RelationDetailProvider | None:
    if adapter is None or not adapter.capabilities.relation_detail:
        return None
    return cast(RelationDetailProvider, adapter)


__all__ = [
    "RelationDetailProvider",
    "RelationDetailRequest",
    "relation_detail_provider",
]
