from __future__ import annotations

from codeseam.adapters.languages.base import (
    LanguageAdapter,
    LanguageAdapterAnalysis,
    LanguageAnalysisContext,
    LanguageRunCacheProtocol,
    StaticLanguageSupport,
)
from codeseam.adapters.languages.capabilities import (
    AdapterCapabilities,
    AdapterCapabilitySummary,
    RepoFactsProvider,
    RepositoryAdapterFact,
    SupportsAdapterCapabilities,
    repo_facts_provider,
)
from codeseam.adapters.languages.manifests import ManifestMatcher, matching_manifest_kind
from codeseam.adapters.languages.registry import LanguageRegistry
from codeseam.adapters.languages.relation_detail import (
    RelationDetailProvider,
    RelationDetailRequest,
    relation_detail_provider,
)
from codeseam.analysis import AdapterId


def default_language_registry() -> LanguageRegistry:
    from codeseam.adapters.languages.ecmascript.adapter import (  # noqa: PLC0415
        ECMAScriptTypeScriptTreeSitterAdapter,
    )
    from codeseam.adapters.languages.python.adapter import PythonAstAdapter  # noqa: PLC0415

    return LanguageRegistry([PythonAstAdapter(), ECMAScriptTypeScriptTreeSitterAdapter()])


__all__ = [
    "AdapterCapabilities",
    "AdapterCapabilitySummary",
    "AdapterId",
    "LanguageAdapter",
    "LanguageAdapterAnalysis",
    "LanguageAnalysisContext",
    "LanguageRunCacheProtocol",
    "LanguageRegistry",
    "ManifestMatcher",
    "RelationDetailProvider",
    "RelationDetailRequest",
    "RepositoryAdapterFact",
    "RepoFactsProvider",
    "StaticLanguageSupport",
    "SupportsAdapterCapabilities",
    "default_language_registry",
    "matching_manifest_kind",
    "relation_detail_provider",
    "repo_facts_provider",
]
