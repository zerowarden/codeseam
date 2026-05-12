from __future__ import annotations

from dataclasses import dataclass

from codeseam.analysis import (
    RepositoryFacts,
    repository_facts_cache_value,
    repository_facts_from_cache_value,
)
from codeseam.cache.main import Cache, CacheCodec
from codeseam.cache.store import PersistentCache

REPOSITORY_FACTS_CACHE_NAMESPACE = "repository_facts"


@dataclass(frozen=True, slots=True)
class _RepositoryFactsCacheCodec(CacheCodec[RepositoryFacts]):
    namespace: str = REPOSITORY_FACTS_CACHE_NAMESPACE

    def dump(self, value: RepositoryFacts) -> object:
        return repository_facts_cache_value(value)

    def load(self, value: object) -> RepositoryFacts | None:
        return repository_facts_from_cache_value(value)


_REPOSITORY_FACTS_CACHE = _RepositoryFactsCacheCodec()


def cached_repository_facts(cache: PersistentCache, key: str) -> RepositoryFacts | None:
    return Cache[RepositoryFacts](cache, _REPOSITORY_FACTS_CACHE).get(key)


def store_repository_facts(
    cache: PersistentCache,
    key: str,
    facts: RepositoryFacts,
) -> None:
    Cache[RepositoryFacts](cache, _REPOSITORY_FACTS_CACHE).set(key, facts)


__all__ = [
    "REPOSITORY_FACTS_CACHE_NAMESPACE",
    "cached_repository_facts",
    "store_repository_facts",
]
