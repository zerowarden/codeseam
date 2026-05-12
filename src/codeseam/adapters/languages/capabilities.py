from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from codeseam.analysis import AdapterId, RepositoryFacts


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Optional facts and enrichments a language adapter can provide.

    Capabilities describe adapter evidence sources, not actionability. A
    Tree-sitter adapter can provide syntax facts without compiler semantics;
    a native or compiler-backed adapter can advertise richer facts later
    without teaching the generic pipeline about a specific language.
    """

    syntax_frontend: str = "unknown"
    relation_detail: bool = False
    policy_constants: bool = False
    repo_facts: bool = False
    compiler_semantics: bool = False


@dataclass(frozen=True, slots=True)
class AdapterCapabilitySummary:
    language: str
    adapter_id: AdapterId
    capabilities: AdapterCapabilities


@dataclass(frozen=True, slots=True)
class RepositoryAdapterFact:
    language: str
    adapter_id: AdapterId
    facts: object


class RepoFactsProvider(Protocol):
    def extract_repo_facts(self, facts: RepositoryFacts) -> object: ...


class SupportsAdapterCapabilities(Protocol):
    capabilities: AdapterCapabilities


def repo_facts_provider(adapter: SupportsAdapterCapabilities | None) -> RepoFactsProvider | None:
    if adapter is None or not adapter.capabilities.repo_facts:
        return None
    return cast(RepoFactsProvider, adapter)


__all__ = [
    "AdapterCapabilities",
    "AdapterCapabilitySummary",
    "RepositoryAdapterFact",
    "RepoFactsProvider",
    "SupportsAdapterCapabilities",
    "repo_facts_provider",
]
