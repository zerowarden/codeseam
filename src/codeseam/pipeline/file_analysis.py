from __future__ import annotations

from dataclasses import dataclass, replace

from codeseam.adapters.languages import LanguageRegistry, default_language_registry
from codeseam.adapters.languages.extraction import (
    FileAnalysisResult,
    analyze_language_file,
    language_context,
)
from codeseam.analysis import PolicyConstant, RepositoryFacts
from codeseam.cache import (
    AnalysisCacheContext,
    CacheWriteBuffer,
    FileSignatureCacheRequest,
    LanguageRunCache,
    PrefetchedSignatures,
    prefetch_cached_signatures,
)
from codeseam.config import Config


@dataclass(slots=True)
class RepositoryFileAnalysis:
    by_path: dict[str, FileAnalysisResult]
    policy_constants: tuple[PolicyConstant, ...]


def analyze_selected_files(
    config: Config,
    facts: RepositoryFacts,
    caches: AnalysisCacheContext | None,
) -> RepositoryFileAnalysis:
    registry = default_language_registry()
    active_caches = replace(caches, write_buffer=CacheWriteBuffer()) if caches is not None else None
    run_cache = active_caches.language if active_caches else None
    prefetched_signatures = (
        _prefetch_signatures(config, facts, registry, active_caches, run_cache)
        if active_caches is not None
        else {}
    )
    by_path: dict[str, FileAnalysisResult] = {}
    policy_constants: list[PolicyConstant] = []
    for relative_path in facts.selected_paths:
        file_record = facts.records_by_path[relative_path]
        context = language_context(config.repo_root, relative_path, file_record, run_cache)
        result = analyze_language_file(
            context,
            file_record,
            registry,
            active_caches,
            prefetched_signatures=prefetched_signatures.get(relative_path),
        )
        by_path[relative_path] = result
        policy_constants.extend(result.policy_constants)
    if active_caches is not None:
        active_caches.flush()
    return RepositoryFileAnalysis(
        by_path=by_path,
        policy_constants=tuple(policy_constants),
    )


def _prefetch_signatures(
    config: Config,
    facts: RepositoryFacts,
    registry: LanguageRegistry,
    caches: AnalysisCacheContext,
    run_cache: LanguageRunCache | None,
) -> dict[str, PrefetchedSignatures]:
    requests: list[FileSignatureCacheRequest] = []
    for relative_path in facts.selected_paths:
        file_record = facts.records_by_path[relative_path]
        adapter = registry.adapter_for_language(file_record.language)
        if adapter is None:
            continue
        requests.append(
            FileSignatureCacheRequest(
                context=language_context(config.repo_root, relative_path, file_record, run_cache),
                file_record=file_record,
                adapter_id=adapter.adapter_id.value,
            )
        )
    return prefetch_cached_signatures(requests, caches)


__all__ = ["RepositoryFileAnalysis", "analyze_selected_files"]
