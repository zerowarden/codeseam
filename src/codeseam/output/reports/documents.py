from __future__ import annotations

from collections import Counter

from codeseam.analysis import CompletenessSummary, SurfacedFindings
from codeseam.output.reports.template_models import agent_summary_model, readme_model
from codeseam.output.reports.templates import render_template
from codeseam.output.serializers.review import target_review_tier_counts
from codeseam.platform import Json, OutputPaths, as_json_object, as_json_objects, text_list

TOP_REVIEW_TARGETS = 10


def build_report(  # noqa: PLR0913
    *,
    config_hash: str,
    manifest: Json,
    targets: Json,
    paths: OutputPaths,
    adapter_capabilities: list[Json] | None = None,
    include_debug_bundle: bool = False,
) -> Json:
    target_items = as_json_objects(targets.get("targets"))
    summary = _summary(target_items)
    artifact_index = paths.artifact_refs()
    if not include_debug_bundle:
        artifact_index.pop("debug_bundle", None)
    return {
        "schema_version": "codeseam.report.v1",
        "run": {
            "config_hash": config_hash,
            "manifest": manifest,
            "adapter_capabilities": adapter_capabilities or [],
        },
        "summary": summary,
        "top_review_targets": target_items[:TOP_REVIEW_TARGETS],
        "review_target_count": len(target_items),
        "artifact_index": artifact_index,
    }


def build_metrics(
    report: Json, surfaced: SurfacedFindings, completeness: CompletenessSummary | None = None
) -> Json:
    return {
        "completeness": completeness.payload() if completeness else None,
        "schema_version": "codeseam.metrics.v1",
        "summary": as_json_object(report.get("summary")),
        "analysis_target_count": len(surfaced.analysis),
        "observation_count": len(surfaced.observations),
        "agent_visible_target_count": len(surfaced.agent_summary),
        "recommended_edit_tier_count": surfaced.recommended_edit_tier_count,
        "recommended_edit_count": surfaced.recommended_edit_count,
        "report_target_count": len(surfaced.ranked),
        "total_analysis_target_count": len(surfaced.analysis),
        "total_observation_count": len(surfaced.observations),
        "artifact_index": as_json_object(report.get("artifact_index")),
    }


def render_agent_summary(
    report: Json,
    targets: list[Json],
    metrics: Json,
    *,
    max_targets: int | None = None,
) -> str:
    return render_template(
        "agent_summary.md.j2",
        agent_summary_model(report, targets, metrics, max_targets=max_targets),
    )


def render_readme(report: Json, metrics: Json) -> str:
    return render_template("meta_readme.md.j2", readme_model(report, metrics))


def _summary(targets: list[Json]) -> Json:
    return {
        "review_target_count": len(targets),
        "targets_by_review_tier": _counts_by_review_tier(targets),
        "targets_by_action_status": _counts_by_action_status(targets),
        "targets_by_type": dict(Counter(str(target["target_type"]) for target in targets)),
        "files_with_targets": sorted(
            {file for target in targets for file in text_list(target.get("files"))}
        ),
    }


def _counts_by_review_tier(targets: list[Json]) -> dict[str, int]:
    return target_review_tier_counts(targets)


def _counts_by_action_status(targets: list[Json]) -> dict[str, int]:
    return dict(Counter(str(target.get("action_status", "")) for target in targets))
