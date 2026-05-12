from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from codeseam.analysis import Clusters, MemberRef, RelationPair
from codeseam.cache import CachedSemanticProvider, PersistentCache
from codeseam.pipeline.repository_enrichment import RepositoryEnrichment
from codeseam.pipeline.signatures import SignatureArtifacts
from codeseam.platform import ConfigError, Json
from codeseam.semantics import (
    SemanticBudget,
    SemanticCandidate,
    SemanticEnrichmentRun,
    SemanticMode,
    SemanticProject,
    SemanticProvider,
    SemanticProviderRequiredError,
    build_semantic_enrichment_requests,
    run_semantic_enrichment,
    unique_semantic_candidates,
)


@dataclass(frozen=True, slots=True)
class SemanticStageRuntime:
    provider: SemanticProvider | None = None
    budget: SemanticBudget | None = None
    cache: PersistentCache | None = None


class _HasSemanticProjects(Protocol):
    def semantic_projects(self) -> tuple[SemanticProject, ...]: ...


def run_semantic_enrichment_stage(
    *,
    repo_root: str,
    mode: SemanticMode,
    signature_artifacts: SignatureArtifacts,
    repository_enrichment: RepositoryEnrichment,
    runtime: SemanticStageRuntime | None = None,
) -> SemanticEnrichmentRun:
    if mode == SemanticMode.OFF:
        return run_semantic_enrichment((), mode=mode)
    projects = _semantic_projects(repository_enrichment)
    candidates = _semantic_candidates(signature_artifacts)
    requests = build_semantic_enrichment_requests(
        repo_root=repo_root,
        mode=mode,
        projects=projects,
        candidates=candidates,
    )
    active_provider = _cached_provider(runtime)
    try:
        return run_semantic_enrichment(
            requests,
            mode=mode,
            provider=active_provider,
            budget=runtime.budget if runtime is not None else None,
        )
    except SemanticProviderRequiredError as exc:
        raise ConfigError(str(exc)) from exc


def semantic_enrichment_stats(run: SemanticEnrichmentRun) -> Json:
    return {
        "mode": run.mode,
        "status": run.status,
        "request_count": len(run.requests),
        "item_count": sum(len(request.items) for request in run.requests),
        "result_count": len(run.results),
        "caveats": list(run.caveats),
    }


def _cached_provider(runtime: SemanticStageRuntime | None) -> SemanticProvider | None:
    if runtime is None or runtime.provider is None:
        return None
    if runtime.cache is None:
        return runtime.provider
    return CachedSemanticProvider(runtime.provider, runtime.cache)


def _semantic_projects(enrichment: RepositoryEnrichment) -> tuple[SemanticProject, ...]:
    projects: list[SemanticProject] = []
    for item in enrichment.adapter_facts:
        provider = getattr(item.facts, "semantic_projects", None)
        if callable(provider):
            projects.extend(cast(_HasSemanticProjects, item.facts).semantic_projects())
    return tuple(projects)


def _semantic_candidates(artifacts: SignatureArtifacts) -> tuple[SemanticCandidate, ...]:
    signatures = {signature.core.signature_id: signature.core for signature in artifacts.records}
    candidates: list[SemanticCandidate] = []
    for ref in _relation_member_refs(artifacts.clusters):
        core = signatures.get(ref.signature_id)
        if core is None:
            continue
        candidates.append(
            SemanticCandidate(
                signature_id=core.signature_id,
                language=core.language,
                relative_path=core.file,
                start_line=core.start_line,
                end_line=core.end_line,
                callable_kind="function",
                symbol_hint=core.symbol,
                semantic_roles=core.semantic_roles,
                has_relation_evidence=True,
                has_body_evidence=bool(core.body_shape_hash or core.body_tree_node_count),
                has_call_evidence=bool(core.call_tokens),
            )
        )
    return unique_semantic_candidates(candidates)


def _relation_member_refs(clusters: Clusters) -> tuple[MemberRef, ...]:
    refs: list[MemberRef] = []
    for cluster in clusters.clusters:
        enrichment = cluster.enrichment
        if enrichment is None:
            continue
        for pair in (
            *enrichment.structural_duplicate_pairs,
            *enrichment.structural_relation_pairs,
        ):
            refs.extend(_pair_refs(pair))
    return tuple(refs)


def _pair_refs(pair: RelationPair) -> tuple[MemberRef, MemberRef]:
    return pair.left, pair.right


__all__ = ["SemanticStageRuntime", "run_semantic_enrichment_stage", "semantic_enrichment_stats"]
