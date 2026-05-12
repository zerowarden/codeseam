from __future__ import annotations

from codeseam.adapters.languages import AdapterCapabilitySummary
from codeseam.analysis import RepositoryFacts
from codeseam.pipeline.repository_enrichment import RepositoryEnrichment
from codeseam.platform import Json, text_list


def adapter_capabilities_payload(enrichment: RepositoryEnrichment) -> list[Json]:
    return [_capability_summary_payload(summary) for summary in enrichment.adapter_capabilities]


def target_adapter_capabilities_payload(
    target: Json,
    facts: RepositoryFacts,
    enrichment: RepositoryEnrichment,
) -> list[Json]:
    languages = _target_languages(target, facts)
    return [
        _capability_summary_payload(summary)
        for summary in enrichment.adapter_capabilities
        if summary.language in languages
    ]


def _target_languages(target: Json, facts: RepositoryFacts) -> set[str]:
    languages: set[str] = set()
    for path in text_list(target.get("files")):
        if path in facts.languages_by_path:
            languages.add(facts.languages_by_path[path])
    return languages


def _capability_summary_payload(summary: AdapterCapabilitySummary) -> Json:
    capabilities = summary.capabilities
    return {
        "language": summary.language,
        "adapter_id": summary.adapter_id.value,
        "syntax_frontend": capabilities.syntax_frontend,
        "relation_detail": capabilities.relation_detail,
        "policy_constants": capabilities.policy_constants,
        "repo_facts": capabilities.repo_facts,
        "compiler_semantics": capabilities.compiler_semantics,
    }


__all__ = ["adapter_capabilities_payload", "target_adapter_capabilities_payload"]
