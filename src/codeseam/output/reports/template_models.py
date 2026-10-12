from __future__ import annotations

from codeseam.analysis import primary_action
from codeseam.output.serializers.review import target_review_tier
from codeseam.platform import Json, as_json_object, as_json_objects, json_text, text_list

READ_ORDER_KEYS = (
    "agent_summary",
    "agent_metrics",
    "meta_readme",
)


def agent_summary_model(
    report: Json,
    all_agent_targets: list[Json],
    metrics: Json,
    *,
    max_targets: int | None = None,
) -> Json:
    """`all_agent_targets` are the summary-eligible targets, already chosen and ranked."""

    agent_targets = all_agent_targets[:max_targets] if max_targets else all_agent_targets
    resolved_metrics = _metrics_with_review_defaults(metrics)
    summary = _summary_with_review_defaults(as_json_object(report.get("summary")))
    return {
        "summary": summary,
        "metrics": resolved_metrics,
        "listed_target_count": len(agent_targets),
        "omitted_target_count": max(0, len(all_agent_targets) - len(agent_targets)),
        "agent_targets": [
            _agent_target(index, target) for index, target in enumerate(agent_targets, 1)
        ],
        "guardrails": _agent_guardrails(),
        "completeness": as_json_object(metrics.get("completeness")),
    }


def readme_model(report: Json, metrics: Json) -> Json:
    resolved_metrics = _metrics_with_review_defaults(metrics)
    artifact_index = as_json_object(report.get("artifact_index"))
    return {
        "report": report,
        "metrics": resolved_metrics,
        "has_debug_bundle": "debug_bundle" in artifact_index,
        "read_order": _select_artifact_order(artifact_index, READ_ORDER_KEYS),
        "artifact_items": sorted(artifact_index.items(), key=lambda item: str(item[0])),
    }


def _agent_target(index: int, target: Json) -> Json:
    action = primary_action(target) or "inspect evidence before editing"
    primary_scope = _target_action_scope(target)
    not_recommended = _not_recommended_actions(target)
    evidence_classes = ", ".join(text_list(target.get("evidence_classes")))
    relation_kinds = _metric_counts(target, "relation_kind_counts")
    files = _target_file_refs(target)
    return {
        "index": index,
        "target_id": target["target_id"],
        "title": target["title"],
        "review_tier": target_review_tier(target),
        "action_status": target.get("action_status", "observe"),
        "primary_action": target.get("primary_action", action),
        "review_score": target.get("review_score", 0.0),
        "visibility": target.get("visibility", ""),
        "lifecycle_state": _lifecycle_state(target),
        "detection_confidence": target.get("detection_confidence", target["confidence"]),
        "recommendation_confidence": target.get("recommendation_confidence", 0.0),
        "reason": _first_string(target.get("reasons")),
        "evidence_line": _agent_evidence_line(target, evidence_classes, relation_kinds),
        "score_line": _agent_score_line(target),
        "action_line": _agent_action_line(action, primary_scope),
        "do_not_line": ", ".join(not_recommended),
        "files_line": ", ".join(files),
        "inspect_command": f"codeseam explain {target['target_id']}",
    }


def _metrics_with_review_defaults(metrics: Json) -> Json:
    return {
        **metrics,
        "recommended_edit_tier_count": metrics.get("recommended_edit_tier_count", 0),
        "recommended_edit_count": metrics.get("recommended_edit_count", 0),
        "analysis_target_count": metrics.get("analysis_target_count", 0),
    }


def _summary_with_review_defaults(summary: Json) -> Json:
    return {
        **summary,
        "targets_by_review_tier": summary.get("targets_by_review_tier", {}),
        "targets_by_action_status": summary.get("targets_by_action_status", {}),
    }


def _agent_evidence_line(
    target: Json,
    evidence_classes: str,
    relation_kinds: str,
) -> str:
    line = f"strength {target.get('evidence_strength', '')}; classes {evidence_classes}"
    return f"{line}; relations {relation_kinds}" if relation_kinds else line


def _agent_score_line(target: Json) -> str:
    return (
        f"relatedness {target.get('relatedness_score', 0.0)}; "
        f"refactorability {target.get('refactorability_score', 0.0)}; "
        f"cost {target.get('abstraction_cost_score', 0.0)}; "
        f"risk {target.get('risk_score', 0.0)}"
    )


def _agent_action_line(action: str, primary_scope: str) -> str:
    return f"{action} - {primary_scope}" if primary_scope else action


def _target_action_scope(target: Json) -> str:
    return _section_text(target, "refactor_action_summary", "primary_scope")


def _not_recommended_actions(target: Json) -> list[str]:
    summary = target.get("refactor_action_summary", {})
    if not isinstance(summary, dict):
        return []
    return text_list(summary.get("not_recommended"))


def _metric_counts(target: Json, key: str) -> str:
    metrics = target.get("metrics", {})
    if not isinstance(metrics, dict):
        return ""
    value = metrics.get(key, {})
    if not isinstance(value, dict):
        return ""
    return ", ".join(
        f"{name}:{count}" for name, count in sorted(value.items(), key=lambda item: str(item[0]))
    )


def _target_file_refs(target: Json) -> list[str]:
    refs = _primary_action_file_refs(target)
    if refs:
        return refs

    refs = []
    for location in as_json_objects(target.get("locations"))[:3]:
        if not isinstance(location, dict):
            continue
        refs.append(_member_ref(location))
    return refs or text_list(target.get("files"))[:3]


def _primary_action_file_refs(target: Json) -> list[str]:
    action = primary_action(target) or "inspect evidence before editing"
    actions = target.get("refactor_action_candidates", [])
    if not isinstance(actions, list):
        return []

    for candidate in actions:
        if not isinstance(candidate, dict) or str(candidate.get("kind", "")) != action:
            continue
        if candidate.get("status") == "not_recommended":
            continue
        members = candidate.get("applies_to", [])
        if isinstance(members, list):
            refs = [_member_ref(member) for member in members[:3] if isinstance(member, dict)]
            return [ref for ref in refs if ref]
    return []


def _member_ref(member: Json) -> str:
    path = str(member.get("file", ""))
    if not path:
        return ""
    start_line = member.get("start_line", "")
    end_line = member.get("end_line", start_line)
    symbol = str(member.get("symbol", ""))
    location = f"{path}:{start_line}-{end_line}" if start_line else path
    return f"{location} {symbol}" if symbol else location


def _first_string(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return ""


def _agent_guardrails() -> list[str]:
    return [
        "Do not refactor solely because signatures match.",
        "Do not assume structural or lexical similarity proves behavior.",
        "Prefer small pure helpers over framework-style abstractions.",
        "Use `codeseam explain <id>` before editing a target not listed above.",
    ]


def _lifecycle_state(target: Json) -> str:
    return _section_text(target, "lifecycle", "state", "new")


def _section_text(
    target: Json,
    section: str,
    key: str,
    default: str = "",
) -> str:
    return json_text(as_json_object(target.get(section)), key, default)


def _select_artifact_order(artifact_refs: Json, keys: tuple[str, ...]) -> list[str]:
    return [str(artifact_refs[key]) for key in keys if isinstance(artifact_refs.get(key), str)]
