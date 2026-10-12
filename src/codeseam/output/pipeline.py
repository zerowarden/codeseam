from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from codeseam.adapters.languages import AdapterCapabilitySummary
from codeseam.analysis import (
    Clusters,
    CompletenessSummary,
    Finding,
    RepositoryFacts,
    SignatureAnalysis,
    build_findings,
    surface_findings,
)
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
from codeseam.output.serializers.findings import agent_review_target_payload, review_target_payload
from codeseam.platform import (
    Json,
    OutputPaths,
    write_atomic,
    write_jsonable_atomic,
    write_jsonl_jsonable_atomic,
)
from codeseam.semantics import SemanticEnrichmentRun


@dataclass(frozen=True)
class ReportArtifacts:
    analysis_targets: list[Json]
    observations: list[Json]
    debug_targets: list[Json]
    report: Json
    agent_summary: str
    agent_metrics: Json
    meta_readme: str
    recommended_edit_tier_count: int = 0


def threshold_breached(artifacts: ReportArtifacts) -> bool:
    return artifacts.recommended_edit_tier_count > 0


@dataclass(frozen=True, slots=True)
class ReportInputs:
    """Everything a report is built from; no pipeline types, so output never imports pipeline."""

    config: Config
    paths: OutputPaths
    facts: RepositoryFacts
    clusters: Clusters
    signatures: Sequence[SignatureAnalysis]
    manifest: Json
    adapter_capabilities: tuple[AdapterCapabilitySummary, ...] = ()
    semantic_enrichment: SemanticEnrichmentRun | None = None
    completeness: CompletenessSummary | None = None
    debug: bool = False


def build_report_artifacts(inputs: ReportInputs) -> ReportArtifacts:
    """Assess, decide surfaces on typed findings, then serialize each surface."""

    config = inputs.config
    policy = config.assessment
    surfaced = surface_findings(
        build_findings(
            inputs.clusters,
            inputs.facts,
            policy,
            inputs.semantic_enrichment,
            signatures=inputs.signatures,
        )
    )
    capabilities = {
        finding.target_id: target_adapter_capabilities_payload(
            finding, inputs.facts, inputs.adapter_capabilities
        )
        for finding in surfaced.ranked
    }
    detail = [
        _with_capabilities(
            review_target_payload(finding, precision=policy.precision),
            capabilities[finding.target_id],
        )
        for finding in surfaced.ranked
    ]

    def agent(findings: Sequence[Finding]) -> list[Json]:
        return [
            agent_review_target_payload(
                finding, adapter_capabilities=capabilities[finding.target_id]
            )
            for finding in findings
        ]

    report = build_report(
        config_hash=config.config_hash,
        manifest=inputs.manifest,
        targets={"targets": detail},
        paths=inputs.paths,
        adapter_capabilities=adapter_capabilities_payload(inputs.adapter_capabilities),
        include_debug_bundle=inputs.debug,
    )
    metrics = build_metrics(report, surfaced, inputs.completeness)
    summary_targets = [payload for payload in detail if payload.get("summary_eligible") is True]
    return ReportArtifacts(
        analysis_targets=agent(surfaced.analysis),
        observations=agent(surfaced.observations),
        debug_targets=detail,
        report=report,
        agent_summary=render_agent_summary(
            report,
            summary_targets,
            metrics,
            max_targets=config.agent_summary_max_targets or None,
        ),
        agent_metrics=metrics,
        meta_readme=render_readme(report, metrics),
        recommended_edit_tier_count=surfaced.recommended_edit_tier_count,
    )


def _with_capabilities(payload: Json, capabilities: list[Json]) -> Json:
    if capabilities:
        payload["adapter_capabilities"] = capabilities
    return payload


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


__all__ = [
    "ReportArtifacts",
    "ReportInputs",
    "build_report_artifacts",
    "write_report_artifacts",
]
