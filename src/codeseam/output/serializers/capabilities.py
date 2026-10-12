from __future__ import annotations

from collections.abc import Sequence

from codeseam.adapters.languages import AdapterCapabilitySummary
from codeseam.analysis import Finding, RepositoryFacts
from codeseam.platform import Json


def adapter_capabilities_payload(summaries: Sequence[AdapterCapabilitySummary]) -> list[Json]:
    return [_capability_summary_payload(summary) for summary in summaries]


def target_adapter_capabilities_payload(
    target: Finding,
    facts: RepositoryFacts,
    summaries: Sequence[AdapterCapabilitySummary],
) -> list[Json]:
    languages = {
        facts.languages_by_path[path] for path in target.files if path in facts.languages_by_path
    }
    return [
        _capability_summary_payload(summary)
        for summary in summaries
        if summary.language in languages
    ]


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
