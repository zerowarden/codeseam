from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codeseam.analysis import AssessmentPolicy, Finding, RepositoryFacts, build_findings
from codeseam.config import Config
from codeseam.output.reports.documents import (
    build_metrics,
    build_report,
    render_agent_summary,
    render_readme,
)
from codeseam.output.serializers.capabilities import (
    adapter_capabilities_payload,
    target_adapter_capabilities_payload,
)
from codeseam.output.serializers.finding_buckets import (
    canonical_analysis_targets,
    partition_analysis_targets,
)
from codeseam.output.serializers.findings import agent_review_target_payload, review_targets_payload
from codeseam.pipeline.repository_enrichment import RepositoryEnrichment
from codeseam.platform import (
    Json,
    OutputPaths,
    as_json_object,
    as_json_objects,
    json_int,
    write_atomic,
    write_jsonable_atomic,
    write_jsonl_jsonable_atomic,
)
from codeseam.semantics import SemanticEnrichmentRun

if TYPE_CHECKING:
    from codeseam.pipeline.signatures import SignatureArtifacts


@dataclass(frozen=True)
class ReportArtifacts:
    findings: list[Json]
    analysis_targets: list[Json]
    observations: list[Json]
    debug_targets: list[Json]
    report: Json
    agent_summary: str
    agent_metrics: Json
    meta_readme: str


def threshold_breached(artifacts: ReportArtifacts) -> bool:
    count = artifacts.agent_metrics.get("recommended_edit_tier_count", 0)
    return isinstance(count, int | float) and count > 0


def build_report_artifacts(  # noqa: PLR0913
    config: Config,
    paths: OutputPaths,
    facts: RepositoryFacts,
    signature_artifacts: SignatureArtifacts,
    manifest: Json,
    repository_enrichment: RepositoryEnrichment | None = None,
    semantic_enrichment: SemanticEnrichmentRun | None = None,
    *,
    debug: bool = False,
) -> ReportArtifacts:
    findings: list[Json] = []
    review_targets = build_findings(
        signature_artifacts.clusters,
        facts,
        AssessmentPolicy.from_config(config.data),
        semantic_enrichment,
        signatures=signature_artifacts.records,
    )
    target_payload = review_targets_payload(
        review_targets,
        precision=AssessmentPolicy.from_config(config.data).precision,
    )
    all_targets_detail = as_json_objects(target_payload.get("targets"))
    repository_enrichment = repository_enrichment or RepositoryEnrichment()
    _add_adapter_capability_facts(all_targets_detail, facts, repository_enrichment)
    final_targets_detail = canonical_analysis_targets(all_targets_detail)
    all_analysis_detail, all_observations_detail = partition_analysis_targets(final_targets_detail)
    review_targets_by_id = {target.target_id: target for target in review_targets}
    all_analysis = _agent_payloads_for_details(all_analysis_detail, review_targets_by_id)
    all_observations = _agent_payloads_for_details(all_observations_detail, review_targets_by_id)
    report = build_report(
        config_hash=config.config_hash,
        manifest=manifest,
        findings=findings,
        targets={"targets": final_targets_detail},
        paths=paths,
        adapter_capabilities=adapter_capabilities_payload(repository_enrichment),
        include_debug_bundle=debug,
    )
    metrics = build_metrics(report, all_analysis_detail, all_observations_detail, findings)
    metrics["report_target_count"] = len(final_targets_detail)
    metrics["total_analysis_target_count"] = len(all_analysis)
    metrics["total_observation_count"] = len(all_observations)
    return ReportArtifacts(
        findings=findings,
        analysis_targets=all_analysis,
        observations=all_observations,
        debug_targets=final_targets_detail,
        report=report,
        agent_summary=render_agent_summary(
            report,
            {"targets": final_targets_detail},
            metrics,
            max_targets=_agent_summary_target_limit(config),
        ),
        agent_metrics=metrics,
        meta_readme=render_readme(report, metrics),
    )


def _add_adapter_capability_facts(
    targets: list[Json],
    facts: RepositoryFacts,
    repository_enrichment: RepositoryEnrichment,
) -> None:
    for target in targets:
        payload = target_adapter_capabilities_payload(target, facts, repository_enrichment)
        if payload:
            target["adapter_capabilities"] = payload


def _agent_payloads_for_details(
    details: list[Json],
    review_targets_by_id: dict[str, Finding],
) -> list[Json]:
    payloads: list[Json] = []
    for detail in details:
        target_id = str(detail.get("target_id", ""))
        target = review_targets_by_id.get(target_id)
        if target is None:
            continue
        capabilities = detail.get("adapter_capabilities")
        payloads.append(
            agent_review_target_payload(
                target,
                adapter_capabilities=as_json_objects(capabilities),
            )
        )
    return payloads


def write_report_artifacts(
    paths: OutputPaths,
    artifacts: ReportArtifacts,
    *,
    write_internal: bool = False,
) -> None:
    if write_internal:
        write_jsonl_jsonable_atomic(paths.artifact("findings"), artifacts.debug_targets)
    write_jsonl_jsonable_atomic(
        paths.artifact("agent_analysis"),
        artifacts.analysis_targets,
    )
    write_jsonl_jsonable_atomic(
        paths.artifact("agent_observations"),
        artifacts.observations,
    )
    write_jsonable_atomic(
        paths.artifact("agent_metrics"),
        artifacts.agent_metrics,
        pretty=True,
    )
    write_atomic(
        paths.artifact("agent_summary"),
        artifacts.agent_summary,
    )
    write_atomic(paths.artifact("meta_readme"), artifacts.meta_readme)


def _agent_summary_target_limit(config: Config) -> int | None:
    value = as_json_object(config.data.get("agent_summary")).get("max_targets", 0)
    limit = json_int(value)
    return limit if limit > 0 else None


__all__ = [
    "ReportArtifacts",
    "build_report_artifacts",
    "write_report_artifacts",
]
