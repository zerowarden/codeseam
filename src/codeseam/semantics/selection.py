from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from codeseam.semantics.enrichment import (
    SemanticEnrichmentItem,
    SemanticEnrichmentRequest,
    SemanticMode,
)

AMBIGUOUS_SEMANTIC_ROLES = frozenset(
    {
        "adapter_forwarder",
        "command_or_registry_surface",
        "declaration_boundary",
        "framework_hook",
        "framework_render_surface",
        "overload_signature",
        "public_api_mirror",
        "sync_async_mirror",
    }
)
DEFAULT_MAX_ITEMS_PER_REQUEST = 200


@dataclass(frozen=True, slots=True)
class SemanticProject:
    """A project context that can answer semantic questions for languages."""

    project_id: str
    language: str
    languages: tuple[str, ...]
    project_cache_key: str
    config_path: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    """A relation-level candidate selected after cheap structural analysis."""

    signature_id: str
    language: str
    relative_path: str
    start_line: int
    end_line: int
    callable_kind: str
    symbol_hint: str = ""
    semantic_roles: tuple[str, ...] = ()
    has_relation_evidence: bool = False
    has_body_evidence: bool = False
    has_call_evidence: bool = False


def build_semantic_enrichment_requests(
    *,
    repo_root: str,
    mode: SemanticMode,
    projects: tuple[SemanticProject, ...],
    candidates: tuple[SemanticCandidate, ...],
    max_items_per_request: int = DEFAULT_MAX_ITEMS_PER_REQUEST,
) -> tuple[SemanticEnrichmentRequest, ...]:
    """Group selected candidates into bounded project-level requests.

    This function assumes relation/candidate generation already happened. It
    deliberately accepts candidates instead of files, so semantic provider cost
    scales with potentially useful relation evidence rather than repository
    size.
    """

    if mode == SemanticMode.OFF or not projects or not candidates:
        return ()
    requests: list[SemanticEnrichmentRequest] = []
    for project in sorted(projects, key=lambda item: (item.config_path, item.project_id)):
        items = tuple(
            _request_item(candidate)
            for candidate in _project_candidates(project, candidates)
            if _worth_semantic_enrichment(candidate)
        )[: max(0, max_items_per_request)]
        if not items:
            continue
        requests.append(
            SemanticEnrichmentRequest(
                request_id=_request_id(project),
                language=project.language,
                mode=mode,
                repo_root=repo_root,
                project_cache_key=project.project_cache_key,
                config_path=project.config_path,
                items=items,
            )
        )
    return tuple(requests)


def _project_candidates(
    project: SemanticProject,
    candidates: tuple[SemanticCandidate, ...],
) -> tuple[SemanticCandidate, ...]:
    project_paths = set(project.paths)
    language_set = {language.casefold() for language in project.languages}
    return tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.language.casefold() in language_set
                and (not project_paths or candidate.relative_path in project_paths)
            ),
            key=lambda item: (item.relative_path, item.start_line, item.signature_id),
        )
    )


def _worth_semantic_enrichment(candidate: SemanticCandidate) -> bool:
    roles = set(candidate.semantic_roles)
    return (
        bool(roles & AMBIGUOUS_SEMANTIC_ROLES)
        or candidate.has_relation_evidence
        or candidate.has_body_evidence
        or candidate.has_call_evidence
    )


def _request_item(candidate: SemanticCandidate) -> SemanticEnrichmentItem:
    return SemanticEnrichmentItem(
        signature_id=candidate.signature_id,
        relative_path=candidate.relative_path,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        callable_kind=candidate.callable_kind,
        symbol_hint=candidate.symbol_hint,
    )


def _request_id(project: SemanticProject) -> str:
    return "::".join(("semantic", project.language, project.project_cache_key, project.config_path))


def unique_semantic_candidates(
    candidates: Iterable[SemanticCandidate],
) -> tuple[SemanticCandidate, ...]:
    deduped: dict[str, SemanticCandidate] = {}
    for candidate in candidates:
        deduped.setdefault(candidate.signature_id, candidate)
    return tuple(deduped.values())


__all__ = [
    "DEFAULT_MAX_ITEMS_PER_REQUEST",
    "SemanticCandidate",
    "SemanticProject",
    "build_semantic_enrichment_requests",
    "unique_semantic_candidates",
]
